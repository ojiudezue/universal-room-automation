# Sensor fleet classes — the settled record (main house, 2026-10-11)

**Purpose:** stop re-litigating which presence/motion sensors can hold a still person and how URA must file them. Operator-confirmed 2026-10-11. Code, configs and plans must agree with this table; if live behaviour contradicts it, measure and update this doc in the same change.

## The three Hobeian families (38 Hobeian devices total)

| Model (`model_id`) | HA model string | What it is | Holds a still person? | URA role | Count |
|---|---|---|---|---|---|
| **ZG-204ZV** | "Millimeter wave motion detection" | mmWave *motion-class* sensor (behaves like PIR) | **No** — drops a still person | `motion_sensors` | 22 |
| **ZG-204ZK** | "24Ghz human presence sensor" | true presence radar | Yes | `presence_sensors` | 5 (Study A, Jaya, Ziri, Exercise Room [entity named `…gameroom…`], +1) |
| **ZG-204ZX** | "24Ghz millimeter wave and T&H sensor" | presence radar + temp/humidity | Yes | `presence_sensors` | 3 (Living Room, Kitchen, Master Bedroom) |

Also in the fleet: 5 Hobeian "Motion sensor" (PIR) and 3 water-leak sensors.

## Rules
1. **ZV is motion, never presence.** All 22 ZV units are filed under `motion_sensors` (verified 2026-10-11 against `core.config_entries`). Do not move a ZV into `presence_sensors`, and do not "fix" a ZV out of `motion_sensors` because its entity name contains `presence`/`mmwave` — the name is Z2M's, not its class.
2. **Duplicate entities:** four ZV devices (breakfast, butler, downguestroom, exercise) carry a bare `…_presence` entity that is a dead leftover of a Z2M rename (unavailable); URA uses the live `…_presence_2`. Use `_2`.
3. **Class by capability, not by name or list.** Two properties decide how a sensor is treated: *holds a still person* (ZK/ZX yes; ZV/PIR no) and *fan-susceptible* (ZK/ZX yes — measured; ZV fan-immune in steady state, measured 2026-10-11 below; real PIR no). Mechanisms that need a "fan-immune witness" (D2 sustain demotion, comfort-fan away veto) read capability, not the entity name: `sensor_capability.is_fan_immune_witness()` (CONF-list kind + `CONF_SENSOR_CAPABILITIES` override) plus a device-model safety net (`fan_veto.is_fan_immune_motion_witness` drops any radar family from `FAMILY_BY_MODEL_ID` filed under `motion_sensors`). `fan_veto.MMWAVE_NAME_PATTERN` is retired (kept, no live reader) — fan-noise Rev 2 C2, branch `fix/fan-noise-running-rejection`.
   **URA treats ZV as a fan-immune witness in steady state. The ~5-min post-fan-on transient (measured 3/11 in Game Room) is NOT currently gated in code; C1a (recheck leaves the fan off on VACATED) + C3 Part A (fan belief held through unavailable flaps) + the per-family recheck factor catch the residual. Follow-up card: FAN-ZV-POWERON-TRANSIENT-GATE-1** (trigger: week-1 measurement shows ZV false-vacate > 1/week in any fan room).
   Live model audit (both houses, 2026-10-11): `docs/planning/AUDIT_motion_sensors_live_models.md`. Three Meross MS600 radars sit in `motion_sensors` (Guest Bedroom 1, Guest Bedroom 2, Media) — held out by the model safety net; move them to `presence_sensors` (a `kind: mmwave` override on a motion-wired entity is rejected by the options validator).
4. Capability is recorded per sensor in `domain_coordinators/sensor_capability.py` (trust_class / failure_mode); extend that, don't invent a parallel registry.

## ZV fan susceptibility — measured 2026-10-11 (7-day recorder window, ground truth = BLE location ±3 min)
| Room | Steady fan ON vs OFF (empty) | Latch ≤5 min after fan→on | Verdict |
|---|---|---|---|
| Game Room (`fan.game_room_ceiling_fan_2`) | 0.74/h vs 0.94/h (27 h fan-on data) | 3/11 | **Fan-immune in steady state**; small power-on transient |
| Living Room | 2.51/h vs 0.71/h — same rise in its Screek radar (8.7% vs 3.6%) → likely real people BLE missed | 0/6 | Ambiguous (confounded) |
| Guest Bedroom 1 (live fan `_2`) | fan never ran in window | – | Insufficient data |
| Exercise Room | `fan.fan_switch_3` unavailable 45+ days | – | Insufficient data |

Hold time while present: ZV drops to off in 30–70 s (p50) — **confirms motion-class (cannot hold a still person)**.
**Working rule until a fan-cycling trial (Living Room, Guest Bedroom 1) or longer retention says otherwise:** a ZV may serve as a fan-immune witness *during steady fan running*, but not within ~5 min after a fan switches on. **Code status (2026-10-11):** the 5-min exclusion is NOT implemented — see Rule 3 and FAN-ZV-POWERON-TRANSIENT-GATE-1.

## Do-not-use list (operator rulings)
- `binary_sensor.invisoutlet_b7d0_motion` and the Study A InvisOutlet occupancy entity — unreliable; never configure as a URA witness (2026-10-11).

## Meross MS600 (dual-homed) — settled 2026-10-11 (operator)
Three MS600 mmWave presence radars (Guest Bedroom 1, Guest Bedroom 2, Media) are paired twice on purpose: the native `meross_lan` integration reports presence as a non-standard numeric value (`…_presence`, ≥1 = person) — so the operator also paired them over **Matter** to get a standard binary occupancy. Filing (correct, leave as is):
- Matter `binary_sensor.mmwave_motion_lux_matter_wifi_<room>_occupancy` → `presence_sensors` — the still-person holder. (Guest Bedroom 2's was in `occupancy_sensors` until 2026-10-11; moved because the fan mechanisms key on occupancy source `mmwave`, which only the `presence_sensors` list produces — in `occupancy_sensors` it was invisible to fan-noise rejection.)
- `meross_lan` `binary_sensor.…_sensor_presence_motion` (the radar's motion bit) → `motion_sensors` — fine for lights, but radar-derived: **not a fan-immune witness**; v5.103.51's model safety net (`ms600`, first-token match) excludes it.
- Native `…_presence_distance` exists → candidate for the deferred fan-distance-band option.
- Do NOT "move the MS600s to presence" (retracted 2026-10-11 — the Matter half already is). No more MS600 purchases planned (native protocol's non-binary interface).

## ESPHome ESP32 radars = HLK-LD2410 (operator 2026-10-11)
Jaya (`jaya_3`), Ziri (`ziri_3`), Kitchen, Study B. ESPHome reports the ESP32 board as the device model, so v5.103.51's `FAMILY_BY_MODEL_ID` resolves them `unknown` → witness role excluded via the name fallback (correct — radar), recheck window factor 1.0 unless the room has a recognised slower family (Jaya/Ziri/Kitchen also carry ZK/ZX → ×2). Measured LD2410 clear-after-fan-off 28/132 s (p50/p90, Jaya) — faster than Zigbee, so 1.0 is adequate; the plan's LD24xx ×3 was unsupported. **No code needed.** Revisit only if the 2026-10-18 re-measure shows Study B's recheck false-negatives. They expose moving/still distance + energy (ESPHome) — the best candidates for the deferred fan-distance-band option.

- **Rule (corrected 2026-10-11):** `occupancy_sensors` = *combined* sensors (radar + motion reported as one signal) — e.g. the Meross MS600 over Matter (PIR + 24 GHz radar + light; fusion undocumented). Combined sensors legitimately contain radars. **Resolved (OCCUPANCY-SOURCE-FOLLOWS-CAPABILITY-1, branch `fix/occupancy-source-follows-capability`, not yet deployed):** fan-noise trust gates no longer key on the occupancy-source LIST label `mmwave`. They read a per-tick capability value — the room's Tier-1 on-set is non-empty and every on entity is radar-bearing (`CONF_SENSOR_CAPABILITIES` override wins both ways > CONF-list kind `mmwave` > device family in `RADAR_SENSOR_FAMILIES`; bed / PIR / unknown = not radar). Filing a combined radar in `occupancy_sensors` is therefore safe for fan rejection (D2 gate + latch, presence fan-interference gate, recheck eligibility / still-armed / VACATED / window family). The GB2 revert to `occupancy_sensors` is an **organic follow-up** gated on live validation, not a ship-time change. Kill switch: `sensor_capability.OCCUPANCY_SOURCE_CAPABILITY_ROUTING_ENABLED` (rung 1). URA room sensor lists accept binary sensors only (`config_flow` EntitySelector domain=binary_sensor), so the native Meross numeric `…_presence` can't be used directly.

- **Native Meross value (UNVERIFIED on our units):** meross_lan sets its `…_sensor_presence_motion` binary from `value == 2` (`meross_lan/devices/ms600.py:249`); HA community reports value 1 = nobody, 2 = present — so that entity may be *presence*, not a motion bit. Verify with hold-time-while-still before relying on it as motion.
