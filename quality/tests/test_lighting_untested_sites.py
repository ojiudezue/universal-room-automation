"""Lighting roles (v5.103.29) — review-C residual sites R4, E8, E9, E10.

Review C's per-site mutation pass found four sites whose neutering left the
suite green. Each test here drives the REAL production method and is the
named anchor for one site:

  R4  actuator_reconciler._resolve_light — occupied entry gate
      ``if entity_id not in entry_set: return None`` (CONF_LIGHTS_ON_ENTRY
      non-members are never asserted ON by the reconciler).
  E8  automation._control_lights_entry — night lights get
      ``mode="evening"`` when the slot is Evening.
  E9  automation._control_lights_entry — default path threads ``slot=slot``
      into ``_turn_on_regular_lights``.
  E10 automation._control_lights_entry — explicit on-entry path applies
      ``slot_regular_light_overrides`` (evening brightness / colour).

Harness REUSED from ``test_lighting_slice_c_manual_hold.py`` (real
RoomAutomation + real ActuatorReconciler, real-module import scoping).
"""

from __future__ import annotations

from test_lighting_slice_c_manual_hold import (  # noqa: F401 — fixture reuse
    M,
    _light_calls,
    _real_modules,
    _run,
    make_room,
)


def _evening_cfg(**extra):
    const = M["const"]
    cfg = {
        const.CONF_LIGHT_CAPABILITIES: const.LIGHT_CAPABILITY_FULL,
        const.CONF_LIGHT_BRIGHTNESS_PCT: 100,
        const.CONF_LIGHT_EVENING_BRIGHTNESS_PCT: 40,
        const.CONF_LIGHT_EVENING_COLOR_KELVIN: 2400,
    }
    cfg.update(extra)
    return cfg


def _dark_room(cfg):
    room = make_room(config=cfg, occupied=True, sleep=False)
    room.auto.is_dark = lambda _lux=None: True  # evening = dark + not sleep
    return room


def _turn_on_data(room, entity_id):
    for c in _light_calls(room.hass, "turn_on"):
        e = c.data.get("entity_id")
        ids = [e] if isinstance(e, str) else list(e or [])
        if entity_id in ids:
            return c.data
    return None


# ---------------------------------------------------------------------------
# R4 — reconciler entry gate
# ---------------------------------------------------------------------------


def test_r4_reconciler_does_not_assert_on_for_non_on_entry_light():
    const = M["const"]
    room = make_room(config={const.CONF_LIGHTS_ON_ENTRY: ["light.a"]},
                     occupied=True)
    data = {const.STATE_OCCUPIED: True}
    # Member of the on-entry list: asserted ON.
    on = room.rec._resolve_light("light.a", data)
    assert on is not None and on.state == "on"
    # In CONF_LIGHTS but NOT in the on-entry list: reconciler stays out.
    assert room.rec._resolve_light("light.b", data) is None


# ---------------------------------------------------------------------------
# E8 — night lights pick the Evening mode
# ---------------------------------------------------------------------------


def test_e8_evening_entry_night_lights_use_evening_overrides():
    const = M["const"]
    room = _dark_room(_evening_cfg(**{
        const.CONF_NIGHT_LIGHTS: ["light.n"],
        const.CONF_NIGHT_LIGHT_EVENING_BRIGHTNESS: 17,
        const.CONF_NIGHT_LIGHT_EVENING_COLOR: 2300,
    }))
    _run(room.auto._control_lights_entry({}))
    data = _turn_on_data(room, "light.n")
    assert data is not None
    assert data["brightness_pct"] == 17
    assert data["color_temp_kelvin"] == 2300


# ---------------------------------------------------------------------------
# E9 — default path threads the slot into _turn_on_regular_lights
# ---------------------------------------------------------------------------


def test_e9_evening_entry_default_path_regular_lights_use_overrides():
    room = _dark_room(_evening_cfg())
    _run(room.auto._control_lights_entry({}))
    data = _turn_on_data(room, "light.a")
    assert data is not None
    assert data["brightness_pct"] == 40
    assert data["color_temp_kelvin"] == 2400


# ---------------------------------------------------------------------------
# E10 — explicit on-entry path applies slot overrides
# ---------------------------------------------------------------------------


def test_e10_evening_entry_on_entry_path_uses_overrides():
    const = M["const"]
    room = _dark_room(_evening_cfg(**{const.CONF_LIGHTS_ON_ENTRY: ["light.a"]}))
    _run(room.auto._control_lights_entry({}))
    data = _turn_on_data(room, "light.a")
    assert data is not None
    assert data["brightness_pct"] == 40
    assert data["color_temp_kelvin"] == 2400
    # light.b is not on the on-entry list.
    assert _turn_on_data(room, "light.b") is None


def test_e10_day_entry_on_entry_path_keeps_day_brightness():
    const = M["const"]
    room = make_room(config=_evening_cfg(**{const.CONF_LIGHTS_ON_ENTRY: ["light.a"]}),
                     occupied=True)
    room.auto.is_dark = lambda _lux=None: False  # day slot
    _run(room.auto._control_lights_entry({}))
    data = _turn_on_data(room, "light.a")
    assert data is not None
    assert data["brightness_pct"] == 100
    assert "color_temp_kelvin" not in data
