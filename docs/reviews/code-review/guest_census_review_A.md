# Guest Census Correctness — Tier 2-DB Review A

**Branch:** `feature/guest-census` (build worktree `.claude/worktrees/guest-census-build`)
**Range:** `eae92423c..c7c308a53` vs `develop`
**Spec:** `docs/planning/PLANNING_guest_census_correctness.md` rev-2 (`3b373d3db`) + plan-review (`b7d22574b`) + `docs/planning/RESEARCH_census_vs_guest_separation.md` (`aa3e39aa8`).
**Framing:** arithmetic correctness + invariant integrity.
**Reviewer:** A (of A/B/C for Tier 2-DB).
**Verdict:** **SHIP**.

---

## 1. INV-CENSUS-ATTRIBUTION — scalar form holds

Clamp code (`camera_census.py::_apply_enhanced_house_census`, ~L3142–L3170):

```python
camera_total_pre_cancel = int(getattr(self, "_last_camera_total_pre_cancel", 0) or 0)
raw_total_ceiling       = max(camera_total_pre_cancel, identified_count)
additive_total          = identified_count + held_unidentified
clamped_total           = min(additive_total, raw_total_ceiling)
clamped_unidentified    = max(0, clamped_total - identified_count)
```

Invariants verified over the reachable input space:

- **`total <= max(pre_cancel, identified)`** — by construction of `min(additive, ceiling)`. ✓
- **`total >= identified`** — `additive = id + held ≥ id`; `ceiling = max(pre_cancel, id) ≥ id`; therefore `min(additive, ceiling) ≥ id`. **The catastrophic "total below identified" case is impossible.** ✓
- **`unidentified ≥ 0`** — `max(0, …)` guard. ✓
- **`held == 0` → `total == id`, `unidentified == 0`** — additive=id, ceiling≥id, min=id. ✓
- **Boundary `identified > pre_cancel`** — ceiling=identified; if held>0, additive>ceiling → all held credited to identified only; `unidentified=0`. This is the correct arithmetic given the invariant (any "extra" must fit under the raw ceiling, and the ceiling is identified because cameras saw nobody). No regression.
- **`pre_cancel == 0 && held == 0`** — total=id, unid=0. ✓
- **All-zero** — total=0, unid=0. ✓
- **Cancellation transition (broken → working)** — for a fixed real-guest topology (4 residents + 1 stranger, stranger in cancellable area), the ceiling `max(pre_cancel, id)` stays at 5 while `camera_unrecognized` moves 5→1. Test `test_clamp_repaired_defenses_preserves_guest` (pre_cancel=5, cam=1, held=1) confirms `total=5, unid=1`. **Guest is preserved as cancellation repairs.** ✓ (This is the rev-1 defect the plan review caught.)

## 2. Per-value table for the live shape (coordinator ask)

Live datapoint tonight: 4 residents + 0 guests, sensor sawtoothed 4..10, hold peaked at held=6. Under this build with `identified_count = 4`, `held_unidentified = 6`, the clamp emits:

| `pre_cancel` (current tick) | ceiling | clamped_total | clamped_unid | Notes |
|-----------------------------|---------|---------------|--------------|-------|
| 0 (all cams show 0)         | 4       | 4             | 0            | Held drop-through on blink tick |
| unset (=0 from `__init__`)  | 4       | 4             | 0            | Unreachable in prod (see §4) |
| 4                           | 4       | 4             | 0            | Held fully absorbed to id |
| 5                           | 5       | 5             | 1            |               |
| 6                           | 6       | 6             | 2            | The `test_clamp_tonight_live_shape` case |
| 10 (real guest peak)        | 10      | 10            | 6            | No clamp fires; additive passes through |

- **No row emits `total < identified` (4).** ✓
- No row emits a NEGATIVE `unidentified_count`. ✓
- The `pre_cancel ∈ {0,4,5,6}` rows undercount `unidentified` relative to the additive `id+held` value; that is the plan's accepted M1 trade-off (see §4). None of them silently drops a person from `total_persons` below the identified BLE ground truth.

## 3. Rev-1 trap prevention

- **Comment guard:** `camera_census.py` L3145 explicitly instructs "MUST use the PRE-cancel scalar … DO NOT 'simplify' back to camera_unrecognized." Anchored to plan-review P1.
- **Test guard:** `test_clamp_repaired_defenses_preserves_guest` is the discriminating oracle — retargeting the ceiling to `camera_unrecognized` collapses total from 5 to 4 and fails the assertion (**D1-M1 drill re-run, verified — see §7**).
- **Staleness / ordering:** `_last_camera_total_pre_cancel` is written unconditionally at Step 2 of `_get_unrecognized_camera_count` (L2803). `_apply_enhanced_house_census` calls `_get_unrecognized_camera_count()` at L3126 immediately before reading `_last_camera_total_pre_cancel` at L3156. **Same tick, deterministic ordering.** The `__init__` default is `0`, so on the unreachable path where the read precedes any producer call, the ceiling degrades to `identified` — which cannot suppress an identified person (`total ≥ id` still holds) and cannot double-count (no held to add). Safe degrade.

## 4. Does the clamp ever suppress a REAL person?

Enumerated cases (id + held after the enhanced path's real inputs):

| Case | pre_cancel | id | held | clamp result | Suppresses real person? |
|------|-----------|----|------|--------------|-------------------------|
| Real stranger + full cancel (P1 counter-example) | 5 | 4 | 1 | total=5, unid=1 | **No** |
| Real stranger + partial cancel | 5 | 4 | 2 | total=5, unid=1 | Undercounts unid by 1; total ≥ real people. No BLE person lost. |
| Two strangers, no residents | 2 | 0 | 2 | total=2, unid=2 | **No** |
| Stranger in null-area camera (uncancellable) | 5 | 4 | 1 | total=5, unid=1 | **No** (null-area contribution enters `pre_cancel` via `unassigned_raw` at L2804) |
| Cancellation broken, 4 residents home, no guest (tonight) | 6 | 4 | 6 | total=6, unid=2 | Sensor over-reports by 2, but no real person is missing. |
| **Transient dropout mid-guest** (blink tick) | 0 | 4 | 1 | total=4, unid=0 | Sensor flaps 5→4→5 across the blink tick. Observability-only artifact. |

Under **D2** (guest arming = `guest_room_gate_armed` only, `presence.py` L5423), the census `unidentified_count` no longer participates in GUEST-entry logic. The dropout-tick flap therefore cannot regress the state machine: GUEST is armed and held by the sustained-occupied guest room path independent of the census sensor value. The census flap is a display artifact on `sensor.persons_in_house` and is bounded to a single tick (recovers when cameras next report). **Not a load-bearing suppression.**

## 5. D2b exit predicate & non-terminality

- Old: `state == GUEST AND unidentified_count == 0 AND NOT guest_gate_armed`.
- New: `state == GUEST AND NOT guest_gate_armed` (`presence.py` L1249).
- `guest_gate_armed` under D2 == `guest_room_gate_armed`. Under D2b the exit fires as soon as no guest room is sustained-occupied, regardless of any lingering census unid — the reachable cause of the 7h02m latch tonight (13:38→20:40) if D2 arming had ever fired. Under D2, arming would not have fired at all in tonight's scenario (no real guest-room sustained occupancy), so tonight's incident is doubly defused.
- **VALID_TRANSITIONS walk (`house_state.py` L82–L88):** `GUEST → {HOME_DAY, HOME_EVENING, HOME_NIGHT, AWAY}`. Exit still routes through `_time_based_home(hour)` which returns one of these. No other state's transition set was touched; no state became newly unreachable or sticky as a side effect of dropping the `unidentified_count == 0` conjunct. ✓
- **Manual override** (`HouseStateMachine.set_override`) is orthogonal to the inference exit and remains intentional bypass — unchanged. ✓

## 6. Confidence values

- Room-only: 0.9 (unchanged from v4.7.2 D5).
- Room + census corroboration: 0.95 (new; +0.05).
- Neither: 0.8 (unreachable under D2; shape preserved per the reader-friendly note at `presence.py` L5453).

Values are sane and monotone in evidence strength. The "unreachable under D2" branch is correctly noted; consistent with neighbouring `_d5_guest_confidence` uses. ✓

## 7. Independent mutation-drill re-runs

Baseline: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=quality pytest quality/tests/test_guest_census_correctness.py -q` → **19 passed**. Also `test_v4622_guest_mode_hardening.py` + `test_v472_feature_b_guest_signal.py` → **101 passed** in total.

Drills run in worktree `.claude/worktrees/review-A-guest-census` at `c7c308a53`, `__pycache__` purged before each, tree restored + reconfirmed 19-pass baseline after each.

| Drill | Mutation | Target test | Result |
|-------|----------|-------------|--------|
| **D1-M1** | `raw_total_ceiling = max(camera_unrecognized, identified_count)` (POST-cancel) | `test_clamp_repaired_defenses_preserves_guest` | **FAILED** at L223 (total=4, expected 5) ✓ |
| **D1-M2** | `total = additive_total` (delete clamp) | `test_clamp_tonight_live_shape` | **FAILED** at L201 (total=10, expected 6) ✓ |
| **D2b-M1** | Restore `unidentified_count == 0` conjunct on GUEST exit | `test_d2b_guest_exits_when_room_clears_even_if_unidentified_stuck` + `test_d2b_guest_non_terminal_from_room_clear` | **BOTH FAILED** (new_state was None — inference did not exit) ✓ |

Each anchor is load-bearing: mutating the site fails a SPECIFIC test named in the drill. Restored tree is `git status` clean; baseline 19-pass reconfirmed.

Note on D1-M1a: the mutation-anchor list in the test module docstring names D1-M1/M2/M3/D2-M1/D3-M1/M2. I read D1-M1a as the "camera_unrecognized ceiling" retarget (identical semantics to D1-M1) and executed it once.

## 8. Sensor observability

`sensor.py` diff is pure diagnostics: adds `area_raw_max_pre_cancel`, `ble_by_area`, `ble_cancel_enabled`, `camera_total_pre_cancel` and swaps `area_contributions` to the enhanced-path dict when enhanced census is active. `enhanced_area is not None` gate is correct; failing back to raw on the disabled path is safe. No arithmetic contribution to the state machine.

## 9. Findings

- **HIGH:** none.
- **MEDIUM:** none.
- **LOW-1:** `int(getattr(self, "_last_camera_total_pre_cancel", 0) or 0)` — the trailing `or 0` conflates "legitimate zero" (all cameras report count=0) with "attribute missing." Both currently degrade to the safe path (ceiling=id), so no bug, but the `or 0` will silently mask a future refactor that assigns a sentinel (e.g., `-1` for "not yet computed"). Recommend `int(getattr(self, "_last_camera_total_pre_cancel", 0))` and let a real `0` mean zero.
- **LOW-2:** Transient-camera-dropout flap on `sensor.persons_in_house` (id=4, held=1, single-tick pre_cancel=0 → sensor shows total=4 for that tick before recovering to 5). Not a state-machine regression under D2, but worth calling out in the READMEv acceptance table so the operator does not chase it. Bounded to one tick per blink.

Neither finding blocks ship.

## 10. Verdict

**SHIP.** INV-CENSUS-ATTRIBUTION is enforced in scalar form across the reachable input space; the "total below identified" catastrophic case is arithmetically impossible; the rev-1 POST-cancel-ceiling trap is guarded by a discriminating test with a load-bearing comment; D2b makes GUEST-exit strictly easier without breaking non-terminality; D3 registry-based room resolution is a real bugfix for the rename hazard. All three requested mutation drills (D1-M1, D1-M2, D2b-M1) fire the correct specific tests. Related suites (101 tests) pass clean.
