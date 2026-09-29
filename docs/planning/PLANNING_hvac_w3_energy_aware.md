# PLANNING — HVAC W3 "Energy-aware HVAC" (ONE consolidated cycle)

**Date:** 2026-09-28 · **Author:** ura-planner · **Status:** REV 2. The plan review returned FIX-PLAN-FIRST; this revision addresses it. G0 results are being appended by the probe agent. No build is dispatched until G0 verdicts are in and this revision is re-checked.
**Workstream card:** `HVAC-W3-ENERGY-AWARE` (`docs/planning/kanban.data.yaml:2338`). Operator 2026-09-28: *"Clearly we need to batch them and consolidate."*
**Read-first satisfied:** `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` read completely, including §10 (corrections C1–C25) and §11 (arc). Nothing below re-asserts a §10 claim.
**Version:** no version assigned (unshipped). If anything ships, it is a PATCH bump (`5.103.x`) — nothing here is a new user-facing capability.

### Revision note — REV 2 (2026-09-28), addressing `docs/reviews/code-review/plan_review_hvac_w3_energy_aware.md`
| Finding | Change |
|---|---|
| **H1** | Q1 is split. (a) Offline, and it is the real check: evaluate the engine's period logic against the file for every hour of a year. (b) Sensor sanity: drop transitions out of `unknown`/`unavailable`; tolerance ≥ 10 min. The weekday/weekend clause is removed (the tariff file has no day-type dimension). |
| **H2** | Every probe derives the local hour/day from `timestamp` via `America/Chicago` (DST-aware). **Never read** `energy_history.hour_of_day` / `day_of_week` / `is_weekend`: they are UTC (`database.py:2697`, `:2723-2725`). A card and a QUALITY_CONTEXT bug-class suggestion are added (§11). |
| **H3** | Q8 keys on `json_extract(details_json,'$.reason')`; the window is post-v5.103.9 only (≥ 2026-09-18), pro-rated. "Outcome-changing" now also requires that the zone's house-state target preset was not already `away`. |
| **M1** | Q3's primary source is now recorder **LTS** (SPAN AC 2025+2026 shoulders; Envoy net/production from 2026-04-11). `energy_history` is a cross-check only. "Time-critical" is dropped. |
| **M2** | Q3 is a two-sided rule: the upper bound can only give NO-GO. GO requires a realistic estimate with a printed bank cap, and battery kWh freed by the shift is valued explicitly. |
| **M3** | New §5.1 triage table covering all 7 readers that use `hvac_action` as "plant running" (SWAP / KEEP / card). |
| **M4** | G2-SC: SPAN configured ⇒ SPAN only; SPAN unavailable/unknown ⇒ drop `on_since`, book nothing. INV-G2(b) is restated (no "equals pre-cycle" claim for zones with SPAN configured). Test added. |
| **M5** | Q10 is decided by live data (`sample_count=14` on all zones), so the choice is between a rename and a reset. **Chosen: rename.** All touch-sites are listed, with a per-site mutation drill. The ~14-day re-learn cost is recorded as accepted. |
| **M6** | Q9: LTS arm dropped; the 7-day SPAN arm only (n≈6); verdict labelled *indicative* below n=10; reset = forced mode off→on by construction. |
| **L1** | `forecast_peak_time_iso` is left alone. G1 now has **five** sites; the existing `anchor_period` attrs are cited; the pinned test is listed. |
| **L2** | DST-day tests added (2026-11-01, 2027-03-14). |
| **L3** | The G1 Live check is preconditioned on both pre-cool switches being ON (live-read). |
| **L4** | One tri-state helper (running / not / unknown); Gate 4 maps unknown→False (unchanged semantics). |
| **L5** | SPAN callback cost and install-latch noted; entity→zone map built at install. |
| **L6** | Q5/Q7 also record ODU stage-vs-SPAN agreement. |
| **L7** | G3-c knob rung stated. |
| **L8** | `hvac_zones.py:1099` → `:1110`; Q11 window limits stated. |

---

## 0. Headline — what this plan concludes

W3 is **one cycle with four ordered groups**. The cycle starts with a read-only measurement step (G0), and G0 decides whether each later group gets built. Consolidating the cards turned up five findings that shrink the build:

1. **The pre-cool window is already right in summer.** The live tariff (`/config/universal_room_automation/tou_rates.json`, identical to the built-in `PEC_TOU_RATES`, `energy_const.py:15-65`) puts summer's first price rise at 14:00 (mid_peak). The hard-coded window `[10,14)` therefore already ends at the first price rise, but only because the two numbers happen to match (Bug Class #63). The reviewer verified that the recorder shows off_peak→mid_peak at 14:00:00–14:00:27 on all 8 days from 09-21 to 09-28, including a weekend. The mismatch shows up **only in shoulder months** (Mar–May, Oct–Nov: off-peak runs until 17:00, so the window ends 3 h early). Winter doesn't matter, because Path A is turned off in winter (`hvac_predict.py:709-712`).
2. **The card's premise that pre-heat is badly timed is real, but fixing it saves no money.** Pre-heat runs 05:00–06:00 (`OFF_PEAK_END_HOUR=6`, `hvac_predict.py:56`, `:664`), which falls inside winter mid_peak 05–09. Heating here is **gas-fired** (`hvac_override.py:1933-1937`). A time-of-use tariff only prices electricity, so re-timing pre-heat saves nothing. **DROP.** Documented here; no card.
3. **"ODU Var" does not exist on this house.** `ha_carrier` only creates `OutdoorUnitVarSensor` when `outdoor_unit_type in ["varcaphp","varcapac"]` (`ha_carrier/sensor.py:90-95`). Neither the registry nor `states_meta` has a `*odu_var*` entity (reviewer-verified). `HVAC-D5-REGROUND-ON-ODU-VAR-1` is **DROPPED as written.** The ODU Status *state* ("Stage 3" / "Stage 5") is a Carrier-side duty signal, but it comes from the same cloud-polled feed family as `hvac_action`. SPAN wins; Q5/Q7 record stage-vs-SPAN agreement so the reason is on record (L6).
4. **URA already has a better "is the compressor running" signal than hvac_action, and D5 and the short-cycle producer don't use it.** The arrester's Gate 4 switched to SPAN circuit draw (`_zone_is_actively_cooling`, `hvac_override.py:1915-1963`, `AC_ACTIVELY_COOLING_KW_MIN=0.5`, `hvac_const.py:818`, default LIVE `:838`) after measuring that Carrier's `hvac_action` reads `idle` for 7–13 % of high-draw time (`kanban.data.yaml:11857-11866`). Seven readers use `hvac_action` as "plant running". The §5.1 triage decides each one; two are SWAP candidates (D5 and short-cycle).
5. **Most of the equipment-health card is measurement, config, or park, not code.** Reset-vs-nudge is a small probe whose outcome is a switch (`switch.ura_hvac_coordinator_ac_reset`). Refrigerant-drift alerts can't be baselined yet: superheat and discharge are **attributes**, and the recorder keeps them for only **7 days** (`configuration.yaml:12-13`). The config-first fix is HA template sensors with `state_class: measurement`, so long-term statistics build up a season of history.

### Consolidation table

| Card | Disposition | Where |
|---|---|---|
| `HVAC-PRECOOL-WINDOW-TOU-DERIVED-1` | **MERGED** — build gated on G0-Q1/Q3 | **G1** |
| `HVAC-D5-REGROUND-ON-ODU-VAR-1` (parked) | **DROPPED as written.** The ODU Var entity doesn't exist here. Its intent, a real duty signal for D5, is merged into G2 on the SPAN signal, gated on G0-Q8 | **G2** |
| `HVAC-EQUIPMENT-HEALTH-OBSERVABILITY-1` | **SPLIT.** P2 reset-vs-nudge → G0-Q9 → config (G3-a). P4 re-ground → G2. P3: the pre-cool part → G0-Q3; the rest PARKED. P1 drift/limit alerts → G3-b (**PARK** + config: template sensors). Filter → G3-c, **operator question** | G0 / G2 / **G3** |
| `HVAC-ANOMALY-BLIND-1` (W4, residual A) | **STAYS SEPARATE** (W4). It becomes a hard dependency only if G3 adds new anomaly metrics, which this plan does not. G2 changes the *producer* of its one live metric (and renames it — §5), so G2 reviewers read that card | W4 |
| `HVAC-BASELINE-MAXSAMPLES-1` (W4, parked) | **STAYS SEPARATE**, still parked. It folds in only if G3-b is ever revived with learned, seasonal baselines | W4 |
| `EC-GRID-ANTICIPATORY-PRECOOL-GAP-1` (parked) | **STAYS SEPARATE**, still parked. Summer-only value; new grid/battery actuation. G0-Q11 records a partial seed; revival trigger **June 2027** | EC thread |
| Pre-heat TOU misalignment (new finding 2) | **DROPPED** — gas heat. Recorded in state-of-play §9 on the next HVAC ship (doc-only) | — |
| `energy_history` UTC-named-local columns (new, from H2) | **NEW CARD to mint** (adjacency sweep first): audit readers of `hour_of_day` / `day_of_week` / `is_weekend`. Out of W3 scope | EC/analytics thread |

### Groups, tiers, and the release

| Group | What | Gate | Tier | Ships? |
|---|---|---|---|---|
| **G0** | One read-only probe script plus an audit doc with a hand-built zone→system→SPAN fixture | none (read-only) | none; the orchestrator re-derives one number independently | no release |
| **G1** | Pre-cool window derived from the TOU engine | G0-Q1 + Q3 | **Tier 2-DB** | in the W3 release if GO |
| **G2** | One "compressor running" truth for the D5 accumulator + the short-cycle producer | G0-Q7 / Q8 (each consumer gated separately) | **Tier 2-DB** (D5 writer input; the one live HVAC anomaly metric; the rename changes the persisted `type`) | in the W3 release if GO |
| **G3-a** | Reset-vs-nudge → maybe turn `ac_reset` OFF | G0-Q9 (indicative) | config (operator action) | no code |
| **G3-b** | Refrigerant / airflow drift alerts | G0-Q5/Q6 + citable limits | — | **PARK** + config (template sensors, operator Q) |
| **G3-c** | `filter_remaining` NM | operator question | Tier 1 if chosen | only if chosen |

**One build branch, one release.** Every group that passes its gate ships together, reviewed at Tier 2-DB (three framing-disjoint reviews) plus live validation and a README write-back. A group that fails its gate drops out without holding up the release.

---

## 1. Institutional context verified

### 1.1 Prior-art scan: REUSE or BUILD, per piece

| Proposed piece | Verdict | Existing at |
|---|---|---|
| Next price-rise anchor, season- and midnight-safe | **REUSE** | `TOURateEngine.get_next_high_rate_transition` `energy_tou.py:645-687` |
| EC → TOU engine accessor from the predictor | **REUSE** | `hvac_predict.py:1736-1737` + `:1771`; property `energy.py:9172-9175` |
| Existing TOU-anchor display attrs | **REUSE (unchanged)** | `anchor_period` / `anchor_starts_in_minutes` `hvac_predict.py:1765-1793` (L1) |
| Legacy fallback anchor when there's no engine | **REUSE** | `PEAK_HOUR_START = 14` `hvac_predict.py:52` |
| Pre-cool window lead | **NEW constant** `ENERGY_PRECOOL_LEAD_HOURS = 4`, replacing `ENERGY_PRECOOL_HOUR_START = 10` (`hvac_const.py:143`) → DELETE | grep: no lead-hours field exists |
| Skip-reason observability | **REUSE** | `_pre_cool_skip_reason` `hvac_predict.py:114`, `:707-758`; exposed `hvac.py:6708` |
| Window display attrs `precool_window`, `precool_anchor_source` | **NEW attrs** (display; the Live oracle needs them) | grep `precool_window`: 0 hits |
| SPAN kW read (staleness, W→kW, rejects kWh counters) | **REUSE** | `_read_kwh_rate` `hvac_override.py:4618-4669`; sibling reader `_carrier_zone_span_kw` `hvac.py:6895` |
| Tri-state compressor predicate (running / not / unknown) | **REFACTOR-EXTRACT** from `_zone_is_actively_cooling` `hvac_override.py:1915-1963` (L4). Gate 4 becomes `tri is RUNNING` (unknown→False, byte-identical); D5/SC map unknown→fallback or drop | one predicate, no hand copy |
| Threshold for "running" | **REUSE** | `AC_ACTIVELY_COOLING_KW_MIN = 0.5` `hvac_const.py:818` (= `CARRIER_BLIND_CORROBORATION_KW_THRESHOLD` `:1391`) |
| Per-zone SPAN entity | **REUSE** | `ZoneState.ac_load_sensor` `hvac_zones.py:160`, populated `:457-512` |
| D5 accumulator | **REUSE (input swap)** | `_accumulate_zone_runtime` `hvac.py:5709-5772`, caller `:2147` |
| Short-cycle producer + listener install | **REUSE (source swap, cooling)** | `_install_short_cycle_listeners` `hvac.py:6058-6095` (latch `:819`, `:6070`, `:6087`); callback `:6097-6210`; rollover `:6240-6370` |
| Orphan-baseline cleanup (the rename's reset mechanism) | **REUSE** | `AnomalyDetector.load_baselines` `coordinator_diagnostics.py:1303-1348` |
| Probe patterns | **REUSE** | `_high_draw_time_s_7d` `hvac_override.py:1438-1506`; `scripts/probes/carrier_blind_episode_detector.py`, `hvac_cycle_duration_probe.py` |
| Equipment-health anomaly home | **NOT BUILT** (G3-b parked). If ever revived: the HVAC `AnomalyDetector` (`hvac.py:1621-1632`), not `SAFETY_METRICS` (`safety.py:939-941`) — see the `hazard_trigger_frequency` precedent `safety.py:933-938` | — |

**Zero new tables, signals, config-flow fields or entities.** Additions: one constant, two display attrs, one extracted tri-state helper, one metric rename.

### 1.2 Prior planning / audit docs consulted
`PROPOSAL_hvac_equipment_health_observability.md` (full); `AUDIT_bryant_duty_cycle_redundancy_2026_09_17.md` (full; its "ODU Var exists" refuted here); `PLANNING_hvac_d5_reframe_occupancy_gate.md` (§0–§2; v5.103.9 shipped 2026-09-18 — the Q8 window boundary); `AUDIT_hvac_duty_cycle_protection_2026_09_17.md`; `PLANNING_v5.7.x_energy_pre_cool_unification.md`; `PLANNING_ec_precool_delete_and_vacancy_hold_assistive.md`; `PLANNING_hvac_short_cycle_producer.md`; `PLANNING_ac_ramp_pipeline_hardening.md`; `PLANNING_carrier_stale_reload.md`; `PLANNING_hvac_fast_occupancy_response.md`, `PLANNING_hvac_w1_w2_finish.md`, `PLANNING_hvac_enable_custom_preset_ranges.md` (headers; sequencing §7); plan review `docs/reviews/code-review/plan_review_hvac_w3_energy_aware.md`.

### 1.3 Memory bodies pulled
`feedback_wire_in_anchor_mandatory.md`; `feedback_coincidental_equality_masks_concept_split.md`; `reference_hvac_zone_tonnage.md`; plus the index lines for measure-before-build, marginal-benefit, config-first, no-soak and hollow anchors.

### 1.4 Design docs read
`HVAC_ARCHITECTURE_STATE_OF_PLAY.md` (complete). `docs/QUALITY_CONTEXT.md` #7, #33, #51, #53, #62, #63.

### 1.5 Code surveyed end-to-end
`hvac_predict.py:1-340`, `:440-880`, `:1720-1800`; `hvac_const.py:75-169`, `:805-845`, `:1175-1250`, `:1375-1396`; `energy_tou.py:1-120`, `:380-728`; `energy_const.py:15-65`; `energy_battery.py:5384-5403`; `hvac_preset.py:95-117`; `hvac.py:5709-5772`, `:6058-6210`, `:6240-6370`, `:6450-6470`, `:6567-6577`, `:7066-7085`; `hvac_override.py:1438-1506`, `:1905-2012`, `:4257-4270`, `:4618-4688`; `aggregation.py:6500-6540`; `binary_sensor.py:1195-1244`; `coordinator_diagnostics.py:914-1112`, `:1303-1348`; `safety.py:930-941`; `ha_carrier/sensor.py:1-163`, `:660-834`; live `tou_rates.json`; `configuration.yaml` recorder block; entity registry (Carrier).

---

## 2. Live facts this plan rests on

| Fact | Source |
|---|---|
| Live tariff = built-in PEC: **summer** (Jun–Sep) off 00–14 & 21–24, mid 14–16 & 20–21, peak 16–20; **shoulder** (Mar–May, Oct–Nov) off 00–17 & 21–24, mid 17–21; **winter** off 00–05, 09–17, 21–24; mid 05–09, 17–21. No day-type dimension | `tou_rates.json`; `energy_const.py:15-65` |
| Rates: off 0.0435; summer mid 0.0932, peak 0.1618; shoulder/winter mid 0.0864; export = import each period | same |
| HVAC season months are identical to the TOU file's months — two derivations that happen to agree (#63) | `hvac_const.py:1049-1050`; `hvac_preset.py:104-117` |
| Recorder states keep **7 days**; LTS is kept indefinitely for `state_class: measurement`: SPAN `span_panel_ac*_power` from **2025-03-12**, Envoy net/production from **2026-04-11**, static pressure / airflow from 2025-03-12 | `configuration.yaml:12-16`; reviewer live read |
| `energy_history` 180 d; **`timestamp` naive UTC; `hour_of_day` / `day_of_week` / `is_weekend` UTC** (`database.py:2697`, `:2723-2725`); Apr values implausible as kW; `whole_house_energy` NULL in current rows | reviewer live read (H2, M1) |
| SPAN power updates p50 5 s, p99 12–13 s; ≤ 2 gaps > 600 s per zone per 7 d; idle reads 4–12 W (never a steady 0) | reviewer live read (M4) |
| `metric_baselines` (`hvac`, `short_cycle_rate`) `sample_count = 14` on zone_1/2/3, last_updated 2026-09-28 | reviewer live read (M5) |
| Three single-zone Carrier systems: `office_b` (zone_1), `thermostat_bryant_wifi_upstairs` (zone_2), `thermostat_bryant_wifi_backhallway` (zone_3); SPAN `ac1`/`ac_2`/`ac_3` | registry; `carrier_blind_episode_detector.py:5-7` — **G0 re-verifies this by hand** |

---

## 3. G0 — Measurement batch (read-only; runs FIRST)

**Deliverable:** `scripts/probes/hvac_w3_energy_probe.py`, run as `ssh ha "python3 -" < … > <scratch>/w3_probe.out`. It opens both DBs `mode=ro` and prints the path it opened plus the earliest timestamp per source. Results and the fixture go to `docs/planning/AUDIT_hvac_w3_measurements.md` and to the "G0 results" section appended to this doc by the probe agent.

**Mandatory time rule (H2):** every local-hour or local-day bucket is computed from a timestamp converted with `zoneinfo("America/Chicago")` (DST-aware). This applies to recorder `last_updated_ts` / LTS `start_ts` (epoch UTC) and to `energy_history.timestamp` (naive UTC, so attach UTC first). **Never read `energy_history.hour_of_day`, `day_of_week` or `is_weekend`.**

**Fixture first:** hand-build *zone → climate entity → Carrier system prefix → configured `ac_load_sensor` → ODU/IDU/static/filter entities*, and commit it in the audit doc.

| Q | Question (exact) | Data | GO / NO-GO |
|---|---|---|---|
| **Q1a** Engine vs file (the real check) | Evaluate `get_current_period` / `get_next_high_rate_transition` for every hour from 2026-10-01 to 2027-09-30 (including both DST days), using an engine loaded from the live file. Compare against an independent table built from the file's `hours` lists by the probe (not by the engine) | offline (import `energy_tou.py` + the file on the host, or copy both locally) | GO iff 100 % of hours agree and the per-season first-rise hour = 14 (summer) / 17 (shoulder) / 05 (winter). Any disagreement → STOP G1 (fix the engine first, EC thread) |
| **Q1b** Sensor sanity | Over 7 days of `sensor.ura_energy_coordinator_tou_period`: transitions **excluding any whose old state is `unknown`/`unavailable`** (restart artifacts) | recorder states | GO iff every remaining transition lands within **+10 min** of a file boundary (one EC update interval; the 09-28 16:05:28 case passes). Informational only unless it contradicts Q1a |
| **Q2** Window mismatch by season | **Arithmetic from the file:** summer 122 d → 0 h mismatch; shoulder 153 d → window ends 3 h before the 17:00 rise; winter N/A. Against the *true* summer peak (16:00), the window ends 2 h early **by design** | none | informational |
| **Q3** Shoulder value — **two-sided rule** (M1, M2) | **Primary source: LTS.** Per shoulder day in Mar–May + Oct–Nov 2025 and Mar–May 2026 (local days, H2): AC kWh 17–21 from the SPAN `ac1/ac_2/ac_3` hourly means. PV surplus 13–17 and grid-vs-battery at 17–21 from Envoy net/production LTS (2026-04-11 →; 2025 days have AC data only, so they're marked `no_grid_split`). Qualifying day = ≥ 1 h of net export ≥ 0.5 kW inside 13–17 (where Envoy is available) AND ≥ 1 kWh AC draw 17–21. `energy_history` is only a cross-check after the probe prints 5 raw rows plus its unit assumption. **UB** (no-cap upper bound) = Σ AC_kWh(17–21) × (0.0864 − 0.0435). **REAL** = Σ min(AC_kWh(17–21), BANK) × (0.0864 − 0.0435), where BANK = configured `energy_precool_offset` °F (live read) × cooling zones banked × **K kWh/°F·zone** (the probe prints the K it assumes and derives it from summer BANKING excursion days — AC kWh 14–16 on bank days vs matched non-bank days — or states "K assumed 0.5, UNVERIFIED"). **Battery valuation:** a kWh the battery does not spend at 17–21 is valued at the mid rate (export = import, live file) **unless** end-of-evening SOC headroom goes unused (SOC at 21:00 ≥ the next-day off-peak charge target) — the probe prints both | LTS (SPAN, Envoy, battery SOC); `hvac_excursion_events` for K | **NO-GO if UB < $25/shoulder-year** (UB can only ever justify NO-GO). **GO only if REAL ≥ $25/shoulder-year AND ≥ 10 qualifying days.** Otherwise PARK G1, trigger "tariff adds a shoulder peak, or REAL doubles" |
| **Q4** Pre-heat fuel | Answered: gas (`hvac_override.py:1933-1937`) | — | DROP |
| **Q5** Telemetry coverage & freshness, per system | 7 days: state distribution of `*_odu_status` / `*_idu_status`; attribute keys present and non-null fraction **while SPAN ≥ 0.5 kW**; median/p95 gap between value changes while running; age of `*_updated_websocket_at` / `*_updated_all_data_at`; confirm no `*odu_var*` in `states_meta` | recorder | G3-b only ever eligible if all 3 systems carry superheat + discharge + static at ≥ 90 % non-null while running and p95 ≤ 30 min. Recorded either way |
| **Q6** Conditioned stability | Superheat & discharge by (ODU stage × 5 °F outdoor band), 7 days; static pressure from LTS by month | recorder attrs; LTS | Informational for G3-b's revival (≥ 3 buckets with superheat IQR ≤ 4 °F) |
| **Q7** hvac_action vs SPAN vs ODU stage (G2-SC gate) | Per zone, cool mode, 7 days: **blind** minutes (SPAN ≥ 0.5 & hvac_action ≠ cooling); **phantom-run** minutes (SPAN < 0.5 & hvac_action = cooling); short cycles (< 600 s) from hvac_action vs from SPAN crossings; % of hvac_action short cycles overlapped by a SPAN on-cycle < 600 s; SPAN flap (on-cycles < 60 s) and minimum kW across genuine on-cycles; **ODU `Stage N`/`off` vs SPAN agreement %** (L6); count of SPAN `unavailable`/`unknown` episodes that occur mid on-cycle (M4) | recorder states | **Re-source GO if** corroboration < 80 % OR counts differ by > 50 %, **AND** SPAN flap < 5 % of on-cycles (otherwise a hysteresis knob would be needed: STOP and re-plan) |
| **Q8** Does D5 change any outcome? (G2-D5 gate) (H3) | Rows in `ura_activity_log`, action `preset_change`, **`json_extract(details_json,'$.reason') = 'energy_shed_cap_reached'`** (NOT a LIKE match: the same string is a boolean key on every preset_change, `hvac.py:3083`, `:3130`, `:3590`), **window 2026-09-18 → now** (post-v5.103.9; the 221 earlier `runtime_exceeded` rows are pre-occupancy-gate and excluded), count pro-rated to 30 d. **Outcome-changing** = the zone's house-state target preset at that tick was NOT already `away` (e.g. `house_state` ∉ {away, vacation}) **AND** the zone was not fused-empty past the vacancy grace. Also: coast/shed minutes in the window; Q7 blind/phantom minutes inside coast/shed. Side note for the audit (UNVERIFIED as a defect): the 09-26 00:32 rows label a house-away write `energy_shed_cap_reached` on an occupied zone under coast | URA DB | **G2-D5 GO if ≥ 3 outcome-changing fires per 30 d (pro-rated)** OR blind+phantom minutes inside coast/shed > 10 % of coast/shed minutes. Otherwise DROP the D5 half (the reviewer's pre-count: 1 → expected DROP) |
| **Q9** Reset vs nudge (M6) — **indicative** | For every hard reset and every `nudge_started` in `ac_ramp_events` in the **last 7 days only** (SPAN fine-grained states; the LTS arm is dropped because hourly means can't resolve a ≤ 10-min restart): SPAN kW 0–20 min after. A hard reset is a forced mode off→on **by construction** (`_perform_ac_reset`, `hvac_override.py:4257-4260`), so the question is only whether the restart comes back at full draw within 10 min (a forced short cycle) versus a nudge's partial kW drop. **State n** (reviewer: 6 resets, zone_1 ×5, zone_3 ×1) | URA `ac_ramp_events`; recorder SPAN | If n ≥ 10 and ≥ 50 % show off → full-draw restart ≤ 10 min → recommend `ac_reset` OFF. If **n < 10 the verdict is labelled INDICATIVE** and goes to the operator as information only |
| **Q10** Short-cycle baseline state (M5) | **DECIDED by live data:** `sample_count = 14` on all zones → baseline just matured on hvac_action-derived counts → **RENAME** (§5) | — | decided |
| **Q11** Grid-anticipatory seed (L8) | Days in the recorder window (reaches back only to ~09-21; a run before 10-01 cannot include 09-29/30) with `pre_cool_skip_reason == no_pv_surplus` inside 10–14 AND EC forecast high ≥ 90 °F | recorder attrs | Seed only; the card stays parked (June 2027 re-run over the first 30 summer days) |

**Invariant G0 (falsifiable):** the probe never writes either DB. Both connections are `mode=ro`; the only output is stdout. Falsify: any write statement in the script, or a DB mtime change attributable to the probe.

### G0 Acceptance Criteria
- **Verify:** the audit doc contains the fixture plus one results row per Q1a–Q11 with a verdict and raw numbers; every hour bucket is derived with `America/Chicago` (a grep of the script for `hour_of_day` / `is_weekend` / `day_of_week` returns nothing).
- **Verify:** the orchestrator independently re-derives Q3's UB (or Q7's blind minutes for one zone) and it agrees within 10 %.
- **Verify:** the probe prints the earliest timestamp per source.
- **Test / Live:** n/a (read-only; the probe IS the live read).

**Config-first:** n/a. **Marginal benefit:** a few hours of scripting decides three groups.

### G0 results (measured 2026-09-28/29, per plan-review corrections)

**Measured by** the G0 probe agent, 2026-09-28 ~23:00 → 09-29 ~00:30 CDT. Everything was read-only: `?mode=ro` URIs over `ssh ha "python3 -"`, SELECT only, stdout only. Q1a runs locally against the live tariff file, which it reads with `ssh ha cat`. The probes are split one per question rather than a single `hvac_w3_energy_probe.py` (operator instruction for this run). They are in `scripts/probes/hvac_w3_g0_*.py` (fixture, q1_tou_truth, q1_engine_offline, q3_shoulder_value, q5_telemetry, q6_conditioned_stability, q7_action_vs_span, q8_d5_outcome, q9_reset_vs_nudge, q10_baseline_state, q11_grid_anticipatory_seed). They were saved and not committed. The review corrections H1/H2/H3/M1/M2/M6, plus the REV 2 additions L6/M4/L8, are applied. Every local hour or day is derived from the timestamps with `America/Chicago`, and a grep of the probes for the three UTC-derived `energy_history` calendar columns returns nothing. The audit doc `AUDIT_hvac_w3_measurements.md` has **not** been written. These results live here only, as instructed.

**Data caveats, applying throughout:**
1. The recorder `states` table starts at 2026-09-21 04:12 CDT (7 days).
2. The 7-day window contains a **restart storm**: 17 HA starts 09-21 → 09-28, 9 of them on 09-28 alone, and 7 of the 09-28 starts had no preceding stop. Across the three SPAN circuits the recorder holds 249–287 `unavailable` blips per circuit over the window (p50 1 s). Only 15–18 of these fall within 15 min of a restart.
3. **Envoy flapping 09-25 → 09-28** makes recent energy data sparse. In `energy_history`, September has 670 NULL `grid_import` rows. No verdict below depends on September Envoy data: Q3 uses the 2025 and Apr–May 2026 LTS.
4. `energy_history` data quality for Apr–May 2026:
   - 04-01 → 04-11 and 04-20 carry no energy data (solar NULL, grid a false 0.0).
   - 04-12 → 05-06 values are scaled 1/1000 (double-divided) and are rescaled in the cross-check.
   - 05-07 onward are true kW.
   - Timestamps are naive UTC (`database.py:2697`).

**Fixture (hand-built, `hvac_w3_g0_fixture.py`, from `core.config_entries` Zone Manager zones + the entity/device registries + live states):**

| zone | ZM zones | climate entity | Carrier system prefix | configured `hvac_ac_load_sensor` | ODU / IDU / static / filter / outdoor-temp / freshness entities |
|---|---|---|---|---|---|
| zone_1 | Entertainment + Master Suite (merged; same thermostat) | `climate.thermostat_bryant_wifi_studyb_zone_1` | `office_b` | `sensor.span_panel_ac1_power` (SPAN Left) | `sensor.office_b_{odu_status, idu_status, static_pressure, airflow, filter_remaining, outdoor_temperature, updated_websocket_at, updated_all_data_at}` |
| zone_2 | Upstairs | `climate.up_hallway_zone_2` | `thermostat_bryant_wifi_upstairs` | `sensor.span_panel_ac_2_power` (SPAN Right) | `sensor.thermostat_bryant_wifi_upstairs_{same set}` |
| zone_3 | Back Hallway | `climate.back_hallway_zone_3` | `thermostat_bryant_wifi_backhallway` | `sensor.span_panel_ac_3_power` (SPAN Right) | `sensor.thermostat_bryant_wifi_backhallway_{same set}` |

No `*odu_var*` entity exists in `states_meta` or in the registry. All three zones have `hvac_ac_ramp_zone_enabled: true`.

| Q | Result (raw numbers) | Verdict |
|---|---|---|
| **Q1a** Engine vs file | Ran the real `TOURateEngine`, loaded through the production `_from_parsed_data` from the live `tou_rates.json` (validation errors: none), plus the built-in engine. Every hour from 2026-10-01 to 2027-09-30 (8760 h, including both DST days = 25 + 23 h) was checked against (1) a table the probe builds from the file's `hours` lists and (2) a hand-written PEC table. Period + season mismatches: **0/8760** for each of the 4 engine × table pairs. First-rise anchor (`get_next_high_rate_transition` from local midnight), 0/365 mismatches: summer 14:00 × 122 d, shoulder 17:00 × 153 d, winter 05:00 × 90 d | **GO** (G1 not blocked on the engine) |
| **Q1b** Sensor sanity | 216 rows. 32 transitions, 0 of them out of `unknown`/`unavailable`. **32/32 within +10 min** of a file boundary. Lag 1–329 s; the only lag over 30 s is 09-28 16:05:28, during the restart storm. Weekend days behave like weekdays. `tou_file_status` = `ok` on all 204 non-null rows. Cross-check: all 16,725 `energy_history.tou_period` labels (2026-04-01 → 09-29) match the tariff for their **local** timestamp (0 mismatches); on 58 of the 60 Apr–May days the first mid_peak row falls in the 17:00 hour | **PASS** (informational) |
| **Q2** Window mismatch | Arithmetic, confirmed by Q1a's anchor counts: summer 122 d → 0 h; shoulder 153 d → the window ends 3 h before the 17:00 rise; winter N/A | informational |
| **Q3** Shoulder value (LTS primary) | BANK = 2.0 °F × 3 zones × K. The offset is the live attr `energy_precool_offset = -2.0`. **K is ASSUMED 0.5 kWh/°F·zone, UNVERIFIED**, because it could not be derived from summer banking days: only 10 of 83 S12_pre_cool banking excursions start inside [10,14) local (see side-finding 1). Qualifying day = ≥ 1 kWh AC 17–21 AND (where Envoy LTS exists) ≥ 1 h of export ≥ 0.5 kWh in 13–17. **2025 shoulder-year** (spring from 03-12 + fall; 133 of 153 days have AC data; 102 qualifying, all `no_grid_split`): AC 17–21 = 876 kWh on qualifying days. **UB = $37.63 (pro-rated $43.29)**. **REAL(K=0.5) = $12.63 (pro-rated $14.53)**; sensitivity REAL(K=1.0) = $26.55 pro-rated. 2026-spring: 46 qualifying (29 PV-verified), UB $18.14, REAL(K=0.5) $5.59. **Battery valuation:** on PV-verified days the battery discharged 311 of 364 kWh of house use at 17–21, so it serves load and does not export at mid-peak; grid fraction = **0.222**. SOC at 21:00 averaged 49 % and reached ≥ the 80 % charge target on **0/28** days. A battery kWh freed at 17–21 is therefore carried into off-peak recharge, where the price delta is ≈ 0. Valued at the grid share only: **REAL $3.23 (K=0.5) – $5.90 (K=1.0) per shoulder-year**. Cross-check: `energy_history` grid fraction over 17–21 local, 04-11 → 05-31 = 0.228 (within 3 % of LTS) | **NO-GO → PARK G1.** UB ($43) ≥ $25, so the upper bound cannot give NO-GO on its own. REAL ($14.5 at the assumed K, $3–6 on battery-corrected valuation) is < $25, so GO fails. The only scenario reaching $25 values every freed battery kWh at the mid rate with K = 1.0, and the measured SOC headroom contradicts it. Trigger unchanged: the tariff adds a shoulder peak, or REAL doubles |
| **Q4** Pre-heat fuel | Gas (answered) | DROP (unchanged) |
| **Q5** Telemetry coverage/freshness | All 3 systems carry superheat, discharge, suction P, coil T, line voltage, static and blower rpm in `*_odu_status` attrs, non-null **94.5–96.9 % while SPAN ≥ 0.5 kW**. IDU airflow/static non-null 98–99.8 %. Median gap between value changes while running is 5.0 min for every key. p95 gap: superheat 30.2 / 20.0 / 55.1 min (z1/z2/z3), discharge 20.4 / 20.1 / 35.4, static 72.6 / 64.3 / 85.5. `updated_websocket_at` age p95 0 min (max 10). `updated_all_data_at` age p50 31 / p95 108 min. ODU state share (cool mode): off 31–48 %, Stage 1–5 the rest, `unavailable` 2.7 %. IDU is `off` 97 % of the time (it reports furnace status). Caveat: the value-change gap overstates staleness for quantized values, such as integer superheat that doesn't move | **G3-b gate FAIL** (static p95 > 30 min on all 3; superheat on z1/z3; discharge on z3). G3-b stays **PARK** (unchanged) |
| **Q6** Conditioned stability | Superheat IQR ≤ 4 °F (n ≥ 30 samples while SPAN ≥ 0.5 kW, bucketed by stage × 5 °F OAT band) in **15 / 11 / 10 buckets** for z1/z2/z3 (36 total). Superheat medians 14–20 °F. Discharge IQR 1–35 °F, widest on z3 at Stage 5. Static pressure LTS monthly median (psi, hourly means including idle hours): z1 went 0.0079 (2026-04) → **0.0151** (2026-09), against a flat ~0.0095 through summer 2025. z2 and z3 show no comparable trend | **Informational.** The ≥ 3-bucket threshold is met, contrary to the plan's expectation, but on 7 days of autocorrelated 5-min samples from one season. That is not enough to baseline drift. G3-b stays PARKed (its trigger also needs a full season of LTS + citable limits). The z1 static-pressure rise is a lead worth one line to the operator (z1 `filter_remaining` = 40 %), not a verdict |
| **Q7** hvac_action vs SPAN vs ODU (G2-SC gate) | Cool-mode, 7.8 d. **Blind** (SPAN ≥ 0.5 & action ≠ cooling): 219 / 73 / 117 min = 3.0 / 1.1 / 2.7 % of SPAN-on. **Phantom** at 0.5 kW: 883 / 1088 / 1526 min = 10.9 / 14.4 / 26.9 % of action=cooling. However, the time share of action=cooling with SPAN in 0.3–0.5 kW is 0 / 11.5 / 23.8 %, and with SPAN < 0.05 kW (truly off) it is 10.7 / 2.8 / 2.8 %. So **zones 2/3 run their low stage at 0.3–0.5 kW, inside the 0.5 kW threshold.** Short cycles (< 600 s): hvac_action 4 / 5 / 15 vs SPAN@0.5 30 / 329 / 362. Corroboration 100 / 40 / 100 %. Counts differ 87 / 98 / 96 %. **SPAN flap (on-cycles < 60 s) at 0.5 kW: 2.6 / 58.7 / 58.5 %**. At 0.2 kW: 13.8 / 3.3 / 1.4 % (no single threshold is < 5 % on all zones). **ODU `Stage N` vs SPAN ≥ 0.2 kW agreement: 98.2 / 98.9 / 98.7 %** (vs ≥ 0.5: 98.2 / 90.9 / 86.3 %). **SPAN `unavailable` mid on-cycle: 172 / 177 / 117 episodes in 7 d** (p50 1 s, p90 4–5 s; only 15–18 per circuit are near a restart), comparable to the 115–145 real on-cycles per zone | **NO-GO as specified → STOP and re-plan G2-SC.** The first clause is met (counts differ > 50 %), but flap at the 0.5 kW threshold is 58 % on z2/z3 (≫ 5 %). The re-plan also needs: (a) a per-zone or hysteretic threshold, a new knob on the ladder; (b) a grace period for SPAN `unavailable` blips, because REV 2's M4 rule "SPAN unavailable ⇒ drop `on_since`" would discard most cycles; (c) a look at the ODU stage signal, which agrees with SPAN about as well as a 0.2 kW threshold does |
| **Q8** Does D5 change an outcome? (G2-D5 gate) | Keyed on `json_extract(details_json,'$.reason')='energy_shed_cap_reached'`, window ≥ v5.103.9 (2026-09-18 05:16 UTC, 11.0 d; 221 legacy `runtime_exceeded` rows excluded): **3 fires. Outcome-changing: 1** (09-20 23:00Z zone_3, home_evening, coast). The two 09-26 00:32Z rows (zone_1, zone_2) had `house_state=away`, so the zone was already going away. **Pro-rated 2.7 / 30 d** (< 3). The occupancy gate logged 61 suppression rows (`energy_shed_cap_deferred_occupied`) in the same window. Coast/shed: 1905 coast min, 0 shed min, over 7 d. Blind + phantom inside coast at 0.5 kW: 984 min = 17.2 % of zone-coast minutes. **Excluding the Q7 low-stage band, blind + truly-off phantom = 452 min = 7.9 %** | **DROP G2-D5.** The count clause fails (2.7 < 3). The second clause reads 17.2 % literally, but 9.3 points of it are low-stage running that a 0.5 kW SPAN predicate would *mis*-credit (Q7), so swapping D5 onto it would add error rather than remove it. The corrected disagreement is 7.9 % < 10 %. **Orchestrator ruling requested** on reading clause 2 as corrected. D5 retirement → W4 sweep (KEEP + DOCUMENT). Side note (UNVERIFIED as a defect): the 09-26 rows write `energy_shed_cap_reached` on zones with `any_room_hvac_occupied=true` under coast with the house away |
| **Q9** Reset vs nudge | 7-d SPAN arm only (short-term stats and states both start 09-21). **Hard resets n = 6** (zone_1 × 5, zone_3 × 1; 9 older resets not assessable). All 6 reach < 0.05 kW, as they must by construction. Off → full-draw restart (≥ 0.8 × pre-draw) within 10 min of OFF: **2/6 = 33 %**. OFF → restart times 414–894 s (n = 4 that restarted within 20 min). **Nudges n = 106:** 86 % reach < 0.05 kW within 20 min and **54 % show off → full-draw restart ≤ 10 min**. The nudge premise ("partial kW drop without reaching zero") is contradicted, though natural cycling within 20 min is a confound. 30-d totals: 13 resets on zone_1, 2 on zone_3, 0 on zone_2 | **INDICATIVE only (n = 6 < 10)**, operator information. At 33 % there would be no `ac_reset` OFF recommendation even at n ≥ 10. Worth noting to the operator: nudges look like they stop the compressor more often than resets force a short cycle |
| **Q10** Baseline state | `short_cycle_rate` sample_count = **14** on zone_1/2/3 (means 1.64 / 1.00 / 2.29, std 2.61 / 0.76 / 2.02, last_updated 2026-09-28 05:04Z). House scope = 0 | Decided (RENAME), but moot while G2-SC is STOPped (Q7) |
| **Q11** Grid-anticipatory seed | Recorder window 09-21 → 09-28 (09-29/30 not yet reached). The HVAC mode sensor has no forecast attr, so the source is `sensor.ura_energy_coordinator_weather_apparent_forecast_high`, an **apparent** high. `no_pv_surplus` held on 506–516 ticks inside 10–14 **every day**, and the apparent forecast high was 96–98 °F → **8/8 seed days** | Seed only. `EC-GRID-ANTICIPATORY-PRECOOL-GAP-1` stays parked (June 2027) |

**Group verdicts:**

| Group | Verdict |
|---|---|
| G1 | **PARK** (Q1a GO, Q3 NO-GO) |
| G2-SC | **STOP / re-plan** (Q7 flap) |
| G2-D5 | **DROP** (Q8) |
| G3-a | No recommendation (Q9 indicative, 33 %) |
| G3-b | **PARK** (Q5 gate fail) |
| G3-c | Unaffected (operator question) |

The W3 release, as specified, ships nothing unless G2-SC is re-planned.

**M3 reader triage:** covered by §5.1 above, with no probe needed. Besides D5 and the short-cycle producer, the other `hvac_action`-as-"plant running" readers are:
- `zone_call_frequency` (`hvac.py:6458-6463`)
- `HouseSystemDemandSensor` (`aggregation.py:6510-6514`, `:6529-6532`)
- room `HVACCooling/HeatingBinarySensor` (`binary_sensor.py:1207`, `:1242`)
- `_perform_ac_reset` `original_action` (`hvac_override.py:4260`)
- Carrier stale-reload corroboration (`hvac.py:7078-7083`)

**Side-findings (UNVERIFIED mechanisms, observations verified):**
1. **S12_pre_cool "banking" borrows run outside the Path A window.**
   - Of 83 `hvac_excursion_events` rows (kind `banking`, site `S12_pre_cool`, since 08-26), only 10 start inside [10,14) local. They start at every hour of the day, including 18–20 CDT, which is summer **peak**.
   - Live example: `sensor.ura_hvac_coordinator_governed_thermostat_borrows` showed an active zone_1 banking borrow from 09-25 18:12 to 20:12 CDT. At the same moment the mode sensor read `pre_cool_active=false` and `pre_cool_skip_reason=outside_window`.
   - This bears directly on G1 and on the cost story. It needs its own investigation and card (adjacency sweep first).
2. **Arrester Gate 4 misreads low-stage running on zones 2/3.** Gate 4's 0.5 kW threshold sits inside the zone 2/3 low-stage draw band (Q7), so Gate 4 reads those zones as "not actively cooling" during 11.5 % / 23.8 % of their action=cooling time. This may be benign for an arrester concerned with high draw. Recorded for the Gate-4 owner; not in W3 scope.
3. **Carrier timestamp attributes.** `updated_all_data_at` refreshes about every 2 h (age p95 108 min), while `updated_websocket_at` is continuous. Any freshness gate should use the websocket timestamp.

**Disjoint check:** the Q3 grid fraction from `energy_history` (0.228) agrees with the Envoy LTS (0.222) within 3 %. The orchestrator's own re-derivation of Q3's UB or Q7's blind minutes, as the G0 acceptance criteria require, is still outstanding.

---

## 4. G1 — TOU-derived pre-cool window

### Problem (producer check)
`_should_energy_precool` gates on `ENERGY_PRECOOL_HOUR_START (10) <= hour < PEAK_HOUR_START (14)` (`hvac_predict.py:715`). The value 14 is used literally at **five decision/display sites** that move together (Bug Class #33):
1. `:252` reboot pickup (`hour >= 14` → triggered_today)
2. `:308-311` likelihood (display; also `PEAK_HOUR_END=19`, wrong vs the 20:00 peak end)
3. `:608` end-of-pre-cool flag clear
4. `:715` window gate
5. `:728` re-engagement `hour < 14`

**Left alone (L1):** `:1749-1761` `forecast_peak_time_iso`. It is paired with `forecast_peak_outside_f` (outdoor-temperature peak), a different concept from the TOU anchor. Moving it would fuse two concepts (#63 inverted). The TOU anchor is already published by the same function as `anchor_period` / `anchor_starts_in_minutes` (`:1765-1793`). `test_v4_6_9_hvac_intent_attrs.py:348-357` pins 14 there and must stay green unchanged.

### Design
- New predictor helper `_precool_anchor(now) -> datetime`: the first off_peak→(mid_peak|peak) transition of `now`'s **local day**, via `tou.get_next_high_rate_transition(start_of_local_day(now))` (`energy_tou.py:645`). `start_of_local_day` = local midnight built with `dt_util` (DST-aware; the engine walks by `timedelta(hours=1)` on aware datetimes, which DST tests must pin). Fallback to `now` at `PEAK_HOUR_START`:00 if the engine is absent, returns `None`, or returns a transition on another local date.
- Window = `[anchor − ENERGY_PRECOOL_LEAD_HOURS h, anchor)`. Live tariff: **summer [10,14) as today**, shoulder [13,17). The season **gate** stays HVAC's; the window follows the tariff (tested independent, #63).
- Sites 1, 3, 4, 5 compare against the anchor datetime. At site 2, `PEAK_HOUR_END` is replaced by "engine current period ∈ {mid_peak, peak}" (display).
- New display attrs `precool_window` (e.g. `"13:00-17:00"`) and `precool_anchor_source` (`tou` | `fallback`) next to `pre_cool_skip_reason` (`hvac.py:6708`).
- `ENERGY_PRECOOL_HOUR_START` **DELETED**; `PEAK_HOUR_START` **KEPT** as the fallback.

### Knob ladder
| Number | Name | Rung | Why |
|---|---|---|---|
| 4 h | `ENERGY_PRECOOL_LEAD_HOURS` (`hvac_const.py`) | 1 | Set-once; the default reproduces summer exactly; no tuning history. Rung 2 only on operator ask |
| 14 | `PEAK_HOUR_START` (existing) | 1 | Fallback only |
| 2 h | `PRECOOL_LEAD_HOURS` (existing, display) | 1 | Unchanged; now anchor-relative |

### Falsifiable invariant INV-G1
> For every local time t in HVAC cooling season, Path A can fire only if `anchor(t) − 4 h ≤ t < anchor(t)`, where `anchor(t)` = the first off_peak→(mid_peak|peak) transition of t's local day per the TOU engine (14:00 if the engine is absent). Under the live tariff, the set of summer ticks that fire is **identical** to the pre-cycle set, including on DST-change days.

Falsified by: a shoulder fire at 10:00–12:59; a shoulder skip at 14:00–16:59 with `outside_window`; any summer difference from the pre-cycle build; a DST-day anchor off by an hour; any of sites 1/3/4/5 still comparing against the literal 14 when the engine is present.

### Producer / consumer
- **Producer:** TOU engine (verified offline by Q1a). If EC is absent → fallback, labelled.
- **Consumers:** S12 pre-cool writes via `_execute_zone_pre_cool` (BANKING borrows, `duration_s=None` at `hvac_predict.py:1161`, so no lease changes); `_pre_cool_triggered_today`; reboot pickup; display attrs. Nothing outside `hvac_predict.py` reads the window (reviewer re-grep). §9e / D48 untouched.

### Config-first
No knob moves the window. **Code required.**

### Marginal benefit
Summer: zero change. Shoulder: at most REAL (Q3). The hard-coded per-season dict alternative is the same size but tariff-blind. The risky ingredient is the time/season seam (#51 family); containment is the fallback plus boundary and DST tests. **Build only if Q3 REAL ≥ $25/yr. Expected: marginal; PARK plausible.**

### Tier: **Tier 2-DB.**

### G1 Acceptance Criteria
- **Verify:** live tariff: summer 10:00–13:59 fires (other gates met), 14:00 does not; shoulder 13:00–16:59 fires, 10:00 and 17:00 do not.
- **Verify:** engine absent → every season behaves as pre-cycle `[10,14)`, `precool_anchor_source == "fallback"`.
- **Verify:** Sep 30 → Oct 1 uses the next-day table (Oct 1 window 13–17).
- **Verify (L2):** on **2026-11-01** (fall-back, 25-h day) and **2027-03-14** (spring-forward, 23-h day) the anchor is 17:00 local and the window is 13:00–16:59 local.
- **Verify:** discriminating tariff (summer months {5..9}): the May window is [10,14) while the HVAC season is shoulder.
- **Test:** `quality/tests/test_hvac_w3_precool_window.py`: `test_summer_window_identical_to_legacy`, `test_shoulder_window_13_to_17`, `test_no_engine_fallback`, `test_season_boundary_sep30_oct1`, `test_dst_fall_back_2026_11_01`, `test_dst_spring_forward_2027_03_14`, `test_gate_and_window_independent`, `test_reboot_pickup_uses_anchor`, `test_end_flag_clears_at_anchor`, `test_reengage_bounded_by_anchor`. Boundary hours derived from `PEC_TOU_RATES`, not literals. `test_v4_6_9_hvac_intent_attrs.py` unchanged and green. **Wire-in anchors:** each of sites 1/3/4/5 gets a behavioral test driving `HVACPredictor.update()`; a per-site mutation (restore literal 14 / `if False and`) must turn a named test red, recorded in the review doc.
- **Sensor:** `sensor.ura_hvac_coordinator_mode` attrs `precool_window = "13:00-17:00"`, `precool_anchor_source = tou` from 2026-10-01.
- **Live (L3 precondition):** first read the live state of the EC "Energy Saver Pre-Cool" switch and the HVAC pre-conditioning master switch. Both must be ON; `pre_cool_skip_reason` is evaluated only when the gate is on (`hvac_predict.py:560`). Then, on the first shoulder day, a tick at 10:00–12:59 reads `outside_window`, and a tick at 13:00–16:59 with export ≥ 500 W reads anything other than `outside_window`. **Discriminates:** pre-fix reads `outside_window` from 14:00; a silent engine failure shows `precool_window 10:00-14:00` with source `fallback`. Summer identity and DST can only be proven in the suite.

---

## 5. G2 — One "compressor running" truth (D5 accumulator + short-cycle producer)

### 5.1 Reader triage — every `hvac_action`-as-"plant running" reader (M3)
| # | Reader | Site | Trust vs display | Decision |
|---|---|---|---|---|
| 1 | D5 duty accumulator | `hvac.py:5739` | trust (drives the forced-away write) | **SWAP** if Q8 GO; else KEEP (D5 retirement → W4 sweep) |
| 2 | Short-cycle producer | `hvac.py:6136-6171` | trust (only live HVAC anomaly metric) | **SWAP** if Q7 GO |
| 3 | `zone_call_frequency` observation | `hvac.py:6458-6463` | in-memory only, persistence suppressed (`hvac_const.py:1225-1229`) | **KEEP.** It measures the thermostat *call*, which is what `hvac_action` means on this system (per `kanban.data.yaml:11734-11735`: it "tracks the ZONE call, not the equipment"); suppressed; no consumer action |
| 4 | `HouseSystemDemandSensor` | `aggregation.py:6510-6514`, `:6529-6532` | display (MEASUREMENT → LTS) | **KEEP + card** `HVAC-SYSTEM-DEMAND-SPAN-SOURCE-1` (adjacency sweep first). It's a display series whose LTS history would change meaning mid-series; W3 doesn't need it; swapping later is cheap once the tri-state helper exists |
| 5 | Room `HVACCooling/HeatingBinarySensor` | `binary_sensor.py:1207`, `:1242` | display, disabled by default (`:1216`) | **KEEP.** Named for the thermostat state; no consumer |
| 6 | `_perform_ac_reset` `original_action` | `hvac_override.py:4260`, used in a message at `:4370` | display (notification text) | **KEEP** |
| 7 | Carrier stale-reload corroboration | `hvac.py:7078-7083` | trust, but it *detects* hvac_action blindness against SPAN | **KEEP (must stay hvac_action)** — swapping would make the blind detector compare SPAN with itself |

### 5.2 Design
- **Tri-state extraction (L4):** from `_zone_is_actively_cooling` (`hvac_override.py:1915-1963`) extract `_zone_cooling_tristate(zone, now) -> RUNNING | NOT_RUNNING | UNKNOWN` (mode guard fails → NOT_RUNNING; `_read_kwh_rate` None → UNKNOWN; kW ≥ 0.5 → RUNNING, else NOT_RUNNING). `_zone_is_actively_cooling` becomes `return tri is RUNNING`, byte-identical for Gate 4 (unknown→False).
- **G2-D5 (only if Q8 GO):** `hvac.py:5739` credits elapsed time iff `hvac_action == "heating"` (gas; the AC circuit can't see it) OR tri is RUNNING OR (tri is UNKNOWN AND `hvac_action == "cooling"`). Nothing else in D5 changes. Bug Class #21: the caller passes `now_utc` (`hvac.py:2147`); `_read_kwh_rate` subtracts aware-vs-aware (`hvac_override.py:4640`), pinned by a test.
- **G2-SC (only if Q7 GO) — rule chosen (M4): SPAN configured ⇒ SPAN only for cooling.**
  - At install, build `{ac_load_sensor_entity: zone_id}` and subscribe those entities alongside the climate entities (`hvac.py:6058-6095`).
  - SPAN event: `unavailable`/`unknown`/unparseable (either side of the transition) → **drop that zone's cooling `on_since`, book nothing** (mirrors the climate-side drop `hvac.py:6122-6135`). kW crossing 0.5 upward → stamp `on_since`; crossing downward → book a cycle if < `SHORT_CYCLE_THRESHOLD_S`. Same date-straddle rule as today (`:6184-6195`).
  - Climate event for a zone **with** a configured `ac_load_sensor`: cooling edges are ignored; heating edges are processed as today.
  - Zone **without** `ac_load_sensor`: exactly today's behaviour.
  - **Cost (L5):** ~50 k callbacks/day (3 sensors × one per ~5 s). The handler must be O(1): dict lookup, float parse, threshold compare. No per-event INFO log; debug only on booked cycles. The `_short_cycle_listener_installed` latch (`hvac.py:819`, `:6070`, `:6087`) means an `ac_load_sensor` configured later is picked up only after a restart or reload. This is documented, not fixed (zone config changes already reload the coordinator path).
- **Rename (M5) — `short_cycle_rate` → `compressor_short_cycle_rate`.** Why a rename rather than an in-place reset: the metric's *definition* changes (SPAN on-cycles, not thermostat calls), and a new name makes the persisted `anomaly_log.type` honest. The existing orphan cleanup deletes the old baseline rows on load with no new DB code. **Touch-sites, each with a mutation drill** (revert one site, a named test must turn red): `hvac_const.py:1182` (`HVAC_METRICS`); `hvac.py:1632` (per-metric min-samples override key); `hvac.py:6286` (`clear_active_anomalies_filtered` metric_name); `hvac.py:6295` (`record_observation` name); `hvac.py:6326` (`AnomalyEvent.type = "hvac.compressor_short_cycle_rate"`); comment notes `hvac_const.py:1207-1234`; tests that assert the old name (builder greps `quality/tests` for `short_cycle_rate` and lists them in the build report). **Accepted cost:** the baseline that matured on 2026-09-28 (`sample_count=14`) is discarded, so the only live HVAC anomaly metric is in `learning` for **~14 days** after deploy (`HVAC_SHORT_CYCLE_MIN_SAMPLES=14`, 1 obs/day/zone). That is acceptable because the old baseline learned the contaminated signal. If G2-SC is NO-GO, **no rename happens**.

### Knob ladder
No new numbers. REUSE `AC_ACTIVELY_COOLING_KW_MIN` 0.5, `AC_KWH_SENSOR_STALENESS_S`, `SHORT_CYCLE_THRESHOLD_S` 600, `HVAC_SHORT_CYCLE_MIN_SAMPLES` 14 (all rung 1). If Q7 shows SPAN flap ≥ 5 % → STOP and re-plan (a hysteresis number would be needed).

### Falsifiable invariant INV-G2 (restated, M4)
> (a) D5: in a cooling-capable mode, a tick is credited iff `hvac_action == heating`, OR the tri-state is RUNNING, OR (tri-state UNKNOWN and `hvac_action == cooling`). (b) Short-cycle, for a zone **with** a configured `ac_load_sensor`: a cooling on-cycle is opened and closed **only** by SPAN crossings of 0.5 kW. An `hvac_action` edge never opens or closes one. A SPAN `unavailable`/`unknown` drops any open cooling `on_since` and books nothing. (c) For a zone **without** an `ac_load_sensor`, D5 and short-cycle behaviour equals the pre-cycle build. (d) Gate 4 verdicts are unchanged for every input.

Falsified by: a blind tick not credited; a phantom tick (fresh SPAN 0.1 kW, hvac_action cooling) credited; a cycle booked from an hvac_action edge on a SPAN zone; a cycle booked across a SPAN `unavailable` gap; any Gate 4 verdict change.

### Producer / consumer
- **Producer:** SPAN circuit power (local; p99 update 13 s; idle 4–12 W, so it never goes stale at idle). Health comes from Q7 (flap, kW floor, mid-cycle unavailability). Zone↔SPAN mapping from the G0 fixture.
- **Consumers of `runtime_exceeded`:** forced-away `energy_shed_cap_reached` (`hvac.py:3326-3334`); ledger/attr keys (`hvac.py:2936`, `:3083`, `:3130`, `:3590`, `:3650`); `zone_presence_state` (`:6030`); `hvac_zones.py:1110`.
- **Consumers of the short-cycle metric:** `AnomalyDetector` → `anomaly_log` (type string renamed) → HVAC anomaly sensor severity (`hvac.py:6567-6577`) → NM path.

### Config-first
No setting re-sources D5 or short-cycle. If Q8 shows D5 is inert: no code and no config change (D5 costs nothing inert; retirement → W4).

### Marginal benefit
- **G2-D5:** acts only in coast/shed on unoccupied zones, which the 5-min vacancy grace already retreats. Reviewer pre-count: 1 outcome-changing fire. **Expected DROP.**
- **G2-SC:** cleans the only metric that can page about a compressor fault. The cost is one listener extension, a rename, and 14 days of re-learning. GO only if Q7 supports it.

### Tier: **Tier 2-DB.**

### G2 Acceptance Criteria
- **Verify:** blind tick (fresh SPAN 2.7 kW, hvac_action idle) → D5 credits; phantom tick (fresh SPAN 0.1 kW, hvac_action cooling) → no credit; stale SPAN → falls back to hvac_action; heating with SPAN 0 → credited.
- **Verify:** SPAN 0.01→2.7→0.01 kW over 300 s books one cycle; an hvac_action cooling→idle→cooling flicker during continuous SPAN ≥ 0.5 books none; SPAN →`unavailable` mid-cycle then back → nothing booked and `on_since` cleared; a zone without `ac_load_sensor` behaves exactly as pre-cycle.
- **Verify:** Gate 4 verdict table (mode × kW × None) is identical before and after the extraction.
- **Test:** `quality/tests/test_hvac_w3_compressor_truth.py`: `test_d5_credits_span_running_when_blind`, `test_d5_ignores_phantom_cooling`, `test_d5_unknown_falls_back`, `test_d5_heating_via_hvac_action`, `test_d5_utc_now_vs_local_last_updated`, `test_sc_span_edges_book_cycle`, `test_sc_hvac_action_flicker_ignored_on_span_zone`, `test_sc_span_unavailable_mid_cycle_drops_on_since`, `test_sc_no_span_zone_unchanged`, `test_gate4_semantics_unchanged`, `test_rename_orphan_baseline_deleted_on_load`. **Wire-in anchors:** drive `_accumulate_zone_runtime` and the real listener callback, and neuter each call site plus each rename site (one at a time) → a named test turns red.
- **Sensor:** HVAC anomaly sensor lists `compressor_short_cycle_rate` per zone with learning status `learning` after deploy.
- **Live:** after the first local-midnight rollover, `metric_baselines` has `compressor_short_cycle_rate` zone_1/2/3 `sample_count = 1` and **no** `short_cycle_rate` rows. **Discriminating:** over the first 7 days, the per-zone counts computed by the probe from SPAN equal URA's booked counts within ±1/day. Under the old producer, URA tracks hvac_action cycles instead (the Q7 gap). Accepted: the anomaly sensor shows `learning` for ~14 days.

---

## 6. G3 — Equipment health (mostly config / park)

| Item | Decision | Why |
|---|---|---|
| **G3-a Reset vs nudge** (P2) | **CONFIG ONLY, indicative.** If Q9 has n ≥ 10 and ≥ 50 % forced full-draw restarts → recommend `switch.ura_hvac_coordinator_ac_reset` OFF. With n < 10 → information for the operator only. Nudges stay ON. | The decision is an existing switch |
| **G3-b Drift / hard-limit alerts** (P1) | **PARK** + config: 9 UI template sensors (`state_class: measurement`) for `suction_superheat`, `discharge_temperature`, `line_voltage` × 3 systems, so LTS accrues. **Revival trigger:** ≥ 1 full cooling season of LTS, AND Q6 re-run shows ≥ 3 stable buckets, AND citable manufacturer limits | 7 days of attribute history; unverified limits; rare-fire path; the Infinity board already protects the unit |
| **G3-c filter_remaining NM** | **OPERATOR QUESTION.** Recommendation: DROP (the Bryant app reminds). If kept: Tier 1 threshold NM (not an anomaly metric), knob `FILTER_REMAINING_ALERT_PCT = 10`, **rung 2** (options flow, set-once, L7) | The operator said "add to SC" on 2026-09-17 |
| **P3 energy attribution** (rest) | **PARK.** Trigger: a proposal to tune vacancy grace or D5 caps on energy grounds | No consumer today |

**INV-G3 (only if G3-c is built):** at most one NM per (system, downward crossing of the threshold); zero NMs while `*_filter_remaining` is unavailable.

**G3 Acceptance Criteria:**
- **Verify:** audit Q9 row states n, per-event trajectories, and INDICATIVE/decisive.
- **Live (G3-a, if the operator turns `ac_reset` off):** `ac_ramp_events` has zero hard-reset rows over the next 7 days while `nudge_started` continues (one-shot query at disposition).
- **Live (G3-b config):** 9 template sensors exist with `state_class: measurement`, and `statistics_meta` rows appear within 1 h.

---

## 7. Sequencing, file overlap, and worktrees
1. **G0** is running now (probe agent; results appended below).
2. **Re-check** this REV 2 against the G0 results (the reviewer's H/M items closed); record per-group GO/NO-GO in a "G0 verdicts" line under the results.
3. **Build G1 + GO halves of G2 + G3-c (if chosen) on one branch.** `hvac_predict.py` overlaps Batch A's `HVAC-PRECOOL-RESTORE-HEAT-MINUS7-1` → build G1 after Batch A merges. `hvac.py` / `hvac_override.py` overlap Batches B/C → worktree `.claude/worktrees/<agent-id>-w3`, rebase before review.
4. **One release**, Tier 2-DB review, framings: **A** correctness and edge cases (window arithmetic, DST, tri-state mapping, SPAN unavailability); **B** time seams and cross-coordinator (EC engine dependency, season boundary, reboot pickup, D5 writer, rename/orphan cleanup on restart); **C** test authority by real per-site mutation (four G1 sites, two G2 call sites, the extraction, five rename sites).
5. **Post-deploy:** live validation, README write-back, and a state-of-play update in the same commit (pre-heat/gas note, ODU-Var-absent note, G2 signal change and the metric rename).

## 8. Non-goals (explicit)
- No change to the summer pre-cool window; no anchoring on the true peak (16:00).
- `forecast_peak_time_iso` is untouched.
- No grid-anticipatory pre-cool. No pre-heat change (gas).
- No change to the TOU engine or tariff file. No fix for `energy_history` UTC columns (carded separately).
- No change to borrow semantics, §9e gates, W1-B rulings (D48 et al.).
- No change to D5 caps, occupancy gate, coast/shed, or the D5 enable switch.
- Gate 4 verdicts are unchanged (the extraction is behaviour-neutral).
- Readers 3–7 in §5.1 are not changed.
- No learned anomaly baselines, no SafetyCoordinator metrics, no `max_samples` change, no HVAC-ANOMALY-BLIND residual-A change.
- No ODU Var or ODU-stage consumption. No Carrier reload change. Nudges stay ON.

## 9. Supersession (pre-planned three-bucket triage)
| Item | Bucket | Reason |
|---|---|---|
| `ENERGY_PRECOOL_HOUR_START` `hvac_const.py:143` | **DELETE** (if G1 ships) | Replaced by anchor − lead; footgun |
| `PEAK_HOUR_START` `hvac_predict.py:52` | KEEP + DOCUMENT | Fallback anchor, and still read by `forecast_peak_time_iso` |
| `PEAK_HOUR_END` `hvac_predict.py:53` | DELETE if G1 ships | Its one reader moves to the engine period; wrong value |
| `OFF_PEAK_END_HOUR` / pre-heat window | KEEP + DOCUMENT | Gas heat; revisit only if heat becomes a heat pump |
| `short_cycle_rate` baseline rows | DELETE via the existing orphan cleanup (if G2-SC ships) | Learned on the contaminated signal |
| `_gate4_legacy_predicate` `hvac_override.py:1965` | KEEP | Rollback path |

## 10. Operator questions
1. **G3-c filter alert:** DROP (recommended) or a small URA NM at ≤ 10 %?
2. **G3-b config step:** OK to create the 9 UI template sensors?
3. **Pre-cool lead hours:** module constant (recommended) or a set-once options field?
4. **G3-a:** if Q9 is decisive (n ≥ 10), are you willing to turn `ac_reset` OFF as config? At today's n≈6 it will be indicative only.
5. **G2-SC rename:** accept ~14 days of `learning` on the HVAC anomaly sensor after deploy (the matured baseline learned the contaminated signal)?

## 11. Suggested QUALITY_CONTEXT bug class (suggestion only — not applied)
**"UTC-bucketed analytics column."** A DB column named like a local-time dimension (`hour_of_day`, `day_of_week`, `is_weekend`) is populated from `utcnow()`, while its sibling `timestamp` is naive UTC. Any probe, analytics query or model feature that buckets by it is silently shifted 5–6 h (by DST), and a weekday/weekend split is wrong for the evening hours that cross UTC midnight. Exemplar: `energy_history` (`database.py:2697`, `:2723-2725`); live row `2026-09-29T04:05Z hour_of_day=4` = 23:05 CDT, and Apr–May rows at `hour_of_day ∈ {17,22}` split evenly between off_peak and mid_peak. **Detection:** grep writers of `hour_of_day|day_of_week|is_weekend` for `utcnow`. **Fix pattern:** populate from `dt_util.now()` (local), or drop the column and derive at read time with a named timezone; consumers must never trust the column name. Sibling of #11 / #21 / #51. The audit of existing readers is carded (consolidation table).

## CORRECTION 2026-09-29: the units ARE variable-speed (operator)
The REV 2 claim "no ODU Var entity exists, so D5-REGROUND-ON-ODU-VAR is dropped as written" is WRONG in its inference. All three outdoor units report `type: proteusac` (Carrier's variable-speed Infinity ODU) on `sensor.thermostat_bryant_wifi_upstairs_odu_status`, `sensor.thermostat_bryant_wifi_backhallway_odu_status` and `sensor.office_b_odu_status`. ha_carrier only creates `OutdoorUnitVarSensor` for `outdoor_unit_type in ["varcaphp","varcapac"]` (`ha_carrier/sensor.py` ~90), so `proteusac` gets no Var % entity. That is an integration gap, not a hardware fact. The ODU status state carries the stage directly ("Stage 1..5" / "off"). **Re-plan G2 around ODU stage as the running signal** (G0: 98-99 % agreement with SPAN ≥ 0.2 kW). This removes the single-kW-threshold flap on zones 2/3 and gives arrester Gate 4 (`ARRESTER-GATE4-LOW-STAGE-THRESHOLD-1`) a stage-aware predicate.
