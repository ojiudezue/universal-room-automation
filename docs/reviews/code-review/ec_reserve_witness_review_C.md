# Review C (test authority, real per-site mutation) - fix/ec-reserve-witness-envoy-sensor @ 76ca12e39 (base f9fb1f5ba)

Suite per drill: test_ec_reserve_witness_resolution.py + test_energy_behavioral_write_verify.py (baseline 50 passed). PYTHONDONTWRITEBYTECODE=1, __pycache__ cleared each run, source restored in try/finally; git status clean after.

| # | Site neutered (energy_write_verify.py unless noted) | Result | First RED test |
|---|---|---|---|
| M1 | reserve-branch-only scoping -> all surfaces | RED | test_cfg_and_storage_mode_witness_unchanged |
| M2 | envoy_eid short-circuit skipped | RED | test_reserve_witness_prefers_envoy_sensor_via_registry |
| M3 | `if serial else None` guard removed | GREEN | none |
| M4/4b/4c | log-once flag: always / never / never set | RED | test_reserve_witness_disabled_sensor_treated_unresolvable |
| M5 | disabled_by check | RED | same |
| M6 | sensor domain filter -> number | RED | test_reserve_witness_ignores_number_domain_same_unique_id |
| M7 | platform == enphase_envoy | RED | test_reserve_witness_anchor_not_envoy_falls_back |
| M8 | SOC suffix endswith | RED | test_reserve_witness_anchor_not_soc_unique_id_falls_back |
| M9/M9b | const suffixes (energy_const.py) | RED | prefers_envoy_sensor_via_registry |
| M10 | resolver consults state (unavailable->fallback) | RED | test_reserve_witness_unavailable_sensor_abstains_not_fallback |
| M11 | `_local_reserve_witness_state` unavailable/unknown guard | GREEN | none (equivalent mutant: float("unavailable") raises ValueError, caught -> (None,None)) |
| M11b | reader resolves no eid | RED | test_watchdog_no_alert_when_envoy_sensor_matches_command |
| M12 | watchdog abstain (hw_value None) | RED | test_pending_hardware_witness_unavailable_abstains (+ new abstain test) |
| M13 | _witness_compare local_raw-None abstain | GREEN | equivalent: _compare(None) returns INCONCLUSIVE -> matched False/UNMAPPED path... redundant guard |
| M14 | _witness_compare no-local_eid abstain | GREEN | equivalent: _read_oracle_raw(None) returns None, then M13 guard |
| M15 | hw_witness_entity populated -> None | RED | test_pending_stuck_row_carries_hw_witness_entity |
| M16 | command_trail hw state | RED | test_command_trail_reports_three_distinct_witnesses |
| M17 | command_trail hw_age_s eid resolution | GREEN | none (display-only age) |
| M18 | anchor lookup disabled | RED | prefers_envoy_sensor_via_registry |
| M19 | serial slice | RED | prefers_envoy_sensor_via_registry |
| M20 | registry exception swallow | RED | test_reserve_witness_registry_raises_falls_back |

## Findings
- LOW (Bug Class #62-adjacent, untested site): M3 `if serial` guard. Only reachable when a unique_id is exactly "_battery_level" (empty serial -> looks up unique_id "_reserve_soc"). A one-line test (anchor unique_id == "_battery_level" with a sensor registered at "_reserve_soc" -> falls back) would pin it. Not ship-blocking.
- LOW: M17 hw_age_s in command_trail has no assertion (display-only value).
- M11/M13/M14 GREEN rows are equivalent mutants (redundant defensive guards; downstream code abstains identically), not test gaps. Abstain behavior as a whole is pinned: M12 and M10 go RED.
- All five readers' abstain paths: watchdog (M12 RED), reader (equivalent), witness_compare (equivalent, redundant), command_trail (M16 RED), hw_witness_entity (M15 RED).

## Verdict: SHIP (optionally add the M3 test, 1-5 LoC, in-cycle per Fix-LOWs rule).
