# Review — EGRESS-EXIT-IDENTITY-BACKFILL-1 R1 (branch fix/exit-backfill-r1 @ 3b9b3c9a6)

Tier 1, single pass, framing A (local correctness + blast radius). Diff: `git diff develop...fix/exit-backfill-r1`. Merge-base verified as cff7544cd (develop's parent of HEAD).
Read: IDENTITY_FUSION_CAMERAS_MANUAL.md §4.3a (the changed section). The presence state-of-play doc was not read in full; this change touches no presence-fusion input.

## Findings

| # | Sev | Site | Finding | Bug class |
|---|---|---|---|---|
| 1 | LOW | sensor.py `_handle_exit_backfilled` (`hass.async_create_task`) | The re-read task isn't tied to the entity. If the entity is removed while the DB read is pending, the task can still call `async_write_ha_state` on it. This matches the existing `PersonsExitedToday` sibling and the try/except swallows the error. | Untracked background task |
| 2 | LOW | sensor.py `_async_reread_last_exit` | If the INSERT for the latest bus exit failed, `events[-1]` is an older row inside the 300 s slack, and its name is adopted. The camera check only rejects it when both cameras are set and differ. Needs an insert failure plus a named older exit within 5 min, so very unlikely. | Stale data source (#7) |
| 3 | INFO | test_egress_exit_backfill.py | 3 untouched DAO tests error at teardown with an aiosqlite thread leak (`_connection_worker_thread`), with and without the mutation. Environment issue, not this diff. | — |

## Cleared (holds because)
- **Switch source:** `_is_egress_identity_enabled` (camera_census.py:3800) fresh-reads merged data+options of the integration entry. Default comes from `DEFAULT_EGRESS_IDENTITY_ENABLED`. This is the same backing store the switch writes, and the same helper the face path uses.
- **Gate order:** the edge gate sits before the cooldown stamp, so an OFF edge doesn't suppress a later ON edge. The pre-UPDATE gate sits after the settle sleep and before `backfill_entry_exit_person_id`, so a row stays NULL if the switch is turned off mid-settle. Both increment the counter. The attribute is exposed via getattr with a default of 0.
- **Listener lifecycle:** both the bus listener and the dispatcher connect are wrapped in `async_on_remove`. The bus listener leaked before this change, so wrapping it fixes that.
- **Re-read:** DB access is async through `_db_read` (aiosqlite, so off the loop). The query uses ascending timestamp order and takes the newest row. The bound is converted to naive-UTC isoformat, which matches the `datetime.utcnow().isoformat()` INSERT format (database.py ~4290), so string comparison is safe. The timestamp (`_last_exit`) is never written. The re-read is skipped when the displayed exit is already named. It fires no event, notification or census call.
- **Signal:** `SIGNAL_EGRESS_EXIT_BACKFILLED` (signals.py:33) is sent only after a successful UPDATE (camera_census.py ~4698).
- **Docs:** the README v5.96.1 and v5.97.1 tables mark the row-level wrong-WHO check as NOT RUN, flag the co-departure claim as "inferred", and state that counters are lower bounds. Manual §4.3a matches the code.

## Mutation drill (C-lite)
I changed the pre-UPDATE gate `if not self._is_egress_identity_enabled():` to `if False:`. `test_exit_backfill_kill_switch_fresh_read_before_update` went RED: the row was named `oji_udezue` when it should have stayed None. After restoring, 27 passed. `git status` is clean apart from the pre-existing `.claude/tmp/`.

| Sev | Found |
|---|---|
| CRITICAL/HIGH/MEDIUM | 0 |
| LOW | 2 |

**Verdict: SHIP.** No must-fix items. The LOWs are optional.
