# PLANNING: EGRESS-INTERIOR-COUNT-REINFORCE-1

**Status:** PLAN ONLY — do not build. Contingent on D1 probe outcome + operator scoping call.
**Card:** `docs/planning/kanban.data.yaml` id `EGRESS-INTERIOR-COUNT-REINFORCE-1` (pre-approved, gated).
**Thread:** presence. **Tier assessment:** Tier 2-DB (regression-prone standing policy: touches the census union — a shared primitive consumed by presence, guest gate, HVAC vacancy, perimeter alerts, arrival/departure notifications; #53/#22 territory called out in the card constraints).
**Related planning:** `PLANNING_exterior_guest_egress.md`, `AUDIT_census_identity_supersession_and_consumers.md` §3 G2/G3, memory `reference_egress_face_coverage_7pct_not_a_ceiling`.

---

## Institutional context verified

### Prior-art surfaces read
- **Interior count PRODUCER:** `custom_components/universal_room_automation/camera_census.py`
  - `PersonCensus._async_update_census_locked()` (~:1252) is the sole producer; emits `interior_count` = `house_result.total_persons` on `SIGNAL_CENSUS_UPDATED` (:1358–1381).
  - Union writer sites (raw + enhanced) at `:1855` and `_apply_enhanced_house_census`; both consume `_get_egress_face_ids_fresh(now)` per plan-review C-CRIT-1.
  - Watchdog discount (`_watchdog_stuck_cameras`, :1271) runs upstream of raw tally — any new reinforcement must land AFTER this so a stuck-camera discount is not defeated by an egress event.
- **Egress transition PRODUCER:** `custom_components/universal_room_automation/transit_validator.py`
  - `EgressDirectionTracker._resolve_direction()` (:1228) fires `hass.bus.async_fire("ura_person_egress_event", { direction, egress_camera, timestamp, person_id, confidence })` at :1284.
  - Direction ∈ {`entry`, `exit`, `ambiguous`}; **`person_id` is optional** (`None` when no fresh face within `FACE_MATCH_WINDOW_S`). The event **fires without identity** — confirmed. This is the load-bearing prerequisite for a face-independent scope.
  - Confidence: 0.9/0.8 for entry|exit (multi-platform / single); 0.4/0.3 for ambiguous. DB write and census-union register are gated `direction != "ambiguous"` already (:1332, :1316).
- **Identity-path reinforcement is ALREADY PLUMBED** (scope-1 side, shipped via EXTERIOR-GUEST-FACE-FASTFOLLOW-1 D1):
  - `PersonCensus.register_egress_face(name, ts)` (:2984) inserts into `_egress_face_ids` TTL dict; TTL `EGRESS_FACE_UNION_TTL_S`. `evict_egress_face` (:3029) removes on exit crossing.
  - Kill-switch: `switch.ura_name_people_at_doors` / `CONF_EGRESS_IDENTITY_ENABLED` (default True) via `_is_egress_identity_enabled` (:2964). Fresh-read per crossing.
  - Consumers: BOTH union writers via `_get_egress_face_ids_fresh`. So a `person_id`-carrying entry ALREADY reinforces the interior union today. **This card cannot re-build that path.**
- **Coverage reality (institutional gate):**
  - Memory `reference_egress_face_coverage_7pct_not_a_ceiling`: `person_id` populated on **0 of 6,883 egress rows all time**; face recognition currently DOWN house-wide; the ~7% figure was a probe bug on the wrong camera (front door instead of the true GARAGE + family-room path).
  - Card D0 note + operator correction: identity path is VIABLE in principle (Protect named face via Alarm Manager webhook on garage+family-room), but the gate ("D1 identity accurate") is NOT MET on live data today. Producer for this cycle's identity-based value is currently emitting nothing.
- **Consumers of `interior_count` (SIGNAL_CENSUS_UPDATED payload):**
  - `domain_coordinators/presence.py` — sole grepped file matching the payload keys under presence coordinator. Presence coordinator's `_census_count` gates house-state (`away` vs occupied) and the guest gate downstream.
  - `sensor.py` — `URAPersonsInHouseSensor` and siblings (4 subscribers to `ura_person_egress_event` at :4311/:4421/:4482/:4530; these are display/diagnostic, not trust decisions).
  - `AUDIT_census_identity_supersession_and_consumers.md` §3 (G2 = door-identity → guest gate; G3 = arrival/departure notify). Both currently ineligible for the same coverage reason.

### Reused vs new
- **REUSED (no new plumbing needed for the identity arm):** `register_egress_face` / `evict_egress_face` / `_get_egress_face_ids_fresh`, `EGRESS_FACE_UNION_TTL_S`, `SIGNAL_CENSUS_UPDATED`, `CONF_EGRESS_IDENTITY_ENABLED` kill switch, `ura_person_egress_event` bus.
- **NEW (face-independent arm — proposed only if D1 probe justifies AND operator approves rescope):** an "unknown-body reinforcement" bucket parallel to `_egress_face_ids` (call it `_egress_body_reinforcements: dict[stem, datetime]`), a TTL constant `EGRESS_BODY_REINFORCE_TTL_S`, a dedup key (camera stem, not identity), a confidence knob `CONF_EGRESS_BODY_REINFORCE_MIN_CONFIDENCE` (Number entity — this is a policy the operator legitimately tunes by observation, per Numbers-Get-Knobs rung 3), and a consumer hook in the SAME two union writer sites already used by the face path.
- **KEEP + DOCUMENT (supersession check pre-emptive):** none. Everything on the identity path stays live.

### Memory bodies pulled
- `reference_egress_face_coverage_7pct_not_a_ceiling` — 0 rows all-time; face DOWN; garage/family-room re-measurement required.
- `feedback_measure_before_build` — probe first for empirically-gated cycles (this one qualifies twice: producer rate + gap size).
- `feedback_marginal_benefit_pushback` — decompose benefit before elaborating; see §Marginal-benefit decomposition below.
- `feedback_coincidental_equality_masks_concept_split` — Bug Class #63; caution because "an entry crossing" and "a body newly present in the interior union" look coincidentally equal in the happy path but split under multi-camera bleed and re-entry within TTL.

---

## The load-bearing invariant (falsifiable, stated up front)

> **INV-COUNT-MONOTONE-REINFORCE:** For any interior census tick T, `interior_count(T)` computed WITH the reinforcement input is either equal to, or greater than by at most the number of DISTINCT identities/bodies whose entry crossings fired within `[T - TTL, T]` and are NOT already represented in the interior substrate at T. Under no legal-config combination may the reinforcement cause `interior_count` to exceed `max(interior_substrate_bodies, reinforced_bodies)` — i.e. it is a `max()` / union operation, never a `+`.

Falsifier: a repro where an interior body detected on interior cameras AND recognised on an egress crossing (identity or, in the face-independent arm, camera-stem match within the TTL) produces `interior_count = 2` for one person. That is the exact double-count class the card constraint calls out (Bug Class #53/#22).

Second invariant (arm-specific to face-independent scope):

> **INV-FI-STEM-DEDUP:** Two egress emits for the same physical crossing (Frigate + UniFi on the same door within `TRANSIT_DOUBLE_FIRE_DEDUP_SECONDS`) contribute AT MOST ONE reinforcement bucket entry. The transit-validator dedup at `_last_resolved` covers the emit but must be re-verified end-to-end at the census-consumer side, because the face-independent arm cannot dedup by `person_id` (the identity arm can).

---

## Producer / Consumer map

### Interior count PRODUCER (existing)
- `PersonCensus._async_update_census_locked` → `_calculate_house_census` (raw tally, watchdog-discounted) → optional `_apply_enhanced_house_census` (union with face_ids, ble_ids, `_get_egress_face_ids_fresh`) → emits `SIGNAL_CENSUS_UPDATED{interior_count, identified_count, unidentified_count, face_recognized_count, peak_held, peak_age_seconds, count_as_of, ...}`.
- **Dependency health today:** BLE OK; interior Frigate OK; **face recognition DOWN house-wide** (memory) — so `identified_count` under-reports and `_get_egress_face_ids_fresh` returns `∅` because `person_id` is never stamped upstream.

### Egress transition PRODUCER (existing)
- `EgressDirectionTracker._resolve_direction` fires `ura_person_egress_event` with direction + optional person_id.
- **Dependency health today:** direction resolution works (uses interior camera correlation, no face required). `person_id` resolution is dependent on Frigate face-recognition sensors within `FACE_MATCH_WINDOW_S` — currently 0-producing per memory.

### Consumers of `interior_count`
- Trust decisions: `PresenceCoordinator._census_count` → house state (`away`/occupied) → guest gate, arrival/departure logic.
- Display: `URAPersonsInHouseSensor` (and 3 siblings). Diagnostic; not a trust decision.
- Downstream (should-be-consuming, per audit): guest gate G2, arrival/departure G3 — not consuming today.

---

## D1 — Measure-before-build probe (REQUIRED, gates every deliverable)

This cycle fires two Measure-Before-Build triggers ("data whose freshness/accuracy is assumed"; "design would change if a divergence number were 10× worse") AND the empirical operator note on the card (`next: … measure how often egress crossings are NOT already reflected in the interior count`). Probe FIRST.

**Probe A — real production rate of the reinforcement input:**
- SSH the recorder DB / URA `entry_exit_events` DB (whichever holds egress log rows): over the last 14 days, count `ura_person_egress_event` emits by (direction, person_id IS NULL, camera_stem, confidence). Cross-check against the DB write gate (`direction != "ambiguous"` and the identity-write side).
- Report: rate/day of `direction="entry"` events overall; rate with `person_id` populated (identity arm); rate without (face-independent arm). Compare to the 0/6883 figure from the memory (verify it's still current post-suffix-fix and post-webhook-work — measure GARAGE + inside-garage cams + family-room Protect specifically, not the front door).

**Probe B — the gap this would fill:**
- For each `direction="entry"` emit in the window, join against the census snapshot table (5-min interval writes) at `[t, t + 5min]` and ask: did `interior_count` increment by ≥1 within that window? "Yes" = the interior substrate already caught it; reinforcement is redundant on that event. "No" = a real gap.
- Report: fraction of entry events with a matching interior-count uptick vs not. This is the LOAD-BEARING NUMBER for the marginal-benefit call. If the gap fraction is < ~10%, the cycle's value is single-digit and the marginal-benefit call is NO-BUILD (see §Marginal-benefit).

**Probe C — false-positive surface for the face-independent arm:**
- Count entry events where the interior substrate did NOT increment BUT the emit was for a person already present (re-entry within TTL: went to check the mail, came back). Without identity, the face-independent arm CANNOT distinguish this from a new body — it would inflate the count. This measures the false-positive base rate before any code exists.

**Probe D — coverage re-measurement (from memory correction):**
- Explicitly on GARAGE doorbell + inside-garage cam + family-room Protect (not front door). This settles whether the identity path is currently 0-producing due to face-being-down (temporary fault) or a real coverage ceiling. If face-being-down is the fault, park this card until face is restored — the identity arm is code-complete already.

**Probe deliverable:** one-shot read-only script (`docs/planning/PROBE_egress_interior_reinforce.md` + committed script under `scripts/probes/`). No runtime instrumentation. Cost estimate: ~30 minutes.

### D1 Acceptance Criteria
- **Verify:** probe outputs a numeric table (per-camera-stem entry rate, identity-populated fraction, gap fraction, re-entry FP rate) over ≥14 days of real recorder history.
- **Verify (discriminating):** the table can distinguish (a) face-down fault + high gap = park until face restored, (b) face-covered + low gap = NO BUILD, both arms redundant, (c) face-covered + high gap = build IDENTITY arm only (already plumbed — verify live), (d) face-permanently-thin + high gap + low re-entry FP = operator call on the face-independent arm.
- **Live:** N/A — probe is offline against recorder.

---

## Deliverables (contingent on D1 outcome)

### Path (c): identity-arm live-validation (NO CODE — verify existing path)
Nothing to build. Confirm `register_egress_face` fires end-to-end on live data once face is restored; audit that union writers actually pick it up; add the missing consumers (guest gate G2, arrival/departure G3) as their own cards, not this one.

### Path (d): D2 — face-independent count reinforcement (ONLY if D1 justifies + operator approves rescope)

**Non-goals (mandatory):**
- NOT an identity producer. Never stamps `person_id`.
- NOT a new census producer. Extends `PersonCensus` union writers only.
- NOT a substitute for face recognition being restored.
- NOT wired to the guest gate directly — guest gate reads `identified_count` / `unidentified_count`, not the reinforcement bucket. A face-independent reinforcement contributes to `unidentified_count` only (a body known to have crossed but not identified). Any guest-gate consumption is a SEPARATE card.

**Shape (sketch — full spec deferred until probe unblocks):**
- New TTL bucket on `PersonCensus`: `_egress_body_reinforcements: dict[str, datetime]` keyed by `camera_stem` (NOT identity). Purpose: represents "a body crossed IN here recently and may not be on interior cameras yet."
- Populated in `EgressDirectionTracker._resolve_direction` alongside `register_egress_face`, gated `direction == "entry"` AND `confidence >= CONF_EGRESS_BODY_REINFORCE_MIN_CONFIDENCE` AND `person_id is None` (do NOT double-fire with the identity arm; identity path already reinforces via `_egress_face_ids`).
- Evicted on `direction == "exit"` for the same stem (parallel to `evict_egress_face`).
- Consumed at the SAME TWO union writer sites (raw + enhanced) — computes `max(interior_body_count, interior_body_count + len(fresh_reinforcements) - overlap_with_interior_within_stem_adjacency)`.
- Dedup against interior substrate: for each fresh reinforcement, if the interior cameras adjacent to that egress stem show a body within the reinforcement window, DO NOT add — the substrate already caught it. This is the INV-COUNT-MONOTONE-REINFORCE `max()` semantics, not `+`.
- Fail-open on any exception (byte-identical to today).

**Knobs (Numbers-Get-Knobs ladder):**
- `EGRESS_BODY_REINFORCE_TTL_S` — **module constant** (`const.py`). Protocol window; changing it should require review. Suggested seed: 120 s (short enough that a body missing from interior cameras that long is a real anomaly, not a lag).
- `CONF_EGRESS_BODY_REINFORCE_MIN_CONFIDENCE` — **Number entity** (`number.py`). Operator-tunable policy — floor is 0.8 (single-platform entry), operator may want 0.9 (multi-platform only). Persisted via existing Number-persistence machinery.
- `CONF_EGRESS_BODY_REINFORCE_ENABLED` — **Switch entity** (`switch.py`). Kill-switch, default OFF at ship (opt-in given the FP surface); mirror pattern of `switch.ura_name_people_at_doors`.

**Acceptance criteria (discriminating):**
- **Verify:** with reinforcement OFF, `interior_count` is byte-identical to pre-cycle (mutation drill on the switch confirms this).
- **Verify (discriminating between fix and new FP):** synthesised event stream — (i) entry crossing followed within 30 s by an interior camera body-detection at the adjacent room ⇒ NO uptick (substrate caught it, `max()` holds). (ii) entry crossing with NO interior body-detection for 120 s ⇒ `unidentified_count` uptick by exactly 1 for the TTL, then decays. (iii) Two Frigate+UniFi emits for the same door within 5 s ⇒ ONE reinforcement, not two (INV-FI-STEM-DEDUP). (iv) Entry crossing followed by exit crossing on the same door within TTL ⇒ NET zero (evict on exit).
- **Sensor:** `sensor.ura_persons_in_house` attribute `egress_reinforced_count` (new diagnostic attribute, not a new entity) shows the current live count from `_egress_body_reinforcements` — for observability.
- **Test:** unit tests in `quality/tests/test_camera_census.py` covering the four discriminating scenarios above, plus a source-mutation anchor test (Tier 2-DB Review C authority): neutering the reinforcement fuse in the enhanced writer must cause a SPECIFIC test to fail.
- **Live:** post-restart, verify a real entry event on the garage doorbell with the switch ON produces a `_egress_body_reinforcements` entry AND — critically — that a SECOND entry within TTL for the same stem does NOT double-reinforce; the DB `entry_exit_events` row for the crossing continues to be written as today. Discriminates fix vs new-FP.

**Tier 2-DB review framings (if built):**
- A — data integrity + union-write correctness at the two writer sites; `max()` semantics not `+`; watchdog discount not defeated.
- B — signal chain integrity + no-flap: dispatch-payload shape unchanged (`interior_count` numeric), consumers (presence coord `_census_count`, guest gate) see monotone changes only within the invariant; restart behavior of the TTL dict (must be transient, no RestoreEntity — a stale reinforcement across restart would be a phantom body).
- C — new surfaces + test fixture authority: Switch + Number round-trip through options + persistence; source-mutation drill on the fuse.

---

## Marginal-benefit decomposition (pushback, per standing rule)

- **Simplest version:** identity arm, already plumbed. If D1 shows the face path is currently 0-producing due to a transient fault (face down), the correct action is to fix face recognition, not to build a face-independent bypass. That captures the entire benefit at zero incremental risk.
- **Marginal ingredient risk of the face-independent arm (path d):** introduces a new TTL bucket that mutates the census union without an identity dedup key — the exact concept-split hazard (Bug Class #63) where "crossed" and "present" look equal in the happy path and diverge under re-entry, multi-camera bleed, and the substrate-already-caught case. Failure mode is either silent double-count (guest-gate flips) or silent under-count (away-mode retreats HVAC on an occupied house). Both are cost-and-safety adjacent.
- **Marginal benefit of the face-independent arm:** proportional to Probe B's gap fraction × real entry rate × downstream-consumer readiness (currently: no consumer trusts `unidentified_count` uptick specifically from a crossing). Card explicitly warns: *"IF cycle 3 rescopes to face-independent, revisit whether it's worth it. Otherwise stays parked."*
- **Recommendation:** default to path (c) (identity arm live-validation only). Only proceed to path (d) if D1 shows: (i) face recognition cannot be restored in a reasonable horizon, AND (ii) gap fraction ≥ 20%, AND (iii) re-entry FP base rate ≤ 5%. Park otherwise with the numeric trigger recorded for revisit.

---

## Summary — reporting fields

- **Path (absolute):** `/Users/okosisi/Code/universal-room-automation/docs/planning/PLANNING_egress_interior_count_reinforce.md`
- **Shape:** D1 measure-before-build probe (offline, ~30 min); then a triage into path (c) verify-only or path (d) new face-independent bucket. Path (d) is a single-deliverable Tier 2-DB cycle that adds one TTL dict on `PersonCensus`, one populator in `_resolve_direction`, one evictor, one consumer hook mirrored at the two existing union writer sites, one Switch, one Number, one module constant, and one diagnostic attribute — reusing the exact plumbing pattern of the existing `_egress_face_ids` identity path.
- **Load-bearing invariant:** INV-COUNT-MONOTONE-REINFORCE — reinforcement is a `max()` / union on interior bodies, never a `+`. Secondary: INV-FI-STEM-DEDUP for the face-independent arm.
- **Tier:** Tier 2-DB (regression-prone: shared primitive consumed by presence, guest gate, HVAC vacancy; identity/dedup concept-split hazard).
- **Measure-first probe required:** YES — D1 is the gate on the whole cycle and on the choice between paths (c) and (d). Do not scope D2 until D1 reports.
