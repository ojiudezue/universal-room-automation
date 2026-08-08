# URA v5.64.0 — XCORR-1: burst demotion for isolated single-camera night alerts

**Problem (lived, 2026-08-08 01:01–01:25):** `hot_tub` fired 5 times in 18 minutes. The Protect leg
on that same camera never agreed. No adjacent camera saw anything. The operator got **12
notifications** in 24 minutes for what was almost certainly IR/steam/insect false positives. URA
behaved correctly on bad input — the input was the problem.

## The probe rejected the obvious fix

The intuitive design — "if the sibling engine on the same camera stayed silent, it's a false
positive" — was measured before being built (`AUDIT_xcorr_engine_corroboration_probe.md`, 8 days,
30s window) and **rejected**: solo firing is the NORM on exactly the cameras that matter —
front_side_ptz **92%** solo, back_yard **91%**, pool_equipment **93%**, hot_tub **77%**. Gating on
corroboration would have suppressed 77–93% of exterior person detections *including real ones*.
The engines don't share fields of view or sensitivity per camera, so "sibling silent" means
something different on every camera; there is no house-wide threshold. (Contrast: Frigate on the
door cameras is near-perfectly corroborated — madrone_g6_entry 0% solo, front_door_aerial 3%.)

## What shipped instead — the pattern that was actually diagnostic

> **The FIRST alert is sacred — always full severity.** The 2nd..Nth alert from the same collapsed
> camera-key within the window is DEMOTED (to LOW, never silenced) only when **all three** hold:
> no sibling-engine corroboration on that camera, no adjacent-camera activity per the linker, and
> deep-night.

Composes *after* the existing severity-map coercion so approach/circling escalations still win, and
alongside — never bypassing — the demote-never-silence invariant (INV-XP) and the per-camera cooldown.

Knobs (rung-1): `PERIMETER_BURST_DEMOTE_ENABLED` (kill switch), `PERIMETER_BURST_WINDOW_S` (1800),
`PERIMETER_BURST_MIN_ALERTS` (2), `PERIMETER_BURST_NIGHT_ONLY` (True).

New linker accessors `adjacent_cameras()` / `has_recent_adjacent_activity()` (NEW — the linker
previously exposed no public adjacency reader; reaching into `_adjacency` would break encapsulation).

**Observability:** `burst_demotions_by_camera` on the exterior open-tracks diagnostic sensor records
the full decision — which of the three conditions held, prior alert count, severity before/after —
so a demotion is explainable without log-level surgery.

## Orchestrator-verified drills

| Drill | Result |
|---|---|
| **Break first-alert-sacred** (remove the `MIN_ALERTS` guard, keep the shape) | **RED ×3** incl. `test_xcorr1_first_alert_never_demoted` and the end-to-end wiring test |
| Remove the `_evaluate_burst_demotion` CALL at the wire site | RED ×9 |
| No-op the callee (keep the call) | RED ×10 |
| Remove the `_record_burst_alert` call | RED ×6 |

Both drills per wired site — remove-the-call *and* no-op-the-callee — per the rule learned six times
this week: a test that calls the helper directly does not prove the helper is called.

## Acceptance criteria

- **Live (safety):** the first alert from any camera is never demoted.
- **Live (organic):** a repeat burst from one isolated camera at night shows LOW severity on alerts
  2..N, with `burst_demotions_by_camera` naming the reason.
- **Live:** a genuine multi-camera traversal is NEVER demoted (adjacent activity vetoes it).
- **Live:** kill switch False reproduces today's behavior exactly.

## Live Validation

(prospective — replaced post-restart)
