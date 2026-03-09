"""Tests for Notification Manager (v3.6.29).

Tests cover:
- NM instantiation and configuration
- Severity routing and channel qualification
- Quiet hours logic
- Deduplication
- Ack state machine transitions
- Digest formatting
- Channel health tracking
- Severity ordering and dedup windows
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
import sys
import os
import types

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

# Provide start_of_local_day for database.py
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
        "async_dispatcher_send": lambda hass, signal, data=None: None,
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
    "homeassistant.components.webhook": {
        "async_register": lambda hass, domain, name, webhook_id, handler: None,
        "async_unregister": lambda hass, webhook_id: None,
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
    "homeassistant.components.button": {
        "ButtonEntity": type("ButtonEntity", (), {}),
    },
    "homeassistant.components.switch": {
        "SwitchEntity": type("SwitchEntity", (), {}),
    },
    "homeassistant.components.number": {
        "NumberEntity": type("NumberEntity", (), {}),
    },
    "homeassistant.components.select": {
        "SelectEntity": type("SelectEntity", (), {}),
    },
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

# Now import URA modules via importlib (avoids __init__.py chain on Python 3.9)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import importlib

_cc = types.ModuleType("custom_components")
_cc.__path__ = [os.path.join(os.path.dirname(__file__), "..", "..", "custom_components")]
sys.modules.setdefault("custom_components", _cc)

_ura = types.ModuleType("custom_components.universal_room_automation")
_ura_path = os.path.join(_cc.__path__[0], "universal_room_automation")
_ura.__path__ = [_ura_path]
_ura.__package__ = "custom_components.universal_room_automation"
sys.modules["custom_components.universal_room_automation"] = _ura
_cc.universal_room_automation = _ura

_const_spec = importlib.util.spec_from_file_location(
    "custom_components.universal_room_automation.const",
    os.path.join(_ura_path, "const.py"),
)
_const_mod = importlib.util.module_from_spec(_const_spec)
sys.modules["custom_components.universal_room_automation.const"] = _const_mod
_const_spec.loader.exec_module(_const_mod)
_ura.const = _const_mod

_dc_path = os.path.join(_ura_path, "domain_coordinators")
_dc = types.ModuleType("custom_components.universal_room_automation.domain_coordinators")
_dc.__path__ = [_dc_path]
_dc.__package__ = "custom_components.universal_room_automation.domain_coordinators"
sys.modules["custom_components.universal_room_automation.domain_coordinators"] = _dc
_ura.domain_coordinators = _dc

for _submod_name in ("signals", "house_state", "base", "coordinator_diagnostics", "manager", "notification_manager"):
    _full_name = f"custom_components.universal_room_automation.domain_coordinators.{_submod_name}"
    _spec = importlib.util.spec_from_file_location(
        _full_name, os.path.join(_dc_path, f"{_submod_name}.py"),
    )
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules[_full_name] = _mod
    _spec.loader.exec_module(_mod)
    setattr(_dc, _submod_name, _mod)

from custom_components.universal_room_automation.const import (
    CONF_NM_ENABLED,
    CONF_NM_PUSHOVER_ENABLED,
    CONF_NM_PUSHOVER_SEVERITY,
    CONF_NM_PUSHOVER_SERVICE,
    CONF_NM_COMPANION_ENABLED,
    CONF_NM_COMPANION_SEVERITY,
    CONF_NM_TTS_ENABLED,
    CONF_NM_TTS_SEVERITY,
    CONF_NM_TTS_SPEAKERS,
    CONF_NM_LIGHTS_ENABLED,
    CONF_NM_LIGHTS_SEVERITY,
    CONF_NM_ALERT_LIGHTS,
    CONF_NM_WHATSAPP_ENABLED,
    CONF_NM_WHATSAPP_SEVERITY,
    CONF_NM_PERSONS,
    CONF_NM_PERSON_ENTITY,
    CONF_NM_PERSON_PUSHOVER_KEY,
    CONF_NM_PERSON_COMPANION_SERVICE,
    CONF_NM_PERSON_WHATSAPP_PHONE,
    CONF_NM_PERSON_DELIVERY_PREF,
    CONF_NM_QUIET_USE_HOUSE_STATE,
    CONF_NM_QUIET_MANUAL_START,
    CONF_NM_QUIET_MANUAL_END,
    DOMAIN,
    NM_DELIVERY_IMMEDIATE,
    NM_DELIVERY_DIGEST,
    NM_DELIVERY_OFF,
    CONF_NM_SAFE_WORD,
    CONF_NM_SILENCE_DURATION,
)
import custom_components.universal_room_automation.domain_coordinators.notification_manager as _nm_mod
from custom_components.universal_room_automation.domain_coordinators.notification_manager import (
    AlertState,
    DEDUP_WINDOWS,
    LIGHT_PATTERNS,
    NotificationManager,
    RESPONSE_COMMANDS,
    SEVERITY_MAP,
)
from custom_components.universal_room_automation.domain_coordinators.base import Severity


def _make_hass():
    """Create a mock hass with service calls."""
    hass = MagicMock()
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.bus = MagicMock()
    hass.bus.async_listen = MagicMock(return_value=MagicMock())
    hass.async_create_task = MagicMock(return_value=None)
    hass.states = MagicMock()
    hass.states.get = MagicMock(return_value=None)
    hass.data = {DOMAIN: {}}
    return hass


def _make_config(**overrides):
    """Create a basic NM config."""
    config = {
        CONF_NM_ENABLED: True,
        CONF_NM_PUSHOVER_ENABLED: True,
        CONF_NM_PUSHOVER_SEVERITY: "MEDIUM",
        CONF_NM_PUSHOVER_SERVICE: "notify.pushover",
        CONF_NM_COMPANION_ENABLED: False,
        CONF_NM_TTS_ENABLED: False,
        CONF_NM_LIGHTS_ENABLED: False,
        CONF_NM_WHATSAPP_ENABLED: False,
        CONF_NM_QUIET_USE_HOUSE_STATE: True,
        CONF_NM_PERSONS: [
            {
                CONF_NM_PERSON_ENTITY: "person.test",
                CONF_NM_PERSON_PUSHOVER_KEY: "test_key",
                CONF_NM_PERSON_COMPANION_SERVICE: "",
                CONF_NM_PERSON_WHATSAPP_PHONE: "",
                CONF_NM_PERSON_DELIVERY_PREF: NM_DELIVERY_IMMEDIATE,
            }
        ],
    }
    config.update(overrides)
    return config


# ============================================================================
# Tests
# ============================================================================


class TestNotificationManagerInit:
    """Test NM initialization."""

    def test_create_nm(self):
        """NM can be instantiated with config."""
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config())
        assert nm.enabled is True
        assert nm.alert_state == AlertState.IDLE
        assert nm.active_alert is False
        assert nm.cooldown_remaining == 0
        assert nm.notifications_today == 0

    def test_disabled_nm(self):
        """NM reports disabled when config says so."""
        hass = _make_hass()
        config = _make_config(**{CONF_NM_ENABLED: False})
        nm = NotificationManager(hass, config)
        assert nm.enabled is False

    def test_device_info(self):
        """NM device info has correct identifiers."""
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config())
        info = nm.device_info
        assert (DOMAIN, "notification_manager") in info.get("identifiers", set())


class TestChannelQualification:
    """Test channel severity filtering."""

    def test_pushover_qualifies_medium(self):
        """Pushover at MEDIUM threshold fires for MEDIUM severity."""
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config())
        assert nm._channel_qualifies("pushover", Severity.MEDIUM) is True
        assert nm._channel_qualifies("pushover", Severity.HIGH) is True
        assert nm._channel_qualifies("pushover", Severity.CRITICAL) is True
        assert nm._channel_qualifies("pushover", Severity.LOW) is False

    def test_disabled_channel_never_qualifies(self):
        """Disabled channel never qualifies regardless of severity."""
        hass = _make_hass()
        config = _make_config(**{CONF_NM_PUSHOVER_ENABLED: False})
        nm = NotificationManager(hass, config)
        assert nm._channel_qualifies("pushover", Severity.CRITICAL) is False

    def test_tts_qualifies_critical_only(self):
        """TTS at CRITICAL threshold only fires for CRITICAL."""
        hass = _make_hass()
        config = _make_config(**{
            CONF_NM_TTS_ENABLED: True,
            CONF_NM_TTS_SEVERITY: "CRITICAL",
            CONF_NM_TTS_SPEAKERS: ["media_player.kitchen"],
        })
        nm = NotificationManager(hass, config)
        assert nm._channel_qualifies("tts", Severity.CRITICAL) is True
        assert nm._channel_qualifies("tts", Severity.HIGH) is False

    def test_unknown_channel_never_qualifies(self):
        """Unknown channel name returns False."""
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config())
        assert nm._channel_qualifies("telegram", Severity.CRITICAL) is False


class TestQuietHours:
    """Test quiet hours logic."""

    def test_quiet_hours_manual_overnight(self):
        """Manual quiet hours spanning midnight detected correctly."""
        hass = _make_hass()
        config = _make_config(**{
            CONF_NM_QUIET_USE_HOUSE_STATE: False,
            CONF_NM_QUIET_MANUAL_START: "22:00",
            CONF_NM_QUIET_MANUAL_END: "07:00",
        })
        nm = NotificationManager(hass, config)

        with patch.object(_nm_mod, "dt_util") as mock_dt:
            mock_now = MagicMock()
            mock_now.strftime.return_value = "23:00"
            mock_dt.now.return_value = mock_now
            assert nm._is_quiet_hours() is True

            mock_now.strftime.return_value = "06:00"
            assert nm._is_quiet_hours() is True

            mock_now.strftime.return_value = "12:00"
            assert nm._is_quiet_hours() is False

    def test_quiet_hours_house_state_sleep(self):
        """House state quiet hours triggers on SLEEP."""
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config(**{CONF_NM_QUIET_USE_HOUSE_STATE: True}))
        mock_cm = MagicMock()
        mock_cm.house_state = "sleep"
        hass.data[DOMAIN]["coordinator_manager"] = mock_cm
        assert nm._is_quiet_hours() is True

    def test_quiet_hours_house_state_day(self):
        """Not quiet during home_day."""
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config(**{CONF_NM_QUIET_USE_HOUSE_STATE: True}))
        mock_cm = MagicMock()
        mock_cm.house_state = "home_day"
        hass.data[DOMAIN]["coordinator_manager"] = mock_cm
        assert nm._is_quiet_hours() is False


class TestDeduplication:
    """Test notification deduplication."""

    def test_first_notification_not_deduped(self):
        """First notification is not deduplicated."""
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config())
        assert nm._is_deduplicated("safety", "Smoke", "Kitchen", Severity.CRITICAL) is False

    def test_duplicate_within_window_deduped(self):
        """Same notification within dedup window is suppressed."""
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config())
        nm._is_deduplicated("safety", "Smoke", "Kitchen", Severity.CRITICAL)
        assert nm._is_deduplicated("safety", "Smoke", "Kitchen", Severity.CRITICAL) is True

    def test_different_location_not_deduped(self):
        """Same title at different location is not deduplicated."""
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config())
        nm._is_deduplicated("safety", "Smoke", "Kitchen", Severity.CRITICAL)
        assert nm._is_deduplicated("safety", "Smoke", "Bedroom", Severity.CRITICAL) is False

    def test_different_coordinator_not_deduped(self):
        """Same title from different coordinator is not deduplicated."""
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config())
        nm._is_deduplicated("safety", "Alert", "Kitchen", Severity.HIGH)
        assert nm._is_deduplicated("security", "Alert", "Kitchen", Severity.HIGH) is False


class TestAckStateMachine:
    """Test ack/cooldown/re-fire state machine."""

    def test_initial_state_idle(self):
        """NM starts in IDLE state."""
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config())
        assert nm.alert_state == AlertState.IDLE
        assert nm.active_alert is False

    @pytest.mark.asyncio
    async def test_critical_enters_repeating(self):
        """CRITICAL notification moves to REPEATING state."""
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config())
        await nm._enter_alerting("safety", "CRITICAL", "Fire", "Fire!", "fire", "Kitchen")
        assert nm.alert_state == AlertState.REPEATING
        assert nm.active_alert is True
        assert nm._active_alert_data["hazard_type"] == "fire"

    @pytest.mark.asyncio
    async def test_acknowledge_moves_to_cooldown(self):
        """Acknowledge transitions from REPEATING to COOLDOWN."""
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config())
        mock_db = AsyncMock()
        mock_db.acknowledge_notification = AsyncMock()
        mock_db.get_active_critical = AsyncMock(return_value={"id": 1})
        mock_db.get_active_cooldown = AsyncMock(return_value=None)
        mock_db.set_cooldown = AsyncMock()
        hass.data[DOMAIN]["database"] = mock_db

        await nm._enter_alerting("safety", "CRITICAL", "Fire", "Fire!", "fire", "Kitchen")
        await nm.async_acknowledge()
        assert nm.alert_state == AlertState.COOLDOWN
        assert nm.active_alert is False

    @pytest.mark.asyncio
    async def test_acknowledge_when_idle_no_op(self):
        """Acknowledge when IDLE does nothing."""
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config())
        await nm.async_acknowledge()
        assert nm.alert_state == AlertState.IDLE


class TestDigestFormatting:
    """Test digest message formatting."""

    def test_format_digest_groups_by_coordinator(self):
        """Digest groups notifications by coordinator."""
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config())
        items = [
            {"coordinator_id": "safety", "severity": "HIGH", "title": "Water leak", "location": "Kitchen"},
            {"coordinator_id": "safety", "severity": "MEDIUM", "title": "Humidity", "location": "Bathroom"},
            {"coordinator_id": "energy", "severity": "LOW", "title": "Peak TOU", "location": ""},
        ]
        result = nm._format_digest(items)
        assert "Safety" in result
        assert "Energy" in result
        assert "Water leak" in result

    def test_format_digest_empty(self):
        """Empty digest has header only."""
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config())
        result = nm._format_digest([])
        assert "URA Daily Summary" in result


class TestLightPatterns:
    """Test light pattern definitions."""

    def test_key_hazard_types_have_patterns(self):
        """Key hazard types have light pattern entries."""
        for hazard_type in ["fire", "water_leak", "co", "intruder", "warning"]:
            assert hazard_type in LIGHT_PATTERNS

    def test_pattern_has_effect(self):
        """Each pattern has an effect field."""
        for name, pattern in LIGHT_PATTERNS.items():
            assert "effect" in pattern, f"Missing effect in {name}"


class TestSeverityMap:
    """Test severity string mapping."""

    def test_all_levels_mapped(self):
        """All 4 severity levels are in the map."""
        for level in ["LOW", "MEDIUM", "HIGH", "CRITICAL"]:
            assert level in SEVERITY_MAP

    def test_severity_ordering(self):
        """Severity values are correctly ordered."""
        assert SEVERITY_MAP["LOW"] < SEVERITY_MAP["MEDIUM"]
        assert SEVERITY_MAP["MEDIUM"] < SEVERITY_MAP["HIGH"]
        assert SEVERITY_MAP["HIGH"] < SEVERITY_MAP["CRITICAL"]


class TestDedupWindows:
    """Test dedup window configuration."""

    def test_critical_shortest(self):
        """CRITICAL has the shortest dedup window."""
        assert DEDUP_WINDOWS[Severity.CRITICAL] < DEDUP_WINDOWS[Severity.HIGH]
        assert DEDUP_WINDOWS[Severity.HIGH] < DEDUP_WINDOWS[Severity.MEDIUM]
        assert DEDUP_WINDOWS[Severity.MEDIUM] < DEDUP_WINDOWS[Severity.LOW]


class TestChannelHealth:
    """Test channel health tracking."""

    def test_initial_health_ok(self):
        """All channels start ok."""
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config())
        for health in nm.channel_status.values():
            assert health["status"] == "ok"

    def test_three_failures_degrade(self):
        """3 failures degrade a channel."""
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config())
        nm._update_channel_health("pushover", False)
        nm._update_channel_health("pushover", False)
        nm._update_channel_health("pushover", False)
        assert nm.channel_status["pushover"]["status"] == "degraded"

    def test_success_resets(self):
        """Success resets degraded status."""
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config())
        nm._update_channel_health("pushover", False)
        nm._update_channel_health("pushover", False)
        nm._update_channel_health("pushover", False)
        nm._update_channel_health("pushover", True)
        assert nm.channel_status["pushover"]["status"] == "ok"
        assert nm.channel_status["pushover"]["failures"] == 0


@pytest.mark.asyncio
class TestNotifyRouting:
    """Test async_notify routing to channels."""

    async def test_disabled_nm_no_op(self):
        """Disabled NM does nothing."""
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config(**{CONF_NM_ENABLED: False}))
        await nm.async_notify("safety", Severity.CRITICAL, "Test", "Msg")
        hass.services.async_call.assert_not_called()

    async def test_medium_fires_pushover(self):
        """MEDIUM fires Pushover when enabled at MEDIUM threshold."""
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config())
        await nm.async_notify("safety", Severity.MEDIUM, "Test", "Msg")
        hass.services.async_call.assert_called()
        assert nm.notifications_today == 1
        assert nm.last_notification["severity"] == "MEDIUM"

    async def test_low_suppressed_at_medium_threshold(self):
        """LOW doesn't fire Pushover at MEDIUM threshold."""
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config())
        await nm.async_notify("safety", Severity.LOW, "Test", "Msg")
        # No channels should fire (pushover threshold=MEDIUM, others disabled)
        hass.services.async_call.assert_not_called()

    async def test_quiet_hours_suppress_non_critical(self):
        """Non-CRITICAL suppressed during quiet hours."""
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config())
        mock_cm = MagicMock()
        mock_cm.house_state = "sleep"
        hass.data[DOMAIN]["coordinator_manager"] = mock_cm
        await nm.async_notify("safety", Severity.HIGH, "Test", "Msg")
        hass.services.async_call.assert_not_called()

    async def test_critical_bypasses_quiet_hours(self):
        """CRITICAL bypasses quiet hours."""
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config())
        mock_cm = MagicMock()
        mock_cm.house_state = "sleep"
        hass.data[DOMAIN]["coordinator_manager"] = mock_cm
        await nm.async_notify("safety", Severity.CRITICAL, "Fire", "Fire!")
        hass.services.async_call.assert_called()


class TestTestNotification:
    """Test the test_notification helper."""

    @pytest.mark.asyncio
    async def test_sends_medium_by_default(self):
        """test_notification defaults to MEDIUM severity."""
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config())
        await nm.async_test_notification()
        hass.services.async_call.assert_called()
        assert nm.last_notification["severity"] == "MEDIUM"


class TestDiagnosticCounters:
    """Test diagnostic counters and anomaly detection."""

    @pytest.mark.asyncio
    async def test_delivery_rate_100_initially(self):
        """Delivery rate is 100% with no attempts."""
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config())
        assert nm.delivery_rate == 100.0

    @pytest.mark.asyncio
    async def test_delivery_rate_after_sends(self):
        """Delivery rate tracks send success/failure."""
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config())
        nm._update_channel_health("pushover", True)
        nm._update_channel_health("pushover", True)
        nm._update_channel_health("pushover", False)
        assert nm._send_attempts == 3
        assert nm._send_successes == 2
        assert nm._send_failures == 1
        assert nm.delivery_rate == pytest.approx(66.7, abs=0.1)

    @pytest.mark.asyncio
    async def test_quiet_suppression_counted(self):
        """Quiet hour suppressions are tracked."""
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config(**{CONF_NM_QUIET_USE_HOUSE_STATE: True}))
        mock_cm = MagicMock()
        mock_cm.house_state = "sleep"
        hass.data[DOMAIN]["coordinator_manager"] = mock_cm
        await nm.async_notify("safety", Severity.HIGH, "Test", "Msg")
        assert nm._quiet_suppressions == 1

    @pytest.mark.asyncio
    async def test_dedup_suppression_counted(self):
        """Dedup suppressions are tracked."""
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config())
        await nm.async_notify("safety", Severity.MEDIUM, "Test", "Msg")
        await nm.async_notify("safety", Severity.MEDIUM, "Test", "Msg")
        assert nm._dedup_suppressions == 1

    def test_anomaly_nominal_initially(self):
        """Anomaly status is nominal with no notifications."""
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config())
        assert nm.anomaly_status == "nominal"

    def test_diagnostics_summary_keys(self):
        """Diagnostics summary has expected keys."""
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config())
        summary = nm.diagnostics_summary
        assert "send_attempts" in summary
        assert "delivery_rate" in summary
        assert "dedup_suppressions" in summary
        assert "by_severity" in summary
        assert "by_channel" in summary

    @pytest.mark.asyncio
    async def test_severity_tracking(self):
        """By-severity counter increments correctly."""
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config())
        await nm.async_notify("safety", Severity.MEDIUM, "Test1", "Msg")
        await nm.async_notify("safety", Severity.HIGH, "Test2", "Msg")
        assert nm._notifications_by_severity["MEDIUM"] == 1
        assert nm._notifications_by_severity["HIGH"] == 1


# ============================================================================
# C4b: Inbound Message Handling Tests
# ============================================================================


class TestResponseDictParsing:
    """Test the response dictionary command resolution."""

    def test_ack_aliases(self):
        """All ack aliases resolve to 'ack'."""
        for alias in ("1", "ack", "ok", "acknowledge", "a"):
            assert RESPONSE_COMMANDS[alias] == "ack"

    def test_status_aliases(self):
        """All status aliases resolve to 'status'."""
        for alias in ("2", "status", "s", "info"):
            assert RESPONSE_COMMANDS[alias] == "status"

    def test_silence_aliases(self):
        """All silence aliases resolve to 'silence'."""
        for alias in ("3", "stop", "silence", "mute", "quiet"):
            assert RESPONSE_COMMANDS[alias] == "silence"

    def test_help_aliases(self):
        """All help aliases resolve to 'help'."""
        for alias in ("help", "?", "h"):
            assert RESPONSE_COMMANDS[alias] == "help"

    def test_unknown_command(self):
        """Unknown text is not in the dict."""
        assert RESPONSE_COMMANDS.get("foobar") is None


class TestInboundProcessing:
    """Test _process_inbound_reply behavior."""

    @pytest.mark.asyncio
    async def test_ack_no_active_alert(self):
        """Ack with no active alert returns 'No active alerts'."""
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config())
        response = await nm._process_inbound_reply(None, "companion", "ok")
        assert "No active alerts" in response
        assert nm._inbound_today_count == 1

    @pytest.mark.asyncio
    async def test_status_no_active_alert(self):
        """Status with no active alert returns 'All clear'."""
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config())
        response = await nm._process_inbound_reply(None, "companion", "status")
        assert "All clear" in response

    @pytest.mark.asyncio
    async def test_silence_command(self):
        """Silence command sets silence_until."""
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config(**{CONF_NM_SILENCE_DURATION: 30}))
        response = await nm._process_inbound_reply(None, "companion", "stop")
        assert "silenced for 30 minutes" in response
        assert nm._silence_until is not None

    @pytest.mark.asyncio
    async def test_help_command(self):
        """Help command returns response dict text."""
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config())
        response = await nm._process_inbound_reply(None, "companion", "help")
        assert "Reply:" in response

    @pytest.mark.asyncio
    async def test_unknown_command_returns_help(self):
        """Unknown text returns help text."""
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config())
        response = await nm._process_inbound_reply(None, "companion", "foobar")
        assert "Unknown command" in response
        assert nm._inbound_by_command["unknown"] == 1


class TestSafeWordValidation:
    """Test safe word system for CRITICAL alerts."""

    @pytest.mark.asyncio
    async def test_safe_word_configured_property(self):
        """safe_word_configured is True when word >= 4 chars."""
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config(**{CONF_NM_SAFE_WORD: "myword"}))
        assert nm.safe_word_configured is True

    @pytest.mark.asyncio
    async def test_safe_word_not_configured(self):
        """safe_word_configured is False when empty."""
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config(**{CONF_NM_SAFE_WORD: ""}))
        assert nm.safe_word_configured is False

    @pytest.mark.asyncio
    async def test_safe_word_too_short(self):
        """safe_word_configured is False when < 4 chars."""
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config(**{CONF_NM_SAFE_WORD: "ab"}))
        assert nm.safe_word_configured is False

    @pytest.mark.asyncio
    async def test_ack_rejected_for_critical_without_safe_word(self):
        """Simple 'ok' is rejected when CRITICAL alert is active."""
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config(**{CONF_NM_SAFE_WORD: "myword"}))
        # Manually set CRITICAL alert state
        nm._alert_state = AlertState.REPEATING
        nm._active_alert_data = {
            "coordinator_id": "safety",
            "severity": "CRITICAL",
            "title": "Smoke detected",
            "message": "Smoke in kitchen",
            "hazard_type": "smoke",
            "location": "kitchen",
        }
        response = await nm._process_inbound_reply(None, "companion", "ok")
        assert "safe word" in response.lower()
        # Alert should still be active
        assert nm._alert_state == AlertState.REPEATING

    @pytest.mark.asyncio
    async def test_safe_word_acks_critical(self):
        """Correct safe word acknowledges CRITICAL alert."""
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config(**{CONF_NM_SAFE_WORD: "myword"}))
        nm._alert_state = AlertState.REPEATING
        nm._active_alert_data = {
            "coordinator_id": "safety",
            "severity": "CRITICAL",
            "title": "Smoke detected",
            "message": "Smoke in kitchen",
            "hazard_type": "smoke",
            "location": "kitchen",
        }
        response = await nm._process_inbound_reply(None, "companion", "myword")
        assert "acknowledged" in response.lower()
        assert nm._inbound_by_command["safe_word"] == 1

    @pytest.mark.asyncio
    async def test_safe_word_case_insensitive(self):
        """Safe word matching is case-insensitive."""
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config(**{CONF_NM_SAFE_WORD: "MyWord"}))
        nm._alert_state = AlertState.REPEATING
        nm._active_alert_data = {
            "coordinator_id": "safety",
            "severity": "CRITICAL",
            "title": "Smoke",
            "message": "Smoke detected",
            "hazard_type": "smoke",
            "location": "kitchen",
        }
        response = await nm._process_inbound_reply(None, "companion", "MYWORD")
        assert "acknowledged" in response.lower()

    @pytest.mark.asyncio
    async def test_safe_word_no_active_alert(self):
        """Safe word with no active alert returns no-alert message."""
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config(**{CONF_NM_SAFE_WORD: "myword"}))
        response = await nm._process_inbound_reply(None, "companion", "myword")
        assert "No active alert" in response


class TestPersonMatching:
    """Test person matching from channel metadata."""

    def test_match_by_phone(self):
        """Phone matching uses last 10 digits."""
        hass = _make_hass()
        config = _make_config(**{
            CONF_NM_PERSONS: [{
                CONF_NM_PERSON_ENTITY: "person.john",
                CONF_NM_PERSON_PUSHOVER_KEY: "",
                CONF_NM_PERSON_COMPANION_SERVICE: "",
                CONF_NM_PERSON_WHATSAPP_PHONE: "+11234567890",
                CONF_NM_PERSON_DELIVERY_PREF: NM_DELIVERY_IMMEDIATE,
            }],
        })
        nm = NotificationManager(hass, config)
        assert nm._match_person_by_phone("+11234567890") == "person.john"
        assert nm._match_person_by_phone("1234567890") == "person.john"

    def test_match_by_pushover_key(self):
        """Pushover key matching is exact."""
        hass = _make_hass()
        config = _make_config(**{
            CONF_NM_PERSONS: [{
                CONF_NM_PERSON_ENTITY: "person.jane",
                CONF_NM_PERSON_PUSHOVER_KEY: "pushover_key_123",
                CONF_NM_PERSON_COMPANION_SERVICE: "",
                CONF_NM_PERSON_WHATSAPP_PHONE: "",
                CONF_NM_PERSON_DELIVERY_PREF: NM_DELIVERY_IMMEDIATE,
            }],
        })
        nm = NotificationManager(hass, config)
        assert nm._match_person_by_pushover_key("pushover_key_123") == "person.jane"
        assert nm._match_person_by_pushover_key("wrong_key") is None

    def test_unknown_phone(self):
        """Unknown phone returns None."""
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config())
        assert nm._match_person_by_phone("+19999999999") is None


class TestInboundCounters:
    """Test inbound diagnostic counters."""

    @pytest.mark.asyncio
    async def test_inbound_today_increments(self):
        """Each inbound message increments the counter."""
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config())
        await nm._process_inbound_reply(None, "companion", "status")
        await nm._process_inbound_reply(None, "whatsapp", "help")
        assert nm.inbound_today == 2

    @pytest.mark.asyncio
    async def test_inbound_by_channel(self):
        """Channel counters track correctly."""
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config())
        await nm._process_inbound_reply(None, "companion", "status")
        await nm._process_inbound_reply(None, "whatsapp", "ok")
        assert nm.inbound_by_channel["companion"] == 1
        assert nm.inbound_by_channel["whatsapp"] == 1

    @pytest.mark.asyncio
    async def test_inbound_by_command(self):
        """Command counters track correctly."""
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config())
        await nm._process_inbound_reply(None, "companion", "status")
        await nm._process_inbound_reply(None, "companion", "help")
        await nm._process_inbound_reply(None, "companion", "xyz")
        assert nm.inbound_by_command["status"] == 1
        assert nm.inbound_by_command["help"] == 1
        assert nm.inbound_by_command["unknown"] == 1

    @pytest.mark.asyncio
    async def test_diagnostics_includes_inbound(self):
        """Diagnostics summary includes inbound data."""
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config())
        summary = nm.diagnostics_summary
        assert "inbound_today" in summary
        assert "safe_word_configured" in summary
        assert "inbound_channels_active" in summary


class TestSilencedMessageHandling:
    """Test that silence suppresses inbound processing and outbound sends."""

    @pytest.mark.asyncio
    async def test_silenced_inbound_returns_silenced_message(self):
        """Commands (except status/help/safe_word) return 'silenced' when active."""
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config(**{CONF_NM_SILENCE_DURATION: 30}))
        # Activate silence
        await nm._process_inbound_reply(None, "companion", "stop")
        assert nm._silence_until is not None
        # Now ack should be rejected as silenced
        response = await nm._process_inbound_reply(None, "companion", "ok")
        assert "silenced" in response.lower()

    @pytest.mark.asyncio
    async def test_status_bypasses_silence(self):
        """Status command works even while silenced."""
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config(**{CONF_NM_SILENCE_DURATION: 30}))
        await nm._process_inbound_reply(None, "companion", "stop")
        response = await nm._process_inbound_reply(None, "companion", "status")
        assert "All clear" in response

    @pytest.mark.asyncio
    async def test_help_bypasses_silence(self):
        """Help command works even while silenced."""
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config(**{CONF_NM_SILENCE_DURATION: 30}))
        await nm._process_inbound_reply(None, "companion", "stop")
        response = await nm._process_inbound_reply(None, "companion", "help")
        assert "Reply:" in response

    @pytest.mark.asyncio
    async def test_safe_word_bypasses_silence(self):
        """Safe word works even while silenced."""
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config(**{
            CONF_NM_SILENCE_DURATION: 30,
            CONF_NM_SAFE_WORD: "myword",
        }))
        nm._alert_state = AlertState.REPEATING
        nm._active_alert_data = {
            "coordinator_id": "safety", "severity": "CRITICAL",
            "title": "Smoke", "message": "Smoke!", "hazard_type": "smoke",
            "location": "kitchen",
        }
        await nm._process_inbound_reply(None, "companion", "stop")
        response = await nm._process_inbound_reply(None, "companion", "myword")
        assert "acknowledged" in response.lower()

    @pytest.mark.asyncio
    async def test_silence_suppresses_outbound_non_critical(self):
        """Non-CRITICAL outbound notifications are suppressed while silenced."""
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config(**{CONF_NM_SILENCE_DURATION: 30}))
        # Activate silence
        await nm._process_inbound_reply(None, "companion", "silence")
        # Send a MEDIUM notification — should be suppressed
        await nm.async_notify("safety", Severity.MEDIUM, "Test", "Msg")
        hass.services.async_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_silence_does_not_suppress_critical(self):
        """CRITICAL outbound notifications bypass silence."""
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config(**{CONF_NM_SILENCE_DURATION: 30}))
        await nm._process_inbound_reply(None, "companion", "silence")
        await nm.async_notify("safety", Severity.CRITICAL, "Fire", "Fire!")
        hass.services.async_call.assert_called()


class TestActiveAlertInbound:
    """Test inbound processing when non-CRITICAL alert is active."""

    @pytest.mark.asyncio
    async def test_ack_non_critical_active_alert(self):
        """Ack succeeds for non-CRITICAL active alert without safe word."""
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config())
        # Set up a HIGH (non-CRITICAL) active alert
        nm._alert_state = AlertState.REPEATING
        nm._active_alert_data = {
            "coordinator_id": "safety", "severity": "HIGH",
            "title": "Water leak", "message": "Water detected",
            "hazard_type": "water_leak", "location": "kitchen",
        }
        response = await nm._process_inbound_reply(None, "companion", "ok")
        assert "acknowledged" in response.lower()

    @pytest.mark.asyncio
    async def test_status_with_active_alert(self):
        """Status shows alert details when alert is active."""
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config())
        nm._alert_state = AlertState.REPEATING
        nm._active_alert_data = {
            "coordinator_id": "safety", "severity": "HIGH",
            "title": "Water leak", "message": "Water detected",
            "hazard_type": "water_leak", "location": "kitchen",
        }
        response = await nm._process_inbound_reply(None, "companion", "status")
        assert "water_leak" in response
        assert "kitchen" in response
        assert "REPEATING" in response

    @pytest.mark.asyncio
    async def test_help_shows_critical_text_for_critical(self):
        """Help shows CRITICAL-specific text when CRITICAL alert is active."""
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config(**{CONF_NM_SAFE_WORD: "myword"}))
        nm._alert_state = AlertState.REPEATING
        nm._active_alert_data = {
            "coordinator_id": "safety", "severity": "CRITICAL",
            "title": "Smoke", "message": "Smoke!", "hazard_type": "smoke",
            "location": "kitchen",
        }
        response = await nm._process_inbound_reply(None, "companion", "help")
        assert "safe word" in response.lower()


class TestChannelHandlerRouting:
    """Test channel event handler routing to _process_inbound_reply."""

    def test_whatsapp_handler_routes(self):
        """WhatsApp handler extracts phone/message and calls process_inbound."""
        hass = _make_hass()
        config = _make_config(**{
            CONF_NM_WHATSAPP_ENABLED: True,
            CONF_NM_WHATSAPP_SEVERITY: "LOW",
            CONF_NM_PERSONS: [{
                CONF_NM_PERSON_ENTITY: "person.test",
                CONF_NM_PERSON_PUSHOVER_KEY: "",
                CONF_NM_PERSON_COMPANION_SERVICE: "",
                CONF_NM_PERSON_WHATSAPP_PHONE: "+11234567890",
                CONF_NM_PERSON_DELIVERY_PREF: NM_DELIVERY_IMMEDIATE,
            }],
        })
        nm = NotificationManager(hass, config)
        mock_event = MagicMock()
        mock_event.data = {"phone": "+11234567890", "message": "status"}
        nm._handle_whatsapp_reply(mock_event)
        # Should have called async_create_task
        hass.async_create_task.assert_called_once()

    def test_whatsapp_handler_ignores_empty_message(self):
        """WhatsApp handler ignores events with empty message."""
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config())
        mock_event = MagicMock()
        mock_event.data = {"phone": "+11234567890", "message": ""}
        nm._handle_whatsapp_reply(mock_event)
        hass.async_create_task.assert_not_called()

    def test_companion_action_acknowledge(self):
        """Companion ACKNOWLEDGE_URA action triggers async_acknowledge."""
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config())
        mock_event = MagicMock()
        mock_event.data = {"action": "ACKNOWLEDGE_URA"}
        nm._handle_companion_action(mock_event)
        hass.async_create_task.assert_called_once()

    def test_companion_action_status(self):
        """Companion STATUS_URA action routes to process_inbound."""
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config())
        mock_event = MagicMock()
        mock_event.data = {"action": "STATUS_URA"}
        nm._handle_companion_action(mock_event)
        hass.async_create_task.assert_called_once()

    def test_companion_action_critical_text_input(self):
        """Companion ACKNOWLEDGE_URA_CRITICAL with text routes to process_inbound."""
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config())
        mock_event = MagicMock()
        mock_event.data = {"action": "ACKNOWLEDGE_URA_CRITICAL", "reply_text": "myword"}
        nm._handle_companion_action(mock_event)
        hass.async_create_task.assert_called_once()

    def test_companion_action_unknown_ignored(self):
        """Unknown companion action is ignored."""
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config())
        mock_event = MagicMock()
        mock_event.data = {"action": "SOME_OTHER_ACTION"}
        nm._handle_companion_action(mock_event)
        hass.async_create_task.assert_not_called()
