# v5.58.1 — Hotfix: Perimeter Alert Snapshots (no-picture fix)

Operator report 2026-08-06 ~23:56 CDT: perimeter iMessage alerts arrived
text-only while Frigate held has_snapshot=True events for the exact
window (verified via Frigate API).

Root cause, two defects in the snapshot event-id cache:
1. **Clear-on-end race:** the cache popped the Frigate event id the
   moment the event ended — a brief walk-past ends before dispatch
   resolves, erasing the id exactly when needed. Frigate snapshots
   OUTLIVE their events; the id now persists with
   FRIGATE_SNAPSHOT_ID_TTL_S=120 (rung-1; 0 = kill).
2. **Case-split keys:** cache keyed by Frigate's raw camera name
   (CamelCase) vs lowercase stem lookups — porch-camera snapshots could
   never match. Keys canonicalized both ends.

Tier-1 review: SHIP — cross-person mis-attachment proven architecturally
unreachable (any new person event overwrites the cache before its own
sensor edge dispatches; 300s cooldown > 120s TTL); LOWs applied. 3 new
behavioral tests + 2 mutation drills red-verified; 73/73 file, suite
8304/21-pre-existing.

## Live Validation (prospective)
- **Live:** next perimeter person alert carries the at-detection Frigate
  snapshot attachment (zero dispatch delay).
