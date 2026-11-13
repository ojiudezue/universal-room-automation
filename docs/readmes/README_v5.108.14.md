# v5.108.14 — Pre-arrival stands down when the zone is already cool; arrival pre-heat; Net Grid Today

Cards: HVAC-PRECOOL-STANDDOWN-WHEN-COOL-1, EC-IMPORT-TODAY-NET-AFTER-RESTART-1.
Plan: `docs/planning/PLANNING_hvac_precool_standdown_and_seasons.md` (rev 4, operator-approved 2026-11-12).
Reviews: plan reviews (rev 1, rev 3), code reviews A (FIX), B (SHIP), D (SHIP + one pre-existing MEDIUM), all fixed in
8175df62. Tier 2-DB.

## Pre-arrival pre-cool stands down when the zone is already cool

Before this release, an arrival pre-cool wrote to the thermostat whatever the zone's temperature: 17 of 44 writes from
11-01 to 11-12 landed on a zone already at or below the target (D0 probe,
`scripts/probes/hvac_prearrival_conditioning_probe.py`). Now the pre-arrival leg compares the thermostat's own reading
with the target it would set. At or below the target: no borrow, no write, one `pre_arrival_standdown` activity row per
arrival. It re-checks every tick, so a zone that warms during the window is still pre-cooled. A missing reading writes
as before. Energy pre-cool is unchanged. Margin is a module constant at 0 F (Carrier reports whole degrees). There is no
season gate: the target already follows each season's Home setting (operator ruling).

## Arrival pre-heat (new, all homes)

The mirror for heating: on an arrival, heat to the season's Home heat setting + 2 F, capped at the arrival preset's
cool and 2 F below the live cool setpoint; stand down when the zone is already that warm; skip when no valid band is
left (`band_inverted`). Runs only when the thermostat is in `heat_cool` (single `heat` mode parked) and fails closed
(no write) if the live reading or mode is missing. Uses the same pre-arrival borrow lifecycle as pre-cool, caller site
`S13_pre_arrival`. In Texas November no arrival would have pre-heated (D0).

## No stray thermostat writes on release

- Switch 28 (HVAC Predictive Conditioning) off: a zone that never started a pre-arrival borrow gets no write.
- Energy pre-cool gate off: it no longer ends a live pre-arrival borrow, and (pre-existing bug, review D-M1) no longer
  writes the baseline to a zone with no borrow, e.g. one a person set under Temp Arrester Override.
- The one-shot post-restart energy pre-cool reconciliation applies the same rule. The boot audit already closes and
  restores every interrupted borrow, so in practice this path no longer writes.

## Observability

`sensor.ura_hvac_pre_arrival_status` gains `prearrival_skips`, `prearrival_standdowns_today`, `precool_writes_today`,
`preheat_writes_today` (daily counters, reset on restart).

## Net Grid Today

`sensor.ura_energy_coordinator_energy_import_today` has always been net (import minus export) by design. Its display
name is now "Net Grid Today" (icon transmission tower); entity_id and unique_id unchanged. Gross import stays in the
`import_kwh` attribute (the v8 dashboard "From grid" tile reads it). User manual corrected.

## Validated 2026-11-12 (restart 21:10 CST, house home_night)

| Criterion | Result | Evidence |
|---|---|---|
| Installed | PASS | `update.universal_room_automation_update` installed_version v5.108.14; HA manifest v5.108.14; PR #694 diff carries hvac_predict/hvac/hvac_const/hvac_override/sensor changes |
| New status attributes | PASS | `sensor.ura_hvac_coordinator_hvac_pre_arrival_status` (idle): `prearrival_skips` [], `prearrival_standdowns_today` 0, `precool_writes_today` 0, `preheat_writes_today` 0 |
| No URA ERROR after restart | PASS | system_log, search universal_room_automation, level ERROR: 0 entries |
| Net Grid Today | PASS | `sensor.ura_energy_coordinator_energy_import_today` friendly name "URA: Energy Coordinator Net Grid Today", state 1.47, `import_kwh` 20.642 |
| Stand-down on a real arrival | organic | needs the next arrival into a zone at/below target; disposition via the `--revisit` discriminator (D0 probe check mode) |
| Pre-heat | in-suite only | no November arrival is below the heat target (D0); covered by 76 tests and per-site mutation drills |

Suite: full serial suite 0 failed / 20801 passed, zero new names vs 4e3ca3bc; isolation of 110 HVAC test files clean except two
pre-existing order-dependent files that fail identically at the baseline.

## Not done from the plan

- D5 trip-wire parked (would page for normal weather); revives on a wrong stand-down.
- Single `heat` mode for the heat leg parked (unverified range writes on non-Carrier thermostats).
- Cool-side cap when Solar Banking Cool Floor is set below Home heat: HVAC-PRECOOL-FLOOR-BELOW-ARRIVAL-HEAT-1.
- Energy pre-cool also never reads zone temperature: separate follow-up (review L4).
- Accepted LOWs: A-L3 (one row lost if a zone leaves and re-enters during master-off), B-L1 (arrival pre-heat blocks
  that day's energy pre-heat on the zone).
