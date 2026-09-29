"""HVAC W3 G0-Q1(a) — offline engine-vs-tariff check (per plan review H1).

Runs LOCALLY (not on HA): .venv-ha/bin/python scripts/probes/hvac_w3_g0_q1_engine_offline.py
Reads the live tariff file read-only via `ssh ha cat`, builds the real TOURateEngine from it with the
production loader (_from_parsed_data) and also the built-in PEC engine, then for every local hour
2026-10-01 .. 2027-09-30 (incl. DST days 2026-11-01, 2027-03-14) compares engine.get_current_period()
and get_season() against TWO independent tables: (1) built by this probe directly from the file's
`hours`/`months` lists (plan REV 2 Q1a), (2) hand-written from the operator-stated PEC tariff.
Also checks get_next_high_rate_transition() from local midnight for every day (the G1 anchor):
expected 14:00 summer, 17:00 shoulder, 05:00 winter.
No writes anywhere; stdout only.
"""
import collections, importlib.util, json, subprocess, sys, types
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2] / "custom_components/universal_room_automation/domain_coordinators"
pkg = types.ModuleType("dcstub"); pkg.__path__ = [str(ROOT)]; sys.modules["dcstub"] = pkg
def load(name):
    spec = importlib.util.spec_from_file_location(f"dcstub.{name}", ROOT / f"{name}.py")
    m = importlib.util.module_from_spec(spec); sys.modules[spec.name] = m; spec.loader.exec_module(m); return m
load("energy_const")
tou = load("energy_tou")

from homeassistant.util import dt as dt_util
TZ = ZoneInfo("America/Chicago")
dt_util.set_default_time_zone(TZ)

raw = subprocess.run(["ssh", "ha", "cat /config/universal_room_automation/tou_rates.json"], capture_output=True, text=True, check=True).stdout
data = json.loads(raw)
errs = tou.TOURateEngine._validate_parsed_data(data)
print("live file validation errors:", errs)
eng_file = tou.TOURateEngine._from_parsed_data(data, "/config/universal_room_automation/tou_rates.json", "tou_rates.json")
eng_builtin = tou.TOURateEngine()
print("file engine status:", eng_file.get_period_info(datetime(2026, 9, 28, 12, tzinfo=TZ)).get("tou_file_status"))

ORACLE = {  # independent, hand-written from the operator-stated PEC tariff
    "summer": ({6, 7, 8, 9}, [("off_peak", 0, 14), ("mid_peak", 14, 16), ("peak", 16, 20), ("mid_peak", 20, 21), ("off_peak", 21, 24)]),
    "shoulder": ({3, 4, 5, 10, 11}, [("off_peak", 0, 17), ("mid_peak", 17, 21), ("off_peak", 21, 24)]),
    "winter": ({12, 1, 2}, [("off_peak", 0, 5), ("mid_peak", 5, 9), ("off_peak", 9, 17), ("mid_peak", 17, 21), ("off_peak", 21, 24)]),
}
FIRST_RISE = {"summer": 14, "shoulder": 17, "winter": 5}
def oracle_hand(dt):
    for s, (months, spans) in ORACLE.items():
        if dt.month in months:
            for p, a, b in spans:
                if a <= dt.hour < b:
                    return s, p
def oracle_file(dt):  # independent table from the raw file lists (not via the engine)
    for s, sd in data["seasons"].items():
        if dt.month in sd["months"]:
            for p, pd in sd["periods"].items():
                for a, b in pd["hours"]:
                    if a <= dt.hour < b:
                        return s, p
            return s, "off_peak"

START = datetime(2026, 10, 1, 0, 30, tzinfo=TZ); END = datetime(2027, 10, 1, tzinfo=TZ)
for label, eng in (("file", eng_file), ("built-in", eng_builtin)):
    for oname, oracle in (("file-table", oracle_file), ("hand-table", oracle_hand)):
        bad = 0; n = 0; dst_hours = 0
        u = START.astimezone(ZoneInfo("UTC"))
        while u < END:
            t = u.astimezone(TZ)   # step real hours in UTC so DST days get 23/25 local hours
            n += 1
            if t.date() in (datetime(2026, 11, 1).date(), datetime(2027, 3, 14).date()):
                dst_hours += 1
            s_, p_ = oracle(t)
            if eng.get_current_period(t) != p_ or eng.get_season(t) != s_:
                bad += 1
                if bad <= 5: print("  MISMATCH", label, oname, t, eng.get_season(t), eng.get_current_period(t), "oracle", s_, p_)
            u += timedelta(hours=1)
        print(f"[{label} vs {oname}] hourly period+season mismatches: {bad}/{n} (DST-day hours covered: {dst_hours} = 25+23)")
    abad = 0; days = 0; firsts = collections.Counter()
    d = START.date()
    while d < END.date():
        days += 1
        m0 = datetime(d.year, d.month, d.day, tzinfo=TZ)
        s_, _ = oracle_file(m0)
        nxt = eng.get_next_high_rate_transition(m0)
        got = nxt[0] if isinstance(nxt, tuple) else nxt
        if got is not None and got.date() == d:
            firsts[(s_, got.hour)] += 1
        if got is None or got.date() != d or got.hour != FIRST_RISE[s_]:
            abad += 1
            if abad <= 5: print("  ANCHOR MISMATCH", label, d, s_, nxt)
        d += timedelta(days=1)
    print(f"[{label}] first-rise anchor mismatches: {abad}/{days}; (season, first-rise hour) counts: {dict(firsts)}")
