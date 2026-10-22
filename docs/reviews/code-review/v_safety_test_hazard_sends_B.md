# Review B — fix/safety-test-hazard-sends (e6889329f)

Framing: regression of the REAL hazard path. Diff base: `git diff develop...HEAD` (merge-base ab9245c3e; develop tip 7c131712b is docs/kanban only on top). Files: `domain_coordinators/safety.py`, new test file.

## Byte-identity of the real-hazard NotificationAction

Old inline (develop safety.py ~2579-2592) vs helper `_hazard_notification_action` (safety.py:2839-2858), called at safety.py:2582 with the default `title_prefix="Safety alert"`:

| Field | Old | New (default prefix) | Same |
|---|---|---|---|
| coordinator_id | self.COORDINATOR_ID | self.COORDINATOR_ID | yes |
| severity | hazard.severity | hazard.severity | yes |
| confidence | hazard.confidence | hazard.confidence | yes |
| description | f"Safety alert: {hazard.message}" | f"{'Safety alert'}: {hazard.message}" | yes |
| message | hazard.message | hazard.message | yes |
| channels | _get_notification_channels(hazard.severity) | same | yes |
| hazard_type | hazard.type.value | hazard.type.value | yes |
| location | hazard.location | hazard.location | yes |
| other kwargs | none | none | yes |

The helper is a pure function of `hazard` and has no branching on type, severity or location, so identity holds for every HazardType (smoke, CO, leak/flood, freeze, humidity, ...) × every Severity × every location form, including `:roc` keys (location is passed through verbatim in both). The dedup gate (`self._deduplicator.should_alert`) and the `_alerts_sent_24h += 1` stay in place before the append (safety.py:2580-2582). Real path: PASS.

## Test path isolation

- `_active_hazards`, `_alerts_sent_24h`, `SIGNAL_SAFETY_HAZARD`, response actions: `handle_test_hazard` (safety.py:3008-3065) touches none of them. PASS.
- Dedup: the test path now uses `_test_deduplicator` (safety.py:1048, 3046). Before this change it stamped the REAL `_deduplicator`, so a test could suppress a real page for the same type:location. That defect is now fixed. PASS (improvement).
- Unload/shutdown: the send happens only inside the service handler. When `coordinator_manager` is missing it logs and returns (safety.py:3061-3064), and `_execute_action` no-ops when `_notification_manager` is None and catches NM exceptions (manager.py:1070-1095). No timers or tasks are created on the Safety side. PASS.

## Findings

**MEDIUM (B1). A CRITICAL test page takes over NM's single-slot alert engine and can stop a live real alert from repeating.** Bug class: cross-coordinator shared-state interaction.
- `handle_test_hazard` accepts `severity="critical"` (safety.py:3024, `Severity[severity.upper()]`). The action now reaches NM `async_notify`, and `severity == CRITICAL` calls `_enter_alerting` (notification_manager.py:2008-2009).
- `_enter_alerting` (notification_manager.py:2502-2553) unconditionally cancels the existing cooldown/countdown and overwrites `_active_alert_data` and `_active_episode_id`.
- Repro: a real `smoke` CRITICAL in `kitchen` is REPEATING and unacked. The operator runs `test_safety_hazard(hazard_type=water_leak, location=garage, severity=critical)`. NM's repeat engine now re-pages "TEST safety alert: ..." and stops repeating the real smoke alert. Acking the test also acks that slot.
- Before this change, the test path sent nothing, so this could not happen. It is new reachable behavior. Real-hazard NotificationAction construction itself is unaffected.
- Suggested fixes (builder's choice): (a) refuse or downgrade CRITICAL in the test path when `NM._alert_state` is ALERTING or REPEATING for a non-test episode, or (b) downgrade test pages to HIGH so the repeat engine is never entered. Also note that a test CRITICAL for a life-safety type bypasses DND and boot-settle (notification_manager.py:1516). That is probably intended for a pipeline test, but the operator should confirm.

**LOW (B2). NM-side counters and caches do move on a test page**: `_last_notification`, `_notifications_today_count`, per-severity counts, and the boot-settle `(coord, hazard_type)` seen-set (notification_manager.py:659-670, 1988-2002). Consequence: within NM_BOOT_SETTLE_S after boot, a non-life-safety test page consumes the `(safety, hazard_type)` key, so a real page of the same type in that window is collapsed (notification_manager.py:1517-1525). The window is narrow and the hazard is non-life-safety only, but it is a test page suppressing a real one. Accept or document.

## Verdict

**FIX-REQUIRED** on B1. The real-path refactor is byte-identical and SHIP-quality. Must-fix: B1, a CRITICAL test page must not preempt an active real NM alert. B2: fix it or explicitly accept it.

B2 accepted: tests are operator-initiated and rare; use location 'test'.
