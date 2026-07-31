# URA v5.36.2 — H6 hotfix: B1 suppression completeness (override self-count)

Tier-1 sibling of v5.31.0 B1. **H6 root-caused via recorder trace:** overrides_today
climbed 22-30/day on an EMPTY house in +3 jumps (all 3 zones) on the ~5-min HVAC
decision cadence — each resolved-range `set_temperature` emit flips Carrier presets
to `manual` in the same second, and FOUR writer sites called `suppress()` WITHOUT
`kind="temp"`, so the passthrough counted URA's own side effect as a human override
(and looped: count → restore away → next cycle re-flips). Bug Class #53-adjacent:
helper adopted at some sites, not all.

## Fix
`kind="temp"` added at: hvac.py:1663 (preset-override range emit), hvac_predict.py:936
(banked release), :1012 (banking setback), :1150 (pre-heat). Adjudicated as correctly
untagged: hvac.py:1181 (set_hvac_mode), :1415 (set_preset_mode — transitions are
→non-manual), optimization.py:394 (generic broker, shadow mode, not implicated —
review note). Known accepted tradeoff unchanged: a genuine human manual flip within
the same 5s window is swallowed (same as B1).

Follow-up flagged for the planner: move suppress() into the `emit_set_temperature`
chokepoint so future callers can't repeat this class.

## Validation
- H1: clean boot. H2 (the real proof): `overrides_today` stays ≈0 on the next empty-
  house day (vs 22-30). Recorder: no more +3 jumps on the 5-min cadence.
