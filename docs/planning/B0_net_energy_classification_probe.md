# B0 Probe — Net-Energy-Aware Day Classification (read-only measurement)

**Date:** 2026-07-16 · **Type:** measurement probe, NO code changes · **Author:** probe session

**Operator thesis under test:** the arbitrage/attain/drain ladder classifies days by SOLAR alone
(`classify_solar_day`, `energy_battery.py:1175`, Solcast vs `SOLAR_MONTHLY_THRESHOLDS`,
`energy_const.py:81`); winter has less sun but far less AC load, so solar-only classification
grid-charges on days the house doesn't need it — anti-cost. URA already computes
`predicted_net_kwh` (`energy_forecast.py:225`, PV − temp-adjusted consumption) but the battery
strategy never consumes it.

**Headline verdict: the thesis is directionally REVERSED by the data.** The house is net-negative
in every season (avg net −5 kWh/d even on *excellent*-solar days, −57 on poor days). The
"false-poor overcharge" leak the thesis predicted is tiny (~**$13/yr**). The real leak is the
**inverse**: 59 days/yr where solar classified good/excellent (gate closed, drain target 10–15)
but net was < −30 kWh — the house imported the deficit at peak/mid-peak instead of pre-charging
off-peak. Estimated missed value ≈ **$120/yr**, concentrated in **summer** (29 days, ~$86).
Net-awareness is still worth building — but as a *gate-widener on high-consumption sunny days*,
not a winter gate-closer.

---

## A. Data inventory

| Source | Span | Rows/days | Notes |
|---|---|---|---|
| Enphase Enlighten CSV export (`data/enphase/enphase_custom_report_2026-05-13.xlsx`, gitignored) | 2025-02-24 → 2025-12-31 | 29,280 15-min records → **289 usable days** | Backbone. Columns: Energy Produced/Consumed/Exported/Imported/Stored/Discharged (Wh). Daily = sum of 15-min rows per local calendar day; days with <90 intervals or cons ≤1 kWh dropped. |
| URA sqlite `energy_daily` (`/config/universal_room_automation/data/universal_room_automation.db`) | 2026-03-06 → 2026-07-15 | 126 rows → **72 usable days** (`consumption_kwh` AND `solar_production_kwh` non-null) | Query: `SELECT * FROM energy_daily ORDER BY date`. Also carries `predicted_consumption_kwh` (used in §E). |
| HA long-term statistics (`/config/home-assistant_v2.db`) | 4 envoy serials: 202442014493 (2025-03-10→08-04), 202504003374 (08-12→10-02), 202428004328 (2025-10-03→2026-03-29), 482543015950 (2026-04-11→now) | hourly `sum` rows | **Cross-validation only.** Production `sum` deltas agree with the xlsx to **2.2% MAPE** (n=74 overlap days); consumption `sum` deltas are **corrupt (92.4% MAPE**, multi-million-kWh spikes in the cumulative sum) → HA-stats bridge REJECTED. Day boundary used: local (America/Chicago) calendar day on `start_ts` (`localtime`), sidestepping the F4 UTC-midnight roll by using `sum` deltas, not `state`. |
| Outdoor temp: HA statistic `sensor.thermostat_bryant_wifi_backhallway_outdoor_temperature` (metadata_id 234) | 2025-03-12 → now | 492 days | Daily mean/max of hourly `mean`; days with <12 hourly rows dropped. URA `external_conditions` only starts 2026-04-17 → not used as backbone. |

**Gaps (honest):** 2025-08-05→08-11, 2025-10-02→10-14 partially, and **2026-01-01→2026-03-05
(entire deep winter 2026)** — the xlsx ends 2025-12-31, URA `energy_daily` starts 2026-03-06,
and the only HA source for that window has corrupt consumption sums. Winter n=35 comes from
late-Feb 2025 + Dec 2025 only. A fresh Enlighten export covering Jan–Feb 2026 would close this.

**Merged dataset: 361 usable days, 2025-02-25 → 2026-07-15** (289 xlsx + 72 URA). Full daily
table generated at scratchpad `daily_table.csv` (session artifact; regenerable via `analyze2.py`,
same scratchpad — queries embedded there).

## B. Daily/monthly picture

| Month | n | Solar kWh/d | Cons kWh/d | Net kWh/d | Mean °F | Disagree % |
|---|---|---|---|---|---|---|
| 2025-02 | 4 | 89 | 48 | +41 | – | 50% |
| 2025-03 | 31 | 110 | 110 | −0 | 72 | 52% |
| 2025-04 | 30 | 107 | 110 | −3 | 74 | 47% |
| 2025-05 | 31 | 116 | 131 | −15 | 80 | 65% |
| 2025-06 | 30 | 122 | 146 | −24 | 84 | 67% |
| 2025-07 | 25 | 100 | 144 | −44 | 83 | 44% |
| 2025-08 | 24 | 99 | 147 | −48 | 87 | 75% |
| 2025-09 | 23 | 106 | 127 | −20 | 84 | 78% |
| 2025-10 | 30 | 97 | 120 | −22 | 79 | 87% |
| 2025-11 | 30 | 73 | 95 | −22 | 69 | 83% |
| 2025-12 | 31 | 58 | 92 | −34 | 59 | 74% |
| 2026-03 | 3 | 108 | 82 | +25 | 77 | 0% |
| 2026-04 | 10 | 69 | 102 | −33 | 76 | 50% |
| 2026-05 | 22 | 99 | 125 | −26 | 76 | 50% |
| 2026-06 | 26 | 121 | 162 | −41 | 84 | 77% |
| 2026-07 | 11 | 99 | 164 | −64 | 85 | 55% |

Season means (n / solar / cons / net / mean°F): winter 35 / 61.5 / 86.9 / **−25.4** / 59.5 ·
spring 127 / 105.6 / 116.5 / −10.9 / 76.0 · summer 116 / 110.2 / 150.9 / **−40.7** / 84.6 ·
fall 83 / 91.0 / 112.6 / −21.7 / 76.5.

**Key structural fact:** consumption (86–151 kWh/d seasonal mean) always exceeds a 40-ish kWh
battery's throughput, and net is negative in every season. Winter consumption IS much lower
(87 vs 151 kWh/d summer) — the thesis's premise is right — but winter solar drops even faster
(61 vs 110), so winter net is still −25 kWh/d. There is no season where "poor solar + low load"
makes the buffer unnecessary on the average day.

## C. Solar-only vs net classification

Method: solar-class = the code's monthly ladder (`classify_solar_day`, monthly mode: ≥P75
excellent, ≥P50 good, ≥P25 moderate, else poor — note monthly mode **never returns
`very_poor`**; that class is reachable only in custom-threshold mode, `energy_battery.py:1175-1211`)
applied to **actual production as a proxy for the Solcast forecast** (caveat: forecast error not
modeled; actuals slightly darken cloudy days vs their forecast). Net-class = same ladder applied
to consumption-normalized solar `(solar/cons) × P50(month)` — i.e., "a day is *good* if solar
covers the same fraction of load that P50 solar covers of typical load".

- **Disagreement: 235/361 = 65%** (winter 71%, spring 52%, summer 65%, fall 83%).
- Direction: **226 of 235 disagreements have net-class WORSE than solar-class** (house needs more
  than solar suggests); only 9 days the other way. Solar-only classification is systematically
  over-optimistic, not over-conservative.
- Mean net by solar-class: excellent −4.9 · good −23.5 · moderate −40.4 · poor −56.7 kWh/d.
  The ladder *is* monotone in net need — poor-solar days genuinely need the buffer most, so the
  arbitrage gate's poor→grid-charge rule is directionally correct.

## D. The money question

Rules under test: arbitrage gate opens iff `target_day_class ∈ {poor, very_poor}`
(`energy_battery.py:4166-4183`) → grid-charge toward `peak_buffer_target` (80). Drain targets
`{excellent:10, good:15, moderate:20, poor:30, very_poor:30, unknown:40}`
(`energy_const.py:531-535`, map built at `energy_battery.py:311`). Rates: PEC 2026 off-peak
all-in $0.0860/kWh (energy 0.043481 + delivery 0.022546 + transmission 0.019930, from
`data/enphase/build_energy_report.py:31-48`); round-trip loss 10%; cap 28 kWh/day (30→80% charge).

**D1 — thesis direction (false-poor: gate opened, house didn't need it).** Days with
solar-class = poor AND net ≥ −14 kWh (deficit coverable inside normal drain-target headroom):
**5 days / 361** (winter 1, spring 0, summer 2, fall 2) ≈ 140 kWh ≈ **$13/yr** of unnecessary
off-peak charge. *The thesis's leak is negligible at current consumption levels.*

**D2 — inverse (undercharge risk: gate closed, house needed the buffer).** Days with
solar-class ∈ {good, excellent} AND net < −30 kWh: **59 days / 361** (winter 1, spring 10,
summer 29, fall 19; mean net −40 to −47). Value of pre-charging 28 kWh off-peak instead of
importing at peak/mid-peak (energy-rate spread only, delivery paid either way; summer
peak−off = $0.118/kWh, other seasons mid−off = $0.043/kWh; 90% efficiency):
winter $1 + spring $11 + **summer $86** + fall $21 ≈ **$119 over the span ≈ $120/yr**.
(Upper bound: assumes the full 28 kWh deficit lands in premium windows; the true number needs
TOU-windowed import data — the xlsx has 15-min import and the prior TOU analysis
(`data/enphase/ANALYSIS_2026-05-13_TOU_Peak_Exposure.md`) confirms substantial peak exposure.)

## E. Consumption predictability (scope decider)

In-sample fits on 342 days with temp (mean cons 125.3, sd 34.7 kWh/d):

| Model | R² | MAE (kWh/d) |
|---|---|---|
| Naive constant (mean) | 0.00 | 28.2 |
| Day-of-week baseline (URA's current `_estimate_consumption` backbone) | 0.01 | 28.0 |
| Linear HDD/CDD, base 65°F on daily mean temp | 0.38 | 18.8 (fit: 83.4 + 3.05/CDD + 0.83/HDD) |
| Season dummies + CDD + CDD² + HDD | 0.42 | 18.1 |
| **URA live `predicted_consumption_kwh`** (energy_daily, n=71, 2026-03→07) | **−1.55** | **50.9** |

- Day-of-week carries essentially **zero signal** (R²=0.01) — the existing per-DOW history
  baseline in `energy_forecast.py:246-256` is not earning its keep.
- Temperature alone gets you R²≈0.4 and cuts MAE by a third. CDD dominates (3.05 kWh per
  cooling-degree-day vs 0.83 heating) — this is an AC-load house.
- The **live URA predictor is badly miscalibrated** — worse than predicting the mean
  (systematic over-prediction: e.g. 2026-07-14 predicted 210.4 vs actual 119.8). Whatever ships
  must include recalibrating/validating `_estimate_consumption` first; `predicted_net_kwh` as
  currently produced is not consumable.
- Verdict: a **simple temp-regression** (which `energy_forecast.py:257+` already structurally
  has — base + coeff·|temp−72|) is the right scope. Nothing here justifies Bayesian machinery
  for the classification decision; the residual sd (~18 kWh MAE) is occupancy/EV/pool events,
  which per-day forecasting won't capture regardless of model class.

## F. Scope recommendation (Marginal-Benefit Decomposition)

1. **Do NOT build the thesis version** (net-aware gate-closing on winter poor days): $13/yr.
2. **Smallest version that captures the dollars (~$120/yr, mostly summer):** a
   **consumption-aware gate/target widener** — when `predicted_net_kwh` (recalibrated) is below
   ~−30 kWh, treat the target day one class worse for the *drain-target/attain* path (deeper
   park, or open the attain branch toward `peak_buffer_target`) even when solar-class is
   good/excellent. This REUSES: `predicted_net_kwh` (`energy_forecast.py:225`), the attain
   branch (`energy_battery.py:4189+`), `SOLAR_MONTHLY_THRESHOLDS`, and the existing drain map.
   NEW: one consumption-class rung + a config gate. Tier: regression-prone (arbitrage/attain
   shared primitive) → **Tier 2-DB/3 review per standing policy**.
3. **Prerequisite sub-cycle:** fix `_estimate_consumption` calibration (drop/deweight DOW, keep
   temp regression, validate against `energy_daily` actuals — the data for a nightly
   self-scoring loop already lands in `energy_daily.prediction_error_pct`).
4. **Bayesian engine marginal value:** low for day classification (R² ceiling ~0.4 is a data
   limit, not a model limit). Where it MIGHT help: event-conditioned consumption (EV plug-in,
   guest mode, pool season) — defer until the simple ladder's residuals are measured live.
5. **Other consumers of the same primitive:** DPM relax-ceiling and HVAC pre-cool key off temp,
   which this probe confirms is the dominant consumption driver (3 kWh/CDD) — a trustworthy
   `predicted_consumption_kwh` benefits both; EV solar-aware charging would benefit from net
   (not gross) surplus on the 59 D2 days. All three consume the recalibrated forecast, none
   need a new primitive.
6. **Data follow-up:** pull a fresh Enlighten export covering 2026-01→02 (closes the winter
   gap); the HA consumption statistic for every envoy serial is corrupt (92% MAPE) and should
   never be used as a consumption source.

**Caveats:** classification proxied by actual production, not archived Solcast forecasts (URA
does not persist the forecast; `arbitrage_cycles` / `energy_daily` don't store solar class —
worth adding a class column when the cycle ships, so the next probe measures the real gate).
All model fits in-sample; n=361 with a missing deep-winter 2026.
