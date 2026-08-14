# AUDIT: Frigate-2 first-witness latency vs UniFi Protect (daytime perimeter person events)

**Date:** 2026-08-13 (analysis run ~12:15 CT) · **Cycle:** FRIGATE-RETIRE-1 · **Read-only recorder probe**

## Question

F2 (`binary_sensor.<cam>_person_occupancy_2`) just became the primary snapshot source. On daytime
perimeter person events, does F2 witness first, or does it systematically lag UniFi Protect
(`binary_sensor.<cam>_person_detected`) enough (>5 s) that alert photos capture late scenes?

## Method

- HA recorder DB read-only over ssh (`sqlite3.connect('file:/config/home-assistant_v2.db?mode=ro', uri=True)`),
  all queries scoped by `states_meta.metadata_id` — no unfiltered `states` scans.
- Perimeter cams in scope: back_yard, front_side_ptz, hot_tub, pool_equipment, g5_bullet,
  utilities_ptz, rear_ptz. Sources per cam: F2 `_person_occupancy_2`, Protect `_person_detected`,
  native AI where present (`binary_sensor.armcrestpooloverhead_smart_motion_human` for pool_equipment).
- `off→on` transitions only, clustered into episodes (gap > 120 s = new episode); per episode,
  first-witness source + F2-minus-Protect delta of the two sources' first `on`.
- **Window widened from "today 09:00–now" to the last 7 days, 09:00–19:00 local.** Today
  (2026-08-13) produced only 14 on-transitions and **zero paired F2+Protect episodes** — no
  camera had both sources fire in the same episode today, so today alone cannot answer the question.
  All three source families were verified alive (7-day row counts 73–553 per sensor; all currently
  `off`, none `unavailable` — except the retired F1 base sensors, which went `unavailable` at
  11:37 today, consistent with the F1 retirement).

## Aggregate results (7 days daytime, n = 226 episodes)

| Metric | Value |
|---|---|
| Paired F2+Protect episodes | 62 |
| Median F2−Protect delta | **+1.3 s** (positive = F2 later) |
| Mean delta | +10.8 s (tail-dominated) |
| Range | −61.7 s … +201.6 s |
| F2 first (paired) | 19/62 (31%) |
| Deltas within ±3 s | 32/62 (52%) |
| F2 lags > +5 s | 22/62 (35%) |
| F2 lags > +25 s | 8/62 (13%) |
| Single-witness episodes | F2-only **126**, Protect-only **32**, Native-only **13** |
| Multi-witness first counts | Protect 42, F2 19, Native 2 |

## Per-camera F2−Protect deltas (paired episodes)

| Camera | n | Median | Worst lag | Notes |
|---|---|---|---|---|
| rear_ptz | 18 | **+5.8 s** | +135.3 s | Worst camera; F2 first only 3/18. Also 20 Protect-only episodes (F2 missed entirely). |
| g5_bullet | 17 | +0.8 s | +201.6 s | Median fine, heavy tail (4 episodes > +45 s). |
| hot_tub | 9 | +0.8 s | +77.7 s | Mostly sub-second either way. |
| back_yard | 8 | −0.2 s | +5.5 s | Prompt; and 100+ F2-only episodes Protect never saw. |
| front_side_ptz | 4 | −3.6 s | +18.1 s | F2 usually first. |
| utilities_ptz | 3 | −0.4 s | +4.5 s | Prompt. |
| pool_equipment | 2 | +1.2 s | +1.9 s | Native (armcrest smart_motion_human) is the dominant sole witness here (13 native-only episodes). |

(Full per-episode table reproducible via the probe query; representative extremes:
08-10 09:18 g5_bullet F2 +201.6 s; 08-07 14:11 rear_ptz +135.3 s; 08-10 09:00 back_yard F2 **first by 61.7 s**.)

## Verdict

**F2 is a prompt witness in the typical case, not a systematic laggard — median +1.3 s, 52% of
paired episodes within ±3 s. No blanket snapshot-quality concern.** But two targeted caveats:

1. **rear_ptz is a genuine laggard for F2** (median +5.8 s, F2 misses ~half of Protect's episodes
   outright). If rear_ptz snapshots matter, worth a card: tune the F2 detect stream/threshold for
   that camera, or keep Protect as the snapshot trigger for rear_ptz specifically.
2. **The tail is real but looks like episode-boundary re-sighting, not detector latency**: 13% of
   paired episodes show F2 +25 s or worse (max +201.6 s). These cluster on PTZ/long-range cams
   (g5_bullet, rear_ptz) where F2 likely picks the person up on a later, closer pass within the
   same 120 s cluster. A late snapshot on those events would show a late scene — acceptable for
   occupancy, marginal for alert photos.

## Gate-2 cleanliness context (single-witness episodes)

- **F2-only: 126 episodes** — overwhelmingly back_yard (~100) and front_side_ptz. F2 sees far more
  than Protect on those views; whether these are extra recall or false positives (vegetation/heat
  shimmer at distance) is the Gate-2 question. Protect corroborates almost none of back_yard's F2 events.
- **Protect-only: 32** — mostly rear_ptz and g5_bullet: real F2 misses on the two long-range cams.
- **Native-only: 13** — pool_equipment's armcrest `smart_motion_human` is effectively the only
  reliable witness for that camera; F2 fired there in only 2 episodes all week.
- **Anomaly:** 2026-08-11 daytime had **zero F2 episodes house-wide** (8 Protect/native episodes) —
  looks like an F2 outage or restart that day; worth confirming against Frigate-2 uptime before
  treating 08-11 as detection data.

*Read-only audit; no configuration or code changed.*
