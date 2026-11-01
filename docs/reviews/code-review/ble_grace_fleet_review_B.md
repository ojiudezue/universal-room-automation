# Review B: async / lifecycle / restart / cross-coordinator, `fix/ble-grace-fleet-fraction`

- Commit b13a151ea. Base 338908dd7, verified as the merge-base (three-dot diff).
- Reviewer B, 2026-11-01.
- Read first, completely: `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` and `docs/architecture/SENSOR_FLEET_CLASSES.md`. No corrections-ledger claim is re-asserted here. The doc's §3 and §4.6 text matches the code.
- Targeted tests: the 6 cycle files gave 215 passed, 3 deselected.

## Findings

| SEV | Where | Finding / evidence |
|---|---|---|
| LOW | `person_coordinator.py` `_save_fleet_memory` + `async_teardown` | **Delayed save is not flushed on entry unload/reload.** `async_delay_save(..., 60)` stays pending on the old Store. The reloaded coordinator builds a new Store with the same key and reads disk, so it misses ≤ 60 s of changes. The old instance writes later; its ring is a subset of what the new instance refolds. HA shutdown is flushed by Store's final-write hook. The worst case is losing today's high-water from an earlier read when a reload lands within 60 s of the change during an outage. That only lowers R for today, and a prior-day slot dominates `max`, so it is benign. Optional fix: `await store.async_save(...)` in `async_teardown` when the ring changed. Class: restart-resilience. |
| LOW | `coordinator.py:4346` | `data["ble_absence_grace"]` has no reader (grep), so it is not visible anywhere: not an attribute, not in the DB. It is diagnostic only, and `data` is rebuilt every tick (`coordinator.py:3295`), so it cannot stick. Note only. |

## Cleared

- **Setup ordering (`__init__.py:2216`, call ~3099).** Order is construct → `async_load_fleet_memory` → first refresh. The load catches every exception (corrupt payload, bad tuple, `int('x')`, missing store) and falls back to an empty ring, which is cold memory and the legacy 30. It cannot raise into setup, so setup's failure semantics are unchanged. `ConfigEntryNotReady` from the first refresh behaves as before.
- **Store usage.** It is version 1 and has no migration (new key, nothing to migrate). Saves happen only when a slot changes: a new day, a higher daily max, or a prune. That is a handful per day, written through the 60 s delay, which fits the batch-not-per-row rule. A non-numeric, NaN or inf total is caught and never touches the ring.
- **Bermuda resolution.** Both entities resolve through `reg.async_get_entity_id("sensor", "bermuda", unique_id)`, so a rename is safe. If Bermuda is not loaded, `eid` is None, the floor stays cold at the legacy 30, and the active-proxy miss turns the rule off (pre-existing). A warm ring loaded from the store does NOT apply until the total resolves (`warm` requires `eid is not None`), so a mid-outage restart cannot arm on a shrunken total.
- **Edge listener vs tick.** Both read `_effective_floor` (`_apply_proxy_state`). The floor changes only inside the tick (`_update_fleet_floor`, the first statement of `_ensure_proxy_listener`), and the tick re-applies the current state right after, so the latch is re-judged against the new floor on the same tick. A floor rise at the day rollover can drop the latch, which is the conservative direction.
- **Unload / leak.** The listener is released by `entry.async_on_unload` and by `async_teardown` before the pop (`__init__.py:5697-5703`); release is idempotent. The Store holds a lambda referencing the old coordinator only until its single pending write fires. No new tasks or timers.
- **D1 restart mid-grace.** The fields are not persisted. After a restart, `_ble_only_hold_since` is None and the first tick has `_last_occupied_state` False, so the grace cannot apply. The room takes the pre-existing exit path, which is the conservative direction. A person-coordinator reload mid-grace means `person_coordinator` is falsy and the BLE block is skipped (pre-existing).
- **D1 ripple (presence ↔ HVAC ↔ safety).** The grace only prolongs an existing BLE-only hold by ≤ 90 s, once per episode. It keeps source `"ble"`, so P24 failsafe exemption (ii) still applies, HVAC evidence treats the tick as the hold it continues, and ble→body re-entry is unchanged. Census and house-state use person_coordinator locations, not room occupancy, so they are untouched. Zone/HVAC vacancy and the security occupied view are delayed by ≤ 90 s in the worst case, well inside the HVAC night/day tails. The grace never creates occupancy, because it needs `_last_occupied_state` and `_ble_only_hold_since`. The hold cap is respected, and no NM is fired from the grace branch. All 7 episode-end sites clear both new fields (diff verified).

## Verdict: **SHIP**

There is nothing to fix before ship. The LOW flush-on-teardown change is optional.
