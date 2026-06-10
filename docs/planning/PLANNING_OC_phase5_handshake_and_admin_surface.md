# OC Phase 5 — Sibling Handshake Adoption + OC Observability & Admin Surface Redesign

**Status:** Draft. Supersedes the "Phase 5" section of `docs/planning/PLANNING_OPTIMIZATION_COORDINATOR_v2_agentic.md` only; the rest of v2 stays authoritative.
**Predecessor:** `PLANNING_OPTIMIZATION_COORDINATOR_v2_agentic.md` (Phases 1–4 = SHIPPED v5.0.0–v5.3.0/L1 Shadow, live).
**Operator request (2026-06-09, verbatim):** "a better design of the observability and admin surface for OC — what stays in config, what is mirrored on the OC, control selection for both, user friendly labels for text and for the controls. Look for hints in EC and HC. But any critique or improvement is welcome."

This doc carries two pillars: **Pillar A** = the original Phase 5 (sibling handshake adoption), **Pillar B** = the NEW operator-requested observability + admin-surface redesign.

---

## Tier classification

- **Pillar A (handshake adoption):** **Tier 2-DB elevated.** Triggers fire on principle ("standing 2026-06-08 policy: regression-prone work = three framing-disjoint reviews") — three coordinators gain an opt-in actuation-handshake path. Even at L1 Shadow this changes how vetoes/payloads are observed. The PLAN-v2 framings (A handshake/actuation safety, B autonomy/kill-switch integrity, C DB/LLM I/O) are reused with slight retargeting for Pillar A only — see "Reviews" below.
- **Pillar B (surface redesign):** **Tier 2** by default (no DB shape change, no actuation logic change), with operator option to elevate to Tier 2-DB if Pillar A and Pillar B ship together — see "Sequencing".

## Sequencing — Pillar B SHIPS FIRST (recommended)

**Recommendation: B before A.** Justification:

1. The operator's stated intent for the redesign is to "drive the rungs the handshake will obey." Phase-5 sibling adoption only matters once the rung is dialed above L1. Today the rung is locked at L1 (Shadow) because the autonomy surface is hard to use safely (raw enum tokens, missing translations, no guard on the rung select — a stray dashboard tap could push L5). Fix the surface FIRST so the operator can confidently drive autonomy; THEN wire siblings to obey it.
2. Pillar B is additive (labels, translation keys, sensor split, confirm-guard). It cannot regress shipped behavior. Pillar A touches three coordinators' actuation paths.
3. Pillar B's cosmetic status/findings disagreement fix (task #4 from 2026-06-09 pickup) and the ~10 missing translation keys (task #7) are real blockers TODAY — they should not wait on the larger Phase 5 review queue.

Concretely: Pillar B = one feature cycle, deploy. Pillar A = a separate feature cycle (Tier 2-DB) after Pillar B is live. If for any reason the operator wants them bundled, the combined cycle elevates to Tier 2-DB and both pillars review under the three framings; this doc supports either path.

---

## Institutional context verified

### Greps run + REUSED-vs-NEW

**Optimizer surface as shipped (v5.0.0–v5.3.0) — Pillar B inventory base**

- **CM-options keys (CONF_OPTIMIZER_*):** `CONF_OPTIMIZER_AUTONOMY_LEVEL`, `CONF_OPTIMIZER_KILL_SWITCH`, `CONF_OPTIMIZER_CONFIDENCE_GATE`, `CONF_OPTIMIZER_RATE_CAP_PER_HOUR`, `CONF_OPTIMIZER_QUIET_HOURS_SOURCE`, `CONF_OPTIMIZER_LLM_TASK_ENTITY`, `CONF_OPTIMIZER_LLM_TRIAGE_ENTITY`, `CONF_OPTIMIZER_LLM_SYSTEM_PROMPT`, `CONF_OPTIMIZER_LLM_MAX_INVOCATIONS_PER_24H`, `CONF_OPTIMIZER_SAFETY_DENY_ENTITIES`, plus per-dimension override dict `CONF_OPTIMIZER_DIMENSION_AUTONOMY`. All at `const.py:1525-1745`. REUSED for Pillar B (no new CONF keys added — see decision table).
- **Config-flow step:** `async_step_coordinator_optimization` at `config_flow.py:5593-5759`. REUSED — Pillar B reshapes this step into a **collapsed-section layout** mirroring `presence_timing` at `config_flow.py:4285-4339` (which uses `homeassistant.data_entry_flow.section`).
- **Device entities on `URA: Optimization Coordinator` device (identifiers `(DOMAIN, "optimization_coordinator")`):**
  - `OptimizerKillSwitch` (switch.py:3678-3791) — RestoreEntity-backed, restart-persistent, modeled on `EnergyObservationModeSwitch` (switch.py:400). REUSED.
  - `OptimizerAutonomyLevelSelect` (select.py:400-478) — 6-option select, options write-back. REUSED but its options list is changed to label/value pairs (Pillar B D2).
  - `OptimizerStatusSensor`, `OptimizerFindingsSensor`, `OptimizerRoomHealthSensor`, `RoomOptimizationHealthSensor` (sensor.py:13593-13811). REUSED; cosmetic D5 fixes here.
- **EC + HC precedent patterns (operator: "look for hints in EC and HC")**
  - `_ec_switch_factory(attr_name, unique_suffix, name, icon, default, unique_id_override)` at `switch.py:499-729`. Factory for EC toggle switches with `_attr_entity_category = EntityCategory.CONFIG` (line 535), deferred-restore retry chain (`_RETRY_DELAYS_S = (5, 30, 120)`, line 540), and `SIGNAL_ENERGY_COORDINATOR_READY` unbounded fallback (line 605). Twelve EC switches use this factory (`switch.py:732-790`+).
  - `EnergyObservationModeSwitch` at `switch.py:400` and `HVACObservationModeSwitch` at `switch.py:1682` — both RestoreEntity, both `entity_category=CONFIG`. The HVAC variant adds a `SIGNAL_HVAC_COORDINATOR_READY` deferred-restore wait (`switch.py:1782-1805`). REUSED PATTERN — Pillar B's confirm-guard wrapper for the autonomy rung mimics the deferred-restore shape (a "pending change" intermediate state with a separate apply step).
  - HVAC `presence_timing` collapsed config-flow section: defined `config_flow.py:4285-4339`, flattened on save `config_flow.py:3976-3981`, translation in `translations/en.json:992` ("Advanced — presence timing (rarely change)"). REUSED — Pillar B groups optimizer fields into 3 sections (Autonomy, Safety/Guards, LLM Tier-2) the same way.
  - EC reset/clear button precedent: `OccupancyWeightedPredictionSwitch` (`switch.py:765`) + `ECEvTouSwitchBase` (`switch.py:776`) show factory reuse for new toggles. v4.7.25 "Reset Presence Timer Knobs" button used the same options-strip pattern — REUSED concept for D4's "Reset Optimizer Settings" button.

- **Missing translation keys (known gap from 2026-06-09 pickup task #7).** Grepped `Optimizer|optimization_health|coordinator_optimization` in `translations/en.json` and `strings.json` — **zero hits**. ALL ~14 fields in `async_step_coordinator_optimization` (5+5+1 = 11 base + 4 entity strings) lack translations + helper text. NEW (Pillar B D3): full translation set + entity-strings under `entity.select.optimizer_autonomy_level.state.*` and `entity.switch.optimizer_kill_switch.*`.

**Pillar A — sibling adoption (re-verify base doc's REUSED citations post-v5.3.0)**

- `OptimizerIntentBroker.fire_intent()` / `await_veto()` / `suppress_climate()` / `unsuppress_climate()` at `optimization.py:217-489` (broker class) — **as-shipped, matches PLAN-v2's spec.** Veto TTL = 300s (`_VETO_TTL_SECONDS`), pending cap = 256, A-HIGH-2/3 eviction policies present. **REUSED** — sibling subscribers fire `SIGNAL_OPTIMIZER_INTENT_VETO` with `{action_id, vetoed_by}`.
- `SIGNAL_OPTIMIZER_INTENT`, `SIGNAL_OPTIMIZER_INTENT_VETO`, `SIGNAL_OPTIMIZER_FINDING_EMITTED` at `signals.py:157-159`. REUSED.
- `OverrideArrester.suppress(entity_id)` at `hvac_override.py:499-516`, TTL=5s. Still the canonical HVAC handshake — confirmed by `optimization.py:347-368` (broker calls it). REUSED.
- Sibling `observation_mode` properties — confirmed live at `energy.py:395`, `presence.py:189`, `security.py` (matches base-doc citation). REUSED as the natural opt-out lever.

### Prior planning docs consulted

- `PLANNING_OPTIMIZATION_COORDINATOR_v2_agentic.md` — base doc; this file supersedes only its "Phase 5" 4-line section.
- `PLANNING_v4.7.25_hvac_presence_timer_knobs.md` — collapsed section + reset button + options-as-source-of-truth pattern. Pillar B D2/D4 lift from here directly.
- `PLANNING_v4.7.24_substrate_unification.md` — Bug Class #50 (long-lived subs stored in a list cleared by periodic rebuild). Pillar B D5 sensor changes don't introduce new subscriptions, but the existing `_signal_unsubs` discipline at `sensor.py:13552, 13577` is preserved verbatim.
- `feedback_parsimonious_room_config.md` — "Show the full knob inventory before deploy for a pruning pass." Pillar B D1 IS that inventory.
- `feedback_configurability_clarity.md` — "named-bucket dropdowns + plain-English helper text over runtime Number entities for technical primitives." Drives D3 labels and D2's rung-as-prose-dropdown decision.
- `feedback_no_fabrication.md` — every REUSED claim above carries file:line.

### Memory bodies pulled

- `project_session_pickup_2026_06_09.md` — task #4 (status/findings cosmetic disagreement, fold into D5) + task #7 (~10 missing translation keys, fold into D3) + Phase 5 next.
- `project_optimizer_db_write_flood_incident_2026_06_09.md` — Pillar B MUST NOT add new per-cycle write channels. D5 reads existing `coord._open_findings_count` / `coord._last_findings`; no new DAOs. D5 fix is a DISPLAY change, not a new write path.
- `project_cm_reload_suppression_cycle_stack.md` — Pillar B options-writeback uses `async_update_entry` with options dict, no parent reload (the entity's `async_select_option` at `select.py:469` is already the right shape).
- `project_v4_7_25_hvac_presence_timer_knobs_live.md` — A-HIGH-1 lesson: bidirectional clamp at the config-flow validator (energy-saving ≤ normal). Pillar B applies the same shape for confidence_gate ≤ 1.0 already enforced by the selector, but ALSO adds a soft validator: "rate cap > 0 if rung ≥ L2" (D2).

### Design docs read

- `docs/Coordinator/COORDINATOR_ARCHITECTURE.md` — BaseCoordinator contract, device hierarchy.
- `docs/Coordinator/ENERGY_COORDINATOR_DESIGN_v2.3.md` — EC dual-surface precedent (CM-options + entity, with EC owning the runtime).
- `docs/Coordinator/HVAC_COORDINATOR_DESIGN.md` — `OverrideArrester` is the canonical handshake (re-confirms Pillar A REUSED claim).
- `docs/Coordinator/NOTIFICATION_MANAGER.md` — quiet-hours predicate consumed by `CONF_OPTIMIZER_QUIET_HOURS_SOURCE=reuse_nm`.

### Code locations surveyed end-to-end during scoping

- `domain_coordinators/optimization.py` (1-500, 200-490 broker; 3160-3260 score+summary surfaces).
- `switch.py` (400-790 EC factory + HC observation; 3666-3791 OptimizerKillSwitch).
- `select.py` (395-478 OptimizerAutonomyLevelSelect).
- `sensor.py` (13519-13811 — all five optimizer sensors).
- `config_flow.py` (3900-4339 HVAC presence_timing collapsed section; 5589-5780 optimizer step).
- `translations/en.json` (full grep for optimizer/optimization — zero hits; 975-993 hvac presence-timing helpers as the precedent template).
- `const.py` (1483-1815 entire optimizer block).

---

## Pillar B — OC observability + admin surface redesign

### D1: Full knob inventory + decision table (operator-pruning surface)

The operator-coined "parsimonious room config" rule mandates SHOWING the full knob list before deploy so they can prune. Below is the table; deliverable D1 is the **planning artifact** (it stays in this doc) — no code change.

| # | Knob | Domain | Today's surface | Proposed surface | Rationale |
|---|---|---|---|---|---|
| 1 | Autonomy rung (`CONF_OPTIMIZER_AUTONOMY_LEVEL`) | Autonomy | CM-options Select + `OptimizerAutonomyLevelSelect` entity | **BOTH** (config-flow primary) + entity **wrapped in confirm-guard** (D6) | Footgun — a dashboard tap could push L5. Entity stays for visibility + L0↔L1 toggling; L2+ requires confirm-button press. |
| 2 | Kill switch (`CONF_OPTIMIZER_KILL_SWITCH`) | Autonomy | CM-options Boolean + `OptimizerKillSwitch` entity (RestoreEntity) | **BOTH** (entity primary) | Operator needs to engage instantly from a dashboard. Entity is correct primary. Keep CM-option as the restore source. |
| 3 | Per-dimension autonomy (`CONF_OPTIMIZER_DIMENSION_AUTONOMY`) | Autonomy | CM-options dict only | **Config-flow only** (collapsed "Per-dimension caps" section) | Power-user feature; dashboard mirror would clutter; rarely changed. Visibility on status sensor `effective_level_per_dim` attribute. |
| 4 | Confidence gate (`CONF_OPTIMIZER_CONFIDENCE_GATE`) | Guard | CM-options Number slider | **Config-flow only** | Tuning knob — operator changes it rarely; dashboard tap could destabilize the rung's safety margin. Surface its CURRENT VALUE on status sensor attribute. |
| 5 | Rate cap (`CONF_OPTIMIZER_RATE_CAP_PER_HOUR`) | Guard | CM-options Number | **Config-flow only** | Same rationale as confidence gate. Current window count already on status sensor (`rate_cap_window_count`). |
| 6 | Quiet-hours source (`CONF_OPTIMIZER_QUIET_HOURS_SOURCE`) | Guard | CM-options Select | **Config-flow only** | Binary choice changed at install time. Quiet-active state visible on status sensor (`quiet_hours_active`). |
| 7 | Safety deny-list (`CONF_OPTIMIZER_SAFETY_DENY_ENTITIES`) | Guard | CM-options multi-select | **Config-flow only** | Power-user surface; mistaken entity addition from a dashboard is a footgun. |
| 8 | LLM primary entity (`CONF_OPTIMIZER_LLM_TASK_ENTITY`) | LLM | CM-options Select (discovered) | **Config-flow only** | Provider routing is install-time config. |
| 9 | LLM triage entity (`CONF_OPTIMIZER_LLM_TRIAGE_ENTITY`) | LLM | CM-options Select | **Config-flow only** | Same. |
| 10 | LLM system prompt (`CONF_OPTIMIZER_LLM_SYSTEM_PROMPT`) | LLM | CM-options multiline Text | **Config-flow only** | Live multiline editor — already correct (no dashboard mirror feasible; >255 char). |
| 11 | LLM cap/24h (`CONF_OPTIMIZER_LLM_MAX_INVOCATIONS_PER_24H`) | LLM | CM-options Number | **Config-flow only** | Cost control; rarely changed; visible on status sensor (new attr `llm_invocations_today`). |
| 12 | "Reset Optimizer to defaults" | Admin | Not present today | **NEW button entity** (D4) | One-tap recovery for misconfiguration. Strips optimizer CONF_* keys from `entry.options`. |
| 13 | "Run Optimizer cycle now" | Admin | Not present today | **NEW button entity** (D4) | Operator already requested ad-hoc trigger in past cycles; small surface, reuses `coord.async_request_refresh()`. |

**NET NEW CONF KEYS: 0.** Pillar B is purely a UX redesign over the shipped CONF surface. **NEW entities: 2 buttons** (D4). **CHANGED entities: 1 select** (D2 wraps it in confirm-guard) + **5 sensors** (D5 — display only).

Operator pruning pass: review the table; mark any "BOTH"/"Config-flow only" rows that should be "Entity only" or dropped. Outcome captured in the cycle README before D2 implementation begins.

### D2: Autonomy ladder dropdown — plain-English options + confirm-guard

#### Changes

- **Select options carry labels**, not raw tokens. `OptimizerAutonomyLevelSelect._attr_options` becomes a list of `{value, label}` dicts via the same SelectSelector label pattern used at `config_flow.py:4270-4273` (Pre-Arrival Sources). Values stay as the existing `OPTIMIZER_LEVEL_*` constants (no migration). Labels:

| Value (unchanged) | Label (NEW) |
|---|---|
| `advisory` | Observe only — no actions |
| `shadow` | Shadow mode — predicted actions, no actuation (default) |
| `reversible_device` | Reversible devices only — lights, fans, HVAC setpoints |
| `propose_config` | Propose config changes — 30s veto window |
| `immediate_config` | Apply config changes immediately — ±20% clamp |
| `unbounded` | Unbounded — no allowlist, no clamp (NOT RECOMMENDED) |

- **Confirm-guard for L2+ escalation.** `OptimizerAutonomyLevelSelect.async_select_option()` adds a two-step path when the requested option ranks ≥ L2 (`reversible_device`+) AND the current rank is L0 or L1: the select STORES the pending value into `entry.options[CONF_OPTIMIZER_PENDING_AUTONOMY_LEVEL]` and writes its own state to `pending_<target>`. The new `OptimizerConfirmEscalationButton` (D4) is the only way to commit; pressing it strips the pending key and writes the real key. A separate `OptimizerCancelEscalationButton` clears the pending key.
- Escalations from L2 → L3, L3 → L4 require the same confirm press. De-escalations (any → lower rank, including back to L1/L0) commit immediately.
- Restart resilience: the pending key persists across restarts; the select reflects `pending_<target>` on restore so the operator sees the pending escalation. Kill switch ENGAGE strips the pending key (no escalation can be in flight while killed).

#### Acceptance criteria

- **Verify:** From L1, selecting `reversible_device` writes `optimizer_pending_autonomy_level=reversible_device` to options; `OptimizerAutonomyLevelSelect.current_option == "pending_reversible_device"`; coord's `effective_level` remains `shadow`. Pressing `OptimizerConfirmEscalationButton` commits.
- **Verify:** From L2, selecting `advisory` commits immediately (de-escalation path).
- **Verify:** Engaging the kill switch while a pending escalation exists clears `optimizer_pending_autonomy_level`.
- **Test:** `test_autonomy_select_pending_escalation`, `test_autonomy_select_deescalate_commits_immediately`, `test_autonomy_confirm_button_commits`, `test_autonomy_kill_switch_clears_pending`.
- **Live:** In dashboard, change rung from Shadow to "Reversible devices only" — observe the rung display "Pending: Reversible devices only", then press the "Confirm escalation" button — rung changes to "Reversible devices only", `sensor.ura_optimizer_status.attributes.effective_level == reversible_device`.

### D3: Translation + strings.json — all ~14 fields + entity strings

Fill the documented gap. NEW translations cover BOTH `strings.json` and `translations/en.json` under:

- `options.step.coordinator_optimization.title` = "URA Optimizer"
- `options.step.coordinator_optimization.description` = "How autonomous should the Optimizer be? Start in Shadow mode and raise only after you trust its findings. The Kill Switch on the Optimizer device pauses everything instantly."
- `options.step.coordinator_optimization.data.optimizer_autonomy_level` = "Autonomy level"
- `options.step.coordinator_optimization.data_description.optimizer_autonomy_level` = "How far the Optimizer can act on its own findings. Default: Shadow mode (logs what it WOULD do, never acts). Raise one step at a time, watch the activity log, escalate when you trust it."
- `options.step.coordinator_optimization.data.optimizer_kill_switch` = "Kill switch (pause everything)"
- `options.step.coordinator_optimization.data_description.optimizer_kill_switch` = "When ON, the Optimizer is clamped to Observe-only. Survives restart. Use this when you need a fast brake."
- `options.step.coordinator_optimization.data.optimizer_confidence_gate` = "Confidence gate"
- `options.step.coordinator_optimization.data_description.optimizer_confidence_gate` = "Findings below this confidence stay advisory regardless of autonomy level. Higher = more cautious. Default: 0.70."
- `options.step.coordinator_optimization.data.optimizer_rate_cap_per_hour` = "Max actions per hour"
- `options.step.coordinator_optimization.data_description.optimizer_rate_cap_per_hour` = "Hard ceiling on autonomous actions per rolling hour. Anything past the cap falls back to Shadow until the window resets. Default: 12."
- `options.step.coordinator_optimization.data.optimizer_quiet_hours_source` = "Quiet-hours source"
- `options.step.coordinator_optimization.data_description.optimizer_quiet_hours_source` = "When 'Use Notification Manager quiet hours', the Optimizer clamps to Shadow during quiet hours so it never wakes you. 'None' ignores quiet hours."
- `options.step.coordinator_optimization.data.optimizer_safety_deny_entities` = "Always-skip entities"
- `options.step.coordinator_optimization.data_description.optimizer_safety_deny_entities` = "Entities the Optimizer must never actuate (any tier). Use for safety-critical switches and locks."
- LLM section labels: 4 keys for primary, triage, system prompt, daily cap.
- Two collapsed sections in `options.step.coordinator_optimization.sections`: `optimizer_guards` = "Safety guards (confidence, rate cap, quiet hours, deny-list)", `optimizer_llm` = "LLM Tier-2 reasoning (Claude / OpenAI / Ollama / Google)".
- Entity strings: `entity.select.optimizer_autonomy_level.state.*` (6 labels per D2), `entity.switch.optimizer_kill_switch.name` = "Kill switch", button names + helpers (D4).

#### Acceptance criteria

- **Verify:** Loading the URA Optimizer options step in Settings → Devices & Services shows section headers, plain-English field labels, and helper text under each control — no raw `optimizer_*` snake_case visible.
- **Test:** `test_translation_keys_present_for_optimizer_step` — load `translations/en.json`, assert ALL keys referenced by `async_step_coordinator_optimization` resolve.
- **Live:** Open the options flow; screenshot the step. Every field reads as English; every section header reads as English.

### D4: Buttons — Confirm escalation / Cancel escalation / Reset settings / Run cycle now

Four new button entities on the URA: Optimization Coordinator device. Modeled on the v4.7.25 "Reset Presence Timer Knobs" button (concept, not file:line — that button shipped as the cycle's D-step). All four use the `ButtonEntity` + `entry.options` mutation pattern; none touch the DB directly.

| Entity | Behavior | Available when |
|---|---|---|
| `OptimizerConfirmEscalationButton` | Commits `optimizer_pending_autonomy_level` → `optimizer_autonomy_level`; clears pending. | A pending key exists. |
| `OptimizerCancelEscalationButton` | Strips `optimizer_pending_autonomy_level`. | A pending key exists. |
| `OptimizerResetSettingsButton` | Strips ALL `optimizer_*` keys from `entry.options` (excluding `optimizer_kill_switch` to avoid releasing a tripped kill on accidental tap). | Always. |
| `OptimizerRunCycleNowButton` | Calls `coord.async_request_refresh()`. Rate-limited to one press per 30s (debounce inside the button). | Coordinator is loaded AND kill switch is OFF. |

#### Acceptance criteria

- **Verify:** Pressing Confirm with `optimizer_pending_autonomy_level=propose_config` writes the real key and clears pending within one cycle.
- **Verify:** Pressing Reset with kill switch ON does NOT clear the kill switch.
- **Verify:** Pressing "Run cycle now" twice in 10s only triggers one cycle (debounce).
- **Test:** `test_confirm_button_commits_pending`, `test_reset_button_preserves_kill_switch`, `test_run_cycle_button_debounces`.
- **Live:** Confirm escalation, observe sensor `effective_level` flip within one cycle; press "Run cycle now" and watch a new `last_evaluation` timestamp on the status sensor.

### D5: Status + Findings sensors — cosmetic disagreement fix + dashboard observability

#### Problem (carried from 2026-06-09 pickup task #4)

`OptimizerStatusSensor.extra_state_attributes` exposes `open_findings_count` and `house_score` computed over a **window aggregate** (`coord._open_findings_count`, `coord._house_score`), while `OptimizerFindingsSensor.extra_state_attributes['by_severity']` derives from the **latest cycle only** (`coord._last_findings[-20:]`). They can disagree when the window aggregate spans more than one cycle.

#### Fix

- **Status sensor speaks for the LATEST cycle only.** Replace `open_findings_count` with `last_cycle_findings_count` (derived from `len(coord._last_findings)`). Add `last_cycle_finished_at` (ISO) so the operator can tell whether the value is stale.
- **NEW attribute on status sensor:** `window_findings_count` (the old `_open_findings_count` value) AND `window_house_score` — keeps the windowed aggregate visible but plainly distinguished.
- **NEW attribute on status sensor:** `next_cycle_eta_seconds` — derived from `SCAN_INTERVAL_OPTIMIZATION` (300s) minus seconds since `last_cycle_finished_at`. Operator-facing observability.
- **NEW attribute on status sensor:** `last_action` — the last L2+ action that actually dispatched (read from `coord._last_findings` reverse-scan for `applied_outcome == "applied"`), with sub-fields `{action_id, target_entity, dimension, dispatched_at_iso}`. Empty dict at L1.
- **NEW attribute on status sensor:** `llm_invocations_today` (REUSED — already counted by Phase 2 LLM tier; surface it).
- **Findings sensor:** add `last_action_outcome_score` (the predicted-vs-actual score from the Phase 4 Prediction-Validation pillar, present today in `_last_findings[].observed_effect`). Cosmetic.

These are READ-ONLY sensor changes — NO new DB writes (incident-prevention rule from 2026-06-09).

#### Acceptance criteria

- **Verify:** After a cycle with 3 findings, `sensor.ura_optimizer_status.attributes.last_cycle_findings_count == 3`. After the next cycle with 0 findings, attribute == 0; `window_findings_count` may still be 3.
- **Verify:** `next_cycle_eta_seconds` decrements every state push; never negative for >5s.
- **Verify:** At L1 Shadow, `last_action` attribute is `{}` even when `last_cycle_findings_count > 0`.
- **Test:** `test_status_sensor_last_cycle_vs_window`, `test_status_sensor_next_cycle_eta`, `test_status_sensor_last_action_empty_at_l1`.
- **Live:** Force a sensor-health finding; observe `last_cycle_findings_count` increment immediately; observe `next_cycle_eta_seconds` count down from ~300.

### D6: Confirm-escalation guard implementation

Implementation details for D2's confirm-guard (separated so D2 reads as a UX spec and D6 as the wiring):

- New CONF key `CONF_OPTIMIZER_PENDING_AUTONOMY_LEVEL` (NEW). Lives on CM entry options. NULL when no pending.
- `OptimizerAutonomyLevelSelect._attr_options` extends to include `pending_advisory`, `pending_shadow`, etc. for state display only; they are FILTERED out of the dropdown options list so the operator can only select real rungs. The select's `current_option` returns the pending value when one exists.
- `OptimizationCoordinator.effective_level` continues to read from `CONF_OPTIMIZER_AUTONOMY_LEVEL` (NOT pending) — the coordinator never sees a pending state.
- Kill switch ENGAGE flow (`OptimizerKillSwitch.async_turn_on` at `switch.py:3780-3791`) appends an `entry.options[CONF_OPTIMIZER_PENDING_AUTONOMY_LEVEL] = None` clear.

#### Acceptance criteria

- **Verify:** A pending escalation persists across HA restart.
- **Verify:** `coord.effective_level` never returns `pending_*`.
- **Test:** `test_pending_autonomy_persists_restart`, `test_effective_level_ignores_pending`.

---

## Pillar A — Phase 5 sibling handshake adoption

### Re-verification of base-doc REUSED claims (post-v5.3.0)

All REUSED items the base doc listed for Phase 5 are confirmed live above (broker class, signals, arrester, sibling observation_mode properties). **No regressions, no NEW dependencies introduced by v5.0.0–v5.3.0.** Pillar A can build against the shipped broker as-is.

### D7: `honor_optimizer_intent(intent: dict) -> bool` on Energy / Presence / Security

- Each sibling coordinator gains an `async def honor_optimizer_intent(intent) -> bool` method. Default behavior:
  - **Energy:** veto when (a) the intent targets a switch/circuit currently inside an active load-shedding tier action; (b) the intent targets the EVSE during off-peak charging window; (c) `energy.observation_mode == True`.
  - **Presence:** veto when (a) intent target is a presence-input sensor (mmWave, occupancy) — Optimizer must never spoof presence inputs; (b) `presence.observation_mode == True`.
  - **Security:** Phase 1 = always veto any actuation on `lock.*` or `alarm_control_panel.*` (zero allowlist). `security.observation_mode == True` → veto everything (already correct).
- Each sibling subscribes to `SIGNAL_OPTIMIZER_INTENT` at `async_setup`, calls `honor_optimizer_intent`, and on `False` fires `SIGNAL_OPTIMIZER_INTENT_VETO` with `{action_id, vetoed_by: "energy"|"presence"|"security"}`. Subscription unsubs stored on `self._unsub_listeners` (Bug Class #50 discipline, per memory `project_v4_7_24_substrate_unification_live.md`).

### D8: L2 / L3 allowlist broadening — operator-staged

- L2 (`OPTIMIZER_ALLOWED_DOMAINS_DEVICE`): today `{light, switch, fan, cover, climate}` (`const.py:1569`). NO change in Pillar A.
- L3 (`OPTIMIZER_ALLOWED_DOMAINS_CONFIG`): today `{number, select}` (`const.py:1573`). NO change.
- The Pillar A broadening is **per-sibling opt-in** via `honor_optimizer_intent`'s default vetoes. Operator can later tighten or loosen per-sibling without changing the global allowlists.

#### Acceptance criteria

- **Verify (handshake):** A test intent targeting `switch.evse_l1_plug` during off-peak window is vetoed by Energy; finding records `applied_outcome=vetoed, vetoed_by=energy`.
- **Verify (handshake):** A test intent targeting `binary_sensor.master_bedroom_mmwave` is vetoed by Presence with `vetoed_by=presence`.
- **Verify (handshake):** A test intent targeting `lock.front_door` is vetoed by Security with `vetoed_by=security` (zero allowlist).
- **Verify (observation_mode):** Setting `presence.observation_mode = True` causes Presence to veto EVERY intent regardless of target.
- **Test:** `test_energy_honor_vetoes_evse_offpeak`, `test_presence_honor_vetoes_input_sensor`, `test_security_honor_vetoes_locks`, `test_observation_mode_blanket_veto`.
- **Live (must be done at L2 — operator-controlled escalation):** Dial Comfort dimension to L2 in dev test (controlled room); observe at least one `applied_outcome=applied` finding AND at least one `applied_outcome=vetoed` finding in `optimization_findings` within 24h; verify `vetoed_by` populated. (Per the standing "no soak watching" rule, this is a 1-hour controlled test, not a 24h watch.)

### Pillar A — review-pass contract deviation notes (2026-06-10 fix-up)

The three-framing Tier 2-DB review of the initial Pillar A build surfaced two contract notes worth keeping with the plan for future cycles:

- **Sync-vs-async veto delivery contract.** Sibling `_on_optimizer_intent`
  callbacks are synchronous (`@callback`). They run on the same event-loop
  turn that the broker's `fire_intent` dispatches on, so a veto pushed into
  `_pending_vetoes` is visible immediately after `fire_intent` returns. The
  Pillar A `_dispatch_device_action` / `_dispatch_config_action`
  flow MUST call `broker.await_veto(action_id, veto_window)` UNCONDITIONALLY
  after `fire_intent`, even when `veto_window == 0`, so the synchronous
  in-turn veto is harvested before the actuation runs. The zero-window
  branch of `await_veto` is a synchronous `_take()` against the dict — no
  sleep, no I/O — so the L2 ``reversible_device`` (non-propose) path keeps
  its no-delay character. (The earlier "veto_window > 0" guard caused
  silent advisory-only behavior at L2 — fixed in the fix-up pass.)
- **Operator awareness — observation_mode is a blanket veto.** Any sibling
  whose `observation_mode` is True will veto EVERY optimizer intent
  regardless of target. This is intentional (it lets the operator pause a
  sibling without disabling the optimizer), but it means dialing one
  coordinator into observation mode silently disables L2+ actuation. Surface
  this in the Pillar A cycle README under "Operator gotchas".

### Pillar A — reviews (Tier 2-DB, three framings)

| Framing | Focus (retargeted for Pillar A) |
|---|---|
| Review A — Handshake correctness + actuation safety | Every intent payload includes the action_class + effective_level so siblings can decide; veto eviction TTL still 300s; Bug Class #50 sub discipline on all three siblings; no path bypasses `honor_optimizer_intent`. |
| Review B — Sibling-state precedence + race conditions | Sibling can vote VETO even if its coordinator is mid-async-setup (sub timing); restart resilience of pending intents; observation_mode is read live, not cached; intent veto from a sibling that is itself in observation_mode is not double-counted. |
| Review C — Behavioral / live-validation authority | Test fixtures use real coordinators (not mocks) for the veto path; the live-validation table in the README requires evidence of at least one veto from each sibling within a controlled L2 test window. |

---

## Files modified or created

**Pillar B (no DB changes):**
- `custom_components/universal_room_automation/select.py` — `OptimizerAutonomyLevelSelect` gains label/value options + pending-state handling.
- `custom_components/universal_room_automation/button.py` — NEW `OptimizerConfirmEscalationButton`, `OptimizerCancelEscalationButton`, `OptimizerResetSettingsButton`, `OptimizerRunCycleNowButton`.
- `custom_components/universal_room_automation/sensor.py` — `OptimizerStatusSensor` + `OptimizerFindingsSensor` attribute changes (D5).
- `custom_components/universal_room_automation/config_flow.py` — `async_step_coordinator_optimization` reshaped into 3 sections; cross-field validator (rate cap > 0 when rung ≥ L2).
- `custom_components/universal_room_automation/const.py` — NEW `CONF_OPTIMIZER_PENDING_AUTONOMY_LEVEL` (single addition).
- `custom_components/universal_room_automation/translations/en.json` + `strings.json` — full translation block for the optimizer step + entity strings.

**Pillar A:**
- `custom_components/universal_room_automation/domain_coordinators/energy.py` — `honor_optimizer_intent` + `SIGNAL_OPTIMIZER_INTENT` subscriber.
- `custom_components/universal_room_automation/domain_coordinators/presence.py` — same.
- `custom_components/universal_room_automation/domain_coordinators/security.py` — same.

---

## Plan completion / deferral

- L2/L3 allowlist domain broadening — DEFERRED beyond Pillar A; per-sibling honor logic is the safer lever.
- Per-room dashboard tile / Lovelace card — NOT in scope. The status sensor's enriched attributes are sufficient for an operator-built card.
- Per-dimension autonomy override entity (mirror of the dict CONF) — DEFERRED; collapsed config-flow section is the single source.
