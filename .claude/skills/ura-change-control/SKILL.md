---
name: ura-change-control
description: Executable runbook for URA change control — tier classification (1 / 2 / 2-DB / 3), pre-review baseline tag, sequential framing-disjoint reviews performed solo, fix-up discipline, Pre-Deploy Zero-Bugs Gate, README-before-deploy + write-back-after, and plan-completion accounting. LOAD THIS SKILL when about to plan, review, fix-up, deploy, or classify the scope of ANY change to `custom_components/universal_room_automation/` — including hotfixes, feature cycles, DB-schema-adjacent changes, trust-hierarchy or shared-primitive touches, or anything the operator flags as "delicate" / "regression-prone". Also load when asked "what tier is this" or "how do I review this cycle" or before running `scripts/deploy.sh`. If the task is pure release orchestration (test → README → deploy.sh → HACS → restart → verify) with tier already decided and reviews already done, see the sibling `deploy` skill instead.
---

# URA Change Control — Executable Runbook

CLAUDE.md (project root) is CANONICAL POLICY. This skill is the executable
expansion for a lone Sonnet-class session with **no subagent fleet** — you
run each review yourself, sequentially, with disjoint framings. Whenever
this document and CLAUDE.md disagree, CLAUDE.md wins; edit this skill to
match, do not route around CLAUDE.md.

Audience: one engineer + one model. Fleet usage (`ura-planner` /
`ura-builder` / `ura-reviewer` / `ura-validator` agents) is an optional
accelerator, not a prerequisite. Every step here works solo.

## When NOT to use this skill

| Situation | Use instead |
|---|---|
| Pure release mechanics (stamp → commit → PR → HACS → restart) with tier already decided and reviews already done | `deploy` skill |
| Dashboard YAML / Lovelace card work only | `ha-dashboard` skill |
| Writing HA-native code (config flow, entities, coordinators) with no cycle decision to make | `homeassistant_coding` skill |
| Capturing a load-bearing decision for the trail | `vibememo` skill |
| Doc/architecture refresh after a shipped cycle | `documenter` skill |
| End-of-planning-conversation handoff so the NEXT session doesn't repeat mistakes | `transition-doc` skill |

If you are inside a live cycle (planning → build → review → fix → deploy → validate), stay in this skill; it will hand off to `deploy` at the right moment.

---

## 1. Tier classification — decide FIRST, before touching code

Classify BEFORE build starts. Record the tier in the planning doc. When in doubt, elevate one tier; over-review is cheap, silent regressions are not.

### Decision table

| Signal in the change | Tier | Reviews required |
|---|---|---|
| 1–3 files, single bug, no new features, no cross-coordinator ripple | **Tier 1 (Hotfix)** | 1 |
| New capability, multiple files, new sensors/entities, no DB or shared-primitive touch | **Tier 2 (Feature)** | 2 + live validation |
| Touches `database.py` DAOs, migrates ≥3 callers to a new DAO, changes payload shape of a dispatched event / persisted row, adds behavioral tests against real schema, or precedes a planned schema migration | **Tier 2-DB** | 3 framing-disjoint + live validation |
| Trust-hierarchy / cross-coordinator ripple (presence ↔ HVAC ↔ compliance ↔ safety; battery ↔ grid ↔ cost ↔ EVSE); strategy/decision-logic change; change to a shared primitive consumed by many sites; fix to long-standing logic other code has come to depend on | **Tier 2-DB (standing policy)** | 3 framing-disjoint + live validation |
| Threads a value (reserve floor, clamp, gate, precedence) through a state machine or shared primitive where failure mode = ONE missed emission site; cost-AND-safety-impacting (battery reserve, load-shed, HVAC safety); operator flags "delicate"; area has multi-fix-up history | **Tier 3** | 4 framing-disjoint incl. adversarial-completeness pass D with real source-mutation testing |
| Operator explicitly elevates ("run Tier 2-DB on this") | as-stated | as-stated |

**Identity / fusion / cameras:** any change touching `camera_census.py` / `camera_resolver.py` / `transit_validator.py` / face recognition / `person_id` on `person_entry_exit_events` is regression-prone (identity → guest → HVAC/security trust ripple). Elevate per Tier 2-DB; consult `docs/Coordinator/IDENTITY_FUSION_CAMERAS_MANUAL.md`.

**Standing policy (2026-06-08):** the "DB" in Tier 2-DB is historical. What the protocol buys is three disjoint framings so blind spots cannot converge. Default to elevating regression-prone work; the only work that stays Tier 1 / Tier 2 is pure docs, isolated additive sensors, or hotfixes with no ripple.

**Historical incidents that mint each rule:**

| Rule | Incident |
|---|---|
| Pre-Deploy Zero-Bugs Gate | **v4.7.4.3 (2026-05-29)**: broken release shipped because source-grep AST tests missed a syntax error that `py_compile` would have caught. Coined the gate. |
| Tier 2-DB (3 framings) | **v4.6.3 (2026-05-14)**: first review returned "SHIP"; a second reviewer under a different framing surfaced 6 CRITICALs. Operator: *"We will need 3x staff end reviews that are targeted at diff risks."* |
| Tier 3 (4th adversarial-completeness reviewer) | **v5.5.3 arbitrage-WAIT (2026-06-16)**: three framing-disjoint reviews (A/B/C) all returned SHIP; a dedicated 4th reviewer D found **D-HIGH-1** — a 7th unclamped reserve-emission site (a latent v5.5.0 gap) missed by build, plan, and reviewers A/B/C. Operator: *"This is very delicate. It needs a lot of review. Proceed carefully."* |

---

## 2. Institutional Context First — MANDATORY before planning

Every planning doc MUST include an "Institutional context verified" section BEFORE deliverables. Reviewers verify this. Skip it and you will propose duplicate work — three planners caught ~14 institutional errors in a single 2026-05-30 sitting by following this rule.

For every proposed `CONF_*`, sensor, helper, constant, signal, or config-flow field, output either:

- `REUSED <name> at <file>:<line>` (with grep evidence), OR
- `NEW because no equivalent found after grep of <surfaces>` (with brief justification).

Prior-art surfaces to grep, in order:

1. `custom_components/universal_room_automation/const.py`
2. `custom_components/universal_room_automation/config_flow.py` + `options_flow.py`
3. `sensor.py`, `binary_sensor.py`, `number.py`, `switch.py`, `select.py`, `button.py`
4. `custom_components/universal_room_automation/domain_coordinators/*.py`
5. `docs/Coordinator/<NAME>.md` for the affected coordinator
6. `docs/planning/` — skim filenames + headers, pull bodies for related cycles
7. Memory bodies for related backlog / live / shipped memos (not just `MEMORY.md` index lines)

When the operator says "we have X", treat it as a verification task, not a claim to react to. If you cannot find X, tell them exactly what you searched.

---

## 3. Planning doc — testable acceptance criteria are mandatory

Every deliverable needs:

```markdown
## D1: <name>
<description>

### Acceptance Criteria
- **Verify:** <observable behavior>
- **Sensor:** <entity_id> shows <expected state/attr>
- **Test:** <test function names>
- **Live:** <what to check on running HA post-deploy>
```

The **Live** bullets feed directly into the post-deploy README write-back (§8). Without them, validation has nothing to check.

**Tier 3 additional requirement:** state the falsifiable invariant up front. "Under X, Y can never happen in ANY reachable path." Reviewer D's job is to falsify exactly this string.

---

## 4. Pre-review baseline tag — MANDATORY before fix-ups

Tag the post-build, pre-review state so review fix-ups are diffable:

```bash
git tag pre-review-v<version> -m "Pre-review baseline for v<version>"
```

After all reviews and fix-ups:

```bash
git diff pre-review-v<version>..HEAD              # everything the reviews changed
git diff pre-review-v<version>..HEAD -- <path>    # per-file
```

If a fix-up introduces a regression, this diff is how you isolate it.

Canonical spec: `CLAUDE.md:132-136`.

---

## 5. Framing-disjoint reviews performed SOLO

Do each pass in a **separate turn / fresh context** where possible. If you cannot reset context, at least start each review by re-stating the framing verbatim and IGNORING previous reviews' findings until you have written your own. Overlapping framings converge on the same blind spots (that is the whole reason 2 reviews were not enough in v4.6.3).

### Tier 1 — one review

One adversarial pass against `docs/QUALITY_CONTEXT.md` bug classes. The count in that file's header has drifted before — count `### Bug Class` headings before quoting a number (last-checked highest = **Bug Class #53 — Computed-but-not-consumed control value** at `docs/QUALITY_CONTEXT.md:2168`, 2026-07-02). Focus: the specific fix, its blast radius, edge cases. Fix CRITICAL/HIGH, re-run tests, deploy.

### Tier 2 — two reviews

| Review | Framing | Looks for |
|---|---|---|
| A (Core) | Domain logic vs QUALITY_CONTEXT.md bug classes | correctness, edge cases, None handling, security, HA patterns, error propagation, missing channels/params in codepaths |
| B (Independent) | Runtime / lifecycle | race conditions, restart resilience, DB transaction safety, cross-coordinator interactions, HA lifecycle patterns, timer/listener cleanup |

Then live validation (§8) counts as review 3.

### Tier 2-DB — three framings (do NOT let them overlap)

DB-shape cycles:

| Review | Framing | Looks for |
|---|---|---|
| A | Data integrity + DB architecture preservation | existing rows preserved, no schema regression, single-writer queue unchanged (`database.py:49` `_write_queue`), indexes still cover, existing readers unaffected, existing analytics queries return the same shape post-deploy |
| B | Migration correctness + signal chain integrity | every migrated call site produces equivalent rows AND fires downstream signals/dispatches AND no double-emit risk; end-to-end trace per site; field-by-field shape comparison vs the pre-migration emit |
| C | New surfaces + test-fixture authority | new sensors/buttons/config knobs round-trip through options flow + RestoreEntity; behavioral test fixtures **extract schema from production source, never hand-copy DDL**; tests drive production code paths, not their own INSERT/UPDATE/DELETE |

Strategy/decision-logic Tier 2-DB (not DB shape) — a canonical framing set:

- A = correctness + edge cases
- B = cross-coordinator + precedence + no-flap
- C = test authority + day/cycle-boundary

The **invariant** is three disjoint framings + live validation + README write-back, not the specific axis names. Pick framings that fit the change.

Then live validation D (§8).

**Pre-deploy snapshot** for any DB-shape cycle: capture row rates on the affected table(s) by `(coordinator, severity, type)` (or analogous shape). Without this, post-deploy ±25% comparison is impossible.

### Tier 3 — four framings, one MUST be adversarial completeness (D)

| Review | Framing | Looks for |
|---|---|---|
| A | Local correctness | arithmetic/clamp/helper logic, per-site |
| B | Integration / state-machine integrity | no suppression of the legitimate action, no pre-existing-invariant regression, byte-identical on the no-op path, restart |
| C | Test authority via REAL per-site source mutation | Edit production source to bypass/neuter ONE load-bearing site at a time, run the suite, confirm a SPECIFIC test fails, restore. A site whose bypass leaves the suite green is untested = unacceptable. Global monkeypatch proves aggregate load-bearing; it does NOT prove per-site routing. |
| D | Adversarial completeness / diff-blind | State the load-bearing invariant in falsifiable form, then BREAK it. Re-enumerate the ENTIRE invariant surface — including **pre-existing code, not just the diff** (D-HIGH-1 predated the cycle). Every flagged leak requires a concrete legal-config reachable repro (values + state that trigger it). |

**Config-boundary / combinatorial testing:** when ≥2 independent operator knobs interact, test at their EXTREMES and inversions (e.g. `floor > target`), not just happy-path defaults. Independent sliders create legal combinations the happy path never exercises — that is where v5.5.3's leak hid.

**Orchestrator independent verification before ship — do not trust reviewer summaries.** Re-grep every emission/decision site yourself; re-run a real source mutation on the load-bearing site(s). In v5.5.3 this caught that a verification regex missed a multi-line clamp; the re-run confirmed `2 failed` on mutation.

**Operator checkpoint BEFORE deploy** on Tier 3. Surface the final review outcome + the invariant proof and get explicit go.

If D (or any pass) finds a CRITICAL/HIGH: fix, re-verify the fixed site with its own mutation-anchored test, AND re-run D's completeness enumeration (a fix can reveal an N+1th site). Do not ship until D's invariant holds across the whole surface.

### Review doc filing

Write each review to `docs/reviews/code-review/v<version>_<name>_review<A|B|C|D>_<framing>.md`. Canonical Tier 3 set to model after: `docs/reviews/code-review/v5.5.3_arbwait_review{A,B,C,D}_*.md`. After ship, add `v<version>_<name>_summary.md` with bugs found/fixed/deferred, bug-class frequency, and any new bug classes to file into `docs/QUALITY_CONTEXT.md`.

---

## 6. Fix-up discipline

- Fix ALL CRITICAL and HIGH findings from any review before deploy.
- **Fix LOWs in-cycle when they are 1–30 LoC** (operator-coined 2026-06-02). Stop omnibus-deferring LOWs to the next version. Only defer genuine non-issues. Cap the deferral doc at ~6 entries.
- Re-run tests after every fix pass.
- If fix-up was substantial, spot-check the changed surfaces or run a focused fourth review pass on those surfaces.
- All fix commits ride on top of `pre-review-v<version>` — the tag never moves.

---

## 7. Pre-Deploy Zero-Bugs Gate — MANDATORY

Coined after v4.7.4.3 shipped broken because AST-based source-grep tests missed a syntax error. Run every item, in order, before invoking `scripts/deploy.sh`. Failure of ANY item aborts the deploy.

```bash
cd /Users/okosisi/Code/universal-room-automation

# 1. No unresolved merge / rebase / cherry-pick conflict markers anywhere.
!  grep -RIn --exclude-dir=.git --exclude-dir=graphify-out \
     -E '^(<<<<<<< |=======$|>>>>>>> )' custom_components/ quality/tests/ \
   || (echo "CONFLICT MARKERS FOUND — abort" && false)

# 2. Every changed .py compiles (catches syntax errors AST-tests miss).
CHANGED_PY=$(git diff --name-only --diff-filter=ACMR HEAD~1 -- '*.py')
[ -z "$CHANGED_PY" ] || python3 -m py_compile $CHANGED_PY

# 3. Full cycle test suite passes.
PYTHONPATH=quality python3 -m pytest quality/tests/ -v

# 4. Baseline-diff — no NEW failures vs pre-review-v<version>.
#    (ura-validator agent automates this when the fleet is available;
#     solo version below.)
git stash push -u -m gate-baseline
PYTHONPATH=quality python3 -m pytest quality/tests/ 2>&1 \
  | grep -E '^FAILED' | sort > /tmp/head.failed
git checkout pre-review-v<version>
PYTHONPATH=quality python3 -m pytest quality/tests/ 2>&1 \
  | grep -E '^FAILED' | sort > /tmp/baseline.failed
git checkout -
git stash pop
comm -13 /tmp/baseline.failed /tmp/head.failed   # tests that fail ONLY at HEAD
# Empty output = pass. Any line = NEW regression = abort and fix.
```

Do NOT skip step 2 because "the tests pass" — the tests are largely source-greps and static AST scans; they do not import every module and will happily co-exist with a `SyntaxError` in a runtime path. `py_compile` catches it.

---

## 8. README-before-deploy + validation-write-back-after

### Before deploy

Create `docs/readmes/README_v<version>.md` BEFORE running `scripts/deploy.sh`. Pre-stage any new directories referenced by the README with `git add`. The deploy script's stage step (`scripts/deploy.sh` step 2) only globs known paths — new dirs that are not staged upstream are silently dropped.

Include a **prospective** "Live Validation" section listing the acceptance criteria from the planning doc's `Live:` bullets.

### Deploy

Hand off to the `deploy` skill — it wraps `./scripts/deploy.sh <version> "<summary>" "<notes>"` with test / config-check / HACS / restart / post-restart verification.

### After live validation — MANDATORY write-back

Operator-coined 2026-06-05. A cycle is NOT closed until the README carries the post-restart validation table. Format (verified in `docs/readmes/README_v5.7.2.md:66`): `## Live Validation — Validated <YYYY-MM-DD> (post-restart)`.

Replace the prospective bullet list with a `Validated <date>` **results table** — one row per acceptance criterion, marked PASS / FAIL / as-expected, with concrete observed evidence:

- Live entity_id + attribute value (from MCP `home-assistant` `ha_get_state`).
- Log scan result (from MCP `home-assistant` `ha_get_logs` — cite scan window).
- DB row read (from MCP `ura-sqlite` — verify `--db-path` in `~/.claude.json` points to the LIVE Samba-mounted path `/Users/ojiudezue/ha-config/universal_room_automation/data/universal_room_automation.db`, not `~/.cache/ura/`; see CLAUDE.md "Data Source Verification").

Note any criterion that could only be proven in-suite (and why), and any boot-only transients you saw and dismissed. The README git history IS the validation ledger; future cycles must not have to re-litigate whether the feature shipped working.

**Live-access fallback when the Samba mount or MCP is down:** exact `mount_smbfs` command, live DB path, and read-only websocket fallback are in `ura-diagnostics-and-tooling` § Live-access commands (fact-home). Do NOT proceed with claims about "the running house" using stale cache paths — silent staleness is worse than "I don't know yet."

**No soak watching.** Never propose "monitor for 24h" / "soak overnight" as a post-deploy step. Cycles close at live-validation. Regression trip-wires belong in code (anomaly detection wired to Notification Manager), not calendar reminders.

---

## 9. Plan-completion accounting — MANDATORY

At the end of every cycle, explicitly document what was NOT done from the plan:

- Each planned item skipped or deferred (by ID).
- WHY (time, complexity, dependency, explicit decision).
- WHERE it is tracked for future work (backlog memo, follow-up planning doc, `docs/TECH_DEBT.md`).

Do NOT silently drop planned items. Even "decided not to build" is an accounting entry, not silence.

---

## 10. Post-review documentation

For every cycle, persist:

- `docs/reviews/code-review/v<version>_<name>_review<A|B|C|D>_<framing>.md` — one per review.
- `docs/reviews/code-review/v<version>_<name>_summary.md` — bugs found/fixed/deferred by severity, bug-class frequency table, recommendations for new bug classes.

After writing the summary, check whether any new bug classes should be added to `docs/QUALITY_CONTEXT.md`. When you add a new class, count the `### Bug Class` headings in that file and update any stale header count.

---

## 11. End-to-end cycle checklist

```
[ ] Tier classified in planning doc (§1) — elevated if regression-prone
[ ] Institutional context verified section written (§2)
[ ] Deliverables have Verify / Sensor / Test / Live acceptance criteria (§3)
[ ] Tier 3 only: falsifiable invariant stated up front (§3)
[ ] Build lands on feature branch; `git log` verified from main checkout
[ ] Full test suite green: PYTHONPATH=quality python3 -m pytest quality/tests/ -v
[ ] git tag pre-review-v<version> created (§4)
[ ] Reviews run SEQUENTIALLY with disjoint framings, one file per review (§5)
[ ] Tier 3 only: reviewer C ran real per-site source mutations (§5)
[ ] Tier 3 only: orchestrator independently re-greps + re-runs mutation (§5)
[ ] All CRITICAL + HIGH fixed; LOWs 1–30 LoC also fixed in-cycle (§6)
[ ] Tests re-run green after last fix
[ ] README_v<version>.md exists with prospective Live acceptance (§8)
[ ] Pre-Deploy Zero-Bugs Gate all four steps PASS (§7)
[ ] Tier 3 only: operator checkpoint received (§5)
[ ] Handoff to `deploy` skill
[ ] Post-restart: README Live Validation table written with observed evidence (§8)
[ ] Plan-completion accounting filed (§9)
[ ] Review summary + bug-class updates filed (§10)
```

---

## Provenance and maintenance

Re-verify these facts if they may have drifted (last checked 2026-07-02, URA v5.7.2):

| Claim | Verify with |
|---|---|
| Tier table + Tier 3 protocol wording | `grep -n "Tier " /Users/okosisi/Code/universal-room-automation/CLAUDE.md` |
| Pre-review baseline command | `grep -n "pre-review-v" /Users/okosisi/Code/universal-room-automation/CLAUDE.md` |
| `_write_queue` at `database.py:49` | `grep -n "_write_queue" /Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/database.py` |
| Highest bug class (last shown #53 at line 2168) | `grep -n "^### Bug Class" /Users/okosisi/Code/universal-room-automation/docs/QUALITY_CONTEXT.md | tail -3` |
| README live-validation format | Read `docs/readmes/README_v5.7.2.md` §"Live Validation" |
| Deploy script staging paths | `sed -n '55,70p' /Users/okosisi/Code/universal-room-automation/scripts/deploy.sh` |
| Sibling skills unchanged (`deploy`, `homeassistant_coding`, `ha-dashboard`, `documenter`, `vibememo`) | `ls /Users/okosisi/Code/universal-room-automation/.claude/skills/` |
| Samba mount path + remount command | `grep -A2 "Data Source Verification" /Users/okosisi/Code/universal-room-automation/CLAUDE.md` |

If CLAUDE.md changes any rule this skill mirrors, update this skill in the same commit — never let the two drift.
