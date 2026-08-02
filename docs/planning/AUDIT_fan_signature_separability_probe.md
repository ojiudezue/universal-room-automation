# AUDIT — Fan-Signature Separability Probe (mmWave phantom vs human)

**Date:** 2026-08-01 · **Type:** read-only measurement probe (Measure Before You Build)
**Question:** can fan-induced mmWave phantom activity be separated from human occupancy using only signals the sensors already emit?
**Scripts:** `docs/planning/scripts/fan_signature_probe.py`, `fan_signature_probe_part2.py` (run via `ssh ha "python3 -" < script`)
**Data:** HA recorder DB (mode=ro; span 2026-07-25T15:52Z → 2026-08-01T23:00Z) + URA DB `occupancy_events` (mode=ro) + `.storage/core.entity_registry` (Samba mount).

## Headline findings

1. **The phantoms are transition-triggered, not steady-state-triggered.** Study A's phantom onset (07-31 20:41:16Z) is the *exact second* of a fan speed transition 33%→55% (→100% at 20:42); it cleared 33 s after fan-off (21:12:39 → sensor off 21:13:12). The fan running *steadily* at 33% for the preceding 20 h, and steadily at 100% for 4 h on 08-01, produced **zero** presence edges. Jaya Bedroom independently confirms: an `mmwave`-triggered occupancy entry at 07-26 03:24:13Z, the exact second the ceiling fan turned on (03:24:14, automated, house departing); exit ~9 min after the fan's last off (11:40 → 11:49).
2. **The incident unit (Study A) emits nothing separable on its own.** It is a Tuya-class Zigbee unit (`mqtt`) exposing only a binary presence signal + tuning numbers — no energy channels. Its phantom was one sustained 32-min ON: no re-trigger cadence, no numeric texture. Edge-cadence separation is a dead end for this hardware.
3. **Where LD2410 energy channels exist (ESPHome units), still_energy separates phantom from human clearly** (tables below), and the fan-event cross-signal separates them everywhere with zero new hardware.

## (a) Sensor inventory — who exposes what

| Unit (room) | Platform | Numeric channels | Observed recorder cadence |
|---|---|---|---|
| `binary_sensor.mmwave_zigbee_studya_presence` (Study A — **incident unit**) | mqtt (Zigbee) | **none** (only `number.*_detection_distance/_fading_time/_sensitivity`, battery, linkquality) | binary edges only |
| `sensor.jaya_3_*` (Jaya Bedroom) | esphome LD2410 | move/still energy (+g0–g8 per-gate), detection_distance, binary presence/moving/still target | **~1.1 s while active**, silent when idle (delta-filtered) |
| `sensor.mmwave_lux_wifi_esphome_studyb_*` (Study B) | esphome LD2410 | same full set | ~1–10 s while active, silent idle |
| `sensor.mmwave_lux_wifi_esphome_kitchen_*` (Kitchen) | esphome LD2410 | same full set | ~1–8 s while active |
| `sensor.ziri_3_*` (Ziri Bedroom) | esphome LD2410 | same full set | near-silent all week (room dark) |
| `sensor.screek_human_sensor_l13_{2412s,b38b24}_*` | esphome | move/still energy | not room-mapped in this probe |
| `sensor.hlk_ld2410_{07cb,3616,aff4,bdbc}_{still_energy,detection_distance}` | ld2410 / ld2410_ble | **disabled** (`disabled_by: integration`) | no data |
| Zigbee mmWave siblings (masterbedroom, gameroom, mediaroom, jayabedroom, ziribedroom `mmwave_zigbee_*`) | mqtt | none | binary edges only |

Key cadence fact: the ESPHome energy sensors are **event-driven** (report on change). Recorder sample rate is therefore itself a signal: ~600–2 300 samples/hr when *anything* (fan or human) is in view, ~0–2/hr when the room is truly empty. It separates empty vs non-empty, **not** fan vs human.

## Ground truth used

- Fan transitions (recorder): Study A Dreo on 07-31 00:31–21:12 (33%→speed steps at 20:41), on 08-01 13:05–17:07 @100%; matches the incident labels to the minute.
- URA `occupancy_events` (Study A): last human-plausible entries 07-25/26 evening; then only the 07-31 20:41:17 phantom entry. House away 07-26 → 08-01 confirmed by event silence across all five probed rooms.
- Jaya OCCUPIED window 07-25 16:00–22:40Z: continuous mmwave/ble entry/exit churn (people home, pre-departure).
- Jaya PHANTOM window 07-26 04:00–09:30Z: fan on, house departing/departed, entry trigger simultaneous with automated fan-on ⇒ no human.

## (b) Per-class feature tables

### Numeric energy — `jaya_3` (LD2410), the only fan+energy co-located labeled pair

| Feature | PHANTOM (fan-on, vacant) | OCCUPIED (evening) | EMPTY (fan-off) |
|---|---|---|---|
| still_energy mean ± sd | **39.7 ± 7.9** (CV 0.20) | **71.9 ± 24.4** (CV 0.34) | no samples (silence) |
| still_energy p10/50/90 | 33 / 39 / 47 (tight band) | 32 / 79 / 99 (wide) | — |
| still_energy autocorr @60 s | **0.86** (sticky, slow-drifting) | **0.16** (fast-decorrelating) | — |
| move_energy mean ± sd | 35.9 ± 30.0, p90=85 | 16.8 ± 17.1, p90=32 | — |
| move_energy autocorr @60 s | 0.67 | 0.36 | — |
| detection_distance | pinned 30–40 (CV 0.16) | 23–49 (CV 0.25) | — |
| sample rate (still) | 2 302/hr | 1 930/hr | ~0–2/hr |
| periodogram 0.02–0.45 Hz | peak 0.03–0.05 Hz, SNR 5–7 (weak, no clean oscillation line) | peak 0.025–0.03 Hz, SNR 9–11 | — |
| `fan.oscillating` attr | False throughout (both Dreo + ceiling fans; never oscillated all week) | False | — |

Study B / Kitchen occupied-window stats (07-25) are consistent in shape (occupied still_energy mean 64–67, sd 33–37); no fan-on-vacant window exists for those rooms this week.

### Binary edge cadence — per class

| Unit | PHANTOM | OCCUPIED | EMPTY |
|---|---|---|---|
| `mmwave_zigbee_studya_presence` (incident) | **0 internal edges** — one sustained 32-min ON | 11 edges/12 h; on-dwell med 85 s; inter-onset med ~19 min, CV 1.15 | 0 edges |
| `jaya_3_presence` (LD2410 fused) | 10 | 65 | 0 |
| `jaya_3_moving_target` | 2 251 | 3 037 | 0 |
| `mmwave_zigbee_jayabedroom_presence` (Zigbee sibling) | 63 (flapping under fan) | 3 | 0 |

Zigbee-unit behavior is **unit-inconsistent**: Study A latched one long ON; Jaya's flapped. No robust cadence signature.

### Cross-signal — fan events vs mmWave onsets

| Event | Fan event | mmWave onset/offset | Δt |
|---|---|---|---|
| Study A phantom onset | speed 33→55% @ 20:41:17 | ON @ 20:41:16 | ≤1 s |
| Study A phantom clear | OFF @ 21:12:39 | off @ 21:13:12 | 33 s |
| Jaya phantom onset | ON @ 03:24:14 | mmwave entry @ 03:24:13 | ≤1 s |
| Jaya phantom clear | last OFF @ 11:40:14 | exit @ 11:49:00 | ~9 min (fade timer) |
| Non-events | steady 33% × 20 h; steady 100% × 4 h | no onset | — |

Bonus observation (unexplained, low-stakes): the Study A Zigbee sensor blipped `unavailable` within ~2 s of both Dreo WiFi power-on commands (07-31 00:29/00:31, 08-01 13:05:21 vs fan 13:05:19) — plausibly 2.4 GHz contention; it also blips unavailable several times daily on its own, so not load-bearing.

## (c) Separability verdict per feature

| Feature | Verdict | Notes |
|---|---|---|
| still_energy distribution (LD2410 units) | **Clearly separable** | Phantom = tight low band (33–47, CV 0.20) with high 60 s autocorr (0.86); human = high/wide (median 79, CV 0.34) fast-decorrelating (0.16). Both center and texture separate. |
| move_energy distribution | Marginal | Phantom actually *higher* (fan blades); overlapping tails. Usable as a secondary feature only. |
| detection_distance variance | Marginal | Phantom pinned at fixed reflector distance; human roams. Weak alone. |
| Sample-rate / chatter (event-driven recording) | Separable for empty-vs-non-empty only | Cannot tell fan from human. |
| Periodogram 0.05–0.5 Hz oscillation line | **No signal** | Fans never oscillated (attr False all week); no clean spectral peak; event-driven irregular sampling makes spectral estimates unreliable anyway. Honest null. |
| Binary edge cadence (Zigbee incident units) | **Not separable** | Study A phantom = one sustained ON (zero cadence); sibling unit behavior inconsistent. |
| Fan power/speed **transition** coincidence | **Clearly separable** | All observed phantom onsets within ≤1–2 s of a fan power/speed transition; clears within fade-time of fan-off; steady-state fan never triggered. Works for every room, no new hardware. |

## (d) GO/NO-GO

**GO — two-pronged, minimal feature set:**

1. **Fan-transition coincidence gate (all rooms, primary).** When a room's occupancy onset is mmWave-only (no motion/BLE/camera corroboration) and falls within a small window (~±5 s, tunable per Numbers-Get-Knobs) of a power/speed transition on that room's registered fan entity, tag the onset as fan-suspect and route it to the existing recheck machinery instead of granting occupancy; likewise treat mmWave-only occupancy that clears within fade-time of fan-off as retroactive confirmation of phantom. Prior art to build on, not duplicate: `presence_fan_recheck.py` + `fan_recheck_state` table already exist (fan-interference recheck ladder) — this adds an *onset-time* discriminator to a machinery that today only rechecks later.
2. **still_energy band feature (LD2410-equipped rooms only, corroborator).** Feature = (rolling median in the 30–50 band) AND (60 s autocorrelation high / low sd) ⇒ fan-like; median >~60 with wide spread ⇒ human-like. Thresholds must be learned per unit (single-unit fit here).

Explicitly **not** worth building: edge-cadence classifiers (null result), spectral/oscillation detection (null result), anything requiring the Zigbee units to characterize their own phantom (they emit no usable texture).

**Caveats bounding confidence:** exactly two labeled phantom events, one week, one energy-instrumented phantom (Jaya, ceiling fan — not the Dreo tower); one occupied evening per room; still_energy thresholds are single-unit, single-furniture-configuration fits. The transition-coincidence result is the strongest (two independent rooms, two fan types, exact-second alignment, and two multi-hour steady-state negatives).

## (e) Instrumentation that would make it decisive

- **Enable the disabled LD2410 energy entities** (all `disabled_by: integration`): `sensor.hlk_ld2410_07cb_still_energy`, `sensor.hlk_ld2410_3616_still_energy`, `sensor.hlk_ld2410_aff4_still_energy`, `sensor.hlk_ld2410_bdbc_still_energy` and matching `*_detection_distance` (`ld2410`/`ld2410_ble` platforms) — if any map to fan-equipped rooms, they add the still_energy corroborator there.
  - **2026-08-01 resolved — no enablement needed.** The four disabled entities belong to standalone *Bluetooth* LD2410 dongles (`ld2410_ble` entries, `disabled_by: user` at config-entry level — BLE-budget call, and redundant). The live corroborator population is the ESPHome/Screek fleet, streaming now: `sensor.jaya_3_still_energy`, `sensor.ziri_3_still_energy`, `sensor.mmwave_lux_wifi_esphome_{kitchen,studyb}_still_energy` (each with per-gate g0–g8 arrays), and `sensor.screek_human_sensor_l13_{2412s,b38b24}_still_energy` (living room + master, LD2412S). Six rooms have a still_energy data path today; leave the BLE dongles off.
- **Study A cannot be instrumented in software**: the Tuya Zigbee unit does not expose energy channels. Options: rely on prong 1 only, or co-locate an ESPHome LD2410 (the house already runs four).
- **One deliberate labeled run** (operator away, fan scripted through speed steps in an LD2410 room, e.g. Study B with a portable fan) would multiply the phantom sample count from 2 to N cheaply and validate the ±5 s window and still_energy band on a second unit.
- Prior art note: `sensor.bedroom_still_energy_1h_avg` (statistics platform) already exists — someone has been down the still_energy-smoothing road; reuse the pattern rather than a new helper style.

## Reproduction

```bash
ssh ha "python3 -" < docs/planning/scripts/fan_signature_probe.py
ssh ha "python3 -" < docs/planning/scripts/fan_signature_probe_part2.py
```
Both scripts open both DBs with `mode=ro` URIs; no writes, no config changes were made anywhere during this probe.
