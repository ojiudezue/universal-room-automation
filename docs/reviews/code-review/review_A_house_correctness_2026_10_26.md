# Review A — local correctness + edge cases (house sensors correctness, 2026-10-26)

Framing A only (arithmetic, clamps, units, None/unavailable, day boundaries, consumers).
Base `95c9e4449` (merge-base verified) — three-dot diffs `develop...<branch>`.

## fix/house-energy-correctness (6597e4cbc) — SHIP

| Sev | Site | Finding |
|---|---|---|
| LOW | `energy_forecast.py` `get_adjustment_factor` (`usable[-7:]`) | Window is now "last 7 usable" drawn from a 30-deep deque (`ACCURACY_WINDOW_DAYS=30`), so with many skipped pairs the mean can reach back ~30 days instead of 7. Acceptable (stale > pinned), but undocumented. Bug class: none (semantics note). |
| LOW | `aggregation.py` `WholeHouseCostTodaySensor.extra_state_attributes` | `rate_used` / `rate_source` are still published but no longer participate in the value (value = EC `cost_today`). Display-only; misleading for anyone back-deriving cost. |
| INFO | `database.py` week/month loops | Oldest week/month in the window can still be partial at the start of history (filtered only on `record_count>0`). Pre-existing; first-weeks underestimate. |
| INFO | decision path | Factor feeds `energy_forecast.py:424` → `predicted_consumption` → `energy.py` `_dp_house_load_kw` `base_kw` (`max_span_r1` default for other installs). Factor un-pins from 1.3 → base_kw drops ~up to 23% on those installs. Intended correction, but it IS a decision-input change; README should say so. |

Holds:
- `_factor_pct_error`: None-safe; both sides gated 10..240 kWh before division (predicted≥10 → no div-by-zero); clamp ±60 applied after. Restore path (`restore_from_db`) recomputes from the pair, so restored rows and live rows are homogeneous. Rows from before the change carry no key → `e.get(...) is None` → skipped; factor returns 1.0 until 3 usable — safe.
- `pct_error` stored/returned unchanged (control-path byte identity preserved).
- `DATE(timestamp) < utcnow().date()` — `log_energy_history` writes `datetime.utcnow().isoformat()` and UTC weekday, so the same clock throughout; "tomorrow" path unaffected.
- Month loop `range(1, n+1)` with the existing `while month <= 0` wrap — January handled.
- `_predicted_import_rate`: `ec_tou` = `get_effective_import_rate` (base+delivery+transmission, `energy_tou.py:555-557`) → no add-on; static fallback adds delivery. All 4 predicted-cost sites routed; export path unchanged.
- `cost_today` read via `ec.cost_today` (`energy.py:11982`), non-numeric/exception → None; MONETARY+TOTAL accepts negative net cost.

## fix/house-diagnostics-correctness (58cbfa70c) — SHIP

| Sev | Site | Finding |
|---|---|---|
| MEDIUM | `energy_circuits.py` `_is_expected_on` (mean − 2σ > 5 W) | Detection-coverage tradeoff: a high-variance always-on circuit (fridge/freezer cycling e.g. mean 100 W, σ 60 W) now fails the gate and can no longer raise `tripped_breaker`. Consistent with the stated design, but the false-negative class (refrigeration) is the one that matters most; worth an operator-visible note / per-circuit allowlist card. Bug class: detector over-suppression. |
| LOW | `routine_forecaster.py` ETA | When `elapsed` exceeds every sample the ETA is None (good); when only 1–2 long-tail samples survive, the median is computed from them with no min-count — noisy but bounded. |

Holds:
- Verdict computed BEFORE `baseline.update(power)` and latched only when `zero_since` is first set; reset path (`power > threshold` clears `zero_since`) re-latches on the next drop. Default `expected_on_at_drop=False` = fail-quiet.
- RF: aware/naive mismatch in `now_utc - entered_at` caught → elapsed 0 and `ref_local` stays now (assigned after the subtraction). Cell keyed on entry time matches the refresh walk (`cell_ref = prior_ts`, ~line 424).
- `count_available_sensors` is the sole producer for state and attribute; missing entity counts unavailable; `sensor.py` attribute no longer echoes `sensors_monitored`.

## fix/scanner-areas-own-area (5b8a33bc7) — FIX-REQUIRED

| Sev | Site | Finding |
|---|---|---|
| HIGH | `config_flow.py:1181-1195` | `strip_own_area` was inserted BETWEEN `@instrument_flow` and `class UniversalRoomAutomationConfigFlow`. The decorator now wraps the helper function, and the ConfigFlow class is no longer instrumented (`CONFIG_FLOW_TIMING = True`, `_cflow_timing.py:49`). Silent loss of CFLOW-TIMING on every config-flow step; the function still works only because `instrument_flow` returns its arg. Fix: move the helper above the decorator. Bug class: misplaced decorator / silent instrumentation loss. |
| LOW | options flow strip uses `self._get_current(CONF_AREA_ID)` | If the same submission changes the area, the strip uses the old area. Runtime filter in `person_coordinator.py:1373` covers it, so effect is cosmetic. |

Holds: runtime filter applied before the Tier-1 `_direct_ble_rooms` decision; None/empty lists safe; default shown in options form is pre-stripped.

## Verdicts
- house-energy-correctness: **SHIP**
- house-diagnostics-correctness: **SHIP** (MEDIUM is a design note; card it)
- scanner-areas-own-area: **FIX-REQUIRED** — move `strip_own_area` above `@instrument_flow`.
