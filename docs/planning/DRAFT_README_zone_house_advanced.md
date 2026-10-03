# DRAFT README — Zone and House dialogs: Simple / Advanced (slice B)

**Cards:** ZONE-DIALOGS-CLEANUP-1 (D2) + HOUSE-DIALOGS-CLEANUP-1 (D4), tests in D6.
**Plan:** `docs/planning/PLANNING_zone_house_dialog_cleanup.md` (slice B; slice A = D1/D3/D5 shipped earlier).
**Tier:** 2 (options-flow UI only; no runtime behaviour change).
**Branch:** `feature/zone-house-advanced` (from develop).

## What changed

The Zone Manager and House option forms now hide rarely-used tuning fields unless
HA's profile **Advanced mode** is on. A form with hidden fields shows a hint line
that explains how to reveal them. This reuses the room mechanism (`_adv`,
`_filter_advanced`, `advanced_hint_for`). Nothing new was invented.

| Form | Hidden in Simple mode |
|---|---|
| Zone > Name and rooms | Description (no runtime reader) |
| Zone > Zone Media | If speaker is off (fallback mode) |
| Zone > Thermostat | AC power sensor, AC overrun fix |
| Zone > Zone Energy | Power sensors (no runtime reader) |
| Zone > Weather comfort | No offset with guests, Separate sleep ranges |
| House > Global Sensors | Dark outside below, Backup power price |
| House > Energy Sensors | Device power sensors (no runtime reader) |
| House > Person Tracking | Keep history, Room change wait (no runtime reader) |
| House > Camera Census | Cross-check, Trust the lower count, Smarter counting, Only trust live faces, Phones excuse unknown people, Turn on person detection, Indoor/Outdoor hold |
| House > Perimeter Alerting | AI service, Cameras to describe, AI model, Max reply length, AI provider ID, Snapshot delay |

The Camera Census form drops from 15 fields to 7 in Simple mode: the three camera
pickers, Face recognition, Name people at doors, Known guests and Guest Wi-Fi name.
The fields are now in this order: pickers, then switches, then the guest list and
SSID, then the Advanced tuning. Only the order changed. No key was renamed or moved.

### Invariants
- **I2: nothing stored is unreachable.** A hidden field still shows in Simple mode
  when its stored value differs from the factory default (for lists and text, when
  it is non-empty). This includes the five dead fields (operator decision O1: they
  show in Advanced mode, or when set).
- **I3: Simple saves keep hidden values.** House saves merge into the stored
  options (`{**options, **user_input}`). Zone saves merge into the zone dict, and
  the sibling mirror only copies keys that were on the form. A zone that shares a
  thermostat therefore keeps its own hidden values.
  `zone_rooms` now falls back to the stored description, where it used to write
  `""`, when the field is not submitted (ZM and legacy branches).
- **Reload safety.** A Simple-mode Camera Census or Perimeter save that changes one
  allowlisted key only changes that key, so it stays inside
  `INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS` and does not reload. An entry that
  still holds the 4 retired `perimeter_alert_*` keys reloads once on its first
  perimeter save, because the pop removes them. This is pre-existing and accepted
  (plan review finding 3).

### Shared-helper fix found in build
`_schema_has_advanced` and `_collect_schema_defaults` recursed forever on any
`vol.All` field. After schema compilation, `vol.All.schema` points back at the
parent schema. The weather-comfort form was the first Advanced-marked form with a
`vol.All` field (the offset). Both walkers now treat that back-reference as a leaf.
A regression test is included and was drill-verified.

### Not changed
- `MIRROR_KEYS_ZONE_*`: a test asserts they are unchanged.
- The reload allowlist and `_auto_mirror_to_siblings`.
- Constants. The five dead keys got one-line KEEP+DOCUMENT comments in `const.py`.
- Accepted LOW (plan review 6): a Simple-mode zone save no longer re-mirrors hidden
  keys to siblings, so it no longer heals drift between siblings.

## Tests
`quality/tests/test_zone_house_advanced_fields.py` (79 tests): classification per
key, I2 forced render per key (including entry.data and the legacy zone entry), I3
per step (zone + sibling + House), the Camera Census count and order, hint
placeholders, mirror-set identity, reload safety through the real
`_async_update_listener`, and the walker back-reference.

Mutation drills (source rewritten, then restored with hash verified):
zone helper merge→overwrite (4 fail), zone_rooms description fallback→"" (1 fail),
camera_census merge→user_input (2 fail), `_adv` never unmarks (28 fail),
census_hold_interior forced-render site (1 fail), back-reference guard removed (7 fail).

## Live validation (prospective; fill in post-restart)
- [ ] Profile Advanced mode OFF → Zone > Thermostat shows only the thermostat picker + hint.
- [ ] Advanced mode ON → all three Thermostat fields show; the hint says "Advanced settings shown."
- [ ] Advanced mode OFF → House > Camera Census shows 7 fields + hint.
- [ ] A House with a non-default `census_hold_interior` still shows it in Simple mode.
- [ ] Simple-mode Camera Census save that only edits Known guests: log shows
      "in-place apply, suppressing reload", not "scheduling reload".
- [ ] Weather comfort form opens without error (exercises the vol.All fix).
