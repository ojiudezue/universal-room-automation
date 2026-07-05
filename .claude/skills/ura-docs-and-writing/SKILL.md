---
name: ura-docs-and-writing
description: House rules for URA's docs of record — planning docs (with mandatory Institutional-context-verified section + acceptance criteria), code-review docs, README_v<version>.md release notes + post-restart validation write-back, QUALITY_CONTEXT.md bug-class extraction, docs/Coordinator/ upkeep, BACKLOG.md/TECH_DEBT.md conventions, vibememo cross-references. LOAD BEFORE writing/editing anything under docs/, or when producing a review/plan/release-notes doc. Complements `deploy` (release execution) and `vibememo` (decision trail).
---

# URA docs & writing runbook

You are writing paperwork that a solo operator and future Claude sessions will trust as ground truth. The rules below are enforced by process, not CI. If you skip them, review-work regresses to guesswork.

**Authoritative policy:** `CLAUDE.md` (project root). This skill makes CLAUDE.md executable — it does NOT override it. If this skill and CLAUDE.md disagree, CLAUDE.md wins; fix this skill.

**When NOT to use this skill:**
- Executing a release → `/deploy` skill (`./scripts/deploy.sh <version> <summary> <notes>`). This skill only tells you how to write the README that deploy consumes.
- Capturing a decision trail → `/vibememo` skill. Cross-reference vibememo IDs from planning/README docs; do not duplicate their bodies.
- HA YAML/dashboard authoring → `homeassistant_coding`, `ha-dashboard`.
- Handing off a planning conversation → `transition-doc`.
- Architecture diagrams / feature-done maintenance → `documenter`.

---

## 0. House style — non-negotiable

| Rule | What it means | Anti-pattern |
|---|---|---|
| Terse | Say it once, in the fewest words. Prefer tables over prose. | Multi-paragraph exposition of what a table already shows. |
| Evidence-cited | Every load-bearing claim carries `file:line`, entity_id + attribute value, log excerpt, or DB row. | "The presence code correctly handles X." (no citation) |
| No oversell | State observed behavior, not marketing. `PASS` needs evidence; "should work" is not a claim. | "Ships a rock-solid, best-in-class inclement-weather hold." |
| Date-stamped | Any volatile fact carries `YYYY-MM-DD`. Include a "Provenance and maintenance" footer on longer docs. | "Recently we added…" (when? "recently" rots.) |
| No fabrication | If you cannot cite it this session, mark it `unverified` or say "I'd be guessing." See CLAUDE.md § No Fabrication. | Claiming an HA API shape or library behavior from a plausible mental model. |
| REUSED vs NEW | Every new constant, sensor, helper, field, signal is either REUSED (with `file:line`) or NEW (with justification). See CLAUDE.md § Institutional Context First. | Silently proposing `CONF_FOO` that duplicates an existing knob. |

Sentence-level checklist:
- "As of `YYYY-MM-DD`" or "Validated `YYYY-MM-DD`" on live claims.
- Cite `path/to/file.py:LINE` for code claims. Ranges (`:1400-1535`) are fine.
- Cite `entity_id` + attribute + value for live claims (e.g. `sensor.av_closet_unavailable_entities.actuator_count = 1`).
- Use fenced code blocks for exact log lines, service payloads, YAML fragments.

---

## 1. Where does this doc go?

The `docs/` tree has real sprawl (verified 2026-07-02). Do not add to it. Put new docs in the right directory:

| Doc kind | Correct path | Notes |
|---|---|---|
| Planning doc (upcoming cycle) | `docs/planning/PLANNING_<slug>.md` or `PLANNING_v<version>_<slug>.md` | Recent convention: `PLANNING_<topic>.md`. Version-in-filename is fine but not required. |
| Code review (per framing) | `docs/reviews/code-review/v<ver>_<name>_review<A-D>_<framing>.md` | See §3 for naming rules. |
| Release notes / cycle README | `docs/readmes/README_v<version>.md` | Written BEFORE deploy. Live-validation table written back AFTER restart. |
| Coordinator design doc | `docs/Coordinator/<NAME>_COORDINATOR_DESIGN.md` (or `<NAME>_COORDINATOR.md`) | Update when scope of that coordinator materially shifts. Do NOT create a copy — see sprawl warning below. |
| Bug class catalog | Append to `docs/QUALITY_CONTEXT.md` § Bug Classes | See §5 for the trigger. |
| Backlog item | `docs/BACKLOG.md` with a `## <slug> — YYYY-MM-DD` header | Include tier hint + trigger. |
| Long-lived shortcut | `docs/TECH_DEBT.md` (Where / Shortcut / Why acceptable / Trigger to revisit). | Update in place when resolved — do not delete history. |
| Transient session-transfer | `docs/planning/PLANNING_<topic>_TRANSITION_NOTES.md` or use `/transition-doc`. | Do not scatter loose notes at `docs/` root. |
| Decision trail (durable) | `/vibememo` → `.vibememo/…`. Cross-reference by ID from planning docs. | Do not paste decision-trail bodies into planning docs. |

Known sprawl to route around (do not extend):
- `docs/Coordinator/PRESENCE_COORDINATOR 2.md`, `SAFETY_COORDINATOR 2.md`, `SECURITY_COORDINATOR 2.md` — accidental Finder duplicates. Edit the non-` 2.md` version.
- `docs/ROADMAP_v9.md`, `ROADMAP_v10.md`, `ROADMAP_REMAINING.md` — superseded. Current roadmap is `docs/ROADMAP_v11.md` (per CLAUDE.md).
- v3-era `PLANNING_v3.*.md` docs at `docs/` root (before `docs/planning/` existed). New planning docs go under `docs/planning/`.
- `docs/Organizing URA.md`, `docs/CURRENT_STATE.md` — historical; do not update as if they are live.

---

## 2. Planning docs — mandatory shape

Every planning doc MUST have these two sections BEFORE any deliverable, in this order.

### 2.1 "Institutional context verified" — proof-of-work

Reviewers verify this section during Tier 1/2/2-DB/3 review. Planners who skip it produce plans that duplicate or conflict with existing infrastructure. Empirically validated 2026-05-30 (three planners caught ~14 institutional errors before build). See CLAUDE.md § Institutional Context First for the surfaces to grep.

Copy this exact skeleton (matches the shape used in `docs/planning/PLANNING_arbitrage_wait_inclement_floor.md`, verified 2026-07-02):

```markdown
## Institutional context verified

### Code locations read end-to-end during scoping
- `custom_components/universal_room_automation/<file>.py` — read `:<lo>-<hi>` (...what you took from this read...). Cite every range you're building on.

### Greps run + verdicts

| Surface searched | Pattern | Result | Verdict |
|---|---|---|---|
| `<file>.py` | `<regex>` | <N hits at file:line...> | REUSED at `file:line` / NEW because ... |

REUSED vs NEW summary: <one line per proposed CONF_*/sensor/helper/constant/signal — REUSED with citation, or NEW with why nothing equivalent exists>.

### Prior planning docs / memory bodies / design docs consulted
- `docs/planning/<file>.md` — <relevance: full-read / skim>.
- MEMORY entry `<slug>` — <one-line takeaway>.
- `docs/Coordinator/<NAME>.md` — <read / not applicable because...>.
```

If you cannot fill this in with citations, you have not done the scoping work. Do it before writing deliverables.

### 2.2 Tier classification (state it up front)

State the review tier explicitly with justification (from CLAUDE.md § Review Protocol):

- Tier 1 (Hotfix) — 1-3 files, single bug/issue, no new features, no cross-coordinator ripple.
- Tier 2 (Feature cycle) — new capability, multiple files, new sensors/entities.
- Tier 2-DB (regression-prone / DB-sensitive) — 3 framing-disjoint reviews. Standing policy 2026-06-08: default to Tier 2-DB for anything regression-prone (trust-hierarchy ripple, shared primitive, decision-logic in cost/comfort/safety). The "DB" name is historical.
- Tier 3 (delicate shared primitive / invariant-critical) — 4 reviews including an adversarial-completeness pass D with real per-site source mutation. Trigger: operator flags delicate, or the failure mode is "one missed emission site" (Bug Class #53), or cost-AND-safety impacting.

Tier 3 planning docs additionally MUST state a falsifiable invariant up front — the single property the cycle must guarantee (Reviewer D's job is to falsify exactly that one).

### 2.3 Deliverables with Acceptance Criteria — MANDATORY per CLAUDE.md

Every deliverable ends with a testable acceptance block. Copy this format exactly (matches CLAUDE.md § Planning Docs):

```markdown
## D1: <Deliverable Name>
<description>

### Acceptance Criteria
- Verify: <observable behavior that proves it works>
- Verify: <second observable behavior>
- Sensor: <entity_id> shows <expected value/state>
- Test: <test function names that cover this>
- Live: <what to check on the running HA instance post-deploy>
```

The Live bullets feed directly into the README write-back (§4.2). Without them, the validator does not know what to check.

Also required at the end of every planning doc:
- Plan completion tracking hook — a section titled `## What may be deferred` listing items the builder is allowed to defer, so silent drops become impossible. See CLAUDE.md § Plan Completion Tracking.

---

## 3. Code-review docs

### 3.1 Filename and location

`docs/reviews/code-review/v<version>_<slug>_review<A|B|C|D>_<framing>.md`

Verified 2026-07-02 against `ls docs/reviews/code-review/` — canonical examples:
- Tier 2: `boot_storm_review_A_correctness.md`, `boot_storm_review_B_lifecycle.md` (versionless slugs also seen — prefer versioned form for new work).
- Tier 2-DB (three framings, canonical DB axes A=data-integrity / B=migration / C=surfaces-tests): `v5.5.0_inclement_reviewA_detection_fusion.md`, `...reviewB_integration_precedence.md`, `...reviewC_config_test_authority.md`.
- Tier 3 (four framings): `v5.5.3_arbwait_reviewA_clamp.md`, `...reviewB_statemachine.md`, `...reviewC_tests.md`, `...reviewD_completeness.md`.

Framings must be disjoint — two reviewers on the same axis converge on the same blind spots. State your framing in the header so the operator can see coverage at a glance.

### 3.2 Header shape (copy verbatim)

```markdown
# Code Review — v<version> <cycle name> — Reviewer <A|B|C|D>

**Framing:** <one line stating exactly what this reviewer is responsible for — "correctness + edge cases", "migration + signal chain", "async + lifecycle + races", "adversarial completeness" — and what is OUT of lane>.
**Branch:** `<feature-branch>` (tip `<sha>`). Diff base: `<git diff ...>`.
**Reviewer scope:** <files this reviewer read end-to-end>. Out of lane: <what the other reviewers own>.
**Test state at review:** <pytest summary — e.g. "38/38 new inclement tests pass; suite baseline 35 failed">.
```

### 3.3 Body shape

Order matters — operators read top-down and act on the summary.

1. Summary statistics table — one row per severity, columns Found / Fixed / Deferred.

   ```markdown
   | Severity | Found | Fixed | Deferred |
   |---|---|---|---|
   | CRITICAL | 1 | 0 | 1 |
   | HIGH     | 1 | 0 | 1 |
   | MEDIUM   | 3 | 0 | 3 |
   | LOW      | 2 | 0 | 2 |
   ```

2. Verdict: one of `SHIP` / `FIX-THEN-SHIP` / `BLOCK`. One sentence stating why.

3. Findings, in order of severity. Each finding uses this shape:

   ```markdown
   ### <ID e.g. A-CRIT-1> — <one-line title>
   **Bug class:** <existing #N from QUALITY_CONTEXT.md, or "candidate new class: <name>">.
   **Files:** <path:line ranges>.

   **Reasoning / repro:** <what you actually verified. Reachability: state a concrete legal-config repro
   (the values + state that trigger it). Do not stop at "could happen" — show the path.>

   **Why tests didn't catch it:** <one line — critical for the QC ledger>.

   **Proposed fix:** <minimum diff shape; do not write the patch, describe the shape>.
   ```

4. Bug-class frequency table at the bottom — helps QUALITY_CONTEXT.md maintenance:

   ```markdown
   | Bug class | Count in this review |
   |---|---|
   | #53 Computed-but-not-consumed | 2 |
   | Candidate: <new name> | 1 |
   ```

5. Recommendations for QUALITY_CONTEXT.md — one bullet per candidate new bug class. See §5 for the trigger.

### 3.4 Adversarial-completeness pass D (Tier 3 only)

Reviewer D has a different mandate. Its header MUST include:

- Claim under test: the falsifiable invariant, verbatim from the planning doc.
- LEAD: `LEAK FOUND — YES/NO`. If YES, the finding must include a concrete legal-config reachable repro (values + state; e.g. "target=30, floor=60, soc=45 → reserve 45, 15 below floor — legal because sliders are independent").

D re-enumerates the ENTIRE invariant surface — including pre-existing code, not just the diff. In v5.5.3, D-HIGH-1 was a pre-cycle leak that A/B/C all missed (`docs/reviews/code-review/v5.5.3_arbwait_reviewD_completeness.md`).

D's test-authority criterion is real per-site source mutation (not aggregate monkeypatch): edit production source to neuter one load-bearing site, run the suite, and confirm a specific test fails, then restore. A site whose bypass leaves the suite green is untested.

### 3.5 Running framing-disjoint reviews yourself (no subagent fleet)

If no ura-reviewer fleet is available, you run the passes yourself, sequentially, and MUST keep the framings truly disjoint. Method:

1. Write the framing statement for each reviewer BEFORE reading any code for that pass. Store all N framings in one paragraph at the top of a scratch note so overlap is visible.
2. Do Pass A end-to-end — read only within A's scope; write `..._reviewA_<framing>.md` completely; do NOT peek at what B/C/D will cover.
3. Between passes, clear your working state: re-read only the planning doc and CLAUDE.md § Review Protocol, not the review you just wrote. This prevents framing bleed.
4. Do Pass B, then C, then (Tier 3) D. Save each as its own file.
5. For Tier 3 D: re-enumerate every site of the invariant surface (grep the whole file, not just the diff). Run at least one real source-mutation test per load-bearing site.

Optional accelerator: if the ura-reviewer subagent is available, dispatch A/B/C/(D) in parallel with the framings pre-written. The framings are the load-bearing artifact — do not let a dispatcher generate them.

---

## 4. README_v<version>.md — release notes + validation ledger

`docs/readmes/README_v<version>.md`. Written BEFORE deploy; the git history of the file IS the validation ledger (per CLAUDE.md).

### 4.1 Pre-deploy structure

````markdown
# URA v<version> — <one-line summary> (Tier <N>)

<Two-to-four sentence "what ships" paragraph. Terse. No marketing. Concrete: what changed, what it fixes, who it affects.>

## Origin
<Trigger — bug report, incident, planned cycle. Cite live evidence: entity_id, log excerpt, DB row, date.>

## What ships (Tier <N> — <one-line scope>)
<Bulleted or table listing new entities, changed attributes, migrated schema. Include attribute shape diagrams if the wire format changed.>

## Review / gate
<Tier + which reviewers ran (A/B/C/D) + verdict summary. Pre-deploy zero-bugs gate outcome (conflict-marker grep, py_compile, cycle tests, suite-baseline-diff — see CLAUDE.md § Pre-Deploy Zero-Bugs Gate).>

## Acceptance
```yaml
version: <version>
hypotheses:
  - id: H1
    name: <slug>
    description: <one line>
    oracle: home_assistant
    query: { kind: home_assistant.state_attribute, entity: <entity_id>, attribute: <attr> }
    expected: { condition: "==", value: "<value>" }
    window: { first_check_after: 10m, confirm_after: 1h, alert_if_violated_after: 6h }
```
````

Acceptance-YAML kinds currently registered by the Shipwatch HA adapter (see `docs/BACKLOG.md` → Shipwatch entry, 2026-06-28): `home_assistant.state`, `state_attribute`, `history_max`, `history_min`, `history_count_above`, `log_count`. Do not invent new kinds without updating the sibling adapter. Older un-namespaced `ha_*` kinds are rejected by the current adapter registry.

### 4.2 Post-restart write-back — MANDATORY per CLAUDE.md

A cycle is not closed until its README carries the post-restart validation table.

After live validation runs against the restarted HA instance, replace (or append below) the prospective acceptance with an observed-results table. Copy this shape from `docs/readmes/README_v5.7.2.md` (verified 2026-07-02):

```markdown
## Live Validation — Validated <YYYY-MM-DD> (post-restart)
| # | Criterion | Result | Observed evidence |
|---|---|---|---|
| L1 | <criterion from planning doc's Live acceptance> | **PASS**/**FAIL**/**as-expected** | <concrete: entity_id.attribute = value; log scan result; DB row; MCP tool used>. |
| L2 | ... | ... | ... |
```

Rules for the table:
- One row per Live acceptance bullet from the planning doc. If a criterion could only be proven in-suite (not live), say so in the row and cite the test.
- Evidence must be authoritative: entity_id + attribute + value, not "looks fine". Cite the MCP tool or file you read (e.g. `ha_get_state`, `ha_get_history`, `ha_get_logs`, live Samba mount).
- Note boot-transient false-positives you saw and dismissed, with rationale.
- Note stronger-than-planned outcomes explicitly (v5.7.2 L3 caught a re-drop that the plan only expected to see clear — that is a real result worth logging).

If the live evidence contradicts a prospective claim, the cycle is not closed — fix or roll back, then re-validate. Do not silently rewrite the acceptance to match the miss.

### 4.3 Live-evidence gathering — commands (bake these in)

Prefer MCP tools; fall back to Samba mount + SSH when MCP is down. Exact paths per CLAUDE.md § Data Source Verification — do not invent them. Do not paste credentials into the README.

| Kind of evidence | Preferred | Fallback |
|---|---|---|
| Entity state / attribute | MCP `ha_get_state` | Read `.storage/core.restore_state` on Samba mount |
| Recent history | MCP `ha_get_history` | HA REST `/api/history/period/...` via SSH |
| Logs (search / count) | MCP `ha_get_logs` | `journalctl` / `home-assistant.log` via SSH |
| URA DB rows | MCP `ura-sqlite` (verify `--db-path` points to live Samba path, not `~/.cache/ura/` — CLAUDE.md § Data Source Verification) | Copy DB off Samba mount; open with `sqlite3` locally |
| Integration state | MCP `ha_get_integration` | HA REST `/api/config/config_entries/entry` via SSH |

If Samba is stale/down, the exact remount command lives in CLAUDE.md § Data Source Verification — copy it verbatim from there; do not paste it into this skill.

---

## 5. QUALITY_CONTEXT.md — when to add a bug class

`docs/QUALITY_CONTEXT.md`. Verified 2026-07-02: 52 bug classes present (header still reads "51 documented" — header is stale; fix it as part of the same edit when you add the next class).

### 5.1 Trigger — add a new bug class when ALL are true

- The bug is a class (a shape that has appeared before or is likely to recur), not a one-off typo.
- At least one review's "Why tests didn't catch it" section names a generalizable miss (missing assertion shape, missing lifecycle, missing site enumeration).
- No existing bug class already captures it. Grep `docs/QUALITY_CONTEXT.md` for the pattern before proposing a new one.

### 5.2 Entry shape — copy the existing pattern

Numbered `### Bug Class #<N> — <Title> ⚠️`. Sections in order: `The Mistake:` (code block with `# ❌ WRONG`), `Why it fails:` (bullets), `The Fix:` (code block with `# ✅ CORRECT`), `Regression prevention:` (what to grep or test for in future reviews).

Cross-reference: the review doc that first surfaced the class (`docs/reviews/code-review/<file>.md`) and the cycle README that shipped the fix (`docs/readmes/README_v<ver>.md`).

Update the header:
```markdown
**Bug Classes:** <N> documented (...existing history string... + 1 from v<version> <cycle name>)
**Version:** <bump>
**Last Updated:** <YYYY-MM-DD>
```

### 5.3 Do NOT add a bug class for

- One-off syntax errors or typos (those go to `TECH_DEBT.md` if the shortcut that let them through is durable, or to the review doc alone if it was a slip).
- Fabricated / prospective classes with no reviewer citation.
- Things already covered by an existing class — extend the existing class's regression-prevention section instead.

---

## 6. Coordinator design docs — `docs/Coordinator/`

Update when the coordinator's scope, signals, or invariants materially change — not for every edit. Existing docs verified 2026-07-02:

| File | Coordinator | Notes |
|---|---|---|
| `HVAC_COORDINATOR_DESIGN.md` | HVAC | Extensive; update sections 4/6/7 when control strategy or fan coordination changes. |
| `ENERGY_COORDINATOR_DESIGN_v2.3.md` | Energy | Current version. `v2.2.md` retained for history; do not edit as if live. |
| `PRESENCE_COORDINATOR.md` | Presence | Edit this, NOT `PRESENCE_COORDINATOR 2.md` (Finder duplicate). |
| `SAFETY_COORDINATOR.md`, `SECURITY_COORDINATOR.md` | Safety, Security | Same duplicate hazard — edit non-` 2.md`. |
| `NOTIFICATION_MANAGER.md` | NM | Signals + rate-limit shape. |
| `COORDINATOR_ARCHITECTURE.md` | Cross-cutting | The manager / signal-bus contract lives here. |
| `COMFORT_COORDINATOR.md` | (retired) | Kept for history; do NOT extend — comfort was folded into the Optimization Coordinator (MEMORY: "comfort sliders optimization coordinator"). |

Update rules:
- Bump `**Last Updated:**` at the top.
- If the coordinator's public signals or persisted DB tables change, update the "Signals" / "Persistence" section AND cite the planning doc and review doc that authorized the change.
- If a design decision was captured in vibememo, link the vibememo entry ID from the relevant section.

---

## 7. BACKLOG.md and TECH_DEBT.md conventions

### 7.1 BACKLOG.md

New backlog item shape (verified 2026-07-02 against current entries):

```markdown
## <Slug — human-readable> (Tier <hint>), <YYYY-MM-DD>

**Trigger.** <One paragraph: what surfaced this, with entity_id / log line / date. Cite live evidence.>

**Proposed scope.** <One paragraph or bullets. State REUSED vs NEW at the level you can commit to pre-scoping.>

**Not this cycle because.** <Why it's backlogged instead of built now — dependency, sequencing, resource.>

**Where it will be tracked.** <"Own planning doc when picked up: `PLANNING_<slug>.md`." OR "Rolled into <existing cycle>".>
```

`## ★ PINNED NEXT` at the top is reserved for the operator's explicit next-work commitment. Do not add or remove pins without operator sign-off.

### 7.2 TECH_DEBT.md

Living register. Each entry:

```markdown
## <Where the shortcut is — one line>

**Status:** <ACTIVE / RESOLVED (cycle vX.Y.Z) / SUPERSEDED>.

**Where:** `<file:line>` — <what the shortcut is, structurally>.
**Shortcut:** <what we did instead of the "right" thing>.
**Why acceptable:** <the reason it's OK for now — perf, blast radius, scope>.
**Trigger to revisit:** <the condition under which it stops being acceptable>.
```

When resolved, do not delete the entry — flip status to RESOLVED, add the resolution cycle + link the audit/review doc, and retain the historical body for traceability. Example: the "Presence Tier 1 ORs mmWave + PIR" entry (verified 2026-07-02) keeps its resolved-status header AND the original shortcut description.

---

## 8. vibememo cross-references

`/vibememo` (`.vibememo/`) is the durable decision trail. From URA docs:

- Cite, don't copy. In planning and review docs, reference vibememo entry IDs (from `.vibememo/vibememo.md` index) rather than pasting their bodies. Vibememo evolves under compression; pasted copies rot.
- When to trigger `/vibememo`: the doc you're writing records an architectural, product, or strategic decision that will affect future cycles — trust-hierarchy shifts, coordinator seam changes, tier-elevation policies, deprecations. Not every cycle needs a memo; every load-bearing decision does.
- Where to link from: planning doc's "Institutional context verified" section (under "MEMORY entry <slug>" bullets), and coordinator design docs when a section is directly downstream of a captured decision.

---

## 9. End-to-end walkthrough — a cycle's paperwork lifecycle

Sequence, with the doc produced at each step and who consumes it:

1. Scope / plan — write `docs/planning/PLANNING_<slug>.md` (§2). Consumed by: builder, reviewers, validator. Gate: "Institutional context verified" + tier classification + Acceptance Criteria with Live bullets.
2. Tag baseline — `git tag pre-review-v<version> -m "Pre-review baseline for v<version>"` (per CLAUDE.md § Pre-Review). This is a git action, not a doc, but reviewers rely on the tag existing to diff review-fix changes.
3. Build — code changes in `custom_components/universal_room_automation/`. Not this skill's concern.
4. Review — write `docs/reviews/code-review/v<ver>_<name>_review<A-D>_<framing>.md` per reviewer (§3). One per framing. Tier 2-DB = 3 files; Tier 3 = 4 files including D.
5. Fix-up — new commits, not amends. Update review docs' Summary Statistics table (Fixed column) as fixes land.
6. Pre-deploy README — write `docs/readmes/README_v<version>.md` §4.1. Consumed by `/deploy`. Gate: pre-deploy zero-bugs gate cited in the README's "Review / gate" section.
7. Deploy — `/deploy` skill. Not this skill's concern.
8. Live validation — after HA restart, gather evidence (MCP tools, live mount, entity attrs) per §4.3.
9. README write-back — append §4.2 Live Validation table. Cycle is not closed until this exists.
10. QUALITY_CONTEXT.md update (if applicable) — §5. Same commit or immediate follow-up.
11. Coordinator design doc update (if applicable) — §6.
12. BACKLOG / TECH_DEBT hygiene — §7. Any deferred items from the planning doc's "What may be deferred" section land here.
13. Vibememo (if applicable) — `/vibememo`. Cross-reference from planning doc.

Skipping any of steps 1, 4, 6, 9 breaks the paperwork chain the operator relies on. Steps 10-13 are conditional but must be actively decided (do it or explicitly note why not in the README).

---

## 10. Provenance and maintenance

All file, filename, and count claims below verified against the repo on **2026-07-02**. Re-verify when they may have drifted:

| Claim | Re-verify with |
|---|---|
| Review-doc naming (`review<A-D>_<framing>`) | `ls docs/reviews/code-review/ \| head -40` |
| Planning-doc conventions and existence of "Institutional context verified" | Skim `docs/planning/PLANNING_arbitrage_wait_inclement_floor.md` |
| README pre/post structure | Read `docs/readmes/README_v5.7.2.md` (Origin / What ships / Review / Acceptance / Live Validation) |
| Bug-class count (currently 52, header says 51) | `grep -c "^### Bug Class #" docs/QUALITY_CONTEXT.md` |
| Coordinator-doc duplicates (` 2.md`) | `ls "docs/Coordinator/" \| grep " 2\.md"` |
| Superseded roadmaps | `ls docs/ \| grep -i roadmap` |
| Acceptance-YAML kinds accepted by Shipwatch | `docs/BACKLOG.md` — "Shipwatch `home_assistant` adapter" entry |
| Tier policy | `CLAUDE.md` § Review Protocol — TIERED BY SCOPE (canonical) |
| Institutional-context requirement | `CLAUDE.md` § Institutional Context First |
| Live-validation write-back requirement | `CLAUDE.md` § Record Live Validation Back Into the README |

If CLAUDE.md and this skill diverge, CLAUDE.md is authoritative — update this skill.
