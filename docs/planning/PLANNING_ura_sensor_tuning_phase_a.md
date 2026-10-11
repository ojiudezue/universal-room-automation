# PLANNING — URA-SENSOR-TUNING-1 Phase A (static per-room radar settings)

**Card:** `URA-SENSOR-TUNING-1` (`docs/planning/kanban.data.yaml:30909`)
**Tier:** 2 (feature cycle; new config surface + new writer + re-assert loop; cross-coordinator
touch via actuator_reconciler pattern). Plan review required before build dispatch.
**Scope:** Phase A ONLY — static per-room target settings for a room's presence radars,
applied + drift-reconciled + mismatch-surfaced. **Non-goal:** Phase B dynamic fan-aware tuning
(gated on marginal benefit; see §Non-goals).
**Date:** 2026-10-11
**Author:** ura-planner (orchestrator)
**Deliverable form:** docs only, no commit; after plan review the build dispatches on a
feature branch.

---

## Pre-flight — docs read COMPLETELY

I read COMPLETELY, in this planning session:

- `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` end-to-end, including the §10
  corrections ledger and the **Gold patterns index** at the bottom (capability layer, role
  matrix, SensorExclusionSet, recheck state machine, inert-sink eligibility probe, CM-entry
  timing sweep, fan listener, ActuatorReconciler flap counter, fan-immune witness, HVAC
  leave-off discharge, kill-switch knob ladder, memory-episode write, FAN_TRUST_STATES scope).
- `docs/architecture/SENSOR_FLEET_CLASSES.md` end-to-end (Hobeian ZV/ZK/ZX families + counts,
  the 4 Rules, ZV fan susceptibility table, do-not-use list, Meross MS600 dual-homed ruling,
  ESPHome LD2410 family note, combined-sensor rule corrected 2026-10-11).

Both are cited below where their claims drive this plan.

---

## Problem (one paragraph)

Presence-radar settings — sensitivity (motion/static), detection distance, anti-interference,
fading/hold time — decide fan rejection and false-hold rate (operator, 2026-10-11: on-device
tuning is the biggest Study A lever even with the fan in view;
`PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md:476`). Today those settings are set by hand in Z2M /
on the device and forgotten; they drift silently on factory-reset, re-pair, or manual edit.
Study A was tuned 2026-10-11 (motion 8→5, static 8→6, distance 4.34→3.0 m, before-values in
`scratchpad/studya_zk_before_2026-10-11.json`); Wigton's 17-unit fleet was tuned by one-shot
script (`scratchpad/remote_tune.py`: motion ≤6, static 6, fading 120 s, distance ≤4 m except
master/living). Phase A owns those target settings in URA: per-room, per-radar, applied,
drift-reconciled, mismatch-visible, non-destructive against operator edits.

## Falsifiable invariant (the one property Phase A must guarantee)

> **For every entity listed under URA-managed tuning in a room config:** at any wall-clock
> time ≥ `TUNE_SETTLE_S` after the entity last became `available`, EITHER (a) its live HA
> state equals the URA target for every URA-managed field, OR (b) the room's
> `sensor.<room>_tuning_status` is `drifted` and names the field, OR (c) the entity is
> `unavailable` / out-of-range / write-rate-limited and the status is `pending`.
> **Never** `applied` while live ≠ target.
>
> **Second invariant (non-destruction):** URA writes ONLY to fields the operator set in URA
> for that entity. A field the operator did not set (empty in options) is never written —
> URA is a quiet second writer, not a fleet enforcer.

D (adversarial-completeness, if elevated) breaks this by: factory reset mid-reconcile; a
field toggled in Z2M while URA write is in-flight on a battery device; options cleared while
drift is pending; entity rename.

---

## Institutional context verified

### Design docs read
- `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (full) — gold patterns, FAN_TRUST_STATES scope,
  corrections ledger §10 items 5+8 (`CONF_MMWAVE_SENSORS = "presence_sensors"`, no
  `CONF_PRESENCE_SENSORS` constant; capability is routed through `sensor_capability.py`).
- `SENSOR_FLEET_CLASSES.md` (full) — per-model defaults source of truth; ZV never gets tuned
  as a radar (motion-class); MS600 dual-homed; LD2410 ESPHome fields are
  moving/still distance + energy. **Phase A defaults ONLY exist for ZK, ZX, MS600 (native
  meross_lan), LD2410 (ESPHome), Tuya TS0601 at Wigton, Screek. ZV has no radar knobs to
  own.**

### Prior planning docs skimmed
- `RESEARCH_fan_resistant_mmwave.md` — tuning is a first-class lever (§CORRECTION 2026-10-11,
  op); re-aim is an option, not a prerequisite.
- `RUNBOOK_wigton_ura_reenable.md` — Wigton G4/G5 sensors-tuned gate names the fleet script
  as the current (manual) implementation; this plan replaces that with a URA-owned surface
  in time for staged-on.
- Fan-noise cycle: `PLANNING_fan_noise_running_rejection.md` prior-art audit (its gold
  patterns index is reproduced in `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`).
- Cards `OCCUPANCY-SOURCE-FOLLOWS-CAPABILITY-1`, `OC-STUCK-SENSOR-GENERALIZE-1`,
  `FAN-ZV-POWERON-TRANSIENT-GATE-1`, `ROOM-CREATE-AREA-PREFILL-DETRITUS-1`,
  `SENSOR-FORM-PLAIN-TEXT-1`.

### Memory bodies pulled
- `reference_sensor_fleet_classes` (encoded in SENSOR_FLEET_CLASSES.md).
- `feedback_label_style_guide` — ≤3-word HA entity names, no nerd words (hysteresis,
  provenance, substrate).
- `feedback_configurability_clarity` — named-bucket dropdowns with one-sentence consequence
  text; set-once knobs in config/options flow, not runtime Numbers; raw multipliers hidden
  behind buckets.
- `feedback_parsimonious_room_config` — show the knob inventory before deploy for pruning;
  do not expose every internal timing constant.
- `feedback_config_first_before_code` — step 1b of the build gate: read live values before
  asserting a knob is at a given value.
- `feedback_do_robust_fix_not_bandaid_and_card`.
- `feedback_marginal_benefit_pushback` — explicit § on Phase B marginal gate.

### Prior-art scan (REUSE > EXTEND > BUILD) — per proposed piece

| Proposed piece | Verdict | Existing symbol | Why |
|---|---|---|---|
| Per-room target map for radar settings | **BUILD** (new options surface) | — | No existing per-room "radar tuning target" surface; grep of `const.py` found `CONF_SENSOR_CAPABILITIES` (overrides capability KIND, not device fields) and `CONF_SCANNER_AREAS` (Bermuda), none write device fields. Config lives naturally in the room options flow. |
| Per-model default table (ZK / ZX / MS600 / LD2410 / TS0601 / Screek) | **REUSE** source-of-truth from `SENSOR_FLEET_CLASSES.md` + extend `sensor_capability.FAMILY_BY_MODEL_ID` (`sensor_capability.py` referenced from `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md:273`) with a sibling `TUNING_DEFAULTS_BY_FAMILY` map keyed by the same families. Family resolver already exists (`fan_veto.resolve_sensor_family`, `fan_veto.py:81`, gold patterns index). |
| Resolve the radar's underlying Number/Select/Switch entities on the device | **REUSE** HA device registry → entity registry (same path used by `coordinator._resolve_room_switch_entity_id`, `coordinator.py:3028-3074`, PRESENCE §4.5). Phase A adds a small helper that, given a presence-sensor binary_sensor entity, walks `entity_registry.async_get(…).device_id` → `entity_registry.async_entries_for_device(device_id)` and filters by domain + unique_id suffix per family. No new registry infra. |
| Apply writes (set a HA number / select / switch) | **BUILD** — but trivial: `hass.services.async_call("number", "set_value", …)` / `select.select_option` / `switch.turn_on|off`. Precedent for service-call writes exists in energy coordinators (grep `number.set_value`: `energy.py`, `energy_pool.py`, `energy_battery.py`). No URA "write-config-number" helper exists; one small helper lives in the new file. |
| Drift re-assert loop | **REUSE PATTERN** `ActuatorReconciler` (`actuator_reconciler.py:137`): listener-driven, debounced, flap-counting, RAM-only (`PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` Gold index). We **do not** instantiate a second reconciler; we add a tiny sibling `RadarTuningReconciler` modeled on it, SHARING the flap-detector + rate-cap patterns but NOT its code (actuators and radar-tuning writes have different cadence budgets — see §Battery/write-rate). |
| Mismatch surface (per-room) | **REUSE PATTERN** `sensor.<room>_unavailable_entities` (sensor.py:1773–1862). Phase A adds a per-room `sensor.<room>_tuning_status` that follows the SAME attribute-rich surface pattern (state = one of `applied | drifted | pending | unmanaged`; attrs enumerate per-entity, per-field live vs target). |
| House-wide roll-up | **REUSE PATTERN** `unavailable_entities` house watchdog aggregator precedent (sensor.py:219). One `sensor.ura_tuning_status` roll-up (count of rooms in `drifted`). |
| Options-flow fields | **REUSE** advanced/_adv step pattern in `config_flow.py` (see `caps_kind__<entity>` dropdown pattern, `config_flow.py:12524+`). Phase A adds a new per-sensor advanced section driven by family-defaults with per-field override and a "USE DEFAULT" marker. |
| Named-bucket labels (operator-friendly) | **REUSE** feedback_configurability_clarity precedent; raw sensitivity numbers (1–10) are hidden behind named buckets at the room options flow (see §Label style). The JSON escape hatch is advanced-only (parity with `SENSOR-FORM-PLAIN-TEXT-1`). |
| Factory-reset / re-pair detection | **REUSE** entity `last_updated` + a known-good hash of live values + the drift-detection equality check. No new "device-event" listener needed — a factory reset manifests as live ≠ target on the next number/select state change the entity emits. |
| Write-rate limit | **REUSE PATTERN** `_reconcile_times` / `_flap_windows` deques (`actuator_reconciler.py:154-178`). |
| Kill switch | **REUSE PATTERN** kill-switch rung-1 constant + CM-entry rung-2 toggle (`FAN_TRANSITION_SUSPECT_WINDOW_S` precedent, Gold index). |

**Config-first check (step 1b):** every setting Phase A proposes to own already exists as an
HA number/select/switch on the device (Z2M-exposed). The gap is NOT "add a new HA knob"; it
is "URA tracks the target and reasserts it". No code is unnecessary — but Phase B IS pure
code and may be unnecessary if Phase A + the fan-noise fixes close the measured gap. See
§Marginal-benefit gate.

### Code locations surveyed end-to-end during scoping
- `custom_components/universal_room_automation/actuator_reconciler.py` (first 400 lines +
  listener-arm / flap / `check_quarantine_release` / `_FAN_KEYS`).
- `custom_components/universal_room_automation/domain_coordinators/sensor_capability.py`
  (`derive_capability`, `FAMILY_BY_MODEL_ID`, `is_fan_immune_witness`).
- `custom_components/universal_room_automation/fan_veto.py:51-120` (family resolver +
  model fallback).
- `custom_components/universal_room_automation/coordinator.py:3028-3074` (registry-first
  resolver precedent).
- `custom_components/universal_room_automation/sensor.py:1773-2065` (unavailable-entities
  surface pattern).
- `custom_components/universal_room_automation/config_flow.py:12254-12578` (capability
  options-flow sub-step pattern + per-entity dropdowns).
- `custom_components/universal_room_automation/const.py:480` (`CONF_MMWAVE_SENSORS =
  "presence_sensors"`), `:559` (`CONF_SENSOR_CAPABILITIES`), `:564` (`CONF_SCANNER_AREAS`).

### Measure-before-build note
The empirical gates ARE already run:
1. Study A tuning before/after is in `scratchpad/studya_zk_before_2026-10-11.json` + session;
   false-hold measurement is the acceptance oracle for Phase A at Study A.
2. Wigton fleet-wide `remote_tune.py` ran 2026-10-11; its emitted target vector IS the
   acceptance fixture Phase A must reproduce via the options-flow + default table (hand-built
   fixture → acceptance). We will commit a diffable `AUDIT_radar_tuning_targets_wigton.md`
   with the per-entity target table BEFORE the build dispatches; the build is diffed against
   it (one-shot read-only query across both houses' `.storage/core.entity_registry` +
   `core.restore_state` for the current number entity values).

No additional probe needed to START Phase A. A separate 2-week residual-false-hold probe
feeds the Phase B marginal-benefit gate (§Non-goals).

---

## Design overview

### Writer boundary — URA owns ONLY fields the operator set in URA

- The per-sensor options block has, per URA-managed field, three UI states:
  **USE DEFAULT (family)** / **CUSTOM (named-bucket or number)** / **DO NOT MANAGE (empty)**.
- `DO NOT MANAGE` means **URA never writes that field** on that entity. This is the
  non-destruction invariant. The default is `DO NOT MANAGE` for every field at install
  (no silent drift from a URA update). A new install picks `USE DEFAULT (family)` when the
  operator opens the sensor's advanced panel and clicks "Apply family defaults".
- Values the operator sets in Z2M that URA does not track remain untouched forever. URA
  never deletes, never writes an unset field, never re-asserts without a target.

### Second-writer precedence
On any live ≠ target discovered, Phase A ONLY writes `target`. It does NOT revert operator
Z2M changes to UNMANAGED fields. If live ≠ target on a MANAGED field and the operator wants
the live value kept, they change the URA target in options — same ladder as every URA knob.

### Battery / write-rate
- Hard rate cap: **one write per entity per 24 h** on any single field, EXCEPT the first-apply
  immediately after an options change (operator intent) and the first-apply when the entity
  comes back from `unavailable` after > 1 h (post-rejoin re-assert).
- A write is attempted at most **once per wake interval** on a battery Zigbee device:
  URA fires the write on the next `last_updated` state change the entity emits (proxy for
  "the device is awake"), with a 60-second settle timer, then checks whether live converged;
  if not, back off exponentially (5m / 30m / 2h / 6h) with jitter, capped at 24h.
- **Never** writes while the entity is `unavailable` — the entity would just drop the write.
- The 24h/entity cap and the write-only-on-wake behaviour ARE the "writes cost battery"
  mitigation named in the card's constraints.

### Drift re-assert — restart safety
- At `async_added_to_hass`, after `BOOT_SETTLE_MIN_INPUTS` (`const.py:3789`) is satisfied,
  the room reconciler performs ONE drift check per MANAGED entity. If live ≠ target it
  schedules a wake-gated re-assert; it does NOT force a service call on boot (RestoreEntity
  / cloud-integration unavailable-OFF poisoning precedent, memory
  `project_envoy_boot_incident_2026_06_12`). This is the "a factory reset / re-pair / manual
  Z2M change is DETECTED and surfaced before it is RE-ASSERTED" discipline.
- Flap quarantine (modeled on `actuator_reconciler._flap_windows`): if a field flips live ↔
  target more than K times in W minutes (K=3, W=60 default; the rung-2 CM-entry knob
  `tuning_flap_window_minutes`), quarantine that field on that entity until the operator
  clears via `button.<room>_release_tuning_flap`. State surfaces as `drifted (quarantined)`.

### Mismatch surface
- Per-room `sensor.<room>_tuning_status`:
  - state ∈ `applied | drifted | pending | unmanaged | boot_settling`
  - attributes: `managed_entities` (list), `per_field` (dict → `{entity_id, field,
    target, live, state, last_write_iso}`), `write_budget_remaining_today`, `last_drift_iso`.
- House roll-up `sensor.ura_tuning_status`: state = total `drifted` field-count across rooms.

### Never-desensitised safety (card constraint)
Phase A cannot leave a radar more desensitised than its FAMILY default. If an operator's
`CUSTOM` target is numerically more sensitive OR within one bucket of the family-default
value, the write is permitted; if the operator's target is MORE desensitised than the family
default (lower sensitivity / shorter distance / longer fading), the options-flow validator
raises a soft WARNING at save time ("this is less sensitive than the family default — are
you sure?") — not blocking, since Study A legitimately runs a lower-sensitivity target. The
hard safety is: at restart, if the target is less sensitive than family default AND the live
value is sensitive, the first-apply is DEBOUNCED by 10 minutes to give the operator time to
revert.

---

## Deliverables

### D1 — Per-model `TUNING_DEFAULTS_BY_FAMILY` + family resolver sibling
Add a `tuning_defaults` map in a new module
`custom_components/universal_room_automation/domain_coordinators/radar_tuning_defaults.py`,
keyed by the same family tokens as `sensor_capability.FAMILY_BY_MODEL_ID`. Each entry names
the URA-tracked fields and their family-default target. Phase A tracks ONLY these fields per
family (anything else = `DO NOT MANAGE`):

- `hobeian_zk`: motion_sensitivity, static_sensitivity, detection_distance,
  anti_interference, fading_time.
- `hobeian_zx`: same five.
- `tuya_ts0601_radar`: motion_sensitivity, detection_distance, fading_time
  (anti_interference not uniformly exposed — Wigton verified at build-time against the
  AUDIT fixture).
- `meross_ms600_matter`: nothing in Phase A (Matter binary is read-only); defer.
- `meross_ms600_native`: distance target only — writable via meross_lan? **VERIFY at build;
  if read-only, defer this family.**
- `esphome_ld2410`: moving_distance, still_distance, moving_sensitivity, still_sensitivity,
  retention_time.
- `screek`: TBD at build — operator confirmation on which fields exist.

**Acceptance Criteria**
- **Verify:** `TUNING_DEFAULTS_BY_FAMILY` round-trips against the hand-built
  `docs/planning/AUDIT_radar_tuning_targets_wigton.md` fixture — every Wigton entity's
  per-field default equals the audit value.
- **Test:** `test_tuning_defaults_match_wigton_fixture` + `test_zv_has_no_tuning_entry` (ZV
  motion-class never acquires a tuning entry, per SENSOR_FLEET_CLASSES Rule 1).
- **Live:** none — pure constants.

### D2 — Per-sensor options-flow sub-step with named-bucket labels
Extend the capability sub-step at `config_flow.py:12524+` with a sibling "tuning" collapsible
block, per `presence_sensors` entity. Each tracked field renders as a dropdown with
`USE DEFAULT (family)` / `CUSTOM: <named-buckets>` / `DO NOT MANAGE`. Named buckets
(operator-facing labels — operator-friendly, no nerd words):

- **Motion sensitivity:** `Low (3)` / `Medium (5)` / `High (7)` / `Very high (9)`
  (raw 1–10 behind the labels; CUSTOM number allowed in Advanced JSON only).
- **Still-person sensitivity:** same four buckets.
- **How far it watches:** `Just the room (2 m)` / `Short (3 m)` / `Standard (4 m)` /
  `Long (6 m)`.
- **Ignore passing fans/airflow:** `Off` / `On` (anti_interference boolean).
- **Hold time after last movement:** `Short (30 s)` / `Standard (60 s)` /
  `Long (120 s)` / `Very long (300 s)`.

One-sentence consequence text under each dropdown, per `feedback_configurability_clarity`
(e.g. "Longer hold keeps lights on when you sit still, but delays turning them off after
you leave."). JSON escape hatch is Advanced-only (operator-coined
`feedback_label_style_guide` + `SENSOR-FORM-PLAIN-TEXT-1`).

**Acceptance Criteria**
- **Verify:** opening a room options flow → Advanced → Sensor tuning shows one block per
  managed `presence_sensors` entity with the five dropdowns, every field defaulting to
  `DO NOT MANAGE`.
- **Verify:** labels contain no nerd words (grep the strings: no `hysteresis`,
  `debounce`, `provenance`, `substrate`, `tier`, `failsafe`).
- **Test:** `test_options_flow_tuning_block_round_trips` (save → reload → values preserved);
  `test_tuning_block_hidden_for_zv_rooms` (ZV-only rooms get no tuning block).
- **Live:** at Wigton, Omonele can open a room options flow and set "How far it watches = Short
  (3 m)" on Game Room without reading any raw numbers.

### D3 — Writer + rate-limit + wake-gating
New module `custom_components/universal_room_automation/domain_coordinators/radar_tuning.py`
with class `RadarTuningReconciler(coordinator)`:
- `async_register_listeners` arms per-entity `async_track_state_change_event` on each
  managed tuning entity (radar's number/select/switch, not the binary_sensor).
- On state change: compute `drifted` = (live ≠ target) per managed field; schedule a
  wake-gated re-assert via the family-aware backoff (§Battery/write-rate).
- Writes go through `hass.services.async_call("number", "set_value", …)` /
  `select.select_option` / `switch.turn_on|off`.
- Rate caps and flap quarantine as in §Design overview.

**Acceptance Criteria**
- **Verify:** a factory-reset ZK with URA target `motion_sensitivity=5` returns to 5 within
  one wake-cycle + 60 s after the target state change fires.
- **Verify:** a MANAGED field written in Z2M mid-flight (while URA write is pending) does
  not cause a loop — flap counter trips at K=3 and quarantines the field.
- **Verify:** an UNMANAGED field is never written (set a value in Z2M, confirm URA emits no
  service call for it over 24 h via log scan + MCP call-site trace).
- **Test:** `test_write_rate_cap_one_per_24h_except_options_change`;
  `test_unavailable_entity_no_write`; `test_boot_first_apply_debounced`;
  `test_flap_quarantine_at_K_3_in_60min`; `test_do_not_manage_field_never_written`.
- **Live:** at Study A, after a manual Z2M flip of `motion_sensitivity` from 5→8, URA
  reasserts to 5 at the next wake event; log shows exactly ONE `set_value` call per field
  per wake.

### D4 — `sensor.<room>_tuning_status` + house roll-up
New `RoomTuningStatusSensor` in `sensor.py` (sibling to `UnavailableEntitiesSensor`), plus a
house-level `ura_tuning_status` aggregator.

**Acceptance Criteria**
- **Verify:** when every managed field is in-sync, state = `applied`; when one entity has a
  live ≠ target field, state = `drifted` and attribute `per_field` names the field +
  live/target.
- **Verify:** during the post-boot grace, state = `boot_settling`.
- **Test:** `test_sensor_state_applied_vs_drifted_vs_pending`;
  `test_house_rollup_counts_drifted_fields`.
- **Live:** at Study A immediately after deploy, `sensor.study_a_tuning_status` reports
  `applied` with 5 managed fields; `sensor.ura_tuning_status` reports `0`.

### D5 — Release-flap button + kill switch
- `button.<room>_release_tuning_flap` (clears quarantine for the room).
- Kill switch `switch.ura_sensor_tuning_enabled` (CM-entry rung-2 toggle, default ON). When
  OFF, writer is suspended; the status sensor stays live-vs-target and still surfaces
  `drifted`, but no service calls fire. Precedent: `CONF_FAN_RECHECK_*` kill-switch pattern.

**Acceptance Criteria**
- **Verify:** flipping the kill switch to OFF stops writes within one listener fire; flipping
  back to ON schedules a wake-gated re-assert for every drifted field.
- **Test:** `test_kill_switch_suspends_writer`; `test_release_flap_button_clears_quarantine`.
- **Live:** `switch.ura_sensor_tuning_enabled` toggles on the house dashboard; drift state
  visible before and after.

### D6 — AUDIT fixture + README (same cycle)
- `docs/planning/AUDIT_radar_tuning_targets_wigton.md` — hand-built table (entity, family,
  per-field target). Phase A ships only after D1 round-trips against this.
- `docs/readmes/README_v<ver>.md` — prospective acceptance criteria; validation table written
  back post-restart (CLAUDE.md: Record Live Validation Back Into the README).

**Acceptance Criteria**
- **Verify:** AUDIT fixture committed with cycle.
- **Live:** README post-restart table lists each AC with observed value.

---

## Knob ladder (every number named)

| Knob | Rung | Default | Kill-switch? | Why that rung |
|---|---|---|---|---|
| `TUNE_SETTLE_S` (post-wake settle before drift check) | **1** module const | 60 s | — | Protocol window; operator should never need to tune. |
| `TUNE_WRITE_RATE_PER_DAY_PER_ENTITY` | **1** module const | 1/entity/field | — | Battery-safety bound. |
| `TUNE_BACKOFF_SCHEDULE_S` | **1** module const | `[300, 1800, 7200, 21600]` | — | Backoff. |
| `TUNE_FLAP_K` / `TUNE_FLAP_WINDOW_MIN` | **2** CM-entry (Number) | K=3 / W=60 | — | Operator-tunable per observation. |
| `switch.ura_sensor_tuning_enabled` | **3** live switch | ON | **YES** (OFF disables writer) | Feature kill switch; label "Keep sensor settings". |
| Per-sensor targets (motion / static / distance / anti-interference / fading) | **2** options flow | `DO NOT MANAGE` | Field-level kill (DO NOT MANAGE) | Per-deployment structure. |
| `TUNING_DEFAULTS_BY_FAMILY` (per-model defaults) | **1** module const | per SENSOR_FLEET_CLASSES | — | Change should require review (safety against desensitising). |

---

## Live impact — pre-build read-only probe (both houses)

Phase A will land into live traffic from day one; before build, the orchestrator runs ONE
read-only probe (no writes), captured in `AUDIT_radar_tuning_targets_wigton.md`:

- Main house: `/Users/okosisi/ha-config/.storage/core.entity_registry` +
  `.storage/core.restore_state` — for every presence-sensor binary_sensor, resolve its
  device, enumerate sibling `number.*` / `select.*` / `switch.*` entities, and record their
  current state.
- Wigton: `ssh wigton 'cat /homeassistant/.storage/core.entity_registry'` +
  `.storage/core.restore_state` — same traversal. The AUDIT table rows are the
  hand-built fixture D1 is diffed against.

**Blast radius:** limited to each room's radar devices and the new sensors/button/switch
surfaces. No HVAC path, no house-state path, no actuator path. Phase A is additive — no
existing writer path changes.

---

## Non-goals / rejected options

- **Phase B dynamic fan-aware tuning — DEFERRED, gated on marginal-benefit.** Trigger to
  revisit: ≥2 weeks of post-Phase-A false-hold data in Study A + at least one other fan room
  AT a measured false-hold rate > the operator pain threshold (1/day/room) **AND** the
  fan-noise Rev 2 fixes (recheck no-restore, D2 capability classification, fan-oracle live
  entities) have been shipped and measured. Rationale (`feedback_marginal_benefit_pushback`):
  Phase A + fan-noise Rev 2 may close the measured gap at zero additional risk; Phase B's
  marginal ingredient risk is high (per-cycle writes → battery cost + a NEW cross-coordinator
  writer timed on fan transitions, a known-dangerous seam — reload-storm precedent).
- **URA will not write ZV motion-class radars.** They have no "radar knobs"; per
  `SENSOR_FLEET_CLASSES.md` Rule 1.
- **URA will not write Matter MS600 presence binaries** (read-only Matter cluster). The
  deferred native-meross_lan distance target is build-verified.
- **URA will not touch any field the operator did not explicitly set in URA.** Second-writer
  precedence against Z2M is "URA writes what URA knows, never what URA doesn't know".
- **No bulk apply across rooms.** Each room's options flow is the unit; no "apply family
  defaults to the whole house" button (operator must open each room — intentional friction
  against a batch mistake).
- **No boot-time first-apply storm.** Boot does a drift CHECK only; writes wait for the next
  wake and the post-boot grace (precedent `_in_post_boot_grace`, `actuator_reconciler.py:393`).
- **No Z2M MQTT topic publication path.** URA writes HA entities, not MQTT directly — Z2M
  mirrors HA number/select state back out. This keeps the writer boundary HA-standard and
  rejects a "custom MQTT writer" option considered and rejected (adds a parallel surface
  that Z2M renames would break).
- **No per-tick drift pass.** Drift is listener-driven (state-change event). A periodic
  sweep is REJECTED (noise, battery, no observed value).

---

## Review classification + plan review

- **Tier: 2** (new feature, multiple files, new sensors/switch/button, writer, options
  flow).
- **Not Tier 2-DB** — no `database.py` touch, no payload-shape migration.
- **Not Tier 3** — no shared primitive consumed by many sites; blast radius is confined to
  the room entry's own radar devices; the one write path is behind a kill switch and a
  non-destruction invariant.
- If the plan reviewer argues the "second writer vs Z2M" is a cross-coordinator ripple,
  elevate to Tier 2-DB (3 framing-disjoint reviews: A correctness, B restart/battery, C
  options-flow + button + sensor surfaces + fixture authority).
- Plan review MANDATORY before build dispatch (operator-coined 2026-08-11); reviewer
  independently re-greps `number.set_value`, `set_option`, `derive_capability`,
  `FAMILY_BY_MODEL_ID` across the repo, verifies the prior-art table, and challenges the
  non-destruction invariant with a specific DO NOT MANAGE scenario.

---

## Open questions for plan reviewer

1. Should `switch.ura_sensor_tuning_enabled` be CM-entry (one switch for the whole house)
   or per-room (`switch.<room>_sensor_tuning_enabled`)? Current pick: CM-entry single kill
   switch; operator can also set every room's fields to `DO NOT MANAGE` for per-room pause.
2. For `meross_ms600_native` and `screek`: build-time field verification needed; is the
   plan allowed to defer those families to a Phase A.1 if their writable field set is
   unclear at build dispatch?
3. The named-bucket labels in D2 — defer final wording to a plan-review comment pass, or
   lock them here? Current pick: lock; wording changes are string-only and cheap.
