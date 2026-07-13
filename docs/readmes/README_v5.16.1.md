# URA v5.16.1 — Cloud-first battery writes · battery_full_time v2 · BLE-cancel kill switch

Hotfix batch (H1/H2/H3), built and reviewed 2026-07-13 afternoon.
Builds `114043a8`/`a4e40c30`/`dcd6fe2c`, fix-up `44881a35` (5 HIGH + 5 MED
found by 3 focused reviews, all fixed). Review record: addendum in
`wave2026_07_13_hygiene_blecancel.md`.

## Why (live incident, same day)

v5.16.0's tripwire era began with the smoking gun it was built for: URA
commanded charge-from-grid ON via the local Envoy API at 11:06:27; the
local switch echoed "on"; the Enphase cloud showed off and the hardware
followed the cloud — the battery never grid-charged. Worse, the lying
local read convinced URA its intent was satisfied, so it never
re-commanded, and (commanded ledger being RAM-only post-restart) the
tripwire had nothing to verify. Operator: "rip off the band-aid" —
cloud-first for ALL battery writes.

## H1 — Cloud-first battery writes (all three surfaces)

- Reserve, charge-from-grid, and battery-mode writes now dispatch to the
  Enphase CLOUD entities (the v5.16.0 Cloud Verification entities).
- **Every command-state read moved to the same leg** (W-5): the LKG
  breaker latch, attain adoption/drift reads, `_result` pre-reads,
  EVSE-hold target match, dispatch tap, and (fix-up) `current_storage_mode`.
  Telemetry reads (SOC etc.) unchanged; `envoy_available` deliberately
  still tracks local Envoy health.
- **Self-heal:** when the cloud's applied state disagrees with URA's
  intent, URA re-dispatches within one decision cycle, with an INFO log
  ("H1 self-heal…"). Same-value pending verifications are left to mature
  (no alarm starvation); **3 consecutive self-heals raise the NM alarm
  even if no check matures** — the heal loop cannot mask the alarm.
  Unavailable cloud leg: 3-strike backoff, once-per-day anomaly, no
  infinite dispatch loop.
- **Independence preserved:** the local entities become a secondary
  witness — cloud-verified writes that the gateway's local view disagrees
  with emit `write_local_witness_divergence` (anomaly, not NM).
- Explicitly blanking a Cloud Verification field now coherently demotes
  that surface (reads AND writes) back to the local leg, documented in the
  field description.
- `write_route` per surface visible in the `last_verified_write_*` attrs.

## H2 — battery_full_time v2 (operator's mental model)

"Time to 100% at the CURRENT charge rate (solar or grid) minus
consumption." `basis: current_rate` when charging (observed power,
taper-banded, with an honesty note that hardware may taper harder near
full; ETAs >24h render as `unlikely_today`); `basis: solar_forecast`
fallback when idle/discharging; `unknown` now explains itself
(`missing_input`). Attrs: rate, taper band, consumption assumption.

## H3 — BLE-cancel kill switch

Integration options → census section: **"Phone presence can excuse
unrecognized camera detections"** (default ON). Read live per census tick;
OFF is byte-identical to pre-BLE-cancel behavior. The off-ramp for the
sensitive census change, shipped before its first full live week.

## Acceptance

```yaml
version: 5.16.1
hypotheses:
  - id: H1a
    name: self_heal_re_dispatch_fires
    description: First post-deploy decision cycle detects cloud cfg=off vs arbitrage intent=on and re-dispatches via cloud; INFO "H1 self-heal" in log; charge_from_grid verification completes (verified or reverted — either proves the pipeline).
    oracle: home_assistant
    query: { kind: home_assistant.state_attribute, entity: sensor.ura_energy_coordinator_battery_strategy, attribute: last_verified_write_charge_from_grid }
    expected: { condition: "status != no_data", within: "30m" }
    window: { first_check_after: 15m, confirm_after: 1h, alert_if_violated_after: 4h }
  - id: H1b
    name: battery_actually_grid_charges
    description: During the next arbitrage CHARGE window (or tonight's off-peak), the battery draws grid power — the cloud-applied state and hardware behavior finally match URA intent.
    oracle: home_assistant
    query: { kind: home_assistant.history, entity: sensor.envoy_482543015950_battery, correlate: battery_power_charging_during_window }
    expected: { condition: "charging_observed" }
    window: { first_check_after: 4h, confirm_after: 1d, alert_if_violated_after: 2d }
  - id: H2a
    name: full_time_populated_while_charging
    oracle: home_assistant
    query: { kind: home_assistant.state, entity: sensor.ura_energy_battery_full_time }
    expected: { condition: "not unknown while charging; basis attr present" }
    window: { first_check_after: 30m, confirm_after: 1d, alert_if_violated_after: 2d }
```

## Live Validation (prospective — write back post-restart)

| # | Criterion | How |
|---|---|---|
| L1 | Deploy healthy, zero URA errors (boot DB-worker transients excepted/counted) | error log |
| L2 | Self-heal fires: INFO log + cloud turn_on dispatch + verification schedules (H1a) | log + battery-strategy attrs |
| L3 | Cloud switch flips ON within ~15 min (Enlighten applies) OR the N=3 unmaskable alarm fires — either outcome validates the machinery | cloud switch history / NM |
| L4 | `write_route: cloud` visible on all three surfaces | battery-strategy attrs |
| L5 | battery_full_time populates with basis=current_rate once charging resumes | sensor + attrs |
| L6 | H3 kill switch visible in census options UI (operator spot-check, optional) | UI |
