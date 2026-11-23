# Overnight 2026-11-20 review: lock page last_seen + BLE m2 drill retarget

Tier 1, framing A (local correctness, edge cases, blast radius). Both branches are one commit on
origin/develop d0911ed39 (merge-base verified, three-dot diff).

## 1. fix/lock-page-last-seen (a0bc0d1d7), SECURITY-LOCK-PAGE-LAST-SEEN-1 - SHIP

Display-only constraint holds. `last_seen_ts` (security_lock_freshness.py ~262/280) is written only
into `per_lock[...]["last_seen_ts"]` and read only in `_page` (~490). The `cands`/`real_report_ts`
condition `grace_end < ts <= now` is unchanged, so `real`, `age_s`, `age_h`, `stale`, the dead
debounce (`_dead_since`) and repage records are not touched.

Branches checked:
- Offline (lock unavailable): last_seen is still read (the `signal == SIGNAL_LAST_SEEN` block is
  outside `if not lock_unavail`), so the offline page gets the age. Intended.
- Node dead: `last` is "last report N h" when real exists, otherwise last-seen text or "unknown".
- Stale with real None: the new wording replaces the old ungrammatical "has not reported for since
  restart". With real set, the text is the same as before.
- Restored: unchanged.
- Naive, unparseable, disabled or missing last_seen: `_aware` returns None, so the text stays
  "last report unknown". Parametrized test covers this.
- Non-Z-Wave signal: `last_seen_ts` stays None, so behaviour is the same as before.
- NM dedup keys on (coordinator, title, location, severity) (notification_manager.py:1828), not on
  message text. The page dedup lives in the Store record. The hour count changing in the message has
  no dedup effect. The stale page already carried an hour count before this change.

Mutation drills (worktree, PYTHONDONTWRITEBYTECODE, restored, git status clean):

| Mutation | Result |
|---|---|
| last_seen leaks into cands (`ts <= now`, no grace floor) | RED, 6 tests incl. `test_preboot_last_seen_does_not_feed_freshness`, `test_boot_stamp_not_real_report` |
| display branch disabled (`if False`) | RED, the 3 stale/dead/offline page tests |
| `ts <= now` future guard removed from the display capture | GREEN: untested (L1) |

Findings:
- **L1 LOW (Bug Class #62, untested site)** security_lock_freshness.py:280. No test covers a future
  last_seen. Neutering the guard leaves the suite green. Without the guard a future stamp would print
  "last seen -3 h ago". The code is correct today. Add one parametrized case ("future") to
  `test_offline_page_keeps_unknown_without_usable_last_seen`.
- **L2 LOW (display wording)** security_lock_freshness.py:~495. "(before restart)" is also printed
  when the last_seen stamp falls between boot and grace_end. That stamp is after the restart but is
  correctly excluded from real reports. The wording is slightly inaccurate in that window only. Could
  read "(before or during restart grace)". Cosmetic, optional.

Verdict: **SHIP** (L1 recommended as a 1-line test add, not blocking).

## 2. test/ble-extend-drill-retarget (d10640972), BLE-EXTEND-DRILL-RETARGET-1 - SHIP

The anchor `self._ble_absent_since = None\n# Check if this room has direct BLE coverage` matches
the develop coordinator.py at ~4727. The mutant inserts the `_last_motion_time = now` seeding after
the absence-grace reset and before `is_room_direct_ble(...)` and the chain-only admission. That is
still "seeding hoisted above the predicate". The reset is a no-op for the seeding semantics.

Evidence:
- On the branch: `URA_SOURCE_MUTATION=1 ... -k m2` PASS. Sandbox log
  `baseline_rc=0 mutated_rc=1 expect=KILLED` on
  `test_seeding_order_no_self_confirmation_across_two_ticks`.
- On origin/develop (old anchor): m2 FAILS (anchor no longer present). This confirms the retarget
  was needed.
- Full file under the mutation flag: 22 passed. The sandbox copies production source and never
  writes it.

Findings: none.

Verdict: **SHIP**.

## Statistics

| Severity | Found | Fixed | Deferred |
|---|---|---|---|
| CRITICAL/HIGH/MEDIUM | 0 | - | - |
| LOW | 2 | 0 | 2 (to builder's discretion) |

Bug classes: #62 untested site (1), display wording (1). No new QUALITY_CONTEXT class.


## Fix-up (orchestrator, 2026-11-20 02:08 CST)

Both LOWs fixed in 5a9f2687b on fix/lock-page-last-seen: L1 adds a `future` case to `test_offline_page_keeps_unknown_without_usable_last_seen` (removing the `ts <= now` guard turns it RED). L2 prints "(before restart)" only when the stamp is at or before `boot_ts`, with a new test `test_grace_window_last_seen_not_labelled_before_restart` (always-label mutation turns it RED). Lock freshness + retry-cap files: 78 passed.
