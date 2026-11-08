"""SC-LOCK-REGIME-DOOR-LOCKS-1 D3/D4 — the away lock (lock regime policy 2).

Plan: docs/planning/PLANNING_sc_lock_exclude_and_door_regime.md rev 3 (D3 +
"D3 rev 3 binding amendments" + "Build DO / DON'T"). Every test drives the
REAL LockRegimeController / SecurityCoordinator / switch entity through the
injected fake clock, timers and trackers of _lockout_harness, and asserts on
the recorded hass.services.async_call stream. No source greps.

Invariants: INV-X2 (engage only when every listed person reads exactly
not_home for >= the dwell, kill switch on, entity excluded, SC running, not
observation, entity unlocked), INV-X3 (release unlocks only owned or
in-flight). Boundaries are hardcoded literals (300 s dwell, 20 s read-back),
never imported from const.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from _lockout_harness import TZ, World, load, settle

const = load("const")
R = load("domain_coordinators.security_lock_regime")
sec = load("domain_coordinators.security")

BED = "lock.master_bedroom_lock"
DOOR = "lock.doorlock_kwikset_zwave_frontentry"
LOCK_A = "lock.konnected_f0f5bd523b00_lock"
LOCK_B = "lock.ratgdov25i_dbfe2a_lock_remotes"
COVER_A = "cover.konnected_f0f5bd523b00_garage_door"
OJI = "person.oji_udezue"
EZ = "person.ezinne"
ZIRI = "person.ziri"
KIOSK = "person.wall_kiosk"

DAY = datetime(2026, 11, 7, 10, 0, 0, tzinfo=TZ)
NIGHT = datetime(2026, 11, 7, 23, 0, 0, tzinfo=TZ)


def options(**over):
    opts = {
        "security_garage_lockout_enabled": False,
        "security_lockout_entities": [LOCK_A, LOCK_B],
        "security_lock_entities": [DOOR, BED],
        "security_lock_sweep_exclude": [BED],
        "security_away_lock_enabled": True,
        "security_away_lock_entities": [BED],
        "security_away_lock_persons": [OJI, EZ],
        "security_garage_entities": [COVER_A],
        "security_lockout_excluded_persons": [KIOSK],
        "security_coordinator_enabled": True,
        "sleep_start_hour": 22,
        "sleep_end_hour": 6,
    }
    opts.update(over)
    return opts


class MemStore:
    """Store double: records the last payload produced by the data func."""

    def __init__(self, data=None):
        self.data = data
        self.saved = None
        self.saves = 0

    async def async_load(self):
        return self.data

    def async_delay_save(self, fn, delay):
        self.saved = fn()
        self.saves += 1


class NM:
    def __init__(self):
        self.notes = []

    async def async_notify(self, **kw):
        self.notes.append(kw)


class Rig:
    def __init__(self, w, sc, regime, mgr, nm):
        self.w, self.sc, self.regime, self.mgr, self.nm = w, sc, regime, mgr, nm

    async def person(self, pid, state):
        self.w.set_state(pid, state)
        await settle()

    async def edge(self, new):
        old = self.mgr.house_state
        self.mgr.house_state = new
        self.sc._on_house_state_changed_signal(
            {"old_state": old, "new_state": new, "trigger": "t", "confidence": 1.0}
        )
        await settle()

    def locks(self):
        return self.w.locks_called("lock")

    def unlocks(self):
        return self.w.locks_called("unlock")

    async def both_out(self, dwell=301):
        await self.person(OJI, "not_home")
        await self.person(EZ, "not_home")
        await self.w.advance(dwell)


async def make_rig(*, start=DAY, opts=None, persons=None, bed="unlocked",
                   lockouts="unlocked", store=None, past_boot=True, house="home_day"):
    w = World(start, opts if opts is not None else options(),
              entry_type=const.ENTRY_TYPE_COORDINATOR_MANAGER)
    mgr = SimpleNamespace(house_state=house)
    nm = NM()
    w.hass.data[const.DOMAIN] = {"coordinator_manager": mgr, "notification_manager": nm}
    w.seed(BED, bed, {"friendly_name": "Master Bedroom Lock"})
    w.seed(DOOR, "locked")
    for ent in (LOCK_A, LOCK_B):
        w.seed(ent, lockouts)
    w.seed(COVER_A, "closed", {"device_class": "garage"})
    for pid, st in (persons or {OJI: "home", EZ: "home", KIOSK: "unknown"}).items():
        w.seed(pid, st, last_changed=start)
    sc = sec.SecurityCoordinator(w.hass, lock_entities=[DOOR, BED], garage_entities=[COVER_A])
    regime = R.LockRegimeController(
        w.hass, sc, now=w.clock, call_later=w.call_later, track_state=w.track_state,
        track_added_domain=w.track_added, track_removed_domain=w.track_removed,
        store=store,
    )
    sc._lock_regime = regime
    await regime.async_setup()
    rig = Rig(w, sc, regime, mgr, nm)
    if past_boot:
        await w.advance(601)
        w.calls.clear()
    return rig


# ============================================================================
# Engage (INV-X2)
# ============================================================================


@pytest.mark.asyncio
async def test_engage_when_all_away_after_dwell():
    rig = await make_rig()
    await rig.both_out()
    assert rig.locks() == [BED]
    await rig.w.advance(21)  # read-back
    assert rig.regime.away_lock_owned == {BED}
    assert rig.regime.away_lock_last_action["action"] == "engage"


@pytest.mark.asyncio
async def test_no_engage_one_home():
    rig = await make_rig()
    await rig.person(OJI, "not_home")
    await rig.w.advance(3600)
    assert rig.locks() == []


@pytest.mark.asyncio
async def test_no_engage_named_zone():
    rig = await make_rig()
    await rig.person(OJI, "Work")
    await rig.person(EZ, "not_home")
    await rig.w.advance(3600)
    assert rig.locks() == []


@pytest.mark.asyncio
async def test_no_engage_unknown_state():
    rig = await make_rig()
    await rig.person(OJI, "not_home")
    await rig.person(EZ, "unavailable")
    await rig.w.advance(3600)
    assert rig.locks() == []


@pytest.mark.asyncio
async def test_no_engage_before_dwell():
    rig = await make_rig()
    await rig.person(OJI, "not_home")
    await rig.person(EZ, "not_home")
    await rig.w.advance(299)
    assert rig.locks() == []
    await rig.w.advance(2)  # 301 s
    assert rig.locks() == [BED]


@pytest.mark.asyncio
async def test_dwell_counts_from_last_person_out():
    rig = await make_rig()
    await rig.person(OJI, "not_home")
    await rig.w.advance(1000)
    await rig.person(EZ, "not_home")
    await rig.w.advance(299)
    assert rig.locks() == []
    await rig.w.advance(2)
    assert rig.locks() == [BED]


@pytest.mark.asyncio
async def test_no_engage_kill_switch_off():
    rig = await make_rig(opts=options(security_away_lock_enabled=False))
    await rig.both_out(3600)
    assert rig.locks() == []


@pytest.mark.asyncio
async def test_kill_switch_off_after_arming_blocks_engage():
    """The predicate re-reads the switch at write time: an option turned off
    after the timer armed (not through the switch entity) still blocks."""
    rig = await make_rig()
    await rig.person(OJI, "not_home")
    await rig.person(EZ, "not_home")
    assert rig.regime._away_dwell_unsub is not None
    rig.w.cm_entry.options["security_away_lock_enabled"] = False
    await rig.w.advance(400)
    assert rig.locks() == []
    assert rig.regime.away_lock_last_action["why"] == "kill_switch_off"


@pytest.mark.asyncio
async def test_kill_switch_absent_is_off():
    opts = options()
    del opts["security_away_lock_enabled"]
    rig = await make_rig(opts=opts)
    assert rig.regime.away_lock_on() is False
    await rig.both_out(3600)
    assert rig.locks() == []


@pytest.mark.asyncio
async def test_observation_mode_records_not_writes():
    rig = await make_rig()
    rig.sc.observation_mode = True
    await rig.both_out()
    assert rig.locks() == []
    assert rig.regime.away_lock_last_action["action"] == "would_engage"


@pytest.mark.asyncio
async def test_engage_target_must_be_excluded():
    rig = await make_rig(opts=options(security_lock_sweep_exclude=[]))
    await rig.both_out()
    assert rig.locks() == []
    assert rig.regime.away_lock_last_action["why"] == "not_excluded"


@pytest.mark.asyncio
async def test_engage_skips_lockout_entity():
    rig = await make_rig(opts=options(
        security_away_lock_entities=[BED, LOCK_A],
        security_lock_sweep_exclude=[BED, LOCK_A],
    ))
    await rig.both_out()
    assert rig.locks() == [BED]


@pytest.mark.asyncio
async def test_empty_persons_inert():
    rig = await make_rig(opts=options(security_away_lock_persons=[]))
    await rig.both_out(3600)
    assert rig.locks() == []
    assert rig.regime._away_due_ts(rig.regime._cfg()) is None


@pytest.mark.asyncio
async def test_no_engage_when_already_locked_by_human():
    rig = await make_rig(bed="locked")
    await rig.both_out()
    assert rig.locks() == []
    assert rig.regime.away_lock_owned == set()


@pytest.mark.asyncio
async def test_no_engage_sc_disabled_flag():
    rig = await make_rig()
    rig.sc.enabled = False
    await rig.both_out()
    assert rig.locks() == []


@pytest.mark.asyncio
async def test_timer_arms_only_when_all_not_home():
    rig = await make_rig()
    await rig.person(OJI, "not_home")
    assert rig.regime._away_dwell_unsub is None
    await rig.person(EZ, "not_home")
    assert rig.regime._away_dwell_unsub is not None
    # Literal: EZ's since + 300 s.
    expected = (rig.w.now + timedelta(seconds=300)).timestamp()
    assert rig.regime._away_pending_at == expected
    await rig.person(EZ, "home")
    assert rig.regime._away_dwell_unsub is None
    assert rig.regime._away_pending_at is None


@pytest.mark.asyncio
async def test_predicate_refuses_inside_dwell():
    """INV-X2 at write time: an engage that runs early (e.g. a stale timer)
    is refused by the predicate itself, not only by the timer delay."""
    rig = await make_rig()
    await rig.person(OJI, "not_home")
    await rig.person(EZ, "not_home")
    await rig.w.advance(200)
    await rig.regime._async_away_engage("test")
    assert rig.locks() == []
    assert rig.regime.away_lock_last_action["why"] == "dwell"


@pytest.mark.asyncio
async def test_stale_stamp_with_named_zone_state_never_engages():
    """The predicate reads the LIVE person state: a stamp left behind by a
    missed event never counts a named zone as away."""
    rig = await make_rig()
    await rig.person(OJI, "not_home")
    await rig.person(EZ, "not_home")
    rig.w.seed(EZ, "Work")  # state changes with no event reaching the regime
    await rig.w.advance(400)
    assert rig.locks() == []


@pytest.mark.asyncio
async def test_dwell_zero_engages_on_first_away_edge(monkeypatch):
    monkeypatch.setattr(const, "SECURITY_AWAY_LOCK_ENGAGE_DWELL_S", 0)
    rig = await make_rig()
    await rig.person(OJI, "not_home")
    await rig.person(EZ, "not_home")
    await rig.w.advance(0)
    assert rig.locks() == [BED]


@pytest.mark.asyncio
async def test_non_listed_person_ignored():
    rig = await make_rig(persons={OJI: "home", EZ: "home", ZIRI: "home", KIOSK: "unknown"})
    await rig.person(ZIRI, "not_home")
    await rig.both_out()
    assert rig.locks() == [BED]  # Ziri is not on the list; his state never mattered


# ============================================================================
# Passage mode (not taken)
# ============================================================================


def _refuse_lock(rig):
    rig.w.apply_service_state = False


@pytest.mark.asyncio
async def test_engage_not_taken_one_low_notice_no_ownership():
    rig = await make_rig()
    _refuse_lock(rig)
    await rig.both_out()
    assert rig.locks() == [BED]
    await rig.w.advance(21)
    assert rig.regime.away_lock_owned == set()
    assert rig.regime.away_lock_last_action["action"] == "engage_not_taken"
    assert len(rig.nm.notes) == 1
    assert rig.nm.notes[0]["severity"] == load("domain_coordinators.base").Severity.LOW
    assert "Master Bedroom Lock" in rig.nm.notes[0]["message"]
    await rig.w.advance(3600)
    assert rig.locks() == [BED]  # no retry
    assert len(rig.nm.notes) == 1
    # Further all-away events never re-arm the timer in this formation.
    rig.w.set_state(OJI, "not_home", {"gps_accuracy": 5})
    await settle()
    assert rig.regime._away_dwell_unsub is None
    assert rig.regime._away_pending_at is None


@pytest.mark.asyncio
async def test_two_entities_not_taken_one_advisory():
    study = "lock.study_lock"
    rig = await make_rig(opts=options(
        security_lock_entities=[DOOR, BED, study],
        security_lock_sweep_exclude=[BED, study],
        security_away_lock_entities=[BED, study],
    ))
    rig.w.seed(study, "unlocked")
    _refuse_lock(rig)
    await rig.both_out()
    assert rig.locks() == [BED, study]
    await rig.w.advance(21)
    assert len(rig.nm.notes) == 1


@pytest.mark.asyncio
async def test_engage_taken_records_ownership():
    store = MemStore()
    rig = await make_rig(store=store)
    await rig.both_out()  # engage at +300 s; now +301 s
    await rig.w.advance(18)  # +319 s: read-back (20 s) not run yet
    assert rig.regime.away_lock_owned == set()  # only after the read-back
    await rig.w.advance(2)
    assert rig.regime.away_lock_owned == {BED}
    assert store.saved["away_lock_owned"] == [BED]


@pytest.mark.asyncio
async def test_one_advisory_per_formation():
    rig = await make_rig()
    _refuse_lock(rig)
    await rig.both_out()
    await rig.w.advance(21)
    for i in range(10):
        rig.w.set_state(OJI, "not_home", {"gps_accuracy": i})
        await settle()
        await rig.w.advance(400)
    assert len(rig.nm.notes) == 1
    assert rig.locks() == [BED]
    # One person leaves not_home and returns: a new attempt is allowed.
    await rig.person(EZ, "Work")
    await rig.person(EZ, "not_home")
    await rig.w.advance(301)
    assert rig.locks() == [BED, BED]
    await rig.w.advance(21)
    assert len(rig.nm.notes) == 2


# ============================================================================
# Release (INV-X3)
# ============================================================================


async def _engaged(**kw):
    rig = await make_rig(**kw)
    await rig.both_out()
    await rig.w.advance(21)
    assert rig.regime.away_lock_owned == {BED}
    rig.w.calls.clear()
    return rig


@pytest.mark.asyncio
async def test_release_on_either_arrival_p1():
    rig = await _engaged()
    await rig.w.advance(1800)
    await rig.person(OJI, "home")  # Ezinne stays away (discrimination)
    assert rig.unlocks() == [BED]
    assert rig.regime.away_lock_owned == set()
    assert rig.regime.away_lock_last_action["action"] == "release"


@pytest.mark.asyncio
async def test_release_on_either_arrival_other_person():
    rig = await _engaged()
    await rig.w.advance(1800)
    await rig.person(EZ, "home")
    assert rig.unlocks() == [BED]


@pytest.mark.asyncio
async def test_release_on_arriving_signal_p2():
    rig = await _engaged()
    await rig.w.advance(1800)  # really away >= 15 min
    rig.regime.on_person_arriving({"person_entity": EZ, "source": "geofence"})
    await settle()
    assert rig.unlocks() == [BED]


@pytest.mark.asyncio
async def test_arriving_signal_short_absence_does_not_release():
    rig = await _engaged()  # out for ~5.5 min only
    rig.regime.on_person_arriving({"person_entity": EZ, "source": "camera_face"})
    await settle()
    assert rig.unlocks() == []


@pytest.mark.asyncio
async def test_p2_through_sc_bridge_releases():
    rig = await _engaged()
    await rig.w.advance(1800)
    rig.sc._handle_person_arriving_signal({"person_entity": OJI, "source": "ble"})
    await settle()
    assert rig.unlocks() == [BED]


@pytest.mark.asyncio
async def test_release_only_owned():
    rig = await make_rig()
    await rig.both_out()
    # A human locked it before the dwell ran out? Here: engage refused
    # because it read locked; it is not ours.
    rig2 = await make_rig(bed="locked")
    await rig2.both_out()
    await rig2.w.advance(1800)
    rig2.w.calls.clear()
    await rig2.person(OJI, "home")
    await rig2.person(EZ, "home")
    assert rig2.unlocks() == []


@pytest.mark.asyncio
async def test_manual_unlock_drops_ownership():
    store = MemStore()
    rig = await _engaged(store=store)
    rig.w.set_state(BED, "unlocked")  # human
    await settle()
    assert rig.regime.away_lock_owned == set()
    assert store.saved["away_lock_owned"] == []
    rig.w.set_state(BED, "locked")  # human locks it again
    await rig.w.advance(1800)
    await rig.person(OJI, "home")
    assert rig.unlocks() == []


@pytest.mark.asyncio
async def test_release_inside_readback_window():
    """H2: engage at t, arrival at t+10 s -> unlock issued; the read-back is
    cancelled and E is not owned afterwards."""
    rig = await make_rig()
    await rig.person(OJI, "not_home")
    await rig.w.advance(1000)  # Oji really away
    await rig.person(EZ, "not_home")
    await rig.w.advance(301)
    assert rig.locks() == [BED]
    await rig.w.advance(10)
    await rig.person(OJI, "home")
    assert rig.unlocks() == [BED]
    assert rig.regime._away_readback_unsubs == {}  # read-back cancelled now
    await rig.w.advance(60)
    assert rig.regime.away_lock_owned == set()
    assert rig.regime._away_engage_inflight == {}
    assert rig.regime._away_readback_unsubs == {}


@pytest.mark.asyncio
async def test_hazard_releases_owned():
    rig = await _engaged(opts=options(security_on_hazard_unlock_egress=True))
    rig.sc._maybe_release_lockouts_for_hazard({"hazard_type": "smoke", "severity": "critical"})
    await settle()
    assert BED in rig.unlocks()
    assert rig.regime.away_lock_owned == set()
    # No re-engage in this formation after a hazard.
    await rig.w.advance(3600)
    assert rig.locks() == []


@pytest.mark.asyncio
async def test_kill_switch_off_releases_owned():
    rig = await _engaged()
    rig.w.cm_entry.options["security_away_lock_enabled"] = False
    rig.regime.on_kill_switch_changed(False, "security_away_lock_enabled")
    await settle()
    assert rig.unlocks() == [BED]


@pytest.mark.asyncio
async def test_release_readback_retry_then_high_nm():
    rig = await _engaged()
    await rig.w.advance(1800)
    rig.w.apply_service_state = False  # the unlock never lands
    await rig.person(OJI, "home")
    await rig.w.advance(21)
    await rig.w.advance(21)
    assert rig.unlocks() == [BED, BED]
    highs = [n for n in rig.nm.notes if n["title"] == "Away Lock release failed"]
    assert len(highs) == 1
    assert highs[0]["severity"] == load("domain_coordinators.base").Severity.HIGH
    assert "Master Bedroom Lock" in highs[0]["message"]


# ============================================================================
# Garage policy isolation
# ============================================================================


@pytest.mark.asyncio
async def test_garage_policy_unaffected():
    rig = await make_rig(opts=options(security_garage_lockout_enabled=True))
    before = (rig.regime.reason, rig.regime.release_gen, rig.regime._backstop_unsub,
              rig.regime._reengage_unsub, dict(rig.regime.last_action))
    await rig.both_out()
    await rig.w.advance(21)
    await rig.w.advance(1800)
    rig.w.calls.clear()
    # A non-resident (kiosk) person event triggers no garage release.
    await rig.person(KIOSK, "home")
    assert rig.unlocks() == []
    # Away release: only BED; garage state untouched.
    await rig.person(OJI, "home")
    assert rig.unlocks() == [BED]
    after = (rig.regime.reason, rig.regime.release_gen, rig.regime._backstop_unsub,
             rig.regime._reengage_unsub)
    # The resident arrival bumps release_gen through the GARAGE P1 path (it
    # always did); the away engage/release add nothing beyond that one bump.
    assert after == (before[0], before[1] + 1, before[2], before[3])
    assert rig.regime.last_action["action"] == "release"
    assert rig.regime.last_action["entities"] == []  # garage lockouts were unlocked


@pytest.mark.asyncio
async def test_non_resident_event_no_garage_release():
    rig = await make_rig(opts=options(security_garage_lockout_enabled=True),
                         start=NIGHT, house="sleep", lockouts="locked")
    await rig.person(KIOSK, "not_home")
    await rig.w.advance(1800)
    await rig.person(KIOSK, "home")
    assert rig.unlocks() == []
    assert rig.regime.releasing_set == {}


@pytest.mark.asyncio
async def test_away_person_also_lockout_excluded_still_tracked():
    """§2.2: an away-lock person who is a lockout-excluded person is still
    tracked (_last_real + since-stamp) and releases the away lock."""
    rig = await make_rig(opts=options(security_lockout_excluded_persons=[KIOSK, EZ]))
    await rig.person(OJI, "not_home")
    await rig.w.advance(1000)
    await rig.person(EZ, "not_home")
    assert rig.regime._last_real[EZ][0] == "not_home"
    await rig.w.advance(301)
    assert rig.locks() == [BED]
    await rig.w.advance(1800)
    await rig.w.advance(21)
    rig.w.calls.clear()
    await rig.person(EZ, "home")
    assert rig.unlocks() == [BED]


async def _garage_off_trace(with_away: bool):
    sw = load("switch")
    opts = options(security_garage_lockout_enabled=True)
    if not with_away:
        for key in ("security_lock_sweep_exclude", "security_away_lock_enabled",
                    "security_away_lock_entities", "security_away_lock_persons"):
            opts.pop(key)
    rig = await make_rig(start=NIGHT, house="home_night", opts=opts)
    if with_away:
        await rig.both_out()
        await rig.w.advance(21)
        assert rig.regime.away_lock_owned == {BED}
    rig.w.calls.clear()
    await rig.edge("sleep")
    mgr = SimpleNamespace(house_state="sleep", coordinators={"security": rig.sc})
    rig.w.hass.data[const.DOMAIN]["coordinator_manager"] = mgr
    garage = sw._build_security_lockout_switches(rig.w.hass, rig.w.cm_entry)[0]
    garage.async_write_ha_state = lambda: None
    await garage.async_turn_off()
    await settle()
    await rig.w.advance(21)
    last = {k: v for k, v in rig.regime.last_action.items() if k != "at"}
    return (
        [c for c in rig.w.calls if c[2] != BED],
        rig.regime.reason, rig.regime.release_gen,
        rig.regime._backstop_unsub, rig.regime._reengage_unsub, last,
        BED in rig.unlocks(),
    )


@pytest.mark.asyncio
async def test_garage_switch_off_path_byte_identical():
    base = await _garage_off_trace(False)
    with_away = await _garage_off_trace(True)
    assert with_away == base
    assert base[0] == [
        ("lock", "lock", LOCK_A, False), ("lock", "lock", LOCK_B, False),
        ("lock", "unlock", LOCK_A, True), ("lock", "unlock", LOCK_B, True),
    ]
    assert with_away[-1] is False  # away-owned BED untouched


# ============================================================================
# D4 switch
# ============================================================================


def _switches(rig):
    sw = load("switch")
    mgr = SimpleNamespace(house_state=rig.mgr.house_state, coordinators={"security": rig.sc})
    rig.w.hass.data[const.DOMAIN]["coordinator_manager"] = mgr
    rig.mgr = mgr
    out = {}
    for s in sw._build_security_lockout_switches(rig.w.hass, rig.w.cm_entry):
        s.async_write_ha_state = lambda: None
        out[s.entity_id] = s
    return out


@pytest.mark.asyncio
async def test_switch_default_off():
    opts = options()
    del opts["security_away_lock_enabled"]
    rig = await make_rig(opts=opts)
    sw = _switches(rig)["switch.ura_security_coordinator_away_lock"]
    assert sw.is_on is False
    # Read our own _attr_* values, not HA Entity properties:
    # test_fan_incident_2026_08_01_replay.py:118 installs a bare
    # SwitchEntity stub into sys.modules["homeassistant.components.switch"] at
    # import, so in a full run the switch module may subclass a class with no
    # `name` / `unique_id` properties (validator full-suite failure).
    assert sw._attr_name == "Away Lock"
    assert sw._attr_unique_id == "universal_room_automation_ura_security_coordinator_away_lock"
    assert sw.entity_id == "switch.ura_security_coordinator_away_lock"


@pytest.mark.asyncio
async def test_switch_off_releases_only_its_policy():
    rig = await _engaged(opts=options(security_garage_lockout_enabled=True),
                         start=NIGHT, house="home_night")
    await rig.edge("sleep")
    assert rig.locks() == [LOCK_A, LOCK_B]
    rig.w.calls.clear()
    sws = _switches(rig)
    await sws["switch.ura_security_coordinator_away_lock"].async_turn_off()
    await settle()
    assert rig.w.cm_entry.options["security_away_lock_enabled"] is False
    assert rig.unlocks() == [BED]
    assert rig.regime.reason == "sleep"  # garage untouched
    rig.w.calls.clear()
    await sws["switch.ura_security_coordinator_garage_lockout"].async_turn_off()
    await settle()
    assert rig.unlocks() == [LOCK_A, LOCK_B]


@pytest.mark.asyncio
async def test_switch_on_does_not_engage():
    opts = options(security_away_lock_enabled=False)
    rig = await make_rig(opts=opts)
    await rig.both_out()
    sws = _switches(rig)
    await sws["switch.ura_security_coordinator_away_lock"].async_turn_on()
    await settle()
    await rig.w.advance(3600)
    assert rig.locks() == []


# ============================================================================
# Restart / Store (H1, M3)
# ============================================================================


@pytest.mark.asyncio
async def test_owned_survives_restart():
    store = MemStore()
    rig = await _engaged(store=store)
    await rig.w.advance(1800)
    payload = dict(store.saved)
    # Restart: new controller over the same world, store holds the payload.
    rig2 = await make_rig(start=rig.w.now, store=MemStore(payload), bed="locked",
                          persons={OJI: "not_home", EZ: "not_home", KIOSK: "unknown"})
    assert rig2.regime.away_lock_owned == {BED}
    await rig2.person(OJI, "home")
    assert rig2.unlocks() == [BED]


@pytest.mark.asyncio
async def test_boot_replay_does_not_engage():
    t0 = DAY
    store = MemStore({"residents": [OJI, EZ],
                      "away_not_home_since": {OJI: t0.timestamp() - 4000,
                                              EZ: t0.timestamp() - 4000}})
    rig = await make_rig(store=store, past_boot=False,
                         persons={KIOSK: "unknown"})
    # HA person restore (old_state None) inside the boot window.
    rig.w.set_state(OJI, "not_home")
    rig.w.set_state(EZ, "not_home")
    await settle()
    await rig.w.advance(119)
    assert rig.locks() == []


@pytest.mark.asyncio
async def test_boot_replay_real_edge_inside_window_does_not_engage():
    store = MemStore({"residents": [OJI, EZ],
                      "away_not_home_since": {OJI: DAY.timestamp() - 4000}})
    rig = await make_rig(store=store, past_boot=False,
                         persons={OJI: "not_home", EZ: "home", KIOSK: "unknown"})
    await rig.w.advance(10)
    await rig.person(EZ, "not_home")
    await rig.w.advance(100)  # still before the 120 s recheck
    assert rig.locks() == []


@pytest.mark.asyncio
async def test_boot_recheck_engages_from_persisted_dwell():
    store = MemStore({"residents": [OJI, EZ],
                      "away_not_home_since": {OJI: DAY.timestamp() - 400,
                                              EZ: DAY.timestamp() - 400}})
    rig = await make_rig(store=store, past_boot=False, persons={KIOSK: "unknown"})
    rig.w.set_state(OJI, "not_home")  # restored
    rig.w.set_state(EZ, "not_home")
    await settle()
    await rig.w.advance(119)
    assert rig.locks() == []
    await rig.w.advance(2)  # boot recheck at 120 s
    assert rig.locks() == [BED]


@pytest.mark.asyncio
async def test_restart_mid_dwell_rearms_remainder():
    store = MemStore({"residents": [OJI, EZ],
                      "away_not_home_since": {OJI: DAY.timestamp() - 100,
                                              EZ: DAY.timestamp() - 100}})
    rig = await make_rig(store=store, past_boot=False,
                         persons={OJI: "not_home", EZ: "not_home", KIOSK: "unknown"})
    await rig.w.advance(121)  # recheck: 100 + 121 = 221 s elapsed of 300
    assert rig.locks() == []
    assert rig.regime._away_pending_at == DAY.timestamp() - 100 + 300
    await rig.w.advance(78)  # 299 s
    assert rig.locks() == []
    await rig.w.advance(2)  # 301 s
    assert rig.locks() == [BED]


@pytest.mark.asyncio
async def test_restart_without_persisted_stamp_counts_from_setup():
    rig = await make_rig(store=MemStore({"residents": [OJI, EZ]}), past_boot=False,
                         persons={OJI: "not_home", EZ: "not_home", KIOSK: "unknown"})
    assert rig.regime._away_not_home_since == {OJI: DAY.timestamp(), EZ: DAY.timestamp()}
    await rig.w.advance(299)
    assert rig.locks() == []
    await rig.w.advance(2)
    assert rig.locks() == [BED]


@pytest.mark.asyncio
async def test_restore_without_stamp_counts_from_restore():
    rig = await make_rig(store=MemStore({"residents": [OJI, EZ]}), past_boot=False,
                         persons={KIOSK: "unknown"})
    await rig.w.advance(30)
    rig.w.set_state(OJI, "not_home")  # HA person restore at +30 s
    rig.w.set_state(EZ, "not_home")
    await settle()
    assert rig.regime._away_not_home_since == {
        OJI: DAY.timestamp() + 30, EZ: DAY.timestamp() + 30}
    await rig.w.advance(299)  # +329 s
    assert rig.locks() == []
    await rig.w.advance(2)  # +331 s
    assert rig.locks() == [BED]


@pytest.mark.asyncio
async def test_stale_persisted_stamp_dropped_when_person_reads_home():
    store = MemStore({"residents": [OJI, EZ],
                      "away_not_home_since": {OJI: DAY.timestamp() - 9000}})
    rig = await make_rig(store=store, past_boot=True,
                         persons={OJI: "home", EZ: "not_home", KIOSK: "unknown"})
    assert OJI not in rig.regime._away_not_home_since
    await rig.person(OJI, "not_home")
    await rig.w.advance(299)
    assert rig.locks() == []


@pytest.mark.asyncio
async def test_store_save_merges_keys():
    store = MemStore({"residents": [OJI, EZ]})
    rig = await _engaged(store=store)
    assert store.saved["residents"] == [EZ, OJI]  # kiosk is lockout-excluded
    # Add a person (resident save path) -> away keys still present.
    rig.w.set_state(ZIRI, "home")
    await settle()
    assert ZIRI in store.saved["residents"]
    assert store.saved["away_lock_owned"] == [BED]
    assert set(store.saved["away_not_home_since"]) == {OJI, EZ}
    # An away-lock save keeps residents.
    rig.w.set_state(BED, "unlocked")
    await settle()
    assert store.saved["away_lock_owned"] == []
    assert ZIRI in store.saved["residents"]


@pytest.mark.asyncio
async def test_store_loader_accepts_missing_and_bad_keys():
    rig = await make_rig(store=MemStore({"residents": [OJI], "away_lock_owned": "bad",
                                         "away_not_home_since": {"x": 1, EZ: "nan?"}}))
    assert rig.regime.away_lock_owned == set()
    assert rig.regime._away_not_home_since == {}
    assert OJI in rig.regime._residents


# ============================================================================
# SC disable + teardown + callbacks
# ============================================================================


@pytest.mark.asyncio
async def test_sc_disable_releases_away_lock_with_garage_off():
    rig = await _engaged()  # garage lockout OFF (options default here)
    rig.w.cm_entry.options["security_coordinator_enabled"] = False
    await rig.sc.async_teardown()
    unl = [c for c in rig.w.calls if c[:2] == ("lock", "unlock")]
    assert unl == [("lock", "unlock", BED, True)]
    assert rig.regime.away_lock_owned == set()


@pytest.mark.asyncio
async def test_sc_restart_teardown_does_not_release_away():
    rig = await _engaged()
    await rig.sc.async_teardown()  # options still say enabled
    assert rig.unlocks() == []


@pytest.mark.asyncio
async def test_teardown_cancels_away_timers():
    rig = await make_rig()
    await rig.person(OJI, "not_home")
    await rig.person(EZ, "not_home")
    assert rig.regime._away_dwell_unsub is not None
    await rig.sc.async_teardown()
    assert rig.regime._away_dwell_unsub is None
    assert rig.w.live_timers() == []
    await rig.w.advance(3600)
    assert rig.locks() == []


@pytest.mark.asyncio
async def test_teardown_cancels_away_readback():
    rig = await make_rig()
    await rig.both_out()
    assert rig.regime._away_readback_unsubs
    await rig.sc.async_teardown()
    assert rig.regime._away_readback_unsubs == {}
    assert rig.w.live_timers() == []


@pytest.mark.asyncio
async def test_every_away_callback_is_a_loop_callback():
    from homeassistant.core import HassJob, HassJobType

    rig = await make_rig()
    await rig.both_out()
    await rig.w.advance(21)
    rig.w.set_state(BED, "unlocked")
    await settle()
    names = set()
    for cb in rig.w.registered:
        assert HassJob(cb).job_type == HassJobType.Callback, cb
        target = cb.func if hasattr(cb, "func") else cb
        names.add(getattr(target, "__name__", repr(target)))
    expected = {"_on_away_dwell", "_on_away_readback", "_on_away_lock_event"}
    assert expected <= names, expected - names


@pytest.mark.asyncio
async def test_snapshot_away_keys():
    rig = await make_rig()
    await rig.person(OJI, "not_home")
    await rig.person(EZ, "not_home")
    snap = rig.regime.snapshot()
    assert snap["lock_regime_away_lock_enabled"] is True
    assert snap["lock_regime_away_lock_pending_engage_at"] == (
        rig.w.now + timedelta(seconds=300)).isoformat()
    await rig.w.advance(321)
    snap = rig.regime.snapshot()
    assert snap["lock_regime_away_lock_owned"] == [BED]
    assert snap["lock_regime_away_lock_last_action"]["action"] == "engage"
    assert snap["lock_regime_away_lock_pending_engage_at"] is None
    # Garage keys still present, unchanged names.
    assert "lock_regime_garage_lockout_last_action" in snap


# ============================================================================
# Fix-up pass (reviews A + B)
# ============================================================================


class FlushStore(MemStore):
    def __init__(self, data=None):
        super().__init__(data)
        self.flushed = None

    async def async_save(self, data):
        self.flushed = data


def _owned_payload(**extra):
    payload = {"residents": [EZ, OJI], "away_lock_owned": [BED],
               "away_not_home_since": {OJI: DAY.timestamp() - 3000,
                                       EZ: DAY.timestamp() - 3000}}
    payload.update(extra)
    return payload


@pytest.mark.asyncio
async def test_a1_restart_person_home_at_boot_recheck_releases_owned():
    """A1 repro 1 / B3: Oji got home while HA was down. No event reaches the
    regime (state already home at setup); the boot recheck releases."""
    rig = await make_rig(store=MemStore(_owned_payload()), past_boot=False, bed="locked",
                         persons={OJI: "home", EZ: "not_home", KIOSK: "unknown"})
    assert rig.regime.away_lock_owned == {BED}
    await rig.w.advance(119)
    assert rig.unlocks() == []
    await rig.w.advance(2)  # boot recheck at 120 s
    assert rig.unlocks() == [BED]
    assert rig.regime.away_lock_owned == set()


@pytest.mark.asyncio
async def test_a1_restored_home_event_releases_owned():
    rig = await make_rig(store=MemStore(_owned_payload()), past_boot=False, bed="locked",
                         persons={KIOSK: "unknown"})
    rig.w.set_state(OJI, "home")  # HA person restore (old_state None)
    await settle()
    assert rig.unlocks() == [BED]


@pytest.mark.asyncio
async def test_a1_blip_gated_return_under_15_min_releases():
    """A1 repro 2: engaged at +5 min; Oji not_home -> unknown -> home at
    +10 min. The garage 15-min blip gate does not apply to the away lock."""
    rig = await _engaged()
    await rig.w.advance(240)
    await rig.person(OJI, "unknown")
    await rig.person(OJI, "home")
    assert rig.unlocks() == [BED]


@pytest.mark.asyncio
async def test_b1_hazard_after_first_lock_second_never_locked():
    study = "lock.study_lock"
    rig = await make_rig(opts=options(
        security_lock_entities=[DOOR, BED, study],
        security_lock_sweep_exclude=[BED, study],
        security_away_lock_entities=[BED, study],
    ))
    rig.w.seed(study, "unlocked")

    def hazard_after_bed(domain, service, ent):
        if (domain, service, ent) == ("lock", "lock", BED):
            rig.regime.on_hazard()

    rig.w.call_hooks.append(hazard_after_bed)
    await rig.both_out()
    assert study not in rig.locks()
    assert rig.locks() == [BED]
    assert rig.unlocks() == [BED]


@pytest.mark.asyncio
async def test_a4_switch_off_mid_loop_second_never_locked():
    study = "lock.study_lock"
    rig = await make_rig(opts=options(
        security_lock_entities=[DOOR, BED, study],
        security_lock_sweep_exclude=[BED, study],
        security_away_lock_entities=[BED, study],
    ))
    rig.w.seed(study, "unlocked")

    def switch_off_after_bed(domain, service, ent):
        if (domain, service, ent) == ("lock", "lock", BED):
            rig.w.cm_entry.options["security_away_lock_enabled"] = False

    rig.w.call_hooks.append(switch_off_after_bed)
    await rig.both_out()
    assert rig.locks() == [BED]


async def _restart(rig, store_payload, **kw):
    return await make_rig(start=rig.w.now, store=MemStore(store_payload),
                          past_boot=False, **kw)


@pytest.mark.asyncio
async def test_b2_restart_mid_outing_no_renotify_passage_mode():
    store = MemStore()
    rig = await make_rig(store=store)
    _refuse_lock(rig)
    await rig.both_out()
    await rig.w.advance(21)
    assert len(rig.nm.notes) == 1
    payload = dict(store.saved)
    rig2 = await _restart(rig, payload, persons={OJI: "not_home", EZ: "not_home",
                                                KIOSK: "unknown"})
    await rig2.w.advance(3600)
    assert rig2.locks() == []
    assert rig2.nm.notes == []


@pytest.mark.asyncio
async def test_b2_restart_after_human_unlock_does_not_relock():
    store = MemStore()
    rig = await _engaged(store=store)
    rig.w.set_state(BED, "unlocked")  # at-home guest unlocks it
    await settle()
    await rig.w.advance(3600)
    rig2 = await _restart(rig, dict(store.saved), persons={OJI: "not_home", EZ: "not_home",
                                                          KIOSK: "unknown"})
    await rig2.w.advance(3600)
    assert rig2.locks() == []


@pytest.mark.asyncio
async def test_b2_new_outing_after_restart_still_engages():
    store = MemStore()
    rig = await _engaged(store=store)
    rig2 = await _restart(rig, dict(store.saved), bed="unlocked",
                          persons={OJI: "home", EZ: "not_home", KIOSK: "unknown"})
    await rig2.w.advance(121)
    await rig2.person(OJI, "not_home")  # a fresh formation
    await rig2.w.advance(301)
    assert rig2.locks() == [BED]


@pytest.mark.asyncio
async def test_a2_owned_jammed_release_attempts_unlock():
    rig = await _engaged()
    rig.w.set_state(BED, "jammed")
    await settle()
    await rig.w.advance(1800)
    await rig.person(OJI, "home")
    assert rig.unlocks() == [BED]


@pytest.mark.asyncio
async def test_a3_sc_disable_unavailable_keeps_ownership():
    rig = await _engaged()
    rig.w.set_state(BED, "unavailable")
    rig.w.cm_entry.options["security_coordinator_enabled"] = False
    await rig.regime.async_release_if_disabled()
    assert rig.unlocks() == []
    assert rig.regime.away_lock_owned == {BED}


@pytest.mark.asyncio
async def test_b4_inflight_unavailable_at_release_becomes_owned():
    rig = await make_rig()
    await rig.person(OJI, "not_home")
    await rig.w.advance(1000)
    await rig.person(EZ, "not_home")
    await rig.w.advance(301)  # engaged; read-back pending
    rig.w.set_state(BED, "unavailable")
    await settle()
    await rig.person(OJI, "home")
    assert rig.unlocks() == []
    assert rig.regime.away_lock_owned == {BED}
    rig.w.set_state(BED, "locked")  # comes back locked
    await settle()
    await rig.person(EZ, "home")
    assert rig.unlocks() == [BED]


@pytest.mark.asyncio
async def test_a5_restart_inside_readback_window_owns_locked_lock():
    store = MemStore()
    rig = await make_rig(store=store)
    await rig.both_out()  # lock.lock issued; read-back not run
    payload = dict(store.saved)
    assert payload["away_lock_inflight"] == [BED]
    rig2 = await _restart(rig, payload, bed="locked",
                          persons={OJI: "not_home", EZ: "not_home", KIOSK: "unknown"})
    assert rig2.regime.away_lock_owned == {BED}
    await rig2.person(OJI, "home")
    assert rig2.unlocks() == [BED]


@pytest.mark.asyncio
async def test_b5_teardown_flushes_store():
    store = FlushStore()
    rig = await _engaged(store=store)
    await rig.sc.async_teardown()
    assert store.flushed is not None
    assert store.flushed["away_lock_owned"] == [BED]
    assert set(store.flushed) >= {"residents", "away_lock_owned", "away_not_home_since",
                                  "away_lock_inflight", "away_attempted_marker"}


# ============================================================================
# Review C (test authority) additions
# ============================================================================


@pytest.mark.asyncio
async def test_g1_named_zone_does_not_release_owned():
    rig = await _engaged()
    await rig.w.advance(1800)
    await rig.person(OJI, "Work")
    assert rig.unlocks() == []
    assert rig.regime.away_lock_owned == {BED}


@pytest.mark.asyncio
async def test_g2_release_not_suppressed_by_observation_mode():
    rig = await _engaged()
    rig.sc.observation_mode = True
    await rig.person(OJI, "home")
    assert rig.unlocks() == [BED]


@pytest.mark.asyncio
async def test_g3_sc_disable_releases_with_away_switch_off():
    rig = await _engaged()
    rig.w.cm_entry.options["security_away_lock_enabled"] = False  # no release edge
    rig.w.cm_entry.options["security_coordinator_enabled"] = False
    await rig.regime.async_release_if_disabled()
    assert rig.unlocks() == [BED]


@pytest.mark.asyncio
async def test_g4_switch_off_then_on_same_outing_never_relocks():
    """Switch OFF during the dwell (before any engage), then ON again: the
    release latched this outing, so the next listed-person edge never arms."""
    rig = await make_rig()
    await rig.person(OJI, "not_home")
    await rig.person(EZ, "not_home")
    await rig.w.advance(100)
    rig.w.cm_entry.options["security_away_lock_enabled"] = False
    rig.regime.on_kill_switch_changed(False, "security_away_lock_enabled")
    await settle()
    assert rig.regime._away_dwell_unsub is None
    rig.w.cm_entry.options["security_away_lock_enabled"] = True
    rig.w.set_state(OJI, "not_home", {"gps_accuracy": 3})  # next listed-person edge
    await settle()
    await rig.w.advance(3600)
    assert rig.locks() == []


@pytest.mark.asyncio
async def test_g5_home_unavailable_not_home_needs_fresh_dwell():
    """Review C G5: a home reading drops the stamp, so home -> unavailable
    -> not_home counts the dwell again (no GPS-flap shortcut)."""
    rig = await make_rig()
    await rig.person(EZ, "not_home")
    await rig.person(OJI, "not_home")
    await rig.w.advance(200)
    await rig.person(OJI, "home")
    await rig.person(OJI, "unavailable")
    await rig.person(OJI, "not_home")
    await rig.w.advance(299)
    assert rig.locks() == []
    await rig.w.advance(2)
    assert rig.locks() == [BED]


@pytest.mark.asyncio
async def test_g8_marker_tracks_latest_stamp_two_people():
    """The outing key is the LATEST stamp: if the last person out started a
    new outing while HA was down, the restart may attempt again."""
    store = MemStore()
    rig = await make_rig(store=store)
    await rig.person(OJI, "not_home")
    await rig.w.advance(1000)
    await rig.person(EZ, "not_home")  # EZ holds the latest stamp
    await rig.w.advance(321)
    assert rig.regime.away_lock_owned == {BED}
    rig.w.set_state(BED, "unlocked")  # human unlock: ownership lost
    await settle()
    payload = dict(store.saved)
    since = dict(payload["away_not_home_since"])
    since[EZ] = since[EZ] + 2000  # EZ came back and left again while HA was down
    payload["away_not_home_since"] = since
    rig2 = await _restart(rig, payload, persons={OJI: "not_home", EZ: "not_home",
                                                KIOSK: "unknown"})
    await rig2.w.advance(3600)
    assert rig2.locks() == [BED]


@pytest.mark.asyncio
async def test_g9_attempt_marker_saved_at_attempt():
    store = MemStore()
    rig = await make_rig(store=store)
    rig.sc.observation_mode = True  # no in-flight save follows the attempt
    await rig.both_out()
    assert rig.regime.away_lock_last_action["action"] == "would_engage"
    assert store.saved["away_attempted_marker"] == rig.regime._formation_key(rig.regime._cfg())
    assert store.saved["away_attempted_marker"] is not None


@pytest.mark.asyncio
async def test_g10_sc_disable_failed_unlock_high_away_nm_and_save():
    store = MemStore()
    rig = await _engaged(store=store)
    rig.w.cm_entry.options["security_coordinator_enabled"] = False

    async def refuse(domain, service, data, blocking=False, **kw):
        rig.w.calls.append((domain, service, data.get("entity_id"), blocking))
        raise RuntimeError("lock offline")

    rig.w.hass.services.async_call = refuse
    await rig.regime.async_release_if_disabled()
    assert rig.unlocks() == [BED]
    highs = [n for n in rig.nm.notes if n["title"] == "Away Lock release failed"]
    assert len(highs) == 1
    assert highs[0]["severity"] == load("domain_coordinators.base").Severity.HIGH
    assert store.saved["away_lock_owned"] == []


@pytest.mark.asyncio
async def test_g10_sc_disable_mid_engage_stops_loop():
    """The SC-disable release bumps the release epoch, so an engage loop that
    yields after lock 1 never locks lock 2."""
    study = "lock.study_lock"
    rig = await make_rig(opts=options(
        security_lock_entities=[DOOR, BED, study],
        security_lock_sweep_exclude=[BED, study],
        security_away_lock_entities=[BED, study],
    ))
    rig.w.seed(study, "unlocked")
    real = rig.w.hass.services.async_call
    pending = []

    async def yielding(domain, service, data, blocking=False, **kw):
        await real(domain, service, data, blocking=blocking, **kw)
        if (domain, service, data.get("entity_id")) == ("lock", "lock", BED):
            rig.w.cm_entry.options["security_coordinator_enabled"] = False
            pending.append(asyncio.ensure_future(rig.regime.async_release_if_disabled()))
            await asyncio.sleep(0)
            await asyncio.sleep(0)

    rig.w.hass.services.async_call = yielding
    await rig.both_out()
    await asyncio.gather(*pending)
    assert rig.locks() == [BED]
    assert rig.unlocks() == [BED]


@pytest.mark.asyncio
async def test_g11_engage_call_failure_clears_inflight():
    rig = await make_rig()

    async def boom(domain, service, data, blocking=False, **kw):
        rig.w.calls.append((domain, service, data.get("entity_id"), blocking))
        raise RuntimeError("zwave timeout")

    rig.w.hass.services.async_call = boom
    await rig.both_out()
    assert rig.locks() == [BED]
    assert rig.regime._away_engage_inflight == {}
    assert rig.regime._away_readback_unsubs == {}


@pytest.mark.asyncio
async def test_g11_away_lock_call_is_non_blocking():
    rig = await make_rig()
    await rig.both_out()
    assert ("lock", "lock", BED, False) in rig.w.calls


def _dwell_timers(rig):
    return [t for t in rig.w.live_timers()
            if getattr(t["cb"], "__name__", "") == "_on_away_dwell"]


@pytest.mark.asyncio
async def test_g12_rearm_keeps_a_single_dwell_timer():
    rig = await make_rig()
    await rig.person(OJI, "not_home")
    await rig.person(EZ, "not_home")
    for i in range(5):
        rig.w.set_state(OJI, "not_home", {"gps_accuracy": i})
        await settle()
    assert len(_dwell_timers(rig)) == 1
    await rig.w.advance(301)
    assert rig.locks() == [BED]


@pytest.mark.asyncio
async def test_g12_concurrent_engage_runs_once():
    rig = await make_rig()
    await rig.person(OJI, "not_home")
    await rig.person(EZ, "not_home")
    await rig.w.advance(299)
    rig.regime._cancel_away_dwell()
    rig.w.now = rig.w.now + timedelta(seconds=2)
    # The lock state lags the command, so the unlocked check alone cannot
    # stop a second engage; only the attempted guard does.
    _refuse_lock(rig)
    await asyncio.gather(rig.regime._async_away_engage("a"),
                         rig.regime._async_away_engage("b"))
    assert rig.locks() == [BED]


@pytest.mark.asyncio
async def test_g12_release_skips_owned_lock_already_unlocked():
    rig = await _engaged()
    rig.w.seed(BED, "unlocked")  # unlocked with no event reaching the regime
    await rig.person(OJI, "home")
    assert rig.unlocks() == []
    assert rig.regime.away_lock_owned == set()


def test_live_keys_in_reload_suppress_and_no_live_attr_sets():
    init = load("__init__")
    for key in ("security_lock_sweep_exclude", "security_away_lock_enabled",
                "security_away_lock_persons"):
        assert key in init.OPTIONS_RELOAD_SUPPRESS_KEYS, key
        assert key in init._NO_LIVE_ATTR_KEYS, key
    assert "security_away_lock_entities" not in init.OPTIONS_RELOAD_SUPPRESS_KEYS
    assert "security_away_lock_entities" not in init._NO_LIVE_ATTR_KEYS


@pytest.mark.asyncio
async def test_setup_warns_on_unsupported_overlap(caplog):
    import logging

    caplog.set_level(logging.WARNING)
    await make_rig(opts=options(security_lock_sweep_exclude=[BED, LOCK_A],
                                security_away_lock_entities=[BED, DOOR]))
    text = caplog.text
    assert "both remote lockouts and never-auto-lock" in text
    assert "not in Never auto-lock" in text
