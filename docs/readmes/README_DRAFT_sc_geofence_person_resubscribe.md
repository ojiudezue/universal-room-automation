# DRAFT — SC-GEOFENCE-PERSON-SNAPSHOT-1: SC geofence listener follows person add/remove

Tier 1. Branch `fix/sc-geofence-person-resubscribe`. Version to be assigned at deploy.

## Problem
`SecurityCoordinator._setup_geofence_listener` read `hass.states.async_all("person")`
once at setup and subscribed to that fixed list, returning early if it was empty. A
person entity created later, or loaded after SC, never reached
`_handle_person_state_change` (expected-arrival auto-add while armed).

## Fix
Mirrors the lock regime's pattern (`security_lock_regime.py` `async_setup` add/remove
domain subscriptions, `_on_person_added` / `_on_person_removed`):
- `_setup_geofence_listener` always subscribes `async_track_state_added_domain` and
  `async_track_state_removed_domain` for `person`, even with zero persons.
- On either event, `_resubscribe_geofence_persons` cancels the old per-entity listener
  and resubscribes to the current `person.*` set.
- All unsubs (add, remove, and a canceller for the current per-entity listener) live in
  `_unsub_listeners`, so `_cancel_listeners` on teardown is symmetric.
- No new knob. Behaviour for persons present at setup is unchanged.

## Tests
`quality/tests/test_sc_geofence_person_resubscribe.py` (5 tests) drive the real
SecurityCoordinator method. Mutation drills: removing the added-domain sub, the
removed-domain sub, the resubscribe call, or the teardown canceller each turns specific
tests RED.

## Live acceptance (after the next restart)
INFO logs are not visible (URA logs at WARNING), so verify on ground truth:
- **Live:** run in HA Developer Tools > Template (or `ha_eval_template`):
  `{{ states.person | map(attribute='entity_id') | list }}`, then confirm via HA's
  event-listener count that SC's `state_changed` listeners include every person. The more
  practical check is behavioural. While SC is armed, a person who goes `not_home` -> `home`
  adds an expected-arrival entry that shows on the SC sanction/expected-arrivals sensor
  attribute (`sensor.ura_security_coordinator_*` expected arrivals). Do this for a person
  created after the restart (or one whose entity loads late) as well as an existing one.
- **Discriminator:** without the fix, a person added after setup produces no
  expected-arrival entry when they arrive. With it, they do.
- Not provable live without creating a person: the "person added after setup" path is
  proven in-suite (tests 1–2). It is a restart-order race, so a normal restart may not
  exercise it.
