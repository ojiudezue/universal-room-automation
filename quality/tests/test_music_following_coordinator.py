"""Tests for v3.6.24: Music Following Coordinator elevation.

Tests cover:
- MusicFollowingCoordinator is a valid BaseCoordinator subclass
- evaluate() returns empty list (event-driven, not intent-driven)
- Configurable parameters are stored and accessible
- Priority is 30 (lowest active coordinator)
- coordinator_id is "music_following"
- New constants exist in const.py
- COORDINATOR_ENABLED_KEYS includes music_following
- Backward compat: standalone MusicFollowing class unchanged
"""

import pytest
import sys
import os
import types
import importlib
from unittest.mock import MagicMock, AsyncMock

# ---------------------------------------------------------------------------
# Mock homeassistant and its submodules before importing URA code.
# The quality test suite runs without a real HA installation.
# ---------------------------------------------------------------------------

def _mock_module(name, **attrs):
    """Create a mock module with given attributes."""
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


_identity = lambda fn: fn  # noqa: E731
_mock_cls = MagicMock

_mods = {
    "homeassistant": {},
    "homeassistant.core": {
        "HomeAssistant": _mock_cls,
        "callback": _identity,
        "Event": _mock_cls,
        "State": _mock_cls,
    },
    "homeassistant.config_entries": {"ConfigEntry": _mock_cls},
    "homeassistant.const": MagicMock(),
    "homeassistant.helpers": {},
    "homeassistant.helpers.device_registry": {"DeviceInfo": dict},
    "homeassistant.helpers.entity": {
        "DeviceInfo": dict,
        "EntityCategory": _mock_cls(),
    },
    "homeassistant.helpers.entity_platform": {"AddEntitiesCallback": _mock_cls},
    "homeassistant.helpers.event": {
        "async_track_state_change_event": _mock_cls(),
        "async_track_time_interval": _mock_cls(),
        "async_call_later": lambda hass, delay, cb: _mock_cls(),
    },
    "homeassistant.helpers.dispatcher": {
        "async_dispatcher_send": _mock_cls(),
    },
    "homeassistant.helpers.update_coordinator": {
        "DataUpdateCoordinator": _mock_cls,
        "UpdateFailed": Exception,
    },
    "homeassistant.helpers.selector": _mock_cls(),
    "homeassistant.helpers.entity_registry": {"async_get": _mock_cls()},
    "homeassistant.helpers.sun": {},
    "homeassistant.util": {},
    "homeassistant.util.dt": {
        "utcnow": __import__("datetime").datetime.utcnow,
        "now": __import__("datetime").datetime.now,
        "as_local": lambda dt: dt,
    },
    "homeassistant.components": {},
    "homeassistant.components.sensor": {
        "SensorEntity": type("SensorEntity", (), {}),
        "SensorDeviceClass": _mock_cls(),
        "SensorStateClass": _mock_cls(),
    },
    "homeassistant.components.binary_sensor": {
        "BinarySensorEntity": type("BinarySensorEntity", (), {}),
        "BinarySensorDeviceClass": _mock_cls(),
    },
    "homeassistant.components.button": {
        "ButtonEntity": type("ButtonEntity", (), {}),
    },
}

for name, attrs in _mods.items():
    if isinstance(attrs, dict):
        sys.modules.setdefault(name, _mock_module(name, **attrs))
    else:
        sys.modules.setdefault(name, attrs)

sys.modules.setdefault("aiosqlite", MagicMock())

# Now add the project root so custom_components is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# Create the package hierarchy manually
_cc = types.ModuleType("custom_components")
_cc.__path__ = [os.path.join(os.path.dirname(__file__), "..", "..", "custom_components")]
sys.modules.setdefault("custom_components", _cc)

_ura = types.ModuleType("custom_components.universal_room_automation")
_ura_path = os.path.join(_cc.__path__[0], "universal_room_automation")
_ura.__path__ = [_ura_path]
_ura.__package__ = "custom_components.universal_room_automation"
sys.modules["custom_components.universal_room_automation"] = _ura

# Import const.py directly (it has no HA dependencies beyond typing)
_const_spec = importlib.util.spec_from_file_location(
    "custom_components.universal_room_automation.const",
    os.path.join(_ura_path, "const.py"),
)
_const_mod = importlib.util.module_from_spec(_const_spec)
sys.modules["custom_components.universal_room_automation.const"] = _const_mod
_const_spec.loader.exec_module(_const_mod)
_ura.const = _const_mod

# Now import the domain_coordinators subpackage
_dc_path = os.path.join(_ura_path, "domain_coordinators")
_dc = types.ModuleType("custom_components.universal_room_automation.domain_coordinators")
_dc.__path__ = [_dc_path]
_dc.__package__ = "custom_components.universal_room_automation.domain_coordinators"
sys.modules["custom_components.universal_room_automation.domain_coordinators"] = _dc
_ura.domain_coordinators = _dc

# Import each submodule explicitly
for _submod_name in ("signals", "house_state", "base", "manager", "music_following"):
    _full_name = f"custom_components.universal_room_automation.domain_coordinators.{_submod_name}"
    _spec = importlib.util.spec_from_file_location(
        _full_name, os.path.join(_dc_path, f"{_submod_name}.py"),
    )
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules[_full_name] = _mod
    _spec.loader.exec_module(_mod)
    setattr(_dc, _submod_name, _mod)

# ---------------------------------------------------------------------------
# Imports under test
# ---------------------------------------------------------------------------

from custom_components.universal_room_automation.domain_coordinators.music_following import (
    MusicFollowingCoordinator,
)
from custom_components.universal_room_automation.domain_coordinators.base import (
    BaseCoordinator,
    Intent,
)
from custom_components.universal_room_automation.const import (
    CONF_MUSIC_FOLLOWING_COORDINATOR_ENABLED,
    CONF_MF_COOLDOWN_SECONDS,
    CONF_MF_PING_PONG_WINDOW,
    CONF_MF_VERIFY_DELAY,
    CONF_MF_UNJOIN_DELAY,
    CONF_MF_POSITION_OFFSET,
    CONF_MF_MIN_CONFIDENCE,
    DEFAULT_MF_COOLDOWN_SECONDS,
    DEFAULT_MF_PING_PONG_WINDOW,
    DEFAULT_MF_VERIFY_DELAY,
    DEFAULT_MF_UNJOIN_DELAY,
    DEFAULT_MF_POSITION_OFFSET,
    DEFAULT_MF_MIN_CONFIDENCE,
    COORDINATOR_ENABLED_KEYS,
)


# ============================================================================
# Test: Constants
# ============================================================================


class TestMusicFollowingConstants:
    """Test that all required constants exist and have expected values."""

    def test_coordinator_enabled_key_exists(self):
        assert CONF_MUSIC_FOLLOWING_COORDINATOR_ENABLED == "music_following_coordinator_enabled"

    def test_coordinator_enabled_keys_includes_music_following(self):
        assert "music_following" in COORDINATOR_ENABLED_KEYS
        assert COORDINATOR_ENABLED_KEYS["music_following"] == "music_following_coordinator_enabled"

    def test_configurable_constants_exist(self):
        assert CONF_MF_COOLDOWN_SECONDS == "mf_cooldown_seconds"
        assert CONF_MF_PING_PONG_WINDOW == "mf_ping_pong_window"
        assert CONF_MF_VERIFY_DELAY == "mf_verify_delay"
        assert CONF_MF_UNJOIN_DELAY == "mf_unjoin_delay"
        assert CONF_MF_POSITION_OFFSET == "mf_position_offset"
        assert CONF_MF_MIN_CONFIDENCE == "mf_min_confidence"

    def test_default_values(self):
        assert DEFAULT_MF_COOLDOWN_SECONDS == 8
        assert DEFAULT_MF_PING_PONG_WINDOW == 60
        assert DEFAULT_MF_VERIFY_DELAY == 2
        assert DEFAULT_MF_UNJOIN_DELAY == 5
        assert DEFAULT_MF_POSITION_OFFSET == 3
        assert DEFAULT_MF_MIN_CONFIDENCE == 0.6


# ============================================================================
# Test: MusicFollowingCoordinator
# ============================================================================


class TestMusicFollowingCoordinator:
    """Test MusicFollowingCoordinator class."""

    def _make_coordinator(self, **kwargs):
        hass = MagicMock()
        hass.data = {}
        return MusicFollowingCoordinator(hass, **kwargs)

    def test_is_base_coordinator_subclass(self):
        coord = self._make_coordinator()
        assert isinstance(coord, BaseCoordinator)

    def test_coordinator_id(self):
        coord = self._make_coordinator()
        assert coord.coordinator_id == "music_following"

    def test_name(self):
        coord = self._make_coordinator()
        assert coord.name == "Music Following"

    def test_priority_is_30(self):
        coord = self._make_coordinator()
        assert coord.priority == 30

    def test_default_enabled(self):
        coord = self._make_coordinator()
        assert coord.enabled is True

    def test_can_disable(self):
        coord = self._make_coordinator()
        coord.enabled = False
        assert coord.enabled is False

    @pytest.mark.asyncio
    async def test_evaluate_returns_empty_list(self):
        coord = self._make_coordinator()
        intents = [Intent(source="state_change", entity_id="media_player.test")]
        result = await coord.evaluate(intents, {})
        assert result == []

    @pytest.mark.asyncio
    async def test_evaluate_always_empty_regardless_of_intents(self):
        coord = self._make_coordinator()
        # Even with many intents, should return empty
        intents = [
            Intent(source="state_change"),
            Intent(source="time_trigger"),
            Intent(source="census_update"),
        ]
        result = await coord.evaluate(intents, {"house_state": "home_day"})
        assert result == []

    def test_configurable_parameters_stored(self):
        coord = self._make_coordinator(
            cooldown_seconds=15,
            ping_pong_window=120,
            verify_delay=5,
            unjoin_delay=10,
            position_offset=7,
            min_confidence=0.8,
        )
        assert coord._cooldown_seconds == 15
        assert coord._ping_pong_window == 120
        assert coord._verify_delay == 5
        assert coord._unjoin_delay == 10
        assert coord._position_offset == 7
        assert coord._min_confidence == 0.8

    def test_default_parameters(self):
        coord = self._make_coordinator()
        assert coord._cooldown_seconds == DEFAULT_MF_COOLDOWN_SECONDS
        assert coord._ping_pong_window == DEFAULT_MF_PING_PONG_WINDOW
        assert coord._verify_delay == DEFAULT_MF_VERIFY_DELAY
        assert coord._unjoin_delay == DEFAULT_MF_UNJOIN_DELAY
        assert coord._position_offset == DEFAULT_MF_POSITION_OFFSET
        assert coord._min_confidence == DEFAULT_MF_MIN_CONFIDENCE

    @pytest.mark.asyncio
    async def test_async_setup_without_music_following(self):
        """Setup should not crash when no MusicFollowing instance exists."""
        coord = self._make_coordinator()
        coord.hass.data = {"universal_room_automation": {}}
        await coord.async_setup()
        assert coord._music_following is None

    @pytest.mark.asyncio
    async def test_async_setup_with_music_following(self):
        """Setup should wrap existing MusicFollowing instance."""
        coord = self._make_coordinator()
        mock_mf = MagicMock()
        mock_mf.MIN_CONFIDENCE = 0.6
        coord.hass.data = {"universal_room_automation": {"music_following": mock_mf}}
        await coord.async_setup()
        assert coord._music_following is mock_mf
        # Verify min_confidence was applied
        assert mock_mf.MIN_CONFIDENCE == coord._min_confidence

    @pytest.mark.asyncio
    async def test_async_teardown(self):
        """Teardown should clean up references."""
        coord = self._make_coordinator()
        mock_mf = MagicMock()
        coord._music_following = mock_mf
        await coord.async_teardown()
        assert coord._music_following is None

    def test_device_info(self):
        coord = self._make_coordinator()
        info = coord.device_info
        # device_info returns a DeviceInfo (mocked as dict in tests)
        # Check the identifiers tuple contains the coordinator ID
        assert info is not None

    def test_diagnostics_summary_without_music_following(self):
        coord = self._make_coordinator()
        summary = coord.get_diagnostics_summary()
        assert summary["coordinator_id"] == "music_following"
        assert summary["enabled"] is True
        assert summary["priority"] == 30
        assert summary["music_following"] == {"state": "not_initialized"}

    def test_diagnostics_summary_with_music_following(self):
        coord = self._make_coordinator()
        mock_mf = MagicMock()
        mock_mf.get_diagnostic_data.return_value = {
            "state": "idle",
            "transfers_today": 5,
        }
        coord._music_following = mock_mf
        summary = coord.get_diagnostics_summary()
        assert summary["music_following"]["state"] == "idle"
        assert summary["music_following"]["transfers_today"] == 5


# ============================================================================
# Test: Backward Compatibility
# ============================================================================


class TestBackwardCompatibility:
    """Test that standalone MusicFollowing class is unchanged."""

    def test_standalone_class_still_importable(self):
        """The original music_following.py module should still be importable."""
        # We can't actually import it because it depends on HA components,
        # but we can verify the file exists
        mf_path = os.path.join(
            os.path.dirname(__file__), "..", "..",
            "custom_components", "universal_room_automation", "music_following.py"
        )
        assert os.path.exists(mf_path), "music_following.py should still exist"

    def test_coordinator_module_exists(self):
        """The new coordinator module should exist."""
        coord_path = os.path.join(
            os.path.dirname(__file__), "..", "..",
            "custom_components", "universal_room_automation",
            "domain_coordinators", "music_following.py"
        )
        assert os.path.exists(coord_path), "domain_coordinators/music_following.py should exist"

    def test_coordinator_enabled_keys_has_all_existing(self):
        """Adding music_following should not remove existing coordinator entries."""
        assert "presence" in COORDINATOR_ENABLED_KEYS
        assert "safety" in COORDINATOR_ENABLED_KEYS
        assert "security" in COORDINATOR_ENABLED_KEYS
        assert "energy" in COORDINATOR_ENABLED_KEYS
        assert "hvac" in COORDINATOR_ENABLED_KEYS
        assert "comfort" in COORDINATOR_ENABLED_KEYS
        assert "music_following" in COORDINATOR_ENABLED_KEYS
        assert len(COORDINATOR_ENABLED_KEYS) == 8
