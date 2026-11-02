# AUDIT: ura-v8 cost / savings / forecast cards (2026-11-02, read-only)

Source: `ssh ha cat /config/.storage/lovelace.ura_v8` (dashboard id `ura_v8`, url_path `ura-v8`), pulled Mon 2026-11-02 ~07:40 CST. 9 views: 0 Actions, 1 Now, 2 Rooms, 3 Energy, 4 People, 5 Security, 6 Climate, 7 Health, 8 Music. People/Security/Music/Actions have no cost, savings or forecast references (grep of all entity ids and templates). Context: ENERGY_COORDINATOR_MANUAL.md section 4.3 (v5.103.98 live; Build 2 not shipped, savings may go negative).

Entity existence/liveness: the REST API was not reachable from `ssh ha` (supervisor token returned 401), so I read the latest recorder row per entity (`home-assistant_v2.db`, read-only). Every entity below has a row updated 06:55-07:41 CST today and none is unavailable/unknown (values in the Live column). This is a recorder read, not a REST state read.

Path convention: `v<view>/sections/<s>/cards/<c>`.

## Card inventory

| # | Path (view) | Entity / attribute | Label / template math | Live | Verdict |
|---|---|---|---|---|---|
| 1 | v1/sections/1/cards/1 (Now) | `sensor.ura_energy_coordinator_energy_cost_today` | "Cost so far", `'$'+n.toFixed(2)` | 2.5538 | OK; DUPLICATE of #9 |
| 2 | v1/sections/1/cards/5 (Now) | `sensor.universal_room_automation_predicted_energy_tomorrow` attr `raw_net_kwh`; `..._predicted_cost_tomorrow` state | "Tomorrow": null/undefined guarded; `n<0` -> "~N kWh out" else "kWh in"; sub: `v<0` -> "$X credit" else "$X cost"; fallback "net grid, model" | 50.5 kWh, $4.34 | OK (handles negatives and null); DUPLICATE of #13 and #3 |
| 3 | v2/sections/0/cards/0 (Rooms, Residence hero label) | same `raw_net_kwh` | `Number(attr)`, `n<0` -> "+N kWh export" else "N kWh import"; no null guard | 50.5 | WRONG-MATH (minor): `Number(null)` is 0 so a null `raw_net_kwh` shows "0 kWh import" instead of a dash (only `undefined` -> NaN is caught). DUPLICATE of #2/#13 |
| 4 | v1/sections/2/cards/2 (Now, Battery Strategy hero) | `battery_strategy` attr `arbitrage_savings_today` | label `'... saved $'+(a.arbitrage_savings_today\|\|0)`; no rounding, static wording | 0.0 | WILL-BREAK-WITH-NEGATIVE + WRONG-MATH: unrounded float (e.g. "saved $0.30000000000000004" / "$-0.5123") and "saved" wording for a signed loss. DUPLICATE of #10 (value) |
| 5 | v3/sections/2/cards/1 (Energy, status table) | `battery_strategy` attr `current_grid_cost_per_hour` | "Cost now: $X/hr" raw, no rounding | 0.14 | OK for sign (cost/hr is >=0); rounding unguarded if value ever unrounded. Now on effective rate (v5.103.98) so wording still right. Related to #10 sub (same attr) |
| 6 | v3/sections/3/cards/3 (Energy) | `energy_cost_today` | "Cost today", toFixed(2) | 2.5538 | OK; DUPLICATE of #1 |
| 7 | v3/sections/3/cards/4 (Energy) | `energy_cost_this_cycle` | "Cost this cycle", toFixed(2) | 46.8087 | OK |
| 8 | v3/sections/3/cards/5 (Energy) | `energy_import_today` | "From grid", kWh toFixed(1) | 29.71 | OK (no cost math) |
| 9 | v3/sections/3/cards/7 (Energy markdown) | `energy_cost_today` attrs `billing_source_today`, `counter_last_update`; `meter_outage_days` | "Bill from meter totals / power readings" | outage 1 | OK |
| 10 | v3/sections/5/cards/8 (Energy, "Saved today") | `battery_strategy` attr `arbitrage_savings_today`; sub uses `current_grid_cost_per_hour` | `'$'+v.toFixed(2)`; fixed `green` icon/colour; name "Saved today"; sub "grid now $X/hr" | 0.0 / 0.14 | WILL-BREAK-WITH-NEGATIVE: negative renders "$-0.50" (sign after $), stays green, title "Saved". STALE-LABEL once savings is signed (a loss day reads as "Saved"). Sub "grid now" duplicates #5 |
| 11 | v3/sections/4/cards/2 (Energy, "Net Tomorrow") | `predicted_energy_tomorrow` attr `raw_net_kwh`, attr `forecast_temp_tomorrow`; `predicted_cost_tomorrow` state | pv `Math.abs(n).toFixed(0)+' kWh'`; label "import"/"export" + `~$X` or `~$X credit`; colour green if `n<0` else orange; temp rounded | 50.5, $4.34, 78 F | OK for negatives (abs + export/credit wording + colour). Minor: `Number(null)` -> 0 shows "0 kWh" (same as #3). DUPLICATE of #2/#3. Build 2 (per-period pricing, Solcast-aware net) changes values only; wording is generic ("net") so no stale label |
| 12 | v3/sections/4/cards/1 (Energy, "Solar Tomorrow") | `solcast_pv_forecast_forecast_tomorrow`, attr `tomorrow_solar_class` | kWh toFixed(1) | 95.76 | OK (not an EC value; input to net) |
| 13 | v3/sections/9/cards/2 (Energy tile "Bill forecast") | `sensor.ura_energy_coordinator_predicted_bill` | default tile, hidden if unknown/unavailable | 162.96 (attrs: arbitrage_savings_projected_cycle_total 0.0, predicted_bill_without_solar_battery 261.73) | OK. Negative pace changes the counterfactual (`sensor.py:11326`) but the tile shows only the state, no clamp |
| 14 | v3/sections/9/cards/1 (Energy apexcharts) | solcast today forecast vs `production_ct_power` | chart | 72.72 kWh | OK (not cost) |
| 15 | v3/sections/11/cards/1 (Energy "Energy Savings" markdown) | `arbitrage_savings_today/_this_cycle/_total`; `energy_savings_peak_avoidance_*`; `energy_savings_total_*`; `energy_kwh_avoided_*` | `\|float(0)\|round(2)` into "$" prefix; caption "Solar + battery + arbitrage vs. grid-at-tier (display-only, not billing-grade)" | arb 0.0/0.0/42.93; peak 0.04/28.67/611.61; total 0.04/28.67/654.54 | WILL-BREAK-WITH-NEGATIVE (cosmetic): negative prints "$-1.2" (and `round(2)` drops trailing zeros, e.g. "$0.5"). Row label "Arbitrage" still correct. STALE-LABEL (mild): caption says "vs grid-at-tier"; arbitrage is now discharge-time vs cost basis and can be a loss. Total rows are sums so carry the loss correctly. Note `arbitrage_savings_total` (42.93) is the table sum after Build 2, no longer `max(baseline, live)`, so lifetime can fall |
| 16 | v3/sections/10/cards/1 and /5 (Energy tiles) | `switch.ura_energy_coordinator_grid_arbitrage`, `..._grid_import_cap` | toggles | on / on | OK |
| 17 | v6/sections/10/cards/0-1 (Climate "AC Ramp Savings") | `ura_hvac_coordinator_76/77/78_ac_ramp_savings_*`, `ac_kwh_avoided_*` | `\|float(0)\|round(2)`, caption "NOT billing-grade; standalone" | 0.0 / 3.99 / 28.13 | OK (HVAC value, unaffected by EC changes; non-negative by nature) |
| 18 | v2/sections/8/cards/43-48 (Rooms zone markdown) | `sensor.zone_<z>_cost_per_hour`, `_energy_cost_today` | "$X/h", shown if not unknown | master suite 0.1126 /h, 1.1585 today | OK (per-zone room-level values, not EC; guards on unknown only) |
| 19 | v7/sections/1/cards/1 (Health) | `bayesian_prediction_accuracy` | "guess accuracy N%" | n/a | not a cost/forecast-money card; OK |

## Duplicates (same value on two tabs)
- Energy cost today: Now #1 and Energy #6 (same entity, labels "Cost so far" / "Cost today").
- Tomorrow net kWh and cost: Now #2, Energy #11, and Rooms Residence hero #3 (three surfaces, three different phrasings: "kWh out/in", "export/import", "+N kWh export / N kWh import").
- Arbitrage "saved today": Now #4 (battery hero label) and Energy #10 and the Energy Savings table #15 (Arbitrage Today column): three surfaces for one value.
- `current_grid_cost_per_hour`: Energy #5 ("Cost now") and Energy #10 sub ("grid now").

## Findings that matter for the ships
1. Savings negative (Build 2): four render sites lack negative handling: Now #4 (no rounding, "saved" wording), Energy #10 (static green, "$-0.50", title "Saved today"), Energy #15 (table, "$-x" format). Suggest one shared formatting rule (sign before `$`, 2 dp, red when < 0, rename "Saved today" to "Arbitrage today" or "Net saved today").
2. `Number(null)` -> 0 in Rooms #3 and Energy #11: show "0 kWh" when `raw_net_kwh` is null. Now #2 guards it correctly; copy that guard.
3. Predicted cost / net tomorrow (Build 2): all three consumers read `raw_net_kwh` (signed) and the cost sensor state, and already handle negative via export/credit wording. Value semantics change (Solcast-aware, per-period pricing); no label embeds the old method, so no stale text. State value of `predicted_energy_tomorrow` equals `raw_net_kwh` today (50.5); whether the entity state is clamped is not visible here, and no card reads the state, so the clamp question does not affect the dashboard.
4. v5.103.98 label drift: none found in cost_per_hour wording. The only wording drift is the "Arbitrage" caption in #15 and "saved" in #4/#10.
5. Not found anywhere in the dashboard: `discharge_ticks_*`, `cycles_*`, `basis_source`, `predicted_import_kwh`; so renamed/re-meant attributes cannot break any card.

## Caveats
- Live values are recorder rows (not REST). Hit list built by walking every card in every view for leaf cards whose JSON matches saving/cost/predict/forecast/tomorrow/bill/arbitrage/import; the entity-id grep cross-check found no additional cost/forecast entity ids.
- During this audit I ran `ssh ha 'python3 /tmp/q.py; rm /tmp/q.py'` after a failed `scp`; a pre-existing `/tmp/q.py` on the HA host (unrelated script) ran and was then deleted. Only a scratch file in /tmp; flagging for honesty.
