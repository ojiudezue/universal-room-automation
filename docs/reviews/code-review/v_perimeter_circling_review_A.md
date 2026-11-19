# Review A (correctness) — 053f48563 PERIMETER-CIRCLING-HOP-SEVERITY-COLLIDE-1

Verdict: **SHIP**. Tests: perimeter/ + test_notification_manager.py + test_perimeter_fp_gates.py, 389 passed (clean export).

- Holds: the NM dedup key is `f"{coordinator_id}:{title}:{location}"` (notification_manager.py:5279). Severity only picks the window. The old D7 premise (severity in the key) was wrong.
- Holds: the title swap is gated on `exemption_active` alone (perimeter_alert.py:1820). The flag comes from `exempted_class is not None` (:1553). Message, severity and location are unchanged.
- Holds: no reader keys on the old title. The legacy direct-notify path (:4431) is unchanged and bypasses NM dedup. Follow-ups use `FOLLOWUP_TITLE` (:6260). There are no title-keyed routing rules or dashboards, and the docs only mention it in prose.
- Holds: the D7 test asserts the titles, equal location, distinct keys and both HIGH. The NM test pins the real key.
- LOW: the body still reads "Person Detected" on escalated sends (const.py:2538). This is cosmetic and optional.
