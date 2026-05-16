# v4.6.5.2 — Investigation fixes (MF denominator + recent_anomalies retry)

**Date:** 2026-05-16 CDT
**Tier:** Tier 1 polish (single review)
**Predecessor:** v4.6.5.1 (polish bundle). Items here are the two "investigations" that v4.6.5.1 explicitly deferred — diagnosed in this cycle, fixes shipped.

## Fix 1 — Music Following `transfer_success_rate` denominator

### Investigation

Live data showed `music_following.transfer_success_rate` with mean=0.0, std=0.1 (MIN_VARIANCE floor), sample_count=1594 — zero success in 1594 cycles. Suspicious enough that v4.6.5 review C-M3 + v4.6.5.1 deferral list flagged it for investigation.

Reading `_on_transfer_outcome`:
```python
total = sum(stats.values())          # sums ALL 7 outcomes
success_rate = stats["success"] / total
```

`_transfer_stats` has 7 buckets:
- **Music-involved** (`MusicFollowing._TRANSFER_KEYS`): `success`, `failed`, `unverified`, `active_playback_blocked`
- **Pre-music rejections**: `low_confidence`, `cooldown_blocked`, `ping_pong_suppressed`

In this household, BLE-tracking-confidence rejections (`low_confidence`) dominate — most transfer requests get filtered out BEFORE the music transfer step is even attempted. The denominator is dominated by pre-music rejections, so `success / total ≈ 0` regardless of whether actual music transfers succeed. The same shape problem hit `cooldown_frequency`.

### Fix

Scope the denominator to music-involved attempts only:
```python
music_attempts = sum(stats.get(k, 0) for k in _MF._TRANSFER_KEYS)
if music_attempts > 0:
    success_rate = stats.get("success", 0) / music_attempts
    # ... record + emit
```

For `cooldown_frequency`, the meaningful question is "of decisions past the confidence check, what fraction got cooldown-blocked":
```python
post_confidence_total = music_attempts + stats.get("cooldown_blocked", 0)
if post_confidence_total > 0:
    cooldown_rate = stats.get("cooldown_blocked", 0) / post_confidence_total
    # ... record + emit
```

### Behavioral change

**Cycles where every outcome is a pre-music rejection (no `_TRANSFER_KEYS` outcomes AND no `cooldown_blocked`) no longer record an observation at all.** Pre-fix the early-return only triggered on `total == 0`; post-fix the gate is per-metric. For households where MF is frequently bounced at the confidence check, the AnomalyDetector will see fewer observations per day — slower baseline accumulation, but each observation is now meaningful. Net win for signal quality.

### Baseline drift

The existing persisted baseline (`transfer_success_rate` mean=0.0 std=0.1, sample_count=1594) is now stale relative to the new denominator. Post-deploy observations will drift it slowly toward the real distribution. Expect ~weeks for full convergence on a household with active MF. No one-shot reset — running mean will move organically.

### Worth filing (not v4.6.5.2 scope)

The "MF is rejecting at `low_confidence`" pattern that this investigation exposed is itself worth product attention — if BLE tracking confidence is consistently low, MF won't fire at all regardless of metric design. Possible future cycle: add a `low_confidence_rate` metric to surface this directly, OR investigate whether BLE/person-tracking config needs tuning. Filed for triage.

## Fix 2 — `URARecentAnomaliesSensor` post-restart-zero

### Investigation

Live data after every v4.6.5+ deploy showed `sensor.ura_coordinator_manager_recent_anomalies` with state=0, `top_10` empty, `by_coordinator` empty — minutes after restart, even though `anomaly_log` had hundreds of rows in the 24h window.

Direct DB query confirmed: **603 rows in the last 24h** (bayesian=16, compliance=170, energy=308, presence=109). Sensor should have shown 603.

Reading `URARecentAnomaliesSensor.async_added_to_hass`:
```python
self._unsub = async_dispatcher_connect(
    self.hass, SIGNAL_ACTIVITY_LOGGED, _handle_activity_logged
)
self.async_on_remove(lambda: self._unsub() if self._unsub else None)
# Initial load
await self._async_refresh()
```

`_async_refresh()` does:
```python
database = self.hass.data.get(DOMAIN, {}).get("database")
if database is None:
    return
```

Setup-time race: the CM (Coordinator Manager) entry containing this sensor sets up CONCURRENTLY with room entries that initialize `hass.data[DOMAIN]["database"]`. If the sensor's `async_added_to_hass` fires before the room entry's DB init completes, `database is None` → silent return → state stays at 0. After the silent fail, the sensor only updates on `SIGNAL_ACTIVITY_LOGGED` dispatches from new emits. **Suppressed metrics** (the v4.6.5-suppressed `zone_call_frequency`, v4.6.3.1/.3.3 suppressed presence metrics) don't fire that signal — so for windows where only suppressed metrics fire, the sensor never updates.

### Fix

Replace the immediate `await self._async_refresh()` with a retry helper task:
```python
self._initial_load_task = self.hass.async_create_task(
    self._initial_load_with_db_retry(),
    name="ura_recent_anomalies_initial_load",
)
self.async_on_remove(
    lambda: self._initial_load_task.cancel()
    if self._initial_load_task and not self._initial_load_task.done() else None
)

async def _initial_load_with_db_retry(self) -> None:
    for attempt in range(30):
        if self._unsub is None:  # entity removed during retry
            return
        if self.hass.data.get(DOMAIN, {}).get("database") is not None:
            await self._async_refresh()
            return
        await asyncio.sleep(1.0)
    _LOGGER.warning(...)  # gives up gracefully
```

30 attempts × 1s = 30s budget. Per the review, this is enough for normal setup; if DB is wedged (e.g., the v4.6.3.1 hang) the sensor logs a warning and waits for SIGNAL_ACTIVITY_LOGGED dispatches instead. Bug class #29 (untracked background tasks, v4.6.3 A5) is addressed by storing the task handle in `self._initial_load_task` and registering cancellation via `async_on_remove`. Catches `asyncio.CancelledError` silently so teardown doesn't log a stack trace.

## Files changed

- `custom_components/universal_room_automation/domain_coordinators/music_following.py` — Fix 1 (~25 LoC: new denominators + per-metric `if > 0` gates + module-local `_TRANSFER_KEYS` import)
- `custom_components/universal_room_automation/sensor.py` — Fix 2 (~40 LoC: retry helper, task tracking + cancellation hook, asyncio.CancelledError swallow)
- `quality/tests/test_v465_observability_gap.py` — 3 new tests (success denominator, cooldown denominator, retry helper presence + task tracking)

## Test count

- v4.6.5.1: 3128 passing
- **v4.6.5.2: 3131 passing** (+3 new tests, 0 regressions)
- Pre-existing 56 failures + 14 errors unchanged

## Tier 1 review

Verdict: SHIP-WITH-MINOR-FIXES. Zero CRITICAL. One HIGH (H1: untracked retry task — v4.6.3 A5 bug class) and two LOW test-brittleness items applied pre-deploy. M2/M3/M4 review findings filed in BACKLOG. Full review notes captured in `docs/reviews/code-review/v4.6.5.2_investigation_fixes.md` if you create that doc post-deploy (not blocking).

## Live validation plan

1. **Fix 2 observability check (immediate):** post-restart, `sensor.ura_coordinator_manager_recent_anomalies.state` should reflect the actual count of `anomaly_log` rows in the last 24h within ~30 seconds (DB-readiness retry window). Pre-fix it was 0 indefinitely.
2. **Fix 2 retry-log:** if DB warmup is slow, look for "RecentAnomaliesSensor initial load succeeded after N retries (DB warmup)" at DEBUG level. If DB never appears, the warning "database never appeared in hass.data after 30 seconds" surfaces in error_log.
3. **Fix 1 observation rate (24-48h):** `sensor.ura_music_following_coordinator_music_following_anomaly` `metrics.transfer_success_rate.sample_count` should grow more slowly than pre-fix (we record fewer cycles), but each new observation should reflect a real music-attempt outcome rather than a pre-music rejection ratio.
4. **Fix 1 baseline drift (weeks):** `transfer_success_rate.mean` should slowly drift upward from 0.0 if MF ever actually succeeds. `cooldown_frequency.mean` should drift toward a real ratio. Not visible immediately.

## What this is NOT

- Not v4.6.6 (severity refactor — parked on `feature/v4.6.6-severity-refactor`, Tier 2-DB).
- Not a fix for the underlying "MF is being rejected at low_confidence" product issue — that's a tracking-confidence tuning concern, filed for separate triage.
- Not a one-shot baseline reset — the running mean will move organically as new observations under the new denominators accumulate.
