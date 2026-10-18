# Plan review R1 (completeness) — sleep-mask plan §R3 (Rev 3, D4 + D1-S)

**Plan:** `docs/planning/PLANNING_house_state_sleep_mask_ble_memory_observability.md` §R3 @ `af238dc53` (develop).
**Code:** branch `feature/house-state-sleep-mask-ble-memory` @ `dad3bf6e7` (read via `git archive`). All `file:line` below are on `dad3bf6e7`.
**Framing:** completeness. Independent re-enumeration of readers, writers and wipe-dependent timeouts; stuck-occupied paths; D1-S deletion safety; D-H1 test/drill table; kill-switch byte-identity.
**Read completely first:** `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (incl. §10 ledger #1–#16), `docs/architecture/SENSOR_FLEET_CLASSES.md`, `AUDIT_census_arc_and_away_holistic.md` §P6. No ledger claim is re-asserted here.

**Verdict: FIX-PLAN.** 3 HIGH, 4 MEDIUM, 4 LOW. The reader list (§R3.4.2) is complete. The writer list is not: it misses the boot-settle release, the refresh failure path and a dead writer. The kill switch is not byte-identical to `dad3bf6e7`.

---

## Findings

### F1 — HIGH — boot-settle release leaves a kind stuck True (INV-ZONE-ROOM-TRUTH falsified)
- Cold boot order: `substrate.async_setup()` seeds `_raw_state` (`presence.py:2864`). Then `_discover_room_sensors()` writes every True kind into the tracker (`presence.py:2938`, `:3538-3556`), while the substrate's `_boot_settle_done` is still False.
- During settle a sensor that goes off updates `_raw_state` silently (`occupancy_substrate.py:696-699`).
- `release_boot_settle()` replays **True slots only** (`occupancy_substrate.py:643-647`). No False edge reaches the tracker.
- Today a sibling's off-edge wipes the room (`presence.py:874-895`), which releases it by accident. D4b removes that release. After D4 the kind stays True until **that kind's** sensor fires on and then off again.
- Rooms deleted, and sensors removed from CONF during settle, take the same route. The refresh step 7 is gated on `_boot_settle_done` (`:535`), and step 6 prunes the room silently (`:526-528`).
- **Repro (legal config):** Guest Bedroom 2 has a Matter radar (presence_sensors) and a meross motion bit (motion_sensors). The radar reads `on` at boot. The guest leaves 30 s later, inside settle, and the radar goes `off`. At release nothing is emitted, so GB2's zone tier reads occupied until someone next enters and leaves GB2. That can be hours or days, and it blocks nobody-home and β's indoor guard.
- The plan's test `test_boot_settle_replay_unchanged` pins this defect, and §R3.8.2 ("a sensor that changes during settle … is replayed at release") is only true for True.
- **Fix in plan:** at `_release_boot_settle` (`presence.py:2327-2351`), after `substrate.release_boot_settle()`, run an exact per-kind tracker reseed for every tracker room. Write the substrate value, or False when the room is absent from the substrate. This is the natural home for D4c.3 (see F8). Add `test_release_clears_kind_that_went_off_during_settle` with a drill that drops the reseed and goes RED.

### F2 — HIGH — kill switch False is neither byte-identical nor safe
- §R3.7 says that `ZONE_OCCUPANCY_PER_ENTITY_ENABLED = False` restores "the reviewed branch, byte-identical". §R3.8.2 says (False, D1 True) "gives the reviewed branch".
- But the D1-S deletions are unconditional. They remove the D-H1 live limb (`presence.py:4044-4061`) and the forcing line (`:6271-6276`). With the constant False, the tracker is lossy again (last-writer plus full clear), and D1's nobody-home reads `_zone_night_raw`, which is now tracker-only. **That reopens D-H1 at night.**
  - Repro: constant False, D1 True, a ZX holds a sleeper and a ZV pulses then clears. The room is wiped, and nobody-home fires AWAY on a sleeper while census is 0.
- The gating is also unstated for D4c.1 (deleted entity), D4c.2 (removed-room edges) and D4d (it has its own bound, 7200 by default). That leaves the build ambiguous. INV-BYTE-ID-SINGLE permits D4c and D4d as differences, and R3.7 forbids them.
- **Fix in plan:** do one of the following:
  - (a) gate the D1-S deletions on the constant, so the limb and forcing line survive when it is False; or
  - (b) declare the kill switch coupled (False requires D1 False) and rewrite R3.7 and R3.8.2.

  Either way, add one table that lists every Rev-3 site and whether it is gated. Add a test that runs the D-H1 repro with the constant False and D1 True.

### F3 — HIGH (build-prediction) — `_kind_on_now` reads the wrong map during refresh
- D4a defines `_kind_on_now(room, kind)` over `_entity_to_room_kind` (or an index "rebuilt wherever `_entity_to_room_kind` is assigned (`:335`, `:510`)"), and requires the seed to use the same helper.
- In `refresh_subscriptions` the seed runs at step 4 (`:482-485`), but the map is repointed only at step 5 (`:510`). A helper that reads `self._entity_to_room_kind` would seed from the **old** map:
  - an added sensor is ignored (stuck False until its next edge);
  - a removed `on` sensor still counts (stuck True, which falsifies INV-NO-STUCK-THROUGH-REMOVAL);
  - and this also happens with the constant False, which breaks byte-identity.
- **Fix in plan:** `_kind_on_now(room, kind, entity_map)` takes the map explicitly. The seed passes `desired_entity_to_room_kind` and the live handler passes `self._entity_to_room_kind`. Alternatively, build the index from the desired map before step 4. Add a drill that seeds from the old map and goes RED on `test_options_save_removing_on_sensor_releases_room`.

### F4 — MEDIUM — reading the event entity from `hass.states` breaks existing harnesses; prefer the payload
- Several tests drive `_handle_state_change` with a populated event and `hass=MagicMock()`, without setting `hass.states`. Examples: `test_presence_guest_latch_and_veto_gap.py:620-660` (`test_d3_last_edge_entity_recorded_on_edge`, `test_d3_edge_log_at_debug_level`). Under D4a `MagicMock().state != "on"`, so those tests go RED for a harness reason, not a defect.
- Other suites that call `_handle_state_change` are missing from §R3.6's "Existing suites" list:
  - `test_lighting_slice_c_manual_hold.py`
  - `test_reconcile_on_return.py` / `_reconcile_harness.py`
  - `test_room_substrate_integration.py`
  - `test_substrate_boot_settle.py`
  - `test_presence_guest_latch_and_veto_gap.py`
  - `test_substrate_backcompat.py` (it sets a single global `hass.states.get.return_value`, so it cannot express "sibling on")
- **Recommendation:** compute `occupied = on(event.new_state) or any(on(hass.states.get(s)) for s in siblings(room, kind) if s != entity_id)`. This makes INV-BYTE-ID-SINGLE true by construction (no `hass.states` read when there are no siblings), keeps those harnesses valid, and does not depend on the HA ordering (which is verified anyway: `core.py` stores the state before `async_fire_internal`, and `async_remove` pops it before firing `new_state: None`). The builder greps `_handle_state_change(` across `quality/tests` and lists every hit.

### F5 — MEDIUM — the refresh failure path desyncs the tracker (pre-existing; §R3.8.2 claim is wrong)
- If `async_track_state_change_event` raises (`occupancy_substrate.py:497-506`), step 4 has already reset and reseeded `_raw_state` against the **new** config. The method then returns with the old map, no synthetic edges and the old listener.
- The 30 s retry snapshots the already-reseeded state, so it finds no delta and emits nothing:
  - a removed `on` sensor leaves the tracker stuck True;
  - an added `on` sensor leaves it stuck False, which is the unsafe direction for SLEEP→AWAY.
- §R3.8.2 says "keeps the old listener, so tracker state stays coherent". That is false.
- **Fix in plan:** restore `_raw_state` from `snapshot` before the early return, or reseed and emit edges against the old map, and add a test. It is rare, but it is a stuck path on the invariant the plan claims.

### F6 — MEDIUM — D4c.2 (removed room) reachability depends on unverified ordering
- HA `ConfigEntries._async_remove` unloads first and then runs `del self._entries[...]` (installed `config_entries.py`, `_async_remove`). The URA "unloaded" lifecycle dispatch fires inside unload (`__init__.py:6140-6147`) and schedules the refresh as a task.
- If that task runs before the `del`, `_discover_entity_map` still enumerates the room. The refresh is then a no-op, and D4c.2's False edges wait for the **next** lifecycle event from any room, possibly days later. Meanwhile the deleted room's sensors stay subscribed and keep driving the zone tier live.
- During settle, D4c.2 emits nothing (step 7 gate). F1's release reseed covers that case.
- **Fix in plan:** add a test that drives a real delete ordering, or have the unloaded handler filter entries by state (skip entries not `LOADED`), or schedule a follow-up refresh. At minimum, state the latency in INV-NO-STUCK-THROUGH-REMOVAL. A disabled (unloaded, not deleted) room keeps contributing. That matches the §R3.12 non-goal, but say so.

### F7 — MEDIUM — D4d coverage is overstated
- `census_count = max(camera_total, |face ∪ ble|)` (`presence.py:1172-1176` comment; producer `:4960`). An unidentified body or a face hit therefore makes census ≥ 1. With D4d's `census_count == 0` condition, D4d can fire only when α is blocked by **`camera_input_degraded`** (Frigate dark).
- §R3.3 ("an unidentified or face hit, or α starved") and §R3.8.1 (house column: "Frigate dark or a face/unidentified hit"; Generic: "fires only if α is blocked by a face hit") are wrong. In the Generic shape (no cameras, so never degraded) D4d never fires.
- The trigger also accepts any `any_zone_occupied`: camera-tier hold, fan-interference hold, outdoor zones. It can therefore page with an empty "on entities" diagnosis (LOW).
- **Fix in plan:** correct the text and get an operator ack that "Frigate-dark only" is the intended page surface. Optionally require at least one Tier-1 holder room (`any(provenance)` over zone rooms) in `held`.

### F8 — LOW — D4c.3's premise is false
- `_discover_room_sensors` has exactly one call site (`presence.py:2938`, presence `async_setup`). It always runs against trackers just built by `_discover_zones`, so a "re-discovery reseed" never happens, and Q7's "a kind that was True and is now False would survive the reseed" cannot occur there.
- D4c.3 also changes `_room_provenance[r]` from `{}` to all-False slots for empty rooms. That shows in `to_dict()["rooms_provenance"]` (`presence.py:976-978`) and in `sensor.py:5872`, a display-level INV-BYTE-ID-SINGLE difference.
- **Fix:** drop D4c.3 as written, and reuse the exact per-kind writer as F1's release reseed.

### F9 — LOW — writers missing from the wire-in table
- `_handle_occupancy_change` (`presence.py:5030-5079`) is a dead writer: it has no listener registration, and grep finds only docstring references. It writes the event entity's state per kind and bypasses `_kind_on_now`. Record it as KEEP+DOCUMENT ("would reintroduce last-writer if revived") or delete it.
- `coordinator.py:1822-1840` (the substrate-gap canary) reads `substrate._entity_to_room_kind` as `dict` membership. Any index must be additive; keep the dict.

### F10 — LOW (build-prediction) — the test harness change is unspecified
- The drill runner is `(id, file, swap_from, swap_to, anchor)` with one `ANCHOR` file (`test_house_state_sleep_mask_mutation_drills.py:27`, `:78`), and it has no `occupancy_substrate.py` path constant. The new `test_zone_tracker_per_entity.py` anchors need a per-drill anchor-file column and a `SUB` path.
- `World` uses a stub substrate, `SimpleNamespace(get_room_kinds=lambda r: {})` (`test_house_state_sleep_mask_ble_memory.py:~306`), and drives the tracker directly. Its `clear()` helper uses a kind=None full clear (`:325-331`). The §R3.6 rows that say "re-drive through the real substrate" need a specified harness: a real `OccupancySubstrate`, `async_track_state_change_event` patched, and the substrate's `async_dispatcher_send` routed to `coord._on_substrate_kind_changed`. Otherwise the builder will hand-roll it and may bypass `_on_substrate_kind_changed`.

### F11 — LOW (pre-existing; card, not this cycle) — room rename
- Zone discovery resolves room names from `room_entry.data` only (`presence.py:~3360-3364`), while the substrate uses data merged with options (`occupancy_substrate.py:207`). A room renamed through options keeps its old name in `room_names`. Every substrate edge for the new name then finds no tracker (`presence.py:3582-3588`), so the zone tier silently loses the room.
- D4c.2 at least releases the old name's True kinds, which is a strict improvement. Card it as ZONE-ROOM-NAME-DRIFT.

---

## Re-enumeration (independent grep on `dad3bf6e7`)

Grep: `update_room_occupancy|_room_provenance|provenance_for|_room_occupied\b|\.raw_occupied|_derived_mode|get_room_kinds|is_kind_active|SIGNAL_SUBSTRATE_KIND_CHANGED|zone_trackers|tracker_for_room|\.mode == ZonePresenceMode|_raw_state|_entity_to_room_kind|last_edge_entity_for|_last_kind_per_room|_entity_to_room\b|get_all_room_kinds` over `custom_components/`.

**Readers:** all match plan rows 1–21. Hits outside the plan table, verified as not occupancy reads:
- `coordinator.py:2992`, `:3664`, `:4434-4452` read the tracker's fan maps and hold dict only;
- `hvac*.py`, `switch.py`, `automation.py`, `optimization.py` and `person_coordinator.py` `*_room_occupied` are different symbols (HVAC `RoomCondition`, room-local);
- `memory_facade.py:84-86` contains label strings;
- `sensor_capability.py`, `chatter_detector.py` contain comments.

Also add `coordinator.py:1837` (F9). **The reader list is complete.**

**Writers of raw/tracker state:**

| Writer | Site | In plan? | D4 status |
|---|---|---|---|
| substrate live handler | `occupancy_substrate.py:659-712` | D4a | OK; see F3/F4 |
| substrate seed (setup) | `:314-343` | D4a | OK (map assigned before seed) |
| substrate refresh seed + edges | `:441-557` | D4c.2/.4 | **F3** (stale map), **F5** (failure path), **F6** (delete ordering) |
| substrate boot-settle release | `:629-652` + `presence.py:2327-2351` | **no** | **F1** |
| substrate stale-room prune at setup | `:331-333` | no | inert (fresh trackers per presence setup) |
| presence seed `_discover_room_sensors` | `presence.py:3538-3556` | D4c.3 | **F8** (one-shot, fresh trackers) |
| presence live `_on_substrate_kind_changed` | `:3567-3594` | row 10 | OK |
| tracker `update_room_occupancy` | `:841-897` | D4b | OK |
| dead `_handle_occupancy_change` | `:5030-5079` | **no** | **F9** |
| zone tracker create/prune | `:3240-3268`, `:3291-3409` | no | inert (create once; prune drops the whole tracker) |

**Timeouts/decay that relied on the wipe:** confirmed none. The zone tier has no Tier-1 timer. Camera (`_any_camera_occupied`) and BLE are separate. The fan-interference hold is extend-only (`presence.py:705-711`). The WAKING `_first_positive_zone_occupied_since` resets on any False (`:6313-6320`), so D4 reduces false resets. The one *accidental* release the wipe provided, for a stuck or settle-stale kind, is exactly F1.

## Stuck-occupied paths

| Path | After D4 (as planned) | After fixes |
|---|---|---|
| Sensor stuck/frozen `on` | Held while `on`. Room-tier 4 h exclusion is not mirrored (PICK R3-2). α discharges when cameras are live. D4d pages only when Frigate is dark (F7). Wigton/Generic unpaged (stated). | accepted, with F7 text fix |
| Unavailable / unknown | counts off | PASS |
| Entity deleted from HA (`new_state None`) | D4c.1 releases | PASS (gating to be stated, F2) |
| Entity renamed (registry) | old id is removed, so D4c.1 releases it; the new id is untracked by either tier (pre-existing) | PASS for stuck |
| Sensor removed from CONF (options) | refresh reseed and False edge, **only if** the helper uses the desired map (F3) and the subscription succeeds (F5) | PASS after F3/F5 |
| Room deleted | D4c.2, subject to the delete-ordering race (F6) and the settle gate (F1) | PASS after F1/F6 |
| Room renamed | old name released by D4c.2; the new name is never tracked (F11, pre-existing) | card |
| Sensor goes off during boot settle | **stuck True** (F1) | PASS after F1 |

## D1-S deletion safety
- **INV-NIGHT-RAW-EQUALS-RAW** holds by inspection with the limb deleted. In order, `_zone_night_rooms` handles the BLE early return, `not _has_sensors → []` (derived is AWAY or UNKNOWN), `_room_occupied` (which includes the hold), and the camera limb. That mirrors `_derived_mode` (`presence.py:762-782`).
- The forcing-line deletion is safe under that invariant, and R3-F1 (a manual OCCUPIED override fed the WAKING gate) is a real defect on `dad3bf6e7` (`:6271-6276`, read through `t.mode == OCCUPIED` at `:6262`).
- **Safe only when D4 is on.** With the constant False, see F2.

## D-H1 re-anchoring table
- All 6 `dh1_*` drills (`test_house_state_sleep_mask_mutation_drills.py:143-166`) and all 7 named tests (`test_house_state_sleep_mask_ble_memory.py:554-625`, `:1672-1723`) have a disposition. **Complete for the D-H1 set.**
- Gaps:
  - F10 (harness and anchor-file schema);
  - F4 (the existing-suites list misses `test_presence_guest_latch_and_veto_gap.py`, `test_lighting_slice_c_manual_hold.py`, `test_reconcile_on_return.py`, `test_room_substrate_integration.py`, `test_substrate_boot_settle.py`);
  - F1 (`test_boot_settle_replay_unchanged` as specified pins a defect).
- `test_substrate_backcompat.py` pre/post equivalence keeps passing, because both sides route through the D4b tracker. Its global `return_value` cannot exercise siblings, so it gives no D4a evidence.

## Kill-switch byte-identity vs `dad3bf6e7`

| Site | Gated by `ZONE_OCCUPANCY_PER_ENTITY_ENABLED`? (plan) | Byte-identical when False? |
|---|---|---|
| D4a live OR | yes | yes, if F3/F4 are handled |
| seed via shared helper | n/a (same rule) | **no** if the helper reads the stale map (F3) |
| D4b per-kind clear | yes | yes |
| D4c.1 deleted entity | **unstated** | unknown (F2) |
| D4c.2 removed-room edges | **unstated** | unknown (F2) |
| D4c.3 exact reseed | yes | yes |
| D4d trip-wire | no (own bound, default 7200) | **no** (permitted by INV-BYTE-ID-SINGLE, contradicted by R3.7) |
| D1-S limb deletion | **no** | **no, and unsafe** (F2) |
| D1-S forcing-line deletion | **no** | **no** (R3-F1 behaviour change) |

## Invariant checklist
- INV-ZONE-ROOM-TRUTH: **LEAK** (F1; F3/F5 on refresh).
- INV-NO-STUCK-THROUGH-REMOVAL: **LEAK** (F3, F5, F6 latency).
- INV-SLEEP-NOT-EMPTY: PASS with D4 on; **LEAK** with the kill switch off (F2).
- INV-NIGHT-RAW-EQUALS-RAW: PASS.
- INV-SLEEP-HOLD-BOUNDED (b): PASS.
- INV-BYTE-ID-SINGLE: **LEAK** (F2, F8 display, F3).
- INV-NO-EMPTY-HOUSE-HOLD-WHEN-ALPHA-LIVE: PASS. The D4d coverage claim is wrong (F7).

## Must-fix before build
F1, F2, F3 (HIGH). F4, F5, F6 and F7 are MEDIUM. Fix them in the plan text, as they are cheap. F8–F10 go into the plan; F11 becomes a card.
