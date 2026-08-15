# PLANNING — CIRCLING-LABEL-1 (Option A: classification-transition cooldown exemption)

**Rev-2 (2026-08-14).** Applies plan-review findings from
`docs/reviews/code-review/circling_label_plan_review.md` (commit 0d30ee8bc,
verdict FIX-PLAN-FIRST). Changes vs rev-1:

- HIGH-1: Ask 4 adjudication rewritten from the wrong "RAISE branch
  neutralizes" mechanism to the correct XCORR-1 short-circuit trace
  (NIGHT_ONLY + adjacent_activity), AND the single-camera-nighttime
  reachable gap is closed via Option (i) — `_exemption_active` thread
  into `_evaluate_burst_demotion` early-return. New deliverable D5b.
- MED-1: `is_life_safety_hazard` import spelled out in D2 with a
  named import-missing drill.
- MED-2: New deliverable D7 confirms NM dedup (S7) never collides on
  the exemption path.
- MED-3: I1 pinned as `set[str]` semantics with a multi-escalation
  test that a bool implementation must fail.
- LOWs: S4 in-flight guard interaction documented; strict `<` ordering
  boundary pinned; I4 wording tightened + regression test named;
  restart re-arm operator-visible behavior documented.
- Open build-time finding paragraph CLOSED — adjudication is now
  resolved in-plan; the builder inherits the answer.

---

**Card:** CIRCLING-LABEL-1 (kanban.data.yaml). Operator adjudication 2026-08-14: **Option A approved** per orchestrator recommendation — one dispatch allowed through the per-camera cooldown when a track's classification TRANSITIONS, so the hop where `circling` forms produces one HIGH circling-labelled page.

**Thread:** perimeter. **Tier:** 2 (see §Tier classification for the adjudication vs elevating to 2-DB).

**Predecessor:** CIRCLING-SEVERITY-1 shipped v5.74.0 (D1/D2/D3 machinery + INV-M). That cycle's Review-A MEDIUM-A1 is exactly this card — INV-M held under the founding shape (pages happened) but the pages carried the wrong classification (pass_by/approach), because per-camera cooldown at `perimeter_alert.py:1049-1065` returns before the hop where `classify()` transitions to `circling`. This cycle is the narrow follow-up: not a new invariant, a targeted exemption to the existing cooldown for classification-transition events only.

---

## Institutional context verified

### Greps run

- `rg -n 'PERIMETER_ALERT_COOLDOWN_SECONDS' custom_components/…` → single consumer at `perimeter_alert.py:1057` inside `_async_handle_perimeter_trigger`. Constant defined once in `const.py`. **The cooldown has exactly one gate site** — the exemption is a single-site change.
- `rg -n 'last_dispatched_classification|last_classification' custom_components/…` → **no hits**. Field is genuinely NEW on `ExteriorTrack`.
- `rg -n 'note_alert_dispatched' custom_components/…` → 2 call sites (`perimeter_alert.py:1424` person, `:2556` vehicle — vehicle out of scope) and 1 write site (`exterior_track_linker.py:795`). **`alert_count` is incremented only inside the `dispatched_ok=True` branch** — verified at `perimeter_alert.py:1406-1424`. Confirms the CIRCLING-SEVERITY-1 D3 tripwire semantics are unaffected by this cycle: an exemption-permitted dispatch that succeeds still increments `alert_count`, so `sensor.perimeter_circling_zero_dispatch_24h` continues to fire only on true dispatch-loss paths (5/6/7 from the predecessor plan's trace). **NEW: the exemption changes the classification LABEL on some dispatches, not the dispatch COUNT beyond the +1 per transition.**
- `rg -n '_perimeter_silence_until|NM_SECURITY_HAZARDS' custom_components/…` → NM safeword window state lives at `notification_manager.py:387` (field), gate at `:1452-1488`. NM returns early on suppress **without raising**, so perimeter_alert sees `dispatched_ok=True` and reserves cooldown + calls `note_alert_dispatched`. **This is the load-bearing fact for I3 (safeword outranks exemption): a naive "always update `last_dispatched_classification` on `dispatched_ok`" would let a safeword-suppressed alert silently CONSUME the transition exemption — the operator would never get their HIGH circling page even after the window closed.** See §D2.
- `rg -n 'is_life_safety_hazard' custom_components/…` → defined at `_nm_cycle_a.py` and imported by `notification_manager.py:146`. **NOT currently imported by `perimeter_alert.py`.** MED-1 (rev-1 review): D2 MUST add `from ._nm_cycle_a import is_life_safety_hazard` alongside the existing `NM_HAZARD_EXTERIOR_PERSON` import at `perimeter_alert.py:92`. If omitted, the `try` around the exemption helper would catch NameError and silently return False (masquerading as "safeword window blocks" — D4 would then pass for the wrong reason). See §D2 for the explicit import block and Reviewer A drill #5.
- `rg -n 'classify\(' custom_components/universal_room_automation/exterior_track_linker.py` → producer at `:686-716`; consumers at `perimeter_alert.py:1099-1104` (early, severity resolve), `:1152` (coercion), and `open_tracks_snapshot :769` (D3 diagnostic). The exemption gate needs a *third* call at the cooldown site — verified none exists today.
- `rg -n 'RAISE.*(approach|circling)|approach.*circling.*RAISE' custom_components/…` → continuation-coercion RAISE-only branch at `perimeter_alert.py:1188-1199`. This branch runs POST-cooldown; today it's dead for the 2-camera shape because the cooldown returns before severity is even re-resolved on the hop where `circling` forms. The exemption revives it for exactly one hop per transition. See §D3 for the interaction map.
- `rg -n 'force_immediate_security_image' custom_components/…` → `const.py:1520` (route-reason string) and `test_nm_image_delivery.py`. This is a NM-side snapshot/route-reason decision downstream of `nm.async_notify`; **it does not read `ExteriorTrack.last_dispatched_classification` and is unaffected by this cycle**. Exemption-permitted dispatches carry the same `_kwargs` shape as any other dispatch. Confirmed by reading `perimeter_alert.py:1375-1394`.
- `rg -n 'PERIMETER_BURST|_evaluate_burst_demotion' …` → XCORR-1 burst-demote at `perimeter_alert.py:1213-1239`; helper body at `:1822-1936`. **Read end-to-end during rev-2 (see §Adjudicated ask 4 for the full trace).** Decision order: `PERIMETER_BURST_DEMOTE_ENABLED` → `PERIMETER_BURST_NIGHT_ONLY` guard (window `[23:00, 05:00)` per `const.py:1448/:1458`) → `prior_alerts_in_window >= MIN_ALERTS-1` → `sibling_corroborated` → `adjacent_activity` via `linker.has_recent_adjacent_activity`. Non-night is a hard no-op; nighttime multi-camera on the adjacency graph short-circuits on adjacent_activity; **single-camera nighttime is the only reachable demote path** and is the target of Option (i) in §Ask 4.
- `rg -n '_is_deduplicated|DEDUP' custom_components/universal_room_automation/domain_coordinators/notification_manager.py` → `_is_deduplicated` at `:1490-1494`, keys `(coordinator_id, title, location, severity)`. Verified — the exemption path could dedup with hop 1 iff hop-1 severity equals hop-3 severity. Contextual-severity map (`const.py:1556-1635`) resolves `person + pass_by` to LOW/MEDIUM in every house state, never HIGH; hop-3 exemption is HIGH/CRITICAL — **no HIGH-HIGH collision structurally possible today**. Pinned by D7. See §D7 and MED-2.

### Prior planning docs consulted

- `docs/planning/PLANNING_circling_severity.md` (rev-2, v5.74.0) — full read. This cycle is the "MEDIUM-A1 spinoff" carded from its Review A. The trace, INV-M, and D3 tripwire semantics are inherited and NOT changed.
- `docs/planning/PLANNING_safeword_window.md` — full read. Invariants I1 (never-blanket) and I2 (perimeter-only scope) constrain this cycle: the exemption cannot cause a safeword-windowed alert to leak. See §D2, §Falsifiable invariants.
- `docs/planning/PLANNING_consol_1_alerting_llmvision.md` §6 (contextual severity function) + §D2 — skimmed. Explains why `circling` in `home_day/home_evening` is `HIGH`, in `home_night/away/sleep/vacation` is `CRITICAL`, and why `pass_by` never resolves to HIGH.
- `docs/reviews/code-review/v5.74.0_circling_severity_d3_area.md` — full read (source of the card).
- `docs/reviews/code-review/circling_label_plan_review.md` — rev-1 plan review, FIX-PLAN-FIRST. Rev-2 addresses every finding.

### Memory bodies pulled

- `feedback_suppression_needs_discharge.md` — the exemption is a *permission*, not a suppression. Discharge = the exemption is consumed by exactly ONE dispatch (or by a safeword window). Not restart-persisted (RAM-only, matches ExteriorTrack lifetime).
- `feedback_marginal_benefit_pushback.md` — the exemption is the SIMPLEST version (Option A per card recommendation). Alternatives B (widen invariant + counter) and C (accept) were adjudicated by the operator; not re-litigating.
- `feedback_hollow_test_anchors.md` + `feedback_wire_in_anchor_mandatory.md` — every new field and every gate branch gets a mutation-anchored drill (§Review C).

### Design docs read

- No `docs/Coordinator/PERIMETER_ALERT.md` present; the inline docstrings in `perimeter_alert.py` and `exterior_track_linker.py` are authoritative.

### Code locations surveyed end-to-end

- `custom_components/universal_room_automation/perimeter_alert.py:1028-1450` — the entire `_async_handle_perimeter_trigger` frame, including cooldown (:1049-1065), in-flight guard (:1067-1079), severity resolve (:1088-1117), coercion (:1119-1206), XCORR-1 burst-demote (:1208-1239), dispatch (:1370-1445).
- `custom_components/universal_room_automation/perimeter_alert.py:1822-1936` — `_evaluate_burst_demotion` end-to-end (rev-2, for Ask 4 adjudication).
- `custom_components/universal_room_automation/exterior_track_linker.py:85-135` (ExteriorTrack dataclass) + `:686-716` (classify) + `:782-802` (note_alert_dispatched).
- `custom_components/universal_room_automation/domain_coordinators/notification_manager.py:387, :1440-1494, :3442-3459` — perimeter silence window state, gate, dedup, and open path.
- `custom_components/universal_room_automation/const.py:1556-1635` (contextual severity function) + `:1662-1718` (adjacency graph — reused for the D1 test as in v5.74.0 D1) + `:1436/:1448/:1458` (XCORR-1 constants).
- `custom_components/universal_room_automation/_nm_cycle_a.py` — `is_life_safety_hazard` definition (for MED-1 import).

---

## Perimeter suppression-site enumeration (rev-2 addition, LOW-1 fix)

Every early-return in `_async_handle_perimeter_trigger` on the person leg, in source order, with the exemption's interaction:

| # | Site | Nature | Exemption interaction |
|---|---|---|---|
| S1 | Alert-hours gate | Whole-flow suppress | Upstream of exemption — irrelevant. |
| S2 | Egress-window suppression (:1032-1047) | Whole-flow suppress | Upstream — correct: exemption must not reopen egress-suppressed events. |
| S3 | Per-camera cooldown (:1049-1065) | **The gate the exemption targets.** | Two-step gate per D2. |
| S4 | In-flight guard (:1067-1079) | Concurrency guard | Runs AFTER cooldown. Exemption-permitted alerts still respect S4 — a same-camera dispatch already in flight suppresses the second dispatch. **This is CORRECT (one-in-flight per camera invariant preserved) and INTENTIONAL.** D2 does not move or bypass S4. |
| S5 | XCORR-1 burst-demote (:1213-1239) | Demote (not silence) | See §Ask 4 adjudication — Option (i) `_exemption_active` early-return in `_evaluate_burst_demotion`. |
| S6 | NM safeword window | Silent NM-side suppression, `dispatched_ok=True` from PA POV | Plan I3 short-circuits BEFORE the exemption fires. |
| S7 | NM dedup (:1490-1494) | Silent dedup on `(coord_id, title, location, severity)` | D7 verifies no HIGH-HIGH collision structurally possible on the exemption path. |
| S8 | NM DND / other NM gates | Silent | Existing behavior, exemption-agnostic. |

---

## Falsifiable invariants (state up front)

The build ships iff **all four** hold across the whole reachable surface (D-framing reviewer, if elevated to Tier 3, re-enumerates from scratch; Tier 2 splits I1/I2 across reviewers A/B):

1. **I1 (exactly-one per escalating transition).** For any ExteriorTrack whose lifetime sequence of `classify(t)` observations at cooldown-gate entry produces the ordered class sequence `c_1, c_2, ..., c_n`, the number of dispatches PERMITTED BY THE TRANSITION EXEMPTION (i.e. permitted after the per-camera cooldown would otherwise have blocked) equals the number of *escalating* transitions in that sequence — where escalation is defined by the strict ordering `pass_by < approach < circling`. In particular, for the founding 5-hop shape (`pass_by → pass_by → circling → circling → circling`) the exemption permits exactly ONE additional dispatch (at hop 3), producing exactly ONE HIGH circling-labelled page beyond whatever the baseline cooldown allows. For the fully-escalating shape `pass_by → approach → circling`, the exemption permits **TWO** additional dispatches (one at `→ approach`, one at `→ circling`). **This "one per escalating transition, not one per track lifetime" property is load-bearing: the ledger field `_dispatched_classifications` MUST be a `set[str]` (per-class), NOT a `bool`. A bool implementation is provably wrong under the multi-escalation lifecycle and MUST fail the D3b test.** (rev-2 MED-3 pin.)

2. **I2 (no re-dispatch on de-escalation).** A track whose classification transitions from `circling → pass_by` (or `circling → approach`, or `approach → pass_by`) at some later hop does NOT get a new exemption dispatch on that hop. `last_dispatched_classification` is updated on every exemption-permitted successful dispatch, but the *permission gate* only opens when `severity_rank(current) > severity_rank(last)` — **strict `>`, not `>=`. Equivalently: `current_rank <= last_rank → blocked` (strict `<=` in the predicate).** A `<` boundary would erroneously permit a re-dispatch when `current == last`. (rev-2 LOW-2 pin — `_CLASSIFICATION_RANK.get(unknown, -1)` maps unknowns to -1 so `unknown vs None` yields `-1 <= -1 → blocked`, safe.)

3. **I3 (safeword window outranks exemption, and does not consume it).** While `nm._perimeter_silence_until` is active AND `hazard ∈ NM_SECURITY_HAZARDS` AND `hazard ∉ life-safety` (i.e. the safeword window would suppress a normal perimeter dispatch — the exact condition at `notification_manager.py:1468-1488`), the transition exemption is NOT permitted. `last_dispatched_classification` is NOT updated. When the window expires, the very next hop whose `classify()` differs from `last_dispatched_classification` will fire the transition dispatch normally.

4. **I4 (flap-bounded).** Regardless of oscillation shape, the exemption fires AT MOST ONCE per `(track, target_classification)` pair over the track's lifetime — where `target_classification` is the class the track transitioned INTO. **Explicit reading:** a track oscillating `approach ↔ circling ↔ approach ↔ circling` gets ONE exemption dispatch (the first `→ circling` transition — the first `→ approach` was already dispatched during the initial founding transition). It is NOT "one HIGH page per track EVER"; it IS "one exemption per (track × target class), which for the 3-value vocabulary bounds each track at ≤ 2 total exemptions (one `→ approach`, one `→ circling`)". (rev-2 LOW-3 pin — regression test `test_reescalation_after_downgrade_gets_no_new_exemption`.)

**Combined with the predecessor's INV-M**, the cycle-level guarantee is: *"a track whose classification escalates produces EXACTLY ONE additional dispatch per escalating transition, never any dispatch while a safeword window covers it, and never more than one per target-classification per track lifetime."*

---

## Adjudicated design decisions (embedded in the invariants above)

The operator asked the plan to adjudicate several points. Each is resolved below; no operator decisions are outstanding.

- **Transition-DOWN direction (ask 1).** Adjudicated as I2: exemption is ESCALATING-only, strict ordering `pass_by < approach < circling`, predicate `current_rank <= last_rank → blocked`. Chosen over a "transition-set" approach because the founding ask is escalation-only and a downgrade page has no consumer.
- **Flap bound (ask 2).** Adjudicated as I4: **one exemption per `(track, target_classification)` pair lifetime**, tracked via a **`set[str]` field on ExteriorTrack** (not a `bool` — see I1 and MED-3). Natural upper bound per track: 2 (approach, circling).
- **Restart (ask 3).** Adjudicated as: **RAM-only. State dies with the track.** ExteriorTrack itself is RAM-only. If HA restarts mid-track, the track is lost and the exemption ledger goes with it — the next re-observation opens a new track with an empty `_dispatched_classifications` set. **Operator-visible re-arm behavior (rev-2 LOW-4 pin):** *any HA restart clears the RAM-only exemption ledger for all in-flight tracks; the next escalating hop after restart on each newly-observed track will fire one additional exemption dispatch per target-class it escalates into. Bound: ≤ 2 additional pages per track per restart (approach + circling). This is intentional and acceptable per the founding ask ("one HIGH page at circling formation"); documented on `_dispatched_classifications`' docstring.*

- **Continuation-coercion RAISE + `force_immediate_security_image` + XCORR-1 (ask 4 — rev-2 rewrite).**

  **rev-1 stated the wrong mechanism.** The RAISE branch at `perimeter_alert.py:1188-1199` runs BEFORE XCORR-1 but does not stop XCORR-1 from running; XCORR-1 (`_evaluate_burst_demotion`, :1822-1936) short-circuits on its OWN guards, not on pre-XCORR-1 severity. Rev-2 read the helper end-to-end and traces:

  **Founding case (`home_day`, 09:22 CDT, 2-camera):**
  - Guard 2 (`PERIMETER_BURST_NIGHT_ONLY`, window `[23,5)`): 09:22 not in window → `return False, reason="outside_night_window"`. **XCORR-1 no-op. Exemption dispatch keeps HIGH.** ✓

  **Nighttime multi-camera adjacent (`home_night` ~02:00, back_yard ↔ front_side_ptz):**
  - Guards 2, 3, 4 pass. Guard 5 (`adjacent_activity`): back_yard's adjacency graph contains front_side_ptz → `has_recent_adjacent_activity` True → `return False, reason="adjacent_activity"`. **XCORR-1 no-op. Exemption dispatch keeps CRITICAL.** ✓

  **Nighttime single-camera (`home_night` ~02:00, back_yard ×3) — THE REACHABLE FAILURE PATH:**
  - Guards 2, 3, 4 pass. Guard 5: only-camera-involved is back_yard; no adjacent activity → guard 5 passes. **DEMOTE fires → severity = LOW.** ✗ Founding ask ("hop where circling forms produces one HIGH page") is UNMET for single-camera-night tracks.

  **Fix — Option (i) (adjudicated, minimal, ~3 lines + one mutation-anchored drill):** Thread an `exemption_active` early-return into `_evaluate_burst_demotion`. When the current dispatch was permitted through the classification-transition exemption AND `classification in {"approach", "circling"}`, the demote helper returns `False, reason="classification_transition_exemption"` BEFORE guard 5. This is a first-class short-circuit (near the top of the helper, after `PERIMETER_BURST_DEMOTE_ENABLED` but before the night-window guard — so it protects the founding ask regardless of house_state × camera-shape).

  Mechanism: `_async_handle_perimeter_trigger` sets a local `exemption_active: bool` when the exemption gate permitted the dispatch, then passes it as a keyword arg to `_evaluate_burst_demotion(..., exemption_active=exemption_active)`. Helper signature gains `exemption_active: bool = False` (backward-compatible default). Early-return block at the top of the helper:

  ```python
  if exemption_active and classification in ("approach", "circling"):
      return False, "classification_transition_exemption"
  ```

  Rationale: the exemption's whole point is that ONE dispatch labels the escalating transition. Demoting the transition dispatch to LOW defeats the founding ask across every state × camera-shape, not just the single-camera-night edge. A blanket "exemption bypasses demote for approach/circling" is the correct semantic and the minimum-surface fix.

  Continuation-coercion RAISE is unchanged: for `home_day + circling` the contextual is HIGH and the map is MEDIUM, `HIGH > MEDIUM` → no raise. For `home_night + circling` the contextual is CRITICAL, no raise. Net: RAISE is a no-op on exemption dispatches under today's map (verified by test D5).

  `force_immediate_security_image` is decided at NM downstream of `nm.async_notify` based on hazard/severity — unaffected. Confirmed by grep.

- **Safeword window (ask 5).** Adjudicated as I3: the exemption checks `nm._perimeter_silence_until` (via `getattr`) and defers when the window would suppress. Chosen over "let the exemption fire and let NM suppress" because NM's silent-suppression semantics (returns early without raising, but `dispatched_ok=True` from perimeter_alert's POV) would consume the exemption without paging.

- **Knobs on the ladder (ask 6).** **ZERO new knobs.** The exemption is structural: no threshold, no window, no toggle. Kill-switch semantics are inherited from the linker's existing `tracking_enabled` (fire axe: no tracks → no classification → no exemption) and `TRACK_LINK_WINDOW_S == 0` (byte-identical to no-linker).

---

## Non-goals (explicit)

- Not changing `PERIMETER_ALERT_COOLDOWN_SECONDS` or introducing per-classification cooldowns.
- Not touching the vehicle leg (`perimeter_alert.py:2331-2570`). Person only.
- Not adding an ack/repeat engine to HIGH circling. HIGH pages once, no repeat — same as CIRCLING-SEVERITY-1.
- Not persisting `last_dispatched_classification` or `_dispatched_classifications` across HA restarts.
- Not changing D3 tripwire semantics. `sensor.perimeter_circling_zero_dispatch_24h` continues to count `alert_count == 0` classified-circling tracks; the exemption dispatch increments `alert_count` on success.
- Not changing NM safeword-window behavior. Only *reading* `_perimeter_silence_until` to gate the exemption.
- Not changing NM dedup key. D7 verifies non-collision structurally under today's severity map.
- Not moving or bypassing S4 (in-flight guard). Exemption dispatches still respect one-in-flight-per-camera concurrency (LOW-1 pin).
- Not introducing a new dispatcher signal or cross-coordinator event.
- Not building a soak / monitor step; live validation is the D6 replay table.

---

## Deliverables

### D1 — Add classification transition state to `ExteriorTrack`

**File:** `custom_components/universal_room_automation/exterior_track_linker.py` (dataclass ~ `:95-135`).

Add two fields to the `ExteriorTrack` dataclass:

```python
# CIRCLING-LABEL-1: transition-exemption ledger. RAM-only, dies with
# the track (matches predecessor D3 semantics — a mid-track restart
# loses the ledger; the new track re-earns exemptions from scratch).
#
# _dispatched_classifications is a SET (not a bool). A per-class set is
# load-bearing for I1: the multi-escalation shape pass_by→approach→
# circling produces TWO exemption dispatches (one per escalating
# transition). A bool implementation would collapse the second dispatch
# and provably fails D3b (test_multi_escalation_pass_by_approach_
# circling_gets_two_exemptions).
#
# Operator-visible restart re-arm behavior: any HA restart clears this
# ledger for all in-flight tracks. The next escalating hop after
# restart on each newly-observed track will fire one additional
# exemption dispatch per target-class it escalates into. Bound:
# <= 2 additional pages per track per restart (approach + circling).
# Intentional per the founding ask.
last_dispatched_classification: str | None = None
_dispatched_classifications: set[str] = field(default_factory=set)
```

No other change to the linker in D1. `classify()` is untouched. `note_alert_dispatched()` is untouched at this deliverable — the update to the two new fields happens at the perimeter_alert call site (D2), which is the only place with visibility into whether the dispatch used the exemption gate.

#### Acceptance Criteria
- **Verify:** `ExteriorTrack` dataclass has both fields; defaults are `None` and `set()`.
- **Verify:** the annotation for `_dispatched_classifications` is `set[str]` (not `bool`, not `frozenset`).
- **Test:** `test_exterior_track_dataclass_has_transition_ledger` in `quality/tests/perimeter/test_circling_label_transition.py` — asserts field presence, defaults, AND the `set[str]` annotation type.

---

### D2 — Transition-exemption gate at the cooldown site

**File:** `custom_components/universal_room_automation/perimeter_alert.py` (~`:1049-1065`).

Replace the plain cooldown block with a two-step gate: cooldown check FIRST, then (on cooldown-would-block) a transition-exemption check.

**Required imports (rev-2 MED-1 pin).** At `perimeter_alert.py:~92` (module import block), alongside the existing `NM_HAZARD_EXTERIOR_PERSON`:

```python
from ._nm_cycle_a import is_life_safety_hazard  # CIRCLING-LABEL-1: I3 gate uses this
```

`is_life_safety_hazard` is defined in `_nm_cycle_a.py` and already imported by `notification_manager.py:146`. Omitting this import makes the exemption helper raise `NameError`; the outer `try` swallows it, the helper returns False, and D4 passes for the wrong reason (masquerades as "safeword window blocks"). Reviewer A drill #5 verifies: delete the import → confirm a specific test (`test_import_missing_fails_loud`) fails with a named import-error assertion (not a silent False), then restore.

Pseudocode for the gate (the builder writes exact source):

```python
# --- 3. Per-camera cooldown (outer, authoritative rate limit) ---
cooldown_key = self._camera_key_for_sensor(entity_id) or entity_id
last_alert = self._last_alert.get(cooldown_key)
cooldown_would_block = (
    last_alert is not None
    and (now - last_alert).total_seconds() < PERIMETER_ALERT_COOLDOWN_SECONDS
)

exemption_active = False  # threaded into XCORR-1 (see D5b)
if cooldown_would_block:
    exemption_active = self._classification_transition_exemption_permitted(
        cooldown_key=cooldown_key,
        entity_id=entity_id,
        now=now,
    )
    if not exemption_active:
        _LOGGER.debug(
            "PerimeterAlertManager: alert suppressed for %s — cooldown "
            "(%.0fs of %ds elapsed, no classification-transition exemption)",
            entity_id,
            (now - last_alert).total_seconds(),
            PERIMETER_ALERT_COOLDOWN_SECONDS,
        )
        return
    _LOGGER.info(
        "PerimeterAlertManager: cooldown bypassed for %s by "
        "classification-transition exemption (track owner)",
        entity_id,
    )
```

The local `exemption_active` bool is threaded downstream to `_evaluate_burst_demotion` (see D5b).

New helper `_classification_transition_exemption_permitted(...)`, private to `PerimeterAlertManager`:

```python
_CLASSIFICATION_RANK = {"pass_by": 0, "approach": 1, "circling": 2}

def _classification_transition_exemption_permitted(
    self, *, cooldown_key: str, entity_id: str, now: datetime,
) -> bool:
    """Return True iff the classification-transition exemption should
    permit ONE dispatch past the per-camera cooldown for this event.

    Semantics (see plan §Falsifiable invariants I1-I4):
      - I3: safeword window outranks. Return False if NM would suppress.
      - I4: one exemption per (track, target_class). Return False if
            current class is already in the track's dispatched set.
      - I2: escalation only. Predicate is STRICT: `current_rank <=
            last_rank → blocked` (using strict `<=`, NOT `<`; a `<`
            boundary would erroneously permit re-dispatch on
            current == last).
    """
    # I3: safeword window outranks.
    nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
    if nm is not None:
        silence_until = getattr(nm, "_perimeter_silence_until", None)
        if silence_until is not None and dt_util.utcnow() < silence_until:
            if not is_life_safety_hazard(self.hass, NM_HAZARD_EXTERIOR_PERSON):
                return False

    # Locate the owning track.
    linker = self.hass.data.get(DOMAIN, {}).get("exterior_track_linker")
    if linker is None or TRACK_LINK_WINDOW_S <= 0:
        return False
    if not getattr(linker, "tracking_enabled", True):
        return False
    track = linker.find_owning_track(cooldown_key, "person", now)
    if track is None:
        return False

    current = linker.classify(track)
    last = track.last_dispatched_classification

    # I4: one exemption per (track, target_classification) pair lifetime.
    if current in track._dispatched_classifications:
        return False

    # I2: STRICT escalation. `<= → blocked` — do NOT weaken to `<`.
    current_rank = _CLASSIFICATION_RANK.get(current, -1)
    last_rank = _CLASSIFICATION_RANK.get(last, -1) if last is not None else -1
    if current_rank <= last_rank:
        return False

    return True
```

Update the ledger on successful dispatch. In the existing `dispatched_ok` block (~ `:1406-1430`), after `note_alert_dispatched`:

```python
# CIRCLING-LABEL-1: record classification for the exemption ledger.
# Update EVERY successful dispatch (not only exemption ones) so
# baseline dispatches also seed `last_dispatched_classification`
# and the exemption gate has an accurate "last" to compare against.
try:
    _track = _linker.find_owning_track(_cam_key, "person", now)
    if _track is not None:
        _cls = _linker.classify(_track)
        _track.last_dispatched_classification = _cls
        _track._dispatched_classifications.add(_cls)
except Exception:  # noqa: BLE001
    _LOGGER.debug(
        "PerimeterAlertManager: transition ledger update failed",
        exc_info=True,
    )
```

**Wire-in anchor (mandatory).** The gate is the enclosing `_classification_transition_exemption_permitted` method. The ledger update is the two-statement block inside `dispatched_ok`. Both are behaviorally load-bearing (§Review C mutation drills).

**In-flight guard (S4) interaction (LOW-1 pin).** The in-flight guard at `:1067-1079` remains AFTER the cooldown/exemption gate. An exemption-permitted dispatch still respects one-in-flight-per-camera concurrency — if a same-camera dispatch is already in flight when the exemption fires, S4 suppresses the second. This is intentional (preserves the concurrency invariant) and does NOT consume the exemption (the exemption ledger update lives in the `dispatched_ok` block, which S4 short-circuits before reaching). Documented; not tested (existing S4 tests cover the branch).

**Institutional-context note.** The private-attribute reach into `nm._perimeter_silence_until` mirrors the existing pattern of `_linker._tracks` reach from `perimeter_diagnostics` (documented at `exterior_track_linker.py:147-151`). Add a symmetric one-line contract comment at `notification_manager.py:387` noting that `perimeter_alert._classification_transition_exemption_permitted` reads this field directly — refactor tripwire.

#### Acceptance Criteria
- **Verify:** cooldown-block path unchanged when no owning track (linker absent, or `find_owning_track` returns None).
- **Verify:** cooldown-block path unchanged when owning track's classification is not an escalation over `last_dispatched_classification`.
- **Verify:** cooldown BYPASSED exactly once per escalating transition (I1) — bypass fires, dispatch reaches NM, and subsequent same-classification hops within the cooldown window are re-blocked.
- **Verify:** no bypass when NM safeword window is active (I3); after window expiry the very next escalating hop bypasses.
- **Verify:** no bypass when `classification in track._dispatched_classifications` (I4 flap bound).
- **Verify:** predicate uses strict `<=` (LOW-2) — mutation `<= → <` fails a named test.
- **Verify:** import of `is_life_safety_hazard` is present; removing it fails `test_import_missing_fails_loud`.
- **Verify:** the contract comment at `notification_manager.py:387` is present.
- **Test:** `test_transition_exemption_bypasses_cooldown_on_escalation`, `test_no_exemption_on_de_escalation`, `test_no_exemption_when_target_class_already_dispatched`, `test_no_exemption_when_safeword_window_active`, `test_exemption_available_after_safeword_window_expires`, `test_ledger_updates_on_baseline_dispatch_too`, `test_gate_returns_false_when_linker_absent`, `test_gate_returns_false_when_tracking_disabled`, `test_predicate_boundary_is_strict_le`, `test_import_missing_fails_loud`.

---

### D3 — Regression test: founding 5-hop shape yields ONE HIGH circling page

**File:** `quality/tests/perimeter/test_circling_founding_case_transition.py` (NEW).

Extends the v5.74.0 `test_circling_founding_case.py` pattern with the exemption's expected effect. Feed the exact founding sequence (`back_yard, front_side_ptz, back_yard, front_side_ptz, back_yard`), house_state `home_day`, real `ExteriorTrackLinker` with `set_adjacency(EXTERIOR_ADJACENCY_GRAPH)`, spy NM.

Assertions (in order):

- Precondition: `len(linker.open_tracks) == 1` after event 3 (adjacency-loaded sanity, per predecessor D1 lesson).
- Hop 1 (`back_yard`): dispatch #1. `classify == "pass_by"`. Severity per contextual resolver.
- Hop 2 (`front_side_ptz`): dispatch #2 (different camera → no cooldown). `classify == "pass_by"`.
- Hop 3 (`back_yard` — same camera as hop 1, within 300s cooldown): **exemption fires**. `classify == "circling"`. Dispatch #3 reaches NM at severity `HIGH` (contextual `home_day + circling`).
- Hop 4 (`front_side_ptz` — same camera as hop 2, within cooldown): `classify == "circling"` still, but `circling ∈ track._dispatched_classifications` — no exemption, cooldown blocks. `spy_nm.async_notify.call_count == 3`.
- Hop 5 (`back_yard`): same as hop 4. `spy_nm.async_notify.call_count == 3`.

Final state:
- `track.alert_count == 3`.
- `track.last_dispatched_classification == "circling"`.
- `track._dispatched_classifications == {"pass_by", "circling"}`.
- Exactly one of the three dispatches has `severity == Severity.HIGH` (hop 3).

#### Acceptance Criteria
- **Verify:** `pytest quality/tests/perimeter/test_circling_founding_case_transition.py -v` all green.
- **Verify:** the topology precondition fails loud when `set_adjacency` is skipped.
- **Test:** `test_founding_shape_produces_exactly_one_high_circling_page`, `test_founding_shape_dispatch_count_is_three`, `test_founding_shape_ledger_final_state`, `test_founding_shape_topology_precondition`.
- **Live:** covered by D6.

---

### D3b — Regression test: multi-escalation shape yields TWO exemption dispatches (I1/MED-3 pin)

**File:** same file as D3.

Feed `pass_by → approach → circling` (three hops on the SAME camera within cooldown so each hop past the first must earn the exemption). Assertions:

- Hop 1 (`back_yard`, `pass_by`): baseline dispatch #1. `_dispatched_classifications == {"pass_by"}`.
- Hop 2 (`back_yard`, `approach` — cooldown-blocked): exemption fires. Dispatch #2. `_dispatched_classifications == {"pass_by", "approach"}`.
- Hop 3 (`back_yard`, `circling` — cooldown-blocked): exemption fires. Dispatch #3 at HIGH. `_dispatched_classifications == {"pass_by", "approach", "circling"}`.
- Final: **three distinct NM dispatch records**, one per classification.

**A `bool`-based `_dispatched_classifications` (dispatched-any-yes-or-no) will produce TWO dispatches (hops 1, 2) and fail this test loud.** This is the MED-3 anchor that makes the set semantics load-bearing.

Add also `test_reescalation_after_downgrade_gets_no_new_exemption` (LOW-3 pin): drive `pass_by → circling → approach → circling`. Assert only the first `→ circling` fires the exemption (I4 blocks the second because `circling ∈ set`).

#### Acceptance Criteria
- **Test:** `test_multi_escalation_pass_by_approach_circling_gets_two_exemptions` (proves set semantics; a bool implementation fails it).
- **Test:** `test_reescalation_after_downgrade_gets_no_new_exemption` (I4 bound).

---

### D4 — Test: safeword window outranks exemption (I3)

**File:** `quality/tests/perimeter/test_circling_label_transition.py` (NEW — will also host D1's dataclass test and D2's helper tests).

- Open a safeword window on NM (`_perimeter_silence_until = utcnow() + 30min`).
- Drive the founding 5-hop shape.
- Assert: hops 1-2 dispatch as normal (baseline cooldown allows per-camera; NM silently swallows); hop 3 does NOT bypass cooldown because `_classification_transition_exemption_permitted` returns False (safeword active); verify via `nm._perimeter_silence_suppressions`.
- Expire the window.
- Feed one more hop on `back_yard`. **Now** the exemption fires. Dispatch reaches NM at HIGH.

**Adjudication for I3 subtlety.** Under safeword, baseline hops 1-2 still update the ledger (`last_dispatched_classification` = `pass_by`), because they are NOT exemption dispatches. So when the window lifts, "last" is `pass_by`, current is `circling`, escalation holds, exemption fires.

#### Acceptance Criteria
- **Test:** `test_safeword_window_blocks_transition_exemption`, `test_transition_exemption_fires_after_safeword_window_expires`.
- **Verify:** NM `_perimeter_silence_suppressions` counter increments for the swallowed baseline dispatches.

---

### D5 — Test: coercion RAISE branch on exemption dispatch

**File:** same as D4.

- Drive founding shape. At hop 3 (exemption fires), assert:
  - The dispatched severity is `HIGH` (contextual `home_day + circling` override).
  - The continuation-coercion RAISE branch at `perimeter_alert.py:1188-1199` is entered. Since map value for `home_day/circling` is `MEDIUM < HIGH`, no raise occurs — severity stays `HIGH`.

#### Acceptance Criteria
- **Test:** `test_exemption_dispatch_severity_survives_coercion`.

---

### D5b — Test: single-camera nighttime circling exemption survives XCORR-1 (HIGH-1 pin)

**File:** same as D5.

**Setup:** `home_night` house state, `now = 02:00 CDT` (inside `PERIMETER_BURST_NIGHT_WINDOW`), three hops all on `back_yard`, all within the 300s cooldown.

**Trace:**
- Hop 1 (`back_yard`, `pass_by`): baseline dispatch. Cooldown reserved.
- Hop 2 (`back_yard`, `approach` — cooldown-blocked): exemption fires. `exemption_active=True` threaded into `_evaluate_burst_demotion`. Helper returns `(False, "classification_transition_exemption")` at the new early-return. **No demote. Severity survives at CRITICAL** (contextual `home_night + approach`).
- Hop 3 (`back_yard`, `circling` — cooldown-blocked): exemption fires. Same short-circuit. **Severity survives at CRITICAL.**

**Assertions:**
- `spy_nm.async_notify.call_count == 3`.
- Hop-3 dispatch severity == `Severity.CRITICAL`.
- Hop-3 `self._last_burst_decision["back_yard"]` has `severity_after == "CRITICAL"` and `reason == "classification_transition_exemption"`.

**Mutation drill (Reviewer A #6):** delete the `if exemption_active and classification in (...)` early-return from `_evaluate_burst_demotion` → D5b fails loud with severity demoted to LOW; restore.

Without D5b + Option (i), the single-camera nighttime path produces a LOW-severity circling page — the founding ask ("hop where circling forms produces one HIGH page") would be UNMET for this shape.

#### Acceptance Criteria
- **Test:** `test_exemption_dispatch_severity_survives_xcorr1_single_camera_night`.
- **Verify:** helper signature `_evaluate_burst_demotion(..., exemption_active: bool = False)` is backward-compatible (existing callers omit the kwarg).
- **Verify:** the early-return string reason `"classification_transition_exemption"` is asserted (not a bare bool) — supports observability + reviewer B trace.

---

### D6 — Live validation table (post-deploy)

Replay the founding-case shape live: two operator-triggered walks between `back_yard` and `front_side_ptz` (5 hops, ≤ 3 min) during `home_day`. Table filled in on ship-day and written back into `docs/readmes/README_v<version>.md` per CLAUDE.md "Record Live Validation Back Into the README" mandate.

| Criterion | Expected | Observed | Evidence |
|---|---|---|---|
| Linker attributes the loop to one track | 1 person track, 5 hops | | linker snapshot |
| Classification at hop 3+ = `circling` | `classify(track) == "circling"` | | snapshot attribute |
| Total dispatches = 3 | hops 1, 2, 3 dispatched | | NM log line count / notification_log |
| Hop-3 dispatch severity = HIGH | one dispatch at `severity=HIGH` with classification-metadata indicating circling | | NM log line, phone notification |
| Phone received HIGH circling page | phone notification arrives at hop-3 timing | | phone screenshot / delivery receipt |
| `alert_count == 3` on the owning track | linker snapshot attribute | | snapshot |
| `sensor.perimeter_circling_zero_dispatch_24h == 0` post-walk | D3 tripwire quiet | | entity state |
| No safeword window active during test | `nm._perimeter_silence_until in (None, past)` | | NM state |

**Replay under safeword (deferred / optional):** if the operator wants I3 confirmed live, open a "duke 1h" safeword, replay, observe zero pages, wait for window to expire, replay the escalation hop, observe one HIGH page.

---

### D7 — Verification: NM dedup non-collision on exemption path (MED-2 pin)

**File:** verification appendix in the plan-completion tracking + a test in `test_circling_label_transition.py`.

**Verify structurally:** read `NM_HAZARD_EXTERIOR_PERSON_CONTEXTUAL_SEVERITY` (`const.py:1556-1635`) end-to-end. For every house_state in `{home_day, home_evening, home_night, away, sleep, vacation}`, confirm the resolved severity for `(person, pass_by)` is NEVER `HIGH` (it is LOW or MEDIUM in every state per current map). The exemption's hop-3 dispatch is HIGH or CRITICAL — the `(coordinator_id, title, location, severity)` dedup key at `_is_deduplicated` (`notification_manager.py:1490-1494`) therefore cannot collide with hop-1 because the severities differ. **No dedup-key fix is required.**

**If the map ever changes** such that `(person, pass_by)` resolves to HIGH in some state, this cycle's exemption hop 3 in `home_day` could dedup with hop 1 → silent drop. Test D7 guards this:

- `test_exemption_hop_not_deduplicated_against_baseline_hop`: drive founding shape, assert `nm._dedup_suppressions` counter does NOT increment on hop 3; assert the hop-3 record has a distinct `severity` from the hop-1 record on the NM path.
- If the test ever fails after a severity-map change, the fix is to extend the dedup key to include `classification` (a one-line change in `_is_deduplicated`); documented here so future-me finds it.

#### Acceptance Criteria
- **Verify:** severity map audit shows no `(person, pass_by) → HIGH` mapping in any state — pinned in the test's docstring.
- **Test:** `test_exemption_hop_not_deduplicated_against_baseline_hop`.

---

## Tier classification

**Adjudication: Tier 2 (two framing-disjoint reviews) — NOT elevating to Tier 2-DB.**

Standing policy (2026-06-08) elevates regression-prone work to Tier 2-DB by default. This cycle's regression profile:

- **Cross-coordinator ripple:** LOW. One direction only (perimeter_alert reads `nm._perimeter_silence_until`); no writes to NM state; no new signals; no changes to the linker's public API (only dataclass field additions). Rev-2 adds one keyword-arg to `_evaluate_burst_demotion` (backward-compatible default).
- **Trust-hierarchy:** untouched.
- **Shared primitive:** the cooldown is the primitive, but the exemption is a single-site local gate. The predecessor CIRCLING-SEVERITY-1 rebuilt surrounding invariants at Tier 2-DB; this cycle adds a narrow additional path plus a two-arg wire on XCORR-1.
- **Load-bearing invariant surface:** small (4 invariants I1-I4, all locally verifiable). Predecessor's INV-M is preserved by construction — the exemption only ADDS dispatches, never removes them.

**Recommendation: Tier 2.** Reviewer A / Reviewer B framings below.

**Operator MAY elevate to Tier 2-DB** if the XCORR-1 threading (D5b Option (i)) feels under-scoped. If elevated, add Reviewer C per §Reviewer C (elevation-only) below.

### Reviewer A — local correctness + gate integrity

Framing: verify every branch of `_classification_transition_exemption_permitted` returns the right answer for every combination of (linker present/absent, tracking enabled/disabled, owning-track present/absent, current class × last class over the 4-value cross product `{None, pass_by, approach, circling}²`, `current ∈ _dispatched_classifications`, safeword window active/inactive/expired). Verify the ledger update runs on every `dispatched_ok=True`. Verify the log lines fire on the intended paths. Verify D5b XCORR-1 short-circuit fires with the correct reason string.

Mutation drills (Reviewer A runs):
1. Mutate `_CLASSIFICATION_RANK` (`"circling": 2` → `"circling": 0`) → confirm D3 hop-3 assertion fails; restore.
2. Comment out the I4 check → confirm `test_reescalation_after_downgrade_gets_no_new_exemption` fails; restore.
3. Invert the I3 window check (`if window_active: return True`) → confirm D4 first-half fails LOUD; restore.
4. Neuter the ledger update (`_track.last_dispatched_classification = _cls` → `pass`) → confirm D3 hop-4/5 assertions fail; restore.
5. **(MED-1)** Remove the `from ._nm_cycle_a import is_life_safety_hazard` import → confirm `test_import_missing_fails_loud` fails with a NameError-anchored assertion (not a silent False); restore.
6. **(HIGH-1 / D5b)** Delete the `if exemption_active and classification in ("approach","circling"): return False, "classification_transition_exemption"` early-return in `_evaluate_burst_demotion` → confirm D5b fails with severity demoted to LOW; restore.
7. **(LOW-2)** Weaken the escalation predicate `current_rank <= last_rank` to `current_rank < last_rank` → confirm `test_predicate_boundary_is_strict_le` fails; restore.
8. **(MED-3)** Replace `_dispatched_classifications: set[str]` with a `_exemption_used: bool` and adapt the gate → confirm D3b (`test_multi_escalation_pass_by_approach_circling_gets_two_exemptions`) fails with dispatch count 2 instead of 3; restore.

### Reviewer B — cross-coordinator + state-machine integrity + restart

Framing: trace Frigate event → linker `record_event` → early classify → cooldown/exemption gate → severity resolve → coercion RAISE → XCORR-1 demote (with `exemption_active` threaded) → NM async_notify → NM safeword gate → NM dedup gate → `dispatched_ok` → `note_alert_dispatched` → ledger update. Verify:

- No double-emit on the exemption hop.
- S4 (in-flight guard) interaction: an exemption-permitted dispatch that hits in-flight is suppressed AND does not consume the exemption ledger (ledger update lives in `dispatched_ok`, which S4 short-circuits before reaching). Verify by trace.
- Restart behavior: track dies → next observation opens a new track with empty ledger → first escalation earns exemption. Reviewer B must construct or gesture at a restart test even though the runtime is RAM-only; operator-visible re-arm behavior documented on the field docstring per LOW-4.
- Vehicle leg (`perimeter_alert.py:2331-2570`) is untouched and unaffected.
- XCORR-1 threading: `exemption_active` is set exactly where the exemption gate returned True, is passed as a kwarg to `_evaluate_burst_demotion`, and the helper's new early-return is unreachable when `exemption_active=False` (byte-identical old behavior). No silent flag-carrying across events.
- NM dedup (S7 / D7): re-verify no HIGH-HIGH collision structurally; the test guards regression.
- The contract comment at `notification_manager.py:387` is present.
- Independent enumeration: re-grep every early-return in `_async_handle_perimeter_trigger`; any new dispatch-loss mode introduced by the two-step gate is a finding.

### Reviewer C (elevation-only) — completeness + test authority

If operator elevates to Tier 2-DB, add a Reviewer C sole-jobbed on falsifying I1-I4 with real source mutation:

- Confirm D3 hop-3 assertion fails if the exemption is unconditionally denied (`return False` at top of helper); restore.
- Confirm D4 fails if the safeword check is moved AFTER the escalation check.
- Confirm D5b XCORR-1 pin fails if the `exemption_active` kwarg is dropped from the call site (not just from the helper) — proves the wire is load-bearing at BOTH ends.
- Re-enumerate every consumer of `last_dispatched_classification` / `_dispatched_classifications` after build (should be exactly one gate helper + one ledger updater); any additional read/write is a finding.

Enforces `PYTHONDONTWRITEBYTECODE=1` + `find … -name __pycache__ -exec rm -rf` before mutation runs.

---

## Verification steps (summary)

1. `pytest quality/tests/perimeter/test_circling_founding_case_transition.py quality/tests/perimeter/test_circling_label_transition.py -v` — all green (includes D3, D3b, D4, D5, D5b, D7).
2. `pytest quality/tests/perimeter/test_circling_founding_case.py quality/tests/perimeter/test_circling_severity_per_state.py -v` — predecessor's cycle still green (regression check).
3. Reviewer-A mutation drills 1-8 above — each produces a specific test failure; all restored.
4. Reviewer-B enumeration + XCORR-1 threading trace clean.
5. Full suite baseline diff vs `pre-review-v<version>` — no unrelated regressions.
6. `git tag pre-review-v<version>` before any review-fix work.
7. Live replay per D6; results written back into `docs/readmes/README_v<version>.md`.
8. `sensor.perimeter_circling_zero_dispatch_24h` at 0 in steady state (predecessor tripwire unchanged).

---

## Plan-completion tracking (deferrals)

- Vehicle-leg parallel treatment (transition exemption for car tracks) — deferred; separate card if ever warranted.
- Per-classification cooldowns (finer-grained than "one exemption") — deferred.
- Persisted ledger across restarts — deferred; not needed for the founding ask (restart re-arm behavior is bounded and operator-documented per LOW-4).
- Operator switch to disable the exemption independently of the linker — deferred; would go on the entity rung (Switch).
- Widening classification vocabulary beyond `{pass_by, approach, circling}` — out of scope; if ever added, `_CLASSIFICATION_RANK` gets the new entries and I2's ordering must be re-adjudicated.
- Dedup-key extension to include `classification` — NOT NEEDED today (D7 verifies structural non-collision). If the contextual-severity map ever grows a `(person, pass_by) → HIGH` mapping, D7 will fail and the one-line fix in `_is_deduplicated` is documented in D7.
