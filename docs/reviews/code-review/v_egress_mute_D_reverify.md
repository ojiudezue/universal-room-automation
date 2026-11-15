# Review D (re-verify of the fix-up): scoped egress mute (PERIMETER-GLOBAL-EGRESS-MUTE-1)

Branch `feature/perimeter-egress-mute-scoped`. Fix-up commit `a1fa6d64`, reviewed as `git diff 8493fa8c..a1fa6d64`.
Whole-branch base: `git merge-base develop HEAD` = `1eb0308b` (the plan commit), so the branch is
`9e7af15e` (build) + three review docs + `a1fa6d64`. Read before reviewing: the IDENTITY_FUSION_CAMERAS_MANUAL
egress-mute section. Producer: transit_validator `ura_person_egress_event` (F3, a door crossing with identity
attached). Consumer: the perimeter scoped mute, a security-class consumer (floor 0.9).

## Findings

| # | SEV | Site | Finding | Class |
|---|---|---|---|---|
| D1 | MEDIUM | `perimeter_alert.py:5409-5486` (`_realert_muted_edges`) | **The late re-alert can double-alert.** Each muted edge on a camera gets its own handler task, all created in one call. The handler's in-flight guard (`:1548`) is only set at `:1979`, after real awaits (`_await_edge_capture` `:1785`, enrichment `:1930/1940`), and cooldown is reserved only after dispatch. Two tasks for the same camera both pass both gates. Repro (probe test, deleted afterwards): Oji exits garage_a at t=0; g5_bullet edges at t=75 and t=95 are both muted (same episode); the stranger's unknown crossing (detected t=60) lands at t=105 and schedules 2 tasks; run concurrently with `_await_edge_capture` yielding once (as it does live: `wait_for(task)` or an inline capture) gives **2 NM notifications** for one person. The docstring's "same-camera duplicates fold" is false for this case. The shipped tests miss it because `_drain` awaits tasks one at a time. Fix: one send per camera per call (mark every matching edge `realerted`, write the rows, schedule one handler), plus a concurrent-gather test. | Concurrency (dedup gate set after an await); claim not backed by a test |
| D2 | MEDIUM | `perimeter_alert.py:5763` `_note_egress_identity` (door key) vs `transit_validator.py:2116-2160` (door-group dedup) | **A stranger crossing can be filed under a non-covering door, so it neither vetoes nor re-alerts.** Live config `door_groups` = `{doorbell_lite: garage_a, garage_a: garage_a, ...}`. Transit dedups by `group:garage_a|direction` for 30 s, so one physical crossing through that door is emitted once, under whichever leg resolves first. If `doorbell_lite` wins, the record keys under `doorbell_lite`, which covers nothing. Repro: Oji exits garage_a at t=0 (record under `garage_a`, qualifies); a stranger enters through the same door group at t=60, `doorbell_lite` leg resolves first (garage_a leg deduped); stranger reaches g5_bullet at t=75: muted, and the stranger's record (under `doorbell_lite`) never vetoes or re-alerts. Pre-existing in `9e7af15e`, missed by A/B/C. The covered-camera side is right (see A5 below); the crossing side is keyed per camera while the producer dedups per door group (#63, coincidental equality: camera == door only when a group has one camera). Fix: key the veto/re-alert by door group when `CONF_DOOR_GROUPS` is set (treat a crossing at any camera in a covering door's group as that door's), plus a test with the live grouping. | #63 concept split (camera key vs door group); #53 one-missed-site |
| D3 | LOW | `perimeter_alert.py:5474-5477` | Re-alert task tracking is untested: removing `_gate_log_tasks.add` + done-callback leaves both files GREEN (drill X11). The test rig's `_with_tasks` returns a `SimpleNamespace`, which is unhashable, so in tests `_gate_log_tasks.add(task)` raises, the `except` swallows it and the loop stops after the first edge. That also hid D1. Fix the rig (hashable fake task) and add a teardown-drain assertion. | Hollow test rig (#62 adjacent) |
| D4 | LOW | `perimeter_alert.py:1088` `self._muted_edges = {}` on setup | Untested (drill X22 GREEN). Without it, a reused instance could re-send an edge muted before the reload. Add one assertion to `test_mute_restart_clears_episodes`. | Restart state |
| D5 | LOW | `perimeter_alert.py:1424-1433` teardown | A re-alert task is a full handler run (snapshot + enrichment), not a short gate-row write; teardown now waits up to `PERIMETER_GATE_LOG_TEARDOWN_TIMEOUT_S` (5 s) for it, then cancels. Bounded and safe (cancel lands in the handler's release paths), noted only. A send that completes inside that 5 s does notify during unload; `_do_dispatch` still checks `_active`. | Lifecycle (bounded) |

## Earlier findings: closed?

| Finding | Status | Evidence |
|---|---|---|
| A1 rejected file keeps old covers | CLOSED | `exterior_track_linker.py:509,542` clear covers on load-fail and reject; drills X13, X14 RED |
| A2 veto not retroactive | CLOSED with D1 caveat | `_realert_muted_edges`; drills X1-X10, X12 RED. Decision "(a) Re-alert late" holds except the double send (D1) and the door-group hole (D2) |
| A3 silent name fallback | CLOSED | map built from `census.get_transit_egress_entities_by_camera()` (`camera_census.py:1702`), which calls the same `resolve_cross_platform_sensors` (registry and `CameraResolver.resolve_operator_declaration`, `camera_census.py:840-858`) as the producer's `get_transit_egress_entities`, which transit uses to subscribe (`transit_validator.py:547,1093`). Fallback logged once at INFO and counted (`egress_mute_door_key_fallbacks`, bounded 64); unmapped producer legs listed. Drills X17, X18, X24 RED |
| A4 D10.5 byte-identity | CLOSED (doc) | README note |
| A5 covered cameras perimeter-only | CLOSED | `exterior_seams.py:341-351`; perimeter-only set staged by PAM (`perimeter_alert.py:833-838`, dual-role excluded). Drills X19, X23 RED |
| A5 doorbell_lite removed from garage_a cover | CORRECT | Live `egress_cameras` contains `camera.doorbell_lite`; `perimeter_cameras` does not, so it is egress-only. Its person sensor subscribes only to `_on_egress_state_change`; its edge never reaches `_async_handle_perimeter_trigger`, so the entry was a no-op. Its CROSSINGS are a separate matter (D2) |
| A6 window 0 at age 0 | CLOSED | `:1470`; drill X15 RED |
| A7 / B MEDIUM zero-fire scope | CLOSED | `:5783`; drill X16 RED |
| B LOW trip-wire after teardown | CLOSED | `:5666`; drill X21 RED |
| B LOW double listener | CLOSED | `:1092-1098`; drill X20 RED |
| B LOW anomaly row on real DB | CLOSED | `test_mute_tripwire_anomaly_row_real_db` |
| C F1-F17 | CLOSED for the sites sampled | new tests by name in the test file (`test_mute_ratio_tripwire_cooldown`, `..._ratio_boundary`, `..._task_tracked_and_drained`, `test_diag_*`, `test_mute_future_dated_crossing_does_not_qualify`, `test_mute_identity_case_insensitive`, `test_mute_row_reference_is_latest_crossing`, ...) |

## Re-alert invariants (orchestrator checklist)

| Invariant | Result | Evidence |
|---|---|---|
| Never for a qualifying (resident) crossing | PASS | `if why is None: return 0` (`:5430`); X1 RED on `test_mute_realert_never_for_qualifying_crossing` |
| At most once per muted edge | PASS | flag set before scheduling (`:5443`); X2, X3 RED |
| No double alert | **LEAK (D1)** | 2 notifications for 2 muted edges on one camera when the tasks run concurrently |
| Not after teardown | PASS | guard at the top of `_realert_muted_edges`, tasks tracked and drained/cancelled at teardown; X6 RED (tracking itself untested, D3) |
| Cooldown respected | PASS | runs the normal handler from step 3; `test_mute_realert_cooldown_applies` |
| `egress_mute_realert` gate row written | PASS | `_record_gate` `:5444-5448`; X12 RED |
| Window test matches the veto test (`0 <= edge - crossing <= window`) | PASS | X4, X5 RED; crossing `ts` is the detection time (`transit_validator.py:2193`) |
| Only a covering door re-sends | PASS for the camera key; **LEAK for door groups (D2)** | X10 RED |

## Refactor `_fail_reason` -> `_crossing_fail_reason`: mute decision unchanged

Re-ran 11 of Review C's decision-site drills against the new code (strings re-anchored to the moved code), plus 24
fix-up drills. Each mutation was applied, both test files run (`test_perimeter_egress_mute_scoped.py`,
`test_exterior_seam_mute_covers.py`, `__pycache__` purged, `PYTHONDONTWRITEBYTECODE=1`), and the file restored in a
try/finally. `git status` shows no tracked change after the run.

| Drill | Site | Result | Named failing test |
|---|---|---|---|
| R1 | direction check | RED | test_mute_ambiguous_direction_alerts[-1] |
| R2 | resident check | RED | test_mute_guest_never_mutes |
| R3 | floor | RED | test_mute_below_floor_alerts[0.89-1] |
| R4 | synthetic | RED | test_mute_synthetic_alerts |
| R5 | 0.9 clamp | RED | test_mute_min_conf_clamps_to_0_9 |
| R6 | `_fail_reason` wrapper returns None | RED | test_mute_vetoed_by_unknown_crossing |
| R7 | residents `.lower()` | RED | test_mute_identity_case_insensitive |
| R8 | census-raises fail-open | RED | test_mute_failopen_census_raises |
| R9 | pid `.lower()` | RED | test_mute_identity_case_insensitive |
| R10 | wire-in call | RED | test_mute_known_resident_covered_camera |
| R11 | veto `if failing` | RED | test_mute_vetoed_by_unknown_crossing |
| X1-X10, X12-X21, X23, X24 | fix-up sites (see table above) | RED | as cited |
| X11 | re-alert task tracking | **GREEN** | none (D3) |
| X22 | setup clears `_muted_edges` | **GREEN** | none (D4) |

The decision logic is a verbatim move; same order of checks, same reasons, same inputs (floor and residents are
computed once per decision as before).

## Statistics

| Severity | Found | Must fix |
|---|---|---|
| CRITICAL | 0 | 0 |
| HIGH | 0 | 0 |
| MEDIUM | 2 | 2 (D1, D2) |
| LOW | 3 | D3, D4 in-cycle (1-10 LoC each); D5 note |

Bug classes: concurrency/dedup-after-await (1), #63 concept split (1), hollow test rig (1), restart state (1).
QUALITY_CONTEXT candidate: "dedup gate set after the first await": any fan-out that schedules N handler runs at
once must dedup before scheduling, because per-key in-flight guards set late in the handler do not fold
same-tick siblings.

## Verdict

**FIX-REQUIRED.** Must fix: D1 (one re-alert per camera per crossing, plus a concurrent test), D2 (veto and
re-alert by door group when door groups are configured, plus a live-grouping test). In the same pass: D3 (hashable
fake task in `_with_tasks`, assert tracking) and D4 (assert `_muted_edges` reset on setup).
