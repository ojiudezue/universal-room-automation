# AUDIT: EC source failover class, D0-b/c/d recorder probes (2026-10-29)

Run 2026-10-29 21:50-22:05 CDT, read-only, by ura-prober. Spec: `PLANNING_ec_source_failover_class.md` rev 2 (de891642d), B1 table D0-b..D0-d.
Window: recorder rows 2026-10-24 13:28:06 to 2026-10-29 21:49 CDT (about 5.3 days; the plan assumed 7, the realtime entities only exist from 10-24).

## Method
`ssh ha "python3 -"` with `sqlite3` opened `file:/config/home-assistant_v2.db?mode=ro`, table `states`, joined on `metadata_id` from `states_meta`:
- `sensor.envoy_482543015950_battery_2` = 26860 (realtime SOC; 988 rows)
- `sensor.envoy_482543015950_battery_capacity_2` = 26862 (10 rows)
- `sensor.envoy_482543015950_load_power` = 26857 (45789 rows; the only `load_power`, realtime family)
Realtime poll intervals from `/config/.storage/core.config_entries`: `fast_interval` 30, `live_interval` 10 (seconds; `enable_stream` false). SOC is on the fast coordinator, load_power on the live coordinator (plan D0-a).

Caveat that shapes D0-d: the recorder writes a row only when the value changes. `last_reported_ts` is kept on the row (983 of 988 rows non-null) and holds the last report time of that value. So there is no per-poll series. The valid consecutive-report gap sample is: next row `last_updated_ts` minus previous row `last_reported_ts` (last report with the old value to first report with the new value). One sample per value change, unavailable transitions excluded.

## D0-b: reconnects (unavailable to numeric)
| Reconnect (CDT) | Down for | SOC before | First 3 SOC (offset s) | capacity_2 |
|---|---|---|---|---|
| 10-26 10:09:31 | 17.3 s | 22 | 22 (0), 23 (+91.1), 24 (+794.3) | 40000, unchanged |
| 10-27 07:49:44 | 30.8 s | 19 | 19 (0), 20 (+3576.9), 19 (+3942.8) | 40000, unchanged |
| 10-28 19:17:59 | 30.7 s | 85 | 84 (0), 83 (+119.9), 82 (+269.9) | 40000, no new row |
Only 3 reconnects of the SOC entity in 5.3 days (the same 3 are the capacity_2 events). Spacing after the first value is the value-change spacing (recorder dedup), not poll spacing.
Result: no first value of 0, no jump over 1 pp, no capacity dip. The junk hazard is NOT reproduced on this producer. Consistent with M3. It also means the settle/slew/capacity check are unproven-needed here; they remain insurance against the native-Envoy-style junk (09-26 23:14, 09-25).
Note: the plan's blips are 0.2-0.5 min; measured down times are 17-31 s, matching.

## D0-c: load_power gaps between value changes (last_updated)
n=45784 gaps (unavailable rows excluded): p50 10.0 s, p90 10.2 s, p99 11.1 s, p99.9 23.0 s, max 261.1 s.
Gaps over 120 s: 2. 10-26 10:05:27 gap 261.1 s (ends about 10:09:48, which brackets the 10:09:31 SOC blip) and 10-28 23:05:59 gap 146.1 s (the nightly native outage window). Next largest: 104.4, 96.1, 89.3, 85.7, 85.0, 77.6.
load_power moves nearly every 10 s poll (live interval), so it is a good value-moving witness.
Result: 120 s is about 11x the p99 and is exceeded only twice in 5.3 days, both times when the realtime path was visibly disturbed (so a rejection there is arguably correct). No change needed.

## D0-d: SOC last_reported gaps
n=981 consecutive-report gaps outside unavailable: min 29.4 s, p50 30.03, p90 31.08, p99 31.74 s, max 959.6 s.
Outliers: 959.6 s (10-25 17:34), 434.0 s (10-24 14:03), 197.8 s (10-24 21:20); all other gaps are 34.1 s or less (next: 34.1, 33.2, 32.5). All three outliers are on 10-24/10-25, the first day of the trial (cause unknown; not an unavailable bridge, since those were excluded; possibly integration or HA restarts, unverified). Since 10-26 the max is 34.1 s.
Result: cadence is the configured 30 s with about 1 s jitter. 120 s = 4 polls, about 3.5x the steady-state max.

## Recommended knob values
| Knob | Value | Reason |
|---|---|---|
| `energy_stream_battery_soc_max_age_s` | 120 (keep) | 4 polls; steady max 34 s. 90 would also work; 120 tolerates 3 missed polls. The early-trial outliers (198-960 s) would be rejected at either value, fail-closed, which is correct |
| `DEFAULT_SOC_STREAM_COWITNESS_MAX_AGE_S` | 120 (keep) | p99 11 s; 2 exceedances in 5.3 days, both during real disturbances. Raising to 180 buys only the 146 s case and loosens the freeze detector |
| `DEFAULT_SOC_STREAM_RECONNECT_SETTLE_S` | 60 (keep) | Observed reconnect outages are 17-31 s and no junk was seen; 60 s is about 2 fast polls beyond the longest outage and costs at most 60 s of LKG (which covers 300 s). Not shortened, because zero observed junk is not proof and the 36 s native junk precedent is longer than 30 s |

## Contradictions with the plan
1. D0-d as written ("`last_reported` gap p99 and max") cannot be read directly from the recorder (value-change rows only). Measured via the transition-gap method above; it is a one-per-change sample (981), not every poll. Direct per-poll proof needs a live template or an in-code tripwire.
2. Window is 5.3 days, not 7 (entities created 10-24 13:28).
3. D0-b did not confirm the junk hazard (all three reconnects resumed at the prior value, capacity constant). The plan's trigger for reviving the capacity check ("a capacity dip or first-value 0") did NOT fire; keep it parked in B6.
4. M2 says 3-5 blips; this probe finds exactly 3 SOC unavailable events in the window (load_power has 4 unavailable rows).
5. Not verified here: the unit of `battery_2` is `%` (the stream tier requires exactly `%`, audit :63). Not queried.
