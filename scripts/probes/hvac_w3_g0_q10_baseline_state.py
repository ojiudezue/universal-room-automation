"""HVAC W3 G0-Q10 — short-cycle baseline state (M5: decided by live data; this re-confirms it).

Q10: metric_baselines rows for (hvac, short_cycle_rate, zone_1/2/3): sample_count, mean, std.
Plan REV 2: sample_count = 14 on all zones -> baseline matured on hvac_action-derived counts -> RENAME.
READ-ONLY (mode=ro), stdout only. Run: ssh ha "python3 -" < scripts/probes/hvac_w3_g0_q10_baseline_state.py
"""
import sqlite3, math
URA = "file:/config/universal_room_automation/data/universal_room_automation.db?mode=ro"
u = sqlite3.connect(URA, uri=True)
print("opened:", URA)
for m, s, mean, var, n, lu in u.execute(
        "SELECT metric_name, scope, mean, variance, sample_count, last_updated FROM metric_baselines "
        "WHERE coordinator_id='hvac' AND metric_name LIKE '%short_cycle%' ORDER BY scope"):
    print(f"  {m} {s}: sample_count={n} mean={mean:.2f} std={math.sqrt(var):.2f} last_updated={lu}")
