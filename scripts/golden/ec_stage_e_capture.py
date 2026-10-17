"""EC storm Stage E §E1.10 golden: zero-override classification / hold / buy
projection, captured on v5.103.69 and compared on the Stage E build branch.

PLANNING_ec_storm_stage_e.md Rev 3.2 §E1.10 (INV-7(e)).

Entry point per cell: ``AlertClassifier().classify`` then
``InclementFusion.decide(...)`` -- one tick, fresh pre-onset latch ``{}``,
fresh buy schedule ``{}`` (build side only; detected by signature), empty
forecast latch (confirmed IDs computed fresh from the cell's outlook).

Usage (from the repo root, HA venv):
    .venv-ha/bin/python scripts/golden/ec_stage_e_capture.py --capture
        -> writes quality/tests/fixtures/ec_stage_e_golden_v5_103_69.json
    .venv-ha/bin/python scripts/golden/ec_stage_e_capture.py --compare
        -> exit 0 iff every diff is in an allowed (E0) product

The capture MUST run on a tree whose custom_components equals tag v5.103.69.
The comparison is also run in-suite by
``test_zero_override_golden_identical_to_v5_103_69``.
"""
from __future__ import annotations

import argparse
import inspect
import json
import sys
from dataclasses import fields
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

FIXTURE = REPO / "quality" / "tests" / "fixtures" / "ec_stage_e_golden_v5_103_69.json"

# Allowed zero-override diff (INV-7(e)): exactly the E0 products, by name.
ALLOWED_DIFF_PRODUCTS = frozenset({"Freeze Warning", "Freeze Watch"})

_CHI = ZoneInfo("America/Chicago")
_UNLISTED = "Flood Watch"

# Axes (order is the fixture's index order -- never reorder without
# recapturing on v5.103.69).
WINDOWS = ("active", "prepare_3h", "prepare_8h", "polygon_in_cap", "polygon_out_of_cap")
TOU_SEASON = (
    ("winter", "bottom", (2026, 12, 16, 3)),
    ("winter", "top", (2026, 12, 16, 18)),
    ("summer", "bottom", (2026, 7, 15, 3)),
    ("summer", "top", (2026, 7, 15, 17)),
)
SOCS = (None, 30, 95)
CONDITIONS = ("calm", "stormy")
WRC = (True, False)
OPTIONS = (True, False)
FORECASTS = ("confirms", "not", "none")


def _mods():
    from custom_components.universal_room_automation.domain_coordinators import (
        energy_const as ec,
        inclement as inc,
    )
    return ec, inc


class FakeTOU:
    """Rank helpers built from the committed PEC tariff (energy_const
    PEC_TOU_RATES), so rank agrees with the bottom/top axis by construction."""

    def __init__(self, rates):
        self._rates = rates

    def get_season(self, now):
        for name, data in self._rates.items():
            if now.month in data["months"]:
                return name
        return "shoulder"

    def get_current_period(self, now):
        season = self.get_season(now)
        for pname, pdata in self._rates[season]["periods"].items():
            for s, e in pdata["hours"]:
                if s <= now.hour < e:
                    return pname
        return "off_peak"

    def period_rank(self, season, period):
        try:
            rate = float(self._rates[season]["periods"][period]["import_rate"])
        except (KeyError, TypeError, ValueError):
            return None
        rates = sorted({float(p["import_rate"]) for p in self._rates[season]["periods"].values()})
        return rates.index(rate)

    def rate_rank(self, now):
        return self.period_rank(self.get_season(now), self.get_current_period(now))

    def is_bottom_rate(self, now):
        return self.rate_rank(now) == 0


def products():
    ec, _inc = _mods()
    names = [row[1] for row in ec.INCLEMENT_PRODUCT_TABLE]
    for extra in ("Freeze Watch", _UNLISTED):
        if extra not in names:
            names.append(extra)
    # Stable order independent of table edits: sorted by name.
    return sorted(set(names))


def _code_for(name):
    ec, _inc = _mods()
    for row in ec.INCLEMENT_PRODUCT_TABLE:
        if row[1] == name:
            return row[0]
    return None


def _outlook(kind, start, end):
    _ec, inc = _mods()
    if kind == "none":
        return None
    if kind == "confirms":
        return inc.Outlook(
            window_start=start, window_end=end, hours=12,
            min_temp_f=20.0, max_pop=80.0, max_precip_mm_no_pop=None,
            max_gust=60.0, conditions=frozenset({"lightning"}),
            sources=(("weather.fake", "a", "b"),), min_apparent_f=15.0,
        )
    return inc.Outlook(
        window_start=start, window_end=end, hours=12,
        min_temp_f=55.0, max_pop=10.0, max_precip_mm_no_pop=None,
        max_gust=10.0, conditions=frozenset({"sunny"}),
        sources=(("weather.fake", "a", "b"),), min_apparent_f=55.0,
    )


def _iso(d):
    return d.isoformat() if d is not None else None


def project(cls, dec, window):
    hold = [
        [r.alert_id, r.cls, r.tier] for r in getattr(cls, "hold_alerts", ())
    ]
    prep = [r.alert_id for r in getattr(cls, "prepare_alerts", ())]
    names = {f.name for f in fields(dec)}
    target = dec.preonset_target if "preonset_target" in names else dec.preonset_floor
    out = {
        "tier": cls.tier,
        "contributing_events": list(cls.contributing_events),
        "expires_at": _iso(cls.expires_at),
        "hold": hold,
        "prepare": prep,
        "precharge_eligible": bool(cls.precharge_eligible),
        "polygon_topup_active": bool(cls.polygon_topup_active),
        "prepare_precharge_eligible": bool(cls.prepare_precharge_eligible),
        "hold_depth": dec.hold_depth,
        "reserve_floor": dec.reserve_floor,
        "preonset_target": target,
        "reason": dec.reason,
    }
    if not window.startswith("prepare"):
        # Buy + registered floor only on non-prepare cells (§E1.10: prepare
        # buy/floor timing is owned by the INV-8/INV-9 hand-table tests).
        out["grid_precharge"] = bool(dec.grid_precharge)
        out["preonset_precharge"] = bool(dec.preonset_precharge)
        out["preonset_floor"] = dec.preonset_floor
    return out


def run_cell(product, window, season_tou, soc, cond, wrc, option, fc):
    ec, inc = _mods()
    _season, _tou_kind, ymdh = season_tou
    now = datetime(*ymdh, tzinfo=_CHI)
    if window == "active":
        start = now - timedelta(hours=1)
    elif window == "prepare_3h":
        start = now + timedelta(hours=3)
    elif window == "prepare_8h":
        start = now + timedelta(hours=8)
    elif window == "polygon_in_cap":
        start = now - timedelta(minutes=20)
    else:
        start = now - timedelta(minutes=70)
    end = start + timedelta(hours=12)
    alert = {
        "Event": product, "Type": "Alert", "Status": "Actual",
        "Severity": "Severe", "Certainty": "Likely",
        "ID": f"id-{product}", "Onset": start.isoformat(),
        "Ends": end.isoformat(),
        "Sent": (start - timedelta(hours=1)).isoformat(),
    }
    code = _code_for(product)
    if code:
        alert["NWSCode"] = code
    cls = inc.AlertClassifier().classify([alert], now=now)
    outlook = _outlook(fc, start, end)
    confirmed = set()
    for r in tuple(cls.hold_alerts) + tuple(cls.prepare_alerts):
        if r.polygon_local or not r.alert_id:
            continue
        if inc.forecast_family(r.event) is None:
            continue
        if inc.forecast_confirms(r.event, outlook):
            confirmed.add(r.alert_id)
    tou = FakeTOU(ec.PEC_TOU_RATES)
    battery = SimpleNamespace(
        _tou=tou,
        _expected_solar_surplus_pct=lambda _n, _m: 0.0,
    )
    fusion = inc.InclementFusion(
        reserve_soc=20,
        partial_hold_reserve_floor=ec.DEFAULT_INCLEMENT_PARTIAL_HOLD_RESERVE_FLOOR,
        grid_precharge_on_hold=option,
        watch_requires_corroboration=wrc,
        surplus_margin_pct=ec.DEFAULT_INCLEMENT_RECOVERABLE_SURPLUS_MARGIN_PCT,
        storm_charge_threshold=90,
        blind_full_hold_floor=ec.INCLEMENT_BLIND_FULL_HOLD_FLOOR_PCT,
        preonset_floor=ec.INCLEMENT_PREONSET_FLOOR_PCT,
    )
    kwargs = dict(
        battery=battery,
        classification=cls,
        condition_stormy=(cond == "stormy"),
        condition_provider_count=(2 if cond == "stormy" else 0),
        tou_period=tou.get_current_period(now),
        now=now,
        current_soc=soc,
        bottom_rate=tou.is_bottom_rate(now),
        forecast_confirmed_ids=frozenset(confirmed),
        preonset_latch={},
    )
    if "preonset_buy_schedule" in inspect.signature(fusion.decide).parameters:
        kwargs["preonset_buy_schedule"] = {}
    dec = fusion.decide(**kwargs)
    return project(cls, dec, window)


def cells():
    for wi, window in enumerate(WINDOWS):
        for ti, st in enumerate(TOU_SEASON):
            for si, soc in enumerate(SOCS):
                for ci, cond in enumerate(CONDITIONS):
                    for wri, wrc in enumerate(WRC):
                        for oi, opt in enumerate(OPTIONS):
                            for fi, fc in enumerate(FORECASTS):
                                yield (window, st, soc, cond, wrc, opt, fc)


def knob_header():
    ec, _inc = _mods()
    hdr = {
        "INCLEMENT_PREONSET_LEAD_H": ec.INCLEMENT_PREONSET_LEAD_H,
        "INCLEMENT_PREONSET_FLOOR_PCT": ec.INCLEMENT_PREONSET_FLOOR_PCT,
        "DEFAULT_INCLEMENT_PARTIAL_HOLD_RESERVE_FLOOR": ec.DEFAULT_INCLEMENT_PARTIAL_HOLD_RESERVE_FLOOR,
        "INCLEMENT_BLIND_FULL_HOLD_FLOOR_PCT": ec.INCLEMENT_BLIND_FULL_HOLD_FLOOR_PCT,
        "INCLEMENT_POINT_FEED_POLYGON_EXACT": ec.INCLEMENT_POINT_FEED_POLYGON_EXACT,
        "INCLEMENT_POLYGON_TOPUP_MAX_MIN": ec.INCLEMENT_POLYGON_TOPUP_MAX_MIN,
        "reserve_soc": 20,
        "storm_charge_threshold": 90,
    }
    for name in ("INCLEMENT_GRID_CHARGE_PP_PER_H", "INCLEMENT_PREONSET_BUY_MARGIN_H",
                 "INCLEMENT_PREONSET_FLOOR_LEAD_H"):
        if hasattr(ec, name):
            hdr[name] = getattr(ec, name)
    return hdr


def compute():
    """{product: [projection index per cell]}, [projection json strings]."""
    from homeassistant.util import dt as dt_util
    saved = dt_util.DEFAULT_TIME_ZONE
    dt_util.set_default_time_zone(_CHI)
    try:
        table: list[str] = []
        index: dict[str, int] = {}
        out: dict[str, list[int]] = {}
        for prod in products():
            seq = []
            for cell in cells():
                proj = json.dumps(run_cell(prod, *cell), sort_keys=True)
                if proj not in index:
                    index[proj] = len(table)
                    table.append(proj)
                seq.append(index[proj])
            out[prod] = seq
        return out, table
    finally:
        dt_util.set_default_time_zone(saved)


def capture(path=FIXTURE):
    out, table = compute()
    doc = {
        "about": "EC storm Stage E §E1.10 zero-override golden, captured on v5.103.69",
        "axes": {
            "windows": list(WINDOWS),
            "tou_season": [[s, k, list(t)] for s, k, t in TOU_SEASON],
            "socs": list(SOCS), "conditions": list(CONDITIONS),
            "watch_requires_corroboration": list(WRC),
            "option": list(OPTIONS), "forecast": list(FORECASTS),
        },
        "knobs": knob_header(),
        "projections": table,
        "cells": out,
    }
    path.write_text(json.dumps(doc, indent=0, sort_keys=True) + "\n")
    return doc


def compare(path=FIXTURE):
    """Return (allowed_diffs, disallowed_diffs) as lists of
    (product, cell_tuple, golden_proj, build_proj)."""
    doc = json.loads(path.read_text())
    out, table = compute()
    gtable = doc["projections"]
    cell_list = list(cells())
    allowed, bad = [], []
    for prod in sorted(set(doc["cells"]) | set(out)):
        g = doc["cells"].get(prod)
        b = out.get(prod)
        if g is None or b is None:
            bad.append((prod, None, g is not None, b is not None))
            continue
        for i, cell in enumerate(cell_list):
            gp, bp = gtable[g[i]], table[b[i]]
            if gp != bp:
                rec = (prod, cell, gp, bp)
                (allowed if prod in ALLOWED_DIFF_PRODUCTS else bad).append(rec)
    return allowed, bad


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--capture", action="store_true")
    g.add_argument("--compare", action="store_true")
    args = ap.parse_args()
    if args.capture:
        doc = capture()
        print(f"captured {len(doc['cells'])} products x "
              f"{len(next(iter(doc['cells'].values())))} cells, "
              f"{len(doc['projections'])} distinct projections -> {FIXTURE}")
        return 0
    allowed, bad = compare()
    print(f"allowed (E0) diffs: {len(allowed)}; disallowed diffs: {len(bad)}")
    for rec in bad[:20]:
        print("DISALLOWED", rec)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
