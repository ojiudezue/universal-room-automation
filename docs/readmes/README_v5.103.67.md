# v5.103.67: EC outage ledger (arc Stage L)

**Tier 2-DB.** Three framing-disjoint reviews:
- **A (data integrity):** SHIP, with 1 MEDIUM and 2 LOWs, all fixed.
- **B (integration and lifecycle):** FIX. B-HIGH-1 was fixed. B-MED-1 was refuted, because `log_activity` does go through `_write_queue` (`database.py:665`).
- **C (mutation):** FIX. 12 survivors, all now killed by named tests.

Stage L of `docs/planning/PLANNING_ec_storm_and_blind_decisions.md` Rev 2.1, which is arc steps 2-7.

## Problem
- We had no durable record of real outages or of which alerts were active when they happened. Enphase keeps only about 7 weeks of history.
- Without that record, the storm-hold tiers can't be checked against reality. The Wind Advisory vs freeze correlation had to be rebuilt from public data by hand.

## Solution
- **`nws_alert` rows:** one row per NWS alert message seen, deduplicated by alert `ID`, with URL and then `Event|Sent` as fallbacks.
  - Updates get their own rows. Cancels are kept.
  - The seen set survives restarts: it is seeded from the DB over the last 72 h, and the seed is retried if it fails.
  - The rows are written from a hook placed right after `determine_mode`. That spot runs even during grid-disconnect and blind ticks, and it can never raise into the decision cycle.
- **`grid_outage` rows (primary witness):** a daily sweep of the Enphase cloud calendar, `calendar.main_panel_wall_enphase_cloud_hacs_system_event_history`.
  - It matches by substring and looks back 48 h. The first sweep runs at +5 min.
  - Each row records off-grid and on-grid times, generator events, and the EC decision and SOC nearest the event.
  - Rows are deduplicated across restarts.
- **Local witnesses (corroboration only):** `grid_enabled` and Enpower `grid_status` write `local_only` rows with at most one row per 30 min per sensor. They never open an episode.
  - `iq_gateway_hacs_grid_mode` is not used: it showed 98 false flips in 7 days.
- **Retention:** these ledger actions are exempt from `prune_activity_log`, which normally deletes rows after 7/30 days.
- **No change** to reserve, inclement, or decision behaviour.

## Known limits
- The local witness is unproven. A real or deliberate islanding event is needed to show whether `grid_status` / `grid_enabled` flip at all.
- If the seed fails 3 times, a restart can re-log active alerts.
- The fields `ura_class` / `ura_tier` / `local` stay `unknown` until Stage B.

## Tests
- Cycle file: 62 passed.
- Mutation coverage: 95 independent review mutants plus 53 builder drills plus 19 re-drills, all RED.
- Real HA timer test: confirms the sweep runs on the event loop.

## Live validation (prospective)
- **Live:** within 10 min of restart there are 0 URA ERRORs mentioning `outage` or `ledger`, and no "thread" RuntimeError.
- **Live:** at +5 min the first cloud sweep has run. Either `grid_outage` rows exist for any off-grid events in the last 48 h, or a log line says 0 events were found, or a warning says the calendar could not be resolved.
- **Live:** when an NWS alert is active, there is 1 `nws_alert` row per alert `ID`. After a second restart there are no duplicates.
