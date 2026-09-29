"""HVAC W3 G0-Q8 — does D5 change any outcome? (G2-D5 gate)

Q8 (per plan review H3): Since the v5.103.9 D5 rename + occupancy gate (deployed 2026-09-18 00:16 CDT),
how many preset_change rows with json reason == 'energy_shed_cap_reached' changed the outcome, i.e.
the zone was NOT already fused-empty past the vacancy grace AND the house-state target was NOT already
'away' (house_state == 'away' means the write would have gone away anyway)? Pro-rated to 30 d.
Plus total coast/shed minutes (EC hvac_constraint, recorder 7 d), and the blind/phantom minutes
(Q7 definitions, 0.5 kW) inside coast/shed windows.
GO (D5 input swap) if >= 3 outcome-changing fires / 30 d OR blind+phantom minutes inside coast/shed
exceed 10 % of coast/shed minutes. Otherwise DROP the D5 half of G2.
READ-ONLY (mode=ro), stdout only. Run: ssh ha "python3 -" < scripts/probes/hvac_w3_g0_q8_d5_outcome.py
"""
import sqlite3, json, collections
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Chicago")
REC = "file:/config/home-assistant_v2.db?mode=ro"
URA = "file:/config/universal_room_automation/data/universal_room_automation.db?mode=ro"
ura = sqlite3.connect(URA, uri=True); rec = sqlite3.connect(REC, uri=True)
print("opened:", REC, "|", URA)
print("ura_activity_log span:", ura.execute("SELECT min(timestamp), max(timestamp), count(*) FROM ura_activity_log").fetchone())

V5_103_9 = "2026-09-18T05:16:50+00:00"   # git: v5.103.9 tag 2026-09-18 00:16:50 -0500
rows = ura.execute(
    "SELECT timestamp, action, zone, details_json FROM ura_activity_log "
    "WHERE coordinator LIKE '%hvac%' AND json_extract(details_json,'$.reason')='energy_shed_cap_reached' "
    "AND action='preset_change' ORDER BY timestamp").fetchall()
pre = [r for r in rows if r[0] < V5_103_9]; post = [r for r in rows if r[0] >= V5_103_9]
print(f"\nreason=energy_shed_cap_reached preset_change rows: total {len(rows)} (pre-v5.103.9 {len(pre)}, post {len(post)})")
old_name = ura.execute("SELECT count(*) FROM ura_activity_log WHERE json_extract(details_json,'$.reason')='runtime_exceeded'").fetchone()[0]
print(f"legacy reason=runtime_exceeded rows (pre-rename D5, excluded): {old_name}")
outcome = []
for ts, action, zone, dj in post:
    d = json.loads(dj)
    oc = d.get("zone_vacant_past_grace") is False and d.get("house_state") != "away"
    if oc: outcome.append(ts)
    print("   ", ts, zone, "house_state=", d.get("house_state"), "vacant_past_grace=", d.get("zone_vacant_past_grace"),
          "constraint=", d.get("constraint_mode"), "any_room_hvac_occupied=", d.get("any_room_hvac_occupied"),
          d.get("old_preset"), "->", d.get("new_preset"), "| OUTCOME-CHANGING" if oc else "| not (already away/vacant)")
now_utc = datetime.now(ZoneInfo("UTC"))
days = (now_utc - datetime.fromisoformat(V5_103_9)).total_seconds() / 86400
print(f"outcome-changing fires since v5.103.9: {len(outcome)} over {days:.1f} d -> pro-rated {len(outcome)*30/days:.1f} / 30 d")
supp = ura.execute("SELECT count(*) FROM ura_activity_log WHERE json_extract(details_json,'$.reason')='energy_shed_cap_deferred_occupied' AND timestamp >= ?", (V5_103_9,)).fetchone()[0]
print(f"D5 occupancy-gate suppression rows (energy_shed_cap_deferred_occupied) since v5.103.9: {supp}")

# coast/shed windows from EC hvac_constraint (recorder, 7 d)
def ser(eid, attrs=False):
    mid = rec.execute("SELECT metadata_id FROM states_meta WHERE entity_id=?", (eid,)).fetchone()[0]
    if attrs:
        out = []
        for ts, s, a in rec.execute("SELECT s.last_updated_ts, s.state, sa.shared_attrs FROM states s LEFT JOIN state_attributes sa "
                                    "ON s.attributes_id=sa.attributes_id WHERE s.metadata_id=? ORDER BY 1", (mid,)):
            act = None
            if a:
                try: act = json.loads(a).get("hvac_action")
                except Exception: pass
            out.append((ts, s, act))
        return out
    return rec.execute("SELECT last_updated_ts, state FROM states WHERE metadata_id=? ORDER BY 1", (mid,)).fetchall()
hc = ser("sensor.ura_energy_coordinator_hvac_constraint")
now = datetime.now(TZ).timestamp()
dist = collections.Counter()
for i, (ts, s) in enumerate(hc):
    nxt = hc[i + 1][0] if i + 1 < len(hc) else now
    dist[s] += nxt - ts
print(f"\nhvac_constraint window {datetime.fromtimestamp(hc[0][0],TZ)} .. now; minutes by state:",
      {k: round(v / 60) for k, v in dist.most_common()})
win = [(ts, hc[i + 1][0] if i + 1 < len(hc) else now) for i, (ts, s) in enumerate(hc) if s in ("coast", "shed")]
cs_min = sum(b - a for a, b in win) / 60
print(f"coast+shed minutes (7 d) = {cs_min:.0f}")

FIX = {"zone_1": ("climate.thermostat_bryant_wifi_studyb_zone_1", "sensor.span_panel_ac1_power"),
       "zone_2": ("climate.up_hallway_zone_2", "sensor.span_panel_ac_2_power"),
       "zone_3": ("climate.back_hallway_zone_3", "sensor.span_panel_ac_3_power")}
def inwin(t):
    return any(a <= t < b for a, b in win)
tot_bp = 0.0; tot_true = 0.0
for zid, (cl, sp) in FIX.items():
    ev = [(ts, 0, (s, a)) for ts, s, a in ser(cl, True)] + [(ts, 1, s) for ts, s in ser(sp)]
    ev.sort(key=lambda x: (x[0], x[1]))
    cc = (None, None); k = None; pt = None; b = p = pt0 = 0.0
    for ts, kind, v in ev:
        if pt is not None and k is not None and cc[0] in ("cool", "heat_cool", "auto") and win:
            # integrate only the part inside coast/shed windows
            for a0, a1 in win:
                lo, hi = max(pt, a0), min(ts, a1)
                if hi > lo:
                    on = k >= 0.5
                    if on and cc[1] != "cooling": b += hi - lo
                    if (not on) and cc[1] == "cooling": p += hi - lo
                    if k < 0.05 and cc[1] == "cooling": pt0 += hi - lo
        if kind == 0: cc = v
        else:
            try: k = float(v) / 1000
            except (TypeError, ValueError): k = None
        pt = ts
    tot_bp += b + p; tot_true += b + pt0
    print(f"  {zid}: blind {b/60:.0f} min, phantom {p/60:.0f} min (of which SPAN<0.05 kW true-off {pt0/60:.0f}) inside coast/shed")
print(f"blind+phantom inside coast/shed (summed over 3 zones) = {tot_bp/60:.0f} min = "
      f"{100*tot_bp/60/max(cs_min*3,1):.1f}% of zone-coast/shed-minutes (3 zones x {cs_min:.0f})")
print(f"blind + TRUE-off phantom (SPAN<0.05 kW) inside coast/shed = {tot_true/60:.0f} min = {100*tot_true/60/max(cs_min*3,1):.1f}%")
