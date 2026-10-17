# EC Stage B+C — Tier-3 Review D (adversarial completeness, diff-blind)

Branch `feature/ec-stage-b` @ 43b3a4845, base `pre-build-ec-stage-b` (88dd37aa0, Stage A = v5.103.68), three-dot diff.
Spec: `PLANNING_ec_storm_and_blind_decisions.md` Rev 3.5 §3, §6 Stage B/C, §16 deviations 1-5.
Targeted tests (6 files: preonset_precharge, classification, hourly_outlook, goldens, chokepoint lint, alert classifier): **1712 passed**.

## Surface re-enumeration (grep, not the builder's list)

- **CFG turn_on literals:** `energy_battery.py:7048` is the only battery-side `switch.turn_on` (inside `_result`). Every other match in `energy.py` and `energy_pool.py` is EVSE, plugs or pool. `force_redispatch` re-sends reserve only.
- **`_result(charge_from_grid=True)` sites:** `:4295` (arbitrage), `:5058` (attain), `:6260`/`:6277` (full-hold storm precharge), `:6318` (new D-B6 pre-onset). Pinned by the CFG lint.
- **Floor registration:** entry-reset `:5867`. Blind site `:5984`, sighted site `:6206`, both via `_registered_floor` (`:6744`). DP clamps at `:6687` and `:6728` key on `_tick_reserve_floor`. `_run_attain_branch` (`:6378`, `:6605`) runs after registration.
- **Zone-buy gates:** `inclement.py:1059` (warn), `:1131` (corroborated watch), `:987` (pre-onset). All go through `_zone_buy_confirmed` (`:916`), which requires eligible AND confirmed on the same record. Polygon records never enter `confirmed` (`energy_battery.py` `_forecast_confirmed_ids` skips `polygon_local`).
- **Every eligible zone product has a forecast family** (`energy_const.py:696-711` vs `:786-806`), so no eligible product is dead.

## Invariant checklist

| Invariant | Verdict | Evidence |
|---|---|---|
| INV-1: no reserve write below the registered floor (hold or pre-onset, sighted or blind) | PASS | Every reserve emit folds through `_reserve_action` with `_tick_reserve_floor`. `_registered_floor` gives max(hold, pre) for partial_hold and pre for allow_discharge. The pre-onset `_result` passes `preonset_floor` and folds the same way. A full_hold below a prepare floor is excluded by INV-6's scope (by design). |
| INV-6(vii): no zone grid buy without a forecast confirmation latched for the same eligible alert | PASS (decision) | All three zone legs use the per-record conjunct. Outlook None (never fetched, stale beyond `FORECAST_STALE_MIN`, no provider) → `forecast_confirms` False. Condition corroboration can promote a hold but never sets a buy. A new ID after an Update must re-confirm. The latch only counts IDs present in this tick's records, so a cancelled or left-feed ID cannot buy. RAM latches lost on restart fail toward no buy. |
| Arbitrage / attain interplay | PASS | Pre-onset yields to CHARGE or charging (`:6304-6305`). Their own buys stop code-side at `peak_buffer_target` (`:4067`, `:5297`, `:5507`). A folded reserve above the target overshoots by at most one tick (pre-existing behaviour, as with Stage A hold floors). |
| EVSE / force_redispatch | PASS | Reserve-only, max()-safe, composed from the folded stamp. |
| Ineligible products never buy | PASS | `_zone_buy_confirmed` requires `precharge_eligible`. The polygon leg requires `r.precharge_eligible` (`inclement.py:144`). |
| Polygon top-up capped per alert ID | PASS (as specified) | `inclement.py:141-152`: `[start, min(end, start+60)]`. An Update or new ID reopens the window, which the plan accepts in Rev 3.3 H1. A memory-replayed polygon alert is bounded by the same cap. |
| Option off ⇒ Stage A byte-identical on non-new paths | PASS for buy paths | Each buy conjunct short-circuits on the option. `_polygon_import_guard_tripped` reads nothing when the option is off. See L-2 for the forecast-corroboration exception. |

## Findings

**MEDIUM-1: a pre-onset buy reports `inclement_buy_forecast.confirmed = False`, so the plan's own INV-6(vii) falsifier fires on a legal buy.** Bug class: coincidental-equality / display-vs-decision split (#63-adjacent).
- `inclement.py:1005-1013`: `_apply_prepare` returns `replace(base, ...)` without setting `buy_forecast_confirmed`. That field is set only in `_decide_hold`, so on an allow_discharge or partial_hold base it stays False.
- `energy_battery.py` `_stage_b_attrs` → `buy.confirmed = decision.buy_forecast_confirmed`.
- Repro (fusion direct, run): reserve 20, partial floor 50, knob 80, option True, Winter Storm Warning `w1` with Onset +6 h, bottom rate, SOC 40, `confirmed={"w1"}`. Result: `allow_discharge 80 preonset_precharge=True buy_forecast_confirmed=False`. CFG turns on while the attr reads not confirmed.
- §3 falsifier: "a zone-product charge_from_grid turn_on on a tick whose `inclement_buy_forecast` attr reads not confirmed". Live validation (e) would report a false INV-6(vii) violation. Worse, a reader learns to ignore that attr, which masks a real violation later.
- The grid-buy NM stamp hardcodes `forecast_confirmed: True` for pre-onset (`_grid_buy_stamp`), so the two surfaces also disagree with each other.
- Fix: set `buy_forecast_confirmed=self._zone_buy_confirmed(prows, confirmed)` in the `_apply_prepare` replace, or OR it into the attr.

**LOW-1: the grid-buy NM and the D-B6 "engaged" latch are not gated by observation mode or by the dispatch outcome.** Bug class #23 (observation-mode gating).
- `energy.py:6462-6467` run after `determine_mode` (`:6414`) and before the observation gate (`:6621`).
- In observation mode, `_tick_grid_buy` still triggers "URA started grid-charging the battery" with nothing dispatched. The same false message appears when the breaker-safety chokepoint strips the turn_on.
- `energy_battery.py:6310` sets the latch to `"engaged"` before dispatch, so later ticks skip the solar test.
- Neither affects the forecast or eligibility gates. Fix: gate the NM on `not self._observation_mode` and on the turn_on actually being dispatched.

**LOW-2 (tracked limit, informational): the new CFG site inherits EC-OBSERVATION-MODE-RESERVE-BYPASS-1.**
- `_evaluate_battery` (`energy.py:7194`) dispatches on TOU transitions regardless of observation mode.
- The transition into bottom rate is exactly when a zone buy begins. With observation mode on and the option on, the pre-onset turn_on can dispatch.
- The full-hold zone leg has the same exposure (pre-existing, §12 limit 14). Not must-fix: the option defaults off and the card exists.

**LOW-3 (by design, stated for the operator): forecast confirmation corroborates a watch even with the option off.**
- `inclement.py:1088-1095` changes a watch's hold depth or floor on non-buy paths, so option-off is not byte-identical to Stage A for watches. Neither is D-B1-D-B4 classification.
- This matches D-C2 ("raise-only corroboration"). It does not change any buy.

**LOW-4 (display): the zone-leg NM key can name the wrong alert.**
- `_grid_buy_stamp` picks the first eligible non-polygon hold record, not necessarily the confirmed one that justified the buy.
- The NM text and dedup key can name the wrong alert. Display only.

## Cleared hypotheses (holds because…)
- **Stale or never-fetched outlook:** `hourly_outlook` returns None when no provider is fresh and healthy, or when no slot is covered (`weather_manager.py:916-925`, `:959`).
- **Provider horizon shorter than the window:** confirmation uses only the covered hours (BACKUP policy, D-C1). Partial coverage confirms on real forecast hours only.
- **Cancel or ID churn:** `update_alert_memory` rules 2 and 3. The forecast latch counts only IDs in this tick's records.
- **Blind:** pre-onset needs a known SOC, `_precharge_refused_on_blind` refuses, and the full-hold leg needs a known SOC.
- **CFG left on after the buy condition ends:** every non-CFG `_result` emits the OFF direction (`energy_battery.py:~7055`).

## Verdict

**SHIP-with-fix: FIX-REQUIRED on MEDIUM-1 only** (a one-line field set plus a test asserting `buy_forecast_confirmed` on a pre-onset buy decision). No decision-path leak was found in INV-1 or INV-6(vii). LOW-1 is recommended in-cycle (fix LOWs policy). LOW-2, LOW-3 and LOW-4 are informational.
