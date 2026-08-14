# PLANNING — CIRCLING-LABEL-1 (Option A: classification-transition cooldown exemption)

**Card:** CIRCLING-LABEL-1 (kanban.data.yaml). Operator adjudication 2026-08-14: **Option A approved** per orchestrator recommendation — one dispatch allowed through the per-camera cooldown when a track's classification TRANSITIONS, so the hop where `circling` forms produces one HIGH circling-labelled page.

**Thread:** perimeter. **Tier:** 2 (see §Tier classification for the adjudication vs elevating to 2-DB).

**Predecessor:** CIRCLING-SEVERITY-1 shipped v5.74.0 (D1/D2/D3 machinery + INV-M). That cycle's Review-A MEDIUM-A1 is exactly this card — INV-M held under the founding shape (pages happened) but the pages carried the wrong classification (pass_by/approach), because per-camera cooldown at `perimeter_alert.py:1053-1065` returns before the hop where `classify()` transitions to `circling`. This cycle is the narrow follow-up: not a new invariant, a targeted exemption to the existing cooldown for classification-transition events only.

---

## Institutional context verified

### Greps run

- `rg -n 'PERIMETER_ALERT_COOLDOWN_SECONDS' custom_components/…` → single consumer at `perimeter_alert.py:1057` inside `_async_handle_perimeter_trigger`. Constant defined once in `const.py`. **The cooldown has exactly one gate site** — the exemption is a single-site change.
- `rg -n 'last_dispatched_classification|last_classification' custom_components/…` → **no hits**. Field is genuinely NEW on `ExteriorTrack`.
- `rg -n 'note_alert_dispatched' custom_components/…` → 2 call sites (`perimeter_alert.py:1424` person, `:2556` vehicle — vehicle out of scope) and 1 write site (`exterior_track_linker.py:795`). **`alert_count` is incremented only inside the `dispatched_ok=True` branch** — verified at `perimeter_alert.py:1406-1424`. Confirms the CIRCLING-SEVERITY-1 D3 tripwire semantics are unaffected by this cycle: an exemption-permitted dispatch that succeeds still increments `alert_count`, so `sensor.perimeter_circling_zero_dispatch_24h` continues to fire only on true dispatch-loss paths (5/6/7 from the predecessor plan's trace). **NEW: the exemption changes the classification LABEL on some dispatches, not the dispatch COUNT beyond the +1 per transition.**
- `rg -n '_perimeter_silence_until|NM_SECURITY_HAZARDS' custom_components/…` → NM safeword window state lives at `notification_manager.py:387` (field), gate at `:1452-1488`. NM returns early on suppress **without raising**, so perimeter_alert sees `dispatched_ok=True` and reserves cooldown + calls `note_alert_dispatched`. **This is the load-bearing fact for I3 (safeword outranks exemption): a naive "always update `last_dispatched_classification` on `dispatched_ok`" would let a safeword-suppressed alert silently CONSUME the transition exemption — the operator would never get their HIGH circling page even after the window closed.** See §D2.
- `rg -n 'classify\(' custom_components/universal_room_automation/exterior_track_linker.py` → producer at `:686-716`; consumers at `perimeter_alert.py:1099-1104` (early, severity resolve), `:1152` (coercion), and `open_tracks_snapshot :769` (D3 diagnostic). The exemption gate needs a *third* call at the cooldown site — verified none exists today.
- `rg -n 'RAISE.*(approach|circling)|approach.*circling.*RAISE' custom_components/…` → continuation-coercion RAISE-only branch at `perimeter_alert.py:1188-1199`. This branch runs POST-cooldown; today it's dead for the 2-camera shape because the cooldown returns before severity is even re-resolved on the hop where `circling` forms. The exemption revives it for exactly one hop per transition. See §D3 for the interaction map.
- `rg -n 'force_immediate_security_image' custom_components/…` → `const.py:1520` (route-reason string) and `test_nm_image_delivery.py`. This is a NM-side snapshot/route-reason decision downstream of `nm.async_notify`; **it does not read `ExteriorTrack.last_dispatched_classification` and is unaffected by this cycle**. Exemption-permitted dispatches carry the same `_kwargs` shape as any other dispatch. Confirmed by reading `perimeter_alert.py:1375-1394`.
- `rg -n 'PERIMETER_BURST|_evaluate_burst_demotion' …` → XCORR-1 burst-demote at `perimeter_alert.py:1213-1233` runs AFTER severity map coercion and can only DEMOTE. An exemption dispatch at hop-3 has `prior_alerts_in_window >= 2` (hops 1 + 2 dispatched), so burst-demote will fire — but the coercion RAISE branch (:1188-1199) runs FIRST and, for `classification == "circling"` in `home_day/home_evening`, has already raised severity to `HIGH` (via contextual + map). Adjudication: burst-demote will attempt to floor at LOW, but only if it decides to demote. Verify against §D1 acceptance (Live: replay must produce HIGH, not LOW — if XCORR-1 demotes the transition dispatch, the founding-shape ask is unmet and we need a XCORR-1 exemption too). **This is a FINDING to be verified during build; the plan's expectation is that XCORR-1's `should_demote` returns False for a track with classified `circling` because the RAISE branch has already produced a HIGH — but a builder must confirm by reading `_evaluate_burst_demotion` and pin with a test.** See §Open build-time finding.

### Prior planning docs consulted

- `docs/planning/PLANNING_circling_severity.md` (rev-2, v5.74.0) — full read. This cycle is the "MEDIUM-A1 spinoff" carded from its Review A. The trace, INV-M, and D3 tripwire semantics are inherited and NOT changed.
- `docs/planning/PLANNING_safeword_window.md` — full read. Invariants I1 (never-blanket) and I2 (perimeter-only scope) constrain this cycle: the exemption cannot cause a safeword-windowed alert to leak. See §D2, §Falsifiable invariants.
- `docs/planning/PLANNING_consol_1_alerting_llmvision.md` §6 (contextual severity function) + §D2 — skimmed. Explains why `circling` in `home_day/home_evening` is `HIGH`, in `home_night/away/sleep/vacation` is `CRITICAL`. The exemption dispatch will emit whatever the contextual resolver says at the transition hop; per-state severity is not touched by this cycle.
- `docs/reviews/code-review/v5.74.0_circling_severity_d3_area.md` — full read (source of the card).

### Memory bodies pulled

- `feedback_suppression_needs_discharge.md` — the exemption is a *permission*, not a suppression. Discharge = the exemption is consumed by exactly ONE dispatch (or by a safeword window). Not restart-persisted (RAM-only, matches ExteriorTrack lifetime).
- `feedback_marginal_benefit_pushback.md` — the exemption is the SIMPLEST version (Option A per card recommendation). Alternatives B (widen invariant + counter) and C (accept) were adjudicated by the operator; not re-litigating.
- `feedback_hollow_test_anchors.md` + `feedback_wire_in_anchor_mandatory.md` — every new field and every gate branch gets a mutation-anchored drill (§Review C).

### Design docs read

- No `docs/Coordinator/PERIMETER_ALERT.md` present; the inline docstrings in `perimeter_alert.py` and `exterior_track_linker.py` are authoritative.

### Code locations surveyed end-to-end

- `custom_components/universal_room_automation/perimeter_alert.py:1028-1450` — the entire `_async_handle_perimeter_trigger` frame, including cooldown (:1049-1065), in-flight guard (:1067-1079), severity resolve (:1088-1117), coercion (:1119-1206), XCORR-1 burst-demote (:1208-1239), dispatch (:1370-1445).
- `custom_components/universal_room_automation/exterior_track_linker.py:85-135` (ExteriorTrack dataclass) + `:686-716` (classify) + `:782-802` (note_alert_dispatched).
- `custom_components/universal_room_automation/domain_coordinators/notification_manager.py:387, :1440-1488, :3442-3459` — perimeter silence window state, gate, and open path.
- `custom_components/universal_room_automation/const.py:1556-1635` (contextual severity function) + `:1662-1718` (adjacency graph — reused for the D1 test as in v5.74.0 D1).

---

## Falsifiable invariants (state up front)

The build ships iff **all four** hold across the whole reachable surface (D-framing reviewer, if elevated to Tier 3, re-enumerates from scratch; Tier 2 splits I1/I2 across reviewers A/B):

1. **I1 (exactly-one per escalating transition).** For any ExteriorTrack whose lifetime sequence of `classify(t)` observations at cooldown-gate entry produces the ordered class sequence `c_1, c_2, ..., c_n`, the number of dispatches PERMITTED BY THE TRANSITION EXEMPTION (i.e. permitted after the per-camera cooldown would otherwise have blocked) equals the number of *escalating* transitions in that sequence — where escalation is defined by the strict ordering `pass_by < approach < circling`. In particular, for the founding 5-hop shape (`pass_by → pass_by → circling → circling → circling`) the exemption permits exactly ONE additional dispatch (at hop 3), producing exactly ONE HIGH circling-labelled page beyond whatever the baseline cooldown allows.

2. **I2 (no re-dispatch on de-escalation).** A track whose classification transitions from `circling → pass_by` (or `circling → approach`, or `approach → pass_by`) at some later hop does NOT get a new exemption dispatch on that hop. `last_dispatched_classification` is updated on every exemption-permitted successful dispatch, but the *permission gate* only opens when `severity_rank(current) > severity_rank(last)`. Rationale: the operator ask is "the hop where circling forms produces one HIGH page"; there is no operator ask for a downgrade page.

3. **I3 (safeword window outranks exemption, and does not consume it).** While `nm._perimeter_silence_until` is active AND `hazard ∈ NM_SECURITY_HAZARDS` AND `hazard ∉ life-safety` (i.e. the safeword window would suppress a normal perimeter dispatch — the exact condition at `notification_manager.py:1468-1488`), the transition exemption is NOT permitted. `last_dispatched_classification` is NOT updated. When the window expires, the very next hop whose `classify()` differs from `last_dispatched_classification` will fire the transition dispatch normally. Rationale: preserve operator-invoked silence (safeword I1/I2) AND preserve the transition-dispatch guarantee once silence lifts.

4. **I4 (flap-bounded).** Regardless of oscillation shape, the exemption fires AT MOST ONCE per `(track, target_classification)` pair over the track's lifetime — where `target_classification` is the class the track transitioned INTO. A track oscillating `pass_by ↔ circling ↔ pass_by ↔ circling` gets ONE exemption dispatch (the first `→ circling` transition) and no more. Bounds the worst-case per-track exemption budget at `|{pass_by, approach, circling}| - 1 = 2` (one for `→ approach` if it ever escalates, one for `→ circling` if it ever escalates), which is small, predictable, and monotone in the per-track lifetime. See §D1 for the mechanism (`_dispatched_classifications: set[str]` alongside `last_dispatched_classification`).

**Combined with the predecessor's INV-M**, the cycle-level guarantee is: *"a track whose classification escalates produces EXACTLY ONE additional dispatch for that escalating transition, and never any dispatch while a safeword window covers it, and never more than one per target-classification per track lifetime."*

---

## Adjudicated design decisions (embedded in the invariants above)

The operator asked the plan to adjudicate several points. Each is resolved below; no operator decisions are outstanding.

- **Transition-DOWN direction (ask 1).** Adjudicated as I2: exemption is ESCALATING-only, using the strict ordering `pass_by < approach < circling`. Chosen over a "transition-set" approach (any change permits) because the founding ask is escalation-only and a downgrade page has no consumer. Implementation: compare severity rank of `classify(t)` vs `last_dispatched_classification` at the gate.
- **Flap bound (ask 2).** Adjudicated as I4: **one exemption per `(track, target_classification)` pair lifetime**, tracked via a `set[str]` field on ExteriorTrack. Chosen over a numeric per-track budget because (a) it's the simpler predicate (no counter to reason about); (b) it maps exactly to the operator intent ("one HIGH page at the hop circling forms" — once per track per class); (c) the natural upper bound is 2 (approach, circling), which is already small.
- **Restart (ask 3).** Adjudicated as: **RAM-only. State dies with the track.** ExteriorTrack itself is RAM-only (predecessor plan §D3 reset semantics). If HA restarts mid-track, the track is lost and the exemption ledger goes with it — the next re-observation opens a new track with an empty `_dispatched_classifications` set, and the first hop where `classify()` returns non-`pass_by` gets its exemption. Documented on the field's docstring. Not a functional concern (the operator wanted one HIGH page at circling formation; if a restart interrupts, the next formation still produces one).
- **Continuation-coercion RAISE + `force_immediate_security_image` (ask 4).** RAISE branch at `perimeter_alert.py:1188-1199` is REVIVED for exemption dispatches: the exemption releases the flow past the cooldown gate; the flow then hits the coercion block with `classification == "circling"`, and (in `home_day/home_evening`) the contextual severity is already `HIGH`, and coerced-from-map is `MEDIUM` — `HIGH > MEDIUM` so no raise occurs; severity stays `HIGH`. In `home_night/away/sleep/vacation`, contextual is `CRITICAL` and coerced is `CRITICAL/HIGH` — no raise; stays `CRITICAL`. Net: coercion is a no-op on exemption dispatches given today's map, but the branch is exercised (verified by test D5). `force_immediate_security_image` is decided at the NM layer downstream of `nm.async_notify` based on hazard/severity — unaffected by this cycle. Verified by grep.
- **Safeword window (ask 5).** Adjudicated as I3: the exemption checks `nm._perimeter_silence_until` and defers when the window would suppress. Chosen over "let the exemption fire and let NM suppress" because NM's silent-suppression semantics (returns early without raising, but `dispatched_ok=True` from perimeter_alert's POV) would consume the exemption without paging. See §D2 for the exact predicate.
- **Knobs on the ladder (ask 6).** **ZERO new knobs.** The exemption is structural: no threshold, no window, no toggle. Kill-switch semantics are inherited from the linker's existing `tracking_enabled` (fire axe: no tracks → no classification → no exemption) and `TRACK_LINK_WINDOW_S == 0` (byte-identical to no-linker). If a future operator wants to disable the exemption specifically without disabling the linker, that is a separate cycle with a proper Number/Switch on the entity rung.

---

## Non-goals (explicit)

- Not changing `PERIMETER_ALERT_COOLDOWN_SECONDS` or introducing per-classification cooldowns.
- Not touching the vehicle leg (`perimeter_alert.py:2331-2570`). Person only.
- Not adding an ack/repeat engine to HIGH circling. HIGH pages once, no repeat — same as CIRCLING-SEVERITY-1.
- Not persisting `last_dispatched_classification` or `_dispatched_classifications` across HA restarts (see §Adjudicated design decisions ask 3).
- Not changing D3 tripwire semantics. `sensor.perimeter_circling_zero_dispatch_24h` continues to count `alert_count == 0` classified-circling tracks; the exemption dispatch increments `alert_count` on success (verified above), so the tripwire only fires on real dispatch-loss.
- Not changing NM safeword-window behavior. Only *reading* `_perimeter_silence_until` to gate the exemption.
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
last_dispatched_classification: str | None = None
_dispatched_classifications: set[str] = field(default_factory=set)
```

No other change to the linker in D1. `classify()` is untouched. `note_alert_dispatched()` is untouched at this deliverable — the update to the two new fields happens at the perimeter_alert call site (D2), which is the only place with visibility into whether the dispatch used the exemption gate. **Rationale for locating the update at the caller, not the linker:** the linker is not privy to `dispatched_ok` semantics or safeword-window state; keeping the exemption ledger's updates co-located with the exemption gate is single-source-of-truth (one function updates it, one function reads it).

#### Acceptance Criteria
- **Verify:** `ExteriorTrack` dataclass has both fields; defaults are `None` and `set()`.
- **Test:** `test_exterior_track_dataclass_has_transition_ledger` in `quality/tests/perimeter/test_circling_label_transition.py`.

---

### D2 — Transition-exemption gate at the cooldown site

**File:** `custom_components/universal_room_automation/perimeter_alert.py` (~`:1049-1065`).

Replace the plain cooldown block with a two-step gate: cooldown check FIRST, then (on cooldown-would-block) a transition-exemption check.

Pseudocode (the builder writes exact source):

```python
# --- 3. Per-camera cooldown (outer, authoritative rate limit) ---
cooldown_key = self._camera_key_for_sensor(entity_id) or entity_id
last_alert = self._last_alert.get(cooldown_key)
cooldown_would_block = (
    last_alert is not None
    and (now - last_alert).total_seconds() < PERIMETER_ALERT_COOLDOWN_SECONDS
)

if cooldown_would_block:
    # CIRCLING-LABEL-1: classification-transition exemption.
    # Permit ONE additional dispatch when the owning track's current
    # classification represents an ESCALATION over the last dispatched
    # classification, and the exemption has not already been consumed
    # for this target classification, and no safeword window is active.
    exemption_permitted = self._classification_transition_exemption_permitted(
        cooldown_key=cooldown_key,
        entity_id=entity_id,
        now=now,
    )
    if not exemption_permitted:
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

New helper `_classification_transition_exemption_permitted(...)`, private to `PerimeterAlertManager`:

```python
_CLASSIFICATION_RANK = {"pass_by": 0, "approach": 1, "circling": 2}

def _classification_transition_exemption_permitted(
    self, *, cooldown_key: str, entity_id: str, now: datetime,
) -> bool:
    # I3: safeword window outranks. If NM would suppress this hazard
    # under the current window, do NOT permit the exemption (and do
    # NOT consume it). Read the state directly — NM exposes it as a
    # field and the perimeter manager already reaches into
    # hass.data[DOMAIN] for the linker; same pattern.
    nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
    if nm is not None:
        window_active = (
            getattr(nm, "_perimeter_silence_until", None) is not None
            and dt_util.utcnow() < nm._perimeter_silence_until
            and not is_life_safety_hazard(self.hass, NM_HAZARD_EXTERIOR_PERSON)
        )
        if window_active:
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

    # I2: ESCALATION only.
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

**Institutional-context note.** The private-attribute reach into `nm._perimeter_silence_until` mirrors the existing pattern of `_linker._tracks` reach from `perimeter_diagnostics` (documented at `exterior_track_linker.py:147-151`). Add a symmetric one-line contract comment at `notification_manager.py:387` noting that `perimeter_alert._classification_transition_exemption_permitted` reads this field directly — refactor tripwire.

#### Acceptance Criteria
- **Verify:** cooldown-block path unchanged when no owning track (linker absent, or `find_owning_track` returns None).
- **Verify:** cooldown-block path unchanged when owning track's classification is not an escalation over `last_dispatched_classification`.
- **Verify:** cooldown BYPASSED exactly once per escalating transition (I1) — bypass fires, dispatch reaches NM, and subsequent same-classification hops within the cooldown window are re-blocked.
- **Verify:** no bypass when NM safeword window is active (I3); after window expiry the very next escalating hop bypasses.
- **Verify:** no bypass when `classification in track._dispatched_classifications` (I4 flap bound).
- **Verify:** the contract comment at `notification_manager.py:387` is present.
- **Test:** `test_transition_exemption_bypasses_cooldown_on_escalation`, `test_no_exemption_on_de_escalation`, `test_no_exemption_when_target_class_already_dispatched`, `test_no_exemption_when_safeword_window_active`, `test_exemption_available_after_safeword_window_expires`, `test_ledger_updates_on_baseline_dispatch_too`, `test_gate_returns_false_when_linker_absent`, `test_gate_returns_false_when_tracking_disabled`.

---

### D3 — Regression test: founding 5-hop shape yields ONE HIGH circling page

**File:** `quality/tests/perimeter/test_circling_founding_case_transition.py` (NEW).

Extends the v5.74.0 `test_circling_founding_case.py` pattern with the exemption's expected effect. Feed the exact founding sequence (`back_yard, front_side_ptz, back_yard, front_side_ptz, back_yard`), house_state `home_day`, real `ExteriorTrackLinker` with `set_adjacency(EXTERIOR_ADJACENCY_GRAPH)`, spy NM.

Assertions (in order):

- Precondition: `len(linker.open_tracks) == 1` after event 3 (adjacency-loaded sanity, per predecessor D1 lesson).
- Hop 1 (`back_yard`): dispatch #1. `classify == "pass_by"`. Severity per contextual resolver (`home_day` + `pass_by` = the "pass_by home_day" arm — likely `LOW`; whatever the resolver returns, pin the exact value read at test time — no hardcoded strings, per predecessor D2 build-pred #3).
- Hop 2 (`front_side_ptz`): dispatch #2 (different camera → no cooldown). `classify == "pass_by"`.
- Hop 3 (`back_yard` — same camera as hop 1, within 300s cooldown): **exemption fires**. `classify == "circling"` (revisit_count now ≥ 1). Dispatch #3 reaches NM at severity `HIGH` (contextual `home_day + circling` override at `const.py:1596-1597`). This is the founding-shape acceptance criterion.
- Hop 4 (`front_side_ptz` — same camera as hop 2, within cooldown): `classify == "circling"` still, but `circling ∈ track._dispatched_classifications` — no exemption, cooldown blocks. `spy_nm.async_notify.call_count == 3`.
- Hop 5 (`back_yard`): same as hop 4. `spy_nm.async_notify.call_count == 3`.

Final state:
- `track.alert_count == 3` (hops 1, 2, 3 all dispatched successfully).
- `track.last_dispatched_classification == "circling"`.
- `track._dispatched_classifications == {"pass_by", "circling"}`.
- Exactly one of the three dispatches has `severity == Severity.HIGH` (hop 3); the earlier two have the pass_by severity.

#### Acceptance Criteria
- **Verify:** `pytest quality/tests/perimeter/test_circling_founding_case_transition.py -v` all green.
- **Verify:** the topology precondition fails loud when `set_adjacency` is skipped (proves adjacency is loaded — inherited D1 lesson).
- **Test:** `test_founding_shape_produces_exactly_one_high_circling_page`, `test_founding_shape_dispatch_count_is_three`, `test_founding_shape_ledger_final_state`, `test_founding_shape_topology_precondition`.
- **Live:** covered by D6.

---

### D4 — Test: safeword window outranks exemption (I3)

**File:** `quality/tests/perimeter/test_circling_label_transition.py` (NEW — will also host D1's dataclass test and D2's helper tests).

- Open a safeword window on NM (`_perimeter_silence_until = utcnow() + 30min`).
- Drive the founding 5-hop shape.
- Assert: hops 1-2 dispatch as normal (baseline cooldown allows them per-camera; NM silently swallows via existing safeword gate → `dispatched_ok=True` from perimeter_alert's POV → `alert_count` and ledger update BUT NM suppression_counter increments); hop 3 does NOT bypass cooldown because `_classification_transition_exemption_permitted` returns False (safeword active); `spy_nm.async_notify.call_count == 2` from perimeter_alert's calls, of which 2 are suppressed at NM (verify via `nm._perimeter_silence_suppressions`).
- Expire the window (`_perimeter_silence_until = utcnow() - 1min`).
- Feed one more hop on `back_yard`. **Now** the exemption fires (I3 second half: after window expiry, next escalating hop bypasses). Dispatch reaches NM successfully at HIGH.

**Adjudication for I3 subtlety.** The above test also exercises the interaction: under safeword, baseline hops 1-2 still update the ledger (`last_dispatched_classification` = `pass_by`), because they are NOT exemption dispatches — they use their own per-camera cooldown slot. So when the window lifts, the "last" is `pass_by`, current is `circling`, escalation holds, exemption fires. Verified.

#### Acceptance Criteria
- **Test:** `test_safeword_window_blocks_transition_exemption`, `test_transition_exemption_fires_after_safeword_window_expires`.
- **Verify:** NM `_perimeter_silence_suppressions` counter increments for the swallowed baseline dispatches — proves we're reading the real safeword gate, not a fixture-side skip.

---

### D5 — Test: coercion RAISE branch and XCORR-1 interaction on exemption dispatch

**File:** same as D4.

- Drive founding shape. At hop 3 (exemption fires), assert:
  - The dispatched severity is `HIGH` (contextual `home_day + circling` override).
  - The continuation-coercion RAISE branch at `perimeter_alert.py:1188-1199` is entered (spy via a debug-log capture or a monkeypatched marker). Since map value for `home_day/circling` is `MEDIUM < HIGH`, no raise occurs — severity stays `HIGH`. Assert `severity == Severity.HIGH` post-coercion.
  - XCORR-1 burst-demote decision is captured in `self._last_burst_decision[cooldown_key]`. **Verify `severity_after == "HIGH"`** — this is the open finding pin. If XCORR-1 demotes here, D5 fails LOUD and the builder must address (either by teaching XCORR-1 that classified-circling never demotes, or by moving the exemption dispatch outside the XCORR-1 block).

#### Acceptance Criteria
- **Test:** `test_exemption_dispatch_severity_survives_coercion`, `test_exemption_dispatch_severity_survives_xcorr1_burst_demote`.
- **Verify:** if the XCORR-1 pin fails, the failure message names the demoted severity so the builder sees the ingredient risk immediately.

See also §Open build-time finding.

---

### D6 — Live validation table (post-deploy)

Replay the founding-case shape live: two operator-triggered walks between `back_yard` and `front_side_ptz` (5 hops, ≤ 3 min) during `home_day`, matching the 2026-08-08 09:22 CDT founding case. Table filled in on ship-day and written back into `docs/readmes/README_v<version>.md` per CLAUDE.md "Record Live Validation Back Into the README" mandate.

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

**Replay under safeword (deferred / optional):** if the operator wants I3 confirmed live, open a "duke 1h" safeword, replay the shape, observe zero pages, wait for the window to expire, replay the escalation hop, observe one HIGH page. Not required for ship; nice-to-have for the README's validation ledger.

---

## Tier classification

**Adjudication: Tier 2 (two framing-disjoint reviews) — NOT elevating to Tier 2-DB.**

Standing policy (2026-06-08) elevates regression-prone work to Tier 2-DB by default. This cycle's regression profile:

- **Cross-coordinator ripple:** LOW. One direction only (perimeter_alert reads `nm._perimeter_silence_until`); no writes to NM state; no new signals; no changes to the linker's public API (only dataclass field additions).
- **Trust-hierarchy:** untouched. Presence / HVAC / safety unaffected.
- **Shared primitive:** the cooldown is the primitive, but the exemption is a single-site local gate, not a rewrite. The predecessor CIRCLING-SEVERITY-1 rebuilt the surrounding invariants at Tier 2-DB; this cycle adds a narrow additional path.
- **Load-bearing invariant surface:** small (4 invariants I1-I4, all locally verifiable). Predecessor's INV-M is preserved by construction — the exemption only ADDS dispatches, never removes them.

**Recommendation: Tier 2.** Reviewer A / Reviewer B framings below.

**Operator MAY elevate to Tier 2-DB** (standing per-CLAUDE.md "operator-elevated Tier 2-DB") if the interaction with the safeword window or XCORR-1 feels under-scoped. If elevated, add Reviewer C per §Reviewer C (elevation-only) below.

### Reviewer A — local correctness + gate integrity

Framing: verify every branch of `_classification_transition_exemption_permitted` returns the right answer for every combination of (linker present/absent, tracking enabled/disabled, owning-track present/absent, current class × last class over the 4-value cross product `{None, pass_by, approach, circling}²`, `current ∈ _dispatched_classifications`, safeword window active/inactive/expired). Verify the ledger update runs on every `dispatched_ok=True` (not just exemption dispatches). Verify the log lines fire on the intended paths (info on bypass, debug on suppress).

Mutation drills (Reviewer A runs):
1. Mutate `_CLASSIFICATION_RANK` (`"circling": 2` → `"circling": 0`) → confirm D3 hop-3 assertion fails (`current_rank <= last_rank` blocks the escalation); restore.
2. Comment out the I4 check (`if current in track._dispatched_classifications: return False`) → confirm a synthetic test forcing repeat-escalation is required and NOT present today, OR fabricate one for the review (a hop-4/5 that re-classifies down and then re-classifies up mid-track); restore.
3. Invert the I3 window check (`if window_active: return True`) → confirm D4 first-half fails LOUD (exemption fires under safeword and NM suppressions counter goes to 3 instead of 2); restore.
4. Neuter the ledger update (`_track.last_dispatched_classification = _cls` → `pass`) → confirm D3 hop-4/5 assertions fail (they now bypass because `last` never advanced); restore.

### Reviewer B — cross-coordinator + state-machine integrity + restart

Framing: trace Frigate event → linker `record_event` → early classify → cooldown/exemption gate → severity resolve → coercion RAISE → XCORR-1 demote → NM async_notify → NM safeword gate → `dispatched_ok` → `note_alert_dispatched` → ledger update. Verify:

- No double-emit on the exemption hop.
- Restart behavior: track dies → next observation opens a new track with empty ledger → first escalation earns exemption. Reviewer B must construct or gesture at a restart test even though the runtime is RAM-only.
- Vehicle leg (`perimeter_alert.py:2331-2570`) is untouched and unaffected.
- The XCORR-1 interaction (D5 pin) actually behaves as the plan predicts — Reviewer B independently reads `_evaluate_burst_demotion` and confirms it will not demote a classified-`circling` transition dispatch. If it will, this is a HIGH finding requiring plan/build revision.
- The contract comment at `notification_manager.py:387` is present so a future NM refactor renaming `_perimeter_silence_until` will surface the perimeter_alert cross-reach.
- Independent enumeration: re-grep every early-return in `_async_handle_perimeter_trigger`; any new dispatch-loss mode introduced by the two-step gate is a finding.

### Reviewer C (elevation-only) — completeness + test authority

If operator elevates to Tier 2-DB, add a Reviewer C sole-jobbed on falsifying I1-I4 with real source mutation:

- Confirm D3 hop-3 assertion fails if the exemption is unconditionally denied (`return False` at top of helper); restore.
- Confirm D4 fails if the safeword check is moved AFTER the escalation check (proves ordering matters — safeword must short-circuit).
- Confirm D5 XCORR-1 pin fails if severity is hardcoded HIGH in the test (proves the pin actually reads the post-XCORR-1 value, not a fixture-side value).
- Re-enumerate every consumer of `last_dispatched_classification` / `_dispatched_classifications` after build (should be exactly one gate helper + one ledger updater); any additional read/write is a finding.

Enforces `PYTHONDONTWRITEBYTECODE=1` + `find … -name __pycache__ -exec rm -rf` before mutation runs (predecessor's C discipline).

---

## Open build-time finding (must be resolved before deploy)

**XCORR-1 interaction with the exemption dispatch.** The plan predicts XCORR-1 burst-demote will NOT demote the exemption dispatch because (a) the contextual resolver already produced HIGH for `home_day + circling`, (b) the coercion RAISE branch runs BEFORE XCORR-1, (c) `_evaluate_burst_demotion` reads `prior_alerts_in_window` — which will be ≥ 2 at hop 3 (the exemption's whole point) — but the demote decision also inspects sibling/adjacent activity, and the plan has NOT read `_evaluate_burst_demotion` end-to-end. **The builder MUST read `perimeter_alert.py:1213-1233` + the helper end-to-end BEFORE writing D5, confirm the prediction, and if wrong, either (i) teach XCORR-1 to skip demote when classification is `circling` and the flow used the exemption, or (ii) move the exemption dispatch past XCORR-1 by short-circuiting the block for exemption events.** If (i) or (ii) becomes necessary, the change adds one more site to Reviewer A's mutation drill list.

This is flagged as an open finding rather than resolved because the plan writer did not have `_evaluate_burst_demotion` fully mapped and refuses to fabricate a specification. Per no-fabrication rule.

---

## Verification steps (summary)

1. `pytest quality/tests/perimeter/test_circling_founding_case_transition.py quality/tests/perimeter/test_circling_label_transition.py -v` — all green.
2. `pytest quality/tests/perimeter/test_circling_founding_case.py quality/tests/perimeter/test_circling_severity_per_state.py -v` — predecessor's cycle still green (regression check).
3. Reviewer-A mutation drills 1-4 above — each produces a specific test failure; all restored.
4. Reviewer-B XCORR-1 read-through — open finding closed, either as "prediction holds, D5 pin passes" or as an in-cycle fix.
5. Full suite baseline diff vs `pre-review-v<version>` — no unrelated regressions.
6. `git tag pre-review-v<version>` before any review-fix work.
7. Live replay per D6; results written back into `docs/readmes/README_v<version>.md`.
8. `sensor.perimeter_circling_zero_dispatch_24h` at 0 in steady state (predecessor tripwire unchanged).

---

## Plan-completion tracking (deferrals)

- Vehicle-leg parallel treatment (transition exemption for car tracks) — deferred; separate card if ever warranted.
- Per-classification cooldowns (finer-grained than "one exemption") — deferred; would need XCORR-1-style backpressure reasoning.
- Persisted ledger across restarts — deferred; not needed for the founding ask.
- Operator switch to disable the exemption independently of the linker — deferred; would go on the entity rung (Switch), not a code-level knob.
- Widening classification vocabulary beyond `{pass_by, approach, circling}` — out of scope; if ever added, `_CLASSIFICATION_RANK` gets the new entries and I2's ordering must be re-adjudicated.
