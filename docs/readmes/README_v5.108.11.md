# v5.108.11 — Four Tier-1 fixes

Cards: FAN-RECHECK-FORM-RESTORE-REVERT-1, SC-GEOFENCE-PERSON-SNAPSHOT-1, KANBAN-SHIP-FLOW-CARDS-1,
EC-CFG-SELFHEAL-FALSE-CRITICAL-1. Each had one Tier-1 review (SHIP) and per-site mutation drills.

## Fan re-check switches follow the saved settings

Saving the fan re-check settings in a room's form was undone after the reload: the four on/off
switches (house master, per-room enabled, per-room L2 allowed, and the mirrored trust switch)
restored their remembered state over the new options. The runtime reads the options, so the room ran
one way while the dashboard showed the other (Garage A: options off, switches on). The switches now
take the options value when one is present and fall back to the remembered state only when it is
not. `switch.py`; tests `quality/tests/test_fan_recheck_options_wins_restore.py`.

## Security follows people added after startup

Security's arrival watcher read the person list once at setup, so a person added later, or one that
loaded after URA, was never watched. It now subscribes to person add and remove and rebuilds its
listener, reusing the lock regime's pattern. `security.py` (domain_coordinators); tests on the real
method.

## Release script updates single-line cards

`kanban_ship.py` skipped cards written as one JSON-style line, so shipped cards stayed in review.
It now edits them, and warns (still exit 0 after the push) when it cannot. Repo tooling only.

## No false CRITICAL self-heal page when the battery setting already matches

The write verifier paged "charge_from_grid=True 3 consecutive cycles" on 11-08 although the cloud
switch had flipped to the commanded value 0.3 s earlier. Before the third-repeat page it now
re-reads the oracle with the same comparison the 15-minute check uses; if it matches, the counter
resets and nothing pages. Applies to reserve, charge_from_grid and storage_mode. An unavailable
oracle or a unit mismatch still pages. `energy_write_verify.py`; tests
`quality/tests/test_ec_cfg_selfheal_reread.py`.

## Suite

Full serial suite 20615 passed, 0 failed (baseline 49878819: 0 failed). The first merged run had 6
new failures from the security change: a garage-lockout test whose fake hass lacked the new
added-domain tracker, and five order-dependent failures from a stubbed `callback`. Fixed in tests only
(ff98b438); production code unchanged.

## Held out

HVAC-ZONE-KWH-SEED-WARN-WORDING-1: review found the fix targets a warning branch that most likely
never fired. Back to investigation; this release's restart is used to capture the real reason.

## Validated 2026-11-12 (restart 12:55 CST, house home_day)

| Criterion | Result | Evidence |
|---|---|---|
| Installed | PASS | `update.universal_room_automation_update` installed_version v5.108.11; HA manifest v5.108.11 |
| Garage A fan re-check follows options | PASS | `switch.garage_a_garage_a_fan_recheck` off and `..._l2_allowed` off (were on before; options off); `switch.ura_presence_coordinator_fan_recheck` on |
| No URA ERROR after restart | PASS | system_log, search universal_room_automation: WARNING only (boot transients: 60 s sensor hold, Bermuda polling fallback, census cameras not ready, Envoy booting) |
| Security geofence listener sets up | PASS | no security/geofence entry in system_log |
| Zone-kWh seed reason captured | captured | all three zones: "no RestoreState entry for number.ura_hvac_coordinator_ac_kwh_rate_threshold_*", yet the Numbers restored (zone 1 = 1.0, zones 2/3 = 0.8); recorded on HVAC-ZONE-KWH-SEED-WARN-WORDING-1 |
| No false self-heal CRITICAL | organic | needs the next CFG/reserve write episode; disposition via the `--revisit` discriminator |
