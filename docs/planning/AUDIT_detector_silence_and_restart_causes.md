# AUDIT: Why D1 and P24 don't fire, and what the 30 restarts actually were

**Date:** 2026-08-09
**Posture:** read-only measurement probe. No writes, no restarts, no service calls, no config
changes. All recorder queries opened `file:...?mode=ro` (URI read-only) and scoped by
`metadata_id`; no unfiltered scan of `states`.
**Follows:** `docs/planning/AUDIT_ledger_golden_fixture_yield.md` (2026-08-09) and kanban card
`WATCHDOG-INERT-1`.
**Operator questions:**
1. *"Some are rare. Not a bad thing. Why don't d1 and p24 fire. That would help."*
2. *"If restarts are us shipping we're ok to keep going. If spurious we should trace."*

---

## Answers in one line each

- **D1 (camera stuck-count): verdict (i) correctly rare, with a latent (ii).** The interior
  candidate set genuinely never produces a long `person_count > 0` hold — p99 across all seven
  interior cameras is ≤ 0.044 h against a 3.0 h threshold. Nothing is structurally blocking it.
  The one camera in the house that *did* hold 6.52 h (`garage_b`) is not configured into URA at
  all, so D1 never saw it — an exclusion that is defensible but worth a decision.
- **P24 (RESILIENCE-001 max-active failsafe): verdict (iii) structurally blind on its main leg.**
  The duration precondition was met **27 times** in 7.3 days. The Tier-1-freshness comparison
  suppressed **27 of 27 (100%)** — and it does so *by construction*, not by luck: the failsafe
  check is unreachable with a stale-but-non-null `_last_motion_time`. The single real firing in
  the window came through the `_last_motion_time is None` branch, not the age comparison.
- **Restarts: 26 in 7.3 days, 26/26 deploy-or-operator-driven, 0 spurious.** Every one is a clean
  `homeassistant_stop` preceded by an explicit `homeassistant.restart` service call. No watchdog
  kill, no OOM, no unclean start, no URA parent-entry reload cascade.

---

## Method and data surfaces

| Surface | Path | Window observed |
|---|---|---|
| HA recorder | `/config/home-assistant_v2.db` (~21 GB, `purge_keep_days: 7`) | 2026-08-02 10:03 → 2026-08-09 17:18 CDT (**7.30 d**) |
| URA DB | `/config/universal_room_automation/data/universal_room_automation.db` | `notification_log` 2026-07-26 → 2026-08-09 (14 d) |
| Config | `/config/.storage/core.config_entries` | live |
| Repo | `git log --all` on `develop` | 2026-08-01 → 2026-08-09 |

Host timezone is **CDT (UTC-5)** (`ssh ha date` → `Sun Aug 9 17:11:04 CDT 2026`). All wall-clock
times in this document are CDT unless suffixed UTC. `notification_log.timestamp` is stored in UTC.

**Correction to the prior audit's restart count.** `AUDIT_ledger_golden_fixture_yield.md` reported
"30 restarts, 2.5 h median gap, longest uptime 1.02 d" using a heuristic (clusters of ≥50
`old_state_id IS NULL` rows within 3 min). The authoritative surface is the `events` table:
`homeassistant_stop` / `homeassistant_started` (`event_types` ids 17 / 10). It gives **26 restarts,
3.50 h median inter-restart gap, longest uptime 24.32 h (1.01 d)**. The heuristic over-counted by
4 because a config-entry reload also re-adds entities with `old_state_id IS NULL`. The
*conclusions* of the prior audit are unaffected — max uptime is still under D3's 2.0-day threshold.

---

# INVESTIGATION A — why D1 and P24 don't fire

## D1 — camera stuck-count

### What the code actually does

`CameraCensus._watchdog_stuck_cameras` (`camera_census.py:1948`). Candidate set and gates, read
from source:

| Step | Site | Effect |
|---|---|---|
| Boot-settle gate | `camera_census.py:1970` (`_d1_boot_settle_done`, defined `camera_census.py:2136`) | no verdicts until presence releases boot-settle |
| Candidate set | `camera_census.py:1978` → `_get_interior_camera_entities` (`camera_census.py:1787`) → `_get_integration_camera_list` (`camera_census.py:1803`) | **`CONF_CAMERA_PERSON_ENTITIES` on the integration entry only.** Perimeter and egress cameras are NOT scanned. |
| Platform filter | `camera_census.py:1998-2000` | non-Frigate cameras skipped |
| Sensor filter | `camera_census.py:2001-2003` | camera must expose a `person_count_sensor` |
| Availability | `camera_census.py:2005-2010` | `unavailable`/`unknown` pops the stuck record |
| Zero reset | `camera_census.py:2019-2023` | any `count <= 0` pops the record |
| Rule A "unchanged" | `camera_census.py:2055` | `hours >= CONF_STUCK_CAMERA_HOURS` (`const.py:3098-3099`, default **3.0 h**) |
| Rule B "never_zero" | `camera_census.py:2054` | `nonzero_hours >= STUCK_CAMERA_NEVERZERO_HOURS` (`const.py:3143`, **6.0 h**) |
| Corroboration | `camera_census.py:2063-2070` | `int(ble_here>0) + int(room_tier>0) >= CONF_STUCK_CAMERA_INTERIOR_TIERS_REQUIRED` (`const.py:3101-3104`, default 1) → no NM, no discount |
| Safety rails | `camera_census.py:2072-2087` | `area_id is None` → notify-only; area with no configured interior tier → notify-only. **Neither rail suppresses the NM** — the NM fires regardless of the discount decision (`camera_census.py:2117-2124`). |

**So the safety rails the v5.35.0 README describes cannot explain D1's silence.** They gate the
*census discount*, not the notification. The only things that can suppress an NM are: not being in
the candidate set, not being Frigate, availability/zero resets, the window never maturing, or
corroboration being present.

### Live candidate set

`camera_person_entities` on the integration entry (read from `core.config_entries`):

```
camera.playroom_high_resolution_channel, camera.master_hallway,
camera.staircase_high_resolution_channel, camera.playroom, camera.foyer_fisheye,
camera.family_room, camera.family_room_high_resolution_channel,
camera.foyer_fisheye_high_resolution_channel, camera.master_hallway_high_resolution_channel,
camera.upstairs_hall_high_resolution_channel, camera.stairs_top_high_resolution_channel,
camera.stairs_top_2
```

That resolves to seven distinct interior `*_person_count` sensors: playroom, master_hallway,
staircase, foyer_fisheye, family_room, upstairs_hall, stairs_top.

### Measured distribution of `person_count > 0` holds

Probe: for each of the 23 `sensor.%person_count` metadata_ids, replay the full state series and
extract (a) **never-zero episodes** — continuous runs with `count > 0` across value changes, which
is exactly Rule B's `nonzero_since` window; (b) **unchanged-value runs** — Rule A's `since` window.
Percentiles over episodes, hours.

**Interior candidate set (what D1 actually scans):**

| interior camera | rows | episodes | p50 | p90 | p99 | max never-zero | max unchanged |
|---|---:|---:|---:|---:|---:|---:|---:|
| staircase | 599 | 258 | 0.003 | 0.011 | 0.031 | **0.27 h** | 0.27 h |
| foyer_fisheye | 79 | 10 | 0.016 | 0.082 | 0.137 | 0.14 h | 0.14 h |
| upstairs_hall | 430 | 166 | 0.004 | 0.013 | 0.044 | 0.11 h | 0.07 h |
| master_hallway | 779 | 318 | 0.004 | 0.010 | 0.038 | 0.11 h | 0.11 h |
| family_room | 172 | 56 | 0.004 | 0.020 | 0.035 | 0.08 h | 0.08 h |
| stairs_top | 209 | 75 | 0.002 | 0.005 | 0.037 | 0.04 h | 0.04 h |
| playroom | 59 | **0** | — | — | — | 0.00 h | 0.00 h |

**Non-candidate cameras (perimeter / egress / unconfigured), for contrast:**

| camera | episodes | p90 | max never-zero | in URA config? |
|---|---:|---:|---:|---|
| **garage_b** | 3 | 6.524 | **6.52 h** | **NO — not in any list** |
| front_side_ptz | 452 | 0.125 | 3.49 h | perimeter |
| back_yard | 388 | 0.165 | 2.97 h | perimeter |
| armcrestash41b | 38 | 0.065 | 0.96 h | perimeter |
| garage_a | 41 | 0.022 | 0.70 h | **NO — not in any list** |

### Verdict: **(i) correctly rare** — with one configuration question

- The interior p99 is **0.044 h (2.6 min)**; the interior max is **0.27 h**. The nearer threshold
  (3.0 h) is **11× above the observed maximum** and **~68× above p99**. No interior camera came
  within an order of magnitude in 7.3 days.
- There is no gating precondition blocking it. Boot-settle clears within minutes of each start;
  the seven candidates are all Frigate with live `person_count` sensors and produced 883 non-zero
  episodes between them. D1 is *running and evaluating* — it simply never saw a long hold.
- **Re-thresholding is not justified on this data.** Fitting the threshold to the observed
  distribution would put it at ~0.3-0.5 h, which is *below plausible legitimate occupancy* (a
  person standing in a hallway or sitting in the family room for 30 min is normal), so a
  re-thresholded D1 would fire on real people and be suppressed only by the corroboration check.
  The 3.0 h / 6.0 h pair is a deliberately conservative "this is impossible for a real body"
  bound, and it is behaving as such. **Working as intended — leave the thresholds alone.**
- **Secondary (does not change the verdict): D1's book is in-memory and restart-resets.**
  `self._camera_stuck_state` (`camera_census.py:1004`) does not persist. With a median uptime of
  3.43 h (see Investigation B), a 3.0 h unchanged window fits inside only about half the uptime
  segments and the 6.0 h never-zero window fits inside 8 of 26. If the observed distribution were
  anywhere near the threshold this would matter a great deal; at a 0.27 h maximum it is currently
  moot. It becomes the binding constraint the moment a real stuck camera appears during a
  deploy-heavy day, and it is the same defect `STUCK-SENSOR-1` flagged.

### The `garage_b` question — why it isn't in the interior set

`sensor.garage_b_person_count` held `> 0` continuously for **6.52 h** (3 episodes, 64 rows), which
would have crossed *both* D1 rules. It did not fire because **`camera.garage_b` is not configured
into URA in any capacity** — it appears in neither `camera_person_entities` (interior), nor
`perimeter_cameras`, nor `egress_cameras` on the integration entry. The same is true of
`camera.garage_a`. So the exclusion is not "garage is perimeter, D1 correctly skipped it" — it is
"the garage cameras are unconfigured, and D1 only reads the interior list."

Is that correct? Two separate judgements:

1. **D1's scope (interior-only) is correct as designed.** D1's purpose is to protect the *house
   census* from a phantom interior body. The discount it applies feeds
   `_calculate_house_census`; perimeter and egress counts do not feed that tally the same way, so
   widening D1's scan to them would produce notifications with no corresponding safety value —
   and would immediately start firing on `front_side_ptz` (3.49 h) and `back_yard` (2.97 h), which
   are outdoor cameras where a parked car or a shadow legitimately holds a detection for hours.
   Widening D1 to perimeter would convert a silent detector into a noisy one.
2. **Whether `garage_b` should be configured at all is an open operator decision,** not a D1
   defect. It is a *garage* — an interior-adjacent space with an actual URA room ("Garage B" is a
   configured room, see the P24 table below). A 6.52 h stuck person count on a camera in a room
   URA manages is exactly the failure D1 exists to catch, and today nothing looks at it. **This is
   the single actionable finding for D1: not a threshold change, a coverage gap.**

---

## P24 — RESILIENCE-001 max-active failsafe

### What the code actually does

`RoomCoordinator._async_update_data`, `coordinator.py:2398-2470`:

```
if (data.get(STATE_OCCUPIED) and self._became_occupied_time):        # 2417-2418
    duration = (now - self._became_occupied_time).total_seconds()    # 2419
    if duration > failsafe_seconds:                                  # 2421
        signal_stale = True
        if self._last_motion_time:                                   # 2424
            signal_age = (now - self._last_motion_time).total_seconds()
            if 0 <= signal_age < 2 * self._occupancy_timeout:        # 2437
                signal_stale = False                                 # 2438
        if signal_stale: ...fire...                                  # 2439
```

`failsafe_seconds` from `_get_failsafe_duration_seconds` (`coordinator.py:517`) →
`ROOM_TYPE_FAILSAFE_DURATIONS` (`const.py:900-903`): closet/bathroom 3600 s, everything else
`DEFAULT_FAILSAFE_DURATION_SECONDS` = 14400 s (`const.py:899`).

NM emit: `_fire_max_active_failsafe_nm` (`coordinator.py:201`) → `fire_stuck_signal` with
`key=(room_name,)`, per-day latched (`domain_coordinators/_stuck_signal_nm.py:47`).

### Measurement — the two legs, from production's own variables

The room's `binary_sensor.<slug>_occupied` persists the exact coordinator internals in its
attributes (`binary_sensor.py:383-388`): **`became_occupied_time`**, **`last_motion`**,
**`failsafe_fired`**, `occupancy_source`. That is the authoritative surface — no model, no
re-simulation. Probe: for all 40 URA `_occupied` sensors, join `states` → `state_attributes`
scoped by `metadata_id` (736,553 attribute rows scanned), and for every `state='on'` row compute
`duration = last_updated_ts - became_occupied_time` and `signal_age = last_updated_ts -
last_motion`, then de-duplicate crossings by session (`became_occupied_time`).

| room | type | failsafe (min) | timeout (s) | max session (h) | **Leg 1: crossings** | **Leg 2: stale at crossing** | actual fires |
|---|---|---:|---:|---:|---:|---:|---:|
| Living Room | common_area | 240 | 300 | 9.76 | 6 | 0 | 0 |
| Garage B | garage | 240 | 300 | 24.25 | 6 | 0 | 0 |
| Patio | common_area | 240 | 300 | 15.01 | 5 | 0 | **1** |
| Master Bedroom | bedroom | 240 | 300 | 12.95 | 4 | 0 | 0 |
| Game Room | common_area | 240 | 540 | 6.64 | 2 | 0 | 0 |
| Ziri Bedroom (Bedroom 5) | bedroom | 240 | 500 | 5.26 | 2 | 0 | 0 |
| Ziri Bathroom | bathroom | 60 | 540 | 1.10 | 2 | 0 | 0 |
| **TOTAL** | | | | | **27** | **0** | **1** |

**Leg 1 is met often: 27 duration crossings across 7 rooms in 7.3 days (~3.7/day).**
**Leg 2 suppressed 27 of 27 (100%).**

### Why leg 2 suppresses everything — and why that is structural, not statistical

Trace the tick. By the time control reaches line 2418, `data[STATE_OCCUPIED]` and
`_became_occupied_time` have already been set by the occupancy block at `coordinator.py:2326-2384`:

- **`grace_hold` branch (`coordinator.py:2326-2330`):** holds the previous occupancy. Does *not*
  refresh `_last_motion_time`, does *not* clear `_became_occupied_time`.
- **`any_sensor_active` branch (`coordinator.py:2331-2352`):** sets `self._last_motion_time = now`
  (`coordinator.py:2332`). **`signal_age == 0` → always fresh → always skipped.**
- **`else` / timeout branch (`coordinator.py:2353-2384`):** occupancy survives only while
  `elapsed < self._occupancy_timeout`. So if `STATE_OCCUPIED` is True here,
  **`signal_age < occupancy_timeout < 2 * occupancy_timeout` → always fresh → always skipped.**
  And the moment `elapsed >= occupancy_timeout`, `STATE_OCCUPIED` goes False *and*
  `_became_occupied_time` is set to `None` (`coordinator.py:2373`, `2384`) — so the failsafe guard
  at 2418 is False.

**Therefore the `signal_age` comparison at `coordinator.py:2437` can never evaluate to stale.**
Any path that reaches 2418 with `STATE_OCCUPIED=True` and a non-null `_last_motion_time` has, by
construction, an age below the room's `occupancy_timeout`, which is strictly below the `2 ×
occupancy_timeout` staleness bound. The 27/27 suppression is not a distribution fact — it is a
theorem about the code.

The failsafe is only reachable via:
- **`self._last_motion_time is None` while occupied** (line 2424 falsy → `signal_stale` stays
  True). Reached through the `grace_hold` branch, or through a post-restart restore.
- Negative `signal_age` (clock skew, `coordinator.py:2437`'s `0 <=` guard).

Separately, occupancy held by the **camera override (`coordinator.py:2484-2495`)** or the **BLE
hold (`coordinator.py:2589-2600`)** can never accumulate failsafe duration at all: both run
*after* the failsafe check and both re-seed `self._became_occupied_time = now` when the sensor
path had just cleared it. Ziri Bathroom is the visible fingerprint — the recorder shows
`binary_sensor.ziri_bathroom_occupied` `on` for a 10.79 h stretch on 08-06, yet its
`became_occupied_time` attribute never shows a session longer than **1.10 h**, because the timer
was reset on every tick that the single Tier-1 sensor was quiet and BLE/camera re-asserted.

### The one real firing confirms the mechanism

`notification_log` id 2930, `2026-08-06T00:24:42.373467+00:00` = **08-05 19:24:42 CDT**,
`title = "Stuck signal: max_active_failsafe"`. The matching attribute row on
`binary_sensor.patio_occupied` at `19:24:42.368956`:

```json
{"last_motion":null,"timeout":0,
 "became_occupied_time":"2026-08-05T04:21:17.312051-05:00",
 "failsafe_fired":true,"occupancy_source":"failsafe", ...}
```

Session length 15.06 h against a 4 h limit — and **`last_motion` is `null`**. It fired through the
`_last_motion_time is None` branch, not the age comparison. The trigger is visible in the sensor
stream: `binary_sensor.occupancy_lux_temp_humidity_hobeian_patioleft_presence` went `unavailable`
at **19:24:40**, two seconds before the fire — i.e. sensor unavailability → `grace_hold` → held
occupancy with a null motion timestamp → failsafe. (The other Patio sensor,
`..._patioright_presence`, is a textbook duty-cycle flapper: 1,798 rows in 17 h, toggling
on/off every ~42 s. It is a D2 target in its own right.)

### Verdict: **(iii) structurally blind on its main leg**

The operator asked for the split, and here it is: **duration precondition met 27 times; freshness
skip suppressed 27 of 27; the only firing came through a different branch entirely.** This is not
"working as designed with a low rate" — the v4.5.16 freshness gate is not *filtering* the common
case, it is *swallowing every case the age comparison can see*, because the comparison bound
(`2 × occupancy_timeout`) is strictly wider than the window in which the guarding condition
(`STATE_OCCUPIED and _became_occupied_time`) can hold.

What P24 currently detects is: **"a room was held occupied through `grace_hold` (sensor
unavailability) or a restart-restore for longer than its failsafe limit, with no motion timestamp
at all."** That is a real and useful condition — it caught a genuine 15-hour Patio hold — but it is
a much narrower condition than "stuck sensor holding a room occupied," which is what
RESILIENCE-001 was built for and what the NM text claims ("Tier-1 signal stale").

**This is not a threshold problem, so there is no threshold to recommend.** No value of the
staleness multiplier fixes it: at `k × occupancy_timeout` with `k <= 1` the gate becomes a no-op
(the failsafe fires on every crossing, including the 27 legitimately-occupied ones); at `k > 1`
it is unreachable as shown. Options, for operator decision — all out of scope for this read-only
audit:

- **A — move the check.** Evaluate the failsafe *after* the camera/BLE overrides
  (`coordinator.py:2495` / `2600`) and stop those overrides from re-seeding
  `_became_occupied_time` when a session is already in progress. That makes "held occupied for
  4 h by BLE/camera with no Tier-1 corroboration" reachable, which is the class Ziri Bathroom
  (10.79 h) and Garage B (24.25 h max session) actually exhibit.
- **B — re-base the freshness test on `_last_pir_motion_time`** (`coordinator.py:2340`), which is
  deliberately *not* refreshed by mmWave or occupancy-sensor branches, so it can genuinely go
  stale while a room is occupied. This is the smaller change and matches the "Tier-1 stale" text.
- **C — accept the narrowed semantics** and rewrite the NM diagnosis to say what it means
  ("held occupied with no motion timestamp"), then stop counting P24 as a stuck-sensor detector.

Whichever is chosen, **the NM row should carry the room name.** Today the persisted
`notification_log` row has `message = "[audit]"` and `location = "max_active_failsafe"` — the
`diagnosis` string built at `coordinator.py:210-214` (which does contain the room) is not what
lands in the table. Identifying the firing room required a recorder attribute join. That is a
gap in the ledger surface independent of the detector.

---

## Investigation A summary

| Detector | Verdict | Guarded condition occurs? | Threshold vs observation | Action |
|---|---|---|---|---|
| **D1** camera stuck-count | **(i) correctly rare** | No — interior p99 0.044 h, max 0.27 h | 3.0 h = 11× the observed max; conservative by design | **Leave thresholds.** Decide whether `camera.garage_b` / `camera.garage_a` (6.52 h / 0.70 h holds, unconfigured in URA) should be brought into coverage. Note in-memory book vs 3.43 h median uptime as a latent constraint. |
| **P24** max-active failsafe | **(iii) structurally blind** (main leg) | Yes — 27 duration crossings in 7.3 d | Freshness gate suppressed 27/27, provably not statistically | Not a threshold fix. Operator decision A / B / C above. Also: persist the room name in the NM row. |
| *(D3 frozen tracker, prior audit)* | *(iii) structurally unreachable* | — | 2.0 d threshold vs 1.01 d max uptime — **re-confirmed here**, max uptime 24.32 h | unchanged from `AUDIT_ledger_golden_fixture_yield.md` |

---

# INVESTIGATION B — are the 30 restarts ours, or spurious?

## Method

The prior audit's 30 was a heuristic. The authoritative surface is the recorder `events` table:

```sql
select e.time_fired_ts, et.event_type
  from events e join event_types et on et.event_type_id = e.event_type_id
 where et.event_type in ('homeassistant_start','homeassistant_started','homeassistant_stop')
 order by 1;
```

→ **26 `homeassistant_stop`, 26 `homeassistant_start`, 26 `homeassistant_started`**, perfectly
interleaved. Window 2026-08-02 10:03:01 → 2026-08-09 17:18 CDT (**7.30 d**, bounded by
`purge_keep_days: 7`).

Each stop was then correlated with (a) `call_service` events in the preceding 300 s, joined
through `event_data.shared_data`, and (b) URA deploy commits
(`git log --all --pretty='%ad|%s'`, filtered to `^v5\.\d+\.\d+:`).

## Per-restart classification

Downtime = stop → next `homeassistant_started`. "Deploy" = a URA release commit within ~90 s
before the stop.

| # | Stop (CDT) | Down | Preceding service call | Correlated release | Classification |
|---:|---|---:|---|---|---|
| 1 | 08-02 10:03:01 | 5.1 m | `homeassistant.restart` | v5.47.0 (10:01:00) | deploy |
| 2 | 08-02 10:18:52 | 4.6 m | `homeassistant.restart` | v5.47.1 (10:18:30) | deploy |
| 3 | 08-02 10:32:37 | 9.9 m | `homeassistant.restart` | v5.47.2 (10:32:16) | deploy |
| 4 | 08-03 11:01:59 | 5.7 m | `homeassistant.restart` | v5.48.0 (11:01:30) | deploy |
| 5 | 08-03 13:09:27 | 5.1 m | `homeassistant.restart` | v5.49.0 (13:08:15) | deploy |
| 6 | 08-03 16:40:43 | 5.6 m | `homeassistant.restart` | v5.50.0 (16:40:13) | deploy |
| 7 | 08-03 16:51:33 | 2.6 m | `homeassistant.restart` | v5.50.1 (16:48:28) + v5.50.2 (16:51:09) | deploy (two releases, one restart) |
| 8 | 08-04 04:13:18 | 13.2 m | `homeassistant.restart` | v5.51.0 (04:12:41) | deploy |
| 9 | **08-04 20:09:21** | 5.6 m | `homeassistant.restart` | **none** | **operator / agent manual restart** |
| 10 | 08-05 03:25:00 | 4.6 m | `homeassistant.restart` | v5.51.1 (03:24:13) | deploy |
| 11 | 08-05 19:22:21 | 4.8 m | `homeassistant.restart` | v5.52.0 (19:21:52) | deploy |
| 12 | 08-06 14:32:57 | 5.0 m | `homeassistant.restart` | v5.53.0 (14:32:30) | deploy |
| 13 | 08-06 18:03:08 | 5.2 m | `homeassistant.restart` | v5.54.0 (18:01:12) | deploy |
| 14 | 08-06 18:10:40 | 13.0 m | `homeassistant.restart` | v5.55.0 (18:10:14) | deploy |
| 15 | 08-06 19:41:12 | 9.5 m | `homeassistant.restart` | v5.56.0 (19:40:05) | deploy |
| 16 | 08-06 22:11:44 | 4.8 m | `homeassistant.restart` | v5.57.0 (22:11:18) | deploy |
| 17 | 08-06 22:19:51 | 10.0 m | `homeassistant.restart` | v5.58.0 (22:19:21) | deploy |
| 18 | 08-07 00:46:43 | 5.1 m | `homeassistant.restart` | v5.58.1 (00:46:16) | deploy |
| 19 | 08-07 07:17:35 | 4.7 m | `homeassistant.restart` | v5.59.0 (07:17:06) | deploy |
| 20 | 08-07 14:40:04 | 5.2 m | `homeassistant.restart` | v5.60.0 (14:39:26) | deploy |
| 21 | 08-07 20:09:08 | 9.9 m | `homeassistant.restart` | v5.61.0 (20:08:40) | deploy |
| 22 | 08-08 08:15:40 | 4.5 m | `homeassistant.restart` | v5.62.0 (08:15:06) | deploy |
| 23 | 08-08 09:16:00 | 5.2 m | `homeassistant.restart` | v5.62.1 (09:15:37) | deploy |
| 24 | 08-08 09:57:49 | 4.7 m | `homeassistant.restart` | v5.62.2 (09:57:22) | deploy |
| 25 | 08-08 14:36:33 | 8.2 m | `homeassistant.restart` | v5.63.0 (14:35:55) | deploy |
| 26 | 08-08 17:58:52 | 13.1 m | `homeassistant.restart` | v5.64.0 (17:58:25) | deploy |

### Restart #9 (08-04 20:09:21) — the only non-deploy

Not unexplained: the recorder holds the initiating call.

```
20:09:21 call_service {"domain":"homeassistant","service":"restart","service_data":{}}
20:09:58 service_registered {"domain":"hassio",...}      # supervisor re-registering on boot
```

A bare `homeassistant.restart` with empty `service_data`, followed by a clean stop and a normal
5.6 min boot. No `update.install`, no `hassio.addon_restart`, no `hassio.host_reboot`, no HACS
call in the preceding 5 minutes. This is a **deliberate manual restart** with no URA release
attached — consistent with a session doing a reload-by-restart. It is *ours*, just not a ship.

## Negative findings — what did NOT happen

- **No unclean starts.** All 26 `homeassistant_start` events are preceded by a matching
  `homeassistant_stop`. A watchdog kill, an OOM, or a hard host reboot produces a start with no
  stop. There are zero.
- **No watchdog signature.** Downtimes are 2.6-13.2 min, clustered at ~5 min — the normal
  HAOS core-restart cycle. The documented parent-reload watchdog incident produces a ~5 min
  *outage* with an **unclean** restart; none of these are unclean.
- **No URA parent-entry reload cascade.** Only five `homeassistant.reload_config_entry` calls
  exist in the entire 7.3-day window, and **none** targets a URA entry:
  - `01KNYRAGVP5XESS6N8PD6BVQP2` = `enphase_envoy` "Envoy 482543015950" — 08-03 12:01:31,
    08-04 17:23:52, 08-04 20:19:05, 08-04 21:22:22
  - `01JT961TYPVMK7XKACN7GDY0QW` = `esphome` "ratgdov2.5i dbfe2a" — 08-08 22:20:20

  None precedes a restart (08-04 20:19:05 is *after* restart #9; 08-08 22:20:20 is followed by no
  restart in-window). **The parent-reload watchdog hazard did not fire in this window.**
- **No Core / OS / add-on update restarts.** No `update.install` or `hassio.*` restart/reboot
  service call appears within 5 minutes of any stop.
- **No HACS-download restart distinguishable as its own event.** HACS downloads happen inside the
  deploy flow (`scripts/deploy.sh` → HACS → `homeassistant.restart`); they are folded into the 25
  deploy restarts rather than appearing separately.

## Uptime statistics (corrected)

```
n = 26 uptime segments
median  3.43 h      mean 6.63 h      max 24.32 h (1.01 d)
median inter-restart gap 3.50 h
segments: 0.18 0.15 24.32 2.03 3.44 0.09 11.32 15.72 7.17 15.88 19.10 3.42 0.04
          1.29 2.35 0.05 2.28 6.43 7.30 5.40 11.94 0.93 0.61 4.57 3.24 23.10
```

Two segments under 4 minutes (0.04 h, 0.05 h) are back-to-back deploy pairs (v5.54.0→v5.55.0 at
18:03/18:10 and v5.57.0→v5.58.0 at 22:11/22:19).

## Verdict

**26 restarts in 7.30 days. 25 deploy-driven (a 24-release train from v5.47.0 to v5.64.0), 1
operator-initiated manual restart. 0 spurious. 0 watchdog. 0 unclean. 0 URA-caused.**

Per the operator's own rule — *"If restarts are us shipping we're ok to keep going"* — **we are
shipping. Keep going.** The restart cadence is a direct function of release velocity, not of
instability.

The one thing that *is* worth carrying forward: this cadence is what makes **D3 unreachable**
(2.0 d threshold vs 1.01 d max uptime, re-confirmed) and what makes **D1's in-memory 3.0/6.0 h
windows fragile**. That is a detector-design consequence of a healthy deploy rate, not a reason to
slow the deploy rate. The fix belongs in the detectors (persist the tallies), which is exactly
option **FIX** on card `WATCHDOG-INERT-1`. The card's `separate_ops_concern` line — *"30 HA
restarts in 7.46 days is a red flag independent of this card"* — should be amended: the count is
26, and it is not a red flag. It is a deploy log.

---

## Limitations

- The recorder window is **7.30 days** (`purge_keep_days: 7`). Restarts, camera holds, and
  occupancy sessions before 2026-08-02 10:03 are not observable. The URA `notification_log`
  reaches back to 2026-07-26, but the stuck-signal detectors' first row is **2026-08-03T14:49 UTC**
  — v5.35.0's NM surface only has ~6 days of history, not 14. Firing counts quoted from that
  surface are floors, and additionally floor-limited by the per-day dedup latch
  (`_stuck_signal_nm.py:47`).
- P24 leg-2 measurement samples `last_motion` at the cadence the recorder wrote attribute rows,
  not at the 30 s coordinator tick. Since the finding is a code-reachability argument (27/27 plus
  a proof from `coordinator.py:2331-2384`), sampling density does not change it.
- D1's corroboration inputs (`_ble_home_by_area`, `_room_tier_corroboration_by_area`) are per-tick
  URA-derived state and are not recorded, so the corroboration *decision* was not replayed. It is
  moot here: no interior camera's window ever opened, so corroboration was never consulted.
- The five URA rooms with no `binary_sensor.<slug>_occupied` in the recorder (Guest Bedroom 1
  Bathroom, Guest Bedroom 2, Jaya Bedroom, Media, Master Bath Toilet) are excluded from the P24
  crossing count. Cause not determined here (recorder exclusion or slug mismatch); their omission
  can only make the 27 a floor.
- Deploy correlation uses **commit** timestamps, not HACS-download timestamps. The two are within
  ~30 s of each other for every matched restart, which is why the mapping is unambiguous, but a
  download log was not independently consulted.
