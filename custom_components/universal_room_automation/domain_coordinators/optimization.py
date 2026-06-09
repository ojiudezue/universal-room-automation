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
    # v4.7.35 fix-up (B-B2) — safety/security deny-list CM-options key.
    CONF_OPTIMIZER_SAFETY_DENY_ENTITIES,
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
    # v4.7.36 Phase 3 — additional dimensions.
    OPTIMIZER_DIMENSION_OCCUPANCY_ACCURACY,
    OPTIMIZER_DIMENSION_AUTOMATION_RESPONSIVENESS,
    OPTIMIZER_DIMENSION_CONFIG_BEHAVIOR,
    OPTIMIZER_DIMENSION_ENERGY_EFFICIENCY,
    OPTIMIZER_DIMENSION_SETPOINT_COMPLIANCE,
    OPTIMIZER_DIMENSION_VACANCY_MANAGEMENT,
    OPTIMIZER_DIMENSION_OVERRIDE_FREQUENCY,
    OPTIMIZER_DIMENSION_STATE_MACHINE_ACCURACY,
    OPTIMIZER_DIMENSION_SECURITY_POSTURE,
    OPTIMIZER_DIGEST_RETENTION_DAYS,
    OPTIMIZER_DIGEST_TOP_N,
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
    """Optimization dimensions emitted by the Phase-1/Phase-3 rule engine."""

    SENSOR_HEALTH = OPTIMIZER_DIMENSION_SENSOR_HEALTH
    COMFORT = OPTIMIZER_DIMENSION_COMFORT
    META = OPTIMIZER_DIMENSION_META
    # v4.7.36 Phase 3 — room-level
    OCCUPANCY_ACCURACY = OPTIMIZER_DIMENSION_OCCUPANCY_ACCURACY
    AUTOMATION_RESPONSIVENESS = OPTIMIZER_DIMENSION_AUTOMATION_RESPONSIVENESS
    CONFIG_BEHAVIOR = OPTIMIZER_DIMENSION_CONFIG_BEHAVIOR
    ENERGY_EFFICIENCY = OPTIMIZER_DIMENSION_ENERGY_EFFICIENCY
    # v4.7.36 Phase 3 — zone-level
    SETPOINT_COMPLIANCE = OPTIMIZER_DIMENSION_SETPOINT_COMPLIANCE
    VACANCY_MANAGEMENT = OPTIMIZER_DIMENSION_VACANCY_MANAGEMENT
    OVERRIDE_FREQUENCY = OPTIMIZER_DIMENSION_OVERRIDE_FREQUENCY
    # v4.7.36 Phase 3 — house-level
    STATE_MACHINE_ACCURACY = OPTIMIZER_DIMENSION_STATE_MACHINE_ACCURACY
    SECURITY_POSTURE = OPTIMIZER_DIMENSION_SECURITY_POSTURE

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

    # A-HIGH-2/A-HIGH-3: pending veto eviction policy. Each entry is
    # ``action_id → (deadline_utc, vetoed_by)``. Stale entries are evicted
    # whenever a new veto arrives or a veto is awaited.
    _VETO_TTL_SECONDS = 300  # 5 min
    _VETO_MAX_PENDING = 256

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the broker."""
        self.hass = hass
        # A-HIGH-2: store (received_at, vetoed_by) per action_id so we can
        # age out entries that never got reaped (no _apply_action ran).
        self._pending_vetoes: dict[str, tuple[datetime, str]] = {}
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

    def _evict_stale_vetoes(self) -> None:
        """A-HIGH-2: drop pending vetoes older than the TTL so a never-reaped
        veto doesn't sit in the dict forever (memory leak)."""
        now = dt_util.utcnow()
        cutoff = now - timedelta(seconds=self._VETO_TTL_SECONDS)
        stale = [
            aid for aid, (ts, _by) in self._pending_vetoes.items()
            if ts < cutoff
        ]
        for aid in stale:
            self._pending_vetoes.pop(aid, None)
        # Hard cap as a belt-and-suspenders bound.
        if len(self._pending_vetoes) > self._VETO_MAX_PENDING:
            # Drop oldest until under cap.
            items = sorted(
                self._pending_vetoes.items(), key=lambda kv: kv[1][0]
            )
            overflow = len(items) - self._VETO_MAX_PENDING
            for aid, _ in items[:overflow]:
                self._pending_vetoes.pop(aid, None)

    def _on_veto(self, payload: dict) -> None:
        action_id = payload.get("action_id") if isinstance(payload, dict) else None
        if not action_id:
            return
        vetoed_by = (
            payload.get("vetoed_by", "unknown")
            if isinstance(payload, dict)
            else "unknown"
        )
        self._pending_vetoes[action_id] = (dt_util.utcnow(), vetoed_by)
        # Opportunistically evict stale entries on each new veto arrival.
        self._evict_stale_vetoes()

    def discard_pending(self, action_id: str) -> None:
        """A-HIGH-3: explicitly forget a queued veto once an action ran.

        Callers invoke this on the successful-actuation path so a late
        veto for the *same* action_id can't influence a *future* action.
        """
        self._pending_vetoes.pop(action_id, None)

    def _get_hvac_coordinator(self):
        """Resolve the HVAC coordinator via the coordinator manager.

        A-CRIT-1 fix-up: ``hass.data[DOMAIN]["hvac_coordinator"]`` is NOT a
        slot the integration ever populates (only the OptimizerKillSwitch's
        legacy code path probed it). HVAC is registered via
        ``CoordinatorManager.register_coordinator(hvac)`` and lives in
        ``manager.coordinators["hvac"]``. The CM itself is stored at
        ``hass.data[DOMAIN]["coordinator_manager"]`` (``__init__.py:2159``).
        Also tolerate the legacy slot for backward compat with tests that
        seed it directly.
        """
        try:
            domain_data = self.hass.data.get(DOMAIN, {}) or {}
            # Test-facing back-compat: honour an explicit hvac_coordinator
            # slot if one is mounted (existing tests inject this).
            hvac = domain_data.get("hvac_coordinator")
            if hvac is not None:
                return hvac
            cm = domain_data.get("coordinator_manager")
            if cm is None:
                return None
            coords = getattr(cm, "coordinators", None) or {}
            return coords.get("hvac")
        except Exception:  # noqa: BLE001 — never crash dispatch
            return None

    def _get_arrester(self):
        """Return the HVAC OverrideArrester if present, else None."""
        try:
            hvac = self._get_hvac_coordinator()
            if hvac is None:
                return None
            return getattr(hvac, "override_arrester", None)
        except Exception:  # noqa: BLE001 — never crash dispatch
            return None

    def suppress_climate(self, target_entity: str) -> bool:
        """Open the TTL handshake window for a climate target; safe no-op
        for non-climate entities or when no arrester is present.

        Renamed from ``_maybe_suppress`` per C-MED — broker is a public
        collaborator; the coordinator and tests call this directly. The
        old private name is kept as an alias for back-compat (test seam).
        """
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

    def unsuppress_climate(self, target_entity: str) -> None:
        """Close the TTL window — used on error paths so a failed write
        doesn't sit suppressed for the rest of the TTL.

        Renamed from ``_maybe_unsuppress`` per C-MED.
        """
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

    # Back-compat aliases — tests may have patched these names.
    _maybe_suppress = suppress_climate
    _maybe_unsuppress = unsuppress_climate

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
    ) -> bool:
        """Dispatch SIGNAL_OPTIMIZER_INTENT with the full payload.

        A-HIGH-1: returns True on a clean dispatch, False if the dispatch
        raised. Callers MUST treat False as "intent broker is broken — do
        not actuate" — siblings never saw the intent and can't veto, so a
        silent fallback to ``services.async_call`` would skip the handshake.
        """
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
            return True
        except Exception:  # noqa: BLE001
            _LOGGER.warning(
                "SIGNAL_OPTIMIZER_INTENT dispatch failed — siblings did not "
                "see this intent, skipping actuation",
                exc_info=True,
            )
            return False

    async def await_veto(
        self, action_id: str, veto_window_s: int,
    ) -> str | None:
        """Wait up to ``veto_window_s`` seconds for a matching veto.

        Returns the ``vetoed_by`` string if vetoed, else None.
        """
        # Opportunistic eviction so a long-running optimizer doesn't grow
        # the pending dict unboundedly.
        self._evict_stale_vetoes()

        def _take(aid: str) -> str | None:
            tup = self._pending_vetoes.pop(aid, None)
            if tup is None:
                return None
            # Tuple shape: (received_at, vetoed_by). Accept legacy raw
            # str entries defensively (existing tests inject the dict
            # directly with a plain string value).
            if isinstance(tup, tuple) and len(tup) == 2:
                return str(tup[1])
            return str(tup)

        if veto_window_s <= 0:
            return _take(action_id)
        # Poll at small intervals so siblings can veto inside the window.
        deadline = dt_util.utcnow() + timedelta(seconds=veto_window_s)
        while dt_util.utcnow() < deadline:
            if action_id in self._pending_vetoes:
                return _take(action_id)
            await asyncio.sleep(0.1)
        return _take(action_id)


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
        # Phase 3 — per-zone scoreboard (populated post-cycle).
        self._zone_scores: dict[str, float] = {}

        # Cycle handle.
        self._cycle_unsub = None

        # Phase 2 — LLM Tier-2 wrapper. Lazily constructed so importing
        # the optimizer module doesn't trigger the LLM import chain when
        # only Phase-1 is being used.
        self._llm_tier = None

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

        # H2 fix-up: seed rate-cap history from the DB so a restart can't
        # bypass the per-hour cap. Count rows applied within the last
        # rolling hour and pre-fill the deque with proxy timestamps so the
        # post-restart cycle sees the same "you already spent X actions
        # this hour" as the pre-restart cycle would have. Best-effort —
        # falls back to a cold deque if the DB isn't ready.
        try:
            db = self.hass.data.get(DOMAIN, {}).get("database")
            if db is not None and hasattr(db, "get_recent_optimization_findings"):
                rows = await db.get_recent_optimization_findings(limit=200)
                cutoff = dt_util.utcnow() - timedelta(hours=1)
                seeded = 0
                for r in rows or []:
                    outcome = r.get("applied_outcome") if isinstance(r, dict) else None
                    if outcome != "applied":
                        continue
                    ts_raw = r.get("timestamp") if isinstance(r, dict) else None
                    if not ts_raw:
                        continue
                    try:
                        # Stored ISO timestamps may or may not carry tz; be
                        # forgiving — fall back to "now" so the cap is
                        # over-conservative rather than under-counted.
                        ts = datetime.fromisoformat(str(ts_raw))
                    except (TypeError, ValueError):
                        ts = dt_util.utcnow()
                    # Strip tz if our utcnow is naive so the deque eviction
                    # comparison doesn't blow up (mixed naive/aware).
                    if cutoff.tzinfo is None and ts.tzinfo is not None:
                        ts = ts.replace(tzinfo=None)
                    elif cutoff.tzinfo is not None and ts.tzinfo is None:
                        ts = ts.replace(tzinfo=cutoff.tzinfo)
                    if ts >= cutoff:
                        self._action_dispatch_history.append(ts)
                        seeded += 1
                if seeded:
                    _LOGGER.info(
                        "Optimizer: seeded rate-cap window with %d "
                        "applied-action rows from the last hour",
                        seeded,
                    )
                else:
                    _LOGGER.info(
                        "Optimizer: rate-cap deque cold-started "
                        "(no applied rows in last hour)",
                    )
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "Optimizer: rate-cap seed from DB failed (non-fatal)",
                exc_info=True,
            )

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
        # Phase 1 dimensions.
        findings.extend(self._evaluate_sensor_health_dimension())
        findings.extend(self._evaluate_comfort_dimension())
        # Phase 3 — room-level.
        findings.extend(self._evaluate_occupancy_accuracy_dimension())
        findings.extend(self._evaluate_automation_responsiveness_dimension())
        findings.extend(self._evaluate_config_behavior_dimension())
        findings.extend(self._evaluate_energy_efficiency_dimension())
        # Phase 3 — zone-level.
        findings.extend(self._evaluate_setpoint_compliance_dimension())
        findings.extend(self._evaluate_vacancy_management_dimension())
        findings.extend(self._evaluate_override_frequency_dimension())
        # Phase 3 — house-level.
        findings.extend(self._evaluate_state_machine_accuracy_dimension())
        findings.extend(self._evaluate_security_posture_dimension())

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

        # Phase 2 — LLM Tier-2 pass. Runs AFTER Tier-1 so the LLM sees
        # the just-emitted Tier-1 findings in its corpus. The tier
        # internally enforces: configured-entity guard, delta gate,
        # daily premium cap, optional cheap-triage routing. Every LLM
        # finding flows through the SAME ``_consider_apply`` chokepoint
        # (no bypass path).
        llm_findings = await self._maybe_run_llm_tier(findings)
        for finding in llm_findings:
            await self._persist_finding(finding)
            # `_consider_apply` already ran inside the LLM tier; only
            # persist + dispatch the signal + notify here.
            self._dispatch_finding_signal(finding)
            await self._notify_if_severe(finding)

        all_findings = list(findings) + list(llm_findings)
        self._last_findings = all_findings
        self._last_evaluation_iso = dt_util.utcnow().isoformat()
        return all_findings

    async def _maybe_run_llm_tier(
        self, tier1_findings: list[OptimizationFinding],
    ) -> list[OptimizationFinding]:
        """Run the Phase-2 LLM tier when configured.

        Returns the list of LLM-emitted findings (already routed through
        the chokepoint). Empty list when no LLM task entity is
        configured / delta gate skips / daily cap reached / response
        malformed.
        """
        try:
            if self._llm_tier is None:
                from .optimization_llm import OptimizationLLMTier
                self._llm_tier = OptimizationLLMTier(self.hass, self)
            return await self._llm_tier.run_cycle(tier1_findings) or []
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning(
                "OptimizationLLMTier cycle failed: %s", exc, exc_info=True,
            )
            return []

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

    # ------------------------------------------------------------------
    # HVAC sibling lookups (A-CRIT-1 / A-CRIT-2)
    # ------------------------------------------------------------------

    def _get_hvac_coordinator(self):
        """Resolve the HVAC coordinator via the coordinator manager.

        A-CRIT-1 fix-up: ``hass.data[DOMAIN]["hvac_coordinator"]`` is NOT a
        slot the integration populates. The CoordinatorManager is at
        ``hass.data[DOMAIN]["coordinator_manager"]`` (__init__.py:2159)
        and HVAC lives in ``manager.coordinators["hvac"]``. The legacy
        slot is consulted first for test-injection back-compat.
        """
        try:
            domain_data = self.hass.data.get(DOMAIN, {}) or {}
            hvac = domain_data.get("hvac_coordinator")
            if hvac is not None:
                return hvac
            cm = domain_data.get("coordinator_manager")
            if cm is None:
                return None
            coords = getattr(cm, "coordinators", None) or {}
            return coords.get("hvac")
        except Exception:  # noqa: BLE001
            return None

    def _get_egress_manager(self):
        """Return the HVAC EgressManager if present, else None (A-CRIT-2)."""
        try:
            hvac = self._get_hvac_coordinator()
            if hvac is None:
                return None
            return getattr(hvac, "egress_manager", None)
        except Exception:  # noqa: BLE001
            return None

    def _zone_id_for_climate_entity(self, climate_entity: str) -> str | None:
        """Best-effort: walk HVAC ZoneManager to find the zone owning this
        climate entity, so A-CRIT-2 can ask the EgressManager if it's paused."""
        if not climate_entity:
            return None
        try:
            hvac = self._get_hvac_coordinator()
            if hvac is None:
                return None
            zm = getattr(hvac, "zone_manager", None)
            if zm is None:
                return None
            for zone_id, zone in (getattr(zm, "zones", {}) or {}).items():
                if getattr(zone, "climate_entity", None) == climate_entity:
                    return zone_id
        except Exception:  # noqa: BLE001
            return None
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
    # Phase 3 — additional dimension evaluators.
    #
    # Discipline: each evaluator reads substrate that DEMONSTRABLY exists
    # in the running coordinator graph. Substrate-not-available dimensions
    # return [] with a TODO marker (no fabrication — see CLAUDE.md
    # "No Fabrication — CRITICAL" rule).
    # ------------------------------------------------------------------

    def _iter_hvac_zones(self):
        """Yield (zone_id, ZoneState) for HVAC zones, guarded for tests.

        Substrate: HVAC coordinator's ZoneManager — domain_coordinators/
        hvac_zones.py:179 (class ZoneManager) + hvac.py:677 ZoneManager
        attached as ``hvac.zone_manager``.
        """
        try:
            hvac = self._get_hvac_coordinator()
            if hvac is None:
                return
            zm = getattr(hvac, "zone_manager", None)
            if zm is None:
                return
            for zone_id, zone in (getattr(zm, "zones", {}) or {}).items():
                yield zone_id, zone
        except Exception:  # noqa: BLE001
            return

    def _get_house_state_machine(self):
        """Return the HouseStateMachine via the coordinator manager.

        Substrate: CoordinatorManager.house_state_machine — manager.py:197.
        """
        try:
            domain_data = self.hass.data.get(DOMAIN, {}) or {}
            cm = domain_data.get("coordinator_manager")
            if cm is None:
                return None
            return getattr(cm, "house_state_machine", None)
        except Exception:  # noqa: BLE001
            return None

    def _get_security_coordinator(self):
        """Return the SecurityCoordinator via the coordinator manager.

        Substrate: CoordinatorManager.coordinators["security"] —
        SecurityCoordinator at security.py:456.
        """
        try:
            domain_data = self.hass.data.get(DOMAIN, {}) or {}
            cm = domain_data.get("coordinator_manager")
            if cm is None:
                return None
            coords = getattr(cm, "coordinators", None) or {}
            return coords.get("security")
        except Exception:  # noqa: BLE001
            return None

    def _evaluate_occupancy_accuracy_dimension(
        self,
    ) -> list[OptimizationFinding]:
        """Per room: configured occupancy sensors split — none reporting `on`
        for >30min when a recent motion/mmwave signal IS firing → low confidence
        sensor staleness signal.

        Substrate: per-room CONF_OCCUPANCY_SENSORS + CONF_MOTION_SENSORS +
        CONF_MMWAVE_SENSORS — read fresh from entry.options/data via the
        existing ``_iter_room_entries`` helper (optimization.py:669).
        Read each sensor's state via ``hass.states.get`` (the same path the
        Phase-1 sensor-health rule uses).

        Heuristic: when a motion OR mmwave sensor is ON but NO occupancy
        sensor reports ON, flag low-severity occupancy_accuracy degradation.
        Advisory only — never proposes an action. Calibrated low confidence
        (0.55) because mixed sensor models can legitimately disagree for
        short windows.
        """
        findings: list[OptimizationFinding] = []
        now = dt_util.utcnow()
        for entry in self._iter_room_entries():
            merged = {**(entry.data or {}), **(entry.options or {})}
            room = self._room_name(entry)
            occ_ids: list[str] = []
            sig_ids: list[str] = []
            val_occ = merged.get(CONF_OCCUPANCY_SENSORS)
            if isinstance(val_occ, list):
                occ_ids.extend([v for v in val_occ if isinstance(v, str)])
            elif isinstance(val_occ, str) and val_occ:
                occ_ids.append(val_occ)
            for key in (CONF_MOTION_SENSORS, CONF_MMWAVE_SENSORS):
                val = merged.get(key)
                if isinstance(val, list):
                    sig_ids.extend([v for v in val if isinstance(v, str)])
                elif isinstance(val, str) and val:
                    sig_ids.append(val)
            if not occ_ids or not sig_ids:
                continue
            motion_on = False
            for eid in sig_ids:
                st = self._state_value(eid)
                if st is None:
                    continue
                if str(st.state).lower() in ("on", "true", "occupied"):
                    motion_on = True
                    break
            if not motion_on:
                continue
            occ_on = False
            for eid in occ_ids:
                st = self._state_value(eid)
                if st is None:
                    continue
                if str(st.state).lower() in ("on", "true", "occupied"):
                    occ_on = True
                    break
            if occ_on:
                continue
            dedup_key = ("occupancy_accuracy", room)
            if dedup_key in self._cycle_dedup:
                continue
            self._cycle_dedup.add(dedup_key)
            findings.append(OptimizationFinding(
                timestamp=now.isoformat(),
                level="room",
                target_id=room,
                dimension=OptimizationDimension.OCCUPANCY_ACCURACY,
                severity="low",
                confidence=0.55,
                score=0.0,
                description=(
                    f"{room}: motion/mmwave active but occupancy sensors "
                    f"report clear (provenance disagreement)"
                ),
                proposed_action=None,
                payload={"occupancy_ids": occ_ids, "signal_ids": sig_ids},
                dedup_key=dedup_key,
            ))
        return findings

    def _evaluate_automation_responsiveness_dimension(
        self,
    ) -> list[OptimizationFinding]:
        """Substrate not cleanly available — DEFERRED.

        # TODO Phase 3.x: needs per-room "command-fired → state-change
        # observed" latency telemetry. Today only HVAC's ComplianceTracker
        # (coordinator_diagnostics.py:333) captures a similar signal at
        # the device level (commanded vs actual setpoint), and it is
        # device-typed (climate/light/cover) not per-room. A clean room-
        # tier responsiveness reader would need either a new
        # ResponsivenessRing in BaseCoordinator or a join over
        # decision_log + activity_log timestamps.
        """
        return []

    def _evaluate_config_behavior_dimension(
        self,
    ) -> list[OptimizationFinding]:
        """Per room: comfort upper bound below or equal to the comfort lower
        bound → operator-config bug; emit medium-severity advisory.

        Substrate: per-room comfort options via ``_read_per_room_comfort``
        (optimization.py:682) which already merges entry.options →
        entry.data → module constant fallback. Pure config-validation rule
        — no live state read needed.
        """
        findings: list[OptimizationFinding] = []
        now = dt_util.utcnow()
        for entry in self._iter_room_entries():
            room = self._room_name(entry)
            comfort = self._read_per_room_comfort(entry)
            issues = []
            if comfort["max"] <= comfort["min"]:
                issues.append(
                    f"comfort_temp_max ({comfort['max']}) <= "
                    f"comfort_temp_min ({comfort['min']})"
                )
            if comfort["hum_max"] <= 0 or comfort["hum_max"] > 100:
                issues.append(
                    f"comfort_humidity_max ({comfort['hum_max']}) outside "
                    f"sane bounds (0,100]"
                )
            if not issues:
                continue
            dedup_key = ("config_behavior", room)
            if dedup_key in self._cycle_dedup:
                continue
            self._cycle_dedup.add(dedup_key)
            findings.append(OptimizationFinding(
                timestamp=now.isoformat(),
                level="room",
                target_id=room,
                dimension=OptimizationDimension.CONFIG_BEHAVIOR,
                severity="medium",
                confidence=0.95,
                score=0.0,
                description=(
                    f"{room}: comfort config issues: {'; '.join(issues)}"
                ),
                proposed_action=None,
                payload={"issues": issues, "comfort": comfort},
                dedup_key=dedup_key,
            ))
        return findings

    def _evaluate_energy_efficiency_dimension(
        self,
    ) -> list[OptimizationFinding]:
        """Substrate not cleanly available at room tier — DEFERRED.

        # TODO Phase 3.x: needs per-room energy attribution (kWh by
        # room/zone over a window). Today the energy substrate aggregates
        # at the house tier (energy_pool.py) and per-circuit (energy_circuits.py)
        # — neither maps cleanly to URA rooms. A clean reader would need
        # the planned zone-circuit binding (see Optimization Coordinator
        # v2 plan Phase 4) before this dimension can fire honestly.
        """
        return []

    def _evaluate_setpoint_compliance_dimension(
        self,
    ) -> list[OptimizationFinding]:
        """Per zone: read HVAC ComplianceTracker's compliance summary; high
        deviation rate → medium-severity advisory.

        Substrate: HVAC's compliance_tracker (ComplianceTracker class at
        coordinator_diagnostics.py:333; attached to hvac coordinator via
        hvac.py:677 ``self._compliance = ComplianceTracker(...)``). The
        in-memory tracker emits anomaly events on violations; a clean
        per-zone aggregate is NOT available in-process today, so we
        approximate via SecurityCoordinator's compliance summary shape
        — DEFERRED to a real reader.

        # TODO Phase 3.x: needs ComplianceTracker.get_zone_compliance_rate
        # — today only schedule_check + _check_compliance + anomaly emit
        # exist (coordinator_diagnostics.py:352, 373, 414). A read-side
        # zone roll-up over ``compliance_log`` is needed.
        """
        return []

    def _evaluate_vacancy_management_dimension(
        self,
    ) -> list[OptimizationFinding]:
        """Per zone: a zone whose state machine has not retired to vacant
        despite ``continuous_occupied_since`` > 12h with vacancy_sweep_done
        False → low-severity advisory (likely stuck-sensor).

        Substrate: ZoneState fields (hvac_zones.py:104-106):
          - ``continuous_occupied_since`` (datetime|None)
          - ``vacancy_sweep_done`` (bool)
          - ``vacancy_sweep_enabled`` (bool)
        Iterated via ``_iter_hvac_zones`` (this file) which walks
        ZoneManager.zones (hvac_zones.py:189).
        """
        findings: list[OptimizationFinding] = []
        now = dt_util.utcnow()
        for zone_id, zone in self._iter_hvac_zones():
            try:
                cont_since = getattr(zone, "continuous_occupied_since", None)
                sweep_done = bool(
                    getattr(zone, "vacancy_sweep_done", False)
                )
                sweep_enabled = bool(
                    getattr(zone, "vacancy_sweep_enabled", True)
                )
                zone_name = getattr(zone, "zone_name", zone_id)
            except Exception:  # noqa: BLE001
                continue
            if not sweep_enabled or cont_since is None or sweep_done:
                continue
            try:
                # Normalize TZ for comparison (both should be UTC).
                cs = cont_since
                if cs.tzinfo is None and now.tzinfo is not None:
                    cs = cs.replace(tzinfo=now.tzinfo)
                elif cs.tzinfo is not None and now.tzinfo is None:
                    cs = cs.replace(tzinfo=None)
                hours = (now - cs).total_seconds() / 3600.0
            except Exception:  # noqa: BLE001
                continue
            if hours < 12:
                continue
            dedup_key = ("vacancy_management", zone_id)
            if dedup_key in self._cycle_dedup:
                continue
            self._cycle_dedup.add(dedup_key)
            findings.append(OptimizationFinding(
                timestamp=now.isoformat(),
                level="zone",
                target_id=zone_id,
                dimension=OptimizationDimension.VACANCY_MANAGEMENT,
                severity="low",
                confidence=0.7,
                score=0.0,
                description=(
                    f"Zone {zone_name}: continuous occupancy for "
                    f"{hours:.1f}h with vacancy sweep not fired — "
                    f"possible stuck occupancy signal"
                ),
                proposed_action=None,
                payload={
                    "zone_id": zone_id,
                    "hours_continuous": round(hours, 1),
                },
                dedup_key=dedup_key,
            ))
        return findings

    def _evaluate_override_frequency_dimension(
        self,
    ) -> list[OptimizationFinding]:
        """Per zone: zone.override_count_today ≥ 10 → medium-severity advisory
        (sustained manual fighting suggests setpoint baseline misaligned).

        Substrate: ZoneState.override_count_today (hvac_zones.py:82) — int
        counter incremented by OverrideArrester paths and reset at midnight
        via ``reset_daily_counters`` (hvac_zones.py:708).
        """
        findings: list[OptimizationFinding] = []
        now = dt_util.utcnow()
        for zone_id, zone in self._iter_hvac_zones():
            try:
                count = int(getattr(zone, "override_count_today", 0) or 0)
                zone_name = getattr(zone, "zone_name", zone_id)
            except Exception:  # noqa: BLE001
                continue
            if count < 10:
                continue
            dedup_key = ("override_frequency", zone_id)
            if dedup_key in self._cycle_dedup:
                continue
            self._cycle_dedup.add(dedup_key)
            severity = "high" if count >= 20 else "medium"
            findings.append(OptimizationFinding(
                timestamp=now.isoformat(),
                level="zone",
                target_id=zone_id,
                dimension=OptimizationDimension.OVERRIDE_FREQUENCY,
                severity=severity,
                confidence=0.85,
                score=0.0,
                description=(
                    f"Zone {zone_name}: {count} overrides today — sustained "
                    f"manual fighting; baseline may be misaligned"
                ),
                proposed_action=None,
                payload={
                    "zone_id": zone_id,
                    "override_count_today": count,
                },
                dedup_key=dedup_key,
            ))
        return findings

    def _evaluate_state_machine_accuracy_dimension(
        self,
    ) -> list[OptimizationFinding]:
        """House: state-machine override held >2h → medium advisory (manual
        override outlives operator's typical attention window).

        Substrate: HouseStateMachine — manager.py:197 (cm.house_state_machine).
        Reads ``is_overridden`` + ``_override_since`` (house_state.py:139).
        """
        findings: list[OptimizationFinding] = []
        now = dt_util.utcnow()
        hsm = self._get_house_state_machine()
        if hsm is None:
            return findings
        try:
            overridden = bool(getattr(hsm, "is_overridden", False))
        except Exception:  # noqa: BLE001
            return findings
        if not overridden:
            return findings
        override_since_ts = getattr(hsm, "_override_since", None)
        if override_since_ts is None:
            return findings
        try:
            hours = (now.timestamp() - float(override_since_ts)) / 3600.0
        except (TypeError, ValueError):
            return findings
        if hours < 2:
            return findings
        dedup_key = ("state_machine_accuracy", "house")
        if dedup_key in self._cycle_dedup:
            return findings
        self._cycle_dedup.add(dedup_key)
        findings.append(OptimizationFinding(
            timestamp=now.isoformat(),
            level="house",
            target_id="house",
            dimension=OptimizationDimension.STATE_MACHINE_ACCURACY,
            severity="medium",
            confidence=0.8,
            score=0.0,
            description=(
                f"House state override held {hours:.1f}h — consider clearing"
            ),
            proposed_action=None,
            payload={"hours_overridden": round(hours, 1)},
            dedup_key=dedup_key,
        ))
        return findings

    def _evaluate_security_posture_dimension(
        self,
    ) -> list[OptimizationFinding]:
        """House: security aggregator reports locks_unlocked > 0 during
        AWAY/NIGHT/SLEEP states → high-severity advisory.

        Substrate: SecurityCoordinator.get_security_aggregator_state
        (security.py:1725) returns counts incl. locks_locked/locks_unlocked;
        HouseStateMachine.state for the gating context (manager.py:202).
        """
        findings: list[OptimizationFinding] = []
        now = dt_util.utcnow()
        sec = self._get_security_coordinator()
        if sec is None:
            return findings
        try:
            agg = sec.get_security_aggregator_state() or {}
        except Exception:  # noqa: BLE001
            return findings
        unlocked = int(agg.get("locks_unlocked", 0) or 0)
        if unlocked <= 0:
            return findings
        # Read house state context (best-effort).
        hsm = self._get_house_state_machine()
        house_state = ""
        try:
            if hsm is not None:
                house_state = str(getattr(hsm, "state", "") or "")
        except Exception:  # noqa: BLE001
            house_state = ""
        # Only flag when house is in a gated context. Lowercase compare so
        # both StrEnum value ("away") and plain string match.
        gated = house_state.lower() in ("away", "night", "sleep")
        if not gated:
            return findings
        dedup_key = ("security_posture", "house")
        if dedup_key in self._cycle_dedup:
            return findings
        self._cycle_dedup.add(dedup_key)
        findings.append(OptimizationFinding(
            timestamp=now.isoformat(),
            level="house",
            target_id="house",
            dimension=OptimizationDimension.SECURITY_POSTURE,
            severity="high",
            confidence=0.9,
            score=0.0,
            description=(
                f"{unlocked} lock(s) unlocked while house state is "
                f"{house_state} — review security posture"
            ),
            proposed_action=None,
            payload={
                "locks_unlocked": unlocked,
                "house_state": house_state,
            },
            dedup_key=dedup_key,
        ))
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
        """Read NM's `is quiet now?` predicate. REUSES NM's single source of truth.

        M1 fix-up: prefer the public ``is_quiet_hours_active()`` shim
        when it's been explicitly defined on the NM CLASS (so MagicMock
        auto-attribute synthesis can't mask a test's `_is_quiet_hours`
        configuration). Fall back to the legacy private method otherwise.
        """
        try:
            nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
            if nm is None:
                return False
            # Only use the public shim when the class genuinely defines
            # it. ``vars(type(nm))`` and walking ``__mro__`` ignores
            # MagicMock's __getattr__ shim.
            for klass in type(nm).__mro__:
                if "is_quiet_hours_active" in vars(klass):
                    return bool(nm.is_quiet_hours_active())
            return bool(nm._is_quiet_hours())
        except Exception:  # noqa: BLE001
            return False

    def _rate_cap_window_count(self) -> int:
        """Count dispatches in the rolling 1h window (also evicts stale)."""
        cutoff = dt_util.utcnow() - timedelta(hours=1)
        while self._action_dispatch_history and self._action_dispatch_history[0] < cutoff:
            self._action_dispatch_history.popleft()
        return len(self._action_dispatch_history)

    def _resolve_effective_level(self) -> tuple[str, str | None]:
        """Return (effective_level, clamp_reason) — H3/M3 fix-up.

        ``clamp_reason`` is one of:
          - ``"kill_switch"``: kill switch engaged
          - ``"rate_capped"``: per-hour cap exceeded
          - ``"quiet_hours"``: quiet-hours active and source=reuse_nm
          - ``None``: configured level applies unchanged

        The chokepoint inspects ``clamp_reason`` to emit the right
        outcome (RATE_CAPPED / QUIET_CLAMPED / KILL_SWITCH) on shadowed
        actions, instead of the generic ``OPTIMIZER_OUTCOME_SHADOW``.
        """
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
            return OPTIMIZER_LEVEL_ADVISORY, "kill_switch"

        clamp_reason: str | None = None

        # Quiet hours — clamp to min(configured, L1).
        qh_source = config.get(
            CONF_OPTIMIZER_QUIET_HOURS_SOURCE,
            DEFAULT_OPTIMIZER_QUIET_HOURS_SOURCE,
        )
        if (qh_source == OPTIMIZER_QUIET_HOURS_SOURCE_REUSE_NM
                and self._is_quiet_hours_active()):
            new_level = self._min_level(configured, OPTIMIZER_LEVEL_SHADOW)
            if new_level != configured:
                clamp_reason = "quiet_hours"
            configured = new_level

        # Rate cap — when cap hit, clamp L2+ to L1.
        cap = int(config.get(
            CONF_OPTIMIZER_RATE_CAP_PER_HOUR,
            DEFAULT_OPTIMIZER_RATE_CAP_PER_HOUR,
        ))
        if self._rate_cap_window_count() >= cap:
            new_level = self._min_level(configured, OPTIMIZER_LEVEL_SHADOW)
            if new_level != configured:
                # Rate-cap clamp is the more "louder" reason — it indicates
                # the optimizer is throttling itself, which is operationally
                # noisier than quiet-hours. Prefer it over quiet_hours when
                # both fire on the same level.
                clamp_reason = "rate_capped"
            configured = new_level

        return configured, clamp_reason

    @property
    def effective_level(self) -> str:
        """Compute effective level (post-kill-switch, post-quiet, post-rate-cap)."""
        level, _reason = self._resolve_effective_level()
        return level

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
        """Read the per-dimension cap dict from CM options.

        B-C1: this dict is a CEILING, never a floor — a per-dimension
        entry can only LOWER the effective rung for that dimension below
        the configured CM-wide level; it can never raise it.
        Returns None when no cap is configured for the dimension.
        """
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
    ) -> tuple[float, str | None]:
        """L3+ ±20% clamp around the current value.

        H5 fix-up: returns ``(clamped_value, reject_reason)``. A non-None
        reason means the caller MUST NOT dispatch — the proposed value can
        not be safely clamped against the current state.

        Reject conditions:
          - current value is None / entity unavailable / unknown
            → ``current_value_unavailable``
          - current value is exactly 0.0 (clamp band would collapse to a
            single point, silently forcing the proposed to 0)
            → ``cannot_clamp_zero``

        Otherwise the proposed value is clamped to ``[current ± 20%]`` and
        further intersected with the target entity's reported ``min`` /
        ``max`` attributes when present.
        """
        st = self._state_value(target_entity)
        current = None
        attrs: dict = {}
        if st is None:
            return proposed_value, "current_value_unavailable"
        try:
            state_str = str(st.state).lower()
        except Exception:  # noqa: BLE001
            state_str = ""
        if state_str in ("unavailable", "unknown", "none", ""):
            return proposed_value, "current_value_unavailable"
        try:
            current = float(st.state)
        except (TypeError, ValueError):
            return proposed_value, "current_value_unavailable"
        try:
            attrs = dict(getattr(st, "attributes", {}) or {})
        except Exception:  # noqa: BLE001
            attrs = {}

        if current == 0.0:
            return proposed_value, "cannot_clamp_zero"

        band = abs(current) * OPTIMIZER_CONFIG_CLAMP_FRACTION
        lo = current - band
        hi = current + band

        # Intersect with the entity's reported min/max bounds when present.
        ent_min = attrs.get("min")
        ent_max = attrs.get("max")
        try:
            if ent_min is not None:
                lo = max(lo, float(ent_min))
            if ent_max is not None:
                hi = min(hi, float(ent_max))
        except (TypeError, ValueError):
            pass

        # If the intersection is empty/inverted, the entity's bounds
        # disallow ANY change from current — reject.
        if hi < lo:
            return proposed_value, "entity_bounds_exclude_band"

        if proposed_value < lo:
            return lo, None
        if proposed_value > hi:
            return hi, None
        return proposed_value, None

    async def _check_safety_denylist(
        self,
        finding: OptimizationFinding,
        action_id: str,
        level: str,
        target_entity: str,
        service: str,
        cm_config: dict,
    ) -> str | None:
        """B-B2 fix-up: refuse to actuate any entity in the safety
        deny-list. Returns the outcome string when blocked, else None.

        Applies to ALL findings (Tier-1 + Tier-2 LLM); Tier-2 LLM is the
        primary concern but a deterministic rule-bug could also propose
        a forbidden entity, so the guard is unconditional.

        Source of truth: CM-options key
        ``CONF_OPTIMIZER_SAFETY_DENY_ENTITIES`` (a list of entity_ids).
        Coordinator-enumerated safety/security entities are a planned
        extension (see Phase-3 backlog) — today the operator seeds the
        list explicitly.
        """
        if not target_entity:
            return None
        deny_raw = cm_config.get(CONF_OPTIMIZER_SAFETY_DENY_ENTITIES) or []
        if isinstance(deny_raw, str):
            deny_list = [deny_raw]
        elif isinstance(deny_raw, (list, tuple, set)):
            deny_list = [str(x) for x in deny_raw if isinstance(x, str)]
        else:
            deny_list = []
        if target_entity in deny_list:
            finding.applied_outcome = OPTIMIZER_OUTCOME_DISALLOWED
            await self._log_activity(
                action="clamped", importance="notable",
                description=(
                    f"safety_denylist: {target_entity} blocked from "
                    f"actuation ({service})"
                ),
                details={
                    "action_id": action_id, "level": level,
                    "reason": "safety_denylist",
                    "target_entity": target_entity,
                    "service": service,
                    "created_by": getattr(finding, "created_by", "tier1"),
                },
                finding=finding,
            )
            _LOGGER.info(
                "Optimizer: safety_denylist blocked %s (service=%s, "
                "created_by=%s)",
                target_entity, service,
                getattr(finding, "created_by", "tier1"),
            )
            return OPTIMIZER_OUTCOME_DISALLOWED
        return None

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

        # Compute effective level + clamp reason (post-kill, post-quiet,
        # post-rate-cap). H3/M3: track WHY the level was clamped so the
        # outcome row reflects rate_capped / quiet_hours instead of a
        # generic shadow row.
        level, clamp_reason = self._resolve_effective_level()
        # Per-dimension cap further reduces it.
        per_dim_cap = self._per_dimension_cap(str(finding.dimension))
        if per_dim_cap is not None:
            new_level = self._min_level(level, per_dim_cap)
            if new_level != level and clamp_reason is None:
                clamp_reason = "per_dimension_cap"
            level = new_level

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
            # B-B2 fix-up: safety / security deny-list check.
            deny_outcome = await self._check_safety_denylist(
                finding, action_id, level, target_entity, service, cm_config,
            )
            if deny_outcome is not None:
                return deny_outcome
            # L2 entry requirement.
            if not self._level_at_least(level, OPTIMIZER_LEVEL_REVERSIBLE_DEVICE):
                # We are at L1 shadow — emit intent dry-run + log.
                self.broker.fire_intent(
                    action_id, target_entity, service, service_data,
                    source_dimension=str(finding.dimension),
                    veto_window_s=0, action_class=action_class,
                    effective_level=level,
                )
                # H3/M3: if the level was clamped (rate-cap or quiet
                # hours), record the precise outcome so the DB column
                # distinguishes "configured at L1" from "L2+ clamped".
                if clamp_reason == "rate_capped":
                    finding.applied_outcome = OPTIMIZER_OUTCOME_RATE_CAPPED
                    outcome_str = OPTIMIZER_OUTCOME_RATE_CAPPED
                    activity_action = "clamped"
                    activity_reason = "rate_capped"
                elif clamp_reason == "quiet_hours":
                    finding.applied_outcome = OPTIMIZER_OUTCOME_QUIET_CLAMPED
                    outcome_str = OPTIMIZER_OUTCOME_QUIET_CLAMPED
                    activity_action = "clamped"
                    activity_reason = "quiet_hours"
                else:
                    finding.applied_outcome = OPTIMIZER_OUTCOME_SHADOW
                    outcome_str = OPTIMIZER_OUTCOME_SHADOW
                    activity_action = "shadow_dry_run"
                    activity_reason = None
                finding.predicted_effect = {
                    "service": service,
                    "service_data": service_data,
                    "note": "shadow_dry_run — no dispatch",
                    "clamp_reason": clamp_reason,
                }
                _details = {
                    "action_id": action_id, "level": level,
                    "target_entity": target_entity,
                    "service": service,
                    "predicted_effect": finding.predicted_effect,
                    "dimension": str(finding.dimension),
                }
                if activity_reason is not None:
                    _details["reason"] = activity_reason
                await self._log_activity(
                    action=activity_action, importance="info",
                    description=finding.description,
                    details=_details,
                    finding=finding,
                )
                return outcome_str
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
            # B-B2 fix-up: safety / security deny-list check (applies to
            # config-write writes as much as device actuation).
            deny_outcome = await self._check_safety_denylist(
                finding, action_id, level, target_entity, service, cm_config,
            )
            if deny_outcome is not None:
                return deny_outcome
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
        # A-CRIT-2: never dispatch a climate action into an egress-paused
        # zone — that defeats the EgressManager's pause and could leave
        # heating/cooling running with a window open.
        if target_entity and target_entity.startswith("climate."):
            em = self._get_egress_manager()
            if em is not None:
                zone_id = self._zone_id_for_climate_entity(target_entity)
                try:
                    if zone_id and em.is_paused(zone_id):
                        finding.applied_outcome = OPTIMIZER_OUTCOME_DISALLOWED
                        await self._log_activity(
                            action="clamped", importance="notable",
                            description=(
                                f"egress-paused: {target_entity} (zone={zone_id})"
                            ),
                            details={
                                "action_id": action_id, "level": level,
                                "reason": "egress_paused",
                                "target_entity": target_entity,
                                "zone_id": zone_id,
                            },
                            finding=finding,
                        )
                        return OPTIMIZER_OUTCOME_DISALLOWED
                except Exception:  # noqa: BLE001 — never crash dispatch
                    _LOGGER.debug(
                        "egress_manager.is_paused raised", exc_info=True,
                    )

        veto_window = 0
        if level == OPTIMIZER_LEVEL_PROPOSE_CONFIG:
            from ..const import OPTIMIZER_VETO_WINDOW_SECONDS_L3
            veto_window = OPTIMIZER_VETO_WINDOW_SECONDS_L3

        # A-HIGH-1: if the intent never reached siblings, do NOT proceed.
        intent_ok = self.broker.fire_intent(
            action_id, target_entity, service, service_data,
            source_dimension=str(finding.dimension),
            veto_window_s=veto_window, action_class="reversible_device",
            effective_level=level,
        )
        if not intent_ok:
            finding.applied_outcome = OPTIMIZER_OUTCOME_FAILED
            await self._log_activity(
                action="clamped", importance="notable",
                description=f"intent dispatch failed: {service}",
                details={"action_id": action_id, "level": level,
                         "reason": "intent_dispatch_failure",
                         "target_entity": target_entity, "service": service},
                finding=finding,
            )
            return OPTIMIZER_OUTCOME_FAILED

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

        # B-C3: kill switch may have been engaged DURING the up-to-30s veto
        # window. Re-read LIVE state (never the snapshot) and abort if so.
        cm_config_live = self._read_cm_config()
        if bool(cm_config_live.get(
            CONF_OPTIMIZER_KILL_SWITCH, DEFAULT_OPTIMIZER_KILL_SWITCH,
        )):
            finding.applied_outcome = OPTIMIZER_OUTCOME_KILL_SWITCH
            await self._log_activity(
                action="clamped", importance="notable",
                description=(
                    f"kill_switch engaged during veto window: "
                    f"{finding.description}"
                ),
                details={"action_id": action_id, "level": level,
                         "reason": OPTIMIZER_OUTCOME_KILL_SWITCH,
                         "target_entity": target_entity, "service": service},
                finding=finding,
            )
            return OPTIMIZER_OUTCOME_KILL_SWITCH

        # Open HVAC TTL window (no-op for non-climate).
        self.broker.suppress_climate(target_entity)
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
            # A-HIGH-3: action ran; forget any queued veto for THIS id so
            # a late-arriving veto can't bleed into a future action.
            self.broker.discard_pending(action_id)
            await self._log_activity(
                action="actuated", importance="notable",
                description=finding.description,
                details={"action_id": action_id, "level": level,
                         "target_entity": target_entity, "service": service},
                finding=finding,
            )
            return OPTIMIZER_OUTCOME_APPLIED
        except Exception as exc:  # noqa: BLE001
            self.broker.unsuppress_climate(target_entity)
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
        # H5: clamp helper now reports a reject reason for None/zero/unknown.
        clamped_data = dict(service_data)
        clamped = False
        if "value" in clamped_data:
            try:
                proposed = float(clamped_data["value"])
                new_value, reason = self._clamp_numeric_to_band(
                    target_entity, proposed,
                )
                if reason is not None:
                    finding.applied_outcome = OPTIMIZER_OUTCOME_FAILED
                    await self._log_activity(
                        action="clamped", importance="notable",
                        description=(
                            f"config_write clamp rejected ({reason}): "
                            f"{target_entity}"
                        ),
                        details={"action_id": action_id, "level": level,
                                 "reason": reason,
                                 "target_entity": target_entity,
                                 "proposed": proposed},
                        finding=finding,
                    )
                    return OPTIMIZER_OUTCOME_FAILED
                if new_value != proposed:
                    clamped = True
                clamped_data["value"] = new_value
            except (TypeError, ValueError):
                pass

        veto_window = 0
        if level == OPTIMIZER_LEVEL_PROPOSE_CONFIG:
            from ..const import OPTIMIZER_VETO_WINDOW_SECONDS_L3
            veto_window = OPTIMIZER_VETO_WINDOW_SECONDS_L3

        intent_ok = self.broker.fire_intent(
            action_id, target_entity, service, clamped_data,
            source_dimension=str(finding.dimension),
            veto_window_s=veto_window, action_class="config_write",
            effective_level=level,
        )
        if not intent_ok:
            finding.applied_outcome = OPTIMIZER_OUTCOME_FAILED
            await self._log_activity(
                action="clamped", importance="notable",
                description=f"intent dispatch failed: {service}",
                details={"action_id": action_id, "level": level,
                         "reason": "intent_dispatch_failure",
                         "target_entity": target_entity, "service": service},
                finding=finding,
            )
            return OPTIMIZER_OUTCOME_FAILED

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

        # B-C3: re-check live kill switch after veto wait.
        cm_config_live = self._read_cm_config()
        if bool(cm_config_live.get(
            CONF_OPTIMIZER_KILL_SWITCH, DEFAULT_OPTIMIZER_KILL_SWITCH,
        )):
            finding.applied_outcome = OPTIMIZER_OUTCOME_KILL_SWITCH
            await self._log_activity(
                action="clamped", importance="notable",
                description=(
                    f"kill_switch engaged during veto window: "
                    f"{finding.description}"
                ),
                details={"action_id": action_id, "level": level,
                         "reason": OPTIMIZER_OUTCOME_KILL_SWITCH,
                         "target_entity": target_entity, "service": service},
                finding=finding,
            )
            return OPTIMIZER_OUTCOME_KILL_SWITCH

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
            self.broker.discard_pending(action_id)
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
        """Apply gating uniformly, then dispatch if a proposed_action exists.

        H1 fix-up: the confidence gate now runs BEFORE the proposed_action
        branch so a below-gate finding is marked
        ``OPTIMIZER_OUTCOME_BELOW_GATE`` regardless of whether it carries
        a proposed action. Phase-1 dimensions emit only advisory rows; the
        path is wired so Phase-2 LLM-proposed actions flow through the
        same chokepoint without bypassing the gate.
        """
        # META sentinel rows are always advisory and never gated.
        if finding.dimension == OptimizationDimension.META:
            finding.applied_outcome = OPTIMIZER_OUTCOME_ADVISORY_ONLY
            return

        # H1: confidence gate first — applies to all non-META findings.
        gate = self._confidence_gate()
        try:
            conf = float(finding.confidence)
        except (TypeError, ValueError):
            conf = 0.0
        if conf < gate:
            finding.applied_outcome = OPTIMIZER_OUTCOME_BELOW_GATE
            await self._log_activity(
                action="clamped", importance="info",
                description=finding.description,
                details={
                    "reason": OPTIMIZER_OUTCOME_BELOW_GATE,
                    "confidence": conf, "gate": gate,
                    "dimension": str(finding.dimension),
                },
                finding=finding,
            )
            return

        if not finding.proposed_action:
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
        zone_findings: dict[str, list[OptimizationFinding]] = {}
        open_count = 0
        for f in findings:
            if f.dimension == OptimizationDimension.META:
                continue
            open_count += 1
            if f.level == "room" and f.target_id:
                room_findings.setdefault(f.target_id, []).append(f)
            elif f.level == "zone" and f.target_id:
                zone_findings.setdefault(f.target_id, []).append(f)
        # 100 if no findings, else 100 - (15 per finding) bounded at 0.
        self._room_scores = {}
        for room, room_fs in room_findings.items():
            self._room_scores[room] = max(0.0, 100.0 - 15.0 * len(room_fs))
        # Phase 3 — per-zone scoreboard (populated when a zone dimension fires).
        self._zone_scores = {}
        for zone_id, zone_fs in zone_findings.items():
            self._zone_scores[zone_id] = max(
                0.0, 100.0 - 15.0 * len(zone_fs)
            )
        if room_findings or zone_findings:
            worst = []
            if room_findings:
                worst.append(min(self._room_scores.values()))
            if zone_findings:
                worst.append(min(self._zone_scores.values()))
            self._house_score = min(worst) if worst else 100.0
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

    def get_zone_score(self, zone_id: str) -> float:
        """Return the current per-zone score (Phase 3).

        100.0 when no zone-level finding fired this cycle; otherwise
        100 - 15 * <count of open zone-level findings for that zone>,
        bounded at 0. Mirrors ``get_room_score``.
        """
        return self._zone_scores.get(zone_id, 100.0)

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

    # ------------------------------------------------------------------
    # Phase 3 — Daily digest builder
    # ------------------------------------------------------------------

    def build_daily_digest_payload(
        self, findings: list[OptimizationFinding] | None = None,
    ) -> dict:
        """Build the digest payload from a list of findings (in-memory).

        Returns a dict with:
          - ``date``: today's local-date ISO string
          - ``generated_at``: UTC ISO timestamp
          - ``findings_count``: int (excludes META sentinel)
          - ``by_severity``: dict[str, int]
          - ``by_dimension``: dict[str, int]
          - ``top``: list of up-to-OPTIMIZER_DIGEST_TOP_N abbreviated finding
            dicts (severity-sorted: critical → high → medium → low)
          - ``house_score``: float (final scoreboard score for the cycle)
        """
        src = findings if findings is not None else list(self._last_findings)
        by_sev: dict[str, int] = {
            "critical": 0, "high": 0, "medium": 0, "low": 0,
        }
        by_dim: dict[str, int] = {}
        real: list[OptimizationFinding] = []
        for f in src:
            if f.dimension == OptimizationDimension.META:
                continue
            if f.severity in by_sev:
                by_sev[f.severity] += 1
            dim = str(f.dimension)
            by_dim[dim] = by_dim.get(dim, 0) + 1
            real.append(f)
        sev_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        real.sort(key=lambda f: sev_rank.get(f.severity, 99))
        top = []
        for f in real[:OPTIMIZER_DIGEST_TOP_N]:
            top.append({
                "level": f.level,
                "target_id": f.target_id,
                "dimension": str(f.dimension),
                "severity": f.severity,
                "description": f.description,
            })
        now = dt_util.utcnow()
        return {
            "date": now.date().isoformat(),
            "generated_at": now.isoformat(),
            "findings_count": len(real),
            "by_severity": by_sev,
            "by_dimension": by_dim,
            "top": top,
            "house_score": float(self._house_score),
        }

    async def persist_daily_digest(
        self, findings: list[OptimizationFinding] | None = None,
    ) -> int | None:
        """Build + persist a digest row. Returns the new id or None."""
        database = self.hass.data.get(DOMAIN, {}).get("database")
        if database is None or not hasattr(database, "log_daily_digest"):
            return None
        payload = self.build_daily_digest_payload(findings=findings)
        try:
            return await database.log_daily_digest(
                date=payload["date"],
                generated_at=payload["generated_at"],
                findings_count=payload["findings_count"],
                by_severity=payload["by_severity"],
                by_dimension=payload["by_dimension"],
                summary=payload,
            )
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("persist_daily_digest failed: %s", exc)
            return None

    def format_digest_section(
        self, findings: list[OptimizationFinding] | None = None,
    ) -> str:
        """Render a short text section for the NM person digest.

        Lines:
          ``Optimizer (N findings, house score X):``
          ``  ! 2x high - <description>``
        Returns an empty string when there are zero non-META findings, so
        the NM hook can skip appending entirely on a clean day.
        """
        payload = self.build_daily_digest_payload(findings=findings)
        count = payload["findings_count"]
        if count == 0:
            return ""
        lines = [
            f"Optimizer ({count} findings, house score "
            f"{payload['house_score']:.0f}):",
        ]
        for entry in payload["top"]:
            sev = str(entry.get("severity", "")).lower()
            icon = "!!" if sev in ("critical", "high") else "!"
            desc = entry.get("description", "")
            lines.append(f"  {icon} {sev} - {desc}")
        return "\n".join(lines)
