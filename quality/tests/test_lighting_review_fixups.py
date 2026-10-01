"""Lighting review fix-ups (v5.103.29): behavioural anchors for the four
build reviews' findings and review C's untested sites.

Reuses the Slice D harness (real RoomAutomation / coordinator code, fake
hass) so each test drives production code paths.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import test_lighting_slice_d_house_state as D  # noqa: E402  (shared harness)

M = D.M
FakeHass = D.FakeHass
_run = D._run
_light_targets = D._light_targets
_make_room = D._make_room
_real_modules = D._real_modules  # module-scoped autouse fixture (real modules)


# ---------------------------------------------------------------------------
# Review B HIGH-1: rooms with leave-on lights subscribe to house-state changes
# even without house-state chains / AI rules.
# ---------------------------------------------------------------------------


def _subscribed_signals(cfg):
    cmod = M["coordinator"]

    calls = []
    orig = cmod.async_dispatcher_connect
    cmod.async_dispatcher_connect = lambda hass, signal, handler: calls.append(signal) or (lambda: None)
    try:
        Coord = cmod.UniversalRoomCoordinator
        c = Coord.__new__(Coord)
        c.hass = FakeHass()
        c.entry = SimpleNamespace(entry_id="r1", data={"room_name": "Den"}, options={})
        c._get_config = lambda k, default=None: cfg.get(k, default)
        c._unsub_signal_listeners = []
        c._update_signal_subscriptions()
    finally:
        cmod.async_dispatcher_connect = orig
    return calls


def test_leave_on_room_subscribes_to_house_state_without_rules():
    calls = _subscribed_signals({
        "lights_leave_on_when_empty": ["light.porch"],
        "away_turn_off_leave_on": True,
    })
    assert len(calls) == 1  # the house-state signal only


def test_room_without_leave_on_does_not_subscribe():
    assert _subscribed_signals({}) == []


def test_leave_on_room_with_away_option_off_does_not_subscribe():
    assert _subscribed_signals({
        "lights_leave_on_when_empty": ["light.porch"],
        "away_turn_off_leave_on": False,
    }) == []


# ---------------------------------------------------------------------------
# Operator ruling: a paused room skips the Away leave-on turn-off.
# ---------------------------------------------------------------------------


def test_away_sweep_skips_paused_room():
    hass = FakeHass()
    auto, _e = _make_room(hass, leave_on=["light.porch"], away_off=True)
    auto.coordinator = SimpleNamespace(_is_automation_enabled=lambda: False)
    _run(auto.handle_away_leave_on_sweep())
    assert _light_targets(hass, "turn_off") == []


def test_away_sweep_runs_when_room_enabled():
    hass = FakeHass()
    auto, _e = _make_room(hass, leave_on=["light.porch"], away_off=True)
    auto.coordinator = SimpleNamespace(_is_automation_enabled=lambda: True)
    _run(auto.handle_away_leave_on_sweep())
    assert _light_targets(hass, "turn_off") == ["light.porch"]


# ---------------------------------------------------------------------------
# Review D HIGH (INV-2): a slot scene never overrides a manual hold.
# ---------------------------------------------------------------------------


def _scene_room(hass, scene_state="scening"):
    auto, _e = _make_room(hass)
    auto.config["light_scene_evening"] = "scene.evening"
    hass.states.get = lambda eid: SimpleNamespace(state=scene_state) if eid == "scene.evening" else None
    auto._safe_service_call = AsyncMock(return_value=True)
    return auto


def test_slot_scene_activates_when_no_hold():
    hass = FakeHass()
    auto = _scene_room(hass)
    auto.light_hold_allowed = lambda ents, kind: list(ents)
    assert _run(auto._maybe_activate_slot_scene("evening", ["light.a", "light.b"])) is True
    domain, service, data = auto._safe_service_call.await_args.args[:3]
    assert (domain, service) == ("scene", "turn_on")


def test_slot_scene_skipped_when_a_light_is_held():
    hass = FakeHass()
    auto = _scene_room(hass)
    auto.light_hold_allowed = lambda ents, kind: [e for e in ents if e != "light.b"]
    assert _run(auto._maybe_activate_slot_scene("evening", ["light.a", "light.b"])) is False
    auto._safe_service_call.assert_not_awaited()


# ---------------------------------------------------------------------------
# Review A MEDIUM: dark-only subset honoured on the default entry path.
# ---------------------------------------------------------------------------


def _regular_room(hass):
    auto, _e = _make_room(hass)
    auto.config["lights_on_entry_dark_only"] = ["light.b"]
    auto.light_hold_allowed = lambda ents, kind: list(ents)
    auto._safe_service_call = AsyncMock(return_value=True)
    return auto


def test_default_path_drops_dark_only_when_not_dark():
    hass = FakeHass()
    auto = _regular_room(hass)
    _run(auto._turn_on_regular_lights(is_dark=False))
    data = auto._safe_service_call.await_args.args[2]
    assert data["entity_id"] == ["light.a"]


def test_default_path_keeps_dark_only_when_dark():
    hass = FakeHass()
    auto = _regular_room(hass)
    _run(auto._turn_on_regular_lights(is_dark=True))
    data = auto._safe_service_call.await_args.args[2]
    assert sorted(data["entity_id"]) == ["light.a", "light.b"]


# ---------------------------------------------------------------------------
# Operator ruling REV 2.5: house Sleep only chooses night lights.
# ---------------------------------------------------------------------------


def test_house_sleep_drives_light_choice_not_room_sleep():
    import homeassistant.util.dt as dt_util
    from datetime import datetime, timezone

    hass = FakeHass()
    auto, _e = _make_room(hass)
    hass.data["universal_room_automation"]["coordinator_manager"].house_state = "sleep"
    real_now = dt_util.now
    dt_util.now = lambda: datetime(2026, 9, 30, 20, 45, tzinfo=timezone.utc)
    try:
        # 20:45, clock window 22-07: covers/exits/fans keep the clock.
        assert auto.is_sleep_mode_active() is False
        assert auto.is_sleep_lighting_active() is True
    finally:
        dt_util.now = real_now
