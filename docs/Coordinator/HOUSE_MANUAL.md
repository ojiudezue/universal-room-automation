# House Manual — Rooms, Zones, and the House (Operator Manual)

**Audience:** the homeowner running URA.
**Scope:** how the living tier (rooms, zones, house) actually behaves —
what turns your lights on, what decides you're home, what to watch,
and how to intervene without fighting the system.
**Current through:** URA v5.23.0 (see `const.py:34`).

This is the sibling of `ENERGY_COORDINATOR_MANUAL.md` and
`HVAC_COORDINATOR_MANUAL.md`. It is NOT a code walkthrough. For per-
coordinator design see `PRESENCE_COORDINATOR.md`, `COORDINATOR_ARCHITECTURE.md`,
and the planning docs under `docs/planning/`.

---

## 1. What this tier actually does

The "living tier" is three concentric loops:

1. **Room tier** (`coordinator.py`, `automation.py`) — per-room
   occupancy from motion / mmWave / occupancy sensors, extended by
   camera and BLE; entry and exit actions on lights, fans, covers;
   humidity-fan / bathroom-exhaust behavior; temperature-driven fan
   speed. One `UniversalRoomCoordinator` per configured room.
2. **Zone tier** (`domain_coordinators/presence.py` +
   `aggregation.py`) — a **house zone** is a group of rooms you defined
   for aggregation (occupancy roll-up, music following, HVAC zone
   assignment). See §2 on the house-vs-HVAC-zone distinction.
3. **House tier** (`domain_coordinators/house_state.py` +
   `presence.py`) — one state machine
   (`HouseState`) whose value is one of
   `away / arriving / home_day / home_evening / home_night / sleep / waking / guest`
   (`house_state.py:22-32`). Every downstream coordinator (HVAC,
   Energy, Safety, Notifications) reads this.

Occupancy flows **upward** (room ⇒ zone ⇒ house). Actions flow both
ways: entry/exit actions fire at the room, while sleep/guest/away
biases from the house feed back into room automation and HVAC presets.

---

## 2. House zones ≠ HVAC zones

Operator-corrected 2026-07-12 — this is a common source of confusion.

- **HVAC zones** are the Carrier Infinity zones keyed by the
  thermostat entity (3 of them at this deployment).
- **House zones** are the URA rooms/zones you configured per area.
- **One HVAC zone maps to MULTIPLE house zones by design.**

Compound names like "Entertainment + Master Suite" on an HVAC zone
entity are the *legitimate* merge, not a bug. Do not try to split them.
Full detail in `HVAC_COORDINATOR_MANUAL.md §2`.

---

## 3. How a room decides (in plain language)

### 3.1 The occupancy pipeline (`coordinator.py`)

For each room, every ~30 s (`SCAN_INTERVAL_OCCUPANCY`, `const.py:41`):

1. **Read the three sensor lists** you configured — `motion_sensors`,
   `presence_sensors` (mmWave), and `occupancy_sensors`
   (`const.py:333-335`).
2. **Grace-hold if all input sensors are unavailable** — freeze the
   previous occupied state for the unavailability grace window
   (`coordinator.py:1488-1500`). The room state won't flap while your
   Zigbee coordinator reboots.
3. **Ignore stuck sensors** — any sensor stuck ON longer than the
   stuck-sensor threshold is dropped from the vote
   (`coordinator.py:1513-1523`).
4. **Debounce entry** — sensors must stay active for
   `occupancy_debounce` (default 150 ms UI, `const.py:686`) before
   confirming a NEW occupancy. Prevents a single glitch strobing lights.
5. **On active detection:** mark occupied, seed `_last_motion_time`,
   reset failsafe (`coordinator.py:1628-1644`).
6. **On no detection:** run the timeout — remain occupied until
   `occupancy_timeout` (default 300 s = 5 min, `const.py:685`;
   room-type defaults in `ROOM_TYPE_TIMEOUTS`, `const.py:724`) has
   elapsed since last motion.
7. **Camera extend (v3.5.1)** — if timed out but a camera person
   sensor for this room's area is still ON, keep occupied
   (`coordinator.py:1756-1785`). Skipped when the failsafe has fired.
8. **BLE extend, never create (v5.22.0-era `ble_extend_not_create`,
   `coordinator.py:1794-1892`)** — BLE evidence from Bermuda may
   **extend** an existing motion-confirmed occupancy but **never
   create** one. Two admission legs:
   - **CHAIN** — the room was occupied on the previous update tick;
     a still-body BLE hold extends as long as the person is reported
     present, OR
   - **MOTION** — real motion within
     `BLE_MOTION_CONFIRM_MULTIPLIER × occupancy_timeout`
     (`BLE_MOTION_CONFIRM_MULTIPLIER = 2`, `const.py:375`).
   Kill switch: set the multiplier to `0` to disable the BLE hold
   path entirely.
9. **Failsafe (v4.5.15)** — regardless of sensors, a room cannot
   remain occupied longer than its failsafe duration
   (`DEFAULT_FAILSAFE_DURATION_SECONDS = 4 h`, `const.py:748`; 60 min
   for closets and bathrooms, `ROOM_TYPE_FAILSAFE_DURATIONS`,
   `const.py:749`). The failsafe only fires when the raw signal is
   *stale* — if a Tier-1 sensor is still reporting activity within
   `2 × occupancy_timeout`, the failsafe defers
   (`coordinator.py:1731-1754`). **The failsafe does NOT bound BLE-
   sustained occupancy** — BLE ticks don't set the failsafe timer's
   `occupied=True` at check time; forgotten-phone mitigation lives in
   `PersonPhoneLeftBehindSensor`, not here (documented at
   `coordinator.py:1823-1828`).
10. **Fan-noise recheck (v4.7.22 Mode-2)** — see §3.4 below.

### 3.2 Entry action — what turns lights on

`automation.py:_control_lights_entry` (see :650-697):

- If sleep hours AND night_lights configured → turn on ONLY the
  night_lights with the `sleep` preset (dim/warm defaults 15 % / 2000 K,
  `const.py:528-529`). Regular lights are actively turned off.
- Otherwise, read `entry_light_action` from the room config
  (`CONF_ENTRY_LIGHT_ACTION`, `const.py:539`; values `none / turn_on /
  turn_on_if_dark`, `const.py:547-549`).
- `turn_on_if_dark`: read illuminance and compare against
  `illuminance_dark_threshold` (default 20 lx, `const.py:687`). Below
  → turn on. Above → skip.
- If night_lights exist and it's day, they also turn on with `day`
  preset defaults (100 % / 4000 K, `const.py:530-531`).
- Brightness and transitions honor `light_brightness_pct` (100 %),
  `light_transition_seconds_on` (1 s), `_off` (3 s)
  (`const.py:691-693`).

### 3.3 Exit action — what turns lights off

`_control_lights_exit` (:699-729): if `exit_light_action` is
`turn_off` (the default) and lights are configured, they turn off with
the configured transition. Any other setting (`leave_on`, etc.) short-
circuits.

### 3.4 Fan-noise recheck (Mode-2 BLE-gated pause + recheck, v4.7.22)

When a room's occupancy is being driven by mmWave alone AND a fan is
suspected of shaking the mmWave, the presence coordinator can
briefly PAUSE the fan, spin down, watch mmWave, and either:
- release the pause (fan-coupled false positive → drop occupancy), or
- restore the fan (real person, keep occupancy).

Knobs (all in the room's options flow):
- `fan_recheck_enabled` — master per-`PresenceCoordinator`, default
  `False` = opt-in (`const.py:412`).
- `room_fan_recheck_enabled` — per-room opt-in, default `True`
  (`const.py:418`).
- `fan_recheck_arm_delay_s` = 60 (`const.py:437`) — settle before pause.
- `fan_recheck_spindown_s` = 30 (`const.py:441`).
- `fan_recheck_window_s` = 60 (`const.py:446`) — mmWave observation window.
- `fan_recheck_cooldown_s` = 1800 (`const.py:450`) — per-room rate limit.
- `fan_recheck_max_per_hour` = 2 (`const.py:454`) — hard ceiling; 0 disables.
- `fan_recheck_mmwave_history_ticks` = 3 (`const.py:462`).
- `ROOM_TYPE_RECHECK_FACTOR` — bedroom / media_room get 2× the window
  as a **conservatism dial**, not an eligibility gate (`const.py:466`).

High-still-risk types (bedroom, media_room) get the widened window so
a napping body isn't yanked. Master bedroom fan pause defaults SLEEP-
only in the operator's setup — see `HVAC_COORDINATOR_MANUAL.md §3.4`.

### 3.5 Humidity fan / bathroom exhaust

`automation.py:1745-1985` (grep `humidity_fan_`) drives configured
`humidity_fans` off the room's `humidity_sensor`:

- **Threshold** (`humidity_fan_threshold`, default 60 %, `const.py:702`)
  turns the fan on.
- **Hysteresis** (10 pp, `const.py:705`) — OFF at `threshold − 10`.
- **Min runtime** (`humidity_fan_timeout`, default 600 s = 10 min,
  `const.py:703`) — the fan won't turn off before this once it comes on.
- **Max runtime** (`humidity_fan_max_runtime`, default 3600 s = 60 min,
  `const.py:704`) — force-off cap for stuck sensors.
- **Spike detection (D2)** — EMA baseline; +10 pp above baseline
  triggers, ~45 min time constant (`const.py:631-633`).
- **Presence-proportional post-runtime (D3)** — after occupancy ends,
  runtime = `base + per_min × occupied_minutes`, capped
  (60 s / 30 s per min / 600 s cap, `const.py:640-642`).
- **Wet-room flag** (`wet_room`, `const.py:622`) — defaults True for
  `room_type == bathroom`. Gates the sleep-policy exemption in
  `automation.py`.

### 3.6 Temperature-driven fan control

`fan_control_enabled` toggles per-room comfort fan behavior. Speeds
step at `fan_speed_low_temp` / `_med_temp` / `_high_temp` (default
69 / 72 / 75 °F, `const.py:699-701`). Interacts with HVAC via
`hvac_coordination_enabled` — see HVAC manual for the handshake.

### 3.7 Sleep protection & sleep-bypass

`sleep_protection_enabled`, `sleep_start_hour` / `_end_hour` (defaults
22 / 7, `const.py:719-720`), `sleep_bypass_motion_count` (default 3,
`const.py:721`) — during sleep hours, N motion events are required
before URA takes an entry action. `fan_sleep_policy` = `off / reduce /
normal`, default `reduce` (`const.py:654`).

---

## 4. How a zone decides

Zones are configured through the Zone Manager entry (`CONF_ZONE_*`,
`const.py:64-76`). Each zone lists rooms; the zone's occupancy is a
roll-up of its rooms. Key items:

- `zone_is_outdoor` (default False, `const.py:72-73`) — outdoor
  zones still track raw occupancy but are **excluded from the indoor-
  occupancy aggregate** that gates the v5.7.0 AWAY path. A porch
  camera can't block the house going AWAY when everybody's out.
- `sensor.<domain>_zone_<zone>_active_rooms` (`sensor.py:4444-4470`) —
  attributes `active_rooms` / `inactive_rooms` per zone. First place
  to look when asking "which room is holding the zone occupied?"
- Aggregation sensor bases: `anyone_home`, `rooms_occupied`,
  `occupant_count` (`const.py:128-141`).
- **Music following** (`CONF_ZONE_PLAYER_MODE`, `const.py:87-93`):
  `independent / aggregate / fallback`.

---

## 5. How the house decides

### 5.1 The state machine

`HouseState` enum values and legal transitions live at
`house_state.py:22-89`:

| State | Meaning |
|---|---|
| `away` | Nobody home. Requires `census_count == 0` AND no zone occupied. |
| `arriving` | Transition state from AWAY on new arrival. |
| `home_day` / `home_evening` / `home_night` | Occupied, by time of day. |
| `sleep` | Sleep hours + occupied. |
| `waking` | Coming out of sleep. |
| `guest` | Unidentified person detected while home. |

Transitions carry **minimum-dwell** protection (`house_state.py:96-103`):
AWAY 30 s, ARRIVING 60 s, HOME_* 120 s, SLEEP 600 s (10 min — protects
against false wakes), WAKING 60 s, GUEST 300 s.

The state is exposed as `sensor.ura_house_state` (`sensor.py:4011`)
and duplicate `sensor.ura_presence_house_state` (`sensor.py:4105`).
The user memories refer to
`sensor.ura_presence_coordinator_presence_house_state` — that appears
to be a display name, not the entity id (verify live).
`sensor.ura_house_state_confidence` (`sensor.py:4306`) exposes
confidence.

### 5.2 Away veto (v4.7.14)

Path: when `all_tracked_persons_away AND unidentified_count == 0`,
the presence coordinator infers AWAY at confidence 0.95. Attributes
`tracked_persons_count`, `all_tracked_persons_away` on the house_state
sensor let you audit the gate live. This eliminated the 60–90 s
oscillation seen 2026-05-30; validated with 33 min uninterrupted
dwell post-fix.

### 5.3 Guest gate + latch (v4.7.2, v5.16.0)

`unidentified_count > 0` (Frigate unidentified persons) OR an operator
guest arm raises `guest_gate_armed` (see `presence.py:912-1144`). The
GUEST → SLEEP transition was patched in v5.16.0 so a 22:00 guest
doesn't block sleep-mode HVAC/lights all night. Guest rooms have
their own occupancy threshold: `room_guest_occupancy_threshold_min`
(default 30, `const.py:319`, `config_flow.py:8351`).

### 5.4 Sleep, wake, and wake backstops (v4.7.18.1)

Sleep is exited by:
- Sustained real movement (`_WAKING_SUSTAINED_THRESHOLD_SECONDS = 90`,
  `presence.py:136`), OR
- Daytime backstop:
  `sleep_end_hour + _WAKE_BACKSTOP_HOURS_AFTER_SLEEP_END`
  (`_WAKE_BACKSTOP_HOURS_AFTER_SLEEP_END = 3`, `presence.py:142`). If
  the house is still SLEEP that long past `sleep_end`, WAKING gate
  fires unconditionally. This is what unlocked the 2026-06-05 organic
  wake validation.

The state machine is **not persisted across restart** — the house boots
`AWAY` by design. Persistence was explicitly decided-dropped (see
`v4.7.18.1` memory). The v4.7.21 boot-settle gates suppress the away-
actuation storm during the settling window.

### 5.5 The trust ladder (presence tuning)

- **v4.7.13 sleep person-trust** — during SLEEP, zone-presence trust
  extends to any tracked person marked home. mmWave loses stationary
  bodies; the person tracker is authoritative.
- **v4.7.24 occupancy substrate** — a per-room/per-kind raw layer
  beneath both room and zone occupancy. Curated `CONF_MOTION_SENSORS /
  presence_sensors / occupancy_sensors` lists are the single source of
  truth for both discovery AND kind classification. Bug Class #50
  (rebuild clobber) fix lives here.
- **v4.7.19 provenance split** — `_room_provenance` keys are
  `TIER1_KINDS = ("motion", "mmwave", "occupancy")` (`const.py:342`).
  mmwave is preferred when an entity matches both substrings.
- **v4.7.20 Layer-1 silent fan-interference discount + decay** — a
  hold applied when a room is fan-interference-suspect AND BLE says
  not-corroborated. Duration `fan_interference_hold_s` (default 300 s,
  `const.py:399`). It can only EXTEND occupancy; never shorten it.
- **Camera opt-out** — `CONF_DISABLE_CAMERA_PRESENCE` per room
  (`const.py:354`) mutes just that room's camera signal without
  removing it from URA.

### 5.6 Bermuda / BLE — the operating principle

**Sensors decide entry. BLE only sustains.** This is the
`ble_extend_not_create` contract (§3.1 step 8). Bermuda jitter cannot
create an occupancy — it can only extend one that a motion or mmWave
sensor confirmed. If your BLE is noisy, entry actions are safe; only
"how long the room stays lit past real motion" is at play.

---

## 6. Knobs and where they live

Following the `Numbers Get Knobs` ladder (CLAUDE.md 2026-07-16):
module constant / options-flow / entity, by how it should be governed.

### 6.1 Per-room options flow (config_flow.py room step, `config_flow.py:8000-8500` area)

| Key | Default | Notes |
|---|---|---|
| `CONF_ROOM_NAME`, `CONF_ROOM_TYPE`, `CONF_AREA_ID` | — | Structural. |
| `CONF_OCCUPANCY_TIMEOUT` | 300 s (`const.py:685`) | Room-type override in `ROOM_TYPE_TIMEOUTS`. |
| `CONF_OCCUPANCY_DEBOUNCE` | 150 (UI → seconds in coordinator, `const.py:686`) | Entry debounce. |
| `CONF_MOTION_SENSORS` / `presence_sensors` (mmWave) / `occupancy_sensors` | — | The three curated lists that ARE the truth (v4.7.24). |
| `CONF_ILLUMINANCE_SENSOR` | — | Feeds `turn_on_if_dark`. |
| `CONF_ILLUMINANCE_THRESHOLD` | 20 lx (`const.py:687`) | Dark threshold. |
| `CONF_LIGHTS` / `CONF_NIGHT_LIGHTS` / `CONF_ALERT_LIGHTS` | — | Actuators. |
| `CONF_ENTRY_LIGHT_ACTION` | `turn_on_if_dark` | `none / turn_on / turn_on_if_dark`. |
| `CONF_EXIT_LIGHT_ACTION` | `turn_off` | Any other value keeps lights. |
| `CONF_LIGHT_BRIGHTNESS_PCT` / `_TRANSITION_ON` / `_OFF` | 100 / 1 / 3 | |
| `CONF_NIGHT_LIGHT_SLEEP_BRIGHTNESS/COLOR` | 15 / 2000 K | |
| `CONF_NIGHT_LIGHT_DAY_BRIGHTNESS/COLOR` | 100 / 4000 K | |
| `CONF_HUMIDITY_FANS` + humidity knobs | see §3.5 | |
| `CONF_HUMIDITY_FAN_THRESHOLD` | 60 % | |
| `CONF_HUMIDITY_FAN_TIMEOUT` | 600 s | min-runtime gate. |
| `CONF_HUMIDITY_FAN_MAX_RUNTIME` | 3600 s | force-off cap. |
| `CONF_FAN_CONTROL_ENABLED` + `CONF_FAN_TEMP_THRESHOLD` / low/med/high | 80 / 69 / 72 / 75 °F | |
| `CONF_FAN_VACANCY_HOLD` | 300 s | extra runtime after vacancy. |
| `CONF_FAN_SLEEP_POLICY` | `reduce` | `off / reduce / normal`. |
| `CONF_SLEEP_PROTECTION_ENABLED` + `SLEEP_START/END_HOUR` | on / 22 / 7 | |
| `CONF_SLEEP_BYPASS_MOTION` | 3 | motion events to override sleep. |
| `CONF_ROOM_IS_GUEST_ROOM`, `CONF_ROOM_GUEST_OCCUPANCY_THRESHOLD_MIN` | off / 30 min | v4.7.2 D4. |
| `CONF_DISABLE_CAMERA_PRESENCE` | False | Per-room mute. |
| `CONF_SCANNER_AREAS` | [] | Areas with BLE scanners (sparse-scanner homes). |
| `CONF_ADJACENT_ROOMS` | [] | Fan-noise Layer-2 corroboration list. |
| Fan-recheck cluster (`CONF_FAN_RECHECK_*`) | see §3.4 | |
| `CONF_DOOR_SENSORS` / `_TYPE`, `CONF_WINDOW_SENSORS`, `CONF_IS_EGRESS_WINDOW` | interior / true | Feeds Safety + HVAC egress. |
| `CONF_COVERS`, `CONF_COVER_OPEN_MODE`, timing sources & offsets | — | Cover automation; see const.py:572-597. |
| `CONF_CLIMATE_ENTITY`, `CONF_HVAC_COORDINATION_ENABLED` | — | Ties this room to an HVAC zone. |
| `CONF_ROOM_MEDIA_PLAYER`, `CONF_MUSIC_FOLLOWING_ENABLED` | — | Music-following handoff. |

### 6.2 Zone options flow

- `CONF_ZONE_NAME`, `CONF_ZONE_ROOMS`, `CONF_ZONE_DESCRIPTION`.
- `CONF_ZONE_IS_OUTDOOR` (default False).
- `CONF_ZONE_PLAYER_ENTITY`, `CONF_ZONE_PLAYER_MODE`
  (`independent / aggregate / fallback`).
- `CONF_SHARED_SPACE`, `CONF_SHARED_SPACE_AUTO_OFF_HOUR` (default 23),
  `CONF_SHARED_SPACE_WARNING` — auto-off for common areas
  (`const.py:74-76, 125`).

### 6.3 Integration (house-wide) options flow

- `CONF_TRACKED_PERSONS`, `CONF_PERSON_DATA_RETENTION` (90 d),
  `CONF_TRANSITION_DETECTION_WINDOW` (120 s), `CONF_PERSON_DECAY_TIMEOUT`
  (300 s) — `const.py:158-179`.
- `CONF_OUTSIDE_TEMP_SENSOR`, `CONF_OUTSIDE_HUMIDITY_SENSOR`,
  `CONF_WEATHER_ENTITY`, `CONF_SOLAR_PRODUCTION_SENSOR`,
  `CONF_ELECTRICITY_RATE_SENSOR` (`const.py:674-679`).
- Notification service / target / level (`const.py:663-672`, values
  `off / errors / important / all`).
- Guest VLAN + guest-persistence (`config_flow.py:2911, 3072`).
- LOST-AWAY grace cluster (`CONF_LOST_AWAY_GRACE_MIN`,
  `CONF_LOST_AWAY_INDOOR_CLEAR_TICKS`, `CONF_LOST_AWAY_SLEEP_EXEMPT` —
  presence.py imports at :53-61).

### 6.4 Reviewed module constants (change requires code review)

Live in `const.py`. Do NOT expose as knobs; changing them is a
correctness bound.

- `BLE_MOTION_CONFIRM_MULTIPLIER = 2` (`const.py:375`) — the BLE
  extend-not-create predicate. Kill switch: `0` disables the BLE hold
  path.
- `BLE_TIER_2_WEIGHT = 0.6` (`const.py:363`) — borrowed-scanner
  confidence.
- `D3_DIAGNOSTIC_ENABLED = True` (`const.py:385`) — kill switch for
  the per-room weighted veto + the L1 fan-interference gate hold.
- `ROOM_TYPE_TIMEOUTS`, `ROOM_TYPE_FAILSAFE_DURATIONS` (`const.py:724, 749`).
- `TIER1_KINDS` and the `_classify_entity_kind` ordering
  (`const.py:342`).
- Wake backstop: `_WAKE_BACKSTOP_HOURS_AFTER_SLEEP_END = 3`,
  `_WAKING_SUSTAINED_THRESHOLD_SECONDS = 90` (`presence.py:136-142`).
- Failsafe: `DEFAULT_FAILSAFE_DURATION_SECONDS = 4 h` (`const.py:748`).

---

## 7. What to watch (sensors and attributes)

- **`sensor.ura_house_state`** / **`sensor.ura_presence_house_state`**
  (`sensor.py:4011, 4105`) — the current `HouseState` value; attributes
  from `house_state_machine.to_dict()` include time-in-state, last
  transition reason, `tracked_persons_count`,
  `all_tracked_persons_away`, `unidentified_count`, guest gate state.
- **`sensor.ura_house_state_confidence`** (`sensor.py:4306`) —
  inference confidence.
- **`sensor.<domain>_zone_<zone>_active_rooms`** — attrs `active_rooms`,
  `inactive_rooms` per zone (`sensor.py:4444`). First stop for
  "which room is holding a zone occupied?"
- **Per-room sensors** — the coordinator publishes `STATE_OCCUPIED`,
  `STATE_TIMEOUT_REMAINING`, `STATE_OCCUPANCY_SOURCE`
  (`motion / mmwave / occupancy_sensor / timeout / camera / ble /
   grace_hold / fan_recheck_release / none`), `STATE_BLE_PERSONS`,
  `STATE_TIME_SINCE_MOTION`, `STATE_ILLUMINANCE`
  (`const.py:759-799`).
- **`sensor.<room>_unavailable_entities`** — INPUT sensors that went
  unavailable. **Does NOT track dead actuators** (light/fan/cover). See
  §8.4 and `HVAC_COORDINATOR_MANUAL.md §6.4`.
- **Person location** — `universal_room_automation_<person>_location`
  and recent-path attrs (`MAX_RECENT_PATH_LENGTH = 10`, `const.py:175`).
- **Activity log** — `activity_logger.py` records entry/exit actions
  with the triggering sensor. This is the query surface for "why did
  the lights come on at 3 am?"

---

## 8. How to intervene safely

**Rule of thumb.** If a Number/Switch entity exists for a behavior,
turn that. Don't reach past URA into HA scripts targeting URA-managed
actuators during occupancy — you'll fight the coordinator's exit
action. Prefer sensor-driven custom automations that TRIGGER off URA
state, not automations that fight URA actuators.

### 8.1 "Room turns off too fast on a still occupant"

Order of diagnosis:
1. Read the room's `STATE_OCCUPANCY_SOURCE`. If it's flipping between
   `mmwave` and `none`, mmWave is losing the body.
2. If a fan is running, check whether `fan_interference_hold_s` and
   `fan_recheck` are engaging (`D3_DIAGNOSTIC_ENABLED` must be True).
3. Raise `occupancy_timeout` — 300 s is a floor. Bedrooms default 900 s
   (`ROOM_TYPE_TIMEOUTS`).
4. If the person is in bed, confirm SLEEP-tier person trust
   (v4.7.13) is picking them up — check
   `sensor.ura_house_state`'s state and the tracked-person location.
5. As a last resort, add a mmWave OR occupancy sensor to the room's
   configured lists.

### 8.2 "Setting up a new room well"

- **Sensor choice.** Populate all three lists you have — mmWave
  detects stillness (bedrooms, offices, media rooms); motion is fast
  and cheap; occupancy sensors (ZHA/Aqara-style) are fusion products
  and count when present.
- **Room type.** Pick the right `room_type` — the timeout AND failsafe
  ladders key off it (`const.py:724, 749`). A closet marked `generic`
  will get a 5-min timeout instead of 2 min.
- **Entry action.** `turn_on_if_dark` is the safe default unless the
  room is windowless (then `turn_on`). Set
  `illuminance_dark_threshold` after observing the room's typical dusk
  reading; 20 lx is a generic default.
- **Night lights.** If the room is on the sleep path (hallway,
  bathroom), populate `CONF_NIGHT_LIGHTS` — sleep entry will use only
  those with the sleep preset. Regular lights will be actively turned
  off (`_control_lights_entry` :659-661).
- **Guest rooms.** Toggle `room_is_guest_room` and consider
  `room_guest_occupancy_threshold_min` (default 30 min).

### 8.3 "Lights came on at 3 am with nobody there"

This is the exact class the v5.22.0 `ble_extend_not_create` fix
targeted (Master Bathroom 21:16–21:47 incident). Diagnosis:

1. Query `activity_logger` (or the URA activity log entity if
   exposed) for the entry event — capture the trigger sensor.
2. If the trigger source is `ble`, the fix has regressed — confirm
   `BLE_MOTION_CONFIRM_MULTIPLIER > 0` and check whether the room's
   `_last_occupied_state` was truthy at that time (CHAIN leg) or
   whether recent motion was < 2× timeout (MOTION leg). One of the
   two must have held.
3. If the trigger is `camera`, check for a stuck camera person
   sensor over the false window; consider
   `CONF_DISABLE_CAMERA_PRESENCE` for that room.
4. If the trigger is `motion` / `mmwave`, check
   `_sensor_on_since` — a sensor may have been declared stuck (>N
   hours) and re-enabled by a state edge. See `coordinator.py:1513`.

### 8.4 "A light didn't turn off at exit"

**Check the actuator first, not URA.** Full checklist in project
`CLAUDE.md → Troubleshooting`; short form:

1. Read the room config for which physical device the friendly name
   maps to.
2. Check the actuator's live state — `unavailable` / `restored:true`
   = offline. `sensor.<room>_unavailable_entities` will NOT tell you
   this; it only tracks input sensors.
3. Reload only the specific stuck config entry, not the parent
   URA entry (parent reload = watchdog-restart hazard, see
   feedback_parent_entry_reload_watchdog_hazard).

### 8.5 Bathroom exhaust behaving badly

- Sensor reads suspicious → check the humidity sensor entity directly.
  The 60-min `humidity_fan_max_runtime` cap will force off a stuck
  sensor after an hour.
- Fan cycles too aggressively → raise `humidity_fan_threshold` or
  widen the hysteresis constant (code review; default 10 pp).
- Fan won't stay on after a long shower → tune the D3 presence-
  proportional post-runtime knobs (`base / per_min / cap`).
- Fan runs into sleep → the wet-room + sleep-policy exemption is
  intentional; toggle `wet_room` OFF if you don't want it for that room.

### 8.6 Guest weekend

- Confirm `sensor.ura_house_state` shows `guest` when the guest is
  present (Frigate `unidentified_count > 0` OR operator arm).
- For a guest-only room, set `room_is_guest_room = True` and pick
  `room_guest_occupancy_threshold_min` — e.g. 60 min so a guest
  reading in bed doesn't drop the room every 5 min.
- The v5.16.0 GUEST → SLEEP transition patch means a late guest
  no longer blocks sleep-mode HVAC/lights.

### 8.7 A safe custom automation off URA state

**Do:** trigger your automation off URA's *sensors* (`sensor.ura_house_state`
transitioning to `home_day` at first kitchen occupancy → start
coffee-maker). Use `sensor.<domain>_zone_kitchen_active_rooms` state
change from empty → non-empty as a clean, deduplicated trigger.

**Don't:** target URA-managed lights with a parallel HA automation
during occupancy — URA's entry/exit will fight your writes. If you
need a scene, wire it to the URA entry action (`turn_on`) and let URA
own the transition.

**Don't:** run a custom scheduler that turns off lights that URA has
just turned on; the 4-hour failsafe already bounds forgotten lights,
and the room-type failsafe (60 min for closet/bathroom) bounds the
common lazy cases.

### 8.8 Kill switches (durable)

- BLE hold entirely: `BLE_MOTION_CONFIRM_MULTIPLIER = 0` in `const.py`
  (code change, reload).
- D3 diagnostic + L1 fan-interference hold:
  `D3_DIAGNOSTIC_ENABLED = False` in `const.py`.
- Per-room fan-recheck: `room_fan_recheck_enabled = False` in the
  room's options.
- Per-room camera opt-out: `disable_camera_presence = True` in the
  room's options.
- The house state machine cannot be "paused" — override the zone's
  `ZonePresenceMode` (`AWAY / OCCUPIED / SLEEP / AUTO`, `presence.py:237`)
  as an ephemeral override; auto-resumes on real detection.

---

## 9. Comfort / HVAC interplay (pointer)

The Room tier does not write to individual HVAC thermostats when
Carrier Infinity is running the show — it drives fans and passes
occupancy/setpoint hints. HVAC preset selection (`home / sleep / away`),
zone vacancy timers, and setpoint offsets from Energy Coordinator
constraints (`normal / pre_cool / coast / shed`) all live in the HC —
see **`HVAC_COORDINATOR_MANUAL.md`**, especially §3–5 for the vacancy
grace timers, the bidirectional `#49 ≤ #48` clamp, and the sleep-state
trust behavior.

**Per-room comfort sliders** (ComfortTempMin/Max/HumidityMax
Numbers): these are currently VESTIGIAL — persisted but nothing reads
their live value. They are the input surface for the future
**Optimization Coordinator** comfort dimension (see the "comfort
sliders optimization coordinator" memory). Turning them today does
not change room behavior. Do not delete; they will be wired when
Optimization Phase 1 lands.

---

## 10. AI / learned tier — today's honest state

Advisory-only, no actuation, per current code:

- **Optimization Coordinator L1 Shadow** — observes, does not act.
  Findings surface but the coordinator is not driving decisions
  (v5.0.0-v5.2.1 rolled back; fix-forward pending, see
  optimizer write-flood incident memory).
- **R1 Consumption Estimator (v5.18.0)** — SHADOW. Publishes
  `predicted_consumption_source` on `sensor.ura_energy_daily`; legacy
  day-of-week baseline drives Energy Coordinator decisions during the
  14-day observation.
- **Pattern learning** (`pattern_learning.py`) — informs prediction
  sensors (`AGGREGATION_PREDICTED_ENERGY_*`, `_COST_*`,
  `AGGREGATION_PREDICTED_COOLING`, `AGGREGATION_PREDICTED_HEATING`,
  `STATE_NEXT_OCCUPANCY_TIME`). Read-only surfaces; nothing actuates
  from these values today.
- **Bayesian predictor** (`bayesian_predictor.py`) — see coordinator
  architecture doc; sensor-exposed, not actuation-wired.
- **Battery-Aware EV Charging** — ACTS (v5.21.0 activated 2026-07-17)
  — but this is Energy Coordinator, not this tier. See EC manual §2.4a.

Rule for now: if a sensor name starts with `predicted_` or ends in
`_confidence`, treat it as advisory. Anything the room/zone/house
manuals describe as an ACTION is the deterministic path.

---

## 11. Notification Manager (briefly)

The NM (`domain_coordinators/notification_manager.py`) receives
severity-tagged events from every coordinator and dispatches them to
channels. Operator-visible knobs:

- `CONF_NOTIFY_SERVICE`, `CONF_NOTIFY_TARGET`, `CONF_NOTIFY_LEVEL`
  (integration options).
- Level ladder: `off / errors / important / all`
  (`const.py:669-672`).
- Room override: `CONF_OVERRIDE_NOTIFICATIONS` (`const.py:57`) —
  per-room bypass for a chatty area.
- BlueBubbles / WhatsApp channel wiring lives in the NM; see the
  2026-05-30 NM audit memo for the known gaps (per-person mute,
  safe-word ack, per-tick rate cap — all backlog).

Full detail: `NOTIFICATION_MANAGER.md`.

---

## 12. Recent version history (compressed)

| Version | What changed (operator-visible) |
|---|---|
| v3.5.1 | Camera extends room occupancy. |
| v3.6.0-c1 | Away-filter + AND-gate on zone anyone-home (b761cbe, later exposed by env shift → v4.7.14). |
| v3.8.8 / v3.8.9 | BLE/Bermuda extends room occupancy; sparse-BLE tier hardening. |
| v4.5.15 | Room-type failsafe durations; closet/bathroom = 60 min. |
| v4.7.2 | Guest room designation + occupancy threshold. |
| v4.7.13 | Sleep-state person trust — mmwave-drop doesn't force away during SLEEP. |
| v4.7.14 | Away-state person-tracker veto — 33-min AWAY dwell vs 60-90 s pre-fix. |
| v4.7.16 | Per-room camera-presence opt-out; BLE tier-2 weight; D3 weighted veto scaffolding. |
| v4.7.18.1 | Sleep → waking deadlock hotfix; raw-signal wake timer + daytime backstop. |
| v4.7.19 | Presence provenance split (`_room_provenance` per-kind); fan diagnostic. |
| v4.7.20 / .20.1 | Silent Layer-1 fan-interference hold + decay; dispatcher import hotfix. |
| v4.7.21 | Boot-storm settle gates — house boots AWAY cleanly. |
| v4.7.22 | Mode-2 BLE-gated fan pause + recheck; high-still-risk guard. |
| v4.7.24 | `OccupancySubstrate` per-room/per-kind raw layer beneath both tiers. Bug Class #50. |
| v4.7.25 | HVAC presence-timer knobs surfaced as Number entities #48/49/50 + reset button #51. |
| v5.7.0 | Outdoor-zone AWAY-path exclusion; LOST-AWAY grace cluster (WS-A3). |
| v5.10.0 / v5.11.0 | Music-following gate; occupancy-connectivity cleanup. |
| v5.12.0-v5.14.1 | Substrate resubscribe; SPAN re-key saga; labels; zone delete flow. |
| v5.16.0 | Guest latch — GUEST → SLEEP transition; guest arming from Frigate unidentified. |
| v5.17.x | (energy-side; documented in EC manual). |
| v5.19.0 | Behavioral write-verify machinery. |
| v5.22.0 | `ble_extend_not_create` — BLE never creates occupancy; two-leg (CHAIN, MOTION) admission. |
| v5.23.0 | Current tip (`const.py:34`). |

---

## Draft gaps for operator review

Items I inferred from memory or docs but could not fully pin to code
in this pass — please spot-check before publishing:

1. **`sensor.ura_presence_coordinator_presence_house_state`** — user
   memories cite this entity id, but the actual definitions in
   `sensor.py:4011, 4105` are `sensor.ura_house_state` and
   `sensor.ura_presence_house_state`. The longer form may be the
   friendly name only (**verify live**).
2. **`sensor.<room>_unavailable_entities`** — referenced repeatedly in
   HVAC manual + CLAUDE.md as an existing entity, but I did not
   locate its definition in `sensor.py` during this pass
   (**verify entity id and attribute schema live**).
3. **Zone `active_rooms` sensor entity id prefix** — code writes
   `f"{DOMAIN}_zone_{zone}_active_rooms"` unique_id at
   `sensor.py:4444`. The rendered entity id depends on HA's naming;
   I stated `sensor.<domain>_zone_<zone>_active_rooms` (verify live).
4. **`activity_logger` operator query surface** — `activity_logger.py`
   exists; whether it exposes an entity you can query from the UI or
   only a DB table was not verified in this pass.
5. **v5.22.0 vs v5.23.0 delta** — I mapped `ble_extend_not_create` to
   v5.22.0 based on the `coordinator.py:1807` comment "ble_extend_not_create
   (2026-07-17, fix-up B-HIGH-1)"; the manifest version is v5.23.0
   (`const.py:34`). Please confirm which release the operator considers
   the shipped one.
6. **Comfort sliders as "vestigial today"** — asserted from memory. I
   did not walk their read sites in `hvac.py` this pass; the operator
   memory ("comfort sliders optimization coordinator") is authoritative
   but verify no room-tier reader has been added since.
7. **`_unavail_grace_seconds`** default — I described the grace-hold
   behavior but did not pin the numeric default (search
   `_unavail_grace_seconds` in `coordinator.py`).
8. **Sleep person-trust code path** — v4.7.13 memory cites
   `hvac.py:1151` (SLEEP-only gate). I documented the behavior at the
   presence level; the exact SLEEP-only vs home_night gap is
   referenced but not re-verified here.
9. **BLE tier classification (`is_room_direct_ble`)** — described from
   `coordinator.py:1803` call site; the classification implementation
   in `person_coordinator.py` was not read this pass.
10. **v5.16.0 GUEST-latch mechanism** — described from operator memory
    ("guest latch"). The exact `presence.py` sites for the
    GUEST → SLEEP transition patch were not walked end-to-end.

## Notes / contradictions found in code vs memories/docs read

- **Manifest version = v5.23.0** (`const.py:34`) but no prior
  planning doc for v5.23.0 was skimmed. The memory index calls out
  v5.19.0-v5.21.0 explicitly; v5.22.0 and v5.23.0 don't appear in the
  MEMORY.md excerpt loaded here. The version history table shows my
  best-effort attribution; the operator should confirm the v5.22/23
  scope.
- **`ble_extend_not_create` dating** — the source comment says
  "2026-07-17" (`coordinator.py:1807`), which aligns with the
  2026-07-17 pickup memory "EVSE mid-build (A+B1+B2a done, B2b-i in
  flight)". That memory does NOT mention `ble_extend_not_create` as a
  separately shipped cycle. The change appears in-tree on `develop` at
  the referenced line.
- **`sensor.ura_house_state` vs `sensor.ura_presence_house_state`** —
  the codebase defines BOTH (`sensor.py:4011, 4105`). This is a
  duplication I did not expect; may be an artifact of a rename or a
  deliberate dual-exposure. Worth documenting or de-duplicating.

---

Relevant files:

- `/Users/okosisi/Code/universal-room-automation/docs/Coordinator/HOUSE_MANUAL.md` (this doc)
- `/Users/okosisi/Code/universal-room-automation/docs/Coordinator/ENERGY_COORDINATOR_MANUAL.md` (sibling)
- `/Users/okosisi/Code/universal-room-automation/docs/Coordinator/HVAC_COORDINATOR_MANUAL.md` (sibling)
- `/Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/coordinator.py`
- `/Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/automation.py`
- `/Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/const.py`
- `/Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/domain_coordinators/house_state.py`
- `/Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/domain_coordinators/presence.py`
- `/Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/sensor.py`

---

## Orchestrator resolutions to draft gaps (2026-07-18, session ground truth)

- **Gap 5 / v5.22-v5.23 attribution — RESOLVED:** v5.22.0 = the BLE
  extend-not-create fix (Master Bathroom strobe, shipped + organically
  validated 2026-07-18 03:21 under a 12-flap Bermuda storm). v5.23.0 =
  fan-recheck observability (veto counters + activity-log rows,
  instrumentation-only). Records: ble_extend_not_create_tier2db.md,
  fanrecheck_observability_tier1.md. The pickup memo the drafter read was
  truncated; the full memo covers both.
- **Gap 1 / house-state sensor id — the live entity is
  `sensor.ura_presence_coordinator_presence_house_state`** (read repeatedly
  this session via MCP). The drafter's finding of TWO defined sensor
  classes against the same manager attribute stands as a real de-dup
  candidate (sensor.py:4011 vs :4105) — BACKLOG.
- **Gap 2 / `sensor.<room>_unavailable_entities` exists live** (CLAUDE.md
  Troubleshooting documents its semantics: input sensors only, not
  actuators).
- Remaining gaps (3, 4, 6-10) stand for operator/next-session review.
