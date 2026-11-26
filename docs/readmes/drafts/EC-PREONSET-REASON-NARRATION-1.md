## EC-PREONSET-REASON-NARRATION-1 (narration only)

When a storm floor (pre-onset or partial-hold) raises the off-peak target above the solar-class drain target, the battery strategy reason now names both values: `Off-peak hold — SOC 21.0% <= storm floor 50% (drain target 10%, excellent; floor holds reserve)`. The old text read `<= target 50% (target excellent)`. The `+ pre-onset floor N` suffix is no longer added when the off-peak leg already names the floor. Without a floor, or with a floor at or below the drain target, the text is byte-identical to before. Decision values do not change.

**Acceptance (live):** under the next pre-onset floor at off-peak, `sensor.ura_energy_coordinator_battery_strategy` reason reads `... storm floor <F>% (drain target <D>%, <class>; floor holds reserve)` with no `+ pre-onset floor` suffix, and reserve_level equals F.
