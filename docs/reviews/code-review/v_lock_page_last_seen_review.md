# Review: fix/lock-page-last-seen (Tier 1)

Verdict: SHIP. Findings: 0 CRITICAL, 0 HIGH, 0 MEDIUM.

- There is one wording path. `seen` (absolute local time, "last seen 16 Nov 01:37") is used only when `real is None` and a `last_seen` stamp at or before now exists. Otherwise the message is "last report N h (ago)". The relative "last seen N h ago" wording does not exist (security_lock_freshness.py:490-527).
- Timezone handling: `_aware()` parses the stamp and `dt_util.as_local` converts it (:498). There are no naive datetimes.
- "last report unknown" appears only when there is no real report and no usable `last_seen` (:500).
- Cache-restored state stamps are never used. `last_seen_ts` comes only from the `last_seen` entity value, is display-only and does not feed freshness (`cands` is unchanged, :280-283).
- The restored message is unchanged. The stale message changes only when `seen` exists, which is intended.
- Paging, dedup and delivery are untouched.
- Tests: 64 passed.
- LOW: "(before restart)" compares the stamp with `boot_ts` at second precision. This affects only how the message reads.
