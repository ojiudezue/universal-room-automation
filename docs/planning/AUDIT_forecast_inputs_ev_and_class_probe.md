# AUDIT: forecast inputs, EV energy, zone temps, classification re-probe, per-zone AC energy

Date: 2026-11-01 (CDT, run via `date`). Read-only probe. Scripts were run against the recorder
(`/config/home-assistant_v2.db`, `statistics` hourly `sum`/`mean`, local-day = America/Chicago) and the
URA DB (`energy_daily`). Not read: STATE_OF_PLAY docs (HVAC/presence). This is a data pull, not a
diagnosis of those coordinators. Memory `project_house_zones_vs_hvac_zones` applied (see item 5).

## 1. Weather entity

- Entity: `weather.phalanxmadrone` (URA room entries `weather_entity`; Coordinator Manager
  `energy_weather_entity`, fallbacks `weather.madroneweather_tracker_dynamic_weather_madroneweather_tracker`,
  `weather.madronehaos`; `.storage/core.config_entries`). Integration: `openweathermap`, mode `v3.0`
  (One Call 3.0), entry title PhalanxMadrone. An `nws` KRYW entry also exists but is not the configured one.
- Code: `aggregation.py:1141` `_refresh_forecast_cache` calls `weather.get_forecasts {"type":"daily"}`
  (15-min cache); `_get_forecast_temp` (`aggregation.py:1187`) indexes `forecast[day_offset][field]`
  POSITIONALLY (not date-keyed). If the offset is missing it silently returns `forecast[0]`
  (today's) value, and then falls back to the current-temperature attribute.
  A tomorrow request can therefore return today's high with no flag.
- Features: HA core source (openweathermap/weather.py, dev branch, via WebFetch): v3.0 mode supports
  `FORECAST_DAILY` + `FORECAST_HOURLY`; no twice-daily. The live `supported_features` attribute is NOT in the
  recorder (the state attributes lack it), and I did not call the service. Live HA-version match: UNVERIFIED.
- Daily entry fields (coordinator.py, dev): `datetime` (isoformat, tz as supplied by pyopenweathermap),
  `temperature` (= daily MAX), `templow` (= daily MIN), condition, humidity, pressure, cloud_coverage,
  wind_*, dew_point, apparent temp, uv_index, precipitation, precipitation_probability. NO mean field
  (mean = (high+low)/2 is a poor proxy). Horizon in days: UNVERIFIED (not stated in the source; One Call 3.0
  normally gives ~8, I did not confirm).
- Current state attrs (recorder, 2026-11-01): temperature 69 degF, humidity 83, cloud_coverage 98.

## 2. EV charging energy

URA DB: `evse_state` only holds pause/solar flags (no energy). No EV session/energy table found
(tables grepped: evse_state; energy_daily, energy_history etc. have no EV column).
Recorder long-term stats candidates (daily kWh from hourly `sum` deltas):

| Candidate | Coverage | Verdict |
|---|---|---|
| `sensor.span_panel_car_charger_consumed_energy` | 2025-03-12 -> 2026-10-13 (stats end) | Usable; max 82 kWh/d; one -92 day (2026-03-10) dropped |
| `sensor.span_panel_garage_a_evse_consumed_energy` | stats sparse in 2025 (56 days), full since ~2026-10-12 | Usable from 2026-10-13 (-817 reset artifact on 2026-10-12 dropped). Successor to car_charger; the physical rename is inferred (UNVERIFIED) |
| `sensor.span_panel_garage_b_evse_consumed_energy` | 2025-03 -> now | REJECT: constant ~2.5 kWh/d standby plus Mar-Apr 2026 glitches of 600-4300 kWh/d |
| `sensor.span_panel_2_garage_{a,b}_evse_energy_net` | 2025-09-20 -> now | Not analyzed |
| enphase_ev / Emporia / Tesla energy stats | none found in `statistics_meta` (Emporia only has status/rx/tx) | none |

Chosen series: car_charger through 2026-10-12, then garage_a from 2026-10-13 (window 2026-03-01 -> 2026-11-01, n=224 days, 1 dropped).
- mean 10.47, median 4.51 kWh/day; 37% of days <0.5 kWh; mean over days with >=1 kWh = 17.6, median 19.1.
- By month (mean/median/n/frac days >1 kWh): Mar 6.7/0.1/24/.38, Apr 10.6/2.9/21/.52, May 10.4/7.1/31/.77,
  Jun 8.1/0.1/24/.33, Jul 11.1/4.7/31/.65, Aug 9.2/3.4/31/.65, Sep 16.5/20.2/30/.80, Oct 9.7/2.4/31/.52.
  Since 2026-07-16: mean 11.61, median 6.86 (n=109).
- Sanity vs whole-house `energy_daily.consumption_kwh` (123 days overlap): EV = 6.7% of consumption on average, max day 50%.
  Oct 14-18 shows 0 (operator away; consistent).
- CONTRADICTION with the R1 premise: the same car_charger circuit averaged **9.18 kWh/day in 2025-03..2026-02
  (169 days >1 kWh)**, so 2025 was not "EV-free" (energy_const.py:105-130 fit on 2025 as EV-free).
  The base regression therefore already absorbs ~9 kWh/day of EV load, and `ev_term_kwh` 18.58 on top of it
  double counts most of the EV load. Measured mean 2026 EV load is 10.5 kWh/day (2026 vs 2025 delta approx +1.3).
  The 18.58 constant is a residual (house change, pool, etc.), not an EV measurement. This is evidence for
  replacing it with a per-day measured/lagged EV term or recalibrating. I did not refit the regression.

## 3. Zone average temperature

- `ZoneAvgTemperatureSensor` (`aggregation.py:5063`): mean of `STATE_TEMPERATURE` over ROOM coordinators in a HOUSE zone.
  Entities: `sensor.zone_{back_hallway,entertainment_entertainment,master_suite,upstairs,outside}_avg_temperature`
  (statistics ids 3775, 3653, 3865, 3902, 4231) plus `*_temp_delta`. House zone != HVAC zone: house zones do not
  match HVAC zones one-to-one. Recorder coverage for these: not measured (only existence confirmed).
- `_get_house_avg_temp` (`aggregation.py:1112`): mean over all rooms; written to DB column `house_avg_temp`.
- True per-HVAC-zone indoor temperature = thermostat reading: `sensor.office_b_zone_1_temperature` (Zone 1; climate
  `climate.thermostat_bryant_wifi_studyb_zone_1`), `sensor.up_hallway_zone_2_temperature`, `sensor.back_hallway_zone_3_temperature`.
  Hourly stats coverage 2025-03-12 / 2025-05-01 / 2025-05-01 -> now (~13-14k rows each). Outdoor:
  `sensor.thermostat_bryant_wifi_backhallway_outdoor_temperature` (2025-03-12 -> now).
  Setpoints are not in recorder statistics (unused here).
- Relevance: use the thermostat sensors (HVAC-zone scoped), not `zone_*_avg_temperature`, for indoor-outdoor delta features.

## 4. Re-run of the B0 solar-only vs net classification probe

Method per B0 section C: monthly ladder (`SOLAR_MONTHLY_THRESHOLDS`) on actual production as forecast proxy; net-class =
same ladder on (solar/cons) x P50(month). My implementation is a literal reading of B0's one-line description
(UNVERIFIED equivalent). Calibration check: applied to the 2025 Enphase CSVs (n=286) it gives 73% disagreement,
201 of 209 net-worse, vs B0's 65% (and 226/235 net-worse) over 361 days that included 2026 URA rows. So direction matches; my absolute level is ~8 points higher.
- Recent window 2026-07-16 -> 2026-10-31 (`energy_daily`): only **59 of 108 days have usable consumption+solar**
  (Jul 6, Aug 13, Sep 11, Oct 29; the others are NULL). Disagreement: **43/59 = 73%**, all 43 net-worse
  (house needs more than solar class implies), 0 the other way. Same 73% / one-direction as the calibration.
- Undercharge (solar good/excellent, net < -30): 29 days, rough value **$69** over the window (B0 method:
  28 kWh x spread x 0.9; Jun-Sep spread $0.118, otherwise $0.043). Overcharge (poor and net >= -14): 0 days, $0.
  Annualized at B0's per-year basis (B0: 59 days/yr, $120/yr): 29 of 59 days sampled in one 3.5-month window, a
  naive scale of ~108 -> 365 days gives ~$230/yr, seasonally biased (Aug/Sep heavy; Oct class thresholds are low). Treat as
  "same sign, same order or larger than B0", not a precise figure.
- Mean net by solar class, recent: excellent -37 (n=36), good -72 (12), moderate -83 (2), poor -78 (9). Monthly net: Jul -13, Aug -53, Sep -97, Oct -42.
- Direction is thereby confirmed: the leak is undercharge on good/excellent days, not overcharge. Caveat:
  Oct has 36 "excellent" days partly because P75(Oct)=83 is low versus 2026 actual production.

## 5. Per-HVAC-zone AC energy (circuits from Zone Manager `zone_energy_sensors`)

Circuit-to-HVAC-zone mapping is by the house-zone entry plus room climate_entity config, inferred and UNVERIFIED
as a physical wiring fact: Master Suite entry -> `sensor.span_panel_ac1_consumed_energy` (rooms' climate =
`climate.thermostat_bryant_wifi_studyb_zone_1` = HVAC Zone 1, 4-ton); Upstairs -> `sensor.span_panel_ac_2_consumed_energy`
(Zone 2 `climate.up_hallway_zone_2`, 3-ton); Back Hallway -> `sensor.span_panel_ac_3_consumed_energy` (Zone 3 `climate.back_hallway_zone_3`, 3-ton).
(House zones Entertainment/Outside carry no AC circuit; mixed rooms' climate pointers cross house zones, hence the "inferred".)

Stats coverage (hourly): ac1 2025-03-15 -> now (13.2k rows); ac_2 and ac_3 2025-03-12 -> now. Unit Wh (converted to kWh).
Daily kWh since 2026-07-01 (124 days, no negatives, no outliers, no gaps flagged):

| HVAC zone | Jul / Aug / Sep / Oct mean kWh/d | overall mean | median | max |
|---|---|---|---|---|
| Z1 ac1 (4-ton) | 32.6 / 39.4 / 38.0 / 12.2 | 30.3 | 33.3 | 53.2 |
| Z2 ac_2 (3-ton) | 25.9 / 32.0 / 30.2 / 9.6 | 24.4 | 26.3 | 46.6 |
| Z3 ac_3 (3-ton) | 17.3 / 27.3 / 17.9 / 6.1 | 17.0 | 16.0 | 43.1 |

Sum of three zones approximately 72 kWh/d mean since July, versus whole-house consumption ~120-200: AC is a large share.

Quick daily correlation (daily kWh vs daily mean outdoor minus daily mean zone-thermostat temperature; n=124):

| Zone | r (delta) | R2 (delta) | R2 (outdoor only) | since 2026-03 R2 (delta) |
|---|---|---|---|---|
| Z1 | 0.886 | 0.785 | 0.693 | 0.763 (n=222) |
| Z2 | 0.863 | 0.745 | 0.654 | 0.709 (n=221) |
| Z3 | 0.806 | 0.649 | 0.557 | 0.685 (n=221) |

Findings: per-zone models are well correlated (R2 0.65-0.79 in-sample, single linear feature), much better than the
house-wide R2 0.4 of B0; the indoor term adds 7-9 points over outdoor-only. Indoor temps vary only ~73-80 degF, so the gain comes
mostly from the outdoor term (setpoint, which is the controlled variable, not recorded). Caveats: in-sample only, no
holdout; linear through shoulder season with no deadband; daily thermostat mean lumps unoccupied/setback periods;
`sensor.zone_*_energy_today` only exists since v5.103.97 (today), so the long-term stats above are the series to use.

## Not verified
Live `supported_features` and forecast day count; circuit-to-zone physical wiring; Garage A/B EVSE physical identity vs the
old car_charger circuit; recorder coverage of `zone_*_avg_temperature`; 65% vs 73% reproduction gap (B0 script not available).
Scripts: scratchpad `p1.py`, `p2.py`, `p4.py` under
`/private/tmp/claude-501/-Users-okosisi-Code-universal-room-automation/75cc297f-1426-4620-b7aa-da058bc0fab0/scratchpad/`.

## SPAN AC circuit to HVAC zone pairing probe (2026-11-01, read-only)
Source: recorder, 14d, 1-min grid, forward-filled. Power `sensor.span_panel_ac1_power`, `sensor.span_panel_ac_2_power`, `sensor.span_panel_ac_3_power`; hvac_action of `climate.thermostat_bryant_wifi_studyb_zone_1`, `climate.up_hallway_zone_2`, `climate.back_hallway_zone_3`. Cells: P(power>500W | cooling) / P(power>500W | idle).

| thermostat | ac1 | ac_2 | ac_3 |
|---|---|---|---|
| zone 1 (4-ton) | 0.97 / 0.01 | 0.40 / 0.24 | 0.03 / 0.03 |
| zone 2 (3-ton) | 0.62 / 0.31 | 0.44 / 0.27 | 0.05 / 0.03 |
| zone 3 (3-ton) | 0.50 / 0.35 | 0.25 / 0.30 | 0.30 / 0.00 |

Running power (median while on): ac1 686 W (z1 cooling), ac_2 ~960 W, ac_3 ~810-960 W; peaks 3357 / 2499 / 2512 W. Tonnage ordering holds at peak (ac1 highest).
Verdict: zone1=ac1 CONFIRMED. zone2=ac_2 and zone3=ac_3 UNCLEAR: ac_3 has no discriminating link to zone 2, and zone 3 is cleanest with ac_3 (0.00 idle) but only 0.30 on-while-cooling; ac_2 is on often regardless of thermostat. Cooling minutes are few and the data is November (heating season, shared cycles), so z2/z3 are not separable.

### Follow-up (2026-11-01): August re-run and heating minutes
- August 2026 matrix NOT producible: recorder `states` begins 2026-10-25 10:12 (retention ~7 days); climate hvac_action has no August history (long-term statistics exist for the SPAN power sensors only, with no cooling labels). Verdict stays as above; z2/z3 UNCLEAR.
- hvac_action minutes in the window (the 14-day query actually returned only ~7 days of data; None = no state): z1 cooling 4168 / idle 7017; z2 cooling 1754 / idle 9417 / off 9; z3 cooling 1032 / idle 10151. Zero "heating" minutes in any zone, so no heat-pump heating seen; the furnace has its own SPAN circuit (`sensor.span_panel_furnace_power`).
- Unresolved: why cooling occurs in late Oct and why ac_2/ac_3 do not track it. Needs a cooling-season window from another source (URA DB or HA long-term statistics plus URA hvac logs).
