# SENSOR-HEALTH-SURFACING-1 — Code Review B (Reuse integrity + lifecycle + test authority)

**Cycle:** SENSOR-HEALTH-SURFACING-1
**Branch reviewed:** `feature/sensor-health-surfacing` @ 17134679b (single commit against `develop`)
**Framing:** B — reuse-correctness, lifecycle, test authority (framing-disjoint from Review A: correctness + edge cases).
**Files in scope:** `custom_components/universal_room_automation/const.py`, `coordinator.py`, `sensor.py`, `quality/tests/test_chatter_detector.py`, `test_unavailable_entities_chatter.py`, `test_chatter_wire_in.py`.
**Test result:** 17/17 PASS locally (`PYTHONDONTWRITEBYTECODE=1`).

## Verdict

**FIX-UP THEN SHIP.** Two mandatory pre-ship fixes (HIGH-1, MED-2). Everything else is discretionary.

The build is well-structured, the mutation drills are real, and the two REUSE claims are structurally sound. The single HIGH is a lifecycle bug in the tick-site's `_chatter_nm_notified` gating that can permanently silence a chattery entity if the first NM dispatch happens under startup conditions. The MED-2 is a missing positive assertion of the load-bearing complement claim.

## The two reuse verifications

### REUSE 1 — chatter → `UnavailableEntitiesSensor._unavailable_details` reaches and surfaces

**VERIFIED.** `_iter_configured` (sensor.py:1773) iterates `_SENSOR_LIST_KEYS = ("motion_sensors", "presence_sensors", "occupancy_sensors", "power_sensors")` (sensor.py:1691). These are exactly the three config keys the detector's `_chattering_entities` set is drawn from — `CONF_MMWAVE_SENSORS == "presence_sensors"` (const.py:433). The chatter guard clause at sensor.py:1849 (`if not is_unavail and not is_flapping and not is_chattering: continue`) is byte-symmetric with the flapping guard; the override block at sensor.py:1882-1900 mirrors the flapping override, sets `reason="chattering"` + `transition_count` + `since` (ISO-formatted), and correctly overrides any availability-derived reason (a chattery sensor is the more actionable label). The "presence_sensors" quirk is positively covered by `test_unavailable_entities_sensor_chattering_presence_sensor_key`.

Nit: the override sits inside `if entry is None:`, so if the same eid appears in multiple `_SENSOR_LIST_KEYS`, only the first iteration writes `reason`. That is correct behavior (subsequent iterations just append the role) but not asserted.

### REUSE 2 — `fire_stuck_signal(kind="chatter", …)` fires, latches, recovers, respects kill switch

**MOSTLY VERIFIED, with caveats (see HIGH-1).**

- **Signature match:** `fire_stuck_signal(hass, kind, key, diagnosis, remedy=..., title_override=...)` at `_stuck_signal_nm.py:165-174`. Coordinator call at coordinator.py:2930-2941 matches. `kind="chatter"` is free-form OK (no enum gate on `kind` in `fire_stuck_signal`).
- **Per-day latch:** `_LATCHES[(kind, tuple(key))] = today_iso` at `_stuck_signal_nm.py:228`. Coalesces same-day re-emits. Positively asserted by `test_chatter_nm_emit_once_per_day`.
- **Recovery clears latch:** `fire_stuck_signal_recovered` pops the latch (`_stuck_signal_nm.py:293`) so re-flap notifies same-day. Positively asserted by `test_chatter_nm_recovery_clears_latch_same_day` (**same-day** dispatch → recovery → dispatch = **2** emits, not day-rollover — meets the framing's specific ask).
- **Kill switch (`CONF_STUCK_SIGNAL_NM_ENABLED`) silences chatter NM too:** both `fire_stuck_signal` (line 183) and `fire_stuck_signal_recovered` (line 295) call `_kill_switch_on(hass)`. Positively asserted by `test_chatter_nm_kill_switch_silences_only_nm`, which also confirms `_chattering_entities` still populates (detection independent of NM).
- **Anomaly row:** `fire_stuck_signal` calls `_write_stuck_anomaly` on successful dispatch (`_stuck_signal_nm.py:245`); the chatter path inherits it. Not exercised by the cycle tests but the shared write path is covered elsewhere.

**Caveat — see HIGH-1 below:** the coordinator's local `_chatter_nm_notified` gate does NOT track whether `fire_stuck_signal` actually dispatched; it optimistically records the eid pre-await. This diverges from the module-level `_STUCK_SIGNAL_NOTIFIED` (which is authoritative and set only on successful dispatch) and can permanently suppress re-notification of a chronically-chattery entity if the first dispatch attempt happened while NM was unregistered or the kill switch was off.

## Test authority verdict

**REAL.** No hollow anchors identified.

- `test_chatter_detector.py` binds production methods to stub coords via `_bind` (line 83-85): `_detect_chatter = _bind("_detect_chatter", coord)`. A source change to `_detect_chatter` in coordinator.py is under test, not a shadow reimplementation.
- `test_chatter_wire_in.py` runs two real source-mutation drills: it edits `coordinator.py` / `sensor.py`, disables bytecode + clears `__pycache__` per `feedback_mutation_verification_pycache_staleness.md`, runs pytest as a subprocess, asserts non-zero exit, restores the source, and re-runs to confirm green. Both drills are load-bearing (verified by running the suite — 17/17 pass, and the mutation drills themselves are two of those 17 so they exercised production correctly).
- `test_unavailable_entities_chatter.py` binds `UnavailableEntitiesSensor._unavailable_details.__func__` and drives it directly against a stub coordinator built to satisfy the production-attribute surface.
- Recovery-latch test is same-day (per the framing's ask), not day-rollover.

Gaps in test coverage recorded below as MED-2 (complement-not-duplicate positive assertion) and MED-3 (quiet-window discharge unit test).

## Findings

### HIGH-1 — `_chatter_nm_notified` unconditional pre-add can permanently silence re-notification

**Severity:** HIGH  |  **File:** `coordinator.py:2914-2941`  |  **Bug class:** untracked-task-return-value gating / recovery-only unstick

The tick-site adds `eid` to `self._chatter_nm_notified` **before** `hass.async_create_task(fire_stuck_signal(...))`. Because the return value of `async_create_task` is discarded, the coordinator has no way to know whether `fire_stuck_signal` actually dispatched. Three legitimate paths return `False` inside `fire_stuck_signal` without dispatching:

1. Kill switch off (`_kill_switch_on` false) — coordinator would still gate re-emits.
2. `notification_manager` not yet in `hass.data[DOMAIN]` — a **boot-order hazard** given URA's history with `Envoy boot incident 2026-06-12` and Bug Class #34 patterns.
3. Uncaught exception inside `fire_stuck_signal` (returns False from the outer try/except).

**Failing scenario (concrete, reachable):**
- HA restart; first coordinator tick fires while `notification_manager` registration is still in progress (or with `stuck_signal_nm_enabled=False` set in options).
- `_chatter_nm_notified.add(eid)` records the entity.
- Fire silently returns False; no dispatch, no `_STUCK_SIGNAL_NOTIFIED` update in `_stuck_signal_nm.py`.
- Chattery entity keeps chattering; every subsequent tick hits `if eid in self._chatter_nm_notified: continue`.
- The only path back is the recovery discharge block, which requires the entity to be **out of `chatter_set` for `CHATTER_RECOVERY_QUIET_WINDOW_MIN`**. A chronically-chattery hardware fault never satisfies that; the recovery `fire_stuck_signal_recovered` would also no-op silently (`_STUCK_SIGNAL_NOTIFIED` gate) even if it fired.

Net: the very failure the cycle was built to catch (the 2026-08-09 Garage B pattern, which persisted for 24h) can be permanently silenced by transient boot ordering.

**Fix (one of):**

- **Preferred:** await `fire_stuck_signal(...)` directly (drop `async_create_task`). The call is per-day-latched at `_stuck_signal_nm.py:187`; there is no throughput reason to fire-and-forget, and the coordinator tick is already async. Set `_chatter_nm_notified` only when the awaited return is True.
- **Alternative:** use `_stuck_signal_nm._STUCK_SIGNAL_NOTIFIED` as the source of truth (single reader / writer for the "was ever notified in this process" state) instead of maintaining a parallel per-coordinator mirror.

### MEDIUM-1 — Single-sensor room false-positive: uncorroborated by construction

**Severity:** MEDIUM  |  **File:** `coordinator.py:1994-1997` (`has_corroborator = any(other != eid ... )`)

Corroboration requires a **different-entity-id** candidate to produce ≥1 in-window transition. In a room whose motion+presence+occupancy union is a **single entity** (small closets, entryways, some outdoor cameras), `candidates == [eid]` and `has_corroborator` is False by construction. A genuinely-active PIR that sustains ~2 transitions/min over 60 min (≈120 edges) — plausible for a busy corridor over a dinner-party hour — will be flagged as chattering and NM-emitted.

**Failing scenario:** a single-motion-sensor entryway with human traffic that averages one on-off every ~28 seconds sustained over an hour → uncorroborable → `chatter` NM fires with remedy "Replace sensor". No test drives a single-candidate legitimately-active scenario (mirror-negative of the incident replay).

**Fix (one of, discuss):**

- (a) In the detector, `if len(candidates) < 2: return set()` — accept blindness for single-sensor rooms and rely on P22/D2 (though D2 excludes motion). This tolerates the Garage B pattern because Garage B has multiple candidates.
- (b) Raise the rate floor (`CHATTER_MIN_TRANSITIONS_PER_MIN`) or add an ABSOLUTE-count floor (e.g. ≥200 in-window transitions) that human-driven use won't reach. The incident's 5.2/min = ~312/60min — clearly separable.
- (c) Accept as-designed; document the false-positive class in the release notes and rely on the remedy string to prompt operator triage.

Recommend at least a discriminator test that drives a single-candidate 2/min-active fixture and asserts the current design's behavior explicitly, so a future silencing change can't regress silently.

### MEDIUM-2 — Incident-replay test does NOT positively assert D2 returns ∅ on the same fixture

**Severity:** MEDIUM  |  **File:** `quality/tests/test_chatter_detector.py:302-336` (`test_chatter_detector_replay_garage_b_incident_2026_08_09`)

The docstring claims complement-not-duplicate ("chatter flags ratgdo; D2 duty-cycle would NOT flag it") but the test never calls `_detect_duty_cycle_stuck` on the fixture. It leans on the structural argument that D2's candidate loop iterates `mmwave_sensors + occupancy_sensors` only (verified independently at `coordinator.py:1789` — this argument IS sound), plus an on-ratio argument. Given that the load-bearing thesis of the whole cycle is "complement, not duplicate", the assertion should be positive:

```python
# Same fixture, same coord — extend the test:
coord._detect_duty_cycle_stuck = _bind("_detect_duty_cycle_stuck", coord)
d2_out = coord._detect_duty_cycle_stuck(
    now=now, motion_sensors=[...], mmwave_sensors=[],
    occupancy_sensors=["binary_sensor.garage_b_all_occupancy",
                       "binary_sensor.garage_b_person_occupancy"],
    room_config=..., room_name="Garage B",
)
assert "binary_sensor.ratgdov25i_dbfe2a_motion" not in d2_out
```

Per Producer AND Consumer checks + "acceptance criteria must discriminate": the observation under the fix (chatter flags, D2 doesn't) must be distinct from the observation under a plausible alternate failure (both flag, or D2 also flags because motion drifted into its candidate list).

### MEDIUM-3 — Quiet-window discharge (`_chatter_quiet_since` + `CHATTER_RECOVERY_QUIET_WINDOW_MIN`) has no unit test

**Severity:** MEDIUM  |  **File:** `coordinator.py:2948-2977`

`test_chatter_nm_recovery_clears_latch_same_day` invokes `fire_stuck_signal_recovered` **directly**, bypassing the coordinator tick-site's quiet-window bookkeeping. The tick-site's actual discharge condition —

```python
_quiet_cutoff = time.monotonic() - (CHATTER_RECOVERY_QUIET_WINDOW_MIN * 60)
...
if quiet_since is None or quiet_since > _quiet_cutoff: continue
```

— is untested. A future edit that inverted the comparison (`< _quiet_cutoff`), dropped the `* 60` unit conversion, or read the wrong attribute would not red any test. Add a coordinator-driven test with `fake_mono` that: flags entity → stops driving edges → advances mono past `CHATTER_RECOVERY_QUIET_WINDOW_MIN * 60` → asserts `fire_stuck_signal_recovered` was called and `_chatter_nm_notified` cleared.

### LOW-1 — Kill-switch OFF preserves stale bookkeeping

**File:** `coordinator.py:1919-1922` (`if not CHATTER_DETECTOR_ENABLED: self._chattering_entities = set(); return set()`)

When the rung-1 kill switch is disabled, `_chatter_first_flagged` / `_chatter_transition_count` / `_chatter_quiet_since` / `_chatter_nm_notified` are not pruned. On re-enable, the quiet-since bookkeeping seeds for those entities and may fire "recovered" NMs for chatter that pre-existed the disable. Practical impact is low because rung-1 requires code edit + restart (RAM flushes), but the "byte-identical no-op" claim in the docstring is not literally true across enable-toggles. Cheap fix: on the kill-switch branch, also clear the four bookkeeping dicts.

### LOW-2 — Import-inside-loop churn in tick site

**File:** `coordinator.py:2909, 2937, 2977` (four `# noqa: PLC0415` in the tick-site try block).

The circular-load hazard docstring at `_stuck_signal_nm.py:14-20` does not apply here — coordinator.py already imports from `.const` and from `domain_coordinators` at module top elsewhere. Move `CHATTER_RECOVERY_QUIET_WINDOW_MIN`, `CHATTER_WINDOW_MIN`, `fire_stuck_signal`, and `fire_stuck_signal_recovered` to module-top imports. Trivial cleanup, no behavior change.

### LOW-3 — `is_transition` computed and discarded

**File:** `coordinator.py:1969-1974` — `is_transition` is calculated and immediately discarded via `_ = is_transition`. The comment says "kept only for potential debug log parity with D2". Delete both the calculation and the discard; add back only if a debug log line is actually introduced.

### LOW-4 — Ring re-walk per candidate per tick

**File:** `coordinator.py:1960-1966` — the transition count is computed by re-walking the ring end-to-end for every candidate every tick. For URA's 40 rooms × ~5 candidates × ring-length ≤ ~720 samples, this is negligible today. Track a running counter as edges are observed if profiling later shows a hotspot. Not for this cycle.

### LOW-5 — Docstring / behavior drift in `test_chatter_surfacing_wired_to_unavailable_sensor`

**File:** `quality/tests/test_chatter_wire_in.py:127-129`

The docstring says "Delete the chatter branch in `_unavailable_details`" but the drill only mutates the guard clause (`... and not is_chattering` → `...`); the override block itself is left intact. The drill IS load-bearing (the D3 surfacing test reddens because chatter-only-healthy entities `continue` out of the loop), but the docstring overstates. Either rename to `test_chatter_guard_wired_to_unavailable_sensor` or extend the mutation to also delete the override block for symmetry with the coordinator-side drill.

## Lifecycle summary (framing B focus area)

- **No new async tasks / listeners / timers added beyond the existing `hass.async_create_task(fire_stuck_signal(...))` and `... _recovered(...)` scheduled at the tick site.** Both are annotated `# noqa: untracked-ok` matching the rest of the file's stuck-signal call sites. No `async_track_time_interval` / `async_track_state_change_event` / dispatcher subscriptions added, so no unload-cleanup gap.
- **Deque state bounded:** `_chatter_rings` deque per-entity, pruned by `while ring and (mono - ring[0][0]) > window_sec: ring.popleft()` (coordinator.py:1957-1958). Ring purge for de-configured entities at :1976-1982 mirrors the D2 hygiene pattern (Bug Class #22 mitigation).
- **Module-level `_LATCHES` in `_stuck_signal_nm.py` already has a 30-day prune (`_prune_stale_latches`, line 100-116) — chatter inherits this. No new module-level growth surface.**
- **RAM-only across restart:** `_LATCHES`, `_STUCK_SIGNAL_NOTIFIED`, and `_chatter_*` all reset on restart. Chatter that persists across restart re-fires NM on the first post-boot-settle tick. Acceptable per stuck-signal design.
- **Ordering / re-entrancy at the tick site (D2 release-edge block precedes chatter block):** the chatter block is wrapped in `try / except Exception:` with fail-open swallow, matches the surrounding pattern. No shared state written by both blocks in the same tick.

## Corroboration + complement summary

- **D2 excludes motion_sensors from its scored candidates** (`coordinator.py:1789`: `for sensor in (mmwave_sensors + occupancy_sensors):`). Verified by direct read.
- **Chatter DOES include motion_sensors** (`coordinator.py:1942`: `for src_list in (motion_sensors, mmwave_sensors, occupancy_sensors):`).
- **Ratgdo `binary_sensor.ratgdov25i_dbfe2a_motion` is in Garage B's `motion_sensors`** (per the test's fixture and per `INCIDENT_chatter_class_missed_by_watchdog_2026-08-09.md`). Structural complement is real; only the positive test assertion is missing (MED-2).

## What to fix before ship

1. **HIGH-1** — await `fire_stuck_signal` or source-of-truth `_STUCK_SIGNAL_NOTIFIED`; guarantee `_chatter_nm_notified` matches reality.
2. **MED-2** — add the positive `_detect_duty_cycle_stuck(...) == set()` assertion to the incident-replay test.

## What to fix in-cycle (per Fix LOWs In-Cycle rule)

3. **MED-3** — add coordinator-driven quiet-window discharge test.
4. **LOW-1, LOW-2, LOW-3, LOW-5** — small clean-ups; all together < 30 LoC.

## What to discuss / punt

5. **MED-1** — single-sensor false-positive class: pick (a) / (b) / (c) with the operator; at minimum add a discriminator test that pins current behavior.
6. **LOW-4** — ring-walk perf; not now.

---

*Reviewer B / framing: reuse-correctness + lifecycle + test authority. Written by Oji Udezue.*
