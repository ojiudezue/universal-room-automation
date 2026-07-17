# AUDIT: enphase_ev v4.0.0 upgrade — URA consumption-surface fixture (2026-07-16 ~23:45)

Hand-built fixture table (Measure Before You Build corollary). This is the
go/no-go gate for the barneyonline/ha-enphase-energy v4.0.0 upgrade and the
D0 input to PLANNING_enphase_cloud_reliance.md.

## URA's complete enphase_ev consumption surface (entity-registry verified)

| entity | platform | URA role (file:line) | v4.0.0 breaking-change exposure |
|---|---|---|---|
| number.iq_battery_hacs_battery_reserve | enphase_ev | cloud-first reserve write + oracle (energy_const.py:291, H1 topology :335) | battery controls not in breaking list — verify post-upgrade |
| switch.iq_battery_hacs_charge_battery_from_grid | enphase_ev | CFG write + oracle (energy_const.py:292) | same |
| select.iq_gateway_hacs_system_profile | enphase_ev | storage-mode write + oracle (energy_const.py:295) | same |
| sensor.iq_battery_hacs_battery_overall_charge | enphase_ev | 3-tier SOC resolver cloud fallback (energy_const.py:298; A1 staleness gate 600s :313) | same |

Attribute reads from these entities: `unit_of_measurement` ONLY
(energy_write_verify.py:891, energy_battery.py:688/775) — not on any
v4.0.0 attribute-removal list.

## Ruled OUT of blast radius (entity-registry verified 2026-07-16)

- `switch.garage_a` / `switch.garage_b` / `sensor.garage_a_power_minute_average`
  → **emporia_vue**, not Enphase. EVSE control path untouched.
- `number./select./switch.enpower_482348004678_*`, `sensor.envoy_482543015950_*`
  → **enphase_envoy (core, local)**. Grid Mode breaking change does not apply
  (grid_enabled is local). Local witness leg untouched.
- Scheduler-gated CFG/DTG/RBD schedule sensors → URA consumes none.
- Admin-only service rerouting (`request_grid_toggle_otp`, `set_grid_mode`)
  → URA calls neither.

## Verdict: LOW collision. Upgrade pre-cleared.

Post-upgrade oracle-health pass (execute within 1h of restart):
1. All 4 fixture entities exist with non-unknown state.
2. 3-tier SOC resolver resolves (battery_strategy attrs show a tier, not blind)
   once local Envoy returns.
3. One benign write round-trip verifies (write_verify status ok).
4. Zero URA ERRORs referencing the oracle entities.
Rollback: HACS pin to prior version + restart.
