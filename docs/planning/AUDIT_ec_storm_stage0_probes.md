# AUDIT: EC storm / blind decisions, Stage 0 probes (P1-P4)

Run 2026-10-16 11:2x-11:5x CDT by ura-prober. Read-only. Plan: `PLANNING_ec_storm_and_blind_decisions.md` Rev 2 (commit 95f403597), section 6 Stage 0.
Data: `ssh ha` sqlite (ro) on `/config/home-assistant_v2.db` (recorder window starts **2026-10-09 04:12 CDT**, 7 days) and the URA DB (`ura_activity_log` from 2026-09-16 10:50 CDT; timestamps are UTC ISO). Public: api.weather.gov, NWS/OWM docs, HA core source (GitHub dev branch).

**Limit that shapes P1 and P4(ii):** the probe has no HA API token (`ha core info` = unauthorized; the HA MCP tools are not available to this agent). So `weather.get_forecasts` and `calendar.get_events` were NOT called live. P1 is by integration source + docs + recorder health; P4(ii) rests on the 10-15 audit. Both need one live call (Developer Tools) before their gates are fully closed.

| Probe | Verdict |
|---|---|
| P1 forecast providers | **PARTIAL-GO** (GO by source/docs; live call not run; 1 provider qualifies) |
| P2 NWS feed | **GO** (a-e answered; findings change D-B3 sizing) |
| P3 product codes | **PARTIAL** (10 of 28 codes verified; plan table has a WRONG code for SVR) |
| P4 outage witness | **(i) NO evidence either way, local witness candidates are poor; (ii) PARTIAL; (iii) PARTIAL; (iv) done** |

## P1 forecast provider probe (gates Stage C)

Configured providers (plan line 57) and their HA integration, from `.storage/core.entity_registry` + `core.config_entries`:

| entity | platform / mode | hourly? | temperature | precip_prob | gust | wind_speed | condition | 24 h health (recorder, `unavailable` rows / rows) |
|---|---|---|---|---|---|---|---|---|
| `weather.phalanxmadrone` | openweathermap, mode `v3.0` (config_entries options) | yes (`FORECAST_DAILY|HOURLY` when mode v3.0; core `openweathermap/weather.py:99-104`) | yes | **yes** (`precipitation_probability=round(pop*100)`, `openweathermap/coordinator.py:183-205`) | yes ("where available", OWM docs) | yes | yes | 0/143 |
| `weather.madronehaos` | open_meteo | yes (`open_meteo/weather.py:66-67`) | yes | **no** (hourly builder, lines 179-260, sets no `precipitation_probability`; only `precipitation` amount) | yes | yes | yes | 2/49 |
| `weather.madroneweather_tracker_dynamic_weather_madroneweather_tracker` | dynamic_weather (custom) | **no, daily only** (`/config/custom_components/dynamic_weather/weather.py:80` `FORECAST_DAILY`) | n/a | n/a | n/a | n/a | n/a | 3/107 |
| `weather.nws_30_314635_98_015861_kryw` (exists, not a configured WPM provider) | nws | yes (`FORECAST_HOURLY|TWICE_DAILY`) | yes | yes (`probabilityOfPrecipitation`) | **no** (`nws/weather.py` `_forecast` sets wind speed only) | yes | yes | 0/92 |
| `weather.generac_2325624_weather_2` | generac | not a forecast source | | | | | | 2/15 |

- Horizon: OWM One Call 3.0 = 48 h hourly (https://openweathermap.org/api/one-call-3: "hourly forecast for 48 hours", `hourly.pop`, `hourly.wind_gust` "where available"). Open-Meteo / NWS hourly horizon not verified here (unknown).
- Update cadence: not measured (forecasts are not recorded; recorder `weather.*` rows only carry current conditions). Unknown.
- Rev 3's "no gust" claim: wrong for the configured set. Gust IS carried hourly by OWM and Open-Meteo; absent only in NWS.
- **Gate:** GO requires >=1 healthy provider with hourly temperature + precip probability for >=48 h. **Exactly one qualifies (OWM `weather.phalanxmadrone`, 48 h, health 0/143 in 24 h).** Open-Meteo lacks precip probability, dynamic_weather lacks hourly. `weather.nws_*` qualifies on fields (horizon unverified) and is a candidate second source but is not a configured provider.
- `FORECAST_PRECIP_CONFIRM_PCT`: **not set by this probe** (no recorded pop series; needs a live pull). Unknown.
- **Impact:** Stage C stays buildable, but single-provider (OWM). The D-C1 `hourly_outlook` must treat "OWM stale/unavailable" as None (no corroboration), not as fallback to Open-Meteo (it cannot supply the precip-confirm leg; it can supply freeze via temperature and gust). Adding the NWS entity as a second hourly source is a one-line provider add but is a plan change (cards, not done here). Before Stage C build: one live `weather.get_forecasts type=hourly` on `weather.phalanxmadrone` to confirm >=48 entries with non-null `precipitation_probability`.

## P2 NWS feed semantics

Entities: alerts `sensor.nws_alerts_gps_30_3146_98_0159_nws_alerts_alerts`, timestamp `sensor.nws_alerts_gps_30_3146_98_0159_nws_alerts_last_updated` (registry platform `nws_alerts`; integration `/config/custom_components/nws_alerts/coordinator.py`).

**(a) 10-15/16 WIY recorder history** (136 alert-sensor rows 10-09..10-16; script output summarised):
- 10-15 11:11:29 `Alert` WIY, Onset=Expires=2026-10-16T04:00, Ends=19:00, Sent 10-15 11:10.
- **10-15 23:51:36 the original `Alert` message is gone and replaced by an `Update`**: Sent 23:50, Onset 04:00, **Expires 10-16T19:00**, Ends 19:00. State count stayed 1 (replace, not append) .
- 10-16 10:27:37 a second `Update`: Sent 10:26, **Onset moved to 10:26** (hazard already in effect), Expires/Ends 19:00. Count still 1.
- Answers: the alert did not leave the feed at Expires=04:00 because the Update (23:50) had already superseded it with Expires=19:00; **the feed was never without a WIY inside [Onset 04:00, Ends 19:00]** (state=1 continuously 23:51:36 -> 10:27:37 -> now; 0 `unavailable` rows in 03:00-05:00 or anywhere after 10-12 22:24). The Update arrived ~4 h before Onset. Hence 10-15's missed hold was classification (WIY not matched), not feed loss; D-B3 memory is insurance, consistent with "built regardless".
- Observed fixture shape for the memory test: Alert and Update are **separate** feed entries only while both are active; here NWS removed the superseded Alert (the earlier 10-09 AQA case kept 2-4 same-event messages with different Sent concurrently, so both patterns occur).

**(b) `?point=` polygon-exact? GO: yes, observed live.** Docs are silent (https://www.weather.gov/documentation/services-web-alerts only gives the example; says many alerts are zone-defined). Live cross-check 2026-10-16 (script `scratchpad/pip.py`): active Severe Thunderstorm Warning with polygon (`api.weather.gov/alerts/active`, PA zone PAC005): `?point=` at a point inside the polygon returned that SVW; `?point=` at a point inside the affected county zone but outside the polygon (40.6740,-79.6803) did NOT return it (a zone-only Freeze Watch was returned for both). n=1 warning, so "exact" is supported not proven; no TOW was active to test. **Q7 impact:** `INCLEMENT_UNVERIFIED_POLYGON_TIER` can stay `"table"`; the "polygon not exact" branch is unnecessary on this evidence (keep the switch as a rung-1 constant).

**(c) Watch onset semantics:** from `alerts/active` (553 alerts nationwide, 2026-10-16): for Freeze/Fire Weather/Gale/High Wind/Coastal Flood/Flood Watches, `onset - sent` is **positive in 100% of Alert and Update messages (median 15-37 h)**, i.e. `onset` = **hazard start**, not issue time. When the hazard is already underway the Update re-stamps onset = sent (WIY 10:26 above; Flood/Typhoon Watch Updates onset-sent = 0). Wind Advisory: 47% future onset, rest 0. Not observed for WSA/SVA/TOA (none active). D-B1's `start = Onset or Sent` is right; `now < start` suppression is correct for watches.

**(d) Feed timestamp:** entity = `sensor.nws_alerts_gps_30_3146_98_0159_nws_alerts_last_updated`. Value = `datetime.now().isoformat()` (naive LOCAL, microseconds): e.g. `2026-10-09T21:52:27.748610` (`coordinator.py:68,98,126,188`). Changes every successful poll: 10,321 rows over 7.3 d (~1/min, interval DEFAULT_INTERVAL=1). Gaps >150 s between rows: 10 in 7 d, **max 302 s** (10-13 11:28), plus the unavailable episodes below. So `State.last_changed` advances each minute and `NWS_ALERTS_STALE_S` must be **> ~310 s** (suggest rung-1 default 600 s) or it self-triggers. Caveat: recorder `last_changed_ts` is NULL when equal to `last_updated_ts`; in the live State object last_changed is populated, so the plan's usage is fine.

**(e) Behaviour across drops:**
- Both entities go `unavailable` together (same timestamp to the second): **55 episodes 10-09 21:51 -> 10-12 22:24, mean 74 s, max 245 s, none since 10-12 22:24.** This is the `UpdateFailed` path (`coordinator.py` `except Exception -> UpdateFailed`; HTTP non-200 raises too). Confirmed from recorder, not assumed.
- The empty-with-fresh-timestamp path exists in code (AttributeError return `:68`; also a 200 without `"features"` returns the zero default with fresh timestamp, `:126`) but is **not distinguishable in the recorder**: the only `state=0` interval (10-10 19:00:42 -> 10-15 11:11) corresponds to AQA Expires 10-10 19:00 (a real expiry). Per-alert parse errors (`KeyError/TypeError`) drop that alert with only a log warning (`coordinator.py` alert loop) - another silent-loss path.
- **Impact:** D-B3 stale rule (unavailable OR last_changed too old) is validated: unavailable is the dominant failure and routinely lasts 1-4 min, so memory must bridge at least ~5 min (the plan's bridge is end-time based, which covers it). The "healthy but empty" path cannot be detected from the sensors; the memory is the only defence there.

## P3 product codes (gates D-B2)

`eventCode.NationalWeatherService` differs from SAME (CAP guide / NWS training show FLW vs FAW pairs). API historical queries returned **0 alerts for every product for 2024-2026** (api.weather.gov retains only recent weeks), so history could not be used; codes below come from the live `alerts/active` feed (553 alerts) and `alerts?start=2026-09-16` (500, truncated), 2026-10-16.

| Product | NWS code observed | Status |
|---|---|---|
| Severe Thunderstorm Warning | **SVW** (SAME `SVS`/`SVR`) | verified. **Plan/NWS-SAME list say SVR; the feed value is SVW.** |
| Tornado Warning | **TOW** | verified (09-16..10-16 history query) |
| Freeze Warning / Freeze Watch | FZW / FZA | verified |
| High Wind Warning / Watch | HWW / HWA | verified |
| Tropical Storm Warning | TRW | verified |
| Wind Advisory | WIY | verified (house feed 10-15) |
| Winter Weather Advisory | WWY | verified |
| Winter Storm Warning/Watch, Ice Storm Warning, Hard Freeze Warning/Watch, Extreme Cold Warning/Watch, Wind Chill Warning/Watch/Advisory, Cold Weather Advisory, Blizzard Warning, Tornado Watch, Severe Thunderstorm Watch, Extreme Wind Warning, Hurricane Warning/Watch, Tropical Storm Watch | not in any retrievable feed | **unverifiable now** (SAME list https://www.weather.gov/nwr/eventcodes gives WSW, WSA, BZW, TOA, SVA, EWW, HUW, HUA, TRA, but SAME is not the NWS code; e.g. SVR vs SVW) |

- Verdict **PARTIAL**. Per the plan rule, every unverified row ships as **exact-name match only** (`code=None`). Two corrections: (1) the plan's SVR/TOR rows must use `SVW`/`TOW` if coded (SVA/TOA unverified); (2) the `inclement_code_drift` trip-wire (code vs name disagree) will fire spuriously on SVR/TOR if the table is coded with SAME values - hence code only the verified rows.
- **Impact:** D-B2 table gate satisfied in degraded form; Stage B can proceed with names. The drift row becomes the live verifier for the rest (first WSW/ISW etc. in winter logs the observed code).

## P4 outage witness probe (gates D-L2)

**(i) `switch.enpower_482348004678_grid_enabled` (platform enphase_envoy):** recorder 10-09 04:12 -> 10-16: 106 rows, states only `on` (54) and `unavailable` (52); **time share on 79.8 %, unavailable 20.2 %**; **zero non-None transitions (never `off`)**. But the window contains **0 real off-grid events** (calendar: only generator-maintenance and ~35 gateway reboots; audit `AUDIT_outage_alert_correlation.md` Table 1), so "never goes off" is vacuous: **not discriminating, cannot be decided from available data.** The one off-grid event (2026-09-16 12:39-12:57 CDT) predates the recorder (starts 10-09); the HA statistics for Envoy frequency/voltage show flat 60.0 Hz min=max=60.0 in the 12:00 and 13:00 hours (no signature), grid_power sensors have no statistics. URA DB during that event shows only `anomaly` "Span Left ... power when off grid" (17:45:34Z), `notification` "Envoy Offline" (17:55:34Z) and "Generator Running" (18:00:35Z, CRITICAL).
- Sibling candidates (all 10-09..10-16): `binary_sensor.enpower_482348004678_grid_status` identical profile to grid_enabled (106 rows, 79.8 % on / 20.2 % unavailable, no transitions); `binary_sensor.envoy_stream_grid_connected` 100 % unavailable; **`sensor.iq_gateway_hacs_grid_mode` flaps `on_grid` <-> `off_grid` 98 times in 7 d (196 transitions) with no real outage -> unusable as a witness (false-positive generator)**; `binary_sensor.enpower_..._communicating` goes off ~10x on 10-16 03:32-06:27.
- Verdict **NO-GO for adopting any local witness on evidence; not evidence to drop it either.** Operative facts: the local witness would read `None` 1/5 of the time (the plan's `None` never transitions rule is essential), and the most "obvious" alternative flaps. The discriminating observation (does grid_enabled/grid_status go `off` in a real islanding) requires one real or deliberate off-grid event, which is operator action and not done here. **Impact:** D-L2(i) ships inert-tolerant as designed but is unvalidated; D-L2(ii) cloud sweep is the only evidenced source. Do not use `iq_gateway_hacs_grid_mode`.

**(ii) `calendar.get_events` 48 h within 30 s: NOT RUN (no API access).** Evidence only from the 10-15 audit: week-by-week queries worked, month+ and parallel queries timed out, retention ~7 weeks (earliest 2026-08-29). Entity availability in the recorder: `calendar.main_panel_wall_enphase_cloud_hacs_system_event_history` `off` 98.6 %, `unavailable` 0.21 %, with 19 short (~1 min) `unavailable` blips in 7 d. Verdict **PARTIAL**: 48 h is smaller than the working weekly window, so likely holds; run once live before D-L2(ii). Sweep lookback must be <= ~6 weeks and the sweep must tolerate a 1-min unavailable blip.

**(iii) Exact summaries:** from the audit only (not re-queried): "Your system is now off grid", "...connected to the grid", "Generator turned on for maintenance", "Gateway rebooted". Exact generator-off and on-grid strings **unverified**; the parser must match by substring, not equality, until one live pull records them. Cross-check: URA `sensor.ura_energy_coordinator_generator_status` saw `running` 10-14 12:32-12:44 CDT (maintenance exercise, not off-grid).

**(iv) Calendar platform:** entity registry: `calendar.main_panel_wall_enphase_cloud_hacs_system_event_history`, **platform `enphase_ev`**, not disabled, config_entry `01KR1YNV6PKXMSZSXY42PVGJ25`; it is the **only** `calendar.*_system_event_history` entity (so exactly-one resolution holds today). `OUTAGE_CALENDAR_PLATFORM = "enphase_ev"`.

## Stage impact summary

- **Stage L:** D-L1 unchanged (feed semantics confirmed; the ledger must log both Alert and Update rows, Update supersedes). D-L2(i) local witness is unvalidated (vacuous test, 20 % None, flapping sibling); D-L2(ii) sweep plausible but needs one live 48 h call and substring parsing; platform `enphase_ev`.
- **Stage A:** unaffected by probes.
- **Stage B:** GO. D-B1 start/end rule confirmed; Q7 polygon switch can default `"table"`; D-B2 table codes: only verified rows may carry a code (SVR->`SVW`, TOR->`TOW`), the rest name-only.
- **D-B3:** stale threshold must exceed ~310 s (poll gap max 302 s); unavailable episodes 1-4 min; healthy-but-empty path not detectable.
- **Stage C:** single qualifying provider (OWM); live `get_forecasts` confirmation required; `FORECAST_PRECIP_CONFIRM_PCT` still unset.

## Unknowns left

OWM/Open-Meteo/NWS forecast cadence and Open-Meteo/NWS hourly horizon; live hourly forecast payloads; codes for 18 winter/watch/tropical products; whether grid_enabled/grid_status flip in a real islanding; exact generator-off / on-grid calendar summaries; live 48 h calendar call latency.
