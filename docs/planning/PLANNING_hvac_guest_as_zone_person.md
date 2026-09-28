# PLANNING: Guest as zone person (HVAC-GUEST-AS-ZONE-PERSON-1)

**Card:** `HVAC-GUEST-AS-ZONE-PERSON-1` (workstream `HVAC-W2-OCCUPANCY-TRUTH`, `kanban.data.yaml:21351`)
**Base:** `develop` @ `e873d1abe` (v5.103.18, W1-B shipped)
**Date:** 2026-09-27
**Status:** plan. **STEP 0 verdict: the operator's claim is CONFIRMED. No thermostat build.** The card as written dies.
One small residual (the guest-room fan hold) is kept as a parked, fully specified design with a measured revival
trigger. One optional settings change is offered to the operator.

| Deliverable | What it is | State |
|---|---|---|
| STEP 0 | Trace the sleep latch, sleep veto and night-trust | **Done (§1)**: the claim holds |
| D0 | Read-only probe: guest nights, fan-off events, which code turns the guest fan off | Planned (§6.1), about 20 min |
| K1 | Optional setting: Guest Bedroom 1 night hold | Operator's choice (§6.2) |
| C1 | Correct the card text and park it | Orchestrator, same turn (§6.3) |
| R1 | Guest person feeds the thermostat night-trust (D7) | **REJECTED on design (§3.1)** |
| R2 | Guest person keeps the guest-room fan on overnight | **PARKED, fully specified (§7)** |

---

## 0. Institutional context verified

### 0.1 Documents read
- **`docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md`: read completely (lines 1-470), including §9e (W1-B, v5.103.18).**
  The parts this plan relies on:
  - §3.2 and §3.3: `conditioning_retreat_ok` means *established AND fused-empty*. Person trust covers only the
    unestablished post-reload gap (the reset-only backstop, operator round 4, 2026-09-17).
  - §3.1: the D8 night tail (bedroom 30 min) and the per-room night-hold knobs.
  - §9.3: Jaya's still-sleeper case was fixed with a per-room knob, not code.
  - §9c: Override Vacant is a falling edge that rides the tail. The live test in §7.9 uses this.
  - §9e: the four W1-B gates. There is no interaction; see §5.2.
  - §10: I assert none of C1-C25. This plan depends on **C5** (the night-protection breadth is decided: reset-only)
    and **C24** (HVAC occupancy arms and holds on the lighting `occupied` value plus a tail).
- **`docs/Coordinator/IDENTITY_FUSION_CAMERAS_MANUAL.md`: read completely (lines 1-542).** What matters here:
  - §3.6 graceful-anonymous: a guest person is anonymous by construction. It consumes no `person_id`, face or
    egress data.
  - §2.1: BLE identity is blind to phoneless occupants. That blindness is why a guest cannot be a `zone_persons`
    tracker.
  - The house GUEST predicate and the census are separate from the per-room guest clock. See §4.
- `docs/planning/PLANNING_hvac_night_tail_follows_sleep.md` (B plan): read completely. See §5.1.
- `docs/planning/PLANNING_hvac_w2_night_sleeper_and_placeholder_readers.md`, Piece C (`:424-440`). It already said
  "verify first; may shrink or kill the card" and corrected the stale aggregation cites. This plan is that
  verification.
- `docs/planning/PLANNING_hvac_zone_conditioning_demand.md`: skimmed for the D7/D8 origin, the round-4 reset-only
  rule, and INV-2 "empty guest wing".

### 0.2 Cards read in full
- `HVAC-GUEST-AS-ZONE-PERSON-1`, including `OPERATOR_DESIGN_INPUT_OCCUPANCY_GATE_2026_08_20`,
  `OPERATOR_CONSTRAINTS_2026_08_20`, `THE_HARD_PART` and `RELATIONSHIP`.
- Context entries for this card elsewhere on the board:
  - `HVAC-SUPPLE-SEQUENCE-1`: `WITNESS_CORRECTION_2026_09_15` ("derives a person FROM room occupancy... cannot
    witness its own input") and step 5 (conditional).
  - `HVAC-ZONE-CONDITIONING-DEMAND-1`: `DUMMY_PERSON_REJECTED_2026_09_15` and the constraint "must not strand
    Guest Bedroom 1". This card was the blocker and is now CLOSED (disposition 2026-09-26).
- `HVAC-NIGHT-LENIENCY-DEGRADATION-DEFENSE-1`: operator "ok" (2026-09-27) not to build the full degradation
  defense, because the per-room knob is the practical fix.
- `HVAC-NIGHT-TAIL-STARTS-TOO-EARLY-1` (the B plan's card) and `HVAC-RELOADING-ROOM-PLACEHOLDER-READERS-1`
  (planned; owns the unestablished-zone readers).

### 0.3 Memory bodies pulled
- `feedback_suppression_needs_discharge`: the five-point contract in §7.4 follows it point by point.
- `feedback_measure_before_build`, `feedback_marginal_benefit_pushback` and `feedback_config_first_before_code`
  (CLAUDE.md): these drive §2 and §6.
- `feedback_coincidental_equality_masks_concept_split` and the card's `WITNESS_CORRECTION`: these drive the R1
  rejection.

### 0.4 Code surveyed (end to end for the cited functions, current `develop`)
- `hvac.py`:
  - `_apply_house_state_presets`, `:2132` onward: row-1 `:2320-2404`, D6 `:2428-2539`, D5 `:2541-2719`, dwell
    `:2735-2748`, D7 `:2750-2860`, main-row ledger `:3211-3223`.
  - `_handle_house_state_changed`, `:3641-3685`.
  - Decision-cycle order: `update_room_conditions` `:1925`, presets `:2017`, fans `:2033`.
  - `_build_person_zone_map`, `:4543-4553`.
- `hvac_zones.py`:
  - `Zone`, `:95-194`.
  - Zone status attributes, `:835-894`.
  - Snapshot, `:896-913`.
  - `is_zone_hvac_established`, `:1445-1520`.
  - `conditioning_retreat_ok`, `:1522-1558`.
  - `zone_has_home_person`, `:1560-1583`.
- `aggregation.py`: `ZoneAnyoneBinarySensor`, `:4213-4545` (layers 1-3).
- `hvac_fans.py`:
  - `discover_fans`, `:364-413`.
  - `update`, `:495-540`.
  - Night-trust HOLD while occupied, `:1187-1218`.
  - Vacancy person-trust hold, `:1259-1332`.
  - `occupied` source, `:761`.
- `presence.py`:
  - `_discover_guest_rooms`, `:4838-5008`.
  - `_handle_guest_room_occupancy_change`, `:5010-5075`.
  - `_is_known_person_in_room`, `:5077-5157`.
  - `_guest_room_gate_armed`, `:5159-5209`.
  - Sleep and guest inference, `:1292-1363`.
- `presence_fan_recheck.py`, the eligibility evaluator, `:440-608`.
- `const.py`: `:401-434` (the guest-room CONFs, `GUEST_BOOT_SEED_MIN_RESIDUAL_S`, `GUEST_KNOWN_STICKY_S`).
- `switch.py`: `HVACD5EnableSwitch` `:3063-3145` (the kill-switch template).
- Live `.storage/core.config_entries` (Samba mount, read 2026-09-27): room flags, zone membership and zone_persons.
  See §1.5.

### 0.5 Prior-art scan: REUSE or BUILD per piece
Scanned three places: code (greps below), plans (§0.1), and analysis and memory (§0.2-0.3).

| Piece | Verdict | Where / why |
|---|---|---|
| Per-room guest flag | **REUSE** | `CONF_ROOM_IS_GUEST_ROOM = "room_is_guest_room"`, `const.py:402`. Live `true` on **Guest Bedroom 1** (zone_3) and **Guest Bedroom 2** (zone_2). |
| Stage-1 arm threshold | **REUSE** | `CONF_ROOM_GUEST_OCCUPANCY_THRESHOLD_MIN`, `const.py:403`, per room, default 30. Live 30 on both guest rooms. |
| Stage-1 clock (continuous unknown occupancy) | **REUSE the state, BUILD one read accessor** | `PresenceCoordinator._guest_room_state[room]["first_seen"]`: armed by `_handle_guest_room_occupancy_change` (`presence.py:5064-5071`), reset on vacancy (`:5044-5052`), known-person exclusion (`:5055-5063`), boot seed with a 300 s residual floor (`:4928-4988`). No public per-room read exists today. The only reader is `_guest_room_gate_armed` (`:5159`), which is the **house** GUEST predicate: it ORs across rooms and mutates state. The operator forbids using it, and so does THE_HARD_PART. NEW accessor `guest_room_sustained(room_name, now)`: a read-only per-room test. |
| Known-person exclusion | **REUSE** | `_is_known_person_in_room`, `presence.py:5077`, with the 120 s sticky window `GUEST_KNOWN_STICKY_S` (`const.py:434`). |
| Sleep-onset detection | **REUSE the pattern** | HVAC `_house_state` is set by the signal (`hvac.py:3657`) and seeded at boot (`:1260-1263`). The per-tick state check follows the `hvac_fans.update` latch (`:509-526`). No second event listener. |
| "Room recheck" primitive (operator question d) | **Checked; NOT reusable** | `presence_fan_recheck.py` pauses a running fan so the radar can be tested without fan motion (`:494-517`, "mmwave-sole" + "fan ON"). It is a fan-induced-radar diagnostic, not a generic "is someone still here" recheck, and it deliberately vetoes bedrooms at night (`:483-488`). The stage-2 recheck is a plain occupancy read at a decision tick, so nothing new is needed. |
| Zone "home person" helper | **REUSE, KEEP+WIRE** | `ZoneManager.zone_has_home_person`, `hvac_zones.py:1560`. It has **zero callers** (grep) and was written as the D7/row-1 backstop helper. R2 would extend it and route the fan site through it. |
| Fan person-trust hold | **REUSE the site** | `hvac_fans.py:1284-1302`. Only R2 would touch it. |
| Kill-switch entity | **REUSE the pattern** | `HVACD5EnableSwitch`, `switch.py:3063`. Minus the options write: RestoreEntity only, so there is no reload-suppression surface. |
| Night-state tuple | **REUSE B's constant** | `HVAC_NIGHT_HOLD_STATES = ("sleep", "waking")`, which B adds to `hvac_const.py`. If B has not shipped, R2 adds it with the same name and value. |
| Zone observability | **REUSE the site** | The zone status attributes dict, `hvac_zones.py:835-894`. Add three keys next to `zone_persons` (`:848`). |
| Transition ledger rows | **REUSE** | The `activity_logger.log(coordinator="hvac", ...)` pattern (for example `hvac.py:2829-2849`). One row per transition, never per tick. |
| Synthetic / dummy person | **Rejected earlier, still rejected** | `DUMMY_PERSON_REJECTED_2026_09_15`. |

Greps run: `zone_persons` (all of `custom_components/`), `is_guest|guest_room|CONF_ROOM_IS_GUEST`,
`zone_has_home_person|_zone_conditioning_retreat_ok(`, `_anyone|ZoneAnyoneBinarySensor`, `FAN_TRUST_STATES`,
`latch` (in `hvac.py`: there is no construct named "sleep latch"), and `hvac_coordination_enabled` (live config).

### 0.6 Config-first check

| Candidate setting | Does it solve the problem? | Evidence |
|---|---|---|
| Guest Bedroom 1 `hvac_vacancy_hold_night` (live: unset, so the bedroom default of 1800 s applies) | **Yes, for the only thermostat exposure that remains** (a guest lost by the radar for more than 30 min while asleep). This is the same fix that shipped for Jaya (5400 s, §9.3). | Live config line for entry `01KE2CP30H1251F10K5R1YJRCC`: `room_type: bedroom`, no night-hold override. **Offered as K1 (§6.2).** |
| Assign a person to zone_3 | No | It would fabricate identity (`DUMMY_PERSON_REJECTED`), and it would not help the established path anyway (§1.1). |
| `room_guest_occupancy_threshold_min` | No | This only tunes arming for the house GUEST state. |
| Fan settings for Guest Bedroom 1 | UNVERIFIED | Which code turns this fan off at night is not known; see D0 Q3. |

**Verdict:** K1 covers the thermostat side with no code. R2, the fan side, has no setting equivalent. It is parked
because its value is unmeasured.

---

## 1. STEP 0: trace of the three cited protections (the operator's correctness claim)

**The claim:** "zone sleep latch is supposed to depend on actual occupancy."

**No construct is named "sleep latch" in `hvac.py`** (grep `latch`: only the S1 reclaim-rate, D6-gate, freeze-floor
and runtime latches). I read it as *what keeps a zone out of `away` at night*. The card's cites are stale (they
point to 2026-08 lines), so each one is re-located below on current `develop`.

### 1.1 Night-trust away-suppression (D7). Card cite `hvac.py:1788-1795`, now **`hvac.py:2780-2797`**

```python
if (
    effective_preset == "away"
    and self._house_state in FAN_TRUST_STATES
    and not self._zone_conditioning_retreat_ok(zone)
):
    ... for person_entity in (zone.zone_persons or []): ...
```

What it depends on:
1. **The zone's actual occupancy comes first.** `_zone_conditioning_retreat_ok` → `conditioning_retreat_ok`
   (`hvac_zones.py:1522-1558`) is True if and only if the zone is **established AND fused-empty**. Fused-empty
   means `not any_room_hvac_occupied`, the OR of the rooms' `hvac_occupied` values. Each room's value is the
   lighting occupancy plus the D8 night tail (bedroom 1800 s).
2. Only when retreat is **not** authorised does D7 look at `zone_persons`. That happens when the zone is
   unestablished (a room is reloading or was never seen) or fused-**occupied**.
3. In the normal night case (zone established, rooms empty past tail and grace), D7 falls through and `away`
   stands **for every zone, including zone_1 and zone_2**. The code comment says so (`:2772-2779`), as does §3.2
   ("person-trust only covers the *unestablished* post-reload gap").

When is `effective_preset == "away"` and retreat not OK? Row-1 cannot produce it: row-1 only sets `away` when
retreat is OK (`hvac.py:2339-2346`, `:2403-2404`). So D7 can only intercept:
- **D6 stale-occupancy force-away** (`:2440-2481`). It needs fused-**occupied** for more than `max_occupancy_hours`
  (live 4 h) with fewer than 2 confirming sources, and it is **skipped during `sleep`** (`:2442`).
- **D5 SHED force-away** (`:2568-2719`). It is **skipped during `sleep`** (`:2570`). Under coast with fused
  occupancy it already defers by itself (`:2657-2662`).
- A reloading (unestablished) zone hit by D5 shed.

Conclusion: during house `sleep`, D7 has nothing to intercept, for anyone. In `home_night` and `waking`, it only
intercepts the two failsafes. **The night retreat is decided by occupancy.** A resident's phone does not keep an
established, sensor-empty zone at `home` either. This was operator decision C5, round 4.

### 1.2 Sleep veto. Card cite `aggregation.py:4017-4019`, now **`aggregation.py:4339-4341`**
- It lives in `ZoneAnyoneBinarySensor._sleep_person_fallback_occupied` (`:4297-4402`), which is layer 2 of
  `is_on` (`:4264-4295`).
- It depends on the house state being `sleep` **and** a `zone_persons` tracker being `home`, routed through
  `presence.should_veto_due_to_reliable_signals`.
- **Nothing in HVAC reads it.**
  - This is the display entity `binary_sensor.zone_<house_zone>_anyone`, keyed by **house** zone.
  - Its HVAC writer path ("Writer B") was deleted on 2026-08-06 (`:4225-4262`: "kept byte-identical — the Lovelace
    dashboard consumes it").
  - A grep for `_anyone` readers in `custom_components/**.py` finds only its own `unique_id` (`:4222`).
  - An operator HA automation could read it. That is outside URA and not verified.

### 1.3 Non-sleep person-home bias. Card cite `aggregation.py:4152-4154`, now **`aggregation.py:4474-4476`**
- It is `_nonsleep_person_fallback_occupied` (`:4423-4544`), layer 3 of the same display sensor.
- It depends on `zone_persons` being home plus 5 min of room quiet, in non-sleep home states.
- **Like 1.2, it is display only.** It has no HVAC consumer.

### 1.4 Pre-arrival routing (the card's fourth mention)
`_build_person_zone_map` (`hvac.py:4543-4553`) maps geofence arrivals of `zone_persons` trackers to zones. A guest
has no tracker, so this does not apply. It is a non-goal (§9).

### 1.5 Live facts that bound the blast radius
From `.storage/core.config_entries`, read 2026-09-27:
- **Zone persons:** zone_3 (the AC 3 house zone) has `zone_persons: []`. zone_1 has Ezinne and Oji (two house
  zones merged). zone_2 has Ziri and Jaya.
- **Guest-flagged rooms:**
  - **Guest Bedroom 1** (entry `01KE2CP30H1251F10K5R1YJRCC`): in zone_3. Bedroom, threshold 30, fan
    `fan.guest_room_down_ceiling_fan`, night hold unset (1800 default).
  - **Guest Bedroom 2** (entry `01KCYSBVA2RMB5C3F1Z90F9X72`): in **zone_2**. That zone has persons, so the
    operator's "moot if it does" guard excludes it.
- **The only room the feature could ever touch is Guest Bedroom 1.**

### 1.6 A zone_persons protection the card missed
`hvac_fans.py:1284-1302`: during the night states, when a bedroom **fan is running** and the room reads vacant, the
fan is held on indefinitely while any `zone_persons` tracker is `home`. In `sleep`, the bedroom-only condition is
dropped, so any room qualifies. Otherwise the fan turns off after `DEFAULT_FAN_VACANCY_HOLD = 300` s
(`hvac_const.py:894`).
- This protection is **live during `sleep`**. zone_1 and zone_2 bedrooms get it; Guest Bedroom 1 does not.
- **It is the one real "resident has it, guest doesn't" gap.**

---

## 2. Verdict

**The operator's claim is CONFIRMED.** The thing that keeps a zone out of `away` at night is room occupancy: the
room's `hvac_occupied` value, with the D8 30-minute bedroom night tail, 10-minute vacancy grace and the 5-minute
tick. It goes through `conditioning_retreat_ok`. `zone_persons` does not decide the night retreat for **any** zone.

The card's premise, "empty zone_persons makes three suppressions inert for zone_3", is wrong once measured against
current code:
- **1 of 3 (D7)** is a narrow interceptor of two failsafes (D6 stale, D5 shed). It never fires in `sleep`.
- **2 of 3 (aggregation layers 2 and 3)** are display only.
- **The pre-arrival mention** does not apply to guests.

The premise was true when the card was written (2026-08-20). It stopped being true when round 4 (2026-09-17,
v5.103.7) made person trust a reset-only backstop.

**A guest asleep in Guest Bedroom 1 gets exactly the thermostat protection that Jaya gets in her bedroom.** The one
thermostat exposure left is the same one Jaya had: a still sleeper lost by the radar for longer than the night
tail. It is fixed the same way, with a per-room setting (K1). No thermostat code is needed.

**The cycle as carded dies.** What is left:
- **R1** (guest person in D7): rejected on design grounds (§3.1).
- **R2** (guest person in the fan hold): a real parity gap, but its value is unmeasured. Guests are rare: 8
  sessions in 7 days, maximum 4.5 min, "a guest room with no guest" (card context, 2026-09-15). The B plan's D0
  found 0 gaps in Guest Bedroom 1. R2 is **parked with a revival trigger measured by D0**, and fully specified here
  so the operator's design (two-stage arm and hold) is kept and buildable.

---

## 3. Residuals

### 3.1 R1: guest person in D7 night-trust. **REJECTED (design)**
D7 only intercepts two cases (§1.1):
- **D6:** "occupied for more than 4 h with fewer than 2 confirming sources, so this is likely a **stuck sensor**,
  force away."
- **D5 shed:** "shed dominates occupancy".

For residents, D7's evidence is a **phone**, which is a different channel from the room sensors. A guest person is
**derived from the same room occupancy sensor** that D6 suspects of being stuck:
- A stuck-on guest-room sensor would arm stage 1 (30 min of "continuous" occupancy).
- It would pass stage 2 (it still reads occupied after bedtime).
- It would then **veto the failsafe built to catch exactly that stuck sensor**, pinning zone_3 at `home` through
  `home_night` and `waking` indefinitely.

This is the circular-witness problem the board already recorded (`WITNESS_CORRECTION_2026_09_15`: "cannot witness
its own input"). For D5 shed, it would add a sensor-derived exception to a rule whose design refuses one (shed
forces away even when fused-occupied, `hvac.py:2635-2637`).

**No measurement can rescue R1.** It is dropped, not parked.

### 3.2 R2: guest person in the fan person-trust hold. **PARKED (value unmeasured)**
- The circular-witness harm is small here. A stuck-on sensor already holds the fan through the normal occupied path
  (`hvac_fans.py:1205-1218`), so R2 adds nothing in that case.
- The worst case is a ceiling fan running in an empty guest room until the house wakes.
- The benefit is real only when a guest is asleep, the fan is on, and the radar loses the guest for more than the
  lighting timeout plus 300 s.
- **Blocking unknown (D0 Q3):** Guest Bedroom 1's merged options have `hvac_coordination_enabled: false` (data
  `true`, options `false`). So the room-level fan code (`automation.py:2872-2890`, `_is_hvac_managing_fans` returns
  False) may *also* be driving `fan.guest_room_down_ceiling_fan`, next to the HVAC `FanController`, which discovers
  it anyway (`hvac_fans.py:364-410`, no flag check).
  - If the room level turns the fan off on vacancy, an R2 that edits only `hvac_fans` delivers nothing, and the
    scope grows.
  - This must be answered before any revival. It is also an **adjacency finding** in its own right (a possible
    second writer). See §10.

**Revival trigger (all three):**
1. D0 Q1 shows at least 1 guest night per month (a Guest Bedroom 1 occupancy episode of at least 30 min that
   overlaps 22:00-02:00).
2. D0 Q2 shows at least 1 URA fan-off on a lost sleeper in Guest Bedroom 1 (fan turned off at night while the room
   read vacant, and the room was occupied again within 60 min). **Or** the operator reports a guest woken by the
   fan.
3. D0 Q3 shows `hvac_fans` is the writer that turns the fan off (or the plan is revised to cover the room-level
   writer).

---

## 4. Producer and consumer map

### 4.1 Value: the room's lighting `occupied` (input to everything here)
- **Producer:** the room coordinator. Stuck and chatter sensors are filtered first (`coordinator.py`
  `_fusion_filter_active`, per card `TAP_POINT_RESOLVED`). Timeout is 300 s live for Guest Bedroom 1.
- **Health:**
  - Guest Bedroom 1's behaviour with a real still sleeper is **unmeasured**; there is no guest data.
  - The sibling Jaya radar is known to lose still sleepers for up to 55.6 min (§9.3).
- **Consumers:** the HVAC D1 producer (`hvac_occupied`, trust); `hvac_fans` `occupied` (`:761`, trust); and
  presence's guest clock (below, trust for the house GUEST state).

### 4.2 Value: the per-room guest clock `_guest_room_state[room].first_seen` (REUSED)
- **Producer:** `_handle_guest_room_occupancy_change` (`presence.py:5010-5075`). It listens to the room's
  `binary_sensor` occupied, resolved by unique_id `<entry_id>_occupied` (`:4887-4889`).
  - Transition 1: unknown occupant arms `first_seen`.
  - Transition 2: a known person resets the clock and sets `known`.
  - Transition 3: vacancy resets the clock.
  - Boot seed from `last_changed`, clamped to leave 300 s of residual (`:4928-4988`).
  - Cleared when the Path B kill switch `_guest_detection_enabled` is off (`:5171-5173`).
- **Dependencies:**
  - The room occupied sensor (§4.1).
  - `person_coordinator.data[*]["location"]` for the known-person exclusion. Healthy: BLE, with a 120 s sticky
    window.
  - `switch.ura_presence_guest_detection_enabled`.
- **Consumers today:** exactly one, `_guest_room_gate_armed` (`:5159`), which feeds `_run_inference`
  (`:5741`, `:5755`) and then the **house** GUEST state (`:1318-1325`). That is a trust decision.
- **R2 would add** one read-only consumer, `guest_room_sustained()`. It never calls `_guest_room_gate_armed`.

### 4.3 Value: the zone guest claim (R2 only, NEW, RAM only)
- **Producer:** the stepper in §7.3, once per HVAC decision cycle, right after `update_room_conditions`
  (`hvac.py:1925`) and before presets (`:2017`) and fans (`:2033`).
- **Consumers (R2):**
  - `zone_home_persons()` feeds the fan vacancy hold (`hvac_fans.py:1292`). Trust.
  - Zone status attributes (`hvac_zones.py:848`). Display.
  - Transition ledger rows. Display and audit.
- **Must NOT be consumed by:** D7 (`hvac.py:2787`), row-1, `conditioning_retreat_ok`, D5, D6, D9, the arrester,
  `_build_person_zone_map`, the main-row ledger `home_persons` (`hvac.py:3218`), or the aggregation display sensors.
  This is enforced by the invariant and tests in §7.

---

## 5. Interactions

### 5.1 With the B plan (`PLANNING_hvac_night_tail_follows_sleep.md`)
1. **B makes night tails apply only in `sleep` and `waking`.**
   - After B, Guest Bedroom 1 uses its 60 s day hold during `home_night` (21:00-22:00).
   - B's D0 found 0 exposed gaps there, but on a sample with no guests.
   - A guest who goes to bed before 22:00 therefore has less thermostat protection until 22:00, the same as
     residents. If that ever matters, the fix is the house Sleep Start Hour, or B's parked C. It is not this card.
2. **K1 composes cleanly with B.** A raised Guest Bedroom 1 night hold would apply only in `sleep` and `waking`,
   which is exactly the bedtime window.
3. **R2's hold window is the same state family.** HELD exists only while the house is in `HVAC_NIGHT_HOLD_STATES`
   (`sleep`, `waking`). R2 reuses B's constant rather than defining a second tuple. That makes the order B first,
   then any R2 revival. If R2 revives before B ships, it adds the constant with B's exact name and value, and B's
   diff becomes a no-op on that line.
4. **Sleep onset is the house SLEEP state**, which is clock-only on entry (`presence.py:1296-1301`, live
   `sleep_start_hour` 22 and `sleep_end_hour` 6). The operator accepts this. Leaving sleep is gated on sustained
   occupancy, with a backstop at `sleep_end + 3 h` (B §0.3). Stage 2 keys on this state, so its recheck opens at
   22:15 on a normal night.
5. **B's `FAN_TRUST_STATES` guard** (B §3) is untouched by R2. R2 reads the new constant, not
   `FAN_TRUST_STATES`. The resident fan hold keeps its `FAN_TRUST_STATES` scope.
6. **File overlap:** only `hvac_const.py` (one constant). No conflict in `hvac_zones.py`: B edits
   `_effective_hvac_hold_seconds`; R2 would edit `zone_has_home_person` and the attributes dict.

### 5.2 With W1-B (§9e)
None. R2 writes no thermostat state and adds no input to `manual_guard_verdict`. The fan hold is not a climate
write. Verified: grep of `hvac_preset.py` for `zone_persons|guest` finds 0 hits.

### 5.3 With the house GUEST state and the identity arc
- R2 reads the same per-room clock the house GUEST state uses, but not the GUEST predicate. The two stay decoupled:
  a house in GUEST mode does not arm R2, and R2 never sets GUEST.
- **Side effect to know about for testing:** stage 1 arming in `home_day`, `home_evening` or `home_night` *also*
  fires house GUEST mode through Path B. Arming during `sleep` does not, because the sleep branch returns before the
  guest-entry branch (`presence.py:1296-1301` comes before `:1318`). The controlled test in §7.9 uses this.
- Identity: none consumed. This follows the manual's §3.6 (graceful-anonymous) and §5.5 (no `person_id` consumer is
  added).

---

## 6. Deliverables for THIS cycle (no build)

### 6.1 D0: read-only probe (about 20 min, no tier)
Script: `scripts/probes/hvac_guest_room_night_probe.py`. Run it with `ssh ha "python3 -" < script` against the
recorder, and against the URA DB for the ledger. Resolve every entity id through the entity registry; never build
one from a slug.

Questions:
- **Q1, guest nights.**
  - Look at the whole recorder span for the Guest Bedroom 1 occupied `binary_sensor` (registry unique_id
    `01KE2CP30H1251F10K5R1YJRCC_occupied`).
  - List every ON episode of at least 30 min that overlaps 22:00-02:00.
  - Also count house GUEST-state episodes in the same span (resolve the house-state entity through the registry).
- **Q2, lost-sleeper fan-offs.**
  - For `fan.guest_room_down_ceiling_fan`: count ON→OFF transitions between 22:00 and 09:00 where the room's
    occupied sensor was OFF at that moment and came back ON within 60 min.
  - Run the same count for the resident bedrooms' fans as a control. It should be about 0, which would show their
    person-trust hold working.
- **Q3, which writer turns the guest fan off.**
  - Join those OFF transitions to `ura_activity_log` rows for Guest Bedroom 1 and its fan.
  - Separate HVAC `FanController` rows from room-level automation rows.
  - Record whether the room-level fan path is active for this room (merged options: `hvac_coordination_enabled`,
    plus the room comfort-fan and humidity-fan switches).
- **Q4, D7 relevance (for the record; closes R1).**
  - Count `preset_change_suppressed` rows with `reason = night_trust_suppressed` per zone over the ledger's
    retention.
  - Expected result: about 0 since v5.103.7, because D7 can only intercept D5 shed and D6.

**Acceptance**
- **Verify:** the Q1-Q4 tables are written back into §11 of this doc.
- **Decision rule:**
  - R2's revival trigger (§3.2) fires only if Q1, Q2 and Q3 all qualify.
  - Otherwise the card closes as "premise refuted; fan residual parked with trigger".
- **Discrimination:**
  - A Q2 count of 0 alongside a Q1 count of 0 means "no guests", not "no problem".
  - The card then parks, and does not close as "working". The trigger stays armed.

### 6.2 K1: optional setting (operator's choice; no code, no tier)
- **Offer:** set Guest Bedroom 1's `hvac_vacancy_hold_night` to **5400 s**. This matches Jaya, the one measured
  still-sleeper case, whose largest needed extension was 55.6 min.
- **Cost:**
  - It only arms on a falling edge after real occupancy, so an empty guest room costs nothing.
  - After a guest leaves the room during sleep or waking, zone_3 keeps conditioning for up to 90 min + 10 min of
    grace. That happens only on guest nights.
- **Recommendation:** wait for the first guest night with evidence (the K1 revival cue is a zone_3 retreat while a
  guest slept). Setting it pre-emptively is also defensible, because the cost is zero on guest-less nights. The
  operator decides.
- **Label:** use B's §L strings (`Empty-room hold (night)`). No new strings.
- **Acceptance, if set:**
  - **Verify:** `.storage/core.config_entries` for `01KE2CP30H1251F10K5R1YJRCC` shows
    `hvac_vacancy_hold_night: 5400.0`, and the key is on the reload-suppression list (B §A confirms the list covers
    it).
  - **Live:** after 22:00, in `sleep`, the Guest Bedroom 1 `*_hvac_occupied` binary sensor (doubled slug per §3.1;
    resolve through the registry) has attribute `hvac_vacancy_hold_s` = **5400**. Before the change it reads 1800.

### 6.3 C1: card correction (orchestrator, same turn)
- Replace the card's `why` measured basis with §2's verdict and the corrected cites:
  - D7 is at `hvac.py:2780-2797` and is reset-only plus a failsafe interceptor.
  - Aggregation `:4339-4341` and `:4474-4476` are display only.
- Status becomes `parked` with the §3.2 trigger. Parsimony verdict: DROP for the thermostat, PARK for the fan.
- Use surgical edits to `kanban.data.yaml` only.

---

## 7. R2: parked design (build only if the §3.2 trigger fires)

This is written as spec so the operator's two-stage design survives. Every operator constraint is met.

### 7.1 Guard (operator constraint 1; the first line of the feature)
```text
if zone.zone_persons:            # any assigned person => feature is moot for this zone
    return NO_CLAIM
guest_rooms = [r for r in zone.rooms if room_flag(r, CONF_ROOM_IS_GUEST_ROOM) and room_type(r) != hallway]
if not guest_rooms or not kill_switch_on:
    return NO_CLAIM
```
- The guard runs on **every tick**, not only at setup. A zone that later gains a person, or a room that loses its
  flag, discharges at the next tick.
- Live effect: only zone_3 / Guest Bedroom 1 qualifies. Guest Bedroom 2 is in zone_2, which has persons.

### 7.2 States
Each qualifying zone is in one of three states:

| State | Meaning |
|---|---|
| `NONE` | No claim. |
| `ARMED` | Stage 1 has passed. The claim grants nothing yet. |
| `HELD` | Stage 2 has passed. The claim counts as a zone person for the fan hold only. |

### 7.3 Transitions (evaluated once per decision tick by the stepper)
- **NONE → ARMED (stage 1, operator constraint 2).**
  - `presence.guest_room_sustained(room, now)` is True for some guest room in the zone.
  - Record `armed_at` and `room`.
  - The accessor is read-only. It returns True only if all of these hold:
    - `_guest_detection_enabled`;
    - `first_seen` is not None;
    - the room is not `current_occupancy_known`;
    - `_is_known_person_in_room(room)` is False (a live re-check that mirrors the gate's Part 1, `:5191`);
    - `now - first_seen >= threshold_min * 60`.
  - The accessor does **not** clear `first_seen`. The gate keeps that job.
  - Arming requires the per-room clock only. The house GUEST predicate is never read.
- **ARMED → HELD (stage 2, after sleep onset, operator constraint 3).**
  - Let `sleep_seen_at` be the first tick in this process at which `_house_state == "sleep"`, reset whenever the
    house is outside `HVAC_NIGHT_HOLD_STATES`. It is found by a per-tick state check, not by listening for an event.
  - The recheck opens at `T_open = max(armed_at, sleep_seen_at) + GUEST_PERSON_RECHECK_DELAY_S` (900 s) and closes
    at `T_open + GUEST_PERSON_RECHECK_WINDOW_S` (1800 s).
  - It **passes** at the first tick in `[T_open, T_close]` where the house is in `HVAC_NIGHT_HOLD_STATES` and the
    guest room's `RoomCondition.occupied` is True.
  - This answers the operator's open questions:
    - (a) The recheck starts 15 min after sleep onset (or after arming, if arming came later).
    - (b) It is a 30-minute window, not a single sample, so a bathroom trip does not fail it.
- **ARMED → NONE:**
  - the recheck window closes without a pass (the guest left before bedtime); or
  - the house is outside `ARMED_CARRY_STATES` = (`home_evening`, `home_night`, `guest`, `sleep`, `waking`), so a
    daytime arm never carries into the night; or
  - the guard fails.
- **HELD → NONE:** see the discharge contract in §7.4.
- **HELD grants:** `zone_home_persons(zone)` returns `["guest:<room>"]` for this zone, which drives the fan vacancy
  hold. **It grants nothing else.**

### 7.4 Liveness and discharge contract (from `feedback_suppression_needs_discharge`)

| Item | Specification |
|---|---|
| What re-affirms presence | Nothing is needed once HELD. That is the operator's intent ("then we can trust even if the sensors fail"). Before HELD, the claim is re-evaluated every tick. |
| What expires the claim (primary discharge) | The house leaves `HVAC_NIGHT_HOLD_STATES`. This is checked each tick (a state check, not a one-shot edge), so a missed signal cannot strand it. A sleep ↔ waking flap does **not** discharge it, because both states are in the set. This is the morning discharge the operator asked for, open question (c). |
| Other discharges | Kill switch OFF (next tick). The zone gains a `zone_persons` entry. The room is no longer flagged as a guest room, or is no longer in the zone. `_guest_detection_enabled` turned OFF only blocks new arming; it does not discharge HELD. That choice is stated here and tested. |
| Backstop | `held_since + GUEST_PERSON_HOLD_MAX_S` (43200 s, 12 h). With sleep at 22:00, it cannot outlive the latest wake (the wake backstop is `sleep_end + 3 h` = 09:00, B §0.3) except on a forced or odd house state. The fan's own manual-off cooldown still wins (`hvac_fans.py:1178-1185`). |
| Restart | **Not persisted.** The claim lives in RAM and is absent from `get_state_snapshot` (`hvac_zones.py:896-913`). After a restart the claim is `NONE`. Stage 1 can re-arm within about 5 min, because presence boot-seeds the clock with a 300 s residual floor. Stage 2 re-runs using the first post-boot tick that sees `sleep` as `sleep_seen_at`. So a mid-night restart delays trust by up to 15 + 5 min and never grants it without a fresh sighting. The failure direction is today's behaviour (the fan follows occupancy), which is safe. |
| Transition vs state trigger | All transitions are tick-evaluated states, apart from recording `armed_at` / `sleep_seen_at` / `held_since` timestamps. No event is suppressed, so no event can be lost. |

### 7.5 Falsifiable invariant (INV-GP)
> A guest-derived zone person exists (state `HELD`) for zone Z at tick t **only if** all of these hold:
> 1. `Z.zone_persons` is empty.
> 2. The kill switch is ON.
> 3. A room R in Z has `room_is_guest_room = true`, and presence's per-room clock for R reported sustained unknown
>    occupancy of at least R's threshold at `armed_at`.
> 4. R read occupied at a tick in `[max(armed_at, sleep_seen_at) + 900 s, +2700 s]` while the house was in
>    (`sleep`, `waking`).
> 5. From then until t, the house never left (`sleep`, `waking`), less than 43200 s have passed, and the process did
>    not restart.
>
> **Across every reachable path, the claim is never read by** D7, row-1, `conditioning_retreat_ok`, D5, D6, D9, the
> arrester, pre-arrival, or any climate write. Its only effect is to extend a running fan's vacancy hold in Z.

**How a reviewer breaks it:**
- Find any caller of `zone_home_persons` / `zone_has_home_person` other than the fan site and the display.
- Find a path that reads `_guest_room_gate_armed`.
- Find a zone with persons that arms.
- Find a HELD that survives into `home_day`.

### 7.6 Knobs (placement ladder)

| Name | Rung | Value | Why this rung |
|---|---|---|---|
| Arm threshold | 2, existing per-room field (REUSED) | `CONF_ROOM_GUEST_OCCUPANCY_THRESHOLD_MIN`, live 30 | Already operator-set per room. |
| `GUEST_PERSON_RECHECK_DELAY_S` | 1 (module constant, `hvac_const.py`) | 900 | A bound on a trust decision. Guests are too rare to tune by watching. Changing it should require review. |
| `GUEST_PERSON_RECHECK_WINDOW_S` | 1 | 1800 | Same reasoning. The window tolerates a bathroom trip. |
| `GUEST_PERSON_HOLD_MAX_S` | 1 | 43200 | A backstop, which by definition is review-gated. |
| `HVAC_NIGHT_HOLD_STATES` | 1 (REUSED from B) | (`sleep`, `waking`) | One definition of "night" for HVAC holds. |
| `ARMED_CARRY_STATES` | 1, NEW local tuple | (`home_evening`, `home_night`, `guest`, `sleep`, `waking`) | No existing tuple has these values (grep). |
| Kill switch `switch.ura_hvac_coordinator_guest_sleeper_protection` | 3 (Switch, RestoreEntity only, default ON, no options write) | on/off | For live disable without a reload. **OFF means:** any claim is discharged at the next tick and nothing arms. |

### 7.7 Files (if revived)
- `domain_coordinators/presence.py`: add `guest_room_sustained(room_name, now) -> bool`, a public read-only accessor
  (about 25 lines).
- NEW `domain_coordinators/hvac_guest_person.py`: a pure stepper (the states and transitions of §7.2-7.4). It takes
  a `now` parameter and has no `hass` side effects, so tests can drive it directly.
- `domain_coordinators/hvac_zones.py`:
  - rename the dead `zone_has_home_person` (`:1560`) to `zone_home_persons(zone, hass) -> list[str]` (real trackers
    that are `home`, plus `guest:<room>` when HELD), and keep a `zone_has_home_person` bool wrapper;
  - add attributes `guest_person` (`not_counted` / `waiting_for_bedtime_check` / `counted_tonight`),
    `guest_person_room` and `guest_person_since` next to `:848`.
- `domain_coordinators/hvac.py`:
  - own the stepper;
  - call it right after `:1925`;
  - write transition ledger rows (episode-gated).
  - **No edit at D7 `:2787`** (INV-GP).
- `domain_coordinators/hvac_fans.py:1292`: replace the inline `zone.zone_persons` loop with
  `self._zone_manager.zone_home_persons(zone, self.hass)`. The behaviour for zone_1 and zone_2 must stay byte
  identical.
- `domain_coordinators/hvac_const.py`: the constants above.
- `switch.py`: `HVACGuestSleeperProtectionSwitch`.
- `strings.json` and `translations/en.json`: the §7.8 strings.
- Tests: see §7.9.
- In the same commit: state-of-play §3.3 (a new row), a README, and this doc's §11.
- **Room-level fan path:** scope depends on D0 Q3. If the room level turns this fan off, the revived plan must add
  that site or re-plan. This is **not** pre-decided here.

### 7.8 Labels (exact strings; operator label rule: short phrase, plain helper, 3-word entity names, no jargon)
- **Switch entity name:** `Guest sleeper protection`
- **Switch description** (README and dashboard tooltip):
  `Keeps the guest room's fan running through the night when a guest is asleep there, even if the room's sensors stop noticing them. It only applies to a heating and cooling zone with no household members assigned. The guest must first spend the guest-room time in the room, then be seen in the room again shortly after the house goes to sleep. It ends when the house wakes up. Turn off to return to normal fan behaviour.`
- **Zone attribute values:** `not_counted`, `waiting_for_bedtime_check`, `counted_tonight`.
- **Ledger descriptions:**
  - `Guest in {room}: waiting for bedtime check`
  - `Guest in {room}: counted for the night`
  - `Guest in {room}: no longer counted ({reason})`
  - where `{reason}` is one of `house woke up`, `not seen after bedtime`, `setting turned off`,
    `12-hour limit reached`, `room is no longer a guest room`, or `zone now has an assigned person`.
- **Existing room field** `room_guest_occupancy_threshold_min`. Update its strings only if R2 ships:
  - Current label: "Minutes of Unknown Occupancy Before Guest Mode".
  - Proposed label: `Minutes before someone counts as a guest`
  - Proposed helper: `How long someone the house does not recognise must stay in this room before URA treats them as a guest. This turns on the house's guest mode and, if Guest sleeper protection is on, lets this room's fan keep running overnight for them. 5 to 240 minutes. Default 30.`
- **Banned-word check** on all new strings: `tail`, `gate`, `latch`, `backstop`, `predicate`, `substrate`, `tier`,
  `HVAC-occupied`, `house_state`, `arm`, `trust`.

### 7.9 Acceptance criteria (if revived)

**Tests.** Every production path is exercised through the real stepper, the real `FanController`, and a real
presence accessor over seeded `_guest_room_state`.

- `test_guard_zone_with_persons_never_claims`: zone_2 with Guest Bedroom 2 flagged and sustained stays `NONE`.
  - Mutation: delete the guard line; the test must fail.
- `test_stage1_reads_room_clock_not_house_predicate`: monkeypatch `_guest_room_gate_armed` to return True while the
  room clock is empty. The zone stays `NONE`.
  - Plus a source guard: the stepper and accessor never reference `_guest_room_gate_armed`.
- `test_known_resident_in_guest_room_never_arms`: reuses `_is_known_person_in_room`.
- `test_armed_grants_nothing`: ARMED plus room vacant for 400 s. The fan turns off exactly as today (the
  `DEFAULT_FAN_VACANCY_HOLD` path).
- `test_recheck_pass_enters_held` and `test_recheck_bathroom_trip_inside_window_passes`.
- `test_recheck_miss_discharges`: the guest left before bedtime, so the state is `NONE` after `T_close`.
- `test_held_holds_fan_through_vacancy`: the **wire-in anchor**. Drive `FanController._evaluate_temp_fan`'s vacancy
  branch with `zone_persons=[]` and HELD; the fan must be held.
  - **Neuter drill:** revert `hvac_fans.py:1292` to the inline `zone_persons` loop; this test must go red.
- `test_resident_fan_hold_byte_identical`: zone_1 and zone_2 fan decisions are unchanged across a matrix of tracker
  states.
- `test_held_discharges_on_home_day`, `test_held_survives_sleep_waking_flap`, `test_held_backstop_12h`,
  `test_kill_switch_off_discharges_next_tick`, `test_room_unflagged_discharges`, `test_zone_gains_person_discharges`.
- `test_restart_drops_claim_and_rearms_via_bootseed`: a new stepper instance starts at `NONE`. With the house in
  `sleep` and the room occupied, it reaches HELD only after stage 1 plus the recheck window.
- `test_guest_claim_never_reaches_thermostat` (INV-GP):
  - with HELD on zone_3, established and fused-empty past grace, row-1 writes `away`;
  - D7's `home_persons` stays `[]`;
  - a source guard: `hvac.py`'s D7 block and `conditioning_retreat_ok` do not call `zone_home_persons` /
    `zone_has_home_person`.
- Label check: `strings.json` and `en.json` match, the banned-word check passes, and hassfest passes.

**Live: controlled test** (guests are rare, so the operator stages one). Do it after 22:00 so the house is already in
`sleep` and house GUEST mode cannot fire (§5.3). The house-state select could force `sleep` earlier, but whether
that reaches HVAC's `_house_state` is **UNVERIFIED** (B §0.3), so the clock route is preferred.
1. **Pre-check.** The tester's phone is outside Guest Bedroom 1 (BLE area elsewhere). Otherwise the known-person
   exclusion blocks arming, and that is itself a discriminating check. The fan is ON and zone_3's other rooms are
   empty.
2. The tester stays in Guest Bedroom 1 for at least 30 min.
   - **Expect** zone_3's status attribute `guest_person = waiting_for_bedtime_check`, with one ledger row.
3. The tester is still in the room during the recheck window.
   - **Expect** `counted_tonight`, with one ledger row.
4. **Simulate a sleeper dropout.** Turn ON `switch.guest_bedroom_1_override_vacant` (resolve through the registry).
   Per §9c this is a falling edge that rides the tail.
5. **Discriminating observation, 20 min after step 4:**
   - **Under the fix:** `fan.guest_room_down_ceiling_fan` is still ON. After the 30-min night tail plus 10-min
     grace, zone_3's climate preset goes to `away` per row-1. That shows the claim did not leak into the thermostat.
   - **With no fix, or with the fan site not wired:** the fan turns off about 5-10 min after step 4.
   - **If the claim leaked into the thermostat:** zone_3 stays `home` after tail plus grace with all rooms empty.
   - **If the room-level writer turns the fan off** (the D0 Q3 risk): the fan goes off even though the attribute
     reads `counted_tonight`. The trace shows a room-level ledger row.
6. Turn off the override. The next morning, check that the first tick after the house reaches `home_day` shows
   `not_counted` with reason `house woke up`.

Write the observed results back into the README as a `Validated <date>` table (CLAUDE.md rule).

### 7.10 Tier (if revived): **Tier 2-DB** (three framing-disjoint reviews), plus one adversarial plan review before build
- **Why not Tier 1:** a cross-coordinator read (presence → HVAC), a new state machine, and a shared helper at a
  trust site (the fan hold) that must stay byte identical for residents. The standing 2026-06-08 policy puts
  regression-prone, cross-coordinator work at three framings.
- **Why not Tier 3:** no cost or safety invariant is threaded through many emission sites. INV-GP is enforced at one
  consumer, plus negative source guards.
- **Framings:**
  - A: correctness and edge cases of the stepper (window arithmetic, restart, flap).
  - B: cross-coordinator integrity (the presence clock stays unmutated; resident fan byte identity; house GUEST
    decoupling).
  - C: adversarial completeness against INV-GP. Re-grep every reader of `zone_persons` and the new helper, and prove
    none of them is a thermostat path.

---

## 8. Tier for THIS cycle
**No tier. No code ships.**
- D0 is a read-only probe.
- K1 is an operator settings action.
- C1 is a board edit.
- The plan itself needs no plan review, because nothing is dispatched to a builder.
- A revived R2 is Tier 2-DB (§7.10) and needs its own plan review first.

## 9. Non-goals
- Any change to how `zone_persons` or a guest affects the **thermostat** at night: D7, row-1,
  `conditioning_retreat_ok`, D5, D6 or D9. Round 4 (C5) decided that occupancy decides. Giving a guest more than a
  resident gets would reverse that for zone_3 alone. If the operator ever wants sensor-dropout trust on the
  thermostat, it belongs to `HVAC-NIGHT-LENIENCY-DEGRADATION-DEFENSE-1` for **all** zones, at Tier 3, because it
  touches the shared retreat gate with four consumers.
- R1 (§3.1), dropped.
- The aggregation display sensors (`binary_sensor.zone_*_anyone`, layers 2 and 3). They are display only and not
  consumed by HVAC.
- Pre-arrival for guests: guests have no geofence tracker.
- Using the house GUEST state or `_guest_room_gate_armed` as an input.
- Guest Bedroom 2 and any zone with assigned persons.
- Identity, face, census or egress consumption.
- Changing house sleep hours, B's scope, or B's parked C.
- Persisting the claim across restarts.

## 10. Supersession and adjacent findings (for the orchestrator's adjacency sweep; no cards minted here)

| Item | file:line | Bucket | Note |
|---|---|---|---|
| `zone_has_home_person` (0 callers) | `hvac_zones.py:1560-1583` | **KEEP + DOCUMENT** now; KEEP + WIRE if R2 revives | Its docstring says "used by the D7 / row-1 fail-open path", which is not true (D7 has its own inline loop at `hvac.py:2787`). Add a one-line "unwired; see PLANNING_hvac_guest_as_zone_person §7" comment in whatever cycle next touches the file. |
| Aggregation layers 2 and 3 | `aggregation.py:4297-4544` | KEEP (display, distinct semantics) | They are not HVAC protections. Correct the card text (C1). |
| **Guest Bedroom 1 fan: possible second writer** | Live options `hvac_coordination_enabled: false`; `automation.py:2872-2890`; `hvac_fans.py:364-410` | **Adjacency finding, UNVERIFIED** | The HVAC `FanController` discovers the fan regardless of the room flag, and the room level does not defer when the flag is false. Both may command `fan.guest_room_down_ceiling_fan`. The same shape probably applies to other rooms whose options have `hvac_coordination_enabled: false` but which have fans and are in an HVAC zone (for example Guest Bedroom 2 and Jaya Bedroom, both with options `false`). **Run the 4-surface adjacency sweep before minting a card.** D0 Q3 collects the evidence. |
| Stale card cites | card `refs`, and the `HVAC-ZONE-CONDITIONING-DEMAND-1` and `HVAC-SUPPLE-SEQUENCE-1` entries | Board hygiene | They should be `hvac.py:2780-2797`, `aggregation.py:4339-4341` / `:4474-4476`. They also describe "three inert suppressions", which §2 refutes. |
| State-of-play doc | — | No correction needed | §3.2 and §3.3 already state the reset-only rule correctly. If R2 ever ships, add a §3.3 row. |

## 11. D0 results
*(To be filled when D0 runs: Q1-Q4 tables, and the trigger decision.)*

## 12. Not done from the card's original scope
- **The thermostat "three protections" restore:** not built. §2 refutes the premise.
- **R1 (D7):** dropped (§3.1), because it is a circular witness.
- **R2 (fan):** parked with a measured trigger (§3.2). It is fully specified in §7.
- **Open question (d), the recheck primitive:** answered. `presence_fan_recheck` is not reusable (§0.5), and no new
  primitive is needed.
