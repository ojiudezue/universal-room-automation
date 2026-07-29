# URA v5.35.2 — Stuck-Signal Watchdog observability surface

Tier-1 additive. Exposes the watchdog's RAM-trapped verdicts (operator ask: "what is
the observability surface of this?" — answer was push-heavy/pull-poor; this completes it).

## What ships
- **`sensor.ura_stuck_signal_watchdog`** (Coordinator Manager device, DIAGNOSTIC):
  state = count of active suspects; attrs = `stuck_cameras`, `stuck_sensors`
  (per-room {sensor: kind}), `frozen_trackers`, `last_fired` + `fires_today` per kind
  (RAM emit-stats ledger, resets on restart — documented).
- **Anomaly-ledger history:** one POINT_IN_TIME anomaly row per successful NM emit
  (mirrors the write-verify DAO pattern; latch-bounded ≤1/day/signal; DB failure never
  blocks the NM push — mutation-tested).
- New public accessors (`get_stuck_sensor_kinds`, `get_frozen_trackers`) — no private reach.
- No detection-logic changes. AST-verified class integrity on every touched file
  (v5.35.0 incident discipline).

## Validation
- H1: clean boot, sensor registers, state 0 with empty lists on the healthy house. 15 min.
- H2: on the next watchdog emit, `fires_today`/`last_fired` update + one anomaly row. Organic.
