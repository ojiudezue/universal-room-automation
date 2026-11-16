# Review A: NM-DIGEST-MARK-RACE-1 (branch fix/nm-digest-mark-race, b11ff29e)

Tier 1, one review, framing A (local correctness + edge cases). Static review by ura-reviewer, 2026-11-16 overnight pass; pytest withheld because another session was running full suites. Mutation drill run by the orchestrator (see card).

**Verdict: SHIP.** No CRITICAL / HIGH / MEDIUM.

## Findings

| # | Severity | Finding | Bug class | Fixed? |
|---|---|---|---|---|
| A-L1 | LOW | Audit-sentinel rows are now drained only by a flush that carries at least one real row; a person with only heartbeat / optimizer-only flushes keeps audit rows at delivered=0 until the next real digest. The only delivered=0 reader (`get_pending_digest`) excludes audit rows, so nothing reads them; row count unchanged. | Suppression needs a discharge (bounded-growth variant) | Accepted as a stated trade-off, no fix |
| A-L2 | LOW (info) | `test_nm_image_delivery.py:733` is a source-text check, not a runtime test; runtime proof is the new `test_body_rows_marked_and_audit_drained_up_to_mark`. | Hollow test anchor (#62) | Not changed (pre-existing) |

## Checks that passed
- Single production caller passes the new `max_id` (`notification_manager.py` `_fire_digest`); test doubles accept any args; rows without `id` give no mark.
- High-water mark is sound: read and UPDATE share person_id / delivered=0 / severity filters; AUTOINCREMENT ids are assigned inside the single SQLite writer transaction, so no row with id <= mark can appear after the read; `ORDER BY timestamp` affects body order only; no code resets delivered to 0; `_format_digest` has no row cap.
- Heartbeat path unchanged; optimizer-only flush now marks nothing (deliberate, expectation flipped at `test_notification_manager.py:1613`).
- Tests discriminate: dropping `AND id <= ?` or computing the mark after the send should turn the new real-schema tests RED.

## Statistics

| Severity | Found | Fixed | Deferred/accepted |
|---|---|---|---|
| CRITICAL | 0 | 0 | 0 |
| HIGH | 0 | 0 | 0 |
| MEDIUM | 0 | 0 | 0 |
| LOW | 2 | 0 | 2 |

Bug classes: suppression-needs-discharge 1, hollow test anchor 1. No new class for QUALITY_CONTEXT.md.
