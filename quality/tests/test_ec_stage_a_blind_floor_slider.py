"""EC storm/blind Stage A D-A5 — `InclementBlindFullHoldFloorNumber`.

PLANNING_ec_storm_and_blind_decisions.md Rev 3.1 options-read path:
  1. the key is in `_NO_LIVE_ATTR_KEYS` (snapshot advances, no live push);
  2. the key is in `OPTIONS_RELOAD_SUPPRESS_KEYS` (a slider move is NOT a CM
     reload);
  3. `BatteryStrategy._inclement_config()` reads it from the CM
     `entry.options` every tick (default 60, clamped 0-100);
  4. `InclementFusion._full_hold_floor(None)` uses it:
     max(reserve_soc, partial_floor, slider).
The Number writes ONLY `entry.options` (no coordinator setter).

Every decision test drives the value through a REAL CM config entry's
`options` (never `_inclement_config_override`). Listener tests drive the
REAL `_async_update_listener` / `_apply_in_place` AST-sliced from
`__init__.py` (the `test_cm_reload_suppression` loader), not a source grep.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from _reserve_governor_harness import (  # noqa: F401 — `clock` is a fixture
    _CDT,
    clock,
    make_shell,
)
from custom_components.universal_room_automation.domain_coordinators.energy_const import (
    CONF_INCLEMENT_BLIND_FULL_HOLD_FLOOR,
    CONF_INCLEMENT_NWS_ALERTS_ENTITY,
    CONF_INCLEMENT_PARTIAL_HOLD_RESERVE_FLOOR,
    INCLEMENT_BLIND_FULL_HOLD_FLOOR_PCT,
)

_UTC = timezone.utc
OCT_03 = datetime(2026, 10, 15, 8, 0, tzinfo=_UTC)
_NWS = "sensor.stage_a_slider_nws"
_DOMAIN = "universal_room_automation"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _cm_entry(options: dict):
    return SimpleNamespace(
        entry_id="cm1", title="CM",
        data={"entry_type": "coordinator_manager"},
        options=dict(options),
    )


def _blind_warn_shell(clock, options: dict, *, reserve_soc=10):
    """Fully blind strategy with a real Winter Storm Warning and a REAL CM
    entry carrying `options` (the production `_inclement_config` path)."""
    clock.t = OCT_03
    c, s = make_shell(clock, soc="unavailable")
    s._soc_lkg = None
    s._soc_lkg_at = None
    s.reserve_soc = reserve_soc
    del s._inclement_config_override        # production CM-entry lookup
    c.hass.set_state(_NWS, "1", attributes={"Alerts": [{
        "Event": "Winter Storm Warning", "Severity": "Severe",
        "Certainty": "Likely", "Status": "Actual",
        "Onset": "2026-10-14T00:00:00-05:00",
        "Ends": "2026-10-20T00:00:00-05:00",
    }]})
    entry = _cm_entry({CONF_INCLEMENT_NWS_ALERTS_ENTITY: _NWS, **options})
    c.hass.config_entries.async_entries = lambda domain=None: [entry]
    return c, s, entry


def _blind_floor(clock, s) -> int:
    d = s.determine_mode("off_peak", "shoulder", now=clock.t.astimezone(_CDT))
    assert d["envoy_available"] is False
    assert s._last_inclement_decision.hold_depth == "full_hold"
    return s._tick_reserve_floor


# ===========================================================================
# 3 + 4 — decision path reads the live slider from entry.options
# ===========================================================================
def test_blind_full_hold_floor_reads_live_slider(clock):
    c, s, entry = _blind_warn_shell(
        clock, {CONF_INCLEMENT_BLIND_FULL_HOLD_FLOOR: 75})
    assert _blind_floor(clock, s) == 75
    # A slider move applies on the NEXT tick (no reload, no cache).
    entry.options[CONF_INCLEMENT_BLIND_FULL_HOLD_FLOOR] = 85
    clock.t = datetime(2026, 10, 15, 9, 0, tzinfo=_UTC)
    assert _blind_floor(clock, s) == 85


def test_blind_full_hold_floor_default_when_unset(clock):
    c, s, _ = _blind_warn_shell(clock, {})
    assert _blind_floor(clock, s) == INCLEMENT_BLIND_FULL_HOLD_FLOOR_PCT == 60


def test_blind_floor_first_tick_after_restart_uses_persisted_value(clock):
    """A FRESH strategy (restart) reads the persisted option on its first
    tick: partial 20, reserve 10, slider 40 → 40 (no seeding race)."""
    c, s, _ = _blind_warn_shell(clock, {
        CONF_INCLEMENT_BLIND_FULL_HOLD_FLOOR: 40,
        CONF_INCLEMENT_PARTIAL_HOLD_RESERVE_FLOOR: 20,
    })
    assert s._last_inclement_decision is None
    assert _blind_floor(clock, s) == 40


@pytest.mark.parametrize("slider,expected", [
    (0, 50),      # kill: collapses to max(reserve_soc 10, partial 50)
    (100, 100),   # legacy pin
    (150, 100),   # hand-edited out of range → clamped
    ("junk", 60), # malformed → default
])
def test_blind_floor_slider_extremes_0_100(clock, slider, expected):
    c, s, _ = _blind_warn_shell(
        clock, {CONF_INCLEMENT_BLIND_FULL_HOLD_FLOOR: slider})
    assert _blind_floor(clock, s) == expected


def test_blind_floor_inversion_via_options(clock):
    """reserve_soc 20, partial 80, slider 60 → 80."""
    c, s, _ = _blind_warn_shell(clock, {
        CONF_INCLEMENT_BLIND_FULL_HOLD_FLOOR: 60,
        CONF_INCLEMENT_PARTIAL_HOLD_RESERVE_FLOOR: 80,
    }, reserve_soc=20)
    assert _blind_floor(clock, s) == 80


def test_sighted_full_hold_ignores_slider(clock):
    """The slider only applies when SOC is unknown (sighted keeps int(soc))."""
    c, s, _ = _blind_warn_shell(
        clock, {CONF_INCLEMENT_BLIND_FULL_HOLD_FLOOR: 90})
    from _reserve_governor_harness import _SOC, _st
    _st(c.hass, _SOC, "35", unit="%", lu=clock.t)
    d = s.determine_mode("off_peak", "shoulder", now=clock.t.astimezone(_CDT))
    assert d["envoy_available"] is True
    assert s._tick_reserve_floor == 35


# ===========================================================================
# Entity: seed + options-only writeback
# ===========================================================================
def _number_mod():
    from custom_components.universal_room_automation import number as number_mod
    return number_mod


def _hass_with_energy():
    energy = MagicMock()
    hass = SimpleNamespace(
        data={_DOMAIN: {"coordinator_manager": SimpleNamespace(
            coordinators={"energy": energy})}},
        config_entries=SimpleNamespace(),
    )

    def _update(entry, options=None, **kw):
        if options is not None:
            entry.options = dict(options)
    hass.config_entries.async_update_entry = MagicMock(side_effect=_update)
    return hass, energy


@pytest.mark.parametrize("opts,expected", [
    ({CONF_INCLEMENT_BLIND_FULL_HOLD_FLOOR: 75}, 75),
    ({}, 60),
    ({CONF_INCLEMENT_BLIND_FULL_HOLD_FLOOR: "junk"}, 60),
    ({CONF_INCLEMENT_BLIND_FULL_HOLD_FLOOR: 140}, 100),
])
def test_blind_floor_number_seeds_from_options(opts, expected):
    nm = _number_mod()
    hass, _ = _hass_with_energy()
    n = nm.InclementBlindFullHoldFloorNumber(hass, _cm_entry(opts))
    assert n.native_value == expected
    assert (n.native_min_value, n.native_max_value, n.native_step) == (0, 100, 5)
    assert n.native_unit_of_measurement == "%"
    assert n.unique_id == f"{_DOMAIN}_energy_inclement_blind_full_hold_floor"
    assert n.name == "Inclement Blind Full Hold Floor"


def test_blind_floor_number_writes_options_only():
    nm = _number_mod()
    hass, energy = _hass_with_energy()
    entry = _cm_entry({"other_key": 1})
    n = nm.InclementBlindFullHoldFloorNumber(hass, entry)
    n.async_write_ha_state = lambda: None
    asyncio.new_event_loop().run_until_complete(n.async_set_native_value(75))
    assert entry.options == {"other_key": 1, CONF_INCLEMENT_BLIND_FULL_HOLD_FLOOR: 75}
    assert n.native_value == 75
    assert hass.config_entries.async_update_entry.call_count == 1
    assert energy.method_calls == []     # no coordinator setter of any kind
    assert n.available is True


# ===========================================================================
# 1 + 2 — options listener: no CM reload, snapshot advances
# ===========================================================================
@pytest.fixture(scope="module")
def listener():
    import test_cm_reload_suppression as t
    return t, t._load_init_listener_helpers()


def _drive(listener, old_val, new_val):
    t, ns = listener
    hass = t._FakeHass(hvac=t._FakeHvac())
    entry = t._FakeEntry("cm1", {CONF_INCLEMENT_BLIND_FULL_HOLD_FLOOR: old_val})
    ns["_seed_cm_last_applied_options"](hass, entry)
    entry.options = {CONF_INCLEMENT_BLIND_FULL_HOLD_FLOOR: new_val}
    asyncio.new_event_loop().run_until_complete(
        ns["_async_update_listener"](hass, entry)
    )
    snap = hass.data[_DOMAIN]["cm_last_applied_options"]["cm1"]
    return hass, snap


def test_blind_floor_key_in_options_reload_suppress_keys(listener):
    """A slider move is an in-place apply: no reload task is scheduled."""
    hass, _ = _drive(listener, 60, 75)
    assert hass.async_create_task.call_count == 0
    assert hass.config_entries.async_reload.call_count == 0


def test_blind_floor_key_in_no_live_attr_keys(listener):
    """`_apply_in_place` marks the key applied (`_NO_LIVE_ATTR_KEYS`), so the
    snapshot advances to the new value (an unapplied key keeps the old one
    and is re-diffed forever)."""
    _, snap = _drive(listener, 60, 75)
    assert snap[CONF_INCLEMENT_BLIND_FULL_HOLD_FLOOR] == 75
