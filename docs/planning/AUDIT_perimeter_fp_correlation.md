# AUDIT — Perimeter person-alert false-positive correlation (PERIM-FP-1 probe)

**Date:** 2026-08-12. **Type:** read-only measure-before-build probe (no code changes).
**Data sources:** HA recorder `/config/home-assistant_v2.db` (mode=ro&immutable=1, verified fresh to 12:46Z today), URA DB `notification_log` (same mode, max ts 12:46Z), `.storage/core.entity_registry` + `core.config_entries` via Samba mount.
**Window:** 7 days ending 2026-08-12 ~12:45Z. All times UTC unless marked CDT (CDT = UTC−5).

## Sensor inventory (entity registry)

Configured perimeter cameras (integration entry `perimeter_cameras`, 9): reolinkstudybporchptz, rear_ptz, utilities_ptz, front_side_ptz, armcrest, hot_tub, pool_equipment, g5_bullet, back_yard.

Per camera, up to three person sensors exist:
- `binary_sensor.<cam>_person_occupancy` — **frigate** (instance 1)
- `binary_sensor.<cam>_person_occupancy_2` — **frigate** (instance 2; dual-instance install, see frigate MQTT topic-collision memo)
- `binary_sensor.<cam>_person_detected` — **unifiprotect** smart-detect

7 of 9 cameras have both a Frigate and a Protect person sensor. **armcrest and reolinkstudybporchptz have NO Protect sensor** (Frigate-only views).

## Q1 — Last night's 23:05 CDT (04:05Z) CRITICAL

- Alerting entity: `binary_sensor.front_side_ptz_person_occupancy` → platform **frigate** (instance 1), NOT UniFi Protect. Registry confirms; the Protect sibling for the same camera is `binary_sensor.front_side_ptz_person_detected`.
- Recorder: the sensor went `on` at **04:05:00.387Z and back `off` within the same second** (sub-1s blip).
- Corroboration scan ±300 s across ALL 25 perimeter person sensors: **zero** other edges. The Protect sensor on the *same camera view* did not fire; frigate instance 2 on the same view did not fire; no other camera fired. Camera was in IR/dark mode (`binary_sensor.front_side_ptz_is_dark` = on since ~04:14Z Aug 11, i.e. all night).
- Same pattern for every other front_side alert last night — all single-witness, sub-2s frigate-1 blips:
  04:45:51 (~1 s), 05:50:04 (~2 s), 06:52:52 (~1 s), 09:06:38 (<1 s).
- The earlier photo-bearing alerts the operator saw (per notification_log, all of last night's alerts carried forced snapshots — see Q4) match the same signature. One nuance: at **06:02** pool_equipment (06:02:19) and front_side (06:02:20) blipped within 1.5 s of each other — nominally "corroborated," but both were sub-3 s frigate-1 blips on different views, far more consistent with a shared Frigate-side artifact than a person traversing two non-adjacent views in one second.

## Q2 — 7-day single-witness table

Rising edges to `on`; **single-witness** = no edge from any other camera OR any other source on the same camera within ±120 s. 2,386 edges total.

| camera | source | edges | single-witness | SW rate |
|---|---|---:|---:|---:|
| pool_equipment | frigate1 | 82 | 77 | **94%** |
| hot_tub | frigate1 | 53 | 32 | **60%** |
| front_side_ptz | frigate1 | 697 | 358 | **51%** |
| back_yard | frigate1 | 649 | 321 | **49%** |
| back_yard | frigate2 | 213 | 75 | 35% |
| front_side_ptz | frigate2 | 91 | 13 | 14% |
| rear_ptz | protect | 83 | 11 | 13% |
| reolinkstudybporchptz | frigate1 | 17 | 2 | 12% |
| utilities_ptz | frigate2 | 21 | 2 | 10% |
| hot_tub | frigate2 | 18 | 1 | 6% |
| armcrest | frigate1 | 18 | 1 | 6% |
| g5_bullet | frigate1 | 55 | 3 | 5% |
| utilities_ptz | frigate1 | 28 | 1 | 4% |
| armcrest | frigate2 | 37 | 1 | 3% |
| g5_bullet | protect | 66 | 1 | 2% |
| rear_ptz | frigate1 | 55 | 1 | 2% |
| all remaining protect + frigate2 rows | | | | 0% |

**Alert-hours cut (23:00–05:00 CDT = 04–10Z, 7 nights):** 80 person edges total, **100% from frigate instance 1**, on exactly four cameras — pool_equipment (30), front_side_ptz (26), hot_tub (23), armcrest (1). **Zero Protect person detections and zero frigate-2 detections during alert hours all week.** Every nighttime perimeter alert this week was frigate-1-only.

**On-duration signature (frigate1, 7d):** pool_equipment median 2.5 s (45% sub-2s), hot_tub median 1.7 s (58% sub-2s), front_side median 14.9 s (17% sub-2s) vs healthy cams — rear_ptz 27 s, g5_bullet 20 s, utilities 23 s, armcrest 47 s, all **0–4% sub-2s**. FP blips are morphologically distinct.

## Q3 — Frigate vs Protect delta (same-view cameras, ±120 s, 7d)

frigate = instance1+instance2 edges combined.

| camera | frigate edges | protect edges | agree | frigate-only | protect-only |
|---|---:|---:|---:|---:|---:|
| back_yard | 862 | 17 | 48 | 814 | 0 |
| front_side_ptz | 788 | 14 | 34 | 754 | 0 |
| pool_equipment | 88 | 10 | 9 | 79 | 4 |
| hot_tub | 71 | 17 | 25 | 46 | 1 |
| rear_ptz | 107 | 83 | 98 | 9 | 17 |
| g5_bullet | 105 | 66 | 98 | 7 | 9 |
| utilities_ptz | 49 | 20 | 37 | 12 | 2 |
| armcrest | 55 | 0 | — | 55 | — (no Protect sensor) |
| reolinkstudybporchptz | 34 | 0 | — | 34 | — (no Protect sensor) |

Where cameras are healthy (rear_ptz, g5_bullet, utilities_ptz) the two engines agree ~75–95% of the time. On the suspect cameras Frigate fires **50–60× more often than Protect** and Protect confirms almost nothing. Protect-only firings are rare everywhere (Protect misses little that matters, or Frigate over-covers — either way Protect is the conservative witness).

## Q4 — Repeat-alert snapshot behavior (URA notification_log, last night)

8 alert events 04:05Z–09:12Z, each fanned to 4 channels (pushover, companion, whatsapp, imessage) + one `[audit]` row. **Every audit row last night carried `route_reason=force_immediate_security_image`** — i.e. all 8 were snapshot-forced; there were **no text-only rows** last night. (Aug 11's five events instead show `route_reason=legacy_fallback`.)

| event (UTC) | camera | gap from previous same-camera alert |
|---|---|---|
| 04:05:02 | front_side | — |
| 04:45:53 | front_side | 40.8 min |
| 05:50:06 | front_side | 64.2 min |
| 06:02:21 | pool_equipment | — |
| 06:52:55 | front_side | 62.8 min |
| 08:01:44 | pool_equipment | 119.4 min |
| 09:06:41 | front_side | 133.8 min |
| 09:12:19 | pool_equipment | 70.6 min (detection 08:56, delivered 09:12) |

Each alert corresponds to a **fresh recorder rising edge** at the stated detection time — these are NOT cooldown-spaced repeats of one stuck detection (`PERIMETER_ALERT_COOLDOWN_SECONDS = 300` at const.py:1372; gaps are 40–134 min). The "text-only repeat = no fresh rising edge" calibration question is therefore moot for last night: every delivered alert had its own edge and its own snapshot. Side observation: two additional front_side edges (06:14:29, 07:11:18) produced **no** alert rows — presumably NM dedup/bucketing; worth a one-line confirmation in any follow-up cycle.

## Verdict

**Operator hypothesis SUPPORTED, with a sharper attribution.** Uncorroborated-single-witness ≈ FP holds strongly: during alert hours all week, every person edge came from **Frigate instance 1 only**, was typically a **sub-2-second blip**, on an **IR/dark** camera, with the UniFi Protect smart-detect on the *identical view* silent — while on healthy daytime cameras the two engines agree 75–95%.

**Ghost source:** Frigate instance-1 person detection on four cameras — **pool_equipment (94% single-witness), hot_tub (60%), front_side_ptz (51%), back_yard (49%)** — dominated by nighttime IR frames. front_side_ptz and pool_equipment alone produced all 13 of the last two nights' CRITICAL alerts. This is Frigate model noise under IR (possibly aggravated by the known dual-instance MQTT topic-collision bleed for the `_2`/`_1` split — see memo "frigate mqtt collision"), not URA logic: URA alerted exactly per spec on the edges it was given.

**Cheapest fix candidates surfaced by the data (for the planning doc, not built here):**
1. **Corroboration or min-duration gate** on the perimeter-alert path — the FP population is 45–58% sub-2s while true detections are 20–47 s median; even a ~3–5 s sustained-on requirement or a same-view Protect corroboration check (Protect had 0% nighttime firings = would have suppressed all of last night's alerts) kills the class.
2. **Frigate-side tuning** (min_score/threshold for `person` on the four cameras' night profile) — upstream of URA.
3. Note the two Frigate-only cameras (armcrest, reolinkstudybporchptz) can never be Protect-corroborated; any corroboration gate needs a per-camera fallback (duration gate).
