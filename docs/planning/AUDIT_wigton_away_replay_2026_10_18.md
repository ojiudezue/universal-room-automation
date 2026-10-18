# Wigton AWAY-flap replay (read-only) - 2026-10-18

Generated Sun 2026-10-18 10:47 CDT by ura-prober. Nothing was changed on Wigton (ssh reads of `/config/.storage/*` and `sqlite3 mode=ro` on `/config/home-assistant_v2.db` only). URA is disabled on Wigton, so this is a **simulation of presence.py's three AWAY branches over Wigton's recorder history**, not an observation of URA. Method follows `AUDIT_census_arc_and_away_holistic.md` (P0-P3) and the Rev 4 plan `PLANNING_house_away_flap_untracked_occupant.md`; room-sensor method follows `AUDIT_wigton_sensor_settle_and_replay_2026_10_17.md`. Read first: `docs/architecture/SENSOR_FLEET_CLASSES.md`. Not read: the two Coordinator STATE_OF_PLAY docs (the brief did not name them; the plan's Rev 4 text was the spec used).

Scripts and extracts (not in repo): `/private/tmp/claude-501/-Users-okosisi-Code-universal-room-automation/75cc297f-1426-4620-b7aa-da058bc0fab0/scratchpad/wg/` (`sim.py`, `an.py`, `an2.py`..`an4.py`, `gaps.py`, `states.json`, `cams.json`).

## Answer first

1. **Wigton cannot show the problem the plan fixes, and Rev 4 barely moves it.** Wigton has exactly **one enrolled person** (`person.omonele`, one live phone) that is home 99% of the time, so the tracked-phone branches almost never fire. In the 7.45-day settled window (10-11 00:00 to 10-18 10:41 CDT) the simulation gives **4 AWAY entries today (0.54/day), all with someone home**, and **3 under Rev 4 (0.40/day)**. Confidence **low on the rates (n=4), medium on the direction**.
2. **Guard A is inert on Wigton.** There is no interior camera (9 UniFi Protect cameras, all exterior by name; no URA camera config; face recognition off). The body stamp never moves, `None` counts as quiet, so A changes nothing. Confidence **high**.
3. **Veto B on the two guest bedrooms removed 1 of 4 entries and delayed 1 by 9 minutes** (10-11: AWAY 10.0 min after the phone left instead of 1.0). 0 false holds. Confidence **low** (2 hold episodes, 11 ticks).
4. **Departures within 15 min: cannot be scored.** There is **no verified whole-house departure** in 7.45 days (house was occupied 86% of the time by radar, longest all-room silence 92 min and the phone was home). Phone-departure proxy: 4 of 4 reach AWAY within 15 min today (0.6-1.0 min), 3 of 4 under Rev 4 (one absorbed, one delayed to 10 min). Confidence **low**.
5. **If census is 0 while the phone is home (stress case S0), the picture is far worse**: 251 AWAY entries (33.7/day) today, 209 (28.1/day) under Rev 4, 86% of them SLEEP-mask loops (below). This is a scenario, not a prediction. Confidence **low**; it matters because it shows which assumption carries the whole result.

## 1. Evidence inventory (all read from Wigton, 2026-10-18 10:40 CDT)

| Evidence | What exists | Source |
|---|---|---|
| Person entities | **1**: `person.omonele`, 6 mobile_app trackers (`phalanxiphone15promax`, `madroneair`, `okosisipadmini6_481`, `m4_desktop`, `m1_air`, `omonele_android`) | `.storage/person`, `core.entity_registry` |
| Which tracker actually reports | Only `device_tracker.omonele_android` (958 rows, home/not_home). Others are `unknown`/`unavailable` (iPhone 485 rows, all unknown/unavailable; Macs/iPad 2-34 rows unknown). `person.omonele` therefore equals that one Android phone | recorder (`q1.py`) |
| Other residents | Not enrolled. UniFi shows other phones (Josephine, Ngozi, Chima, Uche, ...) but those `device_tracker.*` entities are `disabled_by: integration` (no states) | `core.entity_registry` |
| URA tracked persons | `["Omonele"]` (Home entry), `domain_coordinators_enabled: false`, `presence_coordinator_enabled: false`, `face_recognition_enabled: false`, `egress_identity_enabled: false` | `core.config_entries` |
| BLE room trackers | **None.** `bermuda` entry has only 4 global count sensors; one `ibeacon` tracker (unavailable); no per-device trackers | `core.entity_registry` |
| Interior cameras | **None found.** 9 UniFi Protect cameras: backyard, right_front, left_side, outdoor_kitchen, front_doorbell, balcony_driveway, back_gym, right_side, upstairs_balcony. Exterior by name only (mounting not verified). They raise ~149 `person_detected` events/day (street traffic) | registry, recorder (`cam.py`) |
| Doors | **No door/window contact sensors, no locks.** Only two Overkiz covers (`all_house_gym_french_doors`, `all_house_primary_slider_door`, device_class blind). No door crossings exist for an egress/entry signal | registry |
| URA room entries (all disabled_by user) | 18 rooms + "House" (House room's only sensor is URA's own `anyone_home`, disabled) | `core.config_entries` |
| Zones (Zone Manager) | Back hallway, Entertainment Zone, Master Suite, Upstairs Zone. **Gym and House have no zone** (rooms carry a `zone` option; Gym has none) | `core.config_entries` |
| Guest rooms | **No room has `room_is_guest_room`.** "Down Guest Bedroom" (Back hallway zone) and "Up Guest Bedroom" (Upstairs zone) are guest rooms by name only, one radar each | `core.config_entries` |
| Fans | `room_fan_mode: off` in every room; no room fan entities configured, so the plan's radar-sole + fan-on breaker (iii) never trips | `core.config_entries` |

### Room sensors, classified by device model (never by name)

| Class (SENSOR_FLEET_CLASSES) | Devices | Rooms |
|---|---|---|
| **ZG-204ZX** (HOBEIAN "24Ghz millimeter wave and T&H sensor"): presence radar, holds a still person, fan-susceptible | **17**: Chinenye, Down Guest Bedroom, Kelechi, Grandma, Up Guest Bedroom, Formal Dining, Game Room, Gym, Kitchen, Laundry, Living Room, Master Bath (2 units: bath + shower), Master Bedroom, Media Room, Receiving Room, Study | all filed under `occupancy_sensors` (the combined list), not `presence_sensors` |
| ecobee ECB501 remote sensor (PIR-class motion) | 3 `*_motion` entities | Game Room, Down Guest Hallway, Study Hallway (`motion_sensors`) |
| ZV motion-class, ZK presence radar, MS600, LD2410 | **none on Wigton** | n/a |

Config drift since the 10-17 replay: Game Room, Down Guest Hallway and Study Hallway were edited 2026-10-18 02:42 UTC (21:42 CDT 10-17), 26 minutes after the earlier replay. The three Ecobee `*_occupancy` entities are **no longer** in `occupancy_sensors` (the earlier audit's "phantom" sources). This simulation uses the current config. Occupancy timeouts are the entry options (120-1800 s, per the 10-17 table).

## 2. "House occupied" ground truth (assumptions)

- **A1.** `person.omonele` = one Android phone carried by one resident. When it is `home`, at least that resident is home (no forgotten-phone case modelled; it cannot be detected, since no other identity source exists).
- **A2.** Other residents (the household has several; rooms named Chinenye, Kelechi, Grandma, two guest rooms) are untracked. Their presence is only visible as radar/PIR activity.
- **A3.** A ZX radar `on` = a body or a phantom; there is no second sensor in 16 of 18 rooms to tell them apart (SENSOR_FLEET_CLASSES: ZX is fan-susceptible).
- **A4.** Window = 10-11 00:00 CDT to 10-18 10:41 CDT (7.45 d), the settled post-tune period (10-10 tuning; Master Bath etc. later). Phone history starts 10-08 but no phone-away occurs before 10-11.

Observed:
- Phone away intervals (`person.omonele`, identical to `omonele_android`): 10-11 11:27-12:16 (49.1 min), 10-13 05:52-05:57 (5.2), 10-13 20:36-20:42 (5.7), 10-16 06:24-06:26 (2.7); plus three sub-second blips (10-11 09:48:57, 10-12 21:57:01-02, 10-14 09:43:53) that a 60 s tick would not sample. Total phone-away time about 62 min of 7.45 days.
- **In all four phone-away episodes other rooms were active** (10-11: 14 rooms; 10-13 05:52: Game Room, Kelechi, Master Bedroom; 10-13 20:36: 6 rooms; 10-16: 5 rooms). So the house was never empty when the phone left.
- Any radar/PIR was on 86.2% of the 7.45 days; every hour of 7 whole days had activity. 355 silent gaps; 281 under 5 min; only **6 gaps over 30 min**, longest 92 min (10-15 08:13-09:45, a weekday morning, phone home; empty-house or deep still sleep is unknowable here).
- Conclusion: **ground truth is "occupied" for essentially the whole window**; there is no verified empty period to score departures against.

## 3. Simulation

Model (approximate, `sim.py`): 60 s ticks over the three branches of `infer()` (nobody-home `presence.py:1127-1131`, path alpha `:1170-1181`, path beta `:1248-1288`), `DEFAULT_HYSTERESIS` (`house_state.py:129-139`: AWAY 30, ARRIVING 60, HOME 120, SLEEP 600, WAKING 60 s), sleep hours 23-06 (`const.py:3116`, default; not set in Wigton's entry), zone-tracker occupancy = room sensors on + room timeout, zone flags masked during SLEEP (`presence.py:930-936`, `:5975-5992`). Gym and House are in no zone. Path beta is not modelled separately: the phone never goes `unavailable`, so beta adds nothing alpha does not already fire first.

Not modelled: zone-tracker timers beyond room timeouts, guest gate (no guest rooms flagged, no cameras), waking sustained-occupancy gate, boot settle, person-coordinator lag/trust matrix (assumed ACTIVE away), event-driven (non-tick) inference.

**Census scenarios (the decisive assumption):**
- **S1 (base).** `census_count = 1` while the phone is home, 0 when away. Basis: `camera_census._get_ble_persons` (`camera_census.py:2671-2686`) counts any person whose location is not `away/unknown/""`, and `person_coordinator` stamps a GPS-home person as location `"home"` (`person_coordinator.py:330-345`, `:382-383`). So a home phone yields census >= 1 even with no BLE or cameras. Not verified live (URA is off).
- **S0 (stress).** `census_count = 0` always (no person data, no cameras, no BLE).

**Rev 4 as simulated.** Guard A (W = 3 min): inert (no interior cameras, see section 1). Veto B (all three branches, fall-through, cap 8 h, run start = start of the room's occupied run): Down Guest Bedroom + Up Guest Bedroom; fan breaker inert (no fans). Sensitivity: B on all 17 rooms.

### Results (10-11 00:00 to 10-18 10:41 CDT, 7.45 d)

| Metric | Today S1 | Rev 4 S1 | Today S0 | Rev 4 S0 |
|---|---|---|---|---|
| AWAY entries (per day) | 4 (0.54) | 3 (0.40) | 251 (33.7) | 209 (28.1) |
| ...with someone home (phone home at entry, or radar on within 5 min / sustained 3 min) | 4 of 4 | 3 of 3 | 251 of 251 (phone) / 202 (radar only) | 209 / 160 |
| Entry path (prev state, branch) | alpha 3, SLEEP-nobody 1 | alpha 2, SLEEP-nobody 1 | SLEEP-nobody 216, HOME-nobody 30, alpha 3, ARRIVING-nobody 2 | SLEEP-nobody 175, HOME-nobody 30, alpha 2, ARRIVING-nobody 2 |
| Days with more than 1 entry | 1 (10-13) | 1 | all 8 days | all 8 days |
| Total hours in AWAY | 1.0 | 0.8 | 14.0 | 13.2 |
| Phone departures reaching AWAY within 15 min (4) | 4 (0.6-1.0 min) | 3 (one at 10.0 min, one absorbed) | n/a | n/a |
| Veto hold ticks / episodes | n/a | 11 / 2 | n/a | 769 / 13 (12.8 h) |
| Holds with no other room active within 5 min ("false hold" upper bound) | n/a | 0 of 11 | n/a | 95 of 769 (12%) |

Per-event (S1):
- 10-11 11:27 phone away 49 min; 14 rooms active. Today AWAY at 11:28. Rev 4: Up Guest Bedroom occupied, veto holds 11:28-11:36, AWAY at 11:37.
- 10-13 05:52 phone away 5 min, state SLEEP: AWAY at 05:53 via nobody-home because the SLEEP mask hides occupied zones (Game Room, Kelechi, Master Bedroom were active). Rev 4 unchanged (no guest room occupied).
- 10-13 20:36 phone away 6 min: alpha at 20:37, unchanged.
- 10-16 06:24 phone away 2.7 min: alpha at 06:25; Rev 4 holds (Down Guest Bedroom occupied) and the phone returns, so no AWAY.

Sensitivities:
- **B on all 17 rooms (S1):** 1 entry (0.13/day), holds 28 ticks / 4 episodes. It "fixes" every flap here because the house is always occupied, which says nothing about its cost on real departures (plan P3: 3 of 10 never reach AWAY). Cannot be scored on Wigton (no verified departure).
- **B on all 17 rooms (S0):** 51 entries (6.9/day), 6,460 hold ticks (108 h).
- **Exterior cameras treated as bodies (not the plan's design):** guard A would hold 1 of 4 entries (10-11, an exterior person 0.6 min earlier) and, with ~149 exterior person events/day, would hold a real departure near the street almost always. Not recommended.

### What carries the result

1. **One enrolled phone.** Everything in S1 is "Omonele's phone left, others stayed". That is alpha ignoring rooms, the same failure the plan describes, but at 0.5/day instead of 2.5/day because Wigton's phone is almost always home.
2. **SLEEP mask (plan C14).** The nobody-home branch needs `census_count == 0` and no zone occupied. In S1 it fired once, when the phone left during SLEEP. In S0 it fires after every SLEEP entry (zones masked, census 0): SLEEP -> AWAY after the 600 s dwell -> ARRIVING -> HOME -> SLEEP again, about 30 times a day. Rev 4's all-branch veto only helps if a *guest room* is occupied.
3. **Guard A needs a camera.** With none, Rev 4 on Wigton is veto B only.

## 4. Confidence per number

| Number | Value | Confidence | Why, and what would change it |
|---|---|---|---|
| Interior cameras: none; guard A inert | n/a | **High** | Registry + config: 9 Protect cameras, none in a URA camera map; face recognition off. Risk: a camera named like an exterior one is actually indoors (names only). |
| Fleet classification (17 ZX, 3 ecobee PIR, nothing else) | n/a | **High** | Device registry `model_id` read directly. |
| No doors, no BLE, no other identity source | n/a | **High** | Registry; bermuda has 0 tracked devices. |
| House occupied ~86% by radar, never silent > 92 min | n/a | **Medium** | Radar-only (ZX, fan-susceptible, A3); a phantom would inflate it. 7.45 d only. |
| Someone-home AWAY entries today S1 | 4 (0.54/day) | **Low** (rate), **Medium** (all four were false) | n=4; depends on S1, on the person coordinator marking the phone ACTIVE-away, and on the 60 s tick. |
| Someone-home AWAY entries Rev 4 S1 | 3 (0.40/day) | **Low** | Same; one absorbed + one delayed rests on 2 hold episodes, 11 ticks. |
| Departures within 15 min | 4/4 today, 3/4 Rev 4 (phone proxy); whole-house: unscorable | **Low** | No verified departure; phone proxy is not a house departure. |
| False holds | 0 of 11 (S1); 95 of 769 uncorroborated (S0) | **Low** | The guest rooms have one radar each, so "corroborated" means another room was active, not that the guest room is truly occupied. |
| S0 numbers (33.7 to 28.1/day) | n/a | **Low** | Depends wholly on census = 0 while the phone is home, which the code contradicts if Omonele is a tracked person (S1). Useful as a bound and as proof the SLEEP mask is the dominant risk when census inputs are missing. |

**Biggest assumption risks, in order:**
1. **Census composition (S0 vs S1).** Unverified on a disabled install. If Wigton's `person_coordinator` does not yield location "home" for Omonele (e.g. the person is excluded or untracked), S0 applies and the AWAY rate is ~30/day.
2. **Phone semantics (A1).** One Android phone stands for the household's tracked state. A phone left home hides real departures (the 92-min 10-15 gap would be a miss), and its movement tells us nothing about the unenrolled residents.
3. **Guest rooms are not flagged.** The simulation assumes the operator sets a cap on "Down Guest Bedroom" and "Up Guest Bedroom"; today they have no guest flag and no cap field exists until Rev 4 ships.
4. **Radar truthfulness (A3).** Every "occupied" is a single ZX radar except Game Room, Down Guest Hallway, Study Hallway (ecobee motion) and Master Bath (two units).
5. **Sleep hours (23-06) and room timeouts** are defaults/last-known, not read from a live URA instance.

## 5. What this does and does not tell the operator

- Wigton is a poor proving ground for Rev 4's A and for the departure clauses: no cameras, no doors, one phone, no verified empty periods.
- It does flag one design property: **with weak census inputs the nobody-home branch plus the SLEEP mask can dominate**, which is exactly plan finding C14 and which Rev 4's guest-room veto does not address. If URA is enabled at Wigton, either keep census >= 1 while a phone is home (S1) or confirm it before enabling.
- Nothing here changes the plan's main-house numbers.
