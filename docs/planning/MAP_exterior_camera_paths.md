# Poor Man's Exterior Path Map (vision-verified 2026-08-06, ~06:44 house time)

Built by eyeballing live frames from all 12 exterior cameras. Purpose:
orient track-linking, validate the ratified adjacency, and site future
sensors. Corrections operator-supplied same day: ArmCrestASH41B is an
INTERIOR cam (ignore in exterior work); PTZ parked positions confirmed
fine.

## What each camera actually sees

| Camera | View (verified) |
|---|---|
| madrone_g6_entry | Front-door porch (stone column, the 127.0.0.1 doormat); stepping-stone path exits LEFT across gravel toward the front lawn |
| front_door_aerial | Overhead of the same entry court: stepping stones across gravel courtyard → door threshold |
| doorbell_lite | Covered portico looking ACROSS the paver motor court to the street + neighbors (second door onto the court) |
| g5_bullet | Garage forecourt pavers at the garage doors; driveway ribbon curves up-right beside lawn |
| front_side_ptz | Large gravel court with oak island + stone retaining curve; road visible top-left (entry drive circle) |
| rear_ptz | Street-facing lawn with paved walking path, berms, curb + neighbor houses (the rear street frontage) |
| utilities_ptz | Open mowed slope to the tree line; utility pad (condensers) bottom-right |
| reolinkstudybporchptz | Elevated from Study-B porch over the side lawn; pool/spa edge visible right; paved path along the top of frame |
| armcrest (pool overhead) | Overhead pool + spa terrace; stepping-stone path runs along the house side; lawn beyond |
| hot_tub | House-corner corridor: patio slab meeting lawn with planting bed against the house, fence beyond — the pinch point between pool terrace and back yard |
| back_yard | Broad back lawn to the two cabana/pergola structures at the rear fence; black fence on the right |
| pool_equipment | WALLED equipment yard (generator + condensers) with one slatted gate to the lawn — a terminal pocket, not a corridor |

## The map (not to scale; edges = ratified adjacency, all vision-consistent)

```
        STREET (front)                          STREET (rear frontage)
             |                                        |
   [front_side_ptz]  gravel circle -------- [rear_ptz] lawn + public path
        |        \                             /    \
 [utilities_ptz]  \                           /      \  (service enters here
   slope w/        \--- paver motor court ---/        \    or via garage court)
   condensers          [g5_bullet][doorbell_lite]      \
                              |                         v
                    stepping stones             [armcrest overhead]   [back_yard]
                              |                    pool + spa terrace   big lawn to cabanas
                 [front_door_aerial]                        \            /
                 [madrone_g6_entry]                          v          v
                   front-door court                     [hot_tub] corner corridor
                                                              |
                                                       [pool_equipment]
                                                        gated terminal yard
                 [studybporchptz] watches the side lawn between the
                 pool terrace and the rear frontage from above
```

## What vision CONFIRMS about the adjacency rulings

1. **pool_equipment as terminal** — it is a walled pocket with a single
   gate; the only sane approach is lawn-side via the hot_tub corridor.
   The removed pool_equipment↔rear_ptz direct edge is visually right.
2. **hot_tub is the choke point** of the whole back route — every
   pool↔backyard traversal squeezes past that house corner. It is also a
   WIDE view where a walker is small → prime suspect for the missed
   hand-offs, exactly matching the detection audit's threshold/resolution
   findings (PTZ parking and masks already exonerated).
3. **rear_ptz and utilities_ptz share no visible ground** — different
   worlds (street lawn vs utility slope) with the gravel circle between
   them; the removed direct edge is visually right and front_side_ptz is
   confirmed as the mandatory middle.
4. **The motor-court cluster** (g5_bullet, doorbell_lite) and the entry
   court (aerial, g6_entry) connect by stepping stones — matching the
   probe's front_door_aerial↔madrone_g6_entry (11 obs) and
   doorbell_lite↔g5_bullet (5 obs) pairs.

## Seam-camera implication (feeds the detection tuning)

The three middle cameras that drop hand-offs (front_side_ptz gravel
court, back_yard lawn, hot_tub corridor) are all WIDE views where a
crossing person occupies few pixels — visually consistent with the
0.7-threshold + min_initialized:2 confirmation gate at 5 fps being the
miss mechanism. armcrest (overhead) has the best geometry of the middles.
