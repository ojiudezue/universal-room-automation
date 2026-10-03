# DRAFT README section — EC-SOLAR-ENTITY-OVERRIDE-1 (EC solar power sensor override)

Plan: `docs/planning/PLANNING_ec_solar_entity_override.md` (Tier 2, PATCH).

## Problem

The Envoy's own production total broke at 23:05 on Oct 1. `/api/v1/production` reports
`wattsNow` 0 and the lifetime counter reset to 45,505 Wh. A reboot did not fix it.
`sensor.envoy_482543015950_current_power_production` is stuck at 0.0, while
`sensor.envoy_482543015950_production_ct_power` (also kW) still shows real solar.
The Energy Coordinator gets its solar input from the Envoy serial (`derive_envoy_config`).
At setup, an explicit `energy_solar_entity` already wins through the `setdefault` merge
(`__init__.py`), but no options-flow field set that key. The operator therefore had no
way to point EC at the healthy sensor.

## Fix

- **Energy Coordinator options:** new optional field **"Solar power sensor (override)"**
  (`energy_solar_entity`), placed right after the Envoy picker. Helper text: *"Leave blank
  to use the Envoy's solar reading. Pick a sensor here only if that reading is wrong."*
  Labels are in `strings.json` and `translations/en.json`.
- **Clearable:** the field uses `suggested_value`. When the field is omitted or saved as
  `""`, the key is removed from the saved options. Without this, the
  `{**options, **user_input}` merge would bring back the old value. `""` is never saved: at
  runtime `setdefault` would keep it and solar would silently read as nothing. The removal
  runs before the Envoy validation merge, so validation sees the cleared state.
- **No other production change.** Precedence (explicit beats derived) already exists at
  setup, in `validate_envoy_config`, and in repairs. A bad pick is rejected inline on the
  field with `derived_entity_missing`.
- Saving this field reloads the CM entry, which rebuilds the entity map. The key is
  deliberately **not** in `OPTIONS_RELOAD_SUPPRESS_KEYS`. Save it while the house is awake.

## Tests (`quality/tests/test_ec_solar_entity_override.py`)

| Test | Proves |
|---|---|
| `test_ec_solar_override_reaches_battery_strategy` | Real `__init__.py` merge + real `_build_entity_map` (both source-extracted) → real `BatteryStrategy`: derived=0.0 kW, CT=4.2 kW → `solar_production`=4.2, `solar_production_w`=4200 |
| `test_ec_solar_override_blank_uses_derived` | Override absent → derived entity, `energy_entity_config` dict-equal to options + `derive_envoy_config` (unchanged default); reads 0.0 |
| `test_ec_solar_override_validation_resolves_override` | `validate_envoy_config(...)["resolved"]["energy_solar_entity"]` == override |
| `test_ec_solar_override_options_roundtrip_set_and_clear` | Real options step: set → present; field omitted → absent (old value not kept); `""` → absent |
| `test_ec_solar_override_schema_exposes_field` | Form schema contains `energy_solar_entity` |
| `test_ec_solar_override_invalid_entity_rejected` | Envoy + non-existent override → form error `derived_entity_missing` on `energy_solar_entity` |
| `test_ec_solar_override_valid_with_envoy_passes_validation` | (plan-review extra) Envoy + valid override → save passes; validator resolved key = override |

### Mutation drills (source edited, suite run, restored by Python rewrite, `__pycache__` cleared, `PYTHONDONTWRITEBYTECODE=1`)

| Drill | Site | Result |
|---|---|---|
| `setdefault(k, v)` → `energy_entity_config[k] = v` | `__init__.py` Envoy derive merge | `test_ec_solar_override_reaches_battery_strategy` FAILED (1 failed, 6 passed); restored |
| Removal `saved_options.pop(CONF_ENERGY_SOLAR_ENTITY, None)` → `pass` | `config_flow.py` energy step | `test_ec_solar_override_options_roundtrip_set_and_clear` FAILED (1 failed, 6 passed); restored |

Targeted regression: the new file plus baec / solar-follow / arbitrage-guard / energy-ladder /
cycle-b config-flow / shared-power-staleness gave 150 passed.
`test_envoy_auto_derive.py` and `test_envoy_boot_decoupling.py` fail at collection with the
same error on develop with this change absent: dataclass `sys.modules.get(cls.__module__)` is
None under the py3.13 venv. This is an existing problem in the test harness, not part of this
change.

## Live acceptance (D3) — to fill after deploy (`Validated <date>` table)

- After setting the override (house awake), the log shows `CM options changed ... falling
  through to reload (changed_keys=['energy_solar_entity'])`. There is no watchdog trip or
  stall, and the CM comes back within its normal setup time.
- The `solar_production` attribute on `sensor.ura_energy_coordinator_battery_strategy`
  matches live `sensor.envoy_482543015950_production_ct_power` (allowing for rounding) while
  that sensor is above 0 in daylight. It is **not** 0.0. A 0.0 reading means the override had
  no effect.
- The `solar_age_s` attribute on the Envoy freshness sensor stays small (seconds) and does not
  climb.
- An EC DB snapshot row written after the reload has a non-zero `solar_production` in daylight.
- No new `envoy` repair issue appears.

## Not done / follow-ups

- PWA "Solar now" card (`dashboard-v3/.../Energy.tsx`) still reads the derived entity by name.
  It is display-only and needs a card (PWA-SOLAR-NOW-ENTITY-1).
- Lifetime-production reset affects `energy_lifetime_production_entity` and daily
  `solar_produced_kwh`. Needs a card (EC-LIFETIME-PRODUCTION-RESET-1).
- Overrides for all 13 derived Envoy entities, and hot-apply without a CM reload: parked
  according to the plan.
- EC manual config-surface row: not edited in this build. Add it with the release README.
