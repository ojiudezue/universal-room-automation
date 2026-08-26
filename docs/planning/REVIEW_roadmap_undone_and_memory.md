# REVIEW — Roadmap Undone-But-Worthwhile + Memory Corpus Critique

**Date:** 2026-08-26
**Author:** ura-planner (strategic review — NOT a build plan)
**Scope:** ROADMAP-UNDONE-REVIEW-1 + MEMORY-ROADMAP-1
**Sources read:** `docs/VISION_v7.md`, `docs/ROADMAP_v11.md`, `docs/planning/kanban.data.yaml`
(cards: MEMORY-ROADMAP-1, ROADMAP-UNDONE-REVIEW-1, EGRESS-IDENTITY-PRODUCER-EMITS-NOTHING-1,
EGRESS-IDENTITY-CONTROL-OBS-1, GUEST-GATE-DOOR-IDENTITY-1, ARRIVAL-DEPARTURE-NOTIFY-1),
memory index `MEMORY.md` (98 entries).

---

## 0. Headline: the roadmap is severely stale

- `ROADMAP_v11.md` header: "Current Production: v3.22.0 … Last Updated April 1, 2026 … Next: Bayesian v4.0.0".
- Live production: **v5.90.x** (per `CLAUDE.md` version cadence note and recent session handoff memos through v5.85.x / v5.79.x).
- Roadmap v11 predates: the entire v4.x arc (Guest Mode actuation, Dynamic Preset Mgmt, Weather Provider Manager, arbitrage hardening, Appliance Coordinator work), the v5.x arc (inclement weather hold, arbitrage guard expose, DB vacuum, census v2 hardening, identity arc, EVSE work, STEP chatter, FanPolicyOracle, echo-guard, energy consumption unification, PA lifetime, ac-ramp savings, primitive CATALOG, stuck-signal watchdog, NM recipients fix, presence GUEST latch, DP drain-precedence, EVSE split), and the entire commercialization / PWA / iOS blueprint arc.
- The header "Next: Bayesian v4.0.0" is **fiction** relative to what actually happened. Bayesian was quietly deferred; the project instead spent 30+ months of releases on energy, presence, HVAC preset composition, and identity/census — none of it Bayesian.
- **Recommendation:** the deliverable of a follow-on cycle is a fresh `ROADMAP_v12.md` written from *live* (v5.90.x) forward. This review is the input to that rewrite, not a replacement.

---

## 1. Undone-but-worthwhile from ROADMAP/VISION

Legend: **(a)** genuinely worthwhile + not done · **(b)** superseded/obsolete · **(c)** done, roadmap-not-updated (drift).

### From ROADMAP_v11 "Future Roadmap"

| Item | Category | Value if built | Tier | Board card? |
|---|---|---|---|---|
| **Bayesian Predictive Intelligence (v4.0.0)** — per-person occupancy posteriors, uncertainty quantification, pre-emptive actuation | **(a)** worthwhile but re-scope | HIGH — but its concrete deliverables (per-person prediction) are gated on identity producer being alive (see §2). B1/B2 (model core + prediction sensors) could ship *without* identity as house-level posteriors and would be genuinely new. B3 (pre-emptive actuation) is gated the same way as identity. | Tier 3 (shared primitive) | NO — needs a fresh card |
| **v4.3.0 Grid Arbitrage Hardening** (D1–D5) | **(c) done** | D1 reserve-level fix and much of D2/D3/D4 shipped through the v5.5.x arbitrage line (`v5.5.3` floor gap RESOLVED per memory; `v5.5.6` arbitrage guard expose SHIPPED). ROI sensor + threshold diag likely partial. | — | Closed via memory refs |
| **v4.5.0 Visual 2D Mapping** | **(b) superseded** | The PWA (`~/Code/ura-dashboard-pwa` v6.1 LIVE) replaced the "HA-panel visual mapping" premise. A floorplan overlay could still land in PWA, but as a PWA feature, not a URA-integration deliverable. | — | Move to PWA repo backlog |
| **Guest Mode Actuation Phase 1 (HVAC preset range overrides)** | **(c) largely done** | Guest latch shipped v5.16.0; Dynamic Preset Mgmt drain-target cycle shipped; override schema exists. Whether the *exact* per-zone `home` cap at 74°F under guest is wired needs a verification pass, not a plan. | — | Verify, then close |
| **Dynamic Preset Mgmt Cycle A** (WeatherProviderManager, ≥2 providers) | **(c) done partial** | `Advanced Energy Mgt Forecaster (partial)` memo confirms WeatherProviderManager shipped v4.7.0. LightGBM forecaster + BatteryStrategy wire-up NOT built. | Tier 2 for the wire-up | Existing memo — needs a card |
| **Dynamic Preset Mgmt Cycle B** (weather-driven preset overrides) | **(a) worthwhile** | If Cycle A is live and unused, Cycle B is the ROI. Depends on 6 operator config decisions per plan doc. | Tier 2 | NO — needs a card |
| **Appliance Coordinator v3** (LG ThinQ deferral + interrupt + Rainbird skip) | **(a) worthwhile if the physical devices are still targets** | Real seasonal energy savings. Needs an "is the operator still driving these devices?" reality check before build. | Tier 2-DB (per plan) | NO — needs a re-scoped card |
| **Sensor Health Surfacing** (chattering + stuck-on detection) | **(a) worthwhile** | Preventative — silent sensor rot poisons occupancy, sleep logic, energy attribution, Bayesian training. The Kitchen mmWave chattering example is the archetypal case. | Tier 2 | NO — needs a card |
| **Config Subentries Migration (v5.0)** | **(a) worthwhile eventually / (b) risk-first** | HA subentries are now ~1.5 years old and load-bearing across integrations. The 34-entry topology's real pain (orphan device residue, cross-entry validation, silent-save bugs) is chronic. But the **migration risk on a live install with months of accumulated options is real**. Do NOT prioritize until an inbound HA deprecation forces it. | Tier 3 | NO — parked-with-trigger |
| **AI Custom Automation (v3.4.0 / v3.10-v3.12)** | **(c) done** | Shipped v3.10–v3.12.1 per roadmap COMPLETED section. | — | — |

### From ROADMAP_v11 "Tech Debt & Hardening"

| Item | Category | Notes | Card? |
|---|---|---|---|
| **#1 Setup/unload symmetry** | **(a) worthwhile** — same bug class as v4.2.24 silent-save + v5.8.0 setup RecursionError. High leverage. | Tier 2 | NO — needs a card |
| **#2 Tracked background tasks** | **(a) worthwhile** — recurring bug class (memory: "wire-in anchors", "suppression needs a discharge", "untracked background tasks"). Small effort, high review-hygiene payoff. | Tier 2 | NO — needs a card |
| **#3 EntityDescription rollout** | **(b) low priority** — cosmetic. Do opportunistically when adding the next coordinator, not standalone. | — | Optional |
| **#4 `runtime_data` migration** | **(a) worthwhile long-term / (b) not urgent** — do during next major refactor. | — | Optional |
| **Load shedding UX doc + dashboard guidance** | **(a) worthwhile** — feature is fully implemented and disabled by default with zero operator-facing guidance. Real value blocked on a docs+dashboard-card cycle. | Tier 1 | NO — needs a card |
| **HVAC zone weight tuning guidance / auto-learn** | **(a) worthwhile-lite** — could auto-learn from sensor response times. | Tier 2 | NO — needs a card |
| **Energy observation mode UX** | **(a) low but easy** — small dashboard/help-text delta. | Tier 1 | NO — needs a card |
| **Roadmap doc cleanup** (v11 itself calls out obsolete v9 + old planning docs) | **(a) worthwhile — this review is step 1** | — | This doc |

### From VISION_v7 "Future Concepts" backlog

| Item | Category | Notes |
|---|---|---|
| **Guest Mode** | **(c) done** | Shipped through v3.15.1 auto guest → v5.16.0 GUEST latch → identity/census arc. Currently the *highest-activity area of the codebase*. |
| **Vacation Mode Detection** | **(a) worthwhile** | Never built as a discrete mode. The primitives exist (census, phone away, calendar). Small, high-value. | 
| **Time Period Profiles** | **(c) mostly done** | Sleep hours + house state (SLEEP / HOME_NIGHT / HOME_DAY) provide most of this. |
| **Weather Integration** | **(c) done** | WeatherProviderManager + inclement weather hold. |

### VISION document itself
The whole VISION_v7 doc is **anchored to v3.2.9 (January 2026)**. Its "Future Architecture" pseudocode is fine as *aspiration* but bears almost no resemblance to what shipped. **Recommend: mark VISION_v7 as archival and write a VISION_v8 alongside ROADMAP_v12.** The IDENTITY-DRIVEN AUTONOMY anchor (see §2) is the natural organizing principle.

---

## 2. The 6.0.0 gate: identity producer emits nothing

**Per `CLAUDE.md` version cadence:** *"MAJOR = 6.0.0 is anchored to a named milestone: IDENTITY-DRIVEN AUTONOMY (the census/identity arc reaching real actuation — guest gate consuming door-identity, arrival/departure keyed to person_id, egress identity), gated on face-recognition/coverage being restored."*

**The hard blocker, plainly:**

- **`person_id` has NEVER been populated.** 0 of 6,883 rows across 5.5 months (card `EGRESS-IDENTITY-PRODUCER-EMITS-NOTHING-1`, updated 2026-08-23).
- Every 6.0.0-anchor consumer is downstream of that column:
  - guest gate consuming door-identity → needs `person_id`
  - arrival/departure keyed to `person_id` → needs `person_id`
  - egress identity → needs `person_id`
- The 2026-08-23 Frigate 2 storage-outage postmortem *narrowed* the mechanism (faces DO exist on egress cameras — garage_a, doorbell_lite, front_door_aerial, etc.), so the failure is in **the JOIN (window/ordering), not availability**. That is the "cheap-fix branch" the card already names. It has not yet been executed.

**Reframing 6.0.0:**

The real gate on 6.0.0 is not "restore face recognition coverage" (which is now known to be present on egress cameras) — it is **fix the producer's join/window logic so `person_id` starts landing in the row**. Until at least one non-zero week of production `person_id` writes exists:

1. The eight identity-consumer cards remain blocked-on-producer, not on their own build.
2. Any Bayesian v4.0.0 person-specific work (B1/B2 posteriors *per person*) is blocked on the same producer.
3. Shipping 6.0.0 without producer health would be shipping the *promise*, not the *behavior* — a Bug Class #63 ("coincidental equality masks a concept split") in the making, where the version number claims a capability the runtime doesn't demonstrate.

**Recommendation:**

- **Do not roll 6.0.0 mechanically** to escape the growing `5.90.x` patch series. Hold it, per the CLAUDE.md standing rule.
- The **actual go-condition** is: *at least one full clean week where `SELECT COUNT(*) WHERE person_id IS NOT NULL` exceeds a per-day floor (e.g. ≥10 rows/day, or some fraction of daily crossings)*. That's a **measure-before-build gate**, exactly matching the CLAUDE.md "Measure Before You Build" rule.
- Sequence the identity arc as: **(1) fix producer join** (small, high-leverage, cheap probe first) → **(2) validate 2 weeks of live `person_id` writes** → **(3) unblock the 8 consumer cards in dependency order** → **(4) tag 6.0.0 when the guest gate, arrival/departure, and egress consumers are live and observed**.
- The producer fix is a **Tier 3** cycle: shared primitive, cost-and-safety adjacent (guest mode affects HVAC, security), historical multi-fix-up area (census/identity arc has had many).

---

## 3. Memory-roadmap critique (MEMORY-ROADMAP-1)

Corpus size: 98 entries in `MEMORY.md` (auto-memory index).

### What is load-bearing and durable

- **Feedback memos codifying process rules** (~30 entries): `no fabrication`, `measure before build`, `marginal benefit pushback`, `disjoint framings`, `falsify first`, `mutation pyc staleness`, `wire-in anchor`, `suppression needs a discharge`, `serialise suite runs`, `worktree isolation`, `hollow anchors`, `subagent protocol`, `context-wide scoping`, `verify claim types`, `extend existing`, `coincidental equality`, `soak exit`, `code tracing methodology`, `architecture map`, `read consumers first`, `cross-investigation synthesis`. **These are the corpus's real value.** Many are already lifted into CLAUDE.md. Keep in perpetuity; delete only on explicit retirement.
- **Reference facts that would silently poison work if forgotten** (~15 entries): `EC config surface`, `EC backout knob MAX_AGE_S=0`, `zone tonnage`, `battery SOC = Envoy not SPAN`, `house zones ≠ HVAC zones`, `Frigate 1 retired 2 suffix`, `Frigate ghost evidence chain`, `pooloverhead four integrations`, `HA logs journald`, `urakanban DNS`, `BLE device budget`, `single user no back-compat`, `Enphase coupling tier`. **Durable. Delete only when the underlying physical fact changes.**
- **Live/backlog project memos** (~15 entries): the shipwatch spinoff, dashboarding workstream, EV drain-precedence, forecast partial, load shedding foundations, jaya bedroom resolved, etc. **Durable while their projects are live**; convert to closed status when their work completes.
- **START-HERE entry**: the current session handoff memo, one at a time. Load-bearing for session pickup.

### What is stale or superseded

- **Session-pickup entries** (5 in the corpus): `2026-08-24` (current), `2026-08-20`, `2026-08-19`, `2026-08-05`, `2026-07-29`, `2026-07-20` — all but the newest one are marked `(superseded)` in the title itself. **They are already tombstoned by convention.** Their bodies still take up index space and, more importantly, human attention when scanning the corpus.
- **Shipwatch confirmed JSONs** (6 entries `shipwatch_confirmed_v*.json`): these are single-shot confirmation records. Useful as evidence for ~2 weeks after ship, then archival only. All are ≥1 month old now.
- **Duplicated project state**: some project memos (e.g. arbitrage floor gap RESOLVED, bathroom exhaust SHIPPED) hold information already captured in git tags + READMEs. Not harmful, but duplicate surface.

### What memory SHOULD capture going forward

- **Named lessons and physical-fact references** — the two categories that repeatedly earn their keep.
- **One live START-HERE session-pickup** — never more. New pickup replaces old; the old is deleted the same turn, not marked `(superseded)`.
- **Producer-health baselines** for load-bearing runtime values — a memo saying "as of DATE, `person_id` writes are 0/day" is durable evidence a future session can build on. When it changes to non-zero, the memo is updated, not duplicated.
- **Cycle post-mortems only when they surface a new bug class** — otherwise the git+README history is the record.
- **Do NOT capture:** shipwatch pass/fail JSONs (move to `~/Code/shipwatch/` history), routine cycle closures without a new lesson, duplicates of kanban card bodies.

### Recommended prune/consolidation pass

Yes — this is warranted. Concrete pass:

1. **Delete** all `(superseded)` session-pickup entries EXCEPT the newest (retain only `2026-08-24`). That's ~5 entries.
2. **Archive** the 6 `shipwatch_confirmed_v*.json` entries out of the URA memory dir — either move to `~/Code/shipwatch/history/` or delete outright since git carries the diff.
3. **Consolidate** the arbitrage/floor-gap and bathroom-exhaust "SHIPPED" memos into a single "closed cycles ledger" memo, or delete since git tags cover it.
4. **Refresh** the identity/egress memos into ONE current-state memo (they currently span "NO-GO" + "REFUTED-reason" + "producer emits nothing" + "control+observability shipped" — the operator has to reconstruct the current state by reading all four).
5. **Add** a "producer health baselines" memo for `person_id` and any other load-bearing runtime column, with a "last checked" date. This is the falsifiable oracle for §2's 6.0.0 gate.

Estimated corpus reduction: 98 → ~75 entries, with **no loss of load-bearing content** and a substantial gain in scan-ability.

---

## 4. Prioritized shortlist — top 5 undone-but-worthwhile, with recommended next step

Ranked by (leverage × unblocks-6.0.0 × cheapness).

### 1. **Identity producer join fix** — the actual 6.0.0 gate
- **Value:** unblocks EGRESS-IDENTITY, GUEST-GATE-DOOR-IDENTITY-1, ARRIVAL-DEPARTURE-NOTIFY-1, and the whole 6.0.0 arc. Without it, the identity investment of the last 6 months is inert.
- **Tier:** Tier 3 (shared primitive, cost-and-safety adjacent).
- **Cheapness:** cheap probe first (measure current join window, ordering, and near-miss rate on live recorder data — no build). Small delta likely.
- **Recommended next step:** **CARD** a Tier-3 measure-first cycle keyed off `EGRESS-IDENTITY-PRODUCER-EMITS-NOTHING-1`. Probe = D0. Fix = D1. Live validation = 2 weeks of `person_id` non-zero writes.

### 2. **Roadmap v12 + Vision v8 rewrite** — orient the whole project against live state
- **Value:** ROADMAP_v11 is 4 months + ~68 shipped versions out of date. Every planner reads a fiction. Every new operator loses hours.
- **Tier:** Tier 1 (docs).
- **Cheapness:** 1 focused session. This review + the memory-roadmap doc are the inputs.
- **Recommended next step:** **PLAN** — write `ROADMAP_v12.md` anchored at v5.90.x, organized around IDENTITY-DRIVEN AUTONOMY as the 6.0.0 arc, with the Bayesian roadmap re-scoped to house-level posteriors first, per-person second (behind identity).

### 3. **Sensor Health Surfacing** (chattering + stuck-on detection)
- **Value:** silent sensor rot poisons every downstream layer (occupancy, sleep protection, energy attribution, future Bayesian training). Preventative, house-wide.
- **Tier:** Tier 2.
- **Cheapness:** ~150–300 LoC + a DB table + a dashboard tile. Existing stuck-on detector (`coordinator.py:1158`) is the anchor to extend.
- **Recommended next step:** **CARD** with the deliverables from ROADMAP_v11 (D1–D6) intact — the plan is already scoped.

### 4. **Setup/unload symmetry + tracked background tasks** (tech debt #1 and #2, bundled)
- **Value:** same bug class as v4.2.24 silent-save and v5.8.0 setup RecursionError incidents. Ongoing exposure until fixed.
- **Tier:** Tier 2, potentially Tier 3 (touches setup paths and shared resources).
- **Cheapness:** medium — 1–2 focused cycles, but each site is small.
- **Recommended next step:** **CARD** as one hardening cycle (they share a lifecycle-hygiene framing).

### 5. **Dynamic Preset Mgmt Cycle B** (weather-driven preset overrides) — activate the shipped WeatherProviderManager
- **Value:** WeatherProviderManager already shipped (v4.7.0) and is under-used. Cycle B is the ROI cycle that consumes it. Real HVAC / cost impact on hot/cold days.
- **Tier:** Tier 2.
- **Cheapness:** low-medium — the override schema exists (Guest Mode Phase 1), the weather provider exists. Cycle B is glue + operator config decisions.
- **Recommended next step:** **CARD** with the 6 operator-config questions from the original plan doc as D0 (operator decisions), then D1 the override source, D2 sensors + button.

### Honorable mentions (not top-5, but worth carding)

- **Vacation Mode** (small, primitives exist, high user-visible value)
- **Load shedding UX docs + dashboard card** (feature is dark without it)
- **Memory corpus prune pass** (do alongside the roadmap rewrite — same session, same context)
- **Bayesian house-level posteriors (v4.0.0 B1/B2, identity-agnostic)** — landable independent of the identity gate; per-person B2 waits on §1

---

## 5. Explicit non-recommendations

- **Do NOT bump to 6.0.0** on schedule pressure. The `5.90.x` version optics are ugly; ship them anyway. 6.0.0 is a truth claim about identity actuation, not a serial number.
- **Do NOT plan v4.5.0 Visual Mapping** as a URA-integration deliverable. It belongs in the PWA repo if it's built at all.
- **Do NOT prioritize Config Subentries v5.0.** No inbound HA deprecation forces it; the migration risk on a live install is real; the pain it fixes (orphan devices, cross-entry validation) is chronic but cosmetic. Park with a trigger: revisit when HA deprecation-warns the current entry pattern.
- **Do NOT re-open the arbitrage floor gap or v5.5.x arbitrage line.** Memory explicitly closes it.

---

## Deliverables

- This document: `/Users/okosisi/Code/universal-room-automation/docs/planning/REVIEW_roadmap_undone_and_memory.md`
- Cross-references:
  - `/Users/okosisi/Code/universal-room-automation/docs/VISION_v7.md` (mark for archival in successor cycle)
  - `/Users/okosisi/Code/universal-room-automation/docs/ROADMAP_v11.md` (stale; input to v12 rewrite)
  - `/Users/okosisi/Code/universal-room-automation/docs/planning/kanban.data.yaml` — cards referenced: MEMORY-ROADMAP-1, ROADMAP-UNDONE-REVIEW-1, EGRESS-IDENTITY-PRODUCER-EMITS-NOTHING-1, EGRESS-IDENTITY-CONTROL-OBS-1, GUEST-GATE-DOOR-IDENTITY-1, ARRIVAL-DEPARTURE-NOTIFY-1

**Not built:** no new plans. Findings and recommendations only. Cards to create are named in §4.
