# PRESENCE — Architecture State of Play (READ FIRST)

**CORRECTION 2026-11-10 (overnight pass, code wins):** this doc carried 34 stale "NOT deployed" markers (on 31 lines). All 18 branches they named (sc-garage-lockout-phase1, lock-face-arrival, sc-lock-exclude-away-lock, perimeter-fp-build, face-source-registry, frigate-mqtt-direct, guest-mode-split, paused-room-lights-fans, fan-noise-running-rejection, recorder-churn-diag-sensors, halo-s1b-nm-panels, census-ble-over-face, occupancy-dwell-anomaly, predict-dwell-migration, house-state-sleep-mask-ble-memory, house-state-attr-unrecorded, ble-grace-fleet-fraction, scanner-areas-own-area) are ancestors of tag v5.108.1 (`git merge-base --is-ancestor`), which HA runs (manifest v5.108.1, restart 2026-11-10 01:04 CST). Every marker now reads "deployed (in v5.108.1, live 2026-11-10)". Behaviour that is deployed but switched OFF by a knob (e.g. the garage lockout switch) is still OFF; deployed does not mean active.

**Geofence person pickup (built 2026-11-11, `feature/forms-release-1`, NOT deployed — PRESENCE-GEOFENCE-FIELD-DEAD-1):** the Presence form's "Geofence Device Trackers" field (`geofence_entities`) is removed; it had no reader (a stored value is ignored; `const.CONF_GEOFENCE_ENTITIES` kept, the dead `__init__` import dropped). `PresenceCoordinator._subscribe_geofence` still tracks every `person.*` present at setup, and now also subscribes any `person.*` added later through `async_track_state_added_domain(hass, "person", ...)` (`_handle_person_added` → `_track_geofence_persons`; both unsubs in `_unsub_listeners`). The add itself is not a transition (no `handle_geofence_event`, no `SIGNAL_PERSON_ARRIVING(source=geofence)`); the next real home/not_home change is. Before this, a person created after URA started (or with no person at setup) never produced a geofence signal until a restart. Tests: `quality/tests/test_presence_geofence_late_person.py` (real hass).

**Status:** forensic snapshot of `develop` as of 2026-10-11; the live house is on v5.103.50.
**Recorder churn, display only (built 2026-10-20, `fix/recorder-churn-diag-sensors`, deployed (in v5.108.1, live 2026-11-10)):** the room sensors `Time Since Motion` (floor 60 s), `Occupancy Timeout Remaining` (ceil 30 s) and `Census Validation Age` (floor 60 s) publish stepped values; `coordinator.data` keeps the raw seconds, so no decision changes. Automation Health publishes start/deadline timestamps instead of elapsed/remaining numbers. Quanta: `const.DIAG_*_QUANTUM_S` (rung 1).
**Census face inputs from `_N` Frigate cameras (built 2026-11-08, `feature/face-source-registry`, v5.107.1, deployed (in v5.108.1, live 2026-11-10) — FACE-SOURCE-REGISTRY-DISCOVERY-1):** the census face reads S5 / S6 / S7 (`camera_census._get_face_recognized_persons`, `_fresh`, `_get_unrecognized_camera_count`) used to skip every Frigate camera whose person sensor ends `_person_occupancy_2` (17 of 29, interior: playroom, upstairs_hall). They now read that camera's face sensor through the device (kill switch `FACE_SOURCE_INCLUDE_DISAMBIGUATED_PERSON_SENSORS`, rung 1, True). S7 (guest count) can only go DOWN (a fresh named face gives `count - 1`; no face sensor stays fail-closed). Presence face pre-arrival (`_get_face_for_camera`) is NOT widened (`FACE_SOURCE_PRESENCE_ARRIVAL_DISAMBIGUATED`, False) because its `SIGNAL_PERSON_ARRIVING(camera_face)` feeds the SC lock regime release / away-lock unlock (§1 table). Details: `IDENTITY_FUSION_CAMERAS_MANUAL.md` §1.1.
**Census face bridge on the live Frigate prefix (built 2026-11-09, `feature/frigate-mqtt-direct`, v5.108.1, deployed (in v5.108.1, live 2026-11-10); FRIGATE-FACE-BRIDGE-DEAD-PREFIX-1):** the fast MQTT face-name latch that feeds `_resolve_face_legs` had been subscribed to the retired `frigate/` prefix, so it received nothing. It now subscribes `<prefix>/tracked_object_update` for every running Frigate entry, through the shared `FrigateEventIngress`, and skips retained messages. More synthetic face legs can now appear between Frigate's sensor resets; the point-read path is unchanged. Details: `IDENTITY_FUSION_CAMERAS_MANUAL.md` §1.3 / §4.5.
**Paused rooms (built 2026-10-19, `fix/paused-room-lights-fans`, deployed (in v5.108.1, live 2026-11-10) — ROOM-OVERRIDE-SWITCH-FORGOTTEN-1):** the room Automation switch / Manual Mode now also stop HVAC-tier and fan-recheck occupancy lights/fans; see §4.5 and §6 item 3.
**Fan-noise running rejection Rev 2 (built 2026-10-11, `fix/fan-noise-running-rejection`, deployed (in v5.108.1, live 2026-11-10) — Tier 2-DB):** C1a recheck VACATED leaves the fan off; C2 fan-immune witness by capability + model safety net (name regex retired); C3 fan belief held through unavailable flaps + reconciler quarantine veto; C4 cooldown 900 + per-family window + rehydrate fixes; C5 transition gate retired (0.0). See §5, §6, §10 item 8, gold patterns. Code at the cited lines wins once merged
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
| `binary_sensor.<room>_occupied` (room occupancy) | `coordinator.py:3613` (STATE_OCCUPIED set in `_async_update_data`) | lighting, fans, covers, zone roll-up, HVAC `RoomCondition.hvac_occupied` (HVAC doc §2), security, perimeter; **NM wall-panel targeting** (Halo S1b, branch `fix/halo-s1b-nm-panels`, deployed (in v5.108.1, live 2026-11-10)): `NotificationManager._panel_target_areas` reads each room coordinator's `data[STATE_OCCUPIED] is True` (display trust only: which panels blink), plus adjacency (`get_adjacent_rooms`, both directions) and house-zone membership through the new public getter `PresenceCoordinator.get_room_zone` (reads `_room_to_zone`; membership only, never the tracker's lossy occupancy view, §10 #19). Phantom holds light a panel needlessly (accepted). |
| Zone `any_room_occupied` / `any_indoor_zone_occupied` | `aggregation.py` + presence consumption `presence.py:6414` | path-β indoor-occupancy guard, HVAC zone rollup, lighting bias |
| `SIGNAL_HOUSE_STATE_CHANGED` | `presence.py` (dispatcher) | HVAC override arrester, fans, lighting, security, EVSE, battery, memory writers; **SC lock regime** (GARAGE-REMOTE-LOCKOUT-SCHEDULE-1, branch `feature/sc-garage-lockout-phase1`, deployed (in v5.108.1, live 2026-11-10)): SLEEP / VACATION / GUEST-in-sleep-window engage the garage remote lockouts, WAKING / HOME_* / ARRIVING release (`security_lock_regime.on_house_state_changed`, fed before SC's auto-follow return). Trust: lock actuation. |
| `person.*` state, `SIGNAL_PERSON_ARRIVING`, HA proximity `sensor.<prox>_<person>_distance` | HA `person` / `presence.py` + `person_coordinator.py` / HA core proximity | **SC lock regime** (same branch, deployed (in v5.108.1, live 2026-11-10)): any resident (every `person.*` minus `security_lockout_excluded_persons`) arriving releases the garage lockouts. Reads raw `person.state` edges by design (edge-triggered reader, like the identity vetoes): `→ home` from `not_home`/zone counts; from `unknown`/`unavailable` only if the last real state was not home ≥ 15 min, or inside 600 s of setup, or no real transition seen since a restore (HA `person` restore). `SIGNAL_PERSON_ARRIVING` is NOT a physical arrival: `source` is `ble` / `geofence` / `camera_face`, and `camera_face` fires for a recognised face on ANY zone camera, interior included (`presence.py` `_handle_face_arrival`, 60 s debounce, no was-away gate). The lock regime therefore counts it only when the person was really away (same ≥ 15 min rule + boot exceptions; review A M2). **Face corroboration (LOCK-REGIME-FACE-ARRIVAL-CORROBORATION-1, branch `feature/lock-face-arrival`, v5.107.4, deployed (in v5.108.1, live 2026-11-10)):** really-away is not enough for `source == "camera_face"`, because a mislabelled face can name a resident who IS away (10-24: Jaya labelled Oji while Oji was abroad). `on_person_arriving` now also requires an independent arrival edge for the SAME person within `PERIMETER_EGRESS_FACE_NONFACE_WINDOW_S` (120 s) and after `PERIMETER_EGRESS_ARRIVAL_BOOT_EXCLUDE_S` (600 s) from lock-regime setup. Both are REUSED rung-1 constants; window 0 means a face never releases. The edge is either a live `person.<slug>` `not_home → home` recorded in `_on_person_event`, or a Bermuda move (`previous_location ≠ location`, method `bermuda`) INTO an entry area: an egress camera's own HA area or a configured door-interior neighbour's area (`arrival_edges.door_entry_areas` over the transit validator). No egress config means no entry areas, so a face never releases. The rule is the D10.5 rule below, extracted into `arrival_edges.py` and shared by both consumers. In practice the Bermuda leg is the one that decides: a tracker edge already releases through P1 and leaves `_really_away` False, so a later face on the tracker leg is a no-op. The gate covers both the garage and the away-lock releases. `ble` / `geofence` / missing source are unchanged. Trust: lock RELEASE (unlock).
- **Review A fix-up, MED-1:** PersonCoordinator overwrites `previous_location` every tick (`person_coordinator.py:1083`), so a live-data move lasts one ~30 s update. The lock therefore listens to PersonCoordinator updates (`async_add_listener`, re-resolved after a reload, unsubscribed at teardown) and stamps every Bermuda move (`arrival_edges.record_bermuda_moves`, ≤ 8 per person). A stamped entry move within 120 s on either side of the face counts. A face with no edge yet is held and re-checked ONCE when that person next makes a Bermuda move; the check is judged at the face's time, and a held face is dropped after 120 s.
- **MED-2:** the lock's boot exclusion is `max(PERIMETER_EGRESS_ARRIVAL_BOOT_EXCLUDE_S, GARAGE_LOCKOUT_BOOT_ARRIVAL_WINDOW_S)`.
- **LOW-1:** lock entry areas are the UNION of all door groups (every egress camera area plus every configured door neighbour). The payload carries no camera, and most face cameras are interior and belong to no door group, so they were not narrowed.
- **CORRECTION (2026-11-09, code wins; card LOCK-ENTRY-AREAS-WRONG-OBJECT-1):** the entry areas are currently ALWAYS EMPTY, so the claim above that "the Bermuda leg is the one that decides" does not hold in code. `security_lock_regime._entry_areas` (:997) passes `hass.data[DOMAIN]["transit_validator"]` to `door_entry_areas`. That object is a `TransitValidator` (`__init__.py:3454`), which has no `_egress_entities` or `_interior_neighbours_by_group`. Those attributes live on `EgressDirectionTracker` (`hass.data["egress_tracker"]`; `transit_validator.py:943, :955`). Effect: a `camera_face` arrival never releases through the Bermuda leg (fail-safe). Perimeter `_near_areas` (`perimeter_alert.py:5062-5066`) has the same wrong-object read, so it reduces to the camera's own area. The unit test uses a `SimpleNamespace` that carries the attributes, which hides the defect.
- **Perimeter D10.5** does not use the stamps. It still reads live data only, so its behaviour is unchanged. No setup-time "resident reads home" release: HA's restore stamps `last_changed` = boot time (review A H1). Proximity: crossing from > R to ≤ R metres (unit via `DistanceConverter`). Trust: release (fail-safe direction). **SC away lock** (SC-LOCK-REGIME-DOOR-LOCKS-1, branch `feature/sc-lock-exclude-away-lock`, deployed (in v5.108.1, live 2026-11-10)): also raw `person.state`, for the persons in `security_away_lock_persons` only. ENGAGE (lock actuation) needs every listed person to read exactly `not_home` (a named zone is not away) for ≥ 300 s, timed from a persisted per-person `not_home` stamp (HA's restore rewrites `last_changed`, so it is never read); boot replays never arm, the 120 s boot recheck arms the remainder. RELEASE whenever a listed person reads `home` (any reading, restored state and short blips included, no blip gate; also checked at the boot recheck) or on `SIGNAL_PERSON_ARRIVING` (same really-away gate as the garage). The regime now keeps `_last_real` for every `person.*`, not only residents; the garage effects stay resident-gated. |
| `person.*` state edges + `PersonCoordinator.data[<name>]` (`method`, `location`, `bermuda_area`, `previous_location`, `last_changed`) | HA `person` / `person_coordinator.py:1080-1090` | **Perimeter D10.5 known-person gate** (PERIMETER-FP-STREET-NOISE-1, v5.107.0, branch `feature/perimeter-fp-build`, deployed (in v5.108.1, live 2026-11-10); `perimeter_alert._nonface_agrees`). Trust: DE-ESCALATE only (a dual-role door camera's alert → LOW), and only as corroboration of a below-0.9 face match naming the SAME person. Counts a real ARRIVAL only: a live `not_home → home` edge recorded by its own `person.*` listener (restore edges with `old_state=None`, `unavailable → home` flaps ignored), or a Bermuda move (`previous_location ≠ location`) INTO the egress camera's own HA area or its explicitly configured door-interior neighbours' areas. Both ignore transitions within `PERIMETER_EGRESS_ARRIVAL_BOOT_EXCLUDE_S` (600 s) of perimeter setup (HA restore stamps `last_changed` at boot, §8), within `PERIMETER_EGRESS_FACE_NONFACE_WINDOW_S` (120 s) of the edge. Interior room hops never count. Same arrival-edge shape as the SC lock regime above, but boot-biased the other way (boot = NOT an arrival). Since v5.107.4 (branch `feature/lock-face-arrival`, deployed (in v5.108.1, live 2026-11-10)) the edge rule lives in the shared `arrival_edges.py` (`live_arrival_slug`, `nonface_arrival_source`, `bermuda_arrival_into`, `area_slug_of_entity`). The perimeter keeps its own constants, listener, `_person_arrivals` and camera-specific `_near_areas`, and its behaviour is unchanged (same 153 tests pass on base and branch). The SC lock regime's camera_face gate uses the same helper. |
| `SIGNAL_CENSUS_UPDATED` | `camera_census.py` | PresenceCoordinator (`_handle_census_update`), inference denominator |
| `binary_sensor.ura_presence_coordinator_visitors_present` (unique id `universal_room_automation_visitors_present`; GUEST-MODE-SPLIT-VISITORS-1 D1, branch `feature/guest-mode-split`, deployed (in v5.108.1, live 2026-11-10)) | `PresenceCoordinator._update_visitors_present` per tick; entity `binary_sensor.VisitorsPresentBinarySensor` (polled, Presence Coordinator device) | **Display only**; no reader in URA (not `infer()`, no NM). On = house GUEST OR `legs.room` (30-min guest-room gate) OR `legs.cam` (Path A, kill `VISITORS_CAM_LEG_ENABLED`) OR `legs.stay` (stay latch). Legs are evaluated only in HOME_* / GUEST (stay in any state). Guest Detection OFF → follows GUEST only. `legs` unrecorded; `since` = last off→on edge. D0 expects short `cam` flashes ~0.4-2.4/day with no visitors |
| `PresenceCoordinator._guest_stay_active` / `_guest_stay_since` / `_guest_stay_basis` / `_guest_stay_day_veto` (same branch; the last is v5.108.5, display only) | `_refresh_guest_stay` (DB walk, §2 step 3) | **Trust:** `_compose_guest_gate` (GUEST entry/hold). Display: house-state sensor attributes, `visitors_present` `legs.stay`. D4 trip-wire `_check_guest_stay_long`: one HIGH stuck-signal NM `kind=guest_stay_long` when the latch has been on > `GUEST_STAY_LONG_NM_DAYS` (28; 0 = off) from `since` and Guest Detection is on (RAM latch, re-armed when the latch drops or the switch is off; a restart during a > 28-day stay re-pages at most once per day via the `fire_stuck_signal` per-day dedup, accepted) |
| `person.*` entities + `sensor.<person>_room` | `person_coordinator.py` | guest gate, census identity fusion, egress, perimeter enrichment |
| `person_state_for_trust(hass, person_entity_id)` → `PersonTrackingCoordinator.effective_person_state` (GPS-assistive cycle, live since v5.103.90) | `person_coordinator.py` (module wrapper + method) | raw `person.state` TRUST readers: `aggregation.py` `_sleep_person_fallback_occupied` / `_nonsleep_person_fallback_occupied` (zone_persons_home veto), `hvac_zones.ZoneManager.zone_has_home_person` (no production caller: no-op today), `hvac.py` night-trust preset hold + `main_row_home_persons` (display, activity log), `hvac_fans.py` night vacancy hold, and (CENSUS-BLE-OVER-FACE-1, branch `fix/census-ble-over-face`, deployed (in v5.108.1, live 2026-11-10); plan `docs/planning/PLANNING_census_ble_over_face.md` rev 4) the `camera_census._get_face_recognized_person_names` stale-face latch guard. That guard reads raw state once; raw `not_home` drops as before, otherwise (rung-1 `CENSUS_FACE_LATCH_FOLLOWS_BLE_LEADS`, default True) it asks this helper and drops an overruled adult's face, counted per tick in `face_dropped_ble_overrule_count` on `sensor.universal_room_automation_persons_in_house` (unrecorded). The dropped body stays in the camera total, so it can raise `unidentified_count` (measured cost accepted by the operator, plan §4.3). `_get_face_recognized_persons_fresh` (confidence corroboration) stays raw: body evidence, not identity. The earlier "left RAW on purpose" choice is superseded (§10 #28). Returns the raw HA state except `not_home` for a person overruled on the last tick (and URA location `away`, switch on). No person coordinator / any error → raw. Identity vetoes (`camera_census` `is_face_leg_person_vetoed`, `transit_validator` egress veto) and edge-triggered readers stay raw by design. |
| `environmental_data.occupied` (5-min sample of room `STATE_OCCUPIED`, keyed by entry_id) | `coordinator.py` data-logging block | **room dwell model** (`room_dwell_model.py`, branch `feat/occupancy-dwell-anomaly`, deployed (in v5.108.1, live 2026-11-10)): share of time occupied by local hour x weekday/weekend, nightly rebuild, read-only → `binary_sensor.<room>_occupancy_anomaly` (display only; no notification). Also `get_uncomfortable_minutes_today`. **PREDICT-MODEL-DWELL-MIGRATION-1 (branch `feature/predict-dwell-migration`, deployed (in v5.108.1, live 2026-11-10)):** the same model now also feeds (a) the room `Bayesian Occupancy Forecast` / `Bayesian Occupancy Pattern` sensors (display; kill switch `FORECAST_DWELL_SOURCE_ENABLED`), and (b) one WRITE: the hourly `dwell_share` producer on `RoomDwellModelRunner` (`room_dwell_model.py` `_dwell_tick`) writes one `prediction_results` row per room per UTC hour, `room_id = entry_id`, predicted = the share frozen at minute `DWELL_SHARE_TICK_MINUTE` of the hour from a model with `trained_until_utc <= start(H)`, actual = the hour's occupied fraction from this same signal; **`confidence` holds the cell's sample count, not a probability**; `error_value` signed (expected − actual). Kill switch `DWELL_SHARE_PRODUCER_ENABLED`. These predictions describe the room-occupancy SIGNAL, so phantom holds count as "usual" and "accurate" (accepted). |

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
   **FIXED on branch `feature/house-state-sleep-mask-ble-memory` (sleep-mask cycle, deployed (in v5.108.1, live 2026-11-10)):**
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
   (`presence.py:1227-1232`, gate comments `:1206-1226`, re-read 2026-10-24). It does NOT check `census_count` or zone/room
   occupancy (corrected 2026-10-16, see §10 #12). Gated on
   `face_recognized_count` to close the forgotten-phone inflation,
   const `CENSUS_FACE_RECOGNITION_WINDOW_SECONDS = 1800 s`, cross-check
   `camera_census._get_face_recognized_person_names` stale-face latch guard (~`camera_census.py:5893-5940`).
2. **AWAY path β** (v5.7.0 WS-A) — admits `LOST`-but-away trackers into the AWAY denominator,
   gated by indoor-occupancy guard (A2/A4), configurable `CONF_LOST_AWAY_GRACE_MIN` (A3) + sleep
   exemption + the FIX-2b indoor-clear tick debounce (`presence.py:1053-1072`,
   `CONF_LOST_AWAY_GRACE_MIN`, `CONF_LOST_AWAY_INDOOR_CLEAR_TICKS`,
   `CONF_LOST_AWAY_SLEEP_EXEMPT`).
3. **GUEST** — `guest_gate_armed = True` while home. (The old wording here, "`_guest_gate_armed()`
   pre-evaluates threshold / confidence / persistence", is stale since GUEST-CENSUS D2, 2026-08-16:
   Path A arms nothing, see §10 #30.) **GUEST-MODE-SPLIT-VISITORS-1 (v5.108.0, branch
   `feature/guest-mode-split`, deployed (in v5.108.1, live 2026-11-10); plan `docs/planning/PLANNING_guest_mode_split_2026_11.md`
   rev 5):** `guest_armed` is composed in ONE helper, `PresenceCoordinator._compose_guest_gate`
   (called at the HOME_* and GUEST branches of `_run_inference`):
   - rule OFF (`const.GUEST_NIGHT_STAY_RULE_ENABLED` False, rung 1): the 30-min guest-room gate
     (`_guest_room_gate_armed`), byte-identical to before (golden
     `quality/tests/fixtures/guest_split_golden_base.json`);
   - rule ON (default): HOME_* → the **stay latch** `_guest_stay_active` (masked by the Guest
     Detection switch); GUEST → the latch except at a house sleep hour (**night yield**, §7).
     The 30-min room gate and Path A are still evaluated but only feed `visitors_present` and
     `guest_reason`. A 30-min (or 5-hour) daytime visit no longer enters GUEST.
   - **Stay latch producer** `_refresh_guest_stay` (one writer; deterministic walk over the URA
     DB, so a restart reproduces it): for each of the last `GUEST_STAY_REPLAY_NIGHTS` (35) completed
     nights, the house sleep window from the engine (`sleep_start_hour` / `sleep_end_hour`, CM
     options, live 22 → 6; NOT the per-room sleep-protection hours) and per designated guest room
     the share of that window occupied (`occupancy_events` by room entry_id, via
     `Database._occupied_episodes_between`) minus resident time (`person_visits` by room name,
     ± `GUEST_KNOWN_STICKY_S`; an open visit, `exit_time` NULL, runs to the latest window end), in
     `Database.get_guest_room_night_fractions`. `had_evidence` is computed AFTER the resident cut. A
     night qualifies at ≥ `GUEST_NIGHT_MIN_FRACTION` (0.25).
     **Rev 5 entry (operator 2026-11-09: "sustained occupancy during the day and an overnight should
     suffice"):** the latch turns on at an ENTRY-QUALIFIED night: the same guest room also had
     ≥ `GUEST_STAY_DAY_MIN_FRACTION` (0.10) non-resident occupancy of its day window
     (`guest_day_window`: local N `GUEST_STAY_DAY_START_HOUR` (10):00 → the night start, ≥ 1 h), with
     ≥ `GUEST_STAY_ENTRY_NIGHTS` (1; 2 = second-night guard) qualifying nights among the last
     `GUEST_STAY_LOOKBACK_NIGHTS` (3). **Rev 6 exit:** off after min(`GUEST_STAY_EXIT_MAX_NIGHTS` (2, operator
     ruling 2026-11-09), n) straight non-qualifying nights, n = qualifying nights in the stay so far
     (starting from the entry night's lookback count), so a one-night visit ends after one empty night
     and any longer stay after two (`GUEST_STAY_EXIT_SCALES_WITH_STAY`, rung 1, True; False = the fixed
     3-night exit of rev 5). **Re-entry grace** (`GUEST_STAY_REENTRY_GRACE_DAYS`, 7, 0 = off; only with
     the scaled exit): for 7 days after a stay ends by empty nights, ONE qualifying night in any guest
     room re-enters, no day test (a guest away overnight who sleeps in the room again).
     **Exit day veto (operator 2026-11-10, v5.108.5, `AUDIT_guest_onset_thresholds_and_hvac_evidence_states_2026_11_10.md`
     §1.3-§1.5):** the empty-night exit does NOT fire while any guest room's non-resident day fraction is
     ≥ `GUEST_STAY_EXIT_DAY_VETO_FRACTION` (0.10, `const.py:554`, rung 1; > 1 = veto off) on a day
     window paired with a night inside the exit window (`_veto_room`, `presence.py:6279`, exit test at
     `:6334-6350`). It reuses the day fractions of the same span read (no new DB read, no new state),
     applies only with the scaled exit (False = rev 5 exactly), and a "Guest left" press still beats it
     (a stay only starts on a post-press night and n counts only post-press nights, so an exit window
     never reaches a pre-press day). October replay with the veto: GUEST 09-28..10-14 and 10-16..10-18
     (the nights away 10-13/10-14 end it; the night back 10-15 re-enters; days 10-16 (0.46) and 10-17
     (0.22) hold it, so 10-17 is no longer dropped; 19 of 21 stay days); 0 days in 10-19..11-08. Cost on
     the unlabelled pre-stay period: the 08-25 stay is held through daytime-occupied empty nights into
     09-12 (pinned in `test_guest_stay_producer.py::test_replay_fixture_day_list_day_veto`). Residual: a
     phantom DAYTIME guest-room hold (fan + MS600 radar, no fan-immune witness in GB1/GB2, §6 item 3)
     now also holds a stay. Bounds (v5.108.5 review A LOW-1 / B LOW-1): the D4 28-day page only PAGES, it
     releases nothing; what ends a veto-only hold (no qualifying night) is the replay window, since the walk
     starts False `GUEST_STAY_REPLAY_NIGHTS` (35) nights back, so the stay drops once its entry night leaves
     the span, about 33 nights after entry. A phantom needs only 0.10 x 12 h = 72 min of a guest-room day
     (GB1/GB2: MS600 radar-derived motion only, no fan-immune witness; GB2 has no BLE scanner, so a
     resident's daytime use there is not subtracted either). The same roll-off also drops the `ended_on`
     anchor, so a grace re-entered stay that follows a long veto-held stay can lose its grace (and the
     latch) about 6 nights later with no new evidence (fails toward no GUEST; deterministic on restart).
     The veto reads ANY guest room, while entry pairs night and day in the SAME room (deliberate, review
     A LOW-2). **Grace reach (review A MEDIUM-1):** a vetoed exit fires later, so `ended_on` (the night that
     ended the stay) moves later and the 7-day re-entry grace reaches later nights; effective reach = the
     daytime hold length + 7 days. Replay: with `GUEST_STAY_ENTRY_NIGHTS` 2 the 08-26 stay is held to
     09-12 and night 09-16 re-enters by grace (`test_replay_fixture_day_list_entry_nights_2`; chain pinned
     by `test_day_veto_hold_then_exit_then_grace_reentry`). **GUEST exposure (review B LOW-3):** every extra
     GUEST day also keeps exterior-person NM severity at the GUEST row (MEDIUM, delivered nowhere) where
     HOME_DAY with no resident home is HIGH (perimeter approach / first_sighting), re-arms security
     ARMED_HOME each morning when auto-follow is on (default off), and pauses Bayesian learning and the
     dwell-anomaly evaluation; all pre-existing GUEST semantics. **Observability (review B LOW-2):** the
     walk publishes the veto holding the latch on the last walked night as `_guest_stay_day_veto`
     (`{room, night, day_fraction}`, highest day fraction wins; None otherwise; cleared by the press and
     by a failed first walk), on the house-state sensor as `guest_stay_day_veto_active` /
     `_room` / `_night` / `_fraction`, plus one INFO `Guest stay exit held by the day veto` per new hold.
     Without the veto the list was 09-28..10-14 and 10-16. Grace re-entries bypass `GUEST_STAY_ENTRY_NIGHTS`. A stay entered by
     grace keeps the original stay's end as the anchor and opens no new grace (review D: no phantom
     chain), so the window never extends past 7 days from the last normally-entered stay's end.
     **"Guest left" button** (`button.ura_presence_coordinator_guest_left`, unique id
     `universal_room_automation_guest_left`, Presence Coordinator device, CM entry):
     `PresenceCoordinator.async_guest_left` clears the latch, records the press time (RAM + HA Store
     `universal_room_automation.guest_left`, loaded by the walk), and runs one inference with trigger
     `guest_left_button`; that tick skips the S9 exit hold once, so GUEST → HOME_* happens now (unless the
     300 s GUEST minimum dwell rejects it; the latch is off, so the next ticks exit). The walk only lets a
     night that STARTS after the last press enter, so the old nights cannot re-latch (also after a
     restart) and a button exit opens no re-entry grace; pre-press nights count toward neither entry
     (q) nor the exit length (n). A failed Store read is retried on the next walk; a failed save is
     retried once. Prior art: no guest-clear action existed;
     the house-state override select (`select.py:225-331`) pins a state and is not reused.
     n is a walk-loop local, so a restart reproduces it.
     `GUEST_STAY_DAY_BEFORE_NIGHT` (True) False also accepts night N−1 with day N. Night and day
     windows go through ONE span read per room. Scheduled (never awaited) by
     `_maybe_schedule_guest_stay_refresh` from each tick once the last completed night changes, and
     once at setup; cancelled at teardown, and no walk is scheduled after teardown starts
     (`_guest_stay_torn_down`). `_discover_guest_rooms` clears the evaluated night, so a flagged or
     un-flagged guest room is walked on the next tick. DB error → the night is NOT stamped evaluated,
     retry after `GUEST_STAY_ERROR_RETRY_S` (900 s); the previous latch / since / basis are KEPT if a
     walk succeeded since boot (`_guest_stay_walked_ok`), else latch off with basis `{"error"}`.
     Clocks: occupancy rows are naive UTC; `person_visits` rows are naive PROCESS-local (§10 #32).
   - GUEST from HOME_* is now reached only by the latch, the manual override, or restart restore.
     The arrival day never shows GUEST (no night yet; parked; `visitors_present` covers it); GUEST
     starts the morning after the first night (replay: stay day 2).
4. **SLEEP** — census people present AND sleep hours (default 23 → 06, overridable in ctor
   `presence.py:1017-1025`).
5. **HOME_DAY / HOME_EVENING / HOME_NIGHT** — census people + time-of-day variants
   (`evening_start_hour=18`, `night_start_hour=21`, `presence.py:1019-1020`).
6. **ARRIVING** — new arrivals from AWAY (`presence.py:1012`).

**FRIGATE-FLEET-DARK gate** (`presence.py:1073-1085`, kwarg
`camera_input_degraded`): when the camera input fleet is dark (Frigate configured AND
status bad), path α SKIPS because the "0 unidentified" denominator becomes unreliable;
control falls through to path β / GUEST / SLEEP.

**AWAY observability (sleep-mask cycle D3, branch, deployed (in v5.108.1, live 2026-11-10)).** These are attributes on the house-state sensor:
- `last_away_branch`: `_veto_path` at the inference edge, or `override` for `override_adapter` / `boot_settle_override`; there is no `restore` source.
- `last_away_at`.
- `away_entries_today`: counted in `_dispatch_house_state_change` after the boot-settle and observation gates, next to the `house_state_log` write. The getter reads 0 on a new local day. At setup it is hydrated with a naive-UTC `start_of_local_day` bound, via `count_house_state_changes_since(..., state="away", exclude_same_previous=True)`.
- `guest_reason`: `guest_room:<room>` > `unidentified_persistent` > `override` > `none`.
  Since GUEST-MODE-SPLIT-VISITORS-1 (branch, deployed (in v5.108.1, live 2026-11-10)), with the stay rule on,
  `night_stay:<rooms>` leads when the stay latch is on in HOME_* / GUEST, and `guest_room:<room>`
  means "a visitor in a guest room", not GUEST (§10 #31). The same sensor publishes
  `guest_stay_active`, `guest_stay_since` (UTC, window end of the night that turned the latch on)
  and `guest_stay_basis` (last 3 nights: `night`, `room`, `fraction`, `day_fraction`, `qualifies`,
  `entry_qualified`; or `{"error"}`). Note `day_fraction` there is the day of the room with the highest
  NIGHT fraction; the exit day veto reads any guest room, so read `guest_stay_day_veto_*` (v5.108.5)
  to see whether the veto holds the latch.

`stale_counted_home` and `nobody_home_zone_input` are in `_unrecorded_attributes`. Since
HOUSE-STATE-SENSOR-ATTR-CHURN-1 (branch `fix/house-state-attr-unrecorded`, deployed (in v5.108.1, live 2026-11-10)) so are
`dwell_seconds`, `zones`, `signal_consensus`, `signal_consensus_band` and `signal_consensus_inputs`
(`sensor.py` `PresenceHouseStateSensor`). Live attributes are unchanged. For recorder history, use
`state_since` for dwell, and use `sensor.ura_presence_coordinator_signal_consensus_confidence` (value, `consensus_band`,
`signal_consensus_inputs`) for consensus.

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

**GPS assistive, BLE leads (PERSON-BLE-WINS-OVER-STALE-GPS-1, live as v5.103.90; plan `docs/planning/PLANNING_presence_gps_assistive.md` rev 3).** In the two
`person.state == "home"` arms of `_async_update_data` (Bermuda-sensor-but-no-room, and no Bermuda
sensor), a GPS-led HA `home` is overruled when ALL hold (`_ble_overrules_gps_home`):
- switch **BLE Leads Home/Away** on (`PresenceBleLeadsEnabledSwitch`, `_PresenceKillSwitchBase`, backing
  `PresenceCoordinator._ble_leads_enabled`, default ON; OFF = pre-change behaviour, byte-identical);
- fleet armed: Bermuda's Active Proxy Count (resolved by registry unique_id
  `BERMUDA_GLOBAL_ACTIVE_PROXY_COUNT`, never by name) has read ≥ the fleet floor F
  continuously for ≥ `BLE_LEADS_ARM_S` (360 s), measured from the later of process start and the last
  below-floor / unknown / unavailable reading (`const.py`, rung 1).
  **Fleet floor = fraction of the remembered fleet (branch `fix/ble-grace-fleet-fraction`, deployed (in v5.108.1, live 2026-11-10);
  plan `docs/planning/PLANNING_ble_rearm_and_fleet_fraction.md` rev 2 D2):** F =
  max(`BLE_LEADS_ABS_MIN_PROXIES` 3, ceil(`BLE_LEADS_FLEET_FRACTION` 0.5 × R)), R = the max of a ring of
  (local date, max Bermuda Total Proxy Count that day) over the last `BLE_LEADS_FLEET_MEMORY_DAYS` (7)
  local days (`person_coordinator._update_fleet_floor`, total resolved by unique_id
  `BERMUDA_GLOBAL_PROXY_COUNT`; non-numeric totals never touch the ring; date-pruned per tick, so slots
  from before an outage age out). The total shrinks with an outage, which is why R is remembered. The
  ring persists in Store `universal_room_automation.ble_fleet_memory` (delayed save 60 s, only when a
  slot changes), restored by `async_load_fleet_memory` in `__init__._async_start_person_coordinator`
  between construction and the first refresh. **Cold memory → legacy 30** (`BLE_LEADS_MIN_ACTIVE_PROXIES`):
  until the ring holds a slot from a completed prior local day AND the total entity resolves (first
  deploy, store missing / corrupt, total entity missing, only today's slot), so a restart mid-outage
  cannot arm on a shrunken same-day total. F is cached per tick in `_effective_floor`; the tick and the
  edge listener both compare against it. This house: R = 62 → F = 31 (D2.0: no active reading in
  [30, 31) in 7 days, so identical to 30 here). INFO log `BLE leads: fleet floor %d (...)` on change. `_fleet_healthy_since` starts None
  (boot latch). An `async_track_state_change_event` listener on the proxy sensor catches a ~60 s dip
  between 30 s ticks; the tick also re-reads the state. The listener registers on the first tick the
  entity resolves (late Bermuda load) and is released by `entry.async_on_unload` and by
  `async_teardown()` called in `async_unload_entry` just before the `person_coordinator` pop. Proxy
  entity missing → rule off (non-Bermuda installs unchanged);
- WiFi axis `MISSING` / `unavailable` (WiFi `home` is a witness; row 4 `not_home` is unchanged);
- every `bluetooth_le` tracker in the person's `device_trackers` reads exactly `not_home`, with ≥ 1 such
  tracker (`_own_ble_trackers_all_not_home`; unavailable / unknown / home on any one → no overrule).
The overrule runs the shared S3 away arm (`_apply_s3_away_arm`: ACTIVE + `away`, LOST-since stamps)
but arms `_person_was_away` only after the overrule has held ≥ 15 min (`_min_away_minutes`, the LOST
path's pre-arrival guard), so a short BLE dropout at home fires no pre-arrival; a return after a real
absence does (consequence replay §3.7) and stamps the existing row-14 reason
`away_ble_silent_only` at `BLE_SILENT_ONLY_AWAY_CONFIDENCE` (0.82). No new status / reason /
confidence; `tracker_sources.gps == "home"` shows GPS was overruled. Overruled persons are collected
in a local and assigned once per tick to `_gps_home_overruled` (a frozenset; kept on UpdateFailed), the
only state `effective_person_state` consults (§1 table). GPS still hastens away (GPS `away` rows
unchanged) and still holds home when BLE has no opinion or the fleet is unproven. Residuals (plan §9):
non-Bermuda installs get no rule; a partial outage keeping ≥ F proxies but blinding every scanner near
one resident can mark them away; the first 6 min after a restart / proxy drop keep today's behaviour; an
app user whose BLE stays `not_home` > 360 s after a restart reads away until re-heard (0 of 14 measured).

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
same IRK (operator), so it duplicates the BLE axis harmlessly.
**Freshest-GPS-wins (PERSON-GPS-ANY-HOME-WINS-1, branch `fix/person-gps-freshest-wins`, NOT
deployed; plan `docs/planning/PLANNING_person_gps_freshest_wins.md`):** the GPS axis is the real
reading (`home` / away) of the GPS tracker with the newest `last_updated`; unknown/unavailable never
beats a real reading; ties and undated trackers keep list order. Same rule as HA's own `person`
entity (`person/__init__.py` `_update_state`). Any-home-wins was rejected (a left-at-home device
would hold a person home). Kill switch `PERSON_GPS_FRESHEST_WINS_ENABLED` (rung 1). Scope: in the
no-room / no-Bermuda branches location comes from `person.<x>.state`, not this axis; the axis sets
`tracker_sources`, `tracking_reason` and `confidence` (diagnostic). WiFi axis is still last-wins.

**All three AWAY branches already need residents' phones/BLE gone** (2026-10-18 verify): nobody-home
via `census_count` (includes BLE ids), α via `all_tracked_persons_away`, β via the trusted-or-lost
denominator plus `census_count == 0`. A resident Bermuda resolved within 300 s but not this tick is
stamped STALE and was EXCLUDED from the denominator instead of counting as home. **Sleep-mask cycle D2 (branch, deployed (in v5.108.1, live 2026-11-10)):**
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
**Own area ignored (branch `fix/scanner-areas-own-area`, deployed (in v5.108.1, live 2026-11-10), 2026-10-26):** HA's
`AreaSelectorConfig` has no exclude option (entity/device/multiple only), so both room flows strip
the room's own `CONF_AREA_ID` from the submitted list (`config_flow.strip_own_area`; the options
form default excludes it too), and `_build_scanner_room_map` drops it before deciding Tier-1 direct
status and the Tier-2 map. Before this, listing the own area (12 live rooms, cleaned 2026-10-26)
silently demoted the room off `_direct_ble_rooms`.

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

**Zone tier (presence `ZonePresenceTracker`) — per-sensor rule (sleep-mask cycle Rev 3, branch `feature/house-state-sleep-mask-ble-memory`, deployed (in v5.108.1, live 2026-11-10); switch `const.ZONE_OCCUPANCY_PER_ENTITY_ENABLED`, rung 1, default True):**
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
- **Paused rooms (ROOM-OVERRIDE-SWITCH-FORGOTTEN-1, built 2026-10-19 on `fix/paused-room-lights-fans`, deployed (in v5.108.1, live 2026-11-10)):** the Automation switch (and Manual Mode ON, which counts as paused — `coordinator._is_automation_enabled`) now also gate the HVAC zone vacancy sweep (lights, night lights, fans), HVAC comfort fans (`FanController.update`, level release of tracking, no write), HVAC sleep-onset fan ON, pre-arrival fans ON and OFF, and the fan-recheck arm (veto `room_paused` in `_evaluate_eligibility` + `_still_armed_eligible`). One predicate: `const.room_automation_paused(room_coord)` (no coordinator / no method / exception → not paused; missing switch → enabled; a switch reading `unavailable` / `unknown` → PAUSED, the room tier's pre-existing semantics, `coordinator.py:3179`). The room-tier `_delayed_exit_verify` retry re-reads the switch after its 3 s delay (`skipped_paused`). NOT gated: the recheck restore discharge, the smoke/CO safety stop, `turn_off_all_managed`; covers, AI / house-state rules and humidity venting are unchanged by ruling (operator 2026-10-18: "Blinds down, house state, venting are fine"). Fans URA lit before the pause stay on until unpause, and on unpause are adopted under a manual-ON hold (up to one hold, review B-L2); the zone sweep does not catch up after an unpause (plan §5). Occupancy consequences: see §6 item 3 (D2 backstop, and the lost recheck VACATED release).
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

### 4.6 BLE chain hold and the absence grace

BLE extends a room's occupancy but never creates it (BLE-WARM-CREATE-1): the BLE block in
`coordinator._async_update_data` (`# === v3.8.8: BLE/Bermuda extends room occupancy ===`) admits a
BLE-reported person only while the chain is unbroken (`_last_occupied_state`, previous tick) and
`BLE_CHAIN_HOLD_ENABLED`. `_ble_only_hold_since` marks a hold sustained by BLE alone (seeded on the
first BLE-only admit, cleared on any body fire, camera admit, D2 demotion, true vacancy, Override
Vacant, skip-first vacant sync, fan-recheck release); the per-room hold cap
(`_ble_hold_cap_exceeded`, bathroom/closet default on, 2 h) measures from it and owns the cap NM.

**Absence grace (BLE-LOCATION-QUALITY-1 D1, branch `fix/ble-grace-fleet-fraction`, deployed (in v5.108.1, live 2026-11-10);
plan `docs/planning/PLANNING_ble_rearm_and_fleet_fraction.md` rev 2):** when no body signal fired, the
failsafe has not latched and `get_persons_in_room` is empty, `_ble_absence_grace_applies` keeps the room
occupied (source `"ble"`, `ble_persons` `[]`, diagnostic key `ble_absence_grace: True`, absent on every
other tick) iff the chain is unbroken, `_ble_only_hold_since` is set, the cap is not exceeded (no NM from
this branch), and either an open grace (`_ble_absent_since`) is younger than `BLE_ABSENCE_GRACE_S` (90 s,
rung 1, 0 = off) or no grace has been spent in this episode (`_ble_grace_used`). ONE grace per BLE-only
episode: a present read closes an open grace but does not reset `_ble_grace_used`; the second absent
stretch in the same episode exits. Both fields are cleared together with `_ble_only_hold_since` at all
seven episode-end sites. It never touches the anchor, `_became_occupied_time` or `_last_motion_time`, so
the exit row (written up to 90 s later on a real BLE-only exit) keeps its `duration` meaning; a blip
shorter than the window writes no exit/entry pair. Not persisted. Measured (D1.0, 7 days): 36 BLE-held
exits, 84 % of short returns ≤ 81 s; replay: 2 of 36 held ≥ 30 min (both person read in-room every
tick). The K-tick re-arm (rescues 10-29 06:34) is parked (plan §7).

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
   **Room-type scope (JAYA-FAN-STILL-PHANTOM-1, 2026-10-18):** bedroom + media_room
   (`HIGH_STILL_RISK_ROOM_TYPES`) are refused ONLY across `FAN_TRUST_STATES`
   {home_night, sleep, waking}, veto `sleep_state` (`_evaluate_eligibility` and the
   arm-delay twin `_still_armed_eligible`). The old all-day `high_still_risk` veto
   (Tier-1 L2 path + Tier-0/2 path) was deleted; by day these rooms run the same
   L1/L2/L3/sensors-only ladder as any room. Media is in the sleep scope for still-sleeper
   protection, not the v4.7.13 HVAC keep-on contract (bedroom-only in `hvac_fans`).
   The room-type window factor (bedroom/media x2) is unchanged.
   **L1 includes scanner-area rooms (same date):** the `ble_l1` veto and mid-flight L1 cancel
   use `_l1_persons`: persons in this room OR in any URA room whose area_id is in this
   room's `CONF_SCANNER_AREAS` (Jaya Bedroom borrows `jaya_bathroom`; her phone resolves
   to the Jaya Bathroom room and adjacency is one-directional, so L2 never saw it).
   This recheck L1 (scanner-area inclusive) DELIBERATELY differs from room-level
   `ble_persons` (exact resolved-location match) — do not "align" them. A bedroom/media
   room ARMED or PAUSED when the house enters home_night/sleep/waking is cancelled as
   OCCUPIED_CONFIRMED (fan restored ON, reason `sleep_state`; review B-1).
   **Paused rooms (branch `fix/paused-room-lights-fans`, deployed (in v5.108.1, live 2026-11-10)):** a room whose
   Automation switch is off (or Manual Mode on) is vetoed `room_paused` right after
   `fan_control_off`, and an ARMED room disarms in `_still_armed_eligible`. A recheck already
   PAUSED is not cut short — its restore is a discharge and still runs. **D2 backstop
   (operator-accepted 2026-10-19):** `is_recheck_eligible` reads the same ladder, so a paused
   room is recheck-ineligible and the D2 defer (`coordinator.py` FAN-RECHECK-D2-DEADLOCK-1
   block) no longer defers; a paused radar-sole room with a running fan can be demoted to vacant
   by D2 (same as Fan-Mode-Off rooms), which feeds `hvac_occupied`. Pinned by
   `test_mmwave_fan_demotion.py::test_paused_room_d2_backstop_not_deferred`.
   **Second consequence (review B-M1, operator-accepted by the same ruling):** a paused room loses the fan recheck's VACATED release (the `room_paused` veto means no probe), so in a paused room without a fan-immune witness (Media, Guest Bedroom 1, Guest Bedroom 2 today: MS600 radar-derived motion bits only, D2 fails closed) a running fan can hold the room, and so its zone, occupied until the 4 h stuck-sensor rule or the P24 max-occupancy failsafe fires. This is the opposite direction to the D2 backstop (it holds rather than retreats). Accepted consequence of the operator ruling that a probe must not turn a person's fan off (review B-M1, 2026-10-19).
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

- **Guest latch** (v5.16.0 fix; corrected 2026-11-07, see §10 #29). There is NO GUEST → SLEEP
  edge: `VALID_TRANSITIONS[GUEST]` = {HOME_DAY, HOME_EVENING, HOME_NIGHT, AWAY}
  (`house_state.py:116-121`) and `can_transition` rejects targets outside the table
  (`house_state.py:219-221`). What v5.16.0 fixed is the EXIT: the GUEST-exit check runs before the
  sleep-hours branch (`presence.py:1399-1401`), so a guest whose gate has cleared goes
  GUEST → HOME_NIGHT, then SLEEP on a later tick (`README_v5.16.0.md:12-14`). While the guest
  gate stays armed, the sleep branch's SLEEP proposal (`presence.py:1404-1408`) is rejected every
  tick and the house holds GUEST all night. Consumers keyed on SLEEP do not fire on such nights.
  The garage lockout handles it itself (operator Q-G1 option (a), 2026-11-07; branch
  `feature/sc-garage-lockout-phase1`, deployed (in v5.108.1, live 2026-11-10)): it engages on GUEST inside the CM sleep
  window behind its own toggle, so it does NOT depend on a GUEST → SLEEP edge. See memory
  `project_presence_guest_latch_and_veto_gap`.
  **Night yield (GUEST-MODE-SPLIT-VISITORS-1, branch `feature/guest-mode-split`, deployed (in v5.108.1, live 2026-11-10)):**
  with the stay rule on, the GUEST hold is the stay latch AND NOT a house sleep hour
  (`_compose_guest_gate`, `sleep_hour` = `StateInferenceEngine._is_sleep_hour(local hour)`). At
  `sleep_start_hour` `infer()` proposes GUEST → HOME_NIGHT; the S9 guest-exit persistence holds it
  `_guest_persistence_seconds` (300 s), so the exit lands on the first tick ≥ sleep_start + 300 s,
  then SLEEP after the HOME_NIGHT dwell (120 s). Morning: SLEEP → WAKING → HOME_DAY, then the HOME_*
  entry branch returns GUEST while the latch is on (pinned in
  `test_guest_split_gate.py::test_night_yield_exits_to_home_night` / `::test_morning_reentry`). No
  state-machine edge was added; #29 stays true. The 30-min gate no longer holds GUEST overnight.
  **Garage lockout across the yield (INV-LOCK-1, rev 5, build review B-M1):** the guest-night clock
  locks at `sleep_start_hour` (house still GUEST for the S9 300 s). The yield's GUEST → HOME_NIGHT
  edge inside the sleep window while `reason == guest_night` no longer releases:
  `security_lock_regime.on_house_state_changed` records `guest_yield_hold` and keeps the reason; the
  later SLEEP edge is a no-op write on locked entities. WAKING / HOME_DAY / HOME_EVENING / ARRIVING /
  resident arrival / the backstop release as before. A manual override GUEST → HOME_NIGHT in the
  window is held too (accepted, plan R26). Pinned by `test_sc_garage_lockout.py`
  `::test_lock_once_at_guest_clock_no_unlock_on_yield` / `::test_lock_held_if_home_night_until_morning`.
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

- **PREDICT-MODEL-DWELL-MIGRATION-1 + PREDICT-SCORER-BASELINE-SKILL-1** (built 2026-10-21, branch `feature/predict-dwell-migration`, deployed (in v5.108.1, live 2026-11-10); plan `docs/planning/PLANNING_predict_dwell_migration.md`). Room forecast / pattern sensors read the dwell model (state = usual share for this hour; `+1h` / `+4h` blend the last scored hour's occupied fraction at weights `FORECAST_PERSISTENCE_WEIGHT_1H` 0.5 / `_4H` 0.25; `last_hour_fraction` is null after a restart until the producer has scored an hour). Hourly `dwell_share` rows (§1 table). `sensor.<person>_likely_next_room` predicts from the person's current room (`person_coordinator` `location`) via `PatternLearner.predict_next_room` first (`NEXT_ROOM_CURRENT_ROOM_PRIMARY`); the next-room scorer (`transitions._score_prediction`) writes a row only when the cached prediction's `current_room` equals the transition's `from_room` (both are person_coordinator's resolved room string, so the compare is exact), and counts skips per person (`scored_since_start`, `skipped_room_mismatch_since_start`, `skip_ratio`, `skip_ratio_ok` on `*_next_room_accuracy`; evidence bound `NEXT_ROOM_MAX_SKIP_RATIO` 0.30). The accuracy sensors and the Optimization next-room finding now report skill over always guessing each person's usual room on the same rows (`prediction_skill.py`); the Optimization clause fires on skill ≤ `OPTIMIZER_PREDICTION_ACCURACY_MIN_SKILL_PCT` (0) instead of the old absolute 35% floor. `prediction_results` prune covers all types at `PREDICTION_RESULTS_RETENTION_DAYS` (45). `energy_forecast` still reads the Bayesian occupancy model (operator Q1; switch off).

- **BAYES-OCCUPANCY-ANOMALY-NEVER-EVALUATES-1** (built 2026-10-21, branch `feat/occupancy-dwell-anomaly`, deployed (in v5.108.1, live 2026-11-10), README_v5.103.83). `binary_sensor.<room>_occupancy_anomaly` never evaluated (logic in `async_update`, never called on a coordinator entity) and its Bayesian arrival model scored long-dwell rooms as rare (Study A 0.004). Now it evaluates in `_handle_coordinator_update` against the room dwell model (§1 table). On only when: occupied; cell share < `OCC_ANOMALY_SHARE_THRESHOLD` (0.02); cell samples span ≥ `OCC_ANOMALY_MIN_CELL_DAYS` (4) distinct days with ≥ `OCC_ANOMALY_MIN_CELL_SAMPLES` (24) samples; occupied ≥ `OCC_ANOMALY_DEBOUNCE_S` (1800 s; 900 failed the G1 replay); house not GUEST; model refreshed. Rising edge: `SIGNAL_OCCUPANCY_ANOMALY` + one `anomaly_log` row `occupancy.dwell_anomaly`, gated by startup grace, per-room cooldown and **presence** observation mode (the room coordinator has no `_observation_mode`; the old check was always False). No NM on any path. It learns phantom holds as "usual" (Study A ZK hold, Jaya LD2410 fan loop) and shows a phantom at a new hour as an anomaly: accepted, display only. The day-based gate replaced a 200-sample gate that weekend cells (≤ 192 samples in 56 days) could never pass. Knobs are tuned from the post-deploy D0 replay (`scripts/probes/occupancy_dwell_backtest.py`); HA's recorder keeps only 7 days, so the replay covers 7 days while training uses `environmental_data` (back to 2025-11-19). Side fixes in the same branch: `get_occupancy_time_today` / `get_occupancy_percentage` / `get_uncomfortable_minutes_today` (entry_id key, local-day window, entry/exit pairing), and the four room "today" sensors now refresh (throttled, quantized) instead of never. `bayesian_predictor.get_anomaly_score` has no production reader now (DELETE candidate after live validation).
- **GUEST-MODE-SPLIT-VISITORS-1** (built 2026-11-09, branch `feature/guest-mode-split`, v5.108.0, deployed (in v5.108.1, live 2026-11-10); plan `docs/planning/PLANNING_guest_mode_split_2026_11.md` rev 5 (one night + a same-room day; INV-LOCK-1); README `docs/readmes/README_v5.108.0.md`). D1 `visitors_present` (§1 table); D2 night-stay producer + D3 composition (§2 step 3, §7 night yield); D4 `guest_stay_long` trip-wire. WiFi is read nowhere (operator decision). Residuals: no GUEST on arrival day (parked); a resident who spends the day and one night in GB2 enters GUEST (GB2 has no scanner, so BLE cannot subtract them; knob `GUEST_STAY_ENTRY_NIGHTS` 2); a guest room un-flagged mid-stay drops out of the next walk (re-walked at once); a never-closed `person_visits` row subtracts to the span end; a phantom guest-room hold (fan, stuck radar; GB1/GB2 have no fan-immune witness, §6 item 3) counts as a guest night and is paged by D4 only after 28 days. Operator checkpoint before deploy (house state).
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

- **Rev 3 D4d trip-wire `zone_hold_all_away` (branch, deployed (in v5.108.1, live 2026-11-10)).**
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
   orchestrator re-read `presence.py:1169-1180`; the predicate is at `:1227-1232` as of 2026-10-24). Path α is trackers-away + unidentified 0 + face 0 +
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

23. **"The iPad's stale GPS overwrote the phone and so drove URA's AWAY decisions."** OVERSTATED
   (2026-10-20, freshest-GPS plan producer check). URA's last-wins GPS axis feeds only
   `tracker_sources` / `tracking_reason` / `confidence`; location in the no-room / no-Bermuda branches
   comes from `person.<x>.state` (`person_coordinator.py` S2/S3/S5 wrapper). HA's person entity already
   picks the freshest GPS, so the iPad could move AWAY only when its fix was the freshest one HA saw.

24. **"BLE-only away at 0.82 cannot flip the house because path α needs 0.9"** (old comment at
   `person_coordinator.py` row 14, and `const.py` `BLE_SILENT_ONLY_AWAY_CONFIDENCE` comment). WRONG
   (GPS-assistive plan, 2026-10-24): path α reads `location` only, never confidence
   (`presence.py` `all_tracked_persons_away`, ~:6395). The row-14 comment is corrected; the 0.82 value is
   kept as an existing label, not a gate.

25. **"Fleet liveness gates BLE silence for everyone."** INCOMPLETE (2026-10-24): `_ble_fleet_live`
   (`person_coordinator.py`) proves liveness only through some person's Bermuda room fix on the previous
   tick, so it is False for the last person out. The GPS-assistive rule uses Bermuda's Active Proxy Count
   as its fleet guard instead (§3).

26. **§2 step 0 "census_count includes BLE-located residents."** INCOMPLETE (2026-10-24): the census
   BLE list (`camera_census._get_ble_persons`) counts any person_coordinator `location` not
   away/unknown, including a GPS-forced `home` (`camera_census.py` ~:2683-2685). A frozen GPS therefore
   blocked nobody-home as well as α.

27. **"A dead BLE fleet makes the trackers unavailable."** WRONG (GPS-assistive plan rev 1, refuted by
   plan review F1): private_ble and Bermuda trackers read `not_home` while still available when the
   scanners go deaf; they go unavailable only if the integration itself fails. The fleet signal is
   Bermuda's Active Proxy Count (§3).

28. **"The census stale-face latch should stay on raw `person.state`; routing it through the BLE
   overrule mostly adds false GUEST for a resident home without a phone."** SUPERSEDED (2026-10-24,
   CENSUS-BLE-OVER-FACE-1). The replay's "Oji home without BLE" premise rested on Frigate face labels
   the operator refuted (Jaya mislabelled as Oji; Oji abroad from ~08:42 10-24). D0
   (`PLANNING_census_ble_over_face.md` §4.3) found every face-only sample in the confirmed-away window
   wrong, and measured the real cost (4 GUEST-eligible runs, ~33 min, on 10-24, third body in one camera
   frame), which the operator accepted (option A). The latch now follows BLE Leads (§1 table).

29. **"GUEST → SLEEP transition had been missing; the latch now survives the night (v5.16.0)."**
   WRONG (2026-11-07, SC garage lockout plan review 1 M2, re-verified by the planner). The code has
   no GUEST → SLEEP edge (`house_state.py:116-121`; enforced at `:219-221`). v5.16.0 moved the
   GUEST exit above the sleep branch (`presence.py:1399-1401`), so a CLEARED guest reaches SLEEP via
   HOME_NIGHT; an ARMED guest gate holds GUEST overnight. §7 corrected.

30. **"`_guest_gate_armed()` pre-evaluates GUEST (threshold / confidence / persistence)"** (§2 step 3,
   from v4.6.2.2). STALE since GUEST-CENSUS D2 (2026-08-16): Path A (`_guest_gate_armed`) arms
   nothing; `guest_armed` was the 30-min room gate, and with GUEST-MODE-SPLIT-VISITORS-1 the stay
   latch (`_compose_guest_gate`). Path A now feeds only `guest_reason`, confidence 0.95 and
   `visitors_present` `legs.cam`.

31. **"`guest_reason` `guest_room:<room>` is a GUEST reason."** WRONG once the night-stay rule is on
   (GUEST-MODE-SPLIT-VISITORS-1): it means a visitor has been in a guest room ≥ 30 min. The GUEST
   reason during a stay is `night_stay:<rooms>`. With the rule off (kill switch) the old meaning
   holds.

32. **"`person_visits` times are naive LOCAL"** (docstring of `Database.get_closed_person_visits`).
   INCOMPLETE (2026-11-09, plan §10 item 1): the writer uses `datetime.now()`
   (`Database.log_person_entry`), i.e. naive PROCESS-local time: UTC on this HAOS host (live rows read
   07:16 while local was 02:38 CST), local only where the process TZ is local. The night-stay
   producer converts with `datetime.fromtimestamp(x.timestamp())` / `naive.timestamp()` (exact on any
   host; pinned by `test_guest_stay_producer.py::test_person_visits_clock_utc_host` /
   `::test_person_visits_clock_local_host`). The dwell model's `usual_people` (display) still trusts
   the docstring; card `PERSON-VISITS-CLOCK-PROCESS-LOCAL-1`.

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
| **FAN_TRUST_STATES scope** | `hvac_const.FAN_TRUST_STATES`, consulted in `presence_fan_recheck._evaluate_eligibility` (sleep_state veto) and `_still_armed_eligible` | Bedroom + media_room (`HIGH_STILL_RISK_ROOM_TYPES`) sleep veto since 2026-10-18 (was bedroom-only, plus an all-day `high_still_risk` veto now deleted); other rooms proceed through sleep. C1a inherits this scope automatically. |

---

