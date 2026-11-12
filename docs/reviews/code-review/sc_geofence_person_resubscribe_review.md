# Review: SC-GEOFENCE-PERSON-SNAPSHOT-1 (branch fix/sc-geofence-person-resubscribe @ 01d5e4bd)

Tier 1, framing B (async / lifecycle / listener cleanup / races). Base verified: merge-base = develop 297333f7.

## Verdict: SHIP (no CRITICAL/HIGH/MEDIUM)

## Checks
1. **HA helper semantics** (installed `homeassistant/helpers/event.py`): `async_track_state_added_domain` = keyed tracker on
   `EVENT_STATE_CHANGED` filtered by `old_state is None` (:637-650, :653-684); removed = `new_state is None` (:687-720).
   Dispatch is `hass.async_run_hass_job` on the loop (:620-632); callback is `@callback` so runs synchronously in-loop.
   Fires once per person entity first-written to the state machine (incl. boot, if person loads after SC) — each fire
   rebuilds an O(n) listener; n is small. Holds.
2. **Teardown ordering**: `_setup_geofence_listener` appends the per-entity canceller BEFORE the add/remove unsubs
   (security.py:2208-2219). `_cancel_listeners` (base.py:287-300) is synchronous with no await, so no state_changed event can
   be dispatched between the canceller and the domain unsubs — no window to recreate a leaked listener. Additionally
   `_shutting_down = True` is set at security.py:922 before `_cancel_listeners()` at :935, and the domain callback gates on
   it (:2248). Holds.
3. **Canceller closure**: `_cancel_geofence_person_listener` reads `self._geofence_person_unsub` at call time and nulls it
   (:2221-2228); each resubscribe cancels-then-replaces (:2232), so after N rebuilds exactly one live handle exists and the
   teardown canceller hits it. Holds.
4. **Re-setup / double subscription**: only re-entry is CM `async_set_coordinator_enabled` (manager.py:1249-1285): disable
   runs `_cancel_listeners()` (clears list, nulls handle), enable re-runs `async_setup`; the `enabled == coordinator.enabled`
   early-return prevents double setup while enabled. The disable path does not set `_shutting_down`, so re-enable keeps the
   gate open. Holds. (LOW, pre-existing/not this diff: `_shutting_down` is never reset to False, so a hypothetical
   teardown→setup on the same instance would leave the domain callback inert; unload recreates the instance, so not reachable today.)
5. **Removed-person event on per-entity listener**: `_handle_person_state_change` returns on `new_state is None` (:2263). Holds.
6. **Tests**: `test_sc_geofence_person_resubscribe.py` drives the real `_setup_geofence_listener` / `_cancel_listeners` with
   patched HA trackers (add, zero-at-setup, remove, unload, unchanged behaviour). Targeted run:
   `test_sc_geofence_person_resubscribe.py test_sc_away_lock.py test_unload_symmetry_task_hygiene.py` → **104 passed**.
   The builder's claim of 2 pre-existing `test_room_name_desync_retry_*` failures did NOT reproduce in this run (all green), so
   no develop-vs-branch comparison was needed; treat as order-dependent, not caused by this diff.

## Findings
| Sev | Item | Bug class | Status |
|---|---|---|---|
| LOW | `_shutting_down` never reset on re-setup (security.py:922) — pre-existing, unreachable via current paths | Restart/lifecycle | Deferred (not in diff) |

No new bug classes for QUALITY_CONTEXT.md.
