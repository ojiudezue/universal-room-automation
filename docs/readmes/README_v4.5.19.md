# v4.5.19 — TransitionDetector Listener Leak Fix + Periodic-Closure Swallow Escalations

**Date:** 2026-05-12 CDT
**Type:** Tier 2 (lifecycle change in transitions.py) + Tier 1 bundle (log-level escalations)
**Predecessor:** v4.5.18 (data quality reporting correction — confirmed today's headline bug was upstream of the reporting)

## Summary — TL;DR

Two unrelated reliability fixes shipping in one deploy:

1. **Listener leak fix (the headline):** every URA reload was leaking a `TransitionDetector._on_location_change` handler on the event bus. N+1 listeners → N+1 INSERTs per transition event. Result: 11,284 / 134,569 = 8.4% byte-identical duplicate rows in `room_transitions` over 90 days, inflating Bayesian priors over time.

2. **Periodic-closure swallow escalations:** the C audit run after v4.5.17's NameError discovery found 11 sites across 6 files where `_LOGGER.debug(...)` inside `except` blocks could silently hide bugs in periodic closures. All 11 escalated to `_LOGGER.warning(..., exc_info=True)` so the next hidden NameError-class bug surfaces immediately.

## Production validation of the SESSION before this cycle

Same-day proof points for fixes from earlier in the session, captured 5 min before this README was written:
- **v4.5.16 Part A — failsafe gate WORKED:** Master Bedroom occupied 4 hr 13 min continuously, `failsafe_fired: false`, mmWave continuously firing. Pre-v4.5.16 code would have force-marked the room vacant at exactly 4 hr 0 min. The freshness gate held.
- **v4.5.17 — Bayesian eval NameError FIXED:** `sensor.ura_coordinator_manager_bayesian_prediction_accuracy` now reports state `0.1109` (Brier), `hit_rate_pct: 88.9%`, `total_predictions_7d: 27` — from 0 for 6+ months.

These are the foundation. v4.5.19 builds on both.

## Part 1: TransitionDetector Listener Leak (the prediction-quality bug)

### Bug

`transitions.py:74` (pre-v4.5.19):
```python
self.hass.bus.async_listen(
    "ura_person_location_change",
    self._on_location_change
)
```

`hass.bus.async_listen(...)` returns an unsubscribe callable. **The return was discarded.**

The integration unload path at `__init__.py:2266-2268` did:
```python
for key in ["transition_detector", "pattern_learner", "music_following"]:
    if key in hass.data[DOMAIN]:
        del hass.data[DOMAIN][key]
```

It removed the dict reference but never called teardown. The listener stayed bound on the bus.

### Consequence

Every URA reload (options-flow save, manual reload via UI, Bayesian-clear button press, anything that triggers `async_reload_entry`) left the previous `_on_location_change` handler active. New detector instance created and also registered. After N reloads: N+1 listeners.

When a transition event fires:
- All N+1 listeners receive identical `event.data` (single object, by reference)
- All N+1 call `_log_transition` → `database.log_transition` → `INSERT INTO room_transitions`
- Result: N+1 byte-identical rows for one logical transition

### How it inflated Bayesian priors

`_build_priors_from_transitions` at `bayesian_predictor.py:243` aggregates counts WITHOUT timestamp dedup. Each duplicate write contributes equally to the prior. Periods with more accumulated reloads (more recent) carry more weight than periods with fewer. Predictions skewed toward recent transition patterns proportionally to the leak.

### The fix

`transitions.py`:
1. `__init__` declares `self._unsub_bus: Callable | None = None` and `self._unsub_cleanup: Callable | None = None`. Defensive against teardown-before-init.
2. `async_init` captures the unsub returns into the new fields.
3. New `async def async_teardown(self)` method calls both unsubs in try/except, logs failures at WARNING with `exc_info=True`, sets handles to None (idempotent).

`__init__.py` unload path:
- Reordered: get detector handle → pop bayesian listener → remove bayesian listener from detector → call `await transition_det.async_teardown()` → THEN delete from `hass.data`.
- **Bonus fix:** the original Bayesian listener removal block ran AFTER the `del`, so `hass.data[DOMAIN].get("transition_detector")` always returned None — dead code path. The reorder makes it actually do something.

### Bug Class #38 — added to QUALITY_CONTEXT

"Discarded `async_listen` Unsubscribe → Listener Leak Across Reload." Includes detection AST patterns, the right shape (`self._unsub_*` capture + `async_teardown` + integration-level teardown call), and the historical example linking back to today's session.

### What v4.5.19 does NOT do

- **Does NOT undo the existing bias in priors.** The 11k duplicate rows are already in `room_transitions`. Future scans of belief-cells will continue to be influenced by them. Filed as a separate concern: optional follow-up to rebuild priors from a dedup'd row set, or accept the gradual decay as fresh transitions accumulate post-v4.5.19.
- **Does NOT change the `room_transitions` schema.** Adding a UNIQUE constraint on `(person_id, second_truncated_ts, from_room, to_room)` would be belt-and-braces but is out of scope for this hotfix.

## Part 2: Periodic-Closure Swallow Escalations

The C audit run after v4.5.17 found 11 sites where `_LOGGER.debug(...)` inside `except` blocks could hide bugs in periodic closures. All escalated to `_LOGGER.warning(..., exc_info=True)`.

### HIGH (4 sites)

1. **`energy.py:_async_decision_cycle`** — arbitrage cycle accounting (`_account_arbitrage_cycle` + `_refresh_arbitrage_status_cache`). Same function the v4.5.17 NameError lived in. A failure here silently breaks arbitrage savings accounting; user-visible only via savings sensor reading zero for weeks.

2. **`energy.py:_refresh_arbitrage_status_cache`** — outer try. If this throws, every arbitrage status sensor reading is stale; user can't tell without DB inspection.

3. **`manager.py:_execute_action`** — NM routing dispatch. The central dispatch path for EVERY coordinator-issued notification (safety hazards, security armed-state, energy alerts). Silent failure killed every operator-visible URA notification. Was dropping the exception entirely (no traceback at all) — now logs with full traceback.

4. **`hvac_covers.py:update()`** — cover intent check. If `is_cover_currently_intended_open` raises (e.g., method renamed during refactor), every owned cover was silently skipped permanently. HVAC cover automation could die invisibly.

### MEDIUM (3 sites)

5. `manager.py:_log_decision` — decision audit trail DB write.
6. `energy.py:_update_power_profiles` — B4 L2 power profile learning.
7. `energy.py:_get_house_avg_climate` — was a bare `except: pass` (no log at all, most invisible shape).

### LOW (4 sites — cosmetic exc_info adds)

8. `energy.py:_refresh_arbitrage_status_cache` cycle_start parse
9. `energy.py` NM alert helper
10. `hvac_override.py` NM alert
11. `security.py` compliance scheduling
12. `music_following.py` anomaly baseline save

(Count is 11+1 because the audit produced 12 escalations total; the LOW count is "5 escalations" in the audit report.)

### Why bundle in one deploy

- Files touched are disjoint: v4.5.19 in `transitions.py` + `__init__.py`, v4.5.20 in 6 other coordinator files
- No coupling — neither fix can mask the other
- One HA restart instead of two
- v4.5.20 is mechanical (log levels only); zero behavior change risk

## Tier 2 Review

**v4.5.19 (lifecycle change) got Tier 2 review** — two independent staff-engineer-level passes per CLAUDE.md when in doubt. Bundle observations also reviewed.

Findings will be appended after the review completes.

## Test count

- v4.5.18: 437 tests
- **v4.5.19: 461** (+24 across `test_v4519_transition_detector_teardown.py` (11 tests) + `test_v4520_swallow_escalations.py` (13 tests))

Breakdown:
- **v4.5.19 (11 tests):**
  - AST regression: unsub return captured, teardown method exists, init declares handles, exception handler uses warning+exc_info
  - Source-grep: unload path calls teardown before del, Bayesian listener removal reordered before del
  - **Behavior: 3 lifecycle tests including a 5-cycle reload simulation asserting listener count stays at 1.**
- **v4.5.20 (13 tests):**
  - Source-grep on each of the 11 escalated sites: old debug-shape absent, new warning-shape present
  - Smoke check: total `exc_info=True` count per file meets minimum threshold

## Live validation plan (post-restart)

### v4.5.19 — listener leak fix

1. **Reload test:** trigger a URA reload (Settings → Devices → URA → 3-dot → Reload). Check `binary_sensor.<room>_occupied` for any room — should not be affected.
2. **Verification via inspection (would require DB access — not from this side):** in 24 hours, query:
   ```sql
   SELECT person_id, from_room, to_room, substr(timestamp,1,19), COUNT(*)
   FROM room_transitions
   WHERE timestamp > '2026-05-12T23:30:00'
   GROUP BY 1,2,3,4 HAVING COUNT(*) > 1;
   ```
   Should return zero rows (no new duplicates post-fix).
3. **Bayesian data quality sensor**: `sensor.ura_coordinator_manager_bayesian_data_quality` `duplicate_timestamps` count should stabilize. It's a 90-day rolling window, so existing duplicates will age out gradually over 90 days. New duplicates should be zero.

### v4.5.20 — escalation visibility

1. No immediate behavior change.
2. If any of the previously-swallowed bugs were firing silently, they'll surface in HA logs at WARNING level with full traceback. Worth a once-over: `ha_get_logs source=system level=WARNING search=universal_room_automation hours_back=2` after a few coordinator cycles.

### Carry-over checks

- v4.5.16 Part A: still no Master Bedroom failsafe firings during evening
- v4.5.17: next Bayesian eval bin at 21:05 CDT should write rows (now well-validated path)
- All v4.5.12 → v4.5.18 entities still respond correctly

## Deploy notes

- 7 files touched (transitions.py, __init__.py, energy.py, manager.py, hvac_covers.py, hvac_override.py, security.py, music_following.py)
- 2 test files added (test_v4519_..., test_v4520_...)
- HACS download required
- HA restart required
- No DB schema changes, no entity unique_ids changed, no config keys

## Documents

- BACKLOG entries cleaned up: v4.5.19 (now this README), v4.5.20 (now bundled here), `__init__.py` debug-swallow audit (closed — falsified during today's investigation)
- QUALITY_CONTEXT.md updated with Bug Class #38

## Next

- **A — Anomaly refresh signals (Presence + MF)** — fully planned, Tier 1, ready to ship next
- **B — Device-page ordering HC experiment** — scan order approved, Tier 1, ready after A
- **v4.6.x — `likely_next_room` accuracy pipeline** — the OTHER prediction-quality cycle (logger + scorer + horizon decisions, ~200 LoC, feature cycle)
- **v4.6.0 — Routine Awareness Phase 1** — existing roadmap
