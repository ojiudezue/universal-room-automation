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

## Plan review 2026-10-18 (Tier-2 adversarial, ura-planner)

Read first, completely: `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (fan pause-recheck §, gold patterns, ledger) and `SENSOR_FLEET_CLASSES.md` scope; `presence_fan_recheck.py` `is_recheck_eligible` :460-500, `_evaluate_eligibility` :512-725, `_still_armed_eligible` :1186-1235; D2 defer consumer `coordinator.py:4344-4428`. Verdict: **FIX-PLAN → fixed below → SHIP-TO-BUILD.**

### Findings and resolutions

**R1 (HIGH — under-scope vs "except during sleep"): media rooms lose their only sleep-time protection.** The sleep veto (`:561-567`) and its mid-arm twin (`_still_armed_eligible:1206-1212`) are `== ROOM_TYPE_BEDROOM` only. Today a media room is refused in EVERY house state by `high_still_risk`. Deleting the veto outright makes a media room eligible in `sleep`/`home_night`/`waking` — a loosening the operator did not ask for (his carve-out is "except during sleep"), and the plan's invariant silently omitted it (it only spoke of `home_day`/`home_evening`). The plan title ("scope … to house sleep only") is the correct intent; D1's "delete" is not.
**Resolution (D1 amended):** do not delete outright. Widen the existing sleep predicate in BOTH sites from `room_type == ROOM_TYPE_BEDROOM` to `room_type in HIGH_STILL_RISK_ROOM_TYPES`, then delete the two `high_still_risk` veto sites (`:698-700`, `:711-714`). Net: bedroom + media refused only across `FAN_TRUST_STATES` (veto reason `sleep_state`), eligible by day/evening; constant `HIGH_STILL_RISK_ROOM_TYPES` stays (now 2 consumers: the two sleep predicates) — the "delete the constant" branch of D1 is void. This is strictly a loosening vs today in every state (no state where media/bedroom becomes MORE restricted). Comment at both sites must say media is included for still-sleeper protection, not the v4.7.13 HVAC keep-on contract (which is bedroom-only in `hvac_fans`). No new constant/knob.
*Operator-confirmable:* if the operator wants media rooms to run through sleep like other non-bedrooms, revert to bedroom-only — one-token change. Default here is the literal reading.

**R2 (MEDIUM — incomplete test enumeration).** The plan names 2 tests; FOUR pin the old contract and will go RED: `test_fan_recheck_observability.py::test_veto_high_still_risk_counts` (:139), `test_fan_recheck_mode2_cycle.py::test_tier1_bedroom_l2_allowed_still_rejects_l2` (~:812), `::test_tier2_bedroom_blocked_even_with_trust_sensors_ok` (:824), `::test_tier2_media_room_blocked_even_with_trust_sensors_ok` (:844). **Resolution:** rewrite all four to the new contract (day → arms; same fixture with `house_state="sleep"` → IDLE with `sleep_state`), do not delete them. Existing sleep tests (`test_sleep_bedroom_preserved_v4_7_13_contract`, `test_home_night_bedroom_vetoed_by_scoped_predicate`, `test_sleep_begins_during_arm_delay_aborts_before_pause_bedroom`, `test_still_armed_non_bedroom_survives_sleep_edge`) must stay green unchanged.

**R3 (MEDIUM — twin site).** Q2 answer: the only other bedroom gate in the recheck path is `_still_armed_eligible:1206-1212` (sleep-edge abort during ARM_DELAY). It is not a `high_still_risk` twin, but under R1 it MUST be widened identically or a media room armed at 20:59 pauses its fan after the `home_night` edge. No restore/rehydrate path gates on room type (grep of `ROOM_TYPE_BEDROOM|HIGH_STILL_RISK` in the module: :71, :112, :565, :698, :712, :1210 only). **Added test:** `test_sleep_begins_during_arm_delay_aborts_before_pause_media_room` (media ARMED in `home_day`, flip to `sleep`, `_still_armed_eligible` is False).

**R4 (INFO — D2 consequence, intended).** `is_recheck_eligible` shares `_evaluate_eligibility`, so bedroom/media by day now return True and the D2 sustain-demotion (`coordinator.py:4414`) DEFERS to the recheck instead of demoting. This is the same arbitration every other room already has (recheck gets first crack; `recheck_in_flight` covers ARMED→COOLDOWN; D2 resumes as backstop once `rate_cap` or any other veto makes eligibility False). Net effect in a bedroom by day: a confirmed-empty episode resolves by a measured fan pause rather than D2's blind demotion — safer for a still person, not riskier. In `FAN_TRUST_STATES` nothing changes (eligibility stays False → D2 behaves as today). **Added acceptance:** test that a bedroom `home_day` radar-sole room gets `is_recheck_eligible == True` (D2 defers) and in `sleep` `== False` (D2 unaffected).

**R5 (LOW — invariant restated).** Replace the falsifiable invariant with: *For a room of type bedroom or media_room, `_evaluate_eligibility` (live and inert) and `_still_armed_eligible` return False whenever house_state ∈ {home_night, sleep, waking} or a trustworthy phone places a person in the room (L1); and no code path emits veto `high_still_risk`. Outside those conditions the room's eligibility is identical to a `generic` room's with the same inputs.* The last clause is the discriminating, falsifiable part — testable by parametrizing the Tier-0/2 and Tier-1-L2 fixtures over `room_type ∈ {bedroom, media_room, generic}` in `home_day` and asserting equal outcomes.

**R6 (LOW — doc write-back).** Per presence-doc rule, the build commit updates `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` §fan pause-recheck (bedroom/media: sleep-scoped refusal only) and corrects stale `HVAC_COORDINATOR_MANUAL.md:493` ("Master Bedroom flagged as high-still-risk protects it during sleep" — protection is now the `sleep_state` predicate).

**R7 (INFO — scope check).** No creep: no knob, constant, signal, or sensor added. Operator's "let recheck run if the room doesn't know where her phone is" is honored only to the extent of the existing ladder — a Tier-1 room with zone persons present and no adjacent L2 hit still vetoes `ble_l2` in EVERY room type. That is pre-existing and not bedroom-specific, so it stays out of this card (joins Critique item 1). Live criterion holds: `DEFAULT_FAN_RECHECK_TRUST_SENSORS_OK = True` (`const.py:746`), so Tier-0/2 bedroom will not stall on `trust_sensors_off` unless the operator turned it off — builder reads the live value before the Live check.

### Amended acceptance (supersedes the matching bullets above)
- Tier-0/2 bedroom and media_room, `home_day`/`home_evening` → ARMED (were `high_still_risk`).
- Same fixtures with `house_state` ∈ {home_night, sleep, waking} → IDLE, veto `sleep_state` (media included).
- Parametrized equivalence vs `generic` (R5).
- Media `_still_armed_eligible` sleep-edge abort (R3).
- `is_recheck_eligible` bedroom day True / sleep False, no counter mutation (R4 + Advisory-2).
- Mutation: (a) revert either sleep predicate to `== ROOM_TYPE_BEDROOM` → media sleep tests RED; (b) re-insert either `high_still_risk` veto → day tests RED.
- Live: unchanged (Jaya Bedroom `high_still_risk` counter absent/flat; a daytime `fan_recheck_outcome` row with Jaya away).
