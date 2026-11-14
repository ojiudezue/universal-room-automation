"""PERIMETER-GATE-EVIDENCE D1 / D1b: daylight-only single-source demotes.

Plan: docs/planning/PLANNING_perimeter_gate_evidence_and_input_health.md
(Part A, D1 + D1b, INV-DAY). Every test drives the REAL handler
(`_async_handle_perimeter_trigger`) through the shared perimeter harness;
the sun is set as a `sun.sun` state, exactly what HA provides. Expected
severities and reasons are written by hand from the plan. Boundary values
are literals, never the imported constants.
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest

from test_perimeter_fp_gates import (  # noqa: E402
    DB_F2,
    DB_KEY,
    DB_PR,
    RP_KEY,
    RP_PR,
    Severity,
    _St,
    _d5,
    _d105,
    _drive,
    _now,
    _perimeter,
    _run,
    _scheduled,
    _sev,
)


def _sun(hass, elev, state="above_horizon"):
    hass._states["sun.sun"] = _St(state, {"elevation": elev})


def _ss(mgr):
    return mgr._last_gate_decisions[RP_KEY]["single_source"]


def _eg(mgr):
    return mgr._last_gate_decisions[DB_KEY]["egress_identity"]


# ---------------------------------------------------------------- D1 (D5)

def test_night_g5_protect_only_not_demoted(monkeypatch):
    """11-08 00:31 shape: Protect-only, eligible, prior 0, no lookback,
    enforce ON, sun at -60 -> original severity, no hold."""
    hass, nm, mgr = _d5(monkeypatch)
    _sun(hass, -60.0, "below_horizon")
    _run(_drive(mgr, RP_PR))
    assert nm.async_notify.await_count == 1
    assert _sev(nm) == Severity.CRITICAL
    d = _ss(mgr)
    assert d["reason"] == "night"
    assert d["would_demote"] is False
    assert d["would_demote_if_day"] is True
    assert d["demoted"] is False
    assert d["is_day"] is False and d["sun_elevation"] == -60.0
    assert 8 not in [delay for delay, _cb in _scheduled]  # no settle hold
    assert mgr._pending_holds == {}
    assert RP_KEY not in mgr._dispatch_in_flight


def test_day_same_inputs_demoted(monkeypatch):
    hass, nm, mgr = _d5(monkeypatch)
    _sun(hass, 20.0)
    _run(_drive(mgr, RP_PR))
    assert _sev(nm) == Severity.LOW
    d = _ss(mgr)
    assert d["reason"] == "single_source" and d["demoted"] is True
    assert d["is_day"] is True


@pytest.mark.parametrize("elev,expected", [
    (0.0, Severity.LOW),          # on the horizon = daylight (>=)
    (-0.01, Severity.CRITICAL),   # just below = night
    (0.01, Severity.LOW),
])
def test_daylight_threshold_boundary(monkeypatch, elev, expected):
    hass, nm, mgr = _d5(monkeypatch)
    _sun(hass, elev)
    _run(_drive(mgr, RP_PR))
    assert _sev(nm) == expected


def _raising_get(hass):
    real = hass._states.get

    def _get(eid):
        if eid == "sun.sun":
            raise RuntimeError("state machine broke")
        return real(eid)
    hass.states.get = _get


@pytest.mark.parametrize("bad", [
    "missing", "unavailable", "unknown", "elev_none", "elev_abc", "raises",
])
def test_sun_unreadable_treated_as_night(monkeypatch, bad):
    hass, nm, mgr = _d5(monkeypatch)
    if bad == "missing":
        hass._states.pop("sun.sun", None)
    elif bad in ("unavailable", "unknown"):
        hass._states["sun.sun"] = _St(bad, {"elevation": 30.0})
    elif bad == "elev_none":
        hass._states["sun.sun"] = _St("above_horizon", {"elevation": None})
    elif bad == "elev_abc":
        hass._states["sun.sun"] = _St("above_horizon", {"elevation": "abc"})
    else:
        _raising_get(hass)
    _run(_drive(mgr, RP_PR))
    assert _sev(nm) == Severity.CRITICAL
    d = _ss(mgr)
    assert d["reason"] == "night" and d["sun_elevation"] is None


def test_sunset_during_settle_not_demoted(monkeypatch):
    hass, nm, mgr = _d5(monkeypatch)
    _sun(hass, 0.1)

    def _sets():
        _sun(hass, -0.1, "below_horizon")
    _run(_drive(mgr, RP_PR, during=_sets))
    assert _sev(nm) == Severity.CRITICAL
    d = _ss(mgr)
    assert d["reason"] == "night_after_settle"
    assert d["would_demote"] is False and d["would_demote_if_day"] is True
    assert d["sun_elevation"] == -0.1
    assert RP_KEY not in mgr._dispatch_in_flight


def test_sunrise_during_settle_still_no_hold_started_at_night(monkeypatch):
    """Night at the decision -> no hold at all (the settle never starts)."""
    hass, nm, mgr = _d5(monkeypatch)
    _sun(hass, -0.1, "below_horizon")
    _run(_drive(mgr, RP_PR, during=lambda: _sun(hass, 5.0)))
    assert _sev(nm) == Severity.CRITICAL
    assert _ss(mgr)["reason"] == "night"


def test_daylight_only_off_byte_identical(monkeypatch):
    """Kill switch False -> develop behaviour at night: demote to LOW with
    develop's decision dict plus the two sun fields only."""
    monkeypatch.setattr(_perimeter, "PERIMETER_SS_DAYLIGHT_ONLY", False)
    hass, nm, mgr = _d5(monkeypatch)
    _sun(hass, -60.0, "below_horizon")
    _run(_drive(mgr, RP_PR))
    assert _sev(nm) == Severity.LOW
    d = _ss(mgr)
    assert set(d) == {
        "gate", "at", "entity_id", "would_demote", "demoted", "reason",
        "severity_before", "enforce", "inputs", "severity_after",
        "sun_elevation", "is_day",
    }
    assert (d["gate"], d["reason"], d["would_demote"], d["demoted"],
            d["severity_before"], d["severity_after"], d["enforce"]) == (
        "single_source", "single_source", True, True, "CRITICAL", "LOW", True)


def test_shadow_mode_records_night(monkeypatch):
    hass, nm, mgr = _d5(monkeypatch, enforce=False)
    _sun(hass, -10.0, "below_horizon")
    _run(_drive(mgr, RP_PR))
    assert _sev(nm) == Severity.CRITICAL
    d = _ss(mgr)
    assert d["reason"] == "night" and d["would_demote"] is False
    # pair: same shadow inputs at day predict a demote
    hass, nm, mgr = _d5(monkeypatch, enforce=False)
    _sun(hass, 10.0)
    _run(_drive(mgr, RP_PR))
    d = _ss(mgr)
    assert d["reason"] == "shadow" and d["would_demote"] is True


def test_agreement_sample_still_opened_at_night(monkeypatch):
    hass, _nm, mgr = _d5(monkeypatch, samples=0, rate_true=0)
    _sun(hass, -30.0, "below_horizon")
    _run(_drive(mgr, RP_PR))
    assert mgr._agreement.has_pending
    mgr._agreement.finalize_due(_now() + timedelta(seconds=61))
    assert mgr._agreement.samples(RP_KEY) == 1


def test_agreement_sample_opened_at_night_when_eligible(monkeypatch):
    """Eligible camera at night: the sample is still opened (the daylight
    test sits after _agreement_open)."""
    hass, _nm, mgr = _d5(monkeypatch)
    _sun(hass, -30.0, "below_horizon")
    _run(_drive(mgr, RP_PR))
    assert mgr._agreement.has_pending


def test_night_branch_still_records_gate(monkeypatch):
    hass, _nm, mgr = _d5(monkeypatch)
    _sun(hass, -30.0, "below_horizon")
    calls = []
    real = mgr._record_gate
    mgr._record_gate = lambda k, d: (calls.append(dict(d)), real(k, d))[1]
    _run(_drive(mgr, RP_PR))
    ss = [c for c in calls if c.get("gate") == "single_source"]
    assert len(ss) == 1 and ss[0]["reason"] == "night"
    assert ss[0]["severity_after"] == "CRITICAL"


# ---------------------------------------------------------------- D1b (D10.5)

def test_egress_uncorroborated_night_not_demoted(monkeypatch):
    hass, nm, mgr = _d105(monkeypatch, corroborate=False)
    _sun(hass, -30.0, "below_horizon")
    _run(_drive(mgr, DB_PR, fire_delays=(20,)))
    assert _sev(nm) == Severity.CRITICAL
    d = _eg(mgr)
    assert d["reason"] == "egress_uncorroborated_night" and d["demoted"] is False
    assert d["is_day"] is False


def test_egress_uncorroborated_day_demoted(monkeypatch):
    hass, nm, mgr = _d105(monkeypatch, corroborate=False)
    _sun(hass, 30.0)
    _run(_drive(mgr, DB_PR, fire_delays=(20,)))
    assert _sev(nm) == Severity.LOW
    assert _eg(mgr)["reason"] == "egress_uncorroborated"


def test_egress_uncorroborated_daylight_knob_off_night_demoted(monkeypatch):
    monkeypatch.setattr(_perimeter, "PERIMETER_EGRESS_UNCORROBORATED_DAYLIGHT_ONLY", False)
    hass, nm, mgr = _d105(monkeypatch, corroborate=False)
    _sun(hass, -30.0, "below_horizon")
    _run(_drive(mgr, DB_PR, fire_delays=(20,)))
    assert _sev(nm) == Severity.LOW
    assert _eg(mgr)["reason"] == "egress_uncorroborated"


def test_egress_uncorroborated_sun_unreadable_not_demoted(monkeypatch):
    hass, nm, mgr = _d105(monkeypatch, corroborate=False)
    hass._states.pop("sun.sun", None)
    _run(_drive(mgr, DB_PR, fire_delays=(20,)))
    assert _sev(nm) == Severity.CRITICAL
    assert _eg(mgr)["reason"] == "egress_uncorroborated_night"


def test_egress_known_person_night_still_demoted(monkeypatch):
    hass, nm, mgr = _d105(monkeypatch)
    _sun(hass, -30.0, "below_horizon")
    cb = [c.args[1] for c in hass.bus.async_listen.call_args_list
          if c.args[0] == "ura_person_egress_event"][0]
    monkeypatch.setattr(_perimeter.dt_util, "parse_datetime",
                        lambda s: _now() - timedelta(seconds=3), raising=False)
    cb(SimpleNamespace(data={"egress_camera": DB_PR, "timestamp": "x",
                             "person_id": "oji_udezue", "identity_confidence": 0.9}))
    _run(mgr._async_handle_perimeter_trigger(DB_PR))
    assert _sev(nm) == Severity.LOW
    assert _eg(mgr)["reason"] == "egress_known_person"


def test_egress_sunset_during_xcorr_settle_not_demoted(monkeypatch):
    """The sun is read at the decision, AFTER the 20 s settle."""
    hass, nm, mgr = _d105(monkeypatch, corroborate=False)
    _sun(hass, 0.5)
    _run(_drive(mgr, DB_PR, during=lambda: _sun(hass, -0.5, "below_horizon"),
                fire_delays=(20,)))
    assert _sev(nm) == Severity.CRITICAL
    assert _eg(mgr)["reason"] == "egress_uncorroborated_night"


def test_egress_uncorroborated_night_arms_followup(monkeypatch):
    hass, nm, mgr = _d105(monkeypatch, corroborate=False)
    _sun(hass, -30.0, "below_horizon")
    _run(_drive(mgr, DB_PR, fire_delays=(20,)))
    assert _sev(nm) == Severity.CRITICAL
    assert DB_KEY in mgr._pending_followups
    # pair: daytime -> demoted to LOW -> no follow-up
    hass, nm, mgr = _d105(monkeypatch, corroborate=False)
    _sun(hass, 30.0)
    _run(_drive(mgr, DB_PR, fire_delays=(20,)))
    assert DB_KEY not in mgr._pending_followups


def test_egress_corroborated_night_unchanged(monkeypatch):
    """Corroborated at night -> full severity as today (not D1b's branch)."""
    hass, nm, mgr = _d105(monkeypatch, corroborate=True)
    _sun(hass, -30.0, "below_horizon")
    _run(mgr._async_handle_perimeter_trigger(DB_PR))
    assert _sev(nm) == Severity.CRITICAL
    assert _eg(mgr)["reason"] == "egress_unknown_corroborated"
    assert DB_F2  # leg fixture present
