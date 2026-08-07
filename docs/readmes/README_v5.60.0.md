# URA v5.60.0 — Protect-sourced traversal checkpoints (TRANSIT-1)

**Problem:** the interior room-to-room traversal validator sourced its checkpoint cameras from a
hand-maintained list (`CONF_CAMERA_PERSON_ENTITIES`). Lists drift — 2 of the 5 real checkpoints
(upstairs hallway, stairs) had silently fallen out, and a third was wired to a sunset-exposed
Frigate entity. A camera dropping out of that list silently degrades path validation with no signal.

**Solution:** enumerate checkpoint cameras from **UniFi Protect** (the authoritative inventory —
it sees every camera) via the resolver, attribute each to its room **by area**, and union that with
the hand-list. A camera can no longer drift out of coverage.

**Tier:** 2-DB (feeds presence trust). 3 framing-disjoint reviews + orchestrator drills.
Review record: `docs/reviews/code-review/v5.60.0_transit_protect_checkpoints.md`.

## What shipped

- **`CameraResolver.enumerate_platform_cameras(platform, family)`** — pure registry walk; groups by
  `(device_id, stem)` so an NVR device hosting several physical cameras yields one row each;
  collapses F1/F2/cross-platform siblings via `resolve_detection_legs`; attributes area
  Protect-leg-first with a **same-platform** cross-leg fallback.
- **transit_validator** — Protect enumeration unioned into `TransitValidator.async_init` and
  `EgressDirectionTracker.async_init`, filtered to `CONF_TRANSIT_CHECKPOINT_AREAS`
  (default: master_hallway, entry_way, garage_hallway, upstairs_hallway, stairs).
- **The decision path honors it** — `_get_shared_space_cameras()` and the camera-active check union
  the Protect set, so recovered coverage actually counts in `validate_transition` (this was the
  cycle's CRITICAL review finding: previously recorded then filtered out).
- **Double-fire collapse** — sightings dedup by physical `device_id` within
  `TRANSIT_DOUBLE_FIRE_DEDUP_SECONDS` (5s), so a camera's Protect+Frigate legs can'tdouble-count and
  inflate presence trust.
- **Self-heal** — `EVENT_ENTITY_REGISTRY_UPDATED` (unifiprotect) triggers a debounced rebuild, so a
  late-loading Protect integration no longer freezes the checkpoint set empty until restart.
- **Live-usable knobs** — `SIGNAL_URA_TRANSIT_CONFIG_CHANGED` rebuilds locally on options change (no
  parent-entry reload / watchdog hazard). Kill switch `CONF_TRANSIT_PROTECT_SOURCED_ENABLED`;
  empty `CONF_TRANSIT_CHECKPOINT_AREAS` is honored as an explicit "none".
- **Diagnostic** — `checkpoint_cameras_by_area` on TransitValidator.

**Depends on:** the 39 live camera area corrections applied 2026-08-07 — area attribution is the
foundation this feature stands on (`AUDIT_resolver_ground_truth_manual.md`).

## Acceptance criteria

- **Verify (suite):** 17/17 in `test_transit_protect_sourced.py`; full suite baseline-clean
  (21 pre-existing failures, name-diff = 0). PASS pre-deploy.
- **Live:** post-restart, `checkpoint_cameras_by_area` contains ≥1 entity for **all five**
  checkpoint areas.
- **Live:** log line reports the Protect-sourced checkpoint count at init; no enumeration failure.
- **Live (drift-proof, the headline):** a Protect camera at a checkpoint area is covered **without**
  appearing in `CONF_CAMERA_PERSON_ENTITIES`.
- **Live (organic):** a real room-to-room crossing at a checkpoint produces exactly **one** logical
  sighting (not two) despite Protect+Frigate legs both being subscribed.
- **Live:** no presence-trust anomaly — `path_validated` rate not inflated vs the prior day.

## Live Validation

(prospective — replaced with the Validated table post-restart)
