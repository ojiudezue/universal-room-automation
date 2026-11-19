# Review A: ROOM-OCCUPIED-ENTITY-REGISTRY-RESOLVE-1 (correctness, edge cases, goal fidelity)

Branch `feature/room-occupied-registry` e037ff441 + 4761b7919, base d882f2d07 (merge-base verified). I read HVAC STATE_OF_PLAY in full before reviewing.
Tests run from a clean export: 6 files, 102 passed.

**Verdict: SHIP.** No CRITICAL, HIGH or MEDIUM findings.

| # | Sev | Site | Finding |
|---|---|---|---|
| 1 | LOW | `memory_baseline.py:56-80` | R3b `_is_room_suppressed` is dead before and after this branch. `hass.data[DOMAIN][entry_id]` holds the coordinator itself, not a dict, so the `isinstance(val, dict)` check never passes. Leaving it alone is correct: reviving it would start dropping samples (a behaviour change), and it matches coordinators, so it never builds an id. Card it. |
| 2 | LOW | fixture AV Closet / Study A Closet | The URA temperature/humidity sensors are `_2`. The old name-built `sensor.av_closet_humidity` read a different entity. R4/R5 now read URA's own mirror, which is the correct target. Neither room is allowlisted, so there is no baseline impact. |
| 3 | INFO | `room_entities.py:_maybe_page` | Ruling: a daily HIGH page is proportionate. The registry is persisted, so steady state is 0 misses. A real miss leaves the fan guard failing open in that room. MEDIUM reaches no channel (the S10 lesson). The page is latched once per local day. |

## Holds

- unique_id `{entry_id}_{key}` matches `entity.py:34`. Temperature and humidity entities are always created (`sensor.py:594-595`).
- Exact `room_name` match; `title` is never read. A slug tie returns None and counts one miss.
- The fixture golden pins the 37 matching rooms. The 10 mismatched rooms (e.g. Foyer resolves to `foyer_foyer`, Jaya to `bedroom_4`) are pinned too.
- The fan guard reads the registry id carried on `RoomFanState.entry_id`. A None result still fails open, as before. For the 10 mismatched rooms the guard now blocks fan-off when the room is occupied.
- R6-R8 and NM co2/tvoc are counted fallbacks; none were deleted. R10 is untouched.
- D5 in `house_status.health` is display only. It is an acceptable drift.
