# PLANNING — Census Occupancy Estimator (HYBRID: held camera floor + deduped door tally) + `guests_present` flag

**Status:** REVISED 2026-10-04 to the operator-approved HYBRID design, following §8a D0 results and the operator rulings at the end of the previous revision. Not yet reviewed. No code is changed by this document.
**Author:** ura-planner, 2026-10-04 (hybrid revision).
**Trigger:** `AUDIT_census_subsystem_2026_10_04.md` (snapshot read 2–3 vs truth 10–12 on 10-03), `AUDIT_census_footage_ground_truth_2026_10_03.md` (per-slot visible counts from Frigate stills), and D0 (§8a of the prior revision) which **NO-GO'd the original flow-ceiling design** on this evidence. The operator ruling 2026-10-04 (round 4) is **GO on a hybrid design, tuned for 1–2 people, graceful degradation, with a main-entry-door config question**. See §13 for the full operator ruling trail.
**Canonical domain reference:** `docs/Coordinator/IDENTITY_FUSION_CAMERAS_MANUAL.md`. §11 lists the corrections this plan makes to it.
**Supersedes:** parked card `CENSUS-GUEST-FLOOR-1`; folds in `EGRESS-INTERIOR-COUNT-REINFORCE-1`. Depends on the Tier-1 R1 (dead face lookup fix) and the Tier-1/2 R3 (dedup) carded separately.

---

## 0. Operator-approved design (the HYBRID, in one page)

**One sentence:** FLOOR = *held whole-house camera max over a short memory window* (where interior cams exist) + *deduped door entries-minus-exits since the last empty anchor*, with home-tracked residents subtracted **once house-wide**, zeroed when the house goes AWAY, and corroborated — not driven — by Revel guest phones once the Revel filter is fixed. The design is **tuned for 1–2 people** (the household norm); parties are the stress case, not the target.

**Rulings this plan encodes (operator 2026-10-04, rounds 1–4):**
1. Cameras count bodies well; names/faces are not required for counting. **INV-NO-NAME**.
2. `guests_present` is a **flag orthogonal to house state** (SLEEP + guests is a legal combination).
3. **Hybrid floor** (not a flow-driven ceiling as in the prior revision): held camera max + door in/out tally, residents subtracted once house-wide. AWAY = reset to 0 (true-empty anchor).
4. **Door tally** = merge both cameras per door, 30 s stem collapse, ~120 s distinct-person group window, quick out-and-back = net zero.
5. Guest WiFi phones (Revel) are **OUT of the floor** until the filter is fixed (hostname/MAC allowlist, "appeared since last empty anchor"). They may enter later as a corroborator, never as a sole floor driver.
6. **Measured interior overlap only.** The only real pair in retention is {`family_room`, `master_hallway`} (J=0.56, 1579 co-on minutes). The §5.2-candidate stair pairs were wrong (J ≤ 0.09).
7. **Exclude Apollo MTR-1** (`sensor.apollo_mtr_1_*`, offline/poor stationary detection) **and `sensor.upzone2_people_count`** (legacy custom) from census inputs.
8. **Tuned for 1–2 people.** Gates re-weighted: morning accuracy band tightened; party band widened; discrimination gate measured against a *household-norm day*, not a 1-guest-IoT-noise day.
9. **Graceful degradation by what is configured. NO new switches.** Interior cams absent → camera term **absent**, not zero. Egress cams absent → no flow term. Nothing configured → fall back to room-occupancy substrate; publish `census.health = degraded|absent` so consumers can read the degradation. Perimeter alerts continue to key off existing `CONF_SECURITY_ENABLED` (`const.py:2925`); interior-census degradation is detected, not switched. (`CONF_PERIMETER_ENRICHMENT_ENABLED` `:2071` is unchanged.)
10. **New config question (one):** household's **main entry door** (front / garage / back) — used as a resident-entry prior for door-to-resident attribution. The oracle household's answer is garage A (~95% of resident entries).
11. **10-03 truth (operator, final):** 3 residents home until afternoon; Jaya out (operator dropped off) and back ~23:24 via garage A **with operator** (that garage A event is resident, not guest); long-stay guest out AM, back evening; **8 day guests arrived 14:20** at the **front door** as one group over ~2 min; 10th visitor left 23:00; one guest left 23:55. §8a's 15-min bins and gates are to be re-scored against this.
12. **Prior-art first.** §4 carries a REUSE / FIX / DISCARD(justified) / NEW table citing file:line for every piece. NEW only where a named gap exists.
13. **Side findings are side cards, not scope.** §12 lists them with their revival triggers; they are not built here.

**Falsifiable invariant for the whole program** (D's single statement to break): *for every reachable tick, `FLOOR ≤ true_people ≤ ESTIMATE`, with `FLOOR = 0` within `EMPTY_ANCHOR_SETTLE_S` of AWAY, and `guests_present` ON iff at least one non-resident is on premises for `GUESTS_PRESENT_ON_S`.* Reviewer D's job in §9 is to produce a legal-config reachable triple that falsifies this.

---

## 1. Tier classification (unchanged structure; thresholds re-stated for the hybrid)

| Phase | Deliverables | Tier | Why |
|---|---|---|---|
| **Measure** | D0-REPLAY (re-score with the 10-03 operator truth), D2-OVERLAP (confirm {family_room, master_hallway}) | none (read-only) | Measure-Before-Build. Prior D0 (§8a) said NO-GO on the flow-ceiling design; the hybrid is specifically what the fix list in §8a's *"Fixes each failure implies"* argued for. D0-REPLAY proves the hybrid meets the re-weighted gates (§8). |
| **Shadow** | D3 (hybrid estimator in shadow), D4 (Revel filter FIX) | **Tier 2-DB** | New persisted state (empty anchor + door tally since anchor); additive payload keys; no consumer-visible value change (`interior_count` byte-identical). Three framing-disjoint reviews. |
| **Promote** | D5 (`guests_present` flag + GUEST consumer migration), D6 (FLOOR replaces snapshot `total_persons`; AWAY-safe binding; empty-anchor reset wiring) | **Tier 3** | Changes the house-state vocabulary (GUEST stops being inferred) and the count that feeds the AWAY veto, HVAC composition, security arming, NM perimeter severity, Bayesian suppression. Cross-coordinator trust-hierarchy ripple at a state-machine × time seam. Audit F5 (AWAY latched with 11 people home across a restart) proves this seam is already live-broken. Tier-3 discipline: two plan reviews, four framing-disjoint build reviews (A local / B state-machine / C per-site source mutation / D adversarial completeness), orchestrator re-grep of every GUEST reader before ship, operator checkpoint before deploy. |
| **Later** | D7 (AI-vision group count at the door) | Tier 2 (parked) | Revival trigger: D0-REPLAY shows door `person_count` cannot resolve groups ≥2 and this is the binding error source. (D0 §P2 already showed `person_count` almost never exceeds 1 — see §8.) |

---

## 2. Institutional context verified

### 2.1 Prior-art scan (REUSE / FIX / DISCARD(justified) / NEW), citing file:line

The exhaustive prior-art inventory lives in §4. The summary verdict table here is what the plan reviewer re-greps.

| Piece | Verdict | Evidence |
|---|---|---|
| Interior per-camera person count | REUSE | `CONF_CAMERA_PERSON_ENTITIES` `const.py:1973`; live 12 interior entities (`core.config_entries:268`). |
| Per-area max / cross-area sum dedup | REUSE then EXTEND (measured overlap pair only) | `_calculate_house_census` `camera_census.py:1690`. Measured overlap: §4.5. |
| Interior overlap table | NEW (named gap; §5.2 candidate list was falsified by D0 §P4) | No `INTERIOR_ADJACENCY` symbol in the component. Reuses the ratification method of `EXTERIOR_ADJACENCY_GRAPH` `const.py:2373`. |
| Hold/decay machinery | REUSE for the held-max floor; DISCARD(justified) for a flow ceiling | `_apply_hold_decay` `camera_census.py:5026`; `CENSUS_PEAK_SUSTAIN_SECONDS=15` `const.py:3544`; `DEFAULT_CENSUS_HOLD_INTERIOR_MINUTES=3` `const.py:3528`. Justification: D0 §P2/§P3 showed the flow is round-trip-dominated and group size unobservable, so a flow ceiling inflates without informing. |
| Door flow producer | REUSE then FIX | `TransitValidator._resolve_direction` `transit_validator.py:1724`; `_on_camera_state_change` `:795-834`; persisted to `person_entry_exit_events` `database.py:793-808`. FIXES: §4.3 dedup (R3). |
| Stem dedup window | FIX (inline literal `5.0` at `transit_validator.py:1736` is both a Numbers-Get-Knobs violation and too short per D0 §P1 which showed <5% residual at 30 s) | — |
| Door group size (`person_count`) | DISCARD(justified) for group-size estimation | D0 §P2: 14 of 15 burst entries had `group_hi`=1; `person_count` cannot resolve groups ≥ 2. Still **used as a floor source** (held-max). |
| Distinct-person group window at door | NEW (named gap: how to collapse legs of a single arrival spread across cameras over ~2 min) | ~120 s per operator footage (8-person group arrived over ~2 min). Collapses two cameras per door, not for group-size inference. |
| Resident attribution at door | REUSE then EXTEND (prior = household main-entry door) | Existing BLE-provenance pattern; depends on `EGRESS-BLE-PROVENANCE-GATE-DROPS-DEPARTURES-1` (§12). D0 §P3: tracker edges 8/42 — provenance is the binding gap, not optional. |
| Resident subtraction scope | FIX (do it once **house-wide**, not per-area) | `_get_unrecognized_camera_count` `camera_census.py:5198` uses `R_cam` (BLE in area); D0 §P4 showed `R_cam≈0` because `_area` rarely resolves to a camera area. House-wide `R_home_awake` subtraction once is the operator-approved shape. |
| Guest-room occupancy | REUSE | `_guest_room_gate_armed` `presence.py:5303`; `_is_known_person_in_room`; `CONF_ROOM_IS_GUEST_ROOM` `const.py:402`. |
| Revel guest phones (recency filter) | FIX | `_get_wifi_guest_count` `camera_census.py:5383-5548`; `CONF_GUEST_VLAN_SSID` `const.py:3553` (`Revel`); `WIFI_GUEST_RECENCY_HOURS=4` `const.py:3638`. D0 §P5: filter preserved IoT noise (UniFi gear, HA voice, `watch`), so the filter must become a **hostname/MAC allowlist + "appeared since last empty anchor" rule**, not a window on `last_changed`. **Phones stay OUT of the floor** until the fix is proven. |
| Egress-face guest identities | REUSE (corroborator only; never a floor driver) | `_get_egress_guest_ids_fresh` `camera_census.py:5695`; `EGRESS_FACE_UNION_TTL_S=300` `const.py:2734`. |
| Body-reinforcement TTL bucket | FOLDED-IN (close its card) | `PLANNING_egress_interior_count_reinforce.md` D2; subsumed by door tally + held-max. Close `EGRESS-INTERIOR-COUNT-REINFORCE-1`. |
| `guests_present` flag | NEW (an entity; no `guests_present` symbol exists repo-wide) | REUSES the existing `binary_sensor.ura_presence_coordinator_guest_mode` `binary_sensor.py:2412-2445` entity_id — re-pointed to the flag, not a second entity. |
| Manual guest override | REUSE | `select.ura_presence_coordinator_house_state_override`, `services.yaml:21`, `HouseStateMachine.set_override`. |
| Household **main entry door** config | NEW (named gap; no `CONF_MAIN_ENTRY_DOOR` found) | Operator ruling 11; §4.6. Reuses the Protect door-cam group names already in the egress set. |
| Interior-census master switch | **DO NOT ADD** (operator ruling 9) | Reuse `CONF_SECURITY_ENABLED` `const.py:2925` for perimeter-alert gating. Interior census degrades by *what is configured*, exposed via `census.health`. |
| Apollo MTR-1 / `upzone2_people_count` | DISCARD(justified) | Operator ruling 7. Apollo offline; upzone2 legacy. **Not** census inputs. |

### 2.2 Prior planning docs consulted
- `AUDIT_census_subsystem_2026_10_04.md` (full read; root cause).
- `AUDIT_census_footage_ground_truth_2026_10_03.md` (full read; ground-truth fixture).
- `quality/tests/fixtures/census_ground_truth_2026_10_03.csv` (full read; per-slot deduped visible counts).
- `RESEARCH_guest_actuation_and_census.md` §4–§8; its warning against a *WiFi over-reading* floor stays honoured — Revel is kept out until the filter is fixed.
- `CATALOG_cross_correlation_primitives.md` Tier 2 C1–C16 ("EXTEND, don't roll a new primitive"); the hybrid is a new combiner over existing producers.
- `AUDIT_exterior_camera_adjacency_probe.md` (ratification method for the overlap table).
- `PLANNING_egress_interior_count_reinforce.md` (folded in).
- `PLANNING_guest_census_correctness.md` (GUEST-CENSUS D1/D2; why Path A is computed but not consumed, `presence.py:5886-5892`).
- Kanban: `CENSUS-GUEST-FLOOR-1` `kanban.data.yaml:16899` SUPERSEDED by D3+D5; `EGRESS-INTERIOR-COUNT-REINFORCE-1` `:16687` FOLDED into D3; `CENSUS-GHOST-DEDUP-1` `:16776` ADJACENT (per-area BLE-cancel the floor reuses); `CENSUS-FACE-RESOLVER-MIGRATE-1` `:19861` candidate home for R1.

### 2.3 Memory bodies relevant (bodies to be pulled by the plan reviewer)
`reference_frigate1_retired_2suffix_permanent`, `reference_protect_face_latency_async`, `reference_egress_face_coverage_7pct_not_a_ceiling`, `project_guest_mode_false_positive_backlog`, `project_presence_guest_latch_and_veto_gap` (I-D1 is **superseded** by this plan removing the latch), `reference_pooloverhead_four_integrations`, `feedback_no_restart_during_sleep`, `project_single_user_no_backcompat` (CHANGING: 2nd install goes live 10-03/04, so **optional inputs must degrade gracefully** — the operator's ruling 9 is exactly this constraint).

### 2.4 Design docs read
`IDENTITY_FUSION_CAMERAS_MANUAL.md` §1–§4 (platform roles, `_2` rules, cross-corroboration doctrine, resolver ladder, TransitValidator); `house_state.py:60-139` (states, transitions, hysteresis). This is a camera/identity/census domain plan — the manual is mandatory per CLAUDE.md.

### 2.5 Code surveyed (end-to-end during scoping)
`presence.py` 1230-1349, 5290-5410, 5840-5910; `camera_census.py` 1690-1965, 3192-3231, 5026, 5198-5381, 5383-5548, 5638-5770, 5695; `transit_validator.py` 795-834, 1167, 1724-1748; `house_state.py` 60-139; `hvac.py` 3928-3974, `hvac_const.py` 220-275, 1229-1239; `preset_overrides.py` 40-155; `dynamic_preset.py` 840-874; `energy.py` 7371-7389; `security.py` 160-176; `__init__.py` 2875-2899; `const.py` 1973, 2071, 2307-2311, 2373, 2712, 2925, 3528, 3544, 3553, 3638. Live config: `/Users/okosisi/ha-config/.storage/core.config_entries` + `core.entity_registry`.

### 2.6 Config-first check (gate step 1b)
- **Interim, zero code:** operator can force GUEST via `select.ura_presence_coordinator_house_state_override`. That still blocks SLEEP and is the only lever today. No knob makes the census stock vs snapshot, no knob makes GUEST orthogonal to SLEEP. **Code is required.**
- **Config that improves inputs (operator-side, no URA change):** Frigate interior zones; more interior camera coverage (operator ruling 9 says NO such coverage is the default case — the design must not require it); enrolling Jaya/Ezinne in Protect faces.
- **One new config question is justified:** the household's main entry door, used as a resident-entry prior for door attribution (operator ruling 10).

---

## 3. Literature and prior art

Table L1–L18 as in the prior revision is retained verbatim and MOVED to `docs/planning/REFERENCES_census_estimator.md` to keep this plan focused. The relevant conclusions re-stated here:
- L1 (Meyn 2009): flow-only = ~70% error; fused + bounded = ~11%. Grounds the hybrid.
- L2 (PreCount 2018): per-door bias learned from verified-empty anchors; D3 records the residual at every AWAY reset for this.
- L4 (Axis): "scheduled reset" is standard; verified-empty is a stronger anchor.
- L8 (bursty signals): justifies the *held-max* floor over an instantaneous floor.
- L15/L17 (Frigate / Protect docs): count sensors exist for Frigate per-camera and `_2` rules apply; Protect exposes no count sensors (binary corroborator only, per manual).
- L18 (HA UniFi): a wireless client is `home` iff `now − last_seen ≤ detection_time`; `last_changed` is the *connect* time. Root cause of R7/D4: the current filter misreads "connected > 4 h" as "resident".

Literature does **not** supply a method for the specific "household of 1–4 with sporadic 1–2 guests" regime; the hybrid is an engineering design, not a cited result.

---

## 4. Inventory: person-detection capabilities actually available

### 4.1 Frigate interior
`sensor.<cam>_person_count` on: family_room, foyer_fisheye, master_hallway, staircase (= Garage Hallway, per D0 §P4), stairs_top, playroom, upstairs_hall. D0 §P4 minutes-with-count>0 over 8 days: family_room=2744, master_hallway=1643, playroom=187, staircase=105, stairs_top=65, upstairs_hall=39, foyer_fisheye=27. **`foyer_fisheye` and `upstairs_hall` are effectively dead on the current camera config** — the design must not depend on them.

### 4.2 UniFi Protect
Per-camera `binary_sensor.<cam>_person_detected` on interior and all five egress cameras. No count, no exposed line-crossing. Binary corroborator only (manual §1, catalog C1).

### 4.3 Egress cameras (five)
`madrone_g6_entry`, `doorbell_lite`, `front_door_aerial`, `garage_a`, `garage_b`. Each has a Protect `_person_detected`, a Frigate `_person_occupancy_2`, and a Frigate `_person_count`. **Door groups the plan uses** (operator-confirmed):
- **front** = {madrone_g6_entry, front_door_aerial, doorbell_lite}
- **garageA** = {garage_a}
- **garageB** = {garage_b}
(Prior §8a lumped doorbell_lite with garageA, which was wrong; the 10-03 arrival burst at 14:20 was at the front door.)

### 4.4 Non-camera counters found in the registry
- `sensor.apollo_mtr_1_fa21b0_*` — **EXCLUDED** (operator ruling 7).
- `sensor.upzone2_people_count` — **EXCLUDED** (operator ruling 7).

### 4.5 Area-mapping facts that matter for overlap and resident subtraction
From `core.config_entries` and `core.entity_registry` (verified live, D0 §P4):
- family_room → Living Room; foyer_fisheye → Entry Way; master_hallway → Master Hallway; **staircase → Garage Hallway** (NOT the foyer stair); stairs_top → Stairs; playroom → Game Room; upstairs_hall → Upstairs Hallway.
- Kitchen, Dining, Media, Master Bedroom, Guest Bedrooms, Garage **rooms** have `room_cameras: []`.
- Measured interior overlap (D0 §P4): the ONLY strong simultaneous overlap pair is **{family_room, master_hallway}** (J=0.56, 1579 co-on minutes). Every §5.2-candidate stair pair in the prior revision had J ≤ 0.09 and is **rejected**.

### 4.6 Household main-entry-door prior (NEW config question)
New: `CONF_MAIN_ENTRY_DOOR` (Select): `front` | `garage_a` | `garage_b` | `front+garage_a` (combo). Default: unset → neutral prior. Operator household: `garage_a`. Used in door-to-resident attribution (§7.3) to raise the resident prior for crossings at the configured door within the match window, and to tie-break ambiguous attribution.

---

## 5. Measured interior overlap (D2)

### 5.1 Probe (if re-run; prior §8a §P4 already produced the Jaccard table over 8 days of recorder)
Method unchanged from the prior revision: simultaneous Jaccard + onset lag + single-resident oracle. The probe already ran; its result is in §8a §P4 and is the measured basis for §5.2.

### 5.2 `INTERIOR_CAMERA_OVERLAP_GROUPS` (rung 1, operator-ratified)
From D0 §P4, the only measured OVERLAP component is:

```
INTERIOR_CAMERA_OVERLAP_GROUPS: Final = (
    frozenset({"family_room", "master_hallway"}),
)
```

Every other interior camera stands alone (fail-safe: sum, since it biases low — correct for a floor). The dedup rule per tick: `S(t) = Σ_components max_{cam∈component} count_cam(t)`. If a future day shows new overlap, the operator ratifies and this const is extended. Non-transitive chains handled by connected components.

---

## 6. `guests_present` flag and consumer migration (D5)

Semantics, migration table (rows 1–25), and orchestrator pre-ship re-grep as in the prior revision §6 — the design did not change on this axis. The only hybrid-specific refinements:

- **Criterion (a)** for ON now reads from the hybrid: `guest_estimate = FLOOR − |R_home_awake|` (clamped at 0), sustained `GUESTS_PRESENT_ON_S`. The hybrid floor is residents-subtracted-once, so `guest_estimate` is well-defined even when a camera also shows a resident.
- **Criterion (c)** Revel path stays conditional on D4 (filter fix) and the "appeared since last empty anchor" rule. Until D4 lands, (c) is dormant.
- **OFF condition** keyed off `FLOOR = |R_home_awake|` for `GUESTS_PRESENT_OFF_S` (plus no guest room unknown-occupied, plus no override). An AWAY empty-anchor forces OFF immediately.
- Entry rows (`binary_sensor.ura_presence_coordinator_guest_mode` at `binary_sensor.py:2412-2445`) **re-point to the flag** keeping the entity_id. Row 23 (operator `automations.yaml:8308`) requires an operator-side note, no URA edit.

Full table (rows 1–25) retained verbatim from the prior revision; the only textual change is "ceiling" → "hybrid floor" in rows 4 and 25.

Tier-3 orchestrator pre-ship: `git grep -nE "GUEST\b|'guest'|\"guest\"|guest_mode"` across the component + `/config/automations.yaml` + `scripts.yaml` + dashboards. Table is a hypothesis; re-greps are authority.

---

## 7. Algorithm specification (D3) — HYBRID

**Scope** (unchanged): count people on the premises inside the egress boundary. Patio = INSIDE for security (operator ruling); patio has no camera/mmWave (coverage gap, §12).

### 7.1 Inputs per tick (existing census tick; no new timer)
- `R_home_awake`: residents the person tracker shows home, filtered to those not in a `SLEEP`-type sub-state (so sleeping residents still count — they are on-premises).
- `count_cam(t)`: Frigate `person_count` per **configured** interior camera, watchdog-discounted (existing stuck-camera discount; runs upstream).
- `S(t)`: overlap-deduped interior bodies (§5.2). If no interior cameras are configured, `S(t)` is **ABSENT** (sentinel, not 0) and the floor's camera term drops out — see §7.5.
- `U_gr(t)`: designated guest rooms occupied with no known person (`_is_known_person_in_room`).
- `W(t)`: Revel guest phones (dormant until D4; see §7.6).
- Door events post-R3-dedup: `(t_e, direction, door_group, person_id|None)` where `door_group ∈ {front, garageA, garageB}` and legs within a door_group are collapsed on a **30 s stem window** (D0 §P1 showed <5% residual at 30 s, 0/80 over-merge).
- Resident attribution per crossing: resolved via `person_id` match, OR a resident tracker edge within `RESIDENT_CROSSING_MATCH_S` (depends on `EGRESS-BLE-PROVENANCE-GATE-DROPS-DEPARTURES-1`), OR the **main-entry-door prior**: when `door_group == CONF_MAIN_ENTRY_DOOR` and a resident tracker went `home` or `not_home` in the last `MAIN_ENTRY_PRIOR_S`, attribute to that resident. (This is what fixes the 23:24 garage-A event = operator + Jaya, both residents.)

### 7.2 FLOOR — held camera max + door tally, residents subtracted once

Two components, both are **lower bounds** on people present now:

1. **Held camera max over a short memory window:**
   `M_cam(t) = max_{τ ∈ [t − FLOOR_WINDOW_S, t]} S(τ)` if interior cameras configured, else ABSENT.

2. **Door tally since last empty anchor:**
   - At the empty anchor (AWAY, §7.4), set `T(t_anchor) = 0`.
   - On an anonymous entry at door_group `g`: `T += 1`.
   - On an anonymous exit at door_group `g`: `T -= 1`, clamped at 0.
   - **Quick out-and-back = net zero:** if an anonymous entry at `g` is followed by an anonymous exit at `g` (or vice versa) within `DOOR_ROUNDTRIP_S` with no other evidence between them (no interior camera rise, no other door event), **collapse the pair** before applying T. This is the operator-ruled "quick out-and-back = net zero" behaviour.
   - **Distinct-person group window:** multiple anonymous entries at the same door_group within `DOOR_GROUP_WINDOW_S` (default 120 s per 10-03 footage of the 8-guest arrival spread over ~2 min) are counted as **distinct persons** (not collapsed) unless the inter-event gap is below `DOOR_SAMEPERSON_S` (default 10 s), which is treated as the same person being re-detected across legs within a door_group.

3. **House-wide resident subtraction (once):**
   `A(t) = max(0, max(M_cam(t) if present else 0, T(t)) + U_gr(t) − |R_home_awake(t)|)`.
   Residents are subtracted once house-wide, not per area. This is the FIX to the `R_cam≈0` failure in D0 §P4.

4. **FLOOR:** `FLOOR(t) = |R_home_awake(t)| + A(t)`.
   - Rationale: residents enter by their count (unconditional), guests enter via the max of two lower bounds (camera or door tally), guest rooms are additive and spatially disjoint from camera areas (§4.5), and the whole guest term is residents-subtracted once because a camera that saw a resident shouldn't double-count them.

### 7.3 ESTIMATE — a soft upper bound bias on the floor

- Base: `ESTIMATE(t) = FLOOR(t)`.
- **Decaying flow bias:** keep an auxiliary accumulator `B(t)` that advances on anonymous entries by `+1` and anonymous exits by `−1`, bounded `[0, DOOR_TALLY_MAX]`, decaying linearly to 0 over `ESTIMATE_DECAY_S` after the last event. `ESTIMATE(t) = FLOOR(t) + max(0, B(t) − T(t))` — i.e. unconsumed flow bias above the tally itself (adds nothing on steady-state).
- **No separate ceiling sensor.** The prior revision's `CEILING` is DISCARDED: D0 showed it was inflated 1.5–2× by round-trip and dedup residuals, and literature L5's "errors accumulate" arithmetic was unmanageable on this data. The band = `ESTIMATE − FLOOR` serves the "honesty" need.

### 7.4 Empty anchor (AWAY reset)

- **Anchor fire condition:** `house_state → AWAY` (produced by the existing AWAY branch in `infer()`), **and** `R_home_awake = ∅`, **and** no guest room unknown-occupied, held for `EMPTY_ANCHOR_SETTLE_S`.
- **On anchor:**
  - Record `(C_pre, T_pre)` as the drift residual of this episode (PreCount-style training data for a future per-door bias).
  - `T → 0`, `B → 0`.
  - FLOOR immediately resumes from fresh evidence (next camera rise or next egress-entry).
- **Operator ruling 2:** a still guest left behind is possible but rare; AWAY is treated as a true-empty anchor regardless. The next egress-entry or camera count re-raises the floor. The acceptance of "possible but rare" is **documented**, not switched.

### 7.5 Graceful degradation (no new switches)

Published alongside the sensors: `census.health = ok | degraded | absent`, with `census.inputs_present = {camera_interior, door_flow, guest_rooms, revel}`.

| Configuration | Floor assembly | Health |
|---|---|---|
| Interior cams + egress cams + guest rooms | full §7.2 | ok |
| Egress cams only (no interior) — **default for most homes** | `M_cam` term absent; FLOOR = residents + max(T, U_gr) − residents (clamped) | degraded |
| Interior cams only (no egress) | `T` term absent; FLOOR = residents + max(M_cam, U_gr) − residents | degraded |
| Guest rooms only | FLOOR = residents + U_gr | degraded |
| Nothing configured | FLOOR = residents + 0; publish `census.health = absent`; consumers fall back to room-occupancy substrate | absent |

No `CONF_INTERIOR_CENSUS_ENABLED`, no new switch. `CONF_SECURITY_ENABLED` `const.py:2925` continues to gate perimeter alerts unchanged.

### 7.6 Revel (D4) — the filter fix, not a floor driver

- Replace `last_changed` recency with the UniFi `state == home` semantic (L18).
- Add a **hostname/MAC allowlist**: deny-list the IoT noise discovered in D0 §P5 (`garagebapu6-mesh-ea`, `officecabinetuswpro24poe`, `home-assistant-voice-*`, generic `iphone` without MAC, generic `watch`). Prefer a known-MAC allowlist for Revel.
- Add **"appeared since last empty anchor"** rule: only phones that joined Revel *after* the most recent AWAY anchor count as fresh guest phones. This drops the perpetually-connected IoT survivors.
- Phones stay **OUT of the FLOOR formula** at D3 ship. They enter only as (c) in the `guests_present` ON criterion (§6), and only after D4 proves the filter clean on the household-norm day.

### 7.7 Restart / boot (Bug Class: restore poisoning; audit F5)

- Persist `T`, `B`, `last_anchor_ts`, `last_anchor_T_pre`, `last_anchor_C_pre` via RestoreEntity extra data on the ESTIMATE sensor. Follow the existing RestoreEntity pattern; the plan reviewer verifies.
- On restore:
  - **Never** treat the boot-time floor as reconfirmation; never let a boot `S=0` lower anything.
  - Suppress the empty-anchor reset for `BOOT_SETTLE_S` (default 600 s).
  - Door events lost during downtime are accepted; the next camera rise re-converges FLOOR.
- F5 remains a separate side card (§12): the AWAY-while-residents-tracked-home is a **boot-time inference bug** in `infer()` that D6 fences, but the root cause is independent of the hybrid.

### 7.8 1-vs-2-person tuning (the household norm)

The gates and knobs are tuned so that:
- On a quiet morning with 2 residents + 1 long-stay guest, FLOOR = 3 within one tick of the guest appearing on camera or on an egress-entry, and `guest_estimate = 1`.
- On a quiet afternoon with 1 resident + 0 guests, FLOOR = 1 and `guest_estimate = 0`.
- A single guest arriving at the main entry door with no camera visibility pushes FLOOR = residents + 1 within `DOOR_SAMEPERSON_S`.
- The 40-person stress case (§7.9) is bounded, not accurate.

### 7.9 Stress case: 40 people circulating for 6 h

| Error source | Effect | Bound |
|---|---|---|
| Camera coverage (~7 areas, kitchen/dining/media uncovered) | `M_cam` ≈ peak simultaneously visible = perhaps 15–25 of 40 | FLOOR stays sound (≤ truth) but loose. |
| Door `person_count` cannot resolve groups (D0 §P2) | T under-counts arrivals in groups ≥2 | Bounded by camera term and D7 revival. |
| Round-trips (car / yard via garage) | T net could oscillate | Round-trip collapse (`DOOR_ROUNDTRIP_S`) + ESTIMATE decay. |
| Unmonitored departure (back patio to street) | T never decrements | Bounded by the next AWAY anchor. |

Accuracy target in the stress case: within ±25% of truth while flow is healthy. The decisions that matter (guests present, house not empty) are robust to a ±6 error at 40.

### 7.10 Knob ladder (every number: name, rung, default, why)

| Knob | Rung | Default | Why | Kill-switch |
|---|---|---|---|---|
| `FLOOR_WINDOW_S` → Number **"Count memory"** | 3 | 1200 s (20 min) | Operator tunes by observing quiet vs busy days. | 0 = instantaneous. |
| `DOOR_ROUNDTRIP_S` | 1 | 180 s | Collapses out-and-back on the same door with no other evidence. | 0 = disabled. |
| `DOOR_GROUP_WINDOW_S` | 1 | 120 s | Fitted to the 10-03 arrival burst (~2 min). | n/a |
| `DOOR_SAMEPERSON_S` | 1 | 10 s | Same person re-detected across legs within a door_group. | n/a |
| `RESIDENT_CROSSING_MATCH_S` | 1 | 120 s | Fitted to BLE edge latency. | n/a |
| `MAIN_ENTRY_PRIOR_S` | 1 | 300 s | Main-entry door resident attribution window. | n/a |
| Stem dedup window (replaces inline `5.0` at `transit_validator.py:1736`) | 1 | 30 s (D0 §P1) | Protocol window. | n/a |
| `EMPTY_ANCHOR_SETTLE_S` | 1 | 900 s | Safety: premature anchor loses the tally. | n/a |
| `BOOT_SETTLE_S` | 1 | 600 s | Restart fence. | n/a |
| `DOOR_TALLY_MAX` | 1 | 30 | Sanity cap. | n/a |
| `ESTIMATE_DECAY_S` | 1 | 1800 s | Shape; needs review. | n/a |
| `GUESTS_PRESENT_MIN_COUNT` | 2 (options flow) | 1 | Set once per household. | n/a |
| `GUESTS_PRESENT_ON_S` / `GUESTS_PRESENT_OFF_S` → **"Guest flag on/off delay"** named buckets (quick / normal / cautious) | 2 | normal = 600 s / 1800 s | Set once; named buckets per configurability-clarity rule. | n/a |
| `CONF_MAIN_ENTRY_DOOR` (Select) | 2 (options flow) | unset | One-time install question. | unset = neutral prior. |
| `WIFI_GUEST_RECENCY_HOURS` `const.py:3638` | **retired** (KEEP+DOCUMENT) | n/a | D4 replaces the semantic. | n/a |
| `switch.ura_census_estimator_enabled` | 3 | ON in shadow (no consumers) | Byte-identical fallback for D6. | OFF = legacy snapshot total + legacy GUEST gate. |

Label check: entity names ≤ 3 words, no jargon ("Count memory", "Guest flag delay", "Main entry door").

### 7.11 Falsifiable invariants

- **INV-FLOOR-SOUND:** for every reachable tick with the inputs it has, `FLOOR(t) ≤ true_people(t)` unless an exit is under-counted. Falsifier: a replay bin where FLOOR exceeds operator truth with no door-exit miss.
- **INV-ORDER:** `FLOOR ≤ ESTIMATE` on every tick, every path (boot, restore, AWAY anchor, decay). Falsifier: any published pair violating the order.
- **INV-NO-NAME:** emptying every face input and setting the kill switch OFF changes no FLOOR/ESTIMATE value. Falsifier: any count delta under face-off on D0 replay.
- **INV-GUEST-ORTHOGONAL (D5):** for any reachable state including SLEEP, `guests_present` can be ON, and `infer()` never returns `HouseState.GUEST`. Falsifier: a SLEEP tick with guest-room unknown-occupied ≥ 30 min and the flag OFF.
- **INV-AWAY-SAFE (D6):** house never enters AWAY while `FLOOR > |R_home_awake|` (i.e. while anonymous bodies are evidenced). Falsifier: F5 replay bin with AWAY and FLOOR > residents.
- **INV-SHADOW-BYTE-IDENTICAL (D3):** with the estimator ON in shadow, every pre-existing `SIGNAL_CENSUS_UPDATED` payload key is byte-identical to pre-cycle. Falsifier: golden-master diff.
- **INV-ANCHOR-ZERO:** within `EMPTY_ANCHOR_SETTLE_S` of entering AWAY with `R_home_awake=∅` and no guest-room unknown, `T=0` and FLOOR = 0. Falsifier: AWAY anchor tick with `T>0` still published.
- **INV-DEGRADE-GRACEFUL:** with every optional input (interior cams, egress cams, guest rooms, Revel) absent in turn, the system publishes a FLOOR (possibly only `|R_home_awake|`) with `census.health` describing the degradation; no exception, no NaN. Falsifier: any config-matrix combination that raises or returns None.

---

## 8. D0-REPLAY: re-score §8a against the operator's 10-03 truth, with hybrid gates (go/no-go)

**Nature:** one-shot, read-only. Reuses the §8a script (`census_d0/census_estimator_replay.py` in session scratchpad; promote to `scripts/probes/`). Adds: (a) the hybrid floor as spec'd in §7; (b) `DOOR_ROUNDTRIP_S` collapse; (c) front door_group = {madrone_g6_entry, front_door_aerial, doorbell_lite}; (d) main-entry-door prior `garage_a`; (e) truth updated per operator §13.

### 8.1 Truth timeline (operator-final, 2026-10-04 round 4)
| Window (CDT) | R_home_awake | Guests | Truth |
|---|---|---|---|
| 00:00–~08:00 | 3 (Ezinne, Oji, Jaya) | long-stay (sleeping) | 4 |
| morning | 3 | 0 (long-stay guest OUT in AM) | 3 |
| until ~14:03 | 3 | 0 | 3 |
| 14:03–14:20 | varies (Oji+Jaya depart ~14:03) | 0 | 1–2 |
| **14:20** | — | **+8 at front door** (one group, ~2 min) | 10–11 |
| evening | 2 (Ezinne + returning long-stay) | 8 + long-stay back = 9 | 11 |
| **23:00** | 2 | 10th visitor leaves (−1) | 10 |
| **23:24** | 3 (Jaya + operator back via **garage A**, both residents — do NOT count as guest) | 9 | 12 |
| **23:55** | 3 | 1 guest leaves (−1) → 8 remaining | 11 |

### 8.2 Hybrid gates (re-weighted for 1–2 person norm)
1. **Ordering:** `FLOOR ≤ ESTIMATE` in 100% of bins (construction).
2. **Floor soundness:** `FLOOR ≤ truth_hi` in ≥ 95% of 15-min bins. (The §8a reference-run failure here was W-driven; with W out, 85% was already achieved; §7.2 house-wide subtraction fix should push ≥ 95%.)
3. **Household-norm accuracy (THE primary gate):** `|FLOOR − truth| ≤ 1` in ≥ 90% of bins between 00:00 and the arrival event. This replaces the prior G4b (which was 6% because of Revel). This is the 1–2-person tuning gate.
4. **Party-band accuracy:** `|FLOOR − truth| ≤ 2` in ≥ 70% of bins between the arrival event and 24:00, AND FLOOR ≥ 4 in ≥ 80% of those bins (the "cannot drop back to resident-only during the party" check).
5. **Resident-only false-positive:** on the morning window with `R_home_awake = 3` and 0 guests, `guest_estimate = 0` in ≥ 90% of bins. (This is the discrimination gate; the §8a G5 criterion is unmeasurable here per retention, but §7.6 Revel-dormancy makes this directly measurable now.)
6. **Anchor behaviour:** at every AWAY-anchor tick in retention, `T=0` within `EMPTY_ANCHOR_SETTLE_S` and FLOOR = 0 (no residual flow).
7. **F5 replay (INV-AWAY-SAFE):** FLOOR > 0 across 15:53/16:01/17:02 stop/start; AWAY would have been blocked at 15:57.
8. **Garage-A-at-23:24 attribution:** with `CONF_MAIN_ENTRY_DOOR=garage_a` and residents' tracker edges, the 23:24 crossing is **attributed to residents** (operator + Jaya), not counted as guest entry.

### 8.3 NO-GO outcomes and what they mean
- (3) fails → either R3 dedup isn't fully applied, or `R_home_awake` is still wrong (phone-area vs home-vs-sleep); re-check `_area` normalization and the SLEEP sub-state filter.
- (4) fails → camera visibility collapsed the floor (same as footage audit observation); accept and move D7 up.
- (5) fails → a false-fire source still enters guest_estimate; most likely Revel leaking in via (c) if D4 is on in the probe, or an un-dedup'd door event. Keep Revel dormant.
- (8) fails → the main-entry-door prior isn't firing; probably BLE provenance is too narrow (depends on `EGRESS-BLE-PROVENANCE-GATE-DROPS-DEPARTURES-1`).

### 8.4 What is already known (from §8a; do not re-litigate in D0-REPLAY)
- Stem dedup at **30 s** = 1% residual, 0/80 over-merge → set as the production dedup window.
- Door `person_count` cannot resolve groups (14/15 burst entries = 1) → group size NOT inferred from `person_count`.
- Measured interior overlap = {family_room, master_hallway} only.
- Revel: current filter preserves 1–5 IoT survivors/day on quiet days → OUT of floor.
- 3 verified-empty anchors over 8 days; residuals were W artifacts → with W out of floor, residual expected ≤ 1.

---

## 9. Deliverables and acceptance criteria

### D0-REPLAY — one-shot re-score (gate before D3 build)
- **Verify:** `AUDIT_census_estimator_replay_2026_10_03_hybrid.md` exists with gates 1–8 and an explicit GO/NO-GO line per gate against the operator-final truth.
- **Verify:** `DOOR_ROUNDTRIP_S` collapse removes the 23:24-garageA pair-with-exit if a matching exit exists in window; the single-entry case stays attributed to residents by the main-entry-door prior.
- **Live:** n/a (offline).

### D1 — Prerequisites (separate cards; not built here)
- **R1** face map fix (`camera_census.py:3216`; replace fake-API monkeypatch in `test_census_accuracy_d1_d2.py:347`, `test_egress_camera_dead_config.py:59`). Tier 1.
- **R3** door dedup across legs, keyed on resolver physical camera, 30 s stem window from D0 §P1, replace inline `5.0` at `transit_validator.py:1736` with the named knob. Tier 1–2. **Prerequisite for D3.**
- **`EGRESS-BLE-PROVENANCE-GATE-DROPS-DEPARTURES-1`** — prerequisite for §7.1 resident attribution. Tier 2.
- **Verify (R3):** replay of 10-03 with production dedup gives < 5% same-stem duplicate rows; `persons_entered_today` display drops ~2×.
- **Live (R3):** next day's `person_entry_exit_events` shows no `garage_a` pairs < 30 s apart same direction.

### D2 — Interior overlap const (operator-ratified)
- **Verify:** `INTERIOR_CAMERA_OVERLAP_GROUPS = (frozenset({"family_room", "master_hallway"}),)` added to `const.py` with provenance comment citing D0 §P4.
- **Test:** `test_overlap_groups_components_max`: a non-transitive chain collapses by component, unlisted camera sums.
- **Live:** with a single resident walking family_room→master_hallway, `S(t)` never exceeds 1 (attribute `floor_components`).

### D3 — HYBRID estimator in SHADOW (Tier 2-DB)
New module `census_estimator.py` (pure, HA-free core + thin `PersonCensus` adapter), fed by the existing census tick and `ura_person_egress_event`. Publishes additive payload keys on `SIGNAL_CENSUS_UPDATED`: `estimate_floor`, `estimate`, `guest_estimate`, `door_tally`, `floor_components`, `inputs_present`, `census_health`. **No consumer reads them in this phase.** `interior_count` byte-identical.
- **Verify:** INV-ORDER, INV-NO-NAME, INV-ANCHOR-ZERO, INV-DEGRADE-GRACEFUL property tests (hypothesis-style, extremes + config matrix).
- **Verify:** INV-SHADOW-BYTE-IDENTICAL: golden-master over recorded ticks.
- **Test:** `test_estimator_replay_2026_10_03_hybrid` drives the production estimator over a fixture extracted from D0-REPLAY against the operator-final truth table (independent oracle, hand-authored).
- **Test:** per-site mutation anchors (C-review drill):
  - neuter `R_home_awake` subtraction → `test_floor_does_not_double_count_residents` fails;
  - neuter `DOOR_ROUNDTRIP_S` collapse → `test_quick_out_and_back_nets_zero` fails;
  - neuter the main-entry-door prior → `test_garage_a_at_2324_attributed_to_residents` fails;
  - neuter the AWAY anchor zeroing → `test_away_anchor_resets_tally` fails;
  - neuter the boot fence → `test_no_anchor_during_boot_settle` fails;
  - neuter the degrade path → `test_absent_interior_cams_still_publishes_floor` fails.
- **Sensor:** `sensor.universal_room_automation_occupancy_estimate` with attributes `floor`, `door_tally`, `guest_estimate`, `last_anchor_residual`, `inputs_present`, `census_health`, `floor_components`. (One sensor, attributes; Q6 answered pragmatically — fewer new entities.)
- **Live:** on a household-norm day (3 residents, 0 guests), `guest_estimate = 0` all day. One operator drill — a guest-free egress + camera walkthrough — publishes `FLOOR = |R_home_awake|` throughout. On the next real gathering, `guest_estimate ≥ 1` within `GUESTS_PRESENT_ON_S` of the arrival at the front door. Validate with one-shot queries, no soak.

### D4 — Revel filter FIX (Tier 1, ships inside D3)
- Replace `last_changed` recency with `state == home` (L18).
- Add hostname/MAC allowlist + "appeared since last empty anchor" rule.
- Fix the stale `WIFI_GUEST_RECENCY_HOURS` docstring at `camera_census.py:5404`.
- **Dormant in the FLOOR formula at D3 ship.** Promoted into `guests_present` criterion (c) only when gate 5 (resident-only FP) still holds on 7 consecutive household-norm days.
- **Verify:** `test_wifi_guest_requires_recent_join_anchor`; `test_wifi_guest_ignores_iot_hostnames`.
- **Live:** on a household-norm day, `wifi_guest_floor` attribute = 0 for ≥ 95% of the day.

### D5 — `guests_present` flag + GUEST consumer migration (Tier 3)
Per §6. **Two plan reviews before build** (completeness + adversarial build-prediction).
- **Verify:** INV-GUEST-ORTHOGONAL.
- **Verify:** manual override "guest" translates to flag ON (manual) + time-based HOME_*.
- **Test:** one behavioural test per row of §6.2 that changes behaviour (rows 9–13, 16–19, 22), each with a source-mutation anchor.
- **Sensor:** `binary_sensor.ura_presence_coordinator_guest_mode` re-pointed to the flag, keeping entity_id; new attribute `source` ∈ `{estimate, guest_room, revel, manual}`.
- **Live:** next gathering: flag ON before sleep hours, stays ON through SLEEP, house state reaches SLEEP, Bayesian learning suppressed, flag OFF within `GUESTS_PRESENT_OFF_S` after last guest leaves.

### D6 — Promote FLOOR to `total_persons` + AWAY-safe + empty-anchor wiring (Tier 3)
`_apply_enhanced_house_census` (`camera_census.py:5740-5754`) publishes `total = FLOOR` when the estimator switch is ON. `infer()` AWAY requires `FLOOR ≤ |R_home_awake|` (i.e. no evidenced anonymous bodies). AWAY anchor wires to §7.4. R5/F5 boot fence included.
- **Verify:** INV-AWAY-SAFE on F5 replay.
- **Verify:** INV-ANCHOR-ZERO on every AWAY anchor in retention.
- **Test:** existing AWAY-veto tests pass unchanged with the switch OFF (byte-identical). With it ON, new AWAY-safe tests pass.
- **Live:** `sensor.universal_room_automation_persons_in_house` on next gathering reads within the D0-REPLAY-accepted error; no AWAY while FLOOR > `|R_home_awake|` across a restart.

### D7 — AI-vision group count at door (PARKED)
Audit §4.1 option B. **Revival trigger:** D0-REPLAY gate 4 fails because of group undercount at the door, OR a real party arrival shows `door_tally` lagging the camera-visible count by ≥ 3 for ≥ `DOOR_GROUP_WINDOW_S`. Stays advisory only (manual §5.5).

### Non-goals
- No Re-ID.
- No Kalman / particle filter in v1. Revisit if D3 live band width is > 50% of the estimate on ordinary days for two consecutive weeks.
- No new interior hardware (operator ruling 9: no interior cams is the default case, not an edge case).
- No change to exterior / property census.
- No separate CEILING sensor (DISCARDED per §7.3).
- No new switches beyond the one estimator kill-switch (operator ruling 9).

---

## 10. Plan completion tracking (what this plan deliberately does NOT do)
- **AI vision at door:** parked as D7 with a trigger.
- **Kalman / particle filter:** parked (non-goal with revival trigger).
- **Flow-driven CEILING sensor:** DISCARDED (D0 falsified it).
- **Revel as a floor driver:** permanently out; only enters `guests_present` as (c), post-D4.
- **F5 shutdown-window AWAY investigation:** side card (§12-A), not folded into this program unless D6 proves it must be.
- **Interior cams absent configuration tested in prod:** depends on a second URA install going live (10-03/04); the test matrix (§D3 INV-DEGRADE-GRACEFUL) covers it synthetically; live validation on the 2nd install is a follow-up.

---

## 11. Manual corrections implied (apply with D3/D5 commits)
- **Manual §4.2:** replace "hold+decay after peaks" with the hybrid: held camera max + door tally with AWAY-anchor reset, residents subtracted once house-wide. Add the rule "counting must not need names" (INV-NO-NAME).
- **Manual §4.3:** correct the "5 s window" stem dedup to 30 s with cross-leg key (apply with R3).
- **New §4.7 "Occupancy estimator (hybrid)":** scope = inside egress boundary; floor/estimate semantics; graceful-degradation matrix; `census.health`.
- **New §4.8 "Main entry door prior":** `CONF_MAIN_ENTRY_DOOR` and the attribution rule.
- **Add to §10 CORRECTIONS LEDGER:** the §5.2-candidate stair pairs were wrong (J ≤ 0.09 in 8 days of recorder); only {family_room, master_hallway} is a real overlap.

---

## 12. Side findings — card them, do not build in this program

Each is a separate card with its own tier and acceptance:

- **A. AWAY-while-residents-tracked-home (audit F5, 16:00–17:05 10-03).** Boot-time inference in `infer()` ignores trackers after an HA restart. Card: `CENSUS-F5-BOOT-AWAY-FENCE-1`. Tier 1 investigate → Tier 2 fix. Revival trigger: already fired. INV-AWAY-SAFE in D6 fences the symptom but the root cause is independent.
- **B. `transit_validator.py:1736` 5 s stem dedup too short.** Card: `TRANSIT-STEM-DEDUP-30S-1`. Rolled into R3. Tier 1. Revival trigger: fired.
- **C. Dead face lookup (`camera_census.py:3216` `er.async_entries_for_platform` does not exist; fake-API monkeypatch in tests).** Card: `CENSUS-FACE-RESOLVER-MIGRATE-1` (kanban `:19861`). Tier 1 hotfix (R1). Prerequisite only for identity attributes, not for counting.
- **D. Patio has no camera / no mmWave (hardware gap).** Card: `COVERAGE-PATIO-1`. Hardware procurement; design treats patio as INSIDE for security without evidence.
- **E. `EGRESS-BLE-PROVENANCE-GATE-DROPS-DEPARTURES-1` prerequisite.** D0 §P3 showed tracker edges cover only 8/42 crossings; the resident attribution in §7.1/§7.3 depends on this fix landing. Tier 2.
- **F. Interior camera coverage of kitchen / living / dining extension (operator option; not forced).** R8. Config only.
- **G. Operator automation `/config/automations.yaml:8308` references `house_state == 'guest'`.** After D5 the state is never inferred; operator must adjust their own automation. Notification, not a URA edit.
- **H. Guest-free day deliberately captured.** `PROBE-GUEST-FREE-DAY-1`: name a day with no long-stay guest and re-run the discrimination gate within 8 days. Needed to validate D4 before promoting Revel into (c).

---

## 13. Operator ruling trail (chronological; this plan's authority)

- **Round 1 (prior-art first):** "Census must use prior tested machinery and functions, not invent new ones. New only where there are proper prior-art gaps. Does not mean using bad functions — fix them, or justify why they should be discarded." → encoded in §4 verdict table.
- **Round 2 (Q7/Q8):** AWAY = true-empty anchor (reset to 0; "still guest left behind is possible but rare"); Apollo MTR-1 and `upzone2_people_count` EXCLUDED; patio = INSIDE for security (hardware gap); no pets. → §7.4, §4.4, §12-D.
- **Round 3 (no new switches; graceful degradation):** no separate interior-census / perimeter toggles; census must degrade by what is configured; many houses have no interior cams (default case); at most ONE switch and reuse `CONF_SECURITY_ENABLED` for perimeter. → §7.5.
- **Round 4 (10-03 truth + GO on hybrid):** 3 residents home until afternoon; Jaya out, back ~23:24 via **garage A with operator** (resident); long-stay guest out AM, back evening; 8 day guests arrived **14:20 at the front door** as one group over ~2 min; 10th visitor left 23:00; one guest left 23:55. **GO on hybrid design**, tuned for 1–2 people, graceful degradation, main-entry-door question (`CONF_MAIN_ENTRY_DOOR`, ~95% garage A for this household). → §0, §7, §8.1.

---

## 14. Operator questions still open (narrow)

- **Q-A** `GUESTS_PRESENT_ON_S` / `OFF_S` named-bucket defaults: `quick` (120 s / 600 s), `normal` (600 s / 1800 s), `cautious` (1800 s / 3600 s). Confirm `normal` as default.
- **Q-B** `CONF_MAIN_ENTRY_DOOR` presentation: Select with single value, or multi-value for houses that genuinely have two main doors? Default to single for now.
- **Q-C** `census.health = absent` surfacing: a sensor attribute only, or a dedicated `sensor.universal_room_automation_census_health` entity so operators can alert on degradation? Recommend attribute only; add entity only if an operator alert is actually wanted.
