# Review — ZONE-ORPHAN-DEVICE-REMOVE-GUARD-1 (Tier 1, framing A: local correctness + device-registry safety)

Branch `fix/zone-orphan-device-guard` @ 8b0eaa41; base develop 9e74f6be (merge-base verified = 9e74f6be; three-dot diff).
Read DEVICE_TREE.md / DEVICE_ENTITY_DEFRAG_POSTMORTEM.md context for registry work.

## Findings
| Sev | Site | Finding | Class |
|---|---|---|---|
| — | `__init__.py:2446-2452` | Site 1 predicate `ident[5:].lower() not in active_zone_names` == old (set already lowercased). Holds. | — |
| — | `__init__.py:4954-4960` | Site 2 predicate `ident not in raw_zone_ids` == old, case-sensitive as before; `zone_manager` exclusion preserved. Holds. | — |
| LOW (behaviour change, safe) | `__init__.py:2261-2263` | Helper now also excludes `zone_manager` and non-str identifiers at site 1. Old site 1 would have deleted a `zone_manager` device under the integration entry unless a zone was literally named "manager" — the new exclusion is strictly safer. | — |
| LOW (accepted trade-off) | `__init__.py:2266-2279` | A genuinely orphaned zone device that still carries stale entity-registry rows (zone removed from ZM options; entities stay registered under the ZM entry) is now kept indefinitely and logs one INFO "SKIPPED" line per boot per such device. Nothing else auto-cleans it; operator removes manually. Accepted: deleting a live device wipes entity customisations (irreversible) vs. a cosmetic leftover (reversible). Log volume = O(stale devices) INFO/boot, bounded. | — |
| — | multi-entry / via_device | `async_remove_device` semantics unchanged vs old code (removes device across entries). Guard only reduces removals. via_device children are not entities, so a parent zone device with no entities but children would still be removed — same as before; zone devices are leaves (`_devices.py:208` zone_* -> zone_manager parent). Holds. | — |
| LOW | tests | Wire-in anchor gap (#62-adjacent): tests drive only the helper; reverting either call site to inline code stays green. Not must-fix for Tier 1: call sites are 6-line delegations verified by reading. Smallest behavioural anchor (follow-up): drive the ZM-entry slug-sweep branch of `async_setup_entry` with a fake registry holding a populated zone_X device absent from `zones` and assert it survives. | Wire-in anchor |

## Mutation drill
Neutered guard `if not remaining:` -> `if True:` (`__init__.py:2270`), PYTHONDONTWRITEBYTECODE=1, __pycache__ cleared:
RED — `test_zone_device_with_entity_survives_missing_id`, `test_disabled_only_entity_counts_as_present` (2 failed / 5 passed). Restored: 7 passed; `git status` clean.

## Verdict: SHIP
No CRITICAL/HIGH/MEDIUM. Optional follow-up: call-site anchor above.
