# PLANNING — Security Coordinator: lock regime + garage remote lockout (+ gated operator auto-open trial)

**Card:** GARAGE-REMOTE-LOCKOUT-SCHEDULE-1 (operator picked option B, 2026-11-07; decisions recorded in the card field `operator_2026_11_07_decisions`).
**Rev:** 3 (2026-11-07). Rev 1 = commit ea4bc6a8. Rev 2 = commit 5a9fb5ea (+ 2b691a77 kill switch, 7283f0aa Phase 2 answers). Rev 3 folds every finding of plan review 1 (`docs/reviews/code-review/sc_garage_lockout_plan_review_1.md`, FIX-PLAN); see the findings → resolution table in §14.
**Tier:** Phase 1 (lock regime + lockout + optimizer cover veto) = Tier 2, operator-elevated to the Tier 2-DB three-review protocol. Phase 2 (auto-open) = **Tier 3**, its own release. See §11.
**Status:** plan rev 3, plan review 2 (adversarial build-prediction) still owed before build dispatch. No code written.

Operator intent (unchanged): the opener "remote lockout" stops the outside keypad and car remotes being guessed or bypassed. "3 AM entries from red eyes. Don't want family to be locked out." 2026-11-07: "Separate arming from locks: arming = security system + alarms; locks = a reasonable locking regime that does not need the alarm armed." And: on a fast (vehicular) approach by the operator, release the lockout and open the garage, as an operator-only trial behind its own toggle.

Mandatory reads done for rev 3: `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (complete, all 835 lines, including the §10 corrections ledger) and `docs/architecture/SENSOR_FLEET_CLASSES.md` (complete). No ledger claim is re-asserted. Ledger items honoured: #13 (Bermuda `home` with `area: null` is stale), #23 (location in no-room branches comes from `person.<x>.state`), #26 (a frozen GPS `home` gives no arrival edge), #27 (a dead BLE fleet reads `not_home`). Rev 3 adds ledger entry #29 to that doc (GUEST → SLEEP, §4.2 below). HVAC is not touched.

---

## 1. Institutional context verified

### 1.1 Live facts

| Fact | Value | Read |
|---|---|---|
| Lockout entities | `lock.konnected_f0f5bd523b00_lock` (Garage A, Konnected blaQ); `lock.ratgdov25i_dbfe2a_lock_remotes` (Garage B, ratgdo 2.5i). `locked` = lockout ON. | rev 1 |
| Doors | `cover.konnected_f0f5bd523b00_garage_door` (A), `cover.ratgdov25i_dbfe2a_door` (B). `device_class` of both: **UNVERIFIED** (D0 Q12; INV-1 depends on it, §5.1). | rev 1 |
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
| SC disable edge | EXTEND: `SecurityCoordinator` overrides the `enabled` setter (`base.py:194-197`) | `manager.async_set_coordinator_enabled(False)` sets `coordinator.enabled = False` then `_cancel_listeners()` (`manager.py:1281-1283`). The override releases once on the True → False edge, before listeners go. Teardown / unload does not go through the setter, so a restart does not release. |
| SC observation-ON edge | not needed (rev 3, H2b) | The observation switch sets a plain attribute (`switch.py:3467-3472`, `security.py:575`); no edge hook exists. Rev 3 solves H2b by making release writes observation-independent instead of adding a hook. |
| Kill switch / Phase 2 switches | REUSE the options-backed switch pattern (`_IntegrationOptionsSwitch`, `switch.py:558`; CM keys added to `OPTIONS_RELOAD_SUPPRESS_KEYS`, `__init__.py:7477`) | No RestoreEntity, so the value comes from entry options at setup and "restored `unavailable`" cannot occur (rev 3, L4). |
| Approach signal (P5, A2) | REUSE HA core proximity **sensors** (`sensor.madronehaos_<person>_distance`, `_direction_of_travel`) | Exists since 2026-11-07 (§1.1). No URA code reads proximity today (grep `proximity\.\|direction_of_travel` over the integration: 0 code hits). Replaces rev 2's single `proximity.*` entity field (M4). |
| Approach zone | OPTIONAL (demoted, rev 3, M3) | Proximity distance gives the same "within 1.5 km" fact for any zone state semantics; the zone is kept only as an optional extra edge. |
| Optimizer cover veto | EXTEND `honor_optimizer_intent` (`security.py:1880-1912`) with REUSE `cover_ownership.is_security_owned_cover` (`cover_ownership.py:82`) | Today it vetoes only `lock.*` (`:1903-1905`) and `alarm_control_panel.*` (`:1907-1909`) and ACKs `cover.*`; `OPTIMIZER_ALLOWED_DOMAINS_DEVICE` includes `cover` (`const.py:4364-4366`); dispatch calls the service directly (`optimization.py:4989`). H3. |
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

**Lockout behaviour on a guest night:** while the house reads GUEST no lockout engages (fail-safe direction: remotes and keypad work, as today). If the gate clears during the night, the house reaches SLEEP and the lockout engages then. The regime does NOT treat GUEST as an engage state. Reason: the operator's goal is family arrivals; a guest night is rare outside his travel, and adding GUEST to the engage set would need its own decision about guests without an arrival signal. Non-goal, revival trigger: the operator asks for lockouts on guest nights. Tests `test_guest_night_does_not_engage`, `test_guest_clears_then_sleep_engages`.

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

- **INV-1 (one garage-raising writer, integration-wide; rev 3, H3):** In the whole integration, the only reachable call that can move either garage cover up (`cover.open_cover`, `cover.toggle`, `cover.set_cover_position`, `cover.stop_cover` excluded) is `AutoOpenController._fire_open()`. Paths that must not: the lock regime; the sweep, lockdown and hazard paths (`security.py`); room covers (`automation.py`, filtered by `cover_ownership`); `hvac_covers.py` (filtered via `_is_garage_cover` → `cover_ownership`); the optimizer (vetoed by D4b); NM companion actions (none exist for covers). **Depends on** both covers reading `device_class: garage` (D0 Q12); if either does not, INV-1 is false through `automation.py` / `hvac_covers.py` and the fix is the operator setting the device class in HA (config-first) before Phase 2. **Outside URA's control:** the opener's own wall button, its own app, and opener-side automations (Garage B moved with no HA call on 2026-10-11 19:07, card HVAC-GARAGE-GUARD-STAGED-SUNSET-1). Falsify: any other reachable call path to a cover-raising service on either garage cover.
- **INV-1A (auto-open is fully gated):** `_fire_open()` issues `cover.open_cover` on door D only if ALL hold at fire time, re-checked after the last `await`: auto-open toggle ON; SC enabled and not in observation mode; shadow switch OFF; arriving person in the allowlist; `fast_approach` true for a fresh episode; that episode has not produced an open; D reads `closed`; **no active security alert (`_active_alert`, `security.py:584`, set at `:1025`, `:1549`) and no lockdown action issued within `AUTO_OPEN_POST_LOCKDOWN_BLOCK_MIN`** (rev 3, M6); house not VACATION unless the arriving person is the operator; house not SLEEP unless the sleep sub-toggle is ON; operator not already reading home past the debounce; **the sweep hold-off for D is armable** (P2-B landed). Falsify: any reachable state in which an open is issued with one of these false, or two opens for one episode.
- **INV-1B (no remote close by new code, and no close of a URA-opened door):** No code added by this cycle calls `cover.close_cover` on a garage. After P2-B, the pre-existing sweep issues no `cover.close_cover` on door D within `AUTO_OPEN_SWEEP_HOLDOFF_S` of an auto-open of D (H4). Falsify: a sweep tick inside the hold-off that emits a close on D.
- **INV-2 (family release; rev 3, H2):** While the lockout feature is enabled and SC is enabled, for any configured resident R, the regime issues `lock.unlock` to every available lockout reading `locked` within `GARAGE_LOCKOUT_RELEASE_MAX_S` (5 s) of the first arrival input for R (P1-P5), regardless of who engaged it **and regardless of SC observation mode** (release writes are observation-independent, §6.1). Measured from the triggering event's timestamp to the `hass.services.async_call` invocation (L6), not from an intent being queued. In addition: the SC enabled True → False edge and the kill switch ON → OFF edge each release once. Falsify: any reachable state (SLEEP, VACATION, mid-debounce, re-engage timer pending, after restart, SC observation ON, auto-open toggle in any position) in which an arrival input does not produce the unlock. Auto-open never weakens INV-2: the release happens on the same edge whether or not an open follows, and an auto-open exception must not skip it.
- **INV-3 (no re-engage on top of a resident):** rev 1 INV-3 unchanged.
- **INV-4 (morning; rev 3, H1):** a lockout engaged for SLEEP is released at the earliest of SLEEP → WAKING, an override to HOME_*, ARRIVING, or 07:00 (`sleep_end_hour` + `GARAGE_LOCKOUT_MORNING_BACKSTOP_MIN`) — **including when HA restarted after the engage**. VACATION-engaged lockouts are not released by the clock or by wake. Falsify: engage at 22:30 SLEEP, restart at 02:00, SLEEP → WAKING at 06:40 (must release), or no wake (must release at 07:00); and VACATION at 07:00 across a restart (must stay locked).
- **INV-5 (edge-only):** rev 1 unchanged.
- **INV-6 (AWAY and GUEST inert):** a transition into AWAY or GUEST never engages a lockout.

### 5.2 Fail-safe directions

- Lockout: **released.** Boot never engages. Release writes go direct and are not suppressed by SC observation. SC disable releases first. Kill switch OFF releases (operator 2026-11-07). Unavailable lockouts skipped with dedup; read-back after `GARAGE_LOCKOUT_READBACK_S` with `GARAGE_LOCKOUT_READBACK_RETRIES` (1) retry, then HIGH NM.
- Auto-open: **closed / no action.** Any doubt = no open; the release still happens.
- **Named residuals (accepted, stated in the README):**
  - **HA down at night (M5):** with HA or the network down, URA cannot release, and the lockout blocks remotes and keypad. Recovery: the front door key / keypad lock, or the opener's own app if it works without HA (D5b records which). This exists from the first night the feature is ON.
  - **SC disabled across a restart:** the disable edge already released, so a locked lockout here means a manual lock or a failed release (NM already sent). No URA release until SC is re-enabled.
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

### 6.2 Auto-open (Phase 2) — `AutoOpenController` in `domain_coordinators/security_auto_open.py`

Separate module so INV-1 is checkable by file. Rev 2 §6.2 stands except as amended here.

**Arrival episode / decision / which door / sleep / vacation / audit / shadow / restart / kill:** rev 2 text stands, with A2 now reading the two proximity sensors (§4.4) and D0 choosing the arithmetic.

**Gates at fire time:** INV-1A (now includes the alert / lockdown gate, M6, and the sweep hold-off, H4). Release first; open only after the release read-back passed or the lockout already read unlocked.

**Sweep hold-off (needs P2-B).** On an auto-open of D the controller stamps `auto_opened_at[D]`; the sweep skips the garage-close for D while `now − auto_opened_at[D] < AUTO_OPEN_SWEEP_HOLDOFF_S`. The no-entry NM covers the door left open. This mechanism belongs to `SC-SWEEP-CLOSES-OPEN-GARAGE-1`, which may fix the sweep more broadly (e.g. occupancy-aware close); D6 needs at least the hold-off.

**Open-without-entry timer.** After an auto-open, no entry evidence (door → `closed`, a sensor in `CONF_SECURITY_AUTO_OPEN_ENTRY_EVIDENCE`, the operator's BLE resolving to an interior room) within `AUTO_OPEN_NO_ENTRY_S` (180) → **HIGH NM, text only, no action button** (M7): "Garage A was opened for your arrival 3 min ago and no entry was seen. Check the camera; close it from the HA app if needed." No close writer, no companion action. Whether the NM can carry a dashboard deep link is UNVERIFIED (NM's notification data fields were not read in this pass); if the builder confirms a URL field exists, a deep link may be added, otherwise text only. The text must not promise the door stays open beyond the sweep hold-off.

**Shadow NM:** `AUTO_OPEN_SHADOW_NM_ENABLED` (§7).

### 6.3 Optimizer cover veto (Phase 1, D4b)

`honor_optimizer_intent` (`security.py:1880`) gains, after the `lock.` / `alarm_control_panel.` checks: if the target starts with `cover.` and `cover_ownership.is_security_owned_cover(hass, target)` is True → veto, `_last_veto_reason = "security_owned_cover"`. Any exception in the check → veto (fail closed for a door). Covers that are not garage / gate are unaffected (blinds still ACK).

---

## 7. Knobs (every number)

| Knob | Default | Rung | Why / kill semantics |
|---|---|---|---|
| `CONF_SECURITY_GARAGE_LOCKOUT_ENABLED` | off at ship | 3 Switch `switch.ura_security_coordinator_garage_lockout`, options-backed (`_IntegrationOptionsSwitch` pattern, key in `OPTIONS_RELOAD_SUPPRESS_KEYS`) | Phase 1 kill; ON → OFF releases both lockouts once (direct, not observation-suppressed, unavailable skipped, read-back + retry, HIGH NM on failure), then no lockout writes. Operator 2026-11-07 'Release on off'. Absent key = OFF. |
| `CONF_SECURITY_LOCKOUT_ENTITIES` | the two lockouts | 2 (domain=lock) | Validator rejects overlap with `security_lock_entities` |
| `CONF_SECURITY_LOCKOUT_RESIDENTS` | the four persons with trackers | 2 | Resolved explicitly; missing ids WARN (M1) |
| `CONF_SECURITY_LOCKOUT_DISTANCE_SENSORS` | the four `sensor.madronehaos_<person>_distance` | 2 (entity selector, domain=sensor, multiple) | P5 source; empty = no P5 |
| `GARAGE_LOCKOUT_APPROACH_RADIUS_M` | 1500 | 3 Number | P5 threshold; 0 = P5 off |
| `CONF_SECURITY_LOCKOUT_APPROACH_ZONE` | empty | 2 (domain=zone) | Optional extra P5 / A1 edge |
| `GARAGE_LOCKOUT_MORNING_BACKSTOP_MIN` | 60 (07:00) | 3 Number | 0 = release at `sleep_end_hour` |
| `GARAGE_LOCKOUT_REENGAGE_DELAY_S` | 900 | 3 Number | 0 = never re-engage after an arrival |
| `GARAGE_LOCKOUT_BOOT_ARRIVAL_WINDOW_S` | 600 | 1 | Restart safety |
| `GARAGE_LOCKOUT_BOOT_RECHECK_S` | 120 | 1 | H1 second read of house state after setup |
| `GARAGE_LOCKOUT_READBACK_S` | 20 | 1 | Protocol window |
| `GARAGE_LOCKOUT_READBACK_RETRIES` | 1 | 1 | L4; then HIGH NM |
| `GARAGE_LOCKOUT_RELEASE_MAX_S` | 5 | 1 | Test oracle (event → service call) |
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
3. Mint `SC-SWEEP-CLOSES-OPEN-GARAGE-1`, `SC-LOCK-REGIME-DOOR-LOCKS-1`, `SC-ARMING-ALARM-ONLY-1` (adjacency sweep first).
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
- **Test:** `test_sleep_engages_both`, `test_vacation_engages_both`, `test_away_never_engages`, `test_guest_night_does_not_engage`, `test_guest_clears_then_sleep_engages`, `test_sleep_to_away_keeps_reason_backstop_releases`, `test_vacation_to_away_holds`, `test_arriving_releases`, `test_wake_releases_sleep_engaged`, `test_override_sleep_to_home_releases`, `test_backstop_releases_stuck_sleep`, `test_backstop_reads_cm_sleep_end_hour`, `test_backstop_default_when_cm_unset`, `test_vacation_not_released_by_backstop`, `test_vacation_not_released_by_wake`, `test_restart_mid_sleep_backstop_still_releases`, `test_restart_mid_sleep_wake_releases`, `test_restart_vacation_restored_holds_at_0700`, `test_restart_unknown_state_treated_as_sleep`, `test_restart_late_house_state_restore_upgrades_reason`, `test_regime_runs_with_auto_follow_off`, `test_arming_path_unchanged_byte_identical`, `test_manual_unlock_not_reasserted`, `test_no_engage_when_disabled`, `test_observation_mode_records_would_engage`.
- **Live:** tonight at SLEEP both lockouts `locked` with `last_action.trigger = house_state:sleep`; next morning `unlocked` with `house_state:waking` or `backstop`.

#### D3: Arrival release (P1-P5) + re-engage
Regime's own resident listener (P1); dispatch in `_handle_person_arriving_signal` above `:2113` / `:2115` (P2); proximity crossing (P5); optional zone edge.
- **Verify:** lockout engaged (URA or manual) + resident arrival → unlock ≤ 5 s measured event → service call; arrivals from `not_home`, `unknown`, `unavailable` and a named zone all release; `old_state None` is not an edge; proximity crossing releases; `wall_kiosk` never releases; VACATION-engaged + arrival → unlock and no re-engage; with SC observation ON the arrival still releases.
- **Discriminates:** every test runs with SC DISARMED (the live state), so a branch placed after `:2015` fails; the P2 test runs with SC observation ON, so a branch below `:2115` fails; `test_resident_listener_survives_empty_person_snapshot` fails if the regime reuses the geofence snapshot.
- **Test:** rev 1 list + `test_release_while_disarmed`, `test_release_under_sc_observation`, `test_arrival_from_unavailable_releases`, `test_arrival_from_named_zone_releases`, `test_old_state_none_not_an_arrival`, `test_resident_listener_survives_empty_person_snapshot`, `test_missing_resident_warns`, `test_proximity_crossing_releases`, `test_proximity_unknown_no_signal`, `test_arriving_signal_branch_above_observation_return`, `test_vacation_arrival_releases_no_reengage`.
- **Live:** one controlled test with the operator (rev 1 D3); a resident proximity crossing logged as `trigger = proximity`.

#### D4: Fail-safes
Rev 1 D4, plus: SC disable-edge release; hazard release placed before the `:2059` observation return; `test_regime_never_emits_cover_service` (INV-1 for Phase 1). Tests: `test_sc_disable_edge_releases`, `test_sc_teardown_does_not_release`, `test_hazard_releases_lockouts_under_observation`, `test_readback_retry_then_high_nm`.

#### D4b: Optimizer veto on SC-owned covers (H3)
§6.3.
- **Verify:** an optimizer intent `cover.open_cover` on either garage cover is vetoed with reason `security_owned_cover`; a blind cover still ACKs; an exception in the ownership check vetoes.
- **Test:** `test_optimizer_cover_open_on_garage_vetoed`, `test_optimizer_cover_on_blind_acked`, `test_optimizer_cover_ownership_error_vetoes`.
- **Live:** `honor_optimizer_intent` has no live trigger at shadow autonomy; proven in-suite (README states this).

#### D5: Diagnostics + docs
Attributes on `sensor.ura_security_coordinator_security_armed_state`: `lock_regime_garage_lockout_{enabled,reason,last_action,reengage_at,missing_residents}` (`_unrecorded_attributes` if they churn). Update `docs/Coordinator/SECURITY_COORDINATOR.md` ("Lock regime vs arming", the observation-independent release, the residuals) and the presence doc §1 consumer table (new consumer of `SIGNAL_PERSON_ARRIVING`, `person.*`, proximity sensors).

#### D5b: Physical tests (operator, before enabling)
With each lockout ON, on each door: (1) outside wireless keypad; (2) a car remote; **(3) HA `cover.open_cover` from the HA app (M5)**; (4) the opener's own app, if any, with HA reachable and, if practical, with HA stopped. Record in §13.
- **Gates:** keypad still opens → README caveat for that door. If HA `open_cover` is refused while locked, the "HA app can always open" recovery claim is removed and the only recovery is release-then-open (the regime release, or the operator unlocking the lockout in the app first); README says so. If HA `open_cover` works while locked, Phase 2's "release before open" ordering stays (belt and braces).

### Phase 2 — operator auto-open trial (Tier 3, separate release)

**Prerequisites (both before D6 dispatch):**
- **P2-A:** D0 Phase 2 gates pass (G1-G5), D0 Q12 shows both covers `device_class: garage`.
- **P2-B:** `SC-SWEEP-CLOSES-OPEN-GARAGE-1` landed with at least the per-door hold-off (§6.2), built after `SECURITY-LOCK-SWEEP-RETRY-CAP-1`. Test `test_sweep_no_close_within_holdoff_after_auto_open` and `test_sweep_closes_after_holdoff`.

#### D6: `AutoOpenController` (shadow-capable)
§6.2; config + switches per §7; decision log (each row includes the proximity readings, so the shadow period measures A2).
- **Verify / Discriminates:** rev 2 text stands (hand-built fixture from a real D0 arrival; drive-by and passenger fixtures produce none).
- **Test:** rev 2 list + `test_no_open_during_active_alert`, `test_no_open_within_post_lockdown_block`, `test_no_entry_nm_has_no_action_button`, `test_shadow_absent_key_reads_on`, `test_optimizer_cannot_open_garage` (INV-1 integration-wide, via D4b). `test_only_auto_open_module_emits_cover_open` drives every SC path AND the optimizer dispatch path.
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
- AWAY never engages. **GUEST nights never engage** (§4.2); revival: operator asks.
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

Answered (2026-11-07): see rev 2 list and the Phase 2 answers at the end. No new operator questions in rev 3. Items the operator should know (README, not questions): release writes run under SC observation mode; HA-down-at-night residual; GUEST nights do not engage.

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

---

## Operator answers to Phase 2 questions (2026-11-07)
Operator: 'I thought I answered those questions?' — taken as acceptance of the planner recommendations, as for rev 1:
- Q-A1 door: the bay D0 shows the operator uses on >=80% of arrivals.
- Q-A2 approach zone: `zone.home_approach`, 1500 m, passive; created at D0. (Rev 3: now optional; the proximity sensors carry the approach signal.)
- Q-A3 too few arrivals: ship Phase 2 in shadow-only to collect data.
- Q-A4 Sleep: auto-open stays off at night until the shadow log shows zero false night opens.
- Q-A5 after auto-open: HIGH notice at 180 s, no auto-close.
- Q-A6 proximity: add an HA `proximity` entry (home, operator) at D0. (Done 2026-11-07, tracking all four residents.)
