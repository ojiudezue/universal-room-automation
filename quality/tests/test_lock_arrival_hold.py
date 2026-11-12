"""Suspicious-arrival hold (PLANNING_lock_suspicious_arrival_hold.md rev 2,
D2 / D3 / D4 / D5) — card GARAGE-REMOTE-LOCKOUT-SCHEDULE-1.

A person home/zone edge whose ``source`` tracker did not itself change at the
edge (the 2-GPS iPad blip) is held H seconds; a revert inside H cancels the
pair with no state change; at H a still-held state replays the ORIGINAL edge.
P2 (``SIGNAL_PERSON_ARRIVING``) and P5 (proximity) see the same hold.

Every test drives the REAL LockRegimeController through the injected fake
clock / timers / trackers of ``_lockout_harness`` and asserts on the
recorded ``lock.unlock`` stream and regime state. Times are literals (H = 5 s
default -> 4.9 / 5.1 s; boot arrival window 600 s), never imported constants.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from _lockout_harness import TZ, FakeState, World, load, settle

const = load("const")
R = load("domain_coordinators.security_lock_regime")

LOCK_A = "lock.konnected_f0f5bd523b00_lock"
LOCK_B = "lock.ratgdov25i_dbfe2a_lock_remotes"
BED = "lock.master_bedroom_lock"
OJI = "person.oji_udezue"
EZ = "person.ezinne"
PHONE = "device_tracker.oji_phone"
IPAD = "device_tracker.okosisipadmini6_2"
EZ_PHONE = "device_tracker.ez_phone"
DIST = "sensor.madronehaos_oji_udezue_distance"
APPROACH = "zone.near_home"

DAY = datetime(2026, 11, 12, 10, 0, 0, tzinfo=TZ)


def options(**over):
    opts = {
        "security_garage_lockout_enabled": True,
        "security_lockout_entities": [LOCK_A, LOCK_B],
        "security_lock_entities": [BED],
        "security_lock_sweep_exclude": [BED],
        "security_away_lock_enabled": True,
        "security_away_lock_entities": [BED],
        "security_away_lock_persons": [OJI, EZ],
        "security_lockout_distance_sensors": [DIST],
        "security_lockout_approach_zone": APPROACH,
        "security_coordinator_enabled": True,
        "sleep_start_hour": 22,
        "sleep_end_hour": 6,
    }
    opts.update(over)
    return opts


class _Ev:
    def __init__(self, data):
        self.data = data


class FakePC:
    def __init__(self):
        self.data = {}
        self.listeners = []

    def async_add_listener(self, cb, context=None):
        self.listeners.append(cb)
        return lambda: self.listeners.remove(cb) if cb in self.listeners else None

    def tick(self):
        for cb in list(self.listeners):
            cb()


class Rig:
    def __init__(self, w, regime, mgr):
        self.w, self.regime, self.mgr = w, regime, mgr

    # -- inputs ---------------------------------------------------------
    def emit(self, eid, state, attrs, last_changed=None):
        w = self.w
        old = w.hass.states.get(eid)
        new = FakeState(eid, state, attrs, last_changed=last_changed or w.now)
        w.hass.states._s[eid] = new
        ev = _Ev({"entity_id": eid, "old_state": old, "new_state": new})
        for rec in list(w.listeners):
            if rec["active"] and eid in rec["ids"]:
                rec["cb"](ev)

    def fresh(self, pid, state, src):
        """A real edge: the source tracker changes with the person."""
        self.w.seed(src, state, {"source_type": "gps"}, last_changed=self.w.now)
        self.emit(pid, state, {"source": src})

    def stale(self, pid, state, src=IPAD, age_s=4119.0):
        """The blip shape: the person reads ``state`` from a tracker whose
        own state last changed ``age_s`` ago."""
        self.w.seed(src, state, {"source_type": "gps"},
                    last_changed=self.w.now - timedelta(seconds=age_s))
        self.emit(pid, state, {"source": src})

    def attr_refresh(self, pid, src=IPAD):
        """Attribute-only person update (lat/lon/accuracy): same state, the
        person's last_changed is kept (HA semantics)."""
        cur = self.w.hass.states.get(pid)
        self.emit(pid, cur.state, {"source": src, "gps_accuracy": 7},
                  last_changed=cur.last_changed)

    def distance(self, ft):
        self.emit(DIST, str(ft), {"unit_of_measurement": "ft"})

    async def advance(self, s):
        await self.w.advance(s)

    def unlocks(self):
        return self.w.locks_called("unlock")

    def relock(self):
        for ent in (LOCK_A, LOCK_B, BED):
            self.w.seed(ent, "locked")
        self.regime.away_lock_owned = {BED}

    def state_fields(self):
        r = self.regime
        return {
            "last_real": dict(r._last_real),
            "arrival_edges": dict(r._arrival_edges),
            "away_since": dict(r._away_not_home_since),
            "attempted": (r._away_attempted, r._away_attempted_marker),
            "releasing": {k: dict(v) for k, v in r.releasing_set.items()},
            "release_gen": r.release_gen,
            "away_epoch": r._away_release_epoch,
            "owned": set(r.away_lock_owned),
        }

    def hold_timers(self):
        return [t for t in self.w.live_timers()
                if getattr(t["cb"], "func", None) is not None
                and t["cb"].func.__name__ == "_on_hold_confirm"]


async def make_rig(*, opts=None, past_boot=True, start=DAY, pc=None):
    w = World(start, opts if opts is not None else options(),
              entry_type=const.ENTRY_TYPE_COORDINATOR_MANAGER)
    # VACATION: lockouts found locked at boot rebuild as vacation (no
    # morning backstop), so only arrivals release them.
    mgr = SimpleNamespace(house_state="vacation")
    w.hass.data[const.DOMAIN] = {"coordinator_manager": mgr}
    if pc is not None:
        w.hass.data[const.DOMAIN]["person_coordinator"] = pc
    for ent in (LOCK_A, LOCK_B):
        w.seed(ent, "locked")
    w.seed(BED, "unlocked")
    w.seed(PHONE, "not_home", {"source_type": "gps"}, last_changed=start)
    w.seed(IPAD, "home", {"source_type": "gps"}, last_changed=start - timedelta(hours=3))
    w.seed(EZ_PHONE, "not_home", {"source_type": "gps"}, last_changed=start)
    w.seed(OJI, "not_home", {"source": PHONE}, last_changed=start)
    w.seed(EZ, "not_home", {"source": EZ_PHONE}, last_changed=start)
    w.seed(APPROACH, "0", {"friendly_name": "Near Home"})
    w.seed(DIST, "9000", {"unit_of_measurement": "ft"})
    sc = SimpleNamespace(enabled=True, _shutting_down=False, observation_mode=False,
                         _garage_entities=[], decision_logger=None)
    regime = R.LockRegimeController(
        w.hass, sc, now=w.clock, call_later=w.call_later, track_state=w.track_state,
        track_added_domain=w.track_added, track_removed_domain=w.track_removed,
    )
    await regime.async_setup()
    rig = Rig(w, regime, mgr)
    if past_boot:
        # Both listed persons not_home since setup: the away lock engages at
        # setup + 300 s (BED locked + owned) well before the boot window ends.
        await w.advance(601)
        rig.distance(9000)
        w.calls.clear()
        if regime.away_lock_on():
            assert regime.away_lock_owned == {BED}
    return rig


# ============================================================================
# D2: person-edge hold (S1-S5)
# ============================================================================


@pytest.mark.asyncio
async def test_blip_pair_noop_garage():
    rig = await make_rig()
    before = rig.state_fields()
    rig.stale(OJI, "home")
    await settle()
    assert rig.unlocks() == []
    assert OJI in rig.regime._held_edges
    await rig.advance(0.039)
    rig.fresh(OJI, "not_home", PHONE)  # the revert, 39 ms later
    await settle()
    assert rig.regime._held_edges == {}
    assert rig.hold_timers() == []
    await rig.advance(10)
    assert rig.unlocks() == []
    assert rig.state_fields() == before
    assert rig.regime.arrival_holds == 1


@pytest.mark.asyncio
async def test_blip_pair_noop_away_stamp():
    """Wrong build (revert processed through the body as a real leave) moves
    the away-lock outing stamp to the revert time; the pair must not."""
    rig = await make_rig()
    since = rig.regime._away_not_home_since[OJI]
    assert since == DAY.timestamp()
    rig.stale(OJI, "home")
    await rig.advance(0.039)
    rig.fresh(OJI, "not_home", PHONE)
    await settle()
    assert rig.regime._away_not_home_since[OJI] == DAY.timestamp()
    assert rig.regime._last_real.get(OJI) is None


@pytest.mark.asyncio
async def test_fresh_source_releases_same_callback():
    rig = await make_rig()
    rig.fresh(OJI, "home", PHONE)
    # Synchronously, before any await: the unlocks are already in flight.
    assert rig.regime._release_inflight == {LOCK_A, LOCK_B, BED}
    assert rig.regime._held_edges == {}
    await settle()
    assert rig.unlocks() == [LOCK_A, LOCK_B, BED]
    assert rig.regime.arrival_holds == 0


@pytest.mark.asyncio
async def test_stale_persisting_confirms_at_h_edge_ts():
    rig = await make_rig()
    edge_ts = rig.w.now.timestamp()
    rig.stale(OJI, "home")
    await rig.advance(4.9)
    assert rig.unlocks() == []
    await rig.advance(0.2)  # 5.1 s after the edge
    assert rig.unlocks() == [LOCK_A, LOCK_B, BED]
    assert rig.regime.last_action["trigger"] == f"person:{OJI}"
    assert rig.regime._arrival_edges["oji_udezue"] == edge_ts
    assert rig.regime._last_real[OJI] == ("home", edge_ts, False)
    assert rig.regime.arrival_hold_confirms == 1
    assert rig.regime._held_edges == {}


@pytest.mark.asyncio
async def test_hold_cancel_by_other_value():
    rig = await make_rig()
    # (a) stale edge, then `unavailable` inside H: cancelled, no stamp.
    rig.stale(OJI, "home")
    await rig.advance(1)
    rig.emit(OJI, "unavailable", {})
    await rig.advance(10)
    assert rig.unlocks() == []
    assert rig.regime._held_edges == {}
    assert "oji_udezue" not in rig.regime._arrival_edges
    assert rig.regime._last_real.get(OJI) is None
    # (b) stale edge to a zone, then a FRESH home inside H: the home event is
    # processed as from the pre-hold value (not_home), so it is an arrival
    # edge (face-corroboration stamp) and releases in the same callback.
    rig.fresh(OJI, "not_home", PHONE)
    await rig.advance(1)
    rig.stale(OJI, "Work", src=IPAD, age_s=900)
    assert OJI in rig.regime._held_edges
    await rig.advance(1)
    ts = rig.w.now.timestamp()
    rig.fresh(OJI, "home", PHONE)
    assert rig.regime._release_inflight == {LOCK_A, LOCK_B, BED}
    assert rig.regime._arrival_edges["oji_udezue"] == ts


@pytest.mark.asyncio
async def test_teardown_cancels_holds():
    rig = await make_rig()
    rig.stale(OJI, "home")
    assert len(rig.hold_timers()) == 1
    await rig.regime.async_teardown()
    assert rig.hold_timers() == []
    assert rig.regime._held_edges == {}
    await rig.advance(10)
    assert rig.unlocks() == []


@pytest.mark.asyncio
async def test_approach_zone_stale_held():
    rig = await make_rig()
    rig.stale(OJI, "Near Home", age_s=900)
    await settle()
    assert rig.unlocks() == []
    await rig.advance(0.05)
    rig.fresh(OJI, "not_home", PHONE)
    await rig.advance(10)
    assert rig.unlocks() == []
    # A stale approach-zone reading that persists releases at H (zone branch).
    rig.stale(OJI, "Near Home", age_s=900)
    await rig.advance(5.1)
    assert rig.regime.last_action["trigger"] == f"approach_zone:{OJI}"
    assert set(rig.unlocks()) == {LOCK_A, LOCK_B}


@pytest.mark.asyncio
async def test_attribute_only_event_keeps_hold():
    """F1: a same-state `home -> home` event inside H (attribute refresh of
    the stale tracker) neither releases nor restarts the hold."""
    rig = await make_rig()
    edge_ts = rig.w.now.timestamp()
    rig.stale(OJI, "home")
    await rig.advance(1)
    rig.attr_refresh(OJI)
    await settle()
    assert rig.unlocks() == []
    await rig.advance(3.9)  # 4.9 s after the edge
    assert rig.unlocks() == []
    await rig.advance(0.2)  # 5.1 s
    assert rig.unlocks() == [LOCK_A, LOCK_B, BED]
    assert rig.regime._arrival_edges["oji_udezue"] == edge_ts
    await rig.advance(10)
    assert rig.unlocks() == [LOCK_A, LOCK_B, BED]  # once


@pytest.mark.asyncio
async def test_away_dwell_deferred_during_hold():
    """F3: the dwell due inside a hold must not consume the one attempt per
    outing; after the revert the away lock engages within H."""
    rig = await make_rig(past_boot=False, opts=options(security_garage_lockout_enabled=False))
    rig.w.seed(OJI, "home", {"source": PHONE}, last_changed=DAY)
    rig.w.seed(EZ, "home", {"source": EZ_PHONE}, last_changed=DAY)
    await rig.advance(700)
    rig.fresh(OJI, "not_home", PHONE)
    rig.fresh(EZ, "not_home", EZ_PHONE)
    left = rig.w.now
    await rig.advance(299.5)
    rig.stale(OJI, "home")  # blip 0.5 s before the dwell is due
    await rig.advance(0.6)  # the dwell came due inside the hold
    assert rig.w.locks_called("lock") == []
    assert rig.regime._away_attempted is False
    rig.fresh(OJI, "not_home", PHONE)  # revert at dwell + 0.1 s
    assert rig.regime._away_attempted is False
    await rig.advance(5)
    assert rig.w.locks_called("lock") == [BED]
    assert (rig.w.now - left).total_seconds() <= 300 + 5.1


@pytest.mark.asyncio
async def test_boot_window_edge_not_held():
    rig = await make_rig(past_boot=False)
    await rig.advance(10)
    rig.relock()
    rig.stale(OJI, "home")
    assert rig.regime._held_edges == {}
    assert rig.regime._release_inflight == {LOCK_A, LOCK_B, BED}
    await settle()
    assert rig.unlocks() == [LOCK_A, LOCK_B, BED]


@pytest.mark.asyncio
async def test_confirm_rereads_config():
    """F7: an exclusion added inside H applies at confirm."""
    rig = await make_rig(opts=options(security_away_lock_enabled=False,
                                      security_away_lock_persons=[]))
    rig.stale(OJI, "home")
    await rig.advance(2)
    rig.w.cm_entry.options = {**rig.w.cm_entry.options,
                              "security_lockout_excluded_persons": [OJI]}
    await rig.advance(5)
    assert rig.unlocks() == []
    assert rig.regime.arrival_hold_confirms == 1
    assert rig.regime._last_real[OJI][0] == "home"


@pytest.mark.asyncio
async def test_proximity_synthetic_hold_already_home_noop():
    """F6: the person was already home (edge processed); the source later
    falls back to the stale device and the distance jumps to 0. The
    synthetic hold's replay is a garage no-op (no person: release) and
    leaves the edge state untouched; the proximity re-read releases as on
    develop."""
    rig = await make_rig()
    rig.fresh(OJI, "home", PHONE)
    await settle()  # the unlock task registers its read-back
    await rig.advance(30)
    real_after = dict(rig.regime._last_real), dict(rig.regime._arrival_edges)
    rig.attr_refresh(OJI, src=IPAD)  # source switch, same state
    rig.relock()
    rig.regime.away_lock_owned = set()
    rig.w.calls.clear()
    rig.distance(0)
    assert OJI in rig.regime._held_edges
    assert rig.unlocks() == []
    await rig.advance(0.1)
    triggers = [rig.regime.last_action["trigger"]]
    assert triggers == [f"proximity:{DIST}"]
    assert rig.unlocks() == [LOCK_A, LOCK_B]
    assert (dict(rig.regime._last_real), dict(rig.regime._arrival_edges)) == real_after


# ============================================================================
# D3: signal gate (S6-S8)
# ============================================================================


@pytest.mark.asyncio
async def test_geofence_signal_dropped_while_stale():
    rig = await make_rig()
    rig.stale(OJI, "home")
    rig.regime.on_person_arriving({"person_entity": OJI, "source": "geofence"})
    await settle()
    assert rig.unlocks() == []
    assert rig.regime.arrival_signal_held == 1
    await rig.advance(0.05)
    rig.fresh(OJI, "not_home", PHONE)
    await rig.advance(10)
    assert rig.unlocks() == []
    # A fresh-source arrival's geofence signal still releases (EZ was never
    # seen home since setup: really away, M-2 (ii)).
    rig.w.seed(EZ, "home", {"source": EZ_PHONE}, last_changed=rig.w.now)
    rig.w.seed(EZ_PHONE, "home", {}, last_changed=rig.w.now)
    rig.regime.on_person_arriving({"person_entity": EZ, "source": "ble"})
    await settle()
    assert rig.unlocks() == [LOCK_A, LOCK_B, BED]


@pytest.mark.asyncio
async def test_geofence_signal_before_state_listener():
    """HA writes the person before any listener / signal runs: a signal that
    reaches the regime before its own state listener still sees the stale
    source in hass.states."""
    rig = await make_rig()
    rig.w.seed(OJI, "home", {"source": IPAD}, last_changed=rig.w.now)
    rig.regime.on_person_arriving({"person_entity": OJI, "source": "geofence"})
    await settle()
    assert rig.unlocks() == []
    assert rig.regime.arrival_signal_held == 1


@pytest.mark.asyncio
async def test_face_not_corroborated_by_blip():
    rig = await make_rig()
    rig.stale(OJI, "home")
    await rig.advance(0.04)
    rig.fresh(OJI, "not_home", PHONE)
    await rig.advance(20)
    rig.regime.on_person_arriving({"person_entity": OJI, "source": "camera_face"})
    await settle()
    assert rig.unlocks() == []
    assert OJI in rig.regime._pending_faces
    assert "oji_udezue" not in rig.regime._arrival_edges


@pytest.mark.asyncio
async def test_held_face_recheck_blocked_while_stale(monkeypatch):
    monkeypatch.setattr(R.LockRegimeController, "_entry_areas", lambda self: {"garage"})
    pc = FakePC()
    rig = await make_rig(pc=pc)
    await rig.advance(16 * 60)  # EZ really away
    rig.w.calls.clear()
    rig.regime.on_person_arriving({"person_entity": EZ, "source": "camera_face"})
    await settle()
    assert EZ in rig.regime._pending_faces
    rig.stale(EZ, "home", src="device_tracker.ez_ipad")
    assert EZ in rig.regime._held_edges
    pc.data["Ezinne"] = {"method": "bermuda", "location": "Garage", "bermuda_area": "Garage",
                         "previous_location": "away", "last_changed": rig.w.now}
    pc.tick()  # Bermuda entry move corroborates the held face -> _apply_arrival
    await settle()
    assert EZ not in rig.regime._pending_faces
    assert rig.unlocks() == []
    assert rig.regime.arrival_signal_held == 1


# ============================================================================
# D4: proximity gate (S9)
# ============================================================================


@pytest.mark.asyncio
async def test_proximity_blip_held_and_dropped():
    rig = await make_rig()
    rig.stale(OJI, "home")
    rig.distance(0)  # same ms: iPad coordinates
    await settle()
    assert rig.unlocks() == []
    assert rig.regime._held_edges[OJI]["proximity_sids"] == {DIST}
    await rig.advance(0.02)
    rig.distance(9000)
    await rig.advance(0.02)
    rig.fresh(OJI, "not_home", PHONE)
    await rig.advance(10)
    assert rig.unlocks() == []
    assert rig.regime._held_edges == {}


@pytest.mark.asyncio
async def test_proximity_real_approach_instant():
    """11-07 12:13:13 shape: crossing to 978 ft 36 s before the person edge,
    person still not_home -> releases at the crossing."""
    rig = await make_rig()
    rig.distance(977.7)
    assert rig.regime._release_inflight == {LOCK_A, LOCK_B}
    await settle()
    assert rig.unlocks() == [LOCK_A, LOCK_B]
    assert rig.regime._held_edges == {}


@pytest.mark.asyncio
async def test_proximity_confirm_rereads_distance():
    rig = await make_rig()
    # Persisting stale home with the distance back outside R: no proximity
    # release at confirm (only the person edge's own release).
    rig.stale(OJI, "home")
    rig.distance(0)
    await rig.advance(0.05)
    rig.distance(9000)
    await rig.advance(5.1)
    garage = [c for c in rig.unlocks() if c != BED]
    assert garage == [LOCK_A, LOCK_B]
    assert rig.regime.last_action["trigger"] == f"person:{OJI}"
    # Same, with the distance still inside R at confirm: proximity releases.
    rig.fresh(OJI, "not_home", PHONE)
    await settle()
    await rig.advance(30)
    rig.relock()
    rig.w.calls.clear()
    rig.stale(OJI, "home")
    rig.distance(0)
    await rig.advance(5.1)
    assert rig.regime.last_action["trigger"] == f"proximity:{DIST}"


# ============================================================================
# D5: knob
# ============================================================================


@pytest.mark.asyncio
async def test_hold_zero_releases_blip_like_develop():
    rig = await make_rig(opts=options(garage_lockout_arrival_hold_s=0))
    rig.stale(OJI, "home")
    assert rig.regime._release_inflight == {LOCK_A, LOCK_B, BED}
    assert rig.regime._held_edges == {}


def test_arrival_hold_number_roundtrip():
    num = load("number")
    ents = num._build_security_lockout_numbers(None, SimpleNamespace(data={}, options={}))
    by_id = {e.entity_id: e for e in ents}
    ent = by_id["number.ura_garage_lockout_arrival_hold"]
    assert ent.native_value == 5.0
    assert (ent.native_min_value, ent.native_max_value, ent.native_step) == (0.0, 60.0, 1.0)
    assert ent.native_unit_of_measurement == "s"
    assert ent.unique_id == "universal_room_automation_garage_lockout_arrival_hold_s"
    assert ("universal_room_automation", "security_coordinator") in ent.device_info["identifiers"]
    entry = SimpleNamespace(data={}, options={"garage_lockout_arrival_hold_s": 12})
    ents = num._build_security_lockout_numbers(None, entry)
    assert {e.entity_id: e for e in ents}["number.ura_garage_lockout_arrival_hold"].native_value == 12.0


@pytest.mark.asyncio
async def test_arrival_hold_number_set_is_read_live():
    """The Number writes entry.options; the regime reads the key live."""
    num = load("number")
    rig = await make_rig()
    ents = num._build_security_lockout_numbers(None, rig.w.cm_entry)
    ent = {e.entity_id: e for e in ents}["number.ura_garage_lockout_arrival_hold"]
    ent.hass = rig.w.hass
    ent.async_write_ha_state = lambda: None
    await ent.async_set_native_value(0)
    assert rig.w.cm_entry.options["garage_lockout_arrival_hold_s"] == 0.0
    rig.stale(OJI, "home")
    assert rig.regime._held_edges == {}
    assert rig.regime._release_inflight == {LOCK_A, LOCK_B, BED}


def test_arrival_hold_key_in_reload_suppress_and_no_live_attr():
    init = load("__init__")
    assert "garage_lockout_arrival_hold_s" in init.OPTIONS_RELOAD_SUPPRESS_KEYS
    assert "garage_lockout_arrival_hold_s" in init._NO_LIVE_ATTR_KEYS


@pytest.mark.asyncio
async def test_snapshot_hold_counters():
    rig = await make_rig()
    snap = rig.regime.snapshot()
    assert snap["lock_regime_arrival_holds"] == 0
    assert snap["lock_regime_held_edges"] == []
    rig.stale(OJI, "home")
    rig.regime.on_person_arriving({"person_entity": OJI, "source": "geofence"})
    snap = rig.regime.snapshot()
    assert snap["lock_regime_arrival_holds"] == 1
    assert snap["lock_regime_arrival_signal_held"] == 1
    assert snap["lock_regime_held_edges"] == [OJI]
    await rig.advance(5.1)
    assert rig.regime.snapshot()["lock_regime_arrival_hold_confirms"] == 1
