# Review B — house correctness branches (2026-10-26)

Framing B: integration, lifecycle, restart, cross-coordinator ripple, no-flap.
Base 95c9e4449, three-dot diffs. Presence doc §3 (BLE / scanner ladder) read for the scanner branch; live
`core.config_entries` read-only.

Merge check: scratch worktree off 95c9e4449, merged energy → diagnostics → scanner → develop: all clean, no
conflicts. The 7 cycle test files on the merged tree: 83 passed. Worktree removed.

## fix/house-energy-correctness (6597e4cbc) — SHIP (one MEDIUM to note)

| Sev | Where | Finding |
|---|---|---|
| MEDIUM (ripple, not a bug) | `energy_forecast.py` `get_adjustment_factor` → `_adjustment_factor` applied at `energy_forecast.py:454` | The factor leaves 1.3 (pinned) and drops to about 1.0, so `predicted_consumption_kwh` falls about 23%. This is not display-only. It feeds `_dp_house_load_kw` r1_base (`energy.py:4907-4958`), which the live `_dp_decision_tick` uses (`energy.py:5314`) when DP is enabled (default `max_span_r1` = max(live, base)). It also feeds the battery-full ETA (`energy_forecast.py:698`) and predicted net exchange (`energy.py:12511`). The direction is a correction. Live validation should record DP `house_load_kw` before and after. |
| LOW | `energy_forecast.py:871,916` | Restore recomputes `pct_error_factor` from DB pairs, so the factor is correct right after a restart. If rows are missing the key, `.get` skips them and the factor falls back to 1.0 below 3 usable rows. Fail-safe. |
| LOW | `aggregation.py:3098-3114` | Cost Today now mirrors `ec.cost_today`. EC missing → None (unknown), not 0. Until `restore_daily` (`energy.py:2681`) runs, the sensor can briefly read 0.0. The midnight reset happens on the first `accumulate` tick after the date change (`energy_billing.py:402`), so yesterday's value can show for up to about 5 min. State class is TOTAL with no `last_reset`, so long-term stats record the nightly drop and the one-time drop from $1,978 as negative change. Display only. |
| clear | `database.py:3160-3260` | Partial-period exclusion is read-only SQL/loop bounds. No writer or queue change. |

## fix/house-diagnostics-correctness (58cbfa70c) — SHIP after the operator accepts M1

| Sev | Where | Finding |
|---|---|---|
| MEDIUM (M1, product decision) | `energy_circuits.py:381-383`, `_is_expected_on` `:421-427` | The gate also suppresses genuine trips on cycling loads that matter, such as fridge, freezer and sump circuits: mean − 2σ ≤ 5 W, so `expected_on_at_drop` is False. Both downstream paths read this monitor's anomalies: the EC alert/NM route (`energy.py:7246-7281`) and the NM digest at `importance="critical"` (`energy.py:10160-10199`). A tripped fridge breaker will now never page. Alternative worth weighing: discriminate on exact 0.0 W (true trip) against standby watts, or add an operator allow-list of critical circuits. |
| LOW | `energy_circuits.py:306-309` | The verdict is captured before `baseline.update` (good). Baselines are restored from the DB (`restore_baselines` `:457`), so a restart does not blind the gate unless a circuit has fewer than 60 samples. |
| clear | `safety.py:3313-3345`, `sensor.py:6945` | `count_available_sensors` is the same loop that was there before, extracted. `get_diagnostics_status` returns the same values, and only the `sensors_available` attribute changes. No grep hit for a reader of that attribute: no page, no decision. |
| clear | `routine_forecaster.py:481-553` | Entry-time cell keying plus remaining-ETA. The only consumer is `presence.get_next_state_prediction` (`presence.py:2319`) → sensor (`sensor.py:6651`), display/PWA only. The prediction shape is unchanged. Before the refresh walk `_last_row_ts` is None, so it falls back to the old shape. |

## fix/scanner-areas-own-area (5b8a33bc7) — FIX-REQUIRED (one MEDIUM, trivial)

| Sev | Where | Finding |
|---|---|---|
| MEDIUM | `config_flow.py:1181-1183` | `strip_own_area` was inserted between `@instrument_flow` and `class UniversalRoomAutomationConfigFlow`. The decorator now wraps the function, and the ConfigFlow class loses its step timing (`CONFIG_FLOW_TIMING = True`, `_cflow_timing.py:49`). It also logs a spurious "instrumented strip_own_area (0 step handlers)". The function still works because the decorator returns its argument. Fix: move the def above `@instrument_flow`. |
| clear | `person_coordinator.py:1372-1376` | Live config: 13 rooms have `scanner_areas`, and none contains its own `area_id`. `_direct_ble_rooms` is unchanged for every live room, so there is no behaviour change today. The Tier-2 lookup is unfiltered, which is harmless because the own area maps to the same room. |
| clear | `config_flow.py:12587-12593, 13338-13341` | The options default pre-strips. On submit, a stored own-area entry is removed, which causes the normal single-room entry reload. Nothing changes until a user submits. |

## Verdict
- energy: SHIP. Record the DP `house_load_kw` shift in live validation.
- diagnostics: SHIP once the operator accepts that cycling-critical circuit trips will no longer page (M1), or add an exact-zero / allow-list path.
- scanner: FIX-REQUIRED. Move `strip_own_area` above `@instrument_flow`.

Bug classes: decorator displacement (lifecycle/instrumentation drift); #53-adjacent ripple (factor → DP decision); coverage loss on a safety-adjacent detector (M1).
