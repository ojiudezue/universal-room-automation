# v4.6.5.1 — Polish bundle (4 items from v4.6.5 reviews)

**Date:** 2026-05-16 CDT (same day as v4.6.5)
**Tier:** Tier 1 polish (single review)
**Predecessor:** v4.6.5 (in-memory anomaly persistence). Items here are all deferrals from the v4.6.5 Tier 2-DB review (A/B/C) and the v4.6.4 carry-over list. The fifth deferred item (severity collapse refactor → distinct DB severity values) is properly Tier 2-DB and ships separately as v4.6.6.

## P1 — `override_frequency` cumulative-counter fix (review B-M2)

Pre-v4.6.5.1, `hvac._record_anomaly_observations` recorded the raw cumulative `total_overrides` (sums each zone's `override_count_today`). That counter resets at midnight and grows monotonically through the day — a sawtooth shape. Reviewer B-M2 flagged that late-day high values would fire ADVISORY just from natural accumulation (mean=3.23 std=3.43 on the live baseline already captures the daily range, so anything well above day-average looks anomalous even if behaviorally normal).

Fix: track previous-cycle total in `self._last_total_overrides_observed` and emit the **per-cycle delta** instead. Stable variance through the day; only true override bursts trigger an anomaly. When the daily reset is detected (delta < 0), the observation is skipped to avoid polluting baseline with a negative reset artifact, and the anchor is updated so the next cycle resumes cleanly.

The persisted payload now carries both `delta_overrides` (the observed value) and `total_overrides_today` (for downstream context).

## P2 — `SUPPRESSED_FROM_PERSISTENCE` as module-level introspectable constants + parametric audit (review C-M1)

Pre-v4.6.5.1, `SUPPRESSED_FROM_PERSISTENCE` was a local set inside each coordinator's `_record_anomaly_observations` method — purely documentation, not introspectable, only present in HVAC and security.

Promoted to module-level constants in each coordinator:
- `hvac_const.py` — `HVAC_SUPPRESSED_FROM_PERSISTENCE = frozenset({"zone_call_frequency", "short_cycle_rate", "comfort_deviation_hours"})`
- `security.py` — `SECURITY_SUPPRESSED_FROM_PERSISTENCE = frozenset({"entry_anomaly_score"})`
- `presence.py` — `PRESENCE_SUPPRESSED_FROM_PERSISTENCE = frozenset({"census_count", "zone_occupied_count"})`
- `music_following.py` — `MUSIC_FOLLOWING_SUPPRESSED_FROM_PERSISTENCE = frozenset()` (empty — both metrics wired)
- `safety.py` — `SAFETY_SUPPRESSED_FROM_PERSISTENCE = frozenset()` (empty — active_hazard_count is wired)

Each constant has a docstring above explaining the per-metric suppression rationale (linking to v4.6.3.1 / v4.6.3.3 / v4.6.5 audit findings).

Added **`test_every_metric_is_wired_or_suppressed`** — a parametric meta-test that walks every coordinator's METRICS list and asserts each metric is either in the suppression set OR has a `record_observation("<name>", ...)` call in the coordinator source. Forward-compat: a future cycle that adds a new metric to `*_METRICS` but forgets to either wire it or suppress it will fail this test, forcing an explicit decision. Also added **`test_all_suppression_constants_are_frozenset`** to keep the constants immutable.

The inline locals in `hvac._record_anomaly_observations` and `security._handle_entry_intent` were removed (replaced with a one-line pointer to the module constant).

## P3 — `tokenize`-based comment filter for negative test assertions (review C-M2/M4)

The legacy `_non_comment_src` helper was line-level — it stripped lines starting with `#` but left docstrings and inline trailing comments intact. That made negative tests like `test_safety_detector_hazard_trigger_frequency_deleted` fragile: a docstring or trailing comment mentioning the deleted metric could silently satisfy a "must not appear" check, masking a regression.

Added `_non_string_src` — a `tokenize`-based helper that walks Python tokens and emits only NAME, OP, NUMBER, and structural tokens. Comments and string literals (including docstrings) are discarded entirely. Use this for identifier/method-name presence checks. The original `_non_comment_src` is preserved (under its original name) for assertions that need to find a specific quoted string literal in code-as-text — a tokenizer-based stripper would discard those literals.

Both helpers are documented with their trade-offs so future maintainers know which to use.

## P4 — `_transitions_today` RestoreEntity hydration (v4.6.4 review M3)

The v4.6.4 cycle wired `transition_count_daily` as a real persistent metric, but the counter (`PresenceCoordinator._transitions_today`) resets to 0 on every reload/restart. Each restart re-seeded the baseline with synthetic 0s, biasing future thrashy-day anomalies to fire more often than they should.

Fix: query `house_state_log` for today's transition count on `async_setup`, seed `_transitions_today` and `_transition_reset_date` from the result. Added DAO `count_house_state_changes_since(since_iso)` for the query, with a behavioral test that drives the production SQL against `real_schema_db` to verify the lexicographic comparison includes today's rows and excludes yesterday's.

## Files changed

**Production code:**
- `custom_components/universal_room_automation/domain_coordinators/hvac.py` — P1 delta tracking + emit; P2 inline-set removal
- `custom_components/universal_room_automation/domain_coordinators/hvac_const.py` — P2 `HVAC_SUPPRESSED_FROM_PERSISTENCE`
- `custom_components/universal_room_automation/domain_coordinators/security.py` — P2 module-level constant + inline-set removal
- `custom_components/universal_room_automation/domain_coordinators/music_following.py` — P2 module-level constant (empty)
- `custom_components/universal_room_automation/domain_coordinators/presence.py` — P2 module-level constant; P4 hydration in `async_setup`
- `custom_components/universal_room_automation/domain_coordinators/safety.py` — P2 module-level constant (empty)
- `custom_components/universal_room_automation/database.py` — P4 `count_house_state_changes_since` DAO

**Tests:**
- `quality/tests/test_v465_observability_gap.py` — P3 helper + P2 parametric audit + P1 delta test + P4 source + behavioral tests; updated 2 existing HVAC tests for the moved constant
- `quality/tests/conftest_db.py` — added `house_state_log` to `_REQUIRED_TABLES` for P4 behavioral test

## Test count

- v4.6.5: 3123 passing
- **v4.6.5.1: 3128 passing** (+5 net new tests: parametric audit, frozenset check, P1 delta, P4 source, P4 behavioral SQL)
- 0 regressions. Pre-existing 56 failures + 14 errors unchanged.

## Deliberately NOT in scope

- **Severity collapse refactor (ADVISORY/ALERT/CRITICAL → distinct DB values).** This is the fifth item from v4.6.5 reviews (A-M2 + B-M1). It changes the shape of `anomaly_log.severity` column values and would affect any existing analytics that group by severity — Tier 2-DB. Files as **v4.6.6** with 3x parallel review ceremony. A background agent prepped the non-overlapping ~50% (`anomaly_event.py` enum, `database.py` DAO, sensor reader, behavioral test infra) in a separate worktree branch so v4.6.6 can pick up cleanly.
- **Music Following instrumentation investigation.** `transfer_success_rate` baseline mean=0.0 over 1594 samples is suspicious. Needs runtime investigation (broken stats vs genuine state), not a code-only polish.
- **`recent_anomalies` sensor lazy-query investigation.** Post-restart the sensor showed state=0 despite 24h-window data. Dispatcher-driven sensor may need a startup query to backfill — needs runtime investigation.

## Live validation plan

1. Post-restart, verify URA log shows `Hydrated _transitions_today=N from house_state_log (since YYYY-MM-DD)` once. The count should match recent activity.
2. `sensor.ura_presence_coordinator_presence_anomaly` metrics dict for `transition_count_daily` should now show `sample_count` jumping forward to include pre-restart transitions (or growing more naturally on subsequent restarts).
3. `sensor.ura_hvac_coordinator_hvac_anomaly` metrics dict for `override_frequency` — over a few hours, watch the `mean` value: should now reflect per-cycle delta (close to 0 most cycles, occasional small ints) rather than the late-day cumulative. New baseline takes time to converge.
4. No new entries in `sensor.ura_coordinator_manager_recent_anomalies.by_coordinator.hvac` from `hvac.zone_call_frequency` (suppression unchanged — still in `HVAC_SUPPRESSED_FROM_PERSISTENCE`).

## What this is NOT

- Not v4.6.6 (severity refactor — separate Tier 2-DB cycle).
- Not a behavioral change to which metrics persist — same 5 wired, same suppressions. Only the EMIT value for `override_frequency` changes (cumulative → delta).
- Not a v4.6.5 hotfix — v4.6.5 is live and clean; this is incremental polish.
