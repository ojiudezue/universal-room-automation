# v5.103.14 — Room-config save no longer stalls the event loop (reload suppression)

**Card:** `ROOM-CONFIG-SAVE-FULL-RELOAD-STALL-1` · Tier 2-DB (reload path + shared substrate primitive; 3 framing-disjoint reviews + orchestrator mutation-verify)

## Problem (operator-reported, log-confirmed 2026-09-19)
Saving a room's **Climate & Fans** options step triggered a **full ~90-entity ROOM reload** as a background task, which stalled the event loop for ~10–30s — the websocket backed up (`Client unable to keep up … >1024 pending`, `No PONG after 27.5s`) and HA went briefly unresponsive. **Not a restart/reset** (no core restart banner) — an unresponsive blip. Two root causes: (RC-A) the `room_last_applied_options` snapshot was never seeded at setup, so the *first save per room per HA lifetime* always fell through to a reload regardless of the allowlist; (RC-B) the options-flow climate step re-writes ~20 default-materialized fields per save, and none were in the reload-suppress allowlist, so `changed_keys` always escaped the suppress branch.

## Fix
- **D0 — seed the snapshot at setup.** `_seed_room_last_applied_options()` seeds `hass.data[DOMAIN]["room_last_applied_options"][entry_id] = dict(entry.options)` in ROOM `async_setup_entry`, before the update-listener registration (no interleave), popped on unload. Without this the first save always reloaded.
- **D1 — extend `_ROOM_SUPPRESS_KEYS` to the climate step (27 keys total).** Per-consumer-site audit (verdict = MIN over sites): 5 LIVE (incl. `hvac_vacancy_hold[_night]`, `target_temp_heat/cool`, `ble_hold_cap_enabled`), 16 REFRESHED-with-coverage (consumed via `automation.self.config`, re-derived every tick by `_refresh_config` at `coordinator.py:4934` and — new this cycle — at the top of `handle_humidity_based_fan_control`). Only `CONF_CLIMATE_ENTITY` stays EXCLUDED (an entity-id rewire correctly warrants a reload). A save whose changed keys are all allowlisted now applies **in place, no reload**.
- **A-H1 fix (review CRITICAL):** `handle_humidity_based_fan_control` now calls `self._refresh_config()` first — it runs *outside* the automation branches, so on the manual-mode/cover-off path the 12 humidity keys would otherwise read stale config after a suppressed save. This makes their REFRESHED coverage true on every reachable tick.
- **D2 — log-dedup** the two `_discover_entity_map` cross-room/multi-CONF WARNs (they re-fire on every suppressed save). The per-room `refresh_subscriptions` refactor is parked (`SUBSTRATE-PER-ROOM-REFRESH-1`); the suppressed path already reaches the substrate no-diff fast-path, so it does zero house-wide work.

## Review ledger
Plan-reviewed (6 must-fix folded: D0 seeding, REFRESHED taxonomy, INV-B restated, push prior-art, default-materialization, D2 descope). Build A = FIX-REQUIRED (H1 CRITICAL + 2 MED, all fixed) · B = SHIP (D0 lifecycle, signal-chain, fall-through all verified) · C/orchestrator mutation-verify: neutering the H1 refresh REDs `test_handle_humidity_based_fan_control_refreshes_config_first`; neutering the D0 seed REDs `test_seed_room_last_applied_options_called_before_add_update_listener`. 40 reload tests + 226 affected-file tests green. Validator: prior 39-name test-infra delta (AST-slice keep-set + a brittle text window) fixed in-cycle.

## Non-goals
- The deferred ZONE_MANAGER update from a climate save (`config_flow.py:11456+`, 2s async) is a separate stall path — carded `ZM-CLIMATE-DEFERRED-UPDATE-SUPPRESS-1`, not touched.
- Per-room substrate refresh — parked `SUBSTRATE-PER-ROOM-REFRESH-1`.

## Live Validation (prospective — to be written back post-restart)
- **Verify:** saving a room's Climate & Fans step changing only threshold/toggle values (no climate entity change) produces **no** `Setting up universal_room_automation` for that room entry in the log, and **no** websocket "unable to keep up" / PONG-timeout in the following 30s.
- **Verify:** saving with `CONF_CLIMATE_ENTITY` changed **does** reload (fall-through preserved).
- **Verify:** `sensor.<room>` climate/humidity behavior unchanged after an in-place-applied save (config read live/next-tick).
- **Zero URA ERROR** post-restart.

## Rollback
`git revert` the merge — additive (a new setup seed + allowlist entries + a handler-local refresh + log dedup); no schema/persistence change.
