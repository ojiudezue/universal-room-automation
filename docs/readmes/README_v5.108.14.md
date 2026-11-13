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

## Live validation (to fill after restart)

- Installed version v5.108.14.
- `sensor.ura_hvac_pre_arrival_status` shows the four new attributes.
- No URA ERROR in the log after restart.
- `sensor.ura_energy_coordinator_energy_import_today` friendly name "Net Grid Today".
- Organic: next arrival into a zone at or below target produces a `pre_arrival_standdown` row and no climate write;
  INV-SD-COOL check mode (D0 probe) over 3 days shows zero violating rows.

## Not done from the plan

- D5 trip-wire parked (would page for normal weather); revives on a wrong stand-down.
- Single `heat` mode for the heat leg parked (unverified range writes on non-Carrier thermostats).
- Cool-side cap when Solar Banking Cool Floor is set below Home heat: HVAC-PRECOOL-FLOOR-BELOW-ARRIVAL-HEAT-1.
- Energy pre-cool also never reads zone temperature: separate follow-up (review L4).
- Accepted LOWs: A-L3 (one row lost if a zone leaves and re-enters during master-off), B-L1 (arrival pre-heat blocks
  that day's energy pre-heat on the zone).
