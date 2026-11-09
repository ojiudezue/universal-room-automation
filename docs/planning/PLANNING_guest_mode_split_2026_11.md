# PLANNING: Split "visitors present" from GUEST; GUEST = sustained night occupancy of a guest room

**Card:** `GUEST-MODE-SPLIT-VISITORS-1` (`docs/planning/kanban.data.yaml:438`).
**Base:** `develop` @ `4b52c262` (v5.107.6); every `file:line` below re-read on that commit, 2026-11-09.
**Status:** rev 6 (2026-11-09). Exit rule: the number of empty nights that ends a stay now grows with the stay
(`min(GUEST_STAY_LOOKBACK_NIGHTS, qualifying nights so far)`), so a one-night visit ends after one empty night and a
long stay still needs three (§0.2, §5.5). The three faster exits the operator proposed all break the October stay
(§5.5). Builder delta against the rev 5 build `a05c628e`: §14.
Rev 5 (2026-11-09): entry rule changed to "sustained daytime occupancy + one qualifying night" on the
operator's 2026-11-09 follow-up (§0.1); replay re-run (§5.4); garage-lockout churn (build review B-M1) specified as
INV-LOCK-1 + D3 acceptance criteria (§3.3). Builder delta against the rev 4 build `3a37f0c2`: §13.
Rev 4 (2026-11-09) was rewritten on the operator's answers to the D0 §8 questions (below). Rev 4 plan review
(adversarial build-prediction, run by the planner) applied: §11. Earlier reviews: plan review 1 (completeness) →
rev 2, `docs/reviews/code-review/guest_split_plan_review_1.md`; plan review 2 (build-prediction) → rev 3,
`docs/reviews/code-review/guest_split_plan_review_2.md`. D0: `docs/planning/AUDIT_guest_split_d0_2026_11.md`.
**Tier:** D1 Tier 2. D2+D3+D4 **Tier 2-DB** (changes house state; standing rule `feedback_tier2db_minimum_arc`). §9.

## Operator answers 2026-11-09 (binding)

Verbatim: *"I think visitors present is high value. And I agree that wifi is deceptive and not reliable. Consider guest
as sustained occupancy at night of the designated guest rooms. They gotta sleep somewhere, right. This might mean
thinking of guest over longer timespans than we are now - which kind of matches the high bar anyway."*

Decisions taken from it:
1. **Ship `visitors_present` first** (D1). Display / advisory only; it never changes house state.
2. **WiFi is dropped from the GUEST rule entirely** (operator decision, not a deferral). The WiFi guest-device producer
   (rev 3 D1) is DROPPED. WiFi is also not a `visitors_present` leg: D0 §4 measured the guest-WiFi floor ≥ 1 for
   14.5-23.2 h of every no-guest day, so it would hold `visitors_present` on all day.
3. **GUEST entry = sustained NIGHT occupancy of a designated guest room over several nights**, not an instantaneous
   30-minute gate. The 30-minute room gate stays, demoted to a `visitors_present` leg.
4. Rev 3's two-leg design (room AND cam/WiFi) is WITHDRAWN. D0 measured its recall on the October stay at 1 of 16
   entry-days.

### 0.1 Operator follow-up 2026-11-09 (binding, rev 5)

Verbatim: *"It can be one night. That's legit. basically sustained occupancy during the day and an overnight should
suffice."* And on scanners: *"We don't know guests irk. So it will have to be sensor occupancy. Unless we ask guests
to authenticate. Which is not a bad idea. But not now."*

5. **Entry = sustained daytime occupancy of a guest room + ONE qualifying night in the same room** (§2.3). The rev 4
   "2 of the last 3 nights" entry rule is dropped. The exit rule (3 straight non-qualifying nights) is kept; the
   replay does not argue against it (§5.4).
6. **Identity is sensor-only.** Guests have no IRK, so nothing identifies a guest. BLE only SUBTRACTS residents
   (`person_visits`). Guest self-authentication is parked as `GUEST-SELF-AUTHENTICATION-1` (revival: operator asks).

### 0.2 Operator follow-up 2026-11-09 (rev 6)

Relayed by the orchestrator: the rev 5 exit ("3 failing nights in a row", `GUEST_STAY_LOOKBACK_NIGHTS` 3) is too
slow. Candidates offered: (a) exit after 1 night below a lower "empty" threshold (hysteresis, e.g. < 0.05);
(b) (a) plus the following day also empty, so the exit lands mid-day; (c) exit after a full day and night with zero
guest-room occupancy. Brief: pick the fastest exit that never drops mid-stay.

7. **Premise correction (data wins).** The brief says the stay's nights ranged 0.14-0.82. They did not: four stay
   nights read **0** in both guest rooms (10-13, 10-14, 10-16, 10-17; §5.2), and all of day 10-14 read 0.00 in both
   rooms. Any exit that fires on one or two empty nights, or on one empty day + night, ends the October stay on 10-14
   or 10-15. None of (a), (b), (c) holds the stay (§5.5).
8. **The October tail is already one day.** Under rev 5 the stay ends on the morning of 10-19; the only active day
   after the stay is 10-18. Nights 10-16 and 10-17 were already empty while the guest was still in the house (GB2
   day 0.46 and 0.22), so the guest-room signal cannot see the departure any earlier.
9. **What rev 6 changes.** The slow exits are the SHORT visits: each one-night entry held 3 days (09-10..12,
   09-16..18). Rev 6 scales the exit length with the stay: min(`GUEST_STAY_LOOKBACK_NIGHTS`, n) empty nights, where
   n = qualifying nights in the stay so far. A one-night visit ends after one empty night (1 day active), a two-night
   visit after two, a stay of three or more nights after three (unchanged). The October stay is identical to rev 5;
   10-19..11-08 stays at 0.

## Deliverables and verdicts

| # | Deliverable | Verdict | Gate |
|---|---|---|---|
| D0 | Read-only probe (done, audit doc) + rev 4 night-occupancy replay (done, §5) | DONE | `D0 GATE: GO` (§5.3) |
| D1 | `binary_sensor.ura_presence_coordinator_visitors_present` (display only) | **BUILD now** | none beyond plan review |
| D2 | Night-stay producer: per-night guest-room occupied fraction from the URA DB → stay latch | **BUILD** (after D1 ships; same build as D3) | D0 GO |
| D3 | GUEST composition: stay latch replaces the 30-min room gate; GUEST yields to SLEEP at night | **BUILD** (with D2) | D0 GO; operator checkpoint before deploy |
| D4 | Trip-wire: stay latch held too long | **BUILD** (with D2/D3) | — |
| D5 | Docs (presence state of play, identity manual, card) | **BUILD** (same commits) | — |
| ~~W~~ | WiFi guest-device producer (rev 3 D1) | **DROPPED** (operator decision 2 above) | — |
| ~~—~~ | Rev 3 two-leg gate, cam latch, WiFi hold trip-wire | **WITHDRAWN** (D0 recall 1/16) | — |

Rev 3 → rev 4 numbering: rev 3 D2 (`visitors_present`) is now D1; rev 3 D3 (gate) is now D3 with a different rule;
rev 3 D4 (WiFi hold trip-wire) is replaced by a stay-length trip-wire.

---

## 0. What exists today, and what changes

Today the only automatic GUEST entry is the 30-minute guest-room gate (`presence.py:6594`, `guest_armed =
guest_room_gate_armed` at `:6601` in HOME_* and `:6609` in GUEST). Path A (`_guest_gate_armed`, census unidentified)
arms nothing; it only sets `guest_reason` / confidence (`:6628-6669`). INV-GUEST-LEAD (`PLANNING_guest_census_correctness.md:63`).

D0 measured this rule against the real October stay (09-27 to 10-17): 35 entries on 16 of 21 days, 28 of them between
06:00 and 10:59, average 32 minutes each, GUEST on only 2 of 21 nights. Short morning episodes are not "a guest is
staying with us." Since 10-18: zero entries in 22 days.

After this plan:
- **GUEST** (high bar) = a guest STAY (rev 5): on some night N a designated guest room R was occupied by someone
  other than a BLE-located resident for at least `GUEST_NIGHT_MIN_FRACTION` of the night window, AND the same room
  was so occupied for at least `GUEST_STAY_DAY_MIN_FRACTION` of the day window before that night
  (`GUEST_STAY_DAY_START_HOUR` → `sleep_start_hour`). Once on, the stay holds until min(`GUEST_STAY_LOOKBACK_NIGHTS`,
  n) nights in a row fail the night test, n = qualifying nights in the stay so far (rev 6, §2.3). The house shows GUEST by day and evening during a stay and goes to SLEEP at
  night as usual.
- **`visitors_present`** (low bar) = GUEST, OR the stay is active, OR the 30-min guest-room gate, OR Path A
  (unidentified bodies on camera ≥ 300 s).

---

## 1. Institutional context verified

Read completely before writing: `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (all 860 lines; §10 ledger
1-29), `docs/architecture/SENSOR_FLEET_CLASSES.md`, `docs/Coordinator/IDENTITY_FUSION_CAMERAS_MANUAL.md`, and
`docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` (all 726 lines; GUEST is an HVAC input: preset map and hold
tables; no HVAC code changes and no §10 claim is re-asserted).

Ledger items that bind this plan:
- Presence §10 #29: there is no GUEST → SLEEP edge (`house_state.py:116-121`, enforced `:219-221`). An armed gate holds
  GUEST all night. A multi-night stay latch would therefore block SLEEP for the whole stay unless the hold yields at
  night. D3 makes it yield (§2.3).
- Presence §10 #28 and identity manual §5.5(a): a face label never actuates. No face input here.
- Presence §10 #15 / SENSOR_FLEET_CLASSES rule 3: the guest rooms' still-person holder is the Matter MS600 occupancy
  (`binary_sensor.mmwave_motion_lux_matter_wifi_guestbedroom{1,2}_occupancy`, filed `presence_sensors`, live config
  2026-11-09). It holds a sleeping body, which is what makes night occupancy measurable.

### 1.1 Prior-art scan: REUSE or BUILD per piece

| Piece | Verdict | Existing symbol (file:line on `4b52c262`) |
|---|---|---|
| Designated guest rooms + their occupancy entity | **REUSE** | `_discover_guest_rooms` `presence.py:5620` (reads `CONF_ROOM_IS_GUEST_ROOM` `const.py:463`, resolves `binary_sensor` by unique id `{entry_id}_occupied` `:5669-5672`, stores `_guest_room_state` / `_guest_room_entity_to_name`). D2 adds the room's `entry_id` to what it records (it already iterates the entry) |
| 30-min guest-room gate (now a visitors leg) | **REUSE unchanged** | `_guest_room_gate_armed` `presence.py:5941-5996`; listener `_handle_guest_room_occupancy_change` `:5793`; boot seed `:5689-5775` (`GUEST_BOOT_SEED_MIN_RESIDUAL_S` `const.py:483`); threshold `CONF_ROOM_GUEST_OCCUPANCY_THRESHOLD_MIN` `const.py:464` (live 30 both rooms) |
| Resident-in-room exclusion | **REUSE (same data, durable form)** | Live gate uses `_is_known_person_in_room` `presence.py:5859` (PersonCoordinator `location`, sticky `GUEST_KNOWN_STICKY_S` 120 `const.py:495`). The night rule reads the durable record of the same fact: `person_visits` rows (`database.py:995`, writer `log_person_entry` `database.py:3890`, room_id = room display name), padded by `GUEST_KNOWN_STICKY_S` |
| Room occupied seconds in a window from the DB | **REUSE + small refactor** | `Database._occupied_seconds_between(db, room_id, start_utc, end_utc)` `database.py:3611` (entry/exit pairing, episode cap `OCC_EPISODE_MAX_S` 43200 `const.py:2240`, look-back, naive-UTC stored clock). Callers `:3692`, `:8478`. D2 extracts its episode list (`_occupied_episodes_between`) so the sum stays byte-identical and the resident subtraction can work on intervals |
| DB read context | **REUSE** | `Database._db_read` `database.py:761`; presence gets the DB at `hass.data[DOMAIN]["database"]` (`presence.py:2727`) |
| Night window | **REUSE** | House sleep window on the inference engine: `self._inference_engine.sleep_start_hour` / `.sleep_end_hour` (`presence.py:1506-1508`, engine `:1055-1061`), fed from CM options `CONF_SLEEP_START_HOUR` / `CONF_SLEEP_END_HOUR` (`__init__.py:3748-3757`, `const.py:3519-3523`, defaults 23/6; **live 22 / 6**, CM entry 2026-11-09). Not the per-room sleep-protection hours (`const.py:1560-1561`, GB1 21-7, GB2 22-7): those drive room lighting, and the stay is a house concept |
| Day window + day fraction (rev 5) | **REUSE reader, NEW knobs** | Same `get_guest_room_night_fractions` span API (rev 4 build `3a37f0c2`, `database.py:3697`), which already takes an arbitrary `windows` list: day windows are just more windows. Knobs `GUEST_STAY_DAY_MIN_FRACTION` / `_DAY_START_HOUR` / `_DAY_BEFORE_NIGHT` are NEW: `grep -rn -e GUEST_STAY_DAY -e DAY_START_HOUR -e DAY_MIN_FRACTION -e day_start_hour` over the package (develop and `3a37f0c2`) returns nothing. The engine has `evening_start_hour` / `night_start_hour` (`presence.py:1019-1020`) but no day-start hour; `sleep_end_hour` (6) as the start gives the same replay list (§5.4), but the operator asked for a separate window knob |
| Sleep-hour test for the night yield | **REUSE** | `StateInferenceEngine._is_sleep_hour` `presence.py:1465-1470` |
| Stay-scaled exit length (rev 6) | **EXTEND walk, NEW knob** | The exit already lives in the walk loop (`presence.py:6226-6233` on `a05c628e`, `elif active and q == 0` at `:6231`). Rev 6 adds a loop-local count and one `min()`; no new state. Knob `GUEST_STAY_EXIT_SCALES_WITH_STAY` is NEW: `git grep -n -i -e EXIT_SCALE -e GUEST_STAY_EXIT -e exit_nights -e SCALES_WITH a05c628e -- custom_components docs/planning` and the same on `develop` return nothing; memory bodies `project_presence_guest_latch_and_veto_gap`, `feedback_tier2db_minimum_arc` mention the guest exit only as the GUEST→HOME_NIGHT edge |
| GUEST composition | **EXTEND** | `presence.py:6586-6613`; `infer()` exit `:1399`, entry `:1425-1432` |
| Path A (cam visitors leg) | **REUSE unchanged** | `_guest_gate_armed` `presence.py:5998-6076` (HOME_* only; `CONF_GUEST_MODE_PERSISTENCE_SECONDS` / `_REQUIRE_CONFIDENCE` `const.py:4245`/`:4248`, live 300 s / medium) |
| `guest_reason` | **EXTEND** | `presence.py:6615-6637`, published `sensor.py:5836` |
| Stay basis attribute (live oracle) | **BUILD** (attribute only) | No equivalent: `house_state_log` has no reason column (`database.py:1494`) |
| `visitors_present` entity | **BUILD** | grep `visitor` over the package: one comment, `config_flow.py:5141`. `URAUnexpectedPersonSensor` (`binary_sensor.py:1889`, instantaneous `unidentified_count > 0`) keeps its own meaning. Shape copied from `GuestModeBinarySensor` `binary_sensor.py:2415-2450` (polled, Presence Coordinator device) |
| Trip-wire | **REUSE pattern** | `_check_sleep_raw_hold` `presence.py:4173`, fires `_stuck_signal_nm.fire_stuck_signal` (`:4235-4237`); called at `:7086` |
| Kill switch for all guest detection | **REUSE** | `switch.ura_presence_coordinator_guest_detection` → `_guest_detection_enabled` (`switch.py:3899`, field only) |
| Confidence 0.9 / 0.95 / override | **REUSE unchanged** | `presence.py:6647-6669`, override `:7234-7236` (guarded on `guest_room_gate_armed`) |

Greps run 2026-11-09 on `4b52c262`: `_guest_room_gate_armed|_guest_gate_armed(|guest_armed|_guest_reason|_disarm_guest_gate|_guest_room_state`
over `domain_coordinators/presence.py` (sites in §4); `HouseState.GUEST|"guest"` over the package (§3.3); `FAN_TRUST_STATES|HVAC_EVIDENCE_RULE_STATES|HVAC_NIGHT_HOLD_STATES`
(`hvac_const.py:1067`, `:1097`, `:1082`); `sleep_start_hour|sleep_end_hour|CONF_SLEEP_START_HOUR` (night window);
`_occupied_seconds_between|_db_read|FROM person_visits|log_person_entry` over `database.py`; `visitor|night_stay|guest_stay|GUEST_NIGHT|GUEST_STAY`
over the package and `const.py` (no hits for the new names); `guest_armed = guest_room_gate_armed` over `quality/tests`
(4 source-grep anchors, §D3).

### 1.2 Prior plans, audits, memory consulted

| Doc | Use |
|---|---|
| `AUDIT_guest_split_d0_2026_11.md` | Stay dates, entry table, cam-leg recall (1/16), WiFi FP (every day), cam-leg fire rates (§5 Q4: 2.41/day post-stay) |
| `PLANNING_guest_census_correctness.md` (INV-GUEST-LEAD :63, INV-GUEST-NO-RESIDENT :69) | INV-GUEST-NO-RESIDENT is carried into the night rule (resident time subtracted). INV-GUEST-LEAD is replaced (§2.5) |
| `AUDIT_guest_mode_fp_2026_10_17.md` | 10-17 entry "plausibly correct"; GUEST consumer effects |
| `PLANNING_presence_guest_latch_and_veto_gap.md`, memory `project_presence_guest_latch_and_veto_gap` | Exit-before-sleep ordering (`presence.py:1399`) that D3's night yield relies on |
| `PLANNING_house_away_flap_untracked_occupant.md` Rev 4 (parked (B) guest-room AWAY veto) | Trigger "guest accuracy becomes a priority" has fired. Not folded (AWAY side). The stay latch is the natural input to that veto later: §8 |
| Memory `project_operator_travel_2026_10_15` | A guest was home 10-14/10-15; the guest rooms read 0 / 0.57 those nights (§5.2) |
| Memory `feedback_marginal_benefit_pushback`, `feedback_suppression_needs_discharge`, `feedback_measure_before_build`, `feedback_portability_imperative` | §2.4, D4, §5, the `person_visits` clock rule (§2.2) |

### 1.3 Config-first

No setting expresses "a guest is staying." Raising the room threshold (`CONF_ROOM_GUEST_OCCUPANCY_THRESHOLD_MIN`) to
e.g. 300 min would approximate "slept there" but resets on any break in occupancy, ignores the night, and still flips
GUEST per episode. Code is needed.

**Guest Bedroom 2 scanner (operator-owned).** GB2 has no BLE scanner of its own today (`scanner_areas:
['guest_bedroom_2_closet']`, live config); the operator will build one (ESP32-C3) after about 11-16. Until then a
resident in GB2 is not BLE-located there, so their time counts as non-resident occupancy. **The rule must not depend on
that scanner, and it does not:** the replay (§5) was run with no GB2 scanner on any night, and residents in
`person_visits` for GB2 numbered 0 on every night measured. When the scanner lands, it can only remove resident time
(fewer qualifying nights), never add.

---

## 2. Design

### 2.1 The night fraction (D2 producer)

For each designated guest room R and each night N (the night that starts on local date N):
- Window W(N) = [local N at `sleep_start_hour`, local N+1 at `sleep_end_hour`) from the engine's house sleep window
  (live 22:00 → 06:00). If `sleep_start_hour <= sleep_end_hour` (a non-wrapping window, e.g. 1 → 6), W(N) = [local N+1
  at start, local N+1 at end). Length is the real elapsed time (DST nights are 7 h or 9 h).
- Occupied episodes of R in W(N): `occupancy_events` entry/exit pairs for `room_id = <R's entry_id>`, via the extracted
  `_occupied_episodes_between` (same pairing and caps as `_occupied_seconds_between`).
- Resident intervals: `person_visits` rows with `room_id = <R's room name>` overlapping W(N), each widened by
  `GUEST_KNOWN_STICKY_S` on both sides.
- `frac(R, N)` = seconds of (occupied episodes minus resident intervals) inside W(N), divided by |W(N)|.
- Night N **qualifies** iff max over guest rooms of `frac(R, N)` ≥ `GUEST_NIGHT_MIN_FRACTION`.
- A night with no DB evidence for any guest room (no rows, DB error) does not qualify (fails toward no GUEST).

**Day fraction (rev 5).** Same reader, same resident subtraction, same pad, different window:
- Day window Dy(N) = [the latest local time at hour `GUEST_STAY_DAY_START_HOUR` that is at least 1 h before the
  start of W(N), start of W(N)). Live (22 → 6, H = 10): local N 10:00 → local N 22:00, 12 h. For a non-wrapping sleep
  window (start 1): local N 10:00 → local N+1 01:00. Length is real elapsed time.
- `dfrac(R, N)` = seconds of (occupied episodes minus padded resident intervals) inside Dy(N), divided by |Dy(N)|.
- Night N is **entry-qualified** iff for one room R both `frac(R, N)` ≥ `GUEST_NIGHT_MIN_FRACTION` AND
  `dfrac(R, N)` ≥ `GUEST_STAY_DAY_MIN_FRACTION` (same room; the replay gave the same day list for "any room", §5.4).
  With `GUEST_STAY_DAY_BEFORE_NIGHT` False, the day after the night also counts: N is also entry-qualified when
  `frac(R, N)` and `dfrac(R, N+1)` pass, judged at the walk after night N+1 (one day later; no new scheduling).
- Identity is sensor-only (operator 2026-11-09): guests carry no IRK. BLE never adds guest time; it only removes
  resident time.

### 2.2 Clocks (portability; both are traps)

- `occupancy_events.timestamp` is naive UTC (`datetime.utcnow()`, docstring `database.py:3617-3619`; D0 verified
  against the 10-17 audit). Bounds passed to `_occupied_episodes_between` are **naive UTC** datetimes. Passing a
  tz-aware datetime makes `.isoformat()` emit `+00:00`, and the string comparison against stored naive values is then
  wrong.
- `person_visits.entry_time` / `exit_time` are written with `datetime.now()` (`database.py:3908`): naive **process-local**
  time. On this HAOS host that is UTC (live rows read 07:16 while the local clock read 02:38 CST, 2026-11-09). On
  another host it may be local. The docstring of `get_closed_person_visits` (`database.py:8559-8560`) says "naive
  LOCAL"; that is true only where the process TZ is local. **Rule:** convert W(N) bounds to the writer's clock with
  `datetime.fromtimestamp(bound.timestamp())` (naive process-local, the exact inverse of `datetime.now()` on any host).
  Never `dt_util.as_local`, never `utcnow()` for this table. Contradiction reported in §10.

### 2.3 The stay latch, and how it drives GUEST (D2 + D3)

**Latch.** `PresenceCoordinator._guest_stay_active: bool`, recomputed (never incremented) from the DB:
- Walk nights from N0 = (last completed night) − `GUEST_STAY_REPLAY_NIGHTS` + 1 to the last completed night, starting
  with the latch False. For each night N, with Q = the number of qualifying nights (night test only) among the last
  `GUEST_STAY_LOOKBACK_NIGHTS` nights ending at N:
  - latch False and N is entry-qualified (§2.1, night + day, same room) and Q ≥ `GUEST_STAY_ENTRY_NIGHTS` → True
    (default `GUEST_STAY_ENTRY_NIGHTS` = 1, so the entry-qualified night alone suffices; 2 restores a rev-4-style
    second-night guard, §5.4);
  - latch True and the last X nights ending at N are all non-qualifying → False, where (rev 6)
    X = min(`GUEST_STAY_LOOKBACK_NIGHTS`, n) when `GUEST_STAY_EXIT_SCALES_WITH_STAY` is True, else
    X = `GUEST_STAY_LOOKBACK_NIGHTS` (rev 5: 3 straight misses);
  - n = the stay's qualifying-night count, a local of the walk: set to Q at the night the latch turns on (so it
    counts the entry night and any qualifying nights already in the lookback; Q ≤ L), plus 1 for each later night
    that qualifies (night test only). It is reset when the latch turns off and never decremented. X ≥ 1 always
    (n ≥ 1 at entry, L ≥ 1);
  - the exit is tested on nights AFTER the entry night only (the entry night itself qualifies, so it cannot exit);
  - otherwise unchanged.
  - With `GUEST_STAY_DAY_BEFORE_NIGHT` False, "N is entry-qualified" also accepts (night N−1, day N), so the walk
    reads one extra day window.
- "Last completed night" = the latest night N whose window end is ≤ now.
- The walk is deterministic in the DB contents, so a restart reproduces the same latch (no Store, no RAM history).
- **When it runs:** (a) once after setup, once the DB is available (setup must not await it); (b) on the first inference
  tick whose local time is ≥ today's window end and whose stored `_guest_stay_evaluated_for` is not today's date. The
  tick only SCHEDULES the async walk (tracked task; one in flight at a time; cancelled at teardown); the walk sets
  `_guest_stay_active`, `_guest_stay_basis`, `_guest_stay_evaluated_for`, `_guest_stay_since`, then calls
  `_run_inference("guest_stay_refresh")`.
- **Guest-detection switch OFF:** the composition treats the latch as False (§2.3 composition). The walk still runs and
  publishes the basis (display), so turning the switch back on restores the current stay without waiting a night.
- **`GUEST_NIGHT_STAY_RULE_ENABLED` False:** no walk is scheduled; the latch stays False; the composition is today's.

**Composition (D3), with `GUEST_NIGHT_STAY_RULE_ENABLED` True and `_guest_detection_enabled` True:**

| House state | Rev 4 `guest_armed` | Today |
|---|---|---|
| HOME_DAY / HOME_EVENING / HOME_NIGHT | `stay` (the latch) | `room` (30-min gate) |
| GUEST | `stay AND NOT engine._is_sleep_hour(local hour)` | `room` |
| other | False | False |

`room` and Path A are still EVALUATED exactly where they are today (HOME_* for both; GUEST for `room`), because
`visitors_present` and `guest_reason` read them. They no longer feed `guest_armed` while the rule is on.

**Why the GUEST hold yields at night.** `infer()` checks the GUEST exit (`presence.py:1399`) before the sleep branch
(`:1404`). With `guest_armed` False at a sleep hour, a GUEST house exits to `_time_based_home(hour)` (HOME_NIGHT), and
the next tick's sleep branch proposes SLEEP (HOME_NIGHT → SLEEP is valid). In the morning: SLEEP → WAKING → HOME_DAY
(`:1411-1418`), then the entry branch (`:1425`) returns GUEST because the latch is still on. No state-machine edge is
added (presence §10 #29 stays true). Daily cost: two extra transitions per stay day (GUEST → HOME_NIGHT at
`sleep_start_hour`, HOME_DAY → GUEST after waking), each above the 300 s GUEST minimum dwell (`house_state.py:137`).

Without the yield, an active stay would hold GUEST every night for weeks and every SLEEP consumer (HVAC night tail, fan
night trust, NM CRITICAL exterior severity, lock regime unless its GUEST toggle is on) would be off for the whole
stay. D0 §3 measured that today GUEST covers 2 of 21 stay nights; the yield keeps nights as they are now.

**Entry/exit discharges** (suppression-needs-discharge): the latch ends after X straight non-qualifying nights
(rev 6: X = min(3, n); a one-night visit is off on the morning after the first empty night, a stay of 3+ qualifying
nights on the morning after the third). Also: guest-detection switch OFF, manual
override, and GUEST → AWAY (valid edge; the latch stays on, so the house re-enters GUEST after ARRIVING → HOME_*).
Phantom room occupancy has no automatic discharge, so D4 pages instead.

### 2.4 Marginal-benefit check (before the spec)

**Rev 5 (supersedes the "2 of 3" choice below).** The operator ruled one night legitimate. The day test is the
simplest addition that fits his words ("sustained occupancy during the day and an overnight"): one more window
through the same reader, no new writer, no new state. What the replay says it buys (§5.4): stay day 2 (09-28) is
caught (rev 4 lost days 1 and 2); 10-19..11-08 stays at 0. What it costs: four more pre-stay day-ranges become active
(08-25..08-27, 09-10..09-12, 09-16..09-18, and 08-25..09-02 now starts earlier), all single-night or
earlier-visit shapes the operator has not labelled. The day test does NOT filter those: the October guest was out of
the room by day (stay day fractions 0.00-0.21), so any day threshold low enough to admit the stay (≤ 0.21) also admits
every one-night case (day fractions 0.24-0.38). The day test's real job is to reject a night-only sleeper with no
daytime presence (09-04: night 0.51, day 0.02) and phantom night holds. The rev 4 analysis below is kept as the record
of why the second-night guard exists; it survives as the knob `GUEST_STAY_ENTRY_NIGHTS` (default 1, set 2 to restore it).

**Rev 4 analysis (kept for the record):**

- **Simplest version that fits the operator's words:** "a guest room was mostly occupied last night" (K=1 of L=1).
  Replay at F=0.25: 15 of 21 stay days, and 9 days outside the stay, including the single 15-hour 09-15 night. Requiring
  2 of the last 3 nights adds one constant and removes the one-night cases (a resident who fell asleep in GB2 once,
  a one-night visitor). It also lifts stay coverage to 19 of 21 days, because 3 nights bridge the gaps the stay really
  had (10-04, 10-10, 10-13/14). Margin pays: same ingredients (one DB read per day), no new writer, no new state class.
- **Rejected: a Store-persisted RAM accumulator** (per-tick sampling of the occupancy entity + `_is_known_person_in_room`).
  It matches the live gate's exclusion exactly, but it needs a new persisted store, loses partial nights to restarts
  (11 HA starts in the 7 days to 11-09, D0 §0), and could not be checked against history. The DB walk IS the replay,
  so the acceptance fixture and production are the same code.
- **Rejected: keep the 30-min gate as a parallel GUEST entry ("room OR stay").** The operator's words point the other
  way, and the gate's 35 stay entries were short morning episodes (D0 §7).
- **Rejected: a GUEST → SLEEP edge** instead of the night yield. It changes the house-state machine (`VALID_TRANSITIONS`)
  for every caller; the yield uses existing edges only.
- **Parked: arrival-day GUEST.** Rev 5 sees a guest from the morning after their first night (day 2, 09-28 in the
  replay). The arrival day itself (09-27) cannot be caught by any night rule: the night has not happened yet.
  `visitors_present` covers it. Revival trigger: the operator says the arrival day matters after one real stay under
  the new rule (`GUEST-GATE-DOOR-IDENTITY-1` / `GUEST-SELF-AUTHENTICATION-1` are the candidate inputs).

### 2.5 Falsifiable invariants

- **INV-STAY-1 (entry).** With `const.GUEST_NIGHT_STAY_RULE_ENABLED` True: every ACCEPTED `transition(GUEST)` from
  HOME_DAY / HOME_EVENING / HOME_NIGHT happens on a `_run_inference` tick where `_guest_stay_active` is True and
  `_guest_detection_enabled` is True. `_guest_stay_active` is True only if some completed night N in the replay window
  had ONE guest room R with non-resident occupied time ≥ `GUEST_NIGHT_MIN_FRACTION` of W(N) AND ≥
  `GUEST_STAY_DAY_MIN_FRACTION` of Dy(N) (or of Dy(N+1) when `GUEST_STAY_DAY_BEFORE_NIGHT` is False), with ≥
  `GUEST_STAY_ENTRY_NIGHTS` night-qualifying nights among the `GUEST_STAY_LOOKBACK_NIGHTS` ending at N, per the DB,
  and no run of X non-qualifying nights since (X per §2.3, rev 6). The only other writers of GUEST
  from HOME_* are the manual override (`select.py:280`, `__init__.py:6200`, `presence.set_house_state_override`
  `presence.py:8663`) and restart restore (`manager.py:688-719`).
  *Corollaries:* a daytime visit of any length with no night in the room never enters GUEST (naps, office use); a
  night in a guest room with less than `GUEST_STAY_DAY_MIN_FRACTION` of the day before in THAT room never enters
  GUEST (09-04 shape); day in GB1 + night in GB2 never enters; Path A and face labels never enter GUEST; WiFi is read
  nowhere. One night WITH a sustained day DOES enter (operator ruling 2026-11-09).
  *Falsifiers to try:* a 6 h afternoon nap in GB1 two days running (no night time); a 15 h night with day 0.02
  (09-04 shape, must not enter) and with day 0.38 (09-15 shape, must enter at defaults, must not at
  `GUEST_STAY_ENTRY_NIGHTS` 2); day in GB1 + night in GB2; a resident with a BLE fix in GB1 all day and night
  (resident time subtracted from BOTH windows); a restart at 05:59 and at 06:01 on a qualifying morning; DST
  nights and DST days; a DB read that raises; the switch toggled off and on mid-stay; a non-wrapping sleep window
  (start 1, end 6) and `GUEST_STAY_DAY_START_HOUR` ≥ the sleep start hour; a guest room un-flagged mid-stay.
- **INV-STAY-2 (no all-night GUEST).** With the rule on, a non-overridden GUEST never holds past the first inference
  tick at or after max(`sleep_start_hour` + `_guest_persistence_seconds` (the S9 exit veto, live 300 s), GUEST entry +
  300 s minimum dwell `house_state.py:137`). The 30 s census tick drives inference; the reviewer measures the real
  inter-tick gap rather than assuming it.
- **INV-STAY-3 (kill switch).** With `GUEST_NIGHT_STAY_RULE_ENABLED` False, `guest_armed`, `guest_reason`,
  `_d5_guest_confidence` and the `infer()` result are byte-identical to `develop` @ `4b52c262` for every input, and no
  DB walk is scheduled.
- **INV-LOCK-1 (rev 5, build review B-M1).** With the guest-night toggle on (`DEFAULT_SECURITY_LOCKOUT_ENGAGE_ON_GUEST_SLEEP`
  True, `const.py:3625`) and the house in GUEST when the sleep window opens, the garage lockouts are LOCKED once, at
  the guest-night clock (`security_lock_regime._on_guest_clock`, `security_lock_regime.py:796-811`), and are NOT
  unlocked by the night yield: no `_release` and no `lock.unlock` write from the GUEST → HOME_NIGHT edge or the
  HOME_NIGHT → SLEEP edge inside the sleep window. Over the whole night from the clock to the first WAKING / HOME_DAY /
  ARRIVING / resident arrival, each lockout entity sees exactly one `lock.lock` write and zero `lock.unlock` writes.
  *Falsifiers:* GUEST at 21:59 with S9 persistence holding GUEST to 22:05, HOME_NIGHT dwell 120 s, then SLEEP; the
  same with the toggle off (no GUEST-night engage; SLEEP engages once as today); GUEST → HOME_NIGHT at 22:05 then the
  house stays HOME_NIGHT (no SLEEP) until 06:00; a manual override GUEST → HOME_NIGHT at 23:00 (a real home edge
  with reason `guest_night`: held too, by design, since the regime cannot tell the two apart; WAKING / HOME_DAY /
  resident arrival still release); GUEST → HOME_EVENING inside the window (not possible from infer(); override only:
  releases as today).
- **INV-STAY-4 (rev 6, exit length).** With the rule on and `GUEST_STAY_EXIT_SCALES_WITH_STAY` True, the walk turns
  the latch off at night N iff the latch was on before N and the last min(`GUEST_STAY_LOOKBACK_NIGHTS`, n) nights
  ending at N are all non-qualifying, n per §2.3. Consequences that must hold: (i) a stay with ≥ L qualifying nights
  never ends on fewer than L straight empty nights (the October stay keeps rev 5's day list exactly: 09-28..10-18);
  (ii) a stay with n < L qualifying nights ends on the morning after its n-th straight empty night; (iii) the latch
  never turns off on the entry night; (iv) with the knob False the walk is byte-identical to `a05c628e`.
  *Falsifiers to try:* one entry-qualified night then empty (must be off after 1 empty night); entry at
  `GUEST_STAY_ENTRY_NIGHTS` 2 (n starts at 2, so 2 empty nights); a qualifying night inside the lookback before the
  entry night (09-04/09-05 shape: n = 2 at entry); a long stay with two isolated empty nights (10-13/10-14 shape: must
  hold); L = 1 (X = 1 always); L = 7 with n = 2 (X = 2); a restart between the first and second empty night (the walk
  recomputes n from the DB, so the result is the same); a stay that exits and re-enters inside the replay window (n
  restarts at the re-entry Q, not the old count).
- **INV-VIS-1 (D1 is display).** D1 adds no call to `_guest_room_gate_armed`, `_guest_gate_armed`, `transition`, or any
  `_guest_*` state writer; `guest_armed`, `guest_reason`, confidence and the `infer()` result are byte-identical to
  base with D1 applied alone.
- Carried: INV-GUEST-NO-RESIDENT (now also for the night fraction, via `person_visits`), I-D1 exit-before-sleep
  ordering. INV-GUEST-LEAD is REPLACED by INV-STAY-1 (operator decision 3).

---

## 3. Producer and consumer checks

### 3.1 Producers

| Value | Arithmetic | Dependencies and their health (2026-11-09) |
|---|---|---|
| `frac(R, N)` | §2.1 | `occupancy_events` for GB1/GB2: rows through 11-01 (GB1) / 11-06 (GB2), entry/exit balanced (GB1 290/289, GB2 308/290 since 09-01; the unbalanced tail is capped by `OCC_EPISODE_MAX_S`). Occupancy itself rides the Matter MS600 (holds a still sleeper, SENSOR_FLEET_CLASSES §Meross). `person_visits`: Bermuda-written 30 s fragments (GB1 229 rows since 09-01; GB2 0; "GB2 Bathroom" 141 is a different room name) |
| Phantom risk | a guest-room occupancy held by a running fan or a stuck radar counts as occupancy | Presence doc §6 item 3 / HVAC §4.2b: GB1/GB2 have no fan-immune witness, so a paused room with a running fan can hold occupancy until the 4 h stuck rule or the P24 failsafe. Measured: max night fraction 0.02 over 10-18..11-08 (21 nights), so not occurring now. D4 pages if it does |
| Stay latch | §2.3 walk | the above + the engine sleep window (CM options, live 22/6) |
| `visitors_present` | GUEST OR stay OR `room` OR `cam` (§D1) | `room`: 30-min gate, D0 §2 (post-stay: 1 qualifying run in 22 days). `cam`: Path A, D0 §5 (post-stay 2.41 fires/day, median 6 min, longest 219 min; 11-02..11-08: 3 fires in 7 days). So expect `visitors_present` to flash on for a few minutes about 0.4-2.4 times a day with no visitors, almost all from `cam`. Display only |

### 3.2 `visitors_present` consumers

None this cycle besides the entity (display). Not read by `infer()`. No NM (parked, §8).

### 3.3 GUEST consumers (re-verified on `4b52c262`; rev 5: one changes code, the SC lock regime row)

Direction of change: GUEST becomes a daytime state for the length of a stay (weeks), absent at night, instead of short
daytime episodes. Fewer GUEST episodes outside stays (the 30-min gate no longer enters).

| Consumer | file:line | Trust / display | Effect |
|---|---|---|---|
| HVAC preset map guest → `home` | `hvac_const.py:1293` | trust | daytime of a stay: `home` preset (same as HOME_DAY maps today; no change in practice) |
| HVAC hold table: evidence rule only in `home_day`/`home_evening`; GUEST uses the legacy tail | `hvac_const.py:1097`; `hvac_zones.py` (HVAC doc §3.1) | trust | during a stay, every zone releases on the slower legacy day tail instead of the evidence clock. More comfort, some energy. Accepted; named in the README |
| HVAC night tail (`sleep`/`waking`) and fan night trust (`home_night`/`sleep`/`waking`) | `hvac_const.py:1082`, `:1067` | trust | unchanged at night (the yield keeps SLEEP) |
| Arrester hold-preserving states | `hvac_const.py:229` | trust | `guest` preserves holds: across the two daily GUEST edges an immune hold survives |
| HVAC Custom Preset Ranges `house_state == "guest"` | `preset_overrides.py:115-148` | trust | only fires in GUEST; now fires through stay days |
| Security armed-state map guest → ARMED_HOME | `security.py:183` | trust | state-driven arming not live (10-17 audit) |
| SC lock regime GUEST-in-sleep-window engage | `security_lock_regime.py:764-766` (`_HOME_STATES` release), `:776-779` (guest engage), `:796-811` (`_on_guest_clock`), `:1409-1412` (`guest_night_ended` predicate) | trust (lock) | **Rev 5 correction (build review B-M1).** Rev 4 said "GUEST is no longer present in the sleep window". False for the first ~5 min: the night yield proposes HOME_NIGHT at `sleep_start_hour`, but the S9 exit persistence holds GUEST `_guest_persistence_seconds` (300 s). So at 22:00:00 `_on_guest_clock` sees GUEST and LOCKS (`REASON_GUEST_NIGHT`); at ~22:05 GUEST → HOME_NIGHT hits the `_HOME_STATES` branch and UNLOCKS; after the 120 s HOME_NIGHT dwell, SLEEP LOCKS again. Three actuations and a ≥ 2-min unlocked gap every stay night. **Fix (D3, lock regime, option (b) of the review):** in `on_house_state_changed`, `new == "home_night"` while `self.reason == REASON_GUEST_NIGHT` and `_in_sleep_window(cfg)` does not release; it keeps the reason and records `guest_yield_hold`. The later SLEEP edge sets reason `sleep` and its engage is a no-op on already-locked entities (`engage_predicate` returns `lockout_locked`, `:1417-1419`). WAKING / HOME_DAY / HOME_EVENING / ARRIVING / resident arrival release as today. INV-LOCK-1. Option (a) (yield `_guest_persistence_seconds` early so GUEST is gone by the clock) was rejected: the operator's rule is "lock once, at the guest-night clock", and (a) moves the lock to the SLEEP edge (22:02+) and couples presence timing to a lock consumer |
| NM exterior-person severity | `const.py:2677`, `:2761` | trust (severity) | daytime of a stay: MEDIUM instead of the home_day level; nights unchanged |
| Bayesian learning suppressed in GUEST | `__init__.py:3278` | trust (learning) | suppressed by day for the whole stay (the guest's pattern is not learned as the house's) |
| Occupancy-anomaly suppressed in GUEST | `binary_sensor.py:3570` | display | suppressed by day during a stay |
| `binary_sensor.ura_presence_coordinator_guest_mode` | `binary_sensor.py:2450` | display | on by day during a stay |
| `guest_reason` on `sensor.ura_presence_coordinator_presence_house_state` | `sensor.py:5836` | display | new value `night_stay:...` (§D3) |
| Wall-panel brightness automation (HA YAML) | `automations.yaml:8270` (10-17 audit) | cosmetic | follows GUEST |

No URA lighting reader of GUEST (grep). `HOUSE_STATE_OVERRIDE_OPTIONS` (`const.py:3666`) and
`HOUSE_STATE_TRIGGER_VALUES` (`const.py:4123`) list `guest` but are option lists, not readers.

---

## 4. Decision-site enumeration

From `grep -n "_guest_room_gate_armed\|_guest_gate_armed(\|guest_armed\|_guest_reason\|_d5_guest_confidence" presence.py`
on `4b52c262`. The builder re-runs it; this list is a hypothesis.

| # | Site | D1 | D3 |
|---|---|---|---|
| S1 | `presence.py:6586-6601` HOME_* branch | read locals only | `guest_armed = self._compose_guest_gate(HOME, room=..., stay=...)` |
| S2 | `:6602-6609` GUEST branch | read locals only | `guest_armed = self._compose_guest_gate(GUEST, ...)` with the night yield |
| S3 | `:6610-6613` else | read locals only | unchanged (False) |
| S4 | `:6615-6637` `guest_reason` | unchanged | `night_stay:<rooms>` first when the stay is active (rule on); rest unchanged |
| S5 | `:6647-6669` confidence + D2 canary | unchanged | values unchanged; canary condition `guest_armed and not guest_room_gate_armed` gated to rule OFF (with the rule on it is the normal case) |
| S6 | `:7046` `infer(guest_gate_armed=guest_armed)` | unchanged | unchanged (anchor) |
| S7 | `infer()` `:1399` exit, `:1425` entry | unchanged | unchanged; the yield comes from S2 |
| S8 | `:7234-7236` confidence override on `guest_room_gate_armed` | unchanged | unchanged: a stay entry logs the engine's 0.8 unless the 30-min gate is also armed that tick (0.9). Recorded in §10 |
| S9 | `:7333-7382` `guest_exit` veto (`_guest_persistence_seconds`) | unchanged | unchanged. Read during review: when `infer()` proposes GUEST → HOME_* it stamps `_guest_exit_quiet_since` and suppresses the exit until `_guest_persistence_seconds` (live 300 s) of consecutive proposals (`:7345-7366`). So the night yield leaves GUEST at the first tick ≥ `sleep_start_hour` + `_guest_persistence_seconds`, then SLEEP on a later tick. This is the INV-STAY-2 bound |
| S10 | `:7596-7605` accepted-transition branch, `_disarm_guest_gate` | unchanged | unchanged |
| S11 | per-tick stay refresh scheduler (new, next to `_check_sleep_raw_hold` call `:7086`) | — | D2 |
| S12 | `_discover_guest_rooms` `:5620` | — | also record `entry_id` per guest room (D2 needs it for `occupancy_events`) |
| S13 | `sensor.py:5836` area | — | publish `guest_stay_active`, `guest_stay_since`, `guest_stay_basis` |
| S14 | override writers `select.py:280`, `__init__.py:6200`, `presence.py:8663` | — | not gated (by design) |
| S15 | restore `manager.py:688-719` | — | not gated; a restored GUEST with the latch False exits on the first tick after the walk |
| S16 | teardown `presence.py:8227` | — | cancel the in-flight walk task |

No `await` sits between the guest block (`:6563`) and `transition()` (`:7543`); the first await after the decision is
`:7605`. D3 adds no await in that span (the latch is read, never fetched, on the decision path).

---

## 5. D0 results and the rev 4 replay

### 5.1 Method (read-only, 2026-11-09)

`ssh ha "python3 -"`, sqlite `mode=ro` on the live URA DB. Scripts:
`/private/tmp/claude-501/-Users-okosisi-Code-universal-room-automation/75cc297f-1426-4620-b7aa-da058bc0fab0/scratchpad/r4_replay.py`
(per-night fractions), `r4_rule.py` (parameter sweep), `r4_pick.py` (chosen point) in the same directory. Rooms GB1
`01KE2CP30H1251F10K5R1YJRCC`, GB2 `01KCYSBVA2RMB5C3F1Z90F9X72`. Nights 08-25 to 11-08 (76). Window 22:00 → 06:00
America/Chicago (the live CM window). Occupancy = raw entry/exit pairs; resident time = `person_visits` rows for the
room name ±120 s, read as UTC (this host's process clock, §2.2). The build moves the fraction logic into
`database.py`; the scripts are the fixture (§D2 test).

### 5.2 Per-night guest-room fraction (max of GB1, GB2; resident time subtracted)

| Period | Nights | Fractions |
|---|---|---|
| Stay 09-27 .. 10-17 | 21 | 0.72, 0.66, 0.82, 0.65, 0.50, 0.36, 0.58, **0.14**, 0.51, 0.30, 0.60, 0.25, 0.37, **0.15**, 0.25, 0.37, **0, 0**, 0.57, **0, 0** |
| After the stay 10-18 .. 11-08 | 22 | max **0.02** |
| Of which 11-02 .. 11-08 | 7 | all **0.00** |
| Before the stay 08-25 .. 09-26 | 33 | GB1 0.90-0.95 on 08-25, 08-28, 08-29, 08-30; GB2 0.51 on 08-25, 09-04, 09-05; GB2 1.00 on 09-15 (cluster B); else ≤ 0.42 |

The resident subtraction changed no night by more than 0.01 (residents were BLE-located in a guest room at night
rarely, and never in GB2). 10-13/10-14 read 0 although a guest was home from 10-14 (memory); where she slept is
unknown (D0 §1). The 2-of-3 lookback carries the stay across those nights.

### 5.3 Rule replay and the gate (rev 4; the entry rule is superseded by §5.4)

Sweep over F ∈ {0.2, 0.25, 0.3, 0.4, 0.5} and (K of L) ∈ {1/1, 1/2, 2/2, 2/3, 2/4, 3/4}. Plateau: F 0.20-0.30 with
2 of 3 gives the same stay result. F = 0.25 sits in the middle of the plateau (nights at exactly 0.25 do not change
the outcome anywhere on it). F ≥ 0.4 drops to 12-13 stay days.

**Chosen: F = 0.25, enter on 2 of the last 3 nights, exit after 3 straight non-qualifying nights.**

| Window | Required | Result (stay latch active, day after the night) |
|---|---|---|
| **October stay 09-27 .. 10-17** | GUEST | **19 of 21 days** (09-29 → 10-17). Lost: 09-27 (arrival) and 09-28 (one night seen). Tail: 10-18 (one day after departure) |
| **11-02 .. 11-08 (no guest)** | no GUEST | **0 of 7 days** |
| 10-19 .. 11-08 (no guest) | — | 0 of 21 days |
| Before the stay | operator to label | active 08-28 → 09-02 (GB1 nights 0.90-0.95) and 09-06 → 09-08 (GB2 09-04/09-05 0.51). Not 09-15 (one night). D0 counted 11, 8, 7, 7, 6, 5 GUEST entries/day on 08-25..08-30 under the old rule; these look like an earlier real visit, unconfirmed |

Raw occupancy without the resident subtraction gives the identical day list.

Today's rule on the same windows, for contrast: 11-02..11-08 also 0 GUEST entries (D0 §2), so that window does not
separate the two rules; the stay does: today 1113 GUEST minutes over 16 days, all short daytime episodes, vs the
whole daytime of 19 days under the new rule.

**D0 GATE: GO** (rev 4 rule; operator answers 2026-11-09 resolve D0 §8 items 1 (dates: 09-27..10-17 used), 4 (rev 3
recommendation superseded by a new rule) and 5 (WiFi devices moot: WiFi dropped). Items 2 (per-entry labels) and 3
(where the guest slept 10-14/15) are not needed for this rule; the late-August / early-September active days are listed
for the operator to label after the build, not as a gate).

### 5.4 Rev 5 replay: day + one night (2026-11-09, read-only)

**Method.** Same DB, rooms, night window and resident subtraction as §5.1, plus the `OCC_EPISODE_MAX_S` 12 h episode
cap that production applies (rev 4's script lacked it; the 09-15 night reads 0.95 instead of 1.00, nothing else
moves). Day windows H → 22:00 local for H ∈ {6, 8, 10, 12, 14}. Scripts in the scratchpad directory
`/private/tmp/claude-501/-Users-okosisi-Code-universal-room-automation/75cc297f-1426-4620-b7aa-da058bc0fab0/scratchpad/`:
`r5_replay.py` (runs on HA via `ssh ha "python3 -"`, prints per-night and per-day fractions per room as JSON;
output saved as `r5_data.json`), `r5_rule.py` (rule + sweep), `r5_pick.py` (fine sweep, `GUEST_STAY_ENTRY_NIGHTS`
2 variant, entry/exit log). "Active day" = the latch is on that local day.

**Day fractions on the stay are LOW.** The October guest slept in GB2 then GB1 but was rarely in the room by day:
`dfrac` (10 → 22) on stay nights was 0.00-0.21 (09-27 GB2 0.21 is the arrival day; 09-29 0.21; most days ≤ 0.10).
The pre-stay one-night cases had MORE daytime: 09-05 GB2 0.24, 09-09 GB2 0.33, 09-15 GB2 0.38.

**Chosen point: F_night 0.25, `GUEST_STAY_DAY_MIN_FRACTION` 0.10, `GUEST_STAY_DAY_START_HOUR` 10, day before the night,
same room, `GUEST_STAY_ENTRY_NIGHTS` 1, exit after 3 straight non-qualifying nights.**

| Window | Required | Rev 5 result | Rev 4 (2 of 3) |
|---|---|---|---|
| **Stay 09-27 .. 10-17** | GUEST | **20 of 21 days**, from **09-28 (day 2)**. Lost: 09-27 (arrival; no night yet). Tail: 10-18. Entry on the morning after night 09-27 (GB2 night 0.72, day 0.21); exit on the morning after night 10-18 | 19 of 21, from 09-29 |
| **10-19 .. 11-08** (no guest) | no GUEST | **0 of 21** (max night 0.02, max day 0.08) | 0 of 21 |
| **11-02 .. 11-08** (no guest) | no GUEST | **0 of 7** | 0 of 7 |
| 08-24 .. 09-02 (GB1 heavy day + night) | operator to label | active **08-25 → 09-02** (entry after night 08-24: GB1 night 0.65, day 0.60; GB1 day 0.6-1.0 every day to 08-30). Data starts 08-24, so 08-25 is the first day the replay can show | 08-28 → 09-02 |
| 09-04 .. 09-08 (GB2 nights 0.51, 0.51) | operator to label | active **09-06 → 09-08** (entry after night 09-05: night 0.51, day 0.24). Night 09-04 alone did NOT enter (day 0.02) | 09-06 → 09-08 (same) |
| 09-09 (GB2 night 0.38, day 0.33) | operator to label | active **09-10 → 09-12** (one night; NEW in rev 5) | not active |
| 09-15 (GB2 night 0.95, day 0.38) | operator to label | active **09-16 → 09-18** (one night; NEW in rev 5) | not active |

Each one-night entry holds 3 days because the exit needs 3 straight misses. Unlabelled stretches are listed for the
operator, not treated as errors: if they were visitors, rev 5 is right on them.

**Sweep (stay days / 10-19..11-08 / 11-02..11-08; same room, day before night):**

| `GUEST_STAY_DAY_MIN_FRACTION` | H = 6 | H = 8 | H = 10 | H = 12 | H = 14 |
|---|---|---|---|---|---|
| 0.0 | 20 / 0 / 0 (+09-05 entry) | 20 / 0 / 0 | 20 / 0 / 0 | 20 / 0 / 0 | 20 / 0 / 0 |
| 0.10 | 20 / 0 / 0 | 20 / 0 / 0 | **20 / 0 / 0** | 20 / 0 / 0 | 20 / 0 / 0 |
| 0.20 | 18 / 0 / 0 | 18 / 0 / 0 | 20 / 0 / 0 | 20 / 0 / 0 | 9 / 0 / 0 |
| 0.21 | — | — | 18 / 0 / 0 (first active 09-30) | — | — |
| 0.30 | 8 / 0 / 0 | 0 | 0 | 0 | 0 |
| ≥ 0.40 | 0 | 0 | 0 | 0 | 0 |

- **Plateau:** at H = 10, day fraction 0.03-0.20 gives (fine sweep 0.0, 0.03, 0.05, 0.10, 0.15, 0.20, 0.21, 0.22,
  0.25); H 6-12 at 0.10 give the identical day list. 0.10 sits mid-plateau; the arrival-day
  margin is 0.21 − 0.10. At ≥ 0.22 (H = 10) the October stay is NEVER entered, because the only day before a
  qualifying night with that much in-room time is the arrival day. A higher day bar is a recall cliff, not a dial.
- **Variants at H = 10, day 0.20:** any room (day in one guest room, night in either) = identical list. Day AFTER the
  night allowed (`GUEST_STAY_DAY_BEFORE_NIGHT` False) = 19 of 21 (from 09-29) and adds 10-19 (the morning after
  departure). Raw occupancy (no resident subtraction) = identical list. Night fraction 0.20-0.50 does not change the
  stay result at day 0.10. Exit after 2 misses ends some pre-stay holds a day earlier; after 4 adds a day; 3 kept.
- **`GUEST_STAY_ENTRY_NIGHTS` 2 (second-night guard) on top of the day test:** stay 18 of 21 from 09-30 at day 0.10
  (19 from 09-29 at day 0.0),
  0 / 0 post-stay, and the one-night entries 09-10..12 and 09-16..18 disappear (and 08-25 becomes 08-26).

**Does one night let a resident through (nap, office use)?**
- A daytime nap or office use with NO night in the room: never (the night test is mandatory). Same as rev 4.
- A resident who spends the day AND sleeps one night in a guest room: YES, at every day threshold that keeps the
  October stay. The day test cannot separate them in this house: the stay's arrival day read 0.21 and the one-night
  cases read 0.24-0.38, so the order is inverted. The only resident filter is the BLE subtraction, and it is blind in
  GB2 until the operator's GB2 scanner lands (no `person_visits` rows for GB2 on any night; §1.3). In GB1 the
  subtraction works (a resident with a phone in GB1 is removed from both windows).
- **Knob that prevents it:** `GUEST_STAY_ENTRY_NIGHTS = 2` (rung 1). It removes every single-night entry in the
  replay and costs two stay days at day 0.10 (18 vs 20; enters 09-30). No day-fraction setting does it. The GB2 scanner, when it
  lands, removes resident time in GB2 for a resident carrying a phone, which is the right fix for this shape at
  `GUEST_STAY_ENTRY_NIGHTS = 1`.
- Default stays at 1 (operator ruling: one night is legit). If the operator labels 09-09 or 09-15 as a resident,
  turn it to 2 (reviewed one-line change) or wait for the GB2 scanner.

**D0 GATE (rev 5): GO.** The stay is caught from day 2, both no-guest windows stay at 0. The pre-stay stretches are an
operator labelling question, not a gate.

### 5.5 Rev 6 replay: faster exits (2026-11-09, read-only)

**Method.** Same data as §5.4 (`r5_data.json`, no new DB read), entry fixed at the rev 5 defaults (night 0.25, day
0.10 from 10:00, same room, day before, `GUEST_STAY_ENTRY_NIGHTS` 1). Script
`/private/tmp/claude-501/-Users-okosisi-Code-universal-room-automation/75cc297f-1426-4620-b7aa-da058bc0fab0/scratchpad/r6_exit.py`
(imports the `r5_rule.py` entry predicate; run `python3 r6_exit.py r5_data.json`). It reproduces the rev 5 list that
`test_replay_fixture_day_list` pins at `a05c628e`, so the harness matches the build. "Night" = max over GB1/GB2 of the
night fraction; "day" = max over both rooms of the 10:00-22:00 fraction (and 06:00-22:00 for (c)).

**The data the stay actually has** (night = 22:00 that date → 06:00; day = 10:00-22:00 that date; max of both rooms):

| Date | 10-12 | 10-13 | 10-14 | 10-15 | 10-16 | 10-17 | 10-18 |
|---|---|---|---|---|---|---|---|
| Night | 0.37 | **0** | **0** | 0.57 (GB2) | **0** | **0** | 0 |
| Day | 0.04 | 0.03 | **0.00** | 0.00 | 0.46 (GB2) | 0.22 (GB2) | 0.02 |

Day 10-15 before the GB2 night 0.57 read 0.00, so once the latch drops at 10-13/10-14 the day test blocks re-entry for
the rest of the stay.

| Exit rule | October stay 09-27..10-17 | Mid-stay drop? | Tail after 10-17 | 10-19..11-08 |
|---|---|---|---|---|
| rev 5: 3 straight nights < 0.25 | 20/21 (from 09-28) | no | 10-18 (1 day) | 0/21 |
| (a) 1 night < 0.05 (also < 0.02, < 0.10: same) | 16/21 | **yes**: off from 10-14, never re-enters (lost 10-14..10-17) | none | 0/21 |
| (b) night < 0.05 + next day < 0.05 (also 0.02, 0.10: same) | 17/21 | **yes**: off at 22:00 on 10-14 (lost 10-15..10-17) | none | 0/21 |
| (c) day + night exactly 0 (also < 0.02) | 17/21 | **yes**: day 10-14 + night 10-14 all zero (lost 10-15..10-17) | none | 0/21 |
| (a2) 2 nights < 0.05 | 17/21 | **yes** (10-13 + 10-14) | none | 0/21 |
| (a3) 3 nights < 0.05 (hysteresis only) | 20/21 | no | 10-18 | 0/21; pre-stay holds get LONGER (08-25..09-12 as one run) |
| **rev 6: min(3, n) nights < 0.25** | **20/21 (from 09-28), identical to rev 5** | **no** | **10-18 (1 day)** | **0/21** |

Rev 6 full day list at the defaults: active 08-25..09-02, **09-06..09-07**, **09-10**, **09-16**, 09-28..10-18; off
10-19..11-08. Against rev 5 that removes 09-08, 09-11, 09-12, 09-17, 09-18 (5 days, all short unlabelled visits). At
`GUEST_STAY_ENTRY_NIGHTS` 2: active 08-26..09-02, 09-06..09-07, 09-30..10-18.

**Variant rejected: n starting at 1 instead of Q.** At `GUEST_STAY_ENTRY_NIGHTS` 2 it splits the August run
(08-26, then 08-28..09-02), because the second qualifying night that let the latch on is not counted. n = Q at entry
does not split anything.

**Why no faster exit exists on this signal.** The stay contains a 2-night, 1-day blackout (night 10-13, day 10-14, night
10-14 all ~0) followed by a real night (10-15, GB2 0.57). Any rule that ends a long stay in under 3 empty nights, or on
one empty day + night, ends it there. The departure-side tail is already 1 day because the stay's last two nights
were empty too. A faster departure would need a different signal (a door crossing, the guest's car, an operator
"guest left" action), not a different threshold on guest-room occupancy.

**Marginal-benefit check (rev 6).** Simplest version: rev 5 unchanged (0 risk, short visits hold 3 days). Rev 6 adds
one walk-local integer and one `min()`: no new state, no new writer, no new read, no Store, deterministic on restart.
Benefit: 5 fewer GUEST days in the 76-night replay, all on short visits, and a one-night visitor no longer leaves the
house in GUEST for two more days (GUEST masks nothing at night because of the yield, but it changes the daytime state
every consumer sees). Cost, named: a visit whose second night reads empty (dropout, guest slept elsewhere) ends after
one day and re-enters only on a later night with a qualifying day before it. In the October stay the first empty night
came after 7 qualifying nights, so this did not bite. Margin pays. The hysteresis threshold (a3) is rejected: it does
not hold the stay any better and makes short holds longer.

**D0 GATE (rev 6): GO.** Stay unchanged, no-guest windows at 0, short visits shorter.

---

## 6. Deliverables

### D1 — `visitors_present` (BUILD now, Tier 2)

- After the guest block's `guest_reason` / confidence (`presence.py` after `:6669`), compute from the EXISTING locals
  only: `legs = {"room": guest_room_gate_armed, "cam": unid_gate_armed and const.VISITORS_CAM_LEG_ENABLED}`;
  `self._visitors_present = (current_state == HouseState.GUEST) or any(legs.values())`; `self._visitors_legs = legs`;
  `self._visitors_since` = UTC time of the last False → True edge (None when off). After D3: add `"stay":
  self._guest_stay_active and self._guest_detection_enabled` to `legs`.
- Entity: `binary_sensor.ura_presence_coordinator_visitors_present`, unique id `{DOMAIN}_visitors_present`,
  Presence Coordinator device (copy `GuestModeBinarySensor` `binary_sensor.py:2415-2450`: polled, no dispatcher).
  Reads `hass.data[DOMAIN]["coordinator_manager"].coordinators.get("presence")` (as `sensor.py:5760`); missing → off.
  Attributes: `legs` (in `_unrecorded_attributes`), `since`.
- Outside HOME_* / GUEST both legs are False (not evaluated there, unchanged), so `visitors_present` is off in SLEEP /
  AWAY until D3 adds `stay`.
- Guest-detection switch OFF: both gate methods already return False (`presence.py:5957-5959`, `:6019-6021`), so the
  legs are False; `visitors_present` follows GUEST only (an override into GUEST still reads on).

**Acceptance criteria**
- **Verify (INV-VIS-1):** call counts of `_guest_room_gate_armed` / `_guest_gate_armed` per tick are identical with and
  without D1 (spy test); `guest_armed`, `guest_reason`, confidence and the `infer()` result match a 200-tuple seeded
  golden generated on `4b52c262` (state, room gate, unidentified count, confidence, persistence elapsed, override,
  detection switch).
- **Verify:** `room` alone → on, house not GUEST; `cam` alone → on, house not GUEST; neither and not GUEST → off;
  house GUEST by override with the switch OFF → on.
- **Discriminates:** under the fix, a 30-min unknown occupant in GB1 gives `visitors_present` on with `legs.room` True
  and the house still HOME_* **only after D3**; with D1 alone, the house enters GUEST as today AND `visitors_present`
  is on (D1 must not change that). A build that wired `visitors_present` into `infer()` would change the D1-alone
  result; the golden catches it.
- **Test:** `test_guest_split_visitors.py::test_display_only_golden`, `::test_gate_call_counts_unchanged`,
  `::test_room_leg`, `::test_cam_leg`, `::test_cam_leg_const_off`, `::test_off_outside_home_guest`,
  `::test_switch_off_follows_guest_only`, `::test_since_edge`, `::test_unique_id_and_device`.
- **Live:** the entity resolves by unique id `universal_room_automation_visitors_present`; `legs` has `room` and `cam`;
  over the first 24 h after restart the recorder shows it on only in short episodes (expect 0-3 episodes, minutes long;
  each with `legs.cam` or `legs.room` true at the time).

### D2 — Night-stay producer (BUILD, with D3; Tier 2-DB)

- `database.py`: extract `_occupied_episodes_between(db, room_id, start_utc, end_utc) -> (list[(start, end)],
  had_evidence)` from `_occupied_seconds_between`; `_occupied_seconds_between` becomes `sum` over it (byte-identical,
  its two callers untouched). New public `async def get_guest_room_night_fraction(room_entry_id, room_name, start_aware,
  end_aware, resident_pad_s) -> tuple[float, bool]` under `_db_read`: occupancy bounds as naive UTC, `person_visits`
  bounds via `datetime.fromtimestamp(x.timestamp())` (§2.2), subtract padded resident intervals, return (fraction,
  had_evidence). Read-only; raises on DB error (caller catches).
- `presence.py`: `_discover_guest_rooms` also records `{room_name: entry_id}` (S12). New
  `async def _refresh_guest_stay(self, now)` runs the §2.3 walk over `GUEST_STAY_REPLAY_NIGHTS` nights. Reads: ONE
  occupancy episode read and ONE `person_visits` read per guest room covering the whole span, bucketed per night in
  Python (not rooms × nights queries). The DB API is therefore span-shaped:
  `get_guest_room_night_fractions(room_entry_id, room_name, windows: list[(start_aware, end_aware)], resident_pad_s)
  -> list[(fraction, had_evidence)]`, replacing the single-window signature above. It writes `_guest_stay_active`, `_guest_stay_since`
  (UTC time the latch last turned True in the walk's own timeline = window end of the night that turned it on),
  `_guest_stay_basis` (list of the last `GUEST_STAY_LOOKBACK_NIGHTS` nights: `{night, room, fraction, day_fraction,
  qualifies, entry_qualified}`; rev 5 adds `day_fraction` = `dfrac` of the same room's day before, and
  `entry_qualified`),
  `_guest_stay_evaluated_for` (local date). Any exception → log WARNING once per day, latch False, basis
  `{"error": ...}`.
- Scheduling (S11): sync check on each tick; schedule via `self.hass.async_create_task` into
  `self._guest_stay_task`, skip while one is pending; cancel in teardown (S16). Setup kicks one walk after the DB is
  reachable (no await in setup).
- Published on `sensor.ura_presence_coordinator_presence_house_state` (S13): `guest_stay_active` (bool),
  `guest_stay_since` (ISO or None), `guest_stay_basis` (list; recorded, changes once a day).

**Acceptance criteria**
- **Verify (fixture = the replay):** a fixture DB built from the 76-night replay rows (or a seeded synthetic copy with
  the same per-night AND per-day fractions) reproduces the §5.5 day list exactly at the rev 6 defaults: active
  08-25..09-02, 09-06..09-07, 09-10, 09-16, 09-28..10-18; off 10-19..11-08. At `GUEST_STAY_ENTRY_NIGHTS` 2: active
  08-26..09-02, 09-06..09-07, 09-30..10-18. With `GUEST_STAY_EXIT_SCALES_WITH_STAY` False: the rev 5 lists (active
  08-25..09-02, 09-06..09-08, 09-10..09-12, 09-16..09-18, 09-28..10-18; at K 2: 08-26..09-02, 09-06..09-08,
  09-30..10-18) (`r6_exit.py`).
- **Discriminates (rev 6 exit):** one entry-qualified night then empty nights → active exactly 1 day (a build that
  kept the fixed 3-night exit gives 3; a build that exits on the entry night gives 0). The October fixture keeps
  09-28..10-18 (a build that applied the short exit to every stay, e.g. n not incremented, drops at 10-14). A
  09-04/09-05-shaped pair (qualifying night with no day, then entry-qualified night) → 2 active days (a build that
  started n at 1 gives 1).
- **Verify:** `_occupied_seconds_between` unchanged on its callers' fixtures (golden on the two existing callers).
- **Verify (clock):** a `person_visits` fixture written in process-local time subtracts correctly under `TZ=UTC` and
  `TZ=America/Chicago` (test sets `time.tzset`); a tz-aware bound passed to the occupancy reader is rejected or
  normalised (assert no `+00:00` in the SQL parameters).
- **Verify:** restart determinism: two walks over the same DB at 06:01 and 14:00 the same day give the same latch and
  basis; a walk at 05:59 uses the previous night set.
- **Verify:** DST: the 11-01 night (9 h) and a spring-forward night (7 h) use their real length.
- **Discriminates (rev 5):** one GB2 night 0.95 with day 0.38 (09-15 shape) → latch True at defaults, False at
  `GUEST_STAY_ENTRY_NIGHTS` 2; one GB2 night 0.51 with day 0.02 (09-04 shape) → False (a build that skipped the day
  test gives True); day 0.60 in GB1 + night 0.72 in GB2 → False (a build that took the day from any room gives True;
  replay-identical, so this is a fixture-only discriminator); a daytime 6 h occupancy on two days with no night →
  False (a build that used the 30-min gate or whole-day occupancy gives True). Resident BLE time in GB1 covering the
  whole day → day test fails (a build that subtracted residents from the night only gives True).
- **Verify (day window):** live 22/6, H 10 → Dy(N) = local N 10:00 → 22:00 (12 h); DST-change days use real
  length; non-wrapping sleep window (1 → 6) with H 10 → local N 10:00 → N+1 01:00; H ≥ sleep start is clamped so
  the day window is at least 1 h (assert the window, not just the result).
- **Verify (one read per room):** the day windows go through the same span-shaped `get_guest_room_night_fractions`
  call as the nights (one call per room with nights + days concatenated, or two calls; never one per window).
- **Test:** `test_guest_stay_producer.py::test_replay_fixture_day_list`, `::test_occupied_seconds_unchanged`,
  `::test_resident_subtraction`, `::test_person_visits_clock_utc_host`, `::test_person_visits_clock_local_host`,
  `::test_naive_utc_bounds`, `::test_restart_determinism`, `::test_window_end_boundary`, `::test_dst_nights`,
  `::test_one_night_with_day_enters`, `::test_one_night_without_day_never_enters`, `::test_day_and_night_same_room`,
  `::test_entry_nights_2_blocks_single_night`, `::test_day_after_night_knob`, `::test_day_window_bounds`,
  `::test_day_resident_subtraction`, `::test_daytime_never_counts`, `::test_db_error_fails_off`,
  `::test_non_wrapping_window`, `::test_task_cancelled_on_teardown`; rev 6:
  `::test_replay_fixture_day_list_fixed_exit`, `::test_one_night_visit_exits_after_one_empty_night`,
  `::test_two_night_visit_exits_after_two`, `::test_long_stay_holds_two_empty_nights`,
  `::test_exit_count_starts_at_entry_q`, `::test_exit_never_on_entry_night`, `::test_exit_count_resets_on_reentry`,
  `::test_exit_scaled_restart_between_empty_nights`, `::test_config_extremes_exit`.
- **Live:** after restart, `guest_stay_basis` on the house-state sensor lists the last 3 nights, each with `fraction`
  (night) and `day_fraction` (the day before, same room) ≤ 0.08, `qualifies` false and `entry_qualified` false;
  `guest_stay_active` false.

### D3 — GUEST from the stay latch (BUILD, with D2; Tier 2-DB; the house-state site)

- One pure helper `_compose_guest_gate(state, *, room: bool, stay: bool, sleep_hour: bool) -> bool`, called at S1 and
  S2. Rule OFF → returns `room` (INV-STAY-3). Rule ON → HOME_*: `stay`; GUEST: `stay and not sleep_hour`. `stay` passed
  in as `self._guest_stay_active and self._guest_detection_enabled`. `sleep_hour` =
  `self._inference_engine._is_sleep_hour(dt_util.now().hour)` (local hour, as `infer()` uses).
- `guest_reason` (S4, rule ON): `night_stay:<comma-joined qualifying rooms>` when the latch is on and the state is HOME_*
  or GUEST; else today's precedence (`guest_room:<room>`, `unidentified_corroborator_only`, `override`, `none`). Note
  `guest_room:<room>` now means "a visitor in a guest room", not GUEST.
- Canary (S5): `guest_armed and not guest_room_gate_armed` debug only when the rule is OFF.
- On each accepted transition INTO GUEST, one INFO line `guest stay entry rooms=<...> basis=<...>` (convenience only).
- **Rev 5, lock regime (INV-LOCK-1):** `security_lock_regime.on_house_state_changed` holds a GUEST-night lock across
  the night yield's GUEST → HOME_NIGHT edge (§3.3 lock row; §13 item 5).

**Acceptance criteria**
- **Verify (INV-STAY-1):** table test over {HOME_DAY, HOME_EVENING, HOME_NIGHT} × room ∈ {T,F} × stay ∈ {T,F} ×
  switch ∈ {T,F}: GUEST proposed only when stay ∧ switch. `room` alone never.
- **Verify (INV-LOCK-1, rev 5, build review B-M1):** lock-regime test driving the real `on_house_state_changed` and
  `_on_guest_clock` with toggle on and live window 22 → 6: house GUEST at 21:59; 22:00 `_on_guest_clock` → one
  `lock.lock` per lockout entity, reason `guest_night`; 22:05 GUEST → HOME_NIGHT → no `lock.unlock`, no `_release`,
  reason still `guest_night`, a `guest_yield_hold` record; 22:07 HOME_NIGHT → SLEEP → reason `sleep`, zero new writes
  (`lockout_locked`); 06:00 WAKING → one `lock.unlock`. Totals over the night per entity: lock 1, unlock 1 (the
  morning). Same sequence with the house staying HOME_NIGHT until 06:00 → still held, released at HOME_DAY. Toggle
  off → no 22:00 engage; SLEEP engages once (today's behaviour, byte-identical). HOME_NIGHT outside the sleep window
  with reason `guest_night` (cannot occur from inference; forced in the test) → releases as today.
- **Discriminates (INV-LOCK-1):** under the fix, the service-call log for the night reads `lock` at 22:00 and
  `unlock` at WAKING only. Under the rev 4 build it reads `lock` 22:00, `unlock` ~22:05, `lock` ~22:07. Under the
  rejected option (a) it reads `lock` at ~22:02 (SLEEP) and nothing at 22:00, which also fails "at the guest-night
  clock".
- **Test (INV-LOCK-1):** `test_guest_split_gate.py::test_lock_once_at_guest_clock_no_unlock_on_yield`,
  `::test_lock_held_if_home_night_until_morning`, `::test_lock_toggle_off_unchanged`; framing-C mutation: delete the
  new `guest_yield_hold` branch → the first test fails.
- **Verify (INV-STAY-2):** in GUEST with stay True, the first tick at `sleep_start_hour` exits to HOME_NIGHT and the next
  tick enters SLEEP; at `sleep_end_hour` the house runs SLEEP → WAKING → HOME_DAY → GUEST. Measure the bound with the
  S9 veto in place and assert it.
- **Verify (INV-STAY-3):** the existing guest test modules (`test_guest_census_correctness.py`,
  `test_v472_feature_b_guest_signal.py`, `test_presence_guest_latch_and_veto_gap.py`, `test_v4622_guest_mode_hardening.py`,
  `test_pc_observability_kill_switches.py`) run unmodified and green under a fixture that sets
  `const.GUEST_NIGHT_STAY_RULE_ENABLED = False`, and the D1 golden matches with the rule OFF.
- **Superseded source-grep anchors (name them in the build commit; replace each with a behavioural test, never keep the
  literal in a kill-switch branch):** `test_guest_census_correctness.py:337-345`, `:375-381`;
  `test_v472_feature_b_guest_signal.py:489-493`, `:687`. `test_recorder_bloat_logflood.py:172` drives the canary shape;
  update it to the rule-OFF condition and keep it red-on-revert.
- **Config boundary:** F ∈ {0, 0.25, 1.0}; day fraction ∈ {0, 0.10, 1.0}; day start ∈ {0, 10, 21, 22, 23}
  against sleep start 22 (the 1 h clamp) and against a non-wrapping window (start 1); day-before ∈ {True, False};
  K = 1, K = L; L = 1, L = 7; replay nights = L (minimum) and 30; sleep window
  wrapping (22→6) and non-wrapping (1→6); threshold min 1 and 600 (visitors leg only).
- **Discriminates:** the 10-17 shape (30 min unknown in GB2 at 16:06 local, house HOME_DAY) under the fix with the
  stay latch already on from the prior nights → house is GUEST already (entered after waking), `guest_reason`
  `night_stay:Guest Bedroom 2`; with the latch off (a day visitor) → no GUEST, `visitors_present` on,
  `guest_reason` `guest_room:Guest Bedroom 2`. Under the plausible wrong build that ORs `room` into entry: GUEST at
  16:06 with `guest_room:` in both cases.
- **Test:** `test_guest_split_gate.py::test_entry_matrix`, `::test_room_alone_never_enters`,
  `::test_night_yield_exits_to_home_night`, `::test_morning_reentry`, `::test_guest_exit_veto_bound`,
  `::test_kill_switch_byte_identical`, `::test_switch_off_blocks_stay`, `::test_restored_guest_without_stay_exits`,
  `::test_away_then_return_reenters`, `::test_guest_reason_night_stay`, `::test_const_read_at_call_time`,
  `::test_config_extremes`. Each of S1, S2, S4, S11 gets a named test that fails when that one site is neutered
  (framing-C drill list).
- **Live:** on the next real stay: `house_state_log` shows HOME_* → `guest` once per day after waking and `guest` →
  `home_night` at ~22:05 (S9 persistence), the house-state sensor's `guest_stay_basis` at the first `guest` state
  shows an `entry_qualified` night, and the lock regime shows one `lock` at 22:00 and no `unlock` before WAKING
  (INV-LOCK-1). With no guest: no `guest` rows at all (the 30-min gate no longer enters), while
  `visitors_present` still turns on for a guest-room visit.

### D4 — Trip-wire: stay latch held too long (BUILD, with D2/D3)

One HIGH stuck-signal NM (`kind=guest_stay_long`) when `_guest_stay_active` has been True continuously for more than
`GUEST_STAY_LONG_NM_DAYS` days (from `_guest_stay_since`). Once per stay; re-armed when the latch turns False. 0 = off.
Shape: copy `_check_sleep_raw_hold` (`presence.py:4173-4255`): a per-tick check called next to it (`:7086`), latch
`_guest_stay_long_nm_fired`, `fire_stuck_signal(kind="guest_stay_long", key=("house",), ...)` in
`hass.async_create_task`. Diagnosis names the room(s) and the last 3 fractions; remedy: "If no guest is staying, check
that room's occupancy sensor (a fan or a stuck radar can hold it) or turn off Guest Detection." Why: a phantom
guest-room hold has no automatic discharge; this sends it to a person. RAM latch; `_guest_stay_since` comes from the
DB walk, so a restart does not restart the span.

**Acceptance criteria**
- **Verify:** fires once after the bound; not at 0; not again in the same stay; re-arms after the latch drops.
- **Test:** `test_guest_stay_tripwire.py::test_fires_once`, `::test_zero_disables`, `::test_rearms_after_stay`,
  `::test_since_survives_restart`, `::test_fires_on_stay_longer_than_bound` (a 30-night fixture stay run through the
  real walk, bound 28: fires on day 28; fails if the walk re-dates `since`).
- **Live:** no `guest_stay_long` row in `notification_log` while no guest is staying.

### D5 — Docs (same commit as D1, and as D2-D4)

- Presence state of play: §2 step 3 (GUEST = stay latch; the `_guest_gate_armed` "pre-evaluates" wording there is
  stale since 08-16 → §10 entry), §7 (night yield; GUEST no longer held overnight by the 30-min gate), §1 table rows for
  `visitors_present` and `guest_stay_*`, §9 card list, §10 entries for the corrections in §10 of this plan.
- Identity manual §6: `GUEST-GATE-DOOR-IDENTITY-1` note (the gate no longer reads instantaneous evidence).
- Card text: replace the `next` line with this plan's rules.

**Acceptance criteria:** **Verify:** the docs cite the new symbols at file:line on the build branch. **Live:** n/a.

---

## 7. Numbers and knobs

| Knob | Rung | Default | Why this rung | Kill-switch semantics |
|---|---|---|---|---|
| `GUEST_NIGHT_STAY_RULE_ENABLED` | 1 (`const.py`) | True | Changes house-state entry; reverting should be reviewed | False = today's 30-min gate entry, byte-identical; no DB walk |
| `GUEST_NIGHT_MIN_FRACTION` | 1 | 0.25 | Fitted to the replay plateau 0.20-0.30 (§5.3); a fitted number, not an operator taste | 0 = any DB evidence qualifies (do not use); > 1 = never qualifies (rule effectively off) |
| `GUEST_STAY_ENTRY_NIGHTS` | 1 | **1** (rev 5; was 2) | Operator 2026-11-09: one night is legit. It is now the second-night GUARD on top of the day test: 2 removes every single-night entry in the replay (09-10..12, 09-16..18) at a cost of 2 stay days (§5.4). The knob that stops a resident's day + one night in GB2 until the GB2 scanner lands | must be 1..`GUEST_STAY_LOOKBACK_NIGHTS`; clamped at read. 1 = entry-qualified night alone suffices |
| `GUEST_STAY_DAY_MIN_FRACTION` | 1 (NEW) | 0.10 | Fitted: replay plateau 0.03-0.20 at H 10 (§5.4); above 0.21 the October stay is never entered (recall cliff), below 0.03 a night-only sleeper (09-04) enters. Fitted number → reviewed change | 0 = day test off (any night with day evidence ≥ 0 qualifies; not rev 4: no second-night guard unless `GUEST_STAY_ENTRY_NIGHTS` 2); > 1 = never enters (rule effectively off for entry; exit unaffected) |
| `GUEST_STAY_DAY_START_HOUR` | 1 (NEW) | 10 | Day window start, local hour; window ends at the CM `sleep_start_hour`. Replay identical for 6-12; 14 halves recall at 0.20 (§5.4). Starts after typical resident wake/office-morning noise in a guest room | clamped 0..23; if it leaves < 1 h before the night window, the window is the 1 h before it (no empty window, no division by zero) |
| `GUEST_STAY_DAY_BEFORE_NIGHT` | 1 (NEW) | True | Operator asked for the choice. True = the day must precede the night (decided on the morning after night 1). False = the day after also counts: replay 19/21 and adds the morning after departure (10-19); decided a day later | False widens entry; never affects exit |
| `GUEST_STAY_LOOKBACK_NIGHTS` | 1 | 3 | The MAXIMUM exit length (rev 6: a stay with ≥ 3 qualifying nights ends on 3 straight non-qualifying nights; replay: 2 drops the October stay at 10-13/10-14, §5.5) and the window for the `GUEST_STAY_ENTRY_NIGHTS` count | clamped ≥ 1 |
| `GUEST_STAY_EXIT_SCALES_WITH_STAY` | 1 (NEW, rev 6) | True | Exit length = min(`GUEST_STAY_LOOKBACK_NIGHTS`, n), n = qualifying nights in the stay so far (§2.3). Replay: October stay identical, one-night visits 3 days → 1 (§5.5). A house-state policy fitted on one stay: changing it should be reviewed, and nobody should tune it by observation | False = rev 5 fixed exit (`GUEST_STAY_LOOKBACK_NIGHTS` straight misses), byte-identical to `a05c628e` |
| `GUEST_STAY_REPLAY_NIGHTS` | 1 | 35 | How far back the deterministic walk starts. It must exceed `GUEST_STAY_LONG_NM_DAYS` + lookback, or `_guest_stay_since` is re-dated inside the walk every morning and D4 can never fire (review R16) | clamped ≥ `GUEST_STAY_LONG_NM_DAYS` + `GUEST_STAY_LOOKBACK_NIGHTS` (and ≥ lookback when D4 is 0) |
| `GUEST_STAY_LONG_NM_DAYS` | 1 | 28 | Trip-wire bound; the one real stay was 21 days | 0 = off |
| `VISITORS_CAM_LEG_ENABLED` | 1 | True | D0 measured the cam leg noisy (§3.1); removable by a reviewed one-line change | False = `legs.cam` always False |
| Night window | 2, REUSED | CM `sleep_start_hour` / `sleep_end_hour` (live 22 / 6) | already operator-set house sleep window | — |
| Resident pad | 1, REUSED | `GUEST_KNOWN_STICKY_S` 120 | same meaning as the live gate's sticky window | 0 = no pad |
| Room threshold `CONF_ROOM_GUEST_OCCUPANCY_THRESHOLD_MIN` | 2, REUSED | 30 | now feeds `visitors_present` only (rule ON) | — |
| Path A persistence / confidence | 2, REUSED | 300 s / medium | unchanged | — |
| Operator toggle | 3, REUSED | `switch.ura_presence_coordinator_guest_detection` | live kill for all guest detection | OFF = no GUEST entry, stay treated False, `visitors_present` follows GUEST only |

All new constants are read as `const.X` at call time (`from .. import const`), never imported by name (a patched
module attribute must reach the code). No new Number, options-flow field or Store.

---

## 8. Non-goals and related cards

- No WiFi anywhere (operator decision). `wifi_guest_floor` stays a census display attribute, unchanged.
- No GUEST → SLEEP edge; no change to `VALID_TRANSITIONS`.
- No arrival-day GUEST (parked, §2.4).
- No change to the 30-min gate, Path A, the census, faces, or the F-5 subtraction.
- No consumer code changes (HVAC, fans, security, NM) except the one lock-regime branch for INV-LOCK-1 (§3.3). No NM on `visitors_present` (revival trigger: the
  operator asks for a "visitors arrived" notification after two weeks with the entity).
- No DB schema change, no new table, no new writer (reads only).
- No GB2 scanner work (operator-owned; the rule does not depend on it).
- Rev 6: no hysteresis "empty" threshold, no empty-day exit, no mid-day exit, no second daily walk (§5.5 rejects all
  of them on the replay). No change to the basis shape or any sensor attribute for the exit count. Parked:
  `GUEST-DEPARTURE-SIGNAL-1` idea (a departure signal such as a door crossing with luggage, the guest's car leaving, or
  an operator "guest left" action) is the only route to a faster long-stay exit; revival trigger: the operator says
  the one-day tail after a real stay under rev 6 mattered.

| Card / parked item | Disposition |
|---|---|
| `CENSUS-GUEST-FLOOR-1` | Unchanged; no longer feeds this card (WiFi dropped). Link only |
| `GUEST-GATE-DOOR-IDENTITY-1` | Stays parked. Door identity could later shorten the arrival-day gap; same revival trigger as §2.4 |
| `GUEST-FP-RESIDUALS-1` | Close candidate after D3 ships: the residual FP shape (30-min room-alone entry) can no longer enter GUEST |
| `GUEST-IDENTITY-PHONE-LEFT-BEHIND-1` | Unchanged |
| `PLANNING_house_away_flap_untracked_occupant.md` Rev 4 (B) guest-room AWAY veto | Trigger fired. The stay latch is its natural input (veto AWAY while a stay is active and a guest room is occupied). Card a re-evaluation; not folded (AWAY side, different invariant) |
| `GUEST-ROOM-FAN-HOLD-1` | Linked: a fan-held guest room is the phantom that D4 pages on |
| `GUEST-SELF-AUTHENTICATION-1` (NEW, parked) | Guests opt in to identify themselves (would give identity where sensors give only occupancy, and could cover the arrival day). Revival trigger: the operator asks. Operator 2026-11-09: "not a bad idea. But not now" |

---

## 9. Tier classification

- **D1: Tier 2.** Additive display entity, no house-state input (INV-VIS-1, pinned by golden). Two framing-disjoint
  reviews (A correctness, B lifecycle / entity registry). Builder `ura-builder`.
- **D2 + D3 + D4: Tier 2-DB** (operator: changes house state; standing rule `feedback_tier2db_minimum_arc`). The
  composition is ONE boolean read at two sites (S1, S2) from a latch with one writer, so the Tier-3 trigger "a value
  threaded through many emission sites" does not fire; rev 3's Tier 3 was for the three-leg recomposition, now
  withdrawn. Three framing-disjoint reviews: A = correctness + DB clocks + replay fidelity; B = state machine (night
  yield, restore, AWAY round-trip, S9 veto interaction, no all-night GUEST, rev 5: INV-LOCK-1 lock actuation count
  across the yield) + async task lifecycle; C = test authority
  by per-site mutation on S1, S2, S4, S11 and the clock conversion. Builder `ura-builder`. Operator checkpoint before
  deploy (house state changes). Live validation + README write-back.

---

## 10. Contradictions found (code wins; fix in D5)

1. `get_closed_person_visits` docstring (`database.py:8559-8560`) says `person_visits` times are naive LOCAL. The writer
   uses `datetime.now()` (`database.py:3908`), which on this HAOS host is UTC (live rows, 2026-11-09). The dwell
   model's `usual_people` (display) therefore reads a window shifted by the UTC offset here. Card it
   (`PERSON-VISITS-CLOCK-PROCESS-LOCAL-1`); not fixed in this cycle beyond D2's own conversion.
2. Presence state of play §2 step 3 says `_guest_gate_armed` "pre-evaluates" GUEST. Since GUEST-CENSUS D2 (08-16) it
   arms nothing (`presence.py:6601`). D5 corrects it.
3. Presence state of play §2 `guest_reason` precedence lists `guest_room:<room>` as a GUEST reason. With the rule ON it
   is a visitor reason. D5 records it.

---

## 11. Rev 4 plan review (adversarial build-prediction; run by the planner, 2026-11-09)

Framing: "what will the builder get wrong reading this?" Findings and where each is fixed:

| # | Finding | Severity | Fix in this plan |
|---|---|---|---|
| R1 | The builder passes tz-aware bounds to the occupancy reader; `.isoformat()` adds `+00:00` and the string compare against naive rows silently returns wrong episodes | HIGH | §2.2 rule + D2 `test_naive_utc_bounds` |
| R2 | The builder reads `person_visits` as local (trusting the `get_closed_person_visits` docstring) or as UTC (trusting this host); either breaks on the other host | HIGH | §2.2 `datetime.fromtimestamp` rule; two TZ tests; §10 item 1 |
| R3 | The builder keeps the latch in RAM with a per-day increment, so a restart forgets the stay | HIGH | §2.3 deterministic walk from the DB; `test_restart_determinism`, D4 `test_since_survives_restart` |
| R4 | The builder makes GUEST hold all night (stay latch only), which blocks SLEEP for weeks (no GUEST → SLEEP edge) | HIGH | §2.3 night yield; INV-STAY-2; `test_night_yield_exits_to_home_night` |
| R5 | The builder awaits the DB inside `_run_inference` on the decision path | HIGH | §2.3 / S11: the tick only schedules; the decision path reads the latch; §4 "no await" note |
| R6 | The builder ORs the 30-min gate into entry ("room OR stay") to keep old tests green | MED | §2.4 rejection; D3 discriminating fixture; source-grep anchors replaced, not appeased |
| R7 | The builder misses two of the four source-grep anchors (rev 3 named only two) | MED | D3 lists all four with lines |
| R8 | The builder leaves the D2 canary firing every GUEST tick with the rule on | LOW | S5 gating; `test_recorder_bloat_logflood.py:172` update |
| R9 | The builder assumes the S9 `guest_exit` veto does not delay the night yield | MED | Resolved by reading `:7333-7382`: the veto delays the exit by `_guest_persistence_seconds`; INV-STAY-2 now states that bound; `test_guest_exit_veto_bound` |
| R16 | With a 14-night walk, `_guest_stay_since` is re-dated to inside the walk every morning, so a 28-day D4 trip-wire can never fire. A builder would ship it green because no test runs a stay longer than the walk | HIGH | `GUEST_STAY_REPLAY_NIGHTS` 35 with a clamp ≥ D4 bound + lookback (§7); D4 test `::test_fires_on_stay_longer_than_bound` drives a 30-night stay through the walk |
| R17 | The builder issues one DB query per room per night (70 a day at 35 nights) | LOW | D2: span-shaped API, one occupancy read + one `person_visits` read per room |
| R18 | A guest room un-flagged mid-stay: the next walk ignores it and the latch can drop | LOW | Accepted and named: the walk reads the CURRENT guest-room list (`_discover_guest_rooms`); README states it |
| R10 | The builder computes `sleep_hour` from UTC | MED | D3: `dt_util.now().hour` (local), as `infer()` |
| R11 | The builder uses the per-room sleep-protection hours (GB1 21-7) instead of the house window, making the fixture disagree with the replay | MED | §1.1 night-window row; D2 fixture uses 22/6 |
| R12 | The builder adds WiFi to `visitors_present` "for completeness" | LOW | Operator decision 2; D1 legs list closed |
| R13 | `_discover_guest_rooms` does not keep the entry id, so the builder slugifies the room name for `occupancy_events.room_id` (which holds entry ids) | MED | S12; §1.1 |
| R14 | The walk task is not cancelled at teardown, or several walks overlap on a burst of ticks | MED | D2 scheduling rules; `test_task_cancelled_on_teardown` |
| R15 | The builder lets switch OFF stop the walk, so re-enabling waits until the next morning | LOW | §2.3: walk always runs; composition masks |

All findings are fixed in the plan text above; no open questions for the operator before D1. Before D2/D3 deploy: the
operator checkpoint (Tier 2-DB, house state).

---

## 11a. Rev 5 plan review (adversarial build-prediction; run by the planner, 2026-11-09)

| # | Finding | Severity | Fix in this plan |
|---|---|---|---|
| R19 | The builder takes the day fraction from ANY guest room (simpler loop over the existing per-night `best` list) | MED | §2.1 same-room rule; D2 `test_day_and_night_same_room` (fixture-only discriminator: the replay cannot tell them apart) |
| R20 | The builder subtracts residents from the night windows only (the rev 4 code path) and reads the day raw | MED | §2.1 "same reader, same resident subtraction"; `test_day_resident_subtraction` |
| R21 | The builder issues a second span read per room for days, or one read per day window | LOW | D2 "one read per room" criterion; nights + days go through the windows list |
| R22 | The builder computes the day window in UTC or as a fixed 12 h before the night start, breaking DST days and non-wrapping windows | MED | §2.1 local-wall-clock construction; `test_day_window_bounds` incl. DST + start-1 window + clamp |
| R23 | The builder keeps `GUEST_STAY_ENTRY_NIGHTS` = 2 from the rev 4 build ("defaults unchanged") | HIGH | §7: default 1 (operator ruling); `test_one_night_with_day_enters` fails at 2 |
| R24 | The builder drops `GUEST_STAY_ENTRY_NIGHTS` as obsolete | MED | §7 keeps it as the resident guard; `test_entry_nights_2_blocks_single_night` |
| R25 | The builder fixes B-M1 by moving the presence yield earlier (option (a)) because it is "in this cycle's files" | HIGH | §3.3 / INV-LOCK-1 name option (b) and why (a) fails the operator rule; discriminating service-call log |
| R26 | The builder's lock fix also swallows a real HOME_NIGHT edge after an operator override out of GUEST | LOW | Accepted by name (INV-LOCK-1 falsifier list): with reason `guest_night` the regime cannot tell them apart; WAKING / HOME_DAY / resident arrival still release, and the backstop is unchanged |
| R27 | `GUEST_STAY_DAY_BEFORE_NIGHT` False is built as a second evening walk | LOW | §2.1: judged at the walk after night N+1 (no new scheduling) |

## 11b. Rev 6 plan review (adversarial build-prediction; run by the planner, 2026-11-09)

| # | Finding | Severity | Fix in this plan |
|---|---|---|---|
| R28 | The builder counts n from the lookback window at every night (n = Q(N)) instead of accumulating it across the stay; then a long stay's n falls to 0-1 after two empty nights and the third night's X shrinks, dropping the October stay at 10-14 | HIGH | §2.3: n is a walk-local accumulator set at entry, +1 per later qualifying night, never decremented; `test_long_stay_holds_two_empty_nights` + the replay fixture |
| R29 | The builder starts n at 1 (the entry night) instead of Q | MED | §2.3 + §5.5 variant note; `test_exit_count_starts_at_entry_q` (09-04/09-05 shape: 2 days, not 1) |
| R30 | The builder tests the exit on the entry night (the `elif` order is lost in a refactor) | MED | INV-STAY-4 (iii); `test_exit_never_on_entry_night` |
| R31 | The builder keeps n across an exit and re-entry inside the replay window | LOW | §2.3 "reset when the latch turns off"; `test_exit_count_resets_on_reentry` |
| R32 | The builder implements (a)/(b)/(c) or a hysteresis threshold "as well", because the brief listed them | MED | §5.5: all rejected on replay; §8 non-goal |
| R33 | The builder adds n to the basis or a new attribute and changes the recorded sensor shape | LOW | §8 non-goal; basis unchanged |

## 12. Live validation (post-restart, feeds the READMEs)

| # | Check | Source | Ships with |
|---|---|---|---|
| L1 | unique id `universal_room_automation_visitors_present` resolves; `legs` has `room`, `cam` | registry + entity | D1 |
| L2 | over 24 h, `visitors_present` on only in short episodes, each with a true leg at the time | recorder | D1 |
| L3 | house-state sensor `guest_stay_basis` lists 3 nights, fractions ≤ 0.02, `guest_stay_active` false | live attribute | D2/D3 |
| L4 | no `guest` row in `house_state_log` from deploy until a real stay | URA DB | D2/D3 |
| L5 | first real stay: daily HOME_* → `guest` after waking (from day 2), `guest` → `home_night` at ~22:05, basis shows an `entry_qualified` night (night ≥ 0.25 AND day ≥ 0.10, same room); exit on the morning after the min(3, n)-th straight empty night (a
one-night visitor: the first empty night; a stay of 3+ nights: the third). Lock regime: per stay night one `lock` at 22:00, no `unlock` until WAKING (`security_lock_regime` records: `guest_yield_hold` at ~22:05). Organic; disposed by this binary discriminator per the soak-exit rule | URA DB + recorder | D2/D3 |

---

## 13. Builder delta against the rev 4 build (`3a37f0c2`)

The rev 4 build is a valid base; rev 5 changes the entry predicate, two defaults, the basis shape, one lock-regime
branch, and the tests that pin them. Nothing else in D1, D3 composition, D4 or the DB reader changes.

1. **`const.py`:** `GUEST_STAY_ENTRY_NIGHTS` 2 → **1** (comment: second-night guard, §7). Add
   `GUEST_STAY_DAY_MIN_FRACTION = 0.10`, `GUEST_STAY_DAY_START_HOUR = 10`, `GUEST_STAY_DAY_BEFORE_NIGHT = True`, each
   with its why + kill semantics from §7. Read as `_ura_const.X` at call time.
2. **`presence.py` `_guest_stay_params`:** return the three new values (clamp day start 0..23, fraction as float).
3. **`presence.py` `_refresh_guest_stay`:** build one day window Dy(N) per night (plus one more when
   `GUEST_STAY_DAY_BEFORE_NIGHT` is False), pass nights + days in ONE `get_guest_room_night_fractions` call per room
   (the API already takes a windows list). Per night keep per-room night and day fractions; `entry_qualified(N)` =
   some room with night ≥ F_night AND day ≥ F_day (same room). Latch: off → on iff `entry_qualified(N)` and the
   night-qualifying count over the lookback ≥ `GUEST_STAY_ENTRY_NIGHTS`; on → off iff the count is 0 (unchanged).
   `since` = window end of the entry night (unchanged). Basis entries gain `day_fraction` and `entry_qualified`.
4. **Day-window helper** next to `guest_night_window`: `guest_day_window(night, start_h, day_start_h, tz)` per §2.1
   (local wall clock, ≥ 1 h clamp). Pure; unit-tested.
5. **`security_lock_regime.py` `on_house_state_changed`:** before the `_HOME_STATES` release, if `new == "home_night"`
   and `self.reason == REASON_GUEST_NIGHT` and `self._in_sleep_window(cfg)`: `self._record("guest_yield_hold",
   trigger="house_state:home_night", written=[])` and return (INV-LOCK-1). No other lock-regime change.
6. **Tests:** update `test_guest_stay_producer.py` replay fixture to the §5.4 day list (both `GUEST_STAY_ENTRY_NIGHTS`
   settings); replace `test_one_night_never_enters` with the rev 5 tests named in D2; add the three INV-LOCK-1 tests
   in D3. The kill-switch golden (`test_kill_switch_byte_identical`, rule OFF) must not change.
7. **Docs (D5):** presence state of play §2 step 3 / §7 and the README describe the rev 5 entry rule; §7's garage
   lockout sentence gains the yield hold.
8. **Still open from the build reviews, not changed by rev 5:** B-M2 (DB error stamps the night evaluated → retry with
   backoff), B-L1 (teardown re-schedule), B-L2 (re-walk on guest-room re-discovery). They stay on the fix-up list.

---

## 14. Builder delta against the rev 5 build (`a05c628e`, `feature/guest-mode-split`)

Rev 6 changes the exit in the walk, one constant, the tests that pin the day list, and the docs. Nothing else in D1,
D3 composition, INV-LOCK-1, D4, the DB reader or the day test changes. Tier stays 2-DB (house state); this delta is
small enough for one fix-up round, but reviews A/B/C re-run on the final branch as already planned (§9).

1. **`const.py`** (next to `GUEST_STAY_LOOKBACK_NIGHTS`, `:519` on `a05c628e`): add
   `GUEST_STAY_EXIT_SCALES_WITH_STAY: Final = True` with the §7 comment (why + "False = rev 5 fixed exit"). Edit the
   rev 5 comment at `:510-517`: "off after LOOKBACK straight non-qualifying nights" →
   "off after min(LOOKBACK, n) straight non-qualifying nights, n = qualifying nights in the stay so far (rev 6;
   LOOKBACK when GUEST_STAY_EXIT_SCALES_WITH_STAY is False)".
2. **`presence.py` `_refresh_guest_stay`, the latch loop (`:6224-6236`):** read
   `scaled = bool(_ura_const.GUEST_STAY_EXIT_SCALES_WITH_STAY)` at call time (with the other params; a fourth value
   from `_guest_stay_day_params` or a local read, builder's choice, but read as `_ura_const.X`). Replace the loop
   body with:
   - keep `q` = qualifying nights among the last `lookback` ending at idx (unchanged; it still gates entry);
   - add a loop-local `n = 0`;
   - entry branch (unchanged condition): on turning True, set `n = q`;
   - else, if active: if `best[idx][2]` (night qualifies) then `n += 1`; set `x = min(lookback, n) if scaled else
     lookback`; turn off iff the last `x` nights ending at idx are all non-qualifying
     (`not any(b[2] for b in best[idx - x + 1: idx + 1])`); on turning off set `since = None` and `n = 0`.
   - With `scaled` False, `x == lookback` and "last x all non-qualifying" is exactly `q == 0`: byte-identical
     (INV-STAY-4 (iv)). Index safety: `x ≤ lookback` and `idx ≥ lookback - 1`, so the slice never goes negative.
   - Update the method docstring ("and off at 0 of them" → the rev 6 rule).
3. **No other code.** Basis entries, `since`, D4, the S9 veto, the composition and the lock regime are unchanged. Do
   not add n to the basis or a sensor attribute (§8, R33).
4. **Tests (`quality/tests/test_guest_stay_producer.py`):**
   - `test_replay_fixture_day_list` → expected = 08-25..09-02, 09-06..09-07, 09-10, 09-16, 09-28..10-18 (docstring:
     rev 6, §5.5).
   - `test_replay_fixture_day_list_entry_nights_2` → 08-26..09-02, 09-06..09-07, 09-30..10-18.
   - NEW `test_replay_fixture_day_list_fixed_exit`: knob False → the two rev 5 lists now in those tests (K 1 and K 2,
     parametrised). Pins INV-STAY-4 (iv) on the real fixture.
   - NEW `test_one_night_visit_exits_after_one_empty_night`: one entry-qualified night (night 0.9, day 0.38), then
     empty → True on the morning after, False the morning after the first empty night (rev 5 gives True until the
     third).
   - NEW `test_two_night_visit_exits_after_two`: the entry-qualified night plus one more qualifying night (n = 2), then empty → True
     after 1 empty night, False after 2.
   - NEW `test_long_stay_holds_two_empty_nights`: 5 qualifying nights, 2 empty, 1 qualifying, then empty → True
     through the 2-night gap; False only after 3 straight empty nights (the 10-13/10-14 shape; kills the R28 build).
   - NEW `test_exit_count_starts_at_entry_q`: night 1 qualifies with day 0.02 (not entry-qualified), night 2
     entry-qualified, then empty → off after 2 empty nights, not 1 (09-04/09-05 shape; kills R29).
   - NEW `test_exit_never_on_entry_night`: lookback 1, scaled, a single entry-qualified night → True on its morning.
   - NEW `test_exit_count_resets_on_reentry`: a 4-night stay, 3 empty (off), then a one-night entry, then empty → off
     after 1 empty night (kills R31).
   - NEW `test_exit_scaled_restart_between_empty_nights`: fresh coordinator walks at 07:00 on the day after the first
     and after the second empty night of a 2-night visit give the same latch as a continuous run (restart
     determinism for n).
   - NEW `test_config_extremes_exit` (parametrised, `GUEST_STAY_DAY_MIN_FRACTION` 0 like `test_config_extremes_walk`):
     (L 1, scaled) one qualifying night then 1 empty → False; (L 7, n 2) → off after 2 empty, not 7; (L 3, knob
     False, n 1) → still True after 2 empty (rev 5).
   - `test_config_extremes_walk` and `test_replay_clamp`: unchanged; re-run (the clamp test counts windows only).
   - `quality/tests/test_guest_stay_tripwire.py`: no change expected (its stays are long, n ≥ 3); re-run
     `::test_fires_on_stay_longer_than_bound` and `::test_since_survives_restart`, and if a fixture there ends a short
     stay, update its expected day, not the code.
   - Mutation anchors for review C: (i) replace `min(lookback, n)` with `lookback` → the one-night and replay tests go
     RED; (ii) drop `n += 1` → `test_long_stay_holds_two_empty_nights` and the replay go RED; (iii) `n = 1` at entry →
     `test_exit_count_starts_at_entry_q` RED; (iv) drop the reset → `test_exit_count_resets_on_reentry` RED.
   - Re-run the kill-switch golden (`test_kill_switch_byte_identical`, rule OFF) and `quality/tests/test_sc_garage_lockout.py`:
     must not change.
5. **`quality/tests/fixtures/guest_stay_r5_replay.json`:** unchanged (same nights; only expectations move).
6. **Docs (D5, same commit as the code):**
   - `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (`:157` on `a05c628e`): "Off after 3 straight
     non-qualifying nights." → the rev 6 rule with the knob, and record in its corrections ledger nothing (no claim
     was wrong; the rule changed).
   - `docs/readmes/README_v5.108.0.md` (or the README of the version this ships as): `:59` row for
     `GUEST_STAY_LOOKBACK_NIGHTS` → "nights looked at; also the most empty nights that end a stay"; add a
     `GUEST_STAY_EXIT_SCALES_WITH_STAY` row; L5 (`:104`) exit wording per §12 L5; the §5.5 replay result (stay
     20/21 unchanged, one-night visits 1 day).
   - `.claude/agents` / memory: none.
7. **Not changed by rev 6, still open from earlier reviews:** whatever of B-M2 / B-L1 / B-L2 is not already closed on
   `a05c628e` (B-M2's retry landed in `d0bc41f0`/`0046d48b`; the builder confirms the other two against the branch
   and lists them in the plan-completion note).
