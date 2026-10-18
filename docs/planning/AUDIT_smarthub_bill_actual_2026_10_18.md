# AUDIT: SmartHub "bill actual" input to EC is dead (read-only probe, 2026-10-18 CDT)

Probe run Sun 2026-10-18 14:32 CDT. Read-only: ssh ha `sqlite3 -readonly /config/home-assistant_v2.db`,
the `~/ha-config` mount, GitHub pages. Nothing changed. Account/location/street redacted
(`<ACCT>`, `<LOC>`).

## Answer first

1. **The EC input stopped on 2026-06-02.** The monthly sensor's last non-zero long-term-statistics row is
   2026-06-01 00:00 (state 313.9 kWh); every row from 06-02 onward is 0.0 (`statistics_meta` id 4701).
   The cause is in the integration, not in URA: its monthly poll returns an empty `USAGE` list, so it
   writes the literal fallback `0` (`smarthub/sensor.py:142-149`). Hourly/daily imports still work (see 1c).
2. **EC does NOT have a "bill actual vs predicted" feature in dollars.** SmartHub's sensor is consumed in exactly
   one place: a kWh *divergence attribute* on `sensor.ura_energy_coordinator_predicted_bill`
   (`energy.py:11562-11618`, `sensor.py:11087-11093`). The predicted bill itself comes from Envoy
   (`prediction_source: "envoy"`). The dead sensor currently makes that attribute show a false
   `utility_divergence_pct: 100.0`.
3. **Recommendation:** (d)+(c): do not build EC code now. Turn the bogus attribute off or bridge it with a
   config-only SQL sensor over the external statistic, and file the upstream issue (text in section 4).
   Details in section 3.

## 1. When and why it stopped

### 1a. Timeline (all from the recorder, `statistics`/`statistics_meta`)

| Fact | Evidence |
|---|---|
| Old entity `sensor.smarthub_energy_sensor` | meta 2535; 2025-08-21 -> 2025-10-31 |
| Renamed `sensor.smarthub_energy_<ACCT>` | meta 3240; 2025-10-31 -> 2026-02-07 (last >0 in Feb) |
| Renamed again to `sensor.smarthub_energy_monthly_usage_<ACCT>_<street>` (the one EC points at) | meta 4701; first row 2026-02-07 19:00. Matches upstream v2.0.4 (02 Feb) "fixes monthly aggregation for the entity" (releases page) |
| Net-meter / export channel appears | export external stat `..._return_sensor_...` (meta 6396) first row **2026-05-26**, first non-zero daily export 05-28 (4.9 kWh). Consistent with solar/net-metering going live late May |
| Monthly sensor counter drops 1422.6 -> 206.2 | 05-28 -> 05-29 (daily max of `state`, meta 4701). This is not the 1st-of-month reset the code implements; coincides with the net-meter appearance. Correlation only; mechanism unverified |
| Last non-zero | 2026-06-01 00:00 (313.9), rows from 06-02: 0.0 |
| Monthly `sum` frozen | 1736.5 from June through 2026-10-18 13:00 |
| Entity state now | `0.0`, updates every poll (states table, 2026-10-18 13:45:48), `last_reading_time` 2026-10-01 per operator |
| Config entry | smarthub entry created 2026-05-01 01:18 UTC (`core.config_entries`); it was re-added, so the rename history is across versions, not this entry |

Upstream: v2.2.0 / v2.2.0-alpha released 01 Jun; v2.3.0-alpha 08 Jul. Upstream issue #72
"No data for any version > 2.0.4" (opened 2026-06-07, open) shows the same symptoms with `TOTAL`
flow direction; maintainer says the fixed direction list is the root problem and a refactor is pending.
#70 and #62 are named as duplicates. Fork named in that thread: `cranksecurity/ha-smarthub-energy-sensor`
(not tested here). The 06-02 onset coincides with the 06-01 release and the late-May net-meter change; I could
not separate the two from recorder data alone. **Unknown.**

### 1b. Why the monthly sensor reads 0 (code, installed copy mtime 2026-10-17 23:50)

- `smarthub/sensor.py:137-142`: monthly query = `get_energy_data(start=first of current month, MONTHLY)`;
  if `data["USAGE"]` is missing/empty -> warning `"No data received from SmartHub API for location %s"` and
  state forced to `0` (line 145).
- `smarthub/api.py:205-250` (`parse_usage`): `USAGE` is only set when a series name equals
  `net_series` (if any) else `forward_series`. With 3 meters (FORWARD, REVERSE, NET), `api.py:212` logs
  "More then 2 meters"; REVERSE matches no `case` (`ParseType` has FORWARD/NET/RETURN/TOTAL only,
  `api.py:35-39`), so `api.py:224` logs "Unknown flow direction" and `return_series` stays empty.
  NET sets `net_series`, so `USAGE` should come from the NET series.
- What I could NOT establish: why the **monthly** response yields no matching series while hourly/daily do.
  The raw response is only logged at debug (`api.py:~202`, `_LOGGER.debug("Usage: %s", entry)`). Candidates:
  the MONTHLY timeframe returns no point for a partial current month, or series ids differ for MONTHLY.
  Both unverified. Cheapest discriminator: one poll with `custom_components.smarthub.api: debug`.

### 1c. Falsifier: the dead path is monthly only

The operator's quoted line has no "to populate historical" suffix, so it is the monthly path
(`sensor.py:142`), not the hourly/daily path (`sensor.py:265`). Consistent with the recorder: external
hourly `smarthub:smarthub_energy_sensor_<ACCT>_<LOC>` (meta 4699) has 8236 rows through
**2026-10-17 22:00** and daily (4700) through 10-17; export hourly (6396) and daily (6397) likewise.
Note the 6-hour poll (`poll_interval: 360`) and SmartHub lag mean the newest hour is ~16 h old now.

Useful, current numbers from those statistics (net import = positive net hours; export = negative net hours,
`api.py:149-153`): cycle 2026-08-23 -> 09-22: import 3669.4 kWh, export 249.7; cycle so far 2026-09-23 -> 10-17:
import 2204.1, export 236.7 (SQL on metas 4699/6396, local-time boundaries approximated at 05:00 UTC).
For comparison EC's Envoy-derived cycle import is 2108.97 kWh (predicted-bill attributes below), so
the surviving external statistic is a sane ~4.5% apart from Envoy for a part-cycle that ends ~16 h earlier. This
shows the data exists and is usable.

## 2. How EC consumes it

Producer: SmartHub integration monthly entity (above). Consumers (grep of `custom_components/universal_room_automation`
for `utility_meter|UTILITY_METER|billing_source`; `grep` for `recorder.statistics|statistics_during_period|get_last_statistics|async_add_external` returned nothing):

| Site | What |
|---|---|
| `domain_coordinators/energy_const.py:1431` | `CONF_ENERGY_UTILITY_METER_ENTITY = "energy_utility_meter_entity"` |
| `domain_coordinators/energy.py:609-612` | read from EC options into `self._utility_meter_entity` |
| `domain_coordinators/energy.py:11562-11618` | `utility_meter_divergence`: reads `hass.states.get(entity)`; only `unknown`/`unavailable` return None; state `0.0` is accepted as a real reading. `divergence_pct = |utility - envoy| / max(utility, envoy, 1) * 100` |
| `sensor.py:11087-11093` | copies `utility_kwh`, `envoy_kwh`, `utility_divergence_pct`, `prediction_source` into attributes of `EnergyPredictedBillSensor` |
| `energy.py:11585-11602` | `cycles_aligned` needs a `last_reset` attribute on the utility entity; the SmartHub entity exposes only `account_id`, `location_id`, `last_reading_time`, `meter_name` (`smarthub/sensor.py:~395-415`), so `cycles_aligned` is False even when working. Also SmartHub's month starts on the 1st (`sensor.py:137`) while EC's cycle starts on the 23rd (`energy_bill_cycle_day: 23.0`) |
| nothing else | `cycles_aligned` has no consumer outside this dict (`grep cycles_aligned` -> only energy.py). `energy_billing_source: auto` is a different axis (Emporia counters vs power integration, `energy_billing.py:159-195`), it does not read SmartHub |
| design intent | `docs/planning/PLANNING_UTILITY_METER_INTEGRATION.md:126` "B-Lite: divergence attributes only. No automatic source switching" - shipped as v4.2.17 (`git log -S`: 48e984993) |

Live now (`sensor.ura_energy_coordinator_predicted_bill`, 2026-10-18 14:31:02, state 196.78 USD):
`prediction_source: envoy`, `utility_kwh: 0.0`, `envoy_kwh: 2108.97`, `utility_divergence_pct: 100.0`,
`days_in_cycle: 25`, `cycle_start_date: 2026-09-23`. So: **the prediction is unaffected; the divergence attribute is
wrong (100%) and has been since 06-02.** There is no EC sensor, DB column, or decision that uses SmartHub for dollars
or for calibration (the B3 "bill calibration" deliverable was not shipped, per the B-Lite note). I did not find a
"bill actual" sensor anywhere in EC; if the operator expected one, it does not exist in the code I searched. Dollars
actual is also absent from the SmartHub integration (kWh only).

Prior art for (b): EC has no external-statistics reader. `hvac_override.py:19,1889,6466` uses the recorder instance
for other purposes (not statistics). So (b) is NEW code.

## 3. Options

| Option | Verdict |
|---|---|
| (a) point EC at another source | There is no other source of "what the utility measured". Envoy/Emporia are what the divergence is compared *against*. Pointless; an empty `energy_utility_meter_entity` is the only valid alternative, and that makes `utility_meter_divergence` return None (`energy.py:11573`), removing the false 100%. **Config-only**. |
| (b) EC reads external statistics | Possible (recorder `statistics_during_period` via executor works on `smarthub:` ids, which are statistics only and have no entity). NEW code in a coordinator for a display-only attribute. Marginal benefit small, cost: new reader, cycle-day math (cycle day 23 vs month), staleness handling. Park. |
| (c) config bridge | A template sensor cannot read long-term stats. A **SQL integration sensor** querying `statistics` for `metadata_id` of `smarthub:smarthub_energy_sensor_<ACCT>_<LOC>` with `start_ts >= cycle start` would give net import for the 23rd-based cycle with zero URA code. Unverified: whether the SQL integration is installed (unknown), and the query needs the cycle start hard-coded or computed in SQL. It would also lack `last_reset`, so `cycles_aligned` remains False (as it is today). |
| (d) wait for upstream | Maintainer acknowledged #72 on/after 2026-06-07; it is still open at probe time with no linked PR (GitHub issues page). Months-old, and the refactor is described as pending. Not a plan on its own. |

**Recommendation.** Config-first: (1) Stop the lie now by clearing `energy_utility_meter_entity` in the EC options
(operator action, nothing else reads it) or accept the 100% as known-bad. (2) If the actual-vs-predicted *kWh* comparison is wanted,
build the SQL-sensor bridge (c) in HA config and point EC at it; the wiring already exists, EC needs no change. Compare
margins: even with the bridge, the attribute is a display of kWh divergence with no downstream consumer; the dollars
"actual bill" the operator describes is not something SmartHub exposes at all. (3) File the upstream issue (section 4), and
optionally try the cranksecurity fork or one debug-log poll to learn why monthly is empty. (b) revisit only if a real
consumer (calibration, B3) is carded.

Not decided here, for the operator: whether a bill-in-dollars comparison is wanted (would need the PEC bill amount, which
SmartHub integration does not provide).

## 4. Upstream issue text (gagata/ha-smarthub-energy-sensor)

**Title:** Net meter with 3 channels (FORWARD / REVERSE / NET): REVERSE flow unknown, monthly entity stuck at 0 since June

**Body:**

Environment: Home Assistant (2026.10-ish), integration v2.3.0-alpha code (manifest.json still reads 2.2.0),
cooperative host pec.smarthub.coop, `poll_interval` 360, account has a solar installation on a net meter
(`isNetMeter: true`).

Symptom: `sensor.smarthub_energy_monthly_usage_<ACCT>_<street>` reports `0.0` with
`last_reading_time` = first of the month. Its last non-zero long-term-statistics row is 2026-06-01. Before
that it tracked monthly kWh (reset on ~05-28/29, coincident with solar export starting on 2026-05-26).

What still works: the imported external statistics. `smarthub:smarthub_energy_sensor_<ACCT>_<LOC>` (hourly) has rows
through the most recent hour, plus `_daily`, and the `smarthub_energy_return_sensor` (export) series. So HOURLY and
DAILY queries succeed; only the MONTHLY poll returns no `USAGE`.

Log lines on each poll:

```
WARNING (MainThread) [custom_components.smarthub.api] More then 2 meters in usage data: [<three meters: FORWARD (consumption), REVERSE (generation), NET; seriesIds redacted>]
WARNING (MainThread) [custom_components.smarthub.api] Unknown flow direction in meter: {... 'flowDirection': 'REVERSE' ...}
WARNING (MainThread) [custom_components.smarthub.sensor] No data received from SmartHub API for location <SmartHubLocation id=<LOC> ...>
```

(The last one has no "to populate historical" suffix, so it is the monthly entity path at `sensor.py` ~L142,
not the statistics backfill.)

Analysis from reading the code: `ParseType` only has FORWARD / NET / RETURN / TOTAL (`api.py`), so the `REVERSE` meter
falls through `case _` and `return_series` stays empty (export is still derived from the NET series, which explains why
the return statistic works). `USAGE` is only populated when a series name equals the NET (else FORWARD) series name; for the
monthly request that match apparently does not happen, so `sensor.py` writes the fallback `ENERGY_SENSOR_KEY: 0`.
This looks like the same family as #72 / #70 / #62 (unknown flow direction) but with `REVERSE` rather than `TOTAL`.
I have not captured the raw monthly response; I can attach `custom_components.smarthub.api: debug` output if that helps.

Suggestions: map `REVERSE` to the return series; do not publish a hard `0` when the monthly response is empty (return
`None`/unavailable, or keep the previous value) so downstream consumers can tell "no data" from "zero usage"; as
asked in #72, expose whatever flow directions the provider reports.

## 5. Plan-completion / open items

- Not done (read-only): no config change, no debug-log capture, no test of the cranksecurity fork, no check that
  the SQL integration is installed.
- Unknown: exact reason the MONTHLY response is empty; whether the late-May counter drop is the net-meter switchover.
- Log lines in section 4 are quoted from the operator's brief; `ssh ha` has no journalctl and
  `/config/home-assistant.log` is 0 bytes, so I could not re-read them (unverified by me).
- Hygiene note: `core.config_entries` holds the SmartHub login in plaintext, and a `grep` over it echoed the
  email/password into my tool output; neither is reproduced here.
