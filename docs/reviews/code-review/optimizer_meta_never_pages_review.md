# Review: OPTIMIZER-META-NEVER-PAGES-1 (Tier 1, framing A + consumer check)

Branch `origin/fix/optimizer-meta-never-pages` @ 03d34c87. Base `develop` @ 1929f226; merge-base verified as 1929f226. Diff is `develop...branch`: 3 files, +116/-28.

**Verdict: SHIP.** No CRITICAL, HIGH or MEDIUM findings. Two LOWs, described below and not fixed.

## Claim verification
- **The only deterministic META producer is the `cycle_ok` sentinel at severity low.** HOLDS. `OptimizationDimension.META` is constructed in exactly one place, `optimization.py:1185`, with `severity="low"`. A grep for `"meta"` / `DIMENSION_META` / `Dimension.META` turns up only consumers and filters (`:1242`, `:5176`, `:5800-5803`, `:6157/6218/6252`, `optimization_llm.py:452`) and the const tuples (`const.py:4415`, `:4494`). No camera, write-volume or blindness tripwire uses META: the fleet one-shots key on `dedup_key[0]` under SENSOR_HEALTH (`optimization.py:5958-5964`). Nothing legitimate is silenced.
- **The LLM tier can emit any dimension.** `optimization_llm.py:1041` strips the raw string but does not lowercase it. `:1147-1150` maps it through `OptimizationDimension(dimension)`. If that raises, the raw string is kept. So `"meta"` becomes the Enum, while `"Meta"`/`"META"` stay as raw strings. The guard covers both shapes: `getattr(d,"value",d)` unwraps the Enum, then `str(...).lower()` compares. The parametrised string test covers the raw-string branch.
- **Normalisation edge cases.** `dimension=None` gives `"none"`, which does not match, so the finding takes the normal path. Unchanged from before.
- **Can a non-meta finding be lowercased into "meta"?** Only if the LLM writes "meta" in some casing. In that case the LLM has labelled the finding META itself, which is the intended target.

## Findings
| # | SEV | Where | Class | Finding |
|---|---|---|---|---|
| L1 | LOW | `const.py:4412-4415` (`OPTIMIZER_DIMENSIONS_ALL` feeds the options-flow HIGH allowlist SelectSelector) | #53 (knob no longer consumed for one value) | The operator can still tick `meta` in the NM HIGH allowlist, but the new guard at `optimization.py:5926-5932` runs first, so that choice now does nothing. This is intended behaviour, but the option silently does nothing. Fix suggestion: drop META from the selector options, or add a one-line note on the knob. No live impact, because the allowlist default is empty. |
| L2 | LOW | `quality/tests/test_optimizer_meta_never_pages.py:54-58` (`test_meta_high_does_not_page`) | #62-adjacent (non-discriminating anchor) | A HIGH META finding is already deferred by `should_defer_high_to_digest`, since META is not in the default allowlist. This test therefore passes with the guard removed. The mutation drill confirmed it stays GREEN. The critical and string-dimension tests do carry the anchor. Fix suggestion: set the allowlist to include `meta` in that test so HIGH reaches the new guard. |

## Cleared items
- **Dedup bookkeeping.** HOLDS. The early return happens before `_notify_dedup_state` / `_notify_dedup_just_set` are touched (`optimization.py:5975+`), so there is no orphan entry and no TTL skew. The cross-cycle decrement helper is unaffected.
- **Persistence and digest.** HOLDS. The guard sits only inside `_notify_if_severe`. It is called at `:1228` and `:1265` after the findings are collected, and the persist and digest paths (`:5800`) are untouched.
- **Tests or consumers that expect META to reach NM.** None. `grep META` across `quality/tests` turns up only low-severity sentinel or display tests (`test_v5110_optimizer_hardening.py:495/621/1045`).
- **Replacement for the deleted source-grep test.** HOLDS, and it is an improvement over #62. `_notify_if_severe` imports `should_defer_high_to_digest` at call time (`optimization.py:5945`), so `monkeypatch.setattr(_nm_cycle_a, ...)` takes effect. Mutation `if False and should_defer...` leaves `calls==[]`, so the test goes RED. Removing the `return` produces a page under `defer=True`, so `[True-0]` goes RED. The dropped assertion that the deprecated `OPTIMIZER_NM_HIGH_ALLOWLIST_DIMENSIONS` import is absent is covered behaviourally: any revert to a bare frozenset path would skip the helper, and `calls==[f]` would fail. Nothing worth keeping was lost.
- **Byte-identical on the no-op path.** HOLDS. Non-META findings only gain one getattr and one string comparison. `test_non_meta_critical_still_pages` confirms they still page.

## Test run and mutation drill
- Baseline: `test_optimizer_meta_never_pages.py` + `test_nm_cycle_a2_knob_surface.py` gave 21 passed.
- Mutation: guard changed to `if False and str(_dim).lower() == ...`, with `__pycache__` cleared and `PYTHONDONTWRITEBYTECODE=1` set. Result was 3 failed, 4 passed. RED: `test_meta_critical_does_not_page`, `test_meta_string_dimension_does_not_page[meta]`, `[META]`. GREEN: `test_meta_high_does_not_page` (see L2).
- Source restored. `git status` is clean apart from this review file.

## Bug-class tally
#53: 1 LOW · #62-adjacent: 1 LOW

## Fix-up (orchestrator, 2026-11-04 overnight)
- L1 FIXED (comment): `const.py` `OPTIMIZER_DIMENSIONS_ALL` now notes that ticking "meta" in the HIGH allowlist has no effect.
- L2 FIXED: `test_meta_high_does_not_page` forces `should_defer_high_to_digest` to False, so only the META guard can stop the page. Orchestrator re-drill (guard → `if False and ...`, `__pycache__` cleared, `PYTHONDONTWRITEBYTECODE=1`): 4 RED (`test_meta_critical_does_not_page`, `test_meta_high_does_not_page`, `test_meta_string_dimension_does_not_page[meta]`, `[META]`), 3 green; source restored, optimization.py clean.

| Severity | Found | Fixed | Deferred |
|---|---|---|---|
| LOW | 2 | 2 | 0 |
