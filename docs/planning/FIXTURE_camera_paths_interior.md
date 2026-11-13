# Camera path fixture: outside to inside (operator, 2026-11-12)

Hand-built by the operator; this is the acceptance fixture any automated adjacency (D7 interior track sequence,
person-sighting chains, vision batch chains) is diffed against. Names are the operator's. Camera entity/stem resolution
is still to be filled in from the CameraResolver registry (do not guess stems; resolve by device).

## Garage / back door to upstairs

| Stage | Cameras (in order) |
|---|---|
| Exterior | Back PTZ, G5, Doorbell Lite |
| Egress | Garage A |
| Interior | Garage hallway/stairs (covers the long garage hallway and the stair bottom) > Stair top > Game room > Upstairs hallway |
| Branch | Garage hallway/stairs > Family room (into the living room) |

## Front door

| Stage | Cameras (in order) |
|---|---|
| Exterior, left approach | Front PTZ > Entry way |
| Exterior, right approach | Utilities PTZ > Entry way |
| Exterior, driveway | Sonoff window cam (now faces the front driveway) |
| Egress | Entry way, Foyer |
| Interior, living room track | Foyer > Family room |
| Interior, master suite track | Foyer > Master hallway |

## Patio

The patio camera covers the covered patio, a hallway between interior and egress. When the patio doors are open it
shares a field of view with the family room camera (expect simultaneous detections; dedupe, not a hop).

## Operator answers (2026-11-12, later)

- **Doorbell Lite is EGRESS** for the garage: it sits just outside the garage and views it and the back driveway
  (matches the live egress config grouping it with Garage A). The garage table's exterior row is Back PTZ, G5.
- **Foyer is INTERIOR** (properly indoor) but sees the front door from high up, so it can serve as a door witness.
  It is not classed as egress because the front door already has two egress cameras.
- **"Entry way" = Front door aerial.** The front door's egress cameras are Front door aerial (from above) and the G6
  Entry doorbell (from the side). Both see a person almost at the same time from different angles; treat as one
  crossing, two views. Aerial is poor for faces but good for counting; the G6 doorbell is the face camera.
- **Sonoff window cam (driveway) leads to** Front door aerial and the G6 Entry doorbell.

Corrected front-door path: Front PTZ (left) / Utilities PTZ (right) / Sonoff window (driveway) > {Front door aerial,
G6 Entry} (egress, simultaneous) > Foyer (interior, door witness) > Family room or Master hallway.

Still open: Garage B path; patio egress (add one?); is "Game room" the `playroom` camera.

## Open items

- Resolve each name to its physical camera (CameraResolver `canonical_camera_key`) and list its Frigate/Protect legs.
- Measure hop rates and lags per ordered pair from recorder history (D7 / D0-SIM input).
- Compare with the live `door_interior_neighbours` option and the exterior adjacency map; differences are findings.
