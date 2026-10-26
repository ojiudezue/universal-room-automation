# AUDIT: room memory, and coordinator request / pub-sub APIs (2026-10-21, ~19:57 CDT)

Read-only. Input to operator approval of `docs/planning/VISION_optimization_coordinator_self_fixing_house.md` (read first, all 148 lines). Code paths are under `custom_components/universal_room_automation/` unless noted. DB reads were `ssh ha sqlite3` on the live DB, 2026-10-21 evening CDT.

Scope note: this is an API survey, not HVAC/presence diagnosis. I did NOT re-read `HVAC_ARCHITECTURE_STATE_OF_PLAY.md` in full for this audit; HVAC statements below come from code at the cited lines only, and anything about HVAC precedence rulings (D13, D48-D52) is deferred to the vision doc's own read of it.

---

## Q1. Room memory

### 1.1 Where it lives and its status

The system is "Hierarchical Entity Memory" (the "room memory" in the question). Docs:

| Doc | Status |
|---|---|
| `docs/planning/VISION_hierarchical_memory.md` | DRAFT v2, finalized 2026-08-02 (line 3). Five memory kinds: episodic, baseline, outcome, identity, plus facts (lines 17-60). |
| `docs/planning/ARCHITECTURE_hierarchical_memory.md`, `MVP_hierarchical_memory.md` | Architecture + MVP (Study A hand-build, then thin facade). |
| `docs/planning/PLANNING_memory_compactor.md` | Compactor plan (MEMORY-COMPACTOR-1). |
| `docs/planning/PLANNING_memory_roadmap_and_critique.md` | Roadmap/critique; "Status: DRAFT for operator review" (line 6) but its card is `done`. Recommends parking P8 (memory-informed decisions) permanently and not opening P9/P11 without evidence (lines 309-340). |
| `docs/planning/AUDIT_memory_writer_coverage.md` | Found `memory_writers._schedule` silently dropped writes (line 9-). Fixed by MEMORY-WRITERS-SILENT-DROP-1. |
| Assistant memory `feedback_memory_first_diagnostics.md` | Operator doctrine 2026-08-14: call `memory_query` before recorder or log mining. |

Kanban (`docs/planning/kanban.data.yaml`): MEMORY-PROGRAM-EPIC (:17514) `done`, MEMORY-COMPACTOR-1 (:17570) `done`, MEMORY-FIRST-DIAGNOSTICS-1 (:17625) `done`, MEMORY-WRITERS-SILENT-DROP-1 (:19628) `done`, MEMORY-ROADMAP-1 (:19766) `done`.

Shipped: episodes table + DAOs, the 7-verb facade, the `memory_query` service, the baseline Welford writer, the nightly compactor, 5 writers from PATH-ALPHA plus fan_recheck_outcome.
Parked or stubbed:
- Facade `outcome()` verb is a stub that always returns `insufficient_history` ("outcome_log:stage1_read_stub", `memory_facade.py:608-627`).
- Redaction is a stub, disabled (`PLANNING_memory_roadmap_and_critique.md` section 1.1).
- Memory-informed decisions (P8) are explicitly parked, and the "memory-ineligible boundary" forbids memory reads on safety, security arm/disarm, occupancy creation/release and reserve-floor decisions (roadmap section 1.4; `memory_writers.py:29-43`).
- Four registered episode types have NO writer: comfort_fan_on, config_changed, systemic_dropout, hazard_recurrent (`const.py:5356-5362`). `sensor_dropout` has a writer that has produced 0 rows in more than 2 months (`const.py:5348-5355`).

### 1.2 What it stores today (live DB)

Tables: `memory_episodes`, `memory_facts` (DDL `database.py:1903-1937`). Baselines are not a separate table: they live in `metric_baselines` under `coordinator_id='memory'` (`memory_baseline.py:1-12`).

`memory_episodes` (schema: node_id, episode_type, started_at, ended_at, adjudication, attrs_json, source_ref):

| episode_type | adjudication | rows | first | last |
|---|---|---|---|---|
| exterior_track | observed | 8,248 | 2026-08-06 | 2026-10-21 |
| actuation_conflict | unadjudicated | 5,356 | 2026-08-03 | 2026-10-21 |
| away_transition_blocked | observed | 416 | 2026-08-16 | 2026-10-21 |
| house_state_transition | observed | 318 | 2026-10-12 | 2026-10-21 |
| occupancy_phantom | phantom | 239 | 2026-08-04 | 2026-10-22 UTC |
| fan_transition_suppressed | phantom | 231 | 2026-08-03 | 2026-10-11 |
| fan_recheck_outcome | observed | 157 | 2026-10-12 | 2026-10-21 |
| comfort_fan_vetoed | confirmed | 150 | 2026-08-02 | 2026-10-13 |
| tracker_trust_excluded | observed | 28 | 2026-10-12 | 2026-10-18 |
| phantom_retro | phantom | 16 | 2026-10-12 | 2026-10-21 |

17 distinct node_ids. `memory_facts`: 982 rows (exterior_track_baseline 624, actuation_conflict_summary 257, phantom_recurrence 97, plus single rows for notification_hygiene, occupancy_baseline, occupancy_reliability, sensor_trust). `metric_baselines` memory scope: 252 rows, keys like `occupied:h09:away` on `room:study_a` with Welford mean, variance, count (517), allowlisted rooms only (`MEMORY_BASELINE_ALLOWLIST`, `memory_baseline.py:7-12`).

phantom_retro: 16 rows. Writer `write_phantom_retro` at `memory_writers.py:138`.

Vocabulary gate: `MEMORY_EPISODE_TYPES` (`const.py:5299`); an unregistered type is rejected at write time (`database.py:10024`). Writers: `memory_writers.py` (phantom_retro :138, away block reconcile :413, house_state_transition :604, fan_recheck_outcome :697), plus detector-ride writers in `fan_veto.py:561`, `coordinator.py:3807,4561`, `sensor.py:1875,1904`, `exterior_track_linker.py:687`.

### 1.3 Who reads it

- `memory_facade.py` `MemoryFacade` with 7 verbs: baseline, episodes, unusual, outcome (stub), narrative, profile, facts (`:367-941`). Access policy by caller_id tier prefix (`:147-217`).
- The only entry point in code is the `universal_room_automation.memory_query` service (`__init__.py:6253-6358`), default `caller_id="observer"`. `grep` found NO coordinator or sensor importing `MemoryFacade` or calling it in-process (only `__init__.py` constructs it, `:6241`). So no automated consumer today; consumers are the operator, dashboards and Claude sessions.
- `memory_compactor.py` reads episodes read-only and writes facts nightly (`nightly_maintenance.py:67`).
- `sensor.py:5251` exposes a memory status sensor (episode counts, baseline fold stats).
- Roadmap table also cites an "NM digest" reader (`PLANNING_memory_roadmap_and_critique.md` section 1.1); I did not verify that in code.

### 1.4 Is there a natural place to record occupancy prediction vs actual per room and hour?

Three candidate homes, with a recommendation.

1. **`prediction_results` (best fit; it is already the scoring ledger).** Schema: `room_id, prediction_timestamp, prediction_type, predicted_value, confidence, actual_value, error_value, person_id` (live schema). Live rows: `next_room` 177,243 (to 2026-10-22 00:55 UTC), `bayesian_occupancy` 6,159 (to 2026-10-21 22:05 UTC). Readers: the accuracy sensors (`sensor.py:15262,15325,15526`) and the Optimization prediction-validation pillar (`optimization.py:3693-3760`), per `AUDIT_predictions_room_zone_house_2026_10_21.md` row 3. A new `prediction_type` such as `dwell_share` (predicted = `expected_share`, actual = occupied fraction of that room-hour, error = difference) fits with zero schema change. The existing score consumers already read this table. Caveat: `RoomDwellModel` is trained on the same `environmental_data` samples it would be scored on (`room_dwell_model.py:3-10`), so scoring today's hour against a model that already contains it is in-sample. The score must use the expected_share frozen BEFORE the hour (what the anomaly sensor read at the time, `binary_sensor.py:3430-3470`) so it is genuinely out-of-sample.
2. **`metric_baselines` memory scope (partial fit).** `occupied:hNN:<house_state_family>` per room already stores the observed occupancy rate per hour (Welford mean, count) for allowlisted rooms (live rows above). That is the "actual" side. It holds no predicted side and keys by house-state family, not weekday/weekend, so it is not the same cell as `RoomDwellModel` ((hour, day type), `room_dwell_model.py:59`).
3. **`memory_episodes` (poor fit for continuous scoring).** It is for discrete adjudicated events. A new type (for example `occupancy_dwell_miss`) is reasonable only for notable misses (occupied for a long time in a cell with expected_share under the threshold). That event already exists as `SIGNAL_OCCUPANCY_ANOMALY` (`signals.py:41-45`, dispatched `binary_sensor.py:3603`) with zero consumers. Writing an episode on that signal would give the OC a persistent, queryable miss record per room. It needs a registered type (`const.py:5299`) and a writer-backed entry.

Recommendation: record the hourly scoring in `prediction_results`; optionally write anomaly rising edges as memory episodes so `memory_query` narrative/unusual can mention them. Falsifier: if `prediction_results` rows for `bayesian_occupancy` are scored on an entirely different cadence or room_id format than the dwell cell, the join breaks; I did not test that. Producer for `actual_value` for the dwell case does not exist today (unknown).

---

## Q2. Request and pub/sub APIs per coordinator

Method: read `domain_coordinators/signals.py` (300 lines, signal constants `:12-245`, payloads `:253-300`), grep of publishers and subscribers across `custom_components`, and the public methods of each coordinator. Publisher/subscriber classification for some signals is from a heuristic grep of the call context; those marked (?) I did not confirm line by line.

### 2.1 Signal surface (who publishes, who subscribes)

| Signal | Publisher | Subscribers |
|---|---|---|
| SIGNAL_HOUSE_STATE_CHANGED | Presence only, via one helper (`presence.py:8474-8505`, gated by boot-settle and observation mode) | hvac.py:1435, security.py:759, routine_forecaster.py, music_following.py:299, sensors (sensor.py:6659, :10421), __init__.py:3199 |
| SIGNAL_ENERGY_CONSTRAINT (payload `EnergyConstraint`: mode, setpoint_offset, occupied_only, etc., `signals.py:263-278`) | Energy (`energy.py:8674`) | HVAC (`hvac.py:1444`) |
| SIGNAL_SAFETY_HAZARD | Safety (`safety.py:2536`) | HVAC (`hvac.py:1505`), Security (`security.py:721`), Energy, music_following, anomaly_event |
| SIGNAL_SECURITY_EVENT | Security (`security.py:1035,1562`) | music_following.py:617 only |
| SIGNAL_PERSON_ARRIVING | Presence (`presence.py:5119,5445`), person_coordinator.py:622 | HVAC (`hvac.py:1491`), Security (`security.py:742`), music_following |
| SIGNAL_NM_ALERT_STATE_CHANGED | NM (`notification_manager.py:2558,3035,...`) | sensors (I did not enumerate) |
| SIGNAL_HOUSE_POLICY_UPDATE | CoordinatorManager (`manager.py:393`) | `sensor.py:5385` (display) |
| SIGNAL_OPTIMIZER_INTENT / _VETO | Intent: OC broker (`optimization.py:483`). Veto: sibling coordinators | Intent subscribers: Energy (`energy.py:12521`), Presence (`presence.py:8292`), Security (`security.py:733`). Veto subscriber: OC (`optimization.py:265`) |
| SIGNAL_ROOM_ENTRY_LIFECYCLE | Room entries / presence / substrate | HVAC fast path (`hvac.py:5426`), binary_sensor |
| SIGNAL_DYNAMIC_PRESET_TRANSITIONED | `dynamic_preset.py:769` | unknown |
| SIGNAL_OCCUPANCY_ANOMALY | `binary_sensor.py:3603` | none (documented zero consumers, `signals.py:41-44`) |
| SIGNAL_INCLEMENT_STATE_CHANGED, SIGNAL_FAN_RECHECK_STARTED/FINISHED, SIGNAL_MMWAVE_FAN_DEMOTED, SIGNAL_EGRESS_EXIT_BACKFILLED | defined in `signals.py` | I found no non-import reference for these in my grep (publish may use another constant spelling); treat as unverified |

Note: there are many `*_ENTITIES_UPDATE` / `*_READY` signals; those are sensor-refresh and startup-ordering plumbing, not coordination.

### 2.2 Coordinator table

| Coordinator | (a) Request API another coordinator can call | Signals published | (c) Arbitration among requesters | What OC needs for "request, don't write" |
|---|---|---|---|---|
| **HVAC (climate)** | YES for writes, but it is a write funnel, not a request queue: `emit_set_temperature` (`hvac_setpoint.py:436`), `emit_set_preset_mode` (:549), `emit_set_hvac_mode` (:820), `emit_set_activity_setpoint` (:899), `emit_select_comfort` (:1040). Each requires `site`, `zone_id`, `reason` and writes a `climate_write` ledger row. Caller still wraps `OverrideArrester.suppress()` itself (`hvac_setpoint.py` docstring last line; `hvac_override.py:3409`). Optional `gate` callable can DEFER the write (comfort-delay; deferred writes are dropped, not queued, `hvac_setpoint.py:7-20`). Also `force_nudge(zone_id)` (`hvac_override.py:7535`). No "ask HVAC to do X and let it decide" method. | none of the coordination signals listed above; it is mostly a subscriber. Preset transition via dynamic_preset (:769) | In-funnel guards only: freeze floor and deadband (`hvac_setpoint.py:19-28`), comfort-delay gate. Ownership/precedence between requesters lives inside HVAC's own logic (arrester, borrows). I did not re-verify it here. HVAC does NOT subscribe to `SIGNAL_OPTIMIZER_INTENT` (grep of `hvac*.py` finds no `honor_optimizer_intent`). | A typed request method on HVAC that takes (zone, intent, reason, requester=OC) and returns accepted/deferred/refused, calling the `emit_*` funnels and the arrester internally. Today the OC would have to call the funnels directly and handle `suppress` itself, which is the thing the vision wants to avoid. HVAC-OPTIMIZER-CLIMATE-FUNNEL-ROUTING-1 covers this. Allowlisted bypass: `DYNAMIC_DOMAIN_ALLOWLIST = {"optimization.py"}` (`hvac_const.py:1546-1555`). |
| **Energy / battery** | Setters for knobs only: `set_arbitrage_target` (`energy.py:11310`), `set_peak_buffer_target`, `set_ev_battery_drain_soc`, `set_dp_enabled`, etc. (`energy.py:11268-11647`). No "request a battery mode" API: decisions flow out of `BatteryStrategy._result` (`energy_battery.py:7068`) driven by the coordinator's own cycle. | SIGNAL_ENERGY_CONSTRAINT (`energy.py:8674`), SIGNAL_ENERGY_ENTITIES_UPDATE | Hard-coded strategy precedence inside the coordinator (TOU, reserve floor, inclement). `honor_optimizer_intent` (`energy.py:12573`) vetoes OC intents that target EVSE surfaces during off-peak or load-shed, plug entities under shed, any battery-strategy entity, and fails closed when TOU is unknown. | OC must not request battery reserve at all (already hard-denied, `optimization.py:~4514`). For anything else, a request API does not exist; the knob setters are the nearest thing and they are normal Number-entity paths. |
| **EVSE** | NONE as a public request API. `EVChargerController` (`energy_pool.py:463`) has `set_force_charge_override(until)` (:1810) and `release_all_*` (:3517-3625), driven internally by owners. | none of its own (rides Energy's) | Real arbitration exists: an owner registry with precedence rows (`energy_pool_owners.py:101-160` `OwnerDeclaration`, `OwnerRegistry`, peer-hold and dispatch_tag fields). It is for EC-internal owners, not external callers. Plug-tier `peer_holds_member` is documented as unconsumed (`energy_pool_owners.py` docstring item 6). | A new owner declaration and external entry point. None exists. Treat as NONE. |
| **Presence / house state** | Partial: `set_house_state_override(state_value)` (`presence.py:8619`), `get_house_state_override` (:8702); `house_state.py` `set_override`/`clear_override`/`force_state` (:267-321). These are operator-override verbs, not coordinator-to-coordinator requests. | SIGNAL_HOUSE_STATE_CHANGED, SIGNAL_PERSON_ARRIVING, fan-interference gate signal (`presence.py:7750`) | Inference ladder plus override adapter inside presence; `honor_optimizer_intent` (`presence.py:8340`) vetoes OC intents on presence-input sensors and in observation mode. | Presence is an input to the OC, not a target. OC should never write it (non-goal already). |
| **Safety** | NONE (`safety.py` exposes `check_thresholds` :773 as internal). | SIGNAL_SAFETY_HAZARD, SIGNAL_SAFETY_ENTITIES_UPDATE | Hazard severity inside Safety; Safety wins by construction because HVAC, Security and Energy subscribe and react. | Nothing: OC must stay out (vision section 3 "never automate" row). |
| **Security** | Yes, narrow: `handle_arm(armed_state, source=...)` (`security.py:2153`), `handle_disarm(source=...)` (:2191). | SIGNAL_SECURITY_EVENT, SIGNAL_SECURITY_ENTITIES_UPDATE | `honor_optimizer_intent` (`security.py:1880`) vetoes OC intents in observation mode and on any `lock.*` or `alarm_control_panel.*` target, unconditionally. | OC must never use arm/disarm. The veto already codifies it. |
| **Notification Manager** | YES, a real request API: `async_notify(coordinator_id, severity, title, message, hazard_type, location, source_anomaly_id, snapshot_*, route_reason)` (`notification_manager.py:1334`). Honours a messaging kill switch (:1365-1367) and re-reads severity config live. | SIGNAL_NM_ALERT_STATE_CHANGED, SIGNAL_NM_ENTITIES_UPDATE | Severity-based routing and channel config inside NM. The vision notes MEDIUM can land with no channel; that routing is NM-internal. | Already usable for "page the operator" (vision fix types 1-3). The OC needs to pick a severity that reaches a channel. |
| **Fan / comfort** | Partial: a shared ownership rule `fan_owner(room_config)` (`const.py:1296`) and `FanPolicyOracle` (`fan_policy_oracle.py`): "NINE `oracle.actuate` sites" serialize every URA fan write under a per-room lock (`fan_policy_oracle.py` docstring). `hvac_fans.py` has `pause_for_recheck` (:2144), `suppress_room_until` (:2065). `LightPolicyOracle` (`light_policy_oracle.py`) does the same for lights (a manual hold stops URA writes). | SIGNAL_FAN_INTERFERENCE_GATE_FIRED (`presence.py:7750`), recheck signals (unverified publisher) | Oracle verdicts (ALLOW/defer by manual hold, owner, safety) are the closest thing to real cross-requester arbitration in the codebase. | OC fan or light actuation should go through the oracle (`oracle.actuate`), not `fan.turn_on`. The oracle is an in-process call, not an OC-facing request API. |
| **Optimization (OC, for comparison)** | Raw `hass.services.async_call(domain, action, data)` at `optimization.py:4677` (device actions via `_dispatch_device_action`, :4549) and `:4826` (config actions, with `_clamp_numeric_to_band`). Target is whatever entity the finding's `proposed_action` names (`target_entity` and `service`); not limited to a coordinator-owned surface. Pre-checks: battery-reserve hard deny, egress-pause check for `climate.*` (:4568-4590), `broker.suppress_climate()` (:4666). | SIGNAL_OPTIMIZER_INTENT (`optimization.py:483`), SIGNAL_OPTIMIZER_FINDING_EMITTED | Veto handshake only: Energy, Presence, Security can veto. HVAC, NM, Safety, fans do not take part. | This is the gap the vision describes. |
| **Halo** | External; not examined. | unknown | unknown | unknown |

### 2.3 Honest summary

- A real request API exists in exactly two places: **NM** (`async_notify`) and **the HVAC write funnels** (`emit_set_*`). The HVAC funnels are a chokepoint that rejects or defers a write; they take a `site` id and write a ledger row, but they do not ask HVAC's owners (arrester, borrow, S1) for permission, so the caller still has to do the `suppress()` handshake.
- **EVSE and battery have no external request API.** Their "arbitration" is private to the Energy coordinator. External influence is limited to Number/Select knob entities and `honor_optimizer_intent` vetoes.
- **Security and Safety** are intentionally not targets.
- **Fans and lights** have the most mature arbitration (oracles with locked consult-emit-note), but as in-process calls.
- **Pub/sub** is event notification only: no signal carries a "request" and no reply is addressable, except the OC intent/veto pair, which is an advisory yes/no handshake the OC itself opens, and which HVAC, NM and the fan/light oracles do not join.
- Therefore the vision's "request, don't write" rule (section 5) describes a contract that does not exist yet for any domain other than NM; it must be built per coordinator. HVAC is the nearest to done (funnels exist), EVSE/battery the furthest.

### 2.4 Falsification and limits

- If any coordinator exposes a public `request_*` style method I missed, my greps (`request|override|hold|suppress|propose|notify|apply_|emit_|claim|pause` on public method names in the hvac*, presence, house_state, NM, security, safety files) would have shown it; for Energy/EVSE I grepped only `set_*`, `release_*`, `pause/resume` patterns and read `energy_pool_owners.py`.
- Unverified: subscribers of NM_ALERT_STATE_CHANGED, DYNAMIC_PRESET_TRANSITIONED; publishers of the INCLEMENT and FAN_RECHECK signals; Halo.
- I made no HA service calls and no repo edits other than this file.
