# v4.5.18 — Data Quality Reporting Correction

**Date:** 2026-05-12 CDT
**Type:** Tier 2 cycle (two independent staff-engineer reviews per user direction "prediction must be rock solid")
**Predecessor:** v4.5.17 (Bayesian eval NameError fix, deployed earlier today)

## Summary — read this first

**This is a REPORTING-ONLY fix. Prediction quality is unchanged.**

The persistent ~91% Bayesian data quality reading was caused by an over-counting dedup bucket in `scan_data_quality`. The 11,284 rows it flagged as "duplicate timestamps" were NEVER actually dropped from belief building — `_build_priors_from_transitions` iterates the row set WITHOUT timestamp dedup. v4.5.18 corrects the bucket math and adds a visibility metric. The Bayesian predictor was always using full data.

**What you'll see post-deploy:**
- The data quality % displayed on `sensor.ura_coordinator_manager_bayesian_data_quality` will jump from ~91% to ~99% on next predictor scan
- A new attribute `same_second_distinct` appears on that sensor — counts legitimate multi-step transitions in the same second (expected ~11k on a typical install, roughly 8%)
- Log line from `scan_data_quality` now includes `same_second_distinct=N` at the end

**What you WON'T see:**
- Any change in `*_likely_next_room` predictions
- Any change in Bayesian belief accuracy
- Any change in observed automation behavior

## The narrative correction (mid-cycle discovery)

The initial framing of this cycle — and the existing BACKLOG entry for the duplicate-timestamp investigation — claimed v4.5.18 would "recover ~8% of legitimate transitions dropped from belief building." **That was wrong.** Review 1 caught it: `scan_data_quality`'s `seen_timestamps` is local to the method. `_build_priors_from_transitions` at `bayesian_predictor.py:243` is the path that actually builds priors, and it doesn't timestamp-dedup at all.

The original symptoms (91% data quality reading) were real, but the interpretation (data being lost) was wrong. v4.5.18 fixes the misleading reading; nothing more.

Per project policy on no-fabrication, comments in code, test docstrings, and BACKLOG entries have all been corrected.

## The fix

### `bayesian_predictor.py:scan_data_quality`

**Before** (line 689-693):
```python
ts_key = str(ts_str)[:19]
if ts_key in seen_timestamps[person_id]:
    report.duplicate_timestamps += 1
    continue
seen_timestamps[person_id].add(ts_key)
```

Dedup key: `(person_id, second-truncated-ts)`. Missing `from_room`/`to_room`.

**After:**
```python
ts_key = str(ts_str)[:19]
dedup_key = (ts_key, from_room, to_room)
if dedup_key in seen_timestamps[person_id]:
    report.duplicate_timestamps += 1
    continue
seen_ts_keys = {k[0] for k in seen_timestamps[person_id]}
if ts_key in seen_ts_keys:
    report.same_second_distinct += 1
seen_timestamps[person_id].add(dedup_key)
```

Wider key correctly classifies legitimate multi-step paths (A→B→C inside one PersonCoordinator cycle where `now` is captured once) as separate transitions. True duplicate writes (same person + same second + same room pair) still get flagged.

### `DataQualityReport`

New field `same_second_distinct: int = 0`. Backward-compatible default.

### `BayesianDataQualitySensor.extra_state_attributes`

New `same_second_distinct` attribute. Additive — existing templates reading other keys unaffected.

## Why PersonCoordinator's timestamp capture causes the multi-step pattern

At `person_coordinator.py:131`, `now = dt_util.now()` is captured ONCE per coordinator cycle. When a cycle processes a multi-step transition path (genuine A→B→C in <30s, or BLE re-emit at restart), all the resulting rows share that single `now` value but have distinct `(from_room, to_room)` tuples. The OLD narrow dedup key collapsed these into the duplicate bucket. The widened key correctly recognizes them.

This is NOT a bug in PersonCoordinator or the writer path. The shared-`now` pattern is intentional (a coordinator cycle is a logical "moment in time"). It's just that the reporting bucket misinterpreted it.

## Tier 2 Review

Per user direction: "prediction must be rock solid → extra research and care." Two independent staff-engineer reviews.

### Review 1 (Core A) — domain correctness, edge cases, semantics

**Key finding (HIGH):** the original narrative framing was wrong (claimed prediction quality fix; actual scope was reporting-only). **Narrative corrected mid-cycle** in code comments, test docstrings, and BACKLOG entry. Other findings: 2 LOW (counter monotonicity, O(n²) comprehension performance — both deferred to follow-up).

Verdict: APPROVED-WITH-FIXES.

### Review 2 (Core B) — consumer audit, restart semantics, narrative consistency

**Key finding (HIGH):** one comment in `sensor.py:8947-8953` still carried the OLD "DROPPED / PASS through to belief building" language even after the v4.5.18 narrative correction. **Fixed pre-deploy.**

**Other findings:**
- MEDIUM: `_build_priors_from_transitions` rationale comment was cold-start-centric; updated to cover warm-restart path too.
- LOW: README needed (this file) — required by CLAUDE.md.
- LOW: BayesianDataQualitySensor doesn't subscribe to `SIGNAL_BAYESIAN_UPDATED` — pre-existing gap, ~30s post-scan refresh lag, inherited not introduced. Worth noting in this README.

Verdict: APPROVED-WITH-FIXES.

### Consumer audit (internal)

Grep across the integration found `BayesianDataQualitySensor` is the only consumer of `quality_report`. No coordinator branches, no template helpers, no internal automations gate on the percentage.

### Consumer risk (external)

If you have any HA automation, template sensor, or notification gating on `sensor.ura_coordinator_manager_bayesian_data_quality` state crossing a threshold (e.g., `< 95%`), it will fire on the **one-time post-deploy jump** from ~91% to ~99%. This is the bucket correction, not a regression. The metric will be stable at the new baseline going forward.

## Operator guidance — interpreting `same_second_distinct`

On the canonical install (134k rows, 4 persons, 90 days), expect this to settle at ~8% of total rows (≈11k).

- **Normal:** sustained growth proportional to ingest (it's the multi-step-path natural rate).
- **Watch for:** sudden spikes (e.g., the value doubling overnight). That would point at writer-path duplication or a stale-BLE re-emission storm. Not a v4.5.18 concern; just a useful diagnostic going forward.

## Test count

- v4.5.17: 422 tests
- **v4.5.18: 437** (+15 from `test_v4518_dedup_key_widen.py`)

15 tests cover:
- Headline fix (multi-step same-second → both pass)
- True duplicates still flagged
- Cross-person dedup isolation
- 3-step path in one second
- Microsecond truncation behavior
- Adjacent-seconds (no false same-second-distinct)
- Alternating back-and-forth (sensor flapping) handling
- Canonical install simulation (~8% same-second-distinct as expected)
- Empty / missing field defensive handling
- Source-grep regression guards (new dedup key tuple, visibility metric, sensor attribute, summary string)

## Live validation plan

### Immediate (post-restart)

1. **Data quality reading jumps:** within ~30 seconds of restart-completion, `sensor.ura_coordinator_manager_bayesian_data_quality` state moves from `91% quality` → ~`99% quality`. (Pre-existing ~30s sensor refresh lag; not v4.5.18 specific.)

2. **`same_second_distinct` populates:** attribute appears, expected value ~10-12k on this install.

3. **`duplicate_timestamps` drops dramatically:** the bucket should be a few hundred at most (true repeat writes, if any). If it stays high (>2k), the widened key isn't catching what we thought — would need investigation.

4. **No URA errors:**  `ha_get_logs source=system level=ERROR search=universal_room_automation hours_back=1` empty.

### Log line check

`scan_data_quality` runs at startup. The log line ending with `same_second_distinct=N` should appear in HA logs within ~1 min of restart completion:
```
B1 Data Quality: 134000 total, 132000 passed (99%), excluded: null=N, self=N, ..., same_second_distinct=11000
```

### Carry-over watch

- v4.5.16 Part A failsafe gate: Master Bedroom 4-hour mark hits ~16:54 CDT today (~50 min from now if you're reading this around 16:00). Already-scheduled wakeup at 17:12 CDT will capture.
- v4.5.17 Bayesian eval: 17:05 CDT bin will fire ~7 min before that wakeup.

## Deploy notes

- 2 files changed (`bayesian_predictor.py`, `sensor.py`) + 1 test file
- HACS download required
- HA restart required
- No DB schema changes, no entity unique_ids changed
- No new entities or config keys

## Documents

- BACKLOG: v4.5.16 duplicate-timestamp investigation entry SUPERSEDED with narrative correction
- Both Review 1 + Review 2 findings filed
- Phase 2 follow-up filed: O(n²) `seen_ts_keys` comprehension optimization (LOW from Review 1)

## Next

- **v4.5.19 candidate (small):** O(n²) comprehension optimization on `seen_ts_keys` if scan latency becomes user-visible at 134k+ rows
- **v4.6.x feature cycle:** the `likely_next_room` accuracy pipeline — the OTHER prediction-quality gap. This IS a real prediction-quality work item (logger + scorer + horizon decisions). The `record_prediction` dead stub at `bayesian_predictor.py:824` is the entry point.
- **v4.6.0:** Routine Awareness Phase 1 (existing roadmap)
