# Crossing vision, shadow (DRAFT, unversioned)

Card: VISION-CROSSING-SHADOW-1. Plan: `docs/planning/PLANNING_crossing_vision.md` rev 2 (Phase 1, D1-D3).
Branch: `feature/crossing-vision-shadow`. Tier 2-DB. The orchestrator assigns the version at deploy.

## What it does

For every entry or exit crossing on a door camera, URA asks llmvision (`video_analyzer`, the existing
OpenAI entry, `gpt-4o-mini`) to count the people in the clip of the matching Frigate person event, and
stores the answer next to the camera's own count in one `memory_episodes` row
(`crossing_vision_shadow`). Nothing acts on it. It exists so a weekly scorer can tell whether vision counts
crossings better than Frigate does before anything feeds the census (Phase 2).

## Controls

| Control | Default | Notes |
|---|---|---|
| `switch.ura_crossing_vision_shadow` (Coordinator Manager) | OFF | Turn on after deploy. OFF = no call, no row |
| `number.*_crossing_vision_daily_calls` (Notification Manager device) | 40 | Calls per local day; 0 = off. RAM counter, a restart can allow one more cap that day |
| `LLMVISION_ENRICHMENT_KILL` (const) | False | Code kill for all llmvision use |
| `CROSSING_VISION_*` (const, rung 1) | plan §6 | Model, frames 4, width 768, timeout 90 s, match ±10 s, end wait 120 s, cluster 60 s, concurrency 2 |

## Other changes

- `ura_person_egress_event` carries `peak_person_count` (same value as the DB row; None when ambiguous).
- Diagnostics `crossing_vision_today` and `crossing_vision_last` on Outside: Open Tracks (not recorded).
- Trip-wires: `crossing_vision_zero` (HIGH: 5+ crossings in 24 h with the switch on and no usable count),
  `crossing_vision_errors` (MEDIUM: more than 25 % of 8+ calls failed). The weekly memory-writer check pages
  if no row is written for 7 days, including a switch left off for a week.

## Live acceptance (to run after deploy with the switch on)

- Within 4 daytime hours: at least one row with `outcome = ok`, non-null `people_count` and
  `camera_peak_count` (sentinel-only rows mean the payload is broken).
- Every row's `source_ref` matches an `egress_identity_outcome` row's `source_ref`.
- `crossing_vision_today.calls` is at most today's crossings.
- One new `person_entry_exit_events` row has the same `peak_person_count` as the matching row's
  `camera_peak_count`.
- No `crossing_vision` ERROR in the HA log; no trip-wire page on the first day.

Validation results are written back here after the restart.
