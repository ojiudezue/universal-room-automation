# PLANNING v4.6.2.3 — Review Carry-Overs from v4.6.2.1 + v4.6.2.2

**Status:** Plan complete, ready to implement
**Tier:** Tier 1 hotfix bundle (≤4 files, 2 narrow bug shapes + LOW cleanups, no schema/lifecycle changes)
**Predecessor:** v4.6.2.2 (Guest mode hardening — deployed 2026-05-14)
**Soak-safety:** Both fixes are narrow and additive to existing code paths. Touches only `automation.py`, `hvac_fans.py`, `presence.py`. No interaction with routine-awareness, regime detector, or census flow beyond reading existing values. Safe to ship during v4.6.2 soak.

## Why

Both prior Tier 1 reviews left small carry-overs flagged in `docs/BACKLOG.md`. Bundle into one short cycle so they don't bit-rot:

**From v4.6.2.1 review (`docs/reviews/code-review/v4.6.2.1_humidity_fan_hardening.md`):** The two MEDIUMs share the same shape: on options-flow reload while a humidity fan is running, the in-memory `_humidity_on_since` anchor resets to `None`. If humidity is in the hysteresis band on the next eval, neither activate nor off branch fires and the anchor never re-seeds → max-runtime cap silently disables until the fan fully cycles off→on. That defeats the cycle's stated purpose (stuck-sensor cap) for in-flight fans. Plus Path A's behavioral tests are source-grep (LOW #8/#9), which is why the MEDIUM made it past the build agent.

**From v4.6.2.2 review (`docs/reviews/code-review/v4.6.2.2_guest_mode_hardening.md`):** `_handle_census_update` only triggers `_run_inference` on count change — a confidence-only upgrade (e.g., `low → high` with counts unchanged) waits up to one 60s periodic cycle before the gate re-evaluates. Bounded delay, not blocking, but trivial to fix. Plus a dead `_census_source_agreement` field and one test-stub drift risk.

## Scope

### A. Reload-mid-cycle state-anchor seeding (both paths)

When the coordinator wakes (post-reload or post-restart) and observes a humidity fan already ON, seed `_humidity_on_since = now` so the max-runtime cap has a valid reference point. Without this seeding, the cap can't fire because elapsed-time is computed against `None`.

**Symmetric in both paths:**

- **Path A (`automation.py`)** — at top of `handle_humidity_based_fan_control`, after threshold computation: if `_humidity_on_since is None` AND any of the configured humidity fans is observed in state `on` (via `hass.states.get`), set `_humidity_on_since = now` and `_humidity_fan_triggered_time = now`.
- **Path B (`hvac_fans.py`)** — in the humidity-fan eval block after `h_currently_on` is computed: if `h_currently_on and room_fan.humidity_on_since is None`, set `room_fan.humidity_on_since = now`.

Add a tiny helper in Path A `_fan_is_actually_on(fans: list[str]) -> bool` that returns True if any entity in the list reports `state == "on"`. Reuse the same pattern in Path B's `_is_entity_on` (already exists at `hvac_fans.py:344`).

### B. Behavioral test coverage for Path A

Replace the source-grep tests (LOW #8/#9) with at least one end-to-end test that constructs a stub `automation.py` instance, primes config with humidity fans + threshold + max_runtime, drives `handle_humidity_based_fan_control` across a humidity sequence, and asserts:
- Cap fires after max_runtime
- Re-trigger suppression holds until humidity drops below OFF threshold
- Reload-mid-cycle scenario: instantiate, simulate "fan was already on", call once → assert `_humidity_on_since` is seeded
- Hysteresis: no chatter near threshold

These tests would have caught both MEDIUMs at build time.

### C. Confidence-change reactivity in `_handle_census_update`

In `domain_coordinators/presence.py` `_handle_census_update`, extend the change-detection check (currently `if old_count != self._census_count or old_unidentified != self._unidentified_count:`) to also include confidence:

```python
old_confidence = self._census_confidence
# ...assignments...
if (
    old_count != self._census_count
    or old_unidentified != self._unidentified_count
    or old_confidence != self._census_confidence
):
    self.hass.async_create_task(self._run_inference("census_update"))
```

Single-line shape change. Closes the up-to-60s delay on confidence-only upgrades.

### D. Dead field + test stub drift cleanups

- **`_census_source_agreement` (LOW #2 from v4.6.2.2 review):** captured in `_handle_census_update` but never read. Either remove the field entirely OR wire it as a future-proof hook (e.g., a strict mode that requires `both_agree` for `high` confidence). For this cycle, **remove the field** — wiring it is a design decision deferred until needed. If reinstated later, add it back deliberately with a planning rationale.
- **Test stub re-implementation (LOW #7 from v4.6.2.2 review):** A subset of tests in `test_v4622_guest_mode_hardening.py` constructed a stub that mirrors `_guest_gate_armed`'s logic instead of calling the real method. Refactor those tests to instantiate a real `PresenceCoordinator` (with mocked `hass` + `entry`) and call `_guest_gate_armed` directly. Production-code drift risk: if `_guest_gate_armed` evolves, the stub tests would silently still pass.

### Out of scope (deferred again)

- **LOW #3 — Sleep policy clears `_humidity_cap_suppressed`.** Edge case; minimal user impact. Defer to a future small touch on `automation.py`.
- **LOW #4 — HVAC-managing transition leaves stale Path A state.** Edge case (HVAC management toggled mid-day is rare). Defer.
- **LOW #5 — Cap-fire clears `_humidity_fan_triggered_time` undocumented.** Comment-only. Will fold into the D2 docstring update.
- **`_humidity_cap_suppressed` Path A field naming asymmetry with Path B.** Cosmetic.

## Deliverables

### D1 — Path A anchor seeding + helper

Modify `automation.py:handle_humidity_based_fan_control` to add the reload-aware seeding block at the top of the function (after `humidity_fans = ...` and threshold reads, before the activate/deactivate branches). Add `_fan_is_actually_on(self, fans: list[str]) -> bool` helper.

**Acceptance Criteria**
- **Verify:** New unit/behavior test `test_path_a_seeds_on_reload_when_fan_already_on` instantiates `RoomAutomation` with humidity fan config, mocks `hass.states.get` to return `state="on"` for the fan, calls `handle_humidity_based_fan_control(humidity=75)` once. Assert `self._humidity_on_since is not None` and equal to `now`.
- **Verify:** With fan observed off + humidity below threshold, anchor stays `None`.
- **Test:** `test_path_a_seeds_on_reload_when_fan_already_on`, `test_path_a_anchor_only_seeded_when_fan_actually_on`.

### D2 — Path B anchor seeding

Modify `hvac_fans.py:update()` humidity-fan block to seed `room_fan.humidity_on_since = now` when `h_currently_on and room_fan.humidity_on_since is None`. Add docstring noting reload-resilience and the v4.5.18-style "fresh signal must arrive before re-trigger after cap" pattern.

**Acceptance Criteria**
- **Verify:** Construct `HVACFanController`, register a room with `humidity_fan_entities=["fan.bath"]`, mock `_is_entity_on("fan.bath") → True`, call `update()` once. Assert the room's `humidity_on_since` is set.
- **Verify:** Subsequent ticks with the same fan-on state do NOT overwrite (`humidity_on_since` is monotonic; only cleared on turn-off).
- **Test:** `test_path_b_seeds_on_reload_when_fan_already_on`, `test_path_b_anchor_is_monotonic_while_fan_on`.

### D3 — Path A behavioral test suite (replaces source-grep)

New file `quality/tests/test_v4623_humidity_fan_behavioral.py`. Stubs `RoomAutomation` with a fake `hass`, `_safe_service_call` recorded as a side-effect log, and a humidity-driver fixture. Covers:

- `test_max_runtime_cap_fires_after_full_window` — drive humidity at 75% for max_runtime+1 seconds; assert turn_off called.
- `test_max_runtime_suppression_blocks_immediate_retrigger` — after cap fires, drive humidity at 75% again immediately; assert NO turn_on call until humidity dips below `threshold - 10%`.
- `test_max_runtime_suppression_clears_when_humidity_drops_below_off` — drive humidity 75% → cap → 75% (still suppressed) → 45% (clears suppression) → 75% again (allowed); assert turn_on called.
- `test_hysteresis_no_chatter_at_threshold_boundary` — humidity oscillates 58↔62 with threshold=60; assert fan turns on once and stays on across the oscillation (single turn_on call).
- `test_reload_seeds_humidity_on_since` — already covered in D1, but include the end-to-end variant here.

**Acceptance Criteria**
- **Test count:** 5 new behavioral tests; all pass.
- **Coverage:** all four MEDIUM-equivalent scenarios from the v4.6.2.1 review are exercised through `handle_humidity_based_fan_control` directly, not via source-grep.

### D4 — `_handle_census_update` confidence reactivity

One-line change to `presence.py:_handle_census_update`'s change-detection condition to also include `_census_confidence`. Capture `old_confidence` before the field reassignment.

**Acceptance Criteria**
- **Verify (behavioral):** Stub `PresenceCoordinator`, dispatch SIGNAL_CENSUS_UPDATED twice with same counts but different confidence (`low → high`). Assert `_run_inference` task was scheduled both times (not just on first dispatch).
- **Test:** `test_confidence_only_change_triggers_inference`.

### D5 — Dead field removal: `_census_source_agreement`

Remove the assignment + field declaration from `presence.py`. Verify no other code reads it (grep first to confirm — should be zero hits beyond the assignment itself).

**Acceptance Criteria**
- **Verify:** `grep -n "_census_source_agreement" custom_components/universal_room_automation/` returns 0 hits after removal.
- **Test:** existing v4622 tests must still pass without modification (the field was never asserted on).

### D6 — Test stub drift refactor

In `test_v4622_guest_mode_hardening.py`, find tests that construct a stub mirroring `_guest_gate_armed` logic. Refactor those to instantiate a real `PresenceCoordinator` (with mock `hass`, mock `entry`) and call `_guest_gate_armed` directly. List of tests touched should be in the commit message.

**Acceptance Criteria**
- **Verify:** Affected test file no longer contains a function body that re-implements the gate logic.
- **Verify:** All v4622 tests still pass after the refactor.
- **Test:** No new tests required; this is a quality-of-existing-tests change.

## Files touched

- `custom_components/universal_room_automation/automation.py` — Path A seeding + `_fan_is_actually_on` helper (~15 LoC)
- `custom_components/universal_room_automation/domain_coordinators/hvac_fans.py` — Path B seeding (~5 LoC)
- `custom_components/universal_room_automation/domain_coordinators/presence.py` — confidence reactivity (~5 LoC) + dead field removal (~3 LoC)
- `quality/tests/test_v4623_humidity_fan_behavioral.py` — new file (~150 LoC)
- `quality/tests/test_v4622_guest_mode_hardening.py` — confidence-trigger test + stub-drift refactor (~30 LoC net)

## Cost

- Production: ~30 LoC across 3 files
- Tests: ~180 LoC across 2 files (1 new, 1 modified)
- Tier 1 review (one staff-engineer pass; mental execution on the seeding flow specifically)

## Risks

1. **Seeding logic asymmetry between paths.** Path A reads from `hass.states.get` at function entry; Path B reads via `_is_entity_on` in the update loop. The behavior should be identical post-fix. Mitigation: parallel test cases in both paths.
2. **Path A `_fan_is_actually_on` async-safety.** `hass.states.get` is a synchronous lookup of in-memory state — safe to call from any context. Not an executor-job candidate.
3. **Dead field removal collateral.** If any external consumer (a custom sensor or dashboard YAML) read `_census_source_agreement` via attribute, removing it would break them. Audit first: `grep` confirms only one assignment site, no readers. Safe to remove.
4. **Behavioral test brittleness.** New tests in D3 depend on `_safe_service_call` being captured. If the underlying call site refactors (e.g., direct `hass.services.async_call`), tests need updating. Acceptable — that's what behavioral tests cost.
5. **Confidence-trigger test (D4) timing.** The test must verify that `async_create_task` was called, not that inference fully ran. Mock the task creation; don't try to await the actual inference.

## Review checklist

- [ ] Both paths seed `humidity_on_since` on observed-on-at-startup AND clear it on turn-off — symmetric lifecycle.
- [ ] No regression in the cap-fire suppression flow (suppression must still require humidity below OFF threshold to clear).
- [ ] `_handle_census_update` confidence-trigger does NOT inadvertently double-fire when count + confidence both change in the same dispatch.
- [ ] Dead field removal verified by grep before commit.
- [ ] All five new behavioral tests in D3 actually call into `handle_humidity_based_fan_control`, not just assert string presence.
- [ ] No module-level imports introduced that could trigger Bug Class #34.
- [ ] No stale references to `_census_source_agreement` in tests, sensor.py, or any subscriber.

## Live validation post-deploy

1. Confirm v4.6.2.1's stated purpose now works under reload: reload a room entry that has humidity fans configured while one is running (test in a safe room or simulate). Verify `_humidity_on_since` survives by triggering a cap-fire scenario and observing the INFO log entry. Alternatively, observe over a normal day — no behavior change expected unless a reload happens.
2. Confirm v4.6.2.2's confidence-trigger fix: watch census_confidence transitions in HA logs (`grep "confidence" home-assistant.log` for URA-emitted events). When confidence changes without count changing, `_run_inference` should fire within 1–2 seconds, not 60s.
3. Confirm no regression in the v4.6.2.2 guest gate: house should not flip to `guest` for transient unidentified blips. Compare 24-h flip rate to baseline.

## Plan completion tracking

After v4.6.2.3 ships, the following remaining items from v4.6.2.1 + v4.6.2.2 reviews are STILL deferred:

- LOW #3 (sleep clears suppression) — defer
- LOW #4 (HVAC-managing transition stale state) — defer
- LOW #5 (cap-fire clears triggered_time undocumented) — folded into D1/D2 docstrings
- (No remaining items from v4.6.2.2)

These remain in `docs/BACKLOG.md` for a future polish pass.
