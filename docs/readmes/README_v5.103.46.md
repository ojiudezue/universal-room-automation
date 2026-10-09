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

## Live validation (prospective)
- After restart: log shows the counter-mode line with source/uom/entities; cost-today attribute `billing_source_today` = counters.
- Import today steps up at each Emporia update; by end of day within 2% of the Emporia daily counter.
- No URA errors at boot.
