# Review B — NM-NO-CHANNEL-FIRED-1 (fix/nm-no-route @ df8e323a)

Framing B: async / lifecycle / race / restart / volume. Diff base `develop...HEAD`.
`quality/tests/test_nm_no_channel_fired.py`: 18 passed.

| # | SEV | Site | Finding | Bug class |
|---|-----|------|---------|-----------|
| B1 | LOW | notification_manager.py:5624-5658 | `_since` window end is stamped `utcnow()` AFTER `_deliver_digest` awaits, but the count ran BEFORE it. A no-route row logged during the delivery await lands in neither flush's count. Capture `flush_now = utcnow()` before `count_no_route_since` and stamp that. Silent miss of a display line; the trip-wire is unaffected. | Capture-before-await |
| B2 | LOW | notification_manager.py:5624 | After a restart `_last_digest_flush` is empty, so the next flush looks back 24 h and can re-report no-routes already counted in a pre-restart flush. Over-reporting, display only. Acceptable; document it, or persist the stamp. | Restart state |
| B3 | LOW (pre-existing, more exposure) | notification_manager.py:5666 + database.py:4958 | `mark_digest_delivered` marks every `delivered=0` LOW/MEDIUM row, including rows inserted while `_deliver_digest` was awaiting, so those rows never appear in a digest. This predates the change. The new fallback rows (about 43 a day) widen the window a little. A fix would mark by `id <= max(pending.id)`. Card it, not must-fix. | Snapshot/mark race |

## Cleared
- **Trip-wire recursion:** `_no_route_tripwire_last` is stamped (:2328) before the anomaly-write await and before the nested `async_notify`. The nested call re-enters `_maybe_fire_no_route_tripwire` and returns on cooldown. If the HIGH alert itself routes nowhere, it appends more no-route times, but the cooldown is the full window, so it fires at most once per 24 h. Holds.
- **Trip-wire concurrency:** the check-and-stamp runs with no await between the count and the stamp (:2319-2328), and the event loop is single-threaded, so two concurrent notifies cannot both fire. Holds.
- **Deque growth:** it is pruned on every `async_notify`, so it is bounded by the window. `dry_run` rows are excluded (:5479). Holds.
- **Restart:** the trip-wire and counters are in memory and re-arm empty, which matches the send counters and is the documented intent (:282-284). No RestoreEntity or timers are added, so there is nothing new to unsubscribe.
- **Duplicate delivery:** the fallback writes only when `not _digest_queued` and in `legacy_fallback` (:2174-2189), so there is one row per recipient per notify. Audit rows use `message='[audit]'` and are excluded by `get_pending_digest` (database.py:4928). The fallback channel `"digest"` is not filtered by any digest reader. A mute on any channel suppresses the fallback, which errs toward silence and respects operator intent.
- **Timestamp format:** the writer (database.py:4821) and `_since` both use `dt_util.utcnow().isoformat()`, so the lexical compare is sound.
- **DB load:** about 43 fallback rows a day plus one COUNT per flush per person. The COUNT uses the `(person_id, …)` index prefix, so the load is negligible. Writes follow the existing `log_notification` path; no per-row write pattern is added.
- **Message size:** `_format_digest` groups by title and location with an "Nx" prefix, so about 20 items collapse to a few lines and stay well under the WhatsApp (~4096) and iMessage limits. The no-route line is one short sentence. The heartbeat now reads "N alerts had no route" instead of "All quiet". Weekly Routine Digest: out of scope; no change to its path in this diff.

## Verdict: SHIP
No CRITICAL/HIGH/MEDIUM. B1 is recommended as a 2-line in-cycle LOW fix. B3 should be carded.
