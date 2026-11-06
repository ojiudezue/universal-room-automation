# v5.103.104 — Room menu trimmed in Advanced mode too; per-room electricity rate removed

**Card:** ROOM-TYPE-TRIMMED-MENU-1 (follow-up, 2026-11-05). Tier 2.

**Visible changes:** a closet, hallway, utility room and other small room types now show only the settings they usually need even when Advanced mode is on, with **More settings…** for the rest. The room **Energy** section no longer has an electricity-rate field. Room cost uses the Energy Coordinator's time-of-use rate, or the house-wide rate when that is unavailable.

## Why

- HA now documents `show_advanced_options` as deprecated (removal in 2027.6) and says it "always returns `True`" until then (contributors.home-assistant.io/core/integrations/flow-steps). Live, every room therefore got the full 12-section menu and the room-type trim never ran. The trim no longer depends on Advanced mode.
- Rooms stored an old per-room rate (0.11 $/kWh, against a 0.15 default). It revealed the Energy section on rooms that have no energy sensors, and it quietly replaced the house-wide rate whenever the Energy Coordinator had no rate.

## Changes

- `config_flow.py` room options menu (`async_step_init`, room branch): always uses `ROOM_MENU_STEPS_BY_TYPE` + in-use reveal + `show_all_settings`. Advanced mode still only controls Advanced fields inside sections (`_filter_advanced` unchanged).
- `room_menu_hint`: the trimmed line ("Showing the settings a closet usually needs. Pick More settings for the rest.") now shows in both modes, followed by the matching Advanced hint.
- `const.py`: menu comment updated.
- Room `energy` step (create flow and options flow): `electricity_rate` field removed. The house-wide rate (house setup and House > Global sensors) is unchanged.
- `energy_billing._get_effective_rate_kwh`: order is now EC TOU, then house-wide rate, then `DEFAULT_ELECTRICITY_RATE`. The room tier and the `room_entry` argument are gone; callers in `sensor.py` (room cost today) and `coordinator.py` (room weekly/monthly cost) updated.
- `coordinator._get_electricity_rate` deleted: it had no callers and implemented the same room-first fallback this release removes.
- Stored room `electricity_rate` values are left in place (no migration). They are no longer read, and they no longer reveal the Energy section.

## Tests

- New `quality/tests/test_room_menu_adv_trim_and_room_rate.py` (17 tests, driving the real options/config flow handlers, the real rate helper and the real room cost sensor).
- Updated `test_room_menu_trim.py` (Advanced mode is trimmed too), `test_room_advanced_fields.py` (hint variants), `test_v4_6_8_rate_reconciliation.py` (hollow room-override mirror replaced by a call to the real helper).
- Mutation drills: five sites, each RED on its own test (see the build report).

## Validated 2026-11-06 (restart 14:55 CT)
| Criterion | Result | Evidence |
|---|---|---|
| Stair Closet trimmed menu | PASS | REST options flow `menu_options` = basic_setup, sensors, devices, options_lighting_behaviour, options_covers, sleep_protection, energy, show_all_settings (energy shown: closet has a Meross plug; sleep_protection has values) |
| Advanced on/off same menu | as-expected | HA 2026.10 forces `show_advanced_options` True; only one state reachable live, both proven in-suite |
| Bedroom keeps all 12 | PASS | Master Bedroom `menu_options` has 12 entries, no show_all_settings |
| Cost uses EC TOU | PASS | `sensor.zone_*_energy_cost_today` attr `rate_source=ec_tou`; `sensor.master_bedroom_energy_cost_today`=0.29 (room sensor carries no rate attr, so rate proven via zone rollup + suite) |
| No config-flow exceptions | PASS | 0 URA ERROR lines after boot (2 at 14:55:17 are shutdown-time DB write skips) |
