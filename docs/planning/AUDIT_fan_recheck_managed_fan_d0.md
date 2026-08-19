# D0 Verification — Fan-Recheck Managed-Fan Gate (card FAN-RECHECK-NOT-CLEARING-1)

**Date:** 2026-08-18
**Scope:** Read-only (code + live). Gates whether the fan-recheck veto-scoping
fix is worth building. NO code modified.
**Question gated:** `_enter_paused` bails `no_managed_fan` if `FanController`
doesn't manage the room's fan — in which case fixing the sleep/guest veto would
not actuate and we'd build the wrong thing.

---

## Q1 — Does `FanController` MANAGE these two fans?

### How the managed set is determined
`FanController` (`domain_coordinators/hvac_fans.py:320`) holds its managed rooms
in `self._room_fans` (`:340`), populated by `discover_fans()` (`:364`). A room is
registered as managed iff ALL of:

1. Its config entry is `ENTRY_TYPE_ROOM` (`hvac_fans.py:380`), AND
2. `room_name in room_to_zone` — i.e. the room belongs to a **discovered HVAC
   zone** (`room_to_zone` built from `zone_manager.zones[].rooms`,
   `hvac_fans.py:373-376`, gate at `:384`), AND
3. `merged[CONF_FANS]` is a non-empty list (`hvac_fans.py:388-397`).

The recheck bail traces as: `_enter_paused` → `self._fan_pause` →
`fan_controller.pause_for_recheck` (`presence_fan_recheck.py:612, 1038-1045`) →
`pause_for_recheck` → `snapshot_room_fan(room_name)`
(`hvac_fans.py:1851`). `snapshot_room_fan`/`pause_for_recheck` return **None iff
`room_name` is not in `self._room_fans`** — that None is what surfaces as
`snapshot is None` → the `no_managed_fan` cancel row
(`presence_fan_recheck.py:613-638`).

### Live room configs (`/Users/okosisi/ha-config/.storage/core.config_entries`, `domain==universal_room_automation`, `entry_type==room`)

| Room | `fans` (CONF_FANS) | Matches target Dreo id? | `zone` | `room_type` | `fan_sleep_policy` |
|---|---|---|---|---|---|
| **Study A** | `['fan.polyfan_dreo704s_wifi_studya']` | ✅ EXACT | `Master Suite` | `generic` | `reduce` |
| **Living Room** | `['fan.towerfan_dreopilotmaxs_wifi_livingroom']` | ✅ EXACT | `Entertainment` | `common_area` | (none → default) |

Both rooms carry a `climate_entity`
(`climate.thermostat_bryant_wifi_studyb_zone_1`) and a `zone`, and both expose
live HVAC/fan URA entities (see Q2) — i.e. both are members of a discovered HVAC
zone, satisfying condition (2). Condition (1) and (3) are satisfied by the table
above (both are `entry_type==room` with a single-element non-empty `fans` list
whose id EXACTLY matches the target Dreo entity).

### Live corroboration
- `fan.polyfan_dreo704s_wifi_studya` = **on** (last_changed 2026-08-18 21:17:43)
- `fan.towerfan_dreopilotmaxs_wifi_livingroom` = **on** (last_changed 21:35:07)
- `binary_sensor.living_room_hvac_cooling` = **on** — the room is present in the
  HVAC-zone coordinator surface, confirming HVAC-zone membership.

### VERDICT — Q1

| Room | Managed? | Recheck `no_managed_fan` bail fires? | Fix will actuate? |
|---|---|---|---|
| **Study A** | ✅ MANAGED | ❌ No | ✅ YES — fix actuates as-is |
| **Living Room** | ✅ MANAGED | ❌ No | ✅ YES — fix actuates as-is |

Both fans are managed by `FanController`. The `no_managed_fan` bail does NOT fire
for either room. The veto-scoping fix is **NOT moot** — it will actuate.

---

## Q2 — WHY are these non-bedroom fans running during sleep?

### Driver = URA comfort-fan logic (occupancy + temperature), NOT a bedroom trust hold
The comfort-fan actuation lives in `FanController._evaluate_temp_fan`
(`hvac_fans.py:1154`). Relevant gates for a NON-bedroom room:

- **Night-trust HOLD/ACTIVATE block (`:1205-1209`) is BEDROOM-ONLY** —
  guarded by `room_fan.room_type == ROOM_TYPE_BEDROOM`. Study A is `generic`,
  Living Room is `common_area` (`const.py:421,428,427`). **Neither qualifies**, so
  this block does not touch them.
- Because they skip the bedroom block, they fall straight to the ordinary
  **occupancy gate** (`:1254-1257`): fan may run iff `occupied` is True; if not
  occupied and off, return `(False,"",0)`. There is **no `house_state`/sleep
  suppression for non-bedroom rooms** in this path — an occupied warm non-bedroom
  room turns/keeps the comfort fan on at `sleep` exactly as it would at `home_day`.
- The only sleep effect on non-bedrooms is a **speed cap** at
  `_apply_sleep_policy` (`:1101-1116`): the cap is in scope only when
  `house_state == "sleep"` OR the room is a bedroom (`:1103-1106`). So at `sleep`
  a `reduce`-policy non-bedroom (Study A) is capped to LOW but **still runs**;
  it is never forced off here.
- `FAN_TRUST_STATES = ("home_night","sleep","waking")`
  (`hvac_const.py:645`).

The display sensor `binary_sensor.living_room_fan_should_run` (comfort view:
`binary_sensor.py:808-817`, `is_on = occupied AND temp >= fan_temp_threshold`) is
NOT the actuator — actuation is `_evaluate_temp_fan`, which additionally holds a
running fan through a vacancy timer (`:1259-1264`, common_area hold = 900 s,
`const.py:1165`). (Live: `living_room_fan_should_run` read **off** at 22:24 while
the fan stayed **on** — consistent with a vacancy/min-runtime hold on an
already-running fan, not a fresh comfort activation.)

### The false-presence → fan → mmWave-shake feedback loop

**Study A history:** fan latched on at 21:17:43, exactly **1 s after its mmWave
went on** (occupancy → comfort fan). Study A's presence substrate includes
`mmwave_sensors` (per live config). Trace:

1. mmWave asserts presence → room `occupied = True`.
2. `_evaluate_temp_fan` occupancy gate passes; warm room → comfort fan ON
   (`:1254`+ temp triggers).
3. Fan airflow physically excites the mmWave radar → mmWave keeps asserting.
4. Room never clears → fan never falls to the vacancy path → **self-sustaining**.

This is a **REAL** loop for Study A: it has an mmWave sensor, it is a non-bedroom
(no sleep suppression to break the cycle), and the comfort fan is gated on the
very occupancy signal the fan corrupts. This is precisely the motion-vs-mmwave
fan-shake class the fan-recheck feature exists to break: recheck PAUSES the fan
(`pause_for_recheck`), observes whether mmWave decays without airflow, and if
mmWave was the lone driver and clears, classifies the room `VACATED`
(`presence_fan_recheck.py:660-676`).

Living Room's live config exposes `motion_sensors` + `occupancy_sensors` (no
`mmwave_sensors` key in its room entry), so the *radar-shake* variant of the loop
is Study-A-specific; Living Room's fan-during-sleep is the same comfort-driver
(occupied + temp, no non-bedroom sleep suppression) but without the mmWave
positive-feedback term.

---

## BOTTOM LINE

- **Go / no-go: GO.** Both Study A and Living Room fans are MANAGED by
  `FanController`; the `no_managed_fan` bail does NOT fire for either. The
  veto-scoping fix **actuates as-is** — no fan mapping is required first.
- **Why they run during sleep:** URA comfort-fan logic (`_evaluate_temp_fan`)
  runs non-bedroom fans on `occupied AND warm` with **no sleep force-off** (only a
  speed cap for `reduce`-policy rooms); the bedroom night-trust block is
  room_type-gated and does not apply to `generic`/`common_area` rooms.
- **Feedback loop:** CONFIRMED REAL for Study A (mmWave present + non-bedroom +
  comfort fan gated on the same occupancy signal the fan shakes). This is the
  exact class fan-recheck is designed to break, and it argues the recheck path
  MUST be reachable for Study A — which Q1 confirms it is. Since the recheck
  itself pauses the fan to break the loop, enabling the recheck (via the
  veto-scoping fix) both actuates AND breaks the loop for Study A; no separate
  loop-breaking work is a prerequisite. (Living Room lacks the mmWave shake term,
  so no loop there — just the comfort driver.)

### Citations
- Managed set: `hvac_fans.py:320,340,364,373-397`
- Bail trace: `presence_fan_recheck.py:580-638, 1038-1045`; `hvac_fans.py:1841-1853`
- Non-bedroom sleep behavior: `hvac_fans.py:1101-1116, 1205-1209, 1254-1264`
- Constants: `const.py:421,427,428,1165`; `hvac_const.py:645`
- Live: config_entries `.storage/core.config_entries`; fan states on;
  `binary_sensor.living_room_hvac_cooling=on`.
