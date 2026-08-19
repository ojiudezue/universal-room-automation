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
went on** (occupancy → comfort fan). Trace:

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

**Living Room — CORRECTION (operator + live evidence, 2026-08-18).** An earlier
draft claimed Living Room "has no mmwave_sensors key, so no shake loop there."
**That was WRONG** — it read the stray/legacy storage key literally named
`mmwave_sensors` (value `None`) instead of URA's ACTUAL mmwave config key.
`CONF_MMWAVE_SENSORS = "presence_sensors"` (`const.py:433` — "Note: blueprint
calls them presence_sensors"). Living Room's live config maps
`presence_sensors: ['binary_sensor.screek_human_sensor_l13_2412s_presence']`
(the Screek L13). So Living Room **DOES** have a physical mmWave (the Screek) and
**URA reads it as its mmwave input**. Live NOW: Screek presence = **on**
(still_target hold, moving_target off) with the fan running — the **same
fan-shake feedback loop as Study A**. See Q3 for the deciding
recheck-observation check.

---

## Q3 — Does the fan-recheck OBSERVE the Screek when it pauses the Living Room fan?

**The deciding check for Living Room.** The recheck's arm gate and VACATE logic
key on `occupancy_source == "mmwave"` and `presence_detected`
(`presence_fan_recheck.py:860, 672-674`). For the Screek to matter, it must be in
the sensor set that produces those two values.

### 1. Where is the Screek mapped in the live Living Room config?
| URA config key | Value | Maps to |
|---|---|---|
| `presence_sensors` | `['binary_sensor.screek_human_sensor_l13_2412s_presence']` | **`CONF_MMWAVE_SENSORS`** (`const.py:433` — the constant's string IS `"presence_sensors"`) |
| `motion_sensors` | `['binary_sensor.mmwave_temp_lux_hum_zigbee_livingroom_presence']` (a Zigbee mmWave) | `CONF_MOTION_SENSORS` → `motion_detected` |
| `mmwave_sensors` | `None` | **stray/legacy storage key — URA does NOT read it** (URA's mmwave key is `presence_sensors`, not `mmwave_sensors`) |

### 2. What the recheck actually reads
`coordinator.py:2423` loads `mmwave_sensors = _get_config(CONF_MMWAVE_SENSORS)` =
the `presence_sensors` list = **[Screek]**. That list feeds
`presence_detected = any(is_sensor_on(s) for s in mmwave_sensors)`
(`coordinator.py:2717-2721`). When occupied, `occupancy_source` is set to
`"mmwave"` iff `presence_detected` is True AND `motion_detected` is False
(`coordinator.py:3065-3073` — **motion takes precedence over presence**). The
recheck reads `room_coord.data["occupancy_source"]` / `["presence_detected"]`
— i.e. the FUSED room signal, which is driven by the Screek via `presence_sensors`.
So **YES, the Screek is in the recheck's observed set** as the mmwave source.

### 3. Live evidence (2026-08-18)
- Screek `presence_sensors`: **on** (last_changed 21:37:08) → `presence_detected = True`
- Zigbee `motion_sensors`: **off** (last_changed 18:41:06) → `motion_detected = False`
- ⇒ fused `occupancy_source` = **"mmwave"** right now (presence True, motion False)
  — exactly the value the recheck arms on.

### VERDICT — Q3
**The recheck WOULD observe the Screek and CAN clear Living Room.** With the Screek
as the lone driver (`occupancy_source == "mmwave"`, current live state), after the
veto-scoping fix the recheck arms → pauses the fan → if the Screek `still_target`
decays once airflow stops, `presence_detected` → False → `occupancy_source` ≠
"mmwave" → **VACATED** (`presence_fan_recheck.py:672-676`). **No config
prerequisite is required** — the Screek is already URA's `CONF_MMWAVE_SENSORS`
input; mapping it into a `mmwave_sensors` key would be redundant (and `mmwave_sensors`
is not even the key URA reads).

**Secondary precedence gap (note, NOT a blocker).** The Zigbee mmWave is mapped
under `motion_sensors`, so `motion_detected` takes precedence over the Screek
(`coordinator.py:3065`). Whenever that Zigbee is simultaneously ON, the fused
`occupancy_source` becomes `"motion"`, and the recheck arm gate (`:860`, requires
`== "mmwave"`) will **not arm** — the recheck would be blind to the room in that
tick. It happens to be clean right now (Zigbee off), but this is a latent
data-dependent gap. Consider a follow-up card to recategorize the Zigbee mmWave
out of `motion_sensors` (a mmWave device labelled as motion inverts the intended
motion-vs-mmwave precedence). This does NOT block the veto fix for the current
Screek-driven case.

---

## BOTTOM LINE

- **Go / no-go: GO.** Both Study A and Living Room fans are MANAGED by
  `FanController`; the `no_managed_fan` bail does NOT fire for either. The
  veto-scoping fix **actuates as-is** — no fan mapping is required first.
- **Why they run during sleep:** URA comfort-fan logic (`_evaluate_temp_fan`)
  runs non-bedroom fans on `occupied AND warm` with **no sleep force-off** (only a
  speed cap for `reduce`-policy rooms); the bedroom night-trust block is
  room_type-gated and does not apply to `generic`/`common_area` rooms.
- **Feedback loop:** CONFIRMED REAL for Study A AND **Living Room** (both have a
  physical mmWave — Study A's, and Living Room's Screek L13 read by URA as
  `CONF_MMWAVE_SENSORS`/`presence_sensors`; both non-bedroom; comfort fan gated on
  the same occupancy signal the fan shakes). This is the exact class fan-recheck
  is designed to break. Since the recheck itself pauses the fan, enabling it (via
  the veto-scoping fix) both actuates AND breaks the loop for both rooms.
- **Screek observation (Q3): CONFIRMED — no config prerequisite for Living Room.**
  The recheck reads the fused `occupancy_source`/`presence_detected`, which is
  driven by the Screek via the `presence_sensors` (= `CONF_MMWAVE_SENSORS`) list.
  Live now: source = "mmwave" (Screek on, Zigbee motion off), so the recheck can
  arm → pause → vacate. The earlier "Living Room lacks mmwave" note was WRONG and
  is corrected above.
- **Latent precedence gap (follow-up card, not a blocker):** Living Room's Zigbee
  mmWave is mapped under `motion_sensors`; when it fires, `motion` precedence
  masks the Screek's "mmwave" source and the recheck won't arm that tick. Consider
  recategorizing it. Does NOT gate the veto fix for the Screek-driven case.

### Citations
- Managed set: `hvac_fans.py:320,340,364,373-397`
- Bail trace: `presence_fan_recheck.py:580-638, 1038-1045`; `hvac_fans.py:1841-1853`
- Non-bedroom sleep behavior: `hvac_fans.py:1101-1116, 1205-1209, 1254-1264`
- Constants: `const.py:421,427,428,1165`; `hvac_const.py:645`
- Live: config_entries `.storage/core.config_entries`; fan states on;
  `binary_sensor.living_room_hvac_cooling=on`.
