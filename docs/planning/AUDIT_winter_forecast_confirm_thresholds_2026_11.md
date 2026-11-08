# AUDIT: winter-storm forecast-confirm thresholds vs real outage / no-outage windows

Date: 2026-11-08 (CST). Read-only measure-before-build probe. Not committed.
Question: do FORECAST_PRECIP_CONFIRM_PCT=50 and FORECAST_PRECIP_CONFIRM_MM=1.0 confirm the freeze/ice outage events, and do they also confirm the no-outage winter warnings?

## Verdict

**Keep 1.0 mm.** Every outage window (Uri x2, 2023 ice, Jan 2026 WSW, Jan 2026 Ice Storm) confirms at 1.0 mm on the archived forecast (max hourly 1.8 to 14.8 mm), and also on observed ERA5 (min 1.1 mm). Lowering to 0.5 or 0.3 mm gains **zero** outage recall. In the forecast data the only windows 1.0 mm fails to confirm are the two no-outage windows that carried no forecast precip (2024-01-15, 2025-01-21), and those stay unconfirmed at 0.3 too. The three no-outage windows that DO confirm (2021-01-10, 2021-02-11, 2022-02-03) had real freezing precip; no amount threshold separates them from the outage windows (their max mm, 2.2 to 5.4, overlaps the outage range 1.8 to 14.8). Precip amount is not a discriminator between outage and no-outage here; the 1.0 value is not the problem. Lower values only add false confirms on observed-precip windows (ERA5 2025-01-21: 0.5 mm max, 2024-01-15: 0.2). No change recommended. Caveat: n=10 windows, 5 outage; see caveats.

## Method

- House point: lat 30.314635, lon -98.015861 (/Users/okosisi/ha-config/.storage/core.config; matches the audit's 30.3146,-98.0159).
- Windows: IEM VTEC archive for TXZ192 (`mesonet.agron.iastate.edu/json/vtec_events_byugc.php?wfo=EWX&ugc=TXZ192`), all Winter Storm Warning (9, 2021+) and the Ice Storm Warning (1). These are the products in `forecast_family` winter_storm (energy_const.py:1174-1177). Outage labels from AUDIT_outage_alert_correlation.md Table 2 (Uri 2021-02-15..19, 2023-01-31..02-03, 2026-01-24). I labelled WSW windows 2021-02-13 and 2021-02-17 as Uri outage; 2021-02-11 (4 days earlier) as no-outage. The audit counts 3 outage / 6 no-outage windows with different grouping; this probe has 4 outage WSW + 1 Ice Storm vs 5 no-outage WSW.
- Replication of code: energy_battery.py:3376-3395 evaluates `hourly_outlook(start, end)` with start = max(now, alert onset), end = min(alert end, start+48 h) (FORECAST_WINDOW_MAX_H=48, energy_const.py:1113). weather_manager.py:995-1018 takes the **max over any hour** (not a sum): `max_pop` over hours with a probability, `max_precip_mm_no_pop` over hours without. inclement.py:1799-1818: winter_storm confirms iff min temp <= 32 F (FORECAST_WINTER_STORM_CONFIRM_F) AND (max_pop >= 50 OR max_mm_no_pop >= 1.0). Probe used onset = IEM issue time, end capped at 48 h, any-hour max.
- Data: Open-Meteo Historical Forecast API (`historical-forecast-api.open-meteo.com`, hourly temperature_2m, precipitation, rain, snowfall, showers, precipitation_probability, weather_code, UTC) and ERA5 archive (`archive-api.open-meteo.com`) as OBSERVED/reanalysis. Script: scratchpad p.py (not committed); raw: scratchpad res.json.
- Coverage: historical-forecast returned data for all 10 windows including Feb 2021 Uri. precipitation_probability was null for all windows before 2025 and present for 2025-01-21 and Jan 2026, so for 2021-2024 only the **mm leg** is testable (this is the Open-Meteo-only fallback the question names).

## Per-event table (historical-forecast = FORECAST; ERA5 = OBSERVED)

mm = max hourly precipitation in window (any-hour). Confirm columns apply the temp gate (min <= 32 F) AND the precip leg, amount leg only unless noted. "fz+precip h" = hours with temp <= 32 F and precip > 0.

| Window (onset UTC date) | Truth | hrs | FC min F | FC max PoP | FC max mm | FC fz+precip h | Confirm @1.0 | @0.5 | @0.3 | ERA5 min F | ERA5 max mm | ERA5 @1.0 / 0.5 / 0.3 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2021-01-10 WSW | no outage | 11 | 31.8 | null | 2.9 | 2 | YES | YES | YES | 34.2 | 2.7 | temp gate fails (34.2) |
| 2021-02-11 WSW (pre-Uri) | no outage | 16 | 28.9 | null | 5.4 | 8 | YES | YES | YES | 28.9 | 0.8 | NO / YES / YES |
| 2021-02-13 WSW (Uri) | OUTAGE | 48 | 8.2 | null | 3.2 | 8 | YES | YES | YES | 10.6 | 1.9 | YES / YES / YES |
| 2021-02-17 WSW (Uri) | OUTAGE | 22 | 21.2 | null | 3.2 | 3 | YES | YES | YES | 21.0 | 1.3 | YES / YES / YES |
| 2022-02-03 WSW | no outage | 34 | 18.5 | null | 2.2 | 8 | YES | YES | YES | 19.9 | 3.9 | YES / YES / YES |
| 2023-01-30 WSW (ice storm) | OUTAGE | 48 | 26.6 | null | 4.0 | 13 | YES | YES | YES | 27.7 | 1.1 | YES / YES / YES |
| 2024-01-15 WSW | no outage | 11 | 15.6 | null | 0.0 | 0 | **NO** | NO | NO | 17.2 | 0.2 | NO / NO / NO |
| 2025-01-21 WSW | no outage | 20 | 24.8 | 23 | 0.0 | 0 | **NO** (PoP 23 < 50) | NO | NO | 27.5 | 0.5 | NO / YES / YES |
| 2026-01-24 WSW | OUTAGE | 10 | 28.9 | 87 | 14.8 | 0 | YES (PoP 87; mm 14.8) | YES | YES | 32.0 | 7.5 | YES / YES / YES |
| 2026-01-24 Ice Storm | OUTAGE | 24 | 16.9 | 88 | 1.8 | 6 | YES (PoP 88; mm 1.8) | YES | YES | 20.8 | 3.2 | YES / YES / YES |

Notes: for PoP-bearing rows (2025, 2026) the live code uses the PoP leg for those hours (50), not mm; shown both. Confirm for the 2021-2024 rows is the mm leg only because PoP is null in the archive.

## Summary counts (forecast, amount leg, temp gate applied)

| Threshold | Outage windows confirmed (of 5) | No-outage windows confirmed (of 5) |
|---|---|---|
| 1.0 mm (current) | 5 | 3 (2021-01-10, 2021-02-11, 2022-02-03) |
| 0.5 mm | 5 | 3 |
| 0.3 mm | 5 | 3 |
| 0.1 mm | 5 | 3 (2024 and 2025 forecast max is 0.0) |

Observed (ERA5) cross-check: 1.0 mm confirms 5/5 outage and 1/5 no-outage (2022-02-03 only; 2021-01-10 fails the temp gate at 34.2 F observed); 0.5 mm adds 2021-02-11 and 2025-01-21 (3/5); 0.3 adds nothing further.

## Caveats

- **Forecast vs observed:** the "historical forecast" series is Open-Meteo's archived model output stitched from the best-match model's early lead hours, not the exact forecast the house would have held at alert issuance (live code samples OWM near hours and Open-Meteo beyond 48 h; coordinator ruling 2026-10-16). It is an approximation of forecast skill. Large forecast-vs-ERA5 gaps (2021-02-11: 5.4 vs 0.8 mm; 2026-01-24: 14.8 vs 7.5) show model spread. ERA5 is reanalysis (~25 km), labelled observed, not station truth.
- **Point vs area:** single grid point at the house; WSW is zone-wide (TXZ192, all Travis). Some timing: 2024 and 2025 windows are 11-20 h, shorter than the 48 h cap.
- **PoP absent pre-2025** in the archive, so the 50% leg is untested for the Uri and 2023 events; only 3 PoP samples exist (2025-01-21: 23, Jan 2026: 87 and 88). 50% confirms both 2026 outage windows and correctly does not confirm 2025-01-21.
- **Small n and labels:** 5 outage / 5 no-outage; outage labels come from public reports (AUDIT_outage_alert_correlation.md caveats: small PEC feeder outages are invisible, so some "no-outage" windows may have had unreported outages, which would make the 3 confirmed no-outage windows less of a false-confirm problem). Utility is PEC (addendum 2026-10-16).
- Temperature gate: ERA5 min 2026-01-24 WSW was exactly 32.0 F (passes <=32); forecast 28.9.
- Nothing here tests the freeze-family (28 F) or convective legs.

## Recommendation

No code or knob change. Revisit only if a PoP-bearing winter season (2026-27) shows an outage window whose max PoP < 50 and max mm < 1.0; trigger is the off-grid ledger (planned) joined to the forecast snapshot, per the audit follow-up.
