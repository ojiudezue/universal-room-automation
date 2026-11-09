"""LOCK-REGIME-FACE-ARRIVAL-CORROBORATION-1 — behavioural tests.

A ``camera_face`` SIGNAL_PERSON_ARRIVING releases the garage lockouts / the
away lock only with an independent arrival edge for the SAME person (live
``person.*`` not_home -> home, or a Bermuda move into an entry area) inside
the D10.5 window (120 s) and outside the post-boot exclusion (600 s).
``_really_away`` still applies. Non-face sources are unchanged.

Every test drives the REAL lock regime (and the SC bridge where noted) with
the injected fake clock / trackers from _lockout_harness; assertions are on
the recorded ``lock.unlock`` service calls. Boundaries are literals (120 /
121, 599 / 601), never the imported constants.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from _lockout_harness import TZ, World, load, settle

const = load("const")
R = load("domain_coordinators.security_lock_regime")
sec = load("domain_coordinators.security")
AE = load("arrival_edges")
TV = load("transit_validator")

LOCK_A = "lock.konnected_f0f5bd523b00_lock"
LOCK_B = "lock.ratgdov25i_dbfe2a_lock_remotes"
COVER_A = "cover.konnected_f0f5bd523b00_garage_door"
DOOR_LOCK = "lock.doorlock_kwikset_zwave_frontentry"
BED = "lock.master_bedroom_lock"
EZ = "person.ezinne"
OJI = "person.oji_udezue"
KIOSK = "person.wall_kiosk"

GARAGE_CAM = "binary_sensor.garage_a_person_occupancy"
HALL_CAM = "camera.garage_hallway"
AREAS = {GARAGE_CAM: "garage", HALL_CAM: "garage_hallway"}

NIGHT = datetime(2026, 11, 7, 23, 0, 0, tzinfo=TZ)


def options(**over):
    opts = {
        "security_garage_lockout_enabled": True,
        "security_lockout_entities": [LOCK_A, LOCK_B],
        "security_lock_entities": [DOOR_LOCK, BED],
        "security_lock_sweep_exclude": [BED],
        "security_garage_entities": [COVER_A],
        "security_lockout_excluded_persons": [KIOSK],
        "security_away_lock_enabled": False,
        "security_away_lock_entities": [BED],
        "security_away_lock_persons": [OJI, EZ],
        "security_coordinator_enabled": True,
        "sleep_start_hour": 22,
        "sleep_end_hour": 6,
    }
    opts.update(over)
    return opts


def real_tracker(egress=(GARAGE_CAM,), neighbours=None):
    """A REAL EgressDirectionTracker (the object stored at
    hass.data[DOMAIN]["egress_tracker"], __init__.py:3461) with its own
    attribute layout -- not a stand-in (LOCK-ENTRY-AREAS-WRONG-OBJECT-1)."""
    t = TV.EgressDirectionTracker(None)
    t._egress_entities = list(egress)
    t._interior_neighbours_by_group = (
        {"garage": [HALL_CAM]} if neighbours is None else neighbours)
    return t


def install_trackers(data, tracker):
    """Store the tracker under its real key and a REAL TransitValidator under
    its own key, so a consumer reading the wrong key sees the wrong object."""
    data["egress_tracker"] = tracker
    data["transit_validator"] = TV.TransitValidator(None)


class Rig:
    def __init__(self, w, sc, regime):
        self.w, self.sc, self.regime = w, sc, regime

    async def person(self, pid, state):
        self.w.set_state(pid, state)
        await settle()

    def unlocks(self):
        return self.w.locks_called("unlock")

    def ble(self, name, *, location, prev="away", age_s=10, tick=False):
        """PersonCoordinator record: Bermuda moved ``name`` prev -> location."""
        pc = self.w.hass.data[const.DOMAIN].setdefault("person_coordinator", FakePC())
        pc.data[name] = {
            "method": "bermuda", "location": location, "bermuda_area": location,
            "previous_location": prev,
            "last_changed": self.w.now - timedelta(seconds=age_s),
        }
        if tick:
            pc.tick()

    def settle_tick(self, name):
        """Next PersonCoordinator tick: previous_location := location (the
        move is no longer visible in the live data, person_coordinator:1083)."""
        pc = self.w.hass.data[const.DOMAIN]["person_coordinator"]
        rec = pc.data[name]
        rec["previous_location"] = rec["location"]
        pc.tick()

    async def face(self, pid, via_sc=True):
        payload = {"person_entity": pid, "source": "camera_face"}
        if via_sc:
            self.sc._handle_person_arriving_signal(payload)
        else:
            self.regime.on_person_arriving(payload)
        await settle()


class FakePC:
    """PersonCoordinator double: `.data` + DataUpdateCoordinator listeners."""

    def __init__(self):
        self.data = {}
        self.listeners = []

    adds = 0

    def async_add_listener(self, cb, context=None):
        self.adds += 1
        self.listeners.append(cb)
        return lambda: self.listeners.remove(cb) if cb in self.listeners else None

    def tick(self):
        for cb in list(self.listeners):
            cb()


@pytest.fixture
def areas(monkeypatch):
    monkeypatch.setattr(R.LockRegimeController, "_area_of_entity",
                        lambda self, e: AREAS.get(e, ""))


async def make_rig(*, opts=None, persons=None, lockouts="locked", bed="unlocked",
                   past_boot=True, with_tv=True, pc=None):
    w = World(NIGHT, opts if opts is not None else options(),
              entry_type=const.ENTRY_TYPE_COORDINATOR_MANAGER)
    w.hass.data[const.DOMAIN] = {"coordinator_manager": SimpleNamespace(house_state="home_night")}
    if pc is not None:
        w.hass.data[const.DOMAIN]["person_coordinator"] = pc
    if with_tv:
        install_trackers(w.hass.data[const.DOMAIN], real_tracker())
    for ent in (LOCK_A, LOCK_B):
        w.seed(ent, lockouts)
    w.seed(DOOR_LOCK, "locked")
    w.seed(BED, bed)
    w.seed(COVER_A, "closed", {"device_class": "garage"})
    for pid, st in (persons or {EZ: "home", OJI: "home", KIOSK: "unknown"}).items():
        w.seed(pid, st, last_changed=NIGHT)
    sc = sec.SecurityCoordinator(w.hass, lock_entities=[DOOR_LOCK, BED],
                                 garage_entities=[COVER_A])
    regime = R.LockRegimeController(
        w.hass, sc, now=w.clock, call_later=w.call_later, track_state=w.track_state,
        track_added_domain=w.track_added, track_removed_domain=w.track_removed,
    )
    sc._lock_regime = regime
    await regime.async_setup()
    rig = Rig(w, sc, regime)
    if past_boot:
        await w.advance(601)
        w.calls.clear()
    return rig


async def ez_really_away(rig, minutes=16):
    await rig.person(EZ, "not_home")
    await rig.w.advance(minutes * 60)
    rig.w.calls.clear()


# ============================================================================
# Face + same-person independent arrival -> release
# ============================================================================


@pytest.mark.asyncio
async def test_face_plus_same_person_ble_entry_arrival_releases(areas):
    rig = await make_rig()
    await ez_really_away(rig)
    rig.ble("Ezinne", location="Garage")
    await rig.face(EZ)
    assert rig.unlocks() == [LOCK_A, LOCK_B]


@pytest.mark.asyncio
async def test_face_plus_ble_into_configured_neighbour_area_releases(areas):
    """Entry areas include the door-interior neighbours' areas."""
    rig = await make_rig()
    await ez_really_away(rig)
    rig.ble("Ezinne", location="Garage Hallway")
    await rig.face(EZ)
    assert rig.unlocks() == [LOCK_A, LOCK_B]


@pytest.mark.asyncio
async def test_face_plus_same_person_tracker_arrival_releases(areas):
    """Tracker leg: the live not_home -> home edge is recorded and
    corroborates the face. In the lock regime that edge ALSO releases
    through P1 by itself and then `_really_away` reads False, so the face
    path adds no second release (documented consequence)."""
    rig = await make_rig()
    await ez_really_away(rig)
    await rig.person(EZ, "home")  # live not_home -> home
    assert rig.unlocks() == [LOCK_A, LOCK_B]
    await rig.w.advance(30)
    assert rig.regime._face_arrival_corroborated(EZ) is True
    rig.w.calls.clear()
    await rig.face(EZ)
    assert rig.unlocks() == []  # already released; face path is a no-op


@pytest.mark.asyncio
async def test_tracker_edge_corroborates_within_window_only(areas):
    rig = await make_rig()
    await ez_really_away(rig)
    await rig.person(EZ, "home")
    await rig.w.advance(120)
    assert rig.regime._face_arrival_corroborated(EZ) is True
    await rig.w.advance(1)
    assert rig.regime._face_arrival_corroborated(EZ) is False


@pytest.mark.asyncio
async def test_restore_and_flap_edges_are_not_tracker_arrivals(areas):
    rig = await make_rig(persons={OJI: "home", KIOSK: "unknown"})
    rig.w.set_state(EZ, "home")  # old None: restore
    await rig.person(EZ, "unavailable")
    await rig.person(EZ, "home")  # unavailable -> home flap
    assert rig.regime._face_arrival_corroborated(EZ) is False


# ============================================================================
# Face without corroboration -> NO release
# ============================================================================


@pytest.mark.asyncio
async def test_face_only_person_really_away_no_release(areas):
    """10-24 shape: face names a resident who IS away, no arrival edge."""
    rig = await make_rig()
    await ez_really_away(rig, minutes=60)
    await rig.face(EZ)
    assert rig.unlocks() == []


@pytest.mark.asyncio
async def test_face_only_direct_regime_call_no_release(areas):
    rig = await make_rig()
    await ez_really_away(rig)
    await rig.face(EZ, via_sc=False)
    assert rig.unlocks() == []


@pytest.mark.asyncio
async def test_face_payload_object_source_is_gated(areas):
    rig = await make_rig()
    await ez_really_away(rig)
    rig.regime.on_person_arriving(SimpleNamespace(person_entity=EZ, source="camera_face"))
    await settle()
    assert rig.unlocks() == []


@pytest.mark.asyncio
async def test_face_plus_other_person_ble_arrival_no_release(areas):
    rig = await make_rig()
    await ez_really_away(rig)
    rig.ble("Oji Udezue", location="Garage")
    await rig.face(EZ)
    assert rig.unlocks() == []


@pytest.mark.asyncio
async def test_face_plus_other_person_tracker_arrival_no_release(areas):
    rig = await make_rig(persons={EZ: "home", OJI: "not_home", KIOSK: "unknown"})
    await ez_really_away(rig)
    rig.w.set_state(LOCK_A, "locked")
    rig.w.set_state(LOCK_B, "locked")
    await rig.person(OJI, "home")  # Oji's real arrival releases via P1 ...
    rig.w.set_state(LOCK_A, "locked")
    rig.w.set_state(LOCK_B, "locked")
    rig.w.calls.clear()
    await rig.face(EZ)  # ... but does not corroborate a face naming Ezinne
    assert rig.unlocks() == []


@pytest.mark.asyncio
async def test_face_plus_interior_ble_hop_no_release(areas):
    rig = await make_rig()
    await ez_really_away(rig)
    rig.ble("Ezinne", location="Kitchen", prev="Family Room")
    await rig.face(EZ)
    assert rig.unlocks() == []


@pytest.mark.asyncio
async def test_face_plus_ble_at_entry_without_move_no_release(areas):
    rig = await make_rig()
    await ez_really_away(rig)
    rig.ble("Ezinne", location="Garage", prev="Garage")
    await rig.face(EZ)
    assert rig.unlocks() == []


@pytest.mark.asyncio
async def test_face_plus_ble_entry_no_transit_validator_no_release(areas):
    """No egress config -> no entry areas -> the Bermuda leg never counts."""
    rig = await make_rig(with_tv=False)
    await ez_really_away(rig)
    rig.ble("Ezinne", location="Garage")
    await rig.face(EZ)
    assert rig.unlocks() == []


@pytest.mark.parametrize("age,expected", [(119, True), (120, True), (121, False)])
@pytest.mark.asyncio
async def test_face_plus_ble_window_boundary(areas, age, expected):
    rig = await make_rig()
    await ez_really_away(rig)
    rig.ble("Ezinne", location="Garage", age_s=age)
    await rig.face(EZ)
    assert rig.unlocks() == ([LOCK_A, LOCK_B] if expected else [])


@pytest.mark.asyncio
async def test_face_still_needs_really_away(areas):
    """_really_away kept: corroborated face for a person home all along
    (real transition seen, home for hours) does not release."""
    rig = await make_rig()
    await rig.person(EZ, "Work")
    await rig.person(EZ, "home")
    await rig.w.advance(3 * 3600)
    rig.w.calls.clear()
    rig.ble("Ezinne", location="Garage")
    await rig.face(EZ)
    assert rig.unlocks() == []


# ============================================================================
# Post-boot exclusion
# ============================================================================


@pytest.mark.asyncio
async def test_arrival_inside_boot_exclusion_no_release(areas):
    """60 s after setup (_really_away is True in the boot window by M-2 (i)):
    a Bermuda move and a tracker edge inside the exclusion are ignored."""
    rig = await make_rig(past_boot=False, persons={EZ: "not_home", OJI: "home",
                                                    KIOSK: "unknown"})
    await rig.w.advance(30)
    await rig.person(EZ, "home")
    await rig.person(EZ, "not_home")  # bounce back out
    rig.w.calls.clear()
    await rig.w.advance(30)
    rig.ble("Ezinne", location="Garage", age_s=5)
    await rig.face(EZ)
    assert rig.unlocks() == []


@pytest.mark.parametrize("edge_at,expected", [(599, False), (601, True)])
@pytest.mark.asyncio
async def test_boot_exclusion_boundary(areas, edge_at, expected):
    """Bermuda move at setup+edge_at, face at setup+602 (inside the 120 s
    window either way): only the move after the 600 s exclusion counts."""
    rig = await make_rig(past_boot=False, persons={EZ: "not_home", OJI: "home",
                                                    KIOSK: "unknown"})
    await rig.w.advance(602)
    rig.w.calls.clear()
    rig.ble("Ezinne", location="Garage", age_s=602 - edge_at)
    await rig.face(EZ)
    assert rig.unlocks() == ([LOCK_A, LOCK_B] if expected else [])


# ============================================================================
# Away lock (master_bedroom_lock) follows the same rule
# ============================================================================


async def _away_engaged(pc=None):
    rig = await make_rig(opts=options(security_garage_lockout_enabled=False,
                                      security_away_lock_enabled=True),
                         lockouts="unlocked", bed="unlocked", pc=pc)
    await rig.person(OJI, "not_home")
    await rig.person(EZ, "not_home")
    await rig.w.advance(301)
    await rig.w.advance(21)  # read-back -> owned
    assert rig.regime.away_lock_owned == {BED}
    await rig.w.advance(1800)
    rig.w.calls.clear()
    return rig


@pytest.mark.asyncio
async def test_away_lock_face_only_no_release(areas):
    rig = await _away_engaged()
    await rig.face(EZ)
    assert rig.unlocks() == []
    assert rig.regime.away_lock_owned == {BED}


@pytest.mark.asyncio
async def test_away_lock_face_plus_ble_entry_releases(areas):
    rig = await _away_engaged()
    rig.ble("Ezinne", location="Garage")
    await rig.face(EZ)
    assert rig.unlocks() == [BED]


# ============================================================================
# Non-face sources unchanged
# ============================================================================


@pytest.mark.parametrize("source", ["ble", "geofence", None])
@pytest.mark.asyncio
async def test_non_face_sources_release_without_corroboration(areas, source):
    rig = await make_rig()
    await ez_really_away(rig)
    payload = {"person_entity": EZ}
    if source is not None:
        payload["source"] = source
    rig.sc._handle_person_arriving_signal(payload)
    await settle()
    assert rig.unlocks() == [LOCK_A, LOCK_B]


@pytest.mark.parametrize("source", ["ble", "geofence"])
@pytest.mark.asyncio
async def test_away_lock_non_face_sources_release(areas, source):
    rig = await _away_engaged()
    rig.regime.on_person_arriving({"person_entity": EZ, "source": source})
    await settle()
    assert rig.unlocks() == [BED]


@pytest.mark.asyncio
async def test_not_home_to_zone_edge_is_not_a_tracker_arrival(areas):
    rig = await make_rig()
    await ez_really_away(rig)
    await rig.person(EZ, "Work")  # not_home -> named zone: not an arrival
    assert rig.regime._face_arrival_corroborated(EZ) is False


@pytest.mark.asyncio
async def test_non_bermuda_record_does_not_corroborate(areas):
    rig = await make_rig()
    await ez_really_away(rig)
    rig.ble("Ezinne", location="Garage")
    rig.w.hass.data[const.DOMAIN]["person_coordinator"].data["Ezinne"]["method"] = "gps"
    await rig.face(EZ)
    assert rig.unlocks() == []


@pytest.mark.asyncio
async def test_window_zero_face_never_releases(areas, monkeypatch):
    monkeypatch.setattr(const, "PERIMETER_EGRESS_FACE_NONFACE_WINDOW_S", 0)
    rig = await make_rig()
    await ez_really_away(rig)
    rig.ble("Ezinne", location="Garage", age_s=0)
    await rig.face(EZ)
    assert rig.unlocks() == []


@pytest.mark.asyncio
async def test_not_set_up_never_corroborates(areas):
    w = World(NIGHT, options(), entry_type=const.ENTRY_TYPE_COORDINATOR_MANAGER)
    w.hass.data[const.DOMAIN] = {"person_coordinator": SimpleNamespace(data={"Ezinne": {
        "method": "bermuda", "location": "Garage", "bermuda_area": "Garage",
        "previous_location": "away", "last_changed": NIGHT}}),
        "egress_tracker": real_tracker(neighbours={}),
        "transit_validator": TV.TransitValidator(None)}
    regime = R.LockRegimeController(
        w.hass, SimpleNamespace(), now=w.clock, call_later=w.call_later,
        track_state=w.track_state, track_added_domain=w.track_added,
        track_removed_domain=w.track_removed,
    )
    assert regime._face_arrival_corroborated(EZ) is False


# ============================================================================
# Review A MED-1: Bermuda move stamps (move before face) + face-first re-check
# ============================================================================


@pytest.mark.parametrize("before,expected", [(119, True), (120, True), (121, False)])
@pytest.mark.asyncio
async def test_move_before_face_survives_next_tick(areas, before, expected):
    """The move is only in the live data for one tick; the stamp keeps it
    for the window."""
    rig = await make_rig(pc=FakePC())
    await ez_really_away(rig)
    rig.ble("Ezinne", location="Garage", age_s=0, tick=True)  # move at T0
    rig.settle_tick("Ezinne")  # next tick: move gone from live data
    await rig.w.advance(before)
    await rig.face(EZ)
    assert rig.unlocks() == ([LOCK_A, LOCK_B] if expected else [])


@pytest.mark.parametrize("after,expected", [(60, True), (120, True), (121, False)])
@pytest.mark.asyncio
async def test_face_first_then_entry_move_rechecks(areas, after, expected):
    rig = await make_rig(pc=FakePC())
    await ez_really_away(rig)
    await rig.face(EZ)  # held: no edge yet
    assert rig.unlocks() == []
    await rig.w.advance(after)
    rig.ble("Ezinne", location="Garage", age_s=0, tick=True)
    await settle()
    assert rig.unlocks() == ([LOCK_A, LOCK_B] if expected else [])


@pytest.mark.asyncio
async def test_face_first_recheck_happens_once(areas):
    rig = await make_rig(pc=FakePC())
    await ez_really_away(rig)
    await rig.face(EZ)
    await rig.w.advance(20)
    rig.ble("Ezinne", location="Kitchen", age_s=0, tick=True)  # not an entry area
    await rig.w.advance(20)
    rig.ble("Ezinne", location="Garage", prev="Kitchen", age_s=0, tick=True)
    await settle()
    assert rig.unlocks() == []
    assert EZ not in rig.regime._pending_faces


@pytest.mark.asyncio
async def test_face_first_other_person_move_no_recheck(areas):
    rig = await make_rig(pc=FakePC())
    await ez_really_away(rig)
    await rig.face(EZ)
    await rig.w.advance(30)
    rig.ble("Oji Udezue", location="Garage", age_s=0, tick=True)
    await settle()
    assert rig.unlocks() == []
    assert EZ in rig.regime._pending_faces


@pytest.mark.asyncio
async def test_face_first_recheck_through_away_lock(areas):
    rig = await _away_engaged(pc=FakePC())
    await rig.face(EZ)
    await rig.w.advance(40)
    rig.ble("Ezinne", location="Garage", age_s=0, tick=True)
    await settle()
    assert rig.unlocks() == [BED]


@pytest.mark.asyncio
async def test_pc_listener_follows_replacement_and_teardown(areas):
    old = FakePC()
    rig = await make_rig(pc=old)
    assert len(old.listeners) == 1
    new = FakePC()
    rig.w.hass.data[const.DOMAIN]["person_coordinator"] = new
    await rig.person(EZ, "not_home")  # any person event re-resolves the PC
    assert old.listeners == [] and len(new.listeners) == 1
    await rig.regime.async_teardown()
    assert new.listeners == []


@pytest.mark.asyncio
async def test_pc_listener_registered_at_setup_once(areas):
    pc = FakePC()
    rig = await make_rig(pc=pc, past_boot=False)
    assert pc.adds == 1 and len(pc.listeners) == 1  # at setup, before any event
    await rig.person(EZ, "not_home")
    await rig.person(EZ, "Work")
    await rig.face(EZ)
    assert pc.adds == 1  # same PC: no re-subscribe churn


@pytest.mark.asyncio
async def test_held_face_expires_after_window(areas):
    rig = await make_rig(pc=FakePC())
    await ez_really_away(rig)
    await rig.face(EZ)
    await rig.w.advance(121)
    rig.ble("Oji Udezue", location="Garage", age_s=0, tick=True)  # any PC tick
    assert EZ not in rig.regime._pending_faces


@pytest.mark.asyncio
async def test_recheck_judged_at_face_time_for_late_tick(areas):
    """A move 100 s BEFORE the face that the PersonCoordinator only reports
    119 s after it: inside the window of the face, so it releases."""
    rig = await make_rig(pc=FakePC())
    await ez_really_away(rig)
    await rig.face(EZ)
    await rig.w.advance(119)
    rig.ble("Ezinne", location="Garage", age_s=219, tick=True)
    await settle()
    assert rig.unlocks() == [LOCK_A, LOCK_B]


def test_record_bermuda_moves_dedupes_and_caps():
    stamps = {}
    rec = {"method": "bermuda", "location": "Garage", "bermuda_area": "Garage",
           "previous_location": "away", "last_changed": NIGHT}
    assert AE.record_bermuda_moves({"Ezinne": dict(rec)}, stamps) == {"ezinne"}
    assert AE.record_bermuda_moves({"Ezinne": dict(rec)}, stamps) == set()
    for i in range(1, 12):
        AE.record_bermuda_moves(
            {"Ezinne": dict(rec, last_changed=NIGHT + timedelta(seconds=i))}, stamps)
    assert len(stamps["ezinne"]) == 8
    assert AE.record_bermuda_moves(
        {"Ezinne": dict(rec, previous_location="Garage")}, {}) == set()
    assert AE.record_bermuda_moves({"Ezinne": dict(rec, method="gps")}, {}) == set()


# ============================================================================
# Review A MED-2: lock-side boot-exclusion floor
# ============================================================================


@pytest.mark.asyncio
async def test_boot_floor_holds_when_perimeter_exclusion_is_zero(areas, monkeypatch):
    """Review repro: perimeter exclusion retuned to 0; HA restart; Bermuda
    restores the person into an entry area (boot-stamped move); a face of
    that person 60 s after setup -> still NO unlock."""
    monkeypatch.setattr(const, "PERIMETER_EGRESS_ARRIVAL_BOOT_EXCLUDE_S", 0)
    rig = await make_rig(past_boot=False, pc=FakePC(),
                         persons={EZ: "not_home", OJI: "home", KIOSK: "unknown"})
    await rig.w.advance(30)
    rig.ble("Ezinne", location="Garage", prev="unknown", age_s=0, tick=True)
    await rig.w.advance(30)
    rig.w.calls.clear()
    await rig.face(EZ)
    assert rig.unlocks() == []


@pytest.mark.parametrize("edge_at,expected", [(599, False), (601, True)])
@pytest.mark.asyncio
async def test_boot_floor_boundary_with_zero_perimeter_exclusion(areas, monkeypatch,
                                                                edge_at, expected):
    monkeypatch.setattr(const, "PERIMETER_EGRESS_ARRIVAL_BOOT_EXCLUDE_S", 0)
    rig = await make_rig(past_boot=False, persons={EZ: "not_home", OJI: "home",
                                                    KIOSK: "unknown"})
    await rig.w.advance(602)
    rig.w.calls.clear()
    rig.ble("Ezinne", location="Garage", age_s=602 - edge_at)
    await rig.face(EZ)
    assert rig.unlocks() == ([LOCK_A, LOCK_B] if expected else [])


# ============================================================================
# Shared helper: entry areas
# ============================================================================


def test_door_entry_areas_egress_and_neighbours():
    tv = SimpleNamespace(_egress_entities=["e1"],
                         _interior_neighbours_by_group={"g": ["n1"], "h": ["n2"]})
    got = AE.door_entry_areas(tv, {"e1": "garage", "n1": "foyer", "n2": ""}.get)
    assert got == {"garage", "foyer"}


def test_door_entry_areas_none_validator_empty():
    assert AE.door_entry_areas(None, lambda e: "x") == set()


# ============================================================================
# LOCK-ENTRY-AREAS-WRONG-OBJECT-1: entry areas come from the EgressDirectionTracker
# ============================================================================


@pytest.mark.asyncio
async def test_entry_areas_read_from_egress_tracker(areas):
    """Enclosing-method anchor: with the real tracker at "egress_tracker" and
    a real TransitValidator at "transit_validator", the entry areas are the
    egress camera's area plus the configured neighbour's area."""
    rig = await make_rig()
    assert rig.regime._entry_areas() == {"garage", "garage_hallway"}


@pytest.mark.asyncio
async def test_neighbour_area_bermuda_move_releases_via_tracker(areas):
    """End-to-end: a Bermuda move into the neighbour-only area (hallway)
    corroborates the face -- only possible if the neighbour map is read
    from the tracker."""
    rig = await make_rig()
    await ez_really_away(rig)
    rig.ble("Ezinne", location="Garage Hallway", age_s=0)
    await rig.face(EZ)
    assert rig.unlocks() == [LOCK_A, LOCK_B]
