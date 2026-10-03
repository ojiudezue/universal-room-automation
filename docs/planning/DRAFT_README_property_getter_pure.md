# DRAFT README — PROPERTY-GETTER-SIDE-EFFECT-TASKS-1 (property getters made pure)

Version: TBD (PATCH). Tier 2. Branch `fix/property-getter-pure-2`. Build to review only, no deploy.

## What changed
Three entity property getters started background work every time anything read them (recorder,
UI, templates, possibly from a thread other than the event loop). Each getter now only returns a
value. The work moved to an update path that HA runs on the event loop.

| Site | Before (in getter) | Now (discharge) |
|---|---|---|
| `aggregation.py` `SafetyAlertBinarySensor.is_on` | `async_create_task(_process_alerts)` on every read while alerts exist | `async_update` (HA poll, once per scan interval). Task tracked in `_alert_task`, re-entry guarded, cancelled in `async_will_remove_from_hass`. `_process_alerts` keeps its coordinator-manager guard and 60s debounce (operator call B, 09-26: fallback kept, trigger moved). |
| `sensor.py` `UnavailableEntitiesSensor.native_value` | `sensor_dropout` memory episode logged on an empty-to-non-empty transition, detected inside the getter | `_handle_coordinator_update` (@callback) calls `_check_dropout_episode()`, then the normal state write. Same transition logic and payload. |
| `sensor.py` `SafetyEventsSummarySensor.native_value` | 24h cache refresh task spawned when stale | `async_update` (HA poll). Same TTL, re-entry guard and cancel-on-remove. |

Displayed values are unchanged: `is_on` = any alert, `native_value` = unavailable count / cached
24h count. Attributes untouched.

## Behaviour notes
- Legacy alert processing now runs at most once per poll (30s default) instead of once per read.
  On this house it remains a no-op (coordinator manager present). On an install without the
  coordinator manager, the first alert action can come up to one poll later than before.
- The dropout episode fires on a coordinator refresh, not on a read. A transition that happens and
  clears between refreshes is not logged. Before, it was only logged if something read the entity
  inside that window, so this case was never reliable.

## Not done (deliberate)
- The hardcoded 85/55/70/25 bands in `_get_alerts` (card's adjacent finding). Under option B they
  are live again only on a no-coordinator-manager install. Not in this card's scope. Needs a
  follow-up card if knobs are wanted.
- The other ~134 `@callback`/timer task sites (card constraint: out of scope).

## Acceptance
- **Test:** `quality/tests/test_property_getter_pure.py` (9 tests, real entity classes).
- **Drills:** four call-neuter drills, each fails exactly one named test (see the review record).
- **Live:** `binary_sensor.universal_room_automation_safety_alert` and
  `sensor.ura_safety_events_summary` show the same state/attributes as before restart.
  No "calls hass.async_create_task from a thread other than the event loop" lines naming
  aggregation.py/sensor.py in the core log.
