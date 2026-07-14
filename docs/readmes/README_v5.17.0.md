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

## Live Validation — Validated 2026-07-14

| # | Criterion | Result | Evidence |
|---|---|---|---|
| L1 | Deploy healthy | **PASS** | HACS `installed_version == v5.17.0`, `pending_update: false`; config check `valid`; restart clean ~00:39-00:41 CDT; `sensor.ura_presence_coordinator_presence_house_state` available (`arriving`, last_changed 00:41:41 CDT post-boot). Zero URA ERROR lines in journal + system_log post-restart. |
| L2 | WS registration line + no WS errors | **PARTIAL (as-expected)** | The registration line is INFO and the HA logger runs at WARNING (journal carries zero INFO lines; `home-assistant.log` no longer written — HAOS journal only), so the line is **unobservable at current log level**. Negative evidence clean: zero `ura/logs` / websocket errors from URA in journal (`grep websocket` matched only an unrelated `unifi_access` disconnect). Registration correctness is proven in-suite; functional proof deferred to L5. |
| L3 | G1 38-room attr diff vs Appendix A | **PASS 38/38, FAIL 0** | Bulk `ha_get_state` on all 38 `*_occupied` sensors; all six `control_*` attrs field-identical to the fixture (lists exact incl. order; `control_climate_entity` string-or-null exact). **AV Closet canary PASS**: `control_lights == ["switch.switch_shelly1pmgen3_wifi_avcloset"]` (the Shelly relay, not the friendly-named light). Three fixture-title slugs differ from live entity ids (resolved via ha_search, attrs match): Master Bath Toilet → `binary_sensor.master_toilet_master_toilet_occupied`, Media → `binary_sensor.media_room_occupied`, Upstairs Guestroom → `binary_sensor.upstairs_guest_bedroom_occupied`. |
| L4 | v5.16.3 rider: write-verify restore | **PASS** | `last_verified_write_reserve_soc = {commanded: 30, oracle_seen: "30.0", verified_at: 2026-07-14T02:41:16Z (pre-restart), status: ok, write_route: cloud, restored: true}` — a pre-restart verified write survived restart with `restored: true`. `charge_from_grid` / `storage_mode` show `status: no_data, restored: true` (no prior write — honest empty restore). `write_mismatch_counts_24h` all 0. |
| L5 | Full WS functional smoke | **DEFERRED (as planned)** | Requires a long-lived access token the operator has not provided. Rides the PWA integration cycle. |

Boot-window transients observed and dismissed (known classes, not regressions): per-room "All N sensors unavailable — holding occupancy state for 60s", SPAN implausible-delta baseline resets, HVAC boot-settle TIMEOUT release after 60s, coverage-rating negative-delta post-restart INCOMPLETE, Bermuda fallback-to-polling. No "Envoy unavailable — holding" regression treatment needed (off_peak blind-hold guard known-safe).

**Note:** D2 operator options-edit round-trip (one room, live attr refresh without restart) not exercised this session — operator-driven; tracked in the G1 plan's completion checklist.
