# Review: NM boot-settle stuck kinds (STUCK-SENSOR-S3B-S1-1) — commit 45572684

Tier 1, one pass, framings A (local correctness) + B (async/lifecycle). Diff `7bf1945d..45572684` verified (4 files).

## Verdict: SHIP (no CRITICAL/HIGH)

## Checks
1. **async_notify return paths** (notification_manager.py): pre-delivery drops all `return False` — disabled 1644, kill switch 1649, quiet hours 1742, silence 1751, perimeter window 1799, dedup 1805, boot-settle 1827. No bare `return` remains between 1600 and the final `return True` at 2401. Drops downstream of boot-settle (severity floors, routing, digest queue, dry-run) return True, so they latch exactly as before. No path that wrote a notification_log row or queued a digest returns False.
2. **Retry bound:** a not-latched stuck page is re-offered each tick. During quiet hours, silence, kill switch or NM disabled, each re-offer costs one cheap call, a debug log and a counter bump. There is no DB write, anomaly row, INFO log or task: the latch, ledger and `_write_stuck_anomaly` all sit after the `delivered is False` return (_stuck_signal_nm.py:250). The recovered pairing holds because `_STUCK_SIGNAL_NOTIFIED` is only added on delivery, so no "recovered" can follow a page that never went out.
3. **Callers:** only `_stuck_signal_nm.py:236` consumes the result (grep of `= await ...async_notify`). Mocks returning None keep the old latch behavior because the check is `is False`.
4. **Dedup un-stamp key** `f"{coordinator_id}:{title}:{location or ''}"` (1823) matches `_is_deduplicated` (5248) byte for byte. The pop only removes the stamp made in this same call, since the previous stamp was already outside the window.
5. **Tests:** test_nm_boot_settle_stuck_kinds.py drives the real `NotificationManager.async_notify` and `fire_stuck_signal`. The targeted run (that file plus test_nm*.py and *stuck*.py) passed 607 tests.

## Findings
| Sev | Where | Finding | Class |
|---|---|---|---|
| LOW | notification_manager.py:1815 | Boot-settle drop logs at INFO. A dropped stuck kind is retried every tick, so this repeats at tick cadence for at most 60 s. Bounded, cosmetic. | log noise |
| LOW | notification_manager.py:1741/1806 | `_quiet_suppressions` / `_dedup_suppressions` now count once per tick for an unlatched stuck page (previously once per day). Display counters only. | #63-adjacent (counter semantics) |
| INFO | _stuck_signal_nm.py | Same-kind/different-key pages without `title_override` share a dedup key. Previously the second one was latched and lost; now it is delivered after the 900 s window. This is an improvement. | — |
| INFO | exception mid-delivery | Raises, then fire_stuck_signal swallows without latching. Same as before (the latch was always after the await); the retry is gated by the dedup stamp. | — |

## Stats
CRIT 0 / HIGH 0 / MED 0 / LOW 2 (not fixed; optional).
