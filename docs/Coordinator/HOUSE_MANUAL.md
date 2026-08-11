# House Manual — Rooms, Zones, and the House (Operator Manual)

**Audience:** the homeowner running URA.
**Scope:** how the living tier (rooms, zones, house) actually behaves —
what turns your lights on, what decides you're home, what to watch,
and how to intervene without fighting the system.
**Current through:** URA v5.45.0 (see `const.py:34`). §13 (fan trust
stack) and §14 (room-camera fusion) added 2026-08-01 for the
v5.40-v5.45 primitives.

This is the sibling of `ZONE_MANUAL.md`, `CM_MANUAL.md`,
`ENERGY_COORDINATOR_MANUAL.md`, and `HVAC_COORDINATOR_MANUAL.md`. It is
NOT a code walkthrough. For per-coordinator design see
`PRESENCE_COORDINATOR.md`, `COORDINATOR_ARCHITECTURE.md`, and the
planning docs under `docs/planning/`.

**Coverage note.** This manual is genuinely ROOM-focused. Zone and CM
material here is a *pointer summary* — the standalone `ZONE_MANUAL.md`
and `CM_MANUAL.md` are the operator surfaces for those tiers.

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
   assignment). See §2 on the house-vs-HVAC-zone distinction and
   `ZONE_MANUAL.md` for zone-tier config in full.
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
Full detail in `HVAC_COORDINATOR_MANUAL.md §2` and `ZONE_MANUAL.md §1`.

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
     present. This is the SOLE admission leg post-2026-08-10
     (BLE-WARM-CREATE-1: the former MOTION leg was deleted after it
     was measured to create — not extend — occupancy on adjacent-room
     Bermuda bleed).
   Kill switch: set `BLE_CHAIN_HOLD_ENABLED = False` (bool, `const.py`)
   to disable the BLE hold path entirely.
9. **Failsafe (v4.5.15)** — regardless of sensors, a room cannot
   remain occupied longer than its failsafe duration
   (`DEFAULT_FAILSAFE_DURATION_SECONDS = 4 h`, `const.py:748`; 60 min
   for closets and bathrooms, `ROOM_TYPE_FAILSAFE_DURATIONS`,
   `const.py:749`). The failsafe only fires when the raw signal is
   *stale* — if a Tier-1 sensor is still reporting activity within
   `2 × occupancy_timeout`, the failsafe defers
   (`coordinator.py:1731-1754`).
10. **Fan-noise recheck (v4.7.22 Mode-2)** — pause-based; see §3.4.
11. **mmWave fan-corroboration D2 demotion (v5.42.0)** — passive
    backstop when the fan is running and mmWave is the ONLY signal;
    see §13.4.

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

Knobs (all in the room's options flow, plus timing knobs on CM):
- `fan_recheck_enabled` — master per-`PresenceCoordinator`, default
  `False` = opt-in (`const.py:412`). Lives on CM options; also
  reachable via the master `FanRecheckEnabledSwitch`.
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
a napping body isn't yanked. See §13.3 for how the recheck relates to
the newer D2 demotion (§13.4) and the L1 fan-interference hold.

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
  triggers, ~45 min time constant (`const.py:733-735`).
- **Presence-proportional post-runtime (D3)** — after occupancy ends,
  runtime = `base + per_min × occupied_minutes`, capped
  (60 s / 30 s per min / 600 s cap, `const.py:742-744`).
- **Wet-room flag** (`wet_room`, `const.py:724`) — defaults True for
  `room_type == bathroom`. Gates the sleep-policy exemption in
  `automation.py`.

### 3.6 Temperature-driven fan control

`fan_control_enabled` toggles per-room comfort fan behavior. Speeds
step at `fan_speed_low_temp` / `_med_temp` / `_high_temp` (default
69 / 72 / 75 °F, `const.py:699-701`). Interacts with HVAC via
`hvac_coordination_enabled` — see HVAC manual for the handshake.

Note the new AWAY veto layer in §13.1 — a "want fan on" from this path
still routes through `should_veto_comfort_fan` and can be suppressed
when the house is AWAY / VACATION and the room has no trusted
presence.

### 3.7 Sleep protection & sleep-bypass

`sleep_protection_enabled`, `sleep_start_hour` / `_end_hour` (defaults
22 / 7, `const.py:748-749`), `sleep_bypass_motion_count` (default 3,
`const.py:750`) — during sleep hours, N motion events are required
before URA takes an entry action. `fan_sleep_policy` = `off / reduce /
normal`, default `reduce` (`const.py:756`).

---

## 4. How a zone decides (summary)

Full detail: `ZONE_MANUAL.md`. Highlights:

- Zones are configured through the Zone Manager entry
  (`CONF_ZONE_*`, `const.py:64-93`). Each zone lists rooms; the
  zone's occupancy is a roll-up of its rooms.
- `zone_is_outdoor` (default False, `const.py:72`) — outdoor
  zones still track raw occupancy but are **excluded from the indoor-
  occupancy aggregate** that gates the v5.7.0 AWAY path.
- `sensor.<domain>_zone_<zone>_active_rooms` (`sensor.py:4444-4470`) —
  attributes `active_rooms` / `inactive_rooms` per zone. First place
  to look when asking "which room is holding the zone occupied?"
- Music following (`CONF_ZONE_PLAYER_MODE`, `const.py:87-93`):
  `independent / aggregate / fallback`.
- Ephemeral override: the `ZonePresenceMode` Select on each zone
  device (`AWAY / OCCUPIED / SLEEP / AUTO`) — see `ZONE_MANUAL.md §4.1`.

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
| `vacation` | Extended-AWAY sibling; comfort-fan veto (§13.1) treats it as AWAY. |

Transitions carry **minimum-dwell** protection (`house_state.py:96-103`):
AWAY 30 s, ARRIVING 60 s, HOME_* 120 s, SLEEP 600 s, WAKING 60 s,
GUEST 300 s.

Live entity is `sensor.ura_presence_coordinator_presence_house_state`
(operator-verified 2026-07-18). The codebase also defines
`sensor.ura_house_state` and `sensor.ura_presence_house_state`
(`sensor.py:4011, 4105`) — de-dup candidate (BACKLOG).
`sensor.ura_house_state_confidence` (`sensor.py:4306`) exposes
confidence.

### 5.2 Away veto (v4.7.14)

Path: when `all_tracked_persons_away AND unidentified_count == 0`,
the presence coordinator infers AWAY at confidence 0.95. Attributes
`tracked_persons_count`, `all_tracked_persons_away` on the house_state
sensor let you audit the gate live.

### 5.3 Guest gate + latch (v4.7.2, v5.16.0)

`unidentified_count > 0` (Frigate unidentified persons) OR an operator
guest arm raises `guest_gate_armed`. The GUEST → SLEEP transition was
patched in v5.16.0 so a 22:00 guest doesn't block sleep-mode HVAC/
lights all night. Guest rooms have their own occupancy threshold:
`room_guest_occupancy_threshold_min` (default 30, `const.py:319`).

### 5.4 Sleep, wake, and wake backstops (v4.7.18.1)

Sleep is exited by:
- Sustained real movement (`_WAKING_SUSTAINED_THRESHOLD_SECONDS = 90`,
  `presence.py:136`), OR
- Daytime backstop:
  `sleep_end_hour + _WAKE_BACKSTOP_HOURS_AFTER_SLEEP_END`
  (`_WAKE_BACKSTOP_HOURS_AFTER_SLEEP_END = 3`, `presence.py:142`).

The state machine is **not persisted across restart** — the house boots
`AWAY` by design.

### 5.5 The trust ladder (presence tuning)

- **v4.7.13 sleep person-trust** — during SLEEP, zone-presence trust
  extends to any tracked person marked home.
- **v4.7.24 occupancy substrate** — a per-room/per-kind raw layer
  beneath both room and zone occupancy.
- **v4.7.19 provenance split** — `_room_provenance` keys are
  `TIER1_KINDS = ("motion", "mmwave", "occupancy")` (`const.py:342`).
- **v4.7.20 Layer-1 silent fan-interference discount + decay** —
  duration `fan_interference_hold_s` (default 300 s, `const.py:399`).
  Extend-only.
- **v5.42.0 D2 mmWave fan-corroboration demotion** — passive backstop
  that OUTRANKS the L1 hold once its higher bar is met (§13.4).
- **Camera opt-out** — `CONF_DISABLE_CAMERA_PRESENCE` per room
  (`const.py:354`) mutes just that room's camera signal.

### 5.6 Bermuda / BLE — the operating principle

**Sensors decide entry. BLE only sustains.** This is the
`ble_extend_not_create` contract (§3.1 step 8).

---

## 6. Knobs and where they live

Following the `Numbers Get Knobs` ladder (CLAUDE.md 2026-07-16):
module constant / options-flow / entity, by how it should be governed.

### 6.1 Per-room options flow (config_flow.py room step)

Selected keys — see `const.py` for the full list. Numbers in the
Default column reflect `const.py` at v5.45.0.

| Key | Default | Notes |
|---|---|---|
| `CONF_ROOM_NAME`, `CONF_ROOM_TYPE`, `CONF_AREA_ID` | — | Structural. |
| `CONF_OCCUPANCY_TIMEOUT` | 300 s (`const.py:685`) | Room-type override in `ROOM_TYPE_TIMEOUTS`. |
| `CONF_OCCUPANCY_DEBOUNCE` | 150 | Entry debounce. |
| `CONF_MOTION_SENSORS` / `presence_sensors` (mmWave) / `occupancy_sensors` | — | The three curated lists that ARE the truth (v4.7.24). |
| `CONF_ILLUMINANCE_SENSOR` / `_THRESHOLD` | — / 20 lx | |
| `CONF_LIGHTS` / `CONF_NIGHT_LIGHTS` / `CONF_ALERT_LIGHTS` | — | Actuators. |
| `CONF_ENTRY_LIGHT_ACTION` / `_EXIT_` | `turn_on_if_dark` / `turn_off` | |
| `CONF_HUMIDITY_FANS` + humidity knobs | see §3.5 | |
| `CONF_FAN_CONTROL_ENABLED` + temperature bands | on / 69/72/75 °F | |
| `CONF_FAN_VACANCY_HOLD` | 300 s | Extra runtime after vacancy. **v5.42.0 BUG 1 fix:** now applies ONLY to fans that are already RUNNING (§13.2). |
| `CONF_FAN_SLEEP_POLICY` | `reduce` | `off / reduce / normal`. |
| `CONF_COMFORT_FAN_AWAY_VETO_ENABLED` | see §13.1 | AWAY / VACATION comfort-fan suppression. |
| `CONF_SLEEP_PROTECTION_ENABLED` + hours | on / 22 / 7 | |
| `CONF_SLEEP_BYPASS_MOTION` | 3 | |
| `CONF_ROOM_IS_GUEST_ROOM`, `CONF_ROOM_GUEST_OCCUPANCY_THRESHOLD_MIN` | off / 30 min | |
| `CONF_DISABLE_CAMERA_PRESENCE` | False | Per-room camera mute. |
| `CONF_ROOM_CAMERAS` | [] | v5.44+ camera-fusion input (§14). Multi-select of ANY camera-related entities. |
| `CONF_AUTO_ENABLE_PERSON_DETECTION` | True | D4 dry-run gate (§14.5). |
| `CONF_SCANNER_AREAS` | [] | Areas with BLE scanners. |
| `CONF_ADJACENT_ROOMS` | [] | Fan-noise Layer-2 corroboration list. |
| Fan-recheck cluster (`CONF_ROOM_FAN_RECHECK_ENABLED` etc.) | see §3.4 / §13.3 | |
| `CONF_DOOR_SENSORS` / `_TYPE`, `CONF_WINDOW_SENSORS`, `CONF_IS_EGRESS_WINDOW` | interior / true | |
| `CONF_COVERS`, cover options | — | See const.py:572-597. |
| `CONF_CLIMATE_ENTITY`, `CONF_HVAC_COORDINATION_ENABLED` | — | |
| `CONF_ROOM_MEDIA_PLAYER`, `CONF_MUSIC_FOLLOWING_ENABLED` | — | |

### 6.2 Zone options flow

See `ZONE_MANUAL.md §3-4`. Highlights: `CONF_ZONE_NAME`,
`CONF_ZONE_ROOMS`, `CONF_ZONE_IS_OUTDOOR`, `CONF_ZONE_PLAYER_ENTITY`,
`CONF_ZONE_PLAYER_MODE`, `CONF_ZONE_PERSONS`, `CONF_ZONE_CAMERAS`.

### 6.3 Integration (house-wide) options flow

- `CONF_TRACKED_PERSONS`, `CONF_PERSON_DATA_RETENTION` (90 d),
  `CONF_TRANSITION_DETECTION_WINDOW` (120 s), `CONF_PERSON_DECAY_TIMEOUT`
  (300 s) — `const.py:158-179`.
- `CONF_OUTSIDE_TEMP_SENSOR`, `CONF_OUTSIDE_HUMIDITY_SENSOR`,
  `CONF_WEATHER_ENTITY`, `CONF_SOLAR_PRODUCTION_SENSOR`,
  `CONF_ELECTRICITY_RATE_SENSOR` (`const.py:674-679`).
- Notification service / target / level — see `CM_MANUAL.md §3`.
- **Camera census lists** — `CONF_CAMERA_PERSON_ENTITIES` (interior),
  `CONF_EGRESS_CAMERAS`, `CONF_PERIMETER_CAMERAS` (`const.py:1072-1074`).
  Distinct from room fusion (§14 and `ZONE_MANUAL.md §6`).
- `CONF_CENSUS_DIVERGENCE_DOWNGRADE` — default True. See §14.7.

### 6.4 Reviewed module constants (change requires code review)

Live in `const.py`. Do NOT expose as knobs; changing them is a
correctness bound.

- `BLE_CHAIN_HOLD_ENABLED = True` (`const.py`) — bool kill switch
  for the BLE chain-hold admission leg (extend-not-create). Set to
  `False` to disable the BLE hold path entirely. Split from the
  legacy `BLE_MOTION_CONFIRM_MULTIPLIER` on 2026-08-10 so that the
  BLE kill switch is independent of the D2 staleness threshold.
- `D2_PIR_STALENESS_MULTIPLIER = 2` (`const.py`) — INT multiplier
  consumed by the D2 mmWave-fan demotion block as the PIR-staleness
  threshold: `D2_PIR_STALENESS_MULTIPLIER × occupancy_timeout`.
  Also acts as the outer-guard kill switch (`> 0`) for the D2
  demotion path only — this is NOT the BLE kill switch (see
  `BLE_CHAIN_HOLD_ENABLED` above). Split from the legacy
  `BLE_MOTION_CONFIRM_MULTIPLIER` on 2026-08-10.
- `BLE_TIER_2_WEIGHT = 0.6` (`const.py:363`).
- `D3_DIAGNOSTIC_ENABLED = True` (`const.py:385`) — upstream kill
  switch for the L1 fan-interference hold AND the D2 demotion (§13.4).
- `MMWAVE_FAN_CORROBORATION_ENABLED = True` (`const.py:522`) — D2
  master kill.
- `MMWAVE_FAN_CORROBORATION_GRACE_S = 600` (`const.py:523`) — fan-on
  grace before D2 can fire. Values <300 are clamped to 300.
- `MMWAVE_NAME_PATTERN` (`fan_veto.py:61`) — regex used to exclude
  mmWave-family entities from motion-only reads (§13.1, §13.5).
- `FRIGATE_CROSS_HOST_CORROBORATION_ENABLED = False`
  (`camera_resolver.py:79`) — F2 gate, ships dark (§14.7).
- `CAMERA_AUTOENABLE_DRY_RUN = True` (`camera_resolver.py:84`) — D4
  dry-run (§14.5).
- `CENSUS_USE_NEW_RESOLVER = False` (`camera_resolver.py:92`) —
  census cutover, ships dark (§14.7).
- `CAMERA_COVERED_ROOMS` (`const.py:701`) — legacy additive bridge
  (§14.1).
- `ROOM_TYPE_TIMEOUTS`, `ROOM_TYPE_FAILSAFE_DURATIONS`.
- Wake backstop: `_WAKE_BACKSTOP_HOURS_AFTER_SLEEP_END = 3`,
  `_WAKING_SUSTAINED_THRESHOLD_SECONDS = 90` (`presence.py:136-142`).
- `DEFAULT_FAILSAFE_DURATION_SECONDS = 4 h` (`const.py:748`).

---

## 7. What to watch (sensors and attributes)

- **`sensor.ura_presence_coordinator_presence_house_state`** — live
  house state. Attrs include `tracked_persons_count`,
  `all_tracked_persons_away`, `unidentified_count`, guest gate state.
- **`sensor.ura_coordinator_manager_house_policy`** — composed live
  policy from CM (see `CM_MANUAL.md §4.1`).
- **`sensor.<domain>_zone_<zone>_active_rooms`** — first stop for
  "which room is holding a zone occupied?"
- **Per-room sensors** — `STATE_OCCUPIED`, `STATE_TIMEOUT_REMAINING`,
  `STATE_OCCUPANCY_SOURCE` (values include `motion / mmwave /
  occupancy_sensor / timeout / camera / ble / grace_hold /
  fan_recheck_release / mmwave_fan_demoted / none`), `STATE_BLE_PERSONS`.
- **`binary_sensor.<room_slug>_camera_person_detected`** (v5.44+, §14).
  Attrs: `sources`, `agreement`, `confidence`, `resolved_camera_devices`,
  `resolved_physical_cameras`, `disabled_by_config`, `configured_cameras`.
- **`binary_sensor.<room>_occupied` attrs** — `mmwave_fan_demoted`
  (bool), `mmwave_fan_demotions_since_boot` (int) — post v5.42.0.
- **`sensor.<room>_unavailable_entities`** — INPUT sensors that went
  unavailable. Does NOT track dead actuators.
- **Activity log** — `activity_logger.py`.

---

## 8. How to intervene safely

**Rule of thumb.** If a Number/Switch entity exists, turn that. Don't
reach past URA into HA scripts targeting URA-managed actuators.

### 8.1 "Room turns off too fast on a still occupant"

1. Read `STATE_OCCUPANCY_SOURCE`. Flipping between `mmwave`/`none` =
   mmWave losing the body.
2. If a fan is running, check §13.4 (D2 demotion) attrs on
   `binary_sensor.<room>_occupied`. `mmwave_fan_demoted=True` +
   `mmwave_fan_demotions_since_boot` incrementing = the room is
   demoting. Consider extending `MMWAVE_FAN_CORROBORATION_GRACE_S`
   (code review) or configuring a PIR sensor (`_d2_motion_sensors_present`
   fail-closes on no-PIR rooms; see §13.4).
3. Raise `occupancy_timeout`. Bedrooms default 900 s.
4. Confirm SLEEP-tier person trust picks the sleeper up.

### 8.2 "Setting up a new room well"

**Configuring sensors CORRECTLY (v5.42.0 mmWave discipline).** The
D2 demotion (§13.4) AND the AWAY-veto motion leg (§13.1) both key
off the *kind* of your sensor entries. Misfile them and the machinery
either can't see the sensor or wrongly trusts it.

- **`presence_sensors` = the mmWave bucket.** Anything using mmWave /
  radar / LD2410 / LD2412 goes here. **Consequence of misfiling: an
  mmWave entity dropped into `occupancy_sensors` is INVISIBLE to ALL
  mmWave machinery** — the D2 demotion, the L1 fan-interference hold,
  and the fan-recheck all key on `STATE_OCCUPANCY_SOURCE == "mmwave"`
  or on the `presence_sensors` list membership.
- **`motion_sensors` = PIR ONLY.** True PIR / IR sensors. `fan_veto.py`
  and `_d2_motion_sensors_present` apply `MMWAVE_NAME_PATTERN`
  (`fan_veto.py:61` — matches `mmwave|radar|presence|ld2410|ld2412`)
  and **strip** entities that look like hybrids from the motion list.
  If your "motion" entity is actually a hybrid, it'll be excluded from
  the motion-recency leg — meaning the AWAY veto (§13.1) and the D2
  PIR-staleness leg both treat this room as **no-PIR**.
- **`occupancy_sensors` = fused ZHA/Aqara-style occupancy.** Kept
  separate from mmWave.
- **Room type.** Pick the right `room_type`; timeout AND failsafe
  ladders key off it.
- **Night lights.** For sleep-path rooms (hallway, bathroom) populate
  `CONF_NIGHT_LIGHTS`.

### 8.3-8.5 (unchanged from prior revisions — see git history).

### 8.6 Guest weekend

- Confirm house state shows `guest`.
- For guest-only rooms, set `room_is_guest_room = True` and pick
  `room_guest_occupancy_threshold_min`.
- The v5.16.0 GUEST → SLEEP patch means a late guest no longer
  blocks sleep-mode HVAC/lights.

### 8.7-8.8 (unchanged).

Kill switches summary:
- BLE hold entirely: `BLE_CHAIN_HOLD_ENABLED = False`.
- D3 diagnostic + L1 fan-interference hold + D2 demotion:
  `D3_DIAGNOSTIC_ENABLED = False`.
- D2 demotion only: `MMWAVE_FAN_CORROBORATION_ENABLED = False`.
- Comfort-fan AWAY veto: `comfort_fan_away_veto_enabled = False` on
  the room.
- Per-room fan-recheck: `room_fan_recheck_enabled = False`.
- Per-room camera opt-out: `disable_camera_presence = True`.

---

## 9. Comfort / HVAC interplay (pointer)

See `HVAC_COORDINATOR_MANUAL.md` and `docs/user-manual/DYNAMIC_PRESET.md`.

**Per-room comfort sliders** (ComfortTempMin/Max/HumidityMax
Numbers): currently VESTIGIAL — persisted but nothing reads their live
value. Reserved for the future Optimization Coordinator comfort
dimension.

---

## 10. AI / learned tier — today's honest state

Advisory-only, no actuation, per current code:

- **Optimization Coordinator L1 Shadow** — observes, does not act.
- **R1 Consumption Estimator (v5.18.0)** — SHADOW during 14-day
  observation.
- **Pattern learning** — read-only surfaces.
- **Bayesian predictor** — sensor-exposed, not actuation-wired.
- **Battery-Aware EV Charging** — ACTS (v5.21.0) but is EC-tier, not
  this tier.

---

## 11. Notification Manager (briefly)

See `CM_MANUAL.md §3` for the full channel + routing + cooldown map.
Room-level override: `CONF_OVERRIDE_NOTIFICATIONS` (`const.py:57`) —
per-room bypass for a chatty area.

---

## 12. Recent version history (compressed)

| Version | What changed (operator-visible) |
|---|---|
| v3.5.1 | Camera extends room occupancy. |
| v4.5.15 | Room-type failsafe durations. |
| v4.7.13 | Sleep-state person trust. |
| v4.7.14 | Away-state person-tracker veto. |
| v4.7.22 | Mode-2 BLE-gated fan pause + recheck. |
| v4.7.24 | `OccupancySubstrate` per-room/per-kind. |
| v5.7.0 | Outdoor-zone AWAY-path exclusion. |
| v5.16.0 | Guest latch — GUEST → SLEEP transition. |
| v5.22.0 | `ble_extend_not_create`. |
| v5.40.0 | Comfort-fan AWAY veto shared predicate (§13.1). |
| v5.42.0 | Fan seam Phase 1 (vacancy-hold RUNNING-only, external adoption, §13.2); D2 mmWave fan-corroboration demotion (§13.4). |
| v5.44.0-v5.45.0 | Room-camera fusion primitives — `CameraResolver`, per-room fused `binary_sensor.<room>_camera_person_detected`, D4 auto-enable dry-run, exterior-person severity-by-house-state (§14). |
| v5.45.0 | Current tip (`const.py:34`). |

---

## 13. Fan trust stack (v5.40.0-v5.42.0) — operator guide

Five interlocking pieces determine whether a comfort fan actually
runs. From highest authority to backstop:

1. AWAY / VACATION veto (`fan_veto.py`) — §13.1
2. Vacancy-hold gate (RUNNING-only, `automation.py`) — §13.2
3. External-lit fan adoption (`hvac_fans.py`) — §13.2
4. Fan-recheck (pause-based Mode-2, `presence_fan_recheck.py`) — §13.3 / §3.4
5. mmWave fan-corroboration D2 demotion (`coordinator.py`) — §13.4

Configure a room's sensors correctly (§13.5) or several of these
layers can't do their job.

### 13.1 Comfort-fan AWAY veto (v5.40.0)

Shared predicate in `fan_veto.py::should_veto_comfort_fan` — consumed
by ALL THREE comfort-fan `turn_on` sites:

1. Room-tier: `automation.py::handle_temperature_based_fan_control`
2. HVAC-tier: `hvac_fans.py::HvacFanController.update` (before
   `_set_fan_state`)
3. Reconciler: `actuator_reconciler.py::_resolve_fan`

**Truth-preserving invariant:** if house state is AWAY or VACATION
AND the room has no trusted presence, a comfort-fan turn_on is
suppressed. Sleep path is disjoint (untouched). Humidity fans, safety
fans, and manual actuations bypass this entirely.

**"Trusted presence" =** PIR-recent (motion sensor ON, or transitioned
OFF within `occupancy_timeout`) OR BLE person tracked in the room
(with active tracking status) OR camera-person for camera-covered
rooms.

**mmWave is EXCLUDED by construction** — the veto exists precisely
because a mmWave-only signal under fan interference is untrustworthy.
Even mmWave entities operators historically misfiled under
`CONF_MOTION_SENSORS` are stripped by name (`MMWAVE_NAME_PATTERN`,
`fan_veto.py:61`).

**Fail-open on any error.** A stuck helper must never silently
suppress a fan. Boot-settle gate also fails-open: if the presence
coordinator isn't wired yet, the veto is skipped
(`fan_veto.py:404-410`).

**Config field (per room):** `CONF_COMFORT_FAN_AWAY_VETO_ENABLED`
(`const.py:684`, key `comfort_fan_away_veto_enabled`). Default —
verify per-room via `DEFAULT_COMFORT_FAN_AWAY_VETO_ENABLED`.

**Observability:** per-room veto counter surfaced as
`get_veto_count(hass, room_name)` (`fan_veto.py:448-454`) — RAM-only,
resets at boot; the D7 counter feeds the dashboard. First hit per boot
per room logs one INFO line ("veto enabled for room=... —
first-check-this-boot").

**Kill switch:** set `comfort_fan_away_veto_enabled=False` on the
room's options → helper returns False unconditionally, pre-cycle
behavior.

### 13.2 Vacancy-hold gate + external-lit fan adoption (v5.42.0)

**BUG 1 fix (`automation.py:1708-1733`):** the room-tier vacancy-hold
override (`occupied=True` during grace) now applies ONLY when a fan
is already RUNNING (`any_fan_on_now`). Prior to v5.42.0, on boot the
first vacant tick re-stamped the vacancy grace and the downstream
temperature branch emitted a spurious `fan.turn_on` in an
unoccupied room. `CONF_FAN_VACANCY_HOLD` still governs the runtime
extension (default handled by `DEFAULT_FAN_VACANCY_HOLD`), it just no
longer arms turn-ONs.

**BUG 2 fix (`hvac_fans.py:239-293`):** a fan that lit externally
(physical switch, another automation, or room-tier during boot warmup)
is now ADOPTED into HVAC-tier bookkeeping (`room_fan.is_on = True`,
`room_fan.trigger = "external"`, `room_fan.speed_pct = <observed>`,
`last_on_time = now`). Log: `"HVAC Fans: <room> adopted externally-lit
fan (speed=<n>%)"`. Without this branch, the vacancy-off path had no
owner and a room-tier-boot-lit fan could run for hours in a vacant
room (the Study A "4h at 100%" incident). The eventual OFF is treated
as a normal vacancy-off, NOT interpreted as manual.

### 13.3 Fan-recheck relationship (v4.7.22, unchanged behavior)

Pause-based Mode-2 layer (§3.4). Fires when mmWave alone is driving
occupancy AND a fan is on AND all 9 trigger conditions hold
(`presence_fan_recheck.py:339-504`). Precedence at v5.42.0:

- **Recheck FIRST** — recheck gets first crack; D2 (§13.4) defers
  while any recheck is in-flight for the room.
- **Vacancy-hold SECOND** — the RUNNING-only override (§13.2) applies
  after recheck completes.
- **D2 demotion as BACKSTOP** — for rooms that are recheck-ineligible
  (SLEEP, rate-capped, no fan configured, master switch off, etc.).

Recheck NEVER fires during `HouseState.SLEEP`
(`presence_fan_recheck.py:373-375`). WAKING is allowed. The v4.7.13
keep-fans-on-through-sleep doctrine is respected.

### 13.4 mmWave fan-corroboration D2 demotion (v5.42.0, Tier-3)

Passive backstop to the recheck: when mmWave-sole occupancy is
sustained past its natural timeout AND the fan has been on ≥ grace AND
no PIR motion in ≥ 2× occupancy_timeout AND no BLE-trustworthy person
AND (for covered rooms) no camera-person, DEMOTE the room to vacant
with `STATE_OCCUPANCY_SOURCE = "mmwave_fan_demoted"`.

**The complete gate list** (`coordinator.py:2438-2447` + helper
methods):

- `data[STATE_OCCUPIED]` is True
- `MMWAVE_FAN_CORROBORATION_ENABLED` (module const, True by default)
- `D2_PIR_STALENESS_MULTIPLIER > 0` (D2 outer-guard kill; NOT the
  BLE kill switch — that is `BLE_CHAIN_HOLD_ENABLED`)
- `_d2_boot_settle_done()` — presence `_boot_settle_done` is True
- `_d2_debounce_elapsed(now)` — past the vacant→occupied debounce
  window (A-CRIT-1 fix — the previous `_occupancy_first_detected is
  None` gate was permanent-fail once occupied)
- `_d2_motion_sensors_present()` — room has ≥1 real PIR after
  `MMWAVE_NAME_PATTERN` filter. **No-PIR rooms FAIL-CLOSED** — leg (e)
  is unsatisfiable there, so we refuse to demote (D-HIGH-1 fix). One
  DEBUG log per room per boot.
- `_d2_house_state_allows()` — house state NOT in `{SLEEP, WAKING,
  HOME_NIGHT}` (D-CRIT-1 fix, `coordinator.py:1611-1637`). Aligns
  with the recheck's SLEEP veto and the duty-cycle detector's
  sleeping-bedroom refusal.
- `STATE_OCCUPANCY_SOURCE == "mmwave"` — mmWave-sole
- PIR-only motion staleness: `_last_pir_motion_time` age ≥ `MULT ×
  occupancy_timeout`
- Recheck-in-flight guard: `_fan_recheck_manager.get_room_state(room)
  == "idle"`

**Fan-on grace:** `MMWAVE_FAN_CORROBORATION_GRACE_S = 600` s
(`const.py:523`). Values <300 are clamped to 300 in the wrapper
(D-MED-2 fail-safe floor). Setting it very low does NOT disable the
feature — use `ENABLED=False` for that.

**On demotion:**
- `data[STATE_OCCUPIED] = False`
- `data[STATE_OCCUPANCY_SOURCE] = "mmwave_fan_demoted"`
  (`OCCUPANCY_SOURCE_MMWAVE_FAN_DEMOTED`, `const.py:524`) — this is the
  **source string** the operator sees on the room's occupancy
  attribute.
- `_mmwave_fan_demoted_last_tick = True`
- `_mmwave_fan_demoted_since = now`
- `_mmwave_fan_demotions_since_boot += 1` — the **since-boot
  counter** exposed on `binary_sensor.<room>_occupied`.
- Room's D1 fan-interference hold is CLEARED atomically
  (`_fan_interference_hold_until` popped) — D-PRIME-CRIT-1
  adjudication: D2 OUTRANKS the hold once its higher bar is met (the
  hold is re-stamped every tick a room stays fan-suspect, so
  defer-to-hold was unreachable). Blast radius stays room-tier-only;
  zone-side `_room_occupied` is held up by sustained mmWave
  provenance in the sustained case anyway.
- Dispatches `SIGNAL_MMWAVE_FAN_DEMOTED` with `room_name`, `reason=
  "mmwave_sole_fan_on_no_corroboration"`, `fan_on_since`, and
  `last_pir_motion_time`.
- INFO log: `"Room <name>: mmwave-fan-corroboration DEMOTE
  (fan_on_for=Xs, pir_last=Ys, source was 'mmwave') — releasing to
  vacant"`.

**Post-demotion flap latch (`_mmwave_demoted_latch`,
`coordinator.py:1639-1699`).** While set, mmWave-sole activity CANNOT
recreate occupancy in this room. Cleared on ANY recovery signal:
mmWave reads off (`mmwave_off`), PIR fires (`pir_motion`), BLE
person arrives (`ble_person`), or fan turns off (`fan_off` — tracker's
`_fan_on_since` drops the room). Clear logs one INFO line.

**Kill switches** (rung-1 module constants, code-review-gated):
1. `MMWAVE_FAN_CORROBORATION_ENABLED = False` — disables the whole
   predicate.
2. `D2_PIR_STALENESS_MULTIPLIER = 0` — also disables the derived
   PIR-staleness gate for D2 (outer-guard). This is the D2-only
   kill; it does NOT disable the BLE chain hold — for that use
   `BLE_CHAIN_HOLD_ENABLED = False`.
3. `D3_DIAGNOSTIC_ENABLED = False` — third UPSTREAM kill (D2's
   `_compute_mmwave_fan_demoted_rooms` wraps
   `_compute_fan_interference_rooms` which short-returns `[]` when
   D3 is disabled). Reuse of the D3 primitive is BY DESIGN.

### 13.5 Configuring a room's sensors CORRECTLY

The single most common cause of "the fan won't turn off / the room
won't demote" is misfiled sensor lists.

- **`presence_sensors`** = **the mmWave bucket.** Anything using
  mmWave / radar / LD2410 / LD2412 goes here.
  **Consequence of misfiling: mmWave entities dropped into
  `occupancy_sensors` are INVISIBLE to ALL mmWave machinery.** D2,
  L1 fan-interference hold, and fan-recheck all key on the room's
  reported `STATE_OCCUPANCY_SOURCE == "mmwave"` and/or the
  `presence_sensors` list membership.
- **`motion_sensors`** = **PIR ONLY.** True PIR / IR only. Hybrids
  matching `mmwave|radar|presence|ld2410|ld2412` (`fan_veto.py:61`)
  are pattern-excluded from motion-recency reads by BOTH the AWAY
  veto and D2's `_d2_motion_sensors_present`. A room whose "motion"
  entries are all hybrids will be treated as **no-PIR** — D2 fails
  closed, and the AWAY veto's motion leg contributes nothing.
- **`occupancy_sensors`** = fused ZHA/Aqara-style occupancy. Kept
  separate; not read as mmWave and not read as motion.

Verify with `STATE_OCCUPANCY_SOURCE`: if a room's mmWave is running
under a fan and its source is *not* reading `"mmwave"`, the entity is
probably in the wrong bucket.

---

## 14. Room-camera fusion (v5.44.0-v5.45.0)

Prior to v5.44, the fan-veto's camera-person leg (§13.1) read a
hand-frozen room allowlist (`CAMERA_COVERED_ROOMS = {"Study A"}`,
`const.py:701`) and raw per-camera person entities. The v5.44+ cycle
replaces that with per-room camera **fusion**: you list any
camera-related entities on the room, a shared `CameraResolver` groups
them per physical camera, and a per-room fused binary_sensor
publishes an OR of the resolved sources with agreement + confidence
attributes.

### 14.1 Configuration surface

- **Field:** `CONF_ROOM_CAMERAS` (`const.py:708`, key `room_cameras`).
  Multi-select on the room's options flow.
- **What to pick:** ANY camera-related entity for the physical camera
  covering this room — a `camera.*` entity, a person `binary_sensor.*`,
  a face `binary_sensor.*`, a person-count `sensor.*`. The resolver
  walks its correlation ladder from any of these back to the physical
  device.
- **Legacy bridge:** `CAMERA_COVERED_ROOMS` (`const.py:701`) is an
  ADDITIVE allowlist retained during the fusion cutover — a room in
  that frozenset is treated as camera-covered even if `room_cameras`
  is empty. Delete-after-graduation candidate.
- **Per-room mute:** `CONF_DISABLE_CAMERA_PRESENCE` (`const.py:354`,
  `disable_camera_presence`) — authoritative; forces the fused sensor
  off and blocks the fan-veto's camera leg (§13.1) even if
  `room_cameras` is populated.

### 14.2 The fused per-room sensor

`binary_sensor.<room_slug>_camera_person_detected`
(`binary_sensor.CameraPersonDetectedSensor`, `binary_sensor.py:1115+`).

- `is_on` = **any** resolved source across ALL fused physical cameras
  reports `on`. `disabled_by_config=True` (via
  `CONF_DISABLE_CAMERA_PRESENCE`) forces `is_on=False`.
- Empty `CONF_ROOM_CAMERAS` → `is_on=False` (NOT unavailable).

### 14.3 Attributes and their meaning

- **`sources`** — list of per-integration dicts: `integration`,
  `entity_id`, `state`, `correlation_basis` (`same_device` / `mac` /
  `identifiers` / `network_inventory` / `name_stem` /
  `operator_declared`), `face_capability` (`absent` / `usable` /
  `ambiguous`), `physical_camera_id`.
- **`agreement`** —
  - `no_sources` (nothing resolved)
  - `single_source` (only one integration observed)
  - `unanimous_on` (all available sources ON)
  - `unanimous_off` (all available sources OFF, ≥2 available)
  - `split` (mixed ON/OFF across sources)
- **`confidence`** —
  - `high` = ≥2 ON, from ≥2 distinct integrations (family-independence
    downgrade applies — see below)
  - `medium` = single ON, or split, or `high` downgraded when all ON
    sources share ONE integration (fix #9 doctrine deferral)
  - `low` = zero available with sources present
  - `none` = no sources at all
- `resolved_camera_devices`, `resolved_physical_cameras`,
  `disabled_by_config`, `configured_cameras`.

### 14.4 Fan-veto rebuttal — what single_source vs split means

The comfort-fan AWAY veto (§13.1) reads the fused sensor. To **rebut**
the veto (i.e., grant "trusted camera presence"), the divergence-aware
gate (`fan_veto.py:302-331`, E-HIGH-1 fix) requires:

- `state == "on"` AND
- `agreement in {"unanimous_on", "single_source"}` OR
  `confidence == "high"`.

- **`single_source`** → grant. Uncontested (only one integration
  covers this room; no second opinion exists).
- **`unanimous_on`** → grant. Multiple sources all agree.
- **`split`** → **deny.** A second camera actively DISSENTS; treat as
  not-trusted for veto purposes. Log at DEBUG: `"fused sensor ... is
  ON but agreement=split ... not corroborated"`.
- **`unanimous_off`** or `is_on=False` → deny (no evidence).

This mirrors the census divergence doctrine ratified at v5.43.0:
single-source keeps current behavior; only contested divergence
downgrades.

### 14.5 D4 auto-enable dry-run + per-room toggle

- **Per-room toggle:** `CONF_AUTO_ENABLE_PERSON_DETECTION`
  (`const.py:712`, `auto_enable_person_detection`, default `True` per
  `DEFAULT_AUTO_ENABLE_PERSON_DETECTION`).
- **What it does:** collects per-integration person-detect switches
  (`switch.<...>_person_detection` / `_detections_person` /
  `_smart_detect_person` / `_ai_person`) from the resolved fusion and
  proposes turning them on.
- **Ships DRY-RUN:** `CAMERA_AUTOENABLE_DRY_RUN = True`
  (`camera_resolver.py:84`, rung-1 module constant). First release
  LOGS what it would enable; **does NOT call switch.turn_on**. Flip
  to False in a later reviewed change once the log inventory looks
  right.
- **Face switches are NEVER auto-enabled — invariant.**
  `_FACE_SWITCH_SUFFIXES` is INVENTORY only
  (`camera_resolver.py:184-190`), guarded by test that they never
  reach the enable path.

### 14.6 Zone-side camera surfaces (distinct from room fusion)

Do not conflate these with room fusion:

- **`CONF_ZONE_CAMERAS`** — zone-side face-confirmed-arrival cameras
  for HVAC pre-arrival. See `ZONE_MANUAL.md §4`.
- **Integration-level census lists** (`const.py:1072-1074`):
  - `CONF_CAMERA_PERSON_ENTITIES` — legacy interior
  - `CONF_EGRESS_CAMERAS`
  - `CONF_PERIMETER_CAMERAS`
  Consumed by `camera_census.py` (whole-house census) and the
  perimeter alerter. Different consumer, different problem.
  `CONF_CENSUS_DIVERGENCE_DOWNGRADE` (`const.py:1102`, default True)
  governs the census's divergence-aware downgrade.

### 14.7 Exterior-person escalation (severity-by-house-state)

`camera_census` / `perimeter_alert.py` escalate an exterior person
detection through NM at a severity that depends on `HouseState`
(`const.py:1133-1153`):

| House state | Severity |
|---|---|
| `away`, `vacation`, `sleep`, `home_night` | `CRITICAL` |
| `guest` | `MEDIUM` (`NM_HAZARD_EXTERIOR_PERSON_GUEST_SEVERITY`) |
| `home_day`, `home_evening`, `arriving`, `waking` | `LOW` |
| unknown / missing / None | `CRITICAL` (fail-safe default) |

**Snapshot offset knob (rung-2 options):**
`CONF_EXTERIOR_SNAPSHOT_OFFSET_S` (`const.py:1159-1162`), default
5 s, range 0–60 s. Delays live-fallback snapshot capture by N seconds
so the still frame is closer to the detection moment despite
acquisition lag. Ignored on Frigate's event-frame path (that snapshot
is inherently at-detection-time). Set to 0 to disable.

**Boot-settle:** `PERIMETER_BOOT_SETTLE_S = 30`
(`const.py:1168`) — perimeter state-change events within 30 s of
manager setup are ignored to suppress spurious CRITICALs from
RestoreEntity replay.

**Label filter:** `FRIGATE_SNAPSHOT_LABELS = {"person"}`
(`const.py:1173`) — only Frigate events whose `after.label` is
`person` update the cached snapshot event_id.

### 14.8 What ships DARK (so you're not surprised by inert flags)

Three flags are code-review-gated OFF at v5.45.0:

1. **`CENSUS_USE_NEW_RESOLVER = False`** (`camera_resolver.py:92`) —
   the whole-house census still uses the LEGACY path. The new
   `CameraResolver` is exercised by D3 (per-room fused sensor) and D5
   (fan-veto camera leg) — flipping this flag routes the census
   through it too. **Cutover requires a golden-master diff artifact
   (legacy vs new outputs across the live registry).** Do NOT flip
   without that artifact.
2. **`FRIGATE_CROSS_HOST_CORROBORATION_ENABLED = False`**
   (`camera_resolver.py:79`) — the F2 gate. Until a 72 h stability
   check (zero MQTT session evictions, zero unavailable⇄value
   flapping, no retained-message ghosts) passes post prefix-split,
   Frigate-1 and Frigate-2 are collapsed to a deterministic winner
   (state-preferring, then lowest sorted device_id) rather than
   treated as independent corroborators. When collapsed, losers'
   person sensors are retained in `dropped_person_sensors` so the
   fused sensor re-resolves on their recovery.
3. **`CAMERA_AUTOENABLE_DRY_RUN = True`** (§14.5) — D4 logs, does
   not call switch.turn_on.

Each is intentional; each is documented at its declaration; flipping
any of them is a reviewed-code-change event.

---

## Notes / contradictions found in code vs prior manual

Verified during this pass (2026-08-01):

- **v5.23.0 → v5.45.0.** The manifest has moved 22 minor versions since
  the prior manual revision. Fan-trust stack (§13) and camera fusion
  (§14) are the material new operator surfaces in that window.
- **`DEFAULT_COMFORT_FAN_AWAY_VETO_ENABLED`** — referenced in
  `fan_veto.py:41` but not read directly in this pass; operator
  should verify default via `const.py` grep or the room options-flow
  UI before assuming behavior.
- **`CAMERA_COVERED_ROOMS = frozenset({"Study A"})`** — the legacy
  allowlist is real code (`const.py:701`) and still consulted by
  `fan_veto._has_camera_person`. Not yet removed; deletion candidate
  after fusion beds in.
- **`sensor.ura_house_state` vs `sensor.ura_presence_house_state`
  vs live `sensor.ura_presence_coordinator_presence_house_state`** —
  three surfaces for the same value; the last is the live entity id.
  De-dup candidate remains open (BACKLOG).
- **`_boot_settle_done` fail-open** in both `fan_veto.py:111-128` and
  `coordinator.py:1546-1557`. Intentional (D-MED-1 accepted-risk):
  suppressing a legitimate post-restart fan is a worse operator
  experience than a few minutes of runtime in a truly empty house.

---

Relevant files:

- `/Users/okosisi/Code/universal-room-automation/docs/Coordinator/HOUSE_MANUAL.md` (this doc)
- `/Users/okosisi/Code/universal-room-automation/docs/Coordinator/ZONE_MANUAL.md` (new)
- `/Users/okosisi/Code/universal-room-automation/docs/Coordinator/CM_MANUAL.md` (new)
- `/Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/coordinator.py`
- `/Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/automation.py`
- `/Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/const.py`
- `/Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/fan_veto.py`
- `/Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/camera_resolver.py`
- `/Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/binary_sensor.py`
- `/Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/domain_coordinators/presence_fan_recheck.py`
- `/Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/domain_coordinators/hvac_fans.py`
- `/Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/domain_coordinators/house_state.py`
- `/Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/domain_coordinators/presence.py`
- `/Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/sensor.py`
