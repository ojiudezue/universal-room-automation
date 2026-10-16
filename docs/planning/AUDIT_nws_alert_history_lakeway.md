# AUDIT: NWS alert history at the house (2021-01-10 → 2026-10-16)

Source: Iowa Environmental Mesonet VTEC archive (`mesonet.agron.iastate.edu/json/vtec_events_byugc.php`), for the two UGCs api.weather.gov resolves our point (30.3146, -98.0159, "Lakeway") to: forecast zone **TXZ192** and county **TXC453** (Travis). Replaces plan D4b (90-day probe): the HA recorder keeps only 7 days (`purge_keep_days: 7`), so the archive is the history.

## Counts (5.8 years)
Zone TXZ192 (302): Heat Advisory 52, Dense Fog Advisory 50, Red Flag Warning 41, **Wind Advisory 33**, Excessive Heat Warning 31, Flood Watch 20, Fire Weather Watch 13, Winter Storm Warning 9, Winter Weather Advisory 8, Freeze Warning 7, Cold Weather Advisory 6, Hard Freeze Warning 5, Winter Storm Watch 5, Wind Chill Warning/Advisory 4/4, Extreme Heat Warning 4, Flash Flood Watch 3, Extreme Cold Warning/Watch 2/2, Hard Freeze Watch 1, Wind Chill Watch 1, **Ice Storm Warning 1**.

County TXC453 (354): Flood Advisory 132, **Severe Thunderstorm Warning 131**, Severe Thunderstorm Watch 44, Flash Flood Warning 29, **Tornado Watch 11**, **Tornado Warning 5**, Flood Warning 2.

## Outage-relevant events per year
| Event | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 YTD |
|---|---|---|---|---|---|---|
| Wind Advisory | 4 | 8 | 6 | 6 | 7 | 2 |
| High Wind Warning | 0 | 0 | 0 | 0 | 0 | 0 |
| Severe Thunderstorm Warning (county) | 22 | 15 | 38 | 20 | 24 | 12 |
| Severe Thunderstorm Watch | 7 | 4 | 9 | 12 | 7 | 5 |
| Tornado Warning (county) | 0 | 4 | 1 | 0 | 0 | 0 |
| Tornado Watch | 3 | 4 | 1 | 1 | 2 | 0 |
| Ice Storm Warning | 0 | 0 | 0 | 0 | 0 | 1 |
| Winter Storm Warning | 4 | 1 | 1 | 1 | 1 | 1 |

## Findings
1. **"High Wind" in the trigger list has never fired here in 5.8 years.** The wind event that does occur is the Wind Advisory (~6/yr). Today's list is effectively blind to wind.
2. **Severe Thunderstorm Warnings are county-keyed (~22/yr)** but are issued as storm polygons; Travis is large, so many don't cover the house. Counting them all as hits over-holds; point-in-polygon would cut that, but needs the alert geometry (not in the HA sensor today).
3. **Dominant alert volume is administrative for a battery** (heat, fog, red flag, flood advisory: ~265 of 656). Correctly excluded today.
4. **Outage co-occurrence: not measurable from local data.** Recorder retention is 7 days; the Enphase cloud system-event calendar timed out on read. Operator memory is the oracle for which events actually caused outages here.
