# AUDIT — W2-1 D0 fast-path rate probe (2026-09-26)

**Plan:** `docs/planning/PLANNING_hvac_w2_occupancy_fast_path.md` §3 (D0) / §5 D0. **Contract:** `PLANNING_hvac_arc_w1_w2_integration.md` C5 + C6.
**Probe:** `scripts/probes/hvac_fast_path_d0_probe.py` (read-only; recorder + URA DB opened `mode=ro`; `.storage` plain reads).
**Run:** `ssh ha "python3 - [--days 7] [--no-overrides] [--json]" < scripts/probes/hvac_fast_path_d0_probe.py` — window **2026-09-19 20:45Z → 2026-09-26 20:45Z**.
**Status:** measured sections complete; **W1-A `climate_write` per-zone baseline is PENDING** (§7). Read `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` first.

---

## 0. Headline

| Question | Answer |
|---|---|
| Trigger-eligible edges (armed-gate replay, cycle-sim variant S) | **472 in 165.2 h ≈ 68.6/day house-wide**: zone_1 32.3/day, zone_2 15.8/day, zone_3 20.5/day |
| …of which can change the zone's decision (zone had NO HVAC-armed room at the edge, "zone-cold") | **114 ≈ 16.6/day** (zone_1 22, zone_2 19, zone_3 73 over the window) — 24 % of eligible edges |
| Burst shape | 5-min sliding burst p95 = **3** in every zone (max 4–6); inter-edge gap **p1 = 0–3 s, p5 = 6–13 s** → bursts are near-simultaneous multi-room flips (e.g. Master Bathroom / Toilet / Vanity), not sustained trains |
| Periodic tick already within X s of an eligible edge | **X=60 s: 19–23 %; X=120 s: 35–42 %; X=300 s: ~100 %** (uniform phase, as expected — 60/300, 120/300) |
| Cycle duration (proxy: cycle END − inferred tick START) | **p50 13 s, p90 23 s, p95 28 s** (bulk 0–30 s; 30–60 s tail is flat background). No durable duration source exists (§5) |
| Per-zone limiter at the plan's <10 % rule (all eligible edges) | only **L ≤ 15 s** passes (S: 9.5 / 10.1 / 6.4 %); L = 60 s denies 15–21 % |
| Per-zone limiter on the edges that matter (zone-cold) | **0 of 114 denied for every L up to 300 s** (min in-zone gap between cold edges = 646 s) |
| Fail-out ("deny > 10 % AND tick covers > 90 %") | **Does NOT fire.** First conjunct true only on all-edge basis; second conjunct is false at every X < 300 s (≤ 42 %). At X = 300 s it is tautologically ~100 % and says nothing about "soon enough" |
| Proposed constants | `HVAC_FAST_PATH_MIN_INTERVAL_S = 60`, `HVAC_FAST_PATH_GLOBAL_MIN_INTERVAL_S = 20`, `HVAC_FAST_PATH_SLA_S = 45` — arithmetic §6; **two plan findings in §6.4 for the planner** |

---

## 1. Method (institutional sources, file:line on `develop` @ `22e9f20d8`)

**Rooms (plan §3 primary signal).** Every non-disabled ROOM entry (`entry_type == "room"`, `const.py:51/55`), `room_type` (`CONF_ROOM_TYPE`, `const.py:396`) ≠ `hallway` (`const.py:450`), member of an HVAC zone. Zone membership = latest `sensor.ura_hvac_coordinator_zone_N_status` attrs `live_rooms ∪ excluded_rooms ∪ transient_rooms` (all excluded/transient lists empty at read). Trigger entity = registry `unique_id == f"{entry_id}_occupied"`, platform `universal_room_automation` (C6) — required: entity_ids do not follow room names (e.g. Jaya Bedroom → `binary_sensor.jaya_bedroom_bedroom_4_occupied`). **33 rooms measured; 10 skipped:** 7 hallways (Kitchen Hallway, Kitchen Hallway Garage, Garage Hallway, Upstairs Hallway, Master Hallway, Guest Bedroom 2 Hallway, Foyer) + 3 in no HVAC zone (Patio, Garage A, Garage B). No disabled room entries.

**Rising edge.** Strict `off → on` only (plan §4.1, finding 6). Only **1** non-off→on transition (`unavailable → on`) in the window — lifecycle noise is negligible.

**Armed-gate replay** — hold per room = `_effective_hvac_hold_seconds` (`hvac_zones.py:976-1046`):
- per-room override `CONF_HVAC_VACANCY_HOLD` / `_NIGHT` (`const.py:1252-1253`, coerced per `_coerce_hold_override` `hvac_zones.py:42`) if set in the entry options, else
- `ROOM_TYPE_HVAC_HOLD` day (`const.py:1219-1224`: bedroom 60, media_room 120, common_area 60, hallway 0; other types → `DEFAULT_HVAC_VACANCY_HOLD = 60`, `const.py:1213`), or
- `ROOM_TYPE_HVAC_HOLD_NIGHT` (`const.py:1230-1241`: bedroom/media 1800, common 900, generic/bath/garage/utility 600, closet/infrastructure 300; fallback `DEFAULT_HVAC_VACANCY_HOLD_NIGHT = 60`, `const.py:1217`);
- night iff house_state ∈ `FAN_TRUST_STATES = ("home_night", "sleep", "waking")` (`hvac_const.py:881`, selected at `hvac_zones.py:1046`); night ≥ day clamp.
- House state = recorded `sensor.ura_coordinator_manager_house_state` (CoordinatorManager.house_state — HVAC's boot seed `hvac.py:1250-1253`; live via `SIGNAL_HOUSE_STATE_CHANGED`, `hvac.py:3276`). `unavailable` rows (2) walk back to the last real state.
- **Only override live today:** Jaya Bedroom day 60 / **night 5400 s**. Its set-date is not recoverable from `.storage`; it is applied across the whole window. Sensitivity run `--no-overrides` in §3.3.

Two replay variants:
- **P — plan replay (literal §3):** edge eligible iff the room's previous `on→off` is ≥ hold seconds earlier (hold keyed on house state at that falling edge — that is when the producer sets the tail, `hvac_zones.py:1111`).
- **S — cycle simulation (recommended):** replays the D1 producer `_compute_hvac_occupied` (`hvac_zones.py:1048-1123`) at every cycle — inferred periodic ticks + house-state-change cycles + one cycle at each eligible edge (the fast path itself; limiter ignored). An edge is eligible iff `_hvac_armed[room]` was not True after the last cycle. Producer dicts reset at every HA start (in-memory). S is closer to the real gate because the tail only starts at the first cycle that SEES the vacancy, so rooms stay armed up to one tick longer than P assumes. S also tags **zone-cold** edges: no room of the zone armed at the edge (= the zone's fused `any_room_hvac_occupied` would flip on this edge).

**Exclusions.** MAIN window ends at **2026-09-26 19:20Z** (empty house). **All 5 HA restarts** in the window are excluded from `homeassistant_stop` to `homeassistant_started + 15 min` — the two named in the brief (09-26 17:49Z, 20:15Z) plus three more found in the recorder (09-20 14:32Z, 09-22 04:19Z, 09-25 23:05Z). MAIN = 165.2 h; full local days (≥ 20 h MAIN) = 09-20 … 09-25 (6 days; daily median/p95/max use these only).

**Tick inference (for coverage and duration).** `async_track_time_interval` re-arms at `loop.time() + 300` on every firing (HA `helpers/event.py` `_TrackTimeInterval._schedule_timer`), so periodic ticks lie on a fixed grid per HA run apart from loop lateness. `SIGNAL_HVAC_ENTITIES_UPDATE` is sent only at the END of `_run_decision_cycle` (`hvac.py:1799`) and `HVACZoneStatusSensor` writes on it (`sensor.py:12274-12276`), so zone-status recorder rows mark cycle ends. Per 6-h chunk the probe fits the period (grid 299.80–301.60 s) and phase (lower envelope of the densest 15-s cluster). **Fitted period 300.3–301.1 s** — the tick drifts +0.3…+1.1 s per firing (event-loop lateness). 1,993 ticks inferred for the 7-day window (theoretical ≈ 2,010 net of restart gaps).

---

## 2. Per-room edges (MAIN window; empty-house column = 0 for every room)

`raw` = strict off→on edges; `P` / `S` = trigger-eligible under each replay; `S-cold` = S edges on a zone with no armed room.

| Zone | Room | Type | raw | P | S | S-cold |
|---|---|---|---:|---:|---:|---:|
| zone_1 | Living Room | common_area | 98 | 80 | 59 | 14 |
| zone_1 | Master Bath Toilet | bathroom | 54 | 51 | 45 | 0 |
| zone_1 | Master Bathroom | bathroom | 40 | 38 | 37 | 5 |
| zone_1 | Master Bedroom | bedroom | 32 | 28 | 19 | 1 |
| zone_1 | Study A | generic | 29 | 28 | 27 | 1 |
| zone_1 | Oji Vanity | bathroom | 22 | 21 | 18 | 0 |
| zone_1 | Study B | generic | 13 | 13 | 12 | 1 |
| zone_1 | AV Closet | infrastructure | 2 | 2 | 2 | 0 |
| zone_1 | Receiving Room | common_area | 2 | 2 | 2 | 0 |
| zone_1 | Study A Closet | closet | 1 | 1 | 1 | 0 |
| zone_2 | Jaya Bedroom | bedroom | 41 | 21 | 19 | 9 |
| zone_2 | Game Room | common_area | 32 | 31 | 28 | 7 |
| zone_2 | Jaya Bathroom | bathroom | 26 | 26 | 25 | 1 |
| zone_2 | Ziri Bedroom (Bedroom 5) | bedroom | 11 | 9 | 9 | 0 |
| zone_2 | Guest Bedroom 2 | bedroom | 10 | 10 | 8 | 2 |
| zone_2 | Guest Bedroom 2 Bathroom | bathroom | 9 | 9 | 9 | 0 |
| zone_2 | Up Guestbedroom Closet | closet | 6 | 6 | 5 | 0 |
| zone_2 | Exercise Room Closet | closet | 3 | 3 | 3 | 0 |
| zone_2 | Media | media_room | 2 | 2 | 1 | 0 |
| zone_2 | Ziri Bathroom | bathroom | 2 | 2 | 2 | 0 |
| zone_2 | Exercise Room / Media Room Closet | common / closet | 0 | 0 | 0 | 0 |
| zone_3 | Laundry | utility | 38 | 38 | 37 | 22 |
| zone_3 | Kitchen Pantry | utility | 38 | 31 | 27 | 19 |
| zone_3 | Butler Pantry | common_area | 24 | 23 | 22 | 9 |
| zone_3 | Breakfast Nook | common_area | 23 | 23 | 20 | 13 |
| zone_3 | Guest Bedroom 1 | bedroom | 12 | 12 | 11 | 3 |
| zone_3 | Dining Room | common_area | 10 | 10 | 6 | 5 |
| zone_3 | Laundry Closet | closet | 9 | 9 | 8 | 1 |
| zone_3 | Stair Closet | closet | 5 | 5 | 5 | 1 |
| zone_3 | Guest Bedroom 1 Bathroom | bathroom | 4 | 4 | 4 | 0 |
| zone_3 | Guest Bedroom 1 Closet | bedroom | 1 | 1 | 1 | 0 |
| zone_3 | Kitchen | common_area | 0 | 0 | 0 | 0 |
| **Total** | | | **599** | **539** | **472** | **114** |

Kitchen and Exercise Room had zero off→on edges in 7 days — worth a look separately (stuck-on or dead occupancy); out of scope here.

---

## 3. Per zone (plan §3 signals)

### 3.1 Variant S — trigger-eligible edges (recommended basis)

| Zone | n (7 d) | per day med / p95 / max (6 full days) | gap p1 / p5 / p50 / p95 / p99 (s) | 5-min burst p95 / max | tick ≤60 s / ≤120 s / ≤300 s | median wait to tick |
|---|---:|---|---|---|---|---:|
| zone_1 | 222 | 33.0 / 45.0 / 48 | 1 / 7 / 551 / 11,356 / 26,148 | 3 / 6 | 23.0 % / 41.9 % / 99.1 % | 142 s |
| zone_2 | 109 | 9.5 / 29.2 / 30 | 0 / 6 / 1,181 / 29,001 / 45,877 | 3 / 5 | 22.9 % / 39.4 % / 100 % | 142 s |
| zone_3 | 141 | 17.0 / 38.0 / 42 | 2 / 13 / 1,102 / 21,638 / 33,019 | 3 / 5 | 19.1 % / 35.5 % / 100 % | 181 s |

Per local day (S): zone_1 09-19=14 (partial), 09-20=36, 09-21=34, 09-22=32, 09-23=17, 09-24=23, 09-25=48, 09-26=18 (partial); zone_2 11, 27, 9, 10, 8, 7, 30, 7; zone_3 4, 20, 14, 26, 13, 12, 42, 10.

Note on percentiles: for a limiter the LOW gap percentiles are the burst metric (p1/p5 are included for that reason); p95/p99 are the long overnight/away gaps.

### 3.2 Variant P (literal plan replay) and zone-cold subset

| Zone | P n | P per day med / p95 / max | P gap p1 / p5 / p50 | S-cold n | S-cold per day med / p95 / max | S-cold gap p1 / p5 / p50 (s) | S-cold tick ≤60 / ≤120 s |
|---|---:|---|---|---:|---|---|---|
| zone_1 | 264 | 39.5 / 55.0 / 58 | 1 / 7 / 460 | 22 | 2.0 / 8.2 / 10 | 646 / 1,058 / 11,184 | 22.7 % / 36.4 % |
| zone_2 | 119 | 9.5 / 32.0 / 33 | 0 / 7 / 917 | 19 | 2.5 / 4.8 / 5 | 4,729 / 4,771 / 19,252 | 15.8 % / 42.1 % |
| zone_3 | 156 | 19.0 / 43.2 / 48 | 3 / 14 / 752 | 73 | 9.0 / 15.8 / 17 | 946 / 1,050 / 3,521 | 19.2 % / 34.2 % |

Zone-cold 5-min burst p95 = max = **1** in every zone.

### 3.3 Sensitivity — Jaya Bedroom night override removed (`--no-overrides`)

Only zone_2 moves: S 109 → 116, S-cold 19 → 26, P 119 → 126; busiest-day L = 60 deny 26.7 % → 25.8 %. Conclusions unchanged.

### 3.4 Empty-house bonus column (phantoms)

Only **0.93 h** of the 19:20Z-onward window survives restart exclusion (the 20:15Z restart + 15 min tail covers most of it). **0 rising edges** in that slice for every room. Too short to characterise phantoms; re-run tomorrow if a phantom rate is wanted (the probe reports it automatically).

---

## 4. Periodic-tick coverage (fail-out input)

Seconds from each eligible edge to the next inferred periodic tick start: coverage ≤ 60 s **19–23 %**, ≤ 120 s **35–42 %**, ≤ 300 s **99–100 %** (the 0.9 % miss in zone_1 = edges in chunks where the tick grid could not be fitted or right after a restart gap). This is the uniform-phase expectation (60/300 = 20 %, 120/300 = 40 %): the periodic tick has no correlation with occupancy, so it is never "already covering" edges in any useful sense below 300 s.

Why this matters with C18: today an edge waits (wait-to-tick) and then a second full tick for the dwell (5–10 min total). D3's dwell follow-up alone would cut that to wait-to-tick + 122 s (median ≈ 142–181 + 122 s); D2's edge trigger removes the wait-to-tick (median 142–181 s) on top. Both components are ~2–3 min of median latency.

---

## 5. Cycle duration

**No durable cycle-duration source exists.** `hvac.py` records no wall-time for `_async_decision_cycle` / `_run_decision_cycle` (no `monotonic`/`perf_counter` in `hvac.py`; the only timers are `hvac_setpoint.py:435/461/479` — per-wire-call `ts_issued`/`ts_returned` on W1-A rows, not cycle time); `decision_log` (`database.py:812-828`) has no duration column and HVAC writes only `preset_change` rows there; `ura_activity_log` has none; the re-entrancy skip at `hvac.py:1601` logs at DEBUG (not retained).

**Proxy (clearly a proxy):** cycle END (zone-status recorder row, `hvac.py:1799`) minus inferred tick START, n = 3,885 rows in the MAIN window:

| p5 | p25 | p50 | p75 | p90 | p95 | p99 |
|---:|---:|---:|---:|---:|---:|---:|
| 3.6 s | 9.1 s | 13.0 s | 18.0 s | 22.7 s | 27.6 s | 54.8 s |

5-s histogram: 0–5: 308, 5–10: 871, 10–15: 1,176, 15–20: 852, 20–25: 415, 25–30: 95, then a flat ~16–35 per bin to 60 s. The bulk is 0–30 s; the flat 30–60 s tail is background (non-periodic cycles / fit error), so p99 is not a cycle-time statistic. Caveat: the phase is the lower envelope, so values are relative to the fastest cycle in each 6-h chunk (absolute durations are ≥ these by that minimum). Implication: the decision-cycle lock is held ~13 s median, ~28 s p95 per periodic tick → ~4 % (13/300) of edges land while a periodic cycle is running and will take the trailing-rerun path (§4.5).

---

## 6. Proposed sizing — arithmetic

### 6.1 `HVAC_FAST_PATH_MIN_INTERVAL_S` (per zone) — propose **60 s**, with a plan finding

Per-zone limiter replay (edge denied if a non-periodic cycle for the same zone ran < L s earlier; stamp only on runs, plan §4.3), deny % of eligible edges over the full window:

| L (s) | P z1 / z2 / z3 | S z1 / z2 / z3 | S busiest day (09-25) z1 / z2 / z3 | zone-cold edges denied |
|---:|---|---|---|---:|
| 15 | 8.3 / 9.2 / 5.8 | 9.5 / 10.1 / 6.4 | 10.4 / 16.7 / 7.1 | 0 / 114 |
| 30 | 11.7 / 14.3 / 11.5 | 12.6 / 13.8 / 11.3 | 16.7 / 16.7 / 11.9 | 0 / 114 |
| 60 | 18.2 / 21.0 / 14.7 | 17.6 / 21.1 / 14.9 | 22.9 / 26.7 / 16.7 | 0 / 114 |
| 120 | 24.2 / 25.2 / 20.5 | 23.9 / 25.7 / 21.3 | 31.2 / 33.3 / 28.6 | 0 / 114 |
| 300 | 34.1 / 34.5 / 29.5 | 33.3 / 34.9 / 29.8 | 41.7 / 50.0 / 38.1 | 0 / 114 |

- **Literal rule** ("deny < 10 % of trigger-eligible edges per zone at p99 burst"): only L ≤ 15 s passes on the 7-day totals, and nothing ≥ 15 s passes on the busiest day (zone_2 16.7 %). Reason: gap p1 = 0–3 s / p5 = 6–13 s — the denied edges are the 2nd/3rd room of a near-simultaneous multi-room flip. A 15-s limiter is not a meaningful cloud-rate protector.
- **Edges that can change a decision:** a denied edge in a zone that already has an HVAC-armed room cannot change the zone's fused `any_room_hvac_occupied`, so it cannot change a preset. All 114 zone-cold edges are ≥ 646 s from the previous eligible edge in their zone, so **L up to 300 s denies 0 of them**.
- **Proposal: L = 60 s** (the plan's starting value). Arithmetic: worst cold-edge exposure = 0/114 denied; all-edge denial 15–21 % (all warm, decision-neutral for presets); non-periodic cycles 72.5/day (L=60, G=0) vs 79.0/day at L=15 — i.e. the limiter only trims ~6.5 cycles/day either way, so 60 vs 15 is not a load decision. 60 s keeps one fast-path cycle per zone per burst.
- **Caveat:** warm-zone edges may still matter to the per-room HVAC fan controller, which §4.7 runs on non-periodic cycles ("fans are the operator's other fast-in lever"). A denied warm edge falls back to the next periodic tick (median 142–181 s) for that room's fan. Not measured here.

### 6.2 `HVAC_FAST_PATH_GLOBAL_MIN_INTERVAL_S` — propose **20 s**, with a plan finding

Rule: aggregate non-periodic cycles ≤ ~1 per 20 s house-wide ⇒ G = 20 s by construction. Replay (S edges + one dwell follow-up per zone-cold edge at +122 s = dwell 120 s live option + `FAST_PATH_DWELL_SLACK_S` 2 s; follow-ups exempt from L, subject to G, plan §4.4):

| L | G | all-edge deny | zone-cold edges denied | follow-ups denied (of 114) | non-periodic cycles/day | max cycles in any 20 s |
|---:|---:|---:|---:|---:|---:|---:|
| 60 | 0 | 18.4 % | 0 | 0 | 72.5 | 2 |
| 60 | 10 | 20.8 % | 5 | 1 | 70.8 | 2 |
| 60 | **20** | 21.6 % | **7** | **5** | **69.6** | 1 |
| 60 | 30 | 22.9 % | 11 | 11 | 67.8 | 1 |
| 60 | 60 | 27.5 % | 23 | 22 | 63.1 | 1 |

Arithmetic: at G = 0 the house already never exceeds 2 non-periodic cycles in 20 s, and averages 72.5/day ≈ 1 per 20 min (+25 % over the 288/day periodic ticks; L=60, G=20 → 69.6/day, +24 %). G = 20 enforces the ceiling (≤ 4,320/day theoretical) at a cost of **7 zone-cold edges (6 %) and 5 dwell follow-ups (4 %)** denied — cross-zone collisions (a zone-X edge within 20 s of a zone-Y cycle that started before the edge and therefore did not see it). Those fall back to the periodic tick (the 5–10 min C18 path).

### 6.3 `HVAC_FAST_PATH_SLA_S` — propose **45 s**

Trigger → cycle START is ~0 s unless the lock is held; then the trailing rerun (§4.5) starts when the running cycle ends: ≤ p95 cycle proxy 27.6 s (≈ 4 % of edges hit a running periodic cycle). 45 s = 27.6 s + ~17 s headroom for proxy error (§5 caveat) and one chained rerun. Limiter denials are outside the SLA by the INV's own wording.

### 6.4 Findings for the planner (not decided here)

1. **The §3 sizing denominator is the wrong population.** "< 10 % of trigger-eligible edges" counts warm-zone edges that cannot move a preset (76 % of eligible edges). Suggest restating the rule over zone-cold edges (0 % denied at any L ≤ 300 s) — or, simpler, add gate 3b "skip if the zone is already `any_room_hvac_occupied`", which would cut triggers from ~68.6/day to ~16.6/day and make the per-zone limiter nearly idle. Check the fan-controller caveat (§6.1) before adopting 3b.
2. **Global-limiter denials of zone-cold edges and follow-ups lose latency.** 7 + 5 per week at G = 20. A deferral (schedule at `last_any + G`) instead of a denial keeps the ceiling and loses nothing; or exempt follow-ups from G as they are already exempt from L.

---

## 7. PENDING — pre-W2-1 `climate_write` baseline (W1-A)

**Not measurable yet.** W1-A's durable `climate_write` rows (`ura_activity_log`, action `climate_write`) started 2026-09-26 ~15:25 CDT (v5.103.16); at probe time only **3 rows** existed (2026-09-26 20:23:16Z … 20:42:14Z), all inside the empty-house window. To be added after ≥ 1 clean day:

| Zone | `climate_write` rows/day | by verb (preset / temperature / hvac_mode) | by site | D0 margin for D3 write-rate acceptance |
|---|---|---|---|---|
| zone_1 | PENDING | PENDING | PENDING | PENDING |
| zone_2 | PENDING | PENDING | PENDING | PENDING |
| zone_3 | PENDING | PENDING | PENDING | PENDING |

Query to use: `select json_extract(details,'$.zone_id'), json_extract(details,'$.verb'), json_extract(details,'$.site'), count(*) from ura_activity_log where action='climate_write' and timestamp >= <start> group by 1,2,3` (verify the details column/key names against W1-A's writer before running). Margin proposal to evaluate then: the fast path adds only *earlier* preset writes on zone-cold entries (≤ 16.6/day house-wide, and each replaces a later tick write rather than adding one), so the expected per-zone write delta is ≈ 0; set the acceptance margin from the observed day-to-day spread of the baseline.

---

## 8. What could not be measured, and why

| Item | Why |
|---|---|
| Absolute cycle duration | No durable source (§5); only an end-vs-inferred-tick proxy |
| W1-A write baseline | W1-A live < 1 day; 3 rows (§7) |
| Phantom (empty-house) edge rate | 0.93 h usable after restart exclusion |
| Historic per-room hold overrides | `.storage` holds only current options; Jaya's 5400 s night override applied to the whole window (sensitivity §3.3) |
| Real tick instants | Inferred from cycle-end rows (fitted period/phase per 6-h chunk); good for coverage statistics, not for per-event claims |
| Fan-controller value of warm-zone edges | Out of D0 scope (§6.1 caveat) |
