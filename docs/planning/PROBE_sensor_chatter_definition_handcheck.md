# PROBE — Sensor-Chatter Definition Hand-Check (STEP D0 gate)

**Type:** Read-only measure-before-build probe. No code built. No files
modified other than this doc.
**Date:** 2026-08-18
**Author:** Oji Udezue
**Doctrine:** "Measure Before You Build" (CLAUDE.md) — the definition a
build will depend on is hand-checked against real recorder history +
the known incident BEFORE any build is scoped against it.

## Definition under test

> A sensor is *chattering* iff it emits a transition whose interval since
> the prior transition is BELOW that sensor's physical minimum floor
> `T_floor` (an **impossibility event** — not merely "fast"). Raw rate and
> %-change never trigger.

Two things had to be empirically confirmed:
- **(a) Catches real chatter:** genuine chatter incidents DO produce
  sub-`T_floor` events.
- **(b) Zero false-positives on healthy sensors** — the operator's hard
  constraint.

## Data path used

Direct read-only SQLite over the **live HA recorder** on the HAOS host via
`ssh ha 'python3 -' < probe.py`, opened `mode=ro` (respects WAL → a
consistent read).

- **Rejected path:** opening the Samba-mounted DB copy with `immutable=1`
  from the Mac returned `database disk image is malformed` — `immutable`
  ignores the live WAL and reads torn pages while HA writes. The ssh path
  is the correct one (the recorder's own filesystem, WAL honored).
- **Candidate set:** all `binary_sensor.*` whose entity_id contains
  `motion` / `presence` / `occupancy` = **417 entities** (motion ∪ presence
  ∪ occupancy). 286 had ≥1 real on↔off transition interval in the window.
- **Method:** per sensor, pulled all `states` rows ordered by
  `last_updated_ts`, kept only real `on`↔`off` transitions (dropped
  `unavailable`/`unknown`, which reset the interval so we never span a
  dropout), computed inter-transition interval distribution (min, p1, p5,
  p50) and a sub-floor histogram (`<0.5 / 0.5-1 / 1-2 / 2-5 / 5-10 / 10-30`s).

## ⚠️ Retention limit — the 2026-08-09 incident is PURGED

The recorder holds **only ~7 days**: earliest `states` row is
**2026-08-11 09:12**, and the incident entity
`binary_sensor.ratgdov25i_dbfe2a_motion` (verified: exists,
`metadata_id=5414`, the ratgdo v2.5i Garage-B opener PIR) has data
**2026-08-11 23:01 → 2026-08-18 21:20 only**. No older recorder DB exists
(only `zigbee.db`, unrelated).

**Consequence:** the 2026-08-09 Garage-B window cannot be observed
directly. What we CAN observe is that the SAME sensor is **still emitting
a pathological transition volume today** — that ongoing behavior is used
as the incident proxy (see below), and it is strong. But "the definition
catches the 08-09 events" is **INFERRED from the ongoing signature, not
directly confirmed against the incident timestamps.**

## Finding 1 — sub-floor events are WIDESPREAD, not rare

Of 286 active sensors, **153 show ≥1 sub-0.5s interval.** This immediately
breaks a naive "one impossibility event ⇒ chatter" rule.

| class | # sensors | # with ≥1 sub-0.5s | # with ≥20 sub-0.5s | total sub-0.5s events |
|---|--:|--:|--:|--:|
| camera / AI-software detections | 154 | 98 | 36 | 16,896 |
| physical PIR / mmWave / opener | 119 | 43 | 6 | 1,751 |
| bed multi-state (`bed_occupied_*`) | 13 | 12 | 0 | 75 |

**Camera / AI detections have NO physical floor.** A Frigate/Protect/
Amcrest person/motion binary_sensor is a *software* inference that can and
does toggle in sub-frame time. `binary_sensor.binarygroup_camera_motion_zone1`
alone logged **14,216 sub-0.5s intervals** and is working exactly as
designed. Applying ANY `T_floor > 0` to this class manufactures thousands
of false positives.

→ **The definition is only meaningful for sensors with a real hardware
blind-time.** Camera/AI, group/aggregate (`*_occupancy_status`,
`*_occupancy_anomaly`), and the multi-state bed sensors MUST be excluded
from chatter detection (they belong to the *other* detectors in the
sensor-trust program, or to the shared exclusion primitive — not to the
`T_floor` chatter client).

## Finding 2 — even healthy PHYSICAL sensors emit isolated sub-floor events

Among the 119 physical PIR/mmWave/opener sensors:
- **76 have ZERO sub-0.5s events** (clean).
- **30 have 1-4** isolated sub-0.5s events over 7 days.
- **Only 6 have ≥20.**

The 1-4 isolated events on otherwise-clean sensors (e.g.
`master_bathroom_motion`=3, `family_room_motion`=4, `garage_a_motion`=2)
are almost certainly transport/recorder artifacts — MQTT double-publish,
restart-adjacent double-fire, an `unavailable`-flanked flap — **not device
chatter.** A single impossibility event is therefore **not diagnostic**;
the operator's zero-false-positive constraint FAILS under a
single-event rule.

→ **A burst / rate requirement is mandatory:** trigger on **K sub-floor
events within a window**, not one. The data separates cleanly: healthy
physical sensors sit at ≤4-5 isolated events / 7 days; the two live
pathological sensors sit at 150-820 (see Finding 3). A threshold anywhere
in that gap (e.g. ≥N sub-floor events within a rolling few-minute window,
tuned so a healthy sensor's lifetime count can't reach it) satisfies both
(a) and (b).

## Finding 3 — the incident sensor (and a second live suspect)

### `binary_sensor.ratgdov25i_dbfe2a_motion` (Garage-B opener PIR)

| metric | value |
|---|--:|
| transitions in 7 days | **58,713** (~8,400/day, ~1 every 10s avg) |
| min interval | 0.0 s |
| p1 | 1.279 s |
| p5 | 1.971 s |
| **p50 (median)** | **2.988 s** |
| sub-0.5s events | 154 (0.26% of transitions) |
| histogram `<.5/.5-1/1-2/2-5/5-10/10-30`s | 154 / 222 / 7,522 / 44,058 / 2,197 / 3,077 |

**This is unambiguously pathological** — a motion PIR does not legitimately
transition 58,713 times in a week with a **3-second median**. BUT the
pathology is a **sustained ~2-5s re-fire cadence**, not a sub-second burst:
only 154 of 58,713 transitions are sub-0.5s.

**This is the pivotal result for the definition.** Whether the definition
CATCHES this depends entirely on where `T_floor` sits:
- `T_floor = 0.5s` → catches 154/58,713 → **misses the incident** (calls a
  58k-transition/week storm "healthy").
- `T_floor ≈ 3s` (a realistic PIR blind/retrigger time) → **half** of all
  transitions become impossibility events → **catches it decisively.**

So the definition is sound for this incident **only if `T_floor` is set to
the device's true physical blind-time (seconds), not a hard-coded 0.5s.**

### ⚠️ `T_floor` must NOT be learned from the sensor's own history

`ratgdo`'s own learned `p1=1.28s / p5=1.97s` would set a floor that
declares its own chatter healthy — a circular trap. **Learned percentiles
are valid only for KNOWN-HEALTHY sensors.** For a sensor that may already
be chattering, `T_floor` must come from the device's documented/configured
blind-time (ESPHome `off_delay` / PIR retrigger spec), not its recorder
percentiles.

### Second live suspect — `binary_sensor.invisoutlet_b7d0_motion` / `_occupancy`

Surfaced by the same scan: **62,245** and **49,874** transitions in 7 days,
820 and 568 sub-0.5s events respectively — a second sensor exhibiting the
same storm class, currently live. Worth an independent look; not part of
the 08-09 incident but validates that the storm signature recurs.

## `T_floor` ladder the data supports (per device family)

Empirical fastest-healthy-refire (p1/p5 of clean sensors) as an
**upper-bound sanity check** on a datasheet-sourced floor — NOT as the
floor itself:

| device family (example entities) | learned p1 (healthy) | learned p5 | suggested `T_floor` source |
|---|--:|--:|---|
| Zigbee occupancy (`occupancy_lux_temp_humidity_hobeian_*`) | ~1.5 s | ~1.7-2.4 s | Zigbee reporting cadence / off-delay |
| ESPHome/Matter PIR (`rgbw_motion_lux_*`) | ~0.8-1.8 s | ~4-20 s | ESPHome `off_delay` config |
| mmWave (`mmwave_*`, `screek_*`, `switch_mmwave_inovelli_*`, `athom_*`) | ~0.4-3.3 s | ~1-9 s | device presence-timeout |
| Opener PIR (`ratgdo*`, `garageopener_gdoblaq_*`) | 1.3 s | 1.9-2.0 s | **datasheet blind-time (NOT learned — chatter-contaminated)** |

These land in the **1-3 s** band. A per-family default floor in that band,
overridable per device from its configured off-delay, is what the data
supports. A single global 0.5s floor does NOT (it misses the ratgdo storm).

## GO / NO-GO

**Definition AS LITERALLY STATED ("a sensor chatters iff it emits A
sub-`T_floor` transition"): NO-GO.** It fails BOTH halves of the test:
1. It does **not reliably catch the real incident** at a small `T_floor` —
   the ratgdo storm is a sustained 2-5s cadence, only 0.26% sub-0.5s. It is
   caught only if `T_floor` is set to the device's true multi-second
   blind-time.
2. It **does not deliver zero false-positives** — 153/286 sensors emit
   sub-floor events, including 30 healthy physical sensors with 1-4
   isolated artifacts. A single event is not diagnostic.

**Definition WITH THREE AMENDMENTS: GO (buildable, and it then catches the
incident with zero healthy false-positives on this dataset):**

1. **Provenance gate (reuse the shared exclusion primitive).** Apply the
   `T_floor` chatter client ONLY to sensors with a real hardware
   blind-time (PIR / mmWave / opener / reed). **Exclude** camera/AI
   detections (154 sensors), group/aggregate sensors, and the bed
   multi-state family. Without this, the definition is unusable.
2. **`T_floor` from device blind-time, never learned from the target
   sensor's own history** (circular). Learned percentiles are an
   upper-bound cross-check for KNOWN-healthy sensors only. Per-family
   defaults sit in the 1-3 s band.
3. **Burst requirement, not single-event.** Trigger on ≥K sub-floor events
   within a rolling window; the healthy-vs-pathological gap (≤4-5 vs
   150-820 events / 7 days) is wide enough to place K with margin.

With (1)+(2)+(3): the ratgdo incident is caught (median 3s ≪ its true PIR
blind-time ⇒ a sustained sub-floor burst), and every healthy sensor in the
7-day dataset stays below threshold → **operator's zero-false-positive
constraint met on the observed data.**

## Caveats / residual risk

- **Incident not directly observed** (08-09 purged; recorder = 7-day
  retention). Verdict on catching it is inferred from the sensor's ongoing
  identical-class storm, which is strong but not the incident timestamps.
- `T_floor` correctness is now the load-bearing input. Because it must be
  device-sourced (not learned for suspect sensors), the build needs a
  per-device blind-time table (ESPHome off-delay / datasheet) — a manual
  fixture to hand-build BEFORE automating (measure-before-build corollary).
- The burst threshold K and window are the second calibration knob; both
  belong on the knob ladder (module constant if review-gated, or a Number
  entity if operator-tunable).

## Acceptance fixture emitted for the build

- **Positive:** `binary_sensor.ratgdov25i_dbfe2a_motion` — 58,713
  transitions/7d, p50=2.988s → MUST be flagged chatter once `T_floor` ≥ its
  device blind-time. Second positive: `invisoutlet_b7d0_motion` (62,245/7d).
- **Negatives (MUST stay healthy):** the 76 physical sensors with zero
  sub-floor events, PLUS the 30 physical sensors with 1-4 isolated
  sub-floor artifacts (these are the false-positive trap the burst rule
  must survive), e.g. `master_bathroom_motion` (3), `family_room_motion`
  (4), `garage_a_motion` (2).
- **Must-exclude (out of scope for this detector):** all 154 camera/AI
  sensors — e.g. `binarygroup_camera_motion_zone1` (14,216 sub-0.5s, working
  as designed) is the canonical "would-be false positive if not excluded."
