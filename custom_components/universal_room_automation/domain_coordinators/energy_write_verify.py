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

        async def _delayed(_now: Any = None) -> None:
            try:
                await self._check(surface, commanded_value, commanded_at)
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "WriteVerifier delayed check raised (swallowed)",
                    exc_info=True,
                )

        try:
            async_call_later(self.hass, self._verify_window_s, _delayed)
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
            return
        # Coalesce: don't re-fire more than once per verify_window_s.
        last = self._last_reversion_at_by_surface.get(surface)
        if last is not None and (now - last) < window:
            return
        self._last_reversion_at_by_surface[surface] = now
        rec = self._records[surface]
        rec.commanded = commanded
        rec.oracle_seen = oracle_raw
        rec.verified_at = now.isoformat()
        rec.status = STATUS_REVERTED
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
                matched = abs(oval_norm - cval) <= 1.0
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
        self, surface: str, title: str, message: str
    ) -> None:
        """Fire NM CRITICAL once per surface per calendar day."""
        today = dt_util.utcnow().date().isoformat()
        if self._nm_trip_date_by_surface.get(surface) == today:
            _LOGGER.debug(
                "WriteVerifier: %s NM alert suppressed (already fired today)",
                surface,
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
            self._nm_trip_date_by_surface[surface] = today
        except Exception:  # noqa: BLE001
            _LOGGER.debug("NM alert failed (swallowed)", exc_info=True)

    # ------------------------------------------------------------------
    # Public accessor consumed by BatteryStrategy.get_status()
    # ------------------------------------------------------------------
    def get_status_attrs(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for surface in WRITE_VERIFY_NM_SURFACES:
            rec = self._records[surface]
            out[f"last_verified_write_{surface}"] = {
                "commanded": rec.commanded,
                "oracle_seen": rec.oracle_seen,
                "verified_at": rec.verified_at,
                "status": rec.status,
            }
        out["write_mismatch_counts_24h"] = {
            s: self._mismatch_counts.value(s)
            for s in WRITE_VERIFY_NM_SURFACES
        }
        return out
