# EC storm Stage E — Tier-3 Review A (local correctness)

Branch `feature/ec-storm-stage-e` @ f2001b333; base `pre-review-ec-stage-e` = fa7e1ffe2 (verified: it is the merge-base; `git diff v5.103.69 pre-review-ec-stage-e -- custom_components` is empty, so the golden was captured on a v5.103.69-identical tree).

**Verdict: SHIP.** No CRITICAL, HIGH or MEDIUM findings. There are 3 LOW/INFO items, all optional.

## Verified (holds because ...)

| Area | Evidence |
|---|---|
| `preonset_h_req` | Driven directly: None→0, SOC=target→0, 79.9/80→2 (ceil+margin), 30/80→2, 0/100→3. The margin is added only when a buy is needed (`inclement.py` preonset_h_req). |
| `schedule_buy_hours` | Driven against the real `TOURateEngine` (America/Chicago). Winter WSW 21:00, SOC 30 @06:00 → {15:00,16:00} (the plan's repro). Shoulder Oct → {15,16}. DST fall-back night 22:00→06:00 → 3 distinct UTC slots {03,04,05 CST}, none skipped or repeated. Midnight-spanning 22:30→04:00 → {01,02,03}. Current slot included (20:20, T 21:00 → {20:00}, a top-rate slot used only because nothing else exists). `period_rank` None → excluded. `tou=None`, `h_req<=0` or T None → (). Ordering `(rank, T−H)`, then sorted ascending. |
| Overlay byte-identity | Every `INCLEMENT_PRODUCT_TABLE` row: `_overlay(row, build_selection({})) == row`. No duplicate names. Retired rows (Hard Freeze*, Wind Chill*) take the out-of-vocab passthrough, so their `row[4]=True` survives even though they are absent from `sel.buy`. |
| Buy ⊆ hold ∩ (family ∪ polygon) ∩ corroborable | `build_selection` clamps at runtime. `selection_form_deltas` validates at the form (`buy_not_in_hold` → `buy_needs_forecast` → `buy_needs_table_hold`). Widened Cold Weather Advisory (family, notice) passes the forecast check and fails table_hold, which is correct. Unlisted names get the synthetic `(None, ev, "watch", False, False)` row with corroborable=False. |
| Case-folding / stale names | Stored names are case-folded against the vocab and canonicalised. Out-of-vocab names are ignored (one debug log per name). Deltas are recomputed against the CURRENT table defaults on each save (overrides, not a snapshot). The form never renders a non-vocab value. |
| Selection threading | All `match_product` / `build_record` / `AlertClassifier` / `update_alert_memory` callers pass the selection (grep: `inclement.py:541,620,709,716`, `energy_outage_ledger.py:278`, `energy_battery.py:2752,2756`). |
| Field split (`preonset_target` vs registered `preonset_floor`) | The readers are correct: the tick floor (`energy_battery.py:6937`) and narration (`:7155`) read the REGISTERED floor. The buy emission (`:6447-6483`) and attrs read the target. A buy slot implies `now ≥ min(S)` → registered = target, so the emitted reserve equals the registered floor. |
| INV-8 registered rule | (ii) is checked first (`hours[0] ≤ now`, hours sorted). (i) runs only when (ii) did not register, uses `eff_lead = min(FLOOR_LEAD_H, LEAD_H)`, and `eff_lead=0` → no (i). Eligibility loss pops the schedule BEFORE `stored` is read, so (ii) cannot survive option-off or an unconfirm. |
| Corroboration caps (4.2) | Every leg is ANDed with `corr_ok`. A watch that is unlisted or widened only, with `requires=False`, falls to the uncorroborated branch, which is ≤ partial_hold (INV-7(c)). |
| E0 rows / family / apparent set | Freeze Warning `("FZW", …, "watch", False, True)` and Freeze Watch `(None, …, "watch", False, True)` are both in the freeze family. Cold Weather Advisory is notice + family + `FORECAST_APPARENT_TEMP_PRODUCTS`. Matches plan §E0. |
| Golden | `compare()` asserts the allowed diff is exactly {Freeze Warning, Freeze Watch}. Prepare-cell buy/floor fields are projected out per §E1.10. |
| strings / translations | Labels, descriptions and the 3 error keys are identical in strings.json and en.json. Legacy `warn_min_severity` / `power_threat_events` labels are removed. |
| Fetch timeouts | Both `get_forecasts` calls are wrapped in `asyncio.timeout(20)`. `asyncio` is imported (`weather_manager.py:18`). TimeoutError is caught by the existing `except Exception` → that provider fails this pass. |

## Builder deviations — adjudicated

- **Dev 1 (selection=None → build from the current table): ACCEPT.** The result is byte-identical (overlay identity above), and the cost is trivial (about 31 rows per call). If `build_selection` raises in the battery, the code falls back to table defaults. That is the conservative direction: an operator removal is ignored, so the house holds more, not less.
- **Dev 3 (error keys under `options.error`): ACCEPT.** HA resolves options-flow errors as `component.<domain>.options.error.<key>`. The repo already pins this location (`quality/tests/test_cycle_b_config_flow.py:1097`, `test_hvac_presence_timer_knobs.py:436`, `test_v473_baseline_preset_editor.py:389`). The step-level `error` dict used by older keys is the non-resolving outlier. It predates this cycle and is out of scope.
- **Dev 6 (the forecast leg requires the confirmed record itself to be corroborable): ACCEPT, required.** Under the plan's literal "ANDed with any(corroborable)", the following state is legal: a co-active unconfirmed table watch plus a widened Cold Weather Advisory confirmed on apparent temp. Then `forecast_corroborates = True` and `corr_ok = True`, so the widened record would corroborate the table watch into a full hold. That violates INV-7(c) ("never counts toward watch corroboration on any leg"). The builder's form closes the gap.

## Findings

| # | Sev | Site | Finding | Bug class |
|---|---|---|---|---|
| A-LOW-1 | LOW | `inclement.py` `_apply_prepare` freeze block (`stored = (hours, pstart, target)`) | An EMPTY S is frozen. If `schedule_buy_hours` returns () because the engine raised transiently, or because no slot was ranked at the freeze tick, that alert ID never re-schedules: there is no buy for the alert's life, and the floor falls back to INV-8(i). This is plan-literal (§E2.2 rules 3+5), and the option is off live. Suggested fix: freeze only a non-empty S, or freeze () only for the static `tou is None` case. | Suppression without discharge (transient → permanent) |
| A-LOW-2 | LOW | `config_flow.py:6174-6188` + form defaults at `:6437` | On a validation error the form re-renders with the STORED effective lists (`selection_form_defaults(entry)`), not the operator's submission, so the operator's edit is lost. UX only; nothing is stored. | — |
| A-INFO-1 | INFO | `_preonset_buy_schedule` tuple `(S, T, target)` | `stored[1]` and `stored[2]` are never read. If the target rises after the freeze (a watch becomes confirmed, so lower → knob), `h_req` stays sized for the old target, while the emission uses the current target. This follows the plan's freeze design (drill (a)) and is accepted. The margin hour absorbs some of it. | Coincidental-equality watch (#63), documented |

None blocks ship.
