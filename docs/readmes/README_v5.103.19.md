# v5.103.19 — HVAC night holds start at house Sleep, not at 21:00

**Card:** `HVAC-NIGHT-TAIL-STARTS-TOO-EARLY-1` (Tier 1; plan `docs/planning/PLANNING_hvac_night_tail_follows_sleep.md`, deliverable B only — C parked)

## Problem
When a room empties, HVAC keeps treating it as occupied for a short "hold" before its zone may switch to Away. Rooms get a longer night hold (bedrooms and media rooms 30 min, common rooms 15 min, others 5–10 min) because radars lose people lying still in bed. That night hold was switched on by `FAN_TRUST_STATES`, which includes `home_night` — a house state that starts at a fixed 21:00, an hour before house Sleep (22:00 live). So from 21:00 a kitchen or media room someone had just walked out of held its zone at comfort for 15–30 minutes.

## Fix
- `hvac_const.py`: new rung-1 constant `HVAC_NIGHT_HOLD_STATES = ("sleep", "waking")`, next to `FAN_TRUST_STATES`, with a comment on why they differ.
- `hvac_zones.py` `_effective_hvac_hold_seconds`: picks the night hold when the house is in `HVAC_NIGHT_HOLD_STATES` instead of `FAN_TRUST_STATES`. Overrides, the night-at-least-day clamp and both callers (producer + per-room display attribute) are unchanged.
- `FAN_TRUST_STATES` is byte-identical: fans, D7 night-trust and the fan recheck behave exactly as before.

Effect: between 21:00 and house Sleep, rooms use their day hold (bedroom/common 60 s, media 120 s). From Sleep until the house actually wakes (the wake is occupancy-vetoed, up to sleep_end + 3 h), night holds apply as before, including per-room overrides (Jaya Bedroom 5400 s, the 9 common rooms 90 s).

Known residual (plan §11, D0): Jaya's room had one 21:41 gap in 7.7 days that the old hold absorbed. Mitigations if it recurs: an earlier house Sleep Start Hour, or revive C for her room.

## Tests
New `quality/tests/test_hvac_night_hold_follows_sleep.py` (helper + wire-in through `_compute_hvac_occupied`); updated `test_zzz_hvac_conditioning_demand.py` (`home_night` → 60) and `test_v5_103_8_hvac_knobs_and_obs.py` (clamp test moved to `sleep` so it still exercises the clamp).

## Live Validation (prospective)
- **L1** (21:00–22:00, house `home_night`): `binary_sensor.media_media_hvac_occupied` attr `hvac_vacancy_hold_s` = **120** (was 1800); `binary_sensor.kitchen_kitchen_hvac_occupied` = **60** (was 90).
- **L2** (after 22:00, house `sleep`): media 1800, kitchen 90, `binary_sensor.jaya_bedroom_jaya_bedroom_hvac_occupied` 5400.
- **L3** (recorder): a bedroom or media room emptying 21:00–22:00 drops `*_hvac_occupied` within ~7 min of `*_occupied` going off; a ~30 min release means B is not working.
- **L4**: at 21:30 in `home_night`, fan decision snapshots still report `sleep_state="sleep"`.

## Rollback
Revert the merge (or set `HVAC_NIGHT_HOLD_STATES` back to include `home_night`). No schema, config or entity changes.
