# Plan review 4: EC storm and blind decisions, Rev 3 (framing 2: adversarial build-prediction)

**Target:** `docs/planning/PLANNING_ec_storm_and_blind_decisions.md` Rev 3 @ 4665b252b
**Framing:** "What will ura-super-builder get wrong reading this?" Focus on the Rev 3 delta: D-B6, the two Number entities, D-A3 keying.
**Code base checked:** worktree `ec-storm-rev3` (HEAD 4665b252b, code = 57ffbe55b).
**Mandatory-read note:** energy-only scope; no HVAC or presence surface touched, so the HVAC/presence state-of-play docs were not required.

**Verdict:** ⚠️ fix in plan before Stage A/B dispatch. 3 HIGH, 7 MED, 4 LOW. No CRIT.

---

## HIGH

### H1. The Number-entity design gives two sources of truth. The repo already has a third option that is the right one.
The plan (D-A5, D-B6, §7) says: copy `PeakBufferTargetNumber`, add an EC coordinator setter `set_inclement_blind_full_hold_floor(int)`, add a `_EC_SETTER_DISPATCH` row, and "the fusion reads the value from the battery strategy each tick (no cached copy in `InclementFusion.__init__`)".

What the code does:
- `_inclement_config()` (`energy_battery.py:2556-2600`) already reads the CM `entry.options` **fresh on every tick**, and `InclementFusion` is **constructed fresh on every tick** inside `_inclement_decision` (`:2713-2720`). So the "no cached copy" concern doesn't apply, and a slider that just writes `entry.options` is visible on the next tick with no setter at all.
- `PeakBufferTargetNumber` uses a setter because `peak_buffer_target` is a battery attribute seeded at EC construction (`energy.py:265`, `:304`). The plan names no equivalent seeding for the new values. A builder who follows the plan literally (EC setter → battery attr, fusion reads the attr) will seed nothing at construction. Between EC setup and the Number's `async_added_to_hass` push (`number.py` C3 retry-on-signal), the first ticks after a restart then run on the module default (60/80), not the persisted value. That is the restore-ordering-versus-first-tick hazard.
- Both the attr and `entry.options` would exist, and the `_inclement_config_override` test seam (`:2582`) would skip the attr path. Tests written against the override would then not exercise the production read.
- The precedent for "consumer reads options fresh, suppress the reload without a push" is `_NO_LIVE_ATTR_KEYS` (`__init__.py:7347`, e.g. `_CONF_ENERGY_MAINS_EXPORT_ENTITY`, "reads `_entity_config` fresh every tick; no live-attr push needed").

**Fix in plan:** pick one path and name it. Recommended: the Number writes `entry.options` (as PeakBuffer does). Add both keys to `_NO_LIVE_ATTR_KEYS`, not `_EC_SETTER_DISPATCH`. Add both keys and their defaults to `_inclement_config()`. Pass the values into `InclementFusion(...)` the way `partial_hold_reserve_floor` is passed. No coordinator setter, no battery attr, no seeding question. `test_blind_full_hold_floor_reads_live_slider` must drive the value through `entry.options`, not `_inclement_config_override`. If the setter path is kept, the plan must say where the battery attr is seeded at construction and add a test where tick 1 runs before the Number is added.

### H2. Pre-charge precedence over arbitrage CHARGE contradicts itself.
§6 "Reuse vs new writer" says an already-running arbitrage CHARGE (`:3961`) "composes with the fold and charges to `max(target, floor)` with no new code". But the pre-charge `return self._result(...)` is placed "immediately after the full_hold block and before the TOU branches" (`:5866`). Bottom rate is `off_peak`, and the arbitrage CHARGE lives inside the off_peak branch. On every pre-charge tick, arbitrage **does not run**:
- its phase machine, timers and chunk lock don't advance;
- when pre-charge drops out (`soc + surplus ≥ floor`), arbitrage resumes with stale phase state, possibly after its lead-time window;
- an arbitrage target of 95 is capped at 80 during pre-charge, then has to re-enter.

The builder will either (a) put the return where the plan says and break the "composes" claim, or (b) "fix" it by skipping pre-charge when arbitrage is in CHARGE, which no INV-6 clause allows.

**Fix in plan:** state the precedence explicitly. Recommended: skip the pre-charge leg when arbitrage phase is CHARGE or attain is not inactive (the fold already lifts their target to ≥ floor). Add it as a seventh refusal in INV-6(iii) and in the gate test. Otherwise state that pre-charge pre-empts arbitrage, and specify what happens to the arbitrage phase state on the ticks it skips (full_hold precedent: the return skips everything, but full_hold is rare and pre-onset spans up to 12 h of ticks).

### H3. Negative D-B6 tests pass hollowly if the classifier throws.
`_inclement_decision` catches every exception from `classifier.classify` and returns `_allow_discharge_decision(reason="classify_error")` (`energy_battery.py:2687-2693`). D-B6 adds tz-aware datetime arithmetic (`now < start ≤ now + lead`, `minutes_to(prepare_start)`, `hh:mm`). A test with a naive `now`, a malformed Onset fixture, or a `TypeError` in the new window code produces a "no floor" decision. That makes these tests green with broken code: `test_preonset_floor_none_outside_lead`, `test_preonset_lead_zero_disables`, `test_preonset_polygon_excluded`, `test_preonset_noop_byte_identical`, and every gate refusal in `test_preonset_precharge_gates`.

**Fix in plan:** every negative D-B6 test asserts `decision.reason != "classify_error"`. Each also carries a positive control in the same fixture, i.e. the same alert shifted into the window must produce a floor. Mutation drill for C: raise inside the prepare-window helper → the negative tests must go RED.

---

## MED

**M1. No hysteresis on the pre-charge condition.** `soc + _expected_solar_surplus_pct(...) < preonset_floor` is re-evaluated every tick. SOC jitter of ±1 or a Solcast refresh moves the sum across the floor, so CFG toggles on and off tick to tick (`_result` defaults `charge_from_grid=False`, `:6283`, so each fall-through tick emits a turn_off). The storm precharge doesn't have this problem because its fallback is BACKUP mode. D-B6 falls through to off_peak. Specify a latch (attain-style) or a named margin knob (rung 1), plus a test that steps SOC 59→60→59 and asserts at most one CFG transition.

**M2. Wall-clock coupling in the reused gate.** `_precharge_refused_on_blind` computes freshness as `dt_util.now() - _last_inclement_decision_at` (`:4140-4150`), while the decision is stamped with the tick's `now` parameter. A test with a synthetic `now` (e.g. 2026-01-15 03:00) and degraded telemetry is refused with "awaiting fresh storm evaluation". The builder will either freeze time inconsistently or "fix" the shared gate to take `now`, which changes the full_hold path. The plan says D-B6 "does not change" the freshness input. It should also tell the builder to freeze `dt_util.now` to the tick `now` in degraded-path tests and not edit the gate.

**M3. Reason-string inputs aren't on the decision.** The reason uses `{event}` and `onset {hh:mm}`. `InclementDecision` gains only `preonset_floor/precharge/start`, with no event name. NWS Onset carries an offset, so `hh:mm` must be `dt_util.as_local(preonset_start)`, or it renders UTC/offset time. Add `preonset_event: str | None` and say "local time".

**M4. The no-op golden can be self-referential.** "Stage B golden decisions are byte-identical" must say the golden is **captured on the pre-D-B6 commit** (Stage B D-B1–D-B5 HEAD) and committed before D-B6 code lands. Otherwise the builder regenerates it after the change and the test proves nothing. Same rule for the Stage A blind re-baseline: capture before, diff after.

**M5. The gate test list is wrong in both directions.** The "six refusals" include *fully blind* and *SOC None*, which are the same state (fully blind = SOC None on all tiers). The list omits two refusals INV-6 names: *uncorroborated watch* and *degraded-stale refusal via `_precharge_refused_on_blind`*. It also omits H2's arbitrage/attain refusal if adopted. The parametrization should be: option False, non-bottom rate, SOC ≥ floor, solar closes gap, SOC None/blind, uncorroborated watch, degraded-stale refused, [arbitrage CHARGE active].

**M6. The solar-surplus argument isn't tested across time boundaries.** `_expected_solar_surplus_pct(now, mins_to_boundary)` was written for a window ending at the next TOU boundary. Its tomorrow branch slices only `[sunrise_tom, min(boundary, sunset_tom)]` (`:4340-4360`), so lead > 24 h (§12 case 21 tests 48) silently ignores day 1 and day 2 solar. Tests that monkeypatch the helper to a constant (the obvious reading of "solar surplus 20") never check the argument. Add tests that assert the minutes argument for: Onset crossing midnight (23:00 → 10:00), pre-dawn → same afternoon (03:00 → 15:00), a DST transition night, and lead 48 (state the under-count as known, or cap the window). Require `int` minutes.

**M7. `tick_preonset` semantics on ties are unspecified.** "The registered floor came from `preonset_floor`" is ambiguous when `partial_hold` floor == prepare floor (an uncorroborated watch prepare at 50 plus an active watch at 50, or §12 case 20 at 90). The row field is the INV-6 live falsifier key. Define it: True iff `preonset_floor is not None and preonset_floor >= reserve_floor_contribution`. Better, record both `tick_preonset_floor` and `tick_floor`.

---

## LOW

- **L1.** The storm-precharge refused branch returns `BACKUP` (`:5816`). D-B6 says "fall through". A builder copying the block wholesale will copy the BACKUP return. Add one sentence: "do not copy the refused-branch return."
- **L2.** The storm precharge has a degraded-telemetry variant that suppresses the `_result` degraded suffix (`:5824-5848`). The plan specifies only the plain shape at `:5856`. Say whether D-B6 mirrors the degraded variant. The reason still starts `Inclement pre-onset`, so the falsifier is unaffected.
- **L3.** The plan's justification "no cached copy in `InclementFusion.__init__`" rests on a false premise: the fusion is rebuilt every tick. Correct it so reviewers don't hunt for a cache (ties to H1).
- **L4.** `test_preonset_precharge_routes_through_result` passes if it only asserts that `_result` was called. Require that it assert the emitted action list (CFG `turn_on` + reserve `set_value` ≥ floor), `_last_charge_from_grid_desired is True`, and that `_last_reserve_level_desired` equals the folded floor.

## Checked and found sound
- D-A3 re-key (`_tick_reserve_floor is not None` vs `hold_depth ≠ allow_discharge`) is identical before D-B6, given Stage A's "None when allow_discharge" registration. After D-B6, the de-escalation rule (precedence 1) folds to the prepare floor at blind top rate, which is correct.
- Onset handoff: the window `now < start` / hold `start ≤ now` partitions with no gap or overlap at `now == start`. A blind floor that drops at Onset (80 → 60) is covered by "hold never lowers a held value". Sighted full_hold goes to BACKUP.
- CFG turn-off after pre-charge ends: `_result(charge_from_grid=False)` default on the next fall-through tick (`:6283`, `:6543`). No orphaned turn_on.
