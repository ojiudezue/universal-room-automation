---
name: ura-analysis-methodology
description: The URA discipline for turning a hunch into an accepted result — evidence bar, recipes, and the idea-lifecycle. Load this when you are about to (a) claim a root cause, (b) exonerate URA for a live symptom, (c) propose a fix, (d) design or review an experiment, (e) state an invariant a change must preserve, or (f) decide whether a passing test suite is actually authoritative for a change. Also load if you catch yourself writing "the fix is..." before you have (i) a mechanism that explains ALL observations including negatives, (ii) a numeric prediction, and (iii) a refutation attempt. Verified against repo 2026-07-02.
---

# URA Analysis Methodology

## Producer check before consumer check (operator-coined 2026-08-16)

Before claiming a root cause for a WRONG VALUE, audit its PRODUCER, not only its consumers:
(1) how many derivations exist and which wins (overwrite-order bugs are invisible downstream);
(2) what the producer depends on and whether each dependency is *currently healthy* — a
subtraction that uses a dead signal is not a defense; (3) plumbing vs arithmetic — "the right
inputs feed it" is not "it computes the right number"; (4) ground truth — compare to something
externally known, never to another internal number sharing the same assumptions.
Acceptance criteria must DISCRIMINATE the fix from a plausible different failure; if both
produce the same observation, pick a different one.
Worked case: the 2026-08-16 census double-count (additive path overwriting the subtractive one
with dedup defenses inert) — every investigation asked who read the count, none asked how it
was made.


## Memory first — MANDATORY entry point (operator-coined 2026-08-14)

Before mining the recorder, HA logs, or raw URA DB tables for ANY investigation or
trace: **query the hierarchical memory facade first.** The house has been journaling
adjudicated episodes since v5.47.0 (`memory_episodes`: exterior_track,
actuation_conflict, occupancy_phantom, fan_transition_suppressed, comfort_fan_vetoed
— 1,799 rows as of 2026-08-14) and the `universal_room_automation.memory_query`
service exposes `episodes` / `narrative` / `unusual` / `profile` / `facts` verbs per
node (room / zone / house / coordinator).

- Start: `memory_query` `narrative` for the affected node + window, then `episodes`
  filtered by type, then `unusual` for z-scored oddities.
- Raw recorder/DB mining is the **verify** step, not the entry point — memory
  narrows the window and names the mechanism candidates first.
- If memory has NO coverage for the question, say so explicitly in the
  investigation doc — each gap is a candidate episode-type writer (card it).

Why: investigations (e.g. AWAY-BLOCK-1 2026-08-13) hand-mined 4-hour recorder
traces while adjudicated episodes covering the same mechanisms sat unconsulted.


The discipline that turns a hunch into an accepted result in URA.
This skill is authoritative for **how you know** what you claim.
Change-control policy (tiers, review counts, deploy gates) lives in
`/CLAUDE.md` and is referenced — never re-stated — here.

## When to load this skill

Load BEFORE any of these actions:

| You are about to... | Load this skill because... |
|---|---|
| Claim a root cause for a live symptom | You need the evidence bar (Section 1) and the mechanism-must-explain-all-observations rule |
| Say "URA is fine, it's <X>" (exonerate URA) | Use Recipe B — you must find the untouched entity, not argue by analogy |
| Draft a planning doc's "Institutional context verified" section | Recipe F + the idea-lifecycle checklist |
| Run a Tier-2-DB or Tier-3 review | Recipes C (invariant falsification), D (mutation-anchored tests) |
| Trust a green pytest run before deploy | Section 5 evidence hierarchy — suite ≠ live |
| Trust reviewer summaries before deploy | Tier-3 orchestrator-verification (Section 4) — you re-verify personally |

## When NOT to use this skill

- **You are executing an already-classified cycle** — the tier is set,
  the plan is written, you are coding. Use `homeassistant_coding` and
  the cycle's planning doc, not this skill.
- **You are just deploying** — use `.claude/skills/deploy`.
- **You are drawing dashboards** — use `.claude/skills/ha-dashboard`.
- **You are chasing a "why won't my light turn on"** — start with
  `/CLAUDE.md` § Troubleshooting (silent-actuator runbook), then come
  back here if URA is still suspect after the untouched-entity check.

---

## 1. The evidence bar (non-negotiable)

A claim is not accepted in URA until it clears **all four**:

| # | Bar | Failure mode if skipped |
|---|---|---|
| E1 | **One mechanism explains ALL observations, including negatives** ("why did X *not* happen on boot #2"). | Two half-mechanisms hide a third failure. See Envoy incident — three failures compounded. |
| E2 | **The mechanism predicts numbers BEFORE the experiment** — a count, a timestamp offset, a row rate, a SOC value. | You retrofit the story to fit whatever the run produced. |
| E3 | **Adversarial refutation attempted** — you assign yourself the refuter role and try to break the claim from the whole reachable surface, not just the diff. | v5.5.3 D-HIGH-1: three reviewers said SHIP, the 4th (adversarial) found a 7th unclamped site. |
| E4 | **Every file:line / API / constant cited is verified in-session** — grep or read it, cite it. | See `/CLAUDE.md` § No Fabrication. Fabricated specs waste review defending impossible bugs. |

**Falsifiable-invariant rule.** If your claim is a promise ("the reserve
floor is never violated in any `partial_hold` path"), state it in a form
that could be broken by a *concrete legal-config repro* and try to break
it. If you cannot state the falsifiable form, the claim is not ready.

---

## 2. Six recipes (each with a worked repro from repo history)

### Recipe A — Discriminating-experiment design

Design experiments whose outcomes rule OUT candidate mechanisms, not
in. If two hypotheses predict the same result, the experiment is not
discriminating — re-design.

**Worked example: Envoy boot incident, 2026-06-12.**
Source of record: `docs/planning/PLANNING_ec_envoy_boot_decoupling.md`
§0 "Incident snapshot".

| Observation | Naive hypothesis | Discriminating check |
|---|---|---|
| Boot #1: all 40 URA entries `not_loaded`, zero URA errors in log | URA crashed silently | Silent crash would leave a partial log; log is empty → NOT URA. Search HA log for `"Setup timed out for stage 2"` → found → Failure A (`after_dependencies: enphase_envoy` stranding, `manifest.json:13-15`) |
| Boot #2 (clean): URA loaded but no EnergyCoordinator, all EC sub-switches `unavailable` | Same as A | A predicts *all* URA down; B predicts *only EC* down. Only EC down → distinct mechanism. Trace `__init__.py:1857` gate → `validate_envoy_config` (`domain_coordinators/energy_const.py:693-778`) ran 17s before Envoy entity appeared → Failure B (one-shot validation race) |
| Boot #3: EC loaded, but 6 intended-ON sub-switches silent-OFF | Options-flow regression | Options untouched. Read RestoreEntity code at `switch.py:617-648`: `target = last_state.state == "on"` — a persisted `unavailable` restores as False. Failure C. |

**Rule you take from this:** three symptoms with the same shape ("EC
broken") were three separate mechanisms. Assuming one mechanism would
have shipped a fix for A that left B and C live.

**Discriminating-experiment checklist.**

- [ ] For each candidate mechanism, write down the observation it
      *predicts to be absent* (the negative).
- [ ] Find one observation that only one candidate predicts. That is
      the discriminator.
- [ ] If no observation discriminates, design one (a targeted log
      scan, a single-entity toggle, a source mutation — see Recipe D).

### Recipe B — Exoneration analysis (check the untouched entity)

To exonerate URA for a live symptom, do **not** argue by analogy
("URA doesn't touch that"). Prove it by reading the state of the
entity URA is accused of touching, and showing that entity is
untouched or its owner is a different integration.

**Worked example: Study B thermostat oscillation, 2026-06-03.**
Source of record: MEMORY entry
`project_studyb_better_thermostat_oscillation`. Symptom: "Office B" /
Study B Carrier TRV cycled `heat_cool ↔ off` on a ~5-minute period.

Procedure that cleared URA:

1. Identify the exact entity that flapped (Carrier TRV climate
   entity).
2. Ask: which integration *owns* that entity? Answer: Better
   Thermostat (`climate.master_suite_zone_1`), not URA's zone climate.
3. Read URA's touch surface for that entity: search
   `domain_coordinators/hvac*.py` for the entity_id or its area. URA's
   zone entity is a *different* climate — untouched.
4. Look for a non-URA cause: a Better-Thermostat °F/°C "implausible
   temp" rejection re-armed a stale single-TRV BT config → mode
   oscillation.
5. Operator remedy: disabled the BT entry. Symptom gone.

**Exoneration checklist.**

- [ ] Name the exact `entity_id` that misbehaved.
- [ ] Verify its integration owner via `.storage/core.config_entries`
      or `ha_get_integration` (MCP). Not URA? Continue but keep URA
      in scope until step 4.
- [ ] Grep URA source for that entity_id / area — if zero hits,
      URA cannot have written to it directly.
- [ ] Cross-check history: `ha_get_history` for the entity across the
      window. If URA is upstream (e.g. via `climate.set_preset_mode`),
      you will see a URA-side sensor state change *precede* each flap.
      No precedence → not URA-driven.
- [ ] Only then say "URA exonerated" — with the four steps as
      evidence, not with analogy.

### Recipe C — Invariant falsification (Tier-3 pass D)

State the load-bearing invariant in a form a concrete repro can break,
then enumerate the WHOLE reachable surface — including pre-existing
code — and try to break it.

**Worked example: v5.5.3 arbitrage-WAIT reserve floor, D-HIGH-1.**
Source of record:
`docs/reviews/code-review/v5.5.3_arbwait_reviewD_completeness.md`,
`docs/QUALITY_CONTEXT.md` Bug Class #53 (line 2168,
"Computed-but-not-consumed control value").

- Invariant, falsifiable form: *"Under an inclement `partial_hold`,
  the battery can never drain/hold below the effective reserve floor
  in ANY off_peak or mid_peak path."*
- Load-bearing computation: `effective_reserve = max(self.reserve_soc,
  decision.reserve_floor)` at `energy_battery.py:2841`.
- Enumeration: grep every `reserve_level=` emission site in
  `domain_coordinators/energy_battery.py` (17 sites). For each,
  classify: consumes `effective_reserve`, provably unreachable, or
  leak.
- Result: the site at `energy_battery.py:2921` emits
  `hold_reserve = int(soc) if soc is not None else 100` with no
  clamp. Sibling branches at 2941 and 2956 clamp. This one branch
  does not. Leak found.
- Concrete legal-config repro (must be reachable via operator knobs
  that are independent): `target=30, floor=60, soc=45` → reserve
  emitted = 45, which is 15 below the floor. Legal because the two
  sliders are independent.

**Invariant-falsification checklist.**

- [ ] Write the invariant as a single sentence starting "In ANY
      path..." or "Under X, Y never...". If it starts "usually" or
      "the intent is", rewrite.
- [ ] Enumerate ALL emission/decision sites of the load-bearing
      value, not just those touched by the diff. Pre-existing code is
      in scope.
- [ ] For each site, produce a one-line justification: consumes,
      unreachable, or leak.
- [ ] For each leak, produce a concrete legal-config repro (values
      + state) reachable via the operator's actual knobs.
- [ ] If the operator sliders are independent, exercise their
      inversions and extremes (e.g. `floor > target`).

### Recipe D — Mutation-anchored test authority

A green test suite is authoritative for a load-bearing site ONLY if
a targeted mutation AT THAT SITE makes a *specific* test fail.
Aggregate monkeypatch proves the helper is load-bearing "somewhere";
it does not prove each site routes through it.

Procedure:

1. Identify the load-bearing site (file:line).
2. Edit production source to bypass or neuter that one site (e.g.
   replace `reserve_level=effective_reserve` with
   `reserve_level=int(soc)`).
3. Run the suite:
   ```bash
   PYTHONPATH=quality python3 -m pytest quality/tests/ -v
   ```
4. Expected: a specific test fails, and its name identifies the
   invariant it protects. Note it.
5. Restore the source.
6. If the suite stayed green under the mutation, the site is
   **untested**. That is unacceptable for a load-bearing site;
   add a test that fails under the mutation before shipping.

**Worked example.** In v5.5.3 the orchestrator re-ran a source
mutation on the load-bearing clamp site and confirmed `2 failed` —
that is the authority claim. A monkeypatch of the helper alone
would not have discriminated between "the helper is called somewhere"
and "the helper is called at THIS site".

### Recipe E — Baseline-diff isolation (pre-review tag)

Before applying ANY review fix-ups, tag the current head:
```bash
git tag pre-review-v<version> -m "Pre-review baseline for v<version>"
```
Then to isolate review-fix churn from the original build:
```bash
git diff pre-review-v<version>..HEAD -- custom_components/
```

Rules:

- Do **not** rebase or squash the pre-review tag away. It is the
  ledger for the fix-up phase.
- The validator (`.claude/agents/ura-validator.md` when present,
  else you) compares the current test-suite failure count against
  the count captured at the tag. A new failure that did not exist
  at the tag is a review-fix regression.
- Tag names are versioned so you can inspect them years later.

### Recipe F — Live-vs-suite evidence hierarchy

For any accepted result, rank the evidence by authority. Higher
authority wins ties.

| Rank | Evidence | Authority for... | Caveat |
|---|---|---|---|
| 1 | Live HA state read post-restart (MCP `ha_get_state`, `ha_get_history`, live-mounted `.storage`, live DB via `ura-sqlite`) | Runtime correctness, wiring, RestoreEntity restoration, actual DB row rates | Requires Samba mount healthy — see fallback below |
| 2 | Behavioral test driving production code paths through real-schema fixtures (`quality/tests/conftest_db`) | Persistence shape, migration correctness, cross-coordinator dispatch | Fixture must extract schema from production source, not hand-copy DDL |
| 3 | Unit test with hand-rolled MockHass (`quality/tests/conftest.py`) | Pure-function correctness, arithmetic, clamps | Cannot prove wiring, cannot prove RestoreEntity, cannot prove DB rows |
| 4 | Source-grep AST / static reasoning | Existence of a call site, obvious typos | Does NOT catch syntax errors that break import (see v4.7.4.3 → Pre-Deploy Zero-Bugs Gate) |
| 5 | Reviewer summary | Directional signal only | The orchestrator MUST re-verify load-bearing claims (Tier 3, `/CLAUDE.md`). |

**Sentinels-only = payload shape broken.** If a live DB check shows
only sentinel rows within an hour of restart, the write path is
broken even though the suite is green. This is the v4.6.1.1 /
v4.6.3-initial-build shape from `/CLAUDE.md` § Tier 2-DB Live
Validation.

---

## 3. Live-access commands

Fact-home: `ura-diagnostics-and-tooling` § Live-access commands + Samba
mount. MCP tool inventory (`ha_get_state`, `ha_get_logs`,
`ha_get_integration`, `ura-sqlite`), the live DB path, and the exact
`mount_smbfs` remount command live there — do not duplicate here.

Test-suite invocation lives in `ura-validation-and-qa` §1.

Before acting on any MCP diagnosis of "missing table" / schema
weirdness, cross-check against live HA (per `/CLAUDE.md`). A stale
cache diagnosis has caused wrong root-cause claims before.

---

## 4. Tier-3 self-execution (lone session, no agent fleet)

The Tier-3 four-pass protocol (A local correctness / B state-machine /
C mutation-anchored tests / D adversarial completeness), the framing
discipline, and the mandatory orchestrator self-verification before
deploy are all defined in `ura-change-control` §Tier 3 — see there for
the pass table and deliverable file naming.

Methodology framing (owned here): Pass D applies Recipe C (invariant
falsification) and Pass C applies Recipe D (mutation-anchored test
authority) below. If you find yourself repeating a Pass-A finding in
Pass-D, Pass-D is not doing its job. If the orchestrator's re-grep +
source mutation do not both hold, do not deploy.

---

## 5. Idea lifecycle — observation to bug-class extraction

| Stage | Artifact | Rule |
|---|---|---|
| Observation | MEMORY entry OR `.vibememo/` capture | Date-stamp. Cite the live evidence (entity, log line, DB row). |
| Backlog | `docs/BACKLOG.md` line, or a `project_*_backlog.md` memory file | State the *observed* effect, not the guessed cause. |
| Planning doc | `docs/planning/PLANNING_<cycle>.md` | Must include the mandatory `Institutional context verified` section (`/CLAUDE.md`). Must state acceptance criteria per deliverable (Verify / Sensor / Test / Live). For Tier-3, must state the falsifiable invariant up front. |
| Build | Cycle branch | Follow the tier from the plan. |
| Pre-review tag | `git tag pre-review-v<version>` | Recipe E. |
| Review | `docs/reviews/code-review/v<ver>_<name>_review<A-D>_<framing>.md` | One file per pass. Bug-class label per finding. |
| Deploy | `scripts/deploy.sh <version> <summary> <notes>` | See `.claude/skills/deploy`. `README_v<version>.md` pre-written; live-validation table written BACK afterward (`/CLAUDE.md`). |
| Live validation | Post-restart MCP checks, results table appended to the README | Sentinels-only = shape broken (Recipe F). |
| Bug-class extraction | Append to `docs/QUALITY_CONTEXT.md` | Add a new `### Bug Class #<N>` block if the finding does not fit an existing class. Update the stale header count (52 entries present as of 2026-07-02, highest number #53; header at `QUALITY_CONTEXT.md:7` still says "51 documented"). Catalog fact-home: `ura-failure-archaeology`. |

**Where good ideas historically came from (raw material for new
cycles).**

- **Operator observation of the running house** — sleep→wake deadlock
  (v4.7.18.1), mmWave fan-noise saga, "AC is on when we're away"
  (v4.7.14 away veto). The house tells you what to fix before the
  suite does.
- **Review passes** — Tier-3 pass D routinely surfaces latent
  pre-existing defects (v5.5.3 D-HIGH-1 was a v5.5.0 leak the build
  did not create).
- **Incident forensics** — Envoy 2026-06-12 produced three fixes AND
  Bug Class #52 (RestoreEntity unavailable-coercion); optimizer
  write-flood 2026-06-09 produced batching + boot-transient
  suppression AND the pre-deploy write-volume test.

---

## 6. Anti-patterns (self-check before you submit an analysis)

- [ ] I named a root cause without a numeric prediction. **Reject.**
- [ ] My mechanism explains the positives but I have not stated the
      negatives it predicts. **Reject.**
- [ ] I said "URA is fine" from analogy, without reading the accused
      entity's owner and history. **Reject** (see Recipe B).
- [ ] I cited a file:line I did not open in this session. **Reject**
      (see `/CLAUDE.md` § No Fabrication).
- [ ] I ran the test suite green and called the change proven.
      **Reject** — did the mutation at the load-bearing site fail a
      specific test (Recipe D)?
- [ ] My invariant statement contains "usually" or "the intent is".
      **Rewrite** into "In ANY path..." (Recipe C).
- [ ] I enumerated only the diff hunks, not the whole reachable
      surface. **Re-enumerate** (Recipe C).
- [ ] I trusted a reviewer summary for a load-bearing claim without
      re-verifying. **Re-verify** (Section 4).

---

## Provenance and maintenance

Re-verify these facts periodically; the repo moves fast.

| Claim | Re-verify with |
|---|---|
| Bug Class #53 exists at line 2168 | `grep -n "^### Bug Class #53" docs/QUALITY_CONTEXT.md` |
| Bug Class count (52 entries as of 2026-07-02; highest number in body #53; header QUALITY_CONTEXT.md:7 says "51 documented" — stale) | `grep -c '^### Bug Class #' docs/QUALITY_CONTEXT.md`. Catalog fact-home: `ura-failure-archaeology`. |
| v5.5.3 D-HIGH-1 details | `docs/reviews/code-review/v5.5.3_arbwait_reviewD_completeness.md` |
| Envoy boot incident three failures | `docs/planning/PLANNING_ec_envoy_boot_decoupling.md` §0 |
| Study B exoneration | MEMORY key `project_studyb_better_thermostat_oscillation` |
| Single-writer DB queue | `custom_components/universal_room_automation/database.py:45-51` (`self._write_queue: asyncio.Queue`) |
| Test invocation | `PYTHONPATH=quality python3 -m pytest quality/tests/ -v` (`/CLAUDE.md` § Testing) |
| Samba live mount path | `/CLAUDE.md` § Data Source Verification (copy verbatim) |
| Tier 3 four-pass protocol | `/CLAUDE.md` § Tier 3 |

If any of these drift, update this file and note the drift date in
the frontmatter description.

Sibling skills — cross-reference, do not duplicate:

- `.claude/skills/deploy` — deploy pipeline (README write-back,
  tag, PR, release).
- `.claude/skills/documenter` — post-cycle docs and diagrams.
- `.claude/skills/homeassistant_coding` — HA idioms, integration
  patterns.
- `.claude/skills/vibememo` / `vibememo-eval` — decision capture.
- `.claude/skills/transition-doc` — end-of-planning transition notes.
