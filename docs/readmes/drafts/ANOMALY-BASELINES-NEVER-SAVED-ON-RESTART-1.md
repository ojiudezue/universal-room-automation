# ANOMALY-BASELINES-NEVER-SAVED-ON-RESTART-1 — README draft

## What was wrong

Anomaly baselines for the `presence`, `security`, `safety`, `safety_rate`,
and `music_following` detectors are persisted ONLY from each coordinator's
`async_teardown()` and, for the CM setup detector, from
`CoordinatorManager.async_stop()`. Neither path runs on an HA restart —
HA fires `EVENT_HOMEASSISTANT_STOP` and exits without unloading the
config entry, so the only teardowns that ever execute are explicit
unloads (reload / disable). Learning accumulated between unloads is
discarded every restart.

Live DB confirmed the drift on 2026-10-01:

| coordinator_id    | last_updated |
|-------------------|--------------|
| presence          | 2026-09-14   |
| security          | 2026-09-04   |
| safety            | 2026-09-04   |
| safety_rate       | 2026-09-11   |
| music_following   | 2026-05-12   |
| energy / hvac / memory | current (per-rollover / per-cycle writers) |
| coordinator_manager    | current (saves each boot) |

## What changed (code)

`custom_components/universal_room_automation/domain_coordinators/manager.py`:

1. New module constant
   `ANOMALY_BASELINE_SAVE_INTERVAL_S = 3600` (named knob, numbers-get-knobs).
2. `CoordinatorManager._wire_anomaly_baseline_persistence()` wires two
   handles after `async_start` completes:
   - `async_track_time_interval(..., timedelta(seconds=ANOMALY_BASELINE_SAVE_INTERVAL_S))`
     — periodic save every hour.
   - `hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _on_stop)`
     — reuses the exact pattern from the house-state stop-hook at
     `manager.py` (previously `:617-633`) so there is one stop-listener style.
3. `_persist_coordinator_baselines()` iterates every coordinator with an
   `anomaly_detector`, awaits its `save_baselines()`, then invokes
   `safety._save_rate_baselines()` (safety_rate scope) and the CM setup
   detector. Each failure is isolated so one broken writer cannot block
   the others.
4. `async_stop()` cleans up both unsubs (listener hygiene).

Verified against HA source (`.venv-ha/lib/python3.13/site-packages/homeassistant/core.py:1112`):
`EVENT_HOMEASSISTANT_STOP` is fired inside `async_stop()` on both
graceful stop and restart, so this listener is reached on every restart.

## Write-volume

- Periodic timer: 1 call per `ANOMALY_BASELINE_SAVE_INTERVAL_S` = 24 calls/day.
- 5 detectors * 24 = 120 `save_baselines()` calls/day, plus 1 safety-rate
  save and 1 setup-detector save per period (total ≈ **168 helper calls/day**).
- Each `save_baselines()` issues an `INSERT OR REPLACE` per
  `(metric, scope)` tuple in that detector's baselines map — a handful
  of rows per call, bounded by the detectors' metric cardinality.
- **No per-decision-cycle amplification.** Behavioural test
  `TestWriteVolumeBounded.test_each_invocation_saves_once_per_detector`
  pins the one-save-per-invocation invariant; the interval constant is
  guarded `>= 1800s`.

## Listener cleanup

`async_stop()` calls both `_anomaly_baseline_periodic_unsub()` and
`_anomaly_baseline_stop_unsub()` and sets both back to `None`.
`TestListenerHygiene.test_async_stop_clears_both_unsubs` is the oracle.

## Falsifiable acceptance (live)

> After one restart and one `ANOMALY_BASELINE_SAVE_INTERVAL_S` period
> (~1h), `metric_baselines.last_updated` for `presence`, `security`,
> `safety`, `music_following` is within the current period.
> On restart (regardless of elapsed time since boot),
> `last_updated` for all four should refresh within seconds of
> `EVENT_HOMEASSISTANT_STOP` being fired at the subsequent restart.

Live check SQL (ura-sqlite or ssh ha):

```sql
SELECT coordinator_id,
       MAX(last_updated) AS last_saved,
       CAST((julianday('now') - julianday(MAX(last_updated))) * 24 AS INT)
         AS hours_ago
  FROM metric_baselines
 WHERE coordinator_id IN ('presence','security','safety',
                          'safety_rate','music_following',
                          'coordinator_manager')
 GROUP BY coordinator_id
 ORDER BY last_saved DESC;
```

Expected after one hour of uptime post-deploy: `hours_ago <= 1` for all
five. Expected on the restart immediately after that: all five refresh
within ~5 seconds of the restart event (stop-flush path).

Discriminator vs failure: if `safety_rate.hours_ago` stays high while
the others refresh, the rate-detector has no samples (data gap), NOT a
save-path regression — the safety 30-min periodic save on
`safety.py:1214` was already live; this cycle re-covers it from the CM
loop for symmetry.

## Tests (behavioural)

`quality/tests/test_anomaly_baseline_periodic_save.py`:

- (a) stop event — `TestStopEventPersistsAllDetectors`
- (b) periodic path — `TestPeriodicTimerPersists`
- (c) simulated-restart sample round-trip — `TestRestartRoundTripSampleCount`
- (d) write-volume bound — `TestWriteVolumeBounded`
- lifecycle — `TestListenerHygiene`
- wire-in anchor drill — `TestWireInAnchor.test_neutering_the_call_site_breaks_the_oracle`
  (production source of `_persist_coordinator_baselines` is extracted
  via `inspect.getsource`, the `await detector.save_baselines()` line
  is removed in a monkeypatched copy, and the stop-callback oracle
  goes red — proving the oracle is bound to the real call site.)

All 59 tests pass in isolation and in combination with
`test_domain_coordinators`, `test_restart_safety_doctrine_1`,
`test_metric_baseline_integration`, `test_coordinator_diagnostics`
(the only remaining failures in that combined set are two pre-existing
failures unrelated to this change).
