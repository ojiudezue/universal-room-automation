# TEST-SUITE-PARALLEL-1 — Tier 1 review (test authority + no masking)

Branch `test/suite-parallel-1`, range `9894bc66..90a0d9c2` (7 commits). Reviewer: ura-reviewer, 2026-11-11.

## Scope checks
- `git diff 9894bc66..90a0d9c2 -- custom_components` is **empty**. The change touches only tests.
- Removed assertions in the whole diff: one (`test_perimeter_alert_nm_routing.py:1198`). It is replaced by a masked equivalent (see F2). No skip or xfail markers were added, apart from `pytest.importorskip("xdist")` in the new `test_xdist_split.py`.

## Findings
| # | Sev | Where | Finding | Class |
|---|-----|-------|---------|-------|
| F1 | none (clears) | `test_snap1_at_detection_snapshots.py:968` | The `_is_in_vehicle_alert_hours` neuter sits in a test that already neutered the vehicle gates on purpose. It only extends that to the renamed gate, so the test is not weakened. The base test fails on wall-clock hour (`9894bc66`: `test_snap1_vehicle_dispatch_threads_snapshot_path` FAILED); the branch passes (33/33). | wall-clock coupling (fixed) |
| F2 | LOW | `test_perimeter_alert_nm_routing.py:1195-1198` | The HH:MM:SS mask is acceptable because this kill-switch test compares message equivalence and the timestamp is wall-clock prose, not what the test is about. A frozen clock would be stronger than a mask. Optional. | wall-clock coupling |
| F3 | none (clears) | `test_prediction_sensor_kill_list.py` | Comparing against `sensor.SensorDeviceClass` still separates TIMESTAMP from any other member, so the assertion is no weaker. | n/a |
| F4 | none (clears) | `test_house_energy_correctness.py` `_freeze`/`_db_globals`, `test_energy_history_kwh_integration.py` | The patches now land on the globals that production actually reads. Before, they could miss when `sys.modules` held a different module object. This makes the tests stronger. The timezone pin replaces a manual set/restore with monkeypatch, and the Chicago case is kept. | stale module ref |
| F5 | none (clears) | `test_d7_donor_hygiene.py` | Three victim-side drills were retired. Their premise (unscoped donors oc_pillar_a/b) is gone because the donors are now scoped. Three new donor-side residue drills (oc_pillar_a/b, optimization_coordinator) reintroduce the leak by un-scoping `import_scope`, so the scoping is still anchored at its new site. The victim fixes stay in as defence in depth. | hollow-anchor check passes |
| F6 | none (clears) | `quality/tests/_xdist_split.py:47-57` | The hook returns `None` unless `--dist loadfile`, so serial runs and other dist modes are unchanged. It is `optionalhook=True`, so registration is safe when xdist is absent. The override of `LoadFileScheduling._split_scope` exists in the installed xdist 3.8.0. It is a private API: an xdist upgrade could silently fall back to the default scope (wall time only, never correctness). `test_xdist_split.py` covers it. | private-API dependency (LOW) |
| F7 | LOW (pre-existing) | `test_snap1_at_detection_snapshots.py:827-836` | `test_snap1_frigate_capture_refuses_traversal_event_id` walks the **parent** of the tempdir, which is the shared `$TMPDIR`, and fails if any foreign path contains "etc" and "passwd". It failed once in a 6-file targeted run and passed in the 2-file and single-file reruns. The cause is environmental (concurrent processes and sandbox copies in the shared tmp), not this branch. Recommend scoping the walk to a private parent. | flaky test |

## Targeted runs (no full suite)
- Run 1: `test_xdist_split` + `perimeter_alert_nm_routing` + `snap1` + `house_energy_correctness` + `optimization_coordinator` + `zone_migration_mint_guard`. Result: 297 passed, 1 failed (F7).
- Run 2: `snap1` + `perimeter`. Result: 97 passed.
- Run 3: `snap1` alone. Result: 33 passed on the branch, 1 failed on base.

The heavy subprocess drills (d7) were not re-run here; that is the validator's job.

## Verdict
**SHIP.** No fix weakens what its test proves. The changes repoint patches at the objects production actually holds, or scope leaks at the donor. F2, F6 and F7 are optional LOWs.
