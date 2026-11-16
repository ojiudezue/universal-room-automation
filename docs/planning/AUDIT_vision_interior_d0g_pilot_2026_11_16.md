# Interior vision D0(g) description pilot: operator grades (2026-11-16)

Batch `i20261116-0112` (17 cards, 16 graded) on the LAN grading page; grades in
`quality/tests/fixtures/interior_desc_operator_grades.json`. Model path = crossing vision's llmvision provider
(gpt-6-luna, max_tokens 4000, width 768). Frames: 3 s recording stills via HA's Frigate proxy, last 3 days, moments
with Frigate person_count 1-4 plus empty controls. 18 model calls.

## Counts (operator count = truth)

| Room | Operator | Model | NVR | Description grade | Operator note |
|---|---|---|---|---|---|
| Upstairs Hallway | 1 | 1 | 1 | accurate | |
| Staircase | 4 | 4 | 4 | accurate | |
| Upstairs Hallway | 4 | 3 | 4 | minor errors | |
| Garage Hallway | 2 | 2 | 3 | accurate | |
| Garage Hallway | 2 | 2 | 3 | minor errors | |
| Game Room | 0 | 0 | 0 | accurate | |
| Foyer | 2 | 0 | 2 | wrong | "Fisheye messing up the recogniction. We need a dewarp" |
| Master Hallway | 1 | 1 | 3 | accurate | |
| Game Room | 0 | 0 | 1 | accurate | |
| Master Hallway | 0 | 0 | 0 | accurate | |
| Staircase | 1 | 1 | 2 | accurate | |
| Living Room | 3 | 4 | 3 | minor errors | |
| Master Hallway | 1 | 1 | 3 | accurate | |
| Living Room | 3 | 3 | 3 | accurate | |
| Foyer | 2 | 0 | 2 | wrong | "foyer is empty but living room has 2 people" |
| Master Hallway | 2 | 2 | 3 | accurate | |

Model exact 12/16 (12/14 excluding the fisheye Foyer). NVR exact 9/16; every NVR miss is an overcount except none
(Master Hallway 3 vs 1-2 three times, Garage Hallway 3 vs 2 twice, Staircase 2 vs 1, Game Room 1 vs 0).
Descriptions: 11 accurate, 3 minor errors, 2 wrong (both Foyer fisheye), 0 made things up.

## Gates (plan §9.D0)

- **D0-P3 (ship 2, D3 describe on demand): PASS.** Useful (accurate + minor) 14/16 = 0.875 against
  `INTERIOR_D0_P3_USEFUL_MIN` 12/20 = 0.60. Sample is 16, not 20 (one control dropped by the call cap, one card ungraded).
- **D0-P1 (ship 3, D2 sampling/correction value): FAILS the NVR bar, which means D2 HAS value.** NVR exact 9/16 = 0.56
  (far below the 0.97 Wilson-LB bar) and vision is better (12/16). Per the plan this is an operator question with a
  recommendation: build D2 (vision samples correct NVR overcounts), sized when more grades exist.

## Findings that change plans

1. **Foyer fisheye needs dewarp** before any model read (operator). Card FOYER-FISHEYE-DEWARP-1.
2. **Foyer camera sees the Living Room**: the Foyer NVR count of 2 was the two people in the Living Room. Cross-room
   overlap is real on live cameras; it is the F-b double-count risk in the ledger-floor plan (§1b) and must be measured
   in F-D0 before the floor builds.
3. **NVR overcounts in hallways** (Master Hallway, Garage Hallway): the ship-1 room records that feed the floor carry
   that bias, which `sustained_min` mitigates better than `window_max`.
