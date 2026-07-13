# v5.16.0 pre-deploy row-rate snapshot — 2026-07-13 ~11:00 CDT

Taken on the live DB (read-only, via SSH) before the wave deploy, per the
Tier 2-DB ±25% post-deploy comparison requirement. Running version at
snapshot time: v5.15.0.

## anomaly_log — last 24h by (coordinator_id, severity, anomaly_type)

| coordinator_id | severity | anomaly_type | rows/24h |
|---|---|---|---:|
| energy | 4 | point_in_time | 287 |
| energy | 1 | point_in_time | 77 |
| compliance | 1 | point_in_time | 58 |
| presence | 2 | point_in_time | 13 |
| presence | 3 | point_in_time | 2 |
| coordinator_manager | 2 | point_in_time | 1 |
| **total** | | | **438** |

## ura_activity_log — last 24h by coordinator

| coordinator | rows/24h |
|---|---:|
| room | 2091 |
| optimization | 743 |
| energy | 326 |
| hvac | 205 |
| presence | 95 |
| safety | 63 |
| compliance | 58 |
| coordinator_manager | 1 |
| notification | 1 |

## metric_baselines

Total rows: **72** (post orphan-DELETE of 2026-07-12; 47 span_nj-* scoped).

## Post-deploy watch points

- New anomaly types expected from the wave: `write_verification_failed`,
  `write_reverted` (transition-latched), `write_verification_unit_mismatch`,
  `write_verification_unmapped_mode`, SOC-divergence events. Expected
  steady-state volume: near-zero (transition-latched by design). ANY
  sustained per-window emission = the B-MED-2 latch failed — investigate.
- Census/guest: guest-gate arming events/day should DROP ≥60% (BLE-cancel
  L1 bar) once census_hold_interior=3 + BLE-cancel are live. Watch
  `ble_cancelled_count` attr on the house census sensor.
- Energy anomaly rows (287/24h at severity 4) are the dominant band —
  post-deploy comparison must hold within ±25% absent a real event.
- 24h window note: this window includes the 2026-07-12/13 Envoy outage +
  three restarts — rates may be modestly elevated vs a quiet day.
