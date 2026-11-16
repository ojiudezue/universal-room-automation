# URA vTBD: unacked page repeats stop after the first hour when home

Card: NM-PERIMETER-REPEAT-STORM-1 (Tier 2). Operator 2026-11-16: "Paging - first hour if home. More if away".

## What changed

- An unacknowledged non-life-safety CRITICAL page (for example a perimeter "person detected" page) still repeats every 5 minutes for the first hour.
- Past one hour, each repeat tick reads the house state first. If the house is home (any known state other than away or vacation), repeats stop and NM ends in the same state an ack reaches: the slot's rows are marked acknowledged in `notification_log`, and `_start_cooldown` runs (COOLDOWN with the hazard's cooldown minutes, `cooldown_expires` stamped on the row). A cap differs from a human ack in three ways: it writes a pre-acked outcome row (`route_reason = bucket_outcome = repeat_capped_home`), each recipient gets one digest line ("Repeats stopped: <title>"), and there is no ack-registry entry, ack TTS or bulk backlog sweep.
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

- A cap behaves like an ack, so it inherits the ack's existing cooldown rule: COOLDOWN does not block a new CRITICAL. `_enter_alerting` cancels the cooldown ("Cancel any existing cooldown/countdown from a previous alert") and starts a new page with a fresh hour. Only the 60 s CRITICAL dedup (`NM_DEDUP_CRITICAL`) applies. When the cooldown expires, `_re_evaluate_hazard` re-fires if the source coordinator reports the hazard still active. Today both apply equally after a human ack.
- The repeat number restarts at 1 after a restart.

## Acceptance

- Test: `quality/tests/test_nm_repeat_home_cap.py` (16 tests: home cap into COOLDOWN, restart after cap, new CRITICAL in cooldown, 3599 s versus 3600 s boundary, away/vacation at 1800 s, unknown state, life-safety intruder and smoke, knob 0, numbered resend rows, ack, restart home and away).
- Live: after the next unacked perimeter page with the house home, `notification_log` shows 11 `route_reason='repeat'` rows and one `repeat_capped_home` row, and no resends after one hour.

## Live validation

Pending deploy.
