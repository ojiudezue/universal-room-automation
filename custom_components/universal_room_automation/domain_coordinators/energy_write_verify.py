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
    CONF_CONDUCT_DISCHARGE_EPSILON_W,
    CONF_CONDUCT_ENABLED,
    CONF_CONDUCT_N_TICKS,
    CONF_CONDUCT_SOC_DEADBAND_PCT,
    CONF_PENDING_ATTEMPT_1_AGE_S,
    CONF_PENDING_ATTEMPT_2_AGE_S,
    CONF_PENDING_ATTEMPT_3_AGE_S,
    CONF_PENDING_MAX_ATTEMPTS,
    CONF_PENDING_STANDDOWN_COOLOFF_S,
    CONF_PENDING_WATCHDOG_ENABLED,
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
# v5.17.2 — a record retires to STALE when the strategy's CURRENT desire
# for the surface equals the oracle-observed value (i.e. the old command
# is no longer wanted; state has converged on the new intent). A stale
# record's `verified_at` is FROZEN at retirement time and it is NEVER
# re-checked, re-stamped, or counted toward mismatch/self-heal counters.
# A fresh schedule() on the same surface replaces the record wholesale
# and revives it normally.
STATUS_STALE = "stale"


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

        # ─── v5.19.0 behavioral write-verify state ────────────────────
        # D1 CONDUCT — reserve-surface only. Consecutive-tick counter,
        # episode start, last evaluation reason (populated for
        # observability), and a per-episode alarm latch so a single
        # standing episode = exactly one anomaly + one NM per day.
        self._conduct_consec: dict[str, int] = {}
        self._conduct_episode_started_at: dict[str, Optional[datetime]] = {}
        self._conduct_last_soc: dict[str, Optional[float]] = {}
        self._conduct_last_discharge_w: dict[str, Optional[float]] = {}
        self._conduct_last_commanded: dict[str, Any] = {}
        self._conduct_last_abstain_reason: dict[str, Optional[str]] = {}
        self._conduct_alarm_latched_at: dict[str, Optional[datetime]] = {}
        # D2 PENDING watchdog — per-surface episode state. `commanded_at`
        # is the anchor: a new commanded_at value opens a fresh episode
        # and resets attempts. `attempts_fired` grows 0→3; at 3 with
        # divergence still standing we HARD STAND-DOWN and pin
        # `standdown_at`; resumes on convergence, fresh commanded_at, or
        # cool-off expiry (then one fresh probe attempt).
        self._pending_episode_at: dict[str, Optional[datetime]] = {}
        self._pending_attempts_fired: dict[str, int] = {}
        self._pending_last_attempt_at: dict[str, Optional[datetime]] = {}
        self._pending_standdown_at: dict[str, Optional[datetime]] = {}
        self._pending_cooloff_probe_fired: dict[str, bool] = {}
        self._pending_last_divergence_age_s: dict[str, Optional[float]] = {}
        self._pending_last_oracle: dict[str, Any] = {}
        # Fix-up ROOT 2 (D-HIGH-3) — value at hard stand-down. Used by:
        #   (a) `is_standdown_active_for_value` — the normal `_result`
        #       dispatch leg skips same-value re-dispatch of a stuck
        #       surface (auto-resume when effective desire changes).
        #   (b) `is_pending_episode_active` — during a pending episode the
        #       overlapping `self_heal_starvation` alarm is suppressed so
        #       the more-specific alarm owns the surface.
        self._pending_standdown_value: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Blind-window guard predicate (see PLANNING_ec_blind_window_evse_guard.md)
    # ------------------------------------------------------------------
    def is_reserve_verifiable(self) -> bool:
        """Return True iff the reserve write path has a fresh verified outcome.

        Coarse predicate consumed by the blind-window EVSE guard: "can we
        prove a reserve command took right now?" A False here means the
        reserve write path is unverifiable (stale/no-data/pending beyond
        the attempt-3 watchdog), which is the second half of the guard's
        entry predicate (the first half being `blind_hold_active`).

        Fix-up A-CRIT-1 (Batch 1) — RULING enforced here:
          (a) Only STATUS_OK counts as verifiable. STATUS_STALE is EXPLICITLY
              excluded: a STALE record has been retired (its `verified_at` is
              frozen at retirement time and never re-checked) — a resting
              STALE record cannot prove a live-write took NOW. Previously
              STALE returned True which made the guard's entry predicate
              unable to fire during a quiet outage between write episodes.
          (b) `verified_at` must be fresher than `CONF_RESERVE_VERIFIABLE_MAX_AGE_S`.
              Between write episodes an OK record rests indefinitely; without
              a freshness bound the predicate would report the reserve write
              path healthy forever, blinding the guard during a live outage
              that started AFTER the last successful verify.
          (c) The cloud oracle for the reserve surface must be READABLE now.
              An oracle-unreadable condition (envoy blind / entity
              unavailable / no oracle configured) means we CANNOT prove the
              write took right now regardless of what the record says.

        REUSES the existing per-surface status vocabulary (STATUS_*).
        Considers the RESERVE surface only — the guard's invariant is
        battery-reserve-specific.
        """
        try:
            # (c) Oracle-readability precondition — evaluated FIRST so a
            # blind oracle short-circuits even a fresh OK record. When the
            # cloud (or its integration) is dark, the last-known outcome
            # is not evidence about NOW.
            from .energy_const import CONF_RESERVE_VERIFIABLE_MAX_AGE_S
            oracle = self._oracle_entity_for(WRITE_VERIFY_SURFACE_RESERVE)
            if not oracle:
                return False
            oracle_probe = self._read_oracle_raw(oracle)
            if oracle_probe is None:
                return False

            rec = self._records.get(WRITE_VERIFY_SURFACE_RESERVE)
            if rec is None:
                return False

            # (a) OK-only. STATUS_STALE, NO_DATA, INCONCLUSIVE, MISMATCH,
            # REVERTED, UNMAPPED, UNIT_MISMATCH — none of these prove the
            # write took right now.
            if rec.status != STATUS_OK:
                return False

            # A pending episode past the attempt-3 watchdog age is by
            # contract "unverifiable" even if the RAM record still reads OK
            # (episode may have been armed post-OK).
            if self.is_pending_episode_active(WRITE_VERIFY_SURFACE_RESERVE):
                return False

            # (b) Freshness gate. Reuse the existing 600s stamp-age gate
            # style used at ~line 815 for `_desired_stamped_at`. Value 0
            # disables the gate (kill-switch for emergency backout).
            max_age = int(CONF_RESERVE_VERIFIABLE_MAX_AGE_S)
            if max_age > 0:
                if not rec.verified_at:
                    return False
                try:
                    stamp = dt_util.parse_datetime(rec.verified_at)
                except Exception:  # noqa: BLE001
                    stamp = None
                if stamp is None:
                    return False
                # tz-aware / tz-naive alignment: match `now` to `stamp`'s
                # awareness so the subtraction never raises. Production HA
                # emits aware ISO from `dt_util.utcnow().isoformat()`; test
                # mocks bind naive `datetime.utcnow`. Both cases yield a
                # valid `age_s`.
                now = dt_util.utcnow()
                try:
                    if stamp.tzinfo is None and now.tzinfo is not None:
                        stamp = stamp.replace(tzinfo=now.tzinfo)
                    elif stamp.tzinfo is not None and now.tzinfo is None:
                        stamp = stamp.replace(tzinfo=None)
                    age_s = (now - stamp).total_seconds()
                except Exception:  # noqa: BLE001
                    return False
                if age_s > float(max_age):
                    return False

            return True
        except Exception:  # noqa: BLE001 — defensive; guard is a read-only oracle
            return False

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
                # Root 2 (b) — alarm coordination. During an active
                # pending episode (attempt fired OR stand-down pinned)
                # for this surface, the more-specific
                # `pending_write_stuck` / `pending_write_standdown` alarm
                # owns the surface; suppress the overlapping
                # `self_heal_starvation` emit so we do not double-fire.
                if self.is_pending_episode_active(surface):
                    _LOGGER.debug(
                        "WriteVerifier: %s self_heal_starvation "
                        "suppressed (pending episode active)",
                        surface,
                    )
                else:
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
            # v5.19.0 — behavioral tripwires on the reserve surface only.
            # D1 conduct: SOC below floor + discharging + no exception.
            # D2 pending: divergence age past attempt-triggered ladder.
            # Both are RESERVE-SURFACE ONLY today: they read the SOC
            # resolver and the local hardware-enforced reserve sensor
            # (a semantic that only maps to the reserve surface).
            try:
                await self._conduct_check_reserve(battery)
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "conduct check raised (swallowed)", exc_info=True,
                )
            try:
                await self._pending_watchdog_reserve(battery)
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "pending watchdog raised (swallowed)", exc_info=True,
                )
        except Exception:  # noqa: BLE001
            _LOGGER.debug("reversion_sweep raised (swallowed)", exc_info=True)

    async def _sweep_surface(self, battery: Any, surface: str) -> None:
        # v5.17.2 — a STALE record has been retired: strategy's current
        # desire equals oracle, so the old command is no longer wanted.
        # Skip entirely — no re-read, no re-stamp, no mismatch increment,
        # no NM. The record revives only when schedule() fires (fresh
        # dispatch), which replaces the record wholesale.
        rec = self._records.get(surface)
        if rec is not None and rec.status == STATUS_STALE:
            _LOGGER.debug(
                "WriteVerifier: %s sweep skipped (record is STALE, "
                "verified_at frozen at %s)",
                surface, rec.verified_at,
            )
            return
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
        # v5.17.2 — STALE-RETIREMENT branch. Before treating a divergence
        # as a genuine reversion, ask: does the STRATEGY still want the
        # commanded value? If the current desire matches the oracle
        # (state has converged on the new intent) AND differs from the
        # stale commanded value, the old command is no longer wanted →
        # retire the record as STATUS_STALE, freeze verified_at, and
        # STOP re-checking / re-stamping / incrementing mismatch.
        # `_current_desire` reuses the SAME `_last_*_desired` fields
        # written by `_result()` at energy_battery.py:3929-3945 (the
        # canonical "strategy intent" ledger — desired reserve was
        # already used for the reserve-sweep's supersession belt).
        desire = self._current_desire(battery, surface)
        if desire is not None and desire != commanded:
            desire_matches_oracle = self._desire_matches_oracle(
                surface, desire, oracle_raw, oracle_unit,
            )
            if desire_matches_oracle:
                rec = self._records[surface]
                # Freeze verified_at at retirement (do NOT re-stamp on
                # subsequent sweeps — the STALE-fast-path at the top of
                # _sweep_surface returns before we get here).
                if rec.status != STATUS_STALE:
                    rec.commanded = commanded
                    rec.oracle_seen = oracle_raw
                    rec.verified_at = now.isoformat()
                    rec.status = STATUS_STALE
                # Clear coalesce so a genuine future flip can re-fire
                # cleanly on the fresh (superseding) record.
                self._last_reversion_at_by_surface.pop(surface, None)
                _LOGGER.info(
                    "WriteVerifier: %s RETIRED as STALE "
                    "(commanded=%s no longer desired; desire=%s == oracle=%s)",
                    surface, commanded, desire, oracle_raw,
                )
                return
        # ── v5.17.5 D3 — freshness gate before genuine-reversion ──────
        # Before treating this divergence as a GENUINE reversion (which
        # stamps REVERTED, emits an anomaly, and fires NM — pressure that
        # ultimately drives self-heal re-dispatches from the strategy),
        # check the STAMP AGE of the strategy's desired-* ledger. If the
        # strategy has NOT stamped a fresh desire within N decision
        # intervals (blind-hold branches RETURN before reaching
        # `_result`, so the stamp goes stale), the "desire" we read via
        # `_current_desire` is at best stale intent and cannot be
        # authoritative for classifying the operator's manual change as
        # a "reversion". Retire the record as STALE and stand down —
        # exactly like the v5.17.2 desire-matches-oracle path — no
        # anomaly, no NM, no re-dispatch pressure.
        #
        # Live incident 2026-07-15 18:31: the reversion sweep treated the
        # operator's manual de-escalation (reserve 10, CFG off) as an
        # external reversion of the frozen 15:06 attain intent (reserve
        # 80, CFG on) that determine_mode had been blind-held from
        # updating. NM fired and the strategy re-dispatched reserve=80.
        # The operator had to disable the whole EnergyCoordinator.
        #
        # Threshold: 2× decision interval (= 600s at the default 5-min
        # cadence). Does NOT require persistence — post-boot the stamp
        # is None until the first _result run; None → treat as stale →
        # stand down, closing review-B's restart question.
        _dsa = getattr(battery, "_desired_stamped_at", None)
        _stale_desire = True
        if _dsa is not None:
            try:
                _age = (dt_util.utcnow() - _dsa).total_seconds()
                _stale_desire = _age > 600
            except Exception:  # noqa: BLE001
                _stale_desire = True
        if _stale_desire:
            rec = self._records[surface]
            if rec.status != STATUS_STALE:
                rec.commanded = commanded
                rec.oracle_seen = oracle_raw
                rec.verified_at = now.isoformat()
                rec.status = STATUS_STALE
            self._last_reversion_at_by_surface.pop(surface, None)
            _LOGGER.info(
                "WriteVerifier: %s sweep — desire stale (blind?) — "
                "standing down (desired_stamped_at=%s, commanded=%s, "
                "oracle=%s)",
                surface, _dsa, commanded, oracle_raw,
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
        # D2-LOW-1 (review D re-pass): while a pending episode is armed
        # on this surface, the more-specific `pending_write_stuck` /
        # `pending_write_standdown` alarm owns the divergence; suppress
        # the overlapping `write_reverted` emission + NM so one
        # divergence yields the pending ladder's alarms only. The
        # separate `write_verification_failed` (t+15m) is left as-is per
        # spec (distinct meaning). Record status remains REVERTED above
        # so state is honest; only the alarm surface is coordinated.
        if self.is_pending_episode_active(surface):
            _LOGGER.debug(
                "WriteVerifier: %s write_reverted emit suppressed "
                "(pending episode active)",
                surface,
            )
            return
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

    def _current_desire(self, battery: Any, surface: str) -> Any:
        """v5.17.2 — read the strategy's CURRENT desire for a surface.

        Reuses the SAME `_last_*_desired` fields written each tick by
        `energy_battery.py::_result()` (see stamp block ~line 3929-3945).
        This is the ledger `_result` already consults when it asks the
        oracle "should I dispatch?" — reusing it here (rather than a
        second, drift-prone source) is the invariant the operator called
        out. Returns None if the strategy has not stamped a desire yet
        (early boot).
        """
        if surface == WRITE_VERIFY_SURFACE_RESERVE:
            return getattr(battery, "_last_reserve_level_desired", None)
        if surface == WRITE_VERIFY_SURFACE_CHARGE_FROM_GRID:
            return getattr(battery, "_last_charge_from_grid_desired", None)
        if surface == WRITE_VERIFY_SURFACE_STORAGE_MODE:
            return getattr(battery, "_last_storage_mode_desired", None)
        return None

    def _desire_matches_oracle(
        self,
        surface: str,
        desire: Any,
        oracle_raw: Any,
        oracle_unit: Optional[str],
    ) -> bool:
        """True iff the strategy's current desire matches the oracle
        (via the SAME `_compare` used everywhere else — no second
        comparison rule)."""
        status, matched = self._compare(
            surface, desire, oracle_raw, oracle_unit,
        )
        return bool(matched) and status == STATUS_OK

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
        """Emit AnomalyEvent via existing bus. Never raises.

        Fix-up D-MED-4 / C-M10 — severity plumbing. The persisted
        `severity` was hardcoded WARNING while callers threaded a
        `severity_class` string ("ALERT"/"HIGH"/"CRITICAL") in `extra`.
        Analytics grouped by severity therefore saw every conduct /
        pending emit as WARNING, defeating the ratified escalation.

        Mapping (per ratification #1: conduct = ALERT, not CRITICAL —
        money leak, not safety):
          * "ALERT"    → AnomalySeverity.ALERT
          * "HIGH"     → AnomalySeverity.ALERT   (attempt #2 rung; the
                          enum has no HIGH bucket — ALERT is the correct
                          rung above ADVISORY and below CRITICAL per
                          anomaly_event.py:46-68)
          * "CRITICAL" → AnomalySeverity.CRITICAL (attempt #3 / final)
          * missing/other → WARNING (unchanged default).
        """
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
            sev_class = str(extra.get("severity_class", "")).upper()
            if sev_class == "CRITICAL":
                severity = AnomalySeverity.CRITICAL
            elif sev_class in ("ALERT", "HIGH"):
                severity = AnomalySeverity.ALERT
            else:
                severity = AnomalySeverity.WARNING
            event = AnomalyEvent(
                coordinator="energy",
                type=type_str,
                severity=severity,
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
        severity: str = "critical",
    ) -> None:
        """Fire NM alert once per (surface, alert_type) per calendar day.

        Fix-up B-MED-3: latch is per (surface, alert_type) so that a
        mismatch alert and a subsequent reversion alert on the SAME
        surface do not share a latch — they represent distinct operator
        events and each deserves at most one notification per day.

        Notification Hygiene FIX 3: ``severity`` is now caller-controlled
        (default preserves legacy CRITICAL behavior). The pending-write
        stuck ladder demotes intermediate attempts to "high" so only the
        FINAL attempt + pending_write_standdown page the operator at
        CRITICAL and thus enter the repeat/safe-word/footer machinery
        (which is severity-derived in NM — line 1338 gate on
        Severity.CRITICAL).
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
                    severity=severity,
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

    # ==================================================================
    # v5.19.0 — Behavioral write-verify (D1 conduct + D2 pending)
    # ==================================================================
    #
    # Invariant I-BWV (Behavioral Write-Verify), from planning doc:
    #   1. Conduct: for surface `reserve_soc`, if commanded floor F is
    #      standing and for N consecutive ticks SOC < F−deadband AND
    #      battery is discharging faster than ε AND no legal exception
    #      holds, then EXACTLY ONE hardware_noncompliance anomaly per
    #      standing episode, ≤1 NM/(surface,alert_type)/day.
    #   2. Pending: if commanded=V and (observed=oracle) diverges for
    #      age > attempt-N threshold, fire ≤3 escalating retries
    #      (each RE-DERIVING live desire at fire-time — I-D3 preserved),
    #      then HARD STAND-DOWN on attempt 3.
    #   3. Never fight the operator: no retry when `_desired_stamped_at`
    #      is stale, when record is STATUS_STALE, or when live desire
    #      moved from the diverged commanded value.
    #
    # Legal below-floor exceptions (D1 only; RATIFIED NARROW per operator
    # decision #2 2026-07-17). Ordered by cheapness:
    #   a. within initial verify window (rounded to _verify_window_s)
    #   b. STATUS_STALE record (desire moved; not authoritative)
    #   c. `_desired_stamped_at` stale (blind-hold branch — I-D3)
    #   d. explicitly-commanded drain: current strategy desire for the
    #      reserve surface is LOWER than the historical commanded floor
    #      we are auditing (i.e. URA has since lowered the floor; the
    #      hardware is legitimately catching up to the new lower value).
    #   e. inclement partial_hold_reserve_floor active: legit lower floor
    #      applied by inclement machinery (v5.5.3 lesson).
    #
    # Per B0-D1: legitimate drains never present as below-floor episodes
    # by construction (URA lowers the floor before draining), so this
    # exception list carries almost no live load — narrow (d)+(e) is
    # sufficient and does not swallow real defects.
    # ------------------------------------------------------------------

    def _local_reserve_witness_state(
        self, battery: Any
    ) -> tuple[Optional[float], Optional[str]]:
        """Read the local hardware-enforced reserve sensor state + unit.

        Per B0-D2, `sensor.envoy_*_reserve_battery_level` is the honest
        hardware witness (its `unavailable` flaps mandate the abstain
        path). Returns (float|None, unit_str|None).
        """
        eid = self._local_entity_for(WRITE_VERIFY_SURFACE_RESERVE)
        if not eid:
            return None, None
        try:
            st = self.hass.states.get(eid)
            if st is None or st.state in ("unavailable", "unknown", None):
                return None, None
            unit = st.attributes.get("unit_of_measurement")
            return float(st.state), unit
        except (TypeError, ValueError, AttributeError):
            return None, None

    def _read_soc_via_resolver(self, battery: Any) -> Optional[float]:
        """Route SOC read through the 3-tier resolver (energy_battery
        battery_soc property). Abstain on None.
        """
        try:
            return battery.battery_soc  # type: ignore[no-any-return]
        except Exception:  # noqa: BLE001
            return None

    def _read_battery_power_w(self, battery: Any) -> Optional[float]:
        """Read signed battery power in W.

        CONVENTION (see energy_battery.py:868-908): POSITIVE = charging,
        NEGATIVE = discharging. The B0 probe report (planning doc) refers
        to the raw sensor which uses positive=discharging; the property
        `battery_power_w` NEGATES that. Consumers of this method
        (discharge tests) must treat `< -ε` as "discharging faster than ε".
        """
        try:
            return battery.battery_power_w  # type: ignore[no-any-return]
        except Exception:  # noqa: BLE001
            return None

    def _reserve_desire(self, battery: Any) -> Optional[int]:
        d = self._current_desire(battery, WRITE_VERIFY_SURFACE_RESERVE)
        try:
            return int(d) if d is not None else None
        except (TypeError, ValueError):
            return None

    # ------------------------------------------------------------------
    # ROOT 1 — Effective post-overlay desired reserve.
    #
    # `_last_reserve_level_desired` on BatteryStrategy is the PRE-overlay
    # value (strategy tick output). The EVSE-hold overlay at
    # `energy.py:_apply_evse_battery_hold` raises the *commanded* value
    # via `max(existing, evse_hold_soc)` and stamps the ledger; the tap
    # at `energy.py:5240-5244` re-stamps `_last_reserve_level` with the
    # actually-dispatched value. Neither writes back to
    # `_last_reserve_level_desired`. Consequences the fix addresses:
    #   * Conduct exception (d) exempts every tick during a standing
    #     EVSE hold if it uses PRE-overlay desire (battery could drain
    #     into car unalarmed).
    #   * Watchdog cancel-on-move check would clobber an active hold if
    #     it compared commanded ledger against PRE-overlay desire.
    #   * `force_redispatch` would push PRE-overlay value 15 while the
    #     hardware needs the hold-raised 61 — reserving into the car.
    #
    # `_effective_reserve_desired` = max(PRE-overlay strategy desire,
    #   active EVSE hold value if `_evse_battery_hold_active`,
    #   inclement partial_hold reserve_floor if that decision is
    #   partial_hold). It IS the value the system actually wants on
    #   hardware right now.
    # ------------------------------------------------------------------
    def _energy_coord(self) -> Any:
        """Return the energy coordinator (owner of EVSE-hold overlay
        state). None if not wired (test fixtures)."""
        return self._coord

    def _evse_hold_state(self) -> tuple[bool, Optional[int]]:
        """(active, hold_soc) reading the ENERGY COORDINATOR overlay
        state — the real writer of the max()-raise. Falls back to
        (False, None) if the coord doesn't expose the fields (test)."""
        coord = self._energy_coord()
        try:
            active = bool(getattr(coord, "_evse_battery_hold_active", False))
            hold_soc = getattr(coord, "_evse_hold_soc", None)
            if hold_soc is not None:
                try:
                    hold_soc = int(hold_soc)
                except (TypeError, ValueError):
                    hold_soc = None
            return active, hold_soc
        except Exception:  # noqa: BLE001
            return False, None

    def _inclement_partial_hold_floor(self, battery: Any) -> Optional[int]:
        """If the LIVE inclement decision is a partial_hold, return its
        `reserve_floor` (the floor URA is legitimately enforcing lower
        than a static commanded value). Else None.

        Reads the REAL state `battery._last_inclement_decision` (an
        `InclementDecision` from inclement.py:493, `hold_depth` in
        {'allow_discharge','partial_hold','full_hold'}). Does NOT invent
        an attribute — `_inclement_partial_hold_active` did not exist on
        BatteryStrategy and was replaced with this read.
        """
        try:
            dec = getattr(battery, "_last_inclement_decision", None)
            if dec is None:
                return None
            if getattr(dec, "hold_depth", None) != "partial_hold":
                return None
            floor = getattr(dec, "reserve_floor", None)
            if floor is None:
                return None
            return int(floor)
        except Exception:  # noqa: BLE001
            return None

    def _dp_transition_floor(self) -> Optional[int]:
        """DP-owned drain-target % (`_dp_decision_soc`) when the DP state
        machine is in TRANSITIONED. Composed into effective desired reserve
        so watchdog + sweep treat the DP-elevated floor as desired, not as
        a wedge. Resolves the energy coordinator the same way
        `_evse_hold_state` does. Returns None outside TRANSITIONED or when
        DP is not wired.

        Bound to production state:
          * carrier: `EnergyCoordinator._dp_carrier` (energy.py:362)
          * floor:   `EnergyCoordinator._dp_decision_soc` (energy.py:370)
        Kept in lock-step with the composition legs in
        `_apply_evse_battery_hold` (energy.py:3224, 3320) — the same
        floor a hold-active tick would compose into the emitted value.
        """
        coord = self._energy_coord()
        if coord is None:
            return None
        try:
            carrier = getattr(coord, "_dp_carrier", None)
            if carrier is None:
                return None
            # State-scoped read: only fold DP floor while TRANSITIONED.
            # Reversion clears both carrier.state and `_dp_decision_soc`
            # (energy.py:3515), so outside TRANSITIONED the floor is None
            # anyway — but the state gate is the semantic contract.
            from .energy_drain_precedence import DPState  # noqa: PLC0415
            if getattr(carrier, "state", None) != DPState.TRANSITIONED:
                return None
            dp_soc = getattr(coord, "_dp_decision_soc", None)
            if dp_soc is None:
                return None
            return int(dp_soc)
        except Exception:  # noqa: BLE001
            return None

    def _effective_reserve_desired(self, battery: Any) -> Optional[int]:
        """Post-overlay effective reserve — value the system wants on
        hardware right now. Returns None if strategy desire is unstamped.

        Composition (max() over all floors, matching the emit-side
        composition in `_apply_evse_battery_hold`):
          * pre-overlay strategy desire (`_last_reserve_level_desired`)
          * EVSE hold overlay (`_evse_hold_soc` when
            `_evse_battery_hold_active`)
          * inclement partial_hold reserve_floor
          * DP-owned drain floor (`_dp_decision_soc` when the DP carrier
            is TRANSITIONED)
        """
        raw = getattr(battery, "_last_reserve_level_desired", None)
        if raw is None:
            return None
        try:
            eff = int(raw)
        except (TypeError, ValueError):
            return None
        hold_active, hold_soc = self._evse_hold_state()
        if hold_active and hold_soc is not None:
            eff = max(eff, hold_soc)
        inc_floor = self._inclement_partial_hold_floor(battery)
        if inc_floor is not None:
            eff = max(eff, inc_floor)
        dp_floor = self._dp_transition_floor()
        if dp_floor is not None:
            eff = max(eff, dp_floor)
        return int(max(0, min(100, eff)))

    def _resolve_hold_owner(self, battery: Any) -> str:
        """Report which subsystem OWNS the current reserve floor.
        Derived from real state; no invented attribute reads.
        Priority: dp transition > evse hold > inclement partial/full >
        arbitrage phase > strategy default. DP outranks the EVSE hold
        overlay because a TRANSITIONED DP window owns the pause and
        raises the composed floor via `_dp_decision_soc` (energy.py:3224,
        3320); the hold overlay is the strategy-side wrapper that
        composes DP into its max().
        """
        dp_floor = self._dp_transition_floor()
        if dp_floor is not None:
            return "dp_transition"
        active, _hold_soc = self._evse_hold_state()
        if active:
            return "evse_battery_hold"
        try:
            dec = getattr(battery, "_last_inclement_decision", None)
            depth = getattr(dec, "hold_depth", None) if dec is not None else None
            if depth in ("partial_hold", "full_hold"):
                return "inclement"
        except Exception:  # noqa: BLE001
            pass
        try:
            phase = getattr(battery, "_arbitrage_phase", None)
            if phase and phase != "n/a":
                return f"arbitrage_{phase}"
        except Exception:  # noqa: BLE001
            pass
        return "strategy"

    # ------------------------------------------------------------------
    # ROOT 2 — Stand-down public accessors (consumed by BatteryStrategy
    # normal dispatch leg + self-heal alarm).
    # ------------------------------------------------------------------
    def is_standdown_active_for_value(
        self, surface: str, value: Any,
    ) -> bool:
        """True iff a HARD STAND-DOWN is active for `surface` at the
        non-compliant `value`. The normal `_result` dispatch leg reads
        this to SKIP same-value re-dispatch of the stuck surface — any
        change in effective desire cancels stand-down (value no longer
        matches) and the append proceeds normally, matching the ratified
        resume conditions (see D2 retry policy).
        """
        sd = self._pending_standdown_at.get(surface)
        if sd is None:
            return False
        sv = self._pending_standdown_value.get(surface)
        if sv is None:
            return False
        try:
            return int(sv) == int(value)
        except (TypeError, ValueError):
            return sv == value

    def is_pending_episode_active(self, surface: str) -> bool:
        """True while a pending episode is armed (attempts fired > 0 or
        a stand-down is pinned). Consumed by the schedule() self-heal
        starvation alarm to suppress the overlapping emit for this
        surface — the more-specific `pending_write_stuck` /
        `pending_write_standdown` alarms own the surface once armed.
        """
        if self._pending_attempts_fired.get(surface, 0) > 0:
            return True
        if self._pending_standdown_at.get(surface) is not None:
            return True
        return False

    # ------------------------------------------------------------------
    # ROOT D-MED-3 — Grid outage witness.
    #
    # Enphase's `switch.enpower_*_grid_enabled` reflects grid presence
    # (state == "off" during a genuine outage). Configured via
    # `DEFAULT_GRID_ENABLED_ENTITY` (energy_const.py:223), resolvable
    # via BatteryStrategy `_get_entity("grid_enabled", default)` when the
    # operator has wired it. Behavior:
    #   * If witness reads "off" → grid outage active; conduct exempted
    #     (backup discharge below floor is legit).
    #   * If witness reads "on"  → grid up; no exception.
    #   * If witness unresolvable / unavailable / unknown → ABSTAIN by
    #     returning None; caller does NOT invent a witness.
    # ------------------------------------------------------------------
    def _grid_outage_active(self, battery: Any) -> Optional[bool]:
        """Return True (outage), False (grid up), or None.

        None has TWO distinct meanings:
          * Witness NOT configured / not resolvable — caller falls
            through (no exception, no abstain — same as pre-D2-MED-2).
          * Witness CONFIGURED but currently unavailable/unknown —
            caller ABSTAINS the conduct check for the tick (D2-MED-2).

        We distinguish via `_grid_witness_state` (see caller).
        """
        try:
            from .energy_const import DEFAULT_GRID_ENABLED_ENTITY
            eid = None
            try:
                eid = battery._get_entity(  # noqa: SLF001
                    "grid_enabled", DEFAULT_GRID_ENABLED_ENTITY, role="read",
                )
            except TypeError:
                eid = battery._get_entity(  # noqa: SLF001
                    "grid_enabled", DEFAULT_GRID_ENABLED_ENTITY,
                )
            except Exception:  # noqa: BLE001
                eid = None
            if not eid:
                return None
            st = self.hass.states.get(eid)
            if st is None or st.state in ("unavailable", "unknown", None):
                return None
            return str(st.state).lower() == "off"
        except Exception:  # noqa: BLE001
            return None

    def _grid_witness_configured_but_stale(self, battery: Any) -> bool:
        """True iff the grid-enabled entity is configured (via
        `_get_entity`) but its live state is unresolvable / unavailable
        / unknown. Used to distinguish "operator hasn't wired one" (no
        abstain) from "witness flapping" (abstain).
        """
        try:
            from .energy_const import DEFAULT_GRID_ENABLED_ENTITY
            try:
                eid = battery._get_entity(  # noqa: SLF001
                    "grid_enabled", DEFAULT_GRID_ENABLED_ENTITY, role="read",
                )
            except TypeError:
                eid = battery._get_entity(  # noqa: SLF001
                    "grid_enabled", DEFAULT_GRID_ENABLED_ENTITY,
                )
            except Exception:  # noqa: BLE001
                return False
            if not eid:
                return False
            st = self.hass.states.get(eid)
            # "State missing entirely" (st is None) is treated as
            # NOT configured — could be a stale entity id / operator
            # default that was never provisioned. Only actual flapping
            # (state exists and reads unavailable/unknown) triggers
            # abstain per D2-MED-2 (that's the B0-measured failure mode).
            if st is not None and st.state in ("unavailable", "unknown"):
                return True
            return False
        except Exception:  # noqa: BLE001
            return False

    def _desire_stamp_fresh(self, battery: Any) -> bool:
        """True if `_desired_stamped_at` is fresh (< 2× decision
        interval = 600s — same threshold as v5.17.5 D3 gate).
        """
        _dsa = getattr(battery, "_desired_stamped_at", None)
        if _dsa is None:
            return False
        try:
            return (dt_util.utcnow() - _dsa).total_seconds() <= 600
        except Exception:  # noqa: BLE001
            return False

    def _legal_conduct_exception(
        self,
        battery: Any,
        commanded_floor: int,
        commanded_at: datetime,
        now: datetime,
    ) -> Optional[str]:
        """Return a short reason string if a legal exception holds,
        else None. Narrow per operator decision #2.
        """
        # (a) within initial verify window
        if (now - commanded_at).total_seconds() < self._verify_window_s:
            return "within_verify_window"
        # (b) STATUS_STALE record — desire has retired.
        rec = self._records.get(WRITE_VERIFY_SURFACE_RESERVE)
        if rec is not None and rec.status == STATUS_STALE:
            return "record_stale"
        # (c) blind-hold — desire not fresh; no authoritative floor.
        if not self._desire_stamp_fresh(battery):
            return "desire_stale"
        # (d) explicitly-commanded lower drain: EFFECTIVE post-overlay
        # desire (Root 1 fix) is below the historical commanded floor.
        # Hardware is catching up to a legit lower target. Using the
        # PRE-overlay desire here would exempt every tick during an EVSE
        # hold — the hold RAISES commanded above pre-overlay desire, so
        # pre-overlay < commanded_floor is trivially true and the battery
        # could drain into the car unalarmed.
        effective = self._effective_reserve_desired(battery)
        if effective is not None and effective < int(commanded_floor):
            return "explicit_drain_desire_lower"
        # (e) inclement partial_hold is a legit lower floor — but only
        # WHILE SOC is at or above (inclement_reserve_floor - deadband).
        # Below that, hardware is violating even the inclement floor and
        # the alarm SHOULD fire (D2-MED-1, review D re-pass). Reads the
        # REAL InclementDecision.hold_depth == "partial_hold" from
        # `battery._last_inclement_decision` (inclement.py:493) —
        # NOT the invented `_inclement_partial_hold_active` attribute.
        inc_floor = self._inclement_partial_hold_floor(battery)
        if inc_floor is not None:
            soc_now = self._read_soc_via_resolver(battery)
            if soc_now is None or soc_now >= (
                int(inc_floor) - CONF_CONDUCT_SOC_DEADBAND_PCT
            ):
                return "inclement_partial_hold"
            # SOC below the inclement floor - deadband → do NOT exempt.
            # Fall through so the trigger check can fire.
        # (f) grid outage — Enpower `_grid_enabled` == "off". Backup
        # discharge below the commanded reserve is expected during an
        # outage. Witness semantics (D2-MED-2, review D re-pass):
        #   * True → grid down → exempt.
        #   * False → grid up → no exception (fall through).
        #   * None + entity CONFIGURED but state unavailable/unknown →
        #     ABSTAIN (caller returns without counting).
        #   * None + entity NOT configured → operator hasn't wired one;
        #     do not abstain (fall through) — preserves prior behavior
        #     for deployments without an Enpower witness.
        outage = self._grid_outage_active(battery)
        if outage is True:
            return "grid_outage"
        if outage is None and self._grid_witness_configured_but_stale(
            battery,
        ):
            return "grid_witness_unavailable"
        return None

    async def _conduct_check_reserve(self, battery: Any) -> None:
        """D1 — reserve-surface conduct check (detect-only, W-6 preserved).

        Sequence:
          1. Read commanded ledger; return if no floor.
          2. Read SOC via 3-tier resolver + battery_power_w. Abstain on
             None (increment nothing, do not fire).
          3. Legal-exception check (narrow list). If any holds → RESET
             the consecutive-tick counter to 0 and clear episode.
          4. Trigger test: `soc < commanded - deadband` AND
             `battery_power_w < -epsilon` (discharging faster than ε).
          5. On trigger: increment counter; at N emit ONCE per episode.
        """
        if not CONF_CONDUCT_ENABLED:
            return
        surface = WRITE_VERIFY_SURFACE_RESERVE
        commanded, commanded_at = self._commanded_ledger(battery, surface)
        if commanded is None or commanded_at is None:
            self._conduct_last_abstain_reason[surface] = "no_commanded"
            return
        try:
            commanded_floor = int(commanded)
        except (TypeError, ValueError):
            self._conduct_last_abstain_reason[surface] = "no_commanded"
            return
        now = dt_util.utcnow()
        soc = self._read_soc_via_resolver(battery)
        power_w = self._read_battery_power_w(battery)
        self._conduct_last_soc[surface] = soc
        self._conduct_last_discharge_w[surface] = power_w
        self._conduct_last_commanded[surface] = commanded_floor
        if soc is None:
            self._conduct_last_abstain_reason[surface] = "soc_blind"
            return
        if power_w is None:
            self._conduct_last_abstain_reason[surface] = "power_none"
            return
        exception_reason = self._legal_conduct_exception(
            battery, commanded_floor, commanded_at, now,
        )
        if exception_reason == "grid_witness_unavailable":
            # D2-MED-2 (review D re-pass): grid witness flapping is
            # measured behavior on this Envoy (B0). Rather than falling
            # through to the alarm-permissive path (previous behavior)
            # OR treating this as a legal exception that RESETS the
            # counter (would mask a real drift), ABSTAIN — do not count,
            # do not fire, do not reset. Counter state persists across
            # the abstain so a genuine episode is not erased by a flap.
            self._conduct_last_abstain_reason[surface] = (
                "grid_witness_unavailable"
            )
            return
        if exception_reason is not None:
            # Legal state — episode closes (if any) and counter resets.
            if self._conduct_consec.get(surface, 0) > 0:
                _LOGGER.debug(
                    "WriteVerifier: %s conduct RESET (exception=%s)",
                    surface, exception_reason,
                )
            self._conduct_consec[surface] = 0
            self._conduct_episode_started_at[surface] = None
            self._conduct_alarm_latched_at[surface] = None
            self._conduct_last_abstain_reason[surface] = exception_reason
            return
        below_floor = (
            soc < (commanded_floor - CONF_CONDUCT_SOC_DEADBAND_PCT)
        )
        # POWER SIGN: battery_power_w is POSITIVE=charging.
        # "Discharging faster than epsilon" → power_w < -epsilon.
        discharging = power_w < -float(CONF_CONDUCT_DISCHARGE_EPSILON_W)
        if not (below_floor and discharging):
            if self._conduct_consec.get(surface, 0) > 0:
                _LOGGER.debug(
                    "WriteVerifier: %s conduct counter reset "
                    "(soc=%.1f floor=%d power_w=%.0f)",
                    surface, soc, commanded_floor, power_w,
                )
            self._conduct_consec[surface] = 0
            self._conduct_episode_started_at[surface] = None
            self._conduct_alarm_latched_at[surface] = None
            self._conduct_last_abstain_reason[surface] = None
            return
        # Trigger tick.
        prev = self._conduct_consec.get(surface, 0)
        n = prev + 1
        self._conduct_consec[surface] = n
        if prev == 0:
            self._conduct_episode_started_at[surface] = now
        self._conduct_last_abstain_reason[surface] = None
        _LOGGER.debug(
            "WriteVerifier: %s conduct tick %d/%d "
            "(soc=%.1f floor=%d power_w=%.0f)",
            surface, n, CONF_CONDUCT_N_TICKS, soc, commanded_floor, power_w,
        )
        if n < CONF_CONDUCT_N_TICKS:
            return
        # Per-episode alarm latch — one anomaly + one NM per standing
        # episode. Latch clears when the episode ends (counter reset).
        if self._conduct_alarm_latched_at.get(surface) is not None:
            return
        self._conduct_alarm_latched_at[surface] = now
        _LOGGER.warning(
            "WriteVerifier: %s HARDWARE NONCOMPLIANCE — "
            "commanded_floor=%d, soc=%.1f, discharging=%.0f W for %d ticks",
            surface, commanded_floor, soc, power_w, n,
        )
        await self._emit_anomaly(
            surface,
            "hardware_noncompliance",
            {
                "commanded_floor": commanded_floor,
                "soc_observed": soc,
                "discharge_w_observed": power_w,
                "consecutive_ticks": n,
                "severity_class": "ALERT",
            },
        )
        await self._maybe_fire_nm(
            surface,
            title=f"Battery below floor while discharging: {surface}",
            message=(
                f"URA commanded reserve floor {commanded_floor}% but SOC "
                f"is {soc:.1f}% and battery is discharging at "
                f"{-power_w:.0f} W for {n} consecutive ticks with no "
                "legal exception. Hardware may not be enforcing the "
                "commanded floor."
            ),
            alert_type="hardware_noncompliance",
        )

    # ------------------------------------------------------------------
    # D2 pending-write watchdog + bounded-escalation retry ladder
    # ------------------------------------------------------------------
    def _pending_attempt_threshold_s(self, attempts_fired: int) -> int:
        """Divergence-age threshold for the NEXT attempt.

        attempts_fired = 0 → 900s (attempt #1 fires at 15m)
        attempts_fired = 1 → 1800s (attempt #2 fires at 30m)
        attempts_fired = 2 → 3600s (attempt #3 fires at 60m)
        """
        if attempts_fired == 0:
            return int(CONF_PENDING_ATTEMPT_1_AGE_S)
        if attempts_fired == 1:
            return int(CONF_PENDING_ATTEMPT_2_AGE_S)
        return int(CONF_PENDING_ATTEMPT_3_AGE_S)

    def _reset_pending_episode(self, surface: str) -> None:
        self._pending_episode_at[surface] = None
        self._pending_attempts_fired[surface] = 0
        self._pending_last_attempt_at[surface] = None
        self._pending_standdown_at[surface] = None
        self._pending_standdown_value.pop(surface, None)
        self._pending_cooloff_probe_fired[surface] = False
        self._pending_last_divergence_age_s[surface] = None

    async def _pending_watchdog_reserve(self, battery: Any) -> None:
        """D2 — pending-write watchdog on the reserve surface.

        Inference-only per operator ratification #3 (2026-07-17): the
        Enphase integration does NOT expose pending fields as HA state
        (B0-D2b confirmed). Divergence-age between URA's commanded
        ledger and the local hardware-enforced sensor drives detection.
        """
        if not CONF_PENDING_WATCHDOG_ENABLED:
            return
        surface = WRITE_VERIFY_SURFACE_RESERVE
        commanded, commanded_at = self._commanded_ledger(battery, surface)
        if commanded is None or commanded_at is None:
            return
        # STATUS_STALE — desire has retired, do not treat as stuck.
        rec = self._records.get(surface)
        if rec is not None and rec.status == STATUS_STALE:
            self._reset_pending_episode(surface)
            return
        # Read hardware witness. Abstain (do NOT increment attempts) on
        # unavailable per operator directive — sensor flaps are common.
        hw_value, hw_unit = self._local_reserve_witness_state(battery)
        if hw_value is None:
            _LOGGER.debug(
                "WriteVerifier: %s pending watchdog abstain "
                "(hardware witness unavailable)",
                surface,
            )
            return
        # Convergence check via the same _compare (percent-normalized).
        status, matched = self._compare(surface, commanded, hw_value, hw_unit)
        if matched and status == STATUS_OK:
            # Converged — close episode + clear stand-down.
            if (
                self._pending_episode_at.get(surface) is not None
                or self._pending_standdown_at.get(surface) is not None
            ):
                _LOGGER.info(
                    "WriteVerifier: %s pending watchdog — CONVERGED "
                    "(hw=%.1f == cmd=%s); resetting episode",
                    surface, hw_value, commanded,
                )
            self._reset_pending_episode(surface)
            self._pending_last_oracle[surface] = hw_value
            return
        # Diverged. Episode anchored to commanded_at — a fresh
        # commanded_at value opens a new episode (attempts reset).
        prev_episode_at = self._pending_episode_at.get(surface)
        if prev_episode_at is None or prev_episode_at != commanded_at:
            self._reset_pending_episode(surface)
            self._pending_episode_at[surface] = commanded_at
        now = dt_util.utcnow()
        divergence_age_s = (now - commanded_at).total_seconds()
        self._pending_last_divergence_age_s[surface] = divergence_age_s
        self._pending_last_oracle[surface] = hw_value
        # If we already HARD STOOD DOWN on this episode, allow ONE
        # cool-off probe attempt (fresh command); after that, silent.
        standdown_at = self._pending_standdown_at.get(surface)
        if standdown_at is not None:
            cooloff_probe_fired = self._pending_cooloff_probe_fired.get(
                surface, False,
            )
            if cooloff_probe_fired:
                return
            age = (now - standdown_at).total_seconds()
            if age < float(CONF_PENDING_STANDDOWN_COOLOFF_S):
                return
            # Fire ONE cool-off probe attempt — re-derives desire.
            await self._pending_fire_retry(
                battery, surface, attempt_index_note="cooloff_probe",
            )
            self._pending_cooloff_probe_fired[surface] = True
            return
        attempts_fired = self._pending_attempts_fired.get(surface, 0)
        # Check whether the age threshold for the next attempt is met.
        threshold = self._pending_attempt_threshold_s(attempts_fired)
        if divergence_age_s < threshold:
            return
        # Fix-up A-LOW-1 / C-M6b — LADDER SPACING gate. Without this, a
        # divergence pre-aged past ATTEMPT_3_AGE (e.g. post-restart) would
        # fire attempts 1/2/3 on three consecutive decision ticks. Enforce
        # ≥ ATTEMPT_1_AGE_S between attempts so ladder spacing matches
        # measured Enphase apply-lag (B0-D2 p90 = 7.7 min < 15 min).
        last_att = self._pending_last_attempt_at.get(surface)
        if last_att is not None:
            since_last = (now - last_att).total_seconds()
            if since_last < float(CONF_PENDING_ATTEMPT_1_AGE_S):
                _LOGGER.debug(
                    "WriteVerifier: %s pending watchdog — spacing gate "
                    "(since_last=%.0fs < %ds); attempt deferred",
                    surface, since_last, int(CONF_PENDING_ATTEMPT_1_AGE_S),
                )
                return
        # ─── LOAD-BEARING SEAM: freshness + desire re-derivation ──────
        # Ratified freshness constraint (2026-07-17):
        #   "Re-commands only if consistent with the energy situation
        #    NOW — never issue stale commands."
        # Each ladder attempt re-derives desire from live strategy state
        # at fire time; it never replays detection-time ledger value.
        if not self._desire_stamp_fresh(battery):
            # Blind — I-D3 forbids retries.
            _LOGGER.info(
                "WriteVerifier: %s pending watchdog — desire stale "
                "(blind) — retry suppressed (I-D3)",
                surface,
            )
            return
        # Root 1 fix — cancel-on-move compares against the EFFECTIVE
        # post-overlay desire, not the pre-overlay strategy desire. A
        # cool-off probe or ladder tick during an active EVSE hold must
        # continue to command the hold-raised value (e.g. 61), not the
        # pre-overlay strategy value (e.g. 15) — the latter would clobber
        # the hold and drain into the car.
        effective = self._effective_reserve_desired(battery)
        if effective is None:
            return
        try:
            _cmd_int = int(commanded)
        except (TypeError, ValueError):
            _cmd_int = None
        if _cmd_int is None or effective != _cmd_int:
            _LOGGER.info(
                "WriteVerifier: %s pending watchdog — effective desire "
                "moved (commanded=%s, effective=%s); ladder CANCELLED",
                surface, commanded, effective,
            )
            self._reset_pending_episode(surface)
            return
        # Attempt number about to fire (1-indexed).
        attempt_no = attempts_fired + 1
        # Emit + optional NM per plan escalation:
        #   #1 → ALERT anomaly + NM once/day
        #   #2 → HIGH anomaly (still ALERT class in NM latch key)
        #   #3 → FINAL — pages operator; hard stand-down set below.
        severity_class = "ALERT"
        if attempt_no == 2:
            severity_class = "HIGH"
        elif attempt_no == 3:
            severity_class = "CRITICAL"
        await self._emit_anomaly(
            surface,
            "pending_write_stuck",
            {
                "commanded": commanded,
                "oracle_seen": hw_value,
                "divergence_age_s": divergence_age_s,
                "attempt": attempt_no,
                "severity_class": severity_class,
                "hw_witness": "envoy_reserve_battery_level",
            },
        )
        await self._maybe_fire_nm(
            surface,
            title=(
                f"Pending write stuck (attempt {attempt_no}"
                f"/{CONF_PENDING_MAX_ATTEMPTS}): {surface}"
            ),
            message=(
                f"URA commanded {surface}={commanded!r} but hardware "
                f"reports {hw_value!r} after {int(divergence_age_s)}s. "
                f"Re-dispatching (attempt {attempt_no})."
            ),
            alert_type=(
                "pending_write_stuck"
                if attempt_no < CONF_PENDING_MAX_ATTEMPTS
                else "pending_write_stuck_final"
            ),
            # Notification Hygiene FIX 3: attempts 1..(MAX-1) fire at
            # HIGH so they don't enter the CRITICAL repeat engine — the
            # per-day latch remains (once per alert_type per day). The
            # FINAL attempt escalates to CRITICAL so the operator gets
            # the safe-word/repeat treatment.
            severity=(
                "high"
                if attempt_no < CONF_PENDING_MAX_ATTEMPTS
                else "critical"
            ),
        )
        # Fire the retry — via BatteryStrategy.force_redispatch, which
        # re-derives desire at fire time (already re-derived above,
        # but force_redispatch re-checks for us — belt+suspenders).
        await self._pending_fire_retry(
            battery, surface, attempt_index_note=f"attempt_{attempt_no}",
        )
        self._pending_attempts_fired[surface] = attempt_no
        self._pending_last_attempt_at[surface] = now
        # HARD STAND-DOWN after final attempt.
        if attempt_no >= int(CONF_PENDING_MAX_ATTEMPTS):
            self._pending_standdown_at[surface] = now
            # Root 2 — capture the non-compliant value so the normal
            # dispatch leg can gate same-value re-dispatch.
            self._pending_standdown_value[surface] = commanded
            _LOGGER.warning(
                "WriteVerifier: %s pending watchdog — HARD STAND-DOWN "
                "after %d attempts; surface marked non-compliant. "
                "URA will stop commanding this surface until convergence, "
                "fresh operator-driven desire change, or cool-off "
                "expiry (%.0fh).",
                surface, attempt_no,
                float(CONF_PENDING_STANDDOWN_COOLOFF_S) / 3600.0,
            )
            await self._maybe_fire_nm(
                surface,
                title=f"URA STAND-DOWN: {surface} non-compliant",
                message=(
                    f"After {attempt_no} identical retries spaced by "
                    "Enphase apply-lag, hardware still diverges. URA "
                    "has deliberately stopped commanding this surface. "
                    "Investigate manually."
                ),
                alert_type="pending_write_standdown",
            )

    async def _pending_fire_retry(
        self,
        battery: Any,
        surface: str,
        attempt_index_note: str,
    ) -> None:
        """Fire ONE re-dispatch via BatteryStrategy.force_redispatch.

        The strategy re-checks freshness + re-derives live desire at
        fire time (belt + suspenders vs the check we did above); if any
        precondition fails the call is a no-op with a DEBUG log.
        """
        try:
            fn = getattr(battery, "force_redispatch", None)
            if fn is None:
                _LOGGER.debug(
                    "WriteVerifier: %s force_redispatch missing on "
                    "BatteryStrategy — retry skipped (%s)",
                    surface, attempt_index_note,
                )
                return
            _LOGGER.info(
                "WriteVerifier: %s pending watchdog — firing retry (%s)",
                surface, attempt_index_note,
            )
            await fn(surface)
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "WriteVerifier: force_redispatch raised (swallowed)",
                exc_info=True,
            )

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
        # ─── v5.19.0 D3 observability attrs ───────────────────────────
        # D1 hardware_noncompliance state (reserve surface only today).
        surface = WRITE_VERIFY_SURFACE_RESERVE
        latched = self._conduct_alarm_latched_at.get(surface)
        started = self._conduct_episode_started_at.get(surface)
        commanded_floor = self._conduct_last_commanded.get(surface)
        out["hardware_noncompliance_state"] = {
            surface: {
                "active": latched is not None,
                "consecutive_ticks": self._conduct_consec.get(surface, 0),
                "soc_observed": self._conduct_last_soc.get(surface),
                "commanded_floor": commanded_floor,
                "discharge_w_observed": (
                    self._conduct_last_discharge_w.get(surface)
                ),
                "episode_started_at": (
                    started.isoformat() if started is not None else None
                ),
                "alarm_latched_at": (
                    latched.isoformat() if latched is not None else None
                ),
                "abstain_reason": (
                    self._conduct_last_abstain_reason.get(surface)
                ),
            },
        }
        # D2 pending_write_stuck state.
        ep_at = self._pending_episode_at.get(surface)
        sd_at = self._pending_standdown_at.get(surface)
        last_att = self._pending_last_attempt_at.get(surface)
        # Read the CURRENT desire so operators can see live desire vs
        # ledger-commanded at the moment attrs render.
        try:
            _live_desire = self._reserve_desire(
                getattr(self._coord, "_battery", None)
            )
        except Exception:  # noqa: BLE001
            _live_desire = None
        # A-NIT-1: explicit None passthrough — `_commanded_ledger`
        # tolerates a None battery (its getattr calls return None); the
        # prior `or self` fallback would mask real "battery not wired"
        # states by dispatching getattrs against WriteVerifier itself.
        _bat_for_ledger = getattr(self._coord, "_battery", None)
        commanded_ledger, commanded_at = self._commanded_ledger(
            _bat_for_ledger, surface,
        )
        out["pending_write_stuck_state"] = {
            surface: {
                "active": ep_at is not None,
                "commanded_at": (
                    commanded_at.isoformat()
                    if commanded_at is not None else None
                ),
                "commanded_value": commanded_ledger,
                "oracle_value": self._pending_last_oracle.get(surface),
                "divergence_age_s": (
                    self._pending_last_divergence_age_s.get(surface)
                ),
                "attempts_fired": self._pending_attempts_fired.get(surface, 0),
                "last_attempt_at": (
                    last_att.isoformat() if last_att is not None else None
                ),
                "standdown_at": (
                    sd_at.isoformat() if sd_at is not None else None
                ),
                "cooloff_probe_fired": (
                    self._pending_cooloff_probe_fired.get(surface, False)
                ),
                "live_desire": _live_desire,
                "desire_stamp_fresh": (
                    self._desire_stamp_fresh(_bat_for_ledger)
                    if _bat_for_ledger is not None else False
                ),
            },
        }
        # D3 three-way command_trail (from operator confusion 2026-07-16):
        # commanded (URA desire ledger) / hardware-enforced / cloud-oracle
        # each with age. Only reserve today.
        battery_obj = getattr(self._coord, "_battery", None)
        hw_val, _hw_unit = (
            self._local_reserve_witness_state(battery_obj)
            if battery_obj is not None else (None, None)
        )
        cloud_eid = self._oracle_entity_for(surface)
        cloud_val = self._read_oracle_raw(cloud_eid) if cloud_eid else None
        cloud_age_s: Optional[float] = None
        hw_age_s: Optional[float] = None
        try:
            if cloud_eid:
                st = self.hass.states.get(cloud_eid)
                if st is not None and getattr(st, "last_updated", None):
                    cloud_age_s = (
                        dt_util.utcnow() - st.last_updated
                    ).total_seconds()
        except Exception:  # noqa: BLE001
            pass
        try:
            hw_eid = self._local_entity_for(surface)
            if hw_eid:
                st = self.hass.states.get(hw_eid)
                if st is not None and getattr(st, "last_updated", None):
                    hw_age_s = (
                        dt_util.utcnow() - st.last_updated
                    ).total_seconds()
        except Exception:  # noqa: BLE001
            pass
        commanded_age_s: Optional[float] = None
        if commanded_at is not None:
            try:
                commanded_age_s = (
                    dt_util.utcnow() - commanded_at
                ).total_seconds()
            except Exception:  # noqa: BLE001
                commanded_age_s = None
        out["command_trail"] = {
            surface: {
                "commanded": {
                    "value": commanded_ledger,
                    "age_s": commanded_age_s,
                    # B-HIGH-1 / D-MED-1 fix — derive hold_owner from
                    # REAL state (evse-hold overlay flag, live inclement
                    # decision, arbitrage phase) rather than reading the
                    # invented `_reserve_hold_owner` attribute that never
                    # existed on BatteryStrategy.
                    "hold_owner": (
                        self._resolve_hold_owner(battery_obj)
                        if battery_obj is not None else None
                    ),
                    "live_desire": _live_desire,
                    # Root 1 — expose the EFFECTIVE post-overlay desire
                    # alongside pre-overlay live_desire so the operator
                    # can see which value hardware is actually being
                    # asked for during a hold.
                    "effective_desired": (
                        self._effective_reserve_desired(battery_obj)
                        if battery_obj is not None else None
                    ),
                },
                "hardware_enforced": {
                    "value": hw_val,
                    "age_s": hw_age_s,
                },
                "cloud_oracle": {
                    "value": cloud_val,
                    "age_s": cloud_age_s,
                },
            },
        }
        return out
