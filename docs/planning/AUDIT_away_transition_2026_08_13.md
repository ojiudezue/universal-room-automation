# AUDIT — Missed home_day → away transition, 2026-08-13 (~11:30–15:51 CT)

**Status:** Diagnosis of record. READ-ONLY incident audit — no fixes applied.
**Evidence:** HA recorder (`/config/home-assistant_v2.db`, mode=ro) + URA DB
(`house_state_log`, `notification_log`) + source trace on develop @ a7ff3574.
All timestamps below are **UTC (Z)**; CT = UTC−5.

## Verdict in one paragraph

The house never received a trustworthy "everyone is away" signal, and the one
fallback path that tolerates untrustworthy trackers was — by design — vetoed by
indoor occupancy. That indoor occupancy was a single phantom: the Living Room
Screek mmWave, pinned ON by the room's own comfort fan, which URA's fan policy
kept running *because the room read occupied* (a closed loop). Every shipped
mechanism that should have broken the loop was individually, deliberately
disabled for exactly this room: the mmWave-fan sustain demotion fails closed on
rooms with no PIR (`motion_sensors: []`), the continuous-stuck rule needs 4 h
(the hold was 2 h 01 m), and the duty-cycle rule is NOTIFY-ONLY by design.
When the operator killed the fans at 20:46Z, the mmWave released in **37
seconds** and the house went `away` 4½ minutes later — the fan was the occupant.

## (a) Incident timeline

| UTC | CT | Event | Evidence |
|---|---|---|---|
| 13:30:14 | 08:30 | `binary_sensor.guest_bedroom_1_occupied` ON (on/off all midday) | recorder |
| 14:37:49 | 09:37 | house `guest → home_day` (guest room cleared 14:32:49 + exit clear) | house_state_log |
| 16:43:02–:09 | 11:43 | `person.oji_udezue` and `person.ezinne` → not_home. **Census stays 2** — Jaya/Ziri trackers stale-home for another ~2.7 h | recorder |
| 15:53:53 | 10:53 | Guest Bedroom 1 occupied ON again | recorder |
| 16:23:59 | 11:23 | `home_day → guest`, trigger `guest_room_occupancy` — Path B 30-min threshold: 15:53:53 + 30:06 | house_state_log |
| 16:30:59 | 11:30 | `guest → home_day` (guest room off 16:25:59) | house_state_log |
| 18:40:08 | 13:40 | Living Room Screek presence ON (`binary_sensor.living_room_presence`); `living_room_occupied` ON 18:40:10 | recorder |
| 18:45:02 | 13:45 | `fan.towerfan_dreopilotmaxs_wifi_livingroom` ON; Screek re-latches ON 18:45:08 and **holds continuously 2 h 01 m** | recorder |
| 19:15:43 | 14:15 | `binary_sensor.living_room_fan_should_run` ON — comfort-fan policy sustains the fan because the room reads occupied. **Loop closed: occupancy→fan→mmWave→occupancy** | recorder |
| 19:24:17 | 14:24 | ALL FOUR persons excluded from trust: `excluded_persons = {Oji: lost, Ezinne: lost, Jaya: stale, Ziri: stale}`; `tracked_persons_count_trusted = 0`; `all_tracked_persons_away = false` (and stays false through the whole window) | house-state sensor attrs |
| 19:28–19:29 | 14:28 | Ziri → not_home; **census → 0** (19:29:17). From 19:29:47 the ONLY occupied zone is Entertainment, provenance `{mmwave: 1}`, `fan_on_rooms: ["Living Room"]`, `fan_interference_rooms: ["Living Room"]` | attrs |
| 19:29–20:46 | 14:29–15:46 | **82 minutes**: census 0, all persons away, house held `home_day` by one fan-pinned mmWave. `veto_path: "none"` on every tick | attrs |
| 20:15:03 | 15:15 | Jaya Bedroom fan ON (empty room) | recorder |
| 20:46:05–:16 | 15:46 | Operator turns off tower fan, `fan.fan_switch_4`, Jaya Bedroom fan (`context_user_id=None`, no parent context → vendor app / physical, not an HA dashboard call) | recorder |
| 20:46:42 | 15:46 | Screek presence OFF — **37 s after fan-off** | recorder |
| 20:51:06 | 15:51 | `home_day → away` conf 0.9 (trigger string `guest_room_occupancy` is just the inference-tick reason, not the cause); `living_room_occupied` OFF 20:51:40 | house_state_log |

## (b) Root-cause chain (file:line)

1. **Trust collapse emptied the away-veto denominator.** By 19:24Z all four
   person trackers were LOST/STALE → excluded → `tracked_persons_count_trusted=0`
   → `all_tracked_persons_away=False`. Path α (the v4.7.14 high-confidence AWAY
   veto, `domain_coordinators/presence.py:~1048-1057`) requires
   `all_tracked_persons_away AND unidentified_count==0 AND census_count==0`
   — it was structurally unreachable the entire window. This is the known
   "away⇒LOST empties the veto denominator" gap (v5.16.0 memory), operating as
   shipped.
2. **Path β (the LOST-tolerant veto built for exactly this) was blocked by the
   phantom zone.** `presence.py:~1093-1141`: β requires `not indoor_blocked`,
   where `indoor_blocked` = any indoor zone occupied. Entertainment was
   "occupied". This veto is intentional — invariant I1, never force AWAY while
   an indoor zone is occupied. Correct design, wrong input.
3. **The census-0 "nobody home" rule was blocked the same way.**
   `presence.py:~1026-1031`: `census_count==0 AND not any_zone_occupied`.
4. **The occupancy was fabricated by fan-on-mmWave.** Screek L13 2412S ON
   18:45:08 (6 s after fan-on) → 20:46:42 (37 s after fan-off). Sole provenance
   of the Entertainment zone from 19:29:47. Meanwhile
   `living_room_fan_should_run` kept the fan running because the room read
   occupied — a self-sustaining loop.
5. **Every breaker for that loop was disabled for this specific room** — see (c).

## (c) Which shipped mechanisms should have caught it, and why each didn't

| Mechanism | Where | Why it didn't fire |
|---|---|---|
| **D2 mmWave-fan sustain demotion** (v5.23.0+) | `coordinator.py:2740-2960` | Predicate requires `_d2_motion_sensors_present()` (`coordinator.py:1786-1815`, D-HIGH-1): **fail-closed when the room has zero PIR**. Living Room config: `motion_sensors: []`, `occupancy_sensors: []` (verified in `core.config_entries`). Leg (e) — PIR staleness ≥ MULT×timeout — is unsatisfiable, so the demotion is permanently off for this room. All other gates (house_state home_day allows, fan flagged: `fan_interference_rooms=["Living Room"]`) would have passed. |
| **Fan-transition CREATION gate** (v5.46.0) | `coordinator.py:~2290+`, `FAN_TRANSITION_SUSPECT_WINDOW_S=5.0` (`const.py:729`) | Creation-only by design (predicate (c): `not self._last_occupied_state`). Occupancy was created at 18:40:10 — fan turned on at 18:45:02, five minutes later. The fan captured an already-occupied room; that is sustain, not creation. Also possibly legitimate creation (Ziri/Jaya trackers still home at 18:40). |
| **Continuous-stuck rule (P22, Fix #9 — the one that DOES exclude)** | `coordinator.py:2117-2145`, `_stuck_sensor_hours=4.0` (`coordinator.py:283`) | Needs 4 h continuous-on. The final hold was 2 h 01 m (18:45:08→20:46:42), and every earlier off-tick that morning reset `_sensor_on_since`. Threshold simply not met — and the flapping-evades-continuous defect is exactly what the STUCK-SENSOR-1 card documents. |
| **D2 duty-cycle stuck detector** (v5.35.0) | `coordinator.py:2155-2200`; 60-min window, 85 % on-ratio, no PIR corroboration required here (none configured) | **Did detect — NOTIFY-ONLY by design** ("a sleeping person is ~100 % mmWave duty cycle... excluding would vacate sleeping bedrooms", FIX 2 B H-1 comment at `coordinator.py:2176-2183`). `notification_log` shows `Stuck signal: dutycycle` NM notes at 13:54, 17:10, 18:00, 18:20Z (room redacted `[audit]`; per-day dedup). Detection without consequence — the deliberate deferral recorded on the STUCK-SENSOR-1 card, blocked on SENSOR-CAPABILITY-1 + SignalTrustLedger criterion 4. |
| **Zone/house-tier stuck awareness** | none | `aggregation.py` / `presence.py` have no stuck-sensor input at all (verified on the card 2026-08-09 and re-confirmed: `veto_path="none"`, no discounting of the mmwave-only provenance). The house tier can see `fan_interference_rooms=["Living Room"]` and `tier1_provenance_breakdown={mmwave:1}` — it publishes both as attributes — but consumes neither in `infer()`. |
| **v4.7.13 sleep-only trust doctrine** | `coordinator.py:1821-1840` (`_d2_house_state_allows`) | Not the blocker here: it only vetoes demotion in SLEEP/WAKING/HOME_NIGHT; house was `home_day`, which **is** covered. The uncovered dimension in this incident is room capability (no PIR), not house state. |

Contributing (not primary): Jaya/Ziri phone trackers held stale-`home` from
~16:43Z to 19:28Z, keeping census at 2 for ~2.7 h after (per operator) everyone
had left — this delayed even reaching the census-0 precondition until 14:29 CT.

## Q6 — the guest flaps

Both flaps are the **guest-room Path B** (`presence.py:4550-4683`), not the
unidentified-census arithmetic: Guest Bedroom 1 (`room_is_guest_room=True`,
threshold 30 min) went occupied at 15:53:53Z; 16:23:59Z entry is exactly
15:53:53 + 30 min (+6 s tick). Exit 16:30:59 after it cleared at 16:25:59.
The earlier `guest → home_day` at 14:37:49 is the same room clearing at
14:32:49. Whether Guest Bedroom 1's midday occupancy was real (Jaya/Ziri were
plausibly home until ~19:28Z per their trackers) or the same phantom class was
not resolved — its input sensor trace was not pulled. The `away` transition's
trigger string `guest_room_occupancy` is only the inference-tick label.

## (d) Recommendations (ranked)

1. **Config-only — give the Living Room a corroborator (PIR or occupancy
   sensor).** `motion_sensors: []` is the single switch that disabled the
   already-shipped D2 sustain demotion for this room. One Zigbee PIR (or
   wiring the existing `rgbw_motion_lux_3rd_zigbee_livingroomhallway` if its
   coverage genuinely includes the seating area — verify placement first) turns
   the fail-closed gate open. Marginal benefit: very high (the entire 82-min
   hold releases at `MULT×occupancy_timeout`); marginal risk: near zero, no
   code. Applies to all six no-PIR rooms in
   `AUDIT_mmwave_only_rooms_2026-07-31.md`.
2. **Tier-1 — break the fan self-justification loop.** `fan_should_run` kept
   the fan on using occupancy whose sole provenance was mmWave in a room whose
   own fan is a known interferer. A small room-tier rule — comfort-fan sustain
   requires occupancy provenance other than mmwave-sole after N minutes, or a
   max mmwave-sole fan runtime — removes the loop without touching presence
   inference. Marginal benefit: high (fixes fans-in-empty-rooms even where the
   away transition isn't at stake); risk: moderate (fan policy churn — knob it,
   default generous).
3. **Tier 2-DB — let path β discount phantom-classed zones.** Today
   `indoor_blocked` treats a zone held ONLY by a fan-interference-flagged,
   mmwave-sole signal as full indoor truth, while the same payload already
   carries `fan_interference_rooms` + `tier1_provenance_breakdown`. Excluding
   such zones from the β indoor guard (NOT from occupancy itself) would have
   fired the LOST-tolerant away veto at ~19:29Z. This is a trust-hierarchy
   ripple on a shared primitive → Tier 2-DB minimum. Marginal benefit: high
   for the away transition specifically; risk: real (I1 erosion — must not
   force AWAY on a sleeping resident; the sleep-exempt gate already covers
   that, but reviews must prove it).
4. **STUCK-SENSOR-1 build** (corroboration-gated exclusion at the room tier) —
   the complete fix for the detector-without-consequence gap; NM notes fired
   all day and nothing consumed them. **Remains BLOCKED** on
   SENSOR-CAPABILITY-1 and the SignalTrustLedger criterion-4 golden-tap
   fixtures (hard blocker independent of approval, per the card). Note the
   card's own caveat applies to this incident: with no corroborator configured,
   Living Room would STAY notify-only even post-build — rec 1 is a
   prerequisite for rec 4 to help this room.
5. **Low-marginal / observe-only — tracker LOST hygiene.** All four trackers
   LOST/STALE simultaneously (and two stale-home for 2.7 h) is what removed
   path α. Note path α **ignores zone occupancy entirely** — had the trackers
   stayed ACTIVE and reported away, α would have fired at ~19:29Z despite the
   phantom. The incident required BOTH failures: trust collapse (killed α) AND
   the phantom zone (killed β + nobody-home). So improving phone tracker
   liveness (Jaya/Ziri devices, WAT-timezone quirk) is a genuine independent
   mitigation —
   but it is device/app work, not URA code, and recs 1-3 cover the house-side
   hole regardless.
