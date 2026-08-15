# Plan Review — CIRCLING-LABEL-1 (Option A, Tier 2)

**Plan:** `docs/planning/PLANNING_circling_label_transition_dispatch.md`
**Branch:** develop
**Framing:** adversarial single plan review (Tier 2 policy — one pass before build dispatch); greps re-run independently, XCORR-1 read end-to-end.
**Verdict:** **FIX-PLAN-FIRST** — one HIGH finding (XCORR-1 adjudication is wrong-mechanism and leaves a real reachable single-camera-night demote path unaddressed), one MED (missing import in helper snippet), plus MED/LOWs below. Fixes are small and confined to the plan doc; no design pivot required.

---

## 1. Institutional-context re-verification

### 1a. Cooldown gate site
- Plan cites `perimeter_alert.py:1053-1065` for the cooldown gate.
- Re-grep + read of current develop: cooldown block occupies **`:1049-1065`** (the `# --- 3. ...` comment starts at 1049; `_last_alert` lookup at 1054; `return` at 1065). **Plan is accurate** — one gate, one consumer of `PERIMETER_ALERT_COOLDOWN_SECONDS` at :1057, single-site change is correct.
- `note_alert_dispatched` call at `:1424` inside the `dispatched_ok` branch (:1406) — confirmed. The plan's ledger-update block is correctly placed.

### 1b. Independent enumeration of dispatch-suppression sites on the perimeter path (person leg)
Re-greped every early-return in `_async_handle_perimeter_trigger` (~ :930-1450). Suppression sites, in order:

| # | Site | Nature | Interacts with exemption? |
|---|---|---|---|
| S1 | Alert-hours gate (upstream of cooldown) | Whole-flow suppress | Exemption fires DOWNSTREAM of this — irrelevant. |
| S2 | Egress-window suppression (:1032-1047) | Whole-flow suppress | Downstream of egress → exemption never runs after egress → **no interaction** (correct; exemption should NOT reopen egress-suppressed events). |
| S3 | Per-camera cooldown (:1049-1065) | **The gate the exemption targets.** | Plan replaces with two-step gate. ✓ |
| S4 | In-flight guard (:1067-1079) | Concurrency guard | Runs AFTER cooldown per current source. **Plan does not discuss this ordering.** See finding LOW-1: an exemption-permitted alert still hits S4; if a same-camera dispatch is in flight, the exemption-permitted second dispatch is suppressed. That's the correct behavior (one-in-flight per camera), but the plan should call it out so the builder doesn't naively move the exemption around it. |
| S5 | XCORR-1 burst-demote (:1213-1239) | Demote (not silence) | See §3 adjudication — real interaction. |
| S6 | NM safeword window (`_perimeter_silence_until`, NM :1468-1488) | Silent NM-side suppression, dispatched_ok remains True | Plan I3 handles this by short-circuiting BEFORE the exemption fires. ✓ |
| S7 | NM dedup (:1490-1494) | Silent dedup, sets counter | Plan does not discuss. Exemption dispatch on hop 3 has classification change → title/message potentially identical to hop 1 → **could dedup**. See finding MED-2. |
| S8 | NM DND / other NM gates (downstream of dedup) | Silent | Not exemption-specific; existing behavior. |

**Finding: 2 suppression sites (S4, S7) not discussed by the plan** but reachable on exemption-permitted events. S4 is arguably fine as-is; S7 needs adjudication.

### 1c. `_perimeter_silence_until` reach
Verified NM field lives at `notification_manager.py:387`. NM's suppression path (:1452-1488) does what the plan says (returns without raising, sets `_perimeter_silence_suppressions`, does NOT touch queue). Plan's I3 correctly reads this.

**Missing import (MED-1).** The plan's `_classification_transition_exemption_permitted` snippet calls `is_life_safety_hazard(self.hass, NM_HAZARD_EXTERIOR_PERSON)`, but a re-grep of `perimeter_alert.py` shows **`is_life_safety_hazard` is NOT imported** (`NM_HAZARD_EXTERIOR_PERSON` IS imported at :92). Builder must add `from ._nm_cycle_a import is_life_safety_hazard` (mirroring NM's own :146). The plan should state this so the builder doesn't ship a NameError or, worse, catch the NameError in the outer `try` and silently return False (which would look like "exemption never fires under safeword" — passing D4 for the wrong reason).

---

## 2. Falsifiable-invariant walk-through (I1-I4)

Constructed the lifecycle `pass_by → approach → circling → approach → circling` and traced plan behavior at each hop (all same camera, cooldown active throughout):

| Hop | classify | last | last_rank | current_rank | current ∈ set | Exemption? | Ledger after |
|---|---|---|---|---|---|---|---|
| 1 | pass_by | None | -1 | 0 | no | **N/A (cooldown allows first)** — baseline dispatch; ledger update → last=pass_by, set={pass_by} | last=pass_by, set={pass_by} |
| 2 | approach | pass_by | 0 | 1 | no | **YES** (escalation, not in set, no safeword). Dispatch. Ledger → last=approach, set={pass_by, approach} | last=approach, set={pass_by, approach} |
| 3 | circling | approach | 1 | 2 | no | **YES**. Dispatch (HIGH). Ledger → last=circling, set={pass_by, approach, circling} | last=circling, set={pass_by, approach, circling} |
| 4 | approach | circling | 2 | 1 | approach ∈ set | Two blockers: current_rank(1) <= last_rank(2) → I2 blocks; also I4 would block. **NO.** | unchanged |
| 5 | circling | circling | 2 | 2 | circling ∈ set | I4 blocks (`current in set`). Also I2: current_rank(2) <= last_rank(2). **NO.** | unchanged |

I1 holds (2 escalations → 2 exemption dispatches). I2 holds (hop 4 downgrade → no dispatch). I4 holds (each target-class fires once). ✓

**Ambiguity a builder could get wrong (LOW-2).** The plan uses `_CLASSIFICATION_RANK.get(current, -1)`. An unknown classification (e.g. a future "loiter" label, or `None`) gets rank -1, matching an `None`-last (rank -1) — I2 predicate is `current_rank <= last_rank`, so -1 <= -1 → **exemption blocked** (safe). Good. But a builder porting to a language with `>=` semantics could invert this. Plan should assert the strict `<=` boundary in a helper docstring so a review-round mutation `<= → <` is provably load-bearing.

**Ambiguity for I4 (LOW-3).** Plan I4 fires once per `(track, target_classification)`. Walk-through step 4: track downgrades to `approach` (already in set) and then re-escalates on hop 6 to `circling` (already in set). Set-membership blocks. Correct per I4. But the plan should state explicitly whether the intent is "at most one HIGH page per track EVER" or "at most one per (target class × track) pair" — because with vocabulary `{pass_by, approach, circling}` and severity-map `home_day` (approach ≈ MEDIUM, circling ≈ HIGH), a track that oscillates approach ↔ circling ↔ approach ↔ circling produces exactly ONE HIGH page. That is what I4 says. Plan says the same. Explicit consistency check passed; noting as LOW because a reviewer will want to see the assertion pinned in a test (D3 tests only the founding shape; add a `test_reescalation_after_downgrade_gets_no_new_exemption`).

---

## 3. XCORR-1 adjudication (operator ask #3) — **HIGH FINDING**

**Read `_evaluate_burst_demotion` at `perimeter_alert.py:1822-1936` end-to-end.**

Decision order in `_evaluate_burst_demotion`:
1. `PERIMETER_BURST_DEMOTE_ENABLED` — `True` in const.py :1436.
2. **`PERIMETER_BURST_NIGHT_ONLY` guard — `True`, window `(23, 5)` from const.py :1448/:1458.** If not in `[23:00, 05:00)` → **`return False, reason="outside_night_window"`**.
3. `prior_alerts_in_window` must be ≥ `MIN_ALERTS-1` = 1, else `first_alert`.
4. `sibling_corroborated` — different-engine fire on this camera → `return False`.
5. `adjacent_activity` via `linker.has_recent_adjacent_activity(cam_key, window_s, now)` → `return False, reason="adjacent_activity"`.
6. Else demote.

### 3a. Plan's stated prediction is wrong-mechanism.
Plan §Grep #7 and §Open build-time finding assert *"burst-demote will fire — but the coercion RAISE branch runs FIRST and has already raised severity to HIGH"* and reasons through the RAISE/demote interaction. **This is not how XCORR-1 short-circuits.** The RAISE branch in §4b is a severity-map coercion that mutates `severity` before XCORR-1 runs, but it does not stop XCORR-1 from running. XCORR-1 either exits via guards 2/3/4/5, or demotes down to LOW regardless of the pre-XCORR-1 severity value (line 1219: `new_sev = max(Severity.LOW, min(severity, Severity.LOW))` is literally `LOW`).

### 3b. Correct adjudication of the founding-case scenario (2-camera daytime `home_day`, ~09:22 CDT).
- Guard 2 (NIGHT_ONLY): 09:22 CDT is not in `[23, 5)` → `in_hours=False` → **`return False, reason="outside_night_window"`**.
- **XCORR-1 no-op. Exemption dispatch's severity survives at HIGH.** ✓ Founding-shape acceptance is met.

The RAISE branch is irrelevant to XCORR-1's decision. Plan D5's pin (`severity_after == "HIGH"`) will pass, but the plan's stated *reason* for it passing is wrong. The D5 test should still be built — it usefully protects against future `PERIMETER_BURST_NIGHT_ONLY` flips or `PERIMETER_BURST_NIGHT_WINDOW` retunes.

### 3c. Correct adjudication of the founding-case scenario at night (`home_night`, e.g. 02:00, cross-camera hops).
- Guard 2 passes (in night window).
- Guard 3: prior=1 on `back_yard` (hop 1) — passes.
- Guard 4 (sibling): typically no — passes.
- **Guard 5 (adjacent_activity): hop 2 fired on `front_side_ptz`, which IS adjacent to `back_yard` per `EXTERIOR_ADJACENCY_GRAPH`. `linker.has_recent_adjacent_activity("back_yard", 1800s, now)` → True → `return False, reason="adjacent_activity"`.**
- **XCORR-1 no-op. Exemption dispatch's severity survives at CRITICAL.** ✓

### 3d. Reachable failure path the plan does NOT cover.
**Single-camera nighttime circling exemption.** Sequence: `back_yard, back_yard, back_yard` (person circles ONE camera, plausible operational shape especially at edges of the property), at ~02:00 (`home_night`).
- Hop 1 (`back_yard`): baseline cooldown allows → dispatch (CRITICAL by contextual). Ledger → last=pass_by.
- Hop 2 (`back_yard`, cooldown-blocked): no dispatch. classify may already be `approach` (revisit_count=1) → escalation could fire exemption. **Assume it does** → dispatch. XCORR-1 with prior=1 (hop 1), no sibling, no adjacent (only camera involved is back_yard) → **DEMOTE fires → LOW**.
- Hop 3 (`back_yard`): classify=circling → escalation over `approach` (in set? approach was added) → I4 blocks (approach in set… wait, this checks CURRENT class). current=circling not in set → escalation → exemption fires → dispatch. Same XCORR-1 conditions → **DEMOTE → LOW**.

**Result: the operator's founding ask ("the hop where circling forms produces one HIGH page") is UNMET for single-camera-night tracks.** The exemption produces a LOW page in this shape — arguably worse than no exemption, because operator sees noise without the "circling" signal.

### 3e. Recommendation — MUST resolve before build dispatch.
The plan's own §Open build-time finding punts this to the builder. That is inappropriate for a Tier-2 plan (planner should resolve, builder should implement). Options:

- **Option (i) [preferred, minimal]:** Extend the exemption to teach XCORR-1 to skip demote when the flow used the exemption AND `classification in {"approach", "circling"}`. Concretely: set `self._exemption_active = True` on the current dispatch's local scope, thread it into `_evaluate_burst_demotion` as an early-return short-circuit. One extra branch, mutation-anchorable in Reviewer A.
- **Option (ii):** Add D5b test for single-camera-night, ACCEPT the demote, document as known limitation (single-camera nighttime circling exemption produces a LOW page). Cheaper but semantically inconsistent with founding ask.
- **Option (iii):** Rework the plan to raise the classification signal at the NM layer independent of severity (title metadata carrying `"[CIRCLING]"` prefix even at LOW). Bigger scope than Option A allows.

Recommended: **Option (i)**, since it's a 3-line change with a mutation-anchorable drill and preserves the founding ask across shapes. Plan must be updated to:
1. State the single-camera-night scenario explicitly under §Adjudicated ask 4 (currently only cross-camera + RAISE-branch reasoning).
2. Add D5b (`test_exemption_dispatch_survives_xcorr1_single_camera_night`) — same-camera oscillation at night, assert `severity_after == "CRITICAL"`.
3. Extend Reviewer A mutation drill list: mutate the XCORR-1 exemption bypass to a no-op, confirm D5b fails.
4. Remove §Open build-time finding paragraph (it becomes resolved).

---

## 4. RAM-only state across restart

Plan §Adjudicated ask 3 states RAM-only, dies with track. **Explicit and correct.** The re-dispatch behavior after restart is:

- Mid-track restart → track dies → new track opens on next observation → empty ledger.
- If the new track's first observation is already `circling` (revisit_count on the fresh track starts at 0; camera_count starts at 1) — **`classify()` returns what?** Need to check `classify` behavior on a first-observation track. If `classify` returns `pass_by` for camera_count=1 (typical), no immediate exemption. If it returns `circling` (unlikely on first obs), the exemption gate compares to `last=None` (rank -1) < 2 → exemption fires. Bounded: one additional HIGH page per restart in the worst case. **Acceptable and bounded per the operator ask.**
- The plan should add one sentence to the docstring of `_dispatched_classifications` explicitly noting the restart-rearm behavior — currently the plan says "matches predecessor D3 semantics" without spelling out the observable operator effect. **LOW-4.**

---

## 5. Acceptance criteria + wire-in anchor discipline

- D1 fields: acceptance is a dataclass introspection test. Fine but hollow-adjacent — the fields are load-bearing only via D2. Acceptable because D2 mutation drills anchor them behaviorally.
- D2 helper: **wire-in anchor is the enclosing method + the ledger-update block.** Reviewer A drill #4 (neuter the ledger update) is the correct behavioral anchor — passes.
- D2 has a specific mutation-drill neutering the safeword check (drill #3) — passes.
- D3 pins the founding shape end-to-end — behavioral, correct.
- D5 pin — see §3, insufficient without D5b.
- D6 live-validation table — testable and specific. ✓
- **Missing anchor for I1's "exactly-one" property across multi-escalation lifecycles.** D3 covers pass_by→circling (skipping approach). Add a test that walks pass_by→approach→circling and asserts **two** exemption dispatches (I1 says "one per escalating transition"). Without it, a builder could implement I4 as "one exemption per track lifetime EVER" (equivalent to `_dispatched_classifications` being replaced by a boolean) and pass every existing D3-D5 test. **MED-3.**

---

## 6. NM dedup interaction (S7)

`_is_deduplicated` (NM :1490) keys on `(coordinator_id, title, location, severity)`. On exemption hop 3:
- coordinator_id: `perimeter_alert` (same as hop 1).
- title: `"Perimeter Alert — Person Detected"` (constant string at perimeter_alert.py :1272 — same as hop 1).
- location: `entity_id` — same physical sensor if same camera as hop 1.
- severity: HIGH (hop 3) vs earlier severity (hop 1 was some contextual value, likely LOW/MEDIUM for pass_by).

If severity DIFFERS from hop 1's severity, no dedup. In the founding case (contextual pass_by ≠ HIGH), **no dedup collision**. ✓ In a scenario where hop 1 was already HIGH (e.g. contextual severity for the hazard's default in some house state), the exemption hop would dedup with hop 1 → **silent drop**. Probably not reachable in the current severity map for person/pass_by, but the plan should verify by reading `NM_HAZARD_EXTERIOR_PERSON_CONTEXTUAL_SEVERITY` and either (a) confirming pass_by is never HIGH in any house state (making dedup structurally impossible), or (b) adding a test. **MED-2.**

---

## Findings summary

| ID | Severity | Area | Fix |
|---|---|---|---|
| HIGH-1 | HIGH | XCORR-1 adjudication wrong-mechanism + real single-camera-night gap unaddressed | §3e — recommend Option (i), add D5b, extend §Adjudicated ask 4, close open-finding paragraph |
| MED-1 | MED | Plan snippet uses `is_life_safety_hazard` without import | Add explicit import instruction to D2 |
| MED-2 | MED | NM dedup (S7) interaction unverified | Read contextual-severity map, confirm no HIGH-HIGH collision or add test |
| MED-3 | MED | I1 "per escalating transition" not pinned by a multi-escalation test | Add `test_multi_escalation_pass_by_approach_circling_gets_two_exemptions` to D3 |
| LOW-1 | LOW | S4 (in-flight guard) interaction with exemption not documented | Add one sentence to §Non-goals or §D2 stating exemption still respects in-flight guard |
| LOW-2 | LOW | Strict `<=` boundary in escalation predicate not pinned | Add docstring note + mutation drill (`<= → <`) |
| LOW-3 | LOW | I4 wording ambiguity re "at most one HIGH page per track" | Explicit statement + test `test_reescalation_after_downgrade_gets_no_new_exemption` |
| LOW-4 | LOW | Restart re-arm operator-visible effect not spelled out | Docstring sentence on `_dispatched_classifications` |

---

## Verdict

**FIX-PLAN-FIRST.** Fix HIGH-1 and both MED findings in the plan doc, then dispatch to build. LOW findings are polish and can be folded in during the same plan edit. Structural design (Option A, one exemption per escalating transition, RAM-only, zero knobs) is sound; the failures are (a) an incorrect adjudication mechanism for XCORR-1 that overlooks a real reachable failure path and (b) plan gaps around adjacent suppression sites and a missing import. All are plan-doc edits; no design rework needed.

Estimated plan-edit effort: ~30 minutes. Rebuild after edit: no.
