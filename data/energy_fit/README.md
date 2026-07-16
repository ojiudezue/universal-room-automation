# energy_fit/ — reproducible offline inputs for R1 consumption regression

- `daily_outdoor_temperature_f.csv` — daily mean/max outdoor temperature in °F,
  keyed by local calendar date. Extracted (2026-07-16) from the URA sqlite HA
  long-term-statistics table for `sensor.thermostat_bryant_wifi_backhallway_outdoor_temperature`
  (metadata_id 234, per B0 §A), aggregated as the daily mean/max of hourly
  `mean` rows; days with <12 hourly rows dropped. Kept as a committed CSV so
  the R1 fit script does not require access to the live HA DB.

Coverage vs the Enphase daily consumption CSV span (2025-02-24 → 2026-07-15,
361 days after outage-mask + negative-day mask): 342/361 = **94.7 %**. The 19
uncovered days are edges + the deep-winter 2026 gap (2026-01-01 → 2026-03-05,
already excluded by consumption-side masks).

If the extraction ever needs to be redone against a newer HA DB, use the same
metadata_id + local-day aggregation described in B0 §A.
