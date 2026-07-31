# URA v5.37.1 — clear-field multi-select + "all quiet" heartbeat digest

Tier-1 batch, driven autonomously under the 2026-07-30 mandate (Tier-2 protocol applied:
2 framing-disjoint reviews + orchestrator verification).

## What ships
1. **`clear_sensor_fields` multi-select** (room sensors step) — generalizes the v5.37.0
   unclearable-EntitySelector fix to temperature/humidity/illuminance/water-leak. Writes
   an explicit `""` options override per cleared field (verified falsy at every consumer:
   coordinator/sensor/optimization/safety/energy). Clear wins over a same-submit new pick
   (documented). Control key never persisted; partial programmatic submits unaffected.
2. **"All quiet" heartbeat** — an empty digest flush now delivers "All quiet — no items."
   instead of silent skip (so silence ≠ breakage), through the same `_deliver_digest`
   path (digest_channels multi-select applies). Kill switch `NM_DIGEST_HEARTBEAT_ENABLED`
   (rung-1). **Review B MEDIUM-1 fixed:** heartbeat does NOT call `mark_digest_delivered`
   (a row inserted between the pending snapshot and the mark would have been silently
   marked delivered without ever appearing in a digest — the pre-heartbeat code was
   race-free by returning early; the gate restores that). Optimizer-only-section flushes
   unchanged and still mark.

## Review
A: SHIP (2 LOW — precedence doc + optimizer-branch test, both addressed).
B: SHIP after MEDIUM-1 (fixed + test flipped to assert_not_awaited). MEDIUM-2 (2
heartbeats/day when quiet) accepted for observation — one-const recalibration if noisy.

## Validation
- H1: clean boot. H2: Kitchen Pantry temperature cleared via the new multi-select
  (post-restart) — merged value `""`, other fields preserved. H3 (organic): next quiet
  flush delivers the heartbeat on WhatsApp+iMessage.
