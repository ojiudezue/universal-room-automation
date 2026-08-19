# STEP Chatter-Quarantine — Review A (Data-integrity + Exclusion-set preservation + Consumer enumeration)

- **Branch:** `feature/step-chatter` @ 07b3ad116
- **Diff base:** `develop...feature/step-chatter` (verified — worktree at `.claude/worktrees/step-chatter`)
- **Framing:** A — byte-identity of the shipped v5.75.0 exclusion behaviour under the shared `SensorExclusionSet` migration; consumer enumeration of the exclusion feed and the `_chattering_entities` mirror; D2-raise Reading-A verification.
- **Tests run (cycle only):** `test_sensor_exclusion.py test_chatter_detector.py test_unavailable_entities_chatter.py test_chatter_wire_in.py` → **40 passed**.

---

## Verdict

**SHIP-WITH-FIX** — one MEDIUM (M-A1, tick-rate task scheduling for chatter STUCK NM) and one MEDIUM (M-A2, hollow test anchor on the Reading-A invariant). No CRITICAL/HIGH under this framing. Byte-identity claim holds; consumer enumeration clean; STEP-EXCLUDE-{1..4} preserved under the migration.

---

## Byte-identity verdict (the load-bearing claim of this framing)

**PASS** at the 6 fusion sites (`coordinator.py:2891-2942`) and on the D2-raise branch (`coordinator.py:2774-2796`).

**Fusion sites — semantically identical to pre-cycle `sensor not in stuck_sensors`:**
- The three "any(...) filter" comprehensions and the three "track which sensor triggered" loops now read `not self._exclusion_set.is_excluded(sensor)`.
- Per-tick ordering is `reset_tick()` (2560) → P22 promote loop (2567-2570, in **lock-step** with the `stuck_sensors = self._p22_stuck_sensor_set(now)` assignment two lines earlier) → D2/D1 promote loop (2647-2649, `stuck_sensors.add(s)` + `_exclusion_set.promote("stuck_dutycycle", ...)` at the same call site) → chatter promote loop (2832-2836, `stuck_sensors.add(_ceid)` + `_exclusion_set.promote("chatter", ...)` at the same call site). At every tick, `set(self._exclusion_set)` `== stuck_sensors` at the moment the fusion sites read it. `is_excluded(x)` `== (x in stuck_sensors)` therefore holds for every reachable input.
- No timing/ordering hazard: no fusion site is reached before the last writer runs. The chatter tick-site is wrapped in `try/except`; if it partially populates before raising, the fusion sites read the partial set — but the pre-cycle code would have done the same because the shared `stuck_sensors` local was mutated up to the same raise point. Behaviour equivalent, not worse.

**D2-raise branch (§D1.1 Reading A) — PASS:**
- `coordinator.py:2774-2796` (the `else` on `_release_edge_scan_should_run()`, reached on a mid-detector exception via `_d2_completed_cleanly=False`). No `promote("stuck_dutycycle", ...)` call in that branch. `reset_tick()` at 2560 has already cleared the mirror, and the D1 promote loop (2647-2649) never ran because control jumped to the `except` at 2725. The mirror therefore contains ONLY the P22 promotions issued at 2567-2570. This matches pre-cycle behaviour, where a D2 raise would similarly not populate `stuck_sensors` with dutycycle entries. The compensating promotion the plan calls "Reading B" is correctly absent. Comment at 2787-2796 explicitly documents the invariant and cites the anchor test.

**The D2-raise reconstruction of `_dutycycle_excluded_now`** (2784-2786) — restoring the previous engaged set for STUCK-SENSOR-1's own release-edge bookkeeping — deliberately does NOT mirror into the shared set. Per §D1.1 point 3 (STUCK-1 book is authoritative for release-scan, mirror is for fusion), this is correct: on the *next* clean tick, the D1 promote loop will re-populate the mirror in lock-step. A brief window (one raising tick) in which the mirror lacks these entries is byte-identical to pre-cycle, where the failed tick would have similarly not carried the dutycycle exclusion into fusion.

---

## Consumer enumeration (the standing rule, applied to both new values)

### Value 1: `SensorExclusionSet._by_entity` (via `is_excluded()`)

Grep across the whole integration surface for `is_excluded`, `_exclusion_set`, and `SensorExclusionSet`:

| Consumer | file:line | Path | Trust vs display |
|---|---|---|---|
| Motion fusion `any(...)` | `coordinator.py:2891-2894` | Room-tier trust | Trust (occupancy vote) |
| Presence/mmwave fusion `any(...)` | `coordinator.py:2898-2901` | Room-tier trust | Trust |
| Occupancy fusion `any(...)` | `coordinator.py:2905-2908` | Room-tier trust | Trust |
| Trigger-source scan (motion) | `coordinator.py:2919-2925` | Diagnostic (`last_trigger_*`) | Display |
| Trigger-source scan (presence) | `coordinator.py:2927-2933` | Diagnostic | Display |
| Trigger-source scan (occupancy) | `coordinator.py:2935-2942` | Diagnostic | Display |

**Zero consumers outside `coordinator.py`.** STEP-EXCLUDE-4 (no zone/house/substrate propagation) verified — I grepped `is_excluded\|_exclusion_set\|SensorExclusionSet` across the tree; the only other hits are `sensor.py:1837` (a docstring citation) and `memory_writers.py:470-494` (person-exclusion — unrelated namespace: `is_excluded_now`). No zone/house/substrate/HVAC/safety consumer has been added.

**Downstream trust impact of excluding a chattering vote:** The three fusion `any()` comprehensions correctly *drop* the excluded sensor from the OR while other sensors of the same kind (and cross-kind: motion / presence / occupancy) continue to contribute. There is no force-vacant path. A room with `motion=[a,b,c]` where `b` is chattering evaluates `any(is_on(a), is_on(c))` — the two remaining trusted sensors carry the vote. If all sensors of a kind are excluded, that kind's leg goes False, but the other kinds' legs still admit `any_sensor_active`. This matches pre-cycle semantics precisely (the same shape existed for continuous-on exclusion since P22).

### Value 2: `self._chattering_entities`

Grep: only two producers/consumers:
- Producer: `coordinator.py:2830-2831, 2878-2880` (populated per-tick from `_chatter_detector.chattering_entities()`) and 2809 (`.discard(_rel)` on release).
- Consumer: `sensor.py:1830-1900` (`UnavailableEntitiesSensor` — diagnostic surface only). Docstring at 1837 explicitly declares "ONLY consumer... NO trust code reads this — fusion authority is `SensorExclusionSet.is_excluded()`."

**No trust-decision consumer.** The chatter kind-label overrides `_stuck_sensor_kinds[eid] = "chatter"` (2843) — this is a per-tick diagnostic label consumed only by the same `UnavailableEntitiesSensor` branch. No shape collision with the existing "continuous" / "dutycycle" labels.

### Analytics / stuck-signal rows

`fire_stuck_signal(kind="chatter", ...)` and `fire_stuck_signal_recovered(kind="chatter", ...)`. The `_stuck_signal_nm` helper is `kind`-agnostic and dedups per `(kind, key)` per day (`_stuck_signal_nm.py:185-189, 228-229`). No schema/PK collision with `("continuous", ...)` or `("dutycycle", ...)` / `("dutycycle_excluded", ...)` — separate namespace. Existing analytics queries reading `kind IN ('continuous','dutycycle')` are unaffected; a query wanting to include chatter must opt in by name.

---

## Findings

### M-A1 — MEDIUM — Per-tick task-scheduling flood on chatter STUCK NM (Bug Class #10 write-flood / #38 task-spam adjacency)

**Location:** `coordinator.py:2832-2867` (chatter promote loop) and `coordinator.py:2802-2828` (chatter release loop).

**Failing input → wrong output:** With N chattering entities and the URA per-tick refresh (~10-30 s), every tick creates N `async_create_task(fire_stuck_signal(...))` tasks — one per chattering entity, per room. The NM helper itself de-dups (`_stuck_signal_nm.py:185-189` returns early once `_LATCHES[latch_key] == today`) so no duplicate NMs fire, but the *task scheduling* is unbounded. Compare `coordinator.py:2681-2699` (STUCK-SENSOR-1 D2 path): that site wraps the `async_create_task` in a `_stuck_sensor_fired`/`_stuck_excluded_fired` caller-side latch pre-check specifically to *avoid* the per-tick task-schedule spam, added as MED-A1 fix-up 2026-08-13. The chatter site re-introduces exactly the pattern that fix-up removed.

**Fix:** Wrap the `hass.async_create_task(fire_stuck_signal(kind="chatter", key=(_ceid,), ...))` in a per-day latch check on the coordinator, symmetric to `_stuck_sensor_fired[("chatter", room_name, _ceid)]`. Discard the key from the latch inside the release loop so a re-flag after quiet re-emits (mirrors the `_stuck_excluded_fired` engage/release-note discipline). The release-side `fire_stuck_signal_recovered` call is naturally edge-driven (only inside the `for _rel in _chatter_released` loop, and `_chattering.discard` in the detector prevents re-add of a released id), so it does not need the same guard.

### M-A2 — MEDIUM — Hollow anchor on the Reading-A invariant (feedback: "Hollow test anchors")

**Location:** `quality/tests/test_sensor_exclusion.py:222-247` (`test_d2_raise_fusion_byte_identity_reading_a`).

**Failing input → wrong output:** The test drives the local `_simulate_tick()` helper (defined in the same test file), NOT `coordinator.py`. A source mutation inserting `self._exclusion_set.promote("stuck_dutycycle", s, ...)` into the D2-raise branch (`coordinator.py:2774-2796`) would leave this test GREEN — the simulator has no coupling to the production branch. The paired `test_reading_B_leak_would_expand_exclusion_set` (250-274) similarly runs the simulator with the `reading_B_leak=True` flag and asserts on the simulator, not on coordinator source. The comment at 271-272 acknowledges this ("the RED that D6 test 6a asserts on: if the coordinator is mutated...") but the RED is never actually surfaced by a coordinator drive-through. This is the "hollow anchor" pattern the memory-body `feedback_hollow_test_anchors` warns against — "a source grep is not a test; drill by DETACHING the value not removing the code; oracles must be independently authored."

**Fix:** Add a behavioural anchor test in `test_chatter_wire_in.py` (or a new `test_step_reading_a_anchor.py`) that:
1. Constructs a real `RoomCoordinator` (or the existing lightweight coordinator fixture used by `test_chatter_wire_in.py`).
2. Populates `self._dutycycle_excluded_last_tick` with two entities.
3. Monkey-patches `_detect_duty_cycle_stuck` (or the corroborator predicate) to raise, forcing the D2-raise branch.
4. Runs one `_async_update_data` tick.
5. Asserts `set(coord._exclusion_set) == p22_only_set` — the SHIPPED source will pass; a Reading-B mutation of `coordinator.py:2774-2796` will fail specifically THAT test.

This closes the loop from "simulator says the SET behaves correctly" to "the production branch actually calls the set correctly." Reviewer C is the natural owner (per-site source mutation) but the gap is visible from framing A because it's the primary invariant of the migration.

### L-A1 — LOW — Fusion-site count in `test_all_6_coordinator_fusion_sites_use_is_excluded`

**Location:** `quality/tests/test_sensor_exclusion.py:282-...`

**Note:** A grep-based "count is_excluded() calls" test in `test_sensor_exclusion.py` is a shape guard, not a behavioural one. If a legitimate future edit adds a 7th consumer (e.g. a new trigger-source category), the test fails; if an edit *replaces* one of the 6 with `sensor not in some_local_set`, the count still hits 6 and the test passes. Consider replacing with per-line anchors (`assert 'not self._exclusion_set.is_excluded(sensor)' in coordinator_lines[2891]` shape) — but LOW because the current 40-test cycle suite plus M-A2's proposed anchor together cover the semantic gap.

---

## Explicit non-findings (checked, cleared)

- **Empty exclusion set on quiet ticks:** `is_excluded(x)` on empty dict returns False → OR filter admits every sensor → byte-identical to pre-cycle empty `stuck_sensors`. `STEP-EXCLUDE-2` holds.
- **Entity in multiple clients:** `promote` stores `{client -> reason}` per entity. `release("A", eid)` leaves the entry as long as `"B"` still holds it (`sensor_exclusion.py:108-120`). `STEP-EXCLUDE-3` holds — verified by `test_client_isolation_multiple_clients_hold` (in the passing suite).
- **Release ordering (auto-release before promote in the chatter tick):** correct — a release must be visible in the same tick so a re-flag can immediately re-promote. `reset_tick()` at 2560 already cleared the mirror; the release loop's `_exclusion_set.release("chatter", _rel)` at 2808 operates on an empty set for that client (noop, safe); the promote loop at 2833-2835 re-populates. Byte-safe.
- **Chatter re-flag after release, same day:** the detector's `_chattering.discard` on release (in `check_release`) allows a fresh flag; the NM helper's per-day latch stays set (correct — one STUCK NM per (kind, key) per day); the coordinator's `_chatter_released` fires the recovered NM per release edge. Consistent with the D1 engage/release-note discipline.
- **`stuck_sensors` local alias vs `_exclusion_set`:** the alias is still consumed by the D1 recovered-NM `_prev_excluded - _dutycycle_excluded_now` scan at 2748. That scan uses the STUCK-1 book (`_dutycycle_excluded_last_tick`), not `stuck_sensors`, so the alias is only a bookkeeping shadow — safe.
- **Analytics shape:** `fire_stuck_signal(kind="chatter", ...)` inserts an anomaly row via the same code path as `dutycycle`; the shape is unchanged and existing queries filtering on `kind IN (...)` continue to work.
- **Restart resilience:** `_chattering` and `_chatter_since` are intentionally RAM-only (`chatter_detector.py:328-332`); on restart, the detector re-observes edges and re-flags from fresh evidence. No RestoreEntity poisoning path (Bug Class #12) because there is no restored value that could produce a stale exclusion.
- **Listener cleanup (Bug Class #38):** `_chatter_unsub` stored, drained in `async_teardown`, and `__init__.py:4813-4817` calls it out of `async_unload_entry`. `_drain_listener` is idempotent and re-armable from `async_register_listeners`.

---

## Summary table

| Sev | Bug class | File:line | Fixed? |
|---|---|---|---|
| MEDIUM | Task-scheduling spam / per-tick fire adjacent to Bug Class #10, #38 | coordinator.py:2832-2867 | Recommend fix pre-ship (small, symmetric to D2 latch pattern) |
| MEDIUM | Hollow test anchor (feedback: hollow anchors) | quality/tests/test_sensor_exclusion.py:222-247 | Recommend adding behavioural anchor in a fix-up |
| LOW | Shape-only grep test masks a replacement mutation | quality/tests/test_sensor_exclusion.py:282- | Optional; superseded by M-A2 fix |

**Byte-identity verdict:** PASS. **Consumer enumeration:** clean; STEP-EXCLUDE-4 holds. **Overall:** SHIP-WITH-FIX (M-A1 caller-side latch is the only pre-ship must; M-A2 is a Reviewer C escalation candidate).
