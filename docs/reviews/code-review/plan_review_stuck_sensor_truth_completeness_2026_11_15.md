# Plan review: stuck-sensor truth (S1-S6) + crossing P3-D8b. Completeness framing (Tier 3 plan review 1 of 2)

Reviewed: `docs/planning/PLANNING_stuck_sensor_truth.md` and the "P3-D8 prerequisites" block in
`docs/planning/PLANNING_crossing_vision.md` at develop 82b013db; crossing code read from `feature/crossing-p3-first` @ 48d4bc94.
Reviewer: ura-planner (Mode 2), 2026-11-15.

**Verdict: PLAN-FIX-REQUIRED.** There are 3 HIGH findings. The S3 premise is false (chatter has never acted, see F1).
S3 changes fan actuation while claiming no behaviour change (F2). The S5 OFF write would be blocked by a chokepoint gate
the plan never names (F3). Scope: FOCUSED, but S5/S6 are a separate Tier-3 unit and should stay sequenced behind S1-S3.

## What was read (disclosure)

- HVAC STATE_OF_PLAY: header entries, §0-§4.3 (incl. §4.2b fans, §4.2c sweep), §10 ledger C1-C39, §11-§12 in full. I did
  not read §4.4-§9e line by line; I grepped them for fan content (only §9.3 Jaya radar, consistent with C27).
- PRESENCE STATE_OF_PLAY: §4-§6 in full, §10 ledger grepped for stuck / P22 / chatter / exclusion / substrate.
  SENSOR_FLEET_CLASSES.md in full. Card MEDIAROOM-FAN-LEFT-ON-STUCK-SENSORS-1 operator_2026_11_15_* fields in full.
- I did not read the two 11-15 audits or the D/G review in full. I relied on the plan's citations of them where I could
  not re-derive a fact from code.
- Neither the plan nor the crossing block re-asserts any HVAC §10 claim. C27 (the Jaya radar removed by the 4 h rule)
  agrees with S1's "radar keeps tolerance 0" rule.

## Findings (by severity)

### F1 HIGH: S3 premise is false. Chatter has run in SHADOW the whole time, because the select and the resolver read different config entries

- `ChatterModeSelect` is created only for the INTEGRATION entry (`select.py:50-60`). It reads and writes
  `CONF_CHATTER_MODE` on that entry (`select.py` `current_option` / `async_select_option`).
- The room resolver `_chatter_mode()` (`coordinator.py:3216-3260`) reads `nm_cycle_a_knob`. That function reads only the
  COORDINATOR_MANAGER entry (`_nm_cycle_a.py:83-90`).
- Live `.storage/core.config_entries`: the integration entry (01KAYV8P…) has `options.chatter_mode = "act"`. The CM entry
  (01KJEC3F…) has no `chatter_mode`, so the room resolver falls back to `DEFAULT_CHATTER_MODE = shadow` (`const.py:6256`).
- The `notification_log` confirms it. Every chatter NM from 11-14 through 11-15 21:49Z reads "WOULD quarantine sensor
  (shadow)", including rows written after the 15:47 CST restart (Garage B 21:49:28Z). The media NMs said shadow because
  the room tier really was in shadow. They are not stale text, and no per-room override exists.
- Consequences:
  - S3 step 0's "if stored act, no code" branch is wrong.
  - Fact 4 and the crossing block's "reads act live since 15:47" are wrong.
  - S2's "after S3 the Meross bit is chatter-excluded (act), so its edges drop" does not hold.
  - The S5 `chatter` trigger has never been able to fire.
  - Turning the knob "on" for real is a first-time house-wide behaviour change: Garage A/B ratgdo and the Master
    Bathroom InvisOutlet would start being quarantined. It was never live.
- Required:
  - Card the split-brain bug and fix it in S3, with one owner entry for the key. Either the select writes the CM entry,
    or the resolver reads the integration entry. Migrate the stored value.
  - Q3 must be re-asked as "turn act on for the first time", not "confirm act".
  - Correct fact 4, §1, C5 and the crossing block.
  - Add a test that the select's write is what `_chatter_mode()` returns.

### F2 HIGH: S3 resolver fix is a fan-actuation change in three rooms, filed as "Tier 1, no behaviour change today"

- `_radar_sole_on_set` → `is_radar` → `fan_veto.is_radar_entity` classifies by override, then CONF kind, then device
  family (`coordinator.py:6146-6177`).
- Today the Meross `…_sensor_presence_motion` bit (filed in `motion_sensors`, registry `model` `ms600-un`, `model_id`
  None, verified in `core.device_registry`) resolves `unknown`, so it is not radar-bearing.
- After S3 it is radar-bearing. A tick where only that bit is on becomes radar-sole. That makes Media, Guest Bedroom 1
  and Guest Bedroom 2 recheck-eligible, so the recheck can pause their fans. Guest Bedroom 1 is `room_temperature`, a
  URA-owned fan, so the recheck can really pause it today. It also changes the recheck window factor (1.5).
- The plan states both "no behaviour change today" and "makes media recheck-eligible … intended". Those contradict each
  other, and the plan leaves out GB1 and GB2.
- Required: Tier 2 minimum, an impact row per room (GB1 / GB2 / Media × Fan Mode × paused), and a test pinning GB1's new
  eligibility.
- Also fix a citation: the plan says registry `model_id ms600-un`. The string is in `model`; `model_id` is None. Each
  room has two Meross devices (`ms600-un` and `ms600 9.0.0`), so the golden test must name which device owns each entity.

### F3 HIGH: S5 OFF in a Fan Mode Off or occupied room is blocked by `_set_fan_state` gates the plan does not name

- `_set_fan_state` (`hvac_fans.py:~1839-1857`, Batch D G1) allows only `FAN_TRIGGER_RECHECK_PAUSE/_RESTORE` when
  `_is_room_fan_owned`. Every other trigger needs `_is_room_hvac_managed`. A new `FAN_TRIGGER_STUCK_CHECK` fails both
  in a Fan Mode Off room and returns False.
- The next guard (`occ == "on" and not is_exempt_from_guard` → return False) blocks the OFF in an occupied room. The
  stuck route requires the room to read occupied.
- The plan names only the oracle ALLOW at `fan_policy_oracle._compute_off_verdict`. Built from the plan as written, the
  stuck route would silently no-op in exactly the Media case.
- Required: name all three gates (G1 owner gate, `is_exempt_from_guard` set, oracle verdict). Give the stuck trigger an
  OFF-only owner rule. Add a test that the Media fixture (Fan Mode Off, paused, occupied) actually emits one
  `fan.turn_off`.

### F4 MEDIUM: S1 consumer table misses the radar-sole ring

- `_live_on_set` / `_radar_sole_on_set` (`coordinator.py:6158-6177`, caller `:4074`) iterate `_fusion_filter_active`.
- A ZV that S1 keeps excluded longer drops out of the on-set. A room with a ZV and a radar becomes radar-sole while the
  ZV is P22-excluded. That changes fan-recheck eligibility and the D1b capability ring, which feeds D2.
- Also missing: the trigger-source attribution loops (`coordinator.py:4040-4060`) and `STATE_MOTION_DETECTED`, which
  drives `_last_motion_bit_time`, the P24 failsafe freshness stamp. An excluded ZV stops refreshing P24.
- Required: add these rows with their effects.

### F5 MEDIUM: S1 house-impact statement conflates HVAC zone and presence zone

- The presence zone tier, nobody-home and path β read the substrate raw and ignore room exclusions (STEP-EXCLUDE-4,
  PRESENCE §4 zone tier; the plan's own §3 last row).
- So S1 does NOT let the presence zone empty while the ZV reads `on`. Only room `STATE_OCCUPIED`, and through it
  `hvac_occupied` / the HVAC zone rollup and HVAC retreat, change.
- The plan's "zone occupancy feeds nobody-home and path β" sends B and D reviewers down a path that does not change.
- Restate: room, HVAC zone, HVAC retreat / D6 / vacancy sweep (lighting denomination) are affected. The presence zone,
  census and house state are not, except through the S2 anchor.

### F6 MEDIUM: S1 class gate uses the wrong predicate

- `is_fan_immune_witness` is true for kinds `bed`, `camera_presence` and `ble_presence` (`sensor_capability.py:359-370`).
  Those are still-person holders. SENSOR_FLEET_CLASSES rule 3 names fan-immune and holds-a-still-person as TWO properties.
- Reusing the fan-immune predicate as "not a still holder" gives a bed sensor a 10 s tolerance.
- Before S3 lands, the MS600 bit resolves `unknown`, so it would get tolerance too.
- Required: a still-holder predicate (radar kind or family, `bed`, `camera_presence`, override) and an explicit S3 → S1
  ordering (the plan runs them in parallel).

### F7 MEDIUM: S1 spec gaps the builder will guess at

- (a) A sub-tick `off` that no tick observed: the on-state's `last_changed` is newer than the run start, but
  `_p22_off_since` was never set. The spec gives no rule (keep, or reset at `last_changed`), yet
  `test_p22_pulse_between_ticks_uses_last_changed` implies one.
- (b) "No stamp yet → stamp as today": today stamps tick `now` (`coordinator.py:3720`), while the ≥ tolerance branch
  stamps `last_changed`. Pick one.
- (c) `unavailable` "neither ends nor extends", but the clock keeps running across the dead span. A sensor dead 4 h that
  returns `on` is excluded at once, a real person included. State whether dead time counts.
  `feedback_dead_sensor_is_faulty_equipment` suggests freezing the clock.

### F8 MEDIUM: S5 INV-S5-OFF-ONLY has a reachable `turn_on` in a paused room

- `restore_after_recheck(leave_off=True)` overrides to a real ON when a manual-ON hold is live
  (`hvac_fans.py` C1a branch, "recheck leave-off overridden — manual-ON hold live, restoring ON"). That ON is
  `fan.turn_on` with `percentage`.
- The arm-time `manual_on_hold_live` veto does not cover a hold adopted mid-window.
- Required: the stuck route decides this branch explicitly (the operator rule says no ON), and
  `test_fan_mode_off_writes_off_only` exercises it.
- Also confirm in the build that `actuator_reconciler._resolve_fan` stays silent for a paused Room-temperature room
  during the window. I did not verify it.

### F9 MEDIUM: S5 veto table is incomplete

- It omits `mmwave_history_short` and `not_mmwave_sole`, the legacy path when
  `OCCUPANCY_SOURCE_CAPABILITY_ROUTING_ENABLED` is False.
- It does not say which BLE-ladder exit authorizes a Tier-0 room. `trust_sensors_off` is KEPT, default True per
  `const.py:903`, so fine today, but a False knob silently disables the stuck route.
- Name the stuck route's ladder entry.

### F10 MEDIUM: required doc updates not scheduled

- S5 changes the HVAC STATE_OF_PLAY §4.2b table (Fan Mode Off → fan recheck "never") and the §4.2b / PRESENCE §6
  "B-M1: a probe must not turn a person's fan off" accepted-consequence text.
- Both docs require an update in the same commit. The plan does not list it as a deliverable.

### F11 MEDIUM: S6 twin resolution uses a name test

- "`via_device` to the same bridge AND equal device name" is name matching, which REGISTRY-NOT-NAMES forbids.
- Live registry: HomeKit twins (`fan.media_room_ceiling_fan_2` etc., `homekit_controller`) and Bond twins are on
  separate devices. Use the operator-declared twin map only, with no name fallback.
- Also specify how a write to the Bond twin, an entity not in the room's `fans` list, routes through `_set_fan_state`,
  the oracle room lock and the `fan_off` activity row. Today the chokepoint writes `snapshot["entities"]`, the
  configured HomeKit twin.

### F12 LOW

- (a) S2's `entities_for` should extract the existing inline comprehension (`occupancy_substrate.py:382-385`), not add a
  parallel one.
- (b) The substrate maps each entity to ONE (room, kind). An input listed by two rooms dispatches under one room while
  `input_room_stuck_excluded` may consult the other. Add a test.
- (c) `_d2_house_state_allows` fails OPEN (True on exception or missing presence). Reused as the sleeper gate, it
  releases a P22 radar on error. Fail closed for the anchor.
- (d) S4:
  - `fire_stuck_signal` latches per (kind, key, calendar day), so an AWAY episode crossing midnight pages twice, against
    INV-S4 "once per episode". Put an episode id in the key or relax the invariant.
  - "No camera person" names no fact. Per the F1-F5 rule, state the source (F2 census or F4 sighting) and consumer class.
  - The stuck-signal global kill switch also gates S4.
- (e) The phantom citation `const.py:6292-6296` is wrong. Those lines are chatter provenance; `phantom_retro` is
  `memory_writers.py:138`, a learning episode. Excluding stuck-route fan-offs removes the one learning signal that
  records "fan caused the hold". Consider tagging instead of excluding.
- (f) The S5 zero-fire trip-wire's denominator ("a stuck exclusion lasted ≥ 30 min in a fan room over 14 d") has no
  named persisted producer. Exclusions are RAM per tick.
- (g) Formatting: D-OP5 sits indented under D-OP4, and the S5 verdict paragraph runs long. Otherwise one clean document.

## Checklist results

- Institutional-context table: present and mostly right. Wrong items: the chatter row (F1), the MS600 row field (F2) and
  the phantom cite (F12e).
- Falsifiable invariants: INV-S1, S2, S3, S4, S5-OFF-ONLY and S6 are all falsifiable. INV-S5-OFF-ONLY is falsified as
  written (F8), and INV-S4 by the latch granularity (F12d).
- Re-enumerated consumers of `_sensor_on_since` / P22:
  - Readers: `coordinator.py` 2375-2400, 2437-2570, 3713-3771; `sensor.py:2526`, `:2597`.
  - Exclusion-set readers: `_fusion_filter_active` call sites at 2317, 4016-4058, 6163;
    `camera_input_room_quarantined` 2794; branch getter; `get_stuck_sensor_kinds` → `sensor.py:5730`.
  - Missing from the plan: 6163 / 4074 (F4) and 4040-4060.
  - The duty-cycle detector does not read `_sensor_on_since` (confirmed).
- Knobs: all on rung 1 with kill semantics, except the S6 twin map, which needs a home. Acceptance criteria discriminate.
  Non-goals are explicit.

## Answer to the chatter question

The select and the room resolver read different config entries (F1). The 11-14/15 media NMs were accurate: the room
tier was in shadow. The NM text is not stale and no room override exists. S3's premise ("already act, config only") does
not hold. It needs a code fix plus a first-time operator decision on house-wide act.
