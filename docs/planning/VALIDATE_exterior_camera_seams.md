# Exterior camera seams — operator validation sheet

**Generated:** 2026-09-13 from `const.py: EXTERIOR_ADJACENCY_GRAPH` (read-only; no code changed).
**Purpose:** the operator asked to validate the handoff points between exterior cameras.
**Provenance of the data:** `AUDIT_exterior_camera_adjacency_probe.md` — probe pairs
(symmetric filtered count ≥ 3) + "Operator ratification (2026-08-06)".

A **seam** = a declared adjacency edge. It means *"a person leaving camera A can plausibly
appear next on camera B"*, and it is what lets the linker treat N sightings as ONE track
instead of N alerts.

**12 cameras · 27 undirected seams.** The table below is the *symmetrized* graph — i.e. what
the code actually uses. `ExteriorTrackLinker.__init__` symmetrizes, so declaring A→B alone is
sufficient; several edges are declared one-way in `const.py` and are live in both directions.

---

## The 27 seams — tick or strike each

| # | Seam (A ↔ B) | Plausible on the ground? |
|---|---|---|
| 1 | armcrest ↔ back_yard | ☐ |
| 2 | armcrest ↔ doorbell_lite | ☐ |
| 3 | armcrest ↔ g5_bullet | ☐ |
| 4 | armcrest ↔ hot_tub | ☐ |
| 5 | armcrest ↔ rear_ptz | ☐ *(ratified addition — pool service chain)* |
| 6 | armcrest ↔ reolinkstudybporchptz | ☐ |
| 7 | back_yard ↔ front_side_ptz | ☐ |
| 8 | back_yard ↔ g5_bullet | ☐ *(ratified addition)* |
| 9 | back_yard ↔ hot_tub | ☐ *(ratified addition)* |
| 10 | back_yard ↔ rear_ptz | ☐ *(ratified addition)* |
| 11 | doorbell_lite ↔ g5_bullet | ☐ |
| 12 | doorbell_lite ↔ rear_ptz | ☐ |
| 13 | front_door_aerial ↔ front_side_ptz | ☐ |
| 14 | front_door_aerial ↔ hot_tub | ☐ |
| 15 | front_door_aerial ↔ madrone_g6_entry | ☐ |
| 16 | front_door_aerial ↔ rear_ptz | ☐ |
| 17 | front_side_ptz ↔ g5_bullet | ☐ |
| 18 | front_side_ptz ↔ hot_tub | ☐ |
| 19 | front_side_ptz ↔ madrone_g6_entry | ☐ |
| 20 | front_side_ptz ↔ rear_ptz | ☐ |
| 21 | front_side_ptz ↔ reolinkstudybporchptz | ☐ |
| 22 | front_side_ptz ↔ utilities_ptz | ☐ |
| 23 | g5_bullet ↔ madrone_g6_entry | ☐ |
| 24 | g5_bullet ↔ rear_ptz | ☐ |
| 25 | hot_tub ↔ pool_equipment | ☐ *(only chain-terminal edge)* |
| 26 | madrone_g6_entry ↔ rear_ptz | ☐ |
| 27 | madrone_g6_entry ↔ utilities_ptz | ☐ |

### Already removed at ratification (do NOT re-add without evidence)
- `pool_equipment ↔ rear_ptz` — judged physically impossible / missed-intermediate artifact
- `rear_ptz ↔ utilities_ptz` — same

---

## Seam count per camera (degree)

| Camera | Seams | Egress-adjacent? |
|---|---|---|
| front_side_ptz | 8 | yes |
| rear_ptz | 7 | yes |
| armcrest | 6 | yes |
| g5_bullet | 6 | yes |
| back_yard | 5 | — |
| hot_tub | 5 | yes |
| madrone_g6_entry | 5 | — *(is itself an EGRESS camera)* |
| front_door_aerial | 4 | **yes** *(also an EGRESS camera — see Q2)* |
| doorbell_lite | 3 | — *(is itself an EGRESS camera)* |
| reolinkstudybporchptz | 2 | — |
| utilities_ptz | 2 | yes |
| **pool_equipment** | **1** | — |

---

## Why the seams matter (the consumers)

1. **Track linking** — an event links to an open track only if the new camera is adjacent to
   the track's last camera AND Δt ≤ `TRACK_LINK_WINDOW_S` (**180 s**); tracks close after
   `TRACK_CLOSE_IDLE_S` (**300 s**) idle.
2. **Circling** — `circling` requires a revisit, or ≥ `EXTERIOR_TRACK_CLASSIFY_CIRCLING_CAMERAS`
   (**3**) distinct cameras with a non-monotonic (looping) sequence.
3. **Severity** — `circling` on a perimeter camera in `home_day`/`home_evening` is forced to
   **HIGH** (`const.py:1794`); `away`/`vacation`/`sleep`/`home_night` are **CRITICAL** regardless.

**A missing seam does not silence anything — it fragments.** Two sightings that should have been
one track become two independent first-sightings, so you get *more* alerts, each classified
weaker (`pass_by`/`first_sighting` instead of `circling`). **A wrong-but-plausible seam does the
opposite** — it merges genuinely separate people into one track and suppresses the second alert.
So: strike a seam you don't believe, and expect more/noisier alerts; add one you do, and expect
fewer/sharper.

---

## Three things to check specifically

**Q1 — `pool_equipment` is a dead end (degree 1).** Its only seam is `hot_tub`. A person who
appears there and leaves in any other direction starts a *new* track. Because `circling` needs
3 distinct cameras, activity around the pool equipment can never itself escalate. **Is
`pool_equipment` genuinely reachable only via the hot tub?** If there is a path to, say,
`back_yard` or `utilities_ptz`, that seam is missing.

**Q2 — `front_door_aerial` is listed as egress-ADJACENT although it IS an egress camera.**
The list's own definition is *"perimeter cameras with an edge to any of the three egress
cameras"* (`madrone_g6_entry`, `doorbell_lite`, `front_door_aerial`). `front_door_aerial`
qualifies only because it neighbours `madrone_g6_entry` — another egress camera. The other two
egress cameras are **not** in the list, so the three are treated inconsistently.
*Practical impact is small* (severity for `camera_class == "egress"` short-circuits `track_class`
at `const.py:1803`, and `doorbell_lite`'s neighbours are all egress-adjacent anyway), so this
reads as **cosmetic inconsistency, not a live defect** — but you declared the list, so confirm
it is intended.

**Q3 — `reolinkstudybporchptz` (degree 2) connects only to `armcrest` and `front_side_ptz`.**
Given it is a *study-B porch* camera, is there really no seam to `back_yard` or
`madrone_g6_entry`?

---

## Cross-checks performed (all passed)

- **Symmetry:** every declared edge is live in both directions after
  `ExteriorTrackLinker.__init__` symmetrization. One-way declarations are harmless.
- **Edge count vs. the source comment:** the comment says *"22 after the two removals"*; that is
  the **probe-pair subtotal**. The 5 ratified additions that were not already probe pairs
  (`g5_bullet↔back_yard`, `rear_ptz↔armcrest`, `rear_ptz↔back_yard`, `back_yard↔hot_tub`,
  `hot_tub↔pool_equipment`) bring it to **27**. Consistent — not a drift.
- **`EXTERIOR_TRACK_EGRESS_ADJACENT_CAMERAS` vs. the graph:** recomputed the neighbours of the
  three egress cameras. Nothing missing; the only extra is `front_door_aerial` (Q2).

## How to apply changes

Edit `EXTERIOR_ADJACENCY_GRAPH` in `const.py` (declare one direction only; it symmetrizes).
It is a **rung-1 module constant** — a reviewed code change, deliberately not an options knob.
Kill switch: `TRACK_LINK_WINDOW_S = 0` disables linking entirely (per-camera behaviour).
