# PLANNING: pre-arrival pre-cool stand-down + seasonal scope

Card: `HVAC-PRECOOL-STANDDOWN-WHEN-COOL-1` (thread hvac, Tier 2). Operator 2026-11-12: "Yes make pre-cool smarter.
It's a summer feature that we should tune for the seasons."

Read first, completely, before this plan: `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` (741 lines, incl. §9e
and the §10 ledger C1-C39), `docs/planning/AUDIT_pre_arrival_inventory_and_precool_standdown.md`, `CLAUDE.md` (incl.
the fire-check / forward-trace corollary, `CLAUDE.md:416-423`). Nothing in §10 is re-asserted here. Paths are under
`custom_components/universal_room_automation/`; `hvac*.py` = `domain_coordinators/`. Code read at develop `b0fd69a6`.

---

## 0. Answer first (marginal-benefit decomposition, done before the spec)

1. **Stand-down (build).** Pre-arrival pre-cool never reads a temperature (`hvac_predict.py:1293-1300`: the only skip
   is `effective_high >= zone.target_temp_high`, a setpoint-vs-setpoint compare). 17 of 34 measured writes landed on a
   zone already at or below the new cool target (audit). Each such write buys zero cooling and still costs one Carrier
   cloud write, a `begin_excursion` row, arrester suppression and a Carrier manual hold until the presets-only return.
   The simplest fix (one compare, before the borrow begins) captures the whole benefit. Build it.
2. **"End" on reached target (do NOT build).** A pre-cool that reaches its target mid-window is the feature
   succeeding; the thermostat idles at the target. Ending the borrow early returns the zone to its pre-borrow preset
   (Away, cool 80 in 45 of 52 writes), which lets it warm before the person arrives. "End early" only makes sense for
   a zone that was already cool at START, and that case is the skip in (1). So the stand-down is a start-time skip,
   re-evaluated every tick while the zone stays in the pre-arrival set (the block at `hvac_predict.py:686-707` runs
   each cycle and only skips on `is_borrow_active`), so a zone that warms during the window still gets its pre-cool.
3. **Seasons (build the minimal piece; park the rest).** Decomposition:
   - The target is already per season: it is the season's Home cool baseline minus 2 F
     (`_resolve_baseline_range` -> `PresetManager.get_seasonal_setpoints`, `hvac_preset.py:126`; per-season,
     operator-editable baselines `CONF_HVAC_BASELINE_<SEASON>_HOME_COOL`, `hvac_const.py:1259+`).
   - With (1) in place, a heating-season zone (typically below 74) stands down by itself. What remains for a season
     gate is a winter zone above the target (sun-warmed), where pre-cool would run the AC on an arrival in winter.
   - The energy pre-cool path already gates on season (`hvac_predict.py:763-766`, summer + shoulder, skip reason
     `off_season`). Mirror that for pre-arrival: one membership test on `PresetManager.current_season`, a rung-1
     tuple. Cheap, reuses the existing idiom, matches the operator's "summer feature".
   - Outdoor-temperature gate, per-season offset knobs, and an arrival PRE-HEAT mirror: PARKED (§9). The outdoor gate
     is subsumed by the indoor stand-down (indoor temperature is the quantity the cool leg acts on). Arrival pre-heat
     does not exist (audit "Heat side"; `_execute_pre_heat` at `hvac_predict.py:709-726` is season/forecast/hour
     triggered, not arrival triggered) and would be a NEW borrow writer on the heat leg with zero winter data.
4. **Config-first.** No existing setting does this. Checked: switch `28 · HVAC Predictive Conditioning` and
   `35 · Pre-Arrival Conditioning` are on/off for the whole feature; knob `35 · Pre-Arrival Window (min)` (live 20)
   bounds duration; `hvac_solar_bank_floor` (live 74) raised to the Home cool would neuter pre-arrival AND energy
   banking for all temperatures. None reads room temperature or season for this path. Code is needed.

---

## 1. Institutional context verified

### 1.1 REUSE-or-BUILD per proposed piece

| Piece | Verdict | Evidence |
|---|---|---|
| Zone temperature for the stand-down | **REUSED** `ZoneState.current_temperature` (`hvac_zones.py:140`, set from the climate entity attr at `:711`) | The cool leg acts on the thermostat's own sensor, so "inert write" is exactly `current_temperature <= effective_high`. `ZoneState.avg_temperature` (`hvac_zones.py:263-276`, weighted room average, falls back to `current_temperature`) is NOT used: a room average can read below the thermostat while the thermostat still calls for cooling (and vice versa). Card constraint "decide what zone temperature means" answered: the thermostat's reading. |
| Compare idiom | **REUSED** from the pre-arrival fan helper (`hvac_predict.py:1494-1527`, `room_temp < setpoint_high` -> skip `below_setpoint`, `None` -> skip `no_data`) | Same shape, applied to the zone. Difference on None, see D1 (fail-open). |
| Season source | **REUSED** `PresetManager.current_season` (`hvac_preset.py:100-118`; months `SUMMER_MONTHS {6,7,8,9}`, `WINTER_MONTHS {12,1,2}`, else shoulder, `hvac_const.py:1207-1208`); already read as `season` in `_check_pre_conditioning` (`hvac_predict.py:445`) | No new season resolver. |
| Season gate idiom | **REUSED** from energy pre-cool `hvac_predict.py:763-766` (`season not in (SEASON_SUMMER, SEASON_SHOULDER)` -> `off_season`) | |
| Outdoor temperature | Exists (`HVACPredictor._get_outdoor_temp`, `hvac_predict.py:1942-1952`, entity shared from the cover controller `hvac.py:1593-1597`). **Not used** (parked, §9). | |
| Margin knob | **NEW** Number entity. Grep of `const.py`, `hvac_const.py`, `config_flow.py`, `options_flow.py`, `number.py`, `switch.py`, `select.py`, `domain_coordinators/*` for `standdown`, `stand_down`, `precool_season`, `pre_arrival_season`, `pre_cool_margin`: no equivalent. The only `_stand_down` hits are S10's local skip variable (`hvac.py:4779-4801`), unrelated. Sibling to reuse as a template: `PreArrivalWindowMinutesNumber` (`number.py:602-641`, knob 35). Used knob numbers: 00-04,10,15,20,25-28,30,31,35,40,45-50,52 (`_attr_name` grep of number/switch/select). |
| Season tuple | **NEW** rung-1 const `PRE_ARRIVAL_PRECOOL_SEASONS` in `hvac_const.py` next to `PRE_ARRIVAL_PRECOOL_OFFSET_F` (`:497-500`). No equivalent (grep above). |
| Stand-down kill switch | **NEW** rung-1 const `PRE_ARRIVAL_PRECOOL_STANDDOWN_ENABLED` (see §6 for why not a switch). |
| Skip-reason surface | **REUSED** `sensor.ura_hvac_pre_arrival_status` (`sensor.py:14463-14514`, already exposes `fan_rooms_skipped` from `_last_fan_skipped_rooms`, reset per cycle at `hvac_predict.py:454`). New attrs on it, no new entity. |
| Ledger row | **REUSED** `ura_activity_log` via the predictor's existing activity logging (same channel the `pre_arrival` intake row uses, `hvac.py:7256-7268`). New action name `pre_cool_standdown`. |
| Trip-wire persistence | **REUSED** the `_zone_state_store` side-key pattern (`__interrupt_latch`, `__immune_holds`, `__tao_state`, §9e). New side-key `__precool_standdown_ring`. |
| Trip-wire notification | **REUSED** NM dispatch as S10 latches do (`_s10_notify`, severity HIGH because MEDIUM reaches no live channel, STATE_OF_PLAY line 88). |

### 1.2 Prior plans consulted
- `PLANNING_hvac_w1_w2_finish.md` (D3/D4: one write from the baseline, `S12_pre_arrival` caller_site, end triggers,
  spent episode, Q7). Skimmed the D4 section; the stand-down sits inside D4's single-write rule and changes none of
  the end paths.
- `PLANNING_v5.7.x_energy_pre_cool_unification.md`, `PLANNING_hc_precool_toggle_oc_observability.md`,
  `PLANNING_ec_precool_delete_and_vacancy_hold_assistive.md`: headers; energy pre-cool path, out of scope here.
- `AUDIT_pre_arrival_inventory_and_precool_standdown.md`: full read; source of the 17/34 number and the inventory.

### 1.3 Memory bodies
`reference_hvac_state_of_play`, `feedback_marginal_benefit_pushback`, `feedback_config_first_before_code`,
`feedback_measure_before_build`, `project_house_zones_vs_hvac_zones` (the stand-down is per HVAC zone, keyed by
thermostat; no house-zone fan-out involved).

### 1.4 Code read end to end
`hvac_predict.py` `_check_pre_conditioning` pre-arrival block `:683-707`, `_execute_zone_pre_cool` `:1259-1310`
(through the floor/skip), `_activate_zone_fans` skip logic `:1494-1527`, energy season gate `:755-786`,
`_get_outdoor_temp` `:1942`; `hvac_preset.py:95-160`; `hvac_zones.py:138-140`, `:262-276`, `:705-711`;
`hvac_const.py:490-505`, `:1207-1244`.

---

## 2. Falsifiable invariants

- **INV-SD (stand-down).** With the stand-down enabled, in ANY reachable path, a pre-arrival pre-cool
  (`_execute_zone_pre_cool(reason="pre_arrival")`) never calls `begin_excursion` and never calls the thermostat write
  when the zone's thermostat reading `T` is numeric and `T <= effective_high + margin`. Falsified by: a
  `climate_write` row with site `S12_pre_cool`, reason `pre_arrival`, whose recorder `current_temperature` at or
  before the row's `ts_issued` is `<= values_after.target_temp_high + margin`.
- **INV-SEASON.** No pre-arrival pre-cool begins while `PresetManager.current_season` is not in
  `PRE_ARRIVAL_PRECOOL_SEASONS`. Pre-arrival FANS are not affected by either gate.
- **INV-NOOP (byte-identical).** When `T` is None, or `T > effective_high + margin`, and the season is in the tuple,
  the call sequence, excursion row and `climate_write` row are identical to today's. The energy pre-cool caller
  (`hvac_predict.py:635`, reason not `pre_arrival`) is identical in every case.

---

## 3. Producer and consumer checks

### 3.1 Values touched

| Value | Producer (how computed, health) | Consumers |
|---|---|---|
| `zone.current_temperature` | Climate entity attr `current_temperature`, copied per cycle at `hvac_zones.py:711`. Carrier reports whole degrees; the attr only changes on 1 F steps (audit: state age 6 s to ~1.1 h). Healthy on all 3 zones in the 14-day recorder window (34/34 writes after 11-05 had a value). Ground truth = the thermostat's own sensor, which is also what the cool leg acts on. | Today: zone status sensor (display, `hvac_zones.py:1219`), `avg_temperature` fallback. NEW: the stand-down compare (trust decision). |
| `effective_high` | `max(baseline_home_cool + PRE_ARRIVAL_PRECOOL_OFFSET_F, max(solar_bank_floor, target_temp_low + MIN_DEADBAND))`, `hvac_predict.py:1284-1297`. Live: baseline 77, floor 74 -> 75 (every DB row shows 75). Shoulder default baseline 74 -> 72 -> floored to 74; winter default 72 -> 70 -> 74, i.e. above the season's Home cool. | Today: the write value + the setpoint skip. NEW: the stand-down compare. |
| `current_season` | Month table, `hvac_preset.py:104-118`. No outdoor input. November = shoulder. | Today: energy pre-cool gate, pre-heat gate, baselines. NEW: pre-arrival gate. |
| margin (NEW knob) | Number entity, see §6. | Stand-down compare only. |

Reachable oddity to note, not fix: in winter (and shoulder at defaults) the floor makes `effective_high` >= the
season's Home cool, so the "pre-cool" writes a cool leg no cooler than Home. The season gate removes the winter case;
shoulder keeps today's behaviour (non-goal).

### 3.2 Fire check (CLAUDE.md corollary 1) — measured 2026-11-12 on the live DB

`hvac_excursion_events` (rows from 2026-08-23), kind `banking`:

| Month | site | borrows | ended by `pre_arrival_arrived` |
|---|---|---|---|
| 2026-08 | `S12_pre_cool` (pre- and energy pre-cool mixed; caller_site split only from v5.103.23) | 18 | n/a |
| 2026-09 | `S12_pre_cool` / `S12_pre_arrival` | 66 / 2 | — / 2 |
| 2026-10 | `S12_pre_arrival` | 76 | 56 |
| 2026-11 (to 12th) | `S12_pre_arrival` | 45 | 34 |

`ura_activity_log` (retention from 2026-10-13): `pre_arrival` intake rows 136 (Oct 13-31), 201 (Nov 1-12).
Audit (14 d): 52 writes, 34 with a known thermostat temperature, 17 at or below 75, 5 strictly below.

So the producer fires steadily (about 2-4 writes/day) and in the shoulder season. Wasted fraction before 11-05 is
unmeasured (recorder starts 11-05). D0 closes that.

### 3.3 Forward trace (corollary 2)
Pre-arrival signal -> `_handle_person_arriving` (`hvac.py:7212-7281`) -> `_pre_arrival_zones` -> cycle ->
`_check_pre_conditioning` block `hvac_predict.py:686-707` -> `_execute_zone_pre_cool` -> `begin_excursion`
(`S12_pre_arrival`) -> `emit_set_temperature` (site `S12_pre_cool`, one `climate_write` row) -> Carrier manual hold
-> ended by `async_end_pre_arrival_borrows` (`hvac.py:7414-7491`; triggers arrived / timeout / max_age / interrupted /
inactive) -> presets-only return to the S1 target. The stand-down cuts the chain BEFORE `begin_excursion`, so nothing
downstream (arrester suppression, gate (e), S10 `borrow_live` skip, Q7 reference, spent-episode logic) sees a borrow.
Downstream consequences to verify in tests: no `_last_precool_zones` add, gate (e) does not hold S1 for that zone, the
zone stays in `_pre_arrival_zones` (fans and the sweep exemption keep working), and the next tick re-evaluates.

### 3.4 Policy placement (corollary 3)
The stand-down is policy for ONE consumer (the pre-arrival thermostat write). It lives at that consumer, inside the
`reason == "pre_arrival"` branch. The producer (arrival signal, `_pre_arrival_zones`) is untouched; fans keep their own
room-level `below_setpoint` rule.

---

## 4. Decision-site enumeration (Bug Class #53)

`grep -rn "_execute_zone_pre_cool" --include='*.py'` -> exactly two callers:
1. `hvac_predict.py:635` energy pre-cool (reason energy). **Untouched** (INV-NOOP).
2. `hvac_predict.py:698` pre-arrival (`reason="pre_arrival"`, `from_baseline=True`). **Gated.**

Placement rule for the builder: the stand-down check goes INSIDE `_execute_zone_pre_cool`, after `effective_high` is
computed (`:1297`) and after the existing setpoint skip (`:1299-1300`), BEFORE the `hvac_excursion` import / any
`begin_excursion` (`:1305+`), keyed on `reason == "pre_arrival"`. The season gate goes at the CALLER (`:697`, before
`is_borrow_active` / the call), so fans (`:703-704`) and the `_pre_conditioning_zones.add` (`:706`) keep running.
Not in the caller for the stand-down because `effective_high` is computed inside the function (one copy).

No other site writes a pre-arrival pre-cool (S12 is the only `climate_write` site with reason `pre_arrival`;
audit 52/52 rows). The re-grep must be repeated by the plan reviewer and the builder.

---

## 5. Deliverables

### D0: Fire-check probe (read-only, first; go/no-go for nothing, feeds the README)
One-shot script `scripts/probes/hvac_precool_standdown_probe.py` run via `ssh ha "python3 -" <`. Per month since
2026-08-23: pre-arrival borrows, writes, end-trigger split; wasted fraction using (a) recorder thermostat
`current_temperature` where available (11-05 on), (b) for older rows the URA `environmental_data` room temperatures
(room_id -> HVAC zone via the zone map) as a labelled PROXY, and (c) per-month `outside_temp` from the same table so
the season split has a number. Output: a table appended to this plan's §3.2 and to the README. No gating role (the
14-day 50% already justifies the build); its job is the before-baseline for the Live check.
- **Verify:** the table exists with thermostat-measured and proxy columns kept separate.
- **Test:** none (probe).
- **Live:** n/a.

### D1: Stand-down at start
In `_execute_zone_pre_cool`, for `reason == "pre_arrival"` and `PRE_ARRIVAL_PRECOOL_STANDDOWN_ENABLED`:
read `T = zone.current_temperature`. If `T` is numeric and `T <= effective_high + margin`: no borrow, no write;
record skip reason `already_cool` with `T`, `effective_high`, `margin` in a per-cycle list
`_last_precool_standdowns` (reset at the same place as `_last_fan_skipped_rooms`, `hvac_predict.py:454`), increment a
daily counter, and queue ONE `ura_activity_log` row `action=pre_cool_standdown` per (zone, arrival episode) (not per
tick; key on the zone's `_pre_arrival_start` value). If `T` is None or non-numeric: proceed as today (fail-open to the
legacy write, record `no_temp` in the skip list, no row). Fail-open is deliberate: a missing reading must not silently
disable the feature, and the legacy write is the known-safe behaviour.
- **Verify:** zone at 74 with target 75, margin 0 -> no `begin_excursion`, no funnel call, skip `already_cool`.
- **Verify (discriminating):** zone at 76 -> write happens (75). Under a plausible wrong build that compares
  `avg_temperature` instead, a fixture with rooms at 73 and thermostat at 76 would skip; the test pins that it writes.
  Under a build that placed the check after `begin_excursion`, an orphan banking row appears; the test asserts zero
  excursion rows.
- **Verify:** `T=None` -> write happens (legacy), skip list shows `no_temp`.
- **Verify:** a zone skipped at tick N whose `T` rises to 77 at tick N+1 (still in `_pre_arrival_zones`) gets the
  pre-cool at N+1.
- **Verify:** energy caller with `T` far below target writes exactly as before (INV-NOOP).
- **Verify:** fans still activate for a stood-down zone (rooms above their setpoint) and the zone still reads
  `pre_arrival` on its status sensor.
- **Test:** `quality/tests/test_hvac_precool_standdown.py`: `test_standdown_at_target_skips_borrow_and_write`,
  `test_standdown_below_target_skips`, `test_above_target_writes_legacy`,
  `test_uses_thermostat_reading_not_room_average`, `test_none_temperature_fails_open`,
  `test_reevaluates_next_tick_when_zone_warms`, `test_energy_precool_unaffected`,
  `test_fans_and_presence_label_unaffected`, `test_margin_widens_standdown` (T=76, margin 1 -> skip),
  `test_one_activity_row_per_episode`, `test_kill_const_false_is_legacy`. Mutation anchor: deleting the compare must
  turn `test_standdown_at_target_skips_borrow_and_write` red; moving it below `begin_excursion` must turn
  `test_standdown_at_target_...` red via the excursion-row assert.
- **Live:** over the first 3 days after deploy, every `climate_write` row with `site=S12_pre_cool` and reason
  `pre_arrival` has a recorder thermostat temperature `> 75 + margin` at `ts_issued` (INV-SD probe, the D0 script in
  check mode); at least one `pre_cool_standdown` row exists if any arrival happened with the zone at or below 75
  (zone_2 evenings were the 5 strictly-below cases).

### D2: Season gate
At the pre-arrival caller (`hvac_predict.py:697`), skip the pre-cool call (not fans, not the set add) when
`season not in PRE_ARRIVAL_PRECOOL_SEASONS`; record skip `off_season` in the same skip list. One INFO per zone per
season change, not per tick.
- **Verify:** winter (December) fixture: no pre-cool call; fans still run; skip `off_season`.
- **Verify:** shoulder and summer: behaviour as D1.
- **Test:** `test_winter_skips_precool_keeps_fans`, `test_shoulder_and_summer_run`.
- **Live:** today (November, shoulder) no change is observable; the gate is proven in-suite. Record that in the README
  table. December 1 is the first live evaluation: zero `S12_pre_cool`/`pre_arrival` `climate_write` rows from 12-01,
  `off_season` in `sensor.ura_hvac_pre_arrival_status` skip list on any arrival. (One-shot query at the next
  organic-card disposition after 12-01, not a soak.)

### D3: Observability
On `sensor.ura_hvac_pre_arrival_status` add attrs `precool_skipped_zones` (the per-cycle list: zone, reason,
`T`, `effective_high`, margin), `precool_standdowns_today`, `precool_writes_today`, `precool_season_active` (bool).
Display only; no decision reads them.
- **Verify:** attrs present and reset at local midnight with the other daily counters.
- **Test:** `test_status_sensor_exposes_standdown_attrs`.
- **Live:** `sensor.ura_hvac_pre_arrival_status` shows the four attrs after restart; `precool_season_active` true.

### D4: Zero-fire / all-fire trip-wire (fire-check corollary)
Persist a 7-slot daily ring `(standdowns, writes)` in `_zone_state_store` side-key `__precool_standdown_ring`, rolled
at local midnight. At the rollover: if the 7-day total of pre-arrival evaluations (standdowns + writes) is at least
`PRECOOL_TRIPWIRE_MIN_EVALS` and EITHER standdowns == 0 OR writes == 0 while the season gate is open, send one NM
(severity HIGH, hazard `precool_standdown_tripwire`, at most once per 7 days) naming which side went silent. Zero
standdowns over many arrivals means the stand-down is dead (or the weather turned hot, which the NM text says);
zero writes means it is swallowing every arrival (e.g. a stale temperature).
- **Verify:** ring survives restart; NM fires once for each silent side; no NM when the season gate is closed.
- **Test:** `test_tripwire_zero_standdowns`, `test_tripwire_zero_writes`, `test_tripwire_quiet_off_season`,
  `test_ring_persists_across_restart`.
- **Live:** `__precool_standdown_ring` present in the zone-state store after the first midnight.

---

## 6. Knobs (every number)

| Name | Rung | Default | Why this rung | Kill semantics |
|---|---|---|---|---|
| `NN · Pre-Cool Stand-down Margin (°F)` (Number, `PreCoolStanddownMarginNumber`, next free HVAC number; template `PreArrivalWindowMinutesNumber` `number.py:602`) range 0.0-3.0 step 0.5 | 3 (live Number) | 0.0 | The operator asked for a margin knob and will tune it by watching which arrivals pull 76-77 F zones down to 75 (12 of 34 writes). Margin 0 = skip only when already at/below target; 1 = also skip the 76 band. | Not a kill switch (0 still stands down at target). |
| `PRE_ARRIVAL_PRECOOL_STANDDOWN_ENABLED` | 1 (const) | True | A back-out, not a policy dial; turning it off should take a reviewed change. | False = today's behaviour exactly (INV-NOOP). |
| `PRE_ARRIVAL_PRECOOL_SEASONS` | 1 (const) | `(SEASON_SUMMER, SEASON_SHOULDER)` | Mirrors the energy pre-cool gate (also a literal at `hvac_predict.py:764`); per-season enablement is not something the operator should flip by observation. Revisit as rung 2 only if the operator asks to drop shoulder. | Adding `SEASON_WINTER` = today's behaviour. |
| `PRECOOL_TRIPWIRE_MIN_EVALS` | 1 | 10 | Below ~10 arrivals/week a silent side is noise (measured ~15-30/week). | 0 = trip-wire off (documented on the const). |
| `PRECOOL_TRIPWIRE_WINDOW_DAYS` | 1 | 7 | Ring length. | — |
| `PRE_ARRIVAL_PRECOOL_OFFSET_F` | 1 (unchanged) | -2.0 | Not touched. | — |

---

## 7. Non-goals
- Energy pre-cool (caller `hvac_predict.py:635`) and its own season gate: untouched.
- Ending a running pre-cool when the zone reaches its target (§0.2: wrong behaviour).
- Arrival pre-heat, outdoor-temperature gate, per-season offset knobs (parked, §9).
- The shoulder floor oddity (`effective_high` >= Home cool at default shoulder baselines).
- Pre-arrival fans' own `below_setpoint` rule; the geofence-intake volume (151/218 rows, audit) — separate question.
- Any change to borrow code (`begin_excursion` / `return_excursion`), the funnels, S1 or the arrester.
- Room-average temperature as the zone temperature.

## 8. Tier
**Tier 2** (card tier holds). Trigger check: the change is ONE consumer site plus a caller gate, it removes writes
rather than adding a writer, does not touch a shared primitive, borrow code, funnels, S1 precedence or any
cross-coordinator value, and fails open to today's behaviour. HVAC-control touch argues for care, so: one adversarial
plan review before build; two framing-disjoint code reviews (A correctness + edge cases incl. None/stale temperature,
whole-degree boundary, margin extremes 0 and 3; B lifecycle: per-tick re-evaluation, restart with a zone mid-window,
ring persistence, midnight rollover) plus a per-site mutation pass on the D1 compare and the D2 gate; live validation
with the README write-back. Not Tier 2-DB (no schema change; the new activity-log action uses the existing table).

## 9. Parked (with revival triggers)
- **Outdoor-temperature gate** — revive if D0/Live shows stand-downs failing on hot days because the thermostat
  reading lags (e.g. writes skipped at T=75 followed by arrival at >= 78 within the window).
- **Per-season offset (rung 3)** — revive if the operator reports shoulder/summer arrivals too warm or too cold with
  the stand-down live.
- **Arrival pre-heat mirror** — revive only with winter data showing arrivals into zones below the Home heat leg by
  >= 2 F (first measurable after 12-01) and an operator ask; it is a new heat-leg borrow writer (Tier 3 shape).
- **Mid-window end on reached target** — not parked; rejected (§0.2).

## 10. Doc write-back owed by the build
HVAC STATE_OF_PLAY: a header entry, §4.2 S12 row (stand-down + season gate), §8 new knob. README with the Live table.
