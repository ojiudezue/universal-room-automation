# Plan review R1 (completeness): House AWAY flap, Rev 3

**Plan:** `docs/planning/PLANNING_house_away_flap_untracked_occupant.md` Rev 3 (`d4794ebd8`, develop)
**Framing:** Tier-3 plan review 1 of 2. The reviewer re-enumerated the surface independently with greps.
**Read first, completely:** `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (no §10 ledger claim is re-asserted) and `docs/architecture/SENSOR_FLEET_CLASSES.md`.
**Verdict: FIX-PLAN.** One HIGH and four MEDIUM findings. All are plan edits; none needs new measurement.

---

## Findings

### HIGH-1: In house SLEEP the room veto does not cover nobody-home. The INV-B justification is false.
- **Plan claim (§2 INV-B, §7 D3):** "Nobody-home and β already cannot fire then, because r's occupancy makes `any_zone_occupied` / `indoor_blocked` true." On that basis veto B goes on α only.
- **Code:**
  - `any_zone_occupied` and `any_indoor_zone_occupied` are computed from `t.mode == ZonePresenceMode.OCCUPIED` (`presence.py:5975-5992`).
  - `ZonePresenceTracker.mode` returns `_override` first (`presence.py:652-656`).
  - On an accepted transition INTO SLEEP, `set_sleep(True)` sets `_override = SLEEP` on every zone tracker (`presence.py:930-936`, `:7027-7031`). Boot restore does the same at `:2404`.
  - So for the whole of house SLEEP, both flags are False whatever the rooms say. The caller passes them unmodified (`presence.py:6487-6516`).
- **Repro (legal config, the card's own scenario):**
  1. Jaya is home with no tracked phone, and the guest's phone is not tracked either.
  2. HOME_NIGHT at 23:00. The Upstairs zone is OCCUPIED from Jaya Bedroom, so `has_people` is true and the house goes to SLEEP.
  3. Next tick: the zones read SLEEP, so `any_zone_occupied = False`. `census_count = 0` because no camera sees a bedroom and there is no BLE identity.
  4. The nobody-home branch (`presence.py:1127-1131`) returns AWAY. SLEEP→AWAY is a valid transition (`house_state.py:110`) and is accepted after the 600 s SLEEP dwell.
- **What does and does not stop it:**
  - β is sleep-exempt (`presence.py:6426-6444`).
  - α gets veto B.
  - Nobody-home has neither a sleep exemption nor veto B. Guard A releases W after the last camera body, and cameras do not see sleepers.
- **Effect:** INV-B, as literally stated (α only), is not falsified. But the plan's §4/§6 "Jaya+guest ≈ 5.8/day" projection simulated room occupancy blocking AWAY outright, not branch by branch. The built code will not deliver it at night.
- **Fix in plan:**
  - Either apply the `away_room_veto` conjunct to nobody-home as well (β is optional because it is already sleep-exempt), after the already-AWAY check and with the same fall-through rule;
  - or compute the veto against raw room state, which it already does via `occupied_since`, and drop the "already cannot fire" claim.
  - Add the test `test_nobody_home_blocked_by_veto_room_in_sleep` (zones overridden to SLEEP, census 0, Jaya occupied → not AWAY). Mutation: drop the conjunct → RED.
  - Restate INV-B over all three branches.
  - Note for D4: `_away_entries_today_someone_home_est` uses `any_zone_occupied`, which is also masked in SLEEP. The estimate undercounts every night. Use raw room or veto-room occupancy instead.

### MEDIUM-1: The `occupied_since` boot seed cannot "count the real run". REUSE exists and was missed.
- **Plan (D3):** boot-seed from `last_changed`, with the test `test_occupied_since_boot_seed_counts_real_run`.
- **Problem:** after an HA restart the room `_occupied` entity is rewritten, so `last_changed` is roughly boot time. The cap clock therefore resets on every restart. A phantom (for example the LD2410's 478-minute unknown) can then hold for up to cap_r after each restart. The hold is still bounded per restart, but the test name promises something the mechanism cannot do.
- **Prior art:** `OccupiedBinarySensor` is a `RestoreEntity` that restores the coordinator's `_became_occupied_time` across restarts (`binary_sensor.py:254-311`, DB fallback `:371`). It also publishes it as the attribute `became_occupied_time` (`binary_sensor.py:473`).
- **Fix:** seed `occupied_since` from that attribute (REUSE) and fall back to `last_changed`. Add a row to the P-table. State in INV-DISCHARGE that the bound is per run, or per restart if the restore is missing.

### MEDIUM-2: The D4 hydration and its live acceptance check disagree by construction.
- `count_house_state_changes_since` compares a LOCAL date string against UTC `datetime.utcnow()` timestamps (`database.py:3031-3046`, writer `:2968`). The docstring admits the skew.
- At CDT, the hydrated "today" includes the previous local evening from 19:00, and drops nothing.
- D4 Live says "`away_entries_today` equals COUNT(*) … since local midnight". After any daytime restart that check fails, and a reviewer could not tell a broken counter from the known skew.
- **Fix:** have the new `state=` path pass the UTC instant of local midnight (only the new kwarg path, so the default stays byte-identical), or state the skew in the acceptance criterion.
- **Same family:** the counter resets only inside `_count_transition` (`presence.py:7459-7462`). Until the first transition after midnight, the attribute shows yesterday's count. Reset it on read or on the periodic tick.

### MEDIUM-3: D0 cannot read 14 days of attribute history; the recorder keeps 7.
- Open (b) is resolved below: the attributes are recorded. But `recorder: purge_keep_days: 7` (`/Users/okosisi/ha-config/configuration.yaml:13`) means D0's "14 days after restart, using `last_camera_body_source` recorder history" will find at most 7 days.
- **Fix:** run D0 at day 7 (or twice, at day 7 and day 14, saving the first extract). Alternatively, persist the at-entry `veto_path` and body source in the `house_state_log.trigger` string, which keeps URA-DB retention with no schema change.
- The §10 parked item "face_recognized_count column … revival if recorder excludes the attribute" has the wrong trigger. Retention, not exclusion, is the binding limit.

### MEDIUM-4: The consumer table (§3.4) misses three house-state AWAY consumers.
- **HA automation `wallpanel_fleet_force_off_secure`** (`automations.yaml:8335-8355`): it triggers on `sensor.ura_coordinator_manager_house_state` to `away` for 3 min and turns off all five wall-panel screens. It is a real actuation consumer.
  - Under the plan, a veto hold keeps the panels on, which is intended. Flaps of 3 min or more today turn them off.
  - Two siblings (`wallpanel_fleet_wake`, `wallpanel_fleet_sleep_after_grace`, `automations.yaml:8255`, `:8270`, `:8320`) gate on `not in ['away','vacation']`.
- **Per-room automation chains and AI rules with `house_state_away` triggers** (`coordinator.py:1739-1749` → `_on_house_state_changed`; trigger labels `config_flow.py:3183`, `:14995`). Live config today has none (checked every room entry), but the table should list it as a consumer class.
- **Exterior-person severity mapping** (`const.py:2344`): `hs in ("away", …) → CRITICAL`. This is presumably the site behind the listed `perimeter_alert.py:1660` row; cite it.
- **No action needed:** `hvac_zones.py:946` (the D5 away edge in `_EV_STATES`) is HVAC-internal and covered by the HVAC row. `switch.py`, `music_following.py` (root) and `routine_forecaster` are listener and docstring hits only, already covered by the "Bayesian/routine/music" row.

### LOW-1: The INV-DISCHARGE hysteresis bound is understated.
It says "≤ 120 s for HOME_*". The AWAY sources also include SLEEP (600 s), GUEST (300 s) and WAKING/ARRIVING (60 s) (`house_state.py:129-139`). State the bound as "the current state's dwell", or the D2 test `test_discharge_while_hysteresis_blocks` should include SLEEP.

### LOW-2: Inference fan-out from the new veto rooms.
- `async_track_state_change_event` fires on attribute-only changes too. Each event schedules `_run_inference` (`presence.py:5401`). Adding Jaya Bedroom adds one more feed.
- URA-ATTRIBUTE-CHURN-1 trimmed the churny attributes on `_occupied` (`binary_sensor.py:271-275`), so the rate is probably small.
- Ask the builder to fire `_run_inference` only when `old.state != new.state` for veto-only rooms. This keeps the guest-role path byte-identical.

### LOW-3: Attribute write amplification on the house-state sensor.
- `PresenceHouseStateSensor` polls by default (30 s, no `should_poll=False`, `aggregation.py:1003+`). `away_hold_age_s` changes every poll during a hold, and `last_camera_body_at` changes on every census update with a body.
- Put `away_hold_age_s` in `_unrecorded_attributes` (precedent: `binary_sensor.py:271`), or publish `away_hold_since` instead of an age. Keep `last_camera_body_source` recorded for D0.

### LOW-4: Citation drift (cosmetic).
- Override service: `__init__.py:6201`, not `:6195`.
- Kill switch: entity `switch.ura_presence_coordinator_away_confirmation_veto` is correct live, but its code slug is `presence_away_veto_enabled` (`switch.py:3880`). The plan's P13 table pairs the two correctly; this is noted only for greppers.
- `count_house_state_changes_since` is `database.py:3031` ✓. `_count_transition` def is at `:7451`.

---

## The three self-check opens: resolved
| Open | Resolution | Evidence |
|---|---|---|
| (a) v8 Presence view path | **There is no `presence` view.** `ura-v8` views: `quick-actions, now, rooms, energy, people, security, climate, health, music`. The card belongs on **`people`** (or `now`). The plan must name the view; "Presence view" does not exist. | `ha_config_get_dashboard(url_path=ura-v8, view_path=presence)` → RESOURCE_NOT_FOUND with that list, 2026-10-18 |
| (b) House-state sensor attributes recorder-excluded? | **Not excluded.** The class has no `_unrecorded_attributes` (`sensor.py:5557-5600`), and no recorder exclude matches `sensor.ura_presence_coordinator_presence_house_state`. **But retention is 7 days** (MEDIUM-3). | `configuration.yaml:12-45` |
| (c) Automations reading someone-home | **None.** No YAML automation, script, scene, group or package references `binary_sensor.ura_presence_coordinator_house_occupied` (78 automations scanned). The house-state automations that do exist read `sensor.ura_coordinator_manager_house_state` (the three wall-panel ones, MEDIUM-4). There is no appdaemon, node-red or pyscript directory. | grep over `/Users/okosisi/ha-config/{automations,scripts,scenes,groups,configuration}.yaml`, `packages/` |

## Re-enumeration results
- **AWAY producers.** `grep "return HouseState.AWAY" presence.py` gives exactly `:1131`, `:1181`, `:1288` ✓.
  - The only other state-machine writers are `transition` at `presence.py:6961`, overrides (`select.py:278`, `__init__.py:6201`, `presence.py:8017`) and `apply_restored` (`manager.py:697`).
  - `force_state` has no callers. `house_state.py` has no inference producer. The plan's fences are complete.
- **`_guest_room_state` readers:** `presence.py:5189, 5227, 5305, 5367, 5500, 5677, 7653` ✓ (5677 is `_clear_guest_room_first_seen`).
- **Sibling maps the builder must also scope:**
  - `_guest_room_entity_to_name` (`:1734`, `:5224`, `:5363`): shared, which is fine.
  - `_guest_room_known_last_true` (`:1742`, `:5459`, `:5473`, written inside `_is_known_person_in_room`): must stay guest-role only.
  - Add both to the builder's reader list.
- **Guest gate entry points:** `_guest_room_gate_armed` is called at `:6067` and `:6081`, and Path A (`_guest_gate_armed`) does not read room occupancy. `CONF_ROOM_IS_GUEST_ROOM` is also read by `room_classification.py:132`, which is unaffected because the plan does not set the flag on Jaya. With the role filter, Jaya Bedroom cannot arm GUEST through any path found ✓.
- **Veto rooms are in indoor zones** (live config): GB1 → Back Hallway, GB2 → Upstairs, Jaya Bedroom → Upstairs; none is outdoor. GB1/GB2 are `room_is_guest_room: True`, Jaya is False ✓. This removes the non-SLEEP half of HIGH-1's concern. The SLEEP mask is the remaining leak.
- **Restart path:**
  - Stamp: RAM, seeded at setup ✓.
  - Knob: CM `entry.options` via the `FanInterferenceHoldNumber` clone (`number.py:3541`) ✓.
  - AWAY counter: hydrated (MEDIUM-2 skew). The someone-home estimate is not hydrated, as declared.
  - `occupied_since`: MEDIUM-1.
  - The 60 s periodic is unconditional (`presence.py:2924-2930`, `:5074-5082`) ✓, so the discharge tick holds.
- **P-table spot checks:** `presence.py:1124`, `2926`, `4758`, `4765`, `5401`, `6476-6486`, `6487`, `6518`, `7926`; `sensor.py:5557`, `5661`; `switch.py:3880`; `number.py:3541`; `const.py:402`; `config_flow.py:12509`, `2306-2337`; `database.py:3031`. All match. P5 omits the `became_occupied_time` REUSE (MEDIUM-1).
- **Knob ladder:**
  - W is rung 3 with kill 0 ✓.
  - The per-room cap is rung 2 with kill 0 ✓.
  - The 600 s lookback is rung 1 ✓.
  - The cap range 0–24 h and the W range 0–1800 / step 30 are stated ✓.
  - Unlisted numbers: none, except the implicit SLEEP dwell (LOW-1), which is existing.

## Must-fix before build
1. HIGH-1: extend veto B to nobody-home (and decide on β), restate INV-B, add the SLEEP-mask test, and fix the estimate's input.
2. MEDIUM-1: seed `occupied_since` from the restored `became_occupied_time`.
3. MEDIUM-2: fix the hydration bound, or make the live criterion honest, and reset the counter at midnight.
4. MEDIUM-3: move D0 inside the 7-day recorder retention, or persist the reason in `house_state_log.trigger`.
5. MEDIUM-4: add the wall-panel automations and the chain/AI-rule consumer class to §3.4.
6. Open (a): name the v8 view (`people`).
LOWs 1–4: fix in the same plan edit.
