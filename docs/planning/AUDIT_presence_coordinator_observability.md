# AUDIT — Presence Coordinator: General + Observability

**Date:** 2026-08-05
**Author:** planner (ura-planner)
**Type:** Audit + recommendations (no version — per URA versioning convention)
**Requested by:** operator 2026-08-05 — *"Audit presence coordinator in general and also for observability. Make recommendations for more observability sensors and toggles for key features on the coordinator ha device surface. Make sure we use the same hygiene we have refined in HC and EC."*

Scope: read-only. No code changes. Downstream product is a Tier-2 cycle scoping (§E) — that build will go through the standard tier gate.

---

## 0. Institutional context verified

**Files read end-to-end (or in load-bearing sections):**
- `custom_components/universal_room_automation/domain_coordinators/presence.py` — 6,935 LOC; function/class map extracted via structural grep; `__init__` (1274-1553), `_run_inference` entry (4799-4900), guest-gate machinery (4467-4770), teardown (6595-6700), `_arriving_rearm_bypass` (4772-4797), optimizer-intent handshake (6710-6817).
- `custom_components/universal_room_automation/sensor.py` — PC device entities at 4522-5150 and census entities at 3368-3700.
- `custom_components/universal_room_automation/binary_sensor.py` — PC device entities at 1783-1905 and census/guest-mode entities.
- `custom_components/universal_room_automation/switch.py` — `PresenceObservationModeSwitch` (2678-2770), `FanRecheckEnabledSwitch` (~4362-4530), `HVACFanControlSwitch` (3245-3400) as hygiene reference, `HVACGuestModeActuationSwitch` (1482-1610), `HVACObservationModeSwitch` (2226-2350), NM suppression-switch `_suppressed_since` pattern (3435-3660).
- `custom_components/universal_room_automation/number.py` — `FanInterferenceHoldNumber` (2711-2820), CM presence-timer cluster (59-95, 399, 662).
- `custom_components/universal_room_automation/select.py` — `PresenceHouseStateOverrideSelect` (214-233).
- `docs/Coordinator/PRESENCE_COORDINATOR.md` — occupancy substrate addendum + design table of contents.

**Prior planning docs consulted (filenames + relevance):**
- `docs/planning/PLANNING_presence_guest_latch_and_veto_gap.md` — guest latch shipped v5.16.0.
- `docs/planning/AUDIT_presence_provenance.md` + `INVESTIGATION_presence_provenance_audit_and_fan_noise.md` + `PLANNING_presence_provenance_split_and_fan_diagnostic.md` — prior provenance-audit template + fan-interference diagnostics precedent.
- `docs/planning/RESEARCH_2026-06-03_presence_sensor_fusion_noise_prone_environments.md` — sensor-fusion prior.
- `docs/planning/PLANNING_v4.7.13_sleep_state_zone_presence_trust.md` — trust-hierarchy scaffolding referenced throughout `presence.py`.
- `docs/planning/PLANNING_v4.7.x_guest_mode_actuation_phase1.md` + `PLANNING_v5.7.0_guest_mode_detection_and_actuation.md` + `PLANNING_v4.6.2.2_guest_mode_hardening.md` — guest actuation family (kill-switch precedent on HVAC side).
- `docs/planning/PLANNING_hvac_presence_timer_knobs_and_options_writeback_retrofit.md` — Numbers-Get-Knobs placement precedent for presence-timer cluster.

**Memory bodies pulled:**
- `project_presence_guest_latch_and_veto_gap.md` (SHIPPED v5.16.0), `project_guest_mode_false_positive_backlog.md` (lost-but-away exclusion path — LIVE evidence today), `project_zone_away_when_occupied_home_night_gap.md` (mmWave-drop retreat gap).

**Live evidence 2026-08-05:** `sensor.ura_presence_house_state` today passed through `guest`; both adults `tracking_status=lost` in the exclusion path. Payload today: `veto_path`, `excluded_persons`, `lost_away_persons`, `lost_away_grace_remaining_s`, `signal_consensus_inputs`, `boot_settle_*`, `arriving_rearm_*`, `fan_interference_*`, per-zone breakdown with tier1 provenance — ALL as attributes on the single house-state sensor.

**Hygiene-bar sources (HC/EC/NM) — patterns extracted:**
- HVAC device: 17 switches, 18 numbers, 4 sensors, 5 binary sensors, 4 buttons (identifiers count grep — `switch.py:17`, `number.py:18`, etc.). Every major HVAC feature has a live kill switch (`HVACFanControlSwitch`, `HVACGuestModeActuationSwitch`, `HVACACRampMasterSwitch`, `HVACACResetSwitch`, `HVACACNudgeSwitch`, `HVACOverrideArresterSwitch`, `HVACPreConditioningSwitch`, `HVACObservationModeSwitch`).
- **Kill-switch discipline pattern (v4.7.3.1 / v5.48.0):** `SwitchEntity, RestoreEntity`; restore is DEFERRED via `SIGNAL_HVAC_COORDINATOR_READY` when coord is not yet ready (switch.py:1552-1610 for `HVACGuestModeActuationSwitch`, replicated across 7+ HVAC switches). Restore-on-"on"-only for pause/suppress variants; `suppressed_since` attr surfaced for provenance (switch.py:3435-3660 NM pattern).
- **Numbers-Get-Knobs ladder** codified in CLAUDE.md: module const (review-gated) / config-flow (per-deploy structure) / live Number/Select/Switch (dashboard-tuned). Applied here.
- **Provenance attrs on suppression switches:** `suppressed_since` ISO timestamp + earliest-wins merge with coordinator's own `_suppressed_since` (switch.py:3516-3530).

**Presence-device-attached entities today (exhaustive):**
| Entity | Type | File:line | Exposes |
|---|---|---|---|
| `sensor.ura_presence_house_state` | sensor | sensor.py:4522 | House state string + **giant** attrs payload (30+ fields, see §B) |
| `sensor.ura_house_state_confidence` | sensor | sensor.py:4738 | Engine confidence 0..1 |
| `sensor.ura_signal_consensus_confidence` | sensor | sensor.py:4829 | Signal-consensus float + input dict |
| `sensor.ura_presence_anomaly` | sensor | sensor.py:~4900 | Anomaly count/last |
| `sensor.ura_presence_compliance` | sensor | sensor.py:~4980 | Compliance % |
| `sensor.ura_presence_next_state` | sensor | sensor.py:5074 | Routine forecaster prediction |
| `binary_sensor.ura_house_occupied` | binary_sensor | binary_sensor.py:1807 | House != AWAY/GUEST |
| `binary_sensor.ura_house_sleeping` | binary_sensor | binary_sensor.py:1847 | House == SLEEP |
| `binary_sensor.ura_guest_mode` | binary_sensor | binary_sensor.py:1885 | House == GUEST |
| `switch.ura_presence_observation_mode` | switch | switch.py:2678 | Suppress dispatch of `SIGNAL_HOUSE_STATE_CHANGED` + `SIGNAL_PERSON_ARRIVING` (deferred restore already implemented via 5s call_later — NOT via signal-ready pattern) |
| `switch.ura_fan_recheck_enabled` | switch | switch.py:4362 | Fan-noise recheck manager on/off |
| `number.ura_fan_interference_hold_s` | number | number.py:2711 | Layer-1 gate hold duration (60..1800s) |
| `select.ura_presence_house_state_override` | select | select.py:214 | Manual state override |

**Total: 13 entities on the `presence_coordinator` device.** For comparison the HVAC device carries ~48 entities across the same platforms — a **~3.7x gap** in operator surface. This is the audit's headline number.

---

## A. General audit of `presence.py` — structure + feature inventory

### A.1 Structural shape
- **Single file, 6,935 LOC.** Contains: `_tracking_active_or_lost_away` module helper (168), `ReliableSignal`/`TransientSignal`/`VetoDecision` dataclasses (194-242), `ZonePresenceMode` const-holder (244), `_classify_entity_kind` classifier (284), `_audit_provenance_invariants` (354), `ZonePresenceTracker` (459-912), `StateInferenceEngine` (914-1259), `PresenceCoordinator` (1260-6935).
- **PC `__init__` is ~280 LOC of state declaration** (1274-1553): 50+ instance attributes. High cognitive load but not a bug — each attr has a documented reason. `PRESENCE_METRICS` (1268) + `PRESENCE_SUPPRESSED_FROM_PERSISTENCE` (99-118) is the right anomaly-registry pattern.
- **`_run_inference` (4799 → ~6350)** is the hot path — ~1500 LOC. Contains the boot-settle gate, snapshot refresh, veto helper, WAKING sustained-signal gate, guest-gate composition, ARRIVING re-arm cooldown application, transition emit. This is the single riskiest function in URA outside of Energy's optimizer — long, deeply nested, and load-bearing for every downstream coordinator. **Flag only — not this cycle's scope.**

### A.2 Feature inventory (with load-bearing state)
| Feature | Load-bearing state | Live kill switch? | Live counters? |
|---|---|---|---|
| House-state inference | `_inference_engine`, `HouseStateMachine` | Override (select) — not a kill switch | via anomaly sensor |
| Zone presence tracking (Tier1/2/3) | `_zone_trackers`, `ZonePresenceTracker._room_provenance` | **NO** | attr-only |
| Occupancy substrate | `_substrate`, `SIGNAL_SUBSTRATE_KIND_CHANGED` | **NO** | attr-only |
| Boot-settle gate | `_boot_settle_done`, `_boot_settle_presence_suppressed`, `_boot_settle_release_reason` | Not a kill switch (safety-critical) | attr-only |
| Cold-start ARRIVING re-arm cooldown (B-2026-08-03-2, 900s const) | `_arriving_rearm_until`, `_arriving_rearm_suppressed`, `_arriving_rearm_bypassed`, `_arriving_last_was_outdoor_only` | **NO** — kill via module const only (0 disables) | attr-only |
| Guest detection (Path A — camera census + persistence) | `_unidentified_first_seen`, `_guest_persistence_seconds`, `_guest_require_confidence`, `_census_confidence` | **NO** (HVAC has its own actuation switch — presence still fires the signal) | attr-only |
| Guest room sustained-occupancy (Path B — D5) | `_guest_room_state`, per-room `first_seen` | **NO** | attr-only |
| Person-tracker AWAY veto (v4.7.14) | `_tracked_persons_count_trusted`, `_excluded_persons`, `_all_tracked_persons_away`, `_veto_path`, `_last_veto_decision` | **NO** | `wake_blocked_ticks`, `last_veto_decision` (attr) |
| Lost/away exclusion (v5.7.0 WS-A1..A4) | `_lost_away_persons`, `_lost_away_grace_remaining_s`, `_indoor_clear_consecutive_ticks`, `_external_empty_consecutive_ticks`, `_outdoor_zones` | **NO** — high false-positive history | attr-only |
| Signal consensus (v4.7.15 D5) | `_signal_consensus`, `_signal_consensus_inputs`, `_consensus_low_since` | **NO** | dedicated confidence sensor exists |
| WAKING sustained-signal gate (v4.7.15 D3) | `_first_positive_zone_occupied_since`, `_wake_blocked_ticks` | **NO** | attr-only |
| Wake-backstop safety valve (v4.7.18.1 D2) | `_wake_backstop_fires`, `_WAKE_BACKSTOP_HOURS_AFTER_SLEEP_END` (module const) | **NO** — safety-critical, correct to not expose | `_wake_backstop_fires` (attr) |
| Fan-interference gating (Layer 1/2/Recheck) | `_fan_interference_hold_s`, `_fan_interference_gated_prev`, `_fan_recheck_manager`, `_mmwave_fan_demoted_snapshot` | Partial — `switch.ura_fan_recheck_enabled` covers Mode-2 only, NOT Layer-1 | attr-only + per-room hold expiry attr |
| Face-confirmed arrival | `_face_arrival_cooldown`, `_face_recognition_enabled` | **NO** (`_face_recognition_enabled` is init-time only, no switch) | attr-only |
| Routine-Awareness Next-State Forecaster | `_routine_forecaster` | **NO** | `sensor.ura_presence_next_state` exists |
| Optimizer-intent handshake (Pillar A) | `_optimizer_intent_unsub`, `_last_veto_reason` | **NO** — observation_mode blankets all | attr-only (via NM/optimizer logs) |
| Observation mode | `observation_mode` bool | **YES** — `switch.ura_presence_observation_mode` | none |

### A.3 Correctness/complexity concerns (flag only — not this cycle's scope)
1. **`switch.ura_presence_observation_mode` does not use the v5.48.0 signal-ready deferred-restore pattern.** It uses a 5s `async_call_later` re-check (switch.py:2743-2762). Compare to `HVACGuestModeActuationSwitch` (1552-1610) subscribing to `SIGNAL_HVAC_COORDINATOR_READY`. There is no `SIGNAL_PRESENCE_COORDINATOR_READY` today. Restore may race on slow boots.
2. **The house-state sensor's attrs payload is very large** (~30 fields plus nested per-zone dict, veto_decision dict, signal_consensus_inputs dict). Recorder writes the ENTIRE attributes dict on every state change AND at recorder cadence for stat_changes. This is a known bloat pattern and blocks history-graph plotting of individual fields (attrs are not history-graphable in Lovelace natively; you have to build a template sensor per attribute).
3. **Cold-boot arriving-rearm cooldown kill-switch is a module-constant zero-value** (`ARRIVING_REARM_COOLDOWN_S = 900` at 165). Per Numbers-Get-Knobs this is defensibly Rung-1 (safety-adjacent, review-gated); however the operator's dashboard has no visibility that the cooldown fired other than reading the attr counters — no "arriving-rearm active until X" sensor.
4. **`_handle_occupancy_change` (4174) linearly scans `_zone_trackers` to find the room's tracker.** The `_room_to_zone` cache exists (1419) but this callback bypasses it. Minor perf, not blocking.
5. **`_is_known_person_in_room` (4617) reads `person_coord._tracked_persons` via getattr with silent fallback to False.** Under the today-live "both adults lost" state this returns False for a legitimately-present tracked person whose phone dropped BLE, which is the exact mechanism that promotes an unknown occupant to Path-B GUEST. Known bug (memory: `project_guest_mode_false_positive_backlog`), tracked but not audit-scope.

---

## B. Observability gaps

### B.1 The giant-attributes anti-pattern
`sensor.ura_presence_house_state` today carries as attributes (sensor.py:4562-4732):

`confidence, census_count, tracked_persons_count, tracked_persons_count_trusted, excluded_persons, all_tracked_persons_away, veto_path, lost_away_persons, lost_away_grace_remaining_s, outdoor_zones, signal_consensus, signal_consensus_inputs (nested dict), consensus_low_since, last_veto_decision (nested dict), wake_blocked_ticks, arriving_rearm_suppressed, arriving_rearm_bypassed, arriving_rearm_active, wake_backstop_fires, boot_settle_done, boot_settle_release_reason, boot_settle_presence_suppressed, boot_settle_hvac_suppressed, per-zone dict (with fan_interference_rooms nested), fan_interference_active`.

**Consequences:**
- Recorder writes the full dict on every house-state change (~10-50/day) AND on every attr change (silent — the entity's `state` didn't change but attrs did → still a recorder write on many HA versions).
- Lovelace history-graph cards cannot plot any of these fields directly. Every dashboard chart requires a template sensor.
- Diff-ing why the house is in state X requires reading the attrs dump — no per-signal history.

### B.2 Attribute-only / log-only / dark signals that deserve promotion

**HIGH-VALUE signals currently attribute-only (should be dedicated sensors so recorder plots them):**
1. `census_count` (attr) — a graphable integer that drives half of inference. Suppressed from anomaly persistence but not from observability — the raw value should be a sensor.
2. `signal_consensus` (0..1 float) — already has a dedicated sensor (`sensor.ura_signal_consensus_confidence`). GOOD — this is the model to replicate.
3. `wake_blocked_ticks` (monotonic counter) — invaluable for diagnosing "why is the house still SLEEP at 10am." Currently attribute-only.
4. `arriving_rearm_suppressed` / `arriving_rearm_bypassed` (monotonic counters) — flap detector KPI (the 2026-08-03 patio-flap incident that motivated the cooldown). Attribute-only.
5. `boot_settle_presence_suppressed` / `boot_settle_hvac_suppressed` (monotonic counters) — how many downstream fanouts the settle gate saved. Attribute-only.
6. `wake_backstop_fires` (monotonic counter) — must-never-fire-in-normal-operation safety valve. Attribute-only. **A HIGH firing rate is a sev-2 signal that some other gate broke** — this belongs on the dashboard AND on NM alerts.
7. Per-zone `_v4716_zone_verdicts` (weighted-veto verdicts, presence.py:1383) — computed each cycle, never surfaced anywhere. **Fully dark today** (attribute would only appear inside the per-zone dict on the house-state sensor and only if a zone tracker is present).

**LOG-only signals worth counters at minimum:**
8. Guest-gate arm/disarm transitions (INFO logs at 4717, 4728, 4691) — no counter. Cannot answer "how often did guest gate arm today."
9. Guest-room Path B `first_seen` arm (INFO log at 4608) — no counter. Same problem.
10. Optimizer-intent VETO fires (INFO log at 6748) — a "presence-vetoed intents today" counter is trivial and useful.
11. Face-confirmed arrivals per zone (`_face_arrivals_today` per tracker exists at 6437 but is not exposed anywhere).
12. Provenance-invariant audit results (`_audit_provenance_invariants` at 354) — return value discarded at every caller unless failure. No sensor of "audit_violations_today."

**FULLY DARK (computed but never persisted or surfaced):**
13. `_indoor_clear_consecutive_ticks` / `_external_empty_consecutive_ticks` (WS-A4 debounce counters) — pure in-memory.
14. `_arriving_last_was_outdoor_only` — pure in-memory bool that gates the cooldown ARMing decision. When the cooldown suppresses an ARRIVING attempt the operator has NO way to know whether it was armed by an outdoor-only ARRIVING (correct) or a false arming.

### B.3 Recommendation on the giant-attrs sensor
- **Split, don't grow.** Every field in §B.1 that a dashboard would plot becomes its own sensor with a small (<5 field) attrs dict of provenance.
- **Trim** `signal_consensus_inputs` and `last_veto_decision` from the house-state sensor's attrs (or clip to top-N keys). Move the full dict onto a dedicated diagnostic sensor with `entity_category=DIAGNOSTIC` and disabled by default.
- **Preserve** `boot_settle_done`, `boot_settle_release_reason`, `arriving_rearm_active`, `fan_interference_active` on the house-state sensor — these are read-at-a-glance and appropriate as attrs.

---

## C. Toggle gaps — features without a live kill switch

Compare hygiene bar: HVAC has 17 switches — one per major feature. Presence has 2 switches (`observation_mode`, `fan_recheck_enabled`). Missing kill switches by feature:

| Feature | Recommended switch (name / default) | Restore semantics | Provenance attr |
|---|---|---|---|
| Guest detection Path A (census-driven) | `switch.ura_presence_guest_detection_enabled` / **default ON** | v5.48.0 signal-ready deferred restore via a NEW `SIGNAL_PRESENCE_COORDINATOR_READY`; restore-on-either-value | `suppressed_since` ISO |
| Guest detection Path B (D5 sustained-room) | `switch.ura_presence_guest_room_detection_enabled` / **default ON** | same | `suppressed_since` |
| Arriving re-arm cooldown | `switch.ura_presence_arriving_rearm_enabled` / **default ON** (kills the cooldown = pre-fix behavior — matches the module-const kill of `ARRIVING_REARM_COOLDOWN_S=0`) | same | `suppressed_since` + `suppressed_bypass_count` |
| Person-tracker AWAY veto (v4.7.14 shared helper) | `switch.ura_presence_away_veto_enabled` / **default ON** | same | `suppressed_since` |
| WAKING sustained-signal gate | `switch.ura_presence_waking_gate_enabled` / **default ON** | same | `suppressed_since` |
| Fan-interference Layer-1 gate | `switch.ura_presence_fan_interference_gate_enabled` / **default ON** (complements the existing Number for hold_s and the existing Mode-2 recheck switch) | same | `suppressed_since` |
| Face-confirmed arrival | `switch.ura_presence_face_arrival_enabled` / **default OFF** (currently init-time only bool) | same | none needed (state=off = suppressed) |
| Signal-consensus veto arming | `switch.ura_presence_signal_consensus_enabled` / **default ON** | same | `suppressed_since` |
| Routine forecaster | `switch.ura_presence_routine_forecaster_enabled` / **default ON** (advisory-only today; killing it hides `sensor.ura_presence_next_state` freshness) | same | `suppressed_since` |

**Do NOT propose switches for:**
- Boot-settle gate — safety-critical, no operator use case.
- Wake-backstop — safety valve.
- Occupancy substrate — foundational; killing it breaks Tier-1.
- Lost/away exclusion — high false-positive history is a REASON to expose visibility, not a REASON to expose a kill (killing it re-opens the wider FP class).

---

## D. Recommendations table

Priority: **P1** = must (closes a diagnostic blind spot or a hygiene-parity gap with HC/EC); **P2** = nice (extends observability); **P3** = defer (operator may prune).

**Rung notation** per Numbers-Get-Knobs: MOD=module const, CFG=options flow, LIVE=live entity.

| # | Entity | Kind | REUSED / NEW | Rung | Why (1 line) | Priority |
|---|---|---|---|---|---|---|
| 1 | `sensor.ura_presence_census_count` | sensor | NEW (attr exists at sensor.py:4566) | n/a | Graph-able integer that drives half of inference; today attrs-only | **P1** |
| 2 | `sensor.ura_presence_wake_blocked_ticks` | sensor (state_class=total_increasing) | NEW (attr exists at sensor.py:4644) | n/a | Monotonic counter; diagnostic-primary for "why still SLEEP at 10am" | **P1** |
| 3 | `sensor.ura_presence_wake_backstop_fires` | sensor (total_increasing) + NM anomaly | NEW (attr exists at sensor.py:4658) | n/a | Safety valve; every fire is a sev-2 upstream regression flag | **P1** |
| 4 | `sensor.ura_presence_arriving_rearm_suppressed` | sensor (total_increasing) | NEW (attr exists at sensor.py:4648) | n/a | Flap-detector KPI (patio-flap incident 2026-08-03) | **P1** |
| 5 | `sensor.ura_presence_arriving_rearm_bypassed` | sensor (total_increasing) | NEW (attr exists at sensor.py:4651) | n/a | Sibling to #4; ratio bypassed/suppressed reveals cooldown correctness | **P1** |
| 6 | `binary_sensor.ura_presence_arriving_rearm_active` | binary_sensor | NEW (attr exists at sensor.py:4654) | n/a | Immediate "is a cooldown suppressing us right now" — dashboard tile | **P1** |
| 7 | `sensor.ura_presence_boot_settle_release_reason` | sensor (state = reason string) | NEW (attr exists at sensor.py:4672) | n/a | Post-restart diagnosis without log scrape | **P2** |
| 8 | `switch.ura_presence_guest_detection_enabled` | switch (RestoreEntity, signal-deferred) | NEW; mirrors `HVACGuestModeActuationSwitch` (switch.py:1482-1610) | LIVE | Guest detection has known FP history; parity with HC's guest actuation switch | **P1** |
| 9 | `switch.ura_presence_arriving_rearm_enabled` | switch | NEW; mirrors `HVACFanControlSwitch` (switch.py:3245) suppressed_since idiom | LIVE | Live kill for the 900s cooldown w/o code change; complements MOD-const zero | **P1** |
| 10 | `switch.ura_presence_away_veto_enabled` | switch | NEW; same pattern as #8 | LIVE | v4.7.14 shared veto is powerful; needs an audit-time kill for A/B | **P1** |
| 11 | `switch.ura_presence_fan_interference_gate_enabled` | switch | NEW; complements existing Number + `switch.ura_fan_recheck_enabled` | LIVE | Layer-1 gate today has no kill; only its knob (`hold_s`) and Mode-2 kill | **P2** |
| 12 | `switch.ura_presence_waking_gate_enabled` | switch | NEW | LIVE | Sustained-signal gate has a rare-fire failure mode; audit-time kill | **P2** |
| 13 | `switch.ura_presence_face_arrival_enabled` | switch (default OFF) | NEW; replaces init-time-only `_face_recognition_enabled` bool (presence.py:1502) | LIVE | Feature is currently dark-toggled; expose it | **P3** |
| 14 | `switch.ura_presence_routine_forecaster_enabled` | switch (default ON) | NEW | LIVE | Kills timer + subscription; matches `_routine_forecaster` teardown path (6684-6692) | **P3** |
| 15 | `sensor.ura_presence_veto_diagnostic` (disabled by default, `entity_category=DIAGNOSTIC`) | sensor + rich attrs | NEW — RECEIVER for the trimmed payload | n/a | Split `last_veto_decision`, `signal_consensus_inputs`, `excluded_persons` OFF the house-state sensor; recorder-bloat mitigation | **P1** |
| 16 | `sensor.ura_presence_guest_arm_count_today` | sensor (total, resets midnight) | NEW; hook the INFO log site at 4717 | n/a | Counter — no way today to answer "how often did guest gate arm today" | **P2** |
| 17 | `sensor.ura_presence_optimizer_vetoes_today` | sensor (total, resets midnight) | NEW; hook `_on_optimizer_intent` VETO branch (6739) | n/a | Fills Pillar-A observability gap | **P2** |
| 18 | `SIGNAL_PRESENCE_COORDINATOR_READY` | signal + a `_ready_event.set()` site symmetric to HVAC's | NEW — enables #8-#14 restore pattern | n/a | Infra prerequisite for signal-deferred restore switches | **P1** |
| 19 | `number.ura_presence_arriving_rearm_cooldown_s` | number (0=disabled..3600, default 900) | NEW — promotes `ARRIVING_REARM_COOLDOWN_S` from MOD-const to LIVE | LIVE | Operator legitimately tunes this by observation (Numbers-Get-Knobs) — flap incident showed one-size doesn't fit | **P2 (with pushback — see rejected §D.2)** |
| 20 | `number.ura_presence_guest_persistence_s` | number (0..3600, default 300) | REUSED as CONF today via `guest_persistence_seconds` init arg (presence.py:1279); promote to LIVE | LIVE | Operator tunes by FP incidents | **P3** |
| 21 | `number.ura_presence_guest_require_confidence` | select (none/low/medium/high) | REUSED as CONF today (presence.py:1280); promote to LIVE | LIVE | Same rationale as #20 | **P3** |
| 22 | `sensor.ura_presence_lost_away_persons_count` | sensor | NEW (list exists at sensor.py:4608) | n/a | Count is graphable; the list stays as attr | **P2** |
| 23 | `button.ura_presence_reset_arriving_rearm` | button | NEW | n/a | Immediate operator "clear the cooldown now" during an incident | **P3** |

### D.2 Considered and REJECTED

- **Kill switch for boot-settle gate** — REJECTED. Safety-critical, no operator use case. Toggling it during a boot storm would defeat exactly the mitigation it exists to provide.
- **Kill switch for lost/away exclusion path** — REJECTED. High false-positive history is a REASON to expose visibility (see #22), not to expose a kill (killing re-opens the wider FP class the WS-A1..A4 machinery closed). If a bug lands here, disable via observation_mode (already a switch) or the guest-detection switch (#8), both of which are proximate.
- **Number entity for `_WAKE_BACKSTOP_HOURS_AFTER_SLEEP_END`** — REJECTED. Per Numbers-Get-Knobs this is a safety bound that SHOULD require review to change. Keep MOD-const.
- **Number entity for `_NONSLEEP_QUIET_THRESHOLD_SECONDS` / `_WAKING_SUSTAINED_THRESHOLD_SECONDS`** — REJECTED. Fitted/tuned thresholds where operator drift would degrade the underlying trust hierarchy. Keep MOD-const.
- **Individual sensors for `_indoor_clear_consecutive_ticks` / `_external_empty_consecutive_ticks`** — REJECTED (parsimony). These are ephemeral debounce counters — reset to 0 constantly. Keep them on the diagnostic sensor (#15).
- **Per-zone verdict sensors (`_v4716_zone_verdicts`)** — REJECTED as sensors (parsimony); accepted as attrs on the diagnostic sensor #15 or on the existing per-zone binary_sensors.
- **Marginal-benefit pushback on #19 (`arriving_rearm_cooldown_s` as LIVE number)**: the MOD-const with kill-at-zero already covers the operator's practical need (turn it off if it misbehaves). Live tuning to non-default non-zero values is a small margin over "leave 900s / turn off" — worth having only if the flap-detector counters (#4/#5) actually show operator wants to nudge. **Recommend P2 with a "revisit if #4/#5 counters show >5 legitimate suppressions/week for 2 weeks."**

---

## E. Proposed Tier-2 build cycle

**Ships:** the P1 set (rows 1-6, 8-10, 15, 18 = 10 items; row 18 is prerequisite infra).

**Scope:**
- New signal `SIGNAL_PRESENCE_COORDINATOR_READY` (dispatched at end of `PresenceCoordinator.async_setup`, symmetric to `SIGNAL_HVAC_COORDINATOR_READY`).
- 4 promoted sensors (#1, #2, #3, #4 + #5) + 1 binary_sensor (#6) — pure attr-to-sensor promotion; no PC state changes required.
- 1 diagnostic-only receiver sensor (#15) + attr trim on the house-state sensor.
- 3 new kill-switches (#8, #9, #10) all using the v5.48.0 pattern (RestoreEntity + SIGNAL_PRESENCE_COORDINATOR_READY deferred restore + `suppressed_since` attr).
- 3 PC state flags: `_guest_detection_enabled`, `_arriving_rearm_enabled`, `_away_veto_enabled` — each gated at its use site with a suppressed_since counter increment when suppressed.

**Non-goals:** no changes to `_run_inference` logic beyond adding kill-switch guards; no changes to `_arriving_rearm_bypass`; no changes to `_guest_gate_armed`. All P2/P3 items land in follow-up cycles.

**Tier classification:** Tier 2-DB — this is regression-prone cross-coordinator work (presence ↔ HVAC guest actuation ↔ NM). Standard 3 framing-disjoint reviews + live validation.

**Acceptance criteria sketch:**
- **Verify:** post-restart `sensor.ura_presence_census_count` reads the same value as the `census_count` attr on `sensor.ura_presence_house_state`.
- **Verify:** `switch.ura_presence_guest_detection_enabled` OFF suppresses `HouseState.GUEST` transitions on a fixture where Path-A would fire; `attributes.suppressed_since` is populated ISO timestamp.
- **Verify:** `switch.ura_presence_arriving_rearm_enabled` OFF disables the cooldown (setting `ARRIVING_REARM_COOLDOWN_S=0` becomes redundant); flap-fixture ARRIVING→AWAY→ARRIVING succeeds.
- **Verify:** the diagnostic-only sensor #15 is `entity_category=DIAGNOSTIC`, `disabled_by_default=True`, and carries `last_veto_decision`, `signal_consensus_inputs`, `excluded_persons`, `_v4716_zone_verdicts` — while these disappear (or are clipped to 5-key stubs) from `sensor.ura_presence_house_state.attributes`.
- **Test:** `test_presence_kill_switches.py` covers each switch's OFF-suppresses-code-path AND ON-executes-code-path with mutation-anchored tests per Tier-3 discipline (each switch OFF must cause a specific test failure elsewhere).
- **Live (post-restart):** `sensor.ura_presence_wake_backstop_fires` = 0 within 30 min; toggling each new switch OFF and back ON is reflected in `_last_changed` + `suppressed_since` attr; house-state sensor attrs count drops from ~30 to ~10.
- **Live (24h):** dashboard cards for wake_blocked_ticks, arriving_rearm counters, and census_count plot correctly from recorder history.

---

## Summary

- **Current PC device surface:** 13 entities (6 sensors, 3 binary_sensors, 2 switches, 1 number, 1 select). HVAC device carries ~48 — **3.7x parity gap**.
- **Top 5 observability gaps:**
  1. `wake_backstop_fires` — safety-valve counter, attribute-only. HIGH firing rate is a silent sev-2 signal.
  2. `arriving_rearm_suppressed` / `arriving_rearm_bypassed` — flap-detector KPI (patio-flap incident), attribute-only.
  3. `wake_blocked_ticks` — primary diagnostic for "why still SLEEP", attribute-only.
  4. `census_count` — drives half of inference, graphable integer, attribute-only.
  5. `_v4716_zone_verdicts` (per-zone weighted-veto verdicts) — computed each cycle, **fully dark**.
- **Top toggle gaps** (no live kill switch today):
  - Guest detection Path A + Path B.
  - Arriving re-arm cooldown.
  - Person-tracker AWAY veto (v4.7.14 shared helper).
  - Fan-interference Layer-1 gate (Number for hold exists; kill does not).
- **P1 recommendation list:** #1 census_count sensor, #2 wake_blocked_ticks sensor, #3 wake_backstop_fires sensor + NM anomaly, #4 arriving_rearm_suppressed sensor, #5 arriving_rearm_bypassed sensor, #6 arriving_rearm_active binary_sensor, #8 guest_detection_enabled switch, #9 arriving_rearm_enabled switch, #10 away_veto_enabled switch, #15 diagnostic receiver sensor (attr split from house-state sensor), #18 `SIGNAL_PRESENCE_COORDINATOR_READY` infra.
- **Additional hygiene items (bundle with P1):** convert `switch.ura_presence_observation_mode` restore path from 5s `async_call_later` to `SIGNAL_PRESENCE_COORDINATOR_READY` deferred pattern once the signal exists.

---

## Operator adjudication (2026-08-05 evening, verbatim intent)

1. **P1 set ACCEPTED** — proceed to build (Tier 2-DB).
2. **Naming must be user-friendly, not geek speak.** Friendly names read
   as plain English on the device page (e.g. "People Home (census)",
   "Mornings Blocked From Waking", "Guest Detection", "Arrival
   Re-Alerts"), entity_ids stay conventional/slug-stable.
3. **Additive only — do NOT remove/split attrs off the house-state
   sensor.** The diagnostic sensor (P1 #10) still ships, but as a COPY
   surface; existing attrs remain untouched (no consumer breakage, no
   dashboard churn). Recorder-bloat concern deferred until evidence.
4. **Wake counter scope:** ships wake-specific as designed. The general
   "stuck in any mode" need is adjudicated into the stuck-signal
   watchdog state-awareness backlog (B-2026-08-04-1): add
   transient-state max-dwell (arriving/waking/guest) fed by the
   house-state sensor's existing dwell_seconds.
