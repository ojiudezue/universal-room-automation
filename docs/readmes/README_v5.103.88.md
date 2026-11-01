# v5.103.88: a life-safety alert keeps the notification slot

Card: NM-MULTI-ALERT-TRACKING-1 (operator-approved 10-15, re-confirmed 10-24). Tier 2, elevated to 3 framing-disjoint reviews (safety path) + a focused 4th re-review of the fix-ups. Deploy risk: MEDIUM-LOW (NM only; the non-life-safety path is unchanged).

## Problem
The notification manager keeps one active alert slot. A later CRITICAL replaced the earlier one even if the earlier was an unacknowledged smoke/CO/leak alert: its 30 s repeat became the newcomer's 300 s, and ack went to the newcomer. Perimeter CRITICALs arrive ~23/day; in 30 days 92 overlaps landed within 30 min of each other (none with life-safety yet).

## Changes (`notification_manager.py`, `database.py`)
1. **Guard** at the top of `_enter_alerting` (`_life_safety_slot_holds_against`): an unacked life-safety alert (`is_life_safety_hazard`, `_nm_cycle_a.py:200`) keeps the slot against a non-life-safety newcomer. The newcomer is still delivered once, and its rows are marked acknowledged so it never repeats. Life-safety newcomers still preempt.
2. **Targeted ack:** ack acknowledges ALL rows (every channel) of the slot alert, matched by coordinator + hazard + location, not "the newest unacked CRITICAL". `acknowledge_notification` takes optional coordinator/hazard and returns the acked row id.
3. **Cooldown** is stamped on the row actually acked.
4. **Restart recovery** prefers the newest unacked life-safety row that is within `NM_RECOVERY_MAX_AGE_H` (24 h); otherwise the newest row, as before.
5. Inbound BlueBubbles/WhatsApp replies link to the slot alert's row.

Behaviour change: every ack with an active slot now targets that alert's rows. Previously it acked whatever CRITICAL was newest.

## Tests
`test_nm_life_safety_slot_precedence.py`, 17 tests, including real-DB restart recovery (fresh smoke beats newer perimeter; 30 h stale smoke does not displace fresh perimeter), all-channel ack, and cooldown row. Every load-bearing site mutation-drilled RED (builder 15+ sites, Review C, orchestrator re-drilled guard and stale filter). `test_nm_cycle_c2_fixup` source count 10→13 (new call sites; each has its own behavioural test). Full suite 18,166 passed, 0 failed.

## Not done
Full multi-alert tracking: a held-back alert is not re-paged after the life-safety alert is acked (card's SIMPLIFY verdict).

## Live acceptance criteria (prospective)
- **Live:** no NM ERROR in the log after restart; `sensor` NM state recovers as before.
- **Live:** the next perimeter CRITICAL while NM is idle behaves exactly as before (takes the slot, repeats at its cadence).
- **Live, organic:** the first ack after deploy marks every channel row of that alert acknowledged (`notification_log` rows with the same coordinator/hazard/location all `acknowledged=1`).
- **In-suite only:** smoke + perimeter overlap (no life-safety CRITICAL has fired in 30 days; not to be staged on the live house).

## Validated 2026-11-01 (retrospective)

Evaluated once on 2026-11-01 (v5.103.93 loaded; URA DB read-only; times UTC). The deploy installed 2026-10-24 ~12:44 UTC; the exact restart that loaded it was not pinned, so "since deploy" uses 2026-10-24T13:00.

| Criterion | Result | Evidence |
|---|---|---|
| No NM ERROR in log after restart; NM state recovers | NOT EXERCISED | No HA core log available to the probe. Indirect: NM kept writing `notification_log` rows through 11-01 (latest 2026-11-01T14:19:08, 590 CRITICAL rows since 10-24 12:00). |
| Perimeter CRITICAL while idle behaves as before | PASS (indirect) | `perimeter_alert` `exterior_person` 1007 rows since 10-24, delivered on pushover/companion/whatsapp/imessage. No cadence check made. |
| First ack marks every channel row of that alert acknowledged | PASS | 442 acknowledged rows since 10-24T13:00; 0 (hazard, location, minute) groups containing a mix of acked and unacked rows. Example ack 2026-10-24T20:08:30 covering 4 channel rows of `exterior_person` back_yard and 4 of `envoy_write_verification`. |
| In-suite only: smoke + perimeter overlap | NOT EXERCISED (by design) | Observed instead: a real Kitchen smoke CRITICAL 2026-10-24T21:42:15 (ids 23810-23814), all four channel rows acked 21:47:50. Row 23814 (aggregate channel `companion,imessage,pushover,whatsapp`) stayed `acknowledged=0`; row 23815 (imessage repeat) acked=1 with no `ack_time`. Minor, possibly worth a look. |
