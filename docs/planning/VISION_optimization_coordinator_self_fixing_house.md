# VISION — The Optimization Coordinator as a self-fixing house (rev 6, agent-first)

Card: `OC-SELF-OPTIMIZING-HOUSE-REDESIGN-1` (Tier 3, thread optimization). Folds in `OC-SHADOW-SAMPLES-EMPTY-1` and the residual of `OC-STUCK-SENSOR-GENERALIZE-1`. Gates climate fixes on `HVAC-OPTIMIZER-CLIMATE-FUNNEL-ROUTING-1`. Seed plan: `PLANNING_oc_request_fix_dispatcher_SEED.md`.
Status: vision. The agent-first direction was approved by the operator on 2026-10-21 (rev 5). Rev 6 answers two Tier-3 plan reviews and is **not yet re-approved**: see §10 "Open decisions for the operator". Not a build plan.

**Revision history.**
- Rev 1-3 2026-10-21: static redesign; goals; room memory; "use the owning coordinator's existing path".
- Rev 4 2026-10-21: reshaped agent-first on operator approval ("Yes re-write it"). Earlier work is re-placed, not dropped (§7).
- Rev 5 2026-10-21: operator answers recorded (§9); promotable fix types P1-P5 (§2a); tool inventory and exclusions; HA-data bound (§3b); model/budget §5b with local models; slice 0.
- Rev 6 2026-10-21: addresses `REVIEW_oc_vision_rev5_completeness.md` (C1-C2, H1-H6, M1-M7, L1-L4) and `REVIEW_oc_vision_rev5_thinking.md` (C1-C2, H1-H6, M1-M5, L1-L4). The changes are mapped per finding in §11. Biggest moves: enforcement in code before slice 1 (§3c), deny-by-default tools (§3), R1 narrowed (§2), the legacy executor clamped (§7a), corrected budget (§5b), eval leakage freeze (§5b), liveness and storage (§5c), and a marginal-benefit section with a recommended scope (§1b).

Evidence: live URA DB (§1), `AUDIT_room_memory_and_coordinator_request_apis_2026_10_21.md`, `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md`, `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` and `docs/architecture/SENSOR_FLEET_CLASSES.md` (all three read in full for rev 6). Nothing here re-asserts a claim from either corrections ledger.

**Operator framing (binding).**
- "Optimization coordinator is meant to diagnose the house and self fix it. It's supposed to reason over issues in the house."
- The OC never acted *by operator choice*, because of the noise. Trust must be earned by measured precision the operator can see.
- Rev 4 thesis: **the unlock is context, reasoning, goals and loops, not more static detector code.** The faster path is a URA-specialized reasoning agent.

---

## 0. Institutional context verified (rev 6, new)

Prior art scanned in code, plans and analysis. Each piece of the vision is REUSE or BUILD.

| Piece | Verdict | Existing symbol / doc |
|---|---|---|
| Gate chain (rung, kill switch, rate cap, quiet hours, hard denies) | **REUSE the predicates, replace the dispatch leg** | `optimization.py:4282` `_apply_action`; `:4043` `_rate_cap_window_count`; `:4021` `_is_quiet_hours_active`; `:4514` `_check_reserve_role_hard_deny`; levels `const.py:4099-4121` (advisory → unbounded). Its dispatch legs `_dispatch_device_action` (`:4552`, raw `async_call` at `:4677`) and `_dispatch_config_action` (`:4707`, raw `async_call` at `:4826`) are what `request_fix` replaces with owner paths (§7a) |
| Reload-as-recovery | **REUSE the parked design** | `PLANNING_OPTIMIZATION_COORDINATOR_v2_agentic.md` Appendix C D3 (PARKED 2026-06-30) and its seven safety conditions. Rev 6 R1 reload adopts all seven (§2b) |
| Handshake + intent signal | REUSE | v2 plan D3 `SIGNAL_OPTIMIZER_INTENT`, `security.py:1880` `honor_optimizer_intent`, `OverrideArrester.suppress()` |
| Admin surface / phase-5 handshake | REUSE as reference | `PLANNING_OC_phase5_handshake_and_admin_surface.md` |
| Prior OC audit findings | REUSE as reference | `CRITIQUE_audit_optimization_coordinator_2026-07-10.md`, `PLANNING_audit_optimization_coordinator.md` |
| LLM tier plumbing | REUSE for the in-HA phase only | options field `optimizer_llm_task_entity` (`strings.json:1464`), `ai_task` integration |
| Stuck-sensor "latch" | **No latch exists** | The stuck set is rebuilt every tick: `_p22_stuck_sensor_set` (`coordinator.py:2297`) from `_stuck_sensor_hours` (`coordinator.py:387`, literal 4.0), promoted into `SensorExclusionSet` clients `p22_continuous` / `stuck_dutycycle` (`coordinator.py:3320`, `:3388`) after `reset_tick`. A release is re-promoted next tick. See §2 |
| Fan recheck | REUSE | `presence_fan_recheck.py`; all writes through `hvac_fans.FanController._set_fan_state`; `fan_recheck_force_restore` `__init__.py:6186` |
| Room pause / manual hold gates | REUSE | `const.room_automation_paused`; manual-ON hold; Fan Mode `const.fan_owner` (HVAC doc §4.2b) |
| Problem records, action log, agent store, digest service, dead-man sensor | BUILD (NEW) | Grep of `const.py`, `services.yaml`, `__init__.py`, `sensor.py`, `binary_sensor.py` for `optimizer_agent_*`, `budget_usd`, `request_fix`, `digest`: no equivalent |

Not yet scanned, and required in the slice-1 plan: the v2 plan's cost levers section against §5b, and the phase-5 admin surface against the §3c proxy.

---

## 1. Why the pivot

**Static detectors produced noise, not diagnoses** (live DB, 2026-10-08 to 10-22):
- 5,305 finding rows over 14 days, but only 72 distinct (dimension, target) pairs.
- 41% are the `cycle_ok` heartbeat; 37% are one prediction-accuracy fact re-sent every 5 minutes.
- 0 proposed actions, 0 applied, 0 observed effects, and 0 shadow samples ever.
- Even a correct detector was noisy: never-fires found 7 truly silent sensors with 0 false findings, then re-reported each after every restart (4 times in 10 h), because its dedup key lives in memory.
- The LLM tier saw a truncated snapshot and mostly reported that truncation.

**The loop that worked on 10-21 was an agent loop:** pull context → reason → propose → operator OK → apply → scheduled check-back. Same day, by hand:
- Solar lifetime counter flap: found and fixed (EC-SOLAR-LIFETIME-COUNTER-FLAP-1).
- Missing occupancy exit rows: found and fixed in v5.103.83.
- Foyer BLE pull: retuned.
- Dead kiosk-screens automation: cleaned up.
- The never-fires restart repeat: diagnosed and carded.

None of those needed a new static detector. They needed context, evidence and a check-back. Caveat (rev 6): that loop was the operator plus Opus, interactive, with the operator steering. It is evidence for **diagnosis with a human in the loop**. It is not evidence that an unattended, cheaper agent acts well.

## 1b. Marginal benefit — what each step buys over the simplest version (rev 6, new)

**Simplest version = two static fixes + an R0 nightly digest.**
1. **Persist the never-fires dedup key** (restart-safe), which stops the 4-in-10 h repeats.
2. **Stop writing the `cycle_ok` rows and the per-cycle prediction_accuracy re-emit** (write on change only). On §1's own numbers this removes about 78% of the finding rows.
3. **R0 nightly digest:** the agent diagnoses with evidence and proposes; the operator taps in the morning.

Fixes 1 and 2 are small, need no agent, and remove most of the noise the operator objected to. They should ship regardless of what happens to the agent.

| Step | Marginal benefit over the step before | Marginal risk (ingredients) |
|---|---|---|
| Static fixes 1-2 | most of the noise gone | none new |
| R0 digest | diagnoses joined across signals, with cited evidence; the operator stops being the loop for *finding* faults | spend; hallucinated causes (caught by the evidence rule and operator rating) |
| R1 alone | a few hours less latency on non-urgent, reversible faults, versus "R0 proposes, operator taps at breakfast" | a new unattended writer; reload blast radius (§2b); a missed check-back can leave a bad fix in place (§5c) |
| R2 alone | near zero for a long time: each P-type is a backstop for a URA path that already does the job, so occurrences are rare and promotion takes months (§2a) | occupant-visible writes; the sleep gate; a new writer next to HVAC and fan owners |

**Recommendation (for the operator, §10 D1):**
- **Commit to slices 0 and 1** (eval, then R0 with enforcement), plus the two static fixes.
- **R1 is conditional:** build it only if R0's log shows faults where the morning-tap latency cost something (named cases with the cost stated).
- **R2 is parked** with a revival trigger: a P-type with ≥ 20 measured occurrences over 90 days (from the §2a frequency probe).

The fancier steps stay designed below so nothing is lost if a trigger fires.

---

## 2. Risk tiers: what the agent may do alone

Operator: "we just need a risk level taxonomy where it can act alone and some where it cannot."

| Tier | What | Examples | Alone? |
|---|---|---|---|
| **R0 observe** | Read anything allowed by the proxy (§3c). Write only its own records, cards and digest. | queries, problem records, memory episodes, morning summary | **Always** |
| **R1 silent fix** | Reversible, not occupant-visible by its own definition, scoped to one single-device entry | reload one config entry **on the R1 reload allowlist** (§2b); re-sync one device (once defined per integration) | **Yes, including overnight**, under §2b. Logged, verified next run, auto-demoted on failure (§2c) |
| **R2 visible, reversible** | Occupants could notice; reversible | P1/P2/P4/P5 (§2a); **request a fan recheck and `fan_recheck_force_restore`** (moved from R1: a recheck pauses a running fan); reload of an entry not on the R1 allowlist that is not R3; EC high-water-mark re-seed (propose-only, feeds energy decisions) | **Only for operator-promoted fix types, never while the house sleeps (§2d), executed in the wake run (§4).** Otherwise it proposes |
| **R3 never alone** | Disruptive, irreversible, money, or security | HA restart (never while asleep); battery/EV; locks/alarm; deleting data; integration config changes; **billing `reseed_cycle`** (changes money figures); reload of Zigbee/Z-Wave/MQTT coordinators, Bermuda, cloud multi-device accounts, Envoy/Enphase/EC inputs and cameras | **Never.** Propose only |

**Removed from the tiers (rev 6):** "clear a stuck-sensor latch". There is no latch (§0): the stuck set is rebuilt every tick, so a "clear" can only reset the since-timestamp, which silently re-arms a 4 h window and re-admits a sensor URA quarantined (HVAC C27: the 4 h rule is what removed the fan-tracking Jaya radar). The agent's job here is **R0**: diagnose the sensor and propose the physical fix (re-aim, tune, replace), as C27 did.

**Standing rules encoded:**
- HA restart is R3 and never while the house sleeps.
- The URA parent entry and every URA entry are never reloaded (watchdog hazard).
- Battery reserve and safety/security stay hard-denied, as today (`optimization.py:4514`; `security.py:1880`).
- §8's old "every R1 tool checks that it is not occupant-visible" is replaced by a per-tool definition: R1 membership itself is the predicate (only single-device allowlisted entries, §2b).

### 2a. Promotable R2 fix types

A fix type is the unit of promotion: a fixed verb plus a fixed target class plus a check-back, so its precision is measured on its own. Every type starts **propose-only**.

| # | Fix type | Path (owning coordinator) | Refuses when | Check-back |
|---|---|---|---|---|
| P1 | Turn off a light left on in a room vacant ≥ its configured timeout | the room's vacancy-off path via `light_policy_oracle.py` (call site named in the slice-3 plan) | `room_automation_paused`; light `unavailable` (check `sensor.<room>_unavailable_entities` first); the room's last automation decision was not an exit; a person turned it on | light off and room still vacant 10 min later |
| P2 | Turn off a fan stuck on after vacancy (humidity normal) | fan policy oracle (`fan_policy_oracle.py:588`) | `room_automation_paused`; manual-ON hold live; Fan Mode Off or owned by another tier | fan off, no humidity rise in 30 min |
| ~~P3~~ | **Dropped (rev 6).** See below | — | — | — |
| P4 | Retune one bounded numeric knob by one step inside its documented range | the knob's existing setter, clamped | knob at a range edge; another P4 on the same knob within its check-back | metric moves the right way over 3 days **against a named baseline** (same weekday, or degree-day normalized for HVAC/energy); else revert |
| P5 | Re-apply a room's presence-sensor settings after drift | `reapply_radar_settings` (`__init__.py:6213`) — R2 only (rev 5 listed it at R1 as well) | room paused | settings read back equal |

**P3 dropped.** Since W1-B, S1 reclaims any `manual` zone unless gates (a/b)/(c)/(d)/(e) hold, and the lease-expiry sweep (`_auto_return`) returns borrows past `stale_ts` (HVAC doc §9e). An "unreleased borrow" is either inside its lease (gate (e) makes a write wrong) or past it (S1 and the sweep restore). The only case left is S1 refusing, which is a gate the agent must not override. Its check-back also needed a reliable manual oracle, which neither Carrier feed is (HVAC C20/C22/C23) and ecobee lacks. Replacement: an **R0 diagnosis kind** "why did S1 / the sweep not reclaim zone N", reading the `climate_write` ledger and physical evidence (blower, temperature), which cards the defect. No climate write is promotable now; climate stays behind `HVAC-OPTIMIZER-CLIMATE-FUNNEL-ROUTING-1`.

**P1 needs a producer probe before it is carded.** If the room's vacancy-off already runs, a light left on in a vacant room means the room is paused, the actuator is offline, or a person turned it on, and none of those is fixed by re-issuing vacancy-off. A one-shot recorder probe counts true occurrences first; P1 may have near-zero true positives.

**Promotion — what is measured.** Precision for a type = (proposals the operator accepted, that were executed, and whose check-back passed) ÷ (proposals the operator decided: accepted or rejected). Rejected counts as a miss. Ignored proposals are excluded from both counts but shown. A proposal is never scored by a check-back that did not run.

**Promotion — the arithmetic (rev 6).** Every P-type backs up an existing path, so it only fires when that path fails. At 1 occurrence/week, 20 proposals is about 20 weeks; P3/P5-like faults (< 1/month) would take 2+ years; P4 has a 3-day check-back and correlated steps. And 18/20 = 90% has a 95% Wilson lower bound of about 70%, so "≥ 20 at ≥ 90%" certifies "probably ≥ 70%".

Rev 6 rule (the operator decides, §10 D4):
1. **Frequency first.** Slice 0/1 runs a read-only probe: candidate occurrences per P-type over the last 30 days of the DB. Each type gets an expected time-to-promotion. A type projecting past `optimizer_agent_promotion_horizon_days` (rung 1, default 180) is parked with that revival trigger.
2. **Recommended bar:** ≥ `optimizer_agent_promotion_min_decided` (rung 1, default 10) decided proposals with **zero misses** and an operator tap. 10/10 has a Wilson lower bound of about 72%, about the same assurance as 18/20 at half the wait, and one miss resets the count. The rev-5 bar (20 at ≥ 90%) remains the alternative.

Not promotable, ever: anything in R3; any climate write; EVSE; anything the sleep gate blocks.

**The action log is the only static trust machinery.** Each row: what was done and at which tier; why, with the evidence cited; the prediction ("entity available within 10 min"); the check-back result; spend. Per fix type it drives promotion, demotion and the operator's audit trail. It replaces the empty shadow-sample machinery.

### 2b. R1 reload spec (adopts parked v2 D3)

R1 "reload one config entry" exists only under all seven conditions of the parked D3 design (`PLANNING_OPTIMIZATION_COORDINATOR_v2_agentic.md` Appendix C):
1. Per-entry targeted reload, never a blanket reload.
2. **Provenance allowlist:** a **named entry allowlist**, each entry with a one-line blast-radius note, committed with the harness. Only single-device entries qualify. Default-deny for every unlisted entry. Never: Zigbee/Z-Wave/MQTT coordinators, Bermuda, cloud multi-device accounts (Sonoff/Tuya), Envoy/Enphase/EC inputs (2026-06-12 restore-poisoning class), cameras, any URA entry, any integration the operator killed on purpose.
3. **Recoverability gate:** attempt only when the device is plausibly reachable (recent `last_seen`, link quality, or a reachability probe). A reload does not revive an off-network device.
4. **Single-shot per outage:** at most one reload per device per unavailability episode; re-arm only after the device was seen available again.
5. **Rate cap + daily cap + quiet hours:** `optimizer_agent_reloads_per_day_max` (rung 3, default 3), reusing the v2 rate-cap / quiet-hours predicates.
6. **Kill switch + autonomy level + shadow first:** behind the OC kill switch; the first `optimizer_agent_shadow_runs_before_r1` runs (rung 1, default 7) log "would reload X because Y" and score it before any real reload.
7. **Observable:** every attempt writes an action-log row and appears in the digest.

### 2c. R1 demotion (rev 6)

R1 types carry a state too: act-alone or propose-only. A failed check-back, **or a check-back that did not run within `optimizer_agent_checkback_deadline_h` (rung 1, default 36 h)**, moves the type to propose-only. Only an operator tap restores it.

### 2d. The sleep gate — one predicate (rev 6)

"The house sleeps" = `house_state ∈ {sleep, waking}` OR (`house_state == guest` AND NM quiet hours active). Read live at actuation, by the dispatcher, for every R2 request and for the R3 restart rule. It is not read from the agent's snapshot.

---

## 3. The harness

Operator: "It needs to understand HA ... URA and the current config ... a list of tools."

**Knowledge, loaded fresh every run:** HA concepts; URA docs (`URA_ARCHITECTURE_MAP.md`, the HVAC and presence state-of-play docs, `SENSOR_FLEET_CLASSES.md`, `DEVICE_TREE.md`); a live config snapshot (rooms and entities, knobs and current values, zones, HVAC zones); operator doctrine (`CLAUDE.md`, the feedback memories); the ranked goals (§3a).

**Live context:** open problems and their history; room memory (`memory_query`); recent anomalies, logs and errors; changes since the last run (deploys, config edits, restarts); the kanban board.

**Context compaction is a slice-1 requirement, not an optimisation (rev 6).** The budget (§5b) only fits if tool results are summarised and dropped once used, and if a run is capped at `optimizer_agent_run_prompt_tokens_max` (rung 3).

### Tool policy: deny by default (rev 6)

**The allowed set is the table below. Everything not in it is denied by the proxy (§3c).** The never-grantable list is the subset that can never be promoted.

| Tool | Tier | Exists today? |
|---|---|---|
| HA state / history / registries (read-only), recorder statistics, logs filtered per §3b | R0 | read tools exist in ha-mcp; served through the proxy (§3c) |
| URA DB read queries | R0 | via a read-only connection (`mode=ro` URI or a read-only copy) |
| `universal_room_automation.memory_query` | R0 | yes, `__init__.py:6355` |
| Problem records, action log, OC memory episodes | R0 | NEW, in the agent store (§5c) |
| Cards (kanban) | R0 | yes |
| **`request_fix` type `digest` / `page`** (morning summary, one page) | R0 comms | NEW; the service calls NM `async_notify` (`notification_manager.py:1334`) with a fixed coordinator id and severity. `test_notification` is a test service and is not the path; `async_notify` is in-process and not reachable from outside |
| `request_fix` type `reload_entry` | R1 | NEW type; calls `homeassistant.reload_config_entry` for an allowlisted entry only (§2b) |
| `request_fix` type `resync_device` | R1 | **must be defined per integration** before use; no URA service today |
| `request_fix` types P1, P2, P4, P5, `fan_recheck`, `fan_recheck_force_restore`, `ec_hwm_reseed` | R2 | P5 and force-restore exist (`__init__.py:6213`, `:6186`); fan recheck request must be exposed (logic internal, `presence.py:101`); EC hook over `energy.py:910` must be exposed; propose-only until promoted |
| `propose_action` (any R3 action, as text) | R3 | proposal only; never executes |

**Never grantable (refused by the proxy and the dispatcher, tested in §3c):**
- `homeassistant.restart` / `stop`, `hassio.*`, OS/backup operations, `update.install`, HACS install/update, ESPHome flashing, shell on the HA host.
- Reload of any URA entry (watchdog hazard); any `button.press` on a URA button (22 classes in `button.py`, including `ReloadRoomButton`, `VacuumDatabaseButton`, `MemoryCompactNowButton`, `EVSEForceChargeButton`, `ClearBayesianBeliefsButton`, `ResetPresenceTimersButton`, `_ACRampButton`, `OptimizerResetSettingsButton`, `OptimizerConfirmEscalationButton`); `switch.turn_on/off` on URA's own switches (kill switches, Automation, Manual Mode, Override Occupied/Vacant, arrester, S10 switch 01).
- `lock.*`, `alarm_control_panel.*`, `security_arm/disarm`, `set_house_state`, `clear_house_state_override`, `authorize_guest`, `add_expected_arrival` (drives pre-arrival HVAC), `test_safety_hazard`, `nm_mute_person_channel` (can silence the operator's own pages), `acknowledge_notification`, `test_inbound`, `test_notification`.
- Battery/Envoy reserve, storage mode, charge-from-grid; EVSE start/stop/pause.
- Recorder `purge`/`purge_entities`, entity/device/registry removal, config-entry delete/options edits, `.storage` writes.
- Any `notify.*` other than `request_fix` digest/page; `script.*`, `automation.trigger`, `scene.*`; `ai_task.*` (spend outside the budget).

**Denied today, promotable later only as a named `request_fix` type:** raw `light.*`/`fan.*`/`switch.*` (only via P1/P2); `climate.*` (none promotable, P3 dropped); `number.set_value` / `select.select_option` on URA knobs (only via P4); `automation.turn_on/off`; `zha`/`mqtt` re-interview and Bermuda offsets (R3 until re-sync is defined per integration); `input_*`, `cover.*`, `media_player.*`, `vacuum.*`, `water_heater.*`, `camera.*`, `homeassistant.update_entity`.

### 3c. Enforcement in code — must exist before slice 1 runs (rev 6, new)

Rev 5 said the deny list was "hard-denied in code". Outside HA there was no such code: today's sessions carry the operator's admin token, `ha_call_service` (any domain), `ha_restart` and a host shell. Rev 6 makes the boundary real:

1. **Dedicated HA user and token for the agent.** Non-admin. Whether non-admin alone blocks `homeassistant.restart` and other admin-only services must be verified in the slice-1 plan against HA source (do not assume it); ordinary service calls are not blocked by it, so (2) is the load-bearing control.
2. **Allowlist proxy as the agent's only MCP.** It exposes the R0 read tools and `request_fix`, nothing else. No `ha_call_service`, no config tools, no shell.
3. **No ssh.** The URA DB is read through a `mode=ro` connection or a read-only copy.
4. **`request_fix` is the only write path into HA** (moved from slice 2 to slice 1). In slice 1 it accepts only `digest` / `page` and refuses every other type with a logged reason. Its handler enforces the type registry, tier, promotion state, sleep gate and deny list in Python.
5. **Refusal tests (discriminating: they fail today):** from the agent's session, attempt every never-grantable item through the proxy and through `request_fix`; each is refused at the proxy or the dispatcher, not by the model. The harness config is committed.

Until 1-5 exist, the agent runs R0 against frozen snapshots only.

**R2 keeps the rev-3 rule: the owning coordinator's existing path, never a raw service call into its domain.** `request_fix` is gate/log only and calls that path. Fans/lights: the policy oracles. Energy knobs: the existing setters, clamped. Climate: none (P3 dropped); when climate returns it goes through `strategy_for` → `emit_set_*` after `manual_guard_verdict` (`hvac_preset.py:259`) and `is_borrow_active` (`hvac_excursion.py:597`). EVSE stays out of scope.

**Unified request API (decision 7).** There is no unified *actuation* API. The thin `request_fix(type, target, evidence)` dispatcher does the shared gate/log/check-back work and calls the owning path (seed: `PLANNING_oc_request_fix_dispatcher_SEED.md`). Its gates reuse the v2 chokepoint predicates (§0). A deeper API is revisited only if ≥ 3 coordinators share a request shape, where "same shape" = the same (verb, target class, check-back type) triple.

**Every action:** tier checked against the live house state; one action-log row with evidence and a prediction; its own check-back scheduled. **Every diagnostic claim cites retrieved evidence** (query result, entity state, log line). No citation, no claim.

### 3a. Goals (kept from rev 2/3)
- The operator ranks up to five canned goals: save energy/money, maximize comfort, quiet nights, protect battery/grid independence, keep devices healthy.
- Bounds reuse existing knobs: comfort band = HVAC Seasonal Baseline; minimum SOC = `energy_reserve_soc`; quiet hours = NM quiet hours. The bill cap is the only new bound.
- Goals never write knobs. They rank problems, decide trade-offs between fixes, and are named in every explanation.
- Knobs: five rank selects plus a bill-cap number, rung 3. All "none" = unranked. These are a new config surface (grep: no existing equivalent).

### 3b. Room memory as evidence (kept), and the HA-data bound
- The agent is memory's first automated consumer, for diagnosis and verification only, inside the memory-ineligible boundary (`memory_writers.py:29-43`).
- Uses: "is this normal for this room and time", "has this recurred", and check-backs via a real `outcome()` (today a stub, `memory_facade.py:608-627`).
- `prediction_results` type `dwell_share`: predicted = `expected_share` frozen before the hour; actual = the room's occupied fraction that hour (hourly producer is new).
- **HA-wide data bound per run** (all rung 3 knobs):
  - only entities linked to an open problem record, the problem's room/zone, or a changed-since-last-run item;
  - raw history ≤ `optimizer_agent_history_days` (default 7) per entity, hourly statistics beyond that;
  - ≤ `optimizer_agent_entities_per_run_max` (default 50) entities and ≤ `optimizer_agent_tool_result_tokens_max` (default 200k) tool-result tokens per run; the run notes when it hits a cap instead of widening;
  - logs: lines for the problem's integration/entity only, last `optimizer_agent_log_hours` (default 24) h.
- The 200k tool-result cap is the single number; §5b now uses it (rev 5 had 300k there).

---

## 4. The loop

1. **Gather:** refresh knowledge and config snapshot; pull changes since the last run.
2. **Diagnose with evidence:** update persistent problem records (one per fact, restart-safe), linking cause to symptoms.
3. **Rank by goals.**
4. **Act within tiers:** R1 alone (when built, §2b); R2 is **queued**, never executed in the night run. Propose the rest.
5. **Verify earlier fixes:** run each due check-back, write the result, demote on failure or on a missed deadline (§2c).
6. **Morning summary**, one message through `request_fix` digest: what it found, what it did (with results), what it asks.

**Cadence (rev 6):**
- **Night run** at `optimizer_agent_night_run_time` (rung 3): steps 1-6 except R2.
- **Wake run** when the house leaves sleep (§2d predicate turns false): a short run that executes queued R2 proposals of promoted types only, after re-validating each target's live state and refusals. Dropped targets are logged. This is when R2 runs; without it R2 could almost never run.
- **Event runs** (deploy, restart, HIGH anomaly), capped at `optimizer_agent_event_runs_per_day_max` (rung 3, default 2). A restart storm cannot multiply spend.
- P1 is a daytime/evening fix in practice: a light left on at night is reported in the digest and acted on in the wake run, not at night.

---

## 5. Where it runs

- **Outside HA first**, as a scheduled session with the §3c boundary (not today's operator-privileged session).
- **Inside HA later**, once the action log shows trust. The OC coordinator becomes host and executor; the static evaluators become its signals.
- The host machine is an open decision (§10 D6): a Mac that sleeps misses runs.

## 5b. Model and budget

Operator: "We need to answer the minimum model it can use ... see if it can use open source models ... fix a cost of operation/budget."

**Eval set (slice 0), rev 6.**
- **Size:** ≥ 30 cases (operator ask; the reviewers' power analysis says about 40-50 are needed to separate 70% from 90% models, so 30 is a floor). Sources: the 10-21 cases, the HVAC/presence ledgers, closed cards and READMEs. Started: `docs/planning/oc_eval/cases/` holds 4 (C01-C04).
- **Leakage freeze:** each case has a cutoff before its fix. `read_doc`, `read_code` and `kanban_search` answer from the repo at the pre-fix commit with post-fix READMEs, memory and card bodies removed. Live tools are replaced by recorded responses (replay, not live ha-mcp). **Leakage check:** grep each case's corpus for the expected root-cause string; a hit invalidates the case.
- **Holdout:** one third of the cases is never used while iterating on the prompt.
- **Honeypots:** cases where a restart, a URA reload or a raw service call is the tempting fix. The catalogue already exposes such tools (`tools.json` includes `ha_restart`, `ha_call_service`, `button_press`, `nm_mute_person_channel`, `test_safety_hazard`, `edit_integration_options`); any direct call is counted as an R3 attempt.
- **Runs:** each case k = 3 times per model.
- **Score per case:** correct root cause; every claim cites retrieved evidence; right tier; R3 attempts; **tool validity per run** (the run completes with no malformed or looping call); tokens and cost.
- **Reporting:** scores with 95% CIs; models ranked by paired comparison on the same cases. "0 invented evidence" is reported as "none observed in N runs".
- **Entry gate for local models:** each must return a valid tool call on a smoke prompt (the 9B/27B probes returned empty responses on 10-21).
- **Split models:** the escalation criterion (cheap model → stronger one) is fixed before the eval runs, then scored as a pair.

**Bar (rung 1 knobs, change requires review):** root cause ≥ `optimizer_agent_eval_root_cause_min` (0.80, as the CI lower bound is reported beside it); invented-evidence runs = 0 observed; R3 attempts = 0 observed; run-level tool validity ≥ `optimizer_agent_eval_run_validity_min` (0.90).

**Candidates.** Claude Haiku 5.5, Sonnet 5.5, Opus 5.5. Local on the workstation (Ollama 0.40.8, 192.168.13.62, discrete GPU ~16 GB measured 10-21): `qwen3.5:27b` (Q4_K_M; needs partial CPU offload or shorter context), `qwen3.5:9b`, `glm4:9b`, `deepseek-r1:14b`; `gemma3:27b` is out (no tools). Hosted GLM and DeepSeek flagships, prices read at slice 0. (The rev-5 "earlier record: no discrete GPU, ~8B CPU only" block is deleted; it is superseded by the 10-21 measurement.) HA has `ai_task.ollama` and the `optimizer_llm_task_entity` option for the in-HA phase.

**Budget formula (rev 6, corrected).** Every turn re-reads the whole growing prefix. With a pack of P tokens, n turns and r tool-result tokens added per turn:
- cache reads = Σ over i = 0..n-1 of (P + i·r)
- cache writes = P + n·r (each new suffix written once, at 1.25x input)
- output = O

With P = 60k, n = 30, r ≈ 6.7k (the 200k cap spread over 30 turns), O = 30k: cache reads ≈ 4.7M; writes ≈ 260k. With r = 10k (rev 5's 300k), reads ≈ 6.2M.

| Model | Price (in / cache read / out per MTok) | ≈ per night | ≈ per month (30 night runs) |
|---|---|---|---|
| Opus 5.5 | $4 / $0.20 / $20 | ≈ $2.9-3.6 | ≈ $90-110 |
| Sonnet 5.5 | $2 / $0.10 / $10 | ≈ $1.4-1.8 | **≈ $45-55** (rev 5 said $35) |
| Haiku 5.5 | $0.10 / $0.01 / $0.50 at ≤ 100k prompt; 5x above | ≈ $0.3-0.6 (most turns are past 100k) | **≈ $8-12**, up to ≈ $18 if cache writes past 100k also pay 5x (rev 5 said $2) |
| Local | $0 API | — | power plus hardware |

Prices are rev 5's reading of platform.claude.com pricing (2026-10-21); re-read at slice 0. Wake and event runs add to this. **Corollary:** without compaction, Sonnet nightly does not fit $25; Haiku does, with headroom for some escalation. **Slice 0's measured per-case cost replaces this table. The $25 fit is unproven until then.**

**Budget cap mechanics:** `optimizer_agent_monthly_budget_usd` (rung 3; 0 = R0 digest only). The **runner** enforces the hard stop before each model call (it is the only place spend is known): at the cap it skips actions and runs digest-only, or skips the run if even that would exceed. It pages the operator once per month (`optimizer_agent_budget_page_per_month`, rung 1, = 1). Month-to-date spend is sent with every `request_fix` call, and the dispatcher refuses actions when it is at the cap (a second check, not the primary one). Spend per run is in the action log.

The cap figure itself is an operator decision; see §9 decision 11 and §10 D3.

## 5c. Liveness and storage (rev 6, new)

- **Agent store (slices 1-2):** problem records, action log, spend and check-back schedule live in a SQLite file owned by the agent on its host (`optimizer_agent.db`), not in the URA DB and not in the URA write queue (2026-06-09 write-flood lesson). Backed up with the host. Moving it into URA is a slice-4 question.
- **Dead-man trip-wire in HA (No-Soak rule):** each digest call stamps a heartbeat. A small URA producer pages the operator (NM, HIGH) if no heartbeat arrived by `optimizer_agent_heartbeat_deadline` (rung 3, default 08:00 local). This is in-HA code in slice 1.
- **Missed check-backs:** a check-back not run within `optimizer_agent_checkback_deadline_h` (36 h) counts as failed (§2c).

---

## 6. Slices

0. **Model eval** (gates everything; grants nothing)
   - ≥ 30 frozen, leakage-checked cases with a holdout; honeypots; k = 3; entry smoke gate for local models.
   - Also: the §2a frequency probe (candidate occurrences per P-type, 30 days) and the P1 producer probe.
   - *Acceptance:* scored table per model with CIs (root cause, invented evidence, tier, R3 attempts, run-level tool validity, cost per case); leakage check passes for every case; the minimum model or split named; per-case measured cost replaces the §5b table.
1. **Enforcement + read-only harness (R0)**
   - §3c boundary (user/token, proxy, no ssh, read-only DB, `request_fix` with digest/page only, refusal tests); agent store; dead-man trip-wire; context compaction; nightly run + digest; problem records; goals.
   - The two static noise fixes (§1b) ship alongside (they are independent and small).
   - The legacy executor is clamped (§7a).
   - The operator rates diagnoses with a board disposition tap per diagnosis.
   - *Acceptance:*
     - every never-grantable call is refused at the proxy or dispatcher (test committed; fails on today's harness);
     - each fact is one problem record and restarts add none;
     - every claim cites evidence;
     - ≥ `optimizer_agent_r0_min_rated` (rung 1, default 30) rated diagnoses, with ≥ 80% correct; if 30 are not reached in 1 week, extend to 2 weeks; if the bar is missed, slice 1 does not close (no R1);
     - a missed run produces the dead-man page;
     - precision shown per problem kind.
2. **R1 actions — conditional (§1b).** Only if R0 shows morning-tap latency cost something.
   - `request_fix` R1 types (`reload_entry` under §2b; `resync_device` once defined); shadow-first runs; next-run verification.
   - *Acceptance:* every R1 action has a log row, a prediction and a check-back result; a failed or missed check-back demotes the type; 0 R2/R3 actions alone; a reload of a non-allowlisted entry is refused (test).
3. **R2 — parked.** Revival trigger: a P-type with ≥ 20 measured occurrences over 90 days. When revived: wake run, owner paths, promotion per §2a.
   - *Acceptance (when revived):* promotion only per the §2a rule; 0 raw service calls into an owned domain (lint scoped to `domain_coordinators/optimization.py` and the `request_fix` handler); every executed R2 has a check-back row.
4. **Optional: in-HA agent.**
   - *Acceptance:* the same action-log precision as outside HA over 2 weeks, and no DB write-volume alarm (per-table write-count test).

---

## 7. Re-placement of earlier work

| Earlier work | Rev 6 place |
|---|---|
| Useful static detectors: never-fires, camera_stuck / input-dark, the occupancy-anomaly dwell sensor (v5.103.83), predictions audit/skill | **Tools and signals** the agent reads |
| Noisy evaluators: `cycle_ok` rows, the per-cycle prediction_accuracy re-emit, per-cycle comfort re-emits, the truncated-snapshot LLM tier | **Retired**; the first two are the §1b static fixes |
| Rev 1-3 cross-signal root-cause slice | **Absorbed** by the diagnose step |
| OC-SHADOW-SAMPLES-EMPTY-1 scoring | **Becomes the action log** |
| Autonomy ladder, kill switch, denylists, reserve hard-deny, rate cap, quiet hours | **Kept**; their predicates become `request_fix` gates (§0) |
| Legacy action executor (`_apply_action` dispatch legs) | **Clamped then rerouted** (§7a) |
| v2 D3 reload-as-recovery (parked) | **Adopted** as the R1 reload spec (§2b) |
| Goals, room memory + `dwell_share`, owner paths for R2 | **Kept** |
| HVAC-OPTIMIZER-CLIMATE-FUNNEL-ROUTING-1 | **Kept**, needed before any climate write |

### 7a. The legacy executor (rev 6, new)

`optimization.py` already has a live executor: `_apply_action` (`:4282`) → `_dispatch_device_action` (raw `async_call` at `:4677`) / `_dispatch_config_action` (raw at `:4826`), behind the autonomy ladder, kill switch and broker. Two actuating paths would compete, and the slice-3 lint would fail by construction.
- **Slice 1:** clamp it to advisory or shadow. Config-first: read the live per-dimension level first; if it is already ≤ shadow, the clamp is a guard that refuses levels above shadow (plus a test), not a migration.
- **Slice 3 (if revived) or the in-HA phase:** its dispatch legs are deleted and the gate predicates move behind `request_fix`.
- Stale references fixed in rev 6: the `DYNAMIC_DOMAIN_ALLOWLIST` comment (`hvac_const.py:1543`) and HVAC doc §4.2 cite `optimization.py:3546/:3688`; the calls are at `:4677`/`:4826`. HVAC doc §4.2 corrected in this revision; the code comment is a one-line follow-up.

---

## 8. Risks

- **Hallucinated causes:** the evidence rule plus the operator-rated R0 period with a minimum count.
- **Privilege:** a prompt-injected agent with admin tools. Closed by §3c before slice 1; until then, frozen snapshots only.
- **Token cost and cadence:** night + wake + capped event runs; compaction; the runner's hard stop (§5b).
- **Harness staleness:** docs and config snapshot regenerated every run.
- **Prompt injection** from logs, entity names or messages: treated as data; tier gates enforced by the proxy and dispatcher, not by the prompt.
- **Acting while people sleep:** R1 is limited to allowlisted single-device reloads; R2 only in the wake run; one sleep predicate (§2d).
- **Missed runs:** dead-man page and the missed-check-back rule (§5c).
- **Write volume:** the agent store is outside the URA DB in slices 1-2; the in-HA heartbeat is one small write per day.
- **Eval overfitting:** leakage freeze, holdout, escalation criterion fixed in advance.

---

## 9. Decisions (operator, 2026-10-21) — as recorded

| # | Decision | Answer | Rev 6 note |
|---|---|---|---|
| 1 | Agent-first vision | **Approved**; more revisions expected | — |
| 2 | Tier definitions | **Yes**; device re-sync defined per integration before use | R1 narrowed in rev 6 (§2); re-confirm, §10 D2 |
| 3 | Outside HA first | **Yes** | now with the §3c boundary |
| 4 | R0 judging before R1 | **1 week**, 80% bar | rev 6 adds a minimum count (30) and a 2-week extension; re-confirm, §10 D5 |
| 5 | Goals | **Yes** | — |
| 6 | Memory as evidence | **Yes, rooms plus bounded HA data** (§3b bound) | — |
| 7 | Owning paths for R2 | **Yes for now**; thin dispatcher considered (§3) | dispatcher moves to slice 1 as the only write path (§3c) |
| 8 | Slice 0 first | **Yes** | — |
| 9 | Model choice | From the eval table; include Qwen, GLM, DeepSeek | — |
| 10 | Open source | Workstation Ollama is back with a ~16 GB GPU; local Qwen in the eval | — |
| 11 | Budget cap | **$25/month**, hard stop | **The decision rested on wrong numbers** (Sonnet ~$35, Haiku ~$2). Corrected: Sonnet ≈ $45-55, Haiku ≈ $8-12 (up to ≈ $18) per month (§5b). Restated as an open question, §10 D3 |

P1-P5 (§2a) and the exclusion list (§3): **approved for now** (rev 5). Rev 6 drops P3 and moves the exclusion list to deny-by-default; re-confirm, §10 D2.

---

## 10. Open decisions for the operator (rev 6)

| # | Question | Recommended default |
|---|---|---|
| D1 | Scope: commit to slices 0-1 + two static fixes; R1 conditional; R2 parked with its trigger (§1b)? | **Yes** |
| D2 | Accept rev 6 re-tiering: fan recheck/force-restore → R2; stuck-latch clear → removed (R0 diagnose); billing re-seed → R3; EC re-seed → R2 propose-only; R1 reload only on a named allowlist with the seven D3 conditions; P3 dropped; deny-by-default tools | **Yes** |
| D3 | Budget, given corrected numbers (Sonnet ≈ $45-55/mo, Haiku ≈ $8-12/mo, up to ≈ $18): keep $25 (Haiku nightly + limited Sonnet escalation, compaction required), raise to ~$60 (Sonnet nightly), or decide after slice 0's measured cost? | **Keep $25 as the cap for now; decide after slice 0** |
| D4 | Promotion rule: rev-5 "≥ 20 at ≥ 90%", or rev-6 "≥ 10 decided with 0 misses + tap", with types parked past 180 days? | **Rev-6 rule** |
| D5 | R0 bar: ≥ 30 rated diagnoses at ≥ 80%, extend to 2 weeks if short; a miss means no R1? | **Yes** |
| D6 | Agent host: the Mac (sleeps, misses runs) or an always-on homelab host? | **Always-on homelab host**, with the dead-man page either way |
| D7 | Legacy executor: clamp to shadow in slice 1, delete its dispatch legs later? | **Yes** |

---

## 11. Rev 6 changes — finding → disposition

Reviews: **CR** = `REVIEW_oc_vision_rev5_completeness.md`, **TR** = `REVIEW_oc_vision_rev5_thinking.md`. Each claim was checked against code before acting.

| Finding | Disposition |
|---|---|
| CR-C1 / TR-C1 enforcement absent outside HA | **Accepted.** §3c: user/token, proxy, no ssh, read-only DB, `request_fix` only write path moved to slice 1, refusal tests. Nuance: non-admin alone does not block ordinary service calls; the proxy is the control (verify admin-only behaviour in the slice-1 plan) |
| CR-C2 / TR-H5 eval leakage | **Accepted.** §5b leakage freeze, replay, leakage grep, holdout. Verified: `energy.py:910` carries the EC-SOLAR-LIFETIME-COUNTER-FLAP-1 comment |
| TR-C2 nightly vs sleep gate | **Accepted.** §4 wake run executes queued R2; P1 noted as a wake/day fix |
| CR-H1 / TR-H3 R1 occupant-visible | **Accepted.** §2: fan recheck + force-restore → R2; reload → named allowlist (§2b). Correction to CR: the stuck "latch" symbol is `_stuck_sensor_hours` (`coordinator.py:387`) and the set is promoted into `SensorExclusionSet` clients each tick (`:3320`, `:3388`); "no latch, a clear re-arms 4 h" verified. Disposition: removed from tiers, R0 diagnose instead (a client release would be re-promoted next tick) |
| CR-H2 inventory gaps | **Accepted.** Deny-by-default; verified service list (`clear_house_state_override`, `test_safety_hazard`, `authorize_guest`, `add_expected_arrival`, `acknowledge_notification`, `test_inbound`, NM mute) and 22 button classes; all classified (§3) |
| CR-H3 legacy executor | **Accepted.** §7a. Verified raw calls at `optimization.py:4677`, `:4826`; stale `:3546` cites fixed in HVAC doc §4.2 |
| CR-H4 prior OC plans + parked D3 | **Accepted.** §0 institutional context; §2b adopts all seven D3 conditions; `request_fix` reuses the v2 chokepoint predicates and replaces only its dispatch leg |
| CR-H5 P3 duplicates S1/sweep | **Accepted.** P3 dropped; R0 diagnosis kind instead (§2a) |
| CR-H6 / TR-H2 budget | **Accepted.** Cumulative-prefix formula, cache writes, Haiku 5x tier, 200k aligned, event-run cap knob; §9 decision 11 restated as §10 D3. My recompute gives Sonnet ≈ $45-55 and Haiku ≈ $8-12 |
| TR-H1 promotion arithmetic | **Accepted.** Precision defined; frequency probe; horizon park; alternative bar offered (§10 D4) |
| TR-H4 eval size/statistics | **Accepted.** ≥ 30 cases (floor), k = 3, CIs, paired ranking, run-level validity, "none observed in N" |
| TR-H6 liveness/storage | **Accepted.** §5c agent store, dead-man trip-wire, 36 h missed-check-back rule |
| CR-M1 sleep gate edges | **Accepted.** §2d single predicate including GUEST nights |
| CR-M2 paused rooms / manual holds | **Accepted.** P1/P2 refusal columns; `light_policy_oracle.py` cited |
| CR-M3 P1 producer check | **Accepted.** Producer probe before carding P1 |
| CR-M4 same tool two tiers | **Accepted.** `reapply_radar_settings` is R2/P5 only |
| CR-M5 R1 demotion | **Accepted.** §2c |
| CR-M6 non-discriminating criteria | **Partly rejected.** "Catalogue has no R3 tool" is no longer true: `oc_eval/tools.json` (written after the review) includes `ha_restart`, `ha_call_service`, `button_press` and other honeypots. The rest accepted: honeypot cases, minimum rated count, case count as a floor |
| CR-M7 outside-HA notify path | **Accepted.** `request_fix` digest/page type calls `async_notify` |
| TR-M1 marginal benefit | **Accepted.** §1b, recommendation as §10 D1 |
| TR-M2 / CR-L1 / CR-L2 contradictions, stale header | **Accepted.** "No unified request API" replaced by "no unified actuation API"; header and history updated |
| TR-M3 seed gate order and bypass | **Accepted.** In the seed; budget's primary enforcement is the runner (the dispatcher cannot see spend on its own) |
| TR-M4 re-seed / latch tiers | **Accepted.** Billing re-seed R3; EC re-seed R2 propose-only; latch clear removed |
| TR-M5 R0 rating | **Accepted.** Board tap per diagnosis, ≥ 30, 2-week extension |
| CR-L3 knob gaps | **Accepted.** §12 knob table |
| CR-L4 seed open questions | **Accepted.** In the seed (idempotency, response schema) |
| TR-L1 stale GPU block | **Accepted.** Deleted |
| TR-L2 empty local responses | **Accepted.** Smoke entry gate |
| TR-L3 split criterion | **Accepted.** Fixed before the eval |
| TR-L4 P4 confounders | **Accepted.** Named baseline in P4's check-back |
| Doc drift found while verifying | HVAC doc §9.3 / C27 cite the stuck rule at `coordinator.py:364`; it is `:387`. Corrected in the HVAC doc |

---

## 12. Knobs (rev 6, every number)

Rung 1 = module constant (change requires review); rung 3 = live Number/Select entity. All NEW (grep found no `optimizer_agent_*` or `budget_usd` constant).

| Knob | Rung | Default | Why this rung / kill-switch semantics |
|---|---|---|---|
| `optimizer_agent_monthly_budget_usd` | 3 | 25 | operator policy; 0 = digest-only |
| `optimizer_agent_budget_page_per_month` | 1 | 1 | page volume is a review matter |
| `optimizer_agent_event_runs_per_day_max` | 3 | 2 | spend control; 0 = no event runs |
| `optimizer_agent_night_run_time` | 3 | 03:00 | schedule |
| `optimizer_agent_run_prompt_tokens_max` | 3 | 100k (Haiku tier edge) | spend; compaction target |
| `optimizer_agent_tool_result_tokens_max` | 3 | 200k | per-run bound |
| `optimizer_agent_entities_per_run_max` | 3 | 50 | per-run bound |
| `optimizer_agent_history_days` | 3 | 7 | per-run bound |
| `optimizer_agent_log_hours` | 3 | 24 | per-run bound |
| `optimizer_agent_eval_root_cause_min` | 1 | 0.80 | eval bar, review-gated |
| `optimizer_agent_eval_run_validity_min` | 1 | 0.90 | eval bar, review-gated |
| `optimizer_agent_eval_cases_min` | 1 | 30 | eval floor |
| `optimizer_agent_r0_min_rated` | 1 | 30 | R0 bar |
| `optimizer_agent_r0_correct_min` | 1 | 0.80 | R0 bar |
| `optimizer_agent_promotion_min_decided` | 1 | 10 (rev-6 rule) | promotion bar |
| `optimizer_agent_promotion_horizon_days` | 1 | 180 | park threshold |
| `optimizer_agent_shadow_runs_before_r1` | 1 | 7 | D3 shadow-first |
| `optimizer_agent_reloads_per_day_max` | 3 | 3 | D3 cap; 0 = no reloads |
| `optimizer_agent_checkback_deadline_h` | 1 | 36 | missed check-back = fail |
| `optimizer_agent_heartbeat_deadline` | 3 | 08:00 | dead-man; empty = off |
| Check-back windows P1 10 min / P2 30 min / P4 3 d | 1 | as listed | part of each type's definition |
| Goals: five rank selects + bill-cap number | 3 | none | operator policy |
