"""Envoy write-verification tripwire.

Reads-only oracle-vs-commanded reconciliation for three battery-strategy
surfaces (reserve_soc, charge_from_grid, storage_mode). NEVER actuates
(invariant W-6 — see PLANNING_envoy_write_verification_and_redundancy.md).

Covers three operator-observed failure shapes:
  (a) local write rejected on dispatch tick
  (b) accepted locally but never propagates to the cloud (primary target)
  (c) applied then silently reverted at any later tick

Emits AnomalyEvent + optional Notification-Manager CRITICAL alerts. NM
alerts are latched per-surface once per day to avoid spam.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_call_later
from homeassistant.util import dt as dt_util

from .energy_const import (
    DEFAULT_WRITE_VERIFY_WINDOW_S,
    STORAGE_MODE_CLOUD_TO_LOCAL,
    WRITE_VERIFY_NM_SURFACES,
    WRITE_VERIFY_SURFACE_CHARGE_FROM_GRID,
    WRITE_VERIFY_SURFACE_RESERVE,
    WRITE_VERIFY_SURFACE_STORAGE_MODE,
)

if TYPE_CHECKING:
    from .energy import EnergyCoordinator

_LOGGER = logging.getLogger(__name__)


STATUS_OK = "ok"
STATUS_MISMATCH = "mismatch"
STATUS_REVERTED = "reverted"
STATUS_INCONCLUSIVE = "inconclusive"
STATUS_UNMAPPED = "unmapped"
STATUS_NO_DATA = "no_data"
STATUS_UNIT_MISMATCH = "unit_mismatch"


def _normalize_percent(
    raw: Any, unit: Optional[str]
) -> tuple[Optional[float], bool]:
    """Normalize a numeric reading intended to be a percentage.

    Returns ``(value_or_none, is_percent_unit)``. Accepts:
      - "%" or None (assume %) → returned as-is
      - fractional 0-1 → multiplied by 100 (with is_percent_unit=False so
        the caller may flag a wiring/units anomaly)
    """
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None, False
    u = (unit or "").strip()
    if u in ("", "%"):
        return v, True
    # Unknown unit — return the value but mark as non-percent so the
    # caller can flag it as a distinct WIRING anomaly (not "reverted").
    return v, False


@dataclass
class _VerifyRecord:
    """Last outcome per surface for the diagnostic attrs."""

    commanded: Any = None
    oracle_seen: Any = None
    verified_at: Optional[str] = None
    status: str = STATUS_NO_DATA
    # Rider (2026-07-13, B-LOW-2 close): True iff this record was
    # rehydrated from KV on restart. Surfaced verbatim in the
    # `last_verified_write_*` display attr so operators can distinguish
    # a pre-restart verified outcome from a post-restart fresh one.
    # Timestamps (`verified_at`) are PRESERVED across restore so age
    # renders honestly. Cleared as soon as `_check` writes a fresh
    # outcome to this surface (the RAM record is replaced wholesale).
    restored: bool = False


@dataclass
class _MismatchCounts:
    """Rolling 24h mismatch counts per surface."""

    counts: dict[str, list[datetime]] = field(default_factory=dict)

    def increment(self, surface: str) -> None:
        self.counts.setdefault(surface, []).append(dt_util.utcnow())

    def value(self, surface: str) -> int:
        cutoff = dt_util.utcnow() - timedelta(hours=24)
        arr = self.counts.get(surface, [])
        # prune
        arr[:] = [t for t in arr if t >= cutoff]
        return len(arr)


class WriteVerifier:
    """Schedule, wait, compare — the delayed reconciliation loop.

    Reused pattern: ``ComplianceTracker.schedule_check`` at
    ``coordinator_diagnostics.py:352`` — same "schedule a delayed compare,
    emit an anomaly on mismatch" shape. This class is a battery-write
    specialization with a 15-min window (vs Compliance's 2 min) and a
    per-surface NM trip latch (reuses the pattern at
    ``energy.py:317`` — ``_fill_priority_nm_trip_date``).
    """

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: "EnergyCoordinator",
        verify_window_s: int = DEFAULT_WRITE_VERIFY_WINDOW_S,
    ) -> None:
        self.hass = hass
        self._coord = coordinator
        self._verify_window_s = int(verify_window_s)
        # Per-surface last verified outcome (RAM only; attrs surface it).
        self._records: dict[str, _VerifyRecord] = {
            s: _VerifyRecord() for s in WRITE_VERIFY_NM_SURFACES
        }
        # Per-surface NM trip latch — ISO date string (YYYY-MM-DD).
        self._nm_trip_date_by_surface: dict[str, str] = {}
        # Rolling 24h mismatch counters.
        self._mismatch_counts = _MismatchCounts()
        # Reversion coalesce — one anomaly per standing reversion per surface.
        self._last_reversion_at_by_surface: dict[str, datetime] = {}
        # Once-per-boot INFO log for disabled surfaces (no oracle configured).
        self._disabled_logged: set[str] = set()
        # Fix-up A/B-HIGH-1 — per-surface pending-check cancel handle.
        # schedule() cancels prior handle before scheduling; cancel_all()
        # (Fix-up B-HIGH-3, Bug Class #38) cancels all on teardown.
        self._pending_by_surface: dict[str, Any] = {}
        # Fix-up A-MED-1 fallback log throttling.
        self._last_soc_fallback_state: Optional[str] = None
        # Review B-H1-1 (2026-07-13) — track the commanded value each
        # surface's pending check is waiting on. If the SAME value is
        # re-dispatched (self-heal loop against a persistently uncooperative
        # cloud leg), we let the existing check mature rather than
        # cancel+reschedule forever (which starves the 15-min compare).
        self._pending_commanded_by_surface: dict[str, Any] = {}
        # Review B-H1-1 — per-surface count of consecutive self-heal
        # re-dispatches (same value). At N=3 we emit a
        # write_verification_failed-class anomaly + fire NM (once/day latch)
        # so the alarm is not maskable by the heal loop even if no check
        # ever matures.
        self._self_heal_consecutive: dict[str, int] = {}
        # Review A-MED-1 = B-H1-2 — per-surface count of consecutive
        # cycles where the cloud (write) target read unavailable/unknown.
        # At N=3 we hold, emit a once/day "cloud write leg unavailable"
        # anomaly + fire NM, and only retry at a 6-cycle backoff.
        self._unavailable_consecutive: dict[str, int] = {}
        self._unavailable_backoff_ticks: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Cloud oracle entity id resolution (respects operator overrides)
    # ------------------------------------------------------------------
    def _oracle_entity_for(self, surface: str) -> Optional[str]:
        """Resolve cloud-oracle entity id for a surface via battery
        strategy's ``_get_entity`` choke point.

        Uses new logical keys wired into ``_build_entity_map`` and
        default constants from ``energy_const``.
        """
        try:
            battery = getattr(self._coord, "_battery", None)
            if battery is None:
                return None
            from .energy_const import (
                DEFAULT_CLOUD_CHARGE_FROM_GRID_ORACLE_ENTITY,
                DEFAULT_CLOUD_RESERVE_ORACLE_ENTITY,
                DEFAULT_CLOUD_STORAGE_MODE_ORACLE_ENTITY,
            )
            key_map = {
                WRITE_VERIFY_SURFACE_RESERVE: (
                    "cloud_reserve_oracle",
                    DEFAULT_CLOUD_RESERVE_ORACLE_ENTITY,
                ),
                WRITE_VERIFY_SURFACE_CHARGE_FROM_GRID: (
                    "cloud_charge_from_grid_oracle",
                    DEFAULT_CLOUD_CHARGE_FROM_GRID_ORACLE_ENTITY,
                ),
                WRITE_VERIFY_SURFACE_STORAGE_MODE: (
                    "cloud_storage_mode_oracle",
                    DEFAULT_CLOUD_STORAGE_MODE_ORACLE_ENTITY,
                ),
            }
            key, default = key_map.get(surface, (None, None))
            if key is None:
                return None
            return battery._get_entity(key, default)  # noqa: SLF001
        except Exception:  # noqa: BLE001
            _LOGGER.debug("oracle entity resolution failed", exc_info=True)
            return None

    def _local_entity_for(self, surface: str) -> Optional[str]:
        """H1 (2026-07-13) — resolve LOCAL (Envoy/Enpower) entity id for
        a surface as the SECONDARY WITNESS under cloud-first writes.

        Under cloud-first writes, the cloud oracle reflects the APPLIED
        state (with lag). The local entity is what the on-house gateway
        actually shows; when local and cloud disagree beyond the verify
        window, that's the "gateway didn't hear it" signal — distinct
        from a cloud-side reversion. Storage_mode is currently excluded
        (local `select.enpower_*_storage_mode` values may differ in
        vocabulary; a future fix-up can extend witness coverage).
        """
        try:
            battery = getattr(self._coord, "_battery", None)
            if battery is None:
                return None
            from .energy_const import (
                DEFAULT_CHARGE_FROM_GRID_ENTITY,
                DEFAULT_RESERVE_SOC_ENTITY,
                DEFAULT_STORAGE_MODE_ENTITY,
            )
            key_map = {
                WRITE_VERIFY_SURFACE_RESERVE: (
                    "reserve_soc_number",
                    DEFAULT_RESERVE_SOC_ENTITY,
                ),
                WRITE_VERIFY_SURFACE_CHARGE_FROM_GRID: (
                    "charge_from_grid",
                    DEFAULT_CHARGE_FROM_GRID_ENTITY,
                ),
                WRITE_VERIFY_SURFACE_STORAGE_MODE: (
                    "storage_mode",
                    DEFAULT_STORAGE_MODE_ENTITY,
                ),
            }
            key, default = key_map.get(surface, (None, None))
            if key is None:
                return None
            # Pass role="read" so the failover flag DOES NOT redirect us
            # back to the cloud entity — we want the raw local leg here.
            return battery._get_entity(key, default, role="read")  # noqa: SLF001
        except Exception:  # noqa: BLE001
            _LOGGER.debug("local entity resolution failed", exc_info=True)
            return None

    # ------------------------------------------------------------------
    # Schedule (called from dispatch tap in energy.py)
    # ------------------------------------------------------------------
    async def schedule(
        self,
        surface: str,
        commanded_value: Any,
        commanded_at: Optional[datetime] = None,
    ) -> None:
        """Schedule a delayed verification check for a commanded write.

        Never raises. If the surface has no oracle configured, logs once
        at INFO and returns cleanly (disabled per operator).
        """
        if surface not in WRITE_VERIFY_NM_SURFACES:
            _LOGGER.debug("WriteVerifier: unknown surface %s", surface)
            return

        oracle = self._oracle_entity_for(surface)
        if not oracle:
            if surface not in self._disabled_logged:
                _LOGGER.info(
                    "WriteVerifier: %s verification DISABLED "
                    "(no cloud oracle entity configured)",
                    surface,
                )
                self._disabled_logged.add(surface)
            return

        commanded_at = commanded_at or dt_util.utcnow()

        # Review A-MED-1 = B-H1-2 (2026-07-13) — unavailable-cloud
        # re-dispatch loop guard. If the cloud (write) target reads
        # unavailable/unknown/None, we must NOT re-dispatch every cycle
        # indefinitely. N-strike (3 consecutive cycles) then hold with a
        # once-per-day anomaly + NM alert; retry at a 6-cycle backoff.
        # Applies uniformly to reserve, charge_from_grid, storage_mode.
        oracle_probe = self._read_oracle_raw(oracle)
        if oracle_probe is None:
            n = self._unavailable_consecutive.get(surface, 0) + 1
            self._unavailable_consecutive[surface] = n
            backoff = self._unavailable_backoff_ticks.get(surface, 0)
            if n >= 3:
                # Backoff: only retry (schedule a check) every 6th cycle
                # after tripping the N-strike threshold.
                if backoff <= 0:
                    self._unavailable_backoff_ticks[surface] = 6
                    await self._emit_anomaly(
                        surface,
                        "cloud_write_leg_unavailable",
                        {
                            "commanded": commanded_value,
                            "consecutive_unavailable": n,
                        },
                    )
                    await self._maybe_fire_nm(
                        surface,
                        title=f"Cloud write leg unavailable: {surface}",
                        message=(
                            f"URA has attempted to dispatch {surface}="
                            f"{commanded_value!r} for {n} consecutive cycles "
                            "but the cloud write leg reads unavailable. "
                            "Verification is on backoff."
                        ),
                        alert_type="cloud_write_leg_unavailable",
                    )
                else:
                    self._unavailable_backoff_ticks[surface] = backoff - 1
                _LOGGER.debug(
                    "WriteVerifier: %s cloud target unavailable "
                    "(consecutive=%d, backoff=%d) — schedule suppressed",
                    surface, n,
                    self._unavailable_backoff_ticks[surface],
                )
                return
            _LOGGER.debug(
                "WriteVerifier: %s cloud target unavailable "
                "(consecutive=%d) — scheduling anyway (pre-N-strike)",
                surface, n,
            )
        else:
            # Cloud is healthy — reset counters.
            self._unavailable_consecutive[surface] = 0
            self._unavailable_backoff_ticks[surface] = 0

        # Review B-H1-1 (2026-07-13) — supersession starvation fix.
        # When a pending check exists for THE SAME commanded value, do
        # NOT cancel+reschedule. The 5-min self-heal loop otherwise
        # re-dispatches the same command every cycle and starves the
        # 15-min check forever. Instead: let the existing check mature,
        # count consecutive self-heals, and at N=3 emit an
        # unmaskable-by-heal-loop anomaly + NM (once/day). A DIFFERENT
        # commanded value is a legitimate fresh command and still
        # supersedes (cancels the stale check).
        prior_commanded = self._pending_commanded_by_surface.get(surface)
        prior = self._pending_by_surface.get(surface)
        if prior is not None and prior_commanded == commanded_value:
            # Same-value self-heal — count it, maybe raise the alarm,
            # then return WITHOUT cancelling or rescheduling. The
            # in-flight check will mature and reset the counter on OK.
            n = self._self_heal_consecutive.get(surface, 0) + 1
            self._self_heal_consecutive[surface] = n
            _LOGGER.debug(
                "WriteVerifier: %s same-value self-heal "
                "(commanded=%s, count=%d) — leaving pending check to mature",
                surface, commanded_value, n,
            )
            if n >= 3:
                await self._emit_anomaly(
                    surface,
                    "write_verification_failed",
                    {
                        "commanded": commanded_value,
                        "reason": "self_heal_starvation",
                        "consecutive_self_heals": n,
                    },
                )
                await self._maybe_fire_nm(
                    surface,
                    title=f"Envoy write self-heal loop: {surface}",
                    message=(
                        f"URA has re-dispatched {surface}={commanded_value!r} "
                        f"{n} consecutive cycles without cloud confirmation. "
                        "The write leg may be silently rejecting writes."
                    ),
                    alert_type="self_heal_starvation",
                )
            return

        # Fresh command (different value) or no prior — cancel any
        # pending check for this surface BEFORE scheduling a new one.
        # A stale in-flight check that fires after a fresh command would
        # compare cloud state against the OLD commanded value, producing
        # a spurious mismatch. Also captures the cancel callback
        # (pre-fix-up: discarded → timer leak on teardown, Bug Class #38).
        prior = self._pending_by_surface.pop(surface, None)
        self._pending_commanded_by_surface.pop(surface, None)
        # Reset self-heal counter on a legitimate fresh command.
        self._self_heal_consecutive[surface] = 0
        if prior is not None:
            try:
                prior()
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "WriteVerifier: cancel prior %s handle failed (swallowed)",
                    surface, exc_info=True,
                )

        async def _delayed(_now: Any = None) -> None:
            # Clear own handle before running compare (self is complete now).
            self._pending_by_surface.pop(surface, None)
            self._pending_commanded_by_surface.pop(surface, None)
            try:
                await self._check(surface, commanded_value, commanded_at)
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "WriteVerifier delayed check raised (swallowed)",
                    exc_info=True,
                )

        try:
            handle = async_call_later(
                self.hass, self._verify_window_s, _delayed
            )
            # Capture cancel callback for supersession + teardown.
            self._pending_by_surface[surface] = handle
            self._pending_commanded_by_surface[surface] = commanded_value
            _LOGGER.debug(
                "WriteVerifier: scheduled %s verify (commanded=%s) in %ds",
                surface, commanded_value, self._verify_window_s,
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "WriteVerifier: schedule failed (swallowed)",
                exc_info=True,
            )

    # ------------------------------------------------------------------
    # Compare (delayed callback body)
    # ------------------------------------------------------------------
    async def _check(
        self,
        surface: str,
        commanded_value: Any,
        commanded_at: datetime,
    ) -> None:
        """Perform the compare + emit any anomalies. Never actuates (W-6)."""
        # Fix-up A/B-HIGH-1 belt: even if cancel was raced, early-return
        # when the commanded ledger has advanced past our commanded_at.
        try:
            battery = getattr(self._coord, "_battery", None)
            if battery is not None:
                _, ledger_at = self._commanded_ledger(battery, surface)
                if ledger_at is not None and ledger_at > commanded_at:
                    _LOGGER.debug(
                        "WriteVerifier: %s check superseded "
                        "(ledger=%s > commanded_at=%s)",
                        surface, ledger_at, commanded_at,
                    )
                    return
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "supersession guard raised (swallowed)", exc_info=True,
            )
        oracle = self._oracle_entity_for(surface)
        if not oracle:
            return
        oracle_raw = self._read_oracle_raw(oracle)
        rec = self._records[surface]

        if oracle_raw is None:
            rec.commanded = commanded_value
            rec.oracle_seen = None
            rec.verified_at = dt_util.utcnow().isoformat()
            rec.status = STATUS_INCONCLUSIVE
            _LOGGER.debug(
                "WriteVerifier: %s inconclusive (oracle unavailable)",
                surface,
            )
            return

        oracle_unit = self._read_oracle_unit(oracle)
        status, matched = self._compare(
            surface, commanded_value, oracle_raw, oracle_unit,
        )
        rec.commanded = commanded_value
        rec.oracle_seen = oracle_raw
        rec.verified_at = dt_util.utcnow().isoformat()
        rec.status = status

        if status == STATUS_UNMAPPED:
            await self._emit_anomaly(
                surface,
                "write_verification_unmapped_mode",
                {"commanded": commanded_value, "oracle_seen": oracle_raw},
            )
            _LOGGER.warning(
                "WriteVerifier: %s unmapped oracle value %r — "
                "verification inconclusive",
                surface, oracle_raw,
            )
            return
        if status == STATUS_UNIT_MISMATCH:
            # Distinct WIRING bug class — NEVER alert as a reverted write.
            await self._emit_anomaly(
                surface,
                "write_verification_unit_mismatch",
                {
                    "commanded": commanded_value,
                    "oracle_seen": oracle_raw,
                    "oracle_unit": oracle_unit,
                },
            )
            _LOGGER.warning(
                "WriteVerifier: %s WIRING/units mismatch — commanded %s vs "
                "oracle %s (unit=%r). Likely factor-of-1000 or sign-convention "
                "wiring bug, not a real cloud reversion. Fix the integration "
                "before treating this as a verification failure.",
                surface, commanded_value, oracle_raw, oracle_unit,
            )
            return

        if status == STATUS_OK or matched:
            # Reset self-heal + unavailable counters — cloud confirmed
            # the write (Review B-H1-1 / A-MED-1).
            self._self_heal_consecutive[surface] = 0
            self._unavailable_consecutive[surface] = 0
            self._unavailable_backoff_ticks[surface] = 0
            _LOGGER.info(
                "WriteVerifier: %s OK (commanded=%s, oracle=%s)",
                surface, commanded_value, oracle_raw,
            )
            return

        # MISMATCH
        self._mismatch_counts.increment(surface)
        await self._emit_anomaly(
            surface,
            "write_verification_failed",
            {"commanded": commanded_value, "oracle_seen": oracle_raw},
        )
        _LOGGER.warning(
            "WriteVerifier: %s MISMATCH (commanded=%s, oracle=%s)",
            surface, commanded_value, oracle_raw,
        )
        await self._maybe_fire_nm(
            surface,
            title=f"Envoy write not applied: {surface}",
            message=(
                f"Commanded {surface}={commanded_value!r} but Enphase cloud "
                f"reports {oracle_raw!r} after {self._verify_window_s}s. "
                "Check the Enpower device link."
            ),
            alert_type="mismatch",
        )

    # ------------------------------------------------------------------
    # Reversion sweep — called from _async_decision_cycle tail
    # ------------------------------------------------------------------
    async def reversion_sweep(self) -> None:
        """Detect shape-(c) silent reversion for each surface. Never actuates.

        For each surface where URA has previously commanded a value AND that
        commanded_at is older than verify_window_s AND no new command has
        been dispatched since, compare the cloud oracle to the last
        commanded value. If they differ, emit ``write_reverted`` and
        NM-latch once per day. Coalesce so a standing-reverted state does
        not spam every 5 min.
        """
        try:
            battery = getattr(self._coord, "_battery", None)
            if battery is None:
                return
            for surface in WRITE_VERIFY_NM_SURFACES:
                await self._sweep_surface(battery, surface)
        except Exception:  # noqa: BLE001
            _LOGGER.debug("reversion_sweep raised (swallowed)", exc_info=True)

    async def _sweep_surface(self, battery: Any, surface: str) -> None:
        commanded, commanded_at = self._commanded_ledger(battery, surface)
        if commanded is None or commanded_at is None:
            return
        window = timedelta(seconds=self._verify_window_s)
        now = dt_util.utcnow()
        if (now - commanded_at) < window:
            return  # Still inside the initial verify window
        oracle = self._oracle_entity_for(surface)
        if not oracle:
            return
        oracle_raw = self._read_oracle_raw(oracle)
        if oracle_raw is None:
            return  # inconclusive read; skip silently
        oracle_unit = self._read_oracle_unit(oracle)
        status, matched = self._compare(
            surface, commanded, oracle_raw, oracle_unit,
        )
        if status == STATUS_UNIT_MISMATCH:
            # WIRING bug — do NOT treat as reverted. Log + emit distinct
            # anomaly, do not fire NM.
            await self._emit_anomaly(
                surface,
                "write_verification_unit_mismatch",
                {
                    "commanded": commanded,
                    "oracle_seen": oracle_raw,
                    "oracle_unit": oracle_unit,
                },
            )
            _LOGGER.warning(
                "WriteVerifier: %s WIRING/units mismatch during reversion "
                "sweep (commanded=%s oracle=%s unit=%r) — NOT alerting as "
                "reverted.",
                surface, commanded, oracle_raw, oracle_unit,
            )
            return
        if status == STATUS_UNMAPPED or matched:
            # Successful verified — reset coalesce so a future flip re-fires.
            self._last_reversion_at_by_surface.pop(surface, None)
            # H1 (2026-07-13) — SECONDARY WITNESS. Under cloud-first
            # writes, cloud is the primary write leg + oracle. The LOCAL
            # entity is now an independent witness: if cloud shows APPLIED
            # but local disagrees beyond the verify window, that's the
            # "gateway didn't hear it" signal (distinct from a real
            # reversion). Emit an anomaly (never NM-critical) so ops has
            # a durable record without noise.
            try:
                await self._witness_compare(surface, commanded)
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "witness compare raised (swallowed)", exc_info=True,
                )
            return
        # Fix-up B-MED-2 — emit ONCE per TRANSITION into REVERTED, not
        # per verify-window tick. DB write-flood history (v5.0.0-v5.2.1
        # rollback) mandates that a standing-reverted state does not
        # generate a new anomaly row every 15 min. NM is separately
        # latched per-day by _maybe_fire_nm; the anomaly bus needs the
        # tighter guard.
        rec = self._records[surface]
        was_reverted = (rec.status == STATUS_REVERTED)
        rec.commanded = commanded
        rec.oracle_seen = oracle_raw
        rec.verified_at = now.isoformat()
        rec.status = STATUS_REVERTED
        # Always keep the coalesce timestamp fresh (for legacy reads).
        self._last_reversion_at_by_surface[surface] = now
        if was_reverted:
            _LOGGER.debug(
                "WriteVerifier: %s still REVERTED (coalesced, no re-emit)",
                surface,
            )
            return
        self._mismatch_counts.increment(surface)
        await self._emit_anomaly(
            surface,
            "write_reverted",
            {"commanded": commanded, "oracle_seen": oracle_raw},
        )
        _LOGGER.warning(
            "WriteVerifier: %s REVERTED (commanded=%s, oracle=%s)",
            surface, commanded, oracle_raw,
        )
        await self._maybe_fire_nm(
            surface,
            title=f"Envoy write reverted: {surface}",
            message=(
                f"URA commanded {surface}={commanded!r} earlier, but the "
                f"Enphase cloud now reports {oracle_raw!r} with no "
                "intervening URA command. Someone or something else changed "
                "it. Check the Enphase app."
            ),
            alert_type="reverted",
        )

    async def _witness_compare(self, surface: str, commanded: Any) -> None:
        """H1 (2026-07-13) — secondary-witness compare (local vs commanded).

        Only meaningful under cloud-first writes: cloud already matched
        as PRIMARY oracle; if the LOCAL entity disagrees, that's the
        gateway-didn't-hear-it signal. Emits a distinct anomaly type
        (``write_local_witness_divergence``), never NM-critical.
        Reserve + charge_from_grid only — storage_mode witness is
        deferred pending local-vocab audit (see _local_entity_for).
        """
        if surface == WRITE_VERIFY_SURFACE_STORAGE_MODE:
            return
        local_eid = self._local_entity_for(surface)
        if not local_eid:
            return
        local_raw = self._read_oracle_raw(local_eid)
        if local_raw is None:
            return  # local unavailable — inconclusive, skip silently
        local_unit = self._read_oracle_unit(local_eid)
        status, matched = self._compare(
            surface, commanded, local_raw, local_unit,
        )
        if status == STATUS_UNIT_MISMATCH:
            # Unit mismatch on the LOCAL leg is a separate wiring
            # concern; not the witness-divergence case. Skip.
            return
        if matched or status == STATUS_UNMAPPED:
            return
        # Local disagrees with commanded (which cloud already confirmed).
        # This is the gateway-didn't-hear-it condition.
        await self._emit_anomaly(
            surface,
            "write_local_witness_divergence",
            {
                "commanded": commanded,
                "local_seen": local_raw,
            },
        )
        _LOGGER.info(
            "WriteVerifier: %s LOCAL WITNESS DIVERGENCE "
            "(commanded=%s, local=%s) — cloud OK, gateway may not have "
            "propagated the write yet",
            surface, commanded, local_raw,
        )

    def _commanded_ledger(
        self, battery: Any, surface: str
    ) -> tuple[Any, Optional[datetime]]:
        """Read the last-commanded (value, timestamp) for a surface."""
        if surface == WRITE_VERIFY_SURFACE_RESERVE:
            return (
                getattr(battery, "_last_reserve_level", None),
                getattr(battery, "_last_reserve_level_at", None),
            )
        if surface == WRITE_VERIFY_SURFACE_CHARGE_FROM_GRID:
            return (
                getattr(battery, "_last_charge_from_grid_command", None),
                getattr(battery, "_last_charge_from_grid_command_at", None),
            )
        if surface == WRITE_VERIFY_SURFACE_STORAGE_MODE:
            return (
                getattr(battery, "_last_storage_mode_command", None),
                getattr(battery, "_last_storage_mode_command_at", None),
            )
        return (None, None)

    # ------------------------------------------------------------------
    # Read + compare helpers
    # ------------------------------------------------------------------
    def _read_oracle_raw(self, entity_id: str) -> Any:
        """Read oracle state. None on unavailable/unknown/missing/error."""
        try:
            st = self.hass.states.get(entity_id)
            if st is None or st.state in ("unavailable", "unknown", None):
                return None
            return st.state
        except Exception:  # noqa: BLE001
            return None

    def _read_oracle_unit(self, entity_id: str) -> Optional[str]:
        """Read the oracle entity's ``unit_of_measurement`` attribute.

        Cross-source unit vigilance — never assume; honor what the
        integration reports. Returns None if not available.
        """
        try:
            st = self.hass.states.get(entity_id)
            if st is None:
                return None
            return st.attributes.get("unit_of_measurement")
        except Exception:  # noqa: BLE001
            return None

    def _compare(
        self,
        surface: str,
        commanded: Any,
        oracle_raw: Any,
        oracle_unit: Optional[str] = None,
    ) -> tuple[str, bool]:
        """Return (status, matched_bool).

        matched=True means the oracle reflects the commanded value.
        status=STATUS_UNMAPPED when the oracle returned a value not in the
        local↔cloud map (storage_mode only) — treat as inconclusive.
        status=STATUS_UNIT_MISMATCH when a numeric compare shows a
        ~factor-of-1000 disagreement (WIRING bug, not a reversion).
        Units are read from oracle_unit and honored; never assumed.
        """
        try:
            if surface == WRITE_VERIFY_SURFACE_RESERVE:
                cval = float(commanded) if commanded is not None else None
                oval_norm, is_percent = _normalize_percent(oracle_raw, oracle_unit)
                if cval is None or oval_norm is None:
                    return STATUS_INCONCLUSIVE, False
                # Factor-of-1000 guard (0-100 vs 0-100000 / 0.0-1.0).
                # Distinct anomaly — never alert as reverted.
                if cval > 0 and (
                    oval_norm / cval > 500 or (cval / oval_norm > 500 if oval_norm > 0 else False)
                ):
                    return STATUS_UNIT_MISMATCH, False
                if not is_percent:
                    return STATUS_UNIT_MISMATCH, False
                # Fix-up A-HIGH-2 / B-MED-1: align verify tolerance with
                # the ±2 dispatch deadband. A 1.0-pt tolerance produced a
                # "1<delta<2" forever-REVERTED band because dispatch would
                # not re-send (deadband) yet verify would keep failing.
                matched = abs(oval_norm - cval) <= 2.0
                return (STATUS_OK if matched else STATUS_MISMATCH, matched)
            if surface == WRITE_VERIFY_SURFACE_CHARGE_FROM_GRID:
                cbool = bool(commanded)
                obool = str(oracle_raw).lower() == "on"
                matched = (cbool == obool)
                return (STATUS_OK if matched else STATUS_MISMATCH, matched)
            if surface == WRITE_VERIFY_SURFACE_STORAGE_MODE:
                if str(oracle_raw) not in STORAGE_MODE_CLOUD_TO_LOCAL:
                    # Not in the known map — inconclusive (never alert).
                    return STATUS_UNMAPPED, False
                normalized = STORAGE_MODE_CLOUD_TO_LOCAL[str(oracle_raw)]
                matched = (str(commanded) == normalized)
                return (STATUS_OK if matched else STATUS_MISMATCH, matched)
        except (TypeError, ValueError):
            return STATUS_INCONCLUSIVE, False
        return STATUS_INCONCLUSIVE, False

    # ------------------------------------------------------------------
    # Anomaly emit + NM latch
    # ------------------------------------------------------------------
    async def _emit_anomaly(
        self, surface: str, type_str: str, extra: dict[str, Any]
    ) -> None:
        """Emit AnomalyEvent via existing bus. Never raises."""
        try:
            from ..const import DOMAIN  # noqa: PLC0415
            from .anomaly_event import (  # noqa: PLC0415
                AnomalyEvent,
                AnomalySeverity,
                AnomalyType,
                build_context_json,
            )
            payload = build_context_json(
                source_signal="write_verify",
                extra={"surface": surface, **extra},
            )
            event = AnomalyEvent(
                coordinator="energy",
                type=type_str,
                severity=AnomalySeverity.WARNING,
                anomaly_type=AnomalyType.POINT_IN_TIME,
                detected_at=dt_util.utcnow().isoformat(),
                payload=payload,
                entity_id=self._oracle_entity_for(surface),
            )
            database = self.hass.data.get(DOMAIN, {}).get("database")
            if database is not None:
                await database.save_anomaly_event(event)
        except Exception:  # noqa: BLE001
            _LOGGER.debug("_emit_anomaly failed (swallowed)", exc_info=True)

    async def _maybe_fire_nm(
        self, surface: str, title: str, message: str,
        alert_type: str = "mismatch",
    ) -> None:
        """Fire NM CRITICAL once per (surface, alert_type) per calendar day.

        Fix-up B-MED-3: latch is per (surface, alert_type) so that a
        mismatch alert and a subsequent reversion alert on the SAME
        surface do not share a latch — they represent distinct operator
        events and each deserves at most one notification per day.
        """
        today = dt_util.utcnow().date().isoformat()
        key = f"{surface}:{alert_type}"
        if self._nm_trip_date_by_surface.get(key) == today:
            _LOGGER.debug(
                "WriteVerifier: %s/%s NM alert suppressed "
                "(already fired today)",
                surface, alert_type,
            )
            return
        try:
            send = getattr(self._coord, "_send_nm_alert", None)
            if send is not None:
                await send(
                    title=title,
                    message=message,
                    severity="critical",
                    hazard_type="envoy_write_verification",
                    location="battery",
                )
            self._nm_trip_date_by_surface[key] = today
        except Exception:  # noqa: BLE001
            _LOGGER.debug("NM alert failed (swallowed)", exc_info=True)

    # ------------------------------------------------------------------
    # Teardown (Fix-up B-HIGH-3, Bug Class #38 — timer leaks)
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Rider (2026-07-13, B-LOW-2 close) — persist/restore _records
    # ------------------------------------------------------------------
    def dump_records_for_persist(self) -> dict[str, dict[str, Any]]:
        """Serialize per-surface `_records` for KV persistence.

        Called from EnergyCoordinator `_save_evse_state` (existing 15-min
        cadence + teardown — no new timer, Bug Class #19/#42). Preserves
        `verified_at` VERBATIM so age renders honestly after restore.
        """
        out: dict[str, dict[str, Any]] = {}
        for surface, rec in self._records.items():
            out[surface] = {
                "commanded": rec.commanded,
                "oracle_seen": rec.oracle_seen,
                "verified_at": rec.verified_at,
                "status": rec.status,
            }
        return out

    def restore_records_from_persist(
        self, payload: dict[str, Any]
    ) -> None:
        """Rehydrate `_records` from KV payload.

        Semantics:
          - Only surfaces still in NO_DATA state are rehydrated (do NOT
            clobber a post-boot fresh outcome).
          - `verified_at` is preserved as-is (original pre-restart ISO).
          - `restored=True` is set so `get_status_attrs()` surfaces the
            provenance.

        Supersession safety: restored `verified_at` is display-only.
        `_check`'s supersession guard compares the COMMANDED ledger
        (`_last_*_at` on battery), NOT `verified_at`. Restored commanded
        ledger keeps its OLD timestamp, so a fresh post-boot dispatch
        (newer commanded_at) cannot be false-superseded by the restored
        ledger.
        """
        if not isinstance(payload, dict):
            return
        for surface in WRITE_VERIFY_NM_SURFACES:
            data = payload.get(surface)
            if not isinstance(data, dict):
                continue
            rec = self._records.get(surface)
            if rec is None:
                continue
            if rec.status != STATUS_NO_DATA:
                continue
            rec.commanded = data.get("commanded")
            rec.oracle_seen = data.get("oracle_seen")
            rec.verified_at = data.get("verified_at")
            # Rider fix-up C-LOW-1: normalize `status` — a corrupt KV
            # payload where `status` is not a str (list/dict/int) must
            # not poison the record. Coerce non-str to NO_DATA.
            raw_status = data.get("status")
            rec.status = raw_status if isinstance(raw_status, str) and raw_status else STATUS_NO_DATA
            rec.restored = True
        _LOGGER.info(
            "Rider: restored WriteVerifier records from KV: %s",
            {s: self._records[s].status for s in WRITE_VERIFY_NM_SURFACES},
        )

    def cancel_all(self) -> None:
        """Cancel every pending delayed check. Called from
        EnergyCoordinator teardown / async_shutdown path so
        async_call_later handles do not leak past coordinator lifetime.
        """
        for surface, handle in list(self._pending_by_surface.items()):
            try:
                if handle is not None:
                    handle()
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "WriteVerifier: cancel %s failed (swallowed)",
                    surface, exc_info=True,
                )
        self._pending_by_surface.clear()
        self._pending_commanded_by_surface.clear()

    # ------------------------------------------------------------------
    # Public accessor consumed by BatteryStrategy.get_status()
    # ------------------------------------------------------------------
    def get_status_attrs(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        # H1 (2026-07-13): expose write_route per surface so the operator
        # can SEE which leg (cloud|local) URA is writing to right now.
        # Surface names in `_write_failover_by_surface` (energy_battery
        # entity-config keys) differ from WRITE_VERIFY_SURFACE_* names —
        # map them explicitly.
        battery = getattr(self._coord, "_battery", None)
        failover = (
            getattr(battery, "_write_failover_by_surface", {}) or {}
        )
        surface_to_key = {
            WRITE_VERIFY_SURFACE_RESERVE: "reserve_soc_number",
            WRITE_VERIFY_SURFACE_CHARGE_FROM_GRID: "charge_from_grid",
            WRITE_VERIFY_SURFACE_STORAGE_MODE: "storage_mode",
        }
        for surface in WRITE_VERIFY_NM_SURFACES:
            rec = self._records[surface]
            route = (
                "cloud" if failover.get(surface_to_key.get(surface, ""))
                else "local"
            )
            out[f"last_verified_write_{surface}"] = {
                "commanded": rec.commanded,
                "oracle_seen": rec.oracle_seen,
                "verified_at": rec.verified_at,
                "status": rec.status,
                "write_route": route,
                # Rider (2026-07-13): honest post-restart flag; see
                # `_VerifyRecord.restored` docstring.
                "restored": rec.restored,
            }
        out["write_mismatch_counts_24h"] = {
            s: self._mismatch_counts.value(s)
            for s in WRITE_VERIFY_NM_SURFACES
        }
        return out
