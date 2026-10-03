# AUDIT — EC overnight drain floor + 10-01 EV ping-pong: "why now" (2026-10-03)

Read-only. No code or HA changes. Sources: recorder `sensor.ura_energy_coordinator_battery_strategy`
attrs (retained from 09-26 04:12 CDT), `sensor.garage_{a,b}_power_minute_average` (the configured EVSE
power entities, `core.config_entries` → `energy_evse_{a,b}_entity`), `sensor.ura_energy_coordinator_ev_charging_status`,
URA DB `decision_log.dp_eval` (08-01 → 10-01 11:05Z; carries `drain_target_soc`, `ev_load_w`, `soc` per tick).
Times are CDT unless marked Z.

## TL;DR

1. **The drain ladder is not broken.** On every night where the target day was excellent/good/moderate it parked
   exactly at its class floor: 09-26/09-27 excellent → 10, 09-28 good → **15** (held 15 all night), 09-29
   moderate → **20** (held 19-20 all night).
2. **"Drains to 10 every night" is true only since 09-30, and only because the target day became `poor`.** With
   `arbitrage_enabled=True` and target poor/very_poor, `_get_off_peak_decision` routes to the arbitrage state machine
   *before* the drain-ladder fallback (`energy_battery.py:5626`), and arbitrage WAIT deliberately emits
   `reserve_soc` (10), not the poor drain target (`energy_battery.py:3510-3534`, "Per plan Mistake #7: no artificial
   drain target"). So the `poor: 30` / `very_poor: 30` rungs of the ladder are **unreachable while the arbitrage gate
   is open on rung_2**. The `current_offpeak_drain_target=30` / `current_park_floor=30` /
   `effective_release_floor=30` attrs describe the fallback path and are **not what is commanded**
   (`current_commanded_reserve=10`, `command_trail.hold_owner=arbitrage_wait`). This is a design/manual conflict,
   not a regression: manual §2.2 says the poor class "protects reserve" and never says arbitrage WAIT bypasses it.
3. **Why the ping-pong was exposed on 10-01 and not before:** it needs three conditions together, and 09-30→10-01
   was the first night in the 5+ weeks of `dp_eval` history where all three were true:
   - **(a) forecast gate open:** target day poor/very_poor. This happens only from 09-30 08:46 on (first `open` in the
     recorder). Every earlier night was `closed_forecast`, so the rung ladder was never evaluated.
   - **(b) after midnight:** the rung projection's "solar horizon" is `sunset_today − now`
     (`energy_battery.py:2996-3003`; `energy_projector.py:185-188`). Before midnight, today's sunset is past, so the
     horizon is 0. **After midnight, "today" becomes the new calendar day, whose sunset is ~17-18 h away.** The horizon
     then spans the whole night (lower bound is never sunrise).
   - **(c) EV actually drawing:** `ev_load_w > 0` (`current_charging_load_w`, `energy_pool.py:2819`). The rung_1
     entry adds the EV load back over that horizon: 11.6 kW ≈ 29 %/h for ~15 h → `arb_projection_rung1 = 100`.
4. **Negatives fit:** 10-01→10-02 and 10-02→10-03 were also poor, post-midnight nights with gate `open`, and the
   charging-status entity reported `charging`. But `garage_a/b_power_minute_average` show no draw above 1 kW (the car
   was already full after the 10-01 14:00-16:00 arbitrage charge). With `ev_load_w = 0`, rung_1 is skipped
   (`ev_load_pct_per_h <= 0 → rung_2`). So those nights saw **no rung_1 and no flap**, and simply WAIT'd at 10.
5. **Season change, Envoy flakiness and recent deploys are not the discriminator** (see §4).

## 1. How the floor is supposed to work vs what the code does

**Manual (§2.1-2.2):** off-peak drain target is set by the class of the target day (the day of the next high-rate
transition). Poor/very_poor → protect reserve. The same class also opens the arbitrage gate.

**Producer chain (code):**
- Class: `_resolve_target_day` (`energy_battery.py:2681`), peak-anchored on `tou.get_next_high_rate_transition`.
  After midnight it uses Solcast TODAY (`target_day_source=solcast_today`). This was correct on every night sampled.
  There is no staleness across midnight.
- Ladder: `_effective_drain_targets` / `_get_offpeak_drain_target` (`:1881`, `:1914`); live
  `{excellent 10, good 15, moderate 20, poor 30, very_poor 30, unknown 40}` = effective.
- `_drain_target_for(now)` (`:1938`), which takes `max(d1, d2)` under the multi-day horizon.

**Consumer that decides what is emitted (`_get_off_peak_decision`, `:5495-5780`), in precedence order:**
1. Completed-chunk attain-hold / HOLD short-circuits (`:5547-5622`).
2. `_gate_is_open(now, target_day_class)` → `_get_arbitrage_decision`. WAIT → `reserve_soc` (10); CHARGE/HOLD →
   `peak_buffer_target` (80). **The drain ladder is never read on this path.**
3. Attain branch (`:5641`).
4. Drain-ladder fallback (`:5660-5780`). This is reached only when arbitrage is disabled, the forecast gate is closed,
   or the rung ladder closes the gate (rung_0/rung_1).

So under poor/very_poor with arbitrage on, the ladder value only applies on rung_0/rung_1 ticks. On 10-01 that
meant the rung_1 ping-pong ticks: `Off-peak hold — SOC 8% <= target 30%` emits `hold_reserve = int(soc)` = 8
(`:5755-5774`), which is not 30 either. **The 30 % floor never actually held on any poor night.**

**Live 10-03 snapshot explained:** `target_day_class=poor` (today, `solcast_today`), `arbitrage_gate=open`,
`arbitrage_rung=rung_2`, `arbitrage_phase=wait`, `reserve_soc 10`, `current_commanded_reserve 10`,
`hold_owner arbitrage_wait`. `current_offpeak_drain_target=30` is the fallback-path accessor (`:1962`), and
`current_park_floor=30` comes from `park_floor_source=planned_fallback`. These are display values; nothing consumes
them on this tick's emission.

## 2. Per-night table (recorder 09-26 → 10-03; dp_eval for EV/drain history)

| Night (start) | Target class (after 00:00) | Gate | Commanded reserve overnight | SOC at 21:00 → min | EV draw after midnight | Rung_1 / flap |
|---|---|---|---|---|---|---|
| 09-26 | excellent | closed_forecast | 10 (ladder) | 63 → ~9 by 02-04 (overnight drain) | none | no |
| 09-27 | excellent | closed_forecast | 10 (ladder) | 9 (summer peak/post-peak discharge reached 12 by 20:00) | 02:00-04:08 | no (gate closed) |
| 09-28 | good | closed_forecast | **15** | 15 held all night | 02:00-03:07 continuous | no |
| 09-29 | good→moderate (multi-day max) | closed_forecast | **20** | 25 → 20 held | 02:00-03:05 | no |
| 09-30 | **poor** | **open** rung_2 / rung_1 | 10 (WAIT) ↔ 8 (rung_1 hold) | **9 at 21:00** (summer peak + post-peak mid_peak discharge to 10) | **01:14-06:11, 11.6 kW** | **YES, 01:14-06:11, ~10-min period** |
| 10-01 | poor | open rung_2 | 10 (WAIT) | 30 → 10 by 23:00 (overnight WAIT drain) | none (car full) | no |
| 10-02 | poor | open rung_2 | 10 (WAIT) | 28 → 10 by 23:00 | none | no |

Where 10 % was reached:
- **09-30:** before off-peak. Summer peak 16-20 discharges to the static reserve: 76 % at 17:00 → 21 % at 20:00 →
  9 % at 21:00. That is the last summer day (the TOU season flips to shoulder on 10-01).
- **10-01 and 10-02:** during off-peak. The shoulder mid_peak 17-21 discharges to about 30 % by 21:00, then arbitrage
  WAIT lets it drain to 10 by about 23:00.

## 3. The rung_1 night firing: which gate should stop it, and what defeated it

The protections that exist:
- **(i) The forecast gate.** rung_1 cannot run unless the target day is poor/very_poor. That kept it dormant every night
  before 09-30.
- **(ii) The `ARB_LADDER_SOLAR_NEGLIGIBLE_PCT_PER_H` guard** (`:3139`). This one is defeated at night by design: it
  reads `_expected_solar_surplus_pct`, which is a *forecast to the boundary*. After midnight it slices today's whole
  Solcast remaining (`:3837-3858`), so it is non-zero all night.
- **(iii) v5.17.4 "bound rung projection to solar-capable hours"** (commit b35189448, 2026-07-15). This was meant to stop
  extrapolating rate × hours outside daylight. It bounds only the **end** of the window (`min(mins, sunset_today − now)`)
  and never the **start** (sunrise). Pre-midnight the bound works by accident (sunset passed → 0 h). Post-midnight
  it covers the night.

This is direct evidence from the recorder on 10-01:
- 01:14:50: `rung_1`, `p0=46.2`, `p1=100.0`, EV paused (`redirect`).
- 01:19:59: `rung_2`, `p1=0.0`, released.
- 01:25:06: `rung_1` again, and so on. That is 15 cycles to 03:20, then 05:30 and 06:05, all at SOC 7-9 %.

`p1` saturating at 100 % from SOC 8.9 % is only possible with a multi-hour rate horizon (8.9 + 29 %/h × h ≥ 83
needs h ≥ 2.6). A sunrise-bounded horizon gives h = 0 before ~07:20.

**Release half of the loop:** with the EV paused, the latched path subtracts the assumed EV rate and finds
`projected_rung0 < exit_band`. That sets rung_2 and intent `breaker`, but the phase is WAIT, not CHARGE, so nothing
holds the EV. The pause set clears, the EV resumes, and the next tick sees `ev_load_w > 0` and re-enters rung_1.
(Spec A4/D1 independently describes the same mechanics.)

## 4. Why now: alternatives tested

| Candidate | Prediction if causal | Observation | Verdict |
|---|---|---|---|
| **Gate open (poor) × post-midnight × EV drawing** | Flap only on the night all three hold | Only 09-30→10-01 has all three. 10-01 and 10-02 nights were poor + post-midnight with no draw → no flap. 09-26..09-29 had draw but the gate was closed → no flap. `dp_eval` 08-26→09-30: no night has `drain_target_soc=30` together with EV draw (08-31's 30 appears at 11:04, after the EV session, which ran on target 10). | **Discriminates** |
| TOU summer → shoulder (10-01) | Flap only on shoulder nights | The flap night 09-30→10-01 is the season boundary; post-midnight is shoulder (boundary 17:00, mins ≈ 945). But a summer poor night has the same defect (boundary 14:00, horizon ≈ 13 h → still 100 %), and shoulder nights 10-01/10-02 did not flap. The season change made the evening shape different (it ends at ~30 % instead of ~10 %), but it is not necessary for the flap. | Not causal; contributes only to the 21:00 SOC |
| Envoy dropout / LKG / degraded telemetry | Toggles on blind ticks | DESIGN §9.1: 13 of 14 turn-ons on Envoy-sighted ticks; recorder rows show `soc` present during the flap. Dropouts occur on almost every night (00:00 "Envoy unavailable" on 09-27, 09-28, 09-29, 09-30, 10-01, 10-02) without a flap. | Refuted as cause |
| Target-day staleness across midnight | Wrong class after 00:00 | `target_day_source` flips `solcast_tomorrow` → `solcast_today` at midnight, and the class is consistent with Solcast on every night. | Refuted |
| Recent deploy | Code change between the last clean night and 10-01 | energy*.py commits: 09-28 18:46/19:12 (EV-ARBITRAGE-RELEASE-IGNORES-FILL-PRIORITY-1, release path) and 10-02 21:22 (SOC ladder split, after the flap). The rung horizon code is unchanged since 07-15/07-16 (v5.17.4 / R7). | Not causal (the latent defect has been there since 07-15) |
| "09-28 also ping-ponged" | Rung or pause churn on the 09-28 night | Gate was `closed_forecast` all night, and `evse_paused_by_arbitrage` was empty. garage_a drew continuously 02:00-03:07 (2 transitions). There is a single off/on (02:53→02:56) on the **09-27→09-28** night during an Envoy-unavailable stretch, which is not a rung loop. | **Not reproduced.** If the operator saw a 09-28 flap, it is a different mechanism; ask for the time window |

Limitation: the recorder only holds strategy attributes back to 09-26. For July-August, poor-night × EV draw
co-occurrence can only be inferred from `dp_eval` (`drain_target_soc` semantics differ before 08-26: it was 80
everywhere). I cannot prove that no summer poor night with an overnight EV session flapped before 08-26.

## 5. What the earlier analysis got right and wrong

- **Right (SPEC A4/D1, card EC-RUNG1-WAIT-EV-PINGPONG-1):** the rung_1 ⇄ WAIT mechanism, the sunset-only horizon, and
  that Envoy is not the cause.
- **Missed, "why now":** neither the spec nor the card says why a defect that is latent since 07-15 first appeared on
  10-01. The answer is the conjunction above. The first poor target-day run since the ladder shipped coincided with an
  overnight EV session. The season change is a coincidence of date, not a cause.
- **Wrong framing, "drains to 10 every night" read as the drain floor failing:** the ladder works (15 and 20 held on
  09-28 and 09-29). On poor nights it is **bypassed by design** by arbitrage WAIT. Its poor/very_poor rungs are dead
  configuration whenever arbitrage is on and rung_2. The `current_offpeak_drain_target` / `current_park_floor` /
  `effective_release_floor` = 30 attributes are misleading on those ticks, because the commanded reserve is 10.
  SPEC D7/Q2 frames this as an open policy question ("should WAIT sit at 8-10 %?"). The manual (§2.2) already promises
  "protect reserve" on poor days, so it is a **code-vs-manual divergence** that needs an operator ruling (honour the
  poor floor during WAIT, or amend the manual).
- **Spec comment D7** ("rung-1 ticks closed the gate so CHARGE could not run") is moot for 10-01. The charge window
  opened at 14:00, CHARGE ran 14:01, and the attain branch reached 80 % by 15:51 (recorder rows 14:01-16:00).

## 6. Confidence

- Mechanism (post-midnight sunset horizon × EV load × open gate): **high**. Recorder `p1=100` at SOC 8.9 is arithmetic
  proof of the multi-hour horizon. All 7 nights fit, including both negative classes.
- "First time since ≥ 08-26": **medium-high** (from `dp_eval`). Before 08-26: **unknown**.
- Drain ladder working on non-poor nights: **high** (09-28 = 15, 09-29 = 20 held).

## 7. Implications for the fix (no build here)

- Bound the rung horizon at **both** ends, to daylight within [now, boundary] (sunrise to sunset). This could reuse the
  overlap logic already in `_expected_solar_surplus_pct`. Rung_1 should be impossible when no daylight lies before the
  boundary inside the next N hours. This kills the night loop at its root. A re-entry cooldown (SPEC INV-1) then
  becomes defence-in-depth, not the fix.
- Separate operator ruling: should arbitrage WAIT floor at `max(reserve_soc, drain_target(poor))` (manual §2.2), or
  should the manual and status attributes be changed to say WAIT drains to `reserve_soc`? If the latter, the status
  attributes should stop showing 30 as the park floor on WAIT ticks.
