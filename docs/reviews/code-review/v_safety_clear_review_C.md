# Safety clear-on-recovery — Review C (test authority via per-site source mutation)

Branch `feature/safety-clear-on-recovery` @ cca8826c7, base 434d8f1f0 (merge-base with develop).
Baseline: `test_safety_hazard_clear_on_recovery.py` + `test_safety_coordinator.py` = 163 passed.
Method: one string-mutation of `domain_coordinators/safety.py` per site, `PYTHONDONTWRITEBYTECODE=1`,
`__pycache__` cleared before every run, original restored in `finally`; tree verified clean.

## Drill table (82 single-site + 5 pair drills)

RED (killed, named test) — 66 sites, including: binary recovery + hold bypass (`test_binary_hazard_smoke_off_clears`),
flooding-on-last-dry, CO2 log-only hysteresis/relapse/MEDIUM anchor, severity-None hysteresis + CO/TVOC offsets,
freeze/overheat/high-hum/low-hum offsets + recovery, freeze/high-hum/low-hum relapse, hold const + compare,
`:roc` suffix / `from_roc` / raise_rate / raise_z, I2 whole + type-conjunct + each of smoke/CO/leak,
set-if-absent, discard, relapse pending-cancel, `_pop_hazard_key` raising pop, ROC None/fraction/z/frac=0/stale both
directions, sweep writer 2 / life-safety-never-drops / window 0+never / drop-arms-hold / ROC block / final try-clear,
writer 1, sweep-outside-flooding-guard, clear_hazard roc+unstamp+raising, clear_all x3, teardown x3,
is_hazard_active roc-strip + exact-match.

GREEN (survived) — findings:

| Site | Sev | Note |
|---|---|---|
| register-before-early-return (safety.py `_process_hazard`, register only when new) | HIGH | Green alone; red only paired with relapse re-add. Only numeric second-raiser is tested. Binary path has no relapse call, so a 2nd smoke/leak sensor in the same room at same severity (not is_new) is unregistered → 1st sensor dries → key clears after hold while 2nd still wet. Needs binary 2-sensor test. |
| I2 `had_pending_clear` conjunct dropped | MED | Every repeated life-safety raise would re-run full response (valve/lights/HIGH page). No test asserts no re-response without pending. |
| `_process_hazard` pending-cancel pop | MED | Green alone (try_clear contributor check masks it). Stale pending survives re-wet → next dry clears with NO hold. Pair red. Needs re-wet→dry→assert-held test. |
| `tryclear` contributor check | MED | Green alone; same pair. |
| overheat relapse | MED | Freeze analogue tested, overheat not. |
| `_UNAVAILABLE_DROP_TYPES` entries (high_humidity, freeze_risk, high_co2 each) | LOW | Only low-humidity drop exercised. |
| unstamp in recovery / relapse / sweep (triple) | LOW | Pair of 3 green; all 4 red. Stale stamp → premature drop on a 2nd short outage (comfort types only). |
| `_record_sensor_recovery` active guard + orphan sweep (pair green) | LOW | Bookkeeping hygiene only. |
| `_pop_hazard_key` pending pop; clear_hazard pending pop; ROC no-history | LOW | Benign / unreachable after get_rate None. |

Boundaries: tests use hardcoded literals (47.9 / 48.0 / 97.0 etc.), not imported constants — PASS.
D6: `test_tvoc_detection` now seeds `_tvoc_above_since` with aware `dt_util.utcnow()` matching production — PASS.

## Verdict: FIX-REQUIRED
Must-fix: binary two-sensor not-is_new registration test; pending-cancel re-wet hold test; I2 no-pending-no-rerun test.
Should-fix: overheat relapse test; drop-type parametrization.
