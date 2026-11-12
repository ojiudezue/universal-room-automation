# PLANNING: EV rung-1 redirect cap + post-pause latch hold

Card: `EV-ARBITRAGE-RUNG1-WAIT-OSCILLATION-1` (Tier 3, `approval: explicit`, operator 2026-11-12 "Go on fix D plan").
Source analysis: `docs/planning/AUDIT_ev_rung1_oscillation_fix_options.md` (shape D).
Plan reviews: `docs/reviews/code-review/PLAN_ev_rung1_redirect_cap_review_1.md` (completeness) and `_review_2.md`
(adversarial build-prediction). Both returned REVISE. This is **revision 2**; §10 maps every finding to its fix.
Operator answers to the open questions are recorded in §9.

Operator constraints (card `refinement_2026_11_12`, `operator_decision_2026_11_12c`):
1. Protect overnight off-peak EV charging.
2. No new machinery on hardened code.
3. Grid-charge intent must always still pause the EVs (breaker invariant).

---

## 0. Institutional context verified

### 0.1 Docs read

| Doc | Read | Relevance |
|---|---|---|
| `CLAUDE.md` Tier 3 rules | full section | Four review framings, falsifiable invariant up front, config-extreme testing, orchestrator mutation re-run, operator checkpoint before deploy |
| `docs/Coordinator/ENERGY_COORDINATOR_MANUAL.md` | §2.2-2.3 (l.70-100), rung/gate attrs row l.399, changelog l.779 | WAIT parks at the drain floor and never grid-charges; rung 1 cannot start at night. No contradiction with code. |
| `docs/planning/AUDIT_ev_rung1_oscillation_fix_options.md` | full | Mechanism, Q1/Q2, shapes A-D, recommendation D, cap-only fallback |
| `docs/planning/PLANNING_arbitrage_solar_attainability_ladder.md` | skim (l.9-145) | Original rung-1 design. Its l.68 defines the credit as the full `ev_load_w`, which is the defect fixed here. Its l.72 ruling (no new kW threshold) is honoured. |
| `docs/planning/PLANNING_ec_daylight_horizon_and_poor_night_floor.md` | review table l.280-292 | Its **F6** (the post-sunrise residual: a grid-fed EV at sunrise still enters rung_1) is **closed by D1**; see D5 write-back. |
| `docs/planning/DESIGN_ec_degraded_data_policy.md` §9.1/9.3 | via card | 10-01 replay: rung_1 entered with EV ≥ 11.6 kW 13/13, WAIT entered with EV off 34/34 |
| HVAC / presence state-of-play docs | not read | Out of domain (energy classifier + EV pool only) |

Memory bodies consulted: `project_ev_drain_precedence_cycle` (Path A untouched), `project_charge_onset_correct_site`
(onset untouched), `feedback_marginal_benefit_pushback`, `feedback_measure_before_build`, `feedback_hollow_test_anchors`.

### 0.2 Line-number re-verification (develop `64ef3740`, reviews ran on `b109d3d8`; energy files unchanged between them)

No audit cite has drifted: `energy_battery.py:265` K=3, `:300`, `:4060-4093` `_effective_import_kw`, `:4217-4221` credit,
`:4308-4312` night release, `:4322` solar collapse, `:4333-4376` counterfactual, `:4377-4389` escalation, `:4413-4472`
entry (latch `:4464`, snapshot `:4468`), `:4479-4542` `_gate_is_open`. `energy.py:8179-8209` pause-reason + breaker
ordering. `energy_pool.py:3091-3140` pause branch.

### 0.3 REUSE-or-BUILD per piece

| Piece | Verdict | Evidence |
|---|---|---|
| Non-battery grid import (kW) | **REUSED** `_effective_import_kw()[0]` | `energy_battery.py:4060-4093`. `battery_power_w` is already freshness-gated (`:2436-2460`); its None means no subtraction, so the import is larger and the credit smaller (conservative). |
| `net_power` freshness gate at the cap only | **REUSED** `_read_fresh_power_w("net_power", DEFAULT_NET_POWER_MAX_AGE_S)` | Wrapper `energy_battery.py:2493-2520`; constant `energy_const.py:551` (180 s, rung 1). Gate only; the `net_power_w` producer stays ungated (MED-2, `energy_const.py:545-550`). Operator accepted (Q1). |
| EV draw | **REUSED** `ev_load_w` from `current_charging_load_w()` | `energy_pool.py:3013-3039`, threaded via `_tick_ev_load_w` (`energy_battery.py:6448`, `:4528`) |
| kW → %/h conversion | **REUSED** `:4217-4221` | same capacity and fallback |
| Hold length | **REUSED** `ATTAIN_RATE_WINDOW_TICKS` through the sampler trim `:5029` | no new number |
| Latch entry timestamp | **NEW** `_arb_rung1_latched_at: datetime \| None` | grep of the energy files for `latched_at` / `rung1_.*_at`: none. The rate window stores `(datetime, soc)`, so the hold needs the entry `now`. |
| Redirect-credit diagnostic | **NEW** `_arb_last_redirectable_kw: float \| None` + attr `arb_rung1_redirectable_kw` | no equivalent attr at `:8383-8387` |
| Kill switch / enable flag / CONF / entity / signal | **NONE** | grep `RUNG1_ENABLED\|rung1_enabled\|redirect_cap\|redirectable`: no hits |
| Regression trip-wire | **REUSED** EC-EV-TOGGLE-TRIPWIRE-1 | `energy.py:8702-8724`, `energy_const.py:758-776`; notify stays off (operator Q3) |
| Duplicate-sampling fix | **NOT HERE**, own card `EC-ATTAIN-RATE-DUP-SAMPLE-1` (`kanban.data.yaml:34380`) | operator Q4 |

### 0.4 Measure-before-build

The gating measurement exists: the audit's recorder replay of 11-08 20:03-20:33Z (net import 12.9-14.7 kW with EVs on,
2.4-3.5 kW paused, solar 0.8-1.9 kW, SOC flat 30 %) and DESIGN §9.1 for 10-01 (17.7 kW with EV on vs 5-6 kW off, night).
Every recorded rung-1 episode had `ev_kw ≤ effective_import_kw` at entry. No new probe.

### 0.5 Config-first check

No setting fixes this (audit l.64-66). The defect is in the producer arithmetic.

---

## 1. Falsifiable invariants

**INV-1 (entry honesty).** `_classify_attain_rung` newly sets `_arb_rung1_latch = True` only if, on that tick, `net_power`
is present and fresh (**unless the freshness kill switch `DEFAULT_NET_POWER_MAX_AGE_S <= 0`, in which case freshness is
not checked; this is a documented, legal config**) and `ev_load_kw > effective_import_kw`. The %/h credit added and
snapshotted never exceeds `clamp(ev_load_kw − effective_import_kw, 0, ev_load_kw) / capacity × 100`.
*Break it with:* any reachable inputs where the latch is set with `ev_load_kw ≤ effective_import_kw`, with net_power
None, with net_power stale while max_age > 0, or where `_arb_last_ev_load_pct_per_h` differs from the entry credit.

**INV-2 (no lag-driven escalation).** While latched, the `projected_rung0 < exit_band` escalation (`:4382`) does not fire
while `_attain_soc_history[0][0] < _arb_rung1_latched_at`. Night release `:4308`, solar collapse `:4322`,
counterfactual-to-rung_0 `:4366` and forecast-closed `:4519` stay ungated. **Consequence (bounded):** a held tick
returns rung_1, so the forecast gate stays closed and arbitrage CHARGE cannot start that tick. D2 therefore delays an
arbitrage CHARGE by at most the hold (INV-3). The attain branch still runs on held ticks and can command grid; if it
does, `grid_charge_intent` makes the pause `breaker` (INV-4).

**INV-3 (bounded hold).** The hold ends at the first tick whose window's oldest sample is at or after the entry tick.
On the production path (`determine_mode`, arbitrage enabled), rung_0/rung_1 ticks are always double-sampled
(classifier `:4174` + attain branch `:6008`, gate closed so `:7221` runs), so the hold is **one tick (N+1), and the
flush tick is N+2** (rate over N→N+2, 10 min). Classifier-direct harnesses single-sample, so they hold N+1 and N+2
and flush at **N+3**. In both regimes the hold never exceeds `ATTAIN_RATE_WINDOW_TICKS` ticks carrying a valid SOC.
*Break it with:* a sequence where `hist[0] < latched_at` after K valid post-entry appends.

**INV-4 (breaker unchanged).** For every tick with `grid_charge_intent` True or phase CHARGE, `pause_reason == "breaker"`
and the pause is dispatched before the battery actions (`energy.py:8185-8209`), whatever the rung, latch or cap.

**INV-5 (overnight untouched).** Outside daylight (`:4248-4252`), the rung, `_arbitrage_intent`, gate outcome, and the EV and
battery actions are identical to develop for the same inputs. **Scope:** display values may differ. On a cap-zero tick
`arb_projection_rung1` becomes None where develop showed a number (`:4424-4431` vs `:4462`), and D3's new attribute exists.

**Observable consequence:** under 11-08 / 10-01 (grid-fed) conditions no garage EVSE shows an arbitrage-owned off→on→off.

**Stated residual (real path).** A *genuine* entry (EV partly solar-fed) whose post-flush rate still projects below
`exit_band` escalates at N+2 (EVs released), and if the next tick re-enters on the same live conditions, the EVs go off
again at N+3: worst case off→on→off within 3 ticks (15 min), instead of 2 ticks on develop. The post-flush decision on
the real path uses a 10-min, all-post-pause window of whole-percent Envoy SOC. A genuine 5 kW redirect into 40 kWh is
+12.5 %/h, about +2 % over 10 min, so quantisation can flip the decision. That is accepted (operator Q4 option a): the window
is all post-pause, which is the point of D2. Widening it to K is `EC-ATTAIN-RATE-DUP-SAMPLE-1`. The trip-wire records
the residual and D-alt (§8) is the remedy.

**Restart (R2-F9).** `_arb_rung1_latch` is not restored (init `:936`, single writer). After restart latch=False and
`latched_at=None`, which is consistent. **Do not add persistence for `_arb_rung1_latched_at`**; that would create a
timestamp-without-latch state.

---

## 2. Producer / consumer map

### 2.1 Producers

| Value | Producer | Arithmetic | Dependency health |
|---|---|---|---|
| `ev_load_w` | `current_charging_load_w()` `energy_pool.py:3013` | Σ power over charging EVSEs; estimate fallback only when status reads charging (`energy_pool.py:1150-1155`, `:4776-4779`) | Healthy on 11-08 (10.1-11.7 kW) |
| `effective_import_kw` | `_effective_import_kw()` `:4060` | `net_w − max(0, batt_w)` in kW; None if net None | `net_power_w` not freshness-gated (intentional); D1 gates locally |
| `redirectable_kw` (local) | D1 | `clamp(ev − imp, 0, ev)`; 0 if snapshot None or net stale | 11-08 20:03: `10.1 − 12.9 < 0 → 0` |
| `ev_load_pct_per_h` | `:4221` via D1 | `redirectable_kw / capacity × 100` | |
| `_arb_rung1_latch` | set `:4464`; cleared `:4312/4323/4369/4383/4520` | | only writer verified by both reviews |
| `_arb_last_ev_load_pct_per_h` | set `:4468` (capped credit); cleared `:4311/4328/4372/4385` | | read only `:4333` |
| `_arb_rung1_latched_at` (NEW) | set at `:4464` | `= now` | read only inside the latched branch |
| `_arb_last_redirectable_kw` (NEW) | set only in the **unlatched entry evaluation** (after the rung-0 block, before `:4424`); `__init__` None; per-tick reset beside `_arbitrage_intent = None` at `:6424` | | None on every tick that did not reach the entry evaluation (latched, rung_0, forecast-closed, peak, early returns) |
| `_attain_soc_history` | `_record_attain_sample` `:5014`, called `:4174` and `:6008` | trim to K+1; cleared `:5796`, `energy.py:12125` | **Always double-sampled on rung_0/rung_1 ticks** with arbitrage on (gate closed → attain branch `:7221`). Rung_2 ticks sample once. The `:4170-4173` "idempotent" comment is wrong (D5 fixes the comment only). |
| `_arbitrage_intent` | `_gate_is_open` `:4521/4532/4536/4540`; entry-reset `:6424` | `"redirect"` iff rung_1 | |

### 2.2 Consumers (re-enumerated by both reviewers; matches)

| Site | Reads | Trust/display | Changed? |
|---|---|---|---|
| `energy_battery.py:4166` | rung cache | trust | no |
| `:4309-4312` | latch (night) | trust | no |
| `:4319-4393` | latch, snapshot | trust | **D2 at `:4382`** |
| `:4413-4472` | credit | trust | **D1** |
| `:4519-4520`, `:4530-4542` | latch clear, rung → intent | trust | no |
| `:7203` / `:7221` | gate outcome → arbitrage decision vs attain branch | trust | no (but D2 can hold rung_1 one tick longer, see INV-2) |
| `:7250-7266` | `closed_rung_1`, projection | display | no |
| `:8383-8387` | rung/intent/projection attrs | display | **D3 adds one attr** |
| `energy.py:8179-8195` | intent → pause_reason | **trust, only EV-switching consumer** | no |
| `energy_pool.py:3091-3140`, `:3143+`, `:3353` | pause / release / label | trust / display | no |

**EV emission sites changed: zero.**

---

## 3. Config-extreme / knob-inversion cases (each becomes a test)

`imp` = `effective_import_kw`, `ev` = `ev_load_kw`. N = entry tick. "Prod" = `determine_mode`-driven; "direct" = classifier-only.

| # | Case | Expected under fix |
|---|---|---|
| 1 | 11-08: ev 10.1, net 12.9, batt 0, solar 1.2, SOC 30, target 90 | rung_2, no latch, redirectable 0 |
| 2 | ev < imp (3 vs 5) | rung_2 |
| 3 | daylight, solar ≈ 0 | rung_2 (`:4415` or cap 0) |
| 4 | net_power unavailable | rung_2 |
| 5 | net_power stale (> 180 s), frozen at −2 kW, EV grid-fed | rung_2. **Positive control:** same inputs with a fresh stamp → rung_1 |
| 5b | max_age = 0 (kill switch), same frozen value | rung_1 (INV-1 carve-out documented, not a leak) |
| 6 | exporting (net −3, ev 7) | full credit 7 kW |
| 7 | EV kW unknown → estimate | credit bounded by estimate error |
| 8 | two EVs (6 + 5), net 8 | credit 3 kW; redirect pauses both |
| 9 | battery discharging 5 kW above the floor, ev 10, house 2, solar 1 → net 6 | credit 4 kW (discharge avoided). The entry tick is gate-closed (not WAIT), so the battery can be discharging above the floor; the credit is the correct SOC effect (operator Q2: keep) |
| 10 | battery_power None/stale | imp = net → smaller credit |
| 11 | duplicate samples | hold ends on timestamp: prod flush N+2, direct flush N+3 |
| 12 | SOC None while latched | `:4176` rung_2 (develop) |
| 13 | window cleared mid-latch | `:4203` rung_2 (develop); after reseed all samples post-entry → flushed |
| 14 | target ≤ SOC while latched | `:4187` rung_2 HOLD (develop) |
| 15 | target extremes 30 / 100 | cap still applies |
| 16 | night | rung/intent/actions identical (INV-5 scope) |
| 17 | grid-charge intent with rung_1 latched | `breaker`, dispatched before the CFG write |
| 18 | `latched_at` None while latched | treated as flushed → develop behaviour |
| 19 | genuine redirect: ev 7, net 2, pre-pause rate below exit, post-pause rate high | prod: rung_1 at N+1 (held) and at N+2 (flushed, rate ≥ exit); direct: held N+1, N+2, rung_1 at N+3 |
| 20 | genuine entry, post-pause rate flat | prod: rung_1 at N+1, **rung_2 exactly at N+2**; direct: rung_1 at N+1/N+2, **rung_2 exactly at N+3** |
| 21 | **CHARGE window opens during the hold** (`arbitrage_charge_lead_time` puts window open at N+1; entry at N; rate flat) | prod: N+1 held rung_1 → gate closed, no arbitrage CHARGE, phase `solar_attain`; N+2 flush → rung_2 → gate open → CHARGE, `breaker` pause before the CFG turn_on. CHARGE delayed by exactly one tick. Develop: CHARGE at N+1. If the attain branch commands grid at N+1, pause_reason is `breaker`. |

---

## 4. Deliverables

### D1: Cap the rung-1 entry credit (producer fix)

At `:4220-4221`:

```
ev_load_kw = max(0.0, float(ev_load_w or 0.0)) / 1000.0
redirectable_kw = 0.0
if ev_load_kw > 0.0 and self._read_fresh_power_w("net_power", DEFAULT_NET_POWER_MAX_AGE_S) is not None:
    snap = self._effective_import_kw()
    if snap is not None:
        redirectable_kw = min(ev_load_kw, max(0.0, ev_load_kw - snap[0]))
ev_load_pct_per_h = (redirectable_kw / capacity_kwh) * 100.0
```

- The existing `ev_load_pct_per_h <= 0.0` short-circuit (`:4424`) turns a zero credit into rung_2.
- `:4468` already snapshots `ev_load_pct_per_h`, so the counterfactual at `:4349` subtracts the capped credit. No edit there.
- Both reads are in one synchronous call, so they see the same HA state.
- Do not touch `net_power_w` (`:2591`) or `_effective_import_kw`.

**Fixture stamping (R2-F5).** `_state_age_s` uses `dt_util.utcnow()` (`energy_battery.py:109`), i.e. wall clock, not tick
`now`. Every D1/D4 fixture must stamp `net_power` relative to wall clock, which is the default `MockState` stamping
(`quality/tests/conftest.py:221-240`). **Never stamp `net_power` with the synthetic replay time.** Only the stale test sets an
old stamp (wall clock − 600 s), and it must carry the positive control (case 5).

**Existing-fixture behaviour (R2-F4, corrected).**
- `test_arbitrage_solar_attainability_ladder.py`: `_build_strategy` sets net 0 W, batt −200 W (`:218-219`, also `:1102-1103`), fresh.
  So imp = 0 and credit = ev. **Expected: these rung-1 tests stay GREEN with the credit unchanged.** Do NOT change
  `_build_strategy` defaults (that would shift the breaker guard and every other `net_power_w` reader in the file). New cap tests
  set `net_power` per test. Consequence: M1 is caught only by the new D1 tests, which is expected.
- `test_ec_daylight_horizon_poor_night_floor.py`: `_make` maps `net_power` to `_NET` (`:171`) but never sets its state (only
  the replay at `:995` does). So net is None and **every rung-1 entry in this file goes to rung_2 after D1.** Affected tests that
  expect a rung_1 entry or a latch taken through `_classify`: `:263` `test_flap_shape_legacy_sunset_only_bound_latches_rung1`,
  `:380` `test_rung1_counterfactual_site_daylight_gated`, `:413` `test_night_releases_carried_rung1_latch`, `:427`
  `test_night_carried_rung1_latch_full_determine_mode`, `:467` `test_night_both_latches_rung1_released_rung0_kept`, `:491`
  `test_daylight_carried_rung1_latch_still_held`, `:522` `test_rung1_counterfactual_site_daylight_value`, `:568`
  `test_rung1_post_sunrise_ev_draw_documented`. The builder runs the file, lists every red by name, and for each one either
  (a) adds a per-test fresh `net_power` that makes the EV solar-fed (the test's subject is not the credit), or
  (b) converts it (the test's subject is the credit). **`:568` is case (b):** convert it to assert `rung_2` for the grid-fed
  sunrise case, rename it `test_rung1_post_sunrise_grid_fed_ev_no_entry` (F6 closed by the cap), and add a solar-fed
  variant asserting rung_1. Tests that set the latch directly (not through `_classify`) should stay green; if one doesn't, STOP and report.
- `test_arbitrage_completed_chunk_hold_precedence.py`: no rung_1 assertions (grep), so no churn is expected.
- No assertion may be weakened. Every changed test is listed in the review record with its before/after fixture.

#### Acceptance criteria
- **Verify:** 11-08 20:03Z replay (ev 10100 W, net 12900 W fresh, batt 0, SOC 30, target 90, daylight) → rung_2, latch False, intent `breaker`.
- **Verify (discriminating):** develop gives rung_1 on the same inputs. Post-fix rung_1 means the cap is not wired. Rung_0 means the fixture is wrong (rung 0 must fail at 32.8 %). Rung_2 caused by staleness is excluded by the case-5 positive control and by asserting `strat._arb_last_redirectable_kw == 0.0` (not None).
- **Test:** `test_rung1_cap_1108_replay_grid_fed_ev_no_entry`, `test_rung1_cap_ev_below_import`, `test_rung1_cap_net_power_none_no_entry`, `test_rung1_cap_net_power_stale_no_entry_with_fresh_control`, `test_rung1_cap_kill_switch_zero_trusts_value`, `test_rung1_cap_export_full_credit`, `test_rung1_cap_two_evs_summed`, `test_rung1_cap_battery_power_none_conservative`, `test_rung1_cap_battery_discharge_credit`, `test_rung1_cap_snapshot_equals_entry_credit`, `test_rung1_post_sunrise_grid_fed_ev_no_entry`, `test_rung1_post_sunrise_solar_fed_ev_enters`.
- **Mutation:** M1 `redirectable_kw` → `ev_load_kw` in the pct line: the 1108 replay and ev-below-import tests go RED. M2 delete the freshness gate: the stale test goes RED (its fresh control stays green). M3 treat a None snapshot as 0 import: the net-none test goes RED.

### D2: Hold the rung-1 latch until the rate window is all post-pause

1. `__init__` beside `:936`: `self._arb_rung1_latched_at: datetime | None = None`.
2. At `:4464`: `self._arb_rung1_latched_at = now` (only writer).
3. At `:4382`:
   ```
   _hist = self._attain_soc_history
   _latched_at = self._arb_rung1_latched_at
   window_flushed = _latched_at is None or (bool(_hist) and _hist[0][0] >= _latched_at)
   if window_flushed and projected_rung0 < exit_band:
       ...existing escalation body unchanged...
   ```
   Not flushed: fall through to the existing rung_1 return at `:4390`.
4. No clearing at the latch-clear sites. The value is read only under latch=True, and the only latch set overwrites it.
5. `>=` because the entry tick's sample is taken before the pause is dispatched, so a window starting at N measures only post-pause intervals.
6. Hold length is defined by timestamps, not counts. Expected flush: **prod N+2, direct N+3** (INV-3).

#### Acceptance criteria
- **Test (pins the boundary and M5, prod path, R2-F2):** `test_rung1_hold_flat_rate_escalates_exactly_at_flush_prod` drives `determine_mode` tick by tick (arbitrage enabled, gate closed on rung ticks so the attain branch double-samples). Case 20: asserts `rung_1` at N+1 and **`rung_2` at exactly N+2**, plus the EV release action at N+2.
- **Test (direct harness):** `test_rung1_hold_flat_rate_escalates_exactly_at_flush_direct`: classifier-only, `rung_1` at N+1 and N+2, **`rung_2` exactly at N+3**.
- **Test (M4 precondition + legacy control, R2-F3):** `test_rung1_hold_held_tick_below_exit_band` asserts at N+1, before the rung check, `strat._arb_last_projection_rung0 < target - ARB_LADDER_EXIT_HYSTERESIS_PCT`, then asserts `rung_1`. Control in the same test: identical sequence with `_arb_rung1_latched_at` forced to None after entry → `rung_2` at N+1 (develop behaviour).
- **Test:** `test_rung1_hold_genuine_redirect_no_flap_prod` (case 19, exact ticks per INV-3), `test_rung1_hold_charge_window_opens_during_hold` (case 21: no arbitrage CHARGE at N+1, CHARGE + `breaker` pause before CFG at N+2), `test_rung1_hold_does_not_gate_night_release`, `test_rung1_hold_does_not_gate_solar_collapse`, `test_rung1_hold_does_not_gate_counterfactual_rung0`, `test_rung1_hold_window_cleared_midlatch`, `test_rung1_hold_latched_at_none_legacy`.
- **Mutation:** M4 force `window_flushed = True` → `test_rung1_hold_held_tick_below_exit_band` goes RED (its precondition guarantees the held tick is discriminating). M5 `>=` → `>` → `test_rung1_hold_flat_rate_escalates_exactly_at_flush_prod` goes RED (rung_1 at N+2 instead of rung_2), and so does the direct variant at N+3. M6 apply the guard to the solar-collapse exit → the solar-collapse test goes RED.

### D3: Observability (display only)

- `__init__`: `self._arb_last_redirectable_kw: float | None = None`.
- Per-tick entry-reset beside `self._arbitrage_intent = None` at `:6424` (`determine_mode`'s first-statement reset block): `self._arb_last_redirectable_kw = None`.
- Stamp it **only in the unlatched entry evaluation** (after the rung-0 block, immediately before `:4424`): `= round(redirectable_kw, 2)`.
- Attr `arb_rung1_redirectable_kw` beside `arb_projection_rung1` at `:8387`.

**Semantics:** a float on ticks that evaluated rung-1 entry (0.0 = grid-fed, no entry). None on every other tick: latched,
rung_0, forecast-closed, peak, early returns, fresh boot. `arb_projection_rung1` becomes None on cap-zero ticks where develop
showed a number (display change, see INV-5).

#### Acceptance criteria
- **Sensor:** `sensor.ura_energy_coordinator_battery_strategy` has `arb_rung1_redirectable_kw`. It is None on a fresh boot with the forecast gate closed (no AttributeError).
- **Test:** `test_rung1_redirectable_kw_none_on_boot_gate_closed`, `test_rung1_redirectable_kw_reset_on_peak_tick` (set on an entry tick, then a peak tick → None), `test_rung1_redirectable_kw_none_while_latched`, `test_rung1_redirectable_kw_value_on_entry_tick`.

### D4: End-to-end replays + config-extreme suite

New file `quality/tests/test_ev_rung1_redirect_cap.py`. It drives `determine_mode` → `_gate_is_open` → the `energy.py`
pause-reason derivation → `determine_arbitrage_actions` with the real pool (no fake coordinator). `net_power` is stamped at wall clock (D1).

- **11-08 replay (14:03-14:33 CST, 7 ticks, two garage EVSEs):** zero arbitrage-owned `switch.turn_off` before the window opens at 14:30, then the `breaker` pause dispatched before the CFG turn_on. Develop reproduces 3 off / 3 on.
- **10-01 replay (01:00-03:00 CDT, night):** compare **rung, `_arbitrage_intent`, gate outcome, EV and battery actions** with develop. Do NOT compare the full attr dict (INV-5 scope). Daylight-shifted variant with import 17.7 kW: no entry. The existing `test_replay_2026_10_01_no_rung1_flap` (`test_ec_daylight_horizon_poor_night_floor.py:1063`) must stay green unchanged.
- **Genuine redirect (case 19) and CHARGE-during-hold (case 21):** see D2.
- **Breaker matrix (INV-4):** {latched unflushed, latched flushed, cap 0, no latch} × {grid_charge_intent True, phase CHARGE} → `breaker`, pause ordered before CFG (reuse the `test_breaker_pause_ordering_*` pattern).
- **Config extremes:** cases 14, 15.

#### Acceptance criteria
- **Test:** `test_replay_1108_no_arbitrage_toggle_before_charge`, `test_replay_1001_night_rung_intent_actions_identical`, `test_replay_1001_daylight_grid_fed_no_entry`, `test_breaker_always_pauses_matrix`, `test_target_extremes_cap_holds`.
- **Mutation:** M1 and M4 re-run against the replay tests; the 1108 replay must go RED under M1.
- **Verify:** suite name-diff against `pre-review-<version>` shows only the D1-listed churn, all green.

### D5: Doc write-back (same commit)

- `ENERGY_COORDINATOR_MANUAL.md` l.399: rung 1 credits only EV draw not covered by grid import (fresh net_power required); a rung-1 pause is held until the rate window is all post-pause (about one tick on the live path). Changelog row near l.779.
- `PLANNING_ec_daylight_horizon_and_poor_night_floor.md` review table F6 row: append "**Resolved** by EV-ARBITRAGE-RUNG1-WAIT-OSCILLATION-1 (rung-1 redirect cap): a grid-fed EV at sunrise gets zero credit; test converted."
- `energy_const.py:545-550` comment: add the third reader of `DEFAULT_NET_POWER_MAX_AGE_S` (the rung-1 entry gate in `_classify_attain_rung`, gate only; the `net_power_w` producer stays ungated).
- Code comments: `:4127-4130` (rung_1 semantics), `:4377-4381` (the "rate already reflects" claim is wrong until the window flushes), `:4170-4173` (sampling is NOT idempotent; rung_0/1 ticks double-sample; see EC-ATTAIN-RATE-DUP-SAMPLE-1). Comment only, no behaviour change.

### Live criteria (post-deploy; feed the README validation table)

- **Live 1 (binary, disposition query):** `ura_activity_log` `energy_pool` `charger_off` rows with `pause_owners` containing `arbitrage` in daylight where the strategy row at that tick has `arbitrage_intent = redirect`. PASS = each has `arb_rung1_redirectable_kw > 0` at its entry tick and recorder `net_power` < EV power, or there are no such rows. FAIL = a redirect pause with redirectable 0/None or net ≥ EV draw. Another owner flapping shows a non-arbitrage `pause_owners` and does not confound this check.
- **Live 2:** the attribute `arb_rung1_redirectable_kw` is present after restart (None or float, no error in logs).
- **Live 3 (operator Q3, no paging):** at disposition, run an explicit query on the URA anomaly table for `ev_toggle_tripwire` rows with an arbitrage owner since deploy. PASS = 0 rows. If any exist, classify each: stated residual (redirectable > 0 at entry, period ≥ 3 ticks) or a cap leak (redirectable 0 or grid-fed).
- **Live 4 (overnight):** first poor-forecast night after deploy: no `redirect` pause rows 01:00-07:00 (as on develop).
- Disposition: at the first poor-forecast daytime with an EV drawing, or after about 1 week. If the precondition doesn't recur, close as "met by replay" with the trip-wire query as the standing guard.

---

## 5. Numbers and knobs

| Number | Source | Rung | Why |
|---|---|---|---|
| Hold length | `ATTAIN_RATE_WINDOW_TICKS` (`:265`) via sampler trim | existing module const | Defined by the window; changing K moves smoothing and hold together |
| net_power freshness | `DEFAULT_NET_POWER_MAX_AGE_S` 180 s (`energy_const.py:551`) | existing rung 1 | Same Envoy threshold as D-OBS/CostTracker. `<= 0` disables the gate at this new reader too (INV-1 carve-out); the comment is updated in D5 |
| Clamp bounds 0 / ev | physical | not knobs | |

No new number. No new kill switch. `ARB_LADDER_RUNG1_ENABLED` is added only if D-alt is invoked (§8).

---

## 6. Non-goals

- Daytime EV policy (solar-led vs off-peak) is out of scope.
- No change to `energy.py:8179-8209`, `determine_arbitrage_actions` or its release branch, the `_paused_by_*` peers, fill_priority, drain Path A, onset, `net_power_w`, or `_effective_import_kw`.
- No blanket arbitrage-active EV pause (A); no tuned hold timer (C).
- **No sampler dedupe.** This cycle accepts the real-path hold (operator Q4, option a). Dedupe is `EC-ATTAIN-RATE-DUP-SAMPLE-1`.
- No trip-wire paging change (operator Q3).
- No restart persistence for the new attributes.
- No change to rung 0, attain, WAIT floor, or the daylight horizon.

---

## 7. Tier classification

**Tier 3** (arbitrage rung state machine driving EV emission, breaker-adjacent, multi-fix-up history). Done: two plan
reviews (this revision answers both). Next: operator plan approval → `ura-super-builder` → four build reviews
(A arithmetic / B state machine incl. case 21 CHARGE delay, night identity, no-op byte-identity / C mutation M1-M6 /
D adversarial completeness vs INV-1..5 with legal-config repros) → orchestrator mutation re-run → operator checkpoint
before deploy. PATCH bump.

Marginal-benefit note on D2: D1 alone removes every recorded (grid-fed) episode. Once D1 removes the false entries, only
genuine entries remain, and those are what the `:4382` lag flaps. On the real path D2 holds one tick, so it costs one
attribute and one condition and delays CHARGE by at most one tick. I keep recommending D1 + D2.

---

## 8. Fallbacks

1. **Cap alone** (D1 + D3 + D4 minus D2 tests) if the operator rejects D2. Park D2 with revival trigger: an arbitrage-owner trip-wire row whose entry tick had `arb_rung1_redirectable_kw > 0`.
2. **D-alt (retire rung 1)** via `ARB_LADDER_RUNG1_ENABLED = False` (module constant, rung 1) if, after ship, a redirect with `redirectable_kw > 0` gains nothing over the flushed window. Separate cycle.

---

## 9. Operator answers (2026-11-12)

- **Q1 freshness gate:** accepted, with wall-clock fixture stamping + positive control (D1) and the INV-1 max_age ≤ 0 carve-out + `energy_const.py` comment (D5).
- **Q2 discharge credit:** keep; wording fixed (case 9).
- **Q3 trip-wire paging:** no paging; Live 3 is an explicit anomaly-table query at disposition.
- **Q4 duplicate sampling:** option (a). Accept the real-path hold (flush N+2, ~10 min window), stated for both harnesses; dedupe stays on `EC-ATTAIN-RATE-DUP-SAMPLE-1`.

---

## 10. Plan review disposition

| Finding | Sev | Fix in this revision |
|---|---|---|
| R1-F1 dup sampling makes hold ~2 ticks; Q4 load-bearing | HIGH | Option (a). INV-3 restated: prod flush N+2, direct N+3; §1 residual recomputed (3 ticks, quantisation noted); §2.1 "always double-sampled"; D5 fixes the `:4170` comment; dedupe → EC-ATTAIN-RATE-DUP-SAMPLE-1 |
| R1-F2 D2 can delay arbitrage CHARGE | MED | INV-2 states the bound (≤ hold = 1 tick prod); case 21; `test_rung1_hold_charge_window_opens_during_hold`; attain-branch grid on held tick → `breaker` (INV-4) |
| R1-F3 `:568` documentation test; F6 closed; churn set vague | MED | D1 names `:568` and converts it to rung_2 + solar-fed variant; full affected-test list per file; D5 marks F6 resolved |
| R1-F4 D3 stash semantics vs AC | LOW | D3: init None, reset at `:6424`, stamped only in the unlatched entry evaluation; semantics + 4 tests |
| R1-F5 INV-5 too broad | LOW | INV-5 scoped to rung/intent/gate outcome/actions; display change stated |
| R1-F6 Q2 "moot in WAIT" wrong | LOW | Case 9 reworded (entry tick is gate-closed; discharge possible above the floor) |
| R2-F1 hold is 1 tick in prod | HIGH | Same as R1-F1: hold N+1, flush N+2 prod; both harnesses specified; exact-tick prod test required |
| R2-F2 M5 hollow against case 19 | HIGH | M5 re-targeted at the flat-rate exact-flush tests (prod N+2, direct N+3), asserting rung_2 exactly at the flush tick |
| R2-F3 M4 hollow without precondition | MED | `test_rung1_hold_held_tick_below_exit_band` asserts the below-exit precondition + legacy control (latched_at None → rung_2) |
| R2-F4 churn prediction wrong | MED | Corrected: ladder-file tests stay green (net 0, batt −200); `_build_strategy` defaults untouched; −1000 W instruction removed; M1 caught by new tests only |
| R2-F5 freshness uses wall clock | MED | D1 fixture-stamping rule (wall clock, never replay time); stale test has a fresh positive control; entry asserts `redirectable == 0.0` to tell cap-zero from stale |
| R2-F6 D3 attr init/reset/semantics | MED | Same as R1-F4 |
| R2-F7 INV-1 vs max_age ≤ 0 | LOW | INV-1 carve-out; case 5b + test; D5 updates `energy_const.py:545-550` |
| R2-F8 INV-5 display shift | LOW | Same as R1-F5; 10-01 replay compares rung/intent/actions only |
| R2-F9 restart path | LOW | §1 restart note: no persistence needed or allowed for `latched_at` |
