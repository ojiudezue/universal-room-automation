# v5.51.1 — NM iMessage Echo-Loop Guard (hotfix)

## Incident (2026-08-05, ~03:07 CDT)

URA's outbound iMessages (sent via BlueBubbles from the operator's own
Apple ID) synced back through the BB new-message webhook with the
`isFromMe` guard defeated, were ingested as inbound replies from the
operator, and each auto-reply re-triggered itself: **12 "Alerts
silenced" replies in 7 seconds** (notification_inbound ids
206741-206752), plus a 4x "Unknown command" burst. One echo entered the
silence path and **silenced alerts without operator intent**.

## Fix — two payload-shape-agnostic rails in notification_manager.py

1. **Rail 1 — self-echo drop.** Every successful iMessage/WhatsApp send
   records its exact body in a ring buffer
   (`NM_ECHO_GUARD_BUFFER_LEN=100`, dedup-on-append so per-recipient
   fan-out uses one slot; TTL `NM_ECHO_GUARD_TTL_S=600`, `0` = kill
   switch). Any inbound on those channels exactly matching a recent
   outbound is dropped before command parsing AND before the silenced
   auto-reply branch. Drops are counted (`echo` pseudo-command +
   `echo_suppressed` attr on the NM inbound sensor) so totals stay
   consistent with what the channel delivered.
2. **Rail 2 — reply floor.** ≥`NM_REPLY_MIN_INTERVAL_S=30` s between
   auto-reply SENDS per (person, channel), scoped to
   `NM_REPLY_RATE_LIMITED_CHANNELS=("imessage","whatsapp")` only —
   companion/pushover cannot self-echo and are never gated. Command
   processing (ack/silence state mutation) is never gated; security
   denials (`safe_word_unauthorized`) are exempt so a repeat
   unauthorized attempt can never look like success.

Recording happens only AFTER a successful service dispatch
(proof-of-send — a failed send cannot seed the buffer); dry-run sends
record nothing.

## Reviews (2, framing-disjoint, autonomous Tier-1 protocol)

- **A (correctness/edge cases):** 0 CRIT, 2 HIGH (buffer sizing under
  fan-out → 100 + dedup; unauthorized-deny swallowed → exempt list),
  5 MED (telemetry visibility, ordering anchor, record-on-success
  anchor, reply-loop anchor, ack-before-gate comment) — all fixed.
- **B (async/lifecycle/regressions):** 0 CRIT, 1 HIGH (rail-2 overreach
  onto companion/pushover → channel scope), 2 MED (record-before-send →
  moved after; restart residual → documented below) — fixed/adjudicated.
- Orchestrator mutation drills: echo-detection neuter, rate-limit
  neuter, scope-widening, dedup neuter — each fails a specific test.

**Accepted residual (B-B3):** the buffers are in-memory; an echo of a
PRE-restart send arriving in the first seconds after boot can process
as one stray inbound (worst case one "Unknown command" reply, after
which its outbound is recorded and the chain dies). A boot-settle skip
was declined per Marginal-Benefit Decomposition — it adds a
time-coupled gate for a one-message residual that cannot re-loop.

## Tests

`quality/tests/test_nm_echo_guard.py` — 14 tests: exact/whitespace
match, non-echo pass-through (incl. "3"/safe word), TTL expiry ±1s,
kill switch, buffer bound + eviction, dedup + TTL-refresh, ordering
anchors (echo < silence < parse), record-after-send anchors, reply-loop
closure anchor, rate-limit behavior (floor, exempt deny, companion
never gated, per-channel floors), telemetry counters, knob defaults.
Full suite: 8125 passed, 19 pre-existing failures unchanged
(baseline-diffed), 0 regressions.

## Live Validation (prospective)

- **Live:** next NM iMessage send produces NO inbound echo row in
  `notification_inbound` (previously every send echoed) OR produces an
  `echo` pseudo-command increment with no reply sent.
- **Live:** `sensor` NM inbound attrs show `echo_suppressed` ≥ 0 and
  rising only when BB reflects.
- **Live:** operator safe-word/`3` replies still get confirmations
  (rail 2 must not swallow first responses).
- **Live:** no "Unknown command"/"Alerts silenced" bursts in the
  operator's thread after deploy.
