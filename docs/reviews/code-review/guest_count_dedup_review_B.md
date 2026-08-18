# Review B — GUEST-COUNT-DEDUP-MIGRATE-1

**Framing (B):** cross-coordinator + no-double-count + `is_on` independence + whole-repo naive-formula sweep. Adversarial. Diff-blind on the sweep (looks at pre-existing code, not only the cycle diff), per the standing Tier 2-DB / Tier 3 posture.
**Branch:** `feature/guest-count-dedup` @ `d010122bd`, worktree `.claude/worktrees/guest-count-dedup`.
**Scope files re-read end-to-end:** `custom_components/universal_room_automation/aggregation.py` (5920-6020), `binary_sensor.py` (1500-1610), `sensor.py` (4420-4510, 3480-3710, 13115-13135), `camera_census.py` (150-160, 1850-1930, 3690-3780), `domain_coordinators/presence.py` (980-1250, 4380-4440, 5140-5220, 6440-6660, 7620-7635), plan (`docs/planning/PLANNING_guest_count_dedup_migrate.md`), plan-review (`docs/reviews/code-review/guest_count_dedup_plan_review.md`).
**Cycle test file:** `quality/tests/test_guest_count_dedup_migrate.py` — spot-read; not full suite.

**Verdict: DO-NOT-SHIP as scoped.** One HIGH finding (H1) — the cycle's own falsifiable invariant I-GC is violated by a **third**, enabled-by-default naive-formula emission site the plan / plan-review / build all missed on the whole-repo sweep. On the two sites the cycle *did* migrate, the migration is correct: `URAUnexpectedPersonSensor.is_on` is genuinely independent of the migrated attribute, and no cross-coordinator consumer relies on either migrated sensor attribute for a trust decision. Fixing H1 (either migrate the third site or explicitly park it with a card the same way `UNEXPECTED-PERSON-IS-ON-DEDUP-MIGRATE-1` is parked, and amend the invariant text) resolves the review.

---

## 1. Whole-repo naive-formula sweep — the load-bearing enumeration

Grep run at repo root against the feature worktree:

```
rg -n "camera_total\s*-\s*ble|max\(0,\s*camera_total" custom_components/
```

Reachable production emission sites of `max(0, camera_total - <ble>)`:

| # | File:line | Class / property | Enabled-by-default? | Migrated by cycle? |
|---|---|---|---|---|
| 1 | `aggregation.py:6008` (post-diff — new deduped path) | `ZoneGuestCountSensor._get_guest_count` | No (`_attr_entity_registry_enabled_default = False`, aggregation.py:5934) | **YES** ✔ |
| 2 | `binary_sensor.py:1601` (post-diff — new deduped attribute) | `URAUnexpectedPersonSensor.extra_state_attributes["guest_count"]` | Yes | **YES** ✔ (attribute only; `is_on` intentionally parked as `UNEXPECTED-PERSON-IS-ON-DEDUP-MIGRATE-1`) |
| 3 | **`sensor.py:4477`** | **`UnidentifiedPersonsSensor.native_value`** | **Yes** (`_attr_entity_registry_enabled_default = True`, sensor.py:4448) | **NO — missed entirely** |
| — | `camera_census.py:1862, :1899` | `_cross_correlate_persons` (the canonical deduped writer — this IS the correct producer; `identified_count` = `|face_ids ∪ ble_ids|`, not the naive substrate count) | n/a | n/a (source of truth) |

Site #3 is a repo-wide, live, user-visible violation of the cycle's own invariant. Detail below in H1.

---

## 2. Findings

### H1 (HIGH — the cycle's own invariant I-GC is violated on the whole-repo sweep by `UnidentifiedPersonsSensor`)

**File:line.** `custom_components/universal_room_automation/sensor.py:4439-4503` (class `UnidentifiedPersonsSensor`; the offending line is **`:4477`** — `return max(0, camera_total - ble_identified)` — and the attribute-side mirror at **`:4498-4500`**).

**Entity_id.** `sensor.universal_room_automation_unidentified_persons` (from unique_id shape at `sensor.py:4453`: `f"{DOMAIN}_unidentified_persons"`). Registered in the platform setup at **`sensor.py:161`** (`UnidentifiedPersonsSensor(hass, entry)` inside `async_setup_entry`), enabled-by-default at `sensor.py:4448`.

**Semantics.** The docstring on the class (`sensor.py:4440-4443`) says verbatim: *"House-level unidentified persons — camera sees them but BLE can't identify. Uses house-level camera count (PersonCensus) minus BLE identified count."* — i.e. this sensor answers **the same question** as the two sites the cycle migrated. Its derivation:

```python
camera_total = int(float(census_state.state))   # sensor.py:4465
ble_identified = sum(
    1 for p in person_coordinator.data.values()
    if p.get("location") not in (None, "unknown", "away")   # sensor.py:4472-4475
)
return max(0, camera_total - ble_identified)             # sensor.py:4477
```

That is `max(0, camera_total − ble_present_by_location)` — the exact `max(0, camera_total − <ble-substrate-count>)` shape the cycle's falsifiable invariant I-GC forbids on any reachable path. It is *worse* than the pre-migration formula on the other two sites in one specific respect: the BLE substrate here is "BLE persons whose `location` is not `away`/`unknown`/`None`" (a location-derived count), which can diverge from the tracking-status `active` count the *other* naive sites used — meaning the three pre-migration sites did not even agree with each other. Post-diff, sites #1 and #2 read the deduped `house.unidentified_count`; site #3 still emits the naive answer against a *third* BLE substrate — so the discriminating divergence the plan constructed (`camera=6, identified=6, ble_active=2` → naive says 4, deduped says 0) reproduces here too, and the operator-facing default sensor will read **4** while the deduped source and the migrated attribute both read **0**.

**Why the plan / plan-review / build missed it.** The Institutional-context section of the plan and the plan-review both greppedfor the *string* `guest_count`:

- Plan §1.3: *"`git grep -n "guest_count"` under `custom_components/` returned exactly these two production write-sites…"*
- Plan-review §1.2: *"Grep `git grep -n "guest_count" custom_components/` returned only…"*

`UnidentifiedPersonsSensor` does not contain the token `guest_count` anywhere — its variable is `ble_identified`, its class is `Unidentified*`, and its attribute key is `ble_identified`. It falls outside the string grep. The falsifiable invariant I-GC is stated in terms of the *forbidden expression* (`max(0, camera_total − ble)`) — the grep chosen to verify it was narrower than the invariant. Under CLAUDE.md's "Post-Ship Supersession & Consumer-Gap Audit" rule (*"Scope the sweep to the PRE-EXISTING code the new capability could obsolete — repo-wide across the capability's DOMAIN, NOT the cycle's own diff"*), the domain is "house-level unidentified/guest count", and this site is squarely in it.

**Blast radius.**
- User-visible: yes — enabled-by-default sensor; almost certainly the source dashboards and NM templates would reference for "how many people in the house we can't identify" (the plan's argued-for canonical answer).
- Cross-coordinator consumers: greppable via `git grep -n 'universal_room_automation_unidentified_persons\|UnidentifiedPersonsSensor' custom_components/` — returned only the platform-setup site (`sensor.py:161`) and the class definition. So no *code* trust decision. Same posture as sites #1 and #2 — display-only, but that is exactly why the cycle chose to migrate #1 and #2. Excluding #3 is inconsistent.
- Invariant I-GC: **violated repo-wide.** Any post-restart proof that "no reachable path emits `max(0, camera_total − ble)`" fails on `sensor.py:4477`.

**Coherence hazard with the migrated sites (this is the specific cross-coordinator symptom).** Post-deploy, an operator or automation reading both `sensor.universal_room_automation_unidentified_persons` (site #3, naive, non-deduped) and `state_attr('binary_sensor.universal_room_automation_unexpected_person_detected','guest_count')` (site #2, deduped) will see **two different integers claiming to be the same quantity** in the same tick — reintroducing the exact "silent divergence between two derivations of the same value" failure the cycle set out to eliminate. The migrated attribute's docstring at `binary_sensor.py:1566-1569` promises the value *is* `census.last_result.house.unidentified_count`; site #3 promises the same conceptually but computes something else. Fix D2's acceptance criterion (plan §304 / §500 — *"`state_attr(...,'guest_count')` equals the canonical `sensor.universal_room_automation_census_unidentified_persons_in_house` state within one tick"*) will PASS while `sensor.universal_room_automation_unidentified_persons` DISAGREES with both — a discriminating-observation failure the plan's acceptance table does not catch.

**End-to-end trace.**
- Producer: naive substrate — camera-total from a state-string parse (`sensor.py:4459-4467`) minus a location-based BLE count derived from `person_coordinator.data` (`:4472-4475`). Neither dependency is health-checked (Producer rule).
- Emission: `native_value` (int, state) + `extra_state_attributes` (`camera_total`, `ble_identified`, `data_scope`, `note`) — both derivations, computed twice.
- Consumers (code): none inside `custom_components/`. Off-repo (`.storage/`, dashboards, NM) not grep-verifiable — same caveat the plan-review flagged as L1 for the other two sites, applies identically here.

**Fix — two acceptable options.**
1. **Migrate site #3 in this cycle** (preferred — one-locus scope, keeps invariant surgically true). Replace `native_value` body with a read of `census.last_result.house.unidentified_count` (same producer swap as sites #1 and #2), and mirror the attribute rewrite (state and attributes from one snapshot of `house`). Add a discriminating test to the cycle suite: same fixture as the plan's D1 discriminating case (`camera=6, identified=6, ble_active=2` — plan §1.6) applied against `UnidentifiedPersonsSensor.native_value`; old → 4-or-6-depending-on-substrate, new → 0. Also add a repo-wide invariant test: `git grep -nE "max\(0, camera_total\s*-\s*(ble|identified)" custom_components/` returns empty (this codifies I-GC as a test, not a claim).
2. **Explicitly park site #3** with a named card the same way `UNEXPECTED-PERSON-IS-ON-DEDUP-MIGRATE-1` parks the `is_on` comparator (e.g. `UNIDENTIFIED-PERSONS-SENSOR-DEDUP-MIGRATE-1`), amend invariant I-GC to say *"…on the two target sites listed in §3"* rather than "on any reachable path", and add a code comment at `sensor.py:4477` pointing to the parking card. **This option is weaker** because the sensor is enabled by default, semantically identical, and the coherence hazard is live from deploy.

Option 1 is a ~15-line change with a fixture the cycle already has.

### L1 (LOW — same class, attribute-side mirror)

`UnidentifiedPersonsSensor.extra_state_attributes` at `sensor.py:4499-4503` recomputes the naive derivation a second time inside the same class, then exposes `ble_identified` as an attribute. If H1 is fixed via option 1, this must be rewritten together (state and attributes from one snapshot of `house`, `feedback_cross_investigation_synthesis.md` discriminating-observation rule) — otherwise the class internally splits its own state from its own attributes. Non-blocking on its own; folded into the H1 fix.

---

## 3. `URAUnexpectedPersonSensor.is_on` independence — CONFIRMED

Re-read `binary_sensor.py:1540-1602` end-to-end.

- `is_on` (:1540-1560) reads `census` and `person_coordinator` freshly on every access, writes `self._camera_total` and `self._ble_total` as a side-effect for diagnostic purposes, and returns `self._camera_total > self._ble_total`.
- `extra_state_attributes` (:1562-1602, post-diff) *also* reads `census` and `person_coordinator` freshly on every access, computes `guest_count = census.last_result.house.unidentified_count` **directly from the census snapshot** (line 1590), and does **not** read `self._camera_total` / `self._ble_total`. The instance state written by `is_on` is not consumed by the attribute property, and vice versa.

There is no shared helper, no shared mutable state that flows between the two properties, and no ordering dependency. The build's claim (and the plan-review's claim) that migrating the attribute cannot alter `is_on` is upheld. The `camera_total` and `ble_total` attribute keys are **retained** with their pre-diff meanings — the only key that changed is `guest_count`, and it changed to the deduped value; `ble_total` is still the tracking-status `active` count, so a dashboard scrape of `{camera_total, ble_total}` is byte-identical to pre-diff on the same tick.

**Correct-by-design incoherence to acknowledge (not a bug).** `is_on = True` with `guest_count = 0` is legal post-migration and is *not* a coherence violation: `is_on` asks "does the camera see more bodies than BLE tracks?" (a BLE-tracking-coverage alarm); `guest_count` asks "how many bodies remain after subtracting the union of face-ID and BLE-ID resident sets?" (a resident/guest classification). If face-ID resolves all 3 camera bodies to residents but BLE only tracks 2 of them, is_on fires (BLE coverage gap on a known resident) while guest_count is 0 (nobody is actually a guest). Operator-facing, this is *more* accurate than the pre-diff state where both used the same naive substrate and thus agreed by coincidence. The plan / build correctly parked the `is_on` migration under `UNEXPECTED-PERSON-IS-ON-DEDUP-MIGRATE-1`; this posture is defensible.

---

## 4. No new double-count / no guest-mode ripple — CONFIRMED with one caveat

**Question 1: does any code consumer read the *migrated* sensor attribute for a trust decision?**
Grep: `git grep -n "guest_count\|ura_.*guest_count\|zone_guest_count"` under `custom_components/` — writers on the two migrated sites plus the parked `is_on` site; the unrelated `security` snapshot `guest_count` at `sensor.py:13125` and `domain_coordinators/security.py:2208` (authorized-guest count from the sanction path, different domain — plan-review §1.2 correctly excluded); one comment in `transit_validator.py:1315`. **Zero code readers** of either migrated attribute. Plan-review §1.2 confirmed independently.

**Question 2: does GUEST house-state gate off the migrated attribute?**
No. The presence coordinator reads `unidentified_count` directly from the **census-dispatched signal payload**, not from the sensor attribute:
- `domain_coordinators/presence.py:4401`: `self._unidentified_count = int(census_data.get("unidentified_count", 0))` — `census_data` is the dispatched census-tick payload, not a sensor-attribute read.
- `presence.py:5152, :5175, :6006, :6220` — all `unidentified_count` reads are of `self._unidentified_count`, populated exclusively from that signal.
Migrating the two *sensor attributes* to the deduped value has no effect on this path; the presence coordinator already consumes the deduped value directly from the census. No trust-decision ripple, no double-count, no feedback loop.

**Caveat (informational, not a finding).** Because presence.py already consumed the deduped value while the sensor attributes emitted the naive value, the pre-diff state had a *silent* producer/consumer disagreement inside URA itself — presence gated GUEST off deduped, but the operator dashboard read naive. The cycle collapses that internal disagreement on the two migrated sites; H1 above is why it does *not* fully collapse it repo-wide.

**Question 3: any feedback loop through census from the migrated value?**
No. Neither `ZoneGuestCountSensor` nor `URAUnexpectedPersonSensor` writes back into `PersonCensus` or into `person_coordinator`. `_get_wifi_guest_count` inside `camera_census.py:3377-3542` is a Wi-Fi-client heuristic used as a *floor input* to the enhanced census, wholly unrelated to the migrated attributes (plan-review §1.2 correctly excluded).

---

## 5. Restart / census-timing on the alert sensor — SAFE

Boot ordering: before `PersonCensus` has emitted its first `last_result`, `census.last_result` is `None`.

- `URAUnexpectedPersonSensor.is_on` (`binary_sensor.py:1546-1547`) short-circuits to `False` when `census` or `person_coordinator` is missing; when `census.last_result` is `None`, `self._camera_total = 0` (`:1549`), so with any `ble_total` the comparison is `0 > ble_total = False`. **No boot flap.**
- `extra_state_attributes` (post-diff, `:1585-1590`) defaults `camera_total = 0`, `ble_total = 0`, `guest_count = 0` under the same guard. Attribute reads consistent with `is_on=False`.
- `ZoneGuestCountSensor._get_guest_count` (post-diff, `aggregation.py:6002-6008`) returns `0` when `census` or `census.last_result` is `None` — same graceful-degradation sentinel as pre-diff.
- Post first census tick, if the tick is empty (`camera_total=0, unidentified_count=0`), all three values collapse to `0` — coherent.

**One transient worth naming.** During the window from HA start to first census tick, `sensor.universal_room_automation_unidentified_persons` (site #3, unmigrated) computes via `hass.states.get('sensor.universal_room_automation_persons_in_house')` (`sensor.py:4459-4460`). If the persons-in-house sensor is `restored:true` / `unknown` at boot before the census initializes, the `int(float(...))` conversion returns `None` and `native_value` returns `None` (`sensor.py:4463, :4467`). This is pre-existing behavior and does not create a new hazard; it does mean the boot ordering between site #3 and sites #1/#2 differs (sites #1/#2 read `census.last_result` directly and go to `0`; site #3 reads through a state-string parse and goes to `None`). Another argument for H1 option 1 (migrate site #3 to the same read shape).

---

## 6. Independent naive-formula-repo-sweep verdict

**Repo-wide `max(0, camera_total − <ble-substrate>)` emission sites post-diff:**

| Site | Migrated? | Enabled-by-default? |
|---|---|---|
| `aggregation.py:6008` (ZoneGuestCountSensor, deduped) | ✔ | No |
| `binary_sensor.py:1601` (URAUnexpectedPersonSensor attr, deduped) | ✔ | Yes |
| `binary_sensor.py:1560` (URAUnexpectedPersonSensor `is_on`, naive) | Parked (`UNEXPECTED-PERSON-IS-ON-DEDUP-MIGRATE-1`) | Yes |
| **`sensor.py:4477` (UnidentifiedPersonsSensor.native_value, naive)** | **NO — missed** | **Yes** |

Invariant I-GC as stated ("no reachable path still emits guest-count via `max(0, camera − ble)`") is **not satisfied** post-diff. The plan is either short one migration (H1 option 1) or short one parking card + an invariant amendment (H1 option 2).

## 7. `is_on` independence verdict

**Independent.** Confirmed by re-read of `binary_sensor.py:1540-1602`. Migrating the attribute cannot alter `is_on` behavior; the two properties share no state that flows between them. Parking `is_on` under `UNEXPECTED-PERSON-IS-ON-DEDUP-MIGRATE-1` is the correct call.

---

## 8. Summary

- **DO-NOT-SHIP** on H1 alone. H1 fix is a ~15-line producer swap on `sensor.py:4477` + attribute mirror at `:4498-4503` + one discriminating test + a repo-wide `git grep` invariant test.
- Sites #1 and #2 migrations are correct, cross-coordinator-safe, and free of double-count / feedback / boot-flap hazards.
- `is_on` independence and parking are both defensible.
- Recommend fix-up (H1 option 1) and a one-turn re-review of the fix-up commit, then ship.

**Bug class.** Whole-repo invariant enumeration miss (the invariant is stated on a *shape* — `max(0, camera − ble)` — but the verification grep is stated on a *token* — `guest_count`; the two do not coincide, and the narrower grep missed a live enabled-by-default site the shape catches). Related to Bug Class #53 (*computed-but-not-consumed / one-missed-site*), and to the operator-coined *Post-Ship Supersession & Consumer-Gap Audit* rule (2026-08-18) — the sweep scope must be the DOMAIN, not the cycle diff. Recommend a candidate `QUALITY_CONTEXT.md` bug class: *"Invariant stated on shape, verified on token — grep-scope narrower than invariant-scope."*
