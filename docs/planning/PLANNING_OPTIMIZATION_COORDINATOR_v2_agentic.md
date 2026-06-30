# Optimization Coordinator — Implementation Plan v2 (Agentic-First)

**Status:** Draft (supersedes `docs/planning/PLANNING_OPTIMIZATION_COORDINATOR.md`)
**Target Version:** v4.7.x (≥ 3 cycles; first deployable cycle = Phase 1 alone)
**Tier:** Tier 2-DB — three framing-disjoint reviews REQUIRED. Justification below.
**Sibling docs:** v1 plan kept as historical baseline; do NOT delete. Bayesian audit findings (operator memo `015_v475_option_c_auto_mirror` / `016_v476_evse_solar_aware_charging_hybrid_self_modulates` / 2026-06-08 EV pickup) are inputs.

> **Intro note (revised 2026-06-08 per operator-final decisions):** This plan now ships a **SIX-rung autonomy ladder** (L0 Advisory → L1 Shadow/dry-run → L2 Reversible-device → L3 Config + veto → L4 Config immediate + bounded → L5 Unbounded). **Phase 1 ships with default = L1 (Shadow/dry-run)** — every cycle logs the action it WOULD take + predicted effect, scored against actual outcomes, with ZERO real actuation until the operator dials up. Config writes (threshold/parameter tweaks) begin at **L3**, not L2. The **LLM Tier-2 layer is built in Phase 2** (right after the deterministic loop), not at the end — Claude reasoning is designed-in from day 1 and reasons over the RAW substrate so it does not depend on the deterministic dimensions added in later phases.

---

## Operator-locked decisions (design to these — do not re-litigate)

1. **Lead with agentic optimization on the existing sensor substrate.** No standalone "health-score foundation" cycle first. Health monitoring is the *value lens* ("is everything working?"), but the first build delivers the optimizer/agentic loop on the substrate URA already produces. Health computation emerges by being the lens we evaluate findings against, not as a precondition.
2. **Full agentic, graduated — SIX-rung ladder (operator-final 2026-06-08).** Autonomy is a configurable LEVEL with a conservative default, escalatable as confidence grows, behind a global kill switch. Six rungs, ordered by increasing autonomy:
   - **L0 — Advisory:** flag/notify only; no actuation. Equivalent to the existing per-coordinator `observation_mode` semantics.
   - **L1 — Shadow / dry-run:** logs the exact action it WOULD take + the predicted effect; the predicted effect is scored against the actual subsequent outcome to build a track record. ZERO real actuation. **THIS IS THE v1 DEFAULT SHIP RUNG.**
   - **L2 — Reversible device actuation only** (operator's "option 3"): allowlisted service calls on devices with a defined revert (lights/fans/HVAC setpoints with snapshot-restore); **NO config / threshold writes at this rung**; every action emits an NM-notable notification.
   - **L3 — Config changes, propose + veto window** (operator's "option 1"): may tweak thresholds/config but fires the intent and auto-applies after a veto window (≥30s) unless a sibling coordinator vetoes; magnitude-capped (±20% numeric clamp).
   - **L4 — Config changes, immediate + bounded** (operator's "option 2"): veto window dropped; numeric tweaks clamped ±20%; rate-capped per the global rate cap.
   - **L5 — Full unbounded** (operator's "option 4"): kill-switch only — no allowlist, no clamp, no veto. NOT recommended for default use.

   Ship Phase 1 defaulting to **L1 (Shadow)**; dial higher per dimension as track-record warrants. The L2/L3 split (device-reversible vs config-write) is load-bearing — D2/D3 enforce it at the chokepoint.
3. **Direct actuation + handshake** (not suggest-only). The optimizer actuates devices directly BUT signals/handshakes with the owning coordinator so its writes aren't misread as user overrides or immediately reverted. REUSES the TTL-window suppression handshake (`OverrideArrester.suppress()/unsuppress()`, `domain_coordinators/hvac_override.py:499-516`, TTL = 5s, v4.7.33 A-F5). Generalises that pattern to a NEW `SIGNAL_OPTIMIZER_INTENT` so non-HVAC sibling coordinators can participate.
4. **LLM Tier-2 from the start — built in Phase 2 (operator-final 2026-06-08).** Claude reasoning is first-class and is delivered immediately after the deterministic Phase-1 loop, NOT deferred to the end of the roadmap. REUSES the existing `ai_task.generate_data` service-call pipeline (`config_flow.py:7951-7964`, `const.py:1281-1302` `AI_RULE_PARSING_PROMPT`). The LLM reasons over the **RAW substrate + the two Phase-1 dimensions (Sensor Health, Comfort)** — it does NOT depend on the additional deterministic dimensions added in Phases 3-5. Actions Claude proposes are gated by the SAME autonomy ladder + handshake — never unguarded.

---

## Tier classification — Tier 2-DB (operator-elevated, plus DB triggers fire)

**Why Tier 2-DB applies from Phase 1:**

- This coordinator actuates devices owned by HVAC, Energy, Presence and Security — the maximal cross-coordinator ripple surface in URA. By the standing 2026-06-08 policy ("regression-prone work = three framing-disjoint reviews"), this MUST be three reviews.
- Phase 1 adds a new DB table `optimization_findings` (anomaly-log-like shape) and a new write site, satisfying the explicit DB triggers in CLAUDE.md.
- **Phase 2 (LLM Tier-2) changes payload shape of `SIGNAL_OPTIMIZER_INTENT`** when adding LLM-source actions (the `created_by=tier2_llm` provenance lane on the dispatched intent) — second DB trigger fires in Phase 2.

**Three framings (run in parallel each cycle):**

| Framing | Focus |
|---|---|
| Review A — Cross-coordinator handshake + actuation safety | Does every actuation site `suppress()` the right entity, with the right TTL? Are sibling coordinators reliably told the action was URA-initiated? Conflict-resolver interactions. |
| Review B — Autonomy ladder + kill switch integrity | L0/L1/L2/L3/L4/L5 gating is correctly applied at EVERY actuation path; kill switch is honored synchronously AND persists across restart; no L2 path writes config; no L3+ path bypasses the allowlist/clamp; observation_mode generalization is consistent across coordinators. |
| Review C — DB schema + LLM I/O + cost cap | `optimization_findings` table preserves existing analytics shape; LLM token/cost cap enforced; prompt-cache stable parts versioned; structured-output validation rejects malformed JSON without silently dropping findings; `ai_task.generate_data` retry/timeout matches the v3.12.0 pattern. |

Live Validation (Review D) replaces the prospective acceptance bullets with a `Validated <date>` table per the 2026-06-05 README-writeback rule.

---

## Institutional context verified

This section is the proof-of-work that the planner consulted prior art before proposing. Reviewers verify it during Tier 2-DB review.

### NEW CONF_* tally (parsimony check — operator-final)

Phase 1 introduces the following NEW CONF_* keys on the **Coordinator-Manager entry only** (zero per-room CONF additions in Phase 1):

1. `CONF_OPTIMIZER_AUTONOMY_LEVEL` — global rung selector (6 options).
2. `CONF_OPTIMIZER_KILL_SWITCH` — global kill state (persisted; restart-resilient).
3. `CONF_OPTIMIZER_DIMENSION_AUTONOMY` — dict {dimension → rung} (per-dimension cap).
4. `CONF_OPTIMIZER_CONFIDENCE_GATE` — float 0.0-1.0; findings below threshold stay advisory regardless of rung.
5. `CONF_OPTIMIZER_RATE_CAP_PER_HOUR` — int; max autonomous actions per rolling hour.
6. `CONF_OPTIMIZER_QUIET_HOURS_SOURCE` — enum {`reuse_nm` | `none`}; when `reuse_nm`, autonomy clamps to L0/L1 whenever NM quiet hours are active (REUSED — see below).

Plus a single NEW per-room reader trio (existing entities, no new CONF surface): `comfort_temp_min/max`, `comfort_humidity_max` already-existing Number entities gain options write-back (D6). **Total NEW CONF on CM entry: 6. Total NEW per-room CONF: 0.**

Scope-ramp (room→zone→house) is INCLUDED but the **lowest-priority dial** and is collapsed into the per-dimension autonomy dict (no separate scope CONF surface) — this honours the operator's "do not let scope proliferate" rule.

### Greps run + REUSED-vs-NEW (every proposed constant, sensor, helper, signal)

**Autonomy / kill switch / quiet-hours surface**

- `CONF_OPTIMIZER_AUTONOMY_LEVEL` — NEW. Grepped `CONF_AUTONOMY|CONF_OPTIMIZER|CONF_AGENTIC` in `custom_components/universal_room_automation/` — no matches. The closest analog is the per-coordinator `_observation_mode: bool` (see below), but that is a binary, not a six-rung ladder. The plan generalises the pattern; the new CONF lives on the Coordinator Manager entry options (`ENTRY_TYPE_COORDINATOR_MANAGER`, `const.py:54`).
- Reused pattern: `observation_mode` flag. Live sites — `domain_coordinators/hvac.py:4556-4563` (property + setter), `domain_coordinators/energy.py:395, 4556-4563`, `domain_coordinators/presence.py:189, 305-312`, `domain_coordinators/security.py`, `domain_coordinators/safety.py`, `domain_coordinators/music_following.py`. Switch entities at `switch.py:396` (Energy), `switch.py:1678` (HVAC), `switch.py:1959` (Safety), `switch.py:2050` (Security), `switch.py:2141` (Presence). All use `RestoreEntity`. The Optimizer's L0 rung is "the same thing observation_mode means" (evaluate but never actuate). The ladder generalises it; L0 = observation_mode-equivalent; L1 (Shadow) extends it with predicted-effect logging + outcome scoring.
- `CONF_OPTIMIZER_KILL_SWITCH` — REUSED concept, NEW key. Maps to a Switch on the new Optimization Coordinator device modeled on `EnergyObservationModeSwitch` (`switch.py:396-480`). Kill switch flips autonomy to L0 synchronously AND **persists across restart** — when tripped, the persisted state survives an HA restart so a kill-switched optimizer stays kill-switched. Cancels in-flight intents and closes all `suppress()` TTLs via `unsuppress()`.
- `CONF_OPTIMIZER_CONFIDENCE_GATE` — NEW. No prior analog; closest is the Bayesian predictor's `data_quality_pct` (`bayesian_predictor.py`), which the gate consumes as ONE input but does not itself constitute. Default = 0.7; below this any finding's `proposed_action` is downgraded to advisory regardless of rung.
- `CONF_OPTIMIZER_RATE_CAP_PER_HOUR` — NEW. No prior rate-cap analog in URA today (grepped `rate_cap|rate_limit|max_per_hour` across `domain_coordinators/` — no general-purpose cap). Default = 12 (one per 5-min cycle worst case at L2+).
- `CONF_OPTIMIZER_QUIET_HOURS_SOURCE` — **REUSED** concept. NM already owns quiet hours: `CONF_NM_QUIET_USE_HOUSE_STATE`, `CONF_NM_QUIET_MANUAL_START`, `CONF_NM_QUIET_MANUAL_END` at `const.py:1167-1169` (+ translations at `en.json:1169-1182`). The Optimizer consumes NM's quiet-hours computed state via the NotificationManager singleton (`hass.data[DOMAIN]["notification_manager"]`) — does NOT add a parallel quiet-hours config. The single NEW CONF is the SOURCE selector: `reuse_nm` (default) or `none`. When `reuse_nm` is active AND NM says quiet, the optimizer's effective rung clamps to `min(configured, L1)`.

**Handshake / signals**

- `SIGNAL_OPTIMIZER_INTENT` — NEW. Grepped `domain_coordinators/signals.py` end-to-end (read 1-196); no existing optimizer-intent signal. Closest analog is `SIGNAL_DYNAMIC_PRESET_TRANSITIONED` (`signals.py:93`) which announces an HVAC state transition; the new signal carries an actuation INTENT before the call is made, so siblings can pre-acknowledge. Naming follows the `ura_*` convention.
- `SIGNAL_OPTIMIZER_FINDING_EMITTED` — NEW. For sensor refresh on new findings (parallel to `SIGNAL_REGIME_EVENT_EMITTED`, `signals.py:57`).
- `OverrideArrester.suppress(entity_id)` / `unsuppress(entity_id)` — REUSED at `domain_coordinators/hvac_override.py:499-516`. TTL window = 5s (`SUPPRESS_TTL_SECONDS`, `hvac_override.py:79`). The Optimizer wraps every HVAC actuation in `suppress()`/await/`unsuppress()` exactly as `_revert_override` does at `hvac_override.py:907-963`. v4.7.33 A-F5 hardening already covers multi-event settles from one logical write — the Optimizer inherits this for free.
- Generalising the handshake to non-HVAC coordinators: NEW. Energy / Presence / Security have NO equivalent of `OverrideArrester.suppress()` today (grepped `\.suppress\(` across `domain_coordinators/` — only HVAC has it). The plan introduces a thin `OptimizerIntentBroker` (see D2) that publishes `SIGNAL_OPTIMIZER_INTENT` before each actuation; sibling coordinators subscribe and opt-in to honoring or vetoing. This is additive — coordinators that don't subscribe simply continue current behavior (compliance tracker may flag the action; the Optimizer notes the unacknowledged write in its finding).

**Sensors / entities (per existing v1 plan §"Consumption Architecture")**

- `sensor.ura_optimizer_status`, `sensor.ura_optimizer_findings`, `sensor.ura_optimizer_room_health`, `sensor.ura_optimizer_zone_health`, `sensor.ura_optimizer_house_summary` — NEW. Grepped `ura_optimizer` — no matches in `sensor.py`. Device hierarchy reuses the v1-plan layout. `device_info` reuses the `BaseCoordinator.device_info` shape at `domain_coordinators/base.py:200-209` (`via_device=(DOMAIN, "coordinator_manager")`).
- Per-room `sensor.{room}_optimization_health` and per-zone `sensor.{zone}_optimization_health` — NEW. Same pattern as the dedicated per-zone v4.7.5 sensors. Phase 1 ships sensors with `state="(initializing)"` and populates them as the first cycle finishes — avoids a Bug Class #5 startup race.

**Findings + digest store**

- `optimization_findings` table — NEW. Grepped `optimization_findings|optimization_daily_digest` in `database.py` — no matches. Schema mirrors `anomaly_log` (already understood by reviewers; see `database.py:665`). DAO `log_finding()` modeled on `save_anomaly_event` at `database.py:4868-4948` (single-path writer, NULL-able metric columns, payload extras carried as JSON). New code uses `_create_table_safe` (`database.py:260`) to avoid Bug Class #9 corruption cascade.
- `optimization_daily_digest` table — DEFERRED to Phase 3 (per v1 plan §Daily Digest, renumbered). NM digest builder integration uses the existing morning/evening hooks (`CONF_NM_PERSON_DIGEST_MORNING/EVENING`) — REUSED.

**Notification surface**

- `NotificationManager.async_notify()` — REUSED at `domain_coordinators/notification_manager.py:652-672`. Severity → channel routing already implemented (Pushover / TTS / Companion). Optimizer calls with `coordinator_id="optimization"`, severity from finding, `source_anomaly_id=None` (the optional id is for anomaly correlation, which Phase 4 will exploit).
- NM **quiet-hours computed state** — REUSED. Optimizer reads NM's "is quiet now?" predicate (computed from `CONF_NM_QUIET_USE_HOUSE_STATE` / manual window) rather than re-implementing the time-window logic. Single source of truth.

**Per-room comfort sliders (v1 plan Appendix A — the orphaned consumer)**

- `ComfortTempMinNumber`, `ComfortTempMaxNumber`, `ComfortHumidityMaxNumber` — REUSED at `number.py:178, 214, 250`. Currently RAM-only (no `entry.options` write-back, no `RestoreEntity`). Phase 1 wires write-back inside the same cycle that introduces the Comfort dimension consumer — see D6. This closes the v1 plan Appendix-A orphan: the sliders gain a real reader (`OptimizationCoordinator._evaluate_comfort_dimension`) AND persistence in one cycle.
- Module constants `COMFORT_TEMP_MIN`, `COMFORT_TEMP_MAX`, `COMFORT_HUMIDITY_MAX` — REUSED at `const.py:872-875`. Stay as fallback defaults; Phase 1 reader prefers per-room slider value with constant fallback.

**Bayesian / accuracy inputs**

- `BayesianPredictor` (live, healthy) — REUSED at `bayesian_predictor.py:132`. The Optimizer's Prediction-Validation pillar (Phase 4) reads predictor accuracy via the existing data-quality and forecast surfaces, NOT by reimplementing the math.
- `BayesianPredictor.is_cell_stale()` — REUSED at `bayesian_predictor.py:969`. The Optimizer uses cell staleness to discount findings that depend on under-learned cells AND feeds it into the confidence gate.
- `RegimeDetector` — REUSED at `domain_coordinators/regime_detector.py:86`. Provides nightly regime-shift events the Optimizer can correlate with degradation findings.
- `ParameterBelief` / `COMFORT_DEFAULT_BELIEFS` — DESIGN-ONLY, zero code (operator audit 2026-06-07). If the Comfort dimension EVER learns per-room comfort bounds, it MUST reuse the live engine's conjugate-update math, `database.save_bayesian_beliefs()` / `database.load_bayesian_beliefs()` (`database.py:4610, 4643`), and `is_cell_stale()`. Per-room comfort learning is BACKLOG for the first build; the Phase 1 Comfort dimension reads the per-room slider with constant fallback, period.

**LLM client (Phase 2 — moved forward from Phase 5)**

- `ai_task.generate_data` — REUSED at `config_flow.py:7951-7964`. Service call with `structure=...` argument for typed JSON output. **Phase 2** calls this from `OptimizationLLMTier()._invoke_claude()` using a multi-section prompt assembled from a context-corpus dataclass. Reuses the v3.12.0 retry path's try/except shape and the `_AI_RULE_ALLOWED_DOMAINS` allowlist concept at `coordinator.py:685-690` (extended to include `notify`, `number`, `select` for optimizer actions). The structured-output schema is anchored to a dataclass — no free-text fall-through.
- Prompt-caching: HA's `ai_task` integration delegates to the user-selected conversation backend (Anthropic). Anthropic prompt-caching is a server-side parameter (`cache_control`); HA's `ai_task` service does NOT expose it today (verified — no `cache_control` param in the structure dict). Plan: emit the stable corpus sections as a single concatenated `instructions=` block with a `# === STABLE CONTEXT (cacheable) ===` marker so future HA versions / a thin custom wrapper can hoist them; until then, accept the per-call token cost but throttle Phase-2 invocations to once per Optimizer cycle (5 min) AND only when the finding set has actually changed (delta-trigger gate).

**Activity log / decision log**

- `ActivityLogger.log()` — REUSED at `activity_logger.py:49-80` (and `SIGNAL_ACTIVITY_LOGGED` at `signals.py:23`). Every optimizer action emits an activity log entry with `coordinator="optimization"`, `importance="notable"` for L2+ actuations, `"info"` for L0/L1 advisories + shadow-dry-runs.
- `DecisionLogger` / `ComplianceTracker` — REUSED via `BaseCoordinator` injection at `domain_coordinators/base.py:184-187`. Compliance tracker is already wired to flag commanded-vs-actual divergence; the optimizer reads its output as input to Config-Behavior dimension scoring (v1 plan §Room Health).

**Goal injection**

- `optimization_goals` table — NEW. Per v1 plan; modeled on the existing `ai_rules` storage shape (entry options + service call). The service call `universal_room_automation.add_goal` — NEW, additive registration in `__init__.py` (sibling to existing services). The config-flow step `async_step_optimization_goals()` — NEW step in CoordinatorManager OptionsFlow.

### Prior planning docs consulted

- `docs/planning/PLANNING_OPTIMIZATION_COORDINATOR.md` — the v1 doc this supersedes. Full read; the consumption architecture (per-zone/per-room sensors, NM digest hooks), the dimension catalog, and Appendix A's comfort-slider analysis are carried forward verbatim where untouched. The phasing is rescoped.
- `docs/planning/PLANNING_v4.7.18_dpm_drift_guard_and_cleanup.md` — DPM is the closest existing "system optimizes itself across the day" surface. Skimmed for the relax-ceiling / climate-norm patterns the Optimizer will eventually read; no overlap, but the Optimizer should observe (not duplicate) DPM's decisions.
- `docs/planning/PLANNING_v4.7.25_hvac_presence_timer_knobs.md` (and the per-room Knob inventory work) — operator-coined "parsimonious room config" rule applies. The Optimizer adds ZERO per-room config fields in Phase 1; the only new per-room reader is the existing comfort slider trio that Phase 1 wires up.
- `docs/planning/PLANNING_v4.7.6_evse_solar_aware_charging.md` — EVSE is one of the costliest cross-coordinator surfaces. Optimizer Phase 5+ will eventually propose tweaks here; Phase 1 explicitly excludes it from the L2 actuation allowlist (advisory only).
- `docs/planning/PLANNING_v4.7.8_egress_window_hvac_pause.md` — EgressManager creates a per-zone pause state (`hvac_egress.py:715` NM hook). Optimizer MUST check `EgressManager.is_paused(zone_id)` before any HVAC actuation (mirroring `hvac_override.py:1044`). Added as an explicit guard.
- `docs/planning/PLANNING_v4.7.12_anomaly_type_discriminator.md` — anomaly_log shape & write path; the Optimizer's findings table follows the same DAO pattern (single-path writer).

### Memory bodies pulled

- `project_v4_7_25_hvac_presence_timer_knobs_live.md` — parsimony rule; do not over-expose internal mechanisms as config.
- `project_cm_reload_suppression_cycle_stack.md` — CM reload suppression and options-write-back. The Optimizer's CONF surface lives on CM entry options; restore-from-options pattern matches v4.7.27.
- `project_v4_7_24_substrate_unification_live.md` — Bug Class #50 (long-lived subscription stored in a list cleared by a periodic rebuild). The Optimizer subscribes to `SIGNAL_OPTIMIZER_INTENT_ACK` and similar signals — store the unsubs on `self._unsub_listeners` (BaseCoordinator pattern) and DO NOT clear that list outside `_cancel_listeners`.
- `feedback_db_sensitive_3x_targeted_reviews.md`, `feedback_tier2db_for_regression_prone.md` — codifies why Tier 2-DB applies here.
- `feedback_no_fabrication.md` — every "this exists" claim above carries a `file:line`.
- `feedback_parsimonious_room_config.md` — Phase 1 ships ZERO new per-room CONF fields. Verified.
- `feedback_pre_deploy_zero_bugs_gate.md` — applies at deploy time, not planning.

### Design docs read

- `docs/Coordinator/COORDINATOR_ARCHITECTURE.md` — for BaseCoordinator contract.
- `docs/Coordinator/NOTIFICATION_MANAGER.md` — confirms `async_notify` is the right entry point for severity-routed alerts; AND confirms NM owns the quiet-hours computed predicate the Optimizer reuses.
- `docs/Coordinator/COMFORT_COORDINATOR.md` — historical (deprecated by operator 2026-06-07). Comfort lives here as a read-only scoring dimension, not as an actuating coordinator.
- `docs/Coordinator/HVAC_COORDINATOR_DESIGN.md` — confirms `OverrideArrester.suppress()` is the canonical HVAC handshake.

### Code locations surveyed end-to-end during scoping

- `domain_coordinators/base.py` (full read of L1-300) — BaseCoordinator contract, Severity enum, ActionType, ServiceCallAction shape.
- `domain_coordinators/signals.py` (full read 1-196) — exhaustive signal inventory.
- `domain_coordinators/hvac_override.py` (read 1-1389; full TTL handshake + AC reset paths).
- `domain_coordinators/manager.py` (relevant slice 230-303) — register_coordinator + setup ordering.
- `activity_logger.py` (1-80) — log() contract.
- `config_flow.py` (7895-8025) — `ai_task.generate_data` usage and prompt assembly.
- `const.py` (relevant slices 1265-1302) — AI_RULES + prompt const; (1166-1182) NM quiet-hours keys (REUSED by Optimizer).
- `number.py` (178-280) — Comfort sliders (orphan).
- `database.py` (relevant slices) — `log_activity`, `save_anomaly_event`, `_create_table_safe`, Bayesian DAOs.
- `bayesian_predictor.py` (125-225) — predictor init + restore.

---

## Mental model (delta from v1)

v1 read "Health Score → Findings → Optional Agentic Mode". v2 reads:

```
Existing substrate (per-room data + zone state + house state + activity_log + Bayesian +
compliance + anomaly + diagnostics)
                ↓
        Optimizer cycle (5 min)
                ↓
    [Tier-1 Rule Engine]  ───────────────┐
    deterministic rules over substrate;  │
    emits Findings with proposed actions │
                ↓                        │
    [Autonomy Matrix Gate]               │
    rung × per-dimension × confidence    │
    + rate-cap + quiet-hours + kill-sw   │
    L0 → log only (advisory)             │
    L1 → SHADOW: log + predicted effect, │
         score vs actual; NO actuation   │   ← v1 DEFAULT
    L2 → reversible device actuation     │
         (allowlist, snapshot-restore)   │
    L3 → config writes + veto window     │
    L4 → config writes immediate ±20%    │
    L5 → unbounded                       │
                ↓                        │
    [Handshake Broker]                   │
    SIGNAL_OPTIMIZER_INTENT fired ──→ Sibling coordinators ACK / VETO
    OverrideArrester.suppress() set     (HVAC reuses TTL handshake;
                ↓                        Energy/Presence/Security
    [Service Call]                        opt-in via SIGNAL_OPTIMIZER_INTENT)
                ↓                        │
    [Outcome Recorder] → optimization_findings DB + Activity Log
                                         │
    [Tier-2 LLM Layer] (Phase 2) ────────┘
    Reasons over RAW SUBSTRATE + Phase-1 dimensions (does NOT depend on
    Phase-3+ deterministic dimensions). Periodic structured-summary →
    ai_task.generate_data → findings + proposed actions
    gated by the SAME autonomy ladder + handshake (never unguarded)
```

Health scoring is the *evaluator* the rule engine and the LLM both use to grade findings. It is computed lazily on-demand from the substrate; it does not require its own foundation cycle.

---

## Phased delivery

### Phase 1 — Agentic Optimizer Skeleton + L0/L1 + Comfort/Sensor-Health dimensions (~1 cycle, ~700 LoC)

**Delivers an end-to-end agentic loop running at L1 (Shadow) by default with two dimensions live (Comfort, Sensor Health), the autonomy ladder + matrix gate + kill switch, the handshake broker, and the findings DB store.** No real actuation by default (L1 = shadow / dry-run: logs intended action + predicted effect, scores vs actual, but does NOT dispatch); the actuation path is wired but disabled until the operator dials L2+.

Why this scope: it proves the pipeline end-to-end (substrate read → rule eval → finding → DB → sensor → NM) with only the two dimensions whose data is unambiguously present today (sensor unavailability + comfort range). Phases 3-5 layer additional dimensions onto the same skeleton.

#### Deliverables

##### D1: `OptimizationCoordinator(BaseCoordinator)` + 5-min cycle

- New file `domain_coordinators/optimization.py`. Subclasses `BaseCoordinator` (`base.py:154`). `coordinator_id="optimization"`, `priority=5` (lowest — runs last in batches), 5-min cycle.
- Registered in `__init__.py` next to existing coordinators (`__init__.py:1898` pattern for Energy).
- Adds a new URA: Optimization Coordinator device (`device_info` via BaseCoordinator).
- Wires `decision_logger`, `compliance_tracker`, `anomaly_detector` (auto-injected by CM).

###### Acceptance Criteria
- **Verify:** New coordinator appears in `coordinator_manager._coordinators` after restart; logged `Coordinator optimization started` at INFO.
- **Sensor:** `sensor.ura_optimizer_status` exists with state `healthy` and attribute `mode` ∈ {advisory, shadow, reversible_device, propose_config, immediate_config, unbounded}.
- **Test:** `test_optimization_coordinator_registration` — asserts coordinator is registered, priority=5, BaseCoordinator contract methods present.
- **Live:** After restart, log line `Coordinator optimization started` present once; sensor `sensor.ura_optimizer_status.state == "healthy"` within 5 min.

##### D2: Autonomy Matrix (rung × per-dimension × confidence-gate + rate-cap + quiet-hours + kill switch)

The autonomy is a **matrix**, not a line. Priority order (operator-final 2026-06-08):

1. **rung × per-domain × confidence-gate** (CORE)
2. **rate-cap + quiet-hours** (CORE)
3. **kill switch** (CORE — well-considered, restart-persistent)
4. scope-ramp room→zone→house (LOWEST priority — collapsed into the per-dimension dict, no separate CONF surface)

Implementation:

- New CM-options field `CONF_OPTIMIZER_AUTONOMY_LEVEL` (Select: `advisory` | `shadow` | `reversible_device` | `propose_config` | `immediate_config` | `unbounded` — **6 options**). **Default = `shadow` (L1)** — Phase 1 ships in Shadow mode.
- New CM-options field `CONF_OPTIMIZER_KILL_SWITCH` (Switch entity on the Optimization Coordinator device). Default OFF (== "active"). When ON, autonomy clamps to L0 synchronously, in-flight intents are cancelled, suppression TTLs explicitly closed via `unsuppress()`. **State persisted via entry.options write-back AND `RestoreEntity` (belt-and-suspenders): the kill state survives an HA restart so a tripped switch stays tripped.**
- New per-dimension cap: `CONF_OPTIMIZER_DIMENSION_AUTONOMY` (dict per dimension → rung). Allows operator to run e.g. Comfort at L2 while keeping Energy at L1. Stored on CM entry options.
- New **confidence gate** `CONF_OPTIMIZER_CONFIDENCE_GATE` (Number 0.0-1.0, default 0.7). When a finding's `confidence < gate`, the finding stays **advisory** regardless of configured rung — proposed_action is downgraded to log-only and emitted as `applied_outcome=advisory_only` with reason `below_confidence_gate`.
- New **rate cap** `CONF_OPTIMIZER_RATE_CAP_PER_HOUR` (Number int, default 12). Rolling-hour window tracked in `_action_dispatch_history` deque. When cap hit, additional L2+ actions clamp to L1 (shadow) for the remainder of the window; rate-limit events emit an activity-log row.
- New **quiet-hours integration** `CONF_OPTIMIZER_QUIET_HOURS_SOURCE` (Select: `reuse_nm` | `none`, default `reuse_nm`). When `reuse_nm` and NM reports quiet hours active, the effective rung is clamped to `min(configured, L1)` — L0/L1 only during quiet hours. **REUSES** NM's quiet-hours predicate (`CONF_NM_QUIET_USE_HOUSE_STATE` + `CONF_NM_QUIET_MANUAL_START/END`, `const.py:1167-1169`). Zero new quiet-hours surface; the Optimizer reads the computed state from NM.
- **Crucial L2/L3 split:** L2 numeric clamp + allowlist applies ONLY to device actuation (reversible service calls on the allowlist). L2 cannot write config / thresholds — config writes begin at L3. The chokepoint enforces this with two separate dispatch paths (`_dispatch_device_action` vs `_dispatch_config_action`).
- L3+ numeric clamp: ±20% of current value, single-write-per-cycle per entity (mirrors v1 plan §Agentic Mode guardrails).
- L2 service-call allowlist (NEW constant `OPTIMIZER_ALLOWED_DOMAINS_DEVICE`) — DEFAULT subset of the v3.12.0 AI-rule allowlist for **reversible device actuation only**: `{light, switch, fan, cover, climate}`. The `number` / `select` domains are NOT on L2 — they are config writes and require L3+.
- L3+ config-write allowlist (NEW constant `OPTIMIZER_ALLOWED_DOMAINS_CONFIG`): `{number, select}`. Operator can extend via options.
- The ladder is enforced at a single chokepoint (`_apply_action` in optimization.py) — no path bypasses it.

###### Acceptance Criteria
- **Verify:** Setting `CONF_OPTIMIZER_AUTONOMY_LEVEL=advisory` causes zero `hass.services.async_call` invocations from `optimization.py` even when findings are emitted.
- **Verify:** Setting `CONF_OPTIMIZER_AUTONOMY_LEVEL=shadow` (default) causes zero `hass.services.async_call` invocations BUT activity-log rows for the predicted action exist (`action=shadow_dry_run`, `predicted_effect` field populated).
- **Verify:** At `reversible_device` (L2), an attempt to dispatch a `number.set_value` is REJECTED at the chokepoint with reason `config_write_requires_L3`; activity-log row records the rejection.
- **Verify:** Confidence gate — a finding with `confidence=0.5` emitted at `reversible_device` rung still results in `applied_outcome=advisory_only` (gate default 0.7).
- **Verify:** Rate-cap — the 13th L2 action in a rolling hour (cap=12) is dispatched as `shadow_dry_run` not as an actuation; activity-log row carries `reason=rate_capped`.
- **Verify:** Quiet hours — when NM reports quiet, effective rung is `min(configured, shadow)`. With `CONF_OPTIMIZER_QUIET_HOURS_SOURCE=none`, quiet hours are ignored.
- **Verify:** Flipping `CONF_OPTIMIZER_KILL_SWITCH` ON clamps `OptimizationCoordinator.effective_level` to `advisory` within one cycle, regardless of stored config.
- **Verify (restart-persistence):** Trip the kill switch, restart HA — after restart, `OptimizationCoordinator.effective_level == advisory` and `CONF_OPTIMIZER_KILL_SWITCH` reads ON; the kill state was NOT lost on restart.
- **Sensor:** `sensor.ura_optimizer_status` attribute `autonomy_level` reflects effective level (post-kill-switch, post-quiet-hours, post-rate-cap).
- **Test:** `test_optimizer_autonomy_clamp` — kill switch clamps to L0; `test_optimizer_l2_no_config_write` — L2 rejects `number.set_value`; `test_optimizer_l3_clamp_bounds` — L3 proposed value 30% above current is clamped to +20%; `test_optimizer_l2_allowlist` — service call to `recorder.purge` is rejected before dispatch; `test_optimizer_confidence_gate` — low-confidence finding stays advisory at L2; `test_optimizer_rate_cap` — 13th action clamps; `test_optimizer_quiet_hours_clamp` — NM quiet predicate clamps effective rung; `test_optimizer_kill_switch_persists_restart` — restart-resilient.
- **Live:** Flip switch in UI, observe log line `Optimizer kill switch ENGAGED, autonomy clamped to advisory`, then attempt to trigger a known-action finding and confirm zero service calls and an activity_log entry `coordinator=optimization, action=advisory_only`. Restart HA, confirm kill switch still tripped.

##### D3: Handshake Broker + `SIGNAL_OPTIMIZER_INTENT` (NEW signal; REUSES `OverrideArrester.suppress()`)

- New helper `OptimizerIntentBroker` in `optimization.py`. Two responsibilities:
  1. **Before** an L2/L3/L4/L5 actuation: fire `SIGNAL_OPTIMIZER_INTENT` with payload `{action_id, target_entity, service, service_data, source_dimension, proposed_at_iso, veto_window_s, action_class}` where `action_class ∈ {reversible_device, config_write}` (so siblings know whether they can veto a config write vs a device toggle). Wait `veto_window_s` (default 0 for L2/L4 immediate paths; ≥30s for L3 propose path) for any sibling coordinator to fire `SIGNAL_OPTIMIZER_INTENT_VETO` (NEW signal) matching `action_id`. If vetoed: log as `proposed_vetoed` finding; do not dispatch.
  2. **At** dispatch time: if target is a `climate.*` entity owned by a Zone, call `OverrideArrester.suppress(climate_entity)` to open the TTL window. Always pair with `unsuppress()` on error paths.
- L1 (Shadow) path: broker emits the intent payload but as a `shadow_dry_run` event — siblings can still observe + veto, but no service call is ever dispatched. This gives the LLM Phase-2 + sibling coordinators a real signal stream to learn against before any actuation goes live.
- HVAC owns climate; the broker accesses the arrester via `hass.data[DOMAIN]["hvac_coordinator"].override_arrester` (mirrors how `hvac_predict.py:521` already calls it).
- Non-HVAC siblings: subscribe at their `async_setup` to `SIGNAL_OPTIMIZER_INTENT` and decide per-coordinator whether to participate. For Phase 1, NONE participate; the signal fires unobserved. Phase 5 wires Energy + Presence subscribers.
- Activity log: every fire of `SIGNAL_OPTIMIZER_INTENT` writes an activity row with `importance=notable` for L2+ and `info` for L1 shadow, `action=optimizer_intent`.

###### Acceptance Criteria
- **Verify:** When the broker dispatches a `climate.set_temperature` call (L2+ rung; L2 disallows climate setpoint=config; this verify applies at L3+), `hvac_override.OverrideArrester._suppressed_until[entity]` carries a future timestamp (≥1s ahead); no false-positive override is recorded by the arrester for that write.
- **Verify:** `SIGNAL_OPTIMIZER_INTENT` payload includes ALL of {action_id, target_entity, service, service_data, source_dimension, proposed_at_iso, veto_window_s, action_class} — none NULL.
- **Verify (Shadow):** At L1, the broker emits the intent payload AND records `applied_outcome=shadow_dry_run` AND no service call is dispatched (assert via mock spy).
- **Test:** `test_optimizer_handshake_suppresses_hvac` — dispatch a fake climate write; assert arrester does not flag it. `test_optimizer_handshake_veto` — sibling fires VETO; assert dispatch is skipped + finding recorded as `proposed_vetoed`. `test_optimizer_shadow_emits_intent_no_call` — L1 emits + no dispatch.
- **Live:** Trigger a known L2 path (e.g. comfort-restore reversible device action in a controlled-test room), observe in HA logs: (a) `[Optimizer] Intent action_id=...` (b) NO `Override detected` line for the same entity (c) activity_log row `coordinator=optimization, action=optimizer_intent` with the action_id.

##### D4: `optimization_findings` DB table + DAO (NEW table; REUSES `_create_table_safe` + `save_anomaly_event`-shaped writer)

- New table `optimization_findings` created via `_create_table_safe` in `database.py` (`database.py:260` pattern):
  ```sql
  optimization_findings(
    id INTEGER PRIMARY KEY,
    timestamp TEXT NOT NULL,        -- ISO8601 UTC
    level TEXT NOT NULL,            -- room | zone | house
    target_id TEXT,                 -- room_name | zone_id | "house"
    dimension TEXT NOT NULL,        -- sensor_health | comfort | ... (StrEnum)
    severity TEXT NOT NULL,         -- low | medium | high | critical
    confidence REAL,                -- 0.0-1.0; feeds the confidence gate
    score REAL,                     -- 0-100 dimension score AT detection time
    description TEXT NOT NULL,
    proposed_action_json TEXT,      -- nullable; serialized ServiceCallAction
    action_class TEXT,              -- nullable; reversible_device | config_write
    applied_action_id TEXT,         -- nullable; set when broker dispatches
    applied_outcome TEXT,           -- nullable; one of {applied, vetoed, failed, advisory_only, shadow_dry_run, rate_capped, quiet_hours_clamped, below_confidence_gate}
    predicted_effect_json TEXT,     -- nullable; populated at L1 (Shadow) — what the action was predicted to change
    observed_effect_json TEXT,      -- nullable; populated post-cycle when shadow score-vs-actual lands
    payload_json TEXT,              -- extras (cell-staleness, snapshots, etc.)
    created_by TEXT NOT NULL        -- tier1 | tier2_llm | manual
  )
  ```
- Indexes: `(timestamp DESC)`, `(level, target_id)`, `(dimension, severity)`, `(applied_outcome)`. Mirrors anomaly_log index choices (`database.py:665`).
- DAO `log_finding(finding: OptimizationFinding) -> int` — single-path writer modeled on `save_anomaly_event` (`database.py:4868`). NULL-able metric columns honored; payload extras under `payload_json["extra"]`.
- Retention: `prune_optimization_findings()` — 30 days for `severity=critical`, 14 days for `high`, 7 days for `medium/low`. Same batched-DELETE shape as `prune_activity_log` (`database.py:4546`) to dodge Bug Class #25.

###### Acceptance Criteria
- **Verify:** After first cycle, table `optimization_findings` exists in `universal_room_automation.db`; ≥1 row written for sensor-health or comfort dimensions (or a "no_findings" sentinel — see D5).
- **Verify:** No NULL `severity` or `dimension` values; all `created_by` values are valid enum strings.
- **Verify (Shadow):** At L1 default, rows include populated `predicted_effect_json` and `applied_outcome=shadow_dry_run`.
- **Test:** `test_optimization_findings_dao_roundtrip` — write a finding, read it back, fields match; `test_optimization_findings_prune` — old low-severity rows pruned at the 7-day boundary.
- **Live:** SQLite query `SELECT count(*), severity FROM optimization_findings GROUP BY severity` within 24h shows non-zero counts AND no NULL severities. NULL-only result = payload shape broken (Tier 2-DB Review D sentinel-only check).

##### D5: Tier-1 Rule Engine (deterministic; Sensor-Health + Comfort dimensions only in Phase 1)

- Rule engine evaluates each room every cycle. Phase 1 ships TWO dimension evaluators only:
  - **Sensor Health:** Reads configured sensors per room from `entry.options`; for each, checks `hass.states.get(eid).state ∈ {unavailable, unknown}` for >60s. Emits `severity=high` finding per stuck sensor.
  - **Comfort:** Reads per-room ComfortTempMin/Max/HumidityMax slider value (D6 wires reader); compares to `room.data.temperature` and `room.data.humidity` when `room.data.occupied == True`. Emits `severity=medium` finding when out-of-range for ≥10 min sustained.
- Each finding carries a `confidence` (0.0-1.0) computed from: substrate freshness, dedup count, and (where applicable) Bayesian `is_cell_stale()`. The matrix gate (D2) consumes this.
- Rule engine has a "no findings" sentinel: emit one `severity=low, dimension=meta, description="cycle_ok"` row per cycle so Review-D can detect a silent-failure mode (no sentinels-only).
- Dimension scores computed lazily: `0` per emitted finding (worst-case), `100` if nothing emitted. Composite room-health-score = weighted average over phase-1 dimensions only; the score MEANING grows as phases add dimensions.

###### Acceptance Criteria
- **Verify:** A temperature sensor explicitly set to `unavailable` for >60s produces exactly one finding per cycle (not one per evaluation) — dedup keyed on `(room, dimension, entity_id)`.
- **Verify:** Setting `ComfortTempMax=74` on a room AND its current temp=75 AND occupied=True produces a comfort finding within ≤2 cycles (10-min sustained gate); the same room with default `ComfortTempMax=76` does NOT (proves slider override is read, per v1 Appendix A acceptance hook).
- **Verify:** Every finding has `confidence` populated in (0.0, 1.0].
- **Sensor:** `sensor.{room}_optimization_health` attribute `degraded_dimensions` contains `comfort` or `sensor_health` when respective findings fire; state reflects the composite score.
- **Test:** `test_rule_engine_sensor_health_unavailable` and `test_rule_engine_comfort_per_room_override` — both gated on the same fixture room.
- **Live:** Force a known sensor unavailable in HA dev tools; observe per-room sensor `sensor.master_bedroom_optimization_health.attributes.degraded_dimensions` includes `sensor_health` within 1 cycle.

##### D6: Wire per-room ComfortTempMin/Max/HumidityMax sliders (REUSES `number.py:178-280`; CLOSES v1 plan Appendix A)

- Add `entry.options` write-back to all three Number `async_set_native_value` methods (mirroring the v4.7.25-27 CM options-writeback pattern). Keys: `comfort_temp_min`, `comfort_temp_max`, `comfort_humidity_max`. NEW CONF keys (per-room) — these are the ONLY per-room CONF additions Phase 1 makes, and they correspond to entities that already exist (so no new config-flow surface, just persistence).
- Add seed-from-options in `__init__` of each Number (fallback chain: `entry.options[key]` → existing instance default `COMFORT_TEMP_MIN/MAX/HUMIDITY_MAX` module constants).
- New helper `OptimizationCoordinator._read_per_room_comfort(entry) -> dict` returns `{min: float, max: float, hum_max: float}`. The Comfort rule (D5) calls this helper exclusively — never reads the module constants directly.
- NOT REUSED here: `RestoreEntity` — the options write-back IS persistence (v4.7.27 pattern). Adding RestoreEntity is redundant; mirrors the v4.7.27 decision.

###### Acceptance Criteria
- **Verify:** After setting `number.master_bedroom_comfort_temperature_max=74` and restarting HA, the entity restores `74` (not the `COMFORT_TEMP_MAX=76` constant).
- **Verify:** `entry.options["comfort_temp_max"] == 74` after the set.
- **Test:** `test_comfort_slider_options_writeback` — set value, reload entry, assert value persisted; `test_comfort_slider_seed_from_options` — set option, fresh entity, value seeds from options.
- **Live:** Set Master Bedroom Comfort Max to 74 in UI; restart HA; entity reads 74 post-restart; force occupied + 75°F → comfort finding fires.

##### D7: Sensors + NM wiring (REUSES per-room/zone/house device hierarchy from v1 plan; REUSES `NotificationManager.async_notify`)

- New platform sensors:
  - `sensor.ura_optimizer_status` (Optimization Coord device): state ∈ {healthy, degraded, critical, paused}; attrs `autonomy_level`, `effective_level`, `mode`, `house_score`, `open_findings_count`, `last_evaluation`, `rate_cap_window_count`, `quiet_hours_active`.
  - `sensor.ura_optimizer_findings` (Optimization Coord device): state = latest finding description; attrs `findings: list[20]`, `by_severity`, `by_level`.
  - `sensor.ura_optimizer_room_health` (Optimization Coord device): state = worst room score; attrs `rooms` map.
  - `sensor.{room}_optimization_health` (each Room device): state = score; attrs as v1 plan §Room Level.
- `SIGNAL_OPTIMIZER_FINDING_EMITTED` (NEW) — dispatched on each new finding; sensors subscribe at `async_added_to_hass`. Pattern: `SIGNAL_REGIME_EVENT_EMITTED` (`signals.py:57`). Store unsubs in `self._unsub_listeners` to avoid Bug Class #50.
- NM integration: severity={critical, high} → `async_notify(coordinator_id="optimization", severity=Severity.HIGH, title=..., message=..., hazard_type=None, location=room_name)`. medium → companion app digest only (Phase 3 adds digest queue write).

###### Acceptance Criteria
- **Verify:** A critical sensor-health finding triggers exactly one `async_notify` call within the cycle it fires (dedup keyed on `(room, dimension, severity)` for cooldown).
- **Verify:** All five+per-room sensors register at integration setup; no `Setup of platform sensor is taking over 10 seconds` warnings.
- **Test:** `test_optimizer_sensor_subscriptions_survive_rebuild` — explicitly checks the Bug Class #50 hazard (a periodic rebuild does NOT clear the optimizer's signal unsubs).
- **Live:** Force a critical finding; observe Pushover notification with the URA Optimizer title and the finding description; sensor `sensor.ura_optimizer_findings.state` matches the finding.

##### D8: Activity Log + Decision Log integration (REUSED)

- Every L1 Shadow predicted action: `activity_logger.log(coordinator="optimization", action="shadow_dry_run", importance="info", details={dimension, action_id, target_entity, service, level, predicted_effect})`.
- Every L2+ proposed action: `activity_logger.log(coordinator="optimization", action="proposed", importance="notable", details={dimension, action_id, target_entity, service, level})`.
- Every L2+ dispatched action: `activity_logger.log(coordinator="optimization", action="actuated", importance="notable", details={...})`.
- Every veto: `activity_logger.log(coordinator="optimization", action="proposed_vetoed", importance="notable", details={..., vetoed_by})`.
- Every rate-cap / quiet-hours / confidence-gate clamp: `activity_logger.log(coordinator="optimization", action="clamped", importance="info", details={..., reason})`.
- DecisionLogger.log_decision integration — same fields, allows the operator's existing decision-log sensors to surface optimizer activity.

###### Acceptance Criteria
- **Verify:** After 1h of operation at L1 default, `ura_activity_log` contains rows with `coordinator=optimization, action=shadow_dry_run`; importance levels correct.
- **Test:** `test_optimizer_activity_log_shadow`, `test_optimizer_activity_log_proposed`, `test_optimizer_activity_log_vetoed`, `test_optimizer_activity_log_clamped`.
- **Live:** SQL `SELECT count(*), importance FROM ura_activity_log WHERE coordinator='optimization' GROUP BY importance` within 24h shows ≥1 row.

---

### Phase 2 — LLM Tier-2 (provider-agnostic via `ai_task.generate_data`) (~1 cycle, ~600 LoC)

**Moved forward from Phase 5 per operator-final 2026-06-08.** Built immediately after the deterministic Phase-1 loop, before Phase-3 dimension expansion. The LLM reasons over the **RAW substrate + the two Phase-1 dimensions** — it does NOT depend on the additional deterministic dimensions added in Phases 3-5.

**Provider-agnostic + cost-controlled (operator requirement 2026-06-08).** `ai_task.generate_data` routes to whichever AI Task entity it's given — so provider choice is a config selector, NOT code. Live HA already exposes four: `ai_task.claude_ai_task`, `ai_task.openai_ai_task`, `ai_task.google_ai_task`, `ai_task.ollama_ai_task` (local). Two NEW CM-options keys:
- `CONF_OPTIMIZER_LLM_TASK_ENTITY` (Select over discovered `ai_task.*` entities; default `ai_task.claude_ai_task`) — the primary reasoning backend.
- `CONF_OPTIMIZER_LLM_TRIAGE_ENTITY` (Select, default = same as primary, recommend `ai_task.ollama_ai_task`) — an OPTIONAL cheap/local backend for the per-cycle "is anything here worth deep analysis?" triage pass. Only when triage flags something does the premium primary backend get called. This is the largest cost lever: routine cycles cost $0 (local Ollama), premium spend only on cycles that actually surface something.

**Cost levers (stacked):** (1) provider selection incl. local Ollama = $0; (2) cheap-triage → premium-deep routing; (3) delta-trigger gate (only call when finding-set changed); (4) hard daily invocation cap; (5) <8KB corpus + structured output keep tokens small. Caps are per-backend so a local backend can run uncapped while the paid one stays bounded.

Periodic batch (default: once per Optimizer cycle when finding-set delta ≥ 1). Pipeline:

1. **Context corpus assembly** — dataclass `OptimizerContextCorpus`:
   ```
   - house: {state, census_summary, energy_summary, security_posture, safety_active}
   - zones: list[{zone_id, preset, setpoints, room_conditions, override_count_today, runtime_seconds}]
   - rooms: list[{room_name, occupancy, temp, humidity, power, comfort_score, last_action}]
   - findings_recent: list[OptimizationFinding] (last 24h, capped at 50)
   - goals_active: list[{kind, target, period, priority}] (built-in + user-injected)
   - bayesian_accuracy: {brier, hit_rate, data_quality_pct, regime_status}
   - prior_actions: list of last 20 optimizer actions + outcomes
   ```
   Note: the corpus draws from the RAW substrate (room data, activity log, anomaly log, Bayesian summary). No dependency on Phase-3+ deterministic dimensions — adding them later EXTENDS but never INVALIDATES the corpus shape.
2. **Structured summary** — pre-LLM compression to <8KB. Token-cap enforced (REUSED concept from v3.12.0 ai_rules — no exact cap exists today; NEW constant `OPTIMIZER_LLM_CONTEXT_MAX_TOKENS=8000`).
3. **LLM invocation** — `hass.services.async_call("ai_task", "generate_data", {entity_id: <CONF_OPTIMIZER_LLM_TASK_ENTITY>, task_name: "ura_optimizer_findings", instructions: prompt, structure: OPTIMIZER_LLM_STRUCTURE}, blocking=True, return_response=True)`. The `entity_id` comes from config (provider-agnostic), NOT hardcoded. Mirrors `config_flow.py:7951`. Prompt assembly = the system prompt (below) + the serialized corpus under a `# === STABLE CONTEXT ===` / `# === CURRENT SNAPSHOT ===` split.
4. **Prompt-cache prep** — single instructions block with `# === STABLE CONTEXT ===` marker. Documented limitation: HA `ai_task` does not surface Anthropic `cache_control` today; the marker is forward-compat scaffolding.
5. **Structured output** — schema: `{findings: [{dimension, severity, confidence, target_level, target_id, description, proposed_action_or_null}], reasoning: str}`. Validate via dataclass; reject malformed JSON without silently swallowing.
6. **Gating** — every proposed_action flows through the SAME autonomy ladder + matrix gate (rung × dimension × confidence-gate + rate-cap + quiet-hours + kill switch) + handshake broker. No bypass path. LLM-source findings are tagged `created_by=tier2_llm` and pass through Phase-1's chokepoint unchanged. **Payload shape change:** dispatched intents now carry `created_by` provenance lane — this is the Phase-2 DB trigger that justifies the Tier 2-DB review framing.
7. **Cost cap** — NEW constant `OPTIMIZER_LLM_MAX_INVOCATIONS_PER_DAY=24` (one per hour worst case). Configurable on CM options.

Phase 2 acceptance includes the Tier 2-DB Review C focus: token cap honored, structured-output schema rejects malformed JSON, cost cap enforced, `created_by=tier2_llm` provenance preserved through the chokepoint, AND provider-switch works (swap `CONF_OPTIMIZER_LLM_TASK_ENTITY` to `ai_task.ollama_ai_task`, confirm findings still parse).

#### System prompt (v0 draft — 2026-06-08; iterate before build, store as `OPTIMIZER_LLM_SYSTEM_PROMPT` in const.py)

The prompt MUST be provider-portable (no Anthropic-specific phrasing) since it may run on Ollama/OpenAI/Google. v0:

```
You are the Optimization Analyst for a Home Assistant whole-home automation
system (URA). You receive a structured snapshot: current home/zone/room state,
the CONFIGURED intent for each (what it is supposed to do), recent findings,
active goals with priority, prediction-accuracy stats, and your own prior
actions with their measured outcomes.

Your job: surface problems and opportunities the deterministic rule engine
misses — degraded/stuck sensors, phantom or missed occupancy, configuration
that contradicts observed behavior, comfort/energy/cost sub-optimality,
coordinators working at cross-purposes, and predictions that have drifted.

Rules:
- Ground EVERY finding in the snapshot. Cite the specific value(s) that justify
  it. If the data does not support a finding, do not invent one.
- Only reference entities, rooms, zones, and config keys that appear in the
  snapshot. Never name anything not present.
- For each finding you MAY propose ONE concrete corrective action, expressed
  only as a service call on an entity in the snapshot and within the provided
  allowlist. Prefer reversible actions. If unsure, propose no action.
- Respect active goals and their priority. Never propose anything that violates
  a safety or security goal.
- Be conservative: a wrong autonomous action is worse than a missed finding.
  When uncertain, lower the severity and propose no action.
- Output ONLY the structured schema. Keep `reasoning` to one short paragraph.

severity: critical = safety/security or "running blind"; high = clear
malfunction or significant waste; medium = sub-optimal but functioning;
low = minor/informational.
confidence: 0.0-1.0, your calibrated certainty the finding is real AND the
snapshot supports it. Findings below the operator's confidence gate are dropped
before any action — so calibrate honestly, do not inflate.
```

The corpus (current snapshot) is appended after this prompt. The allowlist and
active goals are injected into the snapshot, not hardcoded in the prompt, so
they stay operator-configurable. Treat this as a starting point — prompt
tuning is part of the Phase-2 build + Review C.

#### Prompt management — disk-loaded, per-model, visible (operator requirement 2026-06-08)

The prompt is NOT a code constant. It is loaded from a disk markdown file so it can be tuned without a redeploy, and so per-model variants can co-exist and be fed by provider selection.

**Prompt storage — LEAN (operator-trimmed 2026-06-08: "expensive" — no file subsystem, no sync).**

- **One editable prompt, stored in URA, persisted.** Held in the CM config-entry options, edited via a single multiline Options-Flow field. Persists across reboot natively; it is the runtime source of truth. (Not a `text` entity — HA caps entity STATE at 255 chars; the multiline options field has no such limit.)
- **Base/default = a single in-code constant** (`OPTIMIZER_LLM_SYSTEM_PROMPT`, the v0 above). **Reset = clear the field → falls back to the const.** That constant IS the recoverable base. NO disk file, NO per-model variant library, NO reset-from-disk button, NO dedicated prompt sensor, NO file sync/watcher.
- **Two-tier resolution at call time:** live edited prompt (entry.options) → const v0 default. Always have a prompt; never crash.
- **Provider-portable** by default — one prompt across Claude/Ollama/OpenAI/Google. Per-model prompt variants are DEFERRED; add a second stored prompt only if a backend diverges enough in practice to warrant it.
- **NEW config:** 1 key — the prompt text in entry.options (edited via the multiline step). (Drops the earlier `PROMPT_FILE`/`PROMPT_VARIANT` keys; LLM tally returns to the 2 provider-entity selectors + the prompt field.)
- **Institutional check for the builder:** grep for any existing disk-load / file-read helper before adding one (URA prompts today are code constants — `AI_RULE_PARSING_PROMPT` at `const.py:1281`; this is the first disk-loaded prompt, so the loader is NEW — confirm no prior art).

---

### Phase 3 — Dimensions expansion + Daily Digest (~1 cycle, ~500 LoC)

(Formerly Phase 2.) Adds Occupancy-Accuracy, Automation-Responsiveness, Config-Behavior, Energy-Efficiency dimensions (room-level); Setpoint-Compliance, Vacancy-Mgmt, Override-Frequency (zone-level); State-Machine-Accuracy, Security-Posture (house-level). Adds `optimization_daily_digest` DB table + NM digest hook integration. Findings volume becomes visible — autonomy still defaults to L1 (Shadow); per-dimension caps allow targeted L2/L3 escalation.

Acceptance criteria pattern matches Phase 1 (per dimension: explicit fixture + sensor attribute + live signature).

---

### Phase 4 — Prediction Validation pillar + Bayesian / Regime integration (~1 cycle, ~400 LoC)

(Formerly Phase 3.) Reads `BayesianPredictor` accuracy summary (already exposed as data-quality + Brier hit-rate, healthy as of 2026-06-08), `RegimeDetector` events, `DailyEnergyPredictor` accuracy. Adds a Prediction-Accuracy dimension at each level. Cell-staleness (`is_cell_stale`) discounts the score weight of dimensions backed by under-learned cells AND feeds the confidence gate. NO new Bayesian learner — strictly a reader.

---

### Phase 5 — Sibling-coordinator handshake adoption + L2/L3 broadening (~1 cycle, ~400 LoC)

(Formerly Phase 4.) Energy + Presence + Security each subscribe to `SIGNAL_OPTIMIZER_INTENT` and add a `honor_optimizer_intent(intent) -> bool` method. Adoption order driven by where the Optimizer most needs actuation: HVAC (Phase 1 already supports via suppress); Energy (load-shedding interactions, EV pause); Presence (rare — e.g. force room vacant on stuck-sensor advisory); Security (no actuation; ack-only). Expands L2 device allowlist + L3 config allowlist gradually with operator approval.

---

## Risks (top three for executive summary)

1. **Cross-coordinator actuation regression.** The Optimizer touches climate, lights, switches, fans owned by HVAC / Presence / Energy. A subtle handshake bug could cause flap or duplicate actuation. Mitigation: Tier 2-DB three-framing review; explicit `OverrideArrester.suppress()` reuse (battle-tested as of v4.7.33); broker is the single chokepoint; non-HVAC siblings DON'T act on intents in Phase 1 (additive only); Phase 1 ships at L1 (Shadow) so any wiring bug produces log-only artefacts, not real actuation.
2. **Autonomy escalation by default.** Operator may dial L2/L3 broadly before track-record warrants. Mitigation: default L1 (Shadow) produces a real predicted-vs-actual track record before any actuation; per-dimension autonomy cap (D2); ±20% numeric clamp at L3+ + tight domain allowlists (device vs config split); kill switch (restart-persistent); rate-cap + quiet-hours; every L2+ action emits NM-notable + activity-log entry; sentinels-only findings in DB are a live-validation alarm.
3. **LLM cost + hallucinated actions.** Phase 2 (moved forward) could blow up API spend or propose nonsensical actions. Mitigation: hard daily invocation cap; delta-trigger gate (only call when findings set changed); structured-output schema rejects malformed; every LLM-proposed action flows through the SAME autonomy matrix gate (LLM cannot bypass clamp/allowlist/confidence-gate/rate-cap/quiet-hours); LLM-source findings tagged `created_by=tier2_llm` for analytical separation.

Secondary risks (kept short):
- DB growth on `optimization_findings` if Phase 3 dimensions explode false-positive rate — retention + dedup mitigations in D4/D5.
- Bug Class #50 recurrence on the new sensors' signal subs — explicit `_unsub_listeners` discipline noted in D7.
- Comfort-slider write-back interacting with Bug Class #46 (`async_update_entry` re-entrancy) — D6 uses the v4.7.27 sole-source pattern that already cleared this hazard.

---

## Plan completion / deferral accounting

Items from v1 plan that this v2 plan **defers** (must be tracked, not silently dropped):

| v1 item | Status in v2 | Where to track |
|---|---|---|
| Phase 1 (v1) "Room Health Score" as a foundation cycle | RESCOPED — health emerges; first build leads agentic | This doc D1-D8 |
| Per-room comfort Bayesian learner (ParameterBelief / COMFORT_DEFAULT_BELIEFS) | DEFERRED — backlog; reuse live engine when wired | Backlog memo to file post-Phase-1 |
| Zone-level dimensions (Setpoint-Compliance, Vacancy-Mgmt, etc.) | DEFERRED to Phase 3 | This doc Phase 3 |
| House-level dimensions (State-Machine-Accuracy, etc.) | DEFERRED to Phase 3 | This doc Phase 3 |
| Prediction Validation pillar | DEFERRED to Phase 4 | This doc Phase 4 |
| Weekly Report | DEFERRED to Phase 3 / Phase 2 (LLM prose) | This doc |
| User goal injection (config-flow step + service call) | DEFERRED to Phase 5 | This doc Phase 5 |
| Optimizer device aggregate sensor `sensor.ura_optimizer_zone_health` | Phase 1 D7 ships placeholder; populated Phase 3 | This doc |

Items that this plan **explicitly EXCLUDES from Phase 1** (parsimony):
- Per-room runtime config knobs for the Optimizer (none added in Phase 1 beyond the comfort-slider write-back for existing entities).
- Per-room/per-zone autonomy-level overrides (CM-level only in Phase 1; per-dimension caps cover the spread; scope-ramp room→zone→house collapsed into the per-dimension dict, no new CONF surface).
- Action-rollback history beyond what `ura_activity_log` already provides.

---

## Files this plan will modify or create

**Created:**
- `custom_components/universal_room_automation/domain_coordinators/optimization.py` — coordinator + rule engine + broker (Phase 1).
- `custom_components/universal_room_automation/domain_coordinators/optimization_llm.py` — LLM Tier-2 wrapper (**Phase 2**, moved forward from Phase 5).
- `docs/readmes/README_v<version>.md` (per release).
- Future: `docs/reviews/code-review/v<version>_optimization_coordinator.md` (per release).

**Modified:**
- `custom_components/universal_room_automation/__init__.py` — register OptimizationCoordinator next to existing register sites (`__init__.py:1898` pattern).
- `custom_components/universal_room_automation/const.py` — new constants (autonomy levels, dimension StrEnum, allowed-domains DEVICE + CONFIG split, signal names if local, LLM caps, confidence gate, rate cap, quiet-hours source enum).
- `custom_components/universal_room_automation/database.py` — new `_create_table_safe("optimization_findings", ...)` block + `log_finding` DAO + `prune_optimization_findings` (Phase 1); `optimization_daily_digest` (Phase 3).
- `custom_components/universal_room_automation/domain_coordinators/signals.py` — `SIGNAL_OPTIMIZER_INTENT`, `SIGNAL_OPTIMIZER_INTENT_VETO`, `SIGNAL_OPTIMIZER_FINDING_EMITTED`.
- `custom_components/universal_room_automation/number.py` — Comfort sliders gain options write-back + seed-from-options.
- `custom_components/universal_room_automation/sensor.py` — new optimizer sensors (Optim device, per-room).
- `custom_components/universal_room_automation/switch.py` — new `OptimizerKillSwitch` modeled on `EnergyObservationModeSwitch` (`switch.py:396`); RestoreEntity-backed for restart persistence.
- `custom_components/universal_room_automation/select.py` — new `OptimizerAutonomyLevelSelect` (Select entity, **6 options**).
- `custom_components/universal_room_automation/config_flow.py` — new options-flow section on CM entry for autonomy level + per-dimension caps + confidence gate + rate cap + quiet-hours source + LLM caps (Phase 1); per-room reads added when comfort sliders' options-writeback wires up (D6).
- Sibling coordinator files (Phase 5 — formerly Phase 4): `energy.py`, `presence.py`, `security.py` — add `SIGNAL_OPTIMIZER_INTENT` subscribers.

---

## Pre-deploy hooks (pre-deploy zero-bugs gate)

Per `feedback_pre_deploy_zero_bugs_gate.md`:

```bash
# Conflict markers
git grep -n '<<<<<<<\|=======\|>>>>>>>' custom_components/

# Syntax
python3 -m py_compile custom_components/universal_room_automation/domain_coordinators/optimization.py
python3 -m py_compile custom_components/universal_room_automation/database.py
python3 -m py_compile custom_components/universal_room_automation/sensor.py
python3 -m py_compile custom_components/universal_room_automation/number.py

# Suite + cycle tests
PYTHONPATH=quality python3 -m pytest quality/tests/ -v

# Baseline diff
git diff pre-review-v<version>..HEAD
```

---

## Live Validation table (populate post-restart per 2026-06-05 README-writeback rule)

(To be filled in by the validator agent post-deploy. Prospective acceptance lives in each D# block above; observed results go here as `PASS / FAIL / as-expected` rows with concrete evidence.)

| Criterion | Observed | Source |
|---|---|---|
| (TBD post-deploy) | | |

---

## Appendix C: Candidate future capability — offline-actuator self-recovery (deferred here 2026-06-30)

**Origin.** AV-closet light failed to auto-on/auto-off (2026-06-30). Root cause was a dead Shelly relay (`unavailable`/`restored:true` since restart — a WiFi/network event took ~dozens of Shelly/Sonoff devices offline), NOT URA code or config. A URA room cannot actuate an `unavailable` entity, so it failed silently. Three follow-ups came out of it (full write-up: `docs/BACKLOG.md` → "Offline-actuator visibility + recovery"):
- **D1 — visibility** (shipped/standalone Tier 1): `sensor.<room>_unavailable_entities` extended to include actuators (lights/fans/covers/climate), with structured per-entity detail (`roles`, `category`, `state`, `reason` incl. `offline_since_restart`, `since`). Was previously inputs-only, so a dead relay was invisible.
- **D2 — reconcile-on-return** (under study, separate): re-assert URA's *current intent* when an actuator transitions `unavailable → available`. Tracked outside this plan.
- **D3 — reload-as-recovery: PARKED HERE.** Operator (2026-06-30) deferred D3 to a *possible* future extension of this coordinator. See below.

**Why D3 belongs to the Optimization Coordinator, not a standalone heuristic.** A naive "auto-reload any unavailable device" is dangerous and was nearly discarded: reloads tax the event loop (cf. the v5.0.0–v5.2.1 DB write-flood incident + rollback), integration provenance is uncertain (HA-native vs HACS — some HACS integrations reload badly, and there are integrations we have *deliberately killed* where auto-reload would worsen things), and **this session proved a reload does NOT revive a device that is genuinely off-WiFi** (only the rare "device online but HA connection wedged" case benefits — which HA's own coordinator retry already largely covers). That thin value against real blast-radius is *exactly* the kind of guarded, cross-coordinator actuation the OC already builds machinery for: the **autonomy ladder** (default L1 Shadow), the **handshake broker**, the **kill switch**, **rate-cap + quiet-hours**, and **NM-notable** surfacing. D3 should only exist as an OC action subject to all of those — never as a free-standing auto-reloader.

**Required safety pattern (precision + performance — design to these before any build, else discard):**
1. **Per-entry targeted reload only** — `homeassistant.reload_config_entry` for the ONE owning config entry; never a blanket/all-entries reload (blinks every working device).
2. **Provenance allowlist** — only HA-native integrations (or an explicit operator allowlist); HACS/known-fragile/deliberately-killed integrations excluded by default.
3. **Recoverability gate** — attempt only when the device is plausibly reachable (e.g. recent `last_seen`/link-quality, or a reachability probe), so we don't reload a device that's physically off-network (proven useless this session).
4. **Single-shot per outage** — at most one reload attempt per device per unavailability episode; NO retry loop. Re-arm only after the device has been seen available again.
5. **Rate-capped + daily-capped + quiet-hours** — reuse the Phase-1 D2 rate-cap + quiet-hours machinery; a per-house global cap on reloads/hour.
6. **Behind the kill switch + autonomy level** — sits at ~L2 (reversible device action) at most; default OFF; an L1-Shadow rung must log "would reload X because Y" and score it before any real reload is enabled.
7. **Observable** — every attempt emits an `optimization_findings` row + activity-log entry + (optional) NM nudge, so a bad/ineffective reload is greppable (operator's hard-to-troubleshoot concern).

**Status:** design-only idea, **deferred**; not part of Phases 1–5 as currently specced. If pursued, slots as a new OC action/dimension (Phase 3 dimensions expansion or Phase 5 sibling-adoption). **Operator may discard** if the D1 visibility surface (which makes the dead device *visible* for a one-tap manual reload) proves sufficient in practice.
