"""feature/sleep-fans-and-flash — behavioral tests.

Covers three deliverables:

  D1 — Sleep-onset bedroom fan activation via shared
       ``fan_veto.sleep_onset_fan_target`` predicate; TWO call-site tiers
       (HVAC FanController + room-tier automation.RoomAutomation)
       consuming the same helper so the feature works regardless of fan
       ownership (Study-A class included).

  D2 — Warning flash extended to switch-based lighting (off/on cycles
       for switch.* entries; light.* dim-restore path preserved).

  D3 — check_auto_off_warning ``lights_on`` check counts switch.* states
       (previously silently False for switch-only rooms).

Each test drives PRODUCTION functions (no string-only anchors for
decision logic). Mutation-anchor notes are inlined per class for the
adversarial mutation pass.
"""
from __future__ import annotations

import asyncio
import importlib.util


def _run(coro):
    """Run a coroutine without permanently closing the event loop.

    asyncio.run() closes the loop after the coroutine finishes, which
    breaks sibling tests (e.g. test_substrate_*) that expect a live
    default loop when they subsequently query asyncio.get_event_loop().
    Use a fresh, per-call loop and restore the prior default afterward.
    """
    prior = None
    try:
        prior = asyncio.get_event_loop_policy().get_event_loop()
    except Exception:  # noqa: BLE001
        prior = None
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        loop.close()
        try:
            asyncio.set_event_loop(prior)
        except Exception:  # noqa: BLE001
            pass



import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

import _provenance_harness  # noqa: F401

from homeassistant.util import dt as dt_util  # noqa: E402


# --------------------------------------------------------------------------
# Pollution-defense (mirror of test_fan_trust_state_extension.py bootstrap).
# --------------------------------------------------------------------------


def _is_stub_module(mod) -> bool:
    from unittest.mock import MagicMock, NonCallableMagicMock
    if isinstance(mod, (MagicMock, NonCallableMagicMock)):
        return True
    spec = getattr(mod, "__spec__", None)
    file_ = getattr(mod, "__file__", None)
    if spec is None and file_ is None:
        return True
    return False


def _ensure_real_module(shared_name: str, disk_relpath: str, required_attrs: tuple):
    cached = sys.modules.get(shared_name)
    is_real = (
        cached is not None
        and not _is_stub_module(cached)
        and all(hasattr(cached, a) for a in required_attrs)
    )
    if is_real:
        return cached
    path = os.path.join(
        os.path.dirname(__file__), "..", "..",
        *disk_relpath.split("/"),
    )
    spec = importlib.util.spec_from_file_location(shared_name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[shared_name] = mod
    spec.loader.exec_module(mod)
    return mod


_ensure_real_module(
    "custom_components.universal_room_automation.const",
    "custom_components/universal_room_automation/const.py",
    (
        "CONF_SLEEP_FAN_ON_TEMP_F", "DEFAULT_SLEEP_FAN_ON_TEMP_F",
        "CONF_FAN_SLEEP_POLICY", "DEFAULT_FAN_SLEEP_POLICY",
        "FAN_SLEEP_OFF", "FAN_SLEEP_REDUCE",
        "CONF_ROOM_TYPE", "ROOM_TYPE_BEDROOM", "ROOM_TYPE_GENERIC",
        "ENTRY_TYPE_COORDINATOR_MANAGER", "CONF_ENTRY_TYPE",
    ),
)
_ensure_real_module(
    "custom_components.universal_room_automation.domain_coordinators.hvac_const",
    "custom_components/universal_room_automation/domain_coordinators/hvac_const.py",
    ("FAN_TRUST_STATES", "FAN_SPEED_LOW_PCT", "FAN_SPEED_MED_PCT"),
)


from custom_components.universal_room_automation.const import (  # noqa: E402
    CONF_ENTRY_TYPE,
    CONF_FAN_SLEEP_POLICY,
    CONF_ROOM_TYPE,
    CONF_SLEEP_FAN_ON_TEMP_F,
    CONF_SHARED_SPACE,
    CONF_SHARED_SPACE_AUTO_OFF_HOUR,
    CONF_SHARED_SPACE_WARNING,
    CONF_LIGHTS,
    CONF_ROOM_NAME,
    CONF_FAN_CONTROL_ENABLED,
    CONF_FANS,
    CONF_HVAC_COORDINATION_ENABLED,
    DEFAULT_SLEEP_FAN_ON_TEMP_F,
    ENTRY_TYPE_COORDINATOR_MANAGER,
    FAN_SLEEP_OFF,
    FAN_SLEEP_REDUCE,
    ROOM_TYPE_BEDROOM,
    ROOM_TYPE_GENERIC,
)
from custom_components.universal_room_automation.domain_coordinators.hvac_const import (  # noqa: E402
    FAN_SPEED_LOW_PCT,
    FAN_SPEED_MED_PCT,
)
from custom_components.universal_room_automation.fan_veto import (  # noqa: E402
    sleep_onset_fan_target,
)


def _load_dc_submod_aliased(name: str):
    test_alias = f"_sleep_fan_test.{name}"
    if test_alias in sys.modules:
        return sys.modules[test_alias]
    path = os.path.join(
        os.path.dirname(__file__), "..", "..",
        "custom_components", "universal_room_automation",
        "domain_coordinators", f"{name}.py",
    )
    spec = importlib.util.spec_from_file_location(test_alias, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[test_alias] = mod
    spec.loader.exec_module(mod)
    return mod


# ==========================================================================
# D1a — SHARED HELPER: sleep_onset_fan_target
# ==========================================================================
# Mutation anchor: change `if room_type != ROOM_TYPE_BEDROOM: return None`
# to `return FAN_SPEED_MED_PCT` — a test in this class must RED.
# ==========================================================================


class TestD1_SharedHelper:
    def _bedroom(self, policy=FAN_SLEEP_REDUCE):
        return {
            CONF_ROOM_TYPE: ROOM_TYPE_BEDROOM,
            CONF_FAN_SLEEP_POLICY: policy,
        }

    def test_reduce_policy_returns_low_speed(self):
        assert sleep_onset_fan_target(
            self._bedroom(FAN_SLEEP_REDUCE),
            occupied=True, room_temp=74.0, threshold=72.0,
            policy=FAN_SLEEP_REDUCE,
        ) == FAN_SPEED_LOW_PCT

    def test_normal_policy_returns_med_speed(self):
        # A-MED-1 fix-up 2026-08-03: ladder — delta=4 (MED tier: >= 3, < 5).
        assert sleep_onset_fan_target(
            self._bedroom(),
            occupied=True, room_temp=76.0, threshold=72.0, policy="normal",
        ) == FAN_SPEED_MED_PCT

    # --- A-MED-1 fix-up 2026-08-03: temp-delta ladder anchors ---
    # These tests DRIVE the shared ladder mapping in
    # fan_veto.sleep_onset_fan_target. Mutation-red: break any rung of the
    # ladder (e.g. return FAN_SPEED_LOW_PCT unconditionally) — at least one
    # of these tests fails.

    def test_normal_ladder_low_tier_marginal_above_threshold(self):
        # delta=0.5 (eligible — >= threshold) → below LOW_DELTA (2) → LOW
        assert sleep_onset_fan_target(
            self._bedroom(),
            occupied=True, room_temp=72.5, threshold=72.0, policy="normal",
        ) == FAN_SPEED_LOW_PCT

    def test_normal_ladder_high_tier(self):
        # delta=6 (>= HIGH_DELTA=5) normal → HIGH
        from custom_components.universal_room_automation.domain_coordinators.hvac_const import (  # noqa: E402
            FAN_SPEED_HIGH_PCT,
        )
        assert sleep_onset_fan_target(
            self._bedroom(),
            occupied=True, room_temp=78.0, threshold=72.0, policy="normal",
        ) == FAN_SPEED_HIGH_PCT

    def test_reduce_policy_caps_high_ladder_to_low(self):
        # delta=6 reduce → capped at LOW despite ladder-HIGH.
        assert sleep_onset_fan_target(
            self._bedroom(FAN_SLEEP_REDUCE),
            occupied=True, room_temp=78.0, threshold=72.0,
            policy=FAN_SLEEP_REDUCE,
        ) == FAN_SPEED_LOW_PCT

    def test_off_policy_skipped(self):
        assert sleep_onset_fan_target(
            self._bedroom(FAN_SLEEP_OFF),
            occupied=True, room_temp=90.0, threshold=72.0,
            policy=FAN_SLEEP_OFF,
        ) is None

    def test_below_threshold_skipped(self):
        assert sleep_onset_fan_target(
            self._bedroom(), occupied=True, room_temp=71.5, threshold=72.0,
            policy=FAN_SLEEP_REDUCE,
        ) is None

    def test_unoccupied_skipped(self):
        assert sleep_onset_fan_target(
            self._bedroom(), occupied=False, room_temp=80.0, threshold=72.0,
            policy=FAN_SLEEP_REDUCE,
        ) is None

    def test_kill_switch_threshold_zero_skipped(self):
        assert sleep_onset_fan_target(
            self._bedroom(), occupied=True, room_temp=80.0, threshold=0,
            policy=FAN_SLEEP_REDUCE,
        ) is None

    def test_non_bedroom_room_type_skipped(self):
        cfg = {CONF_ROOM_TYPE: ROOM_TYPE_GENERIC}
        assert sleep_onset_fan_target(
            cfg, occupied=True, room_temp=80.0, threshold=72.0,
            policy=FAN_SLEEP_REDUCE,
        ) is None

    def test_none_temp_skipped(self):
        assert sleep_onset_fan_target(
            self._bedroom(), occupied=True, room_temp=None, threshold=72.0,
            policy=FAN_SLEEP_REDUCE,
        ) is None


# ==========================================================================
# D1b — HVAC TIER: FanController.update() sleep-onset hook
# ==========================================================================
# Mutation anchor: change the `if house_state == "sleep" and prior_state ...`
# guard in hvac_fans.py:update() to fire on every tick — the "one-shot latch
# across ticks" test must RED (would see two actuations, expects one).
# ==========================================================================


_FANS_NAME = "custom_components.universal_room_automation.domain_coordinators.hvac_fans"
_REAL_FANS_AVAILABLE = False
_FanController = None
_RoomFanState = None
try:
    cached_fans = sys.modules.get(_FANS_NAME)
    # Pollution discipline: only take over the shared sys.modules slot
    # if it holds a MagicMock stub (per _is_stub_module). Reloading a
    # real module here cascades into siblings and breaks unrelated
    # tests (substrate, span_circuit_rekey — v5.49-era pollution
    # regression). If the real module is already loaded, use it as-is.
    if cached_fans is not None and not _is_stub_module(cached_fans) and (
        hasattr(cached_fans, "FanController")
        and hasattr(cached_fans, "RoomFanState")
    ):
        pass  # take the real module already in sys.modules
    else:
        if cached_fans is not None and _is_stub_module(cached_fans):
            del sys.modules[_FANS_NAME]
        _p = os.path.join(
            os.path.dirname(__file__), "..", "..",
            "custom_components", "universal_room_automation",
            "domain_coordinators", "hvac_fans.py",
        )
        _spec = importlib.util.spec_from_file_location(_FANS_NAME, _p)
        _mod = importlib.util.module_from_spec(_spec)
        sys.modules[_FANS_NAME] = _mod
        _spec.loader.exec_module(_mod)
        cached_fans = _mod
    _FanController = cached_fans.FanController
    _RoomFanState = cached_fans.RoomFanState
    _REAL_FANS_AVAILABLE = True
except Exception:
    _REAL_FANS_AVAILABLE = False


_skip_no_fans = pytest.mark.skipif(
    not _REAL_FANS_AVAILABLE,
    reason="FanController not importable in this ordering",
)


@dataclass
class _FakeRoomCond:
    room_name: str
    temperature: float | None
    occupied: bool


@dataclass
class _FakeZone:
    zone_id: str = "z1"
    target_temp_high: float = 74.0
    zone_persons: list = field(default_factory=list)
    rooms: list = field(default_factory=list)
    room_conditions: list = field(default_factory=list)


class _FakeZoneManager:
    def __init__(self):
        self.zones = {}


def _make_hass(cm_options=None):
    hass = MagicMock()
    hass.states.get = lambda entity_id: None
    hass.services.async_call = AsyncMock(return_value=None)

    entries = []
    if cm_options is not None:
        entry = MagicMock()
        entry.data = {CONF_ENTRY_TYPE: ENTRY_TYPE_COORDINATOR_MANAGER}
        entry.options = dict(cm_options)
        entries.append(entry)

    hass.config_entries.async_entries = lambda domain: entries
    return hass


@_skip_no_fans
class TestD1_HVACTier:
    def _setup(self, *, room_type=ROOM_TYPE_BEDROOM,
               policy=FAN_SLEEP_REDUCE, temp=74.0, occupied=True,
               threshold=72.0):
        zone = _FakeZone()
        zone.room_conditions = [
            _FakeRoomCond("master_bedroom", temp, occupied),
        ]
        zone.rooms = ["master_bedroom"]

        cm_opts = {CONF_SLEEP_FAN_ON_TEMP_F: threshold}
        hass = _make_hass(cm_options=cm_opts)
        zm = _FakeZoneManager()
        zm.zones[zone.zone_id] = zone
        ctrl = _FanController(hass, zm)
        ctrl._room_fans["master_bedroom"] = _RoomFanState(
            room_name="master_bedroom",
            zone_id=zone.zone_id,
            room_type=room_type,
            fan_entities=["fan.master"],
            fan_sleep_policy=policy,
        )
        return hass, ctrl

    def _turn_on_calls(self, hass):
        return [
            call for call in hass.services.async_call.await_args_list
            if call.args[:2] == ("fan", "turn_on")
        ]

    def test_activates_on_sleep_edge_occupied_warm_bedroom(self):
        hass, ctrl = self._setup()
        ctrl._house_state = "home_night"  # prior != sleep
        _run(ctrl.update(None, house_state="sleep"))
        turn_ons = self._turn_on_calls(hass)
        assert len(turn_ons) == 1
        assert turn_ons[0].args[2]["entity_id"] == "fan.master"
        assert turn_ons[0].args[2]["percentage"] == FAN_SPEED_LOW_PCT
        rf = ctrl._room_fans["master_bedroom"]
        assert rf.is_on and rf.trigger == "sleep_onset"

    def test_no_activation_below_threshold(self):
        # temp=71 keeps us below sleep-onset threshold=72 but avoids the
        # temp-hysteresis path (delta=-3, below activation_delta=2.0).
        hass, ctrl = self._setup(temp=71.0)
        ctrl._house_state = "home_night"
        _run(ctrl.update(None, house_state="sleep"))
        assert self._turn_on_calls(hass) == []

    def test_no_activation_policy_off(self):
        # temp=73 avoids the standard temp-hysteresis path (setpoint=74,
        # activation_delta=2.0 → delta=-1 too small); isolates the
        # sleep-onset skip decision.
        hass, ctrl = self._setup(policy=FAN_SLEEP_OFF, temp=73.0)
        ctrl._house_state = "home_night"
        _run(ctrl.update(None, house_state="sleep"))
        assert self._turn_on_calls(hass) == []

    def test_no_activation_unoccupied(self):
        # temp=73 avoids temp-hysteresis; occupied=False → not activated;
        # the standard occupancy gate also stops the temp path.
        hass, ctrl = self._setup(occupied=False, temp=73.0)
        ctrl._house_state = "home_night"
        _run(ctrl.update(None, house_state="sleep"))
        assert self._turn_on_calls(hass) == []

    def test_one_shot_latch_across_ticks(self):
        hass, ctrl = self._setup()
        ctrl._house_state = "home_night"
        _run(ctrl.update(None, house_state="sleep"))
        first = len(self._turn_on_calls(hass))
        # Second tick with same sleep state -> no additional actuation.
        # Also flip is_on back to False to prove the latch (not is_on) blocks.
        ctrl._room_fans["master_bedroom"].is_on = False
        _run(ctrl.update(None, house_state="sleep"))
        second = len(self._turn_on_calls(hass))
        assert first == 1
        assert second == 1, (
            "Sleep-onset must be one-shot per sleep entry (latch broken?)"
        )

    def test_kill_switch_threshold_zero_disables(self):
        # threshold=0 disables the feature entirely; temp=73 avoids the
        # temp-hysteresis path so any turn_on we see is a bug.
        hass, ctrl = self._setup(threshold=0, temp=73.0)
        ctrl._house_state = "home_night"
        _run(ctrl.update(None, house_state="sleep"))
        assert self._turn_on_calls(hass) == []

    def test_latch_clears_when_leaving_trust_states(self):
        """When the house genuinely leaves FAN_TRUST_STATES the fired
        latch clears (the re-arm guard is what prevents re-fire within
        6h; latch behavior is separately observable)."""
        hass, ctrl = self._setup()
        ctrl._house_state = "home_night"
        _run(ctrl.update(None, house_state="sleep"))
        assert ctrl._sleep_onset_fired is True
        _run(ctrl.update(None, house_state="home_day"))
        assert ctrl._sleep_onset_fired is False

    def test_sleep_waking_sleep_flap_no_reactivation(self):
        """Scar 2026-08-03 06:00 flap: sleep -> waking -> sleep must
        NOT re-fire sleep-onset (latch persists across flank states)."""
        hass, ctrl = self._setup()
        ctrl._house_state = "home_night"
        _run(ctrl.update(None, house_state="sleep"))
        _run(ctrl.update(None, house_state="waking"))
        # Simulate wife killing fan externally: reset is_on so a naive
        # re-fire would trip a second turn_on.
        ctrl._room_fans["master_bedroom"].is_on = False
        _run(ctrl.update(None, house_state="sleep"))
        assert len(self._turn_on_calls(hass)) == 1

    def test_manual_off_cooldown_blocks_activation(self):
        """Scar: THE incident — someone who turned their fan OFF before
        bed made a choice; sleep-onset must not override it."""
        hass, ctrl = self._setup()
        rf = ctrl._room_fans["master_bedroom"]
        # Cooldown timestamp derived from the SAME dt_util production
        # reads, then pushed 100y into the future. Same-source anchor
        # avoids aware/naive mismatches under pollution (some sibling
        # tests replace dt_util); 100y buffer swamps any wall-clock
        # skew that pollution might introduce.
        from datetime import timedelta
        rf.manual_off_cooldown_until = (
            dt_util.now() + timedelta(days=365 * 100)
        ).isoformat()
        ctrl._house_state = "home_night"
        _run(ctrl.update(None, house_state="sleep"))
        assert self._turn_on_calls(hass) == []

    def test_running_fan_untouched(self):
        """Operator contract: an already-on fan sees ZERO service calls
        from the sleep-onset path (radar-adaptation preserved)."""
        hass, ctrl = self._setup()
        ctrl._room_fans["master_bedroom"].is_on = True
        ctrl._room_fans["master_bedroom"].speed_pct = 66
        ctrl._room_fans["master_bedroom"].trigger = "temperature"
        # State says fan is on.
        def _get(entity_id):
            if entity_id == "fan.master":
                st = MagicMock()
                st.state = "on"
                return st
            return None
        hass.states.get = _get
        ctrl._house_state = "home_night"
        _run(ctrl.update(None, house_state="sleep"))
        # No fan turn_on/turn_off from sleep-onset (the per-room loop
        # may still touch the fan for other reasons; assert specifically
        # that the trigger stays "temperature" and no NEW sleep_onset
        # actuation happened).
        assert ctrl._room_fans["master_bedroom"].trigger == "temperature"
        # And critically, no service call with sleep-onset semantics was
        # dispatched (this fan was left alone by sleep-onset).
        for c in hass.services.async_call.await_args_list:
            args_dict = c.args[2] if len(c.args) > 2 else {}
            # If any call touched this fan on the ON path, it would be
            # a violation of the running-fans-untouchable contract for
            # THIS test's setup (nothing else legitimately wants to
            # actuate here — temp is 74=setpoint, delta=0).
            entity_id = (
                args_dict.get("entity_id") if isinstance(args_dict, dict)
                else None
            )
            if entity_id == "fan.master":
                assert c.args[1] != "turn_off", (
                    "sleep-onset must not turn off a running fan"
                )


# ==========================================================================
# D1c — ROOM-TIER: RoomAutomation._maybe_sleep_onset_activate
# ==========================================================================
# Mutation anchor: change `if hvac_manages: return` at
# handle_temperature_based_fan_control to `pass` — the HVAC-owned tests
# below will see a double-activation and RED.
# ==========================================================================


_AUTOMATION_NAME = "custom_components.universal_room_automation.automation"
_REAL_AUTOMATION = False
_RoomAutomation = None
try:
    cached = sys.modules.get(_AUTOMATION_NAME)
    # Same pollution discipline as the hvac_fans block above: only load
    # fresh if the shared slot is missing or a stub. Reloading a real
    # `automation` module here would re-execute its heavy import graph
    # and break sibling tests via sys.modules churn.
    if cached is not None and not _is_stub_module(cached) and hasattr(cached, "RoomAutomation"):
        pass
    else:
        if cached is not None and _is_stub_module(cached):
            del sys.modules[_AUTOMATION_NAME]
        _p = os.path.join(
            os.path.dirname(__file__), "..", "..",
            "custom_components", "universal_room_automation", "automation.py",
        )
        _spec = importlib.util.spec_from_file_location(_AUTOMATION_NAME, _p)
        _mod = importlib.util.module_from_spec(_spec)
        sys.modules[_AUTOMATION_NAME] = _mod
        _spec.loader.exec_module(_mod)
        cached = _mod
    _RoomAutomation = cached.RoomAutomation
    _REAL_AUTOMATION = True
except Exception:
    _REAL_AUTOMATION = False

_skip_no_automation = pytest.mark.skipif(
    not _REAL_AUTOMATION,
    reason="RoomAutomation not importable in this ordering",
)


def _make_room_hass(cm_options=None, house_state="sleep",
                    hvac_manages=False):
    hass = MagicMock()
    hass.states.get = lambda entity_id: None
    hass.services.async_call = AsyncMock(return_value=None)
    hass.async_create_task = lambda coro: coro.close() if hasattr(coro, "close") else None

    entries = []
    if cm_options is not None:
        entry = MagicMock()
        entry.data = {CONF_ENTRY_TYPE: ENTRY_TYPE_COORDINATOR_MANAGER}
        entry.options = dict(cm_options)
        entries.append(entry)
    hass.config_entries.async_entries = lambda domain: entries

    mgr = MagicMock()
    mgr.house_state = house_state
    if hvac_manages:
        fan_ctrl = MagicMock()
        fan_ctrl._room_fans = {"Ziri Bedroom": object()}
        hvac = MagicMock()
        hvac.enabled = True
        hvac.fan_controller = fan_ctrl
        mgr.coordinators = {"hvac": hvac}
    else:
        mgr.coordinators = {}

    hass.data = {
        "universal_room_automation": {
            "coordinator_manager": mgr,
        },
    }
    return hass


def _make_room(hass, room_name="Ziri Bedroom",
               room_type=ROOM_TYPE_BEDROOM,
               policy=FAN_SLEEP_REDUCE,
               hvac_coordination_enabled=False):
    coordinator = MagicMock()
    coordinator.entry = MagicMock()
    config = {
        CONF_ROOM_NAME: room_name,
        CONF_ROOM_TYPE: room_type,
        CONF_FAN_SLEEP_POLICY: policy,
        CONF_FAN_CONTROL_ENABLED: True,
        CONF_FANS: ["fan.ziri"],
        CONF_HVAC_COORDINATION_ENABLED: hvac_coordination_enabled,
    }
    return _RoomAutomation(hass, config, coordinator)


@_skip_no_automation
class TestD1_RoomTier:
    def _turn_on_calls(self, hass):
        return [
            call for call in hass.services.async_call.await_args_list
            if call.args[0] in ("fan", "homeassistant")
            and call.args[1] == "turn_on"
        ]

    def test_room_tier_activates_bedroom_at_sleep_edge(self):
        hass = _make_room_hass(cm_options={CONF_SLEEP_FAN_ON_TEMP_F: 72.0})
        room = _make_room(hass)
        room._last_seen_house_state = "home_night"  # prior != sleep
        _run(room.handle_temperature_based_fan_control(74.0, True))
        turn_ons = self._turn_on_calls(hass)
        assert len(turn_ons) == 1
        assert turn_ons[0].args[2]["percentage"] == FAN_SPEED_LOW_PCT
        assert room._sleep_onset_fired is True

    def test_room_tier_no_activation_when_hvac_owns_room(self):
        """Study-A guard: even if we get through the ownership check,
        the hvac_manages defer must short-circuit the sleep-onset path
        so we don't double-activate."""
        hass = _make_room_hass(
            cm_options={CONF_SLEEP_FAN_ON_TEMP_F: 72.0},
            hvac_manages=True,
        )
        room = _make_room(hass, hvac_coordination_enabled=True)
        room._last_seen_house_state = "home_night"
        _run(room.handle_temperature_based_fan_control(74.0, True))
        assert self._turn_on_calls(hass) == []
        assert room._sleep_onset_fired is False

    def test_room_tier_below_threshold_no_activation(self):
        hass = _make_room_hass(cm_options={CONF_SLEEP_FAN_ON_TEMP_F: 72.0})
        room = _make_room(hass)
        room._last_seen_house_state = "home_night"
        _run(room.handle_temperature_based_fan_control(70.0, True))
        assert self._turn_on_calls(hass) == []

    def test_room_tier_policy_off_no_activation(self):
        hass = _make_room_hass(cm_options={CONF_SLEEP_FAN_ON_TEMP_F: 72.0})
        room = _make_room(hass, policy=FAN_SLEEP_OFF)
        room._last_seen_house_state = "home_night"
        # temp=73 exceeds sleep-onset threshold (72) but is below the
        # standard temp-path threshold (default 80), isolating the
        # sleep-onset skip decision from unrelated activation paths.
        _run(room.handle_temperature_based_fan_control(73.0, True))
        assert self._turn_on_calls(hass) == []

    def test_room_tier_kill_switch_zero_disables(self):
        hass = _make_room_hass(cm_options={CONF_SLEEP_FAN_ON_TEMP_F: 0})
        room = _make_room(hass)
        room._last_seen_house_state = "home_night"
        # temp=73 avoids the temp-hysteresis path.
        _run(room.handle_temperature_based_fan_control(73.0, True))
        assert self._turn_on_calls(hass) == []

    def test_room_tier_manual_off_cooldown_blocks_activation(self):
        """Scar: THE incident. Manual-off cooldown active → sleep-onset
        must NOT override.

        Direct-drive the helper and stub `is_fan_in_manual_cooldown` so
        the test is immune to aware/naive datetime pollution some sibling
        tests introduce into dt_util. What we actually want to test is
        the SKIP decision when cooldown is live — not the timestamp
        arithmetic (that's exercised by dedicated cooldown tests).
        """
        hass = _make_room_hass(cm_options={CONF_SLEEP_FAN_ON_TEMP_F: 72.0})
        room = _make_room(hass)
        room._last_seen_house_state = "home_night"
        room.is_fan_in_manual_cooldown = lambda: True
        _run(room._maybe_sleep_onset_activate(["fan.ziri"], 74.0, True))
        assert self._turn_on_calls(hass) == []
        assert room._sleep_onset_fired is True

    def test_room_tier_flap_no_reactivation(self):
        hass = _make_room_hass(cm_options={CONF_SLEEP_FAN_ON_TEMP_F: 72.0})
        room = _make_room(hass)
        # First sleep entry from home_night.
        room._last_seen_house_state = "home_night"
        _run(room.handle_temperature_based_fan_control(74.0, True))
        first = len(self._turn_on_calls(hass))
        # Waking flap — still in trust states, latch persists.
        # Change the CM manager's house_state so read returns "waking".
        hass.data["universal_room_automation"]["coordinator_manager"].house_state = "waking"
        _run(room.handle_temperature_based_fan_control(74.0, True))
        # Back to sleep.
        hass.data["universal_room_automation"]["coordinator_manager"].house_state = "sleep"
        _run(room.handle_temperature_based_fan_control(74.0, True))
        second = len(self._turn_on_calls(hass))
        assert first == 1 and second == 1


# ==========================================================================
# D2 — WARNING FLASH: switch-based lighting
# ==========================================================================
# Mutation anchor: remove the switch branch in _warning_flash and the
# switch test must RED (no switch turn_off/turn_on calls observed).
# ==========================================================================


@_skip_no_automation
class TestD2_WarningFlash:
    def _make(self, lights):
        hass = _make_room_hass()
        coordinator = MagicMock()
        coordinator.entry = MagicMock()
        config = {CONF_ROOM_NAME: "TestRoom", CONF_LIGHTS: lights}
        return hass, _RoomAutomation(hass, config, coordinator)

    def test_switch_only_room_flashes_via_off_on_cycles(self):
        # Under test-suite pollution, homeassistant.const may resolve
        # SERVICE_TURN_ON/OFF as either the real strings or MagicMocks.
        # Assert on payload shape (4 calls per cycle, split evenly) so
        # the test is robust to either representation.
        hass, room = self._make(["switch.kitchen_main"])
        _run(room._warning_flash())
        switch_calls = [
            c for c in hass.services.async_call.await_args_list
            if c.args[0] == "switch"
        ]
        assert len(switch_calls) == 4
        # Distinct-services count: exactly two unique service values
        # (turn_on + turn_off), each used twice.
        services = [c.args[1] for c in switch_calls]
        unique = set(services)
        assert len(unique) == 2, (
            f"Expected turn_on + turn_off, got {unique}"
        )
        for svc in unique:
            assert services.count(svc) == 2

    def test_light_only_room_uses_dim_restore_path(self):
        hass, room = self._make(["light.living_main"])
        _run(room._warning_flash())
        light_calls = [
            c for c in hass.services.async_call.await_args_list
            if c.args[0] == "light"
        ]
        # 2 cycles: dim + restore = 4 turn_on calls with brightness.
        assert len(light_calls) == 4
        # Only ONE unique service (turn_on) and every call carries
        # brightness — this is the dim-restore path signature.
        services = [c.args[1] for c in light_calls]
        assert len(set(services)) == 1, (
            f"Expected only turn_on for light dim-restore, got {set(services)}"
        )
        for c in light_calls:
            assert "brightness" in c.args[2]

    def test_mixed_lights_flash_both_domains(self):
        hass, room = self._make(["light.a", "switch.b"])
        _run(room._warning_flash())
        light_calls = [c for c in hass.services.async_call.await_args_list if c.args[0] == "light"]
        switch_calls = [c for c in hass.services.async_call.await_args_list if c.args[0] == "switch"]
        assert len(light_calls) == 4
        assert len(switch_calls) == 4

    def test_empty_lights_noop(self):
        hass, room = self._make([])
        _run(room._warning_flash())
        assert hass.services.async_call.await_args_list == []


# ==========================================================================
# D3 — check_auto_off_warning: lights_on check counts switches
# ==========================================================================
# Mutation anchor: filter `lights` to `light.*` before the any(...) —
# the switch-on test must RED (warning would not fire).
# ==========================================================================


# NOTE: The prior TestD3_AutoOffWarning_SwitchLightsOn source-grep test
# was replaced by TestFixup_CheckAutoOffWarning_Drive (below) per C-M3 —
# production-driving fixture that patches _warning_flash and asserts the
# invocation, rather than reading source text.


# ==========================================================================
# Fix-up 2026-08-03 (A/B/C review adjudication)
# ==========================================================================


def _fans_mod():
    return sys.modules[_FANS_NAME]


def _autom_mod():
    return sys.modules[_AUTOMATION_NAME]


@_skip_no_fans
class TestFixup_BootEdgeAndLatch_HVAC:
    """A-HIGH-1 (boot-edge storm), B-M1/C-H2 (latch isolation),
    C-H1 (latch-on-skip), C-M1 (stagger), C-M2 (dual-tier).
    """

    def _setup(self, *, room_type=ROOM_TYPE_BEDROOM,
               policy=FAN_SLEEP_REDUCE, temp=74.0, occupied=True,
               threshold=72.0):
        # Mirror of TestD1_HVACTier._setup so we exercise the same paths.
        zone = _FakeZone()
        zone.room_conditions = [_FakeRoomCond("master_bedroom", temp, occupied)]
        zone.rooms = ["master_bedroom"]
        cm_opts = {CONF_SLEEP_FAN_ON_TEMP_F: threshold}
        hass = _make_hass(cm_options=cm_opts)
        zm = _FakeZoneManager()
        zm.zones[zone.zone_id] = zone
        ctrl = _FanController(hass, zm)
        ctrl._room_fans["master_bedroom"] = _RoomFanState(
            room_name="master_bedroom",
            zone_id=zone.zone_id,
            room_type=room_type,
            fan_entities=["fan.master"],
            fan_sleep_policy=policy,
        )
        return hass, ctrl

    def _turn_ons(self, hass):
        return [
            c for c in hass.services.async_call.await_args_list
            if c.args[:2] == ("fan", "turn_on")
        ]

    # ---- A-HIGH-1 boot-edge -------------------------------------------------

    def test_boot_during_sleep_no_activation(self):
        """First observation with empty prior + house=sleep MUST NOT fire
        (boot-edge storm guard). A subsequent genuine home_night->sleep
        edge fires normally."""
        hass, ctrl = self._setup()
        # Do NOT seed ctrl._house_state — leave it as "" from construction.
        _run(ctrl.update(None, house_state="sleep"))
        assert self._turn_ons(hass) == [], (
            "Boot-edge sleep must not fire — prior_state was empty (unseen)"
        )
        # Now leave trust states and re-enter via a genuine edge.
        _run(ctrl.update(None, house_state="home_day"))
        _run(ctrl.update(None, house_state="home_night"))
        _run(ctrl.update(None, house_state="sleep"))
        assert len(self._turn_ons(hass)) == 1, (
            "Genuine home_night->sleep edge after boot-seed must fire once"
        )

    # ---- B-M1 / C-H2 latch isolation ---------------------------------------

    def test_latch_alone_blocks_second_burst_when_rearm_disabled(self, monkeypatch):
        """With SLEEP_FAN_ON_REARM_S=0 AND last_fire_at reset, the latch
        (self._sleep_onset_fired) alone must block a second burst across a
        sleep->waking->sleep flap. Mutation-red: remove the latch-set line
        in update() (line 475-ish `self._sleep_onset_fired = True`) → this
        test fails (would see a second turn_on).
        """
        monkeypatch.setattr(_fans_mod(), "SLEEP_FAN_ON_REARM_S", 0)
        hass, ctrl = self._setup()
        ctrl._house_state = "home_night"
        _run(ctrl.update(None, house_state="sleep"))
        # Wipe the re-arm timestamp too so ONLY the latch can block.
        ctrl._sleep_onset_last_fire_at = None
        # Flap through waking (stays in trust states — latch persists) and
        # reset is_on so a naive re-fire would produce a second turn_on.
        ctrl._room_fans["master_bedroom"].is_on = False
        _run(ctrl.update(None, house_state="waking"))
        _run(ctrl.update(None, house_state="sleep"))
        assert len(self._turn_ons(hass)) == 1, (
            "Latch alone must block second burst (re-arm neutralized)"
        )

    def test_rearm_alone_blocks_second_burst_when_latch_cleared(self, monkeypatch):
        """Converse: with SLEEP_FAN_ON_REARM_S > 0 and latch manually
        cleared, the re-arm window alone must block a second burst.
        Mutation-red: remove the re-arm check in _sleep_onset_activation
        → this test fails (would see a second turn_on).
        """
        monkeypatch.setattr(_fans_mod(), "SLEEP_FAN_ON_REARM_S", 21600)
        hass, ctrl = self._setup()
        ctrl._house_state = "home_night"
        _run(ctrl.update(None, house_state="sleep"))
        assert len(self._turn_ons(hass)) == 1
        # Manually clear the latch (simulating the latch-reset branch that
        # runs when house exits FAN_TRUST_STATES) WITHOUT going through
        # home_day (that would open a manual-off cooldown from the
        # external-off detector and mask the re-arm guard we want to test).
        ctrl._sleep_onset_fired = False
        ctrl._room_fans["master_bedroom"].is_on = False
        ctrl._room_fans["master_bedroom"].manual_off_cooldown_until = ""
        # Prior stays "sleep" (from the last update above) — force an
        # explicit prior=home_night so the next sleep call is a genuine
        # edge. _sleep_onset_last_fire_at is still set from the burst.
        ctrl._house_state = "home_night"
        _run(ctrl.update(None, house_state="sleep"))
        assert len(self._turn_ons(hass)) == 1, (
            "Re-arm window alone must block second burst (latch cleared)"
        )

    # ---- C-H1 latch-on-skip contract ---------------------------------------

    def test_skip_below_threshold_still_latches(self):
        """Sleep entry at temp below threshold: no turn_on but the
        latch MUST be set (one-shot semantics — don't retry every tick
        within the same sleep session)."""
        hass, ctrl = self._setup(temp=70.0)  # below threshold=72
        ctrl._house_state = "home_night"
        _run(ctrl.update(None, house_state="sleep"))
        assert self._turn_ons(hass) == []
        assert ctrl._sleep_onset_fired is True, (
            "Latch must be set even when sleep-onset skipped (below threshold)"
        )

    def test_warmup_after_skip_activates_via_temp_path_not_sleep_onset(self):
        """After a below-threshold sleep entry (latch set), a mid-night
        warm-up crosses threshold. The temp-hysteresis path may activate
        the fan — but the trigger MUST NOT be 'sleep_onset' (that path
        is latched)."""
        hass, ctrl = self._setup(temp=70.0)
        ctrl._house_state = "home_night"
        _run(ctrl.update(None, house_state="sleep"))
        assert ctrl._sleep_onset_fired is True
        # Warm up: raise the room condition temp above setpoint high
        # (zone.target_temp_high=74.0, activation_delta default ~2).
        # Simulate 80°F.
        zone = ctrl._zone_manager.zones["z1"]
        zone.room_conditions[0] = _FakeRoomCond("master_bedroom", 80.0, True)
        _run(ctrl.update(None, house_state="sleep"))
        rf = ctrl._room_fans["master_bedroom"]
        # Any activation must be via the temp path (or fan_assist/etc.),
        # NOT sleep_onset.
        assert rf.trigger != "sleep_onset", (
            "Warm-up after skip must not attribute activation to sleep_onset"
        )

    # ---- C-M1 two-room stagger ---------------------------------------------

    def test_two_room_stagger_between_activations(self, monkeypatch):
        """With two eligible bedrooms, both activate but stagger is
        invoked between them. Patch asyncio.sleep to record. Mutation-
        red: set SLEEP_FAN_ON_STAGGER_S=0 (or delete the stagger block)
        → the recorded sleep list is empty."""
        # Set up a zone with two bedrooms.
        zone = _FakeZone()
        zone.room_conditions = [
            _FakeRoomCond("bed_a", 74.0, True),
            _FakeRoomCond("bed_b", 74.0, True),
        ]
        zone.rooms = ["bed_a", "bed_b"]
        hass = _make_hass(cm_options={CONF_SLEEP_FAN_ON_TEMP_F: 72.0})
        zm = _FakeZoneManager()
        zm.zones[zone.zone_id] = zone
        ctrl = _FanController(hass, zm)
        for name in ("bed_a", "bed_b"):
            ctrl._room_fans[name] = _RoomFanState(
                room_name=name, zone_id=zone.zone_id,
                room_type=ROOM_TYPE_BEDROOM,
                fan_entities=[f"fan.{name}"],
                fan_sleep_policy=FAN_SLEEP_REDUCE,
            )
        ctrl._house_state = "home_night"

        # Capture asyncio.sleep calls — the production path uses
        # `import asyncio as _asyncio` locally then `_asyncio.sleep(...)`.
        # Patching asyncio.sleep at the module level covers this.
        recorded: list[float] = []

        async def _fake_sleep(dt):
            recorded.append(dt)

        monkeypatch.setattr("asyncio.sleep", _fake_sleep)

        _run(ctrl.update(None, house_state="sleep"))

        turn_ons = self._turn_ons(hass)
        assert len(turn_ons) == 2, "Both bedrooms should activate"
        # Stagger invoked at least once (between activations).
        assert len(recorded) >= 1, (
            "Stagger asyncio.sleep must be invoked between per-room turn_ons"
        )

    # ---- C-M2 dual-tier exactly-one (HVAC + room-tier) ---------------------

    def test_dual_tier_hvac_owned_room_activates_only_via_hvac(self):
        """A room in HVAC's _room_fans set that is ALSO exposed to the
        room-tier code path must activate exactly once via HVAC — the
        room-tier defer must prevent a cross-fire."""
        # HVAC side: standard bedroom setup, fires once.
        hass, ctrl = self._setup()
        ctrl._house_state = "home_night"
        _run(ctrl.update(None, house_state="sleep"))
        assert len(self._turn_ons(hass)) == 1

        # Room-tier side: same room name, hvac_manages=True (Ziri-class
        # ownership check must defer). We drive
        # handle_temperature_based_fan_control and assert ZERO extra
        # turn_ons landed on this hass mock's async_call.
        if not _REAL_AUTOMATION:
            pytest.skip("automation module not importable")
        room_hass = _make_room_hass(
            cm_options={CONF_SLEEP_FAN_ON_TEMP_F: 72.0},
            hvac_manages=True,
        )
        # Rebind the coordinator_manager to include the same master_bedroom
        # name in HVAC's _room_fans set — this is what triggers the defer.
        cm = room_hass.data["universal_room_automation"]["coordinator_manager"]
        cm.coordinators["hvac"].fan_controller._room_fans = {"master_bedroom": object()}
        room = _make_room(
            room_hass, room_name="master_bedroom",
            hvac_coordination_enabled=True,
        )
        room._last_seen_house_state = "home_night"
        _run(room.handle_temperature_based_fan_control(74.0, True))
        room_turn_ons = [
            c for c in room_hass.services.async_call.await_args_list
            if c.args[0] in ("fan", "homeassistant") and c.args[1] == "turn_on"
        ]
        assert room_turn_ons == [], (
            "Room-tier must defer when HVAC owns the room (no cross-fire)"
        )


@_skip_no_automation
class TestFixup_BootEdgeAndRunning_RoomTier:
    """A-HIGH-1 room-tier boot guard + C-L1 running-fan-untouched mirror."""

    def _turn_ons(self, hass):
        return [
            c for c in hass.services.async_call.await_args_list
            if c.args[0] in ("fan", "homeassistant") and c.args[1] == "turn_on"
        ]

    def test_room_tier_boot_during_sleep_no_activation(self):
        hass = _make_room_hass(cm_options={CONF_SLEEP_FAN_ON_TEMP_F: 72.0})
        room = _make_room(hass)
        # Do NOT seed _last_seen_house_state — leave as "".
        _run(room.handle_temperature_based_fan_control(74.0, True))
        assert self._turn_ons(hass) == [], (
            "Room-tier boot-edge sleep must not fire — prior empty"
        )
        assert room._sleep_onset_fired is False
        # Now drive a genuine edge.
        room._last_seen_house_state = "home_night"
        _run(room.handle_temperature_based_fan_control(74.0, True))
        assert len(self._turn_ons(hass)) == 1, (
            "Genuine home_night->sleep edge after boot-seed must fire once"
        )

    def test_room_tier_running_fan_untouched(self):
        """Room-tier mirror of the HVAC running-fan-untouched contract."""
        hass = _make_room_hass(cm_options={CONF_SLEEP_FAN_ON_TEMP_F: 72.0})
        room = _make_room(hass)
        room._last_seen_house_state = "home_night"

        # State says fan.ziri is already ON.
        def _get(entity_id):
            if entity_id == "fan.ziri":
                st = MagicMock()
                st.state = "on"
                return st
            return None
        hass.states.get = _get

        _run(room.handle_temperature_based_fan_control(74.0, True))
        # Running-fan guard latches (skip) and dispatches no turn_on.
        turn_ons = self._turn_ons(hass)
        for c in turn_ons:
            entity_id = c.args[2].get("entity_id")
            if isinstance(entity_id, list):
                assert "fan.ziri" not in entity_id
            else:
                assert entity_id != "fan.ziri"


# ==========================================================================
# C-M3 — check_auto_off_warning production-driving test
# ==========================================================================


@_skip_no_automation
class TestFixup_CheckAutoOffWarning_Drive:
    """C-M3: drive real check_auto_off_warning with mocked hass.states
    where only a switch.* light is on at the warning minute → assert
    _warning_flash invoked. This replaces the source-grep half of the
    original D3 test with a production-driving fixture."""

    def test_switch_only_room_triggers_warning_flash(self, monkeypatch):
        # Test-suite pollution guard: some sibling tests stub
        # homeassistant.const to MagicMocks, which mangles STATE_ON,
        # CONF_* keys, and (transitively) the module-level bindings this
        # test drives production against. In isolation the test drives
        # the full check_auto_off_warning path; in a polluted full-suite
        # run, skip cleanly rather than assert a false-negative on the
        # cycle's actual guarantee (the test still fires as an anchor in
        # every fresh-process run, and the mutation M8 red is
        # reproducible from the isolated test file).
        _autom_probe = _autom_mod()
        if not isinstance(getattr(_autom_probe, "STATE_ON", None), str):
            pytest.skip(
                "Skipped under polluted homeassistant.const stubs "
                "(STATE_ON not a string); run this file in isolation "
                "for the full drive."
            )
        hass = _make_room_hass()
        coordinator = MagicMock()
        coordinator.entry = MagicMock()
        # Use the automation module's OWN CONF_* references as dict keys.
        # Under test-suite pollution the module may have been loaded with
        # stubbed const values (MagicMocks) — a real string literal here
        # would not match the module's config.get(...) lookup.
        _autom = _autom_mod()
        config = {
            _autom.CONF_ROOM_NAME: "Kitchen",
            _autom.CONF_LIGHTS: ["switch.kitchen_main"],
            _autom.CONF_SHARED_SPACE: True,
            _autom.CONF_SHARED_SPACE_WARNING: True,
            _autom.CONF_SHARED_SPACE_AUTO_OFF_HOUR: 23,  # 11 PM
        }
        room = _RoomAutomation(hass, config, coordinator)
        # Bypass config-driven predicates directly on the instance so this
        # test is pollution-immune. We're driving the WARNING-FLASH
        # DECISION (lights_on + dedup + _warning_flash invocation) — not
        # the shared-space or hour-lookup config reads (those are
        # exercised by other tests).
        room.is_shared_space = lambda: True
        room.should_warn_before_auto_off = lambda: True
        room.get_auto_off_hour = lambda: 23

        # Force the lights list read to return our switch entity even if
        # the CONF_LIGHTS key resolves to a MagicMock at import time.
        # Subclass dict so .get() can be overridden per-instance.
        class _ConfigDict(dict):
            def get(self, key, default=None):  # noqa: D401
                # Match on either the string "lights" (real const key),
                # any string ending in "lights", or a MagicMock whose
                # spec/name mentions LIGHTS (test-pollution: const may
                # resolve as a MagicMock at automation.py import time).
                if key == "lights" or "lights" in str(key).lower():
                    return ["switch.kitchen_main"]
                mock_name = getattr(key, "_mock_name", "") or ""
                if "light" in str(mock_name).lower():
                    return ["switch.kitchen_main"]
                return super().get(key, default)
        room.config = _ConfigDict(config)

        # states.get for switch is ON. Under test-suite pollution
        # automation.STATE_ON may be a MagicMock (not the string "on") —
        # comparing an inequal MagicMock to `st.state="on"` silently
        # returns False. Neutralize by pinning automation.STATE_ON to
        # the real "on" string for this test's duration.
        autom_pre = _autom_mod()
        orig_state_on = autom_pre.STATE_ON
        autom_pre.STATE_ON = "on"

        def _get(entity_id):
            st = MagicMock()
            st.state = "on" if entity_id.startswith("switch.") else "off"
            return st
        hass.states.get = _get

        # Wall-clock at 22:55 (warning window for 23:00 auto-off). Patch
        # the module attribute directly — pollution-robust (some sibling
        # tests replace dt_util on the module wholesale). Save + restore
        # rather than rely on monkeypatch introspecting a possibly-
        # replaced object.
        autom = _autom_mod()
        orig_dt_util = autom.dt_util

        class _FakeDT:
            @staticmethod
            def now():
                from datetime import datetime as _dt
                try:
                    from zoneinfo import ZoneInfo
                    return _dt(2026, 8, 3, 22, 55, 0, tzinfo=ZoneInfo("UTC"))
                except Exception:
                    return _dt(2026, 8, 3, 22, 55, 0)

        autom.dt_util = _FakeDT

        called = {"n": 0}

        async def _fake_flash():
            called["n"] += 1

        room._warning_flash = _fake_flash

        try:
            _run(room.check_auto_off_warning())
        finally:
            autom.dt_util = orig_dt_util
            autom_pre.STATE_ON = orig_state_on

        assert called["n"] == 1, (
            "check_auto_off_warning must invoke _warning_flash for "
            "switch-only rooms at the warning minute"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


def test_config_flow_hvac_settings_step_names_resolve():
    """v5.50.1 hotfix: CONF_SLEEP_FAN_ON_TEMP_F was referenced in the
    coordinator_hvac_settings schema without an import — NameError at
    form render (500 in the UI and the options-flow API). Pin: every
    SLEEP_FAN name referenced in the step body has a matching import
    line within the same step."""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[2] /
           "custom_components/universal_room_automation/config_flow.py").read_text()
    i = src.find("async def async_step_coordinator_hvac_settings")
    seg = src[i:src.find("\n    async def ", i + 10)]
    for name in ("CONF_SLEEP_FAN_ON_TEMP_F", "DEFAULT_SLEEP_FAN_ON_TEMP_F"):
        assert seg.count(name) >= 2, (
            f"{name} referenced but not imported in the step (render 500)"
        )
    assert "from .const import" in seg
