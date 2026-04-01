"""Tests for v3.22.1 LOW severity cleanup — 12 fixes.

Covers:
1.  UTC consistency in save_room_state (dt_util.now().isoformat())
2.  Override switch slug DRY helper (_room_switch_entity_id)
3.  Cooldown sensor rename ("N recent" + max_remaining_seconds)
4.  Envoy sensor signal listener (SIGNAL_ENERGY_ENTITIES_UPDATE + async_added_to_hass)
5.  Music task tracking (_pending_tasks set, teardown cleanup)
6.  Emergency load shed de-escalation logic exists
7.  CO unlocks egress (security _handle_safety_hazard tuple includes carbon_monoxide)
8.  Unused imports removed (_stop_all_fans_safety only imports CONF_FANS)
9.  Dry-run observation mode debug logs
10. Disabled coordinator guard (signal handlers check _enabled first)
11. CM entry caching (_get_signal_config uses _cm_entry_cache)
12. Switch restore deferred retry (observation mode switches have _deferred_restore + _retry_restore)

TESTING METHODOLOGY:
Tests verify decision logic directly using MockHass/MockCoordinator fixtures.
No heavy HA module mocking. Each test is self-contained.
"""
import ast
import inspect
import textwrap
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, AsyncMock
from tests.conftest import MockHass, MockConfigEntry

DOMAIN = "universal_room_automation"
CONF_ENTRY_TYPE = "entry_type"
ENTRY_TYPE_COORDINATOR_MANAGER = "coordinator_manager"


# =============================================================================
# HELPERS
# =============================================================================

def _get_signal_config(hass, key, default=False):
    """Replicate BaseCoordinator._get_signal_config logic for testing."""
    cm_entry = None
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_COORDINATOR_MANAGER:
            cm_entry = entry
            break
    if cm_entry is None:
        return default
    config = {**cm_entry.data, **cm_entry.options}
    return config.get(key, default)


def make_mock_hass_with_cm_entry(signal_options=None):
    """Create a MockHass with a Coordinator Manager config entry."""
    hass = MockHass()
    cm_entry = MagicMock()
    cm_entry.data = {CONF_ENTRY_TYPE: ENTRY_TYPE_COORDINATOR_MANAGER}
    cm_entry.options = signal_options or {}
    hass.config_entries.async_entries = MagicMock(return_value=[cm_entry])
    hass.async_create_task = MagicMock(return_value=MagicMock())
    return hass


# =============================================================================
# 1. UTC CONSISTENCY — save_room_state uses dt_util.now().isoformat()
# =============================================================================

class TestUTCConsistency:
    """Verify save_room_state updated_at uses local time via dt_util.now()."""

    def test_save_room_state_uses_local_time_pattern(self):
        """The save_room_state SQL should use dt_util.now().isoformat() for updated_at.

        v3.22.1 changed from utcnow() to now() for consistency with local-aware
        timestamps throughout the codebase.
        """
        import importlib
        src_path = (
            "custom_components/universal_room_automation/database.py"
        )
        with open(src_path) as f:
            source = f.read()

        # Locate the save_room_state method
        assert "async def save_room_state" in source, (
            "save_room_state method not found in database.py"
        )

        # Extract the method body
        start = source.index("async def save_room_state")
        # Find the line with updated_at value
        method_body = source[start:start + 1500]

        # Should use dt_util.now().isoformat() — local time, not utcnow()
        assert "dt_util.now().isoformat()" in method_body, (
            "save_room_state should use dt_util.now().isoformat() for updated_at"
        )
        # Should NOT use utcnow for this specific field
        # (Check the tuple that feeds the SQL values)
        sql_tuple_start = method_body.index("room_id,")
        sql_tuple_end = method_body.index(")", sql_tuple_start + 200)
        sql_tuple = method_body[sql_tuple_start:sql_tuple_end]
        assert "utcnow" not in sql_tuple, (
            "save_room_state updated_at should NOT use utcnow"
        )


# =============================================================================
# 2. OVERRIDE SWITCH SLUG DRY — _room_switch_entity_id helper
# =============================================================================

class TestOverrideSwitchSlug:
    """Verify _room_switch_entity_id helper produces correct slugs."""

    def _make_coordinator(self, room_name):
        """Create a mock coordinator with a given room name."""
        entry = MockConfigEntry(data={"room_name": room_name})
        coord = MagicMock()
        coord.entry = entry
        return coord

    def _room_switch_entity_id(self, coordinator, suffix):
        """Replicate the helper from switch.py."""
        slug = coordinator.entry.data.get("room_name", "unknown").lower().replace(" ", "_")
        return f"switch.{slug}_{suffix}"

    def test_simple_room_name(self):
        """Single-word room name produces expected slug."""
        coord = self._make_coordinator("Bedroom")
        result = self._room_switch_entity_id(coord, "override_vacant")
        assert result == "switch.bedroom_override_vacant"

    def test_multi_word_room_name(self):
        """Multi-word room name converts spaces to underscores."""
        coord = self._make_coordinator("Back Hallway")
        result = self._room_switch_entity_id(coord, "override_occupied")
        assert result == "switch.back_hallway_override_occupied"

    def test_already_lowercase(self):
        """Already-lowercase name is unchanged."""
        coord = self._make_coordinator("kitchen")
        result = self._room_switch_entity_id(coord, "manual_mode")
        assert result == "switch.kitchen_manual_mode"

    def test_missing_room_name_falls_back(self):
        """Missing room_name falls back to 'unknown'."""
        coord = MagicMock()
        coord.entry = MockConfigEntry(data={})
        result = self._room_switch_entity_id(coord, "automation")
        assert result == "switch.unknown_automation"

    def test_helper_exists_in_source(self):
        """_room_switch_entity_id function exists in switch.py."""
        src_path = "custom_components/universal_room_automation/switch.py"
        with open(src_path) as f:
            source = f.read()
        assert "def _room_switch_entity_id(" in source


# =============================================================================
# 3. COOLDOWN SENSOR RENAME — "N recent" not "N active", max_remaining_seconds
# =============================================================================

class TestCooldownSensorRename:
    """Verify SafetyActiveCooldownsSensor uses 'recent' and max_remaining_seconds."""

    def _compute_native_value(self, last_alerts, now):
        """Replicate SafetyActiveCooldownsSensor.native_value logic."""
        if not last_alerts:
            return "none"

        active_count = 0
        for key, last_time in last_alerts.items():
            if isinstance(last_time, datetime):
                age = (now - last_time).total_seconds()
                if age < 3600:
                    active_count += 1

        if active_count == 0:
            return "none"
        return f"{active_count} recent"

    def _compute_attributes(self, last_alerts, now):
        """Replicate SafetyActiveCooldownsSensor.extra_state_attributes logic."""
        if not last_alerts:
            return {"cooldowns": {}}

        cooldowns = {}
        for key, last_time in last_alerts.items():
            if not isinstance(last_time, datetime):
                continue
            age = (now - last_time).total_seconds()
            if age < 3600:
                remaining = max(0, 3600 - age)
                cooldowns[key] = {
                    "last_alert": last_time.isoformat(),
                    "age_seconds": round(age, 1),
                    "max_remaining_seconds": round(remaining, 1),
                }
        return {"cooldowns": cooldowns}

    def test_state_says_recent_not_active(self):
        """State value uses 'recent' not 'active'."""
        now = datetime(2026, 3, 31, 12, 0, 0, tzinfo=timezone.utc)
        alerts = {
            "smoke:kitchen": now - timedelta(minutes=5),
            "water_leak:bathroom": now - timedelta(minutes=10),
        }
        value = self._compute_native_value(alerts, now)
        assert "recent" in value
        assert "active" not in value
        assert value == "2 recent"

    def test_single_alert_recent(self):
        """Single alert within window shows '1 recent'."""
        now = datetime(2026, 3, 31, 12, 0, 0, tzinfo=timezone.utc)
        alerts = {"co:garage": now - timedelta(minutes=30)}
        value = self._compute_native_value(alerts, now)
        assert value == "1 recent"

    def test_expired_alert_shows_none(self):
        """Alert older than 1 hour shows 'none'."""
        now = datetime(2026, 3, 31, 12, 0, 0, tzinfo=timezone.utc)
        alerts = {"smoke:kitchen": now - timedelta(hours=2)}
        value = self._compute_native_value(alerts, now)
        assert value == "none"

    def test_attribute_key_is_max_remaining(self):
        """Attribute uses max_remaining_seconds not remaining_seconds."""
        now = datetime(2026, 3, 31, 12, 0, 0, tzinfo=timezone.utc)
        alerts = {"smoke:kitchen": now - timedelta(minutes=10)}
        attrs = self._compute_attributes(alerts, now)
        cooldown_entry = attrs["cooldowns"]["smoke:kitchen"]
        assert "max_remaining_seconds" in cooldown_entry
        assert "remaining_seconds" not in cooldown_entry

    def test_max_remaining_seconds_value(self):
        """max_remaining_seconds is correct (3600 - age)."""
        now = datetime(2026, 3, 31, 12, 0, 0, tzinfo=timezone.utc)
        alerts = {"smoke:kitchen": now - timedelta(seconds=600)}
        attrs = self._compute_attributes(alerts, now)
        remaining = attrs["cooldowns"]["smoke:kitchen"]["max_remaining_seconds"]
        assert remaining == 3000.0  # 3600 - 600

    def test_source_uses_correct_keys(self):
        """Verify source code uses 'recent' in the state value template."""
        src_path = "custom_components/universal_room_automation/sensor.py"
        with open(src_path) as f:
            source = f.read()
        # The native_value property should produce "N recent"
        assert '"max_remaining_seconds"' in source
        assert 'recent"' in source


# =============================================================================
# 4. ENVOY SENSOR SIGNAL LISTENER
# =============================================================================

class TestEnvoySensorSignalListener:
    """Verify SIGNAL_ENERGY_ENTITIES_UPDATE exists and Envoy sensor subscribes."""

    def test_signal_constant_exists(self):
        """SIGNAL_ENERGY_ENTITIES_UPDATE is defined in signals.py."""
        src_path = "custom_components/universal_room_automation/domain_coordinators/signals.py"
        with open(src_path) as f:
            source = f.read()
        assert "SIGNAL_ENERGY_ENTITIES_UPDATE" in source
        # Must be a Final constant
        assert 'SIGNAL_ENERGY_ENTITIES_UPDATE: Final = "ura_energy_entities_update"' in source

    def test_envoy_sensor_has_async_added_to_hass(self):
        """EnergyEnvoyStatusSensor has async_added_to_hass subscribing to the signal."""
        src_path = "custom_components/universal_room_automation/sensor.py"
        with open(src_path) as f:
            source = f.read()

        # Find the class — need a large window because the class is ~3500 chars
        class_start = source.index("class EnergyEnvoyStatusSensor")
        # Find the next class to bound the search
        next_class = source.find("\nclass ", class_start + 1)
        if next_class == -1:
            next_class = len(source)
        class_body = source[class_start:next_class]
        assert "async_added_to_hass" in class_body
        assert "SIGNAL_ENERGY_ENTITIES_UPDATE" in class_body

    def test_envoy_sensor_handle_update_schedules_state(self):
        """_handle_update calls async_schedule_update_ha_state."""
        src_path = "custom_components/universal_room_automation/sensor.py"
        with open(src_path) as f:
            source = f.read()

        class_start = source.index("class EnergyEnvoyStatusSensor")
        next_class = source.find("\nclass ", class_start + 1)
        if next_class == -1:
            next_class = len(source)
        class_body = source[class_start:next_class]
        assert "async_schedule_update_ha_state" in class_body


# =============================================================================
# 5. MUSIC TASK TRACKING
# =============================================================================

class TestMusicTaskTracking:
    """Verify MusicFollowingCoordinator has _pending_tasks and cleans up in teardown."""

    def test_pending_tasks_initialized(self):
        """_pending_tasks is set() on init."""
        src_path = "custom_components/universal_room_automation/domain_coordinators/music_following.py"
        with open(src_path) as f:
            source = f.read()
        assert "self._pending_tasks: set[asyncio.Task] = set()" in source

    def test_tasks_tracked_on_create(self):
        """Tasks are added to _pending_tasks and registered with done callback."""
        src_path = "custom_components/universal_room_automation/domain_coordinators/music_following.py"
        with open(src_path) as f:
            source = f.read()
        assert "self._pending_tasks.add(task)" in source
        assert "task.add_done_callback(self._pending_tasks.discard)" in source

    def test_teardown_cancels_and_clears(self):
        """async_teardown cancels all pending tasks and clears the set."""
        src_path = "custom_components/universal_room_automation/domain_coordinators/music_following.py"
        with open(src_path) as f:
            source = f.read()

        teardown_start = source.index("async def async_teardown")
        teardown_body = source[teardown_start:teardown_start + 300]

        assert "task.cancel()" in teardown_body
        assert "self._pending_tasks.clear()" in teardown_body

    def test_teardown_iterates_over_list_copy(self):
        """Teardown iterates list(self._pending_tasks) to avoid set mutation."""
        src_path = "custom_components/universal_room_automation/domain_coordinators/music_following.py"
        with open(src_path) as f:
            source = f.read()

        teardown_start = source.index("async def async_teardown")
        teardown_body = source[teardown_start:teardown_start + 300]
        assert "list(self._pending_tasks)" in teardown_body


# =============================================================================
# 6. EMERGENCY LOAD SHED DE-ESCALATION
# =============================================================================

class TestEmergencyLoadShedDeescalation:
    """Verify load shedding de-escalation logic in the decision cycle."""

    def test_update_load_shedding_method_exists(self):
        """_update_load_shedding method exists in energy.py."""
        src_path = "custom_components/universal_room_automation/domain_coordinators/energy.py"
        with open(src_path) as f:
            source = f.read()
        assert "def _update_load_shedding(self, tou_period" in source

    def test_deescalation_logic_present(self):
        """De-escalation path exists: level decreases when not sustained."""
        src_path = "custom_components/universal_room_automation/domain_coordinators/energy.py"
        with open(src_path) as f:
            source = f.read()

        method_start = source.index("def _update_load_shedding(self, tou_period")
        # Method is ~4500 chars long — find the next method to bound the window
        next_def = source.find("\n    def ", method_start + 1)
        method_body = source[method_start:next_def if next_def != -1 else method_start + 5000]

        # De-escalation: level -= 1 when sustained is False
        assert "self._load_shedding_active_level -= 1" in method_body
        # Off-peak release
        assert "Load shedding released" in method_body
        # Grace period for restored levels
        assert "self._load_shedding_grace_cycles" in method_body

    def test_deescalation_releases_correct_target(self):
        """De-escalation releases the current level's target via _execute_shed_action(activate=False)."""
        src_path = "custom_components/universal_room_automation/domain_coordinators/energy.py"
        with open(src_path) as f:
            source = f.read()

        method_start = source.index("def _update_load_shedding(self, tou_period")
        next_def = source.find("\n    def ", method_start + 1)
        method_body = source[method_start:next_def if next_def != -1 else method_start + 5000]

        # Should call _execute_shed_action with activate=False for de-escalation
        assert "_execute_shed_action(released, activate=False)" in method_body

    def test_load_shedding_priority_order(self):
        """LOAD_SHEDDING_PRIORITY is pool -> ev -> smart_plugs -> hvac."""
        src_path = "custom_components/universal_room_automation/domain_coordinators/energy_const.py"
        with open(src_path) as f:
            source = f.read()
        assert '["pool", "ev", "smart_plugs", "hvac"]' in source


# =============================================================================
# 7. CO UNLOCKS EGRESS
# =============================================================================

class TestCOUnlocksEgress:
    """Verify security _handle_safety_hazard includes carbon_monoxide in egress unlock tuple."""

    def test_security_hazard_tuple_includes_carbon_monoxide(self):
        """The security handler's egress unlock tuple includes 'carbon_monoxide'."""
        src_path = "custom_components/universal_room_automation/domain_coordinators/security.py"
        with open(src_path) as f:
            source = f.read()

        # Find the _handle_safety_hazard method — use enough window for the full body
        method_start = source.index("def _handle_safety_hazard(self, hazard")
        next_def = source.find("\n    def ", method_start + 1)
        method_body = source[method_start:next_def if next_def != -1 else method_start + 1500]

        # Must include carbon_monoxide in the tuple alongside smoke and fire
        assert '"carbon_monoxide"' in method_body
        assert '"smoke"' in method_body
        assert '"fire"' in method_body

    def test_security_co_triggers_unlock(self):
        """Replicate: carbon_monoxide + critical should trigger unlock."""
        hass = make_mock_hass_with_cm_entry(
            {"security_on_hazard_unlock_egress": True}
        )

        # Replicate security handler logic
        lock_entities = ["lock.front_door", "lock.back_door"]
        actions = []

        hazard = {"hazard_type": "carbon_monoxide", "severity": "critical"}
        hazard_type = hazard["hazard_type"]
        severity = hazard["severity"]

        if hazard_type in ("smoke", "fire", "carbon_monoxide") and severity == "critical":
            if _get_signal_config(hass, "security_on_hazard_unlock_egress"):
                actions.append("unlock_egress")

        assert "unlock_egress" in actions

    def test_security_co_non_critical_does_not_unlock(self):
        """carbon_monoxide at HIGH severity does NOT trigger unlock."""
        hass = make_mock_hass_with_cm_entry(
            {"security_on_hazard_unlock_egress": True}
        )
        actions = []
        hazard = {"hazard_type": "carbon_monoxide", "severity": "high"}
        if hazard["hazard_type"] in ("smoke", "fire", "carbon_monoxide") and hazard["severity"] == "critical":
            if _get_signal_config(hass, "security_on_hazard_unlock_egress"):
                actions.append("unlock_egress")

        assert "unlock_egress" not in actions

    def test_hvac_co_also_stops_fans(self):
        """HVAC handler also uses 'carbon_monoxide' (not just 'co') for fan stop."""
        src_path = "custom_components/universal_room_automation/domain_coordinators/hvac.py"
        with open(src_path) as f:
            source = f.read()

        method_start = source.index("def _handle_safety_hazard(self, hazard")
        next_def = source.find("\n    def ", method_start + 1)
        method_body = source[method_start:next_def if next_def != -1 else method_start + 1500]
        assert '"carbon_monoxide"' in method_body


# =============================================================================
# 8. UNUSED IMPORTS REMOVED — _stop_all_fans_safety only imports CONF_FANS
# =============================================================================

class TestUnusedImports:
    """Verify _stop_all_fans_safety only imports what it needs."""

    def test_stop_all_fans_only_imports_conf_fans(self):
        """_stop_all_fans_safety local import should be CONF_FANS only."""
        src_path = "custom_components/universal_room_automation/domain_coordinators/hvac.py"
        with open(src_path) as f:
            source = f.read()

        method_start = source.index("async def _stop_all_fans_safety")
        method_body = source[method_start:method_start + 500]

        # Should have a local import of CONF_FANS
        assert "from ..const import CONF_FANS" in method_body

        # The import line should only have CONF_FANS (no other CONF_* names)
        import_line_start = method_body.index("from ..const import")
        import_line_end = method_body.index("\n", import_line_start)
        import_line = method_body[import_line_start:import_line_end]
        # Only CONF_FANS should be imported
        assert import_line.strip() == "from ..const import CONF_FANS"


# =============================================================================
# 9. DRY-RUN OBSERVATION MODE DEBUG LOGS
# =============================================================================

class TestDryRunLogs:
    """Verify observation mode early returns now have _LOGGER.debug calls."""

    def _get_handler_body(self, filepath, handler_name):
        """Extract the full body of a method from source."""
        with open(filepath) as f:
            source = f.read()
        method_start = source.index(f"def {handler_name}(self")
        next_def = source.find("\n    def ", method_start + 1)
        return source[method_start:next_def if next_def != -1 else method_start + 2000]

    def test_energy_observation_mode_debug_log(self):
        """Energy _handle_safety_hazard logs debug when in observation mode."""
        body = self._get_handler_body(
            "custom_components/universal_room_automation/domain_coordinators/energy.py",
            "_handle_safety_hazard",
        )
        assert "self._observation_mode" in body
        assert "_LOGGER.debug" in body
        assert "suppressed by observation mode" in body

    def test_hvac_observation_mode_debug_log(self):
        """HVAC _handle_safety_hazard logs debug when in observation mode."""
        body = self._get_handler_body(
            "custom_components/universal_room_automation/domain_coordinators/hvac.py",
            "_handle_safety_hazard",
        )
        assert "self._observation_mode" in body
        assert "_LOGGER.debug" in body
        assert "suppressed by observation mode" in body

    def test_security_observation_mode_debug_log(self):
        """Security _handle_safety_hazard logs debug when in observation mode."""
        body = self._get_handler_body(
            "custom_components/universal_room_automation/domain_coordinators/security.py",
            "_handle_safety_hazard",
        )
        assert "observation_mode" in body
        assert "_LOGGER.debug" in body
        assert "suppressed by observation mode" in body

    def test_music_observation_mode_debug_log(self):
        """Music _handle_safety_hazard logs debug when in observation mode."""
        body = self._get_handler_body(
            "custom_components/universal_room_automation/domain_coordinators/music_following.py",
            "_handle_safety_hazard",
        )
        assert "observation_mode" in body
        assert "_LOGGER.debug" in body
        assert "suppressed by observation mode" in body


# =============================================================================
# 10. DISABLED COORDINATOR GUARD — all signal handlers check _enabled first
# =============================================================================

class TestDisabledCoordinatorGuard:
    """Verify all signal handlers check self._enabled before processing."""

    def _check_handler_has_enabled_guard(self, filepath, handler_name):
        """Check that a signal handler has 'if not self._enabled: return' near the top."""
        with open(filepath) as f:
            source = f.read()

        search = f"def {handler_name}(self"
        assert search in source, f"{handler_name} not found in {filepath}"
        method_start = source.index(search)
        # Check the first 500 chars of the method body for the guard
        # (docstrings with multi-line comments can be 200+ chars)
        method_head = source[method_start:method_start + 500]
        assert "self._enabled" in method_head, (
            f"{handler_name} in {filepath} does not check self._enabled"
        )

    def test_hvac_decision_cycle_enabled_guard(self):
        """HVAC _async_decision_cycle checks _enabled."""
        self._check_handler_has_enabled_guard(
            "custom_components/universal_room_automation/domain_coordinators/hvac.py",
            "_async_decision_cycle",
        )

    def test_hvac_safety_hazard_enabled_guard(self):
        """HVAC _handle_safety_hazard checks _enabled."""
        self._check_handler_has_enabled_guard(
            "custom_components/universal_room_automation/domain_coordinators/hvac.py",
            "_handle_safety_hazard",
        )

    def test_security_safety_hazard_enabled_guard(self):
        """Security _handle_safety_hazard checks _enabled."""
        self._check_handler_has_enabled_guard(
            "custom_components/universal_room_automation/domain_coordinators/security.py",
            "_handle_safety_hazard",
        )

    def test_security_person_arriving_enabled_guard(self):
        """Security _handle_person_arriving_signal checks _enabled."""
        self._check_handler_has_enabled_guard(
            "custom_components/universal_room_automation/domain_coordinators/security.py",
            "_handle_person_arriving_signal",
        )

    def test_energy_safety_hazard_enabled_guard(self):
        """Energy _handle_safety_hazard checks _enabled."""
        self._check_handler_has_enabled_guard(
            "custom_components/universal_room_automation/domain_coordinators/energy.py",
            "_handle_safety_hazard",
        )

    def test_music_safety_hazard_enabled_guard(self):
        """Music _handle_safety_hazard checks _enabled."""
        self._check_handler_has_enabled_guard(
            "custom_components/universal_room_automation/domain_coordinators/music_following.py",
            "_handle_safety_hazard",
        )

    def test_music_person_arriving_enabled_guard(self):
        """Music _handle_person_arriving checks _enabled."""
        self._check_handler_has_enabled_guard(
            "custom_components/universal_room_automation/domain_coordinators/music_following.py",
            "_handle_person_arriving",
        )

    def test_music_security_event_enabled_guard(self):
        """Music _handle_security_event checks _enabled."""
        self._check_handler_has_enabled_guard(
            "custom_components/universal_room_automation/domain_coordinators/music_following.py",
            "_handle_security_event",
        )

    def test_presence_run_inference_enabled_guard(self):
        """Presence _run_inference checks _enabled."""
        self._check_handler_has_enabled_guard(
            "custom_components/universal_room_automation/domain_coordinators/presence.py",
            "_run_inference",
        )


# =============================================================================
# 11. CM ENTRY CACHING — _get_signal_config uses _cm_entry_cache
# =============================================================================

class TestCMEntryCaching:
    """Verify _get_signal_config caches the CM entry."""

    def test_cm_entry_cache_initialized_to_none(self):
        """BaseCoordinator __init__ sets _cm_entry_cache = None."""
        src_path = "custom_components/universal_room_automation/domain_coordinators/base.py"
        with open(src_path) as f:
            source = f.read()
        assert "self._cm_entry_cache = None" in source

    def test_get_signal_config_checks_cache_first(self):
        """_get_signal_config checks _cm_entry_cache before scanning entries."""
        src_path = "custom_components/universal_room_automation/domain_coordinators/base.py"
        with open(src_path) as f:
            source = f.read()

        method_start = source.index("def _get_signal_config(self")
        next_def = source.find("\n    def ", method_start + 1)
        method_body = source[method_start:next_def if next_def != -1 else method_start + 800]

        # First check: if cache is None
        assert "if self._cm_entry_cache is None:" in method_body
        # Should set cache on first find
        assert "self._cm_entry_cache = entry" in method_body

    def test_cached_lookup_avoids_scan(self):
        """If _cm_entry_cache is set, no scanning of config_entries occurs."""
        # Replicate the _get_signal_config logic with caching
        class FakeCoordinator:
            def __init__(self, hass):
                self.hass = hass
                self._cm_entry_cache = None

            def _get_signal_config(self, key, default=False):
                if self._cm_entry_cache is None:
                    for entry in self.hass.config_entries.async_entries(DOMAIN):
                        if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_COORDINATOR_MANAGER:
                            self._cm_entry_cache = entry
                            break
                if self._cm_entry_cache is None:
                    return default
                config = {**self._cm_entry_cache.data, **self._cm_entry_cache.options}
                return config.get(key, default)

        hass = make_mock_hass_with_cm_entry({"test_key": True})
        coord = FakeCoordinator(hass)

        # First call — scans entries
        result1 = coord._get_signal_config("test_key")
        assert result1 is True
        assert coord._cm_entry_cache is not None

        # Reset mock call count
        hass.config_entries.async_entries.reset_mock()

        # Second call — should use cache (async_entries NOT called)
        result2 = coord._get_signal_config("test_key")
        assert result2 is True
        hass.config_entries.async_entries.assert_not_called()


# =============================================================================
# 12. SWITCH RESTORE DEFERRED RETRY
# =============================================================================

class TestSwitchRestoreDeferredRetry:
    """Verify observation mode switches have _deferred_restore and _retry_restore."""

    def _get_class_body(self, source, unique_id_fragment):
        """Extract a full class body from source by finding its unique_id."""
        class_start = source.index(unique_id_fragment)
        class_block_start = source.rfind("class ", 0, class_start)
        # Find the next top-level class to bound the search
        next_class = source.find("\nclass ", class_block_start + 1)
        if next_class == -1:
            next_class = len(source)
        return source[class_block_start:next_class]

    def test_energy_observation_switch_has_deferred_restore(self):
        """EnergyObservationModeSwitch initializes _deferred_restore = False."""
        src_path = "custom_components/universal_room_automation/switch.py"
        with open(src_path) as f:
            source = f.read()

        class_body = self._get_class_body(source, "energy_observation_mode")

        assert "_deferred_restore = False" in class_body
        assert "_retry_restore" in class_body

    def test_hvac_observation_switch_has_deferred_restore(self):
        """HVACObservationModeSwitch initializes _deferred_restore = False."""
        src_path = "custom_components/universal_room_automation/switch.py"
        with open(src_path) as f:
            source = f.read()

        class_body = self._get_class_body(source, "hvac_observation_mode")

        assert "_deferred_restore = False" in class_body
        assert "_retry_restore" in class_body

    def test_retry_restore_logic(self):
        """Replicate _retry_restore: only acts if _deferred_restore is True."""
        class FakeSwitch:
            def __init__(self):
                self._deferred_restore = False
                self._restored = False

            def _get_coordinator(self):
                coord = MagicMock()
                coord.observation_mode = False
                return coord

            def _retry_restore(self, _now=None):
                if not self._deferred_restore:
                    return
                coord = self._get_coordinator()
                if coord is not None:
                    coord.observation_mode = True
                    self._deferred_restore = False
                    self._restored = True

        switch = FakeSwitch()

        # Calling retry when _deferred_restore=False does nothing
        switch._retry_restore()
        assert not switch._restored

        # Set deferred and retry
        switch._deferred_restore = True
        switch._retry_restore()
        assert switch._restored
        assert not switch._deferred_restore

    def test_retry_restore_guard_in_source(self):
        """_retry_restore methods check _deferred_restore before acting."""
        src_path = "custom_components/universal_room_automation/switch.py"
        with open(src_path) as f:
            source = f.read()

        # Find all _retry_restore definitions
        idx = 0
        count = 0
        while True:
            pos = source.find("def _retry_restore(self", idx)
            if pos == -1:
                break
            method_head = source[pos:pos + 200]
            assert "if not self._deferred_restore:" in method_head, (
                f"_retry_restore at pos {pos} does not check _deferred_restore"
            )
            count += 1
            idx = pos + 1

        # Should be at least 2 (energy + hvac observation mode switches)
        assert count >= 2, f"Expected at least 2 _retry_restore methods, found {count}"
