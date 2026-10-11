# PLANNING — Running-fan mmWave noise rejection (fix-up of the existing mechanisms)

**Status:** problem/solution framing approved for planning 2026-10-11 (operator). **Operator decisions 2026-10-11: C1 = C1a (leave the fan off after a VACATED verdict). C2 = REUSE the existing capability layer. C3 = reuse the quarantine primitive.** Tier 2 (cross-mechanism: presence ↔ fans ↔ lights). Requires: institutional-context section + prior-art scan + one adversarial plan review before build (CLAUDE.md). READ FIRST: `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`, `docs/architecture/SENSOR_FLEET_CLASSES.md`.

**Evidence base (measured 2026-10-11, 7-day recorder window + URA DB since v5.84.1):** Study A held occupied ~26 h/week while empty with the fan on (1,541 min) and none of the existing mechanisms reduced it; fan-recheck released Study A correctly 28× but 27 were undone by its own fan restore (mmWave re-latch 11–696 s later, median ~60 s); D2 sustain demotion fired 0× in every room and is unreachable in 7/10 fan rooms; the 5 s transition gate fired 27× in 7 days, 23 on dead/flapping fan entities, and 26/27 were followed by occupancy 2–12 s later. Radars latch 55–240 s after a fan starts (p50) and clear 28–825 s after it stops, by sensor family.

**Falsifiable invariant (to be finalised in plan review):** for a room whose ground truth (BLE location ±3 min) is empty and whose fan is believed ON, occupancy held only by fan-susceptible presence sensors cannot persist longer than N minutes (N set from the measured clear-time distribution) — while a person who is present and still is never vacated by these changes during sleep-family house states.

**Config companion (no code, done alongside):** point Guest Bedroom 1 / Media / Game Room fan config at their live `_2` entities; Master Bedroom RF fan + Exercise `fan.fan_switch_3` need physical fixes (operator). Study A ZG-204ZK tuned 2026-10-11 (motion 5, static 6, distance 2.5 m, anti-interference ON).

---

## C1 — Fan recheck undoes its own correct "empty" verdict

**Problem.** The pause-and-recheck stops the fan, sees mmWave clear, correctly declares the room empty — then immediately restores the fan (`presence_fan_recheck.py:794 _fan_restore`). The restored airflow makes the radar re-detect ~60 s later and the room is occupied again. The 5 s transition gate is armed by the restore (the fan listener `presence.py:3720` stamps it) but expires long before the re-latch. Net effect in Study A: 1 of 28 correct releases stuck.

**Solution.** After a VACATED outcome, do not hand occupancy straight back to the fan-susceptible sensor. Two variants for plan review to choose between:
- **C1a (preferred if comfort allows):** on VACATED, leave the fan OFF (it was only running for a person who has left); the normal fan logic turns it back on when real occupancy returns.
- **C1b:** restore the fan, but for a post-release window sized from the measured latch distribution (~6 min, p90 ≈ 344 s pooled Zigbee) a new occupancy driven **only** by fan-susceptible sensors is not admitted; any fan-immune witness (real PIR, ZV in steady state, BLE, door) admits immediately.

## C2 — Sensors are classified by entity name, so D2 can't run where it should

**Problem.** D2 (running-fan sustain demotion) needs a "real motion sensor" to know the room is genuinely still. `_d2_motion_sensors_present()` (`coordinator.py:2159`) filters motion sensors by the name pattern `mmwave|radar|presence|ld2410|ld2412` (shared with `fan_veto.MMWAVE_NAME_PATTERN`, `fan_veto.py:61`). Every Hobeian ZG-204ZV is named `…_presence`, so rooms whose motion sensors are ZVs count as having none → D2 never fires (7/10 fan rooms). The same name rule makes the fan-veto ignore ZVs while D2/recheck treat them as motion — three mechanisms disagree about one sensor.

**Solution.** Classify each configured sensor by **device capability** (device `model_id` → class from `SENSOR_FLEET_CLASSES.md`: holds-still yes/no, fan-susceptible yes/no/steady-only), via `sensor_capability.py` (extend, don't invent), with the name pattern only as a fallback for unknown models. All four mechanisms (gate, D2, recheck, veto) read the same answer to "is this a fan-immune witness?". ZV = motion-class, fan-immune in steady state but not within ~5 min of a fan switching on (measured).

## C3 — Dead fan entities fake fan activity

**Problem.** Fan entities that flap `unavailable ↔ off/on` every ~20 s are stamped as fan transitions (`presence.py:3752` stamps any state change) and, where a flap lands on `on`, read as "fan running". 23 of 27 recent gate fires came from such flaps; Master Bedroom's RF fan flips to `on` while dead. Every fan mechanism is fed a false fan signal.

**Solution.** Only real fan transitions count: ignore changes to/from `unavailable`/`unknown` when stamping transitions; treat a fan whose entity is unavailable as "fan state unknown" (mechanisms that need "fan on" do nothing rather than guess). Surface a per-room "fan entity unreliable" diagnostic so a misconfigured fan is visible (config fix is the operator's).

## C4 — Recheck timing is one-size-fits-all

**Problem.** The recheck waits spindown 30 s + watch window 60 s for the radar to clear. Measured clear time after fan-off varies by sensor family: Study A Zigbee 51/64 s (p50/p90) — fits; Jaya Zigbee 124/825 s; Living Room one case 1,987 s — those false-negative ("still occupied") and then sit out a 1,800 s cooldown (19 such misses in Study A in one week).

**Solution.** Watch window per sensor class/room, defaulting from the measured family distribution (configurable, on the knob ladder), and cooldown 1,800 s → ~900 s. Knob placement per the Numbers-Get-Knobs ladder.

## C5 — The 5 s fan-start gate blocks almost nothing (decide in plan review)

**Problem.** Radars latch 55–240 s after a fan starts; the gate only delays occupancy creation by up to 5 s. After C3 removes the fake triggers, it has almost no remaining effect.

**Solution.** Either retire it (window = 0, keep the counter for evidence) or fold it into C1b's corroboration window generalised to every fan-on transition: for ~6 min after a fan switches on, a mmWave-only new occupancy needs a fan-immune witness. Plan review decides; C1b/C2 make the generalised form cheap.

## Measurement regime (acceptance)
Baseline = 2026-10-04→10-11 (scripts in session scratchpad `fan_mmwave/`, to be moved to `scripts/fan_noise/`). One week after ship, re-run: per-room empty+fan-on occupied minutes, false-hold length distribution, light minutes in empty rooms, mechanism fire/success/undo counts, and the guard metric: occupied→vacant transitions while BLE says a person is present (must not rise). Study A tuning is measured separately (it changed 2026-10-11, before this cycle) so its effect isn't credited to the code.

---

## Rejected or deferred solutions (and why)
| Option | Verdict | Reason |
|---|---|---|
| Use the radar's internal "motion" output as the fan-immune witness | **Rejected** | Study A's ZG-204ZK exposes no separate motion output; where radars do (LD2410 moving target), the moving channel is exactly what a fan's Doppler triggers (Jaya: moving channel lit with fan alone). A PIR element inside a combo unit would work — none in Study A. |
| Add the Study A InvisOutlet motion sensor as witness | **Rejected (operator)** | Unreliable for a long time; on the do-not-use list. |
| "Re-aim before any tuning — tuning can't recover a fan in view" | **Rejected (operator correction)** | Wrong for the ZK: anti-interference + distance tuning do vacate Study A; tuning is a first-class lever. Re-aiming stays optional. |
| Buy a second sensor (ZV/PIR) per fan room | **Deferred** | Cost; try tuning + software first, measure, then decide room by room. |
| Widen the 5 s gate to minutes as-is | **Rejected** | The gate only delays creation and doesn't sustain-protect; a longer delay still lets the latch through. Superseded by C1b/C5's corroboration window. |
| Move Living Room's mmWave out of `motion_sensors` | **Rejected (retracted)** | It is a ZG-204ZV motion-class sensor — correctly filed. The real bug is name-based classification (C2). |
| Rely on BLE alone as the witness | **Deferred** | BLE room location is noisy (operator's sensor changed 4,262×/week); usable as one witness among several, not alone. |
| Fan-distance-band veto in URA (ignore detections at the fan's range while it runs) | **Deferred** | High value only for distance-reporting radars (ESPHome LD24xx, Meross); needs distance/energy recorded first; Study A's Zigbee reports no distance. Separate cycle after this one. |
| Require corroboration for any mmWave-only hold while a fan runs (general rule) | **Deferred** | Highest coverage but risks dropping still/sleeping people; revisit with this cycle's measured residual. |
| Per-room learned energy baseline (background subtraction) | **Deferred / parked** | Needs per-bin energy history and labelled data; mostly superseded by on-device tuning. |
| URA writes radar settings dynamically while the fan runs | **Deferred** | Carded as URA-SENSOR-TUNING-1 Phase B; Phase A (static, URA-owned settings) first. |
| LD2450 + polygon exclusion zones | **Deferred (hardware)** | Proven fix, but hardware; only for rooms that still fail after this cycle. |


## Operator decisions + prior-art findings (2026-10-11)
- **C1 → C1a.** On VACATED the recheck leaves the fan OFF; normal fan logic restarts it when real occupancy returns.
- **C2 → REUSE, no new classification logic.** `domain_coordinators/sensor_capability.py` already defines kinds (`pir`, `pir_split`, `mmwave`, `motion`, `occupancy`, …) with trust classes, resolved by `derive_capability()` (`sensor_capability.py:172`) from the room CONF lists plus per-entity operator overrides `CONF_SENSOR_CAPABILITIES`. Live: Game Room already declares its ZV `binary_sensor.0xa4c1382e60e05225_presence` as `{"kind": "pir"}`; Guest Bedroom 2 declares a Matter sensor `mmwave`. The defect: the fan mechanisms don't consult it — D2 `_d2_motion_sensors_present()` (`coordinator.py:2159`) and `fan_veto` use the entity-name regex, so even Game Room's declared `pir` is discarded. C2 = route D2 / fan_veto / recheck eligibility / transition gate through `derive_capability()`; declare the remaining ZVs `pir` via the existing override (or a model_id-based default inside the capability layer — plan review decides, prefer the smallest change).
- **C3 → reuse quarantine.** Fleet measurement (24 h, recorder): six fan entities flip ~2,050×/day, ~50% `unavailable` (media_room/game_room/guest_room_down ceiling fans, both patio ceiling fans, RF master-bedroom ceiling fan — all superseded by `_2` live entities); ~7 bathroom/laundry fans flap ~50% unavailable at 38–594/day; real fans 3–200/day with ~0% unavailable. Keep the one-line guard (don't stamp unavailable/unknown as a fan transition; unavailable = fan state unknown). Quarantine via the existing `SensorExclusionSet` primitive with an availability-flap rule rather than fan-only logic — the existing chatter rule (sub-1 s T_floor) does not fit a ~40 s flap, so the new rule belongs in OC-STUCK-SENSOR-GENERALIZE-1 (stuck/flap across all device kinds); this cycle only needs the guard + "unknown" semantics.
