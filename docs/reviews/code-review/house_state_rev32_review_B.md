# Sleep-mask Rev 3.2 (per-entity zone tracker) — Build Review B (integration / lifecycle / races)

**Delta:** `dad3bf6e7...2244661c3` (three-dot, merge-base verified = `dad3bf6e7`). Tier 3, framing B.
**Read first, completely:** `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`, `docs/architecture/SENSOR_FLEET_CLASSES.md`, `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` (incl. §10 ledgers), and plan §R3 / §R3.1 / §R3.2 + build notes. No ledger claim re-asserted. Static review plus one standalone repro script (scratchpad). Suite not run (framing C owns pytest).

**Verdict: FIX-REQUIRED** (one HIGH, trivial fix).

## Findings

| ID | Sev | Site | Finding | Class |
|---|---|---|---|---|
| B-H1 | HIGH | `presence.py` `_reconcile_trackers_to_substrate` (~2350-2370) | **The boot-release reconcile writes into trackers that never receive the room's live edges.** It walks every tracker × `tracker.room_names`. Live edges, the boot replay and `_discover_room_sensors` all route through `tracker_for_room`, which is first-writer-wins over `_room_to_zone` (`presence.py:1949`, built at ~3465). The config flow offers every room to every zone (`config_flow.py:2153-2161`, no exclusion), so a room in two zones is legal. **Repro** (run against the branch, script `scratchpad/revB/repro_multizone.py`): room Hall in zones A and B, Hall's motion sensor `on` at release. Release: replay → A True; reconcile → B `update_room_occupancy("Hall", True, "motion")` → B OCCUPIED. Sensor off → False edge → A only. Output: `A: {'Hall': False} away  B: {'Hall': True} occupied`. Zone B is stuck OCCUPIED until restart, and again after every restart that releases while Hall is on. Effect: nobody-home blocked forever, β indoor guard blocked, consensus −0.4 pins the HVAC Wait-for-Presence gate, D4d pages only if Frigate is dark. Before Rev 3.2, B never saw Hall (no regression path existed). Violates INV-NO-STUCK-THROUGH-REMOVAL / INV-ZONE-ROOM-TRUTH. Not present on the live house (0 rooms in >1 zone in `core.config_entries`, read 2026-10-18), so the impact is other installs. **Fix:** in the reconcile, skip unless `self.tracker_for_room(room_name) is tracker`. Add a mutation-anchored test. | #53 sibling (new writer bypasses the routing primitive) |
| B-L1 | LOW | `camera_census.py:2371-2406` × D4d `held` | **A coverage gap in D4d's documented page surface.** A multi-sensor phantom (Jaya LD2410 + fan) now holds its zone continuously. That makes `_any_zone_occupied_snapshot` True, so any camera-count divergence is "corroborated" and keeps the higher count. Census ≥ 1 then blocks α and nobody-home *and* silences D4d (`census_count == 0` conjunct). Single-sensor rooms already behave this way, so this is a wider version of an existing residual, not a new mechanism. Plan row 7 calls the corroboration intended. **Ask:** add one line to the state-of-play D4d bullet: "silent when the holding sensor also corroborates a camera divergence". | coverage statement |
| B-L2 | LOW | `presence.py` `_check_zone_hold_all_away` (`tier1_rooms`) | `tier1_rooms` is collected from every tracker, including one whose mode is an AWAY override. A True slot set before an operator AWAY override persists, because only a *new* True edge auto-resumes. Case: zone A is OCCUPIED by camera only, and zone B is AWAY-overridden with a stale True slot. `held` passes the "Tier-1 holder" conjunct, and the page names the wrong room. Fix if cheap: collect only from trackers with `mode == OCCUPIED`. | diagnosis accuracy |

## Cleared (holds because)

| Area | Evidence |
|---|---|
| **Substrate dispatch vs tracker update ordering** | `_handle_state_change` is `@callback` (`occupancy_substrate.py:720`). HA's `async_track_state_change_event` and `async_dispatcher_send_internal` run Callback jobs synchronously (installed HA 2026.2.3 `helpers/dispatcher.py:245-247`). The sibling read, the bucket write, the dispatch and the tracker write therefore happen in one loop slice. Every event recomputes the full OR from current `hass.states`, so an out-of-order delivery converges. |
| **Refresh under the lock vs live events** | The body inside `_refresh_lock` stays await-free (re-read `occupancy_substrate.py:441-647`). The scratch seed, the subscribe, the `_raw_state = seed_target` swap, the map swap, the prune and the walk all run in one slice, so no live event lands mid-refresh. Overlap double-delivery is impossible for the same reason. Pre-refresh events use the old map, which is coherent. |
| **Scratch-copy swap** | The copy is shallow per room. Rooms outside the desired set carry over and are pruned at step 6. On subscribe failure it returns before the swap, leaving `_raw_state`, the map and the listener as they were. The retry re-snapshots coherent-old state against the same desired map, so the edges still emit. Nothing outside the substrate holds a `_raw_state` reference (grep: 0 external readers). `coordinator.py:1837` reads the map dict, which is still a dict. |
| **Real HA removal order** | Installed core `config_entries.py:2125-2152`: unload (or skip for non-recoverable) → `del self._entries[...]` → `await entry.async_remove` → `async_remove_entry` (`:1053-1056`), then `_async_clean_up`. `_discover_entity_map` enumerates `async_entries(DOMAIN)` regardless of state, so the "unloaded" refresh still sees the room (no-op), and the "removed" refresh no longer does. If the unloaded-refresh task happens to run after `del`, it emits the False edges itself and "removed" is a no-op. Both orders are correct. `async_remove_entry` filters to ROOM entries. hvac `_on_room_lifecycle` (`hvac.py:5440`) and binary_sensor `_on_lifecycle` (`binary_sensor.py:1760`) ignore `"removed"`. |
| **Boot: seed → settle → release → reconcile** | Replay is synchronous through the dispatcher before the reconcile runs, so the reconcile only pops True→False (apart from B-H1). An absent room reads all False through `get_room_kinds`. Rooms with no difference get no write, so UNKNOWN zones stay UNKNOWN. The `real_input` release at `presence.py:6164` runs before the zone flags at `:6387`, so the same tick sees reconciled trackers. The call is guarded. Reload path (born released): the replay fires before the presence subscription (pre-existing), but the trackers are fresh and `_discover_room_sensors` seeds them from the substrate. No stale True slot is possible. A deleted entity or room during settle is covered by the reconcile. |
| **Restart mid-refresh** | Nothing is persisted (substrate, tracker and D4d clock are all RAM). Teardown sets `_is_torn_down` and cancels the retry. Boot rebuilds from `hass.states`. |
| **Options-save reload of a room** | Neither reload path removes the entry. Both refreshes are no-ops unless the CONF lists changed. If they changed, the first refresh seeds from the new options. Reclassifying an `on` sensor emits a False edge then a True edge in the same slice. The inference runs as `async_create_task`, so it sees only the final state. Its AWAY-override auto-resume is pre-existing and identical with the switch off. |
| **Daytime consumers** | Zone mode/select, nobody-home, β, WAKING: more occupied, as intended (plan §R3.4.2). camera_census limb: see B-L1. Energy counts: analytics only. HVAC: `hvac*.py` reads presence only through `_signal_consensus` (`hvac.py:2717`, grep), and HVAC zone occupancy comes from room coordinators. Consensus arithmetic re-derived from `presence.py:7779-7792`: with all away and a Tier-1-held zone, 1 − 0.4 − 0.1 = 0.5, which does not engage (the −0.2 term needs not-all-away; −0.15 needs Tier-1 count 0). It is ≤ 0.6 < 0.7, so an engaged gate stays pinned. **The documented residual (ledger #22, PICK R3-4 accept) is correct.** |
| **D4d latch / restart / NM** | It mirrors `_check_sleep_raw_hold` exactly. The check-and-set is synchronous with no await. The episode latch resets on a non-held tick, and `fire_stuck_signal` adds a per-day RAM latch with severity HIGH. A restart resets both, so a continuing hold re-pages at most once per 2 h after each restart, which is acceptable. A dropped emit is not retried (same B-L3 acceptance as the sibling). It runs post-infer on the pre-transition `current_state`, so the held window is at most one extra tick. |
| **Switch-off byte-identity** | Every site is gated on `_ura_const.ZONE_OCCUPANCY_PER_ENTITY_ENABLED`: handler early return, live OR, scratch seed, walk, D4b, reconcile, D4d, `async_remove_entry`, D-H1 limb, forcing line. The always-on seed through `_kind_on_now` is set-equivalent to the old loop: desired-map entries for (room, k) are exactly `entity_map` ∩ mapping-room, and `on`→True, everything else off. The only always-present difference is that `async_remove_entry` exists, and with the switch off it returns at once. |

## Invariant checklist (framing-B lens)

| Invariant | Status |
|---|---|
| INV-ZONE-ROOM-TRUTH (ordering, refresh atomicity) | PASS except B-H1 (multi-zone room) |
| INV-NO-STUCK-THROUGH-REMOVAL | PASS for all three routes; **LEAK B-H1** (reconcile-introduced stuck slot) |
| INV-KILL-BYTE-ID | PASS |
| D4d coverage as documented | PASS with B-L1 wording gap |

## Summary

| Sev | Found | Must-fix |
|---|---|---|
| HIGH | 1 | B-H1 |
| LOW | 2 | (fix in-cycle per Fix-LOWs rule) |

**Must-fix:** B-H1 (guard the reconcile with `tracker_for_room(room) is tracker`, plus a test and drill). LOWs: B-L1 doc line, B-L2 restrict `tier1_rooms` to OCCUPIED trackers.

**QUALITY_CONTEXT candidate:** "a new writer that walks a fan-out structure directly instead of through the routing primitive (`tracker_for_room`) diverges from the live path wherever the routing is many-to-one", a #53 sibling.
