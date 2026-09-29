# PLANNING — HVAC W3 "Energy-aware HVAC" → ONE build group: ODU-stage running predicate

**Date:** 2026-09-29 · **Author:** ura-planner · **Status:** REV 3. Re-scoped to one build group per the operator ruling of 2026-09-29 ("Agree with recommendations"). It needs ONE adversarial plan review (Tier 2+ rule) before build. Build after Batch B merges.
**Build card:** `ARRESTER-GATE4-LOW-STAGE-THRESHOLD-1` (`docs/planning/kanban.data.yaml:30392`). **Workstream:** `HVAC-W3-ENERGY-AWARE` (`:2338`).
**Read-first satisfied:** `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` read completely, including §10 and §11. Nothing below re-asserts a §10 claim.
**Version:** unassigned. If shipped, it is a PATCH bump (`5.103.x`).

### Revision note — REV 3 (2026-09-29)
- **Scope is ONE build group (§5):** a per-zone tri-state running predicate (RUNNING / OFF / UNKNOWN) read from the Carrier ODU stage (`*_odu_status` = `off` / `Stage N`; units are variable-speed `proteusac`, see CORRECTION at the end). It is wired into **arrester Gate 4** and into the **short-cycle producer**; the producer's metric is renamed `compressor_short_cycle_rate`.
- **Adjudicated on the board, not re-decided here:**
  - G1 pre-cool window: PARKED.
  - D5 re-ground: CLOSED/dropped.
  - Drift alerts and template sensors: PARKED.
  - Filter alert: DROPPED.
  - They are listed with their revival triggers in §8.
- **REV 2 §5.1 triage carried forward:** every other `hvac_action` reader keeps its current input.
- **SPAN-kW is out as the short-cycle source:** G0-Q7 found 58 % flap on zones 2/3 at 0.5 kW, no single threshold fits all zones, and SPAN went unavailable 117–177 times mid-cycle in 7 days. ODU stage replaces it. SPAN remains only as Gate 4's fallback when the stage is UNKNOWN, so today's Gate 4 behaviour is the fallback.
- **New mini-probe M0 (§4)** measures, before the build: ODU entity availability, stage-update cadence, the Gate 4 flip replay, and stage-derived short cycles. It sets the stale and grace numbers.
- **New finding (§5.2 Gate 4):** after a Gate-7 failure the arrester keeps `last_overshoot_started` (only Gates 4 and 6 clear it, `hvac_override.py:4136`, `:4192`). Low-stage ticks that today fail at Gate 4 would therefore reach Gate 7 and leave the Gate 8 timer running. M0-P4 measures whether that changes any nudge dispatch.
- The REV 2 rationale for sections now superseded is kept only where cited. The G0 spec (§3), the G0 results and the CORRECTION section are intact and unedited.

### Revision note — REV 2 (2026-09-28), history
REV 2 addressed plan review `docs/reviews/code-review/plan_review_hvac_w3_energy_aware.md`:
- H1: Q1 split.
- H2: America/Chicago local-time rule.
- H3: Q8 keying and window.
- M1/M2: Q3 on LTS, two-sided rule.
- M3: 7-reader triage.
- M4: SPAN-only rule.
- M5: rename decided.
- M6: Q9 indicative.
- LOWs L1–L8.

---

## 0. Headline

G0 ran on 2026-09-28/29 (results in §3). It parked or dropped every group except one:
- **The pre-cool window** is worth about $3–15/yr (bar $25): PARK.
- **Re-grounding D5** changes about 2.7 outcomes per 30 d (bar 3): DROP.
- **Equipment drift alerts** fail the telemetry-freshness gate: PARK.
- **A SPAN-kW short-cycle source** flaps 58 % on zones 2/3: STOP.

What survives is the finding the card is named for. The arrester's Gate 4 "is the AC running" test (SPAN ≥ 0.5 kW) reads zones 2/3 as not running during their 0.3–0.5 kW low stage: 11.5 % and 23.8 % of their cooling-call time (G0-Q7). The short-cycle producer's `hvac_action` source disagrees with the compressor on 87–98 % of cycle counts. The ODU stage agrees with SPAN ≥ 0.2 kW on **98.2 / 98.9 / 98.7 %** of cool-mode time. It is a clean on/off signal with no threshold, and one predicate fixes both consumers.

### Consolidation (final, REV 3)
| Card | Disposition (board) | Here |
|---|---|---|
| `ARRESTER-GATE4-LOW-STAGE-THRESHOLD-1` | **THE build group** | §5 |
| `HVAC-PRECOOL-WINDOW-TOU-DERIVED-1` | PARKED | §8 |
| `HVAC-D5-REGROUND-ON-ODU-VAR-1` | CLOSED (dropped) | §8 |
| `HVAC-EQUIPMENT-HEALTH-OBSERVABILITY-1` | PARKED (drift / template sensors); filter DROPPED | §8 |
| `EC-GRID-ANTICIPATORY-PRECOOL-GAP-1` | parked (June 2027) | §8 |
| `HVAC-BASELINE-MAXSAMPLES-1`, `HVAC-ANOMALY-BLIND-1` residual A | W4, separate | §8 |

---

## 1. Institutional context verified

### 1.1 Prior-art scan: REUSE or BUILD, per piece
| Piece | Verdict | Existing at |
|---|---|---|
| Gate 4 predicate + mode Select (legacy / shadow / live) + divergence latch | **REUSE (extend the live-mode body)** | `_zone_is_actively_cooling` `hvac_override.py:1923-1971`; `_gate4_is_ok` `:2020-2040`; `_maybe_write_gate4_divergence` `:1978-2018`; modes `hvac_const.py:824-838` (default LIVE) |
| The single Gate 4 consumer | **REUSE (no change)** | `check_ac_reset` Gate 4 `hvac_override.py:4135-4140`, then Gates 6/7/8 `:4187-4249` |
| SPAN fallback read | **REUSE** | `_read_kwh_rate` `hvac_override.py:4618-4669`, threshold `AC_ACTIVELY_COOLING_KW_MIN = 0.5` `hvac_const.py:818` |
| Tri-state running predicate from ODU stage | **NEW helper** (one function, two consumers). Nothing reads `*_odu_status` today (grep `odu_status` over the component: 0 hits) | — |
| Per-zone ODU entity config | **NEW field** `CONF_HVAC_ODU_STATUS_SENSOR`, mirroring the REUSE precedent `CONF_HVAC_AC_LOAD_SENSOR` (`hvac_const.py:674`; flow `config_flow.py:9390-9461`; strings `strings.json:642,647`; merge `hvac_zones.py:457`, `:481-486`, `:569-582`, `:2716`; field `ZoneState.ac_load_sensor` `hvac_zones.py:160`). No existing field maps a zone to its ODU | grep `odu` in `config_flow.py` / `hvac_const.py`: 0 hits |
| Short-cycle listener + callback | **REUSE (extend)** | `_install_short_cycle_listeners` `hvac.py:6059-6096` (latch `:820`, `:6071`, `:6088`); `_on_zone_climate_state_change` `:6099-6210`; state `_short_cycle_on_since` `:816` (not restored, `:1180`) |
| Daily rollover emitter + baseline save | **REUSE (rename only)** | `_emit_and_reset_short_cycles` `hvac.py:6219-6370` |
| Old-baseline cleanup after the rename | **REUSE** | `AnomalyDetector.load_baselines` orphan delete `coordinator_diagnostics.py:1303-1348` |
| Zone status attrs (Live oracle) | **REUSE (add attrs)** | `sensor.ura_hvac_coordinator_zone_{n}_status` producer `hvac_zones.py:~1090-1150` |

**No new tables, signals or entities.** Additions: one helper, one per-zone config field, two rung-1 constants, a few display attrs, and the metric rename.

### 1.2 Docs consulted
- This plan's G0 results (§3).
- `PLANNING_ac_ramp_pipeline_hardening.md` (Gate-4 design, B-H1 state-clearing rule).
- `PLANNING_hvac_short_cycle_producer.md` (metric semantics, 14-sample gate).
- `AUDIT_bryant_duty_cycle_redundancy_2026_09_17.md`.
- Plan review `plan_review_hvac_w3_energy_aware.md`.
- The card itself, plus the dispositions of the four W3 child cards (`kanban.data.yaml:1742`, `:1970`, `:2010`, `:30393-30394`).

### 1.3 Memory bodies pulled
- `feedback_wire_in_anchor_mandatory.md`
- `feedback_coincidental_equality_masks_concept_split.md`
- `reference_hvac_zone_tonnage.md` (zone↔climate↔threshold mapping; live Gate-7 thresholds are per zone)

### 1.4 Code surveyed (REV 3 additions)
- `hvac_override.py:1919-2040`, `:4040-4267`
- `hvac.py:6059-6210`
- Rename sites (grep `short_cycle_rate`, §5.4)
- `ha_carrier/sensor.py:735-765` (`OutdoorUnitOperationalStatusSensor`: a digit string → state `"on"`; other strings are passed through; `None` → unavailable)

---

## 2. Live facts this plan rests on
| Fact | Source |
|---|---|
| All three ODUs `type: proteusac` (variable-speed); no Var % entity (integration type list) | CORRECTION section; `ha_carrier/sensor.py:90-95` |
| ODU state vocabulary seen: `off`, `Stage 1`…`Stage 5`, `unavailable` (2.7 % of time). The integration also maps pure-digit values to `on` and passes other strings through (e.g. `dehumidify`) | G0-Q5; `ha_carrier/sensor.py:753-765` |
| ODU stage vs SPAN ≥ 0.2 kW agreement 98.2 / 98.9 / 98.7 % (z1/z2/z3) | G0-Q7 |
| Zones 2/3 low stage draws 0.3–0.5 kW; Gate 4 (0.5 kW) reads them OFF for 11.5 % / 23.8 % of action=cooling time | G0-Q7 |
| Gate-7 per-zone kW thresholds (live 2026-08-21): 1.3 / 1.2 / 1.3 kW | `reference_hvac_zone_tonnage.md` (**M0 re-reads live**) |
| Short cycles / 7 d: hvac_action 4 / 5 / 15; SPAN@0.5 30 / 329 / 362 (flap-inflated) | G0-Q7 |
| `short_cycle_rate` baselines `sample_count = 14` on all zones (matured 2026-09-28) | G0-Q10 |
| Zone → system → ODU (hand-built G0 fixture): zone_1 → `office_b` → `sensor.office_b_odu_status`; zone_2 → `sensor.thermostat_bryant_wifi_upstairs_odu_status`; zone_3 → `sensor.thermostat_bryant_wifi_backhallway_odu_status` | G0 fixture (§3). **M0-P0 re-verifies it against live co-movement before build** |

---

## 3. G0 — Measurement batch (read-only; COMPLETED — spec kept for the record)

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

## 4. M0 — Measure-first mini-probe for the build group (read-only; BEFORE build)

**Deliverable:** `scripts/probes/hvac_w3_m0_odu_stage.py` (`ssh ha "python3 -"`, `mode=ro`, America/Chicago rule), with results appended to this doc as "M0 results". It uses a 7-day recorder window and states the earliest timestamp.

| P | Question | GO / sets |
|---|---|---|
| **P0** Mapping check | For each of the 3 `*_odu_status` entities, which zone's SPAN circuit and `climate.*` co-move with its off↔Stage transitions? Report the % of ODU off→Stage edges followed within 120 s by a SPAN ≥ 0.2 kW rise **on each** of the 3 circuits. This confirms (or refutes) office_b = zone_1, upstairs = zone_2, backhallway = zone_3 by physics, not by name | GO iff every ODU co-moves ≥ 90 % with exactly one circuit, and that circuit is the fixture's. Otherwise STOP and fix the mapping |
| **P1** ODU availability pattern | Per entity: count and duration (p50/p90/p99/max) of `unavailable`/`unknown` episodes; how many fall **mid on-cycle** (between two `Stage N` states), how many are **adjacent to an off edge** (within 60 s), how many are within 15 min of an HA start (same method as the G0 SPAN measurement: 117–177 mid-cycle SPAN blips/week) | Sets `ODU_UNAVAILABLE_GRACE_S` = the next 30 s step ≥ the p99 mid-cycle episode duration (cap 300 s). If > 10 % of on-cycles contain an episode longer than the cap → STOP (the stage signal is too gappy) |
| **P2** Stage-update cadence | Per entity: `last_updated` gap distribution while in `Stage N` and while `off` (attribute churn updates `last_updated`); edge latency ODU off→Stage vs SPAN crossing 0.2 kW (both directions, p50/p95) | Sets `ODU_STAGE_STALE_S` = max(900 s, the next 5-min step ≥ the p99.9 running-state gap). Latency p95 > 120 s → note it (it affects cycle-duration accuracy, not the count) |
| **P3** Truth during Carrier blindness | ODU-vs-SPAN (≥ 0.2 kW) agreement restricted to G0's hvac_action-blind minutes, and during Carrier stale episodes (if any in the window) | GO iff agreement ≥ 95 % in blind minutes (ODU must not share hvac_action's failure) |
| **P4** Gate 4 flip replay | Reconstruct every 5-min tick (cool mode, `ramp_zone_enabled`, ramp master ON) per zone. Compute the SPAN-0.5 verdict (today) vs the stage verdict (new, with UNKNOWN → SPAN fallback). For every flip, replay Gates 6–8 using the live per-zone Gate-7 threshold and sustained-samples / detection-time knobs (read live): does the flip change (a) any dispatch (`_handle_overshoot_detected`), (b) the Gate-8 `last_overshoot_started` stamp retention (§5.2 finding), (c) `ramp_state` only? | GO for the Gate-4 wiring iff (a) = 0 and (b) produces 0 earlier dispatches in 7 d. If (b) ≥ 1 → STOP the Gate-4 half and re-plan (the fix would be clearing the Gate 8 stamp on a Gate-7 fail, which is a separate behaviour change). (c) is expected and accepted |
| **P5** Stage-derived short cycles | Per zone: on-cycles from off↔Stage edges; count < 600 s; flap (< 60 s); compare with SPAN@0.2 and hvac_action counts from G0 | GO for the short-cycle wiring iff stage flap < 5 % on every zone |

**INV-M0:** read-only; `mode=ro`; stdout only.

**M0 Acceptance Criteria:**
- **Verify:** an "M0 results" section exists with P0–P5 rows, raw numbers, the two derived constants with their arithmetic, and a GO/STOP per half.
- **Verify:** the orchestrator independently re-derives P0 for one zone (a disjoint check).
- **Test / Live:** n/a.

### M0 results (measured 2026-09-29)

**How it was measured.** The M0 probe agent ran the probes on 2026-09-29.
- Everything was read-only: `?mode=ro` URIs on both DBs over `ssh ha "python3 -"`, SELECT only, stdout only.
- There is one script per probe rather than a single `hvac_w3_m0_odu_stage.py` (operator instruction for this run): `scripts/probes/hvac_w3_m0_p{0_mapping,1_odu_availability,2_stage_cadence,3_blind_truth,4_gate4_replay,5_stage_short_cycles}.py`. They are saved but not committed.
- **Window:** recorder states from 2026-09-21 04:12 CDT (earliest ODU rows 04:13:12 / 04:13:42 / 04:16:58) to 09-29 00:27 CDT, about 7.8 d. The recorder holds 18 `homeassistant_start` events, the first at 09-21 23:25.
- **Restart rule:** an `unknown`/`unavailable` row within 3 min of an HA start is a restart transient. It is dropped, or reported separately.
- **Local time:** every local time is converted from an epoch timestamp with `America/Chicago`.
- **Fixture used:** zone_1 = `office_b` / `ac1` / `climate.thermostat_bryant_wifi_studyb_zone_1`; zone_2 = `upstairs` / `ac_2` / `climate.up_hallway_zone_2`; zone_3 = `backhallway` / `ac_3` / `climate.back_hallway_zone_3`.

**Live knobs read for P4** (constant over the whole window): Gate-4 mode `live`; nudge ON; ramp master ON; sustained samples 2; detection time 7 min; nudge in flight (detection → evaluated) median 365 s. The live per-zone Gate-7 thresholds are **1.5 / 2.2 / 2.2 kW**. §2's "1.3 / 1.2 / 1.3 kW" is stale; this section records the correction and §2 is not edited.

| P | Question | Numbers | Sets | Verdict |
|---|---|---|---|---|
| **P0** Mapping | Which SPAN circuit and climate entity co-move with each ODU's off↔Stage edges? | **Edges:** 106 / 111 / 133 off→Stage edges for office_b / upstairs / backhallway.<br>**Strict window** (SPAN ≥ 0.2 kW rise within 0 to +120 s after the ODU edge), per circuit ac1 / ac_2 / ac_3:<br>• office_b: 65.1 / 2.8 / 4.7 %<br>• upstairs: 3.6 / **99.1** / 8.1 %<br>• backhallway: 3.0 / 9.0 / **97.0** %<br>**Lead-tolerant window** (−300 to +120 s):<br>• office_b: **96.2** / 9.4 / 10.4 %<br>• upstairs: 9.0 / **100** / 19.8 %<br>• backhallway: 9.8 / 18.8 / **99.2** %<br>**Stage→off vs SPAN fall** (lead-tolerant): 97.2 / 100 / 100 % on the fixture circuit, ≤ 25 % on the others.<br>**off→Stage vs hvac_action → cooling** (lead-tolerant): 90.6 / 99.1 / 98.5 % on the fixture zone, ≤ 21 % on the others.<br>**Time-share agreement** (ODU running vs SPAN ≥ 0.2 kW): 98.2 / 98.9 / 98.7 % on the fixture circuit, 51.9–62.2 % on every other pairing | — | **Mapping CONFIRMED** (fixture unchanged). Every ODU co-moves ≥ 94 % with exactly one circuit (≤ 20 % with the others), and that circuit is the fixture's.<br>By the literal rule, office_b **fails** the strict window at 65.1 %. On that unit SPAN leads the ODU edge in about half the starts (P2: signed median −4 s, max 407 s), so the rise falls before the window.<br>**Orchestrator: confirm reading the rule on the lead-tolerant window.** The mapping itself does not need fixing |
| **P1** ODU availability | Episodes of `unavailable`/`unknown` per ODU: how long, mid-cycle or not, and whether near a restart | **11 episodes per ODU, at identical timestamps on all three**, so they are integration-wide events, not per-unit ones:<br>• 1 is the 09-28 restart storm (10,596 s).<br>• 10 are non-restart; none falls within 15 min of an HA start.<br>**Non-restart durations:** p50 69 s, p90 3059 s, p99 = max 4173 s. The distribution is bimodal: seven blips of 2–132 s, and three outages (3059 s and 4173 s, both mid-cycle, plus one 132 s blip).<br>**Mid on-cycle, non-restart:** 7 / 6 / 8 episodes, p99 4173 / 3059 / 3059 s. Pooled n = 21, p99 = 4173 s.<br>**On-cycles containing a non-restart episode > 300 s:** 2 / 1 / 1 of 106 / 112 / 133, i.e. **1.9 / 0.9 / 0.8 %** | **`ODU_UNAVAILABLE_GRACE_S = 300`**<br>= min(300 cap, ceil₃₀(p99 4173 s)). The cap binds. Every blip (max 132 s) fits inside it | **GO** (1.9 % ≤ 10 %). The 2.7 % unavailable share from G0-Q5 is these same few long, integration-wide outages, not frequent blips |
| **P2** Stage cadence | `last_updated` gaps while running and while off; edge latency of the ODU vs SPAN at 0.2 kW | **Gaps while `Stage N`:**<br>• p50 270 / 298 / 267 s<br>• p99 600 / 330 / 330 s<br>• p99.9 758 / 601 / 607 s<br>• max 1056 / 606 / 610 s<br>• pooled n = 5782, p99.9 = 656 s<br>**Gaps while `off`:** p99 894 / 607 / 901 s, max 13,571 / 2106 / 1801 s. Gaps over 900 s: 7 / 5 / 17. On those, a long `off` goes UNKNOWN and falls back to SPAN, which is harmless.<br>**off→Stage latency (ODU − SPAN):**<br>• signed median −4 / −41 / −34 s: **the ODU leads SPAN** on zones 2/3 (compressor soft start)<br>• \|lat\| p95 78 / 70 / 66 s<br>**Stage→off latency:** signed median +14 / −19 / −16 s; \|lat\| p95 68 / 50 / 51 s; zone_1 max 617 s | **`ODU_STAGE_STALE_S = 900`**<br>= max(900, ceil₅ₘᵢₙ(656 s) = 900) | Latency p95 ≤ 78 s < 120 s, so no note is needed. **GO** |
| **P3** Truth during Carrier blindness | ODU vs SPAN ≥ 0.2 kW agreement inside G0's hvac_action-blind minutes (cool mode, SPAN ≥ 0.5, action ≠ cooling) and during stale episodes | **Blind minutes:** 219 / 74 / 108. **Agreement 81.9 / 62.6 / 66.3 %.**<br>**Decomposition:**<br>• z2/z3: all disagreement is edge-order. There are 68 / 78 episodes, p50 25 / 23 s, max 61 / 328 s, every one within 5 min of an edge; blind minutes more than 5 min from an edge = 0.<br>• z1: 13 episodes, one of them **23 min (09-27 23:05–23:28)**. There, `sensor.office_b_odu_status` read a *fresh* `off` (rows every 5 min) and hvac_action read `idle`, while `ac1` held **3.15–3.35 kW** and the room fell 76→75 °F. On z1's non-edge blind minutes the ODU says running 90.0 % of the time.<br>**Stale proxies:** climate frozen > 15 min, 491 / 1024 / 438 min, agreement 94.6 / 99.8 / 100 %. Websocket age > 15 min: 0 min.<br>**All cool-mode time:** 98.2 / 98.9 / 98.7 % | — | **STOP by the literal rule** (< 95 % on all zones).<br>• On z2/z3 the ODU does *not* share hvac_action's failure: the misses are sub-minute edge order.<br>• On z1 it does share it at least once in 7 d: a 23-min full-stage run that both Carrier signals reported as off, with no staleness for the stale guard to catch.<br>This is exactly INV-W3(a)'s "ODU off + SPAN 2.7 kW → Gate 4 False" case, and it happened live. The "OFF overrides SPAN" design choice (§5.2 step 1b) is falsified as safe |
| **P4** Gate-4 flip replay | Replay the 5-min ticks (2252 ticks, 300 s grid phase-anchored on real `detection_fired`) under today's predicate (OLD) vs the stage predicate (NEW); Gates 6–8 are replayed with the live knobs | **Replay fidelity:** OLD vs the real `detection_fired` rows (68 / 27 / 18): precision 47/56, 24/35, 13/19; recall 47/68, 24/27, 13/18. Gates 5/5b, egress, override and S1-skip are not modelled; they are identical across models.<br>**Flip ticks (NEW ≠ OLD):**<br>• z1: 21. 13 are ODU RUNNING with SPAN < 0.3, of which 11 had SPAN < 0.05 kW (ODU lag after a nudge stop, **not** low stage). 8 are ODU `off` with SPAN ≥ 0.5 (the P3 episode).<br>• z2: 192, of which 174 had SPAN 0.3–0.5 kW (low stage).<br>• z3: 289, of which 270 had SPAN 0.3–0.5 kW (low stage).<br>**Gate-4 source on mode-guard-pass ticks:** ODU 97–99.8 %, SPAN fallback 61 / 5 / 17 ticks | — | **(a) dispatch changes: z1 = 3** (2 new, 1 moved), z2 = 0, z3 = 0.<br>**(b) earlier dispatches from Gate-8 stamp retention: 2** on z1:<br>• 09-21 15:04 vs OLD 15:14<br>• 09-27 19:27 vs OLD 19:37<br>Each is 10 min earlier. A tick with ODU RUNNING and SPAN about 0.02 kW passed the new Gate 4, failed Gate 7 and kept a 45–50 min old stamp.<br>**(a′)** One dispatch was delayed 15 min (09-27 23:39 → 23:54) by the ODU-off veto during the P3 episode.<br>**(c) ramp_state-only differences: 6 / 2 / 2 ticks.** A low-stage tick that now passes Gate 4 fails Gate 6 or 7 and is still labelled `idle`.<br>Latent, today's predicate: clearing the stamp on a Gate-7 fail would remove 3 / 9 / 1 of today's replayed dispatches.<br>**→ STOP the Gate-4 half** ((a) ≠ 0 and (b) ≥ 1) |
| **P5** Stage-derived short cycles | On-cycles from ODU edges through the §5.2 grace machine (grace 300 s, stale 900 s), same window as SPAN@0.2 and hvac_action | **ODU on-cycles** 97 / 104 / 125:<br>• short (< 600 s): **7 / 1 / 13**<br>• flap (< 60 s): 2 / 1 / 0 = **2.1 / 1.0 / 0.0 %**<br>• book-keeping: discarded (UNKNOWN→OFF) 0; dropped by grace 2 / 0 / 1 (the 51–70 min outages); dropped by restart 7 / 6 / 7<br>**SPAN@0.2:** 131 / 124 / 145 cycles; short 21 / 5 / 19; flap 12.2 / 1.6 / 0.7 %.<br>**hvac_action (cooling):** 92 / 106 / 124 cycles; short **4 / 5 / 15**.<br>**Overlap:** ODU short cycles that coincide with an hvac_action short cycle (±120 s): 4/7, 1/1, 12/13 | — | **GO by the rule** (flap < 5 % on every zone).<br>**Marginal-benefit note:** the ODU short-cycle counts (7 / 1 / 13) are close to hvac_action's (4 / 5 / 15) and mostly the same events. The "87–98 % disagreement" in §0 / §5.8 was measured against flap-inflated SPAN@0.5, not against compressor truth, so the short-cycle swap buys far less than the plan claims |

**Derived constants:**
- `ODU_UNAVAILABLE_GRACE_S = 300`. The p99 of non-restart mid-cycle episodes is 4173 s, so ceil₃₀ gives 4200 s, above the 300 s cap. The cap therefore binds. The largest short blip is 132 s, so a 150 s value would cover every blip as well.
- `ODU_STAGE_STALE_S = 900`. The pooled running-state gap p99.9 is 656 s, and ceil₅ₘᵢₙ of that is 900 s, which equals the 900 s floor.

**Verdict per half:**
- **Gate-4 half: STOP, re-plan.**
  - P4 (a) = 3 and (b) = 2 earlier dispatches on z1.
  - P3 fails, with a live 23-min ODU-`off`-at-3.3-kW case.
  - Two separate mechanisms:
    1. The ODU lags a nudge-induced stop, so RUNNING with SPAN ≈ 0 keeps the Gate-8 stamp alive. This is the §5.2 finding, now proven reachable.
    2. The ODU-OFF veto of high SPAN.
  - The low-stage rescue the card exists for works as designed on z2/z3 (444 flip ticks in 0.3–0.5 kW) and changed **no** dispatch there.
  - Re-plan options, for the orchestrator (not decided here):
    - ODU used only to *rescue* SPAN (RUNNING ∨ SPAN ≥ 0.5), never to veto it.
    - And/or clear the Gate-8 stamp on a Gate-7 fail. That is a separate behaviour change; replayed on today's predicate it removes 13 dispatches in 7 d.
- **Short-cycle half: GO on P5 as written,** with two caveats for the orchestrator:
  - P3's literal STOP is a predicate-level gate. Here the ODU is no worse than today's hvac_action source: both missed the same z1 run.
  - The measured benefit is small (see the P5 note).

**Findings for the plan review (not applied here):**
- Live criterion (2) in §5.10 ("ramp_state NOT forced to `idle`") does not discriminate. Low-stage ticks still end `idle` via Gate 6/7 (P4 (c) = 2 ticks on z2/z3). `gate4_source` is the discriminating observation.
- §2's Gate-7 thresholds are stale (live 1.5 / 2.2 / 2.2 kW).

**Outstanding:** the orchestrator's disjoint re-derivation of P0 for one zone, per the M0 acceptance criteria.

---

## 5. THE build group — ODU-stage running predicate (card `ARRESTER-GATE4-LOW-STAGE-THRESHOLD-1`)

### 5.1 Reader triage (carried from REV 2; unchanged except rows 1–2)
| # | Reader | Site | Decision (REV 3) |
|---|---|---|---|
| 1 | D5 duty accumulator | `hvac.py:5739` | **KEEP** hvac_action (G2-D5 DROPPED) |
| 2 | Short-cycle producer (cooling edges) | `hvac.py:6099-6210` | **SWAP → ODU stage** (zones with an ODU configured); heating stays on hvac_action |
| 3 | `zone_call_frequency` | `hvac.py:6458-6463` | KEEP (measures the thermostat call; suppressed) |
| 4 | `HouseSystemDemandSensor` | `aggregation.py:6510-6514`, `:6529-6532` | KEEP (display LTS series). A later swap is cheap once the predicate exists; card `HVAC-SYSTEM-DEMAND-SPAN-SOURCE-1` (from REV 2) can be re-targeted to ODU stage at mint time |
| 5 | Room `HVACCooling/HeatingBinarySensor` | `binary_sensor.py:1207`, `:1242` | KEEP |
| 6 | `_perform_ac_reset` `original_action` | `hvac_override.py:4272` (message) | KEEP |
| 7 | Carrier stale-reload corroboration | `hvac.py:7078-7083` | KEEP (must stay hvac_action) |
| + | **Arrester Gate 4** (was SPAN, not hvac_action) | `hvac_override.py:1923-1971` | **SWAP → ODU stage, SPAN fallback on UNKNOWN** |

### 5.2 Design

**Config (new, rung 2):** per-zone `CONF_HVAC_ODU_STATUS_SENSOR` = `"hvac_odu_status_sensor"`.
- It is an entity selector (domain `sensor`) placed beside "AC Load Sensor" in the same zone step (`config_flow.py:9390-9461`).
- Label: **"Outdoor Unit Status"**. Helper text: "The outdoor unit's status sensor (shows off or Stage 1–5). Used to tell when the compressor is really running. Leave empty to use the AC Load Sensor instead."
- It is carried onto `ZoneState.odu_status_sensor` (default `""`), using the same prefer-first-non-empty merge as `ac_load_sensor` (`hvac_zones.py:457`, `:481-486`, `:569-582`, `:2716`).
- **Empty = feature off for that zone = exactly today's behaviour** (the per-zone kill switch and rollback).

**Predicate:** one helper `compressor_state(hass, zone, now) -> RUNNING | OFF | UNKNOWN`. It is a module function in `hvac_override.py` so that both the arrester and `hvac.py` import it; there is no second copy.

| Case | Result |
|---|---|
| `zone.odu_status_sensor` empty | UNKNOWN |
| entity missing, `unavailable`, `unknown` | UNKNOWN |
| `now − state.last_updated > ODU_STAGE_STALE_S` | UNKNOWN |
| state `off` | OFF |
| state matches `^Stage [1-9]$`, or is `on` (integration's digit mapping), or `dehumidify` | RUNNING |
| anything else | UNKNOWN (plus one debug log per new vocabulary value) |

This is a read of `hass.states` only; it performs no I/O. The vocabulary lives in module constants (`ODU_STATE_OFF`, `ODU_RUNNING_PATTERN`, `ODU_RUNNING_EXTRA = {"on","dehumidify"}`).

**Gate 4 (`_zone_is_actively_cooling`, `hvac_override.py:1923-1971`):**
- Step 1 (mode guard) is unchanged.
- New step 1b: `s = compressor_state(...)`. If `s is RUNNING` → True; if `s is OFF` → False; if `s is UNKNOWN` → fall through to today's step 2 (SPAN ≥ 0.5, fail-closed on None).
- `_gate4_is_ok` modes are unchanged. `legacy` still returns the hvac_action verdict. `shadow` now logs divergence between legacy and the stage-aware predicate. `live` decides by the stage-aware predicate.
- **No enum change.** Rollback is per zone (clear the ODU field) or global (Select → `legacy`).
- The `check_ac_reset` body (`:4135-4249`) is **not changed**. Gate 7 still reads SPAN kW against the zone threshold.
- **Finding (recorded, not fixed):** a Gate-7 failure (`:4219-4225`) resets the sample counter but NOT `last_overshoot_started`. With the stage predicate, low-stage ticks (0.3–0.5 kW, previously a Gate-4 failure that cleared the stamp at `:4136`) now reach Gate 7 and keep the stamp. M0-P4 measures whether that yields an earlier dispatch. If it does, the Gate-4 half STOPs (above). If not, card `ARRESTER-GATE8-STAMP-SURVIVES-GATE7-FAIL-1` (adjacency sweep first) as a latent issue for the pre-existing 0.5 kW–threshold band.

**Short-cycle producer (cooling, zones with an ODU configured):**
- `_install_short_cycle_listeners` (`hvac.py:6059-6096`) subscribes the climate entities (today) **plus** every configured `odu_status_sensor`, with an `{odu_entity: zone_id}` map built at install.
- **ODU callback** (O(1): dict lookup, classify, compare). On each state event, compute `compressor_state` for old and new:
  - OFF → RUNNING: stamp `on_since` (only if none is open).
  - RUNNING → OFF: close. If duration < `SHORT_CYCLE_THRESHOLD_S`, book a cycle using the existing date-straddle rule (`hvac.py:6184-6195`).
  - RUNNING → UNKNOWN: mark `unknown_since` and keep `on_since`.
  - UNKNOWN → RUNNING within `ODU_UNAVAILABLE_GRACE_S`: clear `unknown_since`; the cycle continues.
  - UNKNOWN → OFF within grace: **discard** the cycle and book nothing, because the off instant is ambiguous.
  - UNKNOWN for longer than grace (checked on the next event for that zone, and at the 5-min tick for a zone whose ODU is silent): drop `on_since`.
  - Stage N → Stage M: not an edge.
- **Climate callback** for a zone with an ODU configured: cooling-edge handling is skipped, heating edges are unchanged. Zones without an ODU: unchanged.
- **Cost:** ODU state events arrive about every 5 min per system, unlike SPAN's about 5 s (the L5 concern dissolves). No per-event INFO log.
- **Install latch:** the latch (`hvac.py:6071`) means the listener set is fixed at first install. An ODU field set after boot is watched only after an HA restart (the docstring at `:6067-6069` confirms reloads don't re-register). Operator procedure: set the three fields, then restart once. It is verifiable through the new attribute `short_cycle_source` (below). Re-install on change is a **non-goal** (listener-lifecycle risk, Bug Class #38/#50, for a set-once field).

**Display attrs (NEW, for the Live oracle):** on `sensor.ura_hvac_coordinator_zone_{n}_status`: `odu_status_sensor`, `compressor_state` (`running` / `off` / `unknown`), `short_cycle_source` (`odu` / `hvac_action`), `gate4_source` (`odu` / `span_fallback` / `legacy`) — the last is set by the arrester on each Gate-4 evaluation.

### 5.3 Knob ladder
| Number | Name | Rung | Default | Why |
|---|---|---|---|---|
| stale window | `ODU_STAGE_STALE_S` (`hvac_const.py`) | 1 | max(900 s, M0-P2) | Protocol window. A change should need review: too long trusts a frozen stage; too short turns healthy steady-state into UNKNOWN |
| unavailable grace | `ODU_UNAVAILABLE_GRACE_S` (`hvac_const.py`) | 1 | from M0-P1 (≤ 300 s) | Protocol window sized to measured blips |
| ODU entity per zone | `CONF_HVAC_ODU_STATUS_SENSOR` | 2 (options, set-once) | `""` | Per-deployment structure; empty = kill switch per zone |
| short-cycle cutoff | `SHORT_CYCLE_THRESHOLD_S` 600 (existing) | 1 | unchanged | — |
| SPAN fallback cut | `AC_ACTIVELY_COOLING_KW_MIN` 0.5 (existing) | 1 | unchanged | Used only on UNKNOWN, preserving today's behaviour |
| maturation | `HVAC_SHORT_CYCLE_MIN_SAMPLES` 14 (existing) | 1 | unchanged | — |

### 5.4 Metric rename `short_cycle_rate` → `compressor_short_cycle_rate`
**Why:** the definition changes from thermostat-call cycles (4/5/15 a week) to compressor cycles. The 14-sample baseline (matured 2026-09-28) learned the old definition. Reuse the orphan cleanup (`coordinator_diagnostics.py:1303-1348`), which deletes the old `metric_baselines` rows on first load. No new DB code.

**Touch-sites (each gets a per-site mutation drill: revert one, and a named test must turn red):**
1. `hvac_const.py:1182` `HVAC_METRICS` entry
2. `hvac.py:1633` `minimum_samples_by_metric` key
3. `hvac.py:6287` `clear_active_anomalies_filtered(metric_name=…)`
4. `hvac.py:6296` `record_observation(…)` name
5. `hvac.py:6327` `AnomalyEvent.type = "hvac.compressor_short_cycle_rate"` (persisted payload string: a Tier 2-DB trigger)

Comment/doc-only: `hvac_const.py:1207`, `:1217`, `:1234`; `hvac.py:1629`, `:2063`, `:6349`, `:6435`; `coordinator_diagnostics.py:990`, `:1223`.
Tests: `quality/tests/test_hvac_short_cycle_producer.py` (35 refs) and `test_v465_observability_gap.py` (4 refs) must be updated. The builder also greps `/Users/okosisi/ha-config` dashboards for `short_cycle_rate` and lists the hits.

**Accepted cost:** the HVAC anomaly sensor's compressor metric is in `learning` for **~14 days** after deploy (1 obs/day/zone). Existing `anomaly_log` rows keep the old type string (history, not rewritten).

**Zone-scope caveat:** a zone with no ODU configured still emits the renamed metric from hvac_action cycles. On this house all three zones get an ODU, so the concepts don't mix. The build report states the per-zone source.

### 5.5 Falsifiable invariant INV-W3
> For a zone Z with a configured `odu_status_sensor`, in any reachable state:
> - (a) **Gate 4** (live mode) returns True iff the mode guard passes AND (`compressor_state(Z)` is RUNNING, OR it is UNKNOWN and fresh SPAN ≥ 0.5 kW). When the state is OFF, Gate 4 is False regardless of SPAN.
> - (b) **Short-cycle:** a cooling on-cycle for Z is opened and closed **only** by ODU OFF↔RUNNING transitions. No `hvac_action` edge opens or closes one. A cycle whose end is ambiguous (UNKNOWN → OFF) or that spans UNKNOWN longer than `ODU_UNAVAILABLE_GRACE_S` is never booked.
> - (c) For a zone with an **empty** `odu_status_sensor`, Gate 4 and the short-cycle producer are byte-identical to the pre-cycle build.
> - (d) `check_ac_reset` Gates 5–9, D5, and readers 3–7 of §5.1 are unchanged.

Falsified by:
- Gate 4 True on a zone whose ODU reads `off` while SPAN is 2.7 kW (a Carrier-says-off case).
- Gate 4 False on `Stage 2` at 0.4 kW.
- A booked cycle from an hvac_action cooling flicker on an ODU zone.
- A booked cycle across a 400 s `unavailable` gap when grace is 120 s.
- A booked cycle that ended via UNKNOWN → OFF.
- Any behaviour difference on an empty-field zone.

(For (a): Stage OFF + high SPAN → False is intentional. The ODU is the declared truth once configured, and M0-P3 guards that the ODU does not share hvac_action's blindness.)

### 5.6 Producer / consumer
**Producer:** `ha_carrier` `OutdoorUnitOperationalStatusSensor`, which reads `status.outdoor_unit_operational_status` (cloud status plus websocket).

| Dependency | Health |
|---|---|
| Availability | 2.7 % `unavailable` (G0-Q5); pattern → M0-P1 |
| Cadence | median attr change 5 min (G0-Q5); state cadence → M0-P2 |
| Truth vs physics | 98–99 % agreement with SPAN (G0-Q7); in blind windows → M0-P3 |
| Mapping | → M0-P0 |
| Carrier stale-client episodes | Mitigated by the stale guard plus the existing stale-reload machinery (`hvac.py:7199`) |

**Consumers:**

| Consumer | Kind | Detail |
|---|---|---|
| (1) Gate 4 → `check_ac_reset` | trust decision | Nudge gating; the only caller, at `hvac_override.py:4135`. The downstream nudge write is S5 via `emit_set_temperature`, with the §9e gate-(e) borrow row; that path is unchanged |
| (2) Short-cycle producer → `AnomalyDetector` → `anomaly_log` → HVAC anomaly sensor severity (`hvac.py:6567-6577`) → NM | trust (alerting) | — |
| (3) New display attrs | display | — |

### 5.7 Config-first
- No existing knob maps a zone to its ODU, or makes Gate 4 / short-cycle stage-aware.
- Lowering `AC_ACTIVELY_COOLING_KW_MIN` is a module constant, and G0-Q7 showed no single kW value fits all zones (13.8 % flap on z1 at 0.2).
- The per-zone Gate-7 threshold Numbers are unrelated (they gate high draw, not running).
- **Code required.** The ODU field itself is the config step the operator does once.

### 5.8 Marginal benefit
**Benefits:**
- Gate 4 stops misreading zones 2/3's low stage (11.5 % / 23.8 % of cooling time). P4 bounds whether any nudge decision actually changes. If none does, the Gate-4 half is correctness and observability (`ramp_state` stops flipping to IDLE during low-stage runs).
- The short-cycle metric starts counting real compressor cycles instead of thermostat-call edges, which disagree by 87–98 %. It is the only live HVAC metric that can page about a failing compressor.

**Costs and risks:**
- One helper, one options field, one listener extension, and a rename with 14 days of relearning.
- Risky ingredient: the listener-lifecycle change on a callback path, contained by an O(1) handler, the existing teardown envelope, and the per-zone empty-field rollback.
- The simplest alternative (per-zone SPAN kW thresholds) needs a new rung-3 knob per zone plus hysteresis, and still fails on the SPAN unavailability measured in G0. It is rejected on measurement, not preference.

### 5.9 Tier: **Tier 2-DB**
Arrester nudge gating is cost- and comfort-adjacent; the persisted anomaly `type` changes; a new options field needs round-trip coverage. Three framing-disjoint reviews:
- **A: correctness and edge cases.** Predicate truth table, vocabulary, stale guard, grace state machine, date straddle, DST in the rollover.
- **B: lifecycle, restart and cross-coordinator.** Listener install/teardown, restart mid-cycle (`on_since` RAM-only), rename orphan cleanup on first load, options round-trip, Gate-4 mode interplay, Gate-8 stamp finding.
- **C: test authority by real per-site mutation.** Gate 4 step 1b; the ODU callback's four transitions; the climate-callback cooling skip; the 5 rename sites; the options-field wire-in.

One adversarial plan review first.

### 5.10 Acceptance Criteria
- **Verify:** truth table.
  - `off` → OFF; `Stage 1`/`Stage 5`/`on`/`dehumidify` → RUNNING.
  - `unavailable` / `unknown` / missing / `last_updated` older than the stale window / `foo` → UNKNOWN.
  - Empty field → UNKNOWN.
- **Verify:** Gate 4.
  - `Stage 2` + SPAN 0.4 kW → True.
  - `off` + SPAN 2.7 kW → False.
  - UNKNOWN + SPAN 2.7 → True.
  - UNKNOWN + SPAN None → False.
  - Empty field: verdicts identical to pre-cycle across a mode × kW × None matrix.
  - `legacy` mode: identical to pre-cycle.
- **Verify:** short-cycle.
  - off→Stage 3→off in 300 s books 1.
  - An hvac_action cooling→idle→cooling flicker during continuous `Stage 3` books 0.
  - Stage→`unavailable`(60 s)→Stage continues the cycle (grace 120 s).
  - Stage→`unavailable`(400 s)→… books 0 and clears `on_since`.
  - Stage→`unavailable`→`off` books 0.
  - A heating cycle on an ODU zone is still booked from hvac_action.
  - An empty-field zone is byte-identical to pre-cycle.
- **Verify:** after a restart, the first rollover loads no `short_cycle_rate` rows, and the orphan rows are deleted.
- **Test:** `quality/tests/test_hvac_w3_odu_stage_predicate.py`:
  - `test_truth_table`
  - `test_stale_guard_uses_last_updated`
  - `test_gate4_low_stage_running_true`
  - `test_gate4_odu_off_overrides_span`
  - `test_gate4_unknown_falls_back_to_span`
  - `test_gate4_empty_field_identical_matrix`
  - `test_gate4_legacy_mode_identical`
  - `test_gate4_shadow_logs_stage_divergence`
  - `test_sc_odu_edges_book_cycle`
  - `test_sc_hvac_action_cooling_ignored_on_odu_zone`
  - `test_sc_unavailable_within_grace_continues`
  - `test_sc_unavailable_beyond_grace_drops`
  - `test_sc_unknown_to_off_discards`
  - `test_sc_heating_still_on_hvac_action`
  - `test_sc_empty_field_unchanged`
  - `test_sc_date_straddle_rule`
  - `test_rename_orphan_baseline_deleted_on_load`
  - `test_options_field_round_trip`
  - `test_zone_merge_prefers_first_nonempty_odu`

  Updated: `test_hvac_short_cycle_producer.py`, `test_v465_observability_gap.py`.
  **Wire-in anchors:** drive `check_ac_reset` (not the helper) for Gate 4, and the real `_on_*` callbacks via `hass.states.async_set` for the short-cycle producer. Neutering each site (step 1b, each ODU transition branch, the climate cooling-skip, each rename site, the zone-state field population) one at a time must turn a named test red. Record the drill table in the review doc.
- **Sensor:** `sensor.ura_hvac_coordinator_zone_{1,2,3}_status` shows `odu_status_sensor` = the fixture entity, `compressor_state` ∈ {running, off}, `short_cycle_source = odu`, and `gate4_source = odu` on ticks where Gate 4 was evaluated.
- **Live:**
  - **(1)** After setting the three fields and restarting, the attrs above hold.
  - **(2)** On zone_2 or zone_3 during a low-stage run (ODU `Stage 1/2`, SPAN 0.3–0.5 kW), the arrester's per-zone `ramp_state` is NOT forced to `idle` by Gate 4. Discriminates: pre-fix reads `idle` with SPAN < 0.5.
  - **(3)** Over the first 7 days, the per-zone daily compressor-cycle counts that the probe computes independently from ODU transitions equal URA's `_short_cycles_today` at each rollover within ±1. Discriminates: the old producer tracks hvac_action edges, which differ by 87–98 %.
  - **(4)** `metric_baselines` has `compressor_short_cycle_rate` zone_1/2/3 at `sample_count = 1` after the first rollover, and no `short_cycle_rate` rows.
  - **(5)** Zero ERROR lines from the new code in the first 24 h (a one-shot log scan, not a soak).

---

## 6. Sequencing
1. **M0** (read-only) now; append results; derive the two constants.
2. **Plan review** (one adversarial pass) against REV 3 plus the M0 results.
3. **Build after Batch B merges** (card `next`), in `.claude/worktrees/<agent-id>-w3`, rebased on develop. `hvac.py` and `hvac_override.py` overlap Batches B/C.
4. Tier 2-DB review → deploy (PATCH) → the operator sets the 3 ODU fields → one restart → live validation → README write-back → state-of-play update in the same commit (new §6/§9 notes: Gate 4 on ODU stage; short-cycle on ODU; metric rename; ODU Var absent because of the integration type list).
5. **Optional upstream (non-blocking):** ask `dahlb/ha_carrier` to add `proteusac` to the Var sensor type list.

## 7. Supersession (pre-planned)
| Item | Bucket | Reason |
|---|---|---|
| `short_cycle_rate` baseline rows | DELETE via the existing orphan cleanup | Learned the old definition |
| SPAN step 2 of `_zone_is_actively_cooling` | KEEP | Becomes the UNKNOWN fallback |
| `_gate4_legacy_predicate` | KEEP | Rollback path |
| hvac_action cooling-edge handling in the short-cycle callback | KEEP | Still used by empty-field zones |

## 8. Non-goals (parked / dropped items, with their revival triggers from the cards)
| Item | Board status | Revival trigger (from the card / G0 row) |
|---|---|---|
| **Pre-cool window TOU-derived** `HVAC-PRECOOL-WINDOW-TOU-DERIVED-1` | PARKED | The tariff adds a shoulder peak, or the realistic shoulder value doubles (REAL ≥ ~$29/yr vs today's $14.5; bar $25) |
| **D5 re-ground** `HVAC-D5-REGROUND-ON-ODU-VAR-1` | CLOSED (dropped) | None (closed). Its running-signal intent is this build. D5 retirement → W4 supersession sweep (KEEP + DOCUMENT) |
| **Equipment drift alerts** `HVAC-EQUIPMENT-HEALTH-OBSERVABILITY-1` | PARKED | Telemetry gate passes (static-pressure / superheat / discharge p95 update gap ≤ 30 min on all systems), AND ≥ 1 full cooling season of history, AND citable manufacturer limits. **Note:** with the 9 history template sensors not created, superheat/discharge history does not accumulate beyond 7 days. Reviving this starts with the operator choosing to create them |
| **History template sensors** (same card) | PARKED | No consumer until a drift detector is justified |
| **Filter alert** (same card) | DROPPED | None (the Bryant app reminds). Operator info: zone 1 static pressure has about doubled since April 2026 and its filter reads 40 %; a filter change is advised |
| **Reset vs nudge** (same card, Q9) | inconclusive (n = 6) | Proposed here (not on the card): re-run G0-Q9 when ≥ 10 hard resets fall inside one 7-day recorder window |
| **Grid-anticipatory pre-cool** `EC-GRID-ANTICIPATORY-PRECOOL-GAP-1` | parked | June 2027: re-run Q11 over the first 30 summer days; revive if hot-day `no_pv_surplus` mornings cost real $ |
| **Baseline windowing** `HVAC-BASELINE-MAXSAMPLES-1` | parked (W4) | A short-cycle anomaly (now `compressor_short_cycle_rate`) goes seasonally stale in practice: a false-nominal or false-anomaly traced to a > 90-day-old baseline |
| **Anomaly sensor "nominal while blind"** `HVAC-ANOMALY-BLIND-1` residual A | W4 | Operator pick on what the sensor should say while metrics are unfed. The rename's ~14-day `learning` window makes this more visible |
| Pre-heat TOU alignment | dropped | Heating changes to a heat pump |
| S12 banking borrows outside the window (G0 side-finding 1) | to be carded (adjacency sweep) | — |

Also out of scope:
- D5 input (keeps hvac_action).
- The `check_ac_reset` Gates 5–9 body, including the Gate-8 stamp finding.
- Gate-4 mode enum.
- Listener re-install on field change.
- Readers 3–7.
- SPAN threshold tuning.
- ODU attribute (superheat etc.) consumption.
- Carrier reload changes.

Nudges stay ON.

## 9. Operator questions
None blocking. The per-zone ODU field is set by the operator after deploy (three selections plus one restart); the values come from the M0-P0-verified fixture.

## 10. Suggested QUALITY_CONTEXT bug class (suggestion only — not applied)
**"UTC-bucketed analytics column."** A DB column named like a local-time dimension (`hour_of_day`, `day_of_week`, `is_weekend`) is populated from `utcnow()`, while its sibling `timestamp` is naive UTC. Any probe, analytics query or model feature that buckets by it is silently shifted 5–6 h (by DST), and a weekday/weekend split is wrong for the evening hours that cross UTC midnight. Exemplar: `energy_history` (`database.py:2697`, `:2723-2725`); live row `2026-09-29T04:05Z hour_of_day=4` = 23:05 CDT, and Apr–May rows at `hour_of_day ∈ {17,22}` split evenly between off_peak and mid_peak. **Detection:** grep writers of `hour_of_day|day_of_week|is_weekend` for `utcnow`. **Fix pattern:** populate from `dt_util.now()` (local), or drop the column and derive at read time with a named timezone; consumers must never trust the column name. Sibling of #11 / #21 / #51. The audit of existing readers is still to be carded.

## CORRECTION 2026-09-29: the units ARE variable-speed (operator)
The REV 2 claim "no ODU Var entity exists, so D5-REGROUND-ON-ODU-VAR is dropped as written" is WRONG in its inference. All three outdoor units report `type: proteusac` (Carrier's variable-speed Infinity ODU) on `sensor.thermostat_bryant_wifi_upstairs_odu_status`, `sensor.thermostat_bryant_wifi_backhallway_odu_status` and `sensor.office_b_odu_status`. ha_carrier only creates `OutdoorUnitVarSensor` for `outdoor_unit_type in ["varcaphp","varcapac"]` (`ha_carrier/sensor.py` ~90), so `proteusac` gets no Var % entity. That is an integration gap, not a hardware fact. The ODU status state carries the stage directly ("Stage 1..5" / "off"). **Re-plan G2 around ODU stage as the running signal** (G0: 98-99 % agreement with SPAN ≥ 0.2 kW). This removes the single-kW-threshold flap on zones 2/3 and gives arrester Gate 4 (`ARRESTER-GATE4-LOW-STAGE-THRESHOLD-1`) a stage-aware predicate.
