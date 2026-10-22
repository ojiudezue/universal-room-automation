# VISION — The Optimization Coordinator as a self-fixing house (rev 3)

Card: `OC-SELF-OPTIMIZING-HOUSE-REDESIGN-1` (Tier 3, thread optimization). Folds in `OC-SHADOW-SAMPLES-EMPTY-1` (operator 10-17: first slice) and the residual of `OC-STUCK-SENSOR-GENERALIZE-1`. Gates on `HVAC-OPTIMIZER-CLIMATE-FUNNEL-ROUTING-1`.
Status: vision for operator approval. Not a build plan; each slice gets its own plan and plan review.
Rev 1 2026-10-21. Rev 2 2026-10-21 adds operator input: goals (§3), room memory (§2 part F, §5), and honest request contracts (§7). Rev 3 2026-10-21 (operator: "use the Coordinators' paths vs request"): §7 replaced by "use the owning coordinator's existing path"; no unified request API. Evidence for rev 2 is `docs/planning/AUDIT_room_memory_and_coordinator_request_apis_2026_10_21.md`.
I read `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` in full before writing §7, and nothing here re-asserts a claim from its §10 ledger.

**Operator framing (binding).** "Optimization coordinator is meant to diagnose the house and self fix it. It's supposed to reason over issues in the house." Correction 10-16: the OC never acted *by operator choice*, because the operator sensed the noise. Shadow mode was a deliberate trust withhold. So the failure is signal quality, and the right to act has to be earned by measured precision the operator can see. Rev 2: "To make OC reason better, it needs goals."

---

## 1. What the OC is today, and why it has not earned trust

**Its parts** (all in `domain_coordinators/optimization.py` unless noted):

- A 5-minute cycle (`run_cycle`, :1015) runs about 14 dimension evaluators: comfort, sensor_health, occupancy_accuracy, prediction_accuracy, camera_stuck, never-fires, camera_input_dark, and others. Each produces `OptimizationFinding`s (:226).
- An LLM tier (`optimization_llm.py`, `created_by=tier2_llm`) reasons over a truncated snapshot.
- A six-rung autonomy ladder (`const.py:4100-4123`): advisory, **shadow** (live value, CM options `optimizer_autonomy_level: shadow`), reversible_device, propose_config, immediate_config, unbounded. It has a per-dimension cap, confidence gate, rate cap, quiet hours, kill switch and safety deny-list (`_check_safety_denylist` :4221).
- A battery-reserve hard deny (:4514) and an intent/veto handshake that Energy, Presence and Security honour.
- A shadow-accuracy validator (:1449) feeding `_compute_promotion_readiness` (:5180). That output is shown only as a sensor attribute (`sensor.py:18403`).
- **The OC has no notion of what the operator wants.** Every dimension carries the same weight.

**Measured today** (live URA DB, read-only, 2026-10-08 to 10-22 UTC):

| Measure | Value |
|---|---|
| Finding rows, 14 days | **5,305** (about 640/day since 10-14; 10-09..10-13 ran 8-39/day, cause not investigated) |
| Distinct (dimension, target) pairs | **72**. Four problems make up about 80% of rows |
| `meta` "cycle_ok" sentinel | 2,199 rows (41%), one heartbeat per cycle |
| `prediction_accuracy` "top-1 hit-rate 21.1% < 35%" | 1,980 rows (37%), **one** problem re-emitted every cycle |
| `comfort` (room) | 655 rows over 8 rooms in the last 7 days. Jaya Bedroom alone: 359 |
| `sensor_health` | 353 rows over 32 targets (7 days) |
| LLM findings | 122. Most say it cannot see the cause ("findings truncated", "operator is running blind") |
| Rows with a proposed action / applied / observed effect | **0 / 0 / 0** |
| `optimizer_shadow_samples` rows, ever | **0** |

**Why it has not earned trust:**

1. **It reports cycles, not problems.** No dedup survives across cycles or restarts. One unchanged fact (prediction skill is low) produced 1,980 rows. 10-21 evidence: the never-fires detector found 7 sensors, all verified truly silent, with 0 false findings. Yet each one was re-reported after every HA restart (4 times in 10 hours), because its `("sensor_never_fires", eid)` dedup key lives in memory. The finding was correct and the delivery was noisy.
2. **It has no scored track record.** The validator scores only `self._last_findings` (:1498). Those are replaced by the current cycle just before it runs (:1231), and it requires findings to be 900 s old (`const.py:4176`). So nothing is ever old enough, and 0 samples exist. Fixing that alone would still score little, because tier-1 findings carry no proposed action (`_consider_apply` :4895 stamps "no proposed action emitted").
3. **It has no goals, so it cannot rank.** Since "Jaya Bedroom 1 °F warm" and "a sensor is dead" carry equal weight, both are noise.
4. **It does not reason across signals.** Five room-score findings caused by one dead device stay five findings.
5. **Its precision is invisible.**

---

## 2. The target: a house that diagnoses and fixes itself

| Part | What it is | REUSE / NEW |
|---|---|---|
| **A. Goals** (§3) | A ranked set of canned goals the operator picks, with optional bounds. They rank problems, choose between fixes and appear in every explanation. | NEW selects. Bounds REUSE existing knobs. |
| **B. Problems, not findings** | A persistent `problem` record keyed by a stable fingerprint (kind, subject, cause, episode). It holds first/last seen, count, evidence, state (open → acknowledged → fixing → verifying → resolved / wont_fix) and the goal it hurts. Evaluators **update** problems instead of inserting rows. Survives restart. | REUSE `dedup_key` (:246), the evaluators, `_persist_findings_batch` (:5109), `_filter_repeat_sensor_health` (:5047). NEW: the problem table/DAO, with the kanban card lifecycle shape. |
| **C. Reasoning across coordinators** | A root-cause pass that links child problems to a parent (one dead device explains five room problems). Deterministic joins first; the LLM gets the deduped, goal-ranked list, not a truncated snapshot. | REUSE `optimization_llm.py`, `AnomalyDetector` (`coordinator_diagnostics.py:981`), `RoomDwellModel` (`room_dwell_model.py:92`). NEW: the linking. |
| **D. A toolbox ranked by reversibility** (§4) | A fixed catalogue of fix types, each with an owner, a revert and a verifier. The OC proposes a fix type plus arguments, never a free-form service call. | REUSE the ladder's device/config split, `_clamp_numeric_to_band` (:4152) and the denylists. NEW: the catalogue. |
| **E. Autonomy earned per fix type** | Each fix type climbs the existing ladder on measured precision, shown on a scoreboard. Promotion is an operator tap; demotion is automatic. | REUSE `CONF_OPTIMIZER_DIMENSION_AUTONOMY`, `_compute_promotion_readiness`, `optimizer_shadow_samples`. CHANGE: key by fix type, score problems. |
| **F. Memory as evidence; verify-and-rollback loops** (§5) | The OC becomes Hierarchical Entity Memory's first automated consumer, for diagnosis and verification only. Every applied fix arms a verifier using memory's `outcome()`, then passes, or reverts and pages. | REUSE `MemoryFacade` (7 verbs, `memory_facade.py:367-941`), `memory_episodes`, the `observed_effect_json` / `applied_outcome` columns, NM. NEW: `outcome()` implementation, OC episode types. |

The operator surface is one page: active goals; open problems ranked by goal impact, each with evidence, cause and the goal it hurts; a precision scoreboard per fix type; and promote/demote buttons. NM sends problem state changes only, never cycles.

---

## 3. Goals

**Canned list.** The operator selects and ranks up to five:

| Goal | Optional bound | Maps onto EXISTING policy (REUSE) |
|---|---|---|
| Save energy / money | monthly bill cap ($) | TOU engine, arbitrage, `energy_peak_buffer_target`, billing (`energy_billing.py`), HVAC energy-saving vacancy delay (knob 49) |
| Maximize comfort | comfort band (°F) | HVAC Seasonal Baseline ranges (`hvac_baseline_*`), per-room ComfortTempMin/Max sliders (`number.py`), comfort grace (knob) |
| Quiet nights | quiet-hours window | NM quiet hours (`nm_quiet_*`, `nm_quiet_use_house_state`), house Sleep state |
| Protect battery / grid independence | minimum SOC (%) | `energy_reserve_soc`, inclement floor, `hvac_comfort_soc_floor_pct` |
| Keep devices healthy | — | sensor_health, never-fires, camera_stuck dimensions |

**Rule: goals do not duplicate knobs.** A goal never writes an energy or HVAC knob by itself. It is a **ranking lens**. The optional bound is read from the existing knob where one exists (the comfort band is the active Seasonal Baseline; the minimum SOC is `energy_reserve_soc`). Only the bill cap and the goal ranks are NEW values.

**How goals are used:**
- **Ranking problems:** impact = how much the problem costs the goals it hurts, weighted by goal rank. A problem that hurts no selected goal goes to the digest, not NM.
- **Choosing between fixes:** when two fixes conflict (pre-cool for comfort vs hold for money), the higher-ranked goal wins, within the other goal's bound.
- **Explanations:** every problem and fix states its goal, as in "Ranked #2 because it hurts *Maximize comfort* (Jaya Bedroom 2.1 °F above band for 40 min)".

**Knob ladder:** five `select.ura_optimizer_goal_rank_<n>` entities (rung 3, live-tunable, persisted; "none" = slot empty). The bill cap is a Number entity (rung 3; 0 = no cap). Kill switch: all slots "none" means the OC falls back to unranked behaviour, which is rev-1 behaviour.

**Slice:** goal selection and display land in **slice 1** (every problem is tagged with the goal it hurts). Goal-weighted ranking and fix choice land in **slice 2**.

---

## 4. What "self fix" means here, concretely

Ordered by reversibility. The "Route" column says whose code performs the fix (see §7).

| # | Fix type | Real instance | Route | Automate? |
|---|---|---|---|---|
| 1 | **Open or update a problem / card** | never-fires sensors; zone_1 manual strands | OC-owned | **First.** |
| 2 | **Page the operator with one deduped, evidenced ask** | dead AV Closet relay; S10 latch NMs lost at MEDIUM | NM `async_notify` (`notification_manager.py:1334`) — existing path | **First**, at a severity that reaches a channel (companion = HIGH+). |
| 3 | **Flag a dead actuator** | room lights/fans `unavailable`, invisible to `<room>_unavailable_entities` | OC-owned (read-only) | **First.** |
| 4 | **Reload one stuck config entry** | Shelly / cloud entries back on WiFi | HA integration level (`homeassistant.reload_config_entry` on a non-URA entry); no coordinator owns it | **Slice 4**, shadow first. 1 per entry per day; verifier = entities available. **Never** the URA parent entry (watchdog hazard). |
| 5 | **Re-seed a flapping counter / poisoned baseline** | Envoy production counter flap; poisoned energy_daily predictions (10-02..10-04) | **Inside the EC's domain**: the in-memory high-water mark (`energy.py:910`) and `reseed_cycle` (`energy_billing.py:576`) are EC-internal, with no external hook | **Needs one thin EC hook first** (§7). Not slice 4. |
| 6 | **Retune a threshold within bounds** | Jaya Bedroom night vacancy hold; the 4 h stuck-sensor literal (`coordinator.py:364`) | config write through the options/Number path, clamped | **Later** (propose + veto). |
| 7 | **Actuate a device** (setpoints, presets, fans, EVSE) | comfort misses | only through the owning coordinator's existing path (§7), never a raw service call | **Last**; climate only after the HVAC routing is built. |
| — | **Never automate** | battery reserve/grid charge (hard-denied :4514), safety/security (Security already vetoes `lock.*` / `alarm_control_panel.*`, `security.py:1880`), URA parent reload, HA restart, deletion, `.storage` edits, physical fixes | — | Operator-only. The OC may diagnose and page. |

---

## 5. Room memory: OC as its first automated consumer

**What exists** (audit Q1). Hierarchical Entity Memory is shipped:
- `MemoryFacade` with 7 verbs; **`outcome()` is a stub** (`memory_facade.py:608-627`).
- About 15k episodes.
- Baselines in `metric_baselines` (memory scope).
- The only entry point is the `memory_query` service; **no automated consumer exists**.

The standing **memory-ineligible boundary** forbids memory reads on safety, security, occupancy creation/release and reserve decisions (`memory_writers.py:29-43`).

**Position.** The OC reads memory for **diagnosis and evidence only**. Its output is a problem record or a page, never one of those forbidden decisions, so it sits inside the rule. Three uses:
- **Is this normal for this room and time?** Use `baseline` / `unusual`, plus `RoomDwellModel` `expected_share`.
- **Did the fix work?** A before/after comparison through `outcome()`.
- **Has this recurred?** Use `episodes` / `facts`, for example `phantom_recurrence`.

**Three additions:**
1. **Prediction vs actual, out of sample.**
   - Write `prediction_results` rows with `prediction_type = dwell_share`: predicted = the `expected_share` **frozen before the hour** (what the anomaly sensor read, `binary_sensor.py:3467-3511`), and actual = the room's occupied fraction for that hour.
   - Missing producer: the actual occupied fraction per room-hour. It is a new hourly batch read over `environmental_data.occupied`, one batched write per hour.
   - Zero schema change; existing accuracy readers already read this table.
2. **OC problems and fixes become memory episodes.**
   - New registered types `oc_problem` and `oc_fix` (`MEMORY_EPISODE_TYPES`, `const.py:5299`). Write on state changes only, so the volume is bounded.
   - `memory_query narrative` then explains what the house did about each problem.
3. **Implement `outcome()`.** It compares a metric before vs after an episode, which gives fix verification its oracle.

**Slices:** memory reads for "normal?" and recurrence land in **slice 2**. The `dwell_share` producer lands in **slice 2**, so slice 3's comfort/occupancy problems can cite scored skill. OC episodes and `outcome()` land in **slice 4**, where the first fixes need a verifier.

---

## 6. Slices

Slices 1-3 do not write to the house; each is Tier 2-DB (new DAO and changed write volume, given the 2026-06-09 write-flood incident). Slice 4+ is Tier 3.

**Slice 1: problems, goals shown, a track record, visible precision**
- Persistent problem records with restart-safe dedup; remove `cycle_ok` from the findings table.
- Fix the shadow validator (OC-SHADOW-SAMPLES-EMPTY-1).
- Each problem states a falsifiable prediction.
- Goal selects plus a goal tag on each problem.
- Precision per kind on the dashboard.
- *Acceptance:* ≤ 1 row per distinct fact over 7 days, restarts add 0 rows (today: 4 re-reports in 10 h). Samples > 0 within 1 h, and ≥ 20 per scored kind within 7 days. OC writes < 50/day (from ~640). ≤ 2 writes per table per cycle.

**Slice 2: goal-ranked root cause with memory evidence**
- Goal-weighted ranking and parent/child linking.
- Memory "normal?" and recurrence reads.
- `dwell_share` prediction-vs-actual records.
- *Acceptance:* a fixture with one dead device and five dependent problems shows one parent. Every NM-bound problem names its goal. `dwell_share` rows accrue hourly with the predicted value captured before the hour. LLM "truncated" findings fall to 0.

**Slice 3: fixes that write nothing to the house (fix types 1-3)**
- *Acceptance:* every page reached a channel. Operator-rated precision ≥ 80% over 2 weeks, or the kind is demoted to digest.

**Owner paths** (§7): no unified API. The HVAC routing and the EC re-seed hook are built only when a fix type that needs them is about to be promoted. Not needed by slices 1-4.

**Slice 4: reversible OC-owned / integration-level fixes, with verify-and-rollback**
- Fix type 4 (config-entry reload), plus OC episodes and `outcome()`.
- *Acceptance:* ≥ 20 shadow decisions at ≥ 90% precision before the promote button enables. Every applied fix has a verifier verdict and a memory episode. A failed verifier reverts and pages within its deadline.

**Slice 5: bounded config retunes and EC re-seed** (re-seed needs the thin EC hook, §7). **Slice 6: device actuation** through owner paths; climate needs the HVAC routing first.
- *Acceptance:* same precision gate. Every write lands in the owning coordinator's ledger (for climate, a `climate_write` row with an OC site id).

---

## 7. Precondition: use the owning coordinator's existing path

**Rule (rev 3, operator 10-21: "use the Coordinators' paths vs request ... it has to have good cost/benefit").** Where a fix touches a coordinator's domain, the OC calls that coordinator's **existing internal entry point, in process**. It never makes a raw `hass.services.async_call` into that domain. **No unified request API is built.** A thin new entry point is added only where none exists **and** a promoted fix type needs it.

| Domain | Existing path the OC uses | New code needed |
|---|---|---|
| NM | `async_notify` (`notification_manager.py:1334`) | none |
| HVAC | the same path HVAC's own sites use: `strategy_for(hass, entity)` (`hvac_strategy.py:2172`) → adapter verb → `emit_set_*` funnel (`hvac_setpoint.py:436-1040`, writes the `climate_write` row), wrapped in the arrester `suppress()` (`hvac_override.py:3409`) as HVAC's sites do. Before writing, the OC reads the existing gates: `manual_guard_verdict` (`hvac_preset.py:259`, the §9e person-protection/arrester gates) and `is_borrow_active` (`hvac_excursion.py:597`, gate (e)). Climate fixes are **preset verbs only** (`pin_preset` / `hold_preset`); no raw setpoint writes | **remove `optimization.py` from `DYNAMIC_DOMAIN_ALLOWLIST` (`hvac_const.py:1546`)** so the funnel lint covers it; route the OC's climate branch through the path above; give it its own `site` id. This is `HVAC-OPTIMIZER-CLIMATE-FUNNEL-ROUTING-1` |
| Fans / lights | `FanPolicyOracle.actuate` (`fan_policy_oracle.py:588`) / `LightPolicyOracle`, which already arbitrate Fan Mode owner, manual holds and safety | a call site, no new API |
| Energy knobs | the existing setters (`set_peak_buffer_target`, `set_arbitrage_target`, …, `energy.py:11268-11647`), clamped by `_clamp_numeric_to_band` | none. Battery mode and reserve stay hard-denied |
| EC counter re-seed (the one known gap) | none: the production high-water mark (`energy.py:910`) is private; billing has `reseed_cycle` (`energy_billing.py:576`) | **one thin hook**, e.g. `EnergyCoordinator.reseed_production_baseline(reason)`: snapshots the old value, resets the high-water mark, logs one row. Billing re-seed reuses `reseed_cycle`. Built only when the re-seed fix type is promoted |
| EVSE | owner registry is EC-private (`energy_pool_owners.py`) | **out of scope** until a fix type needs EV charging |
| Security, Safety, Presence | never targets (vetoes in code, `security.py:1880`, `presence.py:8340`) | none, ever |

**Cost/benefit.**
- **Cost, using existing paths (rough):**
  - HVAC: one Tier-3 cycle, small LoC (allowlist removal, one routed branch, two gate reads).
  - Fans/lights: a call site each.
  - Energy knobs and NM: none.
  - EC re-seed: one ~30-line hook with a snapshot.
  - About one Tier-3 plus one Tier-2 cycle in total, spread over the slices that need them.
- **Cost of a unified request API (rough):** a new request/reply type, queueing, and an accept/defer/refuse precedence written into every coordinator (HVAC, EC, EVSE, fans, lights). That is about six coordinators of shared-primitive work, each Tier 3, for a caller (the OC) that today has 0 promoted fix types.

**Why the existing paths are enough for the §7 failure modes** (state of play):
- **Manual holds:** a raw Carrier `set_temperature` creates a manual hold (`ha_carrier climate.py:467-537`). The rule "preset verbs only, through the adapter" never creates one.
- **Arrester misattribution:** the arrester books URA's own echo as a human override past the 15 s / 120 s windows (§2, §7, C23). The OC's write is wrapped in the same `suppress()` HVAC uses for its own writes.
- **Precedence bypass:** the OC reads the §9e gates and gate (e) before writing, so it defers to person-protected holds, arrester episodes and live borrows (D13, D48-D52). The adapter applies Custom Preset Ranges and ecobee semantics. The funnel adds the `climate_write` row, closing the C1 invisibility gap.
- **Residual (accepted, stated):** the OC is a caller that obeys HVAC's rules, not a participant HVAC arbitrates. S1 may later move the zone to its own target. That is correct: HVAC's precedence wins. The OC's verifier then scores the fix as "did not hold", which is honest evidence, not a fight.

**Sequencing.**
- Slices 1-3 need none of this: their writes are the OC's own tables plus NM.
- Slice 4's first fix type (non-URA config-entry reload) is integration-level.
- EC re-seed waits for its hook (slice 5).
- HVAC routing must be built before any climate fix type is promoted (slice 6).

---

## 8. Non-goals, risks, decisions

**Non-goals.**
- No house writes in slices 1-3.
- Goals never write energy/HVAC knobs.
- No memory reads in safety, security, occupancy or reserve decisions.
- No new optimizer engine (MILP/emhass stays rejected).
- No room agents (`ROADMAP-STALE-AGENTIC-LAYER-1` stays separate).
- No unified request API; no new entry point for a domain no promoted fix needs (EVSE out of scope).
- Never touch battery reserve, safety or security.

**Risks.**
- **Write volume:** new problem, `dwell_share` and episode writers on the shared queue. Mitigation: batch each one, and add a per-table write-count test.
- **Precision theatre:** cheap predictions that are trivially right. Mitigation: score against independent oracles plus operator ratings.
- **Dedup hiding a recurrence:** the fingerprint includes the episode.
- **Goal weights become a hidden policy engine:** keep them as a ranking lens only (non-goal above).
- **`dwell_share` scored in-sample:** freeze the prediction before the hour.

**Decisions needed from the operator.**

1. **Approve the vision and slice order.** *Recommend yes.* Slices 1-3 carry no house risk and produce the precision numbers trust needs.
2. **Goals:** the five canned goals, ranked via selects (rung 3), with bounds read from existing knobs and only the bill cap new; selection and display in slice 1, ranking in slice 2. *Recommend yes.*
3. **Memory as an evidence source:** the OC becomes memory's first automated consumer for diagnosis and verification only, inside the ineligible boundary. Add `dwell_share` prediction-vs-actual (slice 2) and OC episodes plus `outcome()` (slice 4). *Recommend yes.*
4. **Use owning coordinators' existing paths, no unified request API:** the OC calls each coordinator's in-process entry point (HVAC adapter + `emit_set_*` + arrester `suppress`, preset verbs only, after reading the §9e and borrow gates; energy setters; fan/light oracles; NM). It never makes raw service calls into an owned domain. Remove the `optimization.py` HVAC allowlist. Add a thin hook only where a promoted fix needs one (EC re-seed now; EVSE out of scope). *Recommend yes:* about one Tier-3 plus one Tier-2 cycle, against about six Tier-3 cycles for a unified API, and it closes the manual-hold, misattribution and precedence failure modes.
5. **Score by fix type, not dimension.** *Recommend yes.*
6. **Promotion is always an operator tap; demotion is automatic.** *Recommend yes.*
7. **Precision bars:** ≥ 80% for paging and ≥ 90% over ≥ 20 decisions for any house write, as Number knobs (rung 3). *Recommend yes.*
8. **Retire `meta cycle_ok` rows** in slice 1. *Recommend yes.*
