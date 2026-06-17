# PLANNING — Arbitrage / Attain Inclement `partial_hold` Floor Enforcement

**Status:** PLANNING (no code)
**Tier:** **Tier 2-DB** (operator-elevated — shared regression-prone primitive: the arbitrage / attain state machine that gates every off_peak and mid_peak-continuation reserve emission)
**Targets:** `custom_components/universal_room_automation/domain_coordinators/energy_battery.py`
**Predecessor:** v5.5.0 (SHIPPED + LIVE 2026-06-14) — `docs/planning/PLANNING_inclement_weather_reserve.md`
**Bug class:** #53 — *computed-but-not-consumed control value* (the inclement `effective_reserve` is computed at `:2766` but only consumed by the drain-target fallback — three sibling code paths still emit `reserve_level` unaware of it).

---

## Institutional context verified

### Code locations read end-to-end during scoping
- `custom_components/universal_room_automation/domain_coordinators/energy_battery.py` — read `:1400-1535` (`_get_arbitrage_phase` tail + `_get_arbitrage_decision`), `:1930-2282` (attain decision helpers + reboot recovery), `:2284-2602` (`_run_attain_branch`), `:2603-2985` (`determine_mode` precedence chain through off_peak hold). All cited line numbers below come from this read.
- `docs/planning/PLANNING_inclement_weather_reserve.md` — predecessor v5.5.0 plan; the operator-mandated **invariant** is that `allow_discharge` (≡ no alert) is byte-identical to a pre-v5.5.0 tick. The clamp here MUST preserve that.

### Greps run + verdicts

| Surface searched | Pattern | Result | Verdict |
|---|---|---|---|
| `energy_battery.py` | `reserve_level=` | 17 hits; off_peak/arbitrage/attain emission sites enumerated below | — |
| `energy_battery.py` | `_run_attain_branch` | 3 hits (def `:2284`, call sites `:2812` mid_peak D1b, `:2913` off_peak) | both call sites covered |
| `energy_battery.py` | `_inclement_decision`, `InclementDecision`, `reserve_floor`, `hold_depth` | builder/cache `:787`-`:838`, dispatch `:860`-`:930`, consumption `:2740`-`:2766` + `:2955` + `:2975` | REUSED — fused decision already in hand; plan PASSES it deeper, does not re-derive |
| `energy_battery.py` | `_peak_buffer_target` (constructor + readers) | constructor arg `:160`, field init `:212`, predicate readers `:1128`, `:1139`, `:1175`, `:1374`, emission sites `:1492`, `:1508`, `:1997`, `:2043` | REUSED — every arbitrage/attain emission already pins to this; plan ADDS a `partial_hold` floor on top, never lowers it |
| `domain_coordinators/` (sibling coords) | `effective_reserve`, `reserve_floor` | only present in `energy_battery.py` | no cross-coord ripple to other coordinators in this cycle |

**REUSED vs NEW summary:** *Everything REUSED.* No new CONF_*, no new sensor, no new helper, no new signal, no new constant. The work is parameter-threading plus min-floor clamps at known emission sites. Bug Class #53 is the right framing — the value already exists, callers are silently ignoring it.

### Prior planning docs / memory bodies / design docs consulted
- `docs/planning/PLANNING_inclement_weather_reserve.md` — full read; predecessor cycle.
- MEMORY entry [project_v5_5_0_inclement_weather_shipped] — v5.5.0 SHIPPED+LIVE 2026-06-14; A-CRIT-1 fixup landed in the drain-target fallback only.
- MEMORY entry [project_inclement_arbitrage_wait_floor_gap] — the MEDIUM this plan addresses, surfaced by the fourth-pass review of v5.5.0.
- `docs/Coordinator/ENERGY_COORDINATOR_DESIGN_v2.3.md` exists and is the relevant design doc; arbitrage / attain state-machine semantics are the authoritative reference for the "byte-identical when not partial_hold" invariant. No design-doc edits proposed here (this is a correctness fix inside the existing state machine).

---

## Enumeration — every `reserve_level=` emission inside the off_peak / mid_peak-D1b state machine

This is the **core of the plan** (Bug Class #53 lives or dies on whether enumeration is exhaustive). Three categories:

### Category A — `_get_arbitrage_decision` (`energy_battery.py:1456-1533`)
Reached at `determine_mode :2898` when `self._gate_is_open(now, target_day_class)` is true (tomorrow poor / very_poor, arbitrage enabled). All three phases emit `reserve_level`.

| # | Site | Phase | Currently emits | Risk if `partial_hold` active |
|---|------|-------|----------------|-------------------------------|
| A1 | `:1492` | `HOLD` | `self._peak_buffer_target` (e.g. 80) | LOW — `peak_buffer_target` ≥ typical `partial_hold` floor (50). Safe in steady state, but clamp `max()` makes it provably safe across all configurations. |
| A2 | `:1508` | `CHARGE` (`charge_from_grid=True`) | `self._peak_buffer_target` | LOW — same as A1. Clamp must be `max(target, floor)` so it **cannot suppress charging**: a higher floor below the charge target leaves the target unchanged; a floor *above* the target (misconfiguration) would naturally raise reserve toward the floor — see §"Charge-intent guarantee" below. |
| A3 | **`:1527`** | **`WAIT`** | **`self.reserve_soc`** (e.g. 20) | **THE GAP.** WAIT emits the unmodified hardware reserve floor. Overnight loads then drain to `reserve_soc` while a `partial_hold` watch is active — exactly the regression Bug Class #53 predicts. |

### Category B — `_run_attain_branch` (`:2284-2601`) and its decision-emitting helpers
Reached at `:2913` (off_peak attain) and `:2812` (mid_peak D1b attain). The branch itself emits no `reserve_level` — it delegates to four helpers:

| # | Helper | Defined at | Emits | Floor-clamp needed? |
|---|--------|-----------|-------|---------------------|
| B1 | `_get_attainability_decision` (CHARGE) | `:1997` | `self._peak_buffer_target` | Yes — same `max(target, floor)` shape as A2. |
| B2 | `_get_attainability_hold_decision` (HOLD) | `:2043` | `self._peak_buffer_target` | Yes — same shape as A1. |
| B3 | `_get_attainability_hold_current_decision` (HOLD-CURRENT) | `:2058-2100` | **no `reserve_level` key; `actions=[]`** | **No** — zero-action decision dict by design (B-HIGH-3 reboot-warmup); reserve is not commanded. Safe as-is. |
| B4 | reboot-recovery "release" branch inside `_maybe_run_reboot_recovery` | `:2268` | `self.reserve_soc` | **Yes — second WAIT-class gap.** Orderly release after a boot that landed outside any valid charge window restores `reserve_soc` directly. If `partial_hold` is active at that moment, release would drop below the floor. |

### Category C — drain-target fallback (already fixed in v5.5.0)
| # | Site | Currently emits | Status |
|---|------|----------------|--------|
| C1 | `:2964` (drain) | `drain_target` clamped via `:2955-2956` to `max(drain_target, effective_reserve)` when `partial_hold` | ALREADY CORRECT — leave untouched, regression-test only. |
| C2 | `:2981` (hold) | `hold_reserve` clamped via `:2975-2976` to `max(hold_reserve, effective_reserve)` when `partial_hold` | ALREADY CORRECT — leave untouched, regression-test only. |

### Sites confirmed OUT OF SCOPE for this clamp
| Site | Reason out of scope |
|------|---------------------|
| `:2752`, `:2760` (full_hold) | Already emit `decision.reserve_floor` — by construction the elevated floor itself. |
| `:2776`, `:2783` (peak) | Already read `effective_reserve` (v5.5.0). No change. |
| `:2844` (mid_peak summer-pre-peak hold) | Emits `hold_reserve = int(soc)` — a SOC-pin, not a floor. Clamping `partial_hold` here would be a no-op when SOC > floor and contradictory when SOC < floor (we hold AT current SOC, not below it). Leave untouched; document the no-clamp rationale in the test. |
| `:2864`, `:2879` (mid_peak shoulder/winter discharge + low-SOC) | Already read `effective_reserve` (v5.5.0). No change. |

**Total NEW clamp sites: 4** (A3 WAIT, A2 CHARGE, A1 HOLD, B1 attain CHARGE, B2 attain HOLD, B4 reboot release) — written as 6 line-edits but logically 4 distinct shapes (WAIT-style: `reserve_soc → max(reserve_soc, effective_reserve)`; target-style: `peak_buffer_target → max(peak_buffer_target, effective_reserve)`; release-style: `reserve_soc → max(reserve_soc, effective_reserve)`; with HOLD/CHARGE collapsing to the target-style).

---

## Deliverables

### D1 — Thread `effective_reserve` into the arbitrage + attain decision sites

**Mechanism (operator-preferred parameter over hidden state):** add an `effective_reserve: int` parameter (with default `= None` for back-compat at the type seam) to:
- `_get_arbitrage_decision`
- `_run_attain_branch`
- `_get_attainability_decision`
- `_get_attainability_hold_decision`
- `_maybe_run_reboot_recovery` (so its `release` branch sees the floor)

Plus a `hold_depth: str = "allow_discharge"` parameter on the same five signatures. Two scalars, not the whole `InclementDecision` — keeps the helper signatures minimal and makes the byte-identical guarantee mechanically obvious (helpers only ever see two ints + one string and a `max()` gate).

Call sites in `determine_mode`:
- `:2898` (arbitrage) — pass `effective_reserve=effective_reserve, hold_depth=decision.hold_depth`
- `:2913` (off_peak attain) — same
- `:2812` (mid_peak D1b attain) — same; `effective_reserve` is in scope (computed at `:2766` and the D1b block is later in the same function).

**Why parameter over field:** a field (`self._effective_reserve_this_tick`) would couple every helper to tick lifecycle — easy to read stale on the wrong tick. Explicit parameter makes the data flow audit-able and prevents the "computed-but-not-consumed" class from recurring.

**Default safety:** when callers omit the parameter (legacy tests), default `hold_depth="allow_discharge"` makes every clamp a no-op (gate is false) — byte-identical fallback.

#### Acceptance Criteria
- **Verify:** Every site enumerated in §A1-A3 + §B1, B2, B4 above has the form
  ```python
  reserve_level=(max(<existing_expr>, effective_reserve)
                 if hold_depth == "partial_hold"
                 else <existing_expr>),
  ```
  (or an equivalent `_resolve_reserve(...)` helper).
- **Test:** New behavioral tests in `quality/tests/test_battery_inclement_arbitrage_floor.py`:
  - `test_wait_phase_floors_at_effective_reserve_under_partial_hold` — gate OPEN, phase resolves to WAIT, partial_hold active with floor 50, `reserve_soc=20` → returned `reserve_level == 50`.
  - `test_wait_phase_byte_identical_under_allow_discharge` — same setup, `hold_depth="allow_discharge"` (i.e. `decision.reserve_floor == reserve_soc`) → returned `reserve_level == 20` (pre-v5.5.0 behavior preserved).
  - `test_arbitrage_charge_unchanged_when_target_above_floor` — gate OPEN, CHARGE phase, target=80, floor=50 → `reserve_level == 80` AND `charge_from_grid is True` (charging not suppressed).
  - `test_arbitrage_charge_clamped_when_floor_above_target` — pathological config target=40, floor=50 → `reserve_level == 50` AND `charge_from_grid is True` (clamp raises floor, does not switch off the charge).
  - `test_arbitrage_hold_floors_at_effective_reserve` — HOLD phase, target=80, floor=50 → `reserve_level == 80` (target wins); target=40, floor=50 → `reserve_level == 50`.
  - `test_attain_charge_and_hold_clamped_under_partial_hold` — mirrors the two arbitrage tests against `_get_attainability_decision` + `_get_attainability_hold_decision`.
  - `test_attain_reboot_release_floors_at_effective_reserve` — drive `_maybe_run_reboot_recovery` to the `"release"` branch with partial_hold active; assert `reserve_level == effective_reserve`, not `self.reserve_soc`.
  - `test_attain_hold_current_emits_no_reserve_change` — regression: B3 path still returns `actions=[]` and contains no `reserve_level` key change vs current behavior.
  - **Mutation check** — `test_mutation_each_clamp_required`: parameterized test that monkey-patches each of the 6 clamp expressions to drop the `max()` (returning the bare existing expr), asserts each mutation fails at least one of the above behavioral tests. Proves every clamp is independently load-bearing.
- **Live:** Post-deploy, during the next overnight where:
  (a) tomorrow_solar_class ∈ {poor, very_poor} (arbitrage gate open) AND
  (b) inclement `hold_depth == "partial_hold"` is active (sensor `sensor.ura_energy_inclement_hold_depth` or attribute),
  verify in HA Developer Tools that `sensor.ura_energy_battery_strategy` attribute `reserve_level` is ≥ `effective_reserve` (= `max(reserve_soc, inclement_reserve_floor)`) during the WAIT phase (`arbitrage_phase == "wait"`). Cite entity_id + attribute snapshot in the README write-back.

### D2 — Regression guard: arbitrage CHARGE intent is not suppressed

The single highest-risk consequence of mis-shaped clamping is "I raised the floor, and now the strategy thinks it has reached target and stops charging." We MUST guarantee:

- The clamp ONLY changes the `reserve_level` field. It does NOT touch `charge_from_grid`, mode, or `arbitrage_phase`.
- The CHARGE→HOLD transition in `_get_arbitrage_phase` / `_run_attain_branch` reads SOC against `self._peak_buffer_target` (NOT against the clamped reserve), so a higher floor cannot satisfy the transition early.

#### Acceptance Criteria
- **Verify:** `_get_arbitrage_phase` (`:1374`) still compares `soc >= self._peak_buffer_target`, unchanged.
- **Verify:** `_run_attain_branch` charging→holding transition (`:2383-2401`) still compares against `self._peak_buffer_target`, unchanged.
- **Test:** `test_partial_hold_does_not_advance_charge_to_hold_early` — SOC=60, target=80, floor=70, gate OPEN → phase stays CHARGE (not HOLD), `charge_from_grid is True`, `reserve_level == max(80, 70) == 80`.

### D3 — Byte-identical guarantee for `allow_discharge` / no-alert ticks

- The clamp is gated **twice**: (a) `hold_depth == "partial_hold"` explicit check, AND (b) `max()` is a mathematical no-op when `effective_reserve <= existing_expr`. Either gate alone preserves no-alert behavior; together they make it robust to a future config where `reserve_floor` could equal `reserve_soc` even outside `partial_hold`.
- For `allow_discharge`, `decision.reserve_floor == self.reserve_soc` (v5.5.0 invariant at `:2766`), and `hold_depth != "partial_hold"`, so each clamp is short-circuited by gate (a) — the expression returned is byte-identical to the pre-cycle expression.

#### Acceptance Criteria
- **Test:** `test_no_alert_baseline_is_byte_identical` — parameterized across all six sites: with `hold_depth="allow_discharge"`, snapshot the full decision dict against a saved fixture from a v5.5.0-equivalent run; assert dict equality (mode, reason, charge_from_grid, reserve_level, arbitrage_phase, all keys).
- **Test:** `test_full_hold_unchanged_short_circuits_before_arbitrage_path` — `hold_depth="full_hold"` → control never reaches `_get_arbitrage_decision` / `_run_attain_branch` (precedence at `:2741-2762` returns first).

### D4 — Reason-string telemetry (LOW, fix-in-cycle per "Fix LOWs In-Cycle")
When a clamp fires (computed expr was below floor and `partial_hold` is active), append a `" (partial_hold floor)"` suffix to the `reason` string emitted by the affected helper. Operator-visible signal in the sensor narrative that the floor changed an emission. No new sensor; existing `reason` attribute carries it.

#### Acceptance Criteria
- **Test:** `test_clamp_fires_appends_partial_hold_suffix` — WAIT under partial_hold floor 50, reserve_soc 20 → reason contains `"partial_hold floor"`.
- **Test:** `test_clamp_noop_does_not_append_suffix` — CHARGE with target 80, floor 50 (no-op) → reason does NOT contain `"partial_hold floor"`.

---

## Charge-intent guarantee (interaction caution, called out)

The arbitrage path exists precisely to **raise** SOC during off_peak when tomorrow is poor. The clamp is `max(reserve_level, effective_reserve)` — it can only RAISE a floor, never LOWER a target. Specifically:

- **CHARGE phase (A2, B1):** `reserve_level` is the *target* the battery is being driven toward. `max(target, floor)`:
  - If `target ≥ floor`: returns `target` — charging proceeds to `target` unaffected.
  - If `target < floor` (pathological, e.g. operator set `peak_buffer_target=40` while `partial_hold` floor=50): returns `floor`. This is the CORRECT behavior — the floor IS an additional lower-bound on stored charge; charging now drives to `floor` instead of `target`. Critically, `charge_from_grid=True` is **untouched** — we still pull grid. The Enphase reserve simply locks at a slightly higher number.
- **HOLD phase (A1, B2):** same logic; HOLD already pins at `peak_buffer_target`, clamp can only raise.
- **WAIT phase (A3):** clamp lifts the resting reserve from `reserve_soc` (the safety floor) to `effective_reserve` (the watch-imposed floor). This is the entire point of the fix.

**Confirmed:** no clamp suppresses a charge. The `charge_from_grid` boolean is set independently of `reserve_level` at every site.

---

## Tier classification + review framings

**Tier 2-DB (operator-elevated regression-prone).** Justification: this touches the shared arbitrage/attain state machine consumed across the off_peak AND mid_peak-D1b paths; a wrong clamp can either (a) silently re-create Bug Class #53 in a sibling future cycle, (b) suppress arbitrage charging on poor-solar days (cost regression), or (c) break the byte-identical `allow_discharge` invariant Reviewer B certified for v5.5.0.

Three **framing-disjoint** reviews run in parallel:

### Review A — Enumeration completeness + clamp correctness
- Verify the §A/§B/§C enumeration captures EVERY `reserve_level=` emission reachable from `determine_mode` in the off_peak and mid_peak-D1b branches. Independent re-grep, independent classification.
- Verify each new clamp uses `max(<existing>, effective_reserve)` (not `min`, not assignment).
- Verify the gate `hold_depth == "partial_hold"` is present at every clamp.

### Review B — Charge-intent not suppressed + state-machine integrity + byte-identical
- Trace the `_get_arbitrage_phase` SOC→phase transitions and confirm they continue to read `self._peak_buffer_target` (not the clamped reserve).
- Trace `_run_attain_branch` charging→holding transition similarly.
- Verify `allow_discharge` and no-alert ticks return byte-identical decision dicts (carry through `_result(...)` shape comparison).
- Verify `full_hold` precedence at `:2741` is untouched (still short-circuits before the arbitrage/attain branches).
- Verify mid_peak D1b call site at `:2812` passes the same `effective_reserve` / `hold_depth` it uses in the off_peak branch (no divergence between the two attain entry points).

### Review C — Test authority + mutation coverage + helper signature audit
- Verify behavioral tests drive `determine_mode(...)` end-to-end (the public API), NOT the helpers in isolation. Tests exercising helpers directly are *additionally* permitted but not sufficient.
- Verify the mutation test in D1 trips for EACH of the 6 clamp sites independently.
- Verify default parameter values on `_get_arbitrage_decision` / `_run_attain_branch` / attain helpers preserve back-compat for any in-repo callers / tests that don't pass the new args (grep for direct callers; only `determine_mode` should be calling these helpers in production).
- Verify the new tests cover the four boundary conditions: `floor < reserve_soc` (impossible per `:2766` `max()` but worth a defensive assert), `floor == reserve_soc` (allow_discharge), `floor > reserve_soc` AND `floor < target` (typical partial_hold), `floor > target` (pathological).

---

## Pre-deploy zero-bugs gate (mandatory per `feedback_pre_deploy_zero_bugs_gate`)
- `grep -rnE '<<<<<<<|=======|>>>>>>>' custom_components/universal_room_automation/domain_coordinators/energy_battery.py` returns empty.
- `python -m py_compile custom_components/universal_room_automation/domain_coordinators/energy_battery.py` succeeds.
- `PYTHONPATH=quality python3 -m pytest quality/tests/test_battery_inclement_arbitrage_floor.py -v` all PASS.
- Full suite delta vs `pre-review-v<version>` baseline: zero new failures.

---

## Pre-deploy snapshot (Tier 2-DB requirement)
Capture for ±25% post-deploy regression comparison:
- `sensor.ura_energy_battery_strategy` `reserve_level` distribution by `arbitrage_phase` over the most recent off_peak window (recorder query) — pre-fix.
- `sensor.ura_energy_battery_strategy` `arbitrage_phase` histogram over the same window.
- Post-deploy: same two queries, asserted within ±25% on non-`partial_hold` ticks; on `partial_hold` ticks, `reserve_level` should rise to ≥ `inclement_reserve_floor` (this is the intended shift, not a regression).

---

## Live Validation (Review D)
After restart, on a tick where ALL of the following hold:
1. `sensor.ura_energy_battery_strategy` attribute `arbitrage_active == True` AND `arbitrage_phase == "wait"`
2. `sensor.ura_energy_battery_strategy` attribute `inclement_hold_depth == "partial_hold"`
3. `sensor.ura_energy_battery_strategy` attribute `inclement_reserve_floor > reserve_soc`

**Pass criterion:** the same sensor's `reserve_level` attribute equals `max(reserve_soc, inclement_reserve_floor)` — i.e. the WAIT-phase floor is honored. Cite entity_id + attribute snapshot timestamp in the README write-back table.

**Fallback proof (when the live window doesn't materialize within 48h):** in-suite proof via the `test_wait_phase_floors_at_effective_reserve_under_partial_hold` test; document the in-suite-only basis in the README write-back per CLAUDE.md mandate.

---

## README write-back (mandatory per CLAUDE.md "Record Live Validation Back Into the README")
`docs/readmes/README_v<version>.md` will be authored pre-deploy with prospective Live criteria from the §Live block above, and rewritten post-restart with the observed PASS/FAIL table (entity_id + attribute values + timestamps).

---

## Plan completion tracking — explicit out-of-scope

The following are **deliberately deferred** (not silently dropped):
1. **`full_hold` reserve_floor consumption audit beyond `:2752` / `:2760`** — `full_hold` short-circuits before the arbitrage / attain branches, so no clamp is needed in the state machine. Audit confirmed (Category §C-OOS row 1).
2. **A summer mid_peak pre-peak hold (`:2844`)** — emits `int(soc)` as a SOC-pin, not a floor; clamping is semantically wrong (would lock reserve above current SOC and command discharge upward). Documented above; no change.
3. **Cross-coordinator ripple to `_apply_evse_battery_hold` (energy.py:2453)** — per `:2722-2724` comment, the EVSE hold layer is already `max()`-safe and runs AFTER `determine_mode` returns. No change required; called out for Reviewer B sanity.
4. **A new `effective_reserve` sensor attribute** — `inclement_reserve_floor` already exposed on the strategy sensor (per `:930`); a derived `effective_reserve = max(reserve_soc, inclement_reserve_floor)` could be added but is computable by the dashboard from existing attributes. Defer to a future hygiene cycle if operator wants it surfaced.
5. **Migrating the two existing v5.5.0 clamps (`:2955`, `:2975`) to the shared `_resolve_reserve(...)` helper if D1 introduces one** — optional refactor; if added, do it in this cycle's fix-up pass; if skipped, document under deferral and the two existing clamps remain inline.

---

## Summary of file paths touched by this plan

- `custom_components/universal_room_automation/domain_coordinators/energy_battery.py` — signature changes + 6 clamp insertions + 4 default-param additions. Estimated diff: ~40-60 LoC.
- `quality/tests/test_battery_inclement_arbitrage_floor.py` — NEW file, ~10 behavioral tests + 1 parameterized mutation test.
- `docs/readmes/README_v<version>.md` — NEW (pre-deploy prospective + post-restart write-back).
- `docs/reviews/code-review/v<version>_arbitrage_wait_inclement_floor.md` — NEW (post-3x-review consolidation per CLAUDE.md "Post-Review Documentation").

NO changes to: `const.py`, `config_flow.py`, `options_flow.py`, `sensor.py`, `binary_sensor.py`, `number.py`, `switch.py`, `select.py`, `button.py`, any other coordinator. Verified via the §Institutional context greps above.
