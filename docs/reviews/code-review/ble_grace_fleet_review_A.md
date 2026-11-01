# Review A: BLE absence grace + fleet fraction (correctness, edge cases, presence semantics)

Branch `fix/ble-grace-fleet-fraction` @ `b13a151ea`, base `338908dd7` (merge-base verified). Read first, completely: `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`, `docs/architecture/SENSOR_FLEET_CLASSES.md`. Targeted tests: 96 passed, 3 deselected.

## Verdict: SHIP (no CRITICAL / HIGH / MEDIUM)

## D1 grace: truth table (`coordinator.py:797-830`, branch `:4332`)
Inputs: chain = `_last_occupied_state` (previous tick), hold = `_ble_only_hold_since` set, cap = exceeded, open = `_ble_absent_since` set, used = `_ble_grace_used`.

| chain | hold | cap | open | used | result |
|---|---|---|---|---|---|
| F | any | any | any | any | False (cannot create) |
| T | F | any | any | any | False (body or camera hold, or first post-body tick) |
| T | T | T | any | any | False, no NM from this branch |
| T | T | F | T, age < 90 | any | True |
| T | T | F | T, age >= 90 | any | False |
| T | T | F | F | F | True, opens the grace, sets used |
| T | T | F | F | T | False (second absence in the episode) |

The branch is reached only when the BLE block runs (`not STATE_OCCUPIED and not _failsafe_fired`, `:4136`) and `get_persons_in_room` is empty (the `elif`). A present but refused read (shared scanner or cap) closes the grace at `:4147` and never enters the `elif`.

## Findings
- **Cannot create occupancy: holds.** The chain leg is checked first (`:816`), and `_ble_only_hold_since` is seeded only on a BLE admit, which needs the chain too (`:4231-4233`, `:4300`).
- **No chaining through bleed: holds.** A grace tick sets `_last_occupied_state` True, so a bleed read on the next tick extends the hold. That read would have extended it anyway if there had been no blip. A second absence in the same episode exits because `used` stays True. Room B cannot be created from room A's grace, since BLE never creates.
- **The 7 paired clears: holds.** Every `_ble_only_hold_since = None` site (`:4008, 4118, 4575, 4855, 5265, 5314, 5787`) also clears both new fields. Grep count 7 = 7.
- **Downstream during a grace tick**
  - Lights stay on. That is the intent.
  - The failsafe is deferred by source `"ble"` (`:4782-4784`), the same as an ordinary BLE hold.
  - HVAC evidence is stamped via `source in ("camera","ble")` (`:5982-6002`), so the hold extends by at most 90 s.
  - The cap NM fires only from the present branch. The grace refuses silently (`:820-822`).
  - The ble→body re-entry (`:5389`) behaves as it does for a BLE hold.
  - `data` is rebuilt every tick (`:3295`), so `ble_absence_grace` is absent on all other ticks.
- **LOW (accepted, documented): exit row `duration` can be up to 90 s high.** The exit row's `duration` = now − `_last_motion_time` (`:5952-5956`). On a real BLE-only exit it now reads up to 90 s higher, because the exit is written up to 90 s later. The meaning ("seconds since last motion") is unchanged. Bug class: none, by design (plan §1.3).
- **LOW (pre-existing, safe direction): stale fields if the finalize is skipped.** The finalize clear at `:4846` needs `_became_occupied_time` to be set. If a vacancy ever happened with it None, `_ble_absent_since` and `_ble_grace_used` would go stale along with the pre-existing `_ble_only_hold_since`. Stale values can only refuse a grace (old open grace means age >= 90; `used` True means refused), never grant one. No action.

## D2 floor (`person_coordinator.py:541-604`)
- **Arithmetic: holds.** With R = 62: ceil(31.0) = 31. With R = 4: max(3, 2) = 3. With FRACTION 0: 3. R includes today's slot, which only rises (max fold).
- **Cold memory: holds.** `warm` needs the total entity to resolve AND a slot dated before today (`:582-584`). Otherwise the legacy 30 applies, so a restart mid-outage with only today's shrunken slot stays at 30. First deploy is cold until the first local midnight.
- **Prune: holds.** Slots are kept only if dated within today − 6 … today. Future-dated, undated and malformed slots are dropped, and the ring is sorted. A malformed store payload (non-dict, bad entry) means an empty ring (`:525-535`).
- **Non-numeric totals never touch the ring: holds** (`:567-571`).
- **Listener/tick agreement: holds.** `_update_fleet_floor` runs at the top of `_ensure_proxy_listener` (`:647`) before the tick re-read. `_apply_proxy_state` compares against the cached `_effective_floor` (`:612`) for both callers. If the floor rises above the current active count, the tick clears the latch the same tick.
- **Writes: holds.** A save happens only when the ring changes (about daily, plus total growth), as a 60 s delayed save. No write flood.

## Bug classes checked
- #53 (one missed site): 7/7 clears. The floor has one reader, the cached value. Clean.
- #63 (coincidental equality): F = 31 vs legacy 30 is the same here (plan D2.0). The split is explicit. Clean.
- Day-boundary: uses the local date via `dt_util.as_local`, and ISO strings compare correctly. Clean.
- Observation mode: n/a.
