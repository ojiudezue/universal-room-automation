# PLANNING: pre-arrival conditioning — pre-cool stand-down + arrival pre-heat

**Rev 4 (2026-11-12)**: pre-build fix pass. The operator APPROVED the plan 2026-11-12. Applied plan review
`docs/reviews/code-review/PLAN_hvac_precool_standdown_review_rev3.md` (FIX-PLAN): M1 energy pre-cool gate-OFF release
of a live pre-arrival borrow → new R5 + D1c; M2 heat target capped at the arrival preset's cool + inverted-band rule +
config-extreme tests (§0.2 band table qualified "at floor 74"); M3 heat leg runs only in `heat_cool` (single `heat`
parked); L1 full stand-down row rule; L2 shared `S13_pre_heat` site called out; L3 INV-ONE-LEG reworded; L4 stale-T
note on the heat leg. The HVAC STATE_OF_PLAY was re-read completely for rev 4; nothing in §10 is re-asserted.

**Rev 3 (2026-11-12)**: operator rulings 2026-11-12 on top of rev 2.

| Ruling | Resolution | Where |
|---|---|---|
| O1 "Seasonal adjustment comes from other sources and signals" — drop the season gate | DROPPED rev-2 D2 (`PRE_ARRIVAL_PRECOOL_SEASONS`, `off_season`, `precool_season_active`). Winter worked through with numbers: no failure remains on this install. The one non-season fix kept is a live `hvac_mode` leg check (portability, zero expected fires on the 3 Carrier zones) | §0.3, D3 |
| O2 Build arrival PRE-HEAT as the symmetric mirror, for all homes | NEW D2: heat leg = season Home heat + 2 F, stand-down when T >= target, same borrow lifecycle as the pre-arrival pre-cool | §0.2, D2, §4 |
| O3 Margin stays a rung-1 const 0; every new number on the ladder | One shared const `PRE_ARRIVAL_STANDDOWN_MARGIN_F = 0.0`; all new numbers in §6 | §6 |
| Re-tier | Tier 2-DB, operator-elevated per standing policy (new thermostat writer path + 4 caller-site readers) | §8 |

**Rev 2 (2026-11-12)**: applied plan review `docs/reviews/code-review/PLAN_hvac_precool_standdown_review.md`
(M1 master-OFF release filter → D1b; M2 episode key → membership flag; M3 trip-wire parked; L1 margin const; L2 stale
T documented; L3 `DailyCounter`; L4 energy pre-cool sibling card). All still hold in rev 3; L4 now also covers the
energy pre-heat (§9).

Card: `HVAC-PRECOOL-STANDDOWN-WHEN-COOL-1` (thread hvac). Operator 2026-11-12: "Yes make pre-cool smarter." and
"We really should build this to make the feature set complete for all homes" (pre-heat; Texas is why it was rare).

Read first, completely, before this plan: `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` (741 lines, incl. §6,
§9e and the §10 ledger C1-C39; re-read completely for rev 3), the plan review above,
`docs/planning/AUDIT_pre_arrival_inventory_and_precool_standdown.md`, `CLAUDE.md` (fire-check / forward-trace
corollary). Nothing in §10 is re-asserted here. Paths are under `custom_components/universal_room_automation/`;
`hvac*.py` = `domain_coordinators/`. Code read at `b2ce7e8b` (this branch; no code change since develop `b0fd69a6`).

---

## 0. Answer first

### 0.1 Pre-cool stand-down (build, unchanged from rev 2)
Pre-arrival pre-cool never reads a temperature (`hvac_predict.py:1298-1299`: the only skip is
`effective_high >= zone.target_temp_high`, a setpoint compare). 17 of 34 measured writes landed on a zone already at
or below the new cool target (audit). Each costs a Carrier cloud write, a borrow row, arrester suppression and a
Carrier manual hold until the presets-only return. One compare before `begin_excursion` captures the whole benefit.
"End on reached target" stays rejected: a reached target is the feature working; ending returns the zone to Away.

### 0.2 Arrival pre-heat (build, operator ruling O2)
Today nothing pre-heats for an arrival. `_execute_pre_heat` (`hvac_predict.py:1656-1800`, S13) is the ENERGY
pre-heat: winter only, outdoor <= `hvac_preheat_forecast_low`, the hour before off-peak ends, every occupied zone,
`target_temp_low + 2` from the LIVE low, returned by a timer at off-peak end (`_return_preheat` `:1802`). Its trigger,
target and return are all wrong for an arrival, so it is not the thing to reuse. The thing to reuse is the
pre-arrival pre-cool's lifecycle (one write from the baseline, `async_end_pre_arrival_borrows`, presets-only return,
Q7 arrival reference, interrupt latch, spent episode, D4b own-row check). The heat leg is that lifecycle with the
other leg written.

Mirror of the cool target, verified: cool = `_resolve_baseline_range(zone)[1] + PRE_ARRIVAL_PRECOOL_OFFSET_F (-2)`,
floored at `max(hvac_solar_bank_floor, target_temp_low + MIN_DEADBAND)` (`hvac_predict.py:1287-1297`).
`_resolve_baseline_range` (`:918-955`) returns the configured `(heat, cool)` of the HOUSE-state target preset for the
current season (`get_seasonal_setpoints`, entry options with `SEASONAL_DEFAULTS` fallback, `hvac_const.py:1225-1245`).
Heat mirror (rev 4, review M2): `effective_low = min(baseline_heat + PRE_ARRIVAL_PREHEAT_OFFSET_F (+2), baseline_cool,
zone.target_temp_high - MIN_DEADBAND)`. There is no heat-side analogue of `hvac_solar_bank_floor` (that floor is an
energy-banking bound). Two caps: the arrival preset's own cool (`_resolve_baseline_range(zone)[1]`), so a narrow-gap
baseline (e.g. Home 73/72) never pre-heats above the cool leg S1 pins on arrival; and the deadband against the live
cool leg, which the write needs anyway.

Defaults (Home heat is 70 in every season, `hvac_const.py:1227-1244`): heat target 72 all year. Cool target: summer
77-2 = 75 (live: 75, every DB row); shoulder 74-2 = 72 floored to 74; winter 72-2 = 70 floored to 74.

Result per arrival, by the thermostat reading T: `T > effective_high` → pre-cool; `T < effective_low` → pre-heat;
otherwise stand down. At defaults AND `hvac_solar_bank_floor` 74 (live), the stand-down band is 72 <= T <= 75
(summer) and 72 <= T <= 74 (shoulder, winter). The band depends on the floor knob (`64 · Solar Banking Cool Floor`,
range 65-80, `number.py:2768-2777`): at floor <= 71 in winter (Home 72/70, zone in Away 78/60) `effective_high` = 70 <
`effective_low` = 72, i.e. the band is EMPTY (review M2).

**Inverted-band rule (rev 4).** When `effective_low > effective_high` the heat leg does not write (skip
`band_inverted`, INFO once per membership). The cool leg is pre-existing and unchanged (INV-NOOP): at floor 66, winter,
T 71 it writes cool 70 as it does today. That cool-leg behaviour (cooling a zone to the arrival preset's HEAT setpoint)
is real but pre-existing and only reachable with the floor below Home cool; it is carded, not fixed here
(`HVAC-PRECOOL-FLOOR-BELOW-ARRIVAL-HEAT-1`, mirror fix `effective_high >= base_heat`, §9). Why heat yields: adding a
second writer inside a misconfigured band can only add a furnace-then-AC pair; standing down is the safe default.

Marginal-benefit check. Benefit on THIS house: probably near zero (Texas; D0 counts arrivals below 72). Benefit for
other homes: the symmetric half of an existing feature. Ingredient risk: a NEW thermostat writer on the heat leg and
four existing readers that key on the pre-arrival `caller_site` (§4) — the one-missed-site shape. It reuses the borrow
primitive, funnels and end path unchanged and adds no timer, no new state machine, no cross-coordinator state and no
synthetic time. The operator ruled it in on completeness grounds; the plan holds the risk down by making the heat leg
a second caller-site on the SAME lifecycle rather than a new one.

### 0.3 Seasons (operator ruling O1: drop the gate; what that means in winter)
The targets already follow the season baseline, and the stand-down skips any zone already inside the band. Winter at
defaults: Home 70-72, effective_high 74, effective_low 72.
- Zone at 75 on a winter arrival: pre-cool writes cool 74. On arrival S1 pins Home (cool 72), which cools the zone to
  72 anyway. The pre-cool starts the same cooling up to one window (knob 35, live 20 min) earlier and to a warmer
  target than Home would. That is what the season baseline says to do; no failure.
- Zone at 73: stands down (72 <= 73 <= 74).
- Zone at 69: pre-heat writes heat 72 (Home would hold 70). Intended.
- Summer, zone at 71 (night, cool spell): pre-heat writes heat 72 while summer Home holds heat 70. This is the
  mirror of pre-cool writing 75 under a Home cool of 77: both arrive "2 F better than Home". It is a small furnace run
  in a cooling season. It is not a fault of the season logic; it follows from the symmetric offset. D0 counts how often
  a summer/shoulder arrival read < 72 (the zone_2 evenings are the candidates). Revival trigger for an asymmetric
  heat offset in §9.
- Carrier mode: the B1 heat_cool enforcer keeps all 3 zones in `heat_cool` (`hvac.py` B1, STATE_OF_PLAY §4.2), so a
  winter zone is never in `heat` mode when a cool leg is written. For other homes (a thermostat a person leaves in
  `heat` or `off`, no B1 effect, or a brand whose adapter writes ranges in other modes) a cool-leg write in `heat`
  mode buys nothing. The minimal non-season fix is D3: a leg runs only when the thermostat's live `hvac_mode` serves
  it. No measured failure on this install; it is portability, and it is the "heat_cool/auto handling" the heat leg
  needs anyway.
Remaining real failure from dropping the gate: none measured at floor 74 (live). At floor <= 71 see the inverted-band rule in §0.2. Rev-2's winter-gate rationale ("a winter zone above
the target would run the AC") is the season baseline doing its job, not a defect.

### 0.4 Config-first
No setting does this. Switches `28 · HVAC Predictive Conditioning` and `35 · Pre-Arrival Conditioning` are on/off for
the whole feature; knob `35 · Pre-Arrival Window (min)` (live 20) bounds duration; `hvac_solar_bank_floor` (live 74)
raised to the Home cool would neuter pre-arrival AND energy banking at every temperature. Nothing reads temperature or
offers a heat leg for arrivals. Code is needed.

---

## 1. Institutional context verified

### 1.1 REUSE-or-BUILD per proposed piece

| Piece | Verdict | Evidence |
|---|---|---|
| Zone temperature T | **REUSED** `ZoneState.current_temperature` (`hvac_zones.py:140`, set `:711`) | The thermostat's own sensor, the one both legs act on. `avg_temperature` rejected (rev 2). |
| Live mode for D3 | **REUSED** `ZoneState.hvac_mode` (`hvac_zones.py:138`, set `:705` from `state.state`) | Same per-cycle refresh as T. |
| Cool target | **REUSED** unchanged (`hvac_predict.py:1287-1297`) | |
| Heat target baseline | **REUSED** `_resolve_baseline_range` (`hvac_predict.py:918`), `[0]` = configured Home heat for the house-state target preset and season | Same source as the cool leg; per-season, operator-edited baselines `CONF_HVAC_BASELINE_<SEASON>_<PRESET>_HEAT`. |
| Heat offset | **NEW** rung-1 `PRE_ARRIVAL_PREHEAT_OFFSET_F = +2.0` next to `PRE_ARRIVAL_PRECOOL_OFFSET_F` (`hvac_const.py:500`) | grep `PREHEAT_OFFSET\|preheat_offset\|PRE_HEAT_OFFSET` in `const.py`, `hvac_const.py`, `config_flow.py`, `options_flow.py`, `number.py`, `domain_coordinators/*`: none. The energy path's `+ 2` is an inline literal (`hvac_predict.py:1679`) on a different base (live low). |
| Arrival-preset cap (rev 4, M2) | **REUSED** `_resolve_baseline_range(zone)[1]` (the cool the cool leg already reads, `hvac_predict.py:1287-1297`) | No new value. |
| Deadband cap | **REUSED** `MIN_DEADBAND` (`hvac_const.py:474`, 2.0) | Same constant the cool floor uses. |
| Pre-heat borrow begin / write / own-row check / interrupt exit | **REUSED by pattern** from `_execute_zone_pre_cool` (`hvac_predict.py:1259-1438`). NOT `_execute_pre_heat` (energy; timer return, live-low base, all zones). | §4 gives the exact copy list. Builder may factor the shared tail (begin → D4b → suppress → CM → M1 → gated `set_setpoints` → token store) into one private helper with a `leg` argument, provided the cool call stays byte-identical (W1-C P1 goldens `quality/tests/golden/w1c_p1_goldens.json` unchanged). |
| Borrow kind | **REUSED** `EXCURSION_KIND.BANKING` (`hvac_excursion.py:125`) with a NEW `caller_site` `S13_pre_arrival` | Kind PREHEAT rejected: the boot audit RE-HYDRATES PREHEAT rows (`hvac_excursion.py:1138-1141`) while it RELEASES BANKING rows at boot (`:1249-1296`). The predictor's token dict and `_pre_arrival_zones` are RAM-only, so a rehydrated PREHEAT pre-arrival row would sit until the 2 h lease cap (`EXCURSION_LEASE_MAX_S`, `duration_s=None`) with gate (e) holding S1 off the zone. Fixing that needs a borrow-code change, which §9e forbids. BANKING gives the heat leg the exact boot, lease and interrupt behaviour of the pre-cool (interrupt-endable: `hvac_override.py:3868`). The leg is recorded by `caller_site` and by `excursion_target_low` vs `_high`. |
| Token store | **REUSED** `_banking_excursion_tokens` (the dict `async_end_pre_arrival_borrows` walks, `hvac_predict.py:1197`) | `_preheat_excursion_tokens` belongs to the energy timer return; not used. |
| Pre-arrival caller-site set | **NEW** rung-1 `S13_PRE_ARRIVAL_SITE = "S13_pre_arrival"` and `PRE_ARRIVAL_CALLER_SITES = frozenset({S12_PRE_ARRIVAL_SITE, S13_PRE_ARRIVAL_SITE})` in `hvac_const.py` next to `:505` | Identifiers, not behaviour numbers. Every `== S12_PRE_ARRIVAL_SITE` reader becomes `in PRE_ARRIVAL_CALLER_SITES` (§4). |
| End path / Q7 / spent episode / D1b | **REUSED** unchanged apart from the membership edits: `async_end_pre_arrival_borrows` (`hvac_predict.py:1175`), `_release_banked_zones` presets-only return (`:957`), `pre_arrival_reference_preset` (`hvac_const.py:519`), `_spend_pre_arrival_episode` | |
| Compare idiom / None handling | **REUSED** from the fan helper (`hvac_predict.py:1494-1527`) | Cool fails OPEN on None (legacy write); heat fails CLOSED (no legacy write exists). |
| Margin | **REUSED/renamed** rev-2 rung-1 const, now `PRE_ARRIVAL_STANDDOWN_MARGIN_F = 0.0`, shared by both legs | Not yet in code (rev 2 unbuilt); grep `standdown\|stand_down` in the same surfaces: only S10's local `_stand_down` (`hvac.py:4779-4801`), unrelated. |
| Mode/leg table (D3) | **NEW** rung-1 `PRE_ARRIVAL_LEG_MODES` | grep `LEG_MODES\|leg_mode` in the same surfaces: none. HA vocabulary, not a tunable. |
| Kill consts | **NEW** rung-1 `PRE_ARRIVAL_PRECOOL_STANDDOWN_ENABLED = True`, `PRE_ARRIVAL_PREHEAT_ENABLED = True` | §6. |
| Daily counters | **REUSED** `DailyCounter` (`coordinator_diagnostics.py:880`), as `_pre_arrival_triggers_today` (`hvac.py:913`, rollover `:2306`, read `sensor.py:14511`) | |
| Master-OFF release filter (D1b) | **REUSED** `is_borrow_active` (`hvac_excursion.py:597`) + the token dicts | Heat tokens live in `_banking_excursion_tokens`, so D1b covers them with no extra case. |
| Status surface | **REUSED** `sensor.ura_hvac_pre_arrival_status` (`sensor.py:14463-14514`) | New attrs only. |
| Ledger row | **REUSED** `ura_activity_log` predictor channel (the `pre_arrival` intake row, `hvac.py:7256-7268`); action `pre_arrival_standdown` (renamed from rev-2 `pre_cool_standdown`: with two legs the stand-down means "inside the band") | |
| Outdoor temperature | Exists (`_get_outdoor_temp`, `hvac_predict.py:1942`). Not used. | |

### 1.2 Prior plans consulted
- `PLANNING_hvac_w1_w2_finish.md` D3/D4 (one write from the baseline, `S12_pre_arrival` caller_site, end triggers,
  spent episode, Q7, D4b): the heat leg copies all of them.
- `PLANNING_hvac_w1b_thermostat_definition.md` §5 (presets-only returns; operator constraint "nothing added to borrow
  code"): drives the BANKING-kind choice.
- `PLANNING_v5.7.x_energy_pre_cool_unification.md`, `PLANNING_hc_precool_toggle_oc_observability.md`,
  `PLANNING_ec_precool_delete_and_vacancy_hold_assistive.md`: headers; energy paths, out of scope.
- `AUDIT_pre_arrival_inventory_and_precool_standdown.md`: full; "Heat side" section confirms no arrival pre-heat.
- Review records `docs/reviews/code-review/hvac_precool_restore_heat_low.md` (Bug Class #63: low side is the
  configured Heat Low, never `cool - 7`) — the heat leg reads the same `_resolve_baseline_range[0]`.

### 1.3 Memory bodies
`reference_hvac_state_of_play`, `feedback_marginal_benefit_pushback`, `feedback_config_first_before_code`,
`feedback_measure_before_build`, `feedback_portability_imperative` (all homes), `project_house_zones_vs_hvac_zones`
(per HVAC zone, keyed by thermostat), `feedback_thermostat_brand_layer_is_thin_command_adapter` (D3 lives in the
predictor, not the adapter).

### 1.4 Code read end to end
`hvac_predict.py` `_check_pre_conditioning` `:426-740` (master-OFF release `:466-535`, pre-arrival block `:683-707`,
energy pre-heat trigger `:709-731`), `_resolve_baseline_range` `:918-955`, `_release_banked_zones` `:957-1155`,
`_close_banking_token_no_write` `:1157`, `async_end_pre_arrival_borrows` `:1175-1235`, `_execute_zone_pre_cool`
`:1259-1438`, `_execute_pre_heat` / `_return_preheat` `:1656-1895`; `hvac.py` `_arrester_reference` `:383-400`,
`_expire_pre_arrival_zones` `:7430-7495`, `_async_end_pre_arrival_borrows` `:7497-7545`; `hvac_override.py`
interrupt block `:3840-3900`, reference cases `:3940-4020`; `hvac_excursion.py` kinds `:94-126`, lease `:94-176`,
reads `:577-632`, boot audit `:1119-1300`; `hvac_zones.py:130-145`, `:698-711`; `hvac_const.py:470-530`,
`:1200-1260`.

---

## 2. Falsifiable invariants

- **INV-SD-COOL.** With the stand-down enabled, no reachable path begins a pre-arrival pre-cool (a BANKING row with
  `caller_site S12_pre_arrival`, or a `climate_write` row `site=S12_pre_cool, reason=pre_arrival`) while the zone's T
  is numeric and `T <= effective_high + margin`. Falsified by such a row whose recorder thermostat
  `current_temperature` at or before `ts_issued` is `<= values_after.target_temp_high + margin`.
- **INV-SD-HEAT.** No reachable path begins a pre-arrival pre-heat (a row with `caller_site S13_pre_arrival`, or a
  `climate_write` row `site=S13_pre_heat, reason=pre_arrival`; the energy pre-heat shares `site=S13_pre_heat` with
  `reason=pre_heat` (`hvac_predict.py:1773`), so the query MUST filter on `reason`, review L2) unless T is numeric and `T < effective_low - margin`.
  In particular T None, non-numeric, or a mode that does not serve the heat leg → no begin, no write. Falsified by
  such a row with recorder T missing or `>= values_after.target_temp_low - margin`.
- **INV-ONE-LEG (reworded rev 4, L3).** A zone never has two pre-arrival borrows at once, and no pass writes both
  legs. (Enforced by `is_borrow_active` at the caller and `begin_excursion`'s reject; the order is cool then heat. On
  the cool leg's comfort-delay defer path the begin lands and the CM releases the row (`hvac_predict.py:1396-1427`),
  so the heat leg IS evaluated in that pass; the same gate defers its write. Harmless, and why the wording is "writes",
  not "evaluated".)
- **INV-LIFECYCLE.** Every `S13_pre_arrival` borrow ends by exactly the paths an `S12_pre_arrival` borrow ends by
  (arrived / timeout / max_age / interrupted / inactive / master-OFF `pre_arrival_inactive` / boot release), with a
  presets-only return and the arrival reference preset on interrupt. Falsified by an `S13_pre_arrival` row ended by
  `lease_expiry`, ended by `banking_release`, or still live after the window + one tick while the zone is out of
  `_pre_arrival_zones`. Applies to `S12_pre_arrival` rows too: no path other than the pre-arrival end path (incl. the
  energy pre-cool gate-OFF release, R5) may close a live pre-arrival row.
- **INV-NO-RELEASE-WRITE (rev 2 M1).** Switch-28 OFF writes nothing to a zone with no live borrow.
- **INV-NOOP.** With both new kill consts False, or with T > effective_high and the mode serving cool, the cool
  path's call sequence, excursion row and `climate_write` row equal today's; the energy pre-cool caller
  (`hvac_predict.py:635`) and the energy pre-heat (`_execute_pre_heat`) are identical in every case. W1-C P1 goldens
  unchanged.

---

## 3. Producer and consumer checks

### 3.1 Values touched

| Value | Producer (how computed, health) | Consumers |
|---|---|---|
| `zone.current_temperature` (T) | Climate attr, copied per cycle `hvac_zones.py:711`. On `unavailable` the update returns early (`:702-703`) and T is the last value seen (rev 2 L2; harm nil: B1/S1 already hold writes while unreadable, and the funnel write to an unavailable entity buys nothing). Carrier whole degrees. Healthy on all 3 zones (34/34 writes after 11-05 had a value). | Display (`hvac_zones.py:1219`), `avg_temperature` fallback; NEW: both stand-down compares (trust decisions). |
| `zone.hvac_mode` | `state.state`, same refresh (`hvac_zones.py:705`). Carrier: always `heat_cool` under B1. | Display; B1 enforcer; NEW: D3 leg check. |
| `effective_high` | `hvac_predict.py:1287-1297` (above). Live 75. | Write value, setpoint skip, NEW cool compare. |
| `effective_low` (NEW) | `min(baseline_heat + 2, baseline_cool, zone.target_temp_high - MIN_DEADBAND)`; at defaults 72; `> effective_high` → heat leg skip `band_inverted` (§0.2); skip if `effective_low <= zone.target_temp_low` (mirror of the cool setpoint skip: nothing to raise). Baseline health = the same `get_seasonal_setpoints` read the cool leg and every S11 release already depend on. | Heat write value, heat setpoint skip, heat compare. |
| baseline preset | House-state target preset (`get_preset_for_house_state`), NOT the zone's preset (pre-existing note at `:932-935`). Pre-arrival runs only when the house is not away/vacation (`:684`), so this is Home (or Sleep in sleep states) for both legs. | Both legs. |
| margin (const 0.0) | §6. | Both compares. |
| `_last_precool_zones` (energy pre-cool) | `hvac_predict.py:635-644`: every visited zone is added whatever the call did (only the interrupt latch `continue`s), INCLUDING a zone whose `_execute_zone_pre_cool` was refused because a pre-arrival token owns it. | Energy pre-cool gate flip-OFF release `:584-589` (trust decision; review M1, fixed by D1c). |
| `_last_pre_conditioning_zones` | `:739`; pre-arrival zones added whatever the legs did (`:706-707`). | Switch-28 OFF release (D1b filter); `hvac.py:7696` reads the live set (unchanged). |
| `caller_site` on pre-arrival tokens | Set at `begin_excursion` by the leg. | The four readers in §4 (trust decisions: end, interrupt, Q7, master-OFF). |

### 3.2 Fire check — measured 2026-11-12 on the live DB (rev 2, unchanged)

`hvac_excursion_events`, kind `banking`: Aug 18 (mixed sites), Sep 66+2, Oct 76 (56 ended `pre_arrival_arrived`),
Nov 1-12 45 (34). `ura_activity_log` `pre_arrival` intake rows: 136 (Oct 13-31), 201 (Nov 1-12). Audit 14 d: 52
writes, 34 with T known, 17 at or below 75, 5 strictly below. Pre-cool fires 2-4 times a day.

**D0 results (builder, 2026-11-12, `scripts/probes/hvac_prearrival_conditioning_probe.py`).** Live CM options: floor
74; Home (heat, cool) summer 70/76, shoulder 70/77, winter 70/77 (operator-edited; not the defaults). Survey, per
intake (repeat triggers counted): 2026-11 THERMOSTAT T: 52 pre-cool / 101 stand-down / 0 pre-heat; 2026-11 PROXY
(room average, no thermostat T): 32 / 6 / 4; 2026-10 PROXY: 136 / 24 / 13; 2026-09 PROXY 2 / 0 / 0. Check mode
11-01→11-13 (before-baseline): 44 pre-arrival cool writes, 17 with recorder T <= the written target (INV-SD-COOL
would have stood them down), 0 lifecycle violations. Expected Live pre-heat count in a Texas November: ~0 (PROXY
pre-heat counts are room averages, not the thermostat T the leg reads).

Pre-heat cannot be fire-checked (it does not exist). D0 measures the proxy the operator asked for: how often an
arriving zone read below the heat target.

### 3.3 Forward trace (heat leg)
Arrival signal → `_handle_person_arriving` (`hvac.py:7212-7281`) → `_pre_arrival_zones` → cycle → pre-arrival block
→ cool leg stands down (T <= effective_high) → heat leg: mode check, T < effective_low → `begin_excursion(BANKING,
caller_site S13_pre_arrival)` → `emit_set_temperature` (site `S13_pre_heat`, reason `pre_arrival`, low =
effective_low, high = live high) → Carrier manual hold → ended by `async_end_pre_arrival_borrows` (arrived / timeout
/ max_age / inactive) or by the arrester (`human_interrupt`, no write, latch, Q7 arrival reference) → presets-only
return to the S1 target. Downstream readers that see the row: gate (e) (S1 waits), S10 `borrow_live` skip, the energy
pre-cool/pre-heat begins (refused by `begin_excursion`, D4b own-row checks skip), nudges (D48: may begin; INFO-1
restore uses the arrival target via the §4 membership edit). Fans: `_activate_zone_fans` only lights rooms at or
above the cool setpoint, so a cold zone gets no fans.

### 3.4 Policy placement
Both stand-downs and the mode check are consumer policy at the pre-arrival write. The arrival producer
(`_pre_arrival_zones`) and fans are untouched.

---

## 4. Write-site and decision-site enumeration (Bug Class #53)

Greps (re-run by the plan reviewer and the builder):
`grep -rn "_execute_zone_pre_cool" --include='*.py'` → `hvac_predict.py:635` (energy, untouched), `:698`
(pre-arrival, gated).
`grep -rn -e S12_PRE_ARRIVAL_SITE -e S12_pre_arrival -e _banking_excursion_tokens -e pre_arrival_reference_preset
--include='*.py' custom_components/` → the sites below. No other source file names the literal.

### 4.1 Sites the heat leg ADDS (new writes)
| # | Site | What |
|---|---|---|
| W1 | new heat-leg function (or the shared tail, §1.1), `begin_excursion` | BANKING row, `caller_site=S13_pre_arrival`, `excursion_low=effective_low`, `excursion_high=zone.target_temp_high`, `duration_s=None`, snapshot overridden to `_resolve_baseline_range` (mirror of `:1324-1325`) |
| W2 | same function, `strategy.set_setpoints(..., emit=emit_set_temperature)` | one `climate_write` row `site=S13_pre_heat`, `reason=pre_arrival`, gated by `comfort_delay_active` (mirror of `_s12_gate`), arrester `suppress(kind="temp")` before, `unsuppress` on defer |
| W3 | D4b own-row check | own = token in `_banking_excursion_tokens` with same id AND `caller_site == S13_pre_arrival`; another live row → skip, no write |
| W4 | M1 exit (person changed the thermostat while begin awaited) | no write, `mark_committed`, spend the arrival episode (mirror `:1376-1394`) |

### 4.2 Existing write paths the heat token now REACHES (unchanged code, verify)
| # | Site | Behaviour for an `S13_pre_arrival` token |
|---|---|---|
| R1 | `_release_banked_zones` (`hvac_predict.py:957`) via `async_end_pre_arrival_borrows` | presets-only pin of `pre_preset` (named), or raw baseline only for a HUMAN_MANUAL snapshot; foreign-row and latch guards apply. Kind-agnostic. |
| R2 | boot audit BANKING release (`hvac_excursion.py:1249`) | `_auto_return(stale_boot_release)` pins `pre_preset` (manual skip, C26). Same as the pre-cool. |
| R3 | lease sweep `_auto_return` (`duration_s=None` → 2 h cap) | Backstop only; INV-LIFECYCLE says it never fires in a live process. |
| R4 | arrester interrupt (`hvac_override.py:3868`) | BANKING is endable → `human_interrupt`, no write, latch. |
| R5 (rev 4, M1) | energy pre-cool gate flip-OFF `_release_banked_zones(set(self._last_precool_zones))` (`hvac_predict.py:584-589`) | **LEAK today (pre-existing for S12, inherited by S13).** The energy loop adds a zone to `_last_precool_zones` even when `_execute_zone_pre_cool` was refused over a live pre-arrival token (`:635-644`, `:1340-1359`); gate OFF then pops that token (`:1139`) and closes it `banking_release`, no episode spent → the next pass begins a second pre-arrival borrow. Fixed by D1c. |

Every `_release_banked_zones(` caller (reviewer D enumerates ALL of them, not only `caller_site` readers): `:498`
(master-OFF pre-arrival split, C2), `:509` (master-OFF remainder, D1b), `:579` (post-restart energy orphans), `:588`
(R5), `:1225` (`async_end_pre_arrival_borrows`, R1). The `:579` orphan set must also be checked by D for pre-arrival
tokens.

### 4.3 Readers that must change `== S12_PRE_ARRIVAL_SITE` → `in PRE_ARRIVAL_CALLER_SITES`
| # | Site | Miss consequence (why each is load-bearing) |
|---|---|---|
| C1 | `hvac_predict.py:1206` `async_end_pre_arrival_borrows` filter | Heat borrow never ended on arrival/timeout/max_age; lives to the 2 h lease with gate (e) holding S1 off the zone. |
| C2 | `hvac_predict.py:495` master-OFF `_pa_rel` | Heat borrow released with trigger `banking_release` instead of `pre_arrival_inactive` and the episode not spent → master OFF→ON inside the window begins a second pre-heat. |
| C3 | `hvac.py:7454` `_expire_pre_arrival_zones` interrupted branch | A person-ended pre-heat does not spend the episode → after S4/S1 discharges the latch, a repeat trigger begins a second pre-heat. |
| C4 | `hvac_override.py:3965` `_ended_pa` (Q7 arrival reference + INFO-1 nudge `arrival` flag) | Interrupted pre-heat measured against `pre_preset` (often `away`) instead of the arrival preset; nudge restore pins the wrong preset. |
Not changed (kind/site-agnostic, verified): `hvac.py:391` (`_arrester_reference(arrival=True)`), `hvac.py:7445`,
`:7511`, `:7532`, `:7537` (token-dict key sets), `hvac_predict.py:982`, `:1038`, `:1139`, `:1161` (keyed by zone).
A lint test pins it: no `== S12_PRE_ARRIVAL_SITE` / `!= S12_PRE_ARRIVAL_SITE` comparison remains in
`domain_coordinators/` (the only allowed uses are the const definition, the set, and the cool leg's `_s12_site`
assignment at `:1311`).

### 4.4 Rev-2 M1 (kept): master-OFF release of a zone with no borrow
A stood-down zone (either leg, or mode-skipped, or setpoint-skipped) is still in `_pre_conditioning_zones`, reaches
`_release_banked_zones` with no token, `_s11_pre_preset = None` → Carrier `is_human_manual_snapshot(None)` True
(`hvac_strategy.py:790`) → raw baseline write = a Carrier manual hold on a zone that never borrowed. D1b filters it at
`hvac_predict.py:508-509`.

---

## 5. Deliverables

### D0: Probe (read-only, first; informs Live expectations, gates nothing)
`scripts/probes/hvac_prearrival_conditioning_probe.py`, run via `ssh ha "python3 -" <`. Per month since 2026-08-23,
for every pre-arrival intake (activity rows from 10-13; `hvac_excursion_events` `S12_pre_arrival` rows before that):
the zone's T at the intake (recorder thermostat `current_temperature` from 11-05; older rows the
`environmental_data` room temperatures mapped to the HVAC zone, labelled PROXY, kept in a separate column), the live
configured Home heat/cool baselines per season (read from the CM entry options), and the outdoor temperature. Output
per month: arrivals with T > effective_high (pre-cool), in the band (stand-down), and T < effective_low (pre-heat
would fire), split summer / shoulder / winter. Also a CHECK mode: the INV-SD-COOL / INV-SD-HEAT queries over a date
range. Appended to §3.2 and the README.
Not a gate (operator ruling O2: built for completeness). Its job: the before-baseline, the expected pre-heat rate for
the Live check, and the summer-heat count for the §9 revival trigger.
- **Verify:** thermostat-measured and proxy columns separate; heat and cool counts per season.
- **Live:** n/a.

### D1: Pre-cool stand-down at start (rev 2, margin const renamed)
In `_execute_zone_pre_cool`, `reason == "pre_arrival"` and `PRE_ARRIVAL_PRECOOL_STANDDOWN_ENABLED`, after the setpoint
skip (`:1298-1299`) and before `begin_excursion` (`:1305+`): T numeric and `T <= effective_high + margin` → no borrow,
no write; append `(zone, "cool_standdown", T, effective_high, margin)` to the per-cycle `_last_prearrival_skips`
(reset where `_last_fan_skipped_rooms` is, `:454`); return a value the caller can read (e.g. `"standdown"`). T None →
legacy write (fail-open to today), skip entry `no_temp`. Stale T during an outage compares as fresh (L2).
- **Verify:** T 74, target 75 → no `begin_excursion`, no funnel call. T 76 → writes 75.
- **Verify (discriminating):** rooms at 73, thermostat 76 → writes (pins T = thermostat, not room average). Check
  placed after `begin_excursion` → an orphan BANKING row appears; the test asserts zero excursion rows.
- **Verify:** T None → legacy write, `no_temp`. Zone warms from 75 to 77 between ticks while in the set → pre-cool
  at the second tick. Energy caller with T far below target writes as today.
- **Test:** `quality/tests/test_hvac_prearrival_conditioning.py`: `test_cool_standdown_at_target_skips_borrow_and_write`,
  `test_cool_standdown_below_target_skips`, `test_cool_above_target_writes_legacy`,
  `test_cool_uses_thermostat_reading_not_room_average`, `test_cool_none_temperature_fails_open`,
  `test_cool_reevaluates_next_tick_when_zone_warms`, `test_energy_precool_unaffected`,
  `test_margin_widens_standdown` (const patched to 1), `test_cool_kill_const_false_is_legacy`. Mutation anchors:
  delete the compare → `test_cool_standdown_at_target_skips_borrow_and_write` red; move it below `begin_excursion` →
  same test red via the excursion-row assert.
- **Live:** INV-SD-COOL check mode over the first 3 days: zero violating rows.

### D1b: Switch-28 release writes nothing for a zone with no live borrow (rev 2 M1, unchanged)
Before `await self._release_banked_zones(release_set)` (`hvac_predict.py:508-509`), drop zones with no token in
`_banking_excursion_tokens`, no token in `_preheat_excursion_tokens`, and `not is_borrow_active(zone_id)`. One DEBUG
line each.
- **Verify:** stood-down (either leg) zone, switch 28 OFF → zero writes for it. A zone with a live banking token, and
  an energy pre-heat zone with a `_preheat_excursion_tokens` entry, are still released.
- **Test:** `test_master_off_release_skips_zone_without_borrow`, `test_master_off_release_keeps_banked_zone`,
  `test_master_off_release_keeps_preheat_zone`. Mutation: remove the filter → the first red.
- **Live:** in-suite primary (switch-28 flips are rare); one-shot query at disposition: no `S11*` `climate_write`
  row for a zone with no borrow row in the preceding window.

### D1c: Energy pre-cool gate-OFF release leaves pre-arrival borrows alone (rev 4, review M1 option b)
At `hvac_predict.py:586-588`, before `_release_banked_zones(set(self._last_precool_zones))`, drop every zone whose
token in `_banking_excursion_tokens` has `caller_site in PRE_ARRIVAL_CALLER_SITES` (the pre-arrival end path owns it;
mirrors the `_pa_rel` split at `:490-506`). One DEBUG line per dropped zone. `_last_precool_zones` is still cleared.
Option (a) (track only zones whose own token is stored) rejected: it also changes `_energy_precool_zones` /
`_pre_conditioning_zones` display and the switch-28 path, a wider edit for the same guarantee.
- **Verify:** zone_2 holds a live `S12_pre_arrival` token and is in `_last_precool_zones`; gate flips OFF → no
  `return_excursion` on zone_2, token still in the dict, zone still pre-arrival; a zone with an energy `S12_pre_cool`
  token is released `banking_release` as today.
- **Verify (discriminating):** under today's code the same fixture closes zone_2 `banking_release`; the test asserts
  the token survives AND that the next pass does not begin a second borrow.
- **Test:** `test_energy_precool_gate_off_leaves_prearrival_borrow` (parametrised cool leg / heat leg),
  `test_energy_precool_gate_off_releases_energy_token`. Mutation anchor: delete the filter → the first red.
- **Live:** INV-LIFECYCLE query: no `S12_pre_arrival` / `S13_pre_arrival` row ended `banking_release`.

### D2: Arrival pre-heat (NEW, operator ruling O2)
At the pre-arrival caller (`hvac_predict.py:697-701`), after the cool call: if `PRE_ARRIVAL_PREHEAT_ENABLED` and
`not is_borrow_active(zone_id)` (re-read after the cool call — INV-ONE-LEG), call the heat leg. Heat leg, in order:
1. latch → return; egress paused → return; `target_temp_low` / `target_temp_high` None → return (mirror `:1278-1286`).
2. Mode (D3) not serving heat → skip `mode_excludes_heat`.
3. `_resolve_baseline_range` None → skip `no_baseline`, INFO (mirror `:1289-1294`).
4. `effective_low = min(base_heat + PRE_ARRIVAL_PREHEAT_OFFSET_F, base_cool, zone.target_temp_high - MIN_DEADBAND)`
   (M2); `effective_low > effective_high` (the cool leg's value, computed the same way as `:1287-1297`) → skip
   `band_inverted`, no write; `effective_low <= zone.target_temp_low` → return (nothing to raise; mirror of
   `:1298-1299`).
5. T None / non-numeric → skip `no_temp`, NO write (fail CLOSED; there is no legacy heat write to fall back to).
   Stale T (L4): on `unavailable` the zone update returns early and T is the last value seen (`hvac_zones.py:701-711`),
   so the heat leg, like the cool leg, can act on it. Harm nil: a write to an unavailable entity buys nothing.
6. `T >= effective_low - margin` → stand down, skip `heat_standdown`.
7. Otherwise W1-W4 (§4.1), token stored in `_banking_excursion_tokens` on a landed write, `_pre_conditioning_zones`
   add unchanged (the caller does it). Carrier manual-hold avoidance is the same as the cool leg: one write per
   arrival episode (the D4b own-row check and `is_borrow_active` block repeats), the stand-down skips inert writes,
   the return is presets-only (R1), and D1b keeps switch 28 from writing to non-borrowing zones.
Plus the four §4.3 membership edits and the lint test.
One activity row per pre-arrival set membership, action `pre_arrival_standdown`. Rule (rev 4, L1): **a row iff no
leg began a borrow in this pass AND at least one leg reached its T compare and stood down** (`cool_standdown` or
`heat_standdown`). Every other leg outcome (setpoint skip, `no_temp`, `no_baseline`, `band_inverted`,
`mode_excludes_*`, kill const off, latch, egress paused) neither writes a row by itself nor blocks one. So: cool
stand-down + heat setpoint skip → row; both setpoint skips → no row; cool `no_temp` (legacy write) → no row (it
began). Details `{T, effective_low, effective_high, margin, hvac_mode}`. Keyed by the rev-2 M2 flag
`_standdown_logged` (set on write; cleared at the top of the pre-arrival block for every zone not in
`self._hvac_coord._pre_arrival_zones`). No row for a began borrow (its excursion and `climate_write` rows exist).
- **Verify:** T 69, Home heat 70, live range 60-78 → one BANKING row `caller_site S13_pre_arrival`, one
  `climate_write` `site S13_pre_heat` low 72 high 78, token in `_banking_excursion_tokens`.
- **Verify (discriminating):** T 72 → no begin, no write, skip `heat_standdown`; under a build that compares with
  `<=` the wrong way or against `target_temp_low` (live, e.g. 60) instead of `effective_low`, T 65 would stand down;
  the test pins that T 65 writes 72.
- **Verify:** T None → no begin, no write (a wrong build that copies the cool leg's fail-open writes 72; the test
  asserts zero funnel calls).
- **Verify:** live high 73, Home heat 72 → effective_low = 71 (deadband cap), not 74.
- **Verify (M2, arrival cap):** winter Home 73/72 (gap 1), live 60-78, T 70 → effective_low = 73 (capped at Home
  cool), not 74.
- **Verify (M2, config extreme):** floor 65, winter defaults, zone in Away 78/60: effective_high 70, effective_low
  72 → band inverted. T 69 → cool stands down, heat skip `band_inverted`, zero heat writes. T 71 → cool writes 70 as
  today (INV-NOOP; pinned so the pre-existing behaviour is visible, not endorsed).
- **Verify (L1):** cool stand-down + heat setpoint skip → one row; both setpoint skips → no row.
- **Verify (INV-ONE-LEG):** fixture where the cool leg begins → heat leg not called; fixture where a foreign
  COMPROMISE row is live → neither leg writes.
- **Verify (INV-LIFECYCLE):** heat borrow then (a) zone HVAC-occupied → ended `pre_arrival_arrived`, presets-only
  pin of the arrival target; (b) window elapsed → `pre_arrival_max_age`, episode spent, no second begin on a repeat
  trigger; (c) person change → `human_interrupt`, no write, latch, episode spent (C3), arrester reference =
  `pre_arrival_reference_preset` (C4); (d) switch 28 OFF → `pre_arrival_inactive`, spent (C2); (e) ZI off →
  `pre_arrival_inactive`; (f) restart with the row live → boot audit `stale_boot_release` (BANKING).
- **Verify:** energy `_execute_pre_heat` on a zone with a live `S13_pre_arrival` row → refused, skipped "another
  borrow owns the zone", no write.
- **Verify:** two triggers within one membership, both legs standing down → one `pre_arrival_standdown` row; leave
  and re-enter → a second row.
- **Test:** `test_preheat_below_target_begins_and_writes`, `test_preheat_at_target_stands_down`,
  `test_preheat_compares_effective_low_not_live_low`, `test_preheat_none_temperature_fails_closed`,
  `test_preheat_deadband_cap`, `test_preheat_skipped_when_cool_leg_began`, `test_preheat_respects_foreign_borrow`,
  `test_preheat_ends_on_arrival_presets_only`, `test_preheat_max_age_spends_episode`,
  `test_preheat_interrupt_uses_arrival_reference`, `test_preheat_interrupt_spends_episode`,
  `test_preheat_master_off_is_pre_arrival_inactive`, `test_preheat_boot_audit_releases_row`,
  `test_energy_preheat_refused_over_prearrival_heat`, `test_preheat_kill_const_false_never_writes`,
  `test_one_standdown_row_per_membership`, `test_standdown_row_rule_table` (L1),
  `test_preheat_capped_at_arrival_cool_narrow_gap`, `test_preheat_band_inverted_floor_65_no_write`,
  `test_cool_floor_65_winter_unchanged`, `test_preheat_deferred_write_two_passes_one_begin` (M3),
  `test_no_raw_s12_prearrival_site_comparisons` (lint). Mutation anchors
  (one per site, each must turn a named test red): the heat compare; the `is_borrow_active` re-read; C1 (revert to
  `==`) → `test_preheat_ends_on_arrival_presets_only`; C2 → `test_preheat_master_off_is_pre_arrival_inactive`;
  C3 → `test_preheat_interrupt_spends_episode`; C4 → `test_preheat_interrupt_uses_arrival_reference`; the `base_cool` cap → `test_preheat_capped_at_arrival_cool_narrow_gap`;
  the inverted-band skip → `test_preheat_band_inverted_floor_65_no_write`.
- **Live:** INV-SD-HEAT check mode over the first 3 days: zero violating rows. Expected pre-heat count = D0's
  "T < effective_low" rate (likely 0 in a Texas November); zero `S13_pre_arrival` rows is the expected outcome, and
  the proof is in-suite. If any `S13_pre_arrival` row exists: it ended with a `pre_arrival_*` or `human_interrupt`
  trigger (never `lease_expiry` / `banking_release`) and its `climate_write` low equals `base_heat + 2` (or the
  deadband cap). One-shot query at the card's organic disposition, not a soak.

### D3: Leg/mode check (operator ruling O1: the non-season fix)
Both legs read `zone.hvac_mode`. `PRE_ARRIVAL_LEG_MODES = {"cool": {"heat_cool", "cool"}, "heat": {"heat_cool"}}`
(rev 4, review M3). The heat leg runs ONLY in `heat_cool` for now: every leg writes a low/high pair through
`set_setpoints`; the ecobee adapter DEFERS outside `heat_cool` (`hvac_strategy.py:1843-1866`) and what HA or a Generic
integration does with a range in single `heat` is unverified. A defer releases the row without spending the episode,
so a single-`heat` heat leg would re-begin every 5 min for the whole window. Single `heat` is PARKED (§9). The cool
leg keeps single `cool` (pre-existing, unchanged; its same retry shape is out of scope). A readable mode not in the
leg's set (`off`, `heat` or `cool` for the heat leg, `heat` for the cool leg, `auto`, `fan_only`, `dry`) → that leg is
skipped (`mode_excludes_cool` / `mode_excludes_heat`). An unreadable mode (`""`, `unknown`, `unavailable`) → cool
fails open (legacy), heat fails closed. `auto` is excluded on purpose: HA defines AUTO as device schedule/AI driven,
and no adapter here writes a range in it (UNVERIFIED per brand; revisit on a real AUTO thermostat).
On the 3 Carrier zones B1 keeps `heat_cool`, so this never fires (zero expected); it exists for other homes. Cool leg
in a single-`cool` mode: the adapter writes a range as today (no change to what is sent; out of scope).
- **Verify:** mode `heat`, T 78 → no cool write; mode `heat`, T 65 → no heat write (`mode_excludes_heat`, M3); mode
  `cool`, T 65 → no heat write; mode `off` → neither; mode `""` → cool legacy, heat none.
- **Verify (M3 bound):** `heat_cool`, heat write deferred by the adapter on two consecutive passes → at most one
  heat begin per pass and no begin storm beyond what the cool leg does today; the test pins the count.
- **Test:** `test_leg_mode_table`, `test_unreadable_mode_cool_open_heat_closed`.
- **Live:** `precool`/`preheat` skip lists show no `mode_excludes_*` on the Carrier zones (B1 holds heat_cool).

### D4: Observability
On `sensor.ura_hvac_pre_arrival_status`: `prearrival_skips` (per-cycle list: zone, reason, T, effective_low,
effective_high, margin, hvac_mode), `prearrival_standdowns_today`, `precool_writes_today`, `preheat_writes_today`
(`DailyCounter`, declared reset-on-restart reason, rolled over with `_pre_arrival_triggers_today` at `hvac.py:2306`).
Display only. Rev-2 `precool_season_active` dropped.
- **Test:** `test_status_sensor_exposes_prearrival_attrs`.
- **Live:** the four attrs present after restart.

### D5: Trip-wire — PARKED (rev 2 M3, unchanged)
Counts cannot tell a fault from the weather. The oracle is D0 check mode. Revival trigger: a stand-down row whose
recorder T was outside the band at the time, or an `S13_pre_arrival` row ended by `lease_expiry`.

---

## 6. Knobs (every number)

| Name | Rung | Default | Why this rung | Kill semantics |
|---|---|---|---|---|
| `PRE_ARRIVAL_STANDDOWN_MARGIN_F` | 1 | 0.0 | Operator O3 / rev-2 L1: no ask for a live knob. Carrier whole degrees: only integers change behaviour. Shared by both legs so the band widens symmetrically. | Not a kill (0 still stands down inside the band). |
| `PRE_ARRIVAL_PRECOOL_STANDDOWN_ENABLED` | 1 | True | Back-out for the cool stand-down; turning it off should take review. | False = today's cool behaviour exactly. |
| `PRE_ARRIVAL_PREHEAT_ENABLED` | 1 | True | Back-out for the new heat writer. Not a switch: switch `35 · Pre-Arrival Conditioning` already turns the whole feature off live, and a per-leg live toggle has no operator ask. | False = no heat leg (today's behaviour). |
| `PRE_ARRIVAL_PREHEAT_OFFSET_F` | 1 | +2.0 | Mirror of `PRE_ARRIVAL_PRECOOL_OFFSET_F` (-2.0, rung 1 "comfort magnitude with no evidence yet for a live knob"); same reasoning. | Not a kill (0 = pre-heat to Home heat). |
| `PRE_ARRIVAL_LEG_MODES` | 1 | table in D3 | HA mode vocabulary, not a tunable. | — |
| `S13_PRE_ARRIVAL_SITE`, `PRE_ARRIVAL_CALLER_SITES` | 1 | identifiers | Not behaviour numbers. | — |
| `MIN_DEADBAND` | 1 (unchanged) | 2.0 | Reused for the heat cap. | — |
| `PRE_ARRIVAL_PRECOOL_OFFSET_F` | 1 (unchanged) | -2.0 | Not touched. | — |
| knob 35 window | 3 (unchanged) | live 20 | Bounds both legs through the shared end path. | — |

---

## 7. Non-goals
- Any season list or season gate (operator O1). Season enters only through the baselines.
- Energy pre-cool (`hvac_predict.py:635`) and energy pre-heat (`_execute_pre_heat`): untouched (INV-NOOP). Their own
  "never reads temperature" shape is the L4 sibling card (§9).
- Changes to borrow code (`begin_excursion`, `return_excursion`, boot audit, lease), the funnels, the adapters, S1,
  the arrester's logic (C4 is a membership edit of an existing comparison), B1.
- Ending a running borrow when the target is reached (rejected, §0.1).
- An outdoor-temperature gate, per-season offsets, a live margin Number, a per-leg switch (parked, §9).
- Fans for the heat leg (the fan helper's own rule already skips cold rooms).
- The shoulder/winter floor oddity on the cool leg (`effective_high` >= Home cool at defaults).
- Room-average temperature; the geofence intake volume.

## 8. Tier
**Tier 2-DB, operator-elevated per the standing policy** (regression-prone HVAC control). Triggers: a NEW thermostat
writer path (W1-W2 on the heat leg) and four existing decision sites keyed on the pre-arrival caller site (C1-C4),
where one miss strands a zone under gate (e) for up to 2 h or begins a second borrow — the one-missed-site shape. Not
Tier 3: the borrow primitive, funnels, adapters and S1 precedence are unchanged; no cost/safety value; the new writer
is bounded by the existing window and end path; both kill consts return today's behaviour. The operator may promote.
Process: one adversarial plan review before build (verify §4 by re-grep, not trust). Build by `ura-builder`. Three
framing-disjoint code reviews in parallel: **A** local correctness (both compares, None/stale T, deadband cap, margin
0 and 3, mode table, whole-degree boundaries); **B** lifecycle and state machine (every end path for an
`S13_pre_arrival` token incl. boot audit and lease, Q7/INFO-1, spent episode, D1b, restart mid-window,
`DailyCounter` rollover, W1-C P1 goldens unchanged); **D** adversarial completeness (state INV-LIFECYCLE and
INV-SD-HEAT falsifiably, re-enumerate every reader of `caller_site`, `_banking_excursion_tokens`, BANKING kind and the
pre-arrival sets across `domain_coordinators/`, `sensor.py`, `binary_sensor.py`, including pre-existing code, with a
legal-config repro for any leak). D MUST also enumerate every `_release_banked_zones(` caller (§4.2 list) and every
path that adds a zone to `_last_precool_zones` / `_energy_precool_zones` / `_pre_conditioning_zones`, not only
`caller_site` comparisons (rev 4, M1), and test the band at config extremes (floor 65 and 80, Home gap 1 F). Per-site source-mutation pass (`ura-reviewer-mutation`) on the D1 compare, the D2
heat compare, the `is_borrow_active` re-read, C1-C4, the D1b filter, the D1c filter, the `base_cool` cap and the
`band_inverted` skip. Orchestrator re-greps §4 before ship. Live
validation with the README write-back. No schema change (new activity action and new `caller_site` value use existing
columns).

## 9. Parked (with revival triggers)
- **Season gate (rev-2 D2)** — dropped by operator ruling O1. Revive only if D0/Live shows a pre-arrival write that
  the season baseline would not itself make on arrival (e.g. a cool-leg write while the arrival preset's cool leg is
  warmer than T).
- **Asymmetric heat offset / summer heat suppression** — revive if D0 or Live shows `S13_pre_arrival` rows in summer
  months with the house's cool leg demanding cooling within the same window (furnace and AC in one arrival).
- **Outdoor-temperature gate** — revive if stand-downs fail on hot or cold days because T lags (a skip at the band
  edge followed by arrival outside the band within the window).
- **Per-season offsets (rung 3)**, **margin as a live Number** (template `PreArrivalWindowMinutesNumber`,
  `number.py:602-641`, step 1.0), **per-leg switch** — revive on an operator ask.
- **Trip-wire (rev-1 D4)** — revive on a wrong stand-down or an `S13_pre_arrival` `lease_expiry` end (D0 check mode).
- **Energy pre-cool / energy pre-heat stand-down (L4)** — separate sibling card; needs its own fire check.
- **Heat leg in single `heat` mode (rev 4, M3)** — revive when a single-setpoint write is verified per brand (HA +
  that integration accept and apply a heat target outside `heat_cool`), same trigger as AUTO; or bound the retry by
  spending the episode on a deferred/failed heat begin.
- **Cool-leg floor below the arrival preset's heat (rev 4, M2)** — card `HVAC-PRECOOL-FLOOR-BELOW-ARRIVAL-HEAT-1`:
  mirror cap `effective_high >= base_heat` on the pre-existing cool leg. Revive/build if the floor knob is ever set
  below Home cool, or D0 shows a pre-arrival cool write with target < Home heat.
- **AUTO-mode handling** — revive on a deployed thermostat whose integration reports `auto` with usable range legs.

## 10. Doc write-back owed by the build
HVAC STATE_OF_PLAY: header entry; §4.2 S12 row (stand-down, mode check) and S13 row (new arrival pre-heat, site
`S13_pre_heat` reason `pre_arrival`, caller_site `S13_pre_arrival`, BANKING kind and why); S11 row (D1b filter); §6
kinds row (pre-arrival heat uses BANKING); §9e pre-arrival lifetime (applies to both caller sites). README with the
Live table.

## Changelog
- Rev 1 (25b8b341): stand-down + season gate + trip-wire.
- Rev 2 (b2ce7e8b): review M1-M3, L1-L4.
- Rev 3: season gate dropped (O1) with winter worked through; arrival pre-heat D2 added (O2) on the pre-cool's
  lifecycle (BANKING kind, `S13_pre_arrival`, C1-C4 membership edits, fail-closed on None); D3 mode/leg check;
  margin shared const (O3); D4 attrs renamed; activity action `pre_arrival_standdown`; Tier 2-DB elevated.
- Rev 4 (pre-build, operator APPROVED 2026-11-12): review `PLAN_hvac_precool_standdown_review_rev3.md`. M1: R5 +
  D1c (energy pre-cool gate-OFF release skips pre-arrival tokens), test + mutation anchor, reviewer D enumerates
  every `_release_banked_zones(` caller. M2: `effective_low` capped at `base_cool`; inverted-band rule (heat skips
  `band_inverted`; cool unchanged, mirror cap carded); floor-65 and gap-1 tests; §0.2 band qualified "at floor 74".
  M3: heat leg `heat_cool` only, single `heat` parked with a revival trigger, deferred-write test. L1 stand-down row
  rule; L2 shared `S13_pre_heat` site, filter on `reason`; L3 INV-ONE-LEG reworded; L4 stale-T note on the heat leg.
