# STEP D7 Fix-Up Re-Review — Tier-3 Adversarial (Framing D)

**Cycle:** STEP chatter D7 fix-up
**Commit under review:** `292543d2c` (delta from `7f145ee84`)
**Branch:** `feature/step-chatter`
**Reviewer:** ura-reviewer (framing D — adversarial completeness, boot-safety)
**Date:** 2026-08-19
**Prior reviews:** `step_chatter_d7_review_AD.md`, `step_chatter_d7_review_BC.md`

---

## Verdicts

| Question | Verdict |
|---|---|
| Migrate boot-safe? | **YES — SAFE** |
| Mode-transition release complete? | **YES — complete across the reachable transition surface** |
| `_chatter_mode()` retirement correct? | **YES** |
| STEP core + D7 shadow seam preserved? | **YES** (40/40 D7-cycle tests pass; my per-site mutations restored; tree clean) |
| **Ship verdict** | **SHIP-WITH-FIX** — one hollow-test-anchor MEDIUM (F1) that violates Tier-3 Review-C mutation-authority; one LOW (F2, duplicate NM); one NIT (F3, stale docstring / dead helper). F1 is a test-authority defect, not a runtime defect — production code is correct. Fixing F1 in-cycle keeps the Tier-3 mutation contract honest. |

---

## 1. Migrate boot-safety (LOAD-BEARING — v5.84.0 incident class)

`__init__.py:4044-4082`. Verified against every worst-case input:

| Input | Behavior | Result |
|---|---|---|
| Fresh entry, no chatter keys | `if CONF_CHATTER_QUARANTINE_ENABLED in entry.options` = False → no-op | Safe |
| Already-migrated (key absent, mode already set) | Same — no-op | Idempotent |
| Pre-D7 bool = True, no mode | drops retired key; mode falls to `DEFAULT_CHATTER_MODE` ("shadow") | Correct |
| Pre-D7 bool = False, no mode | drops retired key; sets `CONF_CHATTER_MODE = "off"` — preserves disable-intent | Correct |
| Pre-D7 bool = False, mode already present | drops retired key; leaves operator's mode untouched | Correct (operator already chose) |
| `entry.options` malformed (non-dict) | HA guarantees `MappingProxy`/dict; even so, wrapped in `try/except BLE001` at debug — no crash | Defensive |
| Any raise inside the block | Caught, logged at debug; CM setup continues | Non-fatal |

**Cascade-reload check (Bug Class #46):** the migrate's `async_update_entry` at line 4076 runs BEFORE `entry.add_update_listener(_async_update_listener)` is registered later in the CM setup path (registration is downstream of line 4076, matching the "SAFE because they execute BEFORE" pattern the codebase already relies on at lines 1611-1615). No listener → no reload cascade → no bootstrap-2 budget hazard.

**Import-of-retired-const check:** `_CONF_CHATTER_QUARANTINE_ENABLED` is kept in the module-level import with `# noqa: F401 — migrate-only` and removed from `_NM_A2_KEYS`. Repo-wide grep confirms no other production reader:
- `coordinator._chatter_quarantine_enabled` still exists at coordinator.py:2469 but is **not called by production code** (only test-extract). Effectively dead — see F3.
- `coordinator._chatter_mode()` no longer imports or reads the retired CONF (verified in diff: the `enabled = bool(nm_cycle_a_knob(...))` guard and the `if not enabled: return CHATTER_MODE_OFF` branch are gone).

**Migrate verdict: BOOT-SAFE.** Every input path checked — no `KeyError`, `AttributeError`, or `TypeError` reachable at boot.

---

## 2. Mode-transition release completeness

`_release_all_chatter_exclusions` (coordinator.py:2367-2419) + call site at `_apply_chatter_tick` (coordinator.py:2218-2226).

Transition surface enumerated exhaustively:

| Prev → Now | Handled by | Correct? |
|---|---|---|
| act → shadow | `_release_all_chatter_exclusions` (new) | ✓ (test `test_d7_HIGH_act_to_shadow_flip_releases_chatter_exclusions`) |
| act → off | `_discharge_chatter_latches` + `_release_all_chatter_exclusions` | ✓ (see F2 for LOW double-emit) |
| shadow → off | `_discharge_chatter_latches` only (no promotions to release) | ✓ (test rewritten to `shadow→off`) |
| shadow → act | no release needed (nothing promoted yet) | ✓ (regression test `test_d7_HIGH_shadow_to_act_flip_promotes_fresh`) |
| off → shadow | no release needed | ✓ implicit |
| off → act | no release needed | ✓ implicit |
| First tick (init `_chatter_act_last=False`, `_kill_switch_last=True`) any mode | `False and not is_act_now` → no spurious release; latch discharge only fires when latches exist (empty at boot) | ✓ (init-state coherent) |
| Rapid off → act → shadow in three consecutive ticks | Second tick sets `_chatter_act_last=True`; third tick sees `True and not False` → release fires | ✓ (assuming assignment executes — see F1) |

**STEP-EXCLUDE-3 preserved under release:** verified independently by mutation — replaced `self._exclusion_set.release("chatter", _eid)` with `pass` (drill 24) and confirmed the STEP-EXCLUDE-3 test reds. My own per-site mutation of the whole release helper (removed the whole loop body) reds the same test. Also verified `_stuck_sensor_kinds.pop` is guarded by `if not self._exclusion_set.clients_for(_eid)` (B-LOW-2 provenance guard) — a concurrent stuck_dutycycle promotion keeps the label.

**Paired recovered-NM fires** for each released entity (mirror of D3 auto-release semantics). Wrapped in try/except BLE001, so a recovered-NM raise cannot break the release loop.

**Release verdict: COMPLETE.** Every reachable transition is either explicitly handled or provably a no-op.

---

## 3. `_chatter_mode()` retirement

Diff at coordinator.py:2444-2467. Verified:
- No longer imports `CONF_CHATTER_QUARANTINE_ENABLED` / `DEFAULT_CHATTER_QUARANTINE_ENABLED`.
- Module-const `CHATTER_QUARANTINE_ENABLED = True` still short-circuits to `CHATTER_MODE_OFF` if flipped False (reviewed-code safety bound — rung 1 per the "Numbers Get Knobs" ladder).
- Select "off" is the single operator-facing kill.
- No path where mode resolves to a value not in `CHATTER_MODES`; fallback returns `DEFAULT_CHATTER_MODE`.

**Correct.**

---

## 4. Regression check on STEP core + D7 shadow seam

- Ran `pytest quality/tests/test_chatter_d7_shadow_act.py quality/tests/test_chatter_tick_helper.py quality/tests/test_chatter_wire_in.py` → **40 passed in 11.46s**.
- Per-site mutation of `release("chatter", _eid)` → drill 24 reds ✓ (release helper body is load-bearing).
- Per-site mutation of the `if self._chatter_act_last and not is_act_now:` guard → drill 23 reds ✓ (transition guard is load-bearing).
- Worktree clean after all mutations restored (three untracked docs are prior review artifacts, not from this pass).

---

## Findings

### F1 — MEDIUM — Hollow-test anchor on `_chatter_act_last = is_act_now` assignment
**File:** `coordinator.py:2226`; test stand-ins at `test_chatter_d7_shadow_act.py:237`, `test_chatter_tick_helper.py:297`.
**Boot-reachability:** N/A (test-authority defect; production code is correct).
**Repro (mine, run this pass):** commented out `self._chatter_act_last = is_act_now` (line 2226); cleared `__pycache__`; ran the full `test_chatter_d7_shadow_act.py` under `PYTHONDONTWRITEBYTECODE=1` → **all 9 tests still PASSED**.
**Cause:** the stand-in `_make(...)` constructs the coord with `self._chatter_act_last = (mode == "act")` — pre-seeding the state the assignment is supposed to establish. Each test then calls `_apply_chatter_tick` once (in the initial mode), flips `coord._mode`, and calls again. With the assignment neutered, `_chatter_act_last` retains its manual pre-set value, so the transition still fires on tick 2. In production, if the assignment were absent, `_chatter_act_last` would stay at init `False` forever and `_release_all_chatter_exclusions` would **NEVER fire on a real act→shadow flip** (the HIGH bug re-emerges).
**Impact:** Tier-3 Review-C mutation-anchor contract violated (`feedback_hollow_test_anchors.md`, `feedback_unrestored_mutation_drill_poisons_evidence.md`) — the assignment is a load-bearing site with no failing-test authority. Production is correct today; a future well-meaning refactor that deletes the "obviously redundant" assignment would ship with green tests.
**Fix (in-cycle recommended):** either
  (a) add a drill in `test_chatter_wire_in.py` that mutates `self._chatter_act_last = is_act_now` → `pass` and asserts a specific test reds — but the drill needs a *test* that also fails, so also:
  (b) drop the `self._chatter_act_last = (mode == "act")` pre-set from `_make` (both stand-ins), start every test from init `False`, and prepend a warm-up tick in act mode before the flip. That way tick-1 must run the assignment for tick-2's flip to release.

### F2 — LOW — Double recovered-NM on `act → off` transition
**File:** `coordinator.py:2213` (`_discharge_chatter_latches`) + `2224` (new release call).
**Boot-reachability:** N/A (runtime transition).
**Repro (paper):** state `_chatter_kill_switch_last=True, _chatter_act_last=True`; `mode → "off"`. On the same tick, `_discharge_chatter_latches` fires `fire_stuck_signal_recovered` for every `_chatter_nm_fired` entry with message *"latch discharged (kill switch disabled)"*, then `_release_all_chatter_exclusions` fires it again for every still-promoted entity with message *"exclusion released (mode flipped act -> non-act)"*. For any entity that is both `_chatter_nm_fired` AND currently `SensorExclusionSet`-promoted (the common case — being promoted means having been NM'd), two recovered-NMs are scheduled with different wording.
**Impact:** downstream `_stuck_signal_nm._LATCHES` dedup makes the second a no-op for latch state; but two `hass.async_create_task` calls, two NM emits, two log lines. NM noise, not correctness.
**Fix:** on `act → off`, either (i) skip `_discharge_chatter_latches` when the release path will run (release already discards `_chatter_nm_fired` entries), or (ii) in `_release_all_chatter_exclusions`, skip entities already drained this tick. Defer acceptable.

### F3 — NIT — Stale docstring + dead helper
**File:** `coordinator.py:2186` (docstring), `coordinator.py:2469` (`_chatter_quarantine_enabled` def).
- Docstring of `_apply_chatter_tick` still says *"Kill-switch composed rung-1 + rung-2 via `_chatter_quarantine_enabled()`."* Post-D7 the code calls `_chatter_mode()` and derives `enabled = mode != "off"`. Update or reference `_chatter_mode()`.
- `_chatter_quarantine_enabled()` method itself is now dead production code (grep confirms only the two AST-extract tests reference the name). Safe to remove OR mark with a comment; test-extract sets would need to drop the name. Deferrable.

---

## Institutional-context / prior-art check

- `_NM_A2_KEYS` allowlist correctly no longer includes `_CONF_CHATTER_QUARANTINE_ENABLED` — matches the "reload-suppression allowlist" pattern (`ura-architecture-contract`). Import retained with `# noqa: F401 — migrate-only`.
- Bug Class #46 (update-listener cascade reload during setup) — honored: migrate runs before `add_update_listener` registration.
- `feedback_suppression_needs_discharge` — honored: the release fires the paired recovered-NM to clear the per-day latch.
- `feedback_hollow_test_anchors` — **violated on the assignment site** (F1).
- `feedback_mutation_verification_pycache_staleness` — my mutation pass ran under `PYTHONDONTWRITEBYTECODE=1` with cache cleared.

---

## Summary

The D7 fix-up correctly resolves the reviewer HIGH (mode-transition stale-exclusion) and B-MED (two-mechanism kill-switch drift). Migrate is boot-safe under every input I could construct, runs before update-listener registration so no cascade risk. Mode-transition release is complete across every reachable transition with STEP-EXCLUDE-3 preserved and provenance guards intact.

The one substantive finding is F1: the tests that "prove" the mode-transition works pre-seed the very state the assignment establishes, so the assignment site is untested by mutation. Production code is correct; test authority is not. Fixing F1 in-cycle (drop the pre-set from `_make`, add a warm-up tick) is a ~20-LoC change and keeps the Tier-3 mutation contract honest.

**Ship with F1 fix. F2 and F3 deferrable to a follow-up nit-cycle.**
