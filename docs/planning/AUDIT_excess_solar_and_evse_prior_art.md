# AUDIT — Excess-solar detection, grid export/import measurement, and EVSE control: prior art + mechanism walkthrough

**Date:** 2026-08-23
**Trigger card:** `EVSE-SOLAR-FOLLOW-AMPS-1` (thread `energy`, status `pre_planning`)
**Mode:** READ-ONLY audit. No code, config, or live state was changed. Test suite NOT run.
**Scope:** everything URA already has for (a) excess-solar detection, (b) grid export/import
measurement, (c) EVSE charge control — plus an end-to-end mechanism walkthrough of the four
control paths that can touch an EVSE (HC, TOU, SOLAR, DP) and the interaction matrix between them.

## How to read this document

* Every claim carries a `file:line`. A claim without one is marked **could not determine**.
* **[LIVE]** = executable code. **[COMMENT]** = the claim rests on a comment or docstring only.
  Comments in this codebase have been found stale — see §8 (Stale-comment register).
* **CONFIGURED** vs **DEFINED**: a `CONF_*` that exists in `energy_const.py` but is absent from
  the live config entry behaves as absent. §2 marks each.
* Confusable pairs are called out explicitly in §7. Two of them have already cost real time.

---

## 1. REUSE TABLE — what the solar-follow card proposes vs what exists

Rows are the capabilities `EVSE-SOLAR-FOLLOW-AMPS-1` proposes (from its `PROPOSED_SHAPE_SIMPLEST_VERSION`).

| # | Proposed capability | Verdict | Existing prior art (file:line) | Notes |
|---|---|---|---|---|
| 1 | "Runs only while an EVSE is already excess-solar-active" | **REUSE** | `EVChargerController._excess_solar_active` (`energy_pool.py:202`), populated/drained by `determine_excess_solar_actions` (`energy_pool.py:1318-1701`) | Set is persisted per-EVSE (`energy.py:1839`) and restored (`energy.py:1365-1366`), and torn-restart-reconciled (`energy.py:5183-5225`). A new controller can read this set directly. |
| 2 | Write an amp value to a `number` entity | **REUSE the write shape; NEW the target** | `_execute_service_action` (`energy.py:6455-6476`) is fully generic over `{service,target,data}`; `number.set_value` already emitted at `energy_battery.py:4774`, `energy_battery.py:5449`, `energy.py:4848`, `energy.py:7223`, `energy.py:7247`, `energy_pool.py:122`, `energy_pool.py:140` | **The card's RISKS section says "a device URA has never written to… a new class of command". The command CLASS is not new — `number.set_value` is an established action shape with an established dispatcher.** What is new is the target entity. |
| 3 | "Restore to 48 when the solar session ends" (leave-and-return on a number entity) | **REUSE the pattern** | `PoolOptimizer` (`energy_pool.py:58-160`): `_original_speed` captured on entry (`energy_pool.py:113-115`), restored via `number.set_value` on exit (`energy_pool.py:139-148`), with an explicit "entity unavailable → keep state, retry next cycle" branch (`energy_pool.py:135-137`) | This is a structurally identical feature (TOU-driven continuous modulation of a `number` entity with save/restore) already shipped. It is the closest precedent in the repo and should be the template. |
| 4 | Deadband / step-limit / "write only when target differs" | **NEW** | No amp control exists. Nearest analogue is grid-cap hysteresis (`energy_pool.py:1738`, `hysteresis_kw` default `DEFAULT_GRID_IMPORT_CAP_HYSTERESIS_KW`, `energy.py:5779`) and the drain sticky band `F±2` (`energy_pool.py:1922-1926`) | No generic write-deadband primitive exists. |
| 5 | Reuse write-verify (`energy_write_verify.py`) for the amp write | **EXTEND — does NOT work as-is** | `_maybe_schedule_write_verify` is **surface-keyed and hard-gated**: a `number.set_value` whose `target` != the configured reserve entity returns early and is silently NOT verified (`energy.py:7587-7591`) | Reusing write-verify requires registering a NEW surface. The card's assumption that it "exists and should be reused rather than reinvented" is true only with that extension. |
| 6 | Measure spare solar as `solar_production_w − house_load_excluding_evse` | **REUSE both terms — but a better single term already exists** | `solar_production_w()` (`energy_battery.py:1586-1612`, W-normalized, LKG-stamped); house-load-minus-EV already computed by `_dp_house_load_kw(ev_load_w)` (`energy.py:4151-4193`); EV load by `current_charging_load_w()` (`energy_pool.py:2286-2312`) | **A single signed grid figure is already live and normalized: `net_power_w` (`energy_battery.py:1614-1623`), positive = importing, negative = exporting.** See §4. Subtracting two large numbers is the strictly worse estimator. |
| 7 | Cross-check via an Emporia mains export sensor | **EXTEND — the knob exists, is UNSET, and its sign convention is INVERTED vs the operator's sensor** | `CONF_ENERGY_MAINS_EXPORT_ENTITY` (`energy_const.py:1492`), consumer `EnergyCoordinator.mains_export_active(threshold_w=100.0)` (`energy.py:4044-4097`), called at `energy_pool.py:633` and `energy_pool.py:1422` | See §7.1 — wiring the operator's actual sensor into this knob **without a sign change would invert the meaning**. |
| 8 | Stop on Solcast next-hour / next-X-hours falling below a floor | **EXTEND** | Solcast today / remaining / tomorrow / day_3 are wired (`energy_battery.py:1658-1688`; config `energy_solcast_*` all SET). `next_hour` / `next_x_hours` are **NOT** wired — no `CONF_*` and no consumer | Adding them is genuinely NEW config surface. |
| 9 | "Separate lightweight timer, do not change the EC 5-min tick" | **NEW** | Every EVSE decision today runs inside the single EC decision cycle; the dispatch order is `energy.py:5628 → 5717 → 5726 → 5757 → 5776 → 5839 → 5893` | Correct instinct — but see §6-INT-6: a sub-tick writer means the amp value and every EVSE owner-set decision are computed on **different clocks**. That is a new seam, not just a new timer. |
| 10 | Never write during peak | **REUSE** | `determine_excess_solar_actions` already returns early and clears the whole claim set on `tou_period == "peak"` (`energy_pool.py:1354-1374`) | The card's Q3 finding is confirmed correct. |
| 11 | A knob for min-amps / deadband / step | **NEW** — no amp knob exists | Repo-wide grep for `charging_amps|current_limit|set_charge_rate|max_charging|charger_current|amperage|max_current` over `custom_components/**.py` returns **zero** control hits (only `_observed_net_charge_rate_per_hour` and `AVERAGE_CHARGE_RATE_KW` in `energy_forecast.py:34`, both unrelated) | The card's institutional-context claim on this point is **verified TRUE**. |
| 12 | Restart safety for a mid-session throttle | **EXTEND** | The EVSE owner-set persistence machinery exists and is registry-driven (`energy_pool_owners.py:203-208`, save `energy.py:1830-1841`, restore `energy.py:1355-1375`) | A persisted `_original_amps` per EVSE would slot into `EV_REGISTRY` as a dict-shape declaration. Nothing exists today. |

### 1.1 The single most important finding for this card

**The excess-solar trigger does not measure solar surplus at all.** On the normal (non-blind) path,
`determine_excess_solar_actions` gates purely on `soc >= soc_threshold AND remaining_forecast_kwh >=
kwh_threshold` (`energy_pool.py:1574-1579`). Live thresholds: `energy_excess_solar_soc = 95`,
`energy_excess_solar_kwh = 5.0`. No export, net-power, or production reading is consulted on that
path. `mains_export_active()` is consulted **only** inside the blind-window branch
(`energy_pool.py:1422`) and the blind-window off-peak ride helper (`energy_pool.py:633`).

Consequence for the card: the feature is not "modulate within a measured-surplus session" — there is
no measured surplus today. A solar-follow controller would be **introducing the first measured-surplus
signal into the EVSE path**, not refining an existing one.

### 1.2 The yo-yo, located in code — and the card's diagnosis is one floor off

The card says the loop bottoms out on `ev_battery_drain_soc` (live 80). Two release legs exist, and
**the 95 one fires first**:

1. **Excess-solar release, no hysteresis, no min-on-time** — `energy_pool.py:1685-1699`. When
   `conditions_met` goes False (i.e. the moment SOC drops from 95 to 94, or the Solcast remaining
   falls below 5.0 kWh), every EVSE in `_excess_solar_active` is commanded `switch.turn_off` and the
   claim is dropped. There is no deadband on either input and no minimum on-time. Re-entry requires
   SOC to climb back to ≥95. **This is a complete yo-yo oscillator on its own, with a period set by
   how fast an 11.5 kW draw moves the battery through one SOC point.**
2. **Drain-protection release at 80** — `energy_pool.py:1946-1959`, firing on
   `charging AND battery_power_w < -100 AND battery_soc < soc_threshold`, where `soc_threshold` is
   `self._ev_battery_drain_soc` (`energy.py:5847`), live 80. This is the backstop the card describes.

Leg 1 is upstream of leg 2 and has a 15-point-higher floor, so under the live config the observed
cycle should bounce at ~95, not ~80.

**Marginal-benefit consequence (house rule: compare margins, not totals).** A hysteresis band and a
minimum-on-time on the EXISTING gate at `energy_pool.py:1574-1579` / `:1685` is a few lines inside a
function that already exists, with no new writer, no new actuator class, no sub-tick clock, and no
write-volume exposure. Amp modulation is a new writer on a live actuator at 30-60 s cadence. The
decomposition question the card has not yet answered is: **how much of the yo-yo does the deadband
alone remove, and what is the residual margin that amp modulation buys on top of it?** That question
should be settled before a build is scoped.

---

## 2. The EVSE control surface — twelve owners, one switch

Every mechanism that can turn an EVSE on or off does so by claiming membership in a named
**owner set** on `EVChargerController`. The sets are declared once in
`energy_pool_owners.py` (`EV_REGISTRY`), which is the single source of truth for pruning,
peer-hold checks, persistence and the status classifier (`energy_pool_owners.py:1-70`).

| Owner | Attr (`energy_pool.py`) | Declared | Peer-hold member? | Persistence | Classifier priority |
|---|---|---|---|---|---|
| TOU | `_paused_by_us` | `:200` | **No** | per-EVSE bool | 6 |
| excess_solar | `_excess_solar_active` | `:202` | **No** | per-EVSE bool | 7 |
| grid_cap | `_paused_by_grid_cap` | `:203` | Yes | list KV `evse_grid_cap_paused` | 3 |
| battery_drain | `_paused_by_battery_drain` | `:204` | Yes | list KV `evse_battery_drain_paused` | 2 |
| dp | `_paused_by_dp` | `:216` | **No** (intent-state exclusion) | list KV `evse_dp_paused` | 5 |
| arbitrage | `_paused_by_arbitrage` | `:222` | Yes | list KV `evse_arbitrage_paused` | 4 |
| load_shed | `_paused_by_load_shed` | `:232` | Yes | RAM only | — |
| fill_priority | `_paused_by_fill_priority` | `:305` | Yes | list KV `evse_fill_priority_paused` | 1 |
| proactive_offpeak | `_proactive_offpeak_holds` | `:288` | No (intent-state) | list KV | 8 |
| blind_window | `_paused_by_blind_window` | (blind-window block) | Yes | list KV `evse_blind_window_paused` | — |
| blind_window_liveness_ride | `_blind_window_liveness_ride` | (same) | No (latch) | list KV | — |
| force_charge (scalar) | `_force_charge_until` | `:264` | n/a | scalar KV | — |

Declaration rows: `energy_pool_owners.py:234` (tou), `:245` (excess_solar), `:255` (grid_cap),
`:264` (battery_drain), `:275` (dp), `:286` (arbitrage), `:296` (load_shed), `:307` (fill_priority),
`:317` (proactive_offpeak), `:326` (blind_window), `:336` (liveness_ride).

**Confusable pair — the classifier ladder is NOT the actuation ladder.** The comment at
`energy_pool.py:2622-2626` states the canonical order as
`fill_priority > drain > grid_cap > arbitrage > TOU > excess_solar > charging > idle > off`.
That is the **display/classifier** precedence used by `_classify_evse` (`energy_pool.py:2643-2656`)
to render `energy_status` / `pause_reason_human` on the sensor. It is **not** what decides who
actually gets to actuate. Actuation precedence is emergent — see §6.

`_stronger_peer_holds` (`energy_pool.py:383-412`) is the shared guard that both the TOU ensure-on
path and the excess-solar claim path consult; it returns True if the EVSE is held by any owner with
`peer_holds_member=True`. **`_paused_by_dp` is deliberately excluded** (`energy_pool.py:394-400`
[COMMENT], enforced by `peer_holds_member=False` at `energy_pool_owners.py:279` [LIVE]) because DP is
conditionally yieldable — see §5.

### 2.1 The physical control path — verified

`DEFAULT_EVSE_ENTITIES` (`energy_pool.py:168-183`) hard-codes:

* `garage_a`: `switch` = `switch.garage_a` (`:170`), `power` = `sensor.garage_a_power_minute_average` (`:171`), `span_breaker` = `switch.span_panel_car_charger_breaker` (`:174`)
* `garage_b`: `switch` = `switch.garage_b` (`:177`), `power` = `sensor.garage_b_power_minute_average` (`:178`), `span_breaker` = `switch.span_panel_garage_b_evse_breaker` (`:181`)

Every pause/resume action in `energy_pool.py` targets `config.get("switch", "")` — the **Emporia
switch**, never the SPAN breaker. The card's Q4 correction is **confirmed**. Live: `switch.garage_a`
and `switch.garage_b` both `off` / `Standby` / no vehicle;
`switch.span_panel_garage_a_evse_breaker` is `unavailable` (`restored: true`) but is not in the
control path, so it is an observability gap only.

Note the `garage_a` `span_breaker` value is `switch.span_panel_car_charger_breaker`, **not**
`switch.span_panel_garage_a_evse_breaker`. If any future work reads `span_breaker` for garage_a it
will get a differently-named entity than the one the card investigated.

### 2.2 `self_modulates` — an existing per-EVSE flag whose NAME will collide with this cycle

`_self_modulates_for(evse_id)` (`energy_pool.py:713-724`) reads a per-EVSE config key
`self_modulates` (default False). Its meaning is **"this EVSE has native intelligence, so URA is the
sole authority and skips manual-override detection and re-pauses every tick"**
(`energy_pool.py:714-718` [COMMENT]; consumed live at `energy_pool.py:1873`, `:1886`, `:2181`,
`:2188`, and the plug mirrors at `:3251`, `:3261`, `:3461`, `:3463`; surfaced on the status sensor at
`energy_pool.py:2587-2594`).

This is semantically adjacent to the very Emporia feature the operator disabled. **The key is
defined in code but has no `CONF_*` constant and no config-flow field** — grep across
`custom_components/**.py` finds `self_modulates` only inside `energy_pool.py`, so there is no path
by which an operator can set it today. It is dormant-but-wired. Any new "modulation" naming in this
cycle must not be confused with it. Related parked item: `PLANNING_ev_offpeak_proactive_charging_and_persistence.md:418`
explicitly **DEFERRED** a `self_modulates` opt-out for proactive-on.

---

## 3. MECHANISM 1 — "HC"

**"HC" is not a live identifier anywhere in the codebase.** A grep for `\bHC\b` over
`custom_components/**.py` returns only comments and docstrings; there is no `hc_`-prefixed symbol.
In those comments it consistently means **HVAC Coordinator** — e.g. `hvac.py:513-517`
("HC Pre-Conditioning master enable … lives on HC since pre-conditioning is HC-owned"),
`hvac.py:576-580` ("freeze-protection … HC-owned"), `switch.py:1795`, `switch.py:1951-1954`
("HC coord not ready"), `hvac_predict.py:748`, `config_flow.py:5224-5226`. A second, *distinct*
primitive — the house-state machine (`domain_coordinators/house_state.py`, `HouseState` enum,
`SIGNAL_HOUSE_STATE_CHANGED` at `coordinator.py:142`, `:1499`) — is real live code but is never
abbreviated "HC". Both are reported because the abbreviation is genuinely ambiguous.

### 3.1 How HC participates in energy decisions — one direction only

The coupling is **EC-decides / HC-complies**, via a single dispatched constraint. `hvac.py:600`
[COMMENT] states the rule as "No direct-to-energy reads".

* Producer: `EnergyCoordinator._update_hvac_constraint(period)` — called each cycle at
  `energy.py:6132`, defined `energy.py:6847-6968`. Mode ladder in evaluation order [LIVE]:
  `shed` (`:6876-6881`, requires `peak AND soc < 20 AND load_shedding_enabled AND
  _load_shedding_active_level > 0`) → `coast` (`:6883-6886`, `peak`) → `coast`
  (`:6888-6894`, `mid_peak AND solar_class in ("poor","very_poor") AND not summer_post_peak_midpeak`)
  → `pre_cool` (`:6896-6902`, `off_peak AND soc < 50 AND solar_class in ("excellent","good")`) →
  `pre_heat` (`:6904-6911`) → `normal` (`:6913-6915`). Emitted via
  `async_dispatcher_send(hass, SIGNAL_ENERGY_CONSTRAINT, constraint)` at `energy.py:6937-6952`,
  deduped on `constraint_key` (`:6920-6929`).
* Consumer: HVAC subscribes at `hvac.py:942-947`, handles at `hvac.py:2535-2541`, and consumes the
  mode at `hvac.py:1385-1388`, `:1399`, `:1402`, `:1405-1407`, `:1420`, `:1599-1601`, `:3331`,
  `:3584-3586`, `:686-689`.
* Load-shed reaches HVAC **only** through that constraint — the shed target dispatcher has a bare
  `elif target == "hvac": pass` at `energy.py:7468-7473` [LIVE].
* The only HC→EC read found is preset-override plumbing: `hvac.py:2253` reads
  `manager.coordinators.get("energy")._dynamic_preset_overrides`, gated by
  `self._guest_mode_actuation_enabled` (`hvac.py:2240-2242`).

### 3.2 Can HC veto an EVSE / battery / TOU action?

**No.** No site was found where HVAC state gates an EVSE pause, a battery reserve write, or a TOU
decision. `determine_actions`, `determine_excess_solar_actions`, `determine_fill_priority_actions`,
`determine_battery_drain_actions` and the battery strategy take no HVAC input.

`HouseState` reaches energy at `energy.py:6827-6843` (`_get_house_state()`, reading
`CoordinatorManager.house_state`), whose sole consumer is the dynamic-preset evaluator at
`energy.py:6620` → `energy.py:6711`. That is a comfort/preset path, not an energy-actuation veto.

**Could not determine:** whether an HVAC-side gate on EVSE/battery exists in
`hvac_override.py` / `hvac_covers.py`, which were not read end-to-end.

### 3.3 Relevance to solar-follow — HC is a *competing claimant on the same surplus*

`HVAC-MANUAL-PRESET-CONTRACT-1` (kanban, thread `hvac`, status `planned`) names solar banking and
pre-cool as the other sanctioned consumers of surplus solar. Live config confirms both are on:
`hvac_solar_gain_cover_enabled = True`, `hvac_solar_bank_soc_min = 95`,
`hvac_solar_bank_floor = 74`, `hvac_cover_solar_start_hour = 14`, `hvac_cover_solar_end_hour = 17`,
`energy_precool_enabled = True`.

**Finding — an undocumented threshold coincidence.** `hvac_solar_bank_soc_min = 95` is the *same
number* as `energy_excess_solar_soc = 95`. Both mechanisms therefore arm at the same SOC, on the
same afternoons, against the same surplus, with **no arbitration between them** — HVAC never sees
the EVSE claim and the EVSE path never sees the HVAC one. An EVSE that starts drawing 11.5 kW at
SOC 95 will pull SOC below 95 and thereby disarm solar banking as a side-effect. This is emergent,
not designed. It is not in scope for the solar-follow card, but a controller that *holds* SOC at 95
by construction (the card's Q2 "strict follow") would change HVAC banking behaviour too.

---

## 4. MECHANISM 2 — EVSE TOU

### 4.1 The rate table, and the seasonal fact that changes everything in six weeks

`PEC_TOU_RATES` (`energy_const.py:15-66`), utility = Pedernales Electric Cooperative, "built-in
PEC 2026" (`energy_tou.py:4`, `:43`). Seasons are keyed **by month only** — `get_season` reads
`now.month` (`energy_tou.py:159-163`) and `get_current_period` reads `now.hour`
(`energy_tou.py:165-176`). **There is no weekday/weekend or holiday logic anywhere in
`energy_tou.py`.**

| Season | Months | off_peak hours | mid_peak hours | peak hours |
|---|---|---|---|---|
| summer | 6,7,8,9 | (0,14),(21,24) | (14,16),(20,21) | **(16,20)** |
| shoulder | 3,4,5,10,11 | (0,17),(21,24) | (17,21) | **NONE DEFINED** (`energy_const.py:36-49`) |
| winter | 12,1,2 | (0,5),(9,17),(21,24) | (5,9),(17,21) | **NONE DEFINED** (`energy_const.py:50-64`) |

**Finding, load-bearing for this card.** From **1 October through 28 February**,
`get_current_period()` can never return `"peak"`. Every "never during peak" protection in the EVSE
stack — the excess-solar peak-clear (`energy_pool.py:1354-1374`), the TOU peak/mid-peak pause branch's
peak leg (`energy_pool.py:898`), the fill-priority `tou_period == "peak"` inert clause
(`energy_pool.py:2135`), the HVAC `coast`/`shed` peak modes (`energy.py:6876-6886`) — is **dormant
for five months of the year**. Today (23 Aug) is summer, so peak is live; the card is being scoped
six weeks before that stops being true. A solar-follow controller relying on "peak stops it"
(the card's Q3 answer) would lose that stop from 1 October.

Rate override path: `TOURateEngine.async_from_json_file` (`energy_tou.py:71-82`) loaded once at
`__init__.py:3254-3257` from the hard-coded `DEFAULT_TOU_RATE_FILE`
(`"universal_room_automation/tou_rates.json"`, `energy_const.py:266`).
**`CONF_ENERGY_TOU_RATE_FILE` (`energy_const.py:679`) is DORMANT — grep-verified zero consumers**;
setting it has no effect.

### 4.2 Public API (`energy_tou.py`, class is `TOURateEngine` — a comment at
`energy_pool.py:1269` calls it `EnergyTOUEngine`, which does not exist)

`rate_source` `:150`, `get_season` `:155`, `get_current_period` `:165`, `get_current_rate` `:178`,
`get_export_rate` `:186`, `get_effective_import_rate` `:194`, `get_next_transition` `:199`,
`get_next_period_change_dt` `:247`, `peak_ahead_before_offpeak` `:280-324`,
`check_period_transition` `:326`, `get_next_high_rate_transition` `:351`,
`get_today_high_rate_transitions` `:395`, `get_period_info` `:417`.

`peak_ahead_before_offpeak` walks forward hour-by-hour from the top of the next hour, returns True
on the first `peak`, False on the first `off_peak`, and keeps walking through `mid_peak`
(`energy_tou.py:280-324`). In shoulder/winter it therefore always returns **False**.

### 4.3 TOU → EVSE actuation

Entry: `EVChargerController.determine_actions(tou_period, grid_charge_on=False, coord=None)`
(`energy_pool.py:846-851`), dispatched at `energy.py:6413-6423` **only when `self._ev_tou_enabled`**;
the else-branch runs `release_all_tou()` unconditionally (`energy.py:6433`). The L1 plug mirror is
`energy.py:5940-5952` / `:5958`.

**Peak / mid-peak leg** — `if tou_period in ("peak", "mid_peak"):` (`energy_pool.py:898`):
1. `_proactive_offpeak_holds.discard(evse_id)` unconditionally (`:904`).
2. `if evse_id in self._excess_solar_active: continue` (`:906`) — **excess-solar outranks the TOU
   pause.** Note this is the *mid-peak* protection; the *peak* case is handled separately and more
   strongly by the excess-solar function's own peak-clear.
3. `if force_charge_active: continue` (`:909-914`).
4. `if state["is_on"]:` → `switch.turn_off` + `_paused_by_us.add` (`:919-926`), re-dispatched
   idempotently every tick.

**Off-peak ensure-on leg** — `elif tou_period == "off_peak":` (`energy_pool.py:927`), gates in order:
1. Blind-window guard (`:940-1129`) — fail-safe pause unless `ride_ok` (`:958`) or a per-epoch
   liveness-ride grant (`:988-989`); `will_pause` at `:973-976`; max-defer leg `:1040-1108` with
   kill-switch `CONF_BLIND_WINDOW_MAX_DEFER_MIN <= 0` (`:1050-1051`).
2. Force-charge blind-window drain (`:1168`).
3. **Peer carry-over guard** (`:1180-1196`): `if self._stronger_peer_holds(evse_id) or evse_id in
   self._paused_by_dp:` → drop TOU + proactive claims, `continue`. **This is where DP outranks TOU
   unconditionally — a flat, carrier-state-blind check, unlike the excess-solar yield.**
4. Breaker-safety (`:1208-1227`): `if grid_charge_on:` → claim `_paused_by_arbitrage` with reason
   `"breaker"` and turn OFF. Arbitrage grid-charging beats off-peak ensure-on.
5. Force-charge (`:1235-1237`).
6. Ensure-on (`:1243-1251`) + claim `_proactive_offpeak_holds` / drop `_paused_by_us` (`:1261-1262`).

**Unknown period** — bare `else: continue` (`energy_pool.py:1263-1271`), an explicit safe no-op.

`release_all_tou` (`energy_pool.py:2716-2765`) drains `_paused_by_us` + `_proactive_offpeak_holds`
but defers the `switch.turn_on` when any of six other owners still hold (`:2731-2745`), then
`_proactive_offpeak_holds.clear()` unconditionally (`:2764`).

### 4.4 Fill-priority — TOU-phase-anchored, and the card's Q2 answer is confirmed

`determine_fill_priority_actions` (`energy_pool.py:2051-2284`; plug mirror `:3374-…`). Gates in order:

1. `force_charge_active` (`:2099`).
2. `forecast_healthy = remaining_forecast_kwh >= excess_solar_kwh_threshold` (`:2102-2105`).
3. `forecast_decayed = remaining_forecast_kwh <= (excess_solar_kwh_threshold - safety_margin_kwh)` (`:2109-2114`).
4. **TOU anchoring** (`:2133-2138`) [LIVE]:
   ```python
   off_peak_inert = tou_period == "off_peak" and (is_daylight is not True)
   fill_priority_inert = (
       tou_period == "peak"
       or off_peak_inert
       or (tou_period == "mid_peak" and peak_ahead is False)
   )
   ```
   Inert → release every member and return zero actions (`:2139-2148`). Tri-state matters:
   `peak_ahead is None` (no TOU engine) is NOT inert; `is_daylight is None` keeps off_peak inert.
5. `pause_conditions_global = soc < soc_threshold and forecast_healthy` (`:2150-2155`).
6. Per-EVSE: force-charge bypass (`:2162-2170`); manual-override detection needing
   `observed_off and grace_expired` (`:2188-2209`); **`_excess_solar_active` deferral (`:2214-2219`)**.
7. Pause (`:2221-2241`) / resume with six-owner peer check (`:2242-2282`).

Live knobs: `energy_fill_priority_soc = 80` (rung 3, `FillPrioritySOCNumber` at `number.py:1540`;
`CONF_ENERGY_FILL_PRIORITY_SOC` at `energy_const.py:872`, default 80 at `energy_const.py:870`).
`DEFAULT_FILL_PRIORITY_SAFETY_MARGIN_KWH = 1.0` (`energy_const.py:871`) is **rung 1 only — no CONF
key, no entity.**

The card's Q2 statement of fill-priority behaviour (peak→release, off_peak→release,
mid_peak+peak_ahead→HOLD, mid_peak+no-peak-ahead→release) is **verified correct** against
`energy_pool.py:2133-2138` — with the refinement that off_peak is inert **only when not daylight**
(`is_daylight is not True`), shipped as fill-priority daylight restoration in v5.28.0.

**Consequence in shoulder/winter:** `peak_ahead_before_offpeak` returns False (no peak exists), so
`mid_peak and peak_ahead is False` → **fill-priority is inert in every period from 1 October to
28 February except daylight off-peak.** Combined with §4.1, the whole battery-first pre-peak fill
window disappears for five months.

---

## 5. MECHANISM 3 — EVSE SOLAR (the excess-solar claim path)

`EVChargerController.determine_excess_solar_actions(soc, remaining_forecast_kwh, tou_period,
soc_threshold=95, kwh_threshold=5.0, dp_carrier_state=None, coord=None)` —
`energy_pool.py:1318-1701`.

### 5.1 Caller and inputs

`energy.py:5733-5769`, inside `if not self._observation_mode:` and gated by
`if self._excess_solar_enabled:` (`energy.py:5734`). Live: `energy_excess_solar_enabled = True`.

| Arg | Source | Live value / entity |
|---|---|---|
| `soc` | `self._battery.battery_soc` (`energy.py:5735`) | Envoy `sensor.envoy_482543015950_battery` (derived, `energy_const.py:963`) |
| `remaining_forecast_kwh` | `self._battery.solcast_remaining` (`energy.py:5736`; property `energy_battery.py:1665-1670`) | `sensor.solcast_pv_forecast_forecast_remaining_today` (SET) |
| `tou_period` | `period` from `self._tou.get_current_period()` | §4 |
| `soc_threshold` | `excess_solar_soc_tick` snapshot (`energy.py:5705`, passed `:5759`) | **95** (`energy_excess_solar_soc`) |
| `kwh_threshold` | `self._excess_solar_kwh` (`energy.py:5760`) | **5.0** |
| `dp_carrier_state` | `self._dp_carrier.state.value`, threaded as a plain string (`energy.py:5747-5751`) | §6 |
| `coord` | `self._ev.attach_coord(self)` (`energy.py:5754`), else `getattr(self, "_energy_coord")` (`energy_pool.py:1381-1382`) | — |

### 5.2 Gates in order

1. **Peak clear** — `if tou_period == "peak":` (`:1355`). Turns OFF every member of
   `_excess_solar_active` that is on (`:1362-1367`), drops the claim (`:1369`) and the proactive
   off-peak hold (`:1373`), returns. **Never runs in shoulder/winter (§4.1).**
2. **Blind-window guard** (`:1381-1572`). `engaged = self._blind_window_guard_engaged(coord)`
   (`:1384`), `max_defer_exceeded` (`:1385`). Raw-false drains stale `_paused_by_blind_window`
   (`:1393-1396`). If engaged and not max-defer:
   * `exp = coord.mains_export_active()` (`:1422`) — **the ONLY export measurement on this path.**
   * `envelope_ride_ok = soc_envelope().lower >= _ev_battery_drain_soc` (`:1432-1449`).
   * When `exp is None` (entity unwired *or* unavailable), fall back to
     `coord.solar_production_w_envelope()`; admit only when tier ∈ `("fresh","lkg_bounded")` and the
     **stamped** LKG value ≥ `SOLAR_ENVELOPE_ADMIT_FLOOR_W` (`:1477-1510`).
   * `continue_permission = ((exp is True) or solar_env_admits) and envelope_ride_ok` (`:1511-1513`).
     True → already-active EVSEs continue, **new claims refused**, return (`:1514-1530`).
   * Else DROP leg (`:1531-1572`): turn off, drop claim, add `_paused_by_blind_window` — but skip
     any EVSE holding a `_blind_window_liveness_ride` grant (`:1541-1547`).
3. **The actual trigger** (`:1574-1579`) [LIVE]:
   ```python
   conditions_met = (
       soc is not None and soc >= soc_threshold
       and remaining_forecast_kwh is not None
       and remaining_forecast_kwh >= kwh_threshold
   )
   ```
   **No export, net-power, or solar-production reading is consulted here.** See §1.1.
4. **Claim loop** when met (`:1588-1684`), per EVSE:
   * skip if no `switch` (`:1590`), skip if already claimed (`:1592`);
   * `if self._stronger_peer_holds(evse_id): continue` (`:1599-1608`) — the five/six peer owners;
   * DP yield predicate (`:1621-1631`), see §6;
   * claim from TOU by discarding `_paused_by_us` (`:1633-1635`);
   * atomic DP handoff: discard `_paused_by_dp` + release the `"dp"` dispatch owner (`:1645-1648`);
   * `switch.turn_on` + `_excess_solar_active.add` (`:1650-1656`), or claim-only if already on
     (`:1669-1684`).
5. **Release** when not met (`:1685-1699`) — turn off + discard, for every claimed EVSE.
   **No hysteresis, no minimum on-time, no deadband on either input.** See §1.2.

Post-call bookkeeping: `_post_excess_solar_bookkeeping(_pre_dp_set)` (`energy.py:5769`, defined
`energy.py:5150-5181`) — persists if the yield mutated `_paused_by_dp`, and collapses the DP
reserve floor (`_dp_decision_soc = None` + cancel must-start timer) if the yield drained the DP set.

### 5.3 What `_excess_solar_active` means, and restart behaviour

Membership means **"URA turned this EVSE on (or claimed it) for excess-solar reasons and owns the
turn-off"**. It is an *intent* set, not a derived one.

* Persisted per-EVSE as a bool via `db.save_evse_state(... excess_solar_active=...)`
  (`energy.py:1830-1841`).
* Restored unconditionally at `energy.py:1365-1366`.
* Torn-restart reconciliation `_reconcile_dp_excess_on_restore` (`energy.py:5183-5225`):
  double membership in both `_paused_by_dp` and `_excess_solar_active` → **excess wins**, DP
  membership + `"dp"` owner dropped (`:5213-5222`); DP-only orphan with carrier HOLD_ONLY and switch
  physically ON → command OFF to honour the DP intent.
* Declared `persistence_kind="per_evse_bool"`, `peer_holds_member=False`, `classifier_priority=7`
  at `energy_pool_owners.py:245-251`.

**Restart hazard relevant to the card:** the amp value the card proposes to write lives on an
*external* entity, not in URA state. If URA restarts mid-session, `_excess_solar_active` is restored
but nothing would restore the pre-session amp value. The card names this ("A THROTTLED CHARGER LEFT
BEHIND"); §1 row 12 confirms nothing exists for it today. `RESTART-SAFETY-DOCTRINE-1` (kanban,
`platform`, shipped_organic) is the governing doctrine card.

---

## 6. MECHANISM 4 — EVSE DP (drain precedence)

### 6.1 Gate ladder — `evaluate_dp_transition()`, `energy_drain_precedence.py:609-735`

Pure function over `TransitionInputs` (`:501-555`). Every gate is a **hard stop** returning
`_no_fit(...)` (`:594-606`). The docstring ladder at `:613-621` is [COMMENT]; the table below is the
executable order and includes one gate the docstring omits.

| # | Gate | Condition | Line | Reads | Reason constant |
|---|---|---|---|---|---|
| 1 | blind hold (INV-DP4) | `if inputs.is_blind_hold:` | `:629` | `(not envoy_available) and battery_soc is None` (`energy.py:4432`) | `DP_REASON_BLIND_HOLD` `:490` |
| 2 | kill switch | `if not inputs.dp_enabled:` | `:633` | **effectively unreachable** — both construction sites hard-code `dp_enabled=True` (`energy.py:4449`, `:4264`); the real switch is `is_dp_enabled(self)` at `energy.py:4360`/`:4417` | `DP_REASON_KILL_SWITCH_OFF` `:489` |
| 3 | force-charge yield | `if inputs.force_charge_active:` | `:639` | `_force_charge_until > now` (`energy.py:4450-4453`) | `DP_REASON_FORCE_CHARGE_ACTIVE` `:491` |
| 4 | no charging EVSE | `if not inputs.any_evse_charging:` | `:644` | `_is_any_evse_charging()` (`energy.py:3557-3563`) | `DP_REASON_NO_CHARGING_EVSE` `:493` |
| 5 | missing SOC | `if inputs.soc is None:` | `:647` | **house** battery SOC (`energy.py:4454`) | `DP_REASON_MISSING_SOC` `:494` |
| 6 | **L1-only** | `if inputs.charger_rate_kw <= inputs.l1_rate_threshold_kw:` | **`:652`** | `charger_rate_kw = (ev_load_w or 0)/1000` (`energy.py:4457`); threshold `DP_L1_RATE_THRESHOLD_KW = 3.0` (`energy_const.py:1359`) | `DP_REASON_L1_ONLY` `:492` |
| 7 | already below target | `if int(inputs.soc) <= int(inputs.drain_target_soc):` | `:656` | §6.3 | `DP_REASON_ALREADY_BELOW_TARGET` `:496` |
| 7.5 | missing inputs (divide guard; **not in the docstring**) | `if inputs.house_load_kw <= 0.0 or inputs.charger_rate_kw <= 0.0 or inputs.needed_kwh <= 0.0:` | `:660` | `_dp_house_load_kw()` (`energy.py:4151-4193`), `_dp_needed_kwh_plugged()` (`energy.py:4099-4149`) | `DP_REASON_MISSING_INPUTS` `:495` |
| 8 | fit arithmetic | `fits = (computed_start_dt <= must_start_by_dt and total_hours <= hours_until_end_of_night)` | `:709-712` | below | `DP_REASON_DOES_NOT_FIT` `:497` / `DP_REASON_FITS` `:498` |

Gate-8 math [LIVE]: `drain_soc_pp = soc - drain_target_soc` (`:663`);
`drain_energy_kwh = drain_soc_pp * DP_CAPACITY_KWH_PER_SOC_PP` (0.40, `energy_const.py:1367`) (`:664`);
`drain_hours = drain_energy_kwh / house_load_kw` (`:665`);
`charge_hours = needed_kwh / charger_rate_kw` (`:666`);
`computed_start_dt = now + drain_hours` (`:683`);
end-of-night from `DP_NIGHT_WINDOW_END_HOUR = 6` (`energy_const.py:1385`) (`:692-698`);
`total_hours = drain + charge + margin` (`:708`).

Two further reasons are **string literals emitted by the tick driver, not `DP_REASON_*` constants**:
`"waiting_eval_delay"` (`:823`) and `"already_transitioned"` (`:869`).

### 6.2 DPState machine

States (`:60-77`): `HOLD_ONLY`, `HOLD_PRE_EVAL`, `EVAL_TRANSITION`, `TRANSITIONED`,
`MUST_START_FORCED`. Legal-transition table `_LEGAL_TRANSITIONS` `:111-128`, enforced by
`is_legal_transition` `:304-306` / `try_transition` `:309-353` (illegal → WARNING + False `:326-331`;
self-loop no-op `:333-335`; stamps `hold_started_at` `:343-344`, `transitioned_at` `:345-346`, and
clears all three on entry to HOLD_ONLY `:347-352`).

Transitions [LIVE]: collapse to HOLD_ONLY on kill-switch/no-charging (`:786-787`, TRANSITIONED
deliberately excluded); HOLD_ONLY→HOLD_PRE_EVAL `:801-805`; HOLD_PRE_EVAL→EVAL_TRANSITION on
`elapsed_min >= eval_delay_min` `:818-826`; EVAL_TRANSITION→TRANSITIONED `:852-857` (stamps
`must_start_by_dt` `:854`) or →HOLD_ONLY `:858-861`; TRANSITIONED→MUST_START_FORCED only in the
point-in-time callback `energy.py:5338-5343` armed at `energy.py:5282-5328`;
MUST_START_FORCED→HOLD_ONLY `energy.py:5350-5354`; TRANSITIONED→HOLD_ONLY revert
`energy.py:4552-4573`; kill-switch force-set bypassing `try_transition` at `energy.py:4375`.

Persistence: `DP_KV_KEY = "drain_precedence_state_v1"` (`energy_const.py:1390`), written via
`serialize_for_kv` (`energy.py:2027-2036`; `:441-443`), restored `energy.py:1505-1519` →
`restore_from_blob` `:381-438`. **TRANSITIONED / MUST_START_FORCED are never restored** — coerced to
a fresh HOLD_ONLY at `:430-436`. `shadow_*` fields are RAM-only (absent from `to_dict` `:167-181`).
`DP_TRANSITION_MAX_DURATION_H` (`energy_const.py:1378`) is imported at `:51` and **never used**.

### 6.3 `drain_target_soc` — one derivation, and it is the static knob

Both construction sites set `drain_target_soc=int(self._ev_battery_drain_soc)`
(`energy.py:4456` real tick, `energy.py:4271` shadow). `_ev_battery_drain_soc` is seeded from
`CONF_ENERGY_EV_BATTERY_DRAIN_SOC` (`energy_const.py:858`, default
`DEFAULT_EV_BATTERY_DRAIN_SOC_THRESHOLD = 50` at `energy_const.py:857`) at `energy.py:440-442`,
runtime-mutable via `set_ev_battery_drain_soc` (`energy.py:8732-8739`) behind
`EVBatteryDrainSOCNumber` (`number.py:1417`, rung 3). **Live value 80.**

The forecast-based target is a **different mechanism that does not feed DP**:
`current_offpeak_drain_target()` (`energy_battery.py:1726-1747`) selects from `offpeak_drain_targets`
(`energy.py:200-205`; live `energy_offpeak_drain_excellent = 10 / good 15 / moderate 20 / poor 30`),
and is consumed at `energy_battery.py:296`, `:1773`, `:6043` and via `compose_release_floor`
(`energy.py:5837`) — **never by any `TransitionInputs`.**

**Verdict on the 2026-08-20 defect claim: TRUE of today's code.** DP is wired only to the static
knob. Whether that is a defect or intended config is a **config question, not a code question** —
`AUDIT_dp_live_behavior.md:56` files it as an open operator question, and `:33`/`:50` note it is the
structural reason TRANSITIONED fired 0 times in 21 nights. No commented-out or dead wiring to the
forecast target exists in the DP module or at either construction site.

### 6.4 INV-YIELD-1 / INV-YIELD-2

Verbatim, `PLANNING_dp_sticky_yields_to_excess_solar.md:94-107`:

> **INV-YIELD-1 (permissive, opportunity):** An EVSE whose DP pause is **deferred-reversion-only** —
> i.e. `_dp_carrier.state == HOLD_ONLY` AND `evse_id in _paused_by_dp` — is claimable by excess-solar
> whenever excess conditions hold (`SOC >= excess_solar_soc AND remaining_forecast >=
> excess_solar_kwh_threshold AND tou_period != "peak"`). No config combination may prevent the claim.
>
> **INV-YIELD-2 (restrictive, safety, LOAD-BEARING):** An EVSE paused by an **ACTIVE** DP transition —
> i.e. `_dp_carrier.state IN {TRANSITIONED, MUST_START_FORCED}` — is NEVER released by excess-solar,
> under any config, TOU period, SOC value, or forecast.

**Both are enforced by one predicate** [LIVE], `energy_pool.py:1621-1624`:
```python
_dp_yield_ok = (
    evse_id in self._paused_by_dp
    and dp_carrier_state == "hold_only"
)
```
* INV-YIELD-2 refusal: `energy_pool.py:1625-1631`. The predicate is **stricter than the doc** —
  `HOLD_PRE_EVAL` and `EVAL_TRANSITION` also refuse, and `dp_carrier_state is None` refuses
  (docstring `:1348-1350`).
* INV-YIELD-1 handoff: `energy_pool.py:1645-1649` then `.add` at `:1655` / `:1673` / `:1679`.
* Peak refusal clause: `energy_pool.py:1354-1356`. Stronger-peer clause: `:1598-1607`.
* **Not enforced anywhere else.** The off-peak ensure-on carry-over at `energy_pool.py:1189` is a
  flat, carrier-blind `or evse_id in self._paused_by_dp` — widening it to the yield semantics is
  **explicitly PARKED** at `PLANNING_dp_sticky_yields_to_excess_solar.md:461-465`, with evidence
  trigger "a measured occurrence of an EVSE stranded in `_paused_by_dp` at off_peak boundary".

### 6.5 `evse_battery_hold`

A **separate, older** mechanism from DP: "any EVSE is charging ⇒ pin the battery reserve to the SOC
captured at hold entry, so the house battery does not discharge into the car."

* Not a config key — grep finds no `CONF_*EVSE_BATTERY_HOLD*`. Runtime flag
  `self._evse_battery_hold_active` (`energy.py:315`) + captured `self._evse_hold_soc` (`energy.py:316`).
* Set/cleared at two sites: `energy.py:5604-5613` (decision cycle) and `energy.py:6200-6208`
  (TOU-transition `_evaluate_battery`). Trigger is `self._is_any_evse_charging()` (`energy.py:5603`).
* Applier `_apply_evse_battery_hold` (`energy.py:4575-…`); the emitted reserve is
  `max(existing, hold_reserve, self._dp_decision_soc)` at `energy.py:4733-4742` (update-in-place)
  and `energy.py:4829-4833` (append leg). **This max() is where DP's floor composes in (INV-DP3).**
* Consumed: `sensor.py:8480-8481`, `sensor.py:8555-8559`; `energy_write_verify.py:1440`, `:1557`.
* **Known open scope question, not resolved:** because `hold_reserve` is the *live SOC*, a lower DP
  target is swallowed by the `max()` — `KANBAN.md:506` files this as
  `BIGGEST_SCOPE_QUESTION_HOLD_DEMOTION`, **operator decision needed**, and the parked cycle is
  `project_ev_drain_precedence_cycle` (memory).

### 6.6 Everything DP reads about the charger

1. `charger_rate_kw` (`:523`) ← `current_charging_load_w()/1000` (`energy.py:4457`, `:5570`;
   `energy_pool.py:2286-2312`), which sums live `state["power"]` over EVSEs with `charging=True`.
   Unit W→kW, sign positive. Underlying entity `sensor.garage_{a,b}_power_minute_average`,
   W/kW-normalized at `energy_pool.py:679-682`.
2. `any_evse_charging` (`energy.py:4458`) ← `charging = power > EVSE_CHARGING_POWER_THRESHOLD`
   (100 W, `energy_const.py:826`) at `energy_pool.py:692`, with a switch-`status` fallback that
   substitutes `EVSE_ESTIMATED_POWER_W = 7600` (`energy_const.py:827`) at `energy_pool.py:694-698`.
3. `house_load_kw` (`energy.py:4461`) ← `_dp_house_load_kw(ev_load_w)` (`energy.py:4151-4193`):
   SPAN mains **minus `ev_load_w`** (`:4171`), vs the R1 model, `max_span_r1` takes the max
   (`:4191-4193`). Live `energy_dp_house_load_source = 'max_span_r1'`.
4. `needed_kwh` (`energy.py:4460`) ← `_dp_needed_kwh_plugged()` (`energy.py:4099-4149`), summing the
   per-garage knobs only for EVSEs in `_paused_by_dp` **or** currently `charging` (`:4139-4145`).
   Live `energy_dp_needed_kwh_garage_a = energy_dp_needed_kwh_garage_b = 25.0`.
5. Pause targets on transition: `energy.py:4515-4518`, rescan `:4532-4536`, by `charging`.
6. `state["is_on"]`: `energy.py:4929` (pause), `:5032` (revert), `:5117` (must-start release).

**DP reads no current/amperage entity anywhere.** Rate is inferred solely from instantaneous power.

### 6.7 Shared state DP mutates

`_paused_by_dp` — `.add` `energy.py:4922` (+ `_claim_pause_dispatch_owner("dp")` `:4923`);
`.discard` `energy.py:5028`, `:5033`, `:5089`, `:5116`, `:5214`, **and by excess-solar at
`energy_pool.py:1647`**. Read cross-mechanism at `energy_pool.py:1189`, `:1622`, `:1625`;
`energy.py:1544`, `:1559`, `:4140`, `:4362`, `:4394`, `:4535`, `:4562`, `:5050`, `:5147`, `:5173`,
`:5175`, `:5211`.

`_dp_decision_soc` (the DP reserve floor, `energy.py:417`) — written `energy.py:4953`; cleared
`:5051`, `:5148`, `:5176`; consumed by `_apply_evse_battery_hold` at `energy.py:4733`, `:4829-4832`.
**DP therefore mutates the battery-reserve surface shared with inclement, arbitrage and attain.**

DP also issues **direct HA service calls that bypass the coordinator action queue**:
`switch.turn_off` `energy.py:4931-4936`; `switch.turn_on` `energy.py:5036-5042`, `:5136-5142`
(rationale at `energy.py:4926-4929` [COMMENT]).
