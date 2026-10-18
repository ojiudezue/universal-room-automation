# AUDIT — The census arc, the simple-away guard, and one holistic plan

**Type:** investigation / audit only. No code changed. Not a build approval.
**Written:** 2026-10-18 by ura-planner. **Card:** CENSUS-OCCUPANCY-ESTIMATOR-1 (`operator_instruction_2026_10_18`), HOUSE-STATE-AWAY-FLAP-UNTRACKED-OCCUPANT-1.
**Read completely first:** `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (incl. §10 ledger; nothing here relies on #6, #11 or #12's refuted claims), `docs/architecture/SENSOR_FLEET_CLASSES.md`, `docs/Coordinator/IDENTITY_FUSION_CAMERAS_MANUAL.md`, CLAUDE.md (Institutional Context First, Prior-art scan, Producer/Consumer, Marginal-benefit, Measure-before-build).
**Also read:** `AUDIT_away_flap_untracked_occupant_would_have.md`, `CRITIQUE_census_occupancy_estimator.md`, `PLANNING_house_away_flap_untracked_occupant.md` (Rev 2), `PLANNING_census_occupancy_estimator.md` (headings + §7/§9), `PLANNING_census_inputs_first.md` (R2–R4), `DESIGN_census_simplification.md`, `PLANNING_census_garage_resident_corroborator.md` (via card), `AUDIT_census_subsystem_2026_10_04.md`, every census card listed in the brief, `kanban.history.yaml` (no census rows), READMEs v5.77.0–v5.82.0, v5.103.39, v5.103.47, v5.103.54, v5.103.64, memory bodies `project_session_pickup_2026_10_04`, `project_guest_mode_false_positive_backlog`, `project_presence_guest_latch_and_veto_gap`, `reference_egress_face_coverage_7pct_not_a_ceiling`, git log of `camera_census.py` / `transit_validator.py` / `presence.py`.

---

## Summary (plain language)

1. The arc you remember is the **10-03 party**: 9 guests plus a long-stay guest; the census read 2–3 all afternoon against a truth of 10–12, guest mode never came on, and the house went AWAY for an hour with ~11 people inside.
2. What followed was "fix the inputs, then re-run the replay, then build the estimator". The input fixes shipped (v5.103.39 door events, v5.103.47 name dedup, v5.103.54 boot display). **The re-run never happened.** The replay that was the go/no-go gate was never re-scored, because it was waiting on your answer about the 10-03 timeline (CENSUS-GROUND-TRUTH-CSV-FIX-1), and the estimator card has sat since.
3. Your sense is right: we measured once (the inputs looked fixed on 10-08/09), declared "estimator GO", and then stopped. Nothing measures whether the house is right about who is home.
4. The goal the arc was serving, in your words, is two bits, not a number: **is anyone home** (AWAY correct) and **is a guest here** (guest mode correct). The head-count is display.
5. Against that goal, the estimator is the wrong tool today. No consumer needs a count above 1, and its door tally fails because ~70% of door crossings are unnamed residents. Recommend PARK with triggers (as the 10-18 critique said).
6. The simple-away guard (cameras must have seen nobody for 10 min before AWAY) is mostly reuse: one new timestamp, one new knob, three existing AWAY branches. It fixes the short flaps (31 of 65 trip AWAY entries), not the guest in a bedroom.
7. The bedroom gap is filled by **extending the existing guest-room tracker** (it already knows "a non-resident is in Guest Bedroom 1/2 right now") into a veto on path α, the one AWAY branch that ignores room occupancy. Needs one fan-phantom probe first.
8. Observability is thin exactly where you need it: nothing on the Presence device or the v8 dashboard says *why* the house went AWAY, which branch did it, or how many times today. Fold three attributes, one counter and one v8 card into the same cycle.
9. Recommended set: guard + guest-room veto + observability as ONE Tier-3 cycle (Rev 3 of the AWAY-flap plan), the patio camera mask as a config action, a "score the goal" probe before and 14 days after, and park/close the rest. That covers the bedroom guest and the short flaps; it does not count parties or arm guest mode for common-area gatherings.
10. Five decisions for you are in §6, each with a default.

---

## 1. The census arc found

### 1.1 The episode
- **Date:** Saturday 2026-10-03. **Evidence:** `AUDIT_census_subsystem_2026_10_04.md` §0–§1 (operator truth: "8 guests arrived on 10-03 and stay until 10-04. A 9th arrived and left"; plus one long-stay guest). Footage audit `AUDIT_census_footage_ground_truth_2026_10_03.md:58`: peak deduped visible count 9 against truth ~10–12.
- **What URA did:** `persons_in_house` hourly mean 2.0–3.1 from 13:00 to midnight (error −8 to −10); `binary_sensor.ura_presence_coordinator_guest_mode` never on; house AWAY 15:57→17:00 with ~11 inside (subsystem audit §1.1, F5). Door ledger net entries−exits +9 vs truth +8 — the one input that tracked the truth.
- **Earlier sibling episode (08-15/16):** "census says 4 but there are 4 of us and 6 guests" (CENSUS-GUEST-FLOOR-1 origin) and the 7-h false GUEST on 08-16 (CENSUS-ACCURACY-1 `measured_incident_2026_08_16_guest_7h`). That August arc (v5.77.0–v5.82.1) is closed and is context, not the subject.

### 1.2 The plan that followed
Operator ruling 2026-10-03: "Fix census INPUTS before building the hybrid estimator, then re-run D0-REPLAY." Plans: `PLANNING_census_occupancy_estimator.md` (hybrid, approved and held), `PLANNING_census_inputs_first.md` (Rev 1–4, 10-04/05), `DESIGN_census_simplification.md` (10-05, draft, never committed as a decision). Recommendations R1–R8 from the subsystem audit.

### 1.3 Deliverable ledger

| Item | Source | Status | Version / commit | Live-validated? |
|---|---|---|---|---|
| R1 dead face-name feed (`async_entries_for_platform`) | subsystem audit R1 | **Shipped** | v5.103.39 (`ee0f96163`) | Yes (README_v5.103.39 table) |
| R3 / inputs-first D1: `_2` stem fix, 30 s per-door dedup, door neighbours, `peak_person_count` column | inputs-first R2.2/R3/R4 | **Shipped** | v5.103.39; fix-ups `4f6329fcc` | Yes, rows + config (README_v5.103.39: 17/19 rows with `peak_person_count`) |
| `CONF_MAIN_ENTRY_DOOR` options field | inputs-first R3.7 said defer | **Shipped with no consumer** (README_v5.103.39 §2: "consumer arrives with the estimator cycle") | v5.103.39 | n/a — Bug Class #53 shape |
| D2 resident attribution (Branch A replay-only + D known gap) | inputs-first R2.3 | **Replay half never run**; producer verify done (BLE entry attach already ships, EGRESS-BLE-ENTRY-ATTACH-1 REFUTED) | — | — |
| D3 interior over-count | inputs-first | **Dropped** (probe refuted, R2.4) | — | — |
| Name-space dedup (`oji udezue` / `oji_udezue`) | found by the 10-09 replay | **Shipped** | v5.103.47 (`07e9e3857`, `1ff726d96`) | Yes (card disposed 10-11: 0 GUEST flips after) |
| R5 boot/shutdown AWAY fence | CENSUS-SHUTDOWN-AWAY-FENCE-1 | **Closed** — mostly a display artefact; display fix shipped | v5.103.54 (`51d2a7ec4`) | Yes (card `verified_2026_10_12`) |
| **D4 re-run D0-REPLAY on fixed inputs + corrected truth → `..._rerun.md`** | inputs-first D4 / R2.5 | **Never run.** No `*_rerun.md` exists. Blocked on OP-1 (your 10-03 timeline answer). | — | — |
| CENSUS-GROUND-TRUTH-CSV-FIX-1 (answer key) | 10-04 memo | **Waiting on operator since 10-05** | — | — |
| R2 "make the count a stock" — **measure drift first** ("replay 2–4 weeks against empty anchors") | subsystem audit R2 | **Never run** | — | — |
| R4 census arm for GUEST ("re-measure Path A FP over 30 d first") | subsystem audit R4 | **Never started** | — | — |
| Estimator D3 shadow → D5 guests-present flag → D6 FLOOR | estimator plan | **Never started**; card approved 10-15, critique 10-18 recommends PARK | — | — |
| CENSUS-ATHOME-RESIDENT-CORROBORATOR-1 (garage vouch) | inputs-first R2.3 item 4 | **Planned, waiting on operator Q2/Q3** (plan has an unfixed room-name defect, §8) | — | — |
| CENSUS-PATIO-THROUGH-GLASS-1 | footage audit | **Waiting on operator (NVR config)**; Frigate half re-checked 10-09 still unmasked | — | — |
| R6 `ojini` face-slug hygiene | subsystem audit | Partly absorbed by v5.103.47 canonicaliser; not separately verified | — | — |
| R7 WiFi recency knob / CENSUS-GUEST-FLOOR-1 | subsystem audit, card revived 10-17 | **Never started** | — | — |
| R8 more interior cameras / D7 AI-vision door count | subsystem audit | Parked (hardware / PARKED in estimator §D7) | — | — |
| CENSUS-ACCURACY-1 leftovers (decay leg, 4 registry-bypass sites, P9) | August arc | **Pre-planning since 09-12**; decay leg now superseded | — | — |

### 1.4 Where "measure and continue" was promised, and whether it ran
1. **Inputs-first D4** — "re-run D0-REPLAY as the exit criterion" (`PLANNING_census_inputs_first.md:195-209`). Did not run. The 10-08 and 10-09 *live* replays (card `live_replay_2026_10_08`, `clean_replay_2026_10_09`) checked door inputs and GUEST flips, not the estimator gates.
2. **Inputs-first card `next`** — "Clean → estimator GO, I write the estimator plan". The discriminator came back clean (10-11) and the card was closed with "estimator GO", but the follow-on is the un-run replay again, gated on CSV-FIX.
3. **Subsystem audit R2** — "Measure first: replay 2–4 weeks … to quantify drift per day before building." Never run.
4. **Subsystem audit R4** — "Re-measure Path A's FP rate over 30 days before re-wiring." Never run.
5. **README_v5.103.39** live table — validated that rows carry `peak_person_count`; nobody measured whether the house *answer* (AWAY / guest) improved.

**Why it stalled:** each "continue" was chained behind an operator answer (OP-1 timeline) that is now two weeks old, and the 10-14 trip turned attention to the AWAY flap. The answer key for 10-03 also matters less now: the estimator is recommended for PARK, so the replay is no longer the gate for anything we would build.

---

## 2. The objective

Derived from the operator's words on the cards: "Census and guest are diff states … separate concerns" (CENSUS-ACCURACY-1, 08-16); "census has been wrong all day" (10-03); "I want HVAC to go away fast. As long as that happens, house to be more careful" (AWAY-flap card, 10-17); "make sure a) it's needed b) it solves the problem" (estimator, 10-17).

> **Objective (falsifiable):** over any 14-day window, (1) the house is never AWAY for more than 10 consecutive minutes while a person is inside a room that has a still-holding sensor or a camera, and AWAY entries with someone home are at most 1/day; (2) a genuine departure reaches house AWAY within 15 min and HVAC zone Away within its own vacancy grace (unchanged); (3) GUEST is on only when a non-resident is present (0 resident-only GUEST entries); and (4) the head-count is display-grade (no trust consumer reads a number above 1). Error rates are measured by the P0 scorecard probe (§5.3), not asserted.

Clause (1)'s "room that has a still-holding sensor or a camera" is the honest boundary: a guest in a bedroom with only a ZV motion sensor or nothing is out of reach of any proposal here.

Measured baseline against the objective (URA DB `house_state_log`, read-only, 2026-10-18; would-have audit for the trip):

| Clause | Today | Source |
|---|---|---|
| (1) AWAY entries/day | 10-04→10-13: 0–9 (median 3); trip 10-14→10-17: 33, 10, 33, 19 | `house_state_log` count by day |
| (1) AWAY minutes with a guest-room radar occupied, all phones away | 487 of 2,314 on the trip | would-have audit §0 |
| (2) departure → zone Away | median 5.1 min, p90 22.2 | would-have audit §4.1 |
| (3) GUEST entries | 25 in 11 days since 10-04, all guest-room gate; plausibly correct | critique §a |
| (3) party, GUEST never armed (10-03) | miss | subsystem audit F2 |
| (4) trust consumers of a count > 1 | none | critique §a table |

---

## 3. Prior-art scan — simple-away guard and guest-room radar veto (house-state surgery)

Re-verified on `develop` 2026-10-18. Line numbers are current.

| Piece | Verdict | Evidence (file:line) |
|---|---|---|
| Camera-body evidence per census tick | **REUSE** | `presence.py:4739-4815` `_handle_census_update` parses `unidentified_count` (`:4758`) and `face_recognized_count` (`:4765`). Not `interior_count` (carries BLE; would re-open GAP-A D8, `presence.py:1149-1158`). |
| Last-camera-body timestamp | **BUILD — one RAM field** (`_last_camera_body_ts`) | Grep `last_body|body_seen|last_nonzero` in presence/camera_census/const: 0 hits. `camera_census.py:1323` `_peak_house_timestamp` and the published `peak_held` / `peak_age_seconds` / `count_as_of` (`camera_census.py:1852-1854`, the CENSUS-ACCURACY-1 P7 work) are **peak-hold** stamps on the held total, which is clamped back to the live camera count (`camera_census.py` clamp, AWAY-flap plan §3.2), so they cannot serve. Justified: no existing stamp has "last time a camera saw an unattributed or face-recognised body" semantics. |
| Existing AWAY branches | **EXTEND (one conjunct each)** | `presence.py:1127-1131` nobody-home; `:1170-1181` path α; `:1248-1288` path β. Only automatic AWAY producers (AWAY-flap plan §3.1, R1-verified). |
| Existing AWAY guards | **REUSE, no change** | α `camera_input_degraded` skip (`:1170-1171`); β grace / indoor-clear / `sustained_external_empty` / sleep exemption (`:1215-1258`); `switch.ura_presence_coordinator_away_confirmation_veto` (kill switch, AWAY-flap plan §1.2); state-machine hysteresis (`house_state.py`); arriving re-arm cooldown. None holds AWAY on camera recency: β's `census_count == 0` uses the clamped instantaneous count. |
| `FLOOR_WINDOW_S` knob | **DO NOT REUSE — BUILD own knob** | Grep `FLOOR_WINDOW|COUNT_MEMORY` in `const.py`: 0 hits. `FLOOR_WINDOW_S` exists only in the unbuilt estimator plan (§7.10, default 1200 s). Critique §c.10: sharing it would silently re-lengthen the departure delay if the estimator lands. New rung-3 Number `CONF_PRESENCE_AWAY_QUIET_S` (name is the build plan's call; AWAY-flap Rev 2 D3 proposed `CONF_PRESENCE_COUNT_MEMORY_S`), default 600 s, 0 = off. |
| Discharge timer | **REUSE the 60 s periodic** | `presence.py:2926-2928` `async_track_time_interval(self._periodic_inference …)`, handler `:5074`. Not `_schedule_deferred_retry` (shared slot, AWAY-flap R2-02). |
| Guest-room occupancy producer | **REUSE + EXTEND** | `_discover_guest_rooms` `presence.py:5164-5230` reads `CONF_ROOM_IS_GUEST_ROOM` (`const.py:402`), resolves each guest room's `binary_sensor.<room>_occupied` by registry unique_id, keeps `_guest_room_state[room] = {first_seen, current_occupancy_known, threshold_min}`; `_guest_room_gate_armed` `:5485-5535` already does a **live known-person re-check** (`_is_known_person_in_room`). "A non-resident is in a guest room now" = `first_seen is not None and not current_occupancy_known and not _is_known_person_in_room(room)`. That is the estimator's `U_gr` without the estimator. Extension = one helper returning that bit (no threshold), consumed as a new α conjunct. |
| Still-holding sensor class in the guest rooms | **REUSE (config already correct)** | SENSOR_FLEET_CLASSES: GB1/GB2 Matter MS600 occupancy filed in `presence_sensors` (still-holder); `meross_lan` motion bit in `motion_sensors`. Room `_occupied` already fuses them. |
| Capability check "is this room radar-held" | **REUSE if needed** | `presence.py:3907` `_room_radar_sole_capable`, `sensor_capability.is_radar_capability`. Only needed if the veto should require the radar to be the holder; recommend not (see §5, piece B). |
| Nobody-home and β already respect rooms | **No change** | `:1127` `not any_zone_occupied`; `:1252` `not indoor_blocked`. So the radar veto belongs on **α only** — α is the branch that ignores rooms by design (camera ghost defence, `:1133-1139`). Adding guest rooms to α (not all rooms) keeps that defence: Kitchen LD2410/ZX phantoms (17.6 h on the trip) stay out. |
| Veto-path label | **EXTEND** | `self._veto_path` reset `:1124`, set `:1177/1180` (`active`), `:1274/1277` (`lost_admitted*`); copied `:6518`; written to the D7 episode snapshot in `_dispatch_house_state_change` `:7861-7930`. Add `body_quiet_hold`, `guest_room_hold`, and a `nobody_home` label (today nobody-home AWAY reports `none`). |
| 60 s inference loop | **REUSE** | above; INV-AWAY-DISCHARGE in AWAY-flap Rev 2 §2 stands. |

**New functionality flagged:** (a) one timestamp, (b) one Number knob, (c) one guest-room "occupied-unknown-now" helper, (d) three label strings. Nothing else. Cut from the Rev 2 plan's scope: the shared estimator knob name; the 1200 s default. Not added: a door tally, a held count, a new timer, a new persisted store, a new room-config field.

---

## 4. Observability

### 4.1 What exists today (verified)
- `sensor.ura_presence_coordinator_presence_house_state` (`sensor.py:5557-5784`): state, `previous_state`, `state_since`, `dwell_seconds`, `is_overridden`, `override` (`house_state.py:442-452`), `confidence`, `census_count`, `face_recognized_count`, `path_alpha_gate_source`, `tracked_persons_count(_trusted)`, `excluded_persons`, `all_tracked_persons_away`, `veto_path` (most recent tick only), `lost_away_grace_remaining_s`, `last_veto_decision`, arriving re-arm counters, boot-settle fields, per-zone mode/fans. Live read 10-18: `home_day`, `veto_path: none`.
- `house_state_log` DB table: `state, confidence, trigger, previous_state` — trigger is the event (`census_update`, `periodic`, `deferred_retry`), **not the branch**.
- D7 memory episode `house_state_transition` (`presence.py:7905-7930`) snapshots `veto_path`, counts and `excluded_persons` per transition; `away_transition_blocked` episodes for blocks.
- `transition_count_daily` anomaly metric (`presence.py:1416-1420`, `_count_transition` `:7450-7490`) — z-score trip-wire on ALL transitions per day; not exposed as an entity, not AWAY-specific.
- v8 dashboard (`ura-v8`, read via ha-mcp 10-18): house state shown as text in the greeting and the Presence summary (state + confidence), a zones-mode card, and the override select tile. **No card reads `veto_path`** (search: 0 matches), nor `excluded_persons`, nor any AWAY reason.

### 4.2 Gaps
| # | Gap | Why it matters | Cheapest fix |
|---|---|---|---|
| O1 | Nobody-home AWAY is labelled `none`; there is no persisted "which branch made the house AWAY" | You cannot tell α vs β vs nobody-home without a DB replay (C3 in the Rev 2 plan needed one) | Label `nobody_home`; copy `veto_path` into the D7 snapshot (already there) and into the `trigger` string or a new attr `last_away_reason` |
| O2 | No "AWAY is being held" visibility | A guard that holds silently looks like a stuck HOME | Attrs `away_hold` (`none`/`body_quiet`/`guest_room`), `last_camera_body_at`, `away_eligible_at` |
| O3 | No AWAY-entries-today count | The flap was found by hand-querying the DB | Attr `away_entries_today` (reuse `_count_transition` path and the `count_house_state_changes_since` hydration, `presence.py:2575-2590`) |
| O4 | `veto_path` is last-tick, not last-AWAY | Reading it after the fact shows `none` | `last_away_reason` + `last_away_at` sticky attrs |
| O5 | v8 has no "why" card | Operator asked for it | One markdown card on the v8 presence section reading O1–O4 (dashboard edit, no code) |
| O6 | No regression trip-wire specific to AWAY flapping | No-soak rule: trip-wires belong in code | Optional: an `away_entries_daily` anomaly metric beside `transition_count_daily`. **Recommend not yet** — the existing transition metric already fires on thrashy days; revisit if it misses the next flap. |

O1–O4 are attributes on an existing sensor (no new entity), O5 is dashboard config. Fold into the guard cycle; they are its acceptance instruments.

---

## 5. The cobbled arc

### 5.1 Pieces

| # | Piece | What it solves | Contribution to objective | Depends on | Tier | Cost / risk | Verdict |
|---|---|---|---|---|---|---|---|
| A | **Simple-away guard** (camera-body recency, W = 600 s, nobody-home/α/β, house-side; HVAC unchanged as today it already rides zone vacancy for 69% of zone-episodes) | Short AWAY flaps when an untracked person walks out of camera view | (1): absorbs 31/65 trip and 116/193 baseline AWAY entries; ~150 of 2,314 trip AWAY min. (2): departures delayed median 9.5 min (max 14.6) — inside the 15-min target | none | **3** (state machine × time) | ~1 field + 1 knob + 3 conjuncts; risk = a missed branch or a stuck hold; mitigated by kill switch W = 0 and the periodic discharge | **BUILD** |
| B | **Guest-room AWAY veto on α** (non-resident occupying a `CONF_ROOM_IS_GUEST_ROOM` room blocks α) | Guest still in a bedroom while all phones are away | (1): targets the 487 GB2-occupied trip AWAY min, of which ~344 the guard cannot touch | P1 fan-phantom probe | **3** (same cycle as A) | One helper + one conjunct; risk = a phantom-held guest room blocks AWAY indefinitely → mitigate by fan check and an absolute cap (knob) | **BUILD, gated on P1** |
| C | **Observability O1–O5** | You cannot see why the house is AWAY | Instrument for all four clauses; makes A/B acceptance readable live | A, B | rides A (attrs) / config (O5) | Display only | **FOLD into A** |
| D | Estimator T (door tally), FLOOR into `total_persons`, empty anchor | Party head-count | (4) display only; (1) negative risk (stuck-high FLOOR blocks real AWAY); door attach 29–31% makes T count residents | CSV-FIX, re-run replay | 3 | 37 read sites, new persisted state, 8 config fields | **PARK** (critique triggers) |
| E | Estimator D5 guests-present flag (orthogonal to house state) | SLEEP-with-guest; guest as a bit not a state | (3) design value, no measured miss today | none | 3 | 16 GUEST readers | **PARK** — revive if you want SLEEP + guest behaviour |
| F | Inputs-first D4 replay re-run + CENSUS-GROUND-TRUTH-CSV-FIX-1 | Score the estimator | Only gates D, which is parked | your 10-03 answer | 1 (probe) | Your time | **PARK with D** (close CSV-FIX as waiting-on-trigger) |
| G | **P0 objective scorecard probe** (replaces F as the "measure and continue") | Nobody measures the goal | Defines the error rates in §2 and re-runs 14 days after A/B ship | none | probe | ~1 h read-only | **BUILD (probe, first)** |
| H | CENSUS-PATIO-THROUGH-GLASS-1 (mask patio in Frigate2 + Protect) | Patio guests counted inside | Small: inflates `unidentified` → holds A falsely during patio parties (benign direction) and the display count | operator NVR action | config | Zero code | **DO (config, operator)** |
| I | CENSUS-ATHOME-RESIDENT-CORROBORATOR-1 (garage vouch) | Unnamed resident garage crossings | Feeds only the door tally (parked) and the four display sensors | plan defect fix | 2 | Medium; vouch mis-rate 28–40% | **PARK** with D (trigger: estimator revived) |
| J | CENSUS-GUEST-FLOOR-1 (guest-WiFi devices) | Guests invisible to cameras | (3) potential guest-present corroborator; saw 5 at the party | E or a display need | 2 | Privacy + lifetime design | **PARK** — keep display-only; must not feed AWAY/GUEST without its own FP rate |
| K | CENSUS-ACCURACY-1 leftovers | Decay leg superseded by A; 4 registry-bypass sites; P9 latent | ~0 to objective | — | 1 | Low | **FOLD/SHRINK**: drop decay leg; verify the 4 sites still exist (v5.103.39 fixed the face resolver, some may be gone) as a Tier-1 card; P9 stays latent per GUEST-FP-RESIDUALS-1 trigger |
| L | `CONF_MAIN_ENTRY_DOOR` (shipped, no consumer) and `peak_person_count` (shipped, read only by the replay script) | — | none | — | — | — | **KEEP + DOCUMENT** (option text: "used by a future estimator"); do not delete |
| M | Party GUEST arming (10-03 miss) | Guest mode off during a 12-person party | (3) a real miss, ~rare | — | — | — | **Config-first:** house-state override select `select.ura_presence_coordinator_house_state_override` = guest for planned gatherings; no code. Revive E if this becomes frequent |
| N | EGRESS-INTERIOR-COUNT-REINFORCE-1 | Door flow into count | Folded into D | D | — | — | **PARK** with D |
| O | HVAC riding the guard | Comfort hits on occupied zones | Removes ≤364 of 1,571 trip comfort-minutes, gives up ~556 saving-minutes | — | 3 | Breaks "HVAC fast" | **DROP** per your instruction; the lever for camera-less rooms is HVAC occupancy rules, a separate card if wanted |

### 5.2 Does the recommended set (A + B + C, G, H, M) achieve the objective?

- **Clause (1):** A takes the short flaps; B takes the guest-bedroom case. On the trip data, A alone leaves 1,785 → (at W = 10) 2,018 AWAY minutes with all phones away; B is the only thing in the set that touches the ~344 camera-blind GB2 minutes. Projected residual after A + B: the 983 "no sensor evidence" minutes (cannot tell empty from silent), the 467 minutes where only weaker rooms (Kitchen radars, ZV) were occupied, and the 3 × ~220-min episodes **unless** GB occupancy was the holder (GB2 was occupied 70 min of one). Whether clause (1)'s "≤ 1/day with someone home" is met is **not known** — P0 + the B replay answer it. Honest expectation: met on normal days (baseline median 3/day, most absorbed by A), likely not met for a guest who spends the day in a non-guest room.
- **Clause (2):** met — W = 10 adds ≤ 14.6 min; HVAC untouched.
- **Clause (3):** met today for resident-only false positives (0 since v5.103.47); party arming relies on the override (config). Residual: unplanned gatherings in common areas.
- **Clause (4):** met by construction (no count consumer added).

**Residual error, named:** phoneless person in a camera-less non-guest room; unplanned party guest mode; head-count under-reads at parties (display only).

### 5.3 Missing numbers and the one-shot probe for each
| Number | Probe (read-only, `ssh ha`, URA DB + recorder) |
|---|---|
| Objective scorecard (AWAY entries/day with someone home, AWAY min with a still-holder or camera occupied, departure→AWAY delay, resident-only GUEST entries) — 30-day baseline | **P0**: join `house_state_log` AWAY intervals with `census_snapshots`, `occupancy_events` for rooms with a presence-class sensor, `person.*` recorder, `person_entry_exit_events`. Re-run 14 days post-ship = the "measure and continue" |
| GB1/GB2 phantom rate (does the MS600 hold "occupied" with the room empty or a fan on?) | **P1**: GB1/GB2 `_occupied` minutes during windows with all `person.*` not_home and no guest staying (operator-named dates), split by fan on/off |
| B's simulated contribution | **P2**: re-run the would-have simulation with "α blocked while a guest room is occupied-unknown" at W = 10 |
| Max legitimate guest-room hold (for B's absolute cap) | inside P1: longest continuous GB occupied run with a confirmed guest |

---

## 6. Recommended sequence and operator decisions

**Sequence**
1. **P0, P1, P2 probes** (read-only, one ura-prober run). Gate: P1 phantom rate low enough that B's veto would not hold the house home on an empty day more than ~1/week.
2. **Config now:** H (patio masks, you); M (use the override select for planned gatherings).
3. **Plan Rev 3** of `PLANNING_house_away_flap_untracked_occupant.md`: own knob default 600 s, add B as D5 (α only, guest rooms only, with a cap), add C as D6, keep HVAC on today's path. Two Tier-3 plan reviews.
4. **Build A + B + C as one Tier-3 cycle**: four framing-disjoint reviews, operator checkpoint before deploy.
5. **Board hygiene:** CENSUS-OCCUPANCY-ESTIMATOR-1, CENSUS-GROUND-TRUTH-CSV-FIX-1, CENSUS-ATHOME-RESIDENT-CORROBORATOR-1, EGRESS-INTERIOR-COUNT-REINFORCE-1 → parked with the critique's triggers; CENSUS-ACCURACY-1 shrunk to the registry-site verify; CENSUS-GUEST-FLOOR-1 parked display-only.
6. **14 days after deploy:** re-run P0 and write the result back (cycle closes on it; no soak).

**Decisions (PICK, default in bold)**
1. **Estimator:** **park with triggers** / keep blocked on the CSV answer.
2. **Guard window W:** **600 s** / 900 s / 1200 s (would-have audit: 600 s gets 31 of 34 absorptions at half the delay).
3. **Guest-room veto scope:** **α only, guest-flagged rooms only, after P1** / all rooms with a ZK/ZX/MS600 radar (adds Kitchen phantoms) / none.
4. **Guest-room veto cap:** **hold at most N h then let AWAY through (N a rung-3 knob, default set from P1)** / no cap.
5. **Party guest mode:** **override select by hand for planned gatherings** / revive the guests-present flag (E) now.

Also yours, independent of the arc: answer CENSUS-GROUND-TRUTH-CSV-FIX-1 only if you want the estimator kept warm; otherwise the default above closes it.
