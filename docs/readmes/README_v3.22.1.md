# v3.22.1 — LOW Severity Cleanup

**Date:** 2026-04-01
**Tests:** 48 new
**Review tier:** Hotfix (1 review)

## What Changed

12 deferred LOW/MEDIUM findings from the v3.20–v3.22 hardening reviews,
plus 2 review findings from this cycle's own review.

### Fixes
1. UTC→local timezone consistency in room_state DB table
2. Override switch slug DRY refactor (`_room_switch_entity_id` helper)
3. Cooldown sensor renamed to "Recent Alerts" with `max_remaining_seconds`
4. Envoy sensor signal listener (new SIGNAL_ENERGY_ENTITIES_UPDATE)
5. Music Following task tracking (`_pending_tasks` + teardown cleanup)
6. CO hazard now unlocks egress doors (added "carbon_monoxide" to tuple)
7. Unused imports removed from `_stop_all_fans_safety`
8. Observation mode dry-run logs in all signal handlers
9. Disabled coordinator guard (`_enabled` check) in all signal handlers
10. CM entry cache in `_get_signal_config` (avoids O(n) scan per call)
11. Observation mode switch deferred restore retry with `async_on_remove`
12. Warning log when deferred retry fails (coordinator still unavailable)
