"""HVAC W3 G0-Q3 — shoulder-season value bound for a TOU-derived pre-cool window (G1 gate).

Q3 (plan REV 2, two-sided rule): per LOCAL shoulder day (Mar-May + Oct-Nov 2025, Mar-May 2026):
AC kWh 17-21 from SPAN ac1/ac_2/ac_3 LTS hourly means. Qualifying day = >= 1 h of net export >= 0.5 kW
inside 13-17 (Envoy LTS, 2026-04-11 on; earlier days are `no_grid_split` and PV is unverifiable) AND
>= 1 kWh AC draw 17-21.
  UB   = sum AC_kWh(17-21) x (0.086442 - 0.043481)            -> NO-GO if UB < $25/shoulder-year
  REAL = sum min(AC_kWh(17-21), BANK) x delta, BANK = offset F (live attr energy_precool_offset) x
         zones banked x K kWh/F/zone                            -> GO only if REAL >= $25 AND >= 10 days
K: not derivable cleanly (S12_pre_cool banking borrows are NOT confined to the Path A window — see
probe output), so K is ASSUMED 0.5, UNVERIFIED; K = 1.0 printed as a sensitivity.
Battery valuation printed both ways: (i) every freed kWh at the mid-rate delta (export = import);
(ii) only the grid-import share, because SOC at 21:00 vs the next-day charge target shows whether freed
battery kWh would just be carried into off-peak.
Primary source = recorder LTS (never purged); energy_history = cross-check only. All buckets are local
(America/Chicago) from timestamps; energy_history UTC-derived calendar columns are never read (review H2).
READ-ONLY: both DBs mode=ro; stdout only.
Run: ssh ha "python3 -" < scripts/probes/hvac_w3_g0_q3_shoulder_value.py
"""
import sqlite3, collections
from datetime import datetime, timezone, date
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Chicago")
REC = "file:/config/home-assistant_v2.db?mode=ro"
URA = "file:/config/universal_room_automation/data/universal_room_automation.db?mode=ro"
D_RATE = 0.086442 - 0.043481
SPAN = ["sensor.span_panel_ac1_power", "sensor.span_panel_ac_2_power", "sensor.span_panel_ac_3_power"]
OAT = "sensor.office_b_outdoor_temperature"   # Carrier outdoor temp, LTS mean/max since 2025-03-12
ENV = "sensor.envoy_482543015950_"
PM = range(13, 17); EVE = range(17, 21)
OFFSET_F = 2.0     # live attr sensor.ura_hvac_coordinator_mode energy_precool_offset = -2.0 (read 2026-09-28)
ZONES = 3          # upper value; scope auto_pv_tiered may bank fewer
KWH_PER_F = 0.5    # ASSUMED, UNVERIFIED (see docstring); sensitivity at 1.0 printed
BANK_CAP = OFFSET_F * ZONES * KWH_PER_F
CHARGE_TARGET = 80 # live number.ura_energy_coordinator_peak_buffer_target / fill_priority_soc = 80 (read 2026-09-28)

rec = sqlite3.connect(REC, uri=True); ura = sqlite3.connect(URA, uri=True)
print("opened:", REC, "|", URA)
print(f"BANK = {OFFSET_F} F x {ZONES} zones x K={KWH_PER_F} kWh/F = {BANK_CAP} kWh/day (K ASSUMED, UNVERIFIED); sensitivity K=1.0 -> {OFFSET_F*ZONES} kWh/day")

def lts(eid, col="mean"):
    mid = rec.execute("SELECT id FROM statistics_meta WHERE statistic_id=?", (eid,)).fetchone()
    if not mid:
        print("  (no LTS for", eid, ")"); return {}
    out = {}
    for st, v in rec.execute(f"SELECT start_ts, {col} FROM statistics WHERE metadata_id=? ORDER BY start_ts", (mid[0],)):
        if v is not None:
            dl = datetime.fromtimestamp(st, TZ); out[(dl.date(), dl.hour)] = v
    first = min(out) if out else None
    print(f"  LTS {eid} [{col}] hours={len(out)} earliest={first}")
    return out

def lts_delta(eid, scale):
    """hourly energy from a has_sum counter: sum(h) - sum(h-1), in kWh."""
    mid = rec.execute("SELECT id FROM statistics_meta WHERE statistic_id=?", (eid,)).fetchone()
    out = {}; prev = None
    for st, s in rec.execute("SELECT start_ts, sum FROM statistics WHERE metadata_id=? ORDER BY start_ts", (mid[0],)):
        if s is not None and prev is not None:
            dl = datetime.fromtimestamp(st, TZ); out[(dl.date(), dl.hour)] = max(s - prev, 0) * scale
        prev = s
    print(f"  LTS {eid} [delta sum] hours={len(out)} earliest={min(out) if out else None}")
    return out

print("\nsources:")
span = {e: lts(e) for e in SPAN}
oat_max = lts(OAT, "max")
exp_kwh = lts_delta(ENV + "lifetime_net_energy_production", 1000.0)   # MWh -> kWh
imp_kwh = lts_delta(ENV + "lifetime_net_energy_consumption", 1000.0)
use_kwh = lts_delta(ENV + "lifetime_energy_consumption", 1000.0)
bat_kwh = lts_delta(ENV + "lifetime_battery_energy_discharged", 1000.0)
soc = lts(ENV + "battery")

def ac_eve(d):
    tot = 0.0
    for h in EVE:
        hv = [span[e].get((d, h)) for e in SPAN]
        if any(v is None for v in hv):
            return None
        tot += sum(max(v, 0) for v in hv) / 1000.0
    return tot

def shoulder_label(d):
    if d.month in (3, 4, 5): return f"{d.year}-spring"
    if d.month in (10, 11): return f"{d.year}-fall"
    return None

days = sorted({d for (d, h) in span[SPAN[0]]})
agg = collections.defaultdict(lambda: collections.Counter())
detail = collections.defaultdict(list)
for d in days:
    lab = shoulder_label(d)
    if not lab or d >= datetime.now(TZ).date():
        continue
    ac = ac_eve(d)
    if ac is None:
        agg[lab]["days_missing_ac"] += 1; continue
    a = agg[lab]; a["days"] += 1; a["ac_all"] += ac
    has_env = all((d, h) in exp_kwh for h in PM)
    pv_ok = has_env and any(exp_kwh[(d, h)] >= 0.5 for h in PM)
    if ac < 1.0:
        continue
    if has_env and not pv_ok:
        a["fail_pv"] += 1; continue
    key = "qual" if has_env else "qual_ngs"   # ngs = no_grid_split (no Envoy LTS; PV unverifiable)
    a[key + "_days"] += 1; a[key + "_ac"] += ac
    a[key + "_cap"] += min(ac, BANK_CAP); a[key + "_cap1"] += min(ac, OFFSET_F * ZONES * 1.0)
    if has_env:
        imp = sum(imp_kwh.get((d, h), 0) for h in EVE); use = sum(use_kwh.get((d, h), 0) for h in EVE)
        bat = sum(bat_kwh.get((d, h), 0) for h in EVE)
        a["imp"] += imp; a["use"] += use; a["bat"] += bat
        detail[lab].append((d, round(ac, 2), round(imp, 2), round(use, 2), round(bat, 2), soc.get((d, 21))))

print("\nper shoulder season (AC = SPAN 3 circuits, 17-21 local):")
tot = collections.Counter()
for lab in sorted(agg):
    a = agg[lab]
    q = a["qual_days"] + a["qual_ngs_days"]; qac = a["qual_ac"] + a["qual_ngs_ac"]
    qcap = a["qual_cap"] + a["qual_ngs_cap"]; qcap1 = a["qual_cap1"] + a["qual_ngs_cap1"]
    print(f"  {lab}: days={a['days']} (missing AC {a['days_missing_ac']}) AC_all={a['ac_all']:.0f} kWh | qualifying={q} "
          f"(PV-verified {a['qual_days']}, no_grid_split {a['qual_ngs_days']}, failed PV test {a['fail_pv']}) AC_qual={qac:.0f} kWh")
    print(f"      UB=${qac*D_RATE:.2f}  REAL(K=0.5)=${qcap*D_RATE:.2f}  REAL(K=1.0)=${qcap1*D_RATE:.2f}")
    if a["use"]:
        print(f"      Envoy 17-21 on PV-verified days: import={a['imp']:.0f} use={a['use']:.0f} battery_discharged={a['bat']:.0f} kWh grid_frac={a['imp']/a['use']:.3f}")
    if lab.startswith("2025"):
        for k in ("days", "qual_days", "qual_ngs_days"):
            tot[k] += a[k]
        tot["qac"] += qac; tot["qcap"] += qcap; tot["qcap1"] += qcap1
for lab in sorted(detail):
    print(f"  {lab} PV-verified qualifying days (date, AC17-21, import17-21, use17-21, batt_dis17-21, SOC% mean 21h):")
    for x in detail[lab]:
        print("     ", x)
nd = tot["days"]
if nd:
    f = 153 / nd
    print(f"\nSHOULDER-YEAR 2025 (spring from 03-12 + fall; {nd} days with AC data of 153; qualifying {tot['qual_days']+tot['qual_ngs_days']}, all no_grid_split):")
    print(f"   UB = ${tot['qac']*D_RATE:.2f} (pro-rated x153/{nd}: ${tot['qac']*D_RATE*f:.2f})")
    print(f"   REAL(K=0.5) = ${tot['qcap']*D_RATE:.2f} (pro-rated ${tot['qcap']*D_RATE*f:.2f}) | REAL(K=1.0) = ${tot['qcap1']*D_RATE:.2f} (pro-rated ${tot['qcap1']*D_RATE*f:.2f})")
    s26 = agg.get("2026-spring")
    if s26 and s26["use"]:
        gf = s26["imp"] / s26["use"]
        socs = [x[5] for x in detail["2026-spring"] if x[5] is not None]
        above = sum(1 for x in socs if x >= CHARGE_TARGET)
        print(f"   battery: 2026-spring PV-verified days SOC% at 21:00 mean={sum(socs)/len(socs):.0f}, >= charge target {CHARGE_TARGET}% on {above}/{len(socs)} days;"
              f" battery_discharged 17-21 {s26['bat']:.0f} kWh vs house use {s26['use']:.0f} kWh (battery serves load, no mid-peak export)")
        print(f"   REAL(K=0.5) valued at grid share only (gf={gf:.3f}): ${tot['qcap']*D_RATE*gf*f:.2f}/shoulder-yr | REAL(K=1.0) grid share: ${tot['qcap1']*D_RATE*gf*f:.2f}")

# Why K is not derived: S12_pre_cool banking borrows vs the Path A window (local hours)
bh = collections.Counter()
for (st,) in ura.execute("SELECT started_ts FROM hvac_excursion_events WHERE kind='banking'"):
    bh[datetime.fromisoformat(st).astimezone(TZ).hour] += 1
inwin = sum(v for h, v in bh.items() if 10 <= h < 14)
print(f"\nS12_pre_cool banking excursions by local start hour: {sorted(bh.items())} -> inside [10,14): {inwin}/{sum(bh.values())}")

# ---- cross-check: energy_history (local-time bucketed; 1/1000-scaled days rescaled) ----
rows = ura.execute("SELECT timestamp, grid_import, whole_house_energy FROM energy_history "
                   "WHERE timestamp >= '2026-04-11T05:00' AND timestamp < '2026-06-01T05:00'").fetchall()
byday = collections.defaultdict(list)
for ts, gi, wh in rows:
    dl = datetime.fromisoformat(ts).replace(tzinfo=timezone.utc).astimezone(TZ)
    byday[dl.date()].append((dl, gi, wh))
sg = sw = 0.0
for d, rs in byday.items():
    mx = max([abs(x) for r in rs for x in r[1:] if x is not None] or [0])
    s = 1000.0 if 0 < mx < 0.1 else 1.0
    for dl, gi, wh in rs:
        if dl.hour in EVE and gi is not None and wh is not None:
            sg += gi * s; sw += wh * s
print(f"\ncross-check energy_history 2026-04-11..05-31, 17-21 local, all days: grid_frac = {sg/sw if sw else float('nan'):.3f}")
