# Plan review 1 (completeness): PLANNING_ec_storm_stage_e.md

**Plan:** `docs/planning/PLANNING_ec_storm_stage_e.md` Rev 1 (commit 6dd862d15, develop). Parent `PLANNING_ec_storm_and_blind_decisions.md` Rev 3.5.
**Framing:** Tier-3 plan review #1, completeness. Every surface the plan claims to cover was re-enumerated with greps over develop; the plan's lists were treated as hypotheses.
**Reviewer note:** energy-only plan, so the HVAC and presence state-of-play docs don't apply.
**Verdict: FIX-PLAN.** 1 HIGH-CRIT, 3 HIGH, 7 MED, 6 LOW. None of them changes the design direction (E0 re-sync, E1 overlay with delta storage, E2 short floor lead). Each needs plan text before build dispatch.

## Findings

### F1 (CRITICAL): E2 cannot gate the floor through `decision.preonset_floor`, because that field is also the buy's gate and target
`preonset_floor` is overloaded. It is the floor-registration signal (`_registered_floor`, `energy_battery.py:6839-6849`), and it is also a precondition and the target of the pre-onset buy (`energy_battery.py:6352` requires `preonset_floor is not None`, and `:6385` writes `reserve_level=decision.preonset_floor`). It also drives the stamp target (`:2835`), the attr (`_stage_b_attrs`, `:3137` emits `inclement_preonset` only when it is non-None), the narration (`:7057`) and the ledger field `tick_preonset_floor` (`energy.py:9544-9550`).
Plan §4 says "The floor gate goes in `_apply_prepare` … The registration site in `determine_mode` stays unchanged and reads `decision.preonset_floor`." If the gate nulls `preonset_floor` outside `[s−4h, s)`, the 12 h buy horizon dies, because the buy at `:6352` never fires 4-12 h ahead. That contradicts E2 step 2 and `test_preonset_buy_horizon_unchanged`. If it doesn't null the field, the floor still registers for the full 12 h and E2 does nothing. The E2 Live criterion (`inclement_preonset` reads `{"floor_from": …}` while the alert is 4-12 h ahead) can't be met either, because the attr is gated on the same field.
**Fix to the plan:** split the field. Keep `preonset_floor` as the target and add `preonset_floor_active: bool` (or `preonset_floor_from`). Route `_registered_floor` (`:6839`), the narration (`:7057`) and the `tick_preonset_floor` ledger (`energy.py:9544`) through the active flag. Keep the buy (`:6352`/`:6385`) and stamp (`:2835`) on the target. Rewrite `_stage_b_attrs` (`:3137`) to emit whenever a prepare alert exists, adding `floor_from` and `active`. List all seven sites in §4 and give each one a mutation drill.

### F2 (HIGH): a third `match_product` caller, the outage ledger, is missing from §4 (Bug Class #53)
`energy_outage_ledger.py:269-280` imports `match_product` and `_effective_tier` directly to write `nws_alert.ura_class` / `ura_tier`. Plan §4 says "its two callers `classify` and `build_record`". §3 claims the ledger "now records the effective class". The E0 Live criterion reads `nws_alert.ura_class`. None of that is wired, because the ledger never sees the overrides.
**Fix:** add the ledger to §4, route it through the same overlay, and add a test (`test_selection_overlay_applies_in_outage_ledger`) plus a Review C drill.

### F3 (HIGH): the overlay has no input path. `match_product`, `build_record` and `update_alert_memory` are config-free module functions
`match_product(alert)` (`inclement.py:277`), `build_record(alert)` (`:321`), `update_alert_memory(memory, feed, healthy, now)` (`:346`, which calls `build_record` at `:403` for admission keyed on `rec.cls`) and the ledger (F2) all take no options. `AlertClassifier()` is already built with no args (`energy_battery.py:2749`). "Apply the overlay at `match_product`'s return" (§4) doesn't say how the overrides reach it. Builders will pick different ways (module global, a new param, constructor state), and a global would be a cross-instance state ingredient.
The overlay also has to set `cls` as well as `tier`. D-B3 admission (`:404`), the prepare split (`:505`) and `prepare_class_of` (`:126`) key on `rec.cls`. If the overlay sets only the tier, a WSW removed from hold is still admitted to memory and still opens a pre-onset floor.
**Fix:** specify an immutable `Selection` value (effective hold set, effective buy set, unlisted set), built once per tick in `_inclement_config()` and passed explicitly to `match_product` / `build_record` / `update_alert_memory` / `classify` (or the `AlertClassifier` constructor) and to the ledger. Its default is the table, so call sites that omit it stay byte-identical. State that the overlay rewrites `cls`, `tier` and `precharge_eligible`.

### F4 (HIGH): the condition-corroboration cap (INV-7(c)) is specified at a per-record site that doesn't exist
Watch condition corroboration is tier-level, not per-record (`inclement.py:1103-1105`: `(condition_stormy and condition_provider_count >= 1)`). There is no `rec_unlisted` variable in scope, so "add `and not rec_unlisted`" (§4, E1.3) doesn't apply as written. A mixed case matters here: an unlisted Flood Watch plus a table Winter Storm Watch.
**Fix:** "condition corroboration counts only if some watch record in `hold_alerts` has `unlisted == False`". Then if every watch record is unlisted, the tier is capped at `partial_hold`, and a table watch alongside it still corroborates. Add a mixed-record test. INV-7 should also say that an unlisted prepare record gets the `lower` pre-onset floor (`max(reserve, partial)`, `_apply_prepare` `:976-978`), which is consistent with the partial cap.

### F5 (MED): E2 floor-follows-buy has no discharge when the buy stops being eligible (feedback_suppression_needs_discharge)
The latch is cleared only when the alert leaves the prepare set (`_apply_prepare` `:964-967`). Suppose a warn latch goes `engaged` at 09:00 for a 21:00 Onset, and then the forecast unconfirms, or the operator turns the option off (the kill switch). `_zone_buy_confirmed` goes False and the buy stops. The latch stays `engaged`, so the 80 floor holds from 09:00 to 21:00. That brings back the 12 h hold E2 is meant to remove, with no buy behind it. A latch that is never rolled back in observation mode (parent §12 limit 14, B-LOW-1) has the same effect.
**Fix:** floor-follows-buy should key on `reached`, or on `engaged` AND this tick's buy is still eligible (option on AND `_zone_buy_confirmed`). Otherwise clear `engaged` when eligibility is lost. Add a test for the unconfirm case and one for option True→False.

### F6 (MED): the INV-7(e) golden can't be "byte-identical except E0 rows" while E2 changes prepare timing
INV-7(e) says the golden is captured on the v5.103.69 tag and its matrix includes `prepare`. E2 changes prepare-floor registration for every zero-override install. §8 contradicts it: "Golden captured after E0, before E1/E2 code".
**Fix:** settle one capture point. Run the zero-override golden with `INCLEMENT_PREONSET_FLOOR_LEAD_H` pinned to the old lead (12), or exclude the floor-registration fields and cover E2 with its own golden (`test_preonset_in_window_hold_unchanged_golden` plus the lead-window tests).

### F7 (MED): `_NO_LIVE_ATTR_KEYS` is missing for the four new option keys
Every options-read key in this arc is in both `_NO_LIVE_ATTR_KEYS` (`__init__.py:7353`, see `:7459-7463`) and `OPTIONS_RELOAD_SUPPRESS_KEYS` (`:7506`). The comment at `__init__.py:6927-6928` says both are required. E1.4 names only the reload-suppress list.
**Fix:** add all four keys to both lists, and add a test for both.

### F8 (MED): form keys vs stored keys are unspecified (snapshot storage and CM reload risk)
The form renders effective lists (§1b names `inclement_hold_products` / `inclement_buy_products`), and storage holds four delta keys. The plan doesn't say the two form keys must be **popped** from `user_input` once the deltas are computed. If they stay, `.storage` holds a full snapshot, and the changed keys include non-suppressed keys, which forces a CM reload. Live (a) and (d) would catch it, but only after deploy. Other gaps in the storage spec: (i) the case-fold rule for comparing stored names with the table (the table matches case-folded, `:292`); (ii) a stored name that leaves `NWS_WEATHER_EVENT_NAMES` must be filtered out of the rendered multi-select default, or HA's selector rejects resubmission; (iii) a `hold_added` name whose table row is later removed becomes an unlisted synthetic watch, and the plan should state that.
**Fix:** add these four to E1.4 and add one test for each.

### F9 (MED): INV-7(d) (buy ⊆ hold) is enforced only at form validation, not at runtime
Deltas are stored per list, so a later table change can break the subset. For example, operator `buy_added=[X]` where X was a default hold, and then an E0-style edit makes X notice by default. Today notice records never reach the buy gates, so this is benign in practice, but INV-7(d) is stated at the effective-set level.
**Fix:** compute `effective_buy = (default_buy ∪ buy_added − buy_removed) ∩ effective_hold` in the overlay, and test it with a monkeypatched table.

### F10 (MED): E1 un-parks two of the parent's parked items without saying so
Parent §10 parks *"Promoting Wind Advisory to hold"* (trigger: a ledger outage in a WIY window) and *"Pre-charge eligibility for convective or tropical products"* (trigger: a ledger outage). E1.2 lets the operator do both (it gives Wind Advisory → watch and Tornado Watch → buy as examples). Inventory row 27 still says "Park (existing triggers)", which contradicts E1.2. Parent INV-6(iii)/(vi) treat eligibility as a reviewed rung-1 evidence set, and E1 makes it rung-2 operator-settable.
**Fix:** state the reclassification (the defaults stay evidence-set; widening is an operator action bounded by INV-7), amend inventory row 27 and update the parent §10 write-back in E3.

### F11 (MED): tests that pin the rows E0/E1 change are not listed
- `test_ec_stage_b_classification.py:129-144` (Freeze Warning / FZW cases, exact-name vs Hard Freeze).
- `test_ec_stage_b_preonset_precharge.py:197-213` (full eligibility golden: `"Freeze Warning": False`).
- `test_ec_stage_c_hourly_outlook.py:188, 288-307` (Hard Freeze / Wind Chill family and apparent-temperature behaviour; Freeze Warning needs equivalents).
- `test_inclement_alert_classifier.py:111` constructs `AlertClassifier(power_threat_events=…, warn_min_severity=…)` and breaks when E1.8 deletes those args.
- `test_ec_stage_b_preonset_precharge.py:569-590` (`test_preonset_floor_none_outside_lead` plus the lead monkeypatches). The plan lists only the first of these.
**Fix:** list them in E0/E1.8/E2 as "update, with the expected diff stated", so a builder can't weaken an assertion silently.

### F12 (LOW): B-LOW-5 scope is incomplete
The daily fetch `_fetch_provider_forecast` (`weather_manager.py:405-433`) also runs under `_refresh_lock` (`:443`) with no timeout, the same as the hourly fetch (`:866`, `:900-904`). Bounding only the hourly call leaves the daily path able to hold the lock. **Fix:** wrap both calls, or the shared `async_call`.

### F13 (LOW): E0 vocabulary details
- `Freeze Watch` code `FZA` is not probe-verified. Table policy (`energy_const.py:688-690`) codes only P3-verified codes. Make it name-only (`None`), as `Freeze Warning` would be if FZW weren't already verified.
- `Cold Weather Advisory` gets the `freeze` family, but its hazard is apparent temperature (it replaced Wind Chill Advisory). Add it to `FORECAST_APPARENT_TEMP_PRODUCTS` so an operator-widened hold or buy confirms on apparent temperature, consistent with Extreme Cold. `Freeze Warning/Watch` correctly stay on air temperature.
- **Orchestrator's question.** `Hurricane Force Wind Warning/Watch`, `Storm Warning/Watch`, `Storm Surge *` and `Typhoon *` are marine/coastal/Pacific products (verified present in the 111-name list today). They should **not** be in the table and should be left out of `NWS_WEATHER_EVENT_NAMES` with the other marine products. `Snow Squall Warning` (polygon-based) and `Lake Effect Snow Warning` are inland weather products. Both can stay in the vocabulary as unlisted. Note that an operator-added Snow Squall Warning becomes a **zone** watch (`polygon_local=False`), not a polygon one. `Special Weather Statement` / `Severe Weather Statement` are statements: leave them out of the vocabulary. `Extreme Heat Warning/Watch` is present (Excessive Heat is gone). It is not a hold product here, so leave it unlisted.
- An unlisted product whose alert carries an NWS code produces an `observed_code` drift entry from the synthetic row (`match_product` `:300-305`). Say that synthetic rows skip drift reporting.

### F14 (LOW): §1a has an inaccurate claim about the legacy plumbing
`_inclement_config` builds `power_threat_events` / `warn_min_severity` (`energy_battery.py:2647-2660`), but `AlertClassifier()` is constructed with no args (`:2749`), so the value is never passed. The DELETE bucket is still correct. Only the stated mechanism is wrong. `_event_matches_threat` (`inclement.py:237`) has zero callers in source and tests.

### F15 (LOW): the repair text goes stale
`strings.json:2321-2323` (`inclement_legacy_threat_list_retired`) says "ask for the product table to be updated". After E1 the operator can choose alerts directly. Point the repair at the new fields (strings + translations).

### F16 (LOW): validation error strings and translations
`buy_not_in_hold` / `buy_needs_forecast` need `strings.json` `error` entries and `translations/en.json` entries. Name them in E1.

### F17 (LOW): number.py docstring
`number.py:1688-1695` (`InclementPreonsetFloorNumber`) describes `INCLEMENT_PREONSET_LEAD_H` as the floor lead. Update it to the buy-horizon/floor-lead split.

## Inventory §9 spot-check (12 rows against the kanban and parent §12/§16)
Correct: rows 4, 5 (`_event_matches_threat` has 0 readers), 6, 8 (EC-OBSERVATION-MODE-RESERVE-BYPASS-1 is shipped_organic), 10 (both cards pre_planning), 11 (waiting_operator), 12 (EC-BLIND-DEESCALATE-TOP-RATE-1 pre_planning), 13 (EC-OBS-DP-EVSE-1 pre_planning), 17, 19, 22, 25.
**Missed** (add these rows):
- **EC-RESERVE-WRITE-GOVERNOR-1** (arc step 1) is `shipped_organic`. It needs a soak-exit disposition and isn't in the inventory.
- **EC-INCLEMENT-HARDENING-1** (parent card) is itself `shipped_organic`. The inventory hangs a residual on it but never disposes it. Stage E should close it as done-with-residuals, or move it into Stage E's acceptance.
- **EC-SOC-LADDER-FULL-WIRING-1** (parked) names the "inclement floor" unconsumed invariant. It needs a one-line check that E2's floor-lead change doesn't fire its trigger.
- Parent §16 deferred item: "D-B5 options-flow field removal has no unit test". E1's `test_legacy_plumbing_removed` could absorb it. Say so.
- Parent §12 limits 21 (lead 48 → two peaks) and 23 (Onset slip > lead reopens discharge) change meaning under E2. Restate them against the floor lead and the buy horizon. Limit 25 (forecast latch shrunk window on restart) belongs with row 23.
- The parked-trigger collision in F10 (row 27).

## Re-enumeration record (greps run, develop @ 6dd862d15)
- `INCLEMENT_PRODUCT_TABLE|INCLEMENT_FORECAST_FAMILY|FORECAST_APPARENT_TEMP_PRODUCTS|precharge_eligible`: `inclement.py:143,162,167,295,340,547,930,1292,1321,1340`; `energy_battery.py:2853,3180`; `sensor.py:9390`. The only table iterator is `inclement.py:295`, which matches the plan.
- `match_product|build_record(`: `inclement.py:326,403,495,502` **plus `energy_outage_ledger.py:271`** (F2).
- `preonset_floor|_preonset_precharge_latch|INCLEMENT_PREONSET_LEAD_H`: `inclement.py:478,794,859,1009`; `energy_battery.py:474,2693,2798,2816,2835,3137-3145,6352,6385,6403-6410,6839,7057`; `energy.py:9420,9544-9589`; `number.py:1688-1699`; `__init__.py:7463,7506` (F1, F5, F17).
- `get_forecasts|_refresh_lock`: `weather_manager.py:160,414,443,866,903` (F12).
- Tests: `grep -rlE "INCLEMENT_PRODUCT_TABLE|Hard Freeze|Wind Chill|Freeze Warning|AlertClassifier\(|power_threat"` gives four files (F11).
- NWS vocabulary: `api.weather.gov/alerts/types` fetched 2026-10-17, 111 names. Hard Freeze*, Wind Chill*, Excessive Heat* are absent. Freeze Warning/Watch, Extreme Cold*, Cold Weather Advisory, Winter Weather Advisory, Snow Squall, Lake Effect Snow, Hurricane Force Wind*, Storm Warning/Watch, Extreme Heat* are present.
- Parked items: parent §10 parked list, §12 limits 14/21/23/25/26, §13, §16 deferred; kanban cards matched on arc/EC-INCLEMENT/EC-STORM/preonset.

## Summary
| Severity | Count | IDs |
|---|---|---|
| CRITICAL | 1 | F1 |
| HIGH | 3 | F2, F3, F4 |
| MED | 7 | F5-F11 |
| LOW | 6 | F12-F17 |

Bug classes: #53 computed-but-not-consumed (F1, F2), overloaded field / coincidental equality masking a concept split (F1), suppression without discharge (F5), config-free pure function needing config (F3), reload-suppress/live-attr pairing (F7).

---

## Re-check Rev 2 (a181ae959, 2026-10-17)

**Verdict: FIX-PLAN.** 1 HIGH, 3 MED, 1 LOW, all new. Every Rev-1 finding is resolved in the plan text. N1 changes INV-7(c), so it has to be fixed before build dispatch. N2-N5 are spec gaps that a builder would otherwise fill in its own way.

### Rev-1 findings, verified in the plan text (not just in the §12 mapping)
- **F1:** resolved. §E2.4 splits the field and §4.3 lists the seven readers. My independent grep found exactly seven source readers (`energy_battery.py:2835, 3137-3140, 6352, 6385, 6839, 7057`; `energy.py:9545`), plus the producer (`inclement.py:1009`) and config/knob sites (`:794, 859-864`, `energy_battery.py:2693, 2798`, `number.py:1699`, `__init__.py:7463, 7506`). There is no eighth source reader. `energy.py:9548` (`preonset_event`) derives from the registered floor, which is consistent. `sensor.py:9389` passes the attr through, so it isn't a field reader.
- **F2:** resolved (§4.1).
- **F3:** resolved (§E1.3, §4.1; no global). Callers re-enumerated:
  - `match_product`: `inclement.py:326, 495`; `energy_outage_ledger.py:271`.
  - `build_record`: `:403, :502`.
  - `update_alert_memory`: `energy_battery.py:2753` only.
  - `AlertClassifier(`: `energy_battery.py:2749` only in source. The test constructions (`test_ec_stage_b_*` ×8, `test_inclement_alert_classifier.py:111`) stay valid through the `TABLE_SELECTION` default, except `:111`, which is listed.
  - `security.py:404` is an unrelated `_build_record_action`.
- **F4:** resolved (§4.2). The conjunct covers all three legs and `watch_requires_corroboration` both ways.
- **F5, F7, F8, F9, F10, F12-F17:** resolved as written.
- **F6:** resolved in principle. N2 covers what is still missing.
- **F11:** partly resolved. N3 covers the rest.
- **Inventory misses:** resolved (rows 14, 15, 26-30; limits 21/23/25 restated in §E2).

### N1 (HIGH): a non-corroborable record can still BUY, on two paths
INV-7(c) caps non-corroborable records at partial hold, but it doesn't stop them buying. After E0, `Cold Weather Advisory` has the `freeze` family, so a CWA widened to hold+buy passes `buy_needs_forecast` and `build_selection`'s `∩ hold ∩ family`.
- **Prepare path.** Repro: CWA prepare record 3 h out, SOC 30, hour ∈ S (or bottom rate today), apparent-temp forecast ≤ 28, option True.
  - `high` is False (E1.4), so the floor is `lower` = 50.
  - `pre` (`inclement.py:984-993`) gates only on `_zone_buy_confirmed(prows, confirmed)` and `soc < floor`, so `pre = True` and CFG turns on.
  - The same record in its active window is capped at partial and can never buy. So the pre-onset buy exists only because nothing gates it.
- **Co-active full-hold path, which breaks INV-7(f).** Repro: Tornado Watch (table, `eligible=False`, `energy_const.py:712`) is corroborated by lightning with 2 providers, at bottom rate, with SOC 50. Alone, it gives `full_hold` and no buy. Adding the widened CWA (hold+buy, confirmed) means `_zone_buy_confirmed(hold_alerts)` (`:929-933`, `:1131-1133`) picks the CWA record, so `grid_precharge` becomes True. The decision now differs from the table product alone. This happens under both `watch_requires_corroboration` values.
- **Fix:** add `buy ⊆ corroborable` to `build_selection` (`buy = … ∩ hold ∩ family-or-polygon ∩ corroborable_names`), and add a `buy_needs_table_hold` validation error (strings and translations). Restate INV-7(c) as "never counts toward corroboration **and never buys**". Add these tests:
  - `test_widened_prepare_never_buys`;
  - `test_widened_buy_does_not_change_coactive_table_decision[req_true|req_false]`.

  Add a drill that drops the new `∩ corroborable`. The alternative is to filter `_zone_buy_confirmed` on `r.corroborable`, but the selection-level cut is simpler: the form never offers a buy that can't happen.

### N2 (MED): the §E1.10 golden can't be built as specified
- **No harness contract.**
  - The plan doesn't name the entry point (`InclementFusion.decide(…, bottom_rate=…, preonset_latch=…)`, `inclement.py:877`).
  - It doesn't say how a cell becomes concrete `now`/Onset datetimes, or which fake battery and TOU are used. The scheduler needs `tou.period_rank`/`get_current_period` per hour (via `battery._tou`, `energy_battery.py:735`), while v5.103.69 takes a bare `bottom_rate` bool. The fake TOU's ranks must agree with the bottom/top axis.
  - It doesn't fix `_expected_solar_surplus_pct`, the starting latch state (fresh, single tick) or the `GRID_CHARGE_PP_PER_H` and margin values that define S.
- **Circular allowed-diff rule.** If the "rule in the script" that generates the allowed diff calls the build's `schedule_buy_hours`, a broken scheduler excuses its own diffs. The rule needs an independent reimplementation of the §E2.2 formula, or explicitly enumerated cells.
- **Incomplete allowed-diff list.** It lists only removed buys (a bottom-rate hour outside S). E2 also adds buys at rank > 0 hours inside S (the "unavoidable top rate" case, §E2 acceptance). Both directions must be in the rule. Otherwise the golden goes RED on correct code, or someone loosens it by hand.

### N3 (MED): tests pinning changed surfaces are still under-listed (F11 residual)
- **`test_ec_stage_b_preonset_precharge.py`.** About 45 `.preonset_floor` references (`:552-638, 719-760, 917-1049, 1330-1334, 1685`). The plan names only `:569-590` plus a generic "D-B6 timing tests move". Classify each reference as target or registered, the same discipline as §4.3, so no assertion silently weakens.
- **`test_inclement_preonset_attr_shape` (`:948-960`)** asserts an exact dict. The new fields `active`/`floor_from`/`buy_hours`/`event_time*` break it, and the "emitted whenever target non-None" change alters when it is None.
- **`test_part2_ec_hc_writeback.py:218` (key set) and `:374` (`len == 104`).** Four new keys take the count to 108.

### N4 (MED): the `inclement_selection` attr has no path to the entity
`sensor.py:9376-9393` is an explicit key allowlist, and `test_inclement_state_sensor.py:35-48` pins the key set. E1.7 doesn't add `inclement_selection` to either, so the attr would exist only in `battery_status` (Bug Class #53). Add both to E1.7 and its tests.

### N5 (LOW): the shape of the effective row is unstated
"Adds `corroborable`" to a row that readers index positionally: `build_record` reads `row[2..4]` (`inclement.py:338-340`), and the ledger reads `_row[2]`, `_row[3]` and `_effective_tier(_row)` (`energy_outage_ledger.py:272-274`). State the return shape (positions 0-4 unchanged, `corroborable` appended or returned separately) so the index readers stay correct.

### Selection widening: hold depth checked (task item 2)
- **Widened or unlisted alone.** A widened or unlisted record is always `watch`, never `warn`. So the warn full-hold leg is unreachable. The only full-hold path is a corroborated watch (`:1095-1151` plus the recoverability branch `:1153-1172`), which is closed by §4.2 under both `watch_requires_corroboration` values. The prepare floor is capped at `lower` by E1.4. A partial-hold ceiling holds for widened records alone, and for mixed sets via the table record.
- **Buy.** It does not hold. See N1.
