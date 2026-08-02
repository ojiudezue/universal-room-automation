# v5.47.1 — Hotfix: Memory Wiring Survives the DB-Init Race

## The bug (found in v5.47.0 live validation)
`async_setup_entry` has TWO DB-init sites (CM path + room path); v5.47.0
wired the memory MVP (facade + `memory_query` service + baseline writer)
only at the first. 40+ entries race the init lock at boot — this boot a
ROOM entry won, so the DB initialized (facts seeded, status sensor live)
while the wiring block was silently bypassed: service absent,
`baseline_last_fold` null, zero errors logged. Nondeterministic per boot.

## The fix
Extracted idempotent `_async_wire_memory(hass, entry)` (guards on the
facade key set BEFORE any await — no TOCTOU on the event loop; pops the
key on failure so a later entry retries) called from THREE paths:
CM pre-lock (covers CM reload with a live DB), CM db-init branch, and
the room-path common DB re-read. The owning entry's unload callback now
pops both guard keys, so a single-entry reload rewires on its own
re-setup instead of leaving memory dead until restart. Double-cleanup
with the DB-teardown path is pop-safe (reviewer-verified).

Review: single adversarial pass (Tier 1), verdict SHIP; TOCTOU,
double-unsub, and CM-reload axes all traced. 3 new source-anchor tests
(35/35 memory suite). Full suite 7965/30 baseline, zero drift.

## Live Validation — prospective
- **Live (the criterion that would have caught v5.47.0):**
  `memory_query` present in the service registry AND
  `baseline_last_fold` non-null within ~10 min of restart.
- **Live:** canonical demo — memory_query narrative for room:study_a
  2026-08-01 returns the fan-incident story with provenance.
- **Live:** facts/profile verbs answer; `unusual_today` populates on
  allowlist rooms within 24h.
