# v5.103.70: EC storm Stage E — freeze re-sync, operator alert selection, cheapest-block pre-storm charge

Cards: EC-STORM-PRODUCT-SELECTION-EXTERNAL-1 and EC-STORM-PREONSET-TIMING-1, parent EC-INCLEMENT-HARDENING-1. Plan: `docs/planning/PLANNING_ec_storm_stage_e.md` Rev 3.2+. The plan had two plan reviews and three re-check rounds. The operator approved all open questions on 2026-10-17.

**Tier 3.** Reviews are in `docs/reviews/code-review/ec_stage_e_review_{A,B,C,D}.md`:
- A: SHIP.
- B: SHIP.
- C: 211 single-site mutations; 4 MEDIUM test gaps were closed.
- D: FIX-REQUIRED (1 HIGH, 2 MED), fixed, then the re-pass was SHIP.

Operator deploy go: 2026-10-17. **Deploy risk: HIGH** (it changes battery reserve and grid-charge decisions). Grid pre-charge stays **off** (`inclement_grid_precharge_on_hold` = False) until the operator enables it.

## Problem → solution

- **Problem:** NWS retired Hard Freeze and Wind Chill alerts. Today's Freeze Warning was notice-only and Freeze Watch was ignored, so a hard-freeze night got no hold.
  **Solution (E0):** Freeze Warning and Freeze Watch are watch-class. A partial hold applies on frost nights; a full hold or buy needs a forecast of 28 °F or below. Cold Weather Advisory now confirms on the apparent (feels-like) temperature. An NWS vocabulary snapshot is included (49 names).
- **Problem:** the alert table was fixed in code. The operator could not choose which alerts hold or buy, and another location could not adapt the table.
  **Solution (E1):**
  - The options flow has two lists: "Alerts that hold the battery" and "Of those, alerts that may buy grid power". They are picked from the NWS names, with no free text.
  - Only deltas from the defaults are stored. The reviewed internal table stays the default and is never changed by the operator's choices.
  - The operator chooses whether an alert type acts, never how. Locality, forecast confirmation and the 60-min polygon cap are unchanged.
  - Added or widened products are capped at partial hold. They never buy and never corroborate.
  - "May buy" must be a subset of "holds", must be a table-default holder, and must be forecast-confirmable. This is checked when the form is saved and again at runtime.
  - New attribute `inclement_selection` on the battery strategy sensor.
  - Dead legacy threat-list plumbing is removed.
- **Problem:** the pre-onset floor started up to 12 h before Onset, and the buy fired at the first cheap hour, so the battery was held through hours that didn't matter.
  **Solution (E2):** the operator's 2026-10-17 rulings.
  - The pre-storm grid buy is **one contiguous block of the cheapest hours ending closest to the event**. Hours needed = (target − SOC) ÷ 50 %/h + 1 margin hour.
  - A higher-rate hour is used only when no all-cheapest block fits.
  - The floor holds from the first buy hour to Onset. With no buy, it starts 4 h before Onset.
  - The schedule freezes once. It re-plans if the event time changes, and is cleared when the alert ends, the option is turned off, the forecast stops confirming, or in observation mode.
  - An NWS Update (same Event + code, overlapping window) carries the plan and the "reached" marker to the new ID, so there is no re-buy.
  - Added alerts never set the event time.
  - Rate ranking uses the existing TOU engine.
- **Problem:** a hung forecast provider could hold the refresh lock.
  **Solution (E3):** a 20 s timeout on the hourly and daily forecast fetches.
- **Problem:** an alert with no Ends and Expires ≤ Onset never held.
  **Solution:** the end falls back to Onset + 48 h.

## Not done / parked
- E2b (forecast-timed hold for watches): E2-P probe NO-GO (`docs/planning/AUDIT_ec_storm_e2p_onset_vs_hazard.md`); parked with a revival trigger.
- Reading NWS `references`/VTEC (the integration drops them): parked (`docs/planning/AUDIT_nws_alert_fields_and_updates.md`).

## Tests
- Golden test: with zero overrides, behaviour vs v5.103.69 differs only in the Freeze Warning/Watch cells.
- Builder mutation drills: all RED except documented equivalents. Orchestrator drills: 5/5 RED, tree clean (tie → later block, unranked hour breaks a block, corroboration requires a corroborable record, the event basis excludes unlisted alerts, an Onset is not an Update).
- Cycle files: 2819 pass, in forward and reverse order.
- Full-suite name-diff vs fa7e1ffe2 at e2de7f4e1: CLEAN, 0 NEW / 0 GONE (118 failing names both sides; +97 passed = new tests). Isolated pass over 121 importing files: CLEAN. The 3 soc-ladder NEW at e4bdcecc9 were a fixture building an unreachable watch-without-record state (fixed, assertions unchanged).

## Live validation (prospective)
- **Live:** 0 URA ERRORs after restart.
- **Live:** strategy-sensor attribute `inclement_selection` exists, with no overrides.
- **Live:** with no alert, `inclement_preonset` is null.
- **Live:** `inclement_forecast.fetched_at` advances about every 30 min.
- **Live:** CM options are unchanged (`inclement_grid_precharge_on_hold` False; no override keys written).
- **Live:** `reserve_write` rows match the pre-restart pattern.
- **Live (operator ask):** Envoy stability and reassociation after restart — the Envoy telemetry and write-path reconnect cleanly, the reserve/CFG oracles read back, and there is no new reconnect/unavailable churn vs the pre-restart rate.
- **Live (event-gated):** the first Freeze Warning or hold-class alert produces a schedule in the cheapest contiguous block before Onset, recorded in `inclement_preonset.buy_hours`.
