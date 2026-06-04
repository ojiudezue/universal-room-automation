> ⚠️ **Pre-spinoff plan (2026-06-01).** Shipwatch was spun off into a
> sibling repo at `~/Code/shipwatch/` on 2026-06-02. This document
> remains in the URA repo as a historical record of the pre-spinoff
> thinking. **Active planning lives at `~/Code/shipwatch/docs/planning/`.**

# PLANNING — `ura-shipwatch` (foundation cycle)

**Version slot:** v4.8.0 candidate (foundation work — shapes everything downstream)
**Tier:** 2-DB (introduces new persistence + cross-coordinator surface + a new repo convention)
**Status:** drafted 2026-06-01 post-v4.7.16.2 deploy, awaiting operator review
**Sibling memos:** [[project-queued-sprint-deploys-2026-05-31]], [[project-v4712-live]] (D3 diagnostic-only pattern this generalizes)

---

## Founding principle (per-cycle judgment, not blanket convention)

**Shadow-then-promote is one tool among many. Each cycle's planner decides whether to use it.**

The trigger for tonight's session was that several recent cycles shipped load-bearing decisions straight to gating and the operator only noticed the effects by physical feel. The fix is not a blanket rule — URA is a single-user, single-install project, and a religion that adds a second cycle to every decision is overkill. The fix is making the shadow-then-promote tool *cheap and available* so the planner can reach for it when blast radius warrants.

The planner explicitly decides per cycle:

- **Ship-and-watch (default)** — small surface, reversible, easy to detect failure by existing channels (logs, sensors, physical sensation). Most hotfixes and incremental improvements. Tonight's hotfix A would have qualified.
- **Shadow-then-promote** — high blast radius, hard to reverse, or the failure mode is silent (no log, no obvious sensor, only surfaces in aggregate over days). The v4.7.16 D3 room-veto density correctly used this — its failure mode is "wrong rooms get vetoed," which doesn't trip any log.
- **Direct gating with explicit acceptance hypothesis** — middle ground. Ship gating, but the README's acceptance block names what would prove it correct, and `ura-shipwatch` watches for confirmation/violation. Tonight's hotfix B (sleep-occupied fan trust) would fit here — gating immediately, with a stated hypothesis that fans stay on through the night in occupied bedrooms.

The deliverable below is the **infrastructure that makes all three modes cheap**: structured acceptance blocks, deploy-time baseline snapshots, and the watcher agent. The convention layer is dropped; reviewer guidance becomes "did the planner make a defensible choice given blast radius?", not "did they shadow?"

---

## Why now

State machines this complex stop failing at restart. They fail when conditions converge a week later, and the operator only notices when something physical (a fan, a thermostat preset, an unexpected bill) tells them. Tonight's whole diagnostic started because the operator *felt* the fan stop. Point-in-time post-deploy validation has hit its ceiling — it confirms "didn't immediately explode," not "is actually doing what it should."

We've already accidentally invented the pattern in v4.7.16 D3 (room-veto density shipped as `scope="room_level_weighted"` falls through to no-op verdict). v4.7.17 was scoped to flip it to gating after a week of diagnostic data. We never named the convention. This cycle names it.

---

## Architecture

Three layers, each running where it is cheapest:

```
┌──────────────────────────────────────────────────────────────┐
│ DEPLOY-TIME (deploy.sh)                                      │
│  • Read next version's acceptance block                      │
│  • Snapshot current value of every metric it names           │
│  • Store as baseline record keyed by (version, deploy_ts)    │
└──────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────────┐
│ DATA COLLECTION (HA recorder — already exists)               │
│  • Every state change persisted by HA's recorder             │
│  • Acceptance metrics become recorder queries, not new       │
│    sensors                                                   │
│  • No new storage to reinvent                                │
└──────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────────┐
│ SYNTHESIS (Claude Code agent, CronCreate-scheduled, daily)   │
│  • Wakes once per day (configurable)                         │
│  • Reads acceptance blocks for all active deploys            │
│  • Runs recorder queries vs baseline                         │
│  • Classifies each hypothesis: confirmed / violated / pending│
│  • Writes findings to `.vibememo/` + URA DB                  │
└──────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────────┐
│ REPORTING (existing memory pipeline)                         │
│  • Next session loads memory at startup                      │
│  • Violations float to top of context                        │
│  • Operator sees findings without polling                    │
└──────────────────────────────────────────────────────────────┘
```

**Why not in-process inside URA?** The watcher must survive when URA itself is broken — that's the case where its judgment matters most. Co-locating with URA defeats the purpose.

**Why not pure HA YAML automation?** Collection works; synthesis does not. The agent has to reason: "is this drift the hypothesis pattern, or household noise, or correlated with the deploy?" That's LLM-shaped. Cost-bounded by daily cadence.

**Why HA recorder, not new DB?** HA already captures every state change. Re-inventing the time-series store loses the institutional advantage. The acceptance block reduces to "name the entities and the query shape."

---

## Deliverables

### D1 — Acceptance block format (YAML in README)

Each `docs/readmes/README_v<version>.md` gains a structured `## Acceptance` block at the end. Format example, using tonight's hotfix A:

```yaml
## Acceptance

version: v4.7.16.2
hypotheses:
  - id: H1
    name: ac_nudge_gate_actually_fires
    description: |
      With AC_NUDGE_OVERSHOOT_GAP = 0.0, Gate 6 of check_ac_reset
      should now trip whenever a zone holds at setpoint while burning
      kWh past threshold for the sustained-time gate. Pre-hotfix
      baseline: 0 organic auto-nudges per day for prior 7 days.
    query:
      entity: sensor.ura_hvac_coordinator_ac_nudges_today
      reduction: max_over_period
      period: 24h
    expected:
      condition: ">="
      value: 1
    qualifier:
      # only count days where conditions could have triggered
      requires_any_zone_cooling_min: 30
      requires_kwh_rate_above_threshold_min: 15
    window:
      first_check_after: 24h
      confirm_after: 72h
      alert_if_violated_after: 168h  # 7 days

  - id: H2
    name: no_false_positive_nudges
    description: |
      Lower threshold must not produce spurious nudges. False-positive
      rate should stay below the v4.7.7 user-set tolerance.
    query:
      entity: sensor.ura_hvac_coordinator_ac_nudge_false_positive_rate
      reduction: state_at_check_time
    expected:
      condition: "<="
      value: 0.20  # 20%
    window:
      first_check_after: 72h
      alert_if_violated_after: 168h
```

Format choices:
- **YAML at end of README** beats a separate file because operators already look at the README post-deploy. Co-located = less drift.
- **Hypothesis IDs** (H1, H2) match the pattern v4.7.14.1 already uses for fix-up tracking.
- **Window fields** make explicit when each hypothesis becomes alert-worthy vs still gathering.
- **Qualifiers** prevent false violations from windows where conditions never converged.

A parser-validation test lives in `quality/tests/` to ensure every deployed README's acceptance block round-trips through a schema.

---

### D2 — Deploy-time baseline snapshot (deploy.sh modification)

`scripts/deploy.sh` gains a new step **between** the test-run and the version-stamp phases:

```bash
==> 1.5/7 Capturing pre-deploy baseline
   - Parse docs/readmes/README_v${VERSION}.md acceptance block
   - For each hypothesis, query HA for current metric value
   - Write to URA DB table `shipwatch_baselines`
   - Schema: (version, hypothesis_id, metric_value_json, baseline_ts)
```

Without this snapshot, post-deploy "compared to baseline" is impossible — exactly the v4.6.3 lesson the operator coined as DB-sensitive-cycle protocol. Apply it generally.

DB schema (new, additive):
```sql
CREATE TABLE IF NOT EXISTS shipwatch_baselines (
    version TEXT NOT NULL,
    hypothesis_id TEXT NOT NULL,
    metric_value TEXT NOT NULL,  -- JSON serialization
    baseline_ts INTEGER NOT NULL,
    PRIMARY KEY (version, hypothesis_id)
);

CREATE TABLE IF NOT EXISTS shipwatch_findings (
    version TEXT NOT NULL,
    hypothesis_id TEXT NOT NULL,
    check_ts INTEGER NOT NULL,
    state TEXT NOT NULL,  -- "confirmed" | "violated" | "pending"
    observed_value TEXT NOT NULL,  -- JSON
    notes TEXT,
    PRIMARY KEY (version, hypothesis_id, check_ts)
);

CREATE INDEX IF NOT EXISTS idx_shipwatch_findings_recent
    ON shipwatch_findings (check_ts DESC);
```

---

### D3 — `ura-shipwatch` agent definition

New agent at `~/.claude/agents/ura-shipwatch.md`. Responsibilities:
- Load all acceptance blocks for versions deployed within the last 14 days
- For each active hypothesis, run its recorder query
- Compare to baseline + expected value
- Classify: `confirmed` (expected met + window cleared), `violated` (expected unmet + window cleared), `pending` (insufficient data or window not cleared)
- Write findings to `shipwatch_findings` table
- Write violations + freshly-confirmed hypotheses to `.vibememo/` so next session picks them up
- For violations that have aged > 24h without operator engagement, escalate via NM (a CRITICAL anomaly notification, gated through whatever NM-1 ships)

Agent tools: read-only HA recorder queries + DB writes + Read + Write for memory updates. No HA service calls. No code edits.

The agent's prompt template encodes the convention: "your job is to ask whether the deployed change actually does what the README claimed it would, not whether anything broke."

---

### D4 — Schedule + cadence

`CronCreate` schedule:
- **Daily at 09:00 CDT** — primary synthesis run. Reads all active acceptance blocks, runs queries, writes findings.
- **Manual trigger** via `/shipwatch` slash command — operator can ask "what's the current state?" any time, no waiting for the cron.
- **Post-deploy boost** — for the first 72h after any deploy, the cron also fires at 21:00 CDT (catches end-of-day cooling cycles for HVAC-related hypotheses).

Cost: ~1 agent run/day at typical synthesis size. Bounded.

Active deployment ages out after 14 days unless the acceptance block declares a longer window (e.g., Forecaster cycles may want 30-day confirmation periods for weekly-cycle metrics).

---

### D5 — Reporting + memory integration

When the agent writes a violation:
- New `.vibememo/users/<operator>/entries/shipwatch_violation_v<version>_<hypothesis>.json`
- Brief synopsis to `MEMORY.md` index — one line, ~150 chars
- Next session loads memory at start, violation surfaces in operator's first prompt

When the agent writes a confirmation:
- Updates `shipwatch_findings` table
- No memory write (confirmations are quiet; only violations + first-confirmations earn a notification)
- After all hypotheses for a version are confirmed, writes a single `shipwatch_complete_v<version>.json` memo so the operator can clean up old planning docs

This is intentionally noise-free. The watcher only speaks when something matters.

---

### D6 — CLAUDE.md convention codification

Add to `CLAUDE.md` under a new section:

```markdown
## Shadow-then-Promote Convention — MANDATORY

Every load-bearing decision in URA ships in shadow mode by default.
Promotion to gating requires an explicit second cycle, gated by
evidence collected via the `ura-shipwatch` watcher.

A "load-bearing decision" is any code path that:
- Writes to a thermostat preset, climate setpoint, switch state,
  cover position, or fan state
- Fires a notification
- Vetoes another coordinator's intent (HVAC defer, compliance suppress, etc.)
- Reduces the population a quorum is computed against (e.g., the
  v4.7.14.1 _trusted persons count)

Shipping such a decision in its first cycle requires the diff to:
1. Implement the new logic
2. Compute its verdict
3. Log/persist what it WOULD have done — but not execute it
4. Define an acceptance block in the README naming the metric(s) that
   would prove the shadow agrees with reality
5. Schedule the gating-flip cycle in the planning doc footer

Reviewers must flag any cycle that promotes a new decision-maker to
gating in the same cycle it's introduced. The only exception is a
hotfix to existing already-gating logic.

Retroactive backfill: at convention-adoption time, list existing
load-bearing decisions that never had a shadow phase. File a backlog
item per high-blast-radius decision to add a synthetic shadow + run
the watcher over recent recorder history to determine whether it
would have agreed or disagreed.
```

---

### D7 — Retroactive backfill

The watcher only watches forward by default — shadow blocks are added to NEW deploys. For existing already-gating decisions, we do a one-time audit:

Candidate audit list (decisions currently gating without ever having shadowed):
- v4.7.13 sleep zone trust (zone aggregator SLEEP fallback)
- v4.7.14 away-state person-tracker veto
- v4.7.14.1 H1/H2/H3 forgotten-phone filters
- v4.7.15.1 D1 Pattern A consumes v4.7.14.1
- v4.7.15.1 D6 HVAC defer gate + compliance suppress
- v4.7.16.2 Hotfix A (AC nudge gap change)
- v4.7.16.2 Hotfix B (sleep-state occupied fan trust)

For each, write a retroactive acceptance block. Run the watcher in a "replay" mode over the last 14-30 days of recorder history to compute confirmed-vs-violated counts. This both validates the convention and catches any silent regressions we already shipped.

Replay mode requires the watcher to support `--at <timestamp>` to query historical recorder state as of a point in time. ~50 LoC extension.

---

## Tier classification — operator-elevated 2-DB

Triggers per CLAUDE.md:
- New DB tables (`shipwatch_baselines`, `shipwatch_findings`) → Tier 2-DB trigger 1
- Cross-coordinator surface (the convention applies to every coordinator) → operator-elevation justification
- Convention codification + retroactive backfill → systemic change, framing-disjoint review needed

Three parallel reviewers (Tier 2-DB protocol):
- **Reviewer A — Acceptance block correctness + readability.** Are operators going to write these correctly under deploy pressure? Is the schema expressive enough for real metrics without becoming unwieldy?
- **Reviewer B — Agent autonomy + safety.** What can the watcher do wrong? Are its tool permissions tight? Can it false-alarm? Can it false-confirm? What happens when HA's recorder is itself broken (the case where shadow data is unreliable)?
- **Reviewer C — Convention compatibility.** Does the shadow-then-promote rule actually fit URA's existing hotfix cadence? Are there legitimate cases the rule blocks? What's the escape hatch for true emergency fixes (the v4.7.16.1 DOMAIN-shadow class)?

---

## Live validation (the ironic case)

`ura-shipwatch` itself is a load-bearing decision — it changes how every future cycle ships. Per the convention it's establishing, its first deploy should:
- Ship the schema + collection in shadow mode
- Run for one week, observing whether its findings match operator intuition (does it correctly classify the v4.7.16.2 hotfixes from this week?)
- Cycle 2 promotes the agent's reporting authority — its violations get NM-channel escalation rights, its confirmations clean up backlog memos

We will eat our own dogfood. If the convention doesn't survive its first application, it isn't ready.

---

## Out of scope (separate cycles)

- **Automated promotion** — the ritual to flip a shadow decision to gating once evidence is sufficient. Cycle 3+ once we have data on what "sufficient" means in practice.
- **Real-time alerting / paging cadence** — that's NM's domain. Shipwatch produces findings; NM-3 (per-tick rate cap) decides how they reach the operator.
- **Anomaly detection beyond hypothesis checking** — discovering surprises the README didn't predict. Forecaster + Routine Awareness territory. Shipwatch only checks what the README claimed.
- **Replay/historical analysis for arbitrary questions** — Shipwatch is hypothesis-confirmation, not free-form recorder mining. Operator can still grep recorder via existing tools.

---

## Open questions for operator review

1. **Cadence:** daily 09:00 too sparse for HVAC-related hypotheses that need to see end-of-day cooling cycles? Should we default to 09:00 + 21:00 always, not just post-deploy?
2. **Hypothesis format:** YAML at end of README adequate, or should we move to a structured `acceptance.yaml` per version directory? (YAML-in-README is denser; separate file is cleaner for parsers.)
3. **Retroactive backfill scope:** all 7 listed candidates, or just the highest-blast-radius (v4.7.15.1 D6, v4.7.16.2 hotfix B)?
4. **Notification routing:** violations route through whatever NM ships, but what does that mean today before NM-1..NM-6 land? Use a placeholder direct-iMessage path that NM later subsumes?
5. **Convention scope:** does the shadow-then-promote rule apply to UI-only changes (config flow, dashboard layout), or only to actuating decisions? Recommend: only actuating, but flag the question.

---

## Recall

- "Resume shipwatch planning"
- "Build the shadow-then-promote convention"
- "How will we know it's working"
