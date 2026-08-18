# Egress-Face-Identity D1 — Review A (Correctness + edge cases)

**Branch:** `feature/egress-face-identity-d1` @ `fa5b57c52`
**Diff base:** `develop...HEAD` (three-dot; merge-base)
**Framing:** A — arithmetic correctness, freshness windows, None/empty/unavailable handling, name normalization, veto semantics, test authority.
**Scope:** D1 only. D2 explicitly out-of-scope (fenced by plan).

Files reviewed:
- `custom_components/universal_room_automation/const.py` (+11)
- `custom_components/universal_room_automation/transit_validator.py` (+92)
- `custom_components/universal_room_automation/camera_census.py` (+105)
- `quality/tests/test_egress_face_identity_d1.py` (+387)

Cycle tests: **15/15 PASS** (`PYTHONPATH=quality python3 -m pytest quality/tests/test_egress_face_identity_d1.py -q`).

---

## Verdict — DO-NOT-SHIP

One HIGH: the mirrored `person.<slug> == not_home` stale-face veto in `_resolve_egress_face_identity` uses the wrong slug namespace and can never fire against a real HA person entity in this household. The cycle's own veto test is a hollow oracle that re-implements the buggy slug derivation, so it PASSES on the broken code (Bug Class #62/#64 — hollow test anchor). Ship-blocker because the plan explicitly scoped C-LOW-2 as an invariant to preserve, and shipping this creates a documented-but-inert defense that will not be re-visited.

One MEDIUM: `identified_persons` attribute + DB column now carry Frigate first-name slugs (`"oji"`) instead of URA slugs (`"oji_udezue"`) at the enhanced-house path. This is a silent schema-shape change to a published sensor attribute and a persisted census-history column — no plan callout, no downstream-consumer audit.

Two LOW noted below.

---

## Findings

### A-HIGH-1 — `_resolve_egress_face_identity` veto slug mismatch → veto silently never fires

- **Severity:** HIGH
- **Bug class:** #23 (observation-mode/veto gating never engages) + #62/#64 (hollow test anchor masks it)
- **Site:** `custom_components/universal_room_automation/transit_validator.py:1130-1143`

```python
slug = val.strip().lower().split("_", 1)[0]      # val = "Oji"  → slug = "oji"
person_entity_id = f"person.{slug}"              # → "person.oji"
```

The mirrored census helper (`camera_census.py:3456`) derives the person entity from the URA `tracked_persons` slug — `f"person.{person_slug.lower()}"` where `person_slug` comes from stripping `"person."` off the configured id — so it queries **`person.oji_udezue`**, the actual HA entity in this household (confirmed via `person_coordinator.py:104,417` and the test's own `tracked_persons` fixture value `"person.oji_udezue"`).

The new helper receives `val` as the **Frigate face-library first-name** (`"Oji"`) and derives the slug as its first token → `"oji"` → looks up **`person.oji`**, which does not exist. `hass.states.get("person.oji")` returns `None`, the guard hits its explicit fail-open branch, and the veto never suppresses anything — regardless of whether the real `person.oji_udezue` is `home`, `not_home`, `unknown`, or anything else.

**Failing input → wrong output:**
- HA state: `sensor.front_door_last_recognized_face = "Oji"` (fresh, last_changed = now); `person.oji_udezue = "not_home"`; `person.oji` = missing (as in every real deployment).
- Expected (plan C-LOW-2 invariant): helper returns `None` (stale-face latch guard suppresses identity because tracker says not-home).
- Actual: helper returns `"Oji"`; egress event stamps `person_id="Oji"` and `register_egress_face` seeds the census union for a resident who is provably not_home.

**Why the tests miss it:** `_make_tracker_with_census` builds the test's `person.<slug>` state using the SAME `val.strip().lower().split("_", 1)[0]` derivation the code under test uses (test file lines 118-119). Both sides agree on `person.oji`, so the veto test passes. This is exactly the anti-pattern in `feedback_hollow_test_anchors.md` — the oracle re-implements the code path it is meant to check.

**Recommended fix:**
1. In the helper, resolve the URA slug from the Frigate first name via the census's existing tracked_persons registry — not by string manipulation on `val`. Concretely: iterate `tracked_persons` and pick the slug whose first token equals `_normalize_person_name(val)`; then query `person.<that_slug>`. Reuses census institutional knowledge instead of re-deriving.
2. Fix the test to construct `person.oji_udezue` (the real HA entity) and independently verify that a fresh face + `person.oji_udezue=not_home` yields `None`. This is the discriminator that would have caught the bug.
3. Alternative if a full lookup is judged too heavy: query BOTH `person.{first_token}` AND every `person.{slug}` in `tracked_persons` whose first token matches — but option 1 is cleaner.

Ship-blocker: the plan-review lifted C-LOW-2 into the acceptance surface; a defense that never engages is worse than no defense because nobody will hunt it again.

---

### A-MED-1 — `identified_persons` attribute/column semantics silently changed to first-name slugs

- **Severity:** MEDIUM
- **Bug class:** #6 (schema/attribute-shape drift), adjacent to #23
- **Sites:**
  - `custom_components/universal_room_automation/camera_census.py:3505-3510` (fuse site 2 normalizes into `recognized_set`)
  - `custom_components/universal_room_automation/camera_census.py:3562` (`identified_persons=sorted(recognized_set)`)

Consumers of the enhanced-house `CensusZoneResult.identified_persons`:
- `sensor.py:3609` — published as JSON `person_list` on the "identified persons in house" sensor attribute.
- `database.py:3583-3601` — persisted to `census_house_history.identified_persons` (TEXT JSON).
- `camera_census.py:1205` — `face_persons=list(set(house_result.identified_persons + property_result.identified_persons))` mixes with property-result names before feeding downstream.

Pre-cycle these were URA slugs (e.g. `"oji_udezue"`); post-cycle they are Frigate first-name slugs (`"oji"`). The DB column will contain a chronological mix of the two shapes, breaking any query that filters by full slug. The plan does not call this out; there is no migration or dual-write, and no downstream-consumer audit in the review record.

Note: the raw fuse site 1 (`:1874`) also normalizes now, but the plan-review C-CRIT-1 finding correctly concluded that site's output is overwritten by the enhanced path, so its shape change is a no-op in practice. The MEDIUM is specifically the enhanced-path output.

**Recommended fix:** either (a) keep `identified_persons` in URA-slug form and only use first-name normalization for internal set-membership dedup (normalize to compute `identified_count`; retain slug list separately), or (b) explicitly acknowledge the schema change in the README, note the DB shape transition, and audit the two sensor consumers plus the `face_persons` mix at `:1205` for downstream breakage.

---

### A-LOW-1 — `abs()` on face-age lets a face recognized AFTER the crossing count as fresh

- **Severity:** LOW
- **Bug class:** #23 (semantic gate too permissive)
- **Site:** `transit_validator.py:1101` — `age = abs((timestamp - last_changed).total_seconds())`

If `last_changed > timestamp` (face recognized *after* the recorded crossing time — possible under clock skew, or because Frigate's face event lands seconds after the door-camera person-occupancy edge that drove `_resolve_direction`), the `abs()` accepts it as fresh. Semantically this is "attach an identity from a future observation to a past crossing." For the D1 use case that is probably desirable (face-arrives-slightly-late is the common case), but it is inconsistent with `camera_census._get_egress_face_ids_fresh` which treats `age < 0` as stale and prunes. Two adjacent freshness gates with opposite sign conventions is a maintenance trap.

**Recommended fix:** pick one convention repo-wide (I'd keep `abs()` here and make the census helper symmetric — a face registered a few seconds "in the future" relative to a census tick is a clock-skew artifact, not staleness). Or document the intended asymmetry inline. Not ship-blocking.

---

### A-LOW-2 — `register_egress_face` accepts tz-naive `ts` silently; only surfaces on read

- **Severity:** LOW
- **Bug class:** #6 (tz-naive/aware mix)
- **Site:** `camera_census.py:2773-2780`

`register_egress_face` writes `ts or dt_util.now()` without a tz-awareness check. If any future caller passes a tz-naive `datetime` (the current sole caller in `transit_validator.py` uses the egress `timestamp` which is aware, so no live defect today), the entry sits in `_egress_face_ids` until `_get_egress_face_ids_fresh` raises `TypeError` on subtraction — caught, pruned, name silently dropped from the union. No warning is logged for the tz-mismatch case (it hits the same `except (TypeError, AttributeError)` as any other read defect).

**Recommended fix:** at the write boundary, `if ts.tzinfo is None: ts = ts.replace(tzinfo=dt_util.UTC)` and log INFO on coercion. Cheap and closes the door.

---

## Framing-A audit checklist (for the record)

| Check | Result |
|---|---|
| `FACE_MATCH_WINDOW_S` fencepost (`age > window` drops, `==` keeps) | OK — matches test |
| `EGRESS_FACE_UNION_TTL_S` fencepost (`age > ttl` prunes, `==` keeps) | OK — matches test |
| tz-naive `last_changed` handled | OK (patched to UTC before subtraction) |
| Empty / None / unavailable / unknown / no_match face state → None | OK; also handles bare `"none"` string |
| `_extract_camera_stem` returns None → None | OK, early-return covered |
| `_resolve_face_entity_id` raises → None (fail-CLOSED) | OK, `except` present |
| `hass.states.get` raises → None | OK |
| Name normalization at BOTH fuse sites | OK; `_normalize_name_set` applied at `:1874` AND `:3505` |
| `_normalize_person_name` unicode/whitespace/None safety | OK for None/empty/whitespace via `strip().lower()`; unicode not explicitly tested but `.lower()` is unicode-safe in py3 |
| Prune-during-iterate safety | OK; two-pass (collect stale list, then `pop`) |
| Test discriminator for C-CRIT-1 (`test_house_fuse_egress_only_moves_house_count`) drives real `_apply_enhanced_house_census` | OK — the site would break the test if the `:3491` union were reverted |
| Test discriminator for C-LOW-2 veto is oracle-independent | **FAIL** — see A-HIGH-1 |
| `person.<slug>` veto uses the same namespace as `_get_face_recognized_person_names` (`camera_census.py:3456`) | **FAIL** — see A-HIGH-1 |

---

## Recommendation

**DO-NOT-SHIP.** Fix A-HIGH-1 (real defect + hollow test) and A-MED-1 (either preserve the attribute shape or explicitly own the schema break). A-LOW-1 and A-LOW-2 should be fixed in the same fix-up pass per `feedback_fix_lows_in_cycle.md` (both are one-liners).

After fix-up, re-verify A-HIGH-1 with a mutation-anchored test: temporarily change the helper's slug derivation to something guaranteed wrong (e.g. `slug = "zzz"`), confirm the veto test FAILS; restore. If the test still passes on the mutation, the oracle is still hollow.
