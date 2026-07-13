# PLANNING — Enhanced-Census BLE-Cancel for Unrecognized Camera Persons

> **Re-emit after file-loss (working-tree churn clobbered the original before commit). Build has since landed at commit `2f864ac7`; this doc is preserved for review/history/reference.**

- **Cycle name:** `census_ble_cancel_unrecognized`
- **Target version:** TBD at deploy (successor to whatever tip is on `develop` at build start; re-anchor before commit)
- **Tier:** **Tier 2-DB** — 3 framing-disjoint reviews. Operator-elevated. Rationale: touches the presence/census trust hierarchy that feeds the guest gate and house-state inference. Silent regression risk is real-guest suppression (safety-adjacent) OR resident-mislabel loop (comfort/energy).
- **Sensitivity:** HIGH. Change is small in LoC but sits under `presence_coordinator._guest_gate_armed → HouseState`. Blast radius: guest mode, anomaly emissions on census transitions, NM notifications, HVAC eco/away preset decisions downstream of `HouseState`.
- **Operator directive:** "Document well." Plan and code comments must be readable cold six months from now — mechanism, precedent, invariant, and *why the raw path already did it this way*.
- **Author:** ura-planner
- **Filed:** 2026-07-13 (re-emit same day)
- **Anchor discipline:** Every file:line in this document was re-verified at filing. camera_census.py path is `custom_components/universal_room_automation/camera_census.py` (NOT `domain_coordinators/` — the deep-dig report used the wrong path prefix). Re-verify all anchors before build; the three concurrent cycles do NOT touch this file but a rebase against `develop` is still mandatory.

---

## 1. Institutional context verified

### 1.1 Files read end-to-end during scoping

- `custom_components/universal_room_automation/camera_census.py` — enhanced-house path (`_apply_enhanced_house_census` lines 1956-2012), unrecognized-camera path (`_get_unrecognized_camera_count` lines 1652-1731), raw path (`_cross_correlate_persons` lines 1213-1285, especially the arithmetic at 1243-1249), face-recognized-persons helper (`_get_face_recognized_person_names` lines 1900-1954), BLE persons helper (`_get_ble_persons` lines 1401-1418), `CameraInfo` dataclass with `area_id` field (line 75-80).
- `custom_components/universal_room_automation/person_coordinator.py` — `location` field semantics (stored as resolved room name; "away"/"unknown"/"" signal not-home; see lines 143-234, 313-315). `_area_id_to_room` cache (line 84).
- `custom_components/universal_room_automation/domain_coordinators/presence.py` — `_guest_gate_armed` interaction (referenced at lines 912-1046 range); the AWAY veto (v4.7.14) already predicates on `unidentified_count == 0` (line 983, 1046). This means our fix directly changes AWAY-veto behavior: fewer false unidentifieds → faster AWAY convergence when the family is out (a wanted side effect, but call it out for reviewers).
- `custom_components/universal_room_automation/const.py` — `CENSUS_FACE_RECOGNITION_WINDOW_SECONDS = 1800` (line 1434), `CENSUS_PEAK_SUSTAIN_SECONDS = 15` (line 1428), `CONF_CENSUS_HOLD_INTERIOR / DEFAULT_CENSUS_HOLD_INTERIOR_MINUTES = 3` (lines 1411/1418). Confirms operator's 15→3 change is live-configured and takes effect via the number entity on next restart.

### 1.2 Institutional greps (proof-of-work)

| Proposed addition | Verdict | Evidence |
|---|---|---|
| Function to correlate person → camera area | **NEW** (helper, private) — no existing helper does `person_location → area_id`. `person_coordinator._area_id_to_room` (line 84) inverts the map we need; we'll expose or mirror it. | Grep `area_id_to_room`, `room_to_area`, `person.*area` across `custom_components/**` — only hit is the person_coordinator cache; no reverse-lookup exists in camera_census. |
| Constant / CONF for enable/disable | **NEW but off by default? NO** — reject a new CONF. This is a bug-fix to the enhanced path to restore parity with the raw path (which already subtracts). Adding a CONF makes it look optional; it isn't. Fallback safety: single feature flag in-code (`_ENABLE_BLE_CANCEL = True`) for review/rollback only, not user-facing. | Grep `CONF_CENSUS_*` in const.py — no similar flag; adding one dilutes the "enhanced census v2" contract and invites drift. |
| New sensor / attribute | **REUSE + EXTEND** existing `CensusZoneResult` attrs. Add `ble_cancelled_count` diagnostic attr, surfaced on the house census sensor. No new entity. | `sensor.py` already exposes `camera_unrecognized`, `wifi_guest_floor`, `face_recognized_persons` from `CensusZoneResult` — extend the same channel. |
| Test fixtures | **REUSE** `quality/tests/test_census_v2.py` and `test_census_overcount_v5_9_0.py`. Add cases against `_apply_enhanced_house_census` and `_get_unrecognized_camera_count`. | Files present; already exercise `_dedup_by_area`. |
| Signal / dispatch | **NONE NEW.** No new dispatcher signal — enhanced census result is already pushed via the existing coordinator refresh cycle. | Grep `SIGNAL_CENSUS` — no per-attr signal. |

### 1.3 Prior planning docs skimmed

- `docs/planning/PLANNING_zone_camera_person_only_guard.md` — sibling zone-tier guest-guard cycle currently in flight. Overlapping concept ("cameras alone shouldn't call it a person"), but different tier (zone occupancy) and different code path (presence-tier zone aggregation). No file collisions; note in cycle memo.
- `docs/planning/PLANNING_v4.7.14_away_state_person_tracker_trust.md` (referenced from MEMORY) — the AWAY veto whose `unidentified_count == 0` predicate we impact. Read before build.
- `docs/reviews/code-review/` — search for `census`, `v5.9.0` reviews (D-A overcount / B-C1 dedup) so we don't undo those.

### 1.4 Memory bodies pulled

- `project_v4714_live.md` — away-state person-tracker veto lives on `unidentified_count == 0`. This cycle *strengthens* v4.7.14 (fewer false unidentifieds → cleaner AWAY convergence). Reviewer B must confirm no regression to v4.7.14 acceptance.
- `project_camera_signal_context_investigation.md` — durability/protect-vs-frigate audit context. Not a blocker but reviewer C should be aware.
- Operator memory on mitigation state: `census_hold_interior` was moved 15→3 min on 2026-07-13; changes take effect next restart. **The 3-min hold is a mitigation, not a fix.** This cycle addresses the root cause; the hold stays at 3 min after ship.

### 1.5 Design docs read

- `docs/Coordinator/PRESENCE_COORDINATOR.md` — target for the "how the census decides guest" explainer (deliverable D4). No dedicated census doc exists today; extending PRESENCE_COORDINATOR.md with a new "House Census & Guest Determination" section is the correct home. (Alternative — create `docs/Coordinator/CAMERA_CENSUS.md` — considered and rejected: fragments a coherent presence story.)

### 1.6 Bug-class alignment (`docs/QUALITY_CONTEXT.md`)

- **Bug Class #7 — Stale Data Source:** face_state.last_changed staleness handling — reuse existing pattern in `_get_unrecognized_camera_count`.
- **Bug Class #23 — Observation-mode gating:** N/A here (no shadow mode planned; this is a corrective refactor, guarded by tests).
- **Bug Class #53 — Computed-but-not-consumed:** central risk. If we compute the BLE-cancelled correction but only apply it in one of the two zone paths, we recreate the v5.9.0 D-A overcount incident. **Invariant test must prove the correction reaches the returned `CensusZoneResult.unidentified_count`.**
- **Bug Class #22 — Enum mismatch:** person_coordinator `location` is a room *slug*, `CameraInfo.area_id` is a HA area_id (uuid). Correlation MUST route through the same room↔area map person_coordinator already uses. Do NOT string-compare directly.

---

## 2. Problem statement (the gap, in prose)

The house census has two paths:

- **Raw path** (`_cross_correlate_persons`, lines 1213-1285): computes `unidentified = max(0, camera_total - len(face_ids | ble_ids))` at line 1248. This *implicitly cancels* residents whom BLE places at home even if their face wasn't recognized in the frame.
- **Enhanced path** (`_apply_enhanced_house_census`, lines 1956-2012, default ON): computes `camera_unrecognized` per camera by asking "did that specific camera's face sensor recognize someone in the last 30 min?" (`_get_unrecognized_camera_count`, lines 1652-1731). **It never consults BLE.** A resident whom BLE places at home — even in the same area as the camera — is invisible to the subtraction. The enhanced path then hands `unidentified_raw = camera_unrecognized` (line 1983) into hold/decay, arms the guest gate, and drives HouseState.

**Observed impact (live, 2026-07-12):** guest gate arms 2-4×/day with zero real guests. Interior cams involved: playroom×2, master_hallway, staircase, foyer_fisheye, family_room.

**The enhanced path lost a property the raw path had.** That is the story the code and this doc must tell.

---

## 3. Falsifiable invariant (Tier-2-DB required)

**Invariant I1 (soundness — guests still detected):**
> For any Frigate detection at time t on interior camera C, if the set of home residents (`person_coordinator.data` with `location ∉ {away, unknown, ""}`) has ZERO members whose `location` maps to `C.area_id`, AND no fresh face match on C, then C contributes its `person_count` to `unidentified_raw` — i.e. a genuine guest is NEVER cancelled.

**Invariant I2 (completeness — resident false-positives eliminated):**
> For any Frigate detection at time t on interior camera C, if AT LEAST ONE home resident's `location` maps to `C.area_id`, the count contribution from C to `unidentified_raw` is reduced by exactly `min(person_count, ble_home_in_area)`.

**Invariant I3 (arithmetic bound):**
> `unidentified_raw ≥ 0` and `unidentified_raw ≤ camera_total_unrecognized_without_ble_cancel` (correction is monotone-reducing; never inflates).

Reviewer D's sole job is to break I1 or I2 with a legal-config, reachable state.

---

## 4. Options analysis

### 4.1 Option A — Per-area BLE correlation (RECOMMENDED)

For each interior camera contributing to unrecognized, look up residents whose `person_coordinator` `location` maps to that camera's `area_id`; subtract up to `person_count` per camera.

**Pros:**
- Precise: preserves guest detection when a guest is in a *different* room from any BLE-known resident.
- Same shape as the existing `_dedup_by_area` grouping — natural fit.
- Explainable: "the resident's phone says they're in this room; the camera sees a person in this room; probably the same person."

**Cons:**
- Depends on `person_coordinator._area_id_to_room` correctness (already load-bearing for Bermuda room resolution).
- Room-slug ↔ area_id mapping edge cases (unnamed areas, rooms without cameras).

**Arithmetic — multi-person matrices (guest still counts):**

Let `pc` = person_count on camera C, `fresh_face` = 1 if fresh face match on C else 0, `ble_here` = number of home residents whose location maps to C.area_id.

Contribution formula (replacing lines 1719-1728):
```
face_covered = 1 if fresh_face else 0
raw_contribution = max(0, pc - face_covered)          # existing behaviour
correction     = min(raw_contribution, ble_here)      # NEW
contribution   = raw_contribution - correction
```

Matrix (illustrative — cite these in the review request):

| pc | fresh_face | ble_here | face_covered | raw_contrib | correction | final_contrib | Interpretation |
|---:|:-:|:-:|:-:|:-:|:-:|:-:|---|
| 1 | 0 | 1 | 0 | 1 | 1 | **0** | Resident alone, face missed — was FP, now cancelled |
| 1 | 1 | 1 | 1 | 0 | 0 | 0 | Resident, face matched — unchanged |
| 2 | 0 | 1 | 0 | 2 | 1 | **1** | Resident + guest, no faces — guest counted |
| 2 | 1 | 1 | 1 | 1 | 1 | **0** | Resident face-matched + one more (also resident? or guest?) — see caveat below |
| 2 | 0 | 2 | 0 | 2 | 2 | 0 | Two residents in room, neither face-matched |
| 3 | 0 | 1 | 0 | 3 | 1 | **2** | 1 resident + 2 guests — both guests counted |
| 1 | 0 | 0 | 0 | 1 | 0 | 1 | Pure guest / no resident BLE in area — DETECTED (I1) |
| 0 | 0 | any | 0 | 0 | 0 | 0 | No detection, no contribution |

**Caveat on row 4 (pc=2, fresh_face=1, ble_here=1):** the fresh-face-covers-one heuristic already subtracts one for the face; then we subtract one more for BLE. If the same person is both face-matched AND BLE-here, we double-count the cancellation and miss a *second* person (potential guest). This is a pre-existing weakness of the "face covers 1" simplification (line 1722), not one we introduce, but the plan must acknowledge it and reviewer A must review whether to change the formula to:

```
covered = min(pc, max(face_covered, ble_here) if same_person_likely else face_covered + ble_here)
```

Recommended treatment: keep `face_covered + ble_here` (over-cancels in the rare double-cover case) and add a **HIGH-severity known-limitation note** in code + PRESENCE_COORDINATOR.md. Real-world frequency is very low (fresh face AND BLE in same room for same resident) and the risk (missing a co-present guest) is bounded by the guest gate's other signals. Reviewer B is asked to challenge this trade explicitly.

### 4.2 Option B — Global clamp (raw-path mirror)

After computing `camera_unrecognized`, clamp:
```
unidentified_raw = max(0, camera_unrecognized - max(0, len(recognized_set) - identified_already_credited))
```
Simpler; mirrors line 1248 verbatim.

**Pros:** minimal code; one place; auditable against precedent.
**Cons:** loses the per-area precision. A resident in the kitchen cancels a guest in the foyer if both cameras fire simultaneously — I1 is violated.

### 4.3 Recommendation

**Option A (per-area).** It preserves I1, and the arithmetic parallels the existing `_dedup_by_area` grouping — same primitive, extended. Option B trades correctness for simplicity in a hierarchy where correctness = "did we correctly say a stranger is in the house."

Document Option B in the plan as the fallback we rejected, with the I1 counter-example. Reviewer C tests must include the "resident in kitchen + guest in foyer" case explicitly.

---

## 5. Deliverables & acceptance criteria

### D1 — Add per-area BLE-home lookup helper

**Change:** in `camera_census.py`, add:
```python
def _ble_home_by_area(self) -> dict[str | None, int]:
    """Return {area_id: count} of residents person_coordinator places at home.

    Consults person_coordinator.data; for each resident whose 'location'
    is a real room (not away/unknown/""), resolves that room slug back to
    an area_id via person_coordinator._area_id_to_room (inverse map).
    Residents whose room cannot be resolved to an area contribute to
    key None — they cannot cancel any camera.
    """
```
Use the existing `_area_id_to_room` cache on person_coordinator (invert once per call).

**Acceptance:**
- **Verify:** helper returns `{}` when person_coordinator is missing or has no data (graceful degradation, unit test).
- **Verify:** LOST/away residents are excluded (only home-located residents can cancel).
- **Test:** `test_ble_home_by_area_*` in `quality/tests/test_census_v2.py`.

### D2 — Wire cancellation into `_get_unrecognized_camera_count`

**Change:** replace lines 1719-1728 with the Option-A formula. Feed the per-area BLE map into the loop; correction is per-camera before `_dedup_by_area` collapses across areas.

Emit an INFO-level debug log per cancellation: `"BLE-cancel: camera=<eid> area=<aid> pc=%d ble_here=%d contribution=%d"`.

**Acceptance:**
- **Test:** matrix rows 1-8 from §4.1 as parametrized cases.
- **Test:** ordering — `_dedup_by_area` still receives area-tagged contributions; overcount v5.9.0 regression fixture (`test_census_overcount_v5_9_0.py`) still passes.
- **Verify:** `unidentified_raw` after correction is ≥ 0 (I3).

### D3 — Surface diagnostic attribute on house census sensor

**Change:** extend `CensusZoneResult` with `ble_cancelled_count: int = 0`; populate in `_apply_enhanced_house_census` (compute as sum of cancellations across cameras this cycle); surface on `sensor.ura_camera_census_house` as attribute `ble_cancelled_count`.

**Acceptance:**
- **Sensor:** `sensor.ura_camera_census_house` shows non-null `ble_cancelled_count` attribute.
- **Live:** attribute increments when a resident is in a camera area unrecognized; returns to 0 when they leave or are face-matched.

### D4 — Documentation deliverable (operator directive: "Document well")

**Change:** append a new section **"House Census & Guest Determination"** to `docs/Coordinator/PRESENCE_COORDINATOR.md`. Contents:
1. Two-path history: raw vs enhanced; why enhanced exists (v2 signal quality); what property was lost (BLE subtraction).
2. Current arithmetic (Option A formula) — copy the matrix from §4.1.
3. The v4.7.14 AWAY veto interaction and why this cycle strengthens it.
4. Known limitation: fresh-face AND BLE double-cover (row 4 caveat).
5. Where the guest gate consumes this (`presence.py:_guest_gate_armed`).
6. Explicit statement: "If you are re-investigating a 'phantom guest' complaint, start here." — with anchors.

**Acceptance:** doc section exists at ship; reviewer C confirms all anchors in it resolve.

### D5 — Test authority (Tier-2-DB C requirement — real per-site mutation)

Reviewer C MUST edit `_get_unrecognized_camera_count` in a scratch copy to remove the `correction` subtraction, run the suite, and confirm at least ONE specific test fails (the row-1 or row-3 case). Restore. Same for the `_ble_home_by_area` helper (return `{}` unconditionally → specific test should fail).

**Acceptance:** review C posts the two `2 failed` outputs and the test names.

### D6 — Pre-deploy row-rate snapshot

Snapshot 48h of `sensor.ura_presence_coordinator_presence_house_state` guest-gate arming events from the recorder before deploy. Query:
```sql
SELECT COUNT(*) FROM states
WHERE entity_id = 'sensor.ura_presence_coordinator_presence_house_state'
  AND state IN ('guest', 'occupied_guest', 'home_guest')  -- reviewer to confirm exact states
  AND created > datetime('now', '-48 hours');
```
Reviewer A validates the exact state values against `presence.py`.

### D7 — Live validation (Review D)

Post-deploy, within 48h:
| Criterion | Method | Pass condition |
|---|---|---|
| L1 — guest-gate arming rate drops | Recorder query above, 48h post vs 48h pre | ≥ 60% reduction in false arms (baseline 2-4/day → target ≤ 1/day on quiet days) |
| L2 — real-guest test | Operator invites one real guest; guest walks past foyer_fisheye WITHOUT phone-tracker | `ble_cancelled_count` unchanged; `sensor.ura_camera_census_house.unidentified_count` increments; guest gate arms within existing latency |
| L3 — resident-in-area cancellation observable | Watch `ble_cancelled_count` attribute; walk a resident through master_hallway | Attribute increments while resident there; returns to 0 after they leave |
| L4 — v4.7.14 AWAY veto not regressed | Empty-house evening: verify HouseState reaches AWAY without oscillation | Same or better dwell than v4.7.14 baseline |
| L5 — no census overcount regression | `sensor.ura_camera_census_house.total_persons` under stress (multiple cameras firing) | Never exceeds physical count present |

README write-back MANDATORY per CLAUDE.md — replace L1-L5 prospective bullets with observed evidence.

---

## 6. The three Tier-2-DB review framings

- **Review A — Census arithmetic correctness (per-cam + multi-person matrices).** Prove I2 and I3. Walk every row of the §4.1 matrix against the code. Confirm row-4 caveat is documented. Confirm ordering with `_dedup_by_area` is correct. Confirm units: `person_count` is int, `ble_here` is int, subtraction sign is right.
- **Review B — Cross-coordinator ripple + hold/decay interaction.** Trace the impact through `_apply_hold_decay` → `_apply_enhanced_house_census` → `CensusZoneResult` → house census sensor → `presence._guest_gate_armed` → `HouseState` → HVAC preset / NM guest-arrival announces / anomaly emissions. Confirm v4.7.14 AWAY veto still fires and only fires when it should. Confirm no double-emit or missed-emit under restart. Confirm the person_coordinator ↔ camera_census read is safe wrt person_coordinator boot order (graceful degradation when person_coordinator not yet loaded — invariant: no cancellation is applied).
- **Review C — Test authority via real per-site source mutation + adversarial completeness.** Perform the D5 mutation. Additionally, re-grep `unidentified` / `guest` / `camera_unrecognized` / `_apply_enhanced_house_census` across the repo to enumerate ALL emission and consumption sites; confirm each is covered. Break I1 with a legal config.

Run in parallel. Different framings must not converge.

---

## 7. Rebase & concurrency discipline

- `camera_census.py`, `person_coordinator.py`, `const.py`, `sensor.py`, `presence.py` — the three concurrent cycles do NOT modify `camera_census.py`. However, `presence.py` and `sensor.py` are hot surfaces.
- Before build: `git fetch origin && git rebase origin/develop`.
- After build: re-run rebase before requesting the three parallel reviews.
- Deploy from `develop` per the "deploy from develop" durable rule.

---

## 8. Plan-completion tracking

Items DEFERRED / NOT planned in this cycle (document explicitly, do not silently drop):

- **Row-4 double-cover fix (formula sharpening).** Deferred to a follow-up if L2/L3 live data shows it manifesting. Known-limitation note lands in code + PRESENCE_COORDINATOR.md now.
- **Property-zone (exterior) BLE-cancel.** `_apply_enhanced_property_census` is out of scope — exterior cameras' "unrecognized" semantics differ (delivery drivers, passers-by legitimate). Track as a separate cycle if operator wants it.
- **Refactor to unify raw + enhanced paths.** Attractive but risky; tackle after this cycle stabilizes.
- **CONF for enable/disable.** Explicitly rejected in §1.2 — not a knob, it's a bug-fix.

---

## 9. Open operator questions

Only truly undecidable items — everything else the planner decided in-doc:

1. **Row-4 double-cover — accept known limitation or expand scope?** Recommendation: accept + document. Confirm.
2. **L1 target reduction threshold — 60% is the planner's guess based on the 2-4/day baseline; is that the operator's bar for "shipped working"?** Or should we require ≥ 80% reduction before closing the cycle?

(All other decisions — Option A over B, no CONF flag, PRESENCE_COORDINATOR.md as the doc home, no new sensor entity, no new signal — are made by the planner and stand unless the operator overrules.)
