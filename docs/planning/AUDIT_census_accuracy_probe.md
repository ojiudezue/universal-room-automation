# AUDIT — Census accuracy measurement probe

**Date:** 2026-08-16 (local, America/Chicago)
**Scope:** gating probe for the merged census-accuracy cycle
(`CENSUS-DECAY-SEPARATION-1` + `CENSUS-DEDUP-REPAIR-1`).
**Mode:** READ-ONLY. No repo changes other than this file. No pytest run.
**Rule invoked:** CLAUDE.md "Measure Before You Build".

## Data sources actually used

| Source | Verification |
|---|---|
| HA recorder `/config/home-assistant_v2.db` | via `ssh ha "python3 -" < script.py`, opened `mode=ro`. `purge_keep_days: 7` (`/config/configuration.yaml:13`) — **7 days is the hard history limit.** |
| Live entity states / attributes | `ha_get_state`, `ha_eval_template` (home-assistant MCP) |
| Live config entries / registries | `/Users/okosisi/ha-config/.storage/` over the mounted Samba share (`//homeassistant@192.168.13.13/config`, live — DB mtime tracked "now" during the probe) |
| Source | develop main checkout (`custom_components/universal_room_automation/`) |

**`ura-sqlite` MCP was NOT used** — no `ura-sqlite` server entry was found in
`~/.claude.json`, and the documented mount path in CLAUDE.md
(`/Users/ojiudezue/ha-config/...`) does not exist on this host; the real mount is
`/Users/okosisi/ha-config/...`. All URA-side facts below come from the live
`.storage` registries + the live entity states instead, so nothing here is from a
stale cache. **CLAUDE.md's Data Source Verification section has a stale path and
should be corrected** (separate, out of scope here).

## Live baseline at probe time (2026-08-16 23:19 CDT)

`sensor.universal_room_automation_persons_in_house` = **6**
(`identified_count: 4`, `unidentified_count: 2`, `camera_unrecognized: 0`,
`peak_held: true`, `peak_age_minutes: 4`, `ble_cancelled_count: 0`,
`area_contributions: {}`, `raw_pre_dedup_sum: 0`, `stuck_cameras: []`,
`face_recognized_persons: []`, `confidence: low`).
House state = `sleep`. All four residents are BLE-ACTIVE in bedrooms.
The `+2` is a pure hold/decay tail: no camera is contributing a body this tick.

`sensor.ura_presence_coordinator_people_home_census` = 6 — its 7-day histogram is
**identical** to `persons_in_house`, confirming they are one number, not two.

---

# Q1 — Why does per-area BLE-cancel return zero?

### METHOD

1. Read the mechanism end to end:
   - `camera_census.py:2670` `_get_unrecognized_camera_count()` — 4-step algorithm;
     Step 3 subtraction at `camera_census.py:2806`
     (`ble_here = ble_by_area.get(aid, 0)`; `correction = min(raw_max, ble_here)`).
   - `camera_census.py:2285` `_ble_home_by_area()` — builds `{area_id: count}` from
     `person_coordinator.data`, requires `location` ∉ {away, unknown, home, lost},
     `tracking_status` ∉ {stale, lost}, and a hit in `_build_room_to_area_id_map()`.
   - `camera_census.py:1956` `_build_room_to_area_id_map()` — `{room_name: CONF_AREA_ID}`
     from URA room config entries.
2. Rebuilt each input from live data:
   - room→area map from `.storage/core.config_entries` (39 room entries).
   - camera areas from `.storage/core.entity_registry` + `core.device_registry`
     (entity `area_id` is `None` for every Frigate entity → area resolves via device,
     matching production `resolve_area_id_for_entity`).
   - resident locations from the four live `*_location` sensors + 7 days of recorder history.
3. Measured `ble_cancelled_count` over 7 days from
   `state_attributes` joined to `states` for `persons_in_house`.

### RESULT

**The map is NOT empty, the flag is NOT off, and no None guard is swallowing it.
The failure is an AREA-SET DISJOINTNESS: residents are never located in an area a
counting camera covers.**

Sub-results, each independently checked:

1. **Kill switch is ON.** Integration entry options:
   `census_ble_cancel_enabled: True`, `enhanced_census: True`,
   `census_hold_interior: 3.0`, `census_hold_exterior: 5.0`. Not the cause.
2. **`_build_room_to_area_id_map()` is complete.** 39/39 URA room entries carry
   `area_id`; zero missing. Not the cause.
3. **`_ble_home_by_area()` produces a non-empty map.** At probe time all four
   residents were `tracking_status: active` with real room names
   (Ezinne + Oji → Master Bedroom, Jaya → Jaya Bedroom, Ziri → Ziri Bathroom)
   → map = `{master_bedroom: 2, jaya_bedroom: 1, ziri_bathroom: 1}`. Not the cause.
4. **The camera side and the resident side do not intersect.** The 12 configured
   interior cameras (`camera_person_entities`) resolve to exactly 7 areas:

   | camera area | has a URA room mapped to it? | BLE-cancel possible? |
   |---|---|---|
   | `master_hallway` | **no** | never |
   | `entry_way` (foyer fisheye) | **no** | never |
   | `stairs` (stairs_top ×2) | **no** | never |
   | `game_room` (playroom ×2) | yes (Game Room) | yes |
   | `living_room` (family room ×2) | yes (Living Room) | yes |
   | `garage_hallway` (staircase) | yes (Garage Hallway) | yes |
   | `upstairs_hallway` | yes (Upstairs Hallway) | yes |

   **3 of 7 camera areas have no URA room at all**, so no resident can ever be
   BLE-located there — those cameras are structurally un-cancellable.
   Zero interior cameras cover any bedroom or bathroom, which is where residents are.

5. **Even the 4 cancellable areas are almost never occupied by a BLE-located
   resident.** 7 days of `*_location` history, minutes spent in
   {Living Room, Game Room, Garage Hallway, Upstairs Hallway}:

   | person | minutes in a camera-covered room (7d) | share of the 10 080-min week |
   |---|---|---|
   | Ezinne | 3 | 0.03% |
   | Oji | 2 | 0.02% |
   | Jaya | 61 | 0.6% |
   | Ziri | 1 447 (all Game Room) | 14.4% |
   | **total** | **1 513 / 40 320 person-min** | **3.75%** |

6. **Measured outcome:** `ble_cancelled_count > 0` for **0 seconds out of 7 days**
   (`604 800 s` sampled, time-weighted). The subtraction has never fired in the
   recorder-visible history.

### The specific broken link

There are two, and they are different in kind:

- **B1 (structural, dominant):** camera area set ∩ BLE-locatable area set is
  effectively empty. `entry_way`, `master_hallway`, `stairs` have **no URA room**,
  so `_build_room_to_area_id_map()` can never produce those keys. The dedup as
  designed can only cancel a resident standing in a camera-covered *room*, and
  residents spend 3.75% of their time there — 96% of that from one person in one room.
- **B2 (asymmetry, secondary):** `_get_ble_persons()` (`camera_census.py:1951`)
  counts a person as identified when `location` is anything except
  `away`/`unknown`/`""` — **including `home` and `lost`** — while
  `_ble_home_by_area()` (`camera_census.py:2338-2352`) excludes `home`, `lost`, and
  `stale`/`lost` tracking status. So `identified_count` can be 4 on exactly the ticks
  where the cancel denominator is 0. This is by design (the docstring justifies I1),
  but it means the additive formula's positive term is looser than its corrective term.

### CONFIDENCE

**HIGH** for B1 — derived from the live registries + 7 days of location history, and
corroborated by the direct 0-second measurement of `ble_cancelled_count`.
**HIGH** for B2 — read directly from source, both call sites cited.

---

# Q2 — How much of the camera body count is duplication vs genuine bodies?

### METHOD

Recorder, 7 days, all interior Frigate `*_person_count` sensors
(`master_hallway`, `playroom`, `foyer_fisheye`, `family_room`, `staircase`,
`stairs_top`, `upstairs_hall`). Three analyses:
(a) per-camera time-weighted non-zero occupancy and max value;
(b) 60-second resampling of all seven series to count how many cameras were
simultaneously non-zero and what the naive sum was;
(c) contiguous runs of an unchanged non-zero value longer than 1 hour (stuck detection).

### RESULT

Per camera, 7 days:

| sensor | changes | max | non-zero time | % of week | time ≥2 |
|---|---|---|---|---|---|
| master_hallway | 805 | 3 | 2.60 h | 1.6% | 0.13 h |
| family_room | 561 | 3 | 2.10 h | 1.3% | 0.26 h |
| playroom | 234 | 1 | 1.35 h | 0.9% | 0.00 h |
| staircase | 527 | 4 | 1.12 h | 0.7% | 0.06 h |
| upstairs_hall | 280 | 2 | 0.92 h | 0.6% | 0.05 h |
| stairs_top | 177 | 1 | 0.35 h | 0.2% | 0.00 h |
| foyer_fisheye | 51 | 1 | 0.07 h | 0.0% | 0.00 h |

Concurrency (60-s samples, 10 080 minutes):

- cameras simultaneously non-zero: `{0: 9 652 min, 1: 355, 2: 67, 3: 5, 4: 1}`
- naive sum of interior bodies: `{0: 9 652, 1: 339, 2: 72, 3: 12, 4: 2, 5: 1, 6: 1, 7: 1}`

Stuck runs: **zero** unchanged non-zero runs longer than 1 hour on any interior
camera. The D1 stuck-camera watchdog also reports `stuck_cameras: []` live.

### Interpretation

- **The camera body count is NOT chronically inflated.** Interior cameras report
  zero bodies for 95.8% of the week. The naive cross-camera sum reached ≥5 for
  **3 minutes total in 7 days** and ≥3 for 17 minutes.
- **Hypothesis (b) — repeated/stuck detections on one camera — is REJECTED**
  by the run analysis (no >1 h unchanged non-zero run) and by the low per-camera
  duty cycle.
- **Hypothesis (a) — one person across multiple areas — is real but small.**
  73 minutes out of 10 080 had ≥2 cameras non-zero at once; those are the only
  minutes where cross-area summing can double-count at all. Even if *every* such
  minute were the same body, it caps the same-body duplication contribution at
  ~0.7% of the week.
- **The dominant inflation is (c) "something else": the hold/decay tail**, not the
  instantaneous body count. See Q4 — 74.5% of all elevated-census time has
  `camera_unrecognized == 0`.

### Consequence for the D1 clamp

The premise "the D1 clamp is a no-op because the pre-cancel camera body count is
itself inflated" is **not supported**. The pre-cancel body count is small and
short-lived. Clamping the additive total by it would in fact be a *tight* bound —
tighter than today's behaviour — because today's total is dominated by a decayed
peak that no live camera is still asserting. A clamp evaluated against the
**live** body count would cut the tail; a clamp against the **held/peak** body
count would not.

### CONFIDENCE

**HIGH** for the measurements. **MEDIUM** for the same-body-across-areas
attribution — the recorder cannot prove that two simultaneously non-zero cameras
are seeing the same physical person; 73 minutes is an upper bound on that class,
not a measurement of it. Frigate `event`/`tracked_object` IDs would be needed to
resolve it exactly, and that data is not in the HA recorder.

---

# Q3 — Fresh-face defence

### METHOD

Read the two face consumers and compare their constructed entity IDs against the
live entity registry and live state machine.

- `camera_census.py:2736` — per-camera freshness:
  `face_sensor_id = f"sensor.{base_name}_last_recognized_face"` where
  `base_name` is derived from `binary_sensor.<base>_person_occupancy`.
  A fresh hit yields `raw_contribution = max(0, count - 1)` — the "-1".
  Same construction also at `camera_census.py:2383` and `:2416`.
- `camera_census.py:3023` — global identified set:
  `sensor_id = f"sensor.frigate_{person_slug.lower()}_last_camera"`.

Enumerated the live entities with
`ha_eval_template` and `.storage/core.entity_registry`.

### RESULT

**Both lookups resolve to entities that do not exist. The fresh-face defence has
fired ZERO times, and cannot fire in the current deployment.**

1. **Per-camera face sensors are all suffixed `_2`:**
   `sensor.family_room_last_recognized_face_2`,
   `sensor.master_hallway_last_recognized_face_2`,
   `sensor.playroom_last_recognized_face_2`,
   `sensor.foyer_fisheye_last_recognized_face_2`, … (23 in total, platform `frigate`).
   **No un-suffixed `sensor.*_last_recognized_face` entity exists** — direct
   `ha_get_state` on all four interior ones returns `ENTITY_NOT_FOUND`.
   `hass.states.get(face_sensor_id)` therefore returns `None` →
   `face_is_fresh = False` on every camera, every tick → **`raw_contribution = count`
   always**. The `-1` branch at `camera_census.py:2752` is dead code in production.
2. **Per-person `last_camera` sensors mismatch twice over.** Configured
   `tracked_persons = ['person.ezinne', 'person.oji_udezue', 'person.jaya', 'person.ziri']`
   → the code looks for `sensor.frigate_ezinne_last_camera`,
   `sensor.frigate_oji_udezue_last_camera`, etc. Live entities are
   `sensor.frigate_ezinne_last_camera_2`, `sensor.frigate_oji_last_camera_2`,
   `sensor.frigate_jaya_last_camera_2`, `sensor.frigate_ziri_last_camera_2` —
   wrong on the `_2` suffix for all four, **and** wrong on the name for Oji
   (`oji` vs `oji_udezue`). Only `sensor.frigate_default_last_camera` is un-suffixed.
3. **Confirmed downstream:** live `face_recognized_persons: []`, and over 7 days
   `camera_unrecognized` was ≥1 for 317 minutes with **no** observed -1 credit;
   `identified_count` is therefore exactly `len(ble_persons)` at all times.

**Quantified answer to "how many fresh-face subtractions in the last 24-48 h": 0.
Over 7 days: 0.** Not "rarely" — structurally zero.

The `_2` suffix is the classic HA entity-ID collision artefact: the Frigate
integration re-registered these entities while the original IDs were still held.
This is a **deployment/registry** defect that a code-side rename would only paper
over; the durable fix is either to reclaim the un-suffixed IDs in the registry or
to resolve face sensors via the entity registry by unique_id/device rather than by
string construction.

### CONFIDENCE

**HIGH.** Every claim is a live entity-existence check plus a cited source line.

---

# Q4 — Decay/latch asymmetry, quantified

### METHOD

Joined `states` to `state_attributes` for
`sensor.universal_room_automation_persons_in_house` over the full 7-day retention
window (31 423 rows) and computed time-weighted histograms of `total`,
`identified_count`, `unidentified_count`, `camera_unrecognized`, plus per-episode
runs of `unidentified_count > 0`. "Elevation" = census above the true resident
count of 4.

### RESULT — daily elevation

| day | max census | min above 4 | min above 5 | min above 6 |
|---|---|---|---|---|
| 2026-08-10 | 6 | 282 | 45 | 0 |
| 2026-08-11 | 6 | 178 | 47 | 0 |
| 2026-08-12 | 6 | 35 | 3 | 0 |
| 2026-08-13 | 4 | 0 | 0 | 0 |
| 2026-08-14 | 4 | 0 | 0 | 0 |
| 2026-08-15 | 6 | 129 | 20 | 0 |
| 2026-08-16 | **10** | **535** | 208 | 79 |
| **7-day total** | | **1 159 min ≈ 19.3 h** | 323 min | 79 min |

Mean **166 minutes/day above the true resident count**, but the distribution is
extremely skewed: 3 of 7 days had zero elevation and 2026-08-16 alone accounts for
46% of it.

### RESULT — attribution: decay tail vs live camera evidence

Time-weighted over the 7 days:

- `unidentified_count > 0`: **17.21 h**
- of which `camera_unrecognized == 0` at the same instant (i.e. **no camera is
  asserting any unrecognized body — the number is purely the held peak decaying**):
  **12.83 h = 74.5%**
- camera-backed elevation: 4.38 h = 25.5%

Per day (`tail-only` / `camera-backed`, minutes):

| day | unid>0 | tail-only | camera-backed |
|---|---|---|---|
| 08-10 | 164 | 145 | 19 |
| 08-11 | 165 | 144 | 21 |
| 08-12 | 18 | 17 | 1 |
| 08-13 | 0 | 0 | 0 |
| 08-14 | 0 | 0 | 0 |
| 08-15 | 148 | 122 | 26 |
| 08-16 | 538 | 342 | 196 |

43 elevation episodes, 1 033 minutes total. The five longest:

| start | duration | peak unidentified |
|---|---|---|
| 08-16 17:05 | 210 min | 6 |
| 08-16 14:28 | 144 min | 2 |
| 08-16 22:29 | 54 min | 2 |
| 08-15 17:25 | 45 min | 1 |
| 08-16 13:33 | 40 min | 2 |

A 210-minute episode with peak 6 is far longer than `hold 3 min + 6 × 5 min decay
= 33 min` predicts, which is the observable signature of the self-refresh
(`fresh == peak` refreshes `peak_ts`, `camera_census.py:2504-2516`) repeatedly
re-arming during intermittent detections.

### RESULT — identified-side inflation (separate contributor, not decay)

`identified_count` histogram (minutes over 7 d):
`{0: 413, 1: 34, 2: 623, 3: 1 652, 4: 7 087, 5: 265, 6: 6}`.
**`identified_count` exceeded 4 for 271 minutes**, all on 08-10 (150 min),
08-11 (103 min) and 08-12 (17 min) — with only four tracked persons configured and
`face_recognized_persons` provably always empty (Q3). `identified = len(recognized_set)`
where `recognized_set = set(ble_persons) | set(face_recognized)`, so
`person_coordinator.data` carried **more than four person keys** on those days.
This is a distinct defect from decay and is **not addressed by either planned
deliverable**. It is not diagnosable from the recorder (person_coordinator's dict is
not persisted); it needs a live probe when it recurs.

### Sizing the decay fix

Fixing the decay/self-refresh asymmetry addresses **12.83 h of 17.21 h (74.5%)** of
elevated-unidentified time, i.e. roughly **110 min/day** of false elevation on
average, ~**49 min/day** if 08-16 is treated as an outlier. It does **not** address
the 271 minutes of identified-side inflation.

### CONFIDENCE

**HIGH** for the time-weighted numbers (full attribute history, 31 423 rows).
**MEDIUM-HIGH** for the self-refresh attribution: the recorder does not persist
`_peak_house_timestamp`, so "self-refreshed" is inferred from episode duration
greatly exceeding the deterministic hold+decay ceiling, not read directly.
A `peak_refresh_count` diagnostic would make this directly measurable.

---

# Q5 — Exterior census `single_source` (confirmation)

### METHOD

Live `ha_get_state` on the exterior sensor; 7 days of exterior history; live
exterior track-linker sensor.

### RESULT

- `sensor.universal_room_automation_persons_on_property_exterior` = **0**,
  `source_agreement: "single_source"`, `confidence: "medium"` — **confirmed still
  hard-coded**, matching `camera_census.py:1544/1548/1551/1555`.
- Exterior 7-day distribution never exceeded 4; daily maxima were 2–4, dominated by
  0. Present-day (08-16): 1 095 min at 0, 241 min at 1, 68 min at 2.
- The track linker's counter is exposed as
  `sensor.ura_security_coordinator_outside_people_being_tracked` (NOT
  `..._outside_people_being_tracked` under the `universal_room_automation` slug) —
  live value **0**, and it is **not recorded** (`states_meta` has no history for it,
  so no before/after trend is available from the recorder).

**Before-numbers for the planned `census_counts()` swap (2026-08-16 23:19 CDT):**
exterior census = 0, `source_agreement` = `single_source`,
`exterior_person_tracks_active` = 0. Both agree at zero right now, so this baseline
does **not** discriminate the swap — a non-zero re-read is needed at swap time.

### CONFIDENCE

**HIGH** for the confirmation; **LOW** for the baseline's usefulness (both sides
are 0, and the linker sensor has no recorder history to compare against).

---

# Bonus finding (unplanned, discriminating) — guest minutes are mostly NOT census-driven

Not asked, but it changes what the cycle can claim, so it is recorded here.

**METHOD:** extracted every `guest` episode from
`sensor.universal_room_automation_house_state` over 7 days and cross-referenced
each against `unidentified_count` from the census attribute history.

**RESULT:** 17 guest episodes, 1 582 minutes total. **15 of them (≈1 138 min) had
`unidentified_count == 0` for their ENTIRE duration:**

| start | duration | max unidentified during | min with unid>0 |
|---|---|---|---|
| 08-11 12:52 | 22 | 2 | 14 |
| 08-13 06:03 | 8 | 0 | 0 |
| 08-13 06:38 | 180 | 0 | 0 |
| 08-13 18:52 | 95 | 0 | 0 |
| 08-13 21:38 | 94 | 0 | 0 |
| 08-14 06:03 | 76 | 0 | 0 |
| 08-14 08:36 | 57 | 0 | 0 |
| 08-14 12:33 | 45 | 0 | 0 |
| 08-14 14:02 | 172 | 0 | 0 |
| 08-14 17:57 | 39 | 0 | 0 |
| 08-14 21:21 | 106 | 0 | 0 |
| 08-15 06:03 | 107 | 0 | 0 |
| 08-15 08:15 | 126 | 0 | 0 |
| 08-15 14:32 | 9 | 0 | 0 |
| 08-15 19:22 | 17 | 2 | 11 |
| 08-16 13:38 | **422** | 6 | 388 |

Days 08-13 and 08-14 had **zero** elevated-census minutes (Q4 table) yet 384 and
493 minutes of `guest`. `PresenceCoordinator._guest_gate_armed()`
(`presence.py:4886`) short-circuits to False on `unidentified_count <= 0`, so
these episodes must be entered via the second `guest_gate_armed` path (the
guest-room path referenced at `presence.py:1268-1274`) or held by the
guest-exit persistence at `presence.py:1385-1387`.

**Implication for acceptance criteria:** "guest minutes go down" is NOT a
discriminating acceptance criterion for this cycle — 72% of guest time in the
sampled week is not census-caused, and would be unchanged by a perfect census fix.
The discriminating criteria are `unidentified_count>0` minutes with
`camera_unrecognized==0`, and `ble_cancelled_count`.

**CONFIDENCE:** HIGH for the measurement, **LOW** for the mechanism (the second
path was not traced; this needs its own investigation card).

---

# Go / no-go per deliverable

| Deliverable | Verdict | Evidence |
|---|---|---|
| **CENSUS-DECAY-SEPARATION-1** — separate the hold/decay tail from live camera evidence (stop the self-refresh from immortalising a peak) | **GO — strongest-supported item in the cycle** | 12.83 h of 17.21 h (74.5%) of elevated time has `camera_unrecognized == 0`; a 210-min episode against a 33-min deterministic hold+decay ceiling. Fix targets ~110 min/day of false elevation. |
| **CENSUS-DEDUP-REPAIR-1 — per-area BLE-cancel repair** (as scoped: fix the cancel so it fires) | **NO-GO as scoped** | The cancel is not broken in code; the area sets are disjoint. `ble_cancelled_count > 0` for 0 s in 7 days, and residents spend 3.75% of person-minutes in a camera-covered room, 96% of that one person in Game Room. Repairing the subtraction buys ~0. |
| **CENSUS-DEDUP-REPAIR-1 — reframed: area-coverage repair** (map URA rooms to `entry_way` / `master_hallway` / `stairs`, or add those cameras' areas to the room set) | **CONDITIONAL GO — cheap, config-level, do this first** | 3 of 7 camera areas have no URA room, so those cameras are permanently un-cancellable. This is a configuration change, not a build. Measure `ble_cancelled_count` after; if still 0, the whole dedup line is dead. |
| **Fresh-face `-1` defence** | **NO-GO for a code fix; GO for a registry/deployment fix** | Both face lookups target non-existent entity IDs (`_2` suffix on all 23 face sensors and all 4 `frigate_*_last_camera`; plus `oji` vs `oji_udezue`). Zero subtractions in 7 days. Renaming strings in code would re-break on the next Frigate re-registration — resolve via entity registry instead. This is a prerequisite for any "identified" number being trustworthy. |
| **D1 clamp (bound additive total by pre-cancel camera body count)** | **GO, but only if clamped against the LIVE body count** | The premise that the body count is itself inflated is REJECTED: interior cameras read 0 for 95.8% of the week, naive sum ≥5 for 3 min in 7 days, no stuck runs >1 h. A clamp against the live count is tight and would cut the decay tail; a clamp against the held/peak count would be a no-op. |
| **Exterior `single_source` → `census_counts()` swap** | **GO on correctness; baseline is NOT usable as an acceptance oracle** | `single_source` confirmed live. But exterior census = 0 and `exterior_person_tracks_active` = 0 right now, and the linker sensor has **no recorder history** — the two agree trivially. Add the linker sensor to the recorder before the swap, or the before/after comparison cannot discriminate. |
| **`identified_count` > 4 with 4 tracked persons (271 min over 7 d)** | **CANNOT DECIDE — needs new data** | `person_coordinator.data` is not persisted; the recorder cannot show which extra keys existed. Needs a live probe when it recurs. Not covered by either planned deliverable — track separately. |
| **Guest-mode reduction as an acceptance criterion** | **REJECT the criterion** | 15 of 17 guest episodes (≈72% of guest minutes) had `unidentified_count == 0` throughout. A perfect census fix leaves them untouched. |

## Cannot be answered from existing data

1. Whether two simultaneously non-zero cameras are seeing the **same** physical
   person (73 min/7 d upper bound). Needs Frigate tracked-object IDs; not in the
   HA recorder.
2. Whether an elevation episode's peak **self-refreshed** vs decayed, read
   directly. Inferred from episode duration only; needs a `peak_refresh_count` /
   `peak_last_refreshed` diagnostic attribute.
3. The composition of `person_coordinator.data` on the days `identified_count`
   reached 5–6. Not persisted.
4. The mechanism behind the 15 zero-unidentified guest episodes. Requires tracing
   the second `guest_gate_armed` path live.
5. Anything older than **7 days** — `purge_keep_days: 7`. The "7 days" framing in
   the probe brief is exactly the retention limit; there is no margin.
