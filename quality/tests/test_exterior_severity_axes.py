"""HOUSE-STATE step 1a D5: exterior-person severity (C1 fixed, never lowered).

Plan PLANNING_house_state_axes_step1.md rev 3 D5 / INV-SEV / INV-NO-LOWER.
The managers below are REAL: a real ``CoordinatorManager`` (no ``.presence``
attribute; presence only via ``coordinators``), a real HouseStateMachine, a
real PresenceCoordinator with its residency tracker, and the real
``PerimeterAlertManager._severity_for_current_house_state``. The golden
oracle is develop's resolver output (fixtures/exterior_severity_develop_golden.json,
generated from develop 7d826060), never the code under test. Each switch is
patched in the test body that needs it (fixture rule).
"""

from __future__ import annotations

import json
import logging
import pathlib

import pytest
from homeassistant.core import State

from custom_components.universal_room_automation import const as C
from custom_components.universal_room_automation import perimeter_alert as PA
from custom_components.universal_room_automation.domain_coordinators.base import Severity
from custom_components.universal_room_automation.domain_coordinators.house_state import (
    HouseState,
    HouseStateMachine,
)
from custom_components.universal_room_automation.domain_coordinators.manager import (
    CoordinatorManager,
)
from test_residency_wiring import EZ, OJI, T_SETUP, _coord, _feed, _registry

GOLDEN = json.loads(
    (pathlib.Path(__file__).resolve().parent / "fixtures"
     / "exterior_severity_develop_golden.json").read_text())["cells"]
STATES = ["away", "vacation", "sleep", "home_night", "guest", "home_day",
          "home_evening", "arriving", "waking"]
CCS = ["perimeter", "egress", "other"]
TCS = ["approach", "linger", "first_sighting", "circling"]
RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}


def _manager(hass, presence, state):
    mgr = object.__new__(CoordinatorManager)
    mgr._coordinators = {"presence": presence}
    mgr._house_state_machine = HouseStateMachine(initial_state=HouseState(state))
    hass.data[C.DOMAIN]["coordinator_manager"] = mgr
    return mgr


def _pam(hass):
    pam = object.__new__(PA.PerimeterAlertManager)
    pam.hass = hass
    return pam


def _world(state="arriving", *, states=None):
    hass, coord, st = _coord(states=states or {})
    _manager(hass, coord, state)
    return hass, coord, st, _pam(hass)


def _sev(pam, cc="perimeter", tc="approach"):
    return pam._severity_for_current_house_state(camera_class=cc, track_class=tc)


# ============================================================================
# INV-SEV: ARRIVING needs resident evidence
# ============================================================================


@pytest.mark.asyncio
async def test_arriving_no_resident_critical():
    _hass, coord, _st, pam = _world()
    coord._residency_clock.t = T_SETUP + 5000
    assert _sev(pam) == Severity.CRITICAL
    assert _sev(pam, "egress", "first_sighting") == Severity.CRITICAL


@pytest.mark.asyncio
async def test_arriving_recent_counted_arrival_medium():
    """Oji's counted arrival 40 s before; no resident reads home (raw person
    state not seeded) -> the arrival record alone softens to MEDIUM."""
    _hass, coord, _st, pam = _world()
    _feed(coord, OJI, "not_home", "home", T_SETUP + 5000)
    coord._residency_clock.t = T_SETUP + 5040
    assert coord.get_residents_home_count() == 0
    assert _sev(pam) == Severity.MEDIUM
    coord._residency_clock.t = T_SETUP + 5000 + 301  # outside the 300 s window
    assert _sev(pam) == Severity.CRITICAL


@pytest.mark.asyncio
async def test_arriving_stale_or_boot_arrival_critical():
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace

    # Boot-window arrival (100 s after setup) -> refused.
    _hass, coord, _st, pam = _world()
    _feed(coord, OJI, "not_home", "home", T_SETUP + 100)
    coord._residency_clock.t = T_SETUP + 140
    assert _sev(pam) == Severity.CRITICAL
    # Stale-source arrival -> refused.
    _hass2, coord2, st2, pam2 = _world()
    src = "device_tracker.ez_ipad"
    now = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)
    st2[src] = State(src, "home", last_changed=now - timedelta(seconds=4119))
    coord2._residency_clock.t = T_SETUP + 5000
    coord2._handle_geofence_change(SimpleNamespace(data={
        "entity_id": EZ, "old_state": State(EZ, "not_home"),
        "new_state": State(EZ, "home", {"source": src}, last_changed=now)}))
    coord2._residency_clock.t = T_SETUP + 5040
    assert coord2._residency.recent[-1].source_stale is True
    assert _sev(pam2) == Severity.CRITICAL


@pytest.mark.asyncio
async def test_arriving_resident_home_medium():
    _hass, coord, st, pam = _world()
    coord._residency_clock.t = T_SETUP + 5000
    st[OJI] = State(OJI, "home")
    assert _sev(pam) == Severity.MEDIUM


@pytest.mark.asyncio
async def test_arriving_phone_left_behind_critical(monkeypatch):
    plb = "binary_sensor.ura_ezinne_udezue_phone_left_behind"
    _registry(monkeypatch, {f"{C.DOMAIN}_person_ezinne_udezue_phone_left_behind": plb})
    _hass, coord, st, pam = _world()
    coord._residency_clock.t = T_SETUP + 5000
    st[EZ] = State(EZ, "home")
    st[plb] = State(plb, "on")
    assert _sev(pam) == Severity.CRITICAL
    st[plb] = State(plb, "off")
    assert _sev(pam) == Severity.MEDIUM


@pytest.mark.asyncio
@pytest.mark.parametrize("ph_switch", [False, True])
async def test_arriving_rule_ignores_persons_home_switch(monkeypatch, ph_switch):
    """M4: the ARRIVING arm never reads persons_home. Every resident away ->
    CRITICAL; a resident home -> MEDIUM, whatever the persons_home switch
    (with the switch False persons_home is 0 even with Oji home)."""
    monkeypatch.setattr(C, "EXTERIOR_SEVERITY_PERSONS_HOME_FROM_RESIDENCY", ph_switch)
    monkeypatch.setattr(C, "EXTERIOR_SEVERITY_ARRIVING_NEEDS_RESIDENT", True)
    _hass, coord, st, pam = _world()
    coord._residency_clock.t = T_SETUP + 5000
    st[OJI] = State(OJI, "not_home")
    st[EZ] = State(EZ, "not_home")
    assert _sev(pam) == Severity.CRITICAL
    st[OJI] = State(OJI, "home")
    assert pam._get_persons_home() == (1 if ph_switch else 0)
    assert _sev(pam) == Severity.MEDIUM


@pytest.mark.asyncio
async def test_arriving_switch_off_keeps_medium(monkeypatch):
    monkeypatch.setattr(C, "EXTERIOR_SEVERITY_ARRIVING_NEEDS_RESIDENT", False)
    _hass, coord, _st, pam = _world()
    coord._residency_clock.t = T_SETUP + 5000
    assert _sev(pam) == Severity.MEDIUM


@pytest.mark.asyncio
async def test_arriving_evidence_error_resolves_critical_and_logs(caplog):
    _hass, coord, _st, pam = _world()

    def boom():
        raise RuntimeError("broken presence")

    coord.get_residents_home_count = boom
    with caplog.at_level(logging.INFO, logger=PA.__name__):
        assert _sev(pam) == Severity.CRITICAL
    assert any("ARRIVING exterior-person severity CRITICAL" in r.getMessage()
               for r in caplog.records)


# ============================================================================
# C1: persons_home through the real manager, switch-gated
# ============================================================================


@pytest.mark.asyncio
async def test_persons_home_real_manager_lookup(monkeypatch):
    """Discriminates "lookup still broken": a REAL CoordinatorManager has no
    ``.presence`` attribute; with the switch True, house home_day, Oji home
    (trust), egress camera -> LOW; switch False -> HIGH. The old lookup
    returned 0 in both, so the first case failed on develop."""
    _hass, coord, st, pam = _world("home_day")
    mgr = _hass.data[C.DOMAIN]["coordinator_manager"]
    assert not hasattr(mgr, "presence")
    assert not hasattr(mgr, "_presence_coordinator")
    st[OJI] = State(OJI, "home")
    monkeypatch.setattr(C, "EXTERIOR_SEVERITY_PERSONS_HOME_FROM_RESIDENCY", True)
    assert pam._get_persons_home() == 1
    assert _sev(pam, "egress", "first_sighting") == Severity.LOW
    monkeypatch.setattr(C, "EXTERIOR_SEVERITY_PERSONS_HOME_FROM_RESIDENCY", False)
    assert _sev(pam, "egress", "first_sighting") == Severity.HIGH


@pytest.mark.asyncio
async def test_persons_home_switch_off_is_zero(monkeypatch):
    monkeypatch.setattr(C, "EXTERIOR_SEVERITY_PERSONS_HOME_FROM_RESIDENCY", False)
    _hass, coord, st, pam = _world("home_day")
    st[OJI] = State(OJI, "home")
    st[EZ] = State(EZ, "home")
    assert coord.get_residents_home_count() == 2
    assert pam._get_persons_home() == 0


# ============================================================================
# INV-NO-LOWER / goldens
# ============================================================================


@pytest.mark.asyncio
async def test_no_lower_golden(monkeypatch):
    """With PERSONS_HOME_FROM_RESIDENCY False (two residents at home, so a
    leak would show), every cell resolves >= develop's production value
    (persons_home 0) and differs only on ARRIVING with evidence False."""
    monkeypatch.setattr(C, "EXTERIOR_SEVERITY_PERSONS_HOME_FROM_RESIDENCY", False)
    monkeypatch.setattr(C, "EXTERIOR_SEVERITY_ARRIVING_NEEDS_RESIDENT", True)
    _hass, coord, st, pam = _world("home_day")
    st[OJI] = State(OJI, "home")
    st[EZ] = State(EZ, "home")
    ph = pam._get_persons_home()
    for s in STATES:
        for cc in CCS:
            for tc in TCS:
                base = GOLDEN[f"{s}|{cc}|{tc}|0"]
                for ev in (None, False, True):
                    got = C.NM_HAZARD_EXTERIOR_PERSON_CONTEXTUAL_SEVERITY(
                        s, camera_class=cc, track_class=tc, persons_home=ph,
                        arriving_resident_evidence=ev)
                    assert RANK[got] >= RANK[base], (s, cc, tc, ev, got, base)
                    if s == "arriving" and ev is False:
                        assert got == "CRITICAL"
                    else:
                        assert got == base, (s, cc, tc, ev, got, base)


@pytest.mark.asyncio
async def test_switches_off_golden_full_table(monkeypatch):
    """Both switches False -> every cell equals develop's production resolve
    (persons_home 0), through the real manager, whatever the evidence."""
    monkeypatch.setattr(C, "EXTERIOR_SEVERITY_PERSONS_HOME_FROM_RESIDENCY", False)
    monkeypatch.setattr(C, "EXTERIOR_SEVERITY_ARRIVING_NEEDS_RESIDENT", False)
    for s in STATES:
        _hass, coord, st, pam = _world(s)
        coord._residency_clock.t = T_SETUP + 5000
        for cc in CCS:
            for tc in TCS:
                got = _sev(pam, cc, tc)
                assert got.name == GOLDEN[f"{s}|{cc}|{tc}|0"], (s, cc, tc, got)


def test_flat_table_deleted_no_reader():
    assert not hasattr(C, "NM_HAZARD_EXTERIOR_PERSON_SEVERITY_BY_HOUSE_STATE")
    assert not hasattr(PA, "NM_HAZARD_EXTERIOR_PERSON_SEVERITY_BY_HOUSE_STATE")


def test_fake_manager_coordinators_shape(monkeypatch):
    """Fixture rule (3): the routing fake reaches presence only through
    ``coordinators["presence"]`` and its getters are real (fixed values)."""
    from test_perimeter_alert_nm_routing import _make_hass

    hass, _nm = _make_hass(house_state="home_day", persons_home=2)
    cm = hass.data[C.DOMAIN]["coordinator_manager"]
    fake = cm.coordinators["presence"]
    assert fake.get_residents_home_count() == 2
    assert fake.get_recent_resident_arrival(300) is None
    pam = _pam(hass)
    monkeypatch.setattr(C, "EXTERIOR_SEVERITY_PERSONS_HOME_FROM_RESIDENCY", True)
    assert pam._get_persons_home() == 2
    monkeypatch.setattr(C, "EXTERIOR_SEVERITY_PERSONS_HOME_FROM_RESIDENCY", False)
    assert pam._get_persons_home() == 0
