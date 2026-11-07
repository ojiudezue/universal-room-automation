"""GARAGE-REMOTE-LOCKOUT-SCHEDULE-1 — review C gap anchors.

Each test closes a site review C (per-site source mutation) found GREEN.
The reviewer's probes (scratchpad reviewC/test_zz_reviewC_probes.py) are the
starting oracles, extended to every leg the review named. Imports only
non-test helpers from test_sc_garage_lockout so nothing is collected twice.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from types import SimpleNamespace

import pytest

from _lockout_harness import settle
from test_sc_garage_lockout import (
    COVER_A,
    EZ,
    EZ_DIST,
    KIOSK,
    LOCK_A,
    LOCK_B,
    NIGHT,
    OJI,
    TZ,
    R,
    const,
    make_rig,
    options,
    sec,
)


def _intent(rig, reason, *, reengage=False):
    return {"reason": reason, "trigger": "t", "gen": rig.regime.release_gen,
            "reengage": reengage}


# ---- F1: kill switch OFF makes every non-forced release inert --------------

@pytest.mark.asyncio
async def test_kill_off_arrival_does_not_unlock():
    rig = await make_rig(opts=options(security_garage_lockout_enabled=False),
                         lockouts="locked")
    await rig.person(EZ, "home")
    rig.sc._handle_person_arriving_signal({"person_entity": OJI})
    rig.w.set_state(EZ_DIST, "6000", {"unit_of_measurement": "ft"})
    rig.w.set_state(EZ_DIST, "100", {"unit_of_measurement": "ft"})
    await rig.edge("arriving")
    assert rig.unlocks() == []


# ---- F2a: proximity is an edge, radius 0 = off -----------------------------

@pytest.mark.asyncio
async def test_proximity_staying_inside_does_not_release_again():
    rig = await make_rig(lockouts="locked")
    rig.w.set_state(EZ_DIST, "6000", {"unit_of_measurement": "ft"})
    rig.w.set_state(EZ_DIST, "3000", {"unit_of_measurement": "ft"})  # crossing
    await settle()  # unlock task runs and schedules its read-back
    await rig.w.advance(25)  # read-back done: latch clear
    assert rig.regime._release_inflight == set()
    assert rig.unlocks() == [LOCK_A, LOCK_B]
    rig.w.set_state(LOCK_A, "locked")
    rig.w.set_state(LOCK_B, "locked")
    rig.w.calls.clear()
    rig.w.set_state(EZ_DIST, "2000", {"unit_of_measurement": "ft"})  # still inside
    await settle()
    assert rig.unlocks() == []


@pytest.mark.asyncio
async def test_proximity_exactly_at_radius_counts_and_from_radius_does_not():
    """1500 m radius: 1600 m -> 1500 m is a crossing (<=); 1500 m -> 1400 m
    is not (prev must be strictly outside)."""
    rig = await make_rig(lockouts="locked")
    rig.w.set_state(EZ_DIST, "1600", {"unit_of_measurement": "m"})
    rig.w.set_state(EZ_DIST, "1500", {"unit_of_measurement": "m"})
    await settle()
    assert rig.unlocks() == [LOCK_A, LOCK_B]
    rig2 = await make_rig(lockouts="locked")
    rig2.w.set_state(EZ_DIST, "1500", {"unit_of_measurement": "m"})
    rig2.w.set_state(EZ_DIST, "1400", {"unit_of_measurement": "m"})
    await settle()
    assert rig2.unlocks() == []


@pytest.mark.asyncio
async def test_proximity_radius_zero_off_even_at_zero_distance():
    """Live proximity reads 0.0 inside the home zone; radius 0 = P5 off."""
    rig = await make_rig(lockouts="locked", opts=options(garage_lockout_approach_radius_m=0))
    rig.w.set_state(EZ_DIST, "6000", {"unit_of_measurement": "ft"})
    rig.w.set_state(EZ_DIST, "0.0", {"unit_of_measurement": "ft"})
    await settle()
    assert rig.unlocks() == []


# ---- F2b: approach zone -------------------------------------------------------

ZONE = "zone.home_approach"


def _zone_rig_opts():
    return options(security_lockout_approach_zone=ZONE)


async def _zone_rig():
    rig = await make_rig(lockouts="locked", opts=_zone_rig_opts())
    rig.w.set_state(ZONE, "0", {"friendly_name": "Near House"})
    return rig


@pytest.mark.asyncio
async def test_approach_zone_friendly_name_releases():
    rig = await _zone_rig()
    await rig.person(EZ, "Near House")
    assert rig.unlocks() == [LOCK_A, LOCK_B]
    assert rig.regime.last_action["trigger"] == f"approach_zone:{EZ}"


@pytest.mark.asyncio
async def test_approach_zone_case_insensitive():
    rig = await _zone_rig()
    await rig.person(EZ, "NEAR HOUSE")
    assert rig.unlocks() == [LOCK_A, LOCK_B]


@pytest.mark.asyncio
async def test_approach_zone_other_zone_and_same_state_no_release():
    rig = await _zone_rig()
    await rig.person(EZ, "Work")
    assert rig.unlocks() == []
    await rig.person(EZ, "Near House")
    await settle()
    await rig.w.advance(25)
    assert rig.regime._release_inflight == set()
    rig.w.set_state(LOCK_A, "locked")
    rig.w.set_state(LOCK_B, "locked")
    rig.w.calls.clear()
    rig.w.set_state(EZ, "Near House", {"gps_accuracy": 5})  # attribute-only update
    await settle()
    assert rig.unlocks() == []


# ---- F3: guest clock ----------------------------------------------------------

@pytest.mark.asyncio
async def test_guest_clock_sets_reason_and_backstop_releases():
    rig = await make_rig(start=datetime(2026, 11, 7, 20, 0, tzinfo=TZ))
    await rig.edge("guest")
    await rig.w.advance(2.5 * 3600)  # 22:00 clock
    assert rig.locks() == [LOCK_A, LOCK_B]
    assert rig.regime.reason == "guest_night"
    await rig.w.advance(10 * 3600)  # past 07:00
    assert rig.unlocks() == [LOCK_A, LOCK_B]


@pytest.mark.asyncio
async def test_guest_clock_rearms_next_day():
    rig = await make_rig(start=datetime(2026, 11, 7, 20, 0, tzinfo=TZ))
    await rig.edge("guest")
    await rig.w.advance(2.5 * 3600)
    await rig.edge("home_day")
    rig.w.calls.clear()
    await rig.w.advance(24 * 3600 - 3 * 3600)
    rig.mgr.house_state = "guest"
    rig.w.calls.clear()
    await rig.w.advance(3 * 3600)
    assert rig.locks() == [LOCK_A, LOCK_B]


@pytest.mark.asyncio
async def test_guest_clock_kill_switch_off_inert():
    rig = await make_rig(start=datetime(2026, 11, 7, 21, 0, tzinfo=TZ), house="guest",
                         opts=options(security_garage_lockout_enabled=False))
    await rig.w.advance(2 * 3600)
    assert rig.locks() == [] and rig.regime.reason == "none"


@pytest.mark.asyncio
async def test_guest_clock_toggle_off_inert():
    rig = await make_rig(start=datetime(2026, 11, 7, 21, 0, tzinfo=TZ), house="guest",
                         opts=options(security_lockout_engage_on_guest_sleep=False))
    await rig.w.advance(2 * 3600)
    assert rig.locks() == [] and rig.regime.reason == "none"


@pytest.mark.asyncio
async def test_guest_clock_inside_boot_window_inert():
    rig = await make_rig(start=datetime(2026, 11, 7, 21, 59, tzinfo=TZ), house="guest",
                         past_boot=False)
    await rig.w.advance(90)  # clock fires at 60 s, inside the 120 s window
    assert rig.locks() == [] and rig.regime.reason == "none"


# ---- F4: read-back exhaustion clears the latch ------------------------------

@pytest.mark.asyncio
async def test_latch_cleared_after_readback_retries_exhausted():
    rig = await make_rig(lockouts="locked")
    rig.w.apply_service_state = False  # unlock never lands
    await rig.person(EZ, "home")
    await rig.w.advance(600)
    assert rig.regime._release_inflight == set()
    rig.w.calls.clear()
    await rig.edge("arriving")  # a later release for the same lock still works
    assert rig.unlocks() == [LOCK_A, LOCK_B]


# ---- F5: each write-time predicate conjunct -----------------------------------

@pytest.mark.asyncio
async def test_predicate_vacation_house_left():
    rig = await make_rig()
    rig.mgr.house_state = "sleep"
    assert rig.regime.engage_predicate(_intent(rig, "vacation"), LOCK_A) == "house_left_vacation"


@pytest.mark.asyncio
async def test_predicate_guest_toggle_off():
    rig = await make_rig(opts=options(security_lockout_engage_on_guest_sleep=False))
    rig.mgr.house_state = "guest"
    assert rig.regime.engage_predicate(_intent(rig, "guest_night"), LOCK_A) == "guest_night_ended"


@pytest.mark.asyncio
async def test_predicate_guest_outside_window():
    rig = await make_rig(start=datetime(2026, 11, 7, 12, 0, tzinfo=TZ), house="guest")
    assert rig.regime.engage_predicate(_intent(rig, "guest_night"), LOCK_A) == "guest_night_ended"


@pytest.mark.asyncio
async def test_predicate_sc_disabled():
    rig = await make_rig()
    rig.mgr.house_state = "sleep"
    rig.sc.enabled = False
    assert rig.regime.engage_predicate(_intent(rig, "sleep"), LOCK_A) == "sc_not_running"


@pytest.mark.asyncio
async def test_predicate_sc_shutting_down():
    rig = await make_rig()
    rig.mgr.house_state = "sleep"
    rig.sc._shutting_down = True
    assert rig.regime.engage_predicate(_intent(rig, "sleep"), LOCK_A) == "sc_not_running"


@pytest.mark.asyncio
async def test_predicate_lockout_already_locked():
    rig = await make_rig(lockouts="locked")
    rig.mgr.house_state = "sleep"
    assert rig.regime.engage_predicate(_intent(rig, "sleep"), LOCK_A) == "lockout_locked"


@pytest.mark.asyncio
async def test_predicate_reengage_row_checked_at_write():
    rig = await make_rig()
    rig.mgr.house_state = "sleep"
    rig.regime.reason = "sleep"
    rig.w.set_state(COVER_A, "open")
    assert rig.regime.engage_predicate(_intent(rig, "sleep", reengage=True), LOCK_A) == (
        f"door_not_closed:{COVER_A}"
    )
    assert rig.regime.engage_predicate(_intent(rig, "sleep"), LOCK_A) is None


# ---- F5b: house-state release only undoes the regime's OWN engage -------------

@pytest.mark.asyncio
async def test_home_or_waking_edge_does_not_unlock_a_lock_the_regime_did_not_engage():
    """Explicit rule: a HOME_* / WAKING edge releases only when the regime
    holds a reason (it engaged, or rebuilt one at boot). A lock the operator
    set by hand is released by a resident ARRIVAL (INV-2, any engager) or by
    the kill switch, not by a house-state edge."""
    rig = await make_rig()
    rig.w.set_state(LOCK_A, "locked")
    rig.w.set_state(LOCK_B, "locked")
    rig.w.calls.clear()
    assert rig.regime.reason == "none"
    await rig.edge("home_day")
    await rig.edge("waking")
    assert rig.unlocks() == []
    await rig.person(EZ, "home")  # an arrival still releases it
    assert rig.unlocks() == [LOCK_A, LOCK_B]


# ---- F6: each guard against an engage queued before an SC disable -------------

@pytest.mark.asyncio
async def test_disable_release_bumps_generation_alone(monkeypatch):
    rig = await make_rig(lockouts="locked")
    rig.mgr.house_state = "sleep"
    queued = _intent(rig, "sleep")
    rig.w.cm_entry.options["security_coordinator_enabled"] = False
    await rig.regime.async_release_if_disabled()
    rig.w.set_state(LOCK_A, "unlocked")
    monkeypatch.setattr(rig.regime, "_sc_alive", lambda: True)  # other guard off
    assert rig.regime.engage_predicate(queued, LOCK_A) == "release_since_intent"


@pytest.mark.asyncio
async def test_sc_alive_guard_alone_blocks_engage_during_teardown():
    rig = await make_rig()
    rig.mgr.house_state = "sleep"
    queued = _intent(rig, "sleep")  # generation unchanged: gen guard passes
    rig.sc._shutting_down = True
    assert rig.regime.engage_predicate(queued, LOCK_A) == "sc_not_running"


# ---- F7: teardown wait is bounded and leftovers are cancelled ------------------

@pytest.mark.asyncio
async def test_teardown_wait_bounded_and_hung_unlock_cancelled(monkeypatch):
    rig = await make_rig(lockouts="locked")
    never = asyncio.Event()
    orig = rig.w.hass.services.async_call

    async def hang(domain, service, data, blocking=False, **kw):
        if service == "unlock":
            rig.w.calls.append((domain, service, data["entity_id"], blocking))
            await never.wait()
        else:
            await orig(domain, service, data, blocking=blocking, **kw)

    rig.w.hass.services.async_call = hang
    await rig.person(EZ, "home")
    tasks = list(rig.regime._unlock_tasks)
    assert len(tasks) == 2
    monkeypatch.setattr(const, "GARAGE_LOCKOUT_TEARDOWN_RELEASE_TIMEOUT_S", 0.05)
    await asyncio.wait_for(rig.regime.async_teardown(), 2)
    await settle()
    assert all(t.cancelled() for t in tasks)


# ---- F8: vacation is never released by the backstop (live path) ---------------

@pytest.mark.asyncio
async def test_sleep_then_vacation_backstop_does_not_release():
    rig = await make_rig(start=NIGHT)
    await rig.edge("sleep")
    await rig.edge("vacation")
    await rig.w.advance(10 * 3600)
    assert rig.unlocks() == []
    assert rig.regime.reason == "vacation"


# ---- F9 / F11 / F16 ------------------------------------------------------------

@pytest.mark.asyncio
async def test_non_fire_hazard_type_does_not_release():
    rig = await make_rig(lockouts="locked", opts=options(security_on_hazard_unlock_egress=True))
    rig.sc._handle_safety_hazard({"hazard_type": "water_leak", "severity": "critical"})
    await settle()
    assert rig.unlocks() == []


@pytest.mark.asyncio
async def test_arriving_signal_release_schedules_reengage():
    rig = await make_rig()
    await rig.edge("sleep")
    rig.regime.on_person_arriving({"person_entity": EZ})
    await settle()
    assert rig.unlocks() == [LOCK_A, LOCK_B]
    assert EZ in rig.regime.releasing_set
    assert rig.regime.reengage_at is not None


@pytest.mark.asyncio
async def test_unmapped_distance_sensor_still_releases():
    rig = await make_rig(lockouts="locked", opts=options(
        security_lockout_distance_sensors=[EZ_DIST, "sensor.mystery_thing"]))
    rig.w.set_state("sensor.mystery_thing", "50000", {"unit_of_measurement": "m"})
    rig.w.set_state("sensor.mystery_thing", "100", {"unit_of_measurement": "m"})
    await settle()
    assert rig.unlocks() == [LOCK_A, LOCK_B]


@pytest.mark.asyncio
async def test_person_mapping_needs_delimited_suffix():
    rig = await make_rig(persons={"person.ez": "not_home", EZ: "not_home",
                                  OJI: "home", KIOSK: "unknown"})
    assert rig.regime._person_for_sensor("sensor.madronehaos_ezinne_distance") == EZ
    assert rig.regime._person_for_sensor("sensor.fooezinne_distance") is None


@pytest.mark.asyncio
async def test_kill_switch_on_edge_is_inert():
    rig = await make_rig(lockouts="locked")
    rig.regime.on_kill_switch_changed(True)
    await settle()
    assert rig.unlocks() == []


@pytest.mark.asyncio
async def test_away_sets_no_reason_and_no_backstop():
    rig = await make_rig()
    await rig.edge("away")
    assert rig.regime.reason == "none"
    assert rig.regime._backstop_unsub is None


@pytest.mark.asyncio
async def test_non_wrapping_sleep_window_end_hour_exclusive():
    rig = await make_rig(start=datetime(2026, 11, 7, 6, 30, tzinfo=TZ),
                         opts=options(sleep_start_hour=1, sleep_end_hour=6))
    assert rig.regime._in_sleep_window(rig.regime._cfg()) is False
    rig.w.now = datetime(2026, 11, 7, 5, 59, tzinfo=TZ)
    assert rig.regime._in_sleep_window(rig.regime._cfg()) is True


@pytest.mark.asyncio
async def test_reengage_delay_zero_schedules_nothing():
    rig = await make_rig(opts=options(garage_lockout_reengage_delay_s=0))
    await rig.edge("sleep")
    await rig.person(EZ, "home")
    assert rig.regime._reengage_unsub is None
    assert rig.regime.reengage_at is None


# ---- F10: boot recheck upgrade feeds re-engage ----------------------------------

@pytest.mark.asyncio
async def test_boot_recheck_upgrade_to_sleep_enables_reengage():
    rig = await make_rig(start=datetime(2026, 11, 8, 2, 0, tzinfo=TZ), house="home_night",
                         lockouts="locked", past_boot=False)
    assert rig.regime.reason == "boot_unknown"
    rig.mgr.house_state = "sleep"
    await rig.w.advance(121)
    assert rig.regime.reason == "sleep"
    await rig.w.advance(600)
    await rig.person(EZ, "home")
    assert rig.regime.reengage_at is not None


# ---- F13 / F15: Store shape ------------------------------------------------------

@pytest.mark.asyncio
async def test_store_dict_residents_rejected_with_warning(caplog):
    class Store:
        async def async_load(self):
            return {"residents": {"person.ziri": 1}}

        def async_delay_save(self, fn, delay):
            pass

    with caplog.at_level(logging.WARNING):
        rig = await make_rig(lockouts="locked", store=Store())
    subscribed = set().union(*(rec["ids"] for rec in rig.w.listeners))
    assert "person.ziri" not in subscribed
    assert "unexpected shape" in caplog.text


@pytest.mark.asyncio
async def test_store_list_with_non_str_rejected_with_warning(caplog):
    class Store:
        async def async_load(self):
            return {"residents": ["person.ziri", 5]}

        def async_delay_save(self, fn, delay):
            pass

    with caplog.at_level(logging.WARNING):
        rig = await make_rig(lockouts="locked", store=Store())
    subscribed = set().union(*(rec["ids"] for rec in rig.w.listeners))
    assert "person.ziri" not in subscribed
    assert "unexpected shape" in caplog.text


# ---- F12: SC-side isolation ---------------------------------------------------------

@pytest.mark.asyncio
async def test_regime_error_never_touches_arming_path():
    rig = await make_rig()
    queued = []
    rig.mgr.queue_intent = queued.append
    rig.sc._auto_follow_house_state = True

    def boom(payload):
        raise RuntimeError("regime bug")

    rig.regime.on_house_state_changed = boom
    rig.sc._on_house_state_changed_signal({"new_state": "sleep"})
    assert [i.source for i in queued] == ["house_state_change"]


@pytest.mark.asyncio
async def test_sc_setup_survives_regime_setup_failure(monkeypatch):
    rig = await make_rig()

    class Broken:
        def __init__(self, *a, **k):
            raise RuntimeError("no regime")

    monkeypatch.setattr(R, "LockRegimeController", Broken)
    rig.sc._lock_regime = None
    await rig.sc._async_setup_lock_regime()  # must not raise
    assert rig.sc.lock_regime is None


def test_layer2_veto_fails_closed_when_predicate_raises(monkeypatch):
    from _lockout_harness import load

    cov = load("cover_ownership")

    def boom(*a, **k):
        raise RuntimeError("x")

    monkeypatch.setattr(cov, "is_security_owned_or_configured_cover", boom)
    hass = SimpleNamespace(states=SimpleNamespace(get=lambda e: None), data={})
    sc = sec.SecurityCoordinator(hass)
    assert sc.honor_optimizer_intent({"target_entity": "cover.living_room_blind"}) is False
    assert sc._last_veto_reason == "security_owned_cover"
