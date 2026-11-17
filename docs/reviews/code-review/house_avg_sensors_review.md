# Review: HOUSE-AVG-SENSORS-1 (feat/house-avg-sensors @ 98335c557)

Tier 1, framing A (local correctness + HA patterns + edge cases). Diff: `git diff develop...feat/house-avg-sensors` (base 408a666db). Targeted tests: `quality/tests/test_house_avg_sensors.py` 10 passed.

## Findings

| Sev | Bug class | Location | Finding |
|---|---|---|---|
| LOW | Unit assumption (pre-existing pattern) | aggregation.py `HouseAvgTemperatureSensor` | Unit hardcoded °F. Room temps come from `coordinator._get_sensor_value` -> `float(state.state)` in the source sensor's own unit, no conversion. Matches siblings (`ClimateDeltaSensor` aggregation.py:1800, :2027) and this install (°F), so correct here; a °C install would mislabel, same as every sibling. Portability card, not a blocker. |
| LOW | Efficiency | `_HouseAvgIndoorSensor.native_value` / `extra_state_attributes` | Each state write computes `_get_house_avg_filtered` twice (two classification passes over ~40 rooms). Cheap; could cache per update. |
| INFO | Test fixture | test_house_avg_sensors.py | `test_existing_unfiltered_getters_unchanged` only proves the getters still exist unfiltered, not that TempDeltaOutside/HVACDirection call them; adequate since those call sites are untouched by the diff. |

## Cleared
- Registry rule: exclusion uses `get_room_classification` (room_classification.py:94) reading merged entry data/options `room_type`, `_infrastructure_room` on the coordinator, and Zone Manager `zone_is_outdoor`. No name inference. `rooms_excluded` uses `entry.title` for display only.
- None/unavailable: rooms with `coord.data` empty or value None skipped and not counted; empty set -> None (unknown). Classification fails open to not-excluded (room_classification.py fail-open), so an error degrades to the unfiltered average, never a crash.
- unique_id `universal_room_automation_house_avg_{temperature,humidity}`: no collision (grep of the integration; existing `house_avg_*` are DB columns/locals only). Entity id derived from has_entity_name + integration device.
- Cadence: same `AggregationEntity` + default polling as siblings, plus the room-ready retry; refreshes identically to TempDeltaOutside etc.
- Setup: both added in `async_setup_aggregation_sensors`; wire-in test drives the real setup function.
- Tests drive production classes, real `get_room_classification` and real `outdoor_zone_names_snapshot`; hand-derived oracle (72.0 / 45.0 / 81.3 / 78.0). Not hollow.
- No behavior change: `_get_house_avg_temp` / `_get_house_avg_humidity` untouched; additive only.

## Verdict: SHIP
No CRITICAL/HIGH/MEDIUM. Two LOWs optional.
