# v5.41.0 — Lossless DB Write Ready-Timeout (backlog #13)

## What shipped
Boot-window DB writes are no longer dropped when event-loop starvation stalls the
write worker past 35s. The caller-side wait is now two-stage: WARNING at
`DB_WRITE_READY_SOFT_WARN_S` (35s, with queue depth + elapsed), then continue
waiting to `DB_WRITE_READY_HARD_CAP_S` (300s) — the row completes late instead
of being lost. Only past the hard cap does it raise (loudly, rare). Kill switch:
SOFT >= HARD restores the old single-stage behavior.

Companion hardening from review (the widened wait exposed three latent flaws):
- Worker NEVER abandons a live caller (the old 120s give-up could hand the same
  sqlite connection to the next write mid-block) — warn-tiered unbounded wait,
  safe under the done-invariant (set on every caller exit path incl. cancel).
- Shutdown drain now wakes parked callers promptly (ready-OR-future wait) —
  no 300s shutdown hangs.
- Cancel-mid-park can no longer orphan a queue item into a worker stall.

Root cause context (2026-07-31 investigation): STARTED-window thundering herd /
loop congestion — not write volume (97 rows/8min). v5.16.2 pre-start buffering
unchanged and non-regressed.

## Review
docs/reviews/code-review/db_write_lossless_timeout_tier2db.md — 3 framing-disjoint
reviews (2 HIGH found+fixed) + orchestrator mutation verification. 9/9 cycle
tests; zero suite drift.

## Live Validation — prospective
- **Live:** next 2-3 restarts show ZERO "did not process request" ERRORs; any
  slow-worker WARNs are followed by completed rows (boot-window census/energy/
  house-state/decision rows present in DB for the boot minutes).
- **Live:** restart duration not elongated (shutdown drain wakes callers).
- **Live:** no new URA errors referencing database.py.
