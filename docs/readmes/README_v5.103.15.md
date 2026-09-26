# v5.103.15 — HVAC zones decide on the rooms that are actually running (live-room establishment)

**Card:** `HVAC-DEGRADED-ROOM-TRIPWIRE-1` (workstream `HVAC-W2-OCCUPANCY-TRUTH`) · Tier 2-DB (shared retreat gate consumed by row-1 / D7 / D9 / F4 row-10 across every zone) · plan `docs/planning/PLANNING_hvac_live_room_establishment.md` (REV 2) · read-first `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md`

## Problem
Before URA lets an HVAC zone retreat to `away`, it waits until the zone is *established* — until it has heard from every room in the zone. A room whose config entry is disabled, erroring, stuck retrying setup, or deleted never reports, so its zone never established and kept heating/cooling empty space forever, silently. The operator had ruled on 2026-09-17 (round 4) that establishment is computed over the rooms that are actually running; round 4 implemented it wrongly as `any()`, and round 5 (the orchestrator) reverted to `all(zone.rooms)` instead of fixing the implementation — overriding the operator. This cycle builds the operator's rule correctly.

## Fix
- **Room classification every producer pass** (`ZoneManager._classify_all_rooms`, DST-safe UTC clock):
  - **EXCLUDED** — `disabled_by` set, `SETUP_ERROR`, `MIGRATION_ERROR`, `SETUP_RETRY`, entry removed, or transient for ≥ `HVAC_LIVE_ROOM_TRANSIENT_GRACE_S` (300 s, module constant). An excluded room counts toward **nothing** — it acts as if it were not defined in URA (operator 2026-09-26). Failure exclusion is **sticky** until the entry is observed `LOADED` (stops SETUP_RETRY↔SETUP_IN_PROGRESS flapping).
  - **TRANSIENT** — `NOT_LOADED`, `SETUP_IN_PROGRESS`, `UNLOAD_IN_PROGRESS`, `FAILED_UNLOAD`, unknown future states → **blocks** establishment outright (reload cold-retreat safety).
  - **LIVE** — `LOADED`; counts only if its room coordinator was present on the latest pass AND it has been seen.
- **`is_zone_hvac_established`**: no transient rooms, ≥1 live room, and every live room LOADED + coordinator-present + seen. A zone of only excluded rooms never retreats.
- **Occupancy-only hold**: while a zone is blocked *only* by a reloading room and its live rooms are empty, the occupancy-driven switch back to `home`/`sleep` is held for that tick (no flap). House-state `away`/`vacation`, pre-arrival writes, and D5 shed/coast force-away still write. Each held episode writes one durable `transient_room_hold` ledger row.
- **Alerts**: one WARN + one MEDIUM NM per excluded room per HA start, only for rooms in an HVAC zone, `location=<room>` (so two rooms are not deduplicated into one).
- **Diagnostics** on `sensor.ura_hvac_coordinator_zone_{n}_status`: `live_rooms`, `excluded_rooms` (with reason), `transient_rooms` (with seconds non-loaded), `coordinator_absent_rooms` — guarded so they cannot break the sensor.
- **Latent crash fixed (pre-existing on develop)**: per-zone per-tick locals (`_d3_skipped_this_tick`, `_d5_occupancy_deferred_this_tick`, and the new `_row1_hold_write`) are initialised at the top of the zone loop; with `switch.ura_hvac_zone_intelligence` OFF every decision cycle previously raised `UnboundLocalError`.

## Review ledger
Plan: rev 1 (planner on opus-5) → orchestrator hand-check AM-1 CRITICAL (the rev-1 formula let a reloading, previously-seen room satisfy establishment) + AM-2 → adversarial plan review FIX-PLAN-FIRST F1–F13 (no `conditioning_demand` sensor exists; 2 missed consumers `binary_sensor.py:914`, `hvac_override.py:2319`; coordinator-presence conjunct; SETUP_RETRY excluded immediately) → REV 2. Build 5664b3fb3: A SHIP (3 LOW) · B FIX-REQUIRED (NM dedup; un-retreat flap) · D FIX-REQUIRED (deleted room; SETUP_RETRY flap) · validator 11 NEW (stale test stub + a source-window grep test). Fix-up 1 3e707612b → sent back (no call-site anchors) → 9374b2361 → re-review FIX-REQUIRED (HIGH `UnboundLocalError` with Zone Intelligence off, hidden by a test helper that swallowed exceptions) → round 3 de0774ba9. Pre-existing findings carded, not fixed: `HVAC-RELOADING-ROOM-PLACEHOLDER-READERS-1` (D5 coast, D6 source-4, continuous-occupied clock read a reloading room's placeholder "empty").

## Non-goals
- Other readers of a reloading room's placeholder empty (carded above).
- Occupancy fast path (W2 next), thermostat definition (W1), override-switch semantics (left as-is by operator).

## Live Validation (prospective — to be written back post-restart)
Today no URA room entry is disabled or failing (43 room entries, all LOADED), so the discriminating live signal is **no change** plus correct diagnostics:
- **Verify:** every `sensor.ura_hvac_coordinator_zone_{n}_status` shows `live_rooms` == the zone's rooms, `excluded_rooms == []`, `transient_rooms == []`, `coordinator_absent_rooms == []` once boot settles.
- **Verify (discriminating):** during the post-deploy restart, zones read `transient_rooms` non-empty while rooms load and **no zone retreats to away** in that window (recorder: no `vacant_past_grace` preset change between restart and all rooms LOADED).
- **Verify:** zone preset-change rate for the 24 h after deploy stays within the prior week's band (zone_3 9–33/day), i.e. no new flapping.
- **Verify:** zero `UnboundLocalError` / URA ERROR in the log after restart; no `hvac_degraded_room` NM (none expected — no failed rooms).
- **In-suite only (reason: no failed room exists live):** excluded-room establishment, sticky SETUP_RETRY, entry-removed alert, Zone-Intelligence-off decision cycle.

## Rollback
Revert the feature merge; no schema, config, or entity-registry changes (diagnostic attributes only).
