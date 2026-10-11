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
3. **Class by capability, not by name or list.** Two properties decide how a sensor is treated: *holds a still person* (ZK/ZX yes; ZV/PIR no) and *fan-susceptible* (ZK/ZX yes — measured; ZV **pending measurement 2026-10-11**; real PIR no). Mechanisms that need a "fan-immune witness" (D2 sustain demotion, fan recheck, fan-transition gate, comfort-fan away veto) must read this, not the entity name. Today they disagree: `fan_veto.MMWAVE_NAME_PATTERN` discards motion sensors whose name contains `presence`/`mmwave` (so it ignores the ZVs), while D2/recheck count ZVs as motion.
4. Capability is recorded per sensor in `domain_coordinators/sensor_capability.py` (trust_class / failure_mode); extend that, don't invent a parallel registry.

## Open item
- ZV fan susceptibility: measurement running 2026-10-11 (empty-room fan-on vs fan-off rates per ZV in fan rooms). Record the verdict here.
