# Fan-Recheck ↔ D2 Deadlock — Review C (Test Authority + Fixture-Seam Adjudication)

**Cycle:** FAN-RECHECK-D2-DEADLOCK-1
**Branch / commit:** `feature/fan-recheck-deadlock` @ `ce4437c69`
**Framing (Tier 2-DB Review C):** test authority, mutation-anchor integrity, fixture-seam adjudication
**Baseline:** `develop`
**Suite result on this worktree:** `57 passed, 0 failed` (targeted cycle files)

---

## TL;DR — verdict

- **Shippability:** **SHIP-with-live-validation** (SHIP, contingent on the live-validation table specified in §5 being written back into the README post-restart).
- **Fixture seam:** the "cannot in-suite behaviorally test the D2 OR-composition without a real `UniversalRoomCoordinator`" claim is **REAL** — v5.8.0 territory confirmed. The builder did not give up too early on the load-bearing surface. They DID give up too early on ONE surface: D3 per-room isolation in `presence.py` (see F-C-2 below).
- **Test authority for the load-bearing surface (`is_recheck_eligible` purity + happy-path)** is real, mutation-anchored, and discriminating. This is the fixture-seam success of the cycle.
- **Test authority for the D2 wiring** (`coordinator.py:3409-3440`) rests on static review + live sensor observation, not in-suite. Given the bug itself was discovered live and the fix is live-observable via `sensor.<room>_fan_recheck_state`, this is an acceptable seam FOR THIS CYCLE. It is not a precedent — Tier 3 wiring cycles should extract a testable helper.

---

## 1. Test-by-test adjudication (are the new tests REAL or HOLLOW?)

Framework: a REAL test drives production code through its live callable
surface and its oracle discriminates the fix from a plausible different
failure. A HOLLOW test either re-implements the shape it claims to
verify, uses a stubbed producer that hard-codes the answer, or is a
grep/import assertion masquerading as behavior.

### 1a. `test_fan_recheck_d2_deadlock.py` (7 tests, +242 lines)

| Test | Status | Mutation-anchor verified |
|---|---|---|
| `test_is_recheck_eligible_purity_no_veto_counter_mutation` | **REAL** | Yes — swap `sink=_INERT_SINK` → `sink=_LiveSink(self)` in `is_recheck_eligible` and the veto counter climbs by 100 vs baseline; test flips red. Load-bearing on the inert-sink contract. |
| `test_is_recheck_eligible_purity_no_ladder_layer_mutation` | **REAL** | Yes — the L1 branch calls `sink.set_ladder_layer(ctx, LAYER_L1)`. If routed to the live sink, `ctx.ble_ladder_layer` flips from `LAYER_NONE` to `LAYER_L1` on the first probe. |
| `test_is_recheck_eligible_purity_no_attempts_mutation` | **REAL** | Yes — seeds a 2h-old attempt; `_prune_attempts` would strip it; if routed to live sink → `len == 0` vs baseline. |
| `test_is_recheck_eligible_returns_true_for_armable_room` | **REAL** | Drives the full 9-gate `_evaluate_eligibility` via the read-only surface without ever calling `on_room_tick` — this is exactly what D2 does. Happy-path oracle. |
| `test_is_recheck_eligible_returns_false_for_master_off` | **REAL** | Discriminates master-off from other veto reasons. |
| `test_is_recheck_eligible_returns_false_before_setup` | **REAL** | Advisory-4 backstop contract — if this ever silently returns True, D2 gets house-wide-defeated. Load-bearing. |
| `test_is_recheck_eligible_returns_false_for_unknown_room` | **REAL** | Room-coord resolver miss → False. |
| `test_is_recheck_eligible_returns_false_on_raise` | **REAL** | Monkey-patches `_room_coord_for` to raise. Verifies the outer `except Exception` returns False (D2 backstop). |
| `test_d3_per_room_isolation_pattern_directly` | **HOLLOW** (see F-C-2) | Re-implements the try/except pattern in the test body and asserts against its own re-implementation. Zero anti-regression value against `presence.py:6890-6924`. |

### 1b. `test_fan_recheck_mode2_cycle.py` — sleep-scope test rewrites (+59 / −33 lines)

The prior sleep tests (`test_sleep_house_state_blocks_trigger`, `test_waking_house_state_does_not_block_trigger`, `test_sleep_begins_during_arm_delay_aborts_before_pause`) are DELETED and replaced by **5 new tests** that cover the widened `FAN_TRUST_STATES × bedroom` predicate:

| Test | Status | Discriminating oracle? |
|---|---|---|
| `test_sleep_bedroom_preserved_v4_7_13_contract` | **REAL** | Yes — asserts `vetoes["sleep_state"] >= 1` (discriminates from `not_occupied` etc.). |
| `test_sleep_non_bedroom_arms_post_scope_fix` | **REAL** | Would have flipped red pre-fix; locks the widening motivation. |
| `test_home_night_bedroom_vetoed_by_scoped_predicate` | **REAL** | Locks the `home_night` extension for bedrooms; discriminates via `vetoes["sleep_state"] >= 1`. |
| `test_waking_house_state_does_not_block_non_bedroom` | **REAL** | Positive-case bookend. |
| `test_sleep_begins_during_arm_delay_aborts_before_pause_bedroom` | **REAL** | Drives `_still_armed_eligible` after live house_state mutation. |
| `test_still_armed_non_bedroom_survives_sleep_edge` | **REAL** | Discriminates from the "hollow narrow one gate, not the other" mistake — this is exactly the kind of test that separates surgical fix from over-scoped regression. |

**These 6 rewrites are the strongest single test-authority improvement in the cycle.** The pre-fix suite had ONE sleep test with an oracle of "state == IDLE" — indistinguishable from any other veto reason. The post-fix suite has 6 tests with 6 discriminating oracles across `{bedroom, non-bedroom} × {home_night, sleep, waking, home_day}`. This is exactly the discipline the operator called out on 2026-08-16 ("acceptance criteria must discriminate").

### 1c. Fixture is NOT the v5.8.0 poison pattern

`_FakeRoomCoord` is a hand-built stub (`_build_world` seeds `recent_sources=["mmwave", "mmwave", "mmwave"]` by default). Concern raised in the review brief: does any of the NEW behavioral claims silently re-use this hardcoded-occupancy stub for a claim it can't support?

**Verdict: no.** The purity tests explicitly do NOT drive the 9-gate happy path — they drive to a veto (master_off / L1 / rate-cap-seed) whose outcome is unambiguous given the stub. The happy-path test (`test_is_recheck_eligible_returns_true_for_armable_room`) DOES rely on the stub's hardcoded `occupancy_source="mmwave"` and `recent=[mmwave,mmwave,mmwave]`, but the CLAIM ("the probe returns True when all 9 gates pass") is legitimately answered at that fixture altitude — the fixture is the *definition* of "all 9 gates pass". This is not a hollow claim; it's a scoped claim.

Where the fixture WOULD be hollow is if a test claimed "the D2 coordinator block correctly consults `is_recheck_eligible` and defers demotion when it returns True." No such test exists in-suite (see §2).

---

## 2. Fixture-seam adjudication — is the un-tested D2 wiring genuinely infeasible in-suite?

The load-bearing change on the coordinator side is `coordinator.py:3383-3448` (`recheck_eligible` probe + OR-composed defer branch). No test drives this code path.

### 2a. Can it be tested WITHOUT a real `UniversalRoomCoordinator`?

**Extractable-helper option (evaluated, rejected):** Extract the OR into
```python
def _should_defer_fan_recheck_demote(in_flight: bool, eligible: bool) -> bool:
    return in_flight or eligible
```
and unit-test it. This is trivially green and proves nothing beyond that `or` works in Python. It does NOT prove:
- That D2 actually calls `is_recheck_eligible(room_name)` with the right room name.
- That when the probe returns True, D2 takes the defer branch (not the demote branch).
- That the `_mmwave_fan_demoted_last_tick` bookkeeping still resets on defer.
- That the DEBUG log is emitted so operators can see which reason fired.

A helper extraction here is **fixture theater** — it green-checks a signature that has never been the risk, while the actual risk (call-site wiring) stays uncovered. The operator's canonical anti-pattern for "hollow anchors" applies directly.

**Narrow-harness option (evaluated, rejected for THIS surface):** Build a
harness that instantiates enough of `UniversalRoomCoordinator` to reach
`_async_update_data`'s D2 block. This is v5.8.0 territory — the setup
path recursed and crashed all 40 rooms because tests used a fake
coordinator that never exercised real construction. Reopening that seam
for one wiring assertion is disproportionate.

**Real-coord fixture (rejected):** Constructing a real coord requires
functional HA dispatcher + entity registry + config_entry registration +
DB write queue + 40+ sensor initializers. The bug that this fix was
built to break was ITSELF confirmed live not in-suite — that historical
fact bounds what in-suite authority could ever have caught.

### 2b. VERDICT on the D2 wiring seam

**The seam is REAL.** The builder did not give up too early. The D2 OR-composition is a call-site wiring change with no arithmetic and no state, whose failure modes are:
- Probe never called → covered by static review (grep + diff), live-observable (`fan_recheck_eval_count` stays at 0 when it should climb).
- Probe called but return ignored → covered by static review (the `if recheck_in_flight or recheck_eligible:` is diff-visible), live-observable (`not_occupied` veto counter climbs monotonically on affected rooms).
- Probe returns True when it should return False → covered by 9 in-suite tests on the read-only surface.
- Probe returns False when it should return True → covered by `test_is_recheck_eligible_returns_true_for_armable_room` and the sleep-scope suite.

Rollback is trivial (revert the OR branch, D2 fires as before). Blast radius is bounded (per-tick, per-room, additive gate).

### 2c. Where the seam DID collapse — F-C-2

**`test_d3_per_room_isolation_pattern_directly` is hollow.** The test builds two toy classes in the test file, wraps them in a `try/except`, and asserts the sibling runs. It never touches `presence.py:6890-6924`. The docstring acknowledges this and claims "the actual fan-out loop lives inside the presence coord's tick, which requires a full presence coordinator to construct in-suite" — but this claim is weaker than the D2 case, because:

The D3 change is a plain `for` loop with per-iteration `try/except`. It is trivially extractable into a helper:
```python
def _fan_out_room_ticks(entries, manager, hass_data, logger) -> None:
    for entry in entries:
        # entry-type filter, room_coord resolution, per-iteration try/except
```
The helper takes injectable arguments (entries iterable, manager, hass.data, logger) — no HA lifecycle needed. A real per-room isolation test would call this helper with a list containing a `Mock` that raises + a `Mock` that records, and assert the recorder ran. That is genuinely stronger than the current shape assertion.

**Finding F-C-2 (MEDIUM — should be fixed but not blocking):** Either delete `test_d3_per_room_isolation_pattern_directly` (it has zero anti-regression value against the actual code) or extract the D3 fan-out into a helper and drive the helper directly. The current state is worse than deletion because it gives false confidence.

---

## 3. Findings summary

| ID | Severity | Class | Location | Status |
|---|---|---|---|---|
| F-C-1 | LOW | Non-load-bearing test presentation | `test_fan_recheck_d2_deadlock.py` module docstring | INFO |
| F-C-2 | MEDIUM | Hollow test anchor (structural re-implementation) | `test_fan_recheck_d2_deadlock.py:test_d3_per_room_isolation_pattern_directly` | RECOMMEND FIX (not shipping-blocking) |
| F-C-3 | LOW | D2 wiring untested in-suite (seam adjudicated real) | `coordinator.py:3383-3448` | ACCEPTED SEAM — mitigated by live-validation §5 |
| F-C-4 | INFO | Purity test suite is exemplary | `test_fan_recheck_d2_deadlock.py:32-138` | STRONG — cite as template for future inert-sink patterns |

**No CRITICAL. No HIGH.**

### F-C-1 (LOW): docstring says the D2 side is "covered by review C mutation-anchoring against the real coordinator.py block"

This is aspirational. Review C (this document) does NOT run source mutations against the coord block — the mutation would be along the lines of "delete the OR branch → some test fails" and there is no such test (see §2). Recommend adjusting the docstring to say "the D2 defer wiring on the coordinator side is covered by static review + post-deploy live validation of `sensor.<room>_fan_recheck_state`." Truth in advertising.

### F-C-2 (MEDIUM): see §2c above. Not shipping-blocking because D3 isolation is a trivial per-iteration try/except and its regression would be immediately visible in HA logs as `FanRecheck: on_room_tick failed for room=X` at WARNING (a genuine improvement over the pre-fix silent DEBUG swallow) — the fix's own logging is its regression tripwire.

### F-C-3 (LOW): see §2b. Accepted for this cycle.

---

## 4. Shippability recommendation

**SHIP-with-live-validation.**

Rationale, weighed against the session's hollow-test history:

**In favor of ship:**
- The load-bearing purity contract IS unit-tested with proper mutation-anchoring (three purity tests + Advisory-4 backstop) — this is the discipline the hollow-test incidents demanded.
- The sleep-scope rewrite adds 6 discriminating oracles where 1 non-discriminating oracle existed before.
- The D2 wiring change is a pure OR of two probe results with trivial rollback.
- The D3 change strictly improves observability (silent DEBUG swallow → per-room WARNING).
- The bug this fixes was itself confirmed live not in-suite — the diagnostic pathway that FOUND it is the same pathway that will PROVE the fix works.
- Blast radius is bounded per-tick, per-room, additive; failure mode "D2 never fires" is loud (mmwave-only rooms would never demote, immediately visible on the fan_recheck_state sensor and on live occupancy sensors).

**Against ship (must be mitigated):**
- No in-suite test drives the D2 OR-composition itself. This is the seam. It is real (see §2b) but it is not zero.
- One test is hollow (F-C-2). This does not affect the shipped code but it inflates the apparent test count and should be addressed.

**Mitigation = §5 live-validation table, written back into the README per the 2026-06-05 operator rule.**

Blocking an in-suite behavioral test on this cycle would either (a) re-open v5.8.0 territory, or (b) build a helper harness that doesn't materially improve authority over static review + live validation. Neither is worth the delay for a fix whose motivating bug has been live for 5 days.

---

## 5. Live-validation spec — MANDATORY post-restart, write results back into README

The prompt asked for the EXACT observations that would prove the fix works. Each observation is stated with the discriminator from the failure mode.

### 5.1 Fix-works observations

**Sensor authority:** `sensor.<room>_fan_recheck_state` (per-room attributes). Read via home-assistant MCP.

Pick a room that historically triggered the deadlock — an mmwave-sole occupied room with a fan on outside sleep (Exercise, Study A, or Living Room per Jaya-bedroom's known behavior).

| Observation | PASS oracle | Discriminates from |
|---|---|---|
| **O1: probe firing** | `attributes.fan_recheck_eval_count` INCREMENTS by ≥1 within 3 minutes of a mmwave-sole tick sequence | pre-fix (counter stuck at 0 for the room because `on_room_tick` never got past the `not_occupied` veto — but note this counter climbed via other paths pre-fix too, so O1 alone is not sufficient) |
| **O2: deadlock broken — veto shape** | `attributes.fan_recheck_veto_counts.not_occupied` on the affected room does NOT climb monotonically on every presence tick (climb rate should drop by ≥ order of magnitude vs pre-fix baseline) | The pre-fix signature was `not_occupied` incrementing on EVERY tick because D2 kept flipping `occupied=False` before the recheck could arm. |
| **O3: recheck reaches ARMED at least once** | `state` attribute (or `fan_recheck_state.state`) transitions IDLE → ARMED for at least one affected room within 60 minutes of a real mmwave-sole occupancy | pre-fix: room could NEVER reach ARMED under the deadlock scenario |
| **O4: end-to-end vacate** | On a real vacate: `attributes.last_release_ts` updates AND the room's `occupancy_source` briefly shows `fan_recheck_release` AND `binary_sensor.<room>_anyone_home` flips off | pre-fix: the room got demoted by D2 immediately instead of waiting for the recheck; no `fan_recheck_release` provenance ever appeared for that vacate |
| **O5: DEBUG logs emitted** | HA log scan shows `Room <name>: D2 defer -> fan-recheck-defer:eligible` at least once during the observation window (requires DEBUG logging on `custom_components.universal_room_automation.coordinator`) | Static-review confidence bump; not load-bearing but confirms the branch actually fires. |
| **O6: D3 per-room isolation working** | If ANY room raises inside `on_room_tick` during the window (unlikely organically), the log shows `FanRecheck: on_room_tick failed for room=<name> (isolated — sibling rooms unaffected)` at WARNING and OTHER rooms' `fan_recheck_eval_count` still climbs on that tick | pre-fix: entire fan-out loop bailed at DEBUG; siblings' counters stalled together |

### 5.2 Fix-doesn't-over-defer observations (the "hollow narrow one gate" trap)

The failure mode of a naive fix would be "always defer D2" (defer even when the recheck would legitimately veto). Confirm the discriminator:

| Observation | PASS oracle | Discriminates from |
|---|---|---|
| **O7: bedroom-during-sleep still demotes** | Pick a bedroom (Jaya, Master). During overnight sleep, if mmwave lingers with no PIR, D2 SHOULD still demote at the standard mmwave-linger boundary. Verify at least one such demote in the overnight sleep window: `attributes.mmwave_fan_demoted_last_tick` toggles True at least once. Discriminator: `sensor.<bedroom>_fan_recheck_state.veto_counts.sleep_state` climbs on those ticks (proving `is_recheck_eligible` returned False and D2 fired as backstop). | A naive "always defer" fix would leave bedroom mmwave stuck-on forever during sleep. |
| **O8: rooms with fan off still demote when applicable** | A room with no fan on but mmwave-sole PIR-stale: D2 demotion still fires because `is_recheck_eligible` returns False via `no_fan_on` veto. Discriminator: log shows D2 demote without a preceding `D2 defer -> fan-recheck-defer:eligible` entry for that room. | Confirms probe is answering per-room, not universally True. |

### 5.3 Suite-only invariants (not live-verifiable)

- Purity of `is_recheck_eligible` (no mutation of veto/eval counters, ladder layer, attempts) — proven in-suite by the 3 purity tests, cannot be observed live (any live observation would itself be a probe that mutates state via `on_room_tick`).
- `is_recheck_eligible` returns False before `_setup_done` — proven in-suite; live boot window is brief and difficult to observe.

---

## 6. Test authority verdict — cycle-level summary

- **Real, mutation-anchored, discriminating:** 9 of 10 new tests, all 6 sleep-scope rewrites.
- **Hollow (structural re-implementation):** 1 test (F-C-2).
- **Untested-but-adjudicated-seam:** D2 OR-composition wiring (real seam, mitigated by §5 live-validation).
- **Fixture poison risk (v5.8.0 pattern):** none introduced. `_FakeRoomCoord` is used only for claims scoped to that fixture altitude.
- **Overall test-authority delta vs pre-cycle:** materially positive. The sleep-scope discriminator improvement alone is the kind of test-authority upgrade the operator has been asking for.

---

## 7. Recommendations

1. **SHIP.** Include §5 live-validation table in `docs/readmes/README_v<version>.md` as prospective, then write observed results back per 2026-06-05 rule.
2. **Address F-C-2 in a follow-up (not blocking):** either delete `test_d3_per_room_isolation_pattern_directly` or extract the D3 fan-out into a helper and test it directly. Filing as a kanban card is appropriate.
3. **Adjust F-C-1 docstring** to reflect that Review C's authority for the D2 wiring is static-review + live-validation, not "mutation-anchoring against coordinator.py".
4. **Do not treat this cycle as precedent for skipping in-suite wiring tests.** The D2 seam is real HERE because of v5.8.0 and because the wiring is a pure OR of two probes with trivial rollback and loud failure modes. Future wiring cycles with arithmetic, state, or timing should extract a testable helper.
