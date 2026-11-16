# URA v5.108.34: stuck-sensor pages survive NM boot-settle

Card STUCK-SENSOR-S3B-S1-1 (residual `residual_2026_11_16_boot_settle_drops_chatter`). Tier 1. Fix commit 45572684,
merged to develop by the merge after v5.108.33 (the earlier merge a5678e36 took master by mistake, so v5.108.33 shipped
without it). Install target: the house goes from v5.108.32 straight to v5.108.34, which also carries everything in
`README_v5.108.33.md` (arrival engine option B, WiiM MA twin fix).

Orchestrator check after the corrected merge: the 6 fix tests pass; mutating the location-key site
(`notification_manager.py:862` to `if False:`) turns 2 RED; restored, tree clean.

Found live in v5.108.30 validation: the first act-mode chatter page (Garage B ratgdo motion) never reached
`notification_log`. NM boot-settle collapses repeat (coordinator, hazard_type) emits for `NM_BOOT_SETTLE_S` (60 s), and
every stuck kind shares `STUCK_SIGNAL_NM_HAZARD_TYPE`, so the chatter page was swallowed by a dutycycle page sent 9 s
earlier. `fire_stuck_signal` still set its per-day latch, so chatter stayed silent until the next day.

- Hazards in the new `NM_BOOT_SETTLE_LOCATION_KEYED_HAZARDS` (const.py; today only the stuck-signal hazard) key
  boot-settle on (coordinator, hazard, location), so distinct stuck kinds each send. Other hazards are unchanged.
- `async_notify` returns `False` when it drops a message before delivery and `True` at the end. `fire_stuck_signal`
  sets its latch, ledger entry and anomaly row only when the send was not dropped, so a dropped page is retried at the
  next evaluation (a quiet-hours drop now delivers in the morning instead of being lost for the day).
- A boot-settle drop of a location-keyed hazard removes the dedup stamp it had just written, so the retry is not
  deduplicated away.

Review: Tier 1, SHIP, two LOWs (a repeated INFO boot log; a drop counter can count a retried page twice),
`docs/reviews/code-review/v_nm_boot_settle_stuck_kinds_review.md`. Tests `quality/tests/test_nm_boot_settle_stuck_kinds.py`
(6), 7/7 mutations RED.

Live check: after the restart, every distinct stuck kind active at boot has its own `notification_log` row; Garage B
chatter (if still chattering) pages today.

## Validated (to be written back after install)
