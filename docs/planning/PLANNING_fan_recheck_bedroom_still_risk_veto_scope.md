# Fan recheck: scope the bedroom/media "high still risk" veto to house sleep only

Card: JAYA-FAN-STILL-PHANTOM-1. It was parked with a revival trigger, and that trigger fired on 2026-10-12: a Jaya fan-on, radar-sole episode with no `fan_recheck_outcome` row. **Tier 2:** one plan review, then 3 framing-disjoint build reviews, because this is a presence safety veto.

## Operator direction (2026-10-18, verbatim intent)

> "No blanket refusal outside sleep house mode. Let recheck run when phone says elsewhere. Let recheck run if the room doesn't know where her phone is. Can refuse when BLE has her in the room... We need to stop and check in every room when we think radar is holding a room occupied. Except during sleep... We already have a way to turn off recheck in a room if we want."
>
> "Don't make this fix what it's not... no mission creep."

## Evidence

From `docs/planning/AUDIT_fan_recheck_efficacy_post_rev2_2026_10_18.md`:

- **10-12, 15:28–17:38 CDT.** Jaya Bedroom was held by `jaya_3_presence` alone, with the fan on. The house was in `home_day`. Jaya was Away (location "Away" for 100% of the window; `person.jaya` was not_home). No recheck ran.
- **Live veto counters,** read 2026-10-18 on `sensor.jaya_bedroom_jaya_bedroom_bedroom_4_fan_recheck_state`: `high_still_risk` = 54 since the 13:45 restart, out of 719 evaluations.
- **The restore loop is fixed.** That was v5.103.51: 9 of 9 VACATED verdicts kept the fan off. So the recheck is now worth admitting into more rooms.

## Institutional context verified

- **Code:** `presence_fan_recheck.py`, `_evaluate_eligibility` (lines 512–725), read in full. `HIGH_STILL_RISK_ROOM_TYPES` (`:112`) has exactly two consumers:
  - `:698-700`: the Tier-1 path, where an L2 adjacent hit rejects bedroom/media.
  - `:712-714`: the Tier-0/2 path, an unconditional veto for bedroom/media.
- **Grep:** `high_still_risk|HIGH_STILL_RISK` across `custom_components`, `quality/tests` and `docs/Coordinator` turns up only those two sites, plus the tests `test_fan_recheck_observability.py:139` and `test_fan_recheck_mode2_cycle.py:845`.
- **REUSED, unchanged:**
  - Sleep veto `:561-567`: a bedroom in `FAN_TRUST_STATES` (home_night, sleep, waking) vetoes `sleep_state`. This is the "except during sleep" the operator asked for.
  - L1 veto `:664-670`: a trustworthy phone of a person in THIS room vetoes `ble_l1` in every tier. This is the "refuse when BLE has her in the room".
  - Per-room kill switch `CONF_ROOM_FAN_RECHECK_ENABLED`: the operator's "we already have a way to turn off recheck in a room".
  - Window dial `ROOM_TYPE_RECHECK_FACTOR` (bedroom/media ×2). **Kept.** The measured ZK p90 clear is 345 s, and the bedroom ×2 is what brings the window to 240 s.
- **Prior plans:**
  - `PLANNING_fan_noise_mode2_ble_pause_recheck.md`: D1.5 introduced the room_type dial plus the high-still-risk rejection.
  - `PLANNING_fan_noise_running_rejection.md`: Rev 2, family factors.
  - `ANALYSIS_fan_recheck_loosening_options.md`.
  - The presence doc `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` §fan pause-recheck.
- **NEW:** nothing. No constant, knob, sensor or signal is added.

## D1 — Remove the bedroom/media high-still-risk refusal outside the sleep states

- **Tier-0/2 path:** delete the unconditional veto at `:711-714`. A bedroom or media room proceeds to the existing sensors-only gate (`trust_sensors_ok`), the same as any other room.
- **Tier-1 path:** delete the bedroom/media rejection at `:698-700`. An L2 adjacent hit, with `fan_recheck_l2_allowed`, authorizes L2 for every room type.
- **Keep `HIGH_STILL_RISK_ROOM_TYPES`** only if something still reads it. If nothing does, delete the constant.
  - "Retired — available if revisited" does not apply here, because the room-type window factor already carries the conservatism.
  - Update the two tests to the new contract.
- **Unchanged:**
  - the bedroom sleep veto, the L1 veto, the Tier-0/2 L2-adjacent veto;
  - the window factors, the cooldown, the rate cap, the kill switches.

### Falsifiable invariant

For a bedroom or media room with the house in `home_day` or `home_evening`, fan on, radar-sole for N ticks, and no trustworthy phone of any person in that room: `_evaluate_eligibility` returns True (absent the other existing gates). In every case where a trustworthy phone places a person in that room (L1), or the house is in `home_night`/`sleep`/`waking` and the room is a bedroom, it returns False.

### Acceptance criteria

- **Test:** a Tier-0/2 bedroom, `home_day`, no L1/L2 → eligible (was `high_still_risk`).
- **Test:** the same bedroom with the person's phone in the room (L1) → veto `ble_l1`.
- **Test:** the same bedroom with house `sleep` (and separately `home_night` and `waking`) → veto `sleep_state`.
- **Test:** a Tier-1 bedroom with zone persons present plus an L2 adjacent hit, with L2 allowed → eligible with layer L2 (was `high_still_risk`).
- **Test:** a media room, Tier-0/2, `home_evening` → eligible.
- **Test:** the inert `is_recheck_eligible` path agrees with the live path for all of the above (Advisory-2: no counter mutation).
- **Mutation:** re-inserting either removed veto turns at least one named test RED.
- **Live:** after deploy, `fan_recheck_veto_counts.high_still_risk` stops increasing on the Jaya Bedroom recheck-state sensor. The next fan-on radar-sole episode with Jaya away produces a `fan_recheck_outcome` row for `room:jaya_bedroom`.

### Discriminating observation

- **Fix working:** a `fan_recheck_outcome` row for Jaya during the day, with Jaya not in the room.
- **Plausible different failure** (the recheck still blocked by another gate, e.g. `not_radar_sole` or `ble_l2`): no row, and a different veto counter rising.

The veto counter disambiguates the two.

## Non-goals (operator: no mission creep)

- No change to the L2-adjacent veto (Tier-0/2), the window factors, or the cooldown.
- No family-map change for the ESP32 LD2410 (`jaya_3` resolves as `unknown`). That is carded as a separate measurement: how long the ESP32 LD2410 takes to clear after the fan stops.
- No change to the `phantom_retro` label (carded as a residual).
- No change to the `FAN_TRUST_STATES` scope (home_night stays a sleep-protected state for bedrooms).

## Critique, recorded rather than built

1. **The L2-adjacent veto.**
   - On the Tier-0/2 path, a trustworthy phone in an ADJACENT room still vetoes in every room type. That is pre-existing, and it exists because BLE bleeds across a wall.
   - It means "phone elsewhere" only authorizes when "elsewhere" is not next door.
   - Not changed here. Revisit if the veto counters show `ble_l2` blocking known-empty episodes.
2. **`home_night` in the bedroom sleep veto.** The operator said "sleep"; `home_night` (21:00 → Sleep) is also covered. That is pre-existing and arguably correct (children asleep before house Sleep), so it is left as is.

## Risk

LOW-MEDIUM. The worst case is pausing the fan on a still sleeper by day, with no phone, for up to 240 s. The recheck then sees the person (OCCUPIED_CONFIRMED) and restores the fan, or wrongly vacates a still body that the radar loses with the fan off. That second case is the same exposure every non-bedroom room already has. The per-room kill switch is the operator's fallback.
