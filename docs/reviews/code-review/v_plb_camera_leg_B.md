# Review B — PHONE-LEFT-BEHIND-CAMERA-LEG-1 (async / lifecycle / signal chain / restart)

Branch `feature/phone-left-behind-camera` @ 5ff9c37e, diff base = merge-base with develop (688042b3, three-dot).
Read first: `docs/QUALITY_CONTEXT.md`, `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (diffed sections + §10 #38).

## Findings

| # | SEV | Site | Finding | Class |
|---|---|---|---|---|
| B1 | LOW | `binary_sensor.py:2131-2134`, `const.py:3259` | `hours_since_camera_sighting` has no age cap. The entity polls at the platform default (no `SCAN_INTERVAL` in binary_sensor.py), so once a person has any sighting the stepped age changes every 900 s for the life of the process: about 96 state writes/day/person. `_unrecorded_attributes` keeps it out of the attribute blob but the state row is still written. Entity is disabled by default, so cost is zero unless the operator enabled it. Acceptable; noted so nobody assumes "unrecorded" means "no rows". | recorder churn |
| B2 | LOW | `sensor.py:3559-3565` | NextRoom `camera_last_seen` is computed only on the sensor's update; a sighting that ages past 4 h stays shown until the next update. Display only, bounded by update cadence. | display staleness |
| B3 | INFO | `transit_validator.py:873-876` | D3 drops the `label` attribute read. If any camera did set `label="person"` the old code filed it under key `"person"`, where path validation (which reads only `"unidentified"`) never saw it, so this is a strict improvement for `validate_transition`. | — |

No CRITICAL / HIGH / MEDIUM.

## Cleared (holds because ...)

- **Setup ordering.** `tracked_person_entity_id` is pure (`person_coordinator.py:130-141`) and computed from config at construction (`binary_sensor.py:119-134`); no coordinator needed at setup. Presence / CM / sighting producer are resolved at property-read time via `hass.data[DOMAIN]["coordinator_manager"].coordinators["presence"]` (`binary_sensor.py:2231-2245`, `sensor.py:3576-3579`); missing at any step returns None. PLB wraps the whole lookup in try/except; NextRoom's caller wraps it (`sensor.py:3559-3565`).
- **Key agreement.** PLB: `tracked_persons` entry (display name or `person.*`) -> `tracked_person_entity_id`. NextRoom: `aggregation.py:388` passes `entry.split('.')[-1]`, then `tracked_person_entity_id` re-prefixes; both forms map to the same `person.<slug>` the person coordinator uses. Names with characters HA slugifies differently (hyphen, apostrophe) would mismatch, but that is the pre-existing shared rule, not new.
- **Restart / teardown.** Store is RAM (`person_sighting.py:670`); empty after boot -> all sighting attributes None, `camera_leg: display_only`. After presence teardown `_person_sightings = None` (`presence.py:9169`) and `get_last_person_sighting` returns None (`presence.py:5907-5911`). CM reload swaps the presence object; lookup is fresh each read, so no stale reference is held.
- **No new tasks, listeners, timers, or dispatches.** Diff adds none; nothing to unsub.
- **Fetch cost.** `get_last` is a dict get; NextRoom fetches only when a prediction exists. No I/O, no await.
- **Clock.** `PersonSighting.ts` is `time.time()` epoch (`person_sighting.py:107`); compared against `dt_util.utcnow().timestamp()` — same basis.
- **INV-1 verdict unchanged.** `is_on` step 4: validator missing -> None, else True. Old code returned `get_last_camera_sighting(display_name) is None`, always True because no writer ever stored a named key. Identical.
- **Deleted accessor / constant consumers.** `get_last_camera_sighting`, `TRANSIT_PHONE_LEFT_BEHIND_HOURS`, `PHONE_LEFT_BEHIND_HOURS`: zero readers left in `custom_components/`, `quality/tests/`, `scripts/`.
- **TransitValidationResult payload.** Shape unchanged (fields kept; `identity_status` now never "confirmed"/"mismatch", `camera_person_id` always None). Only consumer is `transitions.py:227-235`, which reads `path_confidence_delta` / `path_method` / `checkpoint_rooms`; DB `update_transition_validation` (`database.py:4569`) persists none of the identity fields. No grep hit for `identity_status` or `_validation.` readers outside transit_validator.py.
- **Removed `ts` local in `_correlate_sighting_to_transition`.** Rule 2 uses its own `t_ts`; no dangling reference (`transit_validator.py:799-816`).
- **Dashboard / template consumers of removed `phone_left_behind_hours`.** 0 hits for `phone_left_behind_hours`, `hours_since_camera_sighting`, `camera_last_seen` in `/Users/okosisi/ha-config/.storage/lovelace.ura_v6/v7/v8` (the files only reference the entity id) and none in `/Users/okosisi/ha-config/*.yaml`. PWA `ura-dashboard-pwa/src/components/tabs/Presence.tsx` references only the entity-id pattern in comments.
- **`transit_camera_validated`** now true when a <4 h person sighting exists (previously always False live). No reader outside the new tests.

## Tests
Focused run (new test file, D9, transit protect-sourced, unload symmetry, plus 8 files touching PLB/NextRoom/transit_validator): 227 passed. No full suite.

## Verdict: SHIP
No must-fix. B1/B2 are optional.
