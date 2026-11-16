# URA vTBD: unacked page repeats stop after the first hour when home

Card: NM-PERIMETER-REPEAT-STORM-1 (Tier 2). Operator 2026-11-16: "Paging - first hour if home. More if away".

## What changed

- An unacknowledged non-life-safety CRITICAL page (for example a perimeter "person detected" page) still repeats every 5 minutes for the first hour.
- Past one hour, each repeat tick reads the house state first. If the house is home (any known state other than away or vacation), repeats stop: the timer is cancelled, the alert slot goes idle, its panel lease is released, one `notification_log` outcome row is written (`route_reason = bucket_outcome = repeat_capped_home`, pre-acked), and each recipient gets one digest line ("Repeats stopped: <title>").
- Away or vacation: the existing ladder continues (30 min until 24 h, then daily).
- Unknown house state (no coordinator manager, empty, or not a `HouseState` value): repeats continue. This fails toward paging.
- Life-safety hazards (base set plus operator extras, including smoke/CO/flood on the "standard" ladder) are never capped.
- Every resend now writes one `notification_log` row (`route_reason="repeat"`, `matrix_branch="repeat_<n>"`, channels fired, pre-acked, `message="[audit]"`). Resends can now be counted. Volume is one row per resend, not one per channel: at most 11 in the first hour, then 2 per hour.
- Ack ends the repeat exactly as before. A page restored after a restart follows the same rule at its first repeat tick, before anything is sent.

## Knobs (rung 1, `const.py`)

| Knob | Default | Notes |
|---|---|---|
| `NM_REPEAT_HOME_CAP_S` | 3600 | Age after which a home house stops repeats. 0 disables the cap (legacy ladder). |
| `NM_REPEAT_CAP_AWAY_STATES` | `{"away", "vacation"}` | States that keep repeating. A separate constant from `MEMORY_WRITER_HEALTH_ABSENT_HOUSE_STATES`; the two are equal today by coincidence. |

House state is read with the existing `NotificationManager._panel_house_state()` (the same coercion `_is_quiet_hours` uses).

## Known limits

- The page's own DB row stays unacknowledged, because nobody acked it. After a restart it is recovered, and it is capped again at its first tick (30 min later) with no send. That writes one more outcome row and one more digest line per restart.
- The repeat number restarts at 1 after a restart.

## Acceptance

- Test: `quality/tests/test_nm_repeat_home_cap.py` (14 tests: home cap, 3599 s versus 3600 s boundary, away/vacation at 1800 s, unknown state, life-safety intruder and smoke, knob 0, numbered resend rows, ack, restart home and away).
- Live: after the next unacked perimeter page with the house home, `notification_log` shows 11 `route_reason='repeat'` rows and one `repeat_capped_home` row, and no resends after one hour.

## Live validation

Pending deploy.
