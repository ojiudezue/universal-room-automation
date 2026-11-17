# ANOMALY-FLOOD-ROWS-1 — Review A (local correctness, edge cases, None, registry rule)

Branch `fix/anomaly-flood-transit-coverage` @ a6319b7e3, diff `b0b47a42c..a6319b7e3`. Static review only, no pytest run (a serial validator run follows).
Presence docs: this change touches census inputs and transit validation; the review is confined to transit_validator / camera_census code and needed no presence-doc claim.

## Key-space proof (the load-bearing question)
- Producer of `RoomTransition.from_room/to_room`: `transitions.py:218-223` passes `previous_location`/`current_location` from the `ura_person_location_change` event. That event is fired at `person_coordinator.py:1123-1137` with `current_location = resolved_room` from `_resolve_person_room`. Tier 1 returns `_area_id_to_room[...]`, filled at `person_coordinator.py:1621,1646` with `entry.data.get("room_name")` verbatim. Tier 2 `_scanner_to_rooms` holds the same `room_name`.
- Map key: `camera_census.build_room_to_area_id_map` keys on `merged.get(CONF_ROOM_NAME)` with `CONF_ROOM_NAME == "room_name"` (`const.py:456`). `CONF_ROOM_NAME` is written only at create time (`config_flow.py:2251`, stored trimmed in data), and the options flow never overrides it. **Same key space, same case, verbatim.** It holds.
- Value side: `CONF_AREA_ID` (`const.py:458`) is the same field person_coordinator reads (`:1626`), so a room's area is the HA area the camera registry reports. Registry lookups only. No name guessing.

## Findings
| # | Sev | Class | file:line | Finding |
|---|---|---|---|---|
| A1 | LOW | Coverage gap (by design, counted) | `person_coordinator.py:1734-1736` → `transit_validator.py` `_transition_covered_by_shared_camera` | When Bermuda reports an area that no URA room claims, `_resolve_person_room` returns the raw area NAME (for example "Hallway"). That string is not a room key, so the move counts as unresolved and is not penalised, even when a shared camera sits in exactly that HA area. Resolving it by area name would be a name match, which the registry rule forbids. The behaviour is acceptable and visible through `path_coverage_room_unresolved_count`. Recommend recording it in the README as a known limit. Not must-fix. |
| A2 | LOW | Counter semantics | `transit_validator.py` (unresolved increment) | `_coverage_room_unresolved_count` counts per room END (0-2 per move), not per move, and only on cameras-active no-sighting moves. The test confirms this (`==2`). Recommend naming that in the attr docstring. Cosmetic. |
| A3 | INFO | — | `build_room_to_area_id_map` per call | The map is rebuilt for every no-sighting validation (a config-entry iteration over about 40 entries). It is cheap, not cached, and always fresh, so a cache could not go stale. OK. |

## Cleared
- **Camera census refactor is byte-equivalent.** The body moved verbatim and `PersonCensus._build_room_to_area_id_map` delegates (`camera_census.py:2994`). Only the debug log text differs.
- **None handling:** `room` None/"" → unresolved. `"away"`/`"unknown"` → not in the map → unresolved, no penalty (moves from "unknown" are already skipped at `transitions.py:200`). An entity missing from the registry, or a camera with no area → `None`, cached. `None in move_areas` is never true because `move_areas` holds only truthy ids. A registry exception → `None`, logged at debug.
- **Area precedence:** the entity `area_id` overrides the device area, then the device area is used. That matches HA semantics. Protect-sourced and F2 camera entities carry a `device_id`, so the device-area fallback covers cameras whose area is set only on the device. The test `test_camera_area_falls_back_to_device_area` drives that path.
- **Cache invalidation:** `_build_and_subscribe` resets `_shared_camera_area` (`transit_validator.py:~556`), so registry-driven rebuilds clear stale areas.
- **Counters:** `not_covered` increments only on cameras_active AND not covered. The inactive path does not count, and a test pins that. The sensor plumbing in `sensor.py:6861-6866` uses `int(... or 0)`, so it is None-safe.
- **Real-implausible case preserved:** a move into or out of a camera room with no sighting still returns `path_implausible`. Two tests pin this, one for the to-room and one for the from-room.
- **Unsub side fix:** the three fields used to sit after `return` in `build_diagnostic_attrs`, so `__init__` never set them, and the first `if self._rebuild_timer_unsub is not None` (`:608`, `:924`) depended on an earlier assignment. Moving them into `__init__` is correct and adds no new behaviour.
- **Tests drive production:** `test_transit_path_coverage.py` imports the real package and calls the real `validate_transition`. Only the registries, the shared-camera list and the clock are monkeypatched, and the entry dicts use the real const strings (`entry_type`/`room`/`room_name`/`area_id`). These are not hollow anchors.

## Verdict
**SHIP.** No CRITICAL/HIGH/MEDIUM. A1 and A2 are LOW and documentation-only.
