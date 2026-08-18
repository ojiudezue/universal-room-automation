# Review A — Correctness + Migration Equivalence

Cycle: `GUEST-COUNT-DEDUP-MIGRATE-1` (feature/guest-count-dedup, commit d010122bd)
Framing: A — semantic equivalence, edge cases, attr/state coherence, graceful degradation
Reviewer role: Tier 2-DB Review A (parallel with B and C)
Date: 2026-08-18

## Verdict: **SHIP**

Two naive `max(0, camera_total - ble_total)` guest-count derivations are
migrated onto the canonical deduped `house.unidentified_count`. The migration
is correct, semantic under-count risk was checked and rejected, graceful
degradation returns the safe sentinel, the retained diagnostic attributes on
`URAUnexpectedPersonSensor` still compute correctly, and the `is_on`
divergence is intentional and carded separately. No CRITICAL / HIGH.

---

## Producer check (per operator's 2026-08-16 rule)

`house.unidentified_count` is produced by two writers, both in
`camera_census.py`:

- `_cross_correlate_persons` at `:1899` — `max(0, camera_total - identified_count)`
- `_apply_enhanced_house_census` at `:3716` — the enhanced-census path that
  wins when enabled: `clamped_unidentified = max(0, clamped_total - identified_count)`,
  where `identified_count = |ble_persons ∪ face_recognized ∪ egress_face_ids|`
  (union of three identity substrates, correctly deduped) and `clamped_total`
  is bounded by `max(camera_total_pre_cancel, identified_count)` so additive
  growth cannot inflate guest count.

Both writers guarantee `unidentified_count >= 0` and typed `int`
(`CensusZoneResult` dataclass field at `:151`). The new reader therefore does
not need its own `max(0, …)` guard, and no negative or `None` value can
reach either migrated site under a legal producer path.

## Semantic equivalence — does the new formula UNDER-count real guests?

Constructed the four resident/guest categorisations against both formulas:

| Scenario | Old `max(0, cam − ble_active)` | New `house.unidentified_count` |
|---|---|---|
| Real guest (camera-seen, no BLE, no face) | Counted (correct) | Counted via `camera_unrecognized` → `held_unidentified` → clamped remainder (**correct**) |
| Resident with BLE-active phone, on camera | Cancelled by BLE-active count (correct) | Cancelled via `ble_persons ⊆ recognized_set` (**correct**) |
| Resident face-matched, BLE OFF (phone dead / left behind) | **Counted as guest (wrong — old bug)** | In `recognized_set` via `face_recognized`; NOT in `unidentified` (**correct — this is the whole point of the cycle**) |
| Two-phone resident (both BLE-active) | Over-subtracted → real guests hidden | Set-union dedupes to one identity → guests preserved (**correct**) |

**Under-count check for a real guest**: a real guest with no BLE and no face
match ends up in `camera_unrecognized` (post BLE-cancel), passes through
`_apply_hold_decay`, survives the `min(additive_total, raw_total_ceiling)`
clamp because `identified_count` did not grow, and appears in
`clamped_unidentified`. **No under-count regression.** The only path that
could hide a real guest is a spurious BLE-identity match against them —
which is a pre-existing property of `_get_unrecognized_camera_count`'s
BLE-cancel step, not introduced by this diff.

## Findings

### A-LOW-1 — Attribute-key rename on `ZoneGuestCountSensor` is a silent scrape-shape break (LOW)
File: `aggregation.py:5959-5992`
Bug class: Attribute-shape drift (external-scraper compatibility) — akin to
QUALITY_CONTEXT `#12`-adjacent (payload-shape change).
Situation: `ble_total` attribute is removed; `identified_count` and
`unidentified_count` are added. Any pre-existing dashboard template /
external scraper reading `attributes.ble_total` on this sensor silently
resolves to `None` post-deploy.
Mitigating facts (why this is LOW, not MEDIUM):
- Sensor is `entity_registry_enabled_default = False` (line 5940 in-diff
  context — disabled by default).
- Plan §Non-Goals note (2026-08-18 touch-up) explicitly documents this and
  asserts no known operator scrape.
- Sibling `URAUnexpectedPersonSensor.extra_state_attributes` keys are
  intentionally preserved (D2 keeps `camera_total` / `ble_total` /
  `guest_count`) — the scrape-shape contract is upheld on the enabled sensor.
Recommendation: none required. If a reviewer wants zero risk, add the
old `ble_total` key as an alias (person-coordinator BLE-active count) —
but this is optional and the plan has already priced the change.

### A-LOW-2 — Boundary reads of `census.last_result` are not snapshot-locked across `native_value` + `extra_state_attributes` (LOW / informational)
File: `aggregation.py:5975` and `5990-5994` (state read) vs
`aggregation.py:5959-5972` (attribute read)
Bug class: Read tearing across HA property invocations (mild variant of
QUALITY_CONTEXT `#7` — stale/inconsistent data source).
Situation: The migrated docstring claims state and attributes "cannot
silently disagree (discriminating-observation rule)". Within a single
property call this holds — each property reads `census.last_result.house`
once. Across the two properties (HA invokes `native_value` and
`extra_state_attributes` in separate calls), a `PersonCensus` refresh could
swap `last_result` between them, producing a one-tick disagreement.
Mitigating facts:
- The window is one census refresh cadence and self-corrects on the next
  update.
- No trust decision consumes this pairing (display-only diagnostic).
- Pre-existing HA pattern; every URA sensor with independent property reads
  has the same property. The old code had the same risk plus a second
  cross-substrate tear (person_coordinator vs census).
Recommendation: soften the docstring wording ("read from ONE snapshot per
property invocation") or, if truly zero-tearing is wanted, cache
`(camera_total, identified, unidentified, confidence)` from one shared
snapshot on `native_value` and have `extra_state_attributes` reuse it.
Not required for ship.

### A-LOW-3 — `is_on` vs `guest_count` attribute intentionally disagree, but co-exist in the same entity payload (LOW / documented)
File: `binary_sensor.py:1540-1560` (unchanged `is_on`) vs `1584-1600`
(migrated attrs)
Bug class: Signal-derivation asymmetry (operator interpretation risk).
Situation: A dashboard user can now see `binary_sensor.ura_unexpected_person`
`on` with `attributes.guest_count = 0` at the same instant (both the fixture
`test_unexpected_person_is_on_still_uses_camera_gt_ble` and my hand-checked
scenario `camera=6, identified=6 (all face-matched), ble_active=2` produce
exactly this). The `is_on` = `camera_total > ble_total` branch is untouched
and still consults person_coordinator's raw BLE-active count.
Mitigating facts:
- Plan §5 / §9 explicitly document the split and card the sibling migration
  as `UNEXPECTED-PERSON-IS-ON-DEDUP-MIGRATE-1`.
- Fixture asserts this on-purpose.
Recommendation: ship as planned; ensure the sibling card lands before any
dashboard change that would surface the disagreement to end users.

### A-LOW-4 — `.house` accessed unguarded when `last_result` is truthy (LOW / no regression)
File: `binary_sensor.py:1584-1588` (no try/except); `aggregation.py:5985-5994`
(wrapped in the outer `try/except Exception` on `_get_guest_count` only for
the state path, not the attribute path).
Bug class: Missing-None guard on nested optional (QUALITY_CONTEXT
`#13`-adjacent — None handling).
Situation: If `census.last_result` is a snapshot whose `.house` is `None` /
missing, `.house.total_persons` / `.house.unidentified_count` raises
`AttributeError`. In `binary_sensor.py` this is unwrapped and would poison
the attribute read.
Mitigating facts:
- Not a regression: pre-cycle code already accessed
  `census.last_result.house.total_persons` on the same path with no guard.
- `_apply_enhanced_house_census` / `_cross_correlate_persons` always return
  a full `CensusZoneResult` for the `house` zone (checked writer paths); no
  code path constructs a `last_result` with `.house = None`.
Recommendation: none required. If ever tightened, guard should live in
`PersonCensus.last_result` construction, not in every consumer.

## Attribute correctness spot-checks (Framing A checklist items)

- **`ZoneGuestCountSensor` attrs share the house snapshot** — confirmed at
  `aggregation.py:5975-5985`; all four fields (`camera_total`,
  `identified_count`, `unidentified_count`, `confidence`) read from the
  same `house` local (`house = census.last_result.house`). ✓
- **Retained `ble_total` on `URAUnexpectedPersonSensor.extra_state_attributes`**
  — still computed via person_coordinator active count (lines 1594-1598),
  identical to pre-cycle derivation. No dead code, no exception when
  person_coordinator absent (guarded). ✓
- **census-absent graceful path returns 0** — both migrated sites hit the
  `if not census or census.last_result is None: return 0` / equivalent
  guard. 0 is the correct sentinel for "guest count unknown" (pre-existing
  semantics preserved). Persistent-None-hazard: only during boot before the
  first census refresh; self-corrects on first tick. Not a stuck-at-0
  concern beyond boot transient. ✓
- **Type safety** — `unidentified_count: int` on `CensusZoneResult`
  (`camera_census.py:151`); no float / None reachable via producer paths. ✓
- **Negative guard removed on the reader is safe** — producer clamps at
  `:1899` and `:3716`; `unidentified_count >= 0` by construction. ✓

## Non-findings (Framing A checked and cleared)

- **Consumer disagreement** — greped `git grep -n "unidentified_count"` on
  the worktree; the two migrated sites plus a `sensor.py` display sensor
  are the only consumers, and the display sensor already read
  `house.unidentified_count` pre-cycle. No third derivation exists post-diff.
- **Signal / dispatch chain** — this cycle adds no signals, no dispatches,
  no DB rows. Nothing to trace end-to-end.
- **RestoreEntity impact** — neither migrated site restores this attribute;
  both re-derive on every property read.

## Ship gate

- CRITICAL: 0
- HIGH: 0
- MEDIUM: 0
- LOW: 4 (three documented / not-required-for-ship; one recommends a
  docstring softening)

**Framing A verdict: SHIP.** The dedup migration is semantically correct,
does not under-count real guests, does not tear state/attr readouts within a
property call, and preserves the on-cycle scrape-shape contract on the
enabled sensor. Cross-check with Reviewers B and C before final ship.
