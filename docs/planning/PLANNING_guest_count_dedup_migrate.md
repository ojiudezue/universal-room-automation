# PLANNING: Guest-count dedup migration (`ZoneGuestCountSensor` + sibling attr)

**Card:** `GUEST-COUNT-DEDUP-MIGRATE-1`
**Date:** 2026-08-18
**Tier:** 2-DB (three framing-disjoint reviews + live validation + README write-back)
**Author:** oji@productmind.co

---

## 0. TL;DR / gating verdict

**`ZoneGuestCountSensor` IS a LIVE registered entity** — registered twice in the
zone platform-setup paths:

- `aggregation.py:388` under `async_setup_zone_sensors` (per-zone
  `ENTRY_TYPE_ZONE` entries), and
- `aggregation.py:464` under `async_setup_zone_manager_sensors`
  (`ENTRY_TYPE_ZONE_MANAGER`, the current path — one entity per configured zone
  under the Zone Manager device).

Per the class body (`aggregation.py:5926-6008`) the unique-id key is
`{DOMAIN}_zone_{zone}_{SENSOR_ZONE_GUEST_COUNT}` and the const value is
`"zone_guest_count"` (`const.py:2075`), yielding entity ids of the shape
`sensor.ura_{zone_slug}_guest_count`, one per zone. They ship
**disabled-by-default** (comment tag "disabled by default" at `aggregation.py:386`
and `:462`) — so the entity is *dormant* on stock installs but the class is
wired, registered, and one flip in the entity registry makes it live. The
NAIVE-SUBTRACTIVE arithmetic at `_get_guest_count` (`aggregation.py:5983-6001`)
is therefore a **live-capable** derivation, and the S4 sibling attribute at
`binary_sensor.py:1584` sits on `URAUnexpectedPersonSensor` — an
**enabled-by-default** integration-level binary sensor
(`binary_sensor.py:1510-1585`, registered at `binary_sensor.py:112`), so THAT
attribute is unconditionally live today. Migration proceeds.

The card is NOT moot. The `ZoneGuestCountSensor` half is a latent trip-hazard
(one registry flip); the `URAUnexpectedPersonSensor.guest_count` attribute is a
live second derivation of the same quantity that the audit fingered as an S4
back-door for the double-count class.

---

## 1. Institutional context verified

### 1.1 Prior planning / audit consulted (full read or targeted)

- `docs/planning/AUDIT_census_identity_supersession_and_consumers.md` — full
  read of §2 & §3 & the supersession table (lines 47, 239, 250, 322): both
  sites are already tagged there as `A2` and `A3 · S4 sibling` with the
  explicit recommendation "**KEEP+WIRE** to census `unidentified_count`". This
  cycle executes the A2/A3 recommendation.
- `docs/PLANNING_v3.5.1_CYCLE_4_SLIM.md` (:124-179, :244, :307) — the CYCLE_4
  design that introduced `ZoneGuestCountSensor` and the naive
  `camera_total − ble_total` formula. Origin doc for the arithmetic being
  replaced.
- `docs/PLANNING_v3.5.1_CYCLE_4.md` (:256-288, :734) — sibling doc for the same
  build.
- `docs/PLANNING_v3.5.2_CYCLE_4.5.md` (:85, :104) — "what shipped instead" —
  confirms the *house-level* nature of the values fed into the "zone" sensor
  (a known compromise from that cycle, not the concern of this migration).
- `docs/PLANNING_v3.5.2_CYCLE_6.md` (:660) — historical note that the
  house-level unidentified sensor was declared non-redundant with
  `ZoneGuestCountSensor`; this migration collapses that historical divergence
  the right way (both sides consume the same deduped source).
- `docs/PLANNING_v3.10.1_CENSUS_V2.md` (:349) — introduces
  `_apply_enhanced_house_census`, the deduped writer we migrate onto.
- `docs/planning/PLANNING_paper_and_oss_fusion_library.md` — skimmed for scope
  boundary; no overlap.
- `docs/readmes/README_v5.79.0.md`, `README_v5.81.0.md` — recent census
  cycles; confirm `unidentified_count` on
  `sensor.universal_room_automation_census_persons_in_house` /
  `..._census_unidentified_persons_in_house` is the canonical deduped surface.
- Memory bodies pulled (relevance): `feedback_cross_investigation_synthesis.md`
  ("acceptance criteria must DISCRIMINATE fix from new-failure — the census
  double-count missed exactly this"), `feedback_falsify_before_asserting.md`,
  `feedback_wire_in_anchor_mandatory.md`, `feedback_hollow_test_anchors.md`,
  `feedback_suppression_needs_discharge.md` — shape the invariant + test
  authority + anchor requirements below.

### 1.2 Coordinator design docs read

- `docs/Coordinator/PRESENCE_COORDINATOR.md` (:1085-1091) — the raw
  (`_cross_correlate_persons`) vs enhanced (`_apply_enhanced_house_census`)
  producer paths; the enhanced path is default-ON since v3.10.1 and stabilizes
  `unidentified_count`. Both write into `census.last_result.house.unidentified_count`.
- `docs/Coordinator/ZONE_MANUAL.md` (:121) — declares
  `SENSOR_ZONE_GUEST_COUNT` on the zone entity contract.

### 1.3 Greps run (REUSED / NEW ledger)

No new `CONF_*`, no new sensor, no new const, no new signal is added by this
cycle. It is a **pure PRODUCER swap on two existing consumers**.

| Proposed | REUSED / NEW | Anchor |
|---|---|---|
| Deduped source read | REUSED — `census.last_result.house.unidentified_count` | `camera_census.py:151` (dataclass field), `camera_census.py:1899`, `:1927` (raw producer), `camera_census.py:3733`, `:3776` (enhanced producer), surfaced on `sensor.py:3483`, `:3633`, `:3702` |
| Read helper on the sensor | REUSED — same `self.hass.data.get(DOMAIN, {}).get("census")` pattern already used at `aggregation.py:5959, :5986` and `binary_sensor.py:1542, :1566` | in-file |
| `SENSOR_ZONE_GUEST_COUNT` constant | REUSED unchanged — `const.py:2075` | — |
| Registration | REUSED — `aggregation.py:388, :464` untouched | — |
| Any knob (see §7) | none | — |

`git grep -n "guest_count"` under `custom_components/` returned exactly these
two production write-sites plus `camera_census._get_wifi_guest_count` (a
different concept — Wi-Fi client heuristic used inside enhanced census, not a
consumer of either target), and one unrelated `security` snapshot `guest_count`
(authorized-guest list length in `sensor.py:13125` /
`domain_coordinators/security.py:2208` — a different domain, not touched).

### 1.4 Consumer surface for the two target sites (see §3 for detail)

`grep -rn 'sensor\..*_guest_count'` and
`grep -rn 'ura_.*_guest_count'` across the repo returned **zero** code
consumers of either target (no automations, no trust decisions, no coordinator
reads). Both surfaces are **display / dashboard only**. This is a
foundational input to the tier decision (§8) and to the risk framing (both
sites are safe to swap; the migration hazard is *silent divergence*, not
runtime break).

---

## 2. Problem statement (single falsifiable invariant)

**Invariant I-GC (falsifiable):** *For every code path in
`custom_components/universal_room_automation/` that surfaces a "guest count"
number — including the `ZoneGuestCountSensor.native_value`, the
`ZoneGuestCountSensor.extra_state_attributes`, and the
`URAUnexpectedPersonSensor.extra_state_attributes["guest_count"]` — the value
MUST equal the canonical deduped `census.last_result.house.unidentified_count`
(or the same graceful-degradation sentinel when the census is unavailable) and
MUST NOT be computed by any second/subtractive/additive derivation from
`total_persons`, BLE active-count, or any other proxy. In particular, the
expression `max(0, camera_total - ble_total)` MUST NOT appear as a live
producer of any surfaced guest-count value on any reachable path.*

The invariant is falsifiable by: (a) a repo grep for the forbidden expression
returning non-test hits, (b) a scenario in which the deduped
`unidentified_count` and the naive subtraction diverge and one of the surfaced
values matches the naive answer.

---

## 3. PRODUCER + CONSUMER checks (mandatory, per the 2026-08-16 rule)

### 3.1 Target site A2 — `ZoneGuestCountSensor._get_guest_count`

**PRODUCER (today, `aggregation.py:5983-6001`):**
```
camera_total = census.last_result.house.total_persons        # :5992
ble_total    = len(persons where tracking_status == "active")  # :5994-5999
return max(0, camera_total - ble_total)                       # :6001
```
Two inputs: (1) `house.total_persons` (a *post-fuse* number produced by
`_cross_correlate_persons` or `_apply_enhanced_house_census`) and
(2) `person_coordinator.data[*].tracking_status == "active"` (BLE substrate,
completely separate signal path from the census identity fuse). These two
numerators/denominators are **not from the same fusion** — that is the whole
double-count trap. `total_persons` is `max(camera_total, identified_count)`
(`camera_census.py:1900, :1928`); subtracting a *separately-derived* BLE
active-count from it can, and does, produce phantom guests (documented in
`docs/reviews/code-review/egress_face_identity_review_B.md:43` — the exact
"phantom guest = 1" reproduction).

The `extra_state_attributes` (`aggregation.py:5957-5981`) EXPOSE
`camera_total` and `ble_total` — they do *not* re-emit `guest_count` (the state
is the guest count). Attributes are diagnostic; state is the derivation.

**PRODUCER (post-migration):**
```
census = hass.data.get(DOMAIN, {}).get("census")
if not census or census.last_result is None:
    return 0                    # unchanged sentinel semantics
return census.last_result.house.unidentified_count
```
Same graceful-degradation contract (return 0 when census unavailable) so no
availability regression. Deletes the read of `person_coordinator` from this
site entirely (dependency reduction — one less null-check surface, and it
removes the second-fuse subtraction). The attribute block ALSO drops the
`ble_total` read and instead exposes `identified_count` +
`unidentified_count` from the same `house` record, so state and attributes
share one source (satisfies the "acceptance criteria must discriminate"
memory: state and attrs cannot silently disagree).

**CONSUMERS (grep-verified):** none in code. Zero automations, zero
coordinators, zero trust decisions read `sensor.ura_*_guest_count`. It is a
**display sensor** (dashboard tile), disabled by default. Trust-decision:
**no**. Display: **yes**. This is why the migration is safe on the read side —
no downstream sees the state, so a shape change (state semantics: still an
int ≥ 0) cannot propagate a bug.

### 3.2 Target site A3/S4 — `URAUnexpectedPersonSensor.extra_state_attributes["guest_count"]`

**PRODUCER (today, `binary_sensor.py:1562-1585`):**
```
camera_total = census.last_result.house.total_persons          # :1573
ble_total    = len(persons where tracking_status == "active")  # :1576-1579
return {..., "guest_count": max(0, camera_total - ble_total)}  # :1584
```
Same naive expression as A2. This is on `URAUnexpectedPersonSensor` which is
`_attr_entity_registry_enabled_default = True` (inherited default; the class
does not opt out and is registered unconditionally at
`binary_sensor.py:112`) — so this second derivation is live on every install
today.

Note also that the same class's `is_on` (`binary_sensor.py:1540-1560`) uses
`camera_total > ble_total` — a *comparison* of the same two quantities rather
than a subtraction. Per card scope this cycle touches ONLY the
`guest_count` attribute and the `ZoneGuestCountSensor` state; the `is_on`
comparison is an **adjacent finding** (§9) not in scope, because changing it
changes a `binary_sensor` state and its own consumers deserve their own
producer/consumer pass. Documented as follow-up card, not swept.

**PRODUCER (post-migration):**
```
census = hass.data.get(DOMAIN, {}).get("census")
if not (census and census.last_result):
    return {"camera_total": 0, "ble_total": 0, "guest_count": 0}
house = census.last_result.house
return {
    "camera_total": house.total_persons,
    "ble_total": <unchanged BLE active read, KEPT for diagnostic parity>,
    "guest_count": house.unidentified_count,
}
```
The `camera_total` / `ble_total` diagnostic attrs are RETAINED unchanged
because they are the observability handle operators use to understand
divergence between the two substrates (deleting them would break existing
dashboards / notification templates that scrape them). Only the
`guest_count` value swaps producer.

**CONSUMERS (grep-verified):** zero in code. No coordinator, no automation,
no template sensor reads `state_attr('binary_sensor...unexpected_person_detected', 'guest_count')`.
Display / operator-tooling only. Trust-decision: **no**. Display: **yes**.

### 3.3 Canonical deduped source health check

`camera_census.py` computes `unidentified_count` at:

- Raw path: `:1862, :1899, :1927` inside `_cross_correlate_persons`, gated by
  `camera_total > 0` — clamps to 0 when no camera signal.
- Enhanced path (default-ON): `:3733, :3776` inside
  `_apply_enhanced_house_census`, applies hold/decay stabilization
  (per `docs/Coordinator/PRESENCE_COORDINATOR.md:1091`).

Both paths write the same field on the same `CensusZoneResult` dataclass
(`camera_census.py:151`). Downstream, the field is already read by:

- `sensor.py:3483` — `URAPersonsInHouseSensor.extra_state_attributes["unidentified_count"]`
  (attribute on the house census sensor — enabled by default).
- `sensor.py:3633` — `URAUnidentifiedPersonsInHouseSensor.native_value` —
  the canonical dedicated entity for this quantity.
- `sensor.py:3702` — `unidentified_total` composed with the exterior
  census.

So the deduped source is (a) canonical, (b) already surfaced as a first-class
sensor, and (c) already trusted by the census-facing observability layer.
Migration adds *two more consumers of an already-load-bearing field* — no new
production of state, no new dispatch, no new persistence.

---

## 4. Deliverables

### D1: Migrate `ZoneGuestCountSensor._get_guest_count` to deduped source

**Change:** `aggregation.py:5983-6001` — replace subtractive body with a read
of `census.last_result.house.unidentified_count`; keep the try/except and the
"census unavailable → 0" contract.

**Change:** `aggregation.py:5957-5981` (`extra_state_attributes`) — replace
`ble_total` (BLE active-count computed independently of the census) with
`identified_count` from the same `house` record; keep `camera_total`,
`confidence`, `zone`. Rationale: state and attributes now derive from ONE
snapshot of `house`, so they cannot disagree (discriminating-observation rule).

Delete the local read of `person_coordinator` in this class entirely.

Note (attribute key-set change, plan-review L2 touch-up 2026-08-18):
`ZoneGuestCountSensor` is disabled-by-default and has no known operator
scrapes of its attributes; replacing `ble_total` with `identified_count`
(and adding `unidentified_count`) is intentional (state/attr consistency
> scrape-shape preservation) and does not violate the
`URAUnexpectedPersonSensor` scrape-preservation contract, which is
separately upheld by D2's `test_unexpected_person_attr_keys_unchanged`.

**Acceptance criteria:**
- **Verify:** `git grep -n "camera_total - ble_total" custom_components/universal_room_automation/aggregation.py` returns **no live-code hits** (comments/tests permitted only in the migration test file).
- **Verify:** `git grep -n "person_coordinator" custom_components/universal_room_automation/aggregation.py` shows the reference removed from `ZoneGuestCountSensor` scope.
- **Test:** new unit `test_zone_guest_count_reads_deduped_unidentified` — construct census with `house.total_persons=6`, `house.identified_count=6`, `house.unidentified_count=0`, `person_coordinator.data` with only 2 "active" (so naive would have said `6−2=4`); assert `native_value == 0`. This test **discriminates**: it FAILS under the old subtractive code and PASSES under the migrated code.
- **Test:** graceful-degradation `test_zone_guest_count_none_census_returns_zero` (census absent OR `last_result is None`) → `native_value == 0`.
- **Test:** mutation-anchor `test_migrated_body_calls_house_unidentified_count` — a per-site source-mutation test (per `feedback_hollow_test_anchors.md`): temporarily reads `aggregation.py`, asserts the substring `house.unidentified_count` appears inside `_get_guest_count`; the CI harness's `feedback_mutation_verification_pycache_staleness.md` rules apply (bytecode disabled, cache cleared) so a stale `.pyc` cannot falsely pass. This anchor exists so a future refactor that re-introduces subtraction is caught by the suite.
- **Live:** entity `sensor.ura_<zone_slug>_guest_count` (enable via UI on ONE zone during live validation) — its state equals `state_attr('sensor.universal_room_automation_census_persons_in_house','unidentified_count')` at read time (allowing for the natural micro-race of independent property reads; a discriminating divergence would be a *sustained* difference, not a one-tick skew).

### D2: Migrate `URAUnexpectedPersonSensor.extra_state_attributes["guest_count"]` to deduped source

**Change:** `binary_sensor.py:1562-1585` — swap the `guest_count` value from
`max(0, camera_total - ble_total)` to `house.unidentified_count`; keep
`camera_total` and `ble_total` attribute keys unchanged (dashboard/scrape
compatibility). The `is_on` at `:1540-1560` is UNCHANGED (adjacent finding,
§9).

**Acceptance criteria:**
- **Verify:** `git grep -n "camera_total - ble_total" custom_components/universal_room_automation/binary_sensor.py` returns no hits.
- **Test:** new unit `test_unexpected_person_attr_guest_count_reads_dedup` — same discriminating scenario as D1 but reading the binary-sensor attribute; assert `attrs["guest_count"] == 0` where the old code returned 4.
- **Test:** attribute-shape preservation `test_unexpected_person_attr_keys_unchanged` — the set of attribute keys is exactly `{"camera_total","ble_total","guest_count"}` (dashboard scrape shape is a public contract; adding/removing keys is a shape change).
- **Live:** on the enabled-by-default `binary_sensor.universal_room_automation_unexpected_person_detected`, `state_attr(...,'guest_count')` equals the canonical `sensor.universal_room_automation_census_unidentified_persons_in_house` state within one tick.

### D3: Test fixture authority — real census, not hand-copied numbers

Per Tier 2-DB Review C framing: the fixture that produces the census used in
D1/D2 tests MUST be constructed by calling the real
`PersonCensus._cross_correlate_persons` and/or `_apply_enhanced_house_census`
(see `quality/tests/test_camera_census.py:888-947` and
`quality/tests/test_guest_census_correctness.py:195-266` for the existing
harness pattern) — never a hand-built `CensusZoneResult(unidentified_count=0)`
literal. Rationale: a hand-built fixture proves the *reader* consumes the
field; it does NOT prove the reader consumes the field with the same shape/
value the real writer produces. The real-writer fixture proves both.

**Acceptance criteria:**
- **Verify:** the new tests import `PersonCensus` and call one of
  `_cross_correlate_persons` / `_apply_enhanced_house_census` at least once to
  produce the fixture value used in the assertion.
- **Verify:** if a shim/monkeypatch is added, it wraps but does not *replace*
  the real derivation (per `feedback_hollow_test_anchors.md`).

### D4: Deferred-adjacent finding parked, not built

`URAUnexpectedPersonSensor.is_on` at `binary_sensor.py:1540-1560` uses
`camera_total > ble_total` — a comparison from the same two mismatched
substrates. Left in place this cycle (scope discipline; the card names two
sites). Written up in §9 with a parked follow-up card recommendation.

---

## 5. Non-goals (explicit)

- **NOT** touched: `URAUnexpectedPersonSensor.is_on` (§9 follow-up).
- **NOT** touched: `_get_wifi_guest_count` (`camera_census.py:3377`) — a
  *floor*-provider inside enhanced-census, not a consumer of either target
  site; different concept.
- **NOT** touched: `guest_count` in
  `sensor.py:13125` / `domain_coordinators/security.py:2208` — the authorized-
  guest snapshot from the sanction checker; unrelated to census unidentified
  count.
- **NOT** enabling `ZoneGuestCountSensor` by default. It stays
  disabled-by-default; the migration does not change its registration state.
- **NOT** changing the `SENSOR_ZONE_GUEST_COUNT` const, unique-id shape, or
  device-info binding — that is a rename and would break entity-registry
  continuity for any operator who enabled the entity historically.
- **NOT** adding new signals, dispatches, DB rows, or config-entry fields.
- **NOT** deprecating or renaming the `camera_total` / `ble_total` attribute
  keys on either site (dashboard/scrape compatibility).
- **NOT** resolving the pre-existing per-zone-entity vs house-level-value
  granularity mismatch on `ZoneGuestCountSensor` (both the old naive formula
  and the new deduped formula read `house.*` — every enabled zone entity
  emits the same house-level integer; a per-zone guest count is a separate
  deliverable that would require a per-zone census cut). Plan-review M1
  touch-up (2026-08-18).

---

## 6. Falsifiable invariant (restatement for reviewers)

**I-GC:** *No reachable production path in
`custom_components/universal_room_automation/` produces a "guest count" value
via `max(0, camera_total - ble_total)` or any equivalent second-derivation
subtraction. Every surfaced guest-count value equals the canonical
`census.last_result.house.unidentified_count` (or 0 when the census is
unavailable).*

**How D (adversarial completeness) would falsify:** re-enumerate every hit of
`guest_count` (case-insensitive, non-test) and every hit of
`unidentified_count` in the tree; for each hit that *emits* a value, prove it
routes through `house.unidentified_count` OR that its subtree is out of scope
per §5 (with a written justification for each exclusion). A single unlisted
emission of `camera_total - ble_total` from a live-reachable path is a
falsification.

---

## 7. Numbers-get-knobs ladder

**No new numbers.** The migration removes a derived integer (the naive
subtraction) and reads an existing derived integer (`unidentified_count`).
There is no threshold, no window, no duration, no gate value introduced. Ladder
placement: **N/A** — nothing to expose.

If a reviewer proposes a knob (e.g., a "prefer naive over deduped" toggle for
rollback), the response is: no. A toggle here duplicates the very
producer-divergence class the cycle exists to kill (see
`feedback_marginal_benefit_pushback.md`). Rollback path is `git revert`, not a
runtime flag.

---

## 8. Tier classification — Tier 2-DB justified

**Trust-hierarchy ripple:** the surfaces being migrated FEED census-guest-
presence dashboards; the census/guest/presence axis is precisely the
"regression-prone" ripple call-out in `CLAUDE.md` under "Tier 2-DB for ALL
regression-prone work" (memory: `feedback_tier2db_for_regression_prone.md`).
Even though grep-verified there are zero *code* consumers, operator-visible
dashboards and NM templates may consume the attributes; a silent
divergence between the migrated deduped value and the historical naive value
would look like a display regression and — because guest count is a
GUEST-mode diagnostic — could mislead the operator into wrong live tuning
decisions.

**Shared-primitive dependency:** the migration adds two new consumers of the
census `unidentified_count` field. That field's producers
(`_cross_correlate_persons`, `_apply_enhanced_house_census`) are shared
primitives consumed across coordinators; a shape or semantics regression in
those producers would now surface in two additional entities. This is exactly
the "changes to a shared primitive consumed by multiple coordinators" trigger.

**Payload-shape change on a persisted / observable record:** the
`extra_state_attributes` dict shape on both target entities is a public
observable contract (HA recorder stores state changes and attribute snapshots).
Changing the value semantics of `guest_count` while keeping the key IS a
payload-shape change under the Tier 2-DB trigger list ("changes payload shape
of a dispatched event or persisted record").

**Three framing-disjoint reviews:**

- **Review A — data integrity + arithmetic correctness.** Per site: is the
  migrated arithmetic correct? Are graceful-degradation sentinels preserved?
  Are attribute-key shapes preserved? Is state-vs-attribute consistency
  achieved on both sites?
- **Review B — cross-coordinator / consumer completeness.** Independent
  re-run of the CONSUMER search across `custom_components/`, `.storage/`
  (blueprints/automations if any exist in the operator's install — flag as
  live-validation task, not blocker), and dashboard YAML if committed. Verify
  the "zero code consumers" claim by re-greeping without relying on this
  planning doc's ledger.
- **Review C — test-fixture authority + adversarial completeness.** Verify
  D3: fixtures actually drive the real census writer, not a hand-built
  `CensusZoneResult`. Per-site source mutation drill: edit `aggregation.py`
  `_get_guest_count` back to the subtractive form; confirm the *new*
  discriminating test fails; restore. Repeat for `binary_sensor.py:1584`.
  Then re-enumerate the invariant surface — every `guest_count` and every
  `unidentified_count` string across `custom_components/` — and prove each
  emission either routes through `house.unidentified_count` or is
  scope-excluded per §5.

**Operator elevation to Tier 3?** No, unless the operator flags. The cycle is
additive-consumer, not additive-producer; there is no strategy or
decision-logic change; no cost or safety axis is touched. The Tier 2-DB
three-framing bar plus mutation-anchored tests is sufficient. If the operator
disagrees and elevates, the fourth (D) framing already has a clear job:
re-enumerate the invariant surface as a diff-blind pass, and one candidate to
audit under D is `URAUnexpectedPersonSensor.is_on` (§9) — the adversarial
pass may want to prove that leaving `is_on` on the naive comparison does not
create a new I-GC violation via an attribute-derived template sensor an
operator might have added downstream (a live-validation check, not a code
break).

---

## 9. Adjacent finding — parked, NOT built this cycle

`URAUnexpectedPersonSensor.is_on` (`binary_sensor.py:1540-1560`) evaluates
`camera_total > ble_total`. This is a *comparison* of the same two mismatched
substrates as the migrated attribute. It is not the target of card
`GUEST-COUNT-DEDUP-MIGRATE-1` (the card names `:5983` + `:1584`), and its
`is_on` state has its own consumer surface that must be independently
producer/consumer-analyzed before touching (e.g., NM alert wiring on
"Unexpected Person Detected" may depend on the exact firing semantics). It is
also the state that drives the sensor's entire reason for existing, so a
migration here is a *behavioral* change, not a display swap.

**Recommendation:** create a follow-up card
`UNEXPECTED-PERSON-IS-ON-DEDUP-MIGRATE-1` scoped to this single decision:
should `is_on` fire when `house.unidentified_count > 0` instead of when
`camera_total > ble_total`? Answer requires enumerating NM/alert consumers of
`binary_sensor.universal_room_automation_unexpected_person_detected` — a
different producer/consumer surface than this cycle.

Evidence trigger to graduate the parked card: a live divergence observation
in which `is_on` fires (naive substrates disagree) but
`unidentified_count == 0` (census fuse says no guest), or the inverse. Either
is a case where the two derivations tell the operator different stories.

---

## 10. Verification steps summary

Pre-build:
1. `git tag pre-review-guest_count_dedup_migrate` (Tier 2-DB pre-review baseline discipline).
2. Snapshot: `sensor.ura_*_guest_count` and
   `binary_sensor.universal_room_automation_unexpected_person_detected`
   attribute values from the live HA instance (for D+/live comparison).

Post-build (builder):
1. `git grep -n "camera_total - ble_total" custom_components/` returns no live-code hits.
2. Unit suite: `PYTHONPATH=quality python3 -m pytest quality/tests/test_zone_guest_count_dedup_migrate.py quality/tests/test_unexpected_person_attr_dedup_migrate.py -v` all green.
3. Full-suite baseline diff vs `pre-review-guest_count_dedup_migrate`.
4. Per-site source-mutation drill (Review C): revert each site independently, prove the specific discriminating test fails, restore, prove suite green. Anchors: the mutation-anchor test in D1 (asserts `house.unidentified_count` substring inside `_get_guest_count`) + an equivalent for D2.

Live (post-restart, README write-back mandatory):
1. Enable one `sensor.ura_<zone_slug>_guest_count` via UI. Read state. Read `state_attr('sensor.universal_room_automation_census_persons_in_house','unidentified_count')`. Assert equal.
2. Read `state_attr('binary_sensor.universal_room_automation_unexpected_person_detected','guest_count')`. Assert equal to `sensor.universal_room_automation_census_unidentified_persons_in_house` state.
3. Confirm ZERO ERROR-level URA logs mentioning `ZoneGuestCountSensor` or `UnexpectedPersonSensor`.
4. Fill in README v<version>.md "Validated <date>" table with observed values (per the CLAUDE.md README write-back rule).

---

## 11. Files touched

- `custom_components/universal_room_automation/aggregation.py` — modify
  `ZoneGuestCountSensor._get_guest_count` (`:5983-6001`) and
  `extra_state_attributes` (`:5957-5981`).
- `custom_components/universal_room_automation/binary_sensor.py` — modify
  `URAUnexpectedPersonSensor.extra_state_attributes` (`:1562-1585`). `is_on`
  UNCHANGED.
- `quality/tests/test_zone_guest_count_dedup_migrate.py` — NEW test module
  (D1 + D3 anchors).
- `quality/tests/test_unexpected_person_attr_dedup_migrate.py` — NEW test
  module (D2 + D3 anchors).
- `docs/readmes/README_v<next>.md` — created pre-deploy; validated
  post-restart.

No changes to `const.py`, `config_flow.py`, `options_flow.py`, `database.py`,
`camera_census.py`, `sensor.py`, any coordinator, any signal, any dispatch.
