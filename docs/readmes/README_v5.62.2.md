# URA v5.62.2 — Hotfix: the NM mute service never worked

**Tier:** Hotfix (1 handler + AST regression test). Found in real time while trying to mute a
live alert loop — the worst possible moment to discover a broken kill switch.

## Defect

`_mute_service_handler` (`domain_coordinators/notification_manager.py:~999`) was registered as a
plain **sync** `def`. Home Assistant runs sync service handlers in an **executor thread**, where
`hass.async_create_task()` is not thread-safe. The coroutine was therefore created and dropped:

```
coroutine 'NotificationManager.async_mute_person_channel' was never awaited
```

and `universal_room_automation.nm_mute_person_channel` returned **HTTP 500**. So the operator's
documented per-person / per-channel mute escape hatch had **never functioned** since it shipped.

## Why it mattered

The only other available lever, `switch.ura_notification_manager_messaging_suppressed`
(`async_suppress_messaging`), is a **total** kill switch — no duration, no life-safety exemption
(`notification_manager.py:1202` returns early for every notification, including smoke/CO/water).
With the surgical lever broken, an operator wanting to silence one noisy channel had only the
option of silencing life-safety alerts too. That is an unacceptable choice to be forced into.

## Fix

`async def _mute_service_handler(call)` — runs on the event loop and simply `await`s
`async_mute_person_channel(...)`. No thread-boundary hop, nothing dropped.

Also checked: no sibling service handler in the integration has the same shape (grep for
sync `*_service_handler(call)` + `hass.async_create_task` returns only this one, now fixed).

## Test

`quality/tests/test_nm_mute_service.py` — an **AST** assertion (not a source grep) that parses the
module and requires the handler be an `AsyncFunctionDef`, plus a second test requiring it to
`await` and to NOT use `hass.async_create_task` (the original defect). Orchestrator-drilled:
reverting to `sync def` turns `test_mute_service_handler_is_async` RED.

## Acceptance criteria

- **Live:** `universal_room_automation.nm_mute_person_channel` with
  `{person_id, channel, duration_minutes}` returns success (not 500) and the mute takes effect —
  subsequent alerts skip that channel for that person while other channels still deliver.
- **Live:** `duration_minutes: 0` clears an existing mute (documented kill semantics).

## Live Validation

(prospective — replaced post-restart)
