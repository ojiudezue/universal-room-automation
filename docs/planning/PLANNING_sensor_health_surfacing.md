# PLANNING — Sensor Health Surfacing (chatter detector + unhealthy-sensors + NM replace hook)

**Card:** `SENSOR-HEALTH-SURFACING-1`
**Tier:** 2 (Feature cycle — two framing-disjoint reviews + live validation)
**Created:** 2026-08-18
**Origin:** `AUDIT_roadmap_undone_worthwhile.md` #1 — "cheapest high-value undone."
**Trigger evidence:** `docs/planning/INCIDENT_chatter_class_missed_by_watchdog_2026-08-09.md` — measured 3,769 off / 3,765 on / 6 unavailable in 24 h on Garage B ratgdo. Both shipped detectors (P22 continuous-on, D2 ≥85 % duty) are structurally blind to ~50 % oscillation: every off-tick resets `_sensor_on_since`, and on-ratio never approaches 85 %.

Tier-2 (not Tier 2-DB): additive detector consuming the existing recorder history, one new `kind` on the existing NM hook, an attribute extension on an existing diagnostic sensor. No schema change. No cross-coordinator trust ripple. If the reviewer disagrees, elevate.

---

## 1. Institutional context verified

### 1.1 Greps run + REUSED / NEW ledger

| Proposed | Verdict | Evidence |
|---|---|---|
| Chatter/flap detection on **sensor values** | **NEW** | `grep -r chatter custom_components/` → 0 hits in code. All `flap` hits refer to (a) ACTUATOR availability quarantine (D2.11 `_actuator_reconciler.flapping_entities()`, `CONF_FLAP_SENSITIVITY` — `config_flow.py:10005-10063`, `const.py:2988-3018`), (b) BLE roam flap (`const.py:2810,2988`), or (c) preset/state hysteresis. None score sensor value oscillation. |
| Stuck-on watchdog to complement | **REUSED** | `coordinator._detect_duty_cycle_stuck` (`coordinator.py:1576-1770`) + `_stuck_sensor_hours` continuous-on check (`sensor.py:2296,2353`). Chatter is an orthogonal transition-rate rule — must **share the same corroborator + boot-settle gates** so it doesn't fire during warm-up or when PIR proves the flapping sensor is real. |
| `sensor.<room>_unavailable_entities` for surfacing | **REUSED, EXTENDED** | `UnavailableEntitiesSensor` (`sensor.py:1677-1900`) already lists unavailable INPUT sensors AND flapping ACTUATORS (D2.11) with `details[].reason ∈ {device_unreachable, offline_since_restart, entity_missing, state_unknown, flapping}` + `transition_count` + `since`. **Add reason `"chattering"`** with the same shape — one new branch in `_unavailable_details()`. Parsimony: no new sensor. **`ura_unhealthy_sensors` = NOT NEEDED as a separate entity.** |
| NM "replace this sensor" hook | **REUSED** | `fire_stuck_signal(kind, key, diagnosis, remedy, ...)` (`_stuck_signal_nm.py:165-264`) already coalesces per (kind, key)/day, persists an anomaly row (`_write_stuck_anomaly` at `:162`), and has a `remedy: str` field literally intended for the operator hint. Chatter enters as `kind="chatter"` on the existing hazard_type `stuck_signal` (`const.py:3778`). Sub-classification list `const.py:3773-3776` gets `chatter` appended. |
| `sensor_health` persistence table | **NOT JUSTIFIED — NEW rejected** | Every chatter fire already persists to `anomaly_log` via `_write_stuck_anomaly`. A dedicated table would duplicate the same rows with a stronger schema commitment, and per-day-latched writes preclude the write-flood pressure that would justify a specialized table. Deferred; revisit only if a future consumer needs a rate-of-flap time series (record the trigger, don't build the table). |
| `CONF_CHATTER_*` (operator-settable) | **NEW rejected — use module constants** | Per "Numbers Get Knobs" ladder: chatter sensitivity is a **detection-quality knob**; changing it should require review (rung 1). Sibling of `STUCK_D2_MIN_MOTION_TRANSITIONS` / `STUCK_D2_FRESH_MOTION_SECONDS` (`const.py:3711-3720`), which are module constants for the same reason. Kill switch mirrors `CONF_STUCK_SIGNAL_NM_ENABLED` (rung 2, already exists). |
| Boot-settle predicate for the new detector | **REUSED** | `self._d2_boot_settle_done()` (`coordinator.py:1644`). Chatter must gate on the same predicate or it will misfire on the restart re-hydration burst. |
| Per-day dedup latch | **REUSED** | `_LATCHES` in `_stuck_signal_nm.py:47`. Keying by `(kind="chatter", (entity_id,))` gets it for free. |
| PIR-corroboration anchor | **REUSED (with fix)** | Same `effective_corroborators` list D2 builds (`coordinator.py:1693`). **But** the incident memo §3.2 warned: "the anchor can be the broken thing" — if the chatterer IS a PIR, it would self-corroborate. Chatter detector MUST evaluate PIRs too (unlike D2 which excludes them), and MUST NOT count the candidate's own transitions toward corroboration. |
| Sensor kind → CONF bucket mapping | **REUSED** | `occupancy_substrate._KIND_TO_CONF` (`occupancy_substrate.py:81`) + `TIER1_KINDS` (`const.py:342`). Candidate set enumerates the room's motion_sensors ∪ mmwave_sensors ∪ occupancy_sensors. |

### 1.2 Prior planning docs consulted
- `docs/planning/INCIDENT_chatter_class_missed_by_watchdog_2026-08-09.md` — full read; defines the invariant and the exact class the shipped watchdog misses.
- `docs/planning/PLANNING_stuck_signal_watchdog.md` — read for the D2 detector contract (referenced by `_stuck_signal_nm.py:3`).
- `docs/planning/PLANNING_signal_trust_ledger_abstraction.md` — read GO-criterion 3 section. Constraint captured: **the ledger's "Extraction, not invention" rule means chatter must ship CONCRETELY here, not as a ledger primitive.** This planning doc respects that: extend `_detect_duty_cycle_stuck`, share NM hook, defer ledger migration.
- `docs/planning/AUDIT_mmwave_only_rooms_2026-07-31.md` Finding 6 — noted: 6 rooms have no PIR at all; chatter detector CAN score them (unlike D2, since chatter needs no anchor), but the "replace this sensor" NM there is the only useful output — no corroboration is possible.

### 1.3 Memory bodies pulled
- `feedback_suppression_needs_discharge.md` — per-day latch is a suppression; discharge is calendar-day rollover (existing behavior) + `fire_stuck_signal_recovered` clears the latch on healthy re-classification. Backstop: latch prune (`_prune_stale_latches`).
- `feedback_wire_in_anchor_mandatory.md` — every deliverable's acceptance test names the enclosing method + the specific value that must be observed post-deploy. Neuter-drill script in D4.

### 1.4 Design docs read
- No `docs/Coordinator/<NAME>.md` for a "sensor_health" coordinator; not creating one — this is a detector extension inside `coordinator.py` + an attribute extension inside `sensor.py`.

### 1.5 Code locations surveyed end-to-end
- `custom_components/universal_room_automation/coordinator.py:1576-1780` (D2 duty-cycle detector, corroborator construction, boot-settle gate).
- `custom_components/universal_room_automation/sensor.py:1677-1900` (UnavailableEntitiesSensor incl. flapping-actuator surfacing).
- `custom_components/universal_room_automation/domain_coordinators/_stuck_signal_nm.py` (fire/recovered/get_emit_stats).
- `custom_components/universal_room_automation/const.py:3680-3780` (all STUCK_* constants).
- `custom_components/universal_room_automation/domain_coordinators/occupancy_substrate.py` (kind→conf mapping).

---

## 2. Falsifiable invariant

> **Under any legal room configuration, a room-input sensor whose state-transition rate over a rolling `CHATTER_WINDOW_MIN` minutes exceeds `CHATTER_MIN_TRANSITIONS_PER_MIN` AND whose transitions are NOT corroborated by an independent (different-entity-id) transition in the same window MUST, within one detector tick after boot-settle completes, appear in `sensor.<room>_unavailable_entities.attributes.details` with `reason == "chattering"` AND cause exactly one `stuck_signal` NM per calendar day with `kind == "chatter"` and a non-empty `remedy` naming the entity.**
>
> Conversely: a healthy sensor whose transitions are corroborated by any independent room-input transition inside the window MUST NOT appear as chattering.

Reviewer D's job: break this invariant with any legal `CONF_MOTION_SENSORS / _MMWAVE_SENSORS / _OCCUPANCY_SENSORS` combination — including the incident's Garage B shape (`mmwave_sensors: None`, `occupancy_sensors: []`, ratgdo as the only member of a room-input list).

---

## 3. Deliverables

### D1 — Chatter detector (transition-rate) in `coordinator.py`

**Location:** new method `_detect_chatter(self, now, motion, mmwave, occupancy, room_name) -> set[str]` sibling to `_detect_duty_cycle_stuck`, called from the same tick site (`coordinator.py:2544`).

**Algorithm:**
1. Candidate set: `motion ∪ mmwave ∪ occupancy` (PIR INCLUDED — chatter, unlike D2, must score PIRs; §3.1 of the incident memo).
2. Per-candidate deque of `(monotonic_seconds, bool_on)` samples (bounded by window; identical container to D2).
3. Boot-settle gate: reuse `self._d2_boot_settle_done()`.
4. Warm-up floor: skip verdict if `< CHATTER_MIN_TICKS` samples.
5. Compute `transitions_per_min = transition_count / window_min`.
6. Corroboration: `transitions_per_min > CHATTER_MIN_TRANSITIONS_PER_MIN` AND *no other* (different `entity_id`) candidate produced ≥1 transition in the same window → mark chattering. (Own-transitions do not corroborate — closes the "anchor is the broken thing" gap.)
7. Return the set. Persist to `self._chattering_entities: set[str]` for the sensor-attribute consumer to read.

**REUSED:** deque plumbing, boot-settle, `CONF_ENTRY_TYPE / DOMAIN` merge — copy the D2 pattern verbatim.

**NEW justification:** D2's duty-cycle math cannot express transition-rate without conflating it with duty; a separate method keeps each rule independently readable and independently killable.

#### Acceptance Criteria — D1
- **Verify:** unit test with a synthetic 60-min window, entity A oscillating 4×/min, no other transitions → `_detect_chatter` returns `{A}`.
- **Verify (discriminator):** entity A oscillating 4×/min AND entity B recording 3 transitions in-window → `_detect_chatter` returns `∅`. (Corroborated = real.)
- **Verify (incident replay):** feed the Garage B 24 h recorder shape (3,769 off / 3,765 on, no other room sensors) → returns `{ratgdo_entity_id}`. Same fixture where `_detect_duty_cycle_stuck` returns `∅` — proves the detector complements, not duplicates.
- **Test:** `test_chatter_detector_flags_oscillator`, `test_chatter_detector_ignores_corroborated`, `test_chatter_detector_boot_settle_gated`, `test_chatter_detector_own_transitions_do_not_corroborate`, `test_chatter_detector_replay_garage_b_incident_2026_08_09`.
- **Live:** post-restart, `coordinator._chattering_entities` on the master-bedroom coordinator is a `set` (initially empty), not `None`.

### D2 — Chatter → NM emit via `fire_stuck_signal`

**Location:** in the same tick site that already awaits `fire_stuck_signal` for `dutycycle`/`continuous`, add one call per newly-chattering entity:

```
kind      = "chatter"
key       = (entity_id,)
diagnosis = f"{entity_id} transitioned {n} times in {window_min}min ({rate:.1f}/min), uncorroborated by any other room sensor"
remedy    = f"Replace sensor {entity_id} — chatter pattern indicates hardware fault (loose contact / dying battery / RF interference)"
title_override = f"Chattering sensor: {room_name} — {entity_id}"
```

Also: on recovery (entity drops back below threshold for a full window), call `fire_stuck_signal_recovered(kind="chatter", key=(entity_id,), message=...)` so the per-day latch clears and next flap re-notifies immediately.

**REUSED:** `fire_stuck_signal` (per-day latch, kill switch, anomaly persist, NM dispatch — all free), `fire_stuck_signal_recovered` for discharge. `STUCK_SIGNAL_NM_HAZARD_TYPE` unchanged. **Add** `"chatter"` to the sub-classification list at `const.py:3773-3776` (comment-only).

**NEW:** nothing.

#### Acceptance Criteria — D2
- **Verify:** unit-test with a stub NM captures exactly one dispatch on first tick; a second tick same-day dispatches zero; day-rollover dispatches one again. (Inherits D2 latch tests.)
- **Verify (discriminator):** `remedy` is non-empty AND contains the entity_id.
- **Verify:** kill switch — with `CONF_STUCK_SIGNAL_NM_ENABLED=False`, zero dispatches, and `_chattering_entities` still populated (detection independent of notification).
- **Test:** `test_chatter_nm_emit_once_per_day`, `test_chatter_nm_recovery_clears_latch`, `test_chatter_nm_kill_switch_silences_only_nm`.
- **Live:** after 1 h of live run on a room with a known chattering sensor (Garage B ratgdo if still flapping), `SELECT COUNT(*) FROM anomaly_log WHERE anomaly_type='stuck_signal' AND json_extract(payload,'$.kind')='chatter'` is ≥ 1; NM `stuck_signal` fired-today counter (`get_emit_stats()["chatter"]`) is ≥ 1.

### D3 — Extend `UnavailableEntitiesSensor` with chattering-sensor surfacing

**Location:** `sensor.py:1814-1868` (`_unavailable_details`). Mirror the flapping-actuator pattern (D2.11) for chattering INPUT sensors.

**Change:** after the existing `flapping_ids` collection, gather `chattering_ids = getattr(coordinator, "_chattering_entities", set())`. In the per-configured-entity loop, treat `is_chattering = eid in chattering_ids` symmetrically to `is_flapping`. When true, emit a `details` row with `reason="chattering"`, `transition_count=<from detector state>`, `since=<first-tick-flagged wallclock>`. Include the entity in the flat `unavailable_entities` list and in `unavailable_sensors` (it is a sensor, not an actuator).

**Consumer note (per Producer/Consumer rule §4):** the ONLY consumer of `sensor.<room>_unavailable_entities` is operator-facing (Lovelace / dashboard). No trust-decision code reads it. Adding chattering rows therefore has no cross-coordinator ripple.

**REUSED:** entire `_unavailable_details` machinery. Icon (`ICON_ANOMALY`). Category (diagnostic, disabled-by-default is fine — operator enables per room).

**NEW:** the reason string `"chattering"` and the two attrs (`transition_count`, `since`) — same shape as the flapping-actuator branch, so downstream template consumers get uniform schema.

#### Acceptance Criteria — D3
- **Verify:** unit test with a coordinator whose `_chattering_entities = {"binary_sensor.foo"}` → sensor's `extra_state_attributes["details"]` contains an entry `{entity_id: "binary_sensor.foo", reason: "chattering", transition_count: <int>, since: <iso-str>, ...}`.
- **Verify (discriminator):** coordinator with empty `_chattering_entities` produces zero `reason == "chattering"` rows.
- **Test:** `test_unavailable_entities_sensor_surfaces_chattering_sensor`, `test_unavailable_entities_sensor_no_chatter_when_set_empty`.
- **Live:** `ha_get_state("sensor.master_bedroom_unavailable_entities")` — attribute `details[*].reason` includes `"chattering"` iff `coordinator._chattering_entities` is non-empty.

### D4 — Neuter-drill anchor (per wire-in-anchor rule)

**Location:** new test file `quality/tests/test_chatter_wire_in.py`.

Behavioral anchor test that, when the tick-site call to `_detect_chatter` is deleted, MUST fail. Not a source grep — the test detaches the return value by monkey-patching `_detect_chatter` to always return `{"sentinel_entity"}`, then asserts the coordinator's `_chattering_entities` contains it after a tick. Second test deletes the surfacing branch: mutates `sensor.py:_unavailable_details` chatter branch (source mutation, not monkey-patch) and asserts `test_unavailable_entities_sensor_surfaces_chattering_sensor` fails, then restores. Per `feedback_mutation_verification_pycache_staleness.md`: disable bytecode + clear cache in the drill helper.

**REUSED:** the drill pattern from prior cycles' wire-in fixtures. Restore-and-status-check at end.

#### Acceptance Criteria — D4
- **Test:** `test_chatter_detector_wired_to_tick`, `test_chatter_surfacing_wired_to_unavailable_sensor`.
- **Verify (mutation):** running the drill script (D4 helper) reports `2 failed` on mutation, `0 failed` on restore.

---

## 4. Numbers on the knob ladder

Per "Numbers Get Knobs": every threshold names a rung + why. All rung 1 (module constants, `const.py`) — chatter sensitivity is a detection-quality knob (like `STUCK_D2_MIN_MOTION_TRANSITIONS`), changes should require code review.

| Constant | Value | Rung | Why not higher |
|---|---|---|---|
| `CHATTER_WINDOW_MIN` | `60` | 1 (module constant) | Matches `DEFAULT_STUCK_SENSOR_DUTYCYCLE_WINDOW_MIN`; same time-domain reasoning; changing it re-derives corroboration semantics. |
| `CHATTER_MIN_TRANSITIONS_PER_MIN` | `2.0` | 1 | Garage B measured ~5.2/min uncorroborated; a legitimately busy PIR in a well-corroborated room can exceed 2/min but WILL be corroborated → detector still returns `∅`. A drift-tuning knob for the operator would invite silent detection erosion. |
| `CHATTER_MIN_TICKS` | `20` | 1 | Same warm-up floor as D2 (`DEFAULT_STUCK_SENSOR_DUTYCYCLE_MIN_TICKS`); shared reason (below-floor false-positives on cold boots). |
| `CHATTER_RECOVERY_QUIET_WINDOW_MIN` | `60` | 1 | Full window of below-threshold behavior before firing `fire_stuck_signal_recovered` — symmetric with detection window; prevents flap-noise recoveries. |
| `CHATTER_DETECTOR_ENABLED` | `True` | 1 (module constant, kill switch) | Sibling of `STUCK_EXCLUSION_ENABLED` (`const.py:3725`). Rung-1 hard-disable for the entire chatter path — detector, surfacing, NM emit — for emergency-off without a code change to detection logic. |
| `CONF_STUCK_SIGNAL_NM_ENABLED` | reused | 2 (options-flow) | Already silences ALL `stuck_signal` NM including new chatter kind; operator can silence a known-bad sensor while awaiting a physical replacement. |

**Kill-switch semantics (documented on `CHATTER_DETECTOR_ENABLED`):** `False` → `_detect_chatter` returns `set()` immediately, `_chattering_entities` stays empty, D3 surfaces nothing, D2 emits nothing. Byte-identical to pre-cycle behavior. No lingering state; no restart required.

---

## 5. Producer AND Consumer sections

### Producer check — `_chattering_entities`
- **Computed by:** `coordinator._detect_chatter` (D1), called once per coordinator tick from the existing call site at `coordinator.py:2544` (alongside D2).
- **Depends on:** rolling deque of state-change samples for each `motion ∪ mmwave ∪ occupancy` member; `self._d2_boot_settle_done()`; `CHATTER_*` module constants.
- **Health of dependencies:** boot-settle predicate already proven in D2 production; deque plumbing copied verbatim; corroborator resolution reuses the D3 SENSOR-CAPABILITY-1 lookup path (also proven).
- **Multiple derivations?** No. Single writer, single owner. Chatter is orthogonal to duty-cycle and continuous-on; a sensor can be flagged by two rules simultaneously (fires two NMs of different `kind`) — that is intentional and correct (different remedies).
- **Ground-truth check:** the incident-replay test (Garage B 24 h) IS the external ground truth; measured recorder data verified by the operator.

### Consumer + call-site check — `_chattering_entities` and `sensor.<room>_unavailable_entities`
- **`_chattering_entities`:** read by exactly one consumer — `UnavailableEntitiesSensor._unavailable_details` (D3). Display-only. NO trust-decision code reads it. (Explicitly non-goal: chatter does NOT trigger occupancy exclusion — see §6.)
- **`fire_stuck_signal(kind="chatter", ...)`:** dispatches through the existing NM path — NotificationManager → BlueBubbles/WhatsApp per NM Cycle A routing. `anomaly_log` gets one row per (entity, day) via `_write_stuck_anomaly`.
- **`sensor.<room>_unavailable_entities`:** consumers are Lovelace cards, PWA dashboard, and operator queries. Zero automation logic reads it. Schema change (adding `reason="chattering"` rows) is purely additive — existing consumers filtering on `details[*].category == "actuator"` are unaffected.

---

## 6. Non-goals (explicit)

1. **Chatter does NOT exclude the sensor from occupancy.** Only P22 continuous-on does that (`STUCK_EXCLUSION_ENABLED`). Rationale: chatter without any independent corroboration might still be a real hyper-sensitive sensor in a busy room; excluding would risk false-vacancy comfort/light regressions. Notify-only is the correct blast radius for this cycle.
2. **No new DB table.** `anomaly_log` via `_write_stuck_anomaly` is enough. `sensor_health` table not built. Trigger to revisit: a consumer wants a time-series of flap rate per entity.
3. **No `ura_unhealthy_sensors` house-level sensor.** Room-level `sensor.<room>_unavailable_entities` already exists and is the correct surfacing point (chattering is a per-room-input concept). A house-level aggregator can be added later as a template if operator asks.
4. **Not the signal_trust_ledger migration.** Per `INCIDENT_chatter_class_missed_by_watchdog_2026-08-09.md` §4: chatter must ship CONCRETELY here first (this cycle) to satisfy the ledger's "Extraction, not invention" rule. Migration into M5 is deferred to whatever cycle revives the ledger plan.
5. **Not adding chatter detection to actuators.** D2.11 flap quarantine already handles that path with different semantics (availability transitions, not state oscillation). No cross-wiring.
6. **No config-flow field.** Detection sensitivity intentionally stays rung 1. If an operator asks for per-room tuning, that becomes a separate MARGINAL-BENEFIT decomposition cycle.

---

## 7. Files changed

| File | Change | Lines (est.) |
|---|---|---|
| `custom_components/universal_room_automation/const.py` | Add `CHATTER_*` constants + append `chatter` to sub-classification comment | +25 |
| `custom_components/universal_room_automation/coordinator.py` | New `_detect_chatter` method + init `_chattering_entities: set` in `__init__` + tick-site call + recovery-tracking | +90 |
| `custom_components/universal_room_automation/sensor.py` | Extend `_unavailable_details` with chattering-sensor branch (mirror flapping-actuator branch) | +25 |
| `quality/tests/test_chatter_detector.py` (new) | D1 + D2 unit tests including incident replay fixture | +200 |
| `quality/tests/test_unavailable_entities_chatter.py` (new) | D3 surfacing tests | +80 |
| `quality/tests/test_chatter_wire_in.py` (new) | D4 wire-in + mutation drill | +100 |

**No changes to:** `config_flow.py`, `options_flow.py`, `database.py`, `notification_manager.py`, `occupancy_substrate.py`, `_stuck_signal_nm.py` (uses existing public API only).

---

## 8. Review protocol

**Tier 2** — two framing-disjoint reviews before deploy + live validation after.
- **Review A (correctness + edge cases):** the `_detect_chatter` math; corroboration semantics (own-transitions excluded; PIR eligible as candidate); boot-settle gate; warm-up floor; kill-switch byte-identity; discriminator tests actually discriminate.
- **Review B (async + lifecycle + cross-surface):** tick-site placement, `_chattering_entities` lifetime across reload/restart, NM latch behavior across day-rollover in a real time-zone, `UnavailableEntitiesSensor` attribute schema not breaking existing dashboard consumers, no untracked background tasks, `fire_stuck_signal_recovered` discharge actually clears latch.
- **Live (Review C, post-deploy):** validate against a room known to have a chattering sensor (Garage B ratgdo if still present) OR inject a synthetic chatterer for 90 min; observe NM emit, DB row, sensor attribute — write results into the version README's `Validated <date>` table.

**Plan-review requirement (Tier 2):** ONE adversarial plan review before build dispatch — verify this section 1.1 ledger by independent grep, verify §2's invariant is falsifiable, verify §5 consumer enumeration is exhaustive.

---

## 9. Risk register (short)

| Risk | Likelihood | Mitigation |
|---|---|---|
| Chatter false-positive on a legitimately busy hallway PIR w/o corroboration | Low | The room's OTHER PIR/mmwave/occupancy sensors WILL corroborate in a real busy hallway; a truly isolated chatterer IS the failure we want flagged. |
| Restart re-hydration burst triggers chatter across many rooms | Medium if unguarded | Reuse `_d2_boot_settle_done()` gate + `CHATTER_MIN_TICKS` warm-up floor — same defenses D2 uses in production today. |
| NM storm on first deploy (backlog of chattering sensors surfaces) | Low | Per-day latch already caps at ≤1/entity/day; NM Cycle A digest already coalesces. |
| Dashboard consumer breaks on new `reason="chattering"` rows | Very low | Additive schema; existing consumers filter by `category` (actuator vs sensor) or ignore unknown reasons. |
| Detection erosion via silent knob drift | Removed by design | All knobs at rung 1 — cannot drift without a reviewed code change. |
