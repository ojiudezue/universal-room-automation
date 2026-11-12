# Plan review 1 (Tier 3, completeness): PLANNING_ev_rung1_redirect_cap.md

Card `EV-ARBITRAGE-RUNG1-WAIT-OSCILLATION-1`. Reviewed 2026-11-12 against develop (`b109d3d8`). Read-only.
HVAC/presence state-of-play docs not read: the plan touches neither domain (energy classifier + EV pool only).

**Verdict: REVISE.** 1 HIGH, 2 MEDIUM, 3 LOW. The core design (D1 cap via reused `_effective_import_kw`, D2
timestamp-based flush guard) is sound and the consumer enumeration holds. The plan mis-models how the rate window
fills on rung-1 ticks, so D2's hold length, its acceptance criteria and its mutation boundary are written for a
path production does not take.

## Independent re-enumeration (own greps)

- `_arb_rung1_latch` writers: init `energy_battery.py:936`, set `:4464`, clears `:4312`, `:4323`, `:4369`, `:4383`,
  `:4520`. No other file touches it. Matches plan §2.1.
- `_arb_last_ev_load_pct_per_h`: set `:4468`, cleared `:4311/:4328/:4372/:4385`, read `:4333`. No reader outside the
  classifier. Matches.
- `_tick_ev_load_w`: written `:6448`, read `:4528` only. `ev_load_w` producer `energy_pool.py:3013`; the estimate
  fallback (`energy_pool.py:1150-1155`) fires only when the EVSE status reads "charging", so case 7 is bounded as the
  plan says.
- `_attain_soc_history`: append `:5027` via `_record_attain_sample` called at `:4174` (classifier) and `:6008`
  (`_run_attain_branch`); cleared `:5796` (chunk reset), `energy.py:12125` (toggle). Readers: `:5043` rate,
  consumed at `:4202`, `:5427`, `:6240`.
- `_arbitrage_intent` → `pause_reason`: only EV-switching consumer `energy.py:8179-8195`; breaker ordering
  `:8197-8209`. No change proposed there. INV-4 holds by construction: D1/D2 only change the rung string, and
  `grid_charge_intent` / CHARGE are tested before `arb_intent`.
- `net_power_w` (`:2591`) reads `_read_power_w("net_power")`; the D1 gate reads `_read_fresh_power_w("net_power", …)`
  (`:2493`) on the same entity key, synchronously. The gate cannot disagree with the snapshot on which entity it reads.
- Parked-plan triggers: `AUDIT_waiting_operator_triage_2026_10_17.md:38` (revival trigger, already fired 11-08, consumed
  by this card). `PLANNING_ec_daylight_horizon_and_poor_night_floor.md:287` F6 (post-sunrise residual): **this cycle
  closes it**, which the plan does not say (see F3). `EC-SOC-LADDER-XVALIDATE-1` (inverted sliders flip the gate and
  oscillate the EVs) is adjacent and not fired. Case 15 covers target ≤ drain floor. The solar-led daytime EV card is
  correctly a non-goal.

## Findings

### F1 HIGH: duplicate sampling is the normal case on every rung-0/rung-1 tick, so D2's hold is about 2 ticks, not K (Q4 is load-bearing)

On a rung_1 (or rung_0) tick `_gate_is_open` returns False (`:4530-4538`), so `determine_mode` falls through to
`_run_attain_branch` (`:7221`), which appends `(now, soc)` again at `:6008` after the classifier already did at `:4174`.
`_record_attain_sample` does not dedupe (`:5027`), and the `:4170-4173` comment calling it "idempotent" is wrong.
On rung_2 / gate-open ticks the attain branch does not run, so those ticks add one sample each.

Trace with K=3 (max_len 4), entry at N after rung_2 ticks: after N → `[N-2, N-1, N, N]`. At N+1 the classifier appends
→ `[N-1, N, N, N+1]`, `hist[0] < latched_at` → held; attain appends → `[N, N, N+1, N+1]`. At N+2 the classifier appends →
`[N, N+1, N+1, N+2]`, `hist[0] == latched_at` → **flushed at N+2**, with the rate measured over 10 min.

Consequences:
- D2 acceptance (case 19: "held at N+1 and N+2 … at N+3 the window is `[N..N+3]`") and M5 ("`>=`→`>` goes RED at the
  N+3 boundary") describe the classifier-only drive used by `_seed_rate` / `_set_rate_history`. In the D4
  `determine_mode` path the boundary is N+2. A builder can satisfy every listed D2 test while production behaves
  differently, which is a non-discriminating criterion (Bug Class #62 adjacent).
- INV-3 ("≤ K ticks") still holds, but §1's residual math ("K+1 ticks (20 min)") and §7's value case for D2 are built on
  a 15-min post-pause window that production does not have. The post-flush rate is a 10-min delta of Envoy SOC. On
  11-08 that SOC read as whole percents (30.0 flat). A genuine 5 kW redirect on 40 kWh (+12.5 %/h) gives about +2 %
  over 10 min, so quantisation is material to whether the flushed test escalates.
- The window also covers fewer ticks than documented for attain and rung 0. That is pre-existing, as the plan says.

**Required:** the plan must decide Q4 rather than defer it, using one of:
(a) Accept a hold of about 2 ticks. Restate D2/INV-3/§1 residual in terms of the real path (flush when `hist[0] >=
latched_at`, which is N+2 under rung-1 duplicate sampling). Pin the boundary and M5 with a **`determine_mode`-driven**
test, not a classifier-only one. Correct the `:4170` comment in D5.
(b) Dedupe in `_record_attain_sample` (skip when `hist[-1][0] == now`). This is one line, but it widens the attain and
rung-0 rate windows from about 2 ticks to K, a behaviour change on the hardened attain path. It needs its own INV,
tests and fixture churn, so it probably belongs in its own card.
I recommend (a) for this cycle, with (b) carded. In either case the D2 tests must run through `determine_mode`.

### F2 MEDIUM: D2 can delay arbitrage CHARGE when the charge window opens during the hold

Under D2 a latched unflushed tick returns rung_1 where develop returns rung_2. rung_1 keeps the forecast gate closed
(`:4535-4538`), so `_get_arbitrage_decision` (`:7203`) does not run and arbitrage CHARGE cannot fire on that tick. Only
the attain branch can pull grid. If `arbitrage_charge_lead_time` opens the window at N+1, CHARGE is delayed by up to
the hold (about 10 min per F1). On 11-08 the window opened at 14:30 during the loop. The plan's statement that D2
"changes only which rung string the classifier returns" is true, but that string controls the CHARGE path, and §3
does not list this case.
**Required:** add the case (entry at window-open − 5 min, hold through window open) with its expected outcome and a
test. State the bound in INV-2/INV-3: "D2 delays an arbitrage CHARGE by at most the hold." Confirm the attain branch's
behaviour on held ticks, because it can still command grid and will then be paused for breaker, so INV-4 is unaffected.

### F3 MEDIUM: the fixture-churn rule conflicts with an existing documentation test, and the plan omits that it closes F6

`quality/tests/test_ec_daylight_horizon_poor_night_floor.py:568` `test_rung1_post_sunrise_ev_draw_documented` asserts
`rung_1` / `p1 == 100` for a sunrise, about-0-rate, grid-fed EV. That is the F6 residual. With no `net_power` set,
D1 makes it rung_2, which is correct and is the fix. The plan's churn instruction ("add a fresh net_power showing the
EV as solar-fed … no assertion may be weakened") would lead a builder to inject a solar-fed `net_power` at sunrise
to keep `rung_1`, which hides that F6 is closed.
**Required:** name this test explicitly. Convert it to assert rung_2 for the grid-fed sunrise case (F6 closed by the
cap) and, optionally, add a solar-fed variant. Add a D5 write-back that marks F6 resolved in
`PLANNING_ec_daylight_horizon_and_poor_night_floor.md`. Also list the churn set exactly instead of "rung-1 cases in …".
A grep finds rung-1 entry fixtures only in `test_arbitrage_solar_attainability_ladder.py` (`:366`, `:459`, `:497`,
`:1084`, `:1599` plus the pool-label tests), `test_ec_daylight_horizon_poor_night_floor.py`, and
`test_arbitrage_completed_chunk_hold_precedence.py`.

### F4 LOW: D3 stash semantics and the acceptance criterion disagree

`_arb_last_redirectable_kw` is computed at `:4220`, which every tick past the boundary/rate early returns reaches,
including latched ticks (EV paused → 0.0) and rung_0 ticks. The reset "after the cache check" does not run on ticks
where the classifier is never called (peak, forecast-closed, full-hold), so the attribute stays stale across peak.
The AC ("None on ticks that did not reach the entry") is false on both counts.
**Fix:** reset in the `determine_mode` per-tick entry-reset block beside `_arbitrage_intent = None` (`:6424`), and
define the stash precisely: set it at `:4220` and document "0.0 while latched", or set it only at the unlatched entry
evaluation. Live 1 reads the entry tick, so either choice works if it is stated.

### F5 LOW: INV-5 "no output changes" is too broad; the display projection changes

When the cap yields 0, the `ev_load_pct_per_h <= 0` short-circuit (`:4424-4431`) sets `_arb_last_projection_rung1 =
None`, where develop computed a number (day, and at night when unlatched). This only affects display
(`arb_projection_rung1`, `:8387`). The `:7260` reason text is read only on `closed_rung_1`. Scope INV-5 and the
`test_replay_1001_night_identical_to_develop` comparison to rung / intent / gate outcome / EV and battery actions, and
state that `arb_projection_rung1` may move from a number to None.

### F6 LOW: Q2 rationale is slightly off

The plan says Q2 is moot "in WAIT at the drain floor". The rung-1 entry tick is gate-closed (not WAIT), so the
battery can be discharging above the drain floor on that tick. Crediting avoided discharge is still the correct SOC
effect. Fix the sentence; the decision stays the same.

## Open questions

- **Q1 freshness gate:** ACCEPT. It narrows entry only, fails toward not pausing, reuses the wrapper and the constant,
  and leaves `net_power_w` / the breaker path alone (MED-2 respected). Note the wrapper passes `age is None` through,
  which matches the D-OBS convention.
- **Q2 battery-discharge credit:** keep the plan's choice; no solar-only cap (see F6 for the wording fix).
- **Q3 trip-wire paging:** do not flip it in this cycle. Live 3 must then be an explicit anomaly-table query at
  disposition, which the plan already implies. Say it explicitly.
- **Q4 duplicate sampling:** must be decided in-plan (F1), not deferred.

## Checklist

| Item | Result |
|---|---|
| Institutional context / REUSE-BUILD table | PASS (cites verified; one NEW attr justified) |
| Consumer / emission-site enumeration | PASS (zero EV emission sites changed; re-grep matches) |
| INV-1 falsifiable, covers None/stale net power | PASS |
| INV-2/3 falsifiable | PASS as stated, but hold length mis-modelled (F1) and CHARGE delay unstated (F2) |
| INV-4 grid-charge always pauses | PASS (derivation order `energy.py:8185-8195` untouched) |
| INV-5 overnight unchanged | PASS for actions; wording too broad (F5) |
| Knob ladder | PASS (no new number; K and 180 s reused, rungs stated) |
| AC discriminate fix vs other failure | PARTIAL: D1 yes; D2 boundary not discriminating on the real path (F1) |
| Non-goals explicit | PASS |
| Parked-plan triggers | F6 of the daylight-horizon plan is closed by this cycle and not recorded (F3) |

**Must fix before build dispatch:** F1, F2, F3. F4–F6 can be fixed in the same revision.
