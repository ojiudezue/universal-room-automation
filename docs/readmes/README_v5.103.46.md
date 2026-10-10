# URA v5.103.46 — Bill counters: live fix-ups

Post-deploy fixes for v5.103.45, found while switching the live install to the Emporia meter counters. Two reviews (both FIX-REQUIRED, all folded), orchestrator re-drill, full-suite name-diff clean. Cards: ENERGY-BILL-ACCURACY-1.

## What was wrong
- After a restart or a settings save, the first counter reading was absorbed into the new baseline instead of billed — energy since the last snapshot was lost (all of it since midnight on a restart across midnight).
- The counter's "live kW" (used by peak-avoidance) divided 15 minutes of meter energy by the 5-minute tick, overstating kW about 3x.
- "Bill from = Power readings" with kWh meters configured would read kWh totals as kW.
- The settings form could not clear the grid meter fields.
- No log said why counter mode was or wasn't active, so a live "source = None" could not be diagnosed.

## Fix
- The first tick after a restore books the change since the snapshot (no loss, no double count).
- Counter kW is computed per meter from the meter's own update window; TOU pro-ration and the sanity cap use the same window. Counter readings stay fresh for 20 minutes (Emporia updates every ~15).
- Power-readings mode ignores kWh meters and uses the Envoy.
- New "Clear grid meters" option on the Energy settings page.
- One-time log lines when counter mode turns on, and when it is off while both meters are set (with the reason).

## Live validation — Validated 2026-10-10 (overnight pass, HA restarted 2026-10-09 11:27 CDT)

| Criterion | Result | Evidence |
|---|---|---|
| `billing_source_today` = counters | PASS | `sensor.ura_energy_coordinator_energy_cost_today` attr `billing_source_today: counters`, `counter_last_update` 01:56:58; `energy_daily` 2026-10-09 row `billing_source=counters` |
| Import within 2% of Emporia | PASS | 10-10 02:05: URA `energy_import_today` 13.858 kWh vs `sensor.mains_vue_3_mainsfromgrid_energy_today` 13.8579. 10-09 after switch-over: URA +4.67 kWh vs Emporia +4.61 kWh (1.3%) |
| No URA errors at boot | PASS | system_log since boot: URA entries are WARNING only, no ERROR |
| Counter-mode log line | not checked live | INFO line fell outside the readable error_log window; the attribute above is the authoritative signal |

Residual (not carded, ~$2): the 10-09 row reads 59.19 kWh vs Emporia 80.80 because the pre-switch morning was carried over from the old power-integration total. 10-07/10-08 were already replaced by `recorder_backfill`.
