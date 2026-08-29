# Universal Room Automation — Roadmap v12

**Version:** 12.0 (DRAFT)
**Current Production:** v5.91.x (patch cadence; MINOR reserved for genuinely new capabilities; MAJOR 6.0.0 gated on IDENTITY-DRIVEN AUTONOMY)
**Last Updated:** 2026-08-28
**Supersedes:** ROADMAP_v11.md (April 2026, written at v3.22.0 — obsolete)
**Status:** DRAFT — pending operator review and closure of the v5→6 identity arc.

---

## Why a v12

ROADMAP_v11 was written at v3.22.0 and named Bayesian Predictive Intelligence
(v4.0.0) as "Next." Reality overran that plan by roughly two majors and dozens
of shipped cycles. v4.0 came and went (Bayesian B1/B2 landed as v4.0.2, then
absorbed into forecasting), v4.7.x shipped the Guest / Weather / Appliance
axis in fragments under other names, v5.x has been the whole-house
optimizer + arbitrage + inclement + census/identity arc, and we now ship
under a codified cadence (PATCH default; MINOR only for a genuinely new
capability; MAJOR 6.0.0 anchored to IDENTITY-DRIVEN AUTONOMY).

The roadmap must now reflect *what actually shipped*, *what remains
worthwhile*, and *what the next MAJOR is anchored to* — not a re-litigation
of the v4.0 Bayesian frame.

---

## Version anchor correction

- **Live:** v5.91.x. PATCH is the default per-cycle bump (`5.91.1`,
  `5.91.2`, …). MINOR (`5.MINOR.0`) is reserved for a NEW user-facing
  capability. MAJOR = **6.0.0 = IDENTITY-DRIVEN AUTONOMY** (see arc below).
- **Do NOT roll 6.0.0 mechanically to dodge 5.100.** 5.90.x holds dozens
  more patch ships; MINOR bumps ride real capability additions.
- v11's "Next: v4.0.0 Bayesian" is HISTORICAL.

---

## What survives from v11 — Ledger

The 2026-08-18 undone-worthwhile audit
(`docs/planning/AUDIT_roadmap_undone_worthwhile.md`) already classified
v11's forward items. Summary (verify against that doc before scoping):

**Shipped under other names:**
- Grid arbitrage hardening → v5.5.x (reserve floor, inclement, guard exposure).
- Guest Mode Actuation Phase 1 (HVAC preset overrides) → v5.16.0.
- Weather / inclement fusion → v5.5.0.
- Optimization Coordinator → its own campaign (v5.0.0+).
- Bayesian B1/B2 → v4.0.2 (absorbed into forecasting; capstone no longer
  the north star).
- HVAC Zone Intelligence hardening → ongoing v5.x.

**Worthwhile-undone (carded, still valid):**
- `SENSOR-HEALTH-SURFACING-1` — chattering + stuck-on detection
  (medium; preventative). Adjacent: `CHATTER-*` cards; unify.
- `APPLIANCE-COST-DEFERRAL-1` — LG ThinQ + Rainbird start-deferral/skip.
- `UNLOAD-SYMMETRY-TASK-HYGIENE-1` — setup/unload symmetry + tracked
  background tasks (tech-debt hardening).
- `CONFIG-SUBENTRIES-MIGRATION-1` (parked; HA subentries still young).
- `ENTITYDESC-RUNTIMEDATA-HYGIENE-1` (parked; do during next major refactor).

**Permanently cut (from v11, still cut):**
- Circadian lighting.
- Per-person temperature preferences (HVAC-zone geometry makes it moot).
- Portable device control.
- v4.5.0 Visual 2D mapping — LOW; still deferred, no user pull.

**Removed as no-longer-relevant:**
- v11's stats block (v3.19.1, 1243 tests, ~54,600 LOC) — replaced by a
  short "current state" pointer below; no longer worth maintaining a
  frozen snapshot in the roadmap.
- v11's "v4.7.x SLOT CONTENTION" queue — every slot has been resolved
  (see AUDIT ledger).

---

## The v5 → v6 arc: IDENTITY-DRIVEN AUTONOMY

This is the north star and the reason `6.0.0` is not a mechanical bump.
The census / identity arc has spent 2026 building the *substrate* for
identity-keyed autonomous behavior: interior person tracking (BLE/GPS/WiFi
device trackers), camera census fusion (Frigate + UniFi Protect), face
recognition (Frigate names + operator-enrolled Protect Known Faces),
guest gate, egress event logging, hierarchical memory.

**The 6.0.0 gate is real actuation keyed to `person_id` at egress,**
not just interior BLE:
1. **Egress identity producer** (currently blocked): `person_id` is 0/7010
   rows all-time on `person_entry_exit_events` because
   `_resolve_egress_face_identity` requires a same-camera-stem face in a
   60s window, and door/garage geometry rarely produces named faces on
   the crossing camera. Fix: interior-fusion (adjacent-camera named face)
   + asymmetric signed-lag window (exit `[-30s,+180s]`, entry
   `[-300s,+60s]`) + ambiguity abstain. Producer card
   `EGRESS-IDENTITY-JOIN-GAP-1` (see build scope). Plan:
   `docs/planning/PLANNING_egress_identity_producer.md`.
   Achievable attach rate at re-tuned face-rec: ~63–66%, capped by
   ~28% multi-name ambiguity (tie-break/ABSTAIN load-bearing).
2. **Consumer wiring** (gated on producer above; do NOT re-scope until
   attach rate is measured >~30% sustained):
   - `PERIMETER-ALERT-NAME-PERSON-1` — perimeter alerts name the person.
   - `GUEST-GATE-DOOR-IDENTITY-1` — guest gate consumes door identity.
   - `ARRIVAL-DEPARTURE-NOTIFY-1` — "Oji arrived / left" notifications.
   - `CENSUS-FACE-RESOLVER-MIGRATE-1` — census reads across
     Frigate+Protect legs.
   - `GUEST-COUNT-DEDUP-MIGRATE-1` — union-cardinality dedup at
     door-identity path.
   - `SECURITY-CENSUS-UNKNOWN-WIRE-1` — auto-lock consumes unknown-count.
   - `UNEXPECTED-PERSON-IS-ON-DEDUP-MIGRATE-1` — alert path dedupes on
     resolved identity.
   - `EGRESS-INTERIOR-COUNT-REINFORCE-1` — interior count reinforced by
     egress-identity flow.
3. **Face-rec substrate work** (operator-side + URA-side):
   - Enroll Jaya, Ezinne as Protect Known Faces (operator).
   - Merge recurring unnamed clusters (operator).
   - Fix the empty Alarm-Manager webhook OR replace with Protect-API
     polling bridge to produce a named Protect entity (URA-side
     `KP-ANNOTATION-1` follow-through; extend
     `_resolve_face_entity_id` at `camera_census.py:2615` to fuse
     Protect + Frigate).
4. **6.0.0 ship criterion:** sustained attach rate ≥ target (operator
   sets — recommended ≥30% over a full day) AND at least two consumer
   cards live (perimeter naming + arrival/departure) AND face-rec
   subsystem confirmed healthy (post the 2026-08-21 house-wide fault).

**Corollary:** anything the operator wants that DOES NOT need
identity-keyed actuation should keep shipping under 5.9x.x /
5.MINOR.0 without waiting on the arc.

---

## The unshipped operator vision: room-to-room AGENTIC layer

Named by the operator, called out in `ROADMAP-STALE-AGENTIC-LAYER-1`:
rooms communicate + form agentic workflows on top of the now-shipped
hierarchical-memory foundation. VISION_v7 gestures at a
"TransitionCoordinator" for movement detection; nothing plans the
agentic layer itself.

This is the next MINOR-capability candidate AFTER 6.0.0 lands (or a
parallel track if the operator elevates it). Concretely, it needs:

- A capability doc: what a "room" says to a neighbor, what state
  transitions are transactional, what conflict resolution looks like
  across neighbors (extends the existing ConflictResolver primitive).
- Composition with hierarchical memory: memory writers already coalesce
  episodes per room; the agentic layer would let one room's episode
  update a neighbor's belief (e.g. "kitchen went quiet, likely dinner
  ended" → dining-area preset).
- A gate on identity: agentic behavior across rooms is much cheaper
  when actors are named (the 6.0.0 producer), so pragmatically this
  wants to come AFTER identity is real.

**Action:** operator input required (constraint from
`ROADMAP-STALE-AGENTIC-LAYER-1`) — this doc names it as the next major
capability track but does not spec it unilaterally.

---

## v5.9x.x forward queue (PATCH default; some MINOR candidates)

Ordered by leverage, dependency, and operator pull. Cards live on the
kanban; this is the trajectory, not a re-derivation.

### PATCH / near-term hardening
- **Notification hygiene** — new tonight, `OPTIMIZER-NOTIFY-FLOOD-DEDUP-1`
  (per-finding dedup/cooldown on optimizer notifications after
  operator observed 8+ identical comfort alerts back-to-back).
- **Optimizer comfort false-positive** — new tonight,
  `OPTIMIZER-COMFORT-HVAC-ZONE-MAPPING-FP-1`. The optimizer flags
  Study A + Study B + Master Bedroom sharing one thermostat zone as a
  comfort VIOLATION, but per memory `project_house_zones_vs_hvac_zones`
  one HVAC zone → multiple house rooms is BY DESIGN. Teach the check.
  (Operator to confirm the physical Master↔studyb_zone_1 mapping first.)
- **BlueBubbles self-echo** — reframed `NM-BB-CHATGUID-SELFSEND-1` on
  operator's real symptom: "a message to myself shows up twice." Needs
  diagnosis before fix.
- **EVSE split cycle** — amp modulation vs start/stop (two plans
  build-ready; oscillator as founding problem of the stop half).
  Continues per session pickup 2026-08-24.
- **HVAC governed-excursion tail** — 4-restore-failure residual carded
  after primary disposition.
- **AC-ramp Zone 3 no-benefit** and related knobs.
- **Chatter detector** — rate-vs-burst gap (`CHATTER-RATE-VS-BURST-GAP-1`)
  is the actionable follow-up to `SENSOR-HEALTH-SURFACING-1`.

### MINOR candidates (each a genuinely new capability)
- **Appliance cost-deferral** (`APPLIANCE-COST-DEFERRAL-1`) — LG ThinQ
  + Rainbird deferral. New coordinator surface → MINOR when it lands.
- **Sensor health surfacing** (`SENSOR-HEALTH-SURFACING-1`) — the
  chatter/stuck dashboard tile + NM hook, if scoped whole rather than
  patched. MINOR-capable.
- **Fusion library extraction** — the paper + OSS library
  (`docs/planning/PLANNING_paper_and_oss_fusion_library.md`), gated on
  the resolver being shipped + 2 weeks live + IP-posture decision. Not
  yet in-scope; when it ships, it is a MAJOR-in-spirit but rides as
  its own repo, not a URA MINOR.

### Tech-debt tracked but not scheduled
- `UNLOAD-SYMMETRY-TASK-HYGIENE-1`, `ENTITYDESC-RUNTIMEDATA-HYGIENE-1`,
  `CONFIG-SUBENTRIES-MIGRATION-1` — rides the next major refactor;
  do NOT do these as standalone cycles.
- `TEST-STRATEGY-REARCH-1` — inbox; keep as one-shot investigation
  before promoting to a cycle.

---

## v6.0.0 — IDENTITY-DRIVEN AUTONOMY (target: after producer + ≥2 consumers land)

**Ship criterion:** see the v5 → v6 arc §4 above.

**What v6.0.0 means to a user:** notifications name people ("Oji
arrived"), the guest gate stops arming when a known resident walks in
without their phone, and perimeter alerts distinguish "resident at the
door" from "unknown at the door." Everything else works as today.

**Non-goals for 6.0.0:**
- Full room-to-room agentic layer (separate track).
- Bayesian predictive intelligence (absorbed into forecasting;
  no more capstone framing).
- Visual 2D mapping (still deferred).
- Per-person temperature preferences (still cut).

---

## Critique of the old roadmap (what did NOT survive)

1. **The Bayesian capstone framing.** v11 named v4.0.0 as "the capstone
   feature." That framing is dead: Bayesian pieces landed as part of
   forecasting; the actual capstone is IDENTITY, not prediction.
   Prediction without identity has diminishing returns because the
   house acts on *aggregate* occupancy anyway — the leverage is naming
   who is in a room, not predicting that someone will be in it.
2. **The v4.7.x slot contention list.** Six items ordered
   warmest-first. Each shipped independently, on its own timeline,
   under a different version. Slot contention as a scheduling primitive
   didn't earn its keep — cards + tier classification did.
3. **The 30-50h Config Subentries migration as a v5.0 anchor.** HA
   subentries are still young; the migration risk is real and the
   pain it fixes is cosmetic. Correctly parked; do NOT elevate.
4. **The old "operational items" section.** Envoy gateway replacement,
   BlueBubbles webhook — either done or superseded (BB webhook
   registration IS done; the real BB issue is self-send, not
   registration; see `NM-BB-CHATGUID-SELFSEND-1`).
5. **Frozen stats.** A stats block in the roadmap goes stale in weeks;
   remove and point at CATALOG / live diagnostics instead.

---

## Recommended memory updates (for orchestrator to apply — I do not edit memory)

1. **Update / replace `feedback_versioning_convention`**: reinforce the
   2026-08-25 cadence — PATCH default, MINOR only for new user-facing
   capability, MAJOR 6.0.0 anchored to IDENTITY-DRIVEN AUTONOMY. Cite
   ROADMAP_v12 as the current durable record so future sessions do not
   re-derive.
2. **Update `project_session_pickup_2026_08_24`** (or fold it into a
   session-pickup successor) to reflect: EGRESS-IDENTITY-JOIN-GAP-1 is
   the canonical producer card (was split across two);
   BORROW-BANKING-LEASE-NOT-RELEASED-1 shipped v5.91.2; the three
   tonight-captures (notif flood, comfort FP, BB self-echo).
3. **Add a new pointer memory** `reference_roadmap_v12` (or update the
   existing roadmap pointer) — one line: "ROADMAP_v11 is HISTORICAL;
   docs/ROADMAP_v12.md is current. 6.0.0 = IDENTITY-DRIVEN AUTONOMY."
4. **Update `reference_egress_face_coverage_7pct_not_a_ceiling`**: the
   two 2026-08-27/08-28 findings on the join-gap card refine this
   further — attach rate ~63-66% is achievable via interior-fusion +
   asymmetric window; ambiguity ~28% is the real cap; face-rec was
   house-wide DOWN 08-21 to at-least-08-24, so the 7% ceiling reason
   was WRONG (it was a fault, not a coverage limit). Producer fix now
   has a plan (`PLANNING_egress_identity_producer.md`).
5. **Retire or supersede `project_advanced_energy_mgt_v47x`** — the
   forecaster wire-up is still queued but the framing is old; either
   fold into the current forecasting reality or mark HISTORICAL.

---

## Where the durable record lives now

- **Roadmap:** this doc (`docs/ROADMAP_v12.md`).
- **Undone-worthwhile ledger:** `docs/planning/AUDIT_roadmap_undone_worthwhile.md`.
- **6.0.0 producer plan:** `docs/planning/PLANNING_egress_identity_producer.md`.
- **Board state:** `docs/planning/kanban.data.yaml` (+ rendered views).
- **Vision:** VISION_v7.md is historical for the *foundation*;
  the room-to-room AGENTIC layer needs its own vision doc when the
  operator green-lights it.

---

**End ROADMAP_v12 (draft).**
