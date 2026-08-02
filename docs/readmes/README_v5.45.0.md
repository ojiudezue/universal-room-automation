# v5.45.0 — CameraResolver: Cross-Integration Physical-Camera Resolution

## What this is
One physical camera often appears in HA as multiple devices — Frigate, UniFi
Protect, Reolink — each exposing different sensors and capabilities. URA
previously had no notion of "same camera": cross-platform matching was a
name-stem heuristic inside the census, and room-level camera presence had been
dead since v3.4.5. This cycle ships `camera_resolver.py`, a shared primitive
that resolves ANY camera-related entity to its physical camera and builds a
per-integration capability map, consumed by (today) the room fusion sensor and
the fan-veto camera leg, and (behind gates) the census.

## The correlation ladder
same-device (with per-camera-object de-fusion inside multi-camera NVR devices)
→ device MAC (format_mac-normalized) → identifiers ((integration,key) tuples)
→ network-inventory join (stub; UniFi client-table wire-up is a future rung)
→ Frigate name-stem (raw + resolution-suffix-stripped on miss)
→ operator declaration (the room_cameras multi-select is ground truth;
ambiguity NEVER guesses).
Frigate×2 same-object devices collapse to one detector family (deterministic
live-state winner; losers watched for recovery re-resolve) until the
cross-host stability gate opens.

## What ships LIVE
- **`room_cameras`** (room config, sensors step): multi-select any camera
  entities; each resolved physical camera becomes a fusion.
- **`binary_sensor.<room>_camera_person_detected` v2**: event-driven (state
  subscriptions + lifecycle re-resolve), OR across cameras with per-source
  attribution, `agreement` (unanimous_on / single_source / split / unanimous_off)
  and `confidence` attrs; same-family ON sources cap confidence at medium.
- **Fan-veto camera leg (divergence-aware)**: camera evidence rebuts the
  comfort-fan away-veto only when agreement is `unanimous_on` OR
  `single_source` OR confidence `high`. **Adjudication (documented):**
  divergence doctrine downgrades DISAGREEMENT (split = a second camera
  actively dissents → deny); absence of a second opinion is not disagreement
  (single-camera rooms keep their rebuttal — same rule as v5.43.0's census
  single-source policy).
- **D4 dry-run**: at setup, logs which person-detection switches WOULD be
  enabled (19 Protect switches live) and inventories face switches
  (face is NEVER auto-enabled — mutation-anchored invariant). No actuation:
  a grep-guardrail test proves zero switch calls exist in the path.

## What ships DARK (each behind its own gate)
| Surface | Flag | Gate to open |
|---|---|---|
| Census cutover to resolver | `CENSUS_USE_NEW_RESOLVER=False` | golden-master diff artifact: captured legacy resolution vs resolver output, every difference explained; separate reviewed flip |
| Frigate F1↔F2 corroboration | `FRIGATE_CROSS_HOST_CORROBORATION_ENABLED=False` | 72h stability (0 MQTT evictions, 0 flap bursts, 0 retained ghosts) from the 08-01 prefix split; earliest ~08-04 |
| D4 live auto-enable | `CAMERA_AUTOENABLE_DRY_RUN=True` | reviewed flip after dry-run inventory validates; `auto_enable_person_detection` options toggle is the operator kill switch |

## Parked with evidence triggers (Review E)
Full weighted/DS fusion scorer (trigger: sustained `split` >5%/day on Study A);
MAC/identifier live consumers (trigger: a home with cross-integration MAC
parity); post-gate family half-weighting (trigger: gate open AND ≥3 same-family
sources on one camera).

## Review
docs/reviews/code-review/camera_resolver_tier3.md — FIVE reviews (A-D +
external-expert E with 21-source literature grounding) + D-prime re-sweep +
orchestrator drills. 7 HIGH-class findings found and fixed, incl. a
booby-trapped cutover flag, three independent stem-matching holes, an
OR-fusion doctrine regression, and four hollow test anchors.

## Live Validation — prospective
- **Live:** boot clean: zero URA errors; D4 dry-run INFO lines present
  (per-room would-enable list + face inventory); NO switch.turn_on issued
  (log scan).
- **Live:** census UNCHANGED (flag dark): census_snapshots row shape and
  counts continuous across the deploy boundary; `unifi_count`/`frigate_count`
  populated as before.
- **Live:** fused sensor appears for any room with room_cameras configured
  (none on deploy day — configure Study A as the harden bench, then verify
  attribution attrs + event-driven updates).
- **Live:** fan-veto behavior unchanged for all rooms without room_cameras
  (legacy allowlist path byte-preserved; veto counters move only per prior
  cycles' semantics).
- **Live:** no zone-snapshot/resolver WARN storms; resolver logs only at
  resolution events.

### Validated 2026-08-01 (~19:20 CDT, first post-deploy boot)
| Criterion | Result | Evidence |
|---|---|---|
| Clean boot | **PASS** | Zero URA ERRORs post-settle. |
| Census unchanged (cutover flag dark) | **PASS** | census_snapshots continuous across the deploy boundary (one 12-min warmup gap on first tick, then normal cadence; row shape and counts identical — legacy path confirmed live). |
| No fan actions in boot window | **PASS** | Zero fan rows (v5.42.0 BUG-1, 4th consecutive clean boot). |
| D4 dry-run inventory + zero actuation | **PASS-structural** | No switch.turn_on exists in the code path (grep-guardrail test); zero rooms have room_cameras yet so per-room lines are correctly absent (B-MED-2 early-return). |
| Fused sensor + attribution | pending-config | Appears when the first room (Study A bench) gets room_cameras configured. |
| Veto unchanged for camera-less rooms | **PASS** | No veto-related log changes; legacy allowlist path in force. |
