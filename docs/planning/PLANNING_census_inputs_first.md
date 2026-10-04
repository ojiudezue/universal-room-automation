# PLANNING — Census INPUTS first (fix producers, then re-run D0-REPLAY)

**Status:** DRAFT 2026-10-04 (not committed). Not shipped. No code changes by this document.
**Author:** ura-planner.
**Operator ruling (2026-10-03):** "Fix census INPUTS before building the hybrid estimator, then re-run D0-REPLAY." The hybrid formula in `PLANNING_census_occupancy_estimator.md` is accepted — but D0-REPLAY (`AUDIT_census_estimator_replay_2026_10_03_hybrid.md`) returned **NO-GO** on gates G2/G3/G5 because the INPUTS it was fed were themselves wrong.
**Operator truth correction (2026-10-04, mid-plan):** there was **NO separate drop-off visitor on 10-03**. The earlier "drop-off guy" in the hybrid audit was a voice-dictation of "drop off Jaya." Corrected ground truth for midday:
- The **12:00–13:30 front-door burst = operator porch-cleaning ONLY** (resident, net 0, no visitor leg).
- The **~12:00 `garage_a` departure = operator + Jaya leaving by car** to drop Jaya off (two residents, both out). The audit's open item about 12:08–12:49 `garage_a`/`garage_b` crossings during Ezinne's 12:19–12:57 tracker gap is reframed: those crossings belong to the operator (and in one case operator+Jaya), not a visitor.
- **Guest band for 12:00–13:30 is 0, not 0–1.** Any `T > 0` in that window is a pure attribution failure.
**Supersedes:** nothing. **Depends on:** none in-flight. **Unblocks:** D3 shadow in `PLANNING_census_occupancy_estimator.md`.
**Canonical reference (mandatory read):** `docs/Coordinator/IDENTITY_FUSION_CAMERAS_MANUAL.md` (platform roles, `_2`-suffix rules, egress-identity JOIN, 6.0.0 identity-driven autonomy gate).
**Also read:** `PLANNING_census_occupancy_estimator.md` (esp. §4.3, §12 last-operator blocks), `AUDIT_census_estimator_replay_2026_10_03_hybrid.md`, `AUDIT_census_subsystem_2026_10_04.md`, `AUDIT_census_footage_ground_truth_2026_10_03.md`.

---

## 0. One-page summary

D0-REPLAY failed because:
- **G2/G3 (floor soundness, household-norm):** the door tally (`T`) over-counted guests at midday on **pure resident activity** (operator porch-cleaning at `front`; operator+Jaya leaving by car at `garage_a`). None of {resident `person_id`, resident tracker edge within ±300 s, main-entry prior} caught them, so 11 `garage_a` crossings reversed into T and the front-door burst produced several unattributed entries. **The midday guest-band truth is 0** — every T>0 minute between 12:00 and 13:30 is a false positive sourced by missing resident attribution, not by a real visitor.
- **G5 (resident-only morning):** `M_cam` read 4–5 bodies 10:00–11:15 with only 3 residents home and the long-stay guest OUT — an interior-camera over-count defect, not an estimator defect.
- **8-person 14:22 arrival collapsed to 1 ledger entry:** two cameras per door merged correctly, but same-door-group same-direction legs within the 180 s round-trip window + 30 s stem dedup collapsed 8 real bodies into 1 logical crossing. `front_door_aerial` only peaked at 6 of 8 concurrent faces — full multiplicity recovery is unrecoverable without a distinct-person group window and (eventually) D7 vision counting.

**The INPUTS, not the formula, are the scope.** This plan fixes door-event quality (D1), BLE departure provenance / resident attribution (D2), and interior camera over-count (D3). Only then (D4) does D0-REPLAY re-run as the exit gate.

**Falsifiable program invariant for this plan:**
> **INV-INPUTS:** on a replay of 2026-10-03 with D1+D2+D3 landed, (a) G5 ≥ 90% (resident-only morning false-positive ≤ 10%), (b) G2 ≥ 95% and G3 ≥ 90% (truth-bounded in household-norm windows), (c) the 14:22 front-door arrival produces ≥ 2 surviving logical entries post-pipeline (full 6-of-8 recovery parked to D7), AND (d) `T` is 0 for the entire 12:00–13:30 window (zero false-positive guests on pure-resident activity, per the corrected truth).

Discrimination: a passing run under the OLD inputs is impossible; a failing run under the NEW inputs tells us which of D1/D2/D3 missed. (d) specifically discriminates attribution failure (D2) from pipeline failure (D1): if `T` is still > 0 at 12:00–13:30 but every midday crossing now carries a resident `person_id` or edge, D1 is wrong (pipeline not counting attributed-residents as attributed); if crossings still have no `person_id`/edge match, D2 is wrong.

---

## 1. Institutional context verified

### 1.1 Prior-art scan — REUSE / FIX / NEW (file:line)

| Piece | Verdict | Evidence |
|---|---|---|
| `TransitValidator._resolve_direction` | **FIX** | `transit_validator.py:1724-1758`. Direction depends on `_get_interior_cameras_near`. |
| `_get_interior_cameras_near` returning ALL interior cams | **FIX** | `transit_validator.py:1955-1963`. Degenerate: any interior fire anywhere → direction=entry. |
| Stem dedup inline literal `5.0` | **FIX** (knob + widen) | `transit_validator.py:1736`. Replace with `DOOR_STEM_DEDUP_S` (default 30 s per `AUDIT_census_subsystem_2026_10_04.md` §1.3: 58/143 dupes <5 s but a 5–30 s band exists). |
| Per-door camera grouping | **FIX** (consume per-install config) | `CONF_DOOR_GROUPS` already exists per `PLANNING_census_occupancy_estimator.md` §4.3; `_resolve_direction` does not yet key off it. |
| `CONF_MAIN_ENTRY_DOOR` (per-install) | **REUSE from estimator plan §4.6** | Options derived from `CONF_DOOR_GROUPS`; oracle household = `garage_a`. |
| `CONF_DOOR_INTERIOR_NEIGHBOURS` | **NEW** (per-install, options-flow rung-2) | Per-door nearby-interior-cam map; grep repo-wide — no existing symbol. |
| BLE/GPS departure provenance | **ALREADY SHIPPED** (verify-only here) | Card `EGRESS-BLE-PROVENANCE-GATE-DROPS-DEPARTURES-1` status=done, shipped v5.96.0. Live counter `ble_exit_backfilled_count=4` on 2026-09-11. **D2 CONFIRMS it is attaching resident legs on the 10-03 replay.** If the midday operator-cleaning + operator+Jaya `garage_a` crossings have NO phone edges within any window on 10-03, the producer did not fire — regression on a shipped feature. |
| `camera_census.py:_calculate_house_census` per-area max | **REUSE** | `camera_census.py:1690`. The interior over-count fix (D3) extends `CONF_INTERIOR_CAMERA_OVERLAP_GROUPS` (per-install) rather than touching this. |
| `CONF_INTERIOR_CAMERA_OVERLAP_GROUPS` | **REUSE from estimator plan §5.2** | Oracle household measured pair: `{family_room, master_hallway}` J=0.56. The footage audit's dedup rule (`foyer_fisheye` sees family_room floor-edge) suggests a second pair P-D3 should confirm. |
| Interior camera entity list | **FIX (config)** | `CONF_CAMERA_PERSON_ENTITIES` `const.py:1973`. Candidate removals: `foyer_fisheye`, `upstairs_hall` (D0 §P4: 27 / 39 min-with-count>0 across 8 days — effectively noise, likely a source of G5 over-count). Config only — no code. |
| Hold / decay | **UNCHANGED** | `_apply_hold_decay` `camera_census.py:5026`. |

### 1.2 Prior planning / audit docs consulted
`PLANNING_census_occupancy_estimator.md` (full), `AUDIT_census_estimator_replay_2026_10_03_hybrid.md` (full), `AUDIT_census_subsystem_2026_10_04.md` (full), `AUDIT_census_footage_ground_truth_2026_10_03.md` (full), `AUDIT_exterior_camera_adjacency_probe.md` (method reference for D3 overlap probe).

### 1.3 Memory bodies relevant
`reference_frigate1_retired_2suffix_permanent` (`_2` suffix on Frigate 2 must be honoured by any new resolver), `reference_protect_face_latency_async` (back-fill expectations when validating attribution), `reference_egress_face_coverage_7pct_not_a_ceiling` (face attach is corroborator, not FLOOR input), `project_single_user_no_backcompat` (CHANGING: 2nd install 10-03/04 — all new config is per-install, degrades gracefully if unset).

### 1.4 Code surveyed (end-to-end for scoping)
`custom_components/universal_room_automation/transit_validator.py` 795-834, 1167, 1700-1980; `camera_census.py` 1521-1700, 1690, 1955, 3192-3263, 3676-3740, 4531, 5026, 5198-5381; `const.py` 1973, 2307, 2373, 3528, 3544, 3638; `database.py` 793-808. Kanban: `EGRESS-BLE-PROVENANCE-GATE-DROPS-DEPARTURES-1` (done v5.96.0 — but see D2 verify-first), `CENSUS-ACCURACY-1`, `CENSUS-FACE-RESOLVER-MIGRATE-1`, `CENSUS-GHOST-DEDUP-1` (done), `TRANSIT-1` (checkpoints shipped v5.60.0 — not in scope).

### 1.5 Config-first check (ura-kanban gate step 1b)
- `CONF_CAMERA_PERSON_ENTITIES` is already a live config — D3's `foyer_fisheye` / `upstairs_hall` removal may be a pure config action. **Test as a config-only variant before writing D3 code.**
- `CONF_INTERIOR_CAMERA_OVERLAP_GROUPS` (per-install options-flow field per estimator §5.2) does not yet exist as an options-flow field. For this cycle: set per-install in a const / YAML; defer UX to the estimator cycle.
- `CONF_DOOR_GROUPS` already exists and is populated. `CONF_DOOR_INTERIOR_NEIGHBOURS` is NEW and REQUIRED by D1.
- No knob fixes the dead-attribution problem (D2 is code or data-side).

---

## 2. Measure-Before-Build — read-only probes (ALL must run before building that deliverable)

One-shot `ssh ha "python3 -" < probe.py` scripts against the HA recorder (`?mode=ro`) and URA DB.

### P-D1 — Door-event forensics on 2026-10-03
**Goal:** diagnose why 14:22's 8-person arrival collapsed to 1 ledger entry; verify every midday crossing is a resident one (per corrected truth).
**Reads:** `person_entry_exit_events` 10-03 00:00–23:59; recorder `binary_sensor.<cam>_person_detected`, `binary_sensor.<cam>_person_occupancy_2`, `sensor.<cam>_person_count` for all 5 egress cameras + `doorbell_lite`.
**Outputs (per crossing):** raw leg list; surviving leg after stem-dedup at 5 / 15 / 30 / 60 s; direction label; any interior cam fire within ±20 s and ±60 s; any resident tracker `home<->not_home` edge within ±120 s / ±300 s / ±900 s.
**Discriminators:**
- 14:22 window: how many **distinct** `person_count` peaks ≥ 1 arrive on `front_door_aerial`+`madrone_g6_entry`+`doorbell_lite` within a 180 s window after cross-camera physical dedup? If ≥ 6, a distinct-person group window of 120 s can recover the group; if ≤ 3, only D7 vision can.
- **12:00–13:30 crossings (operator porch-cleaning + operator+Jaya `garage_a` departure):** list every one with (door_group, direction, resident tracker edge in ±120 / 300 / 900 s? which tracker? any `person_id`?). Per the corrected truth EVERY ONE is a resident crossing. Any crossing that fails to attribute to a resident is a data defect we must explain — bucket as: (a) resident tracker edge exists at some wider window (D2 window-widening), (b) no edge at any window (D2 producer-regression or wrong allowlist), (c) `person_id` on the row but pipeline still counted it as unattributed (D1 pipeline bug).
- `doorbell_lite` 23:25 and 23:30 fires: list all other egress-cam fires within ±60 s to confirm door_group assignment (operator ruling: `garage_a` on this install).

### P-D2 — Resident attribution gap (BLE/GPS) with corrected truth
**Goal:** of every midday crossing (now 100% resident per corrected truth), count how many had Ezinne's / operator's / Jaya's trackers (BLE Bermuda AND GPS) transition at ANY point in ±900 s. Which tracker entity, which edge, which lag?
**Reads:** `person.ezinne`, `person.oji_udezue`, `person.jaya`; every underlying `device_tracker.*` in `EGRESS_CROSSING_ADMISSIBLE_TRACKERS`; `person_entry_exit_events` 10-03.
**Discriminators:**
- For the **~12:00 `garage_a` departure (operator + Jaya leaving by car)**: did BOTH operator's phone AND Jaya's phone fire `home→not_home` within any window? Expected: yes within ±300 s given this is a car departure (GPS geofence). If no, producer regression on `EGRESS-BLE-PROVENANCE-GATE-DROPS-DEPARTURES-1`.
- For the **operator porch-cleaning front-door burst**: the operator never left home — tracker never transitioned. Attribution via tracker-edge is impossible by construction. **This is the hard class.** The main-entry prior does not help (`front` ≠ `garage_a`). Two paths:
  - **Path α (preferred, no new producer):** if the operator's phone BLE **area/room-presence** signal shows them at/near the front door for the crossing, use that as a resident corroborator. Check whether an existing presence signal (`domain_coordinators/presence.py` room-presence, or a Bermuda area tracker) exists that is DIFFERENT from the home/away edge.
  - **Path β (no signal):** accept that an "at-home resident wandering through a non-main door" is physically unattributable from tracker data alone. The estimator §7.4 empty-anchor erasure covers this at the next empty window; but the midday hours have no empty anchor, so **this residual is irreducible without a new input source**. In that case, D2 produces a **documented known-gap** and the plan's INV-INPUTS (d) is adjusted to allow up to N (TBD by P-D2) at-home-operator crossings per day.
- Count `person_entry_exit_events.person_id IS NOT NULL AND person_id IN (residents)` per hour on 10-03 vs the shipped-card's live counter claim. If 0, the producer regressed.

### P-D3 — Interior camera over-count 10:00–11:15
**Goal:** identify which camera(s) contributed the 4–5 vs truth-3 inflation.
**Reads:** per-camera `sensor.<cam>_person_count` 10:00–11:15 at 15 s resolution; `binary_sensor.<cam>_person_occupancy_2`; resident tracker locations.
**Discriminators:**
- Which camera is reading ≥ 1 person per minute? (Expect family_room = 1–3 with residents; the long-stay guest was OUT per operator — so family_room should be ≤ 3 unless the family_room count-source is itself inflated.)
- Any pair of cameras showing simultaneous person_count>0 that is NOT in `CONF_INTERIOR_CAMERA_OVERLAP_GROUPS`? (Expected candidate: `foyer_fisheye`↔`family_room` per footage-audit dedup rules.)
- Any single camera reading > 1 person steadily while footage shows 1? Then camera-side (Frigate zones/masks) config, not URA.

### P-D4 — Replay gate (after D1/D2/D3 land)
Re-run `scripts/probes/census_d0/census_estimator_replay.py`. Compare G1–G9 to baseline in `AUDIT_census_estimator_replay_2026_10_03_hybrid.md`. Score with the **corrected truth** (midday guest band = 0, not 0–1).

**Each probe's report lives in `scripts/probes/census_d0/out_<probe>_<date>.md` and is cited back in the deliverable's acceptance.**

---

## 3. Deliverables (ordered)

### D1 — Door-event quality (per-door camera grouping + per-door interior-neighbours + knob'd dedup)

**Tier:** 2-DB (writes `person_entry_exit_events` with new direction semantics; cross-coordinator ripple into estimator + presence → three framing-disjoint reviews per standing policy).

**Prereq:** P-D1 report in-plan.

**Changes:**
1. `transit_validator.py:1736` — replace inline `5.0` with `DOOR_STEM_DEDUP_S` (module constant, `const.py`, default 30 s). Rung = module constant per `Numbers-Get-Knobs` (ledger-shape change → review-gated).
2. `transit_validator.py:1955-1963` — delete `_get_interior_cameras_near` returning ALL cams; replace with lookup against `CONF_DOOR_INTERIOR_NEIGHBOURS[door_group]`. Fall back to `[]` → direction = AMBIGUOUS when unmapped (do NOT silently return all cams).
3. `transit_validator.py:1724-1758` `_resolve_direction` — resolve `egress_camera_id → door_group` via `CONF_DOOR_GROUPS`; stem-dedup across **all cameras in the door_group** (not just same-stem) over `DOOR_STEM_DEDUP_S`; consult `CONF_DOOR_INTERIOR_NEIGHBOURS[door_group]` for direction nearby-cams; AMBIGUOUS when neighbours unmapped or none in window (estimator §4.3 P-AMB handles downstream — NOT shipped here).
4. NEW config field `CONF_DOOR_INTERIOR_NEIGHBOURS` in options flow (per-install, rung-2). Oracle household (set at install time, not baked in code): `{"front": ["foyer_fisheye", "family_room"], "garage_a": ["staircase"], "garage_b": ["staircase"]}`.
5. NEW config field `CONF_MAIN_ENTRY_DOOR` (Select, options derived from `CONF_DOOR_GROUPS` keys, rung-2) — oracle = `garage_a`.
6. **`doorbell_lite` disposition:** operator ruling 2026-10-04 = **`garage_a`** on this install. Code consumes `CONF_DOOR_GROUPS` — operator sets the group once in options flow; no household string baked in code.

**Knobs:**
- `DOOR_STEM_DEDUP_S` — module constant, default 30 s. (Module rung = ledger-shape change requires review.)
- `CONF_DOOR_INTERIOR_NEIGHBOURS` — options-flow (per-install).
- `CONF_MAIN_ENTRY_DOOR` — options-flow Select (per-install).

**Acceptance:**
- **Verify:** `grep -n "5.0" transit_validator.py` at the stem-dedup site returns 0 hits post-change.
- **Verify:** `_get_interior_cameras_near` no longer returns `self._interior_entities` wholesale.
- **Verify (data, corrected truth):** on the 10-03 replay 12:00–13:30, EVERY surviving ledger crossing has a resident `person_id` OR a resident tracker edge within the configured window (per P-D2 budget). Any residual unattributed crossings in that window are limited to the documented P-D2 Path-β class (at-home operator crossings with no tracker edge).
- **Verify (data):** on the 10-03 replay, surviving `front`-door entries in 14:10–14:40 ≥ 2 (two cameras per door merged; one logical arrival event survives round-trip pairing — full 6-of-8 deferred to D7).
- **Verify (data):** `garage_a` crossings in `person_entry_exit_events` reduce by ≥ 30% vs baseline (58 sub-5s duplicates gone; 5–30 s band collapses).
- **Test:** `test_door_group_stem_dedup_30s_collapses_cross_camera_legs`; `test_resolve_direction_uses_configured_neighbours_not_all_interior`; `test_resolve_direction_ambiguous_when_neighbours_unmapped`; `test_main_entry_door_select_derived_from_door_groups_keys`; `test_doorbell_lite_maps_to_garage_a_per_conf_door_groups`.
- **Live (post-deploy):** at the next real resident entry at `garage_a`, ledger has one entry (not two cross-leg dupes) with the expected direction.
- **Discriminating observation:** if post-D1 the ledger produces FEWER crossings for a real resident entry at the main door, dedup over-reach. Test: single resident physical entry → exactly 1 ledger row, direction=entry.

### D2 — Resident attribution / BLE departure provenance (verify-first, then narrow fix)

**Tier:** 1 if P-D2 shows the v5.96.0 producer attaches correctly in production and the 10-03 replay missed because of a replay-side gap. Tier 2 if P-D2 shows a producer-side regression (hotfix on `camera_census.py:3676-3737`).

**Prereq:** P-D2 report in-plan — **with corrected truth** (every midday crossing is a resident, not a visitor).

**Changes (contingent on P-D2):**
- **Branch A (replay-side only):** teach `scripts/probes/census_d0/census_estimator_replay.py` to consume `person_entry_exit_events.person_id` AND replay the `_on_person_state_change` tracker-edge logic (not just `person.state`). No production code change.
- **Branch B (producer-side regression):** if operator / Jaya phone edges fire within ±900 s but not ±300 s on the ~12:00 `garage_a` departure, widen `RESIDENT_CROSSING_MATCH_S` upward (knob move, module const or options-flow depending on review) with the P-D2 histogram as evidence.
- **Branch C (producer-side gap):** if the allowlist for operator/Jaya/Ezinne is wrong, correct `EGRESS_CROSSING_ADMISSIBLE_TRACKERS` (`const.py`). Security review per the shipped card's A-HIGH-1 (stationary tablet forgery) constraint.
- **Branch D (at-home operator wandering — Path-β residual):** if the operator porch-cleaning crossings have NO tracker edge at any window (operator never left home), DOCUMENT the known gap. Options to be scoped as a FOLLOW-UP card, NOT this cycle: (i) resident-at-room BLE presence as corroborator; (ii) `front` main-entry prior widening when operator tracker is `home` (not useful since the prior is for returning residents); (iii) accept the residual and lean on empty-anchor erasure. **This cycle does not ship a new producer** — Path-β gets a card.

**Knobs:**
- `RESIDENT_CROSSING_MATCH_S` — currently 120 s in replay / shipped producer uses its own window. If widened → named module constant.

**Acceptance:**
- **Verify (data, corrected truth):** on the 10-03 replay, the ~12:00 `garage_a` departure attributes to operator AND Jaya (both residents counted out) with `person_id` ≠ null OR tracker-edge match within the final chosen window. If this fails, D2 blocks on Branch B/C.
- **Verify:** `T` at 13:00 falls from 10 → ≤ P-D2's Path-β budget (expected ≤ 2 if operator-porch-cleaning is the only irreducible class, else 0).
- **Test:** `test_resident_tracker_edge_within_match_window_attributes_crossing`; `test_tracker_stationary_during_crossing_leaves_t_increment` (negative — stationary tablet does NOT attribute); `test_two_residents_leaving_by_car_both_attribute_to_single_crossing`.
- **Live:** on the next real `garage_a` resident entry/exit, `person_entry_exit_events.person_id` is non-null.
- **Discriminating observation:** if post-D2 `T` falls but **resident tracker-attributed crossings decrease**, over-attribution (allowlist too wide → stationary tablet forging crossings). Test: `study_a_wall_tablet` flipping state must NOT attribute any crossing.

### D3 — Interior camera over-count (10:00–11:15 inflation)

**Tier:** 1 (config-only on this install; code-only if a new overlap pair surfaces).

**Prereq:** P-D3 report in-plan.

**Changes (contingent on P-D3):**
- **If `foyer_fisheye`↔`family_room` overlap confirmed (likely per footage-audit dedup rules):** add that pair to `CONF_INTERIOR_CAMERA_OVERLAP_GROUPS` on this install. Code side = `_calculate_house_census` per-area max consumes configured groups.
- **If any camera reads > 1 person steadily while footage shows 1:** camera-side Frigate zones/masks fix, not URA code. Document the camera config change.
- **If `foyer_fisheye` and `upstairs_hall` are dead or noisy (AUDIT §1.3: 27 and 39 min/8d):** remove from `CONF_CAMERA_PERSON_ENTITIES` on this install. Config action, documented.

**Knobs:**
- `CONF_INTERIOR_CAMERA_OVERLAP_GROUPS` — per-install (set via per-install const in this cycle; options-flow field UX deferred).
- `CONF_CAMERA_PERSON_ENTITIES` — existing options-flow (per-install).

**Acceptance:**
- **Verify (data):** on the 10-03 replay 10:00–11:15, `M_cam` ≤ 3 (= R_home); `S(t)` never exceeds R_home in that window.
- **Verify:** G5 ≥ 90% in the re-replay.
- **Test:** `test_interior_overlap_pair_dedup_per_area_max`; a probe-anchored test asserting the overlap pair reads once.
- **Live:** next 3-residents-home-no-guest window, `sensor.universal_room_automation_persons_in_house` tracks resident count ±1.
- **Discriminating observation:** if G5 improves but G2 regresses, over-dedup. Test: 2-camera 2-person physically-separate scene sums to 2, not 1.

### D4 — Re-run D0-REPLAY as the exit criterion

**Tier:** none (read-only).

**Prereq:** D1 + D2 + D3 landed and verified.

**Action:** re-run `scripts/probes/census_d0/census_estimator_replay.py` HYBRID + VARIANTS against 2026-10-03 with new inputs AND corrected truth (`h_truth()` midday band = 0, not 0–1). Write to `AUDIT_census_estimator_replay_2026_10_03_hybrid_rerun.md`.

**Exit criterion (go/no-go on the hybrid D3 shadow build in `PLANNING_census_occupancy_estimator.md`):**
- **GO** if **G2 ≥ 95% AND G3 ≥ 90% AND G5 ≥ 90% AND no regression on G1/G7/G8/G9** AND `T` at 12:00–13:30 = 0 (modulo documented Path-β residual from D2).
- **NO-GO** otherwise → which input is still wrong? Which deliverable missed? Cycle back.

**Discriminating observation vs baseline failure:** baseline failed G2/G3/G5. If any ONE still fails post-fix, we know exactly which input is still faulty (G2/G3 point at T; G5 points at `M_cam`). Failure modes do not alias.

---

## 4. Non-goals (explicit)

- **No hybrid estimator code here.** D3 shadow stays in `PLANNING_census_occupancy_estimator.md`; this plan only unblocks it.
- **No P-AMB promotion logic ships here** — estimator §4.3 unchanged.
- **No GUEST-state migration (D5) or FLOOR→total_persons (D6).**
- **No D7 (vision group count).** 14:22 arrival's 8-vs-2 recovery stays parked.
- **No face-feed resolver fix (R1 in subsystem audit).** Carded as `CENSUS-FACE-RESOLVER-MIGRATE-1`.
- **No `TRANSIT-1` traversal checkpoint changes.** Shipped v5.60.0; out of scope.
- **No new producer for at-home-operator-wandering attribution.** Path-β from D2 goes to a follow-up card.

---

## 5. Tier classification summary

| Deliverable | Tier | Reviews | Why |
|---|---|---|---|
| D1 | 2-DB | 3 framing-disjoint + live | writes `person_entry_exit_events` with new direction semantics; cross-coordinator ripple. |
| D2 Branch A | — | n/a | script-only. |
| D2 Branch B/C | 1 or 2 | per branch | producer-side; security review for allowlist edits. |
| D2 Branch D | — | planning (card out) | Path-β irreducible without new input — follow-up card. |
| D3 (config) | — | documented | per-install. |
| D3 (overlap-pair plumbing) | 1 | 1 pass | additive. |
| D4 | — | read-only probe | exit gate. |

---

## 6. Open operator questions

- **Q-1:** `doorbell_lite` → `garage_a` on this install per operator ruling 2026-10-04. Confirm via P-D1 output (expect `doorbell_lite` 23:25/23:30 fires co-occurring with `garage_a`, not `front_door_aerial` / `madrone_g6_entry`).
- **Q-2:** Remove `foyer_fisheye` and `upstairs_hall` from `CONF_CAMERA_PERSON_ENTITIES` on this install (effectively noise per AUDIT §1.3)? Config-only.
- **Q-3:** Default for `DOOR_STEM_DEDUP_S` — 30 s per audit §1.3. Confirm.
- **Q-4:** Path-β acceptance budget — how many at-home-operator-wandering unattributed crossings per day is acceptable before we build a new resident-presence producer (follow-up card)? Needs P-D2 numbers to answer.

---

## 7. Verification steps (plan review, pre-build)

Per `CLAUDE.md` Plan Review (Tier 2+ gets ONE adversarial plan review before build dispatch):
- Grep: `grep -n "_get_interior_cameras_near\|_resolve_direction\|_last_resolved\|person_entry_exit_events" custom_components/universal_room_automation` — confirm no site beyond D1's enumeration is affected.
- Confirm `CONF_DOOR_GROUPS`, `CONF_EGRESS_CAMERAS`, `CONF_INTERIOR_CAMERA_OVERLAP_GROUPS` existence against current `config_flow.py` / `options_flow.py` / `const.py`. If `CONF_INTERIOR_CAMERA_OVERLAP_GROUPS` is NOT a real options-flow field, ship via per-install const in D3; do not block on UX.
- **Verify the shipped `EGRESS-BLE-PROVENANCE-GATE-DROPS-DEPARTURES-1` producer is attaching legs in production RIGHT NOW** (live counter on running HA). If 0 since 2026-09-11, D2 shifts from Branch A to Branch B/C and Tier climbs.
- P-D1/P-D2/P-D3 must be <5 min wallclock and read-only.

---

## Changelog
- 2026-10-04: initial draft.
- 2026-10-04 (same day, mid-plan): operator truth correction integrated — NO drop-off visitor on 10-03; midday is pure resident activity (porch cleaning + car departure); guest band 12:00–13:30 = 0; INV-INPUTS clause (d) added; D1 acceptance for midday ledger rewritten; D2 split into Branches A–D with the hard "at-home operator wandering" Path-β class made explicit.
