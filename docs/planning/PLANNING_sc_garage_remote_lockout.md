# PLANNING — Security Coordinator: lock regime + garage remote lockout (+ gated operator auto-open trial)

**Card:** GARAGE-REMOTE-LOCKOUT-SCHEDULE-1 (operator picked option B, 2026-11-07; decisions recorded in the card field `operator_2026_11_07_decisions`).
**Rev:** 4 (2026-11-07). Rev 1 = commit ea4bc6a8. Rev 2 = commit 5a9fb5ea (+ 2b691a77 kill switch, 7283f0aa Phase 2 answers). Rev 3 = commit da0ec039 (plan review 1 folded, table §14). Rev 4 folds every finding of plan review 2 (`docs/reviews/code-review/sc_garage_lockout_plan_review_2.md`, adversarial build-prediction, FIX-PLAN); see the findings → resolution table in §15. Where rev 4 text contradicts rev 3 text elsewhere in this file, **§6.1a / §6.3 / §15 win**.
**Tier:** Phase 1 (lock regime + lockout + optimizer cover veto) = Tier 2, operator-elevated to the Tier 2-DB three-review protocol. Phase 2 (auto-open) = **Tier 3**, its own release. See §11.
**Status:** plan rev 4. Review 2 asked for a single delta re-review pass (local edits, no re-scope) before Phase 1 build dispatch. No code written.

Operator intent (unchanged): the opener "remote lockout" stops the outside keypad and car remotes being guessed or bypassed. "3 AM entries from red eyes. Don't want family to be locked out." 2026-11-07: "Separate arming from locks: arming = security system + alarms; locks = a reasonable locking regime that does not need the alarm armed." And: on a fast (vehicular) approach by the operator, release the lockout and open the garage, as an operator-only trial behind its own toggle.

Mandatory reads done for rev 4 (planner, 2026-11-07): `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` read completely again (849 lines, §10 ledger through #29) and `SENSOR_FLEET_CLASSES.md` read completely. No ledger claim is re-asserted. Rev 4 adds no new presence claim; its one new presence fact (the `SIGNAL_HOUSE_STATE_CHANGED` payload carries no `source` key, §6.1a M1) is a code fact about the existing dispatch, cited, not a doc correction.

Mandatory reads done for rev 3: `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (complete, all 835 lines, including the §10 corrections ledger) and `docs/architecture/SENSOR_FLEET_CLASSES.md` (complete). No ledger claim is re-asserted. Ledger items honoured: #13 (Bermuda `home` with `area: null` is stale), #23 (location in no-room branches comes from `person.<x>.state`), #26 (a frozen GPS `home` gives no arrival edge), #27 (a dead BLE fleet reads `not_home`). Rev 3 adds ledger entry #29 to that doc (GUEST → SLEEP, §4.2 below). HVAC is not touched.

---

## 1. Institutional context verified

### 1.1 Live facts

| Fact | Value | Read |
|---|---|---|
| Lockout entities | `lock.konnected_f0f5bd523b00_lock` (Garage A, Konnected blaQ); `lock.ratgdov25i_dbfe2a_lock_remotes` (Garage B, ratgdo 2.5i). `locked` = lockout ON. | rev 1 |
| Doors | `cover.konnected_f0f5bd523b00_garage_door` (A), `cover.ratgdov25i_dbfe2a_door` (B). **Both report `device_class: garage` in state attributes (verified live 2026-11-07, plan review 2 §"Q12")**, so `is_security_owned_cover` returns True on its first branch (`cover_ownership.py:111-112` on develop; review 2 cited 117-118; the file is at the integration root, not under `domain_coordinators/`). D0 Q12 is answered; P2-A's device-class half passes. Residual: a future device-class change or a state-less window, closed by the configured-list leg (§6.3, H2). Both lockouts read `unlocked` at the same read. | review 2, 2026-11-07 |
| SC config (CM entry) | `security_lock_entities = [lock.doorlock_kwikset_zwave_frontentry]`; `security_garage_entities = [both covers]`; `security_lock_check_interval = 60`; `security_auto_follow = false`; armed `disarmed`; observation off | rev 1 |
| CM sleep window | 22 → 06. Presence's inference engine reads the SAME CM keys (`__init__.py:3733-3744`, `cm_config.get(CONF_SLEEP_START_HOUR / CONF_SLEEP_END_HOUR)`, ctor defaults 23 / 6 only when unset, `const.py:3391-3392`). | rev 1 + rev 3 code read |
| HA zones | only `zone.home`, radius 150 m. `zone.home_approach` not yet created (operator answer Q-A2). | rev 1 |
| **HA proximity (NEW, created 2026-11-07)** | core proximity entry `01M6VGHPVWX72KF6ENND5HY309`, zone `zone.home`, tracking `person.oji_udezue`, `person.ezinne`, `person.ziri`, `person.jaya`. It exposes **sensor** entities, no `proximity.*` entity: `sensor.madronehaos_<person>_distance` (unit ft), `sensor.madronehaos_<person>_direction_of_travel`, `sensor.madronehaos_nearest_device`, `sensor.madronehaos_nearest_distance`, `sensor.madronehaos_nearest_direction_of_travel`. At creation Jaya and Ziri read `unknown` (Jaya is BLE-only, no GPS). Recorder history starts 2026-11-07. | orchestrator, 2026-11-07 |
| Persons | `person.oji_udezue` (app GPS + BLE IRK + bermuda), `person.ezinne`, `person.ziri` (single tracker), `person.jaya` (BLE only), `person.wall_kiosk` (no trackers, excluded) | rev 1 |
| Car | `lock.2025_cx_90_phev_preferred_lock` exists; car `device_tracker` UNKNOWN (D0 Q8). | rev 1 |
| Guest | A guest is staying while the operator travels (memory `project_operator_travel_2026_10_15`); GUEST nights are live, §4.2. | memory |

### 1.2 REUSE-or-BUILD per piece

Rev 1 table stands (house-state signal `security.py:1086`; `SIGNAL_PERSON_ARRIVING` handler `:2107`; geofence listener `:1987-2048`; `ServiceCallAction` via `evaluate()` `:801-833`; observation gate `:825-831`; decision/activity log `:1399-1430`; policy record `:1434-1457`; compliance read-back `:1804-1813`; unavailable dedup `:1735-1752`; hazard egress `:2051-2104`; optimizer veto `honor_optimizer_intent` `:1880-1912`). Rev 2 + rev 3 pieces:

| Piece | Verdict | Evidence |
|---|---|---|
| Lock-regime component | **NEW** (small module `security_lock_regime.py`) | No lock-policy owner: door-lock writes are spread over the sweep `_evaluate_lock_check` (`security.py:1678`), lockdown `_generate_lockdown_actions` (`:1642`, callers `:1043`, `:1578`) and hazard egress (`:2084`). |
| House-state feed | EXTEND `_on_house_state_changed_signal` (`security.py:1086`) | Returns before queueing when auto-follow is off (`:1104-1105`). The regime feed goes BEFORE that return; the arming path after it is byte-identical. |
| Person listener for the regime | **NEW, the regime's own** `async_track_state_change_event` on the resolved resident ids (rev 3, M1) | The existing `_setup_geofence_listener` snapshots `hass.states.async_all("person")` once at setup and silently returns when empty (`security.py:1989-1995`); `manifest.json` lists no `person` dependency (only http, frontend, logbook). It also returns on DISARMED (`:2015`) and on `old_state is None` (`:2020`). The regime does not share it; the sanction-checker path is untouched. |
| Arrival signal (P2) | EXTEND `_handle_person_arriving_signal` | Regime dispatch placed ABOVE both early returns `not self._enabled` (`security.py:2113`) and observation (`:2115`) (rev 3, L3). |
| House state read at boot | REUSE `PresenceCoordinator.house_state` property (`presence.py:1992`) | For the H1 boot rebuild. Override survives restart (`house_state.py:46`, `HOUSE_STATE_OVERRIDE_SURVIVES_RESTART`). |
| Vacation detection | REUSE `HouseState.VACATION` | `house_state.py:67`; VACATION → ARRIVING / AWAY only (`house_state.py:122-125`); manual. |
| Release write path | REUSE the hazard-egress direct-call pattern (`security.py:2084-2091`, `hass.services.async_call("lock","unlock",...)` in a created task) | Release must not be suppressed by `evaluate()`'s observation return (`:825-831`) or depend on the manager batch skipping disabled coordinators (`manager.py:971`). See §6.1. |
| Engage write path | REUSE `ServiceCallAction` returned from `evaluate()`, NEW intent source `lock_regime` with its own `evaluate()` branch | `evaluate()` routes `house_state_change` only when auto-follow is on (`security.py:815`); the new branch is unconditional on auto-follow. Observation suppresses engage (would-engage logged). |
| SC disable edge | **REVISED rev 4 (C1):** EXTEND `SecurityCoordinator.async_teardown` (`security.py:841`) with a disable-aware release | Rev 3's setter override is **withdrawn**: `manager.async_set_coordinator_enabled` (`manager.py:1249`) has no caller in `custom_components/` or `quality/` (grep: only its `def`). The real disable path is `switch.ura_security_coordinator_enabled` = `CoordinatorEnabledSwitch(coordinator_id="security", conf_key=CONF_SECURITY_ENABLED)` (`switch.py:259-268`), whose `async_turn_off` writes `security_coordinator_enabled: False` to the CM entry options and then reloads the integration entry (`switch.py:753-761`) → `async_teardown`, and on re-setup SC is not constructed. See §6.1a C1. |
| SC observation-ON edge | not needed (rev 3, H2b) | The observation switch sets a plain attribute (`switch.py:3467-3472`, `security.py:575`); no edge hook exists. Rev 3 solves H2b by making release writes observation-independent instead of adding a hook. |
| Kill switch / Phase 2 switches | REUSE the options-backed switch pattern (`_IntegrationOptionsSwitch`, `switch.py:558`; CM keys added to `OPTIONS_RELOAD_SUPPRESS_KEYS`, `__init__.py:7477`) | No RestoreEntity, so the value comes from entry options at setup and "restored `unavailable`" cannot occur (rev 3, L4). |
| Approach signal (P5, A2) | REUSE HA core proximity **sensors** (`sensor.madronehaos_<person>_distance`, `_direction_of_travel`) | Exists since 2026-11-07 (§1.1). No URA code reads proximity today (grep `proximity\.\|direction_of_travel` over the integration: 0 code hits). Replaces rev 2's single `proximity.*` entity field (M4). |
| Approach zone | OPTIONAL (demoted, rev 3, M3) | Proximity distance gives the same "within 1.5 km" fact for any zone state semantics; the zone is kept only as an optional extra edge. |
| Optimizer cover block (rev 4, H2) | **Layer 1 (primary): EXTEND the optimizer's own L2+ device dispatch** (`optimization.py` dispatch method around `:4868-4905`) with a DISALLOW of the same shape as the `egress_paused` block (`:4880-4903`, outcome `OPTIMIZER_OUTCOME_DISALLOWED`), using `_read_cm_config()` (`optimization.py:4314`) for the configured garage list. **Layer 2: EXTEND `honor_optimizer_intent`** (`security.py:1880`). Both use REUSE `cover_ownership.is_security_owned_cover` (`cover_ownership.py:82`) OR membership in `CONF_SECURITY_GARAGE_ENTITIES` (`const.py:3407`; SC holds it as `self._garage_entities`, `security.py:560`). See §6.3. | Rev 3 row below kept for history. |
| Optimizer cover veto (rev 3) | EXTEND `honor_optimizer_intent` (`security.py:1880-1912`) with REUSE `cover_ownership.is_security_owned_cover` (`cover_ownership.py:82`) | Today it vetoes only `lock.*` (`:1903-1905`) and `alarm_control_panel.*` (`:1907-1909`) and ACKs `cover.*`; `OPTIMIZER_ALLOWED_DOMAINS_DEVICE` includes `cover` (`const.py:4364-4366`); dispatch calls the service directly (`optimization.py:4989`). H3. |
| Garage open service | **NEW writer** `cover.open_cover` (Phase 2 only) | The only `open_cover` callers in `domain_coordinators/` are `hvac_covers.py` (blinds, garage excluded via `cover_ownership`); `automation.py` room covers also filter via `cover_ownership` (`automation.py:31-32`, `:1146`). |
| Auto-open shadow log / NM | REUSE `decision_logger.log_decision` + `activity_logger.log` (`security.py:1399-1430`); NM path (`:1377-1394`) | No new table. NM companion actions are ACK / STATUS / SILENCE only (`notification_manager.py:3373-3400`); no new action (M7). |

Greps run (rev 3, on top of rev 1/2): `sed`/`grep` reads of `security.py` at 700-712, 800-835, 1080-1110, 1640-1725, 1880-1912, 1985-2125; `grep -n "enabled.setter\|_cancel_listeners" base.py`; `manager.py:965-975, 1270-1290, 45-52, 936-946`; `const.py:4297-4300, 4360-4368, 3388-3392`; `grep -n "def \|garage\|device_class" cover_ownership.py`; `grep -n "honor\|veto" optimization.py`; `optimization.py:4980-4995`; `notification_manager.py:3370-3402`; `manifest.json` dependencies; `house_state.py:100-125, 210-240`; `presence.py:1370-1450, 1992, 1506-1508`; `__init__.py:3725-3745`; `switch.py:100-160, 555-575, 3422-3500`; `grep -n "observation_mode" security.py`; kanban grep for the three cards below.

**Card state (kanban grep, 2026-11-07):** `SECURITY-LOCK-SWEEP-RETRY-CAP-1` exists (`kanban.data.yaml:33601`, status `review`, branch `fix/security-lock-sweep-retry-cap`, changes `_evaluate_lock_check`). `SC-SWEEP-CLOSES-OPEN-GARAGE-1`, `SC-LOCK-REGIME-DOOR-LOCKS-1` and `SC-ARMING-ALARM-ONLY-1` are named in this plan but **do not exist on the board yet**; they must be minted (adjacency sweep first) before Phase 1 build dispatch. This revision does not edit the board.

### 1.3 Config-First check

- **Phase 1:** no setting does it (rev 1 §1.3). HA automation (option A) would; the operator chose B.
- **Phase 2:** the HA proximity entry (now exists) is the approach source; the approach zone becomes optional. A plain HA automation could do auto-open; rejected because the shadow period, one-open-per-arrival bookkeeping and audit trail are the safety case.
- **H3 (optimizer):** a config route exists today: keep optimizer autonomy at shadow (default, `const.py:4299`). It is not a fix, because L2 is a legal setting; the code veto stays.

---

## 2. Marginal-benefit decomposition

### 2.1 Phase 1 (B vs A) — unchanged from rev 1

B's margin over a three-trigger HA automation is thin in behaviour and real in observability and failure handling (decision log, observation mode, read-back, NM on failure, hazard release). Built at its smallest: edge-triggered, no periodic enforcement, no DB. Rev 3 adds the H1 boot rebuild, the H2 disable-edge release and the H3 optimizer veto: each is a few lines and closes a path to "family locked out" or "door opened by a second writer".

### 2.2 Phase 2: auto-open vs release-only

**Release-only already gives the operator at 3 AM:** the lockout is released on arrival, so the car remote works.

**Auto-open adds:** not pressing the remote, and the door up a few seconds earlier. On a phone-GPS arrival, seconds, a few times a week.

**Risk ingredients:** (1) a new writer that moves a barrier OPEN; (2) dependence on a phone's GPS stream; (3) inferred intent from noisy samples; (4) a rare-fire path; (5) restart / timing seams; and, found by plan review 1, (6) a pre-existing sweep that will remote-close an open garage on a fixed timer (H4), so an auto-open creates a remote-close hazard unless that sweep is fixed first.

**Verdict.** On margins, release-only wins. The operator asked for the trial, so it is built: behind its own toggle (default OFF), only after D0 passes, shadow first with a numeric exit bar, as a separate Tier-3 release, and only after its prerequisites (§8, Phase 2 prerequisites P2-A and P2-B). If D0 or shadow fails, Phase 2 parks and Phase 1 still delivers the goal.

---

## 3. Architecture: separate arming from locks

### 3.1 The split

- **Arming** = the alarm posture (`ArmedState`, `handle_arm` / `handle_disarm`, auto-follow map `_HOUSE_STATE_TO_ARMED` `security.py:180-186`, sanction checker, alerts).
- **Lock regime** = what should be locked or held, keyed on house state and arrivals, independent of the alarm. Module `domain_coordinators/security_lock_regime.py`, class `LockRegimeController`, owned by `SecurityCoordinator`. This cycle it owns one policy: **garage remote lockouts**.

### 3.2 What moves, what stays, what is carded

| Item | This cycle | Why |
|---|---|---|
| Garage lockout policy | **NEW, in the regime** | The goal. |
| House-state input to locks | **Moves**: fed before the auto-follow return (`security.py:1104`) | Lock behaviour must not depend on `security_auto_follow`. |
| Person-arrival input to locks | **Moves**: the regime's own listener (not the shared geofence listener) | M1; also escapes `:2015` (DISARMED) and `:2020` (`old_state is None`). |
| Arrival signal input | **Moves**: regime dispatch above `:2113` / `:2115` | L3. |
| Arming map, auto-follow, `handle_arm/disarm`, sanction checker, geofence listener | **Stays**, byte-identical | Alarm concern. |
| Periodic sweep `_evaluate_lock_check` | **Stays** this cycle; not edited by Phase 1 | Card `SC-LOCK-REGIME-DOOR-LOCKS-1` (to mint). Collision with `SECURITY-LOCK-SWEEP-RETRY-CAP-1`: see §8 sequencing (M8). |
| Sweep's garage auto-close (`security.py:1705-1723`) | Phase 1: stays. **Phase 2: must be fixed first** (prerequisite P2-B, card `SC-SWEEP-CLOSES-OPEN-GARAGE-1`, to mint) | H4. |
| Optimizer `cover.*` on SC-owned covers | **Vetoed in Phase 1** (D4b) | H3. Pre-existing hole that already lets the optimizer move a garage door today; three lines; shipping it with Phase 1 rather than waiting for Phase 2. |
| Lockdown on alert | Stays (lockouts not added, non-goal) | — |
| Hazard egress | **Extended**: also releases lockouts, placed before the `:2059` observation return | Life safety; §6.1. |
| `ArmedState` weak | Carded `SC-ARMING-ALARM-ONLY-1` (to mint) | Out of scope. |

### 3.3 Lockouts stay out of the sweeps

Lockout entities live in their own CONF list and are never in `security_lock_entities` (sweep and lockdown iterate only `_lock_entities`, `security.py:1648`, `:1685`). The options validator rejects overlap. Both lockouts are `lock.*`, so the optimizer veto already blocks them (`security.py:1903-1905`).

---

## 4. Producer and consumer checks

### 4.1 "A resident is arriving" (release, Phase 1)

| # | Producer | Mechanics (rev 3) | Role |
|---|---|---|---|
| P1 | `person.<x>` → `home` | Regime's own listener on the resolved resident ids. Arrival = new state `home` from any of `not_home`, `unknown`, `unavailable`, or a named non-home zone. `old_state is None` (entity added after a restart) is NOT an arrival edge; the boot rule (§6.1) covers it. A person whose GPS stayed frozen `home` produces no edge (ledger #26 shape); only P2 or P5 catches that. | Lead |
| P2 | `SIGNAL_PERSON_ARRIVING` | Gated by `person_coordinator._pre_arrival_enabled` (`person_coordinator.py:209`, `:1111`) and by BLE resolving a room, so it arrives late. Suppressed under Presence observation (`switch.py:3512-3517`, `presence.py:8512-8518`). | Corroborator, not the lead (L2) |
| P3 | Geofence via Presence | Suppressed under Presence observation | Corroborator |
| P4 | Camera face | Sparse | Corroborator |
| P5 | Proximity distance crossing | `sensor.madronehaos_<person>_distance` goes from > `GARAGE_LOCKOUT_APPROACH_RADIUS_M` to ≤ it. Unit read from the entity's `unit_of_measurement` and converted to metres (the live unit is ft); unknown unit, `unknown` or `unavailable` = no signal. Configured per resident in `CONF_SECURITY_LOCKOUT_DISTANCE_SENSORS`. Optional extra edge: if `CONF_SECURITY_LOCKOUT_APPROACH_ZONE` is set and the zone is non-passive, `person.<x>` → that zone name is also P5. Jaya has no GPS, so P5 never fires for her; Ziri's coverage is checked by D0. | Early release |

Release on the earliest of P1-P5 for any configured resident. Recovery path if all fail: the opener's own app / HA app (whether HA `open_cover` works with the lockout ON is a D5b check, M5).

Consumer: `LockRegimeController` only (trust: release).

### 4.2 House state

SLEEP engages. VACATION engages. AWAY does not engage (operator). ARRIVING releases (rev 3, house-level arrival).

**GUEST nights (M2, verified, code wins).** `VALID_TRANSITIONS[GUEST]` = {HOME_DAY, HOME_EVENING, HOME_NIGHT, AWAY} (`house_state.py:116-121`); `can_transition` rejects any target outside the table (`house_state.py:219-221`). In sleep hours `infer()` proposes SLEEP from any state other than SLEEP / WAKING (`presence.py:1404-1408`), so from GUEST with the gate still armed that proposal is rejected every tick and the house stays GUEST all night. Once the gate clears, the GUEST exit runs before the sleep branch (`presence.py:1399-1401`) and goes GUEST → HOME_NIGHT, then SLEEP on a later tick (this is what v5.16.0 shipped, `README_v5.16.0.md:12-14`). The presence doc's "GUEST → SLEEP transition had been missing" was wrong; corrected in this pass (presence doc §7 + ledger #29).

**Lockout behaviour on a guest night: OPEN, operator decision required before Phase 1 build (rev 4).** The operator disputes the rev 3 reading ("I don't think this is true"). The code reading is re-verified (orchestrator + planner, 2026-11-07): `VALID_TRANSITIONS[GUEST]` has no SLEEP (`house_state.py:116-121`); the GUEST exit fires only when `guest_gate_armed` is False (`presence.py:1399-1401`); the sleep branch's SLEEP proposal (`presence.py:1404-1408`) is rejected by `can_transition` while the state is GUEST. It cannot be checked empirically: the recorder holds no GUEST episode in the last 7 days. So, as the code stands, a night on which the guest gate stays armed reads GUEST until morning and a SLEEP-keyed lockout does not engage. This is no longer recorded as a settled non-goal.

| Option | What | Cost / risk |
|---|---|---|
| **(a)** Lockout engages on GUEST during sleep hours | Regime-only. New engage trigger: house reads GUEST inside the CM sleep window (`CONF_SLEEP_START_HOUR` → `CONF_SLEEP_END_HOUR`, same keys Presence reads, `__init__.py:3733-3744`), fired on either edge: the GUEST edge arriving inside the window, or a regime clock at `sleep_start_hour` while the house already reads GUEST. `reason = guest_night`, released like `sleep` (wake, override, ARRIVING, backstop, arrival, GUEST exit to HOME_*). Knob `CONF_SECURITY_LOCKOUT_ON_GUEST_NIGHT` (rung 3 options-backed switch). | Adds one clock-driven engage (a new time seam in the regime, though only in the safe-to-suppress engage direction). A guest who goes out at night has no arrival signal and finds the remotes locked; the front door and keypad lock are unaffected. INV-6 changes to "AWAY inert; GUEST engages only inside the sleep window with the toggle ON". |
| **(b)** Add a GUEST → SLEEP edge in Presence | A change to `house_state.py` `VALID_TRANSITIONS` plus the presence inference, own card (to mint, e.g. `PRESENCE-GUEST-TO-SLEEP-EDGE-1`) and own cycle | Every SLEEP consumer changes behaviour on guest nights (HVAC presets and the override arrester, fans, lighting, security arming map, EVSE, battery; §1 consumer table of the presence doc). Regression-prone, cross-coordinator, Tier 2-DB at least. Fixes the lockout as a side effect. |

**Planner recommendation: (a), toggle default ON**, because it puts the fix where the need is (the lockout) without changing what SLEEP means for HVAC, fans and the rest; (b) is a much larger blast radius justified only if other SLEEP consumers are also wrong on guest nights, which is a separate question for its own card. If the operator picks (b), Phase 1 ships with GUEST inert and gains the behaviour when (b) lands. Until the operator answers, the builder must not hard-code either: tests `test_guest_night_does_not_engage` / `test_guest_clears_then_sleep_engages` stand for the GUEST-inert baseline, and option (a) adds `test_guest_in_sleep_window_engages_when_toggle_on`, `test_guest_already_set_at_sleep_start_engages_by_clock`, `test_guest_night_toggle_off_inert`, `test_guest_exit_to_home_releases_guest_night`.

**Sleep window source (M9).** The regime reads `CONF_SLEEP_END_HOUR` from the CM entry exactly as Presence does (`__init__.py:3739-3744`: `cm_config.get(CONF_SLEEP_END_HOUR, merged_config.get(..., DEFAULT_SLEEP_END_HOUR))`). Both read one key, so their agreement is structural, not coincidental; the presence doc's "23 → 06" is the ctor default (`presence.py:1055-1056`). SLEEP onset is not a regime clock (the regime engages on the SLEEP edge). Test with non-default values (`sleep_end_hour = 5`, backstop 0) and with the CM key unset (`test_backstop_reads_cm_sleep_end_hour`, `test_backstop_default_when_cm_unset`).

### 4.3 Lockout entity state — state on the opener; survives restart UNVERIFIED (D0 Q10).

### 4.4 Operator fast approach (Phase 2) — PRODUCER CHECK

| # | Signal | Mechanics | Weakness |
|---|---|---|---|
| A1 | Approach-zone edge | Optional. Non-passive zone only (a passive zone never becomes a person's state; whether a passive zone's entity state or any event reflects a person inside it is UNVERIFIED, D0 Q2). | iOS region timing; non-passive side effects (rev 2 §4.4) |
| A2 | Proximity sensors `sensor.madronehaos_oji_udezue_distance` + `_direction_of_travel` (`towards` / `away_from` / `stationary` / `arrived`) | Two entities, configured as `CONF_SECURITY_AUTO_OPEN_DISTANCE_SENSOR` and `CONF_SECURITY_AUTO_OPEN_DIRECTION_SENSOR` (M4). Units converted as in P5. | Only as fresh as the fixes; update cadence measured by shadow (history starts 2026-11-07) |
| A3 | Phone `device_tracker` attributes (`latitude`, `longitude`, `gps_accuracy`, `speed`, `source_type`, `last_updated`) | Raw fixes; D0 recomputes distance by haversine against `zone.home`'s lat/lon | `speed` on iOS UNVERIFIED |
| A4 | CX-90 telematics | Corroborator at best | latency |
| A5 | Bermuda / BLE garage-side scanner | Corroborator (ledger #13 applies) | late |
| A6 | `zone.home` enter (150 m) | person state edge | late (~10-20 s) |

**Derived value:** `fast_approach(arrival_episode)`; arithmetic chosen by D0.

**Approach zone:** demoted to optional (M3). The proximity distance sensor gives the 1.5 km fact whether or not the zone exists. Operator answer Q-A2 (create it passive) stands as harmless; D0 Q2 records whether it produces any signal, and A1 is used only if it does.

**Consumers:** the auto-open decision (trust: OPEN) and P5 early release. Display: shadow rows and diagnostics.

---

## 5. Falsifiable invariants

### 5.1 Invariants

- **INV-1 (one garage-raising writer, integration-wide; rev 3, H3):** In the whole integration, the only reachable call that can move either garage cover up (`cover.open_cover`, `cover.toggle`, `cover.set_cover_position`, `cover.stop_cover` excluded) is `AutoOpenController._fire_open()`. Paths that must not: the lock regime; the sweep, lockdown and hazard paths (`security.py`); room covers (`automation.py`, filtered by `cover_ownership`); `hvac_covers.py` (filtered via `_is_garage_cover` → `cover_ownership`); the optimizer (vetoed by D4b); NM companion actions (none exist for covers). **Depends on** both covers reading `device_class: garage` (D0 Q12, **verified live 2026-11-07: both `garage`**); if either ever does not, INV-1 is false through `automation.py` / `hvac_covers.py` (those two filters read device class only) and the fix is the operator setting the device class in HA (config-first). The optimizer path no longer depends on device class or on SC being alive (rev 4 H2: the optimizer's own dispatch blocks any cover in `security_garage_entities` as well as any garage/gate device class). **Outside URA's control:** the opener's own wall button, its own app, and opener-side automations (Garage B moved with no HA call on 2026-10-11 19:07, card HVAC-GARAGE-GUARD-STAGED-SUNSET-1). Falsify: any other reachable call path to a cover-raising service on either garage cover.
- **INV-1A (auto-open is fully gated):** `_fire_open()` issues `cover.open_cover` on door D only if ALL hold at fire time, re-checked after the last `await`: auto-open toggle ON; SC enabled and not in observation mode; shadow switch OFF; arriving person in the allowlist; `fast_approach` true for a fresh episode; that episode has not produced an open; D reads `closed`; **no active security alert (`_active_alert`, `security.py:584`, set at `:1025`, `:1549`) and no lockdown action issued within `AUTO_OPEN_POST_LOCKDOWN_BLOCK_MIN`** (rev 3, M6); house not VACATION unless the arriving person is the operator; house not SLEEP unless the sleep sub-toggle is ON; operator not already reading home past the debounce; **the sweep hold-off for D is armable** (P2-B landed). **Rev 4 (M5): "once per episode" holds across restart and reload**: no `_fire_open()` for door D while `now − last_open_at[D] < AUTO_OPEN_EPISODE_MAX_S`, where `last_open_at[D]` is persisted (§6.2a), and no open at all within `AUTO_OPEN_EPISODE_MAX_S` of controller setup. Falsify: any reachable state in which an open is issued with one of these false, or two opens for one episode, including an episode that spans a reload or restart.
- **INV-1B (no remote close by new code, and no close of a URA-opened door):** No code added by this cycle calls `cover.close_cover` on a garage. After P2-B, the pre-existing sweep issues no `cover.close_cover` on door D within `AUTO_OPEN_SWEEP_HOLDOFF_S` of an auto-open of D (H4). Falsify: a sweep tick inside the hold-off that emits a close on D.
- **INV-2 (family release; rev 3, H2):** While the lockout feature is enabled and SC is enabled, for any configured resident R, the regime issues `lock.unlock` to every available lockout reading `locked` within `GARAGE_LOCKOUT_RELEASE_MAX_S` (5 s) of the first arrival input for R (P1-P5), regardless of who engaged it **and regardless of SC observation mode** (release writes are observation-independent, §6.1). Measured from the triggering event's timestamp to the `hass.services.async_call` invocation (L6), not from an intent being queued. In addition: SC teardown while the CM options say SC should not run (the real disable path, `switch.py:753-761`; rev 4 C1) and the kill switch ON → OFF edge each release once. **Rev 4 (H1): no `lock.lock` from the regime is issued after a release unless a new engage trigger occurred after that release** (generation check at `evaluate()` time, §6.1a). Falsify: any reachable state (SLEEP, VACATION, mid-debounce, re-engage timer pending, an engage intent queued in the 100 ms batch, after restart, SC observation ON, auto-open toggle in any position) in which an arrival input does not produce the unlock, or in which a lock lands after it without a newer engage trigger. Auto-open never weakens INV-2: the release happens on the same edge whether or not an open follows, and an auto-open exception must not skip it.
- **INV-3 (no re-engage on top of a resident):** rev 1 INV-3, tightened in rev 4 (M2): a re-engage fires only when every resident in the release's `releasing_set` is *settled* (§6.1a M2). Falsify: Ezinne crosses 1500 m at 02:00, is still at 800 m at 02:15 (`person` not `home`); a lock at 02:15 breaks INV-3.
- **INV-4 (morning; rev 3, H1):** a lockout engaged for SLEEP is released at the earliest of SLEEP → WAKING, an override to HOME_*, ARRIVING, or 07:00 (`sleep_end_hour` + `GARAGE_LOCKOUT_MORNING_BACKSTOP_MIN`) — **including when HA restarted after the engage**. VACATION-engaged lockouts are not released by the clock or by wake. Falsify: engage at 22:30 SLEEP, restart at 02:00, SLEEP → WAKING at 06:40 (must release), or no wake (must release at 07:00); and VACATION at 07:00 across a restart (must stay locked).
- **INV-5 (edge-only):** rev 1, made explicit in rev 4 (M1, L1): the regime engages only on a SLEEP / VACATION edge that arrives (a) after the boot window (`GARAGE_LOCKOUT_BOOT_RECHECK_S` after SC setup) and (b) while the kill switch is ON. Turning the kill switch OFF → ON while the house already reads SLEEP does not engage (no catch-up); boot-time edges, including Presence's `boot_settle_override` replay, only rebuild `reason`. Falsify: VACATION override, operator unlocks the lockout at 14:00, restart at 15:00; any `lock.lock` before the next real SLEEP/VACATION edge breaks INV-5.
- **INV-6 (AWAY inert; GUEST pending the operator):** a transition into AWAY never engages a lockout. GUEST: inert under the current text; if the operator picks option (a) of §4.2, GUEST engages only inside the sleep window with `CONF_SECURITY_LOCKOUT_ON_GUEST_NIGHT` ON.

### 5.2 Fail-safe directions

- Lockout: **released.** Boot never engages. Release writes go direct and are not suppressed by SC observation. SC disable releases first. Kill switch OFF releases (operator 2026-11-07). Unavailable lockouts skipped with dedup; read-back after `GARAGE_LOCKOUT_READBACK_S` with `GARAGE_LOCKOUT_READBACK_RETRIES` (1) retry, then HIGH NM.
- Auto-open: **closed / no action.** Any doubt = no open; the release still happens.
- **Named residuals (accepted, stated in the README):**
  - **HA down at night (M5):** with HA or the network down, URA cannot release, and the lockout blocks remotes and keypad. Recovery: the front door key / keypad lock, or the opener's own app if it works without HA (D5b records which). This exists from the first night the feature is ON.
  - **SC disabled across a restart:** the disable edge already released, so a locked lockout here means a manual lock or a failed release (NM already sent). No URA release until SC is re-enabled.
  - **Presence observation ON (rev 4, L2):** no house-state edges, so no engage; an earlier engage releases only by backstop or arrival. Fail-safe direction.
  - **First 120 s after a restart (rev 4, M1):** a genuine SLEEP / VACATION edge there only rebuilds `reason`; engage waits for the next edge. Fail-safe direction.
  - **Phone in a moving car (Phase 2, rev 4, M6):** whoever holds the operator's phone in a moving car opens the garage once auto-open acts. Accepted for the trial; README states it.
  - **SC observation ON:** engage is suppressed (would-engage logged); release still runs. So observation mode can never strand a lockout, but it is not "zero writes" for this feature. The operator should know this (README).

---

## 6. Design

### 6.1 Lock regime — lockout policy (Phase 1)

State in memory: `reason: none | sleep | vacation | boot_unknown`, timer handles, `last_action`. `reason` is not persisted; it is rebuilt at boot (H1).

| Trigger | Condition | Action | Path |
|---|---|---|---|
| house_state → SLEEP | enabled | engage, reason=sleep | evaluate() (`lock_regime` branch) |
| house_state → VACATION | enabled | engage, reason=vacation | evaluate() |
| house_state → AWAY | — | nothing (INV-6). Covers SLEEP → AWAY (reason stays sleep: backstop and arrival still release) and VACATION → AWAY (reason stays vacation) (L1) | — |
| house_state → GUEST | — | nothing (INV-6, §4.2) | — |
| house_state SLEEP → WAKING | reason ∈ {sleep, boot_unknown} | release | direct |
| override → HOME_* from SLEEP | reason ∈ {sleep, boot_unknown} | release. SLEEP's valid targets are only WAKING and AWAY (`house_state.py:108-111`); HOME_* arrives only through `set_override`, which bypasses the table (`house_state.py:267-290`) (L1) | direct |
| house_state → ARRIVING | any reason | release; reason vacation → none | direct |
| clock `sleep_end_hour` + backstop | reason ∈ {sleep, boot_unknown} | release (never for vacation) | direct |
| resident arrival P1-P5 | any lockout reads `locked` | release (any engager); reason sleep and in the night window → schedule re-engage (INV-3); reason vacation → none, no re-engage | direct |
| re-engage timer | both doors closed, house SLEEP, before `sleep_end_hour` | engage, reason=sleep | evaluate() |
| safety hazard critical | `CONF_SECURITY_ON_HAZARD_UNLOCK_EGRESS` | release; placed before the `:2059` observation return | direct |
| kill switch ON → OFF | — | release once, then no lockout writes | direct |
| SC enabled True → False | any lockout reads `locked` | release once (setter override, before `_cancel_listeners`, `manager.py:1281-1283`) | direct |
| setup (boot) | any lockout reads `locked` | never engage. Recent-arrival rule (rev 1 §5) may release. Otherwise rebuild `reason` from `presence.house_state` (`presence.py:1992`): SLEEP → sleep, VACATION → vacation, anything else / presence missing / unknown → `boot_unknown`. Re-read once at `GARAGE_LOCKOUT_BOOT_RECHECK_S` after setup (house-state restore and boot settle may finish after SC setup; Presence does not dispatch a signal for an unchanged restored state): upgrade `boot_unknown` to sleep or vacation if the house now reads so. | — |
| setup (boot), resident ids | — | resolve `CONF_SECURITY_LOCKOUT_RESIDENTS`; subscribe by id (works before the entity exists); WARN once and expose `lock_regime_missing_residents` if any id has no state after boot recheck (M1) | — |

`boot_unknown` is treated as sleep for release (wake, backstop, arrival) and is never engaged by the regime. Cost: a vacation-locked lockout after a restart whose house state did not restore as VACATION would release at 07:00. That is the fail-safe direction, and VACATION is a manual override that survives restart (`house_state.py:46`), so it should be rare.

**Engage vs release paths.** Engage = `ServiceCallAction` from a new `evaluate()` branch for intent source `lock_regime` (not under the `:815` auto-follow condition), so observation mode and CM resolution apply. Release = direct `hass.services.async_call("lock", "unlock", ...)` in a created task, the hazard-egress pattern (`security.py:2084-2091`), followed by the regime's own read-back. Release writes are logged to the decision and activity logs with the trigger. Reason for the split: the two failure directions differ. A suppressed engage costs nothing; a suppressed release locks the family out. Observation mode, the 100 ms manager batch (`manager.py:50`, `:939-944`) and the disabled-coordinator skip (`manager.py:971`) can each suppress an `evaluate()` action, so release does not go through `evaluate()`.

**Kill switch open points (review §"Kill-switch semantics").** (1) The OFF-edge release goes direct (not through `evaluate()`), so SC observation does not suppress it. (2) The switch is options-backed (§1.2), so there is no RestoreEntity and no `unavailable` restore; at setup the value comes from the CM entry options, absent key = OFF (ship default). A boot with the switch OFF issues no writes (only an operator ON → OFF edge releases). Idempotent per entity; policy record `security.lock_regime.garage_lockout`.

### 6.1a Rev 4 amendments to §6.1 (plan review 2 + operator 2026-11-07) — these win over §6.1

**C1 — release on the real disable path.** The setter-override row in §6.1 ("SC enabled True → False") is withdrawn. Instead, `async_teardown` (`security.py:841`), **before** `_cancel_listeners()`, evaluates `coordinator_gate.coordinator_should_run(merged CM data+options, "security")` (`coordinator_gate.py:43`). If it reads False (the switch already wrote `security_coordinator_enabled: False` before reloading, `switch.py:755-758`; this also covers removal from the CM menu and an entitlement denial), the regime releases every lockout that reads `locked`: direct `lock.unlock` with `blocking=True`, bounded by `GARAGE_LOCKOUT_TEARDOWN_RELEASE_TIMEOUT_S`, logged to the decision/activity log with trigger `sc_disabled`; on timeout or error, a HIGH NM is attempted and teardown continues. If it reads True (restart, ordinary reload, options reload), teardown does not release (§5.2 restart semantics unchanged). No release is attempted when the kill switch is OFF (nothing of ours is engaged). The setter override is not built (it has no production caller and would only give a hollow anchor, Bug Class #62).
Tests: `test_sc_switch_off_releases_before_reload` (drive `CoordinatorEnabledSwitch.async_turn_off` for `coordinator_id="security"` with a fake `async_reload` that runs SC teardown; assert the recorded `lock.unlock` call happens and precedes the end of teardown; discriminates: a build that hooks the setter, or releases only on `_cancel_listeners`, records no unlock), `test_sc_teardown_restart_does_not_release` (options still say enabled → no unlock), `test_sc_teardown_release_timeout_does_not_block_unload`. Rev 3's `test_sc_disable_edge_releases` and `test_sc_teardown_does_not_release` are replaced by these.

**H1 — evaluate-time recheck with a release generation.** The regime holds an integer `release_gen`, incremented on every release action (arrival, wake, override, ARRIVING, backstop, hazard, kill-switch OFF, teardown release) **whether or not a write was needed** (a release with both lockouts already `unlocked` still bumps it; that is the race case). Each engage intent carries `gen = release_gen` at queue time and `trigger`. The `lock_regime` branch in `evaluate()` emits `lock.lock` only if, at evaluate time: kill switch ON; SC enabled and not shutting down; `intent.gen == release_gen`; house state still in the engage set for the intent's reason (SLEEP for sleep, VACATION for vacation, GUEST-in-window for guest_night if adopted); and, for a re-engage intent, the M2 settled condition. Otherwise no action and a decision-log row `engage_dropped_stale`. The re-engage timer queues its intent through the same path, so it inherits the check.
Tests: `test_engage_intent_dropped_if_release_after_queue` (queue SLEEP engage; arrival 50 ms later with both lockouts unlocked; run the batch; assert no `lock.lock`), `test_engage_intent_dropped_if_kill_switch_off_after_queue`, `test_engage_intent_dropped_if_house_left_sleep_before_batch`, `test_engage_lands_when_no_release_intervened` (guard against a check that drops everything).

**H3 — arrival de-duplication and timer hygiene.**
- (a) **Blip rule.** An arrival edge from `unknown`/`unavailable` to `home` counts only if the person's last *real* state (not `unknown`/`unavailable`) was not `home` and held for ≥ `GARAGE_LOCKOUT_BLIP_MIN_AWAY_MIN`. The regime keeps `last_real_state[person]` and its timestamp, updated on every real state; it is not persisted (after a restart there is no last real state, so a blip edge does not count; P5 proximity and the boot recent-arrival rule cover a real arrival in that window). Edges from `not_home` or a named zone to `home` count as before.
- (b) **Single release in flight per lockout episode.** Per lockout entity, `release_inflight_until`: while a release write or its read-back is pending, further release triggers bump `release_gen` and append themselves to `releasing_set` but issue no second `lock.unlock`. The first release's read-back decides retry / NM as in §5.2.
- (c) **One re-engage handle.** A single `reengage_unsub`; every arrival cancels it and reschedules from now. `releasing_set` accumulates every resident whose arrival contributed since the last engage, and is cleared on engage.
- (d) **Teardown cancels every regime timer**: backstop, boot recheck, re-engage, read-back, the guest-night clock (if adopted) and the resident add/remove trackers. Today's teardown cancels only the auto-follow debounce (`security.py:851-857`). The regime exposes `async_teardown()` called from SC teardown after the C1 release.
Tests: `test_unknown_blip_while_home_no_release`, `test_unavailable_blip_after_real_away_releases`, `test_multi_trigger_arrival_single_unlock` (P1 + P2 + P5 + ARRIVING within 2 s → exactly one `lock.unlock` per lockout, one read-back task, one re-engage handle), `test_reengage_superseded_by_second_arrival`, `test_teardown_cancels_regime_timers` (assert every handle is None and no callback fires after teardown with time advanced past each delay).

**M1 — boot edges never engage.** The `SIGNAL_HOUSE_STATE_CHANGED` payload is `{old_state, new_state, trigger, confidence}` only (`presence.py:8573-8581`); the `source="boot_settle_override"` argument (`presence.py:2588-2594`) is **not** in the payload, and its trigger is `override_set`, the same as a real override. So the regime cannot filter on `source`. Rule instead: any SLEEP / VACATION edge that arrives before `setup_time + GARAGE_LOCKOUT_BOOT_RECHECK_S` (120 s; Presence's boot settle times out at `BOOT_SETTLE_TIMEOUT_SECONDS = 60`, `const.py:4188`, so the replay falls inside the window when SC is set up first) only rebuilds `reason` and never engages. Covers the VACATION replay and the stale-restore first-inference SLEEP. Residual (named, fail-safe direction): a genuine SLEEP edge in the first 120 s after a restart does not engage until the next edge. Adding `source` to the payload is a Presence change and is not done here. Test: `test_boot_settle_override_vacation_does_not_engage`, `test_boot_window_sleep_edge_rebuilds_reason_only`, `test_sleep_edge_after_boot_window_engages`.

**M2 — "settled" for re-engage.** A resident R in `releasing_set` is settled when `person.R` reads `home`, or R's configured distance sensor reads numeric and > `GARAGE_LOCKOUT_APPROACH_RADIUS_M` again (turned back), or R's arrival is older than `AUTO_OPEN_EPISODE_MAX_S`-style bound `GARAGE_LOCKOUT_REENGAGE_MAX_WAIT_S` (new, rung 1, 3600 s; after that the re-engage is abandoned, not forced: the lockout stays released until the next SLEEP edge or the morning). Re-engage requires every member settled; if not, it re-checks once per `GARAGE_LOCKOUT_REENGAGE_DELAY_S` until the wait bound. Test: `test_reengage_waits_for_proximity_released_resident` (P5 release at 02:00, 800 m at 02:15 → no lock; `home` at 02:20 → lock after both doors closed), `test_reengage_abandoned_after_max_wait`.

**M3 — hazard placement, exactly.** Only the new lockout-release call goes between `if not self._enabled: return` (`security.py:2057-2058`) and `if self.observation_mode:` (`:2059`). The existing hazard config check and door-egress unlock loop stay after the observation return, unchanged. The disabled case is C1's job. Test: `test_hazard_under_observation_releases_lockouts_not_door_locks` (observation ON, hazard: assert `lock.unlock` on both lockouts and **no** call on `security_lock_entities`).

**M4 — proximity units and crossing rule.** Convert with HA's `homeassistant.util.unit_conversion.DistanceConverter` (class exists, `unit_conversion.py:296` in the pinned HA; builder confirms `DistanceConverter.convert(value, from_unit, UnitOfLength.METERS)` signature in the build) using the entity's `unit_of_measurement`; no hand-rolled factor. A unit the converter rejects = no signal. Crossing = previous value numeric and > R AND current numeric and ≤ R. The first numeric reading after `unknown`/`unavailable`, or after setup, is **not** a crossing (P1 `home` covers a phone that comes online inside the radius). D0 adds: read HA proximity's distance definition (to zone centre vs edge, 0 inside the zone; UNVERIFIED here) and state the bias against the haversine-to-centre recompute. Tests: `test_proximity_crossing_releases` uses R = 1500 m, previous 6000 ft, current **3000 ft** (914 m) → must release (a no-conversion build compares 3000 > 1500 and does not); `test_proximity_first_reading_after_unknown_not_a_crossing`; `test_proximity_unit_km_converted`.

**Dynamic resident set (operator 2026-11-07: "know across restarts and only pick up adds and subtractions … real time, not on restart").**
- Resident set = every `person.*` entity minus `CONF_SECURITY_LOCKOUT_EXCLUDED_PERSONS`.
- **Real time:** REUSE HA `async_track_state_added_domain(hass, "person", ...)` and `async_track_state_removed_domain(hass, "person", ...)` (`homeassistant/helpers/event.py:653`, `:711` in the pinned HA). An added `person.*` (not excluded) joins the set and its per-entity state listener is subscribed at once; a removed one leaves the set, its listener is cancelled, it leaves `releasing_set`, and it no longer counts as an arrival or blocks re-engage. Excluded-list edits arrive via options (already in-place apply if the key is in `OPTIONS_RELOAD_SUPPRESS_KEYS`, `__init__.py:7477`) and re-filter the set without reload.
- **Across restarts:** the resolved set is persisted in a `Store` (`universal_room_automation.lock_regime_residents`, delayed save only on change, same pattern as the BLE fleet-memory store, presence doc §3). At setup the regime subscribes by id to the union of the persisted set and the live `person` domain, so a resident whose `person` entity has not loaded yet still has a listener; after the boot recheck, ids in neither the live domain nor a later add are dropped and logged once (`lock_regime_missing_residents` attribute). Persisting is what lets "adds and subtractions" be reported as a diff at boot rather than as a fresh snapshot.
- `sensor` distance sensors stay a configured list (`CONF_SECURITY_LOCKOUT_DISTANCE_SENSORS`); a person without one simply has no P5.
- Tests: `test_person_added_at_runtime_releases_without_reload` (add `person.new` after setup, then `not_home` → `home` → unlock), `test_person_removed_at_runtime_stops_release` (remove `person.ziri`; a later state write for that id produces no unlock), `test_excluded_person_never_releases`, `test_resident_set_persisted_and_restored`, `test_persisted_resident_not_yet_loaded_still_subscribed`.
- **Same flaw in the existing SC geofence listener:** `_setup_geofence_listener` snapshots `hass.states.async_all("person")` once at setup and returns when empty (`security.py:1987-1995`), so the sanction checker misses persons added later and never subscribes if persons load after SC. It is on the arming path, which this cycle keeps byte-identical, so it is **carded, not fixed in-cycle**: mint `SC-GEOFENCE-PERSON-SNAPSHOT-1` (adjacency sweep first; Tier 1; fix = the same added/removed-domain trackers). Revisit in-cycle only if the reviewer finds the regime's helper can be shared at no cost to the byte-identical arming test.

**L1 / L2 / L3.** Kill switch OFF → ON mid-SLEEP: no engage (INV-5), test `test_kill_switch_on_mid_sleep_no_engage`. Presence observation suppresses `SIGNAL_HOUSE_STATE_CHANGED` (`presence.py:8518-8524`): no SLEEP/WAKING edges, so no engage, and a lockout engaged earlier releases only by backstop or arrival; listed in §5.2 residuals. `CONF_SECURITY_AUTO_OPEN_SHADOW`: the options-backed switch's default for that key is True and the test reads the switch entity (`test_shadow_switch_entity_absent_key_reads_on`), not the constant.

### 6.2 Auto-open (Phase 2) — `AutoOpenController` in `domain_coordinators/security_auto_open.py`

Separate module so INV-1 is checkable by file. Rev 2 §6.2 stands except as amended here.

**Arrival episode / decision / which door / sleep / vacation / audit / shadow / restart / kill:** rev 2 text stands, with A2 now reading the two proximity sensors (§4.4) and D0 choosing the arithmetic.

**Gates at fire time:** INV-1A (now includes the alert / lockdown gate, M6, and the sweep hold-off, H4). Release first; open only after the release read-back passed or the lockout already read unlocked.

**Sweep hold-off (needs P2-B).** On an auto-open of D the controller stamps `auto_opened_at[D]`; the sweep skips the garage-close for D while `now − auto_opened_at[D] < AUTO_OPEN_SWEEP_HOLDOFF_S`. The no-entry NM covers the door left open. This mechanism belongs to `SC-SWEEP-CLOSES-OPEN-GARAGE-1`, which may fix the sweep more broadly (e.g. occupancy-aware close); D6 needs at least the hold-off.

**Open-without-entry timer.** After an auto-open, no entry evidence (door → `closed`, a sensor in `CONF_SECURITY_AUTO_OPEN_ENTRY_EVIDENCE`, the operator's BLE resolving to an interior room) within `AUTO_OPEN_NO_ENTRY_S` (180) → **HIGH NM, text only, no action button** (M7): "Garage A was opened for your arrival 3 min ago and no entry was seen. Check the camera; close it from the HA app if needed." No close writer, no companion action. Whether the NM can carry a dashboard deep link is UNVERIFIED (NM's notification data fields were not read in this pass); if the builder confirms a URL field exists, a deep link may be added, otherwise text only. The text must not promise the door stays open beyond the sweep hold-off.

**Shadow NM:** `AUTO_OPEN_SHADOW_NM_ENABLED` (§7).

### 6.2a Rev 4 amendments to Phase 2 (review 2 M5, M6)

**M5 — episode state survives restart and reload.** `last_open_at[D]` (and the episode id that produced it) is persisted in a `Store` written immediately after `_fire_open()` issues the call (before the read-back), and loaded at controller setup. Gates at fire time add: `now − last_open_at[D] ≥ AUTO_OPEN_EPISODE_MAX_S`, and `now − controller_setup_time ≥ AUTO_OPEN_EPISODE_MAX_S` (boot blackout; shadow rows still log as `would_open_blocked_boot`). A Store load failure = treat as "opened just now" (blackout holds; fail-closed). Test: `test_no_second_open_across_reload_mid_episode` (open at T, reload at T+60 s, door closed at T+90 s, fresh fast fixes → no open), `test_store_load_failure_blocks_open`.

**M6 — named residual: whoever holds the operator's phone in a moving car opens the garage.** INV-1A has no physical corroborator (A4 CX-90 telematics is a corroborator at best, its latency unmeasured). Accepted for an operator-only trial; stated in §5.2, in the README, and in Phase 2 reviewer D's repro list. Revival trigger for a corroborator gate: D0/shadow shows the CX-90 tracker (or a Bermuda garage-side hit) arrives early enough to gate on.

### 6.3 Optimizer cover block (Phase 1, D4b) — rev 4 (H2), replaces rev 3 text

Rev 3's "any exception in the check → veto" cannot happen: `is_security_owned_cover` swallows every exception and returns False ("fail open", `cover_ownership.py:93`, guarded reads `:100`, `:117`, registry fallback `:124`), and a non-garage `device_class` is authoritative False (`:116`). And the SC veto is advisory: the optimizer dispatches unless a sibling pushed a veto inside the window (`await_veto`, `optimization.py:505-536`), so with SC disabled (C1 path: not constructed) or mid-reload nobody vetoes.

- **Owned predicate (one helper, NEW, in `cover_ownership.py`):** `is_security_owned_or_configured_cover(hass, entity_id, configured_garages)` = `entity_id in configured_garages` OR `is_security_owned_cover(hass, entity_id)`. The config leg is checked first, so a device-class change or a state-less, registry-less window cannot open the hole for a configured garage.
- **Layer 1 (primary, Phase 1):** in the optimizer's L2+ device dispatch, next to the `egress_paused` block (`optimization.py:4880-4903`), any `cover.*` target for which the predicate is True (configured list from `_read_cm_config().get(CONF_SECURITY_GARAGE_ENTITIES, [])`, `optimization.py:4314`) → `OPTIMIZER_OUTCOME_DISALLOWED`, activity row reason `security_owned_cover`, regardless of whether SC exists. A raise inside the predicate → DISALLOW (here the try/except is ours and can fail closed).
- **Layer 2 (defence in depth):** `honor_optimizer_intent` (`security.py:1880`) vetoes with `_last_veto_reason = "security_owned_cover"` on the same predicate with `self._garage_entities` (`security.py:560`).
- Tests (replace `test_optimizer_cover_ownership_error_vetoes`, which could only pass by making the helper raise, a branch production never takes): `test_optimizer_dispatch_disallows_garage_without_sc` (no SC registered, L2 `cover.open_cover` on a garage → DISALLOWED, no service call recorded), `test_optimizer_garage_disallowed_when_state_missing_and_registry_unavailable` (state absent, registry lookup failing, entity in `security_garage_entities` → DISALLOWED and SC veto), `test_optimizer_garage_disallowed_after_device_class_changed_to_door` (configured leg wins), `test_optimizer_cover_on_blind_acked` (non-garage, not configured → dispatched), `test_optimizer_cover_open_on_garage_vetoed` (Layer 2).

---

## 7. Knobs (every number)

| Knob | Default | Rung | Why / kill semantics |
|---|---|---|---|
| `CONF_SECURITY_GARAGE_LOCKOUT_ENABLED` | off at ship | 3 Switch `switch.ura_security_coordinator_garage_lockout`, options-backed (`_IntegrationOptionsSwitch` pattern, key in `OPTIONS_RELOAD_SUPPRESS_KEYS`) | Phase 1 kill; ON → OFF releases both lockouts once (direct, not observation-suppressed, unavailable skipped, read-back + retry, HIGH NM on failure), then no lockout writes. Operator 2026-11-07 'Release on off'. Absent key = OFF. |
| `CONF_SECURITY_LOCKOUT_ENTITIES` | the two lockouts | 2 (domain=lock) | Validator rejects overlap with `security_lock_entities` |
| ~~`CONF_SECURITY_LOCKOUT_RESIDENTS`~~ → `CONF_SECURITY_LOCKOUT_EXCLUDED_PERSONS` (rev 4, operator) | `[person.wall_kiosk]` | 2 (entity selector, domain=person, multiple) | The resident set is dynamic: every `person.*` minus this list, tracked in real time and persisted (§6.1a "Dynamic resident set"). Empty = every person is a resident. |
| `CONF_SECURITY_LOCKOUT_ON_GUEST_NIGHT` (only if operator picks §4.2 (a)) | ON | 3 Switch, options-backed | OFF = GUEST inert (rev 3 behaviour) |
| `CONF_SECURITY_LOCKOUT_DISTANCE_SENSORS` | the four `sensor.madronehaos_<person>_distance` | 2 (entity selector, domain=sensor, multiple) | P5 source; empty = no P5 |
| `GARAGE_LOCKOUT_APPROACH_RADIUS_M` | 1500 | 3 Number | P5 threshold; 0 = P5 off |
| `CONF_SECURITY_LOCKOUT_APPROACH_ZONE` | empty | 2 (domain=zone) | Optional extra P5 / A1 edge |
| `GARAGE_LOCKOUT_MORNING_BACKSTOP_MIN` | 60 (07:00) | 3 Number | 0 = release at `sleep_end_hour` |
| `GARAGE_LOCKOUT_REENGAGE_DELAY_S` | 900 | 3 Number | 0 = never re-engage after an arrival |
| `GARAGE_LOCKOUT_REENGAGE_MAX_WAIT_S` (rev 4, M2) | 3600 | 1 | Re-engage abandoned (not forced) if the releasing residents are not settled by then |
| `GARAGE_LOCKOUT_BOOT_ARRIVAL_WINDOW_S` | 600 | 1 | Restart safety |
| `GARAGE_LOCKOUT_BOOT_RECHECK_S` | 120 | 1 | H1 second read of house state after setup |
| `GARAGE_LOCKOUT_READBACK_S` | 20 | 1 | Protocol window |
| `GARAGE_LOCKOUT_READBACK_RETRIES` | 1 | 1 | L4; then HIGH NM |
| `GARAGE_LOCKOUT_RELEASE_MAX_S` | 5 | 1 | Test oracle (event → service call). **Not read by production code** (review 2 L4); no timeout may be wired to it. |
| `GARAGE_LOCKOUT_BLIP_MIN_AWAY_MIN` (rev 4, H3a) | 15 | 1 | An `unknown`/`unavailable` → `home` edge counts as an arrival only if the last real state before the blip was not `home` and had been so for ≥ this long. Same value and idea as `person_coordinator._min_away_minutes` (`person_coordinator.py:210`); a separate constant because that one is an instance attribute of another coordinator. 0 = every blip edge counts (rev 3 behaviour). |
| `GARAGE_LOCKOUT_TEARDOWN_RELEASE_TIMEOUT_S` (rev 4, C1) | 5 | 1 | Bound on the awaited unlock inside `async_teardown` so a dead opener cannot stall unload. |
| `CONF_SECURITY_AUTO_OPEN_ENABLED` | off | 3 Switch, options-backed | Phase 2 kill; OFF = no decisions |
| `CONF_SECURITY_AUTO_OPEN_SHADOW` | on (absent key = ON) | 3 Switch, options-backed | ON = decide + log, never act. Options-backed, so no `unavailable` restore; absent / unreadable = ON |
| `CONF_SECURITY_AUTO_OPEN_IN_SLEEP` | off | 3 Switch, options-backed | OFF = no act in SLEEP (shadow still logs) |
| `AUTO_OPEN_SHADOW_NM_ENABLED` | on during shadow | 3 Switch | L4; OFF = shadow decisions logged, not notified |
| `CONF_SECURITY_AUTO_OPEN_PERSONS` | `[person.oji_udezue]` | 2 | Allowlist; empty = inert |
| `CONF_SECURITY_AUTO_OPEN_COVER` | per D0 / Q-A1 | 2 | Single door |
| `CONF_SECURITY_AUTO_OPEN_DISTANCE_SENSOR` | `sensor.madronehaos_oji_udezue_distance` | 2 | A2 (M4) |
| `CONF_SECURITY_AUTO_OPEN_DIRECTION_SENSOR` | `sensor.madronehaos_oji_udezue_direction_of_travel` | 2 | A2 (M4) |
| `CONF_SECURITY_AUTO_OPEN_ENTRY_EVIDENCE` | empty | 2 (binary_sensor, multiple) | L4: garage / mudroom motion for the no-entry timer; empty = door-close + BLE only |
| `AUTO_OPEN_MIN_AWAY_MIN` | 15 | 1 | Matches `_min_away_minutes` |
| `AUTO_OPEN_MIN_SPEED_KMH` | 20 (D0 sets) | 1 | Safety discriminator, review-only |
| `AUTO_OPEN_MAX_GPS_ACCURACY_M` | 50 (D0 sets) | 1 | same |
| `AUTO_OPEN_MAX_FIX_AGE_S` | 60 (D0 sets) | 1 | same |
| `AUTO_OPEN_DEBOUNCE_S` | 90 (D0 sets) | 1 | same |
| `AUTO_OPEN_LEAD_S` | D0 sets | 1 | unused in the home-ring form |
| `AUTO_OPEN_POST_LOCKDOWN_BLOCK_MIN` | 30 | 1 | M6; 0 = only an active alert blocks |
| `AUTO_OPEN_SWEEP_HOLDOFF_S` | 900 | 1 | H4; must be ≥ `AUTO_OPEN_NO_ENTRY_S` (validated) |
| `AUTO_OPEN_EPISODE_MAX_S` | 900 | 1 | Episode bound |
| `AUTO_OPEN_EPISODE_CLOSE_S` | 120 | 1 | Episode close debounce |
| `AUTO_OPEN_NO_ENTRY_S` | 180 | 3 Number | 0 = no no-entry NM (not recommended) |

All anti-false-open discriminators are rung 1 on purpose. Removed: `CONF_SECURITY_LOCKOUT_ON_AWAY` (rev 2); `CONF_SECURITY_AUTO_OPEN_PROXIMITY_ENTITY` (rev 3, replaced by the two sensor fields).

---

## 8. Deliverables

### Sequencing (M8)

1. `SECURITY-LOCK-SWEEP-RETRY-CAP-1` (status review, `fix/security-lock-sweep-retry-cap`) merges to develop first, or Phase 1 is built on a branch cut after it merges. Phase 1 does not edit `_evaluate_lock_check`; the regime's hazard and setter hooks are elsewhere in `security.py`, so the expected conflict is line drift only.
2. After that merge, re-verify every `security.py` line cite in this plan (they are taken from develop on 2026-11-07) and update them before build dispatch.
   **Rev 4 (review 2):** the re-cite list includes `switch.py` (`CoordinatorEnabledSwitch`, `:259-268`, `:753-761`), `optimization.py` (dispatch `:4868-4905`, `_read_cm_config` `:4314`) and `cover_ownership.py`, not only `security.py`.
3. Mint `SC-SWEEP-CLOSES-OPEN-GARAGE-1`, `SC-LOCK-REGIME-DOOR-LOCKS-1`, `SC-ARMING-ALARM-ONLY-1`, and (rev 4) `SC-GEOFENCE-PERSON-SNAPSHOT-1`; plus `PRESENCE-GUEST-TO-SLEEP-EDGE-1` only if the operator picks §4.2 (b) (adjacency sweep first).
3a. **`SC-SWEEP-CLOSES-OPEN-GARAGE-1` is cut from develop only after `SECURITY-LOCK-SWEEP-RETRY-CAP-1` merges**, never in parallel (both edit `_evaluate_lock_check`'s garage block, `security.py:~1705-1723`). It builds a **generic per-door "do not close until" stamp** on SC, `garage_close_holdoff_until[D]` (set via a small public method, read by the sweep before any garage close), with no dependency on the Phase 2 controller. Phase 2's `_fire_open()` later stamps it with `now + AUTO_OPEN_SWEEP_HOLDOFF_S`. This makes P2-B testable before D6 exists (tests stamp the API directly) and removes the circularity of the rev 3 `auto_opened_at[D]` wording.
4. Phase 1 ships. Phase 2 prerequisites P2-A (D0 Phase 2 gates) and P2-B (`SC-SWEEP-CLOSES-OPEN-GARAGE-1`, at minimum the hold-off) land before D6 is dispatched.

### Phase 1 — lock regime + lockout + optimizer veto (Tier 2-DB protocol)

#### D0: Measure (read-only probe; go/no-go for D3's P5 claim and all of Phase 2)

One script over the HA recorder (~7 days) plus the URA DB. Questions §8.1; thresholds §8.2; report §13.

**What D0 can and cannot measure now (rev 3).** The proximity entry and any approach zone have no history before 2026-11-07, so no proximity-sensor cadence or `direction_of_travel` behaviour can be measured on the first pass. But proximity's distance is computed from the same tracker coordinates the recorder already holds, so D0 **recomputes distance offline** by haversine from the operator's (and each resident's) `device_tracker` / `person` latitude / longitude history against `zone.home`'s centre. That gives, on the first pass: G1, G3, G4, G5, G2 in both forms (home-ring and 1.5 km approach), and G6 (P5 lead) for residents with GPS. What it cannot give: proximity's own update cadence and `towards` reliability (A2), and any zone edge (A1). Those are collected by the Phase 2 shadow (D6 in shadow writes the proximity readings into each decision row), and D7's exit bar is evaluated on that data. D0 states for each gate whether it was measured on recomputed distance or on the proximity sensors.

- **Verify:** §13 filled with N, per-signal availability and lead distributions, the replayed false-positive count, the device_class of both covers, and which gates used recomputed distance.
- **Discriminates:** a positive lead with zero replay FPs means Phase 2 is buildable; any replay FP or a negative median lead parks Phase 2.

#### D1: Config + kill switch
Fields per §7 (Phase 1 rows). Kill switch options-backed; semantics §6.1. Tests: `test_lockout_config_roundtrip`, `test_lockout_entities_overlap_rejected`, `test_lockout_switch_reads_options_absent_is_off`, `test_kill_switch_off_releases_both`, `test_kill_switch_off_release_not_suppressed_by_observation`, `test_kill_switch_off_skips_unavailable`, `test_kill_switch_boot_off_no_write`, `test_distance_sensor_unit_ft_converted`. Live: fields present; switch present.

#### D2: Lock regime + engage / morning / vacation / restart
`LockRegimeController` per §6.1, fed from `_on_house_state_changed_signal` before the `:1104` return; new `lock_regime` branch in `evaluate()`.
- **Verify:** SLEEP → both `lock.lock`; VACATION → both lock; AWAY → nothing; GUEST → nothing; SLEEP → WAKING → unlock; override SLEEP → HOME_DAY → unlock; ARRIVING → unlock; stuck SLEEP → unlock at 07:00; VACATION at 07:00 → still locked; restart at 02:00 mid-SLEEP → wake and backstop still release.
- **Discriminates:** `test_vacation_not_released_by_backstop` fails if the backstop keys on "any engage"; `test_away_never_engages` / `test_guest_night_does_not_engage` fail if AWAY / GUEST are in the engage set; `test_regime_runs_with_auto_follow_off` fails if the feed sits after `:1104` or the `evaluate()` branch is under the `:815` auto-follow condition; `test_restart_mid_sleep_backstop_still_releases` fails if `reason` is not rebuilt at boot; `test_restart_late_house_state_restore_upgrades_reason` fails if only the setup-time read is used.
- **Test:** `test_sleep_engages_both`, `test_vacation_engages_both`, `test_away_never_engages`, `test_guest_night_does_not_engage`, `test_guest_clears_then_sleep_engages`, `test_sleep_to_away_keeps_reason_backstop_releases`, `test_vacation_to_away_holds`, `test_arriving_releases`, `test_wake_releases_sleep_engaged`, `test_override_sleep_to_home_releases`, `test_backstop_releases_stuck_sleep`, `test_backstop_reads_cm_sleep_end_hour`, `test_backstop_default_when_cm_unset`, `test_vacation_not_released_by_backstop`, `test_vacation_not_released_by_wake`, `test_restart_mid_sleep_backstop_still_releases`, `test_restart_mid_sleep_wake_releases`, `test_restart_vacation_restored_holds_at_0700`, `test_restart_unknown_state_treated_as_sleep`, `test_restart_late_house_state_restore_upgrades_reason`, `test_regime_runs_with_auto_follow_off`, `test_arming_path_unchanged_byte_identical` (rev 4 oracle: snapshot the emitted action list and `ArmedState` for an auto-follow-ON SLEEP edge on develop, assert equality after the change), `test_manual_unlock_not_reasserted`, `test_no_engage_when_disabled`, `test_observation_mode_records_would_engage`.
- **Live:** tonight at SLEEP both lockouts `locked` with `last_action.trigger = house_state:sleep`; next morning `unlocked` with `house_state:waking` or `backstop`.

#### D3: Arrival release (P1-P5) + re-engage
Regime's own resident listener (P1); dispatch in `_handle_person_arriving_signal` above `:2113` / `:2115` (P2); proximity crossing (P5); optional zone edge.
- **Verify:** lockout engaged (URA or manual) + resident arrival → unlock ≤ 5 s measured event → service call; arrivals from `not_home`, `unknown`, `unavailable` and a named zone all release; `old_state None` is not an edge; proximity crossing releases; `wall_kiosk` never releases; VACATION-engaged + arrival → unlock and no re-engage; with SC observation ON the arrival still releases.
- **Discriminates:** every test runs with SC DISARMED (the live state), so a branch placed after `:2015` fails; the P2 test runs with SC observation ON, so a branch below `:2115` fails; `test_resident_listener_survives_empty_person_snapshot` fails if the regime reuses the geofence snapshot.
- **Test:** rev 1 list + `test_release_while_disarmed`, `test_release_under_sc_observation` (asserts the recorded `lock.unlock` service call, not an intent or log line), `test_person_added_at_runtime_releases_without_reload`, `test_person_removed_at_runtime_stops_release`, `test_excluded_person_never_releases`, `test_resident_set_persisted_and_restored`, `test_persisted_resident_not_yet_loaded_still_subscribed`, `test_unknown_blip_while_home_no_release`, `test_unavailable_blip_after_real_away_releases`, `test_reengage_superseded_by_second_arrival`, `test_reengage_waits_for_proximity_released_resident`, `test_reengage_abandoned_after_max_wait`, `test_proximity_first_reading_after_unknown_not_a_crossing`, `test_proximity_unit_km_converted`, `test_arrival_from_unavailable_releases`, `test_arrival_from_named_zone_releases`, `test_old_state_none_not_an_arrival`, `test_resident_listener_survives_empty_person_snapshot`, `test_missing_resident_warns`, (`test_proximity_crossing_releases` uses 6000 ft → 3000 ft with R = 1500 m, §6.1a M4), `test_proximity_crossing_releases`, `test_proximity_unknown_no_signal`, `test_arriving_signal_branch_above_observation_return`, `test_vacation_arrival_releases_no_reengage`.
- **Live:** one controlled test with the operator (rev 1 D3); a resident proximity crossing logged as `trigger = proximity`.

#### D4: Fail-safes
Rev 1 D4, plus (rev 4): C1 teardown release on the real disable path; hazard lockout release only, between `:2057` and `:2059` (M3); H1 generation recheck; H3 latch / single re-engage / teardown timers; M1 boot window. Tests: `test_sc_switch_off_releases_before_reload`, `test_sc_teardown_restart_does_not_release`, `test_sc_teardown_release_timeout_does_not_block_unload`, `test_hazard_under_observation_releases_lockouts_not_door_locks`, `test_readback_retry_then_high_nm`, `test_engage_intent_dropped_if_release_after_queue` (+ the H1 siblings), `test_multi_trigger_arrival_single_unlock`, `test_teardown_cancels_regime_timers`, `test_boot_settle_override_vacation_does_not_engage`, `test_kill_switch_on_mid_sleep_no_engage`, and `test_regime_never_emits_cover_service` written as a **behavioural** test: drive every regime trigger with a recording `hass.services.async_call` and assert no `cover.open_cover` / `toggle` / `set_cover_position` / `close_cover` call (a source grep does not count, Bug Class #62).

#### D4b: Optimizer veto on SC-owned covers (H3)
§6.3.
- **Verify:** an optimizer intent `cover.open_cover` on either garage cover is vetoed with reason `security_owned_cover`; a blind cover still ACKs; an exception in the ownership check vetoes.
- **Test (rev 4):** see §6.3 list. `test_optimizer_cover_ownership_error_vetoes` is dropped (hollow: the helper never raises).
- **Live:** `honor_optimizer_intent` has no live trigger at shadow autonomy; proven in-suite (README states this).

#### D5: Diagnostics + docs
Attributes on `sensor.ura_security_coordinator_security_armed_state`: `lock_regime_garage_lockout_{enabled,reason,last_action,reengage_at,missing_residents}` (`_unrecorded_attributes` if they churn). Update `docs/Coordinator/SECURITY_COORDINATOR.md` ("Lock regime vs arming", the observation-independent release, the residuals) and the presence doc §1 consumer table (new consumer of `SIGNAL_PERSON_ARRIVING`, `person.*`, proximity sensors).

#### D5b: Physical tests (operator, before enabling)
With each lockout ON, on each door: (1) outside wireless keypad; (2) a car remote; **(3) HA `cover.open_cover` from the HA app (M5)**; (4) the opener's own app, if any, with HA reachable and, if practical, with HA stopped. Record in §13.
- **Gates:** keypad still opens → README caveat for that door. If HA `open_cover` is refused while locked, the "HA app can always open" recovery claim is removed and the only recovery is release-then-open (the regime release, or the operator unlocking the lockout in the app first); README says so. If HA `open_cover` works while locked, Phase 2's "release before open" ordering stays (belt and braces).

### Phase 2 — operator auto-open trial (Tier 3, separate release)

**Prerequisites (both before D6 dispatch):**
- **P2-A:** D0 Phase 2 gates pass (G1-G5). D0 Q12 (both covers `device_class: garage`) is **answered: yes, live 2026-11-07**; D0 re-reads it at run time.
- **P2-B:** `SC-SWEEP-CLOSES-OPEN-GARAGE-1` landed with at least the generic `garage_close_holdoff_until[D]` stamp (§8 step 3a), built after `SECURITY-LOCK-SWEEP-RETRY-CAP-1`. Test `test_sweep_no_close_within_holdoff_after_auto_open` and `test_sweep_closes_after_holdoff`.

#### D6: `AutoOpenController` (shadow-capable)
§6.2; config + switches per §7; decision log (each row includes the proximity readings, so the shadow period measures A2).
- **Verify / Discriminates:** rev 2 text stands (hand-built fixture from a real D0 arrival; drive-by and passenger fixtures produce none).
- **Test:** rev 2 list + `test_no_open_during_active_alert`, `test_no_open_within_post_lockdown_block`, `test_no_entry_nm_has_no_action_button`, `test_shadow_absent_key_reads_on`, `test_optimizer_cannot_open_garage` (INV-1 integration-wide, via D4b). `test_only_auto_open_module_emits_cover_open` drives every SC path AND the optimizer dispatch path with a recording `async_call` (no source grep). Rev 4 adds `test_no_second_open_across_reload_mid_episode`, `test_store_load_failure_blocks_open`, `test_shadow_switch_entity_absent_key_reads_on`.
- **Live:** with shadow ON, the operator's next real arrival writes a would-open row with the input vector, including proximity values.

#### D7: Shadow period → act (operator gate)
Rev 2 text stands. G4 in D0 is a screen, not the proof (L5): one 7-day window with N ≥ 8 has little power on its own; the proof is D7's ≥ 10 further arrivals with 0 false would-opens, measured on the live proximity sensors.

### 8.1 D0 probe questions

Rev 2 questions 1-11 stand, amended:
- **Q2:** record whether the approach zone (if created) produces any recorder-visible signal; A1 used only if it does.
- **Q3 (replaces rev 2):** proximity exists (2026-11-07). D0 cannot measure its cadence (no history); it recomputes distance from tracker lat/lon. The shadow measures the sensors.
- **Q5 / G6:** lead times computed on recomputed distance (1.5 km crossing) as well as zone.home enter.
- **Q12 (new):** `device_class` of both garage covers (state attributes and registry), per `cover_ownership.is_security_owned_cover`. Either not `garage` / `gate` → INV-1 false; operator fixes the device class in HA before Phase 2.
- **Q13 (new):** for each resident, does `person.<x>` (or a tracker) carry GPS lat/lon in the window? (Sizes P5 coverage; Jaya expected none.)

### 8.2 Go / no-go thresholds

Rev 2 table stands. Amendments: G2 (approach form) and G6 are evaluated on recomputed haversine distance in the first D0 pass, labelled as such; G4 is a screen (L5).

---

## 9. Non-goals and parked

- No remote garage close by new code (INV-1B). Auto-close after the no-entry timer: parked (rev 2 trigger).
- No close action button on any NM (M7).
- Sweep garage auto-close not changed in Phase 1 (fixed before Phase 2 via P2-B).
- Door-lock policy not migrated (card to mint).
- Arming / auto-follow unchanged (card to mint).
- Lockouts not in `security_lock_entities` or lockdown.
- AWAY never engages. GUEST nights: **OPEN operator decision** (§4.2, options (a) / (b); planner recommends (a)). Not a settled non-goal.
- **HA-down-at-night residual accepted** (§5.2).
- No face-identity gating; no guests in the allowlist.
- Auto-open for others than the operator: parked.
- Auto-open on foot or bicycle: non-goal.
- No DB schema or new table.
- No change to Presence (the GUEST → SLEEP finding is a doc correction, not a code change).
- Parked from rev 1: periodic enforcement; per-door separate policies.

## 10. Reviewer focus

### Phase 1 (three framing-disjoint passes)
- **A — Correctness + edge cases:** §6.1 against `VALID_TRANSITIONS` and overrides; `reason` rebuild at boot (`boot_unknown` semantics); GUEST inert; unit conversion; INV-1 for the regime; D4b veto.
- **B — Async / lifecycle / arming-vs-locks separation:** feed placement above `:1104`, `:2113`, `:2115`; own listener vs the geofence snapshot; engage-through-evaluate vs release-direct; setter override fires on disable but not on teardown; boot recheck timer cancelled on teardown; arrival vs re-engage vs backstop races; Presence vs SC observation.
- **C — Test authority by per-site mutation:** neuter each release site (own listener, arrival signal, proximity, house-state release, ARRIVING, backstop, hazard, kill-switch edge, disable edge, boot rebuild) and the VACATION engage and the D4b veto, one at a time; a named test must fail each time.

### Phase 2 (four passes)
Rev 2 list, plus D's legal-config repros: optimizer at L2 proposing `cover.open_cover` (must be vetoed); auto-open during an active alert; sweep tick 30 s after an auto-open; a cover whose `device_class` was changed to `door`.

## 11. Tier

- **Phase 1:** Tier 2 by scope, operator-elevated to Tier 2-DB. D4b adds a veto to a shared handshake (`honor_optimizer_intent`), in the fail-closed direction only; it stays Tier 2-DB.
- **Phase 2:** Tier 3 (rev 2 reasons). Two plan reviews before D6 dispatch.

## 12. Operator questions

Answered (2026-11-07): see rev 2 list and the Phase 2 answers at the end. No new operator questions in rev 3.

**Rev 4, OPEN (blocks Phase 1 build dispatch):** Q-G1 guest nights, §4.2: (a) lockout engages on GUEST during sleep hours (regime-only, toggle) or (b) add a GUEST → SLEEP edge in Presence (own card and cycle). Planner recommends (a), toggle default ON.
**Rev 4, answered (operator 2026-11-07):** the resident set is dynamic, persisted across restarts, and tracks person adds/removals in real time (§6.1a). Items the operator should know (README, not questions): release writes run under SC observation mode; HA-down-at-night residual; GUEST nights do not engage.

## 13. D0 results

(pending)

## 14. Plan review 1 → resolution (rev 3)

| Finding | Severity | Verified against code | Resolution in rev 3 | Where |
|---|---|---|---|---|
| H1 restart loses `reason` | HIGH | Plan text (rev 2 §6.1 memory-only); `presence.house_state` exists `presence.py:1992` | Boot rebuild from house state + recheck at `GARAGE_LOCKOUT_BOOT_RECHECK_S`; `boot_unknown` releases like sleep; 5 tests | §6.1, INV-4, D2 |
| H2a SC disabled strands lockout | HIGH | `manager.py:1281-1283`, `:971`; `base.py:194` setter | Setter override releases on the True → False edge; teardown does not; residual named | §6.1, INV-2, D4, §5.2 |
| H2b observation-ON suppresses release | HIGH | `security.py:825-831`; switch sets a plain attribute `switch.py:3467-3472` | Release writes go direct (hazard pattern), not via `evaluate()`; engage still observation-gated. Third option chosen over "release on the observation edge" (no hook exists, and boot-restored observation would still strand). | §6.1, INV-2, D3 |
| H3 optimizer can open garage | HIGH | `const.py:4364-4366`; `security.py:1903-1909`; `optimization.py:4989`; `cover_ownership.py:82` | D4b veto in Phase 1; INV-1 restated integration-wide | §6.3, INV-1, D4b |
| H4 sweep closes an auto-opened door | HIGH | `security.py:702-709`, `:1705-1723` | P2-B prerequisite: `SC-SWEEP-CLOSES-OPEN-GARAGE-1` hold-off before D6; INV-1B extended; tests | §6.2, §8 |
| M1 person snapshot at setup | MED | `security.py:1989-1995`; `manifest.json` deps http/frontend/logbook | Regime's own listener on resolved ids; WARN + attribute on missing | §1.2, §6.1, D3 |
| M2 GUEST night never engages; doc contradiction | MED | `house_state.py:116-121`, `:219-221`; `presence.py:1399-1408`; `README_v5.16.0.md:12-14` | Stated + non-goal + 2 tests; presence doc §7 corrected, ledger #29 | §4.2, §9, presence doc |
| M3 P5 has no producer; passive zone likely silent | MED | No code; HA passive semantics UNVERIFIED | P5 = proximity distance crossing (exists); zone optional | §4.1, §4.4 |
| M4 no `proximity.*` entity | MED | Settled by observation 2026-11-07 (sensor entities) | Two sensor fields replace the single entity field; unit conversion | §1.1, §4.4, §7 |
| M5 recovery vs refused-open contradiction | MED | Opener behaviour UNVERIFIED | D5b adds HA `open_cover` with lockout ON per door; HA-outage residual named | D5b, §5.2 |
| M6 no alert / lockdown gate | MED | `_active_alert` `security.py:584`, `:1025`, `:1549`; lockdown `:1642` | Added to INV-1A + knob + tests + D repro | INV-1A, §7, D6 |
| M7 "Tap to close" | MED | NM actions ACK / STATUS / SILENCE `notification_manager.py:3373-3400` | Text only, no button; deep link only if a URL field is confirmed | §6.2, D6 |
| M8 sweep retry-cap collision | MED | `kanban.data.yaml:33601` status review; branch `fix/security-lock-sweep-retry-cap` | Sequencing: retry-cap first, re-cite after; P2-B after it | §8 sequencing |
| M9 two sleep windows | MED | `__init__.py:3733-3744` reads the same CM keys | Partly refuted: one key, structural equality. Regime reads it the same way; tests with non-default and unset | §4.2 |
| L1 SLEEP → HOME_* only by override; silent AWAY rows | LOW | `house_state.py:108-111`, `:267-290` | Explicit rows + tests; ARRIVING release added | §6.1 |
| L2 P2 late, Presence observation | LOW | `person_coordinator.py:209`, `:1111`; `presence.py:8512-8518` | P2 labelled corroborator | §4.1 |
| L3 P2 placement vs `:2113` / `:2115` | LOW | `security.py:2113-2117` | Placement named; test with observation ON | §1.2, D3 |
| L4 knob gaps | LOW | — | Shadow NM, entry-evidence field, retry count added; switches options-backed (no `unavailable` restore) | §7 |
| L5 G4 low power | LOW | — | Stated as a screen; D7 is the proof | D7, §8.2 |
| L6 5 s oracle start point | LOW | `manager.py:50`, `:939-944` | Measured event → service call; release bypasses the batch anyway | INV-2 |
| Early return `:2020` (`old_state None`) | review table | `security.py:2020-2021` | Own listener; `None → home` not an edge, boot rule covers | §4.1, D3 |
| `evaluate()` branch for new source | review table | `security.py:815` | New `lock_regime` branch, not under auto-follow | §1.2, §6.1 |
| `manager.py:971` disabled skip | review table | yes | Release direct + disable-edge release | §6.1 |
| Kill switch: observation + restore direction | review | `switch.py:3422-3500` (RestoreEntity pattern avoided) | Direct release; options-backed, absent = OFF | §6.1, §7 |
| G2 / G6 no history until D0 config | review | proximity history starts 2026-11-07 | D0 recomputes distance from tracker GPS now; shadow measures the sensors | D0 |
| Opener-side movement outside HA | review table | kanban HVAC-GARAGE-GUARD-STAGED-SUNSET-1 | Named in INV-1 as outside URA | INV-1 |
| `device_class` dependency of INV-1 | review | `cover_ownership.py:31`, `:82` | D0 Q12 + P2-A gate | INV-1, D0 |

**Not resolved here (needs action outside this file):** the three cards named in §3.2 do not exist on the board and must be minted; the `security.py` line cites must be re-verified after `SECURITY-LOCK-SWEEP-RETRY-CAP-1` merges; HA's passive-zone semantics and NM deep-link support remain UNVERIFIED (neither is load-bearing after rev 3); opener behaviour with the lockout ON waits for D5b.

## 15. Plan review 2 → resolution (rev 4)

| Finding | Severity | Verified against code (develop, 2026-11-07) | Resolution in rev 4 | Where |
|---|---|---|---|---|
| C1 SC-disable release hooks a dead path | CRITICAL | `manager.py:1249` def only (grep of `custom_components/` + `quality/`); `switch.py:259-268`, `:753-761` write option then reload; teardown `security.py:841-866` | Setter override withdrawn. Teardown releases (awaited, bounded) when `coordinator_should_run` (`coordinator_gate.py:43`) reads False; restart/reload unaffected. Dead-path tests replaced by a switch-driven test. | §1.2, §6.1a C1, INV-2, D4 |
| H1 queued engage lands after a direct release | HIGH | `manager.py:927-958` batch; release direct | `release_gen` bumped by every release (write or not); engage intent carries gen; `evaluate()` re-checks gen, kill switch, SC enabled, house state, settled residents | §6.1a H1, INV-2 |
| H2a optimizer veto is advisory; SC absent = no veto | HIGH | `optimization.py:505-536` `await_veto`; dispatch `:4868-4905` | Layer 1 hard DISALLOW in the optimizer's own dispatch (egress_paused shape), independent of SC; SC veto kept as layer 2 | §1.2, §6.3, INV-1 |
| H2b ownership helper fails open; error test hollow | HIGH | `cover_ownership.py:93`, `:100`, `:116-117`, `:124` | Configured-list leg (`CONF_SECURITY_GARAGE_ENTITIES`, `const.py:3407`) checked first in both layers; hollow test dropped; state-missing + registry-unavailable + device-class-changed tests | §6.3, D4b |
| H3 blips, multi-trigger unlocks, timers | HIGH | teardown cancels only the auto-follow debounce (`security.py:851-857`); `_min_away_minutes` `person_coordinator.py:210` | Blip rule with `GARAGE_LOCKOUT_BLIP_MIN_AWAY_MIN`; per-lockout in-flight latch; single re-engage handle superseded per arrival; regime teardown cancels every timer and tracker | §6.1a H3, §7 |
| M1 boot_settle_override VACATION engages at boot | MED | `presence.py:2575-2597` dispatch; **payload has no `source` key** (`presence.py:8573-8581`), trigger `override_set`; `BOOT_SETTLE_TIMEOUT_SECONDS = 60` (`const.py:4188`) | Edges within `GARAGE_LOCKOUT_BOOT_RECHECK_S` of setup only rebuild `reason`; residual named | §6.1a M1, INV-5, §5.2 |
| M2 re-engage on a resident still en route | MED | plan text | `releasing_set` must be settled (home, or beyond R again); else re-check, abandon at `GARAGE_LOCKOUT_REENGAGE_MAX_WAIT_S` | §6.1a M2, INV-3, §7 |
| M3 whole hazard block could be hoisted | MED | `security.py:2051-2062` (`:2057` enabled, `:2059` observation) | Only the lockout release goes between `:2057` and `:2059`; door-egress loop unchanged; discriminating test | §6.1a M3, D4 |
| M4 units / crossing rule | MED | `DistanceConverter` at `homeassistant/util/unit_conversion.py:296` (pinned venv) | REUSE converter; crossing = numeric > R then numeric ≤ R; first reading after unknown not a crossing; 3000 ft vs 1500 m test; D0 reads HA's distance definition | §6.1a M4, D3 |
| M5 second open across reload mid-episode | MED (Phase 2) | plan text | Persist `last_open_at[D]`; boot blackout `AUTO_OPEN_EPISODE_MAX_S`; store-load failure fails closed | §6.2a, INV-1A |
| M6 phone in a moving car | MED (Phase 2) | plan text | Named residual (§5.2, README, D's repro list); corroborator revival trigger | §6.2a, §5.2 |
| L1 kill switch ON mid-SLEEP | LOW | — | No catch-up engage; test | §6.1a, INV-5 |
| L2 Presence observation suppresses edges | LOW | `presence.py:8518-8524` | Listed as residual | §5.2 |
| L3 shadow absent = ON via switch | LOW | `switch.py:558` pattern | Switch default True; test reads the entity | §6.1a |
| L4 RELEASE_MAX_S is an oracle | LOW | — | Marked "not read by production code" | §7 |
| Q12 device class | answered | live HA read 2026-11-07: both `garage` | Recorded in §1.1; P2-A half passes | §1.1, §8 |
| Hollow tests table | review | — | Every listed test rewritten to drive production paths with a recording `async_call` / snapshot oracle | D2-D6 |
| Sequencing (a) re-cite list | review | `switch.py` touched by C1 | Re-cite list includes `switch.py`, `optimization.py`, `cover_ownership.py` | §8 step 2 |
| Sequencing (b) sweep card circular | review | `security.py:~1705-1723` shared with retry-cap | Cut after retry-cap merges; generic `garage_close_holdoff_until[D]` API that Phase 2 stamps | §8 step 3a, P2-B |
| Operator: dynamic residents (2026-11-07) | operator | `async_track_state_added_domain` / `_removed_domain` (`helpers/event.py:653`, `:711`); geofence snapshot `security.py:1987-1995` | Resident set = `person.*` minus exclusions, real-time add/remove, persisted Store; geofence flaw carded `SC-GEOFENCE-PERSON-SNAPSHOT-1` (arming path stays byte-identical) | §6.1a, §7, D3 |
| Operator disputes guest-night claim | operator | `house_state.py:116-121`, `presence.py:1399-1408` re-read; no GUEST episode in 7-day recorder | Marked OPEN with options (a)/(b); planner recommends (a) | §4.2, INV-6, §9, §12 |

**Unresolved after rev 4:** Q-G1 guest nights (operator); the four/five cards to mint; re-cite after retry-cap merges; `DistanceConverter.convert` signature and HA proximity's distance definition (builder / D0 to confirm); whether `person` entities removed in HA fire `async_track_state_removed_domain` for storage-backed persons on deletion (expected, builder verifies in test against the pinned HA); opener behaviour with lockout ON (D5b).

---

## Operator answers to Phase 2 questions (2026-11-07)
Operator: 'I thought I answered those questions?' — taken as acceptance of the planner recommendations, as for rev 1:
- Q-A1 door: the bay D0 shows the operator uses on >=80% of arrivals.
- Q-A2 approach zone: `zone.home_approach`, 1500 m, passive; created at D0. (Rev 3: now optional; the proximity sensors carry the approach signal.)
- Q-A3 too few arrivals: ship Phase 2 in shadow-only to collect data.
- Q-A4 Sleep: auto-open stays off at night until the shadow log shows zero false night opens.
- Q-A5 after auto-open: HIGH notice at 180 s, no auto-close.
- Q-A6 proximity: add an HA `proximity` entry (home, operator) at D0. (Done 2026-11-07, tracking all four residents.)
