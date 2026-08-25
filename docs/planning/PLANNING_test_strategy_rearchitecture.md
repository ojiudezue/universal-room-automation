# PLANNING — Test Strategy Re-Architecture (measure-first)

**Card:** `TEST-STRATEGY-REARCH-1` (parent — see `docs/planning/kanban.data.yaml:6735`)
**Branch:** `develop`
**Tier:** measurement cycle first; re-architecture proposals are OUT OF SCOPE until the measurement deliverables land and their numbers gate them in.
**Author role:** ura-planner
**Cycle posture:** This is a MEASURE-BEFORE-BUILD cycle per the standing rule in `CLAUDE.md`. No re-architecture is scoped. Every downstream deliverable is gated by a number produced here.

---

## Institutional context verified

Prior art / documents consulted end-to-end for this plan:

- `docs/planning/kanban.data.yaml:6735-6771` — parent card `TEST-STRATEGY-REARCH-1`, plus the concrete `pytest_restore_hook_2026_08_19` sub-note (source-mutating test without guaranteed restore; parallel-collision root cause in miniature).
- `docs/QUALITY_CONTEXT.md:2399+` — **Bug Class #62 (Source-text/grep-only test assertion)** already codified. The three source-text failures cited in the founding evidence are instances of this class; we do NOT re-name it — we count and classify.
- `CLAUDE.md`:
  - "Measure Before You Build" (probe-first gate).
  - "Marginal-Benefit Decomposition" — the re-architecture MUST wait until the simplest fixes are priced against margins.
  - "Producer AND Consumer checks" — applied to the suite as a producer of pass/fail signal.
  - "Post-Ship Supersession & Consumer-Gap Audit" — will apply once measurement work ships; not this doc.
  - "Serialise suite runs across agents" + "Unrestored drill poisons evidence" memories — direct evidence of the wedge and source-mutation classes.
- Memory: `feedback_wire_in_anchor_mandatory` (hollow-anchor recurrence — 4th cycle running), `feedback_hollow_test_anchors`, `feedback_mutation_verification_pycache_staleness`, `feedback_serialise_suite_runs_across_agents`, `feedback_unrestored_mutation_drill_poisons_evidence`.
- Prior planning: `docs/planning/PLANNING_v4.5.2_test_baseline_cleanup.md` (skimmed — earlier baseline effort; note that a "baseline cleanup" cycle already exists in the arc and did NOT durably fix the 158 floor — supersession bucketing later).
- Existing infra: `scripts/hooks/pytest_serialize.sh` (referenced by parent card; the KILL-not-queue guard whose behaviour matters for D5 wedge diagnosis).
- Referenced sibling cards: `SUITE-ORDER-POLLUTION-1` (subsumed by this parent), the STEP-C-CRIT and fan-recheck audit docs, and the v5.8.0 setup recursion incident (`project_incident_v5_8_0_setup_recursion.md`) — the canonical hollow-fake-at-coordinator-boundary example.

Every deliverable below either measures against these surfaces or reads them; nothing proposes new production constants, sensors, or config knobs — this is a test-infrastructure investigation.

---

## Falsifiable framing (up front)

**Load-bearing claim being measured:** *"The URA test suite, as it stands on develop, produces a low-signal pass/fail: its normal state is 158 failing tests with unknown provenance; a real regression is only visible by set-diff against a large noisy baseline; and the top noise sources (order pollution, source-text tests, hollow anchors, teardown wedge) are quantifiable and rank-orderable by leverage."*

The cycle succeeds if — and only if — every measurement deliverable produces a number an operator can act on (triage bucket counts, per-file order-pollution deltas, source-text test census, hollow-anchor sample rate, wedge reproduction rate + root cause). It fails if any deliverable ships as narrative without a number.

**Discriminating observation up front (avoids intuition-led conclusions):**
- If D1 shows the 158 is dominated by ONE bucket (e.g. >100 are order-pollution), the leverage answer is D2, not D3/D4.
- If D2 shows per-file deltas are small and scattered (long tail), the leverage is a shared-fixture reset, not point fixes.
- If D2 shows a small number of DONOR modules cause most of the deltas, the leverage is quarantining/fixing those donors.
- These predictions are made BEFORE running D1/D2 so the numbers select the fix, not the other way around.

---

## Non-goals (explicit)

- **No re-architecture proposal in this doc.** No "adopt pytest-xdist," no "REAL-COORD HARNESS," no shared-fixture redesign. Those are candidate follow-up cards that this cycle's numbers may or may not justify.
- **No deleting or `@skip`-ing failing tests to get green.** Explicit operator constraint. The 158 must be triaged into buckets with evidence, not swept.
- **No modifying tests or production code.** Read-only measurement. If a probe needs a temporary throwaway edit, it is done on a scratch branch or in `/private/tmp/.../scratchpad/` and NEVER committed to `develop`.
- **No full-suite runs during this cycle from any agent unless the wedge repro (D5) explicitly requires one.** Operator instruction. Use file-level or narrow multi-file selections, with `PYTHONDONTWRITEBYTECODE=1` and a `__pycache__` scrub between runs.
- **No new sensors, CONF_*, entities, or production constants.**

---

## Deliverables

Each deliverable has a **PRODUCER check** (how the number is produced, what its dependencies are, whether they are healthy) and a **CONSUMER/decision** (what call gates on the number).

### D1 — Baseline triage: bucket the 158 failing tests

**Producer.** Use the operator-provided baseline: `141 failed + 17 errors = 158`, identical set on `develop` and the feature branch as of 2026-08-22/23. That list IS the input; DO NOT re-run the full suite to regenerate it. Persist the failing-test-id set (from the operator-provided baseline JUnit XML if available, otherwise a one-shot single full-suite run — see D5 gate) to `docs/planning/artifacts/test_strategy/baseline_158.txt`.

For each of the 158 ids, classify into exactly one bucket by lightweight inspection (open the test, read the failure line if captured, correlate to the file/class):

- **B1 — real product defect.** The test drives real code and the code is wrong. Evidence required: a one-line description of the defective behaviour and the production file:line implicated. These become candidate hotfix cards.
- **B2 — broken test (stale intent).** The behaviour under test was intentionally superseded (like the v4.7.9 `test_no_triggered_by_parameter_added` case). Evidence required: the superseding cycle/commit or the current behaviour that the test contradicts.
- **B3 — order pollution victim.** Test passes when run alone; fails only in suite. Evidence: single-file re-run passes. (Cross-check with D2.)
- **B4 — environment / collection error.** ImportError, IndexError at collection, missing stub in `sys.modules`, `IndexError` off `__path__[0]` (the `test_reboot_pickup_d2.py:151` pattern). Evidence: the exception at collection time.
- **B5 — flaky (nondeterministic).** Passes on some re-runs alone. Evidence: 3 alone-runs, mixed results.

**Method.** Iterate through the failing-id set. For each id, run ONLY that test file in isolation with `PYTHONDONTWRITEBYTECODE=1` and cache-scrub. Record the alone result. That single observation places most ids in B1/B2 vs B3/B4/B5 immediately; only edge cases require inspection.

**Output.** `docs/planning/artifacts/test_strategy/D1_triage.md` — a table with columns: `test_id | file | bucket | evidence-1liner | candidate-card-id-or-none`. Plus a bucket-count summary.

**Acceptance criteria (DISCRIMINATING).**
- **Verify:** table has 158 rows, one row per failing id from the baseline set. Under the fix: rows sum to 158. Under a plausible different failure (silent drops): row count ≠ 158 — this fails.
- **Verify:** every row has evidence non-empty AND either a superseding cycle (B2), a production file:line (B1), a single-file re-pass observation (B3), a collection trace (B4), or three alone-run results (B5).
- **Verify:** bucket-count summary reports `B1 + B2 + B3 + B4 + B5 == 158` exactly.
- **Discriminator:** if any bucket is empty, the doc must state EXPLICITLY "zero found after full sweep" — not omit the bucket. An empty bucket that is silently missing is a fail.

**Self-validation:** the suite cannot validate its own triage. Verification is by orchestrator spot-check of ≥10 randomly-drawn rows against the actual test file — this is the "cannot fully self-validate" mitigation.

---

### D2 — Order-pollution map: per-file alone-vs-suite delta

**Producer.** For each test file under `quality/tests/`, run the file in isolation with `PYTHONDONTWRITEBYTECODE=1` + cache scrub and record `(alone_pass, alone_fail, alone_error)`. Compare against the file's in-suite result from the operator-provided baseline (or the single D5-gated full-suite run). Delta = `alone_pass - in_suite_pass` on the tests that appear in both.

Dependency health: this producer depends on (a) the alone-run being deterministic — verify by re-running the top-5 delta files three times; (b) `PYTHONDONTWRITEBYTECODE=1` genuinely defeating stale bytecode (per `feedback_mutation_verification_pycache_staleness`); (c) NO source mutation surviving between runs (per the STEP hook incident — run `git status` between file batches; abort if the tree is dirty).

**Method.** Iterate all files under `quality/tests/`. For each: single-file run, capture JUnit output, diff against baseline. Persist raw per-file JUnit under `docs/planning/artifacts/test_strategy/D2_alone_runs/<file>.xml`. Aggregate `docs/planning/artifacts/test_strategy/D2_pollution_map.md`.

**Output.** Ranked table: `file | alone_fail | in_suite_fail | delta | is_donor_hypothesis`. A **donor hypothesis** is filed when file X's presence in the run correlates with file Y's failures — measure by running suspected donors + one candidate victim as a two-file selection and seeing whether the victim fails. The `test_ac_ramp_pipeline_hardening.py` case (71/71 alone, 11 failed in suite) is the seed victim; use it to identify at least one donor if possible. Do NOT exhaustively enumerate donor-victim pairs — that is n² and out of scope; identify only the top 3 donors by two-file drill.

**Acceptance criteria (DISCRIMINATING).**
- **Verify:** every test file under `quality/tests/` appears exactly once in the ranked table. Under the fix: table row count == file count. Under silent drops: mismatch.
- **Verify:** `test_ac_ramp_pipeline_hardening.py` is present with alone_fail=0, in_suite_fail=11 (matches operator-provided seed observation). If it doesn't reproduce, the environment differs from the baseline — the whole D2 measurement is invalid until reconciled.
- **Verify:** total delta across all files ≥ the delta explained by D1's B3 count (they should be consistent — B3-count is a subset of the total delta explained by pollution, because a file may have "in-suite-fail=alone-fail" and still contribute B3-classified tests to another file).
- **Discriminator:** if the top-donor hypothesis reproduces (running donor+victim as a 2-file selection fails the victim), the pollution model is validated. If NO donor reproduces the victim's failures, the mechanism is not simple sibling replacement — the finding is that the leak is more diffuse than the ac_ramp cycle suggested. Both outcomes are reportable; a doc that concludes "pollution exists" without either observation is unacceptable.

**Self-validation:** the suite cannot self-validate this map; orchestrator verifies by picking 3 non-top-donor files and re-running two-file selections to confirm the delta is stable.

---

### D3 — Source-text test census (Bug Class #62 population)

**Producer.** Grep `quality/tests/` for the fingerprints of source-text assertions: literal patterns like `_src`, `\.find\(`, `re\.search\(.*source`, `inspect\.signature`, `read_text` inside a test, `open(.*\.py`, and `getsource`. For each hit, open the test and classify:

- **C1 — legitimate structural guard.** e.g. asserting that a constant is DECLARED as a module const (rung guard). Sometimes correct; the operator has to decide.
- **C2 — policy-encoded-as-test.** Encodes a decision from a superseded cycle that a later cycle deliberately reversed (the v4.7.9 `test_no_triggered_by_parameter_added` case).
- **C3 — value over-specified.** Asserts a specific literal (`"Final = 12"`) when the STATED intent is a rung/property (the `test_settle_delay_constant_declared_as_module_const` case). Behavioural intent, textual assertion.
- **C4 — indirection victim.** Uses `str.find` + scan-to-next-def, hits a comment or a lookalike (the `test_retention_uses_batched_delete` case). Wrong by construction.

**Method.** Grep produces the candidate set; open each hit; classify by reading (no runs required — this is a pure inspection producer). Cite each with `file:line` and one-line rationale.

**Output.** `docs/planning/artifacts/test_strategy/D3_source_text_census.md` — table `test_id | file:line | class | rationale | superseding-cycle-if-C2 | true-behavioural-anchor-if-C3/C4`.

**Acceptance criteria (DISCRIMINATING).**
- **Verify:** the three concrete instances the operator named all appear in the census with the classifications C4, C2, C3 respectively. If any is missing or misclassified, the census methodology is wrong.
- **Verify:** total count is a finite number stated in the doc. "Many" is not a number.
- **Discriminator:** if C2+C3+C4 sum is comparable to C1 (say ≥ 25% of the total), the class is systemic — that outcome argues for a follow-up card converting them to behavioural anchors. If C1 dominates (>90%), source-text tests are mostly legitimate and only the identified instances need per-test fixes. Report both possibilities and let the numbers decide.

**Self-validation:** grep + inspection; verifiable by orchestrator re-run of the grep.

---

### D4 — Hollow-anchor sampling: helper-tested vs call-site-tested

**Producer.** Identify N=15 "load-bearing wire-in sites" — call sites in production code that a recent cycle claimed to have covered with a test. Draw from: (a) sites cited in the last 6 planning docs under `docs/planning/PLANNING_*`, (b) any file with a `# wire-in: <helper>` comment or similar convention, (c) call sites of the helpers named in the last 6 review docs under `docs/reviews/` (if present). For each site, perform the CANONICAL DRILL:

1. In a scratch worktree (`.claude/worktrees/test-rearch-d4/` per worktree isolation rule), NEUTER the CALL SITE (comment it out, or replace with `pass`).
2. Run the test file(s) that are supposed to cover it. Record: does ANY test fail? If yes — the site is covered. If no — the site is hollow (a helper-level drill would pass while the call site is unguarded).
3. RESTORE the mutation immediately. Run `git status` to confirm clean. This is the "unrestored mutation drill poisons evidence" backstop.

Dependency health: (a) `PYTHONDONTWRITEBYTECODE=1` per mutation-pyc-staleness memo; (b) worktree isolation per feedback memo; (c) git-status check after each drill.

**Method.** N=15 chosen for cost — this is a sampling deliverable, not exhaustive. The seed instance is documented: `_verify_restore` call site (Tier-3 review case). Include it as sample #1 and confirm the observation reproduces.

**Output.** `docs/planning/artifacts/test_strategy/D4_hollow_anchor_sample.md` — table `site | file:line | drill result (covered/hollow) | supposed covering test | notes`. Plus a computed hollow rate `H/15`.

**Acceptance criteria (DISCRIMINATING).**
- **Verify:** sample #1 (the `_verify_restore` call site) reproduces the reviewer's finding (the call site can be deleted with tests green). If it does NOT reproduce, either the site has since been fixed OR the drill methodology is wrong — investigate before continuing D4.
- **Verify:** every drilled site has an "after" `git status` line showing clean worktree, quoted in the doc. Any missing status line = evidence-poisoning risk = the row is invalidated.
- **Discriminator:** hollow-rate outcomes: `H/15 ≥ 5/15` argues the anchor pattern is systemic (fifth cycle running per operator note → warrants a mandatory-anchor cycle). `H/15 ≤ 1/15` argues the recent cycles' 6/12 rate was an outlier for those files. Both outcomes are reportable; both suggest different follow-ups.

**Self-validation:** the suite ITSELF is the oracle — a drill that leaves tests green IS the finding. This is the one deliverable that self-validates by construction. Orchestrator spot-check verifies the mutation was real (open the scratch worktree diff before restore) and the restore is clean.

---

### D5 — Teardown wedge diagnosis

**Producer.** Reproduce and diagnose the observed teardown wedge — pytest processes surviving after JUnit XML is written, four instances in 24h (three at ~19h48m elapsed, one at 2h32m). This is the ONE deliverable that may require a full-suite run; because runs wedge, GATE this deliverable on operator explicit approval before triggering, and run at most ONE full-suite invocation during the cycle. Use `pytest --timeout=<n>` plus `faulthandler` + `pytest --trace-config` + `py-spy dump` on the surviving PID to identify:

- non-daemon threads still alive at process end,
- unclosed asyncio event loops,
- HA `async_track_*` listeners not cancelled,
- open file/DB handles,
- background tasks spawned by test fixtures without cancellation.

Dependency health: (a) `py-spy` availability on the host — check first; if unavailable, fall back to `/proc/<pid>/stack` on Linux or `sample <pid>` on macOS; (b) the wedge is reproducible on the current develop tree — if D5's single run does NOT wedge, the finding is that either the wedge is intermittent (report the observed rate) or something has changed since the operator's four observations.

**Method.**
1. Confirm no leftover pytest process is running (`pgrep pytest`). If one exists, capture its state (`py-spy dump`, thread list) BEFORE killing — that IS the primary evidence and may make the D5 full run unnecessary.
2. If no leftover exists, request operator approval for ONE full-suite run with `--timeout=600` and instrumentation attached.
3. Whether from the leftover or the fresh run: identify the top blocking primitive (thread name, coroutine, listener).

**Output.** `docs/planning/artifacts/test_strategy/D5_wedge_diagnosis.md` — either a named root cause (thread/loop/listener with file:line origin) with a proposed mechanical reaper spec (`pytest_sessionfinish` hook doing X), OR a documented failure to reproduce with the observed rate.

**Acceptance criteria (DISCRIMINATING).**
- **Verify:** doc either (a) names ONE specific blocking primitive with file:line, or (b) reports "did not reproduce in N=1 attempt after M leftover-process checks" — no third outcome allowed. "Probably an unclosed loop" is not a permitted answer.
- **Verify:** if a root cause is named, a proposed fix specification exists (reaper hook, fixture change, whatever) — with the note that IMPLEMENTATION is a separate card, not this cycle.
- **Discriminator:** a named blocker + fix spec discriminates from "the wedge is diffuse." Both are legitimate outcomes; a doc that concludes "we should investigate more" without either is unacceptable.

**Self-validation:** the suite cannot self-validate. Orchestrator inspects the `py-spy` dump / thread list captured.

---

### D6 — Defensive-code-reading-polluted-state sweep

**Producer.** The `test_reboot_pickup_d2.py:151` failure (`_dc.__path__[0]` IndexError at COLLECTION → whole suite aborts) generalises: defensive code that reads polluted state is not defensive. Grep `quality/tests/` for the fingerprints:

- `__path__[` (indexing into a possibly-stubbed module path),
- `.__file__` reads without `getattr(..., "__file__", None)`,
- `getattr(mod, "__spec__", None).origin` chains without None handling,
- `sys.modules[name].<attr>` where `name` is a production module that other tests are known to stub.

For each hit, open and classify: **safe** (guarded), **at-risk** (unguarded read on a module known to be stubbed), or **already-broken** (the `test_reboot_pickup_d2` sibling class).

**Output.** `docs/planning/artifacts/test_strategy/D6_defensive_read_sweep.md` — table `file:line | pattern | classification | fix-1liner-if-at-risk`.

**Acceptance criteria (DISCRIMINATING).**
- **Verify:** the already-fixed `test_reboot_pickup_d2.py:151` site is confirmed NOT present in the "at-risk" bucket (the fix should have moved it to "safe"). If it's still at-risk, the fix didn't land or has regressed.
- **Verify:** every "at-risk" row has a one-line fix suggestion (mechanical — `getattr` guard, `__file__`-derived path, etc.).
- **Discriminator:** at-risk-count ≥ 3 argues for a follow-up sweep card. At-risk-count = 0 (with the D2 fix confirmed) closes this sub-class.

**Self-validation:** grep + inspection.

---

### D7 — Synthesis + leverage ranking (the "which fix first" answer)

**Producer.** Given D1–D6 numbers, rank the four candidate leverage points by noise-elimination cost/benefit:

| Candidate | Estimated noise removed | Estimated cost | Risk ingredients |
|---|---|---|---|
| Fix top-3 order-pollution donors (D2 output) | B3-count + measured deltas | small | shared-fixture design |
| Convert C2+C3+C4 source-text tests to behavioural anchors (D3 output) | C2+C3+C4 count | medium | per-test rewrite |
| Reap the teardown wedge (D5 output) | freq × orchestrator disruption | small if reaper works | rare-fire correctness |
| Anti-hollow anchor discipline (D4 output) | future-defect prevention (not existing noise) | ongoing | policy, not point fix |

**Method.** Fill the table with the actual numbers from D1–D6. Apply "Marginal-Benefit Decomposition" from CLAUDE.md: for each candidate, state the simplest form of the fix and the marginal risk of any fancier version. Recommend the top-1 to file as a follow-up card; recommend top-2 and top-3 as parked cards with evidence triggers.

**Output.** `docs/planning/artifacts/test_strategy/D7_leverage_ranking.md` — the filled table + one recommendation section + follow-up card stubs (id, title, next).

**Acceptance criteria (DISCRIMINATING).**
- **Verify:** every candidate row has an integer from D1–D6, not a hand-wave.
- **Verify:** the recommendation explicitly names ONE top-leverage follow-up, states the number that justifies it, AND states the number that would reverse the recommendation (the falsifier: "if D2 delta had been < X we would recommend Y instead").
- **Verify:** no follow-up card in the recommendation proposes deleting or skipping tests to reduce the 158; if it did, the deliverable violates the operator constraint.

**Self-validation:** derivative from D1–D6.

---

## Sequencing

D1 and D3 can run in parallel (both are inspection-heavy). D2 must wait for the tree to be quiescent (no other agents running suites). D4 requires a scratch worktree. D5 is gated on operator approval AND on D1–D4 being complete (avoid wedging the tree during other measurement work). D6 is a fast standalone grep. D7 is last, gated on D1–D6 outputs.

```
D1 ──┐
     ├── D7
D3 ──┤
     │
D2 ──┤    (D5 gated on operator approval + D1–D4 done)
     │
D4 ──┤
     │
D6 ──┘
```

---

## Which deliverables self-validate vs need orchestrator verification

A test-infrastructure cycle cannot fully self-validate — that would be circular. Handled per deliverable:

| Deliverable | Self-validates? | Orchestrator verification |
|---|---|---|
| D1 triage | No | Spot-check ≥10 rows against actual test files |
| D2 pollution map | Partial (donor two-file drills self-validate) | Verify 3 non-top-donor files have stable deltas |
| D3 source-text census | No | Re-run the grep, spot-check classifications |
| D4 hollow-anchor sample | **Yes** (drills use the suite as oracle) | Inspect scratch worktree diffs pre-restore + git-status post-restore |
| D5 wedge diagnosis | No | Inspect `py-spy` dump / thread list capture |
| D6 defensive-read sweep | No | Re-run the grep |
| D7 synthesis | No | Numbers traced back to D1–D6 artifacts |

D4's structural self-validation is the strongest signal in the cycle and is treated as the anchor of confidence.

---

## Constraints, ceremony, safety

- **No production code, test code, or config changes committed to `develop`.** All mutations are scratch-worktree, restored before status check.
- **`PYTHONDONTWRITEBYTECODE=1` + `find . -name __pycache__ -exec rm -rf {} +` between D2/D4 runs.** Non-negotiable per mutation-pyc-staleness memo.
- **`git status` after every mutation drill (D4) AND between D2 file batches.** Non-negotiable per unrestored-drill memo.
- **D5 full-suite run is gated on operator approval AND capped at ONE invocation.** Prefer capturing the already-wedged process if one exists.
- **Worktree per worktree-isolation rule: `.claude/worktrees/test-rearch-d4/`.** Never `/tmp/...`.
- **No agent runs the full suite for any reason other than D5.**
- **Artifacts under `docs/planning/artifacts/test_strategy/`** — a new subdirectory; pre-stage with `git add` per release-process convention if any are committed. (These are analysis artifacts, not release deliverables — committing is optional but preferred for the audit trail.)

---

## Explicit non-decisions (parked for follow-up cards, NOT this cycle)

- Whether to adopt a REAL-COORD HARNESS (parent card idea D3).
- Whether to adopt `pytest-xdist` after pollution fixes.
- Whether to delete redundant / obsolete tests (subsumption/supersession).
- Whether to formalize a "no source-text tests" rule in QUALITY_CONTEXT.md (Bug Class #62 already codified; a rule-change is downstream).
- Whether to add a `pytest_sessionfinish` mechanical reaper (D5 may propose the spec; implementation is a separate card).
- Whether to move the `pytest_serialize.sh` KILL semantics to QUEUE (memory says KILL is deliberate; changing it is a policy call).

Each is a candidate follow-up card the D7 synthesis MAY recommend on numbers.

---

## Plan review posture

Per CLAUDE.md "Plan Review — TIERED": this is a measurement (Tier 2-ish) plan. Request ONE adversarial plan review before dispatching D1–D6 work. The reviewer should verify with greps (not trust):
1. That the D3 fingerprint list actually finds the three named instances (independent grep re-run).
2. That the D6 fingerprint list actually finds the already-fixed `test_reboot_pickup_d2` site (should classify as "safe" post-fix).
3. That the D1 bucket definitions are exhaustive and non-overlapping (a test cannot legitimately fall in two buckets).
4. That no deliverable's acceptance criteria could pass via a silent drop (the "count == 158" and "count == file count" invariants).
5. That no deliverable proposes deleting tests.

Findings are fixed IN THIS PLAN before build dispatch.

---

## Files touched by this plan

Read-only measurement cycle. Only new files created:

- `/Users/okosisi/Code/universal-room-automation/docs/planning/PLANNING_test_strategy_rearchitecture.md` (this doc)
- `/Users/okosisi/Code/universal-room-automation/docs/planning/artifacts/test_strategy/baseline_158.txt` (D1 input)
- `/Users/okosisi/Code/universal-room-automation/docs/planning/artifacts/test_strategy/D1_triage.md`
- `/Users/okosisi/Code/universal-room-automation/docs/planning/artifacts/test_strategy/D2_pollution_map.md` + `D2_alone_runs/*.xml`
- `/Users/okosisi/Code/universal-room-automation/docs/planning/artifacts/test_strategy/D3_source_text_census.md`
- `/Users/okosisi/Code/universal-room-automation/docs/planning/artifacts/test_strategy/D4_hollow_anchor_sample.md`
- `/Users/okosisi/Code/universal-room-automation/docs/planning/artifacts/test_strategy/D5_wedge_diagnosis.md`
- `/Users/okosisi/Code/universal-room-automation/docs/planning/artifacts/test_strategy/D6_defensive_read_sweep.md`
- `/Users/okosisi/Code/universal-room-automation/docs/planning/artifacts/test_strategy/D7_leverage_ranking.md`

No production files, no test files, no config, no constants.
