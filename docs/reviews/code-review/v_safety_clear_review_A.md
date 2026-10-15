# Review A — local correctness / edge cases / config extremes
Branch feature/safety-clear-on-recovery @ cca8826c7 vs merge-base 434d8f1f0 (verified = develop HEAD). Targeted tests: 163 passed (test_safety_hazard_clear_on_recovery.py + test_safety_coordinator.py).

## Clear-line anchoring (builder vs plan)
Builder is RIGHT. `_classify_severity` (safety.py:2072) returns LOW at CO>=25 and TVOC>=250 (TVOC below MEDIUM falls through to classify, :2032), so LOW is a raising rung. Plan's "MEDIUM - offset" (CO 33 / TVOC 450) would clear at e.g. CO 30, which re-raises LOW on the next sample: flap and a cleared life-safety key while CO is above 25. CO 23 / TVOC 200 / CO2 1400 (MEDIUM when co2_low<=MEDIUM, else table LOW, :1981) / freeze 48 / overheat 97 / humidity low-3 / low-humidity 33: all correct.

## Findings
- **LOW** safety.py:2042 — in-band (23<CO<25) reading after recovery doesn't relapse, so the hold can expire with CO at 24.9. That's standard one-way hysteresis, and it's below the raise line. The CO2 path (:1997) does relapse in-band, so the two paths behave differently. Harmless, but should be documented.
- **MEDIUM (pre-existing shape, I2 holds)** safety.py:1889: re-wetting during the hold, when it escalates to flooding, returns FLOODING before `_process_hazard(water_leak)`, so the water_leak key's pending clear isn't cancelled. Repro: B (laundry) wet, then dry → pending; A (kitchen) wet; B re-wets within 300 s → active={A,B} → FLOODING returned. `water_leak:laundry` then pops at the next sweep while B is wet. No response is lost: FLOODING is new and gets the valve via :2745. Baseline popped that key on B-dry anyway. Card it, don't block.
- **LOW** ROC: `rate_detector.clear()` on unavailable→valid (:1603) makes `get_rate` None, so the ROC contributor counts as recovered immediately. Only comfort/HVAC_FAILURE types, fine.

## Builder's open question (A off, B on, A re-triggers)
No response is lost for SMOKE, CO or WATER_LEAK. The key never stopped being active. B keeps the contributor set non-empty, so `_record_sensor_recovery` (:2850) doesn't arm a pending clear. Valve, siren and page from the original raise were never undone (nothing in the diff reopens valves). The old re-run was a side effect of the old bug (A-off popped a key while B was still in alarm). When every sensor goes off and then one re-triggers, the rearm fires correctly (:2475).

## Unavailable / extremes
Unavailable returns early before the binary handler (:1589), and smoke/CO/leak aren't in `_UNAVAILABLE_DROP_TYPES`, so an unavailable smoke sensor never clears. That's PASS. HOLD=0 clears immediately on recovery. HOLD=86400 never clears, and rearm still fires during the pending window. ROC fixed vs z-score mode compare like with like (:2885-2893).

## Verdict: SHIP
No must-fix items. Two follow-up cards: the flooding-preempts-leak pending clear, and documenting the CO/TVOC hysteresis asymmetry.
