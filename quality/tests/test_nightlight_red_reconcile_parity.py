"""NIGHTLIGHT-RED-RECONCILE-PARITY-1 — canonical vs reconciler red-hue parity.

A colour-capable night light reconnecting (``unavailable -> available``)
while the room is at sleep must come back RED (``rgb_color``), not warm
white (``color_temp_kelvin``). Before this cycle, the red-hue decision
lived only in ``automation._turn_on_night_lights``; the reconcile-on-
return path went through the shared resolver, which only emitted kelvin.

These tests pin the resolver as the single owner of the decision:

* resolver with ``supported_color_modes`` of a colour bulb at sleep →
  ``rgb_color`` red, NO ``color_temp_kelvin``.
* resolver without modes → kelvin (back-compat; preserves pre-cycle
  tests and callers that cannot read live modes).
* a colour_temp-only bulb at sleep → kelvin (no red forced).
* non-sleep modes never emit red.
* behavioural anchor: the reconciler sleep+occupied branch calls
  ``night_light_turn_on_params`` with the entity's live
  ``supported_color_modes``; replacing that call site with a no-op makes
  the colour-light anchor test fail (call-neuter drill).
"""
from __future__ import annotations

import pytest

from test_lighting_slice_c_manual_hold import (  # noqa: F401
    M,
    _light_calls,
    _real_modules,
    _run,
    make_room,
)


@pytest.fixture(scope="module", autouse=True)
def _bootstrap_modules(_real_modules):  # noqa: F811
    """Chain the sibling module's real-module importer so ``M`` is populated."""
    yield


from custom_components.universal_room_automation.const import (
    CONF_LIGHT_CAPABILITIES,
    CONF_NIGHT_LIGHT_SLEEP_HUE,
    CONF_NIGHT_LIGHTS,
    LIGHT_CAPABILITY_BASIC,
    LIGHT_CAPABILITY_BRIGHTNESS,
    LIGHT_CAPABILITY_FULL,
    NIGHT_LIGHT_SLEEP_HUE_RED,
    NIGHT_LIGHT_SLEEP_HUE_WARM_WHITE,
    NIGHT_LIGHT_SLEEP_RED_RGB,
)
from custom_components.universal_room_automation.lighting.resolver import (
    night_light_turn_on_params,
)


def _cfg_full_red():
    return {
        CONF_LIGHT_CAPABILITIES: LIGHT_CAPABILITY_FULL,
        CONF_NIGHT_LIGHT_SLEEP_HUE: NIGHT_LIGHT_SLEEP_HUE_RED,
    }


# ---------------------------------------------------------------------------
# Resolver — owns the red-hue decision
# ---------------------------------------------------------------------------


def test_sleep_full_red_colour_capable_emits_rgb_not_kelvin():
    """A colour-capable bulb (hs modes) at sleep gets rgb_color red."""
    out = night_light_turn_on_params(
        _cfg_full_red(), "sleep", supported_color_modes={"hs"},
    )
    assert out.get("rgb_color") == list(NIGHT_LIGHT_SLEEP_RED_RGB)
    assert "color_temp_kelvin" not in out
    # xy / rgb / rgbw / rgbww all qualify as colour-capable
    for mode in ("rgb", "rgbw", "rgbww", "xy"):
        out = night_light_turn_on_params(
            _cfg_full_red(), "sleep", supported_color_modes={mode},
        )
        assert out.get("rgb_color") == list(NIGHT_LIGHT_SLEEP_RED_RGB), mode
        assert "color_temp_kelvin" not in out, mode


def test_sleep_full_red_colour_temp_only_bulb_emits_kelvin():
    """A kelvin-only bulb (no rgb/hs/xy mode) at sleep stays warm white."""
    out = night_light_turn_on_params(
        _cfg_full_red(), "sleep", supported_color_modes={"color_temp"},
    )
    assert "rgb_color" not in out
    assert "color_temp_kelvin" in out


def test_sleep_hue_warm_white_never_emits_red():
    cfg = {
        CONF_LIGHT_CAPABILITIES: LIGHT_CAPABILITY_FULL,
        CONF_NIGHT_LIGHT_SLEEP_HUE: NIGHT_LIGHT_SLEEP_HUE_WARM_WHITE,
    }
    out = night_light_turn_on_params(
        cfg, "sleep", supported_color_modes={"rgb"},
    )
    assert "rgb_color" not in out
    assert "color_temp_kelvin" in out


def test_non_sleep_modes_never_emit_red():
    for mode in ("day", "evening"):
        out = night_light_turn_on_params(
            _cfg_full_red(), mode, supported_color_modes={"rgb"},
        )
        assert "rgb_color" not in out, mode
        assert "color_temp_kelvin" in out, mode


def test_brightness_only_bulb_has_no_colour_fields():
    cfg = {
        CONF_LIGHT_CAPABILITIES: LIGHT_CAPABILITY_BRIGHTNESS,
        CONF_NIGHT_LIGHT_SLEEP_HUE: NIGHT_LIGHT_SLEEP_HUE_RED,
    }
    out = night_light_turn_on_params(
        cfg, "sleep", supported_color_modes={"rgb"},
    )
    assert "rgb_color" not in out
    assert "color_temp_kelvin" not in out
    assert "brightness_pct" in out


def test_default_without_modes_backcompat_kelvin():
    """``supported_color_modes=None`` preserves the pre-cycle kelvin path."""
    out = night_light_turn_on_params(_cfg_full_red(), "sleep")
    assert "rgb_color" not in out
    assert "color_temp_kelvin" in out


# ---------------------------------------------------------------------------
# Behavioural anchor — the reconciler's sleep+occupied branch MUST route
# through the resolver's rgb output when the bulb is colour-capable. This
# test fails if the call site is neutered (call-neuter drill).
# ---------------------------------------------------------------------------


def test_reconciler_sleep_occupied_colour_light_asserts_red():
    """Direct per-site anchor: the reconciler's sleep-occupied night-light
    branch produces rgb_color red for a colour-capable bulb.

    We stub the hass/coordinator shim just enough to call
    ``resolve_desired_state`` without the full HA harness.
    """
    from custom_components.universal_room_automation import actuator_reconciler
    from custom_components.universal_room_automation.const import (
        CONF_ENTRY_LIGHT_ACTION,
        LIGHT_ACTION_NONE,
        STATE_OCCUPIED,
    )

    class _StubState:
        def __init__(self, modes):
            self.attributes = {"supported_color_modes": modes}

    class _StubStates:
        def __init__(self, modes):
            self._modes = modes

        def get(self, _eid):
            return _StubState(self._modes)

    class _StubHass:
        def __init__(self, modes):
            self.states = _StubStates(modes)

    class _StubAutomation:
        def is_sleep_lighting_active(self):
            return True

        def is_sleep_mode_active(self):
            return True

        def is_dark(self, _):
            return True

        def _house_state_is_sleep(self):
            return True

    class _StubCoordinator:
        def __init__(self, cfg, modes):
            self.hass = _StubHass(modes)
            self.config_entry = type("CE", (), {"options": cfg, "data": {}})()
            self.data = {STATE_OCCUPIED: True}
            self.automation = _StubAutomation()

    cfg = {
        CONF_NIGHT_LIGHTS: ["light.red_bulb"],
        CONF_LIGHT_CAPABILITIES: LIGHT_CAPABILITY_FULL,
        CONF_NIGHT_LIGHT_SLEEP_HUE: NIGHT_LIGHT_SLEEP_HUE_RED,
        CONF_ENTRY_LIGHT_ACTION: LIGHT_ACTION_NONE,
    }
    coord = _StubCoordinator(cfg, modes=["hs"])
    rec = actuator_reconciler.ActuatorReconciler.__new__(
        actuator_reconciler.ActuatorReconciler,
    )
    rec.coordinator = coord
    rec.hass = coord.hass
    # bypass tracked-entity gate
    rec._tracked_entities = lambda: {"light.red_bulb"}
    rec._is_fan = lambda _e: False
    # bypass _config() reader
    rec._config = lambda: cfg

    out = rec.resolve_desired_state("light.red_bulb")
    assert out is not None
    assert out.state == "on"
    assert out.params.get("rgb_color") == list(NIGHT_LIGHT_SLEEP_RED_RGB)
    assert "color_temp_kelvin" not in out.params

    # And a kelvin-only bulb takes the warm-white path.
    coord2 = _StubCoordinator(cfg, modes=["color_temp"])
    rec2 = actuator_reconciler.ActuatorReconciler.__new__(
        actuator_reconciler.ActuatorReconciler,
    )
    rec2.coordinator = coord2
    rec2.hass = coord2.hass
    rec2._tracked_entities = lambda: {"light.red_bulb"}
    rec2._is_fan = lambda _e: False
    rec2._config = lambda: cfg
    out2 = rec2.resolve_desired_state("light.red_bulb")
    assert out2 is not None
    assert "rgb_color" not in out2.params
    assert "color_temp_kelvin" in out2.params


# ---------------------------------------------------------------------------
# Canonical writer side — hoisted import + per-entity modes passed to
# resolver. Drives REAL ``RoomAutomation._turn_on_night_lights`` under the
# shared harness, with a colour bulb and a kelvin-only bulb side by side.
# ---------------------------------------------------------------------------


def test_canonical_turn_on_night_lights_colour_and_kelvin_sleep():
    """Mixed colour + kelvin bulbs at sleep: colour → rgb_color red,
    kelvin-only → color_temp_kelvin. Matches the reconciler.
    """
    from types import SimpleNamespace

    from test_lighting_slice_c_manual_hold import (  # noqa: F401
        M, _light_calls, _real_modules, _run, make_room,
    )

    # Dummy pytest fixture bootstrapping: the sibling module's autouse
    # fixture is scoped per-module, so just reach in and import M here.
    assert "const" in M, "sibling test module must be imported first"
    const = M["const"]

    base = {
        const.CONF_LIGHTS: ["light.main"],
        const.CONF_NIGHT_LIGHTS: ["light.rgb_bulb", "light.kelvin_bulb"],
        const.CONF_LIGHT_CAPABILITIES: const.LIGHT_CAPABILITY_FULL,
        const.CONF_NIGHT_LIGHT_SLEEP_HUE: NIGHT_LIGHT_SLEEP_HUE_RED,
        const.CONF_ENTRY_LIGHT_ACTION: const.LIGHT_ACTION_NONE,
    }
    room = make_room(config=base, occupied=True, sleep=True)
    # Seed hass state so the per-entity capability read works.
    room.hass._states["light.rgb_bulb"] = SimpleNamespace(
        entity_id="light.rgb_bulb", state="off",
        attributes={"supported_color_modes": ["hs", "color_temp"]},
    )
    room.hass._states["light.kelvin_bulb"] = SimpleNamespace(
        entity_id="light.kelvin_bulb", state="off",
        attributes={"supported_color_modes": ["color_temp"]},
    )

    _run(room.auto._turn_on_night_lights("sleep"))

    on_calls = _light_calls(room.hass, "turn_on")
    # Collate per-entity params.
    seen: dict[str, dict] = {}
    for c in on_calls:
        eids = c.data.get("entity_id")
        eids = [eids] if isinstance(eids, str) else list(eids or [])
        params = {k: v for k, v in c.data.items() if k != "entity_id"}
        for e in eids:
            seen[e] = params
    assert "light.rgb_bulb" in seen, f"rgb bulb must be dispatched: {on_calls}"
    assert "light.kelvin_bulb" in seen, f"kelvin bulb must be dispatched: {on_calls}"
    assert seen["light.rgb_bulb"].get("rgb_color") == list(NIGHT_LIGHT_SLEEP_RED_RGB)
    assert "color_temp_kelvin" not in seen["light.rgb_bulb"]
    assert "rgb_color" not in seen["light.kelvin_bulb"]
    assert "color_temp_kelvin" in seen["light.kelvin_bulb"]


def test_reconciler_house_sleep_entry_branch_colour_light_asserts_red():
    """F1 (Review A): the ``entry_night_light`` branch (house_state=sleep
    while per-room ``is_sleep_lighting_active()`` is False) must also
    carry rgb_color red for a colour-capable bulb. This is the
    actuator_reconciler.py:~907-913 path, downstream of
    ``_mode = "sleep"`` set by the house_state override.

    Neutering the ``supported_color_modes=self._live_color_modes(eid)``
    kwarg on THAT call site previously left this cell untested; this
    test fills the gap.
    """
    from custom_components.universal_room_automation import actuator_reconciler
    from custom_components.universal_room_automation.const import (
        CONF_ENTRY_LIGHT_ACTION,
        LIGHT_ACTION_TURN_ON,
        STATE_ILLUMINANCE,
        STATE_OCCUPIED,
    )

    class _StubState:
        def __init__(self, modes):
            self.attributes = {"supported_color_modes": modes}

    class _StubStates:
        def __init__(self, modes):
            self._modes = modes

        def get(self, _eid):
            return _StubState(self._modes)

    class _StubHass:
        def __init__(self, modes):
            self.states = _StubStates(modes)

    class _StubAutomation:
        # Per-room sleep gate OFF, but house_state=sleep override ON.
        def is_sleep_lighting_active(self):
            return False

        def is_sleep_mode_active(self):
            return False

        def is_dark(self, _):
            return True

        def _house_state_is_sleep(self):
            return True

    class _StubCoordinator:
        def __init__(self, cfg, modes):
            self.hass = _StubHass(modes)
            self.data = {STATE_OCCUPIED: True, STATE_ILLUMINANCE: 0}
            self.automation = _StubAutomation()

    cfg = {
        CONF_NIGHT_LIGHTS: ["light.red_bulb"],
        CONF_LIGHT_CAPABILITIES: LIGHT_CAPABILITY_FULL,
        CONF_NIGHT_LIGHT_SLEEP_HUE: NIGHT_LIGHT_SLEEP_HUE_RED,
        CONF_ENTRY_LIGHT_ACTION: LIGHT_ACTION_TURN_ON,
    }
    coord = _StubCoordinator(cfg, modes=["xy"])
    rec = actuator_reconciler.ActuatorReconciler.__new__(
        actuator_reconciler.ActuatorReconciler,
    )
    rec.coordinator = coord
    rec.hass = coord.hass
    rec._tracked_entities = lambda: {"light.red_bulb"}
    rec._is_fan = lambda _e: False
    rec._config = lambda: cfg

    out = rec.resolve_desired_state("light.red_bulb")
    assert out is not None, "entry_night_light branch should assert ON"
    assert out.state == "on"
    assert out.reason == "entry_night_light", (
        f"must reach the house-sleep entry branch, got {out.reason!r}"
    )
    assert out.params.get("rgb_color") == list(NIGHT_LIGHT_SLEEP_RED_RGB)
    assert "color_temp_kelvin" not in out.params


def test_canonical_entry_main_qualifies_plus_house_sleep_night_light_red():
    """Review B B1-1: when the room's MAIN lights also qualify, the
    night-light-only early-return branch (~1456) is NOT taken, and the
    picker/else branches below (~1553/~1566) must apply the same
    house-Sleep mode-switch — otherwise colour night lights get
    evening/day kelvin while the house is sleeping.

    Repro: sleep_protection off, house=sleep, dark, main entry action
    turn-on, colour bulb in night lights. Expect rgb_color red.
    """
    from types import SimpleNamespace

    from test_lighting_slice_c_manual_hold import (  # noqa: F401
        M, _light_calls, _real_modules, _run, make_room,
    )

    const = M["const"]
    base = {
        const.CONF_LIGHTS: ["light.main"],
        const.CONF_NIGHT_LIGHTS: ["light.rgb_bulb"],
        const.CONF_LIGHT_CAPABILITIES: const.LIGHT_CAPABILITY_FULL,
        const.CONF_NIGHT_LIGHT_SLEEP_HUE: NIGHT_LIGHT_SLEEP_HUE_RED,
        const.CONF_ENTRY_LIGHT_ACTION: const.LIGHT_ACTION_TURN_ON,
        const.CONF_SLEEP_PROTECTION_ENABLED: False,
    }
    room = make_room(config=base, occupied=True, sleep=False)
    # House is in Sleep but per-room sleep gate is off.
    room.auto.is_sleep_mode_active = lambda: False
    room.auto.is_sleep_lighting_active = lambda: False
    room.auto._read_current_house_state = lambda: "sleep"
    # Dark so main lights qualify.
    room.auto.is_dark = lambda _lux=None: True
    room.hass._states["light.rgb_bulb"] = SimpleNamespace(
        entity_id="light.rgb_bulb", state="off",
        attributes={"supported_color_modes": ["hs"]},
    )
    _run(room.auto._control_lights_entry({}))

    on_calls = _light_calls(room.hass, "turn_on")
    rgb_calls = [c for c in on_calls
                 if "light.rgb_bulb" in (
                     [c.data.get("entity_id")] if isinstance(c.data.get("entity_id"), str)
                     else (c.data.get("entity_id") or [])
                 )]
    assert rgb_calls, f"night light must be dispatched: {on_calls}"
    assert any(
        c.data.get("rgb_color") == list(NIGHT_LIGHT_SLEEP_RED_RGB)
        for c in rgb_calls
    ), f"colour bulb at house-Sleep must get rgb_color red: {rgb_calls}"
    assert not any(
        "color_temp_kelvin" in c.data for c in rgb_calls
    ), f"must NOT ship kelvin for rgb bulb: {rgb_calls}"


def test_canonical_entry_picker_branch_house_sleep_night_light_red():
    """Review B B1-1 (picker site specifically): with
    ``CONF_LIGHTS_ON_ENTRY`` set, the ``has_on_entry`` branch
    (automation.py:~1553) must apply the same house-Sleep mode-switch
    as the else branch (~1566) and the night-light-only early return
    (~1456). This test drives the PICKER branch specifically so
    reverting only that site to evening/day is now caught (previous
    drill reverted both at once and masked this).

    Repro: sleep_protection off, house=sleep, dark, CONF_LIGHTS_ON_ENTRY
    picking the main light, night-lights-by-day on so the picker admits
    the colour night light. Expect rgb_color red.
    """
    from types import SimpleNamespace

    from test_lighting_slice_c_manual_hold import (  # noqa: F401
        M, _light_calls, _real_modules, _run, make_room,
    )

    const = M["const"]
    base = {
        const.CONF_LIGHTS: ["light.main"],
        const.CONF_NIGHT_LIGHTS: ["light.rgb_bulb"],
        # Picker branch trigger — this is what makes has_on_entry True.
        const.CONF_LIGHTS_ON_ENTRY: ["light.main"],
        const.CONF_LIGHT_CAPABILITIES: const.LIGHT_CAPABILITY_FULL,
        const.CONF_NIGHT_LIGHT_SLEEP_HUE: NIGHT_LIGHT_SLEEP_HUE_RED,
        const.CONF_ENTRY_LIGHT_ACTION: const.LIGHT_ACTION_TURN_ON,
        const.CONF_SLEEP_PROTECTION_ENABLED: False,
    }
    room = make_room(config=base, occupied=True, sleep=False)
    # House is in Sleep but per-room sleep gate is off (default).
    room.auto.is_sleep_mode_active = lambda: False
    room.auto.is_sleep_lighting_active = lambda: False
    room.auto._read_current_house_state = lambda: "sleep"
    room.auto.is_dark = lambda _lux=None: True
    room.hass._states["light.rgb_bulb"] = SimpleNamespace(
        entity_id="light.rgb_bulb", state="off",
        attributes={"supported_color_modes": ["hs"]},
    )
    _run(room.auto._control_lights_entry({}))

    on_calls = _light_calls(room.hass, "turn_on")
    rgb_calls = [c for c in on_calls
                 if "light.rgb_bulb" in (
                     [c.data.get("entity_id")] if isinstance(c.data.get("entity_id"), str)
                     else (c.data.get("entity_id") or [])
                 )]
    assert rgb_calls, (
        f"picker branch must still dispatch the night light: {on_calls}"
    )
    assert any(
        c.data.get("rgb_color") == list(NIGHT_LIGHT_SLEEP_RED_RGB)
        for c in rgb_calls
    ), f"picker branch at house-Sleep must emit rgb_color red: {rgb_calls}"
    assert not any(
        "color_temp_kelvin" in c.data for c in rgb_calls
    ), f"picker branch must NOT ship kelvin for rgb bulb: {rgb_calls}"


def test_reconciler_entry_night_light_sleep_has_params_to_apply():
    """Review B B1-2: ``entry_night_light`` under ``_mode == "sleep"``
    must set has_params_to_apply=True so the already-on gate (:645)
    cannot skip a factory-warm-white colour bulb returning on. Day /
    evening keep the R3-M3 manual-dim-override skip (False).
    """
    from custom_components.universal_room_automation import actuator_reconciler
    from custom_components.universal_room_automation.const import (
        CONF_ENTRY_LIGHT_ACTION,
        LIGHT_ACTION_TURN_ON,
        STATE_ILLUMINANCE,
        STATE_OCCUPIED,
    )

    class _StubState:
        def __init__(self, modes):
            self.attributes = {"supported_color_modes": modes}

    class _StubStates:
        def __init__(self, modes):
            self._modes = modes

        def get(self, _eid):
            return _StubState(self._modes)

    class _StubHass:
        def __init__(self, modes):
            self.states = _StubStates(modes)

    def _mk_automation(house_sleep: bool):
        a = type("A", (), {})()
        a.is_sleep_lighting_active = lambda: False
        a.is_sleep_mode_active = lambda: False
        a.is_dark = lambda _: True
        a._house_state_is_sleep = lambda: house_sleep
        return a

    def _mk(house_sleep: bool, modes):
        coord = type("C", (), {})()
        coord.hass = _StubHass(modes)
        coord.data = {STATE_OCCUPIED: True, STATE_ILLUMINANCE: 0}
        coord.automation = _mk_automation(house_sleep)
        cfg = {
            CONF_NIGHT_LIGHTS: ["light.red_bulb"],
            CONF_LIGHT_CAPABILITIES: LIGHT_CAPABILITY_FULL,
            CONF_NIGHT_LIGHT_SLEEP_HUE: NIGHT_LIGHT_SLEEP_HUE_RED,
            CONF_ENTRY_LIGHT_ACTION: LIGHT_ACTION_TURN_ON,
        }
        rec = actuator_reconciler.ActuatorReconciler.__new__(
            actuator_reconciler.ActuatorReconciler,
        )
        rec.coordinator = coord
        rec.hass = coord.hass
        rec._tracked_entities = lambda: {"light.red_bulb"}
        rec._is_fan = lambda _e: False
        rec._config = lambda: cfg
        return rec

    # Sleep (house=sleep): has_params_to_apply must be True.
    out_sleep = _mk(True, ["hs"]).resolve_desired_state("light.red_bulb")
    assert out_sleep is not None
    assert out_sleep.reason == "entry_night_light"
    assert out_sleep.has_params_to_apply is True, (
        "sleep mode must force re-apply so factory-warm-white bulbs flip to red"
    )

    # Day (house NOT sleep): keep R3-M3 — do NOT force-apply.
    out_day = _mk(False, ["hs"]).resolve_desired_state("light.red_bulb")
    assert out_day is not None
    assert out_day.reason == "entry_night_light"
    assert out_day.has_params_to_apply is False, (
        "day/evening must preserve manual-dim override (R3-M3)"
    )


def test_switch_room_lights_turn_on_colour_bulb_house_sleep_red():
    """Review B B1-3: RoomLightsSwitch.async_turn_on routes night-light
    params through the shared resolver with live colour modes.
    Repro: house=sleep, per-room sleep off, colour bulb → rgb_color red.
    """
    from types import SimpleNamespace

    from test_lighting_slice_c_manual_hold import (  # noqa: F401
        M, _light_calls, _real_modules, _run, make_room,
    )

    const = M["const"]
    from custom_components.universal_room_automation import switch as _switch

    base = {
        const.CONF_LIGHTS: ["light.main"],
        const.CONF_NIGHT_LIGHTS: ["light.rgb_bulb"],
        const.CONF_LIGHT_CAPABILITIES: const.LIGHT_CAPABILITY_FULL,
        const.CONF_NIGHT_LIGHT_SLEEP_HUE: NIGHT_LIGHT_SLEEP_HUE_RED,
    }
    room = make_room(config=base, occupied=True, sleep=False)
    room.auto.is_sleep_mode_active = lambda: False
    room.auto.is_sleep_lighting_active = lambda: False
    room.auto._house_state_is_sleep = lambda: True
    room.auto.is_dark = lambda _lux=None: True
    room.hass._states["light.rgb_bulb"] = SimpleNamespace(
        entity_id="light.rgb_bulb", state="off",
        attributes={"supported_color_modes": ["hs"]},
    )

    # Build a RoomLightsSwitch without triggering HA entity-platform wiring.
    sw = _switch.RoomLightsSwitch.__new__(_switch.RoomLightsSwitch)
    sw.hass = room.hass
    sw.coordinator = room.coord
    sw._cfg = lambda: room.auto.config
    sw._room_occupied = lambda: True
    sw.async_write_ha_state = lambda: None

    _run(sw.async_turn_on())
    on_calls = _light_calls(room.hass, "turn_on")
    rgb = [c for c in on_calls
           if "light.rgb_bulb" in (
               [c.data.get("entity_id")] if isinstance(c.data.get("entity_id"), str)
               else (c.data.get("entity_id") or [])
           )]
    assert rgb, f"RoomLightsSwitch must dispatch night light: {on_calls}"
    assert any(
        c.data.get("rgb_color") == list(NIGHT_LIGHT_SLEEP_RED_RGB)
        for c in rgb
    ), f"switch writer must emit rgb_color red at house-Sleep: {rgb}"


def test_canonical_turn_on_night_lights_day_mode_never_emits_red():
    """Outside sleep (day mode), colour bulbs never get rgb_color red."""
    from types import SimpleNamespace

    from test_lighting_slice_c_manual_hold import (  # noqa: F401
        M, _light_calls, _real_modules, _run, make_room,
    )

    const = M["const"]
    base = {
        const.CONF_LIGHTS: ["light.main"],
        const.CONF_NIGHT_LIGHTS: ["light.rgb_bulb"],
        const.CONF_LIGHT_CAPABILITIES: const.LIGHT_CAPABILITY_FULL,
        const.CONF_NIGHT_LIGHT_SLEEP_HUE: NIGHT_LIGHT_SLEEP_HUE_RED,
        const.CONF_ENTRY_LIGHT_ACTION: const.LIGHT_ACTION_NONE,
    }
    room = make_room(config=base, occupied=True, sleep=False)
    room.hass._states["light.rgb_bulb"] = SimpleNamespace(
        entity_id="light.rgb_bulb", state="off",
        attributes={"supported_color_modes": ["hs"]},
    )
    _run(room.auto._turn_on_night_lights("day"))

    on_calls = _light_calls(room.hass, "turn_on")
    for c in on_calls:
        assert "rgb_color" not in c.data, f"day mode must not emit red: {c.data}"
