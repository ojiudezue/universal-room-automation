# Review B — perimeter circling title split (053f48563)

Framing B: NM integration, dedup/cooldown/quiet hours, alert hygiene. Verdict: **SHIP**.

- Dedup key `coordinator:title:location` (notification_manager.py:1828,1851): the new title only separates exemption dispatches from baseline ones. A repeat "Escalated" on the same camera still dedups (test pinned).
- Spam bound: the exemption fires only on a strict class-rank increase per track (perimeter_alert.py:2612+). The per-camera `_last_alert` cooldown still stamps at :2047. At most one escalation per rank step.
- Quiet hours and DND (NM:1726) depend on severity and hazard, not title. Unchanged.
- Identity follow-up: keyed by cam_key, uses its own FOLLOWUP_TITLE (:6140-6260). Unaffected.
- Persisted dedup (NM:1144/1259): old-title keys age out. No migration needed.
- Legacy notify fallback (:4431) keeps the old title. It has no NM dedup, so this is harmless. LOW cosmetic.
- Tests: 202 passed (perimeter/ + test_notification_manager.py, clean export).
