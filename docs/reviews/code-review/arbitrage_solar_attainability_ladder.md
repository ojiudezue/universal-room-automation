# Code Review Ledger — Arbitrage Solar-Attainability 3-Rung Ladder

**Branch:** `feature/arbitrage-solar-attainability-ladder` (forked from `develop` @ `24951a8`)
**Planning doc:** `docs/planning/PLANNING_arbitrage_solar_attainability_ladder.md`
**Tier:** 2-DB (operator-elevated — battery↔grid↔cost↔EV ripple + breaker-safety invariant).

---

## Build notes (filled by ura-builder)

### Interpretation of the rung-1 re-entrancy hazard (operator brief, mandatory)

The brief explicitly governs over the plan text on the rung-1 EXIT condition.
Implementation honors the **counterfactual** exit mechanism verbatim:

- While `_arb_rung1_latch=True`, the rung-1 evaluation in `_classify_attain_rung`
  computes a counterfactual projection as
  `soc + (rate - assumed_ev_pct + solar_surplus) * hours`. The `rate` is the
  CURRENT observed K-tick net rate (which reflects the EVs being paused, so
  is artificially inflated). Adding the EV load back on the consumption side
  (subtracting `assumed_ev_pct` from rate) answers the question "if we
  resumed the EVs now, would solar STILL attain?". Only when that
  counterfactual passes `target + ENTRY_HYSTERESIS_PCT` is the latch
  released. This mirrors v5.3.8's entry-vs-exit asymmetry on the attain
  HOLD; it is the same self-referential-rate trap that took four fix-ups to
  kill, and it is closed here at build time, not deferred to review fix-up.
- The `assumed_ev_pct` is **captured at LATCH ENTRY** (`_arb_last_ev_load_pct_per_h`)
  rather than re-read from the live accessor — because while paused, the
  live accessor reads ~0 (correctly), and the counterfactual needs a stable
  assumed load.
- A second escalation branch covers solar collapse mid-latch: when even the
  "EVs-paused" projection falls below `target - EXIT_HYSTERESIS_PCT`, the
  rung-1 latch releases UPWARD to rung-2 (gate opens, label flips to
  `"breaker"`, EVs stay paused for compound-load protection).
- **Critical ordering inside the classifier:** when `_arb_rung1_latch=True`,
  the rung-1 counterfactual is evaluated FIRST — before the rung-0 entry
  predicate would otherwise be consulted. Otherwise the inflated observed
  `rate` (EVs paused) would satisfy a naive rung-0 entry and resume the EVs
  spuriously. The oscillation test `T_OSC` would fail this ordering.

### Files touched + line counts (against develop @ `24951a8`)

| File | Lines changed |
|---|---|
| `custom_components/universal_room_automation/domain_coordinators/energy_battery.py` | +~250 / −15 (new constants, `_classify_attain_rung`, updated `_gate_is_open`, init fields, `determine_mode` kwarg + stash) |
| `custom_components/universal_room_automation/domain_coordinators/energy_pool.py` | +~80 / −10 (new `current_charging_load_w()`, `_arbitrage_pause_reason` side-map, `pause_reason` arg + assertion + fail-closed default, `paused_by_arbitrage_reasons` status attr) |
| `custom_components/universal_room_automation/domain_coordinators/energy.py` | +20 / −3 (compute ev_load_w, thread into `determine_mode`, derive `pause_reason` from `_arbitrage_intent` and route to `determine_arbitrage_actions`) |
| `quality/tests/test_arbitrage_solar_attainability_ladder.py` | +~600 NEW (21 tests across 6 classes) |

### No new CONF / sensor / entity / signal

Per the parsimonious-config rule. Observability rides:
- existing `arbitrage_phase` and `reason` on the strategy sensor (no schema change);
- NEW attribute `paused_by_arbitrage_reasons` on the existing EV
  diagnostic sensor (per-EVSE dict of `"redirect" | "breaker"`);
- internal diagnostics `_arb_last_rung`, `_arb_last_projection_rung0`,
  `_arb_last_projection_rung1` on `BatteryStrategy` (RAM-only, surfaced
  via `get_status` follow-up if desired — not gated by this cycle's DoD).

### Breaker-safety invariant — assertion site

`EVChargerController.determine_arbitrage_actions` is the single chokepoint:

- When `arbitrage_charging=True` and `pause_reason=None` (legacy caller, or
  caller failed to compute intent), the method **fails CLOSED to "breaker"**:
  the EVs are paused for compound-load protection by default. A warning
  is logged so the caller-side migration is visible in URA logs.
- When `pause_reason` is provided and is not `"redirect" | "breaker"`,
  the method raises `AssertionError` — the test `test_bad_pause_reason_rejected`
  pins this.
- `EnergyCoordinator` derives `pause_reason` from `decision["arbitrage_phase"]
  == ARBITRAGE_PHASE_CHARGE` (force "breaker") OR `_arbitrage_intent ==
  "redirect"`. The "force breaker on CHARGE" overrides any disagreement
  with the strategy's `_arbitrage_intent` — defense in depth.
- `effective_import_kw`/load None paths are unchanged from v4.5.0.2;
  the existing grid-import guard at `energy_battery.py:_get_arbitrage_phase`
  still aborts a chunk when the panel approaches the configured cap.

### No 4th pause-owner set; v4.7.28 carry-over unaffected

Rung labels live on `_arbitrage_pause_reason`. Set membership remains
`_paused_by_arbitrage` so the off_peak ensure-on carry-over guard at
`energy_pool.py:518-526` continues to gate both `"redirect"` and
`"breaker"` identically. Verified by `TestV47_28CarryOver`.

### Composition with v5.3.8 attain

`_gate_is_open` returning False due to rung-0 narrowing does NOT bypass
the v5.3.8 attain branch — that branch lives on the post-gate fallback
path in `determine_mode` (~`:2273+`) and runs whether the gate is False by
forecast or by rung-0 narrowing. Verified by `TestComposition`.

### Mutation evidence (≥1 named test per mutation)

| Mutation | Mutation applied | Test(s) that fail |
|---|---|---|
| M1: invert rung-0 entry predicate (`>=` → `<`) | `projected_rung0 >= entry_band` → `<` | 11 tests incl. `test_rung_0_live_incident_shape`, `test_rung_0_latch_no_flap_around_target`, `test_rung_2_falls_through_to_charge`, `test_rung_0_does_not_bypass_attain_path` |
| M2: break rung-1 ENTRY EV-load uplift | drop `+ ev_load_pct_per_h` from entry projection | `test_rung_1_evs_eating_solar`, `test_oscillation_t_osc_rung_1_stable_across_5_ticks`, `test_rung_1_to_rung_0_when_solar_surges` |
| M3: break rung-1 EXIT counterfactual add-back (re-entrancy fix) | drop `- assumed_ev_pct` from counterfactual | `test_oscillation_t_osc_rung_1_stable_across_5_ticks` (named OSCILLATION test) |
| M4: flip rung-1 label assignment | `_arbitrage_intent = "redirect"` → `"breaker"` | `test_rung_1_evs_eating_solar` |
| M5: remove no-solar short-circuit | predicate → `if False` | `test_no_solar_short_circuit` |
| M6: remove breaker fail-closed default | drop `pause_reason = "breaker"` default branch | `test_default_pause_reason_is_breaker_fail_closed` |

The OSCILLATION test (M3 target) drives 5 consecutive ticks with `ev_load_w=0`
(EVs paused) and inflated observed rate (+10%/h) — without the
counterfactual exit, the naive observed projection (≥83) would release
the latch on tick 1 and we'd see rung_0 → resume → re-pause churn. With
the counterfactual, the projection reads `(10 - 14 + ~3) * 5 = -5` →
keeps latched at rung_1 across all 5 ticks. `charge_from_grid` is never
commanded along this path (rung-1 keeps the gate closed).

### Tests + test discipline

- 21 new tests in `quality/tests/test_arbitrage_solar_attainability_ladder.py`.
- Drives REAL `BatteryStrategy.determine_mode` + `_classify_attain_rung`
  + `EVChargerController.determine_arbitrage_actions`. No hand-mutated
  `_paused_by_arbitrage`, `_arbitrage_pause_reason`, `_arbitrage_intent`,
  `_arb_rung0_latch`, `_arb_rung1_latch`, or `_attain_state` to fake a
  state the production code can't reach.
- sys.modules `setdefault` + coexisting with sibling test files.
- Real `energy_const.py` constants and real `TOURateEngine`.
- 13.5/100 kWh battery capacity sensor seeded; `sun.sun` seeded with
  06:00/20:30 daylight; Solcast remaining/today/tomorrow seeded for the
  v5.3.8 projection math.

### EVSE follow-up notes (deferred from this cycle, per CLAUDE.md
"Plan completion tracking")

- The `_arb_last_*` diagnostic snapshots are RAM-only. Promoting them to
  the strategy `get_status()` dict and surfacing on the existing battery
  strategy sensor as `arb_rung_last`, `arb_projection_rung0`,
  `arb_projection_rung1` is a tiny follow-up (no schema change). Not in
  this cycle's plan deliverables.
- README/live-validation write-back happens at deploy time per CLAUDE.md
  (this branch is build-only).

### DoD verification

- `py_compile` clean: `python3 -c "import ast; ast.parse(...)"` PASS on
  all three modified production files.
- Conflict markers: none (grep clean).
- Cycle tests solo: 21/21 passed.
- Cycle tests + full sibling set + reverse-order: 228/228 passed.
- Baseline failure diff vs `develop` @ `24951a8`:
  - Baseline: 34 failed, 14 errors (48 named non-passing IDs).
  - Post-build: 34 failed, 14 errors, +21 new tests passing (5766 total
    pass vs 5745 baseline). ZERO new failures.

### Plan deviations

- The plan suggested adding a `current_charging_load_w()` accessor and
  passing `ev_load_w` "as an argument" to the strategy. Implemented as
  `determine_mode(..., ev_load_w=...)` plus internal stash on
  `self._tick_ev_load_w` so the existing nested call paths
  (`_get_arbitrage_phase` calls `_gate_is_open` again) all observe the
  same tick value. Cleaner than threading a new positional through
  ~3 internal call sites.
- `ARB_LADDER_DEFAULT_BATTERY_KWH = 13.5` was added (one Encharge unit
  equivalent) as a fallback when `_battery_capacity_kwh()` returns None.
  Mirrors the "fail toward charging" bias of the v5.3.8 attain math
  (small denominator → larger ev_pct_per_h, more likely to satisfy
  rung-1 entry). Not strictly in the plan; required for the rung-1 EV
  load → %/h conversion to have a definition when the capacity entity
  is briefly unavailable.

---

## Review A — Gate / projection correctness + no-flap

**Framing:** gate/projection correctness + no-flap (the re-entrancy trap). Reviewer: ura-reviewer (A). Commit `85309a3`.

### Verification done
- Re-ran cycle suite: 21/21 pass.
- Independently re-ran the oscillation mutation (dropped `- assumed_ev_pct` from the counterfactual at `energy_battery.py:891`): `test_oscillation_t_osc_rung_1_stable_across_5_ticks` FAILS at tick 1 (`rung_0` spurious resume, assumed_pct=14.00). Re-entrancy fix is genuinely test-guarded. Restored.

### Findings

**A-HIGH-1 — 13.5 kWh default mis-scales EV-load %/h by ~3x; diverges from the canonical 40 kWh fallback. (bug-class: stale/incorrect data source #7 + magic-constant drift)**
`ARB_LADDER_DEFAULT_BATTERY_KWH = 13.5` (`energy_battery.py:~110`) is the divisor for `ev_load_pct_per_h` when capacity is unknown. The site's canonical fallback is `BATTERY_TOTAL_CAPACITY_KWH_FALLBACK = 40.0` (`energy_forecast.py:27`), matching the real ~40 kWh / 8-Encharge pack. At 13.5, a 14 kW EV load reads ~104 %/h instead of ~35 %/h — a 3x inflation of the rung-1 entry uplift, so rung-1 fires (pauses EVs) on days it should not. The build note frames 13.5 as "fail toward charging," but rung-1 SUPPRESSES grid charge and PAUSES EVs — over-firing it is not conservative, it needlessly pauses cars. Fix: use `40.0` (import the existing constant) for the fallback.

**A-HIGH-2 — strategy-local `_battery_capacity_kwh` has no last-known-good cache; every Envoy blip flips the ladder to the static fallback mid-cycle. (bug-class: stale/incorrect data source #7)**
`energy_battery.py:1276` returns `None` on any `unknown`/`unavailable` read with no caching. The coordinator's sibling accessor `energy.py:1991` explicitly caches last-good "so an Envoy blip during arbitrage doesn't silently flip to the [40 kWh] fallback mid-cycle." The new ladder reintroduces exactly the flip the coordinator guards against — and lands on the wrong (13.5) constant per A-HIGH-1. A capacity blip while latched at rung-1 changes `ev_load_pct_per_h`, perturbing the entry projection (the exit uses the snapshotted `_arb_last_ev_load_pct_per_h`, so exit is shielded; entry is not). Fix: reuse the coordinator's cached accessor or add last-known-good caching here.

**A-MEDIUM-1 — `_gate_is_open` (and thus `_classify_attain_rung`) runs TWICE per rung-2 tick; latch mutation + sample recording are not idempotent-by-contract. (bug-class: double-evaluation / hidden side-effect in a predicate)**
`determine_mode` calls `_gate_is_open` at `:2526`; on a rung-2 result it calls `_get_arbitrage_decision`→`_get_arbitrage_phase`→`_gate_is_open` again at `:1031`. `_classify_attain_rung` is not a pure predicate — it flips `_arb_rung0/1_latch`, records a sample, and (on entry) snapshots `_arb_last_ev_load_pct_per_h`. The second call re-reads `_tick_ev_load_w` (still the live value, so far so good) and re-classifies. It happens to stay consistent because rung-0/rung-1 return gate-False (so the second call is NOT reached) and rung-2 re-derives rung-2 deterministically; the double `_record_attain_sample` is deduped. So no live bug TODAY, but the predicate carrying mutating side-effects across a double call site is fragile: any future change that makes the rung-1 branch reachable on the second call would re-snapshot the assumed EV load from the now-paused `ev_load_w≈0` and silently re-open the trap. Recommend: compute the rung once per tick (cache `_arb_last_rung`/intent for the tick) and have `_gate_is_open` read the cached result, OR document the single-call-reaches-rung-1 invariant with an assertion.

**A-MEDIUM-2 — counterfactual snapshot is stale across an EV-count change. (bug-class: snapshot staleness)**
`_arb_last_ev_load_pct_per_h` is frozen at latch entry. If one EV finishes mid-latch and one keeps charging, the counterfactual still adds back the original (larger) load, so `counterfactual_projected` is understated → the latch holds rung-1 slightly longer than ideal. Direction is conservative (errs toward holding the pause, never toward bang-bang), so this is correctness-bounded, not a flap. Acceptable to ship as-is; worth a one-line comment that the snapshot intentionally over-states on EV-count-down, biasing toward hold.

### Cleared (verified correct)
- **Re-entrancy fix:** `assumed_ev_pct` IS snapshotted at latch entry (`:949`), frozen, and read in the latched branch (`:889`); the live accessor is NOT used in the counterfactual. Mutation-proven (above).
- **Latch ordering:** the `_arb_rung1_latch` counterfactual branch (`:880`) precedes the rung-0 entry block (`:912`) on every path through `_classify_attain_rung`. No path checks rung-0 entry first while latched.
- **Sign conventions:** rung-1 entry adds `+ev_load_pct_per_h` (RAISES projection — correct: EVs paused → battery charges faster); exit subtracts `-assumed_ev_pct` (LOWERS projection — correct: EVs back on). Both directions correct.
- **Hysteresis:** 3% entry / 3% exit applied to BOTH the rung-0 latch (`:913-923`) and the rung-1 boundary (`:893` entry-band / `:905` exit-band). No flap band found.
- **Composition with v5.3.8 attain:** rung-0/rung-1 return gate-False at `:2526`, falling through to the attain branch at `:2541`. The realized-divergence safety net survives gate suppression. Verified by code trace + `TestComposition`.
- **Boundary tz/DST (Bug Class #51):** boundary math delegates to `self._tou.get_next_high_rate_transition` (`:1460`) which owns tz/DST; `mins<=0` guarded at `:843`. No raw midnight arithmetic in the new path.
- **Cold boot:** `<2` samples → `_observed_net_charge_rate_per_hour` returns None → `:849` returns `rung_2`. rung-2-at-boot opens the forecast gate but `_get_arbitrage_phase`'s SOC≥target HOLD short-circuits (charge_from_grid=False), and a genuine sub-target boot still commands grid — acceptable/conservative, consistent with v5.3.8 defer.

### Severity tally (Review A): 0 CRITICAL, 2 HIGH, 2 MEDIUM, 0 LOW
A-HIGH-1 and A-HIGH-2 must be fixed before deploy (both land on the wrong/blip-prone capacity, mis-scaling rung-1 entry on the real 40 kWh pack). A-MEDIUM-1 recommended (predicate side-effect hardening); A-MEDIUM-2 ship-with-comment.

## Review B — Pause-ownership precedence + breaker-safety + label correctness

**Framing:** EVSE pause-ownership / precedence / resume races + breaker-safety invariant. Reviewer: ura-reviewer (B). Commit `85309a3`. Verified against live `energy.py`, `energy_pool.py`, `energy_battery.py`.

### B-CRIT-1 — Breaker invariant violated by intra-tick dispatch ordering (grid-on BEFORE EV-pause). `energy.py:2460-2519`. Bug class: cross-coordinator action ordering / breaker-safety.
The battery decision's `charge_from_grid=True` is appended to `decision["actions"]` (`energy_battery.py:2647-2658`) and dispatched FIRST at `energy.py:2462-2463`. The EV pause actions are computed and dispatched ~55 lines and THREE `await` action-loops later (pool `:2467`, EV-TOU `:2473`, then arbitrage `:2518-2519`). Each `_execute_service_action` is `blocking=True` (`energy.py:2829`) and yields the loop. **The 20 kW Enphase grid charge is therefore physically commanded ON while a charging EV is still ON, for the duration of the pool + EV-TOU dispatch window** (multiple blocking cloud service calls, real wall-clock latency). This is exactly the compound-load breaker condition the invariant exists to prevent (battery 20 kW + EV 7.4 kW + base ~5 kW → ~134A). The ledger claims (line 64) "EVs MUST be paused+breaker-labeled BEFORE/with the grid command" — the code does the opposite: grid-on first, pause last. There is NO assertion that blocks the grid command if EVs are unpaused; the `AssertionError` at `energy_pool.py:1270` only validates the *label string*, not that the pause was dispatched before grid-on. **Fix:** dispatch the arbitrage EV-pause block BEFORE `decision["actions"]` whenever `pause_reason=="breaker"` (pause EVs first, confirm turn_off dispatched, then issue grid-on). Severity CRITICAL — real hardware breaker risk.

### B-CRIT-2 — v5.3.8 ATTAIN commands 20 kW grid charge but is DELIBERATELY excluded from EV pause. `energy.py:2481-2499`, `energy_battery.py:1653`. Bug class: breaker-safety / incomplete invariant coverage.
The brief's invariant is "charge_from_grid COMMANDED ⇒ EVs in set with breaker label." The ATTAIN branch (`_get_attainability_charge_decision`, `:1653`) emits `charge_from_grid=True` — the SAME grid pull as arbitrage CHARGE (docstring `:1615` "Same action shape as arbitrage CHARGE") — yet `arbitrage_charging_phase` at `energy.py:2497` gates ONLY on `ARBITRAGE_PHASE_CHARGE`, and the comment at `:2481-2488` explicitly excludes ATTAIN ("observe-only on EVs … does NOT signal EVSE back off"). So ATTAIN-phase grid charge runs with EVs free to be ON (and off_peak ensure-on at `energy_pool.py:551` will actively turn them on). The "observe-only" rationale conflates *reading* net rate with the *physical breaker draw* — the switch is really flipped. This pre-dates this cycle, but the cycle re-asserts a breaker-safety invariant it does not uphold for the ATTAIN grid-charge path. **Fix or explicit waiver:** either pause EVs (breaker label) on ATTAIN grid-charge, or document in-code why ATTAIN's grid draw is breaker-safe (e.g. throttled rate < 20 kW — NOT evidenced in code). Severity CRITICAL pending rate evidence.

### B-HIGH-1 — RAM-only label side-map + set lost on restart; no breaker-case reboot recovery on the pool side. `energy_pool.py:205,213`. Bug class: restart resilience / orphaned pause.
`_paused_by_arbitrage` (`:205`) and `_arbitrage_pause_reason` (`:213`) are both RAM-only. The battery side has reboot recovery for the `charge_from_grid` switch (`energy_battery.py:1884-1929`), but the POOL arbitrage set has NONE. Restart mid-CHARGE with EVs physically OFF + grid still ON at hardware → set is empty post-boot, so `determine_arbitrage_actions(False,…)` never iterates those EVSEs; they sit OFF with no owner, and off_peak ensure-on (`energy_pool.py:551`) WILL turn them back on (the carry-over guard at `:531` no longer holds because the set is empty) → EV resumes WHILE the battery reboot-recovery may still be adopting an ON grid charge → transient compound-load breaker exposure, compounding B-CRIT-1. **Fix:** persist `_paused_by_arbitrage` membership, OR re-pause deterministically on the first post-boot tick before any ensure-on can fire. Severity HIGH.

### B-MED-1 — `current_charging_load_w()` reads ~0 for already-redirect-paused EVs; live value still flows into the classifier mid-latch. `energy_pool.py:1192-1218`, `energy.py:2381`, `energy_battery.py:999`. Bug class: self-referential measurement.
The accessor sums `power` only for `charging==True` EVSEs, so a redirect-paused EV reads ~0. Production correctly uses the snapshotted `_arb_last_ev_load_pct_per_h` for the rung-1 EXIT counterfactual (ledger 27-30; A-cleared). BUT the live accessor is still re-invoked every tick at `energy.py:2381` and threaded as `ev_load_w` into `_gate_is_open`→`_classify_attain_rung(now, soc, load_w)` at `energy_battery.py:999` WHILE latched (value ≈0). Review A's A-MEDIUM-1 confirms the latched rung-1 branch reads the snapshot not `load_w`, so no live bug today — but the 0-valued live load reaching the classifier is fragile: any future edit making the rung-1 entry block reachable on the latched path would re-snapshot from `load_w≈0` and re-open the trap. Severity MEDIUM (cross-cuts Review A; pin a test driving the live accessor at 0 mid-latch).

### B-OK — verified sound
- **redirect→breaker silent flip:** `energy_pool.py:1282` records the label each tick; `:1283-1284` short-circuits if already in set → no resume/re-pause dispatch churn. EV stays continuously off. Correct.
- **No breaker→redirect drop while grid charging:** `energy.py:2506-2507` FORCES `pause_reason="breaker"` whenever CHARGE phase fired, overriding any `_arbitrage_intent`. A redirect label cannot win during CHARGE. Correct.
- **v4.7.28 ensure-on carry-over:** `energy_pool.py:527-535` includes `_paused_by_arbitrage` in the carry-over guard, swallowing BOTH labels identically (no per-label branch). Confirmed unaffected.
- **Resume precedence on release:** `energy_pool.py:1326-1335` leaves the EV paused if `_paused_by_grid_cap`/`_paused_by_battery_drain`/`_paused_by_us` still claim it → a redirect EV will NOT wrongly resume while battery_drain wants it paused. Correct. (Minor: `_paused_by_fill_priority` and `_excess_solar` are absent from this release guard, unlike the ensure-on guard at `:529`; harmless since release only fires `turn_on` when `not state["is_on"]`, but worth a one-line comment on the asymmetry.)
- **Fail-closed default + assertion:** `energy_pool.py:1262-1273` fails legacy 2-arg callers to `breaker` and rejects bad labels. Sound as a label guard (but does NOT enforce dispatch ordering — see B-CRIT-1).

### Summary
| Severity | Count | IDs |
|---|---|---|
| CRITICAL | 2 | B-CRIT-1 (dispatch order grid-before-pause), B-CRIT-2 (ATTAIN grid-charge excluded from pause) |
| HIGH | 1 | B-HIGH-1 (no pool-side reboot recovery for arbitrage set) |
| MEDIUM | 1 | B-MED-1 (live load accessor 0 mid-latch) |

B-CRIT-1 and B-CRIT-2 must be fixed (or B-CRIT-2 formally waived with rate evidence) before deploy — both are real compound-load breaker exposures on the physical panel.


## Review C — Savings / economics + test authority

**Reviewer:** ura-reviewer (Tier 2-DB framing C). **Commit:** `85309a3`.
**Verdict:** test authority SOUND; one HIGH economic assumption gap (EV deadline),
one MEDIUM capacity-fallback risk, one MED stale-source, two LOW no-ops. No CRITICAL.

### Test authority (my lane) — independently re-verified

Ran all 21 tests solo: **21/21 PASS**. Independently re-applied all 6 mutations
against the real production files (backup/restore). My kill-counts vs builder claims:

| Mutation | Builder claim | My result | Match |
|---|---|---|---|
| M1 invert rung-0 predicate | 11 tests | **11 failed** | ✓ |
| M2 drop rung-1 ENTRY +ev_load uplift | 3 tests | **3 failed** | ✓ |
| M3 drop counterfactual −assumed_ev_pct | 1 (oscillation) | **1 failed (T_OSC only)** | ✓ |
| M4 flip rung-1 label redirect→breaker | 1 | **1 failed** | ✓ |
| M5 remove no-solar short-circuit | 1 | **1 failed** | ✓ |
| M6 remove breaker fail-closed | 1 | **1 failed** | ✓ |

Mutation authority is REAL, not vacuous. **The oscillation test lets PRODUCTION set
the latch** (`_classify_attain_rung` returns rung_1 on the entry tick, then 5 held
ticks) — it does NOT hand-prime `_arb_rung1_latch`/`_arbitrage_pause_reason`/
`_arbitrage_intent`. This is the v5.3.8 hand-primed-latch defect being correctly
AVOIDED (caught twice before; clean here). Grep confirms no test assigns those
internals to fake a state. M3 kills ONLY T_OSC — the oscillation test is the sole
guard on the re-entrancy fix, but it does guard it.

### C-HIGH-1 — Rung-1 economics ignore the EV's own charging deadline/need (economic-assumption gap)
`energy_battery.py:_classify_attain_rung` rung-1 entry (`:~895-905`). Bug class:
**strategy/decision-logic economic assumption**. Rung-1 pauses EVs to redirect solar
into the battery on the premise (plan §"provably least-cost"; memory "solar-first →
off_peak grid cheapest") that the EVs simply charge later at the cheap off_peak rate.
**The code books that as strictly cheaper than rung-2 but never checks the EV's charge
deadline or remaining need.** If rung-1 holds EVs paused through the solar window and a
car must then complete charging during the upcoming HIGH-rate window — because off_peak
hours are insufficient or a departure deadline intervenes — rung-1 can LOSE money vs
letting the car charge on solar now and pulling a little grid into the battery. "Redirect
is strictly cheaper" holds ONLY under the unstated assumption *battery-buffer value >
deferred-EV-charge value AND the EV can always recover its kWh at off_peak*. Neither the
design nor the code encodes a deadline/SOC-need input. **This is an operator ruling, not
an auto-fix** — flagging explicitly. For the URA install (cars charge overnight off_peak
with slack) the assumption likely holds; if any EV ever has a tight morning deadline,
rung-1 is a latent cost regression. Recommend: document the assumption in the README
live section + backlog stub for an EV-deadline guard on rung-1.

### C-MED-1 — 13.5 kWh capacity fallback over-counts EV load ~3x on the real ~40 kWh site
`energy_battery.py:~862` + const `ARB_LADDER_DEFAULT_BATTERY_KWH=13.5`. Bug class:
**hardcoded constant wrong for this install (stale-source #7-adjacent)**. `ev_load_pct_per_h
= (ev_load_kw / capacity_kwh) * 100`. Real capacity ~40 kWh (8 Encharges) but fallback
13.5 → a 14 kW EV reads **~104 %/h instead of ~35 %/h, ~3x over-count** → rung-1 entry
fires too eagerly AND the counterfactual `assumed_ev_pct` (captured at entry) is inflated
3x → latch sticks too long. `_battery_capacity_kwh()` (`:1276`) returns None on entity
missing/`unavailable`/`unknown`/unparseable — i.e. **transient Envoy/Enphase blips, NOT
only cold boot** (this cycle elsewhere acknowledges Envoy blips: the `ev_load_w` try/except
+ ATTAIN "envoy blip" comment). So None CAN occur in steady state on a blip tick; that
tick scales rung-1 by 13.5. MED (not HIGH) because it needs a capacity blip to coincide
with a forecast-gate-open off_peak tick and the latch damps single-tick noise. The build
note's "fail toward charging" rationale is **backwards**: a small denominator makes ev_pct
LARGER → rung-1 MORE eager to PAUSE, not more eager to charge. Recommend: set fallback to
the install's real usable capacity (operator to supply, ~40 kWh).

### C-MED-2 — `_arb_last_ev_load_pct_per_h` not cleared on rung-1→rung-0 release (stale-source #7)
`energy_battery.py:~880` (latched counterfactual-pass branch) sets `_arb_rung0_latch=True`
and releases rung-1 but leaves `_arb_last_ev_load_pct_per_h` at the stale entry value;
likewise the rung-2 escalation branches. Read via `getattr(..., 0.0)`; a later rung-1
entry overwrites before use, so currently latent (not a live bug). Pollutes the
`_arb_last_projection_rung1` diagnostic and risks a future reader trusting a stale value.
LOW-MED. Recommend: clear to `0.0` on every rung-1 latch release.

### C-LOW-1 — Savings accounting CORRECT for the new rungs (no defect; confirms framing)
`_account_arbitrage_cycle` (`energy.py:2068`) books savings ONLY when `arbitrage_phase
in (CHARGE, ATTAIN)` with +SOC delta. Rung-0 and rung-1 both hold `arbitrage_phase = NA`
(gate closed) → **neither books savings — correct**: rung-1 is avoided-grid-via-load-shift,
not avoided-peak-discharge, and must NOT be attributed peak-discharge savings; rung-0
("do nothing") books nothing. The v5.3.8 ATTAIN solar-driven-exclusion (`:2120-2131`,
`battery_w <= solar_w` skip) is intact and NOT bypassed by rung-0 (composition test
confirms the post-gate ATTAIN branch stays reachable). No double-book. No finding —
recorded for completeness.

### C-LOW-2 — Fail-closed-to-breaker for legacy callers: sound, no needless pause
`energy_pool.py:~1255`. The ONLY production caller (`energy.py:~2487`) always computes
`pause_reason` explicitly and only passes `arbitrage_charging=True` when it is already
`"breaker"` or `"redirect"`; it never reaches `determine_arbitrage_actions` with
`True`+`None`. **The concern that fail-closed could pause EVs (breaker) when no grid
charge happens does NOT materialize** — confirmed by trace. The fail-closed default +
its warning log are effectively dead code for the live caller (harmless future-proofing).
The kwarg+stash (`_tick_ev_load_w`) and energy.py try/except deviations are also sound.
No finding.

### Summary (Review C)
- HIGH: 1 (C-HIGH-1 EV-deadline economic assumption — **operator ruling needed**)
- MED: 2 (C-MED-1 13.5 kWh fallback 3x over-count on blip; C-MED-2 stale assumed-pct)
- LOW: 2 no-ops (savings correct; fail-closed sound)
- Test authority: **PASS** — 21/21 solo, all 6 mutations independently reproduce
  builder kill-counts, oscillation test drives the real latch (no hand-priming),
  no vacuous/mirror tests, v5.3.8 hand-primed-latch defect absent.

## Validator (live) — TODO

## Fix-up pass

**Scope.** B-CRIT-1 + B-CRIT-2 (breaker invariant) + B-HIGH-1 (reboot
recovery) + A-HIGH-1 + A-HIGH-2 + C-MED-1 (capacity) + A-MED-1 (per-tick
rung cache) + C-MED-2 (clear assumed EV-load on rung-1 release). Plus
ledger note on C-HIGH-1 (accepted-as-designed) and A-MED-2 (snapshot-
stale-across-EV-count-change comment).

### THE BREAKER INVARIANT — bidirectional, code-enforced

**Statement.** (1) No `charge_from_grid=True` may be DISPATCHED on a
tick until every EV is commanded paused (label="breaker") EARLIER in
the same tick's dispatch sequence. (2) No EV may be commanded ON
(ensure-on, arbitrage resume, any path) while `charge_from_grid` is
commanded OR ON in hardware.

**Implementation.**

- New `BatteryStrategy._result()` field `charge_from_grid: bool`
  (energy_battery.py `_result`) — single source of truth for "this
  tick will pull ~20 kW from the grid into the battery", regardless of
  phase label. This closes B-CRIT-2 AUTOMATICALLY: v5.3.8 ATTAIN's
  `_get_attainability_decision` already calls `_result(charge_from_grid
  =True, ...)`, so the chokepoint sees it without any phase-label
  branch. Mutation test `test_breaker_pause_ordering_on_attain_tick`
  asserts the ATTAIN decision actually carries this flag AND the
  ordering invariant holds.

- New `EnergyCoordinator._execute_breaker_safe_dispatch(decision,
  period)` helper (energy.py) — the SINGLE chokepoint. Detects grid-
  charge intent via `decision["charge_from_grid"] is True` OR the live
  `charge_from_grid` switch reading "on" (B-HIGH-1 hardware-derived
  posture: a stale RAM flag is not authoritative). When either is
  true, derives `pause_reason="breaker"` and DISPATCHES the EV-pause
  actions BEFORE dispatching `decision["actions"]`. Replaces the
  previous phase-label-based pause block at energy.py:~2481 (which
  excluded ATTAIN — B-CRIT-2). Extracting into a helper makes the
  ordering invariant directly unit-testable.

- Resume-side guard (energy_pool.py):
  - `EVChargerController.determine_actions(tou_period, grid_charge_on
    =False)` — new kwarg; when True, the off-peak ensure-on branch
    suppresses any `switch.turn_on`, claims the EVSE under
    `_paused_by_arbitrage` with the "breaker" label, and commands
    `switch.turn_off` if the EVSE is currently ON.
  - `EVChargerController.determine_arbitrage_actions(..., grid_charge_on
    =False)` — new kwarg; when True on the release path, refuses to
    resume and re-claims the EVSE under "breaker".

- Threaded from the coordinator: `_execute_breaker_safe_dispatch`
  computes `grid_charge_intent = decision_grid_charge OR
  live_grid_charge_on` and returns it; the EV-TOU determine_actions
  call site (energy.py:~2480) and the release branch downstream both
  receive this flag.

**Why this single chokepoint covers ALL 3 grid-charge paths.** Every
grid-charge producer — arbitrage CHARGE (rung-2), v5.3.8 ATTAIN, and
the new rungs — flows through `BatteryStrategy._result(...)` to land in
`decision["actions"]`. The chokepoint reads `decision["charge_from_grid"]`
which is set whenever any `_result` call passed `charge_from_grid=True`.
Phase-label-INDEPENDENT by construction.

### Ordering tests (mandatory) — applied and reproduced

1. **`test_breaker_pause_ordering_on_arbitrage_charge_tick`** — drives a
   real CHARGE-phase decision (rung-2, gate opens) and asserts the
   index of `switch.turn_off` for the EV PRECEDES the index of
   `switch.turn_on` for the `charge_from_grid` entity in
   `fake.dispatched`. **Mutation applied** (move breaker-pause AFTER
   decision dispatch): FAILS with `AssertionError: ... 2 < 1`.
2. **`test_breaker_pause_ordering_on_attain_tick`** — drives a real
   `_get_attainability_decision` (the v5.3.8 ATTAIN path), VERIFIES
   `decision["charge_from_grid"] is True` (B-CRIT-2 coverage proof),
   and asserts the same ordering. **Same mutation FAILS** here too —
   confirms ATTAIN is covered.
3. **`test_reboot_mid_charge_keeps_ev_off_and_reestablishes_set`** — sets
   the live charge_from_grid switch ON, passes a decision dict with
   `charge_from_grid=False`. The chokepoint MUST treat as breaker
   (live-switch OR decision), pause the EV, and re-establish the set
   + label.
4. **`test_ensure_on_suppressed_when_grid_charge_on`** — resume-side
   guard. **Mutation applied** (drop the `grid_charge_on` branch in
   `determine_actions`): FAILS with "switch.turn_on dispatched".
5. **`test_release_refused_when_grid_charge_on`** — guard on release
   path. (Sibling: `test_release_resumes_when_grid_charge_off` confirms
   the guard is conditional, not unconditional.)
6. **`test_rung_1_over_fires_with_13_5_default`** — pins
   `ARB_LADDER_DEFAULT_BATTERY_KWH == 40.0`. **Mutation applied** (set
   back to 13.5): FAILS with explicit message.

All 6 original ladder mutations (M1-M6) also re-verified green; M3
counterfactual mutation still kills T_OSC.

### Capacity fix (A-HIGH-1 + A-HIGH-2 + C-MED-1)

- `ARB_LADDER_DEFAULT_BATTERY_KWH` now imports
  `BATTERY_TOTAL_CAPACITY_KWH_FALLBACK = 40.0` from
  `energy_forecast.py:27` — the canonical site-wide fallback (8-Encharge
  pack). The previous 13.5 kWh value was 3x too small and made rung-1
  over-fire; the "fail toward charging" rationale was backwards
  (rung-1 PAUSES EVs, so over-firing harms not helps).
- `BatteryStrategy._battery_capacity_kwh()` now maintains a last-
  known-good cache (`self._cached_battery_capacity_kwh`). On an Envoy
  blip (unknown/unavailable/unparseable), the cached value wins over
  None — mirroring `EnergyCoordinator._get_battery_capacity_kwh` at
  `energy.py:1991-2037` which exists precisely to prevent this flip.
  Test `test_capacity_cached_across_envoy_blip` pins this.

### Per-tick rung cache (A-MED-1)

`_classify_attain_rung` now reads `_arb_rung_cache_tick` / `_arb_rung
_cache_rung` at entry — if `cache_tick == now`, returns the cached
rung directly. This makes the second call within a tick a pure read,
so the latch flips, the sample recording, and the snapshot of
`_arb_last_ev_load_pct_per_h` ALL fire exactly once per tick.
`_gate_is_open` calls `_classify_attain_rung` twice per rung-2 tick
(once directly, once via `_get_arbitrage_phase`). Test
`test_rung_classifier_idempotent_within_tick` proves the second call
with a mutated `load_w` (the value `_gate_is_open`'s nested invocation
would observe after EVs paused) does NOT overwrite the snapshot.

### C-MED-2 — clear `_arb_last_ev_load_pct_per_h` on rung-1 release

All four rung-1 latch-release branches in `_classify_attain_rung` now
set `_arb_last_ev_load_pct_per_h = 0.0`:
- no-solar collapse (line ~917)
- counterfactual passes → release to rung-0 (line ~931)
- projection drops below exit-band → escalate to rung-2 (line ~947)

Stale-source #7 hygiene. Test `test_assumed_load_cleared_on_rung_1_
release` pins this on the rung-1 → rung-0 release branch.

### Accepted-as-designed dispositions

- **C-HIGH-1 (rung-1 economics ignore EV deadline).** Operator
  ruling: SHIP SIMPLE. The durable EV philosophy (solar-first → never
  drain battery into car → off_peak grid cheapest, cars recover on
  overnight off_peak slack) means the assumption `battery-buffer
  value > deferred-EV-charge value AND EV can always recover at
  off_peak` holds for this install. Documented here as an explicit
  accepted assumption with a **revisit trigger**: a real tight-same-
  day-deadline case (e.g. operator's morning departure with insufficient
  off_peak hours to refill the car).
- **A-MED-2 (snapshot-stale-across-EV-count-change).** Acceptable;
  direction is conservative (errs toward holding the pause). No code
  change — the existing inline comment at `_arb_last_ev_load_pct_per_h`
  capture documents that the snapshot is intentionally over-stating on
  EV-count-down so the latch holds slightly longer than ideal (no
  bang-bang risk).
- **B-OK (label asymmetry on release-guard vs ensure-on-guard).**
  Reviewer B noted that `_paused_by_fill_priority` and
  `_excess_solar_active` are absent from the arbitrage release guard
  at `:1326-1335` while present in the off-peak ensure-on guard.
  Harmless because release only fires `turn_on` when `not state["is_on"]`,
  and a later carry-over guard tick would re-pause. No change.

### DoD verification

- `py_compile` clean on all three production modules (`ast.parse`).
- Conflict markers: none (grep clean — only comment dividers, not
  `<<<<<<<`/`>>>>>>>` markers).
- Cycle tests solo: 32/32 passed (21 original + 11 new).
- Full suite: **34 failed, 14 errors, 5777 passed, 29 skipped, 23
  warnings** — identical to `develop`-baseline failure/error tallies
  (34F/14E from the baseline diff). Net +32 passes vs baseline 5745
  (= the 21 original + 11 new tests). **ZERO new failures, ZERO new
  errors**. Failure-ID diff: empty set.
- Reverse-order sanity: `test_solar_banking_toggle.py
  test_oc_pillar_a_handshake.py test_arbitrage_solar_attainability_
  ladder.py` 90/90 pass in both forward and reverse order.
- Six mandatory mutations all applied and reproduce named failures
  (sections above). All five mutations restored; full suite green.

## Pass-2 Review (focused — breaker chokepoint)

**Reviewer:** ura-reviewer (pass-2, focused). **Diff:** `85309a3..a3721da`. **Verdict: FIX-FIRST.**
The breaker chokepoint itself is REAL and complete; but the fix-up's restructuring of the
dispatch block silently DELETED two unrelated production call sites. One of them is the very
method the fix-up added the resume-side guard to — so the resume guard is dead code in prod.

### P2-CRITICAL-1 — EV-TOU + Pool-TOU dispatch DELETED from the live tick; resume-side breaker guard is unreachable in production. `energy.py:2459-2470` (deleted hunk). Bug class: functional regression via refactor / dead guard.
The fix-up rewrote the `if not self._observation_mode:` dispatch block into
`_execute_breaker_safe_dispatch`. In doing so it removed THREE statements and only re-added one:
- DELETED `pool_actions = self._pool.determine_actions(period)` + dispatch loop.
- DELETED `if self._ev_tou_enabled: ev_actions = self._ev.determine_actions(period)` + dispatch loop.
- The chokepoint now dispatches ONLY `decision["actions"]` (battery) + the arbitrage pause/release.
Grep confirms (post-fix-up): `_pool.determine_actions` and `self._ev.determine_actions(period)`
have ZERO live callers anywhere in `custom_components/`. At base `24951a8` and pre-fix-up
`85309a3` the tick called `ev_actions = self._ev.determine_actions(period)` at energy.py:~2472
(verified via `git show 85309a3:…` and `git show 24951a8:…`). The fix-up diff lines 18-20 show
the deletion; no addition re-introduces it.
Consequences:
1. **EV TOU enforcement is gone.** Peak/mid_peak re-pause and off-peak ensure-on (the
   `EVChargerController.determine_actions` body, energy_pool.py:432) no longer run. Cars will not
   be paused on peak, and the off-peak ensure-on (v4.7.28 carry-over) will not fire — a direct
   regression of shipped, live-validated behavior.
2. **The new resume-side breaker guard is DEAD CODE.** The `grid_charge_on` kwarg the fix-up added
   to `determine_actions` (energy_pool.py:435,562-571) — leg (2) of the bidirectional invariant,
   "no EV commanded ON while grid charging" — is never exercised in prod because the method is
   never called. So invariant direction (2) is effectively UNENFORCED for the ensure-on path. The
   only surviving resume guard is the release path inside `determine_arbitrage_actions`
   (`grid_charge_on`, energy_pool.py:1366), which IS still wired (energy.py:2486) but only runs in
   the `pause_reason != "breaker"` branch.
3. **Pool TOU optimization is gone** (same deletion) — out of this cycle's breaker scope but a
   real collateral regression.
Why the suite missed it: every ordering/resume test drives the helper or controller method in
ISOLATION (`_execute_breaker_safe_dispatch(fake,…)` at test line 791; `h.ev.determine_actions(
"off_peak", grid_charge_on=True)`), never the real `_update_energy` tick. No test asserts the tick
calls `self._ev.determine_actions(period)`. **Fix:** re-add the `_pool.determine_actions` and
`if self._ev_tou_enabled: self._ev.determine_actions(period, grid_charge_on=grid_charge_intent)`
dispatch loops inside the chokepoint flow (AFTER the breaker pause, threading `grid_charge_intent`
into the EV call so leg-2 is live), and add a coordinator-tick test that asserts both calls fire.

### P2-HIGH-1 — Envoy-blip co-occurrence can leave grid-charge breaker-unguarded (fail-OPEN window). `energy.py:2818-2835`. Bug class: stale/incorrect data source #7 / fail-open.
`grid_charge_intent = decision_grid_charge OR live_grid_charge_on`. Both legs can read False while
grid is physically ON: (a) the two non-`_result` decision dicts (energy_battery.py:1809 reboot
HOLD-CURRENT, and :2405 Envoy-unavailable) omit `charge_from_grid` → `.get(…,False)`; (b) the
live-switch read sets `live_grid_charge_on=True` ONLY when `st.state=="on"` — an `unavailable`/
`unknown`/`None` switch read yields False. The Envoy-unavailable decision (:2405) co-occurs with an
`unavailable` charge_from_grid switch BY DEFINITION (same Envoy outage). If grid charge was engaged
pre-blip, this tick computes `grid_charge_intent=False` → resume guards don't hold → an EV could be
ensure-on'd under a live ~20 kW grid pull. The live-switch read direction is otherwise correct
(fails CLOSED on a clean read), but the all-False-on-unavailable path fails OPEN precisely on the
blip surface the cycle elsewhere acknowledges. NOTE: this is currently masked by P2-CRITICAL-1
(ensure-on path dead), but becomes live the moment CRITICAL-1 is fixed. **Fix:** treat an
`unavailable`/`unknown` charge_from_grid read as breaker-ON (fail CLOSED) when a prior tick had grid
charge, or latch grid-charge posture across an Envoy blip (last-known-good, mirroring the capacity
cache the fix-up already added).

### Verified SOUND (went deep, no defect)
- **Chokepoint ordering (item 1).** `_execute_breaker_safe_dispatch` awaits ALL `breaker_actions`
  (EV `switch.turn_off`) to completion in the loop at energy.py:2867-2868 BEFORE the
  `decision["actions"]` loop at :2873 (which carries the grid `switch.turn_on`). `blocking=True`
  service calls each await. turn_off strictly precedes grid-on. Ordering tests assert real
  `fake.dispatched` index order (`ev_off_idx < cfg_on_idx`, test :825/:904) — not a label.
- **Off-but-unclaimed EV (item 1).** `determine_arbitrage_actions` proactive-claim branch
  (energy_pool.py:1344-1351) adds an already-off EVSE to `_paused_by_arbitrage` + labels it without
  dispatching turn_off — so a later ensure-on can't flip it on. An ON-but-unclaimed EV hits :1333
  → turn_off + claim. Both correct.
- **All grid-charge producers stamp the key (item 2).** Single `return` in `_result`
  (energy_battery.py:2757-2780) always stamps `"charge_from_grid": bool(charge_from_grid)`; all 16
  `return self._result(...)` paths flow through it (arbitrage CHARGE, ATTAIN, HOLD, rung-2,
  self_consumption/discharge/drain all stamp False not omit). The two bypass dicts (:1809, :2405)
  carry `actions: []` (no grid command) → chokepoint default False is correct for them, and the
  live-switch OR is the intended safety net (see P2-HIGH-1 for its gap).
- **B-CRIT-2 (ATTAIN) genuinely closed.** ATTAIN's `_result(charge_from_grid=True)` lands the key →
  chokepoint pauses EVs phase-label-independently. `test_breaker_pause_ordering_on_attain_tick`
  asserts `decision["charge_from_grid"] is True` AND the ordering. Real coverage.
- **Reboot mid-charge re-claim (item 4).** `live_grid_charge_on` true → `pause_reason="breaker"` →
  `determine_arbitrage_actions(True,"breaker")` re-claims+re-labels every EVSE (incl. off ones via
  proactive claim) and turns ON ones off. Set re-established. (Caveat: depends on a CLEAN switch
  read — see P2-HIGH-1.)
- **Double-dispatch guard (item 5).** `if pause_reason=="breaker": pass` at energy.py:2477-2480
  correctly skips the post-decision re-dispatch (breaker already handled pre-decision). The release
  branch (:2481 else) still runs for `pause_requested=False`/redirect cleanup; with grid still on it
  refuses resume via `determine_arbitrage_actions(grid_charge_on=True)` re-claim (energy_pool.py:1366).
- **Mutation kills (item 6).** Inverting chokepoint order (move breaker pause after decision
  dispatch) → `test_breaker_pause_ordering_*` fail on `ev_off_idx < cfg_on_idx` (real index assert).
  Dropping the `grid_charge_on` branch in `determine_actions` → `test_ensure_on_suppressed_…` fails
  — BUT note this test exercises the now-dead method in isolation (P2-CRITICAL-1), so the green test
  does NOT prove prod safety.

### Pass-2 tally: 1 CRITICAL, 1 HIGH, 0 MEDIUM, 0 LOW
**FIX-FIRST.** P2-CRITICAL-1 is a shipped-behavior regression (EV/pool TOU dispatch deleted) that
also nullifies invariant direction (2). P2-HIGH-1 is a fail-open blip window that goes live once
CRITICAL-1 is fixed. The chokepoint design is correct; the regression is collateral damage from the
dispatch-block rewrite. Both fixable in the chokepoint flow + one coordinator-tick test.

## Fix-up pass 2

**Scope.** P2-CRITICAL-1 (restored deleted TOU dispatch + live resume guard) +
P2-HIGH-1 (Envoy-blip fail-CLOSED via last-known-good latch) + the mandatory
test-gap closure (coordinator-tick integration test).

### P2-CRITICAL-1 — RESTORE deleted `_pool` + `_ev` TOU dispatch, thread `grid_charge_intent` into `_ev.determine_actions`

The prior chokepoint refactor (commit `a3721da`) collateral-deleted two
production statements from the live tick at `energy.py:~2472`:
- `pool_actions = self._pool.determine_actions(period)` + dispatch loop
- `if self._ev_tou_enabled: ev_actions = self._ev.determine_actions(period)` + dispatch loop

This nullified EV TOU enforcement (peak re-pause + v4.7.28 off-peak ensure-on)
in production AND made the new `grid_charge_on` resume-side guard at
`energy_pool.py:435,562-571` DEAD CODE — its only caller was gone.

**Restoration.** Extracted the post-chokepoint dispatch into a new helper
`EnergyCoordinator._dispatch_post_decision_tou_and_arbitrage` (energy.py).
This helper is the seam where the coordinator-tick integration test (below)
asserts both calls fire. Ordering preserved:
1. breaker EV-pause  (inside `_execute_breaker_safe_dispatch`, pre-decision)
2. `decision["actions"]`  (battery — may include `charge_from_grid` switch.turn_on)
3. `self._pool.determine_actions(period)`  (pool TOU restored)
4. `if self._ev_tou_enabled: self._ev.determine_actions(period, grid_charge_on=grid_charge_intent)`  (EV TOU restored, leg-2 guard threaded LIVE)
5. arbitrage release / non-breaker pause  (existing logic; breaker case skipped to avoid double-dispatch)

The grid command precedes the EV TOU call so the ensure-on branch observes the
live grid-charge posture — when `grid_charge_intent=True`, the new resume-side
guard at `energy_pool.py:562` suppresses ensure-on AND re-claims the EVSE
under `_paused_by_arbitrage` with the "breaker" label. Verified by the new
tick test (c).

### P2-HIGH-1 — Envoy-blip fail-CLOSED via last-known-good latch

`grid_charge_intent = decision_grid_charge OR live_grid_charge_on`. The
Envoy-unavailable decision shape (energy_battery.py:~2405) omits
`charge_from_grid` (defaults False) and the live switch reads
`unavailable`/`unknown`/None in the SAME outage — both legs went False while
the panel may physically still be pulling 20 kW.

**Fix chosen: BOTH fail-CLOSED AND last-known-good latch** (operator brief:
"minimum bar is fail-CLOSED; prefer ALSO latching"). New
`EnergyCoordinator._last_known_grid_charge_on: bool` (RAM-only, init in
`__init__` at energy.py:~270). Chokepoint logic at
`_execute_breaker_safe_dispatch`:
- Clean `"on"` read → `live_grid_charge_on=True`, LKG updated to True.
- Clean `"off"` read → `live_grid_charge_on=False`, LKG updated to False.
- `"unavailable"`/`"unknown"`/None/registry-exception → if LKG was True,
  `live_grid_charge_on=True` (fail CLOSED), `_LOGGER.info` warns of the
  blip-treat-as-ON. If LKG was False, fail-open is safe (we never had grid
  charge on).

Mirrors the capacity LKG cache the prior fix-up added (`A-HIGH-2` /
`_cached_battery_capacity_kwh`). Documented in-code with a P2-HIGH-1 marker.

### Test-gap closure (mandatory) — coordinator-tick integration test

Every prior ordering/resume test drove the chokepoint helper or the EV
controller method in ISOLATION — that's exactly why deleting the tick's wiring
silently passed. Added two new test classes:

**`TestCoordinatorTickDispatch`** (4 tests) — builds a bare
`EnergyCoordinator` via `object.__new__`, attaches minimal stand-ins for
`_pool`/`_ev`/`_battery`/`hass`/`_observation_mode`/`_ev_tou_enabled`/
`_last_known_grid_charge_on`, and drives BOTH `_execute_breaker_safe_dispatch`
AND `_dispatch_post_decision_tou_and_arbitrage` in the same order as
`_update_energy`. Assertions:
- (a) `test_tick_invokes_ev_tou_determine_actions` — `self._ev.determine_actions(period, ...)` IS invoked. **Mutation (delete the restored call) → FAILS** with `"ev.determine_actions never invoked"`.
- (b) `test_tick_invokes_pool_determine_actions` — `self._pool.determine_actions(period)` IS invoked.
- (c) `test_tick_grid_charge_tick_ordering_and_no_ev_turn_on` — on a real CHARGE-phase decision, the dispatch order is breaker-pause(turn_off) → charge_from_grid(turn_on) → NO EV turn_on after. Pins leg-2 of the breaker invariant at the tick level.
- (d) `test_tick_threads_grid_charge_on_into_ev_determine_actions` — `grid_charge_on=grid_charge_intent` ACTUALLY PASSED to `ev.determine_actions` (not hardcoded False). **Mutation (hardcode False) → FAILS** with `"FAIL-OPEN: grid_charge_on hardcoded False or not threaded"`.

**`TestEnvoyBlipFailClosed`** (4 tests) — pins the fail-CLOSED + LKG-latch
contract:
- `test_unavailable_with_lkg_on_fails_closed` — `unavailable` read with LKG=True → `grid_charge_intent=True`, EV paused. **Mutation (switch read fail-OPEN on unavailable) → FAILS** with `"assert False is True"`.
- `test_unavailable_with_lkg_off_fails_open_safely` — control: unavailable + LKG=False → no false-positive breaker.
- `test_clean_on_read_updates_lkg` — clean ON read updates the latch; subsequent blip fails CLOSED. **Mutation 3 also fails this.**
- `test_clean_off_read_clears_lkg` — clean OFF clears the latch; blip after clean off doesn't spuriously assert.

### Accepted-as-designed (Pass-2)

- **Pool TOU restoration is a tick-level integration concern, not a
  separate review item** — listed in P2-CRITICAL-1's collateral deletions
  in the brief; restored alongside EV TOU in the same helper.

### Mutation evidence (Pass-2)

| Mutation | Test(s) that fail |
|---|---|
| Delete restored `_ev.determine_actions` call | `test_tick_invokes_ev_tou_determine_actions`, `test_tick_threads_grid_charge_on_into_ev_determine_actions` |
| Hardcode `grid_charge_on=False` in EV TOU call | `test_tick_threads_grid_charge_on_into_ev_determine_actions` |
| Make Envoy-blip switch read fail-OPEN (unavailable → False) | `test_unavailable_with_lkg_on_fails_closed`, `test_clean_on_read_updates_lkg` |
| Invert chokepoint ordering (move breaker pause AFTER decision dispatch) | `test_breaker_pause_ordering_on_arbitrage_charge_tick`, `test_breaker_pause_ordering_on_attain_tick` (PRIOR mutations — re-verified green here) |

All six original ladder mutations (M1-M6) and the prior fix-up's chokepoint
mutations re-verified green; the new tick-level + Envoy-blip mutations close
the test gap that let P2-CRITICAL-1 ship.

### DoD verification (Pass-2)

- `py_compile` clean on `energy.py` (`ast.parse` PASS).
- Conflict markers: none.
- Cycle tests solo: **40/40 passed** (21 original + 11 prior fix-up + 8 new
  Pass-2 — 4 in `TestCoordinatorTickDispatch`, 4 in `TestEnvoyBlipFailClosed`).
- Full suite: **34 failed, 14 errors, 5785 passed, 29 skipped** — identical
  failure/error tallies to `develop` baseline (34F/14E). Net +40 passes vs
  baseline 5745. **ZERO new failures, ZERO new errors.** Failure-ID diff:
  EMPTY SET.
- Reverse-order sanity: `test_arbitrage_solar_attainability_ladder.py
  test_oc_pillar_a_handshake.py test_solar_banking_toggle.py` 98/98 pass in
  both forward and reverse order.
- Restored-call evidence — `git grep` showing live callers post-fix:
  `_dispatch_post_decision_tou_and_arbitrage` invokes both
  `self._pool.determine_actions(period)` and
  `self._ev.determine_actions(period, grid_charge_on=grid_charge_intent)`
  inside the `if not self._observation_mode:` tick block. Helper itself is
  invoked from the tick at `energy.py:~2472`.

## Pass-3 Review (final confirm)

**Reviewer:** ura-reviewer (pass-3, focused confirm). **Diff:** `a3721da..c5606de`. **Verdict: SHIP.**
Fix-up-2 restores the deleted TOU dispatch and adds the Envoy-blip LKG latch + a real
coordinator-tick integration test. Both Pass-2 findings (P2-CRITICAL-1, P2-HIGH-1) are
genuinely fixed; no new ordering/safety regression introduced. Verified against live code,
not the ledger narrative.

### 1. Dispatch ORDER end-to-end — CONFIRMED SAFE
Tick path (`energy.py:2469-2491`): `_execute_breaker_safe_dispatch` runs FIRST → inside it
(`:2898-2911`) breaker EV-pause `turn_off` actions are awaited to completion in the loop
BEFORE the `decision["actions"]` loop (grid `switch.turn_on`). It then returns
`grid_charge_intent`, which is passed into `_dispatch_post_decision_tou_and_arbitrage`
(`:2487`). The post-decision helper (`:2967-2974`) threads `grid_charge_on=grid_charge_intent`
into `self._ev.determine_actions`. The restored TOU dispatch runs AFTER the grid command,
never between (a) and (b). The ensure-on suppression at `energy_pool.py:562` `continue`s
BEFORE the `switch.turn_on` at `:593`, so on a grid-charge tick the EV TOU path physically
cannot emit a turn_on — and turns OFF an already-ON EV. No path resumes a breaker EV while
grid charges. **Pass.**

### 2. grid_charge_intent at the (c) call — CONFIRMED (decision-flag OR live-switch)
Same `grid_charge_intent` computed once in the chokepoint (`energy.py:2876`:
`decision_grid_charge or live_grid_charge_on`) is returned and threaded verbatim into
(c) — not recomputed/stale. The 35-min actuation-lag case is covered: `decision_grid_charge`
reads `decision["charge_from_grid"]` (the DECISION flag, set by `_result()`), so a CHARGE
commanded THIS tick yields `grid_charge_intent=True` even before the switch flips. Both legs
feed it (decision flag OR live-switch incl. LKG-latched value). **Pass.**

### 3. LKG latch — CONFIRMED FAIL-SAFE-DIRECTION
`_last_known_grid_charge_on` (`energy.py:271`) updates True only on clean `"on"`, False only
on clean `"off"`; `unavailable`/`unknown`/None/registry-exception with LKG=True → forces
`live_grid_charge_on=True` (fail closed). The stuck-True case the prompt names IS real: if
grid genuinely turns off during a PERMANENT switch-unavailable window, LKG never sees the
clean `"off"` and stays True forever → EVs held off indefinitely. Confirmed this is the
fail-SAFE direction (lost EV charging, zero breaker risk) and recovers automatically on the
first clean `"off"`/`"on"` read once the entity returns. Acceptable as designed (matches the
operator brief "fail-CLOSED is the minimum bar"). **Pass — noted non-recovery only under
permanent unavailability.**

### 4. Tick integration test authority — CONFIRMED REAL
`TestCoordinatorTickDispatch` builds a bare `EnergyCoordinator` via `object.__new__` and
drives the REAL bound `_execute_breaker_safe_dispatch` + `_dispatch_post_decision_tou_and_arbitrage`
in `_update_energy` order — not a reimplementation. The spy wraps but CALLS the real
`EVChargerController.determine_actions`. Test (c) asserts captured `dispatched` index order
(grid turn_on present, no EV `garage_a` turn_on after it) + real arbitrage-set ownership —
ordering, not labels. **Re-ran the mutation** (deleted the restored `_ev.determine_actions`
call): tests (a) `test_tick_invokes_ev_tou_determine_actions` AND (d)
`test_tick_threads_grid_charge_on_into_ev_determine_actions` both FAIL
(`ev.determine_actions never invoked`). Restored, clean. **Pass.**

### 5. Suite + conflict markers — CLEAN
Cycle suite 40/40 pass. Full suite **34 failed / 14 errors / 5785 passed** — failure-ID set
identical to `develop` baseline (34F/14E); zero new failures. No conflict markers in
energy.py / energy_pool.py / the test file. energy.py git-clean after mutation restore.

### New findings: NONE.
P3-NOTE (informational, not a finding): LKG cannot self-recover under a *permanent*
switch-unavailable; safe direction (EVs stay off). Worth a one-line README live-validation
note, no code change.

### Pass-3 tally: 0 CRITICAL, 0 HIGH, 0 MEDIUM, 0 LOW. **SHIP.**

## README write-back (post-deploy, post-live-validation) — TODO
