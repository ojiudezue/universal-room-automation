# URA v5.59.0 — Multi-Integration Detection Legs via CameraResolver (cycle-3)

**Cycle:** exterior cycle-3 "resolver-legs". Tier 2-DB (3 framing-disjoint reviews +
orchestrator drills). Review record: `docs/reviews/code-review/v5.59.0_resolver_legs.md`.

## What shipped

- **`CameraResolver.resolve_detection_legs(camera_entity_id, family)`** — new public API
  returning every configured integration's detection sensors (as `DetectionLeg(entity_id,
  engine, integration, device_id)`) for a physical camera + family (person/vehicle/animal),
  built on the existing correlation ladder — no new inference machinery.
- **Retired three generations of hand-rolled slug logic** in perimeter_alert.py
  (`_fused_sibling`, `_protect_person_legs`, `_derive_sibling_sensor`). Perimeter setup +
  rescan now consume resolver legs; the N-legs→one-camera-key→one-alert dedup machinery is
  unchanged and mutation-anchored.
- **Native-AI legs**: Reolink bare `_person`/`_vehicle`/`_animal`; Dahua/Amcrest
  `_smart_motion_human`/`_smart_motion_vehicle` (live-probed 2026-08-07). The perimeter
  dedup/snapshot suffix vocabulary is now **derived from the resolver's** (single source —
  the cycle's CRITICAL was a fork of these two vocabularies).
- **Alias bridge**: `EXTERIOR_CAMERA_KEY_ALIASES` (armcrest + reolink porch entries) does
  the Frigate↔native stem work; Frigate devices carry no MACs on this deployment (verified),
  so the MAC rung cannot. Missing-alias tripwire: WARN when one camera's legs resolve to
  >1 camera key.
- **Kill switch** `PERIMETER_MULTI_ENGINE_LEGS_ENABLED` (renamed from
  `PERIMETER_PROTECT_PERSON_LEGS_ENABLED`; one-release alias retained). OFF restores
  v5.58.0-equivalent behavior (base + `_2` + Protect stem probe + Dahua base recognition) —
  NOT the pre-v5.58.0 shape. Default pinned ON by import-level test.
- **Per-engine disagreement telemetry**: rising-edge counts + sole-firing ratio per
  (camera, engine), surfaced as `leg_firing_by_camera` on the exterior open-tracks
  diagnostic sensor. Observability only.
- **Post-F1-sunset ready**: registry-shape tests pin both Option A (`_2` survivors) and
  Option B (bulk-renamed base ids).

## Acceptance criteria

- **Verify (suite):** 24/24 `test_resolver_legs.py`, 0 skips; full suite baseline-clean
  (21 pre-existing failures, name-diff = 0). PASS pre-deploy.
- **Live:** post-restart, per-camera coverage INFO log lines show `coverage by engine:`
  with ≥2 engines on the nine perimeter cameras (armcrest must list a `dahua` leg;
  porch PTZ a `reolink` leg).
- **Live:** NO "legs resolve to >1 camera key" WARN in the log scan (alias table complete).
- **Live:** NO boot WARN-storm of "no `_2` sibling found" from native-AI-based cameras.
- **Live (organic):** first real traversal seen by ≥2 engines produces exactly ONE alert;
  `leg_firing_by_camera` attr populates non-empty within 24h of organic exterior activity.

## Live Validation — Validated 2026-08-07 (restart 07:18 CDT)

| Criterion | Result | Evidence |
|---|---|---|
| HA up, integration loaded @ v5.59.0 | PASS | `manifest.json` version `v5.59.0` on `/config`; `sensor.ura_presence_coordinator_presence_house_state` = `away` (last_changed 07:19:48 CDT) |
| No "legs resolve to >1 camera key" WARN | PASS | journald core scan post-restart: zero matches (URA WARNs ARE visible in the feed — e.g. Envoy deferred re-validation at 07:20:48 — so absence is meaningful) |
| No "no `_2` sibling found" boot WARN-storm | PASS | same scan: zero matches |
| Zero URA ERROR lines post-restart | PASS | journald scan: none |
| Diagnostic sensor carries new telemetry surface | PASS | `sensor.ura_security_coordinator_outside_open_tracks_diagnostic` state `0`, attrs include `leg_firing_by_camera: {}` (new key present; empty pending organic fires) |
| Per-camera "coverage by engine" INFO log shows ≥2 engines | IN-SUITE ONLY | URA logger runs at WARNING (confirmed via logger/log_info), so the INFO line is suppressed live. The invariant is pinned in-suite (`test_coverage_info_log_site_in_production_source`) and the live risk (missing alias → duplicate alerts) is covered by the >1-camera-key WARN tripwire, which is at WARNING and silent = healthy. |
| One alert per multi-engine traversal; `leg_firing_by_camera` populates | ORGANIC (open) | first real exterior traversal; check attr + single NM alert |

Boot transients observed and dismissed: Envoy deferred re-validation (known daily wedge, operator power-cycle pending); stale-override startup audit reverting Entertainment+Master to `home` (arrester machinery working as designed); master-bath fan entity briefly missing during boot settle.
