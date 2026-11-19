# SECURITY-LOCK-STALE-STATE-1 — Review B (async / lifecycle / NM)

Commit b91f4add7 on feature/security-lock-freshness, base cb05f181a (merge-base verified). Cycle tests: 35 passed from a clean export.

**Verdict: FIX-REQUIRED** (one HIGH)

| Sev | Where | Finding |
|---|---|---|
| HIGH | security_lock_freshness.py sweep (`rec["paged_ts"] = _iso(now)` after page append); notification_manager.py ~1700-1740 | Dedup is stamped when the page is *proposed*, not when it is delivered. During quiet hours a HIGH non-life-safety page hits `return False`: it is dropped, not held. A lock that dies at 23:00 is paged into the void and marked paged. The next page comes after R=6 h, which may still fall in quiet hours. With R=0 the page never arrives. Plan §135 says the page is "held"; the code says it is dropped. Fix before deploy: either promote `lock_unverified` (the plan's recommended default), or stamp `paged_ts` only when NM reports delivery. |
| MEDIUM | sweep: the dead-page path has no `swept` check, alongside the existing MEDIUM offline notice | An unavailable lock gets two notifications per episode: MEDIUM offline (once a day) and HIGH dead (every 6 h). The plan accepts this, and excluded locks get dead pages by design (§103). Noted as operator noise, not a defect. |
| LOW | `_save` uses `async_delay_save(30 s)` | A CM reload within 30 s of a page builds a new Store that loads pre-write data, so one duplicate page is possible. HA stop flushes pending saves (final write), so a restart is safe. |
| LOW | manager.py:1055 runs `zwave_js.refresh_value` with `blocking=True` | A silent node can stall the action loop until the zwave-js server times out. The exception is caught per action, so the sweep never breaks. The empty `target_device` path goes to non_device_actions (manager.py:119), so the claim that it never displaces `lock.lock` holds. |
| LOW | stale and unlocked lock | A stale page, then `lock.lock`, then later the retry-cap notice: two distinct pages, no loop. Acceptable. |

**Checks that held:**
- The Store loads before the sweep timer starts (security.py:904).
- The listener is tracked on `_unsub_listeners`; teardown is at base.py:294.
- Boot grace returns before any page. A cache restore cannot pass as a report, because of the recovery stamp and the `grace_end` filter.
- A restart in the middle of the dead debounce restarts the debounce. `paged_ts` is persisted, so dedup survives the restart.
- Both Numbers are on both live-key lists (`__init__.py` 7470, 7824), so changing them reloads neither the CM nor the parent entry.
- The knobs are read live through `regime._cfg()`.
