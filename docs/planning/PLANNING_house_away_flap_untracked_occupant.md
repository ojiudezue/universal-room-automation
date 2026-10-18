# PLANNING — House AWAY flap with an untracked occupant home

**Card:** HOUSE-STATE-AWAY-FLAP-UNTRACKED-OCCUPANT-1
**Status:** **Rev 3**, 2026-10-18. Plan only: the operator approved writing it, not building it. Rev 3 replaces Rev 2's design numbers with the measured results in `AUDIT_census_arc_and_away_holistic.md` (P0–P2 "Probe results 2026-10-18" and "Probe P3"). It adds veto B and the observability work, and drops the shared estimator knob. Rev 2's review dispositions (R1-01…R2-08) still apply and are kept in §13. **Next step:** two Tier-3 plan reviews (completeness + adversarial build-prediction), dispatched by the orchestrator. Then operator approval of the PICKs in §11, then build.
**Author:** ura-planner.
**Operator constraints (2026-10-18, verbatim):**
- "this is surgery on the house state so I want a prior art scan and I want it to build on our infra and not be frivolous new functionality."
- "observability in the presence coordinator and house device is important as well as ura v8 dashboard."
- "HVAC to go away fast... house to be more careful."

---

## 0. The plan in one paragraph

URA declares the house AWAY too readily when no tracked phone is home but a person is. Rev 3 makes three changes, all inside the existing house-state inference and the existing presence sensor.

- **(A) Camera-recency guard.** The three automatic AWAY branches may not fire until the interior cameras have seen no person for **W = 3 min**. Only an unrecognised body or a recognised face counts; phones and BLE never do.
- **(B) Room veto.** The existing guest-room occupancy tracker is extended so that path α (the only AWAY branch that ignores rooms) cannot fire while Guest Bedroom 1, Guest Bedroom 2 or Jaya Bedroom is occupied. The hold is capped at 8 h for the guest rooms and 16 h for Jaya Bedroom.
- **(C) Observability.** The presence house-state sensor shows why the house went AWAY, what is holding it home now, and today's AWAY count. One v8 card shows this.

Measured effect over the last 30 days:
- Ordinary days: someone-home AWAY entries fall from 2.53/day to an expected ~1.7/day (range 0.90–1.71).
- Days when only Jaya and the guest were home: 16.2/day falls to ~5.8/day.
- Departures still reach AWAY as fast as today (7 of 10 within 15 min).
- **The goal of ≤ 1 someone-home AWAY per day is NOT met** (§6). The remaining misses are people in rooms whose sensors cannot be trusted: Master Bathroom, Study A, Master Bedroom.

HVAC's own zone-vacancy path is untouched. The house AWAY edge, which HVAC also follows, arrives at most W later.

---

## 1. Institutional context verified (MANDATORY)

### 1.1 Mandatory docs read completely before writing
- `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`, including the §10 ledger (items 1–12). Nothing here re-asserts a ledger claim. #12 (path α has no census or zone term) is the root of this card and is relied on as corrected.
- `docs/architecture/SENSOR_FLEET_CLASSES.md`:
  - ZV is motion-class and cannot hold a still person. ZK, ZX, MS600 Matter and LD2410 are radars.
  - The room list for veto B was classified by capability (device model), not by entity name (P3 §1).
- `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md`, read completely (HVAC consumes house AWAY).
  - No §10 claim is re-asserted.
  - Zone vacancy grace is knob 48 = 5 min live (§3.2).
  - The house-state handler is `hvac.py:5184` (HVAC doc §2 still says `:3260`, and Rev 2 said `:5177`; both are stale, see §12 C10).
- `docs/planning/AUDIT_census_arc_and_away_holistic.md`, complete, including "Probe results 2026-10-18" and "Probe P3".
- `docs/planning/AUDIT_away_flap_untracked_occupant_would_have.md`, complete.
- Rev 2 of this plan and both plan reviews (`docs/reviews/plan-review/PLAN_REVIEW_house_away_flap_R1_completeness.md`, `…_R2_build_prediction.md`).
- `docs/Coordinator/IDENTITY_FUSION_CAMERAS_MANUAL.md` (via Rev 2; no identity input added). `face_recognized_count` is used only as "a camera saw a body".

### 1.2 Prior-art scan: REUSE / EXTEND / BUILD (re-grepped on `develop` @ `8b7699001`, 2026-10-18)

| # | Piece | Verdict | Evidence (file:line) |
|---|---|---|---|
| P1 | The three automatic AWAY returns | **EXTEND** (one conjunct each, placed after the already-AWAY check) | `presence.py:1127-1131` nobody-home, `:1170-1181` path α, `:1248-1288` path β. `grep "return HouseState.AWAY" presence.py` → exactly `:1131`, `:1181`, `:1288`. No other automatic producer (R1-verified: `HouseStateMachine.transition` only at `presence.py:6961`). |
| P2 | Camera evidence per census tick | **REUSE** | `_handle_census_update` parses `unidentified_count` (`presence.py:4758`) and `face_recognized_count` (`:4765-4769`). |
| P3 | Last-camera-body timestamp | **BUILD: one RAM field** `_last_camera_body_ts` | `grep -rn "last_camera_body\|away_hold\|camera_recent"` → 0 hits. `camera_census.py` `_peak_house_timestamp` / `peak_held` are peak-hold stamps on a total that the clamp cuts back (Rev 2 §3.2), so they cannot serve. |
| P4 | Discharge of the guard | **REUSE** the 60 s periodic | `async_track_time_interval(self._periodic_inference …)` `presence.py:2926-2930`; handler `:5074`. Not `_schedule_deferred_retry` (shared slot, R2-02). |
| P5 | Room-occupancy tracker for veto B | **EXTEND** `_discover_guest_rooms` / `_handle_guest_room_occupancy_change` | `presence.py:5164-5334`, `:5336-5401`. The tracker already resolves each room's `binary_sensor.<room>_occupied` by registry unique_id `f"{entry_id}_occupied"` (`:5213-5216`), holds per-room state in `_guest_room_state` (`:1726`), boot-seeds from `last_changed` (`:5254-5319`), cleans up its unsubs (`:5183-5191`, teardown `:7653`), and re-runs inference on every change (`:5401`). |
| P6 | Guest gate (must NOT change behaviour) | **REUSE, fenced** | `_guest_room_gate_armed` `presence.py:5485-5535` iterates `_guest_room_state`. A non-guest veto room added to that dict would arm GUEST, so §7 D3 adds a role filter (mutation-anchored). |
| P7 | Which rooms are veto rooms + their caps | **BUILD: one room-options field** `CONF_ROOM_AWAY_HOLD_MAX_H` | `grep -n "AWAY_HOLD\|AWAY_VETO" const.py config_flow.py` → 0. `CONF_ROOM_IS_GUEST_ROOM` (`const.py:402`, options `config_flow.py:12509`) cannot be reused: setting it on Jaya Bedroom would arm GUEST mode on Jaya's own occupancy. |
| P8 | Guard window knob | **BUILD: one Number** `CONF_PRESENCE_AWAY_CAMERA_QUIET_S`, cloned from **REUSE template** `FanInterferenceHoldNumber` `number.py:3541` | The template is a Presence Coordinator device Number whose setter writes CM `entry.options` ("SOLE source of truth, no RestoreEntity"). `grep "FLOOR_WINDOW\|COUNT_MEMORY\|AWAY_QUIET" const.py` → 0. The estimator's `FLOOR_WINDOW_S` is unbuilt and **deliberately not shared**: holistic audit §3 explains that sharing would silently lengthen the delay when the estimator lands. |
| P9 | Veto label | **EXTEND** | `self._veto_path` reset `presence.py:1124`, set `:1177/1180/1274/1277`; mirrored `:6518`; surfaced `sensor.py:5661`; copied into the D7 episode `:7926`. `grep "alpha_starved\|beta_only\|lost_admitted"` shows **no actuation consumer** of the values (presence.py + sensor.py only). |
| P10 | Block-episode writer (D5 memory) | **EXTEND** | `_blocked` / `_veto_path_str` `presence.py:6532-6553`. Today a guard or veto hold is not `_blocked` (the D5 predicate needs α-starved or α-denies), so holds would be invisible. |
| P11 | House-state sensor | **EXTEND (attributes only, no new entity)** | `PresenceHouseStateSensor` `sensor.py:5557-5784` (`sensor.ura_presence_coordinator_presence_house_state`, Presence device). |
| P12 | Daily counter + restart hydration | **REUSE + EXTEND** | `_count_transition` `presence.py:7450-7470` (midnight reset); hydration `presence.py:2573-2591` → `database.count_house_state_changes_since` `database.py:3031-3058`. EXTEND = optional `state` filter kwarg (read-only SELECT, default byte-identical). |
| P13 | Kill switches | **REUSE** `switch.ura_presence_coordinator_away_confirmation_veto` (`switch.py:3880`, coerces α/β off at `presence.py:6476-6486`). Guard A: W = 0. Veto B: per-room 0. | — |
| P14 | v8 card style | **REUSE** the Energy view pattern | `ura-v8` view `energy` (read live 2026-10-18): `sections` grid → `heading` (`heading_style: title`) + `custom:button-card` `template: hero` (`custom_fields.pv`, `label`, `variables.color`) + `markdown` table. Pre-edit snapshot pattern: `docs/ha-config-snapshots/lovelace_ura_v8_backup_*.json`. |

**New functionality, flagged and justified:**
1. One RAM timestamp (P3). No existing stamp has these semantics.
2. One rung-3 Number (P8). The guard needs a live, operator-tunable window and no knob exists.
3. One rung-2 room field (P7). Rooms need per-room veto membership plus a cap, and the guest flag would arm GUEST.
4. One optional DAO kwarg (P12).
5. Label strings and sensor attributes (P9–P11).

**Not added:** no timer, no persisted store, no new entity, no census payload change, no DB schema change, no new signal, no door tally, no HVAC split.

### 1.3 Prior plans and cards
- **Estimator** (`PLANNING_census_occupancy_estimator.md`): recommended PARK (holistic audit §5, piece D). Its `FLOOR_WINDOW_S` is not reused (P8).
- **Holistic audit §5 pieces:** A, B and C fold into this plan. G (P0 scorecard) becomes the exit discriminator. H (patio mask) and M (override for planned gatherings) are config actions. O (HVAC rides the guard) is DROPPED by operator instruction.
- **Cards read:**
  - EXERCISE-ROOM-PRESENCE-MISCONFIG-1 (done).
  - STUDYA-ZIGBEE-MMWAVE-MISCATEGORIZED-1 (done).
  - STUDY-A-CSI-SENSOR-1 (parked).
  - CENSUS-OCCUPANCY-ESTIMATOR-1, EGRESS-INTERIOR-COUNT-REINFORCE-1 (planned), CENSUS-ATHOME-RESIDENT-CORROBORATOR-1.
  - No card covers "Study A ZK holds an empty room for hours". See §10.

### 1.4 Memory
- `project_presence_guest_latch_and_veto_gap`, `project_guest_mode_false_positive_backlog` (via the holistic audit's pulled bodies).
- `feedback_suppression_needs_discharge` (the discharge in §7 D2).
- `feedback_marginal_benefit_pushback` (§5).
- `project_house_zones_vs_hvac_zones`.
- `feedback_no_restart_during_sleep` (§9).

### 1.5 Code read for Rev 3
- `presence.py`: `1030-1300`, `2560-2600`, `4750-4772`, `5164-5535`, `6470-6575`, `6955-6972`, `7440-7495`.
- `camera_census.py:3025-3065, 5850-5905` (face count cross-check).
- `hvac.py:1430-1445, 5184-5230`.
- `number.py:3541-3600, 675-700`; `config_flow.py:5490-5505, 5606-5625`; `database.py:3031-3058`.
- `coordinator.py:925-945`.
- Consumer greps in §3.4.

---

## 2. Falsifiable invariants

Definitions:
- `W` = the live `CONF_PRESENCE_AWAY_CAMERA_QUIET_S` (seconds).
- `B` = `_last_camera_body_ts`: the latest census update with `unidentified_count > 0 OR face_recognized_count > 0`. After a restart, `B` = the coordinator setup time until a newer body is seen.
- `R` = the set of rooms with `CONF_ROOM_AWAY_HOLD_MAX_H = cap_r > 0`.
- `O_r(t)` = room r's `binary_sensor.<room>_occupied` is `on` at t.
- `S_r` = the start of r's current continuous occupied run.

> **INV-A (camera quiet):** for W > 0, `infer()` never returns `HouseState.AWAY` from the nobody-home, α or β branch at a time t with `t − B < W`.

> **INV-B (room veto):** for any r ∈ R, path α never returns `HouseState.AWAY` at t while `O_r(t)` and `t − S_r < cap_r`. (Nobody-home and β already cannot fire then, because r's occupancy makes `any_zone_occupied` / `indoor_blocked` true. P2 justified this from code at `presence.py:1127`, `:1252`.)

> **INV-DISCHARGE:** a hold always ends; there is no stuck HOME. If every other AWAY conjunct of a branch holds continuously from `t*` = max(B + W, release of the last veto: room clears or its cap expires), then AWAY is proposed by `t* + 60 s` (one periodic tick) and accepted within any remaining state-machine hysteresis (≤ 120 s for HOME_*, `house_state.py:~130`).

> **INV-NO-BLE-HOLD:** a census update with `unidentified_count = 0 AND face_recognized_count = 0` never moves `B`, whatever `census_count` / `interior_count` say. A forgotten phone or a stale BLE fix cannot hold the house home.

> **INV-ALREADY-AWAY:** neither A nor B changes behaviour when `current_state == AWAY`. In particular, B's room occupancy cannot turn an AWAY house into ARRIVING through α's fall-through. The `if current_state == AWAY: return None` in each branch is evaluated BEFORE the new conjunct.

> **INV-GUEST-UNCHANGED:** a room that is in R but not flagged `CONF_ROOM_IS_GUEST_ROOM` never arms the guest-room gate.

> **INV-BYTE-ID:** with W = 0 and R = ∅, every `infer()` return value, every state transition, and every persisted row are identical to today. The only permitted differences are the new label/attribute VALUES in §7 D4 (display).

Reviewer D's job is to break these, in particular INV-ALREADY-AWAY (§7 D2 explains the trap) and INV-DISCHARGE under a veto room that flaps.

---

## 3. Producer and consumer checks

### 3.1 The three AWAY branches (producer of AWAY)
1. **Nobody home** `presence.py:1127-1131`: `census_count == 0 and not any_zone_occupied`. Confidence 0.9. `_veto_path` stays `none` today, which is the O1 gap.
2. **Path α** `:1170-1181`: `not camera_input_degraded and all_tracked_persons_away and unidentified_count == 0 and face_recognized_count == 0`. Confidence 0.95, label `active`. No census or room term (ledger #12).
3. **Path β** `:1248-1288`: trackers away, `unidentified_count == 0`, `census_count == 0`, `not indoor_blocked`, grace / no-LOST / immediate-engage, `not sleep_exempt_state`. Label `lost_admitted[_immediate]`.

### 3.2 Producer of `B` (the stamp)
- **`unidentified_count`:** the clamped held unidentified count. With all trackers away it equals the instantaneous interior camera person count (clamp `camera_census.py:6006-6009`, Rev 2 §3.2).
- **`face_recognized_count`:** residents recognised within 1800 s whose `person.*` is NOT `not_home` (`camera_census.py:5875-5895`; fail-OPEN when the person entity is missing).
- **Dependency health:**
  - Census updates arrive on every camera change, and the 60 s periodic re-reads the last values.
  - `camera_input_degraded` (Frigate dark) already skips α. The guard still applies to nobody-home and β then. That is conservative: no body is seen, so `B` ages and the guard releases after W.

**Predicate decision (P3 caveat, decided with evidence rather than left as a PICK):** keep **both terms**, `unidentified_count > 0 OR face_recognized_count > 0`.
- **When the face term can matter.** On every AWAY-eligible tick the face term is 0 by construction:
  - α requires `face_recognized_count == 0`.
  - Nobody-home and β require `census_count == 0`, and census ≥ |face ∪ BLE| ≥ face.

  So the face term never coincides with an AWAY decision. It only extends the hold across the moment the last phone goes `not_home`, which is when the cross-check drops recognised faces.
- **Cost bound.** That extension is a departure delay. P3 measured departures with `total_persons > 0`, a strict superset of the face, unidentified and BLE terms, and W = 3 still kept 7 of 10 genuine departures within 15 min, the same as today. Adding the face term therefore cannot cost more departure timing than measured.
- **Benefit.** It holds the house for W after a phone flaps `not_home` while its owner stands in front of a camera. That is a real someone-home case, and it is one the unidentified-only predicate misses.
- **Honest consequence for the numbers.** P3's two bounds bracket the outcome. 0.90/day uses `total_persons`, which includes BLE identities that INV-NO-BLE-HOLD excludes on purpose. 1.71/day uses unidentified only. The face term rarely fires while all phones are away, so **plan on ≈ 1.7/day on ordinary days**. 0.90 is not reachable by design.
- **To make the post-ship scorecard exact,** D4 publishes `last_camera_body_source` (`unidentified` / `face`). The P0 re-run reads it from the recorder.

### 3.3 Producer of the veto bit (room r ∈ R)
- **Input:** URA's fused room occupancy `binary_sensor.<room>_occupied`. P1–P3 measured exactly this signal, including the 300 s hold tail.
- **Unavailable → not occupied:** the existing handler semantics (`presence.py:5356-5359`). This fails OPEN for AWAY. A dead sensor cannot hold the house home.
- **Known-person check: NOT applied to the veto.** The guest gate disarms when a resident is in the room (`_is_known_person_in_room`, `:5403`), because a resident is not a guest. For the AWAY veto, a resident in the room is still someone home. P1–P3 simulated occupancy only. So the veto reads its own `occupied_since` stamp (§7 D3), not `first_seen`.
- **Dependency health per room (P1, P3):**

| Room | Sensor | Health |
|---|---|---|
| GB1 / GB2 | Matter MS600 | 0 uncorroborated radar minutes; 0 occupancy in 6 guest-free control windows; fan explains ≤ 7% of all-away occupied minutes |
| Jaya Bedroom | ZK + LD2410 | 0 C1 / 9 C2 control minutes; swallows 0 of 14 verified-empty absences, delays 1 by 8 min |

  Known unknown: the LD2410 held 478 trip minutes while the ZK saw nothing (Jaya in bed, or phantom). The 16 h cap bounds it.

### 3.4 CONSUMERS of house AWAY: who gets the guard (re-grepped 2026-10-18)

The guard sits in inference, so **every consumer** sees the guarded AWAY. The table prices an up-to-W (3 min) later AWAY and an up-to-cap veto hold.

| Consumer | file:line | Kind | Effect of A (≤ 3 min later) | Effect of B (held while room occupied) |
|---|---|---|---|---|
| HVAC presets | subscribe `hvac.py:1437`, handler `:5184`; AWAY → all-zone away at `hvac.py:2968`/`:3024` | signal, trust | House edge is the first zone mover in 22% of zone-episodes (would-have audit §4.1), now ≤ 3 min (+≤ 60 s tick +≤ 120 s hysteresis) later. **Zone-vacancy retreat (knob 48, 5 min) is untouched** and is first in 69%. | Zones without the occupied room still retreat by zone vacancy. The occupied room's zone stays home, which is correct while someone is there. |
| Room AWAY leave-on lights sweep | `coordinator.py:935` | signal edge | Sweep ≤ 3 min later | No sweep while held; room vacancy timeouts still turn lights off |
| Security auto-follow | `security.py:759`, `:1087-1094`; **off live** (`security_auto_follow=false`, would-have audit §5) | signal, trust | 0 today. If enabled, arm ≤ 3 min later | If enabled, no auto-arm while a veto room is occupied, which is the intended "house careful" behaviour |
| Exterior person NM severity | `perimeter_alert.py:1660-1665` → `NM_HAZARD_EXTERIOR_PERSON_CONTEXTUAL_SEVERITY` `const.py:2314` | poll, trust (NM) | Fewer false CRITICAL pages during flaps (30% at W = 20, less at 3) | Fewer CRITICAL pages while the guest is home |
| Perimeter vehicle night alert | `perimeter_alert.py:2769`, `EXTERIOR_VEHICLE_ALERT_STATES` `const.py:2701` | poll, trust | Night-only, ≤ 3 min | Held while a veto room is occupied (intended) |
| Comfort-fan AWAY veto | `fan_veto.py:60` | poll, trust | ≤ 3 min | Fans not vetoed on the occupant (intended) |
| HVAC pre-conditioning `is_unoccupied` | `hvac_predict.py:446` | poll | ≤ 3 min | Same as HVAC |
| Optimizer posture gate | `optimization.py:3661` | poll, advisory | ≤ 3 min | — |
| Someone-home binary sensor | `binary_sensor.py:2315` | display + HA automations (not enumerated, Rev 2) | ≤ 3 min | Reads home, which is correct |
| Energy offset reset | `energy.py:8144-8236` via `_get_house_state` `:8384` | poll | ≤ 3 min | — |
| Bayesian guest / routine forecaster / music / arrester sunset | `__init__.py:3313-3329`, `routine_forecaster.py:188`, `music_following.py:301`, `hvac_override.py:1010` | signal | Negligible | Negligible |
| Next-state / integration sensors | `sensor.py:6573`, `sensor.py:10326-10335` | display | — | — |
| PWA | `frontend-v3/assets/Home-*.js`, `Presence-*.js` | display | — | — |
| EVSE, battery | no subscription (R1 confirmed) | — | — | — |

**HVAC and the operator's "HVAC fast, house careful".**
- HVAC's own path (zone vacancy, fast exit timers, D5) is not touched.
- The cost is confined to the house-edge component: ≤ W = 3 min on the minority of zone-episodes it leads, and P3 shows departure timing unchanged at W = 3.
- A true exemption would mean HVAC reading an unguarded verdict. That is a second published state and a new consumer contract: new functionality, which the operator ruled out as frivolous. Offered as PICK 4 (§11), default **no split**.

---

## 4. Measure before build (done; read-only, 2026-10-18)
All numbers are from the holistic audit's P0–P3 sections (30 days to 10-18 07:30 CDT; ordinary = 09-18→10-13, 25.7 d; Jaya+guest = 10-14→10-18, 4.3 d). SH = an AWAY entry with someone home (sensor proxy, Kitchen excluded).

| Config | Ordinary SH/day (days > 1) | Jaya+guest SH/day | Genuine departures within 15 min (of 10) | Verified-empty absences swallowed / delayed (of 14) |
|---|---|---|---|---|
| Today | 2.53 (15) | 16.2 | 7 | 0 / 0 |
| A W=3 only | 1.13 (6) | 13.2 | 7 | 0 / 0 |
| A W=3 + GB1/GB2 | 0.97 (4) | 9.7 | 7 | 0 / 0 |
| **A W=3 + GB1/GB2 (8 h) + Jaya (16 h) — this plan** | **0.90 (4) upper / 1.71 (9) lower** | **5.3 / 5.8** | **7** | **0 / 1 (8 min)** |
| A W=5 + GB | 0.90 (3) | 8.1 | 6 | 0 / 0 |
| A W=10 + GB | 0.58 (2) | 6.5 | 0 | 0 / 0 |
| A W=5 + all 7 ZK/ZX rooms | 0.23 (0) | 1.16 | 1 (3 never AWAY) | 4 / 4 |

Upper and lower are the body-predicate bounds (§3.2). The plan's predicate sits near the lower bound.

**Probe gates already passed:**
- P1: the guest-room phantom rate is ~0.6 false holds/week upper bound, under the ~1/week gate.
- P3: Jaya Bedroom passes both control sets.

**One probe deliverable remains** (D0, re-run only): the scorecard after ship.

---

## 5. Marginal-benefit decomposition
- **A alone at W = 3** takes ordinary-day SH from 2.53 to 1.13 and costs no departure timing. That is most of the ordinary-day value, for one field, one knob and three conjuncts.
- **B (guest rooms)** adds 0.16/day on ordinary days and 3.5/day on guest days, for one helper and one conjunct on α. It is worth it only because a guest in a bedroom is the case the cameras cannot see at all.
- **B + Jaya** adds 0.07/day ordinary and ~4.4/day on "Jaya alone" days. The margin is small on ordinary days and large on the case that triggered the card. It costs 1 verified-empty delay of 8 min. The room is a config row, not code, so the operator can drop it with zero code: **kept, as a PICK**.
- **W > 3:** each extra minute buys ~0.03–0.1 SH/day and loses departures (W = 5 → 6/10, W = 10 → 0/10). Rejected under "HVAC fast".
- **All radar rooms:** −0.7 SH/day but 3 of 10 genuine departures never reach AWAY. Rejected; parked (§10).
- **Estimator / door tally:** no consumer needs a count above 1, and door attach is 29–31%. Parked (§10).

---

## 6. The goal, and the honest residual
Goal clause (1) of the holistic audit: **≤ 1 someone-home AWAY per day, and no AWAY over 10 min with a person in a still-holder or camera room.**

- **Ordinary days:** expected ≈ 1.7/day (0.90 is the unreachable upper bound). 4–9 of 26 days stay above 1. **NOT MET.**
- **Jaya+guest days:** ≈ 5.3–5.8/day. **NOT MET.**
- **Remaining misses by room** (P3 §5, ordinary days): Master Bathroom 17 (InvisOutlet, on the do-not-use list), Study A 14 (ZK phantom, the only live sensor), Master Bedroom 9 (swallowed a verified-empty absence), Ziri 8 (one 26.5 h run on 09-28), Study B 7, Living Room 5. On Jaya+guest days: Exercise Room 14 (ZK never on, motion-sourced), Living Room 6.

  These are sensor-quality problems, not inference problems. No veto on these rooms passes the controls.
- **Clause (2), departure within 15 min:** 7 of 10 today and 7 of 10 after this plan. **Already NOT MET before any change** (zone grace plus census/BLE latency ≈ 9 min median). Nothing here makes it worse; nothing here fixes it.
- **Clauses (3) and (4):** met, unchanged.

**What would move clause (1) further:** fixing the sensors in Study A, Master Bathroom and Exercise Room, then re-running P3 to admit those rooms to R. Each room is then a config row. That is the revival path in §10.

---

## 7. Deliverables

### D0 — Scorecard: P0 re-run 14 days after deploy (read-only probe, exit discriminator)
- Re-run the P0/P3 scripts (`scratchpad/p/`, `scratchpad/p3/`; **commit them to `scripts/probes/away_flap_scorecard/` in the build**, so the re-run does not depend on a session scratchpad) over the 14 days after restart. Use the exact stamp from `last_camera_body_source` recorder history. If the attribute is recorder-excluded, fall back to reporting both bounds.
- **Verify (discriminating):**

| Observation | Fix working | A broken (guard never holds) | A stuck (guard never releases) |
|---|---|---|---|
| Ordinary-day SH/day | ≤ 1.9 | ≥ 2.4 | — |
| Genuine departures within 15 min | ≥ 6 of 10 | — | ≤ 3 of 10 |
| AWAY entries with `t − last body < W` | 0 | > 0 | — |

- **Exit:** the cycle closes on this table written into the README. If SH/day > 1.9 or departures < 6/10, the card reopens.

### D1 — Camera-body stamp (producer)
- **Where:** in `_handle_census_update` (`presence.py:4739`), after `_face_recognized_count` is parsed (`:4765-4769`).
- **Write:** if W > 0 and (`_unidentified_count > 0` or `_face_recognized_count > 0`), set `self._last_camera_body_ts = dt_util.utcnow()` and `self._last_camera_body_source = "unidentified" if self._unidentified_count > 0 else "face"`.
- **One clock:** `dt_util.utcnow()` for the stamp and the elapsed computation, nowhere else (R2-04).
- **Boot:** seed `_last_camera_body_ts = dt_util.utcnow()` in setup (Rev 2 choice (a); RAM only, no Store). There is no stamp at the census seed `presence.py:2946/2958` (R1-04).
- **Tests:**
  - `test_body_stamp_set_on_unidentified_positive`
  - `test_body_stamp_set_on_face_positive`
  - `test_body_stamp_not_refreshed_by_ble_only_identity` (census = 1, unidentified = 0, face = 0 → no move)
  - `test_body_stamp_not_refreshed_by_zero`
  - `test_body_stamp_seeded_at_boot`
  - `test_no_stamp_written_when_W_zero`
- **Verify (discriminating):** a forgotten-phone replay (`census_count = 1` from BLE, cameras empty) reaches AWAY via α at B + W + ≤ 60 s. A stamp on `census_count` would never release.

### D2 — Guard A on the three branches (consumer)
- **Caller (`_run_inference`, `presence.py:5731`):**
  - Compute `away_camera_quiet = (W == 0) or (dt_util.utcnow() − self._last_camera_body_ts).total_seconds() >= W`.
  - Pass it as a new `infer()` kwarg `away_camera_quiet: bool = True`. The default keeps every existing caller and test byte-identical.
  - **Do NOT pass `now=` to `infer()`.** The live call `presence.py:6487` does not pass it today, and `infer` reads local `dt_util.now()` for hour windows (`:1112-1115`). This supersedes Rev 2's "pass `now`" instruction and removes a tz seam.
- **Placement (INV-ALREADY-AWAY, the main build trap):**
  - In each branch, keep the existing `if current_state == HouseState.AWAY: … return None` FIRST.
  - Then: `if not away_camera_quiet: <record hold>; fall through` (no return). Fall-through equals today's "this branch's conjunct was false" path.
  - **Do NOT add the guard to the branch's outer `if` condition.** For α that would make an already-AWAY house with `census_count > 0` (forgotten phone) fall through to `:1297` and return ARRIVING when a camera ghost moved `B`.
- **Hold record:** inside `infer()`, after the `:1124` reset, set `self._away_hold = "camera_recent"` and `self._away_hold_detail = {"branch": "nobody_home"|"active"|"lost_admitted…"}`. The first branch that is denied sets it (order: nobody-home, then α, then β).
- **No new timer.** Discharge is the 60 s periodic (`presence.py:2926-2930`).
- **Tests (framing-C anchors; each goes RED when its own site is neutered):**
  - `test_nobody_home_blocked_within_W`
  - `test_path_alpha_blocked_within_W`
  - `test_path_beta_blocked_within_W`
  - `test_away_at_exact_W_boundary` (`>=` → `>` goes RED)
  - `test_W_zero_byte_identical` (golden over the existing presence AWAY suites)
  - `test_periodic_discharges_at_B_plus_W` (inject the clock, call `_periodic_inference`, no sleeps)
  - `test_discharge_while_hysteresis_blocks`
  - `test_guard_ignored_when_already_away`
  - **`test_alpha_guard_never_produces_arriving_from_away`**: `current_state = AWAY`, census = 1 (BLE), body 30 s ago → `infer` returns None. Mutation: move the guard into the outer `if` → RED.
- **Config extremes:**
  - W = 0, W = 1800, W = 30 (below the 60 s tick).
  - `camera_input_degraded = True`.
  - A restart mid-window.
  - `away_confirmation_veto` switch OFF (α and β coerced off; the guard still applies to nobody-home).
- **Live:**
  - Every AWAY row in `house_state_log` comes ≥ W after the last body (D0 table).
  - During a hold, `away_hold = camera_recent` and `away_eligible_at` = B + W.

### D3 — Veto B on path α (extend the guest-room tracker)
- **Config (P7):** room options field `CONF_ROOM_AWAY_HOLD_MAX_H = "room_away_hold_max_h"`, rung 2. It sits in the room options step next to the guest-room flag (`config_flow.py:12509`) and in the matching config-flow step (`config_flow.py:2306-2337` area).
  - NumberSelector 0–24 h, step 1, default **0 = not a veto room (kill switch)**.
  - Label "Keep house Home while occupied (hours)". Help: "If this room's occupancy is trustworthy (a radar that holds a still person), the house won't go Away while it's occupied, for up to this many hours. 0 = off."
  - **Operator config action after deploy:** GB1 = 8, GB2 = 8, Jaya Bedroom = 16 (PICK 2).
- **Tracker extension (one loop, one listener, one dict):**
  - `_discover_guest_rooms` registers a room if `CONF_ROOM_IS_GUEST_ROOM` **or** `hold_max_h > 0`.
  - Each state dict gains `roles` ⊆ {`guest`, `away_veto`}, `hold_max_s`, and `occupied_since` (set on the first `on` edge, cleared on `off`/unavailable, boot-seeded from `last_changed` when `on`, **no residual clamp**: the cap must count the real run).
  - The listener `_handle_guest_room_occupancy_change` maintains `occupied_since` for every registered room, independently of the known-person logic, which stays guest-role only.
  - **Guest-gate fence (INV-GUEST-UNCHANGED):** `_guest_room_gate_armed` skips dicts without role `guest`. The same filter is applied in the boot-seed of `first_seen` and in the `presence.py:5677` loop. The builder must grep every reader of `_guest_room_state` (today `:5189, 5227, 5305, 5367, 5500, 5677, 7653`) and decide guest-only vs all per reader in the build notes.
- **Helper:** `_room_veto_holding(now) -> (room, age_s, cap_s) | None`. It returns the first room with role `away_veto`, `occupied_since is not None`, and `now − occupied_since < hold_max_s`. One clock: `dt_util.utcnow()`.
- **Consumer:** the caller passes `away_room_veto: bool = False` (default byte-identical) into `infer()`.
  - In α only, after the already-AWAY check, and after guard A: `if away_room_veto: self._away_hold = "room_veto"; fall through`.
  - Nobody-home and β are not given the conjunct. Their room terms already block (§2 INV-B note). Adding it would be a second, redundant mechanism.
- **Discharge:** room `off` → listener → `_run_inference("guest_room_occupancy")` (`:5401`, immediate). Cap expiry → the next 60 s periodic. A room that flaps on/off restarts `occupied_since`; the bound is per run (as measured in P3). Reviewer D: test whether a flapping phantom can hold indefinitely; that is the main falsification target of INV-DISCHARGE.
- **Tests:**
  - `test_alpha_blocked_while_veto_room_occupied`
  - `test_alpha_released_at_cap` (mutation: drop the cap comparison → RED)
  - `test_alpha_released_when_room_clears`
  - `test_veto_room_unavailable_does_not_hold`
  - `test_known_resident_in_veto_room_still_holds`
  - `test_non_guest_veto_room_never_arms_guest` (mutation: drop the role filter → RED)
  - `test_guest_room_with_hold_zero_unchanged`
  - `test_veto_ignored_when_already_away` (no ARRIVING)
  - `test_occupied_since_boot_seed_counts_real_run`
  - `test_options_round_trip_room_away_hold_max_h`
- **Live:** with Jaya Bedroom occupied and all phones away, `away_hold = room_veto`, `away_hold_room = Jaya Bedroom`, and the age and cap attributes are shown. No AWAY row lands while the hold age is under the cap.

### D4 — Observability (same cycle; existing sensor and device, one v8 card)
- **Engine labels:**
  - The nobody-home branch sets `_veto_path = "nobody_home"` when it fires (today `none`).
  - The guard and the veto set `_away_hold` / `_away_hold_detail` (D2, D3). Reset to `none` at the top of `infer()`.
  - Mirrored by the caller next to `:6518`.
- **Sticky reason:** on an accepted transition INTO AWAY (`presence.py:~6961`), set `_last_away_reason = <veto_path of that tick>` and `_last_away_at`.
- **Counters:**
  - `_away_entries_today` increments on the same accepted transition, with the midnight reset of `_count_transition` (`:7450-7470`).
  - It is hydrated at boot by the extended `count_house_state_changes_since(today_iso, state="away")` (P12; the kwarg defaults to None = today's query).
  - `_away_entries_today_someone_home_est` increments when, at entry, `any_zone_occupied` was True OR `now − B < AWAY_SOMEONE_HOME_EST_LOOKBACK_S` (rung 1 module constant 600 s, display only; a runtime analogue of P0's at-entry proxy).
  - It is **not hydrated** (resets on restart); the attribute `counts_since` says so.
  - `_away_holds_today` counts hold episodes (an edge of `_away_hold` from `none`).
- **Memory episode (P10):** `_blocked` becomes True also when `_away_hold != "none"` in a home-like state. `_veto_path_str` = `camera_recent` / `room_veto` for those. The payload shape is unchanged (the string value domain grows; P9 shows no value consumers).
- **Attributes added to `sensor.ura_presence_coordinator_presence_house_state`** (`sensor.py:5557`):
  - `last_away_reason`, `last_away_at`
  - `away_hold` (`none`/`camera_recent`/`room_veto`), `away_hold_room`, `away_hold_age_s`, `away_hold_cap_s`, `away_eligible_at`
  - `last_camera_body_at`, `last_camera_body_source`
  - `away_entries_today`, `away_entries_today_someone_home_est`, `away_holds_today`, `counts_since`
  - `away_camera_quiet_s` (the live W)

  These are attributes only, on the existing Presence device entity. No new entity.
- **v8 card (config, after deploy, snapshot first to `docs/ha-config-snapshots/lovelace_ura_v8_backup_<date>.json`):**
  - **Where:** one `sections` grid on the v8 Presence view, styled like the Energy view (P14).
  - **Heading:** "Away decisions", `heading_style: title`, icon `mdi:home-export-outline`.
  - **Hero:** a `custom:button-card` `template: hero` on the house-state sensor. `pv` = state; `label` = `away_hold` (with room and age/cap when held) or `last_away_reason` with its time; `variables.color` blue, orange while held.
  - **Markdown table:** AWAY today / someone-home estimate / holds today / last camera body (age + source) / W.
- **Tests:**
  - `test_nobody_home_sets_label`
  - `test_last_away_reason_sticky_across_ticks`
  - `test_away_entries_today_hydrated_from_db`
  - `test_count_since_state_kwarg_default_unchanged`
  - `test_blocked_episode_classifies_camera_recent_and_room_veto`
  - `test_sensor_exposes_away_attrs`
- **Live:**
  - After the first AWAY: `last_away_reason` ∈ {nobody_home, active, lost_admitted*}, never `none`.
  - `away_entries_today` equals `SELECT COUNT(*) FROM house_state_log WHERE state='away'` since local midnight.
  - The v8 card renders on phone width.

### D5 — Knob: guard window (rung 3)
- **Key:** `CONF_PRESENCE_AWAY_CAMERA_QUIET_S = "presence_away_camera_quiet_s"`, `DEFAULT_… = 180`.
- **Entity:** `number.ura_presence_coordinator_away_camera_quiet`, unique_id `f"{DOMAIN}_presence_away_camera_quiet_s"`, Presence Coordinator device, cloned from `FanInterferenceHoldNumber` (`number.py:3541`).
- **Range and persistence:** 0–1800 s, step 30. CM `entry.options` write-back, no RestoreEntity. Read fresh each `_run_inference`.
- **Why rung 3:** the operator tunes it by watching departures versus flaps (the P3 trade-off curve). **0 = off, today's behaviour.**
- **Name:** "Away camera quiet". Description: "How long the indoor cameras must see no one before the house can go Away. 0 = off."
- **Tests:** `test_away_camera_quiet_options_round_trip`, `test_away_camera_quiet_zero_disables`.
- **Live:** the entity exists at 180 and survives a restart.

### D6 — Docs (same commit as the build)
- PRESENCE state of play:
  - §2 gets the two new conjuncts.
  - §10 gains ledger rows C1/C3/C4 from Rev 2 and C10/C11 from Rev 3.
  - The gold-patterns index gains "room veto via guest-room tracker role".
- HVAC state of play: §2 `hvac.py:3260` → `:5184`; one line in §3.2 that the house AWAY edge is now guarded (≤ W) and zone vacancy is unchanged.
- Estimator plan: a note that `FLOOR_WINDOW_S` is NOT this knob.
- README with the D0 table written back.

---

## 8. Numbers and their knobs

| Number | Value | Rung | Why | Kill |
|---|---|---|---|---|
| W, guard window | 180 s | 3, Number on the Presence device | Live trade of flaps against departures | 0 = off |
| Per-room hold cap | GB1 8 h, GB2 8 h, Jaya 16 h | 2, room options | Per-room structure; the cap is set from each room's longest legitimate run (P1 p-max 762 min; Jaya 15.6 h) | 0 = not a veto room |
| Someone-home estimate lookback | 600 s | 1, module const | Display-only proxy; changing it should be reviewed against P0 | n/a |
| Discharge tick | 60 s | existing | Reused | — |

---

## 9. Non-goals, fences
- **No change to:** the census payload or clamp, the guest gate behaviour, β grace, hysteresis, HVAC code, the door tally, identity, or `census_snapshots` schema.
- **No HVAC split** (PICK 4).
- **No veto on:** nobody-home or β, or on rooms outside R.
- **No AWAY → ARRIVING from room occupancy** (INV-ALREADY-AWAY).
- **Fenced, unchanged, each with a test** (`test_override_away_not_guarded`, `test_restore_not_guarded`):
  - Operator override to AWAY via any of the three selects (`select.py:255-278`, `__init__.py:6195`, `presence.py:8013-8021`).
  - Boot restore `apply_restored` (`house_state.py:368-431`).
  - The cold-boot default `initial_state=AWAY` (HOUSE-STATE-SENSOR-BOOT-AWAY-DISPLAY-1).
- **Restart timing:** deploy follows the travel and sleep rules. One restart, in an awake window (`feedback_no_restart_during_sleep`).

## 10. Parked, with revival triggers
| Item | Why parked | Revival trigger |
|---|---|---|
| Census estimator (FLOOR, door tally T, guests-present flag) | No consumer needs a count above 1; door attach 29–31%; stuck-high FLOOR would block real AWAY | D0 shows SH/day > 1.9 with misses traced to rooms that cameras and radars cannot see, AND door attach ≥ 60% |
| Door tally as an AWAY veto | ~70% of crossings are unnamed residents | EGRESS-INTERIOR-COUNT-REINFORCE-1 attach ≥ 60%, measured |
| Veto on all radar rooms | P3: 3 of 10 departures never reach AWAY; Study A swallows verified-empty absences | A room passes P3's two control sets (0 C1 / ≤ 10 C2 min, 0 verified-empty swallowed). Then it is added by config only (rung-2 field), no code |
| **Study A sensor fix** (ZK holds an empty room: 696 of 2,781 control minutes; Athom dead; InvisOutlet on the do-not-use list) | Hardware/operator action, not code | **No card exists.** Orchestrator to mint `STUDYA-ZK-EMPTY-HOLD-1` (operator: re-aim/retune the ZK, or add a ZV/PIR witness; then re-run P3 for Study A). Sibling sensor findings to card the same way: Exercise Room ZK never on in 7.2 d (EXERCISE-ROOM-PRESENCE-MISCONFIG-1 is done, so this is a new finding); Master Bathroom has no trusted sensor |
| HVAC reads an unguarded verdict | New published state; HVAC cost at W = 3 measured as nil on departures | D0 shows a genuine departure where the zone stayed on comfort > 5 min solely because of the house-edge delay |
| Separate `_body_quiet_unsub` timer | 60 s periodic suffices | D0 shows a discharge later than B + W + 180 s |
| `face_recognized_count` column in `census_snapshots` | Schema change (Tier 2-DB); the attribute covers D0 | The recorder excludes the attribute, AND D0 needs the exact predicate |

## 11. Operator PICKs (defaults in bold)
1. **Guard window W:** **180 s** / 300 s (+0.07 SH/day better, −1 departure of 10) / 0 (guard off, veto only).
2. **Veto rooms and caps:** **GB1 8 h, GB2 8 h, Jaya Bedroom 16 h** / guest rooms only (drop Jaya: ordinary-day SH unchanged, guest-day SH 9.7 instead of 5.3) / none.
3. **Body predicate:** **unidentified OR face** (decided in §3.2; cannot cost departures beyond the measured bound) / unidentified only.
4. **HVAC split:** **no split; HVAC zone path unchanged, house edge ≤ W later** / build an unguarded HVAC read (new functionality; §10 trigger).
5. **Someone-home estimate on the sensor:** **at-entry proxy (any room occupied or a camera body ≤ 10 min)** / omit it and rely on the D0 scorecard only.
6. **Acceptance of the residual:** **accept ≈ 1.7/day ordinary and ≈ 5.5/day guest-only days as this cycle's outcome, with the Study A / Master Bathroom / Exercise Room sensor cards as the next lever** / hold the build until the sensor fixes land.

## 12. Claims found WRONG (Rev 3 additions; Rev 2 C1–C9 stand)
- **C10:** Rev 2 said the HVAC handler is at `hvac.py:5177`, and the HVAC doc §2 says `:3260`. It is at `hvac.py:5184` (subscribe `:1437`).
- **C11:** Rev 2 D2 said "pass `now` to `infer()`". The live call (`presence.py:6487`) passes no `now`. Passing a UTC `now` would shift the local hour windows. Rev 3 passes a precomputed boolean instead.
- **C12:** holistic audit §5.2 said clause (2) is "met" at W = 10. Refuted by P0: the audit measured the added delay, not exit→AWAY.
- **C13:** the holistic audit's helper "non-resident in guest room = … `not _is_known_person_in_room`" is the guest semantic. It is wrong for an AWAY veto, where a resident in the room is someone home (§3.3).

## 13. Tier
**Tier 3.** House state is a shared primitive with 13 consumer groups. The failure mode is one missed branch at a time seam, or a stuck hold. The operator called it "surgery on the house state". Required:
- **Two framing-disjoint plan reviews** of this Rev 3 (orchestrator dispatches).
- **Four build reviews:**
  - A: local correctness.
  - B: state-machine and lifecycle (INV-ALREADY-AWAY, the listener and teardown, hydration).
  - C: per-site source mutation over the anchors in D1–D4.
  - D: adversarial completeness against §2 (flapping veto room, `camera_input_degraded`, the kill-switch interplay, the guest-gate fence).
- **Orchestrator verification:** re-grep every `return HouseState.AWAY` and every `_guest_room_state` reader, and re-run one mutation.
- **Operator checkpoint before deploy.**
- **ura-super-builder.**

Rev 2 review dispositions still applied: R2-01 camera-only stamp; R1-01/R2-02 no timer; R1-02 consumer pricing (now §3.4); R1-03/R2-03 RAM-only boot seed; R2-04 one clock (refined by C11); R2-05 label set inside `infer()`; R2-06 mutation anchors; R1-07 fences; R2-07 knob ownership (new name per P8); R1-06/R2-08 estimator shrink (moot: knob not shared).

---

## 14. Self-check against the Tier-3 plan-review requirement (planner, not a substitute for the two reviews)
- [x] Institutional-context section with re-grepped file:line for every new piece; new functionality listed and justified (§1.2).
- [x] Falsifiable invariants with named break targets (§2).
- [x] Producer and consumer for the stamp, the veto bit and AWAY (§3); AWAY consumers re-grepped, including polling and display (§3.4).
- [x] Emission-site enumeration: three `return HouseState.AWAY` (grep-confirmed); seven `_guest_room_state` readers listed for the builder.
- [x] Every number on the knob ladder with its kill semantics (§8).
- [x] Acceptance criteria discriminate (D0 table: working / never holds / never releases).
- [x] Live checks per deliverable; a 14-day exit scorecard.
- [x] Non-goals and fences (§9); parked items with triggers (§10).
- [x] Goal residual stated as NOT met, with numbers (§6).
- [ ] **Open for the reviewers:**
  - (a) whether the v8 Presence view path is `presence` (the builder reads the live config before editing);
  - (b) whether `PresenceHouseStateSensor` attributes are recorder-excluded (affects D0's exact predicate);
  - (c) all HA automations reading the someone-home binary sensor are not enumerated (carried from Rev 2).
