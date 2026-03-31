# URA Tech Debt & Hardening Plan — v3.20.x–v3.22.x

## Context

Review of the entire URA codebase (53 findings: 7 CRITICAL, 18 HIGH, 25 MEDIUM, 3 LOW) revealed
that the room-level automation core — the foundation of the system — has significant restart
resilience gaps, orphaned toggles, and flaky cover automation. Domain coordinators have signal
wiring gaps, dedup inconsistencies, and observability blind spots. 15 stub entities return
placeholder data.

This plan addresses all CRITICAL and HIGH findings, plus targeted MEDIUM fixes, across 6 cycles
ordered by dependency and user impact. Each cycle has testable acceptance criteria per the new
sprint contract process.

## Execution Strategy

- **Serialize within cycles** where risk warrants it (fix → review → test before next deliverable)
- **Parallelize across deliverables** within a cycle when they touch different files
- **Use worktree isolation** for Cycle A (high-risk coordinator.py/automation.py changes)
- **Review tier:** Cycles A and D are Feature-tier (2 reviews + live validation). Cycles B, C, E, F are Hotfix-tier (1 review).
- **Pre-review tagging** on every cycle: `git tag pre-review-v<version>`

## Signal Flow Reference

### SIGNAL_PERSON_ARRIVING — Current vs Planned

```
                    Presence Coordinator
                    ┌─────────────────┐
                    │  Geofence event  │
                    │  Camera face     │
                    └────────┬────────┘
                             │ dispatch: {person_entity, source}
                             ▼
              ┌──────────────────────────────┐
              │     SIGNAL_PERSON_ARRIVING    │
              └──────┬───┬───┬───┬───┬──────┘
                     │   │   │   │   │
            TODAY:   │   │   │   │   │  PLANNED (Cycle F):
                     │   │   │   │   │
                     ▼   │   │   │   │
                  ┌─────┐│   │   │   │
                  │HVAC ││   │   │   │
                  │Pre- ││   │   │   │
                  │cool ││   │   │   │
                  └─────┘│   │   │   │
                         ▼   │   │   │
                      ┌─────┐│   │   │
                      │Secur││   │   │  Suppress "unknown person" alert
                      │ity  ││   │   │  if person is registered
                      └─────┘│   │   │
                             ▼   │   │
                          ┌─────┐│   │
                          │Enrgy││   │  Could pre-condition energy
                          │     ││   │  (future — skip for now)
                          └─────┘│   │
                                 ▼   │
                              ┌─────┐│
                              │Music││  Start preferred music in
                              │Foll.││  arriving person's zone
                              └─────┘│
                                     ▼
                                  ┌─────┐
                                  │ NM  │  Log arrival event
                                  └─────┘
```

**What it does in simple terms:**
1. Person's phone crosses geofence → HA detects person coming home
2. OR: Frigate camera recognizes a face at the front door
3. Presence Coordinator fires `SIGNAL_PERSON_ARRIVING` with the person's entity ID and source
4. **Today:** Only HVAC reacts — it pre-cools/pre-heats the person's preferred zones
5. **Planned:** Security can suppress false alarms, Music Following can queue music

### SIGNAL_SAFETY_HAZARD — Currently Dead, Planned Wiring

```
                    Safety Coordinator
                    ┌──────────────────┐
                    │ Smoke detected   │
                    │ CO level high    │
                    │ Water leak       │
                    │ Freeze warning   │
                    └────────┬─────────┘
                             │ dispatch: SafetyHazard(type, severity, entity, value)
                             ▼
              ┌──────────────────────────────┐
              │     SIGNAL_SAFETY_HAZARD      │
              └──────┬───┬───┬───┬──────────┘
                     │   │   │   │
            TODAY:   │   │   │   │
            NOBODY!  │   │   │   │
                     │   │   │   │
            PLANNED (Cycle F):
                     │   │   │   │
                     ▼   │   │   │
                  ┌─────┐│   │   │
                  │HVAC ││   │   │  Smoke/CO: STOP fans (don't spread)
                  │     ││   │   │  Freeze: emergency heat
                  └─────┘│   │   │
                         ▼   │   │
                      ┌─────┐│   │
                      │Secur││   │  Smoke/fire: UNLOCK doors (egress)
                      │ity  ││   │
                      └─────┘│   │
                             ▼   │
                          ┌─────┐│
                          │Enrgy││  Any CRITICAL: shed discretionary loads
                          │     ││  Water leak: protect equipment
                          └─────┘│
                                 ▼
                              ┌─────┐
                              │Music│  Stop all playback on CRITICAL
                              └─────┘
```

---

## Cycle A: Room Resilience (v3.20.0) — SERIALIZE, WORKTREE

**Why first:** This is the foundation. Every other cycle builds on a stable room automation core.
**Risk:** HIGH — touches coordinator.py (32KB), automation.py (44KB), binary_sensor.py, database.py
**Review tier:** Feature (2 reviews + live validation)

### D1: Room State Persistence

Enhance `OccupiedBinarySensor` with `RestoreEntity` to persist critical coordinator state
across restarts. Add `room_state` DB table as backup.

**Files:** `binary_sensor.py`, `coordinator.py`, `database.py`

**Variables to persist (MUST):**
- `_became_occupied_time` — occupancy session start (loss = false timeout)
- `_last_occupied_state` — previous state (loss = spurious automations on restart)
- `_occupancy_first_detected` — debounce timer (loss = noise triggers occupancy)
- `_failsafe_fired` — prevents repeated failsafe (loss = double-fire)

**Variables to persist (NICE):**
- `_last_trigger_source` — occupancy trigger type
- `_last_lux_zone` — light level zone (loss = spurious lux trigger)
- `_last_timed_open_date` / `_last_timed_close_date` — cover daily dedup

**Pattern:** RestoreEntity on OccupiedBinarySensor with state in `extra_state_attributes`.
Coordinator reads restored state during first refresh (not __init__). DB table `room_state`
as fallback if state machine snapshot missing.

#### Acceptance Criteria
- **Verify:** After HA restart, `_became_occupied_time` is restored (not None) if room was occupied before restart
- **Verify:** After restart, room does NOT flash vacant→occupied (no spurious transition)
- **Verify:** Cover daily dedup survives restart (covers don't re-trigger same day)
- **Sensor:** `binary_sensor.<room>_occupied` attributes include `became_occupied_time`, `last_trigger_source`
- **Test:** `test_occupied_sensor_restores_state`, `test_coordinator_survives_restart`
- **Live:** Check occupied sensor attributes after HA restart — should show pre-restart values

### D2: Wire Orphaned Room Switches

3 switches exist with RestoreEntity but are never checked at runtime:
- `ClimateAutomationSwitch` (switch.py:1092) — should gate climate/HVAC actions
- `CoverAutomationSwitch` (switch.py:1127) — should gate cover actions
- `ManualModeSwitch` (switch.py:1162) — should disable ALL automation when ON

2 switches are dead code:
- `OverrideOccupiedSwitch` (switch.py:1046) — never checked, no RestoreEntity
- `OverrideVacantSwitch` (switch.py:1069) — never checked, no RestoreEntity

**Files:** `coordinator.py`, `automation.py`, `switch.py`

**Wiring plan:**
- `ManualModeSwitch` ON → `_is_automation_enabled()` returns False (gates everything)
- `ClimateAutomationSwitch` OFF → skip climate service calls in automation.py
- `CoverAutomationSwitch` OFF → skip cover service calls in automation.py
- `OverrideOccupiedSwitch` ON → force occupied state in coordinator refresh
- `OverrideVacantSwitch` ON → force vacant state in coordinator refresh
- Add `RestoreEntity` to both Override switches

#### Acceptance Criteria
- **Verify:** Turning off CoverAutomationSwitch stops all cover actions for that room
- **Verify:** Turning off ClimateAutomationSwitch stops climate preset changes for that room
- **Verify:** Turning on ManualModeSwitch stops all automation (lights, covers, climate, fans)
- **Verify:** OverrideOccupied forces room occupied regardless of sensors
- **Verify:** OverrideVacant forces room vacant regardless of sensors
- **Test:** `test_manual_mode_gates_all_automation`, `test_cover_switch_gates_covers`, `test_climate_switch_gates_climate`, `test_override_occupied_forces_state`
- **Live:** Toggle each switch via HA UI, verify behavior changes immediately

### D3: Cover Automation Hardening

Fix the 5 compounding issues that make cover automation flaky.

**Files:** `automation.py`

**Fixes:**
1. Cover entity validation before every service call (filter unavailable/unknown)
2. Check `_safe_service_call()` return value; keep dedup date unset on failure (allows retry)
3. Cover mode config validation against VALID_OPEN_MODES set
4. Sunrise/sunset failure: log warning, default to NOT opening (safer)
5. Daily dedup now persisted via D1 (RestoreEntity attributes)

#### Acceptance Criteria
- **Verify:** If cover entity is unavailable, service call is skipped with warning log
- **Verify:** If cover service call fails (mock timeout), next refresh cycle retries
- **Verify:** Invalid cover mode in config logs error and falls back to legacy mode
- **Verify:** Missing HA location → covers don't open (log warning)
- **Test:** `test_cover_skips_unavailable_entities`, `test_cover_retries_on_failure`, `test_cover_validates_mode`, `test_cover_handles_no_location`
- **Live:** Check cover behavior after HA restart (should not double-open)

### D4: Listener Cleanup on Fast Reload

Clear `_unsub_state_listeners` at start of `async_config_entry_first_refresh()` to prevent
listener accumulation on rapid reloads.

**Files:** `coordinator.py`

#### Acceptance Criteria
- **Verify:** Rapid reload (2x in 5 seconds) doesn't double event handlers
- **Test:** `test_rapid_reload_no_listener_leak`

---

## Cycle B: Config Flow UX (v3.20.1)

**Why second:** User-facing quality. Independent of Cycle A internals.
**Risk:** MEDIUM — config_flow.py only, no runtime logic changes
**Review tier:** Hotfix (1 review)
**Can start in parallel with Cycle A** (different files, no dependency)

### D1: Automation Chaining in Initial Room Setup

Add automation chaining step to the initial room setup flow (currently options-flow only).
User should be able to bind HA automations to triggers during room creation.

**Files:** `config_flow.py`

#### Acceptance Criteria
- **Verify:** During initial room setup, after automation_behavior step, user sees automation chaining step
- **Verify:** User can bind automations to enter/exit/lux triggers during setup
- **Verify:** Existing options-flow chaining still works unchanged
- **Test:** Config flow test covering initial setup with chaining bindings

### D2: AI Rules in Initial Room Setup

Add AI rules step to initial room setup flow (currently options-flow only).

**Files:** `config_flow.py`

#### Acceptance Criteria
- **Verify:** During initial room setup, user can add AI NLP rules
- **Verify:** Existing options-flow AI rules still works unchanged

### D3: Split Oversized Options Step

Split `automation_behavior` options step (15 fields) into separate lighting + cover sub-steps,
matching the initial setup pattern.

**Files:** `config_flow.py`

#### Acceptance Criteria
- **Verify:** Options flow shows separate lighting and cover steps
- **Verify:** Neither step exceeds 10 fields

### D4: Conditional Fields

- Shared space fields: hidden unless CONF_SHARED_SPACE toggle is True
- Notification override fields: hidden unless CONF_OVERRIDE_NOTIFICATIONS is True

**Files:** `config_flow.py`

#### Acceptance Criteria
- **Verify:** Shared space fields only appear when toggle enabled
- **Verify:** Notification fields only appear when override enabled

### D5: AI Rule Person Selector

Change `CONF_AI_RULE_PERSON` from TextSelector to EntitySelector filtering person entities.

**Files:** `config_flow.py`

#### Acceptance Criteria
- **Verify:** Person field shows dropdown of person entities with autocomplete

---

## Cycle C: Stub Cleanup (v3.20.2)

**Why third:** Clean up dead code. Low risk, high polish.
**Risk:** LOW — removing/implementing stub entities
**Review tier:** Hotfix (1 review)
**Can run in parallel with Cycle B** (different files)

**Important:** Every removed entity must be documented in `docs/DEFERRED_TO_BAYESIAN.md`
with its name, original intent, data source requirements, and link to v4.0.0 Bayesian
Intelligence milestone in ROADMAP_v11.md. Nothing is silently dropped.

### D1: Remove Non-Functional Buttons

Remove `ClearDatabaseButton` and `OptimizeNowButton` — they do nothing on press and
mislead users. Document in deferred plan for reimplementation with real logic in v4.0.0.

**Files:** `button.py`

#### Acceptance Criteria
- **Verify:** Buttons no longer appear in entity list
- **Test:** No test regressions from removal
- **Verify:** Both buttons documented in `docs/DEFERRED_TO_BAYESIAN.md`

### D2: Remove Stub Sensors + Document for v4.0.0

Remove 11 diagnostic sensors that return hardcoded 0/None/"Unknown" and 2 stub binary
sensors. Create `docs/DEFERRED_TO_BAYESIAN.md` documenting each:

| Entity | Original Intent | Data Source Needed | v4.0.0 Milestone |
|--------|----------------|-------------------|-------------------|
| OccupancyPercentageTodaySensor | % of day room occupied | room_transitions DB + time calc | B2: Prediction sensors |
| EnergyWasteIdleSensor | kWh wasted in vacant rooms | energy_history + occupancy join | B4: Energy integration |
| MostExpensiveDeviceSensor | Highest-cost device | circuit_state + TOU rates | B4: Energy integration |
| OptimizationPotentialSensor | Monthly savings estimate | Bayesian + energy model | B4: Energy integration |
| EnergyCostPerOccupiedHourSensor | $/hour when occupied | energy_daily + occupancy | B4: Energy integration |
| TimeUncomfortableTodaySensor | Minutes outside comfort | environmental_data + thresholds | B2: Prediction sensors |
| AvgTimeToComfortSensor | Avg recovery to comfort | environmental_data time series | B2: Prediction sensors |
| WeekdayMorningOccupancyProbSensor | AM weekday occupancy % | Bayesian posterior (room_transitions) | B1: Bayesian model core |
| WeekendEveningOccupancyProbSensor | PM weekend occupancy % | Bayesian posterior (room_transitions) | B1: Bayesian model core |
| TimeOccupiedTodaySensor | Hours occupied today | room_transitions + time calc | B2: Prediction sensors |
| OccupancyPatternDetectedSensor | Pattern description | Pattern learning + Bayesian | B1: Bayesian model core |
| OccupancyAnomalyBinarySensor | Unusual occupancy | Bayesian + z-score | B2: Prediction sensors |
| EnergyAnomalyBinarySensor | Unusual energy usage | MetricBaseline + Bayesian | B4: Energy integration |

**Files:** `sensor.py`, `binary_sensor.py`, new `docs/DEFERRED_TO_BAYESIAN.md`

#### Acceptance Criteria
- **Verify:** Removed entities no longer appear
- **Verify:** No import errors or missing references
- **Verify:** `docs/DEFERRED_TO_BAYESIAN.md` exists with all 15 entities documented
- **Verify:** Each entry links to a specific v4.0.0 Bayesian milestone (B1-B4)
- **Test:** All existing tests pass, no regressions

### D3: Remove Dead Signal

Remove `SIGNAL_COMFORT_REQUEST` — defined in signals.py but never dispatched or consumed.
Document in DEFERRED_TO_BAYESIAN.md as potentially useful for v4.0.0 comfort predictions.

**Files:** `domain_coordinators/signals.py`

#### Acceptance Criteria
- **Verify:** No grep matches for SIGNAL_COMFORT_REQUEST after removal
- **Verify:** Documented in DEFERRED_TO_BAYESIAN.md

---

## Cycle D: Coordinator Hardening (v3.21.0) — SERIALIZE

**Why fourth:** Fixes CRITICAL coordinator resilience issues. Depends on Cycle A patterns.
**Risk:** HIGH — touches all 7 coordinator files + manager
**Review tier:** Feature (2 reviews + live validation)

### D1: Energy DB Restore Parallelization + Timeout

Replace 10 sequential `_restore_*` methods with `asyncio.gather()` + per-method timeout.
Wrap in `asyncio.wait_for(timeout=15)` to prevent setup hang.

**Files:** `domain_coordinators/energy.py`

#### Acceptance Criteria
- **Verify:** Energy coordinator setup completes in <5s (was sequential, potentially >30s)
- **Verify:** If DB is locked, coordinator still starts (with warnings) within timeout
- **Test:** `test_energy_restore_parallel`, `test_energy_restore_timeout`
- **Live:** Check energy coordinator startup time in HA logs after restart

### D2: Coordinator Startup Ordering

Add synchronization so HVAC waits for Presence to be ready before reading house state.
Use `asyncio.Event` set by Presence after discovery completes.

**Files:** `domain_coordinators/manager.py`, `domain_coordinators/presence.py`, `domain_coordinators/hvac.py`

#### Acceptance Criteria
- **Verify:** HVAC sees correct house state on first decision cycle after restart
- **Verify:** If Presence takes >10s, HVAC starts anyway with default state (not hang)
- **Test:** `test_hvac_waits_for_presence`, `test_hvac_timeout_default_state`

### D3: Safety Sensor Recovery

When sensor transitions unavailable→available, re-evaluate current hazard state (not just
clear rate history).

**Files:** `domain_coordinators/safety.py`

#### Acceptance Criteria
- **Verify:** CO sensor goes unavailable at 100ppm, comes back at 50ppm → hazard state updates
- **Test:** `test_sensor_recovery_reevaluates_hazard`

### D4: NM Alert State Persistence

Persist alert state + cooldown timers via RestoreEntity on the NM diagnostics sensor.
On restart, restore cooldown windows to prevent re-fire.

**Files:** `domain_coordinators/notification_manager.py`, `sensor.py`

#### Acceptance Criteria
- **Verify:** CRITICAL alert cooldown survives restart (doesn't re-fire immediately)
- **Test:** `test_nm_cooldown_persists_across_restart`

### D5: Security Expected Arrival Expiry

Fix `SanctionChecker.check_entry()` to validate arrival window timestamp. Expired arrivals
should not suppress security alerts.

**Files:** `domain_coordinators/security.py`

#### Acceptance Criteria
- **Verify:** Expected arrival older than window_minutes is not treated as sanctioned
- **Test:** `test_expired_arrival_not_sanctioned`

### D6: EnergyObservationModeSwitch RestoreEntity

Add RestoreEntity to `EnergyObservationModeSwitch` to eliminate race condition.

**Files:** `switch.py`

#### Acceptance Criteria
- **Verify:** Observation mode state survives restart
- **Test:** `test_energy_observation_mode_restores`

### D7: Feature Toggle — AI Automation Per Room

Add `AiAutomationSwitch` per room. When OFF, AI rules and automation chaining don't execute
for that room.

**Files:** `switch.py`, `coordinator.py`

#### Acceptance Criteria
- **Verify:** Turning off AI automation switch stops AI rules and chained automations for that room
- **Verify:** Other rooms unaffected
- **Test:** `test_ai_automation_switch_gates_rules`

---

## Cycle E: Observability (v3.21.1)

**Why fifth:** Adds debugging sensors and observation mode toggles. Depends on D coordinator wiring.
**Risk:** LOW-MEDIUM — new sensors + new toggle switches, no behavior changes to existing logic
**Review tier:** Feature (2 reviews — new switches affect runtime behavior)

### D1: Coordinator Observation Mode Toggles

HVAC has observation mode (sensors compute, no actions). Extend this pattern to Safety,
Security, and Presence coordinators. Each gets a `switch.ura_<coordinator>_observation_mode`
toggle with RestoreEntity.

**Observation mode means:** Coordinator runs its full analysis pipeline (hazard detection,
state inference, entry evaluation) but does NOT execute actions (no service calls, no NM
alerts, no lock commands). Sensors still update. Useful for tuning, debugging, and onboarding.

| Coordinator | What runs in observation mode | What's suppressed |
|-------------|-------------------------------|-------------------|
| Safety | Hazard detection, rate-of-change, thresholds | NM alerts, action intents |
| Security | Entry evaluation, lock sweep checks, armed state | Lock commands, NM alerts, camera triggers |
| Presence | State inference, zone tracking, census fusion | House state dispatches, NM notifications |

**Files:** `switch.py`, `domain_coordinators/safety.py`, `security.py`, `presence.py`

#### Acceptance Criteria
- **Verify:** Each coordinator's observation mode toggle exists and restores state
- **Verify:** In observation mode, sensors update but no service calls fire
- **Verify:** Observation mode state visible in coordinator diagnostics
- **Test:** `test_safety_observation_mode`, `test_security_observation_mode`, `test_presence_observation_mode`
- **Live:** Toggle safety observation mode ON, trigger a hazard, verify sensor updates but no NM alert

### D2: HVAC Override Arrester Deep Observability

The override arrester is a critical function for energy equilibrium — it detects when
someone manually changes HVAC setpoints and either reverts or compromises. Current
observability is minimal (just on/off sensor). Expand to full transparency.

New sensor: `sensor.ura_hvac_arrester_status` — "monitoring"/"detected"/"grace"/"acting"/"cooldown"

**Attributes (all real-time):**
- `last_override_detected` — ISO timestamp of last detected manual override
- `last_override_entity` — which thermostat entity was overridden
- `last_override_old_setpoint` / `last_override_new_setpoint` — what changed
- `override_type` — "minor" (within compromise range) or "major" (outside range)
- `grace_period_remaining_seconds` — time before arrester acts (user may be testing)
- `planned_action` — what the arrester WILL do when grace expires: "revert", "compromise", "accept"
- `compromise_setpoint` — if compromising, what the resulting setpoint will be
- `overrides_today` — count of overrides detected today
- `overrides_reverted_today` — count reverted
- `overrides_compromised_today` — count where compromise was applied
- `ac_reset_active` — whether AC reset cycle is in progress
- `ac_reset_timeout_minutes` — configured timeout for AC reset
- `ac_reset_start_time` — when current reset started

**Files:** `sensor.py`, `domain_coordinators/hvac_override.py`

#### Acceptance Criteria
- **Sensor:** `sensor.ura_hvac_arrester_status` shows real-time arrester state machine
- **Verify:** grace_period_remaining_seconds counts down in real-time
- **Verify:** planned_action shows what WILL happen before it happens
- **Verify:** After override is reverted, last_override_* attributes persist for debugging
- **Test:** `test_arrester_sensor_grace_period`, `test_arrester_sensor_compromise`, `test_arrester_sensor_revert`
- **Live:** Manually change thermostat, watch arrester sensor update through grace→action cycle

### D3: NM Alert State Sensor

New sensor: `sensor.ura_nm_alert_state` — idle/alerting/cooldown/repeating/re_evaluate.
Attributes: active_alert data, cooldown_remaining_seconds, repeat_timer_active, messaging_suppressed.

**Files:** `sensor.py`, `domain_coordinators/notification_manager.py`

#### Acceptance Criteria
- **Sensor:** `sensor.ura_nm_alert_state` shows current alert machine state
- **Verify:** Attributes update in real-time during alert lifecycle

### D4: Energy Envoy Status Sensor

New sensor: `sensor.ura_energy_envoy_status` — online/offline/stale.
Attributes: offline_count_today, last_reading_age_seconds, uptime_hours.

**Files:** `sensor.py`, `domain_coordinators/energy.py`

#### Acceptance Criteria
- **Sensor:** `sensor.ura_energy_envoy_status` reflects Envoy connectivity
- **Live:** Verify shows "online" when Envoy is reachable

### D5: Safety Active Cooldowns Sensor

New sensor: `sensor.ura_safety_active_cooldowns` — "none" or list of active cooldowns.
Attributes: per-hazard cooldown remaining seconds.

**Files:** `sensor.py`, `domain_coordinators/safety.py`

#### Acceptance Criteria
- **Sensor:** Shows cooldown timers after a hazard alert

### D6: Security Authorized Guests Sensor

New sensor: `sensor.ura_security_authorized_guests` — "none" or "N guests".
Attributes: guest list with expiry times.

**Files:** `sensor.py`, `domain_coordinators/security.py`

#### Acceptance Criteria
- **Sensor:** Shows current authorized guests and expected arrivals with time remaining

---

## Cycle F: Signal Wiring (v3.22.0) — CONFIGURABLE RESPONSES

**Why last:** Adds cross-coordinator intelligence. Depends on all coordinator fixes.
**Risk:** MEDIUM-HIGH — new signal handlers + config flow UI for response preferences
**Review tier:** Feature (2 reviews — config flow + cross-coordinator behavior)

### Design Principle: All Signal Responses Are Configurable

Every coordinator's response to a cross-coordinator signal is **opt-in with sensible defaults**.
Users can enable/disable each response via the coordinator's config flow options step.

This means:
1. Each coordinator gets a "Signal Responses" config sub-step in its options flow
2. Each response is a BooleanSelector toggle with a clear description
3. Defaults are conservative (safety-critical responses ON by default, convenience OFF)
4. Toggling a response does NOT require integration reload — checked at signal handler runtime

**Config pattern per coordinator:**
```
Options → [Coordinator Name] → Signal Responses
  ☑ On safety hazard: [describe action] (default: ON/OFF)
  ☑ On person arriving: [describe action] (default: ON/OFF)
  ☑ On security event: [describe action] (default: ON/OFF)
```

### D1: Signal Response Config Infrastructure

Add `CONF_SIGNAL_RESPONSE_*` constants and config flow steps for each coordinator that
will consume signals. Add a shared pattern for reading signal response preferences at runtime.

**Files:** `const.py`, `config_flow.py`

**New config keys per coordinator:**

| Coordinator | Signal | Config Key | Default | Description |
|-------------|--------|-----------|---------|-------------|
| HVAC | Safety hazard | `CONF_HVAC_ON_HAZARD_STOP_FANS` | **OFF** | Stop fans on smoke/CO |
| HVAC | Safety hazard | `CONF_HVAC_ON_HAZARD_EMERGENCY_HEAT` | **OFF** | Emergency heat on freeze |
| Security | Safety hazard | `CONF_SECURITY_ON_HAZARD_UNLOCK_EGRESS` | **OFF** | Unlock doors on fire |
| Security | Person arriving | `CONF_SECURITY_ON_ARRIVAL_ADD_EXPECTED` | **OFF** | Auto-add to expected arrivals |
| Energy | Safety hazard | `CONF_ENERGY_ON_HAZARD_SHED_LOADS` | **OFF** | Emergency load shed |
| Music | Safety hazard | `CONF_MUSIC_ON_HAZARD_STOP` | **OFF** | Stop music on critical hazard |
| Music | Person arriving | `CONF_MUSIC_ON_ARRIVAL_START` | **OFF** | Start music on arrival |
| Music | Security event | `CONF_MUSIC_ON_SECURITY_STOP` | **OFF** | Stop music on security alert |

**ALL defaults are OFF.** Cross-coordinator signal responses are intrusive behaviors
that need testing and trust-building before enabling. Users opt-in deliberately per
coordinator. The system logs what it WOULD have done (observation-style) even when
disabled, so users can validate behavior before enabling.

#### Acceptance Criteria
- **Verify:** Each coordinator's options flow shows "Signal Responses" sub-step
- **Verify:** Toggles have clear descriptions of what will happen
- **Verify:** Defaults are correct (safety ON, convenience OFF)
- **Test:** Config flow test for each coordinator's signal response step

### D2: Wire SIGNAL_SAFETY_HAZARD (Configurable)

Add consumers with config-gated responses:

**HVAC** (`hvac.py`) — checked at runtime via config:
- `CONF_HVAC_ON_HAZARD_STOP_FANS` (default ON): Smoke/CO → stop all fans (prevent spread)
- `CONF_HVAC_ON_HAZARD_EMERGENCY_HEAT` (default ON): Freeze → activate emergency heat

**Security** (`security.py`) — checked at runtime via config:
- `CONF_SECURITY_ON_HAZARD_UNLOCK_EGRESS` (default ON): Smoke/fire → unlock entry doors

**Music Following** (`music_following.py`) — checked at runtime via config:
- `CONF_MUSIC_ON_HAZARD_STOP` (default ON): Any CRITICAL → stop all playback

**Energy** (`energy.py`) — checked at runtime via config:
- `CONF_ENERGY_ON_HAZARD_SHED_LOADS` (default ON): CRITICAL → shed discretionary loads

Each handler checks its config toggle before acting:
```python
@callback
def _handle_safety_hazard(self, hazard: SafetyHazard) -> None:
    if not self._get_signal_config(CONF_HVAC_ON_HAZARD_STOP_FANS):
        return
    if hazard.hazard_type in ("smoke", "co") and hazard.severity == "critical":
        self._emergency_fan_stop()
```

**Files:** `domain_coordinators/hvac.py`, `security.py`, `energy.py`, `music_following.py`

#### Acceptance Criteria
- **Verify:** All responses OFF by default — smoke hazard with defaults does NOT stop fans
- **Verify:** User enables fan stop toggle → smoke hazard stops fans
- **Verify:** Non-critical hazards → no cross-coordinator action (proportional response)
- **Verify:** When disabled, handler logs "would have stopped fans" (dry-run visibility)
- **Test:** `test_hazard_default_off_no_action`, `test_hazard_stops_fans_when_enabled`, `test_hazard_logs_would_have_when_disabled`, `test_hazard_unlocks_doors_when_enabled`, `test_hazard_sheds_loads_when_enabled`

### D3: Wire SIGNAL_PERSON_ARRIVING to Security + Music (Configurable)

**Security** (`security.py`) — `CONF_SECURITY_ON_ARRIVAL_ADD_EXPECTED` (default ON):
- Registered person arriving → add to expected arrivals
- Suppress "unknown person" alerts for 5 minutes

**Music Following** (`music_following.py`) — `CONF_MUSIC_ON_ARRIVAL_START` (default **OFF**):
- Start preferred music in arriving person's zone
- Off by default — convenience feature, user must opt in

**Files:** `domain_coordinators/security.py`, `music_following.py`

#### Acceptance Criteria
- **Verify:** Both toggles OFF by default — arrival triggers no cross-coordinator action
- **Verify:** User enables security toggle → geofence arrival adds expected arrival
- **Verify:** User enables music toggle → music starts on arrival
- **Test:** `test_arrival_default_off_no_action`, `test_arrival_security_when_enabled`, `test_arrival_music_when_enabled`

### D4: Wire SIGNAL_SECURITY_EVENT to Music (Configurable)

**Music Following** (`music_following.py`) — `CONF_MUSIC_ON_SECURITY_STOP` (default ON):
- CRITICAL security event → stop all playback

**Files:** `domain_coordinators/music_following.py`

#### Acceptance Criteria
- **Verify:** CRITICAL security event stops music when toggle ON
- **Verify:** User disables toggle → music continues during security events
- **Test:** `test_security_event_stops_music_when_enabled`, `test_security_event_skips_when_disabled`

---

## Tracking: Findings vs Fixes

### CRITICAL (7 found → 7 addressed)
| # | Finding | Cycle | Status |
|---|---------|-------|--------|
| 1 | Room state loss on restart (coordinator.py) | A-D1 | PLANNED |
| 2 | Energy DB restore hangs (no timeout) | D-D1 | PLANNED |
| 3 | HVAC+Energy zone control no validation | D-D2 | PLANNED |
| 4 | Coordinator startup ordering race | D-D2 | PLANNED |
| 5 | NM async_notify 209 lines (complexity) | DEFERRED | Refactor tracked but not blocking |
| 6 | Config automation_behavior 15 fields | B-D3 | PLANNED |
| 7 | SIGNAL_SAFETY_HAZARD dead signal | F-D1 | PLANNED |

### HIGH (18 found → 16 addressed, 2 deferred)
| # | Finding | Cycle | Status |
|---|---------|-------|--------|
| 1 | Cover daily dedup lost on restart | A-D1/D3 | PLANNED |
| 2 | Cover entity validation missing | A-D3 | PLANNED |
| 3 | Cover error recovery missing | A-D3 | PLANNED |
| 4 | Listener cleanup on fast reload | A-D4 | PLANNED |
| 5 | Signal subscriptions on config update | A-D4 | VERIFIED OK |
| 6 | 3 orphaned room switches | A-D2 | PLANNED |
| 7 | Safety sensor recovery | D-D3 | PLANNED |
| 8 | Safety+Security+NM dedup uncoordinated | DEFERRED | Architecture discussion needed |
| 9 | Energy 10 sequential restores | D-D1 | PLANNED |
| 10 | Safety _discover_sensors duplication | DEFERRED | Refactor, not blocking |
| 11 | No circuit breaker for coordinator failures | DEFERRED | Complex, need design |
| 12 | 2 stub buttons do nothing | C-D1 | PLANNED |
| 13 | NM alert state observability | E-D1 | PLANNED |
| 14 | Energy envoy status observability | E-D2 | PLANNED |
| 15 | Safety cooldown observability | E-D3 | PLANNED |
| 16 | Security guest list observability | E-D4 | PLANNED |
| 17 | Energy entity config not validated | DEFERRED | Low user impact |
| 18 | Security lock entities not validated | DEFERRED | Low user impact |

### MEDIUM (25 found → 18 addressed, 7 deferred)
Key addressed: cover mode validation, sunrise/sunset handling, AI rule person selector,
conditional config fields, NM alert persistence, security arrival expiry, energy observation
mode persistence, AI automation toggle, config entry merge DRY violation (deferred),
hardcoded thresholds (deferred — config flow expansion is large effort for v4.x).

---

## Version Mapping

| Version | Cycle | Scope | Est. Tests |
|---------|-------|-------|------------|
| v3.20.0 | A: Room Resilience | State persistence, switch wiring, cover hardening | +30 |
| v3.20.1 | B: Config UX | Config flow improvements | +10 |
| v3.20.2 | C: Stub Cleanup | Remove 15 entities + dead signal + DEFERRED_TO_BAYESIAN.md | +5 |
| v3.21.0 | D: Coordinator Hardening | Energy/HVAC/Safety/NM/Security fixes + AI toggle | +25 |
| v3.21.1 | E: Observability | Observation toggles, arrester deep sensor, 4 diagnostic sensors | +20 |
| v3.22.0 | F: Signal Wiring | Configurable cross-coordinator signal responses + config flow | +30 |

**Total estimated new tests: ~120**
**Projected test count: ~1,363**

## Parallelization Map

```
Week 1:  [--- Cycle A (worktree, serialize) ---]  [- Cycle B (parallel) -]  [- Cycle C (parallel) -]
Week 2:  [---------- Cycle D (serialize, depends on A) ----------]
Week 3:  [--- Cycle E (2 reviews, depends on D) ---]  [--- Cycle F (depends on D+E) ---]
```

- A, B, C can start simultaneously (different file sets)
- D must wait for A to merge (builds on room persistence patterns)
- E must complete before F (observation mode toggles + arrester sensor inform signal response design)
- F depends on D (coordinator fixes) and E (observation toggles pattern reused for signal config)

## Verification

After each cycle:
1. `PYTHONPATH=quality python3 -m pytest quality/tests/ -v` — all tests pass
2. `/deploy` — includes live validation (Step 9)
3. `@ura-validator live` — post-deploy entity/log/DB checks
4. Pre-review tag: `git tag pre-review-v<version>`
