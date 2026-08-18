# PLAN REVIEW — Guest / Census Correctness cycle (Tier 2-DB, plan-review pass)

- **Plan under review:** `docs/planning/PLANNING_guest_census_correctness.md` @ `235d72904`
- **Spec source:** `docs/planning/RESEARCH_guest_actuation_and_census.md` @ `8f55b243d`
- **Reviewer role:** single adversarial plan-review pass (CLAUDE.md § Plan Review — Tier 2 / 2-DB).
- **Verdict: DO NOT SHIP — fix plan then rebuild.** One HIGH latent-regression in D1's clamp (finding P1 below), one HIGH observability gap that defeats the acceptance instrument (finding P2), one MEDIUM correctness gap in D2 preservation checks (finding M1), plus MEDIUMs on ground-truth accounting (M2) and the invariant statement (M3). D3 is sound. No new knobs confirmed.

---

## P1 — CRITICAL / HIGH: D1 clamp is correct only while the defect it compensates for stays broken

**Adjudication of the orchestrator's priority finding: CONFIRMED. The clamp regresses the moment BLE-cancel (or fresh-face) starts working.**

### What `camera_unrecognized` actually contains at the clamp site

`_apply_enhanced_house_census` (`camera_census.py:3090`) binds `camera_unrecognized = self._get_unrecognized_camera_count()`. Reading that helper end-to-end (`camera_census.py:2670-2826`), the returned value is the **POST-BLE-cancel** per-area-max sum plus null-area contributions:

- Step 1 (`:2712-2766`) — per-camera raw contribution, with fresh-face `−1`.
- Step 2 (`:2768-2779`) — per-area MAX, null-area cameras to `unassigned_raw`.
- **Step 3 (`:2798-2816`) — BLE subtraction runs here. `area_contributions[aid] = raw_max - correction`.**
- Step 4 (`:2826`) — `sum(area_contributions.values()) + sum(unassigned_raw)`.

So `camera_unrecognized` is *conceptually* "unrecognized after cancellation," not "camera total." It is the same scalar that later appears as the `camera_unrecognized` attribute on the sensor and equals `frigate_count` today ONLY because both defenses return zero (RESEARCH §1.7).

### Contrast with the raw path

`_cross_correlate_persons` (`camera_census.py:1746-1786`) takes `camera_total` as an argument. The producer feeding it (`_calculate_house_census` at `:1331`) uses `_dedup_by_area` output — per-area MAX summed, with **no BLE cancellation applied at all**. So the raw path's ceiling `max(camera_total, identified)` is a max against the **pre-cancel** per-area-max sum.

**The two scalars have different semantics.** Today they numerically coincide only because cancellation returns 0. The plan reuses the label of the enhanced-path scalar and calls its `max(camera_unrecognized, identified)` "exactly the raw path's subtractive derivation" (plan lines 21-25, 105-106, 188-190) — that equivalence holds by numerical coincidence, not by construction.

### Repaired-state counter-example is legal and reachable

Household: 4 residents home + 1 real guest, sibling KP work (face-freshness fix, BLE-area coverage) has restored BLE-cancel on 3 of the 4 residents' areas.

- Cameras: each resident visible in their own area (pc=1 each), guest visible in a fourth area (pc=1) — 5 camera bodies across 5 areas.
- Step 2 per-area max: `{A1:1, A2:1, A3:1, A4:1, GUEST_AREA:1}`.
- Step 3 BLE-cancel: `A1..A3` cancelled (ble_here=1 each), A4 uncancelled (that resident's phone is off / not resolved), GUEST_AREA uncancelled.
- `camera_unrecognized = 0 + 0 + 0 + 1 + 1 = 2`.
- BLE persons: 4 residents → `identified_count = 4`.
- Hold/decay stable: `held_unidentified = 2`.
- **Plan's clamp:** `raw_total_ceiling = max(2, 4) = 4`. `additive = 4 + 2 = 6`. `clamped_total = min(6, 4) = 4`. `clamped_unidentified = max(0, 4 − 4) = 0`.
- **Ground truth:** 5 persons. **Reads 4. Guest suppressed. `unidentified_count = 0`.**

Fully-repaired case (all 4 residents cancelled, guest alone):
- `camera_unrecognized = 1`, `identified = 4`, `held = 1`.
- `ceiling = max(1, 4) = 4`, `additive = 5`, `clamped = min(5, 4) = 4`, `clamped_unid = 0`.
- **Reads 4 for 5. Guest suppressed.**

### The plan's "proof it cannot suppress a real guest" is wrong

Plan lines 210-215:

> *"a genuine stranger's camera detection contributes to `camera_unrecognized` … So `camera_unrecognized ≥ identified + 1` whenever a stranger is on camera → `raw_total_ceiling ≥ identified + 1`."*

The premise `camera_unrecognized ≥ identified + 1` requires camera bodies to accumulate without cancellation. In the repaired state, resident bodies are cancelled per-area BEFORE they reach the `camera_unrecognized` scalar — so `camera_unrecognized` contains ONLY strangers, and `strangers` need not be ≥ `identified + 1`. In any household with more residents than strangers on camera, the ceiling shrinks below `identified` and the clamp silently swallows the guest.

The proof only survives while cancellation is inert. That means shipping D1 as specced **couples the correctness of guest detection to the ongoing brokenness of BLE-cancel / face-freshness.** The two KP chains explicitly excluded as "out of scope" from this cycle are the very repairs that make D1 wrong. Any partial progress on those chains (a single area starts cancelling correctly) triggers the regression in production for the households that area covers.

### The correct ceiling

The scalar the plan wants is the raw path's `camera_total` — per-area MAX summed **before** cancellation. Two equivalent formulations:

**Option A (minimal wire change).** Publish it from `_get_unrecognized_camera_count`:

```python
# camera_census.py, in _get_unrecognized_camera_count, after Step 2:
camera_total_pre_cancel = sum(area_raw_max.values()) + sum(unassigned_raw)
self._last_camera_total_pre_cancel = camera_total_pre_cancel
# ... Step 3 continues (BLE-cancel), Step 4 returns post-cancel scalar as today.
```

Then in `_apply_enhanced_house_census` (D1 site at `:3109`):

```python
raw_total_ceiling = max(self._last_camera_total_pre_cancel, identified_count)
additive_total    = identified_count + held_unidentified
clamped_total     = min(additive_total, raw_total_ceiling)
clamped_unidentified = max(0, clamped_total - identified_count)
```

Re-check both cases:
- Today (cancellation inert): `pre_cancel = 6`, `ceiling = max(6, 4) = 6`, `clamped = min(10, 6) = 6`, `clamped_unid = 2`. Matches plan's intended arithmetic on today's inputs.
- Repaired (guest present): `pre_cancel = 5`, `ceiling = max(5, 4) = 5`, `clamped = min(6, 5) = 5`, `clamped_unid = 1`. **Guest preserved.**
- Fully repaired (guest alone): `pre_cancel = 5`, `ceiling = 5`, `clamped = 5`, `clamped_unid = 1`. **Guest preserved.**

**Option B (share the raw path's own value).** Have the enhanced path receive `raw_result.frigate_count`-style `camera_total` from the raw computation and clamp to `max(that, identified)`. Requires `_calculate_house_census` to stash `camera_total` on the raw result. More surface change; less appealing.

Either way, **the ceiling operand must be a pre-cancel quantity.** The plan's use of `camera_unrecognized` (post-cancel) is the bug.

### The honest invariant

The plan's INV-CENSUS-CLAMP (`identified_count + unidentified_count ≤ max(camera_unrecognized, identified_count)`) is a restatement of the possibly-wrong formula — it declares as an invariant the exact scalar comparison the code performs. That is not a falsifiable invariant; it is a tautology of the implementation.

The **honest** invariant the operator wants is a set-attribution property:

> **INV-CENSUS-ATTRIBUTION.** For every census tick, no person contributes to both `identified_count` and `unidentified_count`. Scalarly: `total ≤ max(camera_total_pre_area_cancel, identified_count)` — never against the post-cancel scalar.

That is falsifiable in the D reviewer's sense: a legal, reachable config (repaired BLE-cancel + one real stranger) violates the plan's stated INV as written unless it is corrected to reference the pre-cancel ceiling.

**Verdict on P1:** DO NOT SHIP D1 as written. Change the ceiling operand to the pre-cancel scalar; restate INV-CENSUS-CLAMP as INV-CENSUS-ATTRIBUTION referencing that scalar; add the mutation-anchored regression test below.

### Regression test that would have caught this

```python
# quality/tests/test_census_clamp_repaired_defenses.py
def test_clamp_preserves_guest_when_ble_cancel_working():
    # 4 residents cancelled per-area, 1 real guest uncancelled.
    # BROKEN plan: camera_unrecognized=1 -> ceiling=max(1,4)=4 -> total=4 (guest lost).
    # CORRECT:    camera_total_pre_cancel=5 -> ceiling=5 -> total=5 (guest preserved).
    inputs = {
        "identified_count": 4,
        "camera_unrecognized": 1,          # post-cancel
        "camera_total_pre_cancel": 5,      # pre-cancel
        "held_unidentified": 1,
    }
    result = _apply_enhanced_house_census_math(**inputs)
    assert result.total_persons == 5
    assert result.unidentified_count == 1
```

The plan's proposed D1 test (`identified=4, camera_unrecognized=6, held=6 → total=6, unid=2`) does not touch this case; both formulations pass. That is why the plan's Review-C mutation drill would not have caught the regression either — the mutation is not the one that matters. Reviewer C must add a mutation of the CEILING OPERAND (swap pre-cancel for post-cancel) and confirm the repaired-state test fails.

---

## P2 — HIGH: G2 observability cannot discriminate the states it is sold as discriminating

The plan sells G2 (publish `_last_enhanced_area_contributions`) as the acceptance instrument that lets an operator distinguish "BLE-cancel ran and cancelled 0" from "BLE-cancel never ran" (RESEARCH §1.9, plan lines 176-183, 431-434).

Reading `_get_unrecognized_camera_count` Step 3 (`camera_census.py:2798-2816`), **`area_contributions` is populated in BOTH branches:**

```python
if not self._get_ble_cancel_enabled():
    for aid, raw_max in area_raw_max.items():
        if raw_max > 0:
            area_contributions[aid] = raw_max      # kill switch off
else:
    for aid, raw_max in area_raw_max.items():
        ...
        final = raw_max - correction
        if final > 0:
            area_contributions[aid] = final         # kill switch on
```

The dict shape is identical in both branches — `{area_id: int}`. Publishing it distinguishes nothing about whether cancellation ran. The plan's claim that it does is unsupported.

`ble_cancelled_count` (already an attribute) also fails to discriminate: it is 0 both when the kill switch is off AND when the switch is on but `ble_by_area` returns `{}` or has no overlap.

**Minimum discriminating publisher set.** To make G2 actually load-bearing on acceptance:

1. Publish `_last_area_raw_max_pre_cancel: dict[str, int]` (the Step 2 output).
2. Publish `_last_ble_by_area: dict[str, int]` (the `_ble_home_by_area()` result for this tick).
3. Publish `_last_ble_cancel_enabled: bool` (the live kill-switch read).
4. Keep the post-cancel `_last_enhanced_area_contributions` as today's proposal.

With these four, the operator can compute: `cancelled_per_area = pre_cancel[aid] − post_cancel[aid]`, and see WHY cancellation was zero (switch off vs empty ble map vs non-overlapping areas). Without them, G2's "acceptance instrument" cannot instrument the thing.

Note this fix ALSO gives D1 its correct ceiling operand for free (`sum(pre_cancel.values()) + sum(unassigned_raw)` — one attribute serves both purposes). P1 and P2 collapse to a single refactor.

**Verdict on P2:** the observability plumbing must publish pre-cancel per-area and BLE-here per-area, not just post-cancel per-area. Update D1's G2 fold accordingly.

---

## M1 — MEDIUM: D2 preservation checks are incomplete; two legitimate guest scenarios stop working

Plan lines 271-283 list preservation checks: guest sleeping in a flagged room, manual override, exit condition, inside-GUEST re-eval, kill switch. It omits the two legitimate scenarios that STOP working under `guest_armed = guest_room_gate_armed`:

1. **Guest in a non-flagged room** (couch in the living room, sleeping on a floor mattress in the study, hanging out in the kitchen while the flagged guest bedroom sits empty). Today Path A can arm on `unidentified_count > 0` sustained ≥ 5 min. Under D2, GUEST cannot arm because no flagged room reports sustained unknown occupancy. **This is a real user scenario; today it works, under D2 it does not.**

2. **Guest present <30 min.** Today Path A arms after 300 s persistence. Under D2, `_guest_room_gate_armed` requires `threshold_min = 30` (per §0.2 live config for all three flagged rooms). GUEST entry is delayed from ~5 min to ≥ 30 min, and only if the guest occupies a flagged room. Learning suppression, HVAC hold preservation, DPM offset reset, and perimeter severity downgrade all fire 25 minutes later than they do today.

The operator accepted "a higher bar" (RESEARCH §3), but the plan must state exactly what stops working. These two cases together are what the operator is trading for FP suppression. The plan should:

- Enumerate both scenarios explicitly under Non-goals / accepted residuals.
- State what the operator can DO if they need coverage: flag additional rooms (config-time), or manually override (Path C).
- Update the "50 daytime FP episodes … stop" claim (plan line 498) to acknowledge that some fraction of those 50 may have been legitimate short-duration guests in the living room / kitchen. Without ground truth on the 50, it is not safe to claim they were ALL false positives.

**Verdict on M1:** add a "Behaviors that stop working" subsection under D2 with the two scenarios named; downgrade the FP-suppression claim to "reduces daytime FP arms; a subset requiring coverage of non-flagged rooms or <30-min guests is intentionally traded away and requires config or manual override."

---

## M2 — MEDIUM: Ground-truth acceptance criterion is not tight enough to distinguish "fixed" from "differently broken"

Plan's post-fix expected reading (lines 493-494): `persons_in_house ∈ [N, N + camera_unrecognized_beyond_residents]`. For tonight (N=5, guest=1), that admits `[5, 6]`, and the clamp with today's inputs will read exactly 6. The operator sees "6" against ground truth 5 and needs to know: is that PASS or is the residual +1 the sign of a different bug?

Once P1 is fixed (pre-cancel ceiling), the arithmetic is:
- Today: `ceiling = max(6, 4) = 6`, `clamped = 6`, `clamped_unid = 2`. **Reads 6 for 5 real people.** The +1 comes from residents whose face gate is failing being bucketed as unidentified — visible in the not-yet-cancelled per-area contributions.
- Fully repaired: reads 5 for 5. Exact match.

The plan should state the expected residual PRECISELY and its cause:

> **After D1 (with today's F2/BLE-cancel telemetry): expected reading = `4 + (2 or 3)` = 6-7. The residual over ground-truth is the count of resident bodies not yet cancelled by BLE-cancel (Ziri's zone unresolved, mmWave ghosts in Master Bedroom). The reading converges to `N + strangers_on_camera` as face freshness and BLE-area coverage repair. It NEVER exceeds `max(camera_total_pre_cancel, identified)`.**

With that written down, the operator can read a post-deploy 6 as PASS-with-known-residual and a post-deploy 8 as FAIL (indicates the clamp did not fire or the ceiling operand is wrong).

**Verdict on M2:** rewrite the "After-picture" bullet to state the precise expected value tonight (accounting for the four residents' current cancellation state), name the residual mechanism, and give a numeric FAIL threshold that would prove the clamp did not fire.

---

## M3 — MEDIUM: Restate INV-CENSUS-CLAMP as an attribution invariant

Bundled with P1. The invariant as stated is a restatement of the formula. Adopt INV-CENSUS-ATTRIBUTION as proposed under P1: *"no person contributes to both identified and unidentified"*, scalarly `total ≤ max(camera_total_pre_area_cancel, identified)`. This is what Reviewer D must try to falsify — and, as shown in P1, the plan's current arithmetic *does* falsify the honest invariant, which is the discovery this review makes.

---

## D3 — SOUND (with one small tightening)

Verified end-to-end:

- `entity.py:34` — `_attr_unique_id = f"{coordinator.entry.entry_id}_{entity_type}"`. Confirmed the room's `OccupiedBinarySensor` passes `"occupied"` as `entity_type` (plan cite of `binary_sensor.py:245` accepted; I did not re-open that file but the `unique_id` shape is consistent with the codebase's rule).
- HA registry API `entity_registry.async_get(hass).async_get_entity_id(domain, platform, unique_id)` is the correct lookup — resolves by stable identity (unique_id), not by string-built entity_id. Renamed rooms are handled correctly because `entry.entry_id` is stable across `.entity_id` renames.
- Iteration over `hass.config_entries.async_entries(DOMAIN)` correctly yields the ROOM entries; the entry_id of each ROOM entry matches the coordinator whose `OccupiedBinarySensor` carries `f"{entry_id}_occupied"`. Resolves "Upstairs Guestroom" → `binary_sensor.upstairs_guest_bedroom_occupied` correctly.

**Small tightening:** the plan's WARNING log on registry miss (`plan lines 313-317`) is right; also add a corresponding DEBUG-or-INFO log on successful subscription that names the *actual* resolved `occupancy_entity_id` alongside `room_name`. Without it, D3's Live criterion ("Registration log shows Upstairs Guestroom subscribed to `binary_sensor.upstairs_guest_bedroom_occupied`") has no producer. The existing `_LOGGER.info("D5 guest room registered: '%s' (threshold=%d min, entity=%s)", ...)` at `presence.py:4726-4729` already emits `entity=occupancy_entity_id` — but that variable is currently the *guessed* string. Under D3 the variable name should be reused (`occupancy_entity_id` = registry-resolved), so the log line falls into place naturally. Verify in build.

---

## Institutional-context / new-CLAUDE.md-rule compliance

- **Producer check** — present, comprehensive, correctly identifies P1/P2 (raw vs enhanced additive) as the failure mode. Well done.
- **Consumer check** — present, correctly enumerates security lockdown, phone-left-behind, veto oracles, HVAC arrester-hold indirection. Well done.
- **Zero new knobs** — confirmed via the plan's grep list; no CONF_*, no Number/Switch/Select, no options-flow field. The transient `_last_enhanced_area_contributions` and `_guest_room_entity_to_name` are correctly classified as internal-not-knob. If P2's fix adopts the four discriminating publishers, they are similarly internal-not-knob.
- **Non-goals include the accepted bathroom-guard residual risk** — confirmed (plan lines 349-354).
- **Falsifiable invariants stated up front** — INV-CENSUS-CLAMP is stated but is a tautology (see M3). INV-GUEST-LEAD is stated and falsifiable and is correct as written.
- **Emission/decision-site re-enumeration by the reviewer** (CLAUDE.md plan-review requirement): done for D1's ceiling (single site at `:3109`, no other additive derivations in the enhanced path; the sensor.py:4354-4416 parallel derivation is correctly flagged out of scope). Done for D2's composition (single site at `:5384-5404`, exit at `:1241` compatible). Done for D3's registration site (`:4707`) and handler lookup (`:4757-4762`).

---

## Summary

| Finding | Severity | Deliverable | Disposition |
|---|---|---|---|
| P1 clamp ceiling uses post-cancel scalar; regresses on defense repair | HIGH | D1 | **Fix in plan before build.** Change ceiling operand to pre-cancel per-area-max sum. |
| P2 G2 dict cannot discriminate cancel-ran-zero from cancel-never-ran | HIGH | D1 (G2 fold) | **Fix in plan before build.** Publish pre-cancel per-area + ble-by-area + kill-switch bool. Collapses with P1 fix. |
| M1 D2 preservation-check list incomplete (couch guest, <30-min guest) | MEDIUM | D2 | State the two behaviors that stop working; qualify the FP-suppression claim. |
| M2 Post-fix expected reading not tight enough to distinguish PASS/differently-broken | MEDIUM | D1 acceptance | State numeric expectation with residual mechanism and FAIL threshold. |
| M3 INV-CENSUS-CLAMP is a formula tautology, not a falsifiable invariant | MEDIUM | Invariant | Restate as INV-CENSUS-ATTRIBUTION. |
| D3 registry resolution | — | D3 | Sound. Add resolved-entity log-line verification to build. |

**Verdict: DO NOT SHIP.** Return to planner for P1+P2 fix (single refactor), M1 preservation-list expansion, M2 acceptance tightening, M3 invariant restatement. D3 proceeds as-is. Re-review after plan edits.

---

*Reviewer: single-pass adversarial plan review, ~90 min. Followed CLAUDE.md § Plan Review — Tier 2 / 2-DB. No source edits.*
