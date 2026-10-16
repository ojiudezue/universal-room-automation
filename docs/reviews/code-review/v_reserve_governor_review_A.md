# Reserve write governor — Review A (local correctness)

Branch `feature/reserve-governor`, diff `53b3ecb8f..1c5d9bc97`. Merge-base verified: it equals 53b3ecb8f. Production surface: energy.py, energy_battery.py and energy_const.py.

| # | SEV | Site | Finding |
|---|---|---|---|
| A-1 | LOW | energy.py `_record_reserve_dispatch` (DB write) | `db.log_activity` is a direct INSERT (database.py:6233), not the serialized `_write_queue`. It runs fire-and-forget through `hass.async_create_task` and is never awaited on the tick. This is the same contract as the HVAC climate_write row, and the change gate keeps volume low. Parity accepted, no fix needed. |
| A-2 | LOW | helper, `int(battery.reserve_soc)` | If `reserve_soc` is ever None, the floor computation raises and the whole row is dropped silently at debug level. Dispatch is unaffected because the outer guard contains it. The value is set at energy_battery.py:418 from config and is int in practice. |
| A-3 | INFO | helper gate memo | The memo key includes `path`, so alternating timer and evaluate writes defeat the gate and write extra rows. This over-logs and never under-logs, which is the safe direction. |

## Per-check verdicts
- **inclement_floor arithmetic:** holds. `max(int(reserve_soc), int(dec.reserve_floor))` only when `hold_depth == "partial_hold"`, otherwise None. Same expression as energy_battery.py:5873 feeding `_floor_reserve` (3868). full_hold and allow_discharge give None, so `floor_ok` is None. `reserve_floor` is typed int (inclement.py:502).
- **Numeric pre_state:** holds. `_get_state_float` (energy_battery.py:881) maps the string "10.0" to 10.0, and unavailable/unknown/missing/non-numeric to None. None means always write. The compare is `int(round(float(pre_state))) == value_i`.
- **Gate key:** holds. The skip needs status APPLIED or DEFERRED, a non-redispatch path, key equal to the memo, and pre_state equal to value. FAILED rows and all redispatch rows bypass the gate. The memo is updated only after a row is actually scheduled. A missing DB returns before the memo update, so nothing is masked later.
- **Status vocabulary:** holds. `WriteStatus` is imported from hvac_strategy.py:238 (str Enum) and stored as `.value`. The C3 sites import the same enum locally.
- **C1 (timer):** holds. Gated on `reserve_eid and target == reserve_eid and value is not None`. FAILED iff `dispatch_result` is present and not ok. pre_state is read before the `await _execute_service_action`, which is the correct capture-before-await ordering. The tap's own filter and the ledger stamp are untouched.
- **C2 (evaluate/CM):** holds. Fires only for `number.set_value` on the resolved reserve entity. A None value makes `int(None)` raise inside the helper's guard, so no row is written and nothing propagates.
- **C3 (redispatch):** holds. FAILED fires after the failure record and APPLIED fires after the step-5 ledger stamp. Each sits in its own try block reached through getattr only, so it cannot re-enter the service-call except or skip the stamp. `live_desire` is already int-coerced (around 6795). The fixed reason string is an acceptable deviation.
- **Exception containment:** holds. The whole helper body is inside a try/except. Every added read at C1 and C2 has its own try block that falls back to None. Nothing written by the helper is read by the dispatch, ledger, verifier or CFG paths. The only state it mutates is `_last_reserve_row_key`.
- **Byte-identical dispatch:** holds. The only additions on the dispatch path are pure state reads and one new keyword-only kwarg with default None. The `_cfg_eid` / CFG ledger logic and action iteration order are unchanged.
- **Builder deviations:** pre_state keyed on `target == _res_eid` is correct, because only the reserve entity is compared. The C3 reason string is acceptable. The inline getattr guards are correct for test stubs.

## Verdict: SHIP
No CRITICAL, HIGH or MEDIUM findings. The LOWs need no fix.
