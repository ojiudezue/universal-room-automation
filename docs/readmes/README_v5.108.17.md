# v5.108.17 — Alerts that reached no one now reach the digest

Card: NM-NO-CHANNEL-FIRED-1. Evidence: `docs/planning/AUDIT_nm_no_channel_fired_2026_11_13.md`. Reviews:
`docs/reviews/code-review/v_nm_no_route_{A,B}.md` (both SHIP; A1 MEDIUM and LOWs fixed in fix-up). Tier 2.

## What was wrong

The only recipient prefers digests, but the channel severity gates send only HIGH to the companion app and only CRITICAL
to WhatsApp, iMessage and Pushover. MEDIUM and LOW alerts routed to an empty channel set, and the digest-queue write was
gated on that same set, so nothing was queued. About 520 alerts in 12 days reached no one (stuck_signal, circuit_anomaly,
presence, 15 moderate high_co2), the Weekly Routine Digest was dropped every week, the daily heartbeat said "All quiet",
and `delivery_rate` read 100.

## What changed

- **Digest fallback.** When a recipient prefers digests and no digest row was written for an alert routed by the plain
  severity gates, NM writes one digest row (channel `digest`). Skipped under an explicit routing matrix that silences the
  severity, or when every digest channel is muted. Audit outcome `digest_queued` instead of `no_channel_fired`.
- **Honest heartbeat.** The digest says "N alerts had no route (reached no channel and no digest)" instead of "All quiet",
  and appends the line to normal digests when N > 0. The window starts at the last flush (taken before the count).
- **Delivery rate** counts routing holes (not drops chosen by a recipient's own gates or mutes).
- **Trip-wire.** `NM_NO_ROUTE_TRIPWIRE_COUNT = 20` routing holes at MEDIUM or above in `NM_NO_ROUTE_TRIPWIRE_WINDOW_S =
  86400` saves an `nm.no_route_tripwire` anomaly and sends one HIGH alert per window. 0 disables.
- Severity comparisons use the numeric value, not class identity (an order-dependent test found the fragile check).
- Test schema extractor no longer bleeds columns between tables.

## Effect on the house

Digests at 08:00 and 18:00 get longer: about 20 items each at first, grouped by title and location. The Weekly Routine
Digest returns. Channel severity settings are unchanged.

## Tests

`test_nm_no_channel_fired.py` (27). Full suite 21006 passed, 0 failed (baseline 20979, 0 failed). 19 + 9 mutation drills,
each RED then restored.

## Validated 2026-11-13

Restart 06:51 CST (`update.universal_room_automation_update` last_changed 12:51:27Z, installed `v5.108.17`). Window to
08:42 CST.

| Criterion | Result | Evidence |
|---|---|---|
| Sub-HIGH alerts queue to digest | PASS | 10 `notification_log` rows `digest_queued` (LOW 4, MEDIUM 6), route reason `legacy_fallback` |
| No `no_channel_fired` | PASS | 0 rows since restart |
| Digest rows delivered at flush | PASS | 4 of the 10 `digest` rows at delivered=2; HIGH companion row delivered=1 |
| No trip-wire anomaly | PASS | 34 `anomaly_log` rows since restart, none `nm.no_route_tripwire` |
| `delivery_rate` present | PASS | `sensor.ura_notification_manager_notification_delivery_rate` 100.0 (15/15) |
| `no_route_count` present | PASS | `sensor.ura_notification_manager_notification_diagnostics` healthy, `no_route_count: 0` |
| No URA setup errors | PARTIAL | `/api/error_log` has no URA ERROR or Traceback; the full boot log could not be read over ssh |

The heartbeat no-route line was not observed because no holes remain. The test suite proves it.

## Not done

- NM-DIGEST-MARK-RACE-1 (rows queued mid-send marked delivered) carded.
- Trimming the noisy stuck_signal / circuit_anomaly sources: next card after the digest volume is visible.
- Music-following test's unscoped `sys.modules` patch left in place (card).
