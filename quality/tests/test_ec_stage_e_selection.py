"""EC storm Stage E E1 — operator alert selection over the internal product
table (PLANNING_ec_storm_stage_e.md §E1, INV-7(a)-(f), OQ-2 approved).

Decision tests drive the REAL `BatteryStrategy.determine_mode` (frozen clock,
real NWS alerts entity, the D-C1 forecast seam faked); fusion-level tests
drive the real `AlertClassifier` + `InclementFusion.decide`. Flow tests drive
the REAL options-flow step `async_step_coordinator_energy`.
"""
from __future__ import annotations

import ast
import asyncio
import copy
import importlib
import importlib.util
import json
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from _ec_stage_e_harness import (  # noqa: F401 — fixtures
    L,
    alert,
    bshell,
    cfg_on,
    chi_clock,
    clock,
    feed,
    inc_mod,
    outlook,
    tick,
)
from custom_components.universal_room_automation.domain_coordinators.energy_const import (
    CONF_INCLEMENT_BUY_ADDED,
    CONF_INCLEMENT_BUY_PRODUCTS,
    CONF_INCLEMENT_BUY_REMOVED,
    CONF_INCLEMENT_HOLD_ADDED,
    CONF_INCLEMENT_HOLD_PRODUCTS,
    CONF_INCLEMENT_HOLD_REMOVED,
    INCLEMENT_PRODUCT_TABLE,
)

REPO = Path(__file__).resolve().parents[2]
PKG = REPO / "custom_components" / "universal_room_automation"
NOW = L(2026, 10, 16, 3)      # shoulder, bottom rate
TOP = L(2026, 10, 16, 18)     # shoulder, top rate (17-21)
KEYS4 = (CONF_INCLEMENT_HOLD_ADDED, CONF_INCLEMENT_HOLD_REMOVED,
         CONF_INCLEMENT_BUY_ADDED, CONF_INCLEMENT_BUY_REMOVED)


def opts(**kw):
    return {
        CONF_INCLEMENT_HOLD_ADDED: kw.get("hold_added", []),
        CONF_INCLEMENT_HOLD_REMOVED: kw.get("hold_removed", []),
        CONF_INCLEMENT_BUY_ADDED: kw.get("buy_added", []),
        CONF_INCLEMENT_BUY_REMOVED: kw.get("buy_removed", []),
    }


def sel(**kw):
    return inc_mod().build_selection(opts(**kw))


def active(event, now, *, id_, code=None, hours=6):
    return alert(event, onset=now - timedelta(minutes=30),
                 ends=now + timedelta(hours=hours), id_=id_, code=code)


def prepare(event, now, *, id_, ahead_h=3, hours=8):
    on = now + timedelta(hours=ahead_h)
    return alert(event, onset=on, ends=on + timedelta(hours=hours), id_=id_)


# ---------------------------------------------------------------------------
# Fusion-level driver (real classifier + real fusion; confirmed IDs computed
# exactly as `_forecast_confirmed_ids` does: zone HOLD records whose family
# confirms on the outlook).
# ---------------------------------------------------------------------------
def fdecide(alerts, selection, *, now=NOW, bottom=True, stormy=False,
            wrc=True, ol=None, soc=50, option=True):
    inc = inc_mod()
    cls = inc.AlertClassifier(selection=selection).classify(alerts, now=now)
    confirmed = {
        r.alert_id for r in tuple(cls.hold_alerts) + tuple(cls.prepare_alerts)
        if not r.polygon_local and r.alert_id
        and inc.forecast_family(r.event) is not None
        and inc.forecast_confirms(r.event, ol)
    }
    f = inc.InclementFusion(reserve_soc=20, partial_hold_reserve_floor=50,
                            grid_precharge_on_hold=option,
                            watch_requires_corroboration=wrc)
    bat = SimpleNamespace(_expected_solar_surplus_pct=lambda n, m: 0.0,
                          _tou=None)
    kw = dict(bottom_rate=bottom, forecast_confirmed_ids=frozenset(confirmed),
              preonset_latch={})
    import inspect
    if "preonset_buy_schedule" in inspect.signature(f.decide).parameters:
        kw["preonset_buy_schedule"] = {}
    d = f.decide(bat, cls, stormy, 2 if stormy else 0,
                 "off_peak" if bottom else "mid_peak", now, soc, **kw)
    return cls, d


def target(d):
    """The pre-onset VALUE (E2 splits it from the registered floor)."""
    return getattr(d, "preonset_target", d.preonset_floor)


def proj(d):
    return (d.hold_depth, d.reserve_floor, d.grid_precharge, d.reason,
            d.precharge_leg, target(d), d.preonset_floor)


# ===========================================================================
# INV-7(e): zero-override golden + table never mutated
# ===========================================================================
def _golden_module():
    spec = importlib.util.spec_from_file_location(
        "ec_stage_e_capture", REPO / "scripts" / "golden" / "ec_stage_e_capture.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_zero_override_golden_identical_to_v5_103_69():
    g = _golden_module()
    allowed, bad = g.compare()
    assert bad == [], bad[:5]
    # The enumerated E0 diff (and nothing else) is present.
    assert {r[0] for r in allowed} == {"Freeze Warning", "Freeze Watch"}


def test_product_table_not_mutated_by_selection():
    inc = inc_mod()
    table_before = copy.deepcopy(INCLEMENT_PRODUCT_TABLE)
    tsel_before = copy.deepcopy(inc.TABLE_SELECTION)
    heavy = opts(hold_added=["Flood Watch", "Wind Advisory"],
                 hold_removed=["Winter Storm Warning", "Tornado Warning"],
                 buy_added=["Tornado Watch"], buy_removed=["Ice Storm Warning"])
    s = inc.build_selection(heavy)
    alerts = [active(n, NOW, id_=n) for n in (
        "Flood Watch", "Wind Advisory", "Winter Storm Warning",
        "Tornado Warning", "Tornado Watch", "Ice Storm Warning")]
    inc.AlertClassifier(selection=s).classify(alerts, now=NOW)
    for a in alerts:
        inc.build_record(a, s)
    assert INCLEMENT_PRODUCT_TABLE == table_before
    assert inc.INCLEMENT_PRODUCT_TABLE == table_before
    assert inc.TABLE_SELECTION == tsel_before
    assert inc.build_selection({}) == tsel_before


# ===========================================================================
# §4.1 — the overlay at every match_product caller
# ===========================================================================
def test_selection_overlay_applies_in_classify():
    inc = inc_mod()
    wsw = active("Winter Storm Warning", NOW, id_="w")
    assert inc.AlertClassifier().classify([wsw], now=NOW).tier == "warn"
    c = inc.AlertClassifier(
        selection=sel(hold_removed=["Winter Storm Warning"]),
    ).classify([wsw], now=NOW)
    assert c.tier == "notice" and c.hold_alerts == ()
    assert c.active_alerts[0].cls == "notice"


def test_selection_overlay_applies_in_build_record():
    inc = inc_mod()
    wsw = active("Winter Storm Warning", NOW, id_="w")
    r = inc.build_record(wsw, sel(hold_removed=["Winter Storm Warning"]))
    assert (r.cls, r.tier, r.precharge_eligible, r.corroborable) == (
        "notice", "notice", False, True)
    r = inc.build_record(wsw, sel(buy_removed=["Winter Storm Warning"]))
    assert (r.cls, r.precharge_eligible) == ("warn", False)
    flood = active("Flood Watch", NOW, id_="f")
    assert inc.build_record(flood) is None
    r = inc.build_record(flood, sel(hold_added=["Flood Watch"]))
    assert (r.cls, r.tier, r.precharge_eligible, r.corroborable,
            r.polygon_local) == ("watch", "watch", False, False, False)


def test_selection_overlay_applies_in_memory_admission():
    inc = inc_mod()
    w = prepare("Winter Storm Warning", NOW, id_="w")
    mem: dict = {}
    inc.update_alert_memory(mem, [w], True, NOW,
                            selection=sel(hold_removed=["Winter Storm Warning"]))
    assert mem == {}
    inc.update_alert_memory(mem, [w], True, NOW)
    assert set(mem) == {"w"}
    mem2: dict = {}
    f = prepare("Flood Watch", NOW, id_="f")
    inc.update_alert_memory(mem2, [f], True, NOW,
                            selection=sel(hold_added=["Flood Watch"]))
    assert set(mem2) == {"f"}


def test_selection_overlay_applies_in_outage_ledger(chi_clock):
    """Drives the ENCLOSING method `EnergyCoordinator._outage_ledger_tick`
    (the call site that builds the selection from the live CM options)."""
    from custom_components.universal_room_automation.domain_coordinators.energy_outage_ledger import (
        OutageLedger,
    )
    w = active("Winter Storm Warning", NOW, id_="w")
    f = active("Flood Watch", NOW, id_="f")

    def run(cm_opts):
        c, s, _ = bshell(chi_clock, NOW, alerts=[w, f])
        feed(c)
        c._outage_ledger = OutageLedger(c.hass)
        c._outage_ledger._alerts_seeded = True
        c._outage_local_readings = lambda: {}
        c._get_cm_options = lambda: cm_opts
        c._outage_ledger_tick()
        loop = asyncio.get_event_loop()
        for _ in range(4):
            loop.run_until_complete(asyncio.sleep(0))
        rows = [json.loads(r["details_json"]) for r in c.db.rows
                if r["action"] == "nws_alert"]
        return {d["id"]: (d["ura_class"], d["ura_tier"]) for d in rows}

    assert run({}) == {"w": ("warn", "warn"), "f": (None, None)}
    got = run(opts(hold_removed=["Winter Storm Warning"],
                   hold_added=["Flood Watch"]))
    assert got == {"w": ("notice", "notice"), "f": ("watch", "watch")}


# ===========================================================================
# Narrow / widen through the REAL battery decision
# ===========================================================================
def test_selection_remove_hold_is_notice_and_not_admitted(chi_clock):
    w = active("Winter Storm Warning", NOW, id_="w")
    c, s, _ = bshell(chi_clock, NOW, alerts=[w], soc="50",
                     extra_opts=opts(hold_removed=["Winter Storm Warning"]))
    tick(chi_clock, c, s, NOW)
    dec = s._last_inclement_decision
    assert dec.reason != "classify_error"
    assert (dec.tier, dec.hold_depth) == ("notice", "allow_discharge")
    assert s._inclement_alert_memory == {}
    # Prepare: no pre-onset target / floor at all.
    p = prepare("Winter Storm Warning", NOW, id_="p", ahead_h=3)
    c2, s2, _ = bshell(chi_clock, NOW, alerts=[p], soc="50",
                       extra_opts=opts(hold_removed=["Winter Storm Warning"]))
    tick(chi_clock, c2, s2, NOW)
    d2 = s2._last_inclement_decision
    assert target(d2) is None and d2.preonset_floor is None
    assert s2._tick_reserve_floor is None
    # Control: the table default holds and admits.
    c3, s3, _ = bshell(chi_clock, NOW, alerts=[w], soc="50")
    tick(chi_clock, c3, s3, NOW)
    assert s3._last_inclement_decision.hold_depth == "full_hold"
    assert set(s3._inclement_alert_memory) == {"w"}


def test_selection_remove_buy_keeps_hold(chi_clock):
    w = active("Winter Storm Warning", NOW, id_="w")
    ok = outlook(min_temp=20.0, pop=80.0)
    c, s, _ = bshell(chi_clock, NOW, alerts=[w], soc="50", ol=ok,
                     extra_opts=opts(buy_removed=["Winter Storm Warning"]))
    d = tick(chi_clock, c, s, NOW)
    assert s._last_inclement_decision.hold_depth == "full_hold"
    assert cfg_on(d) is False
    c2, s2, _ = bshell(chi_clock, NOW, alerts=[w], soc="50", ol=ok)
    assert cfg_on(tick(chi_clock, c2, s2, NOW)) is True  # control


@pytest.mark.parametrize("ol_kw,buys", [
    (dict(min_temp=60.0, pop=75.0, cond=("lightning",)), True),
    (dict(min_temp=60.0, pop=60.0, cond=("lightning",)), False),
    (dict(min_temp=60.0, pop=95.0, cond=("pouring",)), False),
], ids=["lightning_pop75", "lightning_pop60", "pouring_pop95"])
def test_selection_widen_buy_needs_forecast(chi_clock, ol_kw, buys):
    tw = active("Tornado Watch", NOW, id_="tw")
    c, s, _ = bshell(chi_clock, NOW, alerts=[tw], soc="50",
                     ol=outlook(**ol_kw),
                     extra_opts=opts(buy_added=["Tornado Watch"]))
    assert cfg_on(tick(chi_clock, c, s, NOW)) is buys
    if buys:  # control: not selected -> the same confirmed watch never buys
        c2, s2, _ = bshell(chi_clock, NOW, alerts=[tw], soc="50",
                           ol=outlook(**ol_kw))
        assert cfg_on(tick(chi_clock, c2, s2, NOW)) is False
        assert s2._last_inclement_decision.hold_depth == "full_hold"


@pytest.mark.parametrize("wrc", [True, False], ids=["req_true", "req_false"])
def test_widened_notice_not_corroborable(wrc):
    """Repro (ii): Wind Advisory added to hold + `pouring` (2 providers
    stormy) + top rate -> never a full hold on rain."""
    wa = active("Wind Advisory", TOP, id_="wa", code="WIY")
    s_ = sel(hold_added=["Wind Advisory"])
    cls, d = fdecide([wa], s_, now=TOP, bottom=False, stormy=True, wrc=wrc,
                     ol=outlook(min_temp=60.0, pop=95.0, cond=("pouring",)))
    assert cls.hold_alerts[0].corroborable is False
    assert d.hold_depth == "allow_discharge"
    _, d2 = fdecide([wa], s_, bottom=True, stormy=True, wrc=wrc)
    assert d2.hold_depth == "partial_hold"


def test_widened_confirmed_watch_never_self_corroborates():
    """INV-7(c) forecast leg: a widened row whose OWN forecast confirms
    (Cold Weather Advisory, apparent 20 F) still never corroborates."""
    cwa = active("Cold Weather Advisory", NOW, id_="cwa")
    s_ = sel(hold_added=["Cold Weather Advisory"])
    ol = outlook(min_temp=30.0, apparent=20.0, pop=0.0)
    assert inc_mod().forecast_confirms("Cold Weather Advisory", ol) is True
    _, d = fdecide([cwa], s_, ol=ol, wrc=True)
    assert d.hold_depth == "partial_hold"
    _, d = fdecide([cwa], s_, ol=ol, wrc=True, now=TOP, bottom=False)
    assert d.hold_depth == "allow_discharge"


@pytest.mark.parametrize("wrc", [True, False], ids=["req_true", "req_false"])
def test_unlisted_product_capped_partial_hold(wrc):
    """Repro (i): Flood Watch added to hold, bottom rate, stormy: at most
    partial (without the cap req_false gives the corroborated full hold)."""
    fw = active("Flood Watch", NOW, id_="fw")
    s_ = sel(hold_added=["Flood Watch"])
    for stormy in (False, True):
        cls, d = fdecide([fw], s_, stormy=stormy, wrc=wrc, soc=50)
        assert cls.tier == "watch"
        assert d.hold_depth == "partial_hold", (stormy, d.reason)
        assert d.grid_precharge is False


@pytest.mark.parametrize("wrc", [True, False], ids=["req_true", "req_false"])
def test_mixed_unlisted_does_not_demote_table_watch(wrc):
    wsa = active("Winter Storm Watch", NOW, id_="wsa")
    fw = active("Flood Watch", NOW, id_="fw")
    s_ = sel(hold_added=["Flood Watch"])
    for now, bottom in ((NOW, True), (TOP, False)):
        for stormy in (False, True):
            for ol in (None, outlook(min_temp=20.0, pop=80.0)):
                _, alone = fdecide([wsa], s_, now=now, bottom=bottom,
                                   stormy=stormy, wrc=wrc, ol=ol)
                _, mixed = fdecide([wsa, fw], s_, now=now, bottom=bottom,
                                   stormy=stormy, wrc=wrc, ol=ol)
                assert proj(mixed) == proj(alone), (now, stormy, ol)


@pytest.mark.parametrize("wrc", [True, False], ids=["req_true", "req_false"])
def test_widened_buy_does_not_change_coactive_table_decision(wrc):
    """Rev 3 N1: a widened (notice-default) row seeded into buy can never
    buy -- not alone, and not by joining a co-active table hold."""
    ol = outlook(min_temp=30.0, apparent=20.0, pop=0.0)  # CWA confirms only
    cwa = active("Cold Weather Advisory", NOW, id_="cwa")
    s_ = sel(hold_added=["Cold Weather Advisory"],
             buy_added=["Cold Weather Advisory"])
    assert "cold weather advisory" not in s_.buy
    # warn co-active (unconfirmed: no precip)
    wsw = active("Winter Storm Warning", NOW, id_="wsw")
    _, alone = fdecide([wsw], s_, wrc=wrc, ol=ol)
    _, mixed = fdecide([wsw, cwa], s_, wrc=wrc, ol=ol)
    assert proj(mixed) == proj(alone) and mixed.grid_precharge is False
    # ineligible table watch corroborated by condition -> full hold
    tw = active("Tornado Watch", NOW, id_="tw")
    _, alone = fdecide([tw], s_, wrc=wrc, ol=ol, stormy=True)
    _, mixed = fdecide([tw, cwa], s_, wrc=wrc, ol=ol, stormy=True)
    assert alone.hold_depth == "full_hold"
    assert proj(mixed) == proj(alone) and mixed.grid_precharge is False


def test_widened_prepare_never_buys(chi_clock):
    """A widened prepare record seeded into buy: no pre-onset buy, and only
    the lower floor (INV-7(c))."""
    cwa = prepare("Cold Weather Advisory", NOW, id_="cwa", ahead_h=2)
    c, s, _ = bshell(chi_clock, NOW, alerts=[cwa], soc="30",
                     ol=outlook(min_temp=30.0, apparent=10.0, pop=0.0),
                     extra_opts=opts(hold_added=["Cold Weather Advisory"],
                                     buy_added=["Cold Weather Advisory"]))
    d = tick(chi_clock, c, s, NOW)
    dec = s._last_inclement_decision
    assert target(dec) == 50  # lower = max(reserve 20, partial 50)
    assert cfg_on(d) is False and dec.preonset_precharge is False


def test_selection_cannot_override_polygon_locality(chi_clock, monkeypatch):
    """INV-7(a): with POINT_FEED_POLYGON_EXACT False an SVW override is
    inert (Q7 notice), and the overlay never clears polygon_local."""
    inc = inc_mod()
    monkeypatch.setattr(inc, "INCLEMENT_POINT_FEED_POLYGON_EXACT", False)
    svw = alert("Severe Thunderstorm Warning", code="SVW",
                onset=NOW - timedelta(minutes=10),
                ends=NOW + timedelta(minutes=50), id_="svw")
    s_ = sel(buy_added=["Severe Thunderstorm Warning"])
    r = inc.build_record(svw, s_)
    assert r.polygon_local is True and r.tier == "notice"
    c, s, _ = bshell(chi_clock, NOW, alerts=[svw], soc="50",
                     ol=outlook(cond=("lightning",)),
                     extra_opts=opts(buy_added=["Severe Thunderstorm Warning"]))
    d = tick(chi_clock, c, s, NOW)
    assert s._last_inclement_decision.hold_depth == "allow_discharge"
    assert cfg_on(d) is False


def test_runtime_buy_subset_of_hold_seeded_store(chi_clock):
    """Seeded straight into options (no form): buy_added without hold."""
    seeded = opts(buy_added=["Tornado Watch"], hold_removed=["Tornado Watch"])
    s_ = inc_mod().build_selection(seeded)
    assert "tornado watch" not in s_.buy and "tornado watch" not in s_.hold
    tw = active("Tornado Watch", NOW, id_="tw")
    c, s, _ = bshell(chi_clock, NOW, alerts=[tw], soc="50",
                     ol=outlook(min_temp=60.0, pop=80.0, cond=("lightning",)),
                     extra_opts=seeded)
    d = tick(chi_clock, c, s, NOW)
    dec = s._last_inclement_decision
    assert dec.reason != "classify_error" and dec.tier == "notice"
    assert cfg_on(d) is False


def test_unlisted_rows_skip_drift():
    inc = inc_mod()
    fw = active("Flood Watch", NOW, id_="fw", code="FFA")
    c = inc.AlertClassifier(selection=sel(hold_added=["Flood Watch"])).classify(
        [fw], now=NOW)
    assert c.tier == "watch" and c.drift == ()


def test_selection_reads_live_options_per_tick(chi_clock):
    w = active("Winter Storm Warning", NOW, id_="w")
    c, s, _ = bshell(chi_clock, NOW, alerts=[w], soc="50")
    tick(chi_clock, c, s, NOW)
    assert s._last_inclement_decision.hold_depth == "full_hold"
    s._inclement_config_override.update(
        opts(hold_removed=["Winter Storm Warning"]))
    t2 = NOW + timedelta(minutes=5)
    tick(chi_clock, c, s, t2)
    assert s._last_inclement_decision.hold_depth == "allow_discharge"
    s._inclement_config_override.update(opts())
    tick(chi_clock, c, s, t2 + timedelta(minutes=5))
    assert s._last_inclement_decision.hold_depth == "full_hold"


def test_selection_casefold_and_unknown_names(chi_clock):
    inc = inc_mod()
    s_ = inc.build_selection(opts(hold_removed=["winter STORM warning"],
                                  hold_added=["Bogus Alert", "flood watch"]))
    assert "winter storm warning" not in s_.hold
    assert "flood watch" in s_.hold and "bogus alert" not in s_.hold
    hold, _buy = inc.selection_form_defaults(
        opts(hold_added=["Bogus Alert", "flood watch"]))
    assert "Bogus Alert" not in hold and "Flood Watch" in hold
    w = active("Winter Storm Warning", NOW, id_="w")
    c, s, _ = bshell(chi_clock, NOW, alerts=[w], soc="50",
                     extra_opts=opts(hold_removed=["winter STORM warning"],
                                     hold_added=["Bogus Alert"]))
    tick(chi_clock, c, s, NOW)
    dec = s._last_inclement_decision
    assert dec.reason != "classify_error" and dec.tier == "notice"


def test_inclement_selection_attr_shape(chi_clock):
    w = active("Winter Storm Warning", NOW, id_="w")
    fw = active("Flood Watch", NOW, id_="fw")
    wa = active("Wind Advisory", NOW, id_="wa", code="WIY")
    tw = active("Tornado Watch", NOW, id_="tw")
    o = opts(hold_added=["Flood Watch", "Wind Advisory"],
             buy_removed=["Winter Storm Warning"])
    c, s, _ = bshell(chi_clock, NOW, alerts=[w, fw, wa, tw], soc="50",
                     ol=outlook(min_temp=20.0, pop=80.0), extra_opts=o)
    tick(chi_clock, c, s, NOW)
    attr = s._stage_b_attrs(s._last_inclement_decision)["inclement_selection"]
    by = {a["event"]: a for a in attr["alerts"]}
    assert by["Winter Storm Warning"] == {
        "event": "Winter Storm Warning", "level": "hold", "source": "override",
        "corroborable": True, "buy_gate": "not_selected"}
    assert by["Flood Watch"] == {
        "event": "Flood Watch", "level": "hold", "source": "unlisted",
        "corroborable": False, "buy_gate": "not_selected"}
    assert by["Wind Advisory"] == {
        "event": "Wind Advisory", "level": "hold", "source": "widened",
        "corroborable": False, "buy_gate": "not_selected"}
    assert by["Tornado Watch"] == {
        "event": "Tornado Watch", "level": "hold", "source": "table",
        "corroborable": True, "buy_gate": "not_selected"}
    assert attr["overrides"] == {
        CONF_INCLEMENT_HOLD_ADDED: ["Flood Watch", "Wind Advisory"],
        CONF_INCLEMENT_HOLD_REMOVED: [],
        CONF_INCLEMENT_BUY_ADDED: [],
        CONF_INCLEMENT_BUY_REMOVED: ["Winter Storm Warning"],
    }
    # option off -> every gate reads option_off; an eligible confirmed zone
    # row reads forecast_confirmed with the option on.
    c2, s2, _ = bshell(chi_clock, NOW, alerts=[w], soc="50",
                       ol=outlook(min_temp=20.0, pop=80.0))
    tick(chi_clock, c2, s2, NOW)
    a2 = s2._stage_b_attrs(s2._last_inclement_decision)["inclement_selection"]
    assert a2["alerts"] == [{"event": "Winter Storm Warning", "level": "hold+buy",
                             "source": "table", "corroborable": True,
                             "buy_gate": "forecast_confirmed"}]
    c3, s3, _ = bshell(chi_clock, NOW, alerts=[w], soc="50", option=False)
    tick(chi_clock, c3, s3, NOW)
    a3 = s3._stage_b_attrs(s3._last_inclement_decision)["inclement_selection"]
    assert a3["alerts"][0]["buy_gate"] == "option_off"


# ===========================================================================
# Options flow (REAL step) — storage, validation, pop, render
# ===========================================================================
_baec = importlib.import_module("test_baec_config_flow_round_trip")
_cbcf = importlib.import_module("test_cycle_b_config_flow")


def _flow(stored=None):
    flow = _cbcf._make_options_flow(options=dict(stored or {}))
    flow.hass.data = {}
    return flow


def _submit(flow, user_input):
    with _baec._ha_mocks_injected():
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(
                flow.async_step_coordinator_energy(user_input=user_input))
        finally:
            loop.close()


def _form_defaults(flow):
    r = _submit(flow, None)
    keys = {str(getattr(k, "schema", k)): k for k in r["data_schema"].schema}
    return keys


def test_selection_stores_deltas_only_real_flow():
    flow = _flow()
    keys = _form_defaults(flow)
    hold_default = keys[CONF_INCLEMENT_HOLD_PRODUCTS].default()
    buy_default = keys[CONF_INCLEMENT_BUY_PRODUCTS].default()
    r = _submit(_flow(), {CONF_INCLEMENT_HOLD_PRODUCTS: hold_default,
                          CONF_INCLEMENT_BUY_PRODUCTS: buy_default})
    assert r["type"] == "create_entry", r
    saved = r["data"]
    assert {k: saved[k] for k in KEYS4} == {k: [] for k in KEYS4}
    assert CONF_INCLEMENT_HOLD_PRODUCTS not in saved
    assert CONF_INCLEMENT_BUY_PRODUCTS not in saved
    # Retired table names are outside the domain (never a delta, never shown).
    for n in ("Hard Freeze Warning", "Wind Chill Watch"):
        assert n not in hold_default


def test_selection_form_keys_popped():
    r = _submit(_flow(), {
        CONF_INCLEMENT_HOLD_PRODUCTS: ["Winter Storm Warning", "Flood Watch"],
        CONF_INCLEMENT_BUY_PRODUCTS: ["Winter Storm Warning"],
    })
    assert r["type"] == "create_entry", r
    saved = r["data"]
    assert CONF_INCLEMENT_HOLD_PRODUCTS not in saved
    assert CONF_INCLEMENT_BUY_PRODUCTS not in saved
    assert saved[CONF_INCLEMENT_HOLD_ADDED] == ["Flood Watch"]
    assert "Winter Storm Watch" in saved[CONF_INCLEMENT_HOLD_REMOVED]
    assert "Winter Storm Warning" not in saved[CONF_INCLEMENT_HOLD_REMOVED]
    # Render from what was stored: effective lists, round-trip exact.
    keys = _form_defaults(_flow(saved))
    assert keys[CONF_INCLEMENT_HOLD_PRODUCTS].default() == [
        "Flood Watch", "Winter Storm Warning"]
    assert keys[CONF_INCLEMENT_BUY_PRODUCTS].default() == ["Winter Storm Warning"]


def test_selection_validation_buy_subset_of_hold():
    r = _submit(_flow(), {
        CONF_INCLEMENT_HOLD_PRODUCTS: ["Winter Storm Watch"],
        CONF_INCLEMENT_BUY_PRODUCTS: ["Winter Storm Warning"],
    })
    assert r["type"] == "form"
    assert r["errors"] == {CONF_INCLEMENT_BUY_PRODUCTS: "buy_not_in_hold"}


def test_selection_validation_buy_needs_family():
    r = _submit(_flow(), {
        CONF_INCLEMENT_HOLD_PRODUCTS: ["Flood Watch"],
        CONF_INCLEMENT_BUY_PRODUCTS: ["Flood Watch"],
    })
    assert r["type"] == "form"
    assert r["errors"] == {CONF_INCLEMENT_BUY_PRODUCTS: "buy_needs_forecast"}
    r = _submit(_flow(), {
        CONF_INCLEMENT_HOLD_PRODUCTS: ["Cold Weather Advisory"],
        CONF_INCLEMENT_BUY_PRODUCTS: ["Cold Weather Advisory"],
    })
    assert r["errors"] == {CONF_INCLEMENT_BUY_PRODUCTS: "buy_needs_table_hold"}
    # Error strings exist in both string files.
    for p in ("strings.json", "translations/en.json"):
        errs = json.loads((PKG / p).read_text())["options"]["error"]
        for k in ("buy_not_in_hold", "buy_needs_forecast", "buy_needs_table_hold"):
            assert errs[k]


# ===========================================================================
# E1.6 — key sets (behavioural: the real CM options listener)
# ===========================================================================
@pytest.fixture(scope="module")
def listener():
    import test_cm_reload_suppression as t
    return t, t._load_init_listener_helpers()


def _drive(listener, old, new):
    t, ns = listener
    hass = t._FakeHass(hvac=t._FakeHvac())
    entry = t._FakeEntry("cm1", dict(old))
    ns["_seed_cm_last_applied_options"](hass, entry)
    entry.options = dict(new)
    asyncio.new_event_loop().run_until_complete(
        ns["_async_update_listener"](hass, entry))
    return hass, hass.data["universal_room_automation"]["cm_last_applied_options"]["cm1"]


@pytest.mark.parametrize("key", KEYS4)
def test_selection_keys_in_options_reload_suppress_keys(listener, key):
    hass, _ = _drive(listener, {key: []}, {key: ["Flood Watch"]})
    assert hass.async_create_task.call_count == 0
    assert hass.config_entries.async_reload.call_count == 0


@pytest.mark.parametrize("key", KEYS4)
def test_selection_keys_in_no_live_attr_keys(listener, key):
    _, snap = _drive(listener, {key: []}, {key: ["Flood Watch"]})
    assert snap[key] == ["Flood Watch"]


# ===========================================================================
# E1.9 — retired legacy plumbing; §4.1 single table iterator
# ===========================================================================
def _py_files():
    return [p for p in PKG.rglob("*.py") if "__pycache__" not in p.parts]


def _enclosing_funcs(tree):
    parents = {}
    for node in ast.walk(tree):
        for ch in ast.iter_child_nodes(node):
            parents[ch] = node

    def owner(n):
        while n in parents:
            n = parents[n]
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return n.name
        return "<module>"
    return owner


def test_legacy_plumbing_removed():
    legacy_names = {"CONF_INCLEMENT_POWER_THREAT_EVENTS",
                    "CONF_INCLEMENT_WARN_MIN_SEVERITY",
                    "DEFAULT_INCLEMENT_WARN_MIN_SEVERITY",
                    "INCLEMENT_WARN_MIN_SEVERITY_OPTIONS",
                    "_event_matches_threat"}
    legacy_strings = {"inclement_power_threat_events",
                      "inclement_warn_min_severity"}
    readers = set()
    for p in _py_files():
        tree = ast.parse(p.read_text())
        owner = _enclosing_funcs(tree)
        for n in ast.walk(tree):
            name = None
            if isinstance(n, ast.Name) and n.id in legacy_names:
                name = n.id
            elif isinstance(n, ast.alias) and n.name in legacy_names:
                name = n.name
            elif isinstance(n, ast.Constant) and n.value in legacy_strings:
                name = n.value
            if name:
                readers.add((p.name, owner(n), name))
    allowed = {
        ("energy_const.py", "<module>", "CONF_INCLEMENT_POWER_THREAT_EVENTS"),
        ("energy_const.py", "<module>", "inclement_power_threat_events"),
        ("energy.py", "_check_legacy_threat_list",
         "CONF_INCLEMENT_POWER_THREAT_EVENTS"),
    }
    assert readers <= allowed, readers - allowed
    # The two retired fields are absent from the rendered options schema.
    keys = _form_defaults(_flow())
    assert not (legacy_strings & set(keys))
    assert CONF_INCLEMENT_HOLD_PRODUCTS in keys and CONF_INCLEMENT_BUY_PRODUCTS in keys
    # Retired strings gone from both string files.
    for p in ("strings.json", "translations/en.json"):
        txt = (PKG / p).read_text()
        assert "inclement_warn_min_severity" not in txt
        assert '"inclement_power_threat_events"' not in txt


def test_product_table_iterated_only_in_match_and_build_selection():
    owners = set()
    for p in _py_files():
        tree = ast.parse(p.read_text())
        owner = _enclosing_funcs(tree)
        for n in ast.walk(tree):
            it = None
            if isinstance(n, (ast.For, ast.AsyncFor)):
                it = n.iter
            elif isinstance(n, ast.comprehension):
                it = n.iter
            if it is None:
                continue
            nm = getattr(it, "id", None) or getattr(it, "attr", None)
            if nm == "INCLEMENT_PRODUCT_TABLE":
                owners.add((p.name, owner(n)))
    assert owners == {("inclement.py", "match_product"),
                      ("inclement.py", "build_selection")}
