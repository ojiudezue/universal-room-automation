# Second home ("Home", 192.168.17.243) — read-only inspection, 2026-09-30

Source: HA REST API (`/api/config`, `/api/states`, `/api/config/config_entries/entry`, history), read-only, operator-supplied token (not stored in the repo).

## Platform
- HA **2026.9.1**, America/Chicago, °F. API served on **port 80** (8123/443 closed).
- Integrations present: homekit_controller, matter, shelly, sonos, unifiprotect, bermuda + bluetooth, mobile_app, mqtt, met + NWS weather, sun, hacs. No `illuminance` config entry, no Sun2.
- One `homekit_controller` entry ("HASS Bridge") is `not_loaded`; the ecobee's own HomeKit entry is loaded.

## URA already installed — v5.103.18 (update to v5.103.20 offered by HACS)
- Config entries: integration ("Home"), Zone Manager, Coordinator Manager. **Zero room entries.**
- All coordinators enabled, **including HVAC** (`switch.ura_hvac_coordinator_00_enabled = on`) — but HVAC sensors read `not_initialized` (no zones configured), so it is not acting.
- House state `away`; one person (`person.omonele`, state unknown).

## Thermostat — ecobee over HomeKit Controller
`climate.master_closet_ecobee_downstairs` ("Ecobee Downstairs"):
- hvac_modes off / heat / cool / heat_cool; fan_modes on / auto; min 45 / max 92; humidity target 20–50 (current 52 %, target 36).
- **No `preset_modes` on the climate entity.** Single setpoint in cool mode (`temperature` 76; `target_temp_high/low` null).
- Separate **`select.master_closet_ecobee_downstairs_current_mode`** options home / sleep / away (state `unknown` at inspection) — the ecobee comfort-setting control is exposed as a select, not as climate presets.
- **`button.master_closet_ecobee_downstairs_clear_hold`** — resume-schedule equivalent.
- Thermostat occupancy + motion binary_sensors (on), current temperature / humidity sensors.

Implications for the thermostat abstraction (HVAC-W1C-GENERIC-THERMOSTAT-1):
- Holds cannot use climate presets; the ecobee profile must hold via the Current Mode select (home/sleep/away) and/or setpoints, and release via Clear Hold.
- Person-change detection cannot key on `preset_mode == manual`; it must compare setpoint / select changes against URA's last write (context).
- No Carrier-style equipment telemetry.

## Sensors for rooms / lighting
- 10 motion binary_sensors, 9 motion events (Protect), 4 occupancy binary_sensors, 6 temperature, 2 humidity. **No illuminance sensors** — lighting darkness here will use the sun fallback unless an outdoor light sensor is configured (v5.103.28 lighting build: Global Sensors → Outdoor light sensor).

## Recommendation for this weekend
- Upgrade URA to the current release, keep **HVAC coordinator off** (or leave with no zones) until the ecobee profile exists and is validated on this house; configure rooms first.
- Ecobee profile becomes the first non-Carrier target of W1-C.
