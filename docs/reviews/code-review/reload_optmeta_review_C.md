# Reload-Watchdog + Opt-Meta-Boot-Transient — Review C

Framing: **Test fixture authority + hollow-anchor hunting**
(catalogue variants exercised: simulate-not-drive, dead-spy, engine-echoed
fixtures, source-grep-as-test, hand-built imitation, load-time-frozen
source, namespace-stubbed masking).

Branch: `feature/reload-optmeta` (worktree `.claude/worktrees/reload-optmeta`)
Commits under review: `33352c34d..6b1afdcb4` (D1 audit, D2+D3 build,
opt-meta-boot-transient hotfix, D2 fix-up injecting sibling-loader stubs).
Baseline: `origin/develop` @ `9b90ef6d8` (incl. two `test_kanban_render`
fixes — not yet on the branch).

Sibling framings A (correctness+data integrity) and B (lifecycle+signal-chain)
are recorded at `docs/reviews/code-review/reload_optmeta_review_A.md`
and `reload_optmeta_review_B.md` respectively.

---

## Verdict — SHIP WITH CONDITIONS

- **CRITICAL:** 0
- **HIGH:** 0
- **MEDIUM:** 2  (fix or accept-and-document in cycle notes)
- **LOW:** 3
- **Test authority overall:** ACCEPTABLE. Both cycles drive real
  production code paths (opt-meta drives real coordinator+tier
  constructors; reload-watchdog drives the real `_async_update_listener`
  via AST-slice against current source, not a frozen copy). The AST-slice
  pattern carries one live hollow-anchor risk (M-1) that the D2 fix-up
  itself has already demonstrated the tooth of — the pattern silently
  papered over a NameError that only reached daylight because the
  builder ran the sibling suite and saw failures.

---

## Authoritative Suite Numbers (worktree, post-fix-up 6b1afdcb4)

Command run in worktree:
```
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=quality python3 -m pytest quality/tests/ -q --no-header
```

Baseline reference (`origin/develop` @ `9b90ef6d8`): per orchestrator
brief, 26 pre-existing failures minus 2 `test_kanban_render` fixes
that landed on develop after this branch diverged →
**24 pre-existing failures** on current develop head. The branch does
not carry those two fixes, so the branch is expected to still fail
`test_kanban_render::*` (2 tests).

Worktree pre-fix-up (`/tmp/wt_suite.log`, captured 12:47 vs commit
`27acb0a9a`): **28 failed / 9060 passed / 45 skipped / 2 xfailed**.
Of the 28, **4 are direct fallout from the missing sibling-loader
stubs** — all fixed by `6b1afdcb4`:

- `test_cm_reload_suppression.py::test_d3_listener_reloads_for_mixed_change`
- `test_cm_reload_suppression.py::test_d3_listener_reloads_for_non_allowlisted_keys`
- `test_cm_reload_suppression.py::test_d3_listener_unchanged_for_room_entries`
- `test_part2_ec_hc_writeback.py::test_listener_still_reloads_for_mixed_change_with_part2_key`

**Post-fix-up run (`/tmp/wt_suite_post_fixup.log`, HEAD `6b1afdcb4`,
201.67s):** **24 failed / 9064 passed / 45 skipped / 2 xfailed**.

Cycle surface is GREEN — zero failures in:
- `test_reload_watchdog_hazard.py::*` (7/7 pass)
- `test_opt_meta_boot_transient.py::*` (3/3 pass)
- `test_cm_reload_suppression.py::*` (all 3 D3 tests recovered post-fix-up)
- `test_part2_ec_hc_writeback.py::*` (mixed-change test recovered post-fix-up)

All 24 remaining failures are pre-existing baseline unrelated to this
cycle (v4.5/v4.6/v4.7 series, `test_freeze_floor`, `test_deploy_scripts`,
`test_kanban_ship`, `test_d3_area_inherit`, `test_perimeter_alert_nm_routing`,
`test_v47x_dynamic_preset`, `test_v4_7_17_2_dpm_simplified_frame`, etc.).

**Authoritative name-diff vs develop head:** 0 net-new failures from
this cycle. Branch's `test_kanban_render::*` tests do NOT appear in the
worktree failure list (either the disposition-file state on branch
sidesteps the pre-fix flake, or the two develop kanban_render fixes
were only needed for a state the branch does not reach). Either way,
this cycle adds no failures.

---

## MEDIUM-1 (test authority) — AST-slice namespace pre-seeds a kitchen sink; masks NameError until a sibling suite happens to run

Files: `quality/tests/test_reload_watchdog_hazard.py:132-238` (also
`test_cm_reload_suppression.py:_load_init_listener_helpers`,
`test_part2_ec_hc_writeback.py:_load_init_dispatch_namespace`).

The AST-slice loader `_load_ns` seeds the exec namespace with 70+
symbol names (every `_CONF_*` used anywhere in the sliced code, plus
`DOMAIN`, `_LOGGER`, `CONF_ENTRY_TYPE`, `ENTRY_TYPE_*`, `CONF_ZONE`,
`CONF_CAMERA_PERSON_ENTITIES`, …). The load-time behavior is:
compile the slice, exec into this pre-populated dict, add any missing
top-level `_KEEP_NAMES` from the AST itself.

**The failure mode this cycle just demonstrated:** the builder added
an `ENTRY_TYPE_INTEGRATION` reference to `_async_update_listener`.
`test_reload_watchdog_hazard.py` seeded it explicitly so its own tests
passed. Two *sibling* loaders (`test_cm_reload_suppression`,
`test_part2_ec_hc_writeback`) did NOT pre-seed it, so the slice raised
`NameError` at load — visible only because those tests ran and failed
loudly. The fix-up commit `6b1afdcb4` added the two stubs by hand.

The reverse failure mode is the one the operator called out: a future
edit to the listener that references a NEW top-level symbol NOT already
pre-seeded and NOT covered by an existing sibling-loader failure would
be silently invisible in-suite while broken in production. Concretely:
if a new constant `INTEGRATION_STORM_GUARD_ENABLED` were added to the
listener and left out of `_KEEP_NAMES` for these loaders, the slice
would exec (because the constant wouldn't be in the sliced body) and
production would `NameError` at runtime.

**Not a live regression today** — the slice at `_load_ns` DOES include
`_KEEP_NAMES` extraction for the new integration-branch constants
(`INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS`,
`INTEGRATION_RELOAD_SUPPRESS_ENABLED`, `_INTEGRATION_KEY_SIGNAL_TABLE`).
Verified by `grep`.

**Recommendation (cycle-close or next hardening pass):** in `_load_ns`
after compile, walk the AST once with `ast.walk` collecting `Name`
loads whose id is neither in `ns` nor a Python builtin nor the target
of a local assignment, and raise a `RuntimeError` naming them. That
converts the exact class of miss the fix-up commit had to hand-patch
into a hard test failure. Alternative: import the real module via
`importlib` and monkey-patch the two constants for the kill-switch and
table-override drills, giving up the slice but gaining production
import fidelity.

Bug class: this is a fresh variant of the "hollow anchor" family
(feedback_hollow_test_anchors) — the anchor exists, the code runs, but
the anchor cannot detect a specific real-production failure mode.

## MEDIUM-2 (anchor precision) — Dispatch-drill mutates the TABLE, not the CALL; docstring overclaims

File: `quality/tests/test_reload_watchdog_hazard.py:410-441`
(`test_dispatch_line_is_load_bearing_for_transit_signal_test`).

The drill overrides `_INTEGRATION_KEY_SIGNAL_TABLE = {}` at load time
and asserts `dispatched == []`. The docstring reads:

> if the wiring table entry is removed, the transit-signal test's
> expected dispatch MUST NOT fire — proving the dispatch line is the
> load-bearing surface.

The drill proves *only* that the TABLE LOOKUP inside
`_dispatch_integration_key_signals` is load-bearing. Removing the
CALL SITE — the line `_dispatch_integration_key_signals(hass, entry, changed_keys)`
inside `_async_update_listener` — would leave this drill still passing
(no dispatch either way), which is exactly the false-anchor situation
the drill's docstring claims to prevent.

Note: the sibling test
`test_camera_person_entities_change_dispatches_transit_signal_once`
DOES cover the call-site (delete the call → that test fails), so
end-to-end coverage of the surface exists. But the drill's naming
and docstring assert something stronger than the drill actually proves,
and this is exactly the anchor-precision defect the drills are supposed
to prevent.

Fix (~5 LoC): either (a) keep the table-override drill and rename it +
correct the docstring to "the table lookup, NOT the dispatch call, is
load-bearing" and add a second drill that neuters the call by monkeypatching
`_dispatch_integration_key_signals` to a no-op; or (b) replace the
drill with a source mutation on `_async_update_listener` that deletes
the call line and re-runs the D3 assertion. Either restores anchor
authority.

Bug class: hollow-anchor variant — anchor exists and is well-intentioned
but overclaims its coverage.

---

## LOW-1 — `test_binary_sensor_dead_import_removed` is a source-grep-as-test

File: `test_reload_watchdog_hazard.py:443-455`. Matches operator's
catalogued "source-grep-as-test" hollow-anchor category — verifies a
string is absent from a file, not that any behavior is preserved or
regained. Acceptable as a hygiene guard for the MED-1 dead-import
finding from D1, but should not be counted toward D2/D3 behavioral
coverage. Suggest a one-line comment marking it a hygiene assertion,
not a behavior test, so a future reviewer doesn't mis-count it as
covering the reload path.

## LOW-2 — Fall-through snapshot-advance write not asserted

File: `test_reload_watchdog_hazard.py:329-345`
(`test_integration_options_mixed_falls_through_to_reload`).

The production listener has TWO snapshot-write sites in the integration
branch: one in the suppress path (`snapshots[entry.entry_id] = dict(new)`
at `__init__.py:6607`) and one in the fall-through path
(`hass.data.setdefault(...)[entry.entry_id] = dict(entry.options)` at
`__init__.py:6620`). The suppress-path write is asserted
(`test_integration_options_suppress_reload_on_camera_person_entities`);
the fall-through-path write is not. A regression that dropped the
fall-through snapshot advance (e.g. left the snapshot at the pre-save
value) would ship green. ~3 LoC to add the assertion.

## LOW-3 — `_FakeConfigEntries.async_reload` records intent before await

File: `test_reload_watchdog_hazard.py:253-267`. The fake records
`reload_calls.append(entry_id)` at call time and returns a completed
coroutine. Fine for the assertion "was reload SCHEDULED?" — which is
all the tests actually check — but note that production wraps in
`hass.async_create_task(async_reload(...))`, so the reload doesn't run
until the loop schedules it. If a future test wanted to observe
side-effects of the reload actually running, the fake would silently
succeed. Not a defect against current assertions; a footnote for
future editors.

---

## Opt-Meta-Boot-Transient tests — authority PASS

File: `quality/tests/test_opt_meta_boot_transient.py`.

- Drives REAL `OptimizationCoordinator` and `OptimizationLLMTier` via
  their public constructors — no AST slicing, no engine-echoed fixture.
- The DB seam is monkeypatched with `AsyncMock` at
  `db.get_recent_optimization_findings`. This is the correct boundary:
  the tests are about (1) the coordinator projecting DB rows into
  `_boot_findings_seed`, (2) the tier's sync `_assemble_corpus`
  falling back to that seed when `_last_findings` is empty, and
  (3) the tier PREFERRING RAM cache over seed when the RAM cache is
  populated. Each of these is a behavior the production code owns;
  the DB return value is just the input.
- Field-shape assertions on `corpus.findings_recent[0]["target_id"]`
  and `["dimension"]` confirm the tier's projection (`row.get("target_id")`,
  `str(row.get("dimension") or "")`) is exercised end-to-end.
- The "RAM cache wins" test uses a real `OptimizationFinding` +
  `OptimizationDimension.COMFORT` to populate `_last_findings`, then
  asserts the target_id `stale_from_boot` is ABSENT from the output
  and `fresh_from_cycle` is present. That's a proper falsifiable
  oracle — removing the `if ram_cache:` guard would flip both
  assertions.
- The empty-DB test proves no crash and no synthesized rows — the
  regression guard against a naive fix that would have inserted a
  sentinel to satisfy the meta pass.

Minor observations (LOW, not blocking):
- Uses `datetime.utcnow()` (naive). Codebase antipattern more than a
  test defect.
- Imports `_make_hass` from `test_optimization_coordinator` — creates a
  test-file-to-test-file coupling. If that fixture ever moves, both
  files break together. Acceptable given the explicit `# noqa: E402`
  and comment.

---

## Framing-C summary

- The AST-slice loader **does** extract from current source at test time
  (`INIT_SRC = (PKG / "__init__.py").read_text()`) — no frozen copy.
- The signal-table override drill proves only the table lookup, not the
  wiring call. See M-2. Sibling test covers the call, so the surface is
  covered overall — but the drill's docstring overclaims.
- The namespace pre-seeding IS a hollow-anchor vector, already
  demonstrated in-cycle by the D2 fix-up. See M-1.
- Opt-meta tests drive real code paths cleanly; no engine-echoed
  fixtures, no hand-built imitations of production behavior — only DB
  input is faked, which is the correct boundary.
- No test regresses under legitimate mutation of the production code
  under review (verified by reading, not re-mutating — Tier 2-DB
  framing).

Ship. Fix M-1 and M-2 in cycle-close or as a hygiene follow-up carded
against the next reload/signal-table touch. LOWs may be batched into
the same follow-up.

— Reviewer C, 2026-08-15


---

## Addendum — 2026-08-15 (post fix-up 3/3)

Orchestrator re-drill of the H-1 wire-in anchor after fix-up commits
`57239c799` + `0a661fa13` exposed a **drill methodology defect** in the
builder's original anchor + drill process. Recording it here so future
cycles inherit the correction.

### What happened

Builder shipped `test_seed_helper_call_site_exists_in_integration_setup_path`
as a substring-match (`in integration_span`) source-grep anchor for the
H-1 seed-call site at `__init__.py:~3877`. Builder's own drill neutered
the call via `pass`-replacement (`_seed_integration_last_applied_options(hass, entry)`
→ `pass  # NEUTERED`) — the grep test caught it because the substring
was gone. Builder reported the anchor as load-bearing.

Orchestrator re-drill applied a different neuter: **comment-out**
(`# _seed_integration_last_applied_options(hass, entry)  # …`). The
substring survived inside the comment, so the grep-based anchor stayed
green with the production call dead. Orchestrator then applied a
**hard-delete** (line removed entirely) — the grep test finally failed,
but the sibling behavioral test
`test_first_post_restart_save_suppresses_when_snapshot_unseeded_by_test_but_seeded_by_setup`
ALSO stayed green because it invokes the seed helper itself via
`ns["_seed_integration_last_applied_options"](hass, entry)` rather than
driving the setup path. Hollow-anchor variant #5 (simulate-not-drive)
on the cycle's blocker fix.

### Fix (fix-up commit 3/3)

- Replaced `test_seed_helper_call_site_exists_in_integration_setup_path`
  with `test_seed_helper_call_node_exists_in_integration_setup_ast`,
  which parses `__init__.py` with `ast.parse`, walks
  `async_setup_entry` for the `if entry_type == ENTRY_TYPE_INTEGRATION:`
  branch, and asserts a live `ast.Call` node whose callee is
  `_seed_integration_last_applied_options` exists inside that branch.
  AST is comment-invisible; `pass`-replacements delete the Call. All
  three drill variants (comment-out / hard-delete / pass-replacement)
  now fail the anchor by name.
- Ordering check reuses the same AST walk (locates the
  `entry.add_update_listener(_async_update_listener)` Call and compares
  line numbers).
- Renamed the sibling behavioral test to
  `test_seed_helper_when_invoked_makes_first_save_suppress_reload` and
  documented its scope explicitly: HELPER behavior, NOT setup-path
  driver. The AST anchor is what guarantees the setup path calls it.

### Drill re-run (2026-08-15, post fix-up 3/3)

| Variant | Neuter | Prior grep anchor | AST anchor (this fix-up) |
|---|---|---|---|
| Pass-replacement | `_seed_integration...(hass, entry)` → `pass  # …` | ✅ caught (substring gone) | ✅ caught (Call node gone) |
| Comment-out | `_seed_integration...(hass, entry)` → `# _seed_integration...` | ❌ MISSED (substring in comment) | ✅ caught (comment ignored by AST) |
| Hard-delete | line removed | ✅ caught (substring gone) | ✅ caught (Call node gone) |

### Methodology note (durable, add to `feedback_hollow_test_anchors`)

- **Source-grep-as-test anchors have TWO blind spots relative to AST**:
  (1) block comments containing the anchored substring (see the
  Bug-Class-#46 note comment at `__init__.py:1601-1605` that mentions
  `entry.add_update_listener(_async_update_listener)` textually);
  (2) commented-out call sites (`# helper(...)`) that leave the
  substring intact but the Call dead.
- **Builder-run drills MUST use ≥2 neuter styles per site** —
  `pass`-replacement AND comment-out AND hard-delete. A single neuter
  style is not enough to detect substring-anchor blind spots. The
  operator's meta-rule: if the anchor is a `str.__contains__` call,
  the drill MUST include comment-out.
- **Behavioral tests that invoke the fixed helper directly ≠ tests of
  the wire-in.** The two must be distinct; the wire-in anchor must
  parse production source and assert a live Call node in the expected
  scope.

— Addendum, 2026-08-15
