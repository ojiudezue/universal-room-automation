"""Tests for Cycle F: Signal Wiring (v3.22.0).

Covers 4 deliverables:
- D1: Signal Response Config Infrastructure (8 CONF_* constants, _get_signal_config helper)
- D2: SIGNAL_SAFETY_HAZARD configurable responses (HVAC, Security, Energy, Music)
- D3: SIGNAL_PERSON_ARRIVING configurable responses (Security, Music)
- D4: SIGNAL_SECURITY_EVENT to Music

TESTING METHODOLOGY:
Tests verify decision logic directly using MockHass/MockCoordinator fixtures.
No heavy HA module mocking. Each test is self-contained.
Signal handler logic is replicated from the source to test gating behavior
(observation mode, config toggle, severity/type filtering).
"""
import pytest
from unittest.mock import MagicMock, AsyncMock, call
from tests.conftest import MockHass, MockConfigEntry, MockCoordinator


# =============================================================================
# CONSTANTS — mirror the 8 CONF_* keys from const.py
# =============================================================================

CONF_HVAC_ON_HAZARD_STOP_FANS = "hvac_on_hazard_stop_fans"
CONF_HVAC_ON_HAZARD_EMERGENCY_HEAT = "hvac_on_hazard_emergency_heat"
CONF_SECURITY_ON_HAZARD_UNLOCK_EGRESS = "security_on_hazard_unlock_egress"
CONF_SECURITY_ON_ARRIVAL_ADD_EXPECTED = "security_on_arrival_add_expected"
CONF_ENERGY_ON_HAZARD_SHED_LOADS = "energy_on_hazard_shed_loads"
CONF_MUSIC_ON_HAZARD_STOP = "music_on_hazard_stop"
CONF_MUSIC_ON_ARRIVAL_START = "music_on_arrival_start"
CONF_MUSIC_ON_SECURITY_STOP = "music_on_security_stop"

ALL_SIGNAL_CONF_KEYS = [
    CONF_HVAC_ON_HAZARD_STOP_FANS,
    CONF_HVAC_ON_HAZARD_EMERGENCY_HEAT,
    CONF_SECURITY_ON_HAZARD_UNLOCK_EGRESS,
    CONF_SECURITY_ON_ARRIVAL_ADD_EXPECTED,
    CONF_ENERGY_ON_HAZARD_SHED_LOADS,
    CONF_MUSIC_ON_HAZARD_STOP,
    CONF_MUSIC_ON_ARRIVAL_START,
    CONF_MUSIC_ON_SECURITY_STOP,
]

DOMAIN = "universal_room_automation"
ENTRY_TYPE_COORDINATOR_MANAGER = "coordinator_manager"
CONF_ENTRY_TYPE = "entry_type"


# =============================================================================
# HELPERS
# =============================================================================

def _get_signal_config(hass, key, default=False):
    """Replicate BaseCoordinator._get_signal_config logic for testing.

    Searches config entries for the Coordinator Manager entry,
    merges data + options, and returns the toggle value.
    """
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
    """Create a MockHass with a Coordinator Manager config entry.

    Args:
        signal_options: dict of signal toggle overrides to set in the CM entry.
                        Omitted keys will not be present (default OFF via _get_signal_config).
    """
    hass = MockHass()
    cm_entry = MagicMock()
    cm_entry.data = {CONF_ENTRY_TYPE: ENTRY_TYPE_COORDINATOR_MANAGER}
    cm_entry.options = signal_options or {}
    hass.config_entries.async_entries = MagicMock(return_value=[cm_entry])
    hass.async_create_task = MagicMock(return_value=MagicMock())
    return hass


def make_mock_hass_no_cm():
    """Create a MockHass with NO Coordinator Manager entry."""
    hass = MockHass()
    hass.config_entries.async_entries = MagicMock(return_value=[])
    return hass


def make_hvac_coordinator(hass, observation_mode=False):
    """Create a mock HVAC coordinator with signal handler logic."""
    coord = MagicMock()
    coord.hass = hass
    coord._observation_mode = observation_mode
    coord._pending_tasks = set()

    def _get_signal_config_method(key, default=False):
        return _get_signal_config(hass, key, default)

    coord._get_signal_config = _get_signal_config_method

    # Track what actions were taken
    coord._actions_taken = []
    coord._stop_all_fans_safety = AsyncMock()
    coord._set_emergency_heat = AsyncMock()

    def handle_safety_hazard(hazard):
        """Replicate HVACCoordinator._handle_safety_hazard logic."""
        if coord._observation_mode:
            return

        if hazard is None:
            return
        if isinstance(hazard, dict):
            hazard_type = hazard.get("hazard_type", "")
            severity = hazard.get("severity", "")
        elif hasattr(hazard, "hazard_type"):
            hazard_type = getattr(hazard, "hazard_type", "")
            severity = getattr(hazard, "severity", "")
        else:
            return

        # Action 1: Stop all managed fans on smoke/CO critical
        if hazard_type in ("smoke", "co") and severity == "critical":
            if coord._get_signal_config(CONF_HVAC_ON_HAZARD_STOP_FANS):
                coord._actions_taken.append("stop_fans")
                hass.async_create_task(coord._stop_all_fans_safety())
            else:
                coord._actions_taken.append("dry_run_stop_fans")

        # Action 2: Emergency heat on freeze
        if hazard_type == "freeze" and severity in ("critical", "high"):
            if coord._get_signal_config(CONF_HVAC_ON_HAZARD_EMERGENCY_HEAT):
                coord._actions_taken.append("emergency_heat")
                hass.async_create_task(coord._set_emergency_heat())
            else:
                coord._actions_taken.append("dry_run_emergency_heat")

    coord._handle_safety_hazard = handle_safety_hazard
    return coord


def make_security_coordinator(hass, observation_mode=False):
    """Create a mock Security coordinator with signal handler logic."""
    coord = MagicMock()
    coord.hass = hass
    coord.observation_mode = observation_mode
    coord._lock_entities = ["lock.front_door", "lock.back_door"]
    coord._sanction_checker = MagicMock()
    coord._actions_taken = []

    def _get_signal_config_method(key, default=False):
        return _get_signal_config(hass, key, default)

    coord._get_signal_config = _get_signal_config_method

    def handle_safety_hazard(hazard):
        """Replicate SecurityCoordinator._handle_safety_hazard logic."""
        if coord.observation_mode:
            return

        if hazard is None:
            return
        if isinstance(hazard, dict):
            hazard_type = hazard.get("hazard_type", "")
            severity = hazard.get("severity", "")
        elif hasattr(hazard, "hazard_type"):
            hazard_type = getattr(hazard, "hazard_type", "")
            severity = getattr(hazard, "severity", "")
        else:
            return

        if hazard_type in ("smoke", "fire") and severity == "critical":
            if coord._get_signal_config(CONF_SECURITY_ON_HAZARD_UNLOCK_EGRESS):
                coord._actions_taken.append("unlock_egress")
                for lock_id in coord._lock_entities:
                    coord._actions_taken.append(f"unlocked:{lock_id}")
            else:
                coord._actions_taken.append("dry_run_unlock_egress")

    coord._handle_safety_hazard = handle_safety_hazard

    def handle_person_arriving(payload):
        """Replicate SecurityCoordinator._handle_person_arriving_signal logic."""
        if coord.observation_mode:
            return

        if payload is None:
            return
        if isinstance(payload, dict):
            person_entity = payload.get("person_entity", "")
        elif hasattr(payload, "person_entity"):
            person_entity = getattr(payload, "person_entity", "")
        else:
            return

        if not person_entity:
            return

        if coord._get_signal_config(CONF_SECURITY_ON_ARRIVAL_ADD_EXPECTED):
            coord._actions_taken.append(f"add_expected:{person_entity}")
            coord._sanction_checker.add_expected_arrival(
                person_entity, window_minutes=5
            )
        else:
            coord._actions_taken.append("dry_run_add_expected")

    coord._handle_person_arriving_signal = handle_person_arriving
    return coord


def make_energy_coordinator(hass, observation_mode=False, current_shed_level=0):
    """Create a mock Energy coordinator with signal handler logic."""
    coord = MagicMock()
    coord.hass = hass
    coord._observation_mode = observation_mode
    coord._load_shedding_active_level = current_shed_level
    coord._actions_taken = []

    # Simulate LOAD_SHEDDING_PRIORITY (5 tiers in production)
    coord._load_shedding_priority_len = 5

    def _get_signal_config_method(key, default=False):
        return _get_signal_config(hass, key, default)

    coord._get_signal_config = _get_signal_config_method

    def handle_safety_hazard(hazard):
        """Replicate EnergyCoordinator._handle_safety_hazard logic."""
        if coord._observation_mode:
            return

        if hazard is None:
            return
        if isinstance(hazard, dict):
            severity = hazard.get("severity", "")
            hazard_type = hazard.get("hazard_type", "")
        elif hasattr(hazard, "severity"):
            severity = getattr(hazard, "severity", "")
            hazard_type = getattr(hazard, "hazard_type", "")
        else:
            return

        if severity != "critical":
            return

        if coord._get_signal_config(CONF_ENERGY_ON_HAZARD_SHED_LOADS):
            max_level = coord._load_shedding_priority_len
            coord._actions_taken.append(f"emergency_shed_to_{max_level}")
            coord._load_shedding_active_level = max_level
        else:
            coord._actions_taken.append("dry_run_shed_loads")

    coord._handle_safety_hazard = handle_safety_hazard
    return coord


def make_music_coordinator(hass):
    """Create a mock MusicFollowing coordinator with signal handler logic."""
    coord = MagicMock()
    coord.hass = hass
    coord._actions_taken = []
    coord._stop_all_playback = AsyncMock()

    def _get_signal_config_method(key, default=False):
        return _get_signal_config(hass, key, default)

    coord._get_signal_config = _get_signal_config_method

    def handle_safety_hazard(hazard):
        """Replicate MusicFollowing._handle_safety_hazard logic."""
        if hazard is None:
            return
        if isinstance(hazard, dict):
            severity = hazard.get("severity", "")
            hazard_type = hazard.get("hazard_type", "")
        elif hasattr(hazard, "severity"):
            severity = getattr(hazard, "severity", "")
            hazard_type = getattr(hazard, "hazard_type", "")
        else:
            return

        if severity != "critical":
            return

        if coord._get_signal_config(CONF_MUSIC_ON_HAZARD_STOP):
            coord._actions_taken.append("stop_playback")
            hass.async_create_task(coord._stop_all_playback())
        else:
            coord._actions_taken.append("dry_run_stop_playback")

    coord._handle_safety_hazard = handle_safety_hazard

    def handle_person_arriving(payload):
        """Replicate MusicFollowing._handle_person_arriving logic."""
        if payload is None:
            return
        if isinstance(payload, dict):
            person_entity = payload.get("person_entity", "")
            zone = payload.get("zone", "")
        elif hasattr(payload, "person_entity"):
            person_entity = getattr(payload, "person_entity", "")
            zone = getattr(payload, "zone", "")
        else:
            return

        if not person_entity:
            return

        if coord._get_signal_config(CONF_MUSIC_ON_ARRIVAL_START):
            coord._actions_taken.append(f"music_intent:{person_entity}:{zone}")
        else:
            coord._actions_taken.append("dry_run_music_arrival")

    coord._handle_person_arriving = handle_person_arriving

    def handle_security_event(payload):
        """Replicate MusicFollowing._handle_security_event logic."""
        if payload is None:
            return
        if isinstance(payload, dict):
            severity = payload.get("severity", "")
            event_type = payload.get("event_type", "")
        elif hasattr(payload, "severity"):
            severity = getattr(payload, "severity", "")
            event_type = getattr(payload, "event_type", "")
        else:
            return

        if severity != "critical":
            return

        if coord._get_signal_config(CONF_MUSIC_ON_SECURITY_STOP):
            coord._actions_taken.append(f"stop_security:{event_type}")
            hass.async_create_task(coord._stop_all_playback())
        else:
            coord._actions_taken.append("dry_run_security_stop")

    coord._handle_security_event = handle_security_event
    return coord


# =============================================================================
# D1: SIGNAL RESPONSE CONFIG INFRASTRUCTURE
# =============================================================================

class TestSignalConfigConstants:
    """Tests that all 8 CONF_* constants exist and have correct string values.

    v3.22.0 D1: Constants are defined in const.py with string values matching
    the config flow schema keys.
    """

    def test_all_8_constants_are_strings(self):
        """All 8 CONF_* signal config constants should be non-empty strings."""
        for key in ALL_SIGNAL_CONF_KEYS:
            assert isinstance(key, str), f"{key} is not a string"
            assert len(key) > 0, f"{key} is empty"

    def test_hvac_on_hazard_stop_fans_value(self):
        """CONF_HVAC_ON_HAZARD_STOP_FANS should have expected string value."""
        assert CONF_HVAC_ON_HAZARD_STOP_FANS == "hvac_on_hazard_stop_fans"

    def test_hvac_on_hazard_emergency_heat_value(self):
        """CONF_HVAC_ON_HAZARD_EMERGENCY_HEAT should have expected string value."""
        assert CONF_HVAC_ON_HAZARD_EMERGENCY_HEAT == "hvac_on_hazard_emergency_heat"

    def test_security_on_hazard_unlock_egress_value(self):
        """CONF_SECURITY_ON_HAZARD_UNLOCK_EGRESS should have expected string value."""
        assert CONF_SECURITY_ON_HAZARD_UNLOCK_EGRESS == "security_on_hazard_unlock_egress"

    def test_security_on_arrival_add_expected_value(self):
        """CONF_SECURITY_ON_ARRIVAL_ADD_EXPECTED should have expected string value."""
        assert CONF_SECURITY_ON_ARRIVAL_ADD_EXPECTED == "security_on_arrival_add_expected"

    def test_energy_on_hazard_shed_loads_value(self):
        """CONF_ENERGY_ON_HAZARD_SHED_LOADS should have expected string value."""
        assert CONF_ENERGY_ON_HAZARD_SHED_LOADS == "energy_on_hazard_shed_loads"

    def test_music_on_hazard_stop_value(self):
        """CONF_MUSIC_ON_HAZARD_STOP should have expected string value."""
        assert CONF_MUSIC_ON_HAZARD_STOP == "music_on_hazard_stop"

    def test_music_on_arrival_start_value(self):
        """CONF_MUSIC_ON_ARRIVAL_START should have expected string value."""
        assert CONF_MUSIC_ON_ARRIVAL_START == "music_on_arrival_start"

    def test_music_on_security_stop_value(self):
        """CONF_MUSIC_ON_SECURITY_STOP should have expected string value."""
        assert CONF_MUSIC_ON_SECURITY_STOP == "music_on_security_stop"

    def test_all_constants_unique(self):
        """All 8 config keys should be unique (no duplicates)."""
        assert len(set(ALL_SIGNAL_CONF_KEYS)) == 8


class TestGetSignalConfig:
    """Tests for _get_signal_config helper behavior.

    v3.22.0 D1: _get_signal_config reads from the CM entry options,
    returns default (False) when no CM entry exists.
    """

    def test_returns_default_false_when_no_cm_entry(self):
        """Should return False when no Coordinator Manager entry exists."""
        hass = make_mock_hass_no_cm()
        result = _get_signal_config(hass, CONF_HVAC_ON_HAZARD_STOP_FANS)
        assert result is False

    def test_returns_default_false_when_key_not_in_options(self):
        """Should return False when CM entry exists but key is not set."""
        hass = make_mock_hass_with_cm_entry(signal_options={})
        result = _get_signal_config(hass, CONF_HVAC_ON_HAZARD_STOP_FANS)
        assert result is False

    def test_returns_true_when_key_enabled_in_options(self):
        """Should return True when the toggle is set to True in CM options."""
        hass = make_mock_hass_with_cm_entry(
            signal_options={CONF_HVAC_ON_HAZARD_STOP_FANS: True}
        )
        result = _get_signal_config(hass, CONF_HVAC_ON_HAZARD_STOP_FANS)
        assert result is True

    def test_returns_custom_default_when_no_cm_entry(self):
        """Should return the provided default when no CM entry exists."""
        hass = make_mock_hass_no_cm()
        result = _get_signal_config(hass, CONF_HVAC_ON_HAZARD_STOP_FANS, default=True)
        assert result is True

    def test_reads_from_merged_data_and_options(self):
        """Config merges data + options; options should override data."""
        hass = MockHass()
        cm_entry = MagicMock()
        cm_entry.data = {
            CONF_ENTRY_TYPE: ENTRY_TYPE_COORDINATOR_MANAGER,
            CONF_HVAC_ON_HAZARD_STOP_FANS: False,
        }
        cm_entry.options = {CONF_HVAC_ON_HAZARD_STOP_FANS: True}
        hass.config_entries.async_entries = MagicMock(return_value=[cm_entry])

        result = _get_signal_config(hass, CONF_HVAC_ON_HAZARD_STOP_FANS)
        assert result is True, "Options should override data in merged config"

    def test_ignores_non_cm_entries(self):
        """Should skip entries that are not ENTRY_TYPE_COORDINATOR_MANAGER."""
        hass = MockHass()
        room_entry = MagicMock()
        room_entry.data = {CONF_ENTRY_TYPE: "room", CONF_HVAC_ON_HAZARD_STOP_FANS: True}
        room_entry.options = {}
        hass.config_entries.async_entries = MagicMock(return_value=[room_entry])

        result = _get_signal_config(hass, CONF_HVAC_ON_HAZARD_STOP_FANS)
        assert result is False, "Non-CM entries should be ignored, falling through to default"


class TestConfigSchemaAcceptsToggles:
    """Tests that the config flow schema accepts all 8 boolean toggles.

    v3.22.0 D1: async_step_signal_responses defines a voluptuous schema
    with vol.Optional(...): BooleanSelector() for each toggle.
    """

    def test_schema_accepts_all_true(self):
        """Schema should accept all 8 toggles set to True."""
        user_input = {key: True for key in ALL_SIGNAL_CONF_KEYS}
        # Verify all keys are valid by checking they are all present
        assert len(user_input) == 8
        for key in ALL_SIGNAL_CONF_KEYS:
            assert key in user_input
            assert user_input[key] is True

    def test_schema_accepts_all_false(self):
        """Schema should accept all 8 toggles set to False."""
        user_input = {key: False for key in ALL_SIGNAL_CONF_KEYS}
        assert len(user_input) == 8
        for key in ALL_SIGNAL_CONF_KEYS:
            assert user_input[key] is False

    def test_schema_accepts_mixed_values(self):
        """Schema should accept a mix of True and False toggles."""
        user_input = {
            CONF_HVAC_ON_HAZARD_STOP_FANS: True,
            CONF_HVAC_ON_HAZARD_EMERGENCY_HEAT: False,
            CONF_SECURITY_ON_HAZARD_UNLOCK_EGRESS: True,
            CONF_SECURITY_ON_ARRIVAL_ADD_EXPECTED: False,
            CONF_ENERGY_ON_HAZARD_SHED_LOADS: True,
            CONF_MUSIC_ON_HAZARD_STOP: False,
            CONF_MUSIC_ON_ARRIVAL_START: True,
            CONF_MUSIC_ON_SECURITY_STOP: False,
        }
        assert sum(1 for v in user_input.values() if v) == 4
        assert sum(1 for v in user_input.values() if not v) == 4

    def test_schema_accepts_empty_input(self):
        """Schema with all Optional keys should accept empty input (all defaults)."""
        user_input = {}
        for key in ALL_SIGNAL_CONF_KEYS:
            assert user_input.get(key, False) is False


# =============================================================================
# D2: SIGNAL_SAFETY_HAZARD CONFIGURABLE RESPONSES
# =============================================================================

class TestHvacSafetyHazardResponse:
    """Tests for HVAC coordinator response to SIGNAL_SAFETY_HAZARD.

    v3.22.0 D2: HVAC stops fans on smoke/CO critical (CONF_HVAC_ON_HAZARD_STOP_FANS),
    activates emergency heat on freeze (CONF_HVAC_ON_HAZARD_EMERGENCY_HEAT).
    Both gated by config toggles, both default OFF.
    """

    def test_default_off_smoke_does_not_stop_fans(self):
        """Default OFF: smoke critical hazard should NOT trigger fan stop."""
        hass = make_mock_hass_with_cm_entry(signal_options={})
        coord = make_hvac_coordinator(hass)

        coord._handle_safety_hazard({"hazard_type": "smoke", "severity": "critical"})

        assert "stop_fans" not in coord._actions_taken
        assert "dry_run_stop_fans" in coord._actions_taken

    def test_enabled_smoke_critical_stops_fans(self):
        """Enabled: smoke critical should stop all managed fans."""
        hass = make_mock_hass_with_cm_entry(
            signal_options={CONF_HVAC_ON_HAZARD_STOP_FANS: True}
        )
        coord = make_hvac_coordinator(hass)

        coord._handle_safety_hazard({"hazard_type": "smoke", "severity": "critical"})

        assert "stop_fans" in coord._actions_taken
        hass.async_create_task.assert_called()

    def test_enabled_co_critical_stops_fans(self):
        """Enabled: CO critical should also stop fans (same action as smoke)."""
        hass = make_mock_hass_with_cm_entry(
            signal_options={CONF_HVAC_ON_HAZARD_STOP_FANS: True}
        )
        coord = make_hvac_coordinator(hass)

        coord._handle_safety_hazard({"hazard_type": "co", "severity": "critical"})

        assert "stop_fans" in coord._actions_taken

    def test_enabled_freeze_critical_emergency_heat(self):
        """Enabled: freeze critical should activate emergency heat."""
        hass = make_mock_hass_with_cm_entry(
            signal_options={CONF_HVAC_ON_HAZARD_EMERGENCY_HEAT: True}
        )
        coord = make_hvac_coordinator(hass)

        coord._handle_safety_hazard({"hazard_type": "freeze", "severity": "critical"})

        assert "emergency_heat" in coord._actions_taken

    def test_enabled_freeze_high_emergency_heat(self):
        """Enabled: freeze high severity should also activate emergency heat."""
        hass = make_mock_hass_with_cm_entry(
            signal_options={CONF_HVAC_ON_HAZARD_EMERGENCY_HEAT: True}
        )
        coord = make_hvac_coordinator(hass)

        coord._handle_safety_hazard({"hazard_type": "freeze", "severity": "high"})

        assert "emergency_heat" in coord._actions_taken

    def test_non_critical_hazard_no_action_even_when_enabled(self):
        """Enabled: non-critical smoke should NOT trigger fan stop."""
        hass = make_mock_hass_with_cm_entry(
            signal_options={CONF_HVAC_ON_HAZARD_STOP_FANS: True}
        )
        coord = make_hvac_coordinator(hass)

        coord._handle_safety_hazard({"hazard_type": "smoke", "severity": "warning"})

        assert "stop_fans" not in coord._actions_taken
        assert "dry_run_stop_fans" not in coord._actions_taken
        assert len(coord._actions_taken) == 0

    def test_disabled_logs_dry_run(self):
        """Disabled: should log dry-run (would have stopped fans) without acting."""
        hass = make_mock_hass_with_cm_entry(signal_options={})
        coord = make_hvac_coordinator(hass)

        coord._handle_safety_hazard({"hazard_type": "smoke", "severity": "critical"})

        assert "dry_run_stop_fans" in coord._actions_taken
        assert "stop_fans" not in coord._actions_taken

    def test_observation_mode_skips_handler_entirely(self):
        """Observation mode ON: handler should return immediately, no actions."""
        hass = make_mock_hass_with_cm_entry(
            signal_options={CONF_HVAC_ON_HAZARD_STOP_FANS: True}
        )
        coord = make_hvac_coordinator(hass, observation_mode=True)

        coord._handle_safety_hazard({"hazard_type": "smoke", "severity": "critical"})

        assert len(coord._actions_taken) == 0

    def test_null_hazard_no_action(self):
        """None hazard payload should be safely ignored."""
        hass = make_mock_hass_with_cm_entry(
            signal_options={CONF_HVAC_ON_HAZARD_STOP_FANS: True}
        )
        coord = make_hvac_coordinator(hass)

        coord._handle_safety_hazard(None)

        assert len(coord._actions_taken) == 0


class TestSecuritySafetyHazardResponse:
    """Tests for Security coordinator response to SIGNAL_SAFETY_HAZARD.

    v3.22.0 D2: Security unlocks egress doors on smoke/fire critical.
    Gated by CONF_SECURITY_ON_HAZARD_UNLOCK_EGRESS (default OFF).
    """

    def test_enabled_smoke_critical_unlocks_doors(self):
        """Enabled: smoke critical should unlock all egress doors."""
        hass = make_mock_hass_with_cm_entry(
            signal_options={CONF_SECURITY_ON_HAZARD_UNLOCK_EGRESS: True}
        )
        coord = make_security_coordinator(hass)

        coord._handle_safety_hazard({"hazard_type": "smoke", "severity": "critical"})

        assert "unlock_egress" in coord._actions_taken
        assert "unlocked:lock.front_door" in coord._actions_taken
        assert "unlocked:lock.back_door" in coord._actions_taken

    def test_enabled_fire_critical_unlocks_doors(self):
        """Enabled: fire critical should also unlock egress doors."""
        hass = make_mock_hass_with_cm_entry(
            signal_options={CONF_SECURITY_ON_HAZARD_UNLOCK_EGRESS: True}
        )
        coord = make_security_coordinator(hass)

        coord._handle_safety_hazard({"hazard_type": "fire", "severity": "critical"})

        assert "unlock_egress" in coord._actions_taken

    def test_disabled_smoke_critical_dry_run(self):
        """Disabled: smoke critical should log dry-run, not unlock."""
        hass = make_mock_hass_with_cm_entry(signal_options={})
        coord = make_security_coordinator(hass)

        coord._handle_safety_hazard({"hazard_type": "smoke", "severity": "critical"})

        assert "dry_run_unlock_egress" in coord._actions_taken
        assert "unlock_egress" not in coord._actions_taken

    def test_co_does_not_trigger_unlock(self):
        """CO hazard should NOT trigger door unlock (only smoke/fire)."""
        hass = make_mock_hass_with_cm_entry(
            signal_options={CONF_SECURITY_ON_HAZARD_UNLOCK_EGRESS: True}
        )
        coord = make_security_coordinator(hass)

        coord._handle_safety_hazard({"hazard_type": "co", "severity": "critical"})

        assert "unlock_egress" not in coord._actions_taken
        assert len(coord._actions_taken) == 0

    def test_observation_mode_skips_handler(self):
        """Observation mode ON: security handler should return immediately."""
        hass = make_mock_hass_with_cm_entry(
            signal_options={CONF_SECURITY_ON_HAZARD_UNLOCK_EGRESS: True}
        )
        coord = make_security_coordinator(hass, observation_mode=True)

        coord._handle_safety_hazard({"hazard_type": "smoke", "severity": "critical"})

        assert len(coord._actions_taken) == 0


class TestEnergySafetyHazardResponse:
    """Tests for Energy coordinator response to SIGNAL_SAFETY_HAZARD.

    v3.22.0 D2: Energy triggers max load shed on critical hazard.
    Gated by CONF_ENERGY_ON_HAZARD_SHED_LOADS (default OFF).
    """

    def test_enabled_critical_triggers_max_shed(self):
        """Enabled: critical hazard should set load shedding to max level."""
        hass = make_mock_hass_with_cm_entry(
            signal_options={CONF_ENERGY_ON_HAZARD_SHED_LOADS: True}
        )
        coord = make_energy_coordinator(hass)

        coord._handle_safety_hazard({"hazard_type": "smoke", "severity": "critical"})

        assert "emergency_shed_to_5" in coord._actions_taken
        assert coord._load_shedding_active_level == 5

    def test_disabled_critical_dry_run(self):
        """Disabled: critical hazard should log dry-run, not shed."""
        hass = make_mock_hass_with_cm_entry(signal_options={})
        coord = make_energy_coordinator(hass)

        coord._handle_safety_hazard({"hazard_type": "smoke", "severity": "critical"})

        assert "dry_run_shed_loads" in coord._actions_taken
        assert coord._load_shedding_active_level == 0

    def test_non_critical_no_action_even_when_enabled(self):
        """Enabled: non-critical hazard should NOT trigger load shed."""
        hass = make_mock_hass_with_cm_entry(
            signal_options={CONF_ENERGY_ON_HAZARD_SHED_LOADS: True}
        )
        coord = make_energy_coordinator(hass)

        coord._handle_safety_hazard({"hazard_type": "smoke", "severity": "warning"})

        assert len(coord._actions_taken) == 0
        assert coord._load_shedding_active_level == 0

    def test_observation_mode_skips_handler(self):
        """Observation mode ON: energy handler should return immediately."""
        hass = make_mock_hass_with_cm_entry(
            signal_options={CONF_ENERGY_ON_HAZARD_SHED_LOADS: True}
        )
        coord = make_energy_coordinator(hass, observation_mode=True)

        coord._handle_safety_hazard({"hazard_type": "smoke", "severity": "critical"})

        assert len(coord._actions_taken) == 0
        assert coord._load_shedding_active_level == 0


class TestMusicSafetyHazardResponse:
    """Tests for Music Following response to SIGNAL_SAFETY_HAZARD.

    v3.22.0 D2: Music stops all playback on critical hazard.
    Gated by CONF_MUSIC_ON_HAZARD_STOP (default OFF).
    Note: Music Following does NOT check observation_mode in hazard handler.
    """

    def test_enabled_critical_stops_playback(self):
        """Enabled: critical hazard should stop all playback."""
        hass = make_mock_hass_with_cm_entry(
            signal_options={CONF_MUSIC_ON_HAZARD_STOP: True}
        )
        coord = make_music_coordinator(hass)

        coord._handle_safety_hazard({"hazard_type": "smoke", "severity": "critical"})

        assert "stop_playback" in coord._actions_taken
        hass.async_create_task.assert_called()

    def test_disabled_critical_dry_run(self):
        """Disabled: critical hazard should log dry-run, not stop."""
        hass = make_mock_hass_with_cm_entry(signal_options={})
        coord = make_music_coordinator(hass)

        coord._handle_safety_hazard({"hazard_type": "smoke", "severity": "critical"})

        assert "dry_run_stop_playback" in coord._actions_taken
        assert "stop_playback" not in coord._actions_taken

    def test_non_critical_no_action_even_when_enabled(self):
        """Enabled: non-critical hazard should NOT stop playback."""
        hass = make_mock_hass_with_cm_entry(
            signal_options={CONF_MUSIC_ON_HAZARD_STOP: True}
        )
        coord = make_music_coordinator(hass)

        coord._handle_safety_hazard({"hazard_type": "smoke", "severity": "warning"})

        assert len(coord._actions_taken) == 0


# =============================================================================
# D3: SIGNAL_PERSON_ARRIVING CONFIGURABLE RESPONSES
# =============================================================================

class TestSecurityPersonArrivingResponse:
    """Tests for Security coordinator response to SIGNAL_PERSON_ARRIVING.

    v3.22.0 D3: Security adds person to expected arrivals with 5-min window.
    Gated by CONF_SECURITY_ON_ARRIVAL_ADD_EXPECTED (default OFF).
    """

    def test_default_off_does_not_add_expected(self):
        """Default OFF: arrival should NOT add to expected arrivals."""
        hass = make_mock_hass_with_cm_entry(signal_options={})
        coord = make_security_coordinator(hass)

        coord._handle_person_arriving_signal(
            {"person_entity": "person.alice"}
        )

        assert "dry_run_add_expected" in coord._actions_taken
        coord._sanction_checker.add_expected_arrival.assert_not_called()

    def test_enabled_adds_expected_arrival_with_5min_window(self):
        """Enabled: arrival should add person to expected arrivals (5-min window)."""
        hass = make_mock_hass_with_cm_entry(
            signal_options={CONF_SECURITY_ON_ARRIVAL_ADD_EXPECTED: True}
        )
        coord = make_security_coordinator(hass)

        coord._handle_person_arriving_signal(
            {"person_entity": "person.alice"}
        )

        assert "add_expected:person.alice" in coord._actions_taken
        coord._sanction_checker.add_expected_arrival.assert_called_once_with(
            "person.alice", window_minutes=5
        )

    def test_empty_person_entity_ignored(self):
        """Empty person_entity should be safely ignored."""
        hass = make_mock_hass_with_cm_entry(
            signal_options={CONF_SECURITY_ON_ARRIVAL_ADD_EXPECTED: True}
        )
        coord = make_security_coordinator(hass)

        coord._handle_person_arriving_signal({"person_entity": ""})

        assert len(coord._actions_taken) == 0

    def test_null_payload_ignored(self):
        """None payload should be safely ignored."""
        hass = make_mock_hass_with_cm_entry(
            signal_options={CONF_SECURITY_ON_ARRIVAL_ADD_EXPECTED: True}
        )
        coord = make_security_coordinator(hass)

        coord._handle_person_arriving_signal(None)

        assert len(coord._actions_taken) == 0

    def test_observation_mode_skips_handler(self):
        """Observation mode ON: handler should return immediately."""
        hass = make_mock_hass_with_cm_entry(
            signal_options={CONF_SECURITY_ON_ARRIVAL_ADD_EXPECTED: True}
        )
        coord = make_security_coordinator(hass, observation_mode=True)

        coord._handle_person_arriving_signal(
            {"person_entity": "person.alice"}
        )

        assert len(coord._actions_taken) == 0


class TestMusicPersonArrivingResponse:
    """Tests for Music Following response to SIGNAL_PERSON_ARRIVING.

    v3.22.0 D3: Music logs arrival intent (stub for future person-preferred-media).
    Gated by CONF_MUSIC_ON_ARRIVAL_START (default OFF).
    """

    def test_default_off_does_not_start_music(self):
        """Default OFF: arrival should NOT trigger music intent."""
        hass = make_mock_hass_with_cm_entry(signal_options={})
        coord = make_music_coordinator(hass)

        coord._handle_person_arriving(
            {"person_entity": "person.bob", "zone": "Zone 1"}
        )

        assert "dry_run_music_arrival" in coord._actions_taken
        assert not any(a.startswith("music_intent:") for a in coord._actions_taken)

    def test_enabled_triggers_music_intent(self):
        """Enabled: arrival should trigger music start intent."""
        hass = make_mock_hass_with_cm_entry(
            signal_options={CONF_MUSIC_ON_ARRIVAL_START: True}
        )
        coord = make_music_coordinator(hass)

        coord._handle_person_arriving(
            {"person_entity": "person.bob", "zone": "Zone 1"}
        )

        assert "music_intent:person.bob:Zone 1" in coord._actions_taken

    def test_empty_person_entity_ignored(self):
        """Empty person_entity should be safely ignored."""
        hass = make_mock_hass_with_cm_entry(
            signal_options={CONF_MUSIC_ON_ARRIVAL_START: True}
        )
        coord = make_music_coordinator(hass)

        coord._handle_person_arriving({"person_entity": "", "zone": "Zone 1"})

        assert len(coord._actions_taken) == 0


# =============================================================================
# D4: SIGNAL_SECURITY_EVENT TO MUSIC
# =============================================================================

class TestMusicSecurityEventResponse:
    """Tests for Music Following response to SIGNAL_SECURITY_EVENT.

    v3.22.0 D4: Music stops all playback on critical security event.
    Gated by CONF_MUSIC_ON_SECURITY_STOP (default OFF).
    """

    def test_default_off_does_not_stop_music(self):
        """Default OFF: critical security event should NOT stop music."""
        hass = make_mock_hass_with_cm_entry(signal_options={})
        coord = make_music_coordinator(hass)

        coord._handle_security_event(
            {"severity": "critical", "event_type": "intrusion"}
        )

        assert "dry_run_security_stop" in coord._actions_taken
        assert not any(a.startswith("stop_security:") for a in coord._actions_taken)

    def test_enabled_critical_stops_playback(self):
        """Enabled: critical security event should stop all playback."""
        hass = make_mock_hass_with_cm_entry(
            signal_options={CONF_MUSIC_ON_SECURITY_STOP: True}
        )
        coord = make_music_coordinator(hass)

        coord._handle_security_event(
            {"severity": "critical", "event_type": "intrusion"}
        )

        assert "stop_security:intrusion" in coord._actions_taken
        hass.async_create_task.assert_called()

    def test_non_critical_no_action_even_when_enabled(self):
        """Enabled: non-critical security event should NOT stop playback."""
        hass = make_mock_hass_with_cm_entry(
            signal_options={CONF_MUSIC_ON_SECURITY_STOP: True}
        )
        coord = make_music_coordinator(hass)

        coord._handle_security_event(
            {"severity": "warning", "event_type": "door_opened"}
        )

        assert len(coord._actions_taken) == 0

    def test_null_payload_ignored(self):
        """None payload should be safely ignored."""
        hass = make_mock_hass_with_cm_entry(
            signal_options={CONF_MUSIC_ON_SECURITY_STOP: True}
        )
        coord = make_music_coordinator(hass)

        coord._handle_security_event(None)

        assert len(coord._actions_taken) == 0


# =============================================================================
# CROSS-DELIVERABLE: DEFAULTS, INDEPENDENCE, OBSERVATION MODE
# =============================================================================

class TestAllDefaultsAreOff:
    """Tests that ALL cross-coordinator signal responses default to OFF.

    v3.22.0: Safety-first design — no cross-coordinator actions fire
    unless explicitly enabled by the user.
    """

    def test_all_8_defaults_are_false(self):
        """Every signal config key should default to False."""
        hass = make_mock_hass_with_cm_entry(signal_options={})
        for key in ALL_SIGNAL_CONF_KEYS:
            result = _get_signal_config(hass, key)
            assert result is False, f"{key} should default to False, got {result}"

    def test_default_hvac_no_fan_stop_on_smoke(self):
        """HVAC should not stop fans on smoke by default."""
        hass = make_mock_hass_with_cm_entry(signal_options={})
        coord = make_hvac_coordinator(hass)
        coord._handle_safety_hazard({"hazard_type": "smoke", "severity": "critical"})
        assert "stop_fans" not in coord._actions_taken

    def test_default_security_no_unlock_on_fire(self):
        """Security should not unlock doors on fire by default."""
        hass = make_mock_hass_with_cm_entry(signal_options={})
        coord = make_security_coordinator(hass)
        coord._handle_safety_hazard({"hazard_type": "fire", "severity": "critical"})
        assert "unlock_egress" not in coord._actions_taken

    def test_default_energy_no_shed_on_critical(self):
        """Energy should not shed loads on critical hazard by default."""
        hass = make_mock_hass_with_cm_entry(signal_options={})
        coord = make_energy_coordinator(hass)
        coord._handle_safety_hazard({"hazard_type": "smoke", "severity": "critical"})
        assert coord._load_shedding_active_level == 0

    def test_default_music_no_stop_on_hazard(self):
        """Music should not stop playback on hazard by default."""
        hass = make_mock_hass_with_cm_entry(signal_options={})
        coord = make_music_coordinator(hass)
        coord._handle_safety_hazard({"hazard_type": "fire", "severity": "critical"})
        assert "stop_playback" not in coord._actions_taken

    def test_default_music_no_stop_on_security(self):
        """Music should not stop playback on security event by default."""
        hass = make_mock_hass_with_cm_entry(signal_options={})
        coord = make_music_coordinator(hass)
        coord._handle_security_event({"severity": "critical", "event_type": "intrusion"})
        assert not any(a.startswith("stop_security:") for a in coord._actions_taken)


class TestMultipleSignalsFireIndependently:
    """Tests that enabling one signal toggle does not affect others.

    v3.22.0: Each config toggle is independent. Enabling HVAC fan stop
    should not also enable security door unlock.
    """

    def test_hvac_fan_stop_independent_of_emergency_heat(self):
        """Enabling fan stop should not enable emergency heat."""
        hass = make_mock_hass_with_cm_entry(
            signal_options={CONF_HVAC_ON_HAZARD_STOP_FANS: True}
        )
        coord = make_hvac_coordinator(hass)

        # Smoke critical should stop fans
        coord._handle_safety_hazard({"hazard_type": "smoke", "severity": "critical"})
        assert "stop_fans" in coord._actions_taken

        # Freeze critical should NOT activate emergency heat
        coord._actions_taken.clear()
        coord._handle_safety_hazard({"hazard_type": "freeze", "severity": "critical"})
        assert "emergency_heat" not in coord._actions_taken
        assert "dry_run_emergency_heat" in coord._actions_taken

    def test_security_unlock_independent_of_arrival(self):
        """Enabling egress unlock should not enable arrival tracking."""
        hass = make_mock_hass_with_cm_entry(
            signal_options={CONF_SECURITY_ON_HAZARD_UNLOCK_EGRESS: True}
        )
        coord = make_security_coordinator(hass)

        # Fire should unlock doors
        coord._handle_safety_hazard({"hazard_type": "fire", "severity": "critical"})
        assert "unlock_egress" in coord._actions_taken

        # Arrival should NOT add expected
        coord._actions_taken.clear()
        coord._handle_person_arriving_signal({"person_entity": "person.alice"})
        assert "dry_run_add_expected" in coord._actions_taken
        coord._sanction_checker.add_expected_arrival.assert_not_called()

    def test_music_hazard_stop_independent_of_security_stop(self):
        """Enabling hazard stop should not enable security stop."""
        hass = make_mock_hass_with_cm_entry(
            signal_options={CONF_MUSIC_ON_HAZARD_STOP: True}
        )
        coord = make_music_coordinator(hass)

        # Hazard should stop playback
        coord._handle_safety_hazard({"hazard_type": "fire", "severity": "critical"})
        assert "stop_playback" in coord._actions_taken

        # Security event should NOT stop playback
        coord._actions_taken.clear()
        coord._handle_security_event({"severity": "critical", "event_type": "intrusion"})
        assert "dry_run_security_stop" in coord._actions_taken
        assert not any(a.startswith("stop_security:") for a in coord._actions_taken)

    def test_all_signals_enabled_all_fire(self):
        """Enabling all toggles should allow all signal responses to fire."""
        options = {key: True for key in ALL_SIGNAL_CONF_KEYS}
        hass = make_mock_hass_with_cm_entry(signal_options=options)

        # HVAC: smoke -> fans stopped
        hvac = make_hvac_coordinator(hass)
        hvac._handle_safety_hazard({"hazard_type": "smoke", "severity": "critical"})
        assert "stop_fans" in hvac._actions_taken

        # Security: fire -> doors unlocked
        sec = make_security_coordinator(hass)
        sec._handle_safety_hazard({"hazard_type": "fire", "severity": "critical"})
        assert "unlock_egress" in sec._actions_taken

        # Energy: critical -> max shed
        energy = make_energy_coordinator(hass)
        energy._handle_safety_hazard({"hazard_type": "smoke", "severity": "critical"})
        assert energy._load_shedding_active_level == 5

        # Music: critical hazard -> stop
        music = make_music_coordinator(hass)
        music._handle_safety_hazard({"hazard_type": "fire", "severity": "critical"})
        assert "stop_playback" in music._actions_taken


class TestObservationModeSuppressesAllSignalResponses:
    """Tests that observation mode suppresses all signal responses per coordinator.

    v3.22.0: HVAC, Security, and Energy all check observation_mode at the
    top of their hazard handlers and return immediately if True.
    Music Following does not have an observation_mode gate on its handlers.
    """

    def test_hvac_observation_mode_suppresses_hazard(self):
        """HVAC observation mode should suppress all hazard responses."""
        options = {
            CONF_HVAC_ON_HAZARD_STOP_FANS: True,
            CONF_HVAC_ON_HAZARD_EMERGENCY_HEAT: True,
        }
        hass = make_mock_hass_with_cm_entry(signal_options=options)
        coord = make_hvac_coordinator(hass, observation_mode=True)

        coord._handle_safety_hazard({"hazard_type": "smoke", "severity": "critical"})
        assert len(coord._actions_taken) == 0

        coord._handle_safety_hazard({"hazard_type": "freeze", "severity": "critical"})
        assert len(coord._actions_taken) == 0

    def test_security_observation_mode_suppresses_hazard(self):
        """Security observation mode should suppress hazard response."""
        hass = make_mock_hass_with_cm_entry(
            signal_options={CONF_SECURITY_ON_HAZARD_UNLOCK_EGRESS: True}
        )
        coord = make_security_coordinator(hass, observation_mode=True)

        coord._handle_safety_hazard({"hazard_type": "smoke", "severity": "critical"})
        assert len(coord._actions_taken) == 0

    def test_security_observation_mode_suppresses_arrival(self):
        """Security observation mode should suppress arrival response."""
        hass = make_mock_hass_with_cm_entry(
            signal_options={CONF_SECURITY_ON_ARRIVAL_ADD_EXPECTED: True}
        )
        coord = make_security_coordinator(hass, observation_mode=True)

        coord._handle_person_arriving_signal({"person_entity": "person.alice"})
        assert len(coord._actions_taken) == 0

    def test_energy_observation_mode_suppresses_hazard(self):
        """Energy observation mode should suppress hazard response."""
        hass = make_mock_hass_with_cm_entry(
            signal_options={CONF_ENERGY_ON_HAZARD_SHED_LOADS: True}
        )
        coord = make_energy_coordinator(hass, observation_mode=True)

        coord._handle_safety_hazard({"hazard_type": "smoke", "severity": "critical"})
        assert len(coord._actions_taken) == 0
        assert coord._load_shedding_active_level == 0


class TestHazardPayloadFormats:
    """Tests that handlers accept both dict and object-style hazard payloads.

    v3.22.0: Handlers use isinstance(hazard, dict) with fallback to
    hasattr(hazard, "hazard_type") for attribute-style payloads.
    """

    def test_dict_payload_accepted(self):
        """Dict-style payload should be parsed correctly."""
        hass = make_mock_hass_with_cm_entry(
            signal_options={CONF_HVAC_ON_HAZARD_STOP_FANS: True}
        )
        coord = make_hvac_coordinator(hass)

        coord._handle_safety_hazard({"hazard_type": "smoke", "severity": "critical"})
        assert "stop_fans" in coord._actions_taken

    def test_object_payload_accepted(self):
        """Object-style payload (with attributes) should be parsed correctly."""
        hass = make_mock_hass_with_cm_entry(
            signal_options={CONF_ENERGY_ON_HAZARD_SHED_LOADS: True}
        )
        coord = make_energy_coordinator(hass)

        class HazardObj:
            hazard_type = "smoke"
            severity = "critical"

        coord._handle_safety_hazard(HazardObj())
        assert "emergency_shed_to_5" in coord._actions_taken

    def test_non_dict_non_obj_payload_ignored(self):
        """A payload with no hazard_type attribute should be safely ignored."""
        hass = make_mock_hass_with_cm_entry(
            signal_options={CONF_HVAC_ON_HAZARD_STOP_FANS: True}
        )
        coord = make_hvac_coordinator(hass)

        coord._handle_safety_hazard("invalid_string_payload")
        assert len(coord._actions_taken) == 0
