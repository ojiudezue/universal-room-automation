# Plan review (rev 3): PLANNING_hvac_precool_standdown_and_seasons.md — Tier 2-DB, one adversarial pass

Branch `plan/hvac-precool-standdown` @ `1054acaf`. The reviewer read `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md`
completely first (§0-§12, including the §9e precedence rulings and the §10 ledger C1-C39). Nothing in §10 is
re-asserted here. The reviewer also read the rev-1 review (`PLAN_hvac_precool_standdown_review.md`). Every claim was
re-checked by grep or read on this branch. Read-only on code.

**Verdict: FIX-PLAN.** The rev-3 design is sound. The heat leg is a second caller site on the pre-cool's lifecycle,
uses the BANKING kind, fails closed on None, and edits four membership checks. The §4.3 reader list is complete for
`caller_site` comparisons. But there is a fifth end path that is not a `caller_site` comparison. It releases a live
pre-arrival borrow as `banking_release`, which falsifies the plan's own INV-LIFECYCLE. Two config-boundary gaps
also need plan text and tests before build.

## Findings (ranked)

### M1: the energy pre-cool gate flip-OFF ends a live pre-arrival borrow as `banking_release` (Bug class #53, one missed site; pre-existing for S12, inherited by S13)
- The energy pre-cool loop adds every zone it visits to `_last_precool_zones`, whether the call wrote anything or
  not (`hvac_predict.py:635-644`; the only `continue` is the interrupt latch). A zone that holds a live pre-arrival
  token is visited. Inside `_execute_zone_pre_cool`, `begin_excursion` refuses and the D4b own-row check skips
  (`:1340-1359`), because the token's `caller_site` is not `S12_pre_cool`. The zone is still added to the set.
- When the EC energy pre-cool gate turns OFF, `hvac_predict.py:584-589` calls
  `_release_banked_zones(set(self._last_precool_zones))` with the default trigger `banking_release`.
  `_release_banked_zones` pops the zone's token from `_banking_excursion_tokens` (`:1139`) whatever its caller
  site, and closes it as `banking_release`. No arrival episode is spent, so the next pass begins a second pre-arrival
  borrow on a zone that is still in `_pre_arrival_zones`.
- This path is not one of C1-C4 and is not a `caller_site` comparison, so the planned lint
  (`test_no_raw_s12_prearrival_site_comparisons`) cannot catch it. INV-LIFECYCLE lists "ended by
  `banking_release`" as its falsifier. This path produces exactly that row.
- Legal-config repro (cool leg, live today): shoulder or summer midday with PV export, energy pre-cool scope
  `whole_house` or `auto_pv_tiered` with export surplus. A person-arriving trigger begins an `S12_pre_arrival`
  borrow on zone_2. The next pass runs energy pre-cool, which is refused on zone_2 but adds it to
  `_last_precool_zones`. The EC Solar HVAC Banking gate goes OFF (operator, or EC) before arrival. Zone_2's
  borrow ends `banking_release` and the next pass writes a fresh pre-cool.
  Heat leg: the same sequence on a shoulder day with PV export and a zone below 72 F.
- **Fix in plan:** add it to §4.2 as R5. Then do one of two things. (a) In the energy pre-cool loop, do not add a
  zone to `_last_precool_zones` / `_energy_precool_zones` / `_pre_conditioning_zones` unless this call's own token
  is stored. (b) Or, at `:586-588`, drop zones whose token's `caller_site in PRE_ARRIVAL_CALLER_SITES` before the
  release; the pre-arrival end path owns them. (b) is the smaller change and mirrors the `_pa_rel` split at
  `:490-506`. Add a test, `test_energy_precool_gate_off_leaves_prearrival_borrow` (both legs), and add the site to
  the mutation list. Give reviewer D an explicit instruction: enumerate every `_release_banked_zones(` caller (four
  today: `:498`, `:509`, `:579`, `:588`, plus `:1225`), not only `caller_site` readers.

### M2: the band can invert at a legal floor or baseline setting, and the heat target is capped only by the LIVE cool leg (config-boundary gap, Bug class #63)
- `effective_high = max(base_cool - 2, max(solar_bank_floor, live_low + 2))` (`hvac_predict.py:1287-1297`). The knob
  `64 · Solar Banking Cool Floor` has range 65-80 (`number.py:2768-2777`). With floor <= 71, winter Home 72/70 and the
  zone in Away (live 78/60), the result is `effective_high = max(70, 66) = 70` and `effective_low = min(72, 76) = 72`.
  The stand-down band is empty.
- Repro (floor 66, winter defaults, T = 71): the cool leg runs first, finds T 71 > 70, and writes cool 70. The zone
  sits inside the arrival preset's 70-72 band, and URA cools it to the Home HEAT setpoint. INV-ONE-LEG then skips the
  heat leg, which wanted the opposite. The cool leg alone does this today; rev 3's claims in §0.2/§0.3 ("stand-down
  band 72 <= T <= 74 winter", "no failure remains") hold only at floor >= 74.
- Heat side: the cap is `min(base_heat + 2, live_high - MIN_DEADBAND)`. Nothing keeps `effective_low` at or below the
  arrival preset's own cool (`base_cool`). A baseline edit with a gap under 2 F, e.g. winter Home 73/72, gives
  `effective_low` 74 > `base_cool` 73. The zone is pre-heated above the cool leg that S1 pins on arrival, so the
  furnace runs, then the AC.
- **Fix in plan:** (1) Cap the heat target at the arrival preset as well: `effective_low = min(base_heat + offset,
  base_cool, live_high - MIN_DEADBAND)`. The mirror on the cool side, `effective_high >= base_heat`, is a cool-leg
  change. Decide it explicitly (in scope, or carded), because the cool leg is pre-existing. (2) State the inverted-band
  rule: when `effective_low > effective_high`, neither leg writes for T inside `[base_heat, base_cool]`. Or record
  that cool-first wins and why. (3) Add config-extreme tests, which CLAUDE.md requires when two independent knobs
  interact: floor 65 with the winter baseline, and Home gap 1 F. Update the §0.2 band table to say "at floor 74".

### M3: D3 admits single-`heat` mode for the heat leg, but a range write in a single-setpoint mode is unverified and retries every tick (portability)
- Every leg writes through `set_setpoints(target_temp_low=..., target_temp_high=...)`. The Generic adapter is a pure
  delegate (`hvac_strategy.py:481-497`). The ecobee adapter DEFERS outside `heat_cool` (`:1843-1866`), so on ecobee the
  `heat` entry in the table only produces a begin row and a CM release. What HA and a Generic integration do with a
  low/high pair in `heat` mode is not verified. HA validates by feature flag, not by mode. The plan already applies
  this caution to `auto` ("UNVERIFIED per brand"), but not to `heat`.
- On a defer or exception the CM releases the row, and nothing spends the episode. `is_borrow_active` is False
  on the next pass, so the heat leg begins again. That repeats every 5 min for the whole window (knob 35, up to 110
  min), with an excursion row and a `climate_write` row each time. (Pre-existing for the cool leg in single `cool`
  mode.)
- **Fix in plan:** for the new leg, set `PRE_ARRIVAL_LEG_MODES["heat"] = {"heat_cool"}` until a single-mode write is
  verified per brand, and park `heat`/`cool` single modes with the same revival trigger as AUTO. Or bound the retry
  by spending the episode on a deferred or failed heat begin. Either way, add a test for a deferred heat write on
  two passes: at most one begin.

### L1: the outcome table for the `pre_arrival_standdown` row is incomplete
D2 writes the row when "both legs stood down, or a leg disabled/mode-excluded and the other stood down". The plan does
not say what happens for the other leg outcomes: cool setpoint skip (`effective_high >= live high`, common when the
zone already holds Home in winter), heat setpoint skip (`effective_low <= live low`), `no_temp`, `no_baseline`, latch,
egress paused. A builder will guess. Give the full leg-outcome × leg-outcome table, or the rule "a row iff no leg began
and at least one leg reached a T compare".

### L2: one `climate_write` site string is shared with the energy pre-heat
W2 uses `site=S13_pre_heat`. The energy pre-heat uses the same site (`hvac_predict.py:1773`, reason `pre_heat`), and
its begin `caller_site` is also `S13_pre_heat` (`:1704`). Only `reason` tells them apart in INV-SD-HEAT's SQL. That
works, but say so explicitly in INV-SD-HEAT and D0 check mode, or use a distinct site such as
`S13_pre_arrival_heat`.

### L3: the INV-ONE-LEG wording is too strong
"The heat leg is never evaluated in a pass where the cool leg began" is false on the cool leg's defer path. There the
begin lands, the comfort-delay gate defers, and the CM releases the row (`hvac_predict.py:1396-1427`), so the re-read
`is_borrow_active` is False and the heat leg is evaluated. It is harmless, because the same gate defers the heat
write. Reword it to "no pass writes both legs", and keep the test.

### L4: stale T during an outage now drives a new writer
The rev-2 L2 note covers the cool leg. The heat leg likewise acts on the last T before `unavailable`
(`hvac_zones.py:701-711`). The write to an unavailable entity buys nothing, so harm is nil. Add the note to D2.

## Claims verified (hold)
| Claim | Verdict | Evidence |
|---|---|---|
| §4.3: exactly four `caller_site == S12_PRE_ARRIVAL_SITE` readers | HOLDS (for comparisons) | grep: `hvac_predict.py:495`, `:1206`, `hvac.py:7454`, `hvac_override.py:3966`. Other `caller_site` reads are display or logging (`sensor.py:19199`, `hvac_excursion.py` NM/log text). See M1 for the non-comparison path |
| BANKING over PREHEAT for boot safety | HOLDS | boot audit releases BANKING via `_auto_return(stale_boot_release)` (`hvac_excursion.py:1249-1296`); PREHEAT is rehydrated (docstring `:1138-1141`) |
| `_release_banked_zones` is leg-agnostic (presets-only, D2b, latch, foreign-row) | HOLDS | `hvac_predict.py:957-1155`. Keyed by zone; writes the baseline pair, or pins `pre_preset` |
| URA-write ring boot seed handles a low-only borrow | HOLDS | `hvac.py:7290-7297` seeds `lo` and `hi` |
| C4 drives Q7 and the INFO-1 `arrival` flag from one boolean | HOLDS | `hvac_override.py:3963-3997`; `_arrester_reference(arrival=True)` `hvac.py:385-392` |
| D1b covers heat tokens | HOLDS | the heat token is in `_banking_excursion_tokens`; the `_pa_rel` split after the C2 edit routes it to `pre_arrival_inactive` |
| Energy pre-heat refuses over a pre-arrival heat row | HOLDS | D4b own check `hvac_predict.py:1734` (`caller_site == "S13_pre_heat"`) |
| Arrival while energy PREHEAT or another borrow is live → neither leg | HOLDS | the caller's `is_borrow_active` guard (`:697`) plus the plan's re-read; gate (e) row for PREHEAT |
| Home heat is 70 in every season; winter/shoulder/summer targets | HOLDS at defaults | `SEASONAL_DEFAULTS` `hvac_const.py:1225-1244` (tuples are (cool, heat)). Band claims hold only at floor 74 (M2) |
| Winter reasoning for dropping the season gate | HOLDS at defaults; see M2 for floor/baseline extremes | the 75 → 74 → Home-72 walk-through is arithmetically right |
| D3 reads the right field; `unknown` reaches it, `unavailable` does not | HOLDS | `hvac_zones.py:701-705` |
| Rev-2 fixes on the heat leg: no write on release (D1b), one row per membership (flag), `DailyCounter` | HOLD (L1 = row-condition detail) | |
| No schema change | HOLDS | new `caller_site` value / activity action use existing TEXT columns (`database.py:1952`) |
| Tier 2-DB | AGREED | |

## Must-fix before build
1. M1: add R5 (energy pre-cool gate-OFF release) with a pre-arrival filter, a test, and a mutation anchor; widen
   reviewer D's enumeration to every `_release_banked_zones(` caller.
2. M2: cap `effective_low` at `base_cool`; state the inverted-band rule; add the floor-65 and narrow-gap tests;
   qualify the band table.
3. M3: restrict the heat leg to `heat_cool` (or bound retries by spending the episode); add the deferred-write test.

L1-L4 are cheap and belong in the same revision.
