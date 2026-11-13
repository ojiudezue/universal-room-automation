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

## Live validation (prospective)

- Next digest flush: digest rows with channel `digest` delivered; heartbeat or digest carries the no-route line only if
  holes remain.
- `notification_log` audit rows since restart: `digest_queued`, not `no_channel_fired`, for sub-HIGH alerts.
- No `nm.no_route_tripwire` anomaly.
- `delivery_rate` sensor and `no_route_count` diagnostic present.

## Not done

- NM-DIGEST-MARK-RACE-1 (rows queued mid-send marked delivered) carded.
- Trimming the noisy stuck_signal / circuit_anomaly sources: next card after the digest volume is visible.
- Music-following test's unscoped `sys.modules` patch left in place (card).
