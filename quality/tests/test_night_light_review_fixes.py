"""NIGHT-LIGHT-ACTION-SELECTOR-1 (REV 3) — post-review fix pass.

Covers the 3-review findings:
- A/B HIGH-1: reconciler switch.* night light gets {} params (no
  brightness_pct / color_temp_kelvin → switch.turn_on).
- C HIGH / A MEDIUM: canonical ``_turn_on_night_lights`` routes through
  the shared ``night_light_turn_on_params`` helper so canonical and
  reconciler emit identical payloads (helper now owns transition +
  capability default BASIC; red hue stays per-entity in canonical).
- A/B MEDIUM: manual dim override — reconciler no longer forces a
  turn_on when a day/evening night light is already on at a different
  brightness.
- C MEDIUM: options-flow RENDERED default of ``night_lights_by_day`` is
  False (not just the module constant).
- C MEDIUM: canonical ``_night_set`` strip — a night light also listed
  in CONF_LIGHTS_ON_ENTRY is driven by night-light params, not the
  main-light turn_on batch.
- C LOW: ``night_lights_by_day`` is in the room-level reload-suppress
  frozenset in ``__init__.py``.
"""
from __future__ import annotations

from pathlib import Path

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
    yield


def _c():
    return M["const"]


def _mk(**cfg_extra):
    const = _c()
    base = {
        const.CONF_LIGHTS: ["light.main"],
        const.CONF_NIGHT_LIGHTS: ["light.night"],
        const.CONF_LIGHT_CAPABILITIES: const.LIGHT_CAPABILITY_FULL,
        const.CONF_ENTRY_LIGHT_ACTION: const.LIGHT_ACTION_NONE,
    }
    base.update(cfg_extra)
    return make_room(config=base, occupied=True, sleep=False)


def _set_dark(room, is_dark):
    room.auto.is_dark = lambda _lux=None: bool(is_dark)


# ---------------------------------------------------------------------------
# A/B HIGH-1 — reconciler switch.* night light gets {} params.
# ---------------------------------------------------------------------------


def test_reconciler_switch_night_light_has_no_light_params():
    const = _c()
    room = _mk(**{
        const.CONF_NIGHT_LIGHTS: ["switch.night_sw"],
        const.CONF_NIGHT_LIGHTS_BY_DAY: True,
    })
    _set_dark(room, False)
    out = room.rec._resolve_light(
        "switch.night_sw", {const.STATE_OCCUPIED: True},
    )
    assert out is not None and out.state == "on"
    assert out.domain == "switch"
    assert out.params == {}
    assert "brightness_pct" not in out.params
    assert "color_temp_kelvin" not in out.params


# ---------------------------------------------------------------------------
# C HIGH / A MEDIUM — golden canonical payloads + canonical==reconciler
# parity through the shared helper.
# ---------------------------------------------------------------------------


def _canonical_night_service_data(room, mode):
    """Drive canonical ``_turn_on_night_lights`` and return the single
    light.turn_on service_data dict it emits (ignoring entity_id)."""
    _run(room.auto._turn_on_night_lights(mode=mode))
    calls = _light_calls(room.hass, "turn_on")
    light_calls = [c for c in calls if c.domain == "light"]
    assert light_calls, f"canonical emitted no light.turn_on for mode={mode}"
    data = dict(light_calls[-1].data)
    data.pop("entity_id", None)
    return data


@pytest.mark.parametrize("mode", ["sleep", "day", "evening"])
def test_canonical_payload_full_capability_matches_helper(mode):
    """Golden: canonical light.turn_on service_data for FULL capability
    at each mode equals helper(include_transition=True) + no red (the
    default sleep hue is RED, but under FakeHass states return None →
    supports_rgb False → no rgb_color override)."""
    from custom_components.universal_room_automation.lighting.resolver import (
        night_light_turn_on_params,
    )
    const = _c()
    room = _mk()
    data = _canonical_night_service_data(room, mode)
    expected = night_light_turn_on_params(
        room.auto.config, mode, include_transition=True,
    )
    assert data == expected
    assert "transition" in data
    assert "brightness_pct" in data
    assert "color_temp_kelvin" in data


@pytest.mark.parametrize("mode", ["sleep", "day", "evening"])
def test_canonical_payload_brightness_capability_matches_helper(mode):
    from custom_components.universal_room_automation.lighting.resolver import (
        night_light_turn_on_params,
    )
    const = _c()
    room = _mk(**{const.CONF_LIGHT_CAPABILITIES: const.LIGHT_CAPABILITY_BRIGHTNESS})
    data = _canonical_night_service_data(room, mode)
    expected = night_light_turn_on_params(
        room.auto.config, mode, include_transition=True,
    )
    assert data == expected
    assert "color_temp_kelvin" not in data
    assert "brightness_pct" in data


@pytest.mark.parametrize("mode", ["sleep", "day", "evening"])
def test_canonical_payload_basic_capability_matches_helper(mode):
    from custom_components.universal_room_automation.lighting.resolver import (
        night_light_turn_on_params,
    )
    const = _c()
    room = _mk(**{const.CONF_LIGHT_CAPABILITIES: const.LIGHT_CAPABILITY_BASIC})
    data = _canonical_night_service_data(room, mode)
    expected = night_light_turn_on_params(
        room.auto.config, mode, include_transition=True,
    )
    assert data == expected
    assert "brightness_pct" not in data
    assert "color_temp_kelvin" not in data
    assert data.get("transition") is not None


def test_canonical_and_reconciler_agree_day_full():
    """Canonical service_data (minus transition / entity_id) == reconciler
    params for the same room/mode (day, FULL capability, by-day admit)."""
    const = _c()
    room = _mk(**{const.CONF_NIGHT_LIGHTS_BY_DAY: True})
    _set_dark(room, False)
    out = room.rec._resolve_light(
        "light.night", {const.STATE_OCCUPIED: True},
    )
    assert out is not None and out.state == "on"
    canon = _canonical_night_service_data(room, "day")
    canon.pop("transition", None)
    assert out.params == canon


# ---------------------------------------------------------------------------
# A/B MEDIUM — manual dim override: already-on night light during day
# does not get reset.
# ---------------------------------------------------------------------------


def test_reconciler_day_night_light_already_on_at_dim_no_turn_on():
    const = _c()
    room = _mk(**{const.CONF_NIGHT_LIGHTS_BY_DAY: True})
    _set_dark(room, False)
    # Person dimmed it to 20% manually. State is "on"; brightness attr not
    # inspected by _resolve_light — the no-op gate is state-based.
    room.hass.set_state("light.night", "on")
    before = len(_light_calls(room.hass, "turn_on"))
    _run(room.rec._reconcile_one("light.night"))
    after = len(_light_calls(room.hass, "turn_on"))
    assert after == before, (
        "reconciler must not re-emit turn_on for an already-on day "
        "night light (manual-dim override preserved)"
    )


def test_reconciler_day_night_light_off_still_turns_on():
    """Control: when currently OFF, the reconciler DOES fire turn_on
    with the night-light params. The manual-dim fix must not break the
    first-time turn-on."""
    const = _c()
    room = _mk(**{const.CONF_NIGHT_LIGHTS_BY_DAY: True})
    _set_dark(room, False)
    room.hass.set_state("light.night", "off")
    before = len(_light_calls(room.hass, "turn_on"))
    _run(room.rec._reconcile_one("light.night"))
    after = len(_light_calls(room.hass, "turn_on"))
    assert after == before + 1


# ---------------------------------------------------------------------------
# C MEDIUM — options-flow RENDERED default of night_lights_by_day is False.
# ---------------------------------------------------------------------------


def test_options_flow_rendered_default_night_lights_by_day_is_false():
    from _room_menu_helpers import make_flow, render
    from custom_components.universal_room_automation.const import (
        CONF_NIGHT_LIGHTS_BY_DAY,
        ROOM_TYPE_BEDROOM,
    )
    import voluptuous as vol

    rendered = render(make_flow(ROOM_TYPE_BEDROOM), "options_lighting_behaviour")
    schema = rendered["data_schema"]
    found = None
    for marker in schema.schema:
        key = getattr(marker, "schema", marker)
        if key == CONF_NIGHT_LIGHTS_BY_DAY:
            found = marker
            break
    assert found is not None, "night_lights_by_day missing from rendered schema"
    default = found.default
    # vol.Optional stores default as a callable (or vol.UNDEFINED).
    if callable(default):
        default = default()
    assert default is False, f"rendered schema default was {default!r}, want False"


# ---------------------------------------------------------------------------
# C MEDIUM — canonical _night_set strip: night light in on-entry picker
# is driven by night-light params, not main-light params.
# ---------------------------------------------------------------------------


def test_canonical_night_set_strip_dark_room_on_entry_picker():
    """Dark room, CONF_LIGHTS_ON_ENTRY=[main, night], action=TURN_ON:
    light.night must appear ONLY in a night-light turn_on batch (with
    night-light brightness/colour), NEVER in the main-light batch."""
    const = _c()
    room = _mk(**{
        const.CONF_LIGHTS: ["light.main"],
        const.CONF_NIGHT_LIGHTS: ["light.night"],
        const.CONF_LIGHTS_ON_ENTRY: ["light.main", "light.night"],
        const.CONF_ENTRY_LIGHT_ACTION: const.LIGHT_ACTION_TURN_ON,
    })
    _set_dark(room, True)
    _run(room.auto._control_lights_entry({}))
    turn_ons = _light_calls(room.hass, "turn_on")
    assert turn_ons, "no light.turn_on emitted"
    night_batches = []
    main_batches = []
    for c in turn_ons:
        if c.domain != "light":
            continue
        eids = c.data.get("entity_id")
        eids = [eids] if isinstance(eids, str) else list(eids or [])
        if "light.night" in eids:
            night_batches.append(c)
            assert "light.main" not in eids, (
                "night light must not share a batch with main lights"
            )
        if "light.main" in eids:
            main_batches.append(c)
            assert "light.night" not in eids
    assert night_batches, "light.night was not turned on at all"
    # The night-light batch carries night brightness, not the main-light
    # brightness_pct constant.
    from custom_components.universal_room_automation.lighting.resolver import (
        night_light_turn_on_params,
    )
    expected = night_light_turn_on_params(
        room.auto.config, "evening", include_transition=True,
    )
    data = dict(night_batches[-1].data)
    data.pop("entity_id", None)
    assert data == expected


# ---------------------------------------------------------------------------
# C LOW — night_lights_by_day is in the room-level reload-suppress set.
# ---------------------------------------------------------------------------


def test_night_lights_by_day_in_room_suppress_set():
    """The ``_ROOM_SUPPRESS_KEYS`` frozenset in ``__init__.py`` must
    contain the key — otherwise a toggle of ``night_lights_by_day``
    triggers a full room reload (RELOAD-WATCHDOG-HAZARD)."""
    path = (
        Path(__file__).resolve().parents[2]
        / "custom_components" / "universal_room_automation" / "__init__.py"
    )
    src = path.read_text()
    marker = "_ROOM_SUPPRESS_KEYS: frozenset[str] = frozenset({"
    i = src.find(marker)
    assert i != -1, "could not locate _ROOM_SUPPRESS_KEYS frozenset"
    # Find the matching closing brace of the literal (first '})' after i).
    j = src.find("})", i)
    assert j != -1
    block = src[i:j]
    assert '"night_lights_by_day"' in block, (
        "night_lights_by_day missing from _ROOM_SUPPRESS_KEYS"
    )
