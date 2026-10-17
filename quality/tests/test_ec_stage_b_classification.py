"""EC storm/blind Stage B D-B1..D-B5 (PLANNING_ec_storm_and_blind_decisions.md).

D-B1 hazard window (Onset→Ends, Status/Type filter, max-end aggregate),
D-B2 product table (code or exact name, no severity demotion, drift rows),
D-B3 feed health + hold memory, D-B4 bottom rate, D-B5 legacy list retired.

INV-3: Actual + not Cancel + HOLD class + start <= now <= end => tier >= table
tier; now < start contributes nothing; WIY never above notice.

Pure classifier tests drive `AlertClassifier.classify` on fixtures; feed /
memory tests drive the REAL `BatteryStrategy.determine_mode` (frozen clock,
`_reserve_governor_harness`) with a real NWS alerts entity in the mock hass.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from _reserve_governor_harness import (  # noqa: F401 — `clock` is a fixture
    _CDT,
    clock,
    make_shell,
)
from conftest import MockState

import custom_components.universal_room_automation.domain_coordinators.inclement as inc
from custom_components.universal_room_automation.domain_coordinators.energy_const import (
    CONF_INCLEMENT_NWS_ALERTS_ENTITY,
    CONF_INCLEMENT_POWER_THREAT_EVENTS,
    DEFAULT_INCLEMENT_POWER_THREAT_EVENTS,
)
from custom_components.universal_room_automation.domain_coordinators.energy_outage_ledger import (
    OutageLedger,
)
from custom_components.universal_room_automation.domain_coordinators.energy_tou import (
    TOURateEngine,
)
from custom_components.universal_room_automation.domain_coordinators.inclement import (
    AlertClassification,
    AlertClassifier,
    InclementFusion,
)

_UTC = timezone.utc
_NWS = "sensor.stage_b_nws_alerts"
_TS = "sensor.stage_b_nws_last_updated"


def T(day, hour, minute=0, month=10):
    """Local CDT time (October 2026 = CDT)."""
    return datetime(2026, month, day, hour, minute, tzinfo=_CDT)


def iso(dt):
    return dt.isoformat()


def alert(event, *, onset=None, ends=None, expires=None, sent=None,
          code=None, type_="Alert", id_=None, status="Actual",
          severity="Severe", certainty="Likely"):
    a = {
        "Event": event, "Type": type_, "Status": status,
        "Severity": severity, "Certainty": certainty,
        "ID": id_ or f"{event}|{type_}|{onset}|{sent}",
    }
    if code is not None:
        a["NWSCode"] = code
    for k, v in (("Onset", onset), ("Ends", ends), ("Expires", expires),
                 ("Sent", sent)):
        if v is not None:
            a[k] = iso(v)
    return a


def classify(alerts, now):
    return AlertClassifier().classify(alerts, now=now)


# ---------------------------------------------------------------------------
# 10-15 replay (fixture built from the recorder facts in
# AUDIT_ec_storm_stage0_probes.md P2(a): Alert Sent 10-15 11:10, Onset =
# Expires = 10-16 04:00, Ends 19:00; superseded at 23:50 by an Update with
# Expires 19:00).
# ---------------------------------------------------------------------------
WIY_ALERT = alert("Wind Advisory", code="WIY", sent=T(15, 11, 10),
                  onset=T(16, 4), expires=T(16, 4), ends=T(16, 19),
                  id_="wiy-alert")
WIY_UPDATE = alert("Wind Advisory", code="WIY", type_="Update",
                   sent=T(15, 23, 50), onset=T(16, 4), expires=T(16, 19),
                   ends=T(16, 19), id_="wiy-update")


def test_wiy_is_notice_never_hold():
    fusion = InclementFusion(reserve_soc=20, partial_hold_reserve_floor=50,
                             watch_requires_corroboration=False)
    for now in (T(16, 2, 30), T(16, 4), T(16, 18, 59), T(16, 19, 1)):
        c = classify([WIY_UPDATE], now)
        assert c.tier in ("none", "notice")
        d = fusion.decide(None, c, True, 3, "mid_peak", now, 50)
        assert d.hold_depth == "allow_discharge", now
    # Window: 02:30 not active, 04:00 / 18:59 notice, 19:01 gone.
    assert classify([WIY_UPDATE], T(16, 2, 30)).tier == "none"
    assert classify([WIY_UPDATE], T(16, 4)).tier == "notice"
    assert classify([WIY_UPDATE], T(16, 18, 59)).tier == "notice"
    assert classify([WIY_UPDATE], T(16, 19, 1)).tier == "none"
    # WIY is a table row, not gated out (Live (b)).
    assert classify([WIY_UPDATE], T(16, 5)).gated_out_events == ()


def test_update_message_kept_cancel_dropped():
    # An Update is classified (a `Type != Alert` filter would drop it).
    assert classify([WIY_UPDATE], T(16, 12)).tier == "notice"
    wsw_upd = alert("Winter Storm Warning", type_="Update", onset=T(16, 1),
                    ends=T(17, 1))
    assert classify([wsw_upd], T(16, 12)).tier == "warn"
    cancel = alert("Winter Storm Warning", type_="Cancel", onset=T(16, 1),
                   ends=T(17, 1))
    assert classify([cancel], T(16, 12)).tier == "none"
    exercise = alert("Winter Storm Warning", status="Exercise",
                     onset=T(16, 1), ends=T(17, 1))
    assert classify([exercise], T(16, 12)).tier == "none"


def test_freeze_products_hold():
    now = T(16, 3)  # bottom rate
    hfw = alert("Hard Freeze Warning", onset=T(16, 0), ends=T(16, 10))
    hfa = alert("Hard Freeze Watch", onset=T(16, 0), ends=T(16, 10))
    fzw = alert("Freeze Warning", code="FZW", onset=T(16, 0), ends=T(16, 10))
    flood = alert("Flood Watch", onset=T(16, 0), ends=T(16, 10))
    wsw_name_only = alert("winter storm warning", onset=T(16, 0), ends=T(16, 10))
    f = InclementFusion(reserve_soc=20, partial_hold_reserve_floor=50)
    c = classify([hfw], now)
    assert c.tier == "warn"
    assert f.decide(None, c, False, 0, "off_peak", now, 50).hold_depth == "full_hold"
    c = classify([hfa], now)
    assert c.tier == "watch"
    assert f.decide(None, c, False, 0, "off_peak", now, 50).hold_depth == "partial_hold"
    assert classify([fzw], now).tier == "notice"
    c = classify([flood], now)
    assert c.tier == "none" and "Flood Watch" in c.gated_out_events
    assert classify([wsw_name_only], now).tier == "warn"


def test_pre_onset_not_active():
    a = alert("Winter Storm Warning", sent=T(16, 6), onset=T(16, 21),
              ends=T(17, 9))
    assert classify([a], T(16, 20, 59)).tier == "none"
    assert classify([a], T(16, 20, 59)).expires_at is None
    assert classify([a], T(16, 21)).tier == "warn"


def test_wsw_issued_ahead_holds_from_onset():
    a = alert("Winter Storm Warning", sent=T(16, 6), onset=T(16, 21),
              ends=T(17, 9))
    f = InclementFusion(reserve_soc=20, partial_hold_reserve_floor=50)
    d18 = f.decide(None, classify([a], T(16, 18)), False, 0, "mid_peak", T(16, 18), 70)
    assert d18.hold_depth == "allow_discharge"
    assert d18.reason != "classify_error"
    d21 = f.decide(None, classify([a], T(16, 21)), False, 0, "mid_peak", T(16, 21), 70)
    assert d21.hold_depth == "full_hold"


def test_hold_lives_to_ends():
    # Expires 04:00 but Ends 19:00: hold lives to Ends (not min(Ends,Expires)).
    a = alert("Winter Storm Warning", onset=T(16, 1), expires=T(16, 4),
              ends=T(16, 19))
    assert classify([a], T(16, 12)).tier == "warn"
    assert classify([a], T(16, 18, 59)).tier == "warn"
    assert classify([a], T(16, 19, 1)).tier == "none"


def test_fallback_expires_when_no_ends():
    a = alert("Winter Storm Warning", onset=T(16, 1), expires=T(16, 4))
    assert classify([a], T(16, 3, 59)).tier == "warn"
    assert classify([a], T(16, 4, 1)).tier == "none"


def test_unbounded_alert_capped():
    a = alert("Winter Storm Warning", onset=T(16, 0))  # no Ends / Expires
    assert classify([a], T(16, 0) + timedelta(hours=47)).tier == "warn"
    assert classify([a], T(16, 0) + timedelta(hours=48, minutes=1)).tier == "none"
    # No Onset either: Sent anchors the cap.
    b = alert("Winter Storm Warning", sent=T(16, 0))
    assert classify([b], T(16, 0) + timedelta(hours=49)).tier == "none"


def test_aggregate_end_max_over_hold_contributors():
    watch = alert("Winter Storm Watch", onset=T(16, 1), ends=T(16, 20))
    warn = alert("Winter Storm Warning", onset=T(16, 1), ends=T(17, 6))
    notice = alert("Wind Advisory", code="WIY", onset=T(16, 1), ends=T(18, 0))
    c = classify([watch, warn, notice], T(16, 12))
    assert c.tier == "warn"
    assert c.expires_at == T(17, 6)
    # Watch alone: its own end.
    assert classify([watch, notice], T(16, 12)).expires_at == T(16, 20)
    # Only a NOTICE: no HOLD contributor → None.
    assert classify([notice], T(16, 12)).expires_at is None


@pytest.mark.parametrize("exact,switch,expected", [
    (True, "notice", "warn"),
    (True, "table", "warn"),
    (False, "table", "warn"),
    (False, "notice", "notice"),
])
def test_polygon_tier_switch(monkeypatch, exact, switch, expected):
    monkeypatch.setattr(inc, "INCLEMENT_POINT_FEED_POLYGON_EXACT", exact)
    monkeypatch.setattr(inc, "INCLEMENT_UNVERIFIED_POLYGON_TIER", switch)
    svw = alert("Severe Thunderstorm Warning", code="SVW",
                onset=T(16, 15), ends=T(16, 16))
    assert classify([svw], T(16, 15, 20)).tier == expected
    # A zone product is never touched by the polygon switch.
    wsw = alert("Winter Storm Warning", onset=T(16, 15), ends=T(16, 16))
    assert classify([wsw], T(16, 15, 20)).tier == "warn"


def test_code_match_and_name_match():
    # Coded row matched by code even when the event text differs in case.
    a = alert("SEVERE THUNDERSTORM WARNING", code="SVW", onset=T(16, 1),
              ends=T(16, 2))
    c = classify([a], T(16, 1, 30))
    assert c.tier == "warn" and c.drift == ()
    # Code wins a disagreement and is reported as drift.
    b = alert("Severe Thunderstorm Warning", code="TOW", onset=T(16, 1),
              ends=T(16, 2))
    c = classify([b], T(16, 1, 30))
    assert c.tier == "warn"
    assert c.drift == (("Severe Thunderstorm Warning", "TOW", "mismatch"),)
    # Name-only row with an observed code → "observed_code" drift record.
    w = alert("Winter Storm Warning", code="WSW", onset=T(16, 1), ends=T(16, 2))
    assert classify([w], T(16, 1, 30)).drift == (
        ("Winter Storm Warning", "WSW", "observed_code"),
    )


def test_severity_and_certainty_are_attrs_only():
    a = alert("Tornado Warning", code="TOW", onset=T(16, 1), ends=T(16, 2),
              severity="Minor", certainty="Possible")
    c = classify([a], T(16, 1, 30))
    assert c.tier == "warn"
    assert c.max_severity == "Minor" and c.max_certainty == "Possible"


def test_classify_odd_datetime_formats_never_raise():
    for onset in ("2026-10-16T01:00:00", "2026-10-16T06:00:00Z", None, "garbage"):
        a = {"Event": "Winter Storm Warning", "Status": "Actual", "Type": "Alert",
             "ID": f"x{onset}", "Onset": onset, "Ends": "2026-10-17T06:00:00Z"}
        c = classify([a], T(16, 12))
        assert c.tier == "warn", onset


# ---------------------------------------------------------------------------
# D-B4 bottom rate: byte-identical to the literal on PEC across a year.
# ---------------------------------------------------------------------------
class _Bat:
    def _expected_solar_surplus_pct(self, now, mins):
        return 30.0

    def classify_tomorrow_solar(self):
        return "poor"

    def _daylight_bounds(self, anchor):
        return (anchor.replace(hour=7, minute=0), anchor.replace(hour=19, minute=0))


def _cls(tier):
    return AlertClassification(
        tier=tier, contributing_events=("x",), max_severity="Severe",
        max_certainty="Likely", expires_at=None, raw_alert_count=1,
    )


def test_fusion_bottom_rate_hour_sweep_identical():
    tou = TOURateEngine()
    chi = ZoneInfo("America/Chicago")
    t = datetime(2026, 1, 1, 0, 0, tzinfo=chi)
    end = datetime(2027, 1, 1, 0, 0, tzinfo=chi)
    bat = _Bat()
    fusion = InclementFusion(reserve_soc=20, partial_hold_reserve_floor=50,
                             grid_precharge_on_hold=True)
    cases = [("watch", False, 0), ("watch", True, 1), ("warn", False, 0),
             ("none", True, 3)]
    n = 0
    while t < end:
        period = tou.get_current_period(t)
        for tier, stormy, count in cases:
            literal = fusion.decide(bat, _cls(tier), stormy, count, period, t, 40)
            ranked = fusion.decide(bat, _cls(tier), stormy, count, period, t, 40,
                                   bottom_rate=tou.is_bottom_rate(t))
            assert literal == ranked, (t, tier)
        n += 1
        t = (t.astimezone(_UTC) + timedelta(hours=1)).astimezone(chi)
    assert n >= 8759


def test_fusion_bottom_rate_input_is_read():
    # Discriminator for the D-B4 wiring: bottom_rate overrides the name.
    f = InclementFusion(reserve_soc=20, partial_hold_reserve_floor=50)
    now = T(16, 18)
    d_lit = f.decide(_Bat(), _cls("watch"), False, 0, "mid_peak", now, 40)
    d_bot = f.decide(_Bat(), _cls("watch"), False, 0, "mid_peak", now, 40,
                     bottom_rate=True)
    assert d_lit.hold_depth == "allow_discharge"
    assert d_bot.hold_depth == "partial_hold"


# ---------------------------------------------------------------------------
# Battery-level: D-B3 feed health + hold memory through determine_mode.
# ---------------------------------------------------------------------------
def _feed(c, alerts, *, state=None, alerts_lu=None, ts_lu=None):
    st = MockState(_NWS, state if state is not None else str(len(alerts or [])),
                   {"Alerts": alerts} if alerts is not None else {})
    if alerts_lu is not None:
        st.last_changed = st.last_updated = alerts_lu
    c.hass._states[_NWS] = st
    if ts_lu is not None:
        ts = MockState(_TS, iso(ts_lu), {})
        ts.last_changed = ts.last_updated = ts_lu
        c.hass._states[_TS] = ts


def _shell(clock):
    c, s = make_shell(clock)
    s._inclement_config_override = {CONF_INCLEMENT_NWS_ALERTS_ENTITY: _NWS}
    s._nws_last_updated_entity = lambda eid: _TS
    s._tou = TOURateEngine()
    return c, s


def _tick(clock, s, local, period="mid_peak"):
    clock.t = local.astimezone(_UTC)
    s._last_inclement_decision_at = None  # defeat the per-tick cache
    from _reserve_governor_harness import _SOC, _st
    _st(s.hass, _SOC, "70", unit="%", lu=clock.t)
    s.determine_mode(period, "shoulder", now=local)
    return s._last_inclement_decision


WSW_AHEAD = alert("Winter Storm Warning", sent=T(16, 6), onset=T(16, 21),
                  ends=T(17, 9), id_="wsw-1")


def test_memory_admits_alert_before_onset(clock):
    c, s = _shell(clock)
    _feed(c, [WSW_AHEAD], ts_lu=T(16, 14).astimezone(_UTC))
    d = _tick(clock, s, T(16, 14))
    assert d.hold_depth == "allow_discharge" and d.reason != "classify_error"
    assert "wsw-1" in s._inclement_alert_memory


def test_wsw_issued_ahead_feed_lost_before_onset_holds_at_onset(clock):
    c, s = _shell(clock)
    _feed(c, [WSW_AHEAD], ts_lu=T(16, 14).astimezone(_UTC))
    _tick(clock, s, T(16, 14))
    # Alerts sensor unavailable 15:00-23:00 (no Alerts attribute at all).
    _feed(c, None, state="unavailable", ts_lu=T(16, 14).astimezone(_UTC))
    for h in (15, 18, 20):
        assert _tick(clock, s, T(16, h)).hold_depth == "allow_discharge"
    d = _tick(clock, s, T(16, 21))
    assert d.tier == "warn" and d.hold_depth == "full_hold"
    assert s._inclement_alerts_stale is True


def test_unavailable_sensor_is_stale(clock):
    c, s = _shell(clock)
    wsw = alert("Winter Storm Warning", onset=T(16, 1), ends=T(16, 23), id_="w")
    _feed(c, [wsw], ts_lu=T(16, 12).astimezone(_UTC))
    assert _tick(clock, s, T(16, 12)).hold_depth == "full_hold"
    assert s._inclement_alerts_stale is False
    _feed(c, None, state="unavailable")
    d = _tick(clock, s, T(16, 13))
    assert s._inclement_alerts_stale is True
    assert d.hold_depth == "full_hold"  # memory to Ends
    d = _tick(clock, s, T(16, 23, 1))
    assert d.hold_depth == "allow_discharge"  # past Ends


def test_steady_alert_not_stale(clock):
    c, s = _shell(clock)
    wsw = alert("Winter Storm Warning", onset=T(16, 1), ends=T(16, 23), id_="w")
    # The alerts sensor itself has not changed for 2 h (steady alert); the
    # timestamp sibling advances every poll → healthy.
    _feed(c, [wsw], alerts_lu=T(16, 10).astimezone(_UTC),
          ts_lu=T(16, 11, 59).astimezone(_UTC))
    _tick(clock, s, T(16, 12))
    assert s._inclement_alerts_stale is False
    # Control: the sibling 16 min old → stale.
    _feed(c, [wsw], alerts_lu=T(16, 10).astimezone(_UTC),
          ts_lu=T(16, 11, 44).astimezone(_UTC))
    _tick(clock, s, T(16, 12))
    assert s._inclement_alerts_stale is True


def test_stale_boundary_literal_seconds(clock):
    c, s = _shell(clock)
    for age, stale in ((899, False), (900, False), (901, True)):
        _feed(c, [], ts_lu=(T(16, 12) - timedelta(seconds=age)).astimezone(_UTC))
        _tick(clock, s, T(16, 12))
        assert s._inclement_alerts_stale is stale, age


def test_empty_feed_on_attribute_error_keeps_hold(clock):
    c, s = _shell(clock)
    wsw = alert("Winter Storm Warning", onset=T(16, 1), ends=T(16, 23), id_="w")
    _feed(c, [wsw], ts_lu=T(16, 12).astimezone(_UTC))
    _tick(clock, s, T(16, 12))
    # Healthy-looking EMPTY feed (fresh timestamp): clears nothing.
    _feed(c, [], ts_lu=T(16, 13).astimezone(_UTC))
    d = _tick(clock, s, T(16, 13))
    assert s._inclement_alerts_stale is False
    assert d.hold_depth == "full_hold" and "w" in s._inclement_alert_memory


def test_stale_feed_never_admits_new(clock):
    c, s = _shell(clock)
    wsw = alert("Winter Storm Warning", onset=T(16, 1), ends=T(16, 23), id_="w")
    _feed(c, [wsw], ts_lu=T(16, 10).astimezone(_UTC))  # 2 h old → stale
    d = _tick(clock, s, T(16, 12))
    assert s._inclement_alerts_stale is True
    assert s._inclement_alert_memory == {}
    assert d.hold_depth == "full_hold"  # the tick's own feed still classifies
    _feed(c, None, state="unavailable")
    assert _tick(clock, s, T(16, 13)).hold_depth == "allow_discharge"
    # Control: the same alert from a HEALTHY feed is remembered.
    _feed(c, [wsw], ts_lu=T(16, 14).astimezone(_UTC))
    _tick(clock, s, T(16, 14))
    _feed(c, None, state="unavailable")
    assert _tick(clock, s, T(16, 15)).hold_depth == "full_hold"


def test_memory_cleared_by_cancel_writes_row(clock):
    c, s = _shell(clock)
    c._outage_ledger = OutageLedger(c.hass)
    wsw = alert("Winter Storm Warning", onset=T(16, 1), ends=T(16, 23), id_="w")
    _feed(c, [wsw], ts_lu=T(16, 12).astimezone(_UTC))
    _tick(clock, s, T(16, 12))
    cancel = alert("Winter Storm Warning", type_="Cancel", onset=T(16, 1),
                   ends=T(16, 23), id_="w-cancel")
    _feed(c, [cancel], ts_lu=T(16, 13).astimezone(_UTC))
    d = _tick(clock, s, T(16, 13))
    assert s._inclement_alert_memory == {}
    assert d.hold_depth == "allow_discharge"
    c._inclement_rows_tick()
    asyncio.get_event_loop().run_until_complete(asyncio.sleep(0))
    rows = [r for r in c.db.rows if r["action"] == "inclement_memory_cleared"]
    assert len(rows) == 1
    assert '"reason": "cancel"' in rows[0]["details_json"]
    assert '"id": "w"' in rows[0]["details_json"]
    # Drained: a second drain writes nothing.
    c._inclement_rows_tick()
    asyncio.get_event_loop().run_until_complete(asyncio.sleep(0))
    assert len([r for r in c.db.rows
                if r["action"] == "inclement_memory_cleared"]) == 1


def test_memory_cleared_when_absent_from_healthy_nonempty_feed(clock):
    c, s = _shell(clock)
    wsw = alert("Winter Storm Warning", onset=T(16, 1), ends=T(16, 23), id_="w")
    other = alert("Wind Advisory", code="WIY", onset=T(16, 1), ends=T(16, 23),
                  id_="wiy")
    _feed(c, [wsw], ts_lu=T(16, 12).astimezone(_UTC))
    _tick(clock, s, T(16, 12))
    _feed(c, [other], ts_lu=T(16, 13).astimezone(_UTC))
    assert _tick(clock, s, T(16, 13)).hold_depth == "allow_discharge"
    assert s._inclement_pending_rows[-1][2]["reason"] == "left_feed"


def test_code_name_drift_row(clock):
    c, s = _shell(clock)
    c._outage_ledger = OutageLedger(c.hass)
    bad = alert("Severe Thunderstorm Warning", code="TOW", onset=T(16, 12),
                ends=T(16, 13), id_="svw")
    _feed(c, [bad], ts_lu=T(16, 12).astimezone(_UTC))
    _tick(clock, s, T(16, 12, 5))
    _tick(clock, s, T(16, 12, 10))  # same drift: deduped per boot
    c._inclement_rows_tick()
    asyncio.get_event_loop().run_until_complete(asyncio.sleep(0))
    rows = [r for r in c.db.rows if r["action"] == "inclement_code_drift"]
    assert len(rows) == 1
    assert '"kind": "mismatch"' in rows[0]["details_json"]


def test_nws_last_updated_sibling_resolved_from_registry(clock, monkeypatch):
    """The resolver itself (not patched): same config entry, unique_id
    carries `last_updated` (nws_alerts/sensor.py unique_id format)."""
    from types import SimpleNamespace
    from homeassistant.helpers import entity_registry as er
    c, s = make_shell(clock)
    ents = {
        _NWS: SimpleNamespace(entity_id=_NWS, config_entry_id="ce1",
                              unique_id="nws_alerts_gps_alerts_ce1"),
        _TS: SimpleNamespace(entity_id=_TS, config_entry_id="ce1",
                             unique_id="nws_alerts_gps_last_updated_ce1"),
    }
    reg = SimpleNamespace(async_get=lambda eid: ents.get(eid))
    monkeypatch.setattr(er, "async_get", lambda hass: reg)
    monkeypatch.setattr(er, "async_entries_for_config_entry",
                        lambda r, ce: [e for e in ents.values()
                                       if e.config_entry_id == ce])
    assert s._nws_last_updated_entity(_NWS) == _TS
    # Unresolvable → None (unavailable/unknown leg only).
    assert s._nws_last_updated_entity("sensor.other") is None


# ---------------------------------------------------------------------------
# D-B5 legacy list retired
# ---------------------------------------------------------------------------
def _cm_entry(options):
    from types import SimpleNamespace
    from custom_components.universal_room_automation.const import (
        CONF_ENTRY_TYPE,
        ENTRY_TYPE_COORDINATOR_MANAGER,
    )
    return SimpleNamespace(
        data={CONF_ENTRY_TYPE: ENTRY_TYPE_COORDINATOR_MANAGER},
        options=options, entry_id="cm",
    )


def _issue_spy(monkeypatch):
    from homeassistant.helpers import issue_registry as ir
    calls = []
    monkeypatch.setattr(ir, "async_create_issue",
                        lambda *a, **kw: calls.append((a, kw)))
    return calls


def test_legacy_list_no_options_write(clock, monkeypatch):
    c, s = make_shell(clock)
    entry = _cm_entry({CONF_INCLEMENT_POWER_THREAT_EVENTS:
                       list(DEFAULT_INCLEMENT_POWER_THREAT_EVENTS)})
    c.hass.config_entries.async_entries = lambda domain=None: [entry]
    calls = _issue_spy(monkeypatch)
    assert c._check_legacy_threat_list() is False
    assert calls == []
    assert not c.hass.config_entries.async_update_entry.called


def test_customized_legacy_list_raises_repair_issue(clock, monkeypatch):
    c, s = make_shell(clock)
    entry = _cm_entry({CONF_INCLEMENT_POWER_THREAT_EVENTS:
                       list(DEFAULT_INCLEMENT_POWER_THREAT_EVENTS) + ["Flood"]})
    c.hass.config_entries.async_entries = lambda domain=None: [entry]
    calls = _issue_spy(monkeypatch)
    assert c._check_legacy_threat_list() is True
    assert len(calls) == 1
    assert calls[0][0][2] == "inclement_legacy_threat_list_retired"
    assert not c.hass.config_entries.async_update_entry.called


def test_battery_passes_engine_bottom_rate_into_fusion(clock):
    """D-B4 call-site anchor: on PEC the engine and the literal agree, so a
    discriminating engine (bottom at a period NAMED mid_peak) is used: an
    uncorroborated watch holds partial only if the engine's answer is read."""
    class _Eng(TOURateEngine):
        def is_bottom_rate(self, now=None):
            return True
    c, s = _shell(clock)
    s._tou = _Eng()
    wsa = alert("Winter Storm Watch", onset=T(16, 1), ends=T(16, 23), id_="a")
    _feed(c, [wsa], ts_lu=T(16, 18).astimezone(_UTC))
    d = _tick(clock, s, T(16, 18), period="mid_peak")
    assert d.hold_depth == "partial_hold"
    s._tou = TOURateEngine()
    d = _tick(clock, s, T(16, 18, 5), period="mid_peak")
    assert d.hold_depth == "allow_discharge"
