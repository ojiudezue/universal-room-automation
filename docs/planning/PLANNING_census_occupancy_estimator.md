# PLANNING — Census Occupancy Estimator (HYBRID: held camera floor + deduped door tally) + `guests_present` flag

**Status:** REVISED 2026-10-04 (round 5) against two Tier-3 plan reviews (completeness + build-prediction), both FIX-PLAN. All CR/H/M findings fixed in-place; see §15 changelog for finding → section mapping. No code is changed by this document.
**Author:** ura-planner, 2026-10-04 (hybrid revision; review-fix round).
**Trigger:** `AUDIT_census_subsystem_2026_10_04.md`, `AUDIT_census_footage_ground_truth_2026_10_03.md`, D0 (§8a) NO-GO on the prior flow-ceiling design, operator rulings rounds 1–4, and the two Tier-3 plan reviews 2026-10-04.
**Canonical domain reference:** `docs/Coordinator/IDENTITY_FUSION_CAMERAS_MANUAL.md`. §11 lists corrections this plan makes to it.
**Also in-scope for institutional read:** `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` (D5 flag flows into HVAC guest-mode actuation; see §2.4).
**Supersedes:** parked card `CENSUS-GUEST-FLOOR-1`; folds in `EGRESS-INTERIOR-COUNT-REINFORCE-1`. Depends on the Tier-1 R1 (dead face lookup fix) and Tier-1/2 R3 (door-dedup) carded separately.

---

## 0. Operator-approved design (the HYBRID, in one page)

**One sentence:** FLOOR = *max of three lower bounds* — (i) `R_home_awake` (always), (ii) a held camera max over a short memory window **+** `U_gr` (guest rooms), (iii) `R + max(T, U_gr)` where `T` is the running tally of **unattributed-to-resident** door crossings since the last empty anchor — zeroed at a true-empty anchor and corroborated (not driven) by Revel guest phones once the Revel filter is fixed. **Residents are subtracted only from the camera-count term; `T` already excludes resident-attributed crossings; `U_gr` is spatially disjoint from camera areas and is NOT subtracted.** The design is tuned for 1–2 people (household norm); parties are stress, not target.

**Rulings this plan encodes (operator 2026-10-04, rounds 1–4):**
1. Cameras count bodies well; names/faces are not required for counting. **INV-NO-NAME**.
2. `guests_present` is a **flag orthogonal to house state** (SLEEP + guests is a legal combination).
3. **Hybrid floor** (not a flow-driven ceiling): held camera max + door tally of unattributed crossings; residents never double-subtracted. AWAY = true-empty anchor.
4. Door tally merges both cameras per door, 30 s stem collapse, ~120 s distinct-person group window, quick out-and-back nets zero.
5. Guest WiFi phones (Revel) are **OUT of the floor** until the D4 filter is fixed (hostname/MAC allowlist + "appeared since last empty anchor"). Corroborator-only afterward.
6. **Measured interior overlap only.** The one real pair in retention is {`family_room`, `master_hallway`} (J=0.56). All other §5.2-candidate pairs falsified.
7. Exclude Apollo MTR-1 and `sensor.upzone2_people_count` from census inputs.
8. Tuned for 1–2 people; discrimination gate measured against a household-norm day.
9. **Graceful degradation by what is configured. NO new switches** (one estimator kill-switch excepted). Interior cams absent → camera term ABSENT (not zero). Nothing configured → fall back to `R_home_awake`, publish `census.health = absent`. Perimeter alerts continue to key off existing `CONF_SECURITY_ENABLED` (`const.py:2925`).
10. **One new config question:** `CONF_MAIN_ENTRY_DOOR` (`front` | `garage_a` | `garage_b`) — resident-entry prior for door attribution. Oracle household: `garage_a`.
11. **10-03 truth** restated in §8.1.
12. Prior-art first — every proposed piece has a REUSE / FIX / DISCARD(justified) / NEW verdict in §4.
13. Side findings are side cards (§12).

**Falsifiable program invariant (D's one statement to break — now falsifiable per CR-H-1):**
*For every reachable tick t, with the inputs the system currently has, there exist publishable `FLOOR(t)` and `ESTIMATE(t)` satisfying:*
> **INV-PROGRAM:** `0 ≤ FLOOR(t) ≤ true_people(t) ≤ ESTIMATE(t) + ESTIMATE_SLACK`, AND `FLOOR(t) = 0` within `EMPTY_ANCHOR_SETTLE_S` of the empty anchor firing, AND `guests_present` is ON within `GUESTS_PRESENT_ON_S` iff at least one non-resident has been continuously on-premises for that window.

The **only** permitted exception to `FLOOR ≤ true_people` is an under-counted egress event; every exception must **name the specific exit event missed** (door_group, timestamp, which camera/tracker should have fired), per CR-H-1. D's job in §9 is to produce a legal-config reachable triple that falsifies INV-PROGRAM without a nameable missed exit.

---

## 1. Tier classification

| Phase | Deliverables | Tier | Why |
|---|---|---|---|
| **Measure** | D0-REPLAY, D2-OVERLAP | none (read-only) | Measure-Before-Build. |
| **Shadow** | D3 (hybrid estimator in shadow), D4 (Revel filter FIX) | **Tier 2-DB** | New persisted state (empty anchor + door tally); additive payload keys; `interior_count` byte-identical. **Tier 2-DB elevation is explicit here because of D6's `census_snapshots.total_persons` write-path change — see §9/D6 and the H-3 enumeration.** Three framing-disjoint reviews. |
| **Promote** | D5 (`guests_present` flag + GUEST consumer migration), D6 (FLOOR → `total_persons`; AWAY-safe binding; empty-anchor wiring) | **Tier 3** | Changes the house-state vocabulary and the count feeding AWAY veto, HVAC composition (`hvac.py:3945`), security arming, NM severity, Bayesian suppression, census persistence. Cross-coordinator trust ripple at a state-machine × time seam. Two plan reviews (done — this doc is round 5 of fixes), four framing-disjoint build reviews. |
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
| Guest-room occupancy | REUSE | `_guest_room_gate_armed` `presence.py:5303`; `CONF_ROOM_IS_GUEST_ROOM` `const.py:402`. |
| Revel guest phones | FIX | `_get_wifi_guest_count` `camera_census.py:5383-5548`; `WIFI_GUEST_RECENCY_HOURS=4` `const.py:3638` retired (KEEP+DOCUMENT). |
| Egress-face guest identities | REUSE (corroborator only) | `_get_egress_guest_ids_fresh` `camera_census.py:5695`; `EGRESS_FACE_UNION_TTL_S=300` `const.py:2734`. |
| Body-reinforcement TTL bucket | FOLDED-IN | `PLANNING_egress_interior_count_reinforce.md` D2; close `EGRESS-INTERIOR-COUNT-REINFORCE-1`. |
| `guests_present` flag entity | REUSE existing `binary_sensor.ura_presence_coordinator_guest_mode` `binary_sensor.py:2412-2445` — re-pointed to the flag, keeping entity_id. | — |
| Manual guest override | REUSE | `select.ura_presence_coordinator_house_state_override`; `HouseStateMachine.set_override`. |
| Guest-mode kill switch | **REUSE** `switch.ura_presence_guest_detection_enabled` `switch.py:3787` + consumer `presence.py:5316` — **per M-5, do NOT add a second switch**. The one new switch is the estimator kill-switch (§7.10), which is a byte-identical fallback, not a guest-mode gate. |
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
- `house_state.py:60-139` (states, transitions, hysteresis; GUEST state currently in enum).
- **`HVAC_ARCHITECTURE_STATE_OF_PLAY.md`** (per H-5 / M-6): D5's flag feeds `switch.ura_hvac_coordinator_guest_mode_actuation` and `hvac.py:3945` — the HVAC composition entry point for guest-mode presets. The plan's §6.2 row 11 keeps this surface unchanged in semantics (ON when flag ON) but migrates the SOURCE from inferred `HouseState.GUEST` to `guests_present`.

### 2.5 Code surveyed (end-to-end)
`presence.py` 1111, 1223, 1230-1349, 1957, 2903, 5290-5410, 5316, 5585, 5840-5910, 5886-5892, 6218, 6434, 6530, 6667, 6882; `sensor.py` 3636, 4064, 4955; `binary_sensor.py` 1982, 2225, 2412-2445; `aggregation.py` 6346; `database.py` 793-808, 3935 (`census_snapshots.total_persons`); `switch.py` 3787; `camera_census.py` 1690-1965, 3192-3231, 5026, 5198-5381, 5383-5548, 5638-5770, 5695, 5740-5754; `transit_validator.py` 795-834, 1167, 1724-1758, 1955-1963; `house_state.py` 60-139; `hvac.py` 3928-3974, 3945; `const.py` 1973, 2071, 2223, 2307-2311, 2373, 2712, 2925, 3055, 3447, 3528, 3544, 3553, 3638; `energy_const.py` 636.

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

### 4.3 Egress cameras — door groups and direction resolution (FIX per CR-4)

Oracle household egress cameras: `madrone_g6_entry`, `doorbell_lite`, `front_door_aerial`, `garage_a`, `garage_b`. Door groups per operator-confirmed:
- **front** = {madrone_g6_entry, front_door_aerial, doorbell_lite}
- **garageA** = {garage_a}
- **garageB** = {garage_b}

**These are per-install values, not shared defaults** (per H-4). The plan reads them from `CONF_DOOR_GROUPS` on each install.

**Direction resolution FIX (CR-4):** `_resolve_direction` (`transit_validator.py:1743-1758`) currently depends on `_get_interior_cameras_near` (`:1955-1963`), which returns ALL interior cams — degenerate on egress-only homes and insensitive to geometry. **FIX:**
1. Add **per-door nearby-camera mapping** `CONF_DOOR_INTERIOR_NEIGHBOURS: Mapping[door_group, list[interior_cam]]` (options-flow rung-2). Oracle household example: `{"front": ["foyer_fisheye", "family_room"], "garageA": ["staircase"], "garageB": ["staircase"]}`.
2. `_resolve_direction` consults ONLY the configured neighbours for the firing door_group; falls back to AMBIGUOUS when none configured or none active in window.
3. **Ambiguous-crossing policy (define per CR-4):** an AMBIGUOUS crossing does NOT enter `T`. It enters an auxiliary `T_amb` accumulator which decays over `AMBIGUOUS_DECAY_S` (default 1800 s) and feeds ESTIMATE only (never FLOOR). If `T_amb > 0` at an AWAY anchor, log a `census.anchor_residual_ambiguous` metric for post-ship bias learning.
4. **Degradation path for egress-only homes:** when `CONF_DOOR_INTERIOR_NEIGHBOURS` is empty for a door_group AND no interior cams are configured at all, treat every crossing at that door_group as AMBIGUOUS (so it does not enter FLOOR). `census.health` is `degraded` with `inputs_present` excluding `camera_interior`. FLOOR falls back to `R_home_awake + U_gr`.

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
- `source` ∈ {`estimate`, `guest_room`, `revel`, `manual`}
- `guest_estimate` (int ≥ 0)
- `last_on_ts`, `last_off_ts`
- `since_anchor_s` (seconds since last empty anchor)

**ON criterion** (flag goes ON when **any** of (a)(b)(c) holds continuously for `GUESTS_PRESENT_ON_S`, default 600 s):
- **(a) Estimate path:** `guest_estimate = max(0, FLOOR − |R_home_awake|) ≥ GUESTS_PRESENT_MIN_COUNT` (default 1).
- **(b) Guest-room path:** at least one `CONF_ROOM_IS_GUEST_ROOM` room sustained-occupied with no `_is_known_person_in_room` for `CONF_ROOM_GUEST_OCCUPANCY_THRESHOLD_MIN` (default 30 min). Independent of estimate.
- **(c) Revel path (DORMANT until D4 proves clean):** ≥1 Revel phone passed the D4 filter (allowlist + "appeared since last empty anchor"). Until D4 lands, (c) is dormant.

**OFF criterion** (flag goes OFF when **all** of the following hold for `GUESTS_PRESENT_OFF_S`, default 1800 s):
- `FLOOR ≤ |R_home_awake|` (no evidenced anonymous bodies)
- No guest-room sustained-unknown-occupied
- No Revel allowlisted phone currently `state == home`
- No manual override forcing ON

**Immediate OFF** (bypass OFF timer): an AWAY empty-anchor fires AND `U_gr = 0` AND Revel path OFF.

**Manual path:** `select.ura_presence_coordinator_house_state_override == "guest"` forces flag ON with `source = manual`; clearing the override resumes derived evaluation (with ON/OFF timers restarting from clear).

**Per H-5 degradation:** if no phones/trackers are configured (`R_home_awake` is empty-set because `person_tracker` has 0 members), `guests_present` **MUST NOT latch ON** on the estimate path — residents cannot be distinguished from guests. In that configuration flag reports `source=unknown` and remains OFF for (a); (b) and (c) continue to operate.

### 6.2 Migration table (25 rows)

Enumeration surveyed via `git grep -nE "HouseState\.GUEST|house_state == ['\"]guest|_guest_|GUEST_MODE|guest_mode"`. Each row: SOURCE (what reads GUEST today) → DESTINATION (what it reads post-D5). Orchestrator pre-ship re-greps this table (it is a hypothesis).

| # | File:line | Today reads | Post-D5 reads | Behaviour change |
|---|---|---|---|---|
| 1 | `presence.py:1111` | `HouseState.GUEST` branch in `_evaluate_zone_state` | `guests_present` flag | Zone evaluation no longer waits for state transition. |
| 2 | `presence.py:1223` | GUEST in state-dispatch | flag + current state | Dispatch keyed off flag×state cross-product. |
| 3 | `presence.py:1957` | `is_guest_state` helper | `guests_present` | Helper deprecated; forwarder for one release. |
| 4 | `presence.py:2903` | GUEST in Bayesian suppression gate | flag | **Hybrid floor** drives suppression independent of state. |
| 5 | `presence.py:5585` | GUEST → learning gate | flag | Learning paused on flag ON, any state. |
| 6 | `presence.py:5316` | `switch.ura_presence_guest_detection_enabled` consumer (**REUSED** per M-5) | unchanged | Pre-existing guest-detection kill switch — no second switch added. |
| 7 | `presence.py:6218` | GUEST veto denominator | flag | Veto denominator independent of state. |
| 8 | `presence.py:6434` | GUEST sticky-window | flag | Sticky window keyed on flag transitions. |
| 9 | `presence.py:6530` | GUEST ramp | flag | Ramp fires on flag ON edge. |
| 10 | `presence.py:6667` | GUEST entry allowance | flag | Allows entry rows during SLEEP+guests. |
| 11 | `presence.py:6882` | GUEST → HVAC composition call | flag | Routed via existing `switch.ura_hvac_coordinator_guest_mode_actuation`; `hvac.py:3945` reads flag (see §2.4 and HVAC state-of-play). |
| 12 | `sensor.py:3636` | GUEST pretty-name sensor | flag + state | Display only — "guest(s) present" shown alongside state. |
| 13 | `sensor.py:4064` | GUEST count rollup | `guest_estimate` attribute of flag | Single source of guest count. |
| 14 | `sensor.py:4955` | GUEST analytics | `guest_estimate` | Analytics key on flag. |
| 15 | `binary_sensor.py:1982` | GUEST diag | flag | Diag reports flag + source. |
| 16 | `binary_sensor.py:2225` | GUEST → night-mode interlock | flag | SLEEP allowed when flag ON. |
| 17 | `binary_sensor.py:2412-2445` | `ura_presence_coordinator_guest_mode` entity derived from GUEST | **re-pointed** to flag, entity_id kept | External consumers unaffected. |
| 18 | `aggregation.py:6346` | GUEST → group rollup | flag | Group rollup includes guest presence orthogonally. |
| 19 | `database.py:3935` | `census_snapshots.total_persons` producer (snapshot writer path) | **FLOOR via D6** | **Tier 2-DB trigger named here:** payload shape unchanged (`int`), semantic shifts from inferred to measured. Pre-deploy per-table row-rate snapshot taken (standing Tier 2-DB rule). |
| 20 | `house_state.py:77-137` | enum `HouseState.GUEST`, transitions, hysteresis `GUEST: 300` | enum member **retained** for one release (deprecated), transitions keep until external automations migrated; `infer()` never returns GUEST post-D5 (INV-GUEST-ORTHOGONAL) | Dead-code deprecation; row 21 migration path. |
| 21 | `const.py:3055` + `const.py:3447` | `"guest"` in state-name tuples | `"guest"` removed from tuples once row 23 updated by operator | Operator action (external automation) gates removal. |
| 22 | `const.py:2223` | `"guest": NM_HAZARD_EXTERIOR_PERSON_GUEST_SEVERITY` NM severity map keyed on state | **re-keyed on flag**: severity map keyed on `guests_present` + state cross-product | NM severity decoupled from state. |
| 23 | `/config/automations.yaml:8308` | `house_state == 'guest'` | operator-side migration to `is_state('binary_sensor.ura_presence_coordinator_guest_mode', 'on')` | **Not a URA edit**; notification only (per M-6 disposition). |
| 24 | `energy_const.py:636` | GUEST-state key in energy preset map | flag + state | Energy composition keyed on both axes. |
| 25 | `camera_census.py:5740-5754` (`_apply_enhanced_house_census`) | writes `total_persons` from snapshot | writes `FLOOR` when D6 switch ON | Covered by D6 (row 19 is the DB-side; this is the producer-side). |

### 6.3 Open operator questions

- **Q-A** `GUESTS_PRESENT_ON_S` / `OFF_S` named-bucket defaults — propose `quick` (120/600), `normal` (600/1800), `cautious` (1800/3600). Confirm `normal` default.
- **Q-B** `CONF_MAIN_ENTRY_DOOR` single-value Select vs multi-value — recommend single for now.
- **Q-C** `census.health = absent` as attribute only, or dedicated entity — recommend attribute only.
- **Q-D** Keep `HouseState.GUEST` enum member for how long after D5? Recommend one minor release of deprecation, then remove in the next cycle after row 23 is operator-migrated.

---

## 7. Algorithm specification (D3) — HYBRID

### 7.1 Inputs per tick
- **`R_home_awake` (renamed per H1 to `R_home`):** per reviewer #2 H1 the semantics are **all tracked-home residents, any sub-state** (sleeping residents still count — they are on-premises). The symbol in this plan is now `R_home`; `_awake` suffix removed.
- `count_cam(t)`: Frigate `person_count` per configured interior camera, watchdog-discounted.
- `S(t)`: overlap-deduped interior bodies (§5.2). Absent if no interior cams configured.
- `U_gr(t)`: designated guest rooms occupied with no known person. **Guest rooms have no cameras in the oracle household** (§4.5), so `U_gr` is spatially disjoint from `S`.
- `W(t)`: Revel guest phones (dormant until D4).
- Door events post-R3-dedup: `(t_e, direction, door_group, person_id|None)` with 30 s stem collapse.

**Per-event pipeline order (per reviewer #2 H2; falsifiable and deterministic):**
> **leg-collapse** (merge legs within a door_group by same physical camera via resolver, 30 s stem window)
> → **same-person rule** (within door_group, `DOOR_SAMEPERSON_S` default 10 s = same person re-detected)
> → **round-trip pairing** (entry/exit at same door_group within `DOOR_ROUNDTRIP_S` with no other evidence = net zero; see §7.2.(2))
> → **resident attribution** (person_id match OR resident tracker edge within `RESIDENT_CROSSING_MATCH_S` OR main-entry-door prior within `MAIN_ENTRY_PRIOR_S`)
> → **T accounting** (T increments ONLY on unattributed/guest crossings; resident-attributed crossings never touch T)

Each tracker edge attributes **at most one** crossing (per reviewer #2 H3): a per-tracker "attributions-consumed" set keyed on `(tracker_id, edge_ts)`, cleared at the next tracker edge of opposite direction OR at an empty anchor. Test: `test_single_resident_garage_a_ble_edge_after_crossing` (D3).

**Attribution window two-sidedness (per reviewer #2 H3):** `RESIDENT_CROSSING_MATCH_S` applies **symmetrically** — a crossing at `t_c` matches a tracker edge at `t_e` iff `|t_c − t_e| ≤ RESIDENT_CROSSING_MATCH_S`. **Provisional-apply + retroactive-reconcile:** if a crossing arrives first and no tracker edge is in-window, apply it as unattributed (increment T); if a resident tracker edge arrives within the window afterward, retroactively **decrement T** by 1 and record the reconciliation in `floor_components.reconciled_attributions`. Reconciliation is capped at `T > 0` (never negative). Test: provisional apply + reconcile round-trip.

### 7.2 FLOOR — the formula (per CR-2, SINGLE derivation)

Three lower bounds, FLOOR = max of them (not sum):

1. **Resident floor:** `R(t) = |R_home(t)|`.
2. **Camera-dominant floor:** `C_cam(t) = M_cam(t) + U_gr(t)` where `M_cam(t) = max_{τ ∈ [t − FLOOR_WINDOW_S, t]} S(τ)` (held camera max). **`M_cam` includes visible residents** — we subtract residents HERE because a camera that saw a resident shouldn't inflate the floor. So the resident-adjusted camera floor is `C_cam_adj(t) = max(0, M_cam(t) − R(t)) + U_gr(t) + R(t)` which algebraically = `max(R(t), M_cam(t)) + U_gr(t)`. **The identity `max(R, M_cam) + U_gr` is the implementation-friendly form.** `U_gr` is NOT subtracted (spatially disjoint, §4.5).
3. **Door-dominant floor:** `C_door(t) = R(t) + max(T(t), U_gr(t))` where `T` = tally of unattributed/guest crossings since last empty anchor (never includes resident-attributed crossings per §7.1 pipeline). `T` and `U_gr` are **maxed, not summed** (both are lower bounds on guest-count; summing would double-count a guest sleeping in the guest room who also entered via door earlier).

**Single formula (per CR-2):**
```
FLOOR(t) = max(
    R(t),                                   # (1) resident floor
    max(R(t), M_cam(t) if present else 0) + U_gr(t),   # (2) camera-dominant
    R(t) + max(T(t), U_gr(t))               # (3) door-dominant
)
```

Equivalently and compactly:
> **`FLOOR = max( R, max(T, U_gr) + R, M_cam + U_gr, R )`** where `max(T, U_gr) + R` is (3), `M_cam + U_gr` is a lower bound on (2) because `max(R, M_cam) ≥ M_cam`. The implementation uses the three-way max above; this one-liner is the review-form per CR-2.

Round-trip collapse and group window are properties of **T** (per §7.1 pipeline), not of the formula.

### 7.3 ESTIMATE (per CR-H-1)

**Define — no overlap with FLOOR semantics:**
`ESTIMATE(t) = FLOOR(t) + B(t)` where `B(t)` is a decaying **ambiguous/unreconciled-flow accumulator** that counts things `T` deliberately excludes:
- AMBIGUOUS crossings (per §4.3) that could not be classified as entry vs exit;
- unreconciled main-entry-door prior misses (window expired without a tracker edge);
- `T_amb` from §4.3.

`B` is bounded `[0, DOOR_TALLY_MAX]` and decays linearly to 0 over `ESTIMATE_DECAY_S` (default 1800 s). `B` does NOT include anything already in `T` (per CR-H-1 "define what B counts that T doesn't"). If `B` would be definitionally empty on a given install (no AMBIGUOUS source), ESTIMATE = FLOOR and we document that the band collapses.

The band `ESTIMATE − FLOOR = B` is published as `floor_components.estimate_band`; a persistently zero band on an install with ambiguous crossings = a bug (test).

### 7.4 Empty anchor (per CR-3 — INDEPENDENT OF AWAY)

**Anchor fire condition (3-way AND, held for `EMPTY_ANCHOR_SETTLE_S`, default 900 s):**
- `R_home = ∅` (no resident tracker currently home)
- **AND** `M_cam = 0` where interior cams exist (no camera has shown a body in the held-max window) — i.e. `M_cam` has fully bled down
- **AND** `U_gr = 0` (no guest-room sustained-unknown)

**Not required:** AWAY. The anchor fires on evidence of emptiness regardless of house state (fixes the "patio-exit" repro — residents walk out the patio without triggering AWAY, cameras bleed down, anchor should fire).

**On anchor fire:**
- Record `(C_pre, T_pre, T_amb_pre)` as the drift residual.
- `T → 0`, `T_amb → 0`, `B → 0`.
- **Clear the held-max buffer (M_cam history) per CR-H-2** — otherwise a stale 20-min-old peak keeps FLOOR elevated after a true-empty event.
- **Door-tally age-out:** when **no corroborating camera body** has been seen for `DOOR_TALLY_STALE_S` (default 3600 s) and `T > 0`, decay `T` by 1 every `DOOR_TALLY_STALE_S / T_initial` with cap at 0 (per CR-3). Logged as `tally_stale_decay`.

**Lagged-floor semantics (per CR-H-2):** FLOOR shrinks to zero within `max(FLOOR_WINDOW_S, EMPTY_ANCHOR_SETTLE_S)` of the last camera rise + outbound crossing. The window shrinks on *observed* outbound crossings: on an unattributed outbound crossing at door_group `g` with `T=0` and no camera active, start a **floor-shrink** that collapses `FLOOR_WINDOW_S → DEFAULT_CENSUS_HOLD_INTERIOR_MINUTES*60` (180 s today) for the next `FLOOR_SHRINK_HOLD_S` (default 600 s). This bounds AWAY lag to ~3 min when the exit is observed, 20 min when it is not.

**New invariant (per CR-3):**
> **INV-NO-LATCH:** given a reachable trajectory with `R_home = ∅`, `S` monotonically non-increasing to 0, and no `U_gr`, FLOOR reaches 0 within `max(FLOOR_WINDOW_S, EMPTY_ANCHOR_SETTLE_S)`.

Test: `test_patio_exit_empty_anchor_fires` — residents walk out the patio (no door event, no AWAY), cameras bleed down over `FLOOR_WINDOW_S + EMPTY_ANCHOR_SETTLE_S`, anchor fires, FLOOR = 0.

### 7.5 Graceful degradation (per CR-2 — absent terms REMOVED, not zeroed)

| Configuration | FLOOR (absent terms **removed** from the max, not zeroed) | Health |
|---|---|---|
| Interior cams + egress cams + guest rooms + phones | full §7.2 | ok |
| Egress cams only (no interior) | `FLOOR = max(R, R + max(T, U_gr))` (M_cam term absent) | degraded |
| Interior cams only (no egress) | `FLOOR = max(R, max(R, M_cam) + U_gr)` (T term absent) | degraded |
| Guest rooms only | `FLOOR = max(R, R + U_gr) = R + U_gr` | degraded |
| **No phones/trackers (per H-5)** | `R = 0` structurally; `FLOOR = max(0, M_cam + U_gr, max(T, U_gr))`; `guests_present` **cannot latch ON on (a)** (reports `source=unknown`); (b) and (c) still work | degraded; `person_tracker_absent=true` |
| Nothing configured | `FLOOR = R` (= 0 if no phones) | absent |

Published alongside: `census.health ∈ {ok, degraded, absent}` and `census.inputs_present` ⊂ {`camera_interior`, `door_flow`, `guest_rooms`, `revel`, `person_tracker`}. **"Absent" is NOT "zero"** — a missing term drops out of the max; a zero term participates.

### 7.6 Revel (D4)
Replace `last_changed` with `state == home` (L18); add **per-install** `CONF_REVEL_DENYLIST_HOSTNAMES` + `CONF_REVEL_ALLOWLIST_MACS` (per H-4; the hostnames in D0 §P5 are oracle examples, not shared constants); add "appeared since last empty anchor" rule. Stay OUT of FLOOR at D3 ship; enter `guests_present` (c) only after gate 5 holds on 7 consecutive household-norm days.

### 7.7 Restart / boot (per reviewer #2 H6 boot-ordering)

Persist via RestoreEntity extra data on the ESTIMATE sensor: `T`, `T_amb`, `B`, `last_anchor_ts`, `last_anchor_T_pre`, `last_anchor_C_pre`, **and `M_cam_peak` + `M_cam_peak_ts`** (per M-6 "persist M_cam peak+ts"). The producer **hydrates before first publish** (per M-6 "restore at the producer with defined order"):

1. HA start → `async_added_to_hass` reads restored state.
2. Hydrate `T`, `T_amb`, `B`, `M_cam_peak`, `last_anchor_*` into the estimator's state object **before** the first `SIGNAL_CENSUS_UPDATED` emission.
3. First tick: compute FLOOR using hydrated state + fresh inputs (never let a boot-time `S=0` lower `M_cam_peak` while within `FLOOR_WINDOW_S` of `M_cam_peak_ts`).
4. Suppress empty-anchor evaluation for `BOOT_SETTLE_S` (default 600 s) **after hydration completes**, not after HA start — the gap matters when restore is slow.
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
| `AMBIGUOUS_DECAY_S` | 1 | 1800 s | `T_amb` decay. | n/a |
| `RESIDENT_CROSSING_MATCH_S` | 1 | 120 s | BLE edge window (symmetric). | n/a |
| `MAIN_ENTRY_PRIOR_S` | 1 | 300 s | Main-entry attribution. | n/a |
| Stem dedup window (replaces inline `5.0` at `transit_validator.py:1736`) | 1 | 30 s | D0 §P1. | n/a |
| `EMPTY_ANCHOR_SETTLE_S` | 1 | 900 s | Anchor safety. | n/a |
| `BOOT_SETTLE_S` | 1 | 600 s | Restart fence. | n/a |
| `DOOR_TALLY_MAX` | 1 | 30 | Sanity cap. | n/a |
| `ESTIMATE_DECAY_S` | 1 | 1800 s | B decay. | n/a |
| `ESTIMATE_SLACK` | 1 | 2 | INV-PROGRAM soft upper bound slack. | n/a |
| `GUESTS_PRESENT_MIN_COUNT` | 2 options | 1 | Set once. | n/a |
| `GUESTS_PRESENT_ON_S` / `OFF_S` → "Guest flag delay" named buckets | 2 options | normal (600/1800) | Named buckets per label guide. | n/a |
| `CONF_MAIN_ENTRY_DOOR` (Select, options derived from `CONF_DOOR_GROUPS`) | 2 options | unset | Per-install. | unset = neutral. |
| `CONF_INTERIOR_CAMERA_OVERLAP_GROUPS` (per-install) | 2 options | [] | Per-install overlap probe. | n/a |
| `CONF_DOOR_INTERIOR_NEIGHBOURS` (per-install) | 2 options | {} | Per-door nearby interior cams for direction resolution (CR-4). | empty = AMBIGUOUS fallback. |
| `CONF_REVEL_DENYLIST_HOSTNAMES` / `CONF_REVEL_ALLOWLIST_MACS` (per-install) | 2 options | [] | Per-install, not shared defaults. | n/a |
| `WIFI_GUEST_RECENCY_HOURS` `const.py:3638` | **retired** (KEEP+DOCUMENT) | n/a | D4 semantic. | n/a |
| `switch.ura_census_estimator_enabled` | 3 | ON in shadow | Byte-identical fallback for D6. | OFF = legacy snapshot + legacy GUEST gate. |
| **`switch.ura_presence_guest_detection_enabled` `switch.py:3787`** | 3 | **REUSED** | Pre-existing guest-detection kill (consumer `presence.py:5316`). Per M-5, no second switch. | OFF = guest detection disabled; flag forced OFF. |

Label check: "Count memory", "Guest flag delay", "Main entry door" ≤ 3 words, no jargon.

### 7.11 Falsifiable invariants

- **INV-PROGRAM** (§0): single program invariant with explicit nameable-missed-exit exception (per CR-H-1).
- **INV-FLOOR-SOUND:** `FLOOR(t) ≤ true_people(t)` unless an exit is under-counted; **every exception names the missed exit event** (door_group, ts, which producer should have fired) per CR-H-1.
- **INV-ORDER:** `FLOOR ≤ ESTIMATE` on every path.
- **INV-NO-NAME:** emptying face inputs changes no FLOOR/ESTIMATE value.
- **INV-NO-LATCH** (§7.4, per CR-3): under conditions stated, FLOOR reaches 0 in bounded time.
- **INV-GUEST-ORTHOGONAL** (D5): any state (including SLEEP) can co-exist with `guests_present` ON; `infer()` never returns `HouseState.GUEST`.
- **INV-AWAY-SAFE** (D6): no AWAY while `FLOOR > R`.
- **INV-SHADOW-BYTE-IDENTICAL** (D3): pre-existing payload keys byte-identical.
- **INV-ANCHOR-ZERO:** at anchor fire + `EMPTY_ANCHOR_SETTLE_S`, `T=0`, FLOOR=0 (with inputs stated).
- **INV-DEGRADE-GRACEFUL:** every config-matrix combination publishes a FLOOR with correct `census.health`; no exception, no NaN.
- **INV-NO-PHONES-NO-LATCH** (per H-5): with `person_tracker` empty, `guests_present` never latches ON on path (a).

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
| **23:24** (Jaya + operator back via **garage A** — BOTH residents) | 3 | 9 | 12 |
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
2. **Floor soundness:** `FLOOR ≤ truth_hi` in ≥ 95% of bins.
3. **Household-norm accuracy (primary):** `|FLOOR − truth| ≤ 1` in ≥ 90% of bins between 00:00 and the 14:20 arrival.
4. **Party-band accuracy:** `|FLOOR − truth| ≤ 2` in ≥ 70% of bins after 14:20 AND `FLOOR ≥ 4` in ≥ 80% of those bins.
5. **Resident-only false-positive:** on the morning window with `R_home = 3` and 0 guests, `guest_estimate = 0` in ≥ 90% of bins.
6. **Anchor behaviour:** at every AWAY-anchor tick, `T=0` within `EMPTY_ANCHOR_SETTLE_S` and FLOOR = 0.
7. **F5 replay (INV-AWAY-SAFE):** FLOOR > 0 across 15:53/16:01/17:02; AWAY would have been blocked at 15:57.
8. **Garage-A-at-23:24 attribution:** with `CONF_MAIN_ENTRY_DOOR=garage_a`, 23:24 crossing is attributed to residents (operator + Jaya), not guest.

**Reports (per reviewer #2 D0-REPLAY requirement):**
- **How many of the 8 front-door 14:20 entries survive leg-collapse + round-trip pairing** — reported as `d0_front_14_20_entries_surviving` with range (lower bound after collapse, upper bound before). Expected ≥ 6/8 after collapse (sanity: a 2-min burst at one door with 3 cameras is where leg-collapse earns its keep).

### 8.3 NO-GO outcomes
As prior revision; adds:
- **Gate 8 fail** → main-entry-door prior isn't firing; most likely BLE provenance too narrow (depends on `EGRESS-BLE-PROVENANCE-GATE-DROPS-DEPARTURES-1`).

### 8.4 Open discrepancies to list for operator (not resolve)
- Audit tracker shows operator home at 15:42 — contradicts the "operator drove Jaya out in afternoon then picked her up at 23:24" narrative; may indicate operator returned home between the two Jaya trips.
- Audit ledger burst 12:00–13:30 vs the operator-stated 14:20 arrival — three possibilities: (a) early audit miscounting; (b) a smaller earlier arrival not surfaced; (c) ledger lag. Needs operator confirmation; D0-REPLAY uses 14:20 per operator ruling.

### 8.5 Per-tick order (D3, per reviewer #2 M3)
> **ingest → reconcile → anchor → assemble → publish**

- **ingest:** read camera counts, door events, tracker edges for the tick.
- **reconcile:** apply §7.1 per-event pipeline + attribution window (provisional-apply + retroactive-reconcile against any out-of-order edges).
- **anchor:** evaluate empty-anchor condition (3-way AND, §7.4); fire if settled.
- **assemble:** compute `R`, `M_cam`, `T`, `U_gr`, `B`, FLOOR, ESTIMATE, `guest_estimate`, flag state.
- **publish:** emit `SIGNAL_CENSUS_UPDATED` with the full payload (pre-existing keys byte-identical).

### 8.6 Shadow golden-master methodology (per reviewer #2 M4)

Golden-master compares **pre-existing payload keys only** (per reviewer #2 M4 — not full-dict). Methodology:
- Grep full-dict consumers of `SIGNAL_CENSUS_UPDATED` first; enumerate the key set they read.
- Fixture: record pre-cycle emissions key-by-key.
- D3 shadow: emit full new payload; diff only against the enumerated pre-cycle key set. Additive keys (`estimate_floor`, `estimate`, `guest_estimate`, `door_tally`, `floor_components`, `inputs_present`, `census_health`) are explicitly excluded from the diff.
- Any consumer that iterates the full dict is a Tier-2-DB risk and gets its own test.

---

## 9. Deliverables and acceptance criteria

### D0-REPLAY — gate before D3 build
- **Verify:** `AUDIT_census_estimator_replay_2026_10_03_hybrid.md` with gates 1–8 + per-gate GO/NO-GO against the §8.1 reconciled truth.
- **Verify:** `d0_front_14_20_entries_surviving ≥ 6` (per reviewer #2).
- **Verify:** `DOOR_ROUNDTRIP_S` collapse behaviour on the 23:24-garageA pair; residents attributed by main-entry-door prior.
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
- **Verify:** INV-ORDER, INV-NO-NAME, INV-ANCHOR-ZERO, INV-DEGRADE-GRACEFUL, INV-NO-LATCH, INV-NO-PHONES-NO-LATCH property tests.
- **Verify:** INV-SHADOW-BYTE-IDENTICAL golden-master per §8.6.
- **Test:** `test_estimator_replay_2026_10_03_hybrid` against §8.1 reconciled truth (CSV as oracle, flagged rows accommodated by truth table).
- **Test:** per-site mutation anchors (C-review drill):
  - neuter resident-subtraction-from-camera-term → `test_floor_does_not_double_count_residents` fails;
  - neuter `DOOR_ROUNDTRIP_S` collapse → `test_quick_out_and_back_nets_zero` fails;
  - neuter main-entry-door prior → `test_garage_a_at_2324_attributed_to_residents` fails;
  - neuter AWAY-independent anchor → `test_patio_exit_empty_anchor_fires` fails (CR-3);
  - neuter boot fence / hydration order → `test_no_anchor_during_boot_settle` fails (H6);
  - neuter degrade path → `test_absent_interior_cams_still_publishes_floor` fails;
  - neuter two-sided attribution window → `test_single_resident_garage_a_ble_edge_after_crossing` fails (H3);
  - neuter M_cam clear on anchor → `test_m_cam_history_cleared_on_anchor` fails (CR-H-2);
  - neuter per-tick order → `test_publish_sees_reconciled_t` fails (M3);
  - neuter `M_cam_peak` persistence → `test_m_cam_peak_restored_across_restart` fails (M-6).
- **Sensor:** `sensor.universal_room_automation_occupancy_estimate` with attributes `floor`, `estimate`, `band`, `door_tally`, `door_tally_ambiguous`, `guest_estimate`, `last_anchor_residual`, `inputs_present`, `census_health`, `floor_components`, `reconciled_attributions`, `person_tracker_absent`.
- **Live (positive drill, per M-6):** on a household-norm day, `guest_estimate = 0` all day. **Staged anonymous entry drill:** operator opens front door with no resident tracker nearby; verify `guest_estimate ≥ 1` within `GUESTS_PRESENT_ON_S`. One-shot query at disposition, not soak. **Follow-up disposition at next real gathering** replaces the open-ended "next gathering" wait of the prior revision.

### D4 — Revel filter FIX (Tier 1, ships inside D3)
- Replace `last_changed` with `state == home`.
- Per-install `CONF_REVEL_DENYLIST_HOSTNAMES` + `CONF_REVEL_ALLOWLIST_MACS` + "appeared since last empty anchor" rule.
- Retire `WIFI_GUEST_RECENCY_HOURS`; fix stale docstring at `camera_census.py:5404`.
- Dormant in FLOOR at D3 ship; promote into (c) when gate 5 holds on 7 consecutive household-norm days.
- **Verify:** `test_wifi_guest_requires_recent_join_anchor`; `test_wifi_guest_ignores_deny_list_hostnames`; `test_denylist_is_per_install`.
- **Live:** household-norm day → `wifi_guest_floor` attribute = 0 ≥ 95% of day.

### D5 — `guests_present` flag + GUEST consumer migration (Tier 3)
Per §6. Two plan reviews before build (this doc includes both review-fix passes).
- **Verify:** INV-GUEST-ORTHOGONAL.
- **Verify:** manual override "guest" → flag ON (manual).
- **Test:** one behavioural test per row of §6.2 that changes behaviour (rows 1-11, 15-19, 22), each with a source-mutation anchor.
- **Sensor:** `binary_sensor.ura_presence_coordinator_guest_mode` re-pointed to flag; new `source` attribute.
- **Live (positive drill):** staged anonymous entry → flag ON before sleep, stays ON through SLEEP, Bayesian learning suppressed, flag OFF within `GUESTS_PRESENT_OFF_S` after last guest leaves.

### D6 — Promote FLOOR to `total_persons` + AWAY-safe + empty-anchor wiring (Tier 3)
`_apply_enhanced_house_census` (`camera_census.py:5740-5754`) writes `total = FLOOR` when switch ON. `infer()` AWAY requires `FLOOR ≤ R`. AWAY anchor wires to §7.4. Boot hydration order (§7.7).
- **Verify:** INV-AWAY-SAFE on F5 replay; INV-ANCHOR-ZERO at every retention anchor.
- **Test:** existing AWAY-veto tests pass unchanged with switch OFF; new AWAY-safe tests pass with ON.
- **Live:** `sensor.universal_room_automation_persons_in_house` on next gathering within D0-REPLAY-accepted error; no AWAY while FLOOR > R across a restart.
- **Tier 2-DB trigger named:** `census_snapshots.total_persons` (`database.py:3935`) semantic change; pre-deploy row-rate snapshot by `(coordinator, severity, type)` analogue — here per `(hour, writer)`.
- **Enumerated consumer surface** (per H-3): `presence.py:1111, 1223, 1957, 2903, 5316, 5585, 6218, 6434, 6530, 6667, 6882`; `sensor.py:3636, 4064, 4955`; `binary_sensor.py:1982, 2225, 2412-2445`; `aggregation.py:6346`; `database.py:3935`. **`unidentified_count` under D6** = `max(0, FLOOR − R − |identified_guests|)` where `|identified_guests|` is the count of face-recognized guests fresh in `EGRESS_FACE_UNION_TTL_S`. Published as attribute of `sensor.universal_room_automation_persons_in_house`.

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
- `HouseState.GUEST` enum removal — one minor release after D5, gated on row 23 operator migration.

---

## 11. Manual corrections (apply with D3/D5 commits)
- **Manual §4.2:** replace "hold+decay after peaks" with the hybrid, add INV-NO-NAME.
- **Manual §4.3:** correct "5 s window" to 30 s cross-leg key (with R3).
- **New §4.7 "Occupancy estimator (hybrid)":** scope, floor/estimate semantics, graceful-degradation matrix, `census.health`.
- **New §4.8 "Main entry door prior":** `CONF_MAIN_ENTRY_DOOR`, derivation from `CONF_DOOR_GROUPS`.
- **New §4.9 "Direction resolution":** per-door interior-neighbours mapping (CR-4), AMBIGUOUS semantics, egress-only degradation.
- **§10 CORRECTIONS LEDGER:** stair-pair overlap candidates falsified (J ≤ 0.09); only {family_room, master_hallway}.
- **HVAC state-of-play §10:** add row — `switch.ura_hvac_coordinator_guest_mode_actuation` / `hvac.py:3945` now consume `guests_present` flag, not `HouseState.GUEST`.

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

**Parked-card dispositions** (from §2.2): `GUEST-GATE-DOOR-IDENTITY-1` → merge into D5; `SECURITY-CENSUS-UNKNOWN-WIRE-1` → merge into D6; `GUEST-FP-RESIDUALS-1` → superseded by D4+D5; `LIGHTS-GUEST-MODE-BEHAVIOUR-1` → keep separate adjacent; `CENSUS-ACCURACY-1` → superseded by D0-REPLAY+D3; `CENSUS-GHOST-DEDUP-1` → DONE.

---

## 13. Operator ruling trail
Rounds 1–4 as prior revision. **Round 5 (2026-10-04 review-fix):** operator-provided truth timeline refined (3 residents, long-stay guest status, 8-guest arrival at front door, 23:24 garage-A dual-resident return, 23:00 and 23:55 departures). Open discrepancies §8.4 flagged for operator confirmation, not resolved by this plan.

---

## 14. Operator questions still open

Same Q-A/Q-B/Q-C as prior revision + Q-D (`HouseState.GUEST` deprecation window). All in §6.3.

---

## 15. Review-fix changelog (finding → section)

| Finding | Where addressed |
|---|---|
| CR-1 (restore §6.1/§6.2 inline, ON/OFF (a)(b)(c), §8a results, operator questions; remove ref to nonexistent REFERENCES_census_estimator.md) | §3 (ref removed, L1–L18 inlined), §6.1 (semantics + ON/OFF criteria), §6.2 (25-row table), §6.3 (operator questions), §8.0 (D0 results inline) |
| CR-2 / #2 C1 (residents subtracted only from camera term; FLOOR formula; absent≠zero) | §4 verdict row "Resident subtraction scope", §7.2 (single formula with max), §7.5 (degradation rows restate formula with absent terms removed) |
| CR-3 / #2 C3 (empty anchor independent of AWAY; door-tally age-out; INV-NO-LATCH; patio-exit test) | §7.4 (3-way AND fire condition, M_cam clear, DOOR_TALLY_STALE_S, patio-exit test), §7.11 (INV-NO-LATCH) |
| CR-4 (transit_validator direction FIX; per-door neighbours; ambiguous policy; egress-only degradation) | §4 verdict rows (Door flow producer; Door groups per-install), §4.3 (full FIX spec), §7.10 (new knobs), §9 D1 prereq card J |
| H-1 / #2 H-4 (program invariant falsifiable; ESTIMATE definition; INV-FLOOR-SOUND exceptions name missed exit) | §0 (INV-PROGRAM restated falsifiable), §7.3 (ESTIMATE = FLOOR + B with B defined distinct from T), §7.11 (INV-FLOOR-SOUND exception rule) |
| H-2 / #2 C4 (anchor clears M_cam; AWAY delay from 20-min hold vs 3-min today; shrink on exit or lagged-floor) | §4 verdict row "Hold/decay machinery", §7.4 (M_cam clear + FLOOR_SHRINK_HOLD_S + lagged-floor semantics) |
| H-3 (D6 consumer enumeration incl. database.py:3935 Tier 2-DB trigger; unidentified_count definition) | §9 D6 (full enumerated surface + Tier 2-DB trigger named + unidentified_count), §6.2 (row 19), §1 (Tier 2-DB elevation note) |
| H-4 (no house-specific names in shared paths: overlap/door groups/main-entry/Revel per-install) | §2.1 (verdict rows for Overlap, Door groups, Main-entry Select options, Revel deny-list), §4.3, §4.6, §5.2, §7.6, §7.10 |
| H-5 (no phones/trackers degradation row; guests_present must not latch when residents unidentifiable) | §6.1 (per-H-5 clause), §7.5 (no-phones row), §7.11 (INV-NO-PHONES-NO-LATCH) |
| M-1 / M-2 (missing GUEST readers added) | §6.2 rows added for `const.py:3447, 3055, 2223`, `house_state.py:77-137` (row 20), `energy_const.py:636` (row 24) |
| M-3 (discriminating acceptance + positive drill; no open-ended "next gathering" wait) | §9 D3 Live (staged anonymous entry drill), §9 D5 Live |
| M-4 (shadow golden-master pre-existing keys only; grep full-dict consumers) | §8.6 |
| M-5 (reuse `switch.ura_presence_guest_detection_enabled` instead of a new switch) | §2.1 verdict row "Guest-mode kill switch", §6.2 row 6, §7.10 last row, §9 Non-goals |
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
