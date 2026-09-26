# v5.103.17 — URA stops mistaking its own thermostat nudges for a person (ends ~22 self-lockouts/week) + renaming a room can no longer create a duplicate name

**Cards:** `HVAC-ARRESTER-NUDGE-ECHO-FALSE-OVERRIDE-1` (operator-approved simplest fix; 2 reviews) · `ROOM-NAME-UNIQUE-1` (Tier 1; 2 reviews)

## Part 1 — HVAC-ARRESTER-NUDGE-ECHO-FALSE-OVERRIDE-1

### Problem
After URA nudges a thermostat's setpoint, Carrier echoes the change back 5.3–7.5 s later. The arrester ignored changes for only 5 s after a URA temperature write, so the echo was booked as a PERSON's override: 24 of 52 `override_detected` rows since 2026-09-19 (zone_1 17, zone_2 5, zone_3 2). Each one set off a chain (review B, reconstructed from DB + recorder): a medium "HVAC Override" NM alert → 5-min grace → a compromise raw setpoint write at +300 s (which Carrier turns into a real manual hold) → `preset_change_locked_out` at +591–597 s (22 of 22) → revert at +600 s.

### Fix
`SUPPRESS_TTL_SECONDS` 5 → 15 s (`hvac_override.py:133`, rung-1 constant; 2× the worst measured echo). The 120 s preset-kind window is unchanged. Also covers 3 compromise echoes and 1 pre-cool echo (~28 of ~35 URA self-caused false overrides). Added blind time for a genuine human is ~0.3–2.5 s per URA temperature write (after the echo lands, a human touch is manual→manual and was never booked); named-preset changes were never overrides either way.

### Expected effect per week
~22 fewer self-lockouts, ~24 fewer false override NM alerts, ~48 fewer Carrier writes; `override_count_today` and the efficiency score stop counting URA's own echoes. Nudge-effectiveness evaluation (at +355 s) now measures the real restored state rather than a compromise setpoint, so its "effective" rate may shift — expected, not a defect.

### Not fixed (→ W1-B problem 1, value-matched last-write record)
Post-restore zero-delta manual strands (8 rows incl. the long §9.1 strands), restore echoes booked under the preset window, late echoes (32 s, 42 s).

### Review ledger
Build `1ca21dddb` (+ tidy-ups `950148b3d`). Review A (all consumers of the constant) SHIP; review B (does it end the lockouts) SHIP-WITH-RESIDUAL. Gates: full name-diff 0 NEW + isolated run of 42 arrester test files 0 NEW.

## Part 2 — ROOM-NAME-UNIQUE-1

### Problem
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
- **Verify (echo, discriminating):** after restart, 0 `override_detected` rows within 15 s after a `nudge_started` on the same zone; 0 `preset_change_locked_out` at ~+595 s after a nudge; nudges still start and restore (`ac_ramp_events`).
- **Verify (echo, human path intact):** a genuine manual change (operator's controlled test, when done) is still booked `override_detected`.
- **Verify:** all 43 room entries still load; zero URA ERROR after restart.
- **Verify (discriminating, operator-assisted or skipped):** renaming a room to another room's name in its options shows "A room with this name already exists" and `.storage/core.config_entries` `modified_at` for that entry does not change; renaming to a free name saves.
- **In-suite only:** the create/rename race re-check (needs two concurrent flows).

## Rollback
Revert the merge. No schema or entity changes.
