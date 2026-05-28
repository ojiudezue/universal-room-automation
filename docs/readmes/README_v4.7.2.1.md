# v4.7.2.1 — Occupancy-Weighted Prediction Restore Hotfix

**Type:** Hotfix (Tier 1)
**Base:** v4.7.2

## Problem

`switch.ura_energy_occupancy_weighted_prediction` flipped OFF after every HA restart regardless of the user-saved state. If the user had enabled occupancy-weighted energy prediction (switched ON), that setting was silently lost on each restart.

**Root cause:** The prior `OccupancyWeightedPredictionSwitch` was a bespoke standalone class predating the `_ec_switch_factory` pattern. It used `RestoreEntity` to read the prior state but had no `SIGNAL_ENERGY_COORDINATOR_READY` subscription and only a single 5s timer retry. When the EnergyCoordinator was not yet registered at `async_added_to_hass` time (the v4.5.3-retry-budget startup race, Bug Class #5), the restored value was never written to `EnergyCoordinator.occupancy_weighted`. The EC's constructor seed (`occupancy_weighted_energy` from cm_entry config, which does not change when the user toggles via the UI) became the visible state — always False.

## Fix: Path 1 — Factory Conversion

Replaced the bespoke `OccupancyWeightedPredictionSwitch` class (88 lines) with a single `_ec_switch_factory(...)` call.

The factory already implements the correct deferred-restore lifecycle (v4.5.3 retry chain: 5s/30s/120s) and the v4.7.x D2 `SIGNAL_ENERGY_COORDINATOR_READY` subscription (Bug Class #38 compliant). This is the same pattern used by all other EC runtime toggle switches.

The `unique_id` suffix `occupancy_weighted_prediction` is preserved, keeping the entity ID `switch.ura_energy_occupancy_weighted_prediction` stable across the upgrade.

## Counter Bump

`EnergyCoordinator._pending_sub_switch_restores` bumped from **5 → 6**. `OccupancyWeightedPredictionSwitch` now participates in the `binary_sensor.ura_energy_coordinator_ec_sub_switches_synced` health sensor's tracked-switch count.

## Files Changed

- `custom_components/universal_room_automation/switch.py` — bespoke class removed; factory call added after existing EC factory calls
- `custom_components/universal_room_automation/domain_coordinators/energy.py` — `_pending_sub_switch_restores` init: 5 → 6
- `quality/tests/test_v4721_occupancy_weighted_restore.py` — 12 new tests
- `quality/tests/test_v4503_ec_switch_restore.py` — one-line search fix: `find("_ec_switch_factory")` → `find("def _ec_switch_factory(")` to prevent the source-grep from matching the new factory call comment before reaching the factory definition
