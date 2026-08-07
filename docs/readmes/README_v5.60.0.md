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
  `TRANSIT_DOUBLE_FIRE_DEDUP_SECONDS` (5s), so a camera's Protect+Frigate legs can't double-count and
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

## Live Validation — Validated 2026-08-07 (restart ~14:40 CDT)

| Criterion | Result | Evidence |
|---|---|---|
| Integration loaded @ v5.60.0 | PASS | `manifest.json` = `v5.60.0` on the live `/config` |
| **All five checkpoint areas populated** | **PASS** | Live INFO: `TransitValidator Protect-sourced checkpoints:` → `garage_hallway`, `entry_way`, `master_hallway`, `stairs`, `upstairs_hallway` — all 5 present; `protect_sourced=13` of 24 subscribed |
| Multi-leg collapse per camera (F2 input) | PASS | Each checkpoint lists its Protect + Frigate + F2 legs under ONE area (stairs → `stairs_top_person_detected` + `_person_occupancy` + `_person_occupancy_2`), all keyed to one physical camera for dedup |
| **Registry-update self-heal (F5)** | **PASS — proven live** | Touched a Protect checkpoint entity's registry; the debounced rebuild fired and re-emitted the full inventory at 14:44:05. This is the fix for "Protect loads after URA → checkpoints freeze empty until restart" |
| Enumeration errors | PASS | No enumeration-failure log; `protect_sourced=13` non-zero |
| Kill switch / knobs live-changeable (F6) | IN-SUITE ONLY | Signal path pinned by tests; not exercised live (needs an options write — deliberately avoided until the parent-reload hazard fix lands) |
| One logical sighting per crossing (F2) | ORGANIC (open) | Needs a real crossing; assert one sighting despite Protect+Frigate legs both subscribed |
| No presence-trust inflation | ORGANIC (open) | Compare `path_validated` rate vs prior day once traversals accumulate |

**Method note:** `checkpoint_cameras_by_area` is a Python attribute, not an entity, and URA's logger
runs at WARNING — so validation required temporarily raising `transit_validator` to INFO and touching
a Protect entity's registry to force a rebuild. Log level restored to WARNING afterward.
*Residue:* that registry touch set `icon: mdi:stairs` on `binary_sensor.stairs_top_person_detected`
and was not cleared (tool-call issue); cosmetic only — operator may clear it in the UI.

**Follow-up worth doing:** expose `checkpoint_cameras_by_area` on a diagnostic sensor so this is
observable without log-level surgery. The build deliberately scoped that out; validation showed the
cost of that choice.
