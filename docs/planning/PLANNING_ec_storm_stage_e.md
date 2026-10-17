# PLANNING: EC storm Stage E (operator alert selection, pre-onset timing, arc closeout inventory)

**Parent plan:** `PLANNING_ec_storm_and_blind_decisions.md` Rev 3.5 (Stages L, A, B, C shipped: v5.103.67, v5.103.68, v5.103.69). Stage E follows that plan's decision model, invariants INV-1 to INV-6, knob ladder and review protocol. Where this doc says nothing, the parent governs.
**Arc:** `ARC_energy_coordinator_resilience.md`.
**Cards:** EC-STORM-PRODUCT-SELECTION-EXTERNAL-1 (E1), EC-STORM-PREONSET-TIMING-1 (E2), parent EC-INCLEMENT-HARDENING-1 (E0, residual_2026_10_17_legacy_threat_list, E3 inventory). Batch `ec-storm-stage-e`.
**Tier:** 3 (alert classification and grid-buy eligibility feed every storm hold, and E2 moves a reserve floor in time). Two Tier-3 plan reviews before build dispatch (completeness; adversarial build-prediction).
**Status:** Rev 1, 2026-10-17. Coordinator critique of E1 (8 points) folded in as the recommended design (§E1). Not built.

**Operator input (2026-10-17, verbatim):**
- "I think an externalization is interesting. The data backed version is good but annotate could Extend it. It also helps with diff locations who which will have different data and the operator can add or remove things that can hold, or buy. It can be simple list externally and more complicated internally ie we will in the internal table with known good things/code but the user selection stays simple."
- "We didn't talk about good hold onset time. Holding for 12 hours is wasteful. We should hold when it counts ie 3-4 hours to expected event time intersect forecast confirmed time. Vs alert time."
- "These can be follow ups but like immediately plus whatever else is in the arc or cards we spawned from it or things we dropped."
- (Doctrine, unchanged) "get an alert, check the applicability … check the local weather for the next x hours that alert applies, and then make an energy decision." "I don't want grid buys on mere rain."

---

## 0. Read this first: three findings that change the asks

1. **The NWS no longer issues four of our HOLD products (verified 2026-10-17).** `GET https://api.weather.gov/alerts/types` returns 111 event names. It has **no** `Hard Freeze Warning`, `Hard Freeze Watch`, `Wind Chill Warning`, `Wind Chill Watch` or `Wind Chill Advisory`. It does have `Freeze Warning`, `Freeze Watch`, `Extreme Cold Warning/Watch` and `Cold Weather Advisory`. (My understanding is that this is the NWS "hazard simplification" consolidation of 2024-25: Hard Freeze folded into Freeze, Wind Chill into Extreme Cold / Cold Weather Advisory. The date and mapping are from memory and **unverified**; the current vocabulary itself is verified.) Our table (`energy_const.py:694-725`) holds on Hard Freeze and Wind Chill, which can no longer arrive, and classes **Freeze Warning** as `notice` (`:721`). So a hard freeze that comes without an Extreme Cold product produces **no hold and no buy** today. Freezes are the one hazard the operator has seen take power down. This is a live defect in the shipped Stage B table, and it comes ahead of the asks: **E0**.
2. **The hourly outlook keeps per-hour rows, but only exposes an aggregate.** `WeatherProviderManager._hourly[eid] = {"fetched_at", "rows": {hour_utc: {temp_f, apparent_f, pop, mm, gust, condition}}}` (`weather_manager.py:882`, built at `:897-944`). The public `hourly_outlook(start, end)` (`:946-1018`) collapses the window into one `Outlook` (`min_temp_f`, `max_pop`, `max_gust`, a `conditions` set; `inclement.py:1263-1284`). `forecast_confirms` (`inclement.py:1298-1356`) evaluates that aggregate. Locating the hazard hour therefore needs a new per-hour read. The data is already in RAM, so no new fetch is needed. Note that the aggregate can confirm a winter storm from a cold hour and a wet hour that are different hours; a per-hour predicate would not.
3. **The forecast intersection cannot move the floor earlier, and later barely matters.** The pre-onset floor only covers `[start − lead, start)`. At `start` (Onset) the active hold takes over (D-B1). By the operator's definition the expected event time `T` lies inside the alert window, so `T ≥ start`. Intersecting with the forecast can only push the floor's start later, into a slot that is immediately followed by a hold. That saves at most `lead` hours of floor, and only on alerts where the forecast hazard hour is after Onset. Shortening the lead itself captures the operator's actual complaint ("holding for 12 hours is wasteful"). This is the marginal-benefit finding for E2 (§E2).

---

## 1. Institutional context verified

### 1a. REUSE / EXTEND / BUILD per piece

| Piece | Prior art (file:line) | Verdict |
|---|---|---|
| Internal product table | `INCLEMENT_PRODUCT_TABLE` `energy_const.py:694-725`, tuple `(code, name, class, polygon_local, precharge_eligible)`; matcher `match_product` `inclement.py:277-310`; `_effective_tier` `:313-319`; `build_record` `:321` | **REUSE** as the reviewed annotation layer. E0 edits rows. E1 overlays the operator selection on it at match time and never mutates it. |
| Forecast family | `INCLEMENT_FORECAST_FAMILY` `energy_const.py:815-835`; `forecast_family` `inclement.py:1287-1295` | **REUSE.** E0 adds `Freeze Warning` / `Freeze Watch` → `freeze`. "No family" is the E1 rule that refuses a buy. |
| Buy gate | `InclementFusion._zone_buy_confirmed` `inclement.py:918` (same-record eligible AND forecast-confirmed; §16 deviation 1); polygon leg `_precharge_flags` / `polygon_topup_records` | **REUSE unchanged.** E1 feeds an effective `precharge_eligible` per record, and the gates stay as they are. |
| Operator setting persistence | CM options; `OPTIONS_RELOAD_SUPPRESS_KEYS` (`__init__.py`, reload decision `changed_keys ⊆ …` at `:6774`); `_inclement_config()` re-reads `{**data, **options}` every tick (`energy_battery.py:2600-2700`) | **REUSE** the options-read path, rung 2 (options flow), with no setter and no reload. |
| Options-flow inclement section | `config_flow.py` EC step: inclement keys imported `:6029-6043`, `INCLEMENT_ADVANCED_SECTION` | **EXTEND**: two new fields in the existing section. |
| Legacy list | `CONF_INCLEMENT_POWER_THREAT_EVENTS` / `CONF_INCLEMENT_WARN_MIN_SEVERITY` `energy_const.py:615-616`; defaults `:634-644`; read `energy_battery.py:2648-2660` and passed into `AlertClassifier` which discards it (`inclement.py:449-453`); config_flow imports `:6030-6031, 6036-6037` and parse `:6164-6168`; strings `strings.json:983-984, 1068-1069` (+ `translations/en.json`); repair check `energy.py:8335-8367 _check_legacy_threat_list` | **Triage §E1.4**: DELETE the plumbing, KEEP the constants the repair check reads. |
| NWS event vocabulary | none in repo (grep `alerts/types`: 0) | **NEW** rung-1 snapshot tuple `NWS_WEATHER_EVENT_NAMES` (weather subset of `api.weather.gov/alerts/types`, fetched 2026-10-17, cited in the constant). Not fetched at runtime. |
| Prepare window | `AlertClassifier.classify` prepare split `inclement.py:476-519` (`now < start ≤ now + lead`); `INCLEMENT_PREONSET_LEAD_H` `energy_const.py:744` (12); latch `_preonset_precharge_latch` (D-B6) | **EXTEND** (E2): separate the floor lead from the buy horizon. |
| Per-hour forecast | `_hourly` rows `weather_manager.py:882` | Not needed for the recommended E2. **Parked** as E2b, which would reuse these rows. |
| Decision attrs | `_inclement_attrs` `energy_battery.py:~2764`; `sensor.ura_inclement_state` copies `inclement_*` keys (`sensor.py:~9376`) | **EXTEND**: one attr `inclement_selection` (E1.5). |

### 1b. Greps run (develop @ a34a076df)
- `INCLEMENT_PRODUCT_TABLE|INCLEMENT_PREONSET_LEAD_H|CONF_INCLEMENT_POWER_THREAT_EVENTS|CONF_INCLEMENT_WARN_MIN_SEVERITY` over the integration: hits listed in §1a. Nothing else reads the legacy keys.
- `power_threat_events|warn_min_severity` in `config_flow.py`, `inclement.py`, `energy_battery.py`, `strings.json`: as in §1a. `inclement.py:453` `del`s them.
- `hourly_outlook` callers: only `energy_battery.py:2945-2947` (`_forecast_confirmed_ids`).
- `INCLEMENT_FORECAST_FAMILY`: `energy_const.py:815`. It contains the four retired product names and no `Freeze Warning`.
- Proposed new names (`inclement_hold_products`, `inclement_buy_products`, `NWS_WEATHER_EVENT_NAMES`, `INCLEMENT_PREONSET_FLOOR_LEAD_H`, `inclement_selection`): `grep -rn` gives 0 hits each. **NEW.**
- Board: arc and parent cards enumerated in §E3 (`grep "arc: 'ARC_energy\|parent.*EC-INCLEMENT-HARDENING-1" kanban.data.yaml`).

### 1c. Docs and memory read
Parent plan in full (Rev 3.5, §0-§16), `ARC_energy_coordinator_resilience.md`, `README_v5.103.68.md`, `README_v5.103.69.md`, `AUDIT_ec_storm_stage0_probes.md` (P1, P2(c) onset semantics), `AUDIT_nws_alert_history_lakeway.md`, `AUDIT_outage_alert_correlation.md` (Table 3), the three cards. Memory: `project_storm_counsel_doctrine.md`, `reference_ec_config_surface.md`, `feedback_label_style_guide.md`, `feedback_configurability_clarity.md`. HVAC and presence state-of-play docs do not apply (energy only).

### 1d. Measured (read-only probes, 2026-10-17)
- **NWS vocabulary:** see §0.1. 111 names. All weather products relevant here are listed in E0.
- **SOC behaviour, recorder 10-10 06:33 → 10-17 14:33** (`sensor.envoy_482543015950_battery`, hourly samples, n=148 hour pairs):
  - Positive ΔSOC/h: p50 9, p90 25, p95 26, max 30 pp/h. All the top climbs are 11:00-14:00, so they are **solar** charge. There is no grid charge in the window: the pre-charge option is off and arbitrage did not grid-charge overnight. **The grid charge rate is still unmeasured.** The parent plan's ~10 kW (~25 pp/h on 40 kWh) is an estimate, and the hardware ceiling is `BATTERY_MAX_CHARGE_KW` 30.72 kW (~77 pp/h).
  - SOC by local hour, median: 00-10 h ≈ 7-10 %, 13 h 52 %, 15 h 91 %, 16-18 h 94-100 %, 19 h 76 %, 20 h 51 %, 21 h 35 %, 22 h 10 %.
  - Discharge through the shoulder top-rate block 17-21 is about 60 pp in 4 h (≈ 15-20 pp/h).
- **TOU (live `tou_rates.json`, PEC 2026):** winter top rate (`mid_peak`) is 05-09 and 17-21, and the rest is bottom rate. Shoulder top rate is 17-21. Summer peak is 16-20.

---

## 2. Falsifiable invariants (Stage E adds INV-7 and INV-8; INV-1 to INV-6 unchanged)

> **INV-7 (selection chooses WHETHER, never HOW).** For every legal stored value of the two selection options, including empty, everything, and products not in the internal table:
> (a) a `polygon_local` product never contributes a hold or a buy unless `INCLEMENT_POINT_FEED_POLYGON_EXACT` is True, and never buys outside `[start, min(end, start + INCLEMENT_POLYGON_TOPUP_MAX_MIN)]`;
> (b) a zone (non-polygon) product never causes a charge_from_grid turn_on unless `forecast_confirms` is True **on the same record** (`_zone_buy_confirmed`);
> (c) a product with no forecast family never buys. A product not in the internal table never exceeds `partial_hold` (it is treated as `watch`, not polygon-local, not eligible, and forecast-corroboration can't lift it because it has no family). Condition corroboration also can't lift it (E1.3 cap);
> (d) the effective buy set ⊆ the effective hold set;
> (e) **(operator 2026-10-17: "We keep your code list for me right? Not undone.")** `INCLEMENT_PRODUCT_TABLE` stays the authoritative internal default; the selection is an override layer on top and never a replacement. With zero operator overrides, every classification, hold and buy decision is byte-identical to v5.103.69. The proof is a golden over the full product table × {active, prepare, polygon in/out of cap, verified/unverified locality} × {option on/off} × {forecast confirmed/unconfirmed/None}, captured on the v5.103.69 tag before any Stage E code. The one allowed diff is the explicit E0 expected-diff list (Freeze Warning / Freeze Watch rows), and only if OQ-1 is approved. Any other diff stops the build (`test_zero_override_golden_identical_to_v5_103_69`).
> **Falsifiers:** a CFG off→on whose reason names a product not in the effective buy set; a zone-product buy with `inclement_buy_forecast.confirmed` false; an operator-added unlisted product at `full_hold`; a polygon hold while `POLYGON_EXACT` is False; an override-free golden that differs from the E0 table golden.
> **Legal-config repro (why the cap is needed):** the operator adds `Flood Watch` to the hold list (legal: it is in the vocabulary). An uncapped watch reaching `condition_stormy` (`pouring` is in `_STORM_CONDITIONS`) would be lifted to `full_hold` at any TOU. With the cap it stays `partial_hold`.

> **INV-8 (pre-onset floor only when it counts).** For a prepare alert with start `s`: the D-B6 floor is registered on a tick iff `s − INCLEMENT_PREONSET_FLOOR_LEAD_H ≤ now < s` **or** that alert's pre-charge latch is `engaged` or `reached`. A D-B6 buy is only ever evaluated inside `now < s ≤ now + INCLEMENT_PREONSET_LEAD_H` (the buy horizon, unchanged). Active-hold behaviour (`s ≤ now ≤ end`) is untouched.
> **Falsifiers:** a `reserve_write` row with non-null `tick_preonset_floor` while `s − now > floor_lead` and no latch for that alert; floor lead 0 with a floor registered and no latch; any change to a `full_hold`/`partial_hold` decision inside an alert window.
> **Repro:** WSW, Onset 21:00 winter, Sent 06:00, option False. Today (lead 12) the floor is 80 from 09:00, so the 09:00-17:00 bottom-rate hours hold the battery to no purpose. After E2 (floor lead 4) the floor is 80 from 17:00, covering exactly the 17-21 top-rate block, which is the only window where discharge was going to happen.

---

## 3. Producer and consumer checks

| Value | Producer | Consumers |
|---|---|---|
| Effective product row (E1) | `match_product` → internal row → `_apply_selection(row, event, overrides)` → effective `(class, polygon_local, eligible)`. Depends on options, read per tick, and the internal table. For unknown products: the synthetic row `(None, event, "watch", False, False)` + `unlisted=True`. | `build_record` (trust), `_effective_tier` (trust), `_precharge_flags` (trust), `_zone_buy_confirmed` via `rec.eligible` (trust), `inclement_selection` attr (display), ledger `nws_alert.ura_class` (audit; it now records the effective class). |
| Overrides | Options flow submit: `effective − defaults` and `defaults − effective` per level. | `_inclement_config()` per tick, then the classifier. |
| Prepare floor timing (E2) | Classifier prepare split (buy horizon, 12 h) plus a new floor gate in fusion `_apply_prepare` (`inclement.py:935`): floor iff in floor lead or latch engaged/reached. | `_tick_reserve_floor` registration (trust), DP drain stamp (trust), `inclement_preonset` attr (display; gains `floor_from`). |
| SOC/charge-rate physics | Recorder (§1d). Solar rate measured; grid rate not. | Sizing of the floor-lead default only. No runtime consumer. |

The dependency health that matters: the forecast (Stage C) is live, but its precip thresholds are not fitted (parent §16), so E1's "buy only with a family" rule leans on unfitted thresholds. That is acceptable because buys stay off until the operator turns the option on.

---

## 4. Site enumeration

- **Classification entry points that see a product row:** `match_product` (`inclement.py:277`), its two callers `classify` (`:495`) and `build_record` (`:326`), and `_effective_tier` (`:313`). The overlay must apply at `match_product`'s return so both callers see it. Applying it in `classify` alone would miss `build_record`, which is used by the D-B3 memory and the ledger: that is Bug Class #53. Builder: AST-check that no other function iterates `INCLEMENT_PRODUCT_TABLE` (today only `:295`).
- **Eligibility consumers:** `_precharge_flags`, `polygon_topup_records`, `_zone_buy_confirmed` (`:918`), and the three buy expressions (`:989`, `:1020`, `:1068`, `:1140`). All of them read `rec.eligible`, so none changes if the record carries the effective value. Reviewer D re-greps `precharge_eligible|\.eligible` over `inclement.py` and `energy_battery.py`.
- **Forecast-family readers:** `forecast_family` (`:1287`), `_forecast_confirmed_ids` (`energy_battery.py:2909`). E0 adds rows. The unknown-product rule needs no code because family None already yields False (`:1320-1321`).
- **Condition corroboration lift (the INV-7(c) cap site):** the watch corroboration expression in `InclementFusion.decide` (`corroborated = condition OR forecast`). Add `and not rec_unlisted` for condition corroboration only. Builder locates it by symbol.
- **Prepare floor:** the classifier split (`inclement.py:504-512`) stays the buy horizon. The floor gate goes in `_apply_prepare` (`:935`). The registration site in `determine_mode` stays unchanged and reads `decision.preonset_floor`.

---

## 5. Deliverables

### E0: NWS vocabulary re-sync (table rows; ships with E1)

Rows added to `INCLEMENT_PRODUCT_TABLE` (rung 1) and to `INCLEMENT_FORECAST_FAMILY`:

| Product | Class | Eligible | Family | Why |
|---|---|---|---|---|
| Freeze Warning (`FZW`) | **watch** (was notice) | yes (buy only when the forecast confirms ≤ 28 °F) | freeze | It carries the freeze hazard now that Hard Freeze is gone. Watch class keeps an ordinary 32 °F night at partial hold. Forecast ≤ `FORECAST_FREEZE_CONFIRM_F` (28, the old hard-freeze line) corroborates it to full hold and permits a buy. |
| Freeze Watch (`FZA`) | **watch** (was notice) | yes (same rule) | freeze | Precursor of the above. |
| Cold Weather Advisory | notice (unchanged) | no | freeze (display/corroboration only) | The successor of Wind Chill Advisory. It stays notice. |
| Hard Freeze Warning/Watch, Wind Chill Warning/Watch/Advisory | unchanged rows | unchanged | unchanged | KEEP+DOCUMENT. They are harmless while the NWS doesn't issue them, and they still match old CAP replays and other offices if any reissue them. |

Marginal benefit: this is the largest real-risk item in Stage E, at five table cells. The cost of Freeze Warning becoming watch-class is a partial hold, at most `max(reserve_soc, partial_floor)` = 50 live, on frost nights at bottom rate (watch partial holds apply off-peak), and a full hold only on ≤ 28 °F forecast nights. Operator question OQ-1.

**Acceptance**
- **Verify:** `Freeze Warning`, outlook min 34 °F → `partial_hold`, no buy with the option True. Outlook min 25 °F → `full_hold`, buy eligible at bottom rate with SOC < 90.
- **Verify:** `Cold Weather Advisory` → notice, `allow_discharge`.
- **Test:** `test_vocab_snapshot_covers_table` (every table name, except the KEEP+DOCUMENT retired list, is in `NWS_WEATHER_EVENT_NAMES`; the retired list is pinned so a vocabulary refresh fails loudly), `test_freeze_warning_watch_class_forecast_lift`, `test_freeze_warning_buy_needs_28f`.
- **Live:** `inclement_gated_out_events` and the `nws_alert` rows' `ura_class` show `Freeze Warning` = `watch` on the first one received (event-gated, disposes on first FZW). Discriminates: `notice` there means the row edit did not reach `match_product`.

### E1: operator alert selection over the internal table (EC-STORM-PRODUCT-SELECTION-EXTERNAL-1)

**E1.1 Shape: two multi-selects, buy ⊆ hold enforced.** This is coordinator point 1. I picked two fields over one level per product. A per-product dropdown means ~30 rows of four-way selects, which fails "quick conceptual clarity". Two lists read in one glance:
- **"Alerts that hold the battery"** (multi-select). Default = the table's warn and watch rows. A product not selected becomes `notice` (shown and logged, never a hold).
- **"Of those, alerts that may buy grid power"** (multi-select). Default = the table's eligible rows. Helper text: "Only used when 'Top up before storms' is on. Zone-wide alerts still need the local forecast to agree; storm warnings must cover the house."
- **Validation errors** (field-scoped, the existing EC convention): a buy item not in the hold list (`buy_not_in_hold`); a buy item with no forecast family that is also not a polygon table row (`buy_needs_forecast`, coordinator point 3).
- **Choices** come from `NWS_WEATHER_EVENT_NAMES`, a rung-1 snapshot of the weather products in `api.weather.gov/alerts/types` (the curated list excludes 911/civil/tsunami/marine/administrative). There is **no free text** (coordinator point 3): the legacy list failed by silently non-matching substrings.
- "Off" vs "notice": the selection can't gate a product fully out. Notice only shows and logs, and costs nothing. Gating out stays an internal-table property (unlisted vocabulary that is never selected stays gated out, as today). One less axis to explain.

**E1.2 What the selection may and may not change (coordinator point 2; INV-7).** The operator chooses whether a product holds and whether it may buy. Class semantics (warn vs watch for table rows), `polygon_local`, the polygon cap and verified-local rule, forecast confirmation, the storm-charge threshold and the precharge option stay internal. Removing a product from **hold** turns it to notice (narrowing, always safe). Adding a table product that is notice by default (e.g. Wind Advisory) to hold gives it **watch** class (partial hold unless corroborated). Narrowing is allowed and widening is bounded:
- Widening **buy** to an ineligible table row is allowed only if the row has a forecast family or is polygon (e.g. Tornado Watch: buys only when the convective forecast confirms, which needs a storm condition and ≥ 70 % PoP).
- Hurricane/Tropical rows have the convective family, so they can be widened.

**E1.3 Unknown products (coordinator point 3).** A vocabulary product not in the table and added to hold (e.g. `Flood Watch`, `Red Flag Warning`) gets the synthetic row `watch`, `polygon_local=False`, `eligible=False`, `unlisted=True`. It has no family, so forecast corroboration can't lift it and a buy is refused at validation. The fusion caps `unlisted` records at `partial_hold` by ignoring **condition** corroboration for them (the INV-7 repro: `pouring` is a storm condition, so a Flood Watch would otherwise reach full hold). Cost: one conjunct.

**E1.4 Storage: overrides, not a snapshot (coordinator point 4).** Options keys (NEW, rung 2): `inclement_hold_added`, `inclement_hold_removed`, `inclement_buy_added`, `inclement_buy_removed`. Each is a list of exact event names. The submit handler stores `selected − default` and `default − selected`, and the form renders the effective lists. A later evidence-driven table change (like E0) therefore reaches every install that didn't touch the product. All four keys go in `OPTIONS_RELOAD_SUPPRESS_KEYS` and are read per tick by `_inclement_config()` (coordinator point 6), so a change takes effect on the next tick with no CM reload. A stored name that has left the vocabulary is ignored with one debug log and kept (no options write).
**Migration:** the live `inclement_power_threat_events` equals the v5.5.0 default (parent §1a, verified 2026-10-16), so nothing is translated and nothing is written. A customized legacy list keeps raising the existing `inclement_legacy_threat_list_retired` repair (`energy.py:8335`). Substrings are not auto-mapped to products, because that was the defect being removed.

**E1.5 Show consequences (coordinator point 5).** Attr `inclement_selection` on the strategy sensor (copied to `sensor.ura_inclement_state`). For each active or prepare alert: `{event, level: "hold"|"hold+buy"|"notice", source: "table"|"override"|"unlisted", buy_gate: "forecast_confirmed"|"forecast_unconfirmed"|"polygon_in_cap"|"polygon_out_of_cap"|"not_selected"|"option_off"}`. Also `overrides: {hold_added, hold_removed, buy_added, buy_removed}`. Display only. "Just enough" observability (parent §14): one attr, no new sensor.

**E1.6 Other locations (coordinator point 7).** Help text: "Defaults come from storm and outage history at this house (Lakeway, TX). Other locations may need different choices." No per-region default sets. Parked with trigger: a second URA install with a non-Lakeway NWS zone.

**E1.7 Severity stays retired (coordinator point 8).** Class replaces it. No severity field returns.

**E1.8 Retire the dead legacy plumbing (supersession, three buckets).**

| Item | file:line | Bucket | Superseded by | Reason |
|---|---|---|---|---|
| Legacy read and `power_threat_events` / `warn_min_severity` keys in `_inclement_config` | `energy_battery.py:2608-2609, 2618-2619, 2647-2660` | **DELETE** | E1 overrides | Read and passed, then discarded (`inclement.py:453`). Misleads readers. |
| `AlertClassifier.__init__` legacy args | `inclement.py:447-453` | **DELETE** (update callers) | — | Accepted only for call-site compatibility. Callers change in the same commit. |
| config_flow imports + multiline parse | `config_flow.py:6030-6031, 6036-6037, 6164-6168` | **DELETE** | E1 fields | Fields left the form in D-B5. The parse runs on a key that is never submitted. |
| strings/translations for the two fields | `strings.json:983-984, 1068-1069`; `translations/en.json` same | **DELETE** | E1 strings | Dead UI text. |
| `CONF_INCLEMENT_POWER_THREAT_EVENTS`, `DEFAULT_INCLEMENT_POWER_THREAT_EVENTS` | `energy_const.py:615, 634-643` | **KEEP+DOCUMENT** | — | The repair check reads both. |
| `CONF_INCLEMENT_WARN_MIN_SEVERITY`, `DEFAULT_…`, `INCLEMENT_WARN_MIN_SEVERITY_OPTIONS`, `INCLEMENT_SEVERITY_ORDER` | `energy_const.py:616, 644, 838-840` | **DELETE if 0 readers after the above** (builder greps), else KEEP+DOCUMENT | — | Severity is attrs-only now. `_severity_rank` may still use the order (attrs). |
| `_event_matches_threat` substring gate | `inclement.py` (parent §13) | **DELETE**, gated on the v5.103.69 README validation table being written | product table | Parent §13 DELETE candidate. Its condition (Stage B validated) closes with that table. |
| `_check_legacy_threat_list` | `energy.py:8335` | **KEEP** | — | Live repair path. |

**E1 Acceptance**
- **Verify (INV-7e, operator "not undone"):** zero overrides → the golden over the full table × case matrix in INV-7(e), captured on the **v5.103.69 tag** and committed before any Stage E code, is byte-identical except the E0 expected-diff rows. The table constant is not edited by E1 code; the AST test `test_product_table_not_mutated_by_selection` pins that the overlay returns new effective rows and never writes the constant.
- **Verify (narrow):** remove `Winter Storm Warning` from hold → WSW in window = notice, `allow_discharge`. Remove it from buy only → `full_hold`, no CFG with option True, SOC 50, off-peak, forecast confirmed.
- **Verify (widen buy):** add `Tornado Watch` to buy → buys only with a confirmed convective outlook (`lightning` + PoP 75). With PoP 60 or `pouring` only: no buy, hold unchanged.
- **Verify (INV-7a):** a stored override adding SVW to buy has no effect when `POLYGON_EXACT` is False (monkeypatched constant). The SVW stays notice.
- **Verify (INV-7c):** `Flood Watch` added to hold, providers `pouring`, top rate → `partial_hold`, never `full_hold`. Control: `Winter Storm Watch` with the same condition gives `full_hold` (same fixture).
- **Verify (validation):** buy ⊄ hold → `buy_not_in_hold`. Buy `Flood Watch` → `buy_needs_forecast`. Both errors are field-scoped and nothing is persisted.
- **Verify (storage):** submitting the defaults unchanged stores four empty lists. An E0-style table edit after storing changes the effective list for untouched products.
- **Verify (no reload):** changing a selection triggers `apply_in_place`, not a CM reload (the reload-suppress test pattern).
- **Test:** `test_zero_override_golden_identical_to_v5_103_69`, `test_product_table_not_mutated_by_selection`, `test_selection_remove_hold_is_notice`, `test_selection_remove_buy_keeps_hold`, `test_selection_widen_buy_needs_forecast`, `test_selection_cannot_override_polygon_locality`, `test_unlisted_product_capped_partial_hold` (+ control), `test_selection_validation_buy_subset_of_hold`, `test_selection_validation_buy_needs_family`, `test_selection_stores_deltas_only`, `test_selection_keys_in_options_reload_suppress_keys`, `test_selection_reads_live_options_per_tick`, `test_selection_overlay_applies_in_build_record` (memory/ledger path, Bug Class #53 anchor), `test_inclement_selection_attr_shape`, `test_legacy_plumbing_removed` (AST: no reader of the two keys outside the repair check).
- **Mutation drills (Review C):** apply the overlay in `classify` only (the `build_record` test goes RED); drop the buy ⊆ hold validation; drop the unlisted condition-corroboration cap; let an override set `polygon_local=False`; store the full effective list instead of deltas; read the module default instead of options.
- **Live:** (a) options flow shows the two lists with today's defaults, and `.storage/core.config_entries` holds four empty override lists after one save (or none if never saved). A full snapshot there = storage bug. (b) `inclement_selection` reads `[]`, `overrides` all empty, with no alert. (c) 0 URA errors mentioning `selection` / `match_product` after restart. (d) no CM reload in the log when the operator saves a changed selection (discriminates against a missing reload-suppress key).

### E2: pre-onset floor only when it counts (EC-STORM-PREONSET-TIMING-1)

**Marginal-benefit decomposition (do this first; the recommendation follows from it).**
- *Operator's complaint:* "holding for 12 hours is wasteful." The floor, not the hold, is what spans 12 h before Onset.
- *Simplest version:* a short floor lead before alert Onset. In winter the top-rate blocks are 4 h (05-09, 17-21), and an Onset falls at or after one of them. A 4 h lead covers the one top-rate block before Onset, which is the only window where the battery was going to discharge (§1d: ~60 pp across 17-21). The other 8 h of today's lead fall in bottom-rate hours, where the battery barely discharges, so holding then protects almost nothing. **This captures the whole complaint.**
- *Forecast intersection margin:* by §0.3, `T ≥ Onset`, and the hold starts at Onset. Intersecting can only remove some of the ≤4 h of floor directly before a hold that starts anyway, on alerts whose forecast hazard hour is after Onset. The ingredients are a per-hour predicate over provider rows, a new time anchor that moves as forecasts refresh (state × time seam, the bug family the marginal-benefit rule was coined for), and a fallback rule. **Margin ≈ 0 for the pre-onset floor. Recommend not building it here.**
- *Where the operator's idea does have margin:* deferring the **in-window hold** from NWS Onset to `T − L` when NWS Onset is hours ahead of the forecast hazard. That is a demotion of an active warn (principle 1, INV-3) and needs evidence. Parked as **E2b** with trigger: after one winter, `inclement_forecast` + `nws_alert` rows show ≥ 3 HOLD events where the first forecast-confirming hour came ≥ 4 h after Onset. E2b would add `WeatherProviderManager.first_confirming_hour(family, start, end)` over `_hourly` rows using a **per-hour** predicate (cold and wet in the same hour), with fallback `T = start`. Operator question OQ-3.

**Recommended build (E2):**
1. NEW `INCLEMENT_PREONSET_FLOOR_LEAD_H` (rung 1, default **4**): the floor is registered only when `start − 4 h ≤ now < start`.
2. `INCLEMENT_PREONSET_LEAD_H` (12) is **re-scoped to the buy horizon**: the classifier's prepare split is unchanged, so a bottom-rate pre-charge can still start up to 12 h ahead, e.g. a 21:00 winter Onset with the 09-17 bottom-rate window.
3. **Floor-follows-buy:** if the pre-charge latch for that alert is `engaged` or `reached`, the floor is registered from that tick to Onset. Otherwise bought energy would self-consume away before the floor window, and the buy would be wasted. The buy's own `_result` already emits `reserve_level=preonset_floor` while charging, and this extends that past the charge.
4. Physics check for 4 h: from the overnight SOC (~10 %, §1d) to the 80 floor is 70 pp. Solar delivers up to 25 pp/h (p90), so ~3 h on a clear afternoon. Grid is unmeasured (~25 pp/h at the 10 kW estimate, also ~3 h). So 4 h ≥ the charge time on either source, with an hour of margin. With the option off (live), the floor only stops discharge, and 4 h = exactly one top-rate block. Both arguments give 4.

Interactions: the forecast-confirm latch is unchanged (it decides the watch floor level and buy confirmation, not timing). `INCLEMENT_PREONSET_LEAD_H = 0` still kills D-B6 entirely. Floor lead 0 means floor only via the buy latch. Precharge is still OFF live, so live E2 is a floor-timing change only.

**Acceptance**
- **Verify (INV-8 repro):** WSW Onset 21:00 (December), option False: no floor at 16:59, floor 80 at 17:00, hold at 21:00. Same alert, lead constants at the old values (12/12) → floor from 09:00 (regression control, parametrized).
- **Verify (floor-follows-buy):** option True, Onset 21:00, SOC 30 at 10:00 bottom rate, forecast confirmed → buy engages at 10:00, floor registered 10:00-21:00, never below 80 after `reached`. Control: same with option False → no floor before 17:00.
- **Verify:** an active hold inside its window is unchanged (hour-sweep golden of in-window decisions identical).
- **Verify:** floor lead 0 + option False → no pre-onset floor at any hour. Buy lead 0 → D-B6 off.
- **Test:** `test_preonset_floor_lead_window`, `test_preonset_floor_follows_engaged_latch`, `test_preonset_floor_lead_zero_floor_only_with_latch`, `test_preonset_in_window_hold_unchanged_golden`, `test_preonset_buy_horizon_unchanged`; update `test_preonset_floor_none_outside_lead` to the new semantics.
- **Mutation:** key the floor on the buy horizon (repro goes RED); drop floor-follows-buy (the buy fixture shows the floor missing 10:00-17:00 → RED).
- **Live:** with no alert, `inclement_preonset` is `null`. When a future HOLD alert sits 4-12 h ahead, `inclement_preonset` reads `{"floor_from": "<start−4h>", …}` and `reserve_write` rows carry no `tick_preonset_floor` before `floor_from`. Discriminates: a non-null `tick_preonset_floor` earlier than `floor_from` with no latch = gate missing. Event-gated, disposes on the first prepare alert.

### E3: hygiene carried in-cycle (tiny, same review)
- **B-LOW-5 (parent §16):** wrap `get_forecasts` in `asyncio.timeout(FORECAST_FETCH_TIMEOUT_S)` (NEW rung 1, 20 s) so a hung provider can't hold `_refresh_lock`. Test: `test_hourly_fetch_timeout_releases_lock`. ~5 lines. Fixed in-cycle per the fix-LOWs rule.
- **Parent plan §13/§16 write-back:** mark `_event_matches_threat` deleted, legacy plumbing retired, Stage E link.

---

## 6. Knobs

| Knob | Rung | Default | Why / kill |
|---|---|---|---|
| `inclement_hold_added/_removed`, `inclement_buy_added/_removed` (options) | 2 | empty | Operator chooses which alerts hold or buy. Empty = table defaults. Kill for buys = `inclement_grid_precharge_on_hold` False (unchanged). |
| `NWS_WEATHER_EVENT_NAMES` | 1 | snapshot of `api.weather.gov/alerts/types` 2026-10-17 (weather subset) | The selectable vocabulary. Refresh by reviewed code change; the E0 test fails if a table name falls out. |
| `INCLEMENT_PRODUCT_TABLE` rows (E0) | 1 | §E0 | Evidence-set; review required. |
| `INCLEMENT_PREONSET_FLOOR_LEAD_H` | 1 | 4 | Hours before Onset the pre-onset floor applies. Sized to one winter top-rate block and to the ~3 h charge time (§1d). 0 = floor only while a pre-onset buy is engaged or reached. Rung 1 because it prices peak arbitrage against readiness. |
| `INCLEMENT_PREONSET_LEAD_H` | 1 | 12 (re-scoped: buy horizon) | How early a bottom-rate pre-charge may start. 0 = D-B6 off (both legs). |
| `FORECAST_FETCH_TIMEOUT_S` | 1 | 20 | Hourly fetch bound. |

No rung-3 additions. The options flow gains two fields and drops none (the two legacy fields left in D-B5).

---

## 7. Non-goals
1. No change to class/tier semantics, locality, the polygon cap, forecast thresholds, the storm threshold or the precharge option.
2. No per-region default tables (parked, trigger: a second install).
3. No forecast-timed hold (E2b, parked with trigger, OQ-3).
4. No runtime fetch of the NWS vocabulary.
5. No translation of customized legacy substring lists (repair issue stays).
6. No arc steps 9-11, Stage D or EC-OBS-DP-EVSE-1 (each has its own cycle, §E3 inventory).
7. No change to the arbitrage engine, the governor, the overlay or write-verify.

## 8. Tier and review
**Tier 3**: one cycle, E0+E1+E2+E3, `ura-super-builder`. Split option: E2 alone as "E-b" if E1's options-flow surface makes review heavy, since E2 touches only `inclement.py` fusion and constants. Plan reviews: (1) completeness (re-enumerate every `INCLEMENT_PRODUCT_TABLE` / `eligible` / prepare-floor site); (2) build-prediction. Build reviews A/B/C/D as parent §9. D's target is INV-7 under every legal selection, including the vocabulary extremes (empty hold list, everything selected, every unknown product), plus INV-8. Golden captured after E0, before E1/E2 code. Operator checkpoint before deploy. Deploy risk **MEDIUM**: no buy is live, the floor gets shorter, and Freeze Warning starts holding.

---

## 9. E3: arc / spawned / dropped inventory (recommendations, not a menu)

| # | Item | Source | Disposition | Why (one line) |
|---|---|---|---|---|
| 1 | **NWS vocabulary drift** (Hard Freeze/Wind Chill gone, Freeze Warning notice) | found here §0.1 | **Stage E (E0)** | A live freeze-hold gap; cheapest high-value fix in the arc. |
| 2 | Operator alert selection | EC-STORM-PRODUCT-SELECTION-EXTERNAL-1 | **Stage E (E1)** | Operator ask. |
| 3 | Pre-onset timing | EC-STORM-PREONSET-TIMING-1 | **Stage E (E2)**, forecast-timed hold **parked (E2b)** | Shorter lead captures the complaint; the intersection has ~0 margin for the floor. |
| 4 | Legacy threat-list dead plumbing | residual_2026_10_17_legacy_threat_list | **Stage E (E1.8)** | Same files as E1. |
| 5 | `_event_matches_threat` DELETE | parent §13 | **Stage E**, after the v5.103.69 Validated table | Its gate closes with that table. |
| 6 | B-LOW-5 `get_forecasts` timeout under lock | parent §16 | **Stage E (E3)** | 5 lines; prevents a stuck refresh lock. |
| 7 | B-LOW-4 Storm Guard negative cache | parent §16 | **Drop** | Registry re-resolve only runs while the state is missing; cost is a lookup. |
| 8 | Arc step 8: obs-mode bypass | EC-OBSERVATION-MODE-RESERVE-BYPASS-1 (shipped_organic v5.103.69) | **Dispose now** (one query: 0 `reserve_write` rows while observation mode on since restart) | Shipped; organic lane is not a parking lot. |
| 9 | §12 limit 14 + B-LOW-1 (evaluate-path pre-onset latch not rolled back in observation mode) | parent §12 | **Verify in the step-8 disposition**; if the v5.103.69 gate covers the evaluate path's `determine_mode`, close; else card it under step 8 as a residual | Was explicitly deferred to step 8. |
| 10 | Arc steps 9 + 10 (TOU-transition double consume; evaluate-path ledger gap) | EC-TOU-TRANSITION-DOUBLE-CONSUME-1, EC-EVALUATE-PATH-LEDGER-GAP-1 | **Separate joint Tier-2 cycle, next after Stage E**; measure first (how often the manager wins) | Arc rule: same path, one joint plan. |
| 11 | Arc step 11: self-heal re-sends (frozen local reading) | EC-SELFHEAL-UNEXPLAINED-RESENDS-1 (waiting_operator) | **Separate cycle**, unblock on the operator answer | CRITICAL pages 1-5/day; own root cause, not storm logic. |
| 12 | Stage D: 9 H period-name sites + pin | parent §6/§8, Q8 "do it" | **Separate Tier-2 cycle** after steps 9/10 | Byte-identical portability work; independent of Stage E. |
| 13 | EV-charger writes in observation mode | EC-OBS-DP-EVSE-1 | **Separate Tier-2 cycle**, pair with step 8 residuals | Same observation-mode theme, different writers. |
| 14 | `BLIND_RESPECT_MANUAL_LOWER` two must-fix defects | parent §7 | **Park, trigger: any proposal to set it True** | The constant is False, so the defects are unreachable. |
| 15 | HOLD-CURRENT doesn't refresh `_desired_stamped_at` | README v5.103.68 | **Park, trigger: a redispatch gap traced to HOLD-CURRENT** | Re-pass proved it can only suppress a write. |
| 16 | Sighted SOC-unknown full hold uses slider 60, not 100 | README v5.103.68 / parent §6 D-A3 | **Park, trigger: a ledger outage with SOC unknown at hold start** | Rare state; slider is operator-tunable. |
| 17 | Review C equivalent mutant B19 (`cloud_withhold_exempt` at pre-onset) | ec_stage_bc_review_C | **Drop** | Equivalent mutant, unreachable on the cloud tier. |
| 18 | Outage ledger Live (e): does the local witness flip on islanding | parent §12 limit 17, Stage L | **Event-gated disposition on the first real outage** (one query) | Can't be produced; disposes on first event. |
| 19 | Forecast thresholds (50 % / 1.0 mm / 70 %) unfitted | parent §16, README v5.103.69 | **Park, trigger: 2027-03-31 end of first winter with Stage C attrs + `nws_alert` rows; one fit probe then** | No history exists to fit from; buys are off. |
| 20 | Grid pre-charge option turn-on | parent §6 Live (e), ruled "after Stage C" | **Operator action (OQ-4)**, recommend after Stage E ships | E0/E1 change what can buy; turn on once against the final table. |
| 21 | Q7 re-confirm (unverified polygon → notice) | parent §14 | **Operator item (OQ-5)**, default stands | Only bites if `?point=` proves inexact. |
| 22 | §12 limit 15 (D-B3 memory lost on restart) | parent §10 | **Park (existing trigger)** | Unchanged. |
| 23 | §12 limits 25/26 (forecast latch and grid-buy NM dedupe RAM-only) | parent §12 | **Park, trigger: a duplicated buy NM or post-restart unconfirm observed** | Cosmetic / rare. |
| 24 | Polygon per-storm budget | parent D-B2a | **Park (existing trigger: ≥3 covering IDs in one storm)** | Measured ≤100 min per storm. |
| 25 | Storm Guard switched on while HA down not NM'd | parent D-B7 | **Park (operator ruled log-only)** | Ruled. |
| 26 | NM consuming `nws_alert` rows for HOLD-alert notices | parent §13 | **Park, trigger: operator asks to be told about holds** | Grid-buy NM already covers the money action. |
| 27 | Pre-onset buy outside bottom rate; convective/tropical eligibility; WIY promotion; ledger table | parent §10 parked list | **Park (existing triggers)** | Unchanged. |
| 28 | Full-hold degraded path `envoy_available=True` | parent §16 A-HIGH-1 note | **Done** (B-LOW-2, 95ecb7430) | Closed in v5.103.69. |
| 29 | Arc doc status rows stale (steps 2-7 still read "waiting") | ARC doc | **Fix in the Stage E ship commit** | Doc-only. |
| 30 | v5.103.69 README Validated table | CLAUDE.md write-back rule | **Do before Stage E build** | It gates item 5 and closes the cycle. |
| 31 | EC-ENPHASE-CONNECTIVITY-RESILIENCE-1 | outside arc | **Unchanged** (own card) | Explicitly outside. |

---

## 10. Open operator questions (each with the recommended default)

| # | Question | Recommended default |
|---|---|---|
| OQ-1 | Freeze Warning / Freeze Watch become **watch** (partial hold on frost nights, full hold and buy only when the forecast shows ≤ 28 °F)? | **Yes.** The alternative leaves hard freezes unhedged now that the NWS no longer issues Hard Freeze. |
| OQ-2 | Selection UI = two lists ("Alerts that hold the battery", "Of those, alerts that may buy grid power") with buy ⊆ hold enforced, choices from the NWS name list, no free text, unknown products capped at partial hold? | **Yes.** |
| OQ-3 | Pre-onset floor = 4 h before NWS Onset; forecast-timed **hold** deferral parked until a winter of data shows Onset leading the forecast hazard by ≥ 4 h in ≥ 3 events? | **Yes.** The intersection you described can't start the floor earlier, and moving the in-window hold later is a demotion that needs evidence first. |
| OQ-4 | Turn `inclement_grid_precharge_on_hold` on after Stage E ships, not before? | **After Stage E**, against the final table and selection. |
| OQ-5 | Q7 (unverified polygon → notice) stands? | **Stands.** |
| OQ-6 | Grid charge rate is unmeasured. Accept 4 h on the solar evidence plus the one-block argument, or run one supervised bottom-rate grid charge to measure it? | **Accept 4 h.** The first real pre-charge records the rate in `reserve_write` and SOC history. |

## 11. Changelog
| Rev | Date | Change |
|---|---|---|
| 1 | 2026-10-17 | Initial Stage E. Coordinator E1 critique (8 points) folded in. Measured: NWS vocabulary (four HOLD products retired; E0), hourly outlook shape (per-hour rows internal, aggregate public), SOC/TOU physics for the 4 h lead. |
