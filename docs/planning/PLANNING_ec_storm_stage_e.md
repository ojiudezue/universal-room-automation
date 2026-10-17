# PLANNING: EC storm Stage E (operator alert selection, pre-onset timing, arc closeout inventory)

**Parent plan:** `PLANNING_ec_storm_and_blind_decisions.md` Rev 3.5 (Stages L, A, B, C shipped: v5.103.67, v5.103.68, v5.103.69). Stage E follows the parent's decision model, invariants INV-1 to INV-6, knob ladder and review protocol. Where this doc says nothing, the parent governs. Where Stage E changes a parent invariant (INV-6(iii) bottom-rate gate, §E2), the parent is amended in the Stage E ship commit.
**Arc:** `ARC_energy_coordinator_resilience.md`.
**Cards:** EC-STORM-PRODUCT-SELECTION-EXTERNAL-1 (E1), EC-STORM-PREONSET-TIMING-1 (E2, E2-P), parent EC-INCLEMENT-HARDENING-1 (E0, legacy residual, §9 inventory). Batch `ec-storm-stage-e`.
**Tier:** 3. Grid-buy timing, reserve-floor timing and alert classification feed every storm hold.
**Status:** **Rev 3.1** (2026-10-17): one normative text; superseded Rev 2 wording removed (history only in §12). **Rev 3**: both Rev 2 re-checks folded (§12 "Rev 3 re-check fix-up"). Earlier: **Rev 2** (2026-10-17). This revision folds in two Tier-3 plan reviews (`docs/reviews/code-review/plan_review_ec_storm_stage_e_1_completeness.md`, 1C/3H/7M/6L; `…_2_build_prediction.md`, 2C/5H/6M/3L), mapped per finding in §12. It also folds in the operator's E2 ruling of 2026-10-17 (buy in the cheapest hours just before the event; the floor no earlier than needed). Rev 1 (6dd862d15) folded the coordinator's 8-point E1 critique and the "not undone" ruling. Not built.

**Operator input (2026-10-17, verbatim):**
- "I think an externalization is interesting. The data backed version is good but annotate could Extend it. It also helps with diff locations who which will have different data and the operator can add or remove things that can hold, or buy. It can be simple list externally and more complicated internally ie we will in the internal table with known good things/code but the user selection stays simple."
- "We didn't talk about good hold onset time. Holding for 12 hours is wasteful. We should hold when it counts ie 3-4 hours to expected event time intersect forecast confirmed time. Vs alert time."
- "These can be follow ups but like immediately plus whatever else is in the arc or cards we spawned from it or things we dropped."
- "We keep your code list for me right? Not undone."
- **E2 ruling:** "There are 2 downsides to an early hold. We use grid power which may or may not be cheap (well above at dollar value is technically not cheap imo). Can we make the grid buy happen in any cheapest window just before the event and only during a higher rate window before the event if unavoidable. I believe we have prior art in how to check for rate periods so don't invent unnecessary code. So 3-4 hours of the cheapest period before the event. Also I think we know our battery can charge from grid in 1-2 hours."
- (Doctrine, unchanged) "get an alert, check the applicability … check the local weather for the next x hours that alert applies, and then make an energy decision." "I don't want grid buys on mere rain."

---

## 0. Read this first: findings that change the asks

1. **The NWS no longer issues four of our HOLD products (verified 2026-10-17).** `GET https://api.weather.gov/alerts/types` returns 111 event names. None of them is `Hard Freeze Warning/Watch` or `Wind Chill Warning/Watch/Advisory`. The list does have `Freeze Warning`, `Freeze Watch`, `Extreme Cold Warning/Watch` and `Cold Weather Advisory`. I believe this is the 2024-25 NWS hazard simplification, but that date and mapping come from memory and are unverified; the current vocabulary is verified.

   In our table, `Freeze Warning` is `notice` (`energy_const.py:721`) and `Freeze Watch` has **no row**, so it is gated out. A hard freeze that arrives without an Extreme Cold product therefore gets no hold and no buy. Freezes are the one hazard the operator has seen take power down. → **E0**.

2. **The hourly outlook stores per-hour rows but only exposes an aggregate.** The per-hour rows are `WeatherProviderManager._hourly[eid]["rows"] = {hour_utc: {temp_f, apparent_f, pop, mm, gust, condition}}` (`weather_manager.py:882`, built `:897-944`). `hourly_outlook()` (`:946-1018`) collapses them into one `Outlook` (`inclement.py:1263-1284`), and that aggregate is what `forecast_confirms` reads. A forecast "event hour" would need a new per-hour read over rows already in RAM (no new fetch).

3. **Where the forecast intersection has margin (rewritten per Review 2).**
   - **For the pre-onset floor, the margin is about zero.** The floor lives in `[start − lead, start)`. The expected event time `T` is inside the alert window, so `T ≥ start`. Intersecting can only start the floor later, just ahead of a hold that starts at `start` anyway.
   - **Inside the alert window, the margin is real.** First, NWS Updates re-stamp Onset to the Update's Sent time once the hazard is "underway" (`AUDIT_ec_storm_stage0_probes.md:41,47`, Wind Advisory 10-16 10:26). Example: a WSW whose Onset is re-stamped from 21:00 to 13:00 makes D-B1 hold fully from 13:00, through the 17-21 top-rate block, even if the forecast's freezing-precip hour is 22:00. Second, watches are issued 15-37 h ahead (audit `:47`) with 24-48 h windows. Once corroborated, a watch full-holds the whole window. Deferring a **watch's** corroboration-driven full hold is the narrowing of a raise, not a warn demotion: an uncorroborated watch at top rate already allows discharge (`inclement.py:1121-1127`).
   - That margin is empirical, so this cycle **measures it before deciding it** (**E2-P**, a go/no-go probe). It is not parked indefinitely.

4. **The operator's E2 ruling moves the buy, not just the floor.** Today the D-B6 buy fires on any bottom-rate tick inside the 12 h horizon (`is_bottom_rate(now)`, INV-6(iii)). The operator wants three things: the buy in the cheapest hours **closest to the event**, higher-rate hours only when the charge cannot fit, and a floor that starts no earlier than needed. The prior art is `TOURateEngine.rate_rank`/`period_rank` (`energy_tou.py:491-533`, any datetime) and the arbitrage "charge in the last `lead` minutes before the next high-rate transition" pattern (`energy_battery.py:3558-3573 _is_charge_window_open`, `get_next_high_rate_transition` `energy_tou.py:699`). E2 reuses both and adds no new rate-period code (§E2.2).

---

## 1. Institutional context verified

### 1a. REUSE / EXTEND / BUILD per piece

| Piece | Prior art (file:line) | Verdict |
|---|---|---|
| Internal product table | `INCLEMENT_PRODUCT_TABLE` `energy_const.py:694-725` `(code, name, class, polygon_local, precharge_eligible)`; only iterator `match_product` `inclement.py:277-310` (loop `:295`); `_effective_tier` `:313-319` | **REUSE** as the authoritative default ("not undone"). E0 adds and edits rows. E1 overlays it and never mutates it. |
| `match_product` callers | `classify` `inclement.py:495`; `build_record` `:326` (via `update_alert_memory` `:346`/`:403` and `classify` `:502`); **`energy_outage_ledger.py:269-280`** (writes `nws_alert.ura_class`/`ura_tier`) | **EXTEND** all three through an explicit `selection` argument (§E1.3). |
| Forecast family | `INCLEMENT_FORECAST_FAMILY` `energy_const.py:815-835`; `forecast_family` `inclement.py:1287`; `FORECAST_APPARENT_TEMP_PRODUCTS` | **REUSE + rows** (E0). |
| Buy gates | `_zone_buy_confirmed` `inclement.py:918` (same-record eligible AND confirmed); polygon leg `_precharge_flags` / `polygon_topup_records` | **REUSE**; E1 feeds the effective `eligible` per record. |
| Watch corroboration | `_decide_hold` tier-level `corroborated = (not self._watch_requires_corroboration) or (condition_stormy and count>=1) or forecast_corroborates` (`inclement.py:1095-1105`) | **EXTEND**: one corroborable-record conjunct (§E1.4). |
| Options-read path | `_inclement_config()` per tick (`energy_battery.py:2600-2700`); `_NO_LIVE_ATTR_KEYS` (`__init__.py:7353`) **and** `OPTIONS_RELOAD_SUPPRESS_KEYS` (`:7506`), both required (`__init__.py:6927-6928`, `:6982-6984`) | **REUSE**, rung 2. |
| Legacy list | keys `energy_const.py:615-616`; defaults `:634-644`; built but **never passed** in `_inclement_config` (`energy_battery.py:2647-2660`; `AlertClassifier()` is constructed with no args at `:2749`); classifier `del`s them (`inclement.py:449-453`); config_flow `:6030-6031, 6036-6037, 6164-6168`; strings `strings.json:983-984, 1068-1069` + `translations/en.json`; repair `energy.py:8335`, text `strings.json:2321-2323` | Triage §E1.9. |
| NWS vocabulary | none (grep `alerts/types`: 0) | **NEW** rung-1 `NWS_WEATHER_EVENT_NAMES` (§E1.2). |
| Rate ranking | `period_rank` `energy_tou.py:491`, `rate_rank(now)` `:516`, `is_bottom_rate` `:530`, `get_current_period(dt)` `:459`; hour-walk precedent `peak_ahead_before_offpeak` `:628`; arbitrage window `_is_charge_window_open` `energy_battery.py:3558` | **REUSE.** E2 adds one ~20-line pure scheduler that calls `rate_rank(dt)` per hour (no tariff parsing, no period names). |
| Pre-onset fields and readers | `InclementDecision.preonset_floor`, read at 7 sites (§4.3) | **EXTEND**: split into target vs registered floor (§E2.4). |
| Prepare split, latch | classify `inclement.py:476-519`; `_apply_prepare` `:935-1012` (purge `:950-953`, advance `:974-980`, `pre` `:984-1005`); latch `_preonset_precharge_latch` | **EXTEND** (§E2). |
| Hourly rows | `_hourly` `weather_manager.py:882` | **REUSE** in E2-P (offline) and, only on GO, E2b. |
| Fetch timeouts | daily `_fetch_provider_forecast` `weather_manager.py:405-433` under `_refresh_lock` `:443`; hourly `:900-904` under `:866` | **EXTEND**: bound both (E3). |

### 1b. Greps run (develop @ 377a7e3ed)
- `INCLEMENT_PRODUCT_TABLE|INCLEMENT_FORECAST_FAMILY|FORECAST_APPARENT_TEMP_PRODUCTS|precharge_eligible`: `inclement.py:143,162,167,295,340,547,930,1292,1321,1340`; `energy_battery.py:2853,3180`; `sensor.py:9390`. Only `inclement.py:295` iterates the table.
- `match_product|build_record(`: `inclement.py:326,403,495,502`, `energy_outage_ledger.py:271`.
- `preonset_floor`: `energy_battery.py:2693, 2798` (config), `2835, 3137-3145, 6352, 6385, 6839, 7057`; `energy.py:9544-9589`; `inclement.py:1009`.
- `rate_rank|is_bottom_rate|period_rank|cheapest|charge_window`: as in §1a. No existing "cheapest N hours before T" helper (grep `cheapest`: 0).
- `get_forecasts|_refresh_lock`: `weather_manager.py:160,414,443,866,903`.
- Tests touching changed rows: `test_ec_stage_b_classification.py:129-144`, `test_ec_stage_b_preonset_precharge.py:197-213, 569-590`, `test_ec_stage_c_hourly_outlook.py:188, 288-307`, `test_inclement_alert_classifier.py:111`.
- New names (`inclement_hold_products`, `inclement_buy_products`, `inclement_hold_added/_removed`, `inclement_buy_added/_removed`, `NWS_WEATHER_EVENT_NAMES`, `INCLEMENT_PREONSET_FLOOR_LEAD_H`, `INCLEMENT_GRID_CHARGE_PP_PER_H`, `INCLEMENT_PREONSET_BUY_MARGIN_H`, `preonset_target`, `preonset_buy_hours`, `InclementSelection`, `inclement_selection`): 0 hits each. **NEW.**

### 1c. Docs and memory read
- **In full:** the parent plan (Rev 3.5) and the arc doc.
- **READMEs:** v5.103.68 and v5.103.69, including the Validated table (377a7e3ed).
- **Audits:** Stage 0 probes (P1, P2(a)/(c)), NWS alert history, outage correlation.
- **Cards:** all three, plus EC-SOC-LADDER-FULL-WIRING-1.
- **Both plan reviews.**
- **Memory:** `project_storm_counsel_doctrine`, `reference_ec_config_surface`, `feedback_label_style_guide`, `feedback_configurability_clarity`, `feedback_suppression_needs_discharge`, `feedback_coincidental_equality_masks_concept_split`.
- **Not applicable:** the HVAC and presence state-of-play docs (energy only).

### 1d. Measured (read-only, 2026-10-17)
- **NWS vocabulary:** §0.1. 111 names.
- **SOC, recorder 10-10 06:33 → 10-17 14:33** (`sensor.envoy_482543015950_battery`, 148 hour pairs):
  - Positive ΔSOC per hour: p50 9, p90 25, max 30 pp/h. The top climbs are all 11:00-14:00, so they are **solar**.
  - No grid-charge episode is in the window, so the grid charge rate is **not measured**.
  - Operator: "our battery can charge from grid in 1-2 hours". That is 80 pp in 1-2 h, about 40-80 pp/h (16-32 kW on 40 kWh). The hardware ceiling is `BATTERY_MAX_CHARGE_KW` 30.72 kW, about 77 pp/h. The parent's ~10 kW estimate (25 pp/h) understated it.
- **SOC by local hour, median:** 00-10 h ≈ 7-10 %; 15 h 91 %; 17 h 98 %; 21 h 35 %; 22 h 10 %. The shoulder 17-21 top-rate block drains about 60 pp.
- **TOU (live PEC 2026):**
  - Winter: top rate (`mid_peak`) 05-09 and 17-21; every other hour is bottom (0.0435 vs 0.0864 $/kWh).
  - Shoulder: top rate 17-21.
  - Summer: mid_peak 14-16 and 20-21; peak 16-20.

---

## 2. Falsifiable invariants (INV-1 to INV-6 unchanged except INV-6(iii)'s rate gate, amended by INV-9)

> **INV-7 (the selection chooses WHETHER, never HOW).** These hold for every legal stored value of the four override keys, including empty, everything, names outside the vocabulary, hand-edited `.storage`, and combinations made illegal by a later table change. They also hold for every value of `watch_requires_corroboration`.
> - **(a) Locality.** A `polygon_local` product never contributes a hold or a buy unless `INCLEMENT_POINT_FEED_POLYGON_EXACT` is True. It never buys outside `[start, min(end, start + INCLEMENT_POLYGON_TOPUP_MAX_MIN)]`. The selection cannot change `polygon_local`.
> - **(b) Zone buys need the forecast.** A zone product never causes a charge_from_grid turn_on unless `forecast_confirms` holds on the same record (`_zone_buy_confirmed`).
> - **(c) Caps on added rows.** A product with no forecast family never buys. A **non-corroborable** record **never buys** (Rev 3, N1: neither through the pre-onset leg nor by joining a corroborated ineligible table watch's full hold) and never counts toward watch corroboration on **any** leg (condition, `watch_requires_corroboration=False`, forecast). A non-corroborable record is one that is unlisted (not in the table) or selection-widened (a table row whose default class is notice, added to hold). So a hold whose only HOLD records are non-corroborable never exceeds `partial_hold`, and such a prepare record gets only the lower pre-onset floor `max(reserve_soc, partial_floor)`.
> - **(d) Buy ⊆ hold.** The effective buy set is a subset of the effective hold set, computed at runtime (not only at form validation).
> - **(e) Table default.** `INCLEMENT_PRODUCT_TABLE` is the authoritative default and is never mutated. With zero overrides, the **classification, hold-depth and buy** projection (§E1.10) is identical to the v5.103.69 golden, except the enumerated E0 cells. Prepare-floor cells belong to INV-8/INV-9.
> - **(f) No demotion of table products.** Adding an unlisted or widened product never changes the decision for a co-active table product.
>
> **Falsifiers:**
> - a CFG off→on whose reason names a product outside the effective buy set;
> - a zone-product buy with `inclement_buy_forecast.confirmed` false;
> - a non-corroborable-only hold at `full_hold`, under either `watch_requires_corroboration` value;
> - a polygon hold while `POLYGON_EXACT` is False;
> - a zero-override golden diff outside the enumerated cells;
> - a mixed fixture (Winter Storm Watch + unlisted Flood Watch) whose decision differs from Winter Storm Watch alone.
>
> **Repros:**
> - (i) `watch_requires_corroboration=False` (legal option), Flood Watch added to hold, bottom rate. Without the cap the result is `watch_corroborated_offpeak_full_hold` (Review 2 H1).
> - (ii) Wind Advisory added to hold, provider `pouring`, top rate. Without the cap the result is a full hold on rain (Review 2 M6).

> **INV-8 (pre-onset floor only when it counts).** Let `T` be the event time (§E2.1) and `S` the alert's buy schedule (§E2.2, empty when there is no buy). The D-B6 floor is registered on a tick iff `now < start` and **one** of these holds:
> - (i) `now ≥ T − min(INCLEMENT_PREONSET_FLOOR_LEAD_H, INCLEMENT_PREONSET_LEAD_H)`; or
> - (ii) `S` is non-empty and `now ≥ min(S)`, and this tick's buy is still eligible (option on AND same-record confirmed). If eligibility is lost, the latch entry is cleared (`engaged`) or kept with no floor extension (`reached`). Losing eligibility is the discharge for the suppression.
>
> Active holds (`start ≤ now ≤ end`) are unchanged.
>
> **Stated non-guarantees:**
> - A restart mid-buy loses the latch and schedule (RAM). The floor falls back to (i) until the schedule is recomputed on the next tick.
> - In observation mode the latch is rolled back each tick (`energy.py:9420`), so (ii) never applies there.
>
> **Falsifiers:**
> - a `reserve_write` row with non-null `tick_preonset_floor` before `min(T − floor_lead, min(S))`;
> - a floor that persists after the option turns False or the forecast unconfirms with the latch still `engaged`;
> - floor lead 0 with no schedule and a floor registered;
> - any in-window decision change.

> **INV-9 (buy in the cheapest hours closest to the event; amends INV-6(iii)'s `is_bottom_rate(now)` conjunct).** A D-B6 grid buy happens on a tick only if the hour slot containing `now` ∈ `S`. `S` is built and frozen per §E2.2: `h_req` slots (0 when SOC is None or ≥ target), chosen from the UTC hour slots `[H, H+1h)` with `H+1h > now`, `H < T`, `T − H ≤ INCLEMENT_PREONSET_LEAD_H`, excluding unranked slots. They are ordered by `(period_rank(local H), T − H)`: cheapest first, then closest to `T`.
> - An hour with rank > 0 is in `S` **only if** fewer than `h_req` rank-0 hours exist in that range.
> - `S` is frozen at the freeze point of §E2.2 rule 5 and deleted by that rule's discharge. An NWS Update is a new alert ID and starts a fresh `S` (§E2.2 rule 6).
>
> **Falsifiers:**
> - a pre-onset CFG on in a rank > 0 hour while ≥ `h_req` rank-0 hours remained before `T` at schedule time;
> - a pre-onset CFG on at a rank-0 hour farther from `T` than an unscheduled rank-0 hour closer to `T`;
> - more than one CFG on→off per frozen schedule over D-B6-owned ticks (parent H2 scoping).
>
> **Repro:** winter WSW, Onset 21:00, SOC 30 at 06:00, target 80, rate 50 pp/h, margin 1 → `h_req = 1 + 1 = 2` → `S = {15:00, 16:00}`. Those are the last bottom-rate hours before the 17-21 top block, and the floor starts 15:00 (INV-8(ii)). Today the buy fires at the first bottom-rate tick (09:00, after the 05-09 block), the floor runs from 09:00, and the latch keeps it there.

---

## 3. Producer and consumer checks

| Value | Producer | Consumers |
|---|---|---|
| `InclementSelection` (E1) | `build_selection(cm_options)` (pure, `inclement.py`). Effective hold/buy sets plus a corroborable flag per name. Built once per tick in `_inclement_config()`, and by `energy.py` for the ledger from the same `_get_cm_options()`. | `match_product` (all 3 callers, trust); `_decide_hold` corroboration (trust); `inclement_selection` attr (display); ledger `ura_class` (audit). |
| Effective row | `match_product(alert, selection)`: table row → overlay rewrites `cls`, tier and `precharge_eligible`, and adds `corroborable`; an unlisted hold name gets the synthetic `(None, event, "watch", False, False)` with `corroborable=False` and no drift reporting. | `build_record` → `AlertRecord` (memory admission keys on `rec.cls` `:404`, prepare split `:505`, `prepare_class_of` `:126`), `_effective_tier`, `_precharge_flags`, `_zone_buy_confirmed`. |
| `T` (E2) | `preonset_start` (the earliest prepare start, `_apply_prepare` `:957-963`). On E2-P GO only (E2b): the first forecast-confirming hour in `[start, end]`. | Floor gate (trust), scheduler (trust), attr (display). |
| `S` buy schedule (E2) | `schedule_buy_hours(tou, now, T, h_req, horizon)` (pure, calls `rate_rank`); frozen on the latch. | Buy gate at `energy_battery.py:6352` (trust); floor gate (trust); attr `inclement_preonset.buy_hours` (display). |
| `h_req` | `(target − SOC)` from SOC (3-tier resolver; None means no buy, as today) ÷ `INCLEMENT_GRID_CHARGE_PP_PER_H` (operator-stated; unmeasured, §1d). | Scheduler. If the rate is too high (charge slower than assumed), the schedule ends with SOC < target at `T`. The floor still blocks discharge and the hold at `start` takes over. Error toward a short charge, stated (E2-P measures the rate when an episode exists). |

---

## 4. Site enumeration

**4.1 `match_product` callers (three), each its own Review C drill.**
- `classify` (`inclement.py:495`).
- `build_record` (`:326`). It reaches D-B3 memory admission through `update_alert_memory` (`:403`) and the active/prepare split through `classify` (`:502`).
- The outage ledger (`energy_outage_ledger.py:271`). Its `record_tick` gains `selection`, passed by its caller in `energy.py`, which builds it with `build_selection(self._get_cm_options())`.
- **No module global** and no constructor-cached state. `AlertClassifier(selection=…)` takes it per construction, and the battery builds the classifier per tick (`:2749`). Every parameter defaults to `TABLE_SELECTION` (zero overrides), so an omitted argument is byte-identical.
- The AST test pins that `INCLEMENT_PRODUCT_TABLE` is iterated only in `match_product`/`build_selection`.

**4.2 Corroboration site (one).** In `_decide_hold`, the tier-level `corroborated` (`inclement.py:1095-1105`). Every leg is ANDed with `any(r.corroborable for r in watch_records)`, where `watch_records` = active HOLD records with `tier == "watch"`. Mixed sets keep the table watch's corroboration, so INV-7(f) holds.

**4.3 `preonset_floor` readers (seven; split per §E2.4).**

| # | Site | Reads after the split |
|---|---|---|
| 1 | `energy_battery.py:6352` buy precondition | `preonset_target is not None` AND hour ∈ `preonset_buy_hours` (replaces the `is_bottom_rate` conjunct in fusion `:997`) |
| 2 | `:6385` buy `reserve_level` | `preonset_target` |
| 3 | `:2835` grid-buy NM stamp `target` | `preonset_target` |
| 4 | `:3137-3145` `inclement_preonset` attr | emitted whenever `preonset_target` is non-None. Fields: `floor` (target), `active` (`preonset_floor is not None`), `floor_from`, `buy_hours`, `event_time`, `event_time_source` (`"onset"`, or `"forecast"` only under E2b) |
| 5 | `:6839` `_registered_floor` | `preonset_floor` (registered) |
| 6 | `:7057` narration | `preonset_floor` (registered) |
| 7 | `energy.py:9544-9550` ledger `tick_preonset_floor` | `preonset_floor` (registered) |

`inclement.py:1009` (the producer) sets both fields. The builder re-greps `preonset_floor|preonset_target` at build time. **An eighth reader stops the build** until it is classified here. Drill per row: swap target↔registered at that reader, and a named test goes RED.

**4.4 Eligibility consumers:** `_precharge_flags`, `polygon_topup_records`, `_zone_buy_confirmed` and the buy expressions (`inclement.py:989, 1020, 1068, 1140`) all read `rec.eligible`. They are unchanged, because the record carries the effective value. Reviewer D re-greps `\.eligible|precharge_eligible`.

**4.5 Rate-gate consumers changed by INV-9:** only the D-B6 leg (fusion `:997` `is_bottom` and site 1). The full-hold off-peak leg and the polygon leg keep their gates. Stated: those are **in-window** buys, where the event is already under way.

---

## 5. Deliverables

### E0: NWS vocabulary re-sync (rung-1 table rows)

| Product | Today | After | Eligible | Family | Why |
|---|---|---|---|---|---|
| Freeze Warning (`FZW`, probe-verified) | notice | **watch** | yes (buys only on a forecast ≤ 28 °F) | freeze (air temp) | Carries the hard-freeze hazard now. Watch class keeps a 32 °F night at partial hold. |
| Freeze Watch | **gated out (no row)** | **watch**, `code=None` (FZA unverified) | yes (same rule) | freeze (air temp) | Precursor. Name-only per the P3 policy (`energy_const.py:688-690`); drift records the real code. |
| Cold Weather Advisory | notice | notice | no | freeze, and added to `FORECAST_APPARENT_TEMP_PRODUCTS` | Successor of Wind Chill Advisory (apparent-temperature hazard), so an operator-widened hold confirms on apparent temp. |
| Hard Freeze*, Wind Chill* rows | unchanged | unchanged, KEEP+DOCUMENT (retired-name list pinned) | unchanged | unchanged | Harmless; still matches replays. Outside the selectable vocabulary (§E1.2). |

**Stated behaviour the operator approves (OQ-1):**
- A 34 °F Freeze Warning at **bottom** rate gives `partial_hold` (floor 50 live).
- The same alert at **top** rate (winter 05-09, 17-21) gives `allow_discharge`, so the battery is released. An uncorroborated watch at top rate discharges today too (`inclement.py:1121-1127`).
- At ≤ 28 °F the watch is corroborated. At bottom rate that gives `full_hold`. At top rate the result depends on recoverability (`:1159-1172`): `full_hold` if not recoverable, else `partial_hold`.

**Acceptance**
- **Verify (bottom rate, 03:00 Dec):**
  - FZW, outlook 34 °F → `partial_hold`, no buy with option True.
  - Outlook 25 °F → `full_hold`, buy eligible with SOC 50.
- **Verify (top rate, 18:00 Dec):**
  - FZW at 34 °F → `allow_discharge`.
  - At 25 °F → recoverability decides. Two fixtures: SOC 95 with Solcast high → `partial_hold`; SOC 30 → `full_hold`.
- **Verify:** Cold Weather Advisory → notice. Freeze Watch → watch (not gated out).
- **Test:** `test_vocab_snapshot_covers_table` (every non-retired table name is in the vocabulary; the retired list is pinned), `test_freeze_warning_watch_class_forecast_lift` (TOU-parametrized as above), `test_freeze_watch_name_only_row`, `test_cold_weather_advisory_apparent_temp`.
- **Update with the expected diff stated** (no assertion may be weakened silently):
  - `test_ec_stage_b_classification.py:129-144`: FZW notice → watch.
  - `test_ec_stage_b_preonset_precharge.py:197-213`: `"Freeze Warning": False` → True; add Freeze Watch True.
  - `test_ec_stage_c_hourly_outlook.py:188, 288-307`: add FZW/FZA air-temperature cases and the Cold Weather Advisory apparent case.
- **Live (event-gated, disposes on the first FZW):** the `nws_alert` row's `ura_class` reads `watch`, now that the ledger goes through the overlay (§4.1). `notice` would mean the ledger caller was missed.

### E1: operator alert selection over the internal table (EC-STORM-PRODUCT-SELECTION-EXTERNAL-1)

**E1.1 Shape.** Two multi-selects in the existing inclement options section (rung 2):
- **"Alerts that hold the battery"** (form key `inclement_hold_products`).
- **"Of those, alerts that may buy grid power"** (`inclement_buy_products`). Helper text: "Only used when 'Top up before storms' is on. Zone-wide alerts still need the local forecast to agree; storm warnings must cover the house."

I chose two lists over a per-product four-way dropdown for glanceability: two fields instead of ~30 (label style guide). A product left out of hold becomes **notice** (shown and logged, never a hold). Gating out stays internal.

**Validation errors**, field-scoped, with `strings.json` and `translations/en.json` `error` entries:
- `buy_not_in_hold`: "Pick it under 'Alerts that hold the battery' first."
- `buy_needs_forecast`: "This alert can't buy grid power: there's no local forecast check for it."

**E1.2 Choices.**
- `NWS_WEATHER_EVENT_NAMES` (NEW, rung 1): the weather subset of `api.weather.gov/alerts/types`, fetched 2026-10-17 and cited in the constant.
- **Excluded:** marine/coastal/Pacific products (`Hurricane Force Wind *`, `Storm Warning/Watch`, `Storm Surge *`, `Typhoon *`, `Gale *`, seas/surf/spray), statements (`Special/Severe Weather Statement`, `Hazardous Weather Outlook`, `Short Term Forecast`), and civil/911/test/administrative messages.
- **Included but unlisted:** `Snow Squall Warning` (it becomes a **zone** watch if added, not a polygon product), `Lake Effect Snow Warning`, `Extreme Heat Warning/Watch`, flood and fire products.
- **No free text.**
- The **selection domain** is `table_names ∩ NWS_WEATHER_EVENT_NAMES` plus unlisted vocabulary names. Retired table rows (Hard Freeze*, Wind Chill*) are outside it: they always use table behaviour, never appear in the form, and never produce a delta (Review 2 H5).

**E1.3 Threading.** `InclementSelection` is a frozen dataclass: `hold: frozenset[str]`, `buy: frozenset[str]`, `widened: frozenset[str]`, `unlisted: frozenset[str]`, all case-folded.
- `build_selection(options)` computes:
  - `hold = (default_hold − hold_removed) ∪ hold_added`;
  - `buy = ((default_buy − buy_removed) ∪ buy_added) ∩ hold ∩ (family ∪ polygon-table rows) ∩ corroborable_names`. This is the runtime INV-7(c)/(d) (Reviews 1 F9 / 2 H4; Rev 3 N1). `corroborable_names` = table rows whose default class is warn/watch. So a widened notice row (e.g. Cold Weather Advisory, which has the freeze family after E0) or an unlisted row can never buy. The form adds a third validation error, `buy_needs_table_hold`: "Only alerts that hold by default can buy grid power." It has strings and translations.
  - **Row shape (Rev 3, N5):** `match_product` keeps returning a 5-tuple with positions 0-4 unchanged (`code, name, cls, polygon_local, eligible` after the overlay), so the index readers `inclement.py:338-340` and `energy_outage_ledger.py:272-274` stay correct. `corroborable` is returned as a separate third element: `(row, drift, corroborable)`. Callers that unpack two values are updated (3 sites, §4.1), and `AlertRecord` gains `corroborable: bool = True`.
- It is passed explicitly per §4.1. `TABLE_SELECTION` is the zero-override constant.
- **Overlay semantics in `match_product`:**
  - A table HOLD row not in `hold` → `cls = tier = "notice"`, `eligible = False`.
  - A table notice row in `hold` → `cls = "watch"`, `corroborable = False`.
  - A table HOLD row in `hold` → unchanged, `corroborable = True`.
  - An unlisted name in `hold` → synthetic watch, `corroborable = False`, no drift entry.
  - `eligible = name ∈ buy` (polygon rows keep their locality and cap gates).
  - The overlay rewrites `cls`, `tier` and `eligible`, so memory admission (`:404`), the prepare split (`:505`) and `prepare_class_of` (`:126`) all see it.

**E1.4 Caps (INV-7(c)).** Implemented by §4.2's per-tier conjunct. A non-corroborable record also gets the lower pre-onset floor (`_apply_prepare` `high` requires a corroborable warn, or a corroborable watch that is confirmed).

**E1.5 What the selection may change.** It may change whether a product holds or buys, never how (coordinator point 2).
- Narrowing is always allowed.
- Widening hold gives watch class, capped at partial, never corroborated.
- Widening buy is allowed only for rows with a forecast family or polygon locality. For example, Tornado Watch buys only on the convective confirm, which needs a storm condition and ≥ 70 % PoP.
- **Un-parked by this deliverable (Review 1 F10), stated:** parent §10 parks "Promoting Wind Advisory to hold" and "Pre-charge eligibility for convective or tropical products" with ledger-outage triggers. E1 lets the **operator** do either, bounded by INV-7.
- The table **defaults** stay rung-1 evidence. Widening is a rung-2 operator action, not a reviewed evidence change.
- The parent §10 park entries are amended in the ship commit to "default unchanged; operator-selectable via E1".

**E1.6 Storage: overrides, not a snapshot.**
- Stored keys (rung 2): `inclement_hold_added`, `inclement_hold_removed`, `inclement_buy_added`, `inclement_buy_removed`. Each is a list of canonical vocabulary spellings, compared case-folded.
- The submit handler computes the deltas over the selection domain and then **pops** `inclement_hold_products` / `inclement_buy_products` from `user_input`. Otherwise `.storage` would hold a snapshot and the reload decision would see non-suppressed keys (Review 1 F8).
- **Rendering:** the form defaults are the effective lists. A stored name no longer in the vocabulary is filtered out of the rendered default, because HA's selector rejects unknown values. It stays in storage, ignored at runtime with one debug log, until the next save drops it.
- A `hold_added` name whose table row is later removed becomes an unlisted synthetic watch (stated).
- All four keys go in **`_NO_LIVE_ATTR_KEYS` and `OPTIONS_RELOAD_SUPPRESS_KEYS`** (Reviews 1 F7 / 2 M1). They are read per tick, and saving does not reload the Coordinator Manager.
- **Migration:** the live legacy list equals the v5.5.0 default, so nothing is written. A customized list keeps the repair issue, whose text (`strings.json:2321-2323` + translations) now points at the two new fields (F15).

**E1.7 Show consequences (`inclement_selection` attr).** Wiring (Rev 3, N4): add `inclement_selection` to the `sensor.ura_inclement_state` pass-through allowlist (`sensor.py:9376-9393`) and to the pinned key set in `test_inclement_state_sensor.py:35-48`. Without both, the attr exists only in battery status (#53). For each active or prepare alert: `{event, level: "hold"|"hold+buy"|"notice", source: "table"|"override"|"widened"|"unlisted", corroborable, buy_gate: "forecast_confirmed"|"forecast_unconfirmed"|"polygon_in_cap"|"polygon_out_of_cap"|"not_selected"|"option_off"}`. Plus `overrides`. Display only.

**E1.8 Scope rules.**
- Other locations: help text "Defaults come from storm and outage history at this house (Lakeway, TX)". No per-region sets (parked; trigger: a second install).
- Severity stays retired.

**E1.9 Retire the dead legacy plumbing (three buckets).**

| Item | file:line | Bucket | Reason |
|---|---|---|---|
| Legacy keys built in `_inclement_config` (never passed: `AlertClassifier()` takes no args, `:2749`) | `energy_battery.py:2608-2609, 2618-2619, 2647-2660` | DELETE | Built and dropped; misleads readers. |
| `AlertClassifier.__init__` legacy args | `inclement.py:447-453` | DELETE (it gains `selection`) | `test_inclement_alert_classifier.py:111` is updated (expected diff: legacy kwargs removed; `selection` kwarg added). |
| config_flow imports + parse | `config_flow.py:6030-6031, 6036-6037, 6164-6168` | DELETE | Key never submitted. |
| Field strings | `strings.json:983-984, 1068-1069` + translations | DELETE | Dead UI text. |
| `CONF_INCLEMENT_POWER_THREAT_EVENTS`, `DEFAULT_…` | `energy_const.py:615, 634-643` | KEEP+DOCUMENT | The repair check reads them. |
| Severity constants (`CONF_…WARN_MIN_SEVERITY`, default, options, order) | `energy_const.py:616, 644, 838-840` | DELETE if 0 readers after the above, else KEEP+DOCUMENT | Builder greps; `_severity_rank` may keep the order for attrs. |
| `_event_matches_threat` | `inclement.py:237` (0 callers) | DELETE | Parent §13 gate met: the v5.103.69 Validated table landed (377a7e3ed). |
| `_check_legacy_threat_list` | `energy.py:8335` | KEEP | Live repair path. |

`test_legacy_plumbing_removed` (AST: no reader of the two keys outside the repair check; the two fields absent from the schema) also covers the parent §16 deferred item "D-B5 field removal has no unit test".

**E1.10 Golden (zero-override comparison against v5.103.69).**
- **Capture:** the committed script `scripts/golden/ec_stage_e_capture.py` runs in a worktree at tag **v5.103.69** and writes `quality/tests/fixtures/ec_stage_e_golden_v5_103_69.json`. Both are committed **before any Stage E code**. The same script runs on the build branch with zero overrides and compares the two outputs.
- **Entry point:** `AlertClassifier.classify` then `InclementFusion.decide(...)` (`inclement.py:877`), once per cell: a single tick, fresh latch `{}`, fresh buy schedule `{}`, empty forecast latch.
- **Cell → times:** a fixed calendar. Winter `now` = 2026-12-16 03:00 local (bottom) or 18:00 (top); summer 2026-07-15 03:00 / 17:00. Onset = `now` + {−1 h (active), +3 h, +8 h}. Polygon cells: start = `now` − 20 min (in cap) or − 70 min (out of cap).
- **Fakes:** `FakeTOU` (`get_season`, `get_current_period`, `period_rank`, `is_bottom_rate`) built from the committed `tou_rates.json`, so ranks agree with the bottom/top axis by construction. A fake battery with `_expected_solar_surplus_pct` returning 0 and `_tou = FakeTOU`.
- **Knob values:** pinned in the fixture header: v5.103.69 defaults; on the build side also `INCLEMENT_GRID_CHARGE_PP_PER_H=50`, `INCLEMENT_PREONSET_BUY_MARGIN_H=1`, `INCLEMENT_PREONSET_FLOOR_LEAD_H=4`.
- **Axes:**
  - product: every table row, Freeze Watch, and one unlisted name;
  - window position: {active, prepare +3 h, prepare +8 h, polygon in cap, polygon out of cap};
  - TOU {bottom, top} × season {winter, summer};
  - SOC {None, 30, 95};
  - condition {calm, stormy with ≥ 2 providers};
  - `watch_requires_corroboration` {T, F};
  - option {T, F};
  - forecast {confirms, not, None}.
- **Projection** (named fields only; new dataclass fields don't affect it):
  - `AlertClassification`: `{tier, contributing_events, expires_at, hold ids/cls/tier, prepare ids, precharge_eligible, polygon_topup_active, prepare_precharge_eligible}`.
  - `InclementDecision`: `{hold_depth, reserve_floor, grid_precharge, preonset_target (= v5.103.69 preonset_floor), reason}`.
  - **On prepare cells** it also drops `grid_precharge`, `preonset_precharge` and the registered floor. Buy and floor timing there are owned by the INV-8/INV-9 hand-table tests, so the golden never depends on `schedule_buy_hours`.
- **Allowed diff:** exactly the cells whose product is `Freeze Warning` or `Freeze Watch` (E0), enumerated by product name in the script. **Any other diff is RED.**
- **INV-9 hand table:** `quality/tests/fixtures/ec_stage_e_buy_schedule_cases.json`, written by hand and reviewed before build. At least 12 rows of (season, `now`, Onset, SOC, expected S), covering:
  - removed bottom-rate buys and added unavoidable rank > 0 buys;
  - partial S, and T on the hour;
  - SOC ≥ target (S = ()), and a DST night.

  Both directions of E2's buy change are pinned there.

**E1 Acceptance**
- **Verify:**
  - (INV-7e) The golden comparison passes with the enumerated diff only.
  - Behavioural "not mutated" drill: an override run leaves `INCLEMENT_PRODUCT_TABLE` and `TABLE_SELECTION` equal to their import-time copies.
- **Verify (narrow):** WSW removed from hold → notice, `allow_discharge`, **not admitted to D-B3 memory**, no prepare floor. WSW removed from buy only → `full_hold`, no CFG (option True, SOC 50, bottom rate, forecast confirmed).
- **Verify (widen):**
  - Tornado Watch added to buy → buys only with `lightning` + PoP 75; with PoP 60 or `pouring`, no buy.
  - Wind Advisory added to hold + `pouring` + top rate → `partial_hold` at most (repro ii).
- **Verify (caps, INV-7(c)/(f)):** each case parametrized over `watch_requires_corroboration` {T, F}:
  - Flood Watch in hold → `partial_hold` max (repro i).
  - Mixed Winter Storm Watch + Flood Watch → identical to Winter Storm Watch alone.
- **Verify (INV-7a):** an override adding SVW to buy has no effect when `POLYGON_EXACT` is False.
- **Verify (runtime subset):** seed `buy_added=["Tornado Watch"]` with Tornado Watch removed from hold (or a monkeypatched table that makes it notice) directly into options → no buy and no error.
- **Verify (storage):**
  - Submitting the defaults through the real flow handler stores four empty lists, no form keys, and no `hold_removed` for retired names.
  - A case-variant stored name matches.
  - An out-of-vocabulary stored name is not rendered and is ignored at runtime.
- **Verify (no reload):** a changed selection gives `apply_in_place`.
- **Tests:**
  - `test_zero_override_golden_identical_to_v5_103_69`, `test_product_table_not_mutated_by_selection` (behavioural);
  - `test_selection_overlay_applies_in_classify`, `…_in_build_record`, `…_in_memory_admission`, `…_in_outage_ledger`;
  - `test_selection_remove_hold_is_notice_and_not_admitted`, `test_selection_remove_buy_keeps_hold`, `test_selection_widen_buy_needs_forecast`, `test_widened_notice_not_corroborable`;
  - `test_unlisted_product_capped_partial_hold[req_true|req_false]`, `test_mixed_unlisted_does_not_demote_table_watch`, `test_selection_cannot_override_polygon_locality`, `test_runtime_buy_subset_of_hold_seeded_store`;
  - `test_selection_validation_buy_subset_of_hold`, `test_selection_validation_buy_needs_family`, `test_selection_stores_deltas_only_real_flow`, `test_selection_form_keys_popped`, `test_selection_casefold_and_unknown_names`;
  - `test_selection_keys_in_no_live_attr_keys`, `test_selection_keys_in_options_reload_suppress_keys`, `test_selection_reads_live_options_per_tick`;
  - `test_unlisted_rows_skip_drift`, `test_inclement_selection_attr_shape`, `test_legacy_plumbing_removed`.
- **Mutation drills (Review C):**
  - remove the overlay from each `match_product` caller (four drills, each RED);
  - drop `∩ hold` in `build_selection`;
  - drop the corroborable conjunct per leg (three drills);
  - use `any(unlisted)` instead of `any(corroborable)` (the mixed test goes RED);
  - let the overlay set `polygon_local`;
  - store the full list;
  - leave the form keys unpopped;
  - drop a key from either live/reload set;
  - mutate the table in place.
- **Live:**
  - (a) After one save, `.storage/core.config_entries` holds the four override keys (empty) and **no** `inclement_hold_products`/`_buy_products`. A form key present means a snapshot leak.
  - (b) No CM reload in the log on saving a changed selection (discriminates a missing reload-suppress key).
  - (c) 0 URA errors mentioning `selection` / `match_product` after restart.
  - Rev 1's "attr reads [] with no alert" line is dropped (Review 2 L3: non-discriminating).

### E2-P: measure first, the forecast-timed hold (go/no-go this cycle)

A one-shot, read-only `ura-prober` script. It runs **before** E2 build dispatch and its report is committed as `docs/planning/AUDIT_ec_storm_event_time_vs_onset.md`.

- **Q1, Onset re-stamps:**
  - Over the IEM VTEC archive for TXZ192 / TXC453, 2021-2026 (same source as `AUDIT_nws_alert_history_lakeway.md`), for every HOLD-class and E0 product: how many events had an Update (CON/EXT) whose begin time was re-stamped to its issue time, and by how many hours it moved the effective start earlier.
  - Cross-check with the live `nws_alert` ledger rows (Stage L, since 10-16) and the recorder history of the alerts sensor (~10 days).
- **Q2, Onset lead:**
  - For each event: the first observed hazard hour from the nearest ASOS station's hourly observations (IEM ASOS archive; the prober names and cites the station). Freeze family: first hour ≤ 28 °F (apparent temperature for Extreme Cold). Winter storm: first hour with frozen precip present. Convective: first thunder report.
  - The gap `G = first_hazard_hour − effective_start`.
  - Observed hazard is the **oracle**. It is an upper bound on what a forecast could deliver. If a historical-forecast archive covering the house point is available (for example Open-Meteo's historical forecast API, **availability to be verified by the prober**, not assumed), also record the first forecast-confirming hour.
- **Q3, value:** peak-block hours that a forecast-timed hold (`T − L_floor`) would have released versus Onset-timed. Report per event, per year, and in $ (pp × 0.4 kWh × top-bottom spread).
- **Q4, safety:** documented outages (`AUDIT_outage_alert_correlation.md`) that began before `T − L_floor`, i.e. where a deferred hold would have been late.
- **Q5, grid charge rate:** any recorder episode with the charge-from-grid switch on and battery charge power available gives the pp/h. If there is none (likely, §1d), record "none; operator value 1-2 h stands".

**Go/no-go for E2b** (the forecast-timed in-window hold for **watches**, plus re-stamp handling). **GO** iff all three:
- (a) ≥ 3 events in 5.8 y with `G ≥ 4 h`;
- (b) ≥ 12 top-rate hours released over the archive (≈ 2/yr);
- (c) **zero** Q4 outages that would have begun before `T − L_floor`.

Otherwise **NO-GO**: E2b parks with the ledger trigger (≥ 3 ledger HOLD events with `G ≥ 4 h` once Stage C forecast attrs accrue).

**On GO:** E2b gets its own plan addendum and Tier-3 increment (per-hour predicate over `_hourly` rows, "cold and wet in the same hour"; fallback `T = start`). It covers watches only. Warn deferral, including re-stamped warns, stays an explicit operator ruling (OQ-3b), because it demotes an active warning. Without E2b, `T = start` (Onset).

**Acceptance:** the report answers Q1-Q5 with counts and sources, and states GO or NO-GO against (a)-(c). **Live:** n/a (offline).

### E2: buy in the cheapest hours before the event; floor no earlier than needed (EC-STORM-PREONSET-TIMING-1 + operator ruling)

**E2.1 Event time `T`.** `T = preonset_start` (Onset of the earliest prepare alert; NWS onsets for watches are hazard start, P2(c)). Under E2b GO only, `T` may come from the forecast. `T` is shown in the attr with `event_time_source`.

**E2.2 Buy schedule (operator ruling; prior art REUSED).** One pure function `schedule_buy_hours(tou, now, T, h_req, horizon_h) -> tuple[datetime, ...]` in `inclement.py`. It ranks slots with the existing `period_rank` / `get_season` / `get_current_period` helpers (`energy_tou.py:459, 491`): no tariff parsing, no period names. The idea is arbitrage's "charge just before the expensive window" (`_is_charge_window_open`, `energy_battery.py:3558`), generalised from "the next high-rate transition" to "the event". It orders slots by `(rank, T − H)` and takes the first `h_req`, so the bottom-rate slots closest to the event are used. A higher-rate slot enters only when fewer than `h_req` bottom-rate slots remain before `T` (operator: "only during a higher rate window before the event if unavoidable"). Rules:
1. **Slots.**
   - Candidates are UTC hour slots `[H, H+1h)` with `H + 1h > now` and `H < T`, and `T − H ≤ INCLEMENT_PREONSET_LEAD_H`. The slot containing `now` is a candidate.
   - The buy gate is "the slot containing `now` ∈ S".
   - A slot that straddles `T` (T not on the hour) counts as one slot.
2. **Time.**
   - Step on **UTC** hour boundaries (`dt_util.as_utc`, `+ timedelta(hours=1)`). Rank each slot by `dt_util.as_local(H)` → `get_season` / `get_current_period` / `period_rank`.
   - Ordering distance is `T − H` in UTC seconds.
   - Do **not** copy `peak_ahead_before_offpeak`'s wall-clock step (it skips or duplicates hours across DST).
   - `T` (fixed-offset from NWS) is converted with `as_utc` before comparison.
3. **Unranked hours and engine missing.**
   - A slot whose `period_rank` is None is excluded.
   - Engine missing (`battery._tou is None`): S = () and no D-B6 buy. This is a stated byte change from v5.103.69's current-tick `off_peak` fallback, acceptable because the option is off live and an engine-less install has no rate data to schedule against.
   - The engine raising also gives S = (). Floor rule (i) is unaffected in both cases.
4. **No-need case.**
   - If SOC is None or SOC ≥ target: S = (), `h_req = 0`, and no floor via (ii).
   - Otherwise `h_req = ceil((target − SOC) / INCLEMENT_GRID_CHARGE_PP_PER_H) + INCLEMENT_PREONSET_BUY_MARGIN_H`. The margin is added only when a buy is needed.
5. **Storage and freeze point.**
   - The latch stays `dict[str, str]` (`energy_battery.py:474`; the five string readers `inclement.py:975, 984`, `energy_battery.py:3145, 6403-6408`, `energy.py:9420-9421` are untouched).
   - New sibling RAM dict `BatteryStrategy._preonset_buy_schedule: dict[str, tuple[tuple[datetime, ...], datetime, int]]` = `(S, T, target)`, keyed on the prepare `key_id`. It is passed into `_apply_prepare` beside the latch.
   - **Freeze point:** the first tick on which every D-B6 buy conjunct except "slot ∈ S" holds (option, same-record confirmed, corroborable, SOC known and < target, latch not `reached`, solar test failing or latch `engaged`). S is computed then and stored, and later ticks read the stored S.
   - **Readers:** the buy gate (§4.3 row 1), the floor gate INV-8(ii), and the attr `buy_hours` (row 4).
   - **Discharge:** the entry is purged in the same loop as the latch (`inclement.py:950-953`, alert left the prepare set or Onset reached). It is also **deleted** on any tick where the option is False or `_zone_buy_confirmed` is False, whether or not the latch ever engaged, and in observation mode alongside the `engaged` rollback (`energy.py:9420`). Option re-enabled later → no stored S, so the next qualifying tick computes a fresh S from that tick (no stale-schedule case).
6. **Onset Updates.**
   - An NWS Update is a new message ID (`alert_key`, `energy_outage_ledger.py:72-81`), so the old latch and schedule are purged and the new ID starts fresh: no carry-over, and the solar test re-runs.
   - Accepted, not engineered. This is parent §12 limit 23's class. A carry-over keyed on event name + window overlap would add the state × time seam for a rare event.
   - Cost: at most one extra CFG off→on per Update during a buy.
   - The test uses a **new ID** with a moved Onset (`test_schedule_fresh_on_update_new_id`).
7. **Multi-alert value.**
   - Under INV-8(ii) the registered floor = `preonset_target` (the key row's value that was bought toward).
   - The "class of rows inside the floor window" value rule applies only under INV-8(i).
   - Fixture: warn 10 h + watch 3 h with a buy in progress → registered 80, not 50.
8. **Pinned examples.**
   - Shoulder (October) Onset 21:00, SOC 70 → `h_req = 1 + 1 = 2` → S = {15:00, 16:00} (last bottom hours before the 17-21 block).
   - Partial S: T 40 min away at a bottom-rate hour with `h_req = 2` → S = {current slot}.
   - T exactly on the hour: the slot `[T−1h, T)` is the last candidate.

**Drills (scheduler):**
- (a) Recompute S every tick instead of freezing. The fixture has SOC rising 30→60 mid-buy so S shifts later, and the test asserts one CFG on→off; it goes RED.
- (b) Exclude the slot containing `now` (the hh:30 test goes RED).
- (c) Drop the margin-only-when-needed rule, and separately compute `h_req` from `floor` instead of `target`.
- (d) Drop the eligibility conjunct from INV-8(ii).
- (e) Engine-missing path returns a non-empty S.

**Tests added:** `test_schedule_includes_current_slot_at_half_past`, `test_schedule_soc_at_target_empty_no_floor`, `test_schedule_unranked_hour_excluded`, `test_schedule_engine_missing_no_buy`, `test_schedule_dst_fall_back_and_spring_forward`, `test_schedule_window_across_midnight`, `test_schedule_frozen_while_soc_rises`, `test_schedule_cleared_before_engage_on_option_off_and_unconfirm`, `test_schedule_fresh_on_update_new_id`, `test_two_alerts_registered_equals_target_under_buy`, and `test_buy_schedule_hand_table` (the §E1.10 fixture).

**E2.3 Floor timing, priced (operator point 3).** The floor's job is to keep charge you already have, or just bought, until the hold starts.
- **No buy scheduled** (option off, the live state; or not eligible): the floor starts at `T − INCLEMENT_PREONSET_FLOOR_LEAD_H` (default 4).
  - Winter: that is exactly the 17-21 (or 05-09) top-rate block before a 21:00 (or 09:00) Onset, the only window where the battery was going to discharge.
  - Price: holding through it forgoes ~60 pp × 0.4 kWh ≈ 24 kWh × (0.0864 − 0.0435) ≈ **$1.0 per event**.
  - The alternative is to let it discharge and arrive at Onset at ~10-35 % with no way to refill (option off).
  - Rule: with no buy available, hold through the last top block (at most 4 h, about $1). The 12 h lead it replaces held through bottom-rate hours for no gain.
- **Buy scheduled:** the floor starts at `min(S)`, so bought energy isn't discharged before `T`. Because `S` is the cheapest hours **closest to** `T`, any top-rate block between `min(S)` and `T` is one the charge could not avoid: there was no later bottom-rate slot.
  - Example: winter 21:00 Onset, `S = {15:00, 16:00}`, floor 15:00-21:00 (6 h, covering 17-21).
  - Price: the same ~$1 forgone discharge plus the buy (~20 kWh × 0.0435 ≈ $0.9).
  - Versus buying at 09:00 and holding 12 h (today): the same buy cost, plus the same forgone discharge, plus 6 more held hours. So E2 is never worse than today.
- **Not built:** "discharge through the top block, then rebuy after it". It only pays when bottom-rate hours exist **between** the last top block and `T` (rare in winter: the 21:00-onward and 09:00-17:00 slots). It saves the spread minus ~10 % round-trip loss, ≈ $0.9/event, but it adds a second buy per event and a dependence on the rebuy succeeding. Parked (trigger: E2-P or the ledger shows ≥ 3 events/yr with a top block followed by ≥ `h_req` bottom hours before `T`).

**E2.4 Field split (Reviews 1 F1 / 2 C1).**
- `InclementDecision.preonset_target: int | None` is the floor/buy **value**. It is populated across the buy horizon, exactly what `preonset_floor` carries in v5.103.69.
- `preonset_floor: int | None` is now the **registered** floor: equal to `preonset_target` when INV-8 (i) or (ii) holds, else None.
- New: `preonset_buy_hours: tuple[datetime, …] = ()` and `preonset_floor_from: datetime | None`.
- Readers per §4.3.
- **Placement in `_apply_prepare` (Review 2 M3):** after the latch purge (`:950-953`), the `engaged→reached` advance (`:974-980`) and the `pre` computation (`:984-1005`, whose `is_bottom` conjunct becomes "slot containing `now` ∈ S" per §E2.2). It sets `preonset_target`/`preonset_floor` in the final `replace()`. **No early return.**
- **Multi-alert:**
  - `T` is the earliest prepare start (`pstart`), so the floor gate uses `pstart`.
  - Under INV-8(ii) (a buy schedule exists) the registered floor = `preonset_target`, the value being bought toward (§E2.2 rule 7).
  - Under INV-8(i) only, the floor **value** uses the class of rows with `start ≤ now + floor_lead` (a warn 10 h out does not lift a watch's floor 3 h out). If no row is inside the floor window, the latch-key row is used.
  - The latch and schedule exemptions are checked on `key_id`.
  - Two-alert fixtures (warn 10 h + watch 3 h, with and without a buy) pin these rules.
- **Eligibility-loss discharge:** on any tick where the option is False or `_zone_buy_confirmed` is False, an `engaged` latch entry and the schedule entry are deleted. `reached` latch entries stay (no re-buy) but don't extend the floor.
- **Knob extremes (Review 2 L1):** effective floor lead = `min(FLOOR_LEAD_H, LEAD_H)`. Floor lead 0 + no buy → no floor. `LEAD_H` 0 → D-B6 off.

**Interactions:**
- The forecast-confirm latch is unchanged.
- §12 parent limits restated: **21** (lead 48 → now governs only the buy horizon; the floor is still ≤ floor lead or the schedule span); **23** (an Onset slip arrives as a new alert ID: fresh latch and schedule, and the floor follows the new `T`); **25** (a shrunken forecast window on restart can unconfirm a buy, so the eligibility-loss rule clears the floor extension; the floor falls back to (i)).
- EC-SOC-LADDER-FULL-WIRING-1 (parked, D2 peak-buffer seam): E2 neither touches `peak_buffer_target` nor fires its trigger (0 `threshold_ladder_violation` rows; the floor change is registration timing only).

**Acceptance**
- **Verify (INV-9 repro):** winter WSW Onset 21:00, SOC 30 at 06:00, option True, forecast confirmed, rate 50, margin 1 → `S = {15:00, 16:00}`; CFG on at 15:00, off when SOC ≥ 80; floor registered from 15:00. No CFG at 09:00-14:59.
- **Verify (unavoidable top rate):** WSW Onset 19:00 issued at 17:30, SOC 30 → `S` takes the rank-1 hours 17:00-18:00 (no bottom hours remain). Control: Onset 23:00 → `S` takes the bottom-rate hours 21:00-22:00, not the top-rate 17-21 hours.
- **Verify (closest to event):** October (shoulder) Onset 21:00, SOC 70, at 10:00 → `h_req = 2`, `S = {15:00, 16:00}`.
- **Verify (INV-8 option off):** same WSW, option False → no buy; floor from 17:00 (`T − 4`), none at 16:59. Regression control: with `FLOOR_LEAD_H = LEAD_H = 12` the floor starts at 09:00.
- **Verify (eligibility loss):** engaged at 15:00; forecast unconfirms at 16:00 → latch deleted, floor drops to rule (i) (17:00), CFG off. Option True→False at 16:00 → same.
- **Verify:** in-window hold golden unchanged. Effective floor lead parametrized (0, 4, 12, 13 → 12).
- **Tests:** `test_schedule_cheapest_closest_to_event`, `test_schedule_uses_higher_rate_only_if_unavoidable`, `test_preonset_floor_lead_window[0,4,12,13]`, `test_preonset_floor_from_schedule_start`, `test_preonset_floor_clears_on_eligibility_loss[unconfirm|option_off]`, `test_preonset_two_alerts_floor_value_and_gate`, `test_preonset_field_split_readers` (one assert per §4.3 row), `test_preonset_in_window_hold_unchanged_golden`.
- **Test-reference classification (Rev 3, N3):**
  - The builder first lists every `.preonset_floor` reference in `test_ec_stage_b_preonset_precharge.py` (~45, at `:552-638, 719-760, 917-1049, 1330-1334, 1685`). Each is classified as **target** or **registered** in a table committed with the build (same discipline as §4.3), before any edit. A reference whose classification changes its assertion is listed with the expected diff.
  - `test_inclement_preonset_attr_shape` (`:948-960`) is rewritten to the new exact dict (`floor`, `active`, `floor_from`, `buy_hours`, `event_time`, `event_time_source`, plus the existing keys). It now also asserts the attr is non-null at 4-12 h with `active: false`.
  - `test_part2_ec_hc_writeback.py`: add the four override keys to the key set (`:218`) and change the count `:374` from 104 to **108**.
- **Update with the expected diff:** `test_ec_stage_b_preonset_precharge.py:569-590` (`test_preonset_floor_none_outside_lead` now asserts `preonset_target` set and `preonset_floor` None at 4-12 h); every D-B6 test asserting `is_bottom_rate` buy timing moves to the schedule, and the parent gate parametrize gains "hour ∉ S" as a refusal.
- **Mutation:** per §4.3 row (target↔registered swap, seven drills); replace the schedule gate with `is_bottom_rate(now)` (repro RED); order by `(rank, H − now)` (closest-to-event RED); drop the eligibility-loss clear; early-return before the latch advance; plus the scheduler drills in §E2.2.
- **Live:**
  - When a future HOLD alert is 4-12 h ahead, `inclement_preonset` reads `{"active": false, "floor_from": "<T−4h or min(S)>", "buy_hours": [...]}`.
  - `reserve_write` rows carry no `tick_preonset_floor` before `floor_from`. A row earlier than that is a wrong reader (§4.3).
  - Event-gated: disposes on the first prepare alert.

### E3: hygiene carried in-cycle
- **Fetch timeouts (Review 1 F12):** wrap both `get_forecasts` calls (daily `weather_manager.py:414`, hourly `:903`) in `asyncio.timeout(FORECAST_FETCH_TIMEOUT_S)` (NEW rung 1, 20 s). Test `test_fetch_timeout_releases_refresh_lock[daily|hourly]`.
- **`number.py:1688-1695` docstring (F17):** the floor-lead / buy-horizon split.
- **Write-backs in the ship commit:**
  - parent §10 park entries (F10), §12 limits 21/23/25, §13 (`_event_matches_threat` deleted), INV-6(iii) amended by INV-9;
  - arc doc status rows;
  - this plan's completion tracking.

---

## 6. Knobs

| Knob | Rung | Default | Why / kill |
|---|---|---|---|
| `inclement_hold_added/_removed`, `inclement_buy_added/_removed` | 2 | empty | Operator chooses which alerts hold or buy. Empty = table defaults. Buy kill = `inclement_grid_precharge_on_hold` False. |
| `NWS_WEATHER_EVENT_NAMES` | 1 | weather subset of `alerts/types`, 2026-10-17 | Selectable vocabulary. Refreshed by reviewed change; the E0 test fails loudly. |
| E0 table rows | 1 | §E0 | Evidence-set. |
| `INCLEMENT_PREONSET_LEAD_H` | 1 | 12 (re-scoped: buy horizon) | How far ahead a buy may be scheduled. 0 = D-B6 off. |
| `INCLEMENT_PREONSET_FLOOR_LEAD_H` | 1 | 4 | Floor start before `T` when no buy is scheduled. One winter top-rate block. Effective value is `min(·, LEAD_H)`. 0 = floor only with a buy schedule. Rung 1: it prices peak arbitrage. |
| `INCLEMENT_GRID_CHARGE_PP_PER_H` | 1 | 50 | Operator: "charge from grid in 1-2 hours" (80 pp / 1.6 h). Below the 77 pp/h hardware ceiling. E2-P Q5 replaces it once an episode is measured. A smaller value schedules more hours. Rung 1: it sizes paid import. |
| `INCLEMENT_PREONSET_BUY_MARGIN_H` | 1 | 1 | Slack hour against rate or SOC error. 0 = exact. |
| `FORECAST_FETCH_TIMEOUT_S` | 1 | 20 | Fetch bound. |
| E2-P go/no-go thresholds (3 events, 12 h, 0 outages) | plan text | §E2-P | One-shot decision, not runtime. |

---

## 7. Non-goals
1. No change to class/tier semantics, locality, the polygon cap, forecast thresholds, the storm threshold or the precharge option.
2. No per-region default tables.
3. No forecast-timed hold unless E2-P is GO (then a separate increment). No warn deferral without an operator ruling.
4. No runtime fetch of the NWS vocabulary.
5. No translation of customized legacy substring lists.
6. No change to the full-hold or polygon buy legs' rate gates (in-window buys).
7. No "discharge then rebuy" (§E2.3, parked).
8. No change to the arbitrage engine, the governor, the overlay or write-verify. Arc steps 9-11, Stage D and EC-OBS-DP-EVSE-1 have their own cycles.

## 8. Tier, order and review
- **Tier 3.** Order:
  1. E2-P probe (offline, first).
  2. Golden capture on v5.103.69 (committed).
  3. Build E0+E1+E2+E3 on one branch with `ura-super-builder`.
- **Split option:** E2 as increment "E-b" (only `inclement.py` fusion/scheduler, the 7 readers and constants).
- **Build reviews** A/B/C/D per the parent's §9. D's target is INV-7, INV-8 and INV-9:
  - under every legal selection, including vocabulary extremes, `watch_requires_corroboration` {T, F}, and illegal stored combinations;
  - for the scheduler at TOU extremes: Onset inside a top block, Onset at 00:00, a DST night, the summer bracketed mid_peak, engine missing.
- Operator checkpoint before deploy.
- **Deploy risk MEDIUM:** buys stay off live; Freeze rows begin holding; the floor gets shorter.

---

## 9. Arc / spawned / dropped inventory (recommendations)

| # | Item | Source | Disposition | Why |
|---|---|---|---|---|
| 1 | NWS vocabulary drift | §0.1 | **Stage E (E0)** | Live freeze-hold gap. |
| 2 | Operator alert selection | EC-STORM-PRODUCT-SELECTION-EXTERNAL-1 | **Stage E (E1)** | Operator ask. |
| 3 | Pre-onset timing + cheapest-window buy | EC-STORM-PREONSET-TIMING-1 + ruling | **Stage E (E2)** | Operator ask and ruling. |
| 3b | Forecast-timed in-window hold | §0.3 | **Stage E (E2-P) decides; E2b on GO** | Measured this cycle, per Review 2. |
| 4 | Legacy plumbing | residual_2026_10_17_legacy_threat_list | **Stage E (E1.9)** | Same files. |
| 5 | `_event_matches_threat` | parent §13 | **Stage E** | Gate met (Validated table 377a7e3ed). |
| 6 | Fetch timeouts (B-LOW-5, daily + hourly) | parent §16 | **Stage E (E3)** | ~5 lines. |
| 7 | B-LOW-4 Storm Guard negative cache | parent §16 | **Drop** | Re-resolve runs only while the state is missing. |
| 8 | Arc step 8 (obs-mode bypass) | EC-OBSERVATION-MODE-RESERVE-BYPASS-1 (shipped_organic) | **Dispose now** (one query) | Organic lane is not a parking lot. |
| 9 | §12 limit 14 / B-LOW-1 (evaluate-path latch rollback) | parent §12 | **Check in the #8 disposition**; card a residual if not covered | Deferred to step 8. |
| 10 | Arc steps 9+10 | EC-TOU-TRANSITION-DOUBLE-CONSUME-1, EC-EVALUATE-PATH-LEDGER-GAP-1 | **Separate joint Tier-2 cycle next**, measure first | Arc rule. |
| 11 | Arc step 11 | EC-SELFHEAL-UNEXPLAINED-RESENDS-1 (waiting_operator) | **Separate cycle** on the operator answer | CRITICAL pages; own root cause. |
| 12 | Stage D | parent §8, Q8 | **Separate Tier-2 cycle** | Independent. |
| 13 | EV writes in obs mode | EC-OBS-DP-EVSE-1 | **Separate Tier-2 cycle**, paired with #9 | Same theme. |
| 14 | Arc step 1 governor | EC-RESERVE-WRITE-GOVERNOR-1 (shipped_organic) | **Dispose now**: one query over `reserve_write` rows since v5.103.66 (`floor_ok` never false with a floor registered) | Missed in Rev 1 (F-inv). |
| 15 | Parent card | EC-INCLEMENT-HARDENING-1 (shipped_organic v5.103.69) | **Close done-with-residuals at the Stage E ship**; residuals = rows 3b, 18, 19 | Missed in Rev 1. |
| 16 | `BLIND_RESPECT_MANUAL_LOWER` defects | parent §7 | **Park**; trigger: any proposal to set it True | Unreachable while False. |
| 17 | HOLD-CURRENT `_desired_stamped_at` | README v5.103.68 | **Park**; trigger: a redispatch gap traced to it | Only suppresses. |
| 18 | Sighted SOC-unknown full hold = slider 60 | README v5.103.68 | **Park**; trigger: an outage with SOC unknown at hold start | Rare. |
| 19 | Forecast thresholds unfitted | parent §16 | **Park**; trigger: 2027-03-31, one fit probe | No history. |
| 20 | Outage witness on islanding | parent §12 limit 17 | **Dispose on the first real outage** | Event-gated. |
| 21 | Review C equivalent mutant B19 | ec_stage_bc_review_C | **Drop** | Equivalent. |
| 22 | Grid pre-charge option turn-on | parent Live (e) | **Operator (OQ-4)**, after Stage E | Final table and schedule. |
| 23 | Q7 re-confirm | parent §14 | **Operator (OQ-5)**, default stands | — |
| 24 | §12 limits 15 / 25 / 26 | parent §12 | **Park**, existing triggers (25 restated in E2) | — |
| 25 | Polygon per-storm budget; Storm Guard down-time notice; NM for HOLD alerts | parent | **Park**, existing triggers | — |
| 26 | Parent §10: WIY promotion, convective/tropical eligibility | parent §10 | **Superseded by E1** (operator-selectable; defaults unchanged) | Review 1 F10. |
| 27 | Parent §10: pre-onset buy outside bottom rate | parent §10 | **Superseded by E2/INV-9** (higher rate only if unavoidable) | Operator ruling. |
| 28 | Parent §10: ledger table, memory persistence | parent §10 | **Park**, existing triggers | — |
| 29 | D-B5 field-removal unit test | parent §16 | **Stage E** (`test_legacy_plumbing_removed`) | F-inv. |
| 30 | EC-SOC-LADDER-FULL-WIRING-1 | parked card | **No action**; E2 doesn't fire its trigger (§E2) | Checked. |
| 31 | Full-hold degraded `envoy_available` | parent §16 | **Done** (95ecb7430) | — |
| 32 | Arc doc status rows | ARC doc | **Stage E ship commit** | — |
| 33 | v5.103.69 Validated table | CLAUDE.md | **Done** (377a7e3ed) | — |
| 34 | EC-ENPHASE-CONNECTIVITY-RESILIENCE-1 | outside arc | **Unchanged** | — |

---

## 10. Open operator questions (recommended default in bold)

| # | Question | Default |
|---|---|---|
| OQ-1 | Freeze Warning / Freeze Watch become watch: a partial hold on bottom-rate frost nights, **released at top rate** when the forecast is above 28 °F, and a full hold and buy only on a ≤ 28 °F forecast? | **Yes.** |
| OQ-2 | Two lists (hold; may buy ⊆ hold), NWS names only, added and widened alerts capped at partial hold and never corroborated? | **Yes.** |
| OQ-3 | (a) Event time = NWS Onset now, with the forecast-timed version decided by the E2-P probe this cycle (GO = ≥ 3 events with Onset ≥ 4 h ahead of the observed hazard, ≥ 12 top-rate hours saved, no outage missed). (b) If GO, apply it to **watches only**, or to warnings too (including Updates that re-stamp Onset to "now", e.g. a WSW re-stamped from 21:00 to 13:00 holding through the 17-21 block)? | (a) **Yes.** (b) **Watches only**; warnings need their own ruling after you see the probe numbers. |
| OQ-4 | Turn grid pre-charge on after Stage E ships? | **After Stage E.** |
| OQ-5 | Q7 (unverified polygon → notice) stands? | **Stands.** |
| OQ-6 | Grid charge rate = **50 pp/h** (your "1-2 h", 80 pp in ~1.6 h) plus a 1 h margin, so a typical 30 → 80 % top-up books **2 cheapest hours** just before the event. E2-P replaces it if a recorder episode exists. OK? | **Yes.** |
| OQ-7 | With grid buying off, hold the floor through the last top-rate block before the event (≤ 4 h, ≈ $1/event forgone discharge) rather than let the battery drain into the storm? | **Yes.** |

## 11. Changelog
| Rev | Date | Change |
|---|---|---|
| 1 | 2026-10-17 | Initial (6dd862d15): coordinator E1 critique, "not undone", E0 found, E2 4 h lead, inventory. |
| 3.1 | 2026-10-17 | Tidy: superseded Rev 2 text in INV-9, §E1.10 and §E2.2 deleted; §E2.2a merged into §E2.2; E2 acceptance and limit 23 aligned. No rule change. |
| 3 | 2026-10-17 | Re-checks folded: N1 buy ∩ corroborable, golden harness + scheduler-independent diffs, test-ref classification, sensor allowlist, row shape; scheduler slots incl. current hour, separate schedule dict + freeze point + discharge, Update = fresh ID, engine-missing no buy, SOC≥target empty S, UTC stepping, registered = target under buy, 5 drills. |
| 2 | 2026-10-17 | Both plan reviews folded (§12). Operator E2 ruling: cheapest-hours-before-event buy schedule (INV-9, amends INV-6(iii)), floor from the schedule start or `T − 4 h`, priced. Field split (target vs registered floor, 7 readers). Explicit `InclementSelection` threading to all 3 `match_product` callers, including the ledger. Corroborable cap on every leg. Runtime buy ⊆ hold. Selection domain excludes retired names. Golden: one capture point, projection, rule-generated diffs. E2b turned into the E2-P measure-first go/no-go. §0.3 rewritten. Inventory +8 rows. OQ-3 split, OQ-6 re-based on the operator's charge rate, OQ-7 new. |

---

## 12. Plan review fix-up (Rev 2)

R1 = `plan_review_ec_storm_stage_e_1_completeness.md` (af96d1ab7). R2 = `plan_review_ec_storm_stage_e_2_build_prediction.md` (951a5c708).

| ID | Sev | Plan change |
|---|---|---|
| R1-F1 / R2-C1 | CRIT | §E2.4 field split (`preonset_target` vs registered `preonset_floor`); §4.3 seven readers with the field each uses; an eighth reader stops the build; seven swap drills. |
| R2-C2 / R1-F6 | CRIT / MED | §E1.10: one capture point (v5.103.69 tag, committed script + fixture); named projection; full axes; rule-generated expected diff (E0 cells + E2 buy-schedule cells); INV-7(e) scoped to classification/hold/buy; prepare-floor timing moved to INV-8. |
| R1-F2 / R2-H3 (ledger) | HIGH | §4.1 ledger is the third caller; `record_tick(selection=…)` built in `energy.py`; `…_in_outage_ledger` test + drill. |
| R1-F3 / R2-H3 (threading) | HIGH | §E1.3 frozen `InclementSelection`, explicit parameter on `match_product`/`build_record`/`update_alert_memory`/`AlertClassifier`/ledger; no global; overlay rewrites `cls`/tier/`eligible`; memory admission test. |
| R1-F4 / R2-H2 | HIGH | §4.2 tier-level conjunct `any(r.corroborable for r in watch_records)`; mixed fixture; INV-7(f). |
| R2-H1 | HIGH | INV-7(c): the cap covers every leg including `watch_requires_corroboration=False`; tests parametrized; D target list. |
| R2-H4 / R1-F9 | HIGH / MED | `build_selection` runtime `∩ hold ∩ (family ∪ polygon)`; seeded-store test + drill. |
| R2-H5 | HIGH | §E1.2 selection domain = `table ∩ vocabulary` ∪ unlisted vocabulary; retired rows outside; real-flow "defaults → four empty lists" test. |
| R1-F5 | MED | INV-8(ii) + §E2.4 eligibility-loss clear; two tests. |
| R1-F7 / R2-M1 | MED | §E1.6 both key sets; two tests; two drills. |
| R1-F8 | MED | §E1.6 pop form keys, case-fold, out-of-vocabulary render filter, removed-row-becomes-unlisted; tests. |
| R1-F10 | MED | §E1.5 un-park stated; inventory rows 26/27; parent §10 write-back (E3). |
| R1-F11 | MED | Tests to update listed with expected diffs (E0, E1.9, E2). |
| R2-M2 | MED | §E2.4 multi-alert rule (gate on `pstart`, value from rows in the floor window, latch on `key_id`); two-alert fixture. |
| R2-M3 | MED | §E2.4 placement after purge/advance/`pre`; no early return; drill. |
| R2-M4 | MED | §E0 TOU-specific expectations incl. top-rate release (OQ-1 states it). |
| R2-M5 | MED | §E0 Freeze Watch is gated out today; name-only row; golden expected diff. |
| R2-M6 | MED | Widened notice rows are non-corroborable (INV-7(c)); repro (ii); test. |
| R1-F12 | LOW | Both daily and hourly fetches bounded (E3). |
| R1-F13 | LOW | FZA name-only; Cold Weather Advisory → apparent temp; vocabulary inclusions/exclusions listed; unlisted rows skip drift. |
| R1-F14 | LOW | §1a corrected (legacy value built, never passed); `_event_matches_threat` has 0 callers. |
| R1-F15 | LOW | Repair text re-pointed (E1.6). |
| R1-F16 | LOW | Error keys named with strings + translations (E1.1). |
| R1-F17 | LOW | `number.py` docstring (E3). |
| R2-L1 | LOW | Effective floor lead `min(floor, buy)`; parametrized test. |
| R2-L2 | LOW | Restart and obs-mode stated as non-guarantees in INV-8. |
| R2-L3 | LOW | Non-discriminating Live lines dropped or replaced (E1 Live, E2 Live). |
| R1 inventory misses | — | Rows 14, 15, 26-30 added; parent limits 21/23/25 restated in E2. |
| R2 mutation-authority gaps | — | Behavioural table-not-mutated drill; reader-side drills (§4.3); `∩ hold` drill; per-caller overlay drills. |
| R2 forecast-intersection pushback | — | Accepted: §0.3 rewritten; E2b became E2-P (measure-first, GO thresholds, this cycle); OQ-3 split with the re-stamp example. |

### Rev 3 re-check fix-up
R1b = completeness re-check (e7dce3ca4); R2b = build-prediction re-check (f5ed3810a). Both confirmed every Rev 2 mapping resolved.

| ID | Sev | Plan change |
|---|---|---|
| R1b-N1 | HIGH | INV-7(c) "never buys"; `build_selection` buy `∩ corroborable_names`; `buy_needs_table_hold` validation; tests `test_widened_prepare_never_buys`, `test_widened_buy_does_not_change_coactive_table_decision[req_true\|req_false]`; drill: drop `∩ corroborable`. |
| R1b-N2 / R2b-F8 | MED | §E1.10 Rev 3 harness: entry point, cell→times calendar, FakeTOU from the committed tariff, solar stub 0, fresh latch/schedule, pinned knobs. Prepare-cell buy and floor fields projected out of the golden; allowed diff = E0 products by name only (independent of the scheduler). Both directions of E2's buy change are pinned in a hand-written INV-9 case table. |
| R1b-N3 | MED | E2 acceptance: classify the ~45 `.preonset_floor` test refs before editing; attr-shape test rewritten; `test_part2` key set + count 104 → 108. |
| R1b-N4 | MED | E1.7: `sensor.py:9376-9393` allowlist + `test_inclement_state_sensor.py:35-48`. |
| R1b-N5 | LOW | E1.3: 5-tuple positions unchanged; `corroborable` returned separately; `AlertRecord.corroborable`. |
| R2b-F1 | HIGH | §E2.2.1 slots `[H, H+1h)` with `H+1h > now`; hh:30 test + drill. |
| R2b-F2 | HIGH | §E2.2.5 latch type unchanged; sibling `_preonset_buy_schedule` dict; one freeze point; readers; discharge on option-off / unconfirm before engagement and in obs mode; option re-enabled → fresh S. |
| R2b-F3 | MED | §E2.2.6 Update = new ID → fresh start, accepted (limit 23 class); honest new-ID test; hollow test withdrawn. |
| R2b-F4 | MED | §E2.2.3 engine missing → S = () (stated byte change); None rank excluded; tests. |
| R2b-F5 | MED | §E2.2.4 SOC None or ≥ target → S = (); margin only when buying; test + drill. |
| R2b-F6 | MED | §E2.2.2 UTC stepping, local ranking, `as_utc(T)`; DST + across-midnight tests. |
| R2b-F7 | MED | §E2.2.7 registered = target under INV-8(ii); window-class rule only under (i); fixture. |
| R2b-F9 | LOW | §E2.2.8 pinned shoulder answer, partial S, T on the hour. |
| R2b-F10 | — | Five drills (a)-(e) in §E2.2. |

**Rev 3 rejections:**
- None outright.
- R1b-N1's alternative (filter `_zone_buy_confirmed` on `r.corroborable`) is not taken. The reviewer preferred the selection-level cut, and it keeps the form honest.
- R2b-F3's carry-over option is declined, with the reason in §E2.2.6.
- R2b-F4: chose "engine missing → no buy" over the legacy fallback. It is stated as a byte change.

**Rev 2 rejections:** none. **Partially taken:** R1-F1's alternative `preonset_floor_active: bool`. I used a value split instead (`preonset_target` plus a nullable registered `preonset_floor`), so the six existing registered-floor readers keep their None-means-absent semantics without a second flag to forget.
