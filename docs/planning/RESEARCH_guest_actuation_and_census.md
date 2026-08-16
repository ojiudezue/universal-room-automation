# RESEARCH: Guest Actuation + Census — authoritative map and gap-diff

**Date:** 2026-08-16
**Type:** Context-wide read-only research (rooms + zones + house + cross-cutting). No code changes, no cards.
**Frame:** the operator's three problems, quoted verbatim:

> - **Problem A: get a good count that works.**
> - **Problem B: if it's durable, think about activating guest mode and under what conditions.**
> - **Problem C: activate guest mode if high confidence AND sustained.**
>
> Design instinct: *"Guest should have a higher bar. Guest rooms can be indicated and guest mode comes from their occupancy."*

**Headline:** recent work (v5.76–v5.78 + Frigate F2 tuning) moved **Problem A only**. Problems B and C are
untouched by any shipped cycle. The house is in `guest` right now on a count of **10 = 4 identified + 6
unidentified** with one real guest — and the mechanism is identified in §1.6 below: the enhanced census path
is **additive** where the raw path was **subtractive**, and both of its anti-double-count defenses are
returning zero.

---

## 0. Live snapshot (2026-08-16 ~18:39 CT)

### 0.1 Census

| Entity | Value |
|---|---|
| `sensor.universal_room_automation_persons_in_house` | **10** |
| ↳ `identified_count` | 4 |
| ↳ `unidentified_count` | **6** |
| ↳ `confidence` / `source_agreement` | `high` / `both_agree` |
| ↳ `frigate_count` / `unifi_count` | 6 / 3 |
| ↳ `camera_unrecognized` | **6** |
| ↳ `wifi_guest_floor` | 6 (diagnostics-only — see §1.4) |
| ↳ `face_recognized_persons` | **`[]`** |
| ↳ `ble_cancelled_count` | **0** |
| ↳ `area_contributions` | **`{}`** |
| ↳ `raw_pre_dedup_sum` | 9 |
| ↳ `peak_held` / `stuck_cameras` | false / `[]` |
| `sensor.universal_room_automation_identified_persons_in_house` | 4 — `["Ezinne","Jaya","Oji Udezue","Ziri"]` |
| ↳ `ble_confirmed` | all 4 |
| ↳ `face_confirmed` | all 4 |
| `sensor.universal_room_automation_persons_on_property_exterior` | 0 (`medium`, `single_source`) |
| `binary_sensor.universal_room_automation_census_mismatch` | **on** — camera 10 vs ble 4, since 17:47 |
| `sensor.universal_room_automation_house_state` | **`guest`**, since 13:38 CT, `is_overridden: false` |

Two internal contradictions are visible in that table and both are load-bearing:

1. `face_recognized_persons: []` but `face_confirmed: [4 names]`. These are two *different* accessors —
   `_get_face_recognized_persons` (no freshness gate, feeds `face_persons`) vs
   `_get_face_recognized_person_names` (30-min freshness + `person.<slug> != not_home` cross-check, feeds the
   enhanced census). Faces **are** being matched; they are all failing the freshness/cross-check gate.
2. `camera_unrecognized (6) == frigate_count (6)` **exactly**. That is the signature of *zero* cancellation:
   not one camera got the fresh-face `−1`, and not one area got a BLE subtraction.

### 0.2 Live config

Coordinator-manager / integration entry:

```
census_ble_cancel_enabled: True      census_cross_validation: True
census_divergence_downgrade: True    enhanced_census: True
census_hold_interior: 3.0 (min)      census_hold_exterior: 5.0 (min)
guest_vlan_ssid: "Revel"
guest_mode_persistence_seconds: 300.0
guest_mode_require_confidence: "medium"
```

Rooms carrying `room_is_guest_room: True` — **exactly three**, all at the 30-min default:

| Room | `room_is_guest_room` | `room_guest_occupancy_threshold_min` |
|---|---|---|
| Guest Bedroom 1 | **True** | 30.0 |
| Upstairs Guestroom | **True** | 30.0 |
| Down Guest Bathroom | **True** | 30.0 |
| Jaya Bedroom (Bedroom 4), Laundry, Master Bathroom, Master Bath Toilet | False | 30.0 (inert) |

So the operator's instinct — *"guest rooms can be indicated"* — is **already configured on the live house**.
The indication exists. What it feeds is the problem (§3.2).

---

## 1. Every producer of the count

Source: `custom_components/universal_room_automation/camera_census.py` (3171 lines).

### 1.1 Tick structure

`PersonCensus.async_update_census` `:1084` → `_async_update_census_locked` `:1097` (asyncio lock). Per tick:

1. `_get_ble_persons()` `:1937` — persons from `person_coordinator.data` whose `location` ∉ {away, unknown, ""}.
   **No staleness filter here** (contrast `_ble_home_by_area`, §1.3).
2. `_watchdog_stuck_cameras(now)` `:1160` — fail-open.
3. `_calculate_house_census()` `:1221` — the **raw** path.
4. `_calculate_property_census()` `:1502` — exterior.
5. If `_is_enhanced_census_enabled()` `:2451` (**default True, live True**):
   `_apply_enhanced_house_census` `:3075` **overwrites** the raw house result; `_apply_enhanced_property_census` `:3139`.
6. `total_on_property = house.total_persons + property.total_persons` `:1183`.
7. `async_dispatcher_send(SIGNAL_CENSUS_UPDATED, …)` `:1218-1245` — keys `interior_count`, `identified_count`,
   `unidentified_count`, `property_count`, `total_on_property`, `confidence`, `source_agreement`,
   `face_recognized_count` (the last added by v5.78.0 Gap-A D8).
8. DB write only when `startup_age >= 300s` and every 4th cycle `:1253-1262`.

Cadence: `SCAN_INTERVAL_CENSUS = 30s` (`const.py:1390`), wired `__init__.py:2233-2243`; event-driven triggers
debounced by `CENSUS_EVENT_DEBOUNCE_SECONDS = 30` (`const.py:2708`), `__init__.py:2258-2296`.

### 1.2 The raw path (subtractive) — `_cross_correlate_persons` `:1746`

Per-camera contributions gathered at `:1256-1332`: Frigate numeric via `person_count_sensor` → `_get_sensor_int`
`:1287`; stuck-discounted cameras `continue` before contributing `:1293-1307`; Frigate binary-only → 1
`:1313-1318`; non-Frigate binary (UniFi/Reolink/Dahua) → 1 each `:1320-1328`. Collapse via `_dedup_by_area`
`:1894` (**per-area MAX, summed across areas; null-area cameras summed individually**), `:1331-1332`.
Observability deposited at `:1355-1356` (`_last_area_contributions`, `_last_raw_pre_dedup_sum`), cleared on the
cross-validation-disabled path `:1451-1452`.

Fusion: `_cross_validate_platforms` `:1586`, corroboration bundle = fresh faces ∪ BLE persons ∪ any-zone-occupied
`:1385-1396`; `_apply_divergence_downgrade` `:1646`.

**Derivation, `:1770-1777`:**

```python
known        = face_ids | ble_ids
identified   = len(known)
unidentified = max(0, camera_total - identified)     # SUBTRACTIVE
total        = max(camera_total, identified)         # MAX, not sum
```

This form is **structurally incapable of double-counting a resident**: every identified person is removed from
the camera total before it becomes "unidentified", and the total is a max, not a sum. Confidence ladder `:1780-1795`.

### 1.3 The enhanced path (additive) — `_apply_enhanced_house_census` `:3075`

This is what actually ships (`enhanced_census: True` live). It **discards** `raw_result.total_persons` and keeps
only `confidence`/`source_agreement`/`frigate_count`/`unifi_count`/`degraded_mode`/`active_platforms` `:3115-3121`.

```python
camera_unrecognized = self._get_unrecognized_camera_count()          # :3090
wifi_guests         = self._get_wifi_guest_count(now)                # :3091  (diagnostics only)
face_recognized     = self._get_face_recognized_person_names(now)    # :3092
identified_count    = len(set(ble_persons) | set(face_recognized))   # :3095-3096
unidentified_raw    = camera_unrecognized                            # :3102
held_unidentified, peak_held, peak_age = self._apply_hold_decay(...) # :3105
total = identified_count + held_unidentified                         # :3109  ← ADDITIVE
```

**This is the crux of Problem A.** The subtraction that protected the raw path is gone. The enhanced path's only
protections against counting a resident twice are pushed *inside* `_get_unrecognized_camera_count`:

**`_get_unrecognized_camera_count` `:2670` — four steps:**

- **Step 1** `:2708-2766` — per-Frigate-camera raw contribution. If
  `sensor.<base>_last_recognized_face` is fresh (age ≤ `CENSUS_FACE_RECOGNITION_WINDOW_SECONDS` = 1800s,
  `:2740-2754`): `raw_contribution = max(0, count - 1)` `:2760`. Else the **full count** `:2763`.
  Cameras whose binary_sensor id doesn't end `_person_occupancy` short-circuit to full count `:2730-2733`.
- **Step 2** `:2768-2779` — group by `CameraInfo.area_id`, per-area MAX → `area_raw_max`; **null-`area_id`
  cameras go to `unassigned_raw`**.
- **Step 3** `:2798-2816` — BLE cancel, gated live per tick by `_get_ble_cancel_enabled()` `:2459`:
  `correction = min(area_raw_max[aid], ble_by_area[aid])`, accumulating `cancelled_total`, INFO-logging
  `"BLE-cancel: area=… raw_max=… ble_here=… correction=…"` `:2810-2813`.
  Invariants I1 (an area with no resident BLE-here is untouched) / I2 (`min` bound) / I3 (monotone-reducing)
  documented `:2781-2797`. **Null-area contributions are NEVER cancelled** `:2787-2790`.
- **Step 4** `:2826` — `sum(area_contributions.values()) + sum(unassigned_raw)`.

`_ble_home_by_area` `:2285` supplies the subtrahend. It excludes: `tracking_status ∈ {STALE, LOST}` `:2347-2350`;
sentinel locations `away`/`unknown`/`home`/`lost` `:2341`; and **drops rooms that don't resolve to a registry
`area_id`** `:2351-2355` (Fix 4 / A-H3 — an unmapped resident must not cancel null-area cameras). Returns `{}`
on any exception or missing `person_coordinator` `:2327-2332`, `:2359-2364` — graceful degradation means
**no cancellation**, i.e. the failure mode is silent over-count.

### 1.4 WiFi guest-VLAN counter — proven diagnostics-only

`_get_wifi_guest_count` `:2828` does full filtering (SSID/`is_guest` match, `NON_GUEST_HOSTNAME_PREFIXES` /
`TABLET_HOSTNAME_PREFIXES` exclusions, person-tracker + device-registry-sibling + MAC exclusion, recency
`WIFI_GUEST_RECENCY_HOURS = 4` — tightened from 24 on 2026-07-26 because it read 1-2 on an empty house,
`const.py:2789-2799`).

Proof it is excluded from the count — docstring `:3081-3087` and inline `:3098-3102`:

> *"Uses camera-only for unidentified count: `unidentified = camera_unrecognized`. WiFi guest count is still
> computed for diagnostics but excluded from the formula (too many false positives from IoT devices)."*

It survives **only** as the attribute `wifi_guest_floor=wifi_guests` `:3125`, surfaced at `sensor.py:3494`.
The live coincidence `wifi_guest_floor == camera_unrecognized == 6` is exactly that — a coincidence; the code
path proves no summation.

### 1.5 Hold / decay / sustain — `_apply_hold_decay` `:2500`

- Hold seconds from `_get_hold_seconds` `:2480` (interior/exterior CONF minutes × 60). Live: interior 3 min, exterior 5 min.
- First observation latches immediately `:2537-2541`.
- **Upward moves, house only** (`sustain_applies = zone == "house"` `:2543`): pending latch, promotes to peak only
  after `CENSUS_PEAK_SUSTAIN_SECONDS = 15` of sustain `:2545-2576` (v5.9.0 D-B). Property latches instantly `:2577-2582`.
- Within hold window → return stored peak, `peak_held=True` `:2598-2601`.
- After hold, house decays **−1 per `CENSUS_DECAY_STEP_SECONDS` = 300s** `:2603-2613`; property drops instantly `:2615-2618`.

Consequence for Problem C: an over-count of 6 takes **~25 minutes** to decay to 1 even after the cameras clear.
The hold/decay machinery makes a phantom *durable*, which is precisely what the guest persistence gate is
looking for. **The existing sustain machinery cannot distinguish "sustained because real" from "sustained
because held."**

### 1.6 The interior/exterior split

There is **no** `is_outdoor` involvement in the census. The split is purely config-list membership:

- **Interior** = `CONF_CAMERA_PERSON_ENTITIES` → `_get_interior_camera_entities` `:1836` → `_get_integration_camera_list` `:1852`.
- **Exterior** = `CONF_EGRESS_CAMERAS` + `CONF_PERIMETER_CAMERAS` → `_calculate_property_census` `:1502-1508`.
  Exterior is 0/1 per camera (no numeric counts) `:1512-1516`; its confidence never exceeds MEDIUM `:1535-1547`.
- **`CONF_ZONE_IS_OUTDOOR`** (`const.py:72`) is consumed by `aggregation.py:4285`, `presence.py:1663-1701`,
  `safety.py:512-543` — and is **never imported by `camera_census.py`**. This is v5.7.0 WS-A Residual-B1,
  still unbuilt; latent-safe only because Patio has no camera person inputs today.
- **Exterior contributions do NOT enter the house census.** Separate `CensusZoneResult`, joining only at
  `total_on_property` `:1183`. Presence consumes `interior_count` only (`presence.py:4310`).
- `ExteriorTrackLinker.set_allowed_cameras` `exterior_track_linker.py:363` exists precisely because interior
  cameras were "opening exterior tracks and poisoning the census" `:367-368`.

### 1.7 Diagnosis of tonight's count: **10 = 4 + 6**

Reading the live attributes against the code above, the chain is fully determined:

1. `_get_face_recognized_person_names` returns `[]` (30-min freshness + `person.<slug> != not_home` cross-check).
   Faces *are* matched — `face_confirmed` shows all 4 — but none survive the gate. So
   `identified_count = |ble_persons ∪ ∅| = 4`, **entirely from BLE**.
2. In Step 1, the per-camera fresh-face `−1` therefore fires on **zero** cameras. Every camera contributes its
   full `person_count`.
3. In Step 3, `ble_cancelled_count = 0` — no area got a subtraction. Given `census_ble_cancel_enabled: True`
   (verified live), the kill switch is not the cause; the cause is `_ble_home_by_area` returning `{}` or
   returning areas that don't intersect `area_raw_max` (open card CENSUS-GHOST-DEDUP-1 — see §5).
4. Result: `camera_unrecognized == frigate_count == 6`. The four residents' own camera detections are sitting
   *inside* the unidentified bucket.
5. `total = 4 + 6 = 10`. The same house on the **raw** formula would read
   `max(6, 4) = 6` total with `max(0, 6−4) = 2` unidentified.

**The additive/subtractive divergence is the single highest-leverage finding in this document.** The raw path's
invariant (a person can be counted once, as identified *or* unidentified, never both) was silently dropped when
the enhanced path became the default, and was replaced by two *best-effort* corrections that both fail open.

### 1.8 Knobs and their rung

**Config/options flow** (live-editable, read per-tick from merged entry data+options; step `camera_census`
`config_flow.py:2884`):

| Key | const | default | Reader |
|---|---|---|---|
| `CONF_ENHANCED_CENSUS` | `const.py:2676` | True | `_is_enhanced_census_enabled` `:2451` |
| `CONF_CENSUS_BLE_CANCEL_ENABLED` | `const.py:2688` | True | `_get_ble_cancel_enabled` `:2459` |
| `CONF_CENSUS_CROSS_VALIDATION` | `const.py:1405` | True | `_is_cross_validation_enabled` `:1824` |
| `CONF_CENSUS_DIVERGENCE_DOWNGRADE` | `const.py:1415` | True | `_is_divergence_downgrade_enabled` `:1726` |
| `CONF_CENSUS_HOLD_INTERIOR` | `const.py:2679` | 3 min | `_get_hold_seconds` `:2480` (1–60) |
| `CONF_CENSUS_HOLD_EXTERIOR` | `const.py:2680` | 5 min | `_get_hold_seconds` `:2480` (1–30) |
| `CONF_GUEST_VLAN_SSID` | `const.py:2714` | "" | `_get_wifi_guest_count` `:2843` |
| `CONF_CAMERA_PERSON_ENTITIES` / `CONF_EGRESS_CAMERAS` / `CONF_PERIMETER_CAMERAS` | — | [] | `:1852` |
| `CONF_STUCK_CAMERA_HOURS` | `const.py:3604` | 3.0 | `:2225` — **read from options but NOT exposed in the config flow** (rung gap) |
| `CONF_STUCK_CAMERA_INTERIOR_TIERS_REQUIRED` | `const.py:3607` | 1 | `:2237` — same rung gap |

**Module constants** (code-change only, per the knob ladder rung 1):
`CENSUS_PEAK_SUSTAIN_SECONDS = 15` (`const.py:2705`, explicitly "no CONF key, no Number entity, no options-flow
field" `:2703-2704`); `CENSUS_DECAY_STEP_SECONDS = 300` (`:2697`); `CENSUS_EVENT_DEBOUNCE_SECONDS = 30` (`:2708`);
**`CENSUS_FACE_RECOGNITION_WINDOW_SECONDS = 1800`** (`:2711`); `WIFI_GUEST_RECENCY_HOURS = 4` (`:2799`);
`SCAN_INTERVAL_CENSUS = 30` (`:1390`); `STUCK_CAMERA_NEVERZERO_HOURS = 6.0` (`:3673`);
`CENSUS_MISMATCH_THRESHOLD = 2` / `CENSUS_MISMATCH_DURATION_MINUTES = 10` (`:2124-2125`);
`CENSUS_USE_NEW_RESOLVER = True` (`camera_resolver.py:102`, census-path fire axe).

**Live entities:** **none.** There is no `number`/`select`/`switch` entity for any census knob. The only
census-adjacent switch is the exterior-track fire axe `switch.py:5760-5783`, which affects only the
`ExteriorTrackLinker` counters, not `PersonCensus`.

### 1.9 Census sensors

| Class:line | entity_id | State | Key attributes |
|---|---|---|---|
| `URAPersonsInHouseSensor` `sensor.py:3456` | `sensor.universal_room_automation_persons_in_house` | `house.total_persons` | `identified_count`, `unidentified_count`, `confidence`, `source_agreement`, `frigate_count`, `unifi_count`, `degraded_mode`, `active_platforms`, `last_updated` `:3481-3490`; enhanced: `wifi_guest_floor`, `camera_unrecognized`, `peak_held`, `peak_age_minutes`, `face_recognized_persons`, `enhanced_census`, `ble_cancelled_count` `:3492-3505`; `area_contributions`, `raw_pre_dedup_sum`, `pending_peak`, `stuck_cameras` `:3507-3529` |
| `URAIdentifiedPersonsInHouseSensor` `:3534` | `…_identified_persons_in_house` | `identified_count` | `person_list`, `ble_confirmed`, `face_confirmed`, `confidence` `:3560-3566` |
| `URAUnidentifiedPersonsInHouseSensor` `:3568` | `…_unidentified_persons_in_house` | `unidentified_count` | **none** |
| `URAPersonsOnPropertySensor` `:3588` | `…_persons_on_property_exterior` | `persons_outside` | `confidence`, `source_agreement`, `peak_held`, `peak_age_minutes` |
| `URATotalPersonsOnPropertySensor` `:3625` | `…_total_persons_on_property` | `total_on_property` | `inside_count`, `outside_count`, `identified_total`, `unidentified_total`, both confidences |
| `URACensusConfidenceSensor` `:3661` | `…_census_confidence` | `house.confidence` | DIAGNOSTIC, **disabled by default** `:3666` |
| `URACensusValidationAgeSensor` `:3696` | `…_census_validation_age` | age seconds | DIAGNOSTIC, disabled by default |
| `PresenceCensusCountSensor` `:5299` | `sensor.ura_presence_coordinator_people_home_census` | `PresenceCoordinator._census_count` `:5337` | — |

**Observability defect noted:** `area_contributions` is read from `census._last_area_contributions`
(`sensor.py:3511`), which is written by `_calculate_house_census` `:1358` — the **raw** path — not by
`_get_unrecognized_camera_count`, which computes its own local `area_contributions` (§1.3 Step 3) and never
publishes it. So on the enhanced path the attribute cannot report the dedup that actually drives the count.
Live `{}` is therefore *partially* an observability artifact and must not be read as proof of area failure —
but `ble_cancelled_count = 0` **is** a genuine signal from the enhanced path and does prove zero cancellation.

---

## 2. Every consumer of the count

Fan-out is via `SIGNAL_CENSUS_UPDATED` (`domain_coordinators/signals.py:18`), which has exactly **two**
subscribers — `presence.py:2567-2575` (trust) and `sensor.py:3433-3446` (display). Everything else reads
`hass.data[DOMAIN]["census"].last_result` directly.

### 2.1 Trust decisions (change actuation or state)

| file:line | Reads | Effect |
|---|---|---|
| `presence.py:4301-4357` | all payload keys → `_census_count`, `_unidentified_count`, `_face_recognized_count`, `_census_confidence` | The ingress; any change schedules `_run_inference("census_update")` |
| `presence.py:1059-1063` | `census_count`, `any_zone_occupied` | "Nobody home" → `AWAY` @ 0.9 |
| `presence.py:1091-1101` | `all_tracked_persons_away`, `unidentified_count`, **`face_recognized_count`** | **path α away-veto.** Post-v5.78.0-D8 the third clause is `face_recognized_count == 0` (was `census_count == 0`). Forces AWAY @ 0.95 |
| `presence.py:1163-1177` | `unidentified_count`, **`census_count`** | **path β** — still gates on raw `census_count == 0`. Deliberately asymmetric vs α (commit `2e76a5a91`: "NOT in scope: path-β symmetric clause") |
| `presence.py:1211-1214` | `census_count > 0 or any_zone_occupied` | `has_people`; false → no transition |
| `presence.py:1241-1243` | `unidentified_count == 0 and not guest_gate_armed` | **GUEST exit** (invariant I-D1, evaluated before the sleep branch) |
| `presence.py:1262-1274` | `guest_gate_armed` | **HOME_* → GUEST** |
| `presence.py:4861-4940` `_guest_gate_armed` | `unidentified_count`, `census_confidence` | **guest activation Path A** — existence + confidence + persistence |
| `presence.py:5687-5695` | `_census_count == 0 and _unidentified_count == 0 and _indoor_clear_debounced` | `sustained_external_empty` — the immediate-engage limb bypassing the LOST grace |
| `presence.py:6004-6014` | `_census_count > 0` | **wake backstop**: SLEEP past `sleep_end_hour + 3` with census > 0 forces WAKING |
| `presence.py:1877-1897` | `unidentified_person_count`, `census_count` | veto oracle H1 — requires **both** zero |
| `presence.py:5080-5093` | `_census_count >= BOOT_SETTLE_MIN_INPUTS` | cold-boot settle release |
| `presence.py:2616-2647` | `census.last_result.house.total_persons`, else the sensor state | **boot seeding** — without it the first inference always infers AWAY |
| `security.py:774-775, 969-1010` | intent `source == "census_update"` | `_handle_census_intent` → **locks all doors**, sets `_active_alert`, fires `SIGNAL_SECURITY_EVENT("unknown_person", high)`, triggers recording. Suppressed under `observation_mode`. **Highest-consequence consumer.** |
| `security.py:264-282`, `:314-315` | `context["census"]["persons_home"]`, `["unknown_present"]` | Entry classification / lockdown gate. **Caveat: `context["census"]` has no writer anywhere in the repo** — readers only at `:251` and `:314`. Effectively dead; always `{}` ⇒ `unknown_present = False` |
| `binary_sensor.py:1769-1773` | `house.total_persons > 0` | **suppresses** the phone-left-behind alarm |
| `coordinator.py:1027-1033` | `census.get_room_identified_persons(room)` | per-room identified persons feed room presence |

### 2.2 Display only

`sensor.py:3412-3715` (all census sensors), `sensor.py:4354-4416` (a **parallel duplicate derivation** of
unidentified from the sensor state minus BLE), `sensor.py:4947-4961` (`census_count`, `face_recognized_count`,
`path_alpha_gate_source` — the v5.78.0 D2c observability), `sensor.py:5300-5337`, `binary_sensor.py:1527-1585`
(`UnexpectedPersonDetected`), `binary_sensor.py:1610-1660` (`CensusMismatch`), `aggregation.py:5927-5995`
(zone guest-count), `presence.py:6429-6451` (anomaly detector, persistence suppressed),
`dashboard-v3/src/components/tabs/Presence.tsx:39,287,342`, `frontend-v3/assets/Presence-*.js`.

### 2.3 Notable NON-consumers

- **HVAC reads census nowhere.** `hvac.py:3544,3572` and `hvac_const.py:817` mention `census_count` **only in
  comments**. HVAC consumes `house_state` (`hvac.py:1849`) — census reaches it strictly transitively.
- **NM reads census nowhere.** `notification_manager.py` has zero census references; census appears only in
  *message text* (`presence.py:5040`). Perimeter contextual severity (`perimeter_alert.py:1566,1589-1607`)
  uses `presence._tracked_persons_count_trusted`, deliberately **not** census.
- `occupancy_substrate.py`: zero references.
- `house_state.py` contains **no census logic at all** — only `HouseState` `:22` and the state machine
  `:108-252`. All inference lives in `presence.py:980-1290`.

**The v5.78.0 "Gap A" change, precisely.** Path α previously gated on `census_count == 0`, but
`census_count = |ble_home ∪ face_recognized| + held_unidentified` — a **forgotten phone at home** keeps a
resident in `ble_home` → census ≥ 1 → the away-veto is permanently blocked. D8 (`2e76a5a91`) replaced the clause
with `face_recognized_count == 0`, plumbed additively via the new payload key, with `int = 0` defaults preserving
byte-identity (`presence.py:1000`, `:4327`). Invariant I-GA: *only camera-provable evidence blocks path α*.
**Residual:** path β `:1166`, veto-oracle H1 `:1881-1891`, and the veto log gate `:5905-5912` all still use raw
`census_count == 0` — only α was closed.

---

## 3. Every path that can ACTIVATE, SUSTAIN, or RELEASE guest mode

### 3.1 The three paths

**Path A — census-unidentified.** `_guest_gate_armed()` `presence.py:4861-4938`. Four short-circuits in order:
kill switch (`_guest_detection_enabled`, `:4882-4884`) → existence (`unidentified_count > 0`, `:4886`) →
confidence (`_confidence_at_least(census_confidence, _guest_require_confidence)`, `:4895-4901`, ranked at
`:4645-4651`, unknown → rank 0) → persistence (`_unidentified_first_seen` elapsed ≥ `_guest_persistence_seconds`,
`:4911-4927`), with a forced re-check timer at N+5s `:4941-4975` so firing doesn't depend on census jitter.
Effective threshold is **`unidentified > 0`** — `CONF_GUEST_MODE_MIN_UNIDENTIFIED` was considered and dropped in
v4.6.2.2. Confidence 0.8.

**Path B — v4.7.2-D5 guest-room sustained occupancy. CONFIRMED BUILT AND LIVE.**
Config `CONF_ROOM_IS_GUEST_ROOM` / `CONF_ROOM_GUEST_OCCUPANCY_THRESHOLD_MIN` (`const.py:386-387`), UI
`config_flow.py:9347-9356` (default False / 30 min). Discovery + subscription to
`binary_sensor.{room_slug}_occupied`: `_discover_guest_rooms()` `presence.py:4668-4730`, called from setup
`:2561-2562`. Handler `_handle_guest_room_occupancy_change()` `:4732-4801` — a 3-transition machine
(unoccupied → clear `first_seen`; occupied + known person → clear and set `current_occupancy_known=True`;
occupied + unknown → arm `first_seen`), then `_run_inference("guest_room_occupancy")` `:4801`. Known-person test
`_is_known_person_in_room()` `:4803-4828` (falls back to False, i.e. guest-favouring). Pure predicate
`_guest_room_gate_armed()` `:4830-4859`. Confidence 0.9.

*(Note: the prior-art review of `PLANNING_v4.7.2` flagged D4/D5 as possibly unbuilt. Source evidence above plus
the live config in §0.2 settles it — it is built, wired, and configured on three rooms.)*

**Path C — manual override.** Service `set_house_state` with `"guest"` (`services.yaml:21`, handler
`__init__.py:4870-4878`, registered `:4930-4945`, clear `:4891-4897`); select entities `select.py:43,51,52` →
`_HouseStateOverrideSelectBase` `:108` → `PresenceCoordinator.set_house_state_override()` `presence.py:7193-7223`.
`HouseStateMachine.set_override()` `house_state.py:213-221` **explicitly bypasses transition validation and
hysteresis** — and is not gated by the kill switch. Live `is_overridden: false`, so this is not tonight's cause.

**There is no Path D.** `switch.ura_presence_guest_detection_enabled` (`switch.py:3182-3194`) is a kill switch
only. `switch.ura_hvac_coordinator_guest_mode_actuation_enabled` (`switch.py:1506-1631`) is a consumer gate.
`binary_sensor.ura_guest_mode` (`binary_sensor.py:2004-2039`) is a pure mirror of
`manager.house_state == HouseState.GUEST` with **no internal consumer**.

### 3.2 How they compose — verbatim

`presence.py:5382-5404`:

```python
if current_state in _home_like_states:
    unid_gate_armed = self._guest_gate_armed(
        unidentified_count=self._unidentified_count,
        census_confidence=self._census_confidence,
        now=now,
    )
    # v4.7.2 D5: Sustained-occupancy guest room path (additive OR).
    guest_room_gate_armed = self._guest_room_gate_armed(now=dt_util.utcnow())
    guest_armed = unid_gate_armed or guest_room_gate_armed
elif current_state == HouseState.GUEST:
    # Already in GUEST — skip unid gate (side-effect-bearing) but
    # evaluate guest_room gate (pure predicate) so the hold/exit decision is truthful.
    unid_gate_armed = False
    guest_room_gate_armed = self._guest_room_gate_armed(now=dt_util.utcnow())
    guest_armed = guest_room_gate_armed
else:
    unid_gate_armed = False
    guest_room_gate_armed = False
    guest_armed = False
```

Confidence layered on the **result**, `:5407-5414`:

```python
if guest_room_gate_armed and unid_gate_armed:
    _d5_guest_confidence = max(0.8, 0.9)   # = 0.9
elif guest_room_gate_armed:
    _d5_guest_confidence = 0.9
else:
    _d5_guest_confidence = 0.8
```

The single collapsed boolean is passed to the engine at `:5784` (`guest_gate_armed=guest_armed`); the D5
confidence is applied post-hoc at `:5939-5942`. The engine's entry limb, `presence.py:1267-1274`:

```python
if guest_gate_armed and current_state in (
    HouseState.HOME_DAY, HouseState.HOME_EVENING, HouseState.HOME_NIGHT,
):
    if current_state != HouseState.GUEST:
        self._confidence = 0.8
        return HouseState.GUEST
```

**Answer to the composition question: it is a plain OR of two independent latches, collapsed to one boolean
*before* the engine.** The engine cannot tell which path fired. Four precedence consequences:

1. **The confidence gate applies to the left operand only.** `guest_mode_require_confidence` lives *inside*
   `_guest_gate_armed` `:4895-4901`. Path B has **no confidence gate at all** — a single room-occupancy sensor
   can arm GUEST with zero census corroboration.
2. **Inside GUEST the OR degenerates to Path B alone** `:5393-5400`. Path A is deliberately not re-evaluated
   while already GUEST, so **only Path B can sustain GUEST via the gate** — and Path B is the ungated one.
3. **Sleep hours suppress entry but not exit.** The sleep branch `:1245-1250` returns SLEEP before the guest-entry
   limb; v5.16.0 D1 moved the guest-*exit* check above it `:1228-1243`.
4. **Path C bypasses everything** — confidence, persistence, transition validation, hysteresis, kill switch.

### 3.3 Sustain and release

- `guest_mode_persistence_seconds` (`const.py:2719-2720`, default 300, **live 300**; `0` = fire immediately
  `:4904-4909`). Semantics: the unidentified condition must hold **continuously**; `_unidentified_first_seen` is
  cleared on any non-qualifying tick by `_disarm_guest_gate()` `:4653-4662`.
- **Path B has no persistence knob** — only the per-room `threshold_min`, and its exit is **immediate**
  (docstring `:4838`): any occupancy-off or known-person event resets `first_seen` `:4770-4790`.
- State-machine hysteresis: GUEST minimum dwell **300 s** (`house_state.py:103`) vs 120 s for HOME_*.
- **Exit damping (v4.7.15 D3):** GUEST→HOME_* is itself debounced — `presence.py:6032-6087` starts
  `_guest_exit_quiet_since` when `unidentified_count == 0 and not guest_armed`, running the `"guest_exit"` veto
  scope (`:1952-1971`, threshold falls back to `_guest_persistence_seconds`); if not sustained, `new_state = None`
  suppresses the exit that tick.
- **v5.16.0 GUEST→SLEEP latch work** (commit `cd93d169c`, shipped `dd4dc75b8`): D1 moved the guest-exit check
  above the sleep-hours branch — on 2026-07-11 a guest arrived 20:57, the gate cleared 23:05, and the state stayed
  GUEST until 06:05 because the sleep branch returned first and shadowed the exit. D1b added `HOME_NIGHT → GUEST`
  to `VALID_TRANSITIONS` (`house_state.py:64-72`); before that a HOME_NIGHT guest proposal was silently rejected.
  The exit condition deliberately tests `guest_gate_armed` (the OR), not raw `unidentified_count`, so Path B can
  hold GUEST at `unidentified_count == 0` — `presence.py:1241`.
- **Clears:** `_disarm_guest_gate()` on fire, count drop, confidence regression, house leaving HOME_*/GUEST
  `:5365-5372`, on transition into and out of GUEST `:6286-6293`, and on unload `:6976-6977`. Path B additionally
  `_clear_guest_room_first_seen()` `:4996-5002` when the kill switch is OFF.
- `VALID_TRANSITIONS[GUEST]` has **no SLEEP target** (product decision, byte-unchanged since v3.6.0-c0) — so an
  active GUEST **blocks the house from entering SLEEP at all** until it exits to HOME_NIGHT.

---

## 4. What guest mode actually DOES (actuation)

The operator asked specifically about guest actuation. The honest answer: **very little, and the parts designed
to matter are inert.**

### 4.1 Real effects today

**HVAC**
- `hvac_const.py:789` — `HOUSE_STATE_PRESET_MAP["guest"] = "home"`. **Setpoints are identical to HOME.
  Guest changes no HVAC target by itself.**
- `hvac_const.py:224` — `ARRESTER_HOLD_PRESERVING_STATES = {arriving, guest, waking}`, consumed at
  `hvac_override.py:528-560` and `:825-845`. Entering GUEST does **not** sunset operator manual holds or the
  Temp Arrester Override, where every other durable state would clear them. **This is the largest real HVAC delta.**
- `dynamic_preset.py:860-861` — if `CONF_ZONE_DYNAMIC_PRESET_RESET_OFFSET_GUEST` (default **True**), the per-zone
  dynamic-preset offset is forced to **0.0** during guest, disabling weather-driven setpoint shading. House state
  read via `energy.py:6825-6845` (reachable only since v5.37.0).
- `hvac.py:1759` — guest joins the zone-entry-dwell anti-flap set.
- Egress and fans: **zero guest references** in `hvac_egress.py`, `hvac_fans.py`, `fan_policy_oracle.py`,
  `presence_fan_recheck.py`.

**Learning / prediction suppression** (the most functional cluster)
- `__init__.py:2453-2473` — `_bayesian_guest_listener` calls `bayesian_predictor.suppress_learning(True)`;
  all Bayesian occupancy updates dropped (`bayesian_predictor.py:155,353,547,784`).
- `optimization.py:2610-2621` — accuracy-drift findings suppressed, so guest doesn't manufacture DEGRADED findings.
- `binary_sensor.py:2662-2669` — `OccupancyAnomalyBinarySensor` forced off, `suppressed_reason="guest_mode"`.
- `routine_forecaster.py:105,319-322,422-423,469-481` — guest is a passthrough: rows with
  `prev_state ∈ {guest, vacation}` excluded from routine training; forecast returns `state="guest"`,
  confidence 0.3, model suffix `+guest_passthrough`.
- `memory_facade.py:279` — guest bins to family `"home"`.

**NM / notifications**
- `const.py:1617,1627,1711-1712` — exterior-person hazard severity in guest = **MEDIUM**
  (`NM_HAZARD_EXTERIOR_PERSON_GUEST_SEVERITY`), vs CRITICAL for away/sleep/home_night and LOW for home_day/evening.
  Consumed `perimeter_alert.py:1563-1570`.
- `const.py:1673-1678` — the circling→HIGH universal override **explicitly excludes guest**; documented as
  INV-M carve-out at `perimeter_diagnostics.py:7`.
- **Quiet hours are `("sleep","home_night")` only** (`notification_manager.py:3761-3771`) — guest neither
  suppresses nor reroutes notifications.

**Security**
- `security.py:161` — `_HOUSE_STATE_TO_ARMED["guest"] = ArmedState.ARMED_HOME`; entering guest arms to HOME, and
  the DISARMED→ARMED_HOME direction is NM **HIGH** (`:165-175`).
- The `authorize_guest` service and authorized-guest sanctions (`security.py:225-306,2180-2208`,
  `__init__.py:5240-5290`) are an **entirely independent subsystem**, not gated on `HouseState.GUEST`.

**Sleep/wake** — guest entry blocked during sleep hours `:1245`; GUEST is not a valid SLEEP predecessor, so an
active guest blocks SLEEP entirely (§3.3).

**Presence trust / veto denominators** — `aggregation.py:4108-4136` includes `"guest"` in the Layer-3 fallback
set exactly like home_*. `automation.py:2965` `_FAN_TRUST_STATES = ("home_night","sleep","waking")` — guest
**excluded**. `fan_veto.py:75,431` keys only on `_AWAY_STATES`. **Guest neither adds nor removes presence trust,
and there is no guest-specific veto denominator anywhere.**

**Lights / brightness** — no guest-conditional code anywhere in the component.
**Energy / optimizer** — only the dynamic-preset offset reset above.

### 4.2 Designed but INERT

1. **The entire guest HVAC-override producer is unimplemented.** `preset_overrides.py:26`
   `OVERRIDE_SOURCE_GUEST_MODE`, `energy_const.py:617` `GUEST_MODE_PRIORITY = 50`, and the per-zone keys
   `zone_guest_home_cool_low/high`, `zone_guest_sleep_cool_low/high`, `zone_guest_mode_opt_out`,
   `guest_mode_actuation_enabled` (`energy_const.py:654-661`) have **no producer**. Nothing constructs a
   `PresetOverride(source="guest_mode", …)`; the only populator of `_dynamic_preset_overrides` is the
   dynamic-preset source (`energy.py:6581-6747`). `preset_overrides.py:147-148` is dead code. v5.7.0 records that
   `build_guest_mode_overrides` was **deleted at `preset_overrides.py:241-249` for having zero callers** —
   textbook Bug Class #53, computed-but-not-consumed.
2. **`switch.ura_hvac_coordinator_guest_mode_actuation_enabled` is misnamed.** It gates
   `_async_apply_preset_overrides()` wholesale (`switch.py:1506-1631`, `hvac.py:431`, gate `:2159-2160`), which
   today actuates only **dynamic-preset** ranges. Turning it off disables weather-driven setpoints and has
   **zero relation to guests**.
3. **WiFi guest-VLAN counting** — computed in full, discarded (§1.4).
4. **v5.7.0 WS-B guest-cool / vacant-warm signed DPM terms** (`CONF_ZONE_GUEST_COOL_HIGH_OFFSET` default −1.0 °F,
   `CONF_ZONE_RARELY_OCCUPIED_BIAS_F`) — designed, no build evidence.
5. `memory_facade.py:102` `"guest_policy"` — declared doc key, no writer or reader.
6. `PresetOverride.heat_low/heat_high` `:66-67` — "reserved; not exposed", never set.

**Bottom line for Problem B/C:** the cost of a false guest activation today is *mostly* suppressed learning,
a preserved HVAC hold, a disabled DPM offset, downgraded perimeter severity, and a blocked SLEEP transition.
That is real but modest — which is precisely why 50 unexplained guest episodes since 07-13 went unnoticed.
**It also means the actuation surface is a blank slate: whatever the operator wants guest mode to DO must be
built, and should not be built on top of a count that reads 10 for 5 people.**

---

## 5. Prior art

| Doc | Designed | Status |
|---|---|---|
| `PLANNING_census_overcount_dedup_decay.md` (07-07) | D-A same-area spatial dedup; D-B sustain-before-latch (`CENSUS_PEAK_SUSTAIN_SECONDS≈15`); D-C hold re-tune (15→3 min); D-E `area_contributions`/`pending_peak`/`raw_pre_dedup_sum` attrs. Cut: per-input TTL, `CONF_CAMERA_OVERLAP_GROUPS`, transit-transfer suppression | **SHIPPED v5.9.0.** D-A's observability is **inert on the enhanced path** (§1.9) |
| `PLANNING_census_ble_cancel_unrecognized.md` (07-13) | Per-area BLE cancel `correction = min(raw_contribution, ble_here)`; `_ble_home_by_area`; `ble_cancelled_count`; invariants I1/I2/I3. Deliberately **no CONF knob** ("a bug-fix, not an option") — a knob was added later anyway | **SHIPPED (`2f864ac79`/`dcd6fe2c0`) BUT CURRENTLY INERT.** Live `ble_cancelled_count: 0`. Card CENSUS-GHOST-DEDUP-1 verbatim: *"BLE-cancel exists, is enabled, cancels nothing"* |
| `PLANNING_census_fusion_policy.md` (08-01) | Kill max-wins in `_cross_validate_platforms`: uncorroborated divergence → `(min, DISAGREE)` → LOW. `CONF_CENSUS_DIVERGENCE_DOWNGRADE` + `CENSUS_DIVERGENCE_CORROBORATION_KINDS` | **DESIGNED-BUT-UNBUILT.** Premise partly stale post-F1-retirement (Protect leg now non-contributing, `single_source`) |
| `PLANNING_gap_a_census_hole.md` (08-16) | Path α gates `face_recognized_count == 0` not `census_count == 0`; additive payload key; invariant I-GA; explicitly no new knob | **SHIPPED v5.78.0** (`2e76a5a91` + `5db8af1d2`). L1/L4 PASS. Residual: path β unchanged |
| `PLANNING_guest_fp_lost_away_and_outdoor_census.md` | Fix A LOST-away trusted admission; Fix B outdoor-zone census exclusion | **SUPERSEDED stub** — 8 lines; A shipped v4.7.14.1 H3, B shipped v5.7.0 WS-A |
| `PLANNING_presence_guest_latch_and_veto_gap.md` (07-12) | D1 guest-exit before sleep branch; D1b `HOME_NIGHT→GUEST`; D2 empty-house veto immediate-engage limb + `sustained_external_empty`; D3 substrate edge observability | **SHIPPED v5.16.0** (PR #417, `cd93d169` + fix-up `f0aa3231`). Memory says *"Do NOT re-plan."* D2's first build was a tautology caught by three reviewers |
| `PLANNING_v4.6.2.2_guest_mode_hardening.md` | `CONF_GUEST_MODE_PERSISTENCE_SECONDS` (300) + `CONF_GUEST_MODE_REQUIRE_CONFIDENCE` ("medium"). **`CONF_GUEST_MODE_MIN_UNIDENTIFIED` considered and dropped** — threshold stays `> 0` | **SHIPPED** — but the FP it targeted was never solved (2-4 false arms/day persisted; 50 episodes since 07-13) |
| `PLANNING_v4.7.2_dpm_hvac_surface_plus_guest_signal.md` | D3 switch rename; D4 per-room `is_guest_room` + threshold; D5 `guest_room_gate_armed` as **additive OR**, confidence 0.9 > 0.8 | **D4/D5 SHIPPED AND LIVE** (verified §3.1 + §0.2, correcting the prior-art doubt) |
| `PLANNING_v4.7.x_guest_mode_actuation_phase1.md` | Per-(zone,preset) `PresetOverride` schema, `guest_mode` source, priority 50, `active_when` | **PARTIALLY SHIPPED then SUPERSEDED.** Sink + `OverrideEngine` shipped; producer `build_guest_mode_overrides` **deleted for zero callers** |
| `PLANNING_v5.7.0_guest_mode_detection_and_actuation.md` | WS-A A1 LOST-away denominator, A2 indoor guard, A3 `CONF_LOST_AWAY_GRACE_MIN`/`_SLEEP_EXEMPT`, A4 `CONF_ZONE_IS_OUTDOOR`; WS-B guest-cool/vacant-warm DPM terms | **WS-A SHIPPED.** WS-A Residual-B1 (**camera-census outdoor filter**) still unbuilt. **WS-B unbuilt** |
| `AUDIT_census_accuracy_regression.md` (08-15) | H1 CONFIRMED: F2 migration left every count sensor `_2`-suffixed; strict `endswith("_person_count")` matchers → `person_count_sensor=None` → binary fallback → census pinned at the identified count | **FIXED v5.77.0** (CENSUS-SUFFIX-FIX-1, `75c68ecc9`) |
| `AUDIT_guest_fp_fixes_wiring.md` (08-12 + 08-13 addendum) | Fix A/B wired; residual A1 (path-α classifier) and B1 (outdoor census filter). **§3: 50 guest ENTRY episodes since 07-13 across 22/31 days, 1-7/day, almost all daytime, flappy** | A1 **shipped v5.78.0**; B1 **unbuilt**; the 50 episodes **remain unexplained pending operator ground truth** |
| `GOLDEN_MASTER_census_cutover_diff.md` (08-06) | Gate for `CENSUS_USE_NEW_RESOLVER`. First run NO-GO (BLOCK-1: Frigate-keyed stem index dropped the whole UniFi egress leg); bidirectional `_stem_to_device_ids`, `_device_platform_hint`, `area_id` carry-through | **SHIPPED (fix stack)**, final `compared=24 identical=21 differing=3` → GO, 5-mutation ledger |

### Kanban cards

| Card | Status | `next` |
|---|---|---|
| `CENSUS-GHOST-DEDUP-1` | **pre_planning** | *"Investigate (read-only first): instrument or trace which entities produce the unrecognized contributions and what area each resolves to at runtime; confirm whether the enhanced path runs. Then decide: fix area resolution, relax I3 for kn…"* |
| `CENSUS-SUFFIX-FIX-1` | **done** | Post-deploy Live: census exceeds 4 during next multi-person traversal — **met** (`dbe3a542b`) |
| `CENSUS-GUEST-FLOOR-1` | **parked** | *"ura-planner scope after current deploy queue clears; Tier 2 (…possibly 2-DB per standing policy)."* Park note: *"SHRUNK by the regression root-cause… Revisit trigger: AFTER the fix ships + one real gathering, if guest counts still under-read materially"* — design was to re-admit the WiFi VLAN count as a bounded **floor** |
| `PATH-ALPHA-DENOM-1` | **shipped_organic** | (stale-by-success) |
| `GAP-A-CENSUS-HOLE-1` | **shipped_organic** | (stale-by-success; `live_validation_2026_08_16` is current truth) |
| `GUEST-FP-RESIDUALS-1` | **shipped_organic** | *"Fold A1+B1 into the next presence hotfix batch; await operator answer on the 50-episode pattern."* |

**Note on CENSUS-GUEST-FLOOR-1:** its revisit trigger was *under*-reading. Tonight is the opposite — a
material **over**-read. The card's premise should be re-examined before it is unparked; re-admitting a WiFi
floor on top of an additive path that already over-counts would compound the error.

### Recent work

- **v5.76.0** (`468e349f2`) — memory compactor Stage 2 + circling transition exemption. *Census-neutral.*
- **v5.77.0** (`75c68ecc9`) — **census count restore** (the `_2`-suffix fix) + reload-suppress + opt-meta boot fix.
  **Problem A only.**
- **v5.78.0** (`5db8af1d2`) — LOST dissolution (PATH-ALPHA-DENOM-1), 4 memory episode writers, **Gap-A away-veto
  census hole (D8)**, GUEST-FP-RESIDUALS A1, Gap-B PhoneLeftBehind corroboration, EV sensor cleanup.
  New observability `path_alpha_gate_source`, `face_recognized_count`. **Problem A only** — D8 changed how the
  count is *consumed by the AWAY veto*, not how guest mode activates.
- **Frigate F2** — F1 retirement (`49d54f381`, 08-12→08-15, 50 registry renames, F1 entry deleted 08-15,
  965 entities removed) **caused** the v5.77.0 regression. F2 detector tuning (vibememo 052, 08-16): *"13+3 cams
  Low→Medium, 2.5× recognition rate, 8× for Oji."* F2 runs `yolov9t.onnx` OpenVINO with **zero night IR ghosting**
  vs F1's 100%-single-witness sub-2s IR ghosts. Open: `sensor.foyer_fisheye_person_count_2` near-dead
  (1 sample/24h); ASH41B deliberately out of census by operator ruling.

**F2 tuning is a genuine tailwind for Problem A and cuts the other way too:** higher recognition rate shrinks
the unidentified bucket at the source — but only if recognitions pass the **1800 s freshness window**
(`CENSUS_FACE_RECOGNITION_WINDOW_SECONDS`, a rung-1 module constant). Live `face_recognized_persons: []`
alongside `face_confirmed: [4 names]` says they currently are not.

---

## 6. THE DIFF

| | **What exists today** | **What v5.76–v5.78 + F2 changed** | **What is broken / missing** | **Minimal change that would close it** |
|---|---|---|---|---|
| **A: get a good count that works** | Two derivations. **Raw** `_cross_correlate_persons` `:1770-1777` — subtractive, `unidentified = max(0, camera−identified)`, `total = max(camera, identified)`. **Enhanced** `_apply_enhanced_house_census` `:3075` (**default ON**) — additive, `total = identified + camera_unrecognized`, overwriting the raw result. Defenses: fresh-face `−1`/camera `:2760`, per-area BLE cancel `:2798-2816`. Hold 3 min + decay −1/300 s + 15 s sustain. WiFi floor computed, discarded. Exterior fully separate. | **A LOT — and this is the only problem they touched.** v5.77.0 fixed the `_2`-suffix breakage that had pinned census at the identified count since 08-13. v5.78.0 D8 rewired the path-α *consumer* to `face_recognized_count`. F2 tuning raised recognition 2.5–8×. | **Both anti-double-count defenses are returning zero right now.** `ble_cancelled_count: 0`; `camera_unrecognized == frigate_count == 6` exactly (no fresh-face `−1` fired anywhere); `face_recognized_persons: []` while `face_confirmed` has all 4 names. Result **10 = 4 + 6** for ~5 people. Root: the enhanced path dropped the raw path's structural invariant and replaced it with two fail-open corrections. Also: `area_contributions` observability reads the wrong producer (§1.9), so the operator is blind to the enhanced path's dedup. | **G1 (below): restore the subtractive clamp** — `total = max(identified + held_unidentified, identified, camera_total_deduped)` becomes `unidentified = max(0, held_unidentified − identified_seen_on_camera)`. **New code**, ~10 LoC at `camera_census.py:3109`, no new knob. **G2:** point `area_contributions` at the enhanced path's dict (**new code**, observability, ~5 LoC). **G3:** `CENSUS_FACE_RECOGNITION_WINDOW_SECONDS` 1800 s is a rung-1 constant that is now the binding gate post-F2 — **promote to rung 2** (options flow) so it can be tuned against the new recognition rate. |
| **B: if durable, activate guest mode and under what conditions** | Two independent latches OR'd at `presence.py:5399`: **Path A** census-unidentified (kill switch → `>0` → confidence ≥ `medium` → 300 s persistence) and **Path B** guest-room sustained occupancy (`is_guest_room` + `threshold_min`, live on 3 rooms at 30 min). Collapsed to one boolean before the engine `:5784`. Path C manual override bypasses all. Inside GUEST, only Path B is evaluated `:5393-5400`. | **NOTHING.** No shipped cycle since v4.7.2-D5 (Path B) and v5.16.0 (the latch/exit ordering) has touched guest activation. v5.78.0's D8 changed the *away veto*, not the guest gate. | **The OR is backwards relative to the operator's instinct.** Path B — the higher-bar, spatially-grounded, 0.9-confidence path the operator wants to lead — is the *weaker* operand: it has **no confidence gate at all** (`_guest_room_gate_armed` `:4830-4859` checks only the kill switch), no persistence knob, and immediate exit. Path A — the noisy census path — can activate GUEST house-wide **alone**, from any room, on `unidentified > 0`. There is no AND, no room-attribution requirement, no minimum count. | **G4: make Path A require room attribution, keep Path B as-is.** This is **precedence/composition, not new mechanism**: change `guest_armed = unid_gate_armed or guest_room_gate_armed` to require that Path A's unidentified evidence be attributable to a designated guest room — i.e. `(unid_gate_armed and guest_room_gate_armed) or guest_room_gate_armed`, which reduces to **`guest_armed = guest_room_gate_armed`** with Path A demoted to a *corroborator* raising confidence 0.9→0.95. Both operands already exist and are already computed on every tick. **G5 (config-only, zero code):** the 3 guest rooms are already flagged; raise `guest_mode_require_confidence` `medium`→`high` to gate Path A harder in the interim. |
| **C: activate guest mode if high confidence AND sustained** | *Sustained* exists on both paths — Path A `guest_mode_persistence_seconds` 300 s continuous (`_unidentified_first_seen`, cleared on any non-qualifying tick `:4653-4662`), Path B per-room `threshold_min` 30 min. *Confidence* exists on Path A only (`guest_mode_require_confidence: medium`, `:4895-4901`). GUEST hysteresis 300 s; exit debounced by the `"guest_exit"` veto scope `:6032-6087`. | **NOTHING** — and F2/v5.77.0 arguably made C **worse**: a higher, more responsive count feeds a gate whose effective threshold is still `unidentified > 0`. | Three defects. **(i)** "High confidence" is `high|medium|low` **census** confidence — which is `high`/`both_agree` right now *while the count is wrong by 5*. Census confidence measures **platform agreement**, not correctness; both platforms agreeing on a double-counted resident yields `both_agree`. **It is the wrong oracle for the guest bar.** **(ii)** "Sustained" is defeated by hold/decay: a 3-min hold + 300 s-per-person decay makes a phantom *structurally durable* for ~25 min, comfortably outlasting the 300 s persistence gate. **The gate cannot distinguish sustained-because-real from sustained-because-held.** **(iii)** Path B — the path that *is* genuinely high-bar and sustained — has no confidence requirement and doesn't need one, but is currently only an OR operand. | **G6: gate Path A's persistence on the *raw* (unheld) unidentified value, not the held one.** `_apply_hold_decay` already returns both; `unidentified_raw` exists at `camera_census.py:3102`. Plumb it as a second payload key and require *it* to hold for 300 s. **New code**, ~15 LoC, additive/byte-identical by the Gap-A D8 pattern, **no new knob**. **G7 (config-only):** `guest_mode_require_confidence` → `high`. **G8:** if a count threshold is wanted, `CONF_GUEST_MODE_MIN_UNIDENTIFIED` was **designed and dropped** in v4.6.2.2 — reviving it is **new code + rung 2**, but G4 makes it unnecessary and it should not be built alongside G4. |

---

## 7. Ranked gap list (by leverage)

**G1 — Restore the subtractive invariant in the enhanced census path.** *New code, ~10 LoC, no knob.*
`camera_census.py:3109`. The enhanced path can add a person to `identified` and to `unidentified`
simultaneously; the raw path structurally cannot. Everything downstream — guest activation, the AWAY veto,
security lockdown, the phone-left-behind suppressor — inherits the error. **This is the root cause of tonight's
10 and it is one line of arithmetic.** Highest leverage by a wide margin: it fixes Problem A at the invariant
level rather than adding a third fail-open correction on top of two that already failed.
*Falsifiable invariant for the cycle:* **"For any tick, `identified_count + unidentified_count ≤ total distinct
persons physically detectable, and no person contributes to both terms."** Note the existing defenses were
written as *corrections*; G1 makes it a *clamp*, which cannot fail open.

**G4 — Invert the guest composition so guest ROOMS lead.** *Precedence/composition, ~5 LoC, no new mechanism.*
`presence.py:5399`. Both operands are already computed every tick; this is a change to one boolean expression.
Directly implements *"Guest should have a higher bar. Guest rooms can be indicated and guest mode comes from
their occupancy."* The three guest rooms are **already flagged live**. It also fixes the asymmetry that only
Path B can *sustain* GUEST while only Path A can *enter* it. Strictly reduces the FP surface — the 50
daytime episodes since 07-13 are all Path A shaped (flappy, daytime, guest↔home_day within the hour).

**G6 — Persistence gates on raw unidentified, not held.** *New code, ~15 LoC, additive, no knob.*
Closes Problem C's central defect: hold/decay manufactures the very durability the gate is looking for.
Follows the v5.78.0 D8 pattern exactly (new additive payload key, `int = 0` default, byte-identity preserved),
so the plumbing is proven. Lower leverage than G1/G4 only because G1 shrinks the phantom that G6 protects against.

**G3 — Promote `CENSUS_FACE_RECOGNITION_WINDOW_SECONDS` from rung 1 to rung 2.** *Config-only + ~5 LoC to read it.*
This 1800 s module constant is now the **binding gate** on the enhanced path: it is why
`face_recognized_persons: []` while all 4 residents are face-confirmed, and therefore why the per-camera `−1`
never fires. F2 tuning changed the recognition-rate regime underneath a constant that was fitted to F1.
Per the knob ladder, a number the operator would legitimately re-tune by observation after a detector change
belongs on rung 2, not rung 1.

**G7/G5 — `guest_mode_require_confidence` → `high`.** *Config-only, zero code, reversible in the options flow.*
Worth doing tonight as a stopgap. **But be honest about its ceiling:** census confidence is `high`/`both_agree`
*right now, while the count is wrong by 5*. It measures platform agreement, not correctness. This buys hours,
not a fix, and must not be mistaken for closing Problem C.

**G2 — Fix the `area_contributions` observability.** *New code, ~5 LoC.* `sensor.py:3511` reads
`_last_area_contributions` from the **raw** producer while the **enhanced** path computes its own and discards it.
Low behavioural leverage, high diagnostic leverage: without it, CENSUS-GHOST-DEDUP-1 cannot be traced, and any
G1 fix cannot be validated live. **Should ship in the same cycle as G1** — it is the acceptance instrument.

**G9 — Camera-census outdoor-zone filter (v5.7.0 WS-A Residual-B1).** *New code.* `CONF_ZONE_IS_OUTDOOR` exists
and is consumed by three other coordinators but is **never imported by `camera_census.py`**. Latent-safe today
only because Patio has no camera person inputs — a config change alone could arm it. Low urgency, non-zero risk.

**G8 — `CONF_GUEST_MODE_MIN_UNIDENTIFIED`.** *New code + rung 2.* **Recommend NOT building.** It was designed and
deliberately dropped in v4.6.2.2, and G4 makes it redundant: room attribution is a better bar than a raw
count threshold, and stacking both is cruft. Recorded here with its revisit trigger: *if G1+G4 ship and guest
still false-fires on multi-person gatherings, revisit.*

### Explicitly not proposed

Per the no-cruft rule, every gap above composes an existing mechanism. In particular: **no new guest-confidence
sensor** (`sensor.universal_room_automation_census_confidence` exists, merely disabled by default — enable it);
**no new guest state** (`HouseState.GUEST` + `binary_sensor.ura_guest_mode` exist); **no new persistence timer**
(`_unidentified_first_seen` + `_schedule_guest_persistence_recheck` exist); **no new room flag**
(`CONF_ROOM_IS_GUEST_ROOM` exists and is live on 3 rooms); **no re-admission of the WiFi floor**
(CENSUS-GUEST-FLOOR-1 — its trigger was *under*-reading; tonight is an over-read, so its premise is inverted).

### A note on guest actuation

The operator asked about guest actuation specifically. §4 is the honest inventory: guest mode today preserves
HVAC holds, zeroes the DPM offset, suppresses Bayesian learning and anomaly findings, downgrades perimeter
severity, arms security to HOME, and blocks SLEEP — and the *designed* HVAC actuation
(`OVERRIDE_SOURCE_GUEST_MODE`, priority 50, the per-zone guest setpoint keys) has **no producer at all** and its
one-time producer was deleted for having zero callers. **Recommendation: do not build guest actuation on the
current count.** G1 + G4 first; actuation is worth designing only once activation is trustworthy, or the house
will actuate confidently on a phantom.

---

## 8. Answer to the composition question

**How do the guest paths compose today?**

A plain **OR of two independent latches**, evaluated at `presence.py:5382-5404` and collapsed into a single
boolean `guest_armed` *before* it reaches the inference engine at `:5784`. The engine (`:1267-1274`) has no
knowledge of which path fired. Neither latch gates the other; there is no AND, no precedence, no
room-attribution requirement, and no minimum count. Confidence is layered on the *result* (`:5407-5414`,
0.9 if the guest-room path contributed, else 0.8), never used to *arbitrate* between the paths.

Four asymmetries make the OR worse than it first appears:

1. `guest_mode_require_confidence` is applied **inside** `_guest_gate_armed`, i.e. to the **left operand only**.
   Path B has **no confidence gate whatsoever**.
2. **Inside GUEST the OR degenerates to Path B alone** (`:5393-5400`) — so the ungated path is the only one that
   can *sustain* GUEST, while the gated path is the only one that can *enter* it. Exactly backwards.
3. Path B has no persistence knob and exits immediately; Path A has a 300 s persistence gate and a debounced exit.
4. Path C (service/select override, `house_state.py:213-221`) bypasses confidence, persistence, transition
   validation, hysteresis, and the kill switch entirely.

**Did tonight's phantom win because of an OR?**

**No — and this matters for where to spend the fix.** Path A armed on its own merits: `unidentified_count = 6`
(> 0 ✓), `census_confidence = high` (≥ `medium` ✓), and 6 has been held well past 300 s ✓. All three of Path A's
gates passed. The OR was never load-bearing tonight: `unid_gate_armed` alone was `True`, so the right operand
was irrelevant. `is_overridden: false` rules out Path C.

**Tonight's phantom won because the count was wrong, and because Path A is allowed to activate house-wide GUEST
by itself.** Those are two separate defects and both need closing:

- **The count defect (G1)** is why `unidentified` read 6 instead of ~1: the enhanced path added the four
  residents' BLE identities to a camera-unrecognized bucket that still contained those same four residents,
  because neither the fresh-face `−1` nor the BLE-cancel fired. `camera_unrecognized == frigate_count == 6`
  exactly is the fingerprint.
- **The composition defect (G4)** is why a wrong count was *sufficient*. Fixing the count alone leaves guest mode
  one census regression away from firing again — and the census has now regressed twice in four days
  (the `_2` suffix on 08-13, this on 08-16).

So: the OR did not *cause* tonight, but the OR is what makes tonight's class of failure *reachable at all*.
The operator's instinct is correct and is the right structural fix — **guest rooms should lead, and the census
should corroborate, not activate.** Under G4, tonight's phantom would have been contained: with no designated
guest room sustaining unknown occupancy for 30 minutes, `guest_room_gate_armed` would be `False`, and a
6-person census phantom would have raised confidence on nothing at all.

---

*Read-only research. No code, config, or cards were changed in producing this document.*
