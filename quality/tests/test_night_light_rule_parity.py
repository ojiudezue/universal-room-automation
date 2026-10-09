"""NIGHT-LIGHT-ACTION-SELECTOR-1 (REV 3) — canonical + reconciler parity.

Drives the REAL ``RoomAutomation._control_lights_entry`` AND the REAL
``ActuatorReconciler._resolve_light`` through the parity truth-table rows
from the plan's invariant.

Harness REUSED from ``test_lighting_slice_c_manual_hold.make_room``
(see ``test_lighting_untested_sites.py`` for the same reuse pattern).

Independently authored oracle: an explicit expected outcome per row,
not re-derived from the module under test.
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
def _bootstrap_modules(_real_modules):  # noqa: F811 — chain the sibling autouse
    """Chain the sibling test module's real-module importer so ``M`` is
    populated for every test here (its autouse scope cleans ``M`` on
    module exit, so this file needs its own invocation)."""
    yield


def _c():
    return M["const"]


def _mk(**cfg_extra):
    """Build a room with night lights configured, non-sleep by default."""
    const = _c()
    base = {
        const.CONF_LIGHTS: ["light.main"],
        const.CONF_NIGHT_LIGHTS: ["light.night"],
        const.CONF_LIGHT_CAPABILITIES: const.LIGHT_CAPABILITY_FULL,
        const.CONF_ENTRY_LIGHT_ACTION: const.LIGHT_ACTION_NONE,
    }
    base.update(cfg_extra)
    room = make_room(config=base, occupied=True, sleep=False)
    return room


def _turn_on_entity_ids(room, service="turn_on"):
    out: list[str] = []
    for c in _light_calls(room.hass, service):
        e = c.data.get("entity_id")
        if isinstance(e, str):
            out.append(e)
        else:
            out.extend(e or [])
    return out


def _set_dark(room, is_dark):
    room.auto.is_dark = lambda _lux=None: bool(is_dark)


def _set_sleep(room, sleep):
    room.auto.is_sleep_mode_active = lambda: bool(sleep)


# ---------------------------------------------------------------------------
# Canonical rows (R3 invariant discriminators)
# ---------------------------------------------------------------------------


def test_sleep_main_none_night_light_only_room():
    """sleep=T, main=NONE, night_lights=[L], lights=[] → night light ON.

    Master Bedroom today (R3 H1/H3). Canonical must NOT short-circuit on
    the empty CONF_LIGHTS list; it must reach the sleep night-light
    branch.
    """
    const = _c()
    room = _mk(**{const.CONF_LIGHTS: []})
    _set_sleep(room, True)
    _run(room.auto._control_lights_entry({}))
    assert "light.night" in _turn_on_entity_ids(room)


def test_sleep_main_turn_on_night_wins_sole_authority():
    """sleep=T, main=TURN_ON, night_lights=[L] → sleep is SOLE authority.
    Night light ON; main light NOT turned on by this function."""
    const = _c()
    room = _mk(**{const.CONF_ENTRY_LIGHT_ACTION: const.LIGHT_ACTION_TURN_ON})
    _set_sleep(room, True)
    _run(room.auto._control_lights_entry({}))
    ids = _turn_on_entity_ids(room)
    assert "light.night" in ids
    assert "light.main" not in ids, "sleep branch must not fire main lights"


def test_nonsleep_dark_main_none_night_light_on():
    """sleep=F, is_dark=T, main=NONE → night light ON (new sub-branch)."""
    room = _mk()
    _set_dark(room, True)
    _run(room.auto._control_lights_entry({}))
    assert "light.night" in _turn_on_entity_ids(room)


def test_nonsleep_bright_byday_false_no_turn_on():
    """sleep=F, is_dark=F, nl_by_day=F → NO night-light turn-on."""
    room = _mk()
    _set_dark(room, False)
    _run(room.auto._control_lights_entry({}))
    assert "light.night" not in _turn_on_entity_ids(room)


def test_nonsleep_bright_byday_true_turns_on():
    """sleep=F, is_dark=F, nl_by_day=T → night light ON."""
    const = _c()
    room = _mk(**{const.CONF_NIGHT_LIGHTS_BY_DAY: True})
    _set_dark(room, False)
    _run(room.auto._control_lights_entry({}))
    assert "light.night" in _turn_on_entity_ids(room)


def test_r3_h1_main_turn_on_bright_byday_false_no_night_light():
    """The R3-H1 fold:
    sleep=F, is_dark=F, main=TURN_ON, nl_by_day=F
    → canonical turns on main lights but MUST NOT fire the night light.
    """
    const = _c()
    room = _mk(**{const.CONF_ENTRY_LIGHT_ACTION: const.LIGHT_ACTION_TURN_ON})
    _set_dark(room, False)
    _run(room.auto._control_lights_entry({}))
    ids = _turn_on_entity_ids(room)
    assert "light.main" in ids
    assert "light.night" not in ids, "R3-H1: no night-light leak by day"


def test_mixed_room_dark_main_and_night_both_on():
    """sleep=F, is_dark=T, main=TURN_ON → BOTH main and night fire."""
    const = _c()
    room = _mk(**{const.CONF_ENTRY_LIGHT_ACTION: const.LIGHT_ACTION_TURN_ON})
    _set_dark(room, True)
    _run(room.auto._control_lights_entry({}))
    ids = _turn_on_entity_ids(room)
    assert "light.main" in ids
    assert "light.night" in ids


# ---------------------------------------------------------------------------
# Reconciler rows — must AGREE with canonical on each cell.
# ---------------------------------------------------------------------------


def _resolve(room, entity_id, occupied=True):
    const = _c()
    data = {const.STATE_OCCUPIED: occupied}
    return room.rec._resolve_light(entity_id, data)


def test_reconciler_sleep_night_light_on():
    room = _mk()
    _set_sleep(room, True)
    out = _resolve(room, "light.night")
    assert out is not None and out.state == "on"


def test_reconciler_nonsleep_dark_night_light_on():
    room = _mk()
    _set_dark(room, True)
    out = _resolve(room, "light.night")
    assert out is not None and out.state == "on"


def test_reconciler_nonsleep_bright_byday_false_no_opinion():
    """R3-H1 PARITY: canonical no-turn-on ⇔ reconciler NO-OPINION."""
    room = _mk()
    _set_dark(room, False)
    out = _resolve(room, "light.night")
    assert out is None, "night light no-opinion by day when nl_by_day=False"


def test_reconciler_nonsleep_bright_byday_true_on():
    const = _c()
    room = _mk(**{const.CONF_NIGHT_LIGHTS_BY_DAY: True})
    _set_dark(room, False)
    out = _resolve(room, "light.night")
    assert out is not None and out.state == "on"


def test_reconciler_r3_m1_main_turn_on_bright_night_no_opinion():
    """R3-H1/M1 parity: with main=TURN_ON + is_dark=F + nl_by_day=F, the
    reconciler must return NO-OPINION for the night light (canonical
    does not fire it either)."""
    const = _c()
    room = _mk(**{const.CONF_ENTRY_LIGHT_ACTION: const.LIGHT_ACTION_TURN_ON})
    _set_dark(room, False)
    out = _resolve(room, "light.night")
    assert out is None


def test_reconciler_vacant_night_light_off_unchanged():
    """Vacancy branch unchanged — night light off when vacant."""
    room = _mk()
    _set_sleep(room, False)
    _set_dark(room, False)
    out = _resolve(room, "light.night", occupied=False)
    assert out is not None and out.state == "off"


# ---------------------------------------------------------------------------
# R3-M2 param-parity — identical brightness/color_temp from the shared helper.
# ---------------------------------------------------------------------------


def test_r3_m2_reconciler_params_match_canonical_helper_day():
    """Reconciler night-light params in day slot = output of the shared
    helper the canonical path also feeds its service calls from."""
    const = _c()
    room = _mk(**{const.CONF_NIGHT_LIGHTS_BY_DAY: True})
    _set_dark(room, False)
    out = _resolve(room, "light.night")
    assert out is not None and out.state == "on"
    from custom_components.universal_room_automation.lighting.resolver import (
        night_light_turn_on_params,
    )
    expected = night_light_turn_on_params(room.auto.config, "day")
    # The reconciler builds params through the SAME helper.
    assert out.params == expected


# ---------------------------------------------------------------------------
# v5.103.42 post-deploy — exit_action dimension + sleep mode selection.
# Living Room (02:37/02:50 CDT 2026-10-09) regression: night light turned
# on by the rule stayed on after vacancy because exit_light_action=leave_on
# gated the OFF path.
# ---------------------------------------------------------------------------


def _turn_off_entity_ids(room):
    return _turn_on_entity_ids(room, service="turn_off")


def test_canonical_exit_leave_on_still_turns_off_night_light():
    """main exit=leave_on + vacancy ⇒ night light STILL turned off."""
    const = _c()
    room = _mk(**{
        const.CONF_EXIT_LIGHT_ACTION: const.LIGHT_ACTION_LEAVE_ON,
    })
    _run(room.auto._control_lights_exit({}))
    assert "light.night" in _turn_off_entity_ids(room)
    # Main light is NOT turned off under leave_on.
    assert "light.main" not in _turn_off_entity_ids(room)


def test_canonical_exit_leave_on_respects_leave_on_list():
    """leave_on list carries night light ⇒ do NOT turn off."""
    const = _c()
    room = _mk(**{
        const.CONF_EXIT_LIGHT_ACTION: const.LIGHT_ACTION_LEAVE_ON,
        const.CONF_LIGHTS_LEAVE_ON_WHEN_EMPTY: ["light.night"],
    })
    _run(room.auto._control_lights_exit({}))
    assert "light.night" not in _turn_off_entity_ids(room)


def test_canonical_exit_turn_off_unchanged():
    """exit=turn_off path byte-identical: full union OFF (except leave_on)."""
    const = _c()
    room = _mk(**{
        const.CONF_EXIT_LIGHT_ACTION: const.LIGHT_ACTION_TURN_OFF,
    })
    _run(room.auto._control_lights_exit({}))
    ids = _turn_off_entity_ids(room)
    assert "light.night" in ids
    assert "light.main" in ids


def test_reconciler_vacant_leave_on_night_light_off():
    """Reconciler agrees with canonical: night light OFF on vacancy under
    exit=leave_on."""
    const = _c()
    room = _mk(**{
        const.CONF_EXIT_LIGHT_ACTION: const.LIGHT_ACTION_LEAVE_ON,
    })
    out = _resolve(room, "light.night", occupied=False)
    assert out is not None and out.state == "off"


def test_reconciler_vacant_leave_on_main_light_no_opinion():
    """Non-night-light member under exit=leave_on stays untouched."""
    const = _c()
    room = _mk(**{
        const.CONF_EXIT_LIGHT_ACTION: const.LIGHT_ACTION_LEAVE_ON,
    })
    out = _resolve(room, "light.main", occupied=False)
    assert out is None


def test_reconciler_vacant_leave_on_night_in_leave_on_list_no_opinion():
    const = _c()
    room = _mk(**{
        const.CONF_EXIT_LIGHT_ACTION: const.LIGHT_ACTION_LEAVE_ON,
        const.CONF_LIGHTS_LEAVE_ON_WHEN_EMPTY: ["light.night"],
    })
    out = _resolve(room, "light.night", occupied=False)
    assert out is None


def test_is_sleep_lighting_active_follows_house_state_without_sleep_protection():
    """v5.103.42 fix: house_state=sleep ⇒ sleep lighting True even when
    CONF_SLEEP_PROTECTION_ENABLED=False (Living Room 02:37 CDT regression)."""
    const = _c()
    room = _mk(**{
        const.CONF_SLEEP_PROTECTION_ENABLED: False,
    })
    # Force non-sleep clock, then stub house state.
    room.auto.is_sleep_mode_active = lambda: False
    room.auto._read_current_house_state = lambda: "sleep"
    assert room.auto.is_sleep_lighting_active() is True
    # And canonical takes the sleep branch — ``sleep`` mode, not ``evening``.
    _run(room.auto._control_lights_entry({}))
    assert "light.night" in _turn_on_entity_ids(room)


def test_is_sleep_lighting_active_home_night_not_sleep():
    """house_state=home_night is NOT sleep (discriminator)."""
    const = _c()
    room = _mk(**{const.CONF_SLEEP_PROTECTION_ENABLED: False})
    room.auto.is_sleep_mode_active = lambda: False
    room.auto._read_current_house_state = lambda: "home_night"
    assert room.auto.is_sleep_lighting_active() is False


def test_r3_m2_reconciler_params_match_canonical_helper_evening():
    const = _c()
    room = _mk(**{
        const.CONF_NIGHT_LIGHT_EVENING_BRIGHTNESS: 22,
        const.CONF_NIGHT_LIGHT_EVENING_COLOR: 2600,
    })
    _set_dark(room, True)
    out = _resolve(room, "light.night")
    assert out is not None and out.state == "on"
    from custom_components.universal_room_automation.lighting.resolver import (
        night_light_turn_on_params,
    )
    expected = night_light_turn_on_params(room.auto.config, "evening")
    assert out.params == expected
    assert out.params.get("brightness_pct") == 22
    assert out.params.get("color_temp_kelvin") == 2600
