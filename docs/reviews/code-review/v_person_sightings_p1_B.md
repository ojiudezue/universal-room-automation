# Person sightings Phase 1 — Review B (integration / lifecycle / async)

Branch `feature/person-sightings-p1`, head `b2f508ef`, three-dot diff against `3348d379` (merge-base
verified = `3348d379`). Plan `PLANNING_person_sighting_layer.md` rev 11. Tier 3, framing B only:
setup/teardown order, listener and timer cleanup, re-setup and options rebinds, untracked tasks,
the DB write path of the egress outcome log, cross-coordinator ordering, restart, no-op path.
Findings already in reviews A (incl. fix-up) and D are not repeated.

Read in full first: `docs/Coordinator/IDENTITY_FUSION_CAMERAS_MANUAL.md`,
`docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`, `docs/architecture/SENSOR_FLEET_CLASSES.md`,
`docs/QUALITY_CONTEXT.md`. No claim from the presence §10 ledger is re-asserted. No test run (the
validator owns the suite); all findings are from source reads with file:line.

## Findings

| # | Sev | Class | Site | Finding |
|---|---|---|---|---|
| B-M1 | MEDIUM | #58 lifecycle hook lost / #14 snapshot staleness; trip-wire blind (#56) | `person_sighting.py:371-376` (`_maybe_rebind`), `:384-389` (`on_tick`), `:244-255` (`_room_cameras_lookup`) | A URA fused room pick resolves through that room's `CONF_ROOM_CAMERAS` at bind time. Re-resolution fires only on (1) a new resolver object (`camera_census._get_resolver`, rebuilt only after an entity/device REGISTRY update, `camera_census.py:486-544`), (2) a changed `zone_cameras` pick set, (3) HA started, (4) the 300 s add-only retry of UNRESOLVED picks. A room options edit of `CONF_ROOM_CAMERAS` is a config-entry change, not a registry change, and the pick stays "resolved", so none of the four fires. Repro: Family Room fused pick bound to camera X; operator replaces X with Y in the room's cameras. The producer keeps `_face_to_physical` on X's face sensors; Y's faces give no sighting. The D4 denominator joins ring stems through the same stale `_face_to_physical` (`:741`), so `face_sighting_zero` cannot page. Bound: until any unrelated registry update or a restart (frequency not measured). Fix: rebuild on `SIGNAL_ROOM_ENTRY_LIFECYCLE` (presence already subscribes, `presence.py:~3100`, writers at `__init__.py` loaded / unloaded / options_updated), or include each fused pick's room-camera list in the `_bound_picks` comparison. Add a test: change a room's cameras, tick, assert the new camera's face emits. |
| B-L1 | LOW | Blast radius of a new non-essential step | `presence.py:3159` | `_setup_person_sightings()` sits inside the shared discovery `try` (`:3020`, except at `:3198` "non-fatal"). An exception there skips every later step in that block: the `SIGNAL_CENSUS_UPDATED` subscription, the zone-delete prune subscription, `SIGNAL_ZM_ZONES_UPDATED`, `SIGNAL_OPTIMIZER_INTENT`. Unguarded raise points: `_bind_pick` calls `resolver.face_name_entities_for_device` / `canonical_camera_key` outside a try (`person_sighting.py:333-349`), and `_resubscribe_faces` calls `async_track_state_change_event` unguarded (`:367`). No legal-config repro found (the resolver helpers are dict lookups), so LOW. Fix: wrap the call in its own `try/except` with a WARNING, as the transit-validator path-map setup already does (`__init__.py:3476-3479`). |
| B-L2 | LOW | #64 executor-typed callback (pre-existing, now load-bearing) | `presence.py:2985` `_on_face_recog_changed` | A plain `def` handed to `async_dispatcher_connect`, so HA runs it as an executor job. It only reads config entries and writes a bool, so nothing raises. Since the A2 fix-up it gates every interior sighting, the zone display write and the D4 trip-wire (`person_sighting.py:528`, `:534`, `:658`, `:759`), so a switch flip is applied off-loop, a short time after the signal. Pre-existing (not in the diff). Fix: add `@callback`. |
| B-L3 | LOW | Shared-path race | `button.py` `ReloadInteriorPathsButton.async_press`, `transit_validator.py` `_spawn_path_map_load` / `async_load_path_map` | The button awaits `async_load_path_map` directly, outside `_path_map_tasks`, so it can overlap a debounced re-validation load. Both compute `first` and install state after the executor await, so the last to finish wins. They diverge only if the file changes between the two reads. Phase 1 has no runtime reader, so the impact is provenance display only. Note for Phase 2: serialise loads (an `asyncio.Lock` or a generation counter) before a scorer reads `path_map`. |
| B-L4 | LOW | Health-check false page | `const.py:6026/6047` (`egress_identity_outcome` in `MEMORY_WRITER_BACKED_EPISODE_TYPES`) | The weekly memory-writer check pages after 0 rows in 7 days. Rows come only from crossings. A whole-house absence of 7+ days (e.g. vacation with no door crossings) pages, which is a false alarm. Accept and document, or skip the check while the house is in VACATION. |

## Cleared (holds because)

- **Producer listeners and teardown.** All four registrations are released in `async_teardown`
  (`person_sighting.py:178-208`): the bus egress listener (`_unsubs`), the face tracker
  (`_face_unsub`), the STARTED once-listener (`_started_unsub`, cleared in `_on_ha_started` before
  use, so no double unsub after firing) and the census bridge callback (removed from the shared list).
  `enabled = False` stops any later callback (`:398`, `:423`, `:451`). Every callback is `@callback`
  (`:173`, `:395`, `:420`, `:448`), so #64 is clear on the new code. Presence tears the producer down
  first in `async_teardown` (`presence.py:8877-8884`) and before a re-setup (`:5509-5511`). The bridge
  list is never popped on integration unload (`__init__.py` `camera_manager` / `census` pops only), and a
  rebuilt census reads the same list per message (`camera_census.py:5630-5633`); pinned by
  `test_census_reload_keeps_callback` and `test_teardown_unsubscribes_all`.
- **Rebind ordering.** `on_tick` runs the full `_maybe_rebind` BEFORE the add-only retry, and the retry
  updates `_bound_resolver` only after the full rebuild has matched it, so a partial retry can never
  hide a resolver change. `_resubscribe_faces` swaps the tracker synchronously on the loop, so no
  event is lost between unsub and resub.
- **Integration unload order.** `egress_tracker.async_teardown()` (`__init__.py:5924-5927`) runs before
  `database.async_close()`. The `_torn_down` latch is set first (`transit_validator.py` teardown),
  `_log_egress_outcome` returns on it, and in-flight writes are gathered with a 5 s bound and cancelled
  on timeout. Path-map listeners, the debounce timer and load tasks are all released in the same
  teardown. Census is popped before `coordinator_manager.async_stop()`. Producer calls in that
  window see `_census() is None`: `_emit` counts unmapped and returns, and `_denominator` returns 0.
  No crash and no page.
- **Outcome-log DB path.** About 15 rows a day, one `log_memory_episode` per resolution through `_db()` (the
  single-writer queue, `database.py:580`). The type is registered. Per-crossing `node_id`/`source_ref` avoid
  the 60 s `(node_id, type)` dedup merge. There is no per-tick write.
- **Path-map STARTED / registry listeners.** `_on_started` and `_fire` are `@callback`. The once-listener
  unsub lambda is a no-op after firing. Re-validation is debounced (cancel-and-rearm), does nothing once
  the file is installed, and does nothing after teardown.
- **Restart.** Sightings, the last-sighting store, `_last_home_edge_ts` and the trip-wire latches are RAM
  only. The boot drop (`setup_ts + 600 s`) applies to all sources and the D2 rule. Restore edges
  (`old_state` None / HA `unavailable`/`unknown`) are dropped at `:433`. The geofence stamp needs a real
  prior state (`presence.py:5297`). Nothing is persisted, so nothing can be restored stale.
- **Observation mode (#23).** The only new `SIGNAL_PERSON_ARRIVING` dispatch (`presence.py:5576`) is behind
  `self.observation_mode` (`:5545`). `SIGNAL_PERSON_SIGHTING` has no subscriber.
- **Security gate (cross-coordinator).** `face_input_corroborated` returns False on a torn-down regime, and
  a missing regime is rejected (`security.py:2436-2445`). The face's own `ts` is passed, so both gates
  read one clock.
- **No-op path.** With `FACE_SIGHTING_ENABLED` False: no ring (`camera_census.py:1539`), no callback, no
  listener (`person_sighting.py:144`). The camera-change handler only loses the dead v3.19 branch (D5,
  by design). The day-boundary prune replaces `clear()` and prunes only expired keys (A4).

## Verdict: SHIP

No CRITICAL or HIGH. B-M1 should be fixed in the fix-up pass. Phase 1 consumers are display-only plus a
gated-off arrival rule, so it does not block ship, but it does blind the D4 trip-wire. Fix B-L1 and
B-L2 at the same time (each is under 5 lines). B-L3 is a Phase 2 note. B-L4 needs an operator decision.

| Sev | Found |
|---|---|
| CRITICAL | 0 |
| HIGH | 0 |
| MEDIUM | 1 |
| LOW | 4 |

| Bug class | Count |
|---|---|
| #58 / #14 lifecycle snapshot (+ #56 trip-wire blind) | 1 |
| Setup blast radius | 1 |
| #64 executor-typed callback | 1 |
| Concurrent load race | 1 |
| Health-check false page | 1 |
