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

## Validated 2026-10-17 (restart 18:00 CDT; read through 20:29 CDT)

| Criterion | Result | Evidence |
|---|---|---|
| Installed and loaded | PASS | manifest v5.103.70; 50/50 URA entries loaded |
| 0 URA ERRORs | PASS | system log after restart: no `universal_room_automation` ERRORs; WARNINGs pre-existing (consumption cross-check, optimization cap, post-restart coverage) |
| `inclement_selection` present, no overrides | PASS | `{"alerts":[],"overrides":{all empty}}` on `sensor.ura_energy_coordinator_battery_strategy` |
| `inclement_preonset` null, `inclement_alerts_stale` false | PASS | both as expected, no active alert |
| `inclement_forecast.fetched_at` advances | PASS | 01:01:33Z → 01:21:33Z (20 min; README said ~30) |
| CM options unchanged | PASS | `inclement_grid_precharge_on_hold: False`; no `*_added/_removed` keys |
| `reserve_write` pattern | PASS | 1 row 18:01:32, applied, value 10, `inclement_floor` null, no failures |
| Envoy stability / reassociation (operator ask) | STABLE | battery entity: 0 unavailable transitions in 2 h before 13:23, 2 h before 18:00, and 18:00–20:05; entry loaded ~2 min after restart; no reauth/reconnect log lines; write-verify `ok`, 0 mismatches 24 h |
| First hold-class alert schedules a buy block | NOT OBSERVABLE | no alert active; event-gated |

Caveats found during validation (not regressions):
- Envoy MQTT stream sensors unavailable all day, before the restart too (`stream_trust` disabled).
- `sensor.envoy_482543015950_grid_power` has no state object.
- Cloud reserve oracle `number.iq_battery_hacs_battery_reserve` reads 9.0 against a commanded 10, while write-verify says `ok`. To be investigated (tolerance or rounding).
