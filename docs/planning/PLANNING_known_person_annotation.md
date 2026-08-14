# PLANNING — Known-Person Annotation Pipeline v1 (ANNOTATE, don't suppress)

**Card:** KP-ESCALATE-1 (+ folds in the retiring doorbell face automation successor).
**Operator direction (2026-08-14):** exterior perimeter alerts today consult ZERO member/face data — a person page is identical to me whether it is my wife walking up the driveway or a stranger. **v1 = ANNOTATE**. When a face/identity signal is available for a perimeter person detection, the alert message gains a single line: `Person detected — likely <Name>`. The alert itself is preserved byte-for-byte otherwise. **No suppression, no severity change, no dedup change in v1.**

**Phase 2 (explicitly PARKED, not in this cycle):** per-person opt-in suppression / demotion. **Trigger to un-park:** annotation accuracy proven over N organic events with a per-annotation ledger — see D2. Do NOT design phase-2 machinery into v1.

**Tier:** **Tier 2-DB** (elevated per standing regression-prone policy). The pipeline threads external identity signals into `perimeter_alert.py` — the same alert path CONSOL-1 shipped through — where one missed emission site or one stale-identity leak is either a false accusation on a family member or a silenced-in-practice stranger. Three framing-disjoint reviews required (A=local correctness of the annotation adapter + freshness/coverage math, B=integration/state-machine — every perimeter emission site + no accidental suppression + byte-identical fall-through, C=ledger authority via real per-site source mutation). Plan review Tier 2 (one adversarial pre-build pass, re-enumerating emission sites and identity producers independently).

**Branch:** `feature/known-person-annotation-v1`.
**Scope target:** ≤ ~6 files touched (const, new adapter, perimeter_alert wire, ledger extension, config-flow, one sensor); D0 is a probe-only artifact and touches no runtime code.

---

## Falsifiable invariant (Reviewer D framing)

> **INV-KP:** Under any legal config, for any perimeter person-detection that reaches `PerimeterAlertManager._async_handle_perimeter_trigger`:
> (a) the alert dispatches to NM on the same code path, with the same `hazard_type`, `severity`, `title`, `coordinator_id`, `location`, snapshot, and cooldown/dedup behavior as it does today with the annotation adapter disabled — proven by a byte-identical `message` and identical `_kwargs` when the adapter returns `None`;
> (b) when the adapter returns a non-empty annotation string, the ONLY delta in the dispatched payload is exactly one appended line of the form `Person detected — likely <Name(s)>` (or the phase-1-approved template) inserted at a defined position; nothing else in the payload changes;
> (c) the annotation adapter's total wall time is bounded by `known_person_annotation_budget_ms` (rung-3 Number entity, default TBD by D0 latency data); on budget expiry, exception, empty result, or stale identity beyond the freshness window, the adapter returns `None` and the dispatch proceeds as (a) — with a ledger row recording `annotation_status ∈ {none, timeout, exception, stale, no_producer, disabled}`;
> (d) the adapter has NO write path — it cannot mutate NM state, cooldowns, `_dispatch_in_flight`, house_state, presence trackers, or `sensor.*` values.

Reviewer D falsifies (d) especially: enumerate every accessor the adapter reaches; any read that could trigger a state-machine side effect (RestoreEntity load, dispatcher fire, coordinator refresh) is a leak.

---

## Institutional context verified

**Prior planning consulted:**
- `docs/planning/PLANNING_exterior_person_escalation.md` — the original perimeter → NM wiring plan; establishes `hazard_type=exterior_person`, house-state severity map, and the `_async_handle_perimeter_trigger` shape we hook into.
- `docs/planning/PLANNING_consol_1_alerting_llmvision.md` — CONSOL-1 shipped `perimeter_enrichment.py` (the adapter shape being REUSED here) with `INV-ENRICH-NEVER-SILENCES` / `INV-ENRICH-NON-EMPTY` / `INV-ENRICH-BUDGETED` — v1 mirrors these invariants for identity.
- `docs/planning/AUDIT_consol_1_d0_probe.md` — the probe-first pattern this plan copies for D0.
- `docs/planning/AUDIT_frigate1_retirement_inventory.md` — Frigate-1 retirement inventory (needed to know which face producers are still live).
- kanban `KP-ESCALATE-1` + its `direction_2026_08_14` note — the source-of-truth direction.

**Code surfaces surveyed:**
- `custom_components/universal_room_automation/perimeter_alert.py:1272-1436` — message composition and dispatch. Confirmed insertion point: after §6b enrichment block, BEFORE `_do_dispatch` closure captures `message`. This is the single dispatch site for the person leg; a second site exists for vehicles at ~L2441-2517 (out of v1 scope: vehicles are not people).
- `custom_components/universal_room_automation/perimeter_enrichment.py` (full file) — REUSED as adapter shape: `asyncio.wait_for` budget, kill switches (rung-1 const, rung-2 config, rung-3 Number entity), `None`-on-any-failure contract, docstring-pinned invariants. The new adapter follows this exact shape.
- `custom_components/universal_room_automation/camera_census.py:2317-2345` (`_get_face_recognized_persons`) — **Frigate face producer, LOCAL.** Reads `sensor.<base>_last_recognized_face` per Frigate camera (derived from `binary_sensor.<base>_person_occupancy`). Filters out `unavailable/unknown/none/no_match`. No age check on the raw accessor.
- `custom_components/universal_room_automation/camera_census.py:2347-2400` (`_get_face_recognized_persons_fresh`) — **freshness-gated view** using `CENSUS_FACE_RECOGNITION_WINDOW_SECONDS` (age gate on `state.last_changed`). B-HIGH-1 fix-up from 2026-08-01 exists precisely because unbounded face reads corroborated stale evidence — v1 MUST use the fresh accessor, not the raw one.
- `custom_components/universal_room_automation/camera_census.py:2946-3080` (`_get_face_recognized_person_names`) — slug-normalized tracked-person view (`oji_udezue` from `person.oji_udezue`), driven by integration-config `tracked_persons`. Correct source for the display-name map.
- `custom_components/universal_room_automation/domain_coordinators/presence.py:4378-4420` (`_handle_face_arrival`) + `:570-571,919-920,4370-4376` — zone-tracker face state (`_last_face_recognized`, `_last_face_time`) with 30-second `FACE_FRESHNESS_SECONDS` gate. This is the INTERIOR consumer of face rec; it proves the producer is live and shows the freshness discipline already established. v1 does NOT modify this path.
- `custom_components/universal_room_automation/sensor.py:3485,5040-5042` — face state already surfaced on house/zone sensors as `face_recognized_persons` and `last_face_recognized`/`last_face_time`. Reused as read source in the adapter (no new attribute surface required for the identity read itself).
- `const.py` — greps for `CONF_KNOWN_PERSON_*`, `CONF_FACE_*`, `CONF_PERSON_ANNOTATION_*` returned NONE. All annotation knobs are NEW.

**REUSED vs NEW tally:**
- REUSED: adapter shape (perimeter_enrichment.py), Frigate face accessor (camera_census `_get_face_recognized_persons_fresh` + `_get_face_recognized_person_names`), presence tracker face state, hazard/severity/dispatch path (unchanged), `tracked_persons` integration-config list, `CENSUS_FACE_RECOGNITION_WINDOW_SECONDS` freshness constant, `sensor.face_recognized_persons` surface.
- NEW: `known_person_annotation.py` module (adapter), 3-5 `CONF_*` (enable, per-camera producer bindings, annotation format), 1 module const kill switch, 1 rung-3 Number entity (budget), 1 rung-3 Number entity (freshness window override — only if D0 shows Frigate's default 300s is wrong for perimeter cadence), extension to the perimeter dispatch ledger row shape (`annotation_status`, `annotation_identity`, `annotation_producer`, `annotation_latency_ms`).

**Memory bodies pulled:** `feedback_measure_before_build.md`, `feedback_marginal_benefit_pushback.md`, `feedback_suppression_needs_discharge.md` (v1 has no suppression — enforced by this rule), `feedback_hollow_test_anchors.md`, `feedback_no_fabrication.md` (all identity-producer claims in D0 must be confirmed via live probe, not documentation), `feedback_wire_in_anchor_mandatory.md` (D1 acceptance requires a behavioral test that goes red if the adapter call is neutered).

**Design docs:** No `docs/Coordinator/perimeter*.md`; perimeter is module-scoped.

**Not verified / open:**
- UniFi Protect face detection availability today — D0 probe must confirm whether the `unifiprotect` platform exposes a per-camera face attribute on the operator's actual devices, or whether Frigate is the only live producer. Do NOT assume from documentation.
- Whether Doubletake survived the Frigate-1 retirement — D0 probe grep against live entity registry.

---

## D0: Read-only measurement probe (GATES EVERYTHING)

**Purpose (per CLAUDE.md "Measure Before You Build"):** the plan's value and the shape of D1 depend on empirical properties of identity signals that already exist on the running house. Build the probe FIRST, run it against the live HA recorder + entity registry, commit the report as `docs/planning/AUDIT_known_person_d0_probe.md`, and gate D1/D2/D3 on its findings.

**Delivery form:** one Python script executed via `ssh ha "python3 -" < script.py` (same shape as the CONSOL-1 D0 probe). Read-only against `home-assistant_v2.db` (recorder) and the live entity/config registry. No runtime code changes.

**Questions the probe MUST answer:**

**(a) Identity-producer inventory per exterior camera (TODAY).**
For each configured perimeter camera (from `CONF_PERIMETER_CAMERAS` on the live integration config entry):
- Is there a Frigate face producer? (`sensor.<base>_last_recognized_face` present in registry — derive `<base>` per `camera_census._get_face_recognized_persons` algorithm.) If yes: what states has it emitted in the last 30 days? (SELECT DISTINCT state FROM states WHERE entity_id = ? — quantify how often it produces a real name vs `unknown/unavailable/no_match`.)
- Is there a UniFi Protect face attribute? (Inspect `camera.<name>` entity attrs and any `event.<name>_smart_detection` companion; look for `last_face_recognized` / `last_face_time` on any UP-platform entity — do NOT assume the attribute names; enumerate.)
- Is Doubletake still installed? (Registry grep `doubletake` — expected NO post Frigate-1 retirement, but confirm.)
- llmvision (CONSOL-1 enrichment, default OFF): note as *cloud, prompt-and-photo-based*, not a face-rec producer in the identity sense. Flag for the privacy adjudication in the operator-decisions section — using it as an identity source would require sending household reference photos to a cloud LLM.

**(b) Latency + coverage on real perimeter events.**
Reconstruct the last ~30 days of perimeter person-detection events from the recorder (state ON transitions on any entity in `CONF_PERIMETER_CAMERAS` — mirror the trigger the alert manager itself uses). For EACH event:
- Was any identity producer's `state.last_changed` within `[event_time − 30s, event_time + 30s]`? (Producer-per-camera from (a).)
- What was the identity value (name / `unknown` / `no_match` / no update)?
- Delta seconds between event and nearest identity update (signed: negative = identity arrived AFTER the alert).

Report as a per-camera table + a rollup histogram:
- % of events where a *real name* was available at event time − 0s (in-first-message annotation is viable).
- % where a name arrived within +5s / +10s / +30s of event time (would require annotate-by-edit / follow-up-message shape).
- % where no name ever arrived within +60s (annotation would remain absent — this is the fall-through case).

**(c) Enrollment coverage.**
For each `tracked_persons` slug on the integration config: has that person's face been recognized by ANY producer at least once in the last 30 days? Persons with zero recognitions are effectively unenrolled — v1 cannot annotate them regardless of pipeline health.

**Adjudication rule (drives D1's message-timing shape):**
- If (b) shows ≥70% of events have a real name available at t=0: v1 D1 is **in-first-message annotation** (annotation adapter runs synchronously inside the dispatch, budgeted).
- If (b) shows the identity signal *typically arrives 5–15s late*: v1 D1 is **annotate-by-follow-up-edit** — the initial alert fires unannotated (byte-identical to today), and a bounded delayed task fires a *second* NM message (e.g. via a `annotation_arrived` route reason) linking to the first. The bounded delayed task is a *new* rare-fire code path — evaluate marginal benefit vs risk per `feedback_marginal_benefit_pushback.md` before adopting; if margin is thin, ship only the in-first-message shape and accept the coverage gap.
- If (b) shows <30% coverage at any timing: park v1 build entirely, publish D0 as-is, and revisit KP-ESCALATE-1 with a "producer coverage insufficient" verdict. This is a legitimate probe-driven no-go outcome.

**Acceptance:**
- **Verify:** `docs/planning/AUDIT_known_person_d0_probe.md` committed with the three tables (producer inventory, latency histogram, enrollment coverage).
- **Verify:** every claim in D1's design cites a row/number from the D0 report — no design number is asserted without a probe row.
- **Verify:** the operator sign-off in the doc explicitly picks in-first-message vs by-edit vs park-v1.

---

## D1: Annotation wire (`known_person_annotation.py` adapter + perimeter_alert insertion)

**Gated on:** D0 (a)+(b) show ≥1 local producer with usable coverage.

**New module `custom_components/universal_room_automation/known_person_annotation.py`.** Mirrors `perimeter_enrichment.py` shape 1:1:

```python
async def annotate_perimeter_person(
    hass, camera_entity_id: str, event_time: datetime
) -> AnnotationResult | None:
    ...
```

Where `AnnotationResult` is a small dataclass carrying `(display_names: list[str], producer: str, identity_age_s: float, latency_ms: float)`. On any failure class (kill switch, disabled, no producer bound, stale beyond window, budget expiry, exception, empty result), returns `None`. **No exception escapes.**

**Producer resolution:** per-camera producer binding (see knobs below) — the adapter reads ONLY the bound producer's entity. Multi-producer per camera is out of v1 scope (adjudicate in D0 whether any camera actually has more than one).

**Freshness:** identity value's `state.last_changed` age must be ≤ `known_person_annotation_freshness_s` (rung-3 Number, default = D0-driven; upper bound = `CENSUS_FACE_RECOGNITION_WINDOW_SECONDS`). Older = `stale` → return `None`.

**Display-name mapping:** slug → display name via `tracked_persons` friendly-name lookup on the person entity registry (already the shape `_get_face_recognized_person_names` uses). If the recognized identity is not in `tracked_persons` (i.e. a name the face model knows but the operator has not enrolled here), return `None` — v1 does not annotate unrecognized-by-config names, to avoid rendering `Person detected — likely gardener_maybe`.

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

**In-first-message vs by-edit:** the module contract above is the in-first-message shape. If D0 selects by-edit, add a `dispatch_followup_annotation(...)` bounded delayed task that fires a SECOND NM message with `hazard_type=exterior_person_annotation`, throttled per `(camera, identity)` per 5 min. Do NOT design both shapes into the same build — pick one at D1 kickoff based on D0.

**Vehicle leg (L2441-2517):** NOT touched in v1. Vehicles are not people; annotation semantics don't map. Explicit non-goal.

**Acceptance:**
- **Verify:** message diff shows exactly one appended line when `annotation` is present, byte-identical otherwise.
- **Verify:** adapter total wall time p95 ≤ budget in a fixture with a synthetic 2× budget producer delay (proves the `wait_for` bound holds).
- **Test:** `quality/tests/test_known_person_annotation_wire.py` — includes a wire-in-anchor test (per `feedback_wire_in_anchor_mandatory.md`) that neuters the ONE call site in `perimeter_alert.py` (comment out the `annotate_perimeter_person` line) and asserts a specific test goes RED, restored after. A test that stays green under the neuter is unacceptable evidence.
- **Test:** each failure class (disabled, kill-switched, no producer, stale, timeout, exception, empty, unrecognized-name) produces `AnnotationResult=None` and byte-identical `_kwargs`.
- **Live:** trigger a real perimeter detection on a camera whose bound producer has a recent recognized face for a `tracked_persons` member; NM message body contains `Person detected — likely <Name>` on exactly one line, at the position defined. Cooldown, severity, snapshot URL, and `hazard_type` unchanged vs the immediately-prior unannotated alert on the same camera (compare recorder rows).
- **Live:** trigger a perimeter detection on a camera with NO bound producer OR with the face sensor at `unknown`; NM message is byte-identical to the current v5.75.x message. Ledger row shows `annotation_status ∈ {no_producer, none}`.

---

## D2: Ledger honesty (annotation recorded per row — phase-2 gate)

**Purpose:** the phase-2 gate ("annotation accuracy proven over N organic events") needs data. Every perimeter dispatch must record what the annotation adapter did.

**Where:** the existing perimeter dispatch ledger row (whichever DAO/table `perimeter_alert.py` currently writes on dispatch — verify at build time; if none exists, extend the anomaly/notification row shape rather than adding a new table).

**New columns / attributes on the ledger row:**
- `annotation_status`: enum { `annotated`, `none`, `no_producer`, `stale`, `timeout`, `exception`, `empty`, `unrecognized_name`, `disabled`, `kill_switched` } — mutually exclusive.
- `annotation_identity`: the raw producer state value (nullable; e.g. `oji_udezue`). Stored raw so future analysis can distinguish "producer said Oji" from the display-name mapping.
- `annotation_producer`: which producer the adapter read (`frigate:sensor.<x>_last_recognized_face` / `unifi:<...>` / `none`).
- `annotation_identity_age_s`: age of the identity value at the time it was read (nullable).
- `annotation_latency_ms`: adapter wall time.

**Read surface (small):** ONE new sensor `sensor.known_person_annotation_stats` with attrs `{total_events, by_status: {...}, last_annotated_identity, last_annotated_camera, last_annotated_at}`, rolling 30d window. Enough to spot-check without a DB query. Follows the CONSOL-1 stats-sensor pattern (mimic `sensor.perimeter_enrichment_stats` if present; otherwise the same shape).

**No feedback loop in v1.** The ledger is READ-ONLY consumption for phase-2 evaluation. Nothing in v1 acts on the ledger — enforced by grep in review (no imports of the ledger read path outside the sensor).

**Acceptance:**
- **Verify:** every perimeter person dispatch after D1 ship writes exactly one ledger row with `annotation_status` populated.
- **Verify:** `sensor.known_person_annotation_stats.by_status` sums to `total_events` across the window (accounting invariant).
- **Test:** row-shape fixture asserts all 5 columns present with correct types on each status class.
- **Live:** after 24h, `sensor.known_person_annotation_stats` shows non-zero `total_events` and a plausible status distribution matching D0's producer-coverage histogram.

---

## D3: Retiring doorbell face-automation successor (KP-ESCALATE-1 original ask)

**Decision required at D3 kickoff — DO NOT build both.** KP-ESCALATE-1 was originally scoped as *replace the doorbell face automation that CONSOL-1 is retiring*. The direction pivot to annotation-first covers the *known-face-at-perimeter → annotate* half. The other half is *unknown-face-at-doorbell → alert*.

**Two mutually exclusive options for v1:**

- **D3-A: Fold as an inverted-annotation leg.** The same pipeline, but when the producer returns a real name that is NOT in `tracked_persons`, or the producer returns `unknown` in the presence of a person detection at the doorbell camera specifically, dispatch an additional NM notification with `hazard_type=exterior_unknown_person` at a doorbell-specific severity (per the existing house-state severity map). This is a *new emission*, not annotation — it changes alert volume and requires its own falsifiable invariant and D0-style measurement (how often would this fire per day today?). If margin is thin, DEFER.

- **D3-B: Explicit defer.** Publish a one-paragraph note in `KANBAN.md` marking the doorbell face-alert successor as PARKED with trigger *"annotation coverage from D2 shows ≥70% of doorbell person events resolve to a `tracked_persons` name; the residual `unknown` slice is small enough to alert on without volume blow-up."* Un-park after v1 has 4 weeks of D2 data.

**Recommendation (marginal-benefit decomposition, `feedback_marginal_benefit_pushback.md`):** default to **D3-B**. D3-A introduces a *new* alert emission on a rare path with unknown per-day cadence — the exact profile that has burned prior cycles. The annotation pipeline (D1+D2) captures the majority of KP-ESCALATE-1's value with none of that risk. D3-A can be built with confidence in a follow-up once D2 has shown what "unknown at doorbell" cadence actually looks like on the running house.

**Adjudicate at D3 kickoff.** Do not enter D1 build without an operator go/no-go on this.

---

## Knobs (ladder placement — `feedback_numbers_get_knobs_ladder.md`)

| Knob | Rung | Home | Default | Why here |
|---|---|---|---|---|
| `KNOWN_PERSON_ANNOTATION_KILL` | 1 (module const) | `const.py` | `False` | Fire-axe kill switch; changing it should require review. |
| `CONF_KNOWN_PERSON_ANNOTATION_ENABLED` | 2 (config) | integration config entry | `False` at ship (per CONSOL-1 precedent — default OFF until proven) | Per-deployment enable; infrequent, persistent. |
| `CONF_KNOWN_PERSON_ANNOTATION_PRODUCER_BINDINGS` | 2 (config) | integration config entry | `{}` | Structural (per-camera → producer entity_id map); operator-set once per camera. |
| `CONF_KNOWN_PERSON_ANNOTATION_FORMAT` | 2 (config) | integration config entry | `"Person detected — likely {names}."` | Wording change is deployment-flavor, not runtime-tuning. |
| `known_person_annotation_budget_ms` | 3 (Number entity) | Number platform, Number-persistence machinery | D0-driven (likely 500-1500ms) | Live-tunable observation knob; operator legitimately dials for latency vs coverage. |
| `known_person_annotation_freshness_s` | 3 (Number entity) | Number platform | D0-driven, clamped ≤ `CENSUS_FACE_RECOGNITION_WINDOW_SECONDS` | Same rationale. Kill-switch value: `0` disables the annotation (adapter treats any age as stale). |

Every one of these is a **NAMED** configurable — no inline literals. `CONF_KNOWN_PERSON_ANNOTATION_*` grep returned NONE, so all are NEW.

---

## Acceptance criteria (rollup)

**Cycle-level:**
- D0 report committed, operator-signed for the timing shape (in-first-message vs by-edit vs park).
- D1 adapter shipped with wire-in anchor test that goes red on neuter.
- D1 byte-identical fall-through proven by `_kwargs` diff test.
- D2 ledger writes every dispatch with a populated `annotation_status`.
- D2 stats sensor live and non-zero within 24h of deploy.
- D3 explicitly adjudicated (A or B) and recorded.
- Three framing-disjoint reviews returned SHIP before deploy; plan review pass complete before build dispatch.
- Post-deploy README carries a *Validated <date>* table with entity/attribute-cited results (per operator-mandated README write-back).

**Live-only (post-restart) — writes back into `README_v<version>.md` per policy:**
- Real perimeter person event on a bound camera with recent face rec → NM body carries the annotation line, cooldown/severity/snapshot unchanged vs prior alert on same camera.
- Real perimeter person event on an unbound camera → NM body byte-identical to pre-deploy shape; ledger `annotation_status = no_producer`.
- `sensor.known_person_annotation_stats.total_events > 0` within 24h.
- No new `ERROR` logs from `known_person_annotation` module for 24h.

---

## Non-goals (explicit)

- NO alert suppression, demotion, silencing, or dedup change of any kind. `severity`, `hazard_type`, cooldown, dispatch topology unchanged. Any reviewer finding that the adapter could suppress an alert is a CRITICAL.
- NO new face-enrollment machinery. v1 consumes only face producers that already exist on the running system (Frigate face rec, and/or UniFi Protect face if D0 confirms it).
- NO sending reference photos to cloud LLMs. llmvision remains a scene-descriptor (CONSOL-1's role), not a face-identity source. See operator decision below if this changes.
- NO changes to the vehicle leg (L2441-2517).
- NO changes to interior face-arrival handling (`presence._handle_face_arrival`).
- NO cross-alert correlation, no historical-pattern learning, no phase-2 suppression logic. All phase-2 machinery is deferred until D2 has real data.

---

## Operator decisions needed (BEFORE D0 dispatch)

1. **Privacy adjudication — llmvision as identity source: default NO?**
   Using llmvision (CONSOL-1's cloud enrichment path, gpt-4o-mini) as a *face-identity* source would require sending household reference photos + live snapshots to a third-party LLM API. This leaves the LAN and creates a persistent cloud record of household member faces + timestamps. Recommend **NO** for v1: restrict identity producers to *local-only* sources (Frigate face rec, UniFi Protect face if present). Confirm this stance before D0 so the probe doesn't spend cycles on cloud-identity feasibility.

2. **D3 fold-in vs defer.** Recommend D3-B (defer) per marginal-benefit analysis above. Confirm or override.

3. **In-first-message shape preference (soft — D0 will drive this).** If D0 latency data is borderline (e.g. 40-60% coverage at t=0, but +5s pushes to 80%), do you prefer (i) ship in-first-message only and accept the 40% annotated / 60% unannotated split, or (ii) build the annotate-by-edit shape and take on the new rare-fire delayed-task code path? Recommend (i) for v1 simplicity — revisit (ii) after D2 shows real cadence.

4. **`tracked_persons` audit.** Before D0, is the integration-config `tracked_persons` list current? Anyone missing from it cannot be annotated in v1 regardless of face-rec coverage. If the list is stale, curate it before D0 so coverage math isn't distorted.

5. **Message format ergonomics.** Default proposed: `Person detected — likely {names}.` on its own line at the end of the message. Acceptable, or prefer a different position/format (e.g. prepended to the title, bracketed at start of message)?
