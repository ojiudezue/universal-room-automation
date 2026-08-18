# CENSUS-ACCURACY-1 — Build Review A (arithmetic correctness + invariant integrity)

- **Branch tip reviewed:** `feature/census-accuracy` @ `6bf4f4eee` (commits
  `8c97c0567` D1+D2 + `6bf4f4eee` test-isolation/board-drift).
- **Diff base:** `git merge-base develop feature/census-accuracy` =
  `ec034585fdf8b0194d72b872c700125f9187e819` (verified — not two-dot from the
  cycle's own first commit; the plan-review noted a prior reviewer this session
  used the wrong base and lost a deliverable).
- **Framing:** arithmetic correctness + invariant integrity (A of a three-framing
  Tier 2-DB pass). B = cross-coordinator/lifecycle. C = test authority.
- **Suite state (orchestrator-run, not re-run):** branch 25 failed / 9208
  passed, develop 25/9194, NAME-DIFF EMPTY, +14 new tests all in
  `quality/tests/test_census_accuracy_d1_d2.py`.
- **Verdict:** **SHIP.** Two MEDIUM/LOW observations recorded (none blocking).

---

## 1. Independent peak-write enumeration (INV-PEAK-NO-SELF-REFRESH)

Grepped `_store_peak|_peak_house_(camera_count|timestamp)|_peak_property_(count|timestamp)` on the branch-tip source. All writers of `_peak_house_timestamp` / `_peak_property_timestamp` in `camera_census.py` post-D1:

| Site | Purpose | Direction | Legitimate? |
|------|---------|-----------|-------------|
| L2738 (`_apply_hold_decay`, `peak_ts is None`) | First-observation latch | init | ✅ |
| L2768 (`_apply_hold_decay`, sustain-window promotion) | Pending→peak after `CENSUS_PEAK_SUSTAIN_SECONDS` | upward | ✅ |
| L2781 (`_apply_hold_decay`, property zone `fresh > peak`) | Instant upward latch (no sustain for exterior) | upward | ✅ |
| L2818 (`_apply_hold_decay`, post-hold instant drop) | Reset peak to fresh after hold expiry | downward (or 0) | ✅ |
| L2823 (`_store_peak` definition itself) | Helper | — | — |

**The former `elif fresh_count == peak` `_store_peak(...)` at ~old-line 2600 is GONE.** The new branch (L2784-2797) increments `_peak_refresh_suppressed_count`, clears pending, and returns `(fresh_count, False, 0)` **without** touching `peak_ts`. INV-PEAK-NO-SELF-REFRESH holds across the whole enumerated surface.

Test `test_d1_no_peak_self_refresh_under_steady_fresh` (L141) drives production `_apply_hold_decay` with fresh==peak for 10 ticks and asserts `_peak_house_timestamp` is unchanged AND the LIFETIME counter reaches 10 (positive-discriminator per plan-review F3). Real code path, not a source grep.

## 2. Mutation drills (independently re-run this review)

`PYTHONDONTWRITEBYTECODE=1`, `__pycache__` purged in `custom_components/` and
`quality/` before each drill. Source restored + `git diff` = 0 lines after both.

### D1-M1 — re-add self-refresh at the equality branch

Mutation: inserted `self._store_peak(zone, fresh_count, now)` inside the `elif fresh_count == peak` branch (alongside the retained counter increment).

Expected failure: `test_d1_no_peak_self_refresh_under_steady_fresh`.

Observed:

```
FAILED quality/tests/test_census_accuracy_d1_d2.py::test_d1_no_peak_self_refresh_under_steady_fresh
AssertionError: peak_ts changed at tick 1: self-refresh regressed
  assert datetime(2026,8,17,12,0,15) == datetime(2026,8,17,12,0)
```

**PASS** — anchored test detected the regression on the first equality tick. Restored, `git diff --stat` clean.

### D2-M1 — drop the `_2` fallback in `_resolve_face_entity_id`

Mutation: changed `for candidate in (canonical, suffixed):` → `for candidate in (canonical,):`.

Expected failure: `test_d2_resolver_falls_back_to_suffixed_variant`.

Observed:

```
FAILED test_d2_resolver_falls_back_to_suffixed_variant
AssertionError: assert None == 'sensor.armcrest_last_recognized_face_2'
```

**PASS** — anchored. Restored, clean.

## 3. D1 arithmetic — the equality branch + instant-drop

- **Suppression counter placement:** `_peak_refresh_suppressed_count += 1` lives exactly on the deleted-behaviour path (L2795) and NOTHING else. It fires per `_apply_hold_decay` call, which runs once per zone per tick — so a steady `fresh==peak` at both `house` and `property` produces two increments per tick, matching the pre-D1 two-`_store_peak` shape. ✅
- **Per-tick counter reset:** `_face_lookup_missing_count = 0` at the top of `_update_census_inner` (L1141), before any resolver could fire this tick. ✅ Reset timing correct.
- **`INV-DECAY-HONEST`:** at hold+1 tick with `fresh=0`, `_apply_hold_decay` falls past the hold gate (L2808 `elapsed >= hold_seconds`) into the shared instant-drop (L2818): writes `peak=0`, `peak_ts=now`, returns `(0, False, 0)`. `test_d1_empty_house_reaches_zero_within_hold_plus_tick` and `test_d1_house_zone_instant_drop_after_hold` cover this on real code. ✅

## 4. Instant-drop applied to the house zone — safety analysis

The hold gate (L2808) still uses `_get_hold_seconds(zone)`, i.e. `CONF_CENSUS_HOLD_INTERIOR` for `house`. D1 changes the **shape** of decay (linear→instant) but leaves the **hold WINDOW** governed by the same operator knob. A brief within-hold dip returns `peak` (held); after hold expiry the drop is immediate — semantically identical to property zone. Post-drop re-inflation is protected by the pre-existing sustain-latch (`CENSUS_PEAK_SUSTAIN_SECONDS`, house-only branch at L2744). Safe.

## 5. D2 fail-CLOSED direction — 4 sites verified

Enumerated all callers of the two new resolvers:

| Call site (branch-tip line) | Resolver | Miss handling | Direction |
|---|---|---|---|
| `_get_face_recognized_persons` L2574 | `_resolve_face_entity_id` | `if face_sensor_id is None: continue` | fail-CLOSED (person NOT added to recognized set) ✅ |
| second face site L2609 | `_resolve_face_entity_id` | `if face_sensor_id is None: continue` | fail-CLOSED (no `-1` dedup credit) ✅ |
| area/camera dedup L2934 | `_resolve_face_entity_id` | `face_state = None if ... else`; downstream `face_is_fresh = False` → `raw_contribution = count` | fail-CLOSED (whole camera count stays unidentified) ✅ |
| last-camera path L3247 | `_resolve_last_camera_entity_id` | `if sensor_id is None: continue` | fail-CLOSED (no face-based `identified` credit) ✅ |

All four resolve to the SAFE direction: a miss can never over-count `identified`, and can never grant a spurious `-1` to `unidentified_count`. Under-count is by construction acceptable (the plan explicitly frames this as the safe side of the trade).

## 6. Frigate person map — first-name-lowercase keying

- `_build_frigate_person_last_camera_map` (L2497) keys on `parts[2].strip().lower()` where `parts` = `<ULID>:sensor_global_face:<PersonName>`.split(':'). For `Oji` → `"oji"`. ✅
- `_resolve_last_camera_entity_id` uses `person_slug.split("_", 1)[0].strip().lower()`. For URA slug `oji_udezue` → `"oji"`. Match. ✅
- The plan-review's registry probe confirmed the live entity uses `_2` disambiguation; the map iteration order + the `if existing and not existing.endswith("_2"): continue` rule at L2508 correctly **prefers canonical over `_2`** for either iteration order (traced both). ✅

## 7. `CENSUS_DECAY_STEP_SECONDS` tombstone verified

`grep -rn CENSUS_DECAY_STEP_SECONDS custom_components/ quality/` on the branch:

- `const.py:2733` — the tombstoned constant + comment.
- `camera_census.py:70`, `:2715`, `:2814` — comment-only references (tombstone note + two docstrings).
- `test_census_v2.py:36, :197` — **LOCAL** module-level literal + local usage inside a `StubPersonCensusV2` reimplementation (does NOT import from `const`).

**No live production reader.** Tombstone genuine. ✅

## 8. Findings

### MEDIUM — `quality/tests/test_census_v2.py` is now a stale-semantics oracle

`test_census_v2.py` re-implements `_apply_hold_decay` locally as `StubPersonCensusV2._apply_hold_decay` (L166) using its own module-level `CENSUS_DECAY_STEP_SECONDS = 300` (L36). It still exercises the OLD linear-slope semantics and passes because both the oracle and the code-under-test are the same OLD copy — the test is internally self-consistent and never touches production `PersonCensus._apply_hold_decay`.

Why this survives the suite:
- The suite baseline is name-diff-empty (25/9208 vs 25/9194) because the stub is closed over its own logic; production changes cannot flip it.

Why it matters:
- A future maintainer reading `test_census_v2.py` after D1 will believe the old linear-slope decay is a **specified, tested** behaviour — that's the opposite of what D1 declared. That's a documentation-hazard finding, not a correctness bug.

Recommend (non-blocking): either delete the linear-slope path from the stub (aligning oracle to production post-D1), or add a `# NOTE: PRE-D1 FOSSIL — production is now instant-drop; kept only for pre-cycle regression check on the ambient census wiring.` header. Cost: ~15 min. Filed for the next housekeeping pass; **not a ship-blocker** — the +14 new `test_census_accuracy_d1_d2.py` tests are the authoritative D1/D2 guard.

### LOW — `count_as_of` has two different clock stamps under the same key

- `SIGNAL_CENSUS_UPDATED` payload (`camera_census.py:1246`) stamps `count_as_of = dt_util.utcnow().isoformat()` at **dispatch time**.
- `URAPersonsInHouseSensor.extra_state_attributes` (`sensor.py:3565`) stamps `count_as_of = dt_util.utcnow().isoformat()` at **attribute-read time**.

Same key, subtly different semantics. Each is internally correct (the sensor path can't know the last dispatch time without persisting it), but a consumer that cross-references payload vs attr may see a mismatch of up to one HA scan tick. Non-breaking. Recommend a one-line docstring on the sensor attr clarifying this is read-time; can slip into the next cycle.

### LOW — `_face_lookup_missing_count` reset is tied to `_update_census_inner`

The counter is reset only at the top of `_update_census_inner` (L1141). All four current callers of `_resolve_face_entity_id` live inside that compute loop, so this is correct today. If a future patch calls the resolver from a diagnostic-only path (outside the compute loop), the per-tick counter would leak. Not a defect in this cycle; note for the plan of record.

## 9. Verdict

**SHIP.** D1 and D2 arithmetic are correct against my independent re-enumeration; INV-PEAK-NO-SELF-REFRESH, INV-DECAY-HONEST, and the fail-CLOSED direction of D2 all hold across the whole surface I audited; both mutation drills detect the regression they anchor; the tombstone is genuinely dead. The two LOWs and one MEDIUM above are recorded so B/C reviewers can decide independently, but none is a ship-blocker from framing A.
