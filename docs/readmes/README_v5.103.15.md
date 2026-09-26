# v5.103.15 — HVAC zones decide on the rooms that are actually running (live-room establishment) + energy coverage self-check stops false unit-mismatch alarms

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

## Live Validation — Validated 2026-09-26 (HACS v5.103.15 installed, HA restarted 17:49:46Z)

Pre-deploy gate: full-suite name-diff (`scripts/suite_namediff.py`, branch `be9f441e0` vs develop cached baseline) **0 NEW** failing names; merged tree differs from the tested tree by one comment-only hunk in `hvac_setpoint.py`; PR #587 carries the code.

| # | Criterion | Result | Evidence |
|---|---|---|---|
| 1 | Zone diagnostics after boot settles | **PASS** | `sensor.ura_hvac_coordinator_zone_{1,2,3}_status` at 12:53:58 CDT: `live_rooms` 12 / 14 / 14 (all zone rooms), `excluded_rooms` `[]`, `transient_rooms` `[]`, `coordinator_absent_rooms` `[]` on all three |
| 2 | No zone retreats to away because of the restart | **PASS** | zones 2 and 3 were already `away` on every row from 11:30 to 12:46 CDT (pre-restart) and stayed away; zone 1 came up `home`. No transition into away attributable to the boot window. `transient_rooms` was never observed non-empty — rooms loaded before the first sampled state, so the transient path itself is proven in-suite, not live |
| 3 | No `UnboundLocalError` / URA ERROR after restart | **PASS** | error_log after restart: zero ERROR lines from `universal_room_automation`; URA lines are boot WARNINGs only (sensors unavailable → 60 s hold, Envoy unavailable, census cameras unavailable). ERRORs present are other integrations (Shelly, habluetooth, MQTT, Roborock, Denon) |
| 4 | No degraded-room NM | **PASS** | no `degraded` log line; no room excluded, so none expected |
| 5 | 24 h preset-change rate within prior band | **PENDING (evaluate 2026-09-27)** | see finding below — zone 1 was already flapping on v5.103.14, so this criterion must be judged against that pre-existing rate, not the zone-3 band |
| 6 | Coverage: no "unit mismatch" warning across local midnight; window attribute published | **PENDING (evaluate after 2026-09-27 00:00 CDT)** | cannot be observed before the next re-anchor |

**In-suite only (no failed room exists live):** excluded-room establishment, sticky SETUP_RETRY, entry-removed alert, Zone-Intelligence-off decision cycle, transient-room hold.

**Finding surfaced during validation (pre-existing, not caused by this release):** from 08:54 to 12:49 CDT the zone 1 thermostat flipped home ↔ away ~46 times. URA wrote only `away` (reason `vacant_past_grace`) every 10 minutes; the thermostat's config feed (`hold_activity`) read `away` throughout while its status feed (`preset_mode`) kept reporting `home`, so URA kept re-issuing. Recorded on `HVAC-ZONE1-MANUAL-OSCILLATION-1` (`finding_2026_09_26_away_feed_split`); belongs to W1-B (which feed confirms a write).

---

## Also shipping: `COVERAGE-RATING-FALSE-ANOMALOUS-1` (already on develop, reviewed + orchestrator-verified 2026-09-25)
**Problem.** URA's energy coverage self-check (room-attributed vs whole-house measured) disagreed with itself by roughly sevenfold after restarts; the code assumed the gap closes at the next local midnight re-anchor, it did not, and once the post-restart allowance expired the check asserted a specific (unproven) "unit mismatch" diagnosis.
**Fix** (`aggregation.py` `_get_coverage_rating` + warnings; commits `c5ea7dfc7`, `ca69d45c2`): a negative delta is excused across the local-midnight re-anchor as well as post-restart (`COVERAGE_MIDNIGHT_REANCHOR_WINDOW_MIN = 120`, rung-1 constant, sized from 10 days of recorder history); the warning no longer asserts unit-mismatch as fact; the excuse and genuine out-of-bounds warnings have separate throttles; the window attribute is published on the no-data path; an absolute-time backstop bounds the excuse.
**Reviews:** A (local correctness) SHIP; B (test authority, 5 mutation drills) SHIP; fix-up folded MEDIUM-1 + LOWs; orchestrator re-ran 163 passed / 0 skipped and its own mutation drill (red then restored).
**Live Validation (prospective):** after restart and across the next local midnight, no "unit mismatch" warning line for coverage; the coverage-rating sensor shows the re-anchor window attribute; a genuine out-of-bounds (if any) still warns on its own throttle.

## Rollback
Revert the feature merge; no schema, config, or entity-registry changes (diagnostic attributes only).
