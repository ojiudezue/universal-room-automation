# URA v5.7.2 — Unavailable-entities sensor now covers actuators + structured detail (Tier 1)

Makes a dead actuator **visible**. Previously `sensor.<room>_unavailable_entities` only watched the room's *input* sensors (motion/presence/occupancy/power/temp/humidity/illuminance), so a dead light/fan/cover relay was structurally invisible — the room would silently stop auto-actuating and the sensor still read `0`. This extends the sensor to the room's **actuators** and enriches its output with a per-entity reason.

## Origin
AV-closet light stopped auto-on/auto-off (2026-06-30). Root cause was NOT URA code and NOT a config mis-wire — the Shelly relay (`switch.switch_shelly1pmgen3_wifi_avcloset`) was **offline** (`unavailable`/`restored:true` since a restart; a WiFi event took dozens of Shelly/Sonoff devices offline). A URA room can't actuate an `unavailable` entity, so it failed silently. The `unavailable_entities` tracker read `0` through the entire outage because it never looked at actuators. (Full write-up: `docs/BACKLOG.md` → "Offline-actuator visibility + recovery"; D2 reconcile-on-return is a separate design.)

## What ships (Tier 1 — single additive diagnostic, no actuation)
`UnavailableEntitiesSensor` (`sensor.py`) now scans the configured actuators too — `lights`, `night_lights`, `alert_lights`, `fans`, `humidity_fans`, `covers`, `climate_entity` — alongside the existing input sensors, deduped. New attribute shape:

```
state: <total unavailable count>            # backward-compatible (now spans actuators)
attributes:
  unavailable_entities: [...]               # flat list, backward-compatible
  details: [ {entity_id, roles:[...], category:"sensor"|"actuator", state, reason, since} ]
  unavailable_sensors:   [...]              # input-side entity_ids
  unavailable_actuators: [...]              # output-side entity_ids
  sensor_count / actuator_count
```

`reason` is derived from the live HA state object:
- **`offline_since_restart`** — `state=="unavailable"` with the `restored:true` placeholder (HA rehydrated the entity but the device/integration never reported; the AV-closet case).
- `device_unreachable` — `unavailable` without `restored`.
- `state_unknown` — state is `unknown`.
- `entity_missing` — no state object (removed/not registered).

`since` = the entity's `last_changed` (how long it's been down). The split (`category`) lets the room alert / NM treat a dead *input* (degrades detection) differently from a dead *actuator* (degrades actuation) later, with **zero new entities**.

## Review / gate
Tier 1 (additive, diagnostic-only, no actuation, no cross-coordinator ripple). Pre-deploy zero-bugs gate: no conflict markers; `py_compile` clean; suite at the documented **35-failed baseline** (no new failures); `test_sensors.py` + `test_cycle_c_stub_cleanup.py` = 49 passed. No internal consumer reads the sensor's count, so extending it is non-breaking.

Behavioral verification is **live** rather than a unit mirror: the house currently has known-offline actuators (e.g. jaya bath fan, exercise-room-closet switch), which gives a real post-deploy check stronger than a copied-logic test.

---

## Acceptance

```yaml
version: 5.7.2
hypotheses:
  - id: H1
    name: ura_v572_deployed
    description: URA v5.7.2 is the running HACS-installed version.
    oracle: home_assistant
    query: { kind: home_assistant.state_attribute, entity: update.universal_room_automation_update, attribute: installed_version }
    expected: { condition: "==", value: "v5.7.2" }
    window: { first_check_after: 10m, confirm_after: 1h, alert_if_violated_after: 6h }
  - id: H2
    name: no_error_storm
    description: No recurring URA error after the sensor change.
    oracle: home_assistant
    query: { kind: home_assistant.log_count, search: "universal_room_automation", period: 24h }
    expected: { condition: "<", value: 5 }
    window: { first_check_after: 1h, confirm_after: 24h, alert_if_violated_after: 72h }
  - id: H3
    name: actuator_breakdown_live
    description: The unavailable-entities sensor publishes the new actuator breakdown attribute.
    oracle: home_assistant
    query: { kind: home_assistant.state_attribute, entity: sensor.av_closet_unavailable_entities, attribute: actuator_count }
    expected: { condition: "!=", value: "unknown" }
    window: { first_check_after: 10m, confirm_after: 1h, alert_if_violated_after: 24h }
```

> Shipwatch note: the HA adapter stub is backlogged → these resolve `pending` until it ships. Verify entity/attribute names live before trusting `confirmed`.

## Live Validation — Validated 2026-07-01 (post-restart)
| # | Criterion | Result | Observed evidence |
|---|---|---|---|
| L1 | Deploy healthy | **PASS** | `update.universal_room_automation_update` installed_version = `v5.7.2`. Boot log shows only WARNING-level lines (known SPAN circuit-rename energy-sensor noise + boot-transient "All N sensors unavailable — holding occupancy" + Envoy still booting) — **zero URA ERROR entries**. |
| L2 | Actuators surfaced with category/role/reason | **PASS** | 7 rooms flagged unavailable actuators. Examples: `sensor.stair_closet_unavailable_entities` → `switch…staircloset` (`roles=[lights]`, `device_unreachable`); `sensor.studya_room_device…` → `cover.study_a_blinds` (`roles=[covers]`, `device_unreachable`); `sensor.kitchen…` → `switch.switch_tapo_wifi_kitchenrange` (`roles=[night_lights]`, `entity_missing`). `category`/`roles`/`reason`/`since` all populated. **All four reason tokens observed live:** `offline_since_restart`, `device_unreachable`, `entity_missing`, `state_unknown`. |
| L3 | AV closet (the origin case) | **PASS (stronger than planned)** | Prospective expectation was `actuator_count=0` (Shelly recovered). In fact the AV-closet Shelly **re-dropped** (flaky device — 2nd offline episode today; raw `switch…avcloset`=`unavailable`), and the sensor now correctly surfaces it: `actuator_count=1`, `unavailable_actuators=[switch…avcloset]`, `reason=offline_since_restart`, `category=actuator`, `roles=[lights]`, `sensor_count=0`. This is precisely the silent failure the cycle was built to make visible. |
| L4 | Backward compat + recovery-clearing | **PASS** | `unavailable_entities` flat list + numeric state preserved. Recovery verified: `sensor.stair_closet_unavailable_entities` cleared to `0` (`sensor_count=0`/`actuator_count=0`) once its Shelly reconnected post-settle — the sensor clears as devices recover, not only flags. |

**Note:** the AV-closet Shelly is genuinely flaky (2nd offline episode 2026-07-01) — hardware/WiFi attention warranted (operator-side). URA now makes it *visible* (`offline_since_restart`) instead of failing silently, which is the whole point of this cycle.
