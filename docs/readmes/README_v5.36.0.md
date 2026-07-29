# URA v5.36.0 — Per-person digest channel multi-select

Tier-1 (operator ask 2026-07-29: "digests can go out to WhatsApp and iMessage, morning
and evening"). `_deliver_digest` was a single-channel first-wins fallback chain
(Pushover → Companion → WhatsApp → iMessage) — digests could never reach more than one
channel.

## What ships
- New per-person `nm_person_digest_channels` multi-select (pushover/companion/whatsapp/
  imessage) in the NM persons options step. Non-empty → digest fans out to EVERY
  selected channel that is globally enabled + has a per-person target. Empty (default)
  → byte-identical legacy fallback (backward compat).
- Both morning + evening flushes route through the same delivery path (verified — no
  timer changes).

## Throttling-goals accounting (operator question, answered pre-ship)
Interrupt budget unchanged: CRITICAL/HIGH immediate identical; MEDIUM was silently
DROPPED, now batches to the digest (no new pushes). Multi-channel = delivery redundancy
of an already-batched 2×/day artifact, operator-opted per channel. Verified in review:
zero changes to token/cooldown/gate code (grep-clean diff).

## Validation
- H1: clean boot; persons options step shows the multi-select.
- H2: with channels=[whatsapp, imessage], the next digest flush (08:00/18:00) delivers
  the SAME summary on both; `mark_digest_delivered` once. Window: next flush.
