# URA v4.7.23 — Charge-from-Grid Guard Excludes Battery Inrush

**Release date:** 2026-06-05
**Tier:** Tier 2 (two framing-disjoint staff-engineer reviews — correctness + sensor-lag/lifecycle)
**Scope:** Battery arbitrage grid-import guard no longer counts the battery's
own charge inrush against the breaker-protection cap, and a single
battery-CT-lag tick at CHARGE entry can no longer false-lock the whole
off-peak chunk.

**Files:**
- `domain_coordinators/energy_battery.py`
- `domain_coordinators/energy_const.py`
- `quality/tests/test_energy_battery.py`

---

## Trigger

The arbitrage grid-import guard (`_grid_import_guard_triggered`) was meant to
abort an off-peak CHARGE chunk only when **house + EV** draw threatened to trip
the panel breaker — Enphase `charge_from_grid` is binary, so URA can't throttle
the rate, only stop. But it compared TOTAL `net_power_w` — which *includes the
battery's own charge inrush* — against the 12 kW cap. The act of charging
therefore drove `net_power` over the cap and self-aborted the chunk every time.

Observed live: net 18.6 kW with the battery charging 15.8 kW and non-battery
draw flat ~2.8 kW tripped the 12 kW cap, killing arbitrage charging.

---

## Headline Changes

- **Battery-exclusion.** New `_effective_import_kw()` computes
  `effective = net_power_w − max(0, battery_power_w)` from a single sensor
  snapshot. Only the non-battery draw (the breaker risk) is compared to the
  cap. `max(0, …)` means a *discharging* battery can never inflate the figure.
- **Fail-safe preserved.** If `battery_power_w` is briefly unavailable, charge
  is treated as 0 → effective collapses to total `net_power_w` (the stricter
  comparison). A sensor dropout can never *uncap* the guard.
- **2-consecutive-trip lock (CT-lag absorption).** New
  `ARBITRAGE_GUARD_CONSECUTIVE_TRIPS_TO_LOCK = 2`. At CHARGE entry the Envoy
  battery-power CT lags `net_power` by one poll, so the first tick can read
  full inrush on net while the battery still reads ~0. A one-shot lock would
  lose the whole chunk to pure sensor lag. Now tick 1 over-cap defers (keeps
  charging, logs `trip 1/2`); tick 2 over-cap locks. A genuine house+EV
  overdraw still locks within one extra ~30 s tick — inside the breaker margin.
- **Single-snapshot diagnostic.** The same snapshot drives both the guard
  comparison and the recorded `_arbitrage_guard_aborted_kw`, so the diagnostic
  is exactly the value the guard compared (no read-twice divergence).

---

## Behavior / Semantic Notes

- **`_arbitrage_guard_aborted_kw` now records EFFECTIVE (non-battery) import**,
  not total net. The diagnostic reads lower than pre-fix for the same event —
  it is now the value the guard actually compared. Single-user install, no
  external consumer of the attribute.
- The streak counter resets on any under-cap tick and in
  `reset_arbitrage_chunk()`. It is in-memory only; a restart mid-chunk resets
  it to 0 (harmless — chunk state already resets on restart).

---

## Tests

- 141/141 in `test_energy_battery.py` pass, including new
  `TestArbitrageGuardBatteryExclusion`:
  - `test_ct_lag_tick_does_not_false_lock_chunk` — lagged tick keeps charging.
  - `test_sustained_overdraw_locks_on_second_consecutive_tick` — real overdraw
    locks on tick 2.
  - `test_discharging_battery_not_added_to_import`,
    `test_battery_sensor_unavailable_falls_back_to_total`.
- Eight existing guard tests converted to the 2-tick lock.
- Full suite: 62 failed / 14 errors — unchanged from the known pre-existing
  baseline; no new regressions.

---

## Live Validation

- During an off-peak window with the battery charging 10–16 kW from grid, the
  diagnostic `arbitrage_guard_aborted_at` does **not** advance.
- No `Arbitrage CHARGE aborted by grid-import guard` WARNING while only the
  battery (not house+EV) is the large draw.
- A genuine house+EV overdraw past the cap still logs `trip 1/2 … deferring`
  then `aborted … on 2 consecutive ticks` and locks.

## Review

See `docs/reviews/code-review/v4.7.23_charge_from_grid_guard.md` — 1 HIGH
(CT-lag false-lock, fixed), 2 MEDIUM (1 fixed, 1 accepted semantic change),
2 LOW (accepted).
