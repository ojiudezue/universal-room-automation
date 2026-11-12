# v5.108.13 — EV rung-1 redirect cap; lock suspicious-arrival hold

Card: `EV-ARBITRAGE-RUNG1-WAIT-OSCILLATION-1` (Tier 3). Plan: `docs/planning/PLANNING_ev_rung1_redirect_cap.md` (rev 2).
Reviews: A, B, C (mutation), D (adversarial completeness) all SHIP (records under docs/reviews/code-review/v_ev_rung1_redirect_cap_review_*.md). Orchestrator verify: cap reverted to full EV credit -> 9 RED; hold boundary >= -> > -> 3 RED; restored clean. Full serial suite on 9f193681: 0 failed / 20667 passed. Combined release suite on 01e7071a: 0 failed / 20722 passed (first combined run had 7 new names: a pinned suppress-key count and 5 order-dependent real-HA setup errors; both fixed in tests only, 01e7071a).

Accepted residuals: one false pause/resume possible at an EV start when net_power is up to 180 s old (review D-LOW-1); while the SOC reading is missing the hold cannot flush, but night release, solar collapse, counterfactual exit and forecast-closed stay ungated (review B1).

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


# Part 2 — Lock suspicious-arrival hold

Card: GARAGE-REMOTE-LOCKOUT-SCHEDULE-1 (residual). Plan: docs/planning/PLANNING_lock_suspicious_arrival_hold.md rev2. Reviews: A SHIP, B FIX-REQUIRED (away-lock dwell not re-armed after a cancelled blip; fixed 607f06b3), C FIX-REQUIRED (15 untested sites; 15 anchoring tests added 609e1607, re-drill 75 RED / 6 equivalent). Orchestrator verify: stale comparison neutered -> 29 RED, restored clean.

Card: GARAGE-REMOTE-LOCKOUT-SCHEDULE-1 residual. Plan: `docs/planning/PLANNING_lock_suspicious_arrival_hold.md` rev 2 (plan review applied, §12). Branch `feature/lock-suspicious-arrival-hold`. Version not assigned (draft; rename on deploy).

## Why

In 7 days (11-05..11-12) Oji's person entity read `not_home -> home` 78 times for under 1.2 s. Each time the phone tracker went `unavailable`, HA's person fell back to a second GPS device (the iPad) whose `home` was hours old, then the phone came back. 49 of those blips also jumped the proximity distance to 0 ft. With the garage lockout or the away lock on, every blip would have unlocked. The 11-11 tracker trim (one GPS device per person) stops the mechanism in this house today; this change is the guard for the day a second GPS device is added, and for other installs.

## What changed

- **One rule** (`arrival_edges.stale_source_arrival`): an arrival is suspicious when the person's `source` tracker did not itself change at the edge (`person.last_changed - source.last_changed > 10 s`, or no source). Real arrivals measured at most 0.0003 s; blips at least 4,119 s. 0 of 40 real arrivals would be held.
- **Hold, then decide** (`security_lock_regime.py`). A suspicious person edge waits `number.ura_garage_lockout_arrival_hold` seconds (default 5, 0 = off). If the person reverts inside the hold, the edge and its revert cancel with no state change. If the person still reads the held state at the end, the original edge is replayed through the normal path (time stamps carry the edge's own time). Attribute-only updates during the hold change nothing.
- **Same hold on every unlock path that a blip feeds:** the person edge (garage release, approach zone, away lock, face-corroboration stamp), the `SIGNAL_PERSON_ARRIVING` path (geofence / ble / camera_face and the held-face re-check), and the proximity crossing (re-read at the end of the hold).
- **Never held:** edges whose source changed at the edge (every real arrival), edges in the first 600 s after the lock regime starts (boot), and a proximity crossing while the person is `not_home` (a real approach).
- **Away lock:** if its 300 s all-away dwell comes due during a hold, it waits for the hold to end (plus 0.1 s) instead of spending its one attempt.
- **New knob:** `number.ura_garage_lockout_arrival_hold` on the Security Coordinator device, 0-60 s, default 5, 0 = previous behaviour exactly. Applies to the garage lockout and the away lock. In both reload-suppress lists, so changing it never reloads the CM.
- **Diagnostics:** lock-regime snapshot attributes `lock_regime_arrival_holds`, `lock_regime_arrival_signal_held`, `lock_regime_arrival_hold_confirms`, `lock_regime_held_edges`.

Not changed: house-state releases, the boot recheck, the 15-minute blip rule, face-corroboration rules, other consumers of the same blips (expected-arrival sanction, HVAC pre-arrival, music following; follow-up card per plan §7).

## Residuals (plan §9)

- A stale-source `home` that lasts longer than the hold releases at the end of the hold (develop behaviour, H seconds later).
- Holds are not persisted; a restart or lock-regime reload during a hold drops it.
- A proximity sensor that does not resolve to a person bypasses the proximity gate (develop behaviour).
- A dropped arriving signal is not replayed if the hold is cancelled; the next real edge carries the arrival.

## Tests

- `test_arrival_edges.py` (6): the predicate, incl. `last_changed` vs `last_updated`.
- `test_lock_arrival_hold.py` (24): blip pair no-op (garage and away stamp), fresh source releases in the same callback, confirm at H with the edge timestamp, cancel by another value, teardown, approach zone, attribute-only event keeps the hold, away dwell deferral, boot window exempt, config re-read at confirm, synthetic proximity hold on an already-home person, P2 gate (incl. signal before the state listener, face not corroborated by a blip, held-face re-check), P5 gate, knob round trip / live read / suppress lists, snapshot counters.
- `test_lock_arrival_hold_real_ha.py` (3): real HA core and real `person` component: 2-GPS dropout held and dropped, attribute-only refresh stays held, BLE-only arrival instant.
- `test_lock_arrival_hold_replay.py` (3): the committed probe fixture (118 edges, 52 crossings; `scripts/probes/lock_arrival_edge_probe.py`) replayed through the real regime: 40/40 real edges and 3/3 real crossings release in their own callback, 78/78 blips and 49/49 blip crossings never unlock, final state equals the blips-removed run; H = 0 equals the develop golden (`fixtures/lock_arrival_hold_develop_golden.json`, generated from develop b7e4289e).
- 17 per-site mutation drills (the plan's 12 plus 5 call-neuter drills), each RED on its named test.

## Live validation (to fill after deploy)

Prospective:
- `number.ura_garage_lockout_arrival_hold` exists on the Security Coordinator device and reads 5.
- Lock-regime snapshot attributes show `lock_regime_arrival_holds` 0 and `lock_regime_held_edges` [] after a resident's real arrival outside the first 10 minutes after a restart. A non-zero count with no second GPS device on any person = a false hold (a real-arrival delay); check `person.*.source` at that edge.
- Organic, once the lockout is on: each resident arrival's lockout release time equals the person edge time (within 1 s) in the activity log.
