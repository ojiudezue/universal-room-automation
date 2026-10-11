# PLANNING — Running-fan mmWave noise rejection (fix-up of the existing mechanisms)

**Status:** problem/solution framing approved for planning 2026-10-11 (operator). **Operator decisions 2026-10-11: C1 = C1a (leave the fan off after a VACATED verdict). C2 = REUSE the existing capability layer. C3 = reuse the quarantine primitive (guard only in-cycle; flap-rule in OC-STUCK-SENSOR-GENERALIZE-1).** Tier 2 (cross-mechanism: presence ↔ fans ↔ lights). Requires: institutional-context section + prior-art scan + one adversarial plan review before build (CLAUDE.md). READ FIRST: `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`, `docs/architecture/SENSOR_FLEET_CLASSES.md` (both read completely by this planner 2026-10-11).

**Evidence base (measured 2026-10-11, 7-day recorder window + URA DB since v5.84.1):** Study A held occupied ~26 h/week while empty with the fan on (1,541 min); fan-recheck released Study A correctly 28× but 27 were undone by its own fan restore (mmWave re-latch 11–696 s later, median ~60 s); D2 sustain demotion fired 0× in every room and is unreachable in 7/10 fan rooms; the 5 s transition gate fired 27× in 7 days, 23 on dead/flapping fan entities, and 26/27 were followed by occupancy 2–12 s later. Radars latch 55–240 s after a fan starts (p50) and clear 28–825 s after it stops, by sensor family.

**Falsifiable invariant.** For a room whose ground truth (BLE location ±3 min) is empty and whose fan is believed ON, occupancy held only by fan-susceptible presence sensors cannot persist longer than N minutes — where N is the measured p90 clear-time for the room's sensor family (default per family: Zigbee ZK/ZX ≈ 345 s, ESPHome LD24xx ≈ TBD, generic 600 s). SIMULTANEOUSLY: a person who is present and still is never vacated by these changes during `FAN_TRUST_STATES = {HOME_NIGHT, SLEEP, WAKING}`; and the aggregate "occupied→vacant while BLE says a person is present" transition count per week must not increase versus the 2026-10-04→10-11 baseline.

**Config companion (no code, done alongside):** point Guest Bedroom 1 / Media / Game Room fan config at their live `_2` entities; Master Bedroom RF fan + Exercise `fan.fan_switch_3` need physical fixes (operator). Study A ZG-204ZK tuned 2026-10-11 (motion 5, static 6, distance 2.5 m, anti-interference ON) — before/after measured separately so its effect isn't credited to the code.

---

## Institutional context verified (prior-art audit, 2026-10-11)

Operator directive 2026-10-11: *"make sure you do a prior art context-wide audit. Don't want to rebuild what we have already — instead reuse gold patterns."* This section is the proof-of-work.

### A. Code surfaces greppped

| Area | File:line | Finding |
|---|---|---|
| Capability layer | `domain_coordinators/sensor_capability.py:172` `derive_capability()` | Pure-module resolver, operator overrides via `CONF_SENSOR_CAPABILITIES` (`const.py:559`). Vocabulary: `TIER1_CAPABILITIES` incl. `motion`/`mmwave`/`occupancy`/`pir`/`pir_split`/`bed`/`camera_presence`/`ble_presence` (`const.py:503-520`). **Byte-identical defaults** when nothing is declared. |
| Role resolver | `domain_coordinators/sensor_role.py:17-18` | Only wired consumer today: `coordinator._detect_duty_cycle_stuck`. Pure, HA-free. `CANDIDATE_FOR_STUCK` / `CORROBORATOR_FOR_ROOM` live. |
| Operator override in-flight | `config_flow.py:12334,12360,12487` | Game Room already declares `binary_sensor.0xa4c1382e60e05225_presence` as `{"kind": "pir"}`; Guest Bedroom 2 Matter as `mmwave`. The override surface works today; the defect is that fan mechanisms do not consult it. |
| D2 (sustain) | `coordinator.py:2159 _d2_motion_sensors_present` | Imports `fan_veto.MMWAVE_NAME_PATTERN` and filters by **entity name** (regex `(mmwave\|radar\|presence\|ld2410\|ld2412)`). Fail-closes when filtered list is empty → unreachable in ZV-only rooms. |
| Fan-away veto (actuation) | `fan_veto.py:61 MMWAVE_NAME_PATTERN`, `fan_veto.py:146-148 _has_recent_motion` | Same regex, same name-based filter. Three mechanisms disagree about ZV. |
| Fan-transition CREATION gate | `coordinator.py:3601-3745` + `const.py:875 FAN_TRANSITION_SUSPECT_WINDOW_S = 5.0` | Kill switch = 0.0. Reads `presence.get_fan_last_transition(room)`. Stamps memory-episode `fan_transition_suppressed` → adjudication `phantom`. |
| Fan listener (stamps transitions) | `presence.py:3719-3786 _handle_fan_change` | **Stamps on ANY state_changed OR percentage attr change**, including transitions to/from `unavailable`/`unknown` (lines 3752-3762 compute `state_changed` without filtering unavailables). `is_on = False` when unavailable (3738-3739). This is the C3 bug surface. |
| Recheck state machine | `domain_coordinators/presence_fan_recheck.py:1-1379` | STATES `idle/armed/paused/restoring/cooldown`; OUTCOMES `vacated`/`occupied_confirmed`; LAYERS `L1/L2/L3`; HVAC handshake via `_fan_pause` → `FanController.pause_for_recheck` + suppress-until ISO (3703-3719); `_fan_restore` at `:793`. `apply_fan_recheck_release` on room-coord at `:800`. Timing knobs on CM entry (`:1004 _timing_config`). HIGH-STILL-RISK bedrooms gated at `:94`. |
| Recheck call site (D5 precedence) | `presence_fan_recheck.py:493-495` (`CONF_FAN_RECHECK_SPINDOWN_S` etc.) | Already consumes 7 CM-entry timing knobs; room-type `_recheck_factor` already scales window per room type (`ROOM_TYPE_RECHECK_FACTOR`). The per-sensor-family scaling for C4 extends this exact pattern. |
| Exclusion primitive | `domain_coordinators/sensor_exclusion.py:1-176 SensorExclusionSet` | Multi-writer, per-client-provenance, per-tick `reset_tick()` + `promote(client,entity,reason)` + `is_excluded()`. STEP-EXCLUDE-1..4 invariants. Clients today: P22 continuous-on, STUCK-SENSOR-1 dutycycle, `chatter_detector`. New clients wire by `promote(client="…", entity=…, reason=…)`. |
| Chatter detector | `domain_coordinators/chatter_detector.py:1-80` | Sub-T_floor burst detector, auto-release after `CHATTER_RELEASE_QUIET_S`. Rule is **sub-1-s burst** — does NOT fit a ~40 s availability flap. Correct home for the flap rule = OC-STUCK-SENSOR-GENERALIZE-1 (already carded, planning doc exists). |
| Recheck apply-release | `coordinator.py` — `apply_fan_recheck_release` | Hook that drops occupancy on VACATED outcome. Current C1 proposal (C1a) stops here and does NOT restore the fan. |
| HVAC fan controller | `hvac_fans.FanController._set_fan_state` + `pause_for_recheck` / `restore_after_recheck` | All fan writes delegate here per the recheck plan's ownership rule. |
| Comfort-fan veto predicate | `fan_veto.is_veto_relevant`, `fan_veto.veto` | Called by 3 actuation sites (`automation.py`, `hvac_fans.py`, `actuator_reconciler.py`). The `_has_recent_motion` is where C2 lands. |

**Context-wide grep for 'witness'/'corroborat'/'veto'/'hold'/'grace'/'refractory'/'cooldown' confirms:** every pattern URA needs for C1b (if later chosen), C4 (watch-window per family), and C5 (post-fan-on corroboration window) ALREADY EXISTS as a reusable gold pattern (`_fan_on_since` seed stamp at `presence.py:3686-3689,3793-3794`; adjacency / zone-tier queries via `_zone_rooms_for` at `presence_fan_recheck.py:1092`; cooldown idiom in `_enter_cooldown`). No new primitive invented.

### B. Plans / audits / catalogs consulted

| Doc | Relevance |
|---|---|
| `PLANNING_fan_noise_mode2_ble_pause_recheck.md` | Original recheck plan — the state machine, D1 trigger conditions, D1.5 BLE drop-authorization, HVAC handshake, restart matrix. C1a (don't-restore-on-VACATED) is an in-place behavior change to the `_restore` branch; no new state. |
| `PLANNING_fan_noise_mitigation_layers1_2.md` + `_layer2_actuation.md` | Established the three-mechanism complementarity (creation gate + sustain demotion + actuation veto) now summarized in PRESENCE_ARCHITECTURE_STATE_OF_PLAY §6. |
| `PLANNING_fan_trust_state_extension.md` | `FAN_TRUST_STATES = {HOME_NIGHT, SLEEP, WAKING}` — the keep-on contract C1a MUST NOT fight. Study A / Living Room are non-bedroom; fan-recheck's `_evaluate_eligibility:487-491` already scopes the sleep veto to bedrooms. |
| `PLANNING_fan_recheck_d2_deadlock_fix.md` | `is_recheck_eligible` inert-sink probe pattern — reused for cross-mechanism gating. |
| `PLANNING_sensor_capability_vs_role.md` | **The gold pattern for C2.** Established capability≠role, byte-identical defaults, override via `CONF_SENSOR_CAPABILITIES`. C2 adds consumers (D2 / fan_veto / recheck eligibility / transition gate) via `derive_capability()` — zero new primitive. |
| `PLANNING_stuck_sensor_consequence.md` + `PLANNING_oc_stuck_sensor_generalize.md` | Where the ~40 s availability-flap rule BELONGS. This cycle only ships the one-line guard in the stamper; the flap→exclusion promotion is OC-STUCK-SENSOR-GENERALIZE-1. |
| `PLANNING_sensor_health_surfacing.md` | `SensorExclusionSet` contract (STEP-EXCLUDE-1..4) + `UnavailableEntitiesSensor` surface. The per-room "fan entity unreliable" diagnostic lands on the same sensor surface, not a new entity. |
| `AUDIT_mmwave_only_rooms_2026-07-31.md` Findings 1/2/6 | Finding 6 = root-cause of name-based classification; still unresolved in `_d2_motion_sensors_present` + `fan_veto.MMWAVE_NAME_PATTERN`. |
| `docs/articles/mmwave_fans_transition_gate.md` + `mmwave_fan_alignment_probe_results.md` | **Do NOT re-cite as justification to disable the gate** — PRESENCE §10.1 corrects this: true only for Zigbee ZK/ZX in that probe window; false for ESPHome LD2410 (Jaya). |

### C. Memory bodies pulled

- `feedback_context_wide_scoping.md` — scope rooms + zones + house.
- `feedback_config_first_before_code.md` — Study A ZK tuning + `_2`-entity config fixes done 2026-10-11 before this cycle.
- `feedback_marginal_benefit_pushback.md` — C5 marginal benefit is small; folding into C1b (deferred) is cheaper than a bespoke gate.
- `feedback_suppression_needs_discharge.md` — C1a MUST specify what re-arms the fan after a VACATED outcome (normal fan logic on next occupancy edge). Backstop addressed below.
- `feedback_tier2plus_prior_art_scan.md` — this section is the forcing function.
- `reference_hvac_fans_two_sites` — fan writes delegate to `FanController._set_fan_state`.

### D. REUSE-or-BUILD verdict per deliverable piece

| Piece | Verdict | Gold pattern reused | File:line |
|---|---|---|---|
| C1a "do not restore fan on VACATED" | **REUSE** state machine branch | `presence_fan_recheck._restore` outcome branch | `presence_fan_recheck.py:785-849` |
| C1a cross-mechanism re-arm after VACATED | **REUSE** normal fan logic re-entry via next room-tick occupancy edge | `on_room_tick` eligibility re-eval + `hvac_fans.FanController` normal update | `presence_fan_recheck.py:284`, `hvac_fans.py` |
| C2 capability lookup | **REUSE** `derive_capability()` + `TIER1_CAPABILITIES` | `sensor_capability.py:172`, `const.py:503-520` | — |
| C2 operator override | **REUSE** `CONF_SENSOR_CAPABILITIES` already live in options flow | `const.py:559`, `config_flow.py:12334,12487` | — |
| C2 helper "is fan-immune witness?" | **BUILD (small)** — one 15-line pure helper on top of `derive_capability()` | mirrors `sensor_role._CORROBORATOR_KINDS` pattern | `sensor_role.py:59-70` |
| C2 D2 witness check | **REWRITE** `_d2_motion_sensors_present` to consult helper, drop regex | — | `coordinator.py:2159` |
| C2 fan_veto witness check | **REWRITE** `_has_recent_motion` filter to consult helper, drop regex | — | `fan_veto.py:146-148` |
| C2 recheck eligibility | **EXTEND** `_evaluate_eligibility` to require fan-immune witness ok | — | `presence_fan_recheck.py:436-611` |
| C2 transition gate | no code change (gate is CREATION-only on mmwave-sole; name regex not used here) | — | `coordinator.py:3601-3745` |
| C3 stamper guard | **ONE-LINE REUSE** — treat unavailable/unknown as "no transition"; symmetric with existing `is_on = False` at `presence.py:3738-3739` | — | `presence.py:3752-3767` |
| C3 "fan state unknown" semantics in consumers | **REUSE** existing fail-open defaults in `fan_veto._get_house_state` idiom | `fan_veto.py:80-108` | — |
| C3 "fan entity unreliable" diagnostic | **REUSE** `UnavailableEntitiesSensor` surface; no new entity | `sensor.py` (file-level) + `SensorExclusionSet.provenance` | `sensor_exclusion.py:134` |
| C3 flap→quarantine rule | **DEFER** to OC-STUCK-SENSOR-GENERALIZE-1 (cross-kind flap, correct home) | plan already exists | `PLANNING_oc_stuck_sensor_generalize.md` |
| C4 per-family watch window | **EXTEND** `_recheck_factor` to accept a family factor alongside `ROOM_TYPE_RECHECK_FACTOR`; **BUILD** one knob `CONF_FAN_RECHECK_CLEAR_P90_S` (CM-entry, rung-3 Number) | mirrors `_timing_config` 7-knob CM-entry pattern | `presence_fan_recheck.py:1004,1103` |
| C4 cooldown 1800 → ~900 | **CONFIG CHANGE** — flip `DEFAULT_FAN_RECHECK_COOLDOWN_S` default; existing CM-entry Number stays | — | `const.py:707-708` |
| C5 retire 5 s gate (or fold into C1b) | **CONFIG CHANGE** — set `FAN_TRANSITION_SUSPECT_WINDOW_S = 0.0` to retire; preserve `_fan_transition_suppressed_count` for evidence; C1b fold **DEFERRED** | — | `const.py:875` |
| Measurement regime | **BUILD (small)** — move session-scratchpad probe scripts into `scripts/fan_noise/`; one-shot read-only | measure-before-build rule | — |

### E. Gold patterns index (appendix — intended to be copied into PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md after this ships)

| Pattern | Where | When to reuse |
|---|---|---|
| **Capability layer + CONF overrides** | `sensor_capability.py:172 derive_capability()` + `CONF_SENSOR_CAPABILITIES` (`const.py:559`) | ANY classification question about a sensor ("is this a PIR?", "fan-immune?", "corroborator?"). NEVER regex entity names. |
| **Role query matrix (pure, HA-free)** | `sensor_role.py:17-18 role_for(entity, room_config, query)` | When the SAME sensor answers different questions under different queries (D2 stuck candidate vs corroborator). |
| **SensorExclusionSet multi-writer quarantine** | `sensor_exclusion.py` | Any new "untrust this sensor's vote this tick" rule; promote with a NEW client name; release per-client. |
| **Recheck state machine (idle→armed→paused→restoring→cooldown)** | `presence_fan_recheck.py` | Any "stop → re-measure → decide" flow with a HVAC-handshake and restart matrix. |
| **Inert-sink eligibility probe** | `presence_fan_recheck._INERT_SINK` + `is_recheck_eligible` | Cross-mechanism "would this gate fire?" checks that must not perturb observability counters. |
| **CM-entry timing knobs via sweep** | `presence_fan_recheck._timing_config` | A family of knobs operator-tunable live, loaded from CM-entry options with DEFAULT_* fallback. |
| **Fan listener (stamp transitions)** | `presence.py:3719 _handle_fan_change` + `_fan_last_transition` + `get_fan_last_transition` | Any "did a fan just do something?" window query. Guard unavailable/unknown at the stamp site (C3). |
| **Kill-switch constant + knob ladder** | `FAN_TRANSITION_SUSPECT_WINDOW_S` module constant; `CONF_FAN_RECHECK_*` CM-entry Numbers; `CONF_ROOM_FAN_RECHECK_ENABLED` per-room switch | Rung 1 for review-only (safety / fitted); rung 2 for per-deployment structure; rung 3 for live operator tuning. |
| **Memory-episode adjudication write** | `coordinator.py:3701-3729` log_memory_episode `fan_transition_suppressed` → adjudication `phantom` | Durable per-event observability for a gated suppression. |
| **FAN_TRUST_STATES scope** | `hvac_const.FAN_TRUST_STATES`, consulted at `presence_fan_recheck.py:487-491` and `_still_armed_eligible:969-973` | Bedroom-only sleep veto; non-bedrooms proceed through sleep. C1a inherits this scope automatically. |

---

## C1 — Fan recheck undoes its own correct "empty" verdict  [C1a chosen]

**Problem (unchanged from framing).** Recheck VACATED verdict is immediately re-latched by the `_fan_restore` call at `presence_fan_recheck.py:793`. 27 of 28 Study A releases bounced in 11–696 s.

**Solution — C1a: on VACATED, do NOT restore the fan.** The fan was running for a person who has left; normal fan logic re-arms it when real occupancy returns via the standard `on_room_tick` path and `hvac_fans.FanController.update`.

**Smallest change.** In `presence_fan_recheck._restore` (`:785-849`), when `outcome == OUTCOME_VACATED and not forced`, SKIP the `_fan_restore(ctx.room_name, ctx.snapshot)` call. All other branches (OCCUPIED_CONFIRMED, forced via `force_restore`, cancel-driven) still restore. `apply_fan_recheck_release` still fires; cooldown still arms. `ctx.snapshot` is still cleared.

**Discharge for the suppression** (per `feedback_suppression_needs_discharge`): re-arming the fan is not deferred — it is immediate on the next real occupancy edge via the HVAC fan controller's normal update cycle. Backstop: operator-visible `switch.<room>_automation` and manual fan on/off (manual-on bypass path at `hvac_fans`); restart = fresh ctx (recheck cooldown decayed, HVAC decides).

### Acceptance Criteria
- **Verify (code):** `_restore` with `outcome == VACATED and not forced` does not call `_fan_restore`; all other outcomes do. Unit test asserts call-count = 0 under VACATED and 1 under OCCUPIED_CONFIRMED (mutation-anchored: deleting the branch guard fails this test).
- **Verify (DB):** post-ship, in `ura_activity_log`, VACATED outcome rows are NOT followed by a `fan_recheck_outcome=occupied_confirmed` row re-latching the room within 15 min (study A false-restore loop closed).
- **Sensor:** `fan_recheck_last_outcome` attribute reads `vacated` and the room's fan `state` remains `off` (not `on`) at `last_attempt_at + 15 s`.
- **Test:** `test_fan_recheck_restore_skipped_on_vacated` (unit) + behavioral `test_vacated_does_not_re_latch_occupied` (integration — simulated mmwave stays low, HVAC fan controller not called).
- **Live:** 1 week post-ship — Study A empty-room-fan-on hold minutes drop from 1,541 min/week baseline toward <200 min/week; BLE-present → vacated transition count DOES NOT rise versus baseline.

**Non-goal.** C1b (restore-with-corroboration-window) is DEFERRED; revisit if C1a's comfort residual (fan short-cycling on frequent exits) proves meaningful.

---

## C2 — Classify sensors by capability, not entity name  [REUSE sensor_capability]

**Problem (unchanged).** `MMWAVE_NAME_PATTERN` regex at `fan_veto.py:61` is shared by `_d2_motion_sensors_present` (`coordinator.py:2159`) and `_has_recent_motion` (`fan_veto.py:146-148`). ZV sensors named `…_presence` fail the regex and vanish from D2; same regex includes ZVs out of fan_veto; three mechanisms disagree.

**Solution.** Add one small pure helper on top of `derive_capability()`:

```python
# domain_coordinators/sensor_capability.py — appended, pure, HA-free
_FAN_IMMUNE_WITNESS_KINDS: frozenset = frozenset({
    CAPABILITY_KIND_MOTION,       # ZV + real PIR; see SENSOR_FLEET_CLASSES §Rule 3 — motion-class in steady state
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
- **D2** `_d2_motion_sensors_present` (`coordinator.py:2159`): replace `[s for s in motion if not MMWAVE_NAME_PATTERN.search(s)]` with `[s for s in motion if is_fan_immune_witness(self._get_config_dict(), s)]`.
- **fan_veto** `_has_recent_motion` (`fan_veto.py:146-148`): same substitution; keeps mmwave/mmwave-named excluded, now admits ZV (which the SENSOR_FLEET_CLASSES rule says is motion-class and fan-immune in steady state).
- **recheck eligibility**: in `_evaluate_eligibility` (`presence_fan_recheck.py:436`) — no change needed in v1 (eligibility already requires `occupancy_source == "mmwave"` for N consecutive ticks via `recent_occupancy_sources`; capability routing is upstream of that classifier). Documented as acceptance-only — the capability helper is a NEW importable, not a new call site.
- **transition gate**: no change — gate uses mmwave-sole classifier from upstream, not name regex.

**ZV steady-vs-transient subtlety (per SENSOR_FLEET_CLASSES Rule 3 + 2026-10-11 measurement).** ZV is fan-immune in steady state but may latch within ~5 min of fan→on. v1 ignores this (treat ZV as fan-immune uniformly); if the measurement regime shows a residual, add a steady-state gate via `_fan_on_since` (gold pattern at `presence.py:3686-3689,3793-3794`) in a follow-up card — do not inline it in C2.

**Operator overrides.** No new override needed: Game Room's `kind: pir` and Guest Bedroom 2 Matter `kind: mmwave` are already declared via `CONF_SENSOR_CAPABILITIES` and resolved by `derive_capability()`. Any residual misclassification is one options-flow edit, not a code change.

### Acceptance Criteria
- **Verify (code):** `MMWAVE_NAME_PATTERN` has exactly 2 consumers before this change; after this change, 0 consumers in `coordinator.py` and `fan_veto.py` (regex kept only for config_flow validation IF used there — grep confirmed). `is_fan_immune_witness` is the only resolver for "fan-immune witness".
- **Verify (behavior):** in Game Room (ZV with declared `kind: pir`), `_d2_motion_sensors_present()` returns True (today it returns False).
- **Test:** unit — `test_fan_immune_witness_zv_default_motion` (byte-identical default: ZV declared only in `CONF_MOTION_SENSORS` resolves to `motion` → fan-immune True); `test_fan_immune_witness_mmwave_declared` (ZK in `CONF_PRESENCE_SENSORS` resolves to `mmwave` → fan-immune False). Mutation-anchor: deleting any kind from `_FAN_IMMUNE_WITNESS_KINDS` must fail at least one test.
- **Live:** D2 fire count rises from 0 in ≥5 of the 7 previously-unreachable fan rooms within 1 week; false-vacate count during BLE-present-still person DOES NOT rise.

**Non-goal.** No new CONF field. No change to `TIER1_CAPABILITIES`. No role resolver expansion.

---

## C3 — Dead fan entities fake fan activity  [guard-only in-cycle; flap-rule in OC-STUCK-SENSOR-GENERALIZE-1]

**Problem.** 23/27 recent fan-transition gate fires came from entities flapping `unavailable ↔ off/on` every ~20 s (6 fan entities ~2,050 flips/day, ~50% unavailable). `presence.py:3752-3767` stamps `_fan_last_transition` on ANY `state_changed OR percentage_changed`, including unavailable↔state edges.

**Solution (two parts, in-cycle = part A only).**

**Part A — stamp guard (this cycle).** In `_handle_fan_change` at `presence.py:3752`, treat `old_state.state in _UNAVAILABLE_STATES or new_state.state in _UNAVAILABLE_STATES` as "no transition stamped". Symmetric with the existing `is_on = False` guard at line 3738. One-liner, strictly subtractive — no new state. When `new_state` is unavailable, the fan is "unknown"; mechanisms needing "fan on" already fail-closed through `_is_entity_on` returning False (`presence_fan_recheck.py:1045-1050`).

**Part B — flap→quarantine rule (deferred, OC-STUCK-SENSOR-GENERALIZE-1).** The ~40 s availability-flap does NOT fit `chatter_detector`'s sub-1-s T_floor rule. The correct home per `PLANNING_oc_stuck_sensor_generalize.md` §invariant is OC's generalized stuck-sensor detector keyed to the raw device sensor across all device kinds — fan entities are one more kind in that fleet. In-cycle we only ship Part A; the per-room "fan entity unreliable" diagnostic is sourced from the existing `UnavailableEntitiesSensor` surface (already tracks input sensors). We ADD fan entities to that surface's input list — one list extension, no new sensor entity.

### Acceptance Criteria
- **Verify (code):** in `_handle_fan_change`, `transition_now = None` when either old or new state is in `_UNAVAILABLE_STATES`. Mutation anchor: removing the guard causes `test_fan_transition_not_stamped_on_unavailable_edge` to fail.
- **Verify (DB):** post-ship, `_fan_transition_suppressed_count` memory-episode writes (`coordinator.py:3701-3729`) with `fan_transition_suppressed` adjudication drop from the 23/27 flap-driven rate toward ~0 for the 6 flapping-fan rooms.
- **Sensor:** `sensor.<room>_unavailable_entities` lists the flapping fan entity (Media/Game/Guest-down ceiling fans, both patio, Master-BR RF) once the surface's input list includes `CONF_FANS`.
- **Test:** `test_fan_stamp_guards_unavailable_edges` (unit); `test_transition_gate_does_not_fire_on_flap` (integration, drives 100 unavailable↔off flaps in 60 s, asserts `_fan_transition_suppressed_count` unchanged).
- **Live:** within 1 week, Study A / Master-BR / Guest-down transition-gate fire count ≤ 2/week (down from 27/week), and the inferred-fake "fan on" state (via `_is_entity_on` returning True on a flap landing) stops gating recheck ineligibility for `no_fan_on`.

**Non-goal.** No flap-to-exclusion promotion in this cycle. No new entity. OC-STUCK-SENSOR-GENERALIZE-1 is where the flap→quarantine rule lands.

---

## C4 — Recheck timing is one-size-fits-all

**Problem.** Default spindown 30 s + window 60 s + cooldown 1800 s. Measured clear-time p90 varies 51 → 825 s by family; false-negatives then eat a 30-min cooldown (19 misses in Study A/week).

**Solution.**
1. **Cooldown default** `DEFAULT_FAN_RECHECK_COOLDOWN_S` 1800 → 900 (one-line, `const.py:708`). Operator can still raise it via the existing CM-entry Number. Rung 3 (live-tunable).
2. **Per-family watch factor.** Extend `_recheck_factor` (`presence_fan_recheck.py:1103`) to multiply by a `SENSOR_FAMILY_RECHECK_FACTOR` lookup keyed to the room's dominant presence-sensor family (ZK, ZX, LD24xx, generic), resolved via `derive_capability()` + a static family map (model_id → family) owned by `SENSOR_FLEET_CLASSES.md` / `sensor_capability.py`. The map is a module constant (rung 1) — review-only; empirical, not operator-tunable.
3. **Kill switch for the family scaling.** `CONF_FAN_RECHECK_FAMILY_SCALING_ENABLED` CM-entry switch, DEFAULT True; off = v1 behavior.

**Knob ladder (per `feedback_numbers_get_knobs`).** cooldown = rung 3 (existing Number); family factor map = rung 1 (module constant); family-scaling enable = rung 2 (config flow switch).

### Acceptance Criteria
- **Verify (code):** `_recheck_factor(merged)` × `_family_factor(dominant_family)` = effective factor. `_family_factor` returns 1.0 when scaling disabled.
- **Test:** `test_family_factor_zk_scales_window` (Study A family = ZK → factor >= p90/60); `test_family_factor_unknown_defaults_1_0`.
- **Live:** per-room `fan_recheck_outcome` with `outcome=occupied_confirmed-but-should-be-vacated` false-negative count drops in Jaya + Living Room; VACATED rate rises; cooldown-blocked miss count drops ≥50%.

**Non-goal.** No per-room override UI in v1; operator can override via `CONF_FAN_RECHECK_WINDOW_S` on CM-entry if the family factor is wrong.

---

## C5 — Retire the 5 s fan-start gate (preserve counter for evidence)

**Problem.** Gate only delays creation by ≤5 s; radars latch 55–240 s. After C3, 23 of its 27 fires were on fake flaps; the remainder had no measurable effect.

**Solution — retire via kill switch.** Set `FAN_TRANSITION_SUSPECT_WINDOW_S = 0.0` (`const.py:875`). The existing kill-switch branch at `coordinator.py:3649` short-circuits the gate when window ≤ 0; `_fan_transition_suppressed_count` remains available for evidence; the memory-episode write path is dormant. No deletion of code — reversible by flipping the constant.

**C1b fold deferred.** Generalizing to a post-fan-on corroboration window (6 min, mmwave-only occupancy needs a fan-immune witness) is DEFERRED per operator decision and `feedback_marginal_benefit_pushback` — marginal benefit over C1a + C2 + C3 is small and the "deny mmwave-only occupancy" ingredient has the sleeping-still-person risk. Revisit if the week-after measurement shows a residual phantom-creation problem.

### Acceptance Criteria
- **Verify (code):** `FAN_TRANSITION_SUSPECT_WINDOW_S == 0.0`; gate branch at `coordinator.py:3649` short-circuits before reading `_fan_last_transition`.
- **Test:** `test_transition_gate_disabled_when_window_zero` (mutation anchor: setting window = 5.0 flips the test).
- **Live:** `_fan_transition_suppressed_count` stays constant post-ship (gate dormant); no new false-vacate incidents attributable to the gate removal (because C2 + C3 shoulder the load that was 23/27 fake anyway).

**Non-goal.** No code deletion.

---

## Measurement regime (acceptance)

Baseline = 2026-10-04→10-11 window + URA DB episodes since v5.84.1 (session scratchpad `fan_mmwave/`, promote to `scripts/fan_noise/` in this cycle, read-only, HA recorder + URA DB).

**One week after ship, re-run and record** (per-room):
- Empty + fan-on occupied minutes/week (target: Study A → <200).
- False-hold length p50/p90 by sensor family.
- Light minutes in empty rooms (comfort proxy).
- Mechanism fire/success/undo counts: recheck VACATED (no re-latch), D2 sustain demotion (fires in ≥5 of 7 previously-unreachable rooms), transition-gate (near-zero post-C5).
- **Guard metric:** `occupied→vacant while BLE says a person is present` count/week — MUST NOT rise.

Measurement scripts land in `scripts/fan_noise/` and emit a markdown report into `docs/articles/mmwave_fans_running_rejection_results.md` (new; the pre-existing `mmwave_fans_transition_gate.md` / `mmwave_fan_alignment_probe_results.md` get a one-line pointer, NOT re-cited as a conclusion — per PRESENCE §10.1).

---

## Rejected or deferred solutions (and why)
| Option | Verdict | Reason |
|---|---|---|
| Use the radar's internal "motion" output as the fan-immune witness | **Rejected** | Study A's ZG-204ZK exposes no separate motion output; where radars do (LD2410 moving target), the moving channel is exactly what a fan's Doppler triggers (Jaya: moving channel lit with fan alone). A PIR element inside a combo unit would work — none in Study A. |
| Add the Study A InvisOutlet motion sensor as witness | **Rejected (operator)** | Unreliable for a long time; on the do-not-use list. |
| "Re-aim before any tuning — tuning can't recover a fan in view" | **Rejected (operator correction)** | Wrong for the ZK: anti-interference + distance tuning do vacate Study A; tuning is a first-class lever. Re-aiming stays optional. |
| Buy a second sensor (ZV/PIR) per fan room | **Deferred** | Cost; try tuning + software first, measure, then decide room by room. |
| Widen the 5 s gate to minutes as-is | **Rejected** | Gate only delays creation; longer delay still lets latch through. Superseded by C1a + C2 + C3; C5 retires it. |
| Move Living Room's mmWave out of `motion_sensors` | **Rejected (retracted)** | ZG-204ZV is motion-class — correctly filed. Real bug is name-based classification (C2). |
| Rely on BLE alone as the witness | **Deferred** | BLE room location is noisy (operator's sensor changed 4,262×/week); usable as one witness among several, not alone. |
| Fan-distance-band veto in URA (ignore detections at the fan's range while it runs) | **Deferred** | High value only for distance-reporting radars (ESPHome LD24xx, Meross); needs distance/energy recorded first; Study A's Zigbee reports no distance. Separate cycle after this one. |
| Require corroboration for any mmWave-only hold while a fan runs (C1b general rule) | **Deferred** | Highest coverage but risks dropping still/sleeping people; revisit with this cycle's measured residual. |
| Per-room learned energy baseline (background subtraction) | **Deferred / parked** | Needs per-bin energy history and labelled data; mostly superseded by on-device tuning. |
| URA writes radar settings dynamically while the fan runs | **Deferred** | Carded as URA-SENSOR-TUNING-1 Phase B; Phase A (static, URA-owned settings) first. |
| LD2450 + polygon exclusion zones | **Deferred (hardware)** | Proven fix, but hardware; only for rooms that still fail after this cycle. |
| New flap→quarantine primitive in-cycle | **Deferred to OC-STUCK-SENSOR-GENERALIZE-1** | `chatter_detector`'s sub-1-s T_floor doesn't fit a ~40 s flap; cross-kind flap belongs in the generalized stuck-sensor detector. |
| New `is_fan_immune_witness` CONF field | **Rejected** | Already expressible via existing `CONF_SENSOR_CAPABILITIES` operator overrides; no new config surface. |

---

## Operator decisions + prior-art findings (2026-10-11)
- **C1 → C1a.** On VACATED the recheck leaves the fan OFF; normal fan logic restarts it when real occupancy returns.
- **C2 → REUSE, no new classification logic.** `domain_coordinators/sensor_capability.py` already defines kinds with trust classes, resolved by `derive_capability()` from CONF lists plus per-entity operator overrides `CONF_SENSOR_CAPABILITIES`. Add a single pure helper `is_fan_immune_witness()` on top; rewrite `_d2_motion_sensors_present` + `_has_recent_motion` to consult it; drop `MMWAVE_NAME_PATTERN` from both call sites.
- **C3 → reuse quarantine (guard-only in-cycle).** Keep the one-line stamper guard; defer flap→exclusion to OC-STUCK-SENSOR-GENERALIZE-1; extend `UnavailableEntitiesSensor` input list to include `CONF_FANS`.
