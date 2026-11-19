# Review B2 (shared action manager) — fix pass e8b71e74d (parent b91f4add7)

Verdict: **SHIP**. 335 passed (freshness, domain_coordinators, NM, safety refire/hazard, swallow-escalations, lighting manual-hold) from a clean export.

| # | Sev | Where | Finding |
|---|---|---|---|
| 1 | MEDIUM | security_lock_freshness.py:330-357, 370-378 | Common-mode page latches only `COMMON_KEY.paged_ts`; per-lock records get no `paged_kind="dead"`, so a cache restore after an all-locks-offline event never yields the "restored"/unverified page or `out.unverified`. Real hole, bounded: the common page already says state unknown, check doors. Card it (stamp per-lock `paged_kind="dead"` in the common callback). |
| 2 | LOW | manager.py:1058-1068 | `blocking=False` moves error reporting from URA's try/except to HA's own task logging; HA tracks the task (no URA leak). Acceptable. |

Cleared:
- Byte-identical: no other action producer sets `data["blocking"]` or `on_notify_result` (hvac_setpoint.py:267 `blocking` is a climate_write DB payload, not action data).
- Callback: wrapped in try/except (manager.py:1111-1114); NM exception leaves `_delivered=False` so the page is retried. `async_notify` returns bool (notification_manager.py:1611).
- Serialisation: `_log_decision` uses `str(action.data)[:500]` (manager.py:1159), so a callable is safe; no other manager path dumps action data.
- Conflict resolver: empty `target_device` goes to the non-device pass-through (manager.py:118-122); the refresh cannot displace `lock.lock`.
