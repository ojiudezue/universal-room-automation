# v5.103.103 — Zone orphan-device cleanup no longer deletes devices that still have entities

Card: ZONE-ORPHAN-DEVICE-REMOVE-GUARD-1. Also: `docs/architecture/DEVICE_TREE.md` now says `via_device` is deprecated and removed in Core 2027.8 (the 2026.9 RuntimeError we hit stays as observed fact).

## Problem
Two startup cleanups in `__init__.py` delete URA zone devices whose `zone_*` identifier is missing from a zone-name set computed on the spot:
- the integration-entry orphan sweep (v3.5.3), and
- the Zone Manager slug sweep (v3.6.0-c2.1).

If that set comes out incomplete for a moment (load order, a config read error, a zone entry not loaded yet), the sweep deleted a live zone device. That also threw away its entities' registry customizations (names, icons, areas, disabled flags).

## Fix
Both sweeps now call one helper, `_remove_orphan_zone_devices`. It reuses the guard from the D1 music-following cleanup: before removing a device it checks `er.async_entries_for_device(..., include_disabled_entities=True)`. The device is removed only when no entities remain. Otherwise the helper logs `Orphaned <label> removal SKIPPED for <id> — device still has N entities` and moves on. `zone_manager` is never removed. Identifiers are still read without tuple-unpacking, so 3-tuple identifiers don't break the loop. Each device gets one decision, so it can't be removed twice.

Tier 1. No config, schema or entity changes.

## Tests
`quality/tests/test_zone_orphan_device_guard.py`:
- `test_zone_device_with_entity_survives_missing_id`
- `test_empty_zone_device_with_missing_id_is_removed`
- `test_disabled_only_entity_counts_as_present`
- `test_zone_manager_never_removed`
- `test_active_zone_not_removed_even_if_empty`
- `test_three_tuple_identifiers_do_not_crash`
- `test_device_with_two_orphan_ids_removed_once`

## Validated 2026-11-06 (restart 14:55 CT)
| Criterion | Result | Evidence |
|---|---|---|
| No zone device with entities removed | PASS | Core log after restart: 0 `Removed orphaned` lines, 0 `orphan` lines |
| All zone devices present with entities | PASS | Template over `integration_entities`: Back Hallway 21, Entertainment 21, Master Suite 21, Outside 19, Upstairs 21 |
