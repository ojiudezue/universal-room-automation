# Plan review R2 (adversarial build-prediction): SLEEP-mask fix, 5-min BLE memory, AWAY observability

**Plan:** `docs/planning/PLANNING_house_state_sleep_mask_ble_memory_observability.md` (Rev 1, commit 0eeacbb9e)
**Reviewer:** ura-reviewer, framing R2: what will a builder get wrong, and can each invariant be broken with a legal config?
**Date:** 2026-10-18
**Pre-read:** `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (read completely, §10 ledger 1-15 respected) and `SENSOR_FLEET_CLASSES.md` (read completely). No ledger claim is re-asserted here.
**Verdict:** **FIX-PLAN.** The plan needs these changes before build: 1 HIGH and 6 MEDIUM. The LOWs can be fixed in the plan or by the builder.

---

## Findings

### H1 (HIGH): D1 creates a fan → radar → never-AWAY loop in SLEEP, the same shape R2 H2 found in Rev 4
- **Code facts.** The comfort-fan veto acts only when the house is in AWAY or VACATION (`fan_veto.py:60` `_AWAY_STATES`, `:167`). Fans keep running in SLEEP; the night-window trio is `home_night/sleep/waking` (`automation.py:4277`). Fan recheck refuses bedrooms in sleep (FAN_TRUST_STATES scope, state-of-play gold-pattern row). `raw_occupied` is `_derived_mode == OCCUPIED` (`presence.py:748-754`). `_derived_mode` reads `_room_occupied` (`presence.py:771`), and that value is additionally extended by `_fan_interference_hold_until` (`presence.py:~700`). In other words, the existing fan mechanism stretches occupancy longer, never shorter.
- **Legal repro (this house).** Sleep hours are 23-06 and the house is in SLEEP at 23:00. The household leaves at 23:30 carrying their phones. The Frigate fleet goes dark, so `camera_input_degraded=True` and α is skipped (`presence.py:1073-1085`). β is sleep-exempt by default (`CONF_LOST_AWAY_SLEEP_EXEMPT`, `presence.py:1210`). Census is 0. The Jaya Bedroom LD2410 shows phantom presence with the fan on (68 % measured, §6) and its comfort fan keeps running. Today, nobody-home fires AWAY on the masked zones, `fan_veto` turns the fan off, and the phantom clears. **After D1**, `raw_occupied=True` blocks nobody-home, the house stays in SLEEP, the fan stays on, and the phantom stays on until 06:00. The phantom then provides the "sustained raw occupancy" that the WAKING gate wants, giving SLEEP → WAKING → HOME_DAY, and the pre-existing daytime loop takes over. The house is held all night and then into the day.
- **Wigton repro.** omonele's app tracker goes `unknown`, so the person is LOST and excluded from α's trusted set (`presence.py:5939`, `tracked_count == 0` → α starved). β is sleep-exempt. A ZX radar with a running fan in view then gives the same loop.
- **Why the invariants don't catch it.** INV-EMPTY-REACHES-AWAY presupposes "every zone's raw occupancy is clear by t0+T_zone". A phantom violates that premise, so the invariant holds only vacuously. The plan's statement "D1 and D2 add no other hold" is false. D1 adds a night hold whose only discharge today is the bug it removes. §9's "phantom ZX holds SLEEP all night … safer error" covers phantoms in general but misses the self-sustaining fan coupling.
- **Fix-plan.** Choose one of these and write it into D1:
  1. Exclude rooms from the raw limb when the tick is radar-sole with the room's fan on. Reuse `PresenceCoordinator._room_radar_sole_capable(room)` together with `_fan_on_rooms` (gold patterns "Capability-radar-sole boolean" and "Fan listener"). No new producer is needed.
  2. Get an explicit operator acceptance, recorded in §9, that this loop is accepted at night, plus a card for the discharge.

  In both cases, restate INV-EMPTY-REACHES-AWAY with its precondition stated openly, and add a test: `test_sleep_fan_radar_phantom_does_not_hold_empty_house` (option 1) or `..._documented_hold` (option 2).

### M1 (MEDIUM, operator challenge 2026-10-18): INV-NO-BLE-HOLD is mis-scoped; the forgotten-phone discharge is pre-existing and limited
- **Code facts.** D2 touches only STALE, which means a phone that is **no longer** resolved to a room (`person_coordinator.py:607-642`). STALE requires `old_last_bermuda_update` and `time_since_update < decay_timeout`. `last_bermuda_update` is carried through STALE ticks, not refreshed (`:615`, `:625`). A forgotten phone that Bermuda keeps resolving is **ACTIVE** and holds HOME today without D2: `trustworthy_persons` has location = room, so `all_tracked_persons_away=False` (`presence.py:5939-5942`).
- **The only discharge for a visible forgotten phone** is `PersonPhoneLeftBehindSensor.is_on` (`binary_sensor.py:2133-2190`). All of these must hold:
  - the time is outside sleep hours, because the sensor returns False 22:00-07:00 (`:2137-2139`);
  - BLE puts the person in a specific room (`:2147`);
  - that room is not occupied (D9, `:2157-2177`);
  - camera census `total_persons == 0` (`:2181-2185`);
  - there has been no camera sighting for `PHONE_LEFT_BEHIND_HOURS` (1 h, `:2188-2194`).

  When it fires, the house can go AWAY only through exclusion (`presence.py:5677-5805`, reason `phone_left_behind=on`).

  Its limits: up to 1 h of latency, it **never fires overnight**, and it is unusable without interior cameras (Wigton: no census, no sightings, so `sighting is None` is always true, but it is also suppressed at night). This is pre-existing behaviour and out of scope.
- **Builder risk.** The plan's wording ("whatever the phone does afterwards", "governed by `phone_left_behind`") invites a builder or reviewer to treat D2 as a forgotten-phone fix or hazard. Flicker is the one real interaction. A phone at the edge of RSSI that alternates resolved and unresolved re-arms STALE on every resolved tick. Today a gap tick could let α fire, which produces a flap. With D2 the hold is continuous. That hold is still bounded per fix, and the sustaining cause is the ACTIVE ticks, which hold today anyway.
- **Fix-plan.**
  - Restate INV-NO-BLE-HOLD precisely: "**D2 never extends a hold beyond N (+ one person-coordinator interval, 30 s, `const.py:40`, + one presence tick ≤ 60 s) after the person's last Bermuda room fix.**"
  - Add a §12 paragraph that documents the forgotten-phone discharge and the limits above as pre-existing and out of scope.
  - Add tests:
    - `test_d2_preserves_phone_left_behind_precedence`: STALE with `phone_left_behind=on` stays excluded with the `phone_left_behind=on` reason. The plan's `test_phone_left_behind_overrides_stale` covers this; keep it and name it as the precedence anchor.
    - `test_stale_flicker_hold_bounded_by_last_fix`: alternate resolved and unresolved ticks, then stop resolving, and assert that AWAY is proposed by last_fix + N + 90 s.

### M2 (MEDIUM): INV-BYTE-ID-OUTSIDE-SLEEP is false as written; zone trackers can be SLEEP-pinned while the house is not in SLEEP
- `set_house_state_override("sleep")` pins every zone (`presence.py:8024-8025`). A later override to a non-`auto` state, such as `home_day`, does **not** unpin them. Only `"auto"` clears zone SLEEP overrides (`:8008-8012`), and `set_sleep(False)` runs only on an inference transition out of SLEEP (`:7030-7031`). A manual zone SLEEP override (§3.1 says "we also treat as look at raw") has the same effect.
- **Repro.** The house infers SLEEP, so the zones are pinned. The operator selects HOME_DAY from the dropdown. The house is now ≠ SLEEP, but every tracker's `mode == SLEEP`, so D1's raw limb is live outside house SLEEP. `infer()` returns and `_veto_path` differ from today's.
- **Fix-plan.** Restate the invariant as "with no zone tracker in `mode == SLEEP` and no STALE person …". Do not gate on house state, because the tracker-mode gate is the better behaviour. Add `test_zone_sleep_pin_survives_home_override_raw_limb_applies` so the builder does not "fix" this by keying on `current_state`.

### M3 (MEDIUM): the `nobody_home` label has persisted and dashboard readers that the plan says don't exist
- The plan (§2 INV-BYTE-ID) says "grep shows no value consumers beyond `sensor.py` and `presence.py:6518/7926`". But `/config/.storage/lovelace.ura_v8:10453,10458,10464` colours the house-state card **red** and appends "veto: nobody home" whenever `veto_path != 'none'`. `:10477` maps veto_path to "Decided by" labels and has no `nobody_home` key. `lovelace.ura_v7:921,3698` prints it raw.
- §7 D1 step 3 sets `_veto_path="nobody_home"` **also on the already-AWAY return**, so the v8 card turns red for the **entire** time the house is AWAY. Today it reads `none` in AWAY because nobody-home returns before α.
- **Fix-plan.** Choose one:
  - Set the label only on the firing return, not on the already-AWAY return. `last_away_branch` already carries the durable answer.
  - Keep the label as planned and list the v8 card edit (add `nobody_home` to the colour exclusion and the label map) as an operator dashboard step.

  Add the lovelace readers to §3.3 / §4 either way.

### M4 (MEDIUM): D2's consumer list misses `perimeter_alert.py:1703`
- `perimeter_alert` reads `_tracked_persons_count_trusted` as `persons_home`, and its severity table treats 0 as "nobody home", which gives HIGH for home_day/home_evening (`perimeter_alert.py:1688-1705`). D2 raises this count by the number of STALE persons and so changes NM severity during BLE dropouts. That is probably the right direction, but it is an unlisted trust consumer.
- **Fix-plan.** Add it to §3.2 and §4. R1 (completeness) should re-grep `_tracked_persons_count_trusted` and `_all_tracked_persons_away` (`sensor.py:5636/5642`, `switch.py:3873`, `presence.py:6481/7911-7914`, `perimeter_alert.py:1703`).

### M5 (MEDIUM): D3's counter placement and source mapping will be guessed wrong
- `_dispatch_house_state_change` returns early on boot-settle (`presence.py:7879-7889`) and on observation mode (`:7890-7896`), **before** the `log_house_state_change` task (`:7957`). If the increment goes at the top of the function, INV-COUNTER-MATCHES-LOG breaks. **Specify:** increment immediately next to the log scheduling, after both gates.
- Real `source` values are `inference`, `override_adapter` and **`boot_settle_override`** (`presence.py:2440-2446`). The last one is not in the plan's mapping. Map it to `override`.
- The plan's `restore` label has no dispatch site. `apply_restored` (`manager.py:697`) does not go through the helper. A builder chasing "restore" will add a dispatch on boot, which re-emits `SIGNAL_HOUSE_STATE_CHANGED` and writes a log row, a real behaviour change. **Specify:** `restore` is not emitted, or it is set at the attribute level only, with no dispatch and no log row. Drop it from the INV text.

### M6 (MEDIUM): the D1 tests will be written against `infer()` alone, so the wire-in is unanchored (#53 / #62)
- D1 has two sites: the local in `_run_inference` and the kwarg in `infer()`. With the kwarg defaulting to `None`, every planned `infer()`-level test passes even if `_run_inference` never passes the kwarg.
- **Fix-plan.** Require `test_nobody_home_blocked_in_sleep_when_zone_raw_occupied` and the Wigton test to drive `PresenceCoordinator._run_inference` with real `ZonePresenceTracker`s pinned via `set_sleep(True)` and a real room-occupancy update. Mutation anchor: delete the kwarg at the call site (`~:6487-6516`), and a named test must go RED.

### M7 (MEDIUM): the Wigton fixture spec is incoherent about omonele's state
- S0 means census 0. α fires on `all_tracked_persons_away` with no zone term (ledger #12). If the fixture's omonele GPS is `not_home`, `test_wigton_shape_sleep_loop_suppressed` sees AWAY from α, and the test fails or, worse, gets "fixed" by weakening it. If omonele is `home`, census counts the person (`camera_census._get_ble_persons` counts any location that is not away, unknown or empty), which makes it S1, not S0.
- **Fix-plan.** Pin it explicitly. For S0, omonele's tracker is `unknown`/LOST, so α is starved and β is sleep-exempt. This is also the H1 repro shape, so the fixture should carry the H1 test. Each Wigton test asserts **which branch** returned (`_veto_path`) as well as the state.

### L1 (LOW): the hydration ISO format must match the naive column
The writer stores `datetime.utcnow().isoformat()`, naive with no offset (`database.py:2968`). `dt_util.as_utc(x).isoformat()` appends `+00:00`. The lexicographic compare mostly works, but a row at exactly `HH:MM:SS` with no microseconds sorts below the bound. Specify `dt_util.as_utc(dt_util.start_of_local_day()).replace(tzinfo=None).isoformat()`. Use `start_of_local_day` for DST correctness on both transition days, not `now().replace(hour=0)`.

### L2 (LOW): the midnight reset depends on the 60 s periodic tick
The "00:00:30 reads 0" acceptance can fail if the tick lands at 00:00:59. Prefer comparing the date in the attribute getter, which reads 0 when `reset_date != today`. That way the attribute is correct on read regardless of the tick, and the test does not depend on tick phase.

### L3 (LOW): D1 brings outdoor zones back into the night input
`any_zone_raw_occupied` includes outdoor-flagged zones (`presence.py:6004-6006`). A porch camera hit, within its camera timeout, will now hold SLEEP on an empty house at night. This matches daytime behaviour and is bounded by the timeout. State it in §9.

### L4 (LOW): D2 restart behaviour should be stated so nobody "fixes" it
STALE is not restored. At boot `old_data` is empty, so the first tick cannot be STALE (`person_coordinator.py:423`, `:610`). RestoreEntity seeds only `previous_location` and its time (`:1488-1530`). A restart inside N therefore drops the memory, failing toward the pre-D2 behaviour. Add a test that restart does not persist STALE, and add a README line.

### L5 (LOW): the D2 scorecard row is weak
"AWAY rows whose episode lists `tracking_status=stale` = 0" is true by construction once STALE is no longer written to `excluded_persons`. It cannot catch a mis-wire that drops STALE from both `excluded_persons` and `trustworthy_persons`. Better discriminator: AWAY rows where some person's `last_bermuda_update` was less than N before the AWAY. Equivalently, with `stale_counted_home` non-empty in the D7 snapshot, the count must be 0.

### L6 (LOW): `guest_reason` precedence is unspecified
When Path A and Path B are both armed, the plan says "whichever", and the builder will pick one at random. Specify Path B first (room), then A.

### L7 (LOW): the periodic-registration move
Moving it out of the `try:` must keep it appended to `_unsub_listeners`, so teardown cancels it, and must keep it in the once-per-setup path. Anchor `test_periodic_registered_when_discovery_raises` as planned, and also assert that unload cancels it.

---

## Invariant checklist

| Invariant | Result | Note |
|---|---|---|
| INV-EMPTY-REACHES-AWAY | **LEAK (premise)** | H1: a fan-sustained radar phantom in SLEEP violates the premise, and D1 adds that hold. The dwell bound itself holds: SLEEP is 600 s from entry (`house_state.py:135`), SLEEP→AWAY is valid (`:108-111`), and once dwell has elapsed the next 60 s tick is accepted. |
| INV-SLEEP-NOT-EMPTY | PASS | Holds on all `_run_inference` paths once the M6 wire-in is anchored. |
| INV-BLE-SEEN-NOT-AWAY | PASS | STALE location is a room, so `all_tracked_persons_away=False` (`presence.py:5939-5942`). Exception: `phone_left_behind` precedence, which never applies 22-07. |
| INV-NO-BLE-HOLD | **RESTATE** | M1: bound is last fix + N + 30 s + ≤ 60 s. A visible forgotten phone is ACTIVE and out of scope. |
| INV-BYTE-ID-OUTSIDE-SLEEP | **LEAK** | M2: SLEEP-pinned zones under a non-auto override. M3: the label shows on the dashboard. |
| INV-COUNTER-MATCHES-LOG | **AT RISK** | M5: increment placement and `boot_settle_override`. L1: ISO format. L2: tick phase. |

## Must-fix before build
H1, M1, M2, M3, M4, M5, M6, M7. The LOWs are in-plan edits, 1 to 3 lines each.
