# v5.103.17 — Renaming a room can no longer create a duplicate room name

**Card:** `ROOM-NAME-UNIQUE-1` · Tier 1 (autonomous; 2 framing-disjoint reviews + orchestrator gates)

## Problem
Creating a room rejected a name another room already had, but renaming a room in its options did not check at all. Two rooms with the same name collapse every name-keyed map in URA (zone room lists, titles, entity slugs). The create path also had two smaller gaps: a room created while another room was renamed to the same name in parallel could still end up duplicated, and names were stored with any stray leading/trailing spaces.

## Fix (`config_flow.py`, strings)
- One helper, `_room_name_collides`, used by both create and rename: case-insensitive, trimmed, excluding the room being renamed (renaming to your own name or changing its capitalisation is allowed).
- Rename (options → basic setup): a colliding name re-shows the form with "A room with this name already exists"; nothing is written and no reload happens.
- Blank / whitespace-only name shows "name required" on both create and rename.
- Names are stored trimmed on both paths.
- The create path re-checks the name immediately before creating the entry, closing the race with an in-parallel rename.
- The error strings now exist for the options screen too (previously only the create screen had them), with a test that fails if any error the rename step can raise has no translation.

## Review ledger
Build `8d0a855c1` → review A (correctness) FIX-REQUIRED: missing `options.error` string (MEDIUM) + 2 LOWs; review B (lifecycle) FIX-REQUIRED: same MEDIUM; rejection writes nothing / no reload / zone sync skipped; accept path byte-identical; no other rename surface; pre-existing create race (LOW) → fix-up `eebe92784` (all fixed, 6 drills RED). Gates: full name-diff 0 NEW + isolated run of 66 config-flow test files 0 NEW.

## Live Validation (prospective — written back post-restart)
- **Verify:** all 43 room entries still load; zero URA ERROR after restart.
- **Verify (discriminating, operator-assisted or skipped):** renaming a room to another room's name in its options shows "A room with this name already exists" and `.storage/core.config_entries` `modified_at` for that entry does not change; renaming to a free name saves.
- **In-suite only:** the create/rename race re-check (needs two concurrent flows).

## Rollback
Revert the merge. No schema or entity changes.
