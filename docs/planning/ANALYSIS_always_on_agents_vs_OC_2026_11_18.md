# ANALYSIS: always-on agent patterns vs the Optimization Coordinator (2026-11-18)

Operator 2026-11-18: "Absorb this as context for OC and check if we are making any harness design errors that this guide
can improve https://claude.com/resources/articles/building-always-on-agents". Read-only analysis; no code changed.
Written by the orchestrator from the ura-planner's report (the subagent could not write the file).

Sources read: the article (fetched 2026-11-18); `domain_coordinators/optimization.py` (6405 lines: structural greps plus
the cycle and notify sections); `domain_coordinators/optimization_llm.py` (structure); `docs/planning/DRAFT_README_oc_never_fires.md`;
cards OC-SELF-OPTIMIZING-HOUSE-REDESIGN-1, OC-REQUEST-FIX-DISPATCHER-1, OC-SHADOW-SAMPLES-EMPTY-1,
OPTIMIZER-PAGING-PRIMITIVE-1, OPTIMIZER-META-NEVER-PAGES-1. Not read end to end:
`PLANNING_OPTIMIZATION_COORDINATOR_v2_agentic.md`, `PLANNING_OC_phase5_handshake_and_admin_surface.md`,
`AUDIT_oc_ai_task_leverage_2026_11_14.md`; read those before acting on anything here.

## 1. OC's real state (live URA DB, read-only, last 14 days)

| Measure | Value |
|---|---|
| Run cycle | Fixed 5-minute `async_track_time_interval` (`optimization.py:973`), re-entry guard on `_cycle_running` (`:1072-1084`) |
| Findings persisted | 1,802: tier1 1,778, tier2_llm 24; findings every day |
| By dimension | comfort 857, security_posture 437, sensor_health 264, occupancy_accuracy 115, vacancy_management 87, meta 42 |
| By severity | medium 855, high 716, low 228, critical 3 |
| Actions applied | **0** (`applied_action_id` NULL everywhere): shadow_dry_run 1,641, below_confidence_gate 119, advisory_only 42 |
| Shadow track record | `optimizer_shadow_samples` **0 rows** (OC-SHADOW-SAMPLES-EMPTY-1 still open) |
| Reached the operator | 22 `notification_log` rows, ~5 page events (meta 11-04 03:07Z and 11-07 14:51Z; sensor_health 3 on 11-07/08) |
| Daily digest | 3-18 findings a day, then **69 on 11-17** |
| Operator replies to OC | None (`notification_inbound` holds only safe_word, diag_*, unknown) |

OC wakes on a timer and writes findings, about 99% of which are never read. It has never acted, by the operator's
choice (2026-10-16 card note: noise). The LLM tier runs ~1.7 times a day under its rolling cap.

### 1a. Where docs and data disagree

1. A CRITICAL "URA Optimizer — meta" page went out 2026-11-07 14:51Z, after the OPTIMIZER-META-NEVER-PAGES-1 fix was
   committed (2026-11-04 08:13Z). Either that build was not deployed yet, or a path gets past the guard at
   `optimization.py:5966-5973`. Not verified.
2. The redesign card's "6,822 findings/14d" is stale: 1,802 now (~3.8x lower, probably the repeat suppressors and
   digest deferral; not verified).
3. The 11-17 digest spike (69 vs 3-18) is unexplained.

## 2. Pattern map

| Article pattern | OC today | Verdict and change |
|---|---|---|
| Sleep-and-wake run cycle | 5-minute timer tick with re-entry guard (`:973`, `:1072`) | Has it |
| Durable event inbox | None; runs start from the timer or `OptimizerRunCycleNowButton` | Missing; not needed at this scale (§4) |
| Fast ack, heavy checks in-run | No external event handler | N/A |
| Inbox as source of truth, reload on wake | Reloads `_last_findings` from `optimization_findings` (`:825-855`); LLM premium cap from DB (`optimization_llm.py:503`) | Partial |
| One active worker per inbox | `_cycle_running` guard | Has it |
| Mid-run events (queue / fold / interrupt) | Re-entry returns `[]` (`:1075-1078`): a run-now press mid-cycle is silently lost | Partial; set a `_rerun_requested` flag and run once more at cycle end |
| Batch related events | `_cycle_dedup`, `_cap_findings`, digest batches HIGH | Has it |
| Dedup by source id | `dedup_key` tuples, 24 h suppressor in an HA Store, notify TTLs (`:788-798`) | Has it, strong |
| Follow-up timers / schedules in a timer store | Only the fixed schedule; no self-set check-backs | Missing; build inside OC-REQUEST-FIX-DISPATCHER-1 |
| Durable memory, only the unrecoverable | `optimization_findings` is a full log, not curated memory; per-detector HA Stores | Partial |
| Memory: operator instructions | System prompt from CM options (`optimization_llm.py:598`) | Has it |
| Memory: operator notes / corrections | None; dispositions live on the kanban, which OC cannot read | Missing (Top 5 #1) |
| Memory: past messages | NM dedup + notify TTLs; `findings_recent` in the corpus | Partial; nothing records what the operator saw and dismissed |
| Memory: per-task progress | None | Missing; comes with the dispatcher check-back |
| Index-first loading | Corpus sections with trim caps (`optimization_llm.py:98-240`) | Partial |
| "Dreaming" | None; the digest is a count, not a curation | Missing (Top 5 #2) |
| Lean cached context | Stable vs snapshot split (`optimization_llm.py:118-125`); HA `ai_task` exposes no cache_control (`:43-46`) | Has what the platform allows |
| Compaction / reset | Single-shot LLM calls | N/A, correct for the design |
| Credential proxy | HA holds credentials; OC calls HA services | Has it by construction |
| Automated risk review, humans for important decisions | Autonomy ladder + per-dimension autonomy, confidence gate, shadow mode, handshake broker with sibling veto (`:273-464`) | Has it, stricter than the article; gap: no evidence pipeline to earn autonomy (shadow samples 0) |
| Deferred tool calls | No approve/deny path back from a page | Missing (Top 5 #3) |
| Interactive approval cards | NM inbound exists (safe_word, diag_*), no OC approve command | Missing; reuse NM inbound |
| Outbox + dispatcher | NotificationManager (cooldowns, DND, buckets, channels, `notification_log`) | Has it via NM; do not build an OC outbox |
| Three run endings | Page / nothing / digest; no "defer for input" | Partial |
| Eval-tuned message volume | HIGH to digest unless allowlisted (`:5990-6005`); META never pages; page precision never measured | Partial (Top 5 #4) |
| Cheaper intelligence favours long-horizon work | Single-shot LLM, 24 findings in 14 d | Note only |

Outside OC: NotificationManager is the outbox/dispatcher; `kanban.dispositions.pending.jsonl` is a durable operator
inbox for the dev agent, not OC; `optimization_findings` is the event log.

## 3. Top 5 changes (ranked by marginal benefit; all additive under "Only proven code should supersede correct code")

1. **Operator-feedback memory.** A small table / HA Store keyed by `(dimension, dedup_key)` holding the operator's
   verdict ("noise" / "real" / "fixed") from an NM reply or a dashboard button; tier1 emission and the LLM corpus read
   it. Goes straight at "never acted because of the noise". Tier 2-DB, ~one cycle; a mute list first captures most of it.
2. **Fix the shadow scorer, then a nightly "dreaming" pass.** Fix OC-SHADOW-SAMPLES-EMPTY-1 (score against persisted
   findings, not the current cycle's); then one nightly job computes precision per dimension from shadow samples +
   operator verdicts, tightens or prunes weak detectors, and puts the precision table in the digest. Builds the track
   record the ladder requires. Scorer fix = redesign slice 1; nightly job Tier 2.
3. **Approval by reply.** When a finding would act if autonomy allowed, page with approve/deny; the reply lands in
   `notification_inbound` and the next cycle applies via the existing `_apply_action` (`optimization.py:4634`) and
   handshake. Tier 3 (actuation); park until #2 shows good shadow precision on at least one dimension.
4. **Page-precision trip-wire.** Label each OC page's outcome (ACKed / dismissed / ignored) from `notification_log`
   and `notification_inbound`; anomaly to NM when a dimension's page precision falls or the digest spikes (11-17).
   Tier 1-2, read-side.
5. **Follow-up timers inside the request_fix dispatcher.** "Check back at T" rows in a small table that the existing
   tick drains first. Inside OC-REQUEST-FIX-DISPATCHER-1, not separately.

## 4. Not recommended

- **A general OC event inbox:** the 5-minute poll already reads ground truth; a new writer and ordering rules buy
  nothing at current event rates. Revisit if OC reacts to many discrete external events (e.g. operator replies).
- **An OC outbox:** NotificationManager is it.
- **Multi-turn LLM sessions with compaction:** single-shot on a curated corpus is right for now; revisit after #1 and #2.

One-line fix for any OC cycle: queue a rerun when "run cycle now" is pressed mid-cycle (`optimization.py:1075`).

## 5. Open verification

- The 11-07 14:51Z META page: the deployed version then, and the `dimension` / `created_by` of its finding row.
- The 11-17 digest spike: `optimization_daily_digest.by_dimension_json` for that date.

Probe scripts: `.claude/tmp/oc_probe_measure.py`, `oc_probe_measure2.py`, `oc_probe_measure3.py`.

## 6. The same guide applied to the orchestration harness (orchestrator, 2026-11-18)

Today's evidence against the guide: (1) a mutating reviewer and two readers shared one worktree twice (one writer per
tree: now a standing rule); (2) duplicate agent reports and ~20 no-news pings answered with status lines (report once;
send nothing on non-events: standing rule); (3) follow-ups ("ship at 10:00", "re-measure in 30 min") live only in the
session, no durable timer store; (4) no "dreaming" pass on memory (index 134 lines / 227 files, 5 stale RESUME
pickups); (5) operator decisions pile up as chat lists instead of an approvals surface. (3)-(5) await the operator's yes.
