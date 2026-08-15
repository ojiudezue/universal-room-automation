# MEMORY-COMPACTOR-1 — Review C

**Framing:** NEW SURFACES + TEST FIXTURE AUTHORITY (hollow-anchor
hunting, variant #7). Diff-blind to Reviews A/B.
**Branch:** `feature/memory-compactor` @ worktree
`.claude/worktrees/memory-compactor-build`
**Range reviewed:** `c560ded74..c24c36da2` (plus merge `b690ac5b4`),
diff vs `origin/develop` minus merge.
**Verdict:** **DO-NOT-SHIP** — two real findings (one HIGH production
gap, one HIGH hollow-anchor drill), one MED hollow anchor. All
remediable in-cycle without touching the engine.

---

## Method

- Read the entire test module end-to-end; every "anchor" test walked
  to the production symbol it claims to defend.
- Independently re-ran drill #4 (AST scan) + attempted one evasion
  (importlib) → **evasion succeeded**, documented under C2.
- Independently ran the boot-time D0 asserts against a hostile
  registry (bogus rule with orphan `episode_type` + orphan `topic` +
  missing `statement_fn`) → asserts tripped as designed
  (`ASSERT (expected): MEMORY_COMPACTION_RULES keys must be a subset
  of MEMORY_EPISODE_TYPES; orphans: ['bogus_orphan_type']`).
- Cross-checked 3 sampled oracle facts against the audit doc by hand
  (rear_ptz|car first row id=510, first_ts 2026-08-07T22:54:24.483248-05:00
  matches oracle `first_ts` — provenance chain intact; D1 commit
  `c560ded74` landed BEFORE the engine (`758553399`), so oracle cannot
  be engine-echoed).
- Verified sensor pre-first-run None-render path
  (`sensor.py:4571-4583` — `if not stats: return {…: None, …}`).
- Verified button unique_id + device grouping + RestoreEntity: no
  RestoreEntity needed (Button is stateless press-only; re-entrant
  press guarded by `self._running`), unique_id
  `f"{DOMAIN}_memory_compact_now"` is domain-unique, device pinned to
  the CM identifier tuple — matches sibling `VacuumDatabaseButton`
  pattern.

---

## Findings

### C1 — HIGH · Deferred nightly path missing `memory_compactor` entry

**Bug class:** #27 (deferred/primary maintenance-path mirror miss —
already codified from v4.7.8 B-H1 / v4.7.36 B3 / v5.11.0 D-MED-2 /
Batch-4 A-HIGH-1).

**Site:** `custom_components/universal_room_automation/__init__.py`,
`_cleanup_ops_d` list at lines 2123-2154. Primary `_cleanup_ops` list
at lines 1978-2036 includes the compactor tuple at line 2025:

```
("memory_compactor", "run_memory_compactor", {}),
```

`_cleanup_ops_d` does not. Every prior fix-up in that same file for
this exact bug class explicitly mirrors additions into the deferred
list — the pattern is documented in-source (lines 2137-2153 comments
reference three prior mirror fix-ups). This cycle broke the pattern.

**Blast radius.** On any boot where `hass.data[DOMAIN]["database"]`
is not yet reachable at primary-registration time (the deferred
branch — a real code path), the compactor never fires. Silent —
`sensor.ura_memory_status.compactor_last_run` stays None indefinitely
on such hosts, indistinguishable from "cadence not yet reached".

**Why C2's tests didn't catch it.** `test_nightly_ops_includes_memory_compactor`
(line 522) source-scans `_cleanup_ops` only — literally
`src.index('("incremental_vacuum"')` / `src.index('("memory_compactor"')`.
Both substrings appear (once, in the primary list), the assert passes,
the deferred branch gap is invisible.

**Fix:** add `("memory_compactor", "run_memory_compactor", {})` to
`_cleanup_ops_d` immediately after the `incremental_vacuum` entry
(line 2153) with a matching mirror-comment. Extend the wiring test to
assert the tuple appears in BOTH lists (either scan both, or AST-parse
and assert set-inclusion on both list literals).

---

### C2 — HIGH · Drill #4 AST scan trivially evadable

**Site:** `quality/tests/test_memory_compactor.py:82-103`
(`test_no_raw_aiosqlite_in_compactor`). Guards HIGH-2 (CRIT-blocking
on review): no raw `aiosqlite` in `memory_compactor.py`.

**Evasion, verified independently:**

```python
import importlib
def foo():
    mod = importlib.import_module("aiosqlite")
    conn = mod.connect("/tmp/x.db")
```

Ran the drill's exact scan (Import / ImportFrom / Attribute
`aiosqlite.connect`) against this snippet → **`flagged: False`**.
`__import__("aiosqlite")` evades identically. The AST scan sees a
call to `importlib.import_module` with a string constant argument;
the drill does not inspect string constants.

The invariant is real (the module today has no raw aiosqlite); the
drill is not defending it against a trivial refactor. A future
edit that "just needs a quick connection" via importlib would land
green and defeat the read-pool discipline the plan is protecting.

**Fix (small):** extend the scan with one more visitor arm — flag any
`ast.Constant` whose `.value == "aiosqlite"` regardless of parent.
The module has zero legitimate reason to name the string "aiosqlite"
anywhere. Alternative: `if "aiosqlite" in src` grep-check, but the
string-constant AST arm gives a cleaner assertion message.

---

### C3 — MED · `test_sensor_exposes_compactor_attrs` is a hollow source scan

**Site:** `quality/tests/test_memory_compactor.py:546-567` — pure
grep-for-substrings against `sensor.py`. This anchor confirms the
attribute *names appear as string literals*; it does not confirm the
sensor's `extra_state_attributes` returns those keys with the correct
values.

**What passes today that shouldn't.** Rename any read-site key by one
letter — e.g. `stats.get("finshed_at")` at `sensor.py:4585` — and:

- The sensor renders `compactor_last_run: None` forever after runs.
- The source-scan test STILL PASSES (the key name is unchanged, only
  the getter argument mutated).

Builder's own note in the deviation log calls this "acceptable
anchor". Under a hollow-anchor framing it is not — the plan's D5
Live criterion ("sensor attribute reflects last run") has no
in-suite proxy.

**Fix (small):** add one behavioral assertion —

```python
class _DB: _last_compactor_stats = {
    "finished_at": "t1", "facts_created": 3,
    "facts_superseded": 1, "writes_total": 4,
    "aborted_reason": None, "triggered_by": "manual",
}
attrs = URAMemoryStatusSensor._compactor_attrs.__func__(
    _FakeSelf(db=_DB())
)
assert attrs["compactor_facts_created_last_run"] == 3
assert attrs["compactor_triggered_by"] == "manual"
```

or a full-render via the sensor when a stub `hass.data` is
constructible — either falsifies the read-site typo. Keep the
existing source-scan; add the behavioral arm alongside it.

---

### C4 — LOW · Wiring test is also a source-scan (parity with C1/C3)

Same class as C3 — `test_nightly_ops_includes_memory_compactor`
(line 522) scans `__init__.py` text for two substrings. AST-parse
the file and assert the tuple `("memory_compactor",
"run_memory_compactor", {})` is present in the AST list literals for
BOTH `_cleanup_ops` and `_cleanup_ops_d`. Fixes C1's blind spot at
the same time.

---

### C5 — LOW · `test_disabled_returns_none` sys.modules coupling

Line 502-519. The test explicitly patches
`sys.modules["...const"].MEMORY_COMPACTOR_ENABLED = False` and
documents the reason (function-local `from .const import
MEMORY_COMPACTOR_ENABLED` binds fresh each call — the module object
identity has to be the same one the caller sees). Correct as written
but fragile to any future suite-wide test that reimports `const` via a
different path. Acceptable for now; note it in
`DEVELOPMENT_CHECKLIST.md` if the module ever moves.

---

## Cleared (checked, no finding)

- **D0 boot-time asserts** — genuinely trip on hostile registry;
  independently verified by running module-load with an injected
  orphan rule.
- **Oracle authority** — hand-derived from live probe pre-engine.
  Commit ordering: D1 (`c560ded74`, oracle+fixture+audit) precedes
  D2 (`758553399`, engine). Sampled fact matches audit doc columns.
- **Sensor pre-first-run render** — `sensor.py:4574-4583`
  short-circuits to all-`None` when `_last_compactor_stats` is
  missing.
- **Button surface** — `MemoryCompactNowButton` unique_id domain-
  scoped, device pinned to CM identifiers, re-entrancy guarded by
  `self._running`, exception handler around `run_memory_compactor`.
  No RestoreEntity needed (stateless press).
- **`_seed_exterior_track_from_fixture` dedup-bypass** — is bypassing
  a *test-seeding* impediment (60s window on the DAO), not the
  production defense; the DAO gate itself is not this cycle's
  primitive. Comment in-code correctly justifies the bypass.
- **Test fixture provenance** — `exterior_track_rows.json` is 60 rows
  hand-extracted from live DB per audit §"Type-shape notes" (id 510
  matches audit exhibit); not engine output.

---

## Summary

| ID | Severity | Class | Site | Blocking? |
|---|---|---|---|---|
| C1 | HIGH | Deferred/primary path mirror miss (#27) | __init__.py:2123-2154 | YES |
| C2 | HIGH | Hollow drill — importlib evasion | test_memory_compactor.py:82-103 | YES |
| C3 | MED  | Hollow anchor — source-scan for behavioral claim | test_memory_compactor.py:546-567 | Fix-in-cycle |
| C4 | LOW  | Same class as C3 | test_memory_compactor.py:522 | Fix-in-cycle |
| C5 | LOW  | sys.modules identity coupling | test_memory_compactor.py:502-519 | Note only |

**Recommendation.** Do not ship until C1 + C2 fixed and re-verified.
C3/C4 remediation-in-cycle. C5 note in checklist. Once fixed, re-run
the two drills that changed (C1 → new AST-based wiring assertion
should PASS with the tuple in both lists AND FAIL under mutation
that removes either entry; C2 → the extended scan should catch the
importlib-form evasion snippet from this review).
