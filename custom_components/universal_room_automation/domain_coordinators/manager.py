"""Coordinator Manager and Conflict Resolver for domain coordinators."""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from datetime import timedelta
from typing import Any, Final

from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.util import dt as dt_util

from ..const import COORDINATOR_ENABLED_KEYS, DOMAIN, VERSION
from .base import (
    ActionType,
    BaseCoordinator,
    CoordinatorAction,
    Intent,
    NotificationAction,
    Severity,
    ServiceCallAction,
    SEVERITY_FACTORS,
)
from .coordinator_diagnostics import (
    AnomalyDetector,
    AnomalySeverity,
    ComplianceTracker,
    DailyCounter,
    DecisionLogger,
)
from .house_state import (
    HOUSE_STATE_HEARTBEAT_S,
    HOUSE_STATE_RESTORE_MAX_STALE_S,
    HOUSE_STATE_SAVE_DEBOUNCE_S,
    HOUSE_STATE_STORE_KEY,
    HOUSE_STATE_STORE_VERSION,
    HouseState,
    HouseStateMachine,
)

_LOGGER = logging.getLogger(__name__)

# Intent batching window — collect intents for this long before processing
INTENT_BATCH_WINDOW_MS: Final = 100  # milliseconds

# ANOMALY-BASELINES-NEVER-SAVED-ON-RESTART-1: cadence for CM-driven anomaly
# baseline persistence. Per-coordinator save_baselines() lived only in
# async_teardown, which does not run on an HA restart — so presence /
# security / safety / music_following learning was discarded every restart
# (live DB confirmed metric_baselines.last_updated weeks stale while
# teardown-free restarts cycle in hours). 3600s = at most one save per
# detector per hour, keeping the per-restart loss bounded while staying
# well within the write-volume guard that produced the v4.7 flood
# incident (one periodic save per detector per hour, not per decision cycle).
ANOMALY_BASELINE_SAVE_INTERVAL_S: Final = 3600

# ANOMALY-BASELINES-NEVER-SAVED-ON-RESTART-1 (B-LOW fix): bound the
# EVENT_HOMEASSISTANT_STOP flush so a slow / wedged DB cannot delay HA
# shutdown indefinitely. 30s is well above the normal multi-coordinator
# save latency but below any supervisor shutdown-watchdog threshold.
ANOMALY_BASELINE_STOP_SAVE_TIMEOUT_S: Final = 30

# v4.6.11 review fix (A.M2 / C.L4): hoisted to module level so the mapping is
# allocated once, not rebuilt on every get_summary()/get_system_anomaly_status()
# call. AnomalySeverity is a StrEnum so dict-key equality works against either
# the enum instance or its .value string.
_SEVERITY_RANK: Final[dict[AnomalySeverity, int]] = {
    AnomalySeverity.NOMINAL: 0,
    AnomalySeverity.ADVISORY: 1,
    AnomalySeverity.ALERT: 2,
    AnomalySeverity.CRITICAL: 3,
}


class ConflictResolver:
    """Resolves conflicts when multiple coordinators target the same device.

    Resolution logic:
    - Group actions by target_device
    - For each device with >1 action, pick the one with highest effective_priority
      weighted by the coordinator's base priority
    - CRITICAL severity actions always win (Safety)
    - Non-device actions (notifications, constraints, log_only) are never conflicted
    """

    def resolve(
        self,
        actions: list[tuple[BaseCoordinator, CoordinatorAction]],
    ) -> list[tuple[BaseCoordinator, CoordinatorAction]]:
        """Resolve conflicts and return the winning actions.

        Args:
            actions: List of (coordinator, action) tuples from all coordinators.

        Returns:
            List of (coordinator, action) tuples that should be executed.
        """
        if not actions:
            return []

        # Separate device-targeted actions from non-device actions
        device_actions: dict[str, list[tuple[BaseCoordinator, CoordinatorAction]]] = (
            defaultdict(list)
        )
        non_device_actions: list[tuple[BaseCoordinator, CoordinatorAction]] = []

        for coordinator, action in actions:
            if action.target_device:
                device_actions[action.target_device].append((coordinator, action))
            else:
                non_device_actions.append((coordinator, action))

        # Resolve per-device conflicts
        resolved: list[tuple[BaseCoordinator, CoordinatorAction]] = []

        for device_id, candidates in device_actions.items():
            if len(candidates) == 1:
                resolved.append(candidates[0])
                continue

            # Pick the winner: highest (coordinator.priority * action.effective_priority)
            winner = max(
                candidates,
                key=lambda ca: ca[0].priority * ca[1].effective_priority,
            )
            resolved.append(winner)

            # Log the conflict resolution
            losers = [c for c in candidates if c is not winner]
            _LOGGER.info(
                "Conflict on %s: %s (pri=%d, sev=%s) wins over %s",
                device_id,
                winner[0].coordinator_id,
                winner[0].priority,
                winner[1].severity.name,
                ", ".join(
                    f"{c.coordinator_id}(pri={c.priority},sev={a.severity.name})"
                    for c, a in losers
                ),
            )

        # Non-device actions pass through uncontested
        resolved.extend(non_device_actions)

        return resolved


class CoordinatorManager:
    """Orchestrates domain coordinators — intent queue, priority dispatch, execution.

    Lifecycle:
    1. Created during integration setup when CONF_DOMAIN_COORDINATORS_ENABLED is True.
    2. Registers coordinators (added by later cycles as they ship).
    3. Receives intents from triggers and queues them.
    4. Processes the intent queue in batches every INTENT_BATCH_WINDOW_MS.
    5. Invokes coordinators in priority order, collects actions, resolves conflicts.
    6. Executes approved actions and logs decisions.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the coordinator manager."""
        self.hass = hass
        # FAN-LAYER-1 D2 (2026-08-10, Session 1): construct the
        # FanPolicyOracle singleton BEFORE ``self._coordinators`` is
        # populated. Every writer coordinator that will later consult the
        # oracle is registered via ``register_coordinator``; constructing
        # here in ``__init__`` guarantees the oracle exists before any
        # writer's ``async_setup_entry`` fires (PLAN §7.7 boot-order
        # invariant, enforced by
        # ``test_fan_oracle_constructed_before_writers``).
        try:
            from .fan_policy_oracle import FanPolicyOracle  # noqa: PLC0415
            # B-HIGH-2 fix-up (2026-08-11): reuse an existing oracle from
            # hass.data if one is already present — a CM reload (config
            # entry reload) constructs a new CoordinatorManager but the
            # oracle instance MUST SURVIVE so live manual-ON holds and
            # OFF cooldowns aren't dropped. Constructing unconditionally
            # here would wipe every live hold on reload, causing an
            # immediate URA re-arm against a fan the operator just
            # turned on. Only construct on first attach.
            existing = None
            if hass is not None:
                try:
                    existing = hass.data.get(DOMAIN, {}).get("fan_oracle")
                except Exception:  # noqa: BLE001
                    existing = None
            self._fan_oracle: "FanPolicyOracle | None" = (
                existing if existing is not None else FanPolicyOracle(hass)
            )
            if hass is not None:
                try:
                    _dd = hass.data.setdefault(DOMAIN, {})
                    _dd["fan_oracle"] = self._fan_oracle
                    # FAN-ORACLE-BOOT-FALLBACK-NOISE-1: sticky marker so
                    # RoomAutomation only WARNs on fallback AFTER the oracle
                    # has been attached at least once (boot-order writes
                    # before attach are expected and logged at DEBUG).
                    _dd["fan_oracle_attached_once"] = True
                except Exception:  # noqa: BLE001
                    _LOGGER.debug(
                        "FanPolicyOracle: hass.data stash failed (non-fatal)",
                        exc_info=True,
                    )
        except Exception:  # noqa: BLE001
            _LOGGER.error(
                "FanPolicyOracle construction failed — Session 1 skeleton "
                "unavailable, no writers migrated yet so this is non-fatal",
                exc_info=True,
            )
            self._fan_oracle = None
        self._coordinators: dict[str, BaseCoordinator] = {}
        self._intent_queue: list[Intent] = []
        self._conflict_resolver = ConflictResolver()
        self._house_state_machine = HouseStateMachine()
        # D1 persistence: constructed here, loaded/heartbeat/stop-hook
        # wired in async_start.
        # Store is created lazily (_get_house_state_store): importing
        # homeassistant.helpers.storage at module level drags real HA helper
        # modules into sys.modules and breaks the stubbed-module test files
        # (order pollution found in the house-state batch name-diff).
        self._house_state_store = None
        self._house_state_heartbeat_unsub = None
        self._house_state_stop_unsub = None
        self._house_state_restored: bool = False
        # ANOMALY-BASELINES-NEVER-SAVED-ON-RESTART-1: periodic save +
        # EVENT_HOMEASSISTANT_STOP flush handles for coordinator anomaly
        # detectors. See _wire_anomaly_baseline_persistence.
        self._anomaly_baseline_periodic_unsub = None
        self._anomaly_baseline_stop_unsub = None
        self._processing = False
        self._batch_timer_unsub = None
        self._running = False
        # RESTART-SAFETY-DOCTRINE-1 F13: display-only counters exposed on
        # the CM diagnostics sensor. restart: RESET WITH REASON — metric-y
        # counters, no rate-cap consumer. Confirmed no reads on decision
        # paths; only sensor payloads at manager.py:751-752.
        self._conflicts_resolved_today = DailyCounter(
            name="coordinator_manager.conflicts_resolved_today",
            persist=False,
            reason="display-only diagnostic counter; not read on any policy path",
        )
        self._decisions_today = DailyCounter(
            name="coordinator_manager.decisions_today",
            persist=False,
            reason="display-only diagnostic counter; not read on any policy path",
        )
        # Retained for any legacy caller that might still probe the field;
        # DailyCounter now owns its own rollover date internally.
        self._last_reset_date: str = ""

        # v3.6.0-c0.4: Shared diagnostics components
        self._decision_logger = DecisionLogger(hass)
        self._compliance_tracker = ComplianceTracker(hass)

        # v3.6.29: Notification Manager (not a coordinator — standalone service)
        self._notification_manager = None

        # House-State Rung 2a (v5.39.0) — house-policy diagnostic surface.
        # Populated by coordinators via ``record_state_driven_action``. Exposed
        # on the CM device through ``HousePolicySensor`` per INV-1/INV-3.
        # * active_policies: string ids of policies currently ENABLED
        #   (recomputed via ``get_active_policies`` — this dict just caches
        #   the last-known set from coordinator publishes).
        # * last_state_driven_action: {policy, coordinator, record} where
        #   ``record`` is the coordinator's own arming/action trace.
        self._house_policy: dict[str, Any] = {
            "active_policies": [],
            "last_state_driven_action": {},
        }

        # v4.6.10 D3: CM-level anomaly detector for URA self-instrumentation.
        # Wrapped so detector failure does NOT prevent CM construction (CM failing = URA dead).
        try:
            self._setup_anomaly_detector = AnomalyDetector(
                hass=hass,
                coordinator_id="coordinator_manager",
                metric_names=["setup_duration_seconds"],
                minimum_samples=10,
            )
        except Exception:
            _LOGGER.debug(
                "v4.6.10: CM setup_anomaly_detector init failed (non-fatal)",
                exc_info=True,
            )
            self._setup_anomaly_detector = None

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info for the Coordinator Manager device."""
        return DeviceInfo(
            identifiers={(DOMAIN, "coordinator_manager")},
            name="URA: Coordinator Manager",
            manufacturer="Universal Room Automation",
            model="Coordinator Manager",
            sw_version=VERSION,
        )

    @property
    def notification_manager(self):
        """Return the Notification Manager instance."""
        return self._notification_manager

    def set_notification_manager(self, nm) -> None:
        """Set the Notification Manager instance."""
        self._notification_manager = nm
        _LOGGER.info("Notification Manager registered with Coordinator Manager")

    @property
    def house_state_machine(self) -> HouseStateMachine:
        """Return the house state machine."""
        return self._house_state_machine

    @property
    def house_state(self) -> HouseState:
        """Return the current house state."""
        return self._house_state_machine.state

    @property
    def house_policy(self) -> dict[str, Any]:
        """Return the house-policy diagnostic snapshot (INV-1).

        Consumed by ``HousePolicySensor`` on the CM device. The
        ``active_policies`` list is recomputed on every read; the sensor
        re-reads on ``SIGNAL_HOUSE_POLICY_UPDATE`` (signal-driven refresh),
        so a coordinator toggling its kill-switch shows up the next time
        that signal fires (i.e. on the next policy publish).
        """
        return {
            "active_policies": self._compute_active_policies(),
            "last_state_driven_action": dict(
                self._house_policy.get("last_state_driven_action") or {}
            ),
        }

    def _compute_active_policies(self) -> list[str]:
        """Return the list of policies whose enable + kill-switch are ON.

        Rung 2a adds ``security.auto_follow``: active iff the security
        coordinator is enabled AND its ``_auto_follow_house_state`` flag
        is True. Later rungs extend this list (energy.away_posture,
        guest.mode, etc.).
        """
        active: list[str] = []
        sec = self._coordinators.get("security")
        # B-H1 fix-up: use the public ``auto_follow_house_state`` property
        # instead of reaching into the private ``_auto_follow_house_state``.
        if (
            sec is not None
            and getattr(sec, "enabled", False)
            and getattr(sec, "auto_follow_house_state", False)
        ):
            active.append("security.auto_follow")
        return active

    def record_state_driven_action(
        self,
        policy: str,
        coordinator: str,
        action_record: dict[str, Any],
    ) -> None:
        """Record a state-driven action to the house-policy surface (INV-1).

        Called by a coordinator each time it takes (or would take) a
        state-driven action so the CM diagnostic sensor updates. The
        ``action_record`` is the coordinator's own trace payload (e.g.
        security's ``_state_driven_arming_last`` dict). Best-effort — this
        method must never raise.
        """
        try:
            self._house_policy["last_state_driven_action"] = {
                "policy": policy,
                "coordinator": coordinator,
                "record": dict(action_record or {}),
            }
            # Signal the CM house-policy sensor to re-read.
            try:
                from .signals import (  # noqa: PLC0415
                    SIGNAL_HOUSE_POLICY_UPDATE,
                )

                async_dispatcher_send(
                    self.hass, SIGNAL_HOUSE_POLICY_UPDATE
                )
            except Exception:  # noqa: BLE001
                pass
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "record_state_driven_action failed (non-fatal)", exc_info=True
            )

    @property
    def fan_oracle(self):
        """Return the FanPolicyOracle singleton (FAN-LAYER-1 D2).

        May be ``None`` if construction failed at ``__init__``. Callers
        MUST tolerate None; Session 1 has no wired consumers.
        """
        return self._fan_oracle

    @property
    def coordinators(self) -> dict[str, BaseCoordinator]:
        """Return registered coordinators."""
        return self._coordinators

    @property
    def is_running(self) -> bool:
        """Return whether the manager is running."""
        return self._running

    @property
    def conflicts_resolved_today(self) -> int:
        """Return number of conflicts resolved today."""
        return self._conflicts_resolved_today.value

    @property
    def decisions_today(self) -> int:
        """Return number of decisions made today."""
        return self._decisions_today.value

    def _maybe_reset_daily_counters(self) -> None:
        """Force a rollover check on the DailyCounter primitives.

        Kept for backward compatibility with any external caller. The
        counters now roll over lazily on access, so this is a no-op in
        the steady state.
        """
        self._conflicts_resolved_today.rollover_if_needed()
        self._decisions_today.rollover_if_needed()

    def register_coordinator(self, coordinator: BaseCoordinator) -> None:
        """Register a domain coordinator and inject diagnostics."""
        self._coordinators[coordinator.coordinator_id] = coordinator

        # v3.6.0-c0.4: Inject shared diagnostics components
        coordinator.decision_logger = self._decision_logger
        coordinator.compliance_tracker = self._compliance_tracker

        _LOGGER.info(
            "Registered coordinator: %s (priority=%d)",
            coordinator.coordinator_id,
            coordinator.priority,
        )

    def unregister_coordinator(self, coordinator_id: str) -> None:
        """Unregister a domain coordinator."""
        if coordinator_id in self._coordinators:
            del self._coordinators[coordinator_id]
            _LOGGER.info("Unregistered coordinator: %s", coordinator_id)

    def _get_house_state_store(self):
        """Return the house-state Store, creating it on first use."""
        if self._house_state_store is None:
            from homeassistant.helpers.storage import Store  # noqa: PLC0415

            self._house_state_store = Store(
                self.hass, HOUSE_STATE_STORE_VERSION, HOUSE_STATE_STORE_KEY,
            )
        return self._house_state_store

    async def async_start(self) -> None:
        """Start the coordinator manager."""
        self._running = True
        self._last_reset_date = dt_util.now().date().isoformat()

        # D1 (PLANNING house_state restart): restore the last persisted
        # house-state BEFORE any coordinator setup runs. At this point no
        # consumer has read ``manager.house_state`` and no signal listeners
        # exist to dispatch to, so the machine can flip to the restored
        # state without any consumer observing a transition. Failure here
        # is non-fatal — machine simply stays at AWAY.
        try:
            await self._async_restore_house_state()
        except Exception:  # noqa: BLE001 — defensive
            _LOGGER.warning(
                "House-state restore: async_load raised (non-fatal)",
                exc_info=True,
            )
        # Wire persistence hooks on the machine now (transitions during
        # coordinator setup should also be persisted).
        self._wire_house_state_persistence()

        # Set up all registered coordinators.
        # v3.21.0 D2: Startup ordering dependency — HVAC waits on Presence
        # _ready_event (set after initial inference). Dict insertion order
        # already puts Presence before HVAC, but the event makes it explicit.
        for coord_id, coordinator in self._coordinators.items():
            try:
                await coordinator.async_setup()
                _LOGGER.info("Coordinator %s started", coord_id)
            except Exception:
                _LOGGER.exception("Failed to start coordinator %s", coord_id)

        # v3.6.29: Start Notification Manager
        if self._notification_manager:
            try:
                await self._notification_manager.async_setup()
                self.hass.data.setdefault(DOMAIN, {})["notification_manager"] = (
                    self._notification_manager
                )
                _LOGGER.info("Notification Manager started")
            except Exception:
                _LOGGER.exception("Failed to start Notification Manager")

        # v4.6.11 D1: CM-level anomaly detector baseline persistence.
        # Pattern mirrors safety.py:689 / hvac.py:534 / presence.py:638 /
        # security.py:631 / music_following.py:170. Without this load,
        # the in-memory _baselines dict resets every restart and
        # minimum_samples=10 (manager.py:154) is unreachable.
        if self._setup_anomaly_detector is not None:
            try:
                await self._setup_anomaly_detector.load_baselines()
                _LOGGER.debug(
                    "v4.6.11 D1: CM setup_anomaly_detector baselines loaded"
                )
            except Exception:
                _LOGGER.debug(
                    "v4.6.11 D1: CM setup_anomaly_detector load_baselines failed (non-fatal)",
                    exc_info=True,
                )

        # ANOMALY-BASELINES-NEVER-SAVED-ON-RESTART-1: wire the periodic
        # save + stop-flush AFTER all coordinators are up so their
        # anomaly_detector attributes exist.
        self._wire_anomaly_baseline_persistence()

        _LOGGER.info(
            "Coordinator Manager started with %d coordinators",
            len(self._coordinators),
        )

    # ------------------------------------------------------------------
    # ANOMALY-BASELINES-NEVER-SAVED-ON-RESTART-1
    # ------------------------------------------------------------------
    def _wire_anomaly_baseline_persistence(self) -> None:
        """Register the periodic save + EVENT_HOMEASSISTANT_STOP flush.

        Reuses the ``async_listen_once(EVENT_HOMEASSISTANT_STOP)`` pattern
        from the house-state stop-hook above (see ``_wire_house_state_persistence``)
        rather than introducing a second stop-listener style. The periodic
        timer mirrors the house-state heartbeat shape.
        """
        if self._anomaly_baseline_periodic_unsub is None:
            self._anomaly_baseline_periodic_unsub = async_track_time_interval(
                self.hass,
                self._async_persist_coordinator_baselines_periodic,
                timedelta(seconds=ANOMALY_BASELINE_SAVE_INTERVAL_S),
            )
        if self._anomaly_baseline_stop_unsub is None:
            try:
                self._anomaly_baseline_stop_unsub = self.hass.bus.async_listen_once(
                    EVENT_HOMEASSISTANT_STOP,
                    self._async_persist_coordinator_baselines_on_stop,
                )
            except Exception:  # noqa: BLE001 — defensive
                _LOGGER.debug(
                    "Anomaly-baseline stop-hook registration failed",
                    exc_info=True,
                )

    async def _persist_coordinator_baselines(
        self, *, include_safety_rate: bool = False,
    ) -> None:
        """Persist anomaly baselines for every coordinator that owns a detector.

        Covers presence / security / safety / music_following / HVAC
        (idempotent — HVAC also persists on genuine daily rollover) plus
        the CM setup detector. Per-detector failures are isolated so one
        broken writer cannot block the others. Called at most once per
        ``ANOMALY_BASELINE_SAVE_INTERVAL_S`` from the periodic timer, plus
        once on ``EVENT_HOMEASSISTANT_STOP`` — i.e. no per-cycle write
        amplification.

        ``include_safety_rate``: when True, also calls
        ``safety._save_rate_baselines`` (the parallel ``safety_rate`` scope).
        Default False because Safety already persists its rate baselines
        every 30 min internally (safety.py:1214) — the periodic CM path
        must NOT duplicate that writer; only the STOP path sets this True
        to capture samples accrued between the last internal save and
        shutdown. (Review B-MEDIUM.)
        """
        # B-LOW: if the CM has been stopped (or the parent entry is tearing
        # down), a tick already in flight should be a no-op. async_stop sets
        # ``_running=False`` before unsubscribing the periodic/stop handles,
        # so this bounds any lap in flight across the unwire gap. Note the
        # EVENT_HOMEASSISTANT_STOP path fires BEFORE async_stop, so
        # ``_running`` is still True there (verified in restart-safety tests).
        if not getattr(self, "_running", False):
            _LOGGER.debug(
                "Anomaly-baseline persist: CM not running — skipping tick"
            )
            return
        for coord in list(self._coordinators.values()):
            detector = getattr(coord, "anomaly_detector", None)
            if detector is None:
                continue
            try:
                await detector.save_baselines()
            except Exception:  # noqa: BLE001
                _LOGGER.warning(
                    "Anomaly-baseline persist: save_baselines failed for %s "
                    "(non-fatal)",
                    getattr(coord, "coordinator_id", type(coord).__name__),
                    exc_info=True,
                )
        # Safety carries a parallel rate-baseline table (scope=safety_rate).
        # Only invoked on the STOP path — the periodic path leaves this to
        # Safety's own 30-min internal save (safety.py:1214) to avoid double
        # writers racing on the same table (B-MEDIUM).
        if include_safety_rate:
            safety = self._coordinators.get("safety")
            save_rate = getattr(safety, "_save_rate_baselines", None)
            if save_rate is not None:
                try:
                    await save_rate()
                except Exception:  # noqa: BLE001
                    _LOGGER.debug(
                        "Anomaly-baseline persist: safety._save_rate_baselines "
                        "failed (non-fatal)",
                        exc_info=True,
                    )
        # CM setup detector (one sample per boot). async_stop already
        # persists it, but EVENT_HOMEASSISTANT_STOP fires BEFORE async_stop
        # and async_stop does not run on an HAOS restart that kills the
        # process; re-flushing here guarantees arrival of samples captured
        # between the previous period and the stop.
        if self._setup_anomaly_detector is not None:
            try:
                await self._setup_anomaly_detector.save_baselines()
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "Anomaly-baseline persist: setup detector save failed "
                    "(non-fatal)",
                    exc_info=True,
                )

    @callback
    def _async_persist_coordinator_baselines_periodic(self, _now: Any) -> None:
        """Periodic-timer callback. Schedules the async persist."""
        self.hass.async_create_task(self._persist_coordinator_baselines())

    async def _async_persist_coordinator_baselines_on_stop(
        self, _event: Any
    ) -> None:
        """EVENT_HOMEASSISTANT_STOP callback — awaited inline so the save
        completes before HA finishes stopping.

        Bounded by ``ANOMALY_BASELINE_STOP_SAVE_TIMEOUT_S`` (B-LOW fix) so
        a wedged DB cannot stall HA shutdown; on timeout we log and move
        on — the next boot will reload whatever did make it to disk.
        Includes safety_rate on this path (STOP-only).
        """
        try:
            async with asyncio.timeout(ANOMALY_BASELINE_STOP_SAVE_TIMEOUT_S):
                await self._persist_coordinator_baselines(
                    include_safety_rate=True,
                )
        except TimeoutError:
            _LOGGER.warning(
                "Anomaly-baseline STOP save exceeded %ds — abandoning flush "
                "to avoid stalling HA shutdown",
                ANOMALY_BASELINE_STOP_SAVE_TIMEOUT_S,
            )

    async def _async_restore_house_state(self) -> None:
        """D1: load persisted state from Store and apply it to the machine."""
        data = await self._get_house_state_store().async_load()
        if data is None:
            _LOGGER.info(
                "House-state restore: no persisted record (cold-boot default AWAY)"
            )
            self._house_state_restored = False
            return
        restored, age_s, reason = self._house_state_machine.apply_restored(
            data,
            max_stale_s=HOUSE_STATE_RESTORE_MAX_STALE_S,
        )
        if restored:
            _LOGGER.info(
                "House-state restore: state=%s age_s=%.0f override=%s "
                "(boot_restore_active=True)",
                self._house_state_machine._state.value,
                age_s,
                self._house_state_machine._override,
            )
            self._house_state_restored = True
        else:
            _LOGGER.info(
                "House-state restore: NOT applied (age_s=%.0f max=%d reason=%s) — "
                "machine remains at %s",
                age_s,
                HOUSE_STATE_RESTORE_MAX_STALE_S,
                reason,
                self._house_state_machine._state.value,
            )
            self._house_state_restored = False

    def _wire_house_state_persistence(self) -> None:
        """Register debounced-save hook, heartbeat, stop-hook, D2 adapter."""
        store = self._get_house_state_store()
        machine = self._house_state_machine

        def _data_provider() -> dict[str, Any]:
            try:
                return machine.to_persisted_dict()
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "House-state persist: to_persisted_dict raised",
                    exc_info=True,
                )
                return {}

        def _on_persist_change() -> None:
            try:
                store.async_delay_save(
                    _data_provider, HOUSE_STATE_SAVE_DEBOUNCE_S
                )
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "House-state persist: async_delay_save raised",
                    exc_info=True,
                )

        machine.on_persist_change = _on_persist_change

        # D2 hook adapter: route override set/clear through the
        # presence-owned dispatch helper so both boot-settle and
        # observation-mode gates apply and one D7 + activity row is written.
        def _on_state_change(
            old: HouseState, new: HouseState, trigger: str
        ) -> None:
            try:
                presence = self._coordinators.get("presence")
                helper = getattr(
                    presence, "_dispatch_house_state_change", None
                ) if presence is not None else None
                if helper is None:
                    # Presence not yet up (very early boot): fall back to a
                    # direct dispatch (still short-circuited by nothing —
                    # override on empty coordinator set is a no-op path).
                    _LOGGER.debug(
                        "override dispatch adapter: presence not available yet"
                    )
                    return
                # A-MED-3: operator-driven overrides are, by definition,
                # a certain intent. Emit confidence=1.0 (not None) so
                # subscribers see a fully-confident payload equivalent
                # to a Safety-forced transition.
                helper(old, new, trigger, 1.0, "override_adapter")
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "override dispatch adapter raised (non-fatal)",
                    exc_info=True,
                )

        machine.on_state_change = _on_state_change

        # Heartbeat: forced flush every HOUSE_STATE_HEARTBEAT_S so
        # ``saved_at`` reflects liveness. Disabled when the const is 0.
        if HOUSE_STATE_HEARTBEAT_S > 0 and self._house_state_heartbeat_unsub is None:
            def _heartbeat(_now: Any) -> None:
                try:
                    # Fire the forced save through delay_save so it
                    # coalesces if a change is already pending.
                    store.async_delay_save(_data_provider, 0.0)
                except Exception:  # noqa: BLE001
                    _LOGGER.debug(
                        "House-state heartbeat save raised", exc_info=True
                    )

            self._house_state_heartbeat_unsub = async_track_time_interval(
                self.hass,
                _heartbeat,
                timedelta(seconds=HOUSE_STATE_HEARTBEAT_S),
            )

        # Stop-hook: forced graceful flush on HA shutdown.
        if self._house_state_stop_unsub is None:
            async def _on_ha_stop(_event: Any) -> None:
                try:
                    await store.async_save(_data_provider())
                except Exception:  # noqa: BLE001
                    _LOGGER.debug(
                        "House-state stop-hook save raised", exc_info=True
                    )

            try:
                self._house_state_stop_unsub = self.hass.bus.async_listen_once(
                    EVENT_HOMEASSISTANT_STOP, _on_ha_stop
                )
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "House-state stop-hook registration failed", exc_info=True
                )

    async def async_stop(self) -> None:
        """Stop the coordinator manager and tear down all coordinators."""
        self._running = False

        # Cancel pending batch timer
        if self._batch_timer_unsub is not None:
            self._batch_timer_unsub()
            self._batch_timer_unsub = None

        # D1: unsubscribe heartbeat and stop-hook; flush any pending save.
        if self._house_state_heartbeat_unsub is not None:
            try:
                self._house_state_heartbeat_unsub()
            except Exception:  # noqa: BLE001
                pass
            self._house_state_heartbeat_unsub = None
        if self._house_state_stop_unsub is not None:
            try:
                self._house_state_stop_unsub()
            except Exception:  # noqa: BLE001
                pass
            self._house_state_stop_unsub = None
        # ANOMALY-BASELINES-NEVER-SAVED-ON-RESTART-1: unwire the periodic
        # save + stop-flush. Both are idempotent to clear.
        if self._anomaly_baseline_periodic_unsub is not None:
            try:
                self._anomaly_baseline_periodic_unsub()
            except Exception:  # noqa: BLE001
                pass
            self._anomaly_baseline_periodic_unsub = None
        if self._anomaly_baseline_stop_unsub is not None:
            try:
                self._anomaly_baseline_stop_unsub()
            except Exception:  # noqa: BLE001
                pass
            self._anomaly_baseline_stop_unsub = None
        try:
            # Flush any pending delayed save.
            await self._get_house_state_store().async_save(
                self._house_state_machine.to_persisted_dict()
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "House-state final flush on stop raised", exc_info=True
            )
        # Detach hooks so a torn-down machine cannot re-enter save paths.
        self._house_state_machine.on_persist_change = None
        self._house_state_machine.on_state_change = None

        # Tear down all coordinators in reverse priority order
        sorted_coords = sorted(
            self._coordinators.values(),
            key=lambda c: c.priority,
        )
        for coordinator in sorted_coords:
            try:
                await coordinator.async_teardown()
                _LOGGER.info("Coordinator %s stopped", coordinator.coordinator_id)
            except Exception:
                _LOGGER.exception(
                    "Error stopping coordinator %s", coordinator.coordinator_id
                )

        # RESTART-SAFETY-DOCTRINE-1 F2: persist setup AnomalyDetector
        # baselines. Sibling of the safety.py F1 fix; setup timing is
        # sampled once per boot so MINIMUM_SAMPLES=10 takes ~10 restarts to
        # reach — the ONLY way baselines can arm is by surviving each
        # restart. Load call at manager.py:428 was previously paired with
        # no save.
        if self._setup_anomaly_detector is not None:
            try:
                await self._setup_anomaly_detector.save_baselines()
                _LOGGER.info(
                    "CM: saved setup_anomaly_detector baselines on stop"
                )
            except Exception:
                _LOGGER.warning(
                    "CM: failed to save setup_anomaly_detector baselines "
                    "on stop",
                    exc_info=True,
                )

        # v3.6.29: Stop Notification Manager
        if self._notification_manager:
            try:
                await self._notification_manager.async_teardown()
                self.hass.data.get(DOMAIN, {}).pop("notification_manager", None)
            except Exception:
                _LOGGER.exception("Error stopping Notification Manager")

        # UNLOAD-SYMMETRY-TASK-HYGIENE-1: cancel any pending compliance
        # ``schedule_check`` callbacks retained on the CM's shared
        # ``ComplianceTracker`` so they cannot fire against a torn-down
        # manager after unload/reload.
        try:
            _ct = getattr(self, "_compliance_tracker", None)
            if _ct is not None and hasattr(_ct, "async_teardown"):
                _ct.async_teardown()
        except Exception:  # noqa: BLE001 — defensive
            _LOGGER.debug(
                "CM: ComplianceTracker teardown raised (non-fatal)",
                exc_info=True,
            )

        self._intent_queue.clear()
        _LOGGER.info("Coordinator Manager stopped")

    @callback
    def queue_intent(self, intent: Intent) -> None:
        """Queue an intent for processing.

        Intents are collected in a batching window. When the first intent arrives,
        a timer is started. When the timer fires, all queued intents are processed.
        """
        if not self._running:
            return

        self._intent_queue.append(intent)

        # Start batch timer if not already running
        if self._batch_timer_unsub is None:
            self._batch_timer_unsub = async_call_later(
                self.hass,
                INTENT_BATCH_WINDOW_MS / 1000.0,
                self._async_process_batch,
            )

    async def _async_process_batch(self, _now: Any = None) -> None:
        """Process the current batch of intents."""
        self._batch_timer_unsub = None

        if self._processing or not self._intent_queue:
            return

        self._processing = True
        try:
            # Drain the queue
            intents = list(self._intent_queue)
            self._intent_queue.clear()

            # Build shared context
            context = self._build_context()

            # Collect actions from all coordinators in priority order (highest first)
            all_actions: list[tuple[BaseCoordinator, CoordinatorAction]] = []
            sorted_coords = sorted(
                self._coordinators.values(),
                key=lambda c: c.priority,
                reverse=True,
            )

            for coordinator in sorted_coords:
                if not coordinator.enabled:
                    continue

                # Filter intents for this coordinator
                coord_intents = [
                    i
                    for i in intents
                    if not i.coordinator_id
                    or i.coordinator_id == coordinator.coordinator_id
                ]
                if not coord_intents:
                    continue

                try:
                    actions = await coordinator.evaluate(coord_intents, context)
                    for action in actions:
                        all_actions.append((coordinator, action))
                except Exception:
                    _LOGGER.exception(
                        "Error evaluating coordinator %s",
                        coordinator.coordinator_id,
                    )

            if not all_actions:
                return

            # Resolve conflicts
            pre_resolve_count = len(all_actions)
            resolved = self._conflict_resolver.resolve(all_actions)
            conflicts = pre_resolve_count - len(resolved)
            if conflicts > 0:
                self._conflicts_resolved_today.increment(conflicts)

            # Execute approved actions
            for coordinator, action in resolved:
                await self._execute_action(coordinator, action)
                self._decisions_today.increment()

        except Exception:
            _LOGGER.exception("Error processing intent batch")
        finally:
            self._processing = False

            # If more intents arrived during processing, schedule another batch
            if self._intent_queue and self._batch_timer_unsub is None:
                self._batch_timer_unsub = async_call_later(
                    self.hass,
                    INTENT_BATCH_WINDOW_MS / 1000.0,
                    self._async_process_batch,
                )

    def _build_context(self) -> dict[str, Any]:
        """Build the shared context dict passed to all coordinators."""
        return {
            "house_state": self._house_state_machine.state,
            "house_state_machine": self._house_state_machine.to_dict(),
            "timestamp": dt_util.utcnow().isoformat(),
            "coordinators_active": [
                c.coordinator_id
                for c in self._coordinators.values()
                if c.enabled
            ],
        }

    async def _execute_action(
        self,
        coordinator: BaseCoordinator,
        action: CoordinatorAction,
    ) -> None:
        """Execute a single approved action."""
        try:
            if action.action_type == ActionType.SERVICE_CALL:
                if isinstance(action, ServiceCallAction) and action.service:
                    domain, service = action.service.split(".", 1)
                    # Room lighting Slice C (v5.103.28): Safety emergency
                    # lights + Security lights run through here — stamp
                    # every coordinator write as URA's so the D2
                    # manual-change listener never books it as a person.
                    try:
                        from ..ura_context import ura_ctx_kwargs  # noqa: PLC0415
                        _ctx_kw = ura_ctx_kwargs(domain)
                    except Exception:  # noqa: BLE001
                        _ctx_kw = {}
                    await self.hass.services.async_call(
                        domain,
                        service,
                        action.service_data,
                        blocking=True,
                        **_ctx_kw,
                    )
                    _LOGGER.info(
                        "Executed %s.%s on %s (coordinator=%s, severity=%s)",
                        domain,
                        service,
                        action.target_device,
                        coordinator.coordinator_id,
                        action.severity.name,
                    )

            elif action.action_type == ActionType.NOTIFICATION:
                # v3.6.29: Route NotificationAction through NM
                if isinstance(action, NotificationAction) and self._notification_manager:
                    try:
                        await self._notification_manager.async_notify(
                            coordinator_id=coordinator.coordinator_id,
                            severity=action.severity,
                            title=action.description,
                            message=action.message,
                            hazard_type=action.hazard_type or None,
                            location=action.location or None,
                        )
                    except Exception:
                        # v4.5.20: was debug, with no exc captured —
                        # HIGH-severity. This is the central dispatch
                        # path for EVERY coordinator-issued notification
                        # (safety hazards, security armed-state, energy
                        # alerts). Silent failure kills every operator-
                        # visible URA notification. "Non-fatal" is a
                        # misnomer — NM IS the operator's eye.
                        _LOGGER.warning(
                            "NM routing failed for %s (%s)",
                            coordinator.coordinator_id,
                            action.description,
                            exc_info=True,
                        )
                _LOGGER.info(
                    "Notification from %s: %s (severity=%s)",
                    coordinator.coordinator_id,
                    action.description,
                    action.severity.name,
                )

            elif action.action_type == ActionType.LOG_ONLY:
                _LOGGER.info(
                    "Decision logged: %s — %s (severity=%s)",
                    coordinator.coordinator_id,
                    action.description,
                    action.severity.name,
                )

            # Log decision to database
            await self._log_decision(coordinator, action)

        except Exception:
            _LOGGER.exception(
                "Error executing action from %s on %s",
                coordinator.coordinator_id,
                action.target_device,
            )

    async def _log_decision(
        self,
        coordinator: BaseCoordinator,
        action: CoordinatorAction,
    ) -> None:
        """Log a decision to the database."""
        database = self.hass.data.get(DOMAIN, {}).get("database")
        if database is None:
            return

        try:
            await database.log_coordinator_decision(
                coordinator_id=coordinator.coordinator_id,
                decision_type=action.action_type.value,
                context_json=json.dumps({"severity": action.severity.name}),
                action_json=json.dumps(
                    {
                        "target": action.target_device,
                        "description": action.description,
                        "data": str(action.data)[:500],
                    }
                ),
            )
        except Exception:
            # v4.5.20: was debug. Decision audit trail to DB. If schema
            # drifts or DB locks, decisions sensor + history reports go
            # blank with no warning. Doesn't break operation, but the
            # audit-trail feature silently disappears.
            _LOGGER.warning(
                "Failed to log decision for %s — audit-trail row dropped",
                coordinator.coordinator_id,
                exc_info=True,
            )

    def get_summary(self) -> dict[str, Any]:
        """Build coordinator summary for the summary sensor."""
        self._maybe_reset_daily_counters()

        # v4.6.11 D4.1: Build per-coordinator health data and aggregate health_status.
        # Severity mapping: NOMINAL → green, ADVISORY → orange, ALERT/CRITICAL → red.
        # Uses getattr(coordinator, "anomaly_detector", None) — not all coordinators have one.
        worst_rank = 0
        status_per_coordinator: dict[str, dict] = {}
        for coord_id, coordinator in self._coordinators.items():
            det = getattr(coordinator, "anomaly_detector", None)
            if det is not None:
                try:
                    worst_sev = det.get_worst_severity()
                    rank = _SEVERITY_RANK.get(worst_sev, 0)
                    if rank > worst_rank:
                        worst_rank = rank
                    # Review A M1: count only persisted active anomalies — the
                    # raw _active_anomalies list includes suppressed metrics
                    # (e.g. hvac.zone_call_frequency) that get_worst_severity()
                    # already filters out via _persisted_active_anomalies().
                    # Without this, status="nominal" could ship with
                    # active_anomalies>0, which dashboards render as broken.
                    try:
                        active_count = len(det._persisted_active_anomalies())
                    except Exception:
                        active_count = len(getattr(det, "_active_anomalies", []))
                    sev_label = worst_sev.value if worst_sev else "nominal"
                except Exception:
                    rank = 0
                    active_count = 0
                    sev_label = "nominal"
            else:
                rank = 0
                active_count = 0
                sev_label = "nominal"
            # HVAC-ANOMALY-BLIND-1 residual A: additive coverage key. `status`
            # stays SEVERITY (PWA badge + health_status unchanged); coverage
            # is "full" | "partial" per detector, "not_configured" without one.
            if det is not None:
                try:
                    coverage = det.get_coverage_state()
                except Exception:
                    _LOGGER.debug(
                        "get_summary: coverage read failed for %s", coord_id,
                        exc_info=True,
                    )
                    coverage = "unknown"
            else:
                coverage = "not_configured"
            status_per_coordinator[coord_id] = {
                "status": sev_label,
                "active_anomalies": active_count,
                "enabled": coordinator.enabled,
                "coverage": coverage,
            }

        if worst_rank == 0:
            health_status = "green"
        elif worst_rank == 1:
            health_status = "orange"
        else:
            health_status = "red"

        summary: dict[str, Any] = {
            "house_state": str(self._house_state_machine.state),
            "coordinators_registered": len(self._coordinators),
            "coordinators_active": sum(
                1 for c in self._coordinators.values() if c.enabled
            ),
            "decisions_today": self._decisions_today.value,
            "conflicts_resolved_today": self._conflicts_resolved_today.value,
            "health_status": health_status,
            "status_per_coordinator": status_per_coordinator,
        }

        # Add per-coordinator status (populated by each coordinator as they ship)
        for coord_id, coordinator in self._coordinators.items():
            summary[coord_id] = f"registered (priority={coordinator.priority})"

        return summary

    def get_overall_status(self) -> str:
        """Return the overall coordinator status string."""
        if not self._running:
            return "stopped"
        if not self._coordinators:
            return "running (no coordinators)"
        return "running"

    # =========================================================================
    # v3.6.0-c0.4: Enable/Disable Coordinators
    # =========================================================================

    async def async_set_coordinator_enabled(
        self,
        coordinator_id: str,
        enabled: bool,
    ) -> bool:
        """Enable or disable a coordinator.

        When disabling: sets _enabled=False, cancels listeners, sensors show 'disabled'.
        When enabling: sets _enabled=True, calls async_setup() to re-register.
        """
        coordinator = self._coordinators.get(coordinator_id)
        if coordinator is None:
            _LOGGER.warning(
                "Cannot enable/disable unknown coordinator: %s",
                coordinator_id,
            )
            return False

        if enabled == coordinator.enabled:
            return True  # No change needed

        if enabled:
            coordinator.enabled = True
            try:
                await coordinator.async_setup()
                _LOGGER.info("Coordinator %s re-enabled", coordinator_id)
            except Exception:
                _LOGGER.exception(
                    "Error re-enabling coordinator %s", coordinator_id
                )
                coordinator.enabled = False
                return False
        else:
            coordinator.enabled = False
            coordinator._cancel_listeners()
            _LOGGER.info("Coordinator %s disabled", coordinator_id)

        return True

    def get_coordinator_status(self, coordinator_id: str) -> dict:
        """Get status for a specific coordinator."""
        coordinator = self._coordinators.get(coordinator_id)
        if coordinator is None:
            return {"status": "not_registered"}

        return {
            "status": "enabled" if coordinator.enabled else "disabled",
            "coordinator_id": coordinator_id,
            "name": coordinator.name,
            "priority": coordinator.priority,
        }

    # =========================================================================
    # v3.6.0-c0.4: Diagnostics Aggregation
    # =========================================================================

    @property
    def decision_logger(self) -> DecisionLogger:
        """Return the shared decision logger."""
        return self._decision_logger

    @property
    def compliance_tracker(self) -> ComplianceTracker:
        """Return the shared compliance tracker."""
        return self._compliance_tracker

    def get_system_anomaly_status(self) -> dict[str, Any]:
        """Get aggregated anomaly status across all coordinators."""
        self._maybe_reset_daily_counters()

        worst_severity = AnomalySeverity.NOMINAL
        total_active = 0
        total_today = 0
        worst_coordinator = ""
        worst_metric = ""
        learning_status: dict[str, str] = {}
        coordinators_with_anomalies: list[str] = []
        # HVAC-ANOMALY-BLIND-1 residual A: detectors with a blind metric.
        coordinators_partial: list[str] = []

        # Same ordering as module-level _SEVERITY_RANK.
        severity_order = _SEVERITY_RANK

        for coord_id, coordinator in self._coordinators.items():
            if coordinator.anomaly_detector is None:
                learning_status[coord_id] = "not_configured"
                continue

            detector = coordinator.anomaly_detector
            status = detector.get_learning_status()
            learning_status[coord_id] = status

            summary = detector.get_status_summary()
            active = summary.get("active_anomalies", 0)
            today = summary.get("anomalies_today", 0)
            total_active += active
            total_today += today

            if active > 0:
                coordinators_with_anomalies.append(coord_id)
            if summary.get("coverage") == "partial":
                coordinators_partial.append(coord_id)

            coord_severity = detector.get_worst_severity()
            if severity_order.get(coord_severity, 0) > severity_order.get(
                worst_severity, 0
            ):
                worst_severity = coord_severity
                worst_coordinator = coord_id
                metric_name, _z = detector.get_worst_metric()
                worst_metric = metric_name

        return {
            "state": worst_severity.value,
            "active_anomalies": total_active,
            "anomalies_today": total_today,
            "worst_severity": worst_severity.value,
            "worst_coordinator": worst_coordinator,
            "worst_metric": worst_metric,
            "coordinators_with_anomalies": coordinators_with_anomalies,
            "coordinators_partial": coordinators_partial,
            "learning_status": learning_status,
        }

    def get_diagnostics_summary(self) -> dict[str, Any]:
        """Get full diagnostics summary across all coordinators."""
        summary: dict[str, Any] = {
            "system_anomaly": self.get_system_anomaly_status(),
            "coordinators": {},
        }

        for coord_id, coordinator in self._coordinators.items():
            summary["coordinators"][coord_id] = (
                coordinator.get_diagnostics_summary()
            )

        return summary
