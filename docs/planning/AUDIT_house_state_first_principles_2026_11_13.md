# AUDIT: house state from first principles (inventory, measurements, external research, proposal)

Card: HOUSE-STATE-FIRST-PRINCIPLES-1 (`docs/planning/kanban.data.yaml:18617`, Tier 3, investigating).
Read-only. No code changed, no HA state changed. Prepared by ura-planner, 2026-11-13.

**Read completely before writing:** `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (incl. §10 ledger #1-#34),
`docs/architecture/SENSOR_FLEET_CLASSES.md`, `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` (incl. §10 C1-C39),
`docs/reviews/URA_ARCHITECTURE_MAP.md`, `PLANNING_house_state_utilization.md`, `PLANNING_house_state_restart_and_override.md`,
`PLANNING_house_state_sleep_mask_ble_memory_observability.md`, `AUDIT_arriving_on_body_evidence_2026_11_13.md`,
`PLANNING_lock_release_on_arriving.md`. No ledger claim is re-asserted. Code on `develop` @ `387ce52a` wins over every doc.

## 0. Verdict (lead)

1. **The 9-value house state is three axes packed into one enum, and two of them are mostly a clock.** In `infer()`
   (`presence.py:1072-1449`) the only evidence-driven decisions are (a) is anyone here (AWAY vs not) and (b) GUEST (stay latch).
   HOME_DAY / HOME_EVENING / HOME_NIGHT are `_time_based_home(hour)` (`:1451-1464`); SLEEP is "people present AND sleep hour"
   (`:1405-1408`); WAKING is "SLEEP AND not sleep hour" (`:1412-1414`). Measured: every one of 203 SLEEP->WAKING edges fired at
   06:00 local; SLEEP dwell is 480 min at both median and p90 in the last 30 days. SLEEP is a clock window, not sleep.
2. **ARRIVING and WAKING are one-tick shims, not states.** Median dwell 1.0 min, 99% under 2 min (their hysteresis is 60 s,
   `house_state.py:131,136`). ARRIVING is "AWAY and any occupancy" (`presence.py:1349-1370`); 6.4% of its 2,642 edges were real
   arrivals (prior audit). It cannot transition to GUEST or SLEEP, which is why the engine needs it to resolve first (`:1372-1377`).
3. **Consumers already flatten the enum themselves.** HVAC maps 9 -> 4 presets (`hvac_const.py:1358-1369` HOUSE_STATE_PRESET_MAP);
   the memory facade maps 9 -> {away, home, sleep} (`memory_facade.py:270-282`); the routine forecaster collapses to its own vocab
   (`routine_forecaster.py:93-103`); security uses 5 of 9 and leaves HOME_*/SLEEP unmapped (`security.py:189-195`). Each consumer is
   re-deriving the axes the producer merged.
4. **House-level arrival misses per-person arrivals.** In the 7.7-day recorder window there were 75 real resident arrivals
   (not_home -> home after >= 15 min away) against 19 AWAY->ARRIVING rows; 40 of 75 arrived with another resident home and 32 of 75 had
   no house AWAY/ARRIVING within +/-10 min. Anything that wants "Ezinne got home" cannot get it from house state at all. That supports
   the operator hypothesis: arrival is a per-person **event**, not a house state.
5. **AWAY itself is unreliable as a fact.** Exact recorder window: 6 of 19 AWAY entries false (32%; 1 with a resident home, 5 with a
   resident back inside 15 min). 89-day bracketed: ~73% false (snapshot-based, older era, not comparable). ARRIVING's false rate is
   mostly AWAY's false rate showing up one tick later (48.6% of ARRIVING edges are false-AWAY corrections, prior audit).
6. **Recommendation:** separate axes (§4): `occupancy` (empty / occupied / uncertain, with a slow-to-empty, fast-to-occupied rule),
   `residency` (per-person home set, already produced by PersonCoordinator), `period` (day / evening / night / sleep window, a clock),
   plus overlays `guest_stay` and `vacation`, and **arrival / departure as per-person events** fed by tracker edges, egress crossings and
   pre-arrival. Keep the legacy `house_state` sensor as a derived compatibility view during migration. ARRIVING and WAKING retire as
   states. Test both options of the operator hypothesis in §5: **"arrival as event" wins for every access consumer; "narrow ARRIVING
   state" is only defensible as a compatibility shim.**

---

## 1. Inventory: states, transitions, guards

### 1.1 States and producer (`house_state.py:56-67`; producer `StateInferenceEngine.infer`, `presence.py:1072`)

| State | Produced when (code) | Evidence or clock? |
|---|---|---|
| AWAY | nobody-home `census==0 and not zone_occ_for_empty` (`:1181-1189`); path α trackers away + no unidentified/face + cameras healthy (`:1228-1239`); path β LOST-admitted (`:1306-1346`) | evidence |
| ARRIVING | `current==AWAY and (census>0 or any_zone_occupied)` (`:1349-1370`) | evidence (body, no identity) |
| HOME_DAY/EVENING/NIGHT | `_time_based_home(hour)` from ARRIVING, GUEST exit, WAKING, or hour change (`:1375-1377, 1400-1402, 1417-1419, 1437-1447`) | clock (evening 18, night 21) |
| SLEEP | people present and `_is_sleep_hour` (CM sleep window, live 22->6) (`:1405-1408`) | clock gated by "someone here" |
| WAKING | SLEEP and not sleep hour (`:1412-1414`), gated 90 s sustained occupancy (`:7929-8012`) + backstop | clock |
| GUEST | `guest_gate_armed` from HOME_* (`:1426-1433`); gate = stay latch `_compose_guest_gate` | evidence (DB walk over nights) |
| VACATION | **override only**; no `infer()` return | operator |

### 1.2 Transitions and guards

`VALID_TRANSITIONS` `house_state.py:71-126`; dwell `DEFAULT_HYSTERESIS` `:129-139` (AWAY 30 s, ARRIVING 60, HOME_* 120, SLEEP 600,
WAKING 60, GUEST 300, VACATION 7200). Guards outside the machine, all in `PresenceCoordinator._run_inference` (`presence.py:6859`):

| Guard | Site | Applies to |
|---|---|---|
| WAKING sustained gate 90 s + daytime backstop | `:7929-8012`, const `:198` | SLEEP->WAKING |
| GUEST exit persistence (`_guest_persistence_seconds`, 300) + Guest-left button bypass | `:8020-8073` | GUEST->HOME_* |
| ARRIVING re-arm cooldown 900 s (outdoor-only collapse) | `:8170-8216`, `:8243-8285`, const `:226` | AWAY->ARRIVING |
| Boot-restore defer | `:8218-8233` | all |
| Boot-settle + observation-mode dispatch gates | `_dispatch_house_state_change` `:9225+` | dispatch only |
| Away-veto kill switch coercion | `:7705-7723` | AWAY paths α/β |
| Sleep-exempt for β | `:7665-7682` | AWAY path β |
| Override (select / service) bypasses hysteresis; `transition()` clears it | `house_state.py:213-230`, `:241-246` | all |

Structural consequences already documented (not re-asserted, cited): no GUEST->SLEEP edge (ledger #29); SLEEP-pinned zones (ledger
#11/#17); ARRIVING cannot go to GUEST or SLEEP, so every AWAY exit takes a one-minute ARRIVING tick first.

### 1.3 Producer inputs (all inside presence)

`census_count`, `unidentified_count`, `face_recognized_count` (camera_census); `any_zone_occupied`, `any_indoor_zone_occupied`,
`any_zone_occupied_for_empty` (zone trackers + substrate, sleep-mask D1/D4); `all_tracked_persons_away`, trusted/LOST denominators
(PersonCoordinator, `person_state_for_trust` lineage); `guest_gate_armed` (stay latch); `camera_input_degraded`; clock + CM sleep hours.
Note the axis mixing at the input level too: `census_count` = max(camera bodies, face∪BLE ids) blends occupancy and residency.

### 1.4 Consumers (forward trace). T = trust decision, D = display/analytics

| Consumer | file:line | Reads | T/D | What it really needs |
|---|---|---|---|---|
| HVAC preset per house state | `hvac_const.py:1358-1369`, `hvac.py:2850-2860` (skips writes in ARRIVING), signal `hvac.py:1455` | all 9 -> home/sleep/away/vacation | T | occupancy (away), period (sleep), vacation |
| HVAC night tail / evidence rule / fan trust | `hvac_const.py:1104,1119,1134`; `hvac_zones.py:1489,1520`; `hvac_fans.py:615,1216,1442,1521` | sleep/waking, home_day/evening, home_night | T | period |
| HVAC pre-arrival reference | `hvac_const.py:553-561` | sleep/waking | T | period |
| Arrester hold-preserving / durable states | `hvac_const.py:213, 228-229`; `hvac_override.py:1010` | arriving/guest/waking, sleep/away/vacation | T | "is this a durable posture change" = occupancy edge or period edge |
| Garage lockout regime | `security_lock_regime.py:629-650, 845-871, 916, 1642-1646, 1883-1888, 1955-1957` | sleep/vacation/guest/arriving/waking/home_* | T (unlock) | period (sleep window) + vacation + **per-person arrival edge** |
| Security auto-follow (off, never fired) | `security.py:189-195` | away/vacation/guest/arriving/waking | T (arm/disarm) | occupancy + vacation + per-person arrival |
| Exterior-person / track severity | `const.py:2791-2800`, `:2835-2885`, `:3023-3050`, `:3197`; `perimeter_alert.py:1489,1989,3082` | all 9 + persons_home | T (paging) | occupancy + residency count + period (night) |
| Comfort-fan AWAY veto | `fan_veto.py:60,167` | away/vacation | T | occupancy |
| Room per-room chains + Away leave-on sweep | `coordinator.py:990-1000`, `:1792`, `:2325-2335` | away edge, sleep/home_night/waking | T | occupancy edge, period |
| Room lights sleep mode / fan trust | `automation.py:1270-1290`, `:4284-4300`; `lighting/resolver.py:190-313` | sleep, home_night/waking | T | period |
| Non-sleep / sleep person fallback (zone occupancy) | `aggregation.py:4686-4740`, `:4866-4880` | sleep; home_*/arriving/guest/waking | T | period + occupancy |
| Music following | `music_following.py:686-697` | sleep, home_night | T | period |
| NM panel night / colour | `const.py:4202`, `notification_manager.py:223, 4644` | sleep/home_night; arriving colour | T/D | period |
| Optimizer findings gate | `optimization.py:3944` | away/home_night/sleep | T (finding) | occupancy, period |
| HVAC predict / pre-conditioning | `hvac_predict.py:494, 818` | away/vacation, sleep | T | occupancy, period |
| Fan recheck sleep veto | `presence_fan_recheck.py:576,1248` | FAN_TRUST_STATES | T | period |
| Preset overrides / dynamic preset guest | `preset_overrides.py:147`, `dynamic_preset.py:861` | guest | T | guest overlay |
| Binary sensors someone_home / sleep / guest | `binary_sensor.py:2316-2318, 2356, 2452, 3633` | away/vacation, sleep, guest | D (+ HA automations: `wallpanel_*` in `automations.yaml`, sleep-mask plan §4) | the axes directly |
| Bayesian guest listener | `__init__.py:3278-3294` | guest | learning | guest overlay |
| Routine forecaster | `routine_forecaster.py:93-105, 188, 391` | all (collapsed) | D/learning | collapsed already |
| Memory facade / writers | `memory_facade.py:270-282`; `const.py:6080` | all (-> away/home/sleep) | D | collapsed already |
| Energy | `energy.py:9322` | house_state | check at build | likely occupancy |
| House status / diag sensors | `house_status.py:196`, `sensor.py:5653, 5784, 6866, 10613` | state | D | — |

**Fire check (consumer side):** auto-follow 0 fires ever (off); lockout release 0 (switch off); VACATION 0 rows ever (every VACATION
branch in lock regime, security, HVAC, fan veto is unexercised live); GUEST 2 entries in the last 30 days, 0 in the last 27 days (the
night-stay rule made it rare by design). Override: 2 rows ever (`override_set` -> sleep, 10-01).

## 2. Measurements (URA DB `house_state_log`, recorder 8 days; method and scripts in the probe output, scratchpad `hs/`)

### 2.1 Rates

| | all (247 d) | last 30 d |
|---|---|---|
| transitions/day mean / median / p90 | 35.0 / 18 / 79 | 17.2 / 11 / 34 |
| ARRIVING entries/day | 10.7 | 4.65 |
| AWAY entries/day (logged) | 8.46 | 4.65 |
| GUEST entries/day | 3.16 | 0.06 |
| SLEEP entries/night (mean) | 1.80 | 1.03 |

Top edges last 30 d: home_day->away 80, away->arriving 144, arriving->home_day 71, arriving->away 40, sleep->waking 30.

### 2.2 Dwell (minutes)

| state | median (all) | median (30 d) | p90 (30 d) | <2 min (30 d) |
|---|---|---|---|---|
| arriving | 1.0 | 1.0 | 1.0 | 99% |
| waking | 1.0 | 1.0 | 1.0 | 100% |
| away | 2.2 | 14.2 | 101.8 | 20% |
| home_day | 18.4 | 70.6 | 567 | 0% |
| home_night | 2.1 | 59.9 | 60.0 | 3% (clock-bounded 21->22) |
| sleep | 253.7 | 480.1 | 480.4 | 0% (clock-bounded 22->06) |
| guest | 40.0 | 31.0 | 46 | 0% |

### 2.3 False rates where ground truth exists

| Transition | Window | Result |
|---|---|---|
| ->AWAY | recorder 11-05..11-13, exact | 6/19 false (32%): 1 resident home, 5 resident back < 15 min; all 6 `census_update` |
| ->AWAY | 08-16..11-13, 15-min snapshots (bracketed) | ~219/298 false (73%; certain floor 70%); older era, not comparable |
| AWAY->ARRIVING | 03-12..11-13 (prior audit) | 6.4% real, 48.6% false-AWAY correction, 32.8% no resident evidence |
| AWAY->ARRIVING | recorder, exact | 17/19 with a resident edge ±10 min (median lead 35 s) |
| per-person arrival without house arrival | recorder | 32/75 (43%); 40/75 arrived with another resident home |
| SLEEP->WAKING | all | 203/203 at 06:00 local (clock, not wake evidence) |
| SLEEP->AWAY | all | 46; last 10-31 (0 since sleep-mask D1) |

### 2.4 Data finding (new): the log drops AWAY rows

In 565 rows `previous_state` ≠ the prior row's `state`; ~553 are `X -> away -> arriving` with the `away` row missing (home_day 158,
sleep 134, guest 112, …). So `house_state_log` under-counts AWAY entries and `away_entries_today` / INV-COUNTER-MATCHES-LOG readings
built on it inherit the gap. Mechanism **unverified**: a candidate is a dispatch gated (boot-settle or observation) while the machine
still transitioned, but the counts span the whole history, so this needs a probe before anyone acts on it. Card candidate:
`HOUSE-STATE-LOG-MISSING-AWAY-ROWS-1` (orchestrator: adjacency sweep first).

## 3. External research (what others do)

Verified sources (agent fetch + my reads); unverified items are named as such.

| System | Model | Arrival | False-away guard | Takeaway for URA |
|---|---|---|---|---|
| HA core `zone`/`person` ([zone docs](https://www.home-assistant.io/integrations/zone/)) | `zone.home` state = count of persons in it; persons separate | per-person tracker edge | not specified | residency is data; mode is a user layer |
| Phil Hawthorne "not so binary" ([article](https://www.philhawthorne.com/making-home-assistants-presence-detection-not-so-binary/)) | **per-person** Just Arrived / Home / Just Left / Away / Extended Away | transient per-person state (10 min) on tracker edge | Just Left 10 min; reconnect returns to Home without firing arrival | closest analogue to ARRIVING and VACATION, but per person and tracker-keyed, with reconnect suppression |
| Alarmo ([arming modes](https://github.com/nielsfaber/alarmo/wiki/Arming-modes)) | away / night / home / vacation / custom | entry delay (`pending`) around a sensor trigger; no built-in presence disarm | exit/entry delays | security "arrival" is a timed pending state; presence-based arming is an external automation |
| Hubitat Mode Manager ([docs](https://docs2.hubitat.com/apps/mode-manager), [delay thread](https://community.hubitat.com/t/mode-manager-mode-based-on-presence-delay-cancel/15276)) | one global mode (Day/Evening/Night/Away), presence any/all | mode change, no transient | none native; users build cancelable delays | mixing time and presence in one mode causes conflicts (single user report, [HSM thread](https://community.hubitat.com/t/mode-manager-hsm-issue-going-on-vacation-during-the-night-ignores-phone-presence-and-results-in-disarming-hsm-in-the-morning/84217), search summary only) |
| SmartThings ([community](https://community.smartthings.com/t/location-mode-vs-member-location/166375), [support](https://support.smartthings.com/hc/en-gb/articles/360052389671-Locations-in-the-SmartThings-App)) | Home/Away/Night modes, **independent** of member presence | routine "any member arrives -> Home" | none documented | presence and mode are separate objects joined by routines |
| Magic Areas ([area state](https://github.com/jseidl/hass-magic_areas/wiki/Area-State)) | per-area occupied / extended / sleep (sleep from its own entity) | none (just occupied) | extended timeout | sleep is a separate input, not a clock |
| ecobee Smart Home/Away (secondary sources only, weak) | binary home/away from room sensors | any sensor -> Home | ~2 h all-sensors-empty; no overnight away | away slow to enter, fast to exit |
| Lu et al., Smart Thermostat, SenSys 2010 ([PDF](https://www.cs.virginia.edu/%7Estankovic/psfiles/sensys10-final169.pdf)) | HMM over away / active / sleep from motion + door sensors | door events key; motion alone poor | multi-sensor inference | sleep is inferred from evidence, and door events matter for arrival/departure |
| PreHeat, Scott et al., UbiComp 2011 ([PDF](https://ics.uci.edu/~djpatter/classes/2012_09_INF241/papers/p281-scott.pdf)) | occupancy prediction (RFID per person) | **predicted** event | — | arrival is a forecast target fed by per-person signals |

**Not verified (no claims made):** Apple Home first-arrive/last-leave triggers (fetch did not reach the article), Google Home/Nest,
Ring/SimpliSafe/ADT, HA Bayesian binary_sensor, Area Occupancy Detection, CASAS, the Chen 2018 and Labeodan occupancy surveys. A
follow-up fetch should fill these before the proposal goes to plan review; none of the conclusions below depend on them.

**Pattern across verified systems:** (1) who-is-home and the mode label are separate objects; (2) arrival is either per-person or an
event, never "any motion after away"; (3) away is guarded by a slow, cancelable delay and reconnect suppression; (4) time-of-day
belongs to schedules or a separate input, and the one documented failure of a combined mode is time overriding presence.

## 4. First-principles proposal

### 4.1 Axes

| Axis | Values | Producer (REUSE) | Rule |
|---|---|---|---|
| **occupancy** | `empty` / `occupied` / `uncertain` | today's AWAY ladder (nobody-home, α, β) + `any_zone_occupied` | slow to `empty` (existing ladder + dwell), fast to `occupied`; `uncertain` when the ladder disagrees with residency (e.g. trackers away + room sensor holding: the D4d shape) instead of flapping |
| **residency** | set of residents home (+ count), per-person `arrived_at` / `left_at` | PersonCoordinator + `person_state_for_trust`; `arrival_edges.py` (live tracker edge, Bermuda entry move); suspicious-arrival hold | already exists per person; publish one house-level view |
| **period** | `day` / `evening` / `night` / `sleep_window` | `_time_based_home`, CM sleep hours | honest name: a clock. Optional later: sleep *activity* from bedroom evidence (Magic Areas / Lu style) as a separate overlay, not this axis |
| overlays | `guest_stay` (stay latch), `vacation` (operator) | `_compose_guest_gate`; override | independent booleans, not states |

**Events (not state):** `person_arrived(person, source, corroboration)`, `person_departed(...)`, `house_emptied`, `house_occupied`,
`period_changed`. Sources: tracker edge, Bermuda entry-area move, egress crossing direction (`camera_census` arriving legs,
`transit_validator`), face sighting (corroborated by `arrival_source_needs_corroboration`), and pre-arrival (`SIGNAL_PERSON_ARRIVING`
geofence/BLE, HVAC pre-arrival). An expected-arrival window (pre-arrival) is a short-lived per-person **mode**, which is the operator's
"arrival as a mode" in its useful form.

**Compatibility:** derive the legacy `house_state` from the axes (empty -> AWAY; vacation -> VACATION; guest_stay -> GUEST;
sleep_window and occupied -> SLEEP; else HOME_<period>). ARRIVING and WAKING are not produced. One derivation function, so every
legacy reader keeps working while consumers migrate one at a time.

### 4.2 Testing the operator hypothesis (both options)

| Consumer | Option A: arrival = event/mode (egress + pre-arrival + tracker) | Option B: ARRIVING stays a state, narrowed to resident evidence | Verdict |
|---|---|---|---|
| Garage lockout release | releases on `person_arrived` (already does via S1 person path); taint workaround deleted | still needs taint/hold because a narrowed ARRIVING can still be followed by HOME_* without the right person | **A** |
| Security auto-follow disarm | disarm on `person_arrived(resident, corroborated)`; HOME_* unmapped problem disappears | works, but 43% of real arrivals produce no house arrival, so disarm misses people arriving to an occupied armed-home house | **A** |
| Exterior-person severity | use occupancy + residency count + period; "likely the operator approaching" = an expected-arrival window for a named person | narrowed ARRIVING still LOW for anyone during the window | **A** |
| HVAC preset | reads occupancy + period + vacation; the ARRIVING write-skip (`hvac.py:2856`) becomes "occupancy just flipped, settle 60 s" | unchanged | neutral (A simpler) |
| HVAC pre-arrival | already per-person `SIGNAL_PERSON_ARRIVING` | unchanged | already A |
| Arrester hold-preserving states | "transient" = within N s of an occupancy/period edge | unchanged | neutral |
| NM panel colour, routine forecaster, memory | event stream / collapsed vocab already | — | A or no change |

Option B's only advantage is fewer consumer edits. Its cost is that every access consumer keeps a workaround, and it still cannot express
"one resident arrived while another was home". **Recommend A**, with legacy ARRIVING kept only inside the compatibility derivation if a
dashboard or HA automation needs it (none found in URA code beyond the consumers above; HA `automations.yaml` must be grepped at plan time).

### 4.3 Per-consumer migration verdict

| Consumer | Verdict |
|---|---|
| Lock regime (lockout) | MIGRATE to `person_arrived` + `period.sleep_window` + `vacation`; **retire** `_arrival_taint`, `_episode_saw_arriving`, `arriving_hold`, the D3 uncorroborated trip-wire's house-state channel; keep D4 still-locked page (reads person edges already). Operator constraint: the reshape is not done until this ships. |
| Security auto-follow | MIGRATE (parked §13 sibling becomes trivial); keep off until then |
| Exterior severity tables | MIGRATE to (occupancy, residents_home, period, expected_arrival); closes EXTERIOR-PERSON-SEVERITY-ARRIVING-BODY-ONLY-1 |
| HVAC presets / night tail / fan trust / pre-arrival ref | MIGRATE to occupancy + period (mechanical; same outcomes) — Tier 3 per HVAC doc, separate cycle |
| Room chains, lights sleep mode, music, NM panel, optimizer, fan veto, fan recheck | KEEP on legacy derived value first; migrate opportunistically (pure period/occupancy reads) |
| Guest consumers (preset overrides, dynamic preset, Bayesian) | read `guest_stay` overlay |
| Binary sensors someone_home / sleep / guest | re-point to axes; publish new axis sensors |
| Routine forecaster, memory facade | KEEP (already collapse); later read axes directly |

### 4.4 What retires

- ARRIVING and WAKING as produced states (and the ARRIVING re-arm cooldown `presence.py:226, 8170-8285`, the WAKING sustained gate as a
  state guard — its evidence check becomes the occupancy rule).
- Lockout workaround: taint/saw flags, `arriving_hold`, house-state branch of D3, the boot "arriving" handling in `_boot_recheck_regime`
  (`PLANNING_lock_release_on_arriving.md` D1/D3). **Must be revisited and migrated in the same program** (card constraint).
- `ARRESTER_HOLD_PRESERVING_STATES` arriving/waking entries (replaced by an edge-age rule).
- Consumer-local collapse tables (memory facade, forecaster, HOUSE_STATE_PRESET_MAP) once they read axes.
- The 2026-07-30 utilization roadmap (D4b "ARRIVING pre-conditioning", D4e delete undifferentiated states) is superseded by this
  proposal; park it with this card as the reason.

### 4.5 Risks / marginal benefit

- Benefit is concentrated in access and alerting (lockout, auto-follow, exterior severity): today three workarounds; after, one event.
  HVAC gains nothing behavioural (same presets), so its migration is optional and should come last.
- Ingredient risk: a new shared primitive consumed by ~20 sites (Tier 3). Mitigation: compatibility derivation first (byte-identical
  legacy value except ARRIVING/WAKING ticks), then one consumer per cycle.
- **Simplest version capturing most value:** publish `residents_home` + `person_arrived` events + `occupancy` alongside the existing
  enum, migrate the lock regime and severity to them, leave everything else on the legacy value. Removing ARRIVING/WAKING from the enum
  can wait until no consumer reads them.
- AWAY's 32% false rate is not fixed by re-axing; `uncertain` only stops it from being acted on as a hard fact. The ladder's accuracy is
  a separate presence problem (D4d, untracked occupants).

### 4.6 Proposed falsifiable invariant for the plan

"With the new arrival event live, no access unlock (lockout release, auto-follow disarm) is ever issued on evidence that names no
resident; and every resident not_home->home edge that `_arrival_counts` accepts produces exactly one `person_arrived` event within
hold + 1 tick, whatever the house occupancy."

## 5. Next steps (for operator review)

1. Operator: accept/reject the axis model and Option A.
2. If accepted: `PLANNING_house_state_axes.md` (Tier 3; two plan reviews), phase 1 = publish axes + events + compatibility derivation
   (no consumer change), phase 2 = lock regime + exterior severity migration (retire taint), later phases per §4.3.
3. Probe `HOUSE-STATE-LOG-MISSING-AWAY-ROWS-1` before any plan relies on `house_state_log` counts.
4. Fill the unverified external sources (§3) before plan review.
