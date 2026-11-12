# DRAFT README — EV rung-1 redirect cap + post-pause latch hold

Card: `EV-ARBITRAGE-RUNG1-WAIT-OSCILLATION-1` (Tier 3). Plan: `docs/planning/PLANNING_ev_rung1_redirect_cap.md` (rev 2).
Version: TBD at ship (PATCH bump). Rename to `README_v<version>.md` before `deploy.sh`.

## What changed

- **Rung-1 redirect credit is capped (D1).** Rung 1 ("pause the EVs so their solar goes to the battery") used to
  credit the EV's entire draw as solar. It now credits only the part not covered by grid import:
  `clamp(ev_kW − (net_power − battery_charge), 0, ev_kW)`, and only with a fresh `net_power`
  (≤ `DEFAULT_NET_POWER_MAX_AGE_S` = 180 s; `<= 0` disables that gate). A grid-fed EV earns 0 and rung 1 does not
  start. This removes the 11-08 14:03-14:33 CST daylight loop (2 garage chargers off→on→off every 10 min) and the
  daylight-horizon plan's F6 sunrise residual.
- **Rung-1 escalation is held until the rate window is post-pause (D2).** After rung 1 pauses the EVs, its
  "projection fell below exit, escalate to rung 2" check waits until the oldest sample in the charge-rate window is at or
  after the pause tick (about one 5-min tick on the live path). Night release, solar collapse and the counterfactual
  exit are not held. Side effect: an arbitrage CHARGE whose window opens during the hold starts one tick later; any grid
  pull on the held tick is still paused as `breaker`.
- **New attribute (D3):** `sensor.ura_energy_coordinator_battery_strategy` → `arb_rung1_redirectable_kw` (float on ticks
  that evaluated rung-1 entry, 0.0 = grid-fed; `None` otherwise). `arb_projection_rung1` now reads `None` on cap-zero
  ticks where it used to show a number (display only).
- No change to `energy.py` (pause-reason / breaker ordering), `energy_pool.py`, `net_power_w`, or
  `_effective_import_kw`. No new knob.

## Live acceptance criteria (prospective — replace with a `Validated <date>` table after restart)

- **Live 1 (binary, disposition query):** `ura_activity_log` `energy_pool` `charger_off` rows with `pause_owners`
  containing `arbitrage` in daylight where the strategy row at that tick has `arbitrage_intent = redirect`. PASS = each
  has `arb_rung1_redirectable_kw > 0` at its entry tick and recorder `net_power` < EV power, or there are no such rows.
  FAIL = a redirect pause with redirectable 0/None or net ≥ EV draw.
- **Live 2:** `arb_rung1_redirectable_kw` is present on the battery-strategy sensor after restart (None or float), no
  AttributeError / traceback in the logs.
- **Live 3 (no paging):** at disposition, query the URA anomaly table for `ev_toggle_tripwire` rows with an arbitrage
  owner since deploy. PASS = 0 rows. Otherwise classify each: stated residual (redirectable > 0 at entry, period ≥ 3
  ticks) or a cap leak (redirectable 0 or grid-fed).
- **Live 4 (overnight):** first poor-forecast night after deploy: no `redirect` pause rows 01:00-07:00.
- Disposition: first poor-forecast daytime with an EV drawing, or about 1 week; if the precondition does not recur,
  close as "met by replay" with the Live 3 query as the standing guard.

## Tests

`quality/tests/test_ev_rung1_redirect_cap.py` (new, 41 tests) + conversions in
`quality/tests/test_ec_daylight_horizon_poor_night_floor.py` (see build report for the per-test list).
