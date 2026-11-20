# DRAFT: Lock page shows the lock's last-seen age (SECURITY-LOCK-PAGE-LAST-SEEN-1)

Fold into the next release README.

## What changed
When a swept lock has not reported since HA restarted, the HIGH "Lock not verified" page now says
"last seen N h ago (before restart)", using the lock's Z-Wave last_seen sensor. It used to say
"last report unknown". Display only: the pre-restart stamp still does not count as a report, so
staleness, the dead-node debounce and the repage timing are unchanged
(`domain_coordinators/security_lock_freshness.py` `sweep()` / `_page()`).

- A missing, disabled, unparseable, timezone-naive or future-dated last_seen keeps the old text.
- A stamp after boot but inside the boot grace window prints the age without "(before restart)".

## Tests
`quality/tests/test_security_lock_freshness.py`: page wording for stale, dead-node and offline
pages; the fallback cases; the grace-window label; and a check that freshness values (real
report time, age, stale set) do not change. Mutation drills went RED on each guard.
Review record: `docs/reviews/code-review/overnight_2026_11_20_lock_page_and_ble_drill_review.md`
(SHIP, 2 LOWs fixed in 5a9f2687b).

## Live validation (after the restart)
- When a lock that died before the restart is paged, the message contains "last seen" plus an
  age, not "last report unknown". The garage lock (node 10) is the live case if it is still silent.
- `sensor.ura_security_coordinator_*` lock sweep attributes `freshness_age_h` / `stale` behave as
  in v5.108.38 (no change expected).
