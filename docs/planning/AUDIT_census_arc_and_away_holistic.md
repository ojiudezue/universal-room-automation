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

---

## Probe results 2026-10-18

**Run:** Sun 2026-10-18 07:24-07:35 CDT (`date` at commit: 07:30) by ura-prober. Read-only. Sources: URA DB (`house_state_log`, `census_snapshots` zone=house, `occupancy_events`, `person_entry_exit_events`, `memory_episodes`) and the HA recorder (`home-assistant_v2.db`, read over `ssh ha`, `mode=ro`), plus `.storage/core.config_entries` for room config. Scripts and raw extracts (not in repo): `.../scratchpad/p/` (`lib.py`, `p0*.py`, `p1*.py`, `p2.py`). All times CDT unless marked Z.

### 0. Answer first

1. **The recommended set (A at W = 10 min + B + C, G, H, M) does NOT meet the objective as written in section 2.** Clause (3) is met, clause (1) is met on ordinary days but not on days when only Jaya and the guest were home, and **clause (2) is not met at W = 10** (see 2). The earlier claim in section 5.2 that clause (2) is "met" is wrong; it measured the added delay, not exit crossing to house AWAY.
2. **P2:** B contributes real value on the trip window: 8 more entries absorbed (31 to 39 of 65), AWAY minutes with a guest bedroom occupied fall 315 to 40 (A alone removes only 70 of 385). B delays no strict genuine departure (0 of 10).
3. **P1 gate passes:** zero guest-bedroom occupancy in 6 guest-free long-away windows (2,781 min); fan-on explains at most 24 of 336 occupied minutes in all-phones-away windows. Recommended B cap: 8 h.
4. The window **W is the lever**: W = 5 keeps clause (2) at 6 of 9 departures within 15 min and clause (1) at 0.90 someone-home entries/day on ordinary days; W = 10 breaks clause (2).

### 1. P0: objective scorecard

**Windows.** 30 days 2026-09-18 12:30Z to 2026-10-18 12:30Z (07:30 CDT). Split at 10-14 00:00 CDT (operator left the morning of 10-14; Jaya plus a guest home). "Ordinary" = 09-18 to 10-13 (25.7 d). "Jaya+guest" = 10-14 to 10-18 (4.3 d). Recorder phone state only exists from 2026-10-11 04:16 CDT (7.2 d); every phone-dependent figure is limited to that.

**Definitions (all proxies; there is no ground truth for who was home).** "Someone home" for an AWAY entry at time T = a still-holder or camera room occupied at T, OR a sustained (3 min or more) occupied or camera-body period between T+10 min and exit-3 min, OR (recorder window only) a `person.*` home at T. Still-holder/camera rooms: the 12 rooms with `presence_sensors` plus Upstairs Hallway, Living Room, Study A cameras, **excluding Kitchen** (fan phantoms). Camera body = `census_snapshots` house `unidentified_count > 0`. Room occupied = URA `occupancy_events` entry/exit pairs, which include the 300 s hold tail, so this over-states presence.

| Clause | Measure | Today | A (W=10) | A + B (W=10) |
|---|---|---|---|---|
| (1) ordinary days | AWAY entries/day | 2.9 (75; busiest day 13) | 1.1 (27) | 1.0 (25) |
| (1) ordinary days | entries with someone home, per day | 2.53 (65; 15 of 26 days have more than 1) | 0.70 (18; 4 days over 1) | **0.58 (15; 2 days over 1, busiest 5 on 09-28)** |
| (1) Jaya+guest days | AWAY entries/day | 22.3 (96; busiest day 42) | 11.8 (51) | 10.0 (43) |
| (1) Jaya+guest days | entries with someone home, per day | 16.2 (70) | 8.6 (37) | **6.5 (28)** |
| (1) whole 30 d | AWAY episodes where a still-holder/camera room is occupied 3+ min after the first 10 AWAY min | 37 episodes, 1,705 evidence-min | 28, 1,457 | **21, 1,220** |
| (1) kitchen counted | same, Kitchen included | 45 / 2,019 | 32 / 1,735 | 25 / 1,499 |

Residual after A + B on ordinary days (15 entries): Exercise Room (radar) 18 hits, Study A 9, Jaya Bedroom 9, Master Bathroom 7, Master Bedroom 6, Ziri Bedroom 5, Study B 5, Living Room 4. These are residents or visitors in rooms that are not guest rooms; B does not touch them (decision 3 option "all radar rooms" would). On Jaya+guest days the residual is Jaya Bedroom 6, Living Room 4, Exercise 1, Study B 1, GB2 1.

| Clause | Measure | Today | A + B (W=10) |
|---|---|---|---|
| (2) | exit crossing to house AWAY, strict genuine departures (6 in window) | 8.7, 8.9, 9.6, 12.1, 16.0, 24.6 min; 4 of 6 within 15 min | 17.2, 17.7, 18.5, 21.6, 25.5, 34.1 min; **0 of 6 within 15 min** |
| (2) | loose: any exit crossing then AWAY 30+ min within 30 min (10 in window) | median 8.9, p90 24.6, 8 of 10 within 15 min | median 18.5, p90 34.1, 1 of 9 within 15 min (1 absorbed) |
| (3) | GUEST entries (37, `house_state_log` state=guest, previous not guest) with no non-resident evidence | proxy: unidentified census body within 10 min, OR guest room occupied, OR trigger `guest_room_occupancy` | **0 of 37 unsupported** (7 are the guest-room gate itself). Weak proxy: an unidentified body could be an unrecognised resident. |
| (4) | trust consumers of a count above 1 | not a DB question; unchanged (critique section a) | met by construction |

**Sensitivity of clause (2) to W (30 d loose set):** W = 0 median 8.9, 8 of 10 within 15 min; W = 3 median 11.5, 7 of 9; W = 5 median 13.5, 6 of 9; W = 6 median 14.5, 6 of 9; W = 8 median 16.5, 2 of 9; W = 10 median 18.5, 1 of 9. Companion on ordinary days, entries with someone home per day (A + B): W = 3 0.97; W = 5 0.90; W = 6 0.78; W = 8 0.62; W = 10 0.58.

**Why the earlier audit read clause (2) as met:** the would-have audit measured the delay added after the AWAY decision (9.5 min at W = 10). Today's exit-to-AWAY latency is already about 9 min median (zone grace plus census/BLE), so the added delay pushes the total past 15 min.

### 2. P1: guest-room fan phantom and guest-free control

**Config verified** (`core.config_entries`): `room_is_guest_room: true` only for GB1 and GB2. GB2 presence sensor = Matter MS600 `binary_sensor.mmwave_motion_lux_matter_wifi_guestbedroom2_occupancy`, motion = Meross + Hobeian; fan = `fan.fan_switch_4`. GB1 presence = MS600 `..._guestbedroom1_occupancy`, fan = `fan.guest_room_down_ceiling_fan_2`.

**Fan split (recorder window 10-11 04:16 to 10-18 07:30 CDT, 7.2 d; fan history exists nowhere else).**
- GB2: fan on 63 min of 10,273; occupied 967 min. Occupied 61.7% of fan-on minutes vs 9.1% of fan-off minutes. This is confounded (URA turns the fan on because someone is there), so it is not a phantom measure.
- GB1: fan never on in window; occupied 841 min, all fan-off.
- **Inside all-four-phones-not-home windows (3,458 min, three of which are the trip):** GB2 occupied 336 min, of which only **24 min with the fan on** and 311 with it off; GB1 occupied 58 min, 0 with fan on. A fan-induced phantom can therefore explain at most about 7% of the occupied minutes.
- Independent corroboration: in those windows the Matter radar was on 255 min and **0 min of it was uncorroborated** by the Meross or Hobeian GB2 sensor within 5 min (whole recorder window: radar on 583 min, 0 uncorroborated). Caveat: all three are fan-susceptible motion/radar class; this rules out a lone-radar phantom, not a fan wafting two sensors at once.

**Guest-free control (no ground-truth dates exist: no operator-named guest-free dates were found in the board or memory, and the recorder's all-away windows before 10-14 are only 44, 58 and 675 min).** Control = pre-trip AWAY episode of 120+ min with no GUEST state from 6 h before the start through the end: 6 episodes (08-16 11:11, 09-04 18:15, 09-13 09:39, 09-19 11:29, 09-22 12:02, 09-26 10:04), 2,781 min total, **GB1/GB2 occupied 0 min**. Selection note: GB occupancy was not used to choose them.

**False-hold exposure** (AWAY entries, 08-16 to 10-14, 193 entries) where GB1/GB2 was occupied at the entry instant: 36, of which 28 had a GUEST state within 3 h (genuine guests). The other **8 entries (5 distinct occupied runs: 09-16 overnight 922 min, 09-19 6 min, 09-20 5 min, 10-08 75 min, 10-08 47 min) in 59.5 days = about 0.6 per week**. Whether those 5 were unlabelled guests or phantom is **unknown**; the 922-min overnight run looks like a sleeper. This is an upper bound on false holds and sits under the doc's gate of about 1 per week.

**Dates the phones were all away in the pre-trip recorder window:** 10-12 19:32 (44 min, GB 0), 10-13 07:10 (58 min, **GB occupied 50**, no GUEST state checked as guest-free: unknown), 10-14 07:33 to 18:48 (675 min, GB 0). The 10-13 07:10 window is the only candidate phantom in the data; one sample.

**Max legitimate hold (for B's cap).** GB1|GB2 occupied runs since 08-16: 658; those overlapping a GUEST state: 115, p50 70 min, p90 371, max 762; 24 are 240+ min, 5 are 480+. Runs with no GUEST state within 1 h: 433, p50 8, p90 29, max 922 (the overnight one). Remaining occupied time at the 59 AWAY entries that landed inside a GB run: p50 33 min, p90 301, max 509; 9 exceed 240 min, 14 exceed 120 min. **Suggested cap default: 8 h** (covers every observed remaining hold; a 4 h cap gives up 1 to 4 baseline absorptions, a 2 h cap gives up 3 trip absorptions).

**P1 verdict:** gate passes. B would not have held an empty house on any guest-free control episode, and the fan cannot account for most occupied minutes. Residual unknown: 8 unlabelled entries and one 50-min candidate.

### 3. P2: simulated contribution of the veto

**Method.** Replay every real AWAY entry (258 since 08-16: 65 trip from 10-14 17:27, 193 earlier) with the same open-loop rule as the would-have audit (a hold pushes the entry time to hold-end + 30 s; absorbed if that reaches the real exit). A = camera-body hold, W = 10 min. B = hold while GB1 or GB2 is occupied. **Branch logic justified from code:** when a guest room is occupied the nobody-home branch (`presence.py:1127`, needs `not any_zone_occupied`) and path β (`:1252`, needs `not indoor_blocked`) cannot fire, so any AWAY at that moment is path α, which is exactly what B blocks. Reproduction check: A at W = 10 gives 31 of 65 trip, 116 of 193 baseline absorbed and median delay 9.5 min, matching the earlier audit.

"AWAY min" = AWAY minutes inside the recorder all-four-away windows from 10-14 (2,682 min of windows; the audit used 2,765, so the "today" total is 2,280 here vs 2,314 there). "GB occ" = of those, minutes with GB1 or GB2 occupied (bedrooms only; the audit's 487 also counted the GB2 bathroom, closet and hallway).

Camera body = `total_persons > 0` (audit definition):

| Variant | Trip absorbed (of 65) | AWAY min in all-away windows | of which GB occupied | Baseline absorbed (of 193) | Strict genuine delayed (10 episodes) |
|---|---|---|---|---|---|
| Today | 0 | 2,280 | 385 | 0 | 0 |
| A (W=10) | 31 | 1,986 | 315 | 116 | median 9.5, max 10.2 min |
| B only, no cap | 16 | 1,933 | 42 | 28 | 0 |
| A + B, no cap | **39** | **1,711** | **40** | 124 | median 9.5, max 10.2 |
| A + B, cap 8 h | 39 | 1,711 | 40 | 123 | same |
| A + B, cap 4 h | 39 | 1,711 | 40 | 123 | same |
| A + B, cap 2 h | 36 | 1,769 | 98 | 118 | same |
| A + B, cap 1 h | 36 | 1,774 | 103 | 118 | same |

B's own contribution on top of A: +8 trip entries absorbed, -275 AWAY min, and GB-occupied AWAY minutes drop from 315 to 40 (the remaining 40 are minutes where a guest room became occupied after AWAY was already declared; a veto on entry cannot touch those). B delays none of the 10 strict genuine departures (they all have zero GB occupancy).

**Predicate sensitivity (new finding).** `census_snapshots.total_persons` includes identified (BLE/face) people, which inflate "body" while someone is home. With the plan's real predicate proxy `unidentified_count > 0` only: A absorbs **27 of 65 trip and 36 of 193 baseline** (not 116), and A + B absorbs 37 of 65 trip and 61 of 193 baseline. The `face_recognized_count` half of the plan's predicate is not stored in `census_snapshots`, so the true figure lies between the two; the baseline absorption figure of 70% in the would-have audit is an upper bound and about 19% is the lower bound. The trip figure is stable (27 to 31) because all four phones were away there.

### 4. Does the recommended set meet the goal target?

| Clause | Target (section 2) | After A (W=10) + B | Met? |
|---|---|---|---|
| (1) at most 1 AWAY/day with someone home, no AWAY over 10 min with a person in a still-holder/camera room | | 0.58/d ordinary days (2 days over 1); 6.5/d on Jaya+guest days; 21 episodes still carry 3+ min of occupied still-holder room after the first 10 AWAY min | **Partly**: mean met on ordinary days, not met on Jaya+guest days, second half not met (21 episodes) |
| (2) genuine departure to AWAY within 15 min | | median 18.5 min, 0 of 6 strict within 15 | **Not met at W=10**; closer at W = 5 (6 of 9) |
| (3) GUEST only with a non-resident, 0 resident-only entries | | 0 of 37 unsupported (proxy) | Met |
| (4) no trust consumer of a count above 1 | | unchanged | Met by construction |

Honest reading: the set removes most flap churn and nearly all guest-bedroom AWAY holds, but with W = 10 it trades clause (2) for clause (1). The remaining clause (1) shortfall is people in non-guest rooms with phones away (Exercise Room, Jaya Bedroom, Study A, Master Bathroom), which neither A nor B reaches.

### 5. What this changes in the plan (for the planner, not decided here)

- Decision 2 default (W = 600 s) should be re-opened: W = 5 min (300 s) gives 0.90/day on ordinary days and 6 of 9 within 15 min; W = 10 gives 0.58/day and 1 of 9. Either relax clause (2) to "within 15 min of the last camera body" or pick W near 5.
- Decision 4 default stands: cap 8 h.
- Decision 3: "α only, guest-flagged rooms" is supported by P1/P2. The "all radar rooms" option would add Exercise Room and Jaya/Ziri/Master Bedrooms, which dominate the residual, but this probe did not test their phantom rate (only the two guest rooms were probed).
- Add `face_recognized_count` to the snapshot or the stamp store before relying on baseline absorption numbers.

### 6. Caveats

- No ground truth for occupancy; every "someone home" figure is a sensor proxy with hold tails. Kitchen excluded as phantom-prone; including it adds 8 flagged episodes (section 1).
- DB room occupancy vs recorder entity: GB2 1,062 min (DB) vs 967 min (recorder entity) over the recorder window; GB1 identical (841). The DB figure is used for the 30-day work.
- 10-14 (31 AWAY entries that day) is classed "Jaya+guest" here; the earlier audit started its trip window at 17:27.
- Recorder `person.*` for Ziri has a single record (not_home from 10-11 18:11), so pre-18:11 "all away" cannot be asserted for 10-11; this does not affect any window used above.
- Open-loop replay: real exit times held fixed; state-machine hysteresis (up to 120 s) not added; B's `first_seen` / known-person live re-check (`presence.py:5485-5535`) not modelled because all phones are away in every AWAY-eligible moment.
- Not run: P0 resident-only GUEST check against the answer key (none exists); the 14-day post-ship re-run is the real test.

---

## Probe P3 2026-10-18 — still-holder radar rooms

**Run:** Sun 2026-10-18 09:51-10:00 CDT by ura-prober. Read-only. Question: extend veto B from the guest bedrooms to every room whose occupancy comes from a still-holding presence radar (ZK/ZX), alongside guard A at W = 5 and W = 10 min. Read first: `SENSOR_FLEET_CLASSES.md` (ZK/ZX hold a still person, ZV is motion-class) and the P0 to P2 section above. Same windows and method as P0/P2: 30 d to 2026-10-18 07:30 CDT, ordinary days 09-18 to 10-13, Jaya+guest days from 10-14; recorder window 10-11 04:16 to 10-18 07:30 (7.2 d); A = camera-body hold using `census_snapshots.total_persons > 0`; hold rule and open-loop replay identical to P2 (`sim()`), generalised to hold on any room in a set. The P0 `why()`/someone-home proxy is reused unchanged (Kitchen excluded from the proxy). Scripts and extracts (not in repo): `.../scratchpad/p3/` (`common.py`, `a1.py` to `a14.py`, `sim.py`, `rec3.json`); they import `.../scratchpad/p/lib.py` from P0 to P2.

### 0. Answer first

1. **Do not extend B to all radar rooms.** It cuts ordinary-day someone-home AWAY entries to 0.12 to 0.27 per day, but it holds the house home across genuine departures: with all seven ZK/ZX-bearing rooms, 3 of 10 genuine departures never reach AWAY at all, and only 1 of 10 reaches AWAY within 15 min (today 7 of 10). Most of that is Study A, which is a phantom (below).
2. **Classification by capability** (registry device models + `core.config_entries`, never entity names): 7 ZK/ZX-bearing rooms (Study A, Living Room, Master Bedroom, Kitchen, Ziri, Jaya, Exercise Room) plus Study B (LD2410 only) and Media (MS600). Of those, only **Jaya Bedroom** earns inclusion. Study A fails the guest-free control (occupied 696 of 2,781 min). Kitchen is the known fan phantom. Exercise Room's ZK radar was never on in 7.2 d, so it is not a still-holder in practice. Ziri's gain comes from one 26.5 h occupancy run. Living Room, Master Bedroom, Study B and Media each swallow a verified-empty absence for little gain.
3. **Recommendation: A at W = 3 min (180 s), B on GB1, GB2 (cap 8 h) and Jaya Bedroom (cap 16 h).** At W = 3 the departure count within 15 min is unchanged from today (7 of 10, 4 of 6 strict); W = 5 loses one, W = 10 loses all.
4. **The goal target is not met, and cannot be shown to be met.** (a) Someone-home AWAY entries on ordinary days: 0.90 per day with the recommended set if A's body predicate is `total_persons > 0` (upper-bound benefit), but **1.71 per day** with `unidentified_count > 0` only (the plan's real predicate, lower bound); the true figure lies between and the face half of the predicate is not stored. 4 of 26 ordinary days exceed 1 even at the favourable end. On Jaya+guest days it is 5.3 to 5.8 per day. (b) Departures within 15 min: 7 of 10 (4 of 6 strict) at W = 3, identical to today, so the target was already unmet before any change; no W fixes it because the existing zone grace plus census latency is about 9 min median.

### 1. Rooms classified by capability

Radar = a `presence_sensors` entry whose registry device is a radar (ZK `ZG-204ZK`, ZX `ZG-204ZX`, ESPHome LD2410 on an `esp32-c3` board, Screek `Human_Presence_Sensor`, Inovelli VZM32-SN mmWave, Meross MS600 16897). No room has a `sensor_capabilities` override except Game Room (`pir`). Excluded by capability: Master Bathroom (Intecular InvisOutlet, on the 2026-10-11 do-not-use list), Game Room (ZV motion, override `pir`; its URA trigger label says `mmwave` but the class is motion), all ZV rooms. The "occupied" signal used below is the room's `binary_sensor.<room>_occupied` (recorder) or `occupancy_events` (DB).

| Room | Radar entities (family) | Other room sensors | Occupancy trigger mix, 30 d (entries) |
|---|---|---|---|
| Study A | `mmwave_zigbee_studya_presence` (ZK) | `athom_..._mmwave_sensor`: **unavailable in all 15 recorder rows, dead** | mmwave 280 |
| Living Room | `screek_..._2412s_presence` (Screek), `mmwave_lux_temp_hum_zigbee_livingroom_presence` (ZX) | ZV motion | mmwave 489, motion 78 |
| Master Bedroom | `screek_..._b38b24_presence` (Screek), `..._masterbedroom_presence` (ZX), `switch_mmwave_inovelli_occupancy` | 2 bed sensors | mmwave 226, occupancy_sensor 11 |
| Kitchen | `mmwave_lux_wifi_esphome_kitchen_presence` (LD2410), `..._zigbee_kitchen_presence` (ZX) | Protect BLU motion | mmwave 896, motion 184 |
| Ziri Bedroom | `ziri_3_presence` (LD2410), `..._ziribedroom_presence` (ZK) | `ziri_3_moving_target` | mmwave 63, motion 6 |
| Jaya Bedroom | `jaya_3_presence` (LD2410), `..._jayabedroom_presence` (ZK) | none | mmwave 188 |
| Exercise Room | `mmwave_zigbee_gameroom_presence` (ZK), **never on in 7.2 d (23 off rows)** | 2 ZV/PIR motion | **motion 31, mmwave 2** |
| Study B | `mmwave_lux_wifi_esphome_studyb_presence` (LD2410) | none | mmwave 92 |
| Media | `..._matter_wifi_mediaroom_occupancy` (MS600) | Meross motion bit | mmwave 36, motion 25 |
| GB1 / GB2 (already in B) | MS600 Matter occupancy | Hobeian + Meross | see P1 |

### 2. Per-room phantom and corroboration

**Fan-phantom (recorder, all four phones not home: 3,458 min, of which 3,357 are the Jaya+guest trip and 101 are two pre-trip windows).** Format: room occupied min / with a room fan on / with the zone HVAC air handler cooling or heating / either. HVAC fan on = zone `climate` `hvac_action` in cooling or heating (fan_mode is `auto` throughout). Caveat that decides how to read this: Jaya and a guest were physically home on the trip, so occupied minutes there are not phantom; only the 101 pre-trip minutes and the guest-free controls (below) are clean. Also confounded: URA turns room fans on when the room is occupied.

| Room | Occupied / fan / HVAC / either | Of which pre-trip (clean) | Radar-entity-on in same windows |
|---|---|---|---|
| Study A | 1 / 1 / 1 / 1 | 1 / 1 / 1 / 1 | 0 |
| Living Room | 94 / 8 / 0 / 8 | 8 / 8 / 0 / 8 | 34 / 3 / 0 / 3 |
| Master Bedroom | 0 | 0 | 0 |
| Kitchen | **778 / 26 / 121 / 123** | 22 / 1 / 3 / 4 | 190 / 4 / 34 / 34 |
| Ziri Bedroom | 0 | 0 | 0 |
| Jaya Bedroom | 507 / 507 / 171 / 507 (all on the trip) | 0 | 478 / 478 / 188 / 478 |
| Exercise Room | 6 / 0 / 1 / 1 | 0 | 0 |
| Study B | 17 / 0 / 12 / 12 | 0 | 2 / 0 / 1 / 1 |
| Media | 0 | 0 | 0 |
| GB1 / GB2 (P1) | 59 / 0 / 3 / 3 ; 336 / 24 / 2 / 26 | 47 ; 8 | 36 ; 255 |

Only Kitchen has a material fan or HVAC share (16% of its all-away occupied minutes). The Jaya figure reads 100% fan-on because her fan is occupancy-driven and she was home; the recorder cannot separate that from a phantom.

**Corroboration** (a different sensor in the same room on within 5 min of the radar being on; sibling radars on different devices count as second sensors; recorder window 7.2 d). Minutes the radar was on / minutes with no second sensor within 5 min; in brackets the same inside all-phones-away windows.

| Room | Result |
|---|---|
| Study A | **n/a: only one live sensor** (Athom dead) |
| Living Room | Screek 948 / 641 (34 / 34 in away windows, all uncorroborated); ZX 108 / 0 |
| Master Bedroom | Screek 911 / 1; ZX 1,347 / 31; Inovelli 1,210 / 204 (0 in away windows) |
| Kitchen | LD2410 411 / 153 (71 / 58); ZX 970 / 188 (132 / 72) |
| Ziri Bedroom | n/a: only one live sensor (LD2410 on 14 min in 7.2 d) |
| Jaya Bedroom | LD2410 4,172 / 2,398 (**478 / 478**); ZK 751 / 108 (0 in away windows). The LD2410 held 478 trip minutes while the ZK saw nothing. Phantom or Jaya in bed: unknown |
| Exercise Room | ZK never on: no data |
| Study B | n/a: only sensor |
| Media | MS600 110 / 0 |
| GB1, GB2 | 464 / 0 and 583 / 0 (P1) |

**Guest-free, all-away control windows (expected 0).** Control C1 = the six P1 episodes (AWAY 120 min or more, no GUEST state from 6 h before the start through the end; 2,781 min). Control C2 = AWAY 45 min or more, no GUEST, exit crossing at the start and entry crossing at the end (5 episodes, 1,038 min). Occupied minutes from `occupancy_events` (include the 300 s hold tail); no phone data exists before 10-11, so "all away" here is AWAY state plus crossings.

| Room | C1 occupied min (episodes occupied at AWAY entry) | C2 occupied min |
|---|---|---|
| **Study A** | **696 (3 of 6)** | **678 (3 of 5)** |
| Master Bedroom | 47 (1) | 122 (1) |
| Living Room | 5 (0) | 26 (1) |
| Kitchen | 0 | 30 (1) |
| Jaya Bedroom | 0 | 9 (0) |
| GB1 | 0 | 50 (0) |
| Ziri, Study B, Media, Exercise, GB2 | 0 | 0 |

Study A is the clear phantom: on 09-13 (residents oji, jaya, ezinne logged exiting 09:29 to 09:30) and on 09-22 (ezinne exit 11:52, jaya entry 19:17) Study A was "occupied" by the `mmwave` source for the entire 223 and 436 min absence. Its only live sensor is the ZK, so corroboration cannot catch it. Master Bedroom 09-04 (44 min inside a 255 min absence) and the C2 GB1 50 min are unexplained.

### 3. Simulation

**Reproduction check:** A at W = 10 gives 27 AWAY entries, 18 someone-home on ordinary days (0.70 per day) and 51 / 37 on trip days, matching the P0 table; strict departures 17.7, 17.2, 18.5, 21.6, 25.5, 34.1 min matches P0.

Columns: AWAY and someone-home (SH) entries per day on ordinary days (25.7 d) and Jaya+guest days (4.3 d); "d>1" = ordinary days with more than one SH entry; departures within 15 min of the exit crossing (strict 6 / loose 10 / all genuine since 08-16, 10); "absorbed" = the genuine absence never reaches AWAY; VE = of 14 verified-empty absences (strict genuine departures since 08-16 plus C1 plus C2), how many the extension swallowed whole or delayed more than 2 min. Guest rooms are always in B with an 8 h cap; "ext cap" is per room, measured from the start of each room's occupied run.

| Config | Ordinary AWAY / SH per day (d>1) | Trip AWAY / SH per day | Within 15 min strict / loose / genuine-10 (absorbed of 10) | VE swallowed / delayed |
|---|---|---|---|---|
| Today | 2.92 / 2.53 (15) | 22.3 / 16.2 | 4/6, 8/10, 7/10 (0) | 0 / 0 |
| A W=3 only | 1.44 / 1.13 (6) | 17.9 / 13.2 | 4/6, 8/10, 7/10 (0) | 0 / 0 |
| A W=3 + Bguest | 1.32 / 0.97 (4) | 15.1 / 9.7 | 4/6, 7/10, 7/10 (0) | 0 / 0 |
| A W=5 + Bguest | 1.21 / 0.90 (3) | 12.8 / 8.1 | 3/6, 6/10, 6/10 (0) | 0 / 0 |
| A W=10 + Bguest | 0.97 / 0.58 (2) | 10.0 / 6.5 | 0/6, 1/10, 0/10 (0) | 0 / 0 |
| A W=5 + B all 7 ZK/ZX rooms, no cap | 0.70 / 0.23 (0) | 6.0 / 1.16 | 1/6, 2/10, 1/10 (3) | 4 / 4 |
| A W=10 + B all 7 ZK/ZX rooms, no cap | 0.62 / 0.12 (0) | 4.9 / 1.16 | 0/6, 0/10, 0/10 (3) | 4 / 1 |
| A W=5 + B all 7, ext cap 8 h | 0.86 / 0.43 (1) | 8.4 / 3.5 | 1/6, 3/10, 1/10 (2) | 2 / 6 |
| A W=5 + B 5 rooms (no Study A, no Kitchen), no cap | 0.82 / 0.39 (1) | 7.2 / 1.16 | 2/6, 3/10, 4/10 (1) | 2 / 2 |
| A W=10 + B 5 rooms, no cap | 0.70 / 0.23 (1) | 5.6 / 1.16 | 0/6, 0/10, 0/10 (1) | 2 / 0 |
| A W=3 + Bguest + Jaya + Ziri, no cap | 0.97 / 0.58 (3) | 11.1 / 5.3 | 4/6, 6/10, 7/10 (0) | 0 / 1 |
| A W=5 + Bguest + Jaya + Ziri, no cap | 0.86 / 0.51 (2) | 10.2 / 4.9 | 3/6, 4/10, 6/10 (0) | 0 / 2 |
| A W=10 + Bguest + Jaya + Ziri, no cap | 0.74 / 0.35 (1) | 8.4 / 4.2 | 0/6, 0/10, 0/10 (0) | 0 / 1 |
| A W=3 + Bguest + Jaya + Ziri, ext cap 12 h | 1.28 / 0.90 (4) | 13.5 / 7.7 | 4/6, 7/10, 7/10 (0) | 0 / 1 |
| **A W=3 + Bguest + Jaya (cap 16 h)** | **1.28 / 0.90 (4)** | **11.1 / 5.3** | **4/6, 7/10, 7/10 (0)** | **0 / 1** |
| A W=3 + Bguest + Jaya + Ziri, ext cap 24 h or none | 0.97 / 0.58 (3) | 11.1 / 5.3 | 4/6, 6/10, 7/10 (0) | 0 / 1 |

Notes on the table:
- The someone-home proxy shares sensors with the veto, so the all-room rows improve partly by construction (a room held is a room counted). The independent checks are the control windows, the verified-empty swallow count and the departure columns, and those are where the all-room rows fail.
- The Ziri gain on ordinary days is one event: on 09-28 Ziri's room was occupied continuously 20:41 on 09-27 to 23:12 on 09-28 (1,591 min, 26.5 h) while the house flapped to AWAY 12 times between 14:21 and 16:59; Ziri's room is what holds 8 of those entries in the replay. Any cap at or below 16 h removes it; it needs 24 h or more. Whether that run was a person or a stuck radar is unknown (Ziri's room was occupied 660 of 660 min that afternoon with Study A, Study B and Master Bedroom also occupied).
- Jaya's gain is on the trip (10-14 morning cluster, runs up to 934 min), where Jaya was home; her longest run is 15.6 h, so 16 h covers every observed run.
- Jaya's caps: 12 h gives trip SH 7.7 per day, 16 h gives 5.3 per day; ordinary-day SH is 0.90 for any cap, since the only ordinary-day gain from the pair is the Ziri run.

**Sensitivity to A's body predicate (lower bound).** With `unidentified_count > 0` only, A absorbs far less on ordinary days (face-recognised bodies are not stored in `census_snapshots`; the true predicate lies between the two). Ordinary / trip SH per day: A W=3 + Bguest 2.14 / 10.2; **A W=3 + Bguest + Jaya (16 h) 1.71 / 5.8**; W=5 same set 1.64 / 5.3; W=10 same set 1.56 / 4.9 (days over 1: 9 of 26 at W=3). Departure counts are unaffected (7 of 10 genuine within 15 min at W=3 and W=5).

### 4. False-hold exposure per week

Measured over 08-16 to 10-18 (9.1 weeks, 258 AWAY entries). "Verified empty" = 14 absences (10 strict genuine departures with exit crossing and no sustained body, C1, C2). "Entries held beyond Bguest" counts every non-guest-near AWAY entry delayed more than 2 min by the added rooms; it is an upper bound because it includes real occupants.

| Added room (over A W=5 + Bguest) | Entries held / swallowed whole | Verified-empty hit (delayed / swallowed of 14) | Non-guest-near holds per week | Remaining hold p50 / p90 / max (min) | SH entries removed (30 d) |
|---|---|---|---|---|---|
| Study A | 20 / 17 | 4 / 3 | 1.32 | 9 / 219 / 432 | 11 |
| Kitchen | 21 / 10 | 2 / 0 | 1.76 | 4 / 17 / 63 | 6 |
| Exercise Room | 23 / 23 | 0 / 0 | 2.53 | 12 / 43 / 51 | 24 |
| Master Bedroom | 11 / 8 | 2 / 1 | 1.10 | 4 / 73 / 275 | 9 |
| Living Room | 13 / 5 | 2 / 1 | 0.33 | 6 / 10 / 28 | 4 |
| Jaya Bedroom | 23 / 13 | 2 / 0 | 2.20 | 9 / 59 / 91 | 16 |
| Ziri Bedroom | 10 / 10 | 0 / 0 | 0.77 | 4 / 205 / 205 | 8 |
| Study B | 10 / 9 | 2 / 1 | 1.10 | 4 / 44 / 44 | 7 |
| Media | 1 / 1 | 1 / 1 | 0.11 | 165 / 165 / 165 | 1 |

Recommended set (A W=3 + Bguest + Jaya at 16 h): 1 verified-empty absence delayed (09-15, 8 min), 0 swallowed, about 2.6 non-guest-near holds per week as an upper bound (24 in 9.1 weeks; most are the 10-14 trip cluster and a few ordinary mornings). Exercise Room is the largest SH reducer but its holds are motion-sourced with a 12 to 51 min tail, not a still-hold; it is the biggest remaining miss and a sensor finding, not a veto candidate.

### 5. Remaining misses by room (recommended set, A W=3 + Bguest + Jaya 16 h, SH entries)

- **Ordinary days (23 SH entries, upper-bound predicate):** Master Bathroom 17 (InvisOutlet, do-not-use class), Study A 14, Master Bedroom 9, Ziri Bedroom 8 (all 09-28), Study B 7, Living Room 5. Entries can name several rooms.
- **Jaya+guest days (23 SH entries):** Exercise Room 14, Living Room 6, Jaya Bedroom 3, Study B 1, GB2 1.
- Everything left is people in rooms whose sensors are motion-class, phantom-prone, or unreliable (Exercise Room, Master Bathroom, Study A) or in rooms that failed the verified-empty test (Master Bedroom, Living Room, Study B).

### 6. Recommendation

| Decision | Recommendation | Why |
|---|---|---|
| Rooms | GB1, GB2 (existing), **add Jaya Bedroom only** | Jaya: 0 control occupancy in C1, 9 min in C2, swallows 0 of 14 verified-empty absences, delays 1 by 8 min. Do not add Study A (phantom), Kitchen (phantom, 123 fan-or-HVAC minutes of 778), Exercise Room (ZK silent, motion-sourced), Ziri (one 26.5 h run), Living Room / Master Bedroom / Study B / Media (each swallowed a verified-empty absence for 1 to 9 SH entries over 30 d) |
| W | **3 min (180 s)** | Only W that keeps departures within 15 min at today's count (genuine 7/10, strict 4/6). W=5 drops to 6/10 and 3/6; W=10 to 0/10 |
| Hold cap | **8 h guest rooms (P1 default stands), 16 h Jaya Bedroom** | Jaya's longest run is 15.6 h; below 16 h the trip gain falls (12 h: 7.7 SH per day vs 5.3). Ziri, if ever added, needs 24 h or more, which defeats a cap and is the reason to leave it out |
| Marginal-benefit read | Jaya adds 0.07 SH per day on ordinary days (0.97 to 0.90) and 4.4 SH per day on trip days; the all-room version adds 0.7 SH per day more but costs 3 of 10 genuine departures | The extension is worth it only for the "Jaya alone home" case; on ordinary days guard A at W=3 plus Bguest does nearly all the work |

**Goal check, plainly:** (1) at most 1 someone-home AWAY per day: **not met**. Ordinary days 0.90 per day best case, 1.71 per day with the stricter body predicate, and 4 (best case) to 9 of 26 days over 1; Jaya+guest days 5.3 to 5.8 per day. Reaching the target on trip days required holding on Study A, Kitchen, Exercise, Master Bedroom and Living Room, which fail the controls or swallow genuine absences. (2) departures within 15 min: **not met even today** (7 of 10 genuine, 4 of 6 strict; the strict misses today are 16.0 and 24.6 min and come from zone grace plus census latency, not the guard). W=3 holds the count flat; no W improves it.

### 7. Caveats

- No ground truth for who is home. Controls and "verified empty" are crossing-and-state proxies (14 absences); the recorder phone data covers only 7.2 d and its all-away windows are 97% the trip, when Jaya and a guest were home.
- Occupancy minutes from the DB include the 300 s hold tail; the recorder `_occupied` entities were used for fan splits.
- Fan data (room fan and zone HVAC action) exist only for the 7.2 d recorder window; control windows before 10-11 cannot be fan-split.
- A's predicate sensitivity is large on ordinary days (0.90 vs 1.71 per day for the recommended set); the `face_recognized_count` half is not in `census_snapshots`. Add it (or the stamp store) before trusting any ordinary-day number.
- Study A's Athom sensor and Exercise Room's ZK showing no on-time are separate sensor-health findings (not carded here).
- The 09-28 Ziri run and the Jaya LD2410 478 uncorroborated trip minutes are phantom-or-real unknowns; neither could be settled from the recorder.

---

## P4 2026-10-18 — BLE and resident-only goal

**Run:** Sun 2026-10-18 10:46 CDT, ura-prober, read-only. Trigger: operator, "Did you factor BLE in all this? Study A should generally know when I'm there if my phone is on me. Guest accuracy is not a high priority as resident", then clarified "not as high. But that's relative": guests count with a lower weight, so **residents and guests are reported separately and neither is dropped**. Read first: `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (complete), Rev 4 of the AWAY-flap plan, P0 to P3 above. Scripts (not in repo): `.../scratchpad/p4/` (`lib4.py`, `b3.py` to `b8.py`), built on the P3 `sim()` and `pps.json`, `mem.json`, `rec.json` extracts.

### 0. Answer first

1. **Yes for the decision, no for the measurement.** BLE already blocks all three AWAY branches while a phone is *visible* in a room. Neither P0 to P3 nor Rev 4 modelled BLE: they proxied "phones away" and counted room-occupancy evidence at the AWAY instant. That proxy mislabels most departures as "someone home".
2. **Most of the Rev 4 residual is not a miss.** Rev 4 ordinary-day residual (55 entries, 2.14/day, lower predicate): **35 are the residents' own departure** (a resident's BLE was in a room within 20 min and the room's 300 s hold tail was still occupied), 8 are blips with no recent resident BLE, **8 are real resident misses (0.31/day)**, 4 are guest-flagged (0.16/day), 0 are untracked sustained. Upper-predicate set: 25 entries = 12 / 1 / **7 (0.27/day)** / 4 guest / 1 untracked.
3. **Study A, your 14 misses:** your phone was BLE-located inside the house within 17.4 min before the AWAY in **12 of 14**, and in Study A or its closet within 30 min before in 4 of 14. The other 2 (09-22, 09-26) are the all-out phantom days. So Study A mostly "knew you were there" and then lost you: BLE dropout, not a phone left elsewhere.
4. **A BLE lever exists and the plan missed it:** treat a resident whose BLE disappeared within the last N minutes as home (hold AWAY), instead of dropping a STALE person from the denominator. N = 5 min costs no measured departure; N = 10 catches most real resident misses and costs 1 of 7 departures inside 15 min. Not a build approval; precision is limited (section 6).

### 1. How BLE feeds AWAY today (producer and consumer)

**Producer.** `person_coordinator.py:470-541`: if the Bermuda area sensor resolves, `location = <room>`, `tracking_status = ACTIVE`, `tracking_reason = bermuda`. If it does not resolve: within `decay_timeout` (default 300 s, `const.py:164`, applied `person_coordinator.py:610-642`) the person keeps the old room but is stamped **STALE** (`method = bermuda_decay`). After 300 s, `person.*` `not_home` yields `location = away`, ACTIVE (`:723-739`, matrix `:366-368`, `:387-393`); `home` yields `home` (`:681-702`); unknown yields LOST with no vote (`:709-722`).

**Consumer** (`presence.py`, `_run_inference` `:5796-5970`): `trustworthy_persons` keeps a person only if the phone-left-behind sensor is not `on` (`:5834-5860`) AND `tracking_status == ACTIVE` (`:5862-5873`, applied `:5916`). `all_tracked_persons_away = all(location in ("away","") for trustworthy)` (`:5939-5943`).

| Branch | BLE blocks it? | Where |
|---|---|---|
| Nobody-home | Yes while visible: `census_count == 0` and census_count includes BLE ids (comment `:1150-1151`) | `presence.py:1127` |
| Path alpha | Yes while an ACTIVE resident shows a room (`all_tracked_persons_away` false) | `:1170-1175` |
| Path beta | Yes, same denominator, plus `census_count == 0` and `not indoor_blocked` | `:1248-1253` |

**Gaps (all verified in code).**
- **G1, STALE persons are dropped, not counted.** A resident BLE-seen within the last 300 s but unresolved this tick is excluded from the denominator (`:5916`, reason `tracking_status=stale`). Memory snapshots show it live: AWAY at 2026-10-17 20:26, 20:35, 23:33, 23:37 UTC fired via alpha with `tracked_persons_count_trusted = 3`, `excluded_persons = {Jaya: tracking_status=stale}`, `census_count = 1`.
- **G2, no BLE memory past 300 s.** After the decay window a resident whose `person.*` is `not_home` (WiFi/GPS asleep) is plain AWAY-voting, however recently Bermuda placed them.
- **G3, the Rev 4 guard and veto read none of it.** Guard A's stamp B explicitly ignores BLE (INV-NO-BLE-HOLD, plan `:131`); veto B reads rooms, not people.

**Ground truth at the real AWAY decisions.** `memory_episodes` `house_state_transition` to away, 2026-10-13 00:32Z to 10-18 00:11Z: **102 entries**. `all_tracked_persons_away = True` in 102 of 102; trusted count 4 in 98; `census_count = 0` in 98; `unidentified_count = 0` in 102. `veto_path`: `none` (nobody-home) 54, `active` 48. So at every real AWAY, all trackers said away or stale; the "someone home" evidence is always sensors or a person the trackers were not seeing.

### 2. Classification of the residual "someone-home" entries

Method: P3 open-loop replay, Rev 4 = A at W = 3 min + veto B on GB1/GB2 (8 h cap). "Someone home" = the P0 sensor proxy (still-holder or camera rooms, Kitchen excluded). Each entry is bucketed (guest flag first):
- **G**: GUEST state within 1 h or a guest room in the evidence.
- **A1**: evidence only at the AWAY instant (the room's 300 s hold tail) AND a resident BLE room row within 20 min before. A resident just left; AWAY is right.
- **A2**: evidence only at the instant, no recent resident BLE. Blip or phantom; unknown.
- **B (resident miss)**: evidence sustained 10+ min into the AWAY (3+ min occupied or an unidentified body), no guest flag, AND a resident BLE room row 5+ min into the episode and 7+ min before it ended. A resident was home and the trackers did not see them.
- **C**: sustained evidence, no resident phone or BLE signal in the episode. Guest, phoneless person, or phantom.

Ordinary days 09-18 to 10-13 (25.7 d); Jaya+guest days 10-14 to 10-18 (4.3 d; Jaya is a resident, the guest is untracked).

| Config, predicate | Ordinary entries (per day) | G guest | A1 tail | A2 | **B resident miss** | C untracked |
|---|---|---|---|---|---|---|
| Today, upper (`total_persons`) | 65 (2.53) | 14 | 36 | 8 | **7 (0.27/d)** | 0 |
| A W=3 only, upper | 29 (1.13) | 9 | 12 | 1 | 6 | 1 |
| A W=3 only, lower (`unidentified_count`) | 62 (2.41) | 13 | 34 | 8 | 7 | 0 |
| **Rev 4, upper** | **25 (0.97)** | **4 (0.16/d)** | 12 | 1 | **7 (0.27/d)** | **1 (0.04/d)** |
| **Rev 4, lower (the plan's 2.1/day)** | **55 (2.14)** | **4 (0.16/d)** | 35 | 8 | **8 (0.31/d)** | **0** |

| Rev 4 on Jaya+guest days | Entries (per day) | G guest | A1 | A2 | B resident (Jaya) | C untracked (the guest) |
|---|---|---|---|---|---|---|
| upper | 42 (9.74) | 1 | 12 | 15 | **6 (1.39/d)** | **8 (1.86/d)** |
| lower | 44 (10.20) | 3 | 12 | 15 | **6 (1.39/d)** | **8 (1.86/d)** |

Reading:
- **Residents, ordinary days:** real misses are **7 to 8 in 25.7 days (0.27 to 0.31/day), today and under Rev 4 alike.** Rev 4 does not change them; it removes the guest-flagged ones and the short flaps. Against the goal "at most 1 resident someone-home AWAY per day" this is **met on average**, but the days over 1 are concentrated: 09-28 alone is a 12-flap day (all four phones BLE-visible in rooms minutes before each flap).
- **Guests:** 4 guest-flagged entries (0.16/day) plus at most 1 untracked sustained, ordinary days. On Jaya+guest days the untracked guest is the large term (1.86/day, plus 0.23 to 0.70/day guest-flagged). Rev 4 does not reach a guest in a non-guest room with no phone.
- **A1 is the bulk of the "2.1/day" and is mostly an artefact.** It is the departure moment seen through a 300 s hold tail. It is not removable by a veto without delaying real departures (section 4).
- **A2 (8 lower, 1 upper) is unknown:** no resident BLE within 20 min and no sustained evidence. Candidate phantoms.

### 3. Study A, the 14 misses (Rev 4 upper-predicate set, all ordinary days)

| Date / time CDT | Oji's last BLE room before AWAY (min before) | Phone state (recorder, from 10-11) | Reading |
|---|---|---|---|
| 09-22 12:02, 09-26 10:04 | Master Bedroom 4,985 min; Garage A 375 min | n/a | All four away for hours; Study A "occupied" the whole absence: the P3 phantom. Not a miss. |
| 09-28 14:21, 14:43, 14:54, 15:05, 15:13, 16:06, 16:59 (7) | Receiving Room 17.4, Dining Room 11.0, Dining 6.4, Receiving 2.4, Receiving 10.9, Receiving 3.3, Receiving 10.1 | n/a | Oji (and Ezinne, Jaya) BLE-visible in other rooms minutes before each flap. **Resident miss, BLE dropout**; Study A radar was a coincident room. Not Study A. |
| 10-08 09:39 | Study A Closet 13.2; Study A rows at -28.5 and +2.0 min | n/a | **Oji in Study A, BLE dropout, 60-min AWAY.** |
| 10-10 11:18 | Living Room 14.0; Kitchen +1.4 min after | n/a | Oji in the house, BLE moving. Resident miss. |
| 10-11 09:41, 09:47 | Study A Closet 11.7; Foyer 2.4 | `not_home` | Oji leaving (Foyer). AWAY correct; Study A is the fan-tail phantom. |
| 10-11 11:23 | **Study A 6.9; Study A again at +8.1 min; Study B +24 min** | **`not_home` since 11:06** | **Textbook: `person.*` away for 17 min while Bermuda placed Oji in Study A 7 min before and 8 min after.** 73-min AWAY (11:23 to 12:36). |

**Answer to "was my phone home or BLE-located in Study A?"** BLE-located anywhere in the house within 17.4 min before: **12 of 14** (11 if you drop the 10-11 09:47 Foyer departure from "in the house"). BLE-located in Study A or its closet within 30 min before: **4 of 14** (10-08 09:39, 10-11 09:41, 09:47, 11:23). `person.oji_udezue` home: **0 of 3 checkable** (recorder only from 10-11; and by construction an AWAY cannot fire with a trusted `home` phone). Real resident-in-Study-A misses: 10-08 09:39 and 10-11 11:23 (2 of 14); resident in the house elsewhere: 8 (09-28 x7, 10-10); departures: 2; phantom: 2. Mechanism for the 10-11 11:23 case: Bermuda unresolved, `person.*` not_home, no decay left, so alpha counted Oji as away (G1/G2 above).

### 4. The BLE lever the plan missed

**Lever L(N):** a resident who had a BLE room within the last N minutes (dropout recency, not "visible now") counts as home for all three branches, bounded by N. Reuse: `tracking_status == STALE` already encodes N = 300 s; L(5) is "stale persons block instead of being excluded" (one conjunct on the denominator, `presence.py:5916`). Anything longer needs a new last-seen stamp (NEW).

| N | Real sustained misses caught (ordinary, 9 genuine of 11 sustained; 2 are the phantom days) | Genuine departures within 15 min of exit crossing (loose set, 10) | Median exit to AWAY |
|---|---|---|---|
| 0 (today, with A and B) | 0 | 7 | 11.5 min |
| 5 | 2 to 4 | 7 | 11.6 |
| 10 | 6 to 7 | 6 | 14.6 |
| 15 | 9 | 4 | 15.3 |

Entry blocks on the whole residual (incl. A1) are 5/25, 15/25, 21/25 at N = 5/10/15 (upper) but **those extra blocks are the departures themselves**, which is why the cost column rises. Do not read the residual drop as value.

**Forgotten-phone hazard (INV-NO-BLE-HOLD, Rev 2).** The hazard is a stationary phone that stays visible and holds the house forever. L(N) cannot do that: its hold ends N minutes after the phone stops being seen, whatever the phone does; a phone that stays visible is already handled by the existing `phone_left_behind` exclusion (`presence.py:5834-5860`) and is unchanged. The real cost of L(N) is a genuine departure delayed by up to N minutes after the phone is last seen (garage, driveway): the table. So the hazard is bounded, not reopened, but the trade is departure speed.

**Marginal-benefit read.** L(5) is nearly free and reuses `STALE`; it plausibly removes the 10-17 20:26 to 23:37 style entries (4 of 102) and 2 to 4 of 9 ordinary resident misses. L(10) buys a few more at a measured 1-of-7 departure loss. Recommend L(5) as a candidate sub-deliverable of the AWAY-flap plan or its own small card; L(10+) only after the better probe below. **Not decided here.**

### 5. Goal re-stated: residents primary, guests second

| | Today | Rev 4 | With L(5) (estimate) |
|---|---|---|---|
| Resident someone-home AWAY per day, ordinary | 0.27 (7 in 25.7 d), upper | 0.27 to 0.31 | about 0.15 to 0.25 |
| Resident, Jaya+guest days | 1.39 (6 in 4.3 d) | 1.39 | lower |
| Guest-flagged, ordinary | 0.55 (14), upper | 0.16 (4) | unchanged |
| Untracked/phoneless sustained, Jaya+guest days | 2.55 (11) | 1.86 (8) | unchanged |

Residual cause for residents: **BLE dropout with `person.*` not_home** (phone asleep on WiFi/GPS, Bermuda silent for more than 5 minutes), in 9 of 9 genuine ordinary cases a resident BLE row exists in the same episode. It is **not** "phone left in another room" (that case stays visible and is excluded by `phone_left_behind`) and not a missing resident. Guests' residual is "no phone, no camera, non-guest room".

### 6. Caveats and unknowns

- **`pps` lags truth.** `person_presence_snapshots`-style rows (`pps.json`) matched the memory-snapshot all-away state in only 63 of 102 real entries; mismatches are mostly Bermuda rows with no later away row. "Resident BLE within 20 min" and "age since last room row" therefore mix last-seen and last-changed; they are upper bounds on recency. A proper probe needs the Bermuda area sensor history (recorder, 7 days) and the person_coordinator STALE/ACTIVE transitions; not run.
- Rev 4 residual classes A1/A2/B/C are inferences from sensor and BLE rows; no ground truth for who was home.
- The 8 + 7 resident misses are small counts (95% intervals wide); the 09-28 cluster is 7 of 8 lower-set Study A entries.
- Recorder phone state begins 10-11 04:16 CDT; pre-10-11 phone state is unknown.
- Predicate bounds (upper `total_persons` / lower `unidentified_count`) carry over from P2/P3; `face_recognized_count` is still not stored.
- Not done: a replay of L(N) as a real code path; effect of L(N) on the 9 trip stale-Jaya style entries beyond the 4 snapshot rows.
