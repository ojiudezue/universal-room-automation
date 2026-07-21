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
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from homeassistant.core import HomeAssistant, callback
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
    # v5.3.0 Phase 4 — Prediction-Validation pillar.
    OPTIMIZER_DIMENSION_PREDICTION_ACCURACY,
    OPTIMIZER_PREDICTION_ACCURACY_TOP1_FLOOR_PCT,
    OPTIMIZER_PREDICTION_ACCURACY_BRIER_CEILING,
    OPTIMIZER_PREDICTION_ACCURACY_MIN_SAMPLES,
    OPTIMIZER_PREDICTION_ACCURACY_DATA_QUALITY_FLOOR_PCT,
    OPTIMIZER_PREDICTION_ACCURACY_WINDOW_DAYS,
    OPTIMIZER_DIGEST_RETENTION_DAYS,
    OPTIMIZER_DIGEST_TOP_N,
    OPTIMIZER_NOTIFY_DEDUP_CYCLES,
    OPTIMIZER_OCCUPANCY_ACCURACY_GATE_SECONDS,
    OPTIMIZER_LEVEL_ADVISORY,
    OPTIMIZER_LEVEL_IMMEDIATE_CONFIG,
    OPTIMIZER_LEVEL_PROPOSE_CONFIG,
    OPTIMIZER_LEVEL_RANK,
    OPTIMIZER_LEVEL_REVERSIBLE_DEVICE,
    OPTIMIZER_LEVEL_SHADOW,
    OPTIMIZER_LEVEL_UNBOUNDED,
    # v5.2.2 — post-mortem write-queue saturation guardrails.
    OPTIMIZER_MAX_FINDINGS_PER_CYCLE,
    OPTIMIZER_BOOT_SETTLE_CYCLES,
    OPTIMIZER_BOOT_STORM_ROOM_FRACTION,
    # v5.11.0 — OC hardening: tripwire + stub filter + shadow persistence.
    OPTIMIZER_WRITE_VOLUME_WINDOW_SECONDS,
    OPTIMIZER_WRITE_VOLUME_THRESHOLD,
    OPTIMIZER_STUB_DIMENSIONS,
    OPTIMIZER_BOOT_STORM_CACHE_CYCLES,
    OPTIMIZER_SHADOW_SAMPLE_MAX_ROWS,
    OPTIMIZER_PROMOTION_READINESS_MIN_SAMPLES,
    OPTIMIZER_PROMOTION_READINESS_ACCURACY_FLOOR,
    OPTIMIZER_SHADOW_ACCURACY_MIN_SAMPLES,
    OPTIMIZER_SHADOW_ACCURACY_WINDOW_DAYS,
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
    # v5.3.0 Phase 4 — Prediction-Validation pillar (house-level advisory).
    PREDICTION_ACCURACY = OPTIMIZER_DIMENSION_PREDICTION_ACCURACY

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
    # v5.4 D2c — optional LLM reasoning prose (additive). Populated by
    # OptimizationLLMTier when the LLM response includes a `reasoning`
    # field; empty for Tier-1 findings or LLM responses without it.
    # Hard-capped to 512 chars at parse time.
    reasoning: str = ""


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

        def _cmp_ts(ts):
            # Naive/aware tolerance: a naive stamp (legacy writer or test
            # seed) is treated as UTC rather than raising TypeError on
            # comparison — this week's recurring bug class. cutoff side
            # mirrors so naive-mocked clocks (test envs) also compare.
            if ts.tzinfo is None and cutoff.tzinfo is not None:
                return ts.replace(tzinfo=cutoff.tzinfo)
            if ts.tzinfo is not None and cutoff.tzinfo is None:
                return ts.replace(tzinfo=None)
            return ts

        stale = [
            aid for aid, (ts, _by) in self._pending_vetoes.items()
            if _cmp_ts(ts) < cutoff
        ]
        for aid in stale:
            self._pending_vetoes.pop(aid, None)
        # Hard cap as a belt-and-suspenders bound.
        if len(self._pending_vetoes) > self._VETO_MAX_PENDING:
            # Drop oldest until under cap.
            items = sorted(
                self._pending_vetoes.items(), key=lambda kv: _cmp_ts(kv[1][0])
            )
            overflow = len(items) - self._VETO_MAX_PENDING
            for aid, _ in items[:overflow]:
                self._pending_vetoes.pop(aid, None)

    @callback
    def _on_veto(self, payload: dict) -> None:
        action_id = payload.get("action_id") if isinstance(payload, dict) else None
        if not action_id:
            return
        vetoed_by = (
            payload.get("vetoed_by", "unknown")
            if isinstance(payload, dict)
            else "unknown"
        )
        # C-C6 fix-up: keep the FIRST veto per action_id so ``vetoed_by``
        # attribution is deterministic when two siblings veto the same
        # intent in the same event-loop turn. A later sibling's veto
        # would otherwise clobber the first responder's name.
        if action_id not in self._pending_vetoes:
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

        A4 fix-up: CM is authoritative. The legacy
        ``hass.data[DOMAIN]["hvac_coordinator"]`` slot is gated behind the
        ``_optimizer_test_mode`` flag so production cannot read a stale
        injection that would win over the CM-managed coordinator. Tests
        that need the legacy injection set the flag explicitly.
        """
        try:
            domain_data = self.hass.data.get(DOMAIN, {}) or {}
            cm = domain_data.get("coordinator_manager")
            if cm is not None:
                coords = getattr(cm, "coordinators", None) or {}
                hvac = coords.get("hvac")
                if hvac is not None:
                    return hvac
            # Test-only back-compat: opt-in via the explicit test flag.
            if domain_data.get("_optimizer_test_mode"):
                return domain_data.get("hvac_coordinator")
            return None
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

        # v5.2.2 fix-up — per-cycle activity-log buffers. The Phase-1
        # ``_consider_apply`` shadow + below-gate branches USED to call
        # ``_log_activity`` for every finding, which produced an O(N)
        # INSERT into ``ura_activity_log`` and an O(N) per-row
        # ``SIGNAL_ACTIVITY_LOGGED`` dispatch (the SECOND write-flood
        # channel the v5.2.2 batching missed — confirmed by adversarial
        # review after the live house went down). The fix: buffer per
        # cycle, emit AT MOST ONE summary row per buffer at the end of
        # ``run_cycle``. Cleared at the start of every cycle.
        self._cycle_shadow_log_buffer: list[dict] = []
        self._cycle_clamp_log_buffer: list[dict] = []

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
        # A6 fix-up: per-room sustained occupancy/motion disagreement tracking.
        # Disagreement must persist >= OPTIMIZER_OCCUPANCY_ACCURACY_GATE_SECONDS
        # before emitting (motion-on/occupancy-off is transient at wake).
        self._occ_accuracy_disagreement_since: dict[str, datetime] = {}
        # Phase 3 — per-zone scoreboard (populated post-cycle).
        self._zone_scores: dict[str, float] = {}

        # v5.4 D2b — per-dimension verdicts derived from the last cycle's
        # findings. Key = dimension token, value ∈ {ok, advisory, degraded,
        # critical, not_run}. Populated at the end of every cycle.
        self._last_dimension_verdicts: dict[str, str] = {}
        # v5.4 D2a — last-cycle reasoning text + summary so the new
        # OptimizerReasoningSensor can render plain-English commentary.
        self._last_cycle_summary: str = ""
        self._last_cycle_actions_proposed: list[dict] = []
        # v5.4 D2d — rolling shadow-accuracy validator state. The
        # `OPTIMIZER_SHADOW_ACCURACY_*` constants gate warm-up.
        # Stored as a list of (observed_at_utc_iso, match_bool) tuples;
        # consumers compute the % over the trailing window.
        # v5.11.0 D2 — samples upgraded from (ts, matched) to
        # (ts, dimension, target_id, matched) to enable per-dimension
        # accuracy for D6 promotion_readiness. Legacy shape still
        # accepted at read time for restore-from-DB compat.
        self._shadow_accuracy_samples: list[tuple] = []
        self._last_shadow_accuracy_pct: float | None = None
        self._last_shadow_accuracy_status: str = "warming_up"

        # Cycle handle.
        self._cycle_unsub = None

        # v5.2.2 — boot-settle counter. The first
        # ``OPTIMIZER_BOOT_SETTLE_CYCLES`` cycles after coordinator start
        # SKIP persistence + signal dispatch (META sentinel still emits)
        # so the cold-boot unavailable-sensor sweep can't flood the
        # write queue. Real-time integration tests can monkey-patch
        # this to 0 if they need first-cycle persistence.
        self._cycles_since_start: int = 0

        # Phase 2 — LLM Tier-2 wrapper. Lazily constructed so importing
        # the optimizer module doesn't trigger the LLM import chain when
        # only Phase-1 is being used.
        self._llm_tier = None

        # Pillar B (Phase 5) fix-up B-H1: reentrancy guard for run_cycle.
        # Protects against manual-press-vs-interval overlap (the
        # OptimizerRunCycleNowButton calls run_cycle directly while the
        # 5-min tick may also be in flight) AND tick-vs-tick races during
        # boot. Set/cleared in the run_cycle try/finally.
        self._cycle_running: bool = False

        # v5.11.0 D9 — runtime write-volume tripwire. Counts OC-attributed
        # DB writes in a rolling window. If it exceeds threshold, OC
        # self-suspends its PERSISTENCE path (evaluation still runs), fires
        # ONE NM anomaly, and sets ``_write_volume_alarmed_at``. This is
        # the code-level trip-wire the v5.0.0-v5.2.1 incident postmortem
        # demanded. The counter itself never touches the DB — it's a
        # cheap in-memory deque of timestamps.
        self._db_write_timestamps: deque[datetime] = deque()
        self._write_volume_alarmed_at: str | None = None
        self._persistence_suspended: bool = False

        # v5.11.0 D4 — boot-storm gate cache. Once the gate returns
        # "no boot-storm", cache the negative verdict for
        # OPTIMIZER_BOOT_STORM_CACHE_CYCLES cycles so the ~150 state
        # reads per steady-state cycle stop.
        self._boot_storm_cache_cycles_remaining: int = 0
        self._boot_storm_cache_expires_iso: str | None = None

        # v5.11.0 D1 — notify-dedup TTL state (fix MED-3: decrement is
        # now per-cycle, not per-finding). Eagerly initialized here so
        # ``hasattr(self, "_notify_dedup_state")`` warts in the old code
        # are gone.
        self._notify_dedup_state: dict[str, int] = {}
        # v5.11.0 F-MED (A-MED-1 fix-up): keys recorded THIS cycle in
        # ``_notify_if_severe`` are stashed here so ``_decrement_notify
        # _dedup_ttls`` can skip them exactly once (avoids collapsing
        # the intended 12-cycle window to 11 via a same-cycle
        # decrement). Cleared at end-of-cycle by the decrement helper.
        self._notify_dedup_just_set: set[str] = set()

        # v5.11.0 D2 — pending shadow-accuracy samples for this cycle.
        # Batched write on cycle end (never per-sample). Drained by
        # ``_persist_shadow_samples_batch``.
        self._pending_shadow_samples: list[tuple[str, str, str, bool]] = []

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
            # v5.11.0 D8 (LOW-2 fix): elevate to WARNING so a persistent
            # DB seed error is visible to the operator — silent DEBUG
            # would mask silent invariant loss (rate-cap disabled).
            _LOGGER.warning(
                "Optimizer: rate-cap seed from DB failed (non-fatal); "
                "the per-hour cap will cold-start (may over-issue actions "
                "until the deque fills organically)",
                exc_info=True,
            )

        # v5.11.0 D2 — restore shadow-accuracy samples from the DB so the
        # rolling accuracy % survives HA restarts (MED-2 fix). Without
        # this the `warming_up` gate never closes (blocks L1→L2). Best-
        # effort: falls back to a cold list if DB read fails.
        try:
            db = self.hass.data.get(DOMAIN, {}).get("database")
            if db is not None and hasattr(db, "get_recent_shadow_samples"):
                rows = await db.get_recent_shadow_samples(
                    window_days=OPTIMIZER_SHADOW_ACCURACY_WINDOW_DAYS,
                    limit=OPTIMIZER_SHADOW_SAMPLE_MAX_ROWS,
                )
                restored = 0
                for r in rows or []:
                    try:
                        ts = str(r.get("observed_at"))
                        dim = str(r.get("dimension"))
                        target = r.get("target_id")
                        matched = bool(r.get("matched"))
                        self._shadow_accuracy_samples.append(
                            (ts, dim,
                             target if isinstance(target, str) else "",
                             matched)
                        )
                        restored += 1
                    except Exception:  # noqa: BLE001
                        continue
                if restored:
                    _LOGGER.info(
                        "Optimizer: restored %d shadow-accuracy samples "
                        "from the last %d days",
                        restored, OPTIMIZER_SHADOW_ACCURACY_WINDOW_DAYS,
                    )
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "Optimizer: shadow-sample restore from DB failed",
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
        # A5 fix-up: once-per-startup record of which Phase 3 dimensions are
        # deferred stubs (substrate not cleanly available). Helps the operator
        # tell "rule ran, no issues" from "rule isn't really online yet"
        # without spamming each 5-min cycle.
        _LOGGER.debug(
            "Optimizer: deferred-stub dimensions (return [] until Phase 3.x): "
            "automation_responsiveness, energy_efficiency, setpoint_compliance"
        )

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

        A1 fix-up: each evaluator runs inside its own try/except so one
        buggy dimension can't blackhole the cycle's META sentinel or any
        later dimension. Failures log a WARNING with the evaluator name and
        cycle proceeds; the META sentinel ALWAYS emits so Review-D's
        sentinels-only diagnostic stays trustworthy.

        Pillar B (Phase 5) fix-up B-H1: reentrancy guard. The
        OptimizerRunCycleNowButton calls run_cycle directly and the 5-min
        interval tick can also fire concurrently. If a cycle is already in
        flight, log debug + return an empty list rather than running two
        cycles in parallel.
        """
        if self._cycle_running:
            _LOGGER.debug(
                "Optimization run_cycle re-entry suppressed "
                "(cycle already in flight)",
            )
            return []
        self._cycle_running = True
        try:
            return await self._run_cycle_body()
        finally:
            self._cycle_running = False

    async def _run_cycle_body(self) -> list[OptimizationFinding]:
        """Run the cycle body (no reentrancy guard — caller holds it)."""
        self._cycle_dedup.clear()
        # v5.2.2 fix-up — reset per-cycle activity-log buffers. The
        # ``_consider_apply`` shadow + below-gate branches buffer here
        # instead of doing one INSERT per finding; the cycle drains
        # them at the end as AT MOST one summary row per buffer.
        self._cycle_shadow_log_buffer.clear()
        self._cycle_clamp_log_buffer.clear()
        findings: list[OptimizationFinding] = []
        # Each entry: (name-for-logging, callable-returning-list)
        evaluators: tuple[tuple[str, Any], ...] = (
            # Phase 1 dimensions.
            ("sensor_health", self._evaluate_sensor_health_dimension),
            ("comfort", self._evaluate_comfort_dimension),
            # Phase 3 — room-level.
            ("occupancy_accuracy", self._evaluate_occupancy_accuracy_dimension),
            ("automation_responsiveness",
             self._evaluate_automation_responsiveness_dimension),
            ("config_behavior", self._evaluate_config_behavior_dimension),
            ("energy_efficiency", self._evaluate_energy_efficiency_dimension),
            # Phase 3 — zone-level.
            ("setpoint_compliance",
             self._evaluate_setpoint_compliance_dimension),
            ("vacancy_management",
             self._evaluate_vacancy_management_dimension),
            ("override_frequency",
             self._evaluate_override_frequency_dimension),
            # Phase 3 — house-level.
            ("state_machine_accuracy",
             self._evaluate_state_machine_accuracy_dimension),
            ("security_posture", self._evaluate_security_posture_dimension),
            # v5.3.0 Phase 4 — Prediction-Validation pillar. House-level
            # READ-ONLY reader of existing Bayesian accuracy surfaces; emits
            # advisory (proposed_action=None) findings that flow through the
            # SAME shared batched persist path (no new DB write channel).
            ("prediction_accuracy",
             self._evaluate_prediction_accuracy_dimension),
        )
        # v5.4 D2b — per-evaluator finding tally so we can derive
        # `dimension_verdicts` without re-walking findings. Maps
        # dimension token → list[finding] emitted by THIS evaluator.
        # Failed evaluators go into `_raised_dims` so the verdict is
        # `not_run` (distinguishable from `ok`).
        per_dim_findings: dict[str, list[OptimizationFinding]] = {}
        raised_dims: set[str] = set()
        for name, fn in evaluators:
            # Pre-seed the bucket so dimensions that emit nothing get an
            # explicit `ok` verdict rather than missing from the dict.
            per_dim_findings.setdefault(name, [])
            try:
                # v5.3.0 Phase 4 — evaluators may be sync or async (the
                # Prediction-Accuracy reader awaits a DB-backed predictor
                # method). Detect coroutine returns and await them so all
                # other Phase-1/3 evaluators keep their sync contract.
                result = fn()
                if asyncio.iscoroutine(result):
                    result = await result
                emitted = list(result or [])
                findings.extend(emitted)
                per_dim_findings[name].extend(emitted)
            except Exception as exc:  # noqa: BLE001 — never let one dim kill the cycle
                _LOGGER.warning(
                    "Optimizer evaluator '%s' raised; skipping this dim "
                    "(cycle continues): %s", name, exc, exc_info=True,
                )
                raised_dims.add(name)

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

        # v5.2.2 — bound per-cycle cost. If a pathological dimension
        # emits more rows than the sane cap, truncate (highest-severity
        # first) before persistence so the write queue can't be flooded.
        findings = self._cap_findings(findings)

        # Score + (optionally) gate-and-apply each finding. Persistence
        # + signal dispatch are batched to ONE write + ONE signal per
        # cycle (v5.2.2 post-mortem fix for DB write-queue saturation).
        self._update_scoreboard(findings)

        # Boot-storm gate: during the first few cycles or while the
        # house's configured sensors are mostly `unavailable` (cold-boot
        # signature), SKIP persistence + dispatch to keep the write
        # queue free for core URA writes. The META sentinel is still
        # persisted so Review-D's "did the cycle run" diagnostic stays
        # truthful.
        skip_persist, skip_reason = self._should_skip_for_boot_storm(findings)
        self._cycles_since_start += 1

        for finding in findings:
            # CPU-only at L1 Shadow: ``_consider_apply``'s shadow +
            # below-gate branches APPEND to per-cycle buffers (no DB
            # write per finding). v5.2.2 fix-up — previous comment
            # claimed "no DB write inside _consider_apply" but
            # ``_log_activity`` was called per finding, hitting
            # ura_activity_log O(N) times (the SECOND write-flood
            # channel adversarial review caught). Now buffered and
            # drained as AT MOST one summary row per buffer below.
            await self._consider_apply(finding)
            await self._notify_if_severe(finding)

        if skip_persist:
            _LOGGER.info(
                "Optimizer cycle: persistence skipped — %s "
                "(findings=%d held back; META sentinel will still persist)",
                skip_reason, len(findings),
            )
            # Still persist the META sentinel(s) so the cycle's
            # liveness signal lands in the table.
            meta_only = [f for f in findings
                         if f.dimension == OptimizationDimension.META]
            await self._persist_findings_batch(meta_only)
            llm_findings: list[OptimizationFinding] = []
            # v5.2.2 fix-up — the skip path must NOT do O(N) activity
            # writes either. Drop the buffered shadow/clamp records
            # (the gate said "skip persistence"); no summary row
            # emitted. This locks in that boot-storm-skip is truly
            # write-quiet on ura_activity_log too.
            self._cycle_shadow_log_buffer.clear()
            self._cycle_clamp_log_buffer.clear()
        else:
            await self._persist_findings_batch(findings)
            # Phase 2 — LLM Tier-2 pass. Runs AFTER Tier-1 so the LLM
            # sees the just-emitted Tier-1 findings in its corpus. The
            # tier internally enforces: configured-entity guard, delta
            # gate, daily premium cap, optional cheap-triage routing.
            # Every LLM finding flows through the SAME ``_consider_apply``
            # chokepoint (no bypass path).
            llm_findings = await self._maybe_run_llm_tier(findings)
            llm_findings = self._cap_findings(llm_findings)
            for finding in llm_findings:
                # `_consider_apply` already ran inside the LLM tier;
                # only notify here. Persistence batched below.
                await self._notify_if_severe(finding)
            await self._persist_findings_batch(llm_findings)
            # v5.2.2 fix-up — drain the per-cycle activity buffers as
            # AT MOST one summary row each (shadow + clamp). Preserves
            # operator observability ("the optimizer advised N shadow
            # findings this cycle") at O(1) DB cost regardless of N.
            await self._flush_cycle_activity_summaries()

        # ONE signal dispatch per cycle (replaces the per-finding
        # SIGNAL_OPTIMIZER_FINDING_EMITTED fan-out that triggered
        # websocket backpressure in the v5.2.1 incident). The ~35
        # per-room / optimizer sensors that subscribe re-read coordinator
        # state on any payload (they ignore payload contents — verified
        # at sensor.py:13637, 13858), so a single fire is sufficient.
        self._dispatch_findings_updated_signal()

        # v5.11.0 D3 — apply cap ONCE MORE on the merged list. Tier-1 and
        # LLM tiers each cap independently; the merged list can peak at
        # 2×cap = 200 in pathological cycles. Cap-of-caps enforces the
        # single global bound on ``_last_findings``.
        all_findings = self._cap_findings(list(findings) + list(llm_findings))
        self._last_findings = all_findings
        # v5.11.0 D1 — decrement notify-dedup TTLs ONCE per cycle.
        # Previously (v4.7.36 A2) the decrement ran INSIDE
        # ``_notify_if_severe`` — per-finding — which collapsed the
        # intended 12-cycle window to 1.2 cycles in high-severity cycles.
        # Now it decrements exactly once per cycle regardless of finding
        # count. See MED-3 in PLANNING_audit_optimization_coordinator.md.
        # v5.11.0 F1 (MED-1 fix-up): also skip the decrement for dedup
        # keys we set THIS cycle (see ``_notify_if_severe``). Otherwise a
        # freshly-set key gets one free cycle burned off the intended
        # 12-cycle window on the very cycle it was recorded.
        self._decrement_notify_dedup_ttls()
        self._last_evaluation_iso = dt_util.utcnow().isoformat()
        # v5.4 D2b — compute per-dimension verdicts from this cycle's
        # findings. Result keyed by dimension token; value derived from
        # highest-severity finding produced (no findings → ok; raised
        # evaluator → not_run).
        self._last_dimension_verdicts = self._compute_dimension_verdicts(
            per_dim_findings, raised_dims,
        )
        # v5.4 D2a — render the cycle reasoning text + proposed-actions
        # snapshot for the OptimizerReasoningSensor. Cycle-bounded:
        # truncated/capped so the recorder doesn't bloat.
        (
            self._last_cycle_summary,
            self._last_cycle_actions_proposed,
        ) = self._render_cycle_reasoning(all_findings)
        # v5.4 D2d — run the shadow-accuracy validator: walk findings
        # whose predicted_effect was set ≥ OBSERVE_DELAY ago and populate
        # observed_effect. Best-effort: a single match-check raising must
        # not blackhole the cycle (mirrors A1 evaluator pattern).
        # v5.11.0 F2 (fix-up): validator MUST run BEFORE the sample
        # persist so the samples it buffers this cycle land in the same
        # DAO call. Previously the persist ran first, adding a one-cycle
        # lag between validator output and DB row.
        try:
            self._run_shadow_accuracy_validator()
        except Exception:  # noqa: BLE001 — defensive
            _LOGGER.debug(
                "Optimizer shadow-accuracy validator raised; ignoring",
                exc_info=True,
            )
        # v5.11.0 D2 — batched persistence of shadow-accuracy samples.
        # Gated by the D9 tripwire; single DAO call per cycle.
        # v5.11.0 F2 (fix-up): boot-storm-skip cycles MUST be write-quiet
        # on this channel too — mirror the activity-buffer treatment.
        # Drop-and-clear so the buffer can't accumulate across skips
        # and then over-write on the first non-skip cycle.
        if skip_persist:
            self._pending_shadow_samples.clear()
        else:
            try:
                await self._persist_shadow_samples_batch()
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "Optimizer: shadow-sample batch persist raised",
                    exc_info=True,
                )
        return all_findings

    # ------------------------------------------------------------------
    # v5.4 D2 — observability helpers (verdicts, reasoning, shadow accuracy)
    # ------------------------------------------------------------------

    # Severity → verdict token mapping (D2b).
    _SEVERITY_VERDICT_MAP = {
        "low": "advisory",
        "medium": "degraded",
        "high": "critical",
        "critical": "critical",
    }

    @property
    def dry_run_veto_count(self) -> int:
        """Public read-only view for the OC reasoning sensor (D2a).

        Returns the current count of pending vetoes recorded on the
        intent broker. The broker ages out stale entries on each
        await/evict pass, so this is a near-realtime gauge.
        """
        try:
            return len(self.broker._pending_vetoes)
        except Exception:  # noqa: BLE001
            return 0

    def _compute_dimension_verdicts(
        self,
        per_dim_findings: dict[str, list[OptimizationFinding]],
        raised_dims: set[str],
    ) -> dict[str, str]:
        """Derive `dimension_verdicts` for D2b.

        For each dimension that ran this cycle:
          - evaluator raised → `not_run`
          - no findings emitted → `ok`
          - highest severity ∈ severity-verdict map → `advisory` /
            `degraded` / `critical`

        Unknown severity is mapped to `advisory` (conservative).
        """
        verdicts: dict[str, str] = {}
        severity_rank = {"low": 1, "medium": 2, "high": 3, "critical": 4}
        for dim, dim_findings in per_dim_findings.items():
            # v5.11.0 D5 — mark stub dimensions with an explicit `stub`
            # verdict so operators inspecting `dimension_verdicts` don't
            # see silent `ok` on dims that were never actually built.
            # Kept in the map so the presence of stubs stays visible;
            # display filtering happens on the reasoning sensor.
            if dim in OPTIMIZER_STUB_DIMENSIONS:
                verdicts[dim] = "stub"
                continue
            if dim in raised_dims:
                verdicts[dim] = "not_run"
                continue
            if not dim_findings:
                verdicts[dim] = "ok"
                continue
            top_sev = None
            top_rank = -1
            for f in dim_findings:
                sev = getattr(f, "severity", None)
                if not isinstance(sev, str):
                    continue
                rank = severity_rank.get(sev.lower(), 0)
                if rank > top_rank:
                    top_rank = rank
                    top_sev = sev.lower()
            if top_sev is None:
                verdicts[dim] = "ok"
                continue
            verdicts[dim] = self._SEVERITY_VERDICT_MAP.get(
                top_sev, "advisory",
            )
        return verdicts

    def _render_cycle_reasoning(
        self,
        all_findings: list[OptimizationFinding],
    ) -> tuple[str, list[dict]]:
        """Build the plain-English `cycle_summary` + `cycle_actions_proposed`.

        Returns (summary_text, actions_list). Summary is truncated to
        1024 chars; actions list capped at 20 entries (matches the
        existing findings-cap on OptimizerFindingsSensor).
        """
        # Skip the META sentinel — it's bookkeeping noise.
        non_meta = [
            f for f in all_findings
            if str(f.dimension) != "meta"
        ]
        if not non_meta:
            return "cycle_ok — no findings", []
        # Count by severity for the headline.
        sev_counts: dict[str, int] = {}
        for f in non_meta:
            sev = (getattr(f, "severity", "low") or "low").lower()
            sev_counts[sev] = sev_counts.get(sev, 0) + 1
        # Per-dimension one-liner: "<dim>: <count> finding(s), highest=<sev>".
        by_dim: dict[str, list[OptimizationFinding]] = {}
        for f in non_meta:
            by_dim.setdefault(str(f.dimension), []).append(f)
        lines: list[str] = []
        # Headline.
        total = len(non_meta)
        headline_parts = [f"cycle ok — {total} finding(s)"]
        for sev in ("critical", "high", "medium", "low"):
            if sev in sev_counts:
                headline_parts.append(f"{sev_counts[sev]} {sev}")
        lines.append(", ".join(headline_parts))
        # B-LOW-1: reuse the same severity_rank map _compute_dimension_verdicts
        # uses (single source of truth for severity ordering).
        severity_rank = {"low": 1, "medium": 2, "high": 3, "critical": 4}
        for dim, dim_findings in sorted(by_dim.items()):
            severities = [
                (getattr(f, "severity", "low") or "low").lower()
                for f in dim_findings
            ]
            highest = max(severities, key=lambda s: severity_rank.get(s, 0))
            lines.append(
                f"{dim}: {len(dim_findings)} finding(s), highest={highest}",
            )
        summary = "\n".join(lines)[:1024]
        # Cycle-actions snapshot — only entries with a proposed_action.
        actions: list[dict] = []
        for f in non_meta:
            if not f.proposed_action:
                continue
            entry = {
                "dimension": str(f.dimension),
                "severity": f.severity,
                "target_id": f.target_id,
                "target_entity": (
                    f.proposed_action.get("target_entity")
                    or f.proposed_action.get("entity_id")
                ),
                "action": (
                    f.proposed_action.get("service")
                    or f.proposed_action.get("action")
                ),
                "outcome": f.applied_outcome,
                "predicted_effect": f.predicted_effect,
            }
            actions.append(entry)
            if len(actions) >= 20:
                break
        return summary, actions

    def _run_shadow_accuracy_validator(self) -> None:
        """v5.4 D2d — walk `_last_findings` and populate observed_effect.

        Scope: SHADOW-outcome findings only (filter on applied_outcome ==
        OPTIMIZER_OUTCOME_SHADOW). Targets COMFORT + OCCUPANCY_ACCURACY
        dimensions for v1 (clean oracles); other dimensions emit
        observed_effect={"match": None, "evidence": "unscorable"} so
        the Pillar-4 prediction_accuracy reader does NOT collide with
        this one (filtered out from the % calc).

        Match policy (v1):
          - COMFORT: predicted_effect.predicted_direction == "toward_target";
            observed iff room temperature has moved toward target since the
            predicted_effect was recorded. Read-only check; tolerant of
            missing surfaces (→ match=None).
          - OCCUPANCY_ACCURACY: predicted_effect.predicted_recovery is
            scored "did the flagged occupancy sensor change state at least
            once since the prediction was recorded" — also tolerant.

        Population rule: only operate on findings whose timestamp is at
        least `OPTIMIZER_SHADOW_OBSERVE_DELAY_S` in the past, so the
        observation window is meaningful. Updates `_shadow_accuracy_samples`
        and recomputes the rolling pct + status.
        """
        from ..const import (
            OPTIMIZER_OUTCOME_SHADOW,
            OPTIMIZER_SHADOW_OBSERVE_DELAY_S,
            OPTIMIZER_SHADOW_ACCURACY_MIN_SAMPLES,
            OPTIMIZER_SHADOW_ACCURACY_WINDOW_DAYS,
        )
        now = dt_util.utcnow()
        # Normalize to aware UTC: dt_util.utcnow() returns aware in
        # production but some test harnesses substitute datetime.utcnow
        # (naive). Coercing here once means EVERY downstream comparison
        # against parsed `ts` is naive-safe.
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        cutoff = now - timedelta(seconds=OPTIMIZER_SHADOW_OBSERVE_DELAY_S)
        # v1 scorable dimensions.
        scorable = {"comfort", "occupancy_accuracy"}
        # B-MED-1: distinguish "no samples yet" (warming_up) from
        # "oracle wired but reading nothing" (no_observable_data). The
        # latter means the oracle was invoked against scorable findings
        # but every result was inconclusive (match=None) — typically the
        # phantom-surface failure mode B-HIGH-1 was about. We count
        # scorable findings actually evaluated and the subset whose
        # oracle returned match=None.
        scorable_evaluated = 0
        scorable_inconclusive = 0
        for finding in self._last_findings:
            if finding.applied_outcome != OPTIMIZER_OUTCOME_SHADOW:
                continue
            if finding.predicted_effect is None:
                continue
            if finding.observed_effect is not None:
                continue
            try:
                ts = datetime.fromisoformat(finding.timestamp)
                if ts.tzinfo is None:
                    # Normalize naive → aware UTC so cutoff comparison
                    # (always aware via dt_util.utcnow()) never mixes
                    # offset-naive and offset-aware datetimes. Matches
                    # the rest of the optimizer's timestamp discipline.
                    ts = ts.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                continue
            if ts > cutoff:
                # Too recent to score; wait another cycle.
                continue
            dim_str = str(finding.dimension)
            if dim_str not in scorable:
                # Unscorable in v1 — record explicitly so the rolling %
                # calc can skip; this also avoids colliding with the
                # Pillar-4 reader on the same observed_effect slot.
                finding.observed_effect = {
                    "match": None,
                    "evidence": "unscorable",
                    "observed_at": now.isoformat(),
                }
                continue
            try:
                match, evidence = self._score_shadow_finding(finding)
            except Exception:  # noqa: BLE001 — best-effort
                _LOGGER.debug(
                    "Shadow-accuracy match check raised on %s",
                    finding.dedup_key, exc_info=True,
                )
                continue
            finding.observed_effect = {
                "match": match,
                "evidence": evidence,
                "observed_at": now.isoformat(),
            }
            scorable_evaluated += 1
            if match is None:
                scorable_inconclusive += 1
            else:
                # v5.11.0 D2 — upgrade sample shape to 4-tuple:
                # (ts_iso, dimension, target_id, matched). Enables per-
                # dimension accuracy for promotion_readiness (D6).
                _tgt = finding.target_id or ""
                sample = (
                    now.isoformat(), dim_str, _tgt, bool(match),
                )
                self._shadow_accuracy_samples.append(sample)
                # v5.11.0 D2 — also buffer for batched DB persistence.
                # Defensive: test harnesses may instantiate the coord
                # without going through ``__init__`` (mocked instance),
                # in which case _pending_shadow_samples is absent —
                # skip persistence buffering rather than crash.
                if hasattr(self, "_pending_shadow_samples"):
                    self._pending_shadow_samples.append(sample)
        # Prune samples older than the window.
        window_cutoff = now - timedelta(
            days=OPTIMIZER_SHADOW_ACCURACY_WINDOW_DAYS,
        )
        kept: list = []
        for sample in self._shadow_accuracy_samples:
            # v5.11.0 D2 — supports both legacy (ts, matched) and new
            # (ts, dim, target, matched) shape after restore-from-DB
            # migrates old rows on first cycle.
            if isinstance(sample, tuple) and len(sample) == 4:
                ts_iso = sample[0]
            elif isinstance(sample, tuple) and len(sample) == 2:
                ts_iso = sample[0]
            else:
                continue
            try:
                ts = datetime.fromisoformat(ts_iso)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts >= window_cutoff:
                    kept.append(sample)
            except (ValueError, TypeError):
                continue
        # v5.11.0 D2 — hard cap on in-memory sample list.
        if len(kept) > OPTIMIZER_SHADOW_SAMPLE_MAX_ROWS:
            kept = kept[-OPTIMIZER_SHADOW_SAMPLE_MAX_ROWS:]
        self._shadow_accuracy_samples = kept
        total = len(self._shadow_accuracy_samples)
        if total < OPTIMIZER_SHADOW_ACCURACY_MIN_SAMPLES:
            self._last_shadow_accuracy_pct = None
            # B-MED-1: surface oracle-wired-but-inert via a distinct
            # token so a future regression of the B-HIGH-1 "phantom
            # surface" class is observable (sentinel-only is not
            # "warming up"). Heuristic: if every scorable finding this
            # cycle returned inconclusive AND we have at least one such
            # finding, the oracle is wired but reading nothing.
            if (
                scorable_evaluated > 0
                and scorable_inconclusive == scorable_evaluated
            ):
                self._last_shadow_accuracy_status = "no_observable_data"
            else:
                self._last_shadow_accuracy_status = "warming_up"
            return
        # v5.11.0 D2 — support both legacy 2-tuple and new 4-tuple shapes.
        matches = 0
        for s in self._shadow_accuracy_samples:
            if len(s) == 4 and s[3]:
                matches += 1
            elif len(s) == 2 and s[1]:
                matches += 1
        self._last_shadow_accuracy_pct = round(100.0 * matches / total, 1)
        self._last_shadow_accuracy_status = "ready"

    def _score_shadow_finding(
        self,
        finding: OptimizationFinding,
    ) -> tuple[bool | None, str]:
        """Per-dimension oracle for the shadow validator (D2d v1).

        Returns (match, evidence). `match=None` indicates an inconclusive
        observation (missing data); the caller still records
        observed_effect but does NOT count it toward the rolling %.
        """
        dim_str = str(finding.dimension)
        target_id = finding.target_id or ""
        # COMFORT: scored against room temperature movement toward target.
        # We have no historical-temp series here without a DB call, so
        # the v1 oracle is conservative: scored True iff a current
        # in-room temp sensor reads inside the comfort band, else False.
        # `match=None` when no sensor surface is readable.
        if dim_str == "comfort":
            return self._score_comfort_shadow(finding, target_id)
        if dim_str == "occupancy_accuracy":
            return self._score_occupancy_shadow(finding, target_id)
        return None, "unscorable"

    def _find_room_entry_by_target(self, target_id: str):
        """Resolve a finding's ``target_id`` back to the room ConfigEntry.

        Findings emitted by the Comfort / Occupancy evaluators set
        ``target_id = self._room_name(entry)`` (see ``_evaluate_comfort_dimension``
        / ``_evaluate_occupancy_accuracy_dimension``). Re-using the same
        ``_iter_room_entries`` + ``_room_name`` pair as the producers keeps
        the shadow oracle wired to the SAME production surface, not a
        fabricated room-coordinator dict.
        """
        if not target_id:
            return None
        try:
            for entry in self._iter_room_entries():
                if self._room_name(entry) == target_id:
                    return entry
        except Exception:  # noqa: BLE001
            return None
        return None

    def _score_comfort_shadow(
        self,
        finding: OptimizationFinding,
        target_id: str,
    ) -> tuple[bool | None, str]:
        """v1 COMFORT oracle: did the flagged out-of-band condition resolve?

        Coherent shadow semantics (P2-HIGH-1 fix-up pass 2):

        - The COMFORT producer fires the finding ONLY when the room temp
          left its PER-ROOM band ``_read_per_room_comfort(entry)`` (default
          [68,76] from const.py:888-889) and carries that band on the
          finding as ``payload["bounds"] = [min, max]``
          (see ``_evaluate_comfort_dimension`` ~:1602).
        - The oracle re-reads the room temperature later and reports:
            * ``True``  — temperature is back INSIDE the finding's own band
              (the flagged condition RESOLVED).
            * ``False`` — temperature is still OUTSIDE the finding's own
              band (the flagged condition PERSISTED).
            * ``None``  — inconclusive: missing/malformed bounds payload,
              missing/unreadable temp sensor, or no room entry. We do
              NOT fall back to a wider default band, because the previous
              hardcoded ``[65, 80]`` band strictly contained the producer
              band and turned every out-of-band finding into a "match"
              (degenerate near-always-True oracle).

        Drives the SAME reader the Comfort evaluator uses to emit the
        finding in the first place — ``_iter_room_entries`` → curated
        ``CONF_TEMPERATURE_SENSOR`` → ``_state_value``.
        """
        try:
            entry = self._find_room_entry_by_target(target_id)
            if entry is None:
                return None, "room_entry_missing"
            # Pull the producer's own band off the finding payload —
            # NOT a hardcoded fallback (would degenerate again).
            bounds = None
            try:
                payload = finding.payload or {}
                if isinstance(payload, dict):
                    bounds = payload.get("bounds")
            except Exception:  # noqa: BLE001
                bounds = None
            if (
                not isinstance(bounds, (list, tuple))
                or len(bounds) != 2
            ):
                return None, "no_bounds_in_payload"
            try:
                band_min = float(bounds[0])
                band_max = float(bounds[1])
            except (TypeError, ValueError):
                return None, "malformed_bounds_in_payload"
            if band_max <= band_min:
                return None, "malformed_bounds_in_payload"
            merged = {**(entry.data or {}), **(entry.options or {})}
            temp_eid = merged.get(CONF_TEMPERATURE_SENSOR)
            if not temp_eid:
                return None, "no_temperature_sensor_configured"
            st = self._state_value(temp_eid)
            if st is None:
                return None, "no_temperature_reading"
            try:
                temp = float(st.state)
            except (TypeError, ValueError):
                return None, "no_temperature_reading"
            in_band = band_min <= temp <= band_max
            if in_band:
                return True, (
                    f"temp={temp}_resolved_within_"
                    f"[{band_min},{band_max}]"
                )
            return False, (
                f"temp={temp}_persisted_outside_"
                f"[{band_min},{band_max}]"
            )
        except Exception:  # noqa: BLE001
            return None, "exception"

    def _score_occupancy_shadow(
        self,
        finding: OptimizationFinding,
        target_id: str,
    ) -> tuple[bool | None, str]:
        """v1 OCCUPANCY_ACCURACY oracle: did the flagged provenance
        disagreement resolve?

        Coherent shadow semantics (P2-MED-1 fix-up pass 2):

        - The OCCUPANCY_ACCURACY producer fires when motion/mmwave is ON
          but ALL curated occupancy sensors report OFF (a provenance
          disagreement claiming "someone is there but occupancy sensors
          don't see them"). It carries
          ``payload = {"occupancy_ids": [...], "signal_ids": [...]}``
          (see ``_evaluate_occupancy_accuracy_dimension`` ~:1796).
        - The oracle re-reads the SAME ids later and reports:
            * ``True``  — at least one occupancy sensor now reports ON
              (the claim matches reality / disagreement RESOLVED), OR
              the motion/mmwave signal has cleared (the trigger that
              raised the disagreement no longer holds).
            * ``False`` — motion/mmwave still ON AND every occupancy
              sensor still OFF (the same disagreement PERSISTED).
            * ``None``  — inconclusive: no payload ids, no room entry,
              or all sensors unavailable. The previous implementation
              returned True on ANY live read, which measured "sensors
              alive," not "claim resolved" — making False unreachable.

        Drives the SAME reader the occupancy-accuracy evaluator uses
        (``CONF_OCCUPANCY_SENSORS`` / ``CONF_MOTION_SENSORS`` /
        ``CONF_MMWAVE_SENSORS`` via ``_iter_room_entries`` +
        ``_state_value``).
        """
        try:
            # Prefer the ids the producer captured on the finding —
            # this scores the SAME claim that was raised, not whatever
            # the room is configured with now.
            payload = finding.payload if isinstance(
                finding.payload, dict
            ) else {}
            occ_ids: list[str] = []
            sig_ids: list[str] = []
            p_occ = payload.get("occupancy_ids")
            p_sig = payload.get("signal_ids")
            if isinstance(p_occ, list):
                occ_ids = [v for v in p_occ if isinstance(v, str)]
            if isinstance(p_sig, list):
                sig_ids = [v for v in p_sig if isinstance(v, str)]
            # Fall back to current room config when payload was thin
            # (older findings without the producer ids). Still drives
            # the production reader path.
            if not occ_ids or not sig_ids:
                entry = self._find_room_entry_by_target(target_id)
                if entry is None:
                    return None, "room_entry_missing"
                merged = {**(entry.data or {}), **(entry.options or {})}
                if not occ_ids:
                    val_occ = merged.get(CONF_OCCUPANCY_SENSORS)
                    if isinstance(val_occ, list):
                        occ_ids = [
                            v for v in val_occ if isinstance(v, str)
                        ]
                    elif isinstance(val_occ, str) and val_occ:
                        occ_ids = [val_occ]
                if not sig_ids:
                    for key in (CONF_MOTION_SENSORS, CONF_MMWAVE_SENSORS):
                        val = merged.get(key)
                        if isinstance(val, list):
                            sig_ids.extend(
                                [v for v in val if isinstance(v, str)]
                            )
                        elif isinstance(val, str) and val:
                            sig_ids.append(val)
            if not occ_ids:
                return None, "no_occupancy_sensors_configured"

            # Did occupancy now agree (any ON) → disagreement resolved.
            occ_any_on = False
            occ_any_reading = False
            for eid in occ_ids:
                st = self._state_value(eid)
                if st is None:
                    continue
                state_str = str(st.state).lower()
                if state_str in ("unavailable", "unknown", ""):
                    continue
                occ_any_reading = True
                if state_str in ("on", "true", "occupied"):
                    occ_any_on = True
                    break
            if not occ_any_reading:
                return None, "occupancy_unavailable"
            if occ_any_on:
                return True, "occupancy_now_on_disagreement_resolved"

            # Occupancy still all off — check whether the motion/mmwave
            # trigger that raised the finding is still firing.
            sig_any_on = False
            sig_any_reading = False
            for eid in sig_ids:
                st = self._state_value(eid)
                if st is None:
                    continue
                state_str = str(st.state).lower()
                if state_str in ("unavailable", "unknown", ""):
                    continue
                sig_any_reading = True
                if state_str in ("on", "true", "occupied"):
                    sig_any_on = True
                    break
            if not sig_any_reading:
                # Motion/mmwave gone → the trigger condition no longer
                # holds; treat as resolved (the disagreement is moot).
                return True, "signal_cleared_disagreement_moot"
            if not sig_any_on:
                return True, "signal_now_off_disagreement_moot"
            # Motion still on, occ still all off — disagreement persisted.
            return False, "motion_on_occupancy_off_persisted"
        except Exception:  # noqa: BLE001
            return None, "exception"

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

        A4 fix-up: CM is authoritative. The legacy
        ``hass.data[DOMAIN]["hvac_coordinator"]`` slot is gated behind the
        ``_optimizer_test_mode`` flag so production cannot read a stale
        injection that would win over the CM-managed coordinator.
        """
        try:
            domain_data = self.hass.data.get(DOMAIN, {}) or {}
            cm = domain_data.get("coordinator_manager")
            if cm is not None:
                coords = getattr(cm, "coordinators", None) or {}
                hvac = coords.get("hvac")
                if hvac is not None:
                    return hvac
            if domain_data.get("_optimizer_test_mode"):
                return domain_data.get("hvac_coordinator")
            return None
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
                # Disagreement cleared — drop the sustained-since stamp.
                self._occ_accuracy_disagreement_since.pop(room, None)
                continue
            # A6 fix-up: motion-on/occupancy-off is transient at sensor wake.
            # Require the disagreement to persist for at least
            # OPTIMIZER_OCCUPANCY_ACCURACY_GATE_SECONDS before emitting.
            since = self._occ_accuracy_disagreement_since.get(room)
            if since is None:
                self._occ_accuracy_disagreement_since[room] = now
                continue
            try:
                if (now - since).total_seconds() < (
                    OPTIMIZER_OCCUPANCY_ACCURACY_GATE_SECONDS
                ):
                    continue
            except Exception:  # noqa: BLE001
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
                # A3 fix-up: normalize TZ for comparison. A naive
                # ``continuous_occupied_since`` is from HA's local clock —
                # promote it via ``as_local`` → ``as_utc`` instead of
                # mislabelling a naive value as UTC (which would shift the
                # hours-since computation by the local UTC offset).
                cs = cont_since
                if cs.tzinfo is None:
                    cs = dt_util.as_utc(dt_util.as_local(cs))
                if now.tzinfo is None:
                    # Defensive: dt_util.utcnow() is aware; only strip when
                    # both sides are naive to keep arithmetic well-defined.
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
    # v5.3.0 Phase 4 — Prediction-Validation pillar (READ-ONLY).
    # ------------------------------------------------------------------

    def _get_bayesian_predictor(self):
        """Return the shared BayesianPredictor instance, or None.

        Substrate: ``hass.data[DOMAIN]["bayesian_predictor"]`` — wired in
        ``__init__.py:1199`` after CM setup; consumed by the next-room +
        bayesian-accuracy sensors (e.g. sensor.py:10994).
        """
        try:
            return self.hass.data.get(DOMAIN, {}).get("bayesian_predictor")
        except Exception:  # noqa: BLE001
            return None

    async def _read_next_room_accuracy(
        self, days: int,
    ) -> dict | None:
        """Read aggregate next-room top-1 hit-rate + Brier over the window.

        Mirrors HouseNextRoomAccuracySensor (sensor.py:11278) but reads the
        same ``prediction_results`` table directly via the shared
        ``UniversalRoomDatabase`` so we do NOT depend on the sensor entity
        being loaded (avoid circular entity reads). Read-only: a single
        SELECT, no writes.

        Returns ``{top1_hit_rate, brier_score, total_predictions}`` or None
        when the DB is unavailable / table empty.
        """
        try:
            database = self.hass.data.get(DOMAIN, {}).get("database")
            if database is None:
                return None
            cutoff = (
                dt_util.utcnow() - timedelta(days=days)
            ).strftime("%Y-%m-%d %H:%M:%S")
            import json as _json
            try:
                import aiosqlite as _aiosqlite
            except Exception:  # noqa: BLE001 — tests stub aiosqlite
                _aiosqlite = None
            async with database._db_read() as db:
                if _aiosqlite is not None:
                    try:
                        db.row_factory = _aiosqlite.Row
                    except Exception:  # noqa: BLE001
                        pass
                cursor = await db.execute(
                    """SELECT predicted_value, actual_value, error_value
                       FROM prediction_results
                       WHERE prediction_type = 'next_room'
                         AND prediction_timestamp >= ?""",
                    (cutoff,),
                )
                rows = await cursor.fetchall()
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug(
                "prediction_accuracy: next-room read failed (%s); "
                "treating as no data", exc,
            )
            return None
        if not rows:
            return {
                "top1_hit_rate": None,
                "brier_score": None,
                "total_predictions": 0,
            }
        total = 0
        hits = 0
        brier_sum = 0.0
        brier_n = 0
        for r in rows:
            total += 1
            # Row may be aiosqlite.Row (mapping) or a plain tuple under
            # the test stub — handle both.
            try:
                pv = r["predicted_value"]
                av = r["actual_value"]
                ev = r["error_value"]
            except (TypeError, KeyError, IndexError):
                try:
                    pv, av, ev = r[0], r[1], r[2]
                except Exception:  # noqa: BLE001
                    continue
            try:
                pred = _json.loads(pv) if isinstance(pv, str) else (pv or {})
                top = pred.get("top") if isinstance(pred, dict) else None
            except (TypeError, ValueError):
                top = None
            if top is not None and top == av:
                hits += 1
            if ev is not None:
                try:
                    brier_sum += float(ev)
                    brier_n += 1
                except (TypeError, ValueError):
                    pass
        return {
            "top1_hit_rate": (
                round(hits / total * 100, 1) if total else None
            ),
            "brier_score": (
                round(brier_sum / brier_n, 4) if brier_n else None
            ),
            "total_predictions": total,
        }

    async def _evaluate_prediction_accuracy_dimension(
        self,
    ) -> list[OptimizationFinding]:
        """House: READ-ONLY accuracy reader; flag DEGRADED prediction quality.

        Phase 4 of the Optimization Coordinator. Strictly reads existing
        Bayesian accuracy surfaces — no new learner, no reimplemented math:

        - ``BayesianPredictor.get_accuracy_stats(days)`` —
          bayesian_predictor.py:901. Returns brier_score / hit_rate /
          total_predictions for the ``bayesian_occupancy`` surface. May be
          empty/None (provisional surface per audit) — handled gracefully.
        - ``BayesianPredictor.is_learning_suppressed`` —
          bayesian_predictor.py:783. When True, do NOT flag drift
          (guest-mode suppression intentionally pauses learning).
        - ``BayesianPredictor.quality_report`` — bayesian_predictor.py:763.
          ``DataQualityReport.passed / total_rows`` is the data-quality %.
        - ``prediction_results`` table (read directly via the shared DB) —
          mirrors HouseNextRoomAccuracySensor (sensor.py:11278) for the
          next-room top1/Brier aggregate.

        Findings are HOUSE-level only (not per-room) — the accuracy data
        is house/person-level by construction; emitting per-room here
        would inflate the cycle's row count for no signal.

        Confidence is discounted by data volume + a learning-suppressed
        guard, so under-learned or paused-learner cells produce at most
        low-confidence advisories — never a drift alarm.

        # DailyEnergyPredictor deferred: there is no clean in-process
        # accuracy surface for it today (the energy_forecast coordinator
        # tracks point forecasts but does NOT expose hit-rate / Brier of
        # the kind this dimension reads). Re-evaluate when an accuracy
        # ring is added there. Do NOT fabricate one here.
        """
        findings: list[OptimizationFinding] = []
        now = dt_util.utcnow()
        predictor = self._get_bayesian_predictor()
        # When the predictor isn't initialized, there is nothing to read.
        # Stay silent — no fabrication.
        if predictor is None:
            return findings

        # Suppressed-learning gate. Guest mode (or any explicit suppression)
        # intentionally pauses belief updates; flagging "accuracy drift"
        # there would be a false alarm.
        suppressed = False
        try:
            suppressed = bool(predictor.is_learning_suppressed)
        except Exception:  # noqa: BLE001
            suppressed = False
        if suppressed:
            return findings

        # --- Surface 1: next-room top-1 hit-rate + Brier (the SAFE,
        # primary substrate per the audit). House-aggregate readout
        # mirrors HouseNextRoomAccuracySensor.
        next_room: dict | None = None
        try:
            next_room = await self._read_next_room_accuracy(
                days=OPTIMIZER_PREDICTION_ACCURACY_WINDOW_DAYS,
            )
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug(
                "prediction_accuracy: next-room surface unavailable (%s)",
                exc,
            )

        # --- Surface 2: BayesianPredictor.get_accuracy_stats — the
        # PROVISIONAL bayesian-occupancy surface per the audit. Treat
        # as possibly-empty (None/0 predictions); never flag drift off
        # missing data.
        occ_stats: dict | None = None
        try:
            occ_stats = await predictor.get_accuracy_stats(
                days=OPTIMIZER_PREDICTION_ACCURACY_WINDOW_DAYS,
            ) or None
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug(
                "prediction_accuracy: get_accuracy_stats failed (%s)", exc,
            )

        # --- Surface 3: DataQualityReport via predictor.quality_report.
        data_quality_pct: float | None = None
        try:
            report = predictor.quality_report
            if report is not None and getattr(report, "total_rows", 0):
                data_quality_pct = round(
                    report.passed / report.total_rows * 100.0, 1
                )
        except Exception:  # noqa: BLE001
            data_quality_pct = None

        issues: list[str] = []
        payload: dict[str, Any] = {}

        # Determine total sample volume for confidence/staleness gating.
        # The bigger of (next-room total, occupancy total) is what backs
        # the dimension's confidence below.
        next_total = int(
            (next_room or {}).get("total_predictions") or 0
        )
        occ_total = int(
            (occ_stats or {}).get("total_predictions") or 0
        )
        max_total = max(next_total, occ_total)

        # Under-learned gate: if NEITHER surface has hit the min-sample
        # threshold, treat the prediction system as still warming up —
        # do NOT emit a degradation finding. (The audit flagged this
        # exact false-alarm risk during the boot warm-up window.)
        under_learned = max_total < OPTIMIZER_PREDICTION_ACCURACY_MIN_SAMPLES

        # Next-room top1 hit-rate degradation.
        nr_top1 = (
            (next_room or {}).get("top1_hit_rate") if next_room else None
        )
        if (
            not under_learned
            and next_total >= OPTIMIZER_PREDICTION_ACCURACY_MIN_SAMPLES
            and nr_top1 is not None
            and nr_top1 < OPTIMIZER_PREDICTION_ACCURACY_TOP1_FLOOR_PCT
        ):
            issues.append(
                f"next-room top-1 hit-rate "
                f"{nr_top1:.1f}% < floor "
                f"{OPTIMIZER_PREDICTION_ACCURACY_TOP1_FLOOR_PCT:.1f}%"
            )
            payload["next_room_top1_hit_rate"] = nr_top1
            payload["next_room_total_predictions"] = next_total

        # Bayesian-occupancy Brier degradation (provisional surface).
        occ_brier = (
            (occ_stats or {}).get("brier_score") if occ_stats else None
        )
        if (
            not under_learned
            and occ_total >= OPTIMIZER_PREDICTION_ACCURACY_MIN_SAMPLES
            and occ_brier is not None
            and occ_brier > OPTIMIZER_PREDICTION_ACCURACY_BRIER_CEILING
        ):
            issues.append(
                f"bayesian-occupancy Brier {occ_brier:.3f} > ceiling "
                f"{OPTIMIZER_PREDICTION_ACCURACY_BRIER_CEILING:.3f}"
            )
            payload["bayesian_occupancy_brier"] = occ_brier
            payload["bayesian_occupancy_total_predictions"] = occ_total

        # Data-quality degradation (independent of sample volume — the
        # quality report is computed at initialize() time).
        if (
            data_quality_pct is not None
            and data_quality_pct
            < OPTIMIZER_PREDICTION_ACCURACY_DATA_QUALITY_FLOOR_PCT
        ):
            issues.append(
                f"data_quality_pct {data_quality_pct:.1f}% < floor "
                f"{OPTIMIZER_PREDICTION_ACCURACY_DATA_QUALITY_FLOOR_PCT:.1f}%"
            )
            payload["data_quality_pct"] = data_quality_pct

        if not issues:
            return findings

        # Confidence derived from sample volume: hit min-samples = 0.6;
        # 4x min-samples = 0.85 (cap). Discount further when we're
        # leaning on the provisional occupancy surface only.
        if max_total >= OPTIMIZER_PREDICTION_ACCURACY_MIN_SAMPLES * 4:
            confidence = 0.85
        elif max_total >= OPTIMIZER_PREDICTION_ACCURACY_MIN_SAMPLES * 2:
            confidence = 0.75
        elif max_total >= OPTIMIZER_PREDICTION_ACCURACY_MIN_SAMPLES:
            confidence = 0.6
        else:
            # Only the data-quality issue fired (volume-independent). The
            # signal IS real but we have low evidence about prediction
            # behavior itself — keep the advisory low-confidence.
            confidence = 0.5

        dedup_key = ("prediction_accuracy", "house")
        if dedup_key in self._cycle_dedup:
            return findings
        self._cycle_dedup.add(dedup_key)
        findings.append(OptimizationFinding(
            timestamp=now.isoformat(),
            level="house",
            target_id="house",
            dimension=OptimizationDimension.PREDICTION_ACCURACY,
            severity="low",
            confidence=confidence,
            score=0.0,
            description=(
                "Prediction quality degraded: " + "; ".join(issues)
            ),
            # Phase 4 is READ-ONLY: advisory finding, no proposed action.
            proposed_action=None,
            payload=payload,
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

        # A-C1 / C-C1 fix-up: ALWAYS call await_veto so synchronously-
        # delivered sibling vetoes (broker dispatched the intent on this
        # event-loop turn — siblings ran their callback and pushed into
        # _pending_vetoes before the dispatch returned) are observed.
        # The zero-window branch of await_veto is a synchronous _take()
        # against _pending_vetoes — no sleep, no I/O — so the L2
        # propose_config==False path keeps its no-delay character.
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

        # A-C1 / C-C1 fix-up: ALWAYS call await_veto so synchronously-
        # delivered sibling vetoes are observed (see _dispatch_device_action
        # for the full rationale). Zero-window path is a synchronous _take.
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
            # v5.2.2 fix-up — buffer instead of per-finding write. With
            # 35 Sensor-Health findings in a boot-storm cycle, the OLD
            # ``_log_activity`` call here flooded ura_activity_log with
            # 35 INSERTs + 35 SIGNAL_ACTIVITY_LOGGED dispatches per
            # cycle (the SECOND write-flood channel adversarial review
            # caught). The end-of-cycle summary row preserves
            # observability at O(1) cost.
            self._cycle_clamp_log_buffer.append({
                "description": finding.description,
                "dimension": str(finding.dimension),
                "target_id": finding.target_id,
                "level_kind": finding.level,
                "confidence": conf,
                "gate": gate,
            })
            return

        if not finding.proposed_action:
            level = self.effective_level
            if level == OPTIMIZER_LEVEL_SHADOW:
                finding.applied_outcome = OPTIMIZER_OUTCOME_SHADOW
                finding.predicted_effect = {
                    "note": "shadow_dry_run — no proposed action emitted",
                }
                # v5.2.2 fix-up — buffer instead of per-finding write
                # (see comment in below-gate branch above).
                self._cycle_shadow_log_buffer.append({
                    "description": finding.description,
                    "dimension": str(finding.dimension),
                    "target_id": finding.target_id,
                    "level_kind": finding.level,
                    "level": level,
                })
            else:
                finding.applied_outcome = OPTIMIZER_OUTCOME_ADVISORY_ONLY
            return
        await self._apply_action(finding, finding.proposed_action)

    # ------------------------------------------------------------------
    # Persistence + signals + NM
    # ------------------------------------------------------------------

    async def _persist_finding(self, finding: OptimizationFinding) -> None:
        """Legacy per-finding persist — kept for back-compat callers.

        v5.2.2: the cycle path no longer calls this. The cycle uses
        ``_persist_findings_batch`` to bound per-cycle DB writes to 1
        per tier (post-mortem fix for the write-queue saturation
        incident). New callers should prefer the batch variant.

        v5.11.0 F1 (fix-up): even though there is no live caller (Review
        D confirmed), gate on the D9 tripwire defensively so a future
        caller cannot silently reintroduce the write-flood pattern.
        """
        if self._check_write_volume_tripwire():
            return
        database = self.hass.data.get(DOMAIN, {}).get("database")
        if database is None:
            return
        try:
            await database.log_finding(finding)
            # v5.11.0 F1: count this OC-attributed write.
            self._record_db_write()
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug("log_finding failed: %s", exc, exc_info=True)

    # ------------------------------------------------------------------
    # v5.11.0 D1 — Notify-dedup TTL per-cycle decrement (MED-3 fix)
    # ------------------------------------------------------------------

    def _decrement_notify_dedup_ttls(self) -> None:
        """v5.11.0 D1 — decrement all notify-dedup TTLs exactly once
        per cycle. Called at the end of ``_run_cycle_body``.

        Fixes MED-3: previously the decrement ran per-finding inside
        ``_notify_if_severe``, so a cycle with 10 HIGH findings
        decremented ALL keys 10x — collapsing the intended 12-cycle
        (1h) dedup window to ~1.2 cycles.

        v5.11.0 F-MED (A-MED-1 fix-up): keys set DURING the current
        cycle must NOT be decremented that same cycle — otherwise a
        freshly-recorded key burns 1 of its 12 cycles on the very
        cycle it was recorded, delivering an effective 11-cycle window
        instead of the intended 12. The set is populated by
        ``_notify_if_severe`` when it records a new dedup entry and
        cleared at the end of this helper.
        """
        just_set = getattr(self, "_notify_dedup_just_set", None) or set()
        if self._notify_dedup_state:
            stale: list[str] = []
            for k in list(self._notify_dedup_state.keys()):
                if k in just_set:
                    # Recorded this cycle → do not decrement yet.
                    continue
                self._notify_dedup_state[k] -= 1
                if self._notify_dedup_state[k] <= 0:
                    stale.append(k)
            for k in stale:
                self._notify_dedup_state.pop(k, None)
        # Clear the just-set marker at end-of-cycle so the NEXT cycle's
        # decrement covers these keys normally.
        if just_set:
            just_set.clear()

    # ------------------------------------------------------------------
    # v5.11.0 D9 — Write-volume tripwire
    # ------------------------------------------------------------------

    def _record_db_write(self) -> None:
        """v5.11.0 D9 — record one OC-attributed DB write.

        Cheap: append current time, evict entries older than the rolling
        window. No DB writes of its own — pure in-memory bookkeeping.
        """
        now = dt_util.utcnow()
        self._db_write_timestamps.append(now)
        cutoff = now - timedelta(seconds=OPTIMIZER_WRITE_VOLUME_WINDOW_SECONDS)
        while (self._db_write_timestamps
               and self._db_write_timestamps[0] < cutoff):
            self._db_write_timestamps.popleft()

    def _check_write_volume_tripwire(self) -> bool:
        """v5.11.0 D9 — check + maybe trip.

        Returns True iff the tripwire is currently tripped (persistence
        should be suspended). First trip fires ONE NM anomaly + sets
        ``_write_volume_alarmed_at``. Idempotent: subsequent checks
        while tripped do NOT re-page.
        """
        count = len(self._db_write_timestamps)
        if count <= OPTIMIZER_WRITE_VOLUME_THRESHOLD:
            return False
        if self._persistence_suspended:
            return True
        # First trip: page once, then latch.
        # v5.11.0 F-LOW (A-LOW-2 fix-up): recovery is HA RESTART. There
        # is intentionally NO auto-unlatch (a rolling-window auto-clear
        # would silently mask the very regression this trip-wire exists
        # to surface) and NO kill-switch clear helper (the operator's
        # explicit restart doubles as the postmortem trigger).
        self._persistence_suspended = True
        self._write_volume_alarmed_at = dt_util.utcnow().isoformat()
        _LOGGER.error(
            "Optimizer write-volume tripwire FIRED: %d OC-attributed DB "
            "writes in the last %ds (threshold=%d). Persistence "
            "SUSPENDED; evaluation continues.",
            count, OPTIMIZER_WRITE_VOLUME_WINDOW_SECONDS,
            OPTIMIZER_WRITE_VOLUME_THRESHOLD,
        )
        # Fire single NM anomaly if NM present.
        nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
        if nm is not None:
            try:
                # Fire-and-forget so tripwire never blocks the cycle.
                self.hass.async_create_task(nm.async_notify(
                    coordinator_id="optimization",
                    severity=Severity.CRITICAL,
                    title="URA Optimizer — write-volume tripwire",
                    message=(
                        f"OC persistence suspended: {count} DB writes in "
                        f"{OPTIMIZER_WRITE_VOLUME_WINDOW_SECONDS}s "
                        f"(threshold={OPTIMIZER_WRITE_VOLUME_THRESHOLD}). "
                        "Regression suspected — see logs."
                    ),
                    hazard_type=None,
                    location="house",
                ))
            except Exception:  # noqa: BLE001
                _LOGGER.debug("tripwire NM fire failed", exc_info=True)
        return True

    async def _persist_findings_batch(
        self, findings: list[OptimizationFinding],
    ) -> None:
        """v5.2.2 — single-write-queue-roundtrip persist for the cycle.

        Wraps ``database.log_findings_batch`` with the same defensive
        try/except shape as ``_persist_finding``. An empty list is a
        no-op (no DB acquisition). One ``_db()`` round-trip regardless
        of finding count — this is the core fix for the v5.2.1 write
        queue saturation that took the live house down.

        v5.11.0 D9: gated by the write-volume tripwire. If persistence
        has been suspended, the call is a no-op (evaluation still runs).
        """
        if not findings:
            return
        if self._check_write_volume_tripwire():
            _LOGGER.info(
                "Optimizer: persistence suspended by tripwire; "
                "dropping batch of %d findings (evaluation continues)",
                len(findings),
            )
            return
        database = self.hass.data.get(DOMAIN, {}).get("database")
        if database is None:
            return
        try:
            written = await database.log_findings_batch(findings)
            # v5.11.0 D9 — one DAO call = one OC-attributed DB write.
            self._record_db_write()
            if written:
                _LOGGER.debug(
                    "Optimizer: batched %d findings into one DB write",
                    written,
                )
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug("log_findings_batch failed: %s", exc, exc_info=True)

    async def _persist_shadow_samples_batch(self) -> None:
        """v5.11.0 D2 — persist buffered shadow-accuracy samples.

        Batched: one DAO call per cycle regardless of sample count.
        Never per-sample (that would recreate the write-flood pattern).
        Gated by the D9 tripwire.
        """
        if not self._pending_shadow_samples:
            return
        if self._check_write_volume_tripwire():
            self._pending_shadow_samples.clear()
            return
        database = self.hass.data.get(DOMAIN, {}).get("database")
        if database is None or not hasattr(database, "log_shadow_samples_batch"):
            self._pending_shadow_samples.clear()
            return
        rows = list(self._pending_shadow_samples)
        self._pending_shadow_samples.clear()
        try:
            await database.log_shadow_samples_batch(rows)
            # v5.11.0 D9 — one DAO call = one OC-attributed DB write.
            self._record_db_write()
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug(
                "log_shadow_samples_batch failed: %s", exc, exc_info=True,
            )

    def _compute_promotion_readiness(self) -> dict[str, dict]:
        """v5.11.0 D6 — per-dimension L1→L2 promotion readiness.

        Returns ``{dimension: {ready: bool, blocked_by: [reasons],
        evidence: {samples: int, accuracy: float|None}}}``.

        Blocker reasons (canonical, per critique spec):
          - samples_below_min
          - accuracy_below_threshold
          - stub_oracle
          - kill_switch_engaged
          - dimension_autonomy_below_L2
          - shadow_accuracy_not_ready

        Only computed for the two scorable dimensions (comfort +
        occupancy_accuracy) plus surfaces `not_run` for stub dims.
        Rides on D2's persisted samples and D5's stub filter.
        """
        result: dict[str, dict] = {}
        try:
            cfg = self._read_cm_config()
        except Exception:  # noqa: BLE001
            cfg = {}
        kill_switch = bool(cfg.get(CONF_OPTIMIZER_KILL_SWITCH, False))
        # Effective per-dimension cap
        dim_map = cfg.get(CONF_OPTIMIZER_DIMENSION_AUTONOMY) or {}
        # Only scorable v1 dimensions have promotion readiness.
        scorable_dims = (
            OPTIMIZER_DIMENSION_COMFORT,
            OPTIMIZER_DIMENSION_OCCUPANCY_ACCURACY,
        )
        # Bucket samples by dimension. Supports both new 4-tuple shape
        # (ts, dim, target, matched) and legacy 2-tuple (ts, matched).
        # Legacy samples are unattributed → they do NOT contribute to any
        # dimension's count (conservative: forces re-warm-up post-upgrade).
        by_dim_total: dict[str, int] = {}
        by_dim_matches: dict[str, int] = {}
        # v5.11.0 F-MED (D-clause-4 fix-up): also track sample-time span
        # per dimension so a burst of 20+ samples in a single hour
        # cannot clear the ``shadow_accuracy_not_ready`` blocker — the
        # critique-spec requires the window itself (7 days) to have
        # elapsed, not just the sample count to be met.
        by_dim_min_ts: dict[str, datetime | None] = {}
        by_dim_max_ts: dict[str, datetime | None] = {}
        for s in self._shadow_accuracy_samples:
            if isinstance(s, tuple) and len(s) == 4:
                _ts, dim, _tgt, matched = s
                by_dim_total[dim] = by_dim_total.get(dim, 0) + 1
                if matched:
                    by_dim_matches[dim] = by_dim_matches.get(dim, 0) + 1
                # Parse timestamp defensively.
                try:
                    _parsed = datetime.fromisoformat(str(_ts))
                    cur_min = by_dim_min_ts.get(dim)
                    cur_max = by_dim_max_ts.get(dim)
                    if cur_min is None or _parsed < cur_min:
                        by_dim_min_ts[dim] = _parsed
                    if cur_max is None or _parsed > cur_max:
                        by_dim_max_ts[dim] = _parsed
                except (ValueError, TypeError):
                    continue
        for dim in scorable_dims:
            blockers: list[str] = []
            total = by_dim_total.get(dim, 0)
            matches = by_dim_matches.get(dim, 0)
            accuracy = (matches / total) if total > 0 else None
            # v5.11.0 F-LOW (C-LOW-1 fix-up): defensive only — the two
            # scorable_dims (COMFORT, OCCUPANCY_ACCURACY) are disjoint
            # from OPTIMIZER_STUB_DIMENSIONS in v5.11.0, so this branch
            # is unreachable at present. Kept so that if a future
            # dimension is BOTH declared scorable AND marked stub during
            # a transition, promotion is blocked correctly.
            if dim in OPTIMIZER_STUB_DIMENSIONS:
                blockers.append("stub_oracle")
            if kill_switch:
                blockers.append("kill_switch_engaged")
            # Dimension autonomy cap: strings.
            per_dim_cap = dim_map.get(dim)
            if per_dim_cap is not None:
                cap_rank = OPTIMIZER_LEVEL_RANK.get(per_dim_cap, 0)
                if cap_rank < OPTIMIZER_LEVEL_RANK.get(
                    OPTIMIZER_LEVEL_REVERSIBLE_DEVICE, 2
                ):
                    blockers.append("dimension_autonomy_below_L2")
            if total < OPTIMIZER_PROMOTION_READINESS_MIN_SAMPLES:
                blockers.append("samples_below_min")
            elif accuracy is not None and (
                accuracy < OPTIMIZER_PROMOTION_READINESS_ACCURACY_FLOOR
            ):
                blockers.append("accuracy_below_threshold")
            # v5.11.0 F-MED (D-clause-4 fix-up): critique-spec'd
            # ``window_incomplete`` blocker. Require the sample-time
            # SPAN to cover OPTIMIZER_SHADOW_ACCURACY_WINDOW_DAYS —
            # 20 samples in a single hour must NOT clear
            # ``shadow_accuracy_not_ready``. Only enforced when we
            # have both endpoints (else samples_below_min already
            # covers the empty case).
            _min_ts = by_dim_min_ts.get(dim)
            _max_ts = by_dim_max_ts.get(dim)
            if _min_ts is not None and _max_ts is not None:
                _span = _max_ts - _min_ts
                if _span < timedelta(
                    days=OPTIMIZER_SHADOW_ACCURACY_WINDOW_DAYS,
                ):
                    blockers.append("window_incomplete")
            if self._last_shadow_accuracy_status != "ready":
                blockers.append("shadow_accuracy_not_ready")
            result[dim] = {
                "ready": not blockers,
                "blocked_by": blockers,
                "evidence": {
                    "samples": total,
                    "accuracy": (
                        round(accuracy, 3) if accuracy is not None else None
                    ),
                },
            }
        return result

    def _dispatch_finding_signal(self, finding: OptimizationFinding) -> None:
        """Legacy per-finding signal dispatch — kept for back-compat.

        v5.2.2: the cycle path no longer calls this. Per-finding
        dispatch caused websocket "4096 pending messages" backpressure
        when Sensor-Health emitted 35+ rows during the boot storm.
        The cycle now fires ``_dispatch_findings_updated_signal`` ONCE
        after persistence — the per-room / optimizer sensors all
        re-read coordinator state, ignoring payload (sensor.py:13637,
        13858). New callers should prefer the once-per-cycle variant.
        """
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

    def _dispatch_findings_updated_signal(self) -> None:
        """v5.2.2 — ONE per-cycle dispatch after persistence completes.

        The signal name is preserved so existing
        SIGNAL_OPTIMIZER_FINDING_EMITTED subscriptions in sensor.py
        still fire. Payload is a tiny "cycle complete" marker — all
        sensor subscribers (sensor.py:13637, 13858) discard the
        payload and re-read coordinator state via
        ``async_write_ha_state()``, so one fire refreshes them all.
        """
        try:
            async_dispatcher_send(
                self.hass,
                SIGNAL_OPTIMIZER_FINDING_EMITTED,
                {"cycle_complete": True,
                 "timestamp": dt_util.utcnow().isoformat()},
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "findings-updated signal dispatch failed", exc_info=True,
            )

    def _cap_findings(
        self, findings: list[OptimizationFinding],
    ) -> list[OptimizationFinding]:
        """v5.2.2 — belt-and-suspenders cap on per-cycle findings.

        Defends against a pathological dimension flooding the write
        queue. When the list exceeds ``OPTIMIZER_MAX_FINDINGS_PER_CYCLE``,
        keep the highest-severity rows and truncate the rest with a
        WARNING. The META sentinel is always preserved so the cycle's
        liveness diagnostic stays trustworthy.
        """
        if len(findings) <= OPTIMIZER_MAX_FINDINGS_PER_CYCLE:
            return findings
        sev_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        # Preserve META rows separately — they bypass the cap.
        meta = [f for f in findings
                if f.dimension == OptimizationDimension.META]
        non_meta = [f for f in findings
                    if f.dimension != OptimizationDimension.META]
        non_meta.sort(key=lambda f: sev_rank.get(str(f.severity), 99))
        # Reserve space for the META rows so the total stays under the cap.
        keep = OPTIMIZER_MAX_FINDINGS_PER_CYCLE - len(meta)
        if keep < 0:
            keep = 0
        capped = non_meta[:keep] + meta
        _LOGGER.warning(
            "Optimizer cycle produced %d findings (cap=%d) — truncated "
            "to %d highest-severity rows + %d META; %d rows dropped to "
            "protect the DB write queue",
            len(findings), OPTIMIZER_MAX_FINDINGS_PER_CYCLE,
            len(capped) - len(meta), len(meta),
            len(non_meta) - keep,
        )
        return capped

    def _should_skip_for_boot_storm(
        self, findings: list[OptimizationFinding],
    ) -> tuple[bool, str]:
        """v5.2.2 — boot-storm settle gate.

        Returns ``(skip, reason)``. When True, the cycle persists ONLY
        the META sentinel and skips signal dispatch — protecting the
        DB write queue from the cold-boot unavailable-sensor sweep
        that triggered the v5.2.1 incident.

        Triggers:
        1. ``self._cycles_since_start < OPTIMIZER_BOOT_SETTLE_CYCLES``
           (uptime grace — first N cycles).
        2. The fraction of rooms with at least one currently
           ``unavailable`` / ``unknown`` configured sensor exceeds
           ``OPTIMIZER_BOOT_STORM_ROOM_FRACTION`` (boot-storm
           signature).
        """
        if self._cycles_since_start < OPTIMIZER_BOOT_SETTLE_CYCLES:
            return (True, f"uptime_grace "
                    f"(cycle {self._cycles_since_start + 1}/"
                    f"{OPTIMIZER_BOOT_SETTLE_CYCLES})")
        # v5.11.0 D4 (MED-1 fix): boot-storm cache — once we've verified
        # "no boot-storm" once, cache the negative verdict for K cycles
        # so the ~150 state reads per steady-state 30-room cycle stop.
        if self._boot_storm_cache_cycles_remaining > 0:
            self._boot_storm_cache_cycles_remaining -= 1
            return (False, "")
        try:
            total_rooms = 0
            rooms_with_unavailable = 0
            for entry in self._iter_room_entries():
                total_rooms += 1
                merged = {**(entry.data or {}), **(entry.options or {})}
                tracked: list[str] = []
                for key in (CONF_TEMPERATURE_SENSOR, CONF_HUMIDITY_SENSOR,
                            CONF_OCCUPANCY_SENSORS, CONF_MOTION_SENSORS,
                            CONF_MMWAVE_SENSORS):
                    val = merged.get(key)
                    if isinstance(val, list):
                        tracked.extend([v for v in val if isinstance(v, str)])
                    elif isinstance(val, str) and val:
                        tracked.append(val)
                room_has_unavail = False
                for eid in tracked:
                    st = self._state_value(eid)
                    state_str = "" if st is None else str(st.state).lower()
                    if st is None or state_str in ("unavailable", "unknown"):
                        room_has_unavail = True
                        break
                if room_has_unavail:
                    rooms_with_unavailable += 1
                # v5.11.0 F3 (fix-up): the previous in-loop fraction test
                # (running_partial_count / running_partial_total) was
                # broken — one flaky room sorting first produced 1/1 >
                # 0.5, tripping the gate every cycle AND preventing the
                # negative cache from arming. Full-fleet fraction test
                # runs ONCE below after the walk completes. The cache
                # (F3 rider on MED-1) delivers the perf win the
                # short-circuit was meant to; the D9 write-volume
                # tripwire (see F1) is the designated backstop for
                # non-boot mass-unavailability inside the cache TTL.
            # Post-loop full-fleet fraction test.
            if total_rooms > 0:
                _frac = rooms_with_unavailable / total_rooms
                if _frac > OPTIMIZER_BOOT_STORM_ROOM_FRACTION:
                    return (True, (
                        f"boot_storm_signature "
                        f"({rooms_with_unavailable}/{total_rooms} rooms "
                        f"have unavailable sensors, "
                        f"frac={_frac:.2f} > "
                        f"{OPTIMIZER_BOOT_STORM_ROOM_FRACTION:.2f})"
                    ))
            # v5.11.0 D4 — cache the negative verdict for K cycles.
            # NOTE (F3): while the cache is warm the gate is BLIND to a
            # non-boot mass-unavailability spike for up to
            # OPTIMIZER_BOOT_STORM_CACHE_CYCLES cycles. The D9 write-
            # volume tripwire (now complete per F1 — activity_log +
            # digest counted) is the designated backstop for that shape.
            self._boot_storm_cache_cycles_remaining = (
                OPTIMIZER_BOOT_STORM_CACHE_CYCLES
            )
            self._boot_storm_cache_expires_iso = (
                dt_util.utcnow()
                + SCAN_INTERVAL_OPTIMIZATION * OPTIMIZER_BOOT_STORM_CACHE_CYCLES
            ).isoformat()
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug(
                "boot-storm gate check failed; proceeding with cycle: %s",
                exc, exc_info=True,
            )
        return (False, "")

    async def _notify_if_severe(self, finding: OptimizationFinding) -> None:
        if finding.severity not in ("critical", "high"):
            return
        # NM Cycle A (2026-07-20) A2: HIGH findings route to the daily
        # digest by default; only allowlisted dimensions still page NM.
        # CRITICAL always pages. Digest wiring already lives in NM via
        # `_build_optimizer_digest_section` → `opt.format_digest_section()`.
        # NM Cycle A-2 fix-up (C-HIGH-2 / C-HIGH-3, 2026-07-20): defer
        # gate extracted into ``_nm_cycle_a.should_defer_high_to_digest``
        # for mutation-anchored behavioral testing. Semantics are
        # byte-identical: HIGH findings whose dimension isn't in the
        # CM-options allowlist defer to digest; CRITICAL always pages.
        # Read-side normalization (case + Enum-value unwrap) also lives
        # in the helper so a persisted lowercase allowlist matches an
        # Enum-valued finding.dimension. See CONF_OPTIMIZER_NM_HIGH_ALLOWLIST_DIMENSIONS.
        from ._nm_cycle_a import should_defer_high_to_digest
        if should_defer_high_to_digest(self.hass, finding):
            _LOGGER.info(
                "Optimizer: HIGH finding (dimension=%s) deferred to "
                "daily digest (not in NM allowlist)",
                getattr(finding, "dimension", None),
            )
            return
        nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
        if nm is None:
            return
        # A2 fix-up: cross-cycle dedup so an unchanged high finding
        # (e.g. away+unlocked SECURITY_POSTURE / sustained OVERRIDE_FREQUENCY)
        # doesn't page every 5-min cycle. Suppress re-notify for the same
        # dedup_key for OPTIMIZER_NOTIFY_DEDUP_CYCLES (~12 cycles ≈ 1h).
        try:
            dkey = finding.dedup_key
        except Exception:  # noqa: BLE001
            dkey = None
        if dkey is not None:
            # v5.11.0 D1 (MED-3 fix): TTL decrement moved to per-cycle
            # helper ``_decrement_notify_dedup_ttls`` (called once at
            # end of ``_run_cycle_body``). Previously decremented here
            # per-finding, collapsing the 12-cycle window to ~1.2 cycles
            # in high-severity cycles.
            dkey_str = str(dkey)
            if dkey_str in self._notify_dedup_state:
                _LOGGER.debug(
                    "Optimizer: suppressed re-notify for dedup_key=%s "
                    "(cycles_remaining=%d)",
                    dkey_str, self._notify_dedup_state[dkey_str],
                )
                return
            # Mark this dedup_key as suppressed for the next N cycles.
            self._notify_dedup_state[dkey_str] = (
                OPTIMIZER_NOTIFY_DEDUP_CYCLES
            )
            # v5.11.0 F-MED (A-MED-1 fix-up): record the key as
            # freshly-set THIS cycle so the end-of-cycle decrement
            # skips it exactly once. Otherwise the intended 12-cycle
            # window is collapsed to 11 by the same-cycle decrement.
            if getattr(self, "_notify_dedup_just_set", None) is None:
                self._notify_dedup_just_set = set()
            self._notify_dedup_just_set.add(dkey_str)
        sev_map = {"critical": Severity.CRITICAL, "high": Severity.HIGH}
        try:
            await nm.async_notify(
                coordinator_id="optimization",
                severity=sev_map[finding.severity],
                title=f"URA Optimizer — {finding.dimension}",
                message=finding.description,
                hazard_type=None,
                location=finding.target_id or "house",
                # A2: pass a stable identity so NM can dedup downstream too.
                event_class=(
                    f"optimizer.{finding.dimension}"
                    if finding.dimension is not None else "optimizer"
                ),
                dedup_key=(str(finding.dedup_key)
                           if finding.dedup_key is not None else None),
            )
        except TypeError:
            # NM signature may not accept the new kwargs in tests/older
            # builds; retry without them so the notification still fires.
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
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug("NM notify failed: %s", exc, exc_info=True)

    async def _flush_cycle_activity_summaries(self) -> None:
        """v5.2.2 fix-up — emit AT MOST ONE activity row per buffer.

        The shadow + below-gate branches of ``_consider_apply`` now
        APPEND to per-cycle buffers instead of calling
        ``_log_activity`` per finding (which previously caused an
        O(N) INSERT into ura_activity_log and O(N) per-row
        ``SIGNAL_ACTIVITY_LOGGED`` dispatches — the SECOND write-flood
        channel found post-v5.2.2 by adversarial review). This method
        drains the buffers as exactly one summary row per non-empty
        buffer (so worst-case 2 activity writes per cycle), preserving
        observability ("the optimizer advised N shadow findings this
        cycle") at O(1) DB cost.

        Sample caps in the summary payload keep the row small so
        ``ura_activity_log`` doesn't bloat under a flood.
        """
        SAMPLE_CAP = 10  # max distinct target ids included in summary
        for action_name, buf in (
            ("shadow_cycle_summary", self._cycle_shadow_log_buffer),
            ("clamped_cycle_summary", self._cycle_clamp_log_buffer),
        ):
            if not buf:
                continue
            count = len(buf)
            try:
                distinct_dims = sorted(
                    {str(r.get("dimension")) for r in buf
                     if r.get("dimension") is not None}
                )
                targets = [
                    str(r.get("target_id")) for r in buf
                    if r.get("target_id")
                ]
                # Stable distinct sample (preserve first-seen order).
                seen: set[str] = set()
                sampled: list[str] = []
                for t in targets:
                    if t in seen:
                        continue
                    seen.add(t)
                    sampled.append(t)
                    if len(sampled) >= SAMPLE_CAP:
                        break
            except Exception:  # noqa: BLE001 — never let summary crash cycle
                distinct_dims = []
                sampled = []
            details = {
                "count": count,
                "dimensions": distinct_dims,
                "rooms_or_targets": sampled,
                "sample_capped_at": SAMPLE_CAP,
            }
            description = (
                f"Optimizer cycle: {count} findings advised as "
                f"{action_name.replace('_cycle_summary', '')} "
                f"across {len(distinct_dims)} dimensions"
            )
            try:
                await self._log_activity(
                    action=action_name, importance="info",
                    description=description, details=details,
                )
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "cycle activity summary flush failed (%s)",
                    action_name, exc_info=True,
                )
        # Always clear buffers after a flush attempt so a partial
        # failure can't bleed into the next cycle's summary.
        self._cycle_shadow_log_buffer.clear()
        self._cycle_clamp_log_buffer.clear()

    async def _log_activity(
        self,
        action: str,
        importance: str,
        description: str,
        details: dict,
        finding: OptimizationFinding | None = None,
    ) -> None:
        """v5.11.0 F1 (fix-up): SINGLE DAO chokepoint for the
        ``ura_activity_log`` OC-attributed write channel.

        Every OC-side activity write flows through this method — the
        22 ``_log_activity`` sites inside ``_apply_action`` (kill-switch,
        clamp, advisory, domain-block, safety-denylist, shadow, ...)
        + ``_flush_cycle_activity_summaries`` all land here. This is
        the SECOND write-flood channel the v5.0-v5.2 postmortem missed
        (per-cycle activity writes could hit ~100/cycle when the LLM
        tier emits ``proposed_action`` findings, entering ``_apply_action``
        for every one). Gating here catches all of it in ONE place.
        """
        # v5.11.0 F1: tripwire gate BEFORE any DAO call. Drop-and-log
        # (do NOT queue) — a latch means we're in regression territory.
        if self._check_write_volume_tripwire():
            return
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
            # v5.11.0 F1: one DAO call = one OC-attributed DB write.
            self._record_db_write()
        except Exception:  # noqa: BLE001
            _LOGGER.debug("activity_logger.log failed", exc_info=True)

    # ------------------------------------------------------------------
    # Scoreboard / sensor exposure
    # ------------------------------------------------------------------

    def _update_scoreboard(self, findings: list[OptimizationFinding]) -> None:
        room_findings: dict[str, list[OptimizationFinding]] = {}
        zone_findings: dict[str, list[OptimizationFinding]] = {}
        open_count = 0
        worst_sev_rank = 99
        _sev_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        for f in findings:
            if f.dimension == OptimizationDimension.META:
                continue
            open_count += 1
            worst_sev_rank = min(
                worst_sev_rank, _sev_rank.get(f.severity, 99)
            )
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
        self._worst_open_severity_rank = worst_sev_rank

    @property
    def status(self) -> str:
        """Operator-recalibrated 2026-06-10: "critical" is reserved for an
        actual critical-severity open finding — a pile of HIGHs (e.g. dead
        sensors) reads "degraded", not "critical", so the word keeps
        meaning. Vocabulary unchanged: {healthy, degraded, critical}.
        """
        if getattr(self, "_worst_open_severity_rank", 99) == 0:
            return "critical"
        if self._house_score >= 90:
            return "healthy"
        return "degraded"

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
        # B4 fix-up: ``date`` is the user-facing day of coverage — use the
        # local calendar date, not the UTC date (which rolls late-evening
        # local time into the NEXT day). ``generated_at`` stays UTC ISO
        # for stable global ordering.
        return {
            "date": dt_util.now().date().isoformat(),
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
        """Build + persist a digest row. Returns the new id or None.

        B2 fix-up: NM fires the digest hook once per person per day, so a
        2-person house would persist 2 identical rows. Two layers of dedup:

        1. In-memory ``_last_persisted_digest_date`` short-circuits the
           DB round-trip on the 2nd+ fire of the same calendar day.
        2. The DB-level UNIQUE(date) + ON CONFLICT DO UPDATE in
           ``log_daily_digest`` is the durable safety net (covers cross-
           restart and timing races).
        """
        database = self.hass.data.get(DOMAIN, {}).get("database")
        if database is None or not hasattr(database, "log_daily_digest"):
            return None
        payload = self.build_daily_digest_payload(findings=findings)
        today = payload["date"]
        last = getattr(self, "_last_persisted_digest_date", None)
        if last == today:
            _LOGGER.debug(
                "Optimizer: digest already persisted for %s; skipping "
                "duplicate write (in-memory once-per-day guard)", today,
            )
            return None
        # v5.11.0 F1: tripwire gate — a latched persistence-suspend
        # must also suppress the once-a-day digest write, otherwise a
        # regressed OC could still hit the DB via the digest DAO.
        if self._check_write_volume_tripwire():
            _LOGGER.info(
                "Optimizer: persistence suspended by tripwire; "
                "dropping daily digest write for %s", today,
            )
            return None
        try:
            row_id = await database.log_daily_digest(
                date=today,
                generated_at=payload["generated_at"],
                findings_count=payload["findings_count"],
                by_severity=payload["by_severity"],
                by_dimension=payload["by_dimension"],
                summary=payload,
            )
            # Only mark as persisted on a successful write; a None return
            # means the DAO rejected the row (e.g. None date) and we want
            # the next call to retry.
            if row_id is not None:
                self._last_persisted_digest_date = today
                # v5.11.0 F1: one DAO call = one OC-attributed DB write.
                self._record_db_write()
            return row_id
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
