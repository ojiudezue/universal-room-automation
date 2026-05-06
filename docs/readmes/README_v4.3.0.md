# v4.3.0 — Grid Arbitrage Hardening

**Date:** 2026-05-06
**Type:** Feature cycle (Tier 2 — 2 reviews + live validation)
**Predecessor:** v4.2.29

## Summary

Fixes the latent grid arbitrage bug (battery has never charged via arbitrage since v3.11.0) and ships the surrounding hardening: runtime sliders, ladder reconciliation, ROI tracking with bill-prediction counterfactual, threshold diagnostics, and tightened envoy-staleness signaling. Six deliverables (D1-D6).

## Why

The morning of 2026-05-06 captured live evidence that grid arbitrage has never functioned correctly:

- `sensor.ura_energy_coordinator_battery_strategy` showed `arbitrage_active: True`, `reason: "Off-peak arbitrage — continuing (SOC 10.0%, target 80.0%)"`
- `switch.enpower_*_charge_from_grid` was correctly set to `on`
- BUT `number.enpower_*_reserve_battery_level` was `10` (the user's safety floor) instead of `80` (the arbitrage target)

In Enphase `self_consumption` mode, `reserve_battery_level` is BOTH the SOC floor AND the charge target when `charge_from_grid=on`. With reserve=10 and SOC=10, Enphase saw "I'm at floor, allowed to import to floor, hold." No grid import. The user reports never observing arbitrage charging in the entire feature lifetime.

## What changed

### D1 — Reserve-level fix (CRITICAL)

`custom_components/universal_room_automation/domain_coordinators/energy_battery.py`

Phase B activation (~line 419) and continuation (~line 441):
- **Before**: `reserve_level=self.reserve_soc` (passed user's safety floor)
- **After**: `reserve_level=self._arbitrage_target` (passes charge target, e.g. 80%)

Plus a cosmetic state-lag fix at the envoy-unavailable early return (`:295-310`): `self._arbitrage_active=False` is now set so the in-memory state matches the returned dict.

Three new regression tests in `quality/tests/test_energy_battery.py` (`test_arbitrage_activation_uses_target_as_reserve`, `_continuation_`, `_inactive_resets_state_on_envoy_unavailable`). The activation test should have caught the original bug — pre-fix it asserts `reserve_level == 80` and fails with `assert 10 == 80`.

**Pre-existing test stability fix** (rolled in same commit): the harness `_BatteryHarness` now defaults to `solar_classification_mode="custom"` with fixed thresholds. Before this, three drain-target tests classified `solcast_tomorrow="90"` differently per month (per-month percentile thresholds in `SOLAR_MONTHLY_THRESHOLDS`), passing only Jan-Mar. Now date-stable.

### D2 — Arbitrage runtime sliders

`number.py`: new `ArbitrageSOCNumber` class. Two instances per CM entry:
- `number.ura_energy_coordinator_arbitrage_soc_trigger` (range 5-60, default 20)
- `number.ura_energy_coordinator_arbitrage_soc_target` (range 30-95, default 80)

Both `entity_category=CONFIG` so they appear in the EC device card's Configuration section alongside the existing four off-peak drain sliders.

`RestoreEntity` for slider persistence across HA restarts.

EC gets two new setters (`set_arbitrage_trigger`, `set_arbitrage_target`) that mutate `BatteryStrategy._arbitrage_trigger/_target` and call `_check_threshold_ladder()` to surface violations.

### D3 — Threshold reconciliation + default changes

`domain_coordinators/energy_const.py`:
- `DEFAULT_RESERVE_SOC: 20 → 10` (lowered to widen arbitrage window)
- `DEFAULT_ARBITRAGE_SOC_TRIGGER: 30 → 20` (was equal to `drain_poor=30`, causing oscillation; now sits cleanly between reserve_soc=10 and drain_poor=30)

New helper `validate_threshold_ladder()` enforces:
- `reserve_soc ≤ drain_excellent ≤ drain_good ≤ drain_moderate ≤ drain_poor` (monotonic ladder, all above floor)
- `reserve_soc < arbitrage_trigger < drain_poor` (strict, with implied buffer)
- `arbitrage_target > drain_poor` (no immediate re-drain after charging)

Validator runs on every slider write (`EnergyCoordinator._check_threshold_ladder`) and at sensor read (`BatteryStrategy.get_status` includes `threshold_warning` attribute). Violations log WARNING; the sensor surfaces a human-readable message. Auto-clamping is **not** in v4.3.0 — it's deferred (validator is currently warn-only).

### D4 — Per-cycle ROI accounting + counterfactual

**New DB table** (`database.py:944+`):
```sql
CREATE TABLE arbitrage_cycles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    soc_before REAL,
    soc_after REAL,
    kwh_charged REAL NOT NULL,
    off_peak_rate REAL NOT NULL,
    displaced_rate REAL NOT NULL,
    round_trip_efficiency REAL NOT NULL DEFAULT 0.90,
    savings REAL NOT NULL,
    season TEXT
);
CREATE INDEX idx_arbitrage_cycles_timestamp ON arbitrage_cycles(timestamp);
```

Five DAO methods: `save_arbitrage_cycle`, `query_arbitrage_savings_since(iso)`, `query_arbitrage_savings_total`, `query_arbitrage_last_cycle`, `query_arbitrage_pace_recent(days)`.

**Cycle accounting hook** in `EnergyCoordinator._account_arbitrage_cycle()`. Runs after `determine_mode` each tick. When `arbitrage_active=True` and SOC has risen since the previous tick:
- `kwh_charged = (Δ_SOC / 100) × battery_capacity_kwh`
- `savings = kwh_charged × (displaced_rate − off_peak_rate) × RTE`
- Where `displaced_rate` = peak rate (summer) or mid_peak rate (shoulder/winter), and `RTE = 0.90`

**Three new sensors** under the EC device:
- `sensor.ura_arbitrage_savings_today` — since local midnight
- `sensor.ura_arbitrage_savings_this_cycle` — since bill cycle start
- `sensor.ura_arbitrage_savings_total` — lifetime since v4.3.0 deploy

Each has audit attributes (`last_cycle_kwh_charged`, `last_cycle_off_peak_rate`, `last_cycle_displaced_rate`, `last_cycle_round_trip_efficiency`, etc.) so the math is auditable.

**Cross-references**:
- `EnergyBatteryStrategySensor.extra_state_attributes` adds `arbitrage_savings_today` so the strategy sensor shows arbitrage status AND $ saved in one place.
- `EnergyPredictedBillSensor.extra_state_attributes` adds the **counterfactual**:
  - `arbitrage_savings_this_cycle` (already-accrued)
  - `arbitrage_savings_projected_cycle_total` (accrued + 7-day-rolling-avg × days_remaining)
  - `predicted_bill_without_arbitrage` (= predicted_bill + projected_cycle_total)
  - `arbitrage_savings_pct` (% of without-arbitrage bill that arbitrage is saving)

The counterfactual answers "is arbitrage paying off?" at a glance.

**Decision-time INFO log**: `Arbitrage cycle: SOC X→Y (ΔZ), N.NNN kWh charged, off-peak $A → displaced $B, RTE 0.90, savings $C` — auditable trail in HA logs.

### D5 — Threshold diagnostic strings

`BatteryStrategy.get_status()` now includes:
- `threshold_position` — e.g., `"SOC=22% above drain_target (20%, tomorrow=moderate) — will drain to target during off-peak"`
- `next_action_estimate` — e.g., `"continue arbitrage charging until SOC reaches target (80%)"`

Both update each decision cycle.

### D6 — Envoy staleness check (folded from B)

`EnvoyStatusSensor` (`sensor.py:7522+`) now flips to `"stale"` earlier and on more conditions:

1. **Freshness threshold tightened** from hardcoded 30 min to bounded `decision_interval × 2` (clamped to [600s, 1800s]). With the default 5-min decision interval that's 600s — one missed cycle and the sensor flips, instead of waiting 6.

2. **Data-anomaly flag**: when the consumption cross-check fires (`energy.py:_check_consumption_crosscheck`, divergence > 15%), `EnergyCoordinator._envoy_data_anomaly_at` is set. Sensor reports `"stale"` while this is within the last hour. Cleared automatically when divergence drops below 5% (recovery). This covers the v4.2.28 latent defect where envoy_status reported `"online"` while data was zeroed/wrong after Envoy reboot.

## Reviews — Tier 2 (per CLAUDE.md)

Per project memory (`feedback_review_bug_visibility.md`): every bug at every severity is listed below. Nothing aggregated silently into "all-LOW."

### Review 1 (Core A) — Domain logic audit

| Severity | Finding | Status |
|---|---|---|
| CRITICAL | `query_arbitrage_pace_recent` used SQL `DATE(timestamp)` on UTC ISO strings — miscounts day boundaries for non-UTC users | **Fixed** (count in Python via `dt_util.as_local`) |
| HIGH | `_dt.fromisoformat(cycle_start_str).replace(tzinfo=now.tzinfo)` fragile across DST/naive strings | **Fixed** (use `dt_util.parse_datetime` with explicit `as_local` / `as_utc`) |
| HIGH | TZ naive/aware on cycle_start parsing | **Fixed** (same root cause as above) |
| MEDIUM | Validator warns but doesn't auto-clamp slider values | **Deferred** to v4.3.x — warn-only is sufficient for v4.3.0; auto-clamp is its own UX scope |
| MEDIUM | Boundary `<` vs `<=` asymmetry in validator undocumented | **Deferred** — adding docstring noted but not blocking |
| MEDIUM | ROI math assumes all charged kWh consumed at displaced rate (optimism bias) | **Deferred** — accept as documented limitation; would need actual-consumption tracking to fix |
| MEDIUM | `capacity_kwh` fetched per cycle; silent fallback to 40 kWh | **Fixed** (last-known-good wins; WARNING log on first fallback) |
| MEDIUM | `very_poor` drain class not validated | **Deferred** — fallback to `poor` is benign |
| LOW | `arbitrage_savings_pace_monthly` is a misnomer | **Fixed** (renamed to `arbitrage_savings_projected_cycle_total`) |
| LOW | Hardcoded 30-day cycle length in pace projection | **Deferred** — minor accuracy issue around month boundaries |
| LOW | Number entity `role` kwarg | **Not a bug** — custom kwarg on my class, not HA's |
| LOW | 1-hour anomaly window hardcoded | **Deferred** — accepted as design choice |
| LOW | Decision interval not bounded — pathological 60-min config → 120-min stale threshold | **Fixed** (threshold clamped to [600s, 1800s]) |

### Review 2 (Core B) — Lifecycle / race / cross-coordinator audit

| Severity | Finding | Status |
|---|---|---|
| CRITICAL | DB write failure swallows `prev_soc` baseline → next cycle double-counts kWh | **Fixed** (advance baseline BEFORE the await) |
| CRITICAL | Slider→Coordinator init race — `async_added_to_hass` may fire before EC is registered | **Fixed** (subscribe to `SIGNAL_ENERGY_ENTITIES_UPDATE` to retry push on first tick) |
| HIGH | Slider value precedence on entry reload (RestoreEntity vs entry.options ambiguous) | **Fixed** (entry.options presence triggers config-first; otherwise restore-first) |
| MEDIUM | 5 sequential DB queries in cache refresh — no latency log | **Fixed** (DEBUG log of refresh time) |
| MEDIUM | Cache reset on entry reload causes 5-min flicker | **Deferred** — minor UX; acceptable |
| MEDIUM | Slider write race during decision tick | **Deferred** — single-threaded event loop makes this benign in practice; documenting |
| MEDIUM | Anomaly flag never cleared on cross-check recovery | **Fixed** (clear when divergence drops below 5%) |
| MEDIUM | Zero test coverage for D2-D6 | **Partially fixed** — D3 validator tests + D4 cycle math smoke test added; D2 + D6 deferred |
| LOW | Shallow copy of cache | **Deferred** — sensors only read |
| LOW | No retry on DB query timeout in cache refresh | **Deferred** |
| LOW | No retention policy on `arbitrage_cycles` table | **Deferred** — ~500 rows/year; revisit when usage grows |

Verdict (post-fix): **READY TO DEPLOY**.

Full review at `docs/reviews/code-review/v4.3.0_arbitrage_hardening.md`.

## What we parked

- Validator auto-clamp (warn-only currently)
- Multi-day Solcast forecast lookback
- EV/arbitrage shared off-peak budget
- Dashboard "estimated savings if enabled" widget (revisit once D4 has bill-cycle of data)
- Test coverage for D2 (slider entities), D6 (staleness state machine)
- Validator boundary semantics docstring
- Anomaly window length / decision-interval bounds tunability
- `arbitrage_cycles` retention policy
- Auto-clamp slider values to nearest valid ladder position

## Live validation (Review 3 — post-deploy)

After HA restart:

1. **D1 — the killer signal**: confirm arbitrage actually charges. With `arbitrage_enabled=True`, SOC < trigger=20%, tomorrow forecast = poor: within ~30 min, `sensor.envoy_*_battery` SOC must RISE toward 80%. **If it doesn't rise, the fix is wrong** — investigate Enphase reserve-level semantics and revert.
2. Watch logs for the new INFO line: `Arbitrage cycle: SOC X→Y (ΔZ), N.NNN kWh charged, ...`. One per decision tick during arbitrage.
3. **D2**: drag `number.ura_energy_coordinator_arbitrage_soc_trigger` to a new value. Within 5 min, observe `sensor.ura_energy_coordinator_battery_strategy` reason string reflect new threshold. Confirm value persists across HA restart.
4. **D3**: temporarily set arbitrage_trigger above drain_poor (e.g., 35) via slider. Confirm WARNING log + `threshold_warning` attribute appears on battery strategy sensor.
5. **D4**: tomorrow morning, after one off-peak arbitrage window:
   - `sensor.ura_arbitrage_savings_today` shows a plausible $ value
   - Audit attributes show non-zero kWh and rates matching summer peak displacement
   - `sensor.ura_energy_coordinator_predicted_bill` attributes show `predicted_bill_without_arbitrage` higher than `predicted_bill`
6. **D5**: read `threshold_position` and `next_action_estimate` attributes on battery_strategy at multiple SOC levels through the day; sentences should make sense.
7. **D6**: watch for envoy `state == "stale"` if Envoy blips — should flip within ~10 min.

## Tests

```bash
PYTHONPATH=quality python3 -m pytest quality/tests/test_energy_battery.py quality/tests/test_envoy_auto_derive.py quality/tests/test_energy_consumption.py
# 112 passed
```

AST-clean for Python 3.9. Forward-compat for Python 3.14 by construction.

## Deploy notes

- New DB table `arbitrage_cycles` created on first DB-init pass after restart.
- Three default values change for users on stock config: `reserve_soc 20→10`, `arbitrage_soc_trigger 30→20`, plus the (cosmetic) renamed counterfactual attribute. Users who had explicit values in config will keep theirs.
- Manifest version stamped to 4.3.0 by deploy.sh.
- HA restart picks up the new `after_dependencies: ["enphase_envoy"]` from v4.2.29 (carried forward).

## Next

- **v4.3.x** (if needed): hotfixes from live validation.
- **v4.4.x** — B5 Appliance Scheduler (LG ThinQ + Rainbird).
- **v4.5.0** — Routine Awareness (B6 + B7).
- Architectural #0 (test baseline cleanup) is a recurring blocker; consider scheduling.
