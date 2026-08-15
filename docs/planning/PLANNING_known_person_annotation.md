# PLANNING — Known-Person Annotation Pipeline v1 (ANNOTATE, don't suppress) — rev-2

**Rev-2 (2026-08-14):** Operator answered the three open decisions from rev-1. Folded in as **BINDING**:

1. **Identity sources = LOCAL ONLY.** Frigate-2 face recognition + UniFi Protect face detection. **llmvision is EXCLUDED from identity** — no household reference photos leave the LAN. Any cloud-identity alternative is REJECTED.
2. **D3 stranger-alert leg = FOLD IN NOW** (overrides rev-1's DEFER recommendation). The unknown-face stranger-alert leg builds in the SAME cycle. It is the successor to the retiring doorbell face automation. **KP-ESCALATE-1 was declined as a standalone card and its scope is absorbed here** — this cycle's origin is that absorption.
3. **Annotation shape = IN-FIRST-MESSAGE ONLY.** The identity line rides the first alert message on its own line (default format: `Person detected — likely {names}.`). The annotate-by-edit / follow-up-message alternative is REJECTED — see D1 rationale.

**Card:** KP-ESCALATE-1 (absorbed / declined as standalone; scope folded here). Cycle now delivers BOTH the annotation half (known face → annotate) AND the stranger-alert half (unknown face at doorbell → escalate) — the two halves of the retiring doorbell face automation.

**Operator direction (2026-08-14, original):** exterior perimeter alerts today consult ZERO member/face data — a person page is identical to me whether it is my wife walking up the driveway or a stranger. **v1 = ANNOTATE (known) + ESCALATE (unknown, doorbell only)**. When a face/identity signal is available for a perimeter person detection, the alert message gains a single line: `Person detected — likely <Name>`. The alert itself is preserved byte-for-byte otherwise. **No suppression, no severity change, no dedup change of the base alert in v1.** The stranger leg is an ADDITIVE emission on top of the byte-identical base — never a delay or gate on it.

**Phase 2 (explicitly PARKED, not in this cycle):** per-person opt-in suppression / demotion. **Trigger to un-park:** annotation accuracy proven over N organic events with a per-annotation ledger — see D2. Do NOT design phase-2 machinery into v1.

**Tier:** **Tier 2-DB** (elevated per standing regression-prone policy). The pipeline threads external identity signals into `perimeter_alert.py` — the same alert path CONSOL-1 shipped through — where one missed emission site or one stale-identity leak is either a false accusation on a family member, a silenced-in-practice stranger, or (with the folded D3) a false stranger escalation on an enrolled household member. Three framing-disjoint reviews required (A=local correctness of the annotation adapter + freshness/coverage math + false-stranger guard arithmetic, B=integration/state-machine — every perimeter emission site + no accidental suppression + byte-identical base fall-through + stranger leg strictly additive, C=ledger authority via real per-site source mutation, extended to cover the stranger-emission site). Plan review Tier 2 (one adversarial pre-build pass, re-enumerating emission sites and identity producers independently, AND re-enumerating stranger-leg guard bypass paths).

**Branch:** `feature/known-person-annotation-v1`.
**Scope target:** ≤ ~7 files touched (const, new adapter, perimeter_alert wire for BOTH legs, ledger extension, config-flow, one sensor, one stranger-leg guard module or inline); D0 is a probe-only artifact and touches no runtime code.

---

## Falsifiable invariant (Reviewer D framing)

> **INV-KP:** Under any legal config, for any perimeter person-detection that reaches `PerimeterAlertManager._async_handle_perimeter_trigger`:
> (a) the BASE alert dispatches to NM on the same code path, with the same `hazard_type`, `severity`, `title`, `coordinator_id`, `location`, snapshot, and cooldown/dedup behavior as it does today with BOTH the annotation adapter AND the stranger leg disabled — proven by a byte-identical `message` and identical `_kwargs` when the adapter returns `None` and the stranger leg is inert;
> (b) when the adapter returns a non-empty annotation string, the ONLY delta in the dispatched BASE payload is exactly one appended line of the form `Person detected — likely <Name(s)>` (default template) inserted at a defined position; nothing else in the base payload changes;
> (c) the annotation adapter's total wall time is bounded by `known_person_annotation_budget_ms` (rung-3 Number entity, default TBD by D0 latency data); on budget expiry, exception, empty result, or stale identity beyond the freshness window, the adapter returns `None` and the dispatch proceeds as (a) — with a ledger row recording `annotation_status ∈ {none, timeout, exception, stale, no_producer, disabled, kill_switched, unrecognized_name, empty}`;
> (d) the adapter has NO write path — it cannot mutate NM state, cooldowns, `_dispatch_in_flight`, house_state, presence trackers, or `sensor.*` values;
> **(e) STRANGER LEG (folded D3) is strictly ADDITIVE.** The stranger emission is scheduled AFTER the base dispatch has been enqueued to NM (never before, never inline in the base composition), such that no code path in the stranger leg — including its guard evaluation, its identity re-read, or its escalation dispatch — can delay, block, mutate, dedup, or replace the base alert. Proven by: (i) the base dispatch's `_kwargs` are byte-identical whether the stranger leg fires, defers, or is disabled; (ii) mutation-neutering the entire stranger-leg module leaves the base dispatch test suite green; (iii) the stranger leg has NO write access to any of the base-dispatch state listed in (d).

Reviewer D falsifies (d) AND (e) especially: enumerate every accessor the adapter reaches AND every accessor the stranger leg reaches; any read that could trigger a state-machine side effect (RestoreEntity load, dispatcher fire, coordinator refresh) is a leak. For (e), Reviewer D must exhibit a legal-config repro OR prove no legal config exists where a stranger-leg failure (guard exception, identity re-read hang, dispatch error) can delay base delivery.

---

## Institutional context verified

**Prior planning consulted:**
- `docs/planning/PLANNING_exterior_person_escalation.md` — the original perimeter → NM wiring plan; establishes `hazard_type=exterior_person`, house-state severity map, and the `_async_handle_perimeter_trigger` shape we hook into.
- `docs/planning/PLANNING_consol_1_alerting_llmvision.md` — CONSOL-1 shipped `perimeter_enrichment.py` (the adapter shape being REUSED here) with `INV-ENRICH-NEVER-SILENCES` / `INV-ENRICH-NON-EMPTY` / `INV-ENRICH-BUDGETED` — v1 mirrors these invariants for identity.
- `docs/planning/AUDIT_consol_1_d0_probe.md` — the probe-first pattern this plan copies for D0.
- `docs/planning/AUDIT_frigate1_retirement_inventory.md` — Frigate-1 retirement inventory (needed to know which face producers are still live on Frigate-2).
- kanban `KP-ESCALATE-1` + its `direction_2026_08_14` note — the source-of-truth direction (declined as standalone; absorbed here).

**Code surfaces surveyed:** (unchanged from rev-1 — see rev-1 for line-cited list)
- `perimeter_alert.py:1272-1436` insertion point for base + annotation; stranger-leg emission site is a NEW dispatch scheduled AFTER the base enqueue (see D3 for exact placement).
- `perimeter_enrichment.py` — REUSED adapter shape.
- `camera_census.py:2317-2345`, `:2347-2400`, `:2946-3080` — Frigate face producer + freshness-gated view + display-name map.
- `domain_coordinators/presence.py:4378-4420`, `:570-571,919-920,4370-4376` — interior face state (informational only; v1 does not modify).
- `sensor.py:3485,5040-5042` — face state surface reused as read source.
- `const.py` — `CONF_KNOWN_PERSON_*`, `CONF_FACE_*`, `CONF_PERSON_ANNOTATION_*`, `CONF_STRANGER_*` greps returned NONE — all knobs NEW.

**REUSED vs NEW tally:**
- REUSED: adapter shape (perimeter_enrichment.py), Frigate face accessor (`_get_face_recognized_persons_fresh` + `_get_face_recognized_person_names`), presence tracker face state (read-only reference), hazard/severity/dispatch path for base (unchanged), `tracked_persons` integration-config list, `CENSUS_FACE_RECOGNITION_WINDOW_SECONDS` freshness constant, `sensor.face_recognized_persons` surface, house-state severity map (for the stranger leg's severity selection).
- NEW: `known_person_annotation.py` adapter module, `CONF_*` for enable / per-camera producer bindings / annotation format / **stranger-leg enable / doorbell-camera set / false-stranger guard knobs** (see D3), one module-const kill switch (annotation) + one (stranger leg), two rung-3 Number entities (annotation budget + freshness), **three rung-3 Number entities for the false-stranger guard (identity-attempt timeout, confidence floor, enrollment-coverage gate — see D3)**, ledger row extension (`annotation_status`, `annotation_identity`, `annotation_producer`, `annotation_identity_age_s`, `annotation_latency_ms`, `stranger_leg_status`), NEW `hazard_type=exterior_unknown_person`, NEW `NM_ROUTE_REASON_ANNOTATED` and `NM_ROUTE_REASON_STRANGER_ESCALATION`.

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
- **Verify:** `docs/planning/AUDIT_known_person_d0_probe.md` committed with (a) producer inventory, (b) latency histogram, (c) enrollment coverage table, (d) doorbell unknown cadence.
- **Verify:** D0.pre.1 tracked_persons audit result recorded, operator has curated the list.
- **Verify:** D0.pre.2 message-format decision recorded (default binds absent objection).
- **Verify:** every claim in D1 AND D3's design cites a row/number from the D0 report — no design number is asserted without a probe row.
- **Verify:** operator sign-off in the doc adjudicates BOTH the ship-vs-park verdict AND the D3 guard defaults from (d).

---

## D1: Annotation wire (`known_person_annotation.py` adapter + perimeter_alert insertion)

**Gated on:** D0 (a)+(b)+(c) meet the ship threshold.

**Shape (BINDING per rev-2 decision #3):** IN-FIRST-MESSAGE ONLY. The annotation adapter runs synchronously inside the base dispatch composition, budgeted. There is NO annotate-by-edit path, NO follow-up second message for late-arriving identity, NO delayed task. If identity is not available at composition time, the base alert dispatches unannotated, ledger records the fall-through class, and the event is done. Rationale: (i) per `feedback_marginal_benefit_pushback.md`, the by-edit shape introduces a new rare-fire delayed-task code path — categorically risky and hard to observe organically — for marginal coverage over in-first-message; (ii) the operator has bound the decision; (iii) the by-edit shape can be revisited post-D2 if the ledger shows the late-arriving slice is materially large.

**New module `custom_components/universal_room_automation/known_person_annotation.py`.** Mirrors `perimeter_enrichment.py` shape 1:1:

```python
async def annotate_perimeter_person(
    hass, camera_entity_id: str, event_time: datetime
) -> AnnotationResult | None:
    ...
```

Where `AnnotationResult` is a small dataclass carrying `(display_names: list[str], producer: str, identity_age_s: float, latency_ms: float, raw_identity: str)`. On any failure class (kill switch, disabled, no producer bound, stale beyond window, budget expiry, exception, empty result, unrecognized-by-config name), returns `None`. **No exception escapes.**

**Producer resolution:** per-camera producer binding (see knobs). Adapter reads ONLY the bound producer's entity. Multi-producer per camera is out of v1 scope (adjudicate in D0 whether any camera actually has more than one).

**Freshness:** identity value's `state.last_changed` age must be ≤ `known_person_annotation_freshness_s` (rung-3 Number, default = D0-driven; upper bound = `CENSUS_FACE_RECOGNITION_WINDOW_SECONDS`). Older = `stale` → return `None`.

**Display-name mapping:** slug → display name via `tracked_persons` friendly-name lookup on the person entity registry (already the shape `_get_face_recognized_person_names` uses). If the recognized identity is not in `tracked_persons`, return `None` for annotation purposes — v1 does not annotate unrecognized-by-config names, to avoid rendering `Person detected — likely gardener_maybe`. **NOTE:** the raw identity is still surfaced to the stranger-leg guard in D3 (via `AnnotationResult.raw_identity` when annotate-path returns None-with-context, or via a sibling `probe_identity_for_stranger_guard(...)` accessor that returns the same read without the tracked_persons filter — pick one shape at build; the D3 guard needs to distinguish "producer said a name we don't know" from "producer said unknown" from "producer said nothing").

**Budget:** `asyncio.wait_for` around the whole adapter body with `known_person_annotation_budget_ms` (rung-3 Number). Default TBD by D0; upper bound MUST be < remaining time to the existing enrichment dispatch such that the annotation never widens end-to-end alert latency beyond the current p95.

**Insertion site in `perimeter_alert.py`:** after the enrichment block that ends at L1362, before `_do_dispatch` is defined at L1366. Compose:

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

**Byte-identical fall-through proof:** the annotation branch is the ONLY code the adapter reaches on the message; if `annotation is None or not annotation.display_names`, `message` and all downstream `_kwargs` are unchanged relative to today. Test D1-B1 asserts this by running the dispatch twice — once with the adapter forced to return `None`, once with it not called at all — and diffing the captured `_kwargs`.

**Route-reason additions:** NEW `NM_ROUTE_REASON_ANNOTATED = "annotated_known_person"`. If annotation is present AND enrichment is also present, prefer `NM_ROUTE_REASON_ENRICHED_AND_ANNOTATED` (or compose as a stamped tuple — pick one shape; enumerate route reasons in the plan review). Route reason threads into the ledger row (see D2).

**Rejected alternative (recorded):** annotate-by-edit / follow-up-message shape. Rejected because rev-2 binds in-first-message only. The rejection reason: adds a new rare-fire delayed-task code path (worst-recent-bugs profile per `feedback_marginal_benefit_pushback.md`) for marginal coverage gain. Revisit trigger: D2 ledger shows a materially large late-arriving slice AND operator judges the unannotated-fall-through UX unacceptable.

**Vehicle leg (L2441-2517):** NOT touched in v1. Vehicles are not people. Explicit non-goal.

**Acceptance:**
- **Verify:** message diff shows exactly one appended line when `annotation` is present, byte-identical otherwise.
- **Verify:** adapter total wall time p95 ≤ budget in a fixture with a synthetic 2× budget producer delay (proves the `wait_for` bound holds).
- **Test:** `quality/tests/test_known_person_annotation_wire.py` — includes a wire-in-anchor test (per `feedback_wire_in_anchor_mandatory.md`) that neuters the ONE call site in `perimeter_alert.py` (comment out the `annotate_perimeter_person` line) and asserts a specific test goes RED, restored after.
- **Test:** each failure class (disabled, kill-switched, no producer, stale, timeout, exception, empty, unrecognized-name) produces `AnnotationResult=None` and byte-identical `_kwargs`.
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
- **`stranger_leg_status` (NEW for folded D3):** enum { `not_doorbell`, `disabled`, `kill_switched`, `guard_enrollment_gate`, `guard_confidence_floor`, `guard_identity_timeout_pending`, `suppressed_known_after_timeout`, `fired`, `exception` } — mutually exclusive.
- **`stranger_leg_latency_ms` (NEW):** wall time from base-dispatch enqueue to stranger-leg decision (fired OR suppressed with terminal status).

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

**Trigger:** on a perimeter person-detection at a doorbell camera, AFTER the base dispatch has been enqueued to NM (INV-KP (e) — never before, never inline), evaluate the stranger leg. Fire additional NM notification if and only if ALL of the following hold:

1. **Stranger leg globally enabled** (`CONF_STRANGER_LEG_ENABLED`, default OFF at ship per CONSOL-1 precedent).
2. **Camera is in the doorbell set** (`CONF_STRANGER_LEG_DOORBELL_CAMERAS`).
3. **Kill switch not tripped** (`STRANGER_LEG_KILL`, rung-1 module const).
4. **Enrollment-coverage gate passes** for this camera: the D0 enrollment-coverage number for household members expected at this door is ≥ `stranger_leg_enrollment_coverage_gate` (rung-3 Number, default from D0(c), floor 0.60). Gate FAILS → suppress leg, ledger `guard_enrollment_gate`. Rationale: firing stranger escalations against a household whose enrollment is thin guarantees false-stranger fires on household members.
5. **Identity-attempt timeout satisfied:** the leg waits up to `stranger_leg_identity_attempt_timeout_s` (rung-3 Number, default from D0(d) latency histogram, likely 5-15s, MUST be > D0's p50 identity-arrival delta) for the producer to yield an identity. During this wait, the base alert is ALREADY DISPATCHED and delivered — the wait ONLY delays the stranger-leg decision. Discharge (per `feedback_suppression_needs_discharge.md`):
   - **Identity arrives = tracked_persons name** within window → suppress leg, ledger `suppressed_known_after_timeout`. (Base alert is annotated per D1 already; no stranger emission needed.)
   - **Identity arrives = unknown / no_match / unrecognized_name** within window AND confidence (if producer exposes one — Frigate does via `sensor.<base>_last_recognized_face` attributes; UP TBD in D0) ≥ `stranger_leg_confidence_floor` (rung-3 Number, default from D0 producer-confidence distribution) → FIRE stranger emission, ledger `fired`.
   - **No identity within window** → FIRE stranger emission (treated as unknown), ledger `fired`. Backstop: even if the producer never updates, the leg has a bounded terminal decision — never leaks a pending task past `timeout + 1s`.
   - **Exception in guard or producer read** → suppress leg (fail-CLOSED for stranger — a false-positive stranger fire is worse than a missed one, given the phone-notification blast radius), ledger `exception`.
6. **Confidence floor** — already covered in (5) but restated: if the producer emits a confidence score, it must clear `stranger_leg_confidence_floor` for the "unknown/no_match" verdict to be considered high-signal enough to fire. Producers that don't expose confidence (probe in D0) either bypass this gate (fire on any unknown) OR the operator picks a per-producer default at D0 review — plan review must adjudicate.

**Stranger emission shape:**
- NEW `hazard_type = "exterior_unknown_person"`.
- Severity: per existing house-state severity map, at a doorbell-appropriate tier (probably one notch above `exterior_person` base — operator adjudicates at D0 review with the house-state map open).
- `title`: `"Unknown person at doorbell"` (default; configurable via `CONF_STRANGER_LEG_TITLE_FORMAT`).
- `message`: includes camera, timestamp, snapshot URL, AND — if the producer emitted a raw identity (unknown/no_match/unrecognized name) — a diagnostic line `Face producer: {raw_identity}` for operator triage.
- Route reason: NEW `NM_ROUTE_REASON_STRANGER_ESCALATION = "stranger_escalation"`.
- Cooldown: per `(camera, "stranger_leg")` per `stranger_leg_cooldown_s` (rung-3 Number, default 300s — do NOT re-fire on the same camera within 5 min).
- Dispatched via the SAME NM path the base alert uses (no new dispatch code path — reuse `_do_dispatch` or its equivalent), just with a distinct `hazard_type`.

**Invariant to guard (extension of INV-KP (e)):** the stranger leg's evaluation, including the identity-attempt wait, is scheduled on a separate task or callback AFTER the base dispatch has been enqueued to NM. The base dispatch's `_kwargs`, ordering, and delivery are provably independent of the stranger-leg code path. Mutation-neutering the entire stranger-leg module leaves the D1 test suite green (verified in review by Reviewer B).

**Rejected alternatives (recorded):**
- **D3-B "defer entirely"** — rev-1's recommendation. Rejected per rev-2 binding decision #2 (operator has folded in NOW; the retired doorbell face automation cannot be left without a successor across the D2 data-gathering window).
- **Stranger leg on ALL perimeter cameras in v1** — rejected as scope creep; the marginal-benefit case for non-doorbell cameras is unmeasured. Phase-2 decision post-D2 ledger.
- **Fire-OPEN on guard exception** — rejected in favor of fail-CLOSED. A false stranger fire on a household member is a worse UX than a missed stranger fire (which is what today's baseline is anyway — the base alert still fires).

**Knobs (all NEW; ladder placement per `feedback_numbers_get_knobs_ladder.md`):**

| Knob | Rung | Home | Default | Kill semantics |
|---|---|---|---|---|
| `STRANGER_LEG_KILL` | 1 (module const) | `const.py` | `False` | Fire-axe. |
| `CONF_STRANGER_LEG_ENABLED` | 2 (config) | integration config entry | `False` at ship | Per-deployment enable. |
| `CONF_STRANGER_LEG_DOORBELL_CAMERAS` | 2 (config) | integration config entry | `[]` at ship | Structural (which cameras count as doorbells). |
| `CONF_STRANGER_LEG_TITLE_FORMAT` | 2 (config) | integration config entry | `"Unknown person at doorbell"` | Wording. |
| `stranger_leg_identity_attempt_timeout_s` | 3 (Number entity) | Number platform | D0(d)-driven, likely 10s | `0` = fire immediately on any non-tracked identity (disables the wait). |
| `stranger_leg_confidence_floor` | 3 (Number entity) | Number platform | D0-driven, likely 0.60 | `0` = accept any confidence (bypass gate). |
| `stranger_leg_enrollment_coverage_gate` | 3 (Number entity) | Number platform | D0(c)-driven, floor 0.60 | `0` = disable gate; `1.0` = require perfect enrollment. |
| `stranger_leg_cooldown_s` | 3 (Number entity) | Number platform | 300s | `0` = disable cooldown (every event fires). |

**Acceptance:**
- **Verify:** base dispatch `_kwargs` are byte-identical whether stranger leg fires, defers, or is disabled (INV-KP (e) proof).
- **Verify:** mutation-neutering `stranger_leg_evaluate(...)` (comment out the call site AFTER base dispatch) leaves the D1 base-dispatch test suite green (proves the leg is strictly additive and non-blocking).
- **Test:** `quality/tests/test_stranger_leg_wire.py` — wire-in anchor test for the stranger-leg call site (neuter → specific stranger-leg test goes red).
- **Test:** each guard-fail class (enrollment gate, confidence floor, identity timeout with known-arrival, identity timeout with unknown-arrival, no producer, exception) produces the correct `stranger_leg_status` AND (where applicable) fires-or-suppresses correctly.
- **Test:** cooldown fixture — two doorbell events within `stranger_leg_cooldown_s` produce exactly one stranger emission.
- **Live:** trigger a doorbell person event with a KNOWN face (household member walking to door); base alert annotated per D1, NO stranger emission, ledger `stranger_leg_status = suppressed_known_after_timeout`.
- **Live:** trigger a doorbell person event with an UNKNOWN face (e.g. self holding a photo of an unknown person, or a real delivery visitor); base alert dispatches unannotated, followed within `identity_attempt_timeout_s + cooldown grace` by a stranger emission with `hazard_type=exterior_unknown_person`. Ledger `stranger_leg_status = fired`.
- **Live:** trigger a doorbell person event with no producer update within timeout; stranger emission fires, ledger `fired` with `annotation_status ∈ {none, no_producer}`.
- **Live (falsification of INV-KP (e)):** temporarily raise `stranger_leg_identity_attempt_timeout_s` to 30s, trigger a doorbell event, confirm from recorder that the BASE alert timestamp is unchanged relative to a baseline event (no delay attributable to the stranger leg).

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
| `known_person_annotation_budget_ms` | 3 | Number entity | D0-driven (500-1500ms) | Live-tunable. |
| `known_person_annotation_freshness_s` | 3 | Number entity | D0-driven, ≤ `CENSUS_FACE_RECOGNITION_WINDOW_SECONDS` | Live-tunable; `0` = kill. |
| `stranger_leg_identity_attempt_timeout_s` | 3 | Number entity | D0(d)-driven | `0` = fire immediately. |
| `stranger_leg_confidence_floor` | 3 | Number entity | D0-driven | `0` = accept any. |
| `stranger_leg_enrollment_coverage_gate` | 3 | Number entity | D0(c)-driven, ≥0.60 | `0` = disable gate. |
| `stranger_leg_cooldown_s` | 3 | Number entity | 300s | `0` = every event fires. |

Every one is a **NAMED** configurable — no inline literals. All `CONF_*` and `STRANGER_LEG_*` greps returned NONE — all NEW.

---

## Acceptance criteria (rollup)

**Cycle-level:**
- D0 report committed (including D0.pre.1 tracked_persons audit, D0.pre.2 format confirm, D0(d) doorbell-cadence sub-probe), operator-signed for ship/park verdict AND D3 guard defaults.
- D1 adapter shipped with wire-in anchor test that goes red on neuter.
- D1 byte-identical base fall-through proven by `_kwargs` diff test.
- D3 stranger leg shipped with wire-in anchor test, INV-KP (e) proof (base kwargs byte-identical whether leg fires or not), guard-class coverage tests.
- D2 ledger writes every dispatch with populated `annotation_status` AND `stranger_leg_status`.
- D2 stats sensor live and non-zero within 24h of deploy.
- Three framing-disjoint reviews returned SHIP before deploy (A/B/C axes extended to cover stranger leg); plan review pass complete before build dispatch.
- Post-deploy README carries a *Validated <date>* table with entity/attribute-cited results, covering BOTH legs.

**Live-only (post-restart) — writes back into `README_v<version>.md`:**
- Real perimeter person event on a bound camera with recent face rec → NM body carries the annotation line, cooldown/severity/snapshot unchanged.
- Real perimeter person event on an unbound camera → NM body byte-identical to pre-deploy shape; ledger `annotation_status = no_producer`.
- Real doorbell event with known face → base annotated, stranger leg suppressed with `suppressed_known_after_timeout`.
- Real doorbell event with unknown face → base dispatches unannotated on time, stranger emission follows within window, ledger `fired`.
- `sensor.known_person_annotation_stats.total_events > 0` within 24h; `by_stranger_leg_status.fired` count matches operator's manual test count.
- No new `ERROR` logs from `known_person_annotation` or stranger-leg module for 24h.
- INV-KP (e) live check: base alert timestamp unaffected by stranger-leg processing (compare vs pre-deploy baseline event on same camera).

---

## Non-goals (explicit)

- NO alert suppression, demotion, silencing, or dedup change of the BASE alert. Base `severity`, `hazard_type=exterior_person`, cooldown, dispatch topology unchanged. Any reviewer finding that either the adapter OR the stranger leg could suppress/delay/mutate the base alert is a CRITICAL.
- NO new face-enrollment machinery. v1 consumes only local face producers that already exist on the running system (Frigate-2 face rec, and/or UniFi Protect face if D0 confirms it).
- **NO cloud identity sources — LOCAL ONLY per rev-2 binding decision #1.** No sending reference photos or live snapshots to cloud LLMs for face identity. llmvision remains a scene-descriptor (CONSOL-1's role), NEVER a face-identity source in v1 or any future phase without a separate operator adjudication of the privacy posture.
- NO annotate-by-edit / follow-up-message shape per rev-2 binding decision #3. In-first-message only.
- NO stranger leg on non-doorbell perimeter cameras in v1. Doorbell-only. Extension is phase-2, gated on D2.
- NO changes to the vehicle leg (L2441-2517).
- NO changes to interior face-arrival handling (`presence._handle_face_arrival`).
- NO cross-alert correlation, no historical-pattern learning, no phase-2 suppression logic. All phase-2 machinery deferred.

---

## Rev-2 change log

- **Binding decision #1 (LOCAL ONLY):** removed llmvision as an identity-source candidate throughout. D0(a) no longer probes llmvision-as-identity. Non-goals updated to state cloud-identity is REJECTED, not merely "recommended NO."
- **Binding decision #2 (D3 FOLD-IN):** replaced rev-1's D3 defer-recommendation with a full D3 stranger-leg spec (doorbell-only, additive-after-base, false-stranger guard with four gated conditions: enrollment coverage, identity-attempt timeout, confidence floor, cooldown). Added `stranger_leg_status` to D2 ledger. Extended INV-KP with clause (e): stranger leg is strictly additive and cannot delay/block base. Added D0(d) sub-probe for doorbell unknown cadence. Added stranger-leg knobs (2 kill/config + 4 rung-3 Numbers). Origin/context clarified: KP-ESCALATE-1 declined as standalone, scope absorbed here.
- **Binding decision #3 (IN-FIRST-MESSAGE ONLY):** removed annotate-by-edit branch from D0 adjudication rule and from D1 shape spec. Recorded as REJECTED alternative with revisit trigger. D0 latency histogram still records the 5s/10s/30s buckets as informational data for phase-2, but no code path consumes them in v1.
- **Pre-D0 tasks folded:** rev-1 open decisions #4 (`tracked_persons` currency) and #5 (message format) are now explicit D0.pre.1 and D0.pre.2 tasks in the D0 report. Default message format binds unless operator objects during D0 review.
- **Removed** rev-1's "Operator decisions needed (BEFORE D0 dispatch)" section — all five decisions are now either resolved (bindings) or folded as D0 tasks.

---

## Rev-2 summary (for the orchestrator)

**Changes:** llmvision removed from identity path (LOCAL ONLY); D3 stranger leg fully spec'd and folded in (was DEFER); annotate-by-edit path removed (in-first-message ONLY); INV-KP extended with clause (e) covering stranger-leg additivity; D0 gained (d) doorbell-cadence sub-probe and two pre-tasks (tracked_persons audit + format confirm); five new knobs for the stranger leg + false-stranger guard on the ladder; ledger extended with `stranger_leg_status` + `stranger_leg_latency_ms`; non-goals hardened; rev-1 "operator decisions" section deleted (all resolved or folded).

**NEW operator decisions surfaced by the fold-in:** aiming for zero. The fold-in raises two shape-level questions that plan-review or D0 review can adjudicate without a separate operator turn — noted here for transparency, not as blockers:
- (shape, not a blocker) Doorbell-camera identification is a D0.pre.1 task (bundle with tracked_persons audit) — expected: front-door doorbell only.
- (shape, not a blocker) Stranger-emission severity tier — one notch above `exterior_person` base is proposed; adjudicated at D0 review with house-state severity map open, NOT via a separate turn.
- (shape, not a blocker) For producers that don't expose confidence, plan review adjudicates whether the confidence floor is bypassed (fire on any unknown) or the operator picks a per-producer default at D0 review.

If any of these three shape questions require operator input BEFORE plan review, surface at D0 kickoff; otherwise they resolve inline.
