# AUDIT: Exit-Evidenced Vacancy — Corrected Measurement Probe (v2)

**Date:** 2026-08-04 · **Type:** read-only measurement probe (Measure Before You Build)
**Data:** HA recorder `/config/home-assistant_v2.db` (span 2026-07-27 09:12 → 2026-08-04 08:48 UTC, ~7.98 d) + URA DB `ura_activity_log` / `anomaly_log`. Both opened `mode=ro`. No writes, no code changes.

**Question:** For "exit-evidenced vacancy" (room becomes sweep-vacant only when adjacent-space motion follows in-room stillness): what fraction of real exits show exit evidence when CORRECTLY defined, and do the 7 known false sweeps show NO evidence (the discriminator)?

## Method (v1 flaws corrected)

1. **Exit timestamp = timeout expiry, not departure.** Each room's `occupancy_timeout` was read from its config entry (`/config/.storage/core.config_entries`, effective config = `data` merged with `options`; key `occupancy_timeout`). Evidence window = `[exit_ts − timeout − pad, exit_ts]`, pad = 120 s primary (60 s / 300 s sensitivity).
2. **Evidence = raw adjacent motion EDGES** from recorder `states` (off/unknown→`on` transitions of the adjacent rooms' CONFIGURED `binary_sensor` ids from `motion_sensors` + `presence_sensors` + `occupancy_sensors` buckets), not occupancy-entry transitions. No name-guessing for the primary run.
3. Exits = `ura_activity_log` rows with `action='occupancy_exit'` per mapped room, restricted to recorder span (N=88 total).

### Adjacency resolution (map from 2026-08-03 room_transitions probe)

| Room | Timeout | Adjacents resolved | Adjacents UNRESOLVABLE (no URA config entry) |
|---|---|---|---|
| Master Bedroom | 300 s | Master Bathroom, Study B | **Master Hallway, Ezinne Makeup** — not URA rooms |
| Living Room | 300 s | Kitchen, Breakfast Nook, Dining Room | — |
| Study A | 540 s | Study A Closet, Receiving Room | — |
| Jaya Bedroom (Bedroom 4) | 500 s | Jaya Bathroom | **Upstairs Hall** — not a URA room |
| Ziri Bedroom (Bedroom 5) | 500 s | Ziri Bathroom | **Upstairs Hall** |
| Game Room | 540 s | Media ("Media Room") | **Upstairs Hall** |

### Confound discovered: 5 of 13 configured adjacent sensors NEVER fired in 8 days

Per-entity recorder history over the full span (`count('on')`):

| Configured adjacent entity | 'on' rows / total | Status |
|---|---|---|
| `binary_sensor.occupancy_lux_temp_humidity_hobeian_receiving_presence` | 0 / 98 | only off/unavailable/unknown boot writes — **dead or mis-registered** |
| `binary_sensor.occupancy_lux_temp_humidity_studyacloset_presence` | 0 / 98 | same pattern — **dead** |
| `binary_sensor.rgbw_motion_lux_3rdr_wifi_matter_jayabath_occupancy_2` | 0 / 32 | **100% `unavailable` all week** |
| `binary_sensor.mmwave_motion_lux_matter_wifi_mediaroom_occupancy` | 0 / 32 | off-only, 0 events in 8 d |
| `binary_sensor.mmwave_motion_lux_meross_wifi_mediaroom_sensor_presence_motion` | 0 / 60 | off/unavailable only |

Healthy examples for contrast: kitchen mmWave 775 'on' rows, masterbath PIR 58, ziribath 35. **Study A, Jaya Bedroom, and Game Room therefore have effectively ZERO functioning configured adjacency coverage** — their 0% rates below are sensor-fleet artifacts as much as architecture results.

## (A) True-exit evidence rate — configured entities only (pad 120 s)

| Room | Exits (7.98 d) | With evidence | Rate |
|---|---|---|---|
| Master Bedroom | **0** | — | — (MB logged zero `occupancy_exit` rows all week — likely bed-occupancy hold; separate finding) |
| Living Room | 16 | 10 | 63% |
| Study A | 3 | 0 | 0% (dead adjacents) |
| Jaya Bedroom | 19 | 0 | 0% (dead adjacent + Upstairs Hall unmapped) |
| Ziri Bedroom | 15 | 3 | 20% (Upstairs Hall unmapped) |
| Game Room | 35 | 0 | 0% (dead adjacents + Upstairs Hall unmapped) |
| **Pooled** | **88** | **13** | **15%** |

## (D) Sensitivity — pad 60 s / 300 s (configured)

Pooled: pad 60 → 10/88 = **11%**; pad 120 → 13/88 = **15%**; pad 300 → 15/88 = **17%**. The rate is pad-insensitive: the shortfall is coverage, not window sizing.

### Supplemental run — best-achievable adjacency (NON-configured entities, name-resolved; labeled clearly as outside the "configured ids only" rule)

Added: `master_hallway_motion` (camera), `rgbw_motion_lux_3rd_zigbee_masterhallway_occupancy`, `pir_zigbee_ezinnevanity_occupancy`, `rgbw_motion_lux_3rd_zigbee_livingroomhallway_occupancy`, `upstairs_hall_motion` (camera), `receiving_room_sensor_presence` (0 edges — also dead).

| Room | Exits | With evidence (pad 120) | Rate |
|---|---|---|---|
| Living Room | 16 | 11 | 69% |
| Study A | 3 | 0 | 0% |
| Jaya Bedroom | 19 | 4 | 21% |
| Ziri Bedroom | 15 | 6 | 40% |
| Game Room | 35 | 13 | 37% |
| **Pooled** | **88** | **34** | **39%** (pad 60: 38%, pad 300: 47%) |

**Even with adjacency completed via every live hall/vanity sensor found, the best-case pooled true-exit rate is 39-47% — nowhere near the 80% gate requirement.** Caveat: an unknown fraction of the 88 "exits" are themselves false timeouts (occupant still present), which the gate is *supposed* to hold — but even Living Room, the best-instrumented room, tops out at 69%.

## (B) The 7 false-sweep discriminator — PREMISE NOT VERIFIABLE IN DATA

Honesty finding first: **no `actuation_conflict` rows exist anywhere in `anomaly_log`** (`select distinct metric_name ... like '%conflict%' or '%actuat%'` → empty), and `ura_activity_log` shows **no occupancy_exit/sweep events in master_bedroom / living_room / study_a at any of the 7 timestamps** (window 00:30–05:00 UTC contains only: LR exit 01:58, Study A entry 03:08 / exit 03:23, LR entry 04:18 / exit 04:49). The 7 given timestamps (00:43, 00:58, 01:23, 01:43, 01:53, 03:18, 04:43) instead coincide exactly with the **5-minute-cadence `write_local_witness_divergence` energy anomaly rows** (e.g. `2026-08-04T00:43:48`, `00:58:48`, `01:23:48` …). The "7 false sweeps" appear to be a mislabeling of energy write-verify noise, not room actuation conflicts. The discriminator half of the question therefore cannot be honestly scored.

Computed anyway, as specified (adjacent motion edge in `[ts − 15 min, ts]`), per candidate room:

| Conflict ts (UTC) | MB (configured) | LR (configured) | SA (configured) | MB (suppl.) | LR (suppl.) | SA (suppl.) |
|---|---|---|---|---|---|---|
| 00:43 | evidence (400 s) | evidence (131 s) | NONE | evidence | evidence | NONE |
| 00:58 | evidence (814 s) | evidence (126 s) | NONE | evidence | evidence | NONE |
| 01:23 | NONE | NONE | NONE | evidence | evidence | NONE |
| 01:43 | NONE | evidence (405 s) | NONE | evidence | evidence | NONE |
| 01:53 | NONE | NONE | NONE | NONE | NONE | NONE |
| 03:18 | NONE | evidence (190 s) | NONE | NONE | evidence | NONE |
| 04:43 | NONE | NONE | NONE | NONE | NONE | NONE |

Blocked count (NONE = gate blocks): configured — MB 5/7, LR 3/7, SA 7/7. Supplemental — MB 3/7, LR 2/7, SA 7/7. Without a per-timestamp room attribution (none exists in either DB), the "block ≥6/7" criterion is only met if all 7 episodes were Study A — contradicted by the premise. **As measured, the discriminator does NOT clear the bar for MB/LR at these timestamps** — but since the episodes themselves are unconfirmed, this is not evidence against the gate either.

## (C) Cost side — evidence→exit gap for evidenced exits (pad 120)

Gap = `exit_ts − last evidence edge in window` (evidence precedes the timeout expiry):

- Configured (n=13): min 5 s, p25 56 s, median 224 s, p75 390 s, p90 565 s, max 602 s.
- Supplemental (n=34): min 5 s, p25 224 s, median 501 s, p75 556 s, max 607 s.

Interpretation: for evidenced exits, adjacent evidence exists **before** the timeout expires (median ~4-8 min prior), so a gate that checks "was there adjacent motion in the back-window" adds **~zero extra fan runtime on evidenced exits**. The entire cost lands on the 61-85% of exits WITHOUT evidence, where the sweep would be deferred indefinitely (or until a fallback timer) — i.e., in the current sensor fleet the gate would leave most rooms' fans/lights running after most genuine departures.

## Verdict: **NO-GO as designed — REDESIGN required**

Against the stated bar ("pass ≥80% of genuine exits AND block ≥6/7 known false sweeps"):

1. **Pass rate: FAIL, decisively.** 15% (configured), 39% best-case with every live sensor in the house conscripted, 47% at the most generous padding. Not a tuning miss — a 2× structural shortfall even in the best room (LR 69%).
2. **Block rate: UNSCOREABLE.** The 7 "false sweeps" do not exist as actuation-conflict episodes in either DB; the timestamps match the energy write-verify anomaly cadence. Re-derive the false-sweep ground truth before any gate design proceeds.
3. **Root causes to fix before re-probing** (redesign inputs, in order):
   - **Dead sensor fleet:** 5 configured adjacent sensors with zero 'on' events in 8 days (jayabath 100% unavailable; receiving + studyacloset + both mediaroom effectively dead). No adjacency gate can work on top of this.
   - **Adjacency holes:** Upstairs Hall / Master Hallway / Ezinne Makeup are not URA rooms, so the primary egress path of 4 of the 6 rooms has no CONFIGURED evidence source. Non-URA camera motion (`master_hallway_motion`, `upstairs_hall_motion`) exists and works — the gate would need a sanctioned way to consume non-room entities.
   - **Master Bedroom logs zero exits** (0 in 8 days) — likely bed-sensor occupancy hold; MB can't be evaluated at all until that's understood.
   - Some fraction of the 88 "exits" are themselves false timeouts, deflating the measurable ceiling of (A); a follow-up probe should cross-check exits against subsequent re-entry latency to estimate that fraction.

If redesigned, the promising shape per this data: evidence-gated sweep **as a confidence modifier, not a hard gate** (hard gate strands 60%+ of real exits), and only in rooms whose adjacency coverage passes a liveness check (≥N adjacent edges/day).

## Reproduction

All queries run via `ssh ha "python3 -"` against the two DBs in `mode=ro`. Key steps: (1) effective room config = `{**entry.data, **entry.options}`; (2) motion edges = state rows per `states_meta.metadata_id` ordered by `last_updated_ts`, edge when `state=='on' and prev!='on'`; (3) exits from `ura_activity_log` `action='occupancy_exit'` clipped to recorder span; (4) bisect over pooled per-room edge lists.

## Orchestrator addendum (2026-08-04)

**Correction to (B):** the 7 false-sweep episodes ARE verifiable — they
live in `memory_episodes` (type actuation_conflict, adjudicated_by
hvac_fan_controller), a table this probe did not query, and are
corroborated by recorder fan-off state transitions at matching times
(00:18/00:43/00:58/01:23/01:43Z master; 01:53/04:43Z living; 03:18Z
study_a). The 5-min timestamp alignment is the HVAC decision-cycle
cadence — sweeps dispatch on ticks. Ground truth stands.

**Adjudicated outcome:** NO-GO on the hard exit-evidence gate is
ACCEPTED on coverage grounds. The occupied-sensor harm-stop guard (in
build, hotfix/occupied-fan-off-guard) blocks 7/7 of the known false
sweeps with universally-available signals and becomes the vacancy-
confidence architecture for actuation-offs. Exit evidence is PARKED as
a confidence-modifier refinement with evidence triggers: (a) any
actuation_conflict where the occupied sensor had ALSO dropped (the
class the guard cannot see), (b) adjacency sensor fleet repaired.

**Infrastructure rot found (filed):** 5 dead/silent adjacent sensors
incl. jayabath 100% unavailable; Master Bedroom logged ZERO
occupancy_exit rows in 8 days (bed-sensor continuous hold — ties to
B-2026-08-04-1 stuck-signal class).
