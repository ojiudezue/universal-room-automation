# PLANNING — Path-α LOST dissolution + memory writers for the new away logic

**Rev-2 (2026-08-16):** post-operator-checkpoint amendments — three writers this cycle (added `tracker_trust_excluded`); no parked debt (verdicts below on the remaining three candidates: `house_state_transition` BUILD, `zone_phantom` DROP, `exterior multi-source witnesses` DROP); two new Scope-A design inputs evaluated (companion GPS: **already the fix, incorporated**; exterior-path evidence: **DROP from this cycle**, justified); new §"Why occupancy flips are memory-ineligible"; vibememo-after-builds note added.

**Cycle IDs:** PATH-ALPHA-DENOM-1 (Scope A) + MEMORY-WRITERS-1 (Scope B; **four writers total**: 3 built this cycle + 1 build-now verdict folded in) + GUEST-FP-RESIDUALS-1 A1 rider.
**Tier:** 2-DB (operator-elevated de facto — trust-hierarchy ripple on tracking_status; every trust-tier consumer must be re-enumerated). Plan gets ONE adversarial plan review before build dispatch per Tier-2 plan-review protocol.
**Author:** ura-planner (Oji Udezue). **Date:** 2026-08-16.
**Depends on:** ZONE-TIER-DIVERGE-1 trace merged (same code region in presence.py); MEMORY-COMPACTOR-1 shipped (writers assume compactor exists so per-topic distillation rules can be registered day-1).
**Non-goal:** does NOT fix the phantom-zone / fan-loop side of AWAY-BLOCK-1 (that is rec 1/2 on that card). Fixes ONLY the path-α trusted-denominator vacuity that lets a phantom zone win — an independent mitigation.

---

## Falsifiable invariant (state up front — D-framing target)

> **I-α:** For any tick in which every configured person has an unambiguous "away" adjudication from ANY of the case-(a) sources listed in §"Case-(a) sources" (companion-app GPS `person_state == "away"`, or Bermuda-STALE with last-known `location=="away"`, or Bermuda-LOST with `person_state == "away"`), path-α's away-eligibility precondition (`all_tracked_persons_away == True` AND `tracked_persons_count_trusted > 0`) MUST evaluate True — not False-by-vacuity. This holds in ANY reachable configuration (any number of persons ≥ 1, any mix of case-(a) source types per person, fresh install with zero Bermuda fixes ever, restart re-hydration).

Break the invariant → plan is falsified. D's job is to enumerate every reachable state (single-person; multi-person mixed sources; brand-new installs; phone-left-behind interacting with case-(a); guest-mode arm/disarm boundaries; restart re-hydration) and produce a legal-config repro if I-α can be broken.

Secondary invariant on write-rate discipline (memory sprawl guard, §"Memory intent & limits"):

> **I-M:** In steady state (no incidents), the `away_transition_blocked` writer emits ≤ 1 row per calendar day per house; the `occupancy_phantom_retro` writer emits at most 1 row per (room, fan-release event); the `tracker_trust_excluded` writer emits ≤ 1 row per person per exclusion-enter/exit edge (not per tick); the `house_state_transition` writer emits ≤ N rows per day where N = actual house-state transition count (already bounded by house_state_log's own edge semantics — a handful per day). No writer is a per-tick logger, and no writer couples to a detector gate whose failure would silence it.

---

## Institutional context verified

**Grep-verified prior art (REUSED vs NEW):**

- `TRACKING_STATUS_{ACTIVE,STALE,LOST}` — const.py:167-169. **REUSED** as the vocabulary being decomposed; NO new tracking-status constants added by this plan (see §"Design choice #1" for the naming argument).
- `_tracking_active_or_lost_away` (presence.py:169) + `_tracked_persons_count_trusted` (presence.py:1319) + `_all_tracked_persons_away` (presence.py:1320) + `excluded_persons` (presence.py:5097, 1325) — the WS-A1 v5.7.0 path-β machinery. **REUSED** as the model to follow for path-α; path-α gets a symmetric "counts-case-(a)-as-away" denominator. Simplifies (may deprecate) the path-β helper.
- **`person_state` (HA `person.<name>` entity) already consulted at `person_coordinator.py:150` and BRANCHED ON at :352, :394.** When Bermuda has no fix, the code READS `person_state.state`. If `"home"` → assigns `location="home", tracking_status=LOST` (:359-369). If `"away"` (else branch at :370-389, :422-432) → assigns `location="away", tracking_status=LOST, confidence=0.9`. **This is THE defect: `person_state == "away"` is high-confidence evidence (HA person entity aggregates device_tracker.*, including the mobile app companion GPS + router presence), yet tracking_status is stamped LOST purely because Bermuda has no fix. Case-(a) fix is a ONE-LINE change at :385 and :428: assign `TRACKING_STATUS_ACTIVE` in these branches.** This is the operator's design-input (b) answered from source, not speculation.
- `MEMORY_EPISODE_TYPES` frozenset (const.py:3642) — **REUSED as registry** for the four new episode types; adding a member is a reviewed change, which IS the write-quality gate per architecture §4.
- `Database.log_memory_episode` (database.py:8355) — **REUSED** end-to-end. Carries: unregistered-type WARN gate, in-memory (node,type) dedup window (`MEMORY_EPISODE_DEDUP_WINDOW_S`), optional `dedup_source_ref`, write-queue integration. All four writers use this and specify a `source_ref` for retro/edge dedup.
- `MEMORY_FACT_TOPICS` (const.py:3660) — **REUSED**; compactor rules key off two new topics (`away_transition_blocked`, `tracker_trust`).
- Path-α precondition (`all_tracked_persons_away`, presence.py:1048 + :4875) — **THE SITE BEING EDITED.** Verified end-to-end trace: dispatched via `should_veto_due_to_reliable_signals(scope="house_inference")` at :5966; consumed by house-tier away inference; feeds `attrs.all_tracked_persons_away` (:5441) and `_all_tracked_persons_away` on the PresenceHouseStateSensor (:5204).
- `house_state_log` DB table (already populated by presence.py on every house-state transition) — **REUSED as source** for the `house_state_transition` writer (mirrors edges from the existing table into memory_episodes with a gate-input snapshot; not a second write of the same event, but an *adjudicated* episodic view).
- `transit_validator.py` — CONSULTED (surface is CHECKPOINT sequences + EGRESS direction — designed for BLE-camera transit correlation, NOT exposed as "last transit ended at egress" query today). See §"Rejected design input (a)" for why it's dropped from this cycle.
- Camera census (camera_census.py:2296-2335) treats STALE+LOST both as "not-here" for census bookkeeping. **CONSUMER site — must be re-verified** during D1 that the new AWAY-vs-LOST distinction preserves the "not-here" reading (it should: away⇒ACTIVE-away still reads not-here).
- `fan_veto.py:222-234` — consumes `tracking_status == ACTIVE` as its trustworthiness signal (comfort-fan away-veto). **CONSUMER site — reviewed for regression**; a case-(a) person now READS ACTIVE-away and fan_veto only fires in house_state ∈ {AWAY, VACATION}, so the classification loop closes correctly.
- `aggregation.py:5286-5566` — per-person sensor tracking_status attribute writer. **CONSUMER (display)**: values surface to dashboards; adding `BLE_SILENT` needs an icon.
- `sensor.py`, `binary_sensor.py`, `person_coordinator.py:294-428` — tracking_status producers/consumers; enumerated in D1 (below).

**Prior planning docs consulted:**

- `docs/planning/AUDIT_away_transition_2026_08_13.md` (root of AWAY-BLOCK-1; §"(b) Root-cause chain" step 1 states the α gap this plan closes).
- `docs/planning/AUDIT_ble_house_level_weighing.md` (alternate BLE-vacancy conjunct shape — parked path 3 in this plan's alternates).
- `docs/planning/AUDIT_guest_fp_fixes_wiring.md` (source of the A1 rider: path-α diagnostic classifier still lumps LOST-away with excluded).
- `docs/planning/AUDIT_memory_retro_value.md` (source of the memory writers; all six candidates now dispositioned build-or-drop per no-debt rule).
- `docs/planning/AUDIT_zone_tier_divergence.md` (same code region; ZONE-TIER-DIVERGE-1 must land first — sequencing gate).
- `docs/planning/PLANNING_guest_fp_lost_away_and_outdoor_census.md` (v5.16.0 fixed the *veto* denominator; verified this plan does NOT overlap).
- `docs/planning/VISION_hierarchical_memory.md` + `docs/planning/ARCHITECTURE_hierarchical_memory.md` — memory intent/limits; read end-to-end for §"Memory intent & limits" and §"Why occupancy flips are memory-ineligible".

**Memory bodies pulled (full):**

- `project_zone_away_when_occupied_home_night_gap` — adjacent (same "away signal fires through occupied room" family) but fix surface is D1 vacancy overrides, NOT tracking_status decomposition. NO REGRESSION VECTOR here.
- `project_presence_guest_latch_and_veto_gap` (v5.16.0 SHIPPED) — the empty-denominator fix in the guest/veto path. This plan applies the SAME shape to path-α.
- `project_guest_mode_false_positive_backlog` — "lost-but-away excluded from trusted → phantom unidentified → guest". Scope A retires the "excluded" half for case-(a) trackers.

**Design docs read:**

- `docs/Coordinator/PRESENCE.md` (skimmed for house_state inference contract; "path-α ignores zones entirely" is upheld — this plan does NOT introduce a zone-look inside α).

**Code locations surveyed end-to-end (during scoping):**

- `custom_components/universal_room_automation/domain_coordinators/presence.py` (paths α/β around :5029–:5210; :4857–:4900 predicate helper).
- `custom_components/universal_room_automation/person_coordinator.py` (:140–:436 — every branch that stamps `tracking_status`).
- `custom_components/universal_room_automation/const.py` §tracking + §memory.
- `custom_components/universal_room_automation/database.py` `log_memory_episode` + `memory_episodes` DDL (:1533).
- `custom_components/universal_room_automation/memory_facade.py` + `memory_compactor.py` — signatures/topic gate; writers land in the existing pipeline without new tables.
- `custom_components/universal_room_automation/transit_validator.py` (:1–:80 header — enough to confirm current exposed surface is checkpoint-sequences + egress-direction, not "last transit ended at egress" query).

---

## Memory intent & limits (sprawl guard — REQUIRED)

Restated from `VISION_hierarchical_memory.md` + `ARCHITECTURE_hierarchical_memory.md`:

1. **Five kinds of memory only** — episodic, baseline, outcome, identity, consolidated-facts. All four proposed writers in Scope B are **episodic** — no new kind, no new tier.
2. **Seven verbs, hard ceiling** — `baseline / unusual / episodes / outcome / narrative / profile / facts`. Vision §3 names verb-creep as a danger. **No writer earns a verb.** Consumers query them through `episodes(node=<x>, pattern=<type>, ...)`. Zero new interface surface.
3. **§8 access policy + memory-ineligible decisions — NEVER cross.** Enumerated in architecture §8: safety actions, security arm/disarm, occupancy creation/release, reserve-floor/clamp invariants NEVER take memory as input. See §"Why occupancy flips are memory-ineligible" below for the rationale (operator question, answered). This plan preserves that boundary absolutely: all four writers OBSERVE only. Zero actuation feedback.
4. **No LLM, no ML** — pure rule-based emissions. Distillation into facts is deferred to the shipped compactor's registered rules.
5. **No memory-driven actuation in phase 1** — upheld: only NM / diagnostics / dashboard / operator queries consume the new writers.
6. **Episodes = NOTABLE events, not samples** — enforced per-writer:
   - `occupancy_phantom_retro`: fan-release-edge only, with correlation window gates.
   - `away_transition_blocked`: sustained-block coalescing (open-on-first-blocked-tick, close-on-unblock), MIN_HOLD_S gates single-tick recovery from opening an episode.
   - `tracker_trust_excluded`: EDGE-only — person ENTERS or LEAVES the excluded-persons map. Not per-tick while excluded.
   - `house_state_transition`: EDGE-only — mirrors house_state_log's own edge semantics (already bounded to actual transitions).
7. **Future applications from vision §5:** NM quieting, decision-outcome loops, cross-node systemic-vs-local, episodic recurrence, explainability, the paper. These four writers are within-limits contributions to (4) episodic recurrence and (5) explainability.

**Boundary the writers MUST NOT cross (build gate):**

- No writer becomes a high-rate transition logger. **I-M** enforceable per-writer (D1 acceptance criterion + fixtures that fire the trigger 100× in a synthetic minute and assert row-count ≤ N).
- No writer is consumed by away inference, fan actuation, occupancy creation/release, or any memory-ineligible decision. Reviewer B in the Tier-2 review verifies the consumer graph is empty.
- If a writer ever needs a new verb, STOP and re-scope — do not add a verb.

**Argument: the four writers are within intent.** Minimal episodic instrumentation of the incident classes we can name today, keyed on signals that already exist, emitted through the shipped queue, gated by the shipped registry, distilled by the shipped compactor. Zero new tables, zero new verbs, zero new consumers, zero actuation.

---

## Why occupancy flips are memory-ineligible (operator question, answered)

The memory-ineligible list bars memory as an **INPUT to live occupancy DECISIONS**, not occupancy as **memory CONTENT**. Rooms DO remember occupancy: `occupancy_events` is one of the oldest URA tables, the `occupancy_phantom` and (soon) `occupancy_phantom_retro` episode types ARE occupancy memory, the `occupancy_baseline` compactor topic IS occupancy memory. What §8 forbids is the reverse direction: **an occupancy-decision code path calling `memory.baseline(...)` or `memory.facts(...)` and letting the answer flip the live decision.**

Two reasons the boundary exists, both operator-durable:

1. **Present-tense facts must beat compressed-past priors.** A live PIR firing is direct present-tense evidence of a body; a memory answer "Study A is usually empty at 2pm (support=n)" is a compressed statistical prior. Letting the prior out-vote the live sensor inverts the epistemic hierarchy of the whole system — the room would decide unoccupied *while a person stands in it* because history says people aren't usually here. This is exactly the class of failure that AI-heavy home-automation stacks are notorious for.

2. **The feedback loop compounds confident garbage.** If memory could flip occupancy, then:
   - a phantom-poisoned prior would CREATE occupancy at times/rooms matching the prior;
   - that fabricated occupancy would write more `occupancy_events` (and `occupancy_phantom_retro` would NEVER retro-adjudicate them because their creation was itself memory-driven, not fan-driven);
   - the next baseline fold would strengthen the poisoned prior with the fabricated evidence;
   - the loop closes and there is no live signal that can break it.

Contrast with the OK direction (interpretation and annotation):
- NM severity conditioning: memory answers "this smoke sensor false-alarms a lot" → NM adjusts notification TONE, never suppresses response. Live actuation unchanged.
- Dashboard: memory answers "Living Room phantoms recurred 12 times in 30d" → operator sees it, decides.
- Explanation: `narrative()` cites episodes for context; nobody's action is gated.
- Adjudication: retro-phantom writes an ADJUDICATION on a past event; it doesn't flip the current occupancy state (which released 37s ago by hardware).

**Rule of thumb (operator-durable):** memory adjusts *interpretation and attention*; live evidence decides *action*. Occupancy decisions live on the action side, so memory reads must not cross into their code paths. The four writers in this plan preserve this: `occupancy_phantom_retro` writes AFTER release (past-tense adjudication), `away_transition_blocked` writes ABOUT a decision without influencing it, `tracker_trust_excluded` writes AT edges of exclusion (which the trust-tier already computed), `house_state_transition` writes AT edges the state machine already emitted. None feed back.

Promoting any of these decision classes off the ineligible list (e.g. letting β discount phantom-classed zones from memory — AWAY-BLOCK-1 rec 3) is a Tier-3 review by definition and OUT of this cycle.

---


> **OPERATOR RULING (2026-08-16, binding): the two suggested inputs (exterior-path evidence,
> companion-GPS inspection) are POSSIBLE CONFIDENCE BOOSTERS ONLY — "we should be able to set
> state without them."** The core design must set tracking state from the signals it already
> has. Rev-2 complies: companion GPS via `person_state` is an EXISTING consulted source (not an
> addition) and the case-(a) fix is a stamp correction in existing branches; exterior-path is
> DROPPED. No reviewer or builder may make any new input load-bearing for state-setting.

## Scope A — LOST-state dissolution / decomposition

### D1 (FIRST DELIVERABLE) — Exhaustive consumer enumeration of `tracking_status`

**Why first:** the operator's structural direction cannot be answered without a full consumer inventory. Every read site classified into ONE of three semantic buckets:

| Bucket | Meaning today | Post-decomposition target |
|---|---|---|
| **Identity-uncertain** ("we don't know who this person is right now") | LOST used as "no data" | `LOST` (rare — truly unknown; never-had-a-fix + person_state==unknown) |
| **Location-uncertain** ("we know who, we don't know where") | LOST used interchangeably | `BLE_SILENT` (home-but-BLE-silent, phone-on-charger, person_state==home) OR resolved to **`ACTIVE`** with `location=away` when person_state==away |
| **Data-stale** ("we know who, we know where, the fix is old") | STALE | `STALE` — kept, unchanged semantics |

**Deliverable output:** committed artifact `docs/planning/AUDIT_tracking_status_consumers.md` filed at plan-review time (per operator flip on design choice #6). Table enumerates every grep hit for `tracking_status`, `TRACKING_STATUS_LOST`, `TRACKING_STATUS_STALE`, `TRACKING_STATUS_ACTIVE`, and helpers `_tracking_active` / `_tracking_active_or_lost_away`. Files known to touch (must be re-verified line-by-line in the artifact):

- `custom_components/universal_room_automation/person_coordinator.py` — WRITER (:168, :228, :294, :314, :365, :385, :428). **PRIMARY EDIT SITE.**
- `custom_components/universal_room_automation/domain_coordinators/presence.py` — paths α/β (:5081–:5210), reliable-signal dispatch (:5966), helper (:169-190).
- `custom_components/universal_room_automation/aggregation.py:5286-5566` — per-person sensor + icon + attrs (DISPLAY).
- `custom_components/universal_room_automation/camera_census.py:2296-2335` — census gate.
- `custom_components/universal_room_automation/fan_veto.py:222-234` — comfort-fan away-veto.
- `custom_components/universal_room_automation/sensor.py`, `binary_sensor.py`, `config_flow.py`, `__init__.py` — surface / options / bootstrap references.

**Acceptance:** (unchanged from rev-1)

- Enumeration is exhaustive (second-pass reviewer greps find zero new hits).
- Every hit classified with one-line justification.
- Each site marked BYTE-IDENTICAL or CHANGED (with intent).

### D2 — Design pick: dissolve LOST, adjudicated by companion-GPS-first ladder

**Chosen path: (1) Dissolve LOST into honest states** per operator direction, with case-(a) adjudicated by a **precise source ladder** (design-input (b) integration):

### Case-(a) sources — the "confidently away" ladder (adjudication precedence)

A person is assigned `TRACKING_STATUS_ACTIVE` with `location="away"` when ANY of the following is TRUE at classification time (highest-precedence source wins for the `method` attr, but any one satisfies case-(a)):

1. **`person_state == "away"` and no Bermuda area sensor** — person entity aggregates HA device_trackers including the mobile app companion GPS (lat/lon vs home zone) and router-based presence. When it says away, that's high-confidence away evidence. **Present in code TODAY** at person_coordinator.py:394-432 — the classification loop already reads `person_state.state`. The bug is the assignment on :428 stamps `TRACKING_STATUS_LOST`; the fix is `TRACKING_STATUS_ACTIVE`. `method="person_state"`.
2. **Bermuda area sensor exists, no recent BLE fix, `person_state == "away"`** — Bermuda has no room but companion GPS says away. Same fix at person_coordinator.py:370-389 (the else-branch inside the Bermuda-sensor-no-room path): stamp ACTIVE, not LOST. `method="person_state_over_ble"`.
3. **Bermuda STALE with last-known `location == "away"`** — the STALE state already keeps `location=away`; today it correctly holds `TRACKING_STATUS_STALE` (not LOST). STALE-away is already case-(a) semantically; no code change needed here, but path-α's denominator must ADMIT STALE-away persons the same way it admits ACTIVE-away. This is the denominator change.
4. **Never-had-a-fix + person_state == away** — fresh-install fallback via the person_state branch (person entity may still resolve via HA companion GPS even before Bermuda has learned rooms). Falls into source 1 above.

**Case-(b) — `TRACKING_STATUS_BLE_SILENT` (new enum, one value added):**

- `person_state == "home"` AND no recent Bermuda fix → BLE_SILENT (phone-on-charger, person may or may not be present but the BLE evidence is silent while HA still thinks the phone is home). Consumers must NOT count BLE_SILENT as "away." Path-α excludes BLE_SILENT from the trusted denominator the same way it excludes phone-left-behind. Code site: person_coordinator.py:352-369 (currently stamps `TRACKING_STATUS_LOST`; fix to `TRACKING_STATUS_BLE_SILENT`).

**Case-(c) — `TRACKING_STATUS_LOST` (kept, narrowed):**

- Bermuda has no fix AND `person_state == "unknown"` (no companion GPS input either — person entity itself is unknown). This is what LOST is FOR: truly unknown. Consumers exclude from trusted denominator. Code site: person_coordinator.py:152-172 (the person-entity-not-found branch stays LOST; add explicit unknown-state handling in the fallthrough).

**Adjudication precision (design-input (b) integration outcome):** the plan's case-(a) definition IS precisely which sources adjudicate 'confidently away' — the four-item ladder above. The gap the operator identified (companion GPS should already be the signal) is **already the input, mis-classified downstream**. No new plumbing needed; the fix is redirecting the assignment. Zero new device_tracker subscription code.

### Rejected design input (a) — exterior-path evidence

**VERDICT: DROP from this cycle.** Justification:

- Consulted `transit_validator.py`: the exposed surface today is CHECKPOINT sequences (BLE-camera correlation across configured checkpoint areas) and EGRESS direction (entry vs exit inference at egress cameras). There is NO public "did this person's last transit terminate at an egress camera" query — that would require new plumbing on the linker, a new derived signal, and a new subscription on person_coordinator.
- Marginal benefit is LOW after companion GPS is the primary case-(a) source: the operator's use case ("device on a path leading outside the house is strong away-evidence") is DOMINATED by companion GPS, which fires unambiguously once the phone leaves the home zone (typically within 1-2 minutes, before any transit-sequence probability calculation).
- Marginal risk of adding it now: new coupling between transit_validator and person_coordinator; new failure mode where a stale transit sequence over-adjudicates away; another ingredient in Tier-2-DB review scope.
- **Per no-debt rule this is not parked** — the exterior-path signal is not a needed capability for the invariant I-α. If organic evidence surfaces that companion GPS alone leaves case-(a) gaps (e.g. an operator whose phone has no HA app), the transit signal is one obvious source to add in a follow cycle — but that is a "revisit when needed," not a "we owe this build."

### Enum surface change

Net: keep `ACTIVE / STALE / LOST`; **add exactly one** — `BLE_SILENT`. Vocabulary grows by one; the overloading is broken by *reassigning case-(a) from LOST to ACTIVE-away* (the semantic move), not by many enums.

### Ripple accounting (unchanged from rev-1)

- Path-α denominator naturally includes case-(a) persons. **Invariant I-α holds structurally.**
- `_tracking_active_or_lost_away` becomes REDUNDANT — **DEPRECATE + delete** (design choice #2 unchanged).
- `camera_census.py` STALE+LOST bucketing — verify BLE_SILENT joins the "not-here" bucket.
- `fan_veto.py` `== ACTIVE` — case-(a) reads ACTIVE-away; fan_veto fires only in AWAY/VACATION states → correct by construction.
- `aggregation.py` display: BLE_SILENT gets `ICON_TRACKING_BLE_SILENT` (`mdi:cellphone-off` recommended).

**Acceptance criteria (Scope A):** (unchanged from rev-1; see prior section)

### D3 — Rider: GUEST-FP-RESIDUALS-1 A1 (~5 LoC path-α diagnostic classifier)

After D2 lands, case-(a) trackers no longer take the excluded path (they're ACTIVE, not excluded). Residual: message-formatting at presence.py:~5758 must not emit stale "lost-away" reason strings. ~5 LoC.

**Acceptance:** AUDIT_guest_fp_fixes_wiring.md A1 residual closed; no `excluded_persons` reason string carries "lost" for a case-(a) tracker.

---

## Scope B — the memory writers (4 built this cycle; other 2 dropped)

Per operator no-debt rule, every one of the six candidates from `AUDIT_memory_retro_value.md` gets a build-now-or-drop verdict below.

### Build-now (this cycle)

#### D4 — `occupancy_phantom_retro` writer (D2-independent) — BUILD

Unchanged from rev-1. Fan-release-correlation writer at ROOM node; captures the 5 latches of 2026-08-13; knobs `PHANTOM_RETRO_RELEASE_WINDOW_S` (60s) + `PHANTOM_RETRO_MIN_HOLD_S` (300s) at rung 1; source_ref-deduped; consumed only by episodes/narrative/compactor `phantom_recurrence` rule.

#### D5 — `away_transition_blocked` writer — BUILD

Unchanged from rev-1. HOUSE-node writer with open/close coalescing; knobs `AWAY_BLOCK_EPISODE_MIN_HOLD_S` (300s) + `AWAY_BLOCK_EPISODE_MAX_OPEN_S` (6h) + kill switch at rung 1; new fact topic `away_transition_blocked` in MEMORY_FACT_TOPICS; consumed only by episodes/narrative/compactor.

#### D6 — `tracker_trust_excluded` writer — BUILD (new in rev-2, added per operator instruction)

**Trigger:** on the EDGE where a person enters or leaves the `excluded_persons` map (presence.py:5207 `self._excluded_persons = dict(excluded_persons)` — diff against prior snapshot).

**Node:** `house` (the exclusion is a house-tier trust decision, not per-person memory in the identity sense).
**Episode type:** `tracker_trust_excluded` (NEW — add to `MEMORY_EPISODE_TYPES`).
**Adjudication:** `observed`.
**attrs:** `{person, edge: "entered" | "left", reason: <exclusion reason from map>, prior_tracking_status, new_tracking_status, house_state, ticks_since_last_change}`.
**source_ref:** `f"trust_excluded:{person}:{edge_ts.isoformat()}:{edge}"`.

**Knobs (rung 1 constants):** `TRACKER_TRUST_EXCLUDED_WRITER_ENABLED = True`. No other knobs — edge-only writer, rate-bounded by the edge frequency itself (a tracker enters/leaves exclusion at most a few times per day per person; incidents may spike to ~10/day, still well under I-M).

**Rationale for BUILD (why it's worth it):** provides a parallel observation channel to `away_transition_blocked` from the PERSON side rather than the HOUSE side. When Scope A ships, this writer records exactly which case-(b)/case-(c) trackers still land in the excluded map and why. That answers "did LOST dissolution actually shrink the excluded set organically?" without a recorder probe. It also instruments trust-flap: rapid enter/leave cycles on the same person show up as episode density in `episodes(node="house", pattern="tracker_trust_excluded", ...)`.

**Consumer graph:** episodes/narrative/compactor only. New compactor rule under NEW fact topic `tracker_trust` (add to `MEMORY_FACT_TOPICS`): "Person <X> was excluded N times in 30d, dominant reason=<Y>." Zero actuation feedback.

**Acceptance:**

- **Verify:** on a synthetic scenario where person A is stamped case-(b) BLE_SILENT for 3 minutes then transitions to case-(a) ACTIVE-away, exactly 2 rows emit (entered=BLE_SILENT, left=ACTIVE_AWAY).
- **Verify:** I-M — a person stably excluded for 24h emits exactly 1 row (the entering edge), NOT one row per tick.
- **Test:** `test_tracker_trust_excluded_writer.py` — three fixtures (enter, leave, flap). Mutation drill of the edge-diff logic reddens each with distinct names.
- **Live:** post-deploy, first organic exclusion edge writes a row; `episodes(node="house", pattern="tracker_trust_excluded")` returns it.

#### D7 — `house_state_transition` writer with gate-input snapshot — BUILD (verdict added rev-2, no debt)

**VERDICT: BUILD** (operator's guess confirmed). Justification:

- **Cheap** — the house state machine ALREADY writes house_state_log on every transition (verified: `house_state_log` DB table populated by presence.py). The writer mirrors these edges into `memory_episodes` with a richer gate-input snapshot (the inputs that JUSTIFIED the transition, not just the from/to pair). Zero new listener; hooks the existing transition emit.
- **Instruments exactly the code path this cycle changes** — Scope A modifies the inputs to path-α; the writer records the inputs at each transition so we can query "what did the α precondition look like at every home→away transition post-deploy" via `episodes()` instead of a recorder+SQL forensics session. That's the definition of episodic memory earning its keep.
- **Complements D5** — `away_transition_blocked` records the blocks; `house_state_transition` records the successful transitions and their inputs. Together they answer "how often did we block vs succeed, and what inputs mattered."
- **Rate-bounded by construction** — house state transitions are naturally sparse (a handful per day); no per-tick risk.

**Trigger:** on every house-state transition emit in presence.py (mirrors the existing `house_state_log` write; add adjacent `log_memory_episode` call).

**Node:** `house`.
**Episode type:** `house_state_transition` (NEW — add to `MEMORY_EPISODE_TYPES`).
**Adjudication:** `observed`.
**attrs:** `{from_state, to_state, confidence, trigger, gate_inputs: {tracked_persons_count_trusted, all_tracked_persons_away, census_count, unidentified_count, excluded_persons_size, any_zone_occupied, blocking_zones}}`.
**source_ref:** `f"house_state:{transition_ts.isoformat()}"`.

**Knobs (rung 1):** `HOUSE_STATE_TRANSITION_WRITER_ENABLED = True`. No other knobs — edge-only, bounded by the transition frequency.

**Consumer graph:** episodes/narrative/compactor. Distillation ride existing/adjacent facts (no NEW topic needed — house-state distributions roll into general `notification_hygiene` and existing NM baselines).

**Acceptance:**

- **Verify:** each transition emit is mirrored 1:1 into memory_episodes with the gate-input snapshot.
- **Verify:** I-M — a synthetic day with 10 transitions emits exactly 10 rows.
- **Test:** `test_house_state_transition_writer.py` — round-trip fixture: transition emit → episode row → `episodes()` return → snapshot fields match.
- **Live:** post-deploy, next real transition writes a row within seconds.

### Drop verdicts (no debt)

#### zone_phantom — DROP

- **Purpose in the source audit:** to record "zone occupied at zone tier while house tier reads it away" (the F2 zone-tier vs house-tier divergence).
- **Why DROP:** two reasons converge. (1) `occupancy_phantom_retro` at ROOM node covers the underlying phantom class — a zone-tier phantom is a *symptom* of a room-tier phantom rolling up; the room-tier writer captures the CAUSE, and the compactor's per-room fact already rolls up to zones. Building a zone-tier writer duplicates the signal at a different aggregation. (2) The specific zone-vs-house-tier divergence that motivated it is being fixed by `ZONE-TIER-DIVERGE-1` (a hard gate on this cycle); once the tiers reconcile, "zone occupied while house sees it away" becomes structurally impossible, and the writer's own class of events disappears. Building a writer for a class we're actively eliminating is anti-parsimony.
- **No debt filed** — if a NEW zone-only phantom class ever surfaces (e.g. from a zone-tier bug the divergence fix doesn't cover), it becomes a fresh diagnosis question; the audit trail is `episodes(node="zone:<x>", pattern=<whatever we build then>)`. Not carrying a "we should build this someday" ticket.

#### exterior multi-source witnesses — DROP

- **Purpose in the source audit:** add UniFi Protect / native-AI timestamps to `exterior_track.hops` so the F2-vs-Protect first-witness latency question is answerable from memory rather than recorder.
- **Why DROP:** perimeter surface, entirely different cycle. Requires (a) UniFi Protect timestamp plumbing on `exterior_track_linker.py` (new subscription path or an integration bridge), (b) schema addition to hops, (c) migration story for existing exterior_track rows, (d) its own review scope. All orthogonal to path-α trust and the away-block observation class. Zero synergy with the four writers above; would balloon this cycle from Tier 2-DB into a two-headed cycle with no shared invariant.
- **No debt filed** — if the perimeter cycle that would own it materializes (a first-witness latency incident recurs and forensics justify permanent instrumentation), it gets its own card at that point, scoped to the perimeter surface where it belongs. Not carrying it here.

---

## Deliverables summary (rev-2)

| ID | Description | Files touched (planned) |
|---|---|---|
| D1 | Consumer enumeration table of `tracking_status` — filed as `docs/planning/AUDIT_tracking_status_consumers.md` (committed artifact per operator flip on choice #6) | none (research) |
| D2 | Path-α LOST dissolution: person_coordinator.py case-(a)/(b)/(c) split via companion-GPS-first ladder; add `TRACKING_STATUS_BLE_SILENT`; delete `_tracking_active_or_lost_away`; update presence.py denominators; verify camera_census + fan_veto + aggregation | `const.py`, `person_coordinator.py`, `domain_coordinators/presence.py`, `camera_census.py`, `aggregation.py`, `sensor.py`/`binary_sensor.py` |
| D3 | Rider: GUEST-FP-RESIDUALS-1 A1 diagnostic classifier cleanup | `domain_coordinators/presence.py` (~5 LoC) |
| D4 | `occupancy_phantom_retro` writer + registry + compactor rule | `const.py`, `coordinator.py` (fan-off edge listener), `memory_compactor.py` |
| D5 | `away_transition_blocked` writer + registry + new fact topic + compactor rule | `const.py`, `domain_coordinators/presence.py`, `memory_compactor.py` |
| D6 | `tracker_trust_excluded` writer + registry + new fact topic + compactor rule (**new rev-2**) | `const.py`, `domain_coordinators/presence.py` (edge diff at :5207), `memory_compactor.py` |
| D7 | `house_state_transition` writer + registry (**new rev-2**) | `const.py`, `domain_coordinators/presence.py` (adjacent to house_state_log emit), `memory_compactor.py` |

**Non-goals (explicit, unchanged from rev-1 plus rev-2 additions):**

- Does NOT fix the phantom-zone side of AWAY-BLOCK-1 (recs 1/2 on that card).
- Does NOT build `zone_phantom` (DROP, see verdict) or exterior multi-source witnesses (DROP, see verdict).
- Does NOT introduce memory-driven actuation (§6 architecture boundary; see §"Why occupancy flips are memory-ineligible").
- Does NOT rename `TRACKING_STATUS_ACTIVE` or add a `AWAY_NO_FIX` verb.
- Does NOT touch the sleep-only trust doctrine.
- Does NOT add exterior-path/transit signal to case-(a) adjudication (DROP, see rejected design input (a)).

---

## Tier-2-DB review framings (unchanged from rev-1)

- **Review A** — correctness + tracking_status decomposition correctness (case-(a) ladder totality, source-precedence, BLE_SILENT not regressing camera_census).
- **Review B** — cross-coordinator + no-flap + restart resilience (path-β byte-identical without helper; fan_veto correctness; no write-queue pressure beyond I-M).
- **Review C** — test authority via real per-site source mutation + memory-boundary audit (every load-bearing site red-drilled; the four writers verified against §"Memory intent & limits" and §"Why occupancy flips are memory-ineligible" boundary).

**Live D** — post-restart: case-(a) tracker reads ACTIVE with location=away; `all_tracked_persons_away` follows household state; all four writers emit expected shapes; `episodes()` returns; I-M steady-state row bounds hold over 24h.

**Post-restart README write-back** per CLAUDE.md (Validated `<date>` PASS/FAIL table replaces prospective bullets).

---

## Vibememo after builds (operator directive, rev-2)

After each build round in this cycle (initial build, each fix-up round, deploy), the orchestrator writes a vibememo entry capturing the WHY of the ship (per CLAUDE.md "vibememo = WHY, kanban = WHAT/WHERE/NEXT"). Specific entries expected:

- **Post-build:** the ladder decision (companion-GPS-first) + the rejected exterior-path rationale, so future sessions don't re-litigate.
- **Post-review:** which framing caught what; if any writer's I-M bound was challenged.
- **Post-deploy:** first organic case-(a) tracker in the wild + first `away_transition_blocked` episode (or absence over 24h — either is a story worth capturing).

---

## Sequencing

1. **GATED** on ZONE-TIER-DIVERGE-1 trace merged (same code region).
2. **GATED** on MEMORY-COMPACTOR-1 shipped (writers assume compactor exists).
3. Plan review (Tier-2 plan-review protocol: one adversarial pass).
4. Build dispatched to `ura-builder` in a worktree under `.claude/worktrees/`.
5. Three framing-disjoint reviews (A/B/C) + Live D per Tier 2-DB.
6. Vibememo entries per §"Vibememo after builds."
7. README write-back with Validated `<date>` table.

---

## Operator checkpoint (rev-1 — RESOLVED 2026-08-16)

All six design choices accepted (choice 3 amended: 3 writers built this cycle; other 3 candidates dispositioned in §"Scope B" — 1 BUILD (`house_state_transition`), 2 DROP (`zone_phantom`, exterior witnesses)). Two design inputs integrated (companion GPS = incorporated as case-(a) source 1; exterior-path evidence = rejected with justification). New §"Why occupancy flips are memory-ineligible" folded in. Vibememo directive folded in. **Next: plan review, then build.**
