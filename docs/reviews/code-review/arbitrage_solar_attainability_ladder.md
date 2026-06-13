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

## Review A — Gate / projection correctness + no-flap (TODO)

## Review B — Pause-ownership precedence + breaker-safety + label correctness (TODO)

## Review C — Savings / economics + test authority (TODO)

## Validator (live) — TODO

## Fix-up — TODO

## README write-back (post-deploy, post-live-validation) — TODO
