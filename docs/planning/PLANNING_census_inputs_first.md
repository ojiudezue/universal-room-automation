# PLANNING — Census INPUTS first (fix producers, then re-run D0-REPLAY)

**Status:** DRAFT 2026-10-04 (not committed). Not shipped. No code changes by this document.
**Author:** ura-planner.
**Operator ruling (2026-10-03):** "Fix census INPUTS before building the hybrid estimator, then re-run D0-REPLAY." The hybrid formula in `PLANNING_census_occupancy_estimator.md` is accepted — but D0-REPLAY (`AUDIT_census_estimator_replay_2026_10_03_hybrid.md`) returned **NO-GO** on gates G2/G3/G5 because the INPUTS it was fed were themselves wrong.
**Operator truth correction (2026-10-04, mid-plan):** there was **NO separate drop-off visitor on 10-03**. The earlier "drop-off guy" in the hybrid audit was a voice-dictation of "drop off Jaya." Corrected ground truth for midday:
- The **12:00–13:30 front-door burst = operator porch-cleaning ONLY** (resident, net 0, no visitor leg).
- The **~12:00 `garage_a` departure = operator + Jaya leaving by car** to drop Jaya off (two residents, both out). The audit's open item about 12:08–12:49 `garage_a`/`garage_b` crossings during Ezinne's 12:19–12:57 tracker gap is reframed: those crossings belong to the operator (and in one case operator+Jaya), not a visitor.
- **Guest band for 12:00–13:30 is 0, not 0–1.** Any `T > 0` in that window is a pure attribution failure.
- **NOTE (Rev 2):** probe-measured trackers disagree with this timeline — likely ~12:13 = Ezinne (not operator+Jaya); operator+Jaya likely ~13:55. See R2.6/OP-1 — PENDING OPERATOR CONFIRMATION.
**Supersedes:** nothing. **Depends on:** none in-flight. **Unblocks:** D3 shadow in `PLANNING_census_occupancy_estimator.md`.
**Canonical reference (mandatory read):** `docs/Coordinator/IDENTITY_FUSION_CAMERAS_MANUAL.md` (platform roles, `_2`-suffix rules, egress-identity JOIN, 6.0.0 identity-driven autonomy gate).
**Also read:** `PLANNING_census_occupancy_estimator.md` (esp. §4.3, §12 last-operator blocks), `AUDIT_census_estimator_replay_2026_10_03_hybrid.md`, `AUDIT_census_subsystem_2026_10_04.md`, `AUDIT_census_footage_ground_truth_2026_10_03.md`.

---

## 0. One-page summary

D0-REPLAY failed because:
- **G2/G3 (floor soundness, household-norm):** the door tally (`T`) over-counted guests at midday on **pure resident activity** (operator porch-cleaning at `front`; operator+Jaya leaving by car at `garage_a`). None of {resident `person_id`, resident tracker edge within ±300 s, main-entry prior} caught them, so 11 `garage_a` crossings reversed into T and the front-door burst produced several unattributed entries. **The midday guest-band truth is 0** — every T>0 minute between 12:00 and 13:30 is a false positive sourced by missing resident attribution, not by a real visitor.
- **G5 (resident-only morning):** `M_cam` read 4–5 bodies 10:00–11:15 with only 3 residents home and the long-stay guest OUT — an interior-camera over-count defect, not an estimator defect. **(Rev 2: probe refuted this — live census read 3; the "4–5" was a 1200 s-max-hold replay artefact. See R2.4 — D3 DROPPED.)**
- **8-person 14:22 arrival collapsed to 1 ledger entry:** two cameras per door merged correctly, but same-door-group same-direction legs within the 180 s round-trip window + 30 s stem dedup collapsed 8 real bodies into 1 logical crossing. `front_door_aerial` only peaked at 6 of 8 concurrent faces — full multiplicity recovery is unrecoverable without a distinct-person group window and (eventually) D7 vision counting.

**The INPUTS, not the formula, are the scope.** This plan fixes door-event quality (D1), BLE departure provenance / resident attribution (D2), and interior camera over-count (D3). Only then (D4) does D0-REPLAY re-run as the exit gate. **(Rev 2: D3 dropped; see R2.4.)**

**Falsifiable program invariant for this plan:**
> **INV-INPUTS:** on a replay of 2026-10-03 with D1+D2+D3 landed, (a) G5 ≥ 90% (resident-only morning false-positive ≤ 10%), (b) G2 ≥ 95% and G3 ≥ 90% (truth-bounded in household-norm windows), (c) the 14:22 front-door arrival produces ≥ 2 surviving logical entries post-pipeline (full 6-of-8 recovery parked to D7), AND (d) `T` is 0 for the entire 12:00–13:30 window (zero false-positive guests on pure-resident activity, per the corrected truth).

**(Rev 2 note on INV-INPUTS (c): DROPPED — multiplicity-via-row-count is unrecoverable; replaced by `peak_person_count` column, see R2.2 item 8.)**

**(Rev 3 note: INV-INPUTS replaced in full by the consolidated INV-INPUTS-R2 in R3.5. G5 removed from the gate per probe (R2.4).)**

Discrimination: a passing run under the OLD inputs is impossible; a failing run under the NEW inputs tells us which of D1/D2/D3 missed. (d) specifically discriminates attribution failure (D2) from pipeline failure (D1): if `T` is still > 0 at 12:00–13:30 but every midday crossing now carries a resident `person_id` or edge, D1 is wrong (pipeline not counting attributed-residents as attributed); if crossings still have no `person_id`/edge match, D2 is wrong.

---

## 1. Institutional context verified

### 1.1 Prior-art scan — REUSE / FIX / NEW (file:line)

**(Rev 2: multiple REUSE verdicts below were WRONG — see R2.1 for corrections. The table is kept for history.)**
**(Rev 3: Rev-2/Rev-3 verdicts live in R2.1 (prior-art corrections), R3.3 (`_extract_camera_stem` REUSE), R3.7 (`CONF_MAIN_ENTRY_DOOR` deferred). This table is history; see R3.12.)**

| Piece | Verdict | Evidence |
|---|---|---|
| `TransitValidator._resolve_direction` | **FIX** | `transit_validator.py:1724-1758`. Direction depends on `_get_interior_cameras_near`. |
| `_get_interior_cameras_near` returning ALL interior cams | **FIX** | `transit_validator.py:1955-1963`. Degenerate: any interior fire anywhere → direction=entry. |
| Stem dedup inline literal `5.0` | **FIX** (knob + widen) | `transit_validator.py:1736`. Replace with `DOOR_STEM_DEDUP_S` (default 30 s per `AUDIT_census_subsystem_2026_10_04.md` §1.3: 58/143 dupes <5 s but a 5–30 s band exists). |
| Per-door camera grouping | **FIX** (consume per-install config) | `CONF_DOOR_GROUPS` already exists per `PLANNING_census_occupancy_estimator.md` §4.3; `_resolve_direction` does not yet key off it. **(Rev 2: WRONG — CONF_DOOR_GROUPS does NOT exist. NEW. See R2.1.)** |
| `CONF_MAIN_ENTRY_DOOR` (per-install) | **REUSE from estimator plan §4.6** | Options derived from `CONF_DOOR_GROUPS`; oracle household = `garage_a`. **(Rev 2: NEW — derived from a NEW field.)** **(Rev 3: DEFERRED to estimator cycle; no consumer here — R3.7.)** |
| `CONF_DOOR_INTERIOR_NEIGHBOURS` | **NEW** (per-install, options-flow rung-2) | Per-door nearby-interior-cam map; grep repo-wide — no existing symbol. |
| BLE/GPS departure provenance | **ALREADY SHIPPED** (verify-only here) | Card `EGRESS-BLE-PROVENANCE-GATE-DROPS-DEPARTURES-1` status=done, shipped v5.96.0. Live counter `ble_exit_backfilled_count=4` on 2026-09-11. **D2 CONFIRMS it is attaching resident legs on the 10-03 replay.** If the midday operator-cleaning + operator+Jaya `garage_a` crossings have NO phone edges within any window on 10-03, the producer did not fire — regression on a shipped feature. |
| `camera_census.py:_calculate_house_census` per-area max | **REUSE** | `camera_census.py:1690`. The interior over-count fix (D3) extends `CONF_INTERIOR_CAMERA_OVERLAP_GROUPS` (per-install) rather than touching this. |
| `CONF_INTERIOR_CAMERA_OVERLAP_GROUPS` | **REUSE from estimator plan §5.2** | Oracle household measured pair: `{family_room, master_hallway}` J=0.56. The footage audit's dedup rule (`foyer_fisheye` sees family_room floor-edge) suggests a second pair P-D3 should confirm. **(Rev 2: WRONG — does NOT exist. NEW. Moot — D3 dropped.)** |
| Interior camera entity list | **FIX (config)** | `CONF_CAMERA_PERSON_ENTITIES` `const.py:1973`. Candidate removals: `foyer_fisheye`, `upstairs_hall` (D0 §P4: 27 / 39 min-with-count>0 across 8 days — effectively noise, likely a source of G5 over-count). Config only — no code. **(Rev 2: refuted — foyer_fisheye is SILENT not noisy; removal unsupported.)** |
| Hold / decay | **UNCHANGED** | `_apply_hold_decay` `camera_census.py:5026`. |

### 1.2 Prior planning / audit docs consulted
`PLANNING_census_occupancy_estimator.md` (full), `AUDIT_census_estimator_replay_2026_10_03_hybrid.md` (full), `AUDIT_census_subsystem_2026_10_04.md` (full), `AUDIT_census_footage_ground_truth_2026_10_03.md` (full), `AUDIT_exterior_camera_adjacency_probe.md` (method reference for D3 overlap probe).

### 1.3 Memory bodies relevant
`reference_frigate1_retired_2suffix_permanent` (`_2` suffix on Frigate 2 must be honoured by any new resolver), `reference_protect_face_latency_async` (back-fill expectations when validating attribution), `reference_egress_face_coverage_7pct_not_a_ceiling` (face attach is corroborator, not FLOOR input), `project_single_user_no_backcompat` (CHANGING: 2nd install 10-03/04 — all new config is per-install, degrades gracefully if unset).

### 1.4 Code surveyed (end-to-end for scoping)
`custom_components/universal_room_automation/transit_validator.py` 795-834, 1167, 1700-1980; `camera_census.py` 1521-1700, 1690, 1955, 3192-3263, 3676-3740, 4531, 5026, 5198-5381; `const.py` 1973, 2307, 2373, 3528, 3544, 3638; `database.py` 793-808. Kanban: `EGRESS-BLE-PROVENANCE-GATE-DROPS-DEPARTURES-1` (done v5.96.0 — but see D2 verify-first), `CENSUS-ACCURACY-1`, `CENSUS-FACE-RESOLVER-MIGRATE-1`, `CENSUS-GHOST-DEDUP-1` (done), `TRANSIT-1` (checkpoints shipped v5.60.0 — not in scope).

**(Rev 3 refresh, see R3.0):** re-verified on develop end-to-end — `transit_validator.py` 1162-1165, 1235-1245, 1253, 1258, 1363, 1724-1803, 1812, 1840-1866, 1874-1887, 1906-1907, 1955-1963, 1975, 2001-2008; `camera_census.py` 712-720, 797, 859, 4360, 4411, 4497-4555; `camera_resolver.py` 214-270, 291-312, 317; `const.py` 1973, 2795; `database.py` 4041-4066, 4068, 4099, 4137-4177, 972/1819/1957/2012/2057 (ALTER TABLE precedent); `sensor.py` 4518, 4559, 4580, 4661, 4693, 4711, 4765, 4803, 4821, 4851, 4869.

### 1.5 Config-first check (ura-kanban gate step 1b)
- `CONF_CAMERA_PERSON_ENTITIES` is already a live config — D3's `foyer_fisheye` / `upstairs_hall` removal may be a pure config action. **Test as a config-only variant before writing D3 code.** **(Rev 2: refuted; D3 dropped.)**
- `CONF_INTERIOR_CAMERA_OVERLAP_GROUPS` (per-install options-flow field per estimator §5.2) does not yet exist as an options-flow field. For this cycle: set per-install in a const / YAML; defer UX to the estimator cycle. **(Rev 2: moot — D3 dropped.)**
- `CONF_DOOR_GROUPS` already exists and is populated. `CONF_DOOR_INTERIOR_NEIGHBOURS` is NEW and REQUIRED by D1. **(Rev 2: WRONG — CONF_DOOR_GROUPS is NEW, not populated. R2.1.)**
- No knob fixes the dead-attribution problem (D2 is code or data-side). **(Rev 2: refined — one operator-side config action IS available: re-point `person.oji_udezue` away from `okosisipadmini6_2` stationary iPad; see R2.3.)**

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

**(Rev 3 extension — BUILD GATE per R3.2):** P-D1 MUST also publish the **before/after AMBIGUOUS fraction** on 10-03 under the new `_resolve_direction` + neighbours wiring, in two variants: (a) `CONF_DOOR_INTERIOR_NEIGHBOURS` unset (R3.1 fallback — expected delta = 0), and (b) oracle household map filled. If (b) raises AMBIGUOUS by more than X pp (reviewers set X from measured baseline), the oracle neighbour lists must be widened before build dispatch.

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

**(Rev 2: §3.D1 items 1–6 REPLACED by R2.2; §3.D2 Branches A–D REPLACED by R2.3; §3.D3 DROPPED per R2.4. Original text kept below for history.)**
**(Rev 3: see R3.1 (CRITICAL-1 fallback), R3.3 (HIGH-2 REUSE/callers), R3.4 (HIGH-3 producer-already-ships), R3.6 (`peak_person_count`), R3.7 (`CONF_MAIN_ENTRY_DOOR` deferred), R3.9 (dedup-keep-first), R3.11 (fixture renames).)**

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

**(Rev 2: D3 rows DELETE per R2.4.)**

---

## 6. Open operator questions

- **Q-1:** `doorbell_lite` → `garage_a` on this install per operator ruling 2026-10-04. Confirm via P-D1 output (expect `doorbell_lite` 23:25/23:30 fires co-occurring with `garage_a`, not `front_door_aerial` / `madrone_g6_entry`). **(Rev 2: CLOSED by probe.)**
- **Q-2:** Remove `foyer_fisheye` and `upstairs_hall` from `CONF_CAMERA_PERSON_ENTITIES` on this install (effectively noise per AUDIT §1.3)? Config-only. **(Rev 2: DROPPED — probe refuted.)**
- **Q-3:** Default for `DOOR_STEM_DEDUP_S` — 30 s per audit §1.3. Confirm.
- **Q-4:** Path-β acceptance budget — how many at-home-operator-wandering unattributed crossings per day is acceptable before we build a new resident-presence producer (follow-up card)? Needs P-D2 numbers to answer. **(Rev 2: probe measured ≈3–4/day.)**

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
- 2026-10-04: Probe results (P-D1/P-D2/P-D3) appended below.
- 2026-10-04 (Rev 2): post-probe + post-plan-review revision appended. See "Revision 2" section below (supersedes conflicting §1.1/§3/§5/§6 claims).
- 2026-10-05 (Rev 3): post plan-review PLAN-FIX-REQUIRED revision appended. See "Revision 3" section (supersedes R2.2/R2.3/R2.5/R2.6 where in conflict).

---

## Probe results (2026-10-04, read-only, 10-03 CDT)

Scripts + raw output: `scripts/probes/census_inputs/` (`p_d1_door_forensics.py`, `p_d2_attribution.py`, `p_d3_interior_overcount.py`, `out_p_d*_2026_10_03.txt`). Each ran in <1 s against `?mode=ro` recorder + URA DB.

### Plan-premise corrections the probes surfaced (read these first)
1. **`CONF_DOOR_GROUPS` does not exist.** `grep -rn DOOR_GROUPS custom_components/` → 0 hits; not in the live config entry. Same for `EGRESS_CROSSING_ADMISSIBLE_TRACKERS` and `RESIDENT_CROSSING_MATCH_S` (0 hits). §1.1 "already exists and is populated" is wrong. D1 must add the door-group map (NEW), D2 Branches B/C name symbols that don't exist. The shipped BLE exit-backfill uses `BLE_EGRESS_EXIT_BACKFILL_WINDOW_S` + live `source_type == bluetooth_le` filter (`camera_census.py:3967-4070`, `4360-4470`).
2. **Truth timeline vs trackers disagree on the car departure.** Trackers (all three BLE legs agree): **Ezinne** out 12:18–12:19 → back 12:57; **operator + Jaya** out together 14:01:45 (Bermuda) / 14:03:44 (private_ble), back 15:42 (operator) / 23:28 (Jaya). The ledger agrees with the trackers: `garage_a`/`doorbell_lite` exits pid=`ezinne` 12:13–12:14, and exits pid=`oji_udezue`+`jaya` at **13:55:29**. So the "~12:00 operator+Jaya leave by car" is most likely **~13:55**, and the ~12:13 `garage_a` departure is **Ezinne** (operator trusts her phone). **Operator to confirm** before D2/G2–G3 scoring uses it. (Jaya had an all-day `person.jaya=home` until 14:03 — she could not have left at 12:00 per any of her three trackers.)
3. **G5 "M_cam 4–5" is a replay artefact, not a camera defect.** The live `sensor.universal_room_automation_persons_in_house` read **3** at 262/263 state rows 10:00–11:15. The replay's `M_cam` is a sum across components held at a 1200 s windowed max (`census_estimator_replay.py:151-162`); instantaneous camera-sum >3 occurs only **22/300 grid points (7.3%)**. The 20-min max-hold promotes brief cross-camera double counts (people moving family_room → stairs/halls) into a sustained 4–5.

### P-D1 — Door-event forensics
**10-03 ledger:** 165 rows; 35 with `person_id` (jaya 15, oji 12, ezinne 7, ojini 1). Raw egress on-edges (all sensor families): 451.

**Why the 14:22 8-person front arrival became 4 entry / 2 exit rows — it is all three, in this order:**
| Stage | Evidence | Effect |
|---|---|---|
| **Producer (dominant, unrecoverable in URA)** | Each egress sensor triggers only on a **0→N** edge (`transit_validator.py:1100-1110`) — one trigger per sensor per occupancy episode regardless of count. Peak `person_count`: `front_door_aerial` **4**, `madrone_g6_entry` **2**, `doorbell_lite` none. Each camera had exactly **one** on-episode 14:24:12–14:25:31. | The signal never carries more than 4 bodies; the ledger never carries count at all. Distinct-peak test: **1 episode, ≤4 peak → < 6 ⇒ a 120 s distinct-person group window CANNOT recover the group.** Only count-aware ledger rows (peak count per episode) or D7 vision can. |
| **Stem dedup (makes it worse, not better — it fails open)** | The 6 rows are 6 *sensor entities* of 2 cameras, one row each: `aerial_person_detected`, `g6_person_detected`, `g6_person_count`, `g6_person_occupancy_2`, `aerial_person_count`, `aerial_person_occupancy_2`. `_extract_camera_stem` (`camera_census.py:873`) strips `_person_occupancy` but **not `_person_occupancy_2`** → returns `None` → **dedup skipped** for every Frigate-2 occupancy leg (Bug: `_2`-suffix, memo `reference_frigate1_retired_2suffix_permanent`). Count legs that *do* stem-match are 12–24 s after the binary leg, outside the 5 s window. | Duplicate pairs are near-universal across the day (see midday/late tables). |
| **Direction resolution** | The 2 "exit" rows are the aerial count/occ_2 legs (trigger 14:24:36, resolved +45 s). `_get_interior_cameras_near` returns ALL interior cams (`transit_validator.py:1955-1963`); family_room alone had **811** on-edges on 10-03. The resolve loop iterates interior times oldest-first, so any fire in the prior 30 s (exit window) wins over a later one (entry window). | Direction ≈ "was any interior cam busy in the 30 s before"; with family_room near-continuous it is effectively random. |

**Dedup simulation on raw legs (survivors by door):**
| W | stem: front / garage_a / garage_b | door_group: front / garage_a / garage_b |
|---|---|---|
| 5 s | 44 / 119 / 9 | 32 / 106 / 9 |
| 15 s | 41 / 99 / 6 | 25 / 78 / 6 |
| 30 s | 35 / 80 / 5 | 21 / 61 / 5 |
| 60 s | 29 / 61 / 4 | 16 / 43 / 4 |
Door-group dedup at 30 s cuts `garage_a` 119→61 (−49%) vs today's 5 s stem — clears D1's "≥30% reduction" bar, *provided the `_2` stem bug is fixed* (otherwise occupancy_2 legs bypass dedup entirely).

**Midday 11:30–13:45 bucket table** (ledger rows; tracker edges include all 3 residents' BLE+GPS legs):
- 12:03–12:14 (`garage_a`/`doorbell_lite`, 13 rows + front 12:06–12:10, 13 rows): 9 carry `person_id` (oji ×4, jaya ×3, ezinne ×3) — **bucket (a)** for the rest: Ezinne's 12:18–12:19 departure edge is within ±300–900 s. Consistent with **Ezinne leaving by car ~12:13** (truth correction #2).
- 12:38–12:42 `garage_a`/`doorbell_lite` 6 entry rows: **bucket (b) — no resident tracker edge at any window** (Ezinne out, operator+Jaya home and stationary). Path-β class at `garage_a`, not `front`.
- 12:44–13:09 `garage_a` + front 13:02–13:03 (16 rows): **bucket (a)** at ±300/900 s via Ezinne's 12:57 arrival edge; 3 rows pid=ezinne.
- **Bucket (c) (pid on row but pipeline counted unattributed): not observable from the ledger; it is a replay/estimator-side question** — every attributed crossing also has an unattributed duplicate twin from the `_2`/5 s dedup failure, so any pipeline that counts rows rather than deduped crossings will see "unattributed" even when the crossing is attributed. Treat as D1 (dedup) not D2.
- Front-door porch burst (12:05–12:10, 13:01–13:03): no front-door-specific tracker edge (operator never left); operator Bermuda `sensor.iphone_oji_area` = `Receiving Room`/`Breakfast` at those rows.

**`doorbell_lite` 23:25 / 23:30:** co-fires with `garage_a` within 1–60 s on every occasion (23:24:18 / 23:25:05 / 23:25:25; 23:30:09 both); no front-camera fire 23:02→23:55. **Confirms `doorbell_lite` ∈ `garage_a` (Q-1 closed).** Also 13:54–13:57 and 15:43–15:44 co-fire with `garage_a`.

### P-D2 — Resident attribution
| Crossing | Truth (per trackers) | Edges | Ledger `person_id` |
|---|---|---|---|
| 12:13–12:14 `garage_a` exit | Ezinne out (car) | Ezinne BLE dep 12:18:24/12:19:04 (+4–5 min lag) | ezinne ×2, jaya ×1 (12:14:16 jaya mis-attach — Jaya was home per all 3 trackers) |
| 13:55 `garage_a` exit | operator + Jaya out (car) | **both** BLE dep 14:01:45 (Bermuda) / 14:03:44 (private_ble) — **+6–8 min lag** | oji ×1, jaya ×1 at 13:55:29 ✔ |
| 15:44 `garage_a` entry | operator in | BLE arr 15:42:29 (−2 min lead) | oji ×2 ✔ |
| 23:25–23:31 `garage_a` entry | operator + Jaya in | BLE arr 23:28:39/23:28:48 | **0 of 12 rows attributed** ✖ (edges within ±120–300 s) |
| front porch bursts | operator at home | none (never left) | oji ×1 (12:06:17), jaya ×2 (face) |

- **Per-hour attach:** 35/165 rows (21%); live `egress_identity_attach_rate_24h = 0.0625`. Attach is non-zero → **no producer regression** on the shipped BLE path; it is face (conf 0.9, 7 rows) + BLE/other (0.8, 28 rows).
- **GPS legs are useless here:** `phalanxiphone15promax` 1 state all day; `jjs_iphone` unavailable all day; `phalanxiphone15promaxcflare` flaps unavailable/not_home; `okosisipadmini6_2` (current `person.oji_udezue` source!) reads `not_home` while operator is home. BLE (`*_bermuda_tracker`, `private_ble_*`, `ezinne_iphone`) carries all real departures/arrivals.
- **Departure lag is the structural issue:** BLE `home→not_home` lands **+4 to +8 min after** the physical garage crossing (car drive-off → Bermuda timeout). ±300 s misses the 13:55 crossing for the private_ble legs; ±900 s catches all. Arrivals lead/lag ≤ 3 min.
- **Path α:** a per-room Bermuda signal exists (`sensor.iphone_oji_area`, 265 changes 11:30–13:45; also `sensor.iphone_jaya_area`, `sensor.ezinne_iphone_area`) but there is no front-door/porch area; at porch-burst rows it reads Receiving Room/Breakfast, and Jaya's area hops ≥6 rooms per minute. **Not a usable crossing corroborator** → Path β.

**D2 branch:** **A + D** (with a narrow B note).
- **A (replay-side):** replay must consume ledger `person_id` after crossing-level dedup and use a **departure window asymmetric to BLE lag** (e.g. edge ∈ [−180 s, +600 s] after the crossing for exits; ±180 s for arrivals). No producer regression found.
- **D (Path-β, documented gap):** budget for 10-03 = front porch bursts (2 episodes) + 12:38–12:42 `garage_a` (1–2 episodes) ⇒ **≈3–4 unattributable at-home episodes/day** after dedup. Card follow-up; no new producer this cycle.
- **B-note (producer):** the 23:25–23:31 return with operator+Jaya edges inside ±120–300 s got **0** backfilled rows — the shipped backfill is *exit*-only (`find_unnamed_exit_crossings`), and these rows are entries. Entry-side BLE attach is a separate, small gap (card it; not a regression). **(Rev 3 note: this is actually the `_2` stem bug per R3.4, not a producer gap — card REFUTED; entry-side BLE attach via `_resolve_ble_legs` already ships.)**
- C is moot: the named allowlist symbol does not exist.

### P-D3 — Interior over-count 10:00–11:15
| Camera | >0 | >1 | max |
|---|---|---|---|
| family_room | 99.7% | 43.7% | 4 |
| upstairs_hall | 25.7% | 4.0% | 2 |
| playroom | 14.0% | 1.7% | 2 |
| stairs_top | 7.3% | 0.3% | 2 |
| staircase | 6.3% | 0.3% | 2 |
| master_hallway | 5.3% | 0.3% | 2 |
| foyer_fisheye | 0.3% | 0.0% | 1 |
- Pairwise Jaccard (co-on/either): highest family_room↔upstairs_hall 0.26, ↔playroom 0.14; **foyer_fisheye↔family_room J=0.00 — the expected overlap pair is NOT confirmed** (foyer_fisheye barely fired). These co-occurrences are different people in different rooms (3 residents), not one person seen twice.
- When sum>3 (22 points), family_room averages 2.36 and some other cam has a mover. `family_room > 1` 44% of the time with 3 residents home is plausible footage-wise but is the one camera to spot-check for steady multi-count.
- **Live URA census = 3 throughout.** The over-count is the replay's sum-with-1200 s-max-hold, not production.

### GO / NO-GO
| Deliverable | Verdict | Why |
|---|---|---|
| **D1** | **GO — re-scoped.** | (1) Fix `_extract_camera_stem` to strip `_person_occupancy_2` (and `_active_count_2`) — the actual dedup leak; (2) door-group dedup at 30 s (−49% `garage_a`); (3) neighbours map + oldest-first exit bias in `_resolve_direction`. `CONF_DOOR_GROUPS` is NEW, not reuse. **Drop INV-INPUTS (c) "≥2 surviving entries recovers the group" as a D1 success criterion for multiplicity** — the producer peaked at 4/8 in one episode; record `peak person_count` per episode on the ledger row instead (small, additive) if multiplicity matters before D7. |
| **D2** | **GO — Branch A + D (Tier 1, replay-side + card).** | No producer regression; BLE lag is +4–8 min on departures → asymmetric window. Path-β budget ≈3–4 episodes/day. Card the entry-side BLE attach gap (23:25 return, 0/12). **Blocked on operator confirming truth correction #2 (car departure at ~13:55 by operator+Jaya; ~12:13 = Ezinne).** |
| **D3** | **NO-GO (code and config).** | Overlap pair unconfirmed (J=0.00); foyer_fisheye/upstairs_hall removal unsupported (foyer is silent, not noisy); live census correct at 3. Fix belongs in the replay/estimator `M_cam` definition (per-area max at an instant, short hold), i.e. the estimator plan, not an input fix. Optional: footage spot-check of family_room steady count=2–4. |

---

## Revision 2 (post-probe + post-plan-review, 2026-10-04) — SUPERSEDES §1.1, §2, §3, §5, §6 where in conflict

The probe results (previous section) and the plan review together invalidate several §1.1 claims and the D2/D3 scoping. This revision replaces them. Earlier text is kept above for history; where it conflicts with Revision 2, Revision 2 wins.

### R2.1 Prior-art corrections (REUSE → NEW)

The following were asserted REUSE in §1.1; greps now show they do not exist. All are **NEW**.

| Symbol | §1.1 claim | Truth (grep) | Verdict |
|---|---|---|---|
| `CONF_DOOR_GROUPS` | "already exists and is populated" | 0 hits in `custom_components/`; not in live config entry | **NEW** — add options-flow field (per-install) in D1 |
| `CONF_INTERIOR_CAMERA_OVERLAP_GROUPS` | "REUSE from estimator plan §5.2" | 0 hits in code; only referenced in planning docs | **NEW** (but D3 dropped — see R2.4) |
| `EGRESS_CROSSING_ADMISSIBLE_TRACKERS` | implied by D2 Branch C | 0 hits | **NEW** — no symbol to amend; Branch C moot |
| `RESIDENT_CROSSING_MATCH_S` | D2 Branch B knob name | 0 hits | **NEW** — if ever introduced, name it against the real producer's window |

**Real shipped BLE exit-backfill surface (verified in code):**
- Producer registration: `camera_census.py:4562` `_register_ble_transition_listeners`.
- Exit-backfill claim loop: `camera_census.py:~4395-4430`; writes `_ble_exit_backfilled_count` at `:4424`; DAO = `database.backfill_entry_exit_person_id`.
- Entry admission (BLE-near-door entry attach): `camera_census.py:~4498-4555`.
- Real knobs (all `const.py`): `BLE_EGRESS_EXIT_BACKFILL_WINDOW_S = 600` (`:2805`), `BLE_EXIT_DEPARTURE_SETTLE_S = 300` (`:2821`), `BLE_EXIT_CLAIM_MAX_ATTEMPTS` (`:2832`), `BLE_EXIT_PER_SLUG_COOLDOWN_S` (`:2839`).

### R2.2 D1 — Door-event quality (re-scoped per probe + review HIGH-1/HIGH-3/direction/group-size)

**Tier:** 2-DB (ledger-shape change: new NOT NULL-able column `peak_person_count` on `person_entry_exit_events` → three framing-disjoint reviews + migration).

**Prereq:** P-D1 report in-plan (done); operator confirmation of truth-correction #2 (R2.6) before writing acceptance scoring.

**Changes (replaces §3.D1 items 1–6):**

1. **Fix `_extract_camera_stem` (`camera_census.py:873`)** to strip `_person_occupancy_2` and `_active_count_2` suffixes. This is the actual dedup leak: Frigate-2 occupancy sensors bypass stem-dedup today because `_extract_camera_stem` returns `None`, so dedup is skipped. This single fix moves the needle more than any knob change. Memo cross-ref: `reference_frigate1_retired_2suffix_permanent`.
2. **`transit_validator.py:1736`** — replace inline `5.0` with `DOOR_STEM_DEDUP_S` (module constant, `const.py`, default 30 s). Module rung per `Numbers-Get-Knobs`.
3. **`transit_validator.py:1955-1963`** `_get_interior_cameras_near` — replace "return ALL interior cams" with lookup against `CONF_DOOR_INTERIOR_NEIGHBOURS[door_group]`. Unmapped → `[]` → direction = AMBIGUOUS (do NOT silently return all). **HIGH-2 note:** this helper has a **second caller** at `transit_validator.py:1253` (`_resolve_egress_face_identity`); the same contract change applies there — enumerate expected behaviour change in the test matrix (face resolution over the narrowed neighbour set).
4. **`transit_validator.py:1724-1758`** `_resolve_direction` — (a) resolve `egress_camera_id → door_group` via NEW `CONF_DOOR_GROUPS`; (b) stem-dedup across **all cameras in the door_group** (door-group scope, not per-stem; per-stem scope collapses the duplicate siblings but misses cross-camera physical duplicates — door-group default is the probe-supported choice: `garage_a` 119→61 at 30 s); (c) consult `CONF_DOOR_INTERIOR_NEIGHBOURS[door_group]`; (d) **correct ordering for exit bias:** current loop iterates interior fires oldest-first so any neighbour fire in the prior 30 s wins (family_room fired 811×/day → direction effectively random). Replace with newest-first within the per-door neighbour window, and tie `_last_resolved` 60 s prune (`transit_validator.py:2001-2008`) to `DOOR_STEM_DEDUP_S` (keep ≥ dedup window).
5. **NEW `CONF_DOOR_GROUPS`** — options-flow field (per-install). Maps `egress_camera_id → door_group` string. Default empty; unset → each camera is its own group (today's behaviour).
6. **NEW `CONF_DOOR_INTERIOR_NEIGHBOURS`** — options-flow field (per-install). Maps `door_group → list[interior_camera_id]`. Unset → AMBIGUOUS.
7. **NEW `CONF_MAIN_ENTRY_DOOR`** — options-flow Select, options derived from `CONF_DOOR_GROUPS` keys. Oracle household = `garage_a` (per operator ruling + probe-confirmed `doorbell_lite` co-fires).
8. **Group-size (replaces INV-INPUTS (c) / "≥ 2 surviving entries" test):** door handler currently fires on 0→N edge and discards headcount. Add DB column `peak_person_count INTEGER` (default 1) on `person_entry_exit_events`; populate from the max `sensor.<cam>_person_count` observed on the camera during the occupancy episode (bounded sample at episode start → stem-dedup window close). This is the honest group-size input and is the only non-D7 path to multiplicity. **Drop** the plan's earlier "≥ 2 surviving entries post-pipeline" acceptance — producer peaked at 4/8 bodies in one episode; multiplicity-via-row-count is unrecoverable.
9. **`doorbell_lite` disposition:** operator ruling + probe-confirmed → `garage_a` on this install, consumed via `CONF_DOOR_GROUPS` (no household string in code).

**HIGH-1 — ambiguous rows and backfill eligibility:** `database.backfill_entry_exit_person_id` today claims only `direction='exit'` rows (`database.py:~4120`). The new AMBIGUOUS direction MUST be defined as backfill-eligible for both directions, or we silently create rows the BLE producer cannot ever attach to. Decision for this cycle: **AMBIGUOUS rows ARE backfill-eligible on either direction when a resident edge lands within the asymmetric window.** P-D1 must publish the direction distribution under the new neighbours map before build dispatch (how many rows go AMBIGUOUS vs entry/exit) so reviewers can judge blast radius on readers. **(Rev 3: WITHDRAWN — false premise; AMBIGUOUS rows never persist. Replaced by R3.2 BUILD GATE on AMBIGUOUS fraction.)**

**Knobs (ladder):**
- `DOOR_STEM_DEDUP_S` — module constant (ledger-shape consequence; review-gated).
- `CONF_DOOR_GROUPS`, `CONF_DOOR_INTERIOR_NEIGHBOURS`, `CONF_MAIN_ENTRY_DOOR` — options-flow (per-install, rung-2).

**Consumer table (HIGH-2 — enumerate every reader of `person_entry_exit_events` / `_get_interior_cameras_near` / the egress event; verdict on behaviour-change):**

| Consumer | File:line | Reads | Change under D1 |
|---|---|---|---|
| `PersonsEnteredTodaySensor` | `sensor.py:4518`, `:4559`, `:4580` | ledger rows, direction=entry | Fewer dupes; AMBIGUOUS rows ignored today — define policy (count-as-entry? ignore? separate attribute?) |
| `PersonsExitedTodaySensor` | `sensor.py:4661`, `:4693`, `:4765` | ledger rows, direction=exit | Same AMBIGUOUS question |
| `LastPersonEntrySensor` | `sensor.py:4803` | last direction=entry | AMBIGUOUS skipped; verify |
| `LastPersonExitSensor` | `sensor.py:4851` | last direction=exit | AMBIGUOUS skipped; verify |
| `_arrival_departure_notify` | `transit_validator.py:~1810` | event stream; already skips ambiguous | Behaviour preserved (notify quieter when neighbours unmapped) |
| census register/evict | `camera_census.py:~1830+` | event stream | AMBIGUOUS → no register/evict today (safe-by-default); verify |
| `log_entry_exit_event` | `transit_validator.py:1879` | writes ledger | Add `peak_person_count` write |
| BLE exit backfill | `camera_census.py:~4395-4430` | ledger direction=exit | HIGH-1 — extend to AMBIGUOUS? decision above |
| BLE entry admission | `camera_census.py:4521` | ledger direction=entry | HIGH-1 — same |
| `_resolve_egress_face_identity` | `transit_validator.py:1253` | `_get_interior_cameras_near` | Narrower neighbour set; test resolver still finds the face |
| Event `ura_person_egress_event` | fired `transit_validator.py:1786` | downstream listeners | Carries direction; AMBIGUOUS downstream behaviour must be documented |

**(Rev 3 note:** the "BLE entry admission at `camera_census.py:4521` — ledger direction=entry" row is WRONG — `_resolve_ble_legs` is an in-memory resolver-time cache, not a ledger reader. See R3.0 and R3.2 for the corrected consumer map.)

**Acceptance (replaces §3.D1):**
- **Verify:** `_extract_camera_stem('<cam>_person_occupancy_2')` returns the camera stem (not `None`); unit test anchored to the probe-named sensors.
- **Verify:** `_get_interior_cameras_near` no longer returns `self._interior_entities` wholesale at either caller.
- **Verify (data):** on 10-03 replay with new stem + door-group dedup at 30 s, `garage_a` surviving rows drop ≥ 40% (probe measured −49%).
- **Verify (data, truth-pending):** every midday 12:00–13:30 surviving crossing either carries `person_id` or has a resident tracker edge within the configured asymmetric window; residuals bounded by the P-D2 Path-β budget (R2.3).
- **Verify (data):** `peak_person_count` on the 14:24 front-door episode is ≥ 4 (producer peaked at 4 bodies on `front_door_aerial` — multiplicity signal survives even when row-count doesn't).
- **Verify (consumers):** `PersonsEnteredTodaySensor` / `PersonsExitedTodaySensor` daily totals change in the expected direction per the migration note; before/after captured in README.
- **Tests (MED-1 behavioural dedup, all behavioural not source-grep — see "hollow anchors"):**
  - `test_door_group_stem_dedup_collapses_delta_10s_cross_camera_legs` (two cams, same door_group, 10 s apart → 1 row).
  - `test_door_group_stem_dedup_preserves_delta_40s_legs` (same pair at 40 s apart → 2 rows).
  - `test_single_physical_entry_produces_one_row_with_direction_entry`.
  - `test_extract_camera_stem_strips_person_occupancy_2_suffix`.
  - `test_resolve_direction_uses_configured_neighbours_not_all_interior` (both callers).
  - `test_resolve_direction_ambiguous_when_neighbours_unmapped`.
  - `test_main_entry_door_select_derived_from_door_groups_keys`.
  - `test_doorbell_lite_maps_to_garage_a_per_conf_door_groups`.
  - `test_peak_person_count_populated_from_episode_max`.
- **MED-2:** `test_unset_door_groups_falls_back_to_todays_per_camera_behaviour` (unset map → zero behaviour change on existing installs).
- **MED-3:** test fixtures use generic names (`cam_door_a`, `cam_door_b`, `interior_cam_1`); no household-specific entity IDs.
- **Live (post-deploy):** at the next real resident entry at `garage_a`, ledger has one entry row (not duplicate `_2` sibling), direction=entry, `peak_person_count` ≥ 1.
- **Discriminator:** if a single physical entry collapses to 0 rows → dedup over-reach (hard fail).

### R2.3 D2 — Resident attribution (replaces §3.D2; Branch A + D only; Tier 1)

**Tier:** 1 (replay-side + card). No producer regression found; no production code change this cycle.

**Changes:**
1. **Replay (`scripts/probes/census_d0/census_estimator_replay.py`):** consume `person_entry_exit_events.person_id` (after crossing-level dedup) AND an **asymmetric** tracker-edge window: `[-180 s, +600 s]` relative to the crossing for exits (BLE departure lag measured +4–8 min), `±180 s` for arrivals. No production code change.
2. **MED-4 — P-D2 control:** cite live `sensor.universal_room_automation_ble_exit_backfilled_count` (`sensor.py:3861`) as the authoritative counter when scoring D2. Replay never asserts the shipped producer is broken unless this counter is 0 over a 24 h window.
3. **Entry-side BLE attach gap (new card, not this cycle):** the 23:25–23:31 return produced 0/12 attributed rows despite operator+Jaya BLE arrival edges inside ±120–300 s. The shipped backfill (`find_unnamed_exit_crossings`) is exit-only. Card: `EGRESS-BLE-ENTRY-ATTACH-1` (producer-side, estimated Tier 2). **(Rev 3: REMOVED — card closed REFUTED; actual root cause is the `_2` stem bug collapsing identity before BLE legs are consulted. See R3.4.)**
4. **Path-β (at-home operator wandering) known-gap:** budget ≈ 3–4 unattributable episodes/day on this install (front porch bursts + the 12:38–12:42 `garage_a` cluster). Card follow-up (`CENSUS-ATHOME-RESIDENT-CORROBORATOR-1`). No new producer this cycle.

**Config-first finding (operator action, not code):** `person.oji_udezue` currently resolves via `okosisipadmini6_2`, a stationary iPad reading `not_home` while operator is home — making GPS legs structurally useless for operator attribution. **Operator to re-point `person.oji_udezue` to a reliable tracker** (BLE Bermuda / private_ble). Recorded here as a Config-First disposition; no URA code change.

**Knobs:** none shipped this cycle. If the asymmetric window moves into production later, name it `BLE_EXIT_ATTACH_WINDOW_LOOKBACK_S` / `_LOOKAHEAD_S` against the real shipped surface at `camera_census.py:~4395-4430`.

**Acceptance:**
- **Verify (data):** on 10-03 replay, the 13:55 `garage_a` departure attributes to operator AND Jaya (`person_id` or edge within the asymmetric window); R2.6 operator confirmation outstanding.
- **Verify:** `T` at 13:00 reduces to Path-β budget (≤ 4).
- **Verify (live):** `ble_exit_backfilled_count` > 0 over the trailing 24 h (producer not regressed).
- **Tests:** `test_asymmetric_window_catches_8min_departure_lag`; `test_stationary_tablet_tracker_does_not_attribute_crossing`; `test_two_residents_leaving_by_car_both_attribute_to_single_crossing`.
- **Discriminator:** if T falls but resident-attributed row count also falls → over-attribution (allowlist leak); stationary-tablet test must stay green.

### R2.4 D3 — DROPPED from this cycle

Per the probe GO/NO-GO: overlap pair `foyer_fisheye`↔`family_room` unconfirmed (J = 0.00); live `sensor.universal_room_automation_persons_in_house` read 3 throughout 10:00–11:15 (not 4–5); the "4–5" was a replay-side artefact of the 1200 s windowed-max in `census_estimator_replay.py:151-162`.

**Action:** the interior-count fix moves to `PLANNING_census_occupancy_estimator.md` (`M_cam` definition — per-area max at an instant + short hold, not 20 min). No URA production code change in THIS cycle for D3.

Optional operator-side spot-check: review Frigate zones/masks for `family_room` steady 2–4 count (not shipped as a URA deliverable).

### R2.5 D4 — Re-run gate (unchanged, but inputs change)

Re-run with: new ledger (R2.2), replay with person_id + asymmetric window (R2.3), estimator-side `M_cam` fix (deferred to estimator plan — if not landed, score G5 with the known replay artefact caveat).

### R2.6 Operator confirmations required BEFORE build dispatch

- **OP-1 (truth timeline):** probe trackers say **Ezinne** departed by car ~12:13 (BLE 12:18–12:19), returned 12:57; **operator + Jaya** departed together ~13:55 (BLE 14:01–14:03). The plan's original "12:00 operator+Jaya leave" is likely wrong (Jaya tracker read `home` all morning until 14:03 across all three legs). **Marked PENDING OPERATOR CONFIRMATION.** D2 acceptance scoring blocks on this. **(Rev 3 clarification per R3.10: OP-1 gates D2 acceptance scoring and D4 GO/NO-GO; does NOT block D1 build dispatch.)**
- **OP-2 (`doorbell_lite` → `garage_a`):** probe-confirmed via co-fires. Closed.
- **OP-3 (`DOOR_STEM_DEDUP_S = 30 s` default):** probe-supported (−49% garage_a). Confirm. **(Rev 3: gates ship-approval, not build; see R3.10.)**
- **OP-4 (Path-β budget):** accept ≈3–4 unattributable at-home episodes/day on this install as the known gap for this cycle? **(Rev 3: gates D4 GO/NO-GO; see R3.10.)**
- **OP-5 (operator-side):** re-point `person.oji_udezue` away from `okosisipadmini6_2`.

### R2.7 Supersession of §1.1 / §3 items

| Original | Status |
|---|---|
| §1.1 "CONF_DOOR_GROUPS already exists" | **WRONG** — NEW (R2.1) |
| §1.1 "REUSE CONF_INTERIOR_CAMERA_OVERLAP_GROUPS" | **WRONG** — NEW; moot (D3 dropped) |
| §3.D1 items 1–6 | **REPLACED by R2.2 items 1–9** |
| §3.D1 INV-INPUTS (c) ≥ 2 surviving entries | **DROPPED** — replaced by `peak_person_count` column (R2.2 item 8) |
| §3.D2 Branches A–D | **REPLACED by R2.3** (Branch A + D only; B/C name non-existent symbols) |
| §3.D3 | **DROPPED (R2.4)**; moves to estimator plan |
| §5 tier table D3 rows | **DELETE** |
| §6 Q-2 (foyer/upstairs removal) | **DROPPED** — probe refuted |

### R2.8 Changelog addendum
- 2026-10-04 (Rev 2): integrated probe results + plan-review FIX-PLAN. §1.1 REUSE claims for `CONF_DOOR_GROUPS` / `CONF_INTERIOR_CAMERA_OVERLAP_GROUPS` / `EGRESS_CROSSING_ADMISSIBLE_TRACKERS` / `RESIDENT_CROSSING_MATCH_S` corrected to NEW. D1 re-scoped around the real root cause (`_extract_camera_stem` miss on `_2` suffix) + per-door neighbours with newest-first ordering + `peak_person_count` DB column (Tier 2-DB). Full consumer table added (HIGH-2). AMBIGUOUS backfill-eligibility decision (HIGH-1). D2 narrowed to Branch A + D (Tier 1); real producer surface + knobs cited; entry-side BLE attach carded. D3 DROPPED (probe refuted; moves to estimator plan). Operator truth timeline marked PENDING confirmation (OP-1). Config-first operator action recorded (person.oji_udezue tracker).

---

## Revision 3 (post plan-review PLAN-FIX-REQUIRED, 2026-10-05) — SUPERSEDES R2.2 / R2.3 / R2.5 / R2.6 where in conflict

Plan reviewer (2026-10-05) returned a FIX-PLAN with CRITICAL/HIGH/MEDIUM/LOW findings against Rev 2. Each is applied below, with every file:line re-verified on `overnight/1005-review-merge` (branched off `develop`) before writing. Earlier text is retained; Revision 3 wins where it conflicts.

### R3.0 Institutional-context refresh (verified on develop, 2026-10-05)

**Code locations re-verified end-to-end for this revision:**
- `transit_validator.py` — `_extract_camera_stem` wrapper at `:1162-1165` (delegates to census); `_resolve_egress_face_identity` body (relevant branches): `direction=='ambiguous'` short-circuit at `:1235-1237`; egress-stem bail at `:1242-1245`; interior-leg assembly `_get_interior_cameras_near` call at `:1253`; per-leg stem normalisation at `:1258`; BLE leg call at `:1363` (`census._resolve_ble_legs(timestamp, direction) or []`). `_resolve_direction` body: stem-dedup literal `5.0` at `:1736`; `_last_resolved[stem]` write at `:1742`; `_get_interior_cameras_near` call at `:1745`; arrival/departure notify call at `:1812` (comment block starts `:1804-1810`); census register/evict at `:1840-1866`; "Log to database if not ambiguous" gate at `:1874-1887`; `log_entry_exit_event` call at `:1879`. `_get_interior_cameras_near` definition at `:1955-1963` (returns `list(self._interior_entities)` — ALL interior cams). `_count_platforms_fired` with `_extract_camera_stem` call at `:1975`. `_last_resolved` 60 s prune literal at `:2001-2002`.
- `camera_census.py` — `_extract_camera_stem` **definition** at `:859`; `_strip_suffix` / `_strip_disambiguation_suffix` normalisers used in sibling-search at `:712-720`; sibling-search `_extract_camera_stem` call at `:797`; `_resolve_ble_legs` (entry-only lead-window helper) at `:4497-4555`, lead bound at `:4527` (`BLE_EGRESS_ENTRY_LEAD_S = 180`, `const.py:2795`); exit-backfill DAO call sites at `:4360` (`find_unnamed_exit_crossings`) + `:4411` (`backfill_entry_exit_person_id`).
- `camera_resolver.py` — `_has_any_suffix_stripped` at `:317`; `_strip_disambiguation_suffix` at `:291`; `_strip_suffix` at `:305`; `_PERSON_SUFFIXES` et al. `:214-270`.
- `sensor.py` — restore reads at `:4559` (entries), `:4693` (exits), `:4765` (exit variant); live bus listeners at `:4580` / `:4711` / `:4821` / `:4869`.
- `database.py` — `log_entry_exit_event` INSERT at `:4041-4066`; `get_entry_exit_events_since` at `:4068`; `find_unnamed_exit_crossings` at `:4099`; `backfill_entry_exit_person_id` at `:4137-4177` (NO direction filter in the UPDATE SQL — direction eligibility enforced upstream by SELECT). Existing `ALTER TABLE … ADD COLUMN` precedent at `:972`, `:1819`, `:1957`, `:2012`, `:2057` etc.

**Verifications done (REUSE-vs-NEW re-stated for this revision):**
- `_extract_camera_stem` has **exactly five** callers (`grep -n _extract_camera_stem custom_components/universal_room_automation`): `camera_census.py:797` (legacy sibling-search), `transit_validator.py:1242` (face identity egress stem), `:1258` (face identity interior-leg normalisation), `:1733` (dedup head of `_resolve_direction`), `:1975` (`_count_platforms_fired`). Verified ✔.
- `_active_count_2` suffix does **NOT exist** in `custom_components/universal_room_automation` (`grep -rn _active_count_2 custom_components/` → 0 hits). The failing Frigate-2 person legs are `_person_occupancy_2` and `_person_count_2`. The Rev 2 claim of a `_active_count_2` suffix is retracted.
- Existing normalisers `_strip_suffix` + `_strip_disambiguation_suffix` (`camera_resolver.py:291/305`) are already composed in sibling-search at `camera_census.py:716-720`; `_has_any_suffix_stripped` at `camera_resolver.py:317` is the suffix-tolerant helper per the IDENTITY/FUSION manual §1.1 "never assume `_2`" rule. **REUSE** these in the `_extract_camera_stem` fix (R3.3); do NOT hand-add `_2` strings.
- `database.backfill_entry_exit_person_id` (`:4137`) today has NO direction filter in the UPDATE itself — the direction filter is in the CALLER's selection via `find_unnamed_exit_crossings` which is exit-only by name. **Correction to Rev 2 HIGH-1 text:** direction-eligibility is enforced by the SELECTION path, not the UPDATE DAO.
- `get_entry_exit_events_since` at `database.py:4068` is restore-only (sensor startup); live sensors read via `ura_person_egress_event` bus listeners (`sensor.py:4580/4711/4821/4869`). The Rev 2 HIGH-1 text treated "ledger readers" as if they drove live attribution — they do not.

### R3.1 CRITICAL-1 — unset `CONF_DOOR_INTERIOR_NEIGHBOURS` MUST NOT silently stop logging

**Finding:** Rev 2 §R2.2 item 3 specified "unmapped → `[]` → direction = AMBIGUOUS". Tracing the consumers of AMBIGUOUS in `transit_validator.py`:
- DB write is gated at `:1874-1887` ("if direction != 'ambiguous': …"). AMBIGUOUS rows **never reach the ledger**.
- Census register/evict is gated at `:1840` (`if person_id and direction in ("entry", "exit")`). AMBIGUOUS → neither register nor evict.
- Arrival/departure notify is gated inside `_arrival_departure_notify` at `:1906-1907` (`if direction not in ("entry", "exit"): return`). AMBIGUOUS → no notify.
- `_resolve_egress_face_identity` short-circuits at `:1235-1237` returning `(None, None, DISAGREE)`, so the BLE entry leg path at `:1363` is **never reached** for AMBIGUOUS crossings.

**Consequence of Rev 2 as written:** on an unconfigured install (the 2nd home at Wigton, going live weekend 2026-10-03/04 per memory `project_single_user_no_backcompat`) OR on this install BEFORE the operator fills `CONF_DOOR_INTERIOR_NEIGHBOURS`, every egress crossing would resolve AMBIGUOUS, and door logging + census register/evict + notify would **silently stop**. This is a hard regression and violates the single-user-no-backcompat "degrade gracefully if unset" rule.

**Fix (replaces R2.2 item 3; subsumes HIGH-2 contract-change for the second caller):**
- `transit_validator.py:1955-1963` — `_get_interior_cameras_near` behaviour when `CONF_DOOR_INTERIOR_NEIGHBOURS` is unset OR the resolved `door_group` is not a key of the map: **fall back to today's `list(self._interior_entities)` byte-identical** (preserve current behaviour). ONLY when the map is set AND the door_group IS a key do we narrow to the mapped list.
- An **empty mapped list for a configured door_group** (operator explicitly sets `{door_group: []}`) MAY resolve AMBIGUOUS — treat as a deliberate opt-out signal.
- The second caller at `transit_validator.py:1253` (`_resolve_egress_face_identity`) sees the same contract: unmapped → full interior set (today's behaviour); configured → narrowed set. HIGH-2's "narrower neighbour set at the resolver" is therefore scoped to CONFIGURED door_groups only. Zero behavioural change on unset.

**Test (new, mandatory):** `test_unset_neighbours_preserves_todays_direction_and_ledger_write` — assert that with `CONF_DOOR_INTERIOR_NEIGHBOURS` unset AND `CONF_DOOR_GROUPS` unset, a real resident entry at `garage_a` still writes a ledger row with direction=`entry` (not `ambiguous`) AND census register fires AND arrival notify fires. This is the regression trip-wire for Wigton's zero-config install.

### R3.2 HIGH-1 — AMBIGUOUS backfill-eligibility rewritten (false-premise correction) + BUILD GATE

**Finding:** Rev 2's HIGH-1 text ("AMBIGUOUS rows ARE backfill-eligible") rests on the false premise that AMBIGUOUS rows reach the DB. They do not (per R3.1 trace of `:1874-1887`). Simultaneously, Rev 2's consumer table misreads sensor behaviour: `get_entry_exit_events_since` (`database.py:4068`) is restore-only (`sensor.py:4559/4693/4765`); live counts flow via bus listeners at `sensor.py:4580/4711/4821/4869`; the BLE entry admission at `camera_census.py:4497` is an in-memory resolver-time leg cache, NOT a ledger read.

**Fix (replaces R2.2 HIGH-1 decision):**
- There is NO AMBIGUOUS-backfill question — AMBIGUOUS rows do not persist. The correct framing is: **how many crossings newly go AMBIGUOUS under the new `_resolve_direction` / neighbours wiring, and therefore drop out of the ledger / census / notify path entirely?**
- **BUILD GATE (P-D1 extension, blocking):** before build dispatch, P-D1 must publish the **before/after AMBIGUOUS fraction** on 10-03 under the new wiring with (a) `CONF_DOOR_INTERIOR_NEIGHBOURS` unset (R3.1 fall-back path — expected 0 delta) and (b) the oracle household's filled map. The after-fraction (b) MUST NOT exceed the before-fraction (today's AMBIGUOUS rate on 10-03) by more than X percentage points; reviewers set X at plan-review time based on the measured before-rate. If the oracle map materially raises AMBIGUOUS, the neighbour lists are too narrow and must be widened before build.
- **No DB schema change for AMBIGUOUS** this cycle (R2.2 implied one via the backfill-eligibility rewrite — withdrawn).

### R3.3 HIGH-2 — stem fix REUSES existing normalisers; corrected suffix list; five-caller contract

**Finding:** Rev 2 item 1 said "fix `_extract_camera_stem` to strip `_person_occupancy_2` AND `_active_count_2`". `_active_count_2` does not exist (verified: `grep -rn _active_count_2 custom_components/` → 0 hits). The actual failing legs are `_person_occupancy_2` and `_person_count_2` (the latter was missing from Rev 2). The IDENTITY/FUSION manual §1.1 forbids hand-adding `_2` strings — resolve via `_strip_disambiguation_suffix` + `_strip_suffix` (both already composed in sibling-search at `camera_census.py:712-720`) or `_has_any_suffix_stripped` (`camera_resolver.py:317`).

**Fix (replaces R2.2 item 1):**
- `camera_census.py:859` — `_extract_camera_stem` is rewritten to compose the existing normalisers. Pseudocode (not source): take `_entity_name(entity_id)`, apply `_strip_disambiguation_suffix` to strip any `_2`/`_3`/… tail, then `_strip_suffix(name, _PERSON_SUFFIXES)` to strip `_person_occupancy` / `_person_count` / `_person_detected` / etc. Return the resulting stem or `None` only when nothing matched. **No new suffix strings are hand-added.** `_PERSON_SUFFIXES` lives in `camera_resolver.py:214-270` per the manual.
- Verdict in §1.1 table: **REUSE** (`_strip_disambiguation_suffix`, `_strip_suffix`, `_PERSON_SUFFIXES`). Rev 2 marked this NEW; corrected here.

**Enumerate the five callers + expected behaviour + one behavioural test each (replaces R2.2 HIGH-2 consumer-table rows for `_extract_camera_stem`):**

| # | Caller file:line | Role today | Behaviour under R3.3 | Behavioural test (one per caller) |
|---|---|---|---|---|
| 1 | `transit_validator.py:1733` (`_resolve_direction` dedup head) | Stem key for `_last_resolved` — Frigate-2 `_2` legs returned `None` → dedup skipped | Returns real stem for `_2` legs → dedup now covers them | `test_dedup_covers_person_occupancy_2_sibling_within_window` |
| 2 | `camera_census.py:797` (legacy sibling-search) | Stem for sibling-pairing | `_2` siblings now pair instead of being dropped | `test_sibling_search_pairs_person_count_2_with_person_occupancy_2` |
| 3 | `transit_validator.py:1242` (identity egress stem) | Short-circuits to `no_leg` when stem is `None` — today **every `_2` egress crossing exits at `:1243-1245` BEFORE BLE legs at `:1363`** | `_2` egress crossings now continue into BLE/face leg assembly; identity can attach | `test_person_occupancy_2_egress_reaches_ble_leg_resolver` (mutation-anchor: neuter the stem fix at `_extract_camera_stem` and confirm the test fails because the `no_leg` short-circuit re-fires) |
| 4 | `transit_validator.py:1258` (identity interior-leg normalisation) | Interior leg stems | Interior `_2` cameras contribute to the leg-set instead of being filtered out | `test_interior_leg_set_includes_person_occupancy_2_camera_stem` |
| 5 | `transit_validator.py:1975` (`_count_platforms_fired`) | Counts distinct platforms for the stem within 10 s | `_2` legs now count toward `platforms_fired` → more crossings reach `platforms_fired >= 2` | `test_platforms_fired_counts_person_occupancy_2_leg_as_frigate` |

**Side effects (surfaced explicitly for reviewers):**
- **Identity attach rate:** `_2`-stem egress crossings today exit at `transit_validator.py:1243-1245` with `_record("no_leg", SINGLE)` — they never see the BLE legs at `:1363` or the face legs at `:1267-1278`. Post-fix they will, which should **raise** the identity attach rate (today ~6.25% live per R2.3 citation).
- **DB `confidence` column shift:** `_count_platforms_fired` at `:1975` feeds `platforms_fired` which controls the `confidence` written at `:1766-1768` and `:1791`: with `_2` legs counted, the per-direction confidence moves `0.8 → 0.9` (unambiguous) and `0.3 → 0.4` (AMBIGUOUS, where it is written to the bus but NOT the DB). Consumers reading `confidence` as a trust input must tolerate the shift (none today — it is an observability field).
- **AMBIGUOUS fraction:** `platforms_fired >= 2` is more easily reached, which may also change how often direction resolves (no direct code path from `platforms_fired` to direction, but the dedup covering `_2` legs removes some duplicate rows that today bypass `_last_resolved`). The R3.2 BUILD GATE catches any adverse shift.

**§1.1 table entry (REUSE verdict for Rev 3):**

| Piece | Rev 2 verdict | Rev 3 verdict | Evidence |
|---|---|---|---|
| `_extract_camera_stem` fix | NEW/code change | **REUSE normalisers** (`_strip_disambiguation_suffix` + `_strip_suffix` + `_PERSON_SUFFIXES`) | `camera_resolver.py:214-270` + `:291/305`; composed already at `camera_census.py:712-720` |
| Suffix list (`_active_count_2`) | asserted | **RETRACTED** — does not exist | grep 0 hits |
| Suffix list (`_person_count_2`) | missing | **ADDED** — this is a real failing leg | grep match in `camera_census.py` / `const.py` / `binary_sensor.py` |

### R3.4 HIGH-3 — Entry-side BLE attach ALREADY SHIPS; remove the new-card item; measurement replaces hypothesis

**Finding:** The entry-side BLE attach is NOT missing. It ships at `camera_census.py:4497-4555` (`_resolve_ble_legs`, documented "v1 = ENTRY-ONLY" with lead window `0 <= (timestamp - leg.transition_ts) <= BLE_EGRESS_ENTRY_LEAD_S` = 180 s, `const.py:2795`). It is called from `transit_validator.py:1363` on the identity path. R2.3's "Entry-side BLE attach gap (new card)" is based on the 23:25 return showing `0/12` attributed rows — but per R3.3 above, those `_2` egress legs **short-circuit at `transit_validator.py:1243-1245` BEFORE reaching `:1363`**. The 0/12 is the `_2` stem bug, not a producer gap. The sibling card `EGRESS-BLE-ENTRY-ATTACH-1` is **closed REFUTED** on the kanban; do not re-mint it.

**Orchestrator measurement (URA DB, 7 days to 2026-10-05), relied on in acceptance below:**
- `person_entry_exit_events` entries over 7 days: **45 named** / **153 unnamed**.
- 0 of the 45 named entries came from a `_2` camera; 75 of 153 unnamed came from a `_2` camera (concentrated at `front_door_aerial_person_occupancy_2`, `madrone_g6_entry_person_occupancy_2`).
- Clustering unnamed entries within 120 s = **59 crossings**; **13 of 59 clusters** have a resident `person.*` arrival edge within ±300 s — i.e. a producer that admitted the BLE leg would have attributed them.

**Fix (replaces R2.3 item 3):**
- Remove the "new card `EGRESS-BLE-ENTRY-ATTACH-1`" item from R2.3.
- Add to R2.2 D1 acceptance (as a POST-DEPLOY measurement; blocks D4 GO/NO-GO):
  - **Verify (live, post-deploy):** over the first 7 days post-ship, the `_2`-camera share of **named** entries rises above 0, AND of the ~59 (projected over 7 d) unnamed entry-clusters with a resident arrival edge within ±300 s, ≥ 13 attach a `person_id` (match or exceed the pre-ship 13/59 ceiling the stem fix unblocks). A result of 0 attachments means the stem fix did not reach the BLE leg path — hard fail, roll back.

### R3.5 HIGH-4 — Consolidated INV-INPUTS-R2 (single statement, discriminating observations)

**Replaces** the scattered INV-INPUTS clauses in §0 / Rev 2.

> **INV-INPUTS-R2 (falsifiable, single statement):** On a replay of the window **2026-10-03 00:00–23:59 CDT** against `person_entry_exit_events` as written by D1-shipped code, with D2 Branch-A asymmetric window applied in the replay, all of the following hold:
>
> **(a) Dedup covers Frigate-2.** For every egress-camera physical event on 10-03 where a `_person_occupancy` AND `_person_occupancy_2` leg fired within `DOOR_STEM_DEDUP_S` of each other, exactly one surviving ledger row is written (not two).
>   - *Fix-shape vs failure:* under the fix, `garage_a` ledger rows ≤ 61 (probe ceiling). Under a bug where the stem fix regressed sibling-pairing (R3.3 caller #2), total `garage_a` rows **rise** above the baseline 119.
>
> **(b) Attribution ceiling, named-episode anchored.** Each of these NAMED episodes (from P-D1, verified in ledger + tracker edges) attaches to a resident `person_id` on the DEDUPED crossing: front porch burst **12:05–12:10** (operator Bermuda area=Receiving Room/Breakfast throughout — Path-β; expect NO attach), front porch burst **13:01–13:03** (same — Path-β; expect NO attach), `garage_a` cluster **12:38–12:42** (Path-β; expect NO attach), `garage_a` departure **~12:13** (Ezinne, BLE dep 12:18–12:19; expect attach to `ezinne` within [-180,+600] s), `garage_a` departure **13:55** (operator + Jaya, BLE dep 14:01:45 / 14:03:44; expect BOTH attach), `garage_a` entry **~15:44** (operator, BLE arr 15:42:29; attach), `garage_a` entry **23:25–23:31** (operator + Jaya, BLE arr 23:28:39/48; both attach ONLY after R3.3 unblocks the `_2` legs). The **Path-β ceiling** for the day is 3–4 unattributable at-home episodes (per probe).
>   - *Fix-shape vs failure:* under the fix, midday 12:00–13:30 `T` ≤ 4 (Path-β bound). If `T` is 0 across the whole window, over-attribution — the Path-β class attributes falsely (stationary-tablet forgery, re-check R2.3 config action).
>
> **(c) AMBIGUOUS does not rise.** AMBIGUOUS fraction on the oracle household's filled neighbours map does not exceed baseline + X pp (set by reviewers from the R3.2 BUILD GATE measurement). On the UNSET-neighbours fallback (R3.1), AMBIGUOUS fraction is byte-identical to today.
>   - *Fix-shape vs failure:* under the fix, same AMBIGUOUS rate on unset install (Wigton zero-config). If AMBIGUOUS rate on unset install rises above zero delta, R3.1 fallback is broken.
>
> **(d) Multiplicity is honest, not row-counted.** The 14:24 front-door episode writes a single ledger row (producer peaked at 4/8 bodies on `front_door_aerial`; row-count multiplicity unrecoverable per probe) WITH `peak_person_count ≥ 4`. The old INV-INPUTS clause (c) "≥ 2 surviving entries" is **removed** (per Rev 2 note, re-affirmed).
>   - *Fix-shape vs failure:* under the fix, `peak_person_count` on that row ≥ 4. If it is `1` (or NULL on new row), the sampler at R3.6 is broken.
>
> **G5 is NOT a clause of this invariant.** G5 (interior over-count morning window) was a replay-side 1200 s-max-hold artefact (R2.4 / probe); the production census read 3. G5 moves to the estimator plan's `M_cam` definition and is not scored by this cycle. R2.5's "D4 re-run with the known replay artefact caveat" stands: D4 scores G1/G2/G3/G7/G8/G9 and reports G5 for information only.

### R3.6 MEDIUM-1 — `peak_person_count` migration, writer, sampler bounds, reader

**Replaces** R2.2 item 8's one-liner.

- **Migration:** add `peak_person_count INTEGER` to `person_entry_exit_events`. Use the existing `ALTER TABLE … ADD COLUMN` idempotent-migration template already applied at `database.py:972` (`decision_log.scope`), `:1819` (`ac_ramp_events.effective`), `:1957/1961` (`room_transitions`), `:2012` (`prediction_results.person_id`), `:2057` (`notification_log.dry_run`). **Column is NULLABLE** so legacy rows (every row written before this cycle, ~7,010+ all-time per IDENTITY manual §5.1) are distinguishable from "post-cycle, sampler returned 0". No default; readers that need a scalar MUST coalesce to NULL-aware behaviour.
- **Writer:** extend `database.log_entry_exit_event` (`:4041-4066`) with a new `peak_person_count: int | None = None` keyword parameter and INSERT it into the new column. Caller is `transit_validator.py:1879` (`_resolve_direction`), which samples per the next bullet before invoking the DAO.
- **Sampler definition (bounded, deterministic):**
  - **Window:** the sampling window is `[egress_timestamp - DOOR_STEM_DEDUP_S, egress_timestamp + EGRESS_ENTRY_WINDOW_SECONDS]` — i.e. from the dedup lookback bound to the delayed-resolve deadline. The DB row is written at the delayed-resolve point already (see `_resolve_direction` call-chain); sampling to the resolve-time horizon is **free** w.r.t. timing because the write already waits that long.
  - **Sampling target:** the max of `sensor.<cam>_person_count` (and `_person_count_2` where present) observed on the camera stem(s) in the door_group that fired the episode.
  - **Door-group dedup rule for the sampler:** when the door_group is set and multiple cameras in it fired within the window, take **MAX across the group's cameras** (not sum). Rationale: two cameras seeing the same 4-person arrival should report `peak = 4`, not `8`; summing double-counts physical bodies the dedup is explicitly collapsing.
  - **Bounding-window knob:** reuse `DOOR_STEM_DEDUP_S` (lookback) + `EGRESS_ENTRY_WINDOW_SECONDS` (lookahead); no new knob. Rung: ledger-shape-adjacent — if a dedicated knob is later needed, it belongs on the **module-constant rung** (ledger-shape consequence, review-gated), consistent with `DOOR_STEM_DEDUP_S`.
- **Reader (Bug Class #53 computed-but-not-consumed — defuse):** `scripts/probes/census_d0/census_estimator_replay.py` SELECT at approximately `:124` must `SELECT peak_person_count` from the ledger and use it as the multiplicity input for the 14:24 recovery check in INV-INPUTS-R2 (d). If this reader is not landed in the same cycle, the column is dead code — in that case **defer the column** to the estimator cycle (operator-coined "finish the job" / Bug Class #53 avoidance). Default disposition: **ship the reader this cycle** (small, one SELECT + one assertion in the probe).
- **Acceptance test:** `test_peak_person_count_sampler_uses_door_group_max_not_sum` (two cameras in one group both read 4 → row shows 4, not 8); `test_peak_person_count_null_on_legacy_rows` (restore-time read of a pre-migration row does not crash).

### R3.7 MEDIUM-2 — `CONF_MAIN_ENTRY_DOOR` deferred

`CONF_MAIN_ENTRY_DOOR` (R2.2 item 7) has NO consumer in this cycle (D1 writes don't key off it; D4 replay doesn't need it; no sensor/notify path reads it). Per Bug Class #53, **defer to the estimator cycle** where the "main-entry prior" actually consumes it. Remove from this cycle's D1 build. §1.1 table entry drops to "parked until estimator cycle consumes it".

### R3.8 MEDIUM-3 — Options-flow shape for `CONF_DOOR_GROUPS` + `CONF_DOOR_INTERIOR_NEIGHBOURS`

Owning config entry = the top-level URA integration entry (ENTRY_TYPE_COORDINATOR_MANAGER), consistent with other census-adjacent options (`CONF_CAMERA_PERSON_ENTITIES` lives there, `const.py:1973`). Added to the existing options-flow step that already carries camera selectors (no new step).

- **`CONF_DOOR_GROUPS`** — maps egress camera entity_id → door-group string.
  - UI: a repeating pair of (camera selector, text input) rows. Default empty.
  - Label: **"Group door cameras"** (plain phrase; no jargon per label-style-guide).
  - Helper text (one sentence, no jargon): "If two cameras watch the same door, put the same group name beside both so URA counts them as one door."
  - Example row the UI shows pre-filled on the oracle household: `camera: front_door_aerial → group: front`, `camera: doorbell_lite → group: garage_a`.
- **`CONF_DOOR_INTERIOR_NEIGHBOURS`** — maps door-group string → list of interior-camera entity_ids.
  - UI: a repeating pair of (door-group text — populated from `CONF_DOOR_GROUPS` values once set, multi-select of interior cameras).
  - Label: **"Rooms next to each door"**.
  - Helper text: "Pick the indoor cameras that see someone just inside each door. URA uses these to tell entries from exits. Leave empty to keep today's behaviour."
  - Default: empty / unset → R3.1 fall-back (today's "all interior" behaviour) kicks in.
- **No "advanced" / technical labels** (hysteresis, debounce, provenance, substrate — all forbidden per label-style-guide memo).
- **Named-bucket style for any numeric exposure** (per `feedback_configurability_clarity`): `DOOR_STEM_DEDUP_S` is NOT exposed as an operator-facing Number entity this cycle (it stays a module constant per R2.2 item 2 and `Numbers-Get-Knobs` rung-1); no raw multiplier is exposed in options flow.

### R3.9 MEDIUM-4 — 30 s door-group dedup keeps the FIRST leg (acknowledged loss + knob tie)

**Finding:** `transit_validator.py:1732-1742` (the dedup head of `_resolve_direction`) keeps the FIRST leg to arrive — a later, higher-confidence leg within the window is **dropped**, and an exit-then-re-entry within `DOOR_STEM_DEDUP_S` collapses to one logical crossing (direction=whichever fired first). The 60 s `_last_resolved` prune at `:2001-2002` is a hard literal 60 — tied below.

**Accepted loss (documented):**
- A door-group round-trip (exit → re-entry) completed **within 30 s** collapses to a single row with the FIRST direction. We accept this on the operator household on the basis of the probe (no observed sub-30 s round trips on 10-03) and the Rev 2 marginal-benefit decomposition — "pick the newer leg" needs a buffering/replay machinery whose risk doesn't pay for a ~0 event/day gain.
- A multi-platform crossing where the Frigate-2 leg arrives 1–2 s AFTER the Protect leg (common per the IDENTITY manual §1.1) loses the Frigate-2 face/count enrichment on the written row. The identity resolver still runs over the leg-set via `_resolve_egress_face_identity`, so the IDENTITY_CONFIDENCE path is unaffected; only the DB `confidence` column reflects the first platform's `_count_platforms_fired` snapshot. Live attach rate (R2.3) remains the authoritative control.

**Fix (replaces R2.2 item 2 end):**
- `DOOR_STEM_DEDUP_S` default **30 s** (OP-3), module constant, `const.py`.
- `transit_validator.py:2001-2002` — replace the hard literal `60` prune with `max(60, DOOR_STEM_DEDUP_S)` so a future knob increase doesn't accidentally prune `_last_resolved` entries that the dedup head still needs. Add a comment at `:2001` naming the invariant: *"prune horizon ≥ DOOR_STEM_DEDUP_S, else dedup head stops seeing the first leg."*

**Tests (new):**
- `test_round_trip_under_dedup_window` — two legs on the same door_group 15 s apart, directions {exit, entry} → one row survives, direction = the FIRST (`exit`), count sensor's `exit_today - entry_today` reflects the collapse (document the observable).
- `test_round_trip_over_dedup_window` — same pair at 45 s apart → two rows survive, directions preserved.
- `test_last_resolved_prune_is_at_least_dedup_window` — set `DOOR_STEM_DEDUP_S = 90` (test-only monkey of the module const), fire a leg, assert `_last_resolved[stem]` survives at 70 s.

### R3.10 LOW-1 — D1 build is NOT blocked by OP-1; gate-mapping clarified

- **D1 (R2.2) build dispatch is NOT blocked by OP-1 operator confirmation of the 10-03 truth timeline.** The D1 changes (`_extract_camera_stem` fix, dedup knob, neighbours fallback, `peak_person_count` migration, options-flow fields) are independent of which resident the probe attributes the 12:13 / 13:55 crossings to.
- **OP-1 (truth timeline)** gates: (a) **D2 (R2.3) replay scoring** — the asymmetric-window acceptance assertion names which resident attaches to which crossing; and (b) **D4 (R2.5) GO/NO-GO** on INV-INPUTS-R2 (b).
- **OP-3 (`DOOR_STEM_DEDUP_S = 30 s`)** gates **D1 constant default** — but D1 build may land with the probe-recommended 30 s under the standing autonomous build mandate (`feedback_build_implies_ship` / `feedback_autonomous_tier1_with_tier2_protocol`); operator confirms at ship-approval time, not before build.
- **OP-4 (Path-β budget ≈3–4/day)** gates **D4 GO/NO-GO** on INV-INPUTS-R2 (b). Independent of D1.
- OP-2 (`doorbell_lite → garage_a`) and OP-5 (re-point `person.oji_udezue`) are already resolved / operator-side; no build gate.

### R3.11 LOW-2 — Rename fixture-specific test names to generic names

Replace in R2.2 Acceptance test list:
- `test_doorbell_lite_maps_to_garage_a_per_conf_door_groups` → `test_camera_maps_to_configured_door_group` (fixture uses `cam_door_c → door_a`, no household-specific entity_id).
- `test_main_entry_door_select_derived_from_door_groups_keys` → deleted along with `CONF_MAIN_ENTRY_DOOR` deferral (R3.7).
- `test_resolve_direction_uses_configured_neighbours_not_all_interior` kept, fixture renamed to `cam_door_a`, `interior_cam_1`, `interior_cam_2`.
- All new tests in R3.1 / R3.3 / R3.6 / R3.9 use generic names (`cam_door_a`, `cam_door_b`, `interior_cam_1`).

### R3.12 LOW-3 — §1.1 REUSE table: Rev-2 / Rev-3 verdict column

The §1.1 table is kept as-is for history (Rev 2 already annotated it with inline "WRONG — NEW" notes, and Rev 3 added `CONF_MAIN_ENTRY_DOOR` DEFERRED). The authoritative current-verdict surface is now the per-finding tables in R2.1 (prior-art corrections), R3.3 (REUSE for `_extract_camera_stem`), and R3.7 (`CONF_MAIN_ENTRY_DOOR` deferred). Reviewers should treat the latter three as the live verdict ledger; §1.1 is retained only to show the before→after audit trail. Future revisions SHOULD migrate the §1.1 rows into a single table with (Piece | Rev 1 | Rev 2 | Rev 3 | Evidence) columns.

### R3.13 Supersession of Rev 2 items by Rev 3

| Rev 2 item | Rev 3 status |
|---|---|
| R2.2 item 1 (`_active_count_2` suffix) | **RETRACTED** (R3.3) — does not exist |
| R2.2 item 1 (`_extract_camera_stem` fix verdict) | **CHANGED** NEW → **REUSE normalisers** (R3.3) |
| R2.2 item 3 (unmapped → AMBIGUOUS) | **REPLACED** (R3.1) — unmapped → today's behaviour (fallback) |
| R2.2 item 7 (`CONF_MAIN_ENTRY_DOOR`) | **DEFERRED** to estimator cycle (R3.7) |
| R2.2 item 8 (`peak_person_count` one-liner) | **EXPANDED** into R3.6 (migration + writer + sampler + reader) |
| R2.2 HIGH-1 (AMBIGUOUS backfill-eligible) | **WITHDRAWN** — false premise (R3.2); replaced by BUILD GATE on AMBIGUOUS fraction |
| R2.2 HIGH-2 (narrower neighbour set at `:1253`) | **SCOPED** to configured door_groups only (R3.1) + five-caller enumeration (R3.3) |
| R2.3 item 3 (new card `EGRESS-BLE-ENTRY-ATTACH-1`) | **REMOVED** (R3.4) — card closed REFUTED; D1 acceptance covers it |
| R2.3 fixture `test_doorbell_lite_maps_to_garage_a_per_conf_door_groups` | **RENAMED** (R3.11) |
| R2.6 OP-1 as D1 build blocker | **CLARIFIED** (R3.10) — gates D2/D4, not D1 |
| §0 scattered INV-INPUTS clauses | **CONSOLIDATED** into INV-INPUTS-R2 (R3.5); G5 removed from gate |

### R3.14 Rev 3 changelog — plan review 2026-10-05

| Reviewer finding | Where fixed in Rev 3 | Verified against code |
|---|---|---|
| CRITICAL-1 (unmapped neighbours silently stop logging) | R3.1 | `transit_validator.py:1874-1887` (DB gate), `:1840` (register/evict), `:1906-1907` (notify), `:1235-1237` (identity short-circuit), `:1363` (BLE legs) |
| HIGH-1 (AMBIGUOUS backfill false premise + consumer-table errors) | R3.2 + R3.0 (consumer map rewrite) | `database.py:4068` (restore-only), `sensor.py:4559/4580/4693/4711/4765/4821/4869`, `camera_census.py:4497` (in-memory, not ledger) |
| HIGH-2 (REUSE normalisers; `_active_count_2` retraction; `_person_count_2` added; five callers + behavioural tests + side effects) | R3.3 | `camera_census.py:859` (stem defn), `:712-720` (composed normalisers), `:797`; `camera_resolver.py:214-270`, `:291/305`, `:317`; `transit_validator.py:1242`, `:1258`, `:1733`, `:1975`; grep `_active_count_2` = 0 hits |
| HIGH-3 (entry-side BLE attach already ships; measurement replaces card) | R3.4 | `camera_census.py:4497-4555`, `const.py:2795`; URA DB measurement cited |
| HIGH-4 (consolidated INV-INPUTS-R2; discriminating observations; G5 removed from gate) | R3.5 | `AUDIT_census_estimator_replay_2026_10_03_hybrid.md`; P-D1/P-D2 probe tables |
| MEDIUM-1 (`peak_person_count` migration + writer + sampler + reader) | R3.6 | `database.py:4041-4066` (writer target), `:972/1819/1957/2012/2057` (migration precedent); `scripts/probes/census_d0/census_estimator_replay.py:~124` (reader site) |
| MEDIUM-2 (`CONF_MAIN_ENTRY_DOOR` deferred) | R3.7 | no consumer in cycle; Bug Class #53 |
| MEDIUM-3 (options-flow shape + labels) | R3.8 | label-style-guide memo; `const.py:1973` (owning entry precedent) |
| MEDIUM-4 (dedup keeps-first + prune tie + round-trip loss) | R3.9 | `transit_validator.py:1732-1742`, `:2001-2002` |
| LOW-1 (D1 not blocked by OP-1) | R3.10 | gate mapping |
| LOW-2 (generic fixture names) | R3.11 | — |
| LOW-3 (verdict column) | R3.12 | §1.1 retention policy |

### R3.15 Findings not applied / disagreements

- **HIGH-1 mechanism caveat.** The reviewer's finding that `database.backfill_entry_exit_person_id` enforces direction via a `WHERE direction='exit'` clause on the UPDATE is slightly off: the UPDATE DAO at `database.py:4137-4177` has NO direction filter in its SQL (`WHERE id = ? AND person_id IS NULL`). Direction eligibility is enforced at the SELECTION layer (`find_unnamed_exit_crossings`, `:4099`, exit-only by name). The reviewer's **conclusion** (AMBIGUOUS rows never persist, so the "backfill-eligibility" framing is moot) still holds and is applied in R3.2; only the cited mechanism is adjusted. No disagreement with the fix direction.
- **Transit-validator line offsets.** Reviewer cited `:1873-1886` (DB log), `:1835` (register/evict), `:1807` (notify), `:1235` (direction_ambiguous), `:1253` (second `_get_interior_cameras_near` caller), `:1963` (helper tail), and `~:868-876` for `_extract_camera_stem`. Live-on-develop offsets are `:1874-1887`, `:1840`, `:1812` (notify call; `:1804-1810` is the preceding comment), `:1236`, `:1253`, `:1955-1963`, and `:859` for the stem definition. Rev 3 cites the live-on-develop lines; no substantive disagreement, offsets drift by 1–10 only.
- All other reviewer findings applied as written.


# PLANNING_census_inputs_first — Simplification alignment appendix

**Status:** APPENDIX 2026-10-05 to `PLANNING_census_inputs_first.md` (Rev 3).
This file exists as a sibling because the main plan is 712 lines and the
agent writing this appendix had no in-place Edit tool. Reviewers should
treat this as §R3.16 of the plan.

## Pointer

See `docs/planning/DESIGN_census_simplification.md` for the full
component ledger (KEEP / MERGE / DELETE / FIX), target Mermaid, GAINS
table (−3 producer nodes, −1 dead gate path, −16 GUEST readers migrated,
~150 LoC removed staged, 5 bug classes retired), and the three-cycle
sequencing (inputs-first D1 / hybrid D3-D6 / separate post-ship cleanup).

## Scope changes this plan implies for `PLANNING_census_inputs_first.md`

None to the Rev-3 build set. The design doc confirms every D1 (R2.2/R3.*)
item is a REUSE or targeted FIX against existing prior art, with no
proposed deletion of live code inside this cycle. Specifically:

- **No scope added** — Path A `_guest_gate_armed` deletion stays in the
  separate post-D5 cleanup cycle (dead ≠ delete without the replacement
  on-ramp live-validated).
- **No scope removed** — all five changes in `_resolve_direction` (R3.1,
  R3.3, R3.9, R2.2 item 4, R3.6 peak sampler) ride together on the same
  site because they touch the same function; splitting them would
  increase blast radius, not reduce it.
- **One naming / documentation debt flagged for the manual, not this
  cycle:** `IDENTITY_FUSION_CAMERAS_MANUAL.md` needs a one-paragraph
  section clarifying four recurring "duplicate concept" smells that are
  NOT duplicates in code (two different holds; direction resolver vs
  identity-leg helper; property census ≠ house census; identified union
  is one function). Carded, not in-cycle.

## Alignment with operator ruling (2026-10-05)

- "Rely on prior art where it is correct" — the design doc's §1 table
  cites file:line for every KEEP; the Rev-3 R3.3 REUSE verdict for
  `_strip_disambiguation_suffix` + `_PERSON_SUFFIXES` is the main
  concrete example that landed in this cycle's build.
- "Do not invent duplicate concepts" — four flagged "duplicate concept"
  cases adjudicated in design doc §1.5 as NOT duplicate; one real dead
  path (Path A) carded for separate deletion.
- "Simplify where possible but show the work and the gains" — design doc
  §3 GAINS table is the ledger.


# PLANNING_census_inputs_first — Revision 4 appendix (post re-review FIX-PLAN)

**Status:** APPENDIX 2026-10-05 PM to `PLANNING_census_inputs_first.md` (Rev 3).
This file exists as a sibling because the parent plan is 760 lines and the
agent writing this revision had no in-place Edit tool — same precedent as
the Rev-3 R3.16 simplification-alignment appendix at the tail of the parent
plan (lines 714+). Reviewers should treat this as **§R4 of the parent plan**;
the parent's final changelog line is extended by R4.10 below.

**Supersedes:** parent Rev-3 R3.3 / R3.6 / R3.8 / R3.9 / R2.3-MED-4 where in
conflict (full supersession table in R4.9).

**Companion changes to DESIGN doc:** see `DESIGN_census_simplification.md` §6
"Revision 4 corrections" (same date) — C13 verdict flip, C3 verdict landed,
C2 wording, §3 GAINS recomputed, §5 overclaim fix.

---

## Revision 4 (post re-review FIX-PLAN, 2026-10-05 PM) — SUPERSEDES R3.3 / R3.6 / R3.8 / R3.9 / R2.3-MED-4 where in conflict

Re-review returned N-HIGH-1..3, N-MED-1..3, MED-4 and two LOWs against Rev 3.
Each finding is applied below with file:line re-verified on develop. Earlier
Rev-3 text is retained in the parent plan; Rev 4 wins where it conflicts.

### R4.1 N-HIGH-1 — R3.3 stem rewrite composition + `_person_count` regression + `_smart_motion_human` note

**Finding:** R3.3's pseudocode said "apply `_strip_suffix(name, _PERSON_SUFFIXES)` to strip `_person_occupancy` / `_person_count` / `_person_detected` / etc." but `_PERSON_SUFFIXES` at `camera_resolver.py:214-219` is `("_person_detected", "_person_occupancy", "_person_motion")` — it does NOT include `_person_count` (the count suffix lives separately as `_PERSON_COUNT_SUFFIX = "_person_count"` at `:263`). As written, R3.3 would NOT strip `_person_count` or `_person_count_2`, re-introducing the exact leak Rev 3 was trying to close for count-leg dedup.

**Fix (replaces R3.3 pseudocode's suffix-set reference):**
- Compose with the tuple **`_PERSON_SUFFIXES + (_PERSON_COUNT_SUFFIX,)`** — the two symbols already exist at `camera_resolver.py:214-219` and `:263`; do not inline-add strings.
- Order of operations unchanged: `_strip_disambiguation_suffix` first (strip `_2`/`_3` tail), then `_strip_suffix(name, _PERSON_SUFFIXES + (_PERSON_COUNT_SUFFIX,))`.
- **Regression test (new, mandatory):** `test_extract_camera_stem_strips_plain_person_count` — assert `_extract_camera_stem("binary_sensor.foo_person_count")` and `_extract_camera_stem("sensor.foo_person_count_2")` both return `"foo"` (not `None`).

**Side-effect note (added to R3.3 side-effects block for reviewers):**
- Dahua / Amcrest `_smart_motion_human` stems: these legs are NOT in `_PERSON_SUFFIXES` and are NOT touched by this fix — but they ARE their own "person" leg family on this install and feed `_count_platforms_fired` as a distinct stem. Dedup across the door_group now reliably covers the Frigate `_2` siblings (per R3.3) but a `_smart_motion_human` leg and a `_person_occupancy_2` leg from the same physical crossing remain distinguishable stems and therefore survive dedup as separate rows unless they share a door_group AND fall within `DOOR_STEM_DEDUP_S`. This is **correct behaviour** (different platforms = different corroborators) but reviewers should expect `platforms_fired` to count them as two platforms, which is the intent.

### R4.2 N-HIGH-2 — `_last_resolved` prune horizon must include ENTRY_WINDOW_SECONDS (resolve delay)

**Finding:** R3.9 tied the `_last_resolved` prune at `transit_validator.py:2001-2008` to `max(60, DOOR_STEM_DEDUP_S)`. Re-trace of the write/prune lifecycle:
- `_last_resolved[stem] = resolved_at` is written at **leg fire + `ENTRY_WINDOW_SECONDS`** (45 s delayed-resolve), per `transit_validator.py:1084-1086` and `:1135`.
- The prune at `:1159` and `:2001-2008` runs on **every interior event**.
- Reviewer's concrete failure: leg A fires at t=0 and resolves at t+45 (writes `_last_resolved[stem]`); leg B fires at t+25 (within `DOOR_STEM_DEDUP_S = 30`) and resolves at t+70; an interior event at t+65 runs the prune. If the horizon is only `max(60, DOOR_STEM_DEDUP_S)` and `DOOR_STEM_DEDUP_S` is later raised, A can be pruned before B's dedup head at t+55 consults it. The invariant must dominate **dedup window + resolve delay**, not just the dedup window.

**Fix (replaces R3.9's `max(60, DOOR_STEM_DEDUP_S)` and comment):**
- `transit_validator.py:2001-2008` prune horizon = **`max(60, DOOR_STEM_DEDUP_S + ENTRY_WINDOW_SECONDS)`** (default = `max(60, 30 + 45) = 75` s).
- Comment at `:2001` names the invariant: *"prune horizon >= DOOR_STEM_DEDUP_S + ENTRY_WINDOW_SECONDS; dedup head writes `_last_resolved` only after the 45 s delayed-resolve, so a smaller horizon can race the writer and drop the first-leg key before the second leg's dedup head consults it."*

**Test (replaces R3.9's `test_last_resolved_prune_is_at_least_dedup_window`):**
- `test_last_resolved_prune_covers_dedup_plus_resolve_delay` — model the real timing: leg A fires at `t=0` and resolves at `t+ENTRY_WINDOW_SECONDS`; leg B fires at `t+25` and resolves at `t+25+ENTRY_WINDOW_SECONDS`; an interior fire at `t+65` runs the prune; assert leg A's `_last_resolved` entry is still present so leg B's dedup head at `t+70` sees it. Use `ENTRY_WINDOW_SECONDS = 45` and `DOOR_STEM_DEDUP_S = 30`; horizon = 75 s.
- Second variant: raise `DOOR_STEM_DEDUP_S = 90` (test monkey of module const), horizon = `max(60, 135) = 135` s; same assertion holds.

### R4.3 N-HIGH-3 — Path A `_guest_gate_armed` is NOT dead (verdict change: DELETE → MERGE)

**Finding (reviewer, verified in code on develop):** DESIGN §1.3 C13 claimed Path A `_guest_gate_armed` has "NONE at runtime" consumers and should be deleted after D5. **Wrong.** Re-grep:
- `_guest_gate_armed` is **called** at `presence.py:5878`.
- `unid_gate_armed` (its armed flag) is the discriminator at `:5914` that sets `_d5_guest_confidence = 0.95` vs `0.9` (unarmed), feeding the inference engine at `:6468`.
- Side-effects (teardown, status attributes) live at `:5405-5455`.
- Teardown path at `:4973-4976`.

Path A is a **live confidence corroborator** feeding the D5 flag's confidence score — not dead code, not a footgun.

**Fix (replaces DESIGN §1.3 C13 verdict; applied in DESIGN doc §6 Rev-4 appendix):**
- C13 verdict **DELETE → MERGE-INTO-FLAG as confidence corroborator**: Path A `_guest_gate_armed` stays as a boolean input to the D5 flag's confidence (`0.95` armed vs `0.9` unarmed), not as a separate guest-arming producer. The `HouseState.GUEST` transition it formerly fed is removed by D5 (that part of the deletion claim stands); the arming predicate body is kept, re-wired to publish `source=unid_gate` (or kept as a confidence modifier on `source=estimate` — reviewer's call during D5 build).
- Operator ruling 2026-10-05 "rely on prior art" — Path A IS prior art that works today; migrate it, don't delete it.

**GAINS table deltas** (applied in DESIGN doc §6):
- Row "Guest-arming predicates: 2 (Path A dead; Path B live) → 1" **retract**. Correct current state: 2 live predicates (Path A arms confidence; Path B arms the GUEST transition). After D5: still 2 producers, both feeding the single D5 flag (Path A → confidence modifier; Path B → `source=guest_room`). Delta = **"−1 house-state transition, 0 producers deleted"**, not "−1 dead code path".
- Row "Dead-code lines (Path A `_guest_gate_armed`) ~70 LoC → 0" **retract**. Correct delta: `~0 LoC removed`; Path A code stays. The ~150 LoC-removed total drops accordingly to **~80 LoC removed** (pre_cancel ~25 + WIFI_GUEST_RECENCY_HOURS ~15 + HouseState.GUEST enum branch ~40).
- "Bug classes closed" row — remove "#53 (computed-but-not-consumed — Path A)". Path A IS consumed. Keep #22, #7-via-N-MED-1-caveat (see R4.4), #23, and the fake-API-test-anchor class. Count drops **5 → 4** retired bug classes.

### R4.4 N-MED-1 — Face resolver already fixed on develop; remove C3 from FIX list

**Finding:** `camera_census.py:3215-3222` on develop already contains the merged face-lookup fix (pattern against `registry.entities.values()`); Rev 3's "still broken" claim is stale.

**Fix (applied in DESIGN doc §6):**
- DESIGN §1.1 C3 verdict changes from **FIX (R1 hotfix, dead face feed)** to **FIX LANDED on develop (verify-only; no action this cycle)**. No code change here, no card to re-mint.
- GAINS table "Bug classes closed" row — "#7 (stale data source — face map `{}`)" is **retired pre-cycle on develop**; keep listed as retired but attribute to the pre-cycle develop commit, not to this cycle's build.
- GAINS table "Test surface" row — the "−2 hollow anchors" was tied to C3's `async_entries_for_platform` monkeypatch; those tests were migrated when the fix landed. **Drop "−2 hollow anchors" from the row**; keep "+10 behavioural" (which belongs to D1/estimator).

### R4.5 N-MED-2 — `peak_person_count` needs a value buffer; reuse `info.person_count_sensor`; column in BOTH fresh CREATE and ALTER

**Finding:** R3.6's sampler assumed we can "take the max of `sensor.<cam>_person_count` observed on the camera stem(s) in the door_group." Re-reading `transit_validator.py:1101-1110` shows the count-handler only reacts on **0→N edges**: once a camera's count rises above 0, subsequent integer value changes within the same episode do NOT re-fire the handler. There is no live time-series the sampler can `max()` over at resolve time without buffering values ourselves.

Additionally, R3.6 said "max of `sensor.<cam>_person_count`" by stem — building the entity_id by string. The authoritative mapping already exists: `PersonCensus.get_transit_egress_entities()` at `camera_census.py:960-969` yields `CameraInfo` entries whose `person_count_sensor` field is the canonical entity_id. **No string-built entity IDs.**

**Fix (replaces R3.6 sampler definition):**
- **Value buffer, in-process:** `TransitValidator` maintains `self._peak_count_buffer: dict[str, deque[tuple[float, int]]]` keyed by camera stem (from `info.person_count_sensor`), where each deque entry is `(timestamp, int(state))`. The buffer is written by a lightweight `state_changed` listener on each `CameraInfo.person_count_sensor` entity (registered once during the validator's setup, iterating `census.get_transit_egress_entities()`), appending `(now, int(new_state))` on every change where the new state parses as an int >= 0.
- **Prune policy:** on every write, pop entries older than `DOOR_STEM_DEDUP_S + ENTRY_WINDOW_SECONDS` (same horizon as R4.2's `_last_resolved` prune; identical rationale). Cap deque at 64 entries per stem as a last-resort DoS guard.
- **Sampler at resolve time:** for the resolving stem's door_group (if set) OR the resolving stem alone (unset), take the MAX across cameras of `max(v for ts, v in buffer[stem] if egress_ts - DOOR_STEM_DEDUP_S <= ts <= egress_ts + ENTRY_WINDOW_SECONDS)`. Default = 1 if no sample lies in the window (the 0→N edge fired, so at least one value was ≥ 1 at some point in the episode; buffer only misses on `unknown`/`unavailable`).
- **Teardown:** per-entity listeners register handles in `self._peak_count_unsubs: list[Callable]`; `TransitValidator.async_will_remove()` (or equivalent coordinator-tear-down hook) iterates and calls each — mirrors existing listener-teardown idiom (verify at build time).
- **Entity source — reuse not re-key:** iterate `census.get_transit_egress_entities()` and read `info.person_count_sensor` directly (`camera_census.py:960-969`). Do NOT construct `sensor.<stem>_person_count` by string concatenation.
- **Schema (two sites, not one):**
  1. **Fresh CREATE** at `database.py:928` — add `peak_person_count INTEGER` column to the inline `CREATE TABLE IF NOT EXISTS person_entry_exit_events (…)`. New installs do not take the ALTER path; omitting this would ship Wigton with the old shape.
  2. **ALTER migration** — idempotent `ALTER TABLE … ADD COLUMN peak_person_count INTEGER` per the existing precedent at `database.py:972/1819/1957/2012/2057`. For existing installs.
  Both must land in the same cycle. **Add an assertion test** that the schema introspected from an in-memory fresh DB and from a pre-migration DB post-migration are identical column-wise.

**Acceptance tests (add to R3.6's list):**
- `test_peak_count_buffer_prunes_outside_horizon` — write values at `t`, `t+10`, `t+120`; sample at `t+130` with horizon 75; only `t+120` visible.
- `test_peak_count_buffer_teardown_releases_listeners` — tear down validator, assert all `_peak_count_unsubs` called and empty.
- `test_fresh_create_table_includes_peak_person_count_column` — introspect `PRAGMA table_info` on a fresh DB.
- `test_alter_migration_adds_peak_person_count_column_idempotently` — run migration twice; column present; no error.
- `test_peak_count_sampler_reuses_info_person_count_sensor` — monkey `census.get_transit_egress_entities()` to return a `CameraInfo` whose `person_count_sensor` is a non-standard entity_id; assert the listener subscribes to that exact id (not a string-built one).

### R4.6 N-MED-3 — `CONF_DOOR_GROUPS` keyed on census stems; unset-groups dedup key; DESIGN §5 overclaim fix

**Finding:** R3.8 defined `CONF_DOOR_GROUPS` as "egress camera entity_id → door-group string" but did not say WHICH entity_id — the `binary_sensor` leg, the `_2` sibling, the Protect `sensor` id, or the camera-device slug? Per `camera_census.py:960-969` (Frigate/UniFi binary_sensor branch) + `:996-1006` (Protect id branch), the census surfaces per-camera **CameraInfo** objects that already resolve the appropriate per-platform entity_ids (`person_count_sensor`, `person_detected_sensor`, Protect's `binary_sensor.<slug>_person_occupancy`, etc). The authoritative key MUST be the **camera stem (CameraInfo-level identifier)**, resolved via the census mapping, not a raw entity_id the operator picks arbitrarily.

**Fix (replaces R3.8's "egress camera entity_id" wording):**
- `CONF_DOOR_GROUPS` maps **camera stem (as surfaced by `census.get_transit_egress_entities()`)** → door-group string. The options-flow selector enumerates stems from the census surface at render time (not raw entity picker). This matches the existing precedent for `CONF_CAMERA_PERSON_ENTITIES` whose selector enumerates census-surfaced cameras (`const.py:1973`).
- Config-flow label stays "Group door cameras" (R3.8); helper text amended: *"If two cameras watch the same door, put the same group name beside both. URA shows you the cameras it already found; you don't type camera names."*
- **Unset-groups dedup key = per-stem** (today's behaviour byte-identical). R2.2 item 4(b) "door-group scope, not per-stem" applies **only when `CONF_DOOR_GROUPS` is set and the stem has a group**.

**Design doc §5 overclaim fix (applied in DESIGN doc §6):**
- DESIGN §5 "Degrades gracefully — unset `CONF_DOOR_*` → today's behaviour byte-identical" is correct for `CONF_DOOR_INTERIOR_NEIGHBOURS` (R3.1) but **overclaims** on `CONF_DOOR_GROUPS` and `DOOR_STEM_DEDUP_S`: the 30 s dedup window AND the `_extract_camera_stem` `_2`-suffix fix (R3.3/R4.1) apply **to all installs regardless of config**. These are not "degrade gracefully if unset" — they are universal pipeline fixes. Correct §5 wording: *"Neighbours fallback only (R3.1) is unset-byte-identical; the 30 s dedup window and the stem fix apply to all installs."*

### R4.7 MED-4 — Control counter is the attribute `ble_exit_backfilled_count`, not a separate sensor entity

**Finding:** R2.3 item 2 cited `sensor.universal_room_automation_ble_exit_backfilled_count` as a control-counter entity. There is no such entity. The counter is an **attribute** named `ble_exit_backfilled_count` on `URAPersonsInHouseSensor` (defined at `sensor.py:3619`; attribute set at `sensor.py:3861`).

**Fix (replaces R2.3 item 2 and R3.4 "URA DB measurement" wording):**
- Authoritative live-check: read the `ble_exit_backfilled_count` attribute of `sensor.universal_room_automation_persons_in_house` (the entity id for `URAPersonsInHouseSensor`). The live value as of 2026-09-11 was `4`; R2.3's "producer not regressed if > 0 over 24 h" refers to this attribute, not a standalone sensor.
- Replay / acceptance wording updated: "Verify (live): `state_attributes.ble_exit_backfilled_count` on `sensor.universal_room_automation_persons_in_house` increments over the trailing 24 h."

### R4.8 LOW — C2 verdict wording + R3.8 operator-entered-names clarification

- **C2 (`_get_unrecognized_camera_count`)** — DESIGN §1.1 verdict changes from **"MERGE-INTO-C9 (estimator)"** to **"MERGE-INTO estimator FLOOR"** (same substance; "C9" in Rev 3 was a drafting slip — the chokepoint is C5. Substance unchanged; verdict wording corrected only).
- **R3.8 wording clarification:** door and camera names (`front`, `garage_a`, `front_door_aerial`, `doorbell_lite`) are **operator-entered values** on this install (and sample pre-fills in options-flow helper text), **never code defaults baked into the integration**. Rev 3 §R3.8's "pre-filled on the oracle household" example is illustrative-only; the shipped code ships with empty `CONF_DOOR_GROUPS` and empty `CONF_DOOR_INTERIOR_NEIGHBOURS`. Add explicit callout to R3.8: *"No household-specific strings are shipped in `const.py` or options-flow defaults; the operator types their own names at install time."*

### R4.9 Supersession of Rev-3 items by Rev-4

| Rev 3 item | Rev 4 status |
|---|---|
| R3.3 pseudocode "_strip_suffix(name, _PERSON_SUFFIXES)" | **CORRECTED** → `_PERSON_SUFFIXES + (_PERSON_COUNT_SUFFIX,)` (R4.1) |
| R3.6 sampler "max of sensor.<cam>_person_count" | **REPLACED** by value-buffer + `info.person_count_sensor` reuse (R4.5) |
| R3.6 "column migration" (ALTER only) | **EXPANDED** to fresh CREATE at `database.py:928` AND ALTER (R4.5) |
| R3.8 "egress camera entity_id → door-group" | **CORRECTED** to census-stem keying + render-time selector (R4.6) |
| R3.9 prune horizon `max(60, DOOR_STEM_DEDUP_S)` | **CORRECTED** to `max(60, DOOR_STEM_DEDUP_S + ENTRY_WINDOW_SECONDS)` (R4.2) |
| R2.3 item 2 "sensor.universal_room_automation_ble_exit_backfilled_count" | **CORRECTED** to attribute on `URAPersonsInHouseSensor` (R4.7) |
| DESIGN §1.3 C13 "DELETE after D5" | **CHANGED** to MERGE-as-confidence-corroborator (R4.3; applied in DESIGN §6) |
| DESIGN §1.1 C3 "FIX (R1 hotfix)" | **CHANGED** to "FIX LANDED on develop; verify-only" (R4.4; applied in DESIGN §6) |
| DESIGN §3 GAINS "−1 dead code path" + "~150 LoC removed" + "5 bug classes" | **ADJUSTED** per R4.3/R4.4 (DESIGN §6) |
| DESIGN §5 "unset CONF_DOOR_* byte-identical" | **CLARIFIED** — neighbours fallback only; stem + 30 s apply universally (R4.6) |

### R4.10 Rev-4 changelog — re-review 2026-10-05 PM

- 2026-10-05 (Rev 4): applied re-review FIX-PLAN. N-HIGH-1 stem rewrite now composes `_PERSON_SUFFIXES + (_PERSON_COUNT_SUFFIX,)` with plain-`_person_count` regression test; `_smart_motion_human` cross-platform note added. N-HIGH-2 prune horizon widened to `DOOR_STEM_DEDUP_S + ENTRY_WINDOW_SECONDS` (default 75 s) with resolve-delay-modelled test. N-HIGH-3 Path A `_guest_gate_armed` verdict changed to MERGE (live confidence corroborator at `presence.py:5878/5914/6468`); DESIGN GAINS recomputed. N-MED-1 face resolver fix already landed on develop; C3 removed from FIX list; GAINS "#7 retired" and "−2 hollow anchors" dropped. N-MED-2 peak_count value buffer + `info.person_count_sensor` reuse + fresh-CREATE schema update. N-MED-3 `CONF_DOOR_GROUPS` keyed on census stems + §5 overclaim fix. MED-4 corrected counter site to attribute on `URAPersonsInHouseSensor`. LOW C2 wording tidied; R3.8 operator-entered-names clarified.
