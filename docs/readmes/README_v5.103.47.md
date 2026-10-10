# URA v5.103.47 — Frigate-down alert + census name fix

Two changes. Cards: PERIMETER-DETECTION-WENT-DARK-1, CENSUS-NAME-SPACE-DEDUP-1.

## 1. Alert when the camera fleet goes dark (Tier 2-DB)
Plan: docs/planning/PLANNING_frigate_down_tripwire.md (Rev 2). Plan review, then three framing-disjoint reviews (A correctness/delivery, B lifecycle/precedence, C test authority by per-site mutation), each FIX-REQUIRED and fixed; orchestrator re-drilled; full-suite name-diff 0 new failures.

**Problem.** 2026-10-06 → 10-08 Frigate 2 sat in setup_retry ~58 h. The census read the dark fleet as nobody home and door rows lost head counts. Nobody was told.

**Solution.**
- **One definition of "dark"** (shared helper `compute_camera_input_dark_frame` in camera_census.py): Frigate cameras exist (denominator > 0) AND (≥ 75% of their person-count sensors unavailable OR `frigate_status_2` down). Clears below 25% with status healthy (hysteresis). A house with no Frigate cameras (Protect-only) is never dark.
- **Notification:** optimizer finding `camera_input_dark` after 270 s of darkness (two 5-min ticks), 180 s boot settle, one message per episode. It pages — it bypasses the digest deferral that other sensor-health findings still get — and is exempt from the per-cycle findings cap.
- **New entity:** `binary_sensor.ura_camera_input_degraded` ("Camera Input Dark", on the Coordinator Manager device) mirrors the census latch; attributes give fraction, counts, frigate_status_2 state, affected entities.
- **Presence:** while dark, the camera-based "everyone away" rule (path α) is skipped — dark cameras are not evidence of an empty house. All other rules (path β, GUEST exit, SLEEP) still run.
- Knobs (module constants, review-gated): fire 0.75, clear 0.25, dwell 270 s, boot settle 180 s.
- Not built: automatic Frigate reload (parked; one-tap Reload is enough once you are told).

## 2. Census counts a resident once (Tier 1, 2 reviews)
On 10-08/09 all 6 GUEST triggers were false: the census held "oji udezue" (face-library name) and "oji_udezue" as two people. `_canonical_person_slug` now turns spaces and hyphens into "_" before matching; known-guest names are normalised the same way. Stored DB ids were already slugs (verified), so nothing migrates.

## Live validation (prospective)
- After restart: `binary_sensor.ura_camera_input_degraded` = off with Frigate healthy; fraction_unavailable ≈ 0.
- No URA errors at boot.
- Census: `identified_persons` never contains a space-form name; re-run the 10-08 replay window → GUEST false positives 0.
- Fleet-dark page: proven in-suite (real notify path, default config); not forced live.
