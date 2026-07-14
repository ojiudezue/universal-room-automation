# URA v5.17.0 — Observability WebSocket Surface + Per-Room Control Attrs (G1)

**Date:** 2026-07-14
**Tier:** Observability WS = Tier 2 (two framing-disjoint reviews; 2 CRITICAL + 3 HIGH found and fixed). G1 = Tier 1 (SHIP).
**Review record:** `docs/reviews/code-review/v5_17_0_observability_ws_g1.md`
**Build commits:** ff74a24d (WS build), 63a128e8 (WS review fixes), 96e9c9ec (G1).

## 1. Observability WebSocket surface

Three **read-only** Home Assistant WebSocket commands over the URA SQLite logs, plus a live subscription stream, built for the PWA dashboard / observability workstream:

| Command | Purpose |
|---|---|
| `ura/logs/anomalies` | Query the anomaly log (filter by severity, coordinator, time; `min_importance` filter) |
| `ura/logs/activity` | Query the activity log |
| `ura/logs/subscribe` | Live subscribe — pushes new anomaly/activity rows as they are written; stream discrimination on `action == "anomaly"` |

**Read-only invariant:** connections open the DB with `PRAGMA query_only`; all SQL is parameterized; no write path exists on this surface.

**Caps:** server-side hard cap of 200 rows per query, default limit 50 (sized from the live-DB probe — 148KB pages drove column projection + the 50 default).

**Severity mapping:** the severity name map is derived from the `AnomalySeverity` enum (severities are stored numeric in the DB), so the surface cannot drift from the enum.

**Push marshalling:** subscription pushes are marshalled onto the event loop (loop-safe; one of the review fixes).

**API doc:** `docs/websocket_api.md`.

## 2. G1 — per-room `control_*` attributes

Every room's occupancy binary sensor (`binary_sensor.<room>_occupied`) now exposes six attributes describing what the room actually controls, sourced from the actuator's own **options-first** config read (options over data, matching live behavior):

- `control_lights`
- `control_night_lights`
- `control_fans`
- `control_humidity_fans`
- `control_covers`
- `control_climate_entity`

Fixture of expected values for all 38 rooms: `docs/planning/PLANNING_g1_room_control_list_attrs.md` Appendix A (extracted live from `core.config_entries`; AV Closet canary = the Shelly relay switch, not the misleading friendly-named light).

## Shipwatch acceptance hypotheses

```yaml
hypotheses:
  - id: H1
    check: installed_version == v5.17.0
  - id: H2
    check: zero URA ERROR log lines over 24h
  - id: H3
    check: binary_sensor.study_a_occupied attribute control_lights is a non-empty list within 1h of restart
```

## Live Validation (prospective)

- **L1:** Deploy healthy — HACS installed v5.17.0, config valid, restart clean, house_state sensor available.
- **L2:** WS registration INFO line present in HA log (`websocket_api` / `ura/logs`); no WS-related errors.
- **L3:** G1 38-room attribute diff vs Appendix A fixture — per-row PASS/FAIL; AV Closet canary MUST show the Shelly switch.
- **L4 (bonus, v5.16.3 rider):** `sensor.ura_energy_coordinator_battery_strategy` attrs `last_verified_write_*` show `restored: true` post-restart **if** a pre-restart verified write existed (report honestly either way).
- **L5:** Full WS functional smoke (actually issuing the WS commands) — **DEFERRED**: requires a long-lived access token the operator has not provided. Registration-line + log-scan evidence only for this release; functional smoke rides the PWA integration cycle.
