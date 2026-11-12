# AUDIT: EV rung-1 / WAIT oscillation, fix options

Card: `EV-ARBITRAGE-RUNG1-WAIT-OSCILLATION-1` (Tier 3). Read-only analysis, 2026-11-12. No build.
Operator: "We need to fix regardless. It's just figuring out the right fix."

Sources read: the card in full (incl. `merged_from_EC_RUNG1_WAIT_EV_PINGPONG_1`, `trigger_check_2026_10_12_overnight`,
`trigger_fired_2026_11_09_overnight`; there is **no `operator_decision_2026_11_12` field on the card yet**),
`docs/planning/DESIGN_ec_degraded_data_policy.md` §9, `docs/Coordinator/ENERGY_COORDINATOR_MANUAL.md` (rung/WAIT rows,
l.74-96, 399, 769), `energy_battery.py` `_classify_attain_rung` / `_gate_is_open` / `_effective_import_kw`,
`energy.py` pause-reason derivation + post-decision dispatch, `energy_pool.py` `determine_arbitrage_actions` +
`current_charging_load_w`. There is no separate EC "state of play" doc under `docs/Coordinator/`; the manual is the
ground-truth doc.

Evidence: HA REST recorder (`sensor.ura_energy_coordinator_battery_strategy` with attribute history,
`switch.garage_a/b`), URA DB `ura_activity_log` and `decision_log` (`dp_eval`). **Retention limit:** the recorder
and the `charger_on/off` activity rows only go back to 2026-11-05. Episodes before that (09-28, 10-01, 10-09, 10-11)
come from the card's earlier measurements and the sparser `decision_log.dp_eval` rows (kept since 02-28).

---

## Mechanism (code, file:line)

The loop is **not** what the card's working theory says ("the projection includes the paused EV"). The exit-to-rung-0
leg already uses a counterfactual with the EV added back (`energy_battery.py:4333-4376`). The flip comes from two
other defects in `_classify_attain_rung`:

1. **Producer bug: the rung-1 entry credits the EV's entire draw as solar that will go to the battery.**
   `energy_battery.py:4217-4221` converts the full `ev_load_w` into %/h (`ev_kw / 40 kWh * 100`), and
   `:4433-4463` projects `soc + (rate + ev_load_pct_per_h) * h + surplus`. A 10.1 kW car adds ~25 %/h, so with
   ~2.5 h to the boundary the projection reaches 100 % from a 30 % start. That is only true if the car is running
   on solar. When the car is running on **grid import**, pausing it cuts the import and sends nothing to the battery.
2. **The keep test is inconsistent with the entry test.** Once latched, rung 1 is kept only if `projected_rung0`
   (observed 3-tick rate, `ATTAIN_RATE_WINDOW_TICKS = 3`, `:265`) stays ≥ target − 3 (`:4377-4389`). The comment at
   `:4378-4379` assumes the observed rate "already reflects" the pause, but 5 minutes after the pause the 3-tick window
   is still mostly pre-pause samples. Even a real redirect would fail this test on the first tick after entry.

The loop, tick by tick:

| Tick | Rung result | Phase / intent | EV action |
|---|---|---|---|
| N | no latch, rung 0 fails, entry projection (full EV credit) ≥ 93 → **rung_1**, latch set (`:4463-4472`) | `solar_attain`, intent `redirect` (`:4535-4538`) | `energy.py:8191-8192` pause_reason `redirect` → `determine_arbitrage_actions(arbitrage_charging=True)` pauses (`energy_pool.py:3114-3141`) |
| N+1 | latched; counterfactual < 93; `projected_rung0` < 87 → **escalate rung_2**, latch cleared (`:4382-4389`) | gate open (`:4540-4542`), phase WAIT (window not open) | WAIT is not CHARGE and grid charge is off, so pause_reason = None (`energy.py:8185-8194`) → release branch turns the EV on (`energy_pool.py:3143` ff.) |
| N+2 | no latch, EV drawing again → entry fires again | rung_1 | pause |

Period 10 min, one switch per 5-min tick. The loop ends only when something else wins: the charge window opens
(CHARGE, breaker pause) or attain takes over.

## Q1: Is it an 80-90 % SOC band?

**No.** Rung 1 has no SOC band. It can fire on any off-peak tick where all of these hold
(`_gate_is_open` `:4498-4530`, `_classify_attain_rung` `:4176-4472`):

- arbitrage enabled, and the target day is `poor`/`very_poor` (or D+2 poor with the multi-day horizon on);
- off-peak TOU (only the off-peak branch calls `_get_arbitrage_phase`);
- SOC < `peak_buffer_target` (live **90**, `number.ura_energy_coordinator_peak_buffer_target`); at or above 90 it returns rung_2 → HOLD (`:4187-4191`);
- rung 0 fails (projection without redirect < 93);
- forecast solar surplus ≥ 0.5 %/h (`ARB_LADDER_SOLAR_NEGLIGIBLE_PCT_PER_H`, `:300`);
- an EV is drawing power (`current_charging_load_w() > 0`);
- in daylight (since v5.103.37, `:4244-4260`, `:4308-4312`); before that, also at night.

"SOC 30.0% <= target 30% (target poor)" in the 11-08 reason is the **drain floor** (`current_offpeak_drain_target`
30, poor slider), not the arbitrage target. The arbitrage target in the projection text is the 90.

Live knobs (read 2026-11-12): `peak_buffer_target` 90, `arbitrage_charge_lead_time` 150 min (window opens 14:30 CST
for the 17:00 mid-peak), drain targets poor/very_poor 30, `fill_priority_soc` 80, `ev_battery_drain_soc` 80,
`resume_ev_at_battery_soc` 95, `grid_arbitrage` on, `ev_tou_management` on, `ev_charge_onset_overnight` on.

Episodes:

| Episode (UTC) | SOC | Owner / mechanism | Source |
|---|---|---|---|
| 09-20 06:33-06:53 (01:33 CDT) | 9-10 % | EV load alternating every tick at night, off-peak; most likely night rung-1 (rung not recorded) | `decision_log.dp_eval` ev_load_w flips |
| 09-28 | n/a | rung_1 ⇄ WAIT (night) | card / D0 replay; recorder gone |
| 10-01 06:09-08:20 (01-03 CDT) | 7-9 % | rung_1 ⇄ WAIT, **night**, no sun; 31 turn-ons | DESIGN §9.1, card |
| 10-09 19:19-19:54, 10-11 19:21-19:41 | 79-83 % | **fill_priority**, not arbitrage (self_consumption, phase n/a) | card `EV-FILL-PRIORITY-SOC-CHATTER-1` (done) |
| **11-08 20:03-20:33 (14:03-14:33 CST)** | **30 %** | **rung_1 ⇄ WAIT, daylight**, owner `arbitrage`; 7 switches on each of garage_a and garage_b | recorder (below) |

The 80-90 % band the operator has in mind is the **fill-priority** chatter (threshold 80, the same number for pause
and resume). That is a different owner and was fixed under its own card. Rung-1 episodes ran at 7-10 % and 30 %.
In the 7-day recorder (11-05 to 11-12) 11-08 is the only cluster of 4 or more switches on either garage switch.

**11-08 is the same mechanism** as 10-01, in daylight. Recorder (strategy attrs, solar kW / net import kW):

| UTC | phase | rung | proj r0 | proj r1 | EVs paused | solar | net import |
|---|---|---|---|---|---|---|---|
| 20:03:08 | solar_attain | rung_1 | 32.8 | **100.0** | → both | 1.24 | 12.9 |
| 20:08:08 | wait | rung_2 | 31.9 | 0.0 | [] | 1.91 | **2.4** |
| 20:13:08 | solar_attain | rung_1 | 31.8 | 100.0 | both | 1.09 | 14.7 |
| 20:18:09 | wait | rung_2 | 31.7 | 0.0 | [] | 1.45 | **3.0** |
| 20:23:09 | solar_attain | rung_1 | 31.7 | 97.7 | both | 0.97 | 13.5 |
| 20:28:10 | wait | rung_2 | 31.6 | 0.0 | [] | 0.78 | **3.5** |
| 20:33:10 | attain → 20:38 charge | rung_1 → rung_2 | | | held (breaker) | | |

The table shows the producer bug directly. With the cars paused the house still imported 2.4-3.5 kW, so solar
(about 1-2 kW) never covered the non-EV load. Pausing an 11 kW car could not have sent any solar to the battery. SOC
stayed at 30 % for the whole episode, and attain measured +0.0 %/h. The rung-1 projections of 100 / 97.7 % were
false on every entry.

## Q2: Pause the EVs whenever arbitrage is active?

**What "arbitrage active" means in code.** The phase comes from `_get_arbitrage_phase` (`energy_battery.py:4544`),
called only in off-peak: `n/a` (gate closed: not a poor day, or rung 0/1 closed it), `WAIT` (gate open, charge window
not open), `CHARGE` (grid-charging toward 90 %), `HOLD` (SOC ≥ 90). There are also the closed-gate labels
`solar_attain`/`attain` with rung_0/rung_1. EVs are paused today only in CHARGE / grid-charge intent (`breaker`,
`energy.py:8185-8189`, dispatched before the CFG write) and on rung_1 (`redirect`).

**How often it is on (7 days, 11-05 to 11-12, recorder):** gate open or rung_1 for 52.7 h, of which **21.0 h were
00-07 CST**, 24.5 h 07-17 and 7.2 h 17-24. On 4 poor-forecast days (11-06 to 11-09) WAIT ran 9.8-17.2 h per day.
**The garage_a switch was on for 23.8 h of those**: 17.5 h overnight, 6.3 h daytime.

**Cost.** A blanket pause would have blocked about 17.5 h of overnight off-peak charging in one week, which is
essentially the whole 01:00-07:00 onset window on every poor-forecast night. That window is the cheapest one, and
it is when the cars are expected to fill. Cars would leave undercharged on exactly the days the house is short of
solar. It would also block 6.3 h of midday off-peak charging that is safe today because the battery is parked, not
grid-charging, in WAIT.

**Does it remove the loop?** It removes this loop only if rung_1/solar_attain also counts as "active". In that case
the pause owner becomes stable for the whole poor day. The flip point then moves to the gate boundary: forecast
class changes (Solcast refreshes, midnight roll, D+2 neighbour) and rung_0 ⇄ rung_2 transitions. Those carry 3 %
hysteresis and are rare, so the loop is effectively gone, but at the cost above.

**Interactions:** it adds a new standing arbitrage claim that the off-peak ensure-on / onset funnel
(`_proactive_offpeak_holds`), drain-precedence Path A (`_paused_by_battery_drain`) and fill_priority (`_paused_by_fill_priority`)
must all defer to (the release peer list at `energy_pool.py:3195-3216`). Releases at WAIT→n/a would also hand chargers to
fill_priority (`:3217-3244`), so a third owner joins at each boundary. The breaker invariant is untouched: CHARGE
already pauses. It is a one-site change (`energy.py:8185-8195`), but it changes behaviour over about 50 h a week.

## Shapes compared

| Shape | Removes the loop? | Cost / comfort | Ingredient risk | Sites touched |
|---|---|---|---|---|
| **A. Blanket pause while arbitrage is active** | Yes (if rung_1 is included); moves the flip to rare gate boundaries | **High**: ~17.5 h/week of overnight off-peak EV charging blocked, plus 6.3 h midday | New standing owner across a ~50 h/week window; peer/precedence ripple with onset, drain Path A, fill_priority | `energy.py:8185-8195` (1), but wide behavioural reach |
| **B. "Judge the projection without the paused EV" (as the card words it)** | **No** as worded. The exit-to-rung-0 counterfactual already exists (`:4333-4376`). The failing leg is the escalation (`:4382`) plus the false entry credit | Low | Low | `_classify_attain_rung` only |
| **C. Minimum hold time on the rung-1 pause** | **No**. It slows the loop to period ≈ hold + 5 min, still flapping. On 11-08 it would have held the cars off for nothing (battery gained 0) | Medium: blocks EV charging for a redirect that does not exist | New timer on a state machine × time seam (the risky ingredient) | `_classify_attain_rung` |
| **D. Cap the entry credit at the solar actually feeding the EV, and hold the latch until the rate window has flushed** | **Yes**. Entry stops firing when the car is on grid (11-08, 10-01, every recorded episode). When the redirect is real, the latch survives the measurement lag and is judged on post-pause samples | **Lowest**: cars charge unless pausing really sends solar to the battery | One read-only input (reused) + a lag guard derived from an existing constant; no new owner, no new emission site | `_classify_attain_rung` only (entry `:4413-4472`, keep `:4377-4389`, snapshot `:4468`) |
| D-alt. Retire rung 1 (entry always → rung_2, behind a module constant) | Yes | Loses rung 1's value, which measured **0** in the only recorded daytime episode | Lowest (removes a rare-fire writer) | `_classify_attain_rung` entry |

### D in detail

- **Entry credit.** `redirectable_kw = clamp(ev_kw − effective_import_kw, 0, ev_kw)`, where `effective_import_kw` is
  **REUSED** from `_effective_import_kw()[0]` (`energy_battery.py:4060-4093`: non-battery grid import, house + EV,
  with battery charge already subtracted). That works out to `solar − non-EV load`, clamped to the EV draw. Use
  `redirectable_kw` in place of `ev_load_kw` at `:4220-4221`. If `net_power` is unavailable the snapshot is `None`;
  then set `redirectable = 0`, so rung 1 is skipped and the result is rung_2. That fails toward *not* pausing for
  redirect. The breaker pause still happens in CHARGE, so the safety direction is unchanged.
  11-08 check: 20:03 → 10.1 − (12.9 − ~0) < 0 → 0 → no entry → WAIT, EVs keep charging until CHARGE pauses them for
  breaker protection at 14:30. 10-01 (night): already blocked by the daylight gate, and also blocked by the cap.
- **Snapshot consistency.** `_arb_last_ev_load_pct_per_h` (`:4468`) stores the *capped* %/h, so the exit
  counterfactual (`:4349`) subtracts the same quantity the entry added.
- **Lag guard.** While latched, skip the `projected_rung0 < exit_band` escalation (`:4382`) until the rate window
  holds `ATTAIN_RATE_WINDOW_TICKS + 1` post-pause samples. This is not a tuned hold time. It is the window length,
  derived from an existing module constant. After the flush the observed rate is real evidence, so escalation is
  then legitimate and happens at most once (the re-entry then sees the live import). The solar-collapse escape
  (`:4322`) and the night release (`:4308`) stay ungated.
- **Knobs.** No new behavioural number. If a rung-1 kill switch is wanted for D-alt fallback:
  `ARB_LADDER_RUNG1_ENABLED` (module constant, rung 1 of the ladder: changing it needs review because it is in the
  arbitrage state machine). NEW: grep of `energy_battery.py`/`energy_const.py` found no rung-1 enable flag.
- **Not touched:** `energy.py:8179-8195` pause-reason derivation, `determine_arbitrage_actions`, breaker ordering,
  release peers, fill_priority, drain Path A, onset. Zero EV emission sites change.

## Recommendation

**D**: cap the rung-1 entry credit at the solar that is actually feeding the EV, and gate the latched escalation on
the rate window having flushed. It fixes the producer. It is the only shape that is both correct and cheap, and the
whole change stays inside one pure-ish classifier. A and C fail on cost and correctness respectively. B as worded
targets a leg that already works.

Marginal-benefit note: D-alt (retire rung 1) is the simplest shape that removes the loop, and the only recorded
daytime rung-1 episode delivered nothing. If plan review prices the lag guard as too much rare-fire state-machine
surface, ship the **entry cap alone**. It removes every recorded episode, because all of them had the car on grid.
Park the lag guard, with this revival trigger: an arbitrage-owner toggle cluster while `net_import < ev_load` (that
is, the EV was genuinely solar-fed). Keep D-alt as the fallback if the cap still mis-fires.

**Falsifiable invariant:** *In any off-peak tick, the arbitrage owner never pauses an EVSE with intent `redirect`
unless, at that tick, the EV's draw exceeds non-battery grid import (some of it is solar-fed). Once paused for
`redirect`, no rung-ladder decision releases it before the rate window holds only post-pause samples. So no garage
EVSE sees an arbitrage-owned off→on→off sequence within `(ATTAIN_RATE_WINDOW_TICKS + 1)` ticks, and grid-charge
intent still always pauses (breaker unchanged).*

Live discriminator: replaying 11-08 conditions (EV ~10 kW, solar < 2 kW, import > EV draw) shows phase WAIT with
`arbitrage_rung = rung_2`, `arb_projection_rung1` None/low, and **no** arbitrage-owned charger toggles before the
CHARGE pause. Under a plausible different failure, such as the lag guard missing or a pause owner other than
arbitrage, either the toggles persist or `pause_owners` shows another owner. Mutation targets: the cap at the entry
site and the lag guard at `:4382`.

**Tier:** 3, as carded (arbitrage state machine, cost + breaker adjacent). Expect 2 plan reviews. Entry-cap-only
narrows the build to a single site, with the dwell parked.
