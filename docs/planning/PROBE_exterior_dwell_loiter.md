# PROBE — Exterior dwell / loiter predicate (`EXTERIOR-DWELL-LOITER-1`)

**Type:** READ-ONLY measurement probe (measure-before-you-build gate). No design, no code.
**Date:** 2026-08-17
**Author:** Oji Udezue
**Data source:** `memory_episodes` (`episode_type='exterior_track'`) in the LIVE URA DB
`/Users/okosisi/ha-config/universal_room_automation/data/universal_room_automation.db`,
opened `file:...?immutable=1` (read-only; DB was WAL-locked by live HA, immutable
snapshot read is the only safe path). Scripts in session scratchpad `probe*.py`.

**Corpus:** 1327 `exterior_track` rows total (one row per CLOSED track). By label:
person=623, car=588, animal=116. **Time span of person tracks: 2026-08-06 → 2026-08-17
(11 days only)** — NOT a long history; every threshold below is derived from 11 days.

**Finding under test:** `ExteriorTrackLinker.classify()` (`exterior_track_linker.py:705-735`)
is purely topological. `circling` iff `revisit_count>=1` OR (`camera_count>=3` AND
non-monotonic path); `approach` iff egress-adjacent camera OR `camera_count>=APPROACH_CAMERAS`
(APPROACH_CAMERAS=0, disabled); else `pass_by`. `duration_s` is computed and persisted but
**never gates a class**. Hypothesis: a person stationary at ONE camera for a long time has
`revisit_count=0, camera_count=1` → `pass_by` → DIGEST/MEDIUM. Loitering is structurally invisible.

---

## Q1 — Duration distribution by classification (label=person)

**METHOD:** Parse `attrs_json.duration_s` grouped by `classification` over the 623 person
tracks; count tracks exceeding 300 / 600 / 1200 s.

**RESULT (seconds):**

| class | n | min | median | p90 | max | >300s | >600s | >1200s |
|---|---|---|---|---|---|---|---|---|
| pass_by | 283 | 0 | 24 | 444 | 4238 | 41 | 15 | 4 |
| approach | 220 | 0 | 13 | 292 | 1581 | 21 | 6 | 3 |
| circling | 120 | 5 | **407** | 3040 | 23750 | 71 | 49 | 34 |

**Interpretation:** The hypothesis is CONFIRMED but partial. Long dwells DO leak into
`pass_by` (41 tracks >5min, 15 >10min, 4 >20min incl. a 4238s = 70-min pass_by) and into
`approach` (21 >5min). BUT `circling` already captures the bulk of long dwells topologically
— its median is 407s and it holds 71 of the 133 person tracks >300s. So loitering is not
*wholly* invisible; the leak is the ~62 long tracks (41 pass_by + 21 approach) that a
one-camera or monotonic path let through. **CONFIDENCE: HIGH** (direct count).

---

## Q2 — Single-camera long-dwell population (what a dwell predicate newly catches)

**METHOD:** person tracks with `camera_count==1` AND `duration_s>threshold`, grouped by `path[0]`.

**RESULT:** 472 of 623 person tracks are single-camera. Of those:

| threshold | n | current classification |
|---|---|---|
| >300s | 56 | 41 pass_by / 15 approach |
| >600s | 21 | — |
| >1200s | 7 | — |

Camera breakdown of the >300s population (n=56):
`front_side_ptz 13, back_yard 12, master_hallway 6, armcrestash41b 5, upstairs_hall 4,
staircase 4, playroom 3, family_room 2, doorbell_lite 2, rear_ptz 2, +5 singletons`.

**DECISIVE SPLIT — interior vs perimeter cameras:** The "exterior" linker ingests INTERIOR
cameras too. Of the 56-track newly-caught population:
- **19 (34%) are INTERIOR cameras** — `master_hallway 6, upstairs_hall 4, staircase 4,
  playroom 3, family_room 2`. These are residents standing/sitting INSIDE the house.
- 37 are perimeter, but dominated by `back_yard 12` and pool/hot-tub area — the household's
  OWN backyard, where residents legitimately dwell (sitting outside, hot tub). Only
  `front_side_ptz 13` + `doorbell/rear/entry` (~18 tracks over 11 days ≈ 1.6/day) are
  street/approach vantage where a stranger dwell would be a genuine security signal.

**CONFIDENCE: HIGH** for counts; the interior/perimeter tagging used a hand-built interior
set `{master_hallway, upstairs_hall, staircase, playroom, family_room, stairs_top, hot_tub,
garage_a}` — MEDIUM confidence on a few ambiguous names, but the interior contamination is
unambiguous for the named 19.

---

## Q3 — Artifact vs real dwell

**METHOD:** For each camera in the >300s cc==1 population, profile median hop count,
max Frigate `best_score`, and identified-count; compare long-dwell frequency to that camera's
total cc==1 person-track volume to spot chronic (always-on) false-positive cameras.

**RESULT:**
- **Every long-dwell track has `median hops == 1`** and high person confidence
  (`best_score` 0.71–0.94). So Frigate is confidently seeing a person-shaped object held
  active in a single camera for the whole window — consistent with EITHER a real stationary
  person OR a fixed high-confidence false-positive (a person-shaped static object: a chair
  silhouette, statue, poster, reflection). Score alone cannot separate them.
- **`identified` = 0 for ALL 56** long-dwell tracks. Context: only **2 of 623** person
  tracks in the entire corpus were ever face-identified. **Face recognition is effectively
  dead on the exterior pipeline.** This is the single most important finding: the system has
  NO signal to distinguish resident from stranger. A gardener, a delivery driver waiting, a
  resident on the porch, and a prowler all render identically (unidentified person, 1 camera,
  high score, long duration).
- **Chronic-camera check:** `front_side_ptz` produces 113 total cc==1 person tracks (11 days)
  of which 13 are >300s; `back_yard` 55 total / 12 long; `pool_equipment` 53 total / 1 long.
  No single camera shows a "constant long-dwell" fixed-artifact signature (e.g. one camera
  emitting long dwells at a rate near its total volume). `front_side_ptz` and `back_yard` are
  simply the busiest cameras, and their long-dwell share (~12%, ~22%) is elevated but not
  pinned at 100%, so they read as high-traffic vantage points rather than a stuck tree/flag
  artifact. **No chronic fixed-false-positive camera identified in this window.**

**CONFIDENCE: MEDIUM.** Absence of a chronic-artifact camera is a real result, but 11 days is
short and the probe cannot inspect the actual frames — a per-camera fixed artifact that fires
intermittently (wind-moved object) would not be distinguishable here.

---

## Q4 — Truncation interaction (fragmentation) — NOT skipped

**METHOD:** `TRACK_CLOSE_IDLE_S=300`, `TRACK_LINK_WINDOW_S=180` (`const.py:1724-1725`). A track
closes after 300s of silence; one real long dwell can fragment into several tracks. Looked for
consecutive same-first-camera cc==1 person tracks where `gap = next.t_first − prev.t_last` is
small (≤600s), and specifically in the 280–320s idle-close signature band.

**RESULT:** 107 consecutive same-camera pairs with gap ≤600s; **median gap 290s**; 65 pairs
≤350s; 23 pairs in 250–350s; only **8 pairs in the tight 280–320s** idle-close band
(`master_hallway 2, playroom, staircase, hot_tub, back_yard, front_side_ptz, pool_equipment`).

**Interpretation:** Fragmentation IS present but modest at the scale that matters. The 8
tight-band pairs are the clearest "one dwell split by the 300s idle-close" candidates; the
broader 107 are inflated by genuinely-busy cameras (`front_side_ptz` alone = 40 of them)
re-firing on separate people. **Consequence: Q1 durations are a LOWER BOUND on real dwell.**
Any threshold set from the persisted `duration_s` will UNDERSTATE true continuous presence for
the fragmented cases, so a threshold chosen near 300s is doubly fragile — it sits exactly at
the fragmentation seam. A dwell predicate would need to reason over *stitched* consecutive
tracks, not the raw `duration_s`, to be correct. **CONFIDENCE: MEDIUM-HIGH** (mechanism
confirmed; magnitude bounded to ~8–65 pairs depending on band).

---

## Q5 — Severity consequence

**METHOD:** `NM_HAZARD_EXTERIOR_TRACK_SEVERITY_MAP` (`const.py:1842-1875`) is keyed by
`(label, house_state, classification)`. The episode rows do NOT persist `house_state`, so
per-track live severity cannot be reconstructed; instead the map is applied to the Q2
population's ACTUAL current classification (41 pass_by / 15 approach) across each house_state.

**RESULT — severity currently drawn by the 56-track long-dwell population:**

| house_state | pass_by (n=41) | approach (n=15) | if reclassified `circling` |
|---|---|---|---|
| away / sleep / vacation | **MEDIUM** | HIGH | **CRITICAL** |
| home_night | LOW | MEDIUM | HIGH |
| home_day | **DIGEST** | LOW | MEDIUM |

**Interpretation:** A 20-minute stationary person at a perimeter camera while the house is
`away` draws the SAME `MEDIUM` as a 5-second walk-past (both `pass_by`), and while `home_day`
draws only `DIGEST`. Reclassifying true perimeter dwells as `circling` would raise them to
CRITICAL (away) / HIGH (night) — the intended security lift. THE EXPOSURE IS REAL for the
~18 street/entry-vantage long dwells (front_side_ptz + doorbell/rear/entry). **But the same
reclassification applied blindly would raise the 19 INTERIOR-camera dwells and 12 own-backyard
dwells to CRITICAL/HIGH pages — residents inside the house and in the hot tub.**
**CONFIDENCE: HIGH** on the map arithmetic; the per-state distribution of the population is
unknown (no persisted house_state) — MEDIUM on real-world page counts.

---

## Recommendation — is a dwell predicate worth building, and at what threshold?

**Do NOT build a raw duration→circling dwell predicate now. The data cannot separate a real
loiterer from a resident, and a naive predicate would convert quiet DIGESTs into CRITICAL
pages on the household's own members.** Specifically:

1. **The false-positive floor is unacceptable with today's inputs.** 34% (19/56) of the
   newly-caught population are INTERIOR cameras (residents inside), and most of the perimeter
   remainder is the OWN backyard/hot-tub. Face identification — the ONE signal that would gate
   "stranger vs resident" — is dead (2/623 identified). A predicate firing here pages the
   operator CRITICAL when a resident sits in the family room or the hot tub. Per the card's
   own false-positive-cost test, **the data cannot separate a parked gardener/resident from a
   prowler, so the honest recommendation is: don't build the alerting predicate until it can.**

2. **The genuine signal is small and already partly covered.** The real security-relevant
   population is ~18 street/entry-vantage long dwells over 11 days (≈1.6/day), and `circling`
   ALREADY captures 71 of the 133 person tracks >300s topologically. The marginal catch of a
   duration predicate is modest, and it is bought at the price of the interior/backyard
   false-positive flood — a bad margin trade (marginal-benefit-pushback).

3. **`duration_s` is not a trustworthy threshold input yet (Q4).** Real dwells fragment at the
   300s idle-close seam, so persisted durations understate truth AND any threshold near 300s
   sits on the fragmentation boundary. A correct predicate must stitch consecutive same-camera
   tracks first.

**If pursued anyway, the prerequisites (build these FIRST, not the predicate):**
- **Camera-role gating:** partition the linker's camera set into INTERIOR / OWN-YARD / PERIMETER-APPROACH.
  A dwell predicate may only escalate on PERIMETER-APPROACH cameras (front_side_ptz, doorbell,
  rear/entry). This alone removes the 19 interior + 12 backyard false positives.
- **Revive exterior face-ID or a resident-allowlist** so a dwelling resident/known gardener can
  be excluded. Without a resident-vs-stranger signal, no duration threshold is safe.
- **Track stitching** across the 300s idle-close before measuring dwell (Q4).

**Threshold the data would support (ONLY after the above):** on PERIMETER-APPROACH cameras,
a stitched continuous-presence **≥ 600 s (10 min)** is the defensible line — p90 of legitimate
`pass_by`/`approach` at those cameras is ~300–450s, so 600s clears the normal-traffic
distribution with margin while still catching the 15 >600s and 4 >1200s cases. A 300s
threshold is too close to both the legitimate p90 AND the fragmentation seam and would false-fire.

**Bottom line:** the blindness is real and the fix direction is right, but the missing
ingredient is not a duration predicate — it is **camera-role gating + a resident/stranger
signal**. Build those; the dwell threshold is a trivial follow-on once they exist. Ship nothing
that pages on `duration_s` alone.
