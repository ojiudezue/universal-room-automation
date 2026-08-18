# Plan Review — GUEST-COUNT-DEDUP-MIGRATE-1 (Tier 2-DB pre-build)

**Date:** 2026-08-18
**Reviewed doc:** `docs/planning/PLANNING_guest_count_dedup_migrate.md`
**Framing:** adversarial single-pass plan review; verify with greps not
trust; scope = plan-quality gate before builder dispatch.
**Verdict:** **PLAN-READY (with 1 MEDIUM clarification recommended, 2 LOWs).**
None are BLOCKING; the plan may proceed to build.

---

## 1. Independent verification of the plan's load-bearing facts

### 1.1 `ZoneGuestCountSensor` live-status — CONFIRMED
- `custom_components/universal_room_automation/aggregation.py:388` under
  `async_setup_zone_sensors` (`ENTRY_TYPE_ZONE` path) — instantiated per zone.
- `custom_components/universal_room_automation/aggregation.py:464` under
  `async_setup_zone_manager_sensors` (`ENTRY_TYPE_ZONE_MANAGER` — the current
  path) — instantiated once per configured zone inside the loop over
  `zones_data`.
- Class-level `_attr_entity_registry_enabled_default = False` at
  `aggregation.py:5934` — disabled-by-default confirmed.
- Unique-id shape `f"{DOMAIN}_zone_{zone}_{SENSOR_ZONE_GUEST_COUNT}"` at
  `:5942`; const `SENSOR_ZONE_GUEST_COUNT = "zone_guest_count"` at
  `const.py:2075` — plan's `sensor.ura_{zone_slug}_guest_count` claim
  matches.
- Plan §0 accurate.

### 1.2 Zero-consumer claim — CONFIRMED for both target sites
Grep `git grep -n "guest_count" custom_components/` returned only:

- Writers on the target sites: `aggregation.py:5944, :5954, :5983` (the
  ZoneGuestCountSensor internals) and `binary_sensor.py:1584` (the target
  attribute).
- Unrelated `_get_wifi_guest_count` producers inside
  `camera_census.py:3377-3542, :3648` — these produce a *floor input*
  consumed by the census fuse itself, not consumers of either target.
- Unrelated `guest_count` in `sensor.py:13125` and
  `domain_coordinators/security.py:2208` — the authorized-guest snapshot
  from the sanction/security path (different domain).
- `const.py:2075` (the const), and one comment in `transit_validator.py:1315`
  citing `_get_guest_count`.

Grep `git grep -n "ura_.*_guest_count\|zone_guest_count\|SENSOR_ZONE_GUEST_COUNT" custom_components/`
returned only the definition and registration sites already listed.

**Independent enumeration → zero code readers of either target** (no
automation trigger via `state_attr(...,'guest_count')`, no coordinator read,
no trust decision, no NM template inside `custom_components/`). Plan §1.4 /
§3.1 / §3.2 claim upheld. Tier 2-DB (not Tier 3) is defensible on the
producer/consumer axis.

Caveat (LOW L1, non-blocking): the grep only covers `custom_components/`,
`quality/tests/`, and `docs/`. HA `.storage/` blueprints, user-authored
automations, and the operator's dashboard YAML are NOT in the repo and
therefore not grep-verifiable pre-build. Plan §8 already acknowledges this
("even though grep-verified there are zero code consumers, operator-visible
dashboards and NM templates may consume the attributes"), and Review B in
§8 defers this to live-validation. Acceptable; noted for completeness.

### 1.3 Producer-swap correctness — CONFIRMED, with a semantic-parity
nuance the plan should call out explicitly (see M1 below)

- `CensusZoneResult.unidentified_count` field defined at
  `camera_census.py:151` — a house-level union-complement (deduped
  face+BLE identified subtracted from `camera_total`).
- Raw producer `_cross_correlate_persons` at `camera_census.py:1899`:
  `unidentified_count = max(0, camera_total - identified_count)` where
  `identified_count = len(face_ids ∪ ble_ids)` (canonicalized when egress
  face path enabled at `:1885-1889`). This is exactly the dedup the naive
  `camera_total − ble_active_count` was missing.
- Enhanced producer path at `:3733, :3776` — default-ON since v3.10.1;
  applies hold/decay stabilization on top.

Semantic replacement is directionally correct: `house.unidentified_count`
is the intended, deduped answer to the same question the naive
subtraction was asking.

### 1.4 Zone-vs-house granularity — pre-existing quirk, NOT introduced
here (documented, MEDIUM finding M1)

`ZoneGuestCountSensor` is registered **per zone** but its old and new
derivations both read `census.last_result.house.*` (a house-level scalar).
Old: `house.total_persons - ble_active_total`. New: `house.unidentified_count`.
Under both, EVERY registered zone entity emits the SAME house-level value —
if an operator enables `sensor.ura_kitchen_guest_count`,
`sensor.ura_living_room_guest_count`, etc., they will all read the same
number. Plan §1 acknowledges this ("`PLANNING_v3.5.2_CYCLE_4.5.md` — 'what
shipped instead' — confirms the house-level nature of the values fed into
the 'zone' sensor (a known compromise from that cycle, not the concern of
this migration)").

**Verdict:** pre-existing, out of scope, non-blocking. But see M1 — the D1
"Live" acceptance criterion should reference the house-level census
directly (which it does), and the plan should note in §5 (non-goals) that
"this migration does NOT resolve the pre-existing per-zone-entity /
house-level-value granularity mismatch." That framing avoids a future
reviewer claiming the migration introduced the quirk.

### 1.5 `URAUnexpectedPersonSensor.is_on` vs attribute — INDEPENDENT,
plan is correct to park

Read `binary_sensor.py:1540-1585`:

- `is_on` (`:1540-1560`) reads `census` + `person_coordinator` freshly and
  writes `self._camera_total` / `self._ble_total` instance state as a
  side-effect. Returns `self._camera_total > self._ble_total`.
- `extra_state_attributes` (`:1562-1585`) ALSO reads `census` +
  `person_coordinator` freshly (does NOT read `self._camera_total` /
  `self._ble_total` instance state). Returns
  `{"camera_total": ..., "ble_total": ..., "guest_count": max(0, camera_total - ble_total)}`.

The two properties share NO helper. Swapping the `guest_count` value in
`extra_state_attributes` does NOT alter `is_on` behavior. The instance-
attribute assignment inside `is_on` is not read by the attribute property,
so migrating the attribute cannot leak into the is_on comparison.

Plan §3.2 / §4 D4 / §9 correctly park `is_on` and correctly identify the
migration as safely decoupled. **Confirmed.**

### 1.6 Discriminating test — genuinely discriminates
Plan D1 fixture: `house.total_persons=6, identified_count=6,
unidentified_count=0`; BLE `active=2`. Old code: `max(0, 6 − 2) = 4`. New
code: `0`. Divergence 4→0. Test PASSES only on the migrated code. ✔
D3 mandates the fixture be produced by the real
`_cross_correlate_persons` / `_apply_enhanced_house_census` writer, per
`feedback_hollow_test_anchors.md`. ✔

### 1.7 Falsifiable invariant I-GC — well-formed
Named, restated in §6, falsifiable by (a) grep for the forbidden
expression on any live-reachable path, (b) a divergence scenario. Meets
the Tier 2-DB (and Tier 3, if elevated) invariant bar.

### 1.8 Institutional-context §1 — complete
Audit doc cited (`AUDIT_census_identity_supersession_and_consumers.md`),
origin design docs cited, memory bodies cited, canonical field anchors
cited (file:line). Complies with CLAUDE.md "Institutional context first."

---

## 2. Findings

### M1 (MEDIUM, non-blocking — clarify in plan §5) — Explicitly non-goal the pre-existing per-zone-entity vs house-level-value granularity

The migration inherits the "every zone entity emits the same house-level
number" quirk that has existed since v3.5.1. §1 mentions it in passing but
§5 (non-goals) does not enumerate it. Add one bullet under §5:

> - **NOT** resolving the pre-existing per-zone-entity vs house-level-value
>   granularity mismatch on `ZoneGuestCountSensor` (both the old naive
>   formula and the new deduped formula read `house.*` — every enabled
>   zone entity emits the same house-level integer; a per-zone guest count
>   is a separate deliverable that would require a per-zone census cut).

This makes it impossible for a future reviewer to attribute the quirk to
this cycle and keeps the invariant I-GC surgically scoped to derivation
correctness, not per-zone semantics.

### L1 (LOW, non-blocking — already flagged by plan §8) — Off-repo consumers

`.storage/` blueprints, user-authored automations, and dashboard YAML are
not repo-grep-verifiable pre-build. Plan already defers to live-validation
in §8 and to the operator's "snapshot before deploy" step in §10. No plan
change required; noted for the reviewer trail.

### L2 (LOW, non-blocking — plan D1 attribute change) — State/attr key-set change on `ZoneGuestCountSensor`

Plan D1 replaces the attribute `ble_total` with `identified_count` (state
and attributes share one snapshot of `house`). This is a **key-set change
on the attribute dict** of `ZoneGuestCountSensor.extra_state_attributes`.
The sibling D2 explicitly preserves the `URAUnexpectedPersonSensor`
attribute keys as `{camera_total, ble_total, guest_count}` for dashboard/
scrape compatibility (D2 acceptance criterion
`test_unexpected_person_attr_keys_unchanged`).

The asymmetry is intentional and defensible — `ZoneGuestCountSensor` is
disabled-by-default (so has no established dashboard scrapes to preserve),
whereas `URAUnexpectedPersonSensor` is enabled-by-default. But the plan
should state the asymmetry explicitly in D1 (one line):

> Note (attribute key-set change): `ZoneGuestCountSensor` is
> disabled-by-default and has no known operator scrapes of its attributes;
> replacing `ble_total` with `identified_count` is intentional (state/attr
> consistency > scrape-shape preservation) and does not violate the
> `URAUnexpectedPersonSensor` scrape-preservation contract, which is
> separately upheld by D2's `test_unexpected_person_attr_keys_unchanged`.

Non-blocking; a builder can add this line during implementation without
re-review.

---

## 3. Verdict

**PLAN-READY.** The plan is grep-anchored, semantically correct on the
producer swap, correctly scoped away from the entangled-looking-but-
actually-independent `is_on`, and Tier 2-DB is the right tier (three
framing-disjoint reviews + live validation + README write-back). Dispatch
to builder.

- Independent consumer enumeration: **zero code consumers of either
  target site** in `custom_components/`. Off-repo (`.storage/`,
  dashboards) deferred to live-validation, consistent with plan §8.
- Zone-vs-house granularity verdict: **pre-existing quirk, not
  introduced by this cycle, out of scope**. Recommend M1 (one-line
  addition to §5 non-goals) to keep the record clean.
- `is_on`/`attr` entanglement verdict: **independent**. Each property
  reads census + person_coordinator freshly; no shared helper; migrating
  the attribute cannot alter `is_on`. Parking `is_on` under
  `UNEXPECTED-PERSON-IS-ON-DEDUP-MIGRATE-1` is correct.
- Findings: 0 CRITICAL, 0 HIGH, 1 MEDIUM (M1 — clarifying non-goal),
  2 LOW (L1 acknowledged, L2 asymmetry-note). None blocking.

Recommend the builder incorporate M1 and L2 as plan text touch-ups during
implementation (single-line each), and proceed.
