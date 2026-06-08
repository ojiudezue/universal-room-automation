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

### Live Validation — Validated 2026-06-08 (restart 06:31 UTC / 01:31 CDT)

Authoritative signals: live entity attributes + `home-assistant.log` (stamps are
HA-local CDT; entity stamps UTC — `01:3x local == 06:3x UTC`).

| # | Criterion | Result | Evidence |
|---|---|---|---|
| 1 | v4.7.30 actually loaded | ✅ PASS | `update.universal_room_automation_update` `installed_version=v4.7.30`, `last_changed 2026-06-08T06:31:33Z` (this boot). |
| 2 | Compliance sensors live + polling | ✅ PASS | `sensor.ura_presence_coordinator_presence_compliance` and `…_safety_coordinator_safety_compliance` exist, `state=100.0`, `last_reported 06:34:55Z` (re-polling post-boot). |
| 3 | #2 — RuntimeWarning gone | ✅ PASS | `coroutine 'ComplianceTracker.get_compliance_rate' was never awaited` last appears `01:30:16 CDT` (06:30 UTC) — **before** the 01:31:33 restart; **zero** occurrences after the v4.7.30 boot. Confirms `native_value` no longer calls the async DAO un-awaited. The `100.0` is now the genuine awaited result (no compliance violations in the 7-day window), not the swallowed-exception default. |
| 4 | Zero URA errors post-boot | ✅ PASS | Only URA ERRORs are 2 shutdown-transients at `01:30:57 CDT` (pre-restart, DB write-worker stopping). None after the boot. Post-boot WARNINGs are all known/non-regression (SPAN baselines = backlog #4; Envoy cross-check transient; zone-not-registered = backlog #5; non-URA: MQTT/shelly/wattbox/smarthub). |
| 5 | #3 — summer post-peak coast release | ⏳ TIME-GATED | Observable only during the summer post-peak window (~20:00–21:00 CDT): Energy log `Published HVAC constraint mode=normal … reason=normal conditions` at the first tick ≥20:00 on a poor-solar day; `mode=coast … reason=mid-peak poor solar` pre-16:00. Restart was 01:31 CDT (morning), so not yet reachable. Rides the **same 20:00–21:00 CDT window as v4.7.29's Review D** → optional shipwatch H1 / recorder trip-wire, **not** a soak-watch (per no-soak policy). Mechanism proven by 7 in-suite tests (2 fail if reverted). |
| 6 | B-MED-1 — duty-cycle reset on release | ⏳ TIME-GATED | Same 20:00 release window; only observable when a real coast→normal release fires. In-suite logic verified; live confirmation folds into the shipwatch H1 evening check. |
| 7 | B-MED-2 watch — grid cap 20:00–20:30 | ⏳ TIME-GATED | First summer evening post-deploy; shipwatch/recorder. |
| 8 | B-LOW-2 watch — no spurious alerts on real compliance values | ✅ PASS (URA side) | No URA-internal consumer reads these sensors (NM does not reference them; diagnostic category). Operator-side HA automations are out-of-repo — none known. |

**Cycle status:** immediate criteria (1–4, 8) PASS post-restart. The post-peak
behavioral criteria (5–7) are time-gated to the 20:00–21:00 CDT window and are
left to the existing shipwatch H1 trip-wire that already covers v4.7.29 — not a
scheduled chore. Cycle closed at live-validation per the no-soak policy.

## Deferred (tracked)
- B-MED-2 (no HVAC shed path in post-peak mid_peak) → load-shedding backlog cycle.
- A-LOW-1 (dead `except`/None-check after the await) → v4.7.31 cleanup.
- B-LOW-1 (per-poll DB read) → not implementable as stated; consistent with the
  existing `LastIdentifiedTime` sensor; no action.
