"""HVAC W1-B §5.P1 arrester booking (N3) — SINGLE `override_detected` row
with `delta_f`, `gated_reason`, `gate_snapshot`, `mode`; precedence
nudge_win -> borrow_active -> immune_stamp -> temp_arrester_override ->
comfort_grant -> passive_mode -> governed; in-memory `last_detection_for`
scoped to the manual episode.

Drives the REAL `OverrideArrester._handle_climate_change` on the arrester
the smoke HVACCoordinator constructs. Behavioural replacements for the
retired two-site AST tests in test_arrester_ledger_visibility.py live here.
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
    """Real HA timers (arrester grace / TAO pre-warn / nudge eval) are armed
    by the production paths under test; the leak detector cancels + warns
    instead of failing (phcc opt-in)."""
    return True


ZONE = "zone_1"
ENT = "climate.test_zone_1"


def _arr(mods, *, enabled=True):
    coord, hass = H.make_coord(mods)
    arr = coord._override_arrester
    arr.enabled = enabled
    # Arrester listens via events; we drive the handler directly.
    return coord, hass, arr


def _rows(hass, mods):
    return hass.data[mods["const"].DOMAIN]["activity_logger"].actions("override_detected")


async def _fire(hass, arr, ev):
    arr._handle_climate_change(ev)
    await H.drain(hass)


def _severe():
    return H.make_event(ENT, old_preset="home", new_preset="manual",
                        old_high=76.0, new_high=64.0, old_low=68.0, new_low=64.0)


def _immune_person(hass, arr):
    hass.states.async_set("person.oji", "home", {"user_id": "u-oji", "friendly_name": "Oji"})
    arr.set_immune_persons(["person.oji"])


# ---- governed / passive -----------------------------------------------


@pytest.mark.asyncio
async def test_governed_detection_writes_one_row_with_attribution_and_delta(mods):
    coord, hass, arr = _arr(mods)
    await _fire(hass, arr, _severe())
    rows = _rows(hass, mods)
    assert len(rows) == 1
    d = rows[0]["details"]
    assert d["mode"] == "governed" and d["gated_reason"] is None
    assert d["delta_f"] == -12.0
    for f in ("old_preset", "new_preset", "old_high", "new_high", "gate_snapshot"):
        assert f in d
    assert rows[0]["zone"] == ZONE and rows[0]["entity_id"] == ENT
    assert ZONE in arr._grace_timers, "governed severe path still arms its grace"
    rec = arr.last_detection_for(ENT)
    assert rec["delta_f"] == -12.0 and rec["gated_reason"] is None


@pytest.mark.asyncio
async def test_passive_mode_no_longer_double_books(mods):
    coord, hass, arr = _arr(mods, enabled=False)
    await _fire(hass, arr, _severe())
    rows = _rows(hass, mods)
    assert len(rows) == 1
    d = rows[0]["details"]
    assert d["mode"] == "passive" and d["gated_reason"] == "passive_mode"
    assert d["delta_f"] == -12.0
    assert ZONE not in arr._grace_timers


@pytest.mark.asyncio
async def test_within_tolerance_human_manual_books_sub_delta_and_no_revert(mods):
    coord, hass, arr = _arr(mods)
    ev = H.make_event(ENT, old_preset="home", new_preset="manual",
                      old_high=76.0, new_high=76.5, old_low=68.0, new_low=68.0)
    await _fire(hass, arr, ev)
    d = _rows(hass, mods)[0]["details"]
    assert d["delta_f"] == 0.5 and d["gated_reason"] is None
    assert ZONE not in arr._grace_timers and ZONE not in arr._compromise_timers


@pytest.mark.asyncio
async def test_non_override_state_change_writes_no_row(mods):
    coord, hass, arr = _arr(mods)
    ev = H.make_event(ENT, old_preset="home", new_preset="home", new_high=74.0)
    await _fire(hass, arr, ev)
    assert _rows(hass, mods) == []
    assert arr.last_detection_for(ENT) is None


# ---- gate (e): nudge_win / borrow_active -------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("src", ["token", "restore_timer", "in_flight"])
async def test_nudge_win_booked_no_revert(mods, src):
    coord, hass, arr = _arr(mods)
    if src == "token":
        arr._nudge_excursion_tokens[ZONE] = type("T", (), {"excursion_id": "n1"})()
    elif src == "restore_timer":
        arr._nudge_restore_timers[ZONE] = lambda: None
    else:
        arr._nudge_in_flight.add(ZONE)
    await _fire(hass, arr, _severe())
    rows = _rows(hass, mods)
    assert len(rows) == 1
    assert rows[0]["details"]["gated_reason"] == "nudge_win"
    assert ZONE not in arr._grace_timers
    assert arr.last_detection_for(ENT)["gated_reason"] == "nudge_win"


@pytest.mark.asyncio
@pytest.mark.parametrize("src", ["row", "compromise_timer"])
async def test_borrow_active_booked_for_non_nudge_kinds(mods, src):
    coord, hass, arr = _arr(mods)
    ex = mods["hvac_excursion"]
    if src == "row":
        ex._test_seed_row(zone_id=ZONE, kind=ex.EXCURSION_KIND.BANKING, duration_s=None)
    else:
        arr._compromise_timers[ZONE] = lambda: None
    await _fire(hass, arr, _severe())
    d = _rows(hass, mods)[0]["details"]
    assert d["gated_reason"] == "borrow_active"
    assert d["gate_snapshot"]["borrow_row" if src == "row" else "compromise_timer"] is True
    assert ZONE not in arr._grace_timers
    ex._test_clear_leases()


# ---- immune / TAO / comfort ----------------------------------------------


@pytest.mark.asyncio
async def test_immune_stamp_booked_and_hold_stamped(mods):
    coord, hass, arr = _arr(mods)
    _immune_person(hass, arr)
    ev = _severe(); ev.context.user_id = "u-oji"
    await _fire(hass, arr, ev)
    d = _rows(hass, mods)[0]["details"]
    assert d["gated_reason"] == "immune_stamp"
    assert ZONE in arr._immune_holds
    assert ZONE not in arr._grace_timers
    led = hass.data[mods["const"].DOMAIN]["activity_logger"]
    assert len(led.actions("immune_hold_stamped")) == 1


@pytest.mark.asyncio
async def test_temp_arrester_override_booked_no_revert(mods):
    coord, hass, arr = _arr(mods)
    arr.set_temp_arrester_override(True)
    await _fire(hass, arr, _severe())
    d = _rows(hass, mods)[0]["details"]
    assert d["gated_reason"] == "temp_arrester_override"
    assert ZONE not in arr._grace_timers


@pytest.mark.asyncio
async def test_comfort_grant_booked_and_seeded(mods):
    coord, hass, arr = _arr(mods)
    meta = {"zone_id": ZONE, "climate_entity_id": ENT, "hvac_mode": "cool",
            "current_temp": 79.0, "delta_f": 4.0, "direction": "cooler",
            "granted_setpoint": 72.0}
    arr._comfort_request_qualifies = lambda *a, **k: (True, meta)
    arr.update_energy_state(0.0, False, battery_soc=95.0, battery_blind=False, shed_active=False)
    await _fire(hass, arr, _severe())
    d = _rows(hass, mods)[0]["details"]
    assert d["gated_reason"] == "comfort_grant"
    assert ZONE in arr._comfort_delay_timers
    assert ZONE not in arr._grace_timers


# ---- precedence (top-down, nudge_win at the TOP) ---------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("lower,expect", [
    ("immune", "nudge_win"),
    ("tao", "nudge_win"),
    ("comfort", "nudge_win"),
    ("passive", "nudge_win"),
])
async def test_nudge_win_short_circuits_every_lower_rung(mods, lower, expect):
    coord, hass, arr = _arr(mods, enabled=(lower != "passive"))
    arr._nudge_excursion_tokens[ZONE] = type("T", (), {"excursion_id": "n1"})()
    ev = _severe()
    if lower == "immune":
        _immune_person(hass, arr); ev.context.user_id = "u-oji"
    elif lower == "tao":
        arr.set_temp_arrester_override(True)
    elif lower == "comfort":
        arr._comfort_request_qualifies = lambda *a, **k: (True, {"zone_id": ZONE})
        arr.update_energy_state(0.0, False, battery_soc=95.0)
    await _fire(hass, arr, ev)
    assert _rows(hass, mods)[0]["details"]["gated_reason"] == expect
    assert ZONE not in arr._immune_holds
    assert ZONE not in arr._comfort_delay_timers


@pytest.mark.asyncio
@pytest.mark.parametrize("pair,expect", [
    (("borrow", "immune"), "borrow_active"),
    (("immune", "tao"), "immune_stamp"),
    (("tao", "comfort"), "temp_arrester_override"),
    (("comfort", "passive"), "comfort_grant"),
])
async def test_arrester_gated_reason_precedence(mods, pair, expect):
    hi, lo = pair
    coord, hass, arr = _arr(mods, enabled=(lo != "passive"))
    ex = mods["hvac_excursion"]
    ev = _severe()
    for g in (hi, lo):
        if g == "borrow":
            ex._test_seed_row(zone_id=ZONE, kind=ex.EXCURSION_KIND.COMPROMISE, duration_s=600)
        elif g == "immune":
            _immune_person(hass, arr); ev.context.user_id = "u-oji"
        elif g == "tao":
            arr.set_temp_arrester_override(True)
        elif g == "comfort":
            arr._comfort_request_qualifies = lambda *a, **k: (True, {"zone_id": ZONE})
            arr.update_energy_state(0.0, False, battery_soc=95.0)
    await _fire(hass, arr, ev)
    rows = _rows(hass, mods)
    assert len(rows) == 1
    assert rows[0]["details"]["gated_reason"] == expect
    ex._test_clear_leases()


# ---- episode scoping of last_detection --------------------------------------


@pytest.mark.asyncio
async def test_last_detection_cleared_when_entity_leaves_manual(mods):
    coord, hass, arr = _arr(mods)
    await _fire(hass, arr, _severe())
    assert arr.last_detection_for(ENT) is not None
    await _fire(hass, arr, H.make_event(ENT, old_preset="manual", new_preset="home"))
    assert arr.last_detection_for(ENT) is None


@pytest.mark.asyncio
async def test_last_detection_returns_copy(mods):
    coord, hass, arr = _arr(mods)
    await _fire(hass, arr, _severe())
    rec = arr.last_detection_for(ENT)
    rec["delta_f"] = 999
    assert arr.last_detection_for(ENT)["delta_f"] == -12.0
