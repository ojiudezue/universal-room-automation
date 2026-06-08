# v4.7.30 — Compliance sensors un-stuck + HVAC post-peak coast release

**Tier:** 2-DB (3 framing-disjoint reviews — see
`docs/reviews/code-review/v4.7.30_compliance_sensors_and_hvac_post_peak_coast.md`).
**Baseline tag:** `pre-review-v4.7.30`.

## What changed

### 1. Compliance-rate sensors un-stuck (backlog #2)
`sensor.ura_presence_compliance` and `sensor.ura_safety_compliance` were silently
pinned at `100.0`: `native_value` (a sync property) called the async
`get_compliance_rate` DAO without awaiting it, so the un-awaited coroutine raised
`TypeError`, got swallowed, and the hardcoded `100.0` fallback was returned every
poll (plus a `RuntimeWarning`). Now `native_value` returns a cached value and a
new `async_update` awaits the rate and caches it. (Bug class candidate #52.)

### 2. HVAC post-peak coast release (backlog #3)
`_update_hvac_constraint` now releases the mid_peak HVAC coast to `normal` during
summer **post-peak** mid_peak (20:00–21:00, no peak ahead before off_peak),
instead of letting the house keep drifting warm. Off_peak (cheap cooling) is
imminent and the battery is already discharging (v4.7.29), so comfort recovers.
Summer **pre**-peak mid_peak and shoulder/winter mid_peak (where mid_peak is the
top rate) keep coasting. Direct mirror of the v4.7.29 battery day-boundary fix.

### 3. Duty-cycle reset on coast→normal release (Review B-MED-1)
`hvac.py:_handle_energy_constraint` now also clears the per-zone duty-cycle
window (`runtime_seconds_this_window`, `window_start`, `runtime_exceeded`) when
**releasing** from a constrained mode to `normal`, not only on entry into a
constrained mode. Without this, a zone that hit `runtime_exceeded` during coast
stayed flagged (and pinned toward the `away` preset via `hvac.py:1174`) until its
duty window naturally expired — which would have blunted change #2's comfort
recovery for up to one duty-cycle window.

## Acceptance criteria

### In-suite (proven before deploy)
- **Test:** `test_hvac_post_peak_coast_release.py` (7) — summer post-peak →
  `normal`; summer pre-peak / shoulder / winter / peak → `coast`. Drives the real
  extracted method; 2 cases fail if the fix is reverted.
- **Test:** `test_compliance_sensor_async_cache.py` (8) — `native_value` returns
  cache, `async_update` awaits + caches, cache is not re-queried on read.
- **Test:** `test_day_boundary_tou.py` (17) — the `peak_ahead_before_offpeak` /
  `get_season` primitives this cycle relies on.
- **Suite:** baseline-diff vs `pre-review-v4.7.30` = zero new failures.

### Live Validation (prospective — to be written back post-restart)
- **Live:** within ~30s of restart, `sensor.ura_presence_compliance` and
  `sensor.ura_safety_compliance` read a real value (not a constant `100.0`), and
  no `RuntimeWarning: coroutine ... get_compliance_rate ... was never awaited`
  appears in the log.
- **Live:** on the first summer decision tick at/after 20:00, the Energy log shows
  `Published HVAC constraint mode=normal ... reason=normal conditions` (coast
  released); before 16:00 (pre-peak) a poor-solar day still shows
  `mode=coast ... reason=mid-peak poor solar`.
- **Live:** no constraint flap at the 20:00 / 21:00 boundaries (single transition
  per boundary).
- **Live (watch, B-MED-2):** grid-import attribute stays under cap during
  20:00–20:30 the first summer evening (combined HVAC+battery release).
- **Live (watch, B-LOW-2):** confirm no operator-side automation/dashboard alerts
  fire on the compliance sensors now showing real <100 values.

## Deferred (tracked)
- B-MED-2 (no HVAC shed path in post-peak mid_peak) → load-shedding backlog cycle.
- A-LOW-1 (dead `except`/None-check after the await) → v4.7.31 cleanup.
- B-LOW-1 (per-poll DB read) → not implementable as stated; consistent with the
  existing `LastIdentifiedTime` sensor; no action.
