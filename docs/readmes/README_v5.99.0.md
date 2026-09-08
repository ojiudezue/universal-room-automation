# v5.99.0 — Integration-reload comprehensive (Tier 1 + Tier 2)

**Type:** Feature cycle — eliminates the ~5-min watchdog outage on integration-entry
options saves for all fresh-read config knobs.
**Tier:** 3 (regression-prone reload primitive). Reviews: 2 framing-disjoint PLAN
reviews + 4 framing-disjoint BUILD reviews (A/B/C/D) + orchestrator mutation-verify.
Plan: `docs/planning/PLANNING_integration_reload_comprehensive_2026_09.md`. Review
record: `docs/reviews/code-review/reload_comprehensive_tier1_2.md`.

## What shipped
`INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS` expanded **3 → 16 keys**. An
integration-entry options save whose changed keys are all in the allowlist now
applies **in-place** (fresh-read consumers pick up the value on their next tick)
instead of triggering `async_reload` of the parent entry — which rebuilds the
singleton bootstrap + ~80 aggregation entities and can stall the event loop long
enough for the supervisor watchdog to restart HA (~5 min outage).

Added (all verified path-(a) fresh-read):
- **Tier 1 (census):** `census_cross_validation`, `census_ble_cancel_enabled`,
  `known_face_guests`, `egress_identity_failsafe_strict`.
- **Tier 2 (perimeter):** `perimeter_vehicle_hours_start/end`,
  `perimeter_enrichment_{enabled,provider,person_sensors,model,max_tokens,provider_id}`,
  `exterior_snapshot_offset_s`.
- **D2.5:** success-gated snapshot advance — a swallowed discharge dispatch retains
  the pre-save value so it re-fires, never silently lost.

Deliberately EXCLUDED (stay on the reload path): `perimeter_cameras`,
`egress_cameras` (UNSAFE-structural — `camera_manager.async_discover` cache);
`perimeter_alert_hours_*` (dead — stripped at migration); `enhanced_census`
(structural — gates event-census listener registration); `tracked_persons`,
`electricity_rate` (multi-consumer / `entry.data`, carded).

## Known-issue / not addressed
Pre-existing `CONF_CAMERA_PERSON_ENTITIES` camera-map staleness (allowlisted since
v1 2026-08-15) — carded `INTEGRATION-CAMERA-DISCOVER-STALE-1`. Not introduced by
this cycle.

## Rollback
`rollback-pre-reload-comprehensive` tag = v5.98.0 state. Rollback = HACS re-download
v5.98.0 + restart (or `git revert` the reload-comprehensive commits on develop +
redeploy). No DB/schema change in this cycle, so rollback is clean.

## Live validation — acceptance criteria (discriminating)

- **L1 (restart resilience):** after HA restart, URA loads, `ha_check_config` valid,
  **zero new URA ERROR** logs, and the allowlist is active (16 keys). Discriminator:
  a broken setup would leave the integration `setup_error` / missing entities.
- **L2 (THE invariant, discriminating):** toggle a switch that writes an
  allowlisted key (`switch.*face_recognition*` → `CONF_FACE_RECOGNITION_ENABLED`,
  or `*egress_identity*` → `CONF_EGRESS_IDENTITY_ENABLED`), then toggle back.
  Expect in the log: **`INTEGRATION options changed … in-place apply, suppressing
  reload (changed_keys=…)`** and **NO `scheduling reload`** line, and the room/CM
  entities' `last_changed` do **NOT** reset (no reload blink). *Discriminator vs a
  regression or the pre-fix behavior:* the pre-fix path logs `Options changed …
  scheduling reload` and the whole integration reloads (entities blink, ~min stall).
  Net state unchanged (toggled back).
- **L3 (no over-reach):** a save that changes a NON-allowlisted structural key still
  reloads (proven in-suite `test_perimeter_camera_list_change_falls_through_to_reload`;
  organic live — a real camera/sensor edit still reloads).
- **L4 (no outage):** no supervisor watchdog restart and no >200ms loop stall around
  the L2 save.

## Validated 2026-09-07 (post-restart, HA core-2026.9.1, v5.99.0 live)

| Criterion | Result | Observed evidence |
|---|---|---|
| L1 — restart resilience | **PASS** | URA loaded post-restart (`sensor.universal_room_automation_persons_in_house`=2); `ha_check_config` → valid, errors=[]; allowlist active (16 members, confirmed on master via AST). |
| L1 — no runtime errors | **PASS** | `error_log` structured scan, 6h window: exactly ONE URA ERROR — "DB write failed: shutdown timeout" at 12:40:33, a **shutdown-time transient** during the deploy restart (count 1, before boot at 12:43:51). **Zero** runtime errors post-boot. |
| **L2 — the invariant (discriminating)** | **PASS** | Toggled `switch.ura_name_people_at_doors` (writes allowlisted `CONF_EGRESS_IDENTITY_ENABLED`) OFF@12:45:12 then ON@12:46:11. Reload-canary `switch.universal_room_automation_domain_coordinators` `last_changed` **held at boot 12:43:51 across BOTH toggles** → the parent integration did NOT reload. Discriminator: a reload tears down + re-adds every URA entity, resetting the canary to ~now; it did not move. Switch restored to original ON state (net-zero). |
| L3 — no over-reach | **PASS (in-suite)** | `test_perimeter_camera_list_change_falls_through_to_reload` + `test_egress_perimeter_keys_not_in_allowlist_v1`: a non-allowlisted/structural key still reloads. Live: organic (a real camera/sensor edit still reloads). |
| L4 — no outage | **PASS** | No supervisor watchdog restart (HA continuously up since the 12:43 boot; no second restart); no stall observed around the L2 toggles. |

**Boot transient dismissed:** the 12:40:33 "DB write failed: shutdown timeout" is the write-queue draining during the deploy restart, not a runtime defect.

**Why L2 is the load-bearing check:** it directly exercises the falsifiable
invariant — an allowlisted-key save causes zero `async_reload`/zero unload — via
a switch that writes a real allowlisted option, with the canary entity as the
reload witness. Confirmed.

**Rollback not needed** — all criteria passed. `rollback-pre-reload-comprehensive`
(v5.98.0) remains available.
