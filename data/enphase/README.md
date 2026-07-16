# Enphase Enlighten exports (site 5700967)
- site_energy_consumption_daily_2025-02-24_to_2026-07-15.csv — kWh/day. CLOSES the deep-winter gap (R5 done, exported 2026-07-16).
- site_energy_production_daily_2025-02-24_to_2026-07-15.csv — **Wh**/day (unit differs from consumption!). Total row at EOF.
- site_recent_power_consumption_15min_2026-07-09_to_07-16.csv — W, 15-min, thousands-separated quoted numbers; small negative values near 0 (CT noise) present.
- enphase_custom_report_2026-05-13.xlsx — earlier 15-min export used by B0 probe.
DATA QUALITY: zero-runs appear in BOTH daily series simultaneously (e.g. 2025-07-22..27, 08-05..11, 09-19..25, 2026-03-30..04-06, 05-27..30) = metering/reporting outages → EXCLUDE, not real zeros. Also partial-day edges around outages; consumption has one negative day (2026-05-28). Estimator fits must mask these.
