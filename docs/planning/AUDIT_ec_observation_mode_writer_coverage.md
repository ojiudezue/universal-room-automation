# AUDIT — EC observation-mode writer coverage (EC-OBSERVATION-MODE-RESERVE-BYPASS-1, D3)

Branch `fix/ec-obs-mode-reserve-gate` (base develop f68dcfbff). Line numbers are on this branch.
Seed: the writer table in `docs/reviews/code-review/plan_review_ec_observation_mode_reserve_gate.md`,
re-derived by grepping `async_call|select_option|turn_on|turn_off` over
`domain_coordinators/energy*.py` plus `RESERVE_SET_VALUE_WRITERS` (`energy_const.py:2328-2340`).

INV-OBS targets: reserve number, charge-from-grid (CFG) switch, storage-mode select.

## A. `RESERVE_SET_VALUE_WRITERS`

| Writer | Role | Reaches HA via | Observation gate | INV-OBS |
|---|---|---|---|---|
| `energy_battery.py::_reserve_action` | decision-dict builder (no call) | timer dispatch, or CM path | `energy.py:6621` (timer) / `energy.py:1400` (CM, D1) | covered |
| `energy_battery.py::force_redispatch` (`:6916`, call `:7020`) | real `number.set_value` | only caller: `energy_write_verify.py::_pending_fire_retry` | `energy_write_verify.py:758` (sweep, D2) + `:2351` (chokepoint, D2) | covered |
| `energy.py::_apply_evse_battery_hold` | decision-dict overlay (no call) | timer dispatch / `_evaluate_battery` | `:6621` / `:1400` | covered |
| `energy.py::_tap_write_verifier` | reader | — | n/a | n/a |
| `energy.py::_evaluate_battery` (`:7189`) | reader + builds CM actions | CM `_execute_action` | `:1400` (D1, its only caller is `evaluate`) | covered |
| `energy.py::_execute_shed_action` (`:8752`) | pool speed | `_execute_service_action` task (`:9063`) | callers: hazard `:1459` (gated `:1426`), `_update_load_shedding` (gated `:7115`) | non-reserve; covered anyway |
| `energy_pool.py::determine_actions` | pool speed dicts | timer dispatch | `:6621` | non-reserve; covered |
| `energy_pool.py::_write_amps` (`:4962`) | EVSE amps | solar-follow `_tick_body` | `energy_pool.py:5247` gates the active path; `_restore_pass` (`:5257/:5270/:5492`) restores saved amps even when disabled | non-reserve; outside INV-OBS (note below) |
| `radar_tuning.py::async_send_radar_settings` | radar numbers | — | not energy | n/a |

## B. Switch / select writers (not in the inventory)

| Site | Target | Path | Observation gate | INV-OBS |
|---|---|---|---|---|
| `energy_battery.py:5711, :6675, :6715` (`switch.turn_on/off` dicts) | CFG switch | decision actions → timer dispatch `_execute_service_action` (`energy.py:7811`, call `:7839`) or CM path | `:6621` / `:1400` | covered |
| `energy_battery.py:6589` (`select.select_option` dict) | storage-mode select | same | `:6621` / `:1400` | covered |
| `energy.py:7446-7570` `_execute_service_action` calls inside `_execute_breaker_safe_dispatch` | reserve / CFG / select / EVSE | only caller `:6630`, inside the `:6621` block (block ends at `:7011` else) | `:6621` | covered |
| `energy.py:6680-7010` `_execute_service_action` calls (EV, plugs, fill-priority) | EVSE / plugs | inside the `:6621` block | `:6621` | covered |
| `energy.py:8840-9042` `switch.*` dicts | shed loads | `_execute_shed_action` | `:1426` / `:7115` | covered |
| `energy_pool.py` `switch.turn_on/off` dicts (`:1047` ... `:4625`) | EVSE chargers | `determine_actions` → timer dispatch | `:6621` | covered |
| `energy.py:5636` (turn_off), `:5787`, `:5934` (turn_on) | EVSE charger | `_dp_decision_tick` (`:4943`, called `:6517`, BEFORE the `:6621` gate) | NONE | outside INV-OBS — `EC-OBS-DP-EVSE-1` |
| `energy.py:6097` (turn_off) | EVSE charger | `_reconcile_dp_excess_on_restore` (`:6028`, called `:1841`) | NONE | outside INV-OBS — `EC-OBS-DP-EVSE-1` |
| `energy.py:8057` | weather `get_forecasts` | read | n/a | n/a |
| `energy_outage_ledger.py:368` | calendar `get_events` | read | n/a | n/a |
| `energy.py:7250` | not a call — CFG ledger stamp match in `_evaluate_battery` | — | `:1400` | covered |

## Result

- Every reserve, CFG and storage-mode writer is behind an observation gate after this branch:
  timer `energy.py:6621`, CM path `energy.py:1400` (D1), re-send ladder
  `energy_write_verify.py:758` + `:2351` (D2). INV-OBS holds on the enumerated surface.
- Known residual writes in observation mode, all EVSE and outside INV-OBS:
  1. DP EVSE switch writes (`energy.py:5636/5787/5934/6097`) — carded `EC-OBS-DP-EVSE-1`.
  2. **New finding (not carded):** solar-follow `_restore_pass` (`energy_pool.py:5257/5270/5492`)
     calls `_write_amps` to restore saved EVSE amps when the controller is disabled, and
     observation mode is folded into "disabled" (`:5247`). Arguably correct (it undoes URA's own
     throttle), but it is a write in observation mode. Fold into `EC-OBS-DP-EVSE-1` or card separately.
- In-flight race (accepted per plan): a CM batch returned before the mode flips still executes.
