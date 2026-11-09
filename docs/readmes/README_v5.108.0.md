# v5.108.0 — Visitors present, and GUEST means a guest is staying

Card: GUEST-MODE-SPLIT-VISITORS-1. Plan: `docs/planning/PLANNING_guest_mode_split_2026_11.md` rev 5 (`250730f6`).
Tier: D1 Tier 2; D2 + D3 + D4 Tier 2-DB (changes house state). **Operator checkpoint before deploy.**

**Status: DRAFT, built on `feature/guest-mode-split`, not reviewed, not deployed.**

## What changes

GUEST used to turn on whenever someone the house did not know stayed 30 minutes in a guest room. In the October
stay that fired 35 times on 16 of 21 days, mostly short morning episodes, and covered only 2 of 21 nights.

Now there are two signals.

- **Visitors present** (low bar, display only): new `binary_sensor.ura_presence_coordinator_visitors_present`
  (unique id `universal_room_automation_visitors_present`, Presence Coordinator device). It is on when the house
  is GUEST, or a guest stay is active, or someone unknown has been in a guest room for 30 minutes, or unidentified
  people have been on camera for 5 minutes. The `legs` attribute says which (`room`, `cam`, `stay`); `since` gives
  when it turned on. Nothing reads it to make decisions.
- **GUEST** (high bar): a guest is staying. One guest room was occupied, by someone who is not a resident located
  there by Bluetooth, for at least a quarter of the house sleep window (22:00 to 06:00 here) AND for at least a
  tenth of the day before (10:00 to 22:00) in the SAME room. One such night is enough (operator 2026-11-09:
  "sustained occupancy during the day and an overnight should suffice"). The check runs once each morning over
  the URA database, so a restart gives the same answer; a database error is retried after 15 minutes and keeps the previous answer meanwhile (off if there is none since boot). A stay ends
  after as many empty nights in a row as it had qualifying nights, up to 2 (operator ruling 2026-11-09): a
  one-night visit ends after one empty night, any longer stay after two. October replay: GUEST 09-28..10-14
  and 10-16 (18 of 21 stay days); the guest's two nights away (10-13, 10-14) end it, and the night back in
  Guest Bedroom 2 (10-15, 0.57, no daytime in the room) re-enters through the re-entry grace: for 7 days after
  a stay ends by empty nights (not by the Guest Left button), one qualifying night in any guest room re-enters
  with no day test. One-night visits are held 1 day.
- During a stay the house is GUEST by day and evening and goes to SLEEP at night as usual: GUEST hands over to
  HOME_NIGHT at the start of the sleep window (after the usual 5-minute exit hold), then SLEEP; after waking it
  returns to GUEST.
- WiFi is not used anywhere (operator decision).
- **Guest left** button (`button.ura_presence_coordinator_guest_left`, on the Presence Coordinator device):
  ends the stay now. The house leaves GUEST on the press (no 5-minute exit hold), the press time is kept
  across restarts, and GUEST comes back only after a new qualifying night that starts after the press (with
  its day). A button exit gets no re-entry grace.
- A trip-wire pages once (HIGH) if a stay lasts more than 28 days, in case a guest-room sensor is stuck on
  (not while Guest Detection is off; a restart during such a stay can page again, at most once a day).
- Garage remote lockouts lock ONCE at 22:00 on a stay night and stay locked through GUEST → HOME_NIGHT → SLEEP
  until waking (INV-LOCK-1; before this fix the night yield unlocked them for about 2 minutes at ~22:05).

What the operator will notice:

- No GUEST on a guest's arrival day (no night yet). `visitors_present` shows them; GUEST starts the morning
  after their first night (October replay: stay day 2; with the 2-night exit cap and the re-entry grace the stay shows 18 of 21 days).
- A resident who spends a day and a night in Guest Bedroom 2 also enters GUEST (no GB2 scanner, so Bluetooth
  cannot subtract them). Set `GUEST_STAY_ENTRY_NIGHTS` to 2 to require a second night.
- A daytime visitor in a guest room no longer switches the house to GUEST.
- During a stay, HVAC zones use the slower GUEST tail by day (more comfort, a little more energy), NM exterior-person
  alerts use the GUEST daytime severity, and Bayesian learning pauses by day. Nights are unchanged.
- The house-state sensor gains `guest_stay_active`, `guest_stay_since` and `guest_stay_basis` (the last 3 nights,
  with the room, night `fraction`, `day_fraction`, `qualifies` and `entry_qualified` for each). `guest_reason` reads `night_stay:<rooms>` during a stay; `guest_room:<room>`
  now means a visitor in a guest room, not GUEST.

## Knobs (all rung 1, `const.py`, read at call time)

| Knob | Default | Meaning |
|---|---|---|
| `GUEST_NIGHT_STAY_RULE_ENABLED` | True | False = the old 30-min gate enters GUEST again (identical behaviour); no database walk |
| `GUEST_NIGHT_MIN_FRACTION` | 0.25 | share of the sleep window a guest room must be occupied |
| `GUEST_STAY_ENTRY_NIGHTS` | 1 | second-night guard: qualifying nights needed among the lookback, on top of the day test (clamped to 1..lookback); 2 removes single-night entries |
| `GUEST_STAY_DAY_MIN_FRACTION` | 0.10 | share of the day window the same guest room must be occupied; 0 = day test off |
| `GUEST_STAY_DAY_START_HOUR` | 10 | day window start (local); ends at the sleep start; at least 1 h |
| `GUEST_STAY_DAY_BEFORE_NIGHT` | True | False = the day after the night also counts (decided a day later) |
| `GUEST_STAY_ERROR_RETRY_S` | 900 | retry delay after a failed walk |
| `GUEST_STAY_LOOKBACK_NIGHTS` | 3 | nights looked at; also the most empty nights that end a stay |
| `GUEST_STAY_EXIT_SCALES_WITH_STAY` | True | exit after min(`GUEST_STAY_EXIT_MAX_NIGHTS`, n) empty nights, n = qualifying nights in the stay; False = the fixed lookback exit (rev 5) |
| `GUEST_STAY_EXIT_MAX_NIGHTS` | 2 | most empty nights in a row before a stay ends (operator ruling); entry still counts over the lookback |
| `GUEST_STAY_REENTRY_GRACE_DAYS` | 7 | days after a stay ends by empty nights during which one qualifying night (any guest room, no day test) re-enters; 0 = off; ignored when the scaled exit is off |
| `GUEST_STAY_REPLAY_NIGHTS` | 35 | nights walked each morning (clamped to at least trip-wire days + lookback) |
| `GUEST_STAY_LONG_NM_DAYS` | 28 | trip-wire bound; 0 = off |
| `VISITORS_CAM_LEG_ENABLED` | True | False = the camera leg never turns `visitors_present` on |

The Guest Detection switch (`switch.ura_presence_coordinator_guest_detection`) still turns all guest detection off:
no GUEST entry, the stay treated as off, `visitors_present` follows GUEST only.

## Files

- `domain_coordinators/presence.py`: `guest_night_window`, `guest_day_window`, `guest_last_completed_night`, `_compose_guest_gate`,
  `_refresh_guest_stay` (the walk), `_maybe_schedule_guest_stay_refresh`, `_guest_stay_tick`,
  `_check_guest_stay_long`, `_update_visitors_present`; `_discover_guest_rooms` records each guest room's entry id;
  teardown cancels the walk and blocks re-scheduling; re-discovery re-walks.
- `domain_coordinators/security_lock_regime.py`: `on_house_state_changed` holds a guest-night lock across the
  GUEST → HOME_NIGHT night yield (`guest_yield_hold`).
- `database.py`: `_occupied_episodes_between` extracted from `_occupied_seconds_between` (same sum);
  new read-only `get_guest_room_night_fractions`.
- `button.py`: `GuestLeftButton` (CM entry, Presence Coordinator device). `binary_sensor.py`: `VisitorsPresentBinarySensor`. `sensor.py`: three house-state attributes. `const.py`: knobs.
- Docs: presence state of play (§1, §2, §7, §9, §10 #30-#32), identity manual §6, card.

## Tests

`test_guest_split_gate.py`, `test_guest_split_visitors.py`, `test_guest_stay_producer.py`,
`test_guest_stay_tripwire.py` (shared harness `guest_split_harness.py`; base golden
`fixtures/guest_split_golden_base.json`, 200 seeded tuples generated on the base tree before the change).
The replay fixture (`fixtures/guest_stay_r5_replay.json`, D0 per-night and per-day fractions) reproduces the
day list of rev 6 with the 2-night exit cap and the 7-day re-entry grace: active 08-25..09-01, 09-05..09-07,
09-10, 09-16, 09-28..10-14, 10-16; 0 days in 10-19..11-08; at `GUEST_STAY_ENTRY_NIGHTS` 2: 08-26..09-01,
09-05..09-07, 09-10, 09-16, 09-30..10-14, 10-16 (grace re-entries need one night, so they bypass the
second-night guard). With
`GUEST_STAY_EXIT_SCALES_WITH_STAY` False it reproduces the rev 5 lists (§5.4) exactly
(`test_replay_fixture_day_list_fixed_exit`). INV-LOCK-1:
`test_sc_garage_lockout.py::test_lock_once_at_guest_clock_no_unlock_on_yield`,
`::test_lock_held_if_home_night_until_morning`, `::test_lock_toggle_off_unchanged`.
Four source-grep anchors were converted to behavioural tests (`test_guest_census_correctness.py`
`::test_home_like_guest_armed_is_room_only`, `::test_inside_guest_branch_unchanged`;
`test_v472_feature_b_guest_signal.py` `::test_additive_or_present`,
`::test_guest_armed_is_guest_room_gate_in_guest_branch`), plus the canary anchor
`test_recorder_bloat_logflood.py::test_d2_canary_production_source_shape`.

## Live validation (prospective; replace with a `Validated <date>` table after restart)

| # | Check | Source | Pass when |
|---|---|---|---|
| L1 | `visitors_present` exists | registry + entity | unique id `universal_room_automation_visitors_present` resolves; `legs` has `room`, `cam`, `stay` |
| L2 | `visitors_present` is quiet with no visitors | recorder, first 24 h | on only in short episodes (expect 0-3, minutes long), each with a true leg at the time |
| L3 | the stay walk ran | house-state sensor attributes | `guest_stay_basis` lists 3 nights, `fraction` and `day_fraction` ≤ 0.08, `qualifies` and `entry_qualified` false; `guest_stay_active` false |
| L4 | no GUEST without a stay | URA DB `house_state_log` | no `guest` row from deploy until a real stay |
| L5 | first real stay | URA DB + recorder | daily HOME_* → `guest` after waking, `guest` → `home_night` just after 22:00, basis shows an `entry_qualified` night (night ≥ 0.25 AND day ≥ 0.10, same room); lock regime one `lock` at 22:00, a `guest_yield_hold` at ~22:05, no `unlock` before WAKING; ends the morning after the min(2, n)-th straight empty night (n = qualifying nights in the stay). Organic: dispose by this discriminator per the soak-exit rule |
| L6 | no trip-wire noise | URA DB `notification_log` | no `guest_stay_long` row while no guest is staying |
| L7 | logs | HA log | no `Guest stay walk failed` WARNING |
| L8 | Guest left button | registry + entity | unique id `universal_room_automation_guest_left` resolves on the Presence Coordinator device; pressing it during a real stay writes a `house_state_log` row with trigger `guest_left_button` |

Discriminator for L3/L4 against a plausible different failure: if the walk never ran (scheduling broken),
`guest_stay_basis` stays `[]` rather than listing 3 nights.
