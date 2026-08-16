# PLANNING — Path-α LOST dissolution + memory writers for the new away logic

**Cycle IDs:** PATH-ALPHA-DENOM-1 (Scope A) + MEMORY-WRITERS-1 (Scope B; top-2 writers only). Rider: GUEST-FP-RESIDUALS-1 A1 (~5 LoC path-α diagnostic classifier).
**Tier:** 2-DB (operator-elevated de facto — trust-hierarchy ripple on tracking_status; every trust-tier consumer must be re-enumerated). Plan gets ONE adversarial plan review before build dispatch per Tier-2 plan-review protocol.
**Author:** ura-planner (Oji Udezue). **Date:** 2026-08-16.
**Depends on:** ZONE-TIER-DIVERGE-1 trace merged (same code region in presence.py); MEMORY-COMPACTOR-1 shipped (writers assume compactor exists so per-topic distillation rules can be registered day-1).
**Non-goal:** does NOT fix the phantom-zone / fan-loop side of AWAY-BLOCK-1 (that is rec 1/2 on that card). Fixes ONLY the path-α trusted-denominator vacuity that lets a phantom zone win — an independent mitigation.

---

## Falsifiable invariant (state up front — D-framing target)

> **I-α:** For any tick in which (a) every configured person tracker is in state `LOST` or `STALE`, AND (b) every configured person's `location` is one of `("away", "")` (i.e. no last-known indoor room), path-α's away-eligibility precondition (`all_tracked_persons_away == True` AND `tracked_persons_count_trusted > 0`) MUST evaluate True — not False-by-vacuity. Equivalently: an all-LOST/all-away household is away-eligible from the person-tracker signal alone, in ANY reachable configuration (any number of persons ≥ 1, any mix of LOST/STALE, any subset of never-had-a-fix persons).

Break the invariant → plan is falsified. D's job is to enumerate every reachable state (including single-person households, brand-new installs with zero fixes, phone-left-behind interacting with LOST, guest-mode arm/disarm boundaries, restart re-hydration) and produce a legal-config repro if I-α can be broken.

Secondary invariant on write-rate discipline (memory sprawl guard, §"Memory intent & limits"):

> **I-M:** In steady state (no incidents), the `away_transition_blocked` writer emits ≤ 1 row per calendar day per house; the `occupancy_phantom_retro` writer emits at most 1 row per (room, fan-release event). Neither writer is a per-tick logger, and neither couples to a detector gate whose failure would silence it (the retro writer's whole point is D2-independence).

---

## Institutional context verified

**Grep-verified prior art (REUSED vs NEW):**

- `TRACKING_STATUS_{ACTIVE,STALE,LOST}` — const.py:167-169. **REUSED** as the vocabulary being decomposed; NO new tracking-status constants added by this plan (see §"Design choice #1" for the naming argument).
- `_tracking_active_or_lost_away` (presence.py:169) + `_tracked_persons_count_trusted` (presence.py:1319) + `_all_tracked_persons_away` (presence.py:1320) + `excluded_persons` (presence.py:5097, 1325) — the WS-A1 v5.7.0 path-β machinery. **REUSED** as the model to follow for path-α; path-α gets a symmetric "counts-LOST-away-as-away" denominator. Simplifies (may deprecate) the path-β helper.
- `MEMORY_EPISODE_TYPES` frozenset (const.py:3642) — **REUSED as registry** for the two new episode types (`occupancy_phantom_retro`, `away_transition_blocked`); adding a member is a reviewed change, which IS the write-quality gate per architecture §4.
- `Database.log_memory_episode` (database.py:8355) — **REUSED** end-to-end. Carries: unregistered-type WARN gate, in-memory (node,type) dedup window (`MEMORY_EPISODE_DEDUP_WINDOW_S`), optional `dedup_source_ref`, write-queue integration. Both new writers use this and specify a `source_ref` for retro dedup.
- `MEMORY_FACT_TOPICS` (const.py:3660) — **REUSED**; new compactor rules key off two new topics (see §"Memory intent & limits").
- Path-α precondition (`all_tracked_persons_away`, presence.py:1048 + :4875) — **THE SITE BEING EDITED.** Verified end-to-end trace: dispatched via `should_veto_due_to_reliable_signals(scope="house_inference")` at :5966; consumed by house-tier away inference; feeds `attrs.all_tracked_persons_away` (:5441) and `_all_tracked_persons_away` on the PresenceHouseStateSensor (:5204).
- Camera census (camera_census.py:2296-2335) treats STALE+LOST both as "not-here" for census bookkeeping. **CONSUMER site — must be re-verified** during D1 that the new AWAY-vs-LOST distinction preserves the "not-here" reading (it should: away⇒AWAY still reads not-here).
- `fan_veto.py:222-234` — consumes `tracking_status == ACTIVE` as its trustworthiness signal (comfort-fan away-veto). **CONSUMER site — reviewed for regression** (fan-veto should NOT arm on a case-(a) "confidently away" tracker, but it doesn't need to — its call site is house_state ∈ {AWAY, VACATION}, so the classification loop is closed either way).
- `aggregation.py:5286-5566` — per-person sensor tracking_status attribute writer. **CONSUMER (display)**: values surface to dashboards; changing the vocabulary needs a UI story.
- `sensor.py`, `binary_sensor.py`, `person_coordinator.py:294-428` — tracking_status producers/consumers; enumerated in D1 (below).

**Prior planning docs consulted:**

- `docs/planning/AUDIT_away_transition_2026_08_13.md` (root of AWAY-BLOCK-1; §"(b) Root-cause chain" step 1 states the α gap this plan closes).
- `docs/planning/AUDIT_ble_house_level_weighing.md` (alternate BLE-vacancy conjunct shape — parked path 3 in this plan's alternates).
- `docs/planning/AUDIT_guest_fp_fixes_wiring.md` (source of the A1 rider: path-α diagnostic classifier still lumps LOST-away with excluded).
- `docs/planning/AUDIT_memory_retro_value.md` (source of the two memory writers picked — see §"Scope B" for why THESE two out of the six candidates).
- `docs/planning/AUDIT_zone_tier_divergence.md` (same code region; ZONE-TIER-DIVERGE-1 must land first — sequencing gate).
- `docs/planning/PLANNING_guest_fp_lost_away_and_outdoor_census.md` (v5.16.0 fixed the *veto* denominator; verified this plan does NOT overlap — v5.16.0 fixed the guest-FP path, not the away-eligibility path).
- `docs/planning/VISION_hierarchical_memory.md` + `docs/planning/ARCHITECTURE_hierarchical_memory.md` — memory intent/limits; read end-to-end for §"Memory intent & limits".

**Memory bodies pulled (full):**

- `project_zone_away_when_occupied_home_night_gap` — Zone 1 mmWave drops-still-body → D1 vacancy override retreats AC; adjacency confirmed (same "away signal fires through occupied room" family), but that memo's fix surface is D1 vacancy overrides, NOT tracking_status decomposition. NO REGRESSION VECTOR here — this plan strengthens the "trust away" side without touching sleep-only trust doctrine.
- `project_presence_guest_latch_and_veto_gap` (v5.16.0 SHIPPED) — the empty-denominator fix in the guest/veto path. The plan below applies the SAME shape (denominator can never empty by vacuity) to path-α. Verified live: v5.16.0 pattern uses relaxed denominator, exactly this plan's move for α.
- `project_guest_mode_false_positive_backlog` — "lost-but-away excluded from trusted → phantom unidentified → guest". This plan's Scope A directly retires the "excluded" half of that failure mode for case-(a) trackers. Fix A on that memo aligns with this plan; Fix B (outdoor zone exclusion) already shipped in v5.7.0 WS-A4.

**Design docs read:**

- `docs/Coordinator/PRESENCE.md` (skimmed for house_state inference contract; the invariant "path-α ignores zones entirely" is upheld — this plan does NOT introduce a zone-look inside α).

**Code locations surveyed end-to-end (during scoping):**

- `custom_components/universal_room_automation/domain_coordinators/presence.py` (paths α/β around :5029–:5210 read line-by-line; :4857–:4900 predicate helper).
- `custom_components/universal_room_automation/const.py` §tracking + §memory.
- `custom_components/universal_room_automation/database.py` `log_memory_episode` + `memory_episodes` DDL (:1533).
- `custom_components/universal_room_automation/memory_facade.py` and `memory_compactor.py` — signatures/topic gate; confirmed writers land in the existing pipeline without new tables.

---

## Memory intent & limits (sprawl guard — REQUIRED)

Restated from `VISION_hierarchical_memory.md` + `ARCHITECTURE_hierarchical_memory.md`:

1. **Five kinds of memory only** — episodic, baseline, outcome, identity, consolidated-facts. The two proposed writers in Scope B are **episodic** — no new kind, no new tier.
2. **Seven verbs, hard ceiling** — `baseline / unusual / episodes / outcome / narrative / profile / facts`. Vision §3 explicitly names verb-creep as a danger and rejected `similar` and `trend` as being expressible via existing verbs. **Neither writer earns a verb.** Consumers query them through `episodes(node="house", pattern="away_transition_blocked", ...)` and `episodes(node="room:<x>", pattern="occupancy_phantom_retro", ...)`. Zero new interface surface.
3. **§8 access policy + memory-ineligible decisions — NEVER cross.** Enumerated in architecture §8: safety actions, security arm/disarm, occupancy creation/release, reserve-floor/clamp invariants NEVER take memory as input. **This plan preserves that boundary absolutely:**
   - The `away_transition_blocked` writer OBSERVES an away-inference tick and records why it was vetoed. It does NOT feed back into away inference. Zero actuation path.
   - The `occupancy_phantom_retro` writer OBSERVES a fan-release-correlated mmWave drop and records "that was likely phantom." It does NOT flip occupancy, does NOT demote in real time, does NOT influence D2 or path-β's β-indoor guard. (If we ever wanted to gate β on this signal it would be a NEW Tier-3 cycle with the trust-change review it deserves — explicitly OUT of this plan.)
4. **No LLM, no ML** — both writers are pure rule-based emissions on live signals. Distillation into facts is deferred to the shipped compactor's registered rules (topics `phantom_recurrence`, `away_transition_blocked` — the latter is NEW, added to `MEMORY_FACT_TOPICS`).
5. **No memory-driven actuation in phase 1** — upheld: both writers are read-only for URA runtime; only NM / diagnostics / dashboard / operator queries consume them.
6. **Episodes = NOTABLE events, not samples** — enforced by design:
   - `away_transition_blocked`: emits ONCE per house-tier tick that meets a **new, sharp** trigger (path-α precondition failed AND path-β vetoed AND at least one previous minute already blocked — i.e. it's a *held* block, not a routine tick). In-memory dedup at `MEMORY_EPISODE_DEDUP_WINDOW_S` (already 300s per database.py:8391) is the second gate; the writer's own coalesce logic (open on first blocked tick, close on unblock) makes it O(1 row per block-episode).
   - `occupancy_phantom_retro`: emits on the EDGE where mmWave releases within `PHANTOM_RETRO_RELEASE_WINDOW_S` after a fan-off, AND the fan-on→now duration was ≥ `PHANTOM_RETRO_MIN_HOLD_S`. Both knobs default to values that pass the AUDIT retro's 5-of-5 latch capture with zero false emits over a 24h dry-run probe (see D1 acceptance).
7. **Future applications from vision §5:** NM quieting via per-node baselines, decision-outcome loops, cross-node systemic-vs-local diagnosis, episodic recurrence recognition, explainability, the paper. **Both writers are within-limits contributions to (4) episodic recurrence and (5) explainability**: they make the two failure classes of 2026-08-13 first-class queryable objects rather than SQL-forensics questions.

**Boundary the writers MUST NOT cross (build gate):**

- Neither writer becomes a high-rate transition logger. **Invariant I-M** above is enforceable (D1 acceptance criterion + a fixture that fires the trigger 100× in a synthetic minute and asserts ≤ N rows, N = knob-derived).
- Neither writer is consumed by away inference, fan actuation, or any of the four memory-ineligible decision classes. Reviewer B in the Tier-2 review explicitly checks the consumer graph is empty.
- If either writer ever needs a new verb, that is the design signal to STOP and re-scope, not to add a verb.

**Argument: these two writers are within intent.** They are minimal episodic instrumentation of the two hardest recent incidents (AWAY-BLOCK-1 latches + house-block itself), keyed on signals that already exist, emitted through the shipped queue, gated by the shipped registry, distilled by the shipped compactor. Zero new tables, zero new verbs, zero new consumers, zero actuation. The one net new bit is that the away-inference tick learns to look at itself and file a report when it detects it is vetoing under case-(a) starvation — which is precisely the "narrative" verb's raw material.

---

## Scope A — LOST-state dissolution / decomposition

### D1 (FIRST DELIVERABLE) — Exhaustive consumer enumeration of `tracking_status`

**Why first:** the operator's direction — "do we need a lost state at all?" — cannot be answered without a full consumer inventory. Every read site is classified into ONE of three semantic buckets:

| Bucket | Meaning today | Post-decomposition target |
|---|---|---|
| **Identity-uncertain** ("we don't know who this person is right now") | LOST used as "no data" | `LOST` (rare — truly unknown; e.g. never-had-a-fix) |
| **Location-uncertain** ("we know who, we don't know where") | LOST used interchangeably | `BLE_SILENT` (home-but-BLE-silent, phone-on-charger) OR resolved via last-known → **`AWAY`** if last-known==away |
| **Data-stale** ("we know who, we know where, the fix is old") | STALE | `STALE` — kept, unchanged semantics |

**Deliverable output:** a table in the plan review artifact enumerating every grep hit for `tracking_status`, `TRACKING_STATUS_LOST`, `TRACKING_STATUS_STALE`, `TRACKING_STATUS_ACTIVE`, and the two helpers `_tracking_active` / `_tracking_active_or_lost_away`. Files known to touch (from grep, must be re-verified line-by-line in the review artifact):

- `custom_components/universal_room_automation/domain_coordinators/presence.py` — paths α/β denominator loops (:5081–:5210), reliable-signal dispatch (:5966), veto helper (:169-190).
- `custom_components/universal_room_automation/person_coordinator.py` — WRITER (:168, :228, :294, :314, :365, :385, :428): the state machine that assigns LOST/STALE/ACTIVE. **This is where the decomposition primarily lands.**
- `custom_components/universal_room_automation/aggregation.py:5286-5566` — per-person sensor state + icon + attrs (DISPLAY).
- `custom_components/universal_room_automation/camera_census.py:2296-2335` — census gate: STALE+LOST both read as "not-here."
- `custom_components/universal_room_automation/fan_veto.py:222-234` — comfort-fan house-away veto (checks `== ACTIVE`).
- `custom_components/universal_room_automation/sensor.py`, `binary_sensor.py`, `config_flow.py`, `__init__.py` — surface / options / bootstrap references.

**Acceptance:**

- **Verify:** the enumeration is exhaustive — a second-pass reviewer running the same greps finds zero new hits.
- **Verify:** every hit is classified into one of the three buckets, with a one-line justification per site.
- **Verify:** each site's behavior is stated for the post-decomposition vocabulary and marked BYTE-IDENTICAL or CHANGED (with intent).

### D2 — Design pick: decomposition path (1) with (2) as containment fallback

**Chosen path: (1) Dissolve LOST into honest states** — per the operator's direction "we should find a way to say AWAY not LOST."

Concretely, in `person_coordinator.py`:

- **Case (a)** — no recent Bermuda fix AND last-known `location ∈ ("away", "")` → assign `TRACKING_STATUS_ACTIVE` with `location="away"`. This is the "confidently away with no BLE fix" case: reading the last-known location is legitimate for the away direction because BLE loss + last-known-away is *consistent* evidence, not conflicting. Alternative would be a new `AWAY_NO_FIX` state — REJECTED as verb-creep at the enum level (adds a state read by every consumer; the correct behavior at every consumer is "treat as ACTIVE-away", so name it that).
- **Case (b)** — no recent Bermuda fix AND last-known `location` is a home room → assign **new** `TRACKING_STATUS_BLE_SILENT` (const addition; only ONE new enum value). Rationale: phone-on-charger genuinely IS ambiguous ("phone is here, person may not be"). Consumers must NOT count BLE_SILENT persons as "away" (they may be actively home, phone-left-behind path already covers phone-left-behind). Path-α denominator excludes BLE_SILENT the same way it excludes phone-left-behind today.
- **Case (c)** — no recent Bermuda fix AND no last-known location (fresh install, brand-new person) → `TRACKING_STATUS_LOST`. Truly unknown; consumers exclude from trusted denominator. This case is what LOST is FOR.

Net enum change: keep `ACTIVE / STALE / LOST`; **add exactly one** — `BLE_SILENT`. Vocabulary grows by one; the overloading is broken by *reassigning case-(a) from LOST to ACTIVE-away* (the semantic move), not by adding many enums.

**Ripple accounting:**

- Path-α denominator now naturally includes case-(a) persons (they read ACTIVE, `all_tracked_persons_away` is TRUE when all such persons have `location=away`). **Invariant I-α holds structurally.**
- `_tracking_active_or_lost_away` (v5.7.0 WS-A1) becomes REDUNDANT — the reason it exists is to admit LOST-away persons into path-β, which case (a) no longer needs. **DEPRECATE the helper** (delete after verifying path-β can lean on plain `_tracking_active`). Verified: this is what the operator direction implies ("path-β `_tracking_active_or_lost_away` — which becomes redundant/simplifiable").
- `camera_census.py` STALE+LOST bucketing — verify BLE_SILENT is added to the "not-here" bucket (BLE_SILENT means phone-may-be-alone; census should NOT count the person as present).
- `fan_veto.py` `== ACTIVE` — a case-(a) person now READS ACTIVE-away; fan_veto only fires in house_state ∈ {AWAY, VACATION}, so a person reading ACTIVE-away contributes to house-away detection upstream and fan_veto continues to work by construction. **No change.**
- `aggregation.py` display: BLE_SILENT gets a new icon (`ICON_TRACKING_BLE_SILENT` — likely `mdi:bluetooth-off` or `mdi:cellphone-off`; operator UI vote deferred to build); LOST icon narrows to "truly unknown" cases.
- Config flow / sensor definitions: `BLE_SILENT` becomes a valid attribute value; option validators (if any) must accept it — verified by D1 enumeration.

**Fallback path (kept as B in operator's alternates):** if D1 exposes a consumer whose migration to case-(a)⇒ACTIVE is unsafe (e.g. a downstream integration that treats ACTIVE as "phone actively pinging" for something OTHER than trust), fall back to **path (2)**: keep LOST wholesale, patch path-α to admit "all-LOST + all-entity-away" as away-eligible (a symmetric copy of the v5.7.0 WS-A1 denominator into path-α). This is a smaller surgical fix that preserves the vacuity bug's structural cause but closes the specific denominator-empty case. **Pre-committed decision rule:** if any D1 site's migration requires more than a one-line predicate change, escalate to operator; do not silently fall back.

**Acceptance criteria (Scope A design + implementation):**

- **Verify:** I-α holds for every legal-config repro D generates (single-person; multi-person; mixed BLE_SILENT+ACTIVE-away; fresh install with no fixes; post-restart re-hydration).
- **Verify:** `_tracking_active_or_lost_away` is deleted (or, if it's kept for one tick of migration safety, has a deprecation comment + removal cycle carded).
- **Sensor:** `sensor.ura_presence_coordinator_presence_house_state` attribute `all_tracked_persons_away` = True when the household matches case-(a)-only-with-away-locations, under a fixture that seeds all persons LOST-away and injects a house-tier tick.
- **Sensor:** per-person tracking_status attr shows `active` for case (a), `ble_silent` for case (b), `lost` for case (c), `stale` unchanged.
- **Test:** new `tests/test_path_alpha_lost_dissolution.py` — mutation-anchored (per Tier-2 protocol): drills that flip case-(a) assignment from ACTIVE-away back to LOST cause specific NAMED test failures (I-α anchor + denominator-inclusion anchor); drills that delete the BLE_SILENT bucket cause the phone-on-charger anchor to fail; a mutation that force-assigns case-(c) fresh-install to ACTIVE reddens the "unknown-does-not-vote-away" test. Every load-bearing site gets a per-site red drill; no green-on-mutation site ships.
- **Test:** the four consumer sites (person_coordinator writer, presence α/β, camera_census, aggregation display, fan_veto) get per-site behavior tests, not just source-grep anchors (per C-framing hollow-anchor discipline).
- **Live:** post-deploy, when trackers next enter case-(a) organically, `tracked_persons_count_trusted` reflects the persons and `all_tracked_persons_away` follows their locations. Cross-check against the recorder using the exact query shape from AUDIT_away_transition_2026_08_13.md.

### D3 — Rider: GUEST-FP-RESIDUALS-1 A1 (~5 LoC path-α diagnostic classifier)

Per the guest-FP audit, path-α's `excluded_persons` map still lumps case-(a) trackers under `tracking_status=lost` — the guest gate doesn't read this map (audit §"why nothing broke"), so it's diagnostic clarity only. After D2 lands, case-(a) trackers no longer take this path (they're ACTIVE, not excluded), so the residual disappears **naturally**. What remains: the message-formatting site at presence.py:~5758 (`p, reason for p, reason in sorted(self._excluded_persons.items())`) must not emit a stale "lost-away" reason. Verify + delete any dead branch.

**Estimate:** ~5 LoC after D2 lands; folded in as a rider because it lives in the same file and same function region.

**Acceptance:** the AUDIT_guest_fp_fixes_wiring.md A1 residual is closed; no `excluded_persons` reason string carries "lost" for a case-(a) tracker.

---

## Scope B — the two memory writers

Per operator direction, only the TOP TWO writers from `AUDIT_memory_retro_value.md`'s six-candidate list are in scope this cycle: **(1) fan-release-correlated retro phantom writer** and **(2) `away_transition_blocked` writer**. The remaining four (`tracker_trust_excluded`, `house_state_transition`, `zone_phantom`, exterior multi-source witnesses) stay on the MEMORY-WRITERS-1 card, unbuilt.

### D4 — `occupancy_phantom_retro` writer (D2-independent)

**Trigger:** on a room's mmWave `on→off` edge, if a fan-off event happened within `PHANTOM_RETRO_RELEASE_WINDOW_S` seconds AND the fan-on→now duration was ≥ `PHANTOM_RETRO_MIN_HOLD_S`, emit a retro phantom episode.

**Node:** `room:<room_id>` (episodic tier is per-room; matches existing `occupancy_phantom` writer's scope).
**Episode type:** `occupancy_phantom_retro` (NEW — add to `MEMORY_EPISODE_TYPES` in const.py).
**Adjudication:** `phantom`. **Adjudicated by:** `fan_release_correlation`.
**attrs:** `{fan_entity, fan_off_ts, mmwave_off_ts, release_delay_s, hold_s, room_capabilities: {has_pir, has_camera, has_ble}}`.
**source_ref:** `f"phantom_retro:{room_id}:{fan_off_ts.isoformat()}"` — enables `dedup_source_ref=True` so a boot-time replay of the same edge never double-writes.

**Knobs (Numbers Get Knobs — ladder rung 1: module constant, review-gated because these are corroboration-window discipline):**

- `PHANTOM_RETRO_RELEASE_WINDOW_S` — default 60s (per AUDIT retro: Screek release 37s, Hobeian release 22s and 36s, all ≤ 60s). Kill-switch semantic: 0 disables the writer.
- `PHANTOM_RETRO_MIN_HOLD_S` — default 300s (5min). Avoids emitting on a brief fan-tap → mmWave-blink coincidence.
- Rung 1 constants because these govern the correlation gate; entity-tuning would let organic drift silently poison the phantom_recurrence fact.

**Consumer graph:** ONLY `episodes()` / `narrative()` / compactor `phantom_recurrence` rule. Zero actuation. **Verified in D1's consumer enumeration.**

**Distillation:** compactor's existing `phantom_recurrence` topic gets a rule that includes retro-phantom rows in the per-room fact ("Living Room: N phantoms in 30d, M via fan-release, K via D2"), giving operator/NM a room-comparable signal for the six no-PIR rooms that D2 currently can't score.

**Acceptance:**

- **Verify:** all five 2026-08-13 latches (Living Room + Upstairs Guestroom ×2 + Jaya Bedroom ×2) would have emitted rows on a synthetic replay of that day's recorder timestamps. Fixture asserts row count = 5, adjudication = phantom, room_ids = {living_room, upstairs_guestroom, jaya_bedroom}.
- **Verify:** the writer does NOT emit for the two rooms whose sensor released MID-fan (Ziri, Study A — sensor off before fan off): those are not phantoms.
- **Verify:** I-M bound holds — synthetic minute with 100 spurious mmWave edges but no fan events produces 0 rows.
- **Test:** `test_occupancy_phantom_retro_writer.py` — five load-bearing anchors (one per latch fixture), each with a mutation drill (delete the writer call → each anchor reddens with a distinct named failure).
- **Live:** first fan-latch after deploy → row appears in `memory_episodes` within 60s of mmWave release; `episodes(node="room:living_room", pattern="occupancy_phantom_retro")` returns it via the facade.

### D5 — `away_transition_blocked` writer with gate-input snapshot

**Trigger:** on a house-tier inference tick, if BOTH path-α AND path-β were EVALUATED and BOTH returned "cannot fire" AND at least one prior evaluation in the last `AWAY_BLOCK_EPISODE_MIN_HOLD_S` seconds also blocked → coalesce into an OPEN episode (create at first sustained block, keep open, update `ended_at` on close). On the tick where either path becomes reachable OR the house transitions to `away`, close the episode.

**Node:** `house`.
**Episode type:** `away_transition_blocked` (NEW — add to `MEMORY_EPISODE_TYPES`).
**Adjudication:** `observed` (this is a diagnostic, not a verdict on causation).
**attrs snapshot at OPEN (immutable) + summary at CLOSE:**
- Snapshot (open): `{tracked_persons_count_trusted, all_tracked_persons_away, excluded_persons: {<name>: reason}, census_count, unidentified_count, veto_path: "alpha_starved"|"beta_indoor_blocked"|"both"; blocking_zones: [<zone_id>], blocking_provenance: {<zone_id>: <breakdown>}, fan_interference_rooms}`.
- CLOSE summary: `{duration_s, closed_by: "alpha_reachable"|"beta_indoor_cleared"|"away_transition"|"restart"}`.
**source_ref:** `f"away_block:{open_ts.isoformat()}"`.

**Knobs (Numbers Get Knobs — rung 1 module constants; operator legitimately might tune the "how long is a real block" threshold, so operator-tune-later is possible but rung-3 is deferred until evidence):**

- `AWAY_BLOCK_EPISODE_MIN_HOLD_S` — default 300s. A single-tick block (recovers immediately) does NOT open an episode; only *sustained* blocks are notable.
- `AWAY_BLOCK_EPISODE_MAX_OPEN_S` — default 6h. Force-close and re-open beyond that to bound row growth if a real block ever runs unbounded (I-M discipline).
- Kill-switch: `AWAY_BLOCK_EPISODE_WRITER_ENABLED = True` (rung 1 constant).

**Restart behavior:** on boot, the open-episode state is NOT persisted (in-memory). If a real block spans a restart, a NEW episode opens post-restart with `closed_by=restart` on the pre-restart phantom (best-effort — the pre-restart episode simply ends at the last-known tick via `ended_at` at write time; details in the writer contract).

**Consumer graph:** ONLY `episodes()` / `narrative()` / compactor. Zero actuation. NO feedback into away inference.

**Distillation:** compactor gets a NEW rule under a NEW fact topic `away_transition_blocked` (add to `MEMORY_FACT_TOPICS`). Rule: N+ blocks in 30d whose `blocking_zones` overlap → propose fact "House blocks on <zone> phantom-holding <N> times/30d." Directly instruments the new away logic from Scope A — so the operator can watch, without a recorder probe, whether Scope A eliminated the vacuity blocks and what shape the remaining blocks take (path-β indoor guard, phantom-zone driven).

**Acceptance:**

- **Verify:** a replay of the 2026-08-13 incident (14:29Z start of census-0, 15:51Z away transition) opens exactly ONE episode of duration 82 min with `veto_path="both"` (α starved AND β indoor-blocked) and `blocking_zones=["Entertainment"]`.
- **Verify:** I-M holds — a synthetic day with zero real blocks emits 0 rows; a day with 10 briefly-blocked ticks (each < MIN_HOLD_S) emits 0 rows.
- **Test:** `test_away_transition_blocked_writer.py` — three fixtures (α-only starved; β-only indoor-blocked; both). Mutation drill: delete the writer call → each fixture reddens with a distinct named failure. A separate mutation that OPENS an episode but never CLOSES it must redden the "duration is bounded" anchor.
- **Live:** post-Scope-A deploy, over 24h the writer emits ≤ 1 row (I-M steady-state bound); the very first path-β block that occurs on a real phantom zone shows up in `episodes(node="house", pattern="away_transition_blocked")`.

---

## Deliverables summary

| ID | Description | Files touched (planned) |
|---|---|---|
| D1 | Consumer enumeration table of `tracking_status` (proof-of-work artifact, filed alongside this plan) | none (research) |
| D2 | Path-α LOST dissolution: person_coordinator.py case-(a)/(b)/(c) split; add `TRACKING_STATUS_BLE_SILENT`; delete `_tracking_active_or_lost_away`; update presence.py denominators; verify camera_census + fan_veto + aggregation display | `const.py`, `person_coordinator.py`, `domain_coordinators/presence.py`, `camera_census.py`, `aggregation.py`, `sensor.py`/`binary_sensor.py` (attr surface) |
| D3 | Rider: GUEST-FP-RESIDUALS-1 A1 diagnostic classifier cleanup | `domain_coordinators/presence.py` (~5 LoC) |
| D4 | `occupancy_phantom_retro` writer + register episode type + compactor rule for `phantom_recurrence` | `const.py` (MEMORY_EPISODE_TYPES, knobs), `coordinator.py` (fan-off edge listener), `database.py` (no change — reuses `log_memory_episode`), `memory_compactor.py` (rule registration) |
| D5 | `away_transition_blocked` writer + register episode type + new fact topic + compactor rule | `const.py` (MEMORY_EPISODE_TYPES, MEMORY_FACT_TOPICS, knobs), `domain_coordinators/presence.py` (open/close hook in the inference tick), `memory_compactor.py` (rule registration) |

**Non-goals (explicit):**

- Does NOT fix the phantom-zone side of AWAY-BLOCK-1 (recs 1/2 on that card).
- Does NOT build the other four writers from AUDIT_memory_retro_value.md (they stay on MEMORY-WRITERS-1).
- Does NOT introduce memory-driven actuation (§6 architecture boundary).
- Does NOT rename `TRACKING_STATUS_ACTIVE` or add a `AWAY_NO_FIX` verb (rejected in D2 — verb-creep at enum level).
- Does NOT touch the sleep-only trust doctrine (`zone_away_when_occupied` memo) — that's a separate uncovered dimension.

---

## Tier-2-DB review framings

Per CLAUDE.md, three framing-disjoint reviews + live validation. Framings for THIS cycle (per the CLAUDE.md guidance to fit framings to the change — a trust-hierarchy strategy change, not a schema change):

- **Review A — correctness + tracking_status decomposition correctness.** Every consumer site classified in D1 behaves correctly under the new vocabulary; case-(a)/(b)/(c) assignment logic is total and terminates; BLE_SILENT does not silently regress camera_census's not-here bookkeeping.
- **Review B — cross-coordinator + no-flap + restart resilience.** Path-β behavior byte-identical when `_tracking_active_or_lost_away` is deleted (path-β now leans on plain `_tracking_active`); no denominator flap on restart before person_coordinator has any fixes yet; fan_veto's ACTIVE-only check remains correct under case-(a)-ACTIVE-away semantics; memory-writer additions do not add write-queue pressure beyond I-M bounds.
- **Review C — test authority via real per-site source mutation + memory-boundary audit.** Every load-bearing site (D2 case-split, D4 writer, D5 open/close) gets an individual source mutation that reddens a NAMED test; global monkeypatch is disallowed. Memory-writer files are inspected against the §"Memory intent & limits" boundary — reviewer confirms neither writer is consumed by any of the four memory-ineligible decision classes.

**Live Validation (Review D)** — post-restart, verify: (i) case-(a) tracker in recorder reads `active` with `location=away`, (ii) `all_tracked_persons_away` follows real household state, (iii) memory_episodes has the expected shape on any post-deploy fan latch or path-β block, (iv) `episodes()` returns the rows through the facade, (v) I-M steady-state row bounds hold over 24h.

**Post-restart README write-back** (per CLAUDE.md): replace the prospective Live bullets with a `Validated <date>` PASS/FAIL table.

---

## Sequencing

1. **GATED** on ZONE-TIER-DIVERGE-1 trace merged (same code region).
2. **GATED** on MEMORY-COMPACTOR-1 shipped (writers assume compactor exists).
3. Plan review (Tier-2 plan-review protocol: one adversarial pass, verifies consumer enumeration greps independently, verifies invariant I-α is falsifiable, verifies I-M is enforceable, verifies knobs are on the correct ladder rung, verifies non-goals are explicit).
4. Build dispatched to `ura-builder` in a worktree under `.claude/worktrees/`.
5. Three framing-disjoint reviews (A/B/C) + Live D per Tier 2-DB.
6. Operator checkpoint gate — **see below.**

---

## Operator checkpoint

**MANDATORY per operator: NO BUILD UNTIL OPERATOR RESPONDS.**

### Summary

This plan closes the path-α trusted-denominator vacuity gap identified in AWAY-BLOCK-1 (14:29–15:51Z on 2026-08-13, house held `home_day` for 82 min because *every* person tracker was excluded, emptying the denominator by vacuity, and the one fallback that tolerates untrustworthy trackers — path β — was blocked by a fan-latched phantom zone). Operator direction was to fix it structurally rather than patch the denominator arithmetic: **decompose the overloaded `tracking_status: LOST` into honest states** so a "confidently-away-no-BLE-fix" person is called AWAY (and counts in path-α), not LOST (and gets excluded). Simultaneously, add the top two memory writers from AUDIT_memory_retro_value.md — the D2-independent fan-release-correlated retro-phantom writer (would have captured all 5 latches across both incidents) and `away_transition_blocked` (which directly instruments the new away logic). Both writers are episodic-tier only, no new verbs, no actuation feedback, hard write-rate bounds. Rides the same cycle: GUEST-FP-RESIDUALS-1 A1 (~5 LoC) as a rider because it lives in the same function. Tier 2-DB (three framing-disjoint reviews + live), gated on ZONE-TIER-DIVERGE-1 trace + MEMORY-COMPACTOR-1 shipped, plan-review-first per plan-review discipline.

### Key design choices (decisions-with-alternatives)

1. **CHOSEN: dissolve LOST by *reassigning* case-(a) to `ACTIVE` with `location=away`, and add EXACTLY ONE new enum value `BLE_SILENT` for case-(b) phone-on-charger.** The overloading breaks by making the semantic move (a case-(a) tracker IS trustworthy-away), not by growing the vocabulary. **REJECTED:** adding `AWAY_NO_FIX` as a fourth enum (verb-creep at the state-machine level; every consumer would have to learn it, and the correct behavior everywhere is exactly "treat as ACTIVE-away"). **REJECTED:** the fallback path-2 minimal fix (keep LOST wholesale, patch path-α's denominator to admit all-LOST+all-entity-away as away-eligible) — preserves the vacuity's structural cause. **Flip: if the operator prefers the smaller, more surgical fix,** the cycle collapses to path-2 (still Tier-2, no new enum, no `_tracking_active_or_lost_away` deprecation) and Scope B is unchanged.

2. **CHOSEN: delete `_tracking_active_or_lost_away` (the v5.7.0 WS-A1 helper) as part of D2** — it becomes redundant because case-(a) trackers now read ACTIVE, so path-β no longer needs the relaxed predicate; it can lean on plain `_tracking_active`. **REJECTED:** keep the helper for one deprecation cycle. **Flip: if the operator wants the belt-and-suspenders keep-then-delete**, add a deprecation comment + a removal card for the following cycle, no other change to this plan.

3. **CHOSEN: build ONLY the top 2 memory writers this cycle (`occupancy_phantom_retro` + `away_transition_blocked`), park the other four** (`tracker_trust_excluded`, `house_state_transition`, `zone_phantom`, exterior multi-source witnesses). These two together instrument BOTH sides of the 2026-08-13 incident (the latch that caused the veto + the block itself), which is the cheapest artifact that pays for the retro-value gap. **REJECTED:** build all six (write-queue and cognitive-surface pressure without matching consumers today). **Flip: if the operator wants `tracker_trust_excluded` added,** it's a small addition (fires when a person enters/leaves LOST/STALE exclusion) that would double-instrument the same failure mode from a different angle — worth adding IF the operator wants a parallel observation channel for D2 correctness.

4. **CHOSEN: `occupancy_phantom_retro` writes at ROOM node, `away_transition_blocked` writes at HOUSE node; neither is consumed by any actuation path.** Boundary explicitly enforced by review-C's memory-ineligible-decision audit. **REJECTED:** letting path-β discount phantom-classed zones based on the retro-phantom fact (which is AWAY-BLOCK-1 rec 3, a Tier-2-DB trust-hierarchy change on its own). This plan preserves the memory-ineligible boundary strictly; feeding memory back into occupancy inference is a separate future cycle with its own trust-change review. **Flip: if the operator wants rec 3 folded in here,** it becomes Tier 3 (delicate cost/safety impact via HVAC ripple), not Tier 2-DB — and needs to state a new falsifiable invariant on top of I-α.

5. **CHOSEN: knobs at rung 1 (module constants) — `PHANTOM_RETRO_RELEASE_WINDOW_S`, `PHANTOM_RETRO_MIN_HOLD_S`, `AWAY_BLOCK_EPISODE_MIN_HOLD_S`, `AWAY_BLOCK_EPISODE_MAX_OPEN_S`, kill-switches `PHANTOM_RETRO_ENABLED` / `AWAY_BLOCK_EPISODE_WRITER_ENABLED`.** Rung 1 because these govern correlation-window discipline; operator-tuning without review would silently drift the write rate and poison compactor facts. **REJECTED:** rung 3 (Number entities) — too tunable; the whole point of I-M is that write rate is bounded by construction. **Flip: if the operator legitimately wants live tuning on `AWAY_BLOCK_EPISODE_MIN_HOLD_S`** (the one operator-facing threshold — "how long is a real block"), promote that one knob to rung 3; keep the phantom-retro correlation windows at rung 1.

6. **CHOSEN: sequence D1 (consumer enumeration) as the FIRST deliverable, before any code change.** The operator's structural direction ("do we need a lost state at all?") is unanswerable without the full consumer inventory; D1 is a proof-of-work artifact that the plan-reviewer and reviewer-A can both independently verify. **REJECTED:** starting with the person_coordinator writer edit ("obvious change") — historically that's how consumer sites get missed. **Flip: if the operator wants D1 output filed as a separate committed artifact** (`docs/planning/AUDIT_tracking_status_consumers.md`) before build dispatch — yes, easy to do; it becomes the acceptance fixture for reviewer-A.
