# AUDIT — ARREST-COMFORT-1 Probe P1 (measure-before-build)

**Date:** 2026-08-11 (run ~02:45 UTC)
**Plan:** `PLANNING_arrester_comfort_delay.md` §6 (rev-2 thresholds)
**Method:** strictly read-only. All DBs opened `mode=ro` over `ssh ha "python3 -"`. Recorder
(`/config/home-assistant_v2.db`) queried only by `metadata_id` (no unfiltered scans); URA DB
(`/config/universal_room_automation/data/universal_room_automation.db`) for activity/zone/compliance rows.

## Method notes (vocabulary discovery)

- **`ura_activity_log` carries NO arrester/override action vocabulary.** Distinct actions over its
  31-day window (2026-07-12 → 2026-08-11) contain no `override`/`arrest`/`revert`/`compromise` rows —
  climate rows are `preset_change` (3,018; reasons `house_state_transition`/`vacant_past_grace`/
  `runtime_exceeded`/None) and `preset_change_suppressed` (4). The arrester (`hvac_override.py`) does
  not write to the activity log at all. **Consequence:** the 31-day qualifying-event measurement the
  spec assumed is CANNOT-MEASURE from the URA DB; qualifying events were instead reconstructed from
  the **recorder** climate history over its retention window.
- **Reconstruction window:** 7.73 days (2026-08-03 09:13 UTC → 2026-08-11 02:43 UTC) — recorder purge
  depth for the three zone thermostats (`climate.thermostat_bryant_wifi_studyb_zone_1` mid=1525,
  `climate.up_hallway_zone_2` mid=5281, `climate.back_hallway_zone_3` mid=5282).
- **Manual-candidate event** := recorder attribute transition that is (a) `preset_mode` non-manual →
  `manual` (flip), or (b) setpoint (`target_temp_high`/`target_temp_low`/`temperature`) change while
  `preset_mode` stays `manual` (sp), excluding any transition within ±20 s of a URA
  `preset_change` activity row for that zone. 603 candidates found (zone_1 266, zone_2 223, zone_3 114).
- **D1 predicate** applied exactly per plan §3.2 (per-hvac_mode legs, range-drag rule, deadband
  fail-closed, |delta| ≥ 2.0 °F on relevant leg), **∧ zone occupied** (zone_events intervals:
  zone_1 = Entertainment ∪ Master Suite, zone_2 = Upstairs, zone_3 = Back Hallway).
- **Joins:** SOC = last `sensor.envoy_482543015950_battery` (mid=18389) state before event; coast =
  `sensor.ura_energy_coordinator_hvac_constraint` (mid=16391; states coast/normal/pre_cool) at event;
  flap = `preset_change` rows with `reason=runtime_exceeded` within ±15 min.
- **Sanity anchor:** the 2026-08-09 kids incident (16:49 / 17:14 CDT = 21:49 / 22:12 UTC, zone_2)
  appears in the qualifying set exactly as expected (delta 2 / 6, ct 80, SOC 99-100, constraint=coast,
  flap co-fire TRUE). The reconstruction pipeline reproduces the motivating incident.

### Caveats
- Residual contamination possible from URA `emit_set_temperature` writes not represented as
  `preset_change` rows (exclusion window only covers preset writes). The zone_3 flips at exactly
  11:00:00 UTC (= 06:00 local `next_activity_time`) look like the Bryant's own schedule, not a human;
  zone_3's 3 qualifying events should be discounted. Direction of error: **overcount**, which does not
  change any GO verdict (thresholds are lower bounds and zone_2 alone clears them by >40×).
- `zone_events` timestamps are naive; treated as UTC (consistent with `ura_activity_log` +00:00 rows).

## Per-metric numbers

| # | Metric | Value |
|---|---|---|
| 1 | Qualifying-under-INV events | **49 in 7.73 d ≈ 44.4/week**. Per-zone: zone_2 **43**, zone_1 3, zone_3 3 (zone_3 likely schedule artifacts, see caveats). 603 manual candidates; non-qual reasons dominated by deadband (304) and unoccupied (177 toward-comfort-but-vacant). |
| 2 | SOC at qualifying events | SOC known 43/49 (6 unknown → fail-closed, no grant). **SOC ≥ 80: 21/43 = 49 %** of known; grant fraction over all 49 = **43 %** (~19/week would grant). Distribution is bimodal: 20 events at 83-100, 20 events ≤ 64, cluster at 7-15 (pre-dawn/pre_cool). |
| 3 | Coast co-fire | **15/49 (31 %) ≈ 13.6/week** inside `coast`; of those, 13 also had SOC ≥ 80 (i.e. the D3 guard would actually fire ~12/week). pre_cool 14, normal 19. |
| 4 | Multi-thermostat zones | **0.** Zone-manager config maps exactly one `climate_entity` per HVAC zone (zone_1/zone_2/zone_3, one Bryant each). (House zones ≠ HVAC zones: zone_1 covers Entertainment + Master Suite house zones — known architecture.) |
| 5 | Preset-flap co-fire | **9/49 (18 %)** qualifying events within ±15 min of a `runtime_exceeded` preset_change — all in zone_2 on the 08-08 and 08-09 evenings, i.e. the flap and the comfort request co-fire on precisely the kids-incident evenings. |
| 6 | Recorder attribute retention | Oldest retained climate row (2026-08-03, age 7.7 d) carries FULL attributes (`current_temperature`, `temperature`, `target_temp_high/low`, `preset_mode`, `hvac_action`, …). Retention ≈ **7.7 days** — at, not above, the 7-day bar. |
| 7 | Cycle-B trigger | **MET.** 2026-08-08 evening, zone_2: 4 qualifying manual flips at 22:05 / 22:36 / 22:55 / 23:06 UTC — each re-flip within ~30 min of the prior (i.e. within an hour of where a 30-min grace would have expired). Second cluster 08-09 21:49-22:12. 14 same-zone qualifying pairs < 1 h apart across the window. |

## Threshold table (plan §6) — PASS/FAIL

| Metric | Plan threshold | Observed | Result → Action |
|---|---|---|---|
| Qualifying/week (1) | 0 in 30 d → defer; ≥ 1 → proceed | 44.4/week (7.7-d window; 31-d CANNOT-MEASURE, see method) | **PASS — Cycle A proceeds** |
| Coast co-fire (3) | ≥ 1/week → D3 as scoped | 13.6/week (12/week with SOC ≥ 80) | **PASS — D3 build required as scoped** |
| Coast co-fire (3) | < 1/month → defer D3 | not met | n/a |
| Multi-thermostat zones (4) | 0 → simplify grant key | 0 | **Simplify grant key to `zone_id`** in build (per-entity machinery unnecessary) |
| Recorder retention (6) | < 7 d → synthesize fixture | 7.7 d, attrs intact | **PASS (marginal)** — kids-incident rows still present; **extract the D5 replay fixture immediately** (they purge ~2026-08-16) |
| Cycle-B trigger (7) | already met → escalate scope | MET (08-08 4-flip cluster + 08-09 cluster) | **Escalate:** consider Cycle B (D4) in-cycle, still framing-disjoint reviewed |

## Verdicts

- **D1 (predicate + branch): GO.** ~44 qualifying events/week; predicate legs all exercised in the wild (hc_cool dominant; deadband fail-closed is the top rejection — predicate shape is right).
- **D2 (SOC gate): GO.** Gate is load-bearing, not decorative: it splits real events ~50/50 (21 grant / 22+6 collapse). Envoy-blind fail-closed path also exercised (6 unknown-SOC events).
- **D3 (coast precedence guard): GO.** ~13.6 coast co-fires/week, ~12/week with SOC ≥ 80 — the guard fires routinely, and 9 flap co-fires confirm HVAC-PRESET-FLAP-1 races the exact same events. Correct seam.
- **Build simplification (metric 4):** grant key collapses to `zone_id`.
- **Scope escalation (metric 7):** Cycle-B evidence trigger is ALREADY met in-window; per plan, consider D4 in-cycle (operator decision — Tier-3 checkpoint).
- **CANNOT-MEASURE:** 31-day qualifying rate (URA-DB arrester vocabulary absent; recorder retention 7.7 d). Optional build note: the D1 ledger rows themselves will close this gap going forward.
