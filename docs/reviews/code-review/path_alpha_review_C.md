# PATH-ALPHA — Review C (Test-Fixture Authority + Hollow-Anchor Hunt)

**Cycle:** PATH-ALPHA (D1-D9 + EV riders)
**Branch under review:** `feature/path-alpha` @ `02f5e79f7`
**Worktree:** `.claude/worktrees/path-alpha-build`
**Diff vs:** `develop` (`3ac0c956b`)
**Framing (C):** test fixture authority, hollow-anchor variants (7 catalogued), engine-echo, drill re-run
**Reviewer:** Oji Udezue
**Date:** 2026-08-16

---

## Verdict

**FIX-THEN-SHIP.** No suite regressions and the wire-in drill matrix reproduces cleanly for the delete + comment-out shapes on all 5 anchors. One HIGH is a load-bearing test-authority defect (the D2b vocabulary pin scans two non-existent paths and silently no-ops on the entire classifier surface). One HIGH is a spec/impl gap (matrix row 5 has no emission site and no test). Two MEDs are anchor-shape blind spots with cheap zero-cruft strengthenings.

Fix C-HIGH-1 and adjudicate C-HIGH-2 before ship. The two MEDs may fix in-cycle (each is ~10 LoC in a test) or defer with a tracked follow-up per the operator's LOWs-in-cycle discipline; recommendation is fix in-cycle because both are one-line anchor changes and the anchor authority is the whole point of Framing C.

---

## Authoritative Suite Numbers

Run under `PYTHONDONTWRITEBYTECODE=1`, `__pycache__` purged in both trees before the run, sequential (no concurrent pytest — prior sessions have deadlocked that way).

| Tree                    | failed | passed | skipped | xfailed | wall     |
|-------------------------|-------:|-------:|--------:|--------:|----------|
| `feature/path-alpha`    |    24  |  9159  |     45  |     2   | 205.96 s |
| `develop` (baseline)    |    25  |  9078  |     45  |     2   | 202.41 s |

**Failing-name set diff (names, not just counts):**
- Failing on `develop` only (fixed on feature): `test_snap1_frigate_capture_refuses_traversal_event_id`
- Failing on `feature` only (regressions): **NONE** (empty set)
- Common failing: **24** (all pre-existing baseline failures)

**Net:** +81 passing tests on feature (consistent with the new fixture files), −1 baseline failure. Builder's suite claim matches (baseline was actually 25 → 24 due to the eliminated frigate traversal failure; builder reported 24/24). No mismatch. No regression.

---

## Findings

### C-HIGH-1 — Vocabulary-pin retired-literal scan is inert on the two load-bearing surfaces (hollow variant 6, silent-pass)

**File:** `quality/tests/test_tracking_reason_vocabulary_pin.py:88-134`
**Severity:** HIGH — a real coverage hole disguised as an anchor.

The `_SCAN_TARGETS` list references:
- `custom_components/universal_room_automation/domain_coordinators/person_coordinator.py` — **does not exist** (real path is `custom_components/universal_room_automation/person_coordinator.py`, no `domain_coordinators/` prefix)
- `custom_components/universal_room_automation/domain_coordinators/aggregation.py` — **does not exist** (real path is `custom_components/universal_room_automation/aggregation.py`)

Combined with the guard at line 133-134 (`if not target.exists(): continue`), the loop silently no-ops on the two paths, and `test_retired_values_not_reachable_as_literals` will PASS even if a retired reason (`bermuda_degraded`, `home_gps_only`) is re-introduced as a literal in either file. Only `presence.py`, `sensor.py`, and `binary_sensor.py` are actually scanned — the classifier surface (`person_coordinator.py`), which is precisely where D2a introduced the reason vocabulary, is uncovered.

**Repro (Investigator #2 confirmed):** appending `x = "bermuda_degraded"` to `person_coordinator.py` leaves the suite green.

**Fix (minimal, no cruft):**
1. Correct the two paths in `_SCAN_TARGETS` (drop the `domain_coordinators/` segment).
2. Convert the silent skip into a self-alarm: `assert target.exists(), target` before the `continue`, or precompute the list at module load and hard-fail collection. Prevents the exact class of drift that produced this defect.

Blast radius: any future rename or move of a scanned surface silently defeats the pin unless self-alarmed.

---

### C-HIGH-2 — 16-row matrix row 5 collapsed with row 4; `anomalous_wifi_gone_local_home` reason has no emission site and no test (hollow variant 4 / coverage gap)

**File:** `quality/tests/test_path_alpha_d2a_matrix_classifier.py:302-305`, `person_coordinator.py:315-319`, plan §THE UNIFIED MATRIX row 5.
**Severity:** HIGH — requires builder/planner adjudication before ship (unimplemented emission site OR dead vocabulary).

- Plan row 5: `GPS=home, WiFi=not_home, BLE=visible@<home_room>` → reason `anomalous_wifi_gone_local_home` (conf 0.85).
- Fixture rows 4 and 5 both use `ble="silent"` and both expect `anomalous_gps_stale_local_gone`. Row 5 is a mis-copy of row 4; the plan's `BLE=visible@<home_room>` sub-case is not exercised.
- Production `_classify_matrix_row` unconditionally returns `anomalous_gps_stale_local_gone` for `gps=="home" AND wifi=="not_home"` regardless of the BLE axis. There is no branch that emits `anomalous_wifi_gone_local_home`.
- Yet `anomalous_wifi_gone_local_home` IS a member of `TRACKING_REASON_VALUES` (vocab pin line 72) — so the vocabulary carries a value with no writer.

**Two possible truths, either is a defect:**
- (a) Row 5 was meant to be handled at the row-1-resolved BLE-visible@home_room site, in which case a dedicated test at that call site is missing and the classifier is under-branching.
- (b) The reason is dead vocabulary. Then remove it from `TRACKING_REASON_VALUES` — carrying dead names invites future authors to write dead code.

**Fix:** planner/builder adjudicate before ship; then either implement the branch + add a matrix row that exercises it, OR delete the vocabulary entry (updating any downstream consumer that references the string).

---

### C-MED-1 — All 5 wire-in anchors blind to `if False:` gating (shape C); D5 reconcile also blind to shape D (except-branch duplicate) — Framing-C authority gap

**Files:** the 5 wire-in anchors in `quality/tests/test_memory_writers.py` (D4 phantom_retro, D5 note_tick, D5 reconcile, D6 tracker_trust, D7 house_state_transition).
**Severity:** MED — anchor authority gap, not a shipped-code defect.

Drill matrix (re-run by Investigator #1, `PYTHONDONTWRITEBYTECODE=1`, caches purged, `git status` clean between drills):

| Anchor                              | Call site               | A: delete | B: comment | C: `if False:` | D: try-only |
|-------------------------------------|-------------------------|:---------:|:----------:|:--------------:|:-----------:|
| D4 phantom_retro                    | coordinator.py:2813     | RED       | RED        | **GREEN**      | n/a         |
| D6 tracker_trust                    | presence.py:5884        | RED       | RED        | **GREEN**      | n/a         |
| D7 house_state_transition           | presence.py:6351        | RED       | RED        | **GREEN**      | n/a         |
| D5 note_tick                        | presence.py:5865        | RED       | RED        | **GREEN**      | n/a         |
| D5 reconcile / gate assign          | presence.py:2357, 2360  | RED       | RED        | **GREEN**      | **GREEN**   |

All 5 anchors use `ast.walk` + `isinstance(node, ast.Call)`. An `ast.If(test=ast.Constant(value=False))` wrapper leaves the `Call` visible → passes. No behavioural mirror in the current suite fails under `if False:` gating: the entire `test_memory_writers.py` suite (25/25) stays green when any of the sites is `if False:`-wrapped in isolation.

**D5 reconcile shape-D specific:** deleting only the try-branch gate assign at presence.py:2360 leaves the except-branch duplicate at :2372, so `_away_block_reconcile_done` is only ever set from the failure path. The anchor stays GREEN. Full suite: 25/25 green. The tick-loop guard at presence.py:5857 (`if not _away_block_reconcile_done: return`) is then permanently suppressed on the happy path — a Suppression-needs-Discharge / Bug Class #53 (computed-but-not-consumed) violation of the D5 writer chain. **Shipped code is correct** (both branches assign True); the anchor is over-permissive.

**Adjudication:** FINDING, MED. Delete/comment coverage is not sufficient on its own — `if False:` is a real-world debugging edit pattern; if an operator silences a writer that way, the suite currently ships green.

**Minimal strengthening (adopt, no framework, no cruft):**

1. In the anchor's `ast.walk` helper (`_count_call_names_in_source`), add a pre-pass that prunes unreachable branches BEFORE walking. ~6 lines applied uniformly across all 5 anchors, or once in a shared helper:

    ```python
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and isinstance(node.test, ast.Constant) and node.test.value is False:
            node.body = []
        if isinstance(node, ast.If) and isinstance(node.test, ast.Constant) and node.test.value is True:
            node.orelse = []
    ```

   Closes shape C for all 5 anchors uniformly. Zero runtime framework cost.

2. For the D5 reconcile anchor, tighten branch scope: walk `async_setup_fn.body` for the enclosing `ast.Try`, require `_away_block_reconcile_done = True` assignment inside `try.body` (NOT `except handlers`). Encodes the actual invariant "gate opens on success path." ~8 LoC.

Both are one-file test changes, no dependencies, no config knobs.

---

### C-MED-2 — Matrix `sources["ble"]` axis is a red-herring input; `tracker_sources.ble` output not asserted anywhere

**File:** `quality/tests/test_path_alpha_d2a_matrix_classifier.py` (harness), `person_coordinator.py:297` (production ignores `sources["ble"]`, uses `ble_axis` param).
**Severity:** MED — small coverage gap; not defect-hiding today.

`_classify(...)` passes `sources={"gps":..., "wifi":..., "ble":"MISSING"}` and expects an identical `sources_out` stamp. Production ignores `sources["ble"]` and never re-derives it from `ble_axis` for the output stamp. The plan lists `tracker_sources` as part of the emitted attribute; the fixture never asserts the BLE component of `tracker_sources` reflects the actual `ble_axis` parameter. If a future change wires `ble_axis` back into the stamp incorrectly, the matrix won't catch it.

**Fix:** add one row asserting `row["tracker_sources"]["ble"]` matches the post-liveness-degrade axis (with an explicit non-`MISSING` value). Low blast radius. Could ship as a follow-up.

---

### C-LOW-1 — Builder-claimed "4 hvac.py memory-episode string references" allowlist: actually 2, both legitimate

**File:** `quality/tests/test_memory_writers.py` consumer-graph allowlist (`("domain_coordinators/hvac.py", "house_state_transition")`).
**Severity:** LOW — documentation drift, no coverage impact.

Grep of `custom_components/universal_room_automation/domain_coordinators/hvac.py` for `house_state_transition` returns 2 lines (not 4):

| Line | Context                                                              | Unrelated to memory episodes? | Note                   |
|-----:|----------------------------------------------------------------------|:-----------------------------:|------------------------|
| 1911 | `preset_change_reason = "house_state_transition"` (fallthrough)      | Y                              | HVAC preset-ledger tag |
| 1967 | `"house_state_transition"` inside `_s1_defer_reasons` set            | Y                              | HVAC DEFER logic       |

Both are legitimate HVAC-preset-reason string tags, unrelated to the D7 memory-episode writer. The file-level allowlist is honest; consider tightening to per-line tuples if you're re-touching the fixture for other reasons.

---

## Fixture-Authority Per-File Roll-up

| File                                                    | Verdict | Notes                                                                                          |
|---------------------------------------------------------|---------|------------------------------------------------------------------------------------------------|
| `test_path_alpha_d2a_matrix_classifier.py`              | SOFT    | Rows DRIVE production `_classify_matrix_row`; row 5 collapsed (C-HIGH-2); ble-axis red-herring (C-MED-2). |
| `test_memory_writers.py`                                | CLEAN   | Real DAO writers driven; DB mocked at coherent boundary (`log_memory_episode`); consumer-graph is string-grep on quoted literals, adequate for its stated boundary claim. |
| `test_path_alpha_d8_gap_a_face_only.py`                 | CLEAN   | Production sensor loaded via file-path spec and driven; mocks scoped to HA runtime stubs only. |
| `test_path_alpha_d9_room_corroboration.py`              | CLEAN   | As above.                                                                                      |
| `test_pathalpha_d2c_d3_observability.py`                | CLEAN   | As above.                                                                                      |
| `test_tracking_reason_vocabulary_pin.py`                | HOLLOW  | Two non-existent scan targets + silent-skip guard = C-HIGH-1 (variant 6 assertion-free-by-skip). |

---

## D2b Migration Coverage Audit

Migrated tests: `test_v570_fixup_wiring.py`, `test_v570_guest_detection_trust.py` (Investigator #3).

- `test_v570_fixup_wiring.py`: coverage preserved. Every removed assertion has a matching replacement asserting the D2b behaviour (kill-switch source anchor for the relaxed-predicate retirement). No downgraded truthy checks.
- `test_v570_guest_detection_trust.py`: coverage preserved. LOST-admission-list retirement is asserted both positively (D2b path taken) and negatively (old relaxed-predicate path no longer accepts the previously-accepted case).
- `test_v4715_universalize_veto.py` one-line change: not a coverage loss — literal-string update to reflect the D2b reason renaming.

Verdict: CLEAN. No quiet weakening.

---

## What Passed (Framing-C signal, not just absence of findings)

- Suite integrity: matches builder claim, no regressions, one baseline failure eliminated, +81 net passing tests all from real production classes driven end-to-end.
- 4 of 5 wire-in anchors are AST-based but do redden under the two most common neuter shapes (delete + comment). Framing-C-visible authority is real for those shapes.
- `test_memory_writers.py` writer coverage genuinely exercises `custom_components/universal_room_automation/database.py` DAOs with the queue mocked at the async_add_executor_job boundary — not hand-rolled SQL.
- D8 / D9 / D2c observability sensor tests load production sensor classes via `importlib.util.spec_from_file_location` and DRIVE them; mocks are confined to HA-runtime stubs.
- D2b migration preserved and added negative tests.

---

## Blocking-vs-Non-Blocking Summary

| Finding    | Severity | Blocker for ship? | Recommended action                                       |
|------------|:--------:|:-----------------:|----------------------------------------------------------|
| C-HIGH-1   | HIGH     | **YES**           | Fix paths + self-alarm on missing scan target (~4 LoC).  |
| C-HIGH-2   | HIGH     | **YES** (adjudicate) | Planner+builder: implement branch OR delete dead vocabulary; then add matrix row or vocab removal. |
| C-MED-1    | MED      | No (fix in-cycle) | AST pre-pass for unreachable `If`; try-scope for D5 reconcile anchor. ~14 LoC total. |
| C-MED-2    | MED      | No                | Add one matrix row asserting `tracker_sources["ble"]` reflects `ble_axis`. |
| C-LOW-1    | LOW      | No                | Optional per-line tightening of allowlist.               |

---

## Non-Findings / Explicit Passes

- Suite regressions: NONE.
- Engine-echo in D2a matrix: expected values are fixture literals independently authored per row; not derived from the SUT. (Row 5's error is a copy-paste of row 4's expected, not an engine-echo.)
- Dead spies in observability tests: none found — mocked objects match production surface.
- Assertion-free smoke tests in D8/D9/D2c: none found.
- Over-broad mocks masking `NameError` in the new files: none found; MagicMock scope is HA-runtime stubs and dependencies of the SUT, not the SUT itself.
- Consumer-graph string-grep allowlist for hvac.py: honest (see C-LOW-1).

---

## Recommendation

**FIX-THEN-SHIP.** Fix C-HIGH-1 (four-line path correction + self-alarm) and adjudicate C-HIGH-2 (dead vocab vs missing branch) before deploy. Fix C-MED-1 and C-MED-2 in-cycle if the fix-up round is running anyway; both are trivial and both strengthen Framing-C authority, which is the whole point of the review. Once the two HIGHs are resolved, this cycle is safe to ship — no shipped-code regressions and the additive test surface is honest.
