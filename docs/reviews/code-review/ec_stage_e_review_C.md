# EC storm Stage E — Review C (test authority via real per-site source mutation)

Branch `feature/ec-storm-stage-e`, code HEAD `f2001b333`, base `pre-review-ec-stage-e` (`fa7e1ffe2`).
Method: 211 independent single-site mutations of production source (I enumerated the sites from
`git diff pre-review-ec-stage-e..f2001b333 -- custom_components`, not from the builder's drill list). One
mutation at a time, transient edit and restore in one Python step, `-B` and `__pycache__` cleared before every run,
`git status` clean after each batch and at the end. Test set per drill (2134 tests, ~29 s): `test_ec_stage_e_*`,
`test_ec_stage_b_{classification,preonset_precharge,goldens}`, `test_ec_stage_c_hourly_outlook`,
`test_inclement_{alert_classifier,state_sensor,solar_horizon}`, `test_part2_ec_hc_writeback`, `test_cm_reload_suppression`,
`test_ec_outage_ledger`, `test_battery_inclement_{precedence,arbitrage_floor}`, `test_dpm_cleanup_and_labels`.
Baseline (no-op mutation): 2134 passed.

Result: 211 sites mutated, 168 RED, 43 SURVIVED. Of the 43: 21 are equivalent (proof given), 22 are real test gaps
(0 HIGH, 4 MEDIUM, 18 LOW). No survivor is a production bug; each MEDIUM is a missing test on a load-bearing INV-7/8/9 site.

## RED rows (site -> first failing test)

| Site group | Mutations (all RED) | Killing test (first) |
|---|---|---|
| build_selection: hold_removed/hold_added/buy_removed/buy_added consumption, `& hold`, `& corroborable`, `& family`, corroborable-set, casefold, unlisted/widened/overrides, vocab filter | S3,S4b,S5a,S5c,S6-S11,S14 | `test_ec_stage_e_selection.py::test_selection_overlay_applies_in_{build_record,classify}`, `test_runtime_buy_subset_of_hold_seeded_store`, `test_selection_casefold_and_unknown_names`, `test_widened_buy_does_not_change_coactive_table_decision` |
| form: defaults filters, deltas hold_added/hold_removed, validation errors buy_not_in_hold / buy_needs_forecast / buy_needs_table_hold | F1,F2,D1-D5 | `test_selection_stores_deltas_only_real_flow`, `test_selection_validation_buy_subset_of_hold`, `test_selection_validation_buy_needs_family`, `test_selection_form_keys_popped` |
| `_overlay` (retired passthrough, eligible, not-held default-hold class/corr/precharge, widened class/corr, held default eligible/corr), `match_product` (unlisted branch, synthetic row class/polygon/buy/corr, corroborable return, overlay skip), `build_record` (selection pass, corroborable), memory admission, classifier ctor + both calls, `active_alerts` | O1-O5,O7,O9-O11,M1-M5,B1,B2,U1,C1-C4,R1 | `test_selection_overlay_applies_*`, `test_widened_notice_not_corroborable[*]`, `test_unlisted_product_capped_partial_hold`, `test_ec_stage_b_preonset_precharge::test_polygon_topup_requires_eligible_row`, `test_preonset_in_window_hold_unchanged_golden` |
| fusion corroboration (4 legs + corr_ok), prepare `watch_confirmed` corroborable | X1-X5 | `test_widened_confirmed_watch_never_self_corroborates`, `test_widened_notice_not_corroborable[req_true/false]`, `test_widened_prepare_never_buys` |
| scheduler: purge, freeze-once, store, slot gate, current-slot inclusion, `<` vs `<=` T, rank-None exclusion, sort key (3 variants), take-h_req, sort-asc, except, local conversion, h_req (>=, None, ceil, margin), constants (PP/H x2, MARGIN x2, LEAD_H, FLOOR_LEAD x2) | P1,P9-P11,P13,P14,P32,H1,H2,H4-H9,Q1,Q1b,Q3,Q4,K1-K4b,A1,A2 | `test_schedule_frozen_while_soc_rises`, `test_buy_schedule_hand_table`, `test_schedule_unranked_hour_excluded`, `test_schedule_engine_missing_no_buy`, `test_preonset_floor_from_schedule_start` |
| eligibility-loss discharge (option off, unconfirm; latch + schedule + key_id guard), latch reached/engaged/solar, full_hold shadow | P2-P8,P15 | `test_preonset_floor_clears_on_eligibility_loss[unconfirm/option_off]`, `test_preonset_precharge_latch_no_flap`, `test_preonset_precharge_gates[solar_closes]`, `test_review_c_active_full_hold_shadows_prepare_fields` |
| registered-floor rule (ii) now>=min(S) (3 variants), starts[], (i) gate / precedence, eff_lead min/max, horizon_end, in_window filter, hi warn / watch-confirmed / value, floor_from min, replace() fields (target/floor/buy_hours/floor_from) | P16-P18b,P20-P30 | `test_preonset_floor_from_schedule_start`, `test_two_alerts_registered_*`, `test_schedule_soc_at_target_empty_no_floor`, `test_schedule_engine_missing_no_buy` |
| 7 preonset readers, target vs registered: slot gate, target-not-None gate, `reserve_level`, grid-buy stamp target, attr gate/floor/active/floor_from/buy_hours/event_time(_source), `_registered_floor` reader (+ partial max, allow_discharge), narration reader, `tick_preonset_floor` reader | B7-B19,E1,A14,A15 | `test_ec_stage_e_preonset_timing.py::test_preonset_field_split_readers`, `test_inclement_preonset_attr_shape`, `test_preonset_partial_hold_takes_max` |
| callers of selection: battery cfg / classifier / memory / fusion schedule arg / attr set + key, ledger (energy.py pass + build, ledger record_alerts + match_product) | B1-B3,B5,B6,B20,E3,E4,L1,L2 | `test_selection_overlay_applies_in_outage_ledger`, `test_inclement_selection_attr_shape`, `test_selection_remove_hold_is_notice_and_not_admitted` |
| observation-mode `_sched.clear()` | E2 | `test_schedule_cleared_every_observation_mode_tick` |
| E0: FZW row class/precharge, Freeze Watch row/precharge, family (3), apparent set, vocabulary (6) | V1-V9 | `test_zero_override_golden_identical_to_v5_103_69`, `test_freeze_watch_name_only_row`, `test_freeze_warning_watch_class_forecast_lift`, `test_vocab_snapshot_covers_table` |
| timeouts (daily, hourly), tiny constant | W1,W2,K5b | `test_ec_stage_e_hygiene.py::test_fetch_timeout_releases_refresh_lock[daily/hourly]` |
| allowlists: sensor attr, `_NO_LIVE_ATTR_KEYS` (2 probes), `OPTIONS_RELOAD_SUPPRESS_KEYS` (4 keys) | Z1-Z3d | `test_attributes_return_inclement_subset`, `test_selection_keys_in_{no_live_attr_keys,options_reload_suppress_keys}[*]` |
| config_flow: error set, deltas applied, form-key pops (x2), form defaults (x2) | G1,G2,G4,G5,G10,G11 | `test_selection_validation_buy_subset_of_hold`, `test_selection_stores_deltas_only_real_flow` |
| selection attr (display): level, gate (option_off/not_selected/forecast_confirmed), source (3), corroborable, overrides, exc swallow | A3-A5,A7-A9,A12,A13 | `test_inclement_selection_attr_shape` |

## SURVIVED rows

### Real gaps

| ID | Site | Mutation | SEV | Why it matters / repro | Recommended test |
|---|---|---|---|---|---|
| X6 | `inclement.py` `_apply_prepare` registered rule (i), `hi = any(r.corroborable and (...))` | drop `r.corroborable` | MEDIUM (INV-7(c), INV-8(i)) | Cold Weather Advisory widened to hold (family `freeze`, not corroborable), forecast-confirmed, Onset within 4 h, zero other prepare rows: target stays `lower` (X5 guard holds) but the mutant registers `max(lower, knob)` = 80 as the floor. X5 is killed, this sibling site is not. | Fusion-direct: widened CWA + `confirmed={id}`, option off, Onset +3 h: assert `preonset_floor == lower` (not knob). |
| H3b / H3 | `schedule_buy_hours` `if t_u - slot <= horizon` | `if True` / `<` | MEDIUM (INV-9 slot inclusion) | The horizon cut-off is untested. now=03:30, T=15:10 (11h40m ahead, inside the prepare window): slot 03:00 is 12h10m before T and must be excluded; mutant includes it. The `<=` boundary (slot exactly 12 h before T) is also unpinned. | Pure test: T-H = 12h exactly (included) and 12h+1s (excluded), with `now` mid-hour. |
| D6 | `selection_form_deltas` `CONF_INCLEMENT_BUY_ADDED` list | `[]` | MEDIUM (INV-7 authority) | Legal input: Tornado Watch (default hold, family, default buy False) in the buy field. No test asserts the stored `buy_added` delta, so an operator opt-in to buy could be silently dropped. | `selection_form_deltas(hold=default, buy=default+["Tornado Watch"])` -> `buy_added == ["Tornado Watch"]`, `error is None`. |
| D7 | same, `BUY_REMOVED` list | `if False` | MEDIUM (INV-7 authority) | Operator unticks Winter Storm Warning from buy; the delta is never stored, so the buy stays on against the operator's choice. Consumption (S8a) is tested; production of the delta is not. | Same function: buy=default minus "Winter Storm Warning" -> `buy_removed == ["Winter Storm Warning"]`. |
| G8/G9, G6b | `config_flow.py` absent-key defaults / guard | `[]`, `hold only` | LOW | A submit carrying only one of the two keys would wipe the other list (G8: hold -> `[]` -> every default hold lands in `hold_removed`). HA forms submit both defaults, so not reachable from the UI. | Real-flow test submitting only the buy key: stored overrides for hold unchanged. |
| G7, G12 | `config_flow.py` current-defaults source; selector options | data-only; `[:3]` | LOW | The real-flow test does not validate through the schema (selector options) and the options-vs-data merge is unpinned. | Assert `schema` options == vocabulary; defaults reflect stored options. |
| K5 | `FORECAST_FETCH_TIMEOUT_S` 20 -> 20000 | value | LOW | Hygiene tests patch the constant; the shipped value (which bounds the `_refresh_lock` hold) is not pinned. | `assert 0 < FORECAST_FETCH_TIMEOUT_S <= 30`. |
| P31 | `target = max(0, min(100, int(target)))` | clamp removed | LOW | `lower = max(reserve_soc, partial_floor)`; `partial_floor` is `int()` only, no clamp in the constructor. A partial floor > 100 stamps `reserve_level` > 100 ("clamp BEFORE stamp"). | Fusion-direct with `partial_hold_reserve_floor=120` and 0 extremes. |
| B4 / S13 / D8 | battery cfg `build_selection` try/except; `_names` str wrap; `_canon` vocab filter | removed | LOW | Defensive paths untested (string-valued stored option; garbage names reach stored deltas). | Unit tests for str input and unknown names in `selection_form_deltas`. |
| A3b, A6, A10, A11 | `_selection_attr` display: notice level, polygon_in/out_of_cap, `in_cap` computation, prepare records appended | removed | LOW (display only, E1.7) | The attr-shape test covers one fixture without notice rows, polygon rows or prepare-only records. | Extend `test_inclement_selection_attr_shape` with a polygon in/out-of-cap alert, a notice row, and a prepare-only alert. |
| Q5 | `preonset_slot` `as_utc` | removed | LOW | Equivalent in whole-hour-offset zones (US/Central), wrong in +05:30. Not reachable at this house. | Slot test under a half-hour-offset tz. |
| V10 | vocabulary list | drop "Flash Flood Watch" | LOW | Only table names + a few spot names are pinned; non-table vocabulary is not snapshot-tested. | Pin `len(NWS_WEATHER_EVENT_NAMES)` or a hash of the tuple. |

### Equivalent mutants (proof)

| ID | Mutation | Proof it is equivalent |
|---|---|---|
| S4a / S5b | drop `row[3]` polygon rows from `can_buy` / drop `& can_buy` | Enumerated the table at HEAD: every vocabulary row with default class warn/watch (the only rows in `corroborable`) is in `INCLEMENT_FORECAST_FAMILY`; the polygon rows (TOW, SVW, Extreme Wind) are all family members. The clamp is redundant today and bites only if a non-family hold row is added. This matches the builder's note. Dormant guard: recommend a monkeypatched-table test so the clamp is anchored. |
| D2b | forecast-error ignores polygon-row exemption | Same fact: no hold-class vocabulary row is polygon-only. |
| S12 | `setdefault` -> last-wins | No duplicate names in `INCLEMENT_PRODUCT_TABLE`. |
| S1 / S2 | drop `and cf in vocab` on default hold / buy | Adds only retired names (Hard Freeze/Wind Chill) to `sel.hold`/`sel.buy`; `_overlay` bypasses retired rows and every renderer filters by the vocabulary order. No observable behavior change. |
| S15 / D9 | `Mapping` guard / `build_selection(None)` | `None` is a zero-override input only via the guard, and the mutation D9 still has the guard. |
| O6 / O6b / O8 | not-held non-default row corroborable True / precharge `row[4]` / widened `polygon_local` False | Not-held non-default rows are notice rows: `row[4]` and `row[3]` are False for every notice row; notice-tier records never enter `hold_alerts`/`prepare_alerts` where `corroborable` is read. |
| G3 | deltas applied even when `errors` set | With `errors` non-empty the flow re-renders the form and does not save. |
| P12 | `stored = (hours, pstart, 0)` | `stored[1]` and `stored[2]` are never read (only `stored[0]`); the tuple's T/target fields are dead data (LOW: the docstring promises a `(S, T, target)` key that nothing compares). |
| P19 | `eff_lead > 0` guard | When `eff_lead == 0`, `fstart == pstart`, and a prepare record has `start > now` by construction so `_dt_le(fstart, now)` is never true. |
| H10 / H11 / H12 / H13 | `tou is None`, `event_time is None`, `h_req <= 0` guards; `max(0.0, horizon)` | Each failure falls into the `except Exception` (-> `()`) or an empty slice; output identical. |
| H4b | coerce rank None to 0 | Mutation left the `if rank is not None` guard in place (invalid mutant, equivalent). |
| Q2 / Q4b | `rate <= 0` guard; `max(0, margin)` | `INCLEMENT_GRID_CHARGE_PP_PER_H` = 50 and `..._MARGIN_H` = 1 are constants (never <= 0 / negative). Defensive only. |

## Findings

No HIGH. Four MEDIUM test gaps, all on INV-7/9 sites, all with a one-test fix; the production code at each site is correct
(each MEDIUM site was cross-checked by reading the surrounding logic and, for X6 and D6/D7, constructing the legal-input
repro above).

1. MEDIUM X6 — registered-floor `hi` corroborable guard unanchored (INV-7(c) via INV-8(i)).
2. MEDIUM H3b/H3 — scheduler horizon cut-off and boundary unanchored (INV-9).
3. MEDIUM D6 — `buy_added` delta production unanchored (INV-7 operator authority).
4. MEDIUM D7 — `buy_removed` delta production unanchored (INV-7 operator authority).
5. LOW — config_flow partial-submit / selector options / defaults source (G6b, G7, G8, G9, G12).
6. LOW — hygiene/clamp/defensive (K5, P31, B4, S13, D8, Q5, V10), dead `stored[1:]` (P12), selection-attr display branches (A3b, A6, A10, A11).

The builder's single reported equivalent (`& (family | polygon)` in `build_selection`) is confirmed equivalent and is one of
two fully-redundant clamp terms; I recommend one monkeypatched-table test so the clamp is mutation-anchored.

## Verdict: FIX-REQUIRED (test-only)

Add 4 tests (X6, H3b/H3, D6, D7) before ship; the LOWs may ride the same fix-up (1-30 LoC each). No production change is
needed. After the fix-up, re-run only the new tests' mutations (X6, H3b, H3, D6, D7).

Tree state: `git status` clean after every drill and at the end (transient scripts removed).
