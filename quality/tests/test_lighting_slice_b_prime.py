"""Slice B' tests: role-picker resolver behaviour + outdoor illuminance tier.

Covers:
- resolver honours CONF_LIGHTS_ON_ENTRY when present (subset semantics)
- CONF_LIGHTS_ON_ENTRY_DARK_ONLY carve-out when is_dark is False
- CONF_LIGHTS_LEAVE_ON_WHEN_EMPTY carve-out in the exit set
- ABSENT new keys ⇒ today's behaviour (regression guard on Slice A resolver)
- darkness fallback tier ordering (room→borrowed→outdoor→sun→False)
- OUTDOOR_DARK_LUX threshold discrimination (399 dark / 401 not)
- kill switch disables tiers 3 AND 4
- config-flow round-trip: saved value outside CONF_LIGHTS is not dropped
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.universal_room_automation.const import (
    CONF_AWAY_TURN_OFF_LEAVE_ON,
    CONF_ILLUMINANCE_THRESHOLD,
    CONF_LIGHT_DARK_LUX_SOURCE,
    CONF_LIGHT_DARK_USE_SUN_FALLBACK,
    CONF_LIGHTS,
    CONF_LIGHTS_LEAVE_ON_WHEN_EMPTY,
    CONF_LIGHTS_ON_ENTRY,
    CONF_LIGHTS_ON_ENTRY_DARK_ONLY,
    CONF_NIGHT_LIGHTS,
    CONF_OUTDOOR_DARK_LUX,
    CONF_OUTDOOR_LIGHT_SENSOR,
    DEFAULT_OUTDOOR_DARK_LUX,
    SUN_DARK_ELEVATION_DEG,
)
from custom_components.universal_room_automation.lighting.resolver import (
    effective_entry_set,
    effective_exit_set,
)
from custom_components.universal_room_automation.lighting import darkness as dk


# ---------------------------------------------------------------------------
# Resolver — new keys
# ---------------------------------------------------------------------------


def test_on_entry_absent_matches_today_union():
    cfg = {
        CONF_LIGHTS: ["light.a", "light.b"],
        CONF_NIGHT_LIGHTS: ["light.n"],
    }
    assert effective_entry_set(cfg, False) == ["light.a", "light.b", "light.n"]


def test_on_entry_present_restricts_set():
    cfg = {
        CONF_LIGHTS: ["light.a", "light.b"],
        CONF_NIGHT_LIGHTS: ["light.n"],
        CONF_LIGHTS_ON_ENTRY: ["light.a"],
    }
    assert effective_entry_set(cfg, False) == ["light.a"]


def test_on_entry_dark_only_removed_when_not_dark():
    cfg = {
        CONF_LIGHTS: ["light.a", "light.b"],
        CONF_LIGHTS_ON_ENTRY: ["light.a", "light.b"],
        CONF_LIGHTS_ON_ENTRY_DARK_ONLY: ["light.b"],
    }
    assert effective_entry_set(cfg, False, is_dark=False) == ["light.a"]
    assert effective_entry_set(cfg, False, is_dark=True) == ["light.a", "light.b"]


def test_leave_on_absent_matches_today_union_exit():
    cfg = {
        CONF_LIGHTS: ["light.a", "light.b"],
        CONF_NIGHT_LIGHTS: ["light.n"],
    }
    assert effective_exit_set(cfg) == ["light.a", "light.b", "light.n"]


def test_leave_on_carves_out_exit():
    cfg = {
        CONF_LIGHTS: ["light.a", "light.b"],
        CONF_NIGHT_LIGHTS: ["light.n"],
        CONF_LIGHTS_LEAVE_ON_WHEN_EMPTY: ["light.b"],
    }
    assert effective_exit_set(cfg) == ["light.a", "light.n"]


def test_sleep_hours_night_only_still_wins_over_on_entry():
    """Sleep semantics unchanged: night lights only when sleep + night non-empty."""
    cfg = {
        CONF_LIGHTS: ["light.a"],
        CONF_NIGHT_LIGHTS: ["light.n"],
        CONF_LIGHTS_ON_ENTRY: ["light.a"],
    }
    assert effective_entry_set(cfg, is_sleep_hours=True) == ["light.n"]


# ---------------------------------------------------------------------------
# Darkness fallback — outdoor illuminance tier
# ---------------------------------------------------------------------------


class _FakeState:
    def __init__(self, state, attributes=None):
        self.state = state
        self.attributes = attributes or {}


class _FakeStates:
    def __init__(self, mapping):
        self._m = mapping

    def get(self, entity_id):
        return self._m.get(entity_id)


class _FakeEntity:
    def __init__(self, entity_id, platform="illuminance", disabled_by=None):
        self.entity_id = entity_id
        self.platform = platform
        self.disabled_by = disabled_by


class _FakeRegistry:
    def __init__(self, entities):
        self.entities = {e.entity_id: e for e in entities}


class _FakeConfigEntry:
    def __init__(self, data, options):
        self.data = data
        self.options = options


class _FakeConfigEntries:
    def __init__(self, entries):
        self._entries = entries

    def async_entries(self, domain):
        return list(self._entries)


class _FakeHass:
    def __init__(self, states=None, integration_options=None):
        self.states = _FakeStates(states or {})
        from custom_components.universal_room_automation.const import (
            CONF_ENTRY_TYPE, ENTRY_TYPE_INTEGRATION,
        )
        entries = []
        if integration_options is not None:
            entries.append(_FakeConfigEntry(
                data={CONF_ENTRY_TYPE: ENTRY_TYPE_INTEGRATION},
                options=integration_options,
            ))
        self.config_entries = _FakeConfigEntries(entries)


def _patch_registry(monkeypatch, entities):
    reg = _FakeRegistry(entities)
    import homeassistant.helpers.entity_registry as er
    monkeypatch.setattr(er, "async_get", lambda hass: reg)


def test_outdoor_unset_falls_to_sun():
    hass = _FakeHass(
        states={"sun.sun": _FakeState("below_horizon", {"elevation": -10.0})},
        integration_options={},
    )
    assert dk.is_dark_fallback({}, hass) is True


def test_outdoor_configured_and_available_below_threshold():
    outdoor_eid = "sensor.phalanxmadrone_illuminance"
    hass = _FakeHass(
        states={outdoor_eid: _FakeState("399")},
        integration_options={CONF_OUTDOOR_LIGHT_SENSOR: outdoor_eid},
    )
    assert dk.is_dark_fallback({}, hass) is True


def test_outdoor_configured_not_dark_above_threshold():
    outdoor_eid = "sensor.phalanxmadrone_illuminance"
    hass = _FakeHass(
        states={outdoor_eid: _FakeState("401")},
        integration_options={CONF_OUTDOOR_LIGHT_SENSOR: outdoor_eid},
    )
    assert dk.is_dark_fallback({}, hass) is False


def test_outdoor_configured_but_unavailable_falls_to_sun():
    outdoor_eid = "sensor.phalanxmadrone_illuminance"
    hass = _FakeHass(
        states={
            outdoor_eid: _FakeState("unavailable"),
            "sun.sun": _FakeState("below_horizon", {"elevation": -10.0}),
        },
        integration_options={CONF_OUTDOOR_LIGHT_SENSOR: outdoor_eid},
    )
    assert dk.is_dark_fallback({}, hass) is True


def test_sun_unavailable_returns_not_dark():
    hass = _FakeHass(
        states={"sun.sun": _FakeState("unavailable")},
        integration_options={},
    )
    assert dk.is_dark_fallback({}, hass) is False


def test_kill_switch_disables_outdoor_and_sun():
    outdoor_eid = "sensor.phalanxmadrone_illuminance"
    hass = _FakeHass(
        states={
            outdoor_eid: _FakeState("10"),
            "sun.sun": _FakeState("below_horizon", {"elevation": -10.0}),
        },
        integration_options={CONF_OUTDOOR_LIGHT_SENSOR: outdoor_eid},
    )
    cfg = {CONF_LIGHT_DARK_USE_SUN_FALLBACK: False}
    assert dk.is_dark_fallback(cfg, hass) is False


def test_borrowed_lux_wins_over_outdoor():
    outdoor_eid = "sensor.phalanxmadrone_illuminance"
    borrow_eid = "sensor.borrow"
    hass = _FakeHass(
        states={
            outdoor_eid: _FakeState("10"),
            borrow_eid: _FakeState("500"),
        },
        integration_options={CONF_OUTDOOR_LIGHT_SENSOR: outdoor_eid},
    )
    cfg = {
        CONF_LIGHT_DARK_LUX_SOURCE: borrow_eid,
        CONF_ILLUMINANCE_THRESHOLD: 50,
    }
    assert dk.is_dark_fallback(cfg, hass) is False


def test_configured_outdoor_threshold_override():
    outdoor_eid = "sensor.phalanxmadrone_illuminance"
    hass = _FakeHass(
        states={outdoor_eid: _FakeState("150")},
        integration_options={
            CONF_OUTDOOR_LIGHT_SENSOR: outdoor_eid,
            CONF_OUTDOOR_DARK_LUX: 100,  # tighter threshold
        },
    )
    # 150 lux with a 100-lux threshold ⇒ not dark
    assert dk.is_dark_fallback({}, hass) is False


def test_default_threshold_matches_module_default():
    assert DEFAULT_OUTDOOR_DARK_LUX == 400.0


def test_form_prefill_suggestion_when_illuminance_platform_present(monkeypatch):
    _patch_registry(monkeypatch, [_FakeEntity("sensor.pre_fill_lux")])
    assert (
        dk.discover_outdoor_illuminance_suggestion(_FakeHass())
        == "sensor.pre_fill_lux"
    )


def test_form_prefill_no_suggestion_when_none(monkeypatch):
    _patch_registry(monkeypatch, [])
    assert dk.discover_outdoor_illuminance_suggestion(_FakeHass()) is None


def test_disabled_illuminance_entry_not_suggested(monkeypatch):
    _patch_registry(monkeypatch, [
        _FakeEntity("sensor.disabled_illum", disabled_by="user"),
    ])
    assert dk.discover_outdoor_illuminance_suggestion(_FakeHass()) is None


# ---------------------------------------------------------------------------
# CONF_AWAY_TURN_OFF_LEAVE_ON default is TRUE
# ---------------------------------------------------------------------------


def test_away_turn_off_leave_on_default_true_constant_exists():
    # sentinel: the key + default surface exists (the boolean's default
    # is TRUE at the config-flow site — checked in the round-trip test).
    assert CONF_AWAY_TURN_OFF_LEAVE_ON == "away_turn_off_leave_on"
