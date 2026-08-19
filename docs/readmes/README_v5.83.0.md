# URA v5.83.0 — Guest/unidentified counts stop using the naive `camera − ble` subtraction

Part of the census/identity program's post-ship cleanup (found by the domain-wide supersession
sweep, card `GUEST-COUNT-DEDUP-MIGRATE-1`). Kills the last surviving instances of the exact
additive/subtractive divergence behind the historical GUEST double-count.

## The problem this closes

**Three** enabled/registered sensors computed a "how many unknown people" figure the *naive* way —
`max(0, camera_total − ble_something)` — which double-counts a resident the cameras saw but whose
phone/face wasn't matched. The census already produces the *deduped* answer
(`house.unidentified_count` = `camera_total − |face_ids ∪ ble_ids|`, `camera_census.py:1899`), but
these three surfaced their own parallel subtraction, so an operator could see two different integers
for the same quantity.

## What shipped

All three sites now read the deduped `census.last_result.house.unidentified_count`:
- `aggregation.py` `ZoneGuestCountSensor._get_guest_count` (disabled-by-default, per-zone)
- `binary_sensor.py` `URAUnexpectedPersonSensor` `guest_count` **attribute** (enabled-by-default)
- `sensor.py` `UnidentifiedPersonsSensor.native_value` (`sensor.universal_room_automation_unidentified_persons`,
  enabled-by-default) — the third site, found by Review B (the plan/plan-review/build had verified
  the invariant with a *token* grep on `guest_count`; this site uses `ble_identified`/`Unidentified*`
  and slipped it).

**Root-cause hardening:** the invariant is now enforced by a **shape-invariant test**
(`test_shape_invariant_no_naive_camera_minus_ble_count`) that scans every component `.py` (blanking
docstrings/comments, excluding the canonical producer) and fails CI if the `max(0, camera_total −
<ble>)` count pattern reappears at any production site. Token grep → shape grep is what would have
caught the third site up front.

**Not touched:** `URAUnexpectedPersonSensor.is_on` (`camera_total > ble_total`, a boolean alarm, not
a count) — it's a different question (BLE-coverage alarm ≠ resident-vs-guest classification) and is
carded separately as `UNEXPECTED-PERSON-IS-ON-DEDUP-MIGRATE-1`.

## Semantics (verified in Review A)

A real guest (no BLE, no face-match) still flows to `unidentified_count` — not under-counted. The
case the old formula got *wrong* (a resident with a dead phone but a face match, miscounted as a
guest) is now correctly excluded. That's the whole point.

## Attribute-surface note

`sensor.universal_room_automation_unidentified_persons` **retired its `ble_identified` attribute
key** (verified zero live consumers across dashboards/scripts/automations) and added
`identified_count` + `unidentified_count`. `ZoneGuestCountSensor` likewise (disabled-by-default).
`URAUnexpectedPersonSensor`'s scrape keys (`camera_total`/`ble_total`) are preserved.

## Non-goals / knobs

No new knobs, consts, signals, DB, or config-flow fields. Pure producer swap.

## Review

Tier 2-DB: plan → plan review → build → 3 framing-disjoint reviews (A SHIP / B DO-NOT-SHIP found the
3rd site / C SHIP) → H1 fix-up (migrate site #3 + shape invariant) → re-review SHIP. 18 tests,
mutation-drilled (revert any site → the behavioral + shape-invariant tests fail).

## Acceptance criteria — live

- **L1:** boot clean, zero URA ERROR; the three sensors read the same deduped figure the presence
  coordinator already uses (no cross-surface divergence).
- **Live (Wed occupancy):** with a real guest present, `unidentified_persons` / `guest_count` reflect
  the deduped count; a resident with a dead phone but face-matched is NOT counted as a guest.

## Live Validation

### Validated 2026-08-18 (~15:5x CT, post-restart) — house EMPTY

| # | Criterion | Result | Evidence |
|---|---|---|---|
| L1 | Boot clean, zero URA ERROR | **PASS** | system_log ERROR count 0; `sensor.ura_presence_coordinator_presence_house_state` = `away` (available) |
| Live | deduped guest/unidentified counts; dead-phone-face-matched resident not counted as guest | **ORGANIC-PENDING** | needs occupancy (Wed) |

**Boot-clean now; occupancy discrimination organic on Wed.**
