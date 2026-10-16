# VISION: The self-optimizing house

Status: DRAFT for operator review (2026-10-16). No code, no version. Cards: OC-SELF-OPTIMIZING-HOUSE-REDESIGN-1 (`kanban.data.yaml:227-238`), ROADMAP-STALE-AGENTIC-LAYER-1 (`:9380-9420`), OC-SHADOW-SAMPLES-EMPTY-1 (`:239-245`).

File paths are relative to `custom_components/universal_room_automation/` (written `C/`) or `docs/planning/`. Code wins over this doc. Where a claim was traced only from code and not checked against the live DB, the doc says so.

---

## 0. Institutional context verified

**Primary inputs, read in full.**
- OC docs: `PLANNING_OPTIMIZATION_COORDINATOR.md` (v1), `PLANNING_OPTIMIZATION_COORDINATOR_v2_agentic.md`, `PLANNING_OC_phase5_handshake_and_admin_surface.md`, `PLANNING_audit_optimization_coordinator.md`, `CRITIQUE_audit_optimization_coordinator_2026-07-10.md`, `DRAFT_README_oc_never_fires.md`, `PLANNING_hc_precool_toggle_oc_observability.md`.
- Memory docs: `ARCHITECTURE_hierarchical_memory.md`, `MVP_hierarchical_memory.md`, `PLANNING_memory_roadmap_and_critique.md`, `PLANNING_memory_writers.md`, `PLANNING_memory_compactor.md`, `AUDIT_memory_writer_coverage.md`, `AUDIT_memory_retro_value.md`, `AUDIT_memory_handbuild_study_a.md`, `AUDIT_memory_handbuild_compactor_exterior_track.md`.
- Context docs: `AUDIT_v6_milestone_candidates.md`, `docs/ROADMAP_v12.md` §agentic (`:133-157`), `docs/VISION_v7.md` (`:16, 157, 164, 224, 423-426, 623`).
- Not read: the HVAC STATE_OF_PLAY doc. This vision makes no HVAC change. Any slice that touches HVAC must read it first.

**Code surveyed:** `C/domain_coordinators/optimization.py`, `optimization_llm.py`, `C/const.py` (OC block 3900-4434), `C/database.py` (shadow samples), `C/memory_facade.py`, `C/memory_writers.py`, `C/memory_compactor.py`, plus the existing loop sites in the table below.

| Existing piece | file:line | Verdict |
|---|---|---|
| Autonomy ladder L0-L5 (advisory..unbounded) | `const.py:3908-3925`, conf key `:3935`, default shadow `:3948` | **EXTEND**: keep the rungs, but apply them per action class instead of per dimension (`CONF_OPTIMIZER_DIMENSION_AUTONOMY` `:3937` is the seed) |
| Single chokepoint `_consider_apply` → `_apply_action` | `optimization.py:~4775`, `:4282` | **REUSE** as the only action path |
| Intent broker + sibling veto handshake | `OptimizerIntentBroker` `optimization.py:259`, `fire_intent :453`; design in phase5 `:50, :238-244` | **REUSE**: this is how a tool asks a domain coordinator first |
| L2 device dispatch, allowlist light/switch/fan/cover/climate | `_dispatch_device_action optimization.py:4487`, `const.py:4013` | **REUSE**, behind per-class opt-in |
| L3+ config writes, number/select, ±20% clamp | `const.py:4018-4021` | **REUSE** for the knob-adjust tool |
| Confidence gate 0.7, rate cap, quiet hours, kill switch | `const.py:3938, 3950`; `optimization.py:4326` | **REUSE** |
| Outcome enum (shadow_dry_run, advisory_only, …) | `const.py:4424-4434` | **REUSE** |
| `optimizer_shadow_samples` table + writer + reader + prune | `database.py:1285, 6856, 6902, 6930` | **REUSE storage, REWRITE the producer** (§1.3) |
| Shadow validator | `optimization.py:1278, 1488-1560` | **RETIRE/REWRITE**: structurally cannot produce a sample |
| Promotion readiness (min 20 samples, accuracy floor 0.60, 7-day span, blockers) | `optimization.py:5103-5209`, `const.py:4414-4416` | **EXTEND**: becomes the per-class precision card the operator sees |
| Tier-1 evaluators (13 dimensions + camera/never-fires) | `optimization.py:1044+`; stubs `const.py:4397` | **RETIRE** as user-facing findings, except sensor_health/never-fires/camera; the rest become goal metrics or internal only |
| LLM tier (provider-agnostic, 24 calls/day) | `OptimizationLLMTier optimization_llm.py:261`; only producer of `proposed_action` `:1161` | **EXTEND** into the incident summarizer and proposer (§4) |
| Paging (`_notify_if_severe`, high-allowlist, digest deferral) | `optimization.py:5417`, `const.py:3470` | **REUSE** for the quiet goal |
| Memory facade, 7 verbs per node | `memory_facade.py:336-911` | **REUSE**. **EXTEND** `_compose_locality :874`, whose `_adjacency_cache` (`:344`) is never populated |
| Memory writers / compactor | `memory_writers.py:138-697`, `memory_compactor.py:231` | **REUSE**. Coverage gaps are listed in §1 |
| `memory_episodes` / `memory_facts` / `metric_baselines` / `outcome_log` | arch doc `:111-257` | **REUSE**: `outcome_log` is where a loop's measure step writes |
| HVAC governed writes `emit_set_*`, excursion kinds | `hvac_setpoint.py:436, 549, 820, 899, 1040`; `hvac_excursion.py:117` | **REUSE**: the only HVAC tool path |
| Write-verify self-heal | `WriteVerifier energy_write_verify.py:131` (`schedule :417`, `reversion_sweep :726`) | **REUSE** as the model loop: act → read back → revert |
| AnomalyDetector (z-score, min 24 samples) | `coordinator_diagnostics.py:981`, used in hvac/presence/security/music | **REUSE** for detect. NM wiring from it was not traced |
| Per-entry reload with cooldown and daily cap | `hvac.py:8758-8767` | **EXTEND** into a generic reload tool. v2 App. C warns reload does not revive an off-WiFi device (`:593`) |
| HVAC predictor, Bayesian, PatternLearner, energy forecast | `hvac_predict.py:89`, `bayesian_predictor.py:132`, `pattern_learning.py:20`, `energy_forecast.py:50` | **REUSE** as predictors, not rebuilt |
| Arbitrage lead-time knob | `number.py:1586` | Example of a hand-run loop (the 360→180 change) |
| ConflictResolver | `domain_coordinators/manager.py:86` | **REUSE** for cross-room arbitration |
| "Health monitor" | none found under that name | Correction: the earlier draft cited it. Its role is played by sensor_health findings + the anomaly detector |
| A separate notification-dedup function | not found in `optimization.py` | Correction: the earlier draft claimed one. Dedup lives in the paging path above |

**New, with no equivalent found:** goal definitions (§2.1), action-class registry (§2.2), per-class precision card (§2.5). Each is a thin layer over the REUSE items above.

---

## 1. The problem, and what the two programs already tried

### 1.1 In your words

> "I want a self optimizing house. Else I'm stuck chatting all the time. There has to be a way to give it goals and tools, have it use logs to spot real problems and use loops to optimize."

Today you are the optimization loop. You notice a symptom (restart storm, Envoy going blind, an alert flood) and open a chat. An agent then mines journald, the recorder and the URA DB, and a human-approved cycle ships the fix. URA already writes most of that evidence. The house never reads it and acts on its own.

### 1.2 OC today (14 days to 2026-10-16, from `AUDIT_v6_milestone_candidates.md:41`)

| Fact | Number |
|---|---|
| Findings | 6,822 |
| Low-value tier-1 (`meta/low` 2,246, `prediction_accuracy/low` 2,117, `comfort/medium` 1,808) | ~90% |
| `sensor_health/high` (the useful part) | 265 |
| `tier2_llm` | 124 |
| Outcomes shadow_dry_run / advisory_only / below_confidence_gate | 4,240 / 2,287 / 305 |
| Actions | 0 (level = shadow, by your choice) |
| `optimizer_shadow_samples` rows | 0 |

> "it never acted because I sensed this [noise]. And didn't set it to act."

Shadow was a trust withhold, and it was correct. The failure is signal quality, plus a scoring path that could never have earned trust anyway.

### 1.3 Why `optimizer_shadow_samples` is empty (traced from code, not checked live)

The validator (`optimization.py:1488-1560`) only scores a finding that is in `self._last_findings` and is at least 900 s old (`OPTIMIZER_SHADOW_OBSERVE_DELAY_S`, `const.py:3985`; check at `:1517`). Three things stop it:

1. **Nothing is ever 15 minutes old.** `_last_findings` is replaced every 5-minute cycle (`:1231`), and findings are stamped `now` when created (`:3139, 3175, 3337`). Every candidate fails `ts > cutoff`. This alone guarantees 0 rows.
2. **Occupancy findings never reach SHADOW.** They carry confidence 0.55 (`:3342`), below the 0.7 gate, so they become BELOW_GATE. That leaves only comfort.
3. **The comfort oracle often returns None** when bounds, a sensor or a reading are missing (`:1658-1736`).

Before that, the samples lived in RAM only and a weekly restart wiped them (audit MED-2 `:104`). They were persisted to the DB later, but the age bug means nothing ever reached the table. Also, every tier-1 evaluator emits `proposed_action=None` (e.g. `:2083, 3151, 3348`). So even a working scorer would only be scoring "a problem exists", not "this action would help". The v2 plan's L1 promise was "logs the exact action it WOULD take… scored against the actual outcome" (`v2 :16-21`). For tier-1, that never existed.

### 1.4 What the memory and OC programs planned, what shipped, and where they fell short

| # | Failing (evidence) | How this design answers it |
|---|---|---|
| F1 | **No written path to action.** The L1→L2 criteria were never documented (audit `:138-142`). The numeric gate exists only in code (`const.py:4414`; the critique's gate `:245` uses 80% while code uses 0.60). Only 2 of 14 dimensions can be scored (audit `:140`). | §2.5: per-class precision card, thresholds as visible knobs, promotion offered to you. A class with no scorer cannot climb past rung 1, and the card says so. |
| F2 | **Scorer structurally dead** (§1.3). Findings carried no action to score. | §2.4: a loop row is created only when a tool is proposed. It is stored durably at proposal time (not in a rolling in-memory list) and scored later from `outcome_log`. Slice 1 acceptance requires rows to accumulate. |
| F3 | **Findings organized around what is computable, not around goals.** 14 dimensions advertised, about 5 emit, stubs report "ok" (audit `:117`, critique `:36`). The per-room score defaults to 100, so "never ran" looks the same as "clean" (critique `:158`). | §2.1: every finding must name the goal it threatens. No goal, no finding. "Unknown" is a separate state from "ok". |
| F4 | **Silent no-ops.** Memory `_schedule` dropped writes behind a bare except, so 3 writers had 0 rows (coverage `:7-31`). The OC veto guard caused silent advisory-only behavior at L2 (phase5 `:276`). A sibling in observation mode silently disables L2 (`:277-282`). Rate-cap seed errors were swallowed at DEBUG (audit `:107`). | Every tool call writes its outcome row (applied / vetoed / no-op / failed) and reads the actuator back (the WriteVerifier pattern). A class whose outcomes are mostly no-op is demoted and paged. This does not prevent new silent bugs. It makes them visible on the card within a day. |
| F5 | **"Shipped and working" claimed without checking the DB.** The writers plan said "not under-firing" and deferred the probe (writers `:24, :72-75`); live, they had 0 rows (coverage `:69-71`). | Each slice has a live DB acceptance criterion: rows exist, with non-sentinel values. This is the existing Review-D rule, applied to the loop's own tables. |
| F6 | **Detectors' blind spots become memory's blind spots.** All 56 phantom rows came from PIR rooms, while the three rooms that actually latched have 0 rows (retro `:17-28`). Never-fires was disabled by unavailable time and missed late-added sensors (draft README `:18-28`). | Only partly answered. The loop measures goals from ground truth (actuator state, temperatures, `notification_log`), not from the detector that raised the finding. A detector that never fires stays invisible unless a goal metric degrades. Open risk, stated in §6. |
| F7 | **Value shown in hand-builds but not live.** Study A self-scored 6/7 (`:154`). The live retro scored 0 FULL of 4 investigations (retro `:141`). Facade verbs are under-used next to raw SQL (roadmap `:133`). | Slice 1 is judged on live numbers only. Memory is used where a loop needs it (baselines for detect, `outcome_log` for measure), not as a product in itself. |
| F8 | **Built with nothing reading it, or nothing producing it.** Comfort sliders have no reader (v1 `:581`). `observed_effect` has no producer (hc `:23`). Four episode types have no writer. 362 away-block episodes have 0 facts (coverage `:49-52, :95`). The facade's `_adjacency_cache` is never written (`memory_facade.py:344, 874`). | Each new piece ships together with its consumer, in the same slice. `observed_effect` gets its producer in slice 1, because that is what the measure step fills. |
| F9 | **Over-correction after incidents.** The write-flood rollback pushed the OC toward invisibility (audit `:127, :161`). | Loop rows go through the batched DB write queue and are capped per day. They are subject to the critique's D9 write-volume tripwire (`:261-270`). |
| F10 | **Unsafe operator surface.** Raw tokens and an unguarded select ("a stray dashboard tap could push L5", phase5 `:20, :46`). | Promotion is one class at a time and needs explicit confirmation. The global level becomes a kill switch plus a ceiling. |

**What memory explicitly forbids, and this design keeps:** no memory-driven actuation in safety, security arming, occupancy create/release, or reserve floor (arch `:304-322`; P8 rejected permanently, roadmap `:179-189`). Locality is a query *answer*, not a permission boundary (arch `:196-203`).

**What memory was built for:** "the room-to-room agentic layer… the consumer the memory foundation was built for" (roadmap `:171-177`). §3 is that consumer, deliberately small.

---

## 2. The model

Five parts. Each extends something in §0.

### 2.1 Goals (you set them, the house measures them)

| Goal | Example target | Measured from |
|---|---|---|
| Comfort | occupied rooms in band ≥95% of occupied hours | room temps + occupancy (comfort sliders `v1 :581` finally get their reader) |
| Cost | monthly import under $X; no peak import | energy coordinator / TOU |
| Reliability | no actuator unavailable > 30 min unnoticed; no unexplained restart | sensor_health / never-fires / camera evaluators, restart history |
| Quiet | ≤ N pages/day; page only if a goal is at risk and the house can't fix it | `notification_log`, paging primitive `optimization.py:5417` |
| Safety and security | never delegated (§3) | — |

Targets are Number entities and enables are Switches. These are on the existing knob ladder; no options-flow additions. The quiet goal is the one that addresses the chatting.

### 2.2 Tools (typed, scoped, reversible)

| Tool (action class) | Reuses | Undo |
|---|---|---|
| Mute/merge a finding class | paging allowlist + digest deferral (`const.py:3470`) | unmute |
| Adjust a knob within bounds | L3 number/select write ±20% (`const.py:4018-4021`) | restore prior value |
| Reload one stuck config entry | generalize `hvac.py:8758-8767` (cooldown + daily cap) | idempotent; documented limit (off-WiFi) |
| Device action (light/switch/fan/cover) | `_dispatch_device_action :4487` + broker veto | inverse service |
| HVAC nudge | `emit_set_*` + excursion kinds only, behind HVAC-OPTIMIZER-CLIMATE-FUNNEL-ROUTING-1 (parked prerequisite) | excursion expiry |
| Page / file a card | NM, kanban intake | n/a |

Each tool declares its scope, bounds, undo, and the goal metric it expects to move. Every call goes through `_consider_apply` → `_apply_action` and the intent broker, so siblings can veto it (phase5 `:238-244`). There is no second write path. A tool with no undo can never run autonomously.

### 2.3 Observation

Read what already exists: findings, outcome rows, `command_trail` / write-verify ledgers, `notification_log`, anomaly detector output, `room_transitions` (362k), `memory_episodes` (14,077), `memory_facts` (913), `metric_baselines`, `outcome_log`. Ground truth outranks display prose. No new instrumentation unless a probe shows a gap.

### 2.4 Loops

```
detect (goal at risk) -> hypothesize -> propose tool + predicted metric change
  -> record proposal durably -> (shadow or act) -> measure after window -> keep / revert
```

The working model is `WriteVerifier` (`energy_write_verify.py:131`): schedule a check, read back, revert on mismatch (`reversion_sweep :726`). The OC loop is the same shape with a goal metric in place of a register. Measure results go to `outcome_log` and fill `observed_effect` (F8). A scheduled job scores proposals from the durable table, replacing the rolling-list validator (F2). Measure windows must survive a restart, or be discarded cleanly if they can't.

### 2.5 Trust ladder, per action class

Same rungs as `const.py:3908`, applied per class:

| Rung | Behaviour | To promote |
|---|---|---|
| 0 Advisory | finding only | — |
| 1 Shadow | proposal recorded and scored | a scorer exists |
| 2 Propose | one-tap approve page | precision ≥ P over ≥ N samples spanning ≥ 7 days (extends `_compute_promotion_readiness :5103`) |
| 3 Act + tell | acts, tells you, auto-reverts on miss | your opt-in for that class |
| 4 Act quietly | digest only | your opt-in + sustained rung-3 precision |

- Promotion is never automatic. Demotion is automatic: a precision drop or a revert/no-op streak drops the class one rung and pages you.
- P/N default to code's 20 samples / 0.60. The critique argued for 80%. You choose (Q2).
- One card per class: rung, samples, precision, last action, blockers. The blocker reasons reuse `:5185-5209`.

---

## 3. Rooms as agents

> "the idea is that memory allows room to room communication and optimization"

**What a room agent is:** the existing room coordinator plus a belief stored in memory. It is not an LLM per room.

**What it decides (narrow):**
- its comfort/cost tradeoff inside the house goal bands
- pre-conditioning for a likely arrival, using a neighbour's episodes as a prior
- whether its own odd reading is a fault or normal

**What it knows:** its own facade answers (`baseline`, `episodes`, `unusual`, `facts`) plus neighbours via `_compose_locality` (`memory_facade.py:874`). That function returns zone siblings, but its `self_neighbors` source `_adjacency_cache` is never written. The 10-08 overnight note on the card (`:9382`) proposes populating it from `room_transitions` as the first slice. Rooms communicate through shared memory, not direct messages. That keeps it auditable and bounded by the compactor, and it respects the arch rule that locality is an answer, not a permission.

**How rooms coordinate:** rooms propose; the existing arbiters decide. HVAC zones arbitrate rooms that share a thermostat (one HVAC zone fans out to several house zones, by design). The ConflictResolver (`manager.py:86`) and the house coordinator handle cross-zone conflicts.

**Never delegated:** safety, security and arming, occupancy create/release, reserve floor (arch `:304-322`), and anything without an undo.

**Marginal-benefit check, still owed:** what does a room agent decide that room logic plus a memory query doesn't? The best candidate is the neighbour prior. Slice 3 measures it, and if it shows no lift, this section gets parked with that evidence.

---

## 4. Where an LLM fits

| Step | Deterministic | LLM |
|---|---|---|
| Detect against goals | yes | no |
| Group a log/finding storm into one incident | rules first | yes: one-sentence summary + likely cause, as a hypothesis |
| Propose a tool | lookup table for known classes | for unknown classes, rung ≤ 2 only. Today the LLM tier is the *only* source of `proposed_action` (`optimization_llm.py:1161`) |
| Record, score, revert, promote | always | never |
| Talk to you | templates | digest prose; "why did you do that" (hc plan's missing `llm_reasoning_summary`, `:22`) |

Reasons:
- **Determinism.** Scoring must be replayable.
- **Cost.** The existing 24-call/day cap (v2 `:386-415`) is enough for incidents, not for individual findings.
- **Failure modes.** Hallucinated causes and confident wrong tools. LLM proposals earn rungs exactly like rules do.

Reuse `OptimizationLLMTier`. Do not add a second LLM path.

---

## 5. First slice that would prove it

**Slice 1: the quiet goal (finding and alert noise) plus a working scorer.**
- Detect: finding classes with no goal link, or duplicates (the ~90%).
- Tool: mute/merge a class (reversible).
- Loop: propose → record durably → shadow-predict "volume −X%, no real fault hidden" → act after opt-in → measure.
- This forces the fix for OC-SHADOW-SAMPLES-EMPTY-1 (§1.3) and gives `observed_effect` its producer.

Success, in live numbers (targets for you to confirm):
- low-value share from ~90% to <30% of findings
- `optimizer_shadow_samples` (or its successor) > 0 and growing daily, with real non-sentinel values; precision shown on a dashboard
- ≥1 class at rung 2 with ≥ P precision over ≥ N samples
- discriminator: zero hidden faults. A muted class that later contained a confirmed `sensor_health/high` fault counts as a miss. sensor_health / never-fires / camera classes cannot be muted.

**Slice 2: stuck device or entry (reliability goal).** Generalize the HVAC reload tool. It builds on OC-STUCK-SENSOR-GENERALIZE-1 (`shipped_organic`, `kanban:3531`). It respects the off-WiFi limit (v2 App. C).

**Slice 3: neighbour prior (measure first).** A read-only probe over `room_transitions` and `memory_episodes`: does a neighbour's episode improve next-room arrival prediction over the room's own history? If yes, populate `_adjacency_cache`. This is the go/no-go for §3.

---

## 6. Non-goals, risks, what to retire

**Non-goals:**
- no autonomy in safety, security, occupancy create/release, or reserve floor
- no LLM in scoring or promotion
- no new write path
- no per-room LLM, no room message bus
- no automatic promotion

**Risks:**
- The loop floods itself. The quiet goal covers its own pages, and D9 caps its writes.
- Goal gaming: muting to hit the quiet goal hides real faults. Mitigated by the miss discriminator and the unmutable classes.
- Rare classes never reach N. They stay at rung 2, which still removes the chat.
- State × time seams: measure windows across restarts and TOU boundaries.
- **Blind detectors (F6) are not solved.** Goal metrics only catch a blind spot once the outcome degrades.
- Per-install goals are needed for multi-home rollout.

**Retire, via three-bucket triage, after slice 1 is live-validated:**
- **DELETE:** the rolling-list shadow validator (`optimization.py:1488-1560`). It is structurally dead and gives false confidence. Its storage stays.
- **DEMOTE to internal metrics:** user-facing `meta/low` and `prediction_accuracy/low` findings. Re-express `comfort/medium` as the comfort goal metric.
- **KEEP as kill switch + ceiling:** the coordinator-wide `optimizer_autonomy_level` (`const.py:3935`).
- **KEEP + DOCUMENT:** the stub dimensions (`const.py:4397`). Show them as "no scorer", never "ok".
- **KEEP:** sensor_health / never-fires / camera evaluators, the LLM tier, paging, the broker and veto handshake, the L2/L3 dispatch machinery.

---

## 7. Open questions for you

1. Goals: are comfort / cost / reliability / quiet right? What are your numbers?
2. Promotion: code says 20 samples / 60%, the critique says 80%. What precision would you trust per class?
3. Slice 1 = noise plus scorer. Or does Envoy blindness or the restart storms cost you more?
4. Rung 3 ("act and tell"): page per action, or a daily digest?
5. Rooms-as-agents: OK to gate it on the slice-3 measurement and park it if there's no lift?
6. LLM: incident summarizer only, or also proposals for unknown classes from day one (rung ≤ 2)?
7. Milestone: is "OC leaves shadow" the 6.x headline (the audit ranks it first), or a track parallel to identity?
