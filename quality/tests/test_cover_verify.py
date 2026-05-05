"""Tests for v4.2.22 cover send-with-verify + straggler retry.

Covers:
- All blinds reach commanded state on first try -> success, dedup set.
- One straggler -> retry pass closes it -> success.
- Persistent straggler -> dedup NOT set, failure counter incremented.
- Per-cover sequential commands (not group call).
- Counter daily reset.
- Unsupported action raises.
- Open action targets 'open' state.

Stubs Home Assistant modules at sys.modules level (mirrors the pattern in
test_activity_logger.py), then loads
custom_components.universal_room_automation.automation directly to get
RoomAutomation. asyncio.sleep is patched out so settle delays don't slow tests.
"""
import asyncio
import sys
import types
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Mock homeassistant before importing URA code.
# ---------------------------------------------------------------------------

def _mock_module(name, **attrs):
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
    "homeassistant.helpers.event": {
        "async_track_state_change_event": _mock_cls(),
        "async_track_time_interval": lambda hass, cb, interval: _mock_cls(),
        "async_call_later": lambda hass, delay, cb: _mock_cls(),
        "async_track_time_change": lambda hass, cb, **kw: _mock_cls(),
    },
    "homeassistant.helpers.sun": {
        "get_astral_event_date": lambda *a, **kw: None,
    },
    "homeassistant.util": {},
    "homeassistant.util.dt": {
        "utcnow": datetime.utcnow,
        "now": datetime.now,
        "as_local": lambda dt: dt,
    },
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

# Load const + automation directly without going through the package __init__
# (which pulls in DB, coordinator, dashboard registration, etc.).
import importlib.util
import os

_pkg_dir = os.path.join(
    os.path.dirname(__file__), "..", "..",
    "custom_components", "universal_room_automation",
)

# Register a minimal package stub so 'from .const import' resolves.
_pkg_name = "custom_components.universal_room_automation"
if _pkg_name not in sys.modules:
    pkg = types.ModuleType(_pkg_name)
    pkg.__path__ = [os.path.abspath(_pkg_dir)]
    sys.modules[_pkg_name] = pkg
if "custom_components" not in sys.modules:
    cc = types.ModuleType("custom_components")
    cc.__path__ = [os.path.abspath(os.path.join(_pkg_dir, ".."))]
    sys.modules["custom_components"] = cc

def _load(submod_name):
    full = f"{_pkg_name}.{submod_name}"
    if full in sys.modules:
        return sys.modules[full]
    spec = importlib.util.spec_from_file_location(
        full,
        os.path.join(_pkg_dir, f"{submod_name}.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full] = mod
    spec.loader.exec_module(mod)
    return mod

_const = _load("const")
_automation = _load("automation")
RoomAutomation = _automation.RoomAutomation


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeState:
    def __init__(self, state):
        self.state = state


class _FakeStates:
    """Per-entity scripted state sequences."""
    def __init__(self):
        self._scripted: dict = {}
        self._fixed: dict = {}

    def set_fixed(self, entity_id, state):
        self._fixed[entity_id] = state

    def script(self, entity_id, sequence):
        self._scripted[entity_id] = list(sequence)

    def get(self, entity_id):
        if entity_id in self._scripted:
            seq = self._scripted[entity_id]
            value = seq.pop(0) if len(seq) > 1 else seq[0]
            return _FakeState(value)
        if entity_id in self._fixed:
            return _FakeState(self._fixed[entity_id])
        return None


def _make_automation(covers, fake_states):
    hass = MagicMock()
    hass.states = fake_states
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock(return_value=None)
    hass.async_create_task = lambda coro: asyncio.ensure_future(coro)
    hass.data = {}

    coordinator = MagicMock()
    entry = MagicMock()
    entry.data = {"room_name": "Living Room", "covers": covers}
    entry.options = {}
    coordinator.entry = entry

    config = {"room_name": "Living Room", "covers": covers}
    automation = RoomAutomation(hass, config, coordinator)
    automation._config_entry = entry
    return automation, hass


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_all_blinds_close_first_try():
    covers = ["cover.lr_1", "cover.lr_2", "cover.lr_3"]
    states = _FakeStates()
    for c in covers:
        states.set_fixed(c, "closed")

    automation, hass = _make_automation(covers, states)
    with patch("asyncio.sleep", new=AsyncMock()):
        success, failed = await automation._send_covers_with_verify(
            covers, "close_cover",
        )

    assert success is True
    assert failed == []
    assert automation._cover_failures_today == 0
    assert automation._cover_attempts_today == 3
    assert hass.services.async_call.call_count == 3
    # Per-cover (not group): each call's entity_id is a single string.
    for call in hass.services.async_call.call_args_list:
        service_data = call.args[2]
        assert isinstance(service_data["entity_id"], str)


@pytest.mark.asyncio
async def test_straggler_recovers_on_retry():
    covers = ["cover.lr_1", "cover.lr_2", "cover.lr_3"]
    states = _FakeStates()
    states.set_fixed("cover.lr_1", "closed")
    states.set_fixed("cover.lr_2", "closed")
    # Third blind: stays open after first batch, closes after retry.
    states.script("cover.lr_3", ["open", "closed"])

    automation, hass = _make_automation(covers, states)
    with patch("asyncio.sleep", new=AsyncMock()):
        success, failed = await automation._send_covers_with_verify(
            covers, "close_cover",
        )

    assert success is True
    assert failed == []
    assert automation._cover_failures_today == 0
    # 3 first attempt + 1 straggler retry = 4 calls.
    assert hass.services.async_call.call_count == 4
    last_call = hass.services.async_call.call_args_list[-1]
    assert last_call.args[2]["entity_id"] == "cover.lr_3"


@pytest.mark.asyncio
async def test_persistent_straggler_increments_failure_counter():
    covers = ["cover.lr_1", "cover.lr_2"]
    states = _FakeStates()
    states.set_fixed("cover.lr_1", "closed")
    states.set_fixed("cover.lr_2", "open")  # never closes

    automation, hass = _make_automation(covers, states)
    with patch("asyncio.sleep", new=AsyncMock()):
        success, failed = await automation._send_covers_with_verify(
            covers, "close_cover",
        )

    assert success is False
    assert failed == ["cover.lr_2"]
    assert automation._cover_failures_today == 1
    assert automation._last_cover_failure_entities == ["cover.lr_2"]
    assert automation._last_cover_failure_time is not None
    # cover.lr_2 sent on first batch + 2 retries = 3 times.
    lr2_calls = [
        c for c in hass.services.async_call.call_args_list
        if c.args[2]["entity_id"] == "cover.lr_2"
    ]
    assert len(lr2_calls) == 3


@pytest.mark.asyncio
async def test_unavailable_blind_not_counted_as_straggler():
    covers = ["cover.lr_1", "cover.lr_2"]
    states = _FakeStates()
    states.set_fixed("cover.lr_1", "closed")
    states.set_fixed("cover.lr_2", "unavailable")

    automation, hass = _make_automation(covers, states)
    with patch("asyncio.sleep", new=AsyncMock()):
        success, failed = await automation._send_covers_with_verify(
            covers, "close_cover",
        )

    # Unavailable blinds are filtered, not treated as failure.
    assert success is True
    assert failed == []
    assert automation._cover_failures_today == 0


@pytest.mark.asyncio
async def test_daily_counter_reset():
    covers = ["cover.lr_1"]
    states = _FakeStates()
    states.set_fixed("cover.lr_1", "open")  # persistent

    automation, _ = _make_automation(covers, states)
    automation._cover_failures_today = 5
    automation._cover_failure_reset_date = "2000-01-01"

    with patch("asyncio.sleep", new=AsyncMock()):
        await automation._send_covers_with_verify(covers, "close_cover")

    # Reset on entry, then +1 for the straggler.
    assert automation._cover_failures_today == 1


@pytest.mark.asyncio
async def test_unsupported_action_raises():
    covers = ["cover.lr_1"]
    states = _FakeStates()
    automation, _ = _make_automation(covers, states)

    with pytest.raises(ValueError):
        await automation._send_covers_with_verify(covers, "stop_cover")


@pytest.mark.asyncio
async def test_open_action_target_state_open():
    covers = ["cover.lr_1"]
    states = _FakeStates()
    states.set_fixed("cover.lr_1", "open")

    automation, _ = _make_automation(covers, states)
    with patch("asyncio.sleep", new=AsyncMock()):
        success, failed = await automation._send_covers_with_verify(
            covers, "open_cover",
        )

    assert success is True
    assert failed == []


# Review-fix tests -----------------------------------------------------------

class _PositionState:
    """State object with current_position attribute for position-based covers."""
    def __init__(self, state, position):
        self.state = state
        self.attributes = {"current_position": position}


def test_cover_at_target_position_based_closed():
    """H3: a blind at position=3 reporting state='open' is treated as closed."""
    s = _PositionState("open", 3)  # state says open, position says nearly closed
    assert RoomAutomation._cover_at_target(s, "closed") is True
    assert RoomAutomation._cover_at_target(s, "open") is False


def test_cover_at_target_position_based_open():
    """H3: a blind at position=98 reporting state='open' is treated as open."""
    s = _PositionState("open", 98)
    assert RoomAutomation._cover_at_target(s, "open") is True
    assert RoomAutomation._cover_at_target(s, "closed") is False


def test_cover_at_target_position_partial_is_straggler():
    """H3: position=50 is neither closed nor open — must be re-issued."""
    s = _PositionState("open", 50)
    assert RoomAutomation._cover_at_target(s, "closed") is False
    assert RoomAutomation._cover_at_target(s, "open") is False


def test_cover_at_target_no_position_falls_back_to_state():
    """H3: covers without current_position use plain state.state comparison."""
    class _S:
        state = "closed"
        attributes = {}
    assert RoomAutomation._cover_at_target(_S(), "closed") is True
    assert RoomAutomation._cover_at_target(_S(), "open") is False


def test_cover_at_target_none_state():
    assert RoomAutomation._cover_at_target(None, "closed") is False


@pytest.mark.asyncio
async def test_position_based_straggler_recovers():
    """H3 end-to-end: position=10 is straggler, retry brings it to position=2."""
    covers = ["cover.lr_1"]
    states = _FakeStates()
    # First reading: state=open + position=10 -> straggler.
    # Second reading (after retry): state=closed + position=2 -> success.
    seq = [_PositionState("open", 10), _PositionState("closed", 2)]
    states._scripted["cover.lr_1"] = list(seq)
    # Override .get to return _PositionState directly.
    original_get = states.get
    def get(eid):
        if eid == "cover.lr_1" and states._scripted.get(eid):
            seq = states._scripted[eid]
            return seq.pop(0) if len(seq) > 1 else seq[0]
        return original_get(eid)
    states.get = get

    automation, hass = _make_automation(covers, states)
    with patch("asyncio.sleep", new=AsyncMock()):
        success, failed = await automation._send_covers_with_verify(
            covers, "close_cover",
        )

    assert success is True
    assert failed == []
    # Initial + 1 retry = 2 calls.
    assert hass.services.async_call.call_count == 2


@pytest.mark.asyncio
async def test_daily_reset_clears_failure_metadata():
    """M1: day rollover must also clear last-failure timestamp/entities."""
    covers = ["cover.lr_1"]
    states = _FakeStates()
    states.set_fixed("cover.lr_1", "closed")

    automation, _ = _make_automation(covers, states)
    automation._cover_failures_today = 3
    automation._last_cover_failure_time = datetime(2026, 5, 2, 20, 0)
    automation._last_cover_failure_entities = ["cover.old_failure"]
    automation._cover_failure_reset_date = "2000-01-01"

    automation._maybe_reset_cover_counters()

    assert automation._cover_failures_today == 0
    assert automation._last_cover_failure_time is None
    assert automation._last_cover_failure_entities == []


@pytest.mark.asyncio
async def test_duplicate_cover_ids_are_deduped():
    """v4.2.26 review M1: a misconfigured covers list with duplicate
    entries must not double-send the command per cycle."""
    covers = ["cover.lr_1", "cover.lr_1", "cover.lr_2", "cover.lr_2"]
    states = _FakeStates()
    states.set_fixed("cover.lr_1", "closed")
    states.set_fixed("cover.lr_2", "closed")

    automation, hass = _make_automation(covers, states)
    with patch("asyncio.sleep", new=AsyncMock()):
        success, failed = await automation._send_covers_with_verify(
            covers, "close_cover",
        )

    assert success is True
    assert failed == []
    # 2 unique covers despite 4 input entries
    assert hass.services.async_call.call_count == 2
    assert automation._cover_attempts_today == 2


@pytest.mark.asyncio
async def test_blocking_false_for_cover_calls():
    """v4.2.23: cover calls must use blocking=False to avoid timing out
    on group covers whose sub-blinds take 30-60s to settle."""
    covers = ["cover.lr_1"]
    states = _FakeStates()
    states.set_fixed("cover.lr_1", "closed")

    automation, _ = _make_automation(covers, states)
    captured = {}
    original = automation._safe_service_call
    async def spy(*args, **kwargs):
        captured["blocking"] = kwargs.get("blocking")
        return await original(*args, **kwargs)
    automation._safe_service_call = spy

    with patch("asyncio.sleep", new=AsyncMock()):
        await automation._send_covers_with_verify(covers, "close_cover")

    assert captured["blocking"] is False


@pytest.mark.asyncio
async def test_inner_safe_service_call_no_inner_retry():
    """M3: cover sends should not double-retry inside _safe_service_call.

    Verify the outer helper passes max_retries=0 (so the outer settle+verify
    loop is the single source of truth for retries).
    """
    covers = ["cover.lr_1"]
    states = _FakeStates()
    states.set_fixed("cover.lr_1", "closed")

    automation, hass = _make_automation(covers, states)
    # Patch _safe_service_call to capture max_retries kwarg.
    captured = {}
    original = automation._safe_service_call
    async def spy(*args, **kwargs):
        captured["max_retries"] = kwargs.get("max_retries")
        return await original(*args, **kwargs)
    automation._safe_service_call = spy

    with patch("asyncio.sleep", new=AsyncMock()):
        await automation._send_covers_with_verify(covers, "close_cover")

    assert captured["max_retries"] == 0
