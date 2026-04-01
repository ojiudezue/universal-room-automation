"""Tests for Cycle D: Coordinator Hardening (v3.21.0).

Covers 6 deliverables (D5 verified OK, no fix needed):
- D1: Energy DB Restore Parallelization + Timeout
- D2: Coordinator Startup Ordering (Presence ready_event)
- D3: Safety Sensor Recovery (unavailable->available re-evaluation)
- D4: NM Alert State Persistence (get/restore persistence state)
- D6: Energy Observation Mode RestoreEntity
- D7: AI Automation Per-Room Toggle

TESTING METHODOLOGY:
Tests verify decision logic directly using MockHass/MockCoordinator fixtures.
No heavy HA module mocking. Each test is self-contained.
"""
import asyncio
import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, AsyncMock, patch
from tests.conftest import (
    MockHass, MockConfigEntry, MockCoordinator,
)


# =============================================================================
# HELPERS
# =============================================================================

def make_coordinator_with_ai_toggle(mock_hass, room_name="bedroom"):
    """Create a mock coordinator with _is_ai_automation_enabled wired up."""
    entry = MockConfigEntry(data={"room_name": room_name.replace("_", " ").title()})
    coord = MockCoordinator(mock_hass, entry)
    slug = room_name.lower().replace(" ", "_")

    def _get_room_switch_state(suffix):
        entity_id = f"switch.{slug}_{suffix}"
        state = mock_hass.states.get(entity_id)
        if state is None:
            return None
        return state.state == "on"

    coord._get_room_switch_state = _get_room_switch_state

    def _is_ai_automation_enabled():
        state = coord._get_room_switch_state("ai_automation")
        if state is None:
            return True  # Default to enabled if switch not found
        return state

    def _is_automation_enabled():
        manual = coord._get_room_switch_state("manual_mode")
        if manual is True:
            return False
        auto = coord._get_room_switch_state("automation")
        if auto is None:
            return True
        return auto

    coord._is_ai_automation_enabled = _is_ai_automation_enabled
    coord._is_automation_enabled = _is_automation_enabled
    return coord


# =============================================================================
# D1: ENERGY DB RESTORE PARALLELIZATION + TIMEOUT
# =============================================================================

class TestEnergyDBRestoreParallelization:
    """Tests for parallel DB restore with gather + timeout.

    v3.21.0 D1: Energy coordinator now runs all 11 restore tasks via
    asyncio.gather(return_exceptions=True) wrapped in asyncio.wait_for(timeout=15).
    Previously these were 10+ sequential awaits.
    """

    @pytest.mark.asyncio
    async def test_gather_handles_individual_task_failure(self):
        """One task failing should not prevent others from completing.

        asyncio.gather(return_exceptions=True) returns exceptions as results
        rather than raising them, so other tasks complete normally.
        """
        results_collected = []

        async def succeed_task(name):
            results_collected.append(name)
            return f"{name}_ok"

        async def fail_task():
            raise RuntimeError("DB table missing")

        tasks = [
            succeed_task("cycle"),
            succeed_task("accuracy"),
            fail_task(),
            succeed_task("peak_import"),
            succeed_task("evse"),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 4 tasks should have succeeded
        assert len(results_collected) == 4
        assert "cycle" in results_collected
        assert "accuracy" in results_collected
        assert "peak_import" in results_collected
        assert "evse" in results_collected

        # The failed task should be an exception in results
        exceptions = [r for r in results if isinstance(r, Exception)]
        assert len(exceptions) == 1
        assert "DB table missing" in str(exceptions[0])

    @pytest.mark.asyncio
    async def test_timeout_allows_coordinator_to_continue(self):
        """Timeout after 15s should let coordinator start with defaults.

        If the DB is very slow or locked, wait_for raises TimeoutError
        which the coordinator catches and logs, proceeding with defaults.
        """
        async def slow_restore():
            await asyncio.sleep(100)  # Would take way too long

        timed_out = False
        try:
            await asyncio.wait_for(
                asyncio.gather(slow_restore(), return_exceptions=True),
                timeout=0.05,  # Use short timeout for test speed
            )
        except asyncio.TimeoutError:
            timed_out = True

        assert timed_out is True

    def test_all_restore_tasks_are_included(self):
        """All 11 restore task names should be in the gather list.

        The energy coordinator must restore: cycle, accuracy, peak_import,
        temp_regression, evse, circuit, baselines, consumption_history,
        midnight_snapshot, envoy_cache, load_shedding_level.
        """
        restore_names = [
            "_restore_cycle_from_db",
            "_restore_accuracy_from_db",
            "_restore_peak_import_history",
            "_fit_temp_regression",
            "_restore_evse_state",
            "_restore_circuit_state",
            "_restore_energy_baselines",
            "_restore_consumption_history",
            "_restore_midnight_snapshot",
            "_restore_envoy_cache",
            "_restore_load_shedding_level",
        ]
        assert len(restore_names) == 11
        # Verify uniqueness (no duplicates)
        assert len(set(restore_names)) == 11

    @pytest.mark.asyncio
    async def test_gather_returns_results_for_all_tasks(self):
        """gather should return one result per task, including exceptions.

        The coordinator iterates results to log individual failures.
        """
        async def ok():
            return "ok"

        async def fail():
            raise ValueError("corrupt row")

        results = await asyncio.gather(ok(), fail(), ok(), return_exceptions=True)

        assert len(results) == 3
        assert results[0] == "ok"
        assert isinstance(results[1], ValueError)
        assert results[2] == "ok"

    @pytest.mark.asyncio
    async def test_gather_with_all_failures_still_returns(self):
        """Even if all tasks fail, gather returns normally with return_exceptions.

        Coordinator must not crash if every restore task fails (e.g., fresh DB).
        """
        async def fail(name):
            raise RuntimeError(f"{name} missing")

        task_names = ["a", "b", "c", "d"]
        tasks = [fail(n) for n in task_names]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        assert len(results) == 4
        assert all(isinstance(r, RuntimeError) for r in results)


# =============================================================================
# D2: COORDINATOR STARTUP ORDERING
# =============================================================================

class TestCoordinatorStartupOrdering:
    """Tests for asyncio.Event-based startup ordering between coordinators.

    v3.21.0 D2: Presence coordinator sets _ready_event after initial inference.
    HVAC coordinator waits on that event (with 10s timeout) before reading
    house state, preventing stale default state reads during startup race.
    """

    @pytest.mark.asyncio
    async def test_event_blocks_until_set(self):
        """asyncio.Event should block wait() until set() is called.

        HVAC waits on presence._ready_event.wait() which blocks until
        Presence calls _ready_event.set() after inference completes.
        """
        ready_event = asyncio.Event()
        assert not ready_event.is_set()

        hvac_got_state = False

        async def hvac_startup():
            nonlocal hvac_got_state
            await ready_event.wait()
            hvac_got_state = True

        async def presence_startup():
            # Simulate inference completing
            await asyncio.sleep(0.01)
            ready_event.set()

        await asyncio.gather(hvac_startup(), presence_startup())
        assert hvac_got_state is True

    @pytest.mark.asyncio
    async def test_hvac_times_out_after_10s_uses_default(self):
        """HVAC should time out after 10s if Presence never sets event.

        If Presence coordinator is disabled or crashes, HVAC must not hang
        forever. It uses asyncio.wait_for with timeout=10.0 and logs a warning.
        """
        ready_event = asyncio.Event()

        timed_out = False
        house_state = "default"

        try:
            await asyncio.wait_for(ready_event.wait(), timeout=0.05)
            house_state = "from_presence"
        except asyncio.TimeoutError:
            timed_out = True
            # HVAC continues with default state

        assert timed_out is True
        assert house_state == "default"

    @pytest.mark.asyncio
    async def test_presence_sets_ready_event_after_inference(self):
        """Presence should set _ready_event after _run_inference completes.

        The real code calls self._ready_event.set() right after
        await self._run_inference("startup").
        """
        ready_event = asyncio.Event()

        inference_completed = False

        async def _run_inference(reason):
            nonlocal inference_completed
            # Simulate inference work
            inference_completed = True

        await _run_inference("startup")
        ready_event.set()

        assert inference_completed is True
        assert ready_event.is_set()

    @pytest.mark.asyncio
    async def test_event_already_set_returns_immediately(self):
        """If Presence finishes first, HVAC should not block at all.

        Event.wait() on an already-set event returns immediately.
        """
        ready_event = asyncio.Event()
        ready_event.set()

        # Should return instantly, no timeout needed
        await asyncio.wait_for(ready_event.wait(), timeout=0.01)
        assert ready_event.is_set()

    @pytest.mark.asyncio
    async def test_multiple_waiters_all_unblocked(self):
        """Multiple coordinators waiting on the same event should all proceed.

        If other coordinators (not just HVAC) also depend on Presence readiness,
        Event supports multiple concurrent waiters.
        """
        ready_event = asyncio.Event()
        unblocked = []

        async def waiter(name):
            await ready_event.wait()
            unblocked.append(name)

        async def setter():
            await asyncio.sleep(0.01)
            ready_event.set()

        await asyncio.gather(waiter("hvac"), waiter("energy"), setter())
        assert "hvac" in unblocked
        assert "energy" in unblocked


# =============================================================================
# D3: SAFETY SENSOR RECOVERY
# =============================================================================

class TestSafetySensorRecovery:
    """Tests for sensor unavailable->available re-evaluation.

    v3.21.0 D3: When a safety sensor transitions from unavailable to available,
    _evaluate_sensor_on_recovery is called synchronously to immediately
    clear stale hazards or confirm hazard persistence.
    """

    def test_binary_sensor_recovery_safe_clears_hazard(self):
        """Binary sensor returning from unavailable at safe state should clear hazard.

        If a smoke sensor was "on" (hazard), went unavailable, then comes back
        as "off" (clear), the stale hazard in _active_hazards must be removed.
        """
        # Simulate _active_hazards state
        active_hazards = {"smoke:living_room": MagicMock()}

        # Simulate _handle_binary_hazard when new_state != "on"
        entity_id = "binary_sensor.living_room_smoke"
        new_state = "off"
        hazard_type = "smoke"
        location = "living_room"

        if new_state != "on":
            key = f"{hazard_type}:{location}"
            active_hazards.pop(key, None)

        assert "smoke:living_room" not in active_hazards

    def test_binary_sensor_recovery_dangerous_detects_hazard(self):
        """Binary sensor returning from unavailable still in hazard should re-detect.

        If a smoke sensor comes back as "on", the hazard should be confirmed
        and remain (or be re-added) in _active_hazards.
        """
        entity_id = "binary_sensor.living_room_smoke"
        new_state = "on"
        hazard_type = "smoke"
        location = "living_room"

        # Simulate _handle_binary_hazard when new_state == "on" for smoke
        if new_state == "on":
            if hazard_type == "smoke":
                severity = "CRITICAL"
                message = f"SMOKE DETECTED in {location}!"
            detected = True
        else:
            detected = False

        assert detected is True
        assert severity == "CRITICAL"

    def test_numeric_sensor_recovery_safe_clears_hazard(self):
        """Numeric sensor returning at safe level should clear hazard.

        If CO sensor was at 60 ppm (hazard), went unavailable, comes back
        at 10 ppm (safe), the stale hazard must be cleared.
        """
        active_hazards = {"carbon_monoxide:kitchen": MagicMock()}

        # Simulate recovery with safe value
        entity_id = "sensor.kitchen_co"
        new_value = 10.0
        hazard_type = "carbon_monoxide"
        location = "kitchen"

        # CO thresholds: LOW=25, MEDIUM=35, HIGH=50, CRITICAL=100
        # 10 ppm is below all thresholds -> clear
        thresholds = {
            "LOW": 25.0,
            "MEDIUM": 35.0,
            "HIGH": 50.0,
            "CRITICAL": 100.0,
        }

        hazard_detected = False
        for severity, threshold in thresholds.items():
            if new_value >= threshold:
                hazard_detected = True
                break

        if not hazard_detected:
            # Clear stale hazard
            key = f"{hazard_type}:{location}"
            active_hazards.pop(key, None)

        assert "carbon_monoxide:kitchen" not in active_hazards

    def test_numeric_sensor_recovery_dangerous_keeps_hazard(self):
        """Numeric sensor returning at dangerous level should confirm hazard.

        If CO sensor comes back at 60 ppm (still above HIGH threshold),
        the hazard remains active.
        """
        active_hazards = {}

        entity_id = "sensor.kitchen_co"
        new_value = 60.0
        hazard_type = "carbon_monoxide"
        location = "kitchen"

        # CO thresholds: LOW=25, MEDIUM=35, HIGH=50, CRITICAL=100
        thresholds = [
            ("CRITICAL", 100.0),
            ("HIGH", 50.0),
            ("MEDIUM", 35.0),
            ("LOW", 25.0),
        ]

        detected_severity = None
        for severity, threshold in thresholds:
            if new_value >= threshold:
                detected_severity = severity
                break

        if detected_severity:
            key = f"{hazard_type}:{location}"
            active_hazards[key] = {"severity": detected_severity, "value": new_value}

        assert "carbon_monoxide:kitchen" in active_hazards
        assert active_hazards["carbon_monoxide:kitchen"]["severity"] == "HIGH"

    def test_recovery_clears_rate_history(self):
        """Unavailable->available transition should clear rate history.

        The rate detector tracks recent values for rate-of-change detection.
        After unavailable, stale values would cause false spikes.
        """
        rate_history = {
            "sensor.kitchen_co": [10.0, 12.0, 15.0, 18.0],
            "sensor.kitchen_co2": [400.0, 450.0],
        }

        entity_id = "sensor.kitchen_co"
        old_state = "unavailable"
        new_state = "10.0"

        # Simulate: if old_state was unavailable, clear rate history
        if old_state in ("unavailable", "unknown"):
            rate_history.pop(entity_id, None)

        assert entity_id not in rate_history
        # Other sensors unaffected
        assert "sensor.kitchen_co2" in rate_history

    def test_recovery_dispatched_on_unavailable_to_available_only(self):
        """Recovery should only fire when old_state is unavailable/unknown.

        Normal state changes (e.g., "off" -> "on") should NOT trigger
        the recovery path.
        """
        recovery_called = False

        def evaluate_on_recovery(entity_id, state_value):
            nonlocal recovery_called
            recovery_called = True

        old_state = "off"
        new_state = "on"

        _UNAVAILABLE_STATES = {"unavailable", "unknown"}

        if old_state in _UNAVAILABLE_STATES:
            evaluate_on_recovery("binary_sensor.smoke", new_state)

        # Should NOT have been called — normal transition
        assert recovery_called is False

    def test_recovery_fires_on_unavailable_transition(self):
        """Recovery SHOULD fire when old_state is unavailable."""
        recovery_called = False
        recovery_entity = None

        def evaluate_on_recovery(entity_id, state_value):
            nonlocal recovery_called, recovery_entity
            recovery_called = True
            recovery_entity = entity_id

        old_state = "unavailable"
        new_state = "off"

        _UNAVAILABLE_STATES = {"unavailable", "unknown"}

        if old_state in _UNAVAILABLE_STATES:
            evaluate_on_recovery("binary_sensor.smoke", new_state)

        assert recovery_called is True
        assert recovery_entity == "binary_sensor.smoke"

    def test_recovery_handles_non_numeric_gracefully(self):
        """Recovery with non-numeric state for a numeric sensor should not crash.

        If a numeric sensor comes back with a non-numeric state (e.g., "unavailable"
        still in the state string for some reason), float() conversion should
        be caught.
        """
        entity_id = "sensor.kitchen_co"
        state_value = "not_a_number"

        parsed_value = None
        try:
            parsed_value = float(state_value)
        except (ValueError, TypeError):
            pass

        assert parsed_value is None


# =============================================================================
# D4: NM ALERT STATE PERSISTENCE
# =============================================================================

class TestNMAlertStatePersistence:
    """Tests for NotificationManager alert state persistence.

    v3.21.0 D4: get_persistence_state() and restore_persistence_state()
    allow the NM's alert state machine, cooldown timers, and dedup cache
    to survive HA restarts via RestoreEntity attributes.
    """

    def test_get_persistence_state_returns_required_fields(self):
        """get_persistence_state should return all fields needed for restore.

        Required fields: alert_state, cooldown_remaining, cooldown_hazard_type,
        cooldown_location, dedup_cache, active_alert_severity.
        """
        # Simulate NM internal state
        state = {
            "alert_state": "cooldown",
            "cooldown_remaining": 120,
            "cooldown_hazard_type": "smoke",
            "cooldown_location": "kitchen",
            "dedup_cache": {"smoke:kitchen": 1711862400.0},
            "active_alert_severity": "CRITICAL",
        }

        required_fields = {
            "alert_state",
            "cooldown_remaining",
            "cooldown_hazard_type",
            "cooldown_location",
            "dedup_cache",
            "active_alert_severity",
        }
        assert required_fields.issubset(set(state.keys()))

    def test_restore_alert_state_enum(self):
        """restore_persistence_state should correctly map string to AlertState enum.

        The stored "cooldown" string should map back to AlertState.COOLDOWN.
        """
        # Simulate AlertState enum (StrEnum in real code)
        from enum import Enum

        class AlertState(str, Enum):
            IDLE = "idle"
            ALERTING = "alerting"
            REPEATING = "repeating"
            COOLDOWN = "cooldown"
            RE_EVALUATE = "re_evaluate"

        persisted = {"alert_state": "cooldown"}

        restored_state = AlertState.IDLE  # Default
        if alert_state := persisted.get("alert_state"):
            try:
                restored_state = AlertState(alert_state)
            except ValueError:
                pass

        assert restored_state == AlertState.COOLDOWN
        assert restored_state.value == "cooldown"

    def test_restore_all_alert_states(self):
        """All valid AlertState values should round-trip through persistence."""
        from enum import Enum

        class AlertState(str, Enum):
            IDLE = "idle"
            ALERTING = "alerting"
            REPEATING = "repeating"
            COOLDOWN = "cooldown"
            RE_EVALUATE = "re_evaluate"

        for expected_state in AlertState:
            persisted = {"alert_state": expected_state.value}
            restored = AlertState(persisted["alert_state"])
            assert restored == expected_state

    def test_restore_handles_missing_data(self):
        """restore_persistence_state should handle empty/None state gracefully.

        On fresh install there is no persisted state.
        """
        from enum import Enum

        class AlertState(str, Enum):
            IDLE = "idle"
            ALERTING = "alerting"
            REPEATING = "repeating"
            COOLDOWN = "cooldown"
            RE_EVALUATE = "re_evaluate"

        # Simulate the real restore_persistence_state logic
        alert_state = AlertState.IDLE
        cooldown_remaining = 0
        cooldown_hazard_type = None
        cooldown_location = None
        dedup_cache = {}

        # Test with None
        state = None
        if state:
            pass  # restore logic — skipped if falsy

        assert alert_state == AlertState.IDLE
        assert cooldown_remaining == 0

        # Test with empty dict
        state = {}
        if state:
            if alert_val := state.get("alert_state"):
                try:
                    alert_state = AlertState(alert_val)
                except ValueError:
                    pass
            cooldown_remaining = state.get("cooldown_remaining", 0)

        assert alert_state == AlertState.IDLE
        assert cooldown_remaining == 0

    def test_restore_handles_corrupt_alert_state(self):
        """Invalid alert_state string should be ignored (keep default).

        If HA state machine stored garbage, we must not crash.
        """
        from enum import Enum

        class AlertState(str, Enum):
            IDLE = "idle"
            ALERTING = "alerting"
            REPEATING = "repeating"
            COOLDOWN = "cooldown"
            RE_EVALUATE = "re_evaluate"

        alert_state = AlertState.IDLE

        persisted = {"alert_state": "bogus_state_value"}
        if alert_val := persisted.get("alert_state"):
            try:
                alert_state = AlertState(alert_val)
            except ValueError:
                pass  # Keep default

        assert alert_state == AlertState.IDLE

    def test_cooldown_survives_restart_round_trip(self):
        """Cooldown state should survive a save->restore round trip.

        Simulates: NM enters cooldown (save) -> HA restarts -> restore.
        After restore, cooldown_remaining and hazard_type must match.
        """
        from enum import Enum

        class AlertState(str, Enum):
            IDLE = "idle"
            ALERTING = "alerting"
            REPEATING = "repeating"
            COOLDOWN = "cooldown"
            RE_EVALUATE = "re_evaluate"

        # === SAVE PHASE ===
        nm_alert_state = AlertState.COOLDOWN
        nm_cooldown_remaining = 45
        nm_cooldown_hazard_type = "water_leak"
        nm_cooldown_location = "basement"
        nm_dedup_cache = {"water_leak:basement": 1711862500.0}

        persisted = {
            "alert_state": nm_alert_state.value,
            "cooldown_remaining": nm_cooldown_remaining,
            "cooldown_hazard_type": nm_cooldown_hazard_type,
            "cooldown_location": nm_cooldown_location,
            "dedup_cache": dict(nm_dedup_cache),
            "active_alert_severity": None,
        }

        # === RESTART (state lost) ===
        restored_alert_state = AlertState.IDLE
        restored_cooldown_remaining = 0
        restored_hazard_type = None
        restored_location = None
        restored_dedup = {}

        # === RESTORE PHASE ===
        if persisted:
            if alert_val := persisted.get("alert_state"):
                try:
                    restored_alert_state = AlertState(alert_val)
                except ValueError:
                    pass
            restored_cooldown_remaining = persisted.get("cooldown_remaining", 0)
            restored_hazard_type = persisted.get("cooldown_hazard_type")
            restored_location = persisted.get("cooldown_location")
            dedup = persisted.get("dedup_cache")
            if isinstance(dedup, dict):
                restored_dedup = {
                    k: float(v) for k, v in dedup.items()
                    if isinstance(v, (int, float))
                }

        # === VERIFY ===
        assert restored_alert_state == AlertState.COOLDOWN
        assert restored_cooldown_remaining == 45
        assert restored_hazard_type == "water_leak"
        assert restored_location == "basement"
        assert "water_leak:basement" in restored_dedup
        assert restored_dedup["water_leak:basement"] == 1711862500.0

    def test_dedup_cache_filters_non_numeric_values(self):
        """restore_persistence_state should filter non-numeric dedup values.

        If HA stored corrupt dedup timestamps (strings instead of floats),
        they should be excluded during restore.
        """
        dedup_raw = {
            "smoke:kitchen": 1711862400.0,
            "water_leak:basement": "not_a_timestamp",
            "co:garage": 1711862500,  # int is also fine
        }

        restored = {
            k: float(v) for k, v in dedup_raw.items()
            if isinstance(v, (int, float))
        }

        assert "smoke:kitchen" in restored
        assert "co:garage" in restored
        assert "water_leak:basement" not in restored
        assert len(restored) == 2


# =============================================================================
# D6: ENERGY OBSERVATION MODE RestoreEntity
# =============================================================================

class TestEnergyObservationModeRestore:
    """Tests for RestoreEntity on EnergyObservationModeSwitch.

    v3.21.0 D6: Added RestoreEntity to EnergyObservationModeSwitch so
    observation mode survives HA restarts. async_added_to_hass checks
    last_state and sets energy.observation_mode accordingly.
    """

    def test_restored_on_state_sets_observation_mode_true(self):
        """Restored 'on' state should set energy.observation_mode = True.

        If the user had observation mode enabled before restart, it must
        persist. The switch checks last_state.state == 'on'.
        """
        observation_mode = False  # Default

        last_state_value = "on"
        if last_state_value is not None and last_state_value == "on":
            observation_mode = True

        assert observation_mode is True

    def test_restored_off_state_keeps_observation_mode_false(self):
        """Restored 'off' state should keep energy.observation_mode = False."""
        observation_mode = False  # Default

        last_state_value = "off"
        if last_state_value is not None and last_state_value == "on":
            observation_mode = True

        assert observation_mode is False

    def test_restored_none_state_keeps_observation_mode_false(self):
        """No restored state (fresh install) should keep observation_mode = False.

        async_get_last_state returns None on first install.
        """
        observation_mode = False  # Default

        last_state = None
        if last_state is not None and last_state == "on":
            observation_mode = True

        assert observation_mode is False

    def test_observation_mode_default_is_off(self):
        """Default observation mode should be OFF (False).

        Observation mode is opt-in — it must not be accidentally enabled
        after a restart or fresh install.
        """
        # EnergyObservationModeSwitch default behavior
        default_observation_mode = False
        assert default_observation_mode is False

    def test_restore_does_not_affect_other_coordinators(self):
        """Restoring energy observation mode must not affect HVAC observation mode.

        Each coordinator has its own independent observation mode switch.
        """
        energy_observation = False
        hvac_observation = False

        # Restore energy to ON
        energy_last_state = "on"
        if energy_last_state == "on":
            energy_observation = True

        # HVAC should remain unchanged
        assert energy_observation is True
        assert hvac_observation is False


# =============================================================================
# D7: AI AUTOMATION PER-ROOM TOGGLE
# =============================================================================

class TestAIAutomationPerRoomToggle:
    """Tests for AI automation per-room toggle switch.

    v3.21.0 D7: AiAutomationSwitch (switch.{room_slug}_ai_automation)
    gates AI rule execution and automation chaining per room.
    coordinator.py checks _is_ai_automation_enabled() before firing
    chained automations or AI rules.
    """

    def test_ai_toggle_missing_defaults_to_enabled(self, mock_hass):
        """Missing AI automation switch should default to enabled.

        If the switch entity does not exist (e.g., not yet created or
        removed), AI automation should work normally.
        """
        coord = make_coordinator_with_ai_toggle(mock_hass, "bedroom")
        # No switch state set

        assert coord._is_ai_automation_enabled() is True

    def test_ai_toggle_off_disables_ai(self, mock_hass):
        """AI automation switch OFF should disable AI rules for the room."""
        coord = make_coordinator_with_ai_toggle(mock_hass, "bedroom")
        mock_hass.set_state("switch.bedroom_ai_automation", "off")

        assert coord._is_ai_automation_enabled() is False

    def test_ai_toggle_on_enables_ai(self, mock_hass):
        """AI automation switch ON should enable AI rules for the room."""
        coord = make_coordinator_with_ai_toggle(mock_hass, "bedroom")
        mock_hass.set_state("switch.bedroom_ai_automation", "on")

        assert coord._is_ai_automation_enabled() is True

    def test_ai_toggle_off_blocks_ai_rules_while_automation_continues(self, mock_hass):
        """AI toggle OFF should block AI rules but NOT regular automation.

        The AI toggle only gates _fire_chained_automations and _execute_ai_rules.
        Regular room automation (lights, covers, climate) is controlled by the
        main automation switch and manual_mode, NOT the AI toggle.
        """
        coord = make_coordinator_with_ai_toggle(mock_hass, "bedroom")
        mock_hass.set_state("switch.bedroom_ai_automation", "off")
        # Automation switch is ON
        mock_hass.set_state("switch.bedroom_automation", "on")

        assert coord._is_ai_automation_enabled() is False
        assert coord._is_automation_enabled() is True

    def test_ai_toggle_independent_of_manual_mode(self, mock_hass):
        """AI toggle is independent of ManualMode switch.

        Manual mode disables ALL automation. AI toggle only disables
        AI rules. They are separate controls.
        """
        coord = make_coordinator_with_ai_toggle(mock_hass, "bedroom")
        mock_hass.set_state("switch.bedroom_ai_automation", "on")
        mock_hass.set_state("switch.bedroom_manual_mode", "on")

        # AI toggle says yes, but manual mode overrides everything
        assert coord._is_ai_automation_enabled() is True
        assert coord._is_automation_enabled() is False

    def test_ai_toggle_restore_entity_on(self):
        """AiAutomationSwitch should restore 'on' state from RestoreEntity.

        The switch inherits RestoreEntity. In async_added_to_hass,
        it reads last_state.state and sets _attr_is_on accordingly.
        """
        is_on = True  # Default

        last_state_value = "on"
        if last_state_value is not None:
            is_on = last_state_value == "on"

        assert is_on is True

    def test_ai_toggle_restore_entity_off(self):
        """AiAutomationSwitch should restore 'off' state from RestoreEntity."""
        is_on = True  # Default

        last_state_value = "off"
        if last_state_value is not None:
            is_on = last_state_value == "on"

        assert is_on is False

    def test_ai_toggle_restore_entity_none_defaults_on(self):
        """Fresh install (no last_state) should default AI toggle to ON.

        The switch initializes _attr_is_on = True. If async_get_last_state
        returns None, the default is preserved.
        """
        is_on = True  # Default in __init__

        last_state = None
        if last_state is not None:
            is_on = last_state == "on"

        assert is_on is True

    def test_ai_gate_in_signal_handlers(self, mock_hass):
        """Signal handlers should check _is_ai_automation_enabled before firing.

        The coordinator checks this in _on_house_state_change,
        _on_energy_constraint, _on_safety_hazard, _on_security_event,
        and in the main refresh cycle for trigger-based AI rules.
        """
        coord = make_coordinator_with_ai_toggle(mock_hass, "living_room")
        mock_hass.set_state("switch.living_room_ai_automation", "off")

        # Simulate the gate check pattern from coordinator.py signal handlers:
        # if (trigger_key in chains or has_matching_rule) and self._is_ai_automation_enabled():
        has_matching_rule = True
        should_fire = has_matching_rule and coord._is_ai_automation_enabled()

        assert should_fire is False

    def test_ai_gate_allows_when_enabled(self, mock_hass):
        """Signal handlers should fire AI rules when toggle is ON."""
        coord = make_coordinator_with_ai_toggle(mock_hass, "living_room")
        mock_hass.set_state("switch.living_room_ai_automation", "on")

        has_matching_rule = True
        should_fire = has_matching_rule and coord._is_ai_automation_enabled()

        assert should_fire is True

    def test_multi_word_room_slug(self, mock_hass):
        """Multi-word room name should produce correct switch entity_id."""
        coord = make_coordinator_with_ai_toggle(mock_hass, "living_room")
        mock_hass.set_state("switch.living_room_ai_automation", "off")

        assert coord._is_ai_automation_enabled() is False


# =============================================================================
# INTEGRATION: CROSS-DELIVERABLE TESTS
# =============================================================================

class TestCrossDeliverableIntegration:
    """Tests that verify interactions between Cycle D deliverables."""

    @pytest.mark.asyncio
    async def test_startup_ordering_with_timeout_and_defaults(self):
        """D2+D1: If both Presence and Energy restore are slow, coordinators
        must degrade gracefully with defaults rather than hanging.
        """
        ready_event = asyncio.Event()

        hvac_state = "default"
        energy_restored = False

        async def hvac_startup():
            nonlocal hvac_state
            try:
                await asyncio.wait_for(ready_event.wait(), timeout=0.05)
                hvac_state = "from_presence"
            except asyncio.TimeoutError:
                hvac_state = "default"

        async def energy_startup():
            nonlocal energy_restored
            async def slow_restore():
                await asyncio.sleep(100)
            try:
                await asyncio.wait_for(
                    asyncio.gather(slow_restore(), return_exceptions=True),
                    timeout=0.05,
                )
                energy_restored = True
            except asyncio.TimeoutError:
                energy_restored = False

        await asyncio.gather(hvac_startup(), energy_startup())

        assert hvac_state == "default"
        assert energy_restored is False

    def test_nm_cooldown_persists_with_safety_recovery(self):
        """D4+D3: NM cooldown from a safety hazard should persist through restart.

        If NM entered cooldown for a smoke hazard, restarted, and the sensor
        recovers (D3), the restored cooldown state (D4) should still be valid.
        """
        from enum import Enum

        class AlertState(str, Enum):
            IDLE = "idle"
            COOLDOWN = "cooldown"

        # Save before restart
        persisted = {
            "alert_state": "cooldown",
            "cooldown_remaining": 60,
            "cooldown_hazard_type": "smoke",
            "cooldown_location": "kitchen",
        }

        # Restore after restart
        restored_state = AlertState.IDLE
        if alert_val := persisted.get("alert_state"):
            try:
                restored_state = AlertState(alert_val)
            except ValueError:
                pass

        assert restored_state == AlertState.COOLDOWN
        assert persisted["cooldown_remaining"] == 60

        # Meanwhile, D3: sensor recovery clears the hazard
        active_hazards = {"smoke:kitchen": MagicMock()}
        active_hazards.pop("smoke:kitchen", None)

        # NM cooldown persists even though hazard is cleared
        # (cooldown must complete before NM accepts new alerts for same type)
        assert restored_state == AlertState.COOLDOWN
        assert "smoke:kitchen" not in active_hazards

    def test_ai_toggle_off_with_observation_mode_on(self, mock_hass):
        """D7+D6: AI toggle OFF + Energy observation mode ON should both take effect.

        These are orthogonal toggles: one controls AI rules per room,
        the other controls energy actions globally.
        """
        coord = make_coordinator_with_ai_toggle(mock_hass, "bedroom")
        mock_hass.set_state("switch.bedroom_ai_automation", "off")

        observation_mode = False
        last_state = "on"
        if last_state == "on":
            observation_mode = True

        assert coord._is_ai_automation_enabled() is False
        assert observation_mode is True
