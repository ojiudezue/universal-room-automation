# v4.2.26 — Retro review fixes (M1, M3, M5)

**Date:** 2026-05-04
**Type:** small fixes from retroactive review of v4.2.22-24

## Summary

Single-pass adversarial review of the three cover/save hotfixes shipped tonight under time pressure surfaced 3 fixable items. All low-risk, ship-safe.

## Changes

### M1: Dedupe duplicate cover IDs in `_send_covers_with_verify`
`automation.py` — input list is now run through `dict.fromkeys()` before send. A misconfigured covers list with the same entity twice would otherwise fire two service calls per cycle, wasting RF bursts. Test added: `test_duplicate_cover_ids_are_deduped`.

### M3: Drop dead `timeout=5.0` on cover service calls
`automation.py` — `blocking=False` makes HA's `async_call` return immediately; the `timeout` parameter is meaningless and was misleading. Removed.

### M5: Strengthen AST guard for Bug Class #28
`quality/tests/test_update_listener_async.py` — now resolves attribute-access handlers (`add_update_listener(self.foo)`) in addition to bare names, via a new `_handler_name()` helper. Unresolvable shapes (lambdas, partials, cross-module references) are surfaced in the assertion message for human audit rather than silently skipped.

## What we parked

| ID | Severity | Reason |
|---|---|---|
| H2 | HIGH | Practically unreachable — no `await` between flag set and scheduler call |
| H3 | HIGH | Manual-retry button is a feature, not a bug. Future enhancement |
| H4 | HIGH | Tilt-cover thresholds are academic until tilt support lands |
| M4 | MEDIUM | Per-room configurable settle is a feature. Defer |
| M6 | — | Invalidated — HA awaits coroutine callbacks for `async_track_state_change_event` and `async_dispatcher_connect` |
| L1-L5 | LOW | Test debt + stylistic; tracked, not blocking |

Full review doc: `docs/reviews/code-review/v4.2.22-24_retro.md`

## Tests

1727 passed (+1 dedup test vs v4.2.25 baseline of 1726), 86 failed (= baseline → zero regressions).

## Deploy notes

No HA restart strictly required (changes are scoped to internal cover helper logic + a test). The reduced RF traffic from M1 dedup will only show up if a user has a duplicate entry in their covers list (today: nobody, but the guard is now in place).
