# v4.6.5.3 — Surface fix + SIGNAL_DATABASE_READY + MF first-emit log

**Date:** 2026-05-16 CDT
**Tier:** Tier 1 polish bundle (single review)
**Predecessor:** v4.6.5.2 (MF denominator + recent_anomalies retry)

Three small follow-ups bundled into one cycle. All three were items the v4.6.5.2 deploy reviews or the morning soak observation surfaced; this cycle ships them rather than re-deferring.

## Item 1 — Surface fix: per-coordinator severity ignores SUPPRESSED metrics

Post-v4.6.5 + v4.6.5.1 the per-coordinator anomaly sensors (HVAC, presence) consistently showed `state: critical` because their in-memory `_active_anomalies` counters were dominated by suppressed degenerate-shape metrics (HVAC `zone_call_frequency`, presence `census_count` / `zone_occupied_count`). Functionally fine — anomaly_log stays clean — but visually `critical` looks alarming for what is, by design, suppressed-from-persistence noise.

**Fix:** `AnomalyDetector.__init__` accepts a new `suppressed_metric_names: frozenset[str]` parameter. `get_worst_severity()` and `get_status_summary().active_anomalies` filter against this set via new `_persisted_active_anomalies()` helper. All 5 coordinators wire their v4.6.5.1 P2 module-level `*_SUPPRESSED_FROM_PERSISTENCE` constant into the constructor.

`get_status_summary()` adds a new attribute `suppressed_active_anomalies` so operators can still see the in-memory firing for diagnostic purposes — just not as the sensor's primary `state`.

**Semantic note:** the per-coordinator anomaly sensor now reflects "anomaly_log-eligible signal" rather than "all in-memory anomalies." This aligns the sensor with the recent-anomalies dashboard. If you ever want to see suppressed-metric activity, check the `suppressed_active_anomalies` attribute.

## Item 2 — M2 from v4.6.5.2 review: SIGNAL_DATABASE_READY (replaces polling)

v4.6.5.2 Fix 2 closed the recent-anomalies-sensor-zero bug with a 30s × 1s polling loop. v4.6.5.3 replaces the loop with a one-shot dispatcher subscription:

- New signal `SIGNAL_DATABASE_READY` in `signals.py`.
- Dispatched once from each `hass.data[DOMAIN]["database"] = database` site in `__init__.py` (two sites — defensive belt-and-braces).
- `URARecentAnomaliesSensor.async_added_to_hass` now: (a) immediate refresh if DB already in `hass.data`, OR (b) subscribe to `SIGNAL_DATABASE_READY` and refresh once on first fire. Handler auto-unsubscribes after firing to prevent redundant refreshes on URA reload.
- v4.6.5.2's polling helper `_initial_load_with_db_retry` is gone.

Event-driven and cheaper than polling. Deterministic — no race window, no sleep, no max-attempt cap to tune.

## Item 3 — M4 from v4.6.5.2 review: one-shot info-log on first MF emit

v4.6.5.2 Fix 1 changed the MF `transfer_success_rate` and `cooldown_frequency` denominators. The persisted baseline starts drifting from `mean=0.0` only as new observations arrive under the new logic — operationally invisible for weeks unless someone checks the metrics dict.

`MusicFollowingCoordinator._first_emit_logged: set[str]` is a one-shot guard. On the first post-restart emit per metric, `_LOGGER.info` surfaces the observed rate and explains the v4.6.5.2 Fix 1 context. Discoverable signal that "the new denominator is live."

## Files changed

- `custom_components/universal_room_automation/domain_coordinators/coordinator_diagnostics.py` — `AnomalyDetector` accepts `suppressed_metric_names`, new `_persisted_active_anomalies()` helper, `get_worst_severity()` + `get_status_summary()` updated
- `custom_components/universal_room_automation/domain_coordinators/hvac.py` — import + pass `HVAC_SUPPRESSED_FROM_PERSISTENCE`
- `custom_components/universal_room_automation/domain_coordinators/presence.py` — pass `PRESENCE_SUPPRESSED_FROM_PERSISTENCE`
- `custom_components/universal_room_automation/domain_coordinators/security.py` — pass `SECURITY_SUPPRESSED_FROM_PERSISTENCE`
- `custom_components/universal_room_automation/domain_coordinators/music_following.py` — pass MF suppression set + `_first_emit_logged` set + per-metric guarded info-log (Item 3)
- `custom_components/universal_room_automation/domain_coordinators/safety.py` — pass `SAFETY_SUPPRESSED_FROM_PERSISTENCE`
- `custom_components/universal_room_automation/domain_coordinators/signals.py` — new `SIGNAL_DATABASE_READY`
- `custom_components/universal_room_automation/__init__.py` — dispatch `SIGNAL_DATABASE_READY` at both DB-assignment sites
- `custom_components/universal_room_automation/sensor.py` — `URARecentAnomaliesSensor` subscribes to signal; old polling helper removed
- `quality/tests/test_v465_observability_gap.py` — 3 new tests, 1 inverted (replaces v4.6.5.2 polling test)

## Test count

- v4.6.5.2: 3131 passing
- **v4.6.5.3: 3134 passing** (+3 new tests, 0 regressions)
- Pre-existing 56 failures + 14 errors unchanged

## Live validation plan

1. **Item 1 immediate signal:** post-restart, `sensor.ura_hvac_coordinator_hvac_anomaly` and `sensor.ura_presence_coordinator_presence_anomaly` should drop from `state: critical` to `nominal`/`advisory` once in-memory suppressed-metric anomalies populate (was permanently `critical` pre-fix). New attribute `suppressed_active_anomalies` should show the count of in-memory-only firings (HVAC: zone_call_frequency; presence: census_count + zone_occupied_count).
2. **Item 2 immediate signal:** `sensor.ura_coordinator_manager_recent_anomalies` should populate as fast as Fix 2 did (within 1-2s of DB ready, not 30s polling window). Look for `SIGNAL_DATABASE_READY` dispatch in error_log if anything goes wrong.
3. **Item 3 first-emit signal:** look in URA log for `MusicFollowing transfer_success_rate first post-deploy emit: rate=...` — fires on first MF transfer outcome.

## What this is NOT

- Not v4.6.6 (severity refactor — separate Tier 2-DB cycle).
- Not a fix for the MF `low_confidence` rejection product issue (BLE tracking confidence) — that's user-config territory.
- Not a removal of the `_active_anomalies` list — the in-memory record is preserved; only the SEVERITY calculation and `active_anomalies` count filter it.
