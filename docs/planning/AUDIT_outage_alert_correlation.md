# AUDIT: grid outages vs NWS alerts at the house (Lakeway TX, 30.3146,-98.0159)

Date: 2026-10-15. Read-only research. Question (operator): is Wind Advisory genuinely predictive of power loss here, or only co-incident? Operator belief: "the only thing I have seen down power is actually freezes". Operator has lived here ~2 years.

## Bottom line

1. **There is no usable local outage ledger for wind.** The house's Enphase cloud calendar only reaches back to about 2026-08-29 (~47 days). In that window there were **0 real grid outages** (one off-grid pair on 2026-09-16 12:39-12:57 was a manual test with the generator on). In the same window there were **0 alerts of any kind** (0 Wind Advisory, 0 SVR warnings). So local data neither supports nor refutes the Wind Advisory hypothesis. It is an empty comparison.
2. **Public documented outages affecting Lakeway are rare (5 found, 2021-2026) and the large ones match the operator's belief**: the two big events are freeze/ice (Feb 2021 Uri load-shed, Feb 2023 ice storm), plus a small Jan 2026 Arctic-blast cluster. The one non-freeze large event (2026-06-04, ~8,200 Austin Energy customers, 1.5-2 h) was a **transmission-line fault with no alert active**.
3. **Wind Advisory: 33 windows in 5.8 years at TXZ192, 0 coincide (+/-6 h) with any documented Lakeway outage.** That is "no evidence of prediction", not "proven non-predictive" (public coverage misses small PEC feeder outages; see caveats). Recommendation: do not raise Wind Advisory above medium on outage grounds; freeze/ice/winter-storm family is the supported high-severity class.

## Method

- **Local ground truth:** HA `calendar.main_panel_wall_enphase_cloud_hacs_system_event_history`, queried week by week (month-long and longer windows time out; parallel calls time out). Earliest data found: an event spanning from 2026-08-29 21:58 CDT; queries for 2026-08-29 (day) and everything before 2026-08-29 time out / return nothing, i.e. the Enphase cloud feed retains ~6-7 weeks. Searched Sep 1 - Oct 15 for "off grid", "connected to the grid", "gateway rebooted", "generator". Weeks 2026-09-01..14, 09-22..10-15 were scanned from saved JSON with a regex; week 09-15..21 read in full.
- **Second local signal (rejected):** HA long-term statistics. Envoy frequency (hourly, since 2026-05-14) has ~60 gaps of 2-34 h, and Shelly frequency stats show multi-hour multi-device dropouts (e.g. 2026-07-08, 2026-09-07, 2026-09-12). These are known Envoy/WiFi flapping and recorder/HA gaps, not grid events (no matching off-grid calendar events). Not used as outage evidence. The recorder DB itself only holds states since 2026-10-08.
- **Public ground truth:** WebSearch/WebFetch (PEC, Austin Energy, KVUE, Fox 7, City of Lakeway). Note Lakeway is served by **both Pedernales Electric Cooperative and Austin Energy** (and the house's own utility not verified here). Many results were undated; undated items are listed but not correlated.
- **Alerts:** IEM archives `iem_TXZ192.json` (county zone, 302 alerts 2021-01-10..2026-10-16), `iem_TXC453.json` (Travis County FIPS, 354 products 2021-03-22..2026-10-01), `sbw.json` (WFO EWX storm-based warning polygons; point-in-polygon at -98.0159,30.3146 gives **32 point-covering Severe Thunderstorm Warnings, 0 Tornado Warnings** vs 131 county-level SVR products). Script: `.claude/tmp/corr.py` (not committed). Active = issue <= event_end+6h and expire >= event_start-6h.

## Table 1 - local ground truth (Enphase calendar, 2026-08-29 .. 2026-10-15)

| Event | Time (CDT) | Duration | Real outage? |
|---|---|---|---|
| "Your system is now off grid" -> "connected to the grid" | 2026-09-16 12:39 -> 12:57 | 18 min | **No - manual test**: generator turned on/off at 12:43/12:52, midday, no alert, no weather |
| "Generator turned on for maintenance" | 09-02, 09-23, 10-14 ~12:30 | ~10 min each | No (scheduled exercise) |
| "Gateway rebooted" | ~35 times, many at 23:1x nightly | 1 min | No grid signal; gateway/Envoy issue, not outage |

Real off-grid events found: **0**. Alerts active at TXZ192/TXC453 in the window: **0**.

## Table 2 - public documented outages affecting Lakeway, with alerts active (+/-6 h)

| # | Event | Cause | Scale / duration | Alerts active (IEM) |
|---|---|---|---|---|
| 1 | 2021-02-15..19 Winter Storm Uri, ERCOT load-shed | freeze / grid load-shed | statewide; days | Hard Freeze Warning, Wind Chill Warning, Winter Storm Warning, Winter Weather Advisory |
| 2 | 2023-01-31..02-03 ice storm (Fox 7 02-01; PEC timeline) | ice on limbs/lines (article: not wind) | >200,000 Central TX; PEC 40-50k peak; ~1 week to full restore; Lakeway dateline | Winter Storm Warning (only) |
| 3 | 2026-01-24 Arctic blast (Fox 7) | freezing temps | PEC 10 outages (Lakeway/Lago Vista), AE 9 customers - small | Extreme Cold Warning, Ice Storm Warning, Winter Storm Warning |
| 4 | 2026-06-04 12:30-14:00 CDT (KVUE/Yahoo) | Austin Energy transmission-line fault, western Travis | ~8,200 customers, <=1.5-2 h; Bee Cave+Lakeway | **None** |
| 5 | 2025-07-04 storms/flooding (PEC) | storms + flood; Burnet/Williamson hardest, Lakeway impact unconfirmed | unquantified for Lakeway | Flash Flood Warning, Flood Advisory, Flood Watch (no Wind Advisory) |

Undated/unplaceable (not correlated): PEC "widespread storms, high winds, heavy lightning" 7,500 -> <100 members in 2.5 h; Dripping Springs ~12,000-customer storm; Lakeway 86-location and 92-customer outages (Nextdoor, undated, one cause "public-caused damage").

## Table 3 - alert type vs outages (raw counts)

"Windows" = alert products issued 2021-2026 (TXZ192 + TXC453; SVR-point from polygons). "Windows with outage" = overlapping one of events 1-5 (+/-6 h). "Outages explained" = of 5 documented events.

| Alert type | Windows | Windows with outage | Outages explained (of 5) |
|---|---|---|---|
| Wind Advisory | 33 | 0 | 0 |
| Severe Thunderstorm Warning (county) | 131 | 0 | 0 |
| SVR warning, point-covering | 32 | 0 | 0 |
| Winter Storm Warning | 9 | 3 (Uri, 2023 ice, Jan 2026) | 3 |
| Ice Storm Warning | 1 | 1 (Jan 2026) | 1 |
| Hard Freeze Warning | 5 | 1 (Uri) | 1 |
| Wind Chill Warning | 4 | 1 (Uri) | 1 |
| Extreme Cold Warning | 2 | 1 (Jan 2026) | 1 |
| Winter Weather Advisory | 8 | 1 (Uri) | 1 |
| Freeze Warning / Cold Weather Advisory / Wind Chill Advisory | 7 / 6 / 4 | 0 | 0 |
| Flash Flood Warning | 29 | 1 (Jul 2025, unconfirmed Lakeway impact) | 1 |
| Flood Watch/Advisory | 20 / 132 | 1 (Jul 2025) | 1 |
| (no alert) | - | - | **1: 2026-06-04 transmission fault** |

Winter-family hit rate is crude: ~3 of 9 Winter Storm Warnings (33%) saw a documented outage; most of the remaining 6 windows had no public coverage (not necessarily no outage).

## Caveats

- n = 5 public events; local n = 0. Percentages are not meaningful; counts only.
- Public coverage is biased to large, newsworthy outages. Small PEC feeder/transformer outages from wind gusts (tens to low hundreds of customers) leave no news trail, so "Wind Advisory has 0 documented outages" is **absence of evidence**, not proof of absence.
- Wind-driven outages in this region plausibly occur with thunderstorm outflow (convective gusts) which is warned by SVR, not Wind Advisory. The 7,500-member PEC storm and Dripping Springs events fit that but are undated, so cannot be tied to a warning here.
- Event times for Uri and the 2023 storm are approximate windows, +/-6 h padding is generous; winter events span days so overlap with winter alerts is near-guaranteed (inflates winter recall by construction).
- The house's utility (PEC vs Austin Energy) was not verified; outage 4 was Austin Energy.
- Enphase gateway sees only grid loss at the main panel; microinverter/gateway-reboot noise is not outage.

## Recommended follow-ups (cards, not built)

1. Ask PEC (or Austin Energy, whichever serves the house) for outage history by feeder/account for the address - the only unbiased ground truth. Or export Enphase cloud event history monthly to the URA DB so a local ledger accumulates (calendar retains ~7 weeks).
2. Add a code trip-wire: record every real off-grid event (excluding generator-test windows) with the then-active alerts, to the DB, so the correlation self-builds.
3. Until then: keep Wind Advisory at medium; treat Winter Storm/Ice Storm/Hard Freeze/Extreme Cold as the outage-predictive class.

## Sources

- PEC freeze timeline: https://mypec.com/extraordinary-freeze-a-timeline-of-the-storm/
- Fox 7 ice storm (Lakeway, 2023-02-01): https://www.fox7austin.com/news/central-texas-weather-power-outages
- Fox 7 Arctic blast (2026-01-24): https://www.fox7austin.com/news/austin-weather-power-outages-central-texas
- Austin Energy Bee Cave/Lakeway 2026-06-04: https://www.kvue.com/article/news/local/austin-energy-outages-bee-cave-lakeway-travis-county-western/269-c840c74c-a08f-4d9f-a91d-389fc25c8328 and https://www.yahoo.com/news/weather-news/articles/thousands-austin-energy-customers-without-172204056.html
- PEC July 4 2025: https://mypec.com/pedernales-electric-cooperative-responds-to-july-4-storms-and-flooding/
- City of Lakeway PEC notice (undated): https://nextdoor.com/agency-post/tx/lakeway/city-of-lakeway/power-outage-234189675/
- Iowa Environmental Mesonet alert archives (VTEC, SBW) - local files in session scratchpad.
