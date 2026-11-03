# Review: ENERGY-TODAY-MIDNIGHT-FREEZE-1 (fix/energy-today-midnight-freeze @ e0a211fc)

Tier 1, framing A (local correctness + blast radius). Diff base `develop...e0a211fc`: `aggregation.py` (+helper, mixin move, 3 call sites) and a new test file.

## Findings

| Sev | Where | Finding | Class |
|---|---|---|---|
| MEDIUM (pre-existing shape, not a regression) | aggregation.py `_accept_energy_today` | A staggered reset is now published as several drops (for example 34.45 → 20 → 4.4). HA `sensor/recorder.py:452 reset_detected` books any drop below 90% of the prior value as a new meter cycle and adds the post-drop value to `sum`. Each partial step therefore adds yesterday's residual to long-term statistics. Before the fix, one partial drop was booked and then the value froze, so the overcount is about the same size, now spread over 2-3 steps. A clean fix would hold until the sum settles, or publish one drop. Card it; do not block on it. | #63-adjacent (one reset vs many partial resets) |
| LOW | `ENERGY_TODAY_RESET_ACCEPT_WINDOW_MIN` | If a room's `coord.data` resets after 00:15 (its coordinator update failed through the window, or `_update` raised), the total holds at the last accepted value. It self-heals once today's sum passes the held value, so the freeze is bounded, not permanent. Rooms whose energy sensor is offline at midnight return `None` (coordinator.py:5212) and drop out of the sum, which is accepted in-window; when they return with a reset baseline the total goes up. That common late case is safe. | design limit |
| LOW | in-window | Inside 00:00-00:15, ANY dip is accepted, including a room going unavailable and then coming back (dip, then rise). That books one extra recorder reset with a small value. The window is 15 min/day and values are tiny just after midnight. | accepted risk |
| LOW | RoomsEnergyTotalSensor + restore | After a mid-day restart, rooms on the power-integration path (coordinator.py:5221, `_energy_accumulator` not persisted) restart at 0. The restored total is held until the rooms climb back past it. The display lags by that energy, but this is more accurate than the old drop-and-book-a-reset behaviour. | benign |

## Cleared
- DST / timezone: `dt_util.now()` is local, and the room coordinators reset on local `now.date()`. US DST changes at 02:00, so midnight is never repeated or skipped. Holds.
- Restart at 00:05: the restored `last_accepted_date` is yesterday, so `_apply_restore` reseeds nothing and the first sample is accepted outright (last_value None). If the restore is same-day (restart at 00:05 after a 00:00 sample), the drop is in-window and accepted. Holds.
- Restart mid-day: same-day restore plus a boot sample of 0 is outside the window, so it is held. This is the intended fix: no false reset is booked for a `total_increasing` sensor. Holds.
- MRO: `RoomsEnergyTotalSensor(Mixin(RestoreEntity), AggregationEntity, SensorEntity)` linearises as Mixin → RestoreEntity → AggregationEntity → SensorEntity → Entity. `AggregationEntity.async_added_to_hass` calls super (aggregation.py:~1181). This is the same shape as the zone sensors already shipped. `__init__` sets `_last_accepted_date`, so the `hasattr` gate in `_apply_restore` passes. Holds.
- Behaviour change vs old helper: the old code accepted the first sample when `_last_accepted_date` was None. The new code does the same (the guard needs both last_value and last_date). Holds.
- Consumers: EC `_get_rooms_energy_total` (domain_coordinators/energy.py:11267) sums room coordinators directly, not this sensor, so it is unaffected. The DB snapshot (database.py:3154) takes the EC value. frontend-v3 Rooms reads only the `room_energies` attribute, which is unchanged. The energy forecast does not read these sensors (grep). Unaffected.

## Tests
`test_energy_today_midnight_freeze.py` gives 13 passed; with `test_zone_power_rollup.py`, 44 passed (.venv-ha, targeted). No mutation drill (framing A).

## Verdict
**SHIP.** No CRITICAL or HIGH findings. Card the MEDIUM (multi-step partial resets inflate the recorder `sum`) as a follow-up.
