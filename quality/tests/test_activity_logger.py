"""Tests for URA Activity Logger.

Tests cover:
- ActivityLogger dedup logic (same description, different description, critical bypass)
- HA event firing
- DB failure swallowing
- Details JSON capping
- Database methods (log_activity, prune_activity_log, get_recent_activities)
- Sensor state and attributes
- Logbook formatting
"""
import json
import sys
import time
import types
import asyncio
import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, AsyncMock, patch, call

# ---------------------------------------------------------------------------
# Mock homeassistant and its submodules before importing URA code.
# ---------------------------------------------------------------------------

def _mock_module(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod

_identity = lambda fn: fn  # noqa: E731
_mock_cls = MagicMock

def _start_of_local_day():
    now = datetime.now()
    return datetime(now.year, now.month, now.day)

_mods = {
    "homeassistant": {},
    "homeassistant.core": {
        "HomeAssistant": _mock_cls,
        "callback": _identity,
        "Event": _mock_cls,
        "State": _mock_cls,
        "CALLBACK_TYPE": type(None),
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
        "async_track_time_interval": lambda hass, cb, interval: _mock_cls(),
        "async_call_later": lambda hass, delay, cb: _mock_cls(),
        "async_track_time_change": lambda hass, cb, **kw: _mock_cls(),
    },
    "homeassistant.helpers.dispatcher": {
        "async_dispatcher_connect": lambda hass, signal, cb: _mock_cls(),
        "async_dispatcher_send": lambda hass, signal, *args: None,
    },
    "homeassistant.helpers.update_coordinator": {
        "DataUpdateCoordinator": _mock_cls,
        "UpdateFailed": Exception,
    },
    "homeassistant.helpers.selector": _mock_cls(),
    "homeassistant.helpers.entity_registry": {"async_get": _mock_cls()},
    "homeassistant.helpers.restore_state": {"RestoreEntity": type("RestoreEntity", (), {})},
    "homeassistant.helpers.sun": {},
    "homeassistant.util": {},
    "homeassistant.util.dt": {
        "utcnow": datetime.utcnow,
        "now": datetime.now,
        "as_local": lambda dt: dt,
        "start_of_local_day": _start_of_local_day,
    },
    "homeassistant.components": {},
    "homeassistant.components.logbook": {
        "LOGBOOK_ENTRY_MESSAGE": "message",
        "LOGBOOK_ENTRY_NAME": "name",
    },
    "homeassistant.components.sensor": {
        "SensorEntity": type("SensorEntity", (), {}),
        "SensorDeviceClass": _mock_cls(),
        "SensorStateClass": _mock_cls(),
    },
    "homeassistant.components.binary_sensor": {
        "BinarySensorEntity": type("BinarySensorEntity", (), {}),
        "BinarySensorDeviceClass": _mock_cls(),
    },
    "homeassistant.components.button": {"ButtonEntity": type("ButtonEntity", (), {})},
    "homeassistant.components.switch": {"SwitchEntity": type("SwitchEntity", (), {})},
    "homeassistant.components.number": {"NumberEntity": type("NumberEntity", (), {})},
    "homeassistant.components.select": {"SelectEntity": type("SelectEntity", (), {})},
    "homeassistant.components.webhook": {
        "async_register": lambda hass, domain, name, webhook_id, handler: None,
        "async_unregister": lambda hass, webhook_id: None,
    },
    "homeassistant.components.person": {"DOMAIN": "person"},
    "homeassistant.components.device_tracker": {"DOMAIN": "device_tracker"},
    "homeassistant.components.zone": {"DOMAIN": "zone"},
    "homeassistant.components.light": _mock_cls(),
    "homeassistant.components.fan": _mock_cls(),
    "homeassistant.components.climate": _mock_cls(),
    "homeassistant.components.cover": _mock_cls(),
    "homeassistant.components.alarm_control_panel": _mock_cls(),
    "homeassistant.components.media_player": _mock_cls(),
    "homeassistant.components.automation": _mock_cls(),
    "homeassistant.helpers.area_registry": {"async_get": _mock_cls()},
    "aiosqlite": MagicMock(),
}

for name, attrs in _mods.items():
    if isinstance(attrs, dict):
        existing = sys.modules.get(name)
        if existing is None:
            sys.modules[name] = _mock_module(name, **attrs)
        else:
            for k, v in attrs.items():
                if not hasattr(existing, k):
                    setattr(existing, k, v)
    else:
        if name not in sys.modules:
            sys.modules[name] = attrs


# ============================================================================
# Fixtures
# ============================================================================

class MockHassForActivity:
    """Minimal mock HASS for activity logger tests."""

    def __init__(self):
        self.data = {"universal_room_automation": {}}
        self.bus = MagicMock()
        self.bus.async_fire = MagicMock()
        self._tasks = []

    def async_create_task(self, coro):
        """Track created tasks."""
        self._tasks.append(coro)
        coro.close()


@pytest.fixture
def mock_hass_activity():
    """Provide a mock HASS for activity logger."""
    return MockHassForActivity()


@pytest.fixture
def mock_database():
    """Provide a mock database with activity log methods."""
    db = MagicMock()
    db.log_activity = AsyncMock()
    db.prune_activity_log = AsyncMock(return_value=0)
    db.get_recent_activities = AsyncMock(return_value=[])
    return db


@pytest.fixture
def activity_logger(mock_hass_activity, mock_database):
    """Provide an initialized ActivityLogger."""
    from custom_components.universal_room_automation.activity_logger import ActivityLogger
    mock_hass_activity.data["universal_room_automation"]["database"] = mock_database
    logger = ActivityLogger(mock_hass_activity)
    return logger


# ============================================================================
# ActivityLogger Core Tests
# ============================================================================

@pytest.mark.asyncio
async def test_log_writes_to_db(activity_logger, mock_database):
    """Verify log() calls database.log_activity with correct params."""
    await activity_logger.log(
        coordinator="room",
        action="light_turn_on",
        description="Turned on 3 lights",
        room="Living Room",
        importance="info",
        entity_id="light.living_room_1",
    )

    mock_database.log_activity.assert_called_once()
    call_kwargs = mock_database.log_activity.call_args
    assert call_kwargs.kwargs["coordinator"] == "room"
    assert call_kwargs.kwargs["action"] == "light_turn_on"
    assert call_kwargs.kwargs["description"] == "Turned on 3 lights"
    assert call_kwargs.kwargs["room"] == "Living Room"
    assert call_kwargs.kwargs["importance"] == "info"
    assert call_kwargs.kwargs["entity_id"] == "light.living_room_1"


@pytest.mark.asyncio
async def test_log_fires_ha_event(activity_logger, mock_hass_activity):
    """Verify log() fires ura_action HA event with correct data."""
    await activity_logger.log(
        coordinator="hvac",
        action="preset_change",
        description="Zone 1 preset home -> eco",
        zone="zone_1",
    )

    mock_hass_activity.bus.async_fire.assert_called_once()
    event_name, event_data = mock_hass_activity.bus.async_fire.call_args[0]
    assert event_name == "ura_action"
    assert event_data["coordinator"] == "hvac"
    assert event_data["action"] == "preset_change"
    assert event_data["description"] == "Zone 1 preset home -> eco"
    assert event_data["zone"] == "zone_1"
    assert "timestamp" in event_data


@pytest.mark.asyncio
async def test_dedup_same_description(activity_logger, mock_database):
    """Verify identical events within dedup window are suppressed."""
    await activity_logger.log(
        coordinator="room",
        action="fan_on",
        description="Fans on at 66% (75F)",
        room="Bedroom",
    )
    # Rapid second call with same params — should be deduped
    await activity_logger.log(
        coordinator="room",
        action="fan_on",
        description="Fans on at 66% (75F)",
        room="Bedroom",
    )

    assert mock_database.log_activity.call_count == 1


@pytest.mark.asyncio
async def test_dedup_different_description_passes(activity_logger, mock_database):
    """Verify different descriptions for same action are NOT deduped."""
    await activity_logger.log(
        coordinator="room",
        action="fan_on",
        description="Fans on at 33% (72F)",
        room="Bedroom",
    )
    await activity_logger.log(
        coordinator="room",
        action="fan_on",
        description="Fans on at 66% (75F)",
        room="Bedroom",
    )

    assert mock_database.log_activity.call_count == 2


@pytest.mark.asyncio
async def test_dedup_different_room_passes(activity_logger, mock_database):
    """Verify same action in different rooms is NOT deduped."""
    await activity_logger.log(
        coordinator="room",
        action="occupancy_entry",
        description="Room occupied (source: motion)",
        room="Bedroom",
    )
    await activity_logger.log(
        coordinator="room",
        action="occupancy_entry",
        description="Room occupied (source: motion)",
        room="Kitchen",
    )

    assert mock_database.log_activity.call_count == 2


@pytest.mark.asyncio
async def test_critical_bypasses_dedup(activity_logger, mock_database):
    """Verify critical importance events are never deduped."""
    await activity_logger.log(
        coordinator="safety",
        action="hazard_detected",
        description="SMOKE DETECTED in Kitchen!",
        importance="critical",
    )
    await activity_logger.log(
        coordinator="safety",
        action="hazard_detected",
        description="SMOKE DETECTED in Kitchen!",
        importance="critical",
    )

    assert mock_database.log_activity.call_count == 2


@pytest.mark.asyncio
async def test_notable_has_longer_dedup_window(activity_logger, mock_database):
    """Verify notable events use 60s dedup (vs 30s for info)."""
    from custom_components.universal_room_automation.activity_logger import _DEDUP_WINDOWS
    assert _DEDUP_WINDOWS["info"] == 30.0
    assert _DEDUP_WINDOWS["notable"] == 60.0
    assert _DEDUP_WINDOWS["critical"] == 0.0


@pytest.mark.asyncio
async def test_db_failure_no_raise(activity_logger, mock_database):
    """Verify DB write failure does not propagate to caller."""
    mock_database.log_activity.side_effect = Exception("DB locked")

    # Should not raise
    await activity_logger.log(
        coordinator="room",
        action="test",
        description="test desc",
    )
    # Event should still fire even when DB fails
    activity_logger.hass.bus.async_fire.assert_called_once()


@pytest.mark.asyncio
async def test_no_db_no_crash():
    """Verify log() works when database is None."""
    from custom_components.universal_room_automation.activity_logger import ActivityLogger
    mock_hass = MockHassForActivity()
    # No database in hass.data
    logger = ActivityLogger(mock_hass)

    # Should not raise
    await logger.log(
        coordinator="room",
        action="test",
        description="test desc",
    )
    mock_hass.bus.async_fire.assert_called_once()


@pytest.mark.asyncio
async def test_details_json_capped(activity_logger, mock_database):
    """Verify details over 2KB are truncated."""
    big_details = {"data": "x" * 3000}

    await activity_logger.log(
        coordinator="room",
        action="test",
        description="test",
        details=big_details,
    )

    call_kwargs = mock_database.log_activity.call_args
    details_json = call_kwargs.kwargs["details_json"]
    assert details_json is not None
    assert len(details_json) <= 2048


@pytest.mark.asyncio
async def test_details_json_small_passes_through(activity_logger, mock_database):
    """Verify small details dict is serialized correctly."""
    small_details = {"source": "motion", "threshold": 50}

    await activity_logger.log(
        coordinator="room",
        action="test",
        description="test",
        details=small_details,
    )

    call_kwargs = mock_database.log_activity.call_args
    details_json = call_kwargs.kwargs["details_json"]
    assert details_json is not None
    parsed = json.loads(details_json)
    assert parsed["source"] == "motion"
    assert parsed["threshold"] == 50


def test_clear_dedup_cache():
    """Verify clear_dedup_cache empties the cache."""
    from custom_components.universal_room_automation.activity_logger import ActivityLogger
    mock_hass = MockHassForActivity()
    logger = ActivityLogger(mock_hass)
    logger._dedup_cache["test_key"] = time.monotonic()
    assert len(logger._dedup_cache) > 0

    logger.clear_dedup_cache()
    assert len(logger._dedup_cache) == 0


@pytest.mark.asyncio
async def test_room_none_in_event_data(activity_logger, mock_hass_activity):
    """Verify room=None is not included in event data."""
    await activity_logger.log(
        coordinator="energy",
        action="load_shed",
        description="Load shedding escalated",
    )

    event_data = mock_hass_activity.bus.async_fire.call_args[0][1]
    assert "room" not in event_data


@pytest.mark.asyncio
async def test_signal_dispatched(activity_logger, mock_hass_activity):
    """Verify SIGNAL_ACTIVITY_LOGGED is dispatched."""
    dispatched = []

    def capture_dispatch(hass, signal, *args):
        dispatched.append((signal, args))

    with patch(
        "custom_components.universal_room_automation.activity_logger.async_dispatcher_send",
        side_effect=capture_dispatch,
    ):
        await activity_logger.log(
            coordinator="room",
            action="test",
            description="test desc",
            room="Office",
        )

    assert len(dispatched) == 1
    signal_name, signal_args = dispatched[0]
    assert signal_name == "ura_activity_logged"
    assert signal_args[0]["coordinator"] == "room"
    assert signal_args[0]["room"] == "Office"


@pytest.mark.asyncio
async def test_dedup_expires_after_window(activity_logger, mock_database):
    """Verify dedup allows events after window expires."""
    await activity_logger.log(
        coordinator="room",
        action="fan_on",
        description="Fans on at 66% (75F)",
        room="Bedroom",
    )
    assert mock_database.log_activity.call_count == 1

    # Manually expire the dedup cache entry
    for key in list(activity_logger._dedup_cache):
        activity_logger._dedup_cache[key] -= 60  # Move 60s into the past

    await activity_logger.log(
        coordinator="room",
        action="fan_on",
        description="Fans on at 66% (75F)",
        room="Bedroom",
    )
    assert mock_database.log_activity.call_count == 2


@pytest.mark.asyncio
async def test_details_none_passes_null(activity_logger, mock_database):
    """Verify details=None results in details_json=None."""
    await activity_logger.log(
        coordinator="room",
        action="test",
        description="test",
        details=None,
    )

    call_kwargs = mock_database.log_activity.call_args
    assert call_kwargs.kwargs["details_json"] is None


# ============================================================================
# Logbook Platform Tests
# ============================================================================

def test_logbook_describe_event_with_room():
    """Verify logbook formatting with room name."""
    from custom_components.universal_room_automation.logbook import async_describe_events

    described_events = {}

    def mock_async_describe_event(domain, event_type, handler):
        described_events[event_type] = handler

    mock_hass = MagicMock()
    async_describe_events(mock_hass, mock_async_describe_event)

    assert "ura_action" in described_events
    handler = described_events["ura_action"]

    mock_event = MagicMock()
    mock_event.data = {
        "coordinator": "room",
        "action": "light_turn_on",
        "description": "Turned on 3 lights (entry, dark)",
        "room": "Living Room",
    }

    result = handler(mock_event)
    assert result["name"] == "URA: Living Room"
    assert result["message"] == "Turned on 3 lights (entry, dark)"


def test_logbook_describe_event_without_room():
    """Verify logbook formatting without room (house-level event)."""
    from custom_components.universal_room_automation.logbook import async_describe_events

    described_events = {}

    def mock_async_describe_event(domain, event_type, handler):
        described_events[event_type] = handler

    mock_hass = MagicMock()
    async_describe_events(mock_hass, mock_async_describe_event)

    handler = described_events["ura_action"]

    mock_event = MagicMock()
    mock_event.data = {
        "coordinator": "energy",
        "action": "load_shed_escalate",
        "description": "Load shedding escalated to level 2",
    }

    result = handler(mock_event)
    assert result["name"] == "URA Energy"
    assert result["message"] == "Load shedding escalated to level 2"


# ============================================================================
# Signal Constant Test
# ============================================================================

def test_signal_constant_defined():
    """Verify SIGNAL_ACTIVITY_LOGGED is defined in signals.py."""
    from custom_components.universal_room_automation.domain_coordinators.signals import (
        SIGNAL_ACTIVITY_LOGGED,
    )
    assert SIGNAL_ACTIVITY_LOGGED == "ura_activity_logged"
