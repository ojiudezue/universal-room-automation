# PLANNING — House AWAY flap with an untracked occupant home

**Card:** HOUSE-STATE-AWAY-FLAP-UNTRACKED-OCCUPANT-1
**Status:** **Rev 4**, 2026-10-18. Plan only (operator approved writing it, not building it). Rev 4 folds every finding of the two Tier-3 plan reviews of Rev 3:
- `docs/reviews/plan-review/PLAN_REVIEW_house_away_flap_R1_completeness_rev3.md` (`972df3b01`): 1 HIGH, 4 MEDIUM, 4 LOW.
- `docs/reviews/plan-review/PLAN_REVIEW_house_away_flap_R2_build_prediction_rev3.md` (`593ae4ccf`): 4 HIGH, 5 MEDIUM, 5 LOW.

Disposition of every finding: §15. **The biggest change:** Jaya Bedroom leaves the default veto rooms, because the fan/phantom loop cannot be closed without removing all of its measured benefit (§3.3). That changes the goal residual (§6).
**Next step:** the orchestrator decides whether Rev 4 needs a re-verify review. Then the operator approves the PICKs (§11), then build.
**Author:** ura-planner.
**Operator constraints (2026-10-18, verbatim):**
- "this is surgery on the house state so I want a prior art scan and I want it to build on our infra and not be frivolous new functionality."
- "observability in the presence coordinator and house device is important as well as ura v8 dashboard."
- "HVAC to go away fast... house to be more careful."

---

## 0. The plan in one paragraph

URA declares the house AWAY too readily when no tracked phone is home but a person is. Rev 4 makes three changes inside the existing house-state inference and the existing presence sensor.

- **(A) Camera-recency guard.** None of the three automatic AWAY branches may fire until the interior cameras have seen no unrecognised body and no recognised face for **W = 3 min**. While the guard waits, the house **keeps its current state**; it does not drift into SLEEP or GUEST.
- **(B) Room veto.** The existing guest-room occupancy tracker is extended so that **no AWAY branch** can fire while Guest Bedroom 1 or Guest Bedroom 2 is occupied, capped at 8 h per run. A room never holds on a tick where its radar is the only sensor on and its fan is running.
- **(C) Observability.** The presence house-state sensor shows why the house went AWAY, what is holding it home, and today's AWAY count. One card on the v8 `people` view shows this.

Measured effect (30 days):
- Ordinary days: someone-home AWAY entries fall from 2.53/day to roughly **2.1/day** (bounds 0.97–2.14).
- Days with only Jaya and a guest home: 16.2/day falls to roughly **10/day**.
- Departures reach AWAY as fast as today (7 of 10 within 15 min).

**The goal (≤ 1/day) is not met** (§6). HVAC's zone-vacancy path is untouched.

---

## 1. Institutional context verified (MANDATORY)

### 1.1 Mandatory docs read completely before writing
- **`docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`**, including the §10 ledger 1–12. No ledger claim is re-asserted.
  - #12 (path α has no census or zone term) is relied on as corrected.
  - #1 (the ESPHome LD2410 fires on a running fan) is now load-bearing (§3.3).
- **`docs/architecture/SENSOR_FLEET_CLASSES.md`.** The veto rooms were classified by capability:
  - The MS600 Matter radars hold a still person.
  - The Jaya LD2410 is a radar and is fan-susceptible.
- **`docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md`**, read completely. No §10 claim is re-asserted.
  - The house-state handler is at `hvac.py:5184` (C10).
  - Zone vacancy is knob 48 = 5 min.
- **`docs/planning/AUDIT_census_arc_and_away_holistic.md`**, including "Probe results 2026-10-18" and "Probe P3".
- **`docs/planning/AUDIT_away_flap_untracked_occupant_would_have.md`**.
- **Rev 2 and Rev 3 of this plan, and all four plan reviews** (R1/R2 of Rev 2, R1/R2 of Rev 3).
- **`docs/Coordinator/IDENTITY_FUSION_CAMERAS_MANUAL.md`** (via Rev 2). `face_recognized_count` is used only as "a camera saw a body".

### 1.2 Prior-art scan: REUSE / EXTEND / BUILD
Re-grepped on `develop` @ `593ae4ccf`, 2026-10-18.

| # | Piece | Verdict | Evidence (file:line) |
|---|---|---|---|
| P1 | The three automatic AWAY returns | **EXTEND**: two new checks per branch, placed after that branch's already-AWAY check | Nobody-home `presence.py:1127-1131`; path α `:1170-1181`; path β `:1248-1288`. `grep "return HouseState.AWAY"` finds exactly `:1131`, `:1181`, `:1288`. The only other state-machine writers are `transition` `:6961`, the overrides (`select.py:278`, `__init__.py:6201`, `presence.py:8017`) and `apply_restored` (`manager.py:697`). |
| P2 | Camera evidence per census tick | **REUSE** | `_handle_census_update`: `unidentified_count` at `presence.py:4758`, `face_recognized_count` at `:4765-4769`. |
| P3 | Last-camera-body timestamp | **BUILD: one RAM field** | `grep last_camera_body\|away_hold` finds 0 hits. |
| P4 | Discharge of the guard | **REUSE** the 60 s periodic, **with its registration isolated** (D2) | `async_track_time_interval(self._periodic_inference…)` at `presence.py:2926-2930`. Today it sits inside the same `try:` as `_discover_guest_rooms` (`:2881`), whose `except` is at `:2932-2933` (R2v3-H3). Handler at `:5074`. |
| P5 | Room-occupancy tracker for veto B | **EXTEND** | `_discover_guest_rooms` `presence.py:5164-5334`; listener `:5336-5401`; state dict `_guest_room_state` `:1726`; sibling maps `_guest_room_entity_to_name` `:1734` and `_guest_room_known_last_true` `:1742`. |
| P5b | Restart-surviving run start for the cap | **REUSE** | Room `OccupiedBinarySensor` is a RestoreEntity and restores the coordinator's `_became_occupied_time` (`binary_sensor.py:306-308`, DB fallback `:371-373`). The value is published as the attribute `became_occupied_time` (`binary_sensor.py:473`). (R1 MEDIUM-1, R2v3-H2) |
| P5c | Fan/phantom loop breaker | **REUSE two primitives** | Per-tick capability radar-sole flag `data[STATE_RADAR_SOLE_TICK]`, written at `coordinator.py:3621` (ledger #10, gold pattern "Capability-radar-sole boolean"). Presence fan belief `_fan_on_rooms` `presence.py:580` (gold pattern "Fan listener — last-known-good belief"). |
| P5d | Re-read room config without a restart | **REUSE** `SIGNAL_ROOM_ENTRY_LIFECYCLE` | Dispatched on room load/unload at `__init__.py:5631-5641`, `:6140-6150`, `:8634-8637`. (R2v3-H4a) |
| P6 | Guest gate (behaviour must not change) | **REUSE, fenced** | `_guest_room_gate_armed` `presence.py:5485-5535`, called at `:6067` and `:6081`. |
| P7 | Veto-room membership and cap | **BUILD: one room-options field** | `grep AWAY_HOLD\|AWAY_VETO` in `const.py` and `config_flow.py` finds 0 hits. `CONF_ROOM_IS_GUEST_ROOM` (`const.py:402`) would arm GUEST, so it cannot be reused. |
| P8 | Guard-window knob | **BUILD: one Number**, cloned from `FanInterferenceHoldNumber` (`number.py:3541`), **including its two allowlist entries** | The template's key is in `OPTIONS_RELOAD_SUPPRESS_KEYS` (`__init__.py:7480`, listed at `:7559`) and has an in-place apply at `:8263-8280`. `_NO_LIVE_ATTR_KEYS` is at `__init__.py:7359`. (R2v3-H4b) |
| P9 | Veto label | **EXTEND** | `_veto_path` reset at `presence.py:1124`, set at `:1177/1180/1274/1277`, mirrored at `:6518`. Read by `sensor.py:5661` and the D7 episode `:7926`. No actuation consumer reads the values. |
| P10 | Block-episode writer | **EXTEND** | `_blocked` / `_veto_path_str` `presence.py:6532-6553`. |
| P11 | House-state sensor | **EXTEND (attributes only)** | `PresenceHouseStateSensor` `sensor.py:5557`. No `_unrecorded_attributes` and it polls (30 s). Precedent for unrecorded attributes: `binary_sensor.py:271`. |
| P12 | Daily AWAY count across restarts | **EXTEND the DAO with an optional UTC-instant query** | `count_house_state_changes_since` `database.py:3031-3058`. The writer stores naive UTC (`database.py:2968`). Hydration is at `presence.py:2573-2591`. The sole row writer is `_dispatch_house_state_change` `presence.py:7861`. `_count_transition` is at `:7451`. |
| P13 | Kill switches | **REUSE** | `switch.ura_presence_coordinator_away_confirmation_veto` (code slug `presence_away_veto_enabled`, `switch.py:3880`; coerced at `presence.py:6476-6486`). W = 0. Per-room cap 0. |
| P14 | v8 card style | **REUSE** the Energy-view pattern on the **`people`** view | `ura-v8` views: quick-actions, now, rooms, energy, people, security, climate, health, music (R1 open (a)). The pattern is a heading plus `custom:button-card` `template: hero` plus a markdown table. Colour is set by a `[[[ ]]]` JS template in `styles`, as the Energy "Net Tomorrow" card does. |

**New functionality, flagged and justified:**
- one timestamp (P3);
- one rung-3 Number (P8);
- one rung-2 room field (P7);
- one optional DAO argument (P12);
- labels and sensor attributes.

**Not added:** a timer, a persisted store, an entity, a census payload change, a DB schema change, a signal, a door tally, or an HVAC split.

### 1.3 Prior plans and cards
- The estimator plan stays PARKED (§10). Holistic audit pieces A, B, C and G fold into this plan; H and M stay config actions; O is dropped.
- Cards read: EXERCISE-ROOM-PRESENCE-MISCONFIG-1 (done), STUDYA-ZIGBEE-MMWAVE-MISCATEGORIZED-1 (done), STUDY-A-CSI-SENSOR-1 (parked), CENSUS-OCCUPANCY-ESTIMATOR-1, EGRESS-INTERIOR-COUNT-REINFORCE-1, CENSUS-ATHOME-RESIDENT-CORROBORATOR-1, HVAC-NIGHT-LENIENCY-DEGRADATION-DEFENSE-1 (Jaya radar tracks the fan; HVAC doc C27).

### 1.4 Memory
- `feedback_suppression_needs_discharge` (H1–H3)
- `feedback_parent_entry_reload_watchdog_hazard` (H4b)
- `feedback_no_restart_during_sleep`
- `project_reload_storm_refuted_restart_storm_live` (restart storms bound the cap, H2)
- `project_presence_guest_latch_and_veto_gap`
- `project_guest_mode_false_positive_backlog`
- `feedback_marginal_benefit_pushback`
- `project_house_zones_vs_hvac_zones`

### 1.5 Code read for Rev 4
In addition to Rev 3:
- `presence.py:930-936` (`set_sleep`)
- `presence.py:1288-1340` (fall-through ladder to SLEEP)
- `presence.py:2870-2935` (discovery try-block)
- `binary_sensor.py:254-311` and `:473`
- `coordinator.py:3621`
- `__init__.py:7359`, `:7480`, `:8263-8280`
- `const.py:2335-2345`
- the four `SIGNAL_ROOM_ENTRY_LIFECYCLE` sites

---

## 2. Falsifiable invariants

Definitions:
- `W` = the live `CONF_PRESENCE_AWAY_CAMERA_QUIET_S`, in seconds.
- `B` = `_last_camera_body_ts`. It is the most recent census update with `unidentified_count > 0 OR face_recognized_count > 0`. It is seeded at coordinator setup, and `None` means quiet.
- `R` = the set of rooms with cap `cap_r` = `CONF_ROOM_AWAY_HOLD_MAX_H × 3600 > 0`.
- `H_r(t)` = room r is **holding** at t. That means `binary_sensor.<room>_occupied` is `on`, AND NOT (room tick radar-sole AND a fan of r is on), AND `t − S_r < cap_r`.
- `S_r` = the run start. It is the room coordinator's restored `_became_occupied_time` when available, otherwise the entity's `last_changed`.

> **INV-A (camera quiet):** for W > 0, `infer()` never returns AWAY from any of the three branches at t when `t − B < W`.

> **INV-B (room veto):** for every r ∈ R, `infer()` never returns AWAY from **any** of the three branches at t while `H_r(t)`. This holds whatever the zone flags say: house SLEEP masks them (`presence.py:930-936`), and a room may belong to no zone. (R1 HIGH-1, R2v3-M5)

> **INV-GUARD-HOLDS-STATE:** on a tick where guard A is the reason no AWAY is returned, `infer()` returns `None`. It never returns SLEEP, GUEST, WAKING, ARRIVING or HOME_* on that tick. (R2v3-H1)

> **INV-DISCHARGE:** if every other AWAY condition of some branch holds continuously from `t*` = max(B + W, the end of every `H_r`), then AWAY is proposed by `t* + 60 s` and accepted within the remaining dwell of the current state, using `DEFAULT_HYSTERESIS` (`house_state.py:129-139`): SLEEP 600 s, GUEST 300 s, HOME_* 120 s, WAKING/ARRIVING 60 s.
> - Under guard A the current state is unchanged (INV-GUARD-HOLDS-STATE), so no new dwell is started.
> - Each hold `H_r` ends by `S_r + cap_r`. `S_r` survives a restart through the restored `became_occupied_time`; it resets only when that restore is missing (first boot, entity purge), and the attribute `away_hold_cap_basis` shows which.
> - The discharge requires the 60 s periodic to be registered whatever discovery does (D2).

> **INV-NO-BLE-HOLD:** a census update with `unidentified_count = 0 AND face_recognized_count = 0` never moves `B`.

> **INV-ALREADY-AWAY:** neither A nor B changes the result when `current_state == AWAY`. Each branch's `if current_state == AWAY: return None` runs before the new checks.

> **INV-GUEST-UNCHANGED:** a room in R that is not flagged `CONF_ROOM_IS_GUEST_ROOM` never arms the guest-room gate. The guest kill switch and the known-resident branch never touch `S_r` / `occupied_since`.

> **INV-BYTE-ID:** with W = 0 and R = ∅, every `infer()` return value, every transition, and every `house_state_log` row match today's. The only permitted differences are:
> - new attribute values;
> - the new `_veto_path` value `nobody_home`. It is persisted in the D7 memory-episode payload (`:7926`), so the value domain grows. Grep shows no value consumers beyond `sensor.py:5661` and `presence.py:6518/7926` (R2v3-L3).

---

## 3. Producer and consumer checks

### 3.1 The three AWAY branches
Nobody-home (`:1127-1131`, confidence 0.9), path α (`:1170-1181`, label `active`) and path β (`:1248-1288`, labels `lost_admitted[_immediate]`), as in Rev 3.

**New in Rev 4: the zone flags are masked during house SLEEP.** `any_zone_occupied` and `any_indoor_zone_occupied` come from `t.mode == OCCUPIED` (`presence.py:5975-5992`). `mode` returns `_override` first (`:652-656`). `set_sleep(True)` overrides every zone tracker on entry to SLEEP (`:7027-7031`, and the boot restore at `:2404`). So during SLEEP, nobody-home's "no zone occupied" condition is true whatever the rooms say. Only the veto's own room read sees the sleeper.

### 3.2 Producer of `B`
Unchanged from Rev 3, including the predicate decision: **`unidentified_count > 0 OR face_recognized_count > 0`**.
- The face term is 0 on every AWAY-eligible tick.
- It only extends the hold across the moment the last phone goes `not_home`.
- Its departure cost is bounded by P3's `total_persons` measurement, which found no change at W = 3.

R2v3-L1 changes one detail: **the stamp is written whatever W is**. Turning W from 0 to 180 then starts from a fresh B, and the write is a RAM-only change, so INV-BYTE-ID still holds.

### 3.3 Producer of the veto bit, and the fan/phantom loop (R2v3-H2)

**The loop.**
1. The comfort-fan veto acts only when the house is AWAY or VACATION (`fan_veto.py:60`, `:167`).
2. Veto B keeps the house out of AWAY, so a bedroom fan stays on.
3. On a fan-susceptible radar the running fan fakes presence. Ledger #1 measured this in Jaya's room: 68 % of the time with the room empty and the fan on. HVAC doc C27 shows Jaya's radar tracks the fan.
4. The faked presence keeps the room occupied, which keeps the veto holding.

P3 measured the veto open-loop, over history in which α had already sent the house AWAY and the fan veto had broken the loop. Its control numbers therefore do not bound the closed loop.

**Options weighed with evidence (P3 §2 tables, all-phones-away windows):**

| Breaker | GB1 / GB2 cost | Jaya Bedroom result |
|---|---|---|
| (i) Require a second sensor in the room to agree | GB: 0 uncorroborated radar minutes (P1), so cost ≈ 0 | The LD2410 held 478 minutes and the ZK held 0. All of Jaya's trip gain disappears. |
| (ii) Exclude fan-on minutes | GB2: 24 of 336 occupied minutes have the fan on (≤ 7 %); GB1: 0 | All 507 of Jaya's occupied minutes had the fan on. Gain = 0. |
| (iii) **Do not hold on a tick that is radar-sole AND has the room fan on** (REUSE `STATE_RADAR_SOLE_TICK` + `_fan_on_rooms`) | GB rooms carry a Hobeian ZV/PIR, a fan-immune witness, so a real guest who moves keeps the hold. Cost ≤ the 24 GB2 fan-on minutes. | Jaya's room has only radars (LD2410 + ZK), so every fan-on tick is radar-sole. Gain = 0. |
| (iv) Keep Jaya at a lower cap | — | The loop still holds an empty house HOME for the full cap after every departure with the fan on. That is the opposite of "house careful but correct". |

**Decision.**
- Adopt **(iii)** as the generic loop breaker for every veto room. It reuses two primitives, is fail-open (no hold), and costs the guest rooms at most about 7 % of their occupied minutes.
- **Drop Jaya Bedroom from the default rooms.** No breaker closes the loop in her room without removing all of its measured benefit; this is the "if it can't be closed safely" branch of the brief.
- Jaya Bedroom stays legal as a config row (cap > 0). The §10 revival trigger is a fan-immune witness (ZV or PIR) in the room, or an LD2410 retune proven by a fan-on/empty re-measure.

**Other producer rules:**
- The veto reads URA's fused `binary_sensor.<room>_occupied`, the same signal P1–P3 measured.
- Unavailable counts as not occupied (`presence.py:5356-5359`), so the veto fails open.
- The known-person check does NOT apply. A resident in the room is someone home (C13).
- The radar-sole flag and the fan belief are read fresh per inference from the room coordinator's `data` and `_fan_on_rooms`. If either is missing or raises, the room counts as **not holding**.

### 3.4 CONSUMERS of house AWAY
Re-grepped 2026-10-18, plus R1 MEDIUM-4. The guard and the veto sit in inference, so every consumer sees the guarded AWAY. "≤ W" means the AWAY edge arrives up to 3 min later (plus at most one 60 s tick plus dwell).

| Consumer | file:line | Kind | Effect of A | Effect of B |
|---|---|---|---|---|
| HVAC presets | `hvac.py:1437`, `:5184`; AWAY → away at `:2968`/`:3024` | signal, trust | House edge is first mover in 22 % of zone-episodes, now ≤ W later. Zone vacancy (knob 48) unchanged, first in 69 %. | The occupied guest room's zone stays home, which is correct. Other zones retreat by zone vacancy. |
| Room AWAY leave-on lights sweep | `coordinator.py:935` | signal edge | ≤ W | No sweep while held |
| Per-room automation chains / AI rules on `house_state_away` | `coordinator.py:1739-1749`; trigger labels `config_flow.py:3183`, `:14995` | signal | ≤ W. Live config has none today. | held |
| **HA automation `wallpanel_fleet_force_off_secure`** | `automations.yaml:8335-8355`: `sensor.ura_coordinator_manager_house_state` → `away` for 3 min turns off 5 wall panels | HA automation, actuation | Flaps of 3 min or more no longer reach it: fewer false panel-offs | Panels stay on while a guest is home (intended) |
| Wall-panel siblings `wallpanel_fleet_wake`, `_sleep_after_grace` | `automations.yaml:8255`, `:8270`, `:8320` (gate `not in ['away','vacation']`) | HA automation | ≤ W | held |
| Security auto-follow | `security.py:759`, `:1087-1094`; **off live** | signal | 0 today | If enabled, no auto-arm while held (intended) |
| Exterior-person NM severity | mapping **`const.py:2344`** (`hs in ("away","vacation","sleep","home_night") → CRITICAL`), called from `perimeter_alert.py:1660-1665` | poll, trust (NM) | Fewer false CRITICALs during daytime flaps. At night the state is SLEEP or HOME_NIGHT, which also maps to CRITICAL, so no change at night. | Daytime guest hold → contextual severity instead of CRITICAL |
| Perimeter vehicle night alert | `perimeter_alert.py:2769`, `const.py:2701` | poll | Night-only, ≤ W | held |
| Comfort-fan AWAY veto | `fan_veto.py:60`, `:167` | poll, trust | ≤ W | **Part of the loop in §3.3**; broken by (iii) |
| HVAC pre-conditioning | `hvac_predict.py:446` | poll | ≤ W | as HVAC |
| Optimizer posture | `optimization.py:3661` | advisory | ≤ W | — |
| Someone-home binary sensor | `binary_sensor.py:2315` | display. **No HA automation reads it** (R1 open (c), 78 automations scanned) | ≤ W | — |
| Energy offset reset | `energy.py:8144-8236`, `:8384` | poll | ≤ W | — |
| Bayesian guest / routine / music / arrester sunset | `__init__.py:3313-3329`, `routine_forecaster.py:188`, `music_following.py:301`, `hvac_override.py:1010` | signal | negligible | negligible |
| Next-state / integration sensors, PWA | `sensor.py:6573`, `:10326-10335`; `frontend-v3` | display | — | — |
| EVSE, battery | none | — | — | — |

**HVAC and "HVAC fast".** HVAC's own path (zone vacancy, fast exit timers, D5) is untouched. Guard A no longer moves an empty house into SLEEP (R2v3-H1), so HVAC sleep presets cannot be applied to an empty house at night by this change. An HVAC split stays PICK 4, default **no split**.

---

## 4. Measure before build (done; read-only, 2026-10-18)
Source: holistic audit P0–P3. Ordinary days are 09-18 → 10-13 (25.7 d); Jaya+guest days are 10-14 → 10-18 (4.3 d). SH = an AWAY entry with someone home (sensor proxy). "upper" uses `total_persons`; "lower" uses unidentified only, which is closest to this plan's predicate (§3.2).

| Config | Ordinary SH/day (days > 1) | Jaya+guest SH/day | Genuine departures within 15 min (of 10) | Verified-empty absences swallowed / delayed (of 14) |
|---|---|---|---|---|
| Today | 2.53 (15) | 16.2 | 7 | 0 / 0 |
| A W=3 only | 1.13 upper | 13.2 | 7 | 0 / 0 |
| **A W=3 + GB1/GB2 8 h: this plan** | **0.97 (4) upper / 2.14 (9) lower** | **9.7 upper / 10.2 lower** | **7** | **0 / 0** |
| A W=3 + GB + Jaya 16 h (Rev 3, now dropped) | 0.90 / 1.71 | 5.3 / 5.8 | 7 | 0 / 1 |

Two Rev 4 effects that the simulation already assumed, so the table is unaffected:
- **SLEEP-mask fix (R1 HIGH-1).** P2/P3 modelled room occupancy as blocking AWAY outright. Rev 3's α-only veto would have under-delivered at night. Rev 4's all-branch veto now delivers what was simulated.
- **Fan breaker (iii) on the guest rooms.** It costs at most 24 of 336 GB2 occupied minutes in the all-away windows, below the table's resolution.

---

## 5. Marginal-benefit decomposition
- **A alone (W = 3)** does most of the ordinary-day work at no departure cost.
- **B on the guest rooms** is the only lever for a guest in a camera-less bedroom. It needs one helper, two checks per branch, and two reused primitives for the breaker.
- **Jaya Bedroom** has a measured margin of +4.4 SH/day avoided on Jaya-alone days, but that margin is made of fan-on LD2410 minutes. Those are indistinguishable from the phantom that the closed loop would sustain. Its risk is an empty house held HOME for up to its cap after every departure with the fan on, and that risk exceeds its margin. Dropped, and parked with a trigger.
- **W > 3, all radar rooms, estimator:** unchanged from Rev 3. All rejected or parked.

---

## 6. The goal and the honest residual
Goal clause (1): **≤ 1 someone-home AWAY per day, and no AWAY over 10 min with a person in a still-holder or camera room.**

- **Ordinary days:** roughly **2.1/day** expected (the predicate sits at the lower bound; 0.97 is unreachable by design). 9 of 26 days stay above 1. **NOT MET.**
- **Jaya+guest days:** roughly **10/day**. **NOT MET.**
- **Change from Rev 3, caused by review finding R2v3-H2:** Rev 3 reported ≈ 1.7 ordinary and ≈ 5.5 Jaya+guest. The 0.4/day and ~4.5/day differences are Jaya Bedroom's contribution. Rev 4 removes it because it cannot be told apart from the fan phantom.
- **Remaining misses by room:**
  - Jaya Bedroom: fan-coupled LD2410; HVAC doc C27; card HVAC-NIGHT-LENIENCY-DEGRADATION-DEFENSE-1.
  - Master Bathroom: InvisOutlet, on the do-not-use list.
  - Study A: ZK phantom; it is the room's only live sensor.
  - Master Bedroom: swallowed a verified-empty absence.
  - Ziri: one 26.5 h run.
  - Study B, Living Room.
  - On guest days, Exercise Room (its ZK was never on).
- **Clause (2), departure within 15 min:** 7 of 10 today and 7 of 10 after. Not met before this change either; unchanged.
- **Clauses (3) and (4):** met and unchanged.

**What moves clause (1) next:** fix the sensors in Jaya Bedroom, Study A, Master Bathroom and Exercise Room. Then re-measure each with P3's controls and add it to R as a config row. The §10 cards hold this.

---

## 7. Deliverables

### D0: Scorecard at day 7 and day 14 after the restart (read-only probe, exit discriminator; R1 MEDIUM-3)
- The recorder keeps **7 days** (`configuration.yaml:13`, `purge_keep_days: 7`), so D0 runs **twice**:
  - **Day 7:** reads the recorder attributes `last_camera_body_source`, `away_hold`, `last_away_reason`. **Save the extract to `docs/planning/AUDIT_house_away_flap_scorecard_day7.json`.**
  - **Day 14:** uses the URA DB (`house_state_log`, `census_snapshots`, `occupancy_events`, `person_entry_exit_events`, and the `memory_episodes` D7 snapshots, which carry `veto_path` and the hold labels with URA retention) plus the recorder's last 7 days.

  This adds no schema change.
- The probe scripts (P0–P3) are committed by the build to `scripts/probes/away_flap_scorecard/`.

**Discriminating table:**

| Observation | Fix working | A broken (never holds) | A or B stuck (never releases) |
|---|---|---|---|
| Ordinary-day SH/day | ≤ 2.3 | ≥ 2.5 | — |
| Genuine departures within 15 min | ≥ 6 of 10 | — | ≤ 3 of 10 |
| AWAY rows with `t − last body < W` | 0 | > 0 | — |
| AWAY rows while a guest room holds (`H_r`) | 0 | — | — |
| Longest HOME stretch with a guest room fan-on + radar-sole and phones away (loop row, R2v3-H2) | 0 holds counted | — | > 0 |

**Exit:** the table is written into the README. Any failing row reopens the card.

### D1: Camera-body stamp (producer)
- In `_handle_census_update`, after `presence.py:4769`: when `_unidentified_count > 0` or `_face_recognized_count > 0`, set `_last_camera_body_ts = dt_util.utcnow()` and `_last_camera_body_source`. This is written **whatever W is** (R2v3-L1).
- Seed at setup with `dt_util.utcnow()`. RAM only. No stamp at the census seed (`:2946/2958`).
- **Tests:**
  - `test_body_stamp_set_on_unidentified_positive`
  - `test_body_stamp_set_on_face_positive`
  - `test_body_stamp_not_refreshed_by_ble_only_identity`
  - `test_body_stamp_not_refreshed_by_zero`
  - `test_body_stamp_seeded_at_boot`
  - `test_stamp_written_when_W_zero_but_no_output_change` (replaces Rev 3's "no stamp when W = 0")
- **Verify:** a forgotten-phone replay reaches AWAY via α at B + W + ≤ 60 s.

### D2: Guard A, and an isolated discharge
- **Caller** (`_run_inference`, `presence.py:5731`): `away_camera_quiet = W == 0 or B is None or (dt_util.utcnow() − B).total_seconds() >= W`. `None` counts as quiet (R2v3-L4). It is passed as the `infer()` keyword `away_camera_quiet: bool = True`. **No `now=`** is passed (C11).
- **Placement and semantics** (R2v3-H1; INV-GUARD-HOLDS-STATE). In each of the three branches:
  1. Keep the existing `if current_state == AWAY: … return None` **first**.
  2. Then evaluate veto B (D3), and if it holds, record the hold and **fall through**.
  3. Then: `if not away_camera_quiet: self._away_hold = "camera_recent"; return None`.

  Fall-through is right for the veto because someone is home: SLEEP or GUEST with a guest in the room is correct. `return None` is right for the guard because the house may be empty: it holds the current state, so no SLEEP, GUEST, ARRIVING→HOME or new dwell is started.
- **Ordering when both apply on one branch:** veto first, then guard.
  - If the veto holds, the fall-through runs the rest of the ladder and the guard is not reached for that branch.
  - The first branch whose other conditions hold decides. In branch order (nobody-home, α, β), the first one that would have fired applies its hold.
- **Labels** (R2v3-L2): a denied branch **does not** set `_veto_path`. It sets only `_away_hold` and `_away_hold_detail = {"branch": …}`. Both are reset at the top of `infer()` and mirrored by the caller next to `:6518`.
- **Early returns** (R2v3-L5): on every early return of `_run_inference` (boot-settle deferral `~:6951`, and so on), the mirrored `_away_hold` is set to `none`, so the sensor never shows a stale hold.
- **Discharge isolation** (R2v3-H3):
  - Move the `async_track_time_interval(self._periodic_inference, 60 s)` registration (`presence.py:2926-2930`) **out of** the discovery `try:` block, so it is registered whatever discovery raises.
  - Also wrap all new per-room parsing in `_discover_guest_rooms` in its own per-room try/except, like the existing boot-seed at `:5254-5319`.
- **No new timer.**
- **Tests** (framing C anchors; each must go RED when its own site is neutered):
  - Per branch: `test_nobody_home_blocked_within_W`, `test_path_alpha_blocked_within_W`, `test_path_beta_blocked_within_W`.
  - Boundary and kill: `test_away_at_exact_W_boundary`, `test_W_zero_byte_identical`.
  - `test_guard_hold_does_not_enter_sleep_on_would_be_away_tick`: 23:01, zones occupied by tails, α guard-denied → `None`, not SLEEP. Mutation: replace `return None` with fall-through → RED.
  - `test_guard_hold_from_arriving_returns_none`.
  - `test_guard_ignored_when_already_away`.
  - `test_alpha_guard_never_produces_arriving_from_away`.
  - Discharge: `test_periodic_discharges_at_B_plus_W`; `test_discharge_dwell_table` (from SLEEP 600 s, GUEST 300 s, HOME_DAY 120 s; replaces Rev 3's 120 s-only test).
  - `test_periodic_registered_when_guest_room_discovery_raises`. Mutation: move the registration back into the shared block → RED.
  - `test_none_stamp_is_quiet`.
  - `test_early_return_clears_mirrored_hold`.
- **Config extremes:** W = 0, 30, 1800; `camera_input_degraded`; restart mid-window; away-veto switch OFF.
- **Live:**
  - No AWAY row lands < W after the last body.
  - During a guard hold the state does not change, and `away_hold = camera_recent`.
  - `away_eligible_at` is re-evaluated after boot, which shows the periodic is alive.

### D3: Veto B on all three branches (extending the guest-room tracker)

**Config (P7).** Room options field `CONF_ROOM_AWAY_HOLD_MAX_H = "room_away_hold_max_h"`, rung 2. It sits next to the guest-room flag (`config_flow.py:12509`, and the config-flow step near `:2306-2337`).
- NumberSelector, 0–24 h, step 1. Parsed as `int(float(x or 0))` inside the per-room try.
- **Default 0 = not a veto room**, which is also the kill switch.
- Label: "Keep house Home while occupied (hours)". Help: "If this room's occupancy is trustworthy (a radar that holds a still person, plus a motion sensor), the house won't go Away while it's occupied, for up to this many hours. 0 = off."

**Live config changes without a restart** (R2v3-H4a). Presence subscribes to `SIGNAL_ROOM_ENTRY_LIFECYCLE` (P5d). On a room's `loaded` event, presence re-runs `_discover_guest_rooms`, which already cleans up its unsubs and maps at `:5183-5191`. A room options save reloads that room entry, so caps and the kill switch take effect within seconds.
- The builder must confirm that the new room key is **not** in any room-level reload-suppress set. If it is, the change instead needs a room reload, and the plan's Live criterion is restated to say so.
- **Operator config action, in order:** deploy → restart once (awake window) → set GB1 = 8 and GB2 = 8 in the room options. Each save reloads only that room.

**Tracker extension.**
- `_discover_guest_rooms` registers a room if it is a guest room **or** its cap is > 0.
- Each room's state dict gains: `roles` ⊆ {`guest`, `away_veto`}, `hold_max_s`, `occupied_since`, and `cap_basis` (`restored` | `last_changed`).

**Seeding `occupied_since`** (R1 MEDIUM-1, R2v3-H2). At discovery, when the room is `on`: seed from the room coordinator's restored `_became_occupied_time` (P5b; also exposed as the entity attribute `became_occupied_time`), and set `cap_basis=restored`. Otherwise use `last_changed` with `cap_basis=last_changed`. The Rev 3 test `…counts_real_run` is replaced by:
- `test_occupied_since_seeded_from_restored_became_occupied_time`
- `test_occupied_since_falls_back_to_last_changed_and_marks_basis`

**Reader-by-reader disposition** (R2v3-M3, R1). The builder implements exactly this:

| Reader / site | Roles affected | Rule |
|---|---|---|
| `:5189` `_guest_room_state.clear()` (re-discover) | all | Clears all; re-discovery rebuilds |
| `:5227` dict creation | all | Adds `roles`, `hold_max_s`, `occupied_since`, `cap_basis` |
| `:5254-5319` `first_seen` boot seed | **guest only** | Unchanged for guest rooms; skipped for veto-only rooms |
| new `occupied_since` boot seed | **away_veto** | As above |
| `:5367-5398` listener, transitions 1–3 | **guest only** for `first_seen` / `current_occupancy_known` | Unchanged |
| listener: `occupied_since` | **away_veto** | Set on an off→on **state** change only. Clear on on→off or unavailable. **An attribute-only event (on→on) never resets it.** Transition 2 (known resident) never touches it. |
| `:5401` `_run_inference` scheduling | guest: unchanged | Veto-only rooms schedule inference **only when `old.state != new.state`** (R1 LOW-2) |
| `:5500` `_guest_room_gate_armed` | **guest only** | Skips dicts without role `guest` |
| `:5677` `_clear_guest_room_first_seen` (guest kill switch) | **guest only** | Never touches `occupied_since` |
| `:7653` teardown | all | Unchanged |
| `_guest_room_entity_to_name` `:1734/:5224/:5363` | all (shared) | Unchanged semantics |
| `_guest_room_known_last_true` `:1742/:5459/:5473` | **guest only** | Not read by the veto |

**Helper.** `_room_veto_holding(now) -> (room, age_s, cap_s, basis) | None`. It returns the first veto room that meets all of these:
- its `occupied_since` is set;
- `now − occupied_since < hold_max_s`;
- **NOT** (the room coordinator's `data[STATE_RADAR_SOLE_TICK]` is True **and** the room is in `_fan_on_rooms`) (§3.3 (iii)).

Any read error means the room is not holding.

**Consumer.**
- The caller passes `away_room_veto: bool = False` into `infer()`; the default is byte-identical.
- It is applied **in all three branches**, after the already-AWAY check: `if away_room_veto: self._away_hold = "room_veto"; fall through` (R1 HIGH-1, R2v3-M5).

**Discharge.** A room going off fires the listener, which runs inference immediately. Cap expiry and the fan breaker take effect at the next 60 s periodic.

**Tests:**
- Holds and releases:
  - `test_alpha_blocked_while_veto_room_occupied`
  - **`test_nobody_home_blocked_by_veto_room_in_sleep`** (zones overridden to SLEEP, census 0, GB2 holding → not AWAY; mutation: drop the nobody-home check → RED)
  - `test_beta_blocked_by_veto_room`
  - `test_veto_room_without_zone_blocks_nobody_home`
  - `test_alpha_released_at_cap`
  - `test_alpha_released_when_room_clears`
  - **`test_veto_not_held_when_radar_sole_and_fan_on`** (mutation: drop the breaker → RED)
  - `test_veto_held_when_fan_on_but_motion_witness_on`
  - `test_veto_room_unavailable_does_not_hold`
  - `test_known_resident_in_veto_room_still_holds`
  - `test_veto_ignored_when_already_away`
- Guest-gate fence:
  - `test_non_guest_veto_room_never_arms_guest`
  - `test_guest_kill_switch_does_not_clear_occupied_since`
  - `test_attribute_only_event_keeps_occupied_since`
  - `test_veto_only_room_schedules_inference_on_state_change_only`
- Config:
  - `test_room_lifecycle_loaded_rediscovers_veto_rooms`
  - `test_options_round_trip_room_away_hold_max_h`
  - `test_malformed_cap_value_does_not_break_discovery`

**Live:**
- With GB2 occupied and all phones away: `away_hold = room_veto`, `away_hold_room = Guest Bedroom 2`, and the cap and basis are shown. No AWAY lands while the hold is under the cap.
- Setting GB2 to 0 releases the hold within one tick, with no restart.

### D4: Observability (existing sensor and device, one v8 card)

**Labels.**
- The nobody-home branch sets `_veto_path = "nobody_home"` when it fires.
- The hold labels come from D2/D3.
- `_blocked` (`:6532-6553`) is also True when `_away_hold != "none"` in a home-like **or SLEEP** state. `_veto_path_str` is then `camera_recent` / `room_veto`. The payload shape is unchanged.

**Sticky reason and the AWAY count** (R1 MEDIUM-2, R2v3-M1).
- Increment `_away_entries_today` and set `_last_away_reason` / `_last_away_at` in `_dispatch_house_state_change` (`:7861`, the sole `house_state_log` writer) on any edge into AWAY. That covers inference, override and restore, so the counter and the DB agree by construction.
- The reason is `override` / `restore` when not inferred.
- **Day boundary:** the local date, checked on every periodic tick as well as at increment time, so the count resets at local midnight even without a transition.

**Hydration.** New DAO keyword `count_house_state_changes_since(since_iso, state=None, since_utc=None)`. The new path passes `since_utc` = local midnight converted to UTC, plus `state='away'`, and filters `previous_state IS NULL OR previous_state <> 'away'`. The default call (`_transitions_today`, `presence.py:2582`) stays byte-identical.

**Someone-home estimate** (R1 HIGH-1 note). Incremented at an AWAY edge when any of these was true at entry:
- a camera body was seen within `AWAY_SOMEONE_HOME_EST_LOOKBACK_S` (600 s, rung 1);
- any registered tracker room (guest or veto) was occupied;
- the house was not in SLEEP and `any_zone_occupied` was true.

It does **not** read zone flags in SLEEP, where they are masked. It is not hydrated, and `counts_since` says so.

**Attributes on `sensor.ura_presence_coordinator_presence_house_state`:**
- Reason: `last_away_reason`, `last_away_at`.
- Hold: `away_hold` (`none` / `camera_recent` / `room_veto`), `away_hold_room`, `away_hold_since`, `away_hold_cap_s`, `away_hold_cap_basis`, `away_eligible_at`.
- Camera: `last_camera_body_at`, `last_camera_body_source`.
- Counters: `away_entries_today`, `away_entries_today_someone_home_est`, `away_holds_today`, `counts_since`.
- The live W: `away_camera_quiet_s`.
- `away_hold_age_s` (derivable) goes in **`_unrecorded_attributes`** (R1 LOW-3, R2v3-M2). Every other new attribute stays recorded, because D0 day-7 needs them.

**v8 card** (config, after deploy; snapshot first to `docs/ha-config-snapshots/lovelace_ura_v8_backup_<date>.json`).
- **Placement:** one `sections` grid on the **`people` view** (PICK 7; `now` is the alternative).
- **Heading:** "Away decisions", `heading_style: title`, `mdi:home-export-outline`.
- **Hero:** `custom:button-card`, `template: hero`, on the house-state sensor:
  - `custom_fields.pv`: `[[[ return entity.state.replace(/_/g,' ') ]]]`
  - `label`: `[[[ var a=entity.attributes; if(a.away_hold && a.away_hold!=='none'){ return (a.away_hold==='room_veto' ? 'held by '+a.away_hold_room : 'cameras saw someone · Away from '+(a.away_eligible_at||'?')); } return a.last_away_reason ? 'last Away: '+a.last_away_reason.replace(/_/g,' ') : 'no Away today'; ]]]`
  - colour via `styles.custom_fields.pv` and `styles.icon`: `[[[ return (entity.attributes.away_hold && entity.attributes.away_hold!=='none') ? 'var(--orange-dark)' : 'var(--blue-dark)'; ]]]`. This matches the Energy "Net Tomorrow" card. `variables.color` is static, so it cannot be used for this.
- **Markdown table:** AWAY today, someone-home estimate, holds today, last camera body (age and source), W.

**Tests:**
- `test_nobody_home_sets_label`
- `test_denied_branch_does_not_set_veto_path`
- `test_last_away_reason_sticky_and_set_for_override`
- `test_away_entries_today_resets_at_local_midnight_without_transition`
- `test_away_count_hydration_uses_utc_instant_of_local_midnight`
- `test_count_since_default_unchanged`
- `test_blocked_episode_classifies_camera_recent_and_room_veto_including_sleep`
- `test_someone_home_est_not_masked_in_sleep`
- `test_hold_age_unrecorded`

**Live:**
- `last_away_reason` is never `none` after an AWAY.
- `away_entries_today` equals `COUNT(*)` from `house_state_log` where `state='away'`, `previous_state` is NULL or not `away`, and `timestamp ≥` the UTC instant of local midnight. This holds after a restart too.
- The card renders at phone width on `people`.

### D5: Knob, the guard window (rung 3)
- **Key:** `CONF_PRESENCE_AWAY_CAMERA_QUIET_S = "presence_away_camera_quiet_s"`, default 180.
- **Entity:** `number.ura_presence_coordinator_away_camera_quiet`, unique_id `f"{DOMAIN}_presence_away_camera_quiet_s"`, on the Presence device. Range 0–1800, step 30.
- Cloned from `FanInterferenceHoldNumber` with CM `entry.options` write-back. **The key is added to `OPTIONS_RELOAD_SUPPRESS_KEYS` (`__init__.py:7480`) and `_NO_LIVE_ATTR_KEYS` (`:7359`)** (R2v3-H4b). No in-place apply is needed, because W is read fresh each inference.
- **0 = off.** Name: "Away camera quiet". Description: "How long the indoor cameras must see no one before the house can go Away. 0 = off."
- **Tests:**
  - `test_away_camera_quiet_options_round_trip`
  - `test_away_camera_quiet_zero_disables`
  - **`test_away_camera_quiet_change_does_not_reload_cm`** (mutation: remove from the suppress set → RED)
- **Live:** the entity reads 180 and survives a restart. Moving the slider logs no CM reload.

### D6: Docs (same commit as the build)
- **PRESENCE state of play:**
  - §2: the two new checks and the SLEEP-mask note.
  - §10: rows C1/C3/C4 (Rev 2), C10–C14.
  - Gold patterns: "room veto = guest-room tracker role + radar-sole/fan breaker".
- **HVAC state of play:** §2 `:3260` → `:5184`; one line that the house AWAY edge is guarded (≤ W) and zone vacancy is unchanged.
- **Estimator plan:** `FLOOR_WINDOW_S` is not this knob.
- **README:** the D0 tables, written back.

---

## 8. Numbers and their knobs
| Number | Value | Rung | Why | Kill |
|---|---|---|---|---|
| W | 180 s | 3, Number on the Presence device, reload-suppressed | Live trade-off: flaps vs departures | 0 |
| Per-room cap | GB1 8 h, GB2 8 h (Jaya 0) | 2, room options, live via the room-lifecycle re-discover | P1 longest legitimate run 762 min | 0 |
| Someone-home lookback | 600 s | 1 | Display proxy | n/a |
| Discharge tick | 60 s | existing | reused | — |
| Dwell table | SLEEP 600 / GUEST 300 / HOME_* 120 / WAKING, ARRIVING 60 s | existing `DEFAULT_HYSTERESIS` | Bounds INV-DISCHARGE | — |

---

## 9. Non-goals and fences
- **Unchanged:** the census payload and clamp, guest-gate behaviour, β grace, hysteresis values, HVAC code, door tally, identity, and the schema.
- **No HVAC split.** No AWAY → ARRIVING from room occupancy.
- **Fenced, with tests** (`test_override_away_not_guarded`, `test_restore_not_guarded`):
  - overrides: `select.py:255-278`, `__init__.py:6201`, `presence.py:8017`;
  - boot restore: `apply_restored`, `manager.py:697`;
  - the cold-boot AWAY default (HOUSE-STATE-SENSOR-BOOT-AWAY-DISPLAY-1).
- **Deployment:** one restart in an awake window, then the room config action (D3).

## 10. Parked, with revival triggers
| Item | Why parked | Revival trigger |
|---|---|---|
| **Jaya Bedroom as a veto room** | Fan/phantom loop (§3.3); all 507 measured minutes were fan-on, with an LD2410-only hold | A fan-immune witness (ZV or PIR) installed in Jaya Bedroom, **or** an LD2410 retune, then a P3 re-measure: 0 fan-on/empty phantom minutes over 7 days and 0 verified-empty absences swallowed. Then set the cap by config; no code. Related card: HVAC-NIGHT-LENIENCY-DEGRADATION-DEFENSE-1 |
| Census estimator / door tally | As Rev 3 | D0 SH > 2.3 traced to rooms that are blind to both cameras and radars, AND door attach ≥ 60 % |
| Veto on all radar rooms | P3: 3 of 10 departures never reach AWAY | Per room: passes P3's two controls, then added by config |
| **Study A sensor fix** | Hardware/operator | **No card exists.** Orchestrator to mint `STUDYA-ZK-EMPTY-HOLD-1`. Also card the Exercise Room ZK never being on (a new finding) and the absence of a trusted Master Bathroom sensor |
| HVAC unguarded read | New published state | A D0 departure where a zone stayed on comfort > 5 min solely because of the house-edge delay |
| Separate discharge timer | The isolated periodic suffices | D0 discharge later than B + W + 60 s + dwell |
| `face_recognized_count` column, or persisting the reason in `house_state_log.trigger` | Schema / persisted-value change; `memory_episodes` plus the two-run D0 cover it | D0 day-14 cannot classify AWAY rows from `memory_episodes` (retention is the binding limit, not exclusion; R1 MEDIUM-3) |

## 11. Operator PICKs (defaults in bold)
1. **Guard window W:** **180 s** / 300 s / 0.
2. **Veto rooms and caps:** **GB1 8 h + GB2 8 h** / guest rooms plus Jaya at 16 h (rejected by the plan: the fan loop, §3.3; only after the §10 trigger) / none.
3. **Body predicate:** **unidentified OR face** / unidentified only.
4. **HVAC split:** **none** / an HVAC read that ignores the guard.
5. **Someone-home estimate on the sensor:** **yes, the SLEEP-safe proxy** / omit.
6. **Residual:** **accept ≈ 2.1/day ordinary and ≈ 10/day Jaya+guest as this cycle's outcome; next lever = the sensor cards** / hold the build for the sensor fixes.
7. **v8 card view:** **`people`** / `now`.

## 12. Claims found WRONG
Rev 2's C1–C9 stand. Rev 3 added:
- **C10:** HVAC handler at `hvac.py:5184`.
- **C11:** no `now=` is passed to `infer()`.
- **C12:** holistic §5.2's clause (2).
- **C13:** a known resident still counts for the veto.

Rev 4 adds:
- **C14 (Rev 3 self-correction, R1 HIGH-1):** "nobody-home and β cannot fire while a veto room is occupied, because the zone flags carry it" is false during house SLEEP (`set_sleep` overrides every zone tracker), and false for a room in no zone.
- **C15 (Rev 3 self-correction, R2v3-H1):** "guard fall-through equals today's path" is false. The fall-through reaches SLEEP, GUEST or HOME_*, which start new dwells. The guard now returns `None`.
- **C16 (Rev 3 self-correction, R2v3-H2 / R1 MEDIUM-1):**
  - "boot-seed from `last_changed` counts the real run" is false: `last_changed` is rewritten at boot.
  - "P3 control numbers bound veto B" is false for a fan-susceptible radar: P3 is open-loop.
- **C17 (Rev 3 self-correction, R2v3-H4):**
  - "set the caps after deploy" did nothing without a re-discover hook.
  - Cloning the Number without its suppress-key entry reloads the CM.
- **C18 (Rev 3, R1 MEDIUM-3):** "D0 at 14 days from recorder history" exceeds the 7-day retention.

## 13. Tier
**Tier 3.** Required:
- the re-verify decision on Rev 4 (orchestrator);
- four build reviews:
  - A: local correctness;
  - B: state machine and lifecycle, covering INV-GUARD-HOLDS-STATE, the try-block isolation, the lifecycle re-discover and unsubs, hydration;
  - C: per-site mutation over the D1–D5 anchors;
  - D: adversarial completeness against §2. Targets: the fan loop with the breaker in place, the SLEEP mask, a room with no zone, restart storms versus `cap_basis`, the kill-switch interplay;
- the orchestrator re-greps every `return HouseState.AWAY` and every reader in the §7 D3 table, and re-runs one mutation;
- an operator checkpoint before deploy;
- ura-super-builder.

## 14. Self-check against the Tier-3 plan-review requirement (planner; not a substitute for reviews)
- [x] Prior-art table re-grepped; new pieces listed and justified; every REUSE the reviewers found is added (P5b, P5c, P5d).
- [x] Invariants restated; INV-DISCHARGE now uses the real dwell table and names its three preconditions (isolated periodic, `cap_basis`, fan breaker).
- [x] All three `return HouseState.AWAY` sites carry both checks; reader table complete (12 sites).
- [x] Consumers include HA automations (wall panels) and `const.py:2344`.
- [x] Every number on the ladder; both knobs have a live path that needs no restart and no CM reload.
- [x] D0 table discriminates, including the loop row; runs inside the 7-day retention.
- [x] Residual restated with the Rev 4 numbers.
- [x] All three Rev 3 opens are resolved by the reviewers: view `people`; attributes are recorded but retained 7 days; no automation reads someone-home.
- [ ] **Open for the build:** confirm that the new room key is not in a room-level reload-suppress set (D3); confirm that `data[STATE_RADAR_SOLE_TICK]` is published for the guest rooms' current sensor mix (MS600 Matter in `presence_sensors`, the Meross motion bit and the Hobeian in `motion_sensors`).

---

## 15. Review findings → resolution (Rev 3 reviews)

| ID | Sev | Finding | Resolution | Where |
|---|---|---|---|---|
| R1 HIGH-1 | HIGH | SLEEP masks the zone flags, so nobody-home fires AWAY with a sleeper in a veto room | Veto on **all three** branches; INV-B restated; SLEEP test; estimate input fixed; C14 | §2, §3.1, D3, D4, §12 |
| R1 MED-1 | MED | `last_changed` boot seed resets the cap each restart; `became_occupied_time` REUSE missed | Seed from the restored `_became_occupied_time`; `cap_basis` attribute; tests renamed | P5b, §2, D3 |
| R1 MED-2 | MED | Hydration compares local date vs UTC; no midnight reset without a transition | DAO `since_utc` + state filter; reset on the periodic tick; honest live oracle | P12, D4 |
| R1 MED-3 | MED | D0 needs 14 days of recorder data; retention is 7 | D0 runs at day 7 (extract saved) and day 14 (URA DB + `memory_episodes`); parked trigger reworded | D0, §10, C18 |
| R1 MED-4 | MED | Missed consumers: wall-panel automations, chain/AI-rule class, `const.py:2344` | Added to §3.4 | §3.4 |
| R1 LOW-1 | LOW | Hysteresis bound understated | Dwell table in INV-DISCHARGE; `test_discharge_dwell_table` | §2, D2, §8 |
| R1 LOW-2 | LOW | Inference fan-out on attribute events | Veto-only rooms schedule inference on state change only | D3 table |
| R1 LOW-3 | LOW | Recorder write amplification | `away_hold_age_s` unrecorded; `away_hold_since` published | D4 |
| R1 LOW-4 | LOW | Citation drift | `__init__.py:6201`, switch slug, `_count_transition` `:7451` | §1.2, §9 |
| R1 opens (a)(b)(c) | — | View / recorder / automations | `people`; recorded, 7 d; none | D4, §14 |
| R2v3-H1 | HIGH | Guard fall-through enters SLEEP/GUEST/HOME and starts a 600 s dwell | Guard returns `None` (hold state); the veto falls through; INV-GUARD-HOLDS-STATE; two tests; C15 | §2, D2 |
| R2v3-H2 | HIGH | Fan/veto loop; cap resets on restart | Breaker (iii) radar-sole AND fan-on → no hold (REUSE); **Jaya dropped from defaults** (no breaker keeps its benefit); restored run start; D0 loop row; C16 | §3.3, D3, D0, §6, §10, PICK 2 |
| R2v3-H3 | HIGH | Periodic registration shares the discovery try-block | Registration moved out; per-room parsing wrapped; test plus mutation | D2 |
| R2v3-H4 | HIGH | (a) caps need a restart; (b) the knob reloads the CM | (a) `SIGNAL_ROOM_ENTRY_LIFECYCLE` re-discover; config order stated. (b) suppress-key + no-live-attr entries; no-reload test; C17 | D3, D5 |
| R2v3-M1 | MED | AWAY count vs oracle (UTC, override AWAYs) | Count at `_dispatch_house_state_change`; UTC instant; previous-state filter | D4 |
| R2v3-M2 | MED | Recorder growth | `away_hold_age_s` unrecorded; the rest kept for D0 | D4 |
| R2v3-M3 | MED | Reader table under-specified | 12-row disposition table plus two tests | D3 |
| R2v3-M4 | MED | No `presence` view; static colour variable | `people` view (PICK 7); JS-templated label and colour written out | D4, P14 |
| R2v3-M5 | MED | Veto room with no zone | Covered by the all-branch veto; `test_veto_room_without_zone_blocks_nobody_home` | D3 |
| R2v3-L1 | LOW | Stamp gated on W > 0 → stale B when turned on | Stamp unconditionally | §3.2, D1 |
| R2v3-L2 | LOW | Denied branch label ambiguous | A denied branch leaves `_veto_path` alone | D2 |
| R2v3-L3 | LOW | `nobody_home` value persisted even at W = 0 | Stated in INV-BYTE-ID; no value consumers | §2 |
| R2v3-L4 | LOW | `None` stamp raises | `None` is quiet | D2 |
| R2v3-L5 | LOW | Stale hold on early returns | Mirrored hold reset on early returns; test | D2 |

**Rejected:** none. **Adapted:**
- R2v3-H2 offered "a lower Jaya cap". That was rejected in favour of dropping Jaya, because a lower cap still holds an empty house for the full cap after every fan-on departure.
- R1 MED-3 offered "persist the reason in `house_state_log.trigger`". Rejected as a persisted-value change; the `memory_episodes` D7 snapshots already carry the labels with URA retention.
