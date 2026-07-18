# PLANNING — BLE Extend, Never Create

**Cycle:** `ble_extend_not_create`
**Trigger:** 2026-07-17 21:16-21:47 Master Bathroom strobe. Cold room
(no PIR/mmWave from 21:01-21:38); Bermuda ping-ponged the phone between
Master Bedroom / Master Bathroom / Ezinne Makeup; every flap fired
`occupancy_entry (source: ble)` -> `light_turn_on` -> vacate -> off.

**Root cause:** `coordinator.py:1808` (pre-fix) had
`ble_allowed = direct_ble` unconditionally, admitting Tier-1 direct-BLE
rooms with no motion confirmation. A cold-room Bermuda flap CREATED
occupancy.

## Load-bearing invariant (falsifiable, Tier-3 discipline)

For any room, on any tick of `_async_update_data`, the BLE block at
`coordinator.py:1794-1870` must satisfy BOTH:

- **(a) NEVER CREATE.** If the room has (i) no recent physical motion
  within `BLE_MOTION_CONFIRM_MULTIPLIER x occupancy_timeout` AND (ii) the
  occupancy CHAIN was broken on the previous tick
  (`self._last_occupied_state is False`), the BLE block MUST NOT set
  `data[STATE_OCCUPIED] = True` — regardless of BLE tier (direct or
  shared), regardless of `ble_persons` truthiness.
- **(b) EXTEND indefinitely under an unbroken chain (fix-up B-HIGH-1).**
  If the room's occupancy CHAIN is unbroken
  (`self._last_occupied_state is True` from the previous tick), the BLE
  block MUST admit and hold — indefinitely, bounded only by the
  pre-existing 4-hour failsafe at `:1760`. This preserves the still-body
  sleep hold that pre-fix Tier-2 semantics guaranteed.

**Global kill:** `BLE_MOTION_CONFIRM_MULTIPLIER = 0` disables the BLE
hold entirely (predicate always False, both legs). Documented on the
constant at `const.py:365-375`.

## Two-leg admission predicate

```
ble_allowed = MULTIPLIER > 0 AND (
    chain_unbroken                              # leg (a) — indefinite
    OR
    motion_within_multiplier_x_timeout_window   # leg (b) — handoff tick
)
```

**Chain signal:** `self._last_occupied_state` (verified prev-tick
semantics — mutations at `coordinator.py:2274 / 2280 / 2302 / 2329 /
2471`, all AFTER the BLE block at `:1794`).

**Motion leg guards:**
- Negative motion_age (NTP jump / manual clock set) fails the motion
  leg. (A-LOW-1 note: this is intentional hardening vs pre-fix Tier-2
  behavior, which had no clock-skew defense on the BLE path — the fix
  brings it in line with the failsafe pattern at `:1730`.)
- Strict-less-than the window (age==threshold rejects; see T3).

**Seed:** `if not self._last_motion_time: self._last_motion_time = now`
inside the admitted branch, AFTER the predicate. Reachable via the
chain leg (previously dead when the motion leg was the sole admission
path). MUST remain below the predicate — hoisting causes motion-leg
self-confirmation on the next tick (M2 anchor).

## Deliverables

### D1 — Chain-leg predicate (production)

Two-leg predicate above at `coordinator.py:1807-1858`.

**Acceptance Criteria:**
- **Verify:** cold room + BLE flap 6 ticks -> never occupied
  (T1 fixture repro).
- **Verify:** chain unbroken + motion age past window -> STILL HELD
  (sleep-hold pin).
- **Verify:** chain broken + motion age past window -> REJECTED (even
  with direct BLE).
- **Verify:** MULT=0 kill switch suppresses both legs.
- **Verify:** negative motion_age fails motion leg (chain still admits
  independently).
- **Test:** `test_masterbath_2026_07_17_repro_ble_flap_never_creates_occupancy`,
  `test_sleep_hold_pin_chain_extends_past_motion_window`,
  `test_sleep_hold_chain_broken_rejects_with_stale_motion`,
  `test_five_tick_chain_motion_confirm_then_chain_extend_then_exit`,
  `test_kill_switch_multiplier_zero_disables_ble_hold_even_with_fresh_motion`,
  `test_boundary_clock_skew_negative_motion_age_rejects`.
- **Live:** on the running house, verify Master Bathroom does not
  strobe on cold-room BLE flaps AND that overnight Master Bedroom sleep
  hold persists across BLE-only ticks (chain leg fires) up to the
  4-hour failsafe.

### D2 — Camera-block source guard (frozen SHA)

`test_camera_block_unchanged_by_this_cycle` — hard-coded SHA256 of the
`v3.5.1` camera block; fails loudly on accidental co-edit.

**Acceptance Criteria:**
- **Verify:** SHA equals frozen literal
  `2e80de19f48a2477d8fb1dfab253b82c670a419e9c22b0dd5cd7d902780b7e0b`.
- **Test:** `test_camera_block_unchanged_by_this_cycle`.

### D3 — Mutation anchors (Reviewer-C authority)

- **M1** — replace final admission with
  `ble_allowed = chain_unbroken or motion_leg or direct_ble` (restores
  the pre-fix Tier-1 bypass); T1 fixture goes RED.
- **M2** — hoist `_last_motion_time` seeding above the predicate; T6
  seeding-order test goes RED.
- **M3** — force `chain_unbroken = False`; sleep-hold pin goes RED
  (proves the chain leg is load-bearing).

**Acceptance Criteria:**
- **Verify:** all three mutation tests report RED under mutation and
  pass on the shipped source.
- **Test:** `test_MUTATION_m1_direct_ble_bypass_restored_makes_masterbath_fixture_red`,
  `test_MUTATION_m2_seeding_hoisted_above_predicate_makes_order_test_red`,
  `test_MUTATION_m3_chain_leg_removed_makes_sleep_hold_test_red`.

## Non-goals

- No change to `v3.5.1` camera block (guarded by D2).
- No change to `is_room_direct_ble` semantics.
- `direct_ble` is intentionally NOT consulted by the fixed predicate —
  the fix-up intentionally removes the tier-based fast path so BLE
  extend-never-create holds uniformly for direct AND shared scanners.
