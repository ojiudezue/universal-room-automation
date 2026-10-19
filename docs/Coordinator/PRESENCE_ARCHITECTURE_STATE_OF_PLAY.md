# PRESENCE — Architecture State of Play (READ FIRST)

**Status:** forensic snapshot of `develop` as of 2026-10-11; the live house is on v5.103.50.
**Fan-noise running rejection Rev 2 (built 2026-10-11, `fix/fan-noise-running-rejection`, NOT deployed — Tier 2-DB):** C1a recheck VACATED leaves the fan off; C2 fan-immune witness by capability + model safety net (name regex retired); C3 fan belief held through unavailable flaps + reconciler quarantine veto; C4 cooldown 900 + per-family window + rehydrate fixes; C5 transition gate retired (0.0). See §5, §6, §10 item 8, gold patterns. Code at the cited lines wins once merged
(`person_coordinator.py:3` header). Builders / planners / reviewers of ANY presence-adjacent
work (BLE, mmWave, PIR, fan interference, occupancy debounce, house-state inference, census,
room switches) read this FIRST, completely, before editing or diagnosing anything. For
identity / camera / census / fusion / egress, this doc summarises and POINTS to the canonical
`docs/Coordinator/IDENTITY_FUSION_CAMERAS_MANUAL.md` — do not duplicate that content here. For
sensor-class truth (ZV / ZK / ZX), summarises and points to
`docs/architecture/SENSOR_FLEET_CLASSES.md`.

**Owner rule (per the HVAC companion doc):** code at the cited `file:line` wins; if this doc
disagrees with the code, the code is right — fix the doc in the same turn. Every claim here is
cited to a verified `file:line` on `develop`, or marked **UNVERIFIED**.

---

## 0. How to use this doc

1. Read it completely before planning, building, reviewing or diagnosing anything in the
   presence arc. Planners cite it in "Institutional context verified"; reviewers check plans
   against §2–§7 and the §9 corrections ledger.
2. **Precedence.** For the areas it covers, this doc supersedes the older
   `PRESENCE_COORDINATOR.md`, planning docs and READMEs — *except* where current code says
   otherwise.
3. **Updates.** Any presence ship, correction or refuted claim updates this doc in the same
   commit. A refutation goes into §9 — never delete the wrong claim; record it with its
   refutation.
4. Paths: `presence.py` = `custom_components/universal_room_automation/domain_coordinators/presence.py`;
   `coordinator.py` = `custom_components/universal_room_automation/coordinator.py`; the rest live
   under `custom_components/universal_room_automation/`.

---

## 1. One-page summary — the pipeline

```
  Hardware sensors  ─┐                                     ┌─ Lights / covers
                     │                                     ├─ HVAC occupancy
   motion / mmwave   │  Room coordinator      Zone roll-up ├─ Fans
   occupancy / bed   │  (coordinator.py)   →  (aggregation)├─ Security / alerts
                     │  per-room occupancy     any_room    ├─ Census (identity)
   BLE (Bermuda +    │  (STATE_OCCUPIED)       occupied    └─ Room-tier reconciler
   private_ble_      │
   device + IRK)     │  → person_coordinator  → PresenceCoordinator
                     │    (room-per-person)    (StateInferenceEngine)
                     │                           path α / path β /
   Cameras ──────────┤                           guest / sleep
   (Frigate/Protect/ │
    Reolink/Amcrest  │  → camera_census ────────────→ unidentified_count,
    /Dahua)          │                                face_recognized_count
                     ┘                                → house_state
```

- **One room coordinator per room entry** (`coordinator.UniversalRoomCoordinator`). It owns
  this room's occupancy, debounce, chatter detection, duty-cycle stuck detection, room
  switches, and the fan-transition CREATION gate (`coordinator.py:3601-3745`).
- **One PresenceCoordinator per install** (`presence.PresenceCoordinator`,
  `presence.py:1`). It consumes room occupancy, zone rollups, camera_census, person_coordinator
  and infers house_state via `StateInferenceEngine` (`presence.py:1004`).
- **One PersonCoordinator per install** (`person_coordinator.PersonCoordinator`) — per-person
  room resolution from Bermuda + CONF_SCANNER_AREAS + private_ble_device + IRK + registry
  fallbacks.
- **Decision cadence** is HA state-change-driven for room occupancy; PresenceCoordinator ticks
  on `SIGNAL_CENSUS_UPDATED` / `SIGNAL_ZM_ZONES_UPDATED` / timers; HVAC runs its own 5-min
  cycle (see HVAC doc).

**Consumers of each signal (verified by grep on `develop`):**

| Signal | File:line produced | Consumed by |
|---|---|---|
| `binary_sensor.<room>_occupied` (room occupancy) | `coordinator.py:3613` (STATE_OCCUPIED set in `_async_update_data`) | lighting, fans, covers, zone roll-up, HVAC `RoomCondition.hvac_occupied` (HVAC doc §2), security, perimeter |
| Zone `any_room_occupied` / `any_indoor_zone_occupied` | `aggregation.py` + presence consumption `presence.py:6414` | path-β indoor-occupancy guard, HVAC zone rollup, lighting bias |
| `SIGNAL_HOUSE_STATE_CHANGED` | `presence.py` (dispatcher) | HVAC override arrester, fans, lighting, security, EVSE, battery, memory writers |
| `SIGNAL_CENSUS_UPDATED` | `camera_census.py` | PresenceCoordinator (`_handle_census_update`), inference denominator |
| `person.*` entities + `sensor.<person>_room` | `person_coordinator.py` | guest gate, census identity fusion, egress, perimeter enrichment |

---

## 2. Decision loop & inference paths

**House-state inference engine** (`presence.py:1004-1200+`): priority ladder
(`presence.py:1007-1013` docstring):

0. **Nobody-home** (`presence.py:1126-1131`, re-read 2026-10-18) — AWAY iff `census_count == 0 AND
   NOT any_zone_occupied`. Listed first in the code and missing from this ladder before 2026-10-18
   (§10 #14). `census_count` includes BLE-located residents, so a resident Bermuda places at home
   blocks it. **SLEEP-mask hazard:** `any_zone_occupied` is `mode == OCCUPIED`
   (`presence.py:5975-5978`), and house SLEEP pins every zone tracker to `SLEEP` via `set_sleep`
   (`presence.py:930`), so during SLEEP this branch reads every zone as empty and can fire AWAY on
   `census_count == 0` alone (e.g. a phoneless sleeper). Wigton replay: 216 of 251 stress-case false
   AWAYs (`AUDIT_wigton_away_replay_2026_10_18.md`).
   **FIXED on branch `feature/house-state-sleep-mask-ble-memory` (sleep-mask cycle, NOT deployed):**
   - **D1.** `_run_inference` computes `any_zone_occupied_for_empty`, in which a SLEEP-mode tracker contributes its raw night occupancy. That is `PresenceCoordinator._zone_night_raw`: BLE, OR an occupied room, OR a camera in its timeout; there is no fan test.
     - The room limb is the tracker's room view OR the live `on` state of any Tier-1 sensor registered to the room (review D-H1). The tracker view is lossy in multi-sensor rooms, because one off-edge clears every kind.
     - The value is passed to `infer(any_zone_occupied_for_empty=...)` and read by nobody-home and D1b. The same signal also feeds the WAKING sustained gate, and path β's indoor guard while a SLEEP zone is night-occupied (review D-M3).
     - The input is keyed on tracker mode, not house state, so zones still SLEEP-pinned under a HOME_* override also read raw.
     - A zone under a manual AWAY override still reads empty (carve-out).
   - **D1b.** After the sleep window ends, raw night occupancy counts as `has_people`, so SLEEP discharges via WAKING.
   - **Trip-wire.** It fires one **HIGH** stuck-signal NM (`kind=sleep_raw_hold`) when INFERRED SLEEP (not an override) is still held only by raw occupancy with census 0 more than `SLEEP_RAW_HOLD_NM_BOUND_S` (5400 s; 0 = off) after max(sleep-window end, SLEEP entry). That means the D1b discharge failed. An overnight raw hold inside the window is normal and never fires.
   - **Kill switch:** `PRESENCE_NOBODY_HOME_READS_RAW_IN_SLEEP` (rung 1).
   - **Labels:** nobody-home now sets `_veto_path = "nobody_home"` on the FIRING return only; the already-AWAY return keeps `none`.
1. **AWAY path α** — "ACTIVE-only" tracker veto (v4.7.14 origin). AWAY iff `NOT camera_input_degraded
   AND all_tracked_persons_away AND unidentified_count == 0 AND face_recognized_count == 0`
   (`presence.py:1169-1180`, re-read 2026-10-16). It does NOT check `census_count` or zone/room
   occupancy (corrected 2026-10-16, see §10 #12). Gated on
   `face_recognized_count` to close the forgotten-phone inflation (`presence.py:1042-1052`,
   const `CENSUS_FACE_RECOGNITION_WINDOW_SECONDS = 1800 s`, cross-check
   `camera_census.py:3034-3055`).
2. **AWAY path β** (v5.7.0 WS-A) — admits `LOST`-but-away trackers into the AWAY denominator,
   gated by indoor-occupancy guard (A2/A4), configurable `CONF_LOST_AWAY_GRACE_MIN` (A3) + sleep
   exemption + the FIX-2b indoor-clear tick debounce (`presence.py:1053-1072`,
   `CONF_LOST_AWAY_GRACE_MIN`, `CONF_LOST_AWAY_INDOOR_CLEAR_TICKS`,
   `CONF_LOST_AWAY_SLEEP_EXEMPT`).
3. **GUEST** — `guest_gate_armed = True` while home. `_guest_gate_armed()` pre-evaluates
   threshold / confidence / persistence (v4.6.2.2, `presence.py:1091-1094`).
4. **SLEEP** — census people present AND sleep hours (default 23 → 06, overridable in ctor
   `presence.py:1017-1025`).
5. **HOME_DAY / HOME_EVENING / HOME_NIGHT** — census people + time-of-day variants
   (`evening_start_hour=18`, `night_start_hour=21`, `presence.py:1019-1020`).
6. **ARRIVING** — new arrivals from AWAY (`presence.py:1012`).

**FRIGATE-FLEET-DARK gate** (`presence.py:1073-1085`, kwarg
`camera_input_degraded`): when the camera input fleet is dark (Frigate configured AND
status bad), path α SKIPS because the "0 unidentified" denominator becomes unreliable;
control falls through to path β / GUEST / SLEEP.

**AWAY observability (sleep-mask cycle D3, branch, NOT deployed).** These are attributes on the house-state sensor:
- `last_away_branch`: `_veto_path` at the inference edge, or `override` for `override_adapter` / `boot_settle_override`; there is no `restore` source.
- `last_away_at`.
- `away_entries_today`: counted in `_dispatch_house_state_change` after the boot-settle and observation gates, next to the `house_state_log` write. The getter reads 0 on a new local day. At setup it is hydrated with a naive-UTC `start_of_local_day` bound, via `count_house_state_changes_since(..., state="away", exclude_same_previous=True)`.
- `guest_reason`: `guest_room:<room>` > `unidentified_persistent` > `override` > `none`.

`stale_counted_home` and `nobody_home_zone_input` are in `_unrecorded_attributes`.

**Veto-path verdict** (corrected 2026-10-18, §10 #16): the house-state sensor attribute
`veto_path` (`sensor.py:5661`) mirrors the engine's `_veto_path` (`presence.py:6518`), values
`none` / `active` / `lost_admitted` / `lost_admitted_immediate` (`none` also covers a
nobody-home AWAY today). The labels `alpha_starved` / `alpha_denies` / `beta_only` exist only in
the D5 `away_transition_blocked` memory-episode payload (`presence.py:6548-6561`).

**HouseState enum** (`house_state.py:56-67`): `AWAY, ARRIVING, HOME_DAY, HOME_EVENING,
HOME_NIGHT, SLEEP, WAKING, GUEST, VACATION`. `VALID_TRANSITIONS` at `house_state.py:71+`.

**Persistence** (`house_state.py:26-54`): `HOUSE_STATE_STORE_KEY`,
`HOUSE_STATE_RESTORE_MAX_STALE_S = 1800`, `HOUSE_STATE_HEARTBEAT_S = 300`,
`HOUSE_STATE_SAVE_DEBOUNCE_S = 1.0`, override survives restart = True.

---

## 3. BLE presence

**Producers (upstream HA integrations URA relies on):** Bermuda (scanner-fleet area sensor),
`private_ble_device` (IRK → device_tracker), and HA's `person.*` composite. URA does NOT run
BLE radios — it reads what Bermuda / private_ble_device publish.

**`person_coordinator.py`** (`v5.103.50`, header `person_coordinator.py:3`) resolves per-person
room via a **three-tier scanner ladder** (`person_coordinator.py:10-14`):

1. **Tier 1 — direct area match** (dense scanner homes, zero config).
2. **Tier 2 — `CONF_SCANNER_AREAS` override** (sparse homes, lookup
   `person_coordinator.py:979`, derived attribute `person_coordinator.py:1646-1700`). A room
   with `CONF_SCANNER_AREAS` configured is "Tier 2 / borrowing"; a room that OWNS a scanner
   via area_id is "Tier 1"; otherwise Tier 0 (`person_coordinator.py:1650-1700`).
3. **Tier 3 — occupancy disambiguation** when multiple rooms share a scanner.

**Bermuda-area-sensor resolution** (strategies in order, `person_coordinator.py:1180-1238`):
config → `private_ble_device` → name-pattern → entity-registry fallback → **WARN "No Bermuda
area sensor found for %s (tried: config, private_ble, patterns, registry)"**
(`person_coordinator.py:1237`). That warning is the canonical fallback-exhaustion signal.

**Fleet liveness gate** — `BLE_FLEET_LIVENESS_WINDOW_S = 90` (`person_coordinator.py:67`,
rung-1 module constant). If any tracked person had a Bermuda update within 90 s the fleet is
"provably live" and a `BLE=silent` stamp is admitted as matrix row 14
(`away_ble_silent_only`); otherwise `BLE=silent` degrades to indeterminate (row 16
`no_signal`). This is the backstop that prevents a dead scanner fleet from voting everyone
away.

**Phone-left-behind** — `PersonPhoneLeftBehindSensor`
(`binary_sensor.py:2095-2270`), unique_id
`{DOMAIN}_person_{slug}_phone_left_behind` (`binary_sensor.py:2122`, resolved by
`presence.py:5713-5717`). When on, the person is excluded from the AWAY-veto denominator
(`presence.py:5677-5805`); the exclusion reason is prefixed `phone_left_behind=on`
(`presence.py:5792-5803`). D9 room-occupancy carve-out at `const.py:2693`.

**Per-person tracker axes (re-read 2026-10-18)** — `person_coordinator.py:200-240` builds
`{gps, wifi, ble}` from the HA `person.*` entity's `device_trackers` list in order, and the LAST
tracker of a source type wins. A second GPS device that never reads home (2026-10-18: an iPad
~100 m from `zone.home` centre with a 53 m radius) therefore overwrote the phone's GPS axis with
`away`. Removed from `person.oji_udezue` 2026-10-18 (operator). Keep each person to phone app GPS +
BLE IRK (`private_ble_device_*`); the `*_bermuda_tracker` is Bermuda's own tracker derived from the
same IRK (operator), so it duplicates the BLE axis harmlessly. Open: whether "any GPS home wins"
should replace last-wins (carded in the sleep-mask/BLE-memory plan).

**All three AWAY branches already need residents' phones/BLE gone** (2026-10-18 verify): nobody-home
via `census_count` (includes BLE ids), α via `all_tracked_persons_away`, β via the trusted-or-lost
denominator plus `census_count == 0`. A resident Bermuda resolved within 300 s but not this tick is
stamped STALE and was EXCLUDED from the denominator instead of counting as home. **Sleep-mask cycle D2 (branch, NOT deployed):**
- `_tracking_active` now also admits STALE while `PRESENCE_STALE_RESIDENT_COUNTS_HOME` is True (rung 1). The hold lasts at most last fix + `CONF_PERSON_DECAY_TIMEOUT` + 30 s + 60 s.
- `phone_left_behind` precedence is unchanged.
- STALE persons counted home are listed in the unrecorded attribute `stale_counted_home`.
- STALE is not restored across a restart.
- Readers that shift toward "home": NM `persons_home`, HVAC Wait-for-Presence consensus (−0.4 term), the compliance consensus defer gate (`coordinator_diagnostics.py:667`, not in plan §3.2 but the same direction), the arriving re-arm bypass, and the episode labels. Measured (P4, `AUDIT_census_arc_and_away_holistic.md`):
real resident someone-home AWAYs ≈ 0.27–0.31/day on ordinary days; most "someone-home AWAYs" in
earlier probes were residents actually leaving while a room's 300 s hold tail was still on.

**Tracked persons config** — `CONF_TRACKED_PERSONS`, confidence distances
`CONF_PERSON_HIGH_CONFIDENCE_DISTANCE` / `CONF_PERSON_MEDIUM_CONFIDENCE_DISTANCE`, decay
`CONF_PERSON_DECAY_TIMEOUT` (defaults in `const.py`, imports
`person_coordinator.py:33-58`). Staleness: `TRACKING_STATUS_ACTIVE / STALE / LOST`,
`STALE_THRESHOLD_SECONDS`, `MAX_RECENT_PATH_LENGTH`.

**Scanner-areas config field** — `CONF_SCANNER_AREAS = "scanner_areas"` (`const.py:564`),
area-selector in config flow (`config_flow.py:2576`) and options flow
(`config_flow.py:12576`). Introduced v3.2.4 (`config_flow.py:14`).

**What BLE can prove**: coarse ROOM, with scanner-area granularity, when the fleet is live.
**What BLE cannot prove**: identity-at-a-door, sub-room location, or presence vs
phone-left-behind (that is why the carve-outs exist). Face / camera is the identity oracle —
see `IDENTITY_FUSION_CAMERAS_MANUAL.md`.

---

## 4. Room sensors & occupancy

**Four CONF roles** (declared on each room entry):

- `CONF_MOTION_SENSORS` — motion-class (PIR + Hobeian ZV mmWave-motion, see §5).
- `CONF_PRESENCE_SENSORS` — true presence radar that holds a still person (ZK / ZX).
- `CONF_OCCUPANCY_SENSORS` — HA `device_class="occupancy"` fleet.
- `CONF_MMWAVE_SENSORS` — **its VALUE is `"presence_sensors"`** (`const.py:480`): it IS the
  presence-radar list above, under its code name. There is no separate `CONF_PRESENCE_SENSORS`
  constant. `sensor_capability.derive_capability` maps it to kind `mmwave`. (Corrected
  2026-10-11 — see §10 item 8.)

**Capability layer** — `domain_coordinators/sensor_capability.py` lifts the CONF-list wiring
to a `SensorCapability` ("what IS this hardware"), with `CAPABILITY_KIND_*`
(`sensor_capability.py:34-40`) and trust classes (`TRUST_CLASS_STRONG_EVIDENCE` etc). Pure
module (no HA imports). Operator declares ambiguous cases via `CONF_SENSOR_CAPABILITIES`.
**Role layer** — `sensor_role.py` answers role per QUERY (CANDIDATE_FOR_STUCK,
CORROBORATOR_FOR_ROOM, CREATOR_VS_EXTENDER). Current wired consumer:
`coordinator._detect_duty_cycle_stuck` (`sensor_role.py:17-18`).

**Zone tier (presence `ZonePresenceTracker`) — per-sensor rule (sleep-mask cycle Rev 3, branch `feature/house-state-sleep-mask-ble-memory`, NOT deployed; switch `const.ZONE_OCCUPANCY_PER_ENTITY_ENABLED`, rung 1, default True):**
- A zone room is occupied iff ANY registered Tier-1 sensor reads `on`. Unavailable, unknown and missing all count as off.
- **Substrate (D4a).** `OccupancySubstrate._kind_on_now(room, kind, map, *, event_entity, event_state)` is the ONE per-kind rule for seed and live. It ORs every entity mapped to (room, kind); the event entity's state comes from the payload and only siblings are read from `hass.states`. Single-sensor kinds are therefore byte-identical.
- **Tracker (D4b).** An off-edge for kind k pops only k. A `kind=None` False is still a full clear.
- **Discharges:**
  - an entity deleted from HA (payload `None`) counts as off;
  - a removed ROOM entry releases its kinds through `async_remove_entry` → lifecycle `"removed"` → the refresh's snapshot-room walk;
  - a refresh seeds into a scratch copy and swaps only after the subscribe succeeds (one retry, then coherent-old);
  - boot-settle release reconciles every tracker room to the substrate, writing differing slots only.
- **Switch False:** byte-identical to `dad3bf6e7`, including the D-H1 night live-sensor limb and the WAKING forcing line, which run only while it is False.
- **Read rule:** the switch is read as the `const` module attribute only, in `presence.py`, `occupancy_substrate.py` and `__init__.py` (lint-enforced). Tests flip it with the `per_entity_off` fixture or `--per-entity-off`.
- The zone tier still ignores room-tier stuck exclusions and D2 demotion (STEP-EXCLUDE-4, PICK R3-2). A stuck or phantom sensor in any room holds its zone while it reads `on`.

**Combination into `STATE_OCCUPIED`** — `coordinator._async_update_data` evaluates
`motion_detected`, `occupancy_detected`, `presence_detected`, applies mmwave-sole gate
(§4.1), debounce (§4.2), fan-transition CREATION gate (§4.3), chatter / stuck exclusions
(§4.4). Final write: `coordinator.py:3613+`.

### 4.1 mmwave-sole handling

A tick that is **presence-only** (mmwave fired, PIR did not, occupancy did not) sets
`mmwave_sole_here = True`; `any_sensor_active` is zeroed under that condition on CREATION
(`coordinator.py:3586-3594`). Backed by the fan-transition gate (§4.3) and D2 sustain
demotion.

### 4.2 Debounce

Per-room `_occupancy_debounce_seconds` (`coordinator.py:~2150`); `_occupancy_first_detected`
timestamp carries the pending edge. The fan-transition gate explicitly must NOT reset this
on suppression (HIGH-B1 fix, `coordinator.py:3628-3634`).

### 4.3 Chatter detection — physics-based quarantine

`domain_coordinators/chatter_detector.py:1-30`. Per-entity sub-T_floor burst detector:
`>= CHATTER_BURST_K` transitions below the sensor family's floor within
`CHATTER_OBSERVATION_WINDOW_S` → quarantined via `SensorExclusionSet`. Auto-release after
`CHATTER_RELEASE_QUIET_S` of zero transitions. Owned by
`coordinator._chatter_detector` (`coordinator.py:696`), listeners registered
`coordinator.py:1708-1709`.

### 4.4 Duty-cycle stuck

`coordinator._detect_duty_cycle_stuck` uses the role resolver (
`sensor_role.CANDIDATE_FOR_STUCK`). Sleep-family rooms are exempt
(`coordinator.py:1812-1817`, referenced from the D2 veto doc at `coordinator.py:2191-2197`).

### 4.5 Override switches and room-switch resolver

- `switch.<room>_automation` — master automation enable.
- `switch.<room>_manual_mode` — v3.20.0 ManualMode: ON disables ALL room automation.
- `switch.<room>_cover_automation`, `switch.<room>_ai_automation`,
  `switch.<room>_override_occupied`, `switch.<room>_override_vacant`,
  `switch.<room>_auto_recovery` (consumed by `actuator_reconciler.py:1199`).

**Room-switch resolver** — `coordinator._resolve_room_switch_entity_id`
(`coordinator.py:3028-3074`), the **ROOM-SWITCH-LOOKUP-BY-NAME-1 fix (2026-10-10)**: resolves
by entity-registry `unique_id = "{entry_id}_{suffix}"`, falls back to the name-built slug
only when registry misses; caches the resolution; WARNs once per `(entry, suffix)` on second
consecutive miss. This replaces the old built-name-only lookup that fell silently open on
HA's double-prefix slug for new rooms (see §9 corrections).

---

## 5. Sensor fleet classes (summary — canonical doc is SENSOR_FLEET_CLASSES.md)

The three Hobeian families (`docs/architecture/SENSOR_FLEET_CLASSES.md`):

| Model | What it is | Holds still person? | URA role | Count |
|---|---|---|---|---|
| ZG-204ZV | mmWave motion-class (PIR-like) | **No** | `motion_sensors` | 22 |
| ZG-204ZK | 24 GHz presence radar | Yes | `presence_sensors` | 5 |
| ZG-204ZX | 24 GHz presence + T&H | Yes | `presence_sensors` | 3 |

**Rules in effect** (SENSOR_FLEET_CLASSES.md §Rules):

- ZV is motion, never presence; do not "fix" a ZV out of `motion_sensors` because its name
  says `presence`/`mmwave` — the name is Z2M's, not its class.
- Four ZV devices carry a dead bare `_presence` entity (Z2M rename leftover); URA uses the
  live `_presence_2`.
- Capability keyed by TRUE class (`sensor_capability.py`), not by entity name.
- **Retired by fan-noise Rev 2 C2 (branch, not deployed):** `fan_veto.MMWAVE_NAME_PATTERN`
  (`fan_veto.py`) is kept but has no live reader. `coordinator._d2_motion_sensors_present`
  and `fan_veto._has_recent_motion` now keep a motion sensor iff
  `fan_veto.is_fan_immune_motion_witness` = `sensor_capability.is_fan_immune_witness`
  (capability kind ∈ motion/pir/pir_split/bed/camera_presence/ble_presence, override-aware)
  AND its device family (`fan_veto.resolve_sensor_family`: entity → device `model_id`, fallback
  `model` → `sensor_capability.FAMILY_BY_MODEL_ID`, cached per boot on `hass.data`) is not a
  radar family. ZV rooms now reach D2. HISTORICAL (before Rev 2): the regex excluded every
  ZV (`…_presence`) so D2 was unreachable in ZV-only rooms.

---

## 6. Fan-noise mechanisms (and their measured efficacy 2026-10-11)

Three complementary mechanisms exist; **each covers a different direction**:

1. **Fan-transition CREATION gate** — `coordinator.py:3601-3745`, const
   `FAN_TRANSITION_SUSPECT_WINDOW_S` — **RETIRED to 0.0 by Rev 2 C5** (was 5.0 s; code kept,
   `_fan_transition_suppressed_count` frozen). Suppresses NEW occupancy
   creation when a mmwave-sole rising edge coincides with a fan transition inside the
   window. Does not extend existing holds; sustain never interrupted (predicate (c)); kill
   switch = 0.0.
2. **D2 sustain demotion** — mmwave-fan demotion gate on sustain path, requires a REAL PIR
   motion sensor by `_d2_motion_sensors_present` (`coordinator.py:2159-2188`). Fail-closed
   when no fan-immune witness is present. (CORRECTED 2026-10-12: an earlier line here said
   "7/10 fan rooms, ZV-only means D2 is UNREACHABLE". That is WRONG on current code. A ZV
   resolves to family `zigbee_zv`, which is not in `RADAR_SENSOR_FAMILIES`
   (`sensor_capability.py:408`), so `is_fan_immune_motion_witness` keeps it, and ZV rooms
   reach D2. See the Rev 2 note above. Only rooms whose motion sensors are all radar
   (e.g. Media, MS600 only) fail closed.) Sleep/Waking/Home-Night exempt (`coordinator.py:2190-2210`).
   **D2-PIR-STAMP-FOLLOWS-FAN-IMMUNE-WITNESS-1 (2026-10-12):** the PIR staleness leg (e)
   stamp `self._last_pir_motion_time` and the flap-latch `pir_motion` clear reason are
   both now gated by `_fan_immune_motion_witness_on(motion_sensors)` (reuses
   `fan_veto.is_fan_immune_motion_witness`) — a radar-derived motion bit filed under
   `CONF_MOTION_SENSORS` (e.g. meross_lan MS600 `..._presence_motion` on GB1/GB2/Media)
   can be faked by a fan, so stamping on it kept `pir_stale` False forever and the latch
   oscillated. Classifier is capability + device-model; on exception -> no stamp / no clear.
   The helper iterates `_fusion_filter_active(motion_sensors)`, the same stuck/chatter-filtered
   list `motion_detected` uses (Review A HIGH fix-up), so an excluded-but-on PIR is not a witness.
   **Scope fence:** the P24 max-occupancy FAILSAFE freshness gate (~4705) does NOT read the
   witness-only stamp. It reads `_last_motion_bit_time`, which keeps the pre-change semantics
   (refreshed on any `motion_detected` tick). Moving the failsafe onto the witness stamp would
   force-vacate a sleeping guest in GB1/GB2 after the failsafe duration, held only by the MS600.
   That is a separate policy decision, not part of this card (Review B MEDIUM). Sites: `coordinator.py` PIR stamp branch (~3948) +
   `_evaluate_mmwave_demoted_latch` `pir_motion` reason (~2951). The pre-fix behaviour was
   the sole-reason the ZV-only fail-closed from `_d2_motion_sensors_present` was not the
   only D2 blocker in rooms with both a ZV AND a radar-derived motion bit.
3. **Fan pause-recheck** — `domain_coordinators/presence_fan_recheck.py:1-60+`. Pauses the
   fan, re-reads mmwave with airflow stopped, drops occupancy if empty. Routes ALL writes
   through `hvac_fans.FanController._set_fan_state`. Config: `CONF_FAN_RECHECK_*` family.
   **Rev 2:** a VACATED verdict calls `restore_after_recheck(..., leave_off=True)` — every
   restore discharge runs but no ON is written (a live manual-ON hold still restores ON);
   eligibility vetoes `manual_on_hold_live` and `fan_quarantined` (ActuatorReconciler flap
   quarantine); window = CM window × room-type factor × dominant presence-sensor family factor
   (`SENSOR_FAMILY_RECHECK_FACTOR`, kill switch `fan_recheck_family_scaling_enabled`);
   cooldown default 900 s; PAUSED/COOLDOWN rehydrate read the live effective window / knob.
4. **Comfort-fan house-AWAY veto** — `fan_veto.py:1-80+`. ONE predicate consumed by all
   three comfort-fan actuation sites (room-tier `automation.py::handle_temperature_based_fan_control`,
   HVAC `hvac_fans.HvacFanController.update`, reconciler `actuator_reconciler._resolve_fan`).
   Mmwave EXCLUDED from "trusted presence" in AWAY/VACATION. Kill switch
   `CONF_COMFORT_FAN_AWAY_VETO_ENABLED`.

**Measured efficacy 2026-10-11 (operator probe, scratchpad; use as "measured 2026-10-11"
with the caveat that these come from the ~7-day recorder window 2026-10-04→10-11 plus URA DB episodes since v5.84.1):**

- Fan recheck: **27 of 28 releases were undone by a fan restore loop** (restore-on-vacate
  re-arms the fan, mmwave re-asserts, occupancy reinstates). The recheck mechanism is
  essentially cancelling itself today.
- Fan-transition CREATION gate: **23 of 27 fires came from dead fan entities** (stale
  `_fan_last_transition` on fans that no longer exist / are unavailable). The gate is firing
  on noise.
- D2 sustain demotion: **unreachable in 7 of 10 fan rooms** because those rooms have no
  real PIR (ZV-only). `_d2_motion_sensors_present` fail-closes and refuses to demote.
  (SUPERSEDED, corrected 2026-10-12: since the Rev 2 capability/family classifier, a ZV counts
  as a fan-immune witness and ZV rooms reach D2. Only rooms whose motion sensors are all radar
  still fail closed.)
- Study A fan room: approximately **26 hours/week of false holds** attributable to fan
  interference while the room was empty.
- Jaya room (ESPHome LD2410): **68 % of the time, "presence" fires with the room empty and
  the fan on**; the ZV / ESPHome window carries 28-30 of those stamps per band.

These are the current numbers that argue the three mechanisms converge on blind spots and
need redesign at the SENSOR-CLASS level (operator roadmap: fuse by capability class, not by
entity-name regex).

---

## 7. House state transitions — guest / sleep / arriving

- **Guest latch** (v5.16.0 fix). GUEST → SLEEP transition had been missing; the latch now
  survives the night. See memory `project_presence_guest_latch_and_veto_gap`.
- **Guest-mode false-positive gap** (open): LOST-but-away excluded from the trusted
  denominator → phantom unidentified → spurious GUEST
  (`project_guest_mode_false_positive_backlog`).
- **Sleep bedroom D2 exemption** at `coordinator.py:2190-2210` — mmwave stillness in a
  sleeping bedroom is EXPECTED; D2 demotion is REFUSED there.
- Identity / census interplay belongs in `IDENTITY_FUSION_CAMERAS_MANUAL.md` — see §1
  (camera platforms), §3 (face-name availability), the egress-identity producer / JOIN. Do
  not re-litigate those here.

---

## 8. Restart / boot behaviour

- **`_skip_first_automation`** (`coordinator.py:555`): room coordinator skips the first
  automation pass after setup. Captured BEFORE the if-block in each tick
  (`coordinator.py:5061`) so downstream humidity-gate / reconciler see the same value
  (`_humidity_gate.py:31-51`, `actuator_reconciler.py:550`). Cleared on first tick
  (`coordinator.py:5069-5070`).
- **Boot settle gate** — `BOOT_SETTLE_MIN_INPUTS = 1` (`const.py:3789`),
  `BOOT_SETTLE_TIMEOUT_SECONDS` (also in `const.py`). Presence waits for at least
  `BOOT_SETTLE_MIN_INPUTS` census-count inputs before admitting the first inference
  (`presence.py:5620-5645`).
- **House-state restore** — `house_state.py:33-54`: version 1 store, 1800-s max staleness,
  300-s heartbeat; override survives restart.
- **Memory writers restart-discharge invariant** — `presence.py:6438-6440`: the coalescer
  cannot emit before `reconcile_open_away_block_on_boot` runs.

---

## 9. Known gaps / open cards (grep `docs/planning/kanban.data.yaml`)

Open-ish cards touching presence / BLE / fan / mmWave / census (most-recent first; one-line
each; verify current status in the board):

- **HOUSE-STATE-SENSOR-BOOT-AWAY-DISPLAY-1** (2026-10-11) — boot-time house-state sensor
  reads AWAY while inference still settling.
- **CENSUS-NAME-SPACE-DEDUP-1** (2026-10-11) — census name-space dedup gap.
- **CENSUS-INPUTS-FIRST-1** (2026-10-11, 2026-10-09, 2026-10-05) — census producer
  inputs-first measurement; plan rev-2 awaiting re-review.
- **CENSUS-SHUTDOWN-AWAY-FENCE-1** (2026-10-11, 2026-10-06, 2026-10-05) — shutdown-time
  census fence.
- **CENSUS-GROUND-TRUTH-CSV-FIX-1** (2026-10-05).
- **CENSUS-PATIO-THROUGH-GLASS-1** (2026-10-05).
- **CENSUS-ATHOME-RESIDENT-CORROBORATOR-1** (2026-10-08).
- **OC-STUCK-SENSOR-GENERALIZE-1** (recurring; stuck-sensor generalization).
- **STUCK-SENSOR-WARNING-PER-TICK-1** (2026-10-09).
- **FAN-ORACLE-BOOT-FALLBACK-NOISE-1** (recurring 2026-10-05 → 2026-10-09).
- **BLE-BLEED-EXTEND-SLEEP-1** (2026-10-08).
- **RESTORE-UNAVAILABLE-OFF-SWEEP-1** (recurring) — RestoreEntity unavailable → OFF sweep
  (same bug class as the Envoy incident, memory `project_envoy_boot_incident_2026_06_12`).
- **EGRESS-BLE-ENTRY-ATTACH-1** (2026-10-05) — egress identity producer attach rate — see
  `IDENTITY_FUSION_CAMERAS_MANUAL.md`.
- **ROOM-ENERGY-SENSOR-MISPICKS-1** (2026-10-11) — sensor-mispick class (adjacent).

- **Rev 3 D4d trip-wire `zone_hold_all_away` (branch, NOT deployed).**
  - **When it fires:** one HIGH stuck-signal NM when the house is held out of AWAY by Tier-1 room sensors alone for more than `ZONE_HOLD_ALL_AWAY_NM_BOUND_S` (7200 s; 0 = off). "Alone" means all of: not AWAY/VACATION/SLEEP; no override; census 0; every trusted tracker away; a zone occupied; no BLE-occupied zone; a Tier-1 holder room.
  - **Coverage:** in practice it pages only while the Frigate fleet is dark, since otherwise α discharges an empty house. The Tier-1 holder must sit in a zone that reads OCCUPIED (build reviews A-L3 / B-L2).
  - **Silent cases (named, no code change):**
    - No trusted tracker. This covers Wigton S0 and also THIS house when every resident is LOST (build review D-L1). Card WIGTON-STUCK-ZX-NO-PAGE-1 covers both shapes.
    - The holding sensor also corroborates a camera-count divergence. `camera_census._any_zone_occupied_snapshot` keeps the higher count, so census ≥ 1, which blocks α and nobody-home and silences D4d (reviews B-L1 / D-L2): one piece of evidence counted twice.
    - The away-veto switch (`switch.ura_presence_away_veto_enabled`) is off. That coerces `all_tracked_persons_away` False.
  - **ZONE-ROOM-NAME-DRIFT-1 (PRIORITY follow-up, build review D-M2).** A room renamed through options keeps its old name in the zone tracker.
    - With the switch ON, the D4c.2 walk releases the old name's kinds, and the new name's edges find no tracker. A sleeper in a renamed room therefore loses night cover until presence re-discovers (a restart), and nobody-home can AWAY it.
    - This is a regression versus `dad3bf6e7`, whose D-H1 limb covered it by accident. It is NOT a regression versus develop, which has no D1.
    - By day the two are equivalent, except that switch-off keeps the old name stuck True.
  - **Accepted by name (build review D-L3):** an entity listed in two rooms belongs to the first claim only (config already WARNs). With the switch on, the second room loses its night cover, which the D-H1 limb also covered by accident.
- **HOUSE-STATE-AWAY-FLAP-UNTRACKED-OCCUPANT-1** (2026-10-18) — operator approved the SMALL cycle
  (SLEEP-mask fix + 5-min resident BLE memory + AWAY-branch/flip-count/guest-reason observability);
  Rev 4 camera guard + guest-room veto PARKED (revive when guest accuracy is a priority). Must
  help or be inert on Wigton-shaped installs (no interior cameras / BLE). Census estimator PARKED.
- **STUDYA-ZK-EMPTY-HOLD-1**, **EXERCISE-ROOM-ZK-NEVER-ON-1**, **MASTER-BATH-NO-TRUSTED-PRESENCE-1**
  (2026-10-18) — sensor-quality residuals from probe P3. Exercise Room's radar entity is
  `binary_sensor.mmwave_zigbee_gameroom_presence` (device `Mmwave_Zigbee_ExcerciseRoom`, area
  exercise_room — only the entity_id says gameroom); zero `on` in 7 days.
- Jaya Bedroom LD2410 + fan forms a hold loop (fan-off only acts when house AWAY, fan keeps LD2410
  phantom on) — reason Jaya was dropped from any room veto (Rev 4 §15, R2 H2).

Memory-backed open threads: Jaya ESPHome LD2410 fan interference (operator probe
2026-10-11); fan recheck restore-loop defect; D2 unreachable in ZV-only fan rooms; ZV
fan-susceptibility measurement running 2026-10-11 (verdict to be recorded in
`SENSOR_FLEET_CLASSES.md` §Open item).

---

## 10. CORRECTIONS LEDGER — claims that were wrong, do not re-assert

1. **"Steady-state fans are innocent of phantom mmwave presence."**
   Source: `docs/articles/mmwave_fans_transition_gate.md` and
   `docs/articles/mmwave_fan_alignment_probe_results.md`. **CORRECTED (2026-10-11):** true
   for Zigbee ZK/ZX in that specific probe window; **false for ESPHome LD2410** (Jaya room
   measurement 2026-10-11: 68 % of time presence fires in empty room with fan ON, 28-30
   stamps per band). The articles' conclusion must not be used to justify disabling the
   fan-transition gate or de-prioritising fan noise work on ESPHome rooms.

2. **"Living Room mmWave is filed as motion — that's wrong."** **RETRACTED (2026-10-11).**
   The Living Room mmWave is a ZG-204ZX (presence class) — but ZG-204ZV units ARE and
   should remain in `motion_sensors`. The "wrong filing" claim conflated the two families.
   See `SENSOR_FLEET_CLASSES.md` Rule 1 and Rule 3.

3. **"Master Toilet night light not firing — URA bug."** **REFUTED (2026-10-10).** URA
   logs `occupancy_entry` / `occupancy_exit` events, not `light_*` events; absence of a
   `light_*` row is not evidence that the light did not fire. The actuation path was
   proven live by `switch.<room>` state transitions on the same timeline; the perceived
   bug was a log-reading error.

4. **"Room automation switches honour OFF."** **FALSE before v5.103.48 (2026-10-10 fix,
   `coordinator.py:3028-3074`).** The old built-name slug lookup fell silently open on HA's
   double-prefix slug for new rooms and any operator rename, so OFF switches read as "not
   found" and the gate defaulted to ENABLED. The registry `unique_id = "{entry_id}_{suffix}"`
   lookup is the durable identity. **Any claim that an older release honoured a room OFF
   switch for a newly-created room must be verified against this fix.**

5. **"`CONF_MMWAVE_SENSORS` is the way to declare mmWave sensors."** **MISLEADING.** The key
   exists (`const.py`, imported `presence.py:46`) but current occupancy logic routes
   capability through the per-entity `sensor_capability.py` fed from
   `CONF_MOTION_SENSORS` / `CONF_PRESENCE_SENSORS` / `CONF_OCCUPANCY_SENSORS` and operator
   overrides. New plans must not propose wiring through `CONF_MMWAVE_SENSORS` without
   verifying a consumer exists.

6. **"The AWAY-veto denominator is just census_count."** **SUPERSEDED (v5.7.0).** It is the
   path-α × path-β × FRIGATE-FLEET-DARK ladder with LOST-away admission, indoor-clear
   debounce, sleep exemption and camera-degraded fall-through
   (`presence.py:1033-1200`). Do not plan on the pre-v5.7.0 shape.

7. **"The fan-transition gate also protects sustain."** **FALSE** (per code comment
   `coordinator.py:3608-3626`). It covers CREATION only; sustain is covered by D2;
   actuation by `fan_veto`. Three mechanisms, three directions.

8. **"`CONF_MMWAVE_SENSORS` is a legacy key, unused in current flow"** (§4 of this doc,
   2026-10-11 morning). **WRONG (2026-10-11, fan-noise Rev 2 build):** `CONF_MMWAVE_SENSORS =
   "presence_sensors"` (`const.py:480`) — it is the live presence-radar list. There is no
   `CONF_PRESENCE_SENSORS` constant; plans that say "`CONF_PRESENCE_SENSORS`" mean this key.

9. **"Fan family can be resolved from `device.model_id`"** (fan-noise plan Rev 2 §C4).
   **INCOMPLETE (2026-10-11 audit):** ESPHome / Meross devices carry `model_id = None`; the
   resolver falls back to `model`. Custom ESPHome builds (Jaya, Kitchen, Study B, Ziri) report
   the board (`esp32-c3-devkitm-1`) and resolve `unknown`. `docs/planning/AUDIT_motion_sensors_live_models.md`.

10. **"`occupancy_source == "mmwave"` is sufficient to detect a radar-sourced tick."**
   **FALSE (OCCUPANCY-SOURCE-FOLLOWS-CAPABILITY-1, branch `fix/occupancy-source-follows-capability`,
   not yet deployed).** The string names the CONF LIST that produced the tick (`presence_sensors`
   only), not the device capability; a radar filed in `occupancy_sensors` / `motion_sensors`
   never produced it, and a ZK + ZV co-fire produced it although the tick was not radar-sole.
   Trust decisions read `data[STATE_RADAR_SOLE_TICK]` (coordinator producer, ringed in
   `_recent_radar_sole_ring`) and `PresenceCoordinator._room_radar_sole_capable(room)` (presence
   fan-interference gate). The label itself is unchanged (dashboard attribute, DB
   `log_occupancy_event.trigger`, activity log). Kill switch:
   `sensor_capability.OCCUPANCY_SOURCE_CAPABILITY_ROUTING_ENABLED`.

---

11. **"House Sleep stops a zone from going Away."** WRONG (orchestrator, 2026-10-12). The zone
   presence select / `sensor.zone_<z>_presence_status` is pinned to `sleep` by
   `ZonePresenceTracker.set_sleep` (`presence.py:929`, since v3.6.0) — display only; its
   `derived_mode` attribute still says `away`. The thermostat follows the HVAC path:
   `hvac.py:3016` turns a `sleep` target into `away` once the zone is HVAC-vacant past grace
   (zone 3 did so at 00:00 and 00:42 on 2026-10-12). HVAC vacancy uses the per-room HVAC hold
   (v5.103.20 evidence/shadow machine; night tail `ROOM_TYPE_HVAC_HOLD_NIGHT`, bedroom 30 min),
   so the zone dashboard can read "empty" while `zone_N_status.any_room_hvac_occupied` is still
   true — read `hvac_release_at` / `away_due_at` there. Back Hallway stayed in Sleep because a
   guest was sleeping in Guest Bedroom 1 (ZV + MS600 fired together; operator-confirmed).

12. **"Path α requires `census_count == 0` AND all zones away."** WRONG (overnight pass 2026-10-16,
   orchestrator re-read `presence.py:1169-1180`). Path α is trackers-away + unidentified 0 + face 0 +
   camera fleet not degraded; a moment with no interior body on camera is enough even if a room
   sensor holds. This is why an untracked occupant flips the house AWAY (HOUSE-STATE-AWAY-FLAP-
   UNTRACKED-OCCUPANT-1; plan `docs/planning/PLANNING_house_away_flap_untracked_occupant.md`).

13. **"10-11 11:23 was a resident miss: phone GPS said away while Bermuda had Oji in Study A."**
   WRONG (2026-10-18, orchestrator recorder read). The app GPS fix at 11:06 was 27 km from home
   (north Austin); the AWAY was correct, the IRK re-saw the phone at 12:36 on return. Bermuda's
   tracker read `home` with `area: null` (stale), not a room fix. P4's resident-miss count is an
   upper bound for this reason.

14. **"The inference ladder starts with path α."** INCOMPLETE (2026-10-18). The first branch in
   `infer()` is nobody-home (`presence.py:1126-1131`); §2 now lists it as step 0 with its SLEEP-mask
   hazard.

15. **"An entity_id naming a room identifies the room."** Not for `binary_sensor.mmwave_zigbee_gameroom_presence`
   (2026-10-18): it is the Exercise Room's radar (device and area say so). Classify by device/area,
   never entity name — consistent with SENSOR_FLEET_CLASSES Rule 3.

16. **"The sensor's `veto_path` takes `alpha_starved` / `alpha_denies` / `beta_only` / `none`."**
   WRONG (2026-10-18, plan review R1 of the SLEEP-mask cycle). Those are D5 episode labels
   (`presence.py:6548-6561`); the sensor carries the engine values (`presence.py:1124-1277`, mirrored
   `:6518`). The v8 People "Decided by" row maps the D5 vocabulary, so it never matches a live value.

17. **"SLEEP stops nobody-home AWAY."** FALSE before the sleep-mask cycle (2026-10-18): SLEEP-pinned zones read `mode == SLEEP`, so nobody-home saw every zone empty and fired on `census_count == 0` alone. Fixed by D1 on `feature/house-state-sleep-mask-ble-memory`.

18. **"Drop fan-on radar-sole rooms from the night input (fan-loop breaker)."** REJECTED 2026-10-18 by stress test P5 (`AUDIT_census_arc_and_away_holistic.md` §P5): it blanks real sleepers (Jaya 76 % of occupied minutes) and had zero measured need in 220 days. It is parked; revive it only if the `sleep_raw_hold` trip-wire fires on a night a prober proves was empty and held by a fan-on radar-sole room.

19. **"A zone tracker's room view says whether the room is occupied."** FALSE for multi-sensor rooms (review D-H1, 2026-10-18): `update_room_occupancy(room, False, kind)` clears every kind, and the substrate is last-writer per (room, kind). A ZX still holding a sleeper reads empty after a ZV pulse clears. The night input works around it with live sensor state; daytime readers still have the gap (card ZONE-TRACKER-PER-SENSOR-WIPE-1).

20. **"The tracker's derived room view is 'stronger on True, equivalent on False'"** (provenance-split plan). WRONG for multi-sensor rooms (review D-H1; P6: Jaya 56 h, Master 22 h and Kitchen 11 h of wiped-while-on per 7 days). Fixed by Rev 3 D4b (per-kind clear).

21. **"The substrate's per-kind bool is the room's raw kind state."** WRONG before Rev 3 D4a. The live path was last-writer per (room, kind), so one of two same-kind sensors going off reported the kind False while the other was on. Only the seed ORed.

22. **"The HVAC 'Wait for Presence' consensus defer gate's hysteresis bounds its deferral"** (sleep-mask plan §R3.4.2 row 13, first draft). WRONG (plan reviews R2-5 / Rev 3.1 recheck M1):
   - The gate engages at < 0.5 within 30 s of a transition and releases only at ≥ 0.7.
   - A zone held by Tier-1 while all phones are away keeps consensus ≤ 0.6, so it pins an already-engaged gate for the length of the hold.
   - D4 cannot engage the gate alone (1 − 0.4 − 0.1 = 0.5).
   - Accepted by name (PICK R3-4); card HVAC-CONSENSUS-GATE-PIN-1 (probe first). No HVAC code change.

## 11. Read before you touch — agent checklist

Before planning, building, reviewing or diagnosing anything presence-adjacent:

1. Read this doc end-to-end. Verify the §1-§10 claims you intend to rely on against the
   cited `file:line`.
2. For sensor-class questions, read `docs/architecture/SENSOR_FLEET_CLASSES.md`.
3. For identity / camera / census / fusion / egress / perimeter, read
   `docs/Coordinator/IDENTITY_FUSION_CAMERAS_MANUAL.md`. **Do not duplicate** that content
   in presence plans; summarise and link.
4. For HVAC occupancy / tail holds, read `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md`.
5. Prior-art scan (Tier 2+ plans) — grep `const.py` + `config_flow.py` for any proposed
   CONF_* / field / selector before adding a new one; record REUSED (file:line) or NEW
   (why).
6. Producer AND consumer check — for every presence VALUE touched: who produces it (name
   the arithmetic + each dependency's current health), who reads it (file:line, trust vs
   display).
7. Config-first — check the knob ladder (room options flow, Number/Select/Switch entities,
   room config, HA integration) before writing code. Read LIVE values before asserting a
   knob is at a given setting.
8. Mutation-verify any load-bearing site under test by editing production source to
   neuter ONE site at a time and confirming a SPECIFIC test fails (Tier-3 framing C). Aggregate
   monkeypatches prove nothing per-site.
9. Any ship / correction / refuted claim updates this doc in the same commit; a refutation
   goes into §10, never deletes a wrong claim without recording its refutation.


## Addendum 2026-10-11 (orchestrator-verified)
- **D2 reachability root cause:** `_d2_motion_sensors_present()` (`coordinator.py:2159`) filters motion sensors through the same name pattern as `fan_veto.MMWAVE_NAME_PATTERN` (`fan_veto.py:61`, matches `mmwave|radar|presence|ld2410|ld2412`). Every Hobeian ZG-204ZV entity is named `…_presence`, so a room whose only motion sensors are ZVs counts as having **no** motion sensor → D2 can never fire there. Name-based classification contradicts `docs/architecture/SENSOR_FLEET_CLASSES.md` (ZV = motion-class). Fix = classify by device capability (model_id / sensor_capability), not entity name.
- **ZV fan susceptibility (measured):** Game Room fan-immune in steady state with a small power-on transient (3/11 within 5 min); Living Room confounded; Guest Bedroom 1 / Exercise no data. Working rule: ZV usable as a fan-immune witness during steady fan running, not within ~5 min of a fan switching on. Details in SENSOR_FLEET_CLASSES.md.
- **Operator ruling 2026-10-11 — Study A InvisOutlet:** do NOT use the InvisOutlet (`binary_sensor.invisoutlet_b7d0_motion` / its occupancy entity) as a URA motion/occupancy witness in Study A — "problematic for a while". (A 2026-10-11 analysis proposed it as the D2 witness; rejected.) Study A therefore has **no fan-immune witness today**: its only sensor is the ZG-204ZK presence radar. Options: add a ZG-204ZV or real PIR in Study A, or rely on BLE for corroboration.
- **CORRECTION (operator, 2026-10-11):** "with a fan in the sensor's field of view, no amount of tuning recovers it — re-aim first" (from RESEARCH_fan_resistant_mmwave.md, repeated in session) is **WRONG for the Study A ZG-204ZK**. Operator observation over months: with `anti_interference` ON it eventually vacates Study A — better than the away-facing InvisOutlet did. Treat on-device tuning (anti-interference, **detection distance**, sensitivities) as a first-class lever even when the fan is in view; re-aiming is an option, not a prerequisite. Study A tuned 2026-10-11: motion 8→5, static 8→6, distance 4.34→3.0 m (before-values in session scratchpad studya_zk_before_2026-10-11.json); judge by the before/after false-hold measurement.


## Gold patterns index (from PLANNING_fan_noise_running_rejection.md prior-art audit, 2026-10-11)
Reuse these before building anything new (order: reuse > extend > build only if nothing fits).


| Pattern | Where | When to reuse |
|---|---|---|
| **Capability layer + CONF overrides** | `sensor_capability.py:172 derive_capability()` + `CONF_SENSOR_CAPABILITIES` (`const.py:559`) | ANY classification question about a sensor ("is this a PIR?", "fan-immune?", "corroborator?"). NEVER regex entity names. |
| **Role query matrix (pure, HA-free)** | `sensor_role.py:17-18 role_for(entity, room_config, query)` | When the SAME sensor answers different questions under different queries (D2 stuck candidate vs corroborator). |
| **SensorExclusionSet multi-writer quarantine** | `sensor_exclusion.py` | Any new "untrust this sensor's vote this tick" rule; promote with a NEW client name; release per-client. |
| **Recheck state machine (idle→armed→paused→restoring→cooldown)** | `presence_fan_recheck.py` | Any "stop → re-measure → decide" flow with a HVAC-handshake and restart matrix. |
| **Inert-sink eligibility probe** | `presence_fan_recheck._INERT_SINK` + `is_recheck_eligible` | Cross-mechanism "would this gate fire?" checks that must not perturb observability counters. |
| **CM-entry timing knobs via sweep** | `presence_fan_recheck._timing_config` | A family of knobs operator-tunable live, loaded from CM-entry options with DEFAULT_* fallback. |
| **Fan listener (stamp transitions) — last-known-good belief** | `presence.py _handle_fan_change` + `_fan_known_good` (seeded in `_discover_room_fans`) + `_fan_last_transition` / `_fan_on_rooms` / `_fan_on_since` / `_fan_off_at` + `get_fan_last_transition` | Any "did a fan just do something?" window query. Unavailable/unknown edges HOLD the last known-good belief; a return from unavailable in a different state is a real transition (wall-switch power-on). |
| **ActuatorReconciler availability-flap counter** | `actuator_reconciler.py` `_FAN_KEYS`, `_flap_*`, `check_quarantine_release`, `flapping_entities()` / `flapping_detail()`; surfaced on `sensor.<room>_unavailable_entities` | "Is this actuator flapping unavailable↔available?" Recheck reads it via `_fan_in_actuator_quarantine`. |
| **Fan-immune witness (capability + model safety net)** | `sensor_capability.is_fan_immune_witness`, `FAMILY_BY_MODEL_ID`; `fan_veto.resolve_sensor_family` / `is_fan_immune_motion_witness` | Any "can a running fan fake this sensor?" question. Never regex entity names. |
| **HVAC "leave off" discharge** | `hvac_fans.restore_after_recheck(leave_off=True)` → the AWAY-veto skip branch | End a recheck pause without re-arming the fan while keeping every discharge duty. |
| **Kill-switch constant + knob ladder** | `FAN_TRANSITION_SUSPECT_WINDOW_S` module constant; `CONF_FAN_RECHECK_*` CM-entry Numbers; `CONF_ROOM_FAN_RECHECK_ENABLED` per-room switch | Rung 1 for review-only (safety / fitted); rung 2 for per-deployment structure; rung 3 for live operator tuning. |
| **Memory-episode adjudication write** | `coordinator.py:3701-3729` log_memory_episode `fan_transition_suppressed` → adjudication `phantom` | Durable per-event observability for a gated suppression. |
| **Capability-radar-sole boolean** | `coordinator.py` producer (`_radar_sole_on_set` → `data[STATE_RADAR_SOLE_TICK]`) + `_recent_radar_sole_ring` + `any_radar_bearing_on_now`; `presence.PresenceCoordinator._room_radar_sole_capable`; classifier `fan_veto.is_radar_entity` / `sensor_capability.is_radar_capability` | Any trust decision that must distinguish "a radar is the sole tick driver" from "a radar-list entity fired" — never use the `occupancy_source` string for this. |
| **night_raw (sleep-mask D1)** | `PresenceCoordinator._zone_night_raw` / `_zone_night_rooms` | "Is a SLEEP-pinned zone really occupied?" = raw zone occupancy (BLE / room / camera) with NO fan test. Read by nobody-home + the D1b wake disjunct + the sleep_raw_hold trip-wire only. |
| **STALE concept split (deliberate, Bug Class #63)** | D2 `_tracking_active` (STALE = home) vs `fan_veto._ble_present_in_room`, `camera_census._ble_home_by_area`, `aggregation.py` per-zone status (STALE = not present) | Do NOT align them: a frozen tracker must not defeat the fan veto or cancel a real guest, but must not vote a resident away within the decay window. |
| **`_kind_on_now` — one per-kind rule (Rev 3 D4a)** | `occupancy_substrate.OccupancySubstrate._kind_on_now(room, kind, map, *, event_entity, event_state)` | Any per-(room, kind) occupancy bool, seed or live. Pass the map explicitly (a refresh seed uses the DESIRED map); take the event entity from the payload, siblings from `hass.states`. Never re-derive a second rule. |
| **FAN_TRUST_STATES scope** | `hvac_const.FAN_TRUST_STATES`, consulted at `presence_fan_recheck.py:487-491` and `_still_armed_eligible:969-973` | Bedroom-only sleep veto; non-bedrooms proceed through sleep. C1a inherits this scope automatically. |

---

