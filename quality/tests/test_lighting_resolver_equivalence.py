"""Slice A resolver-equivalence tests (ROOM-LIGHTING-SETUP-REDESIGN-1).

Proves ``effective_entry_set`` / ``effective_exit_set`` match today's live
derivation at the four inline sites the plan enumerates. If a later slice
alters entry/exit semantics without extending this helper, these tests
fail — that is the invariant the D8 sweep depends on.
"""
from __future__ import annotations

import pytest

from custom_components.universal_room_automation.const import (
    CONF_LIGHTS,
    CONF_NIGHT_LIGHTS,
)
from custom_components.universal_room_automation.lighting.resolver import (
    effective_entry_set,
    effective_exit_set,
)


# ---------------------------------------------------------------------------
# Independent oracles — hand-rewritten from today's inline code paths.
# These MUST NOT be replaced with a call to the module under test.
# ---------------------------------------------------------------------------


def _oracle_entry(cfg: dict, is_sleep_hours: bool) -> list[str]:
    """Mirror of automation.py:_control_lights_entry lines 1017-1055."""
    lights = list(cfg.get(CONF_LIGHTS, []) or [])
    night = list(cfg.get(CONF_NIGHT_LIGHTS, []) or [])
    if is_sleep_hours and night:
        # sleep mode: night lights only
        return list(dict.fromkeys(night))
    # day (or sleep with no night lights): union, regular first
    return list(dict.fromkeys(lights + night))


def _oracle_exit(cfg: dict) -> list[str]:
    """Mirror of automation.py:_control_lights_exit lines 1079-1082
    and actuator_reconciler.py:109 _LIGHT_KEYS union.
    """
    lights = list(cfg.get(CONF_LIGHTS, []) or [])
    night = list(cfg.get(CONF_NIGHT_LIGHTS, []) or [])
    off_set = list(lights) + [e for e in night if e not in lights]
    return off_set


# ---------------------------------------------------------------------------
# Fixtures — representative of URA rooms as of v5.103.27.
# ---------------------------------------------------------------------------

FIXTURES = [
    # (label, cfg)
    ("empty", {}),
    ("lights_only", {CONF_LIGHTS: ["light.a", "light.b"]}),
    ("night_only", {CONF_NIGHT_LIGHTS: ["light.night"]}),
    (
        "disjoint_lights_and_night",
        {
            CONF_LIGHTS: ["light.a", "light.b"],
            CONF_NIGHT_LIGHTS: ["light.night"],
        },
    ),
    (
        "overlapping_night_in_lights",
        {
            CONF_LIGHTS: ["light.a", "light.n"],
            CONF_NIGHT_LIGHTS: ["light.n"],
        },
    ),
    (
        "night_outside_lights",
        {
            CONF_LIGHTS: ["light.main"],
            CONF_NIGHT_LIGHTS: ["light.hallway"],
        },
    ),
    (
        "switch_as_light",
        {
            CONF_LIGHTS: ["switch.relay_a", "light.b"],
            CONF_NIGHT_LIGHTS: [],
        },
    ),
    (
        "none_values",
        {
            CONF_LIGHTS: None,
            CONF_NIGHT_LIGHTS: None,
        },
    ),
]


@pytest.mark.parametrize("label,cfg", FIXTURES)
@pytest.mark.parametrize("is_sleep", [False, True])
def test_effective_entry_set_matches_oracle(label, cfg, is_sleep):
    assert effective_entry_set(cfg, is_sleep) == _oracle_entry(cfg, is_sleep)


@pytest.mark.parametrize("label,cfg", FIXTURES)
def test_effective_exit_set_matches_oracle(label, cfg):
    assert effective_exit_set(cfg) == _oracle_exit(cfg)


# ---------------------------------------------------------------------------
# Discriminator: sleep-with-no-night-lights falls through to the day union.
# This is the exact seam automation.py:1023 gates on (`if is_sleep_hours
# and night_lights`) — a regression that flipped it to "night only when
# sleep, regardless of list" would fail here.
# ---------------------------------------------------------------------------

def test_sleep_without_night_lights_uses_full_union():
    cfg = {CONF_LIGHTS: ["light.a"], CONF_NIGHT_LIGHTS: []}
    assert effective_entry_set(cfg, is_sleep_hours=True) == ["light.a"]


def test_sleep_with_night_lights_narrows_to_night_only():
    cfg = {CONF_LIGHTS: ["light.a"], CONF_NIGHT_LIGHTS: ["light.n"]}
    assert effective_entry_set(cfg, is_sleep_hours=True) == ["light.n"]
    # day fallthrough is the union
    assert effective_entry_set(cfg, is_sleep_hours=False) == ["light.a", "light.n"]


def test_exit_union_ignores_sleep():
    """The vacancy/exit union has no sleep gate (operator ruling)."""
    cfg = {CONF_LIGHTS: ["light.a"], CONF_NIGHT_LIGHTS: ["light.n"]}
    # Only one exit derivation regardless of clock state.
    assert effective_exit_set(cfg) == ["light.a", "light.n"]


def test_order_preservation_and_dedup():
    cfg = {
        CONF_LIGHTS: ["light.a", "light.b", "light.a"],
        CONF_NIGHT_LIGHTS: ["light.b", "light.c"],
    }
    # dedup preserves first occurrence
    assert effective_entry_set(cfg, is_sleep_hours=False) == [
        "light.a",
        "light.b",
        "light.c",
    ]
    assert effective_exit_set(cfg) == ["light.a", "light.b", "light.c"]
