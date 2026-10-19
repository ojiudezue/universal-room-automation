# Test Wave 2 D7 slice 1: Review B (isolation, lifecycle, suite side effects)

Branch `worktree-agent-aaf12a41b32eac630` @ 7b227bbe0 vs develop 6f38b9b9e (three-dot). Test-only diff, 22 files.

## Findings

| Sev | Where | Finding |
|---|---|---|
| LOW | `quality/tests/_d7_isolation.py:54-92` | Without `attrs=True`, `import_scope` restores `sys.modules` keys but not the submodule attribute that the import system binds on a parent package that already existed. Measured: after `test_hvac_fan_control.py` runs alone, the real `...domain_coordinators` package still has an attribute `hvac_fans` pointing at a stub-era module that is no longer in `sys.modules`. Production never reads it through `from ..domain_coordinators import hvac_fans`; every consumer uses `from .hvac_fans import X`, which goes through `sys.modules` (hvac.py:103, hvac_predict.py:1462, presence_fan_recheck.py:1465). So nothing is broken today. It is a latent donor shape, and the `DONOR_PROBES` residue check (`test_d7_donor_hygiene.py:85`) only inspects `sys.modules`, so it cannot see this shape. Suggested fix: on exit, also delete the parent attribute for every added key that was removed. |
| LOW | `test_d7_donor_hygiene.py:125-140, 200-212` | The hygiene anchors are not marked `source_mutation`, so they run in the default suite. They spawn one pytest subprocess per donor and per donor-victim pair. That costs time but cannot hang: each subprocess has a 300 s timeout, and `subprocess.run` kills the child on `TimeoutExpired`. There are no grandchildren, and the temp dirs are `TemporaryDirectory`s. Under xdist these subprocesses run in parallel; that is safe because the concurrency guard is a Bash hook, not pytest-internal. |
| INFO | `test_census_device_switches.py` | Running the file alone gives 6 FAILs. The develop copy gives the same 6 FAILs alone (I verified this with a temp copy, then deleted it). This predates the branch and is not a regression. |
| INFO | worktree | During my review, `quality/tests/test_v4715_universalize_veto.py` showed as modified in the working tree, and the change was not mine. A concurrent agent is writing in this worktree. Confirm before commit. By the end of my run the tree was back to only the untracked review files. |

## Questions answered

- **Stale modules or new donors under xdist or shuffle:** holds. `reinstall` is a module-scoped autouse generator. pytest tears down a module fixture whenever the next item belongs to a different module, including when xdist `--dist=load` interleaves modules on one worker. So the stubs are present only while that module's items run, and the `import_scope` inside `reinstall` (`_d7_isolation.py:104`) removes lazy imports made against the stubs. The snapshot is taken before the re-install writes, so the restore goes back to the true pre-fixture state. Imports at collection time are wrapped in `import_scope` and restored at the end of the block, so files collected afterwards see the real modules. The only residue is the parent-attribute LOW above.
- **Masking production regressions:** none found. The donor files still run their own tests against the same stubs as before. The restore only removes the leak into later files, so later files now run against real HA/URA, which is stricter. One change is a side effect of the fix: `test_v4623_humidity_fan_behavioral.py` now shows 5 stale-expectation fails in every order. These are surfaced, not masked, and are deferred to slice 2.
- **Subprocess anchors:** bounded by timeouts and leave no leaked processes. Mutation drills run in a sandbox copy (`_mutation_sandbox.py:117-127`); the new relative-to-repo resolution asserts the target is under `custom_components/` or `quality/`.
- **Order-matrix tool:** read-only. Collect mode is `--collect-only`. Run mode writes junit to a `TemporaryDirectory` with `PYTHONDONTWRITEBYTECODE=1` and `-p no:cacheprovider` (`collect_order_matrix.py:116-140`). `git status` was clean afterwards.
- **Spot check:** `--run --seeds 1 --reverse` on 8 files (hvac_fan_control, census, chatter, ac_ramp, bathroom_exhaust, safeword, sleep_fans, identity_fusion): 205 results in every order, 0 new fails, 0 healed, PASS. The 6 census failures are identical across all orders.

## Verdict: SHIP

No CRITICAL, HIGH or MEDIUM findings. The parent-attribute LOW is worth fixing in slice 2: delete the parent attribute in `import_scope` and extend the probe.
