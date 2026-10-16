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

## Addendum 2026-10-16: point-local check and freezes (operator: "only thing I have seen down power is freezes"; "local to our location, not county wide")
**Point vs county (storm polygons).** IEM storm-based warning polygons (`geojson/sbw.py`, WFO EWX, 2021-01 → 2026-10), point-in-polygon at 30.3146,-98.0159:
- Severe Thunderstorm Warning: 271 polygon features near Travis; **32 cover the house** (features include follow-up segments, so distinct events ≤ 32, ≈ ≤5.5/yr) vs 131 county-keyed events. **~4× over-count if keyed by county.**
- Tornado Warning: 18 polygon features near Travis; **0 covered the house**.
- Winter, freeze, wind and heat products are **zone-keyed** (TXZ192 = all of Travis); NWS issues no polygon for them, so zone is the finest available locality for those.
- The HA `nws_alerts` sensor does not carry the polygon geometry today, so point-local filtering of SVR/TOR needs the alert's geometry (api.weather.gov `/alerts/active?point=` returns polygon-matched alerts for storm products — to verify in planning).

**Freeze/winter events at the zone (outage-relevant history):**
- Feb 2021 (Uri, ERCOT load-shed): Winter Storm Warning ×3, Wind Chill Warning ×2, Hard Freeze Warning ×3.
- Feb 2022: Winter Storm Warning. Dec 2022: Hard Freeze + Wind Chill Warning.
- **30 Jan 2023 Winter Storm Warning** = the Austin ice storm (widespread tree-on-line outages 1-2 Feb 2023).
- Jan 2024: Hard Freeze, Winter Storm, Wind Chill Warnings. Jan 2025: Winter Storm Warning. Feb 2025: Extreme Cold Warning.
- Jan 2026: Winter Storm Warning + **Ice Storm Warning** + Extreme Cold Warning.
- Today's trigger list covers Winter Storm and Ice Storm, but **not Hard Freeze, Wind Chill, Extreme Cold** — the products that accompanied the 2021 grid load-shed. Freeze Warning (~1/yr, 32 °F) is likely not outage-relevant.

**Wind Advisory severity:** live CAP for the 10-15 WIY is `Severity: Moderate`, `Certainty: Likely`; it is an Advisory (Y), below Warning. Whether it should hold depends on local outage evidence — the operator has not observed wind outages; freezes are the observed cause. Do not promote WIY to hold without that evidence.

**Operator confirmation needed:** which dates actually lost power at the house (2021-02 Uri? 2023-02 ice storm? 2026-01?).
