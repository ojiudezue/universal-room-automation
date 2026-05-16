# v4.6.4 — Polish bundle

**Date:** 2026-05-15 CDT (same day as v4.6.3.3)
**Type:** Tier 1 polish (4 surgical follow-ups from v4.6.3.3 audit + older review carry-overs)
**Predecessor:** v4.6.3.3 (census_count persistence suppression)

## Why bundle

After v4.6.3.3 shipped, the audit had already surfaced two small adjacent items (`transition_count_daily` wire-up, `safety.hazard_trigger_frequency` dead code) and the v4.6.3.3 Tier 1 reviewer filed a regex-tighten LOW. Pairing those with three small fixes from v4.6.2.3's deferred-LOW list keeps each cycle narrow without leaving polish items to drift forever.

## P1 — Wire up `presence.transition_count_daily`

The metric was declared in `PRESENCE_METRICS` since v3.6.0-c1 but no `record_observation` call site ever existed — so the AnomalyDetector saw zero observations for it and the slot was effectively dead.

Made `_count_transition` async so it can record + emit. On each increment:
1. `record_observation("transition_count_daily", "house", float(self._transitions_today))`
2. If an anomaly fires, build the canonical `AnomalyEvent`, call `store_event`, and fire `activity_logger.log(action="anomaly", ...)`

The metric is well-shaped — monotone counter resetting at midnight — so z-score persistence is safe. No degenerate-shape risk like the suppressed `census_count` / `zone_occupied_count` metrics.

The single call site for `_count_transition()` was updated to `await self._count_transition()` (inside `_run_inference`, already an async context).

**New test:** `test_presence_transition_count_daily_wired_and_recorded` asserts the metric is declared, the `record_observation` call exists, the function is async, and the call lives inside `_count_transition` (co-located with the increment for atomicity).

## P2 — Delete `safety.hazard_trigger_frequency` dead code

Audit during v4.6.3.3 confirmed this metric had never fired a single anomaly. It was recorded as a constant `1.0` per call ("Each trigger is a count observation"), so the baseline mean converged to `1.0` and every subsequent observation matched the mean exactly (`|value - mean| = 0` → `z = 0` → NOMINAL severity → no emit). (Note: variance floors at `MIN_VARIANCE`, so the suppression is not because std=0; it's because the value-mean delta is always zero.)

Dropped from `SAFETY_METRICS`; full ~50 LoC emit block removed. `active_hazard_count` (real 0..N variance) retained.

## P3 — Three small `automation.py` fixes from prior reviews

**P3a (LOW #3 from v4.6.2.1 review):** Sleep branch in `handle_humidity_based_fan_control` no longer clears `_humidity_cap_suppressed = False`. Sleep onset must not void the post-cap-fire suppression contract ("humidity must drop below OFF threshold before re-trigger") — otherwise cap-fire + sleep within minutes leaks the contract on wake.

**P3b (LOW #4 from v4.6.2.1 review):** HVAC-managing entry now clears Path A anchor state (`_humidity_on_since`, `_humidity_fan_triggered_time`) before returning. Without this, a stale anchor from a pre-HVAC run blocks the reload-seed logic (which only fires when the anchor is None) and the max-runtime cap loses its reference point when HVAC stops managing later.

**Known trade-off:** the clear runs on every HVAC-managing eval, not only on the transition INTO HVAC-managing. A fan that bounces in and out of HVAC-managing windows therefore resets its runtime budget each cycle. Accepted as a safety bias — the max-runtime cap is a stuck-sensor / runaway-humidity guard rather than a true budget tracker, and a fresh window per handoff is preferable to carrying stale (possibly hours-old) anchors across multi-hour HVAC management.

**P3c (LOW #5 from v4.6.2.1 review):** Added intent comment at the cap-fire branch explaining why both anchor fields are cleared (one for fresh runtime window on next trigger, one to flip `fan_is_on` false and route the next eval through the ON branch).

## P4 — Tighten regex test (v4.6.3.3 review L1)

The v4.6.3.3 reviewer flagged that `r"activity_logger\.log\([^)]*action=['\"]anomaly['\"]"` stops `[^)]*` at the first `)`, so a future re-introduction with a nested call before `action=` (e.g. `description=str(foo())`) silently passes.

Replaced with a balanced-paren walk that captures the full outer-call body, then searches for the `action="anomaly"` keyword inside it. Tolerates arbitrary nested calls.

## Inverted-invariant tests updated

`test_presence_no_live_store_event_or_anomaly_event` and `test_presence_no_activity_logger_anomaly_calls` (from v4.6.3.3) asserted *zero* live emit paths in `presence.py`. v4.6.4 P1 added one legitimate path. Both tests are now renamed and inverted to assert **exactly one** path, anchored on `transition_count_daily`:

- `test_presence_only_transition_count_daily_emits_persisted`
- `test_presence_only_transition_count_daily_activity_logger_call`

This protects against accidental re-introduction of suppressed emits OR addition of a new emit without an explicit audit + test update.

## Files changed

- `custom_components/universal_room_automation/domain_coordinators/presence.py` — P1 wire-up (~70 LoC added in `_count_transition`, 1 line changed at call site)
- `custom_components/universal_room_automation/domain_coordinators/safety.py` — P2 deletion (~45 LoC removed, 5 LoC of explanatory comment added)
- `custom_components/universal_room_automation/automation.py` — P3a, P3b, P3c (~10 LoC changed across 3 sites)
- `quality/tests/test_v463_anomaly_migration.py` — P1 new test + P4 regex rewrite + 2 inverted-invariant test renames/updates
- `docs/BACKLOG.md` — status update
- `docs/readmes/README_v4.6.4.md` — new (this file)

## Test count

- v4.6.3.3: 3096 passing
- **v4.6.4: 3097 passing** (+1 net new behavioral test, 0 regressions)
- Pre-existing 56 failures + 14 errors unchanged (test infrastructure debt)

## Deferred (NOT in this bundle)

- LOW #8, #9 from v4.6.2.1 review (Path A behavioral test rewrite — replace source-grep with end-to-end driver tests) — separate cycle when behavioral test infrastructure hardens
- v4.6.3 review B4 (decision-contradicted-within-N-min path), B5 (anomaly source_signal drift on NM emit), C10 (label externalization to translations) — separate
- v4.6.2.3 INFO #4 (test isolation / sys.modules pollution) — separate infra cleanup cycle

## What this is NOT

- Not v4.6.5 (in-memory anomaly persistence for HVAC / security / music_following / safety-detector) — that's the next cycle, branch already built at `feature/v4.6.5-in-memory-anomaly-persistence` commit c4d697f. Rebase onto develop after this ships, then audit `hvac.zone_call_frequency` cardinality before deploying.

## Live validation plan

1. Post-restart, confirm `sensor.ura_presence_coordinator_presence_anomaly` shows `transition_count_daily` becoming an active metric (`active: true`, `sample_count` > 0 within a few state transitions).
2. Confirm `safety.hazard_trigger_frequency` no longer appears in any URA coordinator's metric list (it shouldn't — but a quick check is cheap).
3. Confirm humidity fan behavior still works through a normal cycle: cap-fire suppression survives a sleep transition; HVAC-managing handoff clears Path A state cleanly.
4. No regression in `sensor.ura_coordinator_manager_recent_anomalies.by_coordinator` — presence stays low (only new `transition_count_daily` entries, which are rare in normal use).
