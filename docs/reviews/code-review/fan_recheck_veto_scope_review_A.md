# Review A (local correctness) — fix/fan-recheck-still-risk-veto-scope

Diff: `git diff b716228e9..9ee216981` (merge-base verified = b716228e9). Presence STATE_OF_PLAY fan-recheck section read.

## Findings
- **LOW (Bug Class #63 concept split, documentation)** `presence_fan_recheck.py:1322-1355` `_l1_persons` is NEW semantics, not reuse. The room-level `ble_persons` path (`coordinator.py:4071`) calls `get_persons_in_room` -> `get_room_occupants` (`person_coordinator.py:1554`, exact match on resolved location). Resolution (`person_coordinator.py:1063-1070`) gives Tier-1 direct area match precedence over Tier-2 `_scanner_to_rooms`, so a Bermuda area `jaya_bathroom` resolves to room "Jaya Bathroom" (which exists, area `jaya_bathroom`) and does NOT appear in Jaya Bedroom's `ble_persons`. The recheck L1 is now broader than the room's own `ble_persons`. That matches operator intent; no room-level helper exists to reuse. Note the divergence in STATE_OF_PLAY so nobody "aligns" it back.
- **LOW (info)** Every room with `scanner_areas` naming another URA room's area picks up that room's persons as L1 (live: Exercise Room <- Exercise Room Closet, Exercise Room Closet <- Exercise Room, Kitchen Hallway <- kitchen/butler_pantry rooms if they exist, Living Room <- dining_room/entry_way rooms, Garage Hallway/Laundry Closet <- laundry). The direction is conservative (more vetoes, so the fan stays on), which matches the operator's "including scanner-area rooms" wording.
- **LOW (test-only)** `_l1_persons` uses `getattr(person_coord, "_area_id_to_room", None) or {}`. When person_coord is a bare MagicMock, that returns a truthy mock, `.get` returns a mock room, and spurious L1 becomes possible if the test sets scanner_areas. Production holds because the attr is always a dict (`person_coordinator.py:118,960`).

## Cleared
- Area normalization: map is keyed by area_id, area name and normalized name (`person_coordinator.py:992-994`); helper tries raw then normalized. Holds.
- None/empty/str scanner_areas: `or []`, str wrapped as a list, falsy entries skipped. Holds.
- Own-area in scanner_areas (Laundry Closet `laundry_closet`, Study B `study_b`): resolves to self and is skipped via `seen={room_name}`. Holds.
- Unmapped area (`balcony`, no URA room): `area_map.get` returns None and is skipped. Balcony phones already resolve to Ziri Bedroom via Tier-2 `_scanner_to_rooms`, so plain `get_persons_in_room` covers it. Holds; operator config treated as ground truth.
- Cross-zone scanner room: no zone filter. Correct per intent (the scope is BLE in the room).
- Live/inert parity: a single `_evaluate_eligibility` serves `_LiveSink` and the inert sink (`:133,155,492,510`). The L1 site uses `sink.set_ladder_layer`/`sink.veto` with no bare mutation. Holds.
- L1 consumers: both fan-recheck sites (`:675` eligibility, `:1136` mid-flight cancel) were converted. `presence.py:4623` is the separate presence-level helper and outside scope.
- Sleep predicate twins `:572` and `:1213` are identical (`HIGH_STILL_RISK_ROOM_TYPES`). Both `high_still_risk` veto sites were deleted; no remaining code emits it.
- Stale refs: code and tests only mention it in comments or not-in assertions. **LOW** `.claude/skills/ura-presence-reliability-campaign/SKILL.md:356,365,378` still describes the `high_still_risk` guard as live; update it. `README_v5.23.0.md:36` is historical, leave it.
- Tests: the two cycle files pass 115/115. Fan-family 812 pass / 7 fail, and the identical 7 fail at base b716228e9 (pre-existing).

## Verdict: SHIP (LOWs: update the SKILL.md stale guard text; note the L1-vs-ble_persons divergence in STATE_OF_PLAY).
