# Review: ZONE-LIVE-POWER-ROLLUP-1 (fix/zone-power-rollup acfcd42b..78a974c9)

Tier 1/2, framing A (correctness + edge cases + recorder/statistics). Base verified = merge-base with develop `e3c75a99`.
Tests: `quality/tests/test_zone_power_rollup.py` 22 passed.

| SEV | file:line | Finding | Bug class |
|---|---|---|---|
| MEDIUM | aggregation.py:4386-4430 (`_zone_level_energy`), 5246-5262 (`ZoneEnergyTodaySensor.native_value`) | Mid-day restart with a lifetime-counter (>1000 kWh) zone energy sensor: in-memory baseline is lost, first read re-anchors to current so the zone-tier contribution restarts at 0. `_last_valid_value` is also None after restart, so the decrease guard does not hold. The TOTAL_INCREASING entity drops (e.g. 30 -> 20 kWh). HA recorder treats that as a meter reset and adds the full new value to the long-term `sum`, so statistics OVERCOUNT by the post-restart value, and the energy-today shown undercounts the rest of the day. This happens on every mid-day restart. The house coverage tier has the same pre-existing baseline loss, but there it only feeds a delta sensor; here it feeds a TOTAL_INCREASING energy statistic. Fix: persist baselines (RestoreEntity / extra restore data with anchor_date), or restore `_last_valid_value` for the same date so the guard holds. | Restart resilience / stale in-memory state |
| LOW | aggregation.py:4345-4347 | The room-overlap skip only checks the zone's own member rooms. An entity listed in a room of a different zone and also in this zone's `zone_power/energy_sensors` is counted twice across zones. That config is unusual but legal. | One-missed-site (#53, scope) |
| LOW | aggregation.py:3648-3672 vs 4386 | House coverage zone tier does not skip room overlap; the new zone sensor does. This gap predates the cycle, so nothing new is double counted, but the two tiers now give different answers for the same config. Card it. | #63 concept split |
| LOW | aggregation.py:4304-4325 | Every state read walks the config entries and rebuilds the room set. The cost is small (a few dozen entries); just noting it. | Performance |
| INFO | 5260-5262 | Same-day unavailable zone sensor: the sum dips, and the guard returns `_last_valid_value`, so no decrease reaches the recorder. Holds. |  |

Cleared:
- **Unit conversions:** go through `power_state_to_w` / `energy_state_to_kwh`. W->kW for cost/hour is unchanged.
- **Midnight re-eval:** derived sensors re-anchor and return 0; native sensors pass through.
- **House coverage:** it does not sum zone Energy Today entities, so no new double count.
- **`any_valid`:** extended correctly in both cost sensors.

**Verdict: SHIP with a MEDIUM follow-up.** The restart overcount only appears when a lifetime-counter zone energy sensor is configured. Check live config: if any `zone_energy_sensors` reads >1000 kWh, fix before ship.
