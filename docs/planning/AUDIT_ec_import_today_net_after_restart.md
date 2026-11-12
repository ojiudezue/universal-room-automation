# AUDIT: EC "Energy Import Today" falling after restart (2026-11-12)

Probed 2026-11-12 16:37 CDT (22:37Z). Read-only. Method: code read, HA REST history, live core.config_entries.

## Answer (verdict: NOT a regression, NOT restart-caused)

`sensor.ura_energy_coordinator_energy_import_today` is a NET sensor by design: `import_kwh_today - export_kwh_today`.
- Producer: `sensor.py:12198-12212` (`EnergyImportTodaySensor.native_value` returns `round(import_kwh - export_kwh, 3)`). Its docstring (`sensor.py:12176`) reads "Net grid exchange today (positive=import, negative=export)". `state_class=TOTAL` at `sensor.py:12190` exists because it can decrease.
- Introduced in v3.14.8 (commit 634a8424, 2026-03-13); README_v3.14.8.md:26 says "Now shows net grid exchange (import - export)". Nothing in v5.108.9..v5.108.13 changed this formula. `git log v5.108.9..HEAD` on `energy_billing.py` and `energy_billing_counters.py` returns no commits. The v5.108.10 battery charge split (9e3d52f5, 2c110837, 1c0f1a8b) touched neither file; it only touched `sensor.py`.
- It "tracked Emporia import all morning" only because export was ~0 until after the restart. Recorder history of the Emporia export counter `sensor.main_panels_mains_vue_3_mainstogrid_energy_today`: 0.0009 at 11-12 15:15Z, 5.01 at 19:42Z, 12.13 at 20:35Z, 17.38 at 21:36Z, 19.08 at 22:37Z. Solar export started around 19:30Z, i.e. just after the 18:56Z restart. Pre-restart sensor attributes: import_kwh 19.724, export_kwh 0.001 (18:10Z). Net = import, so the two lines overlapped.
- After restart: import_kwh = 19.859 (matches Emporia from-grid 19.843), export_kwh climbs with the Emporia export counter, and 19.859 - 19.172 = 0.687 (22:22Z). Live attributes confirm: import 19.859, export 19.172, net_cost 0.8733.
- The 0.687 value equals import minus export, exactly as coded. Both leg accumulators are correct against Emporia ground truth (within 0.02 kWh).

## Falsification checks run
- If a restart had corrupted the import accumulator, the `import_kwh` attribute would drop. It stayed 19.859 (19.835 at 18:56:59Z, then 19.859 at 21:39Z). Disproved.
- If export had been double-booked, export_kwh would exceed the Emporia export counter. 17.382 vs counter 17.38 at 21:36-21:39Z; 19.172 vs 19.085 at 22:37Z (the 22:22Z accrual lags one Emporia ~15-min update). Disproved.
- Envoy cross-check (from the brief: net consumption delta 18.3, production 19.7) is consistent with real import ~19-20 and real export ~19. Not re-measured here.

## Counter mode details (for the record)
- Config (live CM entry): `energy_billing_source=auto`, `energy_grid_import_entity=sensor.mains_vue_3_mainsfromgrid_energy_today`, `energy_grid_export_entity=sensor.main_panels_mains_vue_3_mainstogrid_energy_today`. Both kWh slots, so `_is_counter_mode()` is true (`energy_billing.py:194-205`). The room-entry options `grid_import_sensor` (Envoy lifetime net consumption) and `grid_import_sensor_2` (Emporia) are NOT the billing counter; billing reads the CM-entry slots.
- Counter accrual: `energy_billing.py:447-477` adds per-slice `imp_kwh` / `exp_kwh` to `_import_kwh_today` / `_export_kwh_today` via `CounterAccrualTracker.tick` (`energy_billing_counters.py`). Restore: `restore_daily` (`energy_billing.py:597-654`) restores the counter baselines first (`:628-631`) and the day totals only if snapshot_date == today (`:645-646`). I did not trace a restart where the snapshot was absent; the live numbers show no loss.
- Restart gap in the sensor series: `unknown` at 18:56:38Z, 19:49:06Z and 21:51:54Z is the sensor reading `manager is None` / `energy is None` (`sensor.py:12200-12205`) while the coordinator boots. 18:56Z is the v5.108.11 restart. 19:49Z and 21:51Z (15:51 CST) are two further transient unknowns (the export-today sensor shows the same). I did not establish what caused those two; likely reloads or restarts per the brief (not verified in journald).

## Blast radius
- Cost sensors NOT affected. `cost_today` = import_cost 1.707 - export_credit 0.834 = 0.873 (live `net_cost` attr 0.8733). The drop from 1.69 (17:25Z) to 0.87 is real export credit, not a bug. Cost is derived from the two gross accumulators (`energy_billing.py:459-477`), never from the net sensor.
- Cycle totals / bill forecast / DB: fed from `_import_kwh_cycle`, `_export_kwh_cycle`, `_cost_this_cycle` (gross legs), not from this sensor. Unaffected.
- Consumers of the net sensor itself: dashboards / Energy-dashboard statistics (it is `state_class=TOTAL`, `device_class=ENERGY`). I grepped `custom_components` only; the shell glob failed on the repo-side search, so dashboard consumers were not enumerated (unknown).
- Earlier restarts (11-11 19:24 CST, 11-12 13:48 CST): export counter on 11-11 was 0.25-0.94 kWh all day (low), so the net/gross gap was < 1 kWh and would not have looked like a fall. Today's gap only became visible because export reached ~19 kWh. I did not pull per-restart sensor attributes for 11-11.

## Fix shape
No code bug. Options for the operator if the name is misleading:
1. Config-first / do nothing: read `import_kwh` attribute (or `sensor.mains_vue_3_mainsfromgrid_energy_today`) for gross import.
2. Cheap clarity fix (Tier 1): rename the friendly name "Energy Import Today" to "Energy Net Grid Today" (changes `sensor.py:12198` name only; entity_id stays via registry) and/or add a gross `EnergyGridImportToday` sensor reading `import_kwh_today`. Marginal benefit is display only; park unless dashboards mislead again.
3. Do NOT change the net formula: other consumers may rely on it since v3.14.8 (not enumerated).

## Not verified
- Dashboard/PWA/NM consumers of the net sensor.
- Cause of the 19:49Z and 21:51Z `unknown` windows.
- Journald restart timeline for 11-11/11-12.
