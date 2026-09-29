"""HVAC Batch D — HVAC-WRITES-WHILE-THERMOSTAT-UNAVAILABLE-1.

2026-09-28 14:24-17:21 all three climate entities were unavailable through a
run of HA restarts; zone_1 took 37 `B1_heat_cool_enforcer` writes with
`values_before.hvac_mode = unavailable`, plus an S1 `away` write every tick.

Drives the REAL `HVACCoordinator._apply_house_state_presets` on the W1-B
smoke harness:
  * an unavailable / unknown thermostat gets NO enforcer and NO S1 write;
  * one `climate_write_held_unreadable` ledger row per outage EPISODE (not
    per tick); a new outage after recovery opens a new episode;
  * when the entity reads again, normal writes resume on the next tick.
"""
from __future__ import annotations

import os
import sys

import pytest

pytest.importorskip("homeassistant.helpers.storage")

_HERE = os.path.dirname(__file__)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import _w1b_harness as H  # noqa: E402


@pytest.fixture(autouse=True, scope="module")
def _scoped():
    baseline = H.snapshot_shims()
    try:
        yield
    finally:
        H.restore_shims(baseline)


@pytest.fixture
def mods():
    return H.load_real()


@pytest.fixture
def expected_lingering_timers():
    return True


ZONE = "zone_1"
ENT = "climate.test_zone_1"


def _mode_writes(hass, entity_id):
    return [
        c for c in hass.services.calls
        if c[0] == "climate" and c[1] == "set_hvac_mode"
        and c[2].get("entity_id") == entity_id
    ]


def _held_rows(hass, mods):
    led = hass.data[mods["const"].DOMAIN]["activity_logger"]
    return [
        r for r in led.actions("climate_write_held_unreadable")
        if r.get("zone") == ZONE
    ]


def _zone(mods, *, state, hvac_mode="cool", preset="manual"):
    """zone_1 needs BOTH writes on a readable tick: cached hvac_mode drifted
    off heat_cool (B1) and a manual preset S1 reclaims to `home`."""
    coord, hass = H.make_coord(mods)
    coord._house_state = "home_day"
    coord._zone_intelligence_enabled = False
    z = coord.zone_manager.zones[ZONE]
    z.hvac_mode = hvac_mode
    z.preset_mode = preset
    H.set_climate(hass, ENT, preset_mode=preset, hold_activity=preset, state=state)
    for other in ("zone_2", "zone_3"):
        coord.zone_manager.zones[other].preset_mode = "home"
    return coord, hass, z


async def _tick(coord, hass):
    await coord._apply_house_state_presets()
    await H.drain(hass)


@pytest.mark.parametrize("state", ["unavailable", "unknown"])
@pytest.mark.asyncio
async def test_unreadable_thermostat_gets_no_enforcer_and_no_s1_write(mods, state):
    coord, hass, z = _zone(mods, state=state)
    await _tick(coord, hass)
    assert _mode_writes(hass, ENT) == []
    assert H.preset_writes(hass, ENT) == []
    db_rows = hass.data[mods["const"].DOMAIN]["database"].rows
    assert [
        r for r in db_rows
        if r.get("action") == "climate_write" and r.get("zone") == ZONE
    ] == []


@pytest.mark.asyncio
async def test_positive_control_readable_zone_gets_both_writes(mods):
    """Same zone, readable: B1 enforces heat_cool and S1 reclaims to home —
    proves the unreadable test above is not vacuous."""
    coord, hass, z = _zone(mods, state="cool")
    await _tick(coord, hass)
    assert [c[2]["hvac_mode"] for c in _mode_writes(hass, ENT)] == ["heat_cool"]
    assert len(H.preset_writes(hass, ENT, "home")) >= 1


@pytest.mark.asyncio
async def test_one_ledger_row_per_outage_episode_and_writes_resume(mods):
    coord, hass, z = _zone(mods, state="unavailable")
    for _ in range(3):
        await _tick(coord, hass)
    assert _mode_writes(hass, ENT) == []
    assert H.preset_writes(hass, ENT) == []
    rows = _held_rows(hass, mods)
    assert len(rows) == 1, rows
    assert rows[0]["details"]["state"] == "unavailable"
    assert rows[0]["entity_id"] == ENT

    # Entity reads again -> the next tick writes as normal.
    H.set_climate(hass, ENT, preset_mode="manual", hold_activity="manual", state="cool")
    await _tick(coord, hass)
    assert [c[2]["hvac_mode"] for c in _mode_writes(hass, ENT)] == ["heat_cool"]
    assert len(H.preset_writes(hass, ENT, "home")) >= 1
    assert ZONE not in coord._climate_unreadable_episodes

    # A NEW outage opens a NEW episode (second row), still no writes.
    n_mode, n_preset = len(_mode_writes(hass, ENT)), len(H.preset_writes(hass, ENT))
    H.set_climate(hass, ENT, preset_mode="manual", hold_activity="manual", state="unknown")
    z.preset_mode = "manual"
    z.hvac_mode = "cool"
    await _tick(coord, hass)
    await _tick(coord, hass)
    assert len(_mode_writes(hass, ENT)) == n_mode
    assert len(H.preset_writes(hass, ENT)) == n_preset
    assert len(_held_rows(hass, mods)) == 2


@pytest.mark.asyncio
async def test_s1_held_when_only_s1_would_write(mods):
    """S1-only anchor: the zone is already heat_cool (B1 has nothing to do),
    so the ONLY write is S1's — and it is held while unreadable."""
    coord, hass, z = _zone(mods, state="unavailable", hvac_mode="heat_cool")
    await _tick(coord, hass)
    assert H.preset_writes(hass, ENT) == []
    assert len(_held_rows(hass, mods)) == 1


@pytest.mark.asyncio
async def test_enforcer_held_during_arriving(mods):
    """B1-only anchor: `arriving` returns right after the enforcer loop, so
    the ONLY possible write is B1's — and it is held while unreadable."""
    coord, hass, z = _zone(mods, state="unavailable")
    coord._house_state = "arriving"
    await _tick(coord, hass)
    assert _mode_writes(hass, ENT) == []
    assert len(_held_rows(hass, mods)) == 1
    H.set_climate(hass, ENT, preset_mode="manual", hold_activity="manual", state="cool")
    await _tick(coord, hass)
    assert [c[2]["hvac_mode"] for c in _mode_writes(hass, ENT)] == ["heat_cool"]
