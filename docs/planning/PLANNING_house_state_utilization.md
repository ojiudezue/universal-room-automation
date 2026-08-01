# PLANNING — House-State Utilization Roadmap

Status: OPERATOR-RATIFIED 2026-07-30 ("I like the recommendations even rung 4")
Owner: architecture
Scope: multi-cycle (rungs 2 → 4). Rung 1 is in flight in a parallel cycle and is referenced here, not re-planned.

## 0. Framing

The `HouseStateMachine` (custom_components/universal_room_automation/domain_coordinators/house_state.py:22-33) defines nine
states — AWAY, ARRIVING, HOME_DAY, HOME_EVENING, HOME_NIGHT, SLEEP, WAKING, GUEST, VACATION (no ENTERTAINMENT). The canonical
instance lives on `CoordinatorManager._house_state_machine` (manager.py:143), exposed via a `.house_state` property.
`StateInferenceEngine.infer()` (presence.py:906) proposes; the machine disposes.

Today's utilization audit:

| State         | Consumed by                                             | Verdict                    |
|---------------|---------------------------------------------------------|----------------------------|
| SLEEP         | HVAC preset trust, fan sleep-mode, NM quiet             | Well-consumed              |
| AWAY          | Presence veto, a few HVAC hooks                         | Thin — big posture upside  |
| HOME_DAY      | (nothing operational)                                   | Dead                       |
| HOME_EVENING  | (nothing operational)                                   | Dead                       |
| ARRIVING      | (nothing operational)                                   | Dead                       |
| HOME_NIGHT    | Some HVAC (via preset), lighting overlap                | Thin                       |
| GUEST         | Preset-override string only (energy.py dead read)       | Nearly decorative          |
| VACATION      | Equivalent to AWAY + preset string                      | Undifferentiated           |
| WAKING        | Sleep-exit gate                                         | Sufficient                 |

**Rung-1 dead wires (fixed in parallel cycle, referenced not re-planned):**
- `energy.py:6824` reads `getattr(presence, "_house_state", "")` — attribute does not exist on presence coordinator → always
  returns `""` → guest dynamic-preset reset (energy.py surrounding block) is unreachable.
- `hvac.py:687-688` same dead attribute read at boot-seed → HVAC boot-state defaults instead of seeding from truth.
- `optimization.py:2388` compares house state against literal `"night"` — the enum value is `"home_night"`, so the branch
  never fires.
- `security.py:943-969` `_handle_house_state_intent` has a full complete house-state → armed-state mapping, but there is
  NO caller: no `SIGNAL_HOUSE_STATE_CHANGED` subscription in security.py, no intent producer. `CONF_SECURITY_AUTO_FOLLOW`
  (const.py:1114, config_flow.py:5724, 5803-5804) exists with default False and is not read anywhere operational.

## 1. Institutional context verified

Greps run (rg against HEAD, 2026-07-30):

- `HouseState`, `house_state`, `_house_state` — enumerated all live-read/live-write sites; four dead reads listed above.
- `SIGNAL_HOUSE_STATE_CHANGED` — declared `signals.py:12`, payload dataclass `signals.py:210`, subscribed in hvac.py:621
  (preset adjust), sensor.py, several diag surfaces. NOT subscribed in security.py, energy.py posture path, water/appliance.
- `observation_mode` / `_observation_mode` — REUSED existing kill-switch idiom: safety.py:679-680, 2010; hvac.py:275, 418-425;
  binary_sensor.py:2165. Every domain coordinator we plan to route intent through has this surface.
- `CONF_SECURITY_AUTO_FOLLOW` — const.py:1114, config_flow.py:5724/5803-5804. REUSED as rung-2a kill switch.
- `ArmedState` mapping — REUSED at security.py:950-960 (already complete; needs wiring only).
- `CoordinatorManager._house_state_machine` — manager.py:143; `.house_state` property confirmed as canonical.
- `CoordinatorManagerSensor` precedent — house-level diagnostic device already exists; the new "house policy" observability
  attrs land there rather than creating a new device.
- `preset_overrides` machinery — reused for rung-3 GUEST softening (verify exact module during rung-3 build, not re-planned here).

Design docs consulted (skim): `docs/Coordinator/security.md`, `docs/Coordinator/energy.md`, `docs/Coordinator/hvac.md`,
`docs/Coordinator/presence.md`. Prior planning docs skimmed for overlap: `PLANNING_presence_pair_guest_latch_veto_gap.md`
(guest-latch cycle — feeds rung 3 GUEST work; no conflict).

Memory bodies pulled: `project_v4_7_25_hvac_presence_timer_knobs_live.md` (Numbers-persistence pattern for any knob we
expose live), `project_v4_7_24_substrate_unification_live.md` (subscription-rebuild Bug Class #50 — applies to any new
SIGNAL_HOUSE_STATE_CHANGED subscriber added below), `project_presence_guest_latch_and_veto_gap.md` (GUEST semantics).

**NEW vs REUSED for proposed additions:** every proposed addition below is annotated REUSED (with file:line) or NEW.

## 2. Plan-wide invariants (operator-ratified 2026-07-30)

These apply to every rung and every reviewer must check them.

### INV-1 Observability of state-driven behavior
Every rung-2..4 state-driven behavior change MUST be visible on the running house before any operator has to open logs.
Concretely:
- **House policy diagnostic on the Coordinator Manager device** (REUSED — `CoordinatorManagerSensor` precedent): NEW sensor
  `sensor.ura_coordinator_manager_house_policy` with attrs:
  - `active_policies: list[str]` — e.g. `["security.auto_follow", "energy.away_posture", "water.eco"]`.
  - `last_state_driven_action: {policy, state, action, at, coordinator}`.
  - `last_state_transition: {from, to, at, confidence}`.
- **Per-coordinator execution attrs** on each coordinator's own device — e.g. security coordinator sensor gains
  `state_driven_arming_last: {from_state, to_armed, at, notified: True}`, energy coordinator battery_strategy sensor
  gains `state_driven_posture: {mode, entered_at, source_state}`, water/appliance similar.
- Rule: **no silent state-driven actuation.** If a state-driven action fires without a diagnostic attr update, review
  fails.

### INV-2 Coordinator-state honoring (never bypass)
The house-state machine PROPOSES intent. The owning domain coordinator DISPOSES through its EXISTING enable /
observation-mode / kill-switch machinery. No new bypass paths. Concretely:
- **Security** (rung 2a, 3, 4-VACATION): actions ONLY when the security coordinator is enabled AND
  `_observation_mode == False` AND `CONF_SECURITY_AUTO_FOLLOW == True`. Route through the same armed-state code path
  used by manual arming (i.e. call the coordinator's arm/disarm entrypoint, do not poke `_armed_state` directly).
- **Energy** (rung 2b, 4-VACATION): posture change is an INTENT into EC's existing decision cycle (the same cycle that
  already resolves `battery_strategy`), not a direct actuator call. Each existing kill switch (EC observation switch,
  per-tier enable switches) still applies. If EC is disabled or in observation, we still update the diagnostic attr
  ("would apply away-posture; EC disabled") — INV-1 stays honest.
- **HVAC** (rung 4-EVENING, 4-ARRIVING, 4-VACATION): route through existing preset-selection code, respecting
  `hvac._observation_mode` (hvac.py:275/418-425). No new direct thermostat calls.
- **Water / appliance** (rung 2c): NOTIFY-only in rung 2c. Actuation deferred to a later cycle that gets its own
  observation switch + kill switch.
- **Safety**: untouched by this roadmap. Not a state-driven consumer.

### INV-3 Placement
- **House-level policy surface** → Coordinator Manager device (alongside stuck-signal watchdog + `CoordinatorManagerSensor`).
  This is where "which policies are active" lives.
- **Per-domain execution attrs** → each coordinator's own device (security, energy, hvac, water/appliance). This is where
  "what did this coordinator actually do in response" lives.
- No new devices, no shadow surfaces.

### INV-4 State-driven arming is always notified
Any auto-follow arm/disarm transition fires an NM notification (channel: security, severity: HIGH for arm, MEDIUM for
disarm-on-arrival). Operator standing rule: security posture changes are never silent. Reuse existing NM
`NotificationAction` (security.py:930-938 pattern).

### INV-5 Rung sequencing
Rungs ship in order: rung 1 → rung 2a → rung 2b → rung 2c → rung 3 → rung 4 items (each its own cycle). Do not bundle.
Each cycle carries the observability required by INV-1 for the behaviors it turns on.

## 3. Rung 1 — REFERENCE ONLY (in flight, parallel cycle)

Dead-wire fixes + `SIGNAL_HOUSE_STATE_CHANGED` subscription in security.py behind default-off `CONF_SECURITY_AUTO_FOLLOW`.
This roadmap does not re-plan rung 1. Rung 2a builds ON TOP of rung 1's wiring.

Acceptance dependency: before rung 2a can begin, rung 1 must have landed such that toggling `CONF_SECURITY_AUTO_FOLLOW`
delivers a `SIGNAL_HOUSE_STATE_CHANGED` payload into `security._handle_house_state_intent` and that handler runs. Rung 2a
adds the behavior; rung 1 adds only the pipe.

## 4. Rung 2 — Meaningful policy from AWAY / VACATION / SLEEP transitions

### D2a — Security auto-follow ENABLED path

**What:** When `CONF_SECURITY_AUTO_FOLLOW == True` and the security coordinator is enabled + not in observation, house-state
transitions drive real arming through security's existing armed-state entrypoint:

| Transition             | Armed target        | Notify severity |
|------------------------|---------------------|-----------------|
| any → AWAY             | ARMED_AWAY          | HIGH            |
| any → VACATION         | ARMED_VACATION      | HIGH            |
| any → GUEST            | ARMED_HOME (no int) | MEDIUM          |
| AWAY/VACATION → ARRIVING | DISARMED          | MEDIUM          |
| SLEEP → WAKING         | DISARMED            | MEDIUM          |

**Files:**
- `domain_coordinators/security.py` — extend `_handle_house_state_intent` to (a) call the same public arm/disarm method
  manual UI uses (do NOT set `_armed_state` directly), (b) skip when `_observation_mode` or `not _enabled`, (c) emit an
  NM `NotificationAction` per INV-4, (d) update per-coordinator execution attr `state_driven_arming_last`.
- `sensor.py` — extend the security coordinator sensor with attrs listed under INV-1 (per-coordinator).
- `domain_coordinators/manager.py` or a new small helper — publish `active_policies` + `last_state_driven_action` +
  `last_state_transition` for the CM device (INV-1). REUSED CoordinatorManagerSensor.
- `sensor.py` — new `HousePolicySensor` (NEW: no equivalent found in grep of sensor.py).

**Constants / knobs (Numbers Get Knobs ladder):**
- `CONF_SECURITY_AUTO_FOLLOW` — REUSED (const.py:1114). Rung 1 module-constant tier. Kill switch (False = feature dormant).
- `CONF_SECURITY_AUTO_FOLLOW_ARM_DELAY_S` — NEW module constant; short debounce so a bounce through AWAY doesn't arm.
  Default 30s. Module constant tier (Numbers Get Knobs rung 1) — safety-adjacent; operator changes require review.
- No new entity knobs in rung 2a.

**Acceptance criteria:**
- Verify: with `CONF_SECURITY_AUTO_FOLLOW=False`, no arming/disarming occurs on any transition (regression guard).
- Verify: with `=True` + security enabled + not observation: house AWAY for ≥ arm-delay → armed state = ARMED_AWAY within
  arm-delay + 1 batch.
- Verify: observation_mode=True suppresses actuation but STILL updates the diagnostic attr with a "would-arm" record.
- Sensor: `sensor.ura_coordinator_manager_house_policy.active_policies` includes `"security.auto_follow"`.
- Sensor: security coordinator device attr `state_driven_arming_last` populated with `from_state`, `to_armed`, `at`,
  `notified=True`.
- NM: exactly one HIGH notification per genuine transition (dedup on batch); zero on bounce.
- Test: `test_security_auto_follow_arms_on_away`, `_disarms_on_arriving`, `_observation_mode_suppresses_but_records`,
  `_disabled_no_notify`, `_bounce_debounced`.
- Live: after deploy, force AWAY (person-tracker override or presence intent) → observe arming + NM in ≤ 60s; force
  ARRIVING → observe disarm.

**Tier:** Tier 2-DB (operator standing policy — regression-prone: security actuation, cross-coordinator ripple presence
→ house-state → security → NM). Three framing-disjoint reviews:
- A = correctness + edge cases (transition table completeness, debounce, observation gating).
- B = cross-coordinator + lifecycle (SIGNAL subscription doesn't clobber on rebuild — Bug Class #50; NM channel path;
  restart resilience of armed state).
- C = surfaces + notification authority (attrs round-trip through options + RestoreEntity where relevant; NM dedup key
  correctness; no double-emit if presence re-publishes same state).

### D2b — Energy AWAY / VACATION posture (through EC decision cycle)

**What:** When house is in AWAY (≥ N minutes) or VACATION, EC's decision cycle receives an INTENT that biases:
- HVAC pre-cool: relaxed (widen setpoints per DPM's existing away band; do NOT bypass DPM).
- Battery drain-target allowance: deeper (respect existing floor machinery — do NOT lower floor, raise permitted drain).
- EVSE: freedom to charge whenever cost-favorable (relax any presence-linked hold).

**Files:**
- `domain_coordinators/energy.py` — add a house-state intent subscriber (REUSED `SIGNAL_HOUSE_STATE_CHANGED`) that sets
  an internal `_house_posture` field consumed by the existing decision cycle. Do NOT touch actuators directly.
- Same file — extend `battery_strategy` sensor attrs with `state_driven_posture` (INV-1 per-coordinator surface).
- `sensor.py` — no new sensors; extend attrs.

**Constants / knobs:**
- `CONF_ENERGY_HOUSE_STATE_POSTURE` — NEW config-flow enable (rung-2 default False during shakeout, flip True after
  observation). Options-flow tier (Numbers Get Knobs rung 2 — per-deployment structure).
- `CONF_ENERGY_AWAY_POSTURE_MIN_MINUTES` — NEW Number entity (Numbers Get Knobs rung 3 — operator legitimately tunes by
  observation; default 20 min). Persistence via existing Number-persistence machinery (see
  `project_v4_7_25_hvac_presence_timer_knobs_live.md`).

**Acceptance criteria:**
- Verify: house AWAY for < N min → posture unchanged.
- Verify: house AWAY for ≥ N min → EC `battery_strategy.state_driven_posture.mode == "away_relaxed"` within one EC cycle.
- Verify: EC observation switch ON → posture NOT actuated; diagnostic still populated with "would apply".
- Sensor: `sensor.ura_coordinator_manager_house_policy.active_policies` includes `"energy.away_posture"` when active.
- Test: `test_ec_away_posture_debounce`, `_vacation_uses_same_posture`, `_observation_suppresses_actuation`,
  `_home_transition_clears_posture`, `_no_actuator_direct_calls` (proves INV-2 by grep-mocking energy actuator entry
  points and asserting call count 0).
- Live: after deploy, verify posture flips within N min of measured AWAY dwell and clears within one cycle of ARRIVING.

**Tier:** Tier 2-DB (regression-prone: EC decision cycle, battery floor sibling risk — the inclement-arbitrage-WAIT-floor
saga is the standing precedent).

### D2c — Water / appliance AWAY posture (NOTIFY-only in rung 2)

**What:** When house is in AWAY (≥ M hours) or VACATION, emit a finding + NM notification: water-heater eco recommended,
monitored plugs left on. No actuation in this rung; actuation deferred to a Rung 2c-follow-up cycle with its own
observation switch.

**Files:**
- `domain_coordinators/optimization.py` — new finding kind `water_appliance_away_posture` gated on the corrected house-state
  read (uses `manager.house_state` property, not the dead `"night"` literal — this is one of the rung-1 fixes; verify at
  rung-2c build time).
- `sensor.py` — extend optimization findings surface; no new sensors.

**Constants / knobs:**
- `CONF_APPLIANCE_AWAY_POSTURE_MIN_HOURS` — NEW Number entity, default 4h. Rung-3 knob (operator tunes).
- Actuation is explicitly out of scope for this rung; a future cycle adds the actuator kill-switch + observation surface.

**Acceptance criteria:**
- Verify: AWAY for ≥ M hours → exactly one finding + one MEDIUM NM per dwell (dedup); no actuator calls (grep-anchored test).
- Sensor: policy sensor includes `"appliance.away_notify"` when finding active.
- Test: `test_appliance_away_notify_only`, `_dedup_per_dwell`, `_no_actuation`.
- Live: verify NM fires on a real 4h+ AWAY; verify no state changes on any plug/water-heater entity.

**Tier:** Tier 2 (notify-only, no actuation — lower blast radius than 2a/2b, but still cross-coordinator into NM).

## 5. Rung 3 — GUEST as a real mode

**What:** GUEST stops being a preset string and becomes a mode that softens automation in guest-designated zones and
biases NM.

**Sub-deliverables:**
- **D3a** GUEST zone softening — through EXISTING preset_overrides machinery (REUSED; verify module + exact call site at
  build time). Longer vacancy delays, less aggressive HVAC setback, no auto-off lighting in guest zones.
- **D3b** NM guest-suppression — TTS off, "notification lights" (bright colored flashes) suppressed in guest-designated
  zones for the duration of GUEST. Reuse existing NM per-channel mute infrastructure (grep NM channel mutes at build
  time — REUSED if found; otherwise the NM-gap audit memo lists per-channel mute as a NEW backlog item and this rung
  becomes the trigger).
- **D3c** Security ARMED_HOME-guest variant — interior sensors NOT armed in guest zones; perimeter still armed. Add to
  the security transition table from D2a.

**Depends on:** `PLANNING_presence_pair_guest_latch_veto_gap.md` GUEST latch fixes must be live first (otherwise GUEST
flickers and rung-3 flaps loud).

**Constants / knobs:**
- `CONF_GUEST_ZONES` — NEW options-flow multi-selector (rung 2 — per-deployment structure). Verify no equivalent config
  exists at build time.
- `CONF_GUEST_MODE_VACANCY_MULT` — NEW Number entity, default 2.0×. Rung-3 knob.

**Acceptance criteria:**
- Verify: entering GUEST → guest-zone vacancy delays multiply; non-guest zones unaffected.
- Verify: NM TTS suppressed in guest zones only.
- Verify: security stays ARMED_HOME with interior guest zones disarmed; perimeter armed.
- Verify: exiting GUEST restores all defaults within one batch.
- Sensor: policy sensor includes `"guest.mode"` when active; per-coordinator attrs enumerate which zones softened.
- Test: full transition suite + guest-latch edge cases.
- Live: verify with a real guest scenario.

**Tier:** Tier 2-DB (cross-coordinator: presence → house-state → security + NM + preset_overrides).

## 6. Rung 4 — Differentiate-or-delete (each item its own cycle)

Operator ratified all four. Each is a standalone cycle; sequence at cycle-scoping time.

### D4a — HOME_EVENING scene / lighting + HVAC bias hook
Real behavior on entering HOME_EVENING: dimmer lighting scene per-zone hook (through room automation's existing scene
machinery — REUSED, verify), HVAC bias toward evening comfort setpoints. Sun-aware boundary option (below).
Tier 2.

### D4b — ARRIVING pre-conditioning + porch + disarm
On entering ARRIVING: pre-condition HVAC (bring temp within band before occupants land), porch light on, security disarm
(covered by D2a mapping — this cycle adds the HVAC + lighting pieces). Kill switch: NEW `CONF_ARRIVING_ACTIONS_ENABLED`
(options-flow tier, default False). Tier 2.

### D4c — VACATION as real policy
Distinct from AWAY: extended HVAC setback (wider than AWAY), security ARMED_VACATION (covered by D2a), water-off decision
(finding + optional actuation with its own observation switch, deferred sub-cycle). NEW config-flow field
`CONF_VACATION_HVAC_SETBACK_F` (Number entity, rung-3 knob, default 8°F beyond AWAY band).
Tier 2-DB (water-off actuation, extended setback = comfort-loss risk if bug).

### D4d — Sun-aware evening / night boundaries (option)
Replace fixed `evening_start_hour` / `night_start_hour` on `StateInferenceEngine` with an OPTION to use
`sun.sun` elevation crossings. Preserves backward compat (hour-based remains default). NEW option
`CONF_HOUSE_STATE_USE_SUN_BOUNDARIES` (options-flow tier). Tier 2.

### D4e — DELETE recommendation for undifferentiated states
If at rung-4 scoping time any state STILL has no differentiated behavior after rungs 2-4 (candidates: HOME_DAY if D4a
covers evening only), file an explicit DELETE cycle with migration note (map deleted state to nearest survivor in the
state machine; publish a one-version deprecation window; update `HouseState` enum + `VALID_TRANSITIONS`). Do NOT leave
dead enum values.

## 7. Sequencing summary

1. Rung 1 (in flight)
2. D2a Security auto-follow — Tier 2-DB (map already written; smallest surface with biggest observability payoff)
3. D2b Energy away-posture — Tier 2-DB
4. D2c Water/appliance NOTIFY — Tier 2
5. Rung 3 GUEST — Tier 2-DB (requires guest-latch fix live first)
6. Rung 4 items — each its own cycle, tiered per above

Each cycle writes its live-validation results back into its README per the standing rule.

## 8. Verification cross-reference (file:lines used to author this plan, all at HEAD 2026-07-30)

- house_state.py:22-33 (enum), :36-60 (transitions)
- manager.py:143 (canonical machine on CM)
- presence.py:906 (`StateInferenceEngine.infer`)
- security.py:930-938 (NM pattern REUSED), :943-969 (unwired handler + complete mapping)
- energy.py:6815-6826 (dead `_house_state` read)
- hvac.py:280-289-adjacent boot-seed read at :687-688 (dead attribute)
- hvac.py:275, 418-425 (observation_mode surface REUSED)
- hvac.py:621 (existing SIGNAL_HOUSE_STATE_CHANGED subscription — Bug Class #50 precedent)
- optimization.py:2380-2400 (dead `"night"` literal branch)
- const.py:1114 (`CONF_SECURITY_AUTO_FOLLOW` REUSED)
- config_flow.py:5724, 5803-5804 (auto-follow field surface REUSED)
- signals.py:12 (`SIGNAL_HOUSE_STATE_CHANGED`), :210 (payload dataclass)
- safety.py:679-680, 2010 (observation_mode idiom REUSED)
- binary_sensor.py:2165 (observation_mode read pattern REUSED)

## 9. Not-in-scope explicitly

- Rung 1 dead-wire fixes (parallel cycle).
- Rung-2c actuator work (deferred sub-cycle with its own observation switch).
- Any change to Safety coordinator.
- Any new house-state VALUE (no ENTERTAINMENT etc.) — differentiation happens in behavior, not new enum members. If a
  new state is proposed later it gets its own scoping doc under the Institutional Context First rule.

---
**2026-08-01 operator dispositions:** Rung 2a stays OFF — "right mechanism but I consider security WIP; won't enable yet." Rungs 2b/2c/3/4 PARKED without a trigger — "may be chasing a problem I don't want to solve yet." Do not re-propose; wait for operator pull.
