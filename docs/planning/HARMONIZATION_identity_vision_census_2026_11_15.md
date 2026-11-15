# HARMONIZATION: identity / vision / census arc, plans in flight (2026-11-15)

Read-only audit by ura-planner. No plan, card or code was edited; the only file written is this one. Code citations are
develop @ c0a7c59d unless a branch is named. Operator brief (2026-11-15): "We have plans we haven't executed. Or in
progress. Check for consistency and plan to harmonize and make sure sequence is right."

Read completely: charter `ARC_DRIFT_ANALYSIS_identity_vision_census_2026_11_13.md` (incl. 11-15 additions), `.claude/skills/ura-arc/SKILL.md`,
`ARC_identity_vision_census_map.md`. Read by section with greps (disclosed gap, the docs are 300-3000 lines):
`CONTRACT_person_awareness_layer.md` (§2, §4, §5 G1-G9), `PLANNING_crossing_vision.md` (header, §0, Phase 3, §6-§8 in
full), `PLANNING_vision_interior_sightings.md` (§1, §1a, §5, §7, §8, §8c, §9.D4/D5, §12, §14-§16), `PLANNING_census_deconfliction.md`
(§3.2-§3.4, §7, §8), step 7 rev 3.1 (header, §13, G3 / direction sites), step 8 (develop rev 2 AND branch
`plan/identity-actions-v6-rev3` rev 3.4, header + §10), music repair (header, BLE rows), NVR witness (header, W2/W5,
sequence), ship 3 plan (3b U/Wr text), stream health, read API, sighting layer (header + area lines). Audits read in
full: watched set, crossing pipeline, entry/foyer; door accuracy and crossing-day audits by section; media-room fan
audit §0-§1, §4-§6. `AUDIT_upguest_fan_held_occupancy_2026_11_15.md` does not exist; `PLANNING_person_awareness_leak_cleanup.md`
does not exist (the work is card LAYER-LEAK-CLEANUP-1, planned, plan card LAYER-LEAK-CLEANUP-PLAN-1 parked).
**The presence and HVAC state-of-play docs were NOT read completely.** This audit asserts no presence or HVAC mechanism of
its own; presence claims below come from audits that did read them (media-room fan audit) or from code read here.

---

## 1. Plan inventory

| Plan | Status (verified) | Branch / last commit | Charter goal served | F1-F5 |
|---|---|---|---|---|
| `PLANNING_crossing_vision.md` Phase 1-2 | Phase 1 live (shadow switch on). P2-D1-D3 ledger + census-p2 merged (`feature/census-deconfliction-p2-ledger` 0 ahead of develop). P2-D8 fast stage built + reviewed, **unmerged** | `feature/crossing-vision-fast-stage` 921c9c47, 5 ahead | census accuracy, "bullet proof at entry", two-stage latency | P: F3 attributes, ledger term (F2-A input). C: F3 bus/ring |
| same, **Phase 3** (P3-D0..D7) | written 2026-11-15, **unreviewed** (Tier 3 needs two plan reviews + G) | develop 810075a3 | "Is Vision working as designed... door crossing... counting well?"; "Vision on crossing with no clear direction - of course" | P: F3 attrs `vision_direction`, `vision_people_count`, `direction_agreement`, `pass_key` via G3. C: F3 |
| `PLANNING_vision_interior_sightings.md` | APPROVED; ship 1 (D0 probe, D1 records, D5 no-model leg) build in progress; branch has **0 commits** beyond the plan | `feature/interior-vision-d1` = 7b818ce1 | "Interior vision is meant to supplement person counts sensors... describe"; "tight and not deferred" | P: F4-shaped unnamed room records → F2-A term (D4). C: F1 (`persons_in_room`), F3 (D5), F4 faces |
| `PLANNING_census_deconfliction.md` | CD1-CD3 **shipped** (v5.108.23); CD4 flips gated | develop | "guests should be both vision and frigate/protect person counts with deconfliction" | P: F2-T (unchanged), F2-A |
| `PLANNING_person_awareness_layer_ship3.md` | 3a shipped (v5.108.24), 3b shipped (v5.108.25, DEAD-CAMERA-DEVICE-RULE-1 shipped_organic) | develop | "consumers can read and producers can feed"; "no leaks"; dead-camera rule | layer plumbing for all |
| leak cleanup | no plan file; card LAYER-LEAK-CLEANUP-1 planned, plan card parked | n/a | "no leaks" | n/a |
| `PLANNING_nvr_witness_layer.md` (W2-W6) | planned, reviewed 3x (11-13), **predates 3b**, Tier 3 | develop; W1 merged (`feature/nvr-witness-w1-pairing` 0 ahead) | dual NVR "cross compare to reduce errors"; "if even one nvr has the cam..." | P: per-camera witness record. C: Frigate + Protect person entities |
| `PLANNING_egress_direction_aware_identity.md` (step 7) rev 3.1 | planned; waiting on contract amendment + operator §13 answers; **not re-reviewed since 3.1** | develop | "egress only names people who are already home... It should do both"; arrivals accuracy | P: F3 identity attach (`arrival_confirmed`, `pair_resolved`), F5 `camera_egress`. C: F1, path map |
| `PLANNING_identity_actions_v6.md` (step 8) | develop holds **rev 2**; rev 3.4 is on **unmerged** `plan/identity-actions-v6-rev3` f20f54bc (10 ahead). §10.1 parallel set built, **unreviewed** | build `feature/step8-identity-actions` 275b9a92 (forked from music at c5685b5f, BEFORE music's review-C fix-ups) | v6.0.0 "get a move on"; personalization "Don't want to defer too much" | C: F5 (`subscribe_person_arriving`), F1 edges, F3 arrival record, F4 BLE room |
| `PLANNING_music_following_repair.md` | built, reviewed (A/B/C incl. two C fix-up rounds), **unshipped since 11-14** | `feature/music-following-repair` e31fe83a, 15 ahead | "No shadow mode... must work on day 1" | C: F4 BLE transitions |
| `PLANNING_person_sighting_layer.md` | Phase 1 shipped in parts; Phase 2 = step 7 | develop | F1-F5 home | P: F4; F5 via D2 |
| `PLANNING_camera_input_stream_health.md` | S1, S2 shipped (branches 0 ahead) | develop | "A dead camera is... faulty equipment" | evidence service (held / released) |
| `PLANNING_person_awareness_read_api.md` | ship 1 shipped (v5.108.21); ship 2 = LAYER-LEAK-CLEANUP / PERSON-ID-INLINE-SWEEP-1 | develop | one read surface | read surface |
| G6-ONE-BLE-ROOM-READ-1 | card planned, no plan; "dispatch planning the moment ship 3 merges" (ship 3 merged 11-15) | n/a | one BLE-in-room meaning | F4 BLE read |
| ZONE-CAMERA-DISCOVERY-DEVICE-AREA-1 | waiting_operator (APPROVE A: device-area fallback) | n/a | cameras feeding rooms, zones, census | evidence plumbing |
| MEDIAROOM-FAN-LEFT-ON-STUCK-SENSORS-1 | investigating; audit done | n/a | (presence / fan, touches ledger anchor) | evidence quality |
| BLE-ARRIVAL-PRODUCER-HVAC-GATED-1 | planned T2; a v6.0.0 prerequisite (step 8 rev 3.4 §10) | n/a | arrivals | P: F5 BLE |

Board (batch person-sightings, 46 open cards listed by status in the scratch query): the arc-critical open ones are
VISION-AMBIGUOUS-CROSSINGS-1 (planned T3), DOOR-VISION-GROUP-UNDERCOUNT-1 (planned T2), VISION-INTERIOR-SIGHTINGS-1
(in_progress), EGRESS-DIRECTION-AWARE-IDENTITY-1 (planned T3), NVR-WITNESS-CONSOLIDATION-1 (planned T3),
G6-ONE-BLE-ROOM-READ-1, BLE-ARRIVAL-PRODUCER-HVAC-GATED-1, LAYER-LEAK-CLEANUP-1 (planned), EGRESS-OUTCOME-WEEKLY-LABEL-1
(waiting_operator), ZONE-CAMERA-DISCOVERY-DEVICE-AREA-1 (waiting_operator), BERMUDA-DISTANCE-SENSORS-DEAD-1
(waiting_operator). MUSIC-FOLLOWING-TRANSFER-REPAIR-1 shows `planned` with next "Tier 2 build after the vision-arc
builds free a builder slot", which is stale (it is built and reviewed). HA-FOYER-CAMERA-AREA-ALIGN-1 is
`shipped_organic` but had no effect (§3, S3).

---

## 2. Consistency conflicts (each with a decided resolution)

**C1. The ledger has never been `known`; every door-vision benefit is behind a blocked anchor.** Crossing plan P2-D2
step 2 holds the empty-house anchor while any Tier-1 input is "held"; `_held_inputs` (`crossing_vision.py:1110-1177`)
reads raw `hass.states` for every Tier-1 entity plus the stream view, and does NOT honour the room's stuck-signal
exclusion. Live: ledger `unknown` since boot (`AUDIT_crossing_pipeline_after_v5_108_24.md` §5; `AUDIT_crossing_vision_day_2026_11_14.md`
§4: "Known L on 11-14: never", 0 anchor rows ever). Held set on an AWAY house: media room Matter radar on 18 h
(the room already excluded it at 4 h), the flapping Meross bit, upguest Hobeian, study A, master bath. Census bar e
(known ≥ 90 %, `PLANNING_census_deconfliction.md:139`) and bar a (≥ 10 anchors) are unreachable while this holds, so
F-LEAD, F-NOTIFY and the census use of P3-D3/D4 can never fire. Phase 3 does not address it (its producer check notes
it at `PLANNING_crossing_vision.md` Phase 3 "(4) Ledger terms: zero term rows").
*Resolution:* a small Tier-2 crossing-vision deliverable (call it P3-D8, "anchor honours stuck exclusion") ships
BEFORE P3-D3: an input the room fusion has excluded as stuck-continuous or chatter does not hold the anchor; an
`unavailable` / dead input still holds (operator rule "dead sensor = faulty equipment... hold, never release"). Reuse
the stuck-signal exclusion map (the room's exclusion set; same source `sensor.ura_stuck_signal_watchdog` reads,
`sensor.py:5728` per the fan audit) through a public getter, never a hass.data scan (contract G7 rule). The policy
line (stuck-excluded ≠ held) is an operator decision (§7 D3). Trip-wire already exists: `crossing_ledger_anchor_zero`.

**C2. `deconflict_house` signature: interior adds keywords, Phase 3 changes the ledger term only.** Code today:
`deconflict_house(trust, *, guest_vis, vision_leads, flag_min, extra_guest_terms=None)` (`census_deconflict.py:90-97`).
Interior §9.D4 adds `interior_term=None, interior_leads=False` (`PLANNING_vision_interior_sightings.md:543-546`) and
asks the census plan §3.3 and §3.2 to change (`:703-705`). Phase 3 changes no signature: P3-D4/D7 change what the ledger
emits (`cluster_terms` `crossing_ledger.py:172-203`), i.e. the value of `guest_vis`, and P3-D7 bumps
`pipeline_version`, which "resets the census bars a-e window" (Phase 3 P3-D7). No textual collision; two semantic ones:
(a) interior's "lower bound" rule uses `base = ledger when L` (`:532-534`), so a P3-D7 flip changes interior's base
without interior's bar knowing; (b) the census plan names the leads flag `L` / `CROSSING_VISION_AWARENESS_VISION_LEADS`
while the code parameter is `vision_leads`. *Resolution:* census plan §3.3 is the one owner; the orchestrator applies
interior's §14 edit there now (it is approved) and adds one line: "a `pipeline_version` bump on the ledger resets the
ledger's bars only; interior's bar counts interior grades only". Interior ship 5 is the only build that touches the
signature; Phase 3 builds must not touch it (add to Phase 3 non-goals). Name the parameter `vision_leads` in all plan text.

**C3. Interior D5 reads a crossing field nobody writes.** Interior D5 takes `n` from "crossing vision's `people_count`
from `get_crossing(source_ref)` once the fast stage writes it as a G3 attribute" (`PLANNING_vision_interior_sightings.md:502-503`).
The fast stage writes provisional rows only and never a term or a G3 attribute (contract G8, `CONTRACT_person_awareness_layer.md:367`);
Phase 3 P3-D3 is the first production G3 writer and names the field `vision_people_count`, role `vision_direction`.
*Resolution:* interior D5 reads `vision_people_count` from `get_crossing` (P3-D3 attribute), then the arrival record,
then `bodies_nvr` (order unchanged). Until P3-D3 ships the first source is simply absent (n_source says so). Plan edit,
no re-review (a field rename inside an approved order).

**C4. Interior D5 path windows vs Phase 3 pass collapse and term hold.** D5 opens a path window per `entry` crossing
(`:490-493`). The 11-14 audit found 21 of 25 clustered members were opposite-direction twins of one pass (8 same device
twice, 8 two cameras of one door, 3 W1 twins, 2 Doorbell Lite pair; Phase 3 table). So one arrival can open two D5
windows (two cameras of one door) and an arrival mislabelled `exit` (4 of 17 readable clips) opens none. The P3-D4 term
hold (110 s) delays only the ledger term; D5 never reads the ledger (G8), so no timing collision. *Resolution:* D5
de-duplicates windows by physical pass: windows whose crossings share a `pass_key` (P3-D3 attribute, or, before P3-D3,
the same door group within `CROSSING_VISION_CLUSTER_S`) merge into one `PathRecord`; D5's vision leg (ship 4, spends
calls) additionally opens on `vision_direction = in` when the tracker said `exit` or `ambiguous`. INV-DIR-GATE governs
ledger terms only, so a display producer may use vision direction. Plan edit to interior §9.D5; it changes a ship-4
trigger, so a focused re-review of D5 only.

**C5. Three plans each propose "one physical pass = one crossing".** P3-D4 collapses at the ledger (consumer side);
NVR witness W2 "must dedup one physical crossing across NVR legs" (`PLANNING_nvr_witness_layer.md:171-174`) at
corroboration; EGRESS-TRACKER-DIRECTION-1 (filed only by P3-D7, i.e. after FLIP-READY) would add "a pass-level dedup
(one physical pass = one resolved crossing)" at the tracker (Phase 3 text). Three dedups of the same physical fact is
the arc-map artificial-seam test, and the tracker one is the robust fix: notify, the census egress-face union,
`person_entry_exit_events`, perimeter and sightings all read the tracker today and all double-fire on twins.
*Resolution:* one pass-identity function owned by the F3 owner (`EgressDirectionTracker`), keyed by the matched
Frigate event plus the W1 pair (`camera_resolver` W1 pairing), producing `pass_key` at resolution. P3-D4 consumes it
instead of computing its own; W2 consumes it. P3-D0 (d) is the measurement for both. EGRESS-TRACKER-DIRECTION-1 is
planned NOW (pass dedup part; the direction-oracle part still waits for P3-D6 data). Tier 3 because it touches every
F3 reader. Operator decision on timing (§7 D4).

**C6. Step 7 makes identity attach direction-aware on a direction that is 35 % wrong.** Step 7 changes the veto in
`_resolve_direction` / `_resolve_egress_face_identity_ex` to depend on direction (`PLANNING_egress_direction_aware_identity.md:96`,
`:153`, D6 "veto direction-aware"); its non-goal is "Changing direction resolution" (`:813`). The door audit measured
the tracker wrong on 6 of 17 readable clips, mostly arrivals labelled exit. A step-7 build on that base would name an
arriving resident against an `exit`, or skip a naming on a mislabelled `entry`. Phase 3 deliberately leaves the tracker
direction byte-identical for step 7's readers (INV-F3-OWNER). *Resolution:* step 7 is not blocked, but rev 3.2 adds
(a) a replay of its decision rules on the 17 hand-labelled clips of the P3-D0 fixture
(`quality/tests/fixtures/crossing_vision_door_eval_2026_11_14.json`), reporting how many named outcomes flip when the
tracker direction is wrong; (b) a `direction_agreement` display field on its arrival notices when P3-D3 exists; (c) a
pointer that the root fix is EGRESS-TRACKER-DIRECTION-1 (C5). Needs re-review.

**C7. G3 roles and fields: three writers, one contract list.** Contract §4.2 roles today: `arrival_confirmed`,
`exit_backfilled`, `pair_resolved`, "crossing-vision attribute roles" (`CONTRACT_person_awareness_layer.md:310`). Phase 3
adds role `vision_direction` and fields `vision_direction`, `vision_people_count`, `direction_agreement`, `pass_key`
(`transit_validator.py:946-983` additive); step 7 adds `identity_role`, `pair_state`, `pair_partner`; interior adds no
G3 write (it reads). G3 is BUILT (`amend_crossing` `transit_validator.py:1036`, `attach_crossing_attribute` `:1232`;
contract §4.3), so step 7's "0 hits in code on batch-2" (`:100`) and contract G3's "whichever builds first (the other
extends it)" (`:362`) are both stale. Naming hazard: P3 "pair collapse / `pass_key`" (one person, two cameras) vs step 7
"pair guard / `pair_state`" (two similar residents, Jaya/Ezinne). *Resolution:* the contract §2.3 additive-field list and
§4.2 role list are amended once now by the orchestrator with all seven fields and both roles, so neither build edits
the contract; P3 renames its knob `CROSSING_VISION_LEDGER_PAIR_COLLAPSE` to `..._PASS_COLLAPSE` and `PAIR_SAME_EVENT_MIN`
to `PASS_SAME_EVENT_MIN` so "pair" means only the confusable-resident pair. `test_g3_never_sets_direction` (P3-D3) and
step 7's INV-RING test both stay.

**C8. The shared `analyze_crossing_images` seam.** It exists only on the unmerged fast-stage branch
(`perimeter_enrichment.py:461` on 921c9c47; 0 hits on develop). Interior's still route requires it
(`PLANNING_vision_interior_sightings.md:137`, `:237`; "whichever merges first owns it", `:708`). Phase 3 does not mention
the fast stage at all, though P3-D1 / P3-D3 edit the same `_run` / `_record` path and add `pipeline_version` that P2-D8
rows were supposed to carry (Phase 3 §0: "0 hits in code"). *Resolution:* rebase the fast-stage branch on develop and
merge it DARK (`CROSSING_VISION_FAST_STAGE_ENABLED` False, already its default) before any P3 build and before interior
ship 2; P3-D3's `pipeline_version` covers fast-stage rows too. The fast-stage owner of `analyze_crossing_images` is
crossing vision; interior calls it unchanged. If the rebase shows conflicts beyond `_run` / `_record`, it gets a
one-pass review (Tier 2), not a re-plan.

**C9. `persons_in_room` (G6).** Contract G6 defines the one BLE-in-room read (`CONTRACT:365`) but not its return type;
ship 3 did not build it (`PLANNING_person_awareness_layer_ship3.md:1220`, Q1 "G6 rest goes to G6-ONE-BLE-ROOM-READ-1").
Interior ship 1 builds it if G6 has not merged, pinning `tuple[str, ...]` and `active_only` (`:710-716`); step 8 rev 3.4
reads `get_person_location` and names the one site to swap later (rev 3.4 `:483-486`); music repair reads the BLE event
payload (`PLANNING_music_following_repair.md:41-42`, `:138-140`), not a room read; the room coordinator still has its own
`_get_identified_persons_in_room` (`coordinator.py:1375` on the interior branch). *Resolution:* interior ship 1 is the
builder of `persons_in_room` (it is in progress and G6 has no plan); G6-ONE-BLE-ROOM-READ-1 keeps the reader migration
and the §2.4a probe and is planned now, rebased on interior ship 1. The contract edit pinning the return type lands in
interior ship 1's commit. Step 8 swaps its one site in G6's migration, not in step 8.

**C10. Grading tool ownership.** One tool, P2-D10 (crossing vision), is the owner: it is NOT built (Phase 3 §0: "0 hits
for `GRADE_URA`"). Interior Q3 default "door first, same tool, same weekly budget" (`:60`, `:340`, `:618-620`); P3-D6 adds
`_in` / `_out` / `_pass` grades; arc map M10 merged identity labelling (EGRESS-OUTCOME-WEEKLY-LABEL-1) into the same run
(operator approved Q4). The 46-clip door evaluation was a prober's hand count, not the tool. *Resolution:* P2-D10 is
built as part of the Phase 3 scorer ship (P3-D6), with the direction grades, the identity question of M10 and an
`interior` discriminator column from the start (cheap now, a migration later). Interior grading starts when the door
evaluation set reaches the P3-D7 bar sample (`CROSSING_VISION_DIRECTION_SCORED_MIN_N` 30 scored crossings), not "when
the door set is done", which has no size.

**C11. Daily vision call caps.** Door: `CROSSING_VISION_DAILY_CALLS` Number (40 now, P3-D5 → ≈ 100, ≤ 200), counter
rehydrated from rows after P3-D5. Interior: `number.ura_interior_vision_daily_calls` 60 + `..._daily_cost_usd` 0.50,
"Separate from the door cap" (`:628`), describe reserve 10; its `calls_today` is RAM with no rehydrate (grep of the plan:
no rehydrate text). Both call the same Luna provider (`CROSSING_VISION_PROVIDER_ID`, interior `:138`).
*Resolution:* keep two caps (a shared budget would let interior starve the door, which is the central question), keep
cost as a guard not a budget, and copy P3-D5's restart rehydration (with its DB-error-starts-at-cap rule) into interior
D7. Combined concurrency: interior respects `CROSSING_VISION_MAX_CONCURRENT` as a shared semaphore so a door call is
never queued behind interior calls (door preempts). Plan edit to interior D2/D7; no re-review beyond a spot-check.

**C12. The camera area map is entity-area only; plans assume area-matched cameras.** The room override, `has_camera`
and zone discovery read `CameraManager._cameras_by_area`, built at `camera_census.py:1105-1123` from
`resolve_configured_cameras` (`:736`) → `resolve_camera_entity` (`:573`), where `area_id=bs_entity.area_id or
camera_entry.area_id` (`:680`): two ENTITY areas, no device area. Live, all 28 configured person entities have entity
area null (watched-set audit §1). The device-area path at `:915-922` is in `resolve_cross_platform_sensors` (`:824`),
which does not build the area map. Consequences per plan:
- interior vision: unaffected for its own groups (it reads "entity area, else device area", `:214`) but its record
  copies census per-entity readings, and census per-AREA structures are all keyed `""`;
- census: unrecognized contributions are grouped "by `CameraInfo.area_id` with same-area max / cross-area sum"
  (`camera_census.py:6247`, `:6302`). With one key for every camera, the house guest count is plausibly a house-wide
  max, not a cross-room sum, and `_ble_home_by_area` / `_room_tier_corroboration_by_area` (`:3212`, `:3247`) cancel
  nothing per room. **Not verified end to end here**; it is the first thing ZONE-CAMERA-DISCOVERY-DEVICE-AREA-1's
  probe must replay, because fixing the map can RAISE `guest_cam` (house-state reach);
- room override, `sensor.py:2837` has_camera, `presence.py:5240` `_discover_zone_cameras`: inert;
- ship 3b: Wr = 3, U = 14 instead of U = foyer (watched-set audit);
- interior's comparison of its term to `guest_cam` (D4 agreement fields) inherits the census skew.
*Resolution:* approve ZONE-CAMERA-DISCOVERY-DEVICE-AREA-1 option A (reuse `resolve_area_id_for_entity`,
`camera_resolver.py`), but classify it Tier 2-DB minimum with the house-state rule (it can change `unidentified_count`,
an AWAY/GUEST input), its first deliverable a census replay (guest_cam before/after on 7 days of snapshots). Sequence it
before interior ship 3 (D2 compares to NVR counts) and before any F-LEAD; it does not block interior ship 1.

**C13. NVR witness W2 vs 3b `CameraTwinHealth` vs crossing / interior camera reads.** The NVR plan was written 11-13
and has zero references to `CameraTwinHealth`, `camera_twin_health.py` or `physical_camera_dead` (grep). Arc map 9a says
"seam with 3b's `CameraTwinHealth` = extend, never a second camera-liveness model" (`ARC_identity_vision_census_map.md:157`).
Interior ships 1-4 read liveness through 3b and need W2 only for the D4 flip provenance (`:206-232`). Crossing vision
reads Frigate events and the W1 door groups; W2's transit `_count_platforms_fired` migration (`PLANNING_nvr_witness_layer.md:126`)
sits on the same crossings as C5. *Resolution:* NVR plan rewrite (arc rule 5) before W2 is dispatched: liveness
delegates to `CameraTwinHealth`; W2 keeps the agreement record only; pass dedup consumed from C5; W5's calendar gate
replaced (C/D table, §6). Re-review required.

**C14. Stuck / fan-held occupancy vs the ledger anchor and the fan recheck.** C1 is the ledger side. The fan side: only
3 of 12 fan rooms can arm the recheck (media audit `:196`), 20 of 47 room Automation switches are off (`:46`; the brief
said 21, the audit counts 20), and the stuck machinery reaches no fan writer (`:115`, `:132`). The ledger plan's
argument that a held still guest must block the anchor (P2-D2 step 2) is right for a radar on a real person and wrong
for a radar the room itself has excluded. *Resolution:* C1 for the anchor; the media audit's simplest version (a code
trip-wire "house AWAY or no person evidence while a room is radar-held" → NM, `:155`) ships under
MEDIAROOM-FAN-LEFT-ON-STUCK-SENSORS-1 (Tier 2, presence builder reads the state of play). The stuck-triggered recheck
stays parked with the audit's trigger. The paused rooms are an operator question, not code (§7 D5).

**C15. Step 7 egress direction vs Phase 3 vision direction vs EGRESS-TRACKER-DIRECTION-1.** Three owners of
"direction": the tracker (`transit_validator.py:2401-2423`, F3 owner, read by notify, census union, DB rows,
perimeter, sightings), step 7 (consumes it for the veto, C6), Phase 3 (an F3 attribute, display now, ledger after
INV-DIR-GATE). *Resolution:* one direction, owned by the tracker; vision is evidence about it, never a second
direction for readers other than the ledger and display. EGRESS-TRACKER-DIRECTION-1 is the one place that may later
let vision's scored direction (or the pass dedup) change the tracker's resolution, with the P3-D6 tracker accuracy as
its baseline. Step 7 and Phase 3 plan text both point there.

**C16. Step 8 build base and plan of record.** `feature/step8-identity-actions` was forked from the music branch at
c5685b5f, before music's review-C fix-ups 3a03ac26 / 5a5d9d76 / e31fe83a; step 8 depends on music D7
`set_preference_provider`. Develop holds step 8 rev 2 (welcome scene a non-goal, `:278`) while the build follows rev
3.4 on an unmerged branch. *Resolution:* merge `plan/identity-actions-v6-rev3` to develop now (it is reviewed through
3.3 with 3.4 fixes), ship music, rebase step 8 on develop, then the §10.1 reviews.

---

## 3. Stale assumptions (falsified by live findings)

| # | Plan text | Live finding | Effect |
|---|---|---|---|
| S1 | Census bars a and e assume a ledger that is `known` most of the time and ~4 anchors a week (`PLANNING_census_deconfliction.md:134-139`; crossing plan anchor sweep) | `known` 0 % since the ledger shipped; 0 anchor rows ever; held stuck radars on an AWAY house (pipeline audit §5, day audit §4) | F-LEAD / F-NOTIFY unreachable; Phase 3 benefit to census unreachable (C1) |
| S2 | Ship 3b: "U = the foyer group" (`PLANNING_person_awareness_layer_ship3.md:721-723`, `:1211-1215`); room override sensors watched by rooms | Wr = 3 panels, U = 14 (watched-set audit) | 3b pages come from the house owner, not rooms; README/plan numbers wrong |
| S3 | Entry/foyer audit: "CameraInfo.area_id = entity area, else device area (camera_census.py:680, :918-922)"; fix = move the fisheye devices to `foyer` | `:680` is entity area or camera-entity area; `:918` is in `resolve_cross_platform_sensors`, not the area map. Watched-set audit: "the foyer move changed nothing" | HA-FOYER-CAMERA-AREA-ALIGN-1 is `shipped_organic` with no effect; it is blocked on ZONE-CAMERA-DISCOVERY-DEVICE-AREA-1 (its own next says so) |
| S4 | v3.5.1 room camera override, `has_camera`, zone camera discovery work by area | inert since no entity carries an area (watched-set audit §3) | every plan reading "the room's cameras" by area reads nothing (C12) |
| S5 | Crossing plan D0 "direction vs validator 51 %" read as vision direction quality | it measured the validator; the tracker is 35 % wrong on readable clips (door audit §3b) | P3-D0 (b) re-measures against human truth (already in Phase 3) |
| S6 | Interior D5: fast stage writes `people_count` as a G3 attribute (`:502-503`) | fast stage writes provisional rows only (G8); field is `vision_people_count` (P3-D3) | C3 |
| S7 | Step 7: G3 "0 hits in code on batch-2" (`:100`); citations on batch-2 | G3 built and live (3a); batch-2 merged | step 7 rev 3.2 rebases citations on develop |
| S8 | Step 7 treats the tracker direction as the basis of a direction-aware veto | 35 % wrong on readable clips, mostly arrivals labelled exit | C6 |
| S9 | Step 8 on develop: rev 2 (welcome scene a non-goal; music D1 blocked on BERMUDA-DISTANCE-SENSORS-DEAD-1, `:248-250`) | rev 3.4 on branch drops the 8 ft gate (rev 3.4 `:40`); music branch 706f7230 dropped it | develop plan is not the plan of record (C16) |
| S10 | Board: music "Tier 2 build after the vision-arc builds free a builder slot" | built and reviewed since 11-14 | ship it |
| S11 | Crossing plan cap 40 with RAM counter as an accepted residual | 46 calls on 11-14 across two restarts | P3-D5 (in plan); interior has the same RAM pattern (C11) |
| S12 | Census plan non-goal "vision direction" (`:346`) | Phase 3 P3-D7 lets vision direction feed the ledger after a bar | census §8 points at INV-DIR-GATE instead |
| S13 | Fan recheck is the fan-noise defence for held rooms | 3 of 12 fan rooms can arm it; 20 of 47 rooms paused; RF fans never read `on` in HA (media audit) | anchor cannot rely on the recheck to clear held inputs (C1, C14) |
| S14 | Arc map status column (`ARC_identity_vision_census_map.md:39-71`) | read API shipped, census-p2 shipped, 3a/3b shipped, interior approved and building | map refresh |
| S15 | Interior §5 / §7: build base `feature/layer-ship3b` @ 5d8b831d "a build starts only after ship 3b is on develop" | 3b is on develop (v5.108.25) | precondition met; citations still on 5d8b831d (fine, symbols win) |

---

## 4. Recommended sequence

Constraints: at most 2 builders at once, one suite runner (memory `feedback_fewer_agents_sonnet_readonly`,
`feedback_serialise_suite_runs_across_agents`); probes and reviews are not builder slots. Operator priorities: door
vision counting well (central), hard parts sooner, don't defer, completion; music and step 8 waiting since 11-14.

**Now (no builder slot needed, in parallel):**
1. **Ship music repair** (`feature/music-following-repair` e31fe83a): validator name-diff on develop, README, deploy,
   live write-back. Reason: reviewed, waiting a day; it is step 8's base; operator "No delays".
2. **Merge step 8 plan rev 3.4** to develop (`plan/identity-actions-v6-rev3`). Reason: plan of record (C16).
3. **P3-D0 probe** (prober, ≤ 120 Luna calls with the operator's OK). Reason: it gates P3-D2 route, P3-D3 direction,
   P3-D4 / C5 pass dedup; it is the next measurement of "is it counting well".
4. **Phase 3 plan reviews** (completeness + build prediction + G), with the §5 edits applied first. Reason: Tier 3.
5. **ZONE-CAMERA-DISCOVERY-DEVICE-AREA-1 replay probe** (read-only: census guest_cam before/after on 7 days). Reason:
   C12 changes a trust input; measure first.
6. Contract §2.3 / §4.2 amendment for all G3 fields and roles (orchestrator doc edit, C7).

**Builder slot A (in flight): interior ship 1** (D0 probe, D1 records incl. `persons_in_room`, D5 no-model leg with the
C3/C4 edits). Reason: approved, in progress, needs no model and no labelling. Then slot A takes **step 8**: rebase on
develop after music ships, run the §10.1 reviews (Tier 2-DB per rev 3.4 default), then the remaining step 8 build.

**Builder slot B, this week:**
7. **Fast-stage merge (dark)**, rebased (C8). Small; unblocks P3 and interior ship 2.
8. **P3-D8 anchor honours stuck exclusion** + **P3-D1 error text** + **P3-D5 cap rehydrate** (Tier 1-2, one build,
   two reviews). Reason: P3-D8 is the one change that lets the ledger become `known` at all; without it nothing door
   vision does reaches F2-A. Needs operator D3.
9. **P3-D3 + P3-D2** (Tier 3, four code reviews, operator checkpoint) once P3-D0 reports. Reason: direction is the top
   failure (door audit verdict); P3-D3 ships count-only if the direction gate fails (no parking).

**Next week, in this order (slot B, then whichever slot frees):**
10. **ZONE-CAMERA-DISCOVERY-DEVICE-AREA-1** build (Tier 2-DB + house-state rule), if the replay shows no GUEST
    regression or the operator accepts the delta. Before interior ship 3 and any F-LEAD.
11. **EGRESS-TRACKER-DIRECTION-1 plan** (pass dedup at the tracker, C5), written in parallel with P3-D3 review; build
    after P3-D0 (d) numbers. Then **P3-D4** consumes its `pass_key` (or, if the operator keeps it ledger-only, P3-D4 as
    written).
12. **Step 7 rev 3.2** (C6 replay, G3 rebase, operator §13 answers) → re-review → build. Critical path to v6.0.0 (step 8
    needs step 7's amend function and `camera_egress`). Can be planned now; builds after step 8's parallel set frees
    slot A.
13. **BLE-ARRIVAL-PRODUCER-HVAC-GATED-1** (Tier 2), any free slot before v6.0.0 (step 8 rev 3.4 §10).
14. **P2-D10 grading + P3-D6 scorer** (one build, C10). Then interior ships 2-4 in plan order; interior grading starts
    at 30 scored door crossings.
15. **MEDIAROOM trip-wire** (C14), Tier 2, any slot.
16. **NVR witness rewrite → W2** (C13), after 11 so it consumes the pass key.
17. **G6-ONE-BLE-ROOM-READ-1** migration, after interior ship 1 (C9); LAYER-LEAK-CLEANUP-1 behind the arc (as decided).
18. P3-D7 flip and interior D4 flip at their bars (operator checkpoints); EGRESS-TRACKER-DIRECTION-1 direction part
    with P3-D6 data.

Shippable this week: music repair; fast stage (dark); P3-D8 + P3-D1 + P3-D5; interior ship 1; the P3-D0 report; plan
merges. Step 8 §10.1 is reviewable this week and shippable as soon as its reviews pass (its user-facing v6.0.0 still
waits on step 7).

Why direction-and-anchor before groups: the 11-14 net error was mainly direction labels (Phase 3 §7 item 6, door
audit §3c), and a perfect group count still contributes nothing while the ledger is `unknown` (C1).

---

## 5. Plan edits needed

| Plan | Edit | Re-review? |
|---|---|---|
| `PLANNING_crossing_vision.md` Phase 3 | Add P3-D8 anchor honours stuck exclusion (C1) with tests (`test_stuck_excluded_input_does_not_hold_anchor`, `test_unavailable_input_still_holds_anchor`) and Live "first `anchor` row within 2 empty episodes"; rename PAIR→PASS knobs (C7); state that the fast stage merges dark first and P3 rows' `pipeline_version` covers fast rows (C8); P3-D4 consumes the tracker `pass_key` if EGRESS-TRACKER-DIRECTION-1 lands first (C5); P3-D6 builds P2-D10 with identity (M10) and interior columns (C10); non-goal: no `deconflict_house` signature change (C2); file EGRESS-TRACKER-DIRECTION-1 now, not at P3-D7 | Yes: these edits go into the pending Tier-3 plan reviews (not yet run) |
| `PLANNING_vision_interior_sightings.md` | D5 `n` reads `vision_people_count` (C3); D5 merges windows by pass and the vision leg opens on `vision_direction = in` (C4); D7 counter rehydrate + door-preempting shared semaphore (C11); grading start = 30 scored door crossings (C10); note census per-area keying under C12 in §15 | Focused re-review of D5 + D7 only (approved plan, ship-4 trigger changes) |
| `PLANNING_census_deconfliction.md` | §3.3 gains interior's approved edit (signature `interior_term`, `interior_leads`, lower-bound rule, exclusion from `vis`), uses the code name `vision_leads`, and the bar-window line (C2); §8 "vision direction" non-goal points at INV-DIR-GATE (S12); bar windows sample-sized, not 7 days (§6) | Spot-check (text the interior plan already passed) |
| `CONTRACT_person_awareness_layer.md` | §2.3 / §4.2: seven G3 fields, roles `vision_direction`, `arrival_confirmed`, `pair_resolved`; G3 row "BUILT, extended by each writer"; G6 return type `tuple[str, ...]`, `active_only` | No (orchestrator, per arc rule) |
| `PLANNING_egress_direction_aware_identity.md` | Rev 3.2: citations on develop; G3 built (S7); C6 replay on the P3-D0 fixture; pointer to EGRESS-TRACKER-DIRECTION-1; `pair_*` naming kept, P3 uses `pass_*` | Yes (Tier 3) |
| `PLANNING_identity_actions_v6.md` | Merge rev 3.4 to develop (C16); record that music D1 no longer needs Bermuda distance (S9) | No (rev 3.4 reviewed) |
| `PLANNING_nvr_witness_layer.md` | Rewrite: liveness = `CameraTwinHealth` (3b), pass dedup consumed (C5), W5 gate sized by records not "≥ 14 days" (C13) | Yes (Tier 3, two reviews + G) |
| `PLANNING_person_awareness_layer_ship3.md` | 3b §6.3 numbers: Wr = 3, U = 14, with the C12 cause (S2) | No |
| `ARC_identity_vision_census_map.md` | Status column refresh (S14); add C5 merge row (one pass identity: P3-D4 + W2 + EGRESS-TRACKER-DIRECTION-1); add ZONE-CAMERA-DISCOVERY and MEDIAROOM rows; step 2b gains P3-D8 | No |
| `PLANNING_music_following_repair.md` | None; ship it | No |
| Board (orchestrator) | MUSIC next; HA-FOYER-CAMERA-AREA-ALIGN-1 back to blocked on ZONE-CAMERA; mint P3-D8 / EGRESS-TRACKER-DIRECTION-1 cards in the arc; G6 next = plan now | n/a |

---

## 6. Drift table

| Operator said | Where it drifted | Correction | Status |
|---|---|---|---|
| "Is Vision working as designed is the central question... is it counting well?" | Counting was measured (80 % singles, groups under) but no plan noticed vision has contributed to no census number since the ledger shipped (never `known`) | P3-D8 before P3-D3 (C1) | open |
| "We should do the hard parts sooner"; "don't defer" | Phase 3 files EGRESS-TRACKER-DIRECTION-1 only after FLIP-READY, while three plans build pass dedups around the tracker | Plan the tracker pass dedup now (C5) | open |
| "Foul. Why that long?" (gates sized to error rates) | Census `CROSSING_VISION_GO_WINDOW_DAYS` 7 and F-LEAD "≥ 7 days" (`PLANNING_census_deconfliction.md:74`, `:127`); NVR W5 "≥ 14 days of W2 records" (`PLANNING_nvr_witness_layer.md:339`) | Replace with sample-size / interval-width bars, as interior and Phase 3 already do | open |
| "step 8 is fine. You better get a move on" | Plan of record on an unmerged branch; build forked before music's fix-ups; §10.1 unreviewed for a day | C16; reviews this week | open |
| "No shadow mode... No delays" (music) | Reviewed, unshipped since 11-14; board says "build after a slot frees" | Ship now | open |
| "if even one nvr has the cam it doesn't count as dead" | Fixed by 3b; NVR witness plan still models liveness itself | C13 rewrite | open |
| "Unacceptable to do the latter anymore" (registry) | Camera area map reads entity area only, so it misses the registry's device area; census person-entity detection still matches `_person_occupancy` / `_person_detected` suffixes (`camera_census.py:650-664`) | ZONE-CAMERA (C12); suffix rule stays on REGISTRY-NOT-NAMES-1 | open |
| "consumers can read and producers can feed... no leaks" | Two plans each assumed the other extends G3; contract list incomplete | C7 single contract amendment | open |
| "Vision on crossing with no clear direction - of course" | none: P3-D3 ships count-only if the direction gate fails | — | ok |
| "Interior... tight and not deferred" | none: ship 1 building, no labelling dependency | — | ok |
| "Not expecting new names... Non goal" | none found | — | ok |
| "The layer was just a prereq" | none new: leak cleanup is behind the arc | — | ok |

---

## 7. Operator decisions (only the operator's)

| # | Decision | Recommended default |
|---|---|---|
| D1 | Spend up to 120 Luna calls on P3-D0 (b) direction/count replay | Yes |
| D2 | ZONE-CAMERA-DISCOVERY-DEVICE-AREA-1 option A, knowing it can raise the census guest count and turns on room camera holds house-wide | Yes, after the 7-day replay is shown to you; Tier 2-DB + house-state review |
| D3 | Does an input the room has excluded as stuck (continuous-on or chatter) still hold the empty-house anchor? (Dead / `unavailable` inputs keep holding, your rule) | No: stuck-excluded inputs stop holding the anchor; dead ones still hold |
| D4 | Plan EGRESS-TRACKER-DIRECTION-1 (pass dedup at the tracker, for every F3 reader) now, rather than after the vision-direction flip | Now; build after P3-D0 (d) confirms the shared-event rule |
| D5 | 20 of 47 room Automation switches have read `off` since at least 11-08 (Kitchen, Master Bedroom, Jaya, both guest rooms, Foyer, Media...). Deliberate? | Unknown; please confirm. If not deliberate, turning them on is a config fix, no code |
| D6 | Step 7 §13 answers (QA no deferral, QB candidate rule, Q1-Q7) and the misrecognition ceiling | The plan's recommendations |
| D7 | Interior §1a Q1 (interior leads on its own bar) | Yes (plan default; recorded so the census edit can land) |
| D8 | EGRESS-OUTCOME-WEEKLY-LABEL-1: Jaya's phone on 11-11; Ojini / Ziri trackers (still open since 11-13) | Answer when convenient; it feeds the M10 labelling run |
