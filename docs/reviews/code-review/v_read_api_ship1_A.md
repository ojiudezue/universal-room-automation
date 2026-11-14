# Review A: person-awareness read API ship 1 (local correctness, edge cases, byte-identity)

Branch `feature/person-awareness-read-api-ship1` @ 6b3b6891. Diff base = `git merge-base develop HEAD` = 376c1272
(three-dot). Plan: `docs/planning/PLANNING_person_awareness_read_api.md` §5 ship 1. Card PERSON-AWARENESS-READ-API-1.
Presence/identity docs: findings checked against the plan's INV-ID-ONE-RULE and manual §5.5 thresholds; no
corrections-ledger claim is re-asserted.

**Verdict: SHIP.** No CRITICAL/HIGH/MEDIUM. Two LOWs, one informational.

## Byte-identity truth table (old inline vs `slug_of`, run against the real module)

| Input | Old A/D (`replace('person.','').strip().lower()`) | New `slug_of` | Same |
|---|---|---|---|
| `person.oji_udezue` (live options form) | `oji_udezue` | `oji_udezue` | yes |
| ` person.oji_udezue ` | `oji_udezue` | `oji_udezue` | yes |
| `person.Oji` | `oji` | `oji` | yes |
| `Person.oji` / `PERSON.x` | `person.oji` / `person.x` | same | yes |
| `''`, `'  '`, `'person.'`, `None` (D filters falsy) | `''` | `''` | yes |
| `oji` (no space) | `oji` | `oji` | yes |
| `Oji Udezue` (display, data form) | `oji udezue` | `oji_udezue` | no: the intended fix |
| `Ólá Bí` | `ólá bí` | `ólá_bí` | no: same intended fix (space only) |
| `person.a.person.b`, `person.x person.y` | `a.b`, `x y` | `a.person.b`, `x person.y` | no: illegal HA object ids, unreachable |

Live config: `merged = {**entry.data, **entry.options}` so options (entity ids) win; every row that live config
can produce is identical for A, C, D. B (`tracked_person_entity_id(p.strip())`) keeps any `person.*` entry verbatim,
so identical to the old `p.strip()`. C gains `.lower()`; HA entity ids are lowercase, so identical. Divergence is
confined to display-name config, which is the plan's stated fix (INV-ID-ONE-RULE).

Thresholds: perimeter floor `max(table[security]=0.9, PERIMETER_EGRESS_KNOWN_MIN_CONF)` == old `max(0.9, ...)`
(`perimeter_alert.py:5188-5195`; `_const_mod` exists at :80; kill switch `>1.0` still first). Notification compare
reads `table[notification]=0.75` (`transit_validator.py:2683-2687`), same value and `>=`. Table is a
`MappingProxyType`, import-time validator passes for the default sets. Cycle tests: 32 passed.

## Findings

| # | SEV | Where | Finding | Class |
|---|---|---|---|---|
| A-L1 | LOW | `transit_validator.py:2658-2662`, `:2683-2687` | `ARRIVAL_NAME_CONFIDENCE_THRESHOLD` is kept "for existing readers" but the comparison no longer reads it. Grep finds no reader in code or tests, so today it is a dead alias; a future test or subclass that overrides the attribute would silently have no effect. Either compare against `self.ARRIVAL_NAME_CONFIDENCE_THRESHOLD` (still table-sourced) or delete the alias. | #63 two names for one value |
| A-L2 | LOW | `transit_validator.py:2257-2269` | `_record_crossing` runs unguarded between the bus fire and the debug log / arrival notify. All inputs are already used by the bus payload a few lines up (`resolution.provenance`, `egress_timestamp.isoformat()`), so it cannot raise on any reachable path; noting only because a future field added to `CrossingRecord` could break the notify path. Acceptable as is. | none (holds) |
| A-I1 | INFO | `person_coordinator.py:818, 990, 1740` | Pre-existing inline `f"person.{name.lower().replace(' ', '_')}"` copies remain; for a `person.*` entry they would produce `person.person.*`. Out of ship 1 scope (plan RA9, ship 2); INV-ID-ONE-RULE is therefore true for the four residuals only, as the README says. Keep on RA9. | #53 one-missed-site (deferred, tracked) |

## Cleared

- **Re-export** (`person_coordinator.py:130-138`): `tracked_person_entity_id` is the same object (test asserts `is`);
  the only other importer, `presence.py:5275` (lazy import from `person_coordinator`), still resolves. Body is
  byte-identical to the removed one. No test monkeypatches `person_coordinator.tracked_person_entity_id`, so the
  census importing from `person_ids` directly loses no patch seam.
- **`get_house_census`** (`presence.py:5952-5982`): reads `census.last_result` (a property, `camera_census.py:1958`)
  `.house` (`CensusZoneResult`, fields `identified_count`, `unidentified_count`, `total_persons`,
  `source_agreement`, `timestamp` all exist at :314-324). None census / result / house -> None; any `int()` failure
  is caught -> None. Frozen dataclass fields match the plan plus `view`.
- **`view_for_class`** (`presence.py:5984-6008`): non-str, unpromoted, illegal, switch missing or not `on`, any
  error -> `trust`. With default `{display}` and no switch entity, every class reads trust.
- **`get_last_crossing`**: tracker key `egress_tracker` matches `__init__.py:3473` / `const.DIRECTION_TRACKER_DATA_KEY`;
  try/except on both layers. `CrossingRecord` fields carry the same values as the bus fire (`confidence` = crossing
  confidence, `identity_confidence`, provenance None when no person). RAM only, no entity or log change.
- **Plan-drift claims (README)**: `CrossingRecord` adds `identity_confidence` beyond the plan's field list (additive,
  harmless); `canonical_person_slug` public wrapper added as plan says; awareness view returns trust values with
  provenance `camera` as the plan specifies. Verified.

## Summary

| Severity | Found | Must fix |
|---|---|---|
| CRITICAL | 0 | 0 |
| HIGH | 0 | 0 |
| MEDIUM | 0 | 0 |
| LOW | 2 | 0 (A-L1 recommended in-cycle) |
| INFO | 1 | 0 |

Bug classes: #63 (1), #53 deferred (1). No new class for QUALITY_CONTEXT.md.
