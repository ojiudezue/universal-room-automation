# SPEC — Energy Coordinator behaviour contract (what SHOULD happen)

**Status:** DRAFT for operator review, 2026-10-03. Spec only, no code changed.
**Operator ask:** *"We need to be clear on what SHOULD happen. Seams from low-solar days, leaning on arbitrage more, and a flaky Envoy."*
**How to read:** each row is a situation, the intended battery command (reserve, charge-from-grid = CFG), the intended charger
state, and the ONE owner responsible. "Today's code" was read this session (file:line). Rows marked **DIVERGES** are where the
code does something different from the intent. Intent column is my draft from the manual, ratified designs and memory; rows marked
**(proposed)** are not yet operator-ratified and are repeated in the open questions.

Sources read: `docs/Coordinator/ENERGY_COORDINATOR_MANUAL.md` §2.1-2.6, `docs/planning/DESIGN_ec_degraded_data_policy.md` (REV 2 + §9 D0),
kanban cards EC-RUNG1-WAIT-EV-PINGPONG-1 / EC-DEGRADED-DATA-POLICY-1 / EC-ATTAIN-HOLD-WHEN-ENVOY-BLIND-1, memory notes on EV drain
precedence, charge onset, attain solar aggression, battery SOC = Envoy. Code: `energy_battery.py`, `energy_pool.py`, `energy.py`,
`energy_projector.py`, `energy_const.py` (paths under `custom_components/universal_room_automation/domain_coordinators/`).

---

## 0. Vocabulary (plain)

| Term | Meaning | Where |
|---|---|---|
| Seasons / periods | Summer (Jun-Sep): off-peak 00-14 & 21-24, mid-peak 14-16 & 20-21, **peak 16-20**. Shoulder (Mar-May, Oct-Nov): off-peak 00-17 & 21-24, mid-peak 17-21, **no peak**. Winter (Dec-Feb): off-peak 00-05, 09-17, 21-24; mid-peak **05-09** and 17-21, no peak. | `energy_const.py:15-66` |
| Boundary | Start of the next higher-rate period. Shoulder = 17:00 mid-peak. Winter has a **morning** boundary at 05:00. | `energy_battery.py:3960-3993` |
| Reserve | Discharge floor, not a charge target. | Manual §2.2 |
| Drain target | Overnight floor chosen by the target day's solar class (excellent 10 … poor 30, unknown 40). | `energy_const.py:790-797`, `energy_battery.py:5701-5722` |
| Peak buffer / attain target | SOC to have at the boundary (default 80). | `energy_const.py:830` |
| Reserve soc | Hard floor (default 10). | `energy_const.py:181` |
| Charge window | Opens `arbitrage_charge_lead_time_min` before the boundary (default 360, live knob 180). | `energy_battery.py:2771-2786`, `energy_const.py:831` |
| Rung 0 / 1 / 2 | Arbitrage ladder: 0 = solar alone attains, 1 = pausing EVs lets solar attain ("redirect"), 2 = grid-charge needed. | `energy_battery.py:2862-3200` |
| Data tiers | Envoy fresh (≤300 s by `last_reported`) → LKG (≤300 s) → cloud (≤600 s by `last_updated`) → blind (none). | `energy_battery.py:870-989` |

---

## 1. Scenario table

### A. Normal data (Envoy live)

| # | Situation | Intended battery | Intended chargers | Owner | Today's code does | Verdict |
|---|---|---|---|---|---|---|
| A1 | Off-peak, target day good/excellent, SOC > drain target | reserve = drain target, CFG off; battery serves house down to it | ON (ensure-on), subject to drain guard / BAEC | Battery: drain-target path. EV: ensure-on (#11) | `energy_battery.py:5734-5754` emits reserve=drain target; EV `energy_pool.py:1632-1670` | Matches |
| A2 | Off-peak, target day good/excellent, SOC ≤ drain target | reserve = current SOC (stop discharge), CFG off — no grid charge, solar refills tomorrow | ON | Drain-target path | `energy_battery.py:5756-5774` reserve=int(soc), CFG default False. Comment says "import cheap grid" but nothing charges | Matches intent; comment misleading |
| A3 | Off-peak, target day poor, before charge window, no EV load | reserve = reserve_soc (10), CFG off ("WAIT"); battery may drift low, CHARGE refills later | ON | Arbitrage (rung 2 WAIT) | `energy_battery.py:3413-3414`, `:3510-3534` | Matches. See Q2 (should it sit near 8-10 % all night?) **RESOLVED (Q2 ruling (a), build `feature/ec-daylight-poor-night`, version TBD at deploy): WAIT holds the poor drain floor (park only).** |
| A4 | Off-peak, target day poor, **night, EV drawing** | Same as A3: WAIT. Pausing the EV at night frees no solar, so rung 1 must not fire | ON, **stable** (no toggling) | Arbitrage (rung 2) | **Rung 1 latches at night.** Projection horizon is bounded by *today's* sunset, which at 01:00-06:00 is ~13-18 h away, so the EV load (11.6 kW ≈ 29 %/h on 40 kWh) is extrapolated over ~10 h → "projected 100 %" (`energy_battery.py:2992-3003`, `:3157-3195`). The no-solar guard reads the *forecast* surplus to the boundary, which is non-zero at night (`:3139`, `:3837-3857`). Next tick (EV paused) the latched check fails → rung 2 → WAIT → release turns EV on (`:3106-3113`; `energy_pool.py:2940-3016`). 10-min cycle. Reserve also alternates 8 ↔ 10 (hold `:5757` vs WAIT `:3516`) | **DIVERGES (D1)** — **RESOLVED by EC daylight horizon (build `feature/ec-daylight-poor-night`, version TBD): rate horizon daylight-gated, rung 1 cannot enter before sunrise.** |
| A5 | Off-peak, target day poor, daytime, solar running, EV drawing, pausing EV lets solar reach target | Rung 1: CFG off, reserve per drain path; pause EV, solar fills battery | OFF (label "redirect") until solar attains, then ON | Arbitrage (rung 1) | Same code as A4; legitimate in daylight. Exit is counterfactual (`:3044-3117`) | Matches by design; still no anti-flap if counterfactual oscillates |
| A6 | Off-peak, poor, inside charge window, SOC < target | reserve = target, CFG on (CHARGE) | OFF for breaker, before CFG is sent | Arbitrage (rung 2 CHARGE) + breaker chokepoint | `energy_battery.py:3306-3411`, `:3487-3508`; EV paused first `energy.py:6773-6797` | Matches |
| A7 | Off-peak, poor, SOC reaches target | reserve = target until boundary, CFG off (HOLD, chunk locked) | ON (no breaker load) | Arbitrage HOLD / completed-chunk HOLD | `energy_battery.py:3459-3485`, `:5547-5618` | Matches |
| A8 | Off-peak, target day NOT poor, but realized solar falling short of target | Attain: CFG on until target, then HOLD | OFF during CFG | Attain branch | Entry `energy_battery.py:4901-4960`; latched path `:4659-4899`. Known bias: front-loads grid then exports solar (AUDIT_attain_solar_aggression) | Matches; aggression is a separate parked question |
| A9 | Summer mid-peak, peak still ahead, SOC < target | Attain continuation may keep CFG on (mid-peak cheaper than peak) | OFF (mid-peak) | Attain (D1b) | `energy_battery.py:5406-5429` | Matches |
| A10 | Summer mid-peak, peak ahead, otherwise | reserve = current SOC (freeze) | OFF | Mid-peak hold | `energy_battery.py:5444-5459`; EV `energy_pool.py:1282-1310` | Matches |
| A11 | Summer peak | reserve = effective reserve, battery discharges; CFG off | OFF | Peak branch | `energy_battery.py:5375-5390`; EV off `energy_pool.py:1282-1310` | Matches |
| A12 | **Shoulder** mid-peak (17-21, no peak) | Discharge to reserve; no attain continuation | OFF | Mid-peak discharge | `energy_battery.py:5460-5494` (attain continuation is summer-only, `:5411`) | Matches |
| A13 | **Winter** 05-09 morning mid-peak after an overnight off-peak | Boundary is 05:00: charge window and attain target 05:00, discharge 05-09, then off-peak 09-17 refills from solar/grid before 17:00 | OFF 05-09 | Arbitrage / attain, then mid-peak discharge | Boundary walks across midnight (`:2777`); surplus pre-dawn walks to tomorrow (`:3810-3813`). Not exercised this season | Unverified live; flag for winter (Q6) |
| A14 | Off-peak, EV plugged evening, battery high | Hold reserve at captured SOC, then BAEC decides: drain battery into house first, start car at floor or at must-start-by 03:00 | OFF (owner `dp`) then ON | BAEC (#9) + battery hold | Manual §2.4a; `CONF_DP_MUST_START_BY_MIN_PAST_MIDNIGHT` `energy_const.py:1585` | Matches (shipped, armed) |
| A15 | Off-peak, EV charging, battery discharging, SOC < 80 | Battery not drained into car | OFF until floor / must-start-by | Drain guard (#7) | `energy_pool.py:2191-2310` | Matches |
| A16 | Off-peak, charge-onset enabled, before onset time | Battery per other rows | Charger that is OFF stays OFF until onset or must-start-by; never turned OFF mid-charge | Ensure-on funnel | `energy_pool.py:1632-1659`, `:110-174` | Matches |
| A17 | Battery ≥ 95 % with surplus solar (any non-peak) | No change | Excess-solar claims L2 chargers | Excess solar (#10) | Manual §2.4 | Matches |

### B. Degraded data (Envoy flaky)

| # | Situation | Intended battery | Intended chargers | Owner | Today's code does | Verdict |
|---|---|---|---|---|---|---|
| B1 | Envoy down < 5 min (LKG tier) | Decide normally on LKG | Unchanged | Strategy | `energy_battery.py:904-908` | Matches |
| B2 | Envoy down, cloud SOC fresh and **moving** | Decide normally; no *fresh* grid-charge starts; an already-running charge may continue only with a live import reading | Unchanged; no new turn-on caused by the data change | Strategy (degraded) | Proceeds `:5217-5231`; fresh CFG refused `:3332-3349`, `:4907-4916`; running attain releases to HOLD when net power unreadable `:4730-4760` | Matches the v5.17.5 contract |
| B3 | Envoy down, cloud SOC "fresh" but **frozen** (re-reported same value) | Treat as blind, not as truth | As blind (B4) | Resolver | Resolver gates cloud on `last_updated` ≤ 600 s (`:957-972`). A frozen value is rejected after 10 min, but inside those 10 min it is trusted. D0: cloud said 10.0 % while Envoy reached 29 %; p95 divergence 8.7 pp even when "fresh" (§9.2) | Partial — D0 says do NOT switch to `last_reported` (no-go) |
| B4 | Fully blind (no tier), off-peak, no grid charge running | Hold battery as-is, no commands | **Keep whatever pauses exist**; no new turn-on | Strategy blind branch + blind-window guard | Blind branch returns no actions but publishes `charge_from_grid=False` (`energy_battery.py:5197-5215`); breaker intent then ignores the last *commanded* CFG (`energy.py:6764`, only the live switch LKG latch `:6739-6759`) | **DIVERGES (D4)** — "no information" is published as "no grid charge" |
| B5 | Fully blind, a grid charge (attain/arbitrage) was running | Off-peak: keep CFG and keep EVs paused until data returns or boundary; never release EVs while CFG may be on | OFF (breaker) | Breaker chokepoint | Same as B4: decision CFG=False; if the cloud switch reads `on`/LKG-on the pause holds, otherwise the arbitrage release can turn EVs on (`energy_pool.py:2940-2990`) | **DIVERGES (D4)** |
| B6 | Fully blind, peak (or into peak), CFG on | CFG off, reserve → reserve_soc | OFF | Blind de-escalation | `energy_battery.py:5139-5189` (reads cloud switch OR last command) | Matches |
| B7 | Fully blind during attain window (10-02 14:00-15:48 CDT) | (proposed) If a fresh **moving** SOC witness exists, keep attaining bounded; if none, hold and **page the operator** before the boundary | OFF if charging | Strategy blind branch | Holds silently "Envoy unavailable — holding (no commands issued)" (`:5190-5194`); D0 replayed exactly 99/100 min. Cloud was frozen at 10 % so the cloud-attain fix (P1-5) is NO-GO | **DIVERGES (D3)** — no page; outcome left to operator luck |
| B8 | Blind > 2 min, off-peak, charger ON, reserve write cannot be verified | Pause unless envelope proves SOC ≥ drain target or house is exporting | OFF, max 60 min, then must-start-by liveness | Blind-window guard (#2.5) | `energy_pool.py:1313-1432`, debounce `:690-791`, max-defer `:1433-1501` | Matches as designed |
| B9 | Blind but **cloud reserve write verified < 10 min ago** | (proposed) Guard still engages for the EV-drain risk; cloud verification proves the *reserve* is set, not that SOC is known | OFF as B8 | Blind-window guard | Predicate is `blind AND NOT reserve_write_verifiable()` (`energy_pool.py:680-688`) — a recent cloud verify disarms the guard entirely. On 10-01 the verify was > 600 s old, so this did not bite (D0 Q8) | **DIVERGES (D5)** — cloud-only trust; backout knob doc §2.5a calls this an accepted "partial outage" hole |
| B10 | Data blinks blind ↔ sighted every tick | Nothing loosens on a blind tick; debounce only delays **tightening** | No turn-on caused by the blink | Guard + arbitrage release | A sighted tick clears the debounce and drains `_paused_by_blind_window` (`energy_pool.py:703-747`, `:1520-1522`); arbitrage release runs on blind ticks with no blind check (`:2940-2990`) | **DIVERGES (D6)** — small in practice (1 of 14 turn-ons on 10-01) |
| B11 | Local Envoy CFG switch reads `on`, cloud CFG switch reads `off`/stale | Treat CFG as ON for breaker purposes (any witness on ⇒ on) | OFF | Breaker chokepoint | Breaker reads only the **write-leg (cloud)** switch (`energy.py:6730-6733`). D0: local `switch.enpower_…_charge_from_grid` `on` from 06:39:18 and an EV was turned on at 06:45:02 | **DIVERGES (D2)** — possible breaker exposure |

---

## 2. Invariants (falsifiable)

| ID | Invariant | Holds today? |
|---|---|---|
| INV-1 | No charger switches more than **2 times per hour** because of a strategy decision (operator, manual, force-charge excluded). | **No** — 10-01: 31 EV turn-ons in a day, 10-min period (D1). No trip-wire exists (grep `flap`/`toggle` in coordinators: nothing). |
| INV-2 | A pause owner may not release a charger that its own logic will re-pause on the next tick with unchanged inputs. | **No** — rung 1 / WAIT (D1). |
| INV-3 | Never release a protective pause because data went missing; missing data may only hold or tighten. | **Partly** — blind branch publishes CFG=False (D4); sighted blink drains guard set (D6). |
| INV-4 | No EV turn-on while battery CFG is commanded, on, or **unknown-after-commanded-on**, on **any** witness (local or cloud). | **Partly** — checks cloud switch + its LKG latch only (D2, D4). |
| INV-5 | No grid import into peak while blind. | Yes (`energy_battery.py:5139-5189`). |
| INV-6 | No fresh grid-charge start without a live import reading. | Yes (`:3332-3349`, `:4911-4916`). |
| INV-7 | A rung that claims "pausing the EV redirects solar" must only fire while solar is actually producing (or within the solar hours before the boundary). | **No** (D1). **Resolved for pre-sunrise / post-sunset entry** (EC daylight horizon build); post-sunrise residual documented (plan review #2 F6). |
| INV-8 | Reserve writes do not alternate between two values on consecutive ticks with unchanged SOC. | **No** — 8 ↔ 10 with D1 (inferred from code; confirm in D0 data). |
| INV-9 | When the house cannot reach its pre-boundary goal for lack of data, the operator is told before the boundary. | **No** (D3). |

---

## 3. Divergence list

| ID | What | Evidence | Who should own the fix |
|---|---|---|---|
| **D1** | **10-01 rung_1 ⇄ WAIT ping-pong.** Rung 1 ("EV pause redirects solar") fires at night because (a) the rate horizon is bounded by *today's* sunset, not by daylight actually left before the boundary, and (b) the no-solar guard reads forecast surplus, not current production. Entry adds the EV load at +29 %/h for ~10 h → 100 %; with the EV paused the latched check fails → rung 2 WAIT → release → EV on → repeat. Side effect: reserve alternates 8/10. | `energy_battery.py:2992-3003`, `:3139`, `:3157-3195`, `:3106-3113`; `energy.py:6779-6782`, `:6881-6886`; `energy_pool.py:2940-3016`. D0 §9.1: 13/13 rung-1 entries with EV ≥ 11.6 kW, 34/34 WAIT with EV off. | EC-RUNG1-WAIT-EV-PINGPONG-1 (Tier 2+) |
| **D2** | Breaker check ignores the local CFG witness. | `energy.py:6730-6764`; D0 §9.3 P1-2 row. | New card or fold into D1/D4 card |
| **D3** | 10-02 attain blind-hold: holds silently for 99 min with the battery at ~10 % before the 17:00 boundary; operator charged by hand. No safe automatic fix today (cloud frozen; MQTT witness down since 09-30). | `energy_battery.py:5086-5215`; D0 §9.1, §9.2. | Page-the-operator is the cheap fix; real fix = restore a moving SOC witness (ENVOY-FLAKINESS / MQTT stream) |
| **D4** | Blind branch publishes `charge_from_grid=False`; breaker intent does not OR in `_last_charge_from_grid_command`. | `energy_battery.py:5214`; `energy.py:6764`; compare `:5152` which does use the last command. | EC-DEGRADED-DATA-POLICY-1 P1-2/P1-3 (re-scoped) |
| **D5** | Cloud-only trust disarms the blind-window guard: a recent cloud reserve verify ⇒ guard never engages even though SOC is unknown. | `energy_pool.py:684-688`; manual §2.5a calls it intentional. | Operator decision (Q4) |
| **D6** | Blind release: a single sighted tick drains the guard's pause set and resets debounce; arbitrage release has no blind check. | `energy_pool.py:703-747`, `:1520-1522`, `:2940-2990`. | P1-4 (cheap, ride-along) |
| **D7** | **Battery at ~8 % through the 10-01 off-peak.** By the WAIT design this is intended (battery serves the house overnight, CHARGE refills inside the window; flat off-peak rate). But on 10-01 the rung-1 ticks closed the gate, so the CHARGE phase could not run on those ticks either; whether the 14:00-17:00 window was reached cleanly is unverified. Comment at `:5756` ("import cheap grid") is false: nothing imports. | `energy_battery.py:3510-3534`, `:5756-5774`, `:3258-3261`. | Confirm with D0 data (see Q2); fix comment in D1 cycle |

---

## 4. Open questions for the operator

1. **Q1 — Rung 1 at night (D1).** Should rung 1 ("pause EVs so solar fills the battery") be allowed only while the sun is up and producing? Proposed: yes, and once rung 1 releases, it may not re-enter for N minutes (INV-1). What is N (proposed 60)? **RESOLVED (night half): rate horizon daylight-gated. Cooldown N not built (marginal-benefit pushback, plan D3); INV-1 trip-wire carded as detection.**
2. **Q2 — Overnight floor on a poor-day arbitrage night (D7).** WAIT lets the battery sit near 8-10 % until the charge window. Off-peak rate is flat, so charging at 02:00 costs the same as at 14:00, but charging early spends grid on energy tomorrow's (weak) solar might have supplied. Do you want (a) today's behaviour, (b) a minimum overnight floor on poor days (e.g. the poor drain target, 30 %), or (c) charge earlier when the Envoy is flaky? **RESOLVED: operator ruling (a)-variant 2026-10-03 = (b) floor at the poor drain target, park only; refill-to-floor is attain's decision.**
3. **Q3 — Lean on arbitrage more.** Lead time is a knob (live 180, default 360). Do you want a longer window on poor days, or should attain (not just arbitrage) charge on "moderate" days too? Today the arbitrage gate opens only on poor/very_poor (`energy_battery.py:3226`).
4. **Q4 — Cloud reserve verify vs blind SOC (D5).** Should a recent cloud reserve verification still disarm the EV blind guard? Proposed: no — guard on unknown SOC regardless; accept more deferrals on Envoy outages (22.7/day this week).
5. **Q5 — Blind before the boundary (D3).** With no trustworthy SOC, what should happen at, say, T-90 min before a high-rate boundary: (a) hold and page you (proposed), (b) blind grid-charge for a capped time with EVs paused, or (c) hold silently (today)?
6. **Q6 — Winter morning boundary.** Winter adds a 05:00-09:00 mid-peak. Should overnight arbitrage target 05:00 (today's code) or skip the morning window and target 17:00?
7. **Q7 — Local vs cloud CFG witness (D2).** Confirm: any witness reading CFG on ⇒ chargers stay off. (Proposed yes.)
8. **Q8 — Flap trip-wire.** Add a code trip-wire (NM page) when any charger toggles more than 2×/hour from strategy? (Proposed yes; no-soak rule.)
