# v5.108.0 — Visitors present, and GUEST means a guest is staying

Card: GUEST-MODE-SPLIT-VISITORS-1. Plan: `docs/planning/PLANNING_guest_mode_split_2026_11.md` rev 4 (`f8cbcba4`).
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
- **GUEST** (high bar): a guest is staying. A guest room was occupied, by someone who is not a resident located
  there by Bluetooth, for at least a quarter of the house sleep window (22:00 to 06:00 here) on at least 2 of the
  last 3 nights. The check runs once each morning over the URA database, so a restart gives the same answer.
  Three empty nights in a row end the stay.
- During a stay the house is GUEST by day and evening and goes to SLEEP at night as usual: GUEST hands over to
  HOME_NIGHT at the start of the sleep window (after the usual 5-minute exit hold), then SLEEP; after waking it
  returns to GUEST.
- WiFi is not used anywhere (operator decision).
- A trip-wire pages once (HIGH) if a stay lasts more than 28 days, in case a guest-room sensor is stuck on.

What the operator will notice:

- No GUEST on a guest's arrival day or after their first night. `visitors_present` shows them; GUEST starts
  the morning after their second night.
- A daytime visitor in a guest room no longer switches the house to GUEST.
- During a stay, HVAC zones use the slower GUEST tail by day (more comfort, a little more energy), NM exterior-person
  alerts use the GUEST daytime severity, and Bayesian learning pauses by day. Nights are unchanged.
- The house-state sensor gains `guest_stay_active`, `guest_stay_since` and `guest_stay_basis` (the last 3 nights,
  with the room and fraction for each). `guest_reason` reads `night_stay:<rooms>` during a stay; `guest_room:<room>`
  now means a visitor in a guest room, not GUEST.

## Knobs (all rung 1, `const.py`, read at call time)

| Knob | Default | Meaning |
|---|---|---|
| `GUEST_NIGHT_STAY_RULE_ENABLED` | True | False = the old 30-min gate enters GUEST again (identical behaviour); no database walk |
| `GUEST_NIGHT_MIN_FRACTION` | 0.25 | share of the sleep window a guest room must be occupied |
| `GUEST_STAY_ENTRY_NIGHTS` | 2 | qualifying nights needed (clamped to 1..lookback) |
| `GUEST_STAY_LOOKBACK_NIGHTS` | 3 | nights looked at; also the number of empty nights that end a stay |
| `GUEST_STAY_REPLAY_NIGHTS` | 35 | nights walked each morning (clamped to at least trip-wire days + lookback) |
| `GUEST_STAY_LONG_NM_DAYS` | 28 | trip-wire bound; 0 = off |
| `VISITORS_CAM_LEG_ENABLED` | True | False = the camera leg never turns `visitors_present` on |

The Guest Detection switch (`switch.ura_presence_coordinator_guest_detection`) still turns all guest detection off:
no GUEST entry, the stay treated as off, `visitors_present` follows GUEST only.

## Files

- `domain_coordinators/presence.py`: `guest_night_window`, `guest_last_completed_night`, `_compose_guest_gate`,
  `_refresh_guest_stay` (the walk), `_maybe_schedule_guest_stay_refresh`, `_guest_stay_tick`,
  `_check_guest_stay_long`, `_update_visitors_present`; `_discover_guest_rooms` records each guest room's entry id;
  teardown cancels the walk.
- `database.py`: `_occupied_episodes_between` extracted from `_occupied_seconds_between` (same sum);
  new read-only `get_guest_room_night_fractions`.
- `binary_sensor.py`: `VisitorsPresentBinarySensor`. `sensor.py`: three house-state attributes. `const.py`: knobs.
- Docs: presence state of play (§1, §2, §7, §9, §10 #30-#32), identity manual §6, card.

## Tests

`test_guest_split_gate.py`, `test_guest_split_visitors.py`, `test_guest_stay_producer.py`,
`test_guest_stay_tripwire.py` (shared harness `guest_split_harness.py`; base golden
`fixtures/guest_split_golden_base.json`, 200 seeded tuples generated on the base tree before the change).
The replay fixture reproduces the plan §5.3 day list exactly (active 09-29 .. 10-18, off 10-19 .. 11-08).
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
| L3 | the stay walk ran | house-state sensor attributes | `guest_stay_basis` lists 3 nights, fractions ≤ 0.02, `qualifies` false; `guest_stay_active` false |
| L4 | no GUEST without a stay | URA DB `house_state_log` | no `guest` row from deploy until a real stay |
| L5 | first real stay | URA DB + recorder | daily HOME_* → `guest` after waking, `guest` → `home_night` just after 22:00, basis shows ≥ 2 of 3 nights qualifying; ends the morning after the third empty night. Organic: dispose by this discriminator per the soak-exit rule |
| L6 | no trip-wire noise | URA DB `notification_log` | no `guest_stay_long` row while no guest is staying |
| L7 | logs | HA log | no `Guest stay walk failed` WARNING |

Discriminator for L3/L4 against a plausible different failure: if the walk never ran (scheduling broken),
`guest_stay_basis` stays `[]` rather than listing 3 nights.
