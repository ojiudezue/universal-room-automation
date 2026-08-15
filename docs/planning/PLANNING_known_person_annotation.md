# PLANNING — Known-Person Annotation Pipeline v1 (ANNOTATE, don't suppress) — rev-3

**Rev-3 (2026-08-14):** Plan-review fix-up per `docs/reviews/code-review/known_person_annotation_plan_review.md` (commit 4e468d37f). All CRIT/HIGH/MED/LOW findings resolved in-plan with orchestrator adjudications. Summary at end.

**Rev-2 (2026-08-14):** Operator answered the three open decisions from rev-1. Folded in as **BINDING**:

1. **Identity sources = LOCAL ONLY.** Frigate-2 face recognition + UniFi Protect face detection. **llmvision is EXCLUDED from identity** — no household reference photos leave the LAN. Any cloud-identity alternative is REJECTED.
2. **D3 stranger-alert leg = FOLD IN NOW** (overrides rev-1's DEFER recommendation). The unknown-face stranger-alert leg builds in the SAME cycle. It is the successor to the retiring doorbell face automation. **KP-ESCALATE-1 was declined as a standalone card and its scope is absorbed here** — this cycle's origin is that absorption.
3. **Annotation shape = IN-FIRST-MESSAGE ONLY.** The identity line rides the first alert message on its own line (default format: `Person detected — likely {names}.`). The annotate-by-edit / follow-up-message alternative is REJECTED — see D1 rationale.

**Card:** KP-ESCALATE-1 (absorbed / declined as standalone; scope folded here). Cycle now delivers BOTH the annotation half (known face → annotate) AND the stranger-alert half (unknown face at doorbell → escalate) — the two halves of the retiring doorbell face automation.

**Operator direction (2026-08-14, original):** exterior perimeter alerts today consult ZERO member/face data — a person page is identical to me whether it is my wife walking up the driveway or a stranger. **v1 = ANNOTATE (known) + ESCALATE (unknown, doorbell only)**. When a face/identity signal is available for a perimeter person detection, the alert message gains a single line: `Person detected — likely <Name>`. The alert itself is preserved byte-for-byte otherwise. **No suppression, no severity change, no dedup change of the base alert in v1.** The stranger leg is an ADDITIVE emission on top of the byte-identical base — never a delay or gate on it.

**Phase 2 (explicitly PARKED, not in this cycle):** per-person opt-in suppression / demotion. **Trigger to un-park:** annotation accuracy proven over N organic events with a per-annotation ledger — see D2. Do NOT design phase-2 machinery into v1.

**Tier:** **Tier 2-DB** (elevated per standing regression-prone policy). The pipeline threads external identity signals into `perimeter_alert.py` — the same alert path CONSOL-1 shipped through — where one missed emission site or one stale-identity leak is either a false accusation on a family member, a silenced-in-practice stranger, or (with the folded D3) a false stranger escalation on an enrolled household member. Three framing-disjoint reviews required (A=local correctness of the annotation adapter + freshness/coverage math + false-stranger guard arithmetic, B=integration/state-machine — every perimeter emission site AND **every NM hazard-consumer set** (see CRIT-1 fix in D3) + no accidental suppression + byte-identical base fall-through + stranger leg strictly additive, C=ledger authority via real per-site source mutation, extended to cover the stranger-emission site). Plan review Tier 2 (one adversarial pre-build pass, re-enumerating emission sites and identity producers independently, AND re-enumerating stranger-leg guard bypass paths).

**Branch:** `feature/known-person-annotation-v1`.
**Scope target:** ≤ ~7 files touched (const, new adapter, perimeter_alert wire for BOTH legs + extracted `_dispatch_to_nm` method, ledger extension, config-flow, one sensor, one stranger-leg guard module or inline); D0 is a probe-only artifact and touches no runtime code.

---

## Falsifiable invariant (Reviewer D framing)

> **INV-KP:** Under any legal config, for any perimeter person-detection that reaches `PerimeterAlertManager._async_handle_perimeter_trigger`:
> (a) the BASE alert dispatches to NM on the same code path, with the same `hazard_type`, `severity`, `title`, `coordinator_id`, `location`, snapshot, and cooldown/dedup behavior as it does today with BOTH the annotation adapter AND the stranger leg disabled — proven by a byte-identical `message` and identical `_kwargs` when the adapter returns `None` and the stranger leg is inert;
> (b) when the adapter returns a non-empty annotation string, the ONLY delta in the dispatched BASE payload is exactly one appended line of the form `Person detected — likely <Name(s)>` (default template) inserted at a defined position; nothing else in the base payload changes;
> (c) the annotation adapter's total wall time is bounded by `known_person_annotation_budget_ms` (rung-3 Number entity, default TBD by D0 latency data); on budget expiry, exception, empty result, or stale identity beyond the freshness window, the adapter returns `None` and the dispatch proceeds as (a) — with a ledger row recording `annotation_status ∈ {none, timeout, exception, stale, no_producer, disabled, kill_switched, unrecognized_name, empty}`;
> (d) the adapter has NO write path — it cannot mutate NM state, cooldowns, `_dispatch_in_flight`, house_state, presence trackers, or `sensor.*` values;
> **(e) STRANGER LEG (folded D3) is strictly ADDITIVE.** The stranger leg is scheduled as its OWN `entry.async_create_background_task(...)` created **ONLY AFTER the `await nm.async_notify(...)` for the base dispatch has completed** (not after task creation, not after enqueue — after the await returns). The stranger-leg background task MUST NOT hold, observe, read, or release the enclosing `_dispatch_in_flight` guard; it maintains its OWN in-flight guard `_stranger_leg_in_flight` keyed on `_camera_key_for_sensor(entity_id)`, so a hanging identity probe on camera X can never suppress the next base trigger on camera X. No code path in the stranger leg — including its guard evaluation, its identity re-read, or its escalation dispatch — can delay, block, mutate, dedup, or replace the base alert. Proven by: (i) the base dispatch's `_kwargs` are byte-identical whether the stranger leg fires, defers, or is disabled; (ii) mutation-neutering the entire stranger-leg module leaves the base dispatch test suite green; (iii) the stranger leg has NO write access to any of the base-dispatch state listed in (d); (iv) with `stranger_leg_identity_attempt_timeout_s=30s`, back-to-back doorbell events at t=0 and t=6s BOTH produce a base alert (the second is NOT suppressed by a still-held `_dispatch_in_flight` from the first); (v) an interleave-slice fixture where the stranger-leg task yields the loop mid-evaluation cannot observe a partial-write of NM state from the base leg.

Reviewer D falsifies (d) AND (e) especially: enumerate every accessor the adapter reaches AND every accessor the stranger leg reaches; any read that could trigger a state-machine side effect (RestoreEntity load, dispatcher fire, coordinator refresh) is a leak. For (e), Reviewer D must exhibit a legal-config repro OR prove no legal config exists where a stranger-leg failure (guard exception, identity re-read hang, dispatch error) can delay base delivery, AND must explicitly name `_dispatch_in_flight` as forbidden read/hold state.

---

## Institutional context verified

**Prior planning consulted:**
- `docs/planning/PLANNING_exterior_person_escalation.md` — the original perimeter → NM wiring plan; establishes `hazard_type=exterior_person`, house-state severity map, and the `_async_handle_perimeter_trigger` shape we hook into.
- `docs/planning/PLANNING_consol_1_alerting_llmvision.md` — CONSOL-1 shipped `perimeter_enrichment.py` (the adapter shape being REUSED here) with `INV-ENRICH-NEVER-SILENCES` / `INV-ENRICH-NON-EMPTY` / `INV-ENRICH-BUDGETED` — v1 mirrors these invariants for identity.
- `docs/planning/PLANNING_safeword_window.md` — invariant I2 ("perimeter-only") — the operator's duke-window is defined against `NM_SECURITY_HAZARDS` set membership. CRIT-1 fix consulted this doc to adjudicate whether `exterior_unknown_person` joins the set.
- `docs/planning/AUDIT_consol_1_d0_probe.md` — the probe-first pattern this plan copies for D0.
- `docs/planning/AUDIT_frigate1_retirement_inventory.md` — Frigate-1 retirement inventory (needed to know which face producers are still live on Frigate-2).
- kanban `KP-ESCALATE-1` + its `direction_2026_08_14` note — the source-of-truth direction (declined as standalone; absorbed here).

**Code surfaces surveyed:** (unchanged from rev-1 — see rev-1 for line-cited list)
- `perimeter_alert.py:1272-1436` insertion point for base + annotation; stranger-leg emission site is a NEW `entry.async_create_background_task` scheduled AFTER the base `await nm.async_notify(...)` returns (see D3 for exact placement + reused `self._dispatch_to_nm(...)` extracted method).
- `perimeter_enrichment.py` — REUSED adapter shape.
- `camera_census.py:2317-2345`, `:2347-2400`, `:2946-3080` — Frigate face producer + freshness-gated view + display-name map.
- `domain_coordinators/presence.py:4378-4420`, `:570-571,919-920,4370-4376` — interior face state (informational only; v1 does not modify).
- `sensor.py:3485,5040-5042` — face state surface reused as read source.
- `const.py:1467` — `NM_HAZARD_EXTERIOR_PERSON` base hazard type (REUSED unchanged for base).
- `const.py:1509-1512` — `NM_SECURITY_HAZARDS` frozenset (**CRIT-1 fix: `exterior_unknown_person` JOINS this set** — see D3 subsection "NM hazard-consumer enumeration"). Note: joining this set means the duke-window (safeword) also suppresses stranger emissions during operator-declared perimeter-tuning windows. This is intentional per operator adjudication (see D3 note).
- `const.py:1542-1553` — `NM_HAZARD_EXTERIOR_PERSON_SEVERITY_BY_HOUSE_STATE`; `const.py:1556` — resolver. Mirrored to a NEW `NM_HAZARD_EXTERIOR_UNKNOWN_PERSON_SEVERITY_BY_HOUSE_STATE` (see D3 severity table).
- `const.py:3685-3691` — `MEMORY_INELIGIBLE_HAZARD_TYPES` frozenset (**CRIT-1 fix: `exterior_unknown_person` JOINS**).
- `const.py:1526-1533` — CONSOL-1 route reasons; new route-reason enum values appended (LOW-1 fix).
- `notification_manager.py:1368, 1445, 1471, 1709` — force-immediate + safeword scope + recipient bypass — all gate on `NM_SECURITY_HAZARDS`. Joining the set gives the stranger emission the correct routing at all four sites.
- `const.py` — `CONF_KNOWN_PERSON_*`, `CONF_FACE_*`, `CONF_PERSON_ANNOTATION_*`, `CONF_STRANGER_*` greps returned NONE — all knobs NEW.

**REUSED vs NEW tally:**
- REUSED: adapter shape (perimeter_enrichment.py), Frigate face accessor (`_get_face_recognized_persons_fresh` + `_get_face_recognized_person_names`), presence tracker face state (read-only reference), hazard/severity/dispatch path for base (unchanged), `tracked_persons` integration-config list, `CENSUS_FACE_RECOGNITION_WINDOW_SECONDS` freshness constant, `sensor.face_recognized_persons` surface, `_camera_key_for_sensor(entity_id)` fusion helper (REUSED by stranger cooldown key per MED-3 fix and by stranger `_stranger_leg_in_flight` guard key per HIGH-1 fix), house-state severity map SHAPE (mirrored for the stranger leg with a +1-notch delta table — see D3), **base `snapshot_url` and `snapshot_path` REUSED verbatim by the stranger emission** (LOW-2 fix: same file, no re-capture, preserves privacy invariant — no new snapshot write path).
- NEW: `known_person_annotation.py` adapter module, `CONF_*` for enable / per-camera producer bindings / annotation format / **stranger-leg enable / doorbell-camera set / false-stranger guard knobs** (see D3), one module-const kill switch (annotation) + one (stranger leg), two rung-3 Number entities (annotation budget + freshness), **three rung-3 Number entities for the false-stranger guard (identity-attempt timeout, confidence floor, enrollment-coverage gate — see D3)**, ledger row extension (`annotation_status`, `annotation_identity`, `annotation_producer`, `annotation_identity_age_s`, `annotation_latency_ms`, `stranger_leg_status`), NEW `hazard_type=exterior_unknown_person`, NEW 4-value route-reason enum (LOW-1 fix): `NM_ROUTE_REASON_ANNOTATED`, `NM_ROUTE_REASON_ENRICHED_AND_ANNOTATED`, `NM_ROUTE_REASON_STRANGER_ESCALATION` (existing `NM_ROUTE_REASON_ENRICHED` + `NM_ROUTE_REASON_ENRICHMENT_FAILED_FALL_THROUGH` stand), NEW `NM_HAZARD_EXTERIOR_UNKNOWN_PERSON_SEVERITY_BY_HOUSE_STATE` map, **NEW extracted method `PerimeterAlertManager._dispatch_to_nm(...)`** (HIGH-2 fix: refactored from the private closure `_do_dispatch`, reused by both base and stranger legs — see D3), NEW opt-in list `CONF_STRANGER_LEG_NO_CONFIDENCE_PRODUCERS` (MED-2 fix), NEW `_stranger_leg_in_flight` per-camera-key guard (HIGH-1 fix — separate from `_dispatch_in_flight`).

**Memory bodies pulled:** `feedback_measure_before_build.md`, `feedback_marginal_benefit_pushback.md`, `feedback_suppression_needs_discharge.md` (v1 base has no suppression; the stranger leg's guard is a deferral on the *stranger emission only*, never on the base — discharge = timeout window with backstop = fire OR drop-with-ledger, spec'd in D3), `feedback_hollow_test_anchors.md`, `feedback_no_fabrication.md`, `feedback_wire_in_anchor_mandatory.md` (D1 AND D3 acceptance require behavioral tests that go red on call-site neuter).

**Design docs:** No `docs/Coordinator/perimeter*.md`; perimeter is module-scoped.

**Not verified / open (all folded into D0 tasks — see below):**
- UniFi Protect face detection availability on operator's actual devices.
- Whether Doubletake survived the Frigate-1 retirement.
- `tracked_persons` currency (rev-1 open decision #4 — now an explicit D0 task).
- Message format ergonomics (rev-1 open decision #5 — default stands unless operator objects; explicit D0 confirm task).

---

## D0: Read-only measurement probe (GATES EVERYTHING, gates BOTH legs)

**Purpose (per CLAUDE.md "Measure Before You Build"):** the plan's value and the shape of D1 AND D3 depend on empirical properties of identity signals that already exist on the running house. The stranger leg raises the stakes: identity-latency vs dispatch window matters MORE when a missing identity would fire a stranger escalation on a household member. Build the probe FIRST, run it against the live HA recorder + entity registry, commit the report as `docs/planning/AUDIT_known_person_d0_probe.md`, and gate D1/D2/D3 on its findings.

**Delivery form:** one Python script executed via `ssh ha "python3 -" < script.py` (same shape as the CONSOL-1 D0 probe). Read-only against `home-assistant_v2.db` (recorder) and the live entity/config registry. No runtime code changes.

**Pre-D0 tasks (folded from rev-1 open decisions #4 and #5, now BINDING D0 tasks):**

- **D0.pre.1 — `tracked_persons` currency audit.** Enumerate the integration-config `tracked_persons` list on the live entry. For each slug: does a `person.<slug>` entity exist? Does the person entity have `friendly_name` set to the display form the operator wants in the annotation line? Is anyone the operator considers household MISSING from the list? Surface as a bulleted diff in the D0 report. Operator curates the list BEFORE the coverage math in D0(c) runs — otherwise coverage math is distorted (anyone missing is invisible to the pipeline, which would also cause them to trigger stranger escalations in D3 unless enrolled).
- **D0.pre.2 — Message-format confirm.** The default proposal stands unless operator objects: `Person detected — likely {names}.` on its own line at the END of the message. Record confirm/override in the D0 report before D1 kickoff. (Rev-1 open decision #5 collapses to this: default binds unless operator objects during D0 review.)

**Questions the probe MUST answer:**

**(a) Identity-producer inventory per exterior camera (TODAY) — LOCAL ONLY.**
For each configured perimeter camera (from `CONF_PERIMETER_CAMERAS` on the live integration config entry):
- Is there a Frigate-2 face producer? (`sensor.<base>_last_recognized_face` present in registry — derive `<base>` per `camera_census._get_face_recognized_persons` algorithm.) If yes: what states has it emitted in the last 30 days? (SELECT DISTINCT state FROM states WHERE entity_id = ? — quantify how often it produces a real name vs `unknown/unavailable/no_match`.)
- Is there a UniFi Protect face attribute? (Inspect `camera.<name>` entity attrs and any `event.<name>_smart_detection` companion; look for `last_face_recognized` / `last_face_time` on any UP-platform entity — do NOT assume the attribute names; enumerate.)
- Is Doubletake still installed? (Registry grep `doubletake` — expected NO post Frigate-1 retirement, but confirm; if present, treat as an additional local producer candidate.)
- **(a.iii) Confidence-attribute distribution per producer (MED-1 fix).** For each Frigate face producer discovered, enumerate the confidence attribute: attribute name(s), min / mean / p50 / p95 confidence values over the 30-day window, and the distinct-value count for `unknown` verdicts vs recognized-name verdicts (i.e. what is the confidence distribution when the producer says `unknown`? when it says a real name?). Same enumeration for UP if it exposes a confidence attribute; if UP exposes NONE, record that producer under the D3 `CONF_STRANGER_LEG_NO_CONFIDENCE_PRODUCERS` review (MED-2). This histogram directly derives the `stranger_leg_confidence_floor` default (rung-3 Number) — the plan no longer invents `0.60`; the default comes from `p10` of recognized-name confidence values (or `p25` of `unknown` confidences, whichever is lower, so the floor accepts real recognitions but rejects the noise tail).
- **llmvision: OUT OF SCOPE for identity per rev-2 binding decision #1.** Do NOT probe llmvision as an identity source; it remains a scene-descriptor (CONSOL-1's role) and is EXCLUDED from producer bindings. No probe cycles spent on cloud-identity feasibility.

**(b) Latency + coverage on real perimeter events.**
Reconstruct the last ~30 days of perimeter person-detection events from the recorder (state ON transitions on any entity in `CONF_PERIMETER_CAMERAS` — mirror the trigger the alert manager itself uses). For EACH event:
- Was any local identity producer's `state.last_changed` within `[event_time − 30s, event_time + 30s]`? (Producer-per-camera from (a).)
- What was the identity value (name / `unknown` / `no_match` / no update)?
- Delta seconds between event and nearest identity update (signed: negative = identity arrived AFTER the alert).

Report as a per-camera table + a rollup histogram:
- % of events where a *real name* was available at event time − 0s (in-first-message annotation is viable — the ONLY shape v1 will build per rev-2 binding decision #3).
- % where a name arrived within +5s / +10s / +30s of event time (informational only — v1 will NOT build annotate-by-edit; this data feeds phase-2 planning).
- % where no name ever arrived within +60s (annotation would remain absent — this is the fall-through case AND the case the stranger leg needs to distinguish from "real stranger").

**(c) Enrollment coverage.**
For each `tracked_persons` slug on the (D0.pre.1-curated) integration config: has that person's face been recognized by ANY local producer at least once in the last 30 days? Persons with zero recognitions are effectively unenrolled — v1 cannot annotate them regardless of pipeline health, AND (critical for D3) they would fire false-stranger escalations at the doorbell. The enrollment-coverage rollup drives the D3 `stranger_leg_enrollment_coverage_gate` default.

**(d) Doorbell-specific unknown cadence (NEW for folded D3).**
Sub-probe restricted to the DOORBELL camera(s) (operator to identify in D0.pre.1; expected: the front-door doorbell). Over the same 30-day window:
- How many person-detection events occurred at the doorbell?
- Of those, how many had a producer identity resolve to a `tracked_persons` name within `[event, event + stranger_leg_identity_attempt_timeout_s]` (default candidate 15s — probe with 5s/10s/15s/30s buckets)?
- How many had a producer identity resolve to `unknown` / `no_match` in that window?
- How many had NO producer update in that window?

The (unknown + no-update) counts approximate the ACTUAL per-day cadence of the stranger leg firing today. Report as an events/day rollup. If this cadence exceeds ~10/day (order-of-magnitude — operator adjudicates), the false-stranger guard defaults need tightening OR the leg needs to gate on enrollment-coverage before firing.

**Adjudication rule (drives D1 + D3 gate):**
- If (b) shows ≥50% of events have a real name available at t=0 AND (c) shows ≥80% enrollment coverage for household members: D1 in-first-message ships as spec'd, D3 stranger leg ships with the D0-derived guard defaults.
- If (b) is weaker (30-50% at t=0) OR (c) is weaker (60-80% coverage): D1 still ships (in-first-message only per rev-2 binding), but D3 stranger leg's `enrollment_coverage_gate` defaults CLOSED — leg is enabled but the guard suppresses firing on any camera whose household enrollment is thin. Operator opens per-camera as coverage improves.
- If (b) <30% at any timing OR (c) <60% coverage: park v1 build entirely, publish D0 as-is, and revisit with a "producer coverage insufficient" verdict. Applies to BOTH legs — cannot ship the stranger leg on weak coverage (false-stranger risk is unbounded).
- Rev-1's "annotate-by-edit if identity typically arrives 5-15s late" branch is **REMOVED** per rev-2 binding decision #3. In-first-message is the only shape; the latency-late slice becomes an unannotated fall-through, not a delayed second message.

**Acceptance:**
- **Verify:** `docs/planning/AUDIT_known_person_d0_probe.md` committed with (a) producer inventory, (a.iii) confidence-attribute histograms, (b) latency histogram, (c) enrollment coverage table, (d) doorbell unknown cadence.
- **Verify:** D0.pre.1 tracked_persons audit result recorded, operator has curated the list.
- **Verify:** D0.pre.2 message-format decision recorded (default binds absent objection).
- **Verify:** every claim in D1 AND D3's design cites a row/number from the D0 report — no design number is asserted without a probe row. Specifically: `stranger_leg_confidence_floor` default MUST cite a row from D0(a.iii); `stranger_leg_enrollment_coverage_gate` MUST cite D0(c); `stranger_leg_identity_attempt_timeout_s` MUST cite D0(d).
- **Verify:** operator sign-off in the doc adjudicates BOTH the ship-vs-park verdict AND the D3 guard defaults from (a.iii) + (c) + (d).

---

## D1: Annotation wire (`known_person_annotation.py` adapter + perimeter_alert insertion)

**Gated on:** D0 (a)+(a.iii)+(b)+(c) meet the ship threshold.

**Shape (BINDING per rev-2 decision #3):** IN-FIRST-MESSAGE ONLY. The annotation adapter runs synchronously inside the base dispatch composition, budgeted. There is NO annotate-by-edit path, NO follow-up second message for late-arriving identity, NO delayed task. If identity is not available at composition time, the base alert dispatches unannotated, ledger records the fall-through class, and the event is done. Rationale: (i) per `feedback_marginal_benefit_pushback.md`, the by-edit shape introduces a new rare-fire delayed-task code path — categorically risky and hard to observe organically — for marginal coverage over in-first-message; (ii) the operator has bound the decision; (iii) the by-edit shape can be revisited post-D2 if the ledger shows the late-arriving slice is materially large.

**New module `custom_components/universal_room_automation/known_person_annotation.py`.** Mirrors `perimeter_enrichment.py` shape 1:1:

```python
async def annotate_perimeter_person(
    hass, camera_entity_id: str, event_time: datetime
) -> AnnotationResult | None:
    ...
```

Where `AnnotationResult` is a small dataclass carrying `(display_names: list[str], producer: str, identity_age_s: float, latency_ms: float, raw_identity: str, raw_confidence: float | None)`. On any failure class (kill switch, disabled, no producer bound, stale beyond window, budget expiry, exception, empty result, unrecognized-by-config name), returns `None`. **No exception escapes.**

**Producer resolution:** per-camera producer binding (see knobs). Adapter reads ONLY the bound producer's entity. Multi-producer per camera is out of v1 scope (adjudicate in D0 whether any camera actually has more than one).

**Freshness:** identity value's `state.last_changed` age must be ≤ `known_person_annotation_freshness_s` (rung-3 Number, default = D0-driven; upper bound = `CENSUS_FACE_RECOGNITION_WINDOW_SECONDS`). Older = `stale` → return `None`.

**Display-name mapping:** slug → display name via `tracked_persons` friendly-name lookup on the person entity registry (already the shape `_get_face_recognized_person_names` uses). If the recognized identity is not in `tracked_persons`, return `None` for annotation purposes — v1 does not annotate unrecognized-by-config names, to avoid rendering `Person detected — likely gardener_maybe`. **NOTE:** the raw identity + confidence are still surfaced to the stranger-leg guard in D3 via a sibling `probe_identity_for_stranger_guard(hass, camera_entity_id) -> IdentityProbeResult | None` accessor (picked shape) that returns the same read without the `tracked_persons` filter, so the D3 guard can distinguish "producer said a name we don't know" from "producer said unknown" from "producer said nothing". No coupling back through `AnnotationResult` — the two callers use two accessors.

**Budget:** `asyncio.wait_for` around the whole adapter body with `known_person_annotation_budget_ms` (rung-3 Number). Default TBD by D0; upper bound MUST be < remaining time to the existing enrichment dispatch such that the annotation never widens end-to-end alert latency beyond the current p95.

**Insertion site in `perimeter_alert.py`:** after the enrichment block that ends at L1362, before the extracted `self._dispatch_to_nm(...)` call (HIGH-2 fix: `_do_dispatch` closure is refactored to a method — see below). Compose:

```python
annotation: AnnotationResult | None = None
try:
    annotation = await annotate_perimeter_person(self.hass, entity_id, now)
except Exception:  # defense-in-depth — INV-KP (c)
    annotation = None
if annotation and annotation.display_names:
    joined = _format_annotation_names(annotation.display_names)
    message = f"{message}\n\nPerson detected — likely {joined}."
```

**HIGH-2 fix — extract `_do_dispatch` to a method.** The current `_do_dispatch` closure inside `_async_handle_perimeter_trigger` (`perimeter_alert.py:1366`) closes over 10 locals and is unreachable outside its enclosing function. Refactor to a module-level method on `PerimeterAlertManager` with explicit signature:

```python
async def _dispatch_to_nm(
    self,
    *,
    nm,
    entity_id: str,
    cooldown_key: str,
    hazard_type: str,
    severity: str,
    title: str,
    message: str,
    snapshot_url: str | None,
    snapshot_path: str | None,
    route_reason: str,
    coordinator_id: str,
    location: str,
) -> None:
    """Single dispatch shape for base + stranger legs. Owns _dispatch_in_flight ONLY for the base leg (see stranger leg for its own guard)."""
```

Both the base path (via `await self._dispatch_to_nm(...)` or `hass.async_create_task(self._dispatch_to_nm(...))` for the delayed shape) and the stranger leg (D3) call the SAME method. Rationale (adjudicated): duplicating the `nm.async_notify(...)` call at two sites is drift-risky on a dispatch path — a future change (retry, header injection, telemetry) applied at one site and missed at the other silently diverges. Extract-to-method is the one canonical shape. Duplication-shape REJECTED. `_dispatch_in_flight` remains the base-leg-only guard; the stranger leg has its OWN guard `_stranger_leg_in_flight` (HIGH-1 fix, see D3).

**Byte-identical fall-through proof:** the annotation branch is the ONLY code the adapter reaches on the message; if `annotation is None or not annotation.display_names`, `message` and all downstream `_kwargs` to `_dispatch_to_nm` are unchanged relative to today. Test D1-B1 asserts this by running the dispatch twice — once with the adapter forced to return `None`, once with it not called at all — and diffing the captured `_kwargs`.

**Route-reason enum (LOW-1 fix, 4 values fixed, no tuple):**
- `NM_ROUTE_REASON_ANNOTATED = "annotated_known_person"` (NEW)
- `NM_ROUTE_REASON_ENRICHED = "enriched"` (EXISTING, CONSOL-1)
- `NM_ROUTE_REASON_ENRICHED_AND_ANNOTATED = "enriched_and_annotated"` (NEW — composed case)
- `NM_ROUTE_REASON_ENRICHMENT_FAILED_FALL_THROUGH = "enrichment_failed_fall_through"` (EXISTING, CONSOL-1)
- (D3 adds `NM_ROUTE_REASON_STRANGER_ESCALATION = "stranger_escalation"` — separate emission)

Rationale: `route_reason` is a single scalar field in NM (`notification_manager.py:596, 1484`), consumed by dashboards. Tuple composition would force every consumer to normalize; a fixed enum is one line of composition at the emission site.

**Rejected alternative (recorded):** annotate-by-edit / follow-up-message shape. Rejected because rev-2 binds in-first-message only. The rejection reason: adds a new rare-fire delayed-task code path (worst-recent-bugs profile per `feedback_marginal_benefit_pushback.md`) for marginal coverage gain. Revisit trigger: D2 ledger shows a materially large late-arriving slice AND operator judges the unannotated-fall-through UX unacceptable.

**Vehicle leg (L2441-2517):** NOT touched in v1. Vehicles are not people. Explicit non-goal.

**Acceptance:**
- **Verify:** message diff shows exactly one appended line when `annotation` is present, byte-identical otherwise.
- **Verify:** adapter total wall time p95 ≤ budget in a fixture with a synthetic 2× budget producer delay (proves the `wait_for` bound holds).
- **Verify:** `_dispatch_to_nm` is called from both base and stranger sites; grep `nm.async_notify` in `perimeter_alert.py` returns exactly ONE call site (inside `_dispatch_to_nm`), proving the single-dispatch-shape property.
- **Test:** `quality/tests/test_known_person_annotation_wire.py` — includes a wire-in-anchor test (per `feedback_wire_in_anchor_mandatory.md`) that neuters the ONE call site in `perimeter_alert.py` (comment out the `annotate_perimeter_person` line) and asserts a specific test goes RED, restored after.
- **Test:** each failure class (disabled, kill-switched, no producer, stale, timeout, exception, empty, unrecognized-name) produces `AnnotationResult=None` and byte-identical `_kwargs` passed to `_dispatch_to_nm`.
- **Test (HIGH-2):** mutation-neuter the extract by inlining a fake-`_dispatch_to_nm` at the stranger call site — a specific test goes RED, confirming both legs actually route through the method.
- **Live:** trigger a real perimeter detection on a camera whose bound producer has a recent recognized face for a `tracked_persons` member; NM message body contains `Person detected — likely <Name>` on exactly one line, at the position defined. Cooldown, severity, snapshot URL, and `hazard_type` unchanged vs the immediately-prior unannotated alert on the same camera (compare recorder rows).
- **Live:** trigger a perimeter detection on a camera with NO bound producer OR with the face sensor at `unknown`; NM message is byte-identical to the current v5.75.x message. Ledger row shows `annotation_status ∈ {no_producer, none}`.

---

## D2: Ledger honesty (annotation + stranger-leg recorded per row — phase-2 gate)

**Purpose:** the phase-2 gate ("annotation accuracy proven over N organic events") needs data. Every perimeter dispatch must record what the annotation adapter AND the stranger leg did.

**Where:** the existing perimeter dispatch ledger row (whichever DAO/table `perimeter_alert.py` currently writes on dispatch — verify at build time; if none exists, extend the anomaly/notification row shape rather than adding a new table).

**New columns / attributes on the ledger row:**
- `annotation_status`: enum { `annotated`, `none`, `no_producer`, `stale`, `timeout`, `exception`, `empty`, `unrecognized_name`, `disabled`, `kill_switched` } — mutually exclusive.
- `annotation_identity`: the raw producer state value (nullable; e.g. `oji_udezue`). Stored raw so future analysis can distinguish "producer said Oji" from the display-name mapping.
- `annotation_producer`: which producer the adapter read (`frigate:sensor.<x>_last_recognized_face` / `unifi:<...>` / `none`).
- `annotation_identity_age_s`: age of the identity value at the time it was read (nullable).
- `annotation_latency_ms`: adapter wall time.
- **`stranger_leg_status` (NEW for folded D3):** enum { `not_doorbell`, `disabled`, `kill_switched`, `guard_enrollment_gate`, `guard_confidence_floor`, `guard_no_confidence_producer_not_opted_in`, `guard_identity_timeout_pending`, `suppressed_known_after_timeout`, `fired`, `exception` } — mutually exclusive.
- **`stranger_leg_latency_ms` (NEW):** wall time from base-dispatch `await nm.async_notify(...)` return to stranger-leg decision (fired OR suppressed with terminal status).

**Read surface (small):** ONE new sensor `sensor.known_person_annotation_stats` with attrs `{total_events, by_annotation_status: {...}, by_stranger_leg_status: {...}, last_annotated_identity, last_annotated_camera, last_annotated_at, last_stranger_fired_camera, last_stranger_fired_at}`, rolling 30d window. Enough to spot-check without a DB query.

**No feedback loop in v1.** The ledger is READ-ONLY consumption for phase-2 evaluation. Nothing in v1 acts on the ledger — enforced by grep in review.

**Acceptance:**
- **Verify:** every perimeter person dispatch after D1+D3 ship writes exactly one ledger row with `annotation_status` AND `stranger_leg_status` populated.
- **Verify:** `sensor.known_person_annotation_stats.by_annotation_status` sums to `total_events`; same for `by_stranger_leg_status` (accounting invariant, both).
- **Test:** row-shape fixture asserts all columns present with correct types on each status class.
- **Live:** after 24h, `sensor.known_person_annotation_stats` shows non-zero `total_events` and a plausible status distribution matching D0's producer-coverage histogram.

---

## D3: Stranger-alert leg (FOLDED IN per rev-2 binding decision #2)

**Origin:** successor to the retiring doorbell face automation. KP-ESCALATE-1 was originally scoped as *replace the doorbell face automation that CONSOL-1 is retiring*. It was declined as a standalone card; its scope is absorbed into this cycle. The half handled by D1 is *known face at perimeter → annotate*. D3 handles the other half: *unknown face at doorbell → escalate*.

**Rev-1 recommendation OVERRIDDEN.** Rev-1 recommended D3-B (defer). Operator overrode: fold D3 in NOW as an additive stranger-alert leg. Rev-1's D3-A shape (inverted-annotation leg producing an additional NM notification with `hazard_type=exterior_unknown_person`) is the baseline, but with a mandatory **false-stranger guard** designed against the D0 doorbell-cadence data.

**Scope:** DOORBELL camera(s) ONLY in v1 (per D0.pre.1 identification). NOT all perimeter cameras. Rationale: doorbell is the highest-signal / lowest-noise-cadence surface AND is the specific location the retired doorbell face automation covered. Extending to other perimeter cameras is a phase-2 decision gated on D2 stranger-leg ledger data.

### NM hazard-consumer enumeration (CRIT-1 fix)

The NEW `NM_HAZARD_EXTERIOR_UNKNOWN_PERSON = "exterior_unknown_person"` hazard type is registered explicitly at THREE downstream NM decision surfaces. This subsection is the authoritative registration list; Reviewer B verifies each site by grep during Tier 2-DB review.

**Registration table:**

| Surface | file:line | Action for `exterior_unknown_person` | Rationale |
|---|---|---|---|
| `NM_SECURITY_HAZARDS` frozenset | `const.py:1509-1512` | **JOIN** the set. Explicit deliverable: extend the frozenset literal to `{exterior_person, exterior_vehicle, exterior_unknown_person}`. | (i) Force-immediate delivery (`notification_manager.py:1368`) — stranger alert is security-tier, must bypass rate/dedup like base perimeter. (ii) **Safeword window scope (`notification_manager.py:1445, 1471`)** — during an operator-declared duke-window, stranger escalations ARE also suppressed. **Operator adjudication:** the duke-window intent is deliberate perimeter silence for tuning; a stranger emission is security-tier, not life-safety, so it respects the window and lands in the suppression ring alongside base perimeter. Stranger emissions are NOT added to the life-safety bypass union. (iii) Force-immediate recipient lookup (`notification_manager.py:1709`) — recipient selection uses the same security-class path as base perimeter. |
| `MEMORY_INELIGIBLE_HAZARD_TYPES` frozenset | `const.py:3685-3691` | **JOIN** the set. Explicit deliverable: extend the frozenset literal to include `"exterior_unknown_person"` alongside `"exterior_person"`. | Defense-in-depth against memory-driven severity demotion. A stranger alert must never be softened by a future widening of the operative allowlist. Mirrors the base-perimeter posture. |
| Severity resolver | `const.py:1542-1553` (map) + `const.py:1556` (resolver) | **NEW map + NEW resolver.** Deliverable: add `NM_HAZARD_EXTERIOR_UNKNOWN_PERSON_SEVERITY_BY_HOUSE_STATE` — the concrete table below (one notch above base per house-state). Add `NM_HAZARD_EXTERIOR_UNKNOWN_PERSON_CONTEXTUAL_SEVERITY(...)` resolver mirroring the base resolver shape. Dispatch selects this resolver when `hazard_type == "exterior_unknown_person"`. | Stranger at doorbell is a doorbell-appropriate one-notch escalation above the base perimeter tier — spec'd concretely below, not "probably". |

**Explicit severity table** (mirrors `NM_HAZARD_EXTERIOR_PERSON_SEVERITY_BY_HOUSE_STATE`, +1 notch per house-state; assumes the existing severity ladder `{info, low, medium, high, critical}`; if the actual ladder differs, builder maps to the closest one-notch-higher tier and records the mapping in the D0/build note):

| house_state | base `exterior_person` severity (existing) | `exterior_unknown_person` severity (NEW, +1 notch) |
|---|---|---|
| `home_day` | `low` | `medium` |
| `home_night` | `medium` | `high` |
| `sleep` | `high` | `critical` |
| `away` | `medium` | `high` |
| `vacation` | `high` | `critical` |
| `guest` | `low` | `medium` |
| (any state where base = `critical`) | `critical` | `critical` (already ceiling) |

Builder verifies the base map at `const.py:1542-1553` against this table at build time; if the house-state keys or the base severities differ, builder updates this table to match the +1-notch delta and cites `const.py:LNN` in the commit. This table is normative — no "probably" language remains.

**Operator-visible behavior note (for the card/plan and the deploy README):** during an active operator-declared duke-window (safeword), stranger-emissions from the D3 leg ARE ALSO SUPPRESSED alongside base perimeter emissions. This is intentional — the safeword suppresses the perimeter security class as a whole, and the stranger leg is a member of that class. Operators who invoke duke to silence known noise (contractor, gardener, delivery) will not receive a stranger escalation during that window; the leg fires normally once the window closes. If the operator wants stranger emissions to bypass duke in a future cycle, that is a phase-2 decision requiring a policy inversion at `notification_manager.py:1445-1471`.

### Trigger and guard

**Trigger:** on a perimeter person-detection at a doorbell camera, AFTER the base dispatch's `await nm.async_notify(...)` has returned (HIGH-1 fix — see below), the stranger leg is scheduled as its OWN background task. Fire additional NM notification (via `self._dispatch_to_nm(...)` — HIGH-2 fix, same method as base) if and only if ALL of the following hold:

1. **Stranger leg globally enabled** (`CONF_STRANGER_LEG_ENABLED`, default OFF at ship per CONSOL-1 precedent).
2. **Camera is in the doorbell set** (`CONF_STRANGER_LEG_DOORBELL_CAMERAS`).
3. **Kill switch not tripped** (`STRANGER_LEG_KILL`, rung-1 module const).
4. **Enrollment-coverage gate passes** for this camera: the D0 enrollment-coverage number for household members expected at this door is ≥ `stranger_leg_enrollment_coverage_gate` (rung-3 Number, default from D0(c), floor 0.60). Gate FAILS → suppress leg, ledger `guard_enrollment_gate`. Rationale: firing stranger escalations against a household whose enrollment is thin guarantees false-stranger fires on household members.
5. **Identity-attempt timeout satisfied:** the leg waits up to `stranger_leg_identity_attempt_timeout_s` (rung-3 Number, default from D0(d) latency histogram, likely 5-15s, MUST be > D0's p50 identity-arrival delta) for the producer to yield an identity via `probe_identity_for_stranger_guard(...)`. During this wait, the base alert is ALREADY DISPATCHED and delivered — the wait ONLY delays the stranger-leg decision. Discharge (per `feedback_suppression_needs_discharge.md`):
   - **Identity arrives = tracked_persons name** within window → suppress leg, ledger `suppressed_known_after_timeout`. (Base alert is annotated per D1 already; no stranger emission needed.)
   - **Identity arrives = unknown / no_match / unrecognized_name** within window AND confidence gate (see 6) passes → FIRE stranger emission, ledger `fired`.
   - **No identity within window** → FIRE stranger emission (treated as unknown), ledger `fired`. Backstop: even if the producer never updates, the leg has a bounded terminal decision — never leaks a pending task past `timeout + 1s`.
   - **Exception in guard or producer read** → suppress leg (fail-CLOSED for stranger — a false-positive stranger fire is worse than a missed one, given the phone-notification blast radius), ledger `exception`.
6. **Confidence gate (MED-2 fix — fail-CLOSED default with opt-in):**
   - If the producer exposes a confidence attribute (enumerated in D0(a.iii)) → the value MUST clear `stranger_leg_confidence_floor` (rung-3 Number, default from D0(a.iii) distribution) for the `unknown/no_match/unrecognized_name` verdict to fire. Below floor → suppress, ledger `guard_confidence_floor`.
   - **If the producer does NOT expose confidence** → **fail-CLOSED by default**: the leg does NOT fire on that producer's unknown verdicts. To opt in, the operator adds the producer entity_id to `CONF_STRANGER_LEG_NO_CONFIDENCE_PRODUCERS` (rung-2 config list, default empty). Producers in this opt-in list bypass the confidence gate (fire on any unknown). Ledger for suppressed case: `guard_no_confidence_producer_not_opted_in`.
   - **Rationale (per reviewer recommendation):** a producer without confidence has *less* signal than a low-confidence-but-passing verdict. Firing on it silently would be at least as risky as bypassing an exception. Fail-CLOSED plus explicit opt-in mirrors the plan's own posture on guard exceptions. The plan-review adjudication is bound here; the "adjudicate at build" language is removed.

### HIGH-1 fix — structural stranger-leg scheduling

The stranger leg's scheduling primitive is stated exactly, not as "enqueued":

```python
# Inside _async_handle_perimeter_trigger, after annotation composition:

# Base dispatch — this is the load-bearing await.
await self._dispatch_to_nm(  # extracted method, HIGH-2 fix
    nm=nm,
    entity_id=entity_id,
    cooldown_key=cooldown_key,
    hazard_type=NM_HAZARD_EXTERIOR_PERSON,
    ... # all base kwargs
)
# NOTE: _dispatch_to_nm's own await on nm.async_notify(...) has RETURNED
# by the time control reaches the line below. Not "enqueued" — completed.

# Stranger leg — ONLY reachable after the base await returns.
if self._is_doorbell_camera(entity_id) and self._stranger_leg_enabled():
    self._entry.async_create_background_task(
        self.hass,
        self._stranger_leg_evaluate(
            nm=nm,
            entity_id=entity_id,
            base_snapshot_url=snapshot_url,   # LOW-2 fix — reused verbatim, no re-capture
            base_snapshot_path=snapshot_path,
            annotation_probe_at=now,
        ),
        name=f"ura_stranger_leg_{_camera_key_for_sensor(entity_id)}",
    )
# The background task is created ONLY AFTER the base await completed above.
# It is NOT awaited here — control returns to the caller immediately,
# releasing _dispatch_in_flight (which was held ONLY across the base leg).
```

**Guard-state invariants (INV-KP (e) proof obligations):**
- The stranger leg MUST NOT read, hold, acquire, or release `_dispatch_in_flight`. `_dispatch_in_flight` is spec'd as base-leg-only property; Reviewer D falsifies by grepping `_dispatch_in_flight` inside `_stranger_leg_evaluate` / stranger module — any hit is a HIGH.
- The stranger leg maintains its OWN in-flight guard `self._stranger_leg_in_flight: dict[str, asyncio.Task]` keyed on `_camera_key_for_sensor(entity_id)` (MED-3 fix — same fusion helper as base cooldown). A second doorbell trigger on the same camera-key while a stranger-leg task is still running: the second-trigger's stranger leg is suppressed with ledger `guard_identity_timeout_pending`. This is a stranger-leg-only decision — the second-trigger's BASE alert dispatches normally.
- The stranger leg MUST NOT touch base cooldowns, base dedup keys, or `_dispatch_in_flight`. It has its own cooldown (`stranger_leg_cooldown_s`) keyed on `(_camera_key_for_sensor(entity_id), "stranger_leg")`.
- The stranger leg's `_dispatch_to_nm(...)` call is the ONLY write path to NM state; that call composes its own `_kwargs` and does not mutate any base-leg locals.

**Live falsifier (interleave slice) — added per HIGH-1:** with `stranger_leg_identity_attempt_timeout_s=30s`, back-to-back doorbell events at t=0 and t=6s BOTH produce a base alert delivered on time. The second base alert is NOT suppressed by a still-running stranger-leg task from t=0. Verify by inspecting the recorder for two distinct base-alert dispatch timestamps < 1s apart from their respective trigger events.

**Stranger emission shape:**
- `hazard_type = "exterior_unknown_person"` (NEW; registered per the CRIT-1 table above).
- Severity: from `NM_HAZARD_EXTERIOR_UNKNOWN_PERSON_SEVERITY_BY_HOUSE_STATE` (NEW map, table above), resolved via `NM_HAZARD_EXTERIOR_UNKNOWN_PERSON_CONTEXTUAL_SEVERITY(...)`.
- `title`: `"Unknown person at doorbell"` (default; configurable via `CONF_STRANGER_LEG_TITLE_FORMAT`).
- `message`: includes camera, timestamp, snapshot URL, AND — if the producer emitted a raw identity (unknown/no_match/unrecognized name) — a diagnostic line `Face producer: {raw_identity}` for operator triage.
- `snapshot_url` / `snapshot_path` (**LOW-2 fix — explicit reuse**): the stranger emission REUSES the base dispatch's `snapshot_url` and `snapshot_path` verbatim. Same file, no re-capture, no new snapshot write path, no `/config/www` staging. This preserves the LAN-only privacy invariant established in rev-2. The base-leg values are passed into `_stranger_leg_evaluate` as `base_snapshot_url` / `base_snapshot_path` and forwarded into `_dispatch_to_nm`.
- Route reason: `NM_ROUTE_REASON_STRANGER_ESCALATION = "stranger_escalation"` (NEW, 4th value in enum — see LOW-1 in D1).
- Cooldown: per `(_camera_key_for_sensor(entity_id), "stranger_leg")` (MED-3 fix — fusion key, NOT raw entity_id) per `stranger_leg_cooldown_s` (rung-3 Number, default 300s — do NOT re-fire on the same camera within 5 min).
- Dispatched via `self._dispatch_to_nm(...)` — HIGH-2 fix, SAME method the base uses. The stranger leg's call passes `hazard_type="exterior_unknown_person"` and its own composed kwargs; the method body is unchanged (all kwargs explicit).

**Invariant to guard (extension of INV-KP (e)):** the stranger leg's evaluation, including the identity-attempt wait, runs in a `entry.async_create_background_task` created ONLY AFTER the base `await nm.async_notify(...)` has returned. The base dispatch's `_kwargs`, ordering, and delivery are provably independent of the stranger-leg code path. Mutation-neutering the entire stranger-leg module leaves the D1 test suite green (verified in review by Reviewer B).

**Rejected alternatives (recorded):**
- **D3-B "defer entirely"** — rev-1's recommendation. Rejected per rev-2 binding decision #2 (operator has folded in NOW; the retired doorbell face automation cannot be left without a successor across the D2 data-gathering window).
- **Stranger leg on ALL perimeter cameras in v1** — rejected as scope creep; the marginal-benefit case for non-doorbell cameras is unmeasured. Phase-2 decision post-D2 ledger.
- **Fire-OPEN on guard exception** — rejected in favor of fail-CLOSED. A false stranger fire on a household member is a worse UX than a missed stranger fire (which is what today's baseline is anyway — the base alert still fires).
- **Fire on no-confidence producers by default (rev-2 shape)** — REJECTED per MED-2 fix. Fail-CLOSED with explicit `CONF_STRANGER_LEG_NO_CONFIDENCE_PRODUCERS` opt-in.
- **Duplicate `nm.async_notify(...)` at a stranger-only dispatcher** — REJECTED per HIGH-2 fix. Drift risk on the dispatch path is unacceptable; the extracted `_dispatch_to_nm(...)` is the one canonical shape.
- **Await the stranger leg inline in `_async_handle_perimeter_trigger`** — REJECTED per HIGH-1 fix. Would hold `_dispatch_in_flight` across a 10s+ identity wait, suppressing a legitimate second base trigger on the same camera. The background-task shape is structural, not stylistic.

**Knobs (all NEW; ladder placement per `feedback_numbers_get_knobs_ladder.md`):**

| Knob | Rung | Home | Default | Kill semantics |
|---|---|---|---|---|
| `STRANGER_LEG_KILL` | 1 (module const) | `const.py` | `False` | Fire-axe. |
| `CONF_STRANGER_LEG_ENABLED` | 2 (config) | integration config entry | `False` at ship | Per-deployment enable. |
| `CONF_STRANGER_LEG_DOORBELL_CAMERAS` | 2 (config) | integration config entry | `[]` at ship | Structural (which cameras count as doorbells). |
| `CONF_STRANGER_LEG_TITLE_FORMAT` | 2 (config) | integration config entry | `"Unknown person at doorbell"` | Wording. |
| `CONF_STRANGER_LEG_NO_CONFIDENCE_PRODUCERS` | 2 (config) | integration config entry | `[]` at ship | Opt-in list of producer entity_ids that bypass the confidence floor (fire on any unknown). Empty = fail-CLOSED for all no-confidence producers. (MED-2 fix.) |
| `stranger_leg_identity_attempt_timeout_s` | 3 (Number entity) | Number platform | D0(d)-driven, likely 10s | `0` = fire immediately on any non-tracked identity (disables the wait). |
| `stranger_leg_confidence_floor` | 3 (Number entity) | Number platform | D0(a.iii)-driven | `0` = accept any confidence (bypass gate for producers that DO expose one; does NOT affect the no-confidence-producer opt-in). |
| `stranger_leg_enrollment_coverage_gate` | 3 (Number entity) | Number platform | D0(c)-driven, floor 0.60 | `0` = disable gate; `1.0` = require perfect enrollment. |
| `stranger_leg_cooldown_s` | 3 (Number entity) | Number platform | 300s | `0` = disable cooldown (every event fires). |

**Acceptance:**
- **Verify (CRIT-1):** grep confirms `"exterior_unknown_person"` appears in `NM_SECURITY_HAZARDS` frozenset literal at `const.py:~1509`, in `MEMORY_INELIGIBLE_HAZARD_TYPES` frozenset literal at `const.py:~3685`, AND in a NEW `NM_HAZARD_EXTERIOR_UNKNOWN_PERSON_SEVERITY_BY_HOUSE_STATE` map. Reviewer B re-enumerates via `grep -rn NM_SECURITY_HAZARDS\|MEMORY_INELIGIBLE_HAZARD_TYPES\|NM_HAZARD_EXTERIOR_PERSON` and confirms parity for every base-perimeter membership site.
- **Verify (HIGH-1):** grep confirms `_dispatch_in_flight` is NOT read, written, held, or released inside `_stranger_leg_evaluate` or any stranger-module code path. Grep confirms the stranger leg's `_stranger_leg_in_flight` guard exists and is keyed on `_camera_key_for_sensor(entity_id)`.
- **Verify (HIGH-2):** grep confirms `_dispatch_to_nm` is called from exactly TWO sites: the base leg in `_async_handle_perimeter_trigger` and the stranger leg in `_stranger_leg_evaluate`. Grep confirms `nm.async_notify` is called from exactly ONE site (inside `_dispatch_to_nm`).
- **Verify (MED-3):** grep confirms stranger-cooldown key composition uses `_camera_key_for_sensor(entity_id)`, matching base fusion.
- **Verify:** base dispatch `_kwargs` passed to `_dispatch_to_nm` are byte-identical whether stranger leg fires, defers, or is disabled (INV-KP (e) proof).
- **Verify:** mutation-neutering `_stranger_leg_evaluate(...)` (comment out the `entry.async_create_background_task` call site AFTER base dispatch) leaves the D1 base-dispatch test suite green (proves the leg is strictly additive and non-blocking).
- **Test:** `quality/tests/test_stranger_leg_wire.py` — wire-in anchor test for the stranger-leg call site (neuter → specific stranger-leg test goes red).
- **Test:** each guard-fail class (enrollment gate, confidence floor, no-confidence-producer-not-opted-in, identity timeout with known-arrival, identity timeout with unknown-arrival, no producer, exception) produces the correct `stranger_leg_status`.
- **Test:** cooldown fixture — two doorbell events within `stranger_leg_cooldown_s` produce exactly one stranger emission; cooldown key composition asserts `_camera_key_for_sensor(entity_id)` fusion (two entities on the same physical camera → one cooldown, not two).
- **Test (HIGH-1 interleave slice):** with `stranger_leg_identity_attempt_timeout_s=30s`, back-to-back doorbell events at t=0 and t=6s → two base dispatches < 1s from their triggers; the second base dispatch is NOT gated on the first's still-running stranger-leg task. The second's stranger leg is suppressed with `guard_identity_timeout_pending`.
- **Test (HIGH-2):** two-site coverage — mutation-detach `_dispatch_to_nm` (rename to `_dispatch_to_nm_v2`) → BOTH base and stranger leg tests fail (proves both actually route through the extracted method, not a duplicated shadow).
- **Test (CRIT-1 safeword scope):** with a mock safeword window active on the perimeter class, a doorbell trigger produces NEITHER a base emission NOR a stranger emission (both are `NM_SECURITY_HAZARDS` members). Documents the operator-visible behavior note above.
- **Live:** trigger a doorbell person event with a KNOWN face (household member walking to door); base alert annotated per D1, NO stranger emission, ledger `stranger_leg_status = suppressed_known_after_timeout`.
- **Live:** trigger a doorbell person event with an UNKNOWN face (e.g. self holding a photo of an unknown person, or a real delivery visitor); base alert dispatches unannotated, followed within `identity_attempt_timeout_s + cooldown grace` by a stranger emission with `hazard_type=exterior_unknown_person`. Ledger `stranger_leg_status = fired`.
- **Live:** trigger a doorbell person event with no producer update within timeout; stranger emission fires, ledger `fired` with `annotation_status ∈ {none, no_producer}`.
- **Live (falsification of INV-KP (e) latency slice):** temporarily raise `stranger_leg_identity_attempt_timeout_s` to 30s, trigger a doorbell event, confirm from recorder that the BASE alert timestamp is unchanged relative to a baseline event (no delay attributable to the stranger leg).
- **Live (falsification of INV-KP (e) interleave slice):** with `stranger_leg_identity_attempt_timeout_s=30s`, trigger two doorbell events 6s apart; both base alerts dispatch on time in the recorder.
- **Live (CRIT-1 safeword):** during an active operator duke-window, a real doorbell trigger produces no stranger emission (nor base). Recorded in the deploy-README validation table alongside the operator-visible behavior note.

---

## Knobs summary (annotation + stranger leg, ladder placement per `feedback_numbers_get_knobs_ladder.md`)

| Knob | Rung | Home | Default | Why here |
|---|---|---|---|---|
| `KNOWN_PERSON_ANNOTATION_KILL` | 1 | `const.py` | `False` | Fire-axe. |
| `STRANGER_LEG_KILL` | 1 | `const.py` | `False` | Fire-axe (folded D3). |
| `CONF_KNOWN_PERSON_ANNOTATION_ENABLED` | 2 | config entry | `False` at ship | Per-deployment enable. |
| `CONF_KNOWN_PERSON_ANNOTATION_PRODUCER_BINDINGS` | 2 | config entry | `{}` | Per-camera → producer entity_id map. |
| `CONF_KNOWN_PERSON_ANNOTATION_FORMAT` | 2 | config entry | `"Person detected — likely {names}."` | Wording (D0.pre.2-confirmed). |
| `CONF_STRANGER_LEG_ENABLED` | 2 | config entry | `False` at ship | Per-deployment enable (folded D3). |
| `CONF_STRANGER_LEG_DOORBELL_CAMERAS` | 2 | config entry | `[]` at ship | Structural (folded D3). |
| `CONF_STRANGER_LEG_TITLE_FORMAT` | 2 | config entry | `"Unknown person at doorbell"` | Wording (folded D3). |
| `CONF_STRANGER_LEG_NO_CONFIDENCE_PRODUCERS` | 2 | config entry | `[]` at ship | Opt-in list, no-confidence producers (MED-2 fix). |
| `known_person_annotation_budget_ms` | 3 | Number entity | D0-driven (500-1500ms) | Live-tunable. |
| `known_person_annotation_freshness_s` | 3 | Number entity | D0-driven, ≤ `CENSUS_FACE_RECOGNITION_WINDOW_SECONDS` | Live-tunable; `0` = kill. |
| `stranger_leg_identity_attempt_timeout_s` | 3 | Number entity | D0(d)-driven | `0` = fire immediately. |
| `stranger_leg_confidence_floor` | 3 | Number entity | D0(a.iii)-driven | `0` = accept any (does NOT affect no-confidence opt-in). |
| `stranger_leg_enrollment_coverage_gate` | 3 | Number entity | D0(c)-driven, ≥0.60 | `0` = disable gate. |
| `stranger_leg_cooldown_s` | 3 | Number entity | 300s | `0` = every event fires. |

Every one is a **NAMED** configurable — no inline literals. All `CONF_*` and `STRANGER_LEG_*` greps returned NONE — all NEW.

---

## Acceptance criteria (rollup)

**Cycle-level:**
- D0 report committed (including D0.pre.1 tracked_persons audit, D0.pre.2 format confirm, D0(a.iii) confidence distribution, D0(d) doorbell-cadence sub-probe), operator-signed for ship/park verdict AND D3 guard defaults.
- D1 adapter shipped with wire-in anchor test that goes red on neuter.
- D1 byte-identical base fall-through proven by `_kwargs` diff test.
- D1 `_dispatch_to_nm` method extraction verified by two-site coverage test (HIGH-2).
- D3 stranger leg shipped with wire-in anchor test, INV-KP (e) proof (base kwargs byte-identical whether leg fires or not, base timestamp unaffected on both latency AND interleave slices), guard-class coverage tests, CRIT-1 hazard-consumer registration verified at all three surfaces.
- D2 ledger writes every dispatch with populated `annotation_status` AND `stranger_leg_status`.
- D2 stats sensor live and non-zero within 24h of deploy.
- Three framing-disjoint reviews returned SHIP before deploy (A/B/C axes extended to cover stranger leg AND every NM hazard-consumer set per CRIT-1); plan review pass complete before build dispatch.
- Post-deploy README carries a *Validated <date>* table with entity/attribute-cited results, covering BOTH legs AND the operator-visible duke-window/stranger-suppression behavior note.

**Live-only (post-restart) — writes back into `README_v<version>.md`:**
- Real perimeter person event on a bound camera with recent face rec → NM body carries the annotation line, cooldown/severity/snapshot unchanged.
- Real perimeter person event on an unbound camera → NM body byte-identical to pre-deploy shape; ledger `annotation_status = no_producer`.
- Real doorbell event with known face → base annotated, stranger leg suppressed with `suppressed_known_after_timeout`.
- Real doorbell event with unknown face → base dispatches unannotated on time, stranger emission follows within window, ledger `fired`.
- `sensor.known_person_annotation_stats.total_events > 0` within 24h; `by_stranger_leg_status.fired` count matches operator's manual test count.
- No new `ERROR` logs from `known_person_annotation` or stranger-leg module for 24h.
- INV-KP (e) live check (latency slice): base alert timestamp unaffected by stranger-leg processing (compare vs pre-deploy baseline event on same camera).
- INV-KP (e) live check (interleave slice): with elevated timeout, back-to-back doorbell events both produce timely base alerts.
- CRIT-1 duke-window check: doorbell trigger during an active safeword produces NEITHER base NOR stranger emission; recorded with the operator-visible behavior note.

---

## Non-goals (explicit)

- NO alert suppression, demotion, silencing, or dedup change of the BASE alert. Base `severity`, `hazard_type=exterior_person`, cooldown, dispatch topology unchanged. Any reviewer finding that either the adapter OR the stranger leg could suppress/delay/mutate the base alert is a CRITICAL.
- NO new face-enrollment machinery. v1 consumes only local face producers that already exist on the running system (Frigate-2 face rec, and/or UniFi Protect face if D0 confirms it).
- **NO cloud identity sources — LOCAL ONLY per rev-2 binding decision #1.** No sending reference photos or live snapshots to cloud LLMs for face identity. llmvision remains a scene-descriptor (CONSOL-1's role), NEVER a face-identity source in v1 or any future phase without a separate operator adjudication of the privacy posture.
- NO new snapshot write path — stranger emission REUSES base `snapshot_url` / `snapshot_path` verbatim (LOW-2 fix). No `/config/www` staging, no re-capture.
- NO annotate-by-edit / follow-up-message shape per rev-2 binding decision #3. In-first-message only.
- NO stranger leg on non-doorbell perimeter cameras in v1. Doorbell-only. Extension is phase-2, gated on D2.
- NO stranger emission bypass of the operator's duke-window/safeword (per CRIT-1 operator adjudication). Suppression during duke is intentional; any bypass is a phase-2 policy decision.
- NO changes to the vehicle leg (L2441-2517).
- NO changes to interior face-arrival handling (`presence._handle_face_arrival`).
- NO cross-alert correlation, no historical-pattern learning, no phase-2 suppression logic. All phase-2 machinery deferred.

---

## Rev-3 change log (plan-review fix-up)

Fixes applied against `docs/reviews/code-review/known_person_annotation_plan_review.md` (commit 4e468d37f). Every finding resolved in-plan with orchestrator adjudications.

- **CRIT-1 (NM hazard-consumer enumeration):** Added explicit "NM hazard-consumer enumeration" subsection to D3 with a registration table covering all three surfaces. `NM_SECURITY_HAZARDS` JOINED (operator adjudication: stranger is security-tier, respects duke-window suppression, does NOT go in life-safety bypass). `MEMORY_INELIGIBLE_HAZARD_TYPES` JOINED. Severity: NEW `NM_HAZARD_EXTERIOR_UNKNOWN_PERSON_SEVERITY_BY_HOUSE_STATE` map spec'd concretely as one-notch-above the base table per house-state (explicit table, no "probably"). Operator-visible behavior note recorded for the card/deploy README ("during an open duke-window, stranger escalations are also suppressed").
- **HIGH-1 (async ordering):** Replaced "enqueued to NM" language with a structural guarantee. Stranger leg runs as its OWN `entry.async_create_background_task` created ONLY AFTER the base `await nm.async_notify(...)` returns (not after task creation). Stranger leg does NOT hold `_dispatch_in_flight`; has its OWN `_stranger_leg_in_flight` guard keyed on `_camera_key_for_sensor(entity_id)`. Falsification now includes an interleave slice (back-to-back doorbell events at t=0 and t=6s both produce timely base alerts). Reviewer D obligation explicitly names `_dispatch_in_flight` as forbidden state.
- **HIGH-2 (extract vs duplicate):** Adjudicated **extract-to-method** — new `PerimeterAlertManager._dispatch_to_nm(...)` module method with explicit kwargs signature, called from BOTH base and stranger sites. Duplication REJECTED (drift risk on dispatch path). Two-site coverage test added (rename-detach → both leg tests fail).
- **MED-1 (confidence distribution probe):** Added D0(a.iii) sub-probe collecting confidence attribute histograms (min/mean/p50/p95, unknown-vs-recognized distribution) per Frigate + UP producer. `stranger_leg_confidence_floor` default now derives from D0(a.iii) (`p10` of recognized OR `p25` of unknown, whichever lower).
- **MED-2 (no-confidence producers):** Adopted reviewer's recommendation — fail-CLOSED by default. NEW rung-2 opt-in list `CONF_STRANGER_LEG_NO_CONFIDENCE_PRODUCERS` (default empty). Producers on the list bypass the confidence gate; producers off the list AND without a confidence attribute do NOT fire. New ledger status `guard_no_confidence_producer_not_opted_in`. "Adjudicate at build" language removed.
- **MED-3 (cooldown key fusion):** Stranger-leg cooldown key + `_stranger_leg_in_flight` guard key both use `_camera_key_for_sensor(entity_id)` fusion, matching base cooldown. Cooldown test asserts fusion (two entities on one physical camera → one cooldown).
- **LOW-1 (route-reason composition):** Fixed 4-value enum spec'd (`NM_ROUTE_REASON_ANNOTATED`, `NM_ROUTE_REASON_ENRICHED`, `NM_ROUTE_REASON_ENRICHED_AND_ANNOTATED`, `NM_ROUTE_REASON_ENRICHMENT_FAILED_FALL_THROUGH`, plus D3's `NM_ROUTE_REASON_STRANGER_ESCALATION`). Tuple shape REJECTED.
- **LOW-2 (snapshot reuse):** Stranger emission reuses base `snapshot_url` and `snapshot_path` verbatim — explicit in D3 code sketch, in emission-shape bullets, in non-goals. No re-capture, no new write path, LAN-only privacy invariant preserved.

---

## Rev-2 change log

- **Binding decision #1 (LOCAL ONLY):** removed llmvision as an identity-source candidate throughout. D0(a) no longer probes llmvision-as-identity. Non-goals updated to state cloud-identity is REJECTED, not merely "recommended NO."
- **Binding decision #2 (D3 FOLD-IN):** replaced rev-1's D3 defer-recommendation with a full D3 stranger-leg spec (doorbell-only, additive-after-base, false-stranger guard with four gated conditions: enrollment coverage, identity-attempt timeout, confidence floor, cooldown). Added `stranger_leg_status` to D2 ledger. Extended INV-KP with clause (e): stranger leg is strictly additive and cannot delay/block base. Added D0(d) sub-probe for doorbell unknown cadence. Added stranger-leg knobs (2 kill/config + 4 rung-3 Numbers). Origin/context clarified: KP-ESCALATE-1 declined as standalone, scope absorbed here.
- **Binding decision #3 (IN-FIRST-MESSAGE ONLY):** removed annotate-by-edit branch from D0 adjudication rule and from D1 shape spec. Recorded as REJECTED alternative with revisit trigger. D0 latency histogram still records the 5s/10s/30s buckets as informational data for phase-2, but no code path consumes them in v1.
- **Pre-D0 tasks folded:** rev-1 open decisions #4 (`tracked_persons` currency) and #5 (message format) are now explicit D0.pre.1 and D0.pre.2 tasks in the D0 report. Default message format binds unless operator objects during D0 review.
- **Removed** rev-1's "Operator decisions needed (BEFORE D0 dispatch)" section — all five decisions are now either resolved (bindings) or folded as D0 tasks.
