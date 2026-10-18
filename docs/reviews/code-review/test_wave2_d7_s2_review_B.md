# Test Wave 2 D7 slice 2: Review B (cross-file isolation, ordering, suite side effects)

Head: e8081ab98. Test-only. Default-order name-diff reported CLEAN (0 NEW, 57 GONE).
HVAC/presence docs were not read because this change is test-harness only and touches no production source.

## Spot-check

`collect_order_matrix.py --run --seeds 1 --reverse` over 9 files: optimization_coordinator, oc_pillar_a, perimeter_alert_nm_routing, fan_sweep_trio, v4623_humidity, bathroom_exhaust_intelligence, identity_fusion_d2_d3_d4, evse b2b_ii, sleep_fans_and_flash.
Result: 428 results. Seed 1 and reverse order each gave 0 new failures and 0 healed. PASS.

The default order of this subset fails 5 tests in `test_v4623_humidity_fan_behavioral.py`. The file also fails 5 of 6 when run alone, and the pre-slice-2 version (`cdb717ef1~1`) fails the same 5 when run alone. Slice 2 did not introduce this. It is a pre-existing dependency on running the file with others (`_humidity_on_since` stays None). LOW: card it.

## Findings

| SEV | Where | Finding |
|---|---|---|
| MEDIUM | `quality/tests/_d7_isolation.py:200-221` | `restore_clocks_after_test` picks targets by name heuristic (`*dt_util`, `*_mod.dt_util`). Eight of the 10 adopting files also write `_dt_mock.now/utcnow` in `_set_now`, and that name matches neither pattern. Examples: humidity:299, bathroom_exhaust_intelligence:365, fan_manual_on_hold_hvac_tier:226. `_dt_mock` is installed unconditionally into `sys.modules["homeassistant.util.dt"]` at collection (for example humidity:134). Its frozen clock therefore still outlives the test, and any later file that resolves `homeassistant.util.dt` to it inherits the clock. The helper does not create a donor. It also does not hide one, because it re-registers the value it captured at setup, which is identity-preserving. It just leaves this residual donor surface open, while the docstring implies every `_set_now` target is covered. Fix (about 1 LoC): also match names ending in `_dt_mock`, or `endswith("dt_mock")`. Add a case to `test_restore_clocks_after_test_undoes_set_now_writes`. |
| MEDIUM (card) | `test_optimization_coordinator.py:~170`, `test_oc_pillar_a_handshake.py`, `test_oc_pillar_b_admin_surface.py` (dfb543903) | The wipe-and-reimport scoping was reverted because scoping it "exposed 21 victims" (commit message). The per-test eviction is therefore load-bearing: it heals later files that were poisoned by collection-time stubs. This is a hidden order dependency. Under default order the evictors happen to run before those victims. Under a shuffle that moves a victim ahead of every evictor, the victim relies on the stubs being healthy at that point. My seed 1 and reverse runs did not trip it, but they covered only 9 files and could not have reached the 21 victims. Card it as D7-s3: name the 21 victims and fix them on the victim side (or at the stub donor), then re-apply `import_scope` to the three evictors. Not a ship blocker, because behavior equals the pre-cycle baseline. |
| MEDIUM (card) | `test_d7_donor_hygiene.py:33-36`, `test_collect_order_matrix_run_mode.py:21-25` | The `URA_D7_HYGIENE` opt-in anchors are dead by default. `grep` for `URA_D7_HYGIENE` across `scripts/`, `.claude/agents/`, `~/.claude/agents/` finds nothing, and the repo has no `.github/workflows`. The validator does not set the variable, so the subprocess drills and most of the matrix self-test never run unless someone remembers to opt in. Only the one smoke case runs by default. Fix: wire `URA_D7_HYGIENE=1` into the validator agent's procedure (or a `scripts/` gate that deploy and the validator call), or card it explicitly. |
| LOW | `test_v4623_humidity_fan_behavioral.py` | Pre-existing: fails 5/6 when run alone (before and after slice 2). This is a run-alone dependency, and it is the same class of problem as the "run-alone `__path__` fixes" in cdb717ef1. Card it. |
| info | `other_dt_modules` (`_d7_isolation.py:225`) | Read-only. It returns the parent attribute only when it diverges from `sys.modules`, and the callers in evse b2b_i/b2b_ii pin with monkeypatch. Holds: it creates no donor. |
| info | xdist | The helper uses the per-test `monkeypatch` and only process-local state. Under xdist each worker restores its own state, so it adds no cross-worker hazard. |

## Process note

When this review ran, the worktree had a foreign uncommitted edit (`quality/tests/test_zzz_v318_hvac_sensors.py`, 1 line) and an untracked `.d7c_drill.py`. They appear to come from a concurrent framing-C drill. I did not touch them. The C reviewer must confirm the restore. My matrix run overlapped that window, but zzz_v318 was not among the files I ran.

## Verdict

**SHIP** (test-only, with no regression against baseline).
Recommended in-cycle fix (LOW cost): extend the `restore_clocks_after_test` heuristic to `_dt_mock`.
Cards: (1) re-scope the three evictors after fixing their 21 victims; (2) wire `URA_D7_HYGIENE` into the validator or a gate; (3) the humidity file's run-alone failure.
