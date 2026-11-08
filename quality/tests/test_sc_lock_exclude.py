"""SC-LOCK-SWEEP-EXCLUDE-1 D2 — exclusion at every lock emission site.

Plan: docs/planning/PLANNING_sc_lock_exclude_and_door_regime.md rev 3 (D2,
§2.1 consumers, §3 sites S1/S2/S3/U1). Every test drives REAL production code
(SecurityCoordinator, LockRegimeController, the sensor entities, the
optimizer posture dimension, the `doors` diag) and asserts on returned
actions / attributes / the recorded service stream. No source greps.

Invariant guarded (INV-X1): no URA lock.lock ever targets an entity in
``security_lock_sweep_exclude`` (except the away-lock engage, tested in
test_sc_away_lock.py). Bug Class #53 (computed-but-not-consumed): every site
that iterates ``_lock_entities`` is covered by its own test.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from _lockout_harness import TZ, World, load, settle

const = load("const")
R = load("domain_coordinators.security_lock_regime")
sec = load("domain_coordinators.security")

DOOR = "lock.doorlock_kwikset_zwave_frontentry"
HALL = "lock.garage_hallway_doorlock_kwikset916_zwave_garagehallway"
BED = "lock.master_bedroom_lock"
LOCK_A = "lock.konnected_f0f5bd523b00_lock"
LOCK_B = "lock.ratgdov25i_dbfe2a_lock_remotes"
COVER = "cover.konnected_f0f5bd523b00_garage_door"
CAM = "camera.front"

DAY = datetime(2026, 11, 7, 10, 0, 0, tzinfo=TZ)


def options(**over):
    opts = {
        "security_lock_entities": [DOOR, HALL, BED],
        "security_lock_sweep_exclude": [BED],
        "security_lockout_entities": [LOCK_A, LOCK_B],
        "security_garage_entities": [COVER],
        "security_coordinator_enabled": True,
    }
    opts.update(over)
    return opts


def make_sc(*, opts=None, states=None, regime=False, cameras=None):
    w = World(DAY, opts if opts is not None else options(),
              entry_type=const.ENTRY_TYPE_COORDINATOR_MANAGER)
    w.hass.data[const.DOMAIN] = {"coordinator_manager": SimpleNamespace(house_state="away")}
    for eid, st in (states or {DOOR: "unlocked", HALL: "locked", BED: "unlocked"}).items():
        w.seed(eid, st)
    w.seed(COVER, "closed", {"device_class": "garage"})
    for cam in cameras or []:
        w.seed(cam, "streaming")
    sc = sec.SecurityCoordinator(
        w.hass, lock_entities=[DOOR, HALL, BED], garage_entities=[COVER],
        camera_entities=list(cameras or []),
    )
    if regime:
        sc._lock_regime = R.LockRegimeController(
            w.hass, sc, now=w.clock, call_later=w.call_later,
            track_state=w.track_state, track_added_domain=w.track_added,
            track_removed_domain=w.track_removed,
        )
    return w, sc


def _lock_targets(actions):
    return [a.service_data["entity_id"] for a in actions
            if getattr(a, "service", None) == "lock.lock"]


# ---------------------------------------------------------------- S2 sweep


@pytest.mark.asyncio
async def test_sweep_skips_excluded_unlocked():
    w, sc = make_sc()
    actions = await sc._evaluate_lock_check()
    # Discrimination: the NON-excluded unlocked lock IS commanded.
    assert _lock_targets(actions) == [DOOR]
    assert sc.last_lock_sweep["found_unlocked"] == [DOOR]
    assert sc.last_lock_sweep["lock_actions_sent"] == [DOOR]
    assert sc.last_lock_sweep["excluded"] == [BED]


@pytest.mark.asyncio
async def test_sweep_excluded_absent_is_todays_behaviour():
    w, sc = make_sc(opts=options(security_lock_sweep_exclude=[]))
    actions = await sc._evaluate_lock_check()
    assert _lock_targets(actions) == [DOOR, BED]
    assert sc.last_lock_sweep["excluded"] == []


@pytest.mark.asyncio
async def test_sweep_exclude_entry_not_in_lock_list_has_no_effect():
    w, sc = make_sc(opts=options(security_lock_sweep_exclude=["lock.gone"]))
    actions = await sc._evaluate_lock_check()
    assert _lock_targets(actions) == [DOOR, BED]


@pytest.mark.asyncio
async def test_excluded_unavailable_still_notified():
    w, sc = make_sc(states={DOOR: "locked", HALL: "locked", BED: "unavailable"})
    actions = await sc._evaluate_lock_check()
    assert _lock_targets(actions) == []
    assert sc.last_lock_sweep["unavailable"] == [BED]
    msgs = [a.message for a in actions if hasattr(a, "message")]
    assert any("offline" in m and BED in m for m in msgs), msgs


@pytest.mark.asyncio
async def test_exclude_live_no_reload():
    """The exclude list is read live from the CM entry at each sweep."""
    w, sc = make_sc(opts=options(security_lock_sweep_exclude=[]))
    assert _lock_targets(await sc._evaluate_lock_check()) == [DOOR, BED]
    w.cm_entry.options = {**w.cm_entry.options, "security_lock_sweep_exclude": [BED]}
    assert _lock_targets(await sc._evaluate_lock_check()) == [DOOR]


@pytest.mark.asyncio
async def test_exclude_read_through_regime_when_present():
    w, sc = make_sc(regime=True)
    assert _lock_targets(await sc._evaluate_lock_check()) == [DOOR]


@pytest.mark.asyncio
async def test_sweep_excluded_no_retry_episode():
    """Retry-cap branch not merged (orchestrator: build against develop).
    The excluded lock opens no compliance follow-up: compliance checks are
    scheduled only for commanded locks."""
    w, sc = make_sc()
    scheduled = []

    class CT:
        async def schedule_check(self, **kw):
            scheduled.append(kw)

    sc.compliance_tracker = CT()
    for _ in range(3):
        await sc._evaluate_lock_check()
    ents = [kw["device_id"] for kw in scheduled]
    assert ents == [DOOR, DOOR, DOOR]


# ---------------------------------------------------------------- S1 lockdown


@pytest.mark.asyncio
async def test_lockdown_skips_excluded():
    w, sc = make_sc()
    # Caller 1: unknown person (census intent path).
    sc._sanction_checker = SimpleNamespace(has_unknown_persons=lambda ctx: True)
    actions = sc._handle_census_intent(SimpleNamespace(data={}), {})
    assert _lock_targets(actions) == [DOOR, HALL]
    # Caller 2: entry alert path.
    actions = sc._verdict_to_actions(sec.EntryVerdict.ALERT_HIGH, "binary_sensor.front_door")
    assert _lock_targets(actions) == [DOOR, HALL]
    # Garage covers unchanged.
    assert any(getattr(a, "service", None) == "cover.close_cover" for a in actions)


def test_lockdown_without_exclude_locks_all():
    w, sc = make_sc(opts=options(security_lock_sweep_exclude=[]))
    assert _lock_targets(sc._generate_lockdown_actions("x")) == [DOOR, HALL, BED]


# ---------------------------------------------------------------- S3 garage engage


@pytest.mark.asyncio
async def test_lockout_engage_skips_excluded_runtime_guard():
    """A legacy options state with a lock in both exclude and lockout lists
    (the validator rejects it now): the garage engage never locks it."""
    opts = options(
        security_garage_lockout_enabled=True,
        security_lock_sweep_exclude=[BED, LOCK_A],
    )
    w = World(datetime(2026, 11, 7, 23, 0, tzinfo=TZ), opts,
              entry_type=const.ENTRY_TYPE_COORDINATOR_MANAGER)
    mgr = SimpleNamespace(house_state="home_night")
    w.hass.data[const.DOMAIN] = {"coordinator_manager": mgr}
    for ent in (LOCK_A, LOCK_B):
        w.seed(ent, "unlocked")
    sc = sec.SecurityCoordinator(w.hass, lock_entities=[DOOR], garage_entities=[])
    regime = R.LockRegimeController(
        w.hass, sc, now=w.clock, call_later=w.call_later, track_state=w.track_state,
        track_added_domain=w.track_added, track_removed_domain=w.track_removed,
    )
    sc._lock_regime = regime
    await regime.async_setup()
    await w.advance(601)
    w.calls.clear()
    mgr.house_state = "sleep"
    sc._on_house_state_changed_signal({"old_state": "home_night", "new_state": "sleep"})
    await settle()
    assert w.locks_called("lock") == [LOCK_B]
    dropped = regime.last_action
    assert dropped["action"] in ("engage", "engage_dropped_stale")
    # The drop for LOCK_A was recorded with why=excluded.
    assert regime.engage_predicate(
        {"reason": "sleep", "trigger": "t", "gen": regime.release_gen}, LOCK_A
    ) == "excluded"


# ---------------------------------------------------------------- U1 hazard


@pytest.mark.asyncio
async def test_hazard_unlock_still_includes_excluded():
    opts = options(security_on_hazard_unlock_egress=True)
    w, sc = make_sc(opts=opts, states={DOOR: "locked", HALL: "locked", BED: "locked"})
    sc._get_signal_config = lambda key: True
    sc._handle_safety_hazard({"hazard_type": "smoke", "severity": "critical"})
    await settle()
    assert sorted(w.locks_called("unlock")) == sorted([DOOR, HALL, BED])


# ---------------------------------------------------------------- display consumers


def _agg_sensor(w, sc):
    sensor_mod = load("sensor")
    w.hass.data[const.DOMAIN]["coordinator_manager"] = SimpleNamespace(
        coordinators={"security": sc}, house_state="away"
    )
    ent = sensor_mod.SecurityAggregatorSensor.__new__(sensor_mod.SecurityAggregatorSensor)
    ent.hass = w.hass
    return ent


def test_aggregator_excludes_excluded():
    w, sc = make_sc(states={DOOR: "locked", HALL: "locked", BED: "unlocked"}, cameras=[CAM])
    ent = _agg_sensor(w, sc)
    attrs = ent.extra_state_attributes
    assert ent.native_value == "armed"
    assert attrs["locks_total"] == 2
    assert attrs["locks_locked"] == 2
    assert attrs["locks_unlocked"] == 0
    assert attrs["locks_excluded"] == 1


def test_aggregator_without_exclude_is_partial():
    w, sc = make_sc(opts=options(security_lock_sweep_exclude=[]),
                    states={DOOR: "locked", HALL: "locked", BED: "unlocked"}, cameras=[CAM])
    ent = _agg_sensor(w, sc)
    assert ent.native_value == "partial"
    assert ent.extra_state_attributes["locks_excluded"] == 0
    assert ent.extra_state_attributes["locks_unlocked"] == 1


def test_aggregator_fallback_shape_has_locks_excluded():
    sensor_mod = load("sensor")
    w, sc = make_sc()
    ent = sensor_mod.SecurityAggregatorSensor.__new__(sensor_mod.SecurityAggregatorSensor)
    ent.hass = w.hass  # no manager coordinators -> fallback
    w.hass.data[const.DOMAIN] = {}
    attrs = ent.extra_state_attributes
    assert attrs["locks_excluded"] == 0
    assert len(attrs) == 10


def test_last_lock_sweep_sensor_exposes_excluded():
    sensor_mod = load("sensor")
    w, sc = make_sc()
    sc._last_lock_sweep = {"timestamp": "2026-11-07T16:00:00+00:00", "excluded": [BED]}
    w.hass.data[const.DOMAIN]["coordinator_manager"] = SimpleNamespace(coordinators={"security": sc})
    ent = sensor_mod.SecurityLastLockSweepSensor.__new__(sensor_mod.SecurityLastLockSweepSensor)
    ent.hass = w.hass
    assert ent.extra_state_attributes["excluded"] == [BED]


def test_posture_anomaly_ignores_excluded_unlocked():
    opt = load("domain_coordinators.optimization")

    def run(exclude):
        w, sc = make_sc(opts=options(security_lock_sweep_exclude=exclude),
                        states={DOOR: "locked", HALL: "locked", BED: "unlocked"})
        fake = SimpleNamespace(
            _get_security_coordinator=lambda: sc,
            _get_house_state_machine=lambda: SimpleNamespace(state="away"),
            _cycle_dedup=set(),
        )
        return opt.OptimizationCoordinator._evaluate_security_posture_dimension(fake)

    assert run([BED]) == []
    assert len(run([])) == 1  # discrimination: same house, not excluded -> fires


@pytest.mark.asyncio
async def test_compliance_rate_never_above_100():
    # excluded locked + one normal unlocked; garage closed.
    w, sc = make_sc(states={DOOR: "unlocked", HALL: "locked", BED: "locked"})
    w.cm_entry.options["security_lock_sweep_exclude"] = [BED]
    await sc._evaluate_lock_check()
    summary = sc.get_compliance_summary()
    # Hand oracle: HALL locked + COVER closed of {DOOR, HALL, COVER}.
    assert summary["total_devices"] == 3
    assert summary["compliant"] == 2
    assert summary["compliance_rate"] == 66.7


@pytest.mark.asyncio
async def test_compliance_rate_excluded_only_locked_is_not_counted():
    w, sc = make_sc(states={DOOR: "unlocked", HALL: "unlocked", BED: "locked"},
                    opts=options(security_garage_entities=[]))
    sc._garage_entities = []
    await sc._evaluate_lock_check()
    summary = sc.get_compliance_summary()
    assert summary["total_devices"] == 2
    assert summary["compliant"] == 0
    assert summary["compliance_rate"] == 0.0


def test_doors_excluded_unlocked_not_problem():
    hs = load("house_status")
    w, sc = make_sc(states={DOOR: "unlocked", HALL: "locked", BED: "unlocked"})
    w.hass.data[const.DOMAIN]["coordinator_manager"] = SimpleNamespace(
        coordinators={"security": sc})
    res = hs.doors(w.hass)
    by = {f.source: f for f in res.fields}
    assert by[BED].problem is False
    assert by[BED].note == "not auto-locked"
    assert by[DOOR].problem is True  # discrimination
    assert by[HALL].note == ""


def test_doors_excluded_jammed_is_problem():
    hs = load("house_status")
    w, sc = make_sc(states={DOOR: "locked", HALL: "locked", BED: "jammed"})
    w.hass.data[const.DOMAIN]["coordinator_manager"] = SimpleNamespace(
        coordinators={"security": sc})
    by = {f.source: f for f in hs.doors(w.hass).fields}
    assert by[BED].problem is True


# ---- Review C G7: _sweep_excluded coercion, intersect and fallback.


@pytest.mark.parametrize(
    "raw, expected",
    [
        (BED, {BED}),                           # a single string (not a list)
        ((BED, DOOR), {BED, DOOR}),             # tuple
        ([BED, "lock.not_registered"], {BED}),  # intersect with the lock list
        (42, set()),                            # junk
        (None, set()),
    ],
)
def test_g7_sweep_excluded_coercion(raw, expected):
    w, sc = make_sc(opts=options(security_lock_sweep_exclude=raw))
    assert sc._sweep_excluded() == expected


@pytest.mark.asyncio
async def test_g7_single_string_exclude_skips_sweep():
    w, sc = make_sc(opts=options(security_lock_sweep_exclude=BED))
    assert _lock_targets(await sc._evaluate_lock_check()) == [DOOR]


def test_g7_sweep_excluded_read_failure_excludes_nothing():
    w, sc = make_sc()

    def boom(domain=None):
        raise RuntimeError("config entries unavailable")

    w.hass.config_entries.async_entries = boom
    assert sc._sweep_excluded() == set()
