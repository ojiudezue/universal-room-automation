# AUDIT: E2-P, NWS Onset vs observed hazard (forecast-timed hold go/no-go)

Run 2026-10-17 ~14:55-15:30 CDT by ura-prober. Read-only. Spec: `PLANNING_ec_storm_stage_e.md` section "E2-P" (develop file read 2026-10-17; Q1-Q5 and the go/no-go (a)-(c) at lines 360-390). Output path is the one named in the dispatch brief (the plan text names `AUDIT_ec_storm_event_time_vs_onset.md`; rename if the plan wins).

## Verdict: NO-GO

E2b (forecast-timed in-window hold) stays parked. Evidence, against the plan's thresholds ((a) >= 3 events with G >= 4 h, (b) >= 12 top-rate hours freed, (c) 0 outages missed):

| Scope | (a) events with G >= 4 h | (b) top-rate hours freed over 5.8 y | (c) outages missed |
|---|---|---|---|
| **Watches only (what E2b would build, OQ-3b)**, ASOS KATT oracle | 9 (8 SVA + 1 TOA) PASS | **3.75 h** FAIL (need 12) | none documented in watch windows |
| Watches only, any of KATT/KAUS/KRYW earliest hazard | 7 PASS | **1.33 h** FAIL | same |
| Watches only, Open-Meteo gridded proxy | 0 FAIL | 0 h FAIL | same |
| All HOLD-class incl. warnings, KATT | 14 PASS | 16.1 h PASS (11.0 h of it = 2 warnings: Uri 7.0 + Jan 2023 4.0) | **not provable (Jan 2026 start unknown)** |
| All HOLD-class, any-of-3-stations | 10 PASS | **1.3 h** FAIL | |
| All HOLD-class, Open-Meteo proxy | 3 PASS | 13.0 h PASS (all in Feb 2021 WSW) | |

Reading: the only scope E2b covers (watches) fails (b) on every oracle, by 3x or more. Including warnings, (b) passes under 2 of 3 oracles but only on 1-2 storms (Feb 2021, Jan 2023), which are the documented outage storms, and warning deferral is not in E2b scope (OQ-3b). Dollar value is about $4 over 5.8 y at best (section Q3). The ledger trigger in the plan (>= 3 ledger HOLD events with G >= 4 h once Stage C forecast attrs accrue) stands as the revival condition.

## Method

Window: 2021-01-01 to 2026-10-16 (5.8 y). Location 30.3146,-98.0159; zone TXZ192, county TXC453 (from `AUDIT_nws_alert_history_lakeway.md`).

1. **Event list.** IEM `vtec_events_byugc.php?ugc=TXZ192` and `?ugc=TXC453` (the endpoint ignores date params; filtered to issue >= 2020-12-25 locally). Kept the current `INCLEMENT_PRODUCT_TABLE` HOLD rows (`energy_const.py:694-715`: warn + watch) plus Freeze Warning/Watch (E0). 228 VTEC events (table in Q1 header counts).
2. **Per-message timeline.** For each event, `json/vtec_event.py?year=&wfo=&phenomena=&significance=&etn=` returns the original product plus every SVS/update text. Parsed the VTEC line of the segment whose UGC header contains the house UGC: action (NEW/CON/EXT/EXB/EXA/CAN/UPG/EXP), begin, end. `000000T0000Z` begin = "ongoing" = feed Onset becomes Sent (confirmed live: `AUDIT_ec_storm_stage0_probes.md` P2(a), WIY 10-16 10:26).
3. **Hold model (D-B1 as shipped: start = Onset or Sent, held until Ends/Expires).** At each instant the hold is the latest message's [max(begin, Sent), min(end, next message)). CAN/EXP/UPG end it. Intervals are floored at the message's own Sent time (a hold cannot start before the alert is known). 9 watches were upgraded or cancelled before their Onset and never held (listed in Q1 notes).
4. **Hazard oracle (observed), first obs in [hold_start - 12 h, hold_end].** Station KATT (Austin Camp Mabry, 30.3208,-97.7604, ~15 mi E) is primary; alternates KAUS and KRYW (Lago Vista AWOS, 30.4967,-97.9659, ~13 mi N) and "earliest of the three". Definitions as in the plan: Freeze/Hard Freeze: tmpf <= 28 F; Wind Chill/Extreme Cold: apparent temperature (IEM `feel`) <= 28 F; Winter Storm/Ice Storm: METAR wxcodes containing FZRA, FZDZ, SN, PL, GS, SG or BLSN; Tornado/Severe Thunderstorm warn+watch: wxcodes containing TS. Data: IEM `asos.py` (report types 3,4), 2020-12-20 to 2026-10-17.
5. **Forecast proxy.** Open-Meteo Historical Forecast API at the house point (verified available 2021-2026, resolves to 30.3217,-98.0011, elev 349 m): hourly temperature_2m, apparent_temperature, weather_code (freezing/snow codes 56,57,66,67,71,73,75,77,85,86; thunder >= 95). 85 of 92 requests succeeded; the 7 failures are the watches that never held. SVW/TOW not fetched (hazard = issue time by construction).
6. **Deferred hold.** Same intervals, cut to t >= hazard - 4 h; if no hazard is found in the window the hold falls back to Onset (zero hours freed, the plan's `T = start` fallback). Top-rate hours counted in 5-minute steps in America/Chicago: summer (Jun-Sep) 16-20; shoulder (Mar-May, Oct-Nov) 17-21; winter (Dec-Feb) 05-09 and 17-21 (`energy_const.py:15-60` `PEC_TOU_RATES`, plan lines 82-84). Totals are a union across events (overlapping holds are not double counted).
7. **$ conversion.** hours x 15 pp/h (plan line 80: shoulder block drains ~60 pp over 4 h) x 0.4 kWh/pp x (top - bottom rate): winter/shoulder 0.0864 - 0.0435 = 0.0430, summer peak 0.1618 - 0.0435 = 0.1184 $/kWh.

## Q1 Onset re-stamps

Source: IEM per-message VTEC (above). "Earlier shift" = an update whose effective Onset (begin, or Sent if begin = ongoing) is > 15 min earlier than the previous message's Onset. "Ongoing mark" = an update that sets begin to `000000` after a prior explicit Onset (feed Onset moves to Sent, which is LATER than the original).

| Product | events | with >= 1 earlier shift | with an "ongoing" mark (Onset moves later to Sent) |
|---|---|---|---|
| Winter Storm Warning | 9 | 2 | 7 |
| Winter Storm Watch | 5 | 0 | 0 |
| Ice Storm Warning | 1 | 0 | 1 |
| Hard Freeze Warning / Watch | 5 / 1 | 0 / 0 | 3 / 0 |
| Extreme Cold Warning / Watch | 2 / 2 | 1 / 0 | 2 / 0 |
| Wind Chill Warning / Watch | 4 / 1 | 0 / 0 | 4 / 0 |
| Freeze Warning (E0) | 7 | 2 | 2 |
| Severe Thunderstorm Warning / Watch | 131 / 44 | 0 / 0 | 66 / 30 |
| Tornado Warning / Watch | 5 / 11 | 0 / 0 | 1 / 6 |
| **Total** | **228** | **5 (2.2 %)** | |

The 5 earlier shifts (all EXT/EXB with an explicit begin; none from `000000`):

| Event | Update Sent (CDT) | Action | Onset moved earlier by |
|---|---|---|---|
| Freeze Warning FZ.W.0001 2021 | 2021-12-11 22:53 | EXT | 2.0 h |
| Winter Storm Warning WS.W.0001 2022 | 2022-02-02 14:04 | EXT | 3.0 h |
| Freeze Warning FZ.W.0002 2023 | 2023-12-10 22:54 | EXT | 3.0 h |
| Extreme Cold Warning EC.W.0002 2025 | 2025-02-19 00:30 | EXT | 23.5 h (begin re-stamped to its own Sent) |
| Winter Storm Warning WS.W.0001 2026 | 2026-01-23 21:49 | EXT | 3.0 h |

Distribution: 2.0, 3.0, 3.0, 3.0, 23.5 h (median 3.0 h). Convective products: 0 of 191.

**Cross-checks.** (i) URA ledger: 0 rows with `action IN ('nws_alert','grid_outage')` in `ura_activity_log` (URA DB, ssh ha ro, 2026-10-17 ~15:05 CDT), so no ledger data yet. (ii) Recorder alerts sensor `sensor.nws_alerts_gps_30_3146_98_0159_nws_alerts_alerts`, 2026-10-10 10:54 to 2026-10-17 14:50 CDT: only an Air Quality Alert and the Wind Advisory (a NOTICE-class product, not HOLD). Its Updates re-stamped Onset 04:00 -> 10:26 (10-16) -> 18:53, both **later**, not earlier. Consistent with the table: the common re-stamp direction is later (ongoing marks); the earlier direction is rare (2 %) and mostly 2-3 h.

Notes: 9 watches never held (upgraded/cancelled before Onset): Winter Storm Watch 2022-01 (WS.A.0001), 2022-02 (WS.A.0002), 2023-01, 2025-01, 2026-01; Hard Freeze Watch 2022-12; Wind Chill Watch 2022-12; Extreme Cold Watch 2025-02, 2026-01.

## Q2 Onset lead G (first hazard hour minus effective hold start)

Per event in the table below (G in hours; negative = hazard already present before the hold started). Columns: KATT, then earliest-of-3 stations / Open-Meteo proxy (G / hours freed).

Winter and freeze events (28 that held; times CDT):

| Event | First Sent | Hold start | Hold end | First hazard (KATT) | G KATT | Freed h KATT | G / freed any-of-3 | G / freed Open-Meteo |
|---|---|---|---|---|---|---|---|---|
| 2021 WSW WS.W.0001 | 01-10 09:51 | 01-10 09:51 | 01-10 19:27 | 01-10 09:58 | 0.1 | 0 | -3.0 / 0 | -2.9 / 0 |
| 2021 WSW WS.W.0002 | 02-11 08:45 | 02-11 08:45 | 02-11 23:47 | 02-11 10:03 | 1.3 | 0 | -11.5 / 0 | -2.8 / 0 |
| **2021 WSW WS.W.0003 (Uri)** | 02-12 15:20 | 02-13 06:00 | 02-15 12:00 | 02-14 03:16 | **21.3** | **7.00** | -3.8 / 0 | **36.0 / 11.00** |
| 2021 Wind Chill Warn WC.W.0001 | 02-14 13:01 | 02-14 18:00 | 02-15 12:00 | 02-14 06:51 | -11.2 | 0 | -11.8 / 0 | -12.0 / 0 |
| 2021 Hard Freeze Warn HZ.W.0001 | 02-15 14:44 | 02-15 19:00 | 02-16 12:00 | 02-15 07:51 | -11.2 | 0 | -11.8 / 0 | -12.0 / 0 |
| 2021 Wind Chill Warn WC.W.0002 | 02-15 14:40 | 02-15 19:00 | 02-16 12:00 | 02-15 07:51 | -11.2 | 0 | -11.2 / 0 | -12.0 / 0 |
| 2021 WSW WS.W.0004 | 02-15 14:40 | 02-16 18:00 | 02-17 15:11 | 02-16 23:23 | 5.4 | 1.33 | 2.8 / 0 | 6.0 / 2.00 |
| 2021 Hard Freeze Warn HZ.W.0002 | 02-18 14:45 | 02-18 21:00 | 02-19 09:58 | 02-18 09:51 | -11.2 | 0 | -12.0 / 0 | -12.0 / 0 |
| 2021 Hard Freeze Warn HZ.W.0003 | 02-19 14:08 | 02-19 21:00 | 02-20 09:00 | 02-20 02:51 | 5.8 | 0 | 1.9 / 0 | -12.0 / 0 |
| 2021 Freeze Warn FZ.W.0001 | 12-11 13:52 | 12-11 23:00 | 12-12 08:00 | none <= 28 F | - | 0 | 4.9 / 0 | - / 0 |
| 2022 WSW WS.W.0001 | 02-02 02:52 | 02-03 00:00 | 02-04 09:13 | 02-03 03:29 | 3.5 | 0 | 2.9 / 0 | 3.0 / 0 |
| 2022 Freeze Warn FZ.W.0004 | 11-12 09:03 | 11-13 00:00 | 11-13 09:00 | none | - | 0 | - / 0 | - / 0 |
| 2022 Freeze Warn FZ.W.0005 | 12-17 12:32 | 12-18 00:00 | 12-18 09:00 | none | - | 0 | 1.9 / 0 | - / 0 |
| 2022 Hard Freeze Warn HZ.W.0001 | 12-21 13:02 | 12-22 18:00 | 12-25 10:00 | 12-22 14:51 | -3.1 | 0 | -4.8 / 0 | -3.0 / 0 |
| 2022 Wind Chill Warn WC.W.0001 | 12-21 13:01 | 12-22 18:00 | 12-23 11:59 | 12-22 12:51 | -5.2 | 0 | -6.1 / 0 | -5.0 / 0 |
| **2023 WSW WS.W.0001 (ice storm)** | 01-29 21:27 | 01-30 09:00 | 02-02 09:55 | 01-31 07:26 | **22.4** | **4.00** | 10.8 / 0 | 4.0 / 0 |
| 2023 Freeze Warn FZ.W.0001 | 10-31 21:03 | 11-01 03:00 | 11-01 08:54 | none | - | 0 | - / 0 | - / 0 |
| 2023 Freeze Warn FZ.W.0002 | 12-10 14:30 | 12-10 23:00 | 12-11 08:59 | none | - | 0 | 3.9 / 0 | - / 0 |
| 2024 Hard Freeze Warn HZ.W.0001 | 01-14 12:43 | 01-14 18:00 | 01-17 10:00 | 01-14 06:51 | -11.2 | 0 | -12.0 / 0 | -12.0 / 0 |
| 2024 WSW WS.W.0001 | 01-15 01:08 | 01-15 01:08 | 01-15 11:59 | 01-15 03:51 | 2.7 | 0 | -4.1 / 0 | - / 0 |
| 2024 Wind Chill Warn WC.W.0001 | 01-15 11:59 | 01-15 12:00 | 01-16 08:10 | 01-15 00:51 | -11.2 | 0 | -11.2 / 0 | -12.0 / 0 |
| 2024 Freeze Warn FZ.W.0001 | 12-10 13:38 | 12-11 00:00 | 12-11 08:00 | none | - | 0 | - / 0 | - / 0 |
| 2025 WSW WS.W.0001 | 01-19 13:26 | 01-20 18:00 | 01-21 13:31 | 01-20 21:51 | 3.9 | 0 | 2.6 / 0 | - / 0 |
| 2025 Extreme Cold Warn EC.W.0002 | 02-18 13:32 | 02-19 00:30 | 02-20 12:00 | 02-18 19:51 | -4.7 | 0 | -7.0 / 0 | -5.5 / 0 |
| 2025 Freeze Warn FZ.W.0003 | 12-09 02:26 | 12-09 02:26 | 12-09 09:00 | none | - | 0 | 4.5 / 0 | - / 0 |
| 2026 WSW WS.W.0001 | 01-22 11:42 | 01-24 03:00 | 01-24 12:26 | none (KATT) | - | 0 | -1.4 / 0 | 1.0 / 0 |
| 2026 Ice Storm Warn IS.W.0001 | 01-24 12:26 | 01-24 12:26 | 01-25 12:00 | 01-24 20:51 | 8.4 | 0 (no top-rate hour in 12:26-16:51) | -10.8 / 0 | -8.4 / 0 |
| 2026 Extreme Cold Warn EC.W.0001 | 01-22 19:23 | 01-24 18:00 | 01-27 09:00 | 01-24 10:51 | -7.2 | 0 | -11.1 / 0 | -12.0 / 0 |

Freeze Warning events never reach <= 28 F at KATT (they are 32 F products); with <= 32 F the first-hazard hours are 2022-12-18 05:51 and 2023-12-11 05:51 (any-of-3 column shows G of 1.9-4.9 h), still < 12 h of value (every one is a night/early-morning event with at most 4 top-rate hours in the hold).

Convective events with G >= 4 h (KATT; all watches, none are warnings): hold start is the watch Sent time; every value in CDT.

| Event | Hold start | Hold end | First thunder (KATT) | G | Freed h KATT | G / freed any-of-3 |
|---|---|---|---|---|---|---|
| 2021 SVA SV.A.0045 | 03-22 18:05 | 03-22 23:12 | 23:04 | 5.0 | 0.92 | 3.8 / 0 |
| 2021 SVA SV.A.0165 | 05-11 15:41 | 05-11 22:00 | 21:37 | 5.9 | 0.58 | -0.1 / 0 |
| 2022 SVA SV.A.0258 | 05-21 15:30 | 05-21 22:56 | 22:29 | 7.0 | 1.42 | 6.8 / 1.25 |
| 2023 SVA SV.A.0155 | 04-20 14:30 | 04-20 22:00 | 19:40 | 5.2 | 0 | 1.4 / 0 |
| 2024 SVA SV.A.0248 | 05-16 11:01 | 05-16 17:00 | 15:49 | 4.8 | 0 | 4.2 / 0 |
| 2024 SVA SV.A.0358 | 05-31 00:37 | 05-31 07:00 | 05:03 | 4.4 | 0 | 4.3 / 0 |
| 2025 TOA TO.A.0331 | 05-26 14:36 | 05-26 22:24 | 21:09 | 6.5 | 0.08 | -7.7 / 0 |
| 2025 SVA SV.A.0630 | 10-24 20:17 | 10-25 02:56 | 00:51 | 4.6 | 0.58 | 4.1 / 0.08 |
| 2026 SVA SV.A.0197 | 05-10 17:17 | 05-10 23:28 | 21:29 | 4.2 | 0.17 | 3.6 / 0 |

Convective class summary (KATT): Severe Thunderstorm Warning n=131, thunder seen in window 106, G >= 4 h: 0, median G -0.7 h, 0 h freed. Tornado Warning n=5, seen 4, G >= 4: 0. Severe Thunderstorm Watch n=44, seen 30, G >= 4: 8, median G 2.4 h, 3.67 h freed. Tornado Watch n=11, seen 8, G >= 4: 1, 0.08 h freed. Watch windows are short (4-8 h) and mostly fall in shoulder season, where the only top-rate block is 17-21.

## Q3 Value (top-rate hours freed, hold from max(Onset, hazard - 4 h) vs from Onset)

Union across events, hours of top-rate time:

| Oracle | All HOLD-class | Watches only | Winter/freeze (warn+watch) | Convective |
|---|---|---|---|---|
| KATT observed | **16.08 h** | 3.75 h | 12.33 h | 3.75 h |
| Earliest of KATT/KAUS/KRYW | 1.33 h | 1.33 h | 0.00 h | 1.33 h |
| Open-Meteo gridded proxy | 13.00 h | 0.00 h | 13.00 h | 0.00 h |

By calendar year (KATT, all HOLD): 2021 9.83 h, 2022 1.42 h, 2023 4.00 h, 2024 0, 2025 0.67 h, 2026 0.17 h. Open-Meteo: 13.0 h, all 2021. Any-of-3: 2022 1.25 h, 2025 0.08 h.

Dollars (15 pp/h x 0.4 kWh/pp x spread): KATT **$4.15** over 5.8 y (~$0.72/yr), Open-Meteo $3.35, any-of-3 $0.34. This is an upper bound, since it assumes the battery would have been discharging through every freed hour.

Sensitivity of the result to the oracle: the Feb 2021 WSW (Uri lead-in) swings from 7.0 h (KATT, first FZ/SN at 02-14 03:16) to 0 h (earliest-of-3, an earlier snow/ice obs at KAUS/KRYW on 02-13 02:15) to 11.0 h (Open-Meteo). One storm decides (b) in the "all HOLD" scope. That fragility is itself a reason not to build.

## Q4 Safety, documented outages vs the later hold start

Documented outages are those in `AUDIT_outage_alert_correlation.md` Table 2; only freeze/winter ones coincide with HOLD-class alerts. Wind Advisory (NOTICE) has no documented outage; the 2026-06-04 Austin Energy fault had no alert and does not serve this house (PEC); the Jul-2025 flood is Flood/Flash Flood products (not HOLD-class). Coverage test: is the outage instant inside the deferred hold (union over events), and what is the deferred start versus the current hold start?

| Outage | Outage time (source) | Current hold start | Deferred hold start KATT / any-of-3 / Open-Meteo | Result |
|---|---|---|---|---|
| Uri load-shed | 2021-02-15 01:20-01:25 CST (ERCOT, per CBS/S&P) | 2021-02-13 06:00 | 2021-02-13 23:16 / 06:00 / 2021-02-14 14:00 | covered under all 3 (outage 26+ h after deferred start) |
| Jan-Feb 2023 ice storm | first outage time unknown; ~90,000 Austin Energy customers out by 07:11 CST 2023-02-01 (KUT) | 2023-01-30 09:00 | 2023-01-31 03:26 / 01-30 15:50 / 01-30 09:00 | covered (outages cannot precede the storm; deferred start 27 h before the KUT article) |
| 2026-01-24 Arctic blast | PEC 10 outages Lakeway/Lago Vista, **snapshot 21:30 CST**, start unknown (Fox 7) | 2026-01-24 12:26 | 2026-01-24 16:51 / 12:26 / 12:26 | covered at 21:30; **a start between 12:26 and 16:51 would have been missed under the KATT oracle; unknown** |

So (c) is not demonstrable: 2 of 3 are covered, 1 is undeterminable. This is moot for the verdict (fails (b)) but states that a "0 missed" claim would have no support from public data.

## Q5 Grid charge rate

**No episode.** `switch.enpower_482348004678_charge_from_grid` (recorder 2026-10-10 10:54 to 2026-10-17, 95 rows) only has `off` (49) and `unavailable` (46) states; it was never `on`. The three 5-minute-cadence "arbitrage_cycles" charge runs in the URA DB (e.g. 2026-10-14 15:42-16:56 CDT, SOC 80 -> 97 %, 14 pp/h) coincide with 3-15 kW solar production (`sensor.envoy_482543015950_current_power_production`), so they are solar charging, not grid; all 739 `arbitrage_cycles` rows (2026-06-13 to 2026-10-14) fall in local hours 08-16. Nightly SOC statistics (hourly, 2026-04-11 on) show no overnight rise >= 5 pp. Operator value (1-2 h for ~80 pp, 40-80 pp/h) stands, `INCLEMENT_GRID_CHARGE_PP_PER_H` = 50 unmeasured.

## Caveats

- **Observed vs forecast.** The ASOS hazard is a hindsight oracle (upper bound on what a forecast could deliver). Open-Meteo Historical Forecast is a stitched series of archived model analysis/early-forecast hours, not a lead-time forecast as seen at alert time (not verified how it is stitched; stated by the API, not checked here). Neither measures what OWM `weather.phalanxmadrone` would have said at the time; the real forecast-timed hold would be later than the oracle, i.e. frees even fewer hours.
- **Station distance.** KATT/KAUS/KRYW are 13-22 mi from the house; the house is ~350 m elevation west of Austin (colder, different convection). ASOS thunder is a point observation; a thunderstorm 10 mi away is not a hazard at the house. Conversely "earliest of 3" over-triggers. The wide spread between oracles (16.1 / 1.3 / 13.0 h) is the finding.
- **Hazard thresholds.** The plan's <= 28 F apparent threshold is lenient for Extreme Cold/Wind Chill warnings, so cold products usually show G < 0 (already below threshold before the hold). A stricter threshold would raise G for cold products; not run. Freeze Warning (32 F product) almost never satisfies the plan's <= 28 F definition.
- **Zone vs polygon.** SVW/TOW/SVA/TOA were measured with the county-keyed IEM events (TXC453), not point-in-polygon. Per `AUDIT_nws_alert_history_lakeway.md` only ~25 % of SVWs cover the house, so convective counts overstate house-relevant events.
- **Hold model.** Holds are modeled from IEM text products, not from the `nws_alerts` feed the integration actually sees (feed lag/Onset semantics differ slightly; Sent is the product time). Overlapping alert types are unioned; upgrade handoffs (e.g. Watch -> Warning) are treated as separate events.
- **Winter-precip definition.** Counts only METAR FZRA/FZDZ/SN/PL/GS/SG/BLSN at the station; light snow can precede the actual hazard period (Feb 2021) and drives the oracle sensitivity. "IC" (ice crystals) and "GR" (hail) were excluded.
- **Data gaps.** ASOS hourly coverage KATT 97.4 %, KAUS 99.8 %, KRYW 89.7 % of hours; wxcodes present on 14 %, 13 %, 10 % of rows (blank = no weather, indistinguishable from missing); KATT tmpf missing 194 rows. Open-Meteo failed for 7 watch events that never held (HTTP 400, empty date range). IEM `vtec_event.py` returned all 228 events.
- **Outages.** n = 3 relevant, start times unknown for 2 (2023 and 2026); public data only (see `AUDIT_outage_alert_correlation.md` caveats). No per-address PEC history.
- **Ledger** (Stage L) holds 0 `nws_alert` rows; recorder has 7 days. Neither adds HOLD-class history.

## Sources

- IEM VTEC by UGC: https://mesonet.agron.iastate.edu/json/vtec_events_byugc.php?ugc=TXZ192 and ?ugc=TXC453
- IEM VTEC event text with updates: https://mesonet.agron.iastate.edu/json/vtec_event.py?year=2023&wfo=KEWX&phenomena=WS&significance=W&etn=1 (pattern used for all 228)
- IEM ASOS: https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py (stations ATT, AUS, RYW) and https://mesonet.agron.iastate.edu/geojson/network/TX_ASOS.geojson (coordinates)
- Open-Meteo Historical Forecast API: https://historical-forecast-api.open-meteo.com/v1/forecast
- ERCOT load shed 01:20-01:25 CST 2021-02-15: https://www.cbsnews.com/texas/news/fighting-to-restore-power-ercot-calls-for-rotating-outages-as-extreme-winter-weather-forces-generating-units-offline and https://www.spglobal.com/commodity-insights/en/news-research/latest-news/electric-power/022421-ercot-lost-almost-half-of-generation-capacity-in-storm-causing-20-gw-load-shed
- 2023 ice storm: https://www.kut.org/energy-environment/2023-02-01/more-than-90-000-austin-energy-customers-are-without-power-as-a-winter-storm-hits-central-texas
- 2026-01-24: https://www.fox7austin.com/news/austin-weather-power-outages-central-texas ; PEC Jan 25 update https://mypec.com/pec-winter-weather-update-january-25/
- Repo: `docs/planning/AUDIT_nws_alert_history_lakeway.md`, `AUDIT_ec_storm_stage0_probes.md` (P2(a),(c)), `AUDIT_outage_alert_correlation.md`, `custom_components/universal_room_automation/domain_coordinators/energy_const.py:15-60,694-715`.
- Live reads 2026-10-17 (ssh ha, read-only): recorder `/config/home-assistant_v2.db`, URA DB `/config/universal_room_automation/data/universal_room_automation.db`.

Scripts and raw pulls (not committed): `/private/tmp/claude-501/-Users-okosisi-Code-universal-room-automation/75cc297f-1426-4620-b7aa-da058bc0fab0/scratchpad/e2p/` (`fetch.py`, `analyze.py`, `analyze3.py`, `tables.py`, `q4.py`, `vtec_all.json`, `asos_*.csv`, `om.json`).

## Disposition

E2b: NO-GO, park with the plan's ledger trigger. E2 proceeds as `T = start` (Onset). `INCLEMENT_GRID_CHARGE_PP_PER_H` remains the operator value (unmeasured). Cross-check remaining: if Stage C forecast attrs later accrue >= 3 ledger HOLD watch events with G >= 4 h, re-measure with the actual provider forecast rather than an oracle.
