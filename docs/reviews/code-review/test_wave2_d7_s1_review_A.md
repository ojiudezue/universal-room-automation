# Test Wave 2 D7 slice 1 — Review A (local correctness + test-intent preservation)

Branch `worktree-agent-aaf12a41b32eac630` @ 7b227bbe0, base develop 6f38b9b9e (three-dot). Test-only diff, 22 files.
HVAC/presence state-of-play docs not read: no production code is touched.

## Verdict: SHIP (no CRITICAL/HIGH; 3 LOW)

## Q1 — Did any victim-side fix weaken an assertion or make a test pass vacuously?
No assertion was removed or loosened (`git diff -w` shows only fixture/clock/registry plumbing; every `assert` line is unchanged).

| File | Change | Verdict |
|---|---|---|
| test_safeword_window.py:38-48, 164-368 | naive `datetime.utcnow()` → `_now()` = `_nm_mod.dt_util.utcnow()` | Holds. It now uses the same clock production stamps with, so the 45m window bounds (`44:55 < r < 45:05`) and the "-1s expired" case keep their meaning. It is stricter than before, which only passed via a leaked naive clock. |
| test_nm_cycle_c2_fixup / c_routing_matrix / nm_image_delivery | import-time dt_util write → autouse monkeypatch on both `sys.modules` dt and the NM's own `dt_util` global | Holds. The pin has the same values as before, and now it is restored and applied to the namespace production actually reads. |
| test_v4715_universalize_veto.py:1343-1452 | `patch.object(presence_mod,"dt_util")` → `patch.dict(PresenceCoordinator._run_inference.__globals__, ...)` | Holds, and it is stronger. The patch now hits the module the class runs in. The old form could patch an orphan module. |
| test_v4715 / test_v4623 `__path__` | adds a real `__path__` to the placeholder packages | Holds. These were collection breaks when the file ran alone. |
| test_envoy_auto_derive.py:386-407 | per-test truthy `entity_registry.async_get` | Holds. It matches the class's own docstrings (434, 478). The registry-absent hard-error path is documented as covered in test_envoy_boot_decoupling.py (440, 482). `_entity_in_registry` still runs. |
| test_ec_solar_entity_override.py:138-142 | uses the existing `_state_only_registry` fixture (168) | Holds. This is the same pin its siblings at 218/231 already use. |
| test_sleep_fans_and_flash.py:487 | cooldown is stamped from the controller's own `dt_util` | Holds. With the 100-year buffer, the "cooldown blocks fan" assertion is still meaningful. |
| test_appliance_coordinator_v1a.py:273, test_identity_fusion_d2_d3_d4.py:510, test_perimeter_alert_nm_routing.py:44 | donor-side restore (monkeypatch registers current value / `_scheduled.clear()` after yield) | Holds. These are teardown-only, so test bodies are unaffected. |
| test_chatter_detector.py | every stub write goes through MonkeyPatch, module-scoped and undone | Holds. `_stubs_win_at_run_time` still re-installs per test. |

## Q2 — import_scope / reinstall correctness (quality/tests/_d7_isolation.py)
- **Nesting:** each scope snapshots its own `before` and restores to it in `finally`, and inner-before-outer unwinding composes correctly. Holds.
- **Exceptions:** restore runs in `finally`. A raise from the stub block still propagates as a collection error, as it did before. Holds.
- **attrs=True:** it snapshots `vars()` only for prefix modules present at entry, reverts changed or added attrs on the original module object (`before[k]`), and re-sets deleted ones (lines 74-88). `reinstall` opens its scope before re-applying the writes (100-112), so the re-applied writes are reverted at module teardown. Holds.
- **Modules first imported inside the scope:** they are popped (89-91). Correct for the intent.
- **LOW-1 (latent double-identity):** with `attrs=False` (test_hvac_fan_control, test_census_device_switches), a REAL submodule first imported inside the scope is popped from `sys.modules`, but the parent package keeps it as an attribute (`homeassistant.helpers.entity_registry`). A later `import a.b as c` or `from a import b` resolves through that parent attribute, so it can bind a different object than `sys.modules["a.b"]`. test_envoy_auto_derive.py:401-404 already has to guard against exactly this split. No failure is observed today (validator found 0 NEW), but it is a trap for the next slice. Option: always revert parent-package attrs for popped children, even when `attrs=False`.
- **LOW-2:** in-place mutation of a pre-existing module attribute (for example a dict or list in `const`) is invisible to the identity-based snapshot at line 76 and is not restored. This is documented scope rather than a bug; a one-line note in the docstring would make it explicit.

## Q3 — _mutation_sandbox.py widening (lines 120-127)
Holds. `relative_to(_REPO)` still raises for any path outside the repo, and the target is rewritten to `tmp_root / rel_prod`, inside the copied tree. Both `custom_components/` and `quality/` are copied with `symlinks=False`, so the mutant can never land in the live tree.
- **LOW-3:** the new guard is a bare `assert`, which `python -O` strips. Without it, a repo-root file outside those two trees (for example `scripts/x.py`) would target a path that was never copied. A missing-file error is the likely result, not a write to the live tree. Prefer `raise ValueError`.

## Bug classes
Test pollution / order dependence (all fixes). LOW-1 is the module-identity split, a #63-adjacent case where two names refer to two objects. No #62 hollow anchors were introduced.

## Must-fix
None. The three LOWs are optional and in-cycle reasonable.
