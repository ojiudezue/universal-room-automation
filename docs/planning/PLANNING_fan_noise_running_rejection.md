# PLANNING — Running-fan mmWave noise rejection (fix-up of the existing mechanisms)

**Status:** Rev 2 (2026-10-11) — plan-review 2026-10-11 findings 1–12 applied. Rev 1 shipped C1a chosen + REUSE sensor_capability + REUSE quarantine. Rev 2 corrects C1a's HVAC bookkeeping discharge, respects manual-ON holds, REUSES the ActuatorReconciler availability-flap counter for C3 Part B, restates a buildable falsifiable invariant, adds discriminating ACs, scopes ZV 5-min rule + live motion-sensors audit for C2, fixes C4 restart-rehydrate scaling and the model_id resolver source, and corrects C3 Part A to hold last-known-good so flaps don't toggle every "fan on" reader. **Tier 2**; requires one adversarial plan review of Rev 2 before build. **READ FIRST, COMPLETELY, by planner / builder / reviewer:** `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` and `docs/architecture/SENSOR_FLEET_CLASSES.md` (both read completely by this planner on Rev 2 edit, 2026-10-11).

**Evidence base (measured 2026-10-11, 7-day recorder window + URA DB since v5.84.1):** Study A held occupied ~26 h/week while empty with the fan on (1,541 min); fan-recheck released Study A correctly 28× but 27 were undone by its own fan restore (mmWave re-latch 11–696 s later, median ~60 s); D2 sustain demotion fired 0× in every room and is unreachable in 7/10 fan rooms; the 5 s transition gate fired 27× in 7 days, 23 on dead/flapping fan entities, and 26/27 were followed by occupancy 2–12 s later. Radars latch 55–240 s after a fan starts (p50) and clear 28–825 s after it stops, by sensor family.

**Falsifiable invariant (Rev 2 — buildable).** For every fan room, the weekly "empty + fan ON" false-hold minutes measured against BLE ground truth (±3 min) MUST fall from the 2026-10-04→10-11 baseline toward target per-family values below, AND no fan recheck VACATED verdict may land in a room where BLE places a tracked person inside the room within ±3 min of the verdict ("BLE-present-vacate" count MUST NOT rise versus the same probe replayed over the baseline week).

Mechanism bound (stated so it can be falsified by code inspection, not physical measurement): a fan-recheck pause for a tracked, EMPTY room with family F resolves (VACATED or OCCUPIED_CONFIRMED) within `arm_ticks × tick_s + spindown_s + window_s × family_factor_F × room_type_factor` seconds, plus at most one `cooldown_s` wait before re-arming. Family factors in Rev 2:

| Family | Measured p90 clear | `family_factor` (Rev 2) |
|---|---|---|
| Zigbee ZK / ZX | 345 s | 2.0 (vs 60 s default = 120 s window) |
| ESPHome LD2410 / LD2412 (LD24xx) | **not measured in the 7-day window** — set `family_factor = 3.0` as a bounded-but-explicit assumption; FIRST post-ship measurement either confirms or triggers a C4 follow-up card | 3.0 (explicit, measured in week 1) |
| Generic / unknown | 600 s | 1.5 (default; conservative) |

Sleep-state scope (Rev 2 correction, matches code): the fan-recheck sleep veto is **bedrooms only** (`presence_fan_recheck._evaluate_eligibility:487-491` reads `_still_armed_eligible` which gates sleep veto on `is_bedroom`). Non-bedroom rooms (Study A, Living Room, Game Room) may be VACATED during HOME_NIGHT / SLEEP / WAKING — intentional in current code and in Rev 2's design. The BLE-present-vacate guard metric below is the primary non-bedroom protection.

**Config companion (no code, done alongside):** point Guest Bedroom 1 / Media / Game Room fan config at their live `_2` entities; Master Bedroom RF fan + Exercise `fan.fan_switch_3` need physical fixes (operator). Study A ZG-204ZK tuned 2026-10-11 (motion 5, static 6, distance 2.5 m, anti-interference ON) — before/after measured separately so its effect isn't credited to the code.

---

## Institutional context verified (prior-art audit, Rev 2 2026-10-11)

Operator directive 2026-10-11: *"make sure you do a prior art context-wide audit. Don't want to rebuild what we have already — instead reuse gold patterns."* This section is the proof-of-work. **Rev 2 adds the ActuatorReconciler availability-flap primitive (missed in Rev 1), the `_classify_entity_kind` substring fallback in `presence.py:413`, and the full "fan on" reader list that C3 Part A must preserve.**

### A. Code surfaces grepped

| Area | File:line | Finding |
|---|---|---|
| Capability layer | `domain_coordinators/sensor_capability.py:172` `derive_capability()` | Pure-module resolver, operator overrides via `CONF_SENSOR_CAPABILITIES` (`const.py:559`). Vocabulary: `TIER1_CAPABILITIES` incl. `motion`/`mmwave`/`occupancy`/`pir`/`pir_split`/`bed`/`camera_presence`/`ble_presence` (`const.py:503-520`). **Byte-identical defaults** when nothing is declared. Note: `derive_capability` is pure and consults CONF lists + overrides only — it does **NOT** read `model_id` (verified: no `model_id` reference in `sensor_capability.py`). Any model-keyed classifier (C4 family) must call the HA device registry explicitly. |
| Role resolver | `domain_coordinators/sensor_role.py:17-18` | Only wired consumer today: `coordinator._detect_duty_cycle_stuck`. Pure, HA-free. `CANDIDATE_FOR_STUCK` / `CORROBORATOR_FOR_ROOM` live. |
| Operator override in-flight | `config_flow.py:12334,12360,12487` | Game Room already declares `binary_sensor.0xa4c1382e60e05225_presence` as `{"kind": "pir"}`; Guest Bedroom 2 Matter as `mmwave`. Override surface works today; defect is fan mechanisms do not consult it. |
| Name-based classifier fallback | `presence.py:413 _classify_entity_kind` | **Rev 2 addition.** Substring fallback that WARNs and runs ONLY for entities absent from every CONF list. Out of scope for C2 (will not fire for our known entities), but listed so the reviewer sees it was checked and not missed. |
| D2 (sustain) | `coordinator.py:2159 _d2_motion_sensors_present` | Imports `fan_veto.MMWAVE_NAME_PATTERN` and filters by **entity name** (regex). Fail-closes when filtered list is empty → unreachable in ZV-only rooms. |
| Fan-away veto (actuation) | `fan_veto.py:61 MMWAVE_NAME_PATTERN`, `fan_veto.py:146-148 _has_recent_motion` | Same regex, same name-based filter. Three mechanisms disagree about ZV. |
| Fan-transition CREATION gate | `coordinator.py:3601-3745` + `const.py:875 FAN_TRANSITION_SUSPECT_WINDOW_S = 5.0` | Kill switch = 0.0. Reads `presence.get_fan_last_transition(room)`. Stamps memory-episode `fan_transition_suppressed` → adjudication `phantom`. |
| Fan listener (stamps transitions) | `presence.py:3719-3832 _handle_fan_change` | Stamps on ANY state_changed OR percentage attr change, including transitions to/from `unavailable`/`unknown`. `is_on = False` when unavailable (`:3738-3739`); `_fan_on_rooms` discard on unavailable (`:3787+`); `_fan_on_since` reset (`:3793-3794`); `_fan_off_at` write (`:3818-3830`). This is the C3 bug surface. |
| **"Fan on" readers (full set — Rev 2)** | — | Rev 1 missed these; C3 Part A MUST preserve them against unavailable/unknown flaps. `_fan_on_rooms`: `presence.py:3839+ _compute_fan_interference_rooms`, `binary_sensor.py:589`, `sensor.py:5693`, `coordinator.py:2910` (D2 grace), `coordinator.py:4320`. `_fan_on_since`: `coordinator.py:2910,4320`, `presence.py:4312`. `_fan_off_at`: `coordinator.py:3559-3580` (retro-phantom writer). `_is_entity_on` live-state read: `presence_fan_recheck.py:1045-1050`. `get_fan_last_transition`: `coordinator.py:3663` only (the gate C5 retires). |
| Recheck state machine | `domain_coordinators/presence_fan_recheck.py:1-1379` | STATES `idle/armed/paused/restoring/cooldown`; OUTCOMES `vacated/occupied_confirmed`; LAYERS `L1/L2/L3`; HVAC handshake via `_fan_pause` → `FanController.pause_for_recheck` + suppress-until ISO (3703-3719); `_fan_restore` at `:793`. HIGH-STILL-RISK bedrooms gated at `:94`. |
| Recheck call site (D5 precedence) | `presence_fan_recheck.py:493-495` | Already consumes 7 CM-entry timing knobs; room-type `_recheck_factor` scales window per room type (`ROOM_TYPE_RECHECK_FACTOR`). C4 extends this exact pattern. |
| Recheck manual-OFF cooldown veto | `presence_fan_recheck.py:529` `_fan_in_manual_cooldown` | Recheck already vetoes while a manual-OFF cooldown is live. **No manual-ON hold check exists** (grep `manual_on` in `presence_fan_recheck.py` → 0 hits). This is Rev 2 Finding 2's gap. |
| Recheck PAUSED rehydrate stale threshold | `presence_fan_recheck.py:1297-1300` | `window = DEFAULT_FAN_RECHECK_WINDOW_S * 2` (constant, 120 s). With Rev 2 bedroom × family factor, true window grows well past 120 s → stale check kills a legitimate pause. Rev 2 fixes. |
| Recheck COOLDOWN rehydrate | `presence_fan_recheck.py:1347-1349` | Reads `DEFAULT_FAN_RECHECK_COOLDOWN_S` directly, not the live CM knob. Pre-existing Bug Class #53. Rev 2 fixes alongside the 1800→900 default flip. |
| Exclusion primitive | `domain_coordinators/sensor_exclusion.py:1-176 SensorExclusionSet` | Multi-writer, per-client-provenance, per-tick `reset_tick()` + `promote(client,entity,reason)` + `is_excluded()`. STEP-EXCLUDE-1..4 invariants. |
| Chatter detector | `domain_coordinators/chatter_detector.py:1-80` | Sub-T_floor burst detector. Sub-1-s burst — does NOT fit a ~40 s availability flap. |
| **ActuatorReconciler availability-flap primitive (Rev 2 — MISSED in Rev 1)** | `actuator_reconciler.py:117 _FAN_KEYS = (CONF_FANS,)`, `:436-497 _handle_state_change` + `_flap_record_transition`, `:1084-1110 _flap_record_transition / _flap_should_quarantine / _flap_enter_quarantine`, `:1124-1167 check_quarantine_release`, `:1182 flapping_detail` | **Already covers fans today.** Records every unavailable→available edge on `CONF_FANS`, applies `_flap_triple()` (threshold / window / stability) governed by `CONF_FLAP_SENSITIVITY` named buckets, quarantines on breach, auto-releases after stability window, exposes `flapping_detail(entity_id)`. `sensor.py:1964-1975` already surfaces a quarantined fan under `sensor.<room>_unavailable_entities` with `reason: "flapping"`. This is the ~40 s flap rule the plan was deferring to OC-STUCK-SENSOR-GENERALIZE-1. |
| UnavailableEntitiesSensor | `sensor.py:1782-1783` | `fans` is already in `_ACTUATOR_LIST_KEYS`. The "add fan entities to the surface's input list" step from Rev 1 was redundant (Finding 10). |
| Recheck apply-release | `coordinator.py apply_fan_recheck_release` | Hook that drops occupancy on VACATED outcome. |
| HVAC fan controller | `hvac_fans.py:2079-2136 pause_for_recheck` + `:1700-2300 restore_after_recheck` / `_set_fan_state` + `:2250-2289 AWAY-veto "leave off" skip branch` + `:668-700 "turned off externally" branch` opens `manual_off_cooldown` + `:2190-2240 manual_on_hold_paused_at` extension logic | Fan writes delegate here. `pause_for_recheck` turns entities off but does **NOT** clear `RoomFanState.is_on`; only `restore_after_recheck` (or an operator action) clears it. If recheck skips the restore call, the next `update()` sees `is_on=True` with the entity off → "turned off externally" branch opens a 1 h `manual_off_cooldown`, clears any manual-ON hold, and the recheck self-vetoes via `_fan_in_manual_cooldown`. The AWAY-veto skip branch at `:2266-2287` is the correct "leave off" discharge: `is_on=False`, `speed_pct=0`, `trigger=""`, `last_on_time=""`. |
| Comfort-fan veto predicate | `fan_veto.is_veto_relevant`, `fan_veto.veto`, `fan_veto._get_house_state:80-108` | Called by 3 actuation sites (`automation.py`, `hvac_fans.py`, `actuator_reconciler.py`). C2 lands in `_has_recent_motion`. |

**Context-wide grep for 'witness'/'corroborat'/'veto'/'hold'/'grace'/'refractory'/'cooldown' confirms:** every pattern URA needs for C1b (if later chosen), C4 (watch-window per family), and C5 (post-fan-on corroboration window) exists as reusable gold pattern (`_fan_on_since` seed stamp, adjacency / zone-tier queries, cooldown idiom). No new primitive invented.

### B. Plans / audits / catalogs consulted

| Doc | Relevance |
|---|---|
| `PLANNING_fan_noise_mode2_ble_pause_recheck.md` | Original recheck plan — the state machine, D1 trigger conditions, D1.5 BLE drop-authorization, HVAC handshake, restart matrix. Rev 2 C1a is an in-place behaviour change to `_fan_restore` ("leave off" mode); no new state. |
| `PLANNING_fan_noise_mitigation_layers1_2.md` + `_layer2_actuation.md` | Three-mechanism complementarity now in PRESENCE §6. |
| `PLANNING_fan_trust_state_extension.md` | `FAN_TRUST_STATES = {HOME_NIGHT, SLEEP, WAKING}` — bedroom-only sleep veto; non-bedrooms proceed through sleep as coded (Rev 2 invariant honours this). |
| `PLANNING_fan_recheck_d2_deadlock_fix.md` | `is_recheck_eligible` inert-sink probe pattern. |
| `PLANNING_sensor_capability_vs_role.md` | Gold pattern for C2. |
| `PLANNING_stuck_sensor_consequence.md` + `PLANNING_oc_stuck_sensor_generalize.md` | **Rev 2 re-reads this**: OC-STUCK-SENSOR-GENERALIZE-1 is for cross-kind generalized stuck detection, not specifically fan availability flap. Since ActuatorReconciler already covers fan availability flap (above), Rev 2 reads from the reconciler for C3 Part B and leaves OC-STUCK-SENSOR-GENERALIZE-1 to its original scope (sensor-side stuck detection), not fan-availability flap. |
| `PLANNING_sensor_health_surfacing.md` | `SensorExclusionSet` contract + `UnavailableEntitiesSensor` surface. `fans` already in `_ACTUATOR_LIST_KEYS`. |
| `AUDIT_mmwave_only_rooms_2026-07-31.md` Findings 1/2/6 | Finding 6 = root-cause of name-based classification. |
| `docs/articles/mmwave_fans_transition_gate.md` + `mmwave_fan_alignment_probe_results.md` | **Do NOT re-cite as justification to disable the gate** — PRESENCE §10.1 corrects. |

### C. Memory bodies pulled

- `feedback_context_wide_scoping.md`, `feedback_config_first_before_code.md`, `feedback_marginal_benefit_pushback.md`, `feedback_suppression_needs_discharge.md`, `feedback_tier2plus_prior_art_scan.md`, `reference_hvac_fans_two_sites`.

### D. REUSE-or-BUILD verdict per deliverable piece (Rev 2)

| Piece | Verdict | Gold pattern reused | File:line |
|---|---|---|---|
| C1a "do not re-arm fan on VACATED" | **REUSE** AWAY-veto "leave off" branch in `restore_after_recheck` | `hvac_fans.py:2266-2287` | — |
| C1a `_fan_restore` call still runs on VACATED (with `leave_off=True` arg or equivalent) | **REUSE** existing restore discharge path | `presence_fan_recheck.py:793`, `hvac_fans.py restore_after_recheck` | — |
| C1a manual-ON hold handling (Rev 2 — Finding 2) | **REUSE** `_fan_in_manual_cooldown` idiom; add symmetric `_fan_in_manual_on_hold` eligibility veto | `presence_fan_recheck.py:529`, `hvac_fans.py:2094-2100,2190-2240` | — |
| C1a cross-mechanism re-arm after VACATED | **REUSE** `on_room_tick` eligibility re-eval + `hvac_fans.FanController` normal update | `presence_fan_recheck.py:284`, `hvac_fans.py` | — |
| C2 capability lookup | **REUSE** `derive_capability()` + `TIER1_CAPABILITIES` | `sensor_capability.py:172`, `const.py:503-520` | — |
| C2 operator override | **REUSE** `CONF_SENSOR_CAPABILITIES` | `const.py:559`, `config_flow.py:12334,12487` | — |
| C2 helper "is fan-immune witness?" | **BUILD (small)** — 15-line pure helper | mirrors `sensor_role._CORROBORATOR_KINDS` | `sensor_role.py:59-70` |
| C2 pre-ship live motion_sensors × model_id audit (Rev 2 — Finding 7) | **BUILD (one-shot read-only script)** — audits every room's `motion_sensors` list against the device registry's `model_id`; any entry whose `model_id` resolves to a radar family (ZK/ZX/LD24xx/Screek) is flagged and gets a `CONF_SENSOR_CAPABILITIES` `kind: mmwave` override declared in options flow BEFORE build. The resulting table is committed as `docs/planning/AUDIT_motion_sensors_live_models.md` and becomes the C2 acceptance fixture. Audit covers BOTH main house and Wigton registries (operator rolling URA to additional homes 2026-10-03/04, per `project_single_user_no_backcompat`). | measure-before-build + hand-build-fixture rules | — |
| C2 ZV "not fan-immune within ~5 min after fan→on" rule (Rev 2 — Finding 7) | **DECISION:** v1 ships WITHOUT the 5-min gate in code AND updates `SENSOR_FLEET_CLASSES.md` §Rules in the same commit to record Rev 2's reasoning: C3 Part A (Rev 2) holds `_fan_on_since` across unavailable flaps so the gate (when added) can rely on it; the gate itself is deferred to a follow-up card because its marginal benefit over C1a + C2 live audit is small for the main house (only Game Room has a measured latch, 3/11 within 5 min) and the gate's design is coupled to C3 Part A landing first. Follow-up card: `FAN-ZV-POWERON-TRANSIENT-GATE-1` with trigger "post-ship week-1 measurement shows ZV false-vacate rate > 1/week in any fan room". | marginal-benefit pushback | — |
| C2 D2 witness check | **REWRITE** `_d2_motion_sensors_present` to consult helper, drop regex, keep a BUILD-only safety net: filter OUT entities whose live `model_id` resolves to a radar family even if filed under `motion_sensors` — this preserves D-MED-2 protection in Finding 7 against operator mis-filing until the C2 audit is complete | — | `coordinator.py:2159` |
| C2 fan_veto witness check | **REWRITE** `_has_recent_motion` filter to consult helper, drop regex, same model_id safety net | — | `fan_veto.py:146-148` |
| C2 recheck eligibility | **NO CHANGE** in v1 (eligibility already requires `occupancy_source == "mmwave"` for N consecutive ticks via `recent_occupancy_sources`; capability routing is upstream of that classifier). | — | `presence_fan_recheck.py:436-611` |
| C2 transition gate | **NO CHANGE** — gate uses mmwave-sole classifier from upstream, not name regex. | — | `coordinator.py:3601-3745` |
| C3 Part A stamper guard (Rev 2 — reshaped) | **REUSE** last-known-good pattern. On `old_state.state in _UNAVAILABLE_STATES or new_state.state in _UNAVAILABLE_STATES`, DO NOT update `_fan_last_transition`, `_fan_on_rooms`, `_fan_on_since`, or `_fan_off_at` — hold the previous known-good belief. Exception: unavailable→on when prior known-good is off = real wall-switch power-on; stamp as a legitimate transition (preserves the real power-on signal Finding 8 flagged as being dropped by Rev 1's naive guard). | symmetric to the existing `is_on` fail-closed idiom at `:3738-3739` but applied to BELIEF carryover | `presence.py:3752-3832` |
| C3 Part B flap→quarantine (Rev 2 — REUSE, not DEFER) | **REUSE** `ActuatorReconciler._flap_*` + `check_quarantine_release` + `flapping_detail`. The reconciler already quarantines fan entities per `CONF_FLAP_SENSITIVITY`. Consumers that read "fan state unknown" semantics check `reconciler.flapping_detail(entity_id) is not None` and treat it as "fan unreliable this tick"; recheck eligibility adds `_fan_in_actuator_quarantine` veto symmetric to `_fan_in_manual_cooldown`; the five `_fan_on_rooms` readers listed in §A fall through C3 Part A's last-known-good belief, which is correct — reconciler quarantine is for the actuation side; belief carryover is for the inference side. | ActuatorReconciler flap primitive | `actuator_reconciler.py:117,436-495,1084-1110,1124-1167,1182` |
| C3 "fan entity unreliable" diagnostic | **REUSE** `UnavailableEntitiesSensor` — `fans` already in `_ACTUATOR_LIST_KEYS` (Rev 2 Finding 10: no edit needed). | `sensor.py:1782-1783,1964-1975` | — |
| C3 flap→exclusion sensor-side generalization | **STILL DEFERRED** to OC-STUCK-SENSOR-GENERALIZE-1, but with scope corrected: OC-STUCK-SENSOR-GENERALIZE-1 is for presence/motion-sensor-side stuck/flap behaviour across kinds (not fan-availability flap, which the reconciler already owns). | — | — |
| C4 per-family watch window | **EXTEND** `_recheck_factor` to multiply by `SENSOR_FAMILY_RECHECK_FACTOR` keyed by resolved family. **Family resolver source:** HA device registry read for the room's dominant presence-sensor entity, lookup `device.model_id` → family map in `sensor_capability.FAMILY_BY_MODEL_ID` (new module constant, rung 1). **Dominant-family rule:** the family with the most entities in the room's `CONF_PRESENCE_SENSORS` list (ties broken by iteration order). **Fallback:** family `"unknown"` → factor 1.0 (byte-identical v1 behaviour); WARN once per room per boot. | `_recheck_factor` + `_timing_config` sweep | `presence_fan_recheck.py:1004,1103` |
| C4 cooldown 1800 → 900 default | **CONFIG CHANGE** — `DEFAULT_FAN_RECHECK_COOLDOWN_S` default (`const.py:707-708`). | — | — |
| C4 PAUSED rehydrate stale threshold (Rev 2 — Finding 9) | **FIX** — compute `window = effective_window_s * 2` where effective = `DEFAULT_FAN_RECHECK_WINDOW_S × room_type_factor × family_factor`. Resolves via `_timing_config()` + room entry context. | — | `presence_fan_recheck.py:1297-1300` |
| C4 COOLDOWN rehydrate uses DEFAULT, not live knob (Rev 2 — Finding 9, pre-existing Bug Class #53) | **FIX** — route through `_timing_config()` to read live `CONF_FAN_RECHECK_COOLDOWN_S`. | — | `presence_fan_recheck.py:1347-1349` |
| C4 family-scaling kill switch | **BUILD** — `CONF_FAN_RECHECK_FAMILY_SCALING_ENABLED` CM-entry switch, DEFAULT True. | — | — |
| C5 retire 5 s gate | **CONFIG CHANGE** — `FAN_TRANSITION_SUSPECT_WINDOW_S = 0.0`. | — | `const.py:875` |
| Measurement regime | **BUILD (small)** — session-scratchpad probe scripts into `scripts/fan_noise/`; one-shot read-only. | measure-before-build | — |

### E. Gold patterns index (updated Rev 2 — intended to be copied into PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md after this ships)

| Pattern | Where | When to reuse |
|---|---|---|
| **Capability layer + CONF overrides** | `sensor_capability.py:172 derive_capability()` + `CONF_SENSOR_CAPABILITIES` (`const.py:559`) | ANY classification question about a sensor. NEVER regex entity names. Does NOT read `model_id`; call device registry for model-keyed classification. |
| **Role query matrix (pure, HA-free)** | `sensor_role.py:17-18 role_for(entity, room_config, query)` | SAME sensor under different queries. |
| **SensorExclusionSet multi-writer quarantine** | `sensor_exclusion.py` | Sensor-side "untrust this vote this tick". |
| **ActuatorReconciler availability-flap counter (Rev 2)** | `actuator_reconciler.py:117 _FAN_KEYS`, `:436-497`, `:1084-1110`, `:1124-1167`, `:1182 flapping_detail`, surface at `sensor.py:1964-1975` | ANY "actuator entity is flapping unavailable↔available at ~tens of seconds" question. Reads `CONF_FLAP_SENSITIVITY` named buckets. Covers lights + fans today; extensible by adding keys to `_FAN_KEYS`/`_LIGHT_KEYS`. Consumers call `reconciler.flapping_detail(entity_id)` or check `flapping_entities()`. |
| **Recheck state machine** | `presence_fan_recheck.py` | Any "stop → re-measure → decide" flow with HVAC-handshake and restart matrix. |
| **Inert-sink eligibility probe** | `presence_fan_recheck._INERT_SINK` + `is_recheck_eligible` | Cross-mechanism gate probes. |
| **CM-entry timing knobs via sweep** | `presence_fan_recheck._timing_config` | Family of operator-tunable live knobs with DEFAULT_* fallback. **Rehydrate paths MUST route through this, not DEFAULT_* directly** (Rev 2 Finding 9). |
| **Fan listener (stamp transitions) — last-known-good belief carryover (Rev 2)** | `presence.py:3719 _handle_fan_change` + `_fan_last_transition` / `_fan_on_rooms` / `_fan_on_since` / `_fan_off_at` + `get_fan_last_transition` | Any "did a fan just do something?" window query. **Guard unavailable/unknown at the stamp site by holding the last known-good state, not by zeroing.** Preserve real wall-switch power-on (unavailable→on when prior was off). |
| **Kill-switch constant + knob ladder** | `FAN_TRANSITION_SUSPECT_WINDOW_S` module constant; `CONF_FAN_RECHECK_*` CM-entry Numbers; `CONF_ROOM_FAN_RECHECK_ENABLED` per-room switch | Rung 1/2/3. |
| **Memory-episode adjudication write** | `coordinator.py:3701-3729` log_memory_episode `fan_transition_suppressed` → adjudication `phantom` | Durable observability. |
| **FAN_TRUST_STATES scope — bedrooms only (Rev 2 clarification)** | `hvac_const.FAN_TRUST_STATES`, consulted at `presence_fan_recheck.py:487-491` and `_still_armed_eligible:969-973` gated on `is_bedroom` | Bedroom-only sleep veto; non-bedrooms proceed through sleep. The BLE-present-vacate guard metric is the non-bedroom protection. |
| **HVAC "leave off" discharge (Rev 2)** | `hvac_fans.py:2266-2287` AWAY-veto skip branch in `restore_after_recheck` | ANY path that needs to end a recheck pause WITHOUT re-arming the fan while keeping all discharge duties (clear `is_on`, clear `fan_recheck_suppress_until`, reset `manual_on_hold_paused_at` safely, call `note_recheck_restore`). |

---

## C1 — Fan recheck undoes its own correct "empty" verdict  [C1a, Rev 2]

**Problem (unchanged).** Recheck VACATED verdict is immediately re-latched by `_fan_restore`'s unconditional re-arm. 27 of 28 Study A releases bounced in 11–696 s.

**Solution — C1a Rev 2: on VACATED, still call `_fan_restore`, but in a "leave off" mode that reuses the existing AWAY-veto skip branch.** The fan was running for a person who has left; normal fan logic re-arms it when real occupancy returns via the standard `on_room_tick` path and `hvac_fans.FanController.update`. The "leave off" mode must run EVERY discharge duty the normal restore runs (so HVAC's bookkeeping doesn't go stale), and must only skip the actual ON write.

**Smallest change.**

1. `presence_fan_recheck._restore` (`:785-849`): on `outcome == OUTCOME_VACATED and not forced`, call `_fan_restore(ctx.room_name, ctx.snapshot, leave_off=True)` instead of the normal restore. All other branches (OCCUPIED_CONFIRMED, `forced=True`, cancel-driven) still restore ON.
2. `presence_fan_recheck._fan_restore` (`:793`): new `leave_off: bool = False` kwarg, forwarded to `hvac_fans.FanController.restore_after_recheck`.
3. `hvac_fans.restore_after_recheck`: when `leave_off=True`, take the existing AWAY-veto branch at `:2266-2287` unconditionally (bypasses the `is_veto_relevant`/`should_veto_comfort_fan` check that currently gates it) — sets `room_fan.is_on=False`, `speed_pct=0`, `trigger=""`, `last_on_time=""`, and clears `fan_recheck_suppress_until` + calls `note_recheck_restore` the same way the ON path does. **This is why we re-use the AWAY-veto branch rather than inventing a new "fake manual OFF":** the branch already does the right discharge, so Rev 2 just reaches it under a new condition.
4. `manual_on_hold_paused_at` safety (Rev 2 — Finding 2): the restore path at `:2190-2240` adds the pause elapsed back onto a live manual-ON hold. In `leave_off=True` mode this is UNSAFE (the person's hold would be silently extended against an off fan). Rev 2: if a manual-ON hold is live at restore-time AND `leave_off=True`, do NOT touch the hold timers (`manual_on_hold_paused_at` is cleared without adjusting hold-end), AND treat the recheck as a FORCED RESTORE instead of leave-off — the fan goes back on because the operator asked for it. This is the "respect a live manual-ON hold" rule from Finding 2 (operator intent beats recheck inference). Document in `_evaluate_eligibility` with a new `_fan_in_manual_on_hold` veto so the recheck doesn't ARM against a live hold in the first place; the restore-time check is the backstop for a hold that lands DURING the pause.

**Discharge for the suppression** (per `feedback_suppression_needs_discharge`):

- Re-arm of the fan is immediate on the next real occupancy edge via the HVAC fan controller's normal update cycle.
- `fan_recheck_suppress_until` cleared by the leave-off branch at `:2266-2287` (not deferred).
- `RoomFanState.is_on` cleared → no fake `manual_off_cooldown` opens (Finding 1 closed).
- `manual_on_hold_paused_at` reset without arithmetic drift (Finding 2 closed).
- `apply_fan_recheck_release` on the room coordinator still fires; cooldown still arms via `_enter_cooldown`.
- Operator backstop: `switch.<room>_automation`, `switch.<room>_manual_mode`, direct manual on/off (manual-on bypass path at `hvac_fans`).
- Restart: fresh ctx; recheck cooldown decayed per Rev 2 Finding 9 fix; HVAC decides.

### Acceptance Criteria (Rev 2 — Findings 1, 2, 5, 6)

- **Verify (code — Finding 1 anchor):** `_restore` with `outcome == VACATED and not forced` calls `_fan_restore` with `leave_off=True`; `hvac_fans.restore_after_recheck` with `leave_off=True` takes the `:2266-2287` discharge branch and does NOT call `_set_fan_state(..., True, ...)`. Mutation anchor: dropping the `leave_off` kwarg forwarding causes `test_vacated_takes_leave_off_discharge_branch` to fail at the exact assertion that `is_on` is cleared without a service-call write.
- **Verify (code — Finding 1 bookkeeping):** post-leave-off, with real-clock advance past `fan_recheck_suppress_until`, calling `FanController.update()` with the entity live-OFF does NOT open a `manual_off_cooldown` (no "turned off externally" branch taken). Unit test with mocked clock + mocked entity state.
- **Verify (code — Finding 2):** `_evaluate_eligibility` returns `veto_reason="manual_on_hold_live"` when a manual-ON hold is live; a VACATED verdict with a hold that lands DURING the pause forces a restore ON (not leave-off). Test: start pause, inject manual-ON hold mid-pause, verdict VACATED → fan is ON after restore AND the hold's end-time is NOT silently extended.
- **Verify (DB — Finding 6, replaces non-discriminating 15-min AC):** post-ship, for every VACATED verdict in `ura_activity_log`, the per-entity `binary_sensor.<room>_occupied` state **between 60 s and 900 s after the verdict timestamp**, WHILE BLE places all tracked persons OUT of the room per `person.*` + `sensor.<person>_room`, MUST remain `off`. A re-latch inside that window with BLE still away = regression. (The 15-min window of Rev 1 was inside the cooldown and could not discriminate; this one is.)
- **Verify (DB — Finding 5 recheck-specific guard):** VACATED-while-BLE-present count = count of VACATED verdicts where a tracked `person.*` resolves to this room via `sensor.<person>_room` within ±3 min of the verdict. **Replay the same probe over the 2026-10-04→10-11 baseline week** (recheck already ran then; the restore-loop was papering over wrong vacates). Rev 2 ships iff `baseline_count >= post_ship_count`. A rise of ≥1/week = roll back to Rev 1 behaviour or escalate to C1b.
- **Sensor:** `fan_recheck_last_outcome` = `vacated` AND fan `state` = `off` at `last_attempt_at + 15 s` AND again at `last_attempt_at + 300 s` (if BLE still shows room empty).
- **Test:** `test_fan_recheck_restore_leave_off_on_vacated` (unit — service-call count = 0); `test_vacated_does_not_open_manual_off_cooldown` (unit — RoomFanState `is_on` cleared, cooldown map empty); `test_manual_on_hold_live_vetoes_recheck_arm` (unit); `test_manual_on_hold_lands_during_pause_forces_restore` (unit); `test_vacated_discharges_suppress_until_and_hold_paused_at` (unit).
- **Live:** 1 week post-ship — Study A empty-room-fan-on hold minutes drop from 1,541 min/week baseline toward <200 min/week; BLE-present-vacate count DOES NOT rise versus baseline-replay.

**Non-goal.** C1b (restore-with-corroboration-window) is DEFERRED; revisit if C1a's residual proves meaningful.

---

## C2 — Classify sensors by capability, not entity name  [REUSE sensor_capability, Rev 2]

**Problem (unchanged).** Three mechanisms disagree about ZV due to `MMWAVE_NAME_PATTERN` regex. ZV sensors named `…_presence` fail the regex and vanish from D2; same regex includes ZVs out of fan_veto.

**Solution.** One small pure helper on top of `derive_capability()`:

```python
# domain_coordinators/sensor_capability.py — appended, pure, HA-free
_FAN_IMMUNE_WITNESS_KINDS: frozenset = frozenset({
    CAPABILITY_KIND_MOTION,       # ZV + real PIR
    CAPABILITY_KIND_PIR,
    CAPABILITY_KIND_PIR_SPLIT,
    CAPABILITY_KIND_BED,
    CAPABILITY_KIND_CAMERA_PRESENCE,
    CAPABILITY_KIND_BLE_PRESENCE,
})

def is_fan_immune_witness(room_config, entity_id) -> bool:
    cap = derive_capability(room_config, entity_id)
    return cap is not None and cap.kind in _FAN_IMMUNE_WITNESS_KINDS
```

Then:

- **D2** `_d2_motion_sensors_present` (`coordinator.py:2159`): consult helper; drop regex.
- **fan_veto** `_has_recent_motion` (`fan_veto.py:146-148`): consult helper; drop regex.
- **D-MED-2 safety net (Rev 2 — Finding 7):** both call sites ALSO filter OUT any entity whose live `model_id` resolves to a radar family (ZK/ZX/LD24xx/Screek) per `sensor_capability.FAMILY_BY_MODEL_ID` even if it is filed under `CONF_MOTION_SENSORS`. This preserves protection against operator mis-filing until the pre-ship live audit catches every case. One registry read per entity, cached per boot.
- **recheck eligibility / transition gate:** no code change.

**Pre-ship live motion_sensors × model_id audit (Rev 2 — Finding 7, MANDATORY before build).** Script `scripts/fan_noise/audit_motion_sensors_models.py` reads every URA room config entry's `CONF_MOTION_SENSORS` (both main-house and Wigton registries), joins to `device_registry.model_id` for each entity, and emits `docs/planning/AUDIT_motion_sensors_live_models.md` listing every entity whose model resolves to a radar family. Operator declares `CONF_SENSOR_CAPABILITIES` `{kind: mmwave}` overrides for each; the audit table is the C2 acceptance fixture. **No build begins until the audit table is empty of unresolved radars-filed-as-motion.** (Operator ask covers both houses because Wigton = house 2 going live weekend 2026-10-03/04.)

**ZV steady-vs-transient subtlety (Rev 2 — Finding 7 decision).** v1 ships WITHOUT the 5-min `_fan_on_since` gate in code. Rationale: measured latch rate is low (Game Room 3/11 within 5 min; others insufficient data), the gate is coupled to C3 Part A landing first (otherwise flaps reset `_fan_on_since` every ~20 s), and marginal benefit over C1a + C2 live audit is small. In the SAME commit, update `SENSOR_FLEET_CLASSES.md` §Rule 3 to record: "URA treats ZV as fan-immune witness in steady state. The ~5-min post-fan-on transient (measured 3/11 Game Room) is NOT currently gated in code; rely on C1a + C3 Part A + per-family recheck factor to catch the residual. Follow-up card: FAN-ZV-POWERON-TRANSIENT-GATE-1." Code and doc agree in the same commit (per PRESENCE §0 ownership rule).

**Operator overrides.** No new override needed: `CONF_SENSOR_CAPABILITIES` already live.

### Acceptance Criteria

- **Verify (code):** `MMWAVE_NAME_PATTERN` has exactly 2 live code consumers before this change (grep: `fan_veto.py:148`, `coordinator.py:2171`); after this change, 0 in `coordinator.py` and `fan_veto.py`. Rev 2 Finding 11 note: `quality/tests/test_mmwave_fan_demotion.py` imports the regex; the regex module constant is retained with a `# retired — use is_fan_immune_witness()` comment rather than deleted, so the test continues to compile without a cycle-adjacent test edit. `presence.py:413 _classify_entity_kind` substring fallback is OUT OF SCOPE (fires only for entities absent from every CONF list and WARNs when it does); confirmed by grep.
- **Verify (behavior):** in Game Room (ZV with declared `kind: pir`), `_d2_motion_sensors_present()` returns True (today returns False).
- **Verify (acceptance fixture — Finding 7):** `docs/planning/AUDIT_motion_sensors_live_models.md` exists, lists every room's motion_sensors × model_id join at commit time, and has zero unresolved radars-filed-as-motion (every such entity carries a `kind: mmwave` override declared in options flow). Audit covers both main-house and Wigton registries.
- **Verify (code — D-MED-2 safety net):** both `_d2_motion_sensors_present` and `_has_recent_motion` call the model-id safety net; dropping the safety net causes a mutation test (mis-filed ZK in `motion_sensors` without override) to fail.
- **Test:** unit — `test_fan_immune_witness_zv_default_motion`, `test_fan_immune_witness_mmwave_declared`, `test_safety_net_filters_misfiled_radar_by_model_id`. Mutation-anchor on `_FAN_IMMUNE_WITNESS_KINDS` membership.
- **Live:** D2 fire count rises from 0 in ≥5 of the 7 previously-unreachable fan rooms within 1 week; BLE-present-vacate count DOES NOT rise.

**Non-goal.** No new CONF field. No change to `TIER1_CAPABILITIES`. No role resolver expansion. No ZV 5-min gate (deferred, carded).

---

## C3 — Dead fan entities fake fan activity  [guard-only in-cycle, Rev 2]

**Problem.** 23/27 recent fan-transition gate fires came from entities flapping `unavailable ↔ off/on` every ~20 s (6 fan entities ~2,050 flips/day, ~50% unavailable). `presence.py:3752-3832` stamps every "fan on" belief (`_fan_last_transition`, `_fan_on_rooms`, `_fan_on_since`, `_fan_off_at`) on ANY state change including unavailable↔state edges. Rev 1's naive "zero on unavailable" guard dropped real wall-switch power-on events and left five downstream readers toggling.

**Solution (two parts, both in-cycle — Rev 2 Finding 3 reclassifies Part B from DEFERRED to REUSE).**

**Part A — last-known-good belief carryover (this cycle; Rev 2 Finding 8).** In `_handle_fan_change` at `presence.py:3752-3832`:

- When `new_state.state in _UNAVAILABLE_STATES` (fan went unavailable/unknown): DO NOT update `_fan_last_transition`, `_fan_on_rooms`, `_fan_on_since`, or `_fan_off_at`. Hold the last known-good belief. Rationale: a flapping fan is UNRELIABLE, not newly-off; downstream readers should keep their previous belief until a non-flap edge arrives (ActuatorReconciler Part B is the reliability oracle).
- When `old_state.state in _UNAVAILABLE_STATES and new_state.state not in _UNAVAILABLE_STATES`: the fan just came back from unavailable. If the prior known-good `is_on` was equal to the new live state → NOT a transition (hold). If the prior known-good `is_on` was DIFFERENT from the new live state → treat as a real transition (stamp `_fan_last_transition`, update `_fan_on_rooms` / `_fan_on_since` / `_fan_off_at` normally). This preserves a real wall-switch power-on (prior=off → unavailable blip → on=real).
- When neither state is in `_UNAVAILABLE_STATES`: current behaviour unchanged.

Downstream consumer semantics (all FIVE readers listed in §A table — Rev 2 Finding 8):

| Reader | File:line | Behaviour under Rev 2 Part A |
|---|---|---|
| `_compute_fan_interference_rooms` | `presence.py:3839+` | Reads `_fan_on_rooms`; last-known-good means interference flag is stable through flaps. |
| `binary_sensor.<room>_fan_interference` (or similar) | `binary_sensor.py:589` | Stable through flaps. |
| `sensor.<room>_fan_on_minutes` (or similar) | `sensor.py:5693` | No spurious off/on tick accumulation during flaps. |
| D2 grace | `coordinator.py:2910` | `_fan_on_since` holds; grace window not reset by flaps. |
| Retro-phantom writer | `coordinator.py:3559-3580` + `_fan_off_at` write at `presence.py:3818-3830` | No spurious retro-phantom writes on flap-driven off edges. |
| `_fan_on_since` reader at `coordinator.py:4320`, `presence.py:4312` | — | Stable. |
| Recheck `_is_entity_on` | `presence_fan_recheck.py:1045-1050` | Reads LIVE state (not belief); will see `False` during an unavailable moment and MAY veto a recheck arm on `no_fan_on`. That is correct — don't recheck a fan we can't observe. Part B (below) adds a separate "fan unreliable" veto so recheck does not arm against a quarantined flapper either. |

**Part B — REUSE ActuatorReconciler flap counter as the "fan unreliable" oracle (Rev 2 Finding 3, promoted from DEFER).** `ActuatorReconciler` already records every unavailable→available edge on `CONF_FANS` entities (`actuator_reconciler.py:117,436-497,1084-1110`), applies the `CONF_FLAP_SENSITIVITY` threshold/window/stability, quarantines on breach (`:1098-1110`), auto-releases (`:1124-1167`), and exposes `flapping_detail(entity_id)` (`:1182`). It already surfaces a quarantined fan under `sensor.<room>_unavailable_entities` with `reason: "flapping"` (`sensor.py:1964-1975`).

In-cycle wiring:

- Add `_fan_in_actuator_quarantine(room_name) -> bool` to `presence_fan_recheck`, symmetric to `_fan_in_manual_cooldown` at `:529`. Consults the room's reconciler and returns True iff any configured fan entity is in `_flapping`.
- Add this veto to `_evaluate_eligibility` so the recheck does not ARM a pause against a quarantined flapper.
- The five `_fan_on_rooms` readers in Part A table do NOT need a separate "fan unreliable" check — Part A's belief carryover is the correct inference-side treatment (the reader was going to see the LAST GOOD belief anyway).

OC-STUCK-SENSOR-GENERALIZE-1 remains at its original scope (presence/motion sensor-side flap generalization across kinds), NOT fan-availability flap, which the reconciler already owns.

### Acceptance Criteria

- **Verify (code — Part A belief carryover):** on `new_state in _UNAVAILABLE_STATES`, `_fan_last_transition`, `_fan_on_rooms`, `_fan_on_since`, `_fan_off_at` are UNCHANGED. Mutation: removing the guard causes `test_fan_belief_held_through_unavailable_edge` to fail (asserts the five readers all return the pre-flap value through a 100-edge flap).
- **Verify (code — Part A power-on preservation):** `unavailable → on` when prior known-good `is_on=False` IS stamped as a real transition. `test_wall_switch_power_on_through_unavailable_blip_still_stamps`.
- **Verify (code — Part B reconciler reuse):** `_fan_in_actuator_quarantine` consults `reconciler.flapping_entities()` and vetoes `_evaluate_eligibility`. Mutation: removing the veto causes `test_recheck_does_not_arm_against_quarantined_fan` to fail.
- **Verify (metric — Finding 8 replaces vacuous gate-count AC):** post-ship, the `_fan_on_rooms` membership for the 6 flapping-fan rooms (Media/Game/Guest-down ceiling fans, both patio, Master-BR RF) is **constant across any 60-s window containing ≥10 unavailable↔off edges on their fan entities** (today: toggles continuously). Also: retro-phantom writes attributed to `_fan_off_at` on flap-driven off edges drop toward zero. (The old "gate fire count ≤2/week" AC is dropped — C5 retires the gate so that metric is tautologically met.)
- **Sensor:** `sensor.<room>_unavailable_entities` lists the flapping fan entity with `reason: "flapping"` (already works today via reconciler quarantine; no code change needed — Rev 2 Finding 10).
- **Test:** `test_fan_belief_held_through_unavailable_edge`, `test_wall_switch_power_on_through_unavailable_blip_still_stamps`, `test_recheck_does_not_arm_against_quarantined_fan`, `test_fan_on_rooms_membership_stable_during_flap_storm`.
- **Live:** within 1 week, membership of `_fan_on_rooms` is stable for the 6 flapping-fan rooms (no spurious toggles); retro-phantom rate from flap-driven `_fan_off_at` writes drops to ~0.

**Non-goal.** No sensor-side flap→exclusion generalization in-cycle (that is OC-STUCK-SENSOR-GENERALIZE-1 for presence/motion sensors). No new entity.

---

## C4 — Recheck timing is one-size-fits-all  [Rev 2]

**Problem.** Default spindown 30 s + window 60 s + cooldown 1800 s. Measured clear-time p90 varies 51 → 825 s by family; false-negatives then eat a 30-min cooldown (19 misses in Study A/week). Rev 2 additionally fixes two pre-existing restart-rehydrate defects on the same code path (Finding 9).

**Solution.**

1. **Cooldown default** `DEFAULT_FAN_RECHECK_COOLDOWN_S` 1800 → 900 (`const.py:708`). Operator can still raise via existing CM-entry Number. Rung 3 (live-tunable).
2. **Per-family watch factor.** Extend `_recheck_factor` (`presence_fan_recheck.py:1103`) to multiply by `SENSOR_FAMILY_RECHECK_FACTOR` keyed to the room's dominant presence-sensor family. **Resolver source (Rev 2 Finding 9a):** HA device registry read via `homeassistant.helpers.device_registry.async_get(hass)` on the room's `CONF_PRESENCE_SENSORS` entities, lookup each entity's `device.model_id` in a new module constant `FAMILY_BY_MODEL_ID` in `sensor_capability.py` (rung 1 — review-only, empirical). Dominant family = most-frequent family in the room's presence list (ties broken by iteration order). Fallback: family `"unknown"` → factor 1.0 (byte-identical v1); WARN once per room per boot (not per tick).
3. **Kill switch for family scaling.** `CONF_FAN_RECHECK_FAMILY_SCALING_ENABLED` CM-entry switch, DEFAULT True.
4. **PAUSED rehydrate stale threshold fix (Rev 2 Finding 9b).** `presence_fan_recheck.py:1297-1300` currently reads `window = DEFAULT_FAN_RECHECK_WINDOW_S * 2` (constant 120 s). With Rev 2 bedroom × ZK factor the live window is ~690 s and a restart >120 s into a pause would wrongly cancel. Rev 2: compute `window = effective_window_s(room) * 2` where `effective_window_s = _timing_config()['CONF_FAN_RECHECK_WINDOW_S'] × room_type_factor × family_factor`. Routes through the same timing config the live path uses.
5. **COOLDOWN rehydrate uses DEFAULT, not live knob (Rev 2 Finding 9c — pre-existing Bug Class #53).** `presence_fan_recheck.py:1347-1349` reads `DEFAULT_FAN_RECHECK_COOLDOWN_S` directly; must route through `_timing_config()['CONF_FAN_RECHECK_COOLDOWN_S']`. This fix lives in C4 because C4 flips the default and would otherwise expose the discrepancy.

**Knob ladder.** Cooldown = rung 3 (existing Number); family factor map = rung 1 (module constant); family-scaling enable = rung 2 (config flow switch).

### Acceptance Criteria

- **Verify (code):** `_recheck_factor(merged) × _family_factor(dominant_family)` is the effective factor; `_family_factor` returns 1.0 when scaling disabled or family unknown.
- **Verify (code — Finding 9b):** `presence_fan_recheck.py:1297-1300` computes stale window from `_timing_config()`-derived effective window, not `DEFAULT_FAN_RECHECK_WINDOW_S * 2`. Mutation: reverting to constant `DEFAULT_FAN_RECHECK_WINDOW_S * 2` causes `test_rehydrate_paused_respects_effective_window` to fail at a 300-s-stale fixture with ZK bedroom (should rehydrate, not go idle).
- **Verify (code — Finding 9c):** `:1347-1349` reads live CM-entry cooldown via `_timing_config()`. Mutation anchor: `test_cooldown_rehydrate_reads_live_knob`.
- **Verify (code — Finding 9a):** `FAMILY_BY_MODEL_ID` lookup source is the HA device registry; miss → family `"unknown"` → factor 1.0 + one-time WARN.
- **Test:** `test_family_factor_zk_scales_window`, `test_family_factor_unknown_defaults_1_0`, `test_family_factor_is_max_over_recognised_families` (review A-M3: max over recognised families, not majority), `test_rehydrate_paused_respects_effective_window`, `test_cooldown_rehydrate_reads_live_knob`.
- **Live:** per-room `fan_recheck_outcome=occupied_confirmed-but-should-be-vacated` false-negative count drops in Jaya + Living Room; VACATED rate rises; cooldown-blocked miss count drops ≥50%. LD24xx (Jaya) measurement in week 1 either confirms `family_factor=3.0` is sufficient or triggers a C4 follow-up card.

**Non-goal.** No per-room override UI in v1.

---

## C5 — Retire the 5 s fan-start gate (preserve counter for evidence)  [Rev 2]

**Problem.** Gate only delays creation by ≤5 s; radars latch 55–240 s. After C3, 23 of its 27 fires were on fake flaps; remainder had no measurable effect.

**Solution — retire via kill switch.** `FAN_TRANSITION_SUSPECT_WINDOW_S = 0.0` (`const.py:875`). The kill-switch branch at `coordinator.py:3649` short-circuits the gate when window ≤ 0; `_fan_transition_suppressed_count` remains available for evidence; the memory-episode write path is dormant. No deletion.

**Interaction with C3 (Rev 2 Finding 12 cross-link).** C3's "gate fire count ≤2/week" AC from Rev 1 is tautologically satisfied once C5 ships (gate is off). Rev 2 drops that AC from C3 and replaces it with the belief-stability metric above. All other `FAN_TRANSITION_SUSPECT_WINDOW_S` / `_fan_transition_suppressed_count` readers (`binary_sensor.py:487` attribute, `memory_baseline.py:86`) tolerate a frozen counter — verified.

**C1b fold deferred.** Marginal benefit over C1a + C2 + C3 is small; the "deny mmwave-only occupancy" ingredient has the sleeping-still-person risk. Revisit if week-after measurement shows a residual.

### Acceptance Criteria

- **Verify (code):** `FAN_TRANSITION_SUSPECT_WINDOW_S == 0.0`; `coordinator.py:3649` short-circuits before reading `_fan_last_transition`.
- **Test:** `test_transition_gate_disabled_when_window_zero` (mutation anchor: setting window = 5.0 flips the test).
- **Live:** `_fan_transition_suppressed_count` stays constant post-ship (gate dormant); no new false-vacate incidents attributable to gate removal.

**Non-goal.** No code deletion.

---

## Measurement regime (acceptance)

Baseline = 2026-10-04→10-11 window + URA DB episodes since v5.84.1 (session scratchpad `fan_mmwave/`, promote to `scripts/fan_noise/` in this cycle, read-only, HA recorder + URA DB).

**One week after ship, re-run and record** (per-room):

- Empty + fan-on occupied minutes/week (target: Study A → <200).
- False-hold length p50/p90 by sensor family (LD24xx Jaya measurement is the Rev 2 explicit assumption-check for `family_factor=3.0`).
- Light minutes in empty rooms (comfort proxy).
- Mechanism fire/success/undo counts: recheck VACATED (no re-latch), D2 sustain demotion (fires in ≥5 of 7 previously-unreachable rooms), transition-gate (near-zero post-C5).
- **Guard metric A — BLE-present-vacate (Rev 2 Finding 5):** count of VACATED verdicts where a tracked `person.*` resolves to this room within ±3 min of the verdict timestamp. **Replay the same probe over the baseline week.** Post-ship count MUST NOT exceed baseline.
- **Guard metric B — belief stability (Rev 2 Finding 8):** `_fan_on_rooms` membership for the 6 flapping-fan rooms stable across any 60-s window containing ≥10 unavailable↔off edges.

Measurement scripts land in `scripts/fan_noise/` + the C2 audit script in the same directory. The post-ship report lands in `docs/articles/mmwave_fans_running_rejection_results.md` (new).

---

## Rejected or deferred solutions (and why)

| Option | Verdict | Reason |
|---|---|---|
| Use the radar's internal "motion" output as the fan-immune witness | **Rejected** | Study A's ZG-204ZK exposes no separate motion output; where radars do, the moving channel is exactly what a fan's Doppler triggers (Jaya). |
| Add the Study A InvisOutlet motion sensor as witness | **Rejected (operator)** | Unreliable; on do-not-use list. |
| "Re-aim before any tuning — tuning can't recover a fan in view" | **Rejected (operator correction)** | Wrong for the ZK: anti-interference + distance tuning do vacate Study A. |
| Buy a second sensor (ZV/PIR) per fan room | **Deferred** | Cost; try tuning + software first. |
| Widen the 5 s gate to minutes as-is | **Rejected** | Gate only delays creation; superseded by C1a + C2 + C3; C5 retires it. |
| Move Living Room's mmWave out of `motion_sensors` | **Rejected (retracted)** | ZG-204ZV is motion-class — correctly filed. |
| Rely on BLE alone as the witness | **Deferred** | BLE room location noisy; usable as one witness among several. |
| Fan-distance-band veto in URA | **Deferred** | High value only for distance-reporting radars. |
| Require corroboration for any mmWave-only hold while a fan runs (C1b general rule) | **Deferred** | Risks dropping still/sleeping people; revisit with measured residual. |
| Per-room learned energy baseline | **Deferred / parked** | Needs labelled data; mostly superseded by on-device tuning. |
| URA writes radar settings dynamically | **Deferred** | Carded as URA-SENSOR-TUNING-1 Phase B. |
| LD2450 + polygon exclusion zones | **Deferred (hardware)** | For rooms that still fail. |
| New flap→quarantine primitive in-cycle | **REVISED (Rev 2) — REUSE ActuatorReconciler flap counter** | See C3 Part B. Rev 1 wrongly deferred this to OC-STUCK-SENSOR-GENERALIZE-1; the reconciler already covers fan availability flap. |
| ZV 5-min post-fan-on gate in C2 | **Deferred (Rev 2)** | Carded as FAN-ZV-POWERON-TRANSIENT-GATE-1; triggers on week-1 measurement showing residual > 1/week in any fan room. |
| New `is_fan_immune_witness` CONF field | **Rejected** | Expressible via existing `CONF_SENSOR_CAPABILITIES`. |

---

## Operator decisions + prior-art findings (2026-10-11)

- **C1 → C1a (Rev 2 corrected).** Still call `_fan_restore` with a "leave off" mode reusing the AWAY-veto skip branch (`hvac_fans.py:2266-2287`); runs every discharge duty, writes no ON. Respects live manual-ON hold (eligibility veto + mid-pause fallback to real restore).
- **C2 → REUSE sensor_capability + live motion_sensors×model_id audit (Rev 2).** Audit covers main house and Wigton. ZV 5-min gate deferred and carded.
- **C3 → Part A last-known-good belief carryover + Part B REUSE ActuatorReconciler flap counter (Rev 2).** No new primitive. `UnavailableEntitiesSensor` already includes fans.
- **C4 → cooldown 900 + family factor + restart-rehydrate fixes (Rev 2 Finding 9).**

---

## Rev 2 CHANGELOG (2026-10-11)

Applied against Rev 1 of this plan after a one-pass adversarial plan review (findings 1–12). Reviewer read `develop` source for every claim; Rev 2 re-verified each cited file:line.

1. **C1a HVAC bookkeeping discharge (Finding 1 CRIT).** Rev 1 proposed "skip `_fan_restore` on VACATED". Rev 2 instead calls `_fan_restore` with a new `leave_off=True` mode that reuses the AWAY-veto skip branch at `hvac_fans.py:2266-2287`. Prevents a fake `manual_off_cooldown` from opening and the recheck self-vetoing on `_fan_in_manual_cooldown`.
2. **Respect live manual-ON hold (Finding 2 HIGH).** Added `_fan_in_manual_on_hold` eligibility veto + mid-pause fallback: a hold landing during the pause forces a real restore ON. Clears `manual_on_hold_paused_at` without extending the hold end.
3. **C3 Part B REUSE ActuatorReconciler flap counter (Finding 3 HIGH).** Rev 1 deferred availability-flap quarantine to OC-STUCK-SENSOR-GENERALIZE-1 claiming "chatter_detector doesn't fit"; missed that `actuator_reconciler.py:117,436-495,1084-1110,1124-1167,1182` already covers `CONF_FANS` with named-bucket sensitivity and auto-release. Rev 2 adds `_fan_in_actuator_quarantine` recheck veto; OC-STUCK-SENSOR-GENERALIZE-1 remains for sensor-side generalization.
4. **Falsifiable invariant restated (Finding 4 HIGH).** Rev 1's "cannot persist longer than N=p90 (~345 s)" was false by construction (arm ticks + spindown + window + cooldown >> 345 s) and left LD24xx as `TBD`. Rev 2 states a weekly empty+fan-on target with explicit per-family factors (ZK/ZX 2.0, LD24xx 3.0 as a measured-in-week-1 assumption, generic 1.5) plus a mechanism bound in `arm × tick + spindown + window×factor + cooldown` terms. Sleep veto scope corrected to bedrooms only (matches code).
5. **Recheck-specific guard metric (Finding 5 MED).** Added BLE-present-vacate discriminator (count of VACATED verdicts where a tracked `person.*` resolves to this room within ±3 min). Baseline-replay over 2026-10-04→10-11; rollback trigger if post-ship ≥ baseline + 1/week.
6. **C1a non-discriminating ACs replaced (Finding 6 MED).** Replaced "no `occupied_confirmed` within 15 min" and "fan off at `last_attempt_at + 15 s`" (both tautologically met before and after the fix) with: occupied re-latch check between 60–900 s post-VACATED while BLE places all persons out of the room; and the Finding 1 bookkeeping check (no `manual_off_cooldown` opens).
7. **C2 live motion_sensors × model_id audit + D-MED-2 safety net + ZV 5-min decision (Finding 7 MED).** Pre-ship audit script covers main-house AND Wigton registries; audit table is C2 acceptance fixture. Both D2 and fan_veto call sites gain a model-id safety net filtering radars-filed-as-motion. ZV 5-min gate explicitly deferred (carded as FAN-ZV-POWERON-TRANSIENT-GATE-1); `SENSOR_FLEET_CLASSES.md` §Rule 3 updated in the same commit per PRESENCE §0 ownership rule.
8. **C3 Part A reshaped to last-known-good (Finding 8 MED).** Rev 1 guard was limited to the stamper and dropped real wall-switch power-on. Rev 2 preserves power-on (unavailable→on when prior was off = real) and extends the guard to ALL five "fan on" readers (`_fan_on_rooms`, `_fan_on_since`, `_fan_off_at`, retro-phantom writer, D2 grace). Replaces C3's gate-count AC (vacuous once C5 ships) with belief-stability metric.
9. **C4 family resolver source + restart-rehydrate fixes (Finding 9 MED).** `FAMILY_BY_MODEL_ID` lives in `sensor_capability.py`; HA device registry is the lookup source; `"unknown"` fallback. Fixed `presence_fan_recheck.py:1297-1300` (PAUSED stale threshold now uses effective window, not `DEFAULT_FAN_RECHECK_WINDOW_S * 2`) and `:1347-1349` (COOLDOWN rehydrate now reads live knob via `_timing_config()`, not `DEFAULT_FAN_RECHECK_COOLDOWN_S`; pre-existing Bug Class #53).
10. **C3 UnavailableEntitiesSensor step dropped (Finding 10 LOW).** `fans` is already in `_ACTUATOR_LIST_KEYS` (`sensor.py:1782-1783`); the C3 "Sensor:" AC holds today via reconciler quarantine surfacing — no edit needed.
11. **C2 regex enumeration corrected (Finding 11 LOW).** `MMWAVE_NAME_PATTERN` module constant retained (not deleted) with `# retired` comment so `quality/tests/test_mmwave_fan_demotion.py` still compiles. `presence.py:413 _classify_entity_kind` substring fallback listed in §A as checked (out of scope — only fires for entities absent from every CONF list).
12. **C5 / C3 contradiction resolved (Finding 12 LOW).** C3's "gate fire count ≤2/week" AC removed; belief-stability metric replaces it. All `FAN_TRANSITION_SUSPECT_WINDOW_S` / `_fan_transition_suppressed_count` readers tolerate a frozen counter — verified.
13. **Gold-patterns index updated.** Added ActuatorReconciler flap counter row. Added "HVAC leave-off discharge" row. Clarified fan-listener row to say "last-known-good carryover, not zeroing". Marked `derive_capability` as NOT reading `model_id`.

---

## Pre-ship audit results (2026-10-11, builder) — C2 acceptance fixture

Script `scripts/fan_noise/audit_motion_sensors_models.py`, table `docs/planning/AUDIT_motion_sensors_live_models.md`
(main house 43 rooms / 63 sensor entries; Wigton 3 rooms / 3 entries).

| Finding | Effect on the build |
|---|---|
| ESPHome / Meross devices have `model_id = None` | Family lookup keys on `model_id`, falling back to `model` (deviation from §C4 text). |
| Jaya / Kitchen / Study B / Ziri radars are custom ESP32 builds (`esp32-c3-devkitm-1`) | Family `unknown` → factor 1.0. **The LD24xx factor 3.0 does not reach Jaya** until the device reports an LD24xx model. Operator item. |
| 3 Meross MS600 radars in `motion_sensors` (Guest Bedroom 1, Guest Bedroom 2, Media) | Excluded by the model safety net (`ms600 9.0.0` → `generic_radar`). The prescribed remedy "declare `kind: mmwave`" is **rejected by `validate_capabilities_payload`** (D-MEDIUM-1) — the operator fix is to move them to `presence_sensors`. |
| `binary_sensor.ziri_3_moving_target` (LD2410 moving output, ESP32) in Ziri `motion_sensors` | Not caught by regex before nor by the model map now — unchanged. Operator decision. |
| IVO1 `…_masterbath_motion` | Was regex-excluded; now a witness. UNVERIFIED whether it is the outlet's PIR or mmWave output. Operator check. |
| 22 ZG-204ZV in `motion_sensors` | Now fan-immune witnesses (intended). |
| Wigton: 3 ecobee occupancy entities, no radars, no fans | C2/C4 inert there. |

Gate: no radar-filed-as-motion changes behaviour versus today (MS600 held by the safety net; Ziri unchanged).

## Builder notes (2026-10-11, branch `fix/fan-noise-running-rejection`)

- **Family table vs C4 text.** The invariant table lists "Generic / unknown 1.5" while C4 and its AC say unknown → 1.0.
  Built as: `generic_radar` (recognised radar, unmeasured family: Screek, Seeed, Meross, Inovelli) = 1.5; `unknown`
  (registry miss / unrecognised model) = 1.0. Both statements hold.
- **"Treat as forced restore" (C1a step 4)** is implemented in the FanController: a live hold flips leave-off to a real
  restore ON. On the presence side the outcome stays VACATED (the room is still released and the outcome row says
  `forced: false`); the new `manual_on_hold_live` eligibility veto then keeps the recheck from re-arming against the hold.
- **C3 Part A sibling read:** the multi-fan "any other fan on" check also uses the last known-good belief for a sibling
  that is currently unavailable (otherwise one flapping sibling could still drop the room's belief).
- **Known-good seed:** `_discover_room_fans` seeds the per-entity known-good from the live state at discovery.
- **C5:** gate-logic tests keep running at a test-local 5 s window; a new test pins the production window at 0.0.
- `CONF_PRESENCE_SENSORS` in this plan = `CONF_MMWAVE_SENSORS` (value `"presence_sensors"`); no separate constant exists.

## Review fix-up 1 (2026-10-11) — reviews A / B / C

| Finding | Fix |
|---|---|
| B-1 pause can outlast the HVAC suppress (180 s × bedroom 2 × ZK 2 + spindown > 600 s) | suppress_until = now + max(hvac_suppress, spindown + effective window + `FAN_RECHECK_SUPPRESS_MARGIN_S` 60). The same ISO feeds the HVAC tier and the room-tier `note_recheck_pause` backstop |
| A-M2 / B-2 held ON belief never discharges for a fan that stays unavailable | Chosen: **TTL** `FAN_BELIEF_UNAVAILABLE_TTL_S` = 120 s (rung 1). Why TTL over "decay unless quarantined": quarantine needs N flaps inside its window, so a fan that dies once never enters it and would hold forever; measured flaps are 20–40 s, inside 120 s. On expiry a synthetic on→off edge replays through `_handle_fan_change`, so `_fan_on_rooms`, `_fan_on_since` (read by the D2 `fan_off` latch-clear) and `_fan_off_at` move as on a real off edge. A readable edge cancels the timer; re-discovery and teardown cancel all |
| A-M1 exact `ms600 9.0.0` key | First-token, case-insensitive model match (`FAMILY_BY_MODEL_TOKEN`); a sensor whose family is `unknown` falls back to the `MMWAVE_NAME_PATTERN` exclusion (develop behaviour). Side effect: the IVO1 `…masterbath_motion` entity is excluded again, as on develop |
| A-M3 majority incl. `unknown` | Factor = MAX over the room's recognised families; `unknown` ignored (Jaya [esp32, ZK] → 2.0; Master Bedroom [generic, generic, ZX] → 2.0). Supersedes "dominant family" in §C4 |
| A-L1 stale-PAUSED threshold | max(2 × effective window, spindown + effective window + 60) |
| A-L2 stale known-good after re-discovery | discovery drops the entry for a fan that is unavailable now |
| C oracle branch of `_fan_in_manual_on_hold` untested | `test_manual_on_hold_oracle_branch` |
| B-4 quarantine veto on any configured fan | veto only when the quarantined fan is the one RUNNING |

**B-3 (documented, not changed): hold-pause time loss.** When a manual-ON hold was already live at pause time (rare
after the eligibility veto), a VACATED restore turns the fan back on and clears `manual_on_hold_paused_at` WITHOUT
extending the hold, so the person loses the paused minutes (≤ spindown + effective window + margin) from their hold.
Accepted per C1a step 4 ("do not touch the hold timers"). Revisit if an operator reports a hold ending early.
