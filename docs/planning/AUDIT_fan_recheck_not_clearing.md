# AUDIT — Fan-interference recheck not clearing Study A / Living Room

Card: **FAN-RECHECK-NOT-CLEARING-1**
Date: 2026-08-18 (live evidence ~03:10–03:22 UTC / 21:17–22:17 CT)
Type: read-only investigation (code + live). No code changed.

## TL;DR verdict

**CODE gap, not config.** The fan-pause recheck is correctly enabled for both
rooms (master switch ON, both per-room switches ON, each room has a fan + mmwave
mapped). It is not clearing them because the recheck has a **hard, house-wide
`house_state == SLEEP` veto** (`presence_fan_recheck.py:373-375` and `:854-856`),
and the house was in `sleep`. During sleep the fan-pause recheck **never arms in
any room**, so the one mechanism designed to disprove fan-shake mmwave presence
is switched off exactly when these two empty non-bedroom rooms exhibit it.
There is **no config knob** to change this (the veto is a hardcoded literal).
Fixing it needs a code change to scope the SLEEP veto to bedroom / keep-fan-on
rooms instead of the whole house.

**Update (operator follow-up):** SLEEP is the cause it isn't clearing *now*, but
it is NOT the sole reason across the evening — see "Pre-sleep (guest window)
analysis" below. Ordered causes: (a) ~45 min guest window — NOT a house-state
block (there is no guest veto; guest is permitted), a substantive gate whose
identity is undetermined live; (b) ~120 s home_night — structurally too short for
the ~150 s recheck sequence; (c) sleep veto. The corrected fix scope did NOT grow
into "widen eligible states" (there is no whitelist to widen); the SLEEP-veto
scoping remains primary and also cures (b).

## The two distinct mechanisms (don't conflate them)

1. **Fan-interference GATE/HOLD** — `presence.py:_apply_fan_interference_gate`
   (:3770). Passively HOLDS a room occupied. When a room is mmwave-sole + fan-on
   + BLE-uncorroborated, it sets `tracker._fan_interference_hold_until` and
   refreshes it **every tick** the room stays suspect (:3986). This is where the
   `fan_interference_ladder` verdicts come from: L1=room-BLE-present (clears),
   L2=adjacent-BLE, L3=zone-BLE-absent (strongest discount), "none"=no BLE infra.
   These are DISCOUNT/HOLD labels, **not** the recheck's rungs.

2. **Fan-pause RECHECK** — `presence_fan_recheck.py` `FanRecheckManager`. The
   ACTIVE mitigation: arm → pause the fan → observe whether mmwave drops with
   airflow stopped → if it drops, VACATE (`apply_fan_recheck_release`). This is
   the mechanism the operator expects to clear the rooms. It has its OWN ladder
   (`fan_recheck_ble_ladder_layer`, values L1/L2/L3/none — different meaning from
   the gate ladder).

The operator's `fan_interference_ladder: {"Living Room":"L3","Study A":"none"}`
is mechanism (1)'s hold verdict, NOT the recheck rung. Live room attrs confirm:
Study A `ble_corroboration_layer:"none"`, Living Room `"L3"`.

## Designed recheck mechanism (file:line)

- Trigger eligibility: `_is_eligible` (`presence_fan_recheck.py:339`). All gates
  must pass: master enabled, room enabled, fan-control not disabled, **not
  sleep**, room `occupied`, mmwave-sole for N ticks (default 3,
  `DEFAULT_FAN_RECHECK_MMWAVE_HISTORY_TICKS`), ≥1 fan configured AND on, boot
  settled, not in manual-off cooldown, rate cap, then the BLE drop-authorization
  ladder (L1 present → veto; else classify L1/L2/L3/none).
- On eligible → `_enter_armed` (:508) waits `ARM_DELAY_S` (default 60), re-checks
  `_still_armed_eligible` (:840) → `_enter_paused` (:582) calls
  `fan_controller.pause_for_recheck`, waits `SPINDOWN_S` (30) + `WINDOW_S` (60,
  × room-type factor) → `_on_pause_window_done` (:660): if
  `presence_detected` is False AND `occupancy_source != "mmwave"` →
  `OUTCOME_VACATED` → `_restore` (:678) calls
  `room_coord.apply_fan_recheck_release()` to drop the hold. That is the "unhold".

## The blocking gate — exact trigger condition

```
# presence_fan_recheck.py:373-375  (in _is_eligible)
house_state = getattr(self._presence, "house_state", "")
if house_state == HouseState.SLEEP:
    return self._veto(room_name, "sleep_state")
```
and the re-check after arm delay:
```
# presence_fan_recheck.py:854-856  (in _still_armed_eligible)
house_state = getattr(self._presence, "house_state", "")
if house_state == HouseState.SLEEP:
    return False
```

The docstring at :360-372 states the intent explicitly: the pause "is exactly the
wrong operation during home_night / waking when people are awake… and would
notice a fan pause," and it must not fight the v4.7.13 keep-bedroom-fans-on-
through-sleep logic. But the guard is **house-wide** — it suppresses the recheck
in EVERY room during sleep, including empty non-bedroom rooms (Study A, Living
Room) where no sleeper is present to notice a pause. That over-broad scope is the
gap.

## Live evidence (2026-08-18 ~22:17 CT, house = sleep)

- `sensor.ura_presence_coordinator_presence_house_state` = **sleep**,
  `fan_interference_active: true`.
- `switch.ura_presence_coordinator_fan_recheck` = **on** (master enabled).
- `switch.study_a_study_a_fan_recheck` = **on**;
  `switch.living_room_living_room_fan_recheck` = **on** (both rooms enabled).
- `binary_sensor.study_a_occupied` = on; `occupancy_source: mmwave`;
  `tier1_provenance: {motion:false, mmwave:true, occupancy:false}`;
  `fan_on: true`; `fan_interference_suspect: true`;
  `ble_corroboration_layer: "none"`; `fan_recheck_state: "idle"`;
  `fan_recheck_last_attempt_iso: null` (recheck has NEVER run this room);
  fan mapped = `fan.polyfan_dreo704s_wifi_studya`; mmwave =
  `binary_sensor.mmwave_zigbee_studya_presence`.
- `binary_sensor.living_room_occupied` = on; `occupancy_source: mmwave`;
  `fan_on: true`; `fan_interference_suspect: true`;
  `ble_corroboration_layer: "L3"`; `fan_recheck_state: "idle"`;
  `fan_recheck_last_outcome: "occupied_confirmed"`,
  `fan_recheck_last_attempt_iso: 2026-08-13T18:23 CT` (last actual run was 5 days
  ago, in a NON-sleep window); fan mapped =
  `fan.towerfan_dreopilotmaxs_wifi_livingroom`; mmwave =
  `binary_sensor.screek_human_sensor_l13_2412s_presence`.

Both rooms are `fan_recheck_state: idle` with the fan on and mmwave sole — i.e.
they satisfy the *substantive* recheck preconditions; the ONLY thing keeping them
idle is the sleep veto. Living Room's last recheck (5 days ago) landed
`occupied_confirmed`, and Study A has never had one — consistent with the recheck
only ever getting a chance to run outside sleep.

Note the primary reason these rooms READ occupied is that the mmwave sensor
itself reports presence (fan-induced shake) — `tier1_provenance.mmwave: true`.
The gate/hold is secondary; even with `fan_interference_hold_active: false` at
read time, the raw mmwave ON keeps the room occupied. The recheck is the only
mechanism that disproves that raw mmwave — and it is off in sleep.

## CONFIG vs CODE verdict (the four candidates)

- (a) disabled by config? **No** — master + both per-room switches ON.
- (b) fan/mmwave unmapped or wrong entity? **No** — both rooms have a fan and
  mmwave mapped (see live attrs above); `fan_on: true`.
- (c) gated off by a knob? **No operator knob exists.** The block is the
  hardcoded `HouseState.SLEEP` literal (no `CONF_*`).
- (d) firing but mmwave not dropping / pause too short? **No** — it is not firing
  at all (`fan_recheck_state: idle`, Study A `last_attempt_iso: null`).
- (e) code gap where the path never reaches the pause? **YES** — the house-wide
  SLEEP veto returns before arming, in both `_is_eligible` and
  `_still_armed_eligible`.

## Can the operator fix it via config today?

**No.** There is no config field, Number, or Switch that lifts the sleep veto or
scopes it per-room. Setting anything in the options flow will not help — the
recheck is already fully enabled; the sleep literal cannot be reached by config.

## Recommended fix (scope = code)

Scope the SLEEP veto so it suppresses the recheck ONLY for rooms whose fan URA
deliberately holds on through sleep (the v4.7.13 keep-bedroom-fans-on set) — i.e.
bedroom-type / keep-on rooms — and ALLOW the recheck to run during sleep for
empty non-bedroom rooms (studies, living/media common areas) where no sleeper
would notice a brief fan pause. Concretely, in both `_is_eligible` (:373) and
`_still_armed_eligible` (:854): replace the unconditional
`house_state == SLEEP → veto` with a check that only vetoes when the room is in
the keep-fan-on-through-sleep set (reuse the same room-type / hvac_fans
keep-on predicate the v4.7.13 logic uses — verify its source before wiring; do
not fabricate the predicate). Guard the change so the v4.7.13 contract is
preserved for bedrooms.

Governance / knob ladder: if the behavior should be operator-tunable, add a
named module constant or CM-options gate (e.g. a "recheck-during-sleep for
non-keep-on rooms" enable) rather than an inline literal, per Numbers-Get-Knobs.
Kill-switch semantics: the existing master switch already disables the whole
mechanism.

Tier note: this touches the presence fan-recheck state machine and interacts
with the v4.7.13 sleep-fan trust contract (cross-coordinator: presence ↔
hvac_fans) — regression-prone, so Tier 2-DB (3 framing-disjoint reviews) per
standing policy.

## Pre-sleep (guest window) analysis — added on operator follow-up

The operator asked: was the recheck failing to fire BEFORE sleep too? History says
yes (Study A `fan_recheck_last_attempt_iso: null` — it has NEVER armed; Living
Room's last arm was 2026-08-13, 5 days ago). So the SLEEP veto is **not the sole
cause**. Verified against code:

**Timeline (live history, Study A):** guest 18:59:47 → home_night 22:02:28 →
sleep 22:04:28. Fan + mmwave both latched ON continuously at 21:17:43. So
21:17:43→22:02:28 (~45 min) the room was fan-on + mmwave-sole while house =
**guest**, then a ~120 s home_night, then sleep.

### 1. Is there a GUEST veto or a state whitelist? NO.

Grep of `presence_fan_recheck.py` for every `house_state` / `HouseState`
reference returns exactly two sites, both the SLEEP check (`:373-375` in
`_is_eligible`, `:854-855` in `_still_armed_eligible`). **There is no state
whitelist and no GUEST veto.** `_is_eligible` permits every house state except
SLEEP. The per-tick driver `on_room_tick` (called from `presence.py:6893-6903`)
is **ungated by house state** — it fans out to every room each inference tick.
(Note: the `house_state in (SLEEP, WAKING, HOME_NIGHT)` veto at `presence.py:4042`
belongs to a DIFFERENT mechanism — `_compute_mmwave_fan_demoted_rooms`, the mmwave
demotion path — NOT the recheck. Do not conflate them.)

→ The operator's "guest veto" hypothesis is **refuted by the code**. During the
21:17–22:02 guest window, house-state did NOT block arming.

### 2. home_night window too short — CONFIRMED.

Minimum time from idle to a completed VACATE (constants in const.py):
`ARM_DELAY_S 60` (:648) + `SPINDOWN_S 30` (:652) + `WINDOW_S 60` (:657) =
**150 s** (room-type factor 1.0 for study / living_room — neither is
bedroom/media, so no `ROOM_TYPE_RECHECK_FACTOR` inflation). Plus the VACATE only
lands if mmwave actually drops in the window. home_night lasted 22:02:28→22:04:28
= **120 s < 150 s**. Even if it armed at the instant home_night began it could
not complete before sleep; and when sleep begins, `_still_armed_eligible` (:854)
returns False and aborts the in-flight cycle. A home_night this short can NEVER
complete a recheck.

### 3. Complete, ordered cause enumeration

- **(a) 21:17–22:02 GUEST (~45 min): NOT a house-state block.** The recheck
  permits guest. It did not arm for a *substantive-gate* reason, not a state
  reason. Which gate is **undetermined from current live state**: the RAM veto
  counters reset on the (apparently recent) reboot, so they do not cover this
  window. Present-day live reads: Living Room diagnostic
  `sensor.living_room_living_room_fan_recheck_state` shows
  `fan_recheck_eval_count = 1`, `fan_recheck_veto_counts = {'not_occupied': 1}`
  since boot; Study A's diagnostic sensor is absent. These since-boot counters
  are NOT evidence about the guest window. **Leading hypothesis (unverified):**
  during a guest gathering, people were in or adjacent to these common rooms, so
  the BLE drop-authorization ladder (`_is_eligible` L1 room-present veto :435-440,
  or L2 adjacent-present veto) correctly vetoed — which would be *correct*
  behavior, not a defect. Other candidates: mmwave-sole `N`-consecutive-tick
  history (:381-394) if `occupancy_source` toggled, or `boot_settle` (:407) if the
  reboot was inside the window. NOT confirmed live.
- **(b) 22:02–22:04 HOME_NIGHT (~120 s): structurally too short** for the ~150 s
  arm+pause+observe sequence (see §2). CONFIRMED from code.
- **(c) 22:04+ SLEEP: the house-wide SLEEP veto** (:373-375, :854-855).
  CONFIRMED.

Is the set complete? For (b) and (c) yes, from code. For (a) the *category* is
established (substantive gate, not house-state) but the *specific* gate is not
live-confirmed — flagged as the open item below. No evidence of a minimum
sustained-presence duration gate beyond the 3-tick mmwave-sole history.

### 4. Corrected fix scope — did it grow?

**No net growth of the house-state fix, and importantly NOT toward "widen the
eligible states."** There is no state whitelist to widen; guest is already
eligible. Concretely:

- The primary fix remains **scoping the SLEEP veto** so it suppresses the recheck
  only for keep-fan-on-through-sleep (bedroom-type) rooms, letting empty
  non-bedroom rooms be rechecked during sleep. This single change ALSO cures
  cause (b): a room that transitions through a sub-150 s home_night into sleep
  would then get its recheck window *during the ensuing sleep* instead of being
  perpetually blocked. So (b) needs no separate fix.
- Cause (a) does **not** call for a house-state widening (guest is already
  permitted). If the guest-window block was the BLE ladder with people genuinely
  nearby, that is correct and needs no change. Only if a live guest-window
  capture shows a *wrong* veto (e.g. mmwave-tick-history flapping, or an
  over-broad L2 adjacency) would an additional fix be scoped — deferred pending
  evidence.

Net: fix scope is essentially unchanged (still "scope the SLEEP veto to
bedroom/keep-on rooms"), with the added understanding that this same change also
resolves the home_night-too-short case. The guest-window cause is parked as an
evidence-gated open item, not an assumed second fix.

## Open item to verify before building

Why are Study A and Living Room FANS on during sleep at all (they are not
bedrooms)? If a non-URA/manual actor or a different keep-on path is running
them, confirm that the recheck's `pause_for_recheck` / `restore_after_recheck`
round-trips correctly against these specific Dreo fan entities (they must be the
entities `FanController` actually manages, else `_enter_paused` bails with
`no_managed_fan`). This does not change the primary finding (sleep veto), but it
determines whether the fix will successfully actuate once the veto is scoped.
