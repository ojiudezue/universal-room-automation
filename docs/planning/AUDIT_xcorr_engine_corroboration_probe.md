# AUDIT — Cross-engine corroboration probe (XCORR-1 go/no-go gate)

**Date:** 2026-08-08 · read-only recorder probe, 8 days, 30s sibling-agreement window.
**Question:** can "the sibling engine on the same physical camera stayed silent" be used as a
false-positive signal to gate deep-night person alerts?

**Answer: NO for the naive design. The probe REJECTS corroboration-gating as specified.**

## Method

Derived 20 physical cameras that carry ≥2 engines from the live registry (frigate
`_person_occupancy`, protect `_person_detected`, dahua `_smart_motion_human`, reolink `_person`;
`_2` and `_package` excluded; alias-collapsed). For each engine's ON events, counted how many had
*any* sibling-engine ON within ±30s ("corroborated") vs none ("solo").

## Result — solo firing is the NORM, not the exception

Frigate legs on the **exterior perimeter** cameras — the ones that actually drive alerts:

| camera | engine | fires | corroborated | solo | solo % |
|---|---|---|---|---|---|
| front_side_ptz | frigate | 265 | 21 | 244 | **92%** |
| back_yard | frigate | 195 | 18 | 177 | **91%** |
| pool_equipment | frigate | 43 | 3 | 40 | **93%** |
| hot_tub | frigate | 43 | 10 | 33 | **77%** |
| armcrest | frigate | 18 | 8 | 10 | 56% |
| utilities_ptz | frigate | 52 | 31 | 21 | 40% |
| rear_ptz | frigate | 71 | 47 | 24 | 34% |
| g5_bullet | frigate | 40 | 30 | 10 | 25% |

**Gating on corroboration would suppress 77–93% of exterior person detections on the four cameras
that matter — including real ones.** That is an unacceptable false-negative rate for a security
path, and it would violate the demote-never-silence invariant in spirit.

Why so much solo: the engines do not share fields of view or sensitivity on the PTZ/bullet cameras.
Protect fires far more on *interior* cameras (family_room protect 726 vs frigate 39; playroom 632 vs
14; foyer 459 vs 10) while Frigate is the near-perfectly-corroborated engine on the door cameras
(madrone_g6_entry frigate 47/47 = **0%** solo; front_door_aerial 3%; upstairs_hall 3%;
master_hallway 4%). So "silence from the sibling" means completely different things per camera —
there is no house-wide threshold.

## Revised design (probe-grounded)

Do NOT gate on single-event corroboration. Gate on the pattern that was actually diagnostic on
2026-08-08: a **burst from one isolated camera**.

> **First alert always fires at full severity.** Demote the 2nd..Nth alert from the SAME camera
> within a window when *all* of: (a) no sibling-engine corroboration, (b) no adjacent-camera
> activity (linker adjacency), (c) deep-night.

This preserves the intrusion-detection guarantee (the first page always goes out) while killing the
2nd–5th repeats — which is exactly what the operator experienced (12 notifications, 01:01–01:25,
one camera, no corroboration, no adjacent camera, Protect silent throughout).

The other half of the spam is **channel fan-out**: each event fanned to 4 channels
(pushover + companion + whatsapp + imessage), so 3 events = 12 buzzes. Demoted repeats should drop
to a single channel / digest — folds into CONSOL-1's contextual severity.

## Deferred / not built

Per-camera adaptive baselining (using each camera's own solo-rate history rather than a global
threshold) is the theoretically better answer but needs far more data and introduces a learned
component; parked with the trigger *"if burst-demotion proves insufficient after a season."*
