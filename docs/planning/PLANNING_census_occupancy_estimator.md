# PLANNING — Census Occupancy Estimator (HYBRID: held camera floor + deduped door tally) + `guests_present` flag

**Status:** REVISED 2026-10-04 (round 6) against a re-verify review that returned FIX-PLAN (C1 + H1-H4 + MEDs). Round-5 CR/H/M findings remain fixed; round-6 fixes applied in-place; see §15 changelog. No code is changed by this document.
**Author:** ura-planner, 2026-10-04 (hybrid revision; re-verify fix round).
**Trigger:** `AUDIT_census_subsystem_2026_10_04.md`, `AUDIT_census_footage_ground_truth_2026_10_03.md`, D0 (§8a) NO-GO on the prior flow-ceiling design, operator rulings rounds 1–4 **plus 2026-10-04 round-6 "still guest at anchor is rare, accepted risk"**, and two Tier-3 plan reviews + one re-verify review 2026-10-04.
**Canonical domain reference:** `docs/Coordinator/IDENTITY_FUSION_CAMERAS_MANUAL.md`. §11 lists corrections this plan makes to it.
**Also in-scope for institutional read:** `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` (D5 flag flows into HVAC guest-mode actuation; see §2.4).
**Supersedes:** parked card `CENSUS-GUEST-FLOOR-1`; folds in `EGRESS-INTERIOR-COUNT-REINFORCE-1`. Depends on the Tier-1 R1 (dead face lookup fix) and Tier-1/2 R3 (door-dedup) carded separately.

---

## 0. Operator-approved design (the HYBRID, in one page)

**One sentence:** FLOOR = *max of three lower bounds* — (i) `R_home` (always), (ii) a held camera max over a short memory window **plus guest-side-maxed overflow** (`U_gr` and door-tally `T` are maxed against each other on the guest side, not added — per H1), (iii) `R + max(M_cam − R, U_gr, T)` as the single implementation-friendly form. The guest-side `max()` prevents double-counting a guest who is simultaneously in a guest-room hold AND on an interior camera (held 20 min). **Residents are subtracted only from the camera term; `T` already excludes resident-attributed crossings; `U_gr` is spatially disjoint from cameras.** The design is tuned for 1–2 people (household norm); parties are stress, not target.

**Rulings this plan encodes (operator 2026-10-04, rounds 1–6):**
1. Cameras count bodies well; names/faces are not required for counting. **INV-NO-NAME**.
2. `guests_present` is a **flag orthogonal to house state** (SLEEP + guests is a legal combination).
3. **Hybrid floor** (not a flow-driven ceiling): held camera max + door tally of unattributed crossings; residents never double-subtracted. AWAY = true-empty anchor. **Guest-side terms are MAXED, not summed** (H1 round 6).
4. Door tally merges both cameras per door, 30 s stem collapse, ~120 s distinct-person group window, quick out-and-back nets zero.
5. Guest WiFi phones (Revel) are **OUT of the floor** until the D4 filter is fixed (hostname/MAC allowlist + "appeared since last empty anchor"). Corroborator-only afterward.
6. **Measured interior overlap only.** The one real pair in retention is {`family_room`, `master_hallway`} (J=0.56). All other §5.2-candidate pairs falsified.
7. Exclude Apollo MTR-1 and `sensor.upzone2_people_count` from census inputs.
8. Tuned for 1–2 people; discrimination gate measured against a household-norm day.
9. **Graceful degradation by what is configured. NO new switches** (one estimator kill-switch excepted). Interior cams absent → camera term ABSENT (not zero). Nothing configured → fall back to `R_home`, publish `census.health = absent`. Perimeter alerts continue to key off existing `CONF_SECURITY_ENABLED` (`const.py:2925`).
10. **One new config question:** `CONF_MAIN_ENTRY_DOOR` (`front` | `garage_a` | `garage_b`) — resident-entry prior for door attribution. Oracle household: `garage_a`. **Door-group keys are snake_case throughout this plan** (`front`, `garage_a`, `garage_b`) — unified per M round 6.
11. **10-03 truth** restated in §8.1.
12. Prior-art first — every proposed piece has a REUSE / FIX / DISCARD(justified) / NEW verdict in §4.
13. Side findings are side cards (§12).
14. **(ROUND 6, H3) "A still guest could be at home but this is rare."** → the empty anchor MAY erase `T` even if an unmoving guest is actually present. This is an **accepted operator-ruled trade-off**. INV-FLOOR-SOUND and INV-AWAY-SAFE carry an explicit **anchor-erasure exception** (see §7.11). The rationale: the alternative (never erasing T without a provable exit) would latch FLOOR permanently on any home that lacks per-guest tracking — a worse failure mode than a rare under-count of a still guest.

**Falsifiable program invariant (D's one statement to break — now falsifiable per CR-H-1):**
*For every reachable tick t, with the inputs the system currently has, there exist publishable `FLOOR(t)` and `ESTIMATE(t)` satisfying:*
> **INV-PROGRAM:** `0 ≤ FLOOR(t) ≤ true_people(t) ≤ ESTIMATE(t) + ESTIMATE_SLACK`, AND `FLOOR(t) = 0` within `FLOOR_WINDOW_S + EMPTY_ANCHOR_SETTLE_S` (+ `BOOT_SETTLE_S` after restart) of the empty anchor firing, AND `guests_present` is ON within `GUESTS_PRESENT_ON_S` iff at least one non-resident has been continuously on-premises for that window.

The permitted exceptions to `FLOOR ≤ true_people` are: (a) an under-counted egress event — every such exception must **name the specific exit event missed** (door_group, timestamp, which camera/tracker should have fired) per CR-H-1; AND (b) **anchor erasure of a still guest** (round 6, H3) — the accepted trade-off from ruling 14, where an empty anchor fires because `R_home=∅ ∧ M_cam=0 ∧ U_gr=0` even though an unmoving guest is on-premises. D's job in §9 is to produce a legal-config reachable triple that falsifies INV-PROGRAM without a nameable missed exit AND without being an accepted anchor-erasure case.

---

## 1. Tier classification

| Phase | Deliverables | Tier | Why |
|---|---|---|---|
| **Measure** | D0-REPLAY, D2-OVERLAP | none (read-only) | Measure-Before-Build. |
| **Shadow** | D3 (hybrid estimator in shadow), D4 (Revel filter FIX) | **Tier 2-DB** | New persisted state (empty anchor + door tally); additive payload keys; `interior_count` byte-identical. **Tier 2-DB elevation is explicit here because of D6's `census_snapshots.total_persons` write-path change — see §9/D6 and the §6.2.b enumeration.** Three framing-disjoint reviews. |
| **Promote** | D5 (`guests_present` flag + GUEST consumer migration), D6 (FLOOR → `total_persons`; AWAY-safe binding; empty-anchor wiring) | **Tier 3** | Changes the house-state vocabulary and the count feeding AWAY veto, HVAC composition (`domain_coordinators/hvac.py:3945`), security arming, NM severity, Bayesian suppression, census persistence. Cross-coordinator trust ripple at a state-machine × time seam. Two plan reviews + re-verify (done — this doc is round 6 of fixes), four framing-disjoint build reviews. |
| **Later** | D7 (AI-vision group count at door) | Tier 2 (parked) | Revival trigger in §9. |

---

## 2. Institutional context verified

### 2.1 Prior-art scan (REUSE / FIX / DISCARD(justified) / NEW), citing file:line

| Piece | Verdict | Evidence |
|---|---|---|
| Interior per-camera person count | REUSE | `CONF_CAMERA_PERSON_ENTITIES` `const.py:1973`; 12 live interior entities. |
| Per-area max / cross-area sum dedup | REUSE then EXTEND (measured overlap pair only) | `_calculate_house_census` `camera_census.py:1690`. |
| Interior overlap table | NEW (per-install, derived) | No `INTERIOR_ADJACENCY` symbol repo-wide. Pattern mirrors `EXTERIOR_ADJACENCY_GRAPH` `const.py:2373`. **Per H-4: default empty; per-install options-flow field `CONF_INTERIOR_CAMERA_OVERLAP_GROUPS` (rung-2) populated from the overlap probe.** |
| Hold/decay machinery | REUSE for held-max floor; DISCARD(justified) for a flow ceiling | `_apply_hold_decay` `camera_census.py:5026`; `CENSUS_PEAK_SUSTAIN_SECONDS=15` `const.py:3544`; `DEFAULT_CENSUS_HOLD_INTERIOR_MINUTES=3` `const.py:3528`. **Per H-2:** the 3-min hold is kept for the per-camera smoother but the FLOOR uses its own `FLOOR_WINDOW_S` (default 1200 s) and the anchor also clears the held-max buffer (see §7.4). AWAY lag ≤ 20 min from last camera rise is accepted as **lagged-floor semantics**; D6 wires an exit-observed shrink that collapses `FLOOR_WINDOW_S` toward `DEFAULT_CENSUS_HOLD_INTERIOR_MINUTES*60` when the last tracked event in-window was an outbound crossing. |
| Door flow producer | REUSE then FIX | `TransitValidator._resolve_direction` `transit_validator.py:1724-1758`; `_on_camera_state_change` `:795-834`; persisted to `person_entry_exit_events` `database.py:793-808`. **Per CR-4:** `_get_interior_cameras_near` `transit_validator.py:1955-1963` currently returns ALL interior cams, which makes direction resolution degenerate on egress-only homes. FIX required (§4.3). |
| Stem dedup window | FIX | Inline literal `5.0` at `transit_validator.py:1736` — Numbers-Get-Knobs violation AND too short per D0 §P1 (`<5%` residual at 30 s). Replace with named knob. |
| Door group size (`person_count`) | DISCARD(justified) for group-size inference; USED as held-max floor | D0 §P2: 14/15 burst entries had `group_hi=1`. |
| Distinct-person group window at door | NEW (named gap: define `DOOR_GROUP_WINDOW_S` — reviewer #2 flagged "define or delete") | **Defined**, not deleted: default 120 s per 10-03 arrival spread; collapses legs of one group across cameras within a door_group, not for group-size inference. |
| Resident attribution at door | REUSE then EXTEND (main-entry-door prior) | Depends on `EGRESS-BLE-PROVENANCE-GATE-DROPS-DEPARTURES-1` (§12). |
| Resident subtraction scope | FIX (**only** from camera term) | **Per CR-2:** `_get_unrecognized_camera_count` `camera_census.py:5198` uses `R_cam`; the hybrid subtracts residents **once, house-wide, from the M_cam term only**. `T` already excludes resident-attributed crossings by construction (resident crossings never increment T). `U_gr` is in guest rooms with no cameras in the oracle household (§4.5) — no overlap with M_cam, so no subtraction. |
| Guest-room occupancy | REUSE | `_guest_room_gate_armed` `domain_coordinators/presence.py:5303`; `CONF_ROOM_IS_GUEST_ROOM` `const.py:402`. |
| Revel guest phones | FIX | `_get_wifi_guest_count` `camera_census.py:5383-5548`; `WIFI_GUEST_RECENCY_HOURS=4` `const.py:3638` retired (KEEP+DOCUMENT). |
| Egress-face guest identities | REUSE (corroborator only) | `_get_egress_guest_ids_fresh` `camera_census.py:5695`; `EGRESS_FACE_UNION_TTL_S=300` `const.py:2734`. |
| Body-reinforcement TTL bucket | FOLDED-IN | `PLANNING_egress_interior_count_reinforce.md` D2; close `EGRESS-INTERIOR-COUNT-REINFORCE-1`. |
| `guests_present` flag entity | REUSE existing `binary_sensor.ura_presence_coordinator_guest_mode` `binary_sensor.py:2412-2445` — re-pointed to the flag, keeping entity_id. | — |
| Manual guest override | REUSE | `select.ura_presence_coordinator_house_state_override`; `HouseStateMachine.set_override`. |
| Guest-mode kill switch | **REUSE** `switch.ura_presence_guest_detection_enabled` `switch.py:3787` + consumer `domain_coordinators/presence.py:5315` — **per M-5, do NOT add a second switch**. The one new switch is the estimator kill-switch (§7.10), which is a byte-identical fallback, not a guest-mode gate. |
| Household main-entry door | NEW | `CONF_MAIN_ENTRY_DOOR` (Select, per-install options flow); §4.6. |
| Per-install door groups + egress-camera lists | NEW (per H-4) | `CONF_DOOR_GROUPS` (JSON/select-multiple per group) and `CONF_EGRESS_CAMERAS` already exist upstream; the plan's shown values are the oracle household's config, NOT shared defaults. |
| Main-entry-door Select options | **DERIVED** (per H-4) | Options are enumerated from `CONF_EGRESS_CAMERAS` + `CONF_DOOR_GROUPS` on the running install; hardcoding `front`/`garage_a`/`garage_b` only applies to the oracle household. |
| Revel deny-list | **FIX** (per H-4) | `CONF_REVEL_DENYLIST_HOSTNAMES` + `CONF_REVEL_ALLOWLIST_MACS` per-install (options flow); the hostnames called out in D0 §P5 are the oracle household's examples, not a shared constant. |
| Apollo MTR-1 / `upzone2_people_count` | DISCARD(justified) | Operator ruling 7. |

### 2.2 Prior planning docs consulted
`AUDIT_census_subsystem_2026_10_04.md`, `AUDIT_census_footage_ground_truth_2026_10_03.md`, `quality/tests/fixtures/census_ground_truth_2026_10_03.csv` (named as D0-REPLAY oracle — see §8.1), `RESEARCH_guest_actuation_and_census.md`, `CATALOG_cross_correlation_primitives.md` Tier 2 C1–C16, `AUDIT_exterior_camera_adjacency_probe.md`, `PLANNING_egress_interior_count_reinforce.md`, `PLANNING_guest_census_correctness.md`, `PLANNING_guest_count_dedup_migrate.md`. Kanban: `CENSUS-GUEST-FLOOR-1` SUPERSEDED; `EGRESS-INTERIOR-COUNT-REINFORCE-1` FOLDED; `CENSUS-GHOST-DEDUP-1` **DONE**; `CENSUS-FACE-RESOLVER-MIGRATE-1` candidate home for R1.

**Dispositions for the open parked cards (per M-6):**
- `GUEST-GATE-DOOR-IDENTITY-1`: **merge INTO D5** — the flag's criterion (a) consumes door-identity attribution directly. Close the parked card at D5 ship.
- `SECURITY-CENSUS-UNKNOWN-WIRE-1`: **merge INTO D6 M-5 wiring** — security.py reads `FLOOR` instead of inferring from house state.
- `GUEST-FP-RESIDUALS-1`: **supersede** by D5 orthogonal flag + D4 Revel filter — close at D5 ship.
- `LIGHTS-GUEST-MODE-BEHAVIOUR-1`: **keep separate**; adjacent, not scope. Add revival trigger: fires when flag ON produces unwanted lighting behaviour post-D5.
- `CENSUS-ACCURACY-1`: **supersede** by this plan's D0-REPLAY + D3 property tests + §8.1 named-oracle. Close at D3 ship.
- `CENSUS-GHOST-DEDUP-1`: already DONE; noted here so reviewer does not re-raise.

### 2.3 Memory bodies relevant
`reference_frigate1_retired_2suffix_permanent`, `reference_protect_face_latency_async`, `reference_egress_face_coverage_7pct_not_a_ceiling`, `project_guest_mode_false_positive_backlog`, `project_presence_guest_latch_and_veto_gap` (I-D1 superseded here), `reference_pooloverhead_four_integrations`, `feedback_no_restart_during_sleep`, `project_single_user_no_backcompat` (CHANGING: 2nd install 10-03/04 → optional inputs degrade gracefully).

### 2.4 Design docs read
- `IDENTITY_FUSION_CAMERAS_MANUAL.md` §1–§4.
- `domain_coordinators/house_state.py:60-139` (states, transitions, hysteresis; GUEST state currently in enum).
- **`HVAC_ARCHITECTURE_STATE_OF_PLAY.md`** (per H-5 / M-6): D5's flag feeds `switch.ura_hvac_coordinator_guest_mode_actuation` and `domain_coordinators/hvac.py:3945` — the HVAC composition entry point for guest-mode presets. The plan's §6.2.a keeps this surface unchanged in semantics (ON when flag ON) but migrates the SOURCE from inferred `HouseState.GUEST` to `guests_present`.

### 2.5 Code surveyed (end-to-end, paths corrected round 6)
`domain_coordinators/presence.py` 1035, 1111, 1223, 1263, 1301, 1332-1334, 1843-1845, 1957-1960, 2903, 2908-2918, 4579-4629, 5303, 5315-5317, 5467-5534, 5585, 5859, 5893, 6218, 6306, 6372, 6424-6455, 6467, 6530-6540, 6565-6567, 6639-6667, 6730-6797, 6829-6833, 6882-6904, 7270, 7416, 7727, 7928; `sensor.py` 3273, 3636, 4046-4064, 4226-4329, 4955, 5495-5507, 5848-5882; `binary_sensor.py` 1942, 1982, 2182, 2225, 2412-2445, 3255; `__init__.py` 2893; `aggregation.py` 5648, 6346; `database.py` 793-808, 914, 3926-3965; `switch.py` 3787; `camera_census.py` 171, 1576-1690, 1593, 1597, 1642, 1645, 2041, 2299, 3192-3231, 5026, 5198-5381, 5383-5548, 5638-5770, 5695, 5740-5804; `transit_validator.py` 795-834, 1167, 1724-1758, 1838, 1955-1963; `exterior_track_linker.py` 767; `perimeter_diagnostics.py` 37; `domain_coordinators/house_state.py` 60-139 (incl. 77, 89, 94, 106, 116, 130, 137); `domain_coordinators/hvac.py` 3928-3974, 3945, 6835-6867; `domain_coordinators/hvac_const.py` 1266; `domain_coordinators/dynamic_preset.py` 861; `domain_coordinators/preset_overrides.py` 54, 115, 142, 147-148; `const.py` 1973, 2071, 2223, 2307, 2373, 2712, 2925, 3055, 3447, 3528, 3544, 3553, 3638, 3729; `domain_coordinators/energy_const.py` 630-644 (confirmed: `:636` is a comment, not a reader).

### 2.6 Config-first check (gate step 1b)
Interim lever = `select.ura_presence_coordinator_house_state_override` (blocks SLEEP, insufficient). No knob makes census stock vs snapshot or GUEST orthogonal. **Code required.**

---

## 3. Literature and prior art

L1–L18 as in the prior revision, retained **inline** here (reference to `REFERENCES_census_estimator.md` removed per CR-1 since that doc does not exist). Key conclusions:
- **L1 (Meyn 2009):** flow-only ≈70% error; fused + bounded ≈11%. Grounds the hybrid.
- **L2 (PreCount 2018):** per-door bias learned from verified-empty anchors; D3 records residual at each AWAY reset.
- **L4 (Axis):** "scheduled reset" standard; verified-empty is stronger.
- **L5 (Chen 2012):** flow-ceiling arithmetic unmanageable with ≥1% miss rate per edge — grounds the DISCARD of a separate CEILING sensor.
- **L8:** bursty signals → justify held-max over instantaneous.
- **L15 / L17:** Frigate has per-cam `person_count` with `_2` rule; Protect exposes no count sensors (binary-only).
- **L18 (HA UniFi):** `home` iff `now − last_seen ≤ detection_time`; `last_changed` is connect time → root cause of D4.

Literature does not supply a method for "household of 1–4 with sporadic guests"; the hybrid is engineering.

---

## 4. Inventory

### 4.1 Frigate interior
`sensor.<cam>_person_count` on: family_room, foyer_fisheye, master_hallway, staircase (= Garage Hallway), stairs_top, playroom, upstairs_hall. D0 §P4 minutes-with-count>0 over 8 days: family_room=2744, master_hallway=1643, playroom=187, staircase=105, stairs_top=65, upstairs_hall=39, foyer_fisheye=27. foyer_fisheye and upstairs_hall are effectively dead on current camera config.

### 4.2 UniFi Protect
Per-camera `binary_sensor.<cam>_person_detected` on interior and all five egress cameras. Binary corroborator only.

### 4.3 Egress cameras — door groups and direction resolution (FIX per CR-4; AMBIGUOUS policy per H2 round 6)

Oracle household egress cameras: `madrone_g6_entry`, `doorbell_lite`, `front_door_aerial`, `garage_a`, `garage_b`. Door groups per operator-confirmed (**snake_case keys unified per round 6 M**):
- **`front`** = {madrone_g6_entry, front_door_aerial, doorbell_lite}
- **`garage_a`** = {garage_a}
- **`garage_b`** = {garage_b}

**These are per-install values, not shared defaults** (per H-4). The plan reads them from `CONF_DOOR_GROUPS` on each install.

**Direction resolution FIX (CR-4):** `_resolve_direction` (`transit_validator.py:1743-1758`) currently depends on `_get_interior_cameras_near` (`:1955-1963`), which returns ALL interior cams — degenerate on egress-only homes and insensitive to geometry. **FIX:**
1. Add **per-door nearby-camera mapping** `CONF_DOOR_INTERIOR_NEIGHBOURS: Mapping[door_group, list[interior_cam]]` (options-flow rung-2). Oracle household example: `{"front": ["foyer_fisheye", "family_room"], "garage_a": ["staircase"], "garage_b": ["staircase"]}`.
2. `_resolve_direction` consults ONLY the configured neighbours for the firing door_group; falls back to AMBIGUOUS when none configured or none active in window.

**Ambiguous-crossing policy (defined explicitly per H2 round 6 — ONE policy, no §4.3-vs-§7.5 contradiction):**

An AMBIGUOUS crossing is one `_resolve_direction` could not classify. It flows through the §7.1 pipeline (leg-collapse + round-trip pairing + resident attribution) first. After the pipeline, if it is still AMBIGUOUS AND unpaired AND has **no resident tracker edge within `RESIDENT_CROSSING_MATCH_S`**:

- **Policy P-AMB (unified):** classify as a **provisional +1 entry** (increments `T` as unattributed) IFF **either** of:
  - **(cam-approach)** the firing door's exterior camera (or `CONF_DOOR_APPROACH_CAMERAS[door_group]` where defined) saw a person approaching from outside within `DOOR_AMBIGUOUS_APPROACH_S` (default 60 s) before the crossing; OR
  - **(interior-fire)** the door is in **egress-only mode** (no `CONF_DOOR_INTERIOR_NEIGHBOURS` entry AND no interior cams globally) AND any interior presence/motion sensor fires within `DOOR_AMBIGUOUS_INTERIOR_S` (default 90 s) after the crossing.
- Otherwise it goes to `T_amb` (ESTIMATE-only, decays over `AMBIGUOUS_DECAY_S` default 1800 s). `T_amb` never enters FLOOR.

**Accepted cost (operator ruling, round 6):** P-AMB produces false +1 entries when (cam-approach) catches a passer-by that approaches but turns away before crossing, or when (interior-fire) catches a resident moving around on an unrelated schedule. The ceiling on this error class is bounded by door-tally staleness decay (`DOOR_TALLY_STALE_S`) and by the empty anchor (§7.4) — anchor erasure (ruling 14) resets T to 0 and absorbs any such accumulated false entries.

**Degradation path for egress-only homes (made consistent with P-AMB):** when `CONF_DOOR_INTERIOR_NEIGHBOURS` is empty for a door_group AND no interior cams are configured at all, P-AMB (interior-fire) is the ONLY path a crossing can be counted; otherwise it is `T_amb`. `census.health` is `degraded` with `inputs_present` excluding `camera_interior`. FLOOR falls back to `R_home + U_gr + max(T, T_amb_as_ESTIMATE_only=0)` i.e. driven by door entries that passed P-AMB.

Persisted to `person_entry_exit_events` `database.py:793-808`. R3 dedup FIX see §9/R3.

### 4.4 Non-camera counters
Apollo MTR-1 `sensor.apollo_mtr_1_fa21b0_*` EXCLUDED; `sensor.upzone2_people_count` EXCLUDED (operator ruling 7).

### 4.5 Area-mapping facts
From `core.config_entries` + `core.entity_registry` (D0 §P4): family_room → Living Room; foyer_fisheye → Entry Way; master_hallway → Master Hallway; staircase → Garage Hallway; stairs_top → Stairs; playroom → Game Room; upstairs_hall → Upstairs Hallway. Kitchen, Dining, Media, Master Bedroom, Guest Bedrooms, Garage **rooms** have `room_cameras: []`. **Measured interior overlap (D0 §P4):** only strong pair = {family_room, master_hallway} (J=0.56, 1579 co-on min). All §5.2-candidate stair pairs falsified (J ≤ 0.09).

### 4.6 Main-entry-door prior (NEW config question, per-install)
`CONF_MAIN_ENTRY_DOOR` (Select, options-flow rung-2): options **derived at run-time** from the install's `CONF_DOOR_GROUPS` keys (per H-4). Default: unset → neutral prior. Oracle household: `garage_a`. Used in §7.3 attribution.

---

## 5. Measured interior overlap (D2)

### 5.1 Probe
Method: simultaneous Jaccard + onset lag + single-resident oracle; probe already ran in §8a §P4.

### 5.2 Overlap config (**per-install**, not a shared constant per H-4)

The oracle household's answer is:
```
# per-install, options-flow field CONF_INTERIOR_CAMERA_OVERLAP_GROUPS (rung-2)
CONF_INTERIOR_CAMERA_OVERLAP_GROUPS = [
    ["family_room", "master_hallway"],
]
```
Dedup rule per tick: `S(t) = Σ_components max_{cam∈component} count_cam(t)`. Non-transitive chains → connected components. Second install populates its own list from its own overlap probe; unset = every interior cam stands alone (sum, fail-safe low).

---

## 6. `guests_present` flag and consumer migration (D5) — INLINE PER CR-1

### 6.1 Semantics

A `binary_sensor.ura_presence_coordinator_guest_mode` (entity_id REUSED, re-pointed) that is ON whenever the system has evidence of at least one non-resident person on-premises, independent of `HouseState`. Attributes:
- `source` ∈ {`estimate`, `guest_room`, `revel`, `manual`, `unknown`}
- `guest_estimate` (int ≥ 0)
- `last_on_ts`, `last_off_ts`
- `since_anchor_s` (seconds since last empty anchor)

**ON criterion** (flag goes ON when **any** of (a)(b)(c) holds continuously for `GUESTS_PRESENT_ON_S`, default 600 s):
- **(a) Estimate path:** `guest_estimate = max(0, FLOOR − |R_home|) ≥ GUESTS_PRESENT_MIN_COUNT` (default 1).
- **(b) Guest-room path:** at least one `CONF_ROOM_IS_GUEST_ROOM` room sustained-occupied with no `_is_known_person_in_room` for `CONF_ROOM_GUEST_OCCUPANCY_THRESHOLD_MIN` (default 30 min). Independent of estimate.
- **(c) Revel path (DORMANT until D4 proves clean):** ≥1 Revel phone passed the D4 filter (allowlist + "appeared since last empty anchor"). Until D4 lands, (c) is dormant.

**OFF criterion** (flag goes OFF when **all** of the following hold for `GUESTS_PRESENT_OFF_S`, default 1800 s):
- `FLOOR ≤ |R_home|` (no evidenced anonymous bodies)
- No guest-room sustained-unknown-occupied
- No Revel allowlisted phone currently `state == home`
- No manual override forcing ON

**Immediate OFF** (bypass OFF timer): an empty-anchor fires AND `U_gr = 0` AND Revel path OFF. (This is where the operator-ruled "still guest" trade-off bites — see §0 ruling 14; the flag will go OFF on the anchor even if a still guest remains.)

**Manual path:** `select.ura_presence_coordinator_house_state_override == "guest"` forces flag ON with `source = manual`; clearing the override resumes derived evaluation (with ON/OFF timers restarting from clear).

**Per H-5 degradation:** if no phones/trackers are configured (`R_home` is empty-set because `person_tracker` has 0 members), `guests_present` **MUST NOT latch ON** on the estimate path — residents cannot be distinguished from guests. In that configuration flag reports `source=unknown` and remains OFF for (a); (b) and (c) continue to operate. **Additionally (M round 6):** on a no-trackers install the empty-anchor is **disabled** (we cannot verify `R_home = ∅`); `guests_present` reports `source=unknown`; FLOOR degradation per §7.5.

### 6.2 Migration tables (re-enumerated per C1 — split into D5 GUEST readers and D6 FLOOR readers)

**Enumeration method (re-run live for this fix pass):** `grep -nE "HouseState\.GUEST|\"guest\"|'guest'|census_count|total_persons" custom_components/universal_room_automation` across the tree; results triaged into two disjoint tables. Orchestrator pre-ship re-greps and re-attaches file:line. Paths carry the `domain_coordinators/` prefix wherever the file lives there — the prior revision mis-cited `presence.py` / `hvac.py` / `energy_const.py` as top-level.

#### 6.2.a D5 table — real `HouseState.GUEST` / `"guest"` string readers (migrate to `guests_present` flag)

| # | File:line | Today reads | Post-D5 reads | Behaviour change |
|---|---|---|---|---|
| D5-1 | `domain_coordinators/presence.py:1301` | `if current_state == HouseState.GUEST and not guest_gate_armed` (GUEST exit branch in `_evaluate_zone_state`) | flag + current state | GUEST exit replaced by flag-OFF transition on the current state (SLEEP/HOME-NIGHT/HOME). |
| D5-2 | `domain_coordinators/presence.py:1332` / `:1334` | `if current_state != HouseState.GUEST: return HouseState.GUEST` (D5 guest_room path promotion) | sets `guests_present = ON (source=guest_room)`; does NOT transition house state | House state no longer swallowed by GUEST; SLEEP+flag is legal. |
| D5-3 | `domain_coordinators/presence.py:5859` | `if current_state not in _home_like_states and current_state != HouseState.GUEST` (home-like widening) | drop the `and ... GUEST` clause; `_home_like_states` is the sole gate (flag is orthogonal) | GUEST no longer counted as a home-like state. |
| D5-4 | `domain_coordinators/presence.py:5893` | `elif current_state == HouseState.GUEST:` branch in the same block | branch deleted; folded into the preceding home-like branch under the flag | Dead branch removed with row D5-14 deprecation. |
| D5-5 | `domain_coordinators/presence.py:6467` | `if new_state == HouseState.GUEST and guest_room_gate_armed: self._inference_engine._confidence = _d5_guest_confidence` (confidence override on GUEST transition) | fires on `guests_present` ON-edge with `source=guest_room`; confidence raised on the current state | Confidence bump decoupled from state transition. |
| D5-6 | `domain_coordinators/presence.py:6565-6567` | GUEST sticky transition guard (`current_state == HouseState.GUEST ... and new_state != HouseState.GUEST`) | reinterpreted as a flag-OFF guard — no state is "sticky" because flag ON ≠ state transition | Sticky semantics moved onto the flag's OFF timer (`GUESTS_PRESENT_OFF_S`). |
| D5-7 | `domain_coordinators/presence.py:6829` / `:6833` | `if new_state == HouseState.GUEST: ... elif current_state == HouseState.GUEST:` (persistence branches) | both branches deleted; persistence keys on flag transitions in a sibling block | Persistence no longer sees GUEST as a state. |
| D5-8 | `const.py:2307` | `if hs == "guest": return NM_HAZARD_EXTERIOR_PERSON_GUEST_SEVERITY` (NM severity) | re-keyed on `guests_present` + current state cross-product | NM severity decoupled from state. |
| D5-9 | `__init__.py:2893` | `is_guest = str(payload.new_state).lower() == "guest"` (dispatch filter) | reads flag state via the new sensor | Dispatch filter follows flag. |
| D5-10 | `binary_sensor.py:2412-2445` (incl. `:2445` `== HouseState.GUEST`) | `BinarySensorEntity.is_on` for `ura_presence_coordinator_guest_mode` derived from `HouseState.GUEST` | **re-pointed** to flag; entity_id kept, `source` attribute added | External consumers unaffected. |
| D5-11 | `binary_sensor.py:3255` | `if house_state == "guest":` (interlock branch) | flag ON (any `source`) | Interlock widens to any guest evidence. |
| D5-12 | `domain_coordinators/dynamic_preset.py:861` | `if reset_under_guest and house_state == "guest":` (reset-under-guest guard) | reads flag | Reset guard follows flag. |
| D5-13 | `domain_coordinators/preset_overrides.py:147-148` (predicate `"house_state == 'guest'"`) | predicate string compared against `house_state` string | predicate rewritten to `guests_present == on`; `preset_overrides.py:54` / `:115` / `:142` comments updated in same commit | Preset-override predicate reads flag. |
| D5-14 | `domain_coordinators/house_state.py:77, 89, 94, 106, 116, 137` | `HouseState.GUEST` enum member + transitions + hysteresis `GUEST: 300` | enum member **retained for one release** (deprecated), transitions kept until row D5-16 operator-side migration ships; `infer()` never returns GUEST post-D5 (**INV-GUEST-ORTHOGONAL**) | Dead-code deprecation path. |
| D5-15 | `const.py:3055` + `const.py:3447` | `"guest"` string in state-name tuples | `"guest"` removed from tuples once D5-16 operator-side automations migrate | Operator action gates removal. |
| D5-16 | `/config/automations.yaml:8308` | `house_state == 'guest'` | operator-side migration to `is_state('binary_sensor.ura_presence_coordinator_guest_mode', 'on')` | **Not a URA edit**; notification only (per M-6 disposition). |

**Row counts:** 16 real GUEST readers (down from the inflated 25 in the prior revision; the 9 rows removed were FLOOR readers mis-attributed as GUEST — now in §6.2.b).

#### 6.2.b D6 table — `census_count` / `total_persons` (FLOOR) readers (semantic shift via D6)

These sites consume the **count**, not the GUEST state. They are the Tier 2-DB migration surface for D6 (FLOOR → `total_persons`). Behaviour is byte-identical when the D6 switch is OFF; when ON the number they read becomes FLOOR instead of the inferred `total_persons`.

| # | File:line | Today reads | Post-D6 reads | Behaviour change |
|---|---|---|---|---|
| D6-1 | `domain_coordinators/presence.py:1111` | `if census_count == 0 and not any_zone_occupied` (AWAY-infer guard) | FLOOR via `_census_count` hydration path (D6-9) | AWAY no longer fires while FLOOR>0 (per INV-AWAY-SAFE). |
| D6-2 | `domain_coordinators/presence.py:1223` | `and census_count == 0` (secondary AWAY conjunct) | FLOOR | Same as D6-1. |
| D6-3 | `domain_coordinators/presence.py:1957-1960` | `if s.kind == "census_count"` (H1 veto reader) | reads the FLOOR-sourced TransientSignal (kind kept for signal compat) | Veto trip-wire uses FLOOR. |
| D6-4 | `domain_coordinators/presence.py:2903` | `self._census_count = last.house.total_persons` (boot hydration) | hydrates from FLOOR snapshot when D6 switch ON | Boot `_census_count` = FLOOR. |
| D6-5 | `domain_coordinators/presence.py:5585` | `self._census_count >= BOOT_SETTLE_MIN_INPUTS` (boot-settle gate) | FLOOR | Boot-settle gates on measured FLOOR. |
| D6-6 | `domain_coordinators/presence.py:6218` | `self._census_count == 0` (AWAY veto denominator) | FLOOR == 0 | Denominator uses FLOOR. |
| D6-7 | `domain_coordinators/presence.py:6434` | `self._census_count == 0` (sticky AWAY branch) | FLOOR == 0 | Sticky AWAY gates on FLOOR. |
| D6-8 | `domain_coordinators/presence.py:6530` | `self._census_count > 0` (SLEEP→WAKING forcing gate) | FLOOR > 0 | Wake-force uses FLOOR. |
| D6-9 | `domain_coordinators/presence.py:6667` | `TransientSignal("census_count", self._census_count)` (producer path) | emits FLOOR as the `census_count`-kind signal (name retained for compatibility) | Signal payload = FLOOR. |
| D6-10 | `domain_coordinators/presence.py:6882-6884` | `"census_count", float(self._census_count)` (anomaly emit) | FLOOR | Anomaly z-score sources FLOOR. |
| D6-11 | `sensor.py:3636` | `return result.house.total_persons` (count sensor property) | FLOOR when D6 ON, else current `total_persons` | Count sensor reflects FLOOR. |
| D6-12 | `sensor.py:4064` | `"inside_count": result.house.total_persons` (attribute) | FLOOR | Attribute reflects FLOOR. |
| D6-13 | `sensor.py:4955` | `camera_total = house.total_persons` (analytics) | FLOOR | Analytics on FLOOR. |
| D6-14 | `binary_sensor.py:1982` | `camera_total = census.last_result.house.total_persons` | FLOOR | Diag follows FLOOR. |
| D6-15 | `binary_sensor.py:2182` | `if house.total_persons > 0:` (interlock) | FLOOR > 0 | Interlock on FLOOR. |
| D6-16 | `binary_sensor.py:2225` | `census_persons = census.last_result.house.total_persons` (night-mode interlock) | FLOOR | SLEEP interlock on FLOOR. |
| D6-17 | `aggregation.py:6346` | `camera_total = house.total_persons` (group rollup) | FLOOR | Rollup on FLOOR. |
| D6-18 | `camera_census.py:1642, 1645, 1593, 1597` | `"interior_count": house_result.total_persons`, `"property_count": property_result.total_persons` (payload) | `interior_count` **byte-identical** (INV-SHADOW-BYTE-IDENTICAL); FLOOR published as **additive** `floor` key | Legacy keys unchanged; FLOOR additive. |
| D6-19 | `camera_census.py:5740-5754, 5790, 5804` | writes `total_persons` from snapshot | writes **FLOOR** when D6 switch ON (producer side of D6-20) | Snapshot producer side. |
| D6-20 | `database.py:3935, 3945, 3965` | `result.total_persons` into `census_snapshots.total_persons` (DB writer) | FLOOR when D6 switch ON | **Tier 2-DB trigger** — payload shape unchanged (`int`), semantic shift. Pre-deploy per-table row-rate snapshot per standing Tier 2-DB rule. |
| D6-21 | `camera_census.py:1576, 1584, 2041, 2299, 5761` | arithmetic over `total_persons` (totals, exterior census) | unchanged (exterior census is NOT in FLOOR scope — operator ruling §0) | No change. Listed for completeness. |

**Non-reader (not a migration site):** `domain_coordinators/energy_const.py:636` — the "guest_mode=50" string is a **comment** on `DYNAMIC_PRESET_PRIORITY: Final = 30` (next line is `GUEST_MODE_PRIORITY: Final = 50`, used by HVAC override priority, not a GUEST-state consumer). The prior revision mis-cited this as a GUEST reader; **removed** from both tables. HVAC guest-mode override consumes the flag via `switch.ura_hvac_coordinator_guest_mode_actuation` at `domain_coordinators/hvac.py:3945` (unchanged — see §2.4).

**Kill-switch block (not a migration row):** `domain_coordinators/presence.py:5315-5317` (`if not self._guest_detection_enabled: self._clear_guest_room_first_seen(); return False`) is the **REUSED** `switch.ura_presence_guest_detection_enabled` consumer. Per M-5, no second switch; D5 keeps this gate as-is. The prior revision mis-cited the inner line `:5316` (`_clear_guest_room_first_seen`) as the switch read — fixed here.

**Switch definition:** `switch.py:3787` is the DEFINING entity + docstring block (contains the string "HouseState.GUEST" in a comment); consumed at `domain_coordinators/presence.py:5315`.

### 6.3 Open operator questions

- **Q-A** `GUESTS_PRESENT_ON_S` / `OFF_S` named-bucket defaults — propose `quick` (120/600), `normal` (600/1800), `cautious` (1800/3600). Confirm `normal` default.
- **Q-B** `CONF_MAIN_ENTRY_DOOR` single-value Select vs multi-value — recommend single for now.
- **Q-C** `census.health = absent` as attribute only, or dedicated entity — recommend attribute only.
- **Q-D** Keep `HouseState.GUEST` enum member for how long after D5? Recommend one minor release of deprecation, then remove in the next cycle after row D5-16 is operator-migrated.

---

## 7. Algorithm specification (D3) — HYBRID

### 7.1 Inputs per tick
- **`R_home`** (renamed from `R_home_awake` per #2 H1): **all tracked-home residents, any sub-state** (sleeping residents still count — they are on-premises). Symbol `R` in the formula.
- `count_cam(t)`: Frigate `person_count` per configured interior camera, watchdog-discounted.
- `S(t)`: overlap-deduped interior bodies (§5.2). Absent if no interior cams configured.
- `U_gr(t)`: designated guest rooms occupied with no known person. **Guest rooms have no cameras in the oracle household** (§4.5), so `U_gr` is spatially disjoint from `S` — BUT a guest can be simultaneously in a guest room AND on an interior camera (held in `M_cam` for up to `FLOOR_WINDOW_S` after they walked out), which is precisely the double-count H1 round-6 forces the formula to prevent via guest-side `max()`.
- `W(t)`: Revel guest phones (dormant until D4).
- Door events post-R3-dedup: `(t_e, direction, door_group, person_id|None)` with 30 s stem collapse.

**Per-event pipeline order (per reviewer #2 H2; falsifiable and deterministic):**
> **leg-collapse** (merge legs within a door_group by same physical camera via resolver, 30 s stem window)
> → **same-person rule** (within door_group, `DOOR_SAMEPERSON_S` default 10 s = same person re-detected)
> → **round-trip pairing** (entry/exit at same door_group within `DOOR_ROUNDTRIP_S` with no other evidence = net zero; see §7.2.(2))
> → **resident attribution** (person_id match OR resident tracker edge within `RESIDENT_CROSSING_MATCH_S` OR main-entry-door prior within `MAIN_ENTRY_PRIOR_S`)
> → **T accounting** (T increments ONLY on unattributed/guest crossings; resident-attributed crossings never touch T)

Each tracker edge attributes **at most one** crossing (per reviewer #2 H3): a per-tracker "attributions-consumed" set keyed on `(tracker_id, edge_ts)`, cleared at the next tracker edge of opposite direction OR at an empty anchor. Test: `test_single_resident_garage_a_ble_edge_after_crossing` (D3).

**Attribution window two-sidedness (per reviewer #2 H3):** `RESIDENT_CROSSING_MATCH_S` applies **symmetrically** — a crossing at `t_c` matches a tracker edge at `t_e` iff `|t_c − t_e| ≤ RESIDENT_CROSSING_MATCH_S`. **Provisional-apply + retroactive-reconcile:** if a crossing arrives first and no tracker edge is in-window, apply it as unattributed (increment T); if a resident tracker edge arrives within the window afterward, retroactively **decrement T** by 1 AND (per M round 6) **also decrement `T_amb` and `B` by 1 each** if the provisional was previously classified ambiguous (so the retroactive reconcile is complete across T/T_amb/B, not just T). Reconciliation is capped at `≥ 0` on every accumulator (never negative). Record the reconciliation in `floor_components.reconciled_attributions`. Test: `test_provisional_apply_reconcile_clears_t_and_t_amb_and_b`.

**Main-entry-door prior (M round 6 — stays PROVISIONAL, does NOT permanently skip T):** when `CONF_MAIN_ENTRY_DOOR` is set and a crossing fires at that door_group with no in-window resident tracker edge, apply the prior as a **provisional resident attribution** (does NOT increment T) with a `provisional_main_entry_prior` marker. If a resident tracker edge arrives within `MAIN_ENTRY_PRIOR_S` the attribution is finalized (prior consumed). If the window expires with no tracker edge, the attribution is **reversed**: T is incremented +1 retroactively, the crossing becomes an unattributed/guest entry, and the reversal is recorded in `floor_components.reversed_main_entry_priors`. This closes the "resident drops phone / BLE is slow and the prior silently absorbs a guest at the main door forever" hole.

### 7.2 FLOOR — the formula (per CR-2 + H1 round-6 guest-side `max()`)

Three lower bounds. The guest-side terms (`M_cam − R`, `U_gr`, `T`) are **maxed against each other, not summed**, to prevent double-counting a guest who is simultaneously in `U_gr` and `M_cam` (held) or in `T` and `U_gr` (entered via door, then went to the guest room).

**Single formula (per CR-2 + H1 round-6):**
```
FLOOR(t) = R(t) + max(
    0,
    max( M_cam(t) − R(t), 0 ) if M_cam present else 0,
    U_gr(t),
    T(t)
)
```

Equivalently as the review-form "three lower bounds, FLOOR = max" (unchanged structurally; the H1 fix is that the three bounds all collapse to the single `R + max(guest-side)` because the guest-side `max()` is the pointwise maximum of any guest-side bound):

1. **Resident floor:** `R(t) = |R_home(t)|` — bound (1).
2. **Camera-dominant guest term:** `max(M_cam(t) − R(t), 0)` where `M_cam(t) = max_{τ ∈ [t − FLOOR_WINDOW_S, t]} S(τ)` (held camera max; absent if no interior cams).
3. **Door-tally guest term:** `T(t)` = tally of unattributed/guest crossings since last empty anchor (never includes resident-attributed crossings per §7.1 pipeline).
4. **Guest-room guest term:** `U_gr(t)` (spatially disjoint from `S` but NOT from the held `M_cam` memory — hence the `max` with `M_cam − R`).

**Hand-check (H1 round-6 scenario — guest in guest-room AND held on camera):**
- `R = 2`, guest leaves guest room into family room 5 min ago; `U_gr` momentarily reads 1 (still in sustained-unknown-occupancy state), `M_cam = 3` (2 residents + 1 guest visible), `T = 0`.
- Old (summed) formula: `R + max(T, U_gr) = 2 + 1 = 3` AND `max(R, M_cam) + U_gr = 3 + 1 = 4` → max of bounds = **4 (double-counts the guest)**.
- New (guest-side max) formula: `R + max(M_cam − R, U_gr, T) = 2 + max(1, 1, 0) = 2 + 1 = **3**` ✓.
- Hand-check (reviewer's exact case): `R=2`, guest leaves guest room into family room — `U_gr = 0` after the sustained-unknown clears, `M_cam = 3`, `T = 0`. FLOOR = `2 + max(1, 0, 0) = 3`. ✓

**Disjointness proof (H1 round-6):** the guest-side `max()` is sound because each of the three guest-side terms is a lower bound on `|non-resident bodies on premises|`:
- `max(M_cam − R, 0)` ≤ guests visible on camera.
- `T` ≤ guests who entered via a door and have not been attributed to a resident.
- `U_gr` ≤ guests in guest rooms with no known identity.

A single guest can appear in up to all three (walked in a door, got placed in a guest room, is held on a camera). Summing counts them N times; maxing counts them once — correct for a lower bound.

Round-trip collapse and group window are properties of **T** (per §7.1 pipeline), not of the formula.

### 7.3 ESTIMATE (per CR-H-1)

**Define — no overlap with FLOOR semantics:**
`ESTIMATE(t) = FLOOR(t) + B(t)` where `B(t)` is a decaying **ambiguous/unreconciled-flow accumulator** that counts things `T` deliberately excludes:
- AMBIGUOUS crossings (per §4.3) that P-AMB did NOT promote to T;
- unreconciled main-entry-door prior misses that have **not yet reversed** into T within `MAIN_ENTRY_PRIOR_S` (the in-flight provisional window);
- `T_amb` from §4.3.

`B` is bounded `[0, DOOR_TALLY_MAX]` and decays linearly to 0 over `ESTIMATE_DECAY_S` (default 1800 s). `B` does NOT include anything already in `T` (per CR-H-1 "define what B counts that T doesn't"). Per M round 6, when a provisional in B reverses into T (prior-window expiry), B is decremented in the same tick (no double-count on reversal). If `B` would be definitionally empty on a given install (no AMBIGUOUS source), ESTIMATE = FLOOR and we document that the band collapses.

The band `ESTIMATE − FLOOR = B` is published as `floor_components.estimate_band`; a persistently zero band on an install with ambiguous crossings = a bug (test).

### 7.4 Empty anchor (per CR-3 — INDEPENDENT OF AWAY; H3 round-6 accepted still-guest erasure)

**Anchor fire condition (3-way AND, held for `EMPTY_ANCHOR_SETTLE_S`, default 900 s):**
- `R_home = ∅` (no resident tracker currently home)
- **AND** `M_cam = 0` where interior cams exist (no camera has shown a body in the held-max window) — i.e. `M_cam` has fully bled down
- **AND** `U_gr = 0` (no guest-room sustained-unknown)

**Not required:** AWAY. The anchor fires on evidence of emptiness regardless of house state (fixes the "patio-exit" repro — residents walk out the patio without triggering AWAY, cameras bleed down, anchor should fire).

**Anchor disabled on no-trackers installs (M round 6):** if `person_tracker` is empty, `R_home = ∅` cannot be verified, so the anchor is **not armed**. FLOOR degradation per §7.5; `guests_present.source=unknown`.

**Still-guest erasure is ACCEPTED (H3 round-6, operator ruling 14):** when the 3-way AND holds for `EMPTY_ANCHOR_SETTLE_S` but an unmoving guest is actually on-premises (not in `U_gr`, not seen by any camera for `FLOOR_WINDOW_S`, no tracker), the anchor **will fire and erase T**. This is explicitly accepted as the lesser evil over permanent FLOOR latching. INV-FLOOR-SOUND and INV-AWAY-SAFE carry the anchor-erasure exception in §7.11.

**On anchor fire:**
- Record `(C_pre, T_pre, T_amb_pre)` as the drift residual.
- `T → 0`, `T_amb → 0`, `B → 0`.
- **Clear the held-max buffer (M_cam history) per CR-H-2** — otherwise a stale 20-min-old peak keeps FLOOR elevated after a true-empty event.
- **Clear any in-flight provisional main-entry-door priors** (M round 6) — anchor subsumes the "did a tracker edge arrive?" question.
- **Door-tally age-out:** when **no corroborating camera body** has been seen for `DOOR_TALLY_STALE_S` (default 3600 s) and `T > 0`, decay `T` by 1 every `DOOR_TALLY_STALE_S / T_initial` with cap at 0 (per CR-3). Logged as `tally_stale_decay`.

**Lagged-floor semantics (per CR-H-2):** FLOOR shrinks to zero within `FLOOR_WINDOW_S + EMPTY_ANCHOR_SETTLE_S` of the last camera rise + outbound crossing. The window shrinks on *observed* outbound crossings: on an unattributed outbound crossing at door_group `g` with `T=0` and no camera active, start a **floor-shrink** that collapses `FLOOR_WINDOW_S → DEFAULT_CENSUS_HOLD_INTERIOR_MINUTES*60` (180 s today) for the next `FLOOR_SHRINK_HOLD_S` (default 600 s). This bounds AWAY lag to ~3 min when the exit is observed, 20 min when it is not.

**Retroactive-reconcile also clears T_amb/B (M round 6 — AMBIGUOUS garage return):** when a resident tracker edge finally arrives after an AMBIGUOUS crossing earlier counted as a provisional guest, decrement T (if P-AMB promoted it) OR decrement `T_amb` + `B` (if it went to the ambiguous accumulator). Example: AMBIGUOUS garage-A return at 11:00 counted as +1 guest (ESTIMATE high for 30 min); at 11:12 the resident's BLE edge finally fires at `garage_a` — within `RESIDENT_CROSSING_MATCH_S`-extended-for-prior = `MAIN_ENTRY_PRIOR_S` = 300 s window — reconcile decrements both `T` (if promoted) and `T_amb`/`B` (if not), ESTIMATE immediately drops.

**Updated invariant (per CR-3 + H4 round-6):**
> **INV-NO-LATCH:** given a reachable trajectory with `R_home = ∅`, `S` monotonically non-increasing to 0, and no `U_gr`, FLOOR reaches 0 within **`FLOOR_WINDOW_S + EMPTY_ANCHOR_SETTLE_S`** (plus **`BOOT_SETTLE_S`** if the trajectory straddles a restart). Prior revision wrote `max(FLOOR_WINDOW_S, EMPTY_ANCHOR_SETTLE_S)` — **wrong**, because `M_cam` must bleed down over `FLOOR_WINDOW_S` AND then the anchor must hold for `EMPTY_ANCHOR_SETTLE_S`; the operations are sequential. Fixed.

Test: `test_patio_exit_empty_anchor_fires` — residents walk out the patio (no door event, no AWAY), cameras bleed down over `FLOOR_WINDOW_S` + `EMPTY_ANCHOR_SETTLE_S`, anchor fires, FLOOR = 0. Additional test: `test_inv_no_latch_bound_after_restart` — restart during the bleed-down adds `BOOT_SETTLE_S` to the bound.

### 7.5 Graceful degradation (per CR-2 — absent terms REMOVED, not zeroed; H1 round-6 formula)

| Configuration | FLOOR (absent terms **removed** from the guest-side `max`, not zeroed) | Health |
|---|---|---|
| Interior cams + egress cams + guest rooms + phones | `R + max( max(M_cam − R, 0), U_gr, T )` | ok |
| Egress cams only (no interior) | `R + max( U_gr, T )` (camera term absent) | degraded |
| Interior cams only (no egress) | `R + max( max(M_cam − R, 0), U_gr )` (T term absent) | degraded |
| Guest rooms only | `R + U_gr` | degraded |
| **No phones/trackers (per H-5)** | `R = 0` structurally; `FLOOR = max( max(M_cam, 0), U_gr, T_from_P_AMB_only )`; `guests_present` **cannot latch ON on (a)** (reports `source=unknown`); **empty-anchor DISABLED** (M round 6, cannot verify `R_home=∅`); `guests_present = unknown` on paths (a). (b) and (c) still work | degraded; `person_tracker_absent=true`; `empty_anchor_armed=false` |
| Nothing configured | `FLOOR = R` (= 0 if no phones) | absent |

Published alongside: `census.health ∈ {ok, degraded, absent}` and `census.inputs_present` ⊂ {`camera_interior`, `door_flow`, `guest_rooms`, `revel`, `person_tracker`}, plus `empty_anchor_armed: bool` (M round 6). **"Absent" is NOT "zero"** — a missing term drops out of the `max`; a zero term participates.

### 7.6 Revel (D4)
Replace `last_changed` with `state == home` (L18); add **per-install** `CONF_REVEL_DENYLIST_HOSTNAMES` + `CONF_REVEL_ALLOWLIST_MACS` (per H-4; the hostnames in D0 §P5 are oracle examples, not shared constants); add "appeared since last empty anchor" rule. Stay OUT of FLOOR at D3 ship; enter `guests_present` (c) only after gate 5 holds on 7 consecutive household-norm days.

### 7.7 Restart / boot (per reviewer #2 H6 boot-ordering)

Persist via RestoreEntity extra data on the ESTIMATE sensor: `T`, `T_amb`, `B`, `last_anchor_ts`, `last_anchor_T_pre`, `last_anchor_C_pre`, in-flight `provisional_main_entry_priors` (M round 6), **and `M_cam_peak` + `M_cam_peak_ts`** (per M-6 "persist M_cam peak+ts"). The producer **hydrates before first publish** (per M-6 "restore at the producer with defined order"):

1. HA start → `async_added_to_hass` reads restored state.
2. Hydrate `T`, `T_amb`, `B`, `M_cam_peak`, `provisional_main_entry_priors`, `last_anchor_*` into the estimator's state object **before** the first `SIGNAL_CENSUS_UPDATED` emission.
3. First tick: compute FLOOR using hydrated state + fresh inputs (never let a boot-time `S=0` lower `M_cam_peak` while within `FLOOR_WINDOW_S` of `M_cam_peak_ts`).
4. Suppress empty-anchor evaluation for `BOOT_SETTLE_S` (default 600 s) **after hydration completes**, not after HA start — the gap matters when restore is slow. INV-NO-LATCH bound extended by `BOOT_SETTLE_S` across restart (H4 round-6).
5. Door events lost during downtime are accepted; next camera rise / crossing re-converges.

F5 (AWAY-while-residents-home across restart) is fenced by D6's INV-AWAY-SAFE but root cause is independent (side card §12-A).

### 7.8 1-vs-2-person tuning
Same as prior revision §7.8. Quiet morning (2R + 1G) → FLOOR = 3 within one tick; quiet afternoon (1R + 0G) → FLOOR = 1; single guest at main entry → FLOOR = R + 1 within `DOOR_SAMEPERSON_S`; 40-person stress case bounded, not accurate (±25%).

### 7.9 Stress case: 40 people
Unchanged from prior revision §7.9.

### 7.10 Knob ladder

| Knob | Rung | Default | Why | Kill |
|---|---|---|---|---|
| `FLOOR_WINDOW_S` → Number "Count memory" | 3 | 1200 s | Operator-tunable. | 0 = instantaneous. |
| `FLOOR_SHRINK_HOLD_S` | 1 | 600 s | Observed-exit shrink duration. | n/a |
| `DOOR_ROUNDTRIP_S` | 1 | 180 s | Out-and-back collapse. | 0 = disabled. |
| `DOOR_GROUP_WINDOW_S` | 1 | 120 s | Distinct-person group window (defined per reviewer #2 H2). | n/a |
| `DOOR_SAMEPERSON_S` | 1 | 10 s | Same-person re-detect window. | n/a |
| `DOOR_TALLY_STALE_S` | 1 | 3600 s | Age-out for uncorroborated T. | n/a |
| `DOOR_AMBIGUOUS_APPROACH_S` (NEW round 6, H2) | 1 | 60 s | P-AMB (cam-approach) window. | 0 = disables (cam-approach). |
| `DOOR_AMBIGUOUS_INTERIOR_S` (NEW round 6, H2) | 1 | 90 s | P-AMB (interior-fire) window on egress-only installs. | 0 = disables (interior-fire). |
| `AMBIGUOUS_DECAY_S` | 1 | 1800 s | `T_amb` decay. | n/a |
| `RESIDENT_CROSSING_MATCH_S` | 1 | 120 s | BLE edge window (symmetric). | n/a |
| `MAIN_ENTRY_PRIOR_S` | 1 | 300 s | Main-entry attribution; also prior-reversal window (M round 6). | n/a |
| Stem dedup window (replaces inline `5.0` at `transit_validator.py:1736`) | 1 | 30 s | D0 §P1. | n/a |
| `EMPTY_ANCHOR_SETTLE_S` | 1 | 900 s | Anchor safety. | n/a |
| `BOOT_SETTLE_S` | 1 | 600 s | Restart fence; extends INV-NO-LATCH bound (H4 round-6). | n/a |
| `DOOR_TALLY_MAX` | 1 | 30 | Sanity cap. | n/a |
| `ESTIMATE_DECAY_S` | 1 | 1800 s | B decay. | n/a |
| `ESTIMATE_SLACK` | 1 | 2 | INV-PROGRAM soft upper bound slack. | n/a |
| `GUESTS_PRESENT_MIN_COUNT` | 2 options | 1 | Set once. | n/a |
| `GUESTS_PRESENT_ON_S` / `OFF_S` → "Guest flag delay" named buckets | 2 options | normal (600/1800) | Named buckets per label guide. | n/a |
| `CONF_MAIN_ENTRY_DOOR` (Select, options derived from `CONF_DOOR_GROUPS`) | 2 options | unset | Per-install. | unset = neutral. |
| `CONF_INTERIOR_CAMERA_OVERLAP_GROUPS` (per-install) | 2 options | [] | Per-install overlap probe. | n/a |
| `CONF_DOOR_INTERIOR_NEIGHBOURS` (per-install) | 2 options | {} | Per-door nearby interior cams for direction resolution (CR-4). | empty = AMBIGUOUS fallback. |
| `CONF_DOOR_APPROACH_CAMERAS` (per-install, NEW round 6) | 2 options | {} | Per-door approach cam(s) for P-AMB (cam-approach). | empty = cam-approach disabled per-door. |
| `CONF_REVEL_DENYLIST_HOSTNAMES` / `CONF_REVEL_ALLOWLIST_MACS` (per-install) | 2 options | [] | Per-install, not shared defaults. | n/a |
| `WIFI_GUEST_RECENCY_HOURS` `const.py:3638` | **retired** (KEEP+DOCUMENT) | n/a | D4 semantic. | n/a |
| `switch.ura_census_estimator_enabled` | 3 | ON in shadow | Byte-identical fallback for D6. | OFF = legacy snapshot + legacy GUEST gate. |
| **`switch.ura_presence_guest_detection_enabled` `switch.py:3787`** | 3 | **REUSED** | Pre-existing guest-detection kill (consumer `domain_coordinators/presence.py:5315`). Per M-5, no second switch. | OFF = guest detection disabled; flag forced OFF. |

Label check: "Count memory", "Guest flag delay", "Main entry door" ≤ 3 words, no jargon.

### 7.11 Falsifiable invariants

- **INV-PROGRAM** (§0): single program invariant with explicit nameable-missed-exit exception (per CR-H-1) AND accepted anchor-erasure exception (per H3 round-6).
- **INV-FLOOR-SOUND:** `FLOOR(t) ≤ true_people(t)` unless **(i)** an exit is under-counted — every exception names the missed exit event (door_group, ts, which producer should have fired) per CR-H-1 — **OR (ii, round 6, H3) an empty anchor fired erasing T while a still unmoving guest remained on-premises** (accepted operator-ruled trade-off per §0 ruling 14; log line `anchor_erasure_accepted` emitted on each anchor fire naming the pre-anchor `T_pre` so post-ship audit can bound this error class).
- **INV-ORDER:** `FLOOR ≤ ESTIMATE` on every path.
- **INV-NO-NAME:** emptying face inputs changes no FLOOR/ESTIMATE value.
- **INV-NO-LATCH** (§7.4, per CR-3 + H4 round-6): under conditions stated, FLOOR reaches 0 within `FLOOR_WINDOW_S + EMPTY_ANCHOR_SETTLE_S` (+ `BOOT_SETTLE_S` after restart). Prior-revision `max(...)` bound was wrong; fixed to sum.
- **INV-GUEST-ORTHOGONAL** (D5): any state (including SLEEP) can co-exist with `guests_present` ON; `infer()` never returns `HouseState.GUEST`.
- **INV-AWAY-SAFE** (D6): no AWAY while `FLOOR > R` — **except** when an empty anchor has just fired erasing T (H3 round-6 accepted still-guest erasure); in that case AWAY may follow (bounded by the operator-accepted trade-off, logged `anchor_erasure_accepted`).
- **INV-SHADOW-BYTE-IDENTICAL** (D3): pre-existing payload keys byte-identical.
- **INV-ANCHOR-ZERO:** at anchor fire + `EMPTY_ANCHOR_SETTLE_S`, `T=0`, FLOOR=0 (with inputs stated).
- **INV-DEGRADE-GRACEFUL:** every config-matrix combination publishes a FLOOR with correct `census.health`; no exception, no NaN.
- **INV-NO-PHONES-NO-LATCH** (per H-5): with `person_tracker` empty, `guests_present` never latches ON on path (a) AND empty-anchor is disabled (M round 6); `guests_present.source = unknown`.
- **INV-GUEST-SIDE-MAX** (NEW round 6, H1): FLOOR never double-counts a guest who is simultaneously in `U_gr` and held in `M_cam` memory; `U_gr`, `max(M_cam − R, 0)`, and `T` are maxed, not summed. Falsifying triple: `R=2, U_gr=1, M_cam=3, T=0 → FLOOR=3` (not 4).

---

## 8. D0-REPLAY (§8a results restored INLINE per CR-1)

**Nature:** one-shot read-only. Reuses the §8a script (`census_d0/census_estimator_replay.py` in session scratchpad; promote to `scripts/probes/`).

### 8.0 Prior-D0 results (§8a of the pre-fix revision, restored inline)

- **§P1 (stem dedup convergence):** at 5 s (prod) 23% residual duplicate rows; at 15 s 7%; at **30 s** 1% residual, 0/80 over-merge → production dedup window = 30 s.
- **§P2 (`person_count` cannot resolve groups):** 15 arrival bursts over 8 days; `max(person_count)` within a 2-min burst was 1 in **14/15** cases; the one 2 came from the 10-03 playroom frame. `person_count` DISCARDED for group-size inference; USED as a per-camera held-max floor.
- **§P3 (tracker edges cover 8/42 crossings = 19%):** resident provenance is the binding gap; `EGRESS-BLE-PROVENANCE-GATE-DROPS-DEPARTURES-1` is a prerequisite (§12).
- **§P4 (Jaccard interior overlap, 8 days):** only (`family_room`, `master_hallway`) J=0.56, 1579 co-on min. All stair pairs J ≤ 0.09. `R_cam ≈ 0` because camera `area` rarely resolves — house-wide resident subtraction fix (§7.2).
- **§P5 (Revel false-positive sources):** on quiet days, 1–5 IoT survivors retained by `WIFI_GUEST_RECENCY_HOURS=4`: `garagebapu6-mesh-ea`, `officecabinetuswpro24poe`, `home-assistant-voice-*`, generic `iphone` without MAC, generic `watch`. Oracle household examples — per-install denylist (§7.6).
- **§P6 (3 verified-empty anchors over 8 days):** anchor residuals were all W (WiFi) artifacts; with W out of floor the residual is expected ≤ 1 anonymous.

**Reference-run gates on the §8a reference day (pre-fix revision):**
- G1 (ordering) PASS 100%.
- G2 (floor soundness) PASS 85% → §7.2 fix should push ≥ 95%.
- G4b (morning accuracy) FAIL at 6% (Revel-driven); with Revel out, re-score expected ≥ 90%.
- G5 (discrimination gate) unmeasurable in retention.
- G6 (anchor) PASS at all 3 anchors.

### 8.1 Truth timeline (operator-final 2026-10-04 round 4; `census_ground_truth_2026_10_03.csv` is the ORACLE)

**Oracle:** `quality/tests/fixtures/census_ground_truth_2026_10_03.csv`. Its `est_house_total` column is the per-bin truth band D0-REPLAY scores against.

**Reconciled truth table (operator-final):**

| Window (CDT) | R_home | Guests | Truth |
|---|---|---|---|
| 00:00–~08:00 | 3 (Ezinne, Oji, Jaya) | 1 long-stay (sleeping) | 4 |
| morning until ~12:00 | 3 | 0 (long-stay OUT in AM) | 3 |
| 12:00–~13:30 | 3 | 0 | 3 |
| **~afternoon** (operator drives Jaya out) | 2 (Oji, Ezinne) after drop-off; then Oji may be out | 0 | 2 then 1–2 |
| until 14:20 | ≤2 | 0 | 1–2 |
| **14:20** (+2 min) | — | **+8 at front door** as one group | 10–11 |
| evening (long-stay returns) | 2 | 8 + long-stay = 9 | 11 |
| **23:00** | 2 | 10th visitor leaves (−1) | 10 |
| **23:24** (Jaya + operator back via **`garage_a`** — BOTH residents) | 3 | 9 | 12 |
| **23:55** | 3 | 1 guest leaves (−1) | 11 |

**Fixture-vs-truth map (per bin):**

| CSV bin | CSV `est_house_total` | Reconciled truth | Verdict |
|---|---|---|---|
| 12:00 | 4-5 | 3 | **FLAG: fixture high by 1-2.** Long-stay guest was OUT in AM per operator; CSV appears to count them as present. Mark for correction. |
| 12:30 | 3-4 | 3 | Low end matches; high end FLAG same cause. |
| 13:00 | 4-5 | 3 | **FLAG.** Same cause. |
| 13:30 | 4-5 | 1-2 | **FLAG (large).** Operator had departed with Jaya by ~14:03; CSV high end is well above truth. Likely captures AM-ledger burst (12:00–13:30 audit) not real presence. |
| 14:00 | 4-5 | 1-2 | **FLAG.** Pre-arrival window. |
| 14:30 | 10-11 | 10-11 | MATCH. |
| 15:00–22:30 | 10-11 / 11-12 | 11 (post-long-stay return) | MATCH (within 1). |
| 23:00 | 11 | 10 | **FLAG by 1.** 10th visitor just left; fixture may lag the departure by one bin. |
| 23:30 | 12 | 12 (if 23:24 return counted) | MATCH. |
| 23:55 | 12 | 11 | **FLAG by 1.** Guest departure. |

Flagged rows are marked **for correction** (not for D3 to match); D0-REPLAY scores against the reconciled truth table above, not the raw CSV, and the CSV is amended in a follow-up fixture-fix card (`CENSUS-GROUND-TRUTH-CSV-FIX-1`, trivial Tier-1, carded).

### 8.2 Hybrid gates (re-weighted for 1–2 person norm)

1. **Ordering:** `FLOOR ≤ ESTIMATE` in 100% of bins.
2. **Floor soundness:** `FLOOR ≤ truth_hi` in ≥ 95% of bins (anchor-erasure bins per H3 round-6 are excluded from this metric and reported separately as `anchor_erasure_bins`).
3. **Household-norm accuracy (primary):** `|FLOOR − truth| ≤ 1` in ≥ 90% of bins between 00:00 and the 14:20 arrival.
4. **Party-band accuracy:** `|FLOOR − truth| ≤ 2` in ≥ 70% of bins after 14:20 AND `FLOOR ≥ 4` in ≥ 80% of those bins.
5. **Resident-only false-positive:** on the morning window with `R_home = 3` and 0 guests, `guest_estimate = 0` in ≥ 90% of bins.
6. **Anchor behaviour:** at every anchor tick, `T=0` within `EMPTY_ANCHOR_SETTLE_S` and FLOOR = 0.
7. **F5 replay (INV-AWAY-SAFE):** FLOOR > 0 across 15:53/16:01/17:02; AWAY would have been blocked at 15:57.
8. **Garage-A-at-23:24 attribution:** with `CONF_MAIN_ENTRY_DOOR=garage_a`, 23:24 crossing is attributed to residents (operator + Jaya), not guest.
9. **(NEW round 6, H1) Guest-side-max:** on the synthetic `R=2, U_gr=1, M_cam=3, T=0` tick, FLOOR = 3 (not 4). Property test, not replay.

**Reports (per reviewer #2 D0-REPLAY requirement):**
- **How many of the 8 front-door 14:20 entries survive leg-collapse + round-trip pairing** — reported as `d0_front_14_20_entries_surviving` with range (lower bound after collapse, upper bound before). Expected ≥ 6/8 after collapse (sanity: a 2-min burst at one door with 3 cameras is where leg-collapse earns its keep).

### 8.3 NO-GO outcomes
As prior revision; adds:
- **Gate 8 fail** → main-entry-door prior isn't firing; most likely BLE provenance too narrow (depends on `EGRESS-BLE-PROVENANCE-GATE-DROPS-DEPARTURES-1`).
- **Gate 9 fail** → H1 round-6 guest-side `max()` is implemented as a sum somewhere.

### 8.4 Open discrepancies to list for operator (not resolve)
- Audit tracker shows operator home at 15:42 — contradicts the "operator drove Jaya out in afternoon then picked her up at 23:24" narrative; may indicate operator returned home between the two Jaya trips.
- Audit ledger burst 12:00–13:30 vs the operator-stated 14:20 arrival — three possibilities: (a) early audit miscounting; (b) a smaller earlier arrival not surfaced; (c) ledger lag. Needs operator confirmation; D0-REPLAY uses 14:20 per operator ruling.

### 8.5 Per-tick order (D3, per reviewer #2 M3)
> **ingest → reconcile → anchor → assemble → publish**

- **ingest:** read camera counts, door events, tracker edges for the tick.
- **reconcile:** apply §7.1 per-event pipeline + attribution window (provisional-apply + retroactive-reconcile against any out-of-order edges, including T_amb/B decrement per M round 6).
- **anchor:** evaluate empty-anchor condition (3-way AND, §7.4); fire if settled; log `anchor_erasure_accepted` with `T_pre` if any (H3 round-6).
- **assemble:** compute `R`, `M_cam`, `T`, `U_gr`, `B`, FLOOR (guest-side `max`), ESTIMATE, `guest_estimate`, flag state.
- **publish:** emit `SIGNAL_CENSUS_UPDATED` with the full payload (pre-existing keys byte-identical).

### 8.6 Shadow golden-master methodology (per reviewer #2 M4)

Golden-master compares **pre-existing payload keys only** (per reviewer #2 M4 — not full-dict). Methodology:
- Grep full-dict consumers of `SIGNAL_CENSUS_UPDATED` first; enumerate the key set they read.
- Fixture: record pre-cycle emissions key-by-key.
- D3 shadow: emit full new payload; diff only against the enumerated pre-cycle key set. Additive keys (`estimate_floor`, `estimate`, `guest_estimate`, `door_tally`, `floor_components`, `inputs_present`, `census_health`, `empty_anchor_armed`) are explicitly excluded from the diff.
- Any consumer that iterates the full dict is a Tier-2-DB risk and gets its own test.

---

## 9. Deliverables and acceptance criteria

### D0-REPLAY — gate before D3 build
- **Verify:** `AUDIT_census_estimator_replay_2026_10_03_hybrid.md` with gates 1–9 + per-gate GO/NO-GO against the §8.1 reconciled truth.
- **Verify:** `d0_front_14_20_entries_surviving ≥ 6` (per reviewer #2).
- **Verify:** `DOOR_ROUNDTRIP_S` collapse behaviour on the 23:24-`garage_a` pair; residents attributed by main-entry-door prior.
- **Verify (NEW round 6):** gate 9 guest-side-max synthetic tick passes.
- **Live:** n/a (offline).

### D1 — Prerequisites (separate cards)
- **R1** face map fix (`camera_census.py:3216`; replace fake-API monkeypatch). Tier 1.
- **R3** door dedup across legs, 30 s stem window, replace `transit_validator.py:1736` literal. Tier 1–2. **Prerequisite for D3.**
- **`EGRESS-BLE-PROVENANCE-GATE-DROPS-DEPARTURES-1`** — prerequisite for §7.1 attribution.
- **CR-4 FIX card** `TRANSIT-DIRECTION-PER-DOOR-NEIGHBOURS-1` — Tier 2. **Prerequisite for D3** per CR-4.
- **Verify (R3):** replay of 10-03 shows < 5% same-stem duplicates.
- **Live (R3):** next day `person_entry_exit_events` shows no `garage_a` pairs < 30 s apart same direction.

### D2 — Interior overlap (per-install)
- **Verify:** `CONF_INTERIOR_CAMERA_OVERLAP_GROUPS` options-flow field exists; oracle household populated with `[["family_room","master_hallway"]]`; empty default.
- **Test:** `test_overlap_groups_components_max`; `test_overlap_empty_sums`.
- **Live:** single resident walking family_room→master_hallway → `S(t)` never exceeds 1.

### D3 — HYBRID estimator in SHADOW (Tier 2-DB)
New module `census_estimator.py` (pure core + `PersonCensus` adapter). Publishes additive keys. `interior_count` byte-identical.
- **Verify:** INV-ORDER, INV-NO-NAME, INV-ANCHOR-ZERO, INV-DEGRADE-GRACEFUL, INV-NO-LATCH, INV-NO-PHONES-NO-LATCH, **INV-GUEST-SIDE-MAX (round 6)** property tests.
- **Verify:** INV-SHADOW-BYTE-IDENTICAL golden-master per §8.6.
- **Test:** `test_estimator_replay_2026_10_03_hybrid` against §8.1 reconciled truth (CSV as oracle, flagged rows accommodated by truth table).
- **Test:** per-site mutation anchors (C-review drill):
  - neuter resident-subtraction-from-camera-term → `test_floor_does_not_double_count_residents` fails;
  - neuter guest-side `max()` → `test_floor_does_not_double_count_guest_in_room_and_on_camera` fails (H1 round-6);
  - neuter `DOOR_ROUNDTRIP_S` collapse → `test_quick_out_and_back_nets_zero` fails;
  - neuter main-entry-door prior → `test_garage_a_at_2324_attributed_to_residents` fails;
  - neuter main-entry prior-reversal → `test_main_entry_prior_reverses_to_t_on_window_expiry` fails (M round 6);
  - neuter AWAY-independent anchor → `test_patio_exit_empty_anchor_fires` fails (CR-3);
  - neuter boot fence / hydration order → `test_no_anchor_during_boot_settle` fails (H6);
  - neuter INV-NO-LATCH sum-bound → `test_inv_no_latch_bound_after_restart` fails (H4 round-6);
  - neuter P-AMB (cam-approach) → `test_ambiguous_crossing_with_approach_cam_enters_t` fails (H2 round-6);
  - neuter P-AMB (interior-fire) on egress-only → `test_egress_only_ambiguous_counted_on_interior_fire` fails (H2 round-6);
  - neuter degrade path → `test_absent_interior_cams_still_publishes_floor` fails;
  - neuter no-trackers anchor disable → `test_no_trackers_anchor_not_armed` fails (M round 6);
  - neuter two-sided attribution window → `test_single_resident_garage_a_ble_edge_after_crossing` fails (H3);
  - neuter M_cam clear on anchor → `test_m_cam_history_cleared_on_anchor` fails (CR-H-2);
  - neuter retroactive T_amb/B decrement → `test_provisional_apply_reconcile_clears_t_and_t_amb_and_b` fails (M round 6);
  - neuter per-tick order → `test_publish_sees_reconciled_t` fails (M3);
  - neuter `M_cam_peak` persistence → `test_m_cam_peak_restored_across_restart` fails (M-6).
- **Sensor:** `sensor.universal_room_automation_occupancy_estimate` with attributes `floor`, `estimate`, `band`, `door_tally`, `door_tally_ambiguous`, `guest_estimate`, `last_anchor_residual`, `inputs_present`, `census_health`, `floor_components`, `reconciled_attributions`, `reversed_main_entry_priors`, `person_tracker_absent`, `empty_anchor_armed`.
- **Live (positive drill, per M-6):** on a household-norm day, `guest_estimate = 0` all day. **Staged anonymous entry drill:** operator opens front door with no resident tracker nearby; verify `guest_estimate ≥ 1` within `GUESTS_PRESENT_ON_S`. One-shot query at disposition, not soak. **Follow-up disposition at next real gathering** replaces the open-ended "next gathering" wait of the prior revision.

### D4 — Revel filter FIX (Tier 1, ships inside D3)
- Replace `last_changed` with `state == home`.
- Per-install `CONF_REVEL_DENYLIST_HOSTNAMES` + `CONF_REVEL_ALLOWLIST_MACS` + "appeared since last empty anchor" rule.
- Retire `WIFI_GUEST_RECENCY_HOURS`; fix stale docstring at `camera_census.py:5404`.
- Dormant in FLOOR at D3 ship; promote into (c) when gate 5 holds on 7 consecutive household-norm days.
- **Verify:** `test_wifi_guest_requires_recent_join_anchor`; `test_wifi_guest_ignores_deny_list_hostnames`; `test_denylist_is_per_install`.
- **Live:** household-norm day → `wifi_guest_floor` attribute = 0 ≥ 95% of day.

### D5 — `guests_present` flag + GUEST consumer migration (Tier 3)
Per §6. Two plan reviews + re-verify before build (this doc includes round 6 fixes).
- **Verify:** INV-GUEST-ORTHOGONAL.
- **Verify:** manual override "guest" → flag ON (manual).
- **Test:** one behavioural test per row of §6.2.a (rows D5-1..D5-13), each with a source-mutation anchor.
- **Sensor:** `binary_sensor.ura_presence_coordinator_guest_mode` re-pointed to flag; new `source` attribute.
- **Live (positive drill):** staged anonymous entry → flag ON before sleep, stays ON through SLEEP, Bayesian learning suppressed, flag OFF within `GUESTS_PRESENT_OFF_S` after last guest leaves.

### D6 — Promote FLOOR to `total_persons` + AWAY-safe + empty-anchor wiring (Tier 3)
`_apply_enhanced_house_census` (`camera_census.py:5740-5754`) writes `total = FLOOR` when switch ON. `infer()` AWAY requires `FLOOR ≤ R` (except accepted anchor-erasure case per H3 round-6, logged). AWAY anchor wires to §7.4. Boot hydration order (§7.7).
- **Verify:** INV-AWAY-SAFE on F5 replay (anchor-erasure exempt); INV-ANCHOR-ZERO at every retention anchor.
- **Test:** existing AWAY-veto tests pass unchanged with switch OFF; new AWAY-safe tests pass with ON.
- **Live:** `sensor.universal_room_automation_persons_in_house` on next gathering within D0-REPLAY-accepted error; no AWAY while FLOOR > R across a restart (modulo anchor-erasure).
- **Tier 2-DB trigger named:** `census_snapshots.total_persons` (`database.py:3935, 3945, 3965`) semantic change; pre-deploy row-rate snapshot by `(coordinator, severity, type)` analogue — here per `(hour, writer)`.
- **Enumerated consumer surface:** per §6.2.b table (D6-1 .. D6-21), paths carry `domain_coordinators/` prefix where applicable. **`unidentified_count` under D6** = `max(0, FLOOR − R − |identified_guests|)` where `|identified_guests|` is the count of face-recognized guests fresh in `EGRESS_FACE_UNION_TTL_S`. Published as attribute of `sensor.universal_room_automation_persons_in_house`.

### D7 — AI-vision group count at door (PARKED)
**Revival trigger:** D0-REPLAY gate 4 fails because of group undercount, OR a real party shows `door_tally` lagging camera-visible count by ≥ 3 for ≥ `DOOR_GROUP_WINDOW_S`.

### Non-goals
- No Re-ID. No Kalman/particle. No new interior hardware. No change to exterior census. No separate CEILING sensor. No new switches beyond the one estimator kill-switch (reuse `switch.ura_presence_guest_detection_enabled` for guest-detection kill, per M-5).

---

## 10. Plan completion tracking (what this plan deliberately does NOT do)
- AI vision at door — parked D7.
- Kalman/particle — non-goal with trigger.
- Flow-driven CEILING — DISCARDED.
- Revel as floor driver — permanently out.
- F5 shutdown-window AWAY investigation — side card §12-A.
- Interior-cams-absent configuration tested on 2nd install — follow-up live validation; §D3 synthetically covers.
- Fixture CSV correction (flagged rows §8.1) — carded `CENSUS-GROUND-TRUTH-CSV-FIX-1`, Tier-1 trivial.
- `HouseState.GUEST` enum removal — one minor release after D5, gated on row D5-16 operator migration.
- Per-guest tracking that would close the H3 round-6 still-guest erasure window — explicitly out of scope; the trade-off is accepted (operator ruling 14).

---

## 11. Manual corrections (apply with D3/D5 commits)
- **Manual §4.2:** replace "hold+decay after peaks" with the hybrid, add INV-NO-NAME.
- **Manual §4.3:** correct "5 s window" to 30 s cross-leg key (with R3).
- **New §4.7 "Occupancy estimator (hybrid)":** scope, floor/estimate semantics, graceful-degradation matrix, `census.health`, **guest-side-max** (H1 round 6).
- **New §4.8 "Main entry door prior":** `CONF_MAIN_ENTRY_DOOR`, derivation from `CONF_DOOR_GROUPS`, provisional-apply + reversal (M round 6).
- **New §4.9 "Direction resolution":** per-door interior-neighbours mapping (CR-4), AMBIGUOUS P-AMB policy (H2 round 6), egress-only degradation.
- **§10 CORRECTIONS LEDGER:** stair-pair overlap candidates falsified (J ≤ 0.09); only {family_room, master_hallway}.
- **HVAC state-of-play §10:** add row — `switch.ura_hvac_coordinator_guest_mode_actuation` / `domain_coordinators/hvac.py:3945` now consume `guests_present` flag, not `HouseState.GUEST`.

---

## 12. Side findings — card them

- **A.** AWAY-while-residents-tracked-home (audit F5, 10-03 16:00–17:05). `CENSUS-F5-BOOT-AWAY-FENCE-1`. Already fired.
- **B.** `transit_validator.py:1736` stem dedup. `TRANSIT-STEM-DEDUP-30S-1` (rolled into R3).
- **C.** Dead face lookup. `CENSUS-FACE-RESOLVER-MIGRATE-1` (R1).
- **D.** Patio has no camera / mmWave. `COVERAGE-PATIO-1`.
- **E.** `EGRESS-BLE-PROVENANCE-GATE-DROPS-DEPARTURES-1` — prerequisite.
- **F.** Interior camera coverage extension — R8 (config only).
- **G.** Operator automation `/config/automations.yaml:8308` — notification only.
- **H.** Guest-free day capture — `PROBE-GUEST-FREE-DAY-1`.
- **I.** Fixture CSV correction — `CENSUS-GROUND-TRUTH-CSV-FIX-1` (§8.1 flagged rows).
- **J.** `TRANSIT-DIRECTION-PER-DOOR-NEIGHBOURS-1` — CR-4 FIX, Tier 2 prerequisite for D3.
- **K.** (NEW round 6) `CENSUS-ANCHOR-ERASURE-POSTSHIP-AUDIT-1` — scan `anchor_erasure_accepted` log lines post-ship for 2 weeks; if the error class materially exceeds the accepted-trade-off expectation, revive per-guest tracking as a Tier-3 cycle.

**Parked-card dispositions** (from §2.2): `GUEST-GATE-DOOR-IDENTITY-1` → merge into D5; `SECURITY-CENSUS-UNKNOWN-WIRE-1` → merge into D6; `GUEST-FP-RESIDUALS-1` → superseded by D4+D5; `LIGHTS-GUEST-MODE-BEHAVIOUR-1` → keep separate adjacent; `CENSUS-ACCURACY-1` → superseded by D0-REPLAY+D3; `CENSUS-GHOST-DEDUP-1` → DONE.

---

## 13. Operator ruling trail
Rounds 1–4 as prior revision. **Round 5 (2026-10-04 review-fix):** operator-provided truth timeline refined. **Round 6 (2026-10-04 re-verify fix):** operator-ruled "still guest at anchor is rare — accepted risk" (ruling 14, drives H3 anchor-erasure exception); door-group keys unified snake_case (`garage_a`/`garage_b`); main-entry-door prior stays provisional with reversal; retroactive reconcile extended to T_amb/B; INV-NO-LATCH bound = sum (was max); guest-side `max()` formula (H1).

---

## 14. Operator questions still open

Same Q-A/Q-B/Q-C as prior revision + Q-D (`HouseState.GUEST` deprecation window). All in §6.3.

---

## 15. Review-fix changelog (finding → section)

| Finding | Where addressed |
|---|---|
| CR-1 (restore §6.1/§6.2 inline, ON/OFF (a)(b)(c), §8a results, operator questions; remove ref to nonexistent REFERENCES_census_estimator.md) | §3 (ref removed, L1–L18 inlined), §6.1 (semantics + ON/OFF criteria), §6.2 (now split into §6.2.a + §6.2.b per round-6 C1), §6.3 (operator questions), §8.0 (D0 results inline) |
| CR-2 / #2 C1 (residents subtracted only from camera term; FLOOR formula; absent≠zero) | §4 verdict row "Resident subtraction scope", §7.2 (single formula with guest-side max per H1 round 6), §7.5 (degradation rows restate formula with absent terms removed) |
| CR-3 / #2 C3 (empty anchor independent of AWAY; door-tally age-out; INV-NO-LATCH; patio-exit test) | §7.4 (3-way AND fire condition, M_cam clear, DOOR_TALLY_STALE_S, patio-exit test), §7.11 (INV-NO-LATCH) |
| CR-4 (transit_validator direction FIX; per-door neighbours; ambiguous policy; egress-only degradation) | §4 verdict rows (Door flow producer; Door groups per-install), §4.3 (full FIX spec + unified P-AMB per round 6), §7.10 (new knobs), §9 D1 prereq card J |
| H-1 / #2 H-4 (program invariant falsifiable; ESTIMATE definition; INV-FLOOR-SOUND exceptions name missed exit) | §0 (INV-PROGRAM restated falsifiable), §7.3 (ESTIMATE = FLOOR + B with B defined distinct from T), §7.11 (INV-FLOOR-SOUND exception rule) |
| H-2 / #2 C4 (anchor clears M_cam; AWAY delay from 20-min hold vs 3-min today; shrink on exit or lagged-floor) | §4 verdict row "Hold/decay machinery", §7.4 (M_cam clear + FLOOR_SHRINK_HOLD_S + lagged-floor semantics) |
| H-3 (D6 consumer enumeration incl. database.py:3935 Tier 2-DB trigger; unidentified_count definition) | §9 D6 (full enumerated surface + Tier 2-DB trigger named + unidentified_count), §6.2.b (D6-20), §1 (Tier 2-DB elevation note) |
| H-4 (no house-specific names in shared paths: overlap/door groups/main-entry/Revel per-install) | §2.1 (verdict rows for Overlap, Door groups, Main-entry Select options, Revel deny-list), §4.3, §4.6, §5.2, §7.6, §7.10 |
| H-5 (no phones/trackers degradation row; guests_present must not latch when residents unidentifiable) | §6.1 (per-H-5 clause + round-6 anchor-disabled), §7.5 (no-phones row), §7.11 (INV-NO-PHONES-NO-LATCH) |
| M-1 / M-2 (missing GUEST readers added) | §6.2.a rows D5-8 (`const.py:2307`), D5-9 (`__init__.py:2893`), D5-11..D5-13, D5-14 (`domain_coordinators/house_state.py:77..137`) |
| M-3 (discriminating acceptance + positive drill; no open-ended "next gathering" wait) | §9 D3 Live (staged anonymous entry drill), §9 D5 Live |
| M-4 (shadow golden-master pre-existing keys only; grep full-dict consumers) | §8.6 |
| M-5 (reuse `switch.ura_presence_guest_detection_enabled` instead of a new switch) | §2.1 verdict row "Guest-mode kill switch", §6.2.b kill-switch block (not a migration row — line :5315), §7.10 last row, §9 Non-goals |
| M-6 (restore at producer with defined order; hydrate before publish; persist M_cam peak+ts; disposition parked cards; HVAC state-of-play) | §2.2 (parked-card dispositions), §2.4 (HVAC state-of-play added), §7.7 (producer hydration order + M_cam_peak persist), §9 D3 (test for M_cam peak restore) |
| M-7 / M-8 (parked card dispositions) | §2.2, §12 bottom |
| #2 H1 (rename R_home_awake → R_home, all tracked-home residents any sub-state) | §7.1, §7.2, §7.5, throughout — `R_home` used (symbol `R` in formula) |
| #2 H2 (per-event pipeline order; define/delete DOOR_GROUP_WINDOW_S) | §7.1 pipeline block; `DOOR_GROUP_WINDOW_S` defined (not deleted) in §2.1 and §7.10 |
| #2 D0-REPLAY report (how many of 8 front-door entries survive) | §8.2 (reports block) |
| #2 H3 (provisional-apply + retroactive reconcile; two-sided attribution window; ≤1 crossing per tracker edge; test name) | §7.1 (two-sided + provisional) + §9 D3 mutation test |
| #2 H6 (boot ordering) | §7.7 numbered boot sequence |
| #2 M3 (per-tick order ingest→reconcile→anchor→assemble→publish) | §8.5 |
| #2 M4 (shadow golden-master methodology) | §8.6 |
| Truth reconciliation + CSV oracle naming + fixture-flagged rows | §8.1 (reconciled truth table + fixture-vs-truth map + §8.4 open discrepancies + §12-I correction card) |
| **ROUND 6 C1 (§6.2 cite correctness; D5 table GUEST only; D6 table FLOOR only; `domain_coordinators/` prefix; `energy_const.py:636` is a comment)** | §6.2 completely rewritten: §6.2.a 16-row D5 GUEST table with correct cites (presence.py:1301, 1332/1334, 5859, 5893, 6467, 6565-6567, 6829/6833; `__init__.py:2893`; `const.py:2307`; `binary_sensor.py:2412-2445, 3255`; `domain_coordinators/dynamic_preset.py:861`; `domain_coordinators/preset_overrides.py:147-148`; `domain_coordinators/house_state.py:77-137`; `const.py:3055+3447`; `/config/automations.yaml:8308`), §6.2.b 21-row D6 FLOOR table with the mis-attributed rows moved here (presence.py:1111, 1223, 1957, 2903, 5585, 6218, 6434, 6530, 6667, 6882; sensor.py:3636, 4064, 4955; binary_sensor.py:1982, 2225; aggregation.py:6346; database.py:3935). Kill-switch block correctly cites `:5315` (was `:5316`). `energy_const.py:636` noted as a non-reader comment and removed from both tables. §2.5 Code surveyed line also prefixed `domain_coordinators/` throughout. |
| **ROUND 6 H1 (guest-side `max()`; prevent double-count of guest in U_gr AND M_cam)** | §0 (one-sentence restated with guest-side max; ruling 3 updated), §7.1 (U_gr-vs-M_cam disjointness note), §7.2 (new formula `R + max(0, max(M_cam−R, 0), U_gr, T)`; hand-check `R=2, U_gr=1, M_cam=3 → 3`; disjointness proof), §7.5 (degradation rows re-expressed in new formula), §7.11 (INV-GUEST-SIDE-MAX added), §8.2 (gate 9), §9 D3 (mutation anchor + INV-GUEST-SIDE-MAX property test) |
| **ROUND 6 H2 (AMBIGUOUS crossings — unified P-AMB policy; §4.3 vs §7.5 contradiction resolved; cam-approach + interior-fire; egress-only consistent; accepted-cost stated)** | §4.3 (P-AMB defined explicitly as the ONE policy; cam-approach + interior-fire conditions; accepted-cost paragraph; egress-only row made consistent — only P-AMB (interior-fire) can promote to T), §7.3 (B definition updated — AMBIGUOUS crossings P-AMB did NOT promote), §7.10 (`DOOR_AMBIGUOUS_APPROACH_S` + `DOOR_AMBIGUOUS_INTERIOR_S` + `CONF_DOOR_APPROACH_CAMERAS` knobs added), §9 D3 (two mutation anchors). |
| **ROUND 6 H3 (operator ruling: still guest at anchor is rare — accepted trade-off; anchor MAY erase T; INV-FLOOR-SOUND / INV-AWAY-SAFE exception carved)** | §0 (ruling 14 added; INV-PROGRAM exception extended), §6.1 (immediate-OFF restated to call out the trade-off), §7.4 ("Still-guest erasure is ACCEPTED" paragraph; `anchor_erasure_accepted` log line), §7.11 (INV-FLOOR-SOUND clause (ii); INV-AWAY-SAFE "except anchor-erasure" exception), §8.2 (gate 2 exclusion of anchor-erasure bins + reported separately), §9 D6 Live (modulo anchor-erasure), §12-K (post-ship audit card), §13 (ruling 14 noted). Removed contradictory "only exception is missed exit" phrasing. |
| **ROUND 6 H4 (INV-NO-LATCH bound = `FLOOR_WINDOW_S + EMPTY_ANCHOR_SETTLE_S` + `BOOT_SETTLE_S` after restart; prior `max(...)` was wrong)** | §0 (INV-PROGRAM bound statement), §7.4 (updated invariant with correct sum; rationale: bleed + anchor are sequential), §7.7 (boot step 4 notes INV-NO-LATCH extension by `BOOT_SETTLE_S`), §7.10 (`BOOT_SETTLE_S` row notes extension), §7.11 (INV-NO-LATCH updated), §9 D3 mutation (`test_inv_no_latch_bound_after_restart`). |
| **ROUND 6 MED (AMBIGUOUS garage-A return — retroactive reconcile also clears T_amb/B)** | §7.1 (reconcile extended to T_amb + B with ≥0 clamps), §7.4 ("Retroactive-reconcile also clears T_amb/B" paragraph with the 11:00/11:12 example), §9 D3 mutation (`test_provisional_apply_reconcile_clears_t_and_t_amb_and_b`). |
| **ROUND 6 MED (main-entry prior stays PROVISIONAL — does not permanently skip T; reverses to T on window expiry)** | §7.1 (full provisional + reversal spec; `provisional_main_entry_prior` marker; `floor_components.reversed_main_entry_priors`), §7.3 (B holds the in-flight provisional), §7.7 (persist `provisional_main_entry_priors` across restart), §7.10 (`MAIN_ENTRY_PRIOR_S` row notes reversal window), §9 D3 mutation (`test_main_entry_prior_reverses_to_t_on_window_expiry`), sensor attribute `reversed_main_entry_priors`. |
| **ROUND 6 MED (no-trackers home — anchor disabled; `guests_present = unknown`)** | §6.1 (per-H-5 clause extended), §7.4 ("Anchor disabled on no-trackers installs" paragraph), §7.5 (no-phones row shows `empty_anchor_armed=false`), §7.11 (INV-NO-PHONES-NO-LATCH extended), §9 D3 mutation (`test_no_trackers_anchor_not_armed`), sensor attribute `empty_anchor_armed`. |
| **ROUND 6 MED (door-key naming unified — snake_case `garage_a` / `garage_b` everywhere)** | §0 (ruling 10), §4.3 (keys), §8.1 truth table (23:24 row), §8.2 gate 8, §9 D0-REPLAY + D1. |

## Operator answers 2026-10-04 (round 5) — truth discrepancies resolved
- 15:42: operator WAS home — dropped Jaya off and came right back (so afternoon residents = 2 home: operator + Ezinne; Jaya out until ~23:24).
- 12:00–13:30 front-door burst = operator cleaning the front porch before guest arrival (resident in/out, net 0). Operator verbatim: "I also left a drop-off guy, he and I exited with a car" — i.e. an additional short visitor (drop-off) left with the operator by car; treat as transient visitor, net 0 for the day.
