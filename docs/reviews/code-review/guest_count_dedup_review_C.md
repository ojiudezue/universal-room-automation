# GUEST-COUNT-DEDUP-MIGRATE-1 — Review C (Surfaces + Test Authority)

**Framing:** Tier 2-DB Review C — new/changed surfaces and behavioral test authority.
**Worktree:** `.claude/worktrees/guest-count-dedup` at commit `d010122bd`.
**Base:** `develop`.
**Files in scope:** `aggregation.py` (ZoneGuestCountSensor), `binary_sensor.py`
(URAUnexpectedPersonSensor), `quality/tests/test_guest_count_dedup_migrate.py`.

## Verdict

**SHIP** — with a README write-back note re: `ZoneGuestCountSensor`
attribute-key change (C-LOW-1).

**Test-authority one-liner:** The 13 tests are **real, not structural.** The
census fixture drives the production `PersonCensus._apply_enhanced_house_census`
writer end-to-end (verified by tracing the shim stubs: `_get_unrecognized_camera_count`
+ `_last_camera_total_pre_cancel` produce `camera_total=6`; `ble_persons=["p0".."p5"]`
enters the real `identified_count = |normalize_name_set(...)|` reducer; the real
ceiling-clamp arithmetic (`camera_census.py:3713-3716`) produces
`unidentified_count=0`). The discriminating scenario would return `4` under the
pre-migration naive form and returns `0` post-migration — an actual behavioral
discriminator, not a source-string tautology. Grep-anchor tests exist but are
**supplemental** to the behavioral discriminator, not the sole coverage
(satisfies hollow-anchors rule).

**Mutation-authority drill (executed):** Reverted
`ZoneGuestCountSensor._get_guest_count` to the naive form
`max(0, camera_total - ble_total)`, ran the cycle file with `PYTHONDONTWRITEBYTECODE=1`,
observed **4 failures / 9 passes** — including the discriminating behavioral
tests `test_zone_guest_count_reads_deduped_unidentified` and
`test_zone_guest_count_attrs_share_house_snapshot` (not only the grep anchors).
Restored source; worktree clean. The migrated site is genuinely load-bearing on
this test.

## Findings

### C-LOW-1 — `ZoneGuestCountSensor` attribute key-set changed (scrape contract)

**Class:** Attribute-surface change (removed key).
**File:** `custom_components/universal_room_automation/aggregation.py:5977-5985`.

The pre-migration attribute set was `{camera_total, ble_total, zone, confidence}`;
the post-migration set is `{camera_total, identified_count, unidentified_count,
zone, confidence}`. **`ble_total` was removed** and replaced by two new keys
sourced from the same house snapshot as the state. This is a *breaking* attribute
shape change for any dashboard/automation reading
`state_attr('sensor.<zone>_guest_count', 'ble_total')`.

Blast radius is minimal because `_attr_entity_registry_enabled_default = False`
(line 5941) — the entity is disabled by default and there is no evidence in the
worktree of it being enabled. The docstring documents the change explicitly.
The build's own reasoning ("state and attributes now derive from ONE snapshot
so they cannot silently disagree") is sound.

**Recommendation:** SHIP as-is. Add one line to `README_v<version>.md` under
"Attribute shape changes": *"`sensor.house_guest_count` attribute keys: removed
`ble_total` (was a second BLE derivation); added `identified_count` +
`unidentified_count` (both sourced from `census.last_result.house`). Entity is
disabled-by-default; no known consumers."*

### C-INFO-1 — `URAUnexpectedPersonSensor.is_on` remains a second derivation of the same signal

**Class:** Known deferred gap (documented, carded).
**File:** `binary_sensor.py:1540-1560`.

The D2 migration deduped `extra_state_attributes["guest_count"]` but
**intentionally left `is_on` untouched.** `is_on` still fires on
`camera_total > ble_active_count` — the exact naive-comparison form D2 removed
from the attribute. The cycle now supports a legitimate "attrs.guest_count == 0
while is_on == True" divergence, which the test
`test_unexpected_person_is_on_still_uses_camera_gt_ble` explicitly asserts
(lines 326-339 of the test file).

The build documents this in the sensor docstring and cards it separately as
`UNEXPECTED-PERSON-IS-ON-DEDUP-MIGRATE-1`. This is acceptable scope-management
under Marginal-Benefit Decomposition — the is_on migration touches a
trust-hierarchy site (safety/security preset triggers) and merits its own
Tier 2-DB cycle. **No action for this review.** Verify the follow-up card
exists on the kanban before closing this program.

### Positive verifications

- **Test fixture is real, not stubbed at the boundary.** `_build_house_result`
  monkeypatches only the two inputs the writer would call (camera-count producer
  + hold/decay) and lets the identified-set union, ceiling clamp, and
  unidentified subtraction run in production code (`camera_census.py:3663-3716`).
  This is the correct authority level for a value being migrated: prove the
  reader consumes the same shape the writer produces, not just the same field
  name.
- **Discriminating-observation rule satisfied.** State and attrs on
  `ZoneGuestCountSensor` are now sourced from a single `house` snapshot; the
  test `test_zone_guest_count_attrs_share_house_snapshot` asserts
  `attrs["unidentified_count"] == sensor.native_value` — the observation that
  would fail if a future refactor split the derivation again.
- **`URAUnexpectedPersonSensor` scrape contract preserved.** The attribute
  key-set (`camera_total`, `ble_total`, `guest_count`) is unchanged — pinned by
  `test_unexpected_person_attr_keys_unchanged`. Only the `guest_count` *value*
  now sources from the deduped field. Zero risk to existing scrapers on this
  sensor.
- **Graceful-degradation paths preserved.** Both sensors return 0/zeros when
  census is absent or `last_result is None`, exercised by dedicated tests.
- **RestoreEntity / registration unchanged.** No inheritance shift on either
  class; `_attr_entity_registry_enabled_default` on `ZoneGuestCountSensor` is
  still `False` (no accidental enable-flip).
- **Mutation-verify pyc-staleness rule followed** — cycle test suite green
  with `PYTHONDONTWRITEBYTECODE=1` (no stale bytecode masking).

## Summary table

| Finding    | Severity | Fixed pre-ship? | Notes |
|------------|----------|-----------------|-------|
| C-LOW-1    | LOW      | No — SHIP-with-note | Add README write-back line; disabled-by-default limits blast radius |
| C-INFO-1   | INFO     | Deferred by design  | Follow-up card `UNEXPECTED-PERSON-IS-ON-DEDUP-MIGRATE-1`; verify exists |

## Bug-class table

| Class                                       | Count |
|---------------------------------------------|-------|
| Attribute-surface change (removed key)      | 1 (LOW) |
| Known deferred second-derivation (carded)   | 1 (INFO) |

No new bug classes to add to `docs/QUALITY_CONTEXT.md`.

## Test authority verdict (spelled out)

- 13 tests total; 10 behavioral (drive real sensor properties against a
  real-writer census fixture), 3 grep/anchor (supplemental).
- Discriminator (`test_zone_guest_count_reads_deduped_unidentified`,
  `test_unexpected_person_attr_guest_count_reads_dedup`) fails on
  naive-form revert — confirmed by executed mutation drill (4 failed /
  9 passed on revert; restored; clean).
- No fixture hand-sets the field-under-test — the production writer produces
  it.
- Anchor tests do not stand in for behavioral coverage; they are additional
  regression fences against a future refactor re-introducing the naive form.

**Test suite for this cycle is authority-graded.**
