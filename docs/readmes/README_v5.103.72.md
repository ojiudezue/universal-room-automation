# v5.103.72: house state — sleep mask, BLE memory, per-sensor zone tracker, observability

Cards: HOUSE-STATE-AWAY-FLAP-UNTRACKED-OCCUPANT-1 (the approved small cycle; Rev 4 camera guard + guest-room veto stay PARKED), ZONE-TRACKER-PER-SENSOR-WIPE-1 (D-H1).

Plan: `docs/planning/PLANNING_house_state_sleep_mask_ble_memory_observability.md` (Rev 3.2).

**Tier 3.**
- 2 plan reviews, 4 framing-disjoint build reviews, then a re-review of the fixes.
- Reviews are in `docs/reviews/code-review/house_state_sleep_mask_review_{A..D}.md` and `house_state_rev32_review_{A..D}.md`.
- Operator checkpoint: GO 2026-10-18.

**Deploy risk: MEDIUM-HIGH.** House-state inference feeds HVAC presets and lighting.

## Falsifiable invariant

The house never goes AWAY while a zone room holds live, Tier-1, per-sensor occupancy (outside the existing α path, which needs every tracked phone and BLE away). One sensor's off-edge never clears a sibling sensor's live hold in the same room.

## Problem → solution

- **SLEEP masked the zones (D1).**
  - Sleep pins the zone trackers via `set_sleep`, which hid `any_zone_occupied` from the nobody-home branch.
  - The nobody-home branch now reads the raw substrate zone input, so a sleeper's live sensor holds the house home.
  - Bounded by `SLEEP_RAW_HOLD_NM_BOUND_S=5400` (measured after the sleep window ends).
  - D1b: a wake discharge releases the hold.
- **A briefly STALE phone counted as away (D2).** STALE now counts as home within `CONF_PERSON_DECAY_TIMEOUT`. A forgotten phone is still handled by `phone_left_behind`; D2 only affects STALE.
- **The away path was hard to see (D3).** New attributes `last_away_branch` (nobody_home / α / β), `away_entries_today` and `guest_reason`. They are shown in the Presence Diagnostics section on the v8 People view.
- **One sensor cleared the whole room (D4, D-H1).**
  - `_room_provenance` was keyed per kind, so one sensor's off-edge wiped a sibling's live hold. This was confirmed live in audit P6.
  - Now there is a per-entity substrate `_kind_on_now`, and the off-edge pops only its own kind.
  - A boot-settle `_reconcile_trackers_to_substrate` writes only to the room's owner tracker. In a room in two zones, the other zone's tracker is never written.
  - Refresh seeds a scratch copy, then swaps. `async_remove_entry` dispatches "removed".
- **Trip-wire (D4d).**
  - An NM page if a zone holds for over `ZONE_HOLD_ALL_AWAY_NM_BOUND_S=7200` while every tracked person is away and α is blocked only by dark cameras.
  - **D4d is silent when the away-veto switch is off.**
  - The stuck-signal alert counts only occupied zones.
- **Kill switch:** `ZONE_OCCUPANCY_PER_ENTITY_ENABLED` (module constant, read as an attribute in exactly 3 modules, enforced by a lint).
  - Off means today's behaviour exactly: no boot reconcile, no refresh seed, no removal dispatch.
  - On skips the old night workaround.

## Tests

- **Full name-diff at 671d334e7 vs a0cd40412:** CLEAN, 0 NEW / 0 GONE. 69 failing, all pre-existing; 17398 → 17529 passed.
- **Full suite with `--per-entity-off`:** CLEAN, 0 NEW / 0 GONE (switch-off identity).
- **Mutation drills:** `test_house_state_sleep_mask_mutation_drills.py`, 111/111 RED-on-mutation, in plain and reverse order.
- **Orchestrator mutation:** the multi-zone owner guard (`presence.py`, `tracker_for_room(...) is not tracker`) mutated to `if False:` turned `test_reconcile_multi_zone_room_only_owner_written` RED. Restored.

## Not covered / follow-ups

- Guest or no-phone occupant: Rev 4, parked.
- ZONE-ROOM-NAME-DRIFT-1 (priority). A sleeper in a renamed room can be AWAYed until a restart, with the switch on.
- WIGTON-STUCK-ZX-NO-PAGE-1.
- HVAC-CONSENSUS-GATE-PIN-1, pulled out of this cycle.

## Live validation (to be replaced by a Validated table)

- Installed: manifest v5.103.72; all URA entries `loaded`; no URA ERRORs.
- `sensor.ura_presence_coordinator_presence_house_state` carries `last_away_branch`, `away_entries_today` and `guest_reason`.
- No zone tracker stuck occupied after the boot reconcile. Zone modes match the substrate.
- House state is correct for the actual occupancy at restart.
