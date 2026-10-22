# VISION — The Optimization Coordinator as a self-fixing house (rev 4, agent-first)

Card: `OC-SELF-OPTIMIZING-HOUSE-REDESIGN-1` (Tier 3, thread optimization). Folds in `OC-SHADOW-SAMPLES-EMPTY-1` and the residual of `OC-STUCK-SENSOR-GENERALIZE-1`. Gates climate fixes on `HVAC-OPTIMIZER-CLIMATE-FUNNEL-ROUTING-1`. Rev 4 adds §5b Model and budget plus slice 0.
Status: vision for operator approval. Not a build plan.

**Revision history.**
- Rev 1-3 2026-10-21: static redesign; goals; room memory; "use the owning coordinator's existing path".
- Rev 4 2026-10-21: reshaped agent-first on operator approval ("Yes re-write it"). Earlier work is re-placed, not dropped (§7).

Evidence: live URA DB (§1), `AUDIT_room_memory_and_coordinator_request_apis_2026_10_21.md`, and `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md`, which I read in full. Nothing here re-asserts a claim from its §10 ledger.

**Operator framing (binding).**
- "Optimization coordinator is meant to diagnose the house and self fix it. It's supposed to reason over issues in the house."
- The OC never acted *by operator choice*, because of the noise. Trust must be earned by measured precision the operator can see.
- Rev 4 thesis: **the unlock is context, reasoning, goals and loops, not more static detector code.** The faster path is a URA-specialized reasoning agent.

---

## 1. Why the pivot

**Static detectors produced noise, not diagnoses** (live DB, 2026-10-08 to 10-22):
- 5,305 finding rows over 14 days, but only 72 distinct (dimension, target) pairs.
- 41% are the `cycle_ok` heartbeat; 37% are one prediction-accuracy fact re-sent every 5 minutes.
- 0 proposed actions, 0 applied, 0 observed effects, and 0 shadow samples ever.
- Even a correct detector was noisy: never-fires found 7 truly silent sensors with 0 false findings, then re-reported each after every restart (4 times in 10 h), because its dedup key lives in memory.
- The LLM tier saw a truncated snapshot and mostly reported that truncation.

**The loop that actually worked on 10-21 was an agent loop:** pull context → reason → propose → operator OK → apply → scheduled check-back. Same day, by hand:
- Solar lifetime counter flap: found and fixed (EC-SOLAR-LIFETIME-COUNTER-FLAP-1).
- Missing occupancy exit rows: found and fixed in v5.103.83.
- Foyer BLE pull: retuned.
- Dead kiosk-screens automation: cleaned up.
- The never-fires restart repeat: diagnosed and carded.

None of those needed a new static detector. They needed context, evidence and a check-back. The agent automates that loop; the operator stops being the loop.

---

## 2. Risk tiers: what the agent may do alone

Operator: "we just need a risk level taxonomy where it can act alone and some where it cannot."

| Tier | What | Examples | Alone? |
|---|---|---|---|
| **R0 observe** | Read anything. Write only its own records, cards and digest. | queries, problem records, memory episodes, morning summary | **Always** |
| **R1 silent fix** | Reversible, not occupant-visible, scoped to one integration or entry | reload one config entry (never the URA parent); request a fan recheck; clear a stuck-sensor latch; re-seed a counter; re-sync a device | **Yes, including overnight.** Logged, verified next day, auto-demoted on failure |
| **R2 visible, reversible** | Occupants could notice; reversible | HVAC preset switch, fan/light on/off, bounded threshold retune | **Only for operator-promoted fix types, and never while the house sleeps.** Otherwise it proposes |
| **R3 never alone** | Disruptive, irreversible, money, or security | HA restart (also never while asleep); battery/EV decisions; locks/alarm; deleting data; integration config changes; anything that costs money | **Never.** Propose only |

**Standing rules encoded:**
- Integration (config-entry) reload is R1.
- HA restart is R3 and never while the house sleeps.
- The URA parent entry is never reloaded (watchdog hazard).
- Battery reserve and safety/security stay hard-denied, as today (`optimization.py` :4514; `security.py:1880`).

### 2a. Promotable R2 fix types (rev 5, operator: "We need a set of types to promote")

A fix type is the unit of promotion. Each type is a fixed verb plus a fixed target class plus a check-back, so its precision can be measured on its own. Every type starts as **propose-only**. It is promoted to act-alone by an operator tap after ≥ 20 logged proposals at ≥ 90% precision. It is demoted automatically on a failed check-back.

| # | Fix type | Path (owning coordinator) | Check-back |
|---|---|---|---|
| P1 | Turn off a light left on in a room that has been vacant for ≥ its configured timeout | room light path via `fan_policy_oracle`/room actuation | light off and room still vacant 10 min later |
| P2 | Turn off a fan stuck on after vacancy (humidity normal) | fan policy oracle | fan off, no humidity rise in 30 min |
| P3 | Restore an HVAC zone preset after an unreleased borrow/excursion | HVAC `strategy_for` → `emit_set_*` (after `manual_guard_verdict`, `is_borrow_active`) | preset matches the schedule 15 min later, no manual-hold flag |
| P4 | Retune one bounded numeric knob by one step inside its documented range | the knob's existing setter, clamped | the target metric moves the right way over the next 3 days; else revert |
| P5 | Re-apply a room's presence-sensor settings (radar sensitivity) after drift | `reapply_radar_settings` | settings read back equal |

Not promotable, ever: anything in R3; any climate write outside P3; EVSE; anything the house-sleep gate blocks.

**The action log is the only static trust machinery.** Each row records:
- what was done and at which tier;
- why, with the evidence cited;
- the prediction ("entity available within 10 min");
- the check-back result.

Per fix type, the log drives promotion (operator tap) and automatic demotion (a failed check-back, or precision below the bar), and it is the operator's audit trail. It replaces the empty shadow-sample machinery.

---

## 3. The harness

Operator: "It needs to understand HA ... URA and the current config ... a list of tools."

**Knowledge, loaded fresh every run:**
- HA concepts.
- URA docs: `URA_ARCHITECTURE_MAP.md`, the HVAC and presence state-of-play docs, `SENSOR_FLEET_CLASSES.md`, `DEVICE_TREE.md`.
- A live config snapshot: rooms and their entities, knobs and current values, zones, HVAC zones.
- Operator doctrine: `CLAUDE.md` and the feedback memories.
- The ranked goals (§3a).

**Live context:**
- Open problems and their history.
- Room memory (`memory_query`).
- Recent anomalies, logs and errors.
- What changed since the last run: deploys, config edits, restarts.
- The kanban board.

**Tool catalogue, each tool tagged with its tier.** "Exists" is verified against `custom_components/universal_room_automation/__init__.py` and `services.yaml`.

| Tool | Tier | Exists today? |
|---|---|---|
| HA state / history / registries (ha-mcp), recorder + URA DB read queries, logs | R0 | yes (out of HA, as today's sessions use them) |
| `universal_room_automation.memory_query` | R0 | yes, `__init__.py:6355` |
| Cards, problem records, action log, memory episodes | R0 | cards yes; problem records + action log NEW (slice 1); OC episode types NEW |
| NM digest / page (`test_notification` / NM `async_notify`) | R0 comms | yes (`__init__.py:6611`, `notification_manager.py:1334`) |
| `homeassistant.reload_config_entry` (one non-URA entry) | R1 | yes (HA core) |
| `reapply_radar_settings` | R1 | yes, `__init__.py:6213` |
| `fan_recheck_force_restore` (abort a recheck) | R1 | yes, `__init__.py:6186` |
| **Request a fan recheck** | R1 | **must be exposed** (logic is internal: `presence.py:101` `_run_fan_recheck_tick_for_rooms`) |
| **Clear a stuck-sensor latch** | R1 | **must be exposed** (internal: `coordinator.py:1864-2324` stuck-sensor set) |
| **Re-seed a counter / baseline** | R1 | **must be exposed**: thin EC hook over the private high-water mark `energy.py:910`; billing reuses `reseed_cycle` `energy_billing.py:576` |
| **Re-sync a device** | R1 | **must be defined**; no URA service today |
| HVAC preset, fan/light, energy knob retunes | R2 | through the owning coordinator's existing path (rev 3 rule, below) |
| `set_house_state`, `security_arm/disarm`, restart | R3 | exist; never called alone |

**Full tool inventory and exclusions (rev 5).** The table above is the allowed set. Everything below is explicitly excluded from the agent's catalogue, in two classes:

*Never grantable (hard-denied in code, not by prompt):*
- `homeassistant.restart` / `stop`, `hassio.*` host/add-on control, OS/backup operations.
- Reloading the URA parent entry or any URA entry (watchdog hazard).
- `lock.*`, `alarm_control_panel.*`, `security_arm/disarm`, `set_house_state`.
- Battery/Envoy reserve, storage mode, charge-from-grid; EVSE start/stop/pause.
- Recorder `purge`/`purge_entities`, entity/device/registry removal, config-entry delete/options edits, `.storage` writes.
- Any `notify.*` or message send other than the NM digest/page.
- `script.*` / `automation.trigger` / `scene.*` (arbitrary side effects behind one name).
- Shell on the HA host, ESPHome flashing, HACS install/update.

*Excluded today, promotable to a tier later with a named fix type:*
- `light.*`/`fan.*`/`switch.*` raw calls: only via P1/P2 paths, never raw.
- `climate.*` raw calls: only via P3.
- `number.set_value` / `select.select_option` on URA knobs: only via P4, one step, clamped.
- `automation.turn_on/off`: candidate R2 type if a pattern of disabled-by-mistake automations shows up.
- `zha`/`mqtt` device re-interview, Bermuda offset edits: R3 propose-only until device re-sync is defined per integration.

**Unified request API — revisited (operator: "really think about if we need an API that can cover all Coordinators").** Owning paths now (decision 7). The case for a unified API gets stronger as types grow: one place for tier checks, sleep gate, action-log row and check-back scheduling. The cheap middle path: a thin `request_fix(type, target, evidence)` dispatcher in URA that does the shared gate/log/check-back work and then *calls* the owning coordinator's existing path. It is not a new actuation path, so the rev-3 risks (manual-hold, arrester misattribution, precedence bypass) don't come back. Build it in slice 2, when the first R1 types go in-HA; revisit a deeper API only if ≥ 3 coordinators need the same request shape.

**R2 keeps the rev-3 rule: use the owning coordinator's existing path, never a raw service call into its domain.**
- HVAC: `strategy_for` → adapter verb → `emit_set_*` funnel inside the arrester `suppress()`, after reading `manual_guard_verdict` (`hvac_preset.py:259`) and `is_borrow_active` (`hvac_excursion.py:597`). Preset verbs only. Remove `optimization.py` from `DYNAMIC_DOMAIN_ALLOWLIST` (`hvac_const.py:1546`).
- Fans/lights: the policy oracles (`fan_policy_oracle.py:588`).
- Energy knobs: the existing setters, clamped.
- No unified request API. EVSE stays out of scope.
- This prevents manual holds, arrester misattribution of URA's writes as human overrides, and precedence bypass, as rev 3 argued.

**Every action tool must:**
- check its tier against the current house state (asleep → no R2);
- write an action-log row with evidence and a prediction;
- schedule its own check-back.

**Every diagnostic claim must cite retrieved evidence** (a query result, an entity state, a log line). No citation means no claim.

### 3a. Goals (kept from rev 2/3)
- **The list:** the operator ranks up to five canned goals: save energy/money, maximize comfort, quiet nights, protect battery/grid independence, keep devices healthy.
- **Bounds reuse existing knobs:** the comfort band is the HVAC Seasonal Baseline, minimum SOC is `energy_reserve_soc`, quiet hours are NM quiet hours. The bill cap is the only new bound.
- **Goals never write knobs.** They rank problems, decide trade-offs between fixes, and are named in every explanation.
- **Knobs:** five rank selects plus a bill-cap number, rung 3. All slots "none" means unranked.

### 3b. Room memory as evidence (kept from rev 2/3)
- **Position:** the agent is memory's first automated consumer, for diagnosis and verification only, inside the memory-ineligible boundary (no memory reads for safety, security, occupancy or reserve decisions, `memory_writers.py:29-43`).
- **Uses:** "is this normal for this room and time", "has this recurred", and fix check-backs via a real `outcome()` (today a stub, `memory_facade.py:608-627`).
- **Prediction vs actual:** `prediction_results` type `dwell_share`. Predicted = the `expected_share` frozen before the hour; actual = the room's occupied fraction that hour. The hourly actual-fraction producer is new.
- **Beyond rooms (rev 5, operator: "HA as well if needed but room is bounded. Find a bound").** HA-wide data is allowed, under a per-run bound:
  - only entities linked to an open problem record, the problem's room/zone, or a changed-since-last-run item;
  - history window ≤ 7 days per entity, statistics (hourly) beyond that, never raw recorder dumps;
  - ≤ 50 entities and ≤ 200k tool-result tokens per run in total; the run notes when it hits the cap instead of widening;
  - logs: only lines matching the problem's integration/entity, last 24 h.

---

## 4. The nightly loop

1. **Gather:** refresh the knowledge and config snapshot, and pull changes since the last run.
2. **Diagnose with evidence:** update persistent problem records (one per fact, restart-safe), linking cause to symptoms (one dead device explains five room problems).
3. **Rank by goals.**
4. **Act within tiers:** R1 alone, R2 only for promoted types while the house is awake. **Propose** the rest as cards or asks.
5. **Verify last night's fixes:** run each check-back, write the result, and demote on failure.
6. **Morning summary**, one message: what it found, what it did (with results), and what it asks of the operator.

Cadence: nightly, plus on notable events (a deploy, a restart, a HIGH anomaly).

---

## 5. Where it runs

- **Outside HA first**, as a scheduled Claude session like today's (proven tools: ha-mcp, ssh, the URA DB, the board). It is fast to start and needs no URA build to begin.
- **Inside HA later**, once its action log shows trust. The OC coordinator becomes its host and executor, and the static evaluators become its signals.

---

## 5b. Model and budget

Operator: "We need to answer the minimum model it can use ... see if it can use open source models ... fix a cost of operation/budget."

**Benchmark from this house's real cases (slice 0).**
- **Eval set:** cases with known answers.
  - From 10-21:
    - the solar lifetime counter flapping to 0.046 MWh;
    - missing occupancy exit rows on three vacate paths;
    - the Foyer BLE pull and its RSSI offsets;
    - the dead kiosk-screen automation targets;
    - the never-fires restart repeat;
    - the Bayesian arrival-vs-dwell model mismatch;
    - the bridge omitting `color_mode`.
  - Plus about 5-8 more from recent cards and READMEs, for example:
    - the Seeed radar following the Jaya Bedroom fan (state of play §9.3 / C27);
    - S10 latch NMs lost at MEDIUM severity;
    - zone 1 status-vs-config feed split (§9.9);
    - the OC shadow validator never scoring.
- **Each case:** a frozen context snapshot plus the tool list, and the expected root cause, tier and action.
- **Score per case:**
  - correct root cause;
  - every claim cites retrieved evidence (any invented cause fails the case);
  - right tier;
  - 0 R3 attempts;
  - valid tool calls;
  - tokens and cost.

**Candidates.**
- **Claude:** Haiku 5.5, Sonnet 5.5, Opus 5.5.
- **Open source:** at least two tool-calling models, for example a Qwen-class (~8-32B) and a Llama-class (~8-70B), via Ollama or vLLM.
- **Hardware, as found in docs/memory (not assumed):**
  - An Ollama server ran on 192.168.13.62. It was stopped 2026-09-13 because of its RAM use (OLLAMA-CONSUMER-AUDIT-1). It ran qwen3-vl:8b at about 75 s per call with no GPU.
  - Frigate 2 has an Intel iGPU (OpenVINO) used for detection.
  - Unraid (192.168.13.11) is storage.
  - **No discrete GPU is recorded.** So today only small (~8B) CPU models are feasible, slowly. Overnight latency is tolerable, but small models' multi-step tool-calling reliability is the usual failure point.
  - Larger open models need new hardware (a GPU, or a high-memory Apple-silicon box). The operator should confirm what exists.
  - HA already has an `ai_task.ollama` entity, so the plumbing exists.
- **Requirement:** reliable structured tool calls over 20+ round-trips. A model that malformats tools or loops fails regardless of diagnosis quality.

**Minimum model = the cheapest candidate that clears the bar:**
- ≥ 80% correct root cause;
- **0** invented-evidence claims;
- **0** R3 attempts;
- ≥ 95% valid tool calls.

A split is allowed: a cheap model triages nightly and escalates only hard or ambiguous cases to a stronger one. The split is scored as a pair on the same set.

**Budget estimate** (to be replaced by R0 measurements). Per nightly run:
- context pack about 60k tokens, cached after the first call;
- about 30 tool round-trips (about 1.5M cache-read tokens plus about 300k new tool-result tokens);
- about 30k output tokens.

Formula: `cost = 60k·in + 1.5M·cache_read + 300k·in + 30k·out`.

Prices are from platform.claude.com/docs/en/about-claude/pricing, read 2026-10-21. The cache read on Opus and Sonnet 5.5 is 0.05x input.

| Model | Price (in / cache read / out per MTok) | ≈ per night | ≈ per month (30 runs) |
|---|---|---|---|
| Opus 5.5 | $4 / $0.20 / $20 | ≈ $2.3 | ≈ $70 |
| Sonnet 5.5 | $2 / $0.10 / $10 | ≈ $1.2 | ≈ $35 |
| Haiku 5.5 (≤ 100k prompt) | $0.10 / $0.01 / $0.50 | ≈ $0.07 | ≈ $2 (prompts > 100k cost 5x) |
| Open source, local | $0 API | — | power plus hardware; TBD after the operator confirms hardware |

Event-triggered runs (deploy, restart, HIGH anomaly) add per-run cost on top.

**Budget cap:**
- A Number knob `optimizer_agent_monthly_budget_usd` (rung 3). 0 means R0 digest-only.
- **Hard stop:** when spend reaches the cap, the agent skips actions and runs R0 digest-only (or skips the run if even that would exceed), and pages the operator **once** per month.
- Spend per run (tokens and $) is recorded in the action log.
- Recommended starting cap: about $50/month. That covers nightly Sonnet with headroom, and it is revisited after slice 0.

---

## 6. Slices

0. **Model eval** (gates everything; grants nothing)
   - Build the real-case eval set and run every candidate on it.
   - *Acceptance:* a scored table per model (root cause, invented evidence, tier, R3 attempts, tool validity, cost per case). The minimum model or split is named against the bar, and the open-source verdict is stated with the hardware it assumed.
1. **Read-only harness (R0)**
   - Nightly agent and morning summary.
   - Persistent problem records, the action log and goals selection.
   - The operator judges its diagnoses for about 2 weeks.
   - *Acceptance:*
     - each fact is one problem record, and restarts add none;
     - every claim cites evidence;
     - the operator rates ≥ 80% of diagnoses correct over 2 weeks;
     - precision is shown per problem kind.
2. **R1 actions** behind the tier gate, with next-day verification; expose the missing URA services (fan recheck request, stuck-latch clear, counter re-seed hook, device re-sync).
   - *Acceptance:*
     - every R1 action has a log row, a prediction and a check-back result;
     - a failed check-back auto-demotes its fix type;
     - 0 R2/R3 actions taken alone;
     - 0 actions while the house sleeps other than R1.
3. **R2 via coordinator paths**, per operator-promoted fix type, with goals deciding trade-offs; HVAC routing built first.
   - *Acceptance:*
     - a fix type is promotable only after ≥ 20 logged proposals at ≥ 90% precision;
     - every climate write appears as a `climate_write` row with an OC site id;
     - 0 raw service calls into an owned domain (lint).
4. **Optional: in-HA agent.**
   - *Acceptance:* the same action-log precision as outside HA over 2 weeks, with no new DB write-volume alarm (per-table write-count test).

---

## 7. Re-placement of earlier work

| Earlier work | Rev 4 place |
|---|---|
| Useful static detectors: never-fires, camera_stuck / input-dark, the occupancy-anomaly dwell sensor (v5.103.83), predictions audit/skill | **Tools and signals** the agent reads |
| Noisy evaluators: `cycle_ok` rows, the per-cycle prediction_accuracy re-emit, per-cycle comfort re-emits, the truncated-snapshot LLM tier | **Retired** (or demoted to a signal the agent reads once) |
| Rev 1-3 cross-signal root-cause slice | **Absorbed** by the agent's diagnose step |
| OC-SHADOW-SAMPLES-EMPTY-1 scoring | **Becomes the action log** (prediction + check-back per action) |
| Autonomy ladder, kill switch, denylists, reserve hard-deny | **Kept** as backstops under the tiers |
| Goals, room memory + `dwell_share`, owner paths for R2 | **Kept** (§3, §3a, §3b) |
| HVAC-OPTIMIZER-CLIMATE-FUNNEL-ROUTING-1 | **Kept**, needed before any climate R2 |

---

## 8. Risks

- **Hallucinated causes:** the evidence rule (no citation, no claim) plus the operator-judged R0 period.
- **Token cost and cadence:** nightly plus notable events only; context loaded from snapshots, not raw history dumps; the monthly budget cap with a hard stop (§5b).
- **Harness staleness:** docs and the config snapshot are regenerated at the start of every run, never cached.
- **Prompt injection** from logs, entity names or messages: treated strictly as data. Tool tier gates are enforced in code, not by the prompt.
- **Acting while people sleep:** only R1 overnight, and every R1 tool checks that it is not occupant-visible before acting.
- **Write volume (2026-06-09 incident):** problem records and the action log are batched; the agent outside HA writes nothing into the URA write queue in slice 1.

---

## 9. Decisions for the operator

1. **Approve the agent-first vision.** *Recommend yes:* it automates the loop that already works by hand.
2. **Tier definitions, with R1 = config-entry reload, fan-recheck request, stuck-latch clear, counter re-seed, device re-sync.** *Recommend yes,* with device re-sync defined per integration before it is used.
3. **Outside HA first.** *Recommend yes:* proven tools, no build needed to start.
4. **About 2 weeks of R0 judging before any R1.** *Recommend yes,* with the 80% bar.
5. **Goals** (five canned, ranked selects, bounds read from existing knobs). *Recommend yes,* selected in slice 1.
6. **Room memory as evidence**, including `dwell_share` prediction-vs-actual and a real `outcome()`. *Recommend yes.*
7. **Owning coordinators' existing paths for R2, no unified API**, including removing the HVAC allowlist bypass. *Recommend yes.*
8. **Run slice 0 (model eval) first, before anything is granted.** *Recommend yes.*
9. **Model choice after the eval:** the cheapest model or split that clears the bar. *Recommend* deciding from the eval table, expecting Haiku triage with Sonnet escalation.
10. **Open source viable or not:** *Recommend* including at least two models in the eval on today's CPU hardware. Buy hardware only if one clears the bar on a larger model that hardware would enable.
11. **Budget cap value:** *Recommend* $50/month with the hard stop, revised after slice 0.
