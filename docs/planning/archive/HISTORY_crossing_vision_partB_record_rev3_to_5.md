# NOT A BUILD SPEC: crossing vision Part B record, rev 3 to 5 (history)

Archived 2026-11-13 from `plan/crossing-vision` @ 1e76c98a. Every rule that still binds is restated in `PLANNING_crossing_vision.md` or `PLANNING_census_deconfliction.md`.

---

# Crossing vision Part B record (rev 3-5): APPENDIX, NOT A BUILD SPEC

Moved out of `PLANNING_crossing_vision.md` at rev 6.2 (plan review #2 H2). The design here (`vision_hold`, AWAY-hold sites,
`evidence_only`/`vision_led` authority, P2-D4/P2-F rev 5) is SUPERSEDED and must not be built. Only the items listed in
`PLANNING_crossing_vision.md` Part B §B1 are binding, and only as restated there.

# PART B-RECORD (rev 3-5, superseded by Part B rev 6; kept for the reviewed rules it supplies)

## (record) Phase 2: crossing counts as the census input (rev 3)

**Shape in one paragraph.** Each resolved crossing on a watched door adds a signed term to ONE house ledger:
`inside = entries − exits` (validator direction, never vision direction; count = vision when the shadow row is `ok`,
else the camera peak). Two independent anchors keep it honest: the ledger never reads below the residents BLE/trackers
place at home (floor), and it resets to 0 after the house is physically empty by evidence that does not read house
state, the census or the ledger (empty anchor). A resident departure with no matching exit term decrements it
(reconcile). The non-resident estimate `guest_vis = max(0, ledger − residents_home)` enters the census through the
§15.7 deconfliction, at ONE site. Everything ships dark (`evidence_only`): the ledger, its cases and its bars are
computed live from Phase 1 rows while nothing acting changes. Only the authority flip to `vision_led` waits on the
measured bars (§17), and only the operator approves it (Tier 3 checkpoint).

## 14. Read-first, corrections and config-first

**Read first, completely, this revision:** `docs/Coordinator/IDENTITY_FUSION_CAMERAS_MANUAL.md`,
`docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (incl. §10 ledger items 1-35),
`docs/architecture/SENSOR_FLEET_CLASSES.md`. No ledger claim is re-asserted. HVAC is touched only as a downstream
reader of house state (no HVAC code), so the HVAC state-of-play is cited, not edited.

### 14.1 Corrections recorded by this revision

| # | Claim (where) | Correction | Evidence |
|---|---|---|---|
| C1 | "D0d failed, so Phase 2 is blocked until a guard passes" (§5 D0d, §9; `AUDIT_crossing_vision_d0_2026_11_13.md` line 19) | WRONG test of the wrong guard. D1 uses the SET-level guard (all frame counts 0 → `blank`, INV-BLANK). D0d tested the weaker per-frame form (24/30). The set-level form had 0 false blanks in 38 person crossings and 6/6 true blanks (D0b). D0d's truth for the 6 misses was operator labels, but D0b's truth was prober labels, so neither is an operator-validated crossing-level guard number. Phase 2 is gated on ledger-level bars (§17), which measure the guard's effect where it matters | audit lines 63-65, 118 |
| C2 | "vision feeding `unidentified_count` reaches GUEST, HVAC guest mode and the lock regime guest night" (§11, §4.3) | STALE since GUEST-MODE-SPLIT-VISITORS-1 (v5.108.0). GUEST is the night-stay latch over `occupancy_events` (`_compose_guest_gate`); `unidentified_count` reaches only Path A (`_guest_gate_armed`, `presence.py:6665`) → `visitors_present` / `guest_reason` (display). The acting reach is AWAY and ARRIVING: path α needs `unidentified_count == 0` (`presence.py:1214-1232`), nobody-home needs `census_count == 0` where `census_count = house.total_persons` (`presence.py:3217`), and ARRIVING fires on `census_count > 0` from AWAY. Tier 3 + house-state rule still apply | grep below, §15.2 |
| C3 | "a ledger term decays out after the census decay window" (`PLANNING_person_sighting_layer.md` §15.3 item 9) | Dropped. A decaying term erases a staying guest, which is the case the ledger exists for. Replaced by the floor, reconcile and empty anchor (§16) | operator 2026-11-13 ("counting people at crossings") |
| C4 | §15.7a per-crossing bars (≥ 95 % exact per door, ≥ 80 % B/C wins) as the gate | Superseded for the flip by ledger-level bars (§17). The per-crossing numbers are still reported by the scorer as diagnostics | operator 2026-11-13 ("depends on error rates you don't have") |
| C5 | D1 item 7/8 "flat `response_text`", "refused = empty `response_text`" | The json path returns `structured_response`, no `response_text` (D0b). Phase 1 build parses the structured dict (`crossing_vision.py:149-160`); recorded here so Phase 2 reads the same fields | audit line 67 |

### 14.2 Config-first

| Question | Setting checked | Finding |
|---|---|---|
| Can a knob make the census count guests from crossings today? | census options (`CONF_CENSUS_CROSS_VALIDATION`, `CONF_CENSUS_DIVERGENCE_DOWNGRADE`), egress identity toggle | No. The census has no crossing-count input; egress feeds identity (`register_egress_face`) only |
| Can a knob pick the model? | llmvision entry (operator added 01M7B731T26P2HXVW77AQR62PP) | Yes for the model: P2-D1 is option-only plus one rung-1 model constant |
| Can a knob cover the 26 % unmatched crossings? | `CROSSING_VISION_EVENT_MATCH_S` (rung 1) | Partly: ±30 s → 82.9 % (D0c). Wrong-event risk unmeasured → P2-D0 (iii) |

Code is needed for the ledger, its anchors, the census site and the trip-wires.

## 15. Institutional context verified (Phase 2)

### 15.1 Prior-art scan: REUSE or BUILD per piece

| Piece | Verdict | Existing symbol (file:line, develop @ 13229beb unless noted) |
|---|---|---|
| Census owner, single guest-math writer | **REUSE / EXTEND one site** | `PersonCensus._apply_enhanced_house_census` (`camera_census.py:6407-6560` develop cbeb8c3f; same lines on the shadow branch): computes `recognized_set` / `identified_count` (:6452-6468) and the one `vision_hold` read (§16b B5). Rev 5: the census numeric fields are NOT changed (hold-only, §16a R3) |
| Raw house path | **NO CHANGE** | `_cross_correlate_persons` (`camera_census.py:2490-2580`); overwritten by the enhanced recompute for the house (comment at ~6428) |
| Camera body total (empty-anchor input) | **REUSE + publish (rev 5, §16b B2)** | The house raw-path `camera_total` (`camera_census.py:2140-2210` develop: all interior platforms, pre-face, pre-BLE-cancel), published as a new scalar. **NOT** `_last_camera_total_pre_cancel` (`:6069`): that value is Frigate-only and face-subtracted (`count - 1` per camera with a fresh face, `:5940-6070`), so a labelled or mislabelled person on camera reads 0 |
| Agreement vocabulary | **REUSE** | `CENSUS_AGREEMENT_*` (`const.py:2439-2450`) for the vision-vs-camera agreement value; §15.7 cases A/B/C/D are already computed per crossing by Phase 1 (`crossing_vision.agreement_case`, `crossing_vision.py:126`) |
| Result fields | **REUSE** | `CensusZoneResult.active_platforms` / `degraded_mode` / `source_agreement` (`camera_census.py:305-321`); `vision` appended to `active_platforms` only when the vision term was used |
| Provenance constant | **REUSE (not read)** | `IDENTITY_PROVENANCE_VISION` (`const.py:3442`). Phase 2 attaches NO identity (counts only, §15.7 rule 2); the constant stays unread. KEEP + DOCUMENT |
| Residents at home | **REUSE** | `PresenceCoordinator.get_residents_home` / `_count` (`presence.py:5409-5434`, trust state, phone-left-behind excluded, never raises) |
| Resident arrival / departure edges | **REUSE** | Residency producer (`domain_coordinators/residency.py`, house-state 1a D2, a0d590ef, in v5.108.15+); `person_arrival` episodes (`const.py:3925`, `RESIDENCY_EVENT_LOG_PERSIST` `:3924`). Shipped v5.108.19 (restart 17:44 UTC 11-13); no resident edge yet, see §15.3 |
| Room rising edges (empty anchor) | **REUSE** | `OccupancySubstrate.subscribe` (`domain_coordinators/occupancy_substrate.py:867`) |
| Crossing terms | **REUSE** | Phase 1 `crossing_vision_shadow` rows / in-RAM outcome (`crossing_vision.py:778-809`): `people_count`, `camera_peak_count`, `direction`, `outcome`, `crossing_keys`, `primary_crossing_key` |
| Persistence | **REUSE** | `Database.log_memory_episode` + write queue; NEW type `crossing_vision_ledger` (one row per term / reset / reconcile, ~20/day, batched by the queue). Grep `crossing_vision_ledger` = 0 hits |
| Trip-wires | **REUSE** | `fire_stuck_signal` (`_stuck_signal_nm.py:165`) for the stuck-ledger page; the AnomalyDetector → NM path for persistent disagreement (§15.7 rule 4); weekly writer-health via `MEMORY_WRITER_BACKED_EPISODE_TYPES` |
| Authority knob | **NEW const** | `CROSSING_VISION_COUNT_AUTHORITY` (named in §15.7a; grep in `custom_components/` = 0 hits) |
| Downgrade switch | **NEW entity** | `switch.ura_crossing_vision_census_authority` (RestoreEntity, pattern `EgressIdentityFaceFailsafeDrillSwitch` `switch.py:913`). No existing switch gates a census input source |
| Ledger arithmetic | **NEW module** | `crossing_ledger.py`, pure, HA-free (pattern: `interior_paths.score_path` shared with offline scripts), so the runtime and the scorer replay run the SAME code |
| Scorer | **EXTEND** | Phase 1 D4 `scripts/probes/crossing_vision_score_weekly.py` imports `crossing_ledger` for the dark-ledger replay |

Greps run (develop and `feature/crossing-vision-shadow`): `grep -rn unidentified_count custom_components/` (writers
only in `camera_census.py`; readers `presence.py:1078-1232`, `:6665-6693`, `sensor.py:3776, :4148, :4217, :5159-5220`,
`aggregation.py:6696-6778` `ZoneGuestCountSensor` (display), `binary_sensor.py:1891-1990` `URAUnexpectedPersonSensor`
(display, no other reader: grep `unexpected_person` = its own unique id only), `database.py:4485-4524` (census snapshot
rows)); `grep -n "CROSSING_VISION_COUNT_AUTHORITY\|crossing_ledger\|crossing_vision_ledger"` (0); `git grep
RESIDENCY_ARRIVAL_EPISODE_TYPE develop` (`const.py:3925`, writer `presence.py:5302-5310`).

### 15.2 Producer and consumer checks

| Value | Producer (arithmetic, dependency health) | Consumers |
|---|---|---|
| Crossing term | validator `direction` (entry +, exit −) × count; count = `people_count` if outcome `ok`, else `camera_peak_count`, else 1 (§16.3). Health: ~14/day; vision event match 74 % at ±10 s (D0c); exact count 93 % (D0b, n = 45, 1 group set) | ledger only |
| Ledger `L` | §16 rules. Health: unmeasured (P2-D0, dark run) | `guest_vis`; diagnostics; scorer |
| `residents_home` | `get_residents_home_count`, trust state. Health: live since 1a | ledger floor, `guest_vis` |
| `guest_vis` | rev 5: `max(0, L − R)`, `R = max(residents_home, identified_count)` (§16a R4); None while ledger `unknown` | `vision_hold` (§16b B5); diagnostics |
| `vision_hold` (rev 5) | `guest_vis` if effective `vision_led` and healthy, else 0 (int, never None) | the four AWAY-entry sites only (§16b B6) |
| `unidentified_count` (house) | **unchanged from develop in every mode** (rev 5, hold-only) | path α (AWAY veto, trust), Path A → `visitors_present` / `guest_reason` (display), `URAUnexpectedPersonSensor`, `ZoneGuestCountSensor`, `persons_in_house` attrs (display), census DB snapshot |
| `total_persons` (house) → `census_count` | **unchanged from develop in every mode** (rev 5) | nobody-home AWAY, path β H1, ARRIVING-from-AWAY, SLEEP / HOME_* (trust) |

**[SUPERSEDED by §16a R3 / §16b: the vision guest no longer enters `unidentified_count` or `census_count`. Kept for the
record.] Forward trace of the flip.** `vision_led` + `guest_vis ≥ 1` → `unidentified_count ≥ 1` → path α cannot fire and
`census_count ≥ 1` blocks nobody-home → no AWAY → HVAC stays on home presets, SC away arm (auto-follow) does not
engage, NM `persons_home`-style displays show a guest. From AWAY, an entry term → `census_count ≥ 1` → ARRIVING →
HVAC recovery. **Access:** LOCK-RELEASE-ON-ARRIVING is deployed (v5.108.18, PR #698) and v5.108.19 retired the taint:
while a lockout episode is open, HOME_* / ARRIVING edges release only on `override_set` / `override_clear`; WAKING (with a
sleep-like episode reason) and the morning backstop still end sleep-like episodes (README_v5.108.19 lines 23-27). The
remaining live gap is that `switch.ura_security_coordinator_garage_lockout` is OFF, so the hold has not been
live-validated (README_v5.108.18 line 45, PENDING, revisit ~11-16). Two more ARRIVING / census consumers with access or
severity reach are listed in §15.2a (SC auto-follow DISARM on ARRIVING; exterior-person CRITICAL on ARRIVING).
Policy lives in the consumer (the lock, the SC map), not by switching vision off.

### 15.2a Consumers the rev-3 enumeration missed (plan review #1, re-grepped on develop 688042b3)

`census_count` in presence is `census_data["interior_count"]` (`presence.py:5618`), which is `house_result.total_persons`
(`camera_census.py:1873`); the boot seed reads `last_result.house.total_persons` (`presence.py:3227`). Readers beyond
§15.2:

| Reader | File:line | Reach under `vision_led` |
|---|---|---|
| SC auto-follow map `"arriving": DISARMED` | `domain_coordinators/security.py:189-195`, gated by `CONF_SECURITY_AUTO_FOLLOW` (`:893`) | An entry term from AWAY → ARRIVING → alarm DISARMED. Access reach; INV-P2-NO-ACCESS covers it (P2-F precondition) |
| Exterior-person severity on ARRIVING | `perimeter_alert.py:2004-2015` (`EXTERIOR_SEVERITY_ARRIVING_NEEDS_RESIDENT`, v5.108.19) | Ledger-held ARRIVING with no resident home → exterior alerts CRITICAL. NM-severity reach via house state |
| Wake backstop | `presence.py:199-204` (`_WAKE_BACKSTOP_HOURS_AFTER_SLEEP_END`, fires while `census_count > 0`) | Forces WAKING; WAKING ends a sleep-like lockout episode (README_v5.108.19 line 26) |
| ARRIVING re-arm bypass | `presence.py:7027-7050` (`_arriving_rearm_bypass`, `census_count > 0`) | A held ledger bypasses the patio-flap cooldown on every tick |
| Boot settle release | `presence.py:7136-7150` | None: ledger is `unknown` at boot (case D) |
| D2 external-empty immediate engage | `presence.py:7887-7895` (`census == 0 AND unid == 0`) | Blocked while `guest_vis ≥ 1` (same direction as nobody-home) |
| Sleep raw-hold / zone-hold-all-away NM trip-wires | `presence.py:4345-4360`, `:4444-4456` (`_census_count == 0` conjunct) | Silenced while `guest_vis ≥ 1`: a ledger drift hides two existing stuck-house pages |
| `PersonPhoneLeftBehindSensor` | `binary_sensor.py:2180-2190` (`house.total_persons > 0` → off) | **Feedback into the ledger's own inputs**: see INV-P2-IDENTITY and INV-P2-DISCHARGE |
| `house_status.py:206-210` | display | none |
| `SanctionChecker` `unknown_present` | `security.py:282-346`, lockdown at `:1097-1140` | Dormant: no producer writes `context["census"]["unknown_present"]` (grep). Must stay unwired to the ledger |

### 15.3 Fire check

| Producer | Fired? | Evidence (read-only, 2026-11-13) |
|---|---|---|
| Egress crossings | yes | `egress_identity_outcome` 18 rows since the 08:25 CST restart |
| `crossing_vision_shadow` | not deployed | 0 rows |
| Residency `person_arrival` / departures | **0 rows, expected** | The producer shipped in v5.108.19 (installed and restarted 17:44 UTC 11-13). The AWAY → ARRIVING at 16:35 UTC predates it, and every `person.*` `last_changed` = 17:44:17Z (the restart), so no resident edge has occurred since. README_v5.108.19 L1 is PENDING on the first edge. P2-D0 (i) confirms the first edge writes a row |
| Independent empty anchor | unmeasured | AWAY 27 times in 14 days (house_state_log), an upper bound on anchors; P2-D0 (ii) counts the independent predicate |

New producers ship with zero-fire trip-wires (P2-D5).

## 16. The ledger (rules, in evaluation order)

**[Rev 5: rules 2, 3 and 5 and §16.3 are amended by §16b (anchor predicate and input, entry terms restart the window,
reconcile timing, the getter signature). Build from §16b where they differ.]**

One house ledger, RAM, state `known` or `unknown`. `crossing_ledger.CrossingLedger` (pure) holds `L` (int ≥ 0), the
anchor time, and counters.

1. **Boot = `unknown`.** After setup or restart the ledger is `unknown` (`guest_vis` None, case D) until the first empty
   anchor. Nothing is replayed. Parked: replay from `crossing_vision_ledger` rows since the last reset; revival trigger:
   P2-D0 / dark run shows median anchor gap > 24 h.
2. **[SUPERSEDED by §16a R1 and §16b B1-B3: no residents conjunct, action `L = R`, different camera input.]** **Empty anchor (reset to 0, `known`).** Predicate, re-evaluated every `CROSSING_VISION_LEDGER_EVAL_S`: ALL hold
   continuously for `CROSSING_VISION_LEDGER_EMPTY_RESET_S`: `get_residents_home()` empty; census
   `_last_camera_total_pre_cancel == 0` (interior cameras see no body); no Tier-1 room occupancy RISING edge
   (`OccupancySubstrate.subscribe`) in any room. It reads NO house state, census result, `unidentified_count` or ledger
   (circularity: the ledger blocks AWAY, so an AWAY-based reset would latch a positive drift forever). Rising edges, not
   levels: a stuck-on phantom sensor (§6 of the presence doc) makes no edges and cannot block the reset; a moving guest
   does. Pre-reset `L` is recorded as `residue` (the drift oracle, §17 bar a).
3. **Term.** On each Phase 1 crossing outcome with validator direction entry/exit: `L += n` (entry) or
   `L = max(0, L − n)` (exit), where n per §16.3. `ambiguous`: no term, counted. While `unknown`, terms are recorded
   but `L` stays unknown. A term whose crossing E precedes the last anchor (a late outcome) is recorded, not applied.
4. **Floor.** At each census evaluation `L = max(L, R)` (rev 5: `R` per §16a R4, supplied by the census, §16b B4). Raises only; cannot create a guest.
5. **Departure reconcile.** On a resident departure edge (residency producer) with no exit term applied in
   [edge − `CROSSING_VISION_LEDGER_RECONCILE_LEAD_S`, edge + `CROSSING_VISION_LEDGER_RECONCILE_LAG_S`]: `L = max(0, L − 1)`,
   counted `reconciled_departures`. Covers exits through uncovered doors and missed exit matches, the drift direction
   that would otherwise create a phantom guest when a resident leaves.
6. **Clamp.** `L ≥ 0` always; the unclamped running sum is kept as a diagnostic (`L_raw`) so negative drift (missed
   entries) is visible.

### 16.1 Reset anchor: why this one

The only fully independent truth that the house holds 0 non-residents is "no resident home and nothing moving, no body
on camera, for a while". It costs a delay: under `vision_led` a positive drift can hold the house out of AWAY for
`CROSSING_VISION_LEDGER_EMPTY_RESET_S` after it is truly empty (bounded by INV-P2-DISCHARGE). A guest home alone, still
and off camera for that long, is reset to 0, which is today's behaviour (camera count 0) one window later.

### 16.2 Unmatched-crossing policy (coverage 74 % at ±10 s, 83 % at ±30 s)

A crossing ALWAYS produces a term (except `ambiguous`); vision only improves its count. `term_source` per crossing:
`vision` (outcome `ok`), `camera` (any other outcome: `no_frigate_event`, `blank`, `error`, `timeout`, `refused`,
`unparseable`, `skipped_cap`, `skipped_busy`), with n = `camera_peak_count` or 1 when that is None/0 (the validator saw
a person edge). `blank` falls back too: the clip missed the person, the validator did not. Clustered crossings: ONE
term for the cluster with the primary's count and direction if all members share a direction; mixed directions →
each member gets its own camera term. Vision direction is never used (51 %, chance, D0b). Policy knob
`CROSSING_VISION_LEDGER_FALLBACK` (`camera` default / `skip`). Match window: keep ±10 s until P2-D0 (iii) measures the
wrong-event rate at ±30 s; switch to 30 if wrong-event ≤ 2 % (Tier 1 knob turn).

### 16.3 Where the ledger lives

`CrossingVisionShadow` owns the `CrossingLedger` instance and feeds it (terms from its own outcomes, departures from
the residency producer, rising edges from the substrate, the empty-anchor timer). **[Rev 5: the getter takes the
resident term and the camera body total, §16b B4.]** The census reads one getter
`get_vision_guest_estimate() -> (guest_vis | None, healthy: bool, ledger_snapshot)` from
`hass.data[DOMAIN]["crossing_vision"]`; missing object or any exception → `(None, False, {})` = case D. No second
census, no census state in the vision module.

**[R1, R2, R4 kept via Part B §B1; R3, R5, R6 SUPERSEDED rev 6, DO NOT BUILD]** ## 16a. Rev 4: design resolutions for plan review #1 (F1-F5, Q6, Q7)

**R1 (F1, HIGH): one resident-independent anchor.** Rule 2's predicate drops `get_residents_home()` empty. The anchor
is: interior camera body total (rev 5: the raw all-platform total of §16b B2, NOT `_last_camera_total_pre_cancel`) == 0 AND no Tier-1
room rising edge, continuously for `CROSSING_VISION_LEDGER_EMPTY_RESET_S`. Action: `L = R` where `R` is the resident
term of R4. With no resident home this is the old reset to 0; with a phone left on the desk (`residents_home` stuck at
1) it clears the guest surplus and keeps the floor. Residue (bar a) = pre-anchor `L − R`. One anchor, not two: anchor
"A" was this anchor with `R = 0`. Stuck page `crossing_ledger_stuck` (HIGH, `fire_stuck_signal`, RAM latch, re-armed
when `guest_vis` returns to 0): `guest_vis ≥ 1` while camera bodies == 0 and no rising edge for
`CROSSING_VISION_LEDGER_STUCK_S` (7200 > reset 3600, so it fires only if the anchor failed). No resident term in either.
Tests: `test_guest_surplus_discharges_with_resident_phone_home`, `test_stuck_page_resident_independent`,
`test_anchor_sets_L_to_resident_term`. Mutation: re-add the residents-empty conjunct → the first test fails.

**R2 (F2, HIGH): the loop cannot form.** Under R3 the ledger never touches `total_persons`, so
`PersonPhoneLeftBehindSensor` (`binary_sensor.py:2185-2189`, `house.total_persons > 0` → off) reads the same value as
develop and `get_residents_home` (`presence.py:5425`) cannot be moved by the ledger. Pinned by
`test_vision_guest_does_not_flip_phone_left_behind` (vision_led, `vision_hold = 2`, PLB on: stays on;
`residents_home` unchanged across 3 evaluations). INV-P2-IDENTITY gains: "the ledger never changes any input of
`get_residents_home`".

**R3 (F3, HIGH; Q6 adopted): hold-only.** The vision guest never enters `unidentified_count`, `total_persons` or
`census_count`. The census publishes it as a separate field `CensusZoneResult.vision_hold: int` (0 unless effective
`vision_led` and healthy; computed in `_apply_enhanced_house_census` from the one estimate read) plus the unrecorded
diagnostic attributes. Exactly four AWAY-ENTRY predicates read it. **[Rev 5: do NOT add `vision_hold == 0` as a
conjunct of the whole predicate. That also disables the "already AWAY → return None" arms and can CAUSE ARRIVING
(§16b B6 repros). Build the exact shape in §16b B6.]**

| Site (develop) | Predicate |
|---|---|
| `presence.py:1181` nobody-home | `census_count == 0 and not zone_occ` |
| `presence.py:1227-1232` path α | trackers away, `unidentified_count == 0`, face 0 |
| `presence.py:1300-1310` path β | `unidentified_count == 0 and census_count == 0 ...` |
| `presence.py:7887-7895` D2 external-empty ticks | `census == 0 and unid == 0` |

`vision_hold` is threaded into `infer()` as one kwarg (same pattern as `any_zone_occupied_for_empty`), read once per
tick into a local. Consequence by construction: AWAY → ARRIVING is driven only by `census_count`, which the ledger does
not touch, so the ledger can delay AWAY but never initiate ARRIVING, WAKING, a re-arm bypass or a severity change. The
P2-F preconditions on the lockout live-validation and on Q6 are dropped (no ledger path reaches them); the operator's
auto-follow setting is irrelevant to this cycle. Cost accepted: from AWAY, a vision-only guest entry does not wake the
house (the camera path still does, as today). Old P2-D4 ceiling change is removed (nothing to clamp).
Tests: `test_ledger_never_initiates_arriving` (house AWAY, vision_led, entry term n = 3, camera 0 → stays AWAY),
`test_vision_hold_blocks_each_away_entry_predicate` (parametrised over the 4 sites), `test_vision_hold_zero_byte_identical`
(golden `infer()` replay with `vision_hold = 0` vs develop), `test_wake_backstop_ignores_vision_hold`. Mutation: drop
the conjunct at each site in turn → the matching parameter fails (4 drills).

**R4 (F4, MEDIUM): one resident term, the larger.** `R = max(residents_home, identified_count)`, where
`residents_home = PresenceCoordinator.get_residents_home_count()` (`presence.py:5433`, trust state, PLB-aware) and
`identified_count = len(recognized_set)` (BLE ∪ face ∪ egress union, `camera_census.py:6468` develop cbeb8c3f,
`_apply_enhanced_house_census`). `guest_vis = max(0, L − R)`; the floor (rule 4) and the anchor (R1) use the same R.
Why the max: a resident in the union but not in trust-home (face of an overruled adult, egress TTL) or in trust-home but
not the union (phone-left-behind off, BLE-stale) must not be read as a guest; the max errs toward fewer guests, i.e.
toward today's AWAY behaviour. Computed in the census (both values local there; presence getter called once).
Tests: `test_resident_term_union_larger`, `test_resident_term_trust_larger`.

**R5: invariants restated.**
- **INV-P2-DISCHARGE:** under effective `vision_led`, once interior camera bodies == 0 and no room rising edge,
  continuously for `CROSSING_VISION_LEDGER_EMPTY_RESET_S`, `vision_hold` == 0 at the next evaluation, for any crossing
  sequence, resident tracker state (incl. a phone left at home) or restart. The predicate reads no house state, census
  output, resident set or ledger value.
- **INV-P2-NO-ACCESS:** the ledger reaches house state ONLY through `vision_hold` in the four AWAY-entry predicates; it
  can never cause any house-state transition other than "AWAY not entered this tick". No reader of `census_count`,
  `total_persons`, `unidentified_count`, ARRIVING, WAKING or any access / alarm / severity consumer sees a different
  value than develop. Break it by: any read of `vision_hold` / ledger / `guest_vis` outside the four sites and
  diagnostics (reviewer D greps); any write of the ledger into the census numeric fields.

**R6 (F5): §15.2a readers re-checked against R3.**

| Reader | Under R3 |
|---|---|
| SC auto-follow `arriving → DISARMED` (`security.py:189-195`) | unreachable (ledger cannot cause ARRIVING) |
| Exterior severity on ARRIVING (`perimeter_alert.py:2004-2015`) | unreachable |
| Wake backstop (`presence.py:199-204`) | unchanged (reads `census_count`) |
| ARRIVING re-arm bypass (`presence.py:7027-7050`) | unchanged |
| Boot settle release (`presence.py:7136-7150`) | unchanged |
| D2 external-empty (`presence.py:7887-7895`) | gains `vision_hold == 0` (AWAY entry; site 4 in R3) |
| Sleep raw-hold / zone-hold-all-away pages (`presence.py:4345-4360`, `:4444-4456`) | unchanged: they keep firing on a ledger hold, no longer silenced |
| `PersonPhoneLeftBehindSensor` (`binary_sensor.py:2180-2190`) | unchanged (R2) |
| `house_status.py:206-210` | unchanged |
| `SanctionChecker` `unknown_present` (`security.py:282-346`) | must stay unwired; reviewer D greps |

(§20 additions from this section are folded into the §20 table, rev 5.)

**R7 (Q7):** Rev 4 guard A / veto B stay parked (operator answer 2026-11-13).

## 16b. Rev 5: binding build spec (plan review #2, adversarial build-prediction)

Verified against develop cbeb8c3f. Where §16, §16a, §18 or §19 differ, this section wins.

**B1. Anchor predicate (final).** Evaluated every `CROSSING_VISION_LEDGER_EVAL_S` (60 s) by a tracked
`async_track_time_interval` in `CrossingVisionShadow` (unsub in teardown). The window `[t_start, now]` holds iff, at every
sample in it: the camera body total (B2) is a number and == 0; `camera_input_dark` (census payload key,
`camera_census.py:1890`) is False; no Tier-1 room rising edge was noted; and no ENTRY term was applied. Any failing
sample, rising edge or applied entry term sets `t_start = None`; the next passing sample sets `t_start = now`. The anchor
fires when `now − t_start ≥ CROSSING_VISION_LEDGER_EMPTY_RESET_S`: `L = R_last` (B4), state `known`, residue =
`L_before − R_last`, `t_start = now` (re-arms; a second anchor in the same quiet spell records residue 0). The predicate
never reads house state, `census_count`, `unidentified_count`, `residents_home` alone, or `L`. Exit terms, reconciles and
the floor do NOT restart the window.
- Why entry terms restart it: without that, an entry applied at second 3599 of a quiet window is erased at 3600 (the
  person who just came in is reset away). A stream of entry terms with no body or edge ever seen can delay the anchor
  indefinitely; that is what `crossing_ledger_stuck` (B7) pages. INV-P2-DISCHARGE (§16a R5) gains the conjunct "and no
  entry term applied" in its window.
- Why `camera_input_dark` stops the window: a dark fleet reads 0 bodies because nothing can be seen. Resetting then is
  today's behaviour (safe direction) but would score as a "true empty" for bar a. The window does not run while dark.
- Boot: `t_start = None` and the body total is None until the first census tick after setup delivers one. The initial
  attribute value is not evidence.
- Dark means unhealthy: while `camera_input_dark` is latched or the body total is None, `census_tick` returns
  `healthy = False`, so `vision_hold = 0` (B5). [rev 6: `vision_hold` does not exist; read as `vision_* = None`, no AWAY effect] Without this, a fleet dark for days would stop the window AND hold AWAY
  out on a ledger nothing can discharge (B7 counts only zero-body samples, so it would never page either).

**B2. Camera body input.** NEW census scalar `PersonCensus._last_house_camera_bodies: int | None` (None at construction),
written once per census run from the house raw path's `camera_total` (`camera_census.py:2140-2210`: every configured
interior platform, before face subtraction and BLE cancel), and None when that path sets `degraded` with all platforms
unavailable (`:2168-2173`). Do NOT use `_last_camera_total_pre_cancel` (`:6069`): it counts only Frigate cameras and
subtracts one body per camera with a fresh face (`:6040-6042`), so a resident, a named guest, or a guest mislabelled as a
resident (the 10-24 Jaya-as-Oji case) on camera reads 0 and the anchor fires with a body in view.

**B3. Sampling note.** "Continuously" means "at every 60 s sample". A body seen only between samples is missed (accepted;
the census itself samples sensors on its own interval). The window bound therefore carries +1 eval interval.

**B4. Census ↔ ledger call (one site, sync, no await).** In `_apply_enhanced_house_census`, after `identified_count`
(`:6468`) and before the result is built: `R = max(presence.get_residents_home_count(), identified_count)` (presence via
the coordinator manager; missing presence or any error → `R = identified_count`), then one call
`hass.data[DOMAIN]["crossing_vision"].census_tick(now, resident_term=R, camera_bodies=self._last_house_camera_bodies,
camera_input_dark=self._camera_input_dark_latched)`. It applies the floor `L = max(L, R)` while `known`, stores
`R_last`, records the body sample for B1, and returns `(guest_vis | None, healthy)`. Missing object or any exception →
`(None, False)` and `vision_hold = 0`. [rev 6: `vision_hold` does not exist; read as `vision_* = None`, no AWAY effect] This replaces the §16.3 getter. The vision module stores what it is given; it never
reads the census or presence itself, so there is no second census. The B1 timer reads only values stored by the latest
`census_tick` (a sample whose stored body value is older than 2 × `CROSSING_VISION_LEDGER_EVAL_S` counts as failing).
Order: `_refresh_camera_input_dark_latch()` runs AFTER the house result is built (`camera_census.py:1860`), so the latch
passed here is the previous run's. Accepted: one census interval of lag, failing toward "window not running" for the
first dark tick only on a healthy→dark edge; on dark→healthy the window starts one run late.

**[SUPERSEDED rev 6, DO NOT BUILD]** **B5. `vision_hold` value.** `CensusZoneResult.vision_hold: int = 0` (dataclass default 0, so the property zone, the raw
path and every test fixture carry 0). Set on the house result only: `guest_vis` when effective authority is `vision_led`
(const AND switch ON AND `healthy` AND `guest_vis is not None`), else 0. Published on `SIGNAL_CENSUS_UPDATED` as
`"vision_hold": int(...)`. Presence `_handle_census_update` (`presence.py:5609`) reads
`int(census_data.get("vision_hold", 0) or 0)`, on error 0, into `self._vision_hold`, and adds
`or old_vision_hold != self._vision_hold` to the run-inference trigger at `:5676-5685` (otherwise a 1 → 0 release waits
for the 60 s periodic tick). `self._vision_hold` initialises to 0 and is NOT restored or boot-seeded (the boot seed at
`:3220-3245` stays as is). A None anywhere is a bug: `None == 0` is False, so a None reaching a predicate written as
`vision_hold == 0` would block every AWAY.

**[SUPERSEDED rev 6, DO NOT BUILD]** **B6. The four AWAY-entry sites: exact shape.** `infer()` gains the kwarg `vision_hold: int = 0` (default 0, so every
existing caller and test is byte-identical) and `_run_inference` passes `vision_hold=self._vision_hold` at the
`infer(` call (`presence.py:7976`). Sites 1-3 change ONLY the arm that returns `HouseState.AWAY`; the
"already AWAY → return None" arm and its `_veto_path` write stay first and unchanged:

```
if <existing predicate, unchanged>:
    if current_state == HouseState.AWAY:
        ...unchanged...; return None
    if vision_hold <= 0:
        ...unchanged confidence / _veto_path / log...; return HouseState.AWAY
    self._vision_hold_blocked = True   # diagnostic only; fall through as if the predicate were False
```

| # | Site (develop cbeb8c3f) | Shape |
|---|---|---|
| 1 | nobody-home `presence.py:1181-1189` | as above |
| 2 | path α `:1227-1239` | as above |
| 3 | path β `:1305-1345` (both `lost_admitted` labels) | as above |
| 4 | D2 `_external_empty_this_tick` `:7888-7892` | add `and self._vision_hold <= 0` to the tick predicate (it only feeds β's immediate limb; while held the counter resets to 0, so after release β's immediate limb needs N fresh ticks, accepted) |

Why not a conjunct on the whole predicate (the R3 wording): it removes the "already AWAY" holds, and the ladder then
reaches `has_people` → ARRIVING (`:1349-1370`). Legal repros: (a) house AWAY, all trackers away, unidentified 0, face 0,
`census_count = 1` from an egress-face identity still inside its TTL (path α holds AWAY today regardless of census), drift
`L = 3`, `R = 1` → `vision_hold = 2`; with a whole-predicate conjunct α fails, β fails on census, `has_people` is True →
ARRIVING. (b) `camera_input_degraded` True, an outdoor zone occupied (patio), census 0: nobody-home fails on the zone,
α is skipped, β holds AWAY via its already-AWAY arm today (indoor guard reads indoor zones only); with the conjunct it
falls to `has_people = any_zone_occupied` → ARRIVING. Both break INV-P2-NO-ACCESS. NOT a site: the Pattern-A
diagnostic helper `should_veto_due_to_reliable_signals` (`presence.py:2219-2234`, spelled `unid == 0 and census == 0`,
writes only `_last_veto_decision`, display, `sensor.py:5946`, `:6562`). It will report `fired = True` while the hold
blocks AWAY; accepted, and `vision_hold` / `vision_hold_blocked` are published beside it on the house-state sensor
(unrecorded) so the two read together. Also not a site: the v4.7.14 INFO log at `:8136-8150` (keys on
`new_state == AWAY`, so it stays silent while held).

Tests (replace the R3 list): `test_ledger_never_initiates_arriving_identity_census` (repro (a): AWAY, egress identity
census 1, `vision_hold = 2` → `infer()` returns None), `test_ledger_never_initiates_arriving_degraded_outdoor` (repro
(b)), `test_vision_hold_blocks_each_away_entry_site` (parametrised, 4 sites, HOME_DAY start), `test_vision_hold_default_zero_byte_identical`
(golden `infer()` replay omitting the kwarg vs passing 0 vs develop), `test_vision_hold_none_payload_reads_zero`,
`test_vision_hold_change_triggers_inference`, `test_wake_backstop_ignores_vision_hold`. The old
`test_ledger_never_initiates_arriving` with census 0 is a hollow anchor (with census 0 `has_people` is False under both
shapes) and is dropped. Mutations: (i) move the `vision_hold` check above the already-AWAY arm at site 2 → the
identity-census test fails; (ii) same at site 3 → the degraded-outdoor test fails; (iii) drop each site's check → the
matching parameter fails (4 drills); (iv) drop the trigger clause → the change-triggers test fails.

**B7. Stuck page (final).** `crossing_ledger_stuck` HIGH via `fire_stuck_signal`: `guest_vis ≥ 1` while every B1
sample for `CROSSING_VISION_LEDGER_STUCK_S` (7200) had zero bodies and no rising edge (entry terms do not count here, so
a stream of entry terms that keeps blocking the anchor IS paged). Resident-independent. Fires in `evidence_only` too.
RAM latch, re-armed when `guest_vis` returns to 0. This replaces the P2-D5 wording keyed on `residents_home`.

**B8. Reconcile timing.** A departure edge at `t_e` is judged at `t_e + LAG + CROSSING_VISION_TIMEOUT_S +
EVENT_END_WAIT_S` (a tracked `async_call_later`, one per pending departure, cancelled in teardown, superseded per person
by a newer edge), so a slow vision outcome for the matching exit is not missed. Matching uses the crossing time E of
exit terms, not the time the term was applied: an exit term with `E ∈ [t_e − LEAD, t_e + LAG]` cancels the reconcile.
A reconcile is applied only while `known`. Restart drops pending reconciles (ledger is `unknown` after restart anyway).
Test: `test_reconcile_waits_for_late_exit_outcome` (exit outcome applied 90 s after a departure edge with LAG 60 → no
reconcile, `L` decremented once). Mutation: judge at `t_e + LAG` → the test fails (double decrement).

**[SUPERSEDED rev 6, DO NOT BUILD]** **B9. What the hold still changes (accepted at the flip, operator checkpoint).** "AWAY not entered" is itself a reach:
while held, HVAC stays on home presets; the SC auto-follow `away → ARMED_AWAY` (`security.py:189-195`, when
`CONF_SECURITY_AUTO_FOLLOW` is on) does not arm; exterior-person severity follows the HOME_* row, not AWAY. These are
the cost of a correct hold and of a drift hold alike, bounded by B1 + B7. §16a R3's "never ... a severity change" is
corrected to "never initiates a transition"; the operator accepts the delayed arming at P2-F (record the live
auto-follow value in the disposition).

## 17. Go / no-go bars for the authority flip (measured on the dark ledger)

Measured by P2-D6 from live dark-ledger rows (or the offline replay of Phase 1 rows through the same `crossing_ledger`
code). Window: ≥ 7 days AND every bar's minimum sample. All thresholds are rung-1 constants shared by the scorer and the
P2-D5 regression trip-wire.

| Bar | Oracle | Pass | Knob (rung 1) |
|---|---|---|---|
| **a. Drift** | Each independent empty anchor (§16b B1): residue = pre-anchor `L − R_last`. Truth: 0 | residue == 0 on ≥ 80 % of ≥ 10 anchors AND abs(residue) ≤ 1 on every anchor | `CROSSING_VISION_GO_DRIFT_ZERO_SHARE` 0.80, `CROSSING_VISION_GO_DRIFT_MAX_ABS` 1, `CROSSING_VISION_GO_MIN_ANCHORS` 10 |
| a2. Reconcile load | Share of resident departures that needed rule 5 | ≤ 20 % (more = uncovered-door problem the ledger hides, not solves) | `CROSSING_VISION_GO_RECONCILE_SHARE_MAX` 0.20 |
| **b. Resident arrivals** | Each counted residency `arrival` record: a watched-door entry term in [edge − 300 s, edge + 60 s] (manual §5.2 entry window) with n ≥ 1 | ≥ 90 % matched; of matched, ≥ 75 % `term_source = vision` | `CROSSING_VISION_GO_ARRIVAL_MATCH_MIN` 0.90, `CROSSING_VISION_GO_VISION_TERM_SHARE_MIN` 0.75 |
| **c. Groups** | ≥ 10 deliberately sampled crossings of 2-3 people (P2-D7), operator-labelled | vision exact ≥ 8/10; no vision undercount by ≥ 2 | `CROSSING_VISION_GO_GROUP_EXACT_MIN` 0.80, `CROSSING_VISION_GO_GROUP_MIN_N` 10 |
| d. False guest | Census evaluations with ≥ 1 resident home and no operator-labelled guest | `guest_vis ≥ 1` on ≤ 2 % of evaluation time | `CROSSING_VISION_GO_FALSE_GUEST_MAX` 0.02 |
| e. Known | Ledger `known` share of time | ≥ 90 % | `CROSSING_VISION_GO_KNOWN_SHARE_MIN` 0.90 |

Bar (b) needs the residency producer firing (§15.3). If P2-D0 (i) finds the first edge did not write a row, (b) uses `person.*` `not_home →
home` edges from the recorder for the same residents (same edge definition, read offline) and the dead producer
becomes its own card. Per-crossing §15.7a numbers are reported beside the bars, not gating (C4).

Discriminates: bar a separates "vision counts well" from "the floor and reconcile do the work" (a2 reported beside
it); bar b separates "coverage" (matched) from "vision quality" (vision share); bar d is the cost the flip imposes
(AWAY suppressed by a phantom guest), measured directly.

## 18. Deliverables (Phase 2)

All on `feature/crossing-vision-census` off develop after Phase 1 merges. Build and ship dark while Phase 1 collects.

### P2-D0: read-only probe (now; ura-prober; gates the FLIP, not the build)

(i) Residency fire check: confirm the first resident `person.*` edge after the v5.108.19 restart (17:44 UTC 11-13)
writes a `person_arrival` / `person_departure` row (README_v5.108.19 L1). (ii) Count independent empty anchors (§16 rule 2 predicate) over 14 days from the
recorder (person states, interior camera person counts, room occupancy edges) at 1800 / 3600 / 7200 s. (iii) At ±30 s,
wrong-event rate on the 117 D0c clusters (a matched event whose camera/time is not the crossing's). (iv) D0a on entry
`01M7B731T26P2HXVW77AQR62PP`: one `image_analyzer`, one `video_analyzer` (event id), status, latency, structured
response present. ≤ 6 model calls.
**Acceptance:** audit `docs/planning/AUDIT_crossing_vision_p2_d0_<date>.md`, one row per item with numbers.
**Live:** none.

### P2-D1: Luna provider (Tier 1; folds Part A D5)

`CONF_CROSSING_VISION_PROVIDER_ID` (rung 2, integration options Advanced, empty = perimeter provider) set to the new
entry; `CROSSING_VISION_MODEL` → `gpt-6-luna`. Ship before the shadow switch goes on so all bar data is one model
(Q3). **Tests:** `test_provider_override_used`, `test_empty_override_falls_back`. **Live:** ≥ 1 `ok` row with
`model = gpt-6-luna`.

### P2-D2: `crossing_ledger.py` pure core (Tier 3)

Rules §16 as a pure class; no HA import, no clock read (time passed in). Methods: `apply_term`, `floor`,
`reconcile_departure`, `note_rising_edge`, `census_tick(now, resident_term, camera_bodies, camera_input_dark)`,
`evaluate_anchor(now)` (rev 5: no residents argument; B1/B4), `snapshot`.
**Tests** (`quality/tests/test_crossing_ledger.py`): `test_boot_unknown_until_anchor`,
`test_anchor_needs_zero_bodies_and_no_edge_for_window` (rev 5; was `..._all_three_...`), `test_anchor_sets_L_to_resident_term`,
`test_entry_term_restarts_anchor_window`, `test_exit_term_does_not_restart_window`, `test_dark_fleet_stops_window`,
`test_none_bodies_is_failing_sample`, `test_rising_edge_restarts_anchor_window`,
`test_stuck_on_sensor_does_not_block_anchor`, `test_exit_clamps_at_zero_raw_kept`, `test_floor_raises_only`,
`test_reconcile_only_without_exit_term`, `test_ambiguous_no_term`, `test_cluster_one_term_same_direction`,
`test_cluster_mixed_direction_per_member`, `test_fallback_camera_then_one`, `test_residue_recorded_before_reset`,
plus config extremes: `test_reset_window_zero_means_instant_anchor`, `test_reconcile_window_zero_disables`,
`test_fallback_skip_policy`. **Mutation drills:** remove the rising-edge restart → `test_rising_edge_restarts_anchor_window`;
read house state in the predicate (inject) → `test_anchor_independent_of_house_state`; drop the floor → `test_floor_raises_only`;
remove the entry-term restart → `test_entry_term_restarts_anchor_window`; re-add a residents-empty conjunct →
`test_guest_surplus_discharges_with_resident_phone_home`.

### P2-D3: ledger wiring in `crossing_vision.py` (Tier 3)

Feed terms from every outcome path (each of the ten outcomes incl. `clustered`, `off` excluded: no row, no term while
the shadow switch is off, so the ledger goes `unknown` when the switch turns off). Subscribe residency departures and
substrate rising edges (unsubscribed in teardown). One `crossing_vision_ledger` episode per term / reset / reconcile
(attrs: kind, n, term_source, L before/after, residue, crossing_key). Diagnostics on the Outside: Open Tracks sensor
(unrecorded): `crossing_ledger` {state, L, L_raw, last_anchor, residue_last, terms_today by source,
reconciled_today}. **Tests:** `test_every_outcome_yields_one_term_or_documented_none`, `test_switch_off_sets_unknown`,
`test_teardown_unsubscribes_ledger_feeds`, `test_ledger_episode_per_term_batched`. **Live:** after deploy, ≥ 1
`crossing_vision_ledger` term row with non-null `L_after`; `crossing_ledger.state` reads `known` after the first empty
anchor.

**[SUPERSEDED rev 6, DO NOT BUILD: P2-D4 is Part B §B7]** ### P2-D4: census site (Tier 3, house-state rule)

**SUPERSEDED by §16a R3 (rev 4):** the vision guest no longer enters `unidentified_count` / `total_persons`; it is a
separate `vision_hold` field read only by the AWAY-entry predicates. Text below kept for the record.

**Build instead (rev 5):** census side = §16b B2 (publish `_last_house_camera_bodies`), B4 (one `census_tick` call,
`R`), B5 (`vision_hold` field, payload key, unrecorded attributes `vision_guest_estimate`, `vision_case`,
`vision_authority`, `vision_hold` on `sensor.universal_room_automation_persons_in_house`); no change to
`unidentified_raw`, the clamp ceiling, `active_platforms` or any numeric field. Tests: `test_evidence_only_byte_identical_golden`
(every numeric field AND `vision_hold == 0`), `test_vision_led_numeric_fields_unchanged` (vision_led, `guest_vis = 2`:
`unidentified_count` / `total_persons` equal develop, `vision_hold = 2`), `test_switch_off_forces_hold_zero`,
`test_missing_vision_object_hold_zero`, `test_estimate_exception_hold_zero`, `test_property_zone_hold_zero`,
`test_camera_bodies_counts_face_labelled_person` (a Frigate camera with count 1 and a fresh face → bodies 1, while
`_last_camera_total_pre_cancel` = 0). **P2-D4b (presence):** §16b B5 handler + trigger, B6 sites and tests.
Mutations: drop the authority test → the golden fails; read `_last_camera_total_pre_cancel` instead → the face-labelled test fails.

**[SUPERSEDED, record only:]**


In `_apply_enhanced_house_census` only: read the estimate once per evaluation into a local (before any await; the
method is sync). Always compute `guest_cam = camera_unrecognized` (today) and the case (A/B/C/D; agreement value via
`CENSUS_AGREEMENT_*`) and publish them as unrecorded attributes on `sensor.universal_room_automation_persons_in_house`
(`vision_guest_estimate`, `vision_case`, `vision_authority`). Under effective authority `vision_led` (const `vision_led`
AND downgrade switch ON AND estimate healthy): `unidentified_raw = guest_vis` for cases A/B/C; case D keeps
`camera_unrecognized`; and the clamp ceiling becomes `max(camera_total_pre_cancel, identified_count, identified_count +
guest_vis)` (without this the INV-CENSUS-ATTRIBUTION clamp at ~6505 silently discards every vision guest above the
camera total: the site a builder would miss). `vision` appended to `active_platforms` when used. Nothing else in the
census changes. **Tests:** `test_evidence_only_byte_identical_golden` (replay fixture of census inputs across all four
cases, every numeric field equal to develop), `test_vision_led_case_b_uses_vision`, `test_vision_led_case_d_camera`,
`test_vision_led_ceiling_admits_vision_guest`, `test_switch_off_forces_evidence_only`, `test_missing_vision_object_case_d`,
`test_estimate_exception_case_d`. **Mutation drills:** revert the ceiling change → `test_vision_led_ceiling_admits_vision_guest`;
drop the authority test → `test_evidence_only_byte_identical_golden`. **Live:** attributes present; under
`evidence_only` `unidentified_count` unchanged vs the attribute `vision_guest_estimate` (they may differ; the count must
equal the camera path).

**[SUPERSEDED rev 6 for the authority / switch / P2-F text; only the trip-wires restated in Part B §B7 apply]** ### P2-D5: authority knob, downgrade switch, trip-wires (Tier 3)

`CROSSING_VISION_COUNT_AUTHORITY` (rung 1, ships `evidence_only`; values `evidence_only` / `vision_led`).
`switch.ura_crossing_vision_census_authority` (rung 3, default ON, RestoreEntity): OFF forces `evidence_only` at the
next census evaluation; it can only DOWNGRADE (Q2). After a restart the switch restores its last state; with no stored state it starts ON
(the const still gates). Trip-wires:
`crossing_ledger_stuck` exactly as §16b B7 (rev 5; the old "`L ≥ 1` while residents_home is empty" keying is
superseded); `crossing_vision_disagree` via AnomalyDetector → NM when B or C persists ≥
`CROSSING_VISION_DISAGREE_PERSIST_N` per door in 24 h; `crossing_ledger_anchor_zero` LOW when no empty anchor in
`CROSSING_VISION_LEDGER_ANCHOR_ZERO_S` (zero-fire); under `vision_led`, any §17 bar below threshold over rolling 14 d →
NM recommending the switch off. `crossing_vision_ledger` joins `MEMORY_WRITER_BACKED_EPISODE_TYPES`.
**Tests:** `test_stuck_ledger_pages_once`, `test_disagree_persist_pages`, `test_anchor_zero_pages`,
`test_bar_regression_pages_only_vision_led`. Mutation: remove the stuck latch → `test_stuck_ledger_pages_once`.

### P2-D6: scorer extension + disposition (read-only script)

Phase 1 D4 script gains: dark-ledger replay through `crossing_ledger` from `crossing_vision_shadow` rows (so bars
compute before P2 deploys), bars a-e, per-door/direction/day-night breakdown, per-crossing §15.7a diagnostics.
Disposition audit `docs/planning/AUDIT_crossing_vision_ledger_disposition_<date>.md`: **FLIP-READY** (all bars) /
**HOLD** (named failing bar, its revival number) / **PARK** (bar a or b fails twice). One query, not a watch.

### P2-D7: group sample (operator action, ~15 min)

Ten staged crossings of 2-3 residents (garage A and front, ≥ 3 at night), times noted; labels committed as
`quality/tests/fixtures/crossing_vision_groups_labelled.json`. Organic multi-person crossings are too rare to wait for
(1 in 45, D0b).

**[SUPERSEDED rev 6, DO NOT BUILD]** ### P2-F: the flip (Tier 3 checkpoint)

One-line change `CROSSING_VISION_COUNT_AUTHORITY = "vision_led"` with the disposition audit attached. Preconditions,
all required (rev 5): P2-D6 FLIP-READY; 4 code reviews of P2-D2..D5 passed earlier; the operator accepts the §16b B9
costs (delayed HVAC away presets, delayed auto-follow arming with its live setting recorded, HOME_* severity row while
held). The lockout live-validation and SC `arriving → DISARMED` preconditions of rev 3 are dropped: under hold-only the
ledger cannot cause ARRIVING (§16a R3, §16b B6). **Approver: the operator**, at the Tier 3 pre-deploy checkpoint. Revert: the switch (seconds) or the
const (reviewed).

## 19. Falsifiable invariants (reviewer D breaks these)

**Rev 4: INV-P2-DISCHARGE and INV-P2-NO-ACCESS are restated in §16a R5; the restatements win.** **Rev 5: everything
below in §19 is [SUPERSEDED] except INV-P2-DARK (amended: "and `vision_hold` == 0") and the late-term rule. The two
"Plan-review #1 leak" paragraphs are CLOSED by §16a R1-R4 and §16b. INV-P2-IDENTITY's formula is
`guest_vis = max(0, L − R)` (R4), not `L − residents_home`. INV-P2-DISCHARGE's window also requires "no entry term
applied" (§16b B1), and `vision_hold` is 0 whenever the fleet is dark (B1, B5); its bound is `CROSSING_VISION_LEDGER_EMPTY_RESET_S` + one eval interval + one
census interval.**


**INV-P2-DISCHARGE (load-bearing).** Under effective `vision_led`, for ANY sequence of crossings, terms, missed exits,
vision errors, cap skips and restarts: once `get_residents_home()` is empty, the interior camera body total is 0 and no
room rising edge has occurred, continuously for `CROSSING_VISION_LEDGER_EMPTY_RESET_S`, `guest_vis` is 0 or None at the
next evaluation, so the ledger never holds `unidentified_count` > 0 (or `census_count` > 0) beyond that window plus one
evaluation interval. The predicate reads no house state, census result or ledger value.
Break it by: any reset path that reads house state; a term applied after the reset from a crossing whose E precedes
the anchor (late outcomes: a call completing up to `CROSSING_VISION_TIMEOUT_S` + `EVENT_END_WAIT_S` after t0); a
restart that restores `known` with a stale L; a floor raise from a GPS-only `home` the BLE rule overrules.
(Late terms: a term whose crossing E is earlier than the last anchor is recorded but not applied.)
**Plan-review #1 leak (HIGH), must be closed before build.** The invariant is conditional on `get_residents_home()`
going empty, which a legal config can prevent forever: a resident leaves a phone at home with the phone-left-behind
sensor disabled (its default, `binary_sensor.py` `_attr_entity_registry_enabled_default = False`) or BLE-stale-home;
`residents_home = 1` for the whole absence. Repro: L drifts to 2 (one missed exit) with Oji home; Oji leaves through
an uncovered door, phone on the desk → reconcile needs a departure edge, none comes (tracker still `home`); `guest_vis
= 2 − 1 = 1` → `census_count ≥ 1` → no AWAY for the whole trip, and `crossing_ledger_stuck` (keyed on residents_home
empty) never fires. Today the camera path lets AWAY happen. Required: a second, residents-independent discharge, e.g.
anchor B = interior camera bodies 0 AND no room rising edge for `CROSSING_VISION_LEDGER_EMPTY_RESET_S` → `L =
residents_home` (clears the guest surplus, keeps the floor), plus the stuck trip-wire keyed on `guest_vis ≥ 1` with no
camera body and no rising edge for `CROSSING_VISION_LEDGER_STUCK_S`, independent of residents. Test:
`test_guest_surplus_discharges_with_resident_phone_home`.

**INV-P2-DARK.** With effective authority not `vision_led` (const, switch OFF, or estimate unhealthy), every numeric
field of every `CensusZoneResult` and every `infer()` input equals develop's for the same inputs. Break it by: any
second read site of the estimate; the ceiling change applied outside `vision_led`.

**INV-P2-NO-ACCESS.** No lock, garage lockout, alarm, expected-arrival or NM-severity path reads the ledger,
`guest_vis` or the vision attributes; `vision_led` cannot be set while any house-state edge the ledger can cause
(ARRIVING from AWAY; WAKING via the wake backstop) releases an access consumer or disarms the alarm. Today that set is:
garage lockout (ARRIVING holds since v5.108.18/19; live-validation pending with the lockout switch OFF) and the SC
auto-follow map `arriving → DISARMED` (`security.py:193`, live when `CONF_SECURITY_AUTO_FOLLOW` is on). Exterior
CRITICAL-on-ARRIVING (`perimeter_alert.py:2004`) is a severity reach the operator accepts or gates at the flip. Break
it by: a grep hit outside the census site and diagnostics; a flip with the lockout hold not live-validated; a flip with
auto-follow on and the `arriving → DISARMED` row unchanged; a producer wiring `unknown_present` from the census.

**INV-P2-IDENTITY.** The ledger never changes `identified_count`, `identified_persons`, any `person_id` or any resident's
home/away; `guest_vis = max(0, L − residents_home)` only. Break it by: any write to the egress union or sightings from
the ledger.
**Plan-review #1 leaks (HIGH).** (1) Feedback: `PersonPhoneLeftBehindSensor` turns OFF when `house.total_persons > 0`
(`binary_sensor.py:2185-2189`) and `get_residents_home` excludes a resident only while that sensor is ON
(`presence.py:5425`). Under `vision_led`, `guest_vis ≥ 1` raises `total_persons` → the sensor goes off → the resident
re-enters `residents_home` → `guest_vis` drops → the sensor can go on again: the ledger changes a resident's home status
and can oscillate. The build must break the loop (the sensor reads the camera-path total, e.g. `total_persons −
vision guest`, or the ledger's `residents_home` input ignores the PLB term) with a test
`test_vision_guest_does_not_flip_phone_left_behind`. (2) Concept split (Bug Class #63): `guest_vis` subtracts
`residents_home` (trust state) but the census adds it to `identified_count` (`recognized_set`, BLE + face union,
`camera_census.py` ~6468). A resident in one set and not the other is counted twice or not at all. The plan must state
which resident set is subtracted and prove the two agree, or subtract `identified_count` at the census site
(`guest_vis_census = max(0, L − max(residents_home, identified_count))`), with a test per disagreement direction.

## 20. Emission / decision-site enumeration

Rev 5 (folds §16a R3/R6 and §16b; develop cbeb8c3f line numbers). The rev-3 rows "House unidentified source" and
"House clamp ceiling" are removed: hold-only changes neither.

| Site | File:line | Change |
|---|---|---|
| Camera body scalar | `camera_census.py:2140-2210` raw house `camera_total` → `_last_house_camera_bodies` | P2-D4, publish only (§16b B2) |
| Census ↔ ledger call + `vision_hold` producer | `_apply_enhanced_house_census` (`:6407`), after `identified_count` (`:6468`) | P2-D4, one `census_tick` call, `CensusZoneResult.vision_hold` (§16b B4/B5) |
| `unidentified_raw`, `raw_total_ceiling`, `active_platforms` | `:6470-6530` | **none** |
| Census payload | `SIGNAL_CENSUS_UPDATED` dispatch (`:1869-1900`) | P2-D4, add `vision_hold` key |
| Presence capture + trigger | `_handle_census_update` (`presence.py:5609`, trigger `:5676-5685`) | P2-D4b (§16b B5) |
| `infer()` kwarg + call | `presence.py:1072` signature, call `:7976` | P2-D4b, `vision_hold: int = 0` |
| AWAY-entry sites 1-3 | nobody-home `:1181`, α `:1227-1239`, β `:1305-1345` | P2-D4b, AWAY-returning arm only (§16b B6) |
| AWAY-entry site 4 | `_external_empty_this_tick` `:7888-7892` | P2-D4b, tick predicate (§16b B6) |
| Pattern-A diagnostic helper | `should_veto_due_to_reliable_signals` `:2219-2234` | **none** (display; publish `vision_hold` beside it) |
| ARRIVING / WAKING / wake backstop / re-arm bypass / boot settle / boot seed | `:1349-1370`, `:8142`, `:7027-7050`, `:7136-7150`, `:3220-3245` | **none** (read `census_count`, unchanged) |
| Sleep raw-hold / zone-hold-all-away pages | `:4345-4360`, `:4444-4456` | **none** (keep firing while held) |
| `PersonPhoneLeftBehindSensor`, `house_status.py:206-210`, display readers (`sensor.py:3776, :4148, :4217, :5159-5220`; `aggregation.py:6696-6778`; `binary_sensor.py:1891-1990`), census DB snapshot (`database.py:4485-4524`) | as listed | **none** |
| Raw house / property paths | `_cross_correlate_persons`, `_apply_enhanced_property_census` | none (property result keeps `vision_hold = 0`) |
| Ledger feeds | `crossing_vision.py` outcome writer (~:778-809), residency departures (B8 timer), substrate subscribe, B1 timer | P2-D3 |
| Lock / SC / perimeter / `SanctionChecker` | `security_lock_regime.py`, `perimeter_alert.py`, `security.py:282-346` | none; reviewer D greps that `vision_hold` / ledger / `guest_vis` appear only in the rows above and diagnostics |

"Unchanged" rows are proven by `test_vision_hold_default_zero_byte_identical`, `test_vision_led_numeric_fields_unchanged`
and the reviewer-D grep.

## 21. Numbers get knobs (Phase 2)

| Knob | Default | Rung | Why / kill |
|---|---|---|---|
| `CROSSING_VISION_COUNT_AUTHORITY` | `evidence_only` | 1 | Flip needs bars + operator (P2-F). `evidence_only` = dark |
| `switch.ura_crossing_vision_census_authority` | ON | 3 | Live downgrade only; OFF = `evidence_only` |
| `CROSSING_VISION_LEDGER_EMPTY_RESET_S` | 3600 | 1 | Anchor window; the INV-P2-DISCHARGE bound. 0 = reset as soon as the predicate holds (Q1) |
| `CROSSING_VISION_LEDGER_EVAL_S` | 60 | 1 | Anchor evaluation cadence |
| `CROSSING_VISION_LEDGER_RECONCILE_LEAD_S` / `_LAG_S` | 900 / 60 | 1 | Exit crossing usually precedes the tracker departure; 0/0 = reconcile off |
| `CROSSING_VISION_LEDGER_FALLBACK` | `camera` | 1 | Term for non-`ok` outcomes; `skip` = vision-only terms |
| `CROSSING_VISION_LEDGER_STUCK_S` | 7200 | 1 | Stuck-ledger page; 0 = off |
| `CROSSING_VISION_LEDGER_ANCHOR_ZERO_S` | 172800 | 1 | No anchor in 48 h pages LOW; 0 = off |
| `CROSSING_VISION_DISAGREE_FLAG_MIN` / `_PERSIST_N` | 1 / 5 | 1 | §15.7 names, values unchanged |
| `CROSSING_VISION_GO_*` (§17) | per table | 1 | Shared by scorer and regression trip-wire |
| `CROSSING_VISION_EVENT_MATCH_S` | 10 (→ 30 if P2-D0 iii ≤ 2 % wrong-event) | 1 | Coverage vs mismatch |
| `CONF_CROSSING_VISION_PROVIDER_ID` | empty (set to the new entry here) | 2 | Portable provider choice |
| `CROSSING_VISION_GO_ARRIVAL_WINDOW_BEFORE_S` / `_AFTER_S` | 300 / 60 | 1 | Bar b match window around the residency edge. Not `FACE_MATCH_ENTRY_WINDOW_*` (`const.py:3356-3357`, 60 / 300 around the crossing, opposite anchor); P2-D0 measures crossing-to-edge lag before the sign is fixed |
| `CROSSING_VISION_GO_WINDOW_DAYS` / `CROSSING_VISION_GO_REGRESSION_DAYS` | 7 / 14 | 1 | §17 minimum window; P2-D5 rolling bar-regression window |
| `CROSSING_VISION_EVENT_MATCH_WRONG_MAX` | 0.02 | 1 | P2-D0 (iii) threshold for moving the match window to 30 s |

## 22. Non-goals (Phase 2)

Identity from vision (no `IDENTITY_PROVENANCE_VISION` producer); vision direction; B-stage time-lapse, chains, interior
head count (§15.8 parked, revival: bar a fails on residue from uncovered doors); Protect-only crossings (Part A §10);
ledger replay across restarts (§16 rule 1); any change to GUEST (night-stay latch), the lock regime, SC, perimeter or
HVAC code; property-zone census; any NM text change other than the new pages.
**Parked-plan trigger check (plan review #1).** `PLANNING_house_state_sleep_mask_ble_memory_observability.md` line 492
parks Rev 4 guard A (camera-recency) and veto B (guest-room) with revival trigger "guest accuracy becomes a priority (a
long stay or a party)". This cycle's purpose is guest accuracy, so the trigger arguably fires; the operator decides
(Q7) whether Rev 4 A/B stays parked. **Answered 2026-11-13: stays parked**, since this cycle changes the count, not the SLEEP/guest-room
gates.

## 23. Tier and sequencing

**Tier 3 + house-state rule** (Tier 2-DB minimum for house state, elevated: rev 5 threads `vision_hold` from the census
into four AWAY-entry sites of the house-state engine; one mis-shaped site (a whole-predicate conjunct) lets the ledger
initiate ARRIVING, §16b B6). Two framing-disjoint plan reviews (completeness; adversarial build-prediction) before build; four code
reviews (A local; B integration / restart / byte-identical dark path; C per-site mutation; D adversarial completeness
on INV-P2-DISCHARGE incl. pre-existing readers); orchestrator re-grep + mutation; operator checkpoint before deploy and
again at the flip.

Order to completion:
1. Now: P2-D0 probe; P2-D1 Luna (Tier 1) with Phase 1 deploy; operator schedules P2-D7.
2. Phase 1 deploys, shadow switch ON (Luna). Rows accrue; P2-D6 replays the dark ledger from day 1.
3. P2-D2..D5 build in parallel with collection (`ura-super-builder`), reviews, ship DARK (`evidence_only`). Live
   ledger runs beside the replay (they must agree: a check of the build).
4. ≥ 7 days and bar minimums: P2-D6 disposition. FLIP-READY + operator accepts §16b B9 → operator approves P2-F (rev 5;
   the lockout and Q6 preconditions are dropped).

## 24. Operator answers (2026-11-13; all questions closed)

| Q | Answer | Where it lands |
|---|---|---|
| 1. Empty-anchor window | **3600 s** | `CROSSING_VISION_LEDGER_EMPTY_RESET_S` = 3600 (§21); P2-D0 (ii) still reports anchor counts at 1800 / 3600 / 7200 |
| 2. Authority knob rung | **Reviewed code constant + downgrade-only switch** | `CROSSING_VISION_COUNT_AUTHORITY` rung 1 + `switch.ura_crossing_vision_census_authority` rung 3 (P2-D5) |
| 3. Model for the bar data | **gpt-6-luna from shadow day 1** | P2-D1 ships before the shadow switch goes on |
| 4. Event match window | **±10 s until the wrong-event rate is measured** | `CROSSING_VISION_EVENT_MATCH_S` = 10; → 30 only if P2-D0 (iii) ≤ `CROSSING_VISION_EVENT_MATCH_WRONG_MAX` |
| 5. Group sample | **Operator stages ~10 group walks** | P2-D7 |
| 6. Ledger reach | **The ledger only delays AWAY** | §16a R3 + §16b B6 (hold-only); B9 lists what delaying AWAY still changes |
| 7. Parked Rev 4 guard A / veto B | **Stay parked** | §22 |
