# EXPLORE: solar-led daytime EV charging in the EC

Card: `EC-EV-DAYTIME-SOLAR-LED-1` (investigating). Read-only exploration, 2026-11-12. No build, no board edit.
Operator: "Daytime EV charging should be solar-led ... Explore what this could mean for EC."

## Institutional context verified

- **Docs read:** `docs/Coordinator/ENERGY_COORDINATOR_MANUAL.md` (owner precedence table §2.5, l.150-210; §5.5/5.5a
  EV SOC jurisdiction, l.664-735; onset funnel, l.781-820), `AUDIT_ev_rung1_oscillation_fix_options.md` (full),
  `AUDIT_excess_solar_and_evse_prior_art.md` (section map + §4, §7 matrix rows), `PLANNING_evse_solar_follow_amps.md`
  (scope + §1). The other listed plans (solar-idle-dereserve, offpeak-fill-priority-release, onset v1/v2/v3,
  drain-precedence) are summarised by the manual's owner table and onset section, which cite them as shipped; they
  were not re-read in full.
- **Live knobs (HA REST, 2026-11-12):** `evse_solar_aware_charging` on, `ev_tou_management` on, `grid_arbitrage` on,
  `battery_aware_ev_charging` on, `ev_charge_onset_overnight` on (onset 01:00), `fill_priority_soc` 80,
  `resume_ev_at_battery_soc` 95, `ev_battery_drain_soc` 80, `excess_solar_confirm` 3 min, `peak_buffer_target` 90,
  `arbitrage_charge_lead_time` 150 min, drain poor/very_poor 30. Both garage current limits at 48 A.
- **No new symbol proposed.** Every shape below is either a knob turn or a change to an existing owner.

## 1. Who owns the EV today

### Tariff (energy_const.py:15-70, import = export in every period)

| Season (months) | Off-peak 4.35c | Mid-peak | Peak |
|---|---|---|---|
| Summer (6-9) | 00-14, 21-24 | 14-16, 20-21 at 9.32c | 16-20 at 16.18c |
| Shoulder (3-5, 10-11) | 00-17, 21-24 | 17-21 at 8.64c | none |
| Winter (12-2) | 00-05, 09-17, 21-24 | 05-09, 17-21 at 8.64c | none |

Every daylight hour in shoulder and winter except 17:00+ is off-peak at the same price as overnight. Export earns the
same 4.35c. **On this tariff a kWh of solar put into the car is worth exactly a kWh of off-peak grid put into the
car, at any hour.** Everything below follows from that.

### Owners (one switch per EVSE; precedence is emergent, manual §2.5)

| Owner | Where | Acts when | Effect on EV |
|---|---|---|---|
| TOU pause / off-peak ensure-on | `EVChargerController.determine_actions`, `energy_pool.py:1319`; ensure-on block ~`:1700-1775`; called `energy.py:8299` (if `ev_tou_management`) | every tick | mid/peak: OFF. Off-peak (day or night): idempotent ON, claim `_proactive_offpeak_holds` |
| Breaker pause (grid-charge) | same function, branch 2a ~`:1700-1712`; pre-decision dispatch via `determine_arbitrage_actions` `energy.py:8204` | battery grid-charging (arbitrage CHARGE, attain) | OFF, label `breaker` |
| Onset funnel | `_evaluate_onset_gate` `energy_pool.py:115`, `_charge_on_or_defer` `:961` | hold window ending at 01:00 (overnight only) | defers ensure-on; inert in daylight |
| Arbitrage rung-1 redirect | `_classify_attain_rung` `energy_battery.py:4176-4472`; pause reason `energy.py:8185-8195`; actions `energy_pool.py:3041` (`energy.py:8324`) | off-peak, poor day, SOC < 90, daylight, EV drawing | OFF, label `redirect` (the 11-08 flip-flop; fix D) |
| Excess-solar claim (C2) | `determine_excess_solar_actions` `energy_pool.py:1832`; called `energy.py:7435` (if `evse_solar_aware_charging`) | SOC ≥ 95 and remaining forecast ≥ 5 kWh, not peak | ON (overrides TOU pause), bypasses onset |
| Solar-follow amps | `SolarFollowController` `energy_pool.py:4902`; gate `:5270` | only inside an active excess-solar session | 6-48 A tracking export; restores limit after |
| Fill priority | `determine_fill_priority_actions` `energy_pool.py:2697`; called `energy.py:7618` | daylight off-peak or pre-peak mid-peak, SOC < 80, forecast ≥ 5 kWh; inert at night/peak | OFF until SOC 80 (re-pause below 77) |
| Battery-drain guard | `determine_battery_drain_actions` `energy_pool.py:2307`; `energy.py:7553` | battery out of capacity | OFF |
| Grid-import cap | `determine_grid_cap_actions` `energy_pool.py:2230`; `energy.py:7454` | import over cap | OFF |
| Drain precedence (DP) | `energy_drain_precedence.py:609-735`; `energy.py _apply_dp_transition` | overnight drain window, must-start-by 03:00 | OFF / forced start |

### Who wins, by time of day (manual §5.5a, re-checked against the code above)

| Window | Shoulder / winter | Summer |
|---|---|---|
| Night off-peak | Ensure-on after the onset hold; DP may hold/force. Cars fill here. | same |
| Daylight off-peak, SOC < 80, good forecast | **Fill priority holds** (battery first) | same, 07-14 only |
| Daylight off-peak, SOC < 80, poor forecast | **Ensure-on charges from grid**; arbitrage may breaker-pause in CHARGE; rung-1 may flap (11-08) | same |
| Daylight off-peak, SOC 80-95 | **Ensure-on charges from grid** (plain TOU, nobody solar-aware) | same |
| SOC ≥ 95, forecast ≥ 5 kWh | Excess-solar ON + solar-follow amps | same, also into mid-peak 14-16 |
| Mid/peak | OFF (TOU) unless excess-solar | OFF except excess-solar in mid-peak |

So "solar-led" already exists in two pieces: fill priority (battery first, good days, SOC < 80) and excess-solar plus
solar-follow amps (car gets surplus once the battery is full). The plain-grid daytime gaps are the **80-95 band** and
**poor-forecast days**.

## 2. Measured: what daytime EV charging actually happens

Probe: HA recorder, 1-min integration of `sensor.span_panel_garage_{a,b}_evse_power` against Envoy net power,
production and battery charge. Retention only reaches 2026-11-05, so this is 7 days of shoulder, not 14.
"Day" = 07-17 CST.

| Band | EV kWh | of which grid | of which solar | Export kWh | Battery charge kWh |
|---|---|---|---|---|---|
| Day 07-17 | 14.4 | 12.9 | 1.5 | 37.1 | 249.9 |
| Eve 17-21 | 4.5 | 0.9 | 3.6 (battery-backed) | 0.7 | 0 |
| Night | 38.6 | 35.2 | 3.5 | 0.4 | 2.8 |

- Daytime EV energy outside 11-08 is about 0.3-0.5 kWh/day, which is idle/standby draw on the SPAN circuit, not a
  session. **The only real daytime session in the week was 11-08** (11.8 kWh, 11.2 from grid): a poor day with 16 kWh
  of PV, zero export, the rung-1 flip-flop day.
- Export happened on the good days (11-05 17.7 kWh, 11-12 8.8 kWh), when no car was charging by day.
- The cars fill overnight (38.6 kWh in the week).

On 11-08 solar never exceeded the non-EV house load (the rung-1 audit table shows 2.4-3.5 kW import with the cars
paused). There was no solar to lead with. A solar-led rule would have deferred those 11.2 kWh to the night at the
same 4.35c.

## 3. What "solar-led daytime" could mean

### Shape 1: battery-first band widened by knob (config only)

Raise `fill_priority_soc` toward `resume_ev_at_battery_soc` (e.g. 90-94, must stay ≤ 95; the ordering is now
validated, `energy_const.py:2048-2054`). On good-forecast days the car then waits in daylight until the battery is
nearly full, and excess-solar plus solar-follow take over at 95. Reuses fill priority, its hysteresis (3 points), its
NM trip, excess-solar and solar-follow. Changes nothing on poor days (fill priority is forecast-gated) or at night.

- Cost/benefit: tariff value 0 in every season (symmetric 4.35c). Real value is only if the battery would otherwise
  be short at the evening boundary (shoulder/winter 17:00 mid-peak 8.64c, summer 16:00 peak 16.18c), i.e. at most
  the battery top-up gap × the price spread: about 6 kWh × 4.3c = 26c/day shoulder, 6 kWh × 11.8c = 71c/day summer,
  on days when the car is plugged in by day (one in seven measured).
- Comfort risk: a car plugged in midday on a good day charges later in the afternoon. The pre-peak mid-peak hold and
  the 16:00/17:00 TOU pause can leave it uncharged until 21:00. Low for overnight-charging habits, real for a midday
  top-up before an evening trip.
- Fix D interaction: none; fill priority is a different owner and rung 1 only acts on poor days.

### Shape 2: daylight off-peak is solar-only unless the car needs it

Add a daylight hold to ensure-on: in `off_peak` and `is_daylight`, do not ensure-on; let excess-solar/solar-follow
charge the car, and fall back to grid only after a deadline or under a departure need. This is a new owner (or a new
branch in ensure-on, the highest-traffic turn-on site, funnel P0-#1) plus a "need" input that does not exist: URA has
no car SOC or departure time today (only `dp_needed_kwh_garage_{a,b}`, a DP sizing knob).

- Reuses: `_daylight_bounds`, the onset funnel pattern (`_charge_on_or_defer` + must-start-by) as the deadline model.
- Cost/benefit: tariff value 0 (the deferred kWh are bought at night for the same price). On 11-08 it would have
  moved 11.2 kWh from day to night and saved nothing. Its one real effect, keeping the car off while arbitrage is
  deciding, is what fix D already addresses.
- Risk: a new standing claim over about 8-10 h/day in shoulder/winter that every release path (arbitrage release,
  FP resume, DP, drain-release, grid-cap resume) must defer to. That is the peer-list ripple the rung-1 audit priced
  for shape A, and the precedence table is the most-reviewed surface in the EC. Tier 3.
- Comfort risk: highest of the four. A car plugged in on a cloudy day gets nothing until the deadline.

### Shape 3: export-led claim (start excess-solar below 95 when export is measured)

Let excess-solar start a session on measured export (≥ 6 A × 240 V ≈ 1.4 kW) instead of SOC ≥ 95, with
solar-follow sizing it. This is session start/stop semantics, carded as `EVSE-SOLAR-STOP-CONDITIONS-1`, whose founding
problem is a stop/restart oscillator that three plan reviews found. It also competes with the battery for the same
surplus below 95, which is exactly what fill priority prevents. Value is zero on this tariff because exported kWh
earn what overnight kWh cost.

### Shape 4: season-gated

Apply shape 1 or 2 only in summer, when the battery must be full for the 16-20 peak. The tariff makes summer the only
season where a stolen solar kWh can cost more than 4.35c, and fill priority already holds the car on summer mornings
below 80. Season gating adds a second time axis to a state machine for a margin that shape 1's knob already reaches.

## 4. Verdict

**Config change at most. No new machinery.**

Marginal-benefit decomposition:

1. **Simplest version captures all of the available value.** Existing owners already do battery-first on good days
   and solar-to-car once the battery is full. The tariff is symmetric, so "solar vs grid for the car" is worth zero
   in every season. The only non-zero value is battery fullness at the evening boundary, and shape 1 (a knob) covers
   that.
2. **The measured problem is not a policy gap.** The one daytime grid session in 7 days (11-08) had no solar surplus
   to lead with. Its visible harm, the pause/resume flip-flop, is fix D's job. With fix D shipped, 11-08 becomes
   "cars charged from grid at 4.35c and arbitrage paused them at 14:30 for the breaker", which costs the same as
   charging them overnight.
3. **Shapes 2-4 add risky ingredients for zero tariff margin:** a new standing owner over a wide window (2), session
   semantics with a known oscillator (3), a second time axis (4). Their containment cost (Tier 3, 2 plan reviews,
   4 code reviews) buys nothing measurable.

**Recommendation**

- Ship fix D as planned (independent).
- Offer the operator shape 1 as a knob turn only if they want stronger battery-first on good days:
  `number.ura_energy_coordinator_fill_priority_soc` 80 → 90. Trade-off: a midday-plugged car may not charge until
  21:00 on good days. Otherwise leave it at 80.
- Close this card as **no build** and park shapes 2-4 with these revival triggers:
  - the tariff becomes asymmetric (export credit below off-peak import, e.g. a net-billing change). Then solar-led
    charging has real value and shape 3 becomes the right design;
  - URA gains a car SOC / departure input, which makes shape 2's "need" test possible;
  - a recorder probe shows ≥ 3 days/month where daytime EV grid kWh and same-day export are both above 5 kWh (the
    car pulled grid while solar left the house).

**Tier:** knob turn = no tier (operator action). Any of shapes 2-4 = Tier 3.

## 5. Open questions for the operator

1. Is "solar-led" about money, or about using your own solar (self-consumption as a goal)? On this tariff the money
   is zero. If it is a preference, shape 1 is the cheap way to lean that way.
2. Which car charges in daylight, and does it ever need a midday top-up before an evening trip? That decides whether
   shape 1 at 90 is safe.
3. Is the export credit really 4.35c in every period (the `energy_const.py:12` comment says symmetric)? If the bill
   shows a lower export credit, every number above changes.
4. Should the excess-solar 95 % start stay as is? Lowering `resume_ev_at_battery_soc` gives the car surplus earlier at
   the cost of battery top-off. It is the mirror knob of shape 1.

Evidence limits: 7 days of recorder history (shoulder only); no summer data in range. Summer figures above are
tariff arithmetic, not measured.
