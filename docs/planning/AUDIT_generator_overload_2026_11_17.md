# AUDIT: Generac overload fault (E2100) and house demand, 2026-11-16 (Mon)

Read-only probe, run 2026-11-19 08:3x CST. Recorder: ssh ha /config/home-assistant_v2.db. Helpers: .claude/tmp/genload_*.py. All times CST.

## Date correction
Today is Thu 2026-11-19, so Monday = 2026-11-16, not 11-17. The overload fault is on 11-16. A second, short outage happened Tue 11-17 (below).

## 1. Generator integration (platform `generac`, registry-resolved; 27 entities, device "generac_2325624")
Exposes only: status / status_text / status_label, run_time (constant 10.0), protection_time, battery_voltage, signal_strength, outdoor_temperature, last_seen, warning / maintenance / connected binaries, model_number (G00723510), serial. NO output W, amps, voltage, frequency, fuel type, or fault history. Fuel type: unknown (not exposed). Model G00723510 could not be matched to a spec page.

Generac states (recorder, states_meta + states):
- 11-14 14:31:18 Exercising, batt 12.6 V; 14:37:30 Ready, 13.5 V (normal exercise).
- 11-16 08:36:48 Ready; last_seen 15:11:49Z = 09:11:49 CST; Ready at 09:13:20 poll.
- 11-16 09:15:24 status Stopped; status_text "The generator has experienced an overload fault. Please shutdown load on The generator and clear the fault. (E2100)"; label "Service required."; batt 13.0 V; signal 0%. No "Running" state was ever captured (cloud poll about 15 min, and the HA link was unavailable 09:04:34-09:08:51).
- Status stays Stopped through 11-18 (fault never cleared).

## 2. Timeline 11-16
- 08:44 normal load steps 0.9 to 4.6 kW (HVAC/pool; baseline).
- 09:04:23-09:04:48 last SPAN / Envoy / Enpower / Generac-cloud samples; all go unavailable (HA network and Enphase dark). Utility outage starts about 09:04:25 (inferred; Enpower reports grid off only at 09:08:01 after it reboots).
- 09:04 to 09:08:17 SPAN panel status off (3.7 min, whole house dark in SPAN data).
- 09:08:01 Enpower grid_status off. 09:08:17 SPAN back in panel_backup on batteries; Encharges total 9,998 W discharge at 09:08:23 (8 units, 1.14-1.48 kW each); storage_mode self_consumption; pcs_battery_oversubscription ON at 09:08:57.
- 09:09:33-09:09:48 collapse: Envoy load 22.9 kW to 1.6 kW, PV -187 W.
- 09:10:06 SPAN on_grid; 09:10:16 Enpower grid_status on (grid/"grid" returns; import 2.1 kW then 5 kW).
- 09:15:24 Generac cloud reports E2100 overload.
- Gap: the generator's own run window and fault instant are NOT in the data. Fault lies between the last "Ready" report (09:11:49 device time) and 09:15:24, or earlier but unreported while HA/cloud link was down. Unresolved.

11-17 (Tue): Enpower grid off 15:04:38 to 15:06:27; SPAN dark about 15:00:52-15:04:38 (same ~3.5 min gap, so the gap looks like Enphase/network reboot, not generator). Batteries carried only 0.8-1.0 kW. Generac status stayed Stopped/Service required (it was unable to run). No overload then.

## 3. Demand at the event
| Moment | Source | W | A @240V |
|---|---|---|---|
| 09:04:08 pre-outage | Envoy load_power | 4,573 | 19 |
| 09:04:08 | SPAN panels 1+2 sum | about 4,750 | 20 |
| 09:08:01-09:09:33 island | Envoy load_power (CT) | 20,012-22,859 | 83-95 |
| same | Envoy net_power_consumption_2 (energy balance = PV 1.4 + battery 9.9 kW) | 11,309 | 47 |
| same | SPAN panels 1+2 (pool, ACs shed in backup) | 3,000-3,300 | 13 |
| 09:10:49 grid return peak | Envoy load_power | 7,271 | 30 |
Pool pump restart 4,929 W at 09:10:22 (SPAN 15 s sample). EVSE (SPAN garage_b_evse) 44-55 W: not charging. Furnace 166 W; ACs under 50 W: no compressor start recorded. Sample limits: Envoy 10 s, SPAN 15 s, so sub-second inrush is invisible.

Reading the 20-23 kW: load_power (20.0 kW at 09:08:23) equals net CT (10.014) + battery discharge (9.998). That is a double count of the battery output, so it is not trustworthy as true load. Energy balance gives about 11.3 kW; SPAN shows about 3.1 kW. The 8 kW SPAN-vs-balance gap is unexplained. Pre-event Envoy (4.6 kW) and SPAN (4.75 kW) agreed, so the divergence is islanded-mode only.

## 4. Guardian 22 kW limits (sources)
- generac.com 7042 page (https://www.generac.com/residential-products/standby-generators/gaseous/22kw-standby-generator-wifi-enabled-7042/): LP 22,000 W; NG 21,000 W; main breaker 100 (amps presumed). Rated amps not listed.
- Third-party listing (outboundpower.com via search summary; the fetch was rate-limited, not verified directly): LP 22 kW / 91.7 A, NG 19.5 kW / 81.3 A at 240 V, single phase. Generac's own page says NG 21 kW (87.5 A computed), so NG rating differs by source (19.5 vs 21 kW).
- Overload alarm: Generac "OVERLOAD REMOVE LOAD", codes 2100-2103 (https://support.generac.com/s/article/What-does-it-mean-when-my-generator-displays-an-alarm-Overload-Remove-Load-error-codes-2100-2103); no amp or time threshold is given there. Underspeed 1600-1603 is a separate alarm that can be caused by overload, fuel system or maintenance (https://support.generac.com/s/article/What-Does-It-Mean-When-My-Generator-Displays-an-Error-Code-Underspeed-Code-1600). Clear: OFF then ENTER on Guardian, with loads off.

## 5. Verdict
Not settled. Evidence: no recorded demand while the generator could have been supplying exceeds about 7.3 kW (30 A), which is 1/3 of rating, so the data leans AWAY from a legitimate continuous overload. The only above-rating figure (20-23 kW) is a battery double count and occurred while the batteries (not the generator) carried the house. Caveats: the generator's run window is unobserved, and a 3.5-min dark gap precedes everything. A transfer-moment surge (all loads plus Enphase batteries accepting the "grid" and charging) is plausible but unmeasured. Evidence to settle: Mobile Link / controller event log (alarm timestamp, run hours, Underspeed codes 1600-1603), the controller's fault history, fuel type and pressure, inrush clamp or logger on the generator output during an exercise with the Enphase batteries connected, and checking that Enphase generator-input / battery charging does not add load on transfer.
