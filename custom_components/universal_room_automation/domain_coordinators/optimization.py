"""Optimization Coordinator — Phase 1 (agentic skeleton).

Phase 1 ships the end-to-end agentic loop running at L1 (Shadow / dry-run)
by default with two dimensions live (Comfort, Sensor Health), the autonomy
matrix gate + kill switch, the handshake broker, and the findings DB store.

No real actuation by default — L1 logs the action it WOULD take + a
predicted effect, scored against the actual subsequent outcome. The
actuation path is fully wired but inert until the operator dials L2+.

Anchors:
- BaseCoordinator contract: domain_coordinators/base.py:154
- TTL handshake: domain_coordinators/hvac_override.py:79, 499, 510
- Activity logger: activity_logger.py:49
- NotificationManager.async_notify: domain_coordinators/notification_manager.py:652

Bug-class guardrails:
- #50: signal unsubs stored on ``self._unsub_listeners`` (BaseCoordinator).
- #9: DB tables only via ``_create_table_safe`` (see database.py).
- #46: per-room comfort sliders write back via established sole-source
  options pattern (see number.py D6 changes).
- #5: sensors register with placeholder state; populate as the first cycle
  finishes.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import (
    async_dispatcher_connect,
    async_dispatcher_send,
)
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from ..const import (
    CONF_COMFORT_HUMIDITY_MAX,
    CONF_COMFORT_TEMP_MAX,
    CONF_COMFORT_TEMP_MIN,
    CONF_ENTRY_TYPE,
    CONF_OPTIMIZER_AUTONOMY_LEVEL,
    CONF_OPTIMIZER_CONFIDENCE_GATE,
    CONF_OPTIMIZER_DIMENSION_AUTONOMY,
    CONF_OPTIMIZER_KILL_SWITCH,
    CONF_OPTIMIZER_QUIET_HOURS_SOURCE,
    CONF_OPTIMIZER_RATE_CAP_PER_HOUR,
    CONF_OCCUPANCY_SENSORS,
    CONF_MOTION_SENSORS,
    CONF_MMWAVE_SENSORS,
    CONF_TEMPERATURE_SENSOR,
    CONF_HUMIDITY_SENSOR,
    COMFORT_HUMIDITY_MAX,
    COMFORT_TEMP_MAX,
    COMFORT_TEMP_MIN,
    DEFAULT_OPTIMIZER_AUTONOMY_LEVEL,
    DEFAULT_OPTIMIZER_CONFIDENCE_GATE,
    DEFAULT_OPTIMIZER_PRIORITY,
    DEFAULT_OPTIMIZER_QUIET_HOURS_SOURCE,
    DEFAULT_OPTIMIZER_RATE_CAP_PER_HOUR,
    DEFAULT_OPTIMIZER_KILL_SWITCH,
    DOMAIN,
    ENTRY_TYPE_COORDINATOR_MANAGER,
    ENTRY_TYPE_ROOM,
    OPTIMIZER_ALLOWED_DOMAINS_CONFIG,
    OPTIMIZER_ALLOWED_DOMAINS_DEVICE,
    OPTIMIZER_AUTONOMY_LEVELS,
    OPTIMIZER_CONFIG_CLAMP_FRACTION,
    OPTIMIZER_DIMENSION_COMFORT,
    OPTIMIZER_DIMENSION_META,
    OPTIMIZER_DIMENSION_SENSOR_HEALTH,
    OPTIMIZER_LEVEL_ADVISORY,
    OPTIMIZER_LEVEL_IMMEDIATE_CONFIG,
    OPTIMIZER_LEVEL_PROPOSE_CONFIG,
    OPTIMIZER_LEVEL_RANK,
    OPTIMIZER_LEVEL_REVERSIBLE_DEVICE,
    OPTIMIZER_LEVEL_SHADOW,
    OPTIMIZER_LEVEL_UNBOUNDED,
    OPTIMIZER_OUTCOME_ADVISORY_ONLY,
    OPTIMIZER_OUTCOME_APPLIED,
    OPTIMIZER_OUTCOME_BELOW_GATE,
    OPTIMIZER_OUTCOME_DISALLOWED,
    OPTIMIZER_OUTCOME_DOMAIN_BLOCKED,
    OPTIMIZER_OUTCOME_FAILED,
    OPTIMIZER_OUTCOME_KILL_SWITCH,
    OPTIMIZER_OUTCOME_QUIET_CLAMPED,
    OPTIMIZER_OUTCOME_RATE_CAPPED,
    OPTIMIZER_OUTCOME_SHADOW,
    OPTIMIZER_OUTCOME_VETOED,
    OPTIMIZER_QUIET_HOURS_SOURCE_REUSE_NM,
    SCAN_INTERVAL_OPTIMIZATION,
)
from .base import (
    BaseCoordinator,
    CoordinatorAction,
    Intent,
    ServiceCallAction,
    Severity,
)
from .signals import (
    SIGNAL_OPTIMIZER_FINDING_EMITTED,
    SIGNAL_OPTIMIZER_INTENT,
    SIGNAL_OPTIMIZER_INTENT_VETO,
)

_LOGGER = logging.getLogger(__name__)


# ============================================================================
# Dimension enum (kept as a plain Enum / str so duck-typed callers continue
# to work; behaves like a StrEnum for serialization).
# ============================================================================


class OptimizationDimension(str, Enum):
    """Optimization dimensions emitted by the Phase-1 rule engine."""

    SENSOR_HEALTH = OPTIMIZER_DIMENSION_SENSOR_HEALTH
    COMFORT = OPTIMIZER_DIMENSION_COMFORT
    META = OPTIMIZER_DIMENSION_META

    def __str__(self) -> str:  # noqa: D401
        return self.value


# Severity → string mapping used in DB rows and NM routing.
_SEVERITY_NAME = {
    "low": "low",
    "medium": "medium",
    "high": "high",
    "critical": "critical",
}


# ============================================================================
# OptimizationFinding dataclass
# ============================================================================


@dataclass
class OptimizationFinding:
    """A single optimization finding emitted by the Phase-1 rule engine."""

    timestamp: str
    level: str  # room | zone | house
    target_id: str | None
    dimension: OptimizationDimension | str
    severity: str  # low | medium | high | critical
    confidence: float
    score: float
    description: str
    proposed_action: dict | None = None
    action_class: str | None = None  # reversible_device | config_write
    applied_action_id: str | None = None
    applied_outcome: str | None = None
    predicted_effect: dict | None = None
    observed_effect: dict | None = None
    payload: dict | None = None
    created_by: str = "tier1"
    # Dedup key: (level, target_id, dimension, sub_entity_id_or_none)
    dedup_key: tuple | None = None


# ============================================================================
# OptimizerIntentBroker
# ============================================================================


class OptimizerIntentBroker:
    """Handshake broker — emits intent signal, awaits sibling veto, suppresses HVAC.

    Two responsibilities:
    1. Before an L2+ actuation: dispatch ``SIGNAL_OPTIMIZER_INTENT`` and
       (for L3 propose-config) wait ``veto_window_s`` for any sibling to
       fire ``SIGNAL_OPTIMIZER_INTENT_VETO`` matching ``action_id``.
    2. At dispatch time: if the target is a ``climate.*`` entity owned by a
       Zone, call ``OverrideArrester.suppress(entity)`` to open the TTL
       window; always pair with ``unsuppress()`` on error paths.

    At L1 (Shadow), the broker emits the intent payload as a
    ``shadow_dry_run`` event so siblings + the future LLM Tier-2 can learn
    against a real signal stream, but no service call is ever dispatched.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the broker."""
        self.hass = hass
        self._pending_vetoes: dict[str, str] = {}
        self._veto_unsub = None

    def async_start(self) -> None:
        """Subscribe to the veto signal once at coordinator setup."""
        if self._veto_unsub is None:
            self._veto_unsub = async_dispatcher_connect(
                self.hass,
                SIGNAL_OPTIMIZER_INTENT_VETO,
                self._on_veto,
            )

    def async_stop(self) -> None:
        """Unsubscribe at coordinator teardown."""
        if self._veto_unsub is not None:
            try:
                self._veto_unsub()
            except Exception:  # noqa: BLE001 — defensive teardown
                _LOGGER.debug("Veto unsub raised", exc_info=True)
            self._veto_unsub = None

    @property
    def veto_unsub(self):
        """Expose the unsub handle so the coordinator can register it on
        ``self._unsub_listeners`` (Bug Class #50 guardrail)."""
        return self._veto_unsub

    def _on_veto(self, payload: dict) -> None:
        action_id = payload.get("action_id") if isinstance(payload, dict) else None
        if not action_id:
            return
        self._pending_vetoes[action_id] = (
            payload.get("vetoed_by", "unknown")
            if isinstance(payload, dict)
            else "unknown"
        )

    def _get_arrester(self):
        """Return the HVAC OverrideArrester if present, else None."""
        try:
            hvac = self.hass.data.get(DOMAIN, {}).get("hvac_coordinator")
            if hvac is None:
                return None
            return getattr(hvac, "override_arrester", None)
        except Exception:  # noqa: BLE001 — never crash dispatch
            return None

    def _maybe_suppress(self, target_entity: str) -> bool:
        """Open the TTL handshake window for a climate target; safe no-op
        for non-climate entities or when no arrester is present."""
        if not target_entity or not target_entity.startswith("climate."):
            return False
        arrester = self._get_arrester()
        if arrester is None:
            return False
        try:
            arrester.suppress(target_entity)
            return True
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "OverrideArrester.suppress(%s) raised", target_entity,
                exc_info=True,
            )
            return False

    def _maybe_unsuppress(self, target_entity: str) -> None:
        """Close the TTL window — used on error paths so a failed write
        doesn't sit suppressed for the rest of the TTL."""
        if not target_entity or not target_entity.startswith("climate."):
            return
        arrester = self._get_arrester()
        if arrester is None:
            return
        try:
            arrester.unsuppress(target_entity)
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "OverrideArrester.unsuppress(%s) raised", target_entity,
                exc_info=True,
            )

    def fire_intent(
        self,
        action_id: str,
        target_entity: str,
        service: str,
        service_data: dict,
        source_dimension: str,
        veto_window_s: int,
        action_class: str,
        effective_level: str,
    ) -> None:
        """Dispatch SIGNAL_OPTIMIZER_INTENT with the full payload."""
        payload = {
            "action_id": action_id,
            "target_entity": target_entity,
            "service": service,
            "service_data": dict(service_data) if service_data else {},
            "source_dimension": source_dimension,
            "proposed_at_iso": dt_util.utcnow().isoformat(),
            "veto_window_s": int(veto_window_s),
            "action_class": action_class,
            "effective_level": effective_level,
        }
        try:
            async_dispatcher_send(self.hass, SIGNAL_OPTIMIZER_INTENT, payload)
        except Exception:  # noqa: BLE001
            _LOGGER.debug("SIGNAL_OPTIMIZER_INTENT dispatch failed",
                          exc_info=True)

    async def await_veto(
        self, action_id: str, veto_window_s: int,
    ) -> str | None:
        """Wait up to ``veto_window_s`` seconds for a matching veto.

        Returns the ``vetoed_by`` string if vetoed, else None.
        """
        if veto_window_s <= 0:
            return self._pending_vetoes.pop(action_id, None)
        # Poll at small intervals so siblings can veto inside the window.
        deadline = dt_util.utcnow() + timedelta(seconds=veto_window_s)
        while dt_util.utcnow() < deadline:
            if action_id in self._pending_vetoes:
                return self._pending_vetoes.pop(action_id)
            await asyncio.sleep(0.1)
        return self._pending_vetoes.pop(action_id, None)


# ============================================================================
# OptimizationCoordinator
# ============================================================================


class OptimizationCoordinator(BaseCoordinator):
    """Phase-1 agentic optimizer coordinator.

    Implements the matrix gate at the SINGLE chokepoint ``_apply_action``.
    No path bypasses the gate — every dispatched action goes through it.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the optimization coordinator."""
        super().__init__(
            hass,
            coordinator_id="optimization",
            name="Optimization Coordinator",
            priority=DEFAULT_OPTIMIZER_PRIORITY,
        )

        # Broker — lazily started in ``async_setup`` so the unsub lands on
        # ``self._unsub_listeners`` per Bug Class #50.
        self.broker = OptimizerIntentBroker(hass)

        # Rolling-hour action history for the rate cap.
        self._action_dispatch_history: deque[datetime] = deque()

        # Dedup of findings within a cycle so the same `(room, dimension,
        # entity_id)` triple only emits once per cycle.
        self._cycle_dedup: set[tuple] = set()

        # Most recent house-level summary for sensor consumption.
        self._last_findings: list[OptimizationFinding] = []
        self._last_evaluation_iso: str | None = None
        self._house_score: float = 100.0
        self._room_scores: dict[str, float] = {}
        self._open_findings_count: int = 0

        # Per-room sustained-comfort tracking (out-of-range timestamps).
        self._comfort_out_since: dict[tuple, datetime] = {}
        # Per-room sustained-sensor-stuck tracking.
        self._sensor_stuck_since: dict[tuple, datetime] = {}

        # Cycle handle.
        self._cycle_unsub = None

    # ------------------------------------------------------------------
    # BaseCoordinator contract
    # ------------------------------------------------------------------

    async def async_setup(self) -> None:
        """Start the broker + schedule the 5-min cycle."""
        self.broker.async_start()
        # Register broker veto unsub on the bug-class-#50-safe listener
        # list (BaseCoordinator clears this on teardown only).
        if self.broker.veto_unsub is not None:
            self._unsub_listeners.append(self.broker.veto_unsub)

        # 5-min cycle (matches plan D1). Scheduled via HA's tracker so the
        # unsub goes on the BaseCoordinator listener list.
        self._cycle_unsub = async_track_time_interval(
            self.hass,
            self._on_cycle_tick,
            SCAN_INTERVAL_OPTIMIZATION,
        )
        self._unsub_listeners.append(self._cycle_unsub)

        _LOGGER.info("Coordinator optimization started (priority=%d, cycle=%ds)",
                     self.priority,
                     int(SCAN_INTERVAL_OPTIMIZATION.total_seconds()))

    async def evaluate(
        self,
        intents: list[Intent],
        context: dict[str, Any],
    ) -> list[CoordinatorAction]:
        """Optimizer does not participate in the per-intent dispatch flow.

        Returns an empty list — the optimizer's actuation path is the
        5-min cycle running through ``_apply_action``, not the BaseCoord
        intent->action loop.
        """
        return []

    async def async_teardown(self) -> None:
        """Cancel timers + unsubscribe from signals."""
        self.broker.async_stop()
        self._cancel_listeners()

    # ------------------------------------------------------------------
    # Cycle entrypoint
    # ------------------------------------------------------------------

    async def _on_cycle_tick(self, _now=None) -> None:
        """Single 5-min cycle: read substrate → run rules → apply."""
        try:
            await self.run_cycle()
        except Exception as exc:  # noqa: BLE001 — defensive
            _LOGGER.warning("Optimization cycle failed: %s", exc, exc_info=True)

    async def run_cycle(self) -> list[OptimizationFinding]:
        """Public test entry point — run one optimizer cycle.

        Returns the list of findings emitted this cycle (for tests).
        """
        self._cycle_dedup.clear()
        findings: list[OptimizationFinding] = []
        findings.extend(self._evaluate_sensor_health_dimension())
        findings.extend(self._evaluate_comfort_dimension())

        # D5 sentinel — emit one `meta` finding per cycle so silent-failure
        # (no rule ever fires) is distinguishable from "rule ran, no
        # issues". Review D's anti-sentinel-only check expects this row
        # plus real rows; sentinels-only means upstream is broken.
        findings.append(
            OptimizationFinding(
                timestamp=dt_util.utcnow().isoformat(),
                level="house",
                target_id="house",
                dimension=OptimizationDimension.META,
                severity="low",
                confidence=1.0,
                score=100.0,
                description="cycle_ok",
                created_by="tier1",
            )
        )

        # Score + persist + (optionally) dispatch each finding.
        self._update_scoreboard(findings)

        for finding in findings:
            await self._persist_finding(finding)
            await self._consider_apply(finding)
            self._dispatch_finding_signal(finding)
            await self._notify_if_severe(finding)

        self._last_findings = findings
        self._last_evaluation_iso = dt_util.utcnow().isoformat()
        return findings

    # ------------------------------------------------------------------
    # Substrate readers
    # ------------------------------------------------------------------

    def _iter_room_entries(self):
        """Yield ConfigEntry objects for ENTRY_TYPE_ROOM, guarded for tests."""
        try:
            entries = self.hass.config_entries.async_entries(DOMAIN)
        except Exception:  # noqa: BLE001
            return
        for entry in entries or []:
            try:
                if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ROOM:
                    yield entry
            except Exception:  # noqa: BLE001
                continue

    def _read_per_room_comfort(self, entry) -> dict:
        """Return ``{min, max, hum_max}`` for a room — D6 helper.

        Precedence: ``entry.options[key]`` → ``entry.data[key]`` → module
        constant fallback. The Comfort rule calls this exclusively; it
        never reads the module constants directly.
        """
        opts = getattr(entry, "options", {}) or {}
        data = getattr(entry, "data", {}) or {}

        def _pick(key, fallback):
            if key in opts and opts[key] is not None:
                return opts[key]
            if key in data and data[key] is not None:
                return data[key]
            return fallback

        return {
            "min": float(_pick(CONF_COMFORT_TEMP_MIN, COMFORT_TEMP_MIN)),
            "max": float(_pick(CONF_COMFORT_TEMP_MAX, COMFORT_TEMP_MAX)),
            "hum_max": float(_pick(
                CONF_COMFORT_HUMIDITY_MAX, COMFORT_HUMIDITY_MAX,
            )),
        }

    def _room_name(self, entry) -> str:
        try:
            return (
                entry.data.get("room_name")
                or entry.data.get("name")
                or entry.entry_id
            )
        except Exception:  # noqa: BLE001
            return getattr(entry, "entry_id", "unknown")

    def _state_value(self, entity_id: str):
        if not entity_id:
            return None
        try:
            st = self.hass.states.get(entity_id)
            if st is None:
                return None
            return st
        except Exception:  # noqa: BLE001
            return None

    def _is_room_occupied(self, entry) -> bool:
        """Best-effort: any configured occupancy/motion/mmwave sensor is `on`."""
        merged = {**(entry.data or {}), **(entry.options or {})}
        ids: list[str] = []
        for key in (CONF_OCCUPANCY_SENSORS, CONF_MOTION_SENSORS,
                    CONF_MMWAVE_SENSORS):
            val = merged.get(key)
            if isinstance(val, list):
                ids.extend(val)
            elif isinstance(val, str) and val:
                ids.append(val)
        for eid in ids:
            st = self._state_value(eid)
            if st is None:
                continue
            if str(st.state).lower() in ("on", "true", "occupied", "home"):
                return True
        return False

    # ------------------------------------------------------------------
    # Rule engine — Phase 1 dimensions
    # ------------------------------------------------------------------

    def _evaluate_sensor_health_dimension(self) -> list[OptimizationFinding]:
        """Per room: configured sensors stuck unavailable/unknown >60s → high."""
        findings: list[OptimizationFinding] = []
        now = dt_util.utcnow()
        for entry in self._iter_room_entries():
            merged = {**(entry.data or {}), **(entry.options or {})}
            room = self._room_name(entry)
            tracked: list[str] = []
            for key in (CONF_TEMPERATURE_SENSOR, CONF_HUMIDITY_SENSOR,
                        CONF_OCCUPANCY_SENSORS, CONF_MOTION_SENSORS,
                        CONF_MMWAVE_SENSORS):
                val = merged.get(key)
                if isinstance(val, list):
                    tracked.extend([v for v in val if isinstance(v, str)])
                elif isinstance(val, str) and val:
                    tracked.append(val)
            for eid in tracked:
                st = self._state_value(eid)
                state_str = "" if st is None else str(st.state).lower()
                stuck = (st is None) or state_str in ("unavailable", "unknown")
                key = ("sensor_health", room, eid)
                if stuck:
                    first_seen = self._sensor_stuck_since.get(key)
                    if first_seen is None:
                        self._sensor_stuck_since[key] = now
                        continue  # need >60s sustained
                    if (now - first_seen).total_seconds() < 60:
                        continue
                    dedup_key = ("sensor_health", room, eid)
                    if dedup_key in self._cycle_dedup:
                        continue
                    self._cycle_dedup.add(dedup_key)
                    findings.append(OptimizationFinding(
                        timestamp=now.isoformat(),
                        level="room",
                        target_id=room,
                        dimension=OptimizationDimension.SENSOR_HEALTH,
                        severity="high",
                        confidence=0.95,
                        score=0.0,
                        description=(
                            f"Sensor {eid} stuck "
                            f"{state_str or 'missing'} >60s"
                        ),
                        proposed_action=None,  # advisory in Phase 1
                        payload={"entity_id": eid, "stuck_state": state_str},
                        dedup_key=dedup_key,
                    ))
                else:
                    self._sensor_stuck_since.pop(key, None)
        return findings

    def _evaluate_comfort_dimension(self) -> list[OptimizationFinding]:
        """Per room: per-room slider vs room temp/humidity when occupied;
        out-of-range ≥10min sustained → medium."""
        findings: list[OptimizationFinding] = []
        now = dt_util.utcnow()
        for entry in self._iter_room_entries():
            merged = {**(entry.data or {}), **(entry.options or {})}
            room = self._room_name(entry)
            if not self._is_room_occupied(entry):
                # Clear any sustained-trackers for this room.
                for k in list(self._comfort_out_since):
                    if len(k) >= 2 and k[1] == room:
                        self._comfort_out_since.pop(k, None)
                continue

            comfort = self._read_per_room_comfort(entry)
            temp_eid = merged.get(CONF_TEMPERATURE_SENSOR)
            hum_eid = merged.get(CONF_HUMIDITY_SENSOR)

            def _float_or_none(st):
                if st is None:
                    return None
                try:
                    return float(st.state)
                except (TypeError, ValueError):
                    return None

            temp_val = _float_or_none(self._state_value(temp_eid))
            hum_val = _float_or_none(self._state_value(hum_eid))

            # Temperature check — out of [min, max].
            if temp_val is not None and temp_eid:
                out = temp_val < comfort["min"] or temp_val > comfort["max"]
                key = ("comfort_temp", room, temp_eid)
                if out:
                    since = self._comfort_out_since.get(key)
                    if since is None:
                        self._comfort_out_since[key] = now
                    elif (now - since).total_seconds() >= 600:
                        dedup_key = (
                            "comfort", room, temp_eid,
                        )
                        if dedup_key not in self._cycle_dedup:
                            self._cycle_dedup.add(dedup_key)
                            findings.append(OptimizationFinding(
                                timestamp=now.isoformat(),
                                level="room",
                                target_id=room,
                                dimension=OptimizationDimension.COMFORT,
                                severity="medium",
                                confidence=0.8,
                                score=0.0,
                                description=(
                                    f"{room} temp {temp_val}°F out of "
                                    f"[{comfort['min']}, {comfort['max']}] "
                                    f"sustained"
                                ),
                                proposed_action=None,
                                payload={
                                    "entity_id": temp_eid,
                                    "value": temp_val,
                                    "bounds": [comfort["min"], comfort["max"]],
                                },
                                dedup_key=dedup_key,
                            ))
                else:
                    self._comfort_out_since.pop(key, None)

            # Humidity check — only upper bound.
            if hum_val is not None and hum_eid:
                out = hum_val > comfort["hum_max"]
                key = ("comfort_hum", room, hum_eid)
                if out:
                    since = self._comfort_out_since.get(key)
                    if since is None:
                        self._comfort_out_since[key] = now
                    elif (now - since).total_seconds() >= 600:
                        dedup_key = ("comfort_hum", room, hum_eid)
                        if dedup_key not in self._cycle_dedup:
                            self._cycle_dedup.add(dedup_key)
                            findings.append(OptimizationFinding(
                                timestamp=now.isoformat(),
                                level="room",
                                target_id=room,
                                dimension=OptimizationDimension.COMFORT,
                                severity="medium",
                                confidence=0.7,
                                score=0.0,
                                description=(
                                    f"{room} humidity {hum_val}% > "
                                    f"{comfort['hum_max']}% sustained"
                                ),
                                proposed_action=None,
                                payload={
                                    "entity_id": hum_eid,
                                    "value": hum_val,
                                    "upper_bound": comfort["hum_max"],
                                },
                                dedup_key=dedup_key,
                            ))
                else:
                    self._comfort_out_since.pop(key, None)

        return findings

    # ------------------------------------------------------------------
    # Matrix gate + dispatch chokepoint
    # ------------------------------------------------------------------

    def _read_cm_config(self) -> dict:
        """Read the CM entry's effective config (data merged with options)."""
        try:
            for entry in self.hass.config_entries.async_entries(DOMAIN):
                if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_COORDINATOR_MANAGER:
                    return {**(entry.data or {}), **(entry.options or {})}
        except Exception:  # noqa: BLE001
            pass
        return {}

    def _read_cm_entry(self):
        try:
            for entry in self.hass.config_entries.async_entries(DOMAIN):
                if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_COORDINATOR_MANAGER:
                    return entry
        except Exception:  # noqa: BLE001
            return None
        return None

    def _is_quiet_hours_active(self) -> bool:
        """Read NM's `is quiet now?` predicate. REUSES NM's single source of truth."""
        try:
            nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
            if nm is None:
                return False
            return bool(nm._is_quiet_hours())
        except Exception:  # noqa: BLE001
            return False

    def _rate_cap_window_count(self) -> int:
        """Count dispatches in the rolling 1h window (also evicts stale)."""
        cutoff = dt_util.utcnow() - timedelta(hours=1)
        while self._action_dispatch_history and self._action_dispatch_history[0] < cutoff:
            self._action_dispatch_history.popleft()
        return len(self._action_dispatch_history)

    @property
    def effective_level(self) -> str:
        """Compute effective level (post-kill-switch, post-quiet, post-rate-cap)."""
        config = self._read_cm_config()
        configured = config.get(
            CONF_OPTIMIZER_AUTONOMY_LEVEL, DEFAULT_OPTIMIZER_AUTONOMY_LEVEL,
        )
        if configured not in OPTIMIZER_AUTONOMY_LEVELS:
            configured = DEFAULT_OPTIMIZER_AUTONOMY_LEVEL

        # Kill switch — synchronous clamp to L0.
        if bool(config.get(
            CONF_OPTIMIZER_KILL_SWITCH, DEFAULT_OPTIMIZER_KILL_SWITCH,
        )):
            return OPTIMIZER_LEVEL_ADVISORY

        # Quiet hours — clamp to min(configured, L1).
        qh_source = config.get(
            CONF_OPTIMIZER_QUIET_HOURS_SOURCE,
            DEFAULT_OPTIMIZER_QUIET_HOURS_SOURCE,
        )
        if (qh_source == OPTIMIZER_QUIET_HOURS_SOURCE_REUSE_NM
                and self._is_quiet_hours_active()):
            configured = self._min_level(configured, OPTIMIZER_LEVEL_SHADOW)

        # Rate cap — when cap hit, clamp L2+ to L1.
        cap = int(config.get(
            CONF_OPTIMIZER_RATE_CAP_PER_HOUR,
            DEFAULT_OPTIMIZER_RATE_CAP_PER_HOUR,
        ))
        if self._rate_cap_window_count() >= cap:
            configured = self._min_level(configured, OPTIMIZER_LEVEL_SHADOW)

        return configured

    @staticmethod
    def _min_level(a: str, b: str) -> str:
        ra = OPTIMIZER_LEVEL_RANK.get(a, 0)
        rb = OPTIMIZER_LEVEL_RANK.get(b, 0)
        if ra <= rb:
            return a
        return b

    @staticmethod
    def _level_at_least(level: str, threshold: str) -> bool:
        return OPTIMIZER_LEVEL_RANK.get(level, 0) >= OPTIMIZER_LEVEL_RANK.get(threshold, 0)

    def _per_dimension_cap(self, dimension: str) -> str | None:
        """Read the per-dimension cap dict from CM options; return None for `no cap`."""
        config = self._read_cm_config()
        dim_map = config.get(CONF_OPTIMIZER_DIMENSION_AUTONOMY) or {}
        if not isinstance(dim_map, dict):
            return None
        cap = dim_map.get(str(dimension))
        if cap not in OPTIMIZER_AUTONOMY_LEVELS:
            return None
        return cap

    def _confidence_gate(self) -> float:
        config = self._read_cm_config()
        try:
            return float(config.get(
                CONF_OPTIMIZER_CONFIDENCE_GATE,
                DEFAULT_OPTIMIZER_CONFIDENCE_GATE,
            ))
        except (TypeError, ValueError):
            return DEFAULT_OPTIMIZER_CONFIDENCE_GATE

    def _clamp_numeric_to_band(
        self, target_entity: str, proposed_value: float,
    ) -> float:
        """L3+ ±20% clamp around the current value (or proposed if no current)."""
        st = self._state_value(target_entity)
        current = None
        if st is not None:
            try:
                current = float(st.state)
            except (TypeError, ValueError):
                current = None
        if current is None:
            return proposed_value
        band = abs(current) * OPTIMIZER_CONFIG_CLAMP_FRACTION
        lo = current - band
        hi = current + band
        if proposed_value < lo:
            return lo
        if proposed_value > hi:
            return hi
        return proposed_value

    # ------------------------------------------------------------------
    # Single chokepoint
    # ------------------------------------------------------------------

    async def _apply_action(
        self,
        finding: OptimizationFinding,
        action: dict,
    ) -> str:
        """The single chokepoint — every dispatched action goes through here.

        ``action`` shape: ``{service, service_data, target_entity,
        action_class}`` where ``action_class`` ∈ {``reversible_device``,
        ``config_write``}.

        Returns the ``applied_outcome`` string (one of the
        OPTIMIZER_OUTCOME_* enum values) and updates the finding in-place.
        """
        action_id = uuid.uuid4().hex
        finding.applied_action_id = action_id
        finding.proposed_action = dict(action)

        target_entity = action.get("target_entity") or ""
        service = action.get("service") or ""
        service_data = dict(action.get("service_data") or {})
        action_class = action.get("action_class") or "reversible_device"
        finding.action_class = action_class

        domain = service.split(".", 1)[0] if "." in service else ""

        # Compute effective level (post-clamp).
        level = self.effective_level
        # Per-dimension cap further reduces it.
        per_dim_cap = self._per_dimension_cap(str(finding.dimension))
        if per_dim_cap is not None:
            level = self._min_level(level, per_dim_cap)

        # Kill switch already clamps `effective_level` to advisory.
        cm_config = self._read_cm_config()
        if bool(cm_config.get(
            CONF_OPTIMIZER_KILL_SWITCH, DEFAULT_OPTIMIZER_KILL_SWITCH,
        )):
            outcome = OPTIMIZER_OUTCOME_KILL_SWITCH
            finding.applied_outcome = outcome
            await self._log_activity(
                action="advisory_only", importance="info",
                description=f"kill_switch_engaged: {finding.description}",
                details={"action_id": action_id, "reason": outcome,
                         "level": level},
                finding=finding,
            )
            return outcome

        # Confidence gate.
        gate = self._confidence_gate()
        if finding.confidence < gate:
            outcome = OPTIMIZER_OUTCOME_ADVISORY_ONLY
            finding.applied_outcome = outcome
            await self._log_activity(
                action="clamped", importance="info",
                description=finding.description,
                details={"action_id": action_id,
                         "reason": OPTIMIZER_OUTCOME_BELOW_GATE,
                         "confidence": finding.confidence,
                         "gate": gate,
                         "level": level},
                finding=finding,
            )
            return outcome

        # L0 advisory — log only, no dispatch.
        if level == OPTIMIZER_LEVEL_ADVISORY:
            finding.applied_outcome = OPTIMIZER_OUTCOME_ADVISORY_ONLY
            await self._log_activity(
                action="advisory_only", importance="info",
                description=finding.description,
                details={"action_id": action_id,
                         "target_entity": target_entity, "service": service,
                         "level": level},
                finding=finding,
            )
            return OPTIMIZER_OUTCOME_ADVISORY_ONLY

        # Domain allowlist enforcement — L2/L3 split is load-bearing.
        if action_class == "reversible_device":
            if domain not in OPTIMIZER_ALLOWED_DOMAINS_DEVICE:
                finding.applied_outcome = OPTIMIZER_OUTCOME_DOMAIN_BLOCKED
                await self._log_activity(
                    action="clamped", importance="info",
                    description=f"domain blocked: {service}",
                    details={"action_id": action_id, "level": level,
                             "reason": OPTIMIZER_OUTCOME_DOMAIN_BLOCKED},
                    finding=finding,
                )
                return OPTIMIZER_OUTCOME_DOMAIN_BLOCKED
            # L2 entry requirement.
            if not self._level_at_least(level, OPTIMIZER_LEVEL_REVERSIBLE_DEVICE):
                # We are at L1 shadow — emit intent dry-run + log.
                self.broker.fire_intent(
                    action_id, target_entity, service, service_data,
                    source_dimension=str(finding.dimension),
                    veto_window_s=0, action_class=action_class,
                    effective_level=level,
                )
                finding.applied_outcome = OPTIMIZER_OUTCOME_SHADOW
                finding.predicted_effect = {
                    "service": service,
                    "service_data": service_data,
                    "note": "shadow_dry_run — no dispatch",
                }
                await self._log_activity(
                    action="shadow_dry_run", importance="info",
                    description=finding.description,
                    details={"action_id": action_id, "level": level,
                             "target_entity": target_entity,
                             "service": service,
                             "predicted_effect": finding.predicted_effect,
                             "dimension": str(finding.dimension)},
                    finding=finding,
                )
                return OPTIMIZER_OUTCOME_SHADOW
            # L2+ device dispatch path.
            return await self._dispatch_device_action(
                finding, action_id, target_entity, service, service_data,
                level,
            )

        elif action_class == "config_write":
            if domain not in OPTIMIZER_ALLOWED_DOMAINS_CONFIG:
                finding.applied_outcome = OPTIMIZER_OUTCOME_DOMAIN_BLOCKED
                await self._log_activity(
                    action="clamped", importance="info",
                    description=f"config domain blocked: {service}",
                    details={"action_id": action_id, "level": level,
                             "reason": OPTIMIZER_OUTCOME_DOMAIN_BLOCKED},
                    finding=finding,
                )
                return OPTIMIZER_OUTCOME_DOMAIN_BLOCKED
            # CRITICAL: L2 must REJECT config writes with explicit reason.
            if not self._level_at_least(level, OPTIMIZER_LEVEL_PROPOSE_CONFIG):
                outcome = OPTIMIZER_OUTCOME_DISALLOWED
                finding.applied_outcome = outcome
                await self._log_activity(
                    action="clamped", importance="info",
                    description=f"config_write blocked at {level}",
                    details={"action_id": action_id, "level": level,
                             "reason": outcome,
                             "target_entity": target_entity,
                             "service": service},
                    finding=finding,
                )
                return outcome
            return await self._dispatch_config_action(
                finding, action_id, target_entity, service, service_data,
                level,
            )

        else:
            finding.applied_outcome = OPTIMIZER_OUTCOME_FAILED
            await self._log_activity(
                action="clamped", importance="info",
                description=f"unknown action_class={action_class}",
                details={"action_id": action_id, "level": level},
                finding=finding,
            )
            return OPTIMIZER_OUTCOME_FAILED

    async def _dispatch_device_action(
        self,
        finding: OptimizationFinding,
        action_id: str,
        target_entity: str,
        service: str,
        service_data: dict,
        level: str,
    ) -> str:
        """L2+ device dispatch — fires intent, awaits veto (L3 only), calls service."""
        veto_window = 0
        if level == OPTIMIZER_LEVEL_PROPOSE_CONFIG:
            from ..const import OPTIMIZER_VETO_WINDOW_SECONDS_L3
            veto_window = OPTIMIZER_VETO_WINDOW_SECONDS_L3

        self.broker.fire_intent(
            action_id, target_entity, service, service_data,
            source_dimension=str(finding.dimension),
            veto_window_s=veto_window, action_class="reversible_device",
            effective_level=level,
        )
        await self._log_activity(
            action="proposed", importance="notable",
            description=finding.description,
            details={"action_id": action_id, "level": level,
                     "target_entity": target_entity, "service": service,
                     "dimension": str(finding.dimension)},
            finding=finding,
        )

        if veto_window > 0:
            vetoed_by = await self.broker.await_veto(action_id, veto_window)
            if vetoed_by is not None:
                finding.applied_outcome = OPTIMIZER_OUTCOME_VETOED
                await self._log_activity(
                    action="proposed_vetoed", importance="notable",
                    description=finding.description,
                    details={"action_id": action_id, "level": level,
                             "vetoed_by": vetoed_by},
                    finding=finding,
                )
                return OPTIMIZER_OUTCOME_VETOED

        # Open HVAC TTL window (no-op for non-climate).
        self.broker._maybe_suppress(target_entity)
        domain = service.split(".", 1)[0]
        action_name = service.split(".", 1)[1] if "." in service else ""
        try:
            data = dict(service_data)
            if target_entity and "entity_id" not in data:
                data["entity_id"] = target_entity
            await self.hass.services.async_call(
                domain, action_name, data, blocking=False,
            )
            finding.applied_outcome = OPTIMIZER_OUTCOME_APPLIED
            self._action_dispatch_history.append(dt_util.utcnow())
            await self._log_activity(
                action="actuated", importance="notable",
                description=finding.description,
                details={"action_id": action_id, "level": level,
                         "target_entity": target_entity, "service": service},
                finding=finding,
            )
            return OPTIMIZER_OUTCOME_APPLIED
        except Exception as exc:  # noqa: BLE001
            self.broker._maybe_unsuppress(target_entity)
            finding.applied_outcome = OPTIMIZER_OUTCOME_FAILED
            _LOGGER.warning("Optimizer dispatch failed %s: %s", service, exc)
            await self._log_activity(
                action="clamped", importance="notable",
                description=f"dispatch failed: {exc}",
                details={"action_id": action_id, "level": level,
                         "reason": "dispatch_failure"},
                finding=finding,
            )
            return OPTIMIZER_OUTCOME_FAILED

    async def _dispatch_config_action(
        self,
        finding: OptimizationFinding,
        action_id: str,
        target_entity: str,
        service: str,
        service_data: dict,
        level: str,
    ) -> str:
        """L3+ config-write dispatch — ±20% clamp + veto window for L3."""
        # ±20% numeric clamp.
        clamped_data = dict(service_data)
        clamped = False
        if "value" in clamped_data:
            try:
                proposed = float(clamped_data["value"])
                new_value = self._clamp_numeric_to_band(target_entity, proposed)
                if new_value != proposed:
                    clamped = True
                clamped_data["value"] = new_value
            except (TypeError, ValueError):
                pass

        veto_window = 0
        if level == OPTIMIZER_LEVEL_PROPOSE_CONFIG:
            from ..const import OPTIMIZER_VETO_WINDOW_SECONDS_L3
            veto_window = OPTIMIZER_VETO_WINDOW_SECONDS_L3

        self.broker.fire_intent(
            action_id, target_entity, service, clamped_data,
            source_dimension=str(finding.dimension),
            veto_window_s=veto_window, action_class="config_write",
            effective_level=level,
        )
        await self._log_activity(
            action="proposed", importance="notable",
            description=finding.description,
            details={"action_id": action_id, "level": level,
                     "target_entity": target_entity, "service": service,
                     "clamped": clamped, "service_data": clamped_data,
                     "dimension": str(finding.dimension)},
            finding=finding,
        )

        if veto_window > 0:
            vetoed_by = await self.broker.await_veto(action_id, veto_window)
            if vetoed_by is not None:
                finding.applied_outcome = OPTIMIZER_OUTCOME_VETOED
                await self._log_activity(
                    action="proposed_vetoed", importance="notable",
                    description=finding.description,
                    details={"action_id": action_id, "level": level,
                             "vetoed_by": vetoed_by},
                    finding=finding,
                )
                return OPTIMIZER_OUTCOME_VETOED

        domain = service.split(".", 1)[0]
        action_name = service.split(".", 1)[1] if "." in service else ""
        try:
            data = dict(clamped_data)
            if target_entity and "entity_id" not in data:
                data["entity_id"] = target_entity
            await self.hass.services.async_call(
                domain, action_name, data, blocking=False,
            )
            finding.applied_outcome = OPTIMIZER_OUTCOME_APPLIED
            self._action_dispatch_history.append(dt_util.utcnow())
            await self._log_activity(
                action="actuated", importance="notable",
                description=finding.description,
                details={"action_id": action_id, "level": level,
                         "target_entity": target_entity, "service": service,
                         "clamped": clamped},
                finding=finding,
            )
            return OPTIMIZER_OUTCOME_APPLIED
        except Exception as exc:  # noqa: BLE001
            finding.applied_outcome = OPTIMIZER_OUTCOME_FAILED
            await self._log_activity(
                action="clamped", importance="notable",
                description=f"config_write dispatch failed: {exc}",
                details={"action_id": action_id, "level": level,
                         "reason": "dispatch_failure"},
                finding=finding,
            )
            return OPTIMIZER_OUTCOME_FAILED

    async def _consider_apply(self, finding: OptimizationFinding) -> None:
        """If a finding carries a proposed_action, run it through the gate."""
        # Phase 1 dimensions emit advisory-only findings (no proposed
        # action). The path is wired so Phase 2 LLM-proposed actions
        # automatically flow through the same chokepoint.
        if not finding.proposed_action:
            # Still mark applied_outcome=advisory_only for sentinel/meta
            # rows so the DB column isn't NULL on a known-clean cycle.
            if finding.dimension == OptimizationDimension.META:
                finding.applied_outcome = OPTIMIZER_OUTCOME_ADVISORY_ONLY
            else:
                # Compute effective level for visibility; advisory_only
                # respects shadow at L1 default.
                level = self.effective_level
                if level == OPTIMIZER_LEVEL_SHADOW:
                    finding.applied_outcome = OPTIMIZER_OUTCOME_SHADOW
                    finding.predicted_effect = {
                        "note": "shadow_dry_run — no proposed action emitted",
                    }
                    await self._log_activity(
                        action="shadow_dry_run", importance="info",
                        description=finding.description,
                        details={"level": level,
                                 "dimension": str(finding.dimension),
                                 "predicted_effect": finding.predicted_effect},
                        finding=finding,
                    )
                else:
                    finding.applied_outcome = OPTIMIZER_OUTCOME_ADVISORY_ONLY
            return
        await self._apply_action(finding, finding.proposed_action)

    # ------------------------------------------------------------------
    # Persistence + signals + NM
    # ------------------------------------------------------------------

    async def _persist_finding(self, finding: OptimizationFinding) -> None:
        database = self.hass.data.get(DOMAIN, {}).get("database")
        if database is None:
            return
        try:
            await database.log_finding(finding)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug("log_finding failed: %s", exc, exc_info=True)

    def _dispatch_finding_signal(self, finding: OptimizationFinding) -> None:
        try:
            async_dispatcher_send(
                self.hass,
                SIGNAL_OPTIMIZER_FINDING_EMITTED,
                {
                    "level": finding.level,
                    "target_id": finding.target_id,
                    "dimension": str(finding.dimension),
                    "severity": finding.severity,
                    "description": finding.description,
                    "timestamp": finding.timestamp,
                },
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug("finding signal dispatch failed", exc_info=True)

    async def _notify_if_severe(self, finding: OptimizationFinding) -> None:
        if finding.severity not in ("critical", "high"):
            return
        nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
        if nm is None:
            return
        sev_map = {"critical": Severity.CRITICAL, "high": Severity.HIGH}
        try:
            await nm.async_notify(
                coordinator_id="optimization",
                severity=sev_map[finding.severity],
                title=f"URA Optimizer — {finding.dimension}",
                message=finding.description,
                hazard_type=None,
                location=finding.target_id or "house",
            )
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug("NM notify failed: %s", exc, exc_info=True)

    async def _log_activity(
        self,
        action: str,
        importance: str,
        description: str,
        details: dict,
        finding: OptimizationFinding | None = None,
    ) -> None:
        logger = self.hass.data.get(DOMAIN, {}).get("activity_logger")
        if logger is None:
            return
        room = None
        zone = None
        if finding is not None and finding.level == "room":
            room = finding.target_id
        if finding is not None and finding.level == "zone":
            zone = finding.target_id
        try:
            await logger.log(
                coordinator="optimization",
                action=action,
                description=description,
                room=room,
                zone=zone,
                importance=importance,
                details=details,
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug("activity_logger.log failed", exc_info=True)

    # ------------------------------------------------------------------
    # Scoreboard / sensor exposure
    # ------------------------------------------------------------------

    def _update_scoreboard(self, findings: list[OptimizationFinding]) -> None:
        room_findings: dict[str, list[OptimizationFinding]] = {}
        open_count = 0
        for f in findings:
            if f.dimension == OptimizationDimension.META:
                continue
            open_count += 1
            if f.level == "room" and f.target_id:
                room_findings.setdefault(f.target_id, []).append(f)
        # 100 if no findings, else 100 - (15 per finding) bounded at 0.
        self._room_scores = {}
        for room, room_fs in room_findings.items():
            self._room_scores[room] = max(0.0, 100.0 - 15.0 * len(room_fs))
        if room_findings:
            self._house_score = min(self._room_scores.values())
        else:
            self._house_score = 100.0
        self._open_findings_count = open_count

    @property
    def status(self) -> str:
        if self._house_score >= 90:
            return "healthy"
        if self._house_score >= 60:
            return "degraded"
        return "critical"

    def get_room_score(self, room: str) -> float:
        return self._room_scores.get(room, 100.0)

    def get_open_findings_summary(self) -> dict:
        by_sev = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        by_lvl = {"room": 0, "zone": 0, "house": 0}
        for f in self._last_findings:
            if f.dimension == OptimizationDimension.META:
                continue
            if f.severity in by_sev:
                by_sev[f.severity] += 1
            if f.level in by_lvl:
                by_lvl[f.level] += 1
        return {"by_severity": by_sev, "by_level": by_lvl}
