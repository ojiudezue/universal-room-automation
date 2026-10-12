"""NIGHTLIGHT-RED-RECONCILE-PARITY-1 — canonical vs reconciler night-light
params at sleep for a colour-capable bulb (red), a white-only bulb
(kelvin), and the warm_white hue-config.

Before this fix:
- automation.py (:1838) sent ``rgb_color`` red for FULL + colour-capable
  bulbs at sleep when ``CONF_NIGHT_LIGHT_SLEEP_HUE=red``.
- actuator_reconciler.py (:883 nl-by-day branch; and the :820 sleep
  branch's brightness-only payload) went through ``_nl_params`` WITHOUT
  the bulb's modes, so a colour bulb reconnecting at sleep got
  ``color_temp_kelvin=2000`` (warm white).

After the fix, both call sites feed ``supported_color_modes`` into the
shared ``night_light_turn_on_params`` and emit identical params.
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
    yield


def _c():
    return M["const"]


def _mk_full(**extra):
    const = _c()
    cfg = {
        const.CONF_LIGHTS: ["light.main"],
        const.CONF_NIGHT_LIGHTS: ["light.night"],
        const.CONF_LIGHT_CAPABILITIES: const.LIGHT_CAPABILITY_FULL,
        const.CONF_ENTRY_LIGHT_ACTION: const.LIGHT_ACTION_NONE,
    }
    cfg.update(extra)
    # sleep=True drives both canonical _turn_on_night_lights(mode="sleep")
    # AND the reconciler's :820 sleep branch.
    return make_room(config=cfg, occupied=True, sleep=True)


def _set_modes(room, entity_id, modes):
    """Create a stub state with the given ``supported_color_modes`` so
    both ``hass.states.get(eid).attributes.get(...)`` reads succeed.
    Mirrors how a real colour-capable bulb reports its modes.
    """
    room.hass.set_state(entity_id, "off")
    room.hass._states[entity_id].attributes = {"supported_color_modes": list(modes)}


# ---------------------------------------------------------------------------
# Resolver unit tests — pure, HA-free. Pin the red/kelvin pivot.
# ---------------------------------------------------------------------------


def _resolver():
    from custom_components.universal_room_automation.lighting import resolver
    return resolver


def _nl_sleep_cfg(hue="red"):
    const = _c()
    return {
        const.CONF_LIGHT_CAPABILITIES: const.LIGHT_CAPABILITY_FULL,
        const.CONF_NIGHT_LIGHT_SLEEP_HUE: hue,
    }


@pytest.mark.parametrize("mode_name", ["rgb", "rgbw", "rgbww", "hs", "xy"])
def test_resolver_sleep_full_colour_capable_emits_red(mode_name):
    r = _resolver()
    out = r.night_light_turn_on_params(
        _nl_sleep_cfg("red"), "sleep", supported_color_modes=[mode_name],
    )
    assert out.get("rgb_color") == list(r.NIGHT_LIGHT_SLEEP_RED_RGB)
    assert "color_temp_kelvin" not in out
    assert "brightness_pct" in out


def test_resolver_sleep_full_white_only_emits_kelvin():
    r = _resolver()
    out = r.night_light_turn_on_params(
        _nl_sleep_cfg("red"), "sleep", supported_color_modes=["color_temp"],
    )
    assert "rgb_color" not in out
    assert "color_temp_kelvin" in out


def test_resolver_sleep_hue_warm_white_keeps_kelvin_even_colour_capable():
    r = _resolver()
    out = r.night_light_turn_on_params(
        _nl_sleep_cfg("warm_white"), "sleep", supported_color_modes=["rgb"],
    )
    assert "rgb_color" not in out
    assert "color_temp_kelvin" in out


def test_resolver_day_mode_never_red_even_colour_capable():
    r = _resolver()
    out = r.night_light_turn_on_params(
        _nl_sleep_cfg("red"), "day", supported_color_modes=["rgb"],
    )
    assert "rgb_color" not in out
    assert "color_temp_kelvin" in out


def test_resolver_modes_none_preserves_kelvin():
    """Callers that cannot supply modes (unit tests, legacy equivalence
    tests) get the pre-parity behaviour — kelvin, never red."""
    r = _resolver()
    out = r.night_light_turn_on_params(
        _nl_sleep_cfg("red"), "sleep", supported_color_modes=None,
    )
    assert "rgb_color" not in out
    assert "color_temp_kelvin" in out


# ---------------------------------------------------------------------------
# Canonical vs reconciler parity — the card's actual bug.
# ---------------------------------------------------------------------------


def _canonical_last_light_turn_on(room):
    _run(room.auto._turn_on_night_lights(mode="sleep"))
    calls = _light_calls(room.hass, "turn_on")
    light_calls = [c for c in calls if c.domain == "light"]
    assert light_calls, "canonical emitted no light.turn_on at sleep"
    data = dict(light_calls[-1].data)
    data.pop("entity_id", None)
    return data


def _reconciler_sleep_params(room):
    const = _c()
    out = room.rec._resolve_light(
        "light.night", {const.STATE_OCCUPIED: True},
    )
    assert out is not None and out.state == "on"
    assert out.reason == "sleep_night_light"
    return out.params


def test_parity_full_colour_capable_hs_bulb_at_sleep_both_emit_red():
    """A colour bulb reconnecting while occupied at sleep must be
    restored RED by the reconciler, matching canonical. Reconciler is
    read FIRST because the canonical path's service-call stub clobbers
    the stub state attributes with a fresh ``SimpleNamespace``."""
    room = _mk_full()
    _set_modes(room, "light.night", ["hs"])
    recon = _reconciler_sleep_params(room)
    _set_modes(room, "light.night", ["hs"])  # re-arm after reconciler read
    canon = _canonical_last_light_turn_on(room)
    # Both carry rgb_color red + brightness_pct; neither carries kelvin.
    assert "rgb_color" in canon and "rgb_color" in recon
    assert canon["rgb_color"] == recon["rgb_color"]
    assert "color_temp_kelvin" not in canon
    assert "color_temp_kelvin" not in recon
    # transition lives only on canonical (service-call payload); strip
    # it for the structural equality.
    canon_no_tr = {k: v for k, v in canon.items() if k != "transition"}
    assert canon_no_tr == recon


def test_parity_full_colour_capable_xy_bulb_at_sleep_both_emit_red():
    room = _mk_full()
    _set_modes(room, "light.night", ["xy"])
    recon = _reconciler_sleep_params(room)
    _set_modes(room, "light.night", ["xy"])
    canon = _canonical_last_light_turn_on(room)
    assert "rgb_color" in canon and "rgb_color" in recon
    assert canon["rgb_color"] == recon["rgb_color"]


def test_parity_full_white_only_bulb_at_sleep_both_emit_kelvin():
    """A white-only (color_temp) bulb must keep kelvin on BOTH paths —
    kelvin cannot make red, so no override."""
    room = _mk_full()
    _set_modes(room, "light.night", ["color_temp"])
    recon = _reconciler_sleep_params(room)
    _set_modes(room, "light.night", ["color_temp"])
    canon = _canonical_last_light_turn_on(room)
    assert "rgb_color" not in canon
    assert "rgb_color" not in recon
    assert "color_temp_kelvin" in canon
    assert "color_temp_kelvin" in recon
    assert canon["color_temp_kelvin"] == recon["color_temp_kelvin"]


def test_parity_warm_white_hue_both_emit_kelvin_even_colour_capable():
    const = _c()
    room = _mk_full(**{
        const.CONF_NIGHT_LIGHT_SLEEP_HUE: const.NIGHT_LIGHT_SLEEP_HUE_WARM_WHITE,
    })
    _set_modes(room, "light.night", ["rgb"])
    recon = _reconciler_sleep_params(room)
    _set_modes(room, "light.night", ["rgb"])
    canon = _canonical_last_light_turn_on(room)
    assert "rgb_color" not in canon
    assert "rgb_color" not in recon
    assert "color_temp_kelvin" in canon
    assert "color_temp_kelvin" in recon


# ---------------------------------------------------------------------------
# Behavioural wire-in — the reconciler's enclosing method actually calls
# the resolver with supported_color_modes (not just the helper directly).
# ---------------------------------------------------------------------------


def test_reconciler_house_sleep_rule_branch_full_hs_bulb_goes_red():
    """Reconciler nl-rule branch (actuator_reconciler.py :912-914).

    Trigger: per-room sleep gate OFF, ``_house_state_is_sleep`` TRUE,
    night light reachable (dark OR by-day), FULL colour-capable hs bulb.
    This is the house-sleep narrow helper (v5.103.42) — distinct from
    the :820 per-room sleep branch and the only path that fires when
    the operator did NOT configure per-room sleep but the house is in
    SLEEP state. Must emit red + no kelvin, same as canonical.
    """
    const = _c()
    cfg = {
        const.CONF_LIGHTS: ["light.main"],
        const.CONF_NIGHT_LIGHTS: ["light.night"],
        const.CONF_LIGHT_CAPABILITIES: const.LIGHT_CAPABILITY_FULL,
        const.CONF_ENTRY_LIGHT_ACTION: const.LIGHT_ACTION_NONE,
        const.CONF_NIGHT_LIGHTS_BY_DAY: True,
    }
    # Per-room sleep gate OFF; flip ``_house_state_is_sleep`` ON so the
    # reconciler re-maps _mode to "sleep" at :891.
    room = make_room(config=cfg, occupied=True, sleep=False)
    assert room.auto.is_sleep_mode_active() is False
    room.auto._house_state_is_sleep = lambda: True
    room.auto.is_sleep_lighting_active = lambda: False
    room.auto.is_dark = lambda _lux=None: True  # ensure nl_should_on
    _set_modes(room, "light.night", ["hs"])
    out = room.rec._resolve_light(
        "light.night", {const.STATE_OCCUPIED: True},
    )
    assert out is not None and out.state == "on"
    assert out.reason == "entry_night_light"  # the :912 branch's reason
    assert "rgb_color" in out.params
    assert "color_temp_kelvin" not in out.params
    assert "brightness_pct" in out.params


# ---------------------------------------------------------------------------
# Canonical mixed-room batching — every night-light entity reaches exactly
# one turn_on call, with the right payload for its capability.
# ---------------------------------------------------------------------------


def test_canonical_mixed_room_sleep_batching_covers_every_entity():
    """Four night lights in one room at sleep:
      - two hs bulbs       → red group (rgb_color, no kelvin)
      - one color_temp bulb → kelvin group (color_temp_kelvin, no rgb)
      - one switch         → switch.turn_on (no light params)

    Every entity must appear in EXACTLY ONE turn_on call. Light calls
    carry transition + brightness_pct; the switch call carries neither.
    """
    const = _c()
    cfg = {
        const.CONF_LIGHTS: ["light.main"],
        const.CONF_NIGHT_LIGHTS: [
            "light.hs1", "light.hs2", "light.white", "switch.night_sw",
        ],
        const.CONF_LIGHT_CAPABILITIES: const.LIGHT_CAPABILITY_FULL,
        const.CONF_ENTRY_LIGHT_ACTION: const.LIGHT_ACTION_NONE,
    }
    room = make_room(config=cfg, occupied=True, sleep=True)
    _set_modes(room, "light.hs1", ["hs"])
    _set_modes(room, "light.hs2", ["hs"])
    _set_modes(room, "light.white", ["color_temp"])
    # switch.night_sw: no state needed — the canonical loop short-circuits
    # on domain prefix anyway.

    _run(room.auto._turn_on_night_lights(mode="sleep"))

    light_calls = [
        c for c in _light_calls(room.hass, "turn_on") if c.domain == "light"
    ]
    switch_calls = [
        c for c in _light_calls(room.hass, "turn_on") if c.domain == "switch"
    ]

    # Union of entities across all light.turn_on calls == full light set
    # and each entity appears exactly once.
    all_light_eids: list[str] = []
    for c in light_calls:
        eids = c.data.get("entity_id")
        all_light_eids.extend([eids] if isinstance(eids, str) else list(eids))
    assert sorted(all_light_eids) == ["light.hs1", "light.hs2", "light.white"]
    assert len(all_light_eids) == len(set(all_light_eids)), (
        f"an entity landed in more than one turn_on call: {all_light_eids}"
    )

    # Switch gets its own call, no light params.
    switch_eids: list[str] = []
    for c in switch_calls:
        eids = c.data.get("entity_id")
        switch_eids.extend([eids] if isinstance(eids, str) else list(eids))
    assert "switch.night_sw" in switch_eids
    for c in switch_calls:
        assert "brightness_pct" not in c.data
        assert "color_temp_kelvin" not in c.data
        assert "rgb_color" not in c.data
        assert "transition" not in c.data

    # Every light call carries brightness_pct + transition.
    for c in light_calls:
        assert "brightness_pct" in c.data, f"missing brightness_pct in {c.data}"
        assert "transition" in c.data, f"missing transition in {c.data}"

    # Partition by payload: red group vs white group.
    red_calls = [c for c in light_calls if "rgb_color" in c.data]
    white_calls = [c for c in light_calls if "color_temp_kelvin" in c.data]
    assert red_calls and white_calls, (
        f"expected both red and kelvin groups, got "
        f"red={[c.data for c in red_calls]} white={[c.data for c in white_calls]}"
    )
    for c in red_calls:
        assert "color_temp_kelvin" not in c.data  # red group has NO kelvin
        eids = c.data.get("entity_id")
        eids = [eids] if isinstance(eids, str) else list(eids)
        assert set(eids) == {"light.hs1", "light.hs2"}
    for c in white_calls:
        assert "rgb_color" not in c.data            # white group has NO rgb
        eids = c.data.get("entity_id")
        eids = [eids] if isinstance(eids, str) else list(eids)
        assert set(eids) == {"light.white"}


def test_wire_in_reconciler_resolve_light_reads_live_modes():
    """Mutating the entity's live ``supported_color_modes`` flips the
    reconciler's output between red and kelvin for the same cfg — proves
    the enclosing method (``_resolve_light``) is the one reading hass
    state, not a stale cfg-only path."""
    room = _mk_full()

    # Colour-capable → red.
    _set_modes(room, "light.night", ["rgb"])
    red = _reconciler_sleep_params(room)
    assert "rgb_color" in red
    assert "color_temp_kelvin" not in red

    # Rewrite the state as white-only → kelvin.
    _set_modes(room, "light.night", ["color_temp"])
    kelvin = _reconciler_sleep_params(room)
    assert "rgb_color" not in kelvin
    assert "color_temp_kelvin" in kelvin
