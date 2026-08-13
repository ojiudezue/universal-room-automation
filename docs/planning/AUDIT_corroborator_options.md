# AUDIT — Corroborator options for the Living Room (AWAY-BLOCK-1 rec-1 follow-up)

**Status:** Read-only analysis, 2026-08-13. No changes applied.
**Context:** `AUDIT_away_transition_2026_08_13.md` §(c)/(d) — the D2 mmWave-fan
sustain demotion is fail-closed for the Living Room because
`motion_sensors: []`. Operator question: (a) would a SECOND mmWave (instead of
a PIR) arm it? (b) what non-hardware alternatives fit the existing system?

---

## 1. What EXACTLY counts as the D2 corroborator set (as shipped)

Two distinct mechanisms, with DIFFERENT corroborator vocabularies:

### 1a. D2 sustain DEMOTION (the mechanism that was disabled in the incident)

- **Arming gate** `_d2_motion_sensors_present()`
  (`coordinator.py:1785-1814`): reads **`CONF_MOTION_SENSORS` only**
  (`const.py:333`), then filters out entries whose entity_id matches
  `MMWAVE_NAME_PATTERN = (mmwave|radar|presence|ld2410|ld2412)`
  (`fan_veto.py:61-63`). Empty filtered list → fail-closed, demotion
  permanently off for the room.
- **Staleness leg (e)** consumes `_last_pir_motion_time`
  (`coordinator.py:2780-2793`), which is refreshed **only when a
  motion-bucket sensor fires** (`coordinator.py:2505-2511` — the mmWave and
  occupancy_sensor branches deliberately do not touch it, "so mmwave can't
  self-confirm the staleness gate").
- BLE person / camera person appear in D2 only as **vetoes** (block demotion
  when present, via `_compute_fan_interference_rooms`) — they do NOT arm the
  gate and their absence is not consulted by leg (e).

**So the demotion corroborator set = the motion CONFIG BUCKET minus
mmWave-looking names.** It is a role hardcoded onto a wiring list — exactly
the kind-vs-role defect SENSOR-CAPABILITY-1 named.

### 1b. Duty-cycle stuck detector (notify-only) — already role-migrated

SENSOR-CAPABILITY-1 **shipped (v5.65.0)**: `_detect_duty_cycle_stuck` builds
`effective_corroborators` via `resolve_role(cfg, eid,
RoleQuery.CORROBORATOR_FOR_ROOM)` (`coordinator.py:1612-1642`), where
`_CORROBORATOR_KINDS = {motion, pir, pir_split, bed, camera_presence,
ble_presence}` and **mmwave / occupancy are explicitly excluded** — "they are
the very sensors D2 watches for stuck behaviour"
(`domain_coordinators/sensor_role.py:55-76`). Capability overrides live in
`CONF_SENSOR_CAPABILITIES` (`const.py:413`) but are **valid only for entities
already wired in one of the three Tier-1 CONF lists** (resolver API contract,
`sensor_role.py:93-105`). Per the module docstring (lines 14-20), the
duty-cycle detector is the ONLY consumer wired so far; **the D2 demotion gate
(1a) has NOT migrated to `resolve_role`.**

## 2. Answer (a): would a second mmWave corroborate?

**No, three times over:**

1. **As written (config-mechanical):** placed in `presence_sensors` it never
   touches `_d2_motion_sensors_present()` (motion bucket only). Misfiled into
   `motion_sensors`, its name will almost certainly match
   `MMWAVE_NAME_PATTERN` and be filtered out. Either way the gate stays
   fail-closed.
2. **Worse if smuggled past the name filter:** an mmWave in the motion bucket
   with a non-matching name would ARM the gate and then feed
   `_last_pir_motion_time` on every mmWave fire (`coordinator.py:2505-2511`
   keys on bucket, not hardware) — leg (e) can never go stale while the fan
   pins BOTH radars. The gate opens and the demotion still never fires. Net
   negative.
3. **By design in the shipped role layer:** `sensor_role.py` deliberately bars
   kind `mmwave` from `_CORROBORATOR_KINDS`. Even post-migration of D2 onto
   `resolve_role`, a second mmWave only corroborates if the operator falsely
   declares it `strong_evidence` — which would be lying to the trust model.

**Physics (the real reason the code says no):** both mmWaves watch the same
room and the same oscillating fan; radar fan-confusability is a **correlated
failure mode**, so the second unit adds ~zero independent evidence about the
incident scenario. Corroboration requires a *different failure mode*, not a
second copy of the same one.

So the answer to the kind-vs-role sub-question is **(c)**: what matters is the
role slot (today: the motion bucket; post-migration: `CORROBORATOR_FOR_ROOM`),
and mmWave hardware is deliberately excluded from that role regardless of
which bucket it sits in.

## 3. Non-hardware corroborators already in the substrate

Living Room live config (`core.config_entries`, entry "Living Room",
verified 2026-08-13):

| Surface | Value |
|---|---|
| `motion_sensors` | `[]` |
| `occupancy_sensors` | `[]` |
| `presence_sensors` | `['binary_sensor.screek_human_sensor_l13_2412s_presence']` (the incident sensor) |
| `room_cameras` | **not set** (`disable_camera_presence: False`, but `binary_sensor.living_room_camera_person_detected` is hard-off with empty list — `binary_sensor.py:1146,1199-1203`) |
| `room_media_player` | `media_player.living_room_2` |
| `power_sensors` | SPAN living-room plugs + dining lights power |
| `energy_sensor` | SPAN living-room plugs energy |
| `scanner_areas` | `['living_room', 'entry_way', 'dining_room']` (BLE/Bermuda coverage exists) |
| `sensor_capabilities` | not set |

Candidate-by-candidate:

| Candidate | Exists per-room? | Accepted by D2 demotion today? | Code to admit | Fan-confusable? |
|---|---|---|---|---|
| **Hallway PIR** `binary_sensor.rgbw_motion_lux_3rd_zigbee_livingroomhallway_occupancy` (enabled, Zigbee PIR multi) | Yes — unwired | **Yes, the moment it is added to `motion_sensors`** (name does NOT match `MMWAVE_NAME_PATTERN` — no mmwave/radar/presence/ld241x token) | **Zero** — pure options-flow config | No (PIR = thermal; a fan emits no body-heat signature) |
| **Camera person** (`CameraPersonDetectedSensor`, `binary_sensor.py:1137`; role kind `camera_presence` IS in `_CORROBORATOR_KINDS`) | Sensor entity exists but inert: `room_cameras` empty, and the 82-camera registry has **no camera covering the living-room seating area** (`family_room` is a different area; Study A / Upstairs Hallway are the only rooms with `room_cameras` set) | No — and even with a camera, D2 demotion consumes cameras only as a veto, not as leg-(e) corroborator | Hardware/repointing + the D2→`resolve_role` migration | No |
| **BLE room presence** (Bermuda; kind `ble_presence` in `_CORROBORATOR_KINDS`; `scanner_areas` covers living_room) | Area coverage yes; but no per-room binary_sensor exists to wire into a Tier-1 list (Bermuda emits per-device area trackers), and the capability validator only accepts entities in the three CONF lists | No — BLE is a demotion VETO only | Code: either a room-level BLE-anyone binary + wiring, or D2 migration consuming BLE staleness directly | No — but **correlated with the trust collapse**: it corroborates only residents-with-phones, the same signal class that went LOST/STALE in this incident |
| **Media-player activity** (`room_media_player`) | Yes | No shipped mechanism consumes it as occupancy evidence (music-following is an OUTPUT) | Code + a doctrine problem: "TV on" ≠ person (people leave TVs on for hours) | No, but person-confusable in its own way |
| **Power-draw signature** (`power_sensors`) | Yes | No shipped consumer as occupancy | Code — and **disqualified for this room**: the tower fan itself draws on the living-room plugs circuit, so power-as-corroborator re-creates the exact fan-self-confirmation loop | **Yes** (the fan IS the load) |
| **Door events** | No `door_sensors` on this room | N/A — door edges are creator-side evidence, not in the Tier-1 substrate | Hardware + code | No |

## 4. Answer (b) + cheapest path recommendation

**Cheapest armed corroborator, by a wide margin: wire the existing hallway PIR
(`binary_sensor.rgbw_motion_lux_3rd_zigbee_livingroomhallway_occupancy`) into
the Living Room's `motion_sensors`. Zero hardware, zero code, pure options
flow** — it passes the name filter, opens `_d2_motion_sensors_present()`, and
feeds `_last_pir_motion_time` so leg (e) becomes satisfiable. This is audit
rec-1 with a concrete entity.

Two caveats to resolve before/at wiring:
1. **Placement** (audit's own caveat): if the hallway head cannot see the
   seating area, a seated person generates no PIR refresh → D2 could demote a
   genuinely occupied room after `MULT×occupancy_timeout` of stillness. The
   sleep-family veto (`_d2_house_state_allows`) covers night; daytime
   long-still-sitting (movie watching) is the residual risk. Mitigation is
   the same knob that already exists: `D2_PIR_STALENESS_MULTIPLIER` is
   generous by design, and demotion only fires while occupancy is
   mmwave-SOLE with the fan flagged.
2. **Side effect:** a motion-bucket sensor is also an occupancy CREATOR
   (`CREATOR_VS_EXTENDER`, `sensor_role.py:134-147`) — hallway pass-through
   traffic will now create Living Room occupancy edges. Given
   `lights: []` / `exit_light_action: leave_on`, actuation blast radius is
   the fan and HVAC coordination only; acceptable, but note it.

If placement disqualifies the hallway head: **one new Zigbee PIR** (rec-1 as
written) is the next-cheapest; it is still config-only from URA's side.

**The right medium-term path (code, small, already anticipated):** migrate the
D2 demotion gate onto the shipped role layer — replace
`_d2_motion_sensors_present()`'s bucket read with "any entity in the room's
Tier-1 lists satisfying `RoleQuery.CORROBORATOR_FOR_ROOM`", and widen the
leg-(e) timestamp to refresh on any such corroborator (mirroring the
`effective_corroborators` construction at `coordinator.py:1612-1642`). This is
exactly the "other consumers migrate on their own budget in later cycles"
lane in `sensor_role.py:19-20`, and it is what lets a future camera or
bed-class corroborator arm D2 without another bucket hack. It does NOT help
the Living Room today (the room has no wireable corroborator entity other
than the hallway PIR), so it is a follow-on, not the fix.

**What NOT to do:** a second mmWave (correlated failure, barred from the
corroborator role by design, and actively harmful if smuggled into the motion
bucket); power-draw corroboration for this room (the fan is on the measured
circuit — it rebuilds the self-confirmation loop the incident is about).
