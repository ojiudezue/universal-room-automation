# v5.108.25: person-awareness layer ship 3b (device-level dead-camera rule)

Card: DEAD-CAMERA-DEVICE-RULE-1 (parent NVR-WITNESS-CONSOLIDATION-1, whose W2-W6 stay open).

Branch `feature/layer-ship3b`, merged with develop v5.108.24 (ship 3a). Tier 3. Plan:
`docs/planning/PLANNING_person_awareness_layer_ship3.md` rev 3.8 §6 (D6, option A decided Q11, device level decided
Q12). Charter: `docs/planning/ARC_DRIFT_ANALYSIS_identity_vision_census_2026_11_13.md`; arc map step 9a.

## What ships

A physical camera is a registry device. It is reported dead only when every paired NVR device has lost it.

- **Pages (INV-DEAD-CAMERA).** A new owner, `CameraTwinHealth`, lives on the coordinator-manager entry. It builds a twin
  map from the W1 registry pairing (Frigate device with its Protect, Reolink, Amcrest or Dahua sibling, every enabled
  camera entity on an NVR platform) and pages each group once per outage:
  - HIGH (S2) only while every member device is lost and the latest member's loss stamp plus the hold cap has passed;
  - S1 only when both caps are 0;
  - a MEDIUM "one NVR down, the other still sees it" notice;
  - one LOW from whoever owns the outage at its end.
  Groups that no URA reader uses are not paged by 3b (PERIMETER-RING-CAMERAS-STREAM-WATCH-1 and W2 own them).
- **Rooms defer to the owner.** A room suppresses its own page only when the owner pages that device's group. While the
  owner is present but not ready, the room defers, bounded by `CAMERA_TWIN_BOOT_SETTLE_S` (600 s), and then pages, so
  there is no silent outage (worst-case room page delay about 660 s, review D2).
- **Holds at device level (INV-DEAD-INPUT).** Room trackers resolve each input to its camera device. A device is live
  if any enabled camera entity on it is live. The 10 person sensors on multi-camera Protect and Reolink devices, which
  resolved to no camera before, are now held and released by the existing S1/S2 rules, the same as Frigate.
- **House tracker.** Census and zone camera entities that no room watches (live: the foyer group) get the same stamps
  through the owner's house tracker. House getters ask it only when the room fold has no opinion.
- **Send result.** `fire_stuck_signal_ex` returns SENT / ALREADY_SENT / NOT_SENT. Latches are set after the send, so a
  deferred or failed page comes back next tick.
- **Diagnostics.** The coordinator-manager diagnostics download gains `camera_twin_health` (counters only, no entity
  ids, device ids or page keys).

### New pages, named

- Garage Doorbell Lite, Camera_Protect_GarageHallway and Reolink TrackMix (unpaired multi-camera devices a room watches)
  can now send a room S2 HIGH per device.
- garage_a / garage_b page as owner groups because a room reads them. Both of these are room-input health, not
  door-camera health.

### Cost

A Protect or Reolink device that drops off while its person sensor sees a body is now held in the census and zone
camera tier for up to the 900 s cap, as Frigate already is. AWAY through the census can be delayed by up to 15 min in
that case. The empty-house anchor stays on per-device holds (operator chose A on 2026-11-14).

## Reviews

| Review | Verdict | Doc |
|---|---|---|
| A local correctness | FIX-REQUIRED (A-M1: rooms suppressed when no one would page); fixed as the bounded DEFER | `docs/reviews/code-review/v_layer_ship3b_review_A.md` |
| B integration / lifecycle | FIX-REQUIRED (B-M1, same path as A-M1); fixed | `v_layer_ship3b_review_B.md` |
| D adversarial completeness | FIX-REQUIRED (D-M1 same-tick double HIGH, D-M2 disabled room drops a camera from U, D-M3 = A-M1); fixed | `v_layer_ship3b_review_D.md` |
| D2 re-check of the fix-up | SHIP: all MEDIUMs closed against the new code; LOW-1 and LOW-3 then fixed | `v_layer_ship3b_review_D2.md` |
| G goal fidelity | SHIP, with two checkpoint items (anchor stays per-device; garage doorbell pages) | `v_layer_ship3b_review_G.md` |
| C per-site mutation | FIX-REQUIRED (2 HIGH, 10 MEDIUM test gaps; no production defect), closed by 32 tests, 51 drills RED | `v_layer_ship3b_C.md` |

Orchestrator check: re-grepped the policy and send sites; mutating the `pages_device` gate to always SUPPRESS gives 6
failing tests; mutating `_group_dead` from `all` to `any` gives 26 failing tests; both restored, tree clean.

Full-suite name-diff: see the validation table below.

## Not delivered (plan completion tracking)

- Per-reader twin coverage (option B) and the empty-house anchor on physical-camera-dead: DEAD-CAMERA-TWIN-COVERAGE-1,
  to be absorbed by NVR-WITNESS-CONSOLIDATION-1 W2 (one physical camera, two witnesses).
- Census face reads stream health: CENSUS-FACE-READS-STREAM-HEALTH-1.
- Dual-lens package channel membership: DUAL-LENS-PACKAGE-CHANNEL-MEMBERSHIP-1 (no live effect today).
- Reader-less pairs and door-camera health: PERIMETER-RING-CAMERAS-STREAM-WATCH-1.
- Documented residuals: D-L1, LOW-2, LOW-4 (state-of-play doc); D-L3 skipped as pre-existing; review C X14 is an
  equivalent mutant today.

## Live validation (prospective)

- **Boot:** no URA ERROR or traceback after restart.
- **Owner:** the coordinator-manager diagnostics download contains `camera_twin_health` with the map built
  (admitted pairs about 17, rejected about 3) and no entity ids.
- **No false HIGH:** no `camera_stream_dead` / `camera_stream_hold_released` HIGH for an in-map camera while its twin
  reads live, over the restart window.
- **Room input exclusions:** sensors on a live device show no new exclusion in `sensor.<room>_unavailable_entities`.
