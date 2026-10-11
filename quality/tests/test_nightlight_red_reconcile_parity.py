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
