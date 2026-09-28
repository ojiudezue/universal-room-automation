"""HVAC fast occupancy response (v5.103.20) — D1: HVAC's own release clock.

Plan: docs/planning/PLANNING_hvac_fast_occupancy_response.md REV 3 §4 + §11d
(drill rows 1-14, 43, 44).

Invariants under test:
  INV-5  the SHADOW (v5.103.19 machine) runs byte-for-byte on every pass and
         alone owns `_hvac_armed` / `_hvac_prev_state_occupied` /
         `_hvac_tail_until`; night output >= shadow; legacy states
         (home_night / guest / arriving / away / None) are v5.103.19.
  §4.1   ONE evidence stamp in the room coordinator: sensors / grace-hold /
         the camera+BLE override verdict / Override Occupied; suppressed
         sources never stamp (not even the falling edge); Override Vacant
         blocks; fan-recheck release clears `active` without a stamp.
  §4.2   evidence states: `active OR now < ev + hold_ev`; bounded
         refresh-failure hold (evidence states only); night = shadow OR rule.
  §4.5   back-fill `last_occupied_time` to the exact release, evidence +
         night states only.

Real package imports (no HA stubs, no sys.modules mutation) — the same
pattern as test_hvac_night_hold_follows_sleep.py. Every oracle below is an
independent literal, never re-derived from the code under test.
"""
from __future__ import annotations

import ast
import os
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from custom_components.universal_room_automation import const as C  # noqa: E402
from custom_components.universal_room_automation.const import (  # noqa: E402
    CONF_ENTRY_TYPE,
    CONF_ROOM_NAME,
    CONF_ROOM_TYPE,
    DOMAIN,
    ENTRY_TYPE_ROOM,
    OCCUPANCY_SOURCE_FAN_RECHECK_RELEASE,
    OCCUPANCY_SOURCE_MMWAVE_FAN_DEMOTED,
    STATE_OCCUPANCY_SOURCE,
    STATE_OCCUPIED,
)
from custom_components.universal_room_automation.coordinator import (  # noqa: E402
    UniversalRoomCoordinator,
)
from custom_components.universal_room_automation.domain_coordinators import (  # noqa: E402
    hvac_const as HC,
    hvac_zones as _hvac_zones,
)

ZoneManager = _hvac_zones.ZoneManager
ZoneState = _hvac_zones.ZoneState

# 2026-09-28 15:00 UTC = 10:00 CDT (home_day).
NOW = datetime(2026, 9, 28, 15, 0, 0, tzinfo=timezone.utc)
S = timedelta  # noqa: N816


def _zm() -> ZoneManager:
    return ZoneManager(MagicMock())


# ==========================================================================
# Tables + selectors (rows 43-44, RULING R2)
# ==========================================================================

def test_evidence_hold_values():
    """RULING R1/R2: independent literals for every room type."""
    T = C.ROOM_TYPE_HVAC_HOLD
    assert T["closet"] == 60
    assert T["infrastructure"] == 60
    assert T["generic"] == 120
    assert T["utility"] == 120
    assert T["media_room"] == 120
    assert T["garage"] == 120
    assert T["bathroom"] == 180
    assert T["common_area"] == 180          # operator ruling R2 "3mins"
    assert T["bedroom"] == 240
    assert T["hallway"] == 0
    assert set(T) == {
        "closet", "infrastructure", "generic", "utility", "media_room",
        "garage", "bathroom", "common_area", "bedroom", "hallway",
    }


def test_legacy_tail_is_frozen_v5_103_19():
    """The shadow's table: v5.103.19 day values, every type explicit."""
    L = C.ROOM_TYPE_HVAC_TAIL_LEGACY
    assert L["bedroom"] == 60
    assert L["media_room"] == 120
    assert L["common_area"] == 60
    assert L["generic"] == 60
    assert L["closet"] == 60
    assert L["bathroom"] == 60
    assert L["garage"] == 60
    assert L["utility"] == 60
    assert L["infrastructure"] == 60
    assert L["hallway"] == 0
    assert len(L) == 10


def test_selectors_split():
    """Shadow selector (`_effective_hvac_hold_seconds`) reads the legacy
    tail; evidence selector (`_evidence_hold_seconds`) reads the new table.
    Bedroom discriminates: 60 vs 240."""
    zm = _zm()
    assert zm._effective_hvac_hold_seconds("bedroom", "home_day") == 60
    assert zm._effective_hvac_hold_seconds("bedroom", "home_night") == 60
    assert zm._effective_hvac_hold_seconds("bedroom", "sleep") == 1800
    assert zm._evidence_hold_seconds("bedroom") == 240
    assert zm._evidence_hold_seconds("common_area") == 180
    assert zm._evidence_hold_seconds("closet") == 60
    assert zm._evidence_hold_seconds("unknown_type") == 60   # DEFAULT fallback
    assert zm._evidence_hold_seconds("hallway") == 0


def test_evidence_rule_states_and_refresh_bound():
    assert HC.HVAC_EVIDENCE_RULE_STATES == ("home_day", "home_evening")
    assert HC.HVAC_NIGHT_HOLD_STATES == ("sleep", "waking")
    assert HC.HVAC_EVIDENCE_REFRESH_FAIL_HOLD_S == 600


def test_per_room_day_override_wins():
    """Override 400 beats bedroom 240 in the evidence hold. Config extreme:
    a day override LARGER than the night table (2400 > 1800) — the evidence
    hold is 2400 and the shadow's clamp lifts night to 2400 (unchanged
    v5.103.8 behaviour), never the other way round."""
    zm = _zm()
    assert zm._evidence_hold_seconds("bedroom", override_day=400) == 400
    assert zm._evidence_hold_seconds("bedroom", override_day=0) == 0
    assert zm._evidence_hold_seconds("bedroom", override_day=2400) == 2400
    assert zm._effective_hvac_hold_seconds(
        "bedroom", "sleep", override_day=2400, room_name="x",
    ) == 2400
    assert zm._effective_hvac_hold_seconds(
        "bedroom", "home_day", override_day=2400, room_name="x",
    ) == 2400


def test_display_hold_follows_active_rule():
    zm = _zm()
    assert zm._display_hold("bedroom", "home_day") == (240, "evidence")
    assert zm._display_hold("bedroom", "home_evening") == (240, "evidence")
    assert zm._display_hold("bedroom", "sleep") == (1800, "night")
    assert zm._display_hold("bedroom", "waking") == (1800, "night")
    assert zm._display_hold("bedroom", "home_night") == (60, "legacy")
    assert zm._display_hold("bedroom", "guest") == (60, "legacy")
    assert zm._display_hold("bedroom", None) == (60, "legacy")
    assert zm._display_hold("bedroom", "home_day", override_day=90) == (90, "evidence")


# ==========================================================================
# Producer: evidence rule vs shadow (rows 1-6)
# ==========================================================================

def _ev(zm, *, occupied, now, hs, ev, active, room="r1", rt="bedroom",
        refresh_ok=True, override_day=None, override_night=None):
    return zm._compute_hvac_occupied(
        room_name=room, room_type=rt, state_occupied=occupied, now=now,
        house_state=hs, override_day=override_day,
        override_night=override_night,
        last_evidence=ev, evidence_active=active, refresh_ok=refresh_ok,
    )


def test_evidence_state_ignores_lighting_timeout():
    """Row 1. home_day, lighting `occupied` still True (timeout riding),
    evidence 250 s old > bedroom hold 240 -> HVAC output False while the
    shadow is still armed (riding `occupied`)."""
    zm = _zm()
    out = _ev(zm, occupied=True, now=NOW, hs="home_day",
              ev=NOW - S(seconds=250), active=False)
    assert out is False
    assert zm._hvac_armed["r1"] is True          # shadow untouched
    assert zm._hvac_rule["r1"] == "evidence"
    # Within the hold -> True.
    assert _ev(zm, occupied=True, now=NOW, hs="home_day",
               ev=NOW - S(seconds=239), active=False) is True
    # Exactly at the hold boundary (strict <): released.
    assert _ev(zm, occupied=True, now=NOW, hs="home_day",
               ev=NOW - S(seconds=240), active=False) is False


def test_home_evening_to_sleep_mid_timeout_stays_held():
    """Row 2 (INV-5, the Jaya/Ziri repro). home_evening: evidence 250 s
    old -> released (240). House -> sleep with lighting still `occupied`:
    the shadow (armed, riding `occupied`) holds True; when `occupied`
    falls the tail is the NIGHT 1800 s."""
    zm = _zm()
    t0 = NOW
    assert _ev(zm, occupied=True, now=t0, hs="home_evening",
               ev=t0 - S(seconds=250), active=False) is False
    assert zm._hvac_armed["r1"] is True
    assert zm._hvac_prev_state_occupied["r1"] is True
    t1 = t0 + S(seconds=30)
    assert _ev(zm, occupied=True, now=t1, hs="sleep",
               ev=t0 - S(seconds=250), active=False) is True
    assert zm._hvac_rule["r1"] == "night"
    t2 = t1 + S(seconds=30)
    assert _ev(zm, occupied=False, now=t2, hs="sleep",
               ev=t0 - S(seconds=250), active=False) is True
    assert zm._hvac_tail_until["r1"] == t2 + S(seconds=1800)
    assert zm._hvac_arm_source["r1"] == "tail"


def test_home_evening_to_sleep_mid_timeout_stays_held_post_gate_b():
    """Parametrised variant: even if `home_night` joins the evidence
    states later (D0c Gate B), the crossing INTO sleep is still held by
    the shadow."""
    zm = _zm()
    with patch.object(HC, "HVAC_EVIDENCE_RULE_STATES",
                      ("home_day", "home_evening", "home_night")):
        assert _ev(zm, occupied=True, now=NOW, hs="home_night",
                   ev=NOW - S(seconds=250), active=False) is False
        assert _ev(zm, occupied=True, now=NOW + S(seconds=30), hs="sleep",
                   ev=NOW - S(seconds=250), active=False) is True


def test_night_release_never_before_shadow():
    """Row 3. sleep: evidence long expired, shadow tail still live ->
    True; after the shadow tail expires -> False."""
    zm = _zm()
    t0 = NOW
    _ev(zm, occupied=True, now=t0, hs="sleep", ev=t0, active=True)
    t1 = t0 + S(seconds=60)
    assert _ev(zm, occupied=False, now=t1, hs="sleep",
               ev=t0, active=False) is True            # tail armed 1800
    t2 = t1 + S(seconds=1000)                          # evidence 240 gone
    assert _ev(zm, occupied=False, now=t2, hs="sleep",
               ev=t0, active=False) is True
    t3 = t1 + S(seconds=1801)
    assert _ev(zm, occupied=False, now=t3, hs="sleep",
               ev=t0, active=False) is False


def test_night_evidence_extends_past_shadow():
    """sleep: shadow released (no arm ever), fresh evidence -> True (the
    OR); evidence older than 240 -> False."""
    zm = _zm()
    assert _ev(zm, occupied=False, now=NOW, hs="sleep",
               ev=NOW - S(seconds=100), active=False) is True
    assert _ev(zm, occupied=False, now=NOW, hs="sleep",
               ev=NOW - S(seconds=300), active=False) is False


def test_home_night_is_legacy_until_gate():
    """Row 4. home_night: evidence long expired but lighting `occupied`
    True -> shadow decides -> True; rule reported `legacy`."""
    zm = _zm()
    assert _ev(zm, occupied=True, now=NOW, hs="home_night",
               ev=NOW - S(hours=3), active=False) is True
    assert zm._hvac_rule["r1"] == "legacy"
    # And a legacy falling edge arms the v5.103.19 day tail (60 s).
    assert _ev(zm, occupied=False, now=NOW + S(seconds=30), hs="home_night",
               ev=NOW - S(hours=3), active=False) is True
    assert zm._hvac_tail_until["r1"] == NOW + S(seconds=90)


@pytest.mark.parametrize("hs", ["guest", "arriving", "away", None])
def test_guest_arriving_away_are_legacy(hs):
    zm = _zm()
    assert _ev(zm, occupied=True, now=NOW, hs=hs,
               ev=NOW - S(hours=3), active=False) is True
    assert zm._hvac_rule["r1"] == "legacy"
    # Fresh evidence with lighting empty does NOT hold in legacy states.
    zm2 = _zm()
    assert _ev(zm2, occupied=False, now=NOW, hs=hs,
               ev=NOW, active=True) is False


def test_hold_zero_holds_while_active():
    """Row 5. Per-room day hold 0: True while a sensor is on at the latest
    refresh, False the moment it is not (no tail)."""
    zm = _zm()
    assert _ev(zm, occupied=True, now=NOW, hs="home_day", ev=NOW,
               active=True, override_day=0) is True
    assert _ev(zm, occupied=True, now=NOW + S(seconds=1), hs="home_day",
               ev=NOW, active=False, override_day=0) is False


def test_hold_shorter_than_poll_no_drop_while_on():
    """A 10 s hold with a 35 s poll: the `active` term keeps the room
    occupied between polls of a continuously-on sensor."""
    zm = _zm()
    assert _ev(zm, occupied=True, now=NOW, hs="home_day",
               ev=NOW - S(seconds=35), active=True, override_day=10) is True
    assert _ev(zm, occupied=True, now=NOW, hs="home_day",
               ev=NOW - S(seconds=35), active=False, override_day=10) is False


def test_refresh_failure_hold_evidence_states_only_and_bounded():
    """Row 6. home_day: a failing refresh does not trust the stale `active`;
    the previous True output is held for at most 600 s after the last
    evidence. Night: no such hold (shadow decides)."""
    zm = _zm()
    t0 = NOW
    assert _ev(zm, occupied=True, now=t0, hs="home_day", ev=t0, active=True) is True
    # Refresh failing, evidence 300 s old (> 240): held (bounded).
    t1 = t0 + S(seconds=300)
    assert _ev(zm, occupied=True, now=t1, hs="home_day", ev=t0,
               active=True, refresh_ok=False) is True
    # 599 s: still held; 600 s: released (strict <).
    assert _ev(zm, occupied=True, now=t0 + S(seconds=599), hs="home_day",
               ev=t0, active=True, refresh_ok=False) is True
    assert _ev(zm, occupied=True, now=t0 + S(seconds=600), hs="home_day",
               ev=t0, active=True, refresh_ok=False) is False
    # Once released, a still-failing refresh cannot re-hold.
    assert _ev(zm, occupied=True, now=t0 + S(seconds=400), hs="home_day",
               ev=t0, active=True, refresh_ok=False) is False
    # Stale `active` alone (no previous True) never holds.
    zm2 = _zm()
    assert _ev(zm2, occupied=False, now=t0, hs="home_day",
               ev=t0 - S(seconds=700), active=True, refresh_ok=False) is False
    # Night: previous True, refresh failing, shadow not armed -> False.
    zm3 = _zm()
    assert _ev(zm3, occupied=False, now=t0, hs="sleep", ev=t0, active=True) is True
    assert _ev(zm3, occupied=False, now=t0 + S(seconds=300), hs="sleep",
               ev=t0, active=True, refresh_ok=False) is False


def test_shadow_dicts_untouched_by_evidence_branch():
    """50 random evidence-state passes: the three shadow dicts equal a
    shadow-only run on the same `occupied` series."""
    rng = random.Random(20260928)
    series = [(rng.random() < 0.6, rng.choice([0, 30, 100, 300, 1000]),
               rng.random() < 0.5) for _ in range(50)]
    a, b = _zm(), _zm()
    t = NOW
    for occ, age, active in series:
        t += S(seconds=31)
        _ev(a, occupied=occ, now=t, hs="home_day",
            ev=t - S(seconds=age), active=active)
        b._compute_hvac_occupied(
            room_name="r1", room_type="bedroom", state_occupied=occ, now=t,
            house_state="home_day",
        )
    assert a._hvac_armed == b._hvac_armed
    assert a._hvac_prev_state_occupied == b._hvac_prev_state_occupied
    assert a._hvac_tail_until == b._hvac_tail_until
    assert a._hvac_arm_source == b._hvac_arm_source


def test_direct_caller_without_evidence_gets_shadow():
    """A pre-v5.103.20 direct caller (no evidence keywords) in home_day gets
    the shadow's output, so existing producer tests stay valid."""
    zm = _zm()
    assert zm._compute_hvac_occupied(
        room_name="r1", room_type="bedroom", state_occupied=True, now=NOW,
        house_state="home_day",
    ) is True


# ==========================================================================
# update_room_conditions: accessor reads, back-fill (rows 13, 14, 43)
# ==========================================================================

class _Entry:
    def __init__(self, room_name: str, room_type: str, entry_id=None) -> None:
        from homeassistant.config_entries import ConfigEntryState
        self.entry_id = entry_id or f"e_{room_name}"
        self.state = ConfigEntryState.LOADED
        self.disabled_by = None
        self.data = {
            CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM,
            CONF_ROOM_NAME: room_name,
            CONF_ROOM_TYPE: room_type,
        }
        self.options: dict = {}


class _RoomCoord:
    """Fake room coordinator with the v5.103.20 accessor surface."""

    def __init__(self, occupied=False, ev=None, active=False, refresh_ok=True):
        self.data = {"occupied": occupied}
        self.ev = ev
        self.active = active
        self.last_update_success = refresh_ok

    def get_last_hvac_evidence_time(self):
        return self.ev

    def is_hvac_evidence_active(self):
        return self.active


def _install(rooms: dict[str, tuple[str, object]]):
    """rooms: name -> (room_type, coordinator). Returns (zm, zone)."""
    entries = [_Entry(n, rt) for n, (rt, _c) in rooms.items()]
    hass = MagicMock()

    class _CEs:
        def async_entries(self, dom):
            return entries

    hass.config_entries = _CEs()
    hass.data = {DOMAIN: {e.entry_id: rooms[e.data[CONF_ROOM_NAME]][1]
                          for e in entries
                          if rooms[e.data[CONF_ROOM_NAME]][1] is not None}}
    hass.states = MagicMock()
    hass.states.get = lambda ent_id: None
    zm = ZoneManager(hass)
    zone = ZoneState(zone_id="z1", zone_name="Z1", climate_entity="climate.z1")
    zone.rooms = list(rooms)
    zm._zones["z1"] = zone
    return zm, zone


def _tick(zm, when, hs, zone_ids=None):
    with patch.object(_hvac_zones.dt_util, "now", return_value=when), \
         patch.object(_hvac_zones.dt_util, "utcnow", return_value=when):
        zm.update_room_conditions(house_state=hs, zone_ids=zone_ids)


def test_last_occupied_time_backfilled_to_exact_release():
    """Row 13. home_day: room evidence at t0; at t0+400 the pass sees the
    zone empty -> `last_occupied_time` == t0 + 240 exactly (not the pass
    time, not t0)."""
    rc = _RoomCoord(occupied=True, ev=NOW, active=True)
    zm, zone = _install({"bed": ("bedroom", rc)})
    _tick(zm, NOW, "home_day")
    assert zone.any_room_hvac_occupied is True
    assert zone.last_occupied_time == NOW
    rc.active = False
    rc.data = {"occupied": True}            # lighting timeout still riding
    t1 = NOW + S(seconds=400)
    _tick(zm, t1, "home_day")
    assert zone.any_room_hvac_occupied is False
    assert zone.last_occupied_time == NOW + S(seconds=240)
    assert zm.room_release_at("bed") == NOW + S(seconds=240)
    assert zm.zone_release_at("z1") == NOW + S(seconds=240)
    assert zm.zone_away_due_at("z1", 300) == NOW + S(seconds=540)


def test_backfill_night_uses_later_of_shadow_and_evidence():
    """sleep: shadow tail (falling edge at t1 + 1800) is later than the
    evidence release; back-fill lands on the shadow's end."""
    rc = _RoomCoord(occupied=True, ev=NOW, active=True)
    zm, zone = _install({"bed": ("bedroom", rc)})
    _tick(zm, NOW, "sleep")
    rc.active = False
    rc.data = {"occupied": False}
    t1 = NOW + S(seconds=60)
    _tick(zm, t1, "sleep")                  # tail armed to t1 + 1800
    assert zone.any_room_hvac_occupied is True
    assert zm.zone_release_at("z1") == t1 + S(seconds=1800)
    t2 = t1 + S(seconds=2000)
    _tick(zm, t2, "sleep")
    assert zone.any_room_hvac_occupied is False
    assert zone.last_occupied_time == t1 + S(seconds=1800)


def test_no_backfill_in_legacy_states():
    """Row 14. home_night: pass at t1 sees lighting empty (tail 60 armed),
    pass at t1+100 sees released -> `last_occupied_time` stays at t1 (the
    last pass that saw the zone occupied), NOT t1 + 60."""
    rc = _RoomCoord(occupied=True, ev=NOW, active=True)
    zm, zone = _install({"bed": ("bedroom", rc)})
    _tick(zm, NOW, "home_night")
    rc.active = False
    rc.data = {"occupied": False}
    t1 = NOW + S(seconds=400)
    _tick(zm, t1, "home_night")             # tail 60 -> still occupied
    assert zone.any_room_hvac_occupied is True
    assert zone.last_occupied_time == t1
    t2 = t1 + S(seconds=100)
    _tick(zm, t2, "home_night")
    assert zone.any_room_hvac_occupied is False
    assert zone.last_occupied_time == t1
    assert zm.zone_release_at("z1") is None  # legacy: no exit timer


def test_accessor_fallback_uses_isinstance_datetime():
    """Row 43. A MagicMock coordinator (accessor returns a MagicMock) reads
    as `ev None`, `active False`: home_day -> False even with `occupied`
    True (evidence rule); sleep -> shadow decides -> True."""
    mm = MagicMock()
    mm.data = {"occupied": True}
    zm, zone = _install({"bed": ("bedroom", mm)})
    _tick(zm, NOW, "home_day")
    assert zone.any_room_hvac_occupied is False
    assert zm._hvac_last_ev["bed"] is None
    zm2, zone2 = _install({"bed": ("bedroom", MagicMock(data={"occupied": True}))})
    _tick(zm2, NOW, "sleep")
    assert zone2.any_room_hvac_occupied is True


def test_producer_reads_active_and_refresh_from_coordinator():
    """Wire-in anchor for the three reads in update_room_conditions:
    active -> holds with hold 0 evidence; refresh failure -> bounded hold."""
    rc = _RoomCoord(occupied=False, ev=NOW, active=True)
    zm, zone = _install({"bed": ("bedroom", rc)})
    _tick(zm, NOW + S(seconds=300), "home_day")     # ev 300 s old, active
    assert zone.any_room_hvac_occupied is True
    rc.active = False
    rc.last_update_success = False
    _tick(zm, NOW + S(seconds=400), "home_day")     # failing refresh: held
    assert zone.any_room_hvac_occupied is True
    _tick(zm, NOW + S(seconds=601), "home_day")     # bound passed
    assert zone.any_room_hvac_occupied is False


def test_hallway_never_holds_and_absent_set_pass_complete():
    """Hallway rooms contribute nothing to release; a zone room with no
    coordinator is in `_coordinator_absent_this_pass` even when the pass
    is filtered to ANOTHER zone (row 17 sibling)."""
    rc = _RoomCoord(occupied=True, ev=NOW, active=True)
    zm, zone = _install({"hall": ("hallway", rc), "bed": ("bedroom", None)})
    zone2 = ZoneState(zone_id="z2", zone_name="Z2", climate_entity="climate.z2")
    zone2.rooms = []
    zm._zones["z2"] = zone2
    _tick(zm, NOW, "home_day", zone_ids={"z2"})
    assert "bed" in zm._coordinator_absent_this_pass
    assert zone.room_conditions == []          # z1 untouched by the z2 pass
    _tick(zm, NOW, "home_day")
    assert zone.any_room_hvac_occupied is False
    assert zm.zone_release_at("z1") is None


# ==========================================================================
# Coordinator stamp (rows 7-12) — drives the REAL `_stamp_hvac_evidence`
# on a bare UniversalRoomCoordinator (object.__new__ pattern, precedent
# test_ble_hold_cap.py:_bare_coord).
# ==========================================================================

def _bare(*, override_vacant=False, override_occupied=False, last_occ=False):
    c = object.__new__(UniversalRoomCoordinator)
    entry = MagicMock()
    entry.data = {"room_name": "Testbed", CONF_ROOM_TYPE: "bedroom"}
    entry.options = {}
    object.__setattr__(c, "entry", entry)
    object.__setattr__(c, "_last_occupied_state", last_occ)
    object.__setattr__(c, "_last_hvac_evidence_time", None)
    object.__setattr__(c, "_hvac_evidence_active", False)
    object.__setattr__(c, "_hvac_evidence_since", None)
    object.__setattr__(c, "_is_override_vacant", lambda: override_vacant)
    object.__setattr__(c, "_is_override_occupied", lambda: override_occupied)
    object.__setattr__(c, "_last_motion_time", NOW)
    object.__setattr__(c, "_became_occupied_time", NOW)
    object.__setattr__(c, "_ble_only_hold_since", None)
    object.__setattr__(c, "_last_occupied_since_for_handler", None)
    object.__setattr__(c, "data", {})
    return c


def _stamp(c, *, source="motion", sensors=True, grace=False, now=NOW):
    return c._stamp_hvac_evidence(
        {STATE_OCCUPANCY_SOURCE: source, STATE_OCCUPIED: sensors},
        sensors, grace, now,
    )


def test_sensor_evidence_stamps_and_tracks_since():
    c = _bare()
    assert _stamp(c, source="motion", sensors=True, now=NOW) is True
    assert c.get_last_hvac_evidence_time() == NOW
    assert c.is_hvac_evidence_active() is True
    assert c.get_hvac_evidence_since() == NOW
    t1 = NOW + S(seconds=30)
    _stamp(c, source="mmwave", sensors=True, now=t1)
    assert c.get_last_hvac_evidence_time() == t1
    assert c.get_hvac_evidence_since() == NOW      # run start unchanged


def test_falling_edge_refresh_stamps():
    """Row 10. active at t0; the first inactive refresh (t1) stamps once;
    the next inactive refresh (t2) does NOT."""
    c = _bare()
    _stamp(c, source="motion", sensors=True, now=NOW)
    t1 = NOW + S(seconds=2)
    assert _stamp(c, source="timeout", sensors=False, now=t1) is False
    assert c.get_last_hvac_evidence_time() == t1
    assert c.is_hvac_evidence_active() is False
    assert c.get_hvac_evidence_since() is None
    t2 = t1 + S(seconds=30)
    _stamp(c, source="timeout", sensors=False, now=t2)
    assert c.get_last_hvac_evidence_time() == t1


def test_timeout_source_is_not_evidence():
    """The lighting timeout (`occupied` True, no sensor) never stamps a
    cold room."""
    c = _bare()
    assert _stamp(c, source="timeout", sensors=False) is False
    assert c.get_last_hvac_evidence_time() is None


@pytest.mark.parametrize("source", [
    OCCUPANCY_SOURCE_MMWAVE_FAN_DEMOTED, "failsafe",
    OCCUPANCY_SOURCE_FAN_RECHECK_RELEASE,
])
def test_no_stamp_on_fan_demoted_failsafe_recheck_sources(source):
    """Row 7. A suppressed source never stamps — not even the falling-edge
    stamp on that tick, and not on the next tick either."""
    c = _bare(last_occ=True)
    _stamp(c, source="motion", sensors=True, now=NOW)
    t1 = NOW + S(seconds=30)
    # sensors=True here is deliberate: the suppressed source wins.
    assert _stamp(c, source=source, sensors=True, now=t1) is False
    assert c.get_last_hvac_evidence_time() == NOW
    assert c.is_hvac_evidence_active() is False
    t2 = t1 + S(seconds=30)
    assert _stamp(c, source="none", sensors=False, now=t2) is False
    assert c.get_last_hvac_evidence_time() == NOW   # no falling-edge stamp


def test_camera_ble_stamp_only_from_override_verdict():
    """Row 8. `source == camera` / `ble` (the override blocks' verdict)
    stamps with no sensor active; any other non-sensor source does not."""
    for src in ("camera", "ble"):
        c = _bare(last_occ=True)
        assert _stamp(c, source=src, sensors=False) is True
        assert c.get_last_hvac_evidence_time() == NOW
    for src in ("none", "timeout", "override", "grace_hold"):
        c = _bare(last_occ=False)
        assert _stamp(c, source=src, sensors=False) is False
        assert c.get_last_hvac_evidence_time() is None


def test_camera_ghost_ends_at_failsafe_no_falling_edge_stamp():
    """Config extreme: a stuck camera stamps every tick until the failsafe
    fires; the failsafe tick is suppressed (no stamp, no falling edge)."""
    c = _bare(last_occ=True)
    t = NOW
    for _ in range(5):
        assert _stamp(c, source="camera", sensors=False, now=t) is True
        t += S(seconds=30)
    last = c.get_last_hvac_evidence_time()
    assert _stamp(c, source="failsafe", sensors=False, now=t) is False
    assert c.get_last_hvac_evidence_time() == last
    assert c.is_hvac_evidence_active() is False


def test_grace_hold_and_override_occupied_are_evidence():
    c = _bare(last_occ=True)
    assert _stamp(c, source="grace_hold", sensors=False, grace=True) is True
    c2 = _bare(last_occ=False)
    assert _stamp(c2, source="grace_hold", sensors=False, grace=True) is False
    c3 = _bare(override_occupied=True)
    assert _stamp(c3, source="override", sensors=False) is True


def test_override_vacant_blocks_stamp():
    """Row 9. Override Vacant: no evidence even with a sensor on; the room
    releases at last evidence + hold."""
    c = _bare(override_vacant=True)
    assert _stamp(c, source="override", sensors=True) is False
    assert c.get_last_hvac_evidence_time() is None
    assert c.is_hvac_evidence_active() is False


def test_fan_recheck_release_clears_active():
    """Row 12. `apply_fan_recheck_release` ends evidence WITHOUT a stamp."""
    c = _bare(last_occ=True)
    _stamp(c, source="mmwave", sensors=True, now=NOW)
    assert c.is_hvac_evidence_active() is True
    c.apply_fan_recheck_release()
    assert c.is_hvac_evidence_active() is False
    assert c.get_hvac_evidence_since() is None
    assert c.get_last_hvac_evidence_time() == NOW
    assert c.data[STATE_OCCUPANCY_SOURCE] == OCCUPANCY_SOURCE_FAN_RECHECK_RELEASE
    # The next refresh carries the suppressed source -> still no stamp.
    assert _stamp(c, source=OCCUPANCY_SOURCE_FAN_RECHECK_RELEASE,
                  sensors=False, now=NOW + S(seconds=2)) is False
    assert c.get_last_hvac_evidence_time() == NOW


def test_stamp_wired_in_async_update_data_after_override_switches():
    """Wire-in anchor (precedent: test_path_alpha_d2a_matrix_classifier
    AST anchor; the 2,300-line room refresh is not drivable in-suite):
    `_stamp_hvac_evidence` is CALLED exactly once inside
    `_async_update_data`, after the Override-Vacant branch and before the
    skip-first block."""
    p = Path(_REPO_ROOT) / "custom_components/universal_room_automation/coordinator.py"
    tree = ast.parse(p.read_text(encoding="utf-8"))
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "_async_update_data"
    )
    calls = [
        n for n in ast.walk(fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and n.func.attr == "_stamp_hvac_evidence"
    ]
    assert len(calls) == 1
    call_line = calls[0].lineno
    vacant_lines = [
        n.lineno for n in ast.walk(fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and n.func.attr == "_is_override_vacant"
    ]
    skip_first_lines = [
        n.lineno for n in ast.walk(fn)
        if isinstance(n, ast.If) and isinstance(n.test, ast.Attribute)
        and n.test.attr == "_skip_first_automation"
    ]
    assert vacant_lines and max(vacant_lines) < call_line
    assert skip_first_lines and call_line < min(skip_first_lines)
    # Positional wiring: (data, any_sensor_active, grace_hold, now).
    args = [getattr(a, "id", None) for a in calls[0].args]
    assert args == ["data", "any_sensor_active", "grace_hold", "now"]
