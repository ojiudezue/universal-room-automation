# Review A (local correctness) — EV rung-1 redirect cap + post-pause latch hold

Card: EV-ARBITRAGE-RUNG1-WAIT-OSCILLATION-1 (Tier 3). Branch `feature/ev-rung1-redirect-cap` @ `03eb3b70`.
Base `4df802ab` = `git merge-base 03eb3b70 origin/develop` (verified). Plan: `PLANNING_ev_rung1_redirect_cap.md` rev 2.
Framing A only: arithmetic, clamps, units, signs, per-site logic. HVAC/presence docs not applicable (energy only).

Tests run (cycle files + mutated-module neighbour): `test_ev_rung1_redirect_cap.py`,
`test_ec_daylight_horizon_poor_night_floor.py`, `test_arbitrage_solar_attainability_ladder.py` → **447 passed**.

## D1 — credit cap (`energy_battery.py:4235-4250`)

- Units: `ev_load_kw` = W/1000; `_effective_import_kw()[0]` is kW (`:4103`); `%/h = kW / kWh × 100` (`:4250`). Consistent.
- Sign: Envoy raw battery positive = discharging; `battery_power_w` flips (`:2470`) so positive = charging;
  `_effective_import_kw` subtracts only `max(0, batt_w)` (`:4101`). Effective = net − battery charge = H + E − S
  (non-battery import). Redirectable = clamp(E − (H + E − S), 0, E) = clamp(S − H, 0, E): the solar surplus over house load,
  bounded by EV draw. Correct physical meaning.
- Freshness gate: `_read_fresh_power_w("net_power", 180)` (`:4242`); age from `_state_age_s` = wall clock vs
  `last_reported` (`:110`), not tick `now` — correct for production; fixtures stamp wall clock. `max_age <= 0` disables the
  gate (`:2523`) as INV-1 documents. Naive/missing stamp → pass-through (pre-existing helper semantics).
- Two reads (`_read_fresh_power_w` then ungated `net_power_w` inside `_effective_import_kw`) are in one synchronous call → same
  HA state object. Holds.
- Snapshot: `_arb_last_ev_load_pct_per_h = ev_load_pct_per_h` (`:4509`) is the capped credit; counterfactual subtracts it
  (`:4378`, `:4383`, `:4392`). Entry and exit math consistent.

Truth table (E = EV kW, net, batt_w signed charge+, fresh?):

| E | net | batt | fresh | imp | credit | outcome |
|---|---|---|---|---|---|---|
| 0 | any | any | any | — | 0 | rung_2 (`:4464`) |
| 10.1 | 12.9 | 0 | Y | 12.9 | 0 | rung_2, attr 0.0 |
| 7 | −3 | 0 | Y | −3 | 7 (min clamp) | full credit |
| 7 | 2 | 0 | Y | 2 | 5 | partial |
| 10 | 6 | −5 (disch) | Y | 6 | 4 | discharge not subtracted (plan case 9) |
| 7 | 9 | +4 (chg) | Y | 5 | 2 | grid-charge portion excluded |
| 7 | 2 | None/stale | Y | 2 | 5 | conservative (≤ true) |
| 7 | −2 | 0 | N (>180 s) | — | 0 | rung_2 |
| 7 | −2 | 0 | N, max_age 0 | −2 | 7 | carve-out |
| 7 | None | — | — | — | 0 | rung_2 |

## D2 — hold (`:4414-4419`)

- Condition `_latched_at is None or (hist and hist[0][0] >= latched_at)`; only the `projected_rung0 < exit_band` escalation is
  gated. Night release (`:4337-4341`), solar collapse (`:4351`), counterfactual → rung_0 (`:4395`) precede it and are ungated.
- `>=` is right: the entry tick's sample is pre-dispatch, so deltas from it are all post-pause.
- Sole setter of `_arb_rung1_latch = True` is `:4504`, which stamps `latched_at` (`:4505`); stale `latched_at` after release is
  unread (only read under latch) and overwritten on next entry. `None` → legacy behaviour.
- Same `now` feeds both samplers (`:4189`, `:6049`), so timestamp comparisons are like-for-like. History clears
  (`:5837`, `energy.py:12125`) are followed by the classifier append of `now` → window post-entry; `rate is None` returns
  rung_2 earlier (`:4218`, pre-existing, latch not cleared there — unchanged by this diff).
- Hold bounded: K+1 = 4 samples, ≥1 append/tick → flush within ≤ 3 ticks (prod 1 held tick).

## D3 — reset/stamp

Entry-reset at `determine_mode` top (`:6466`); stamp only on the unlatched entry path after the no-solar guard (`:4460`),
before the `<= 0` short-circuit so grid-fed shows 0.0. Rung cache hit (`:4179`) returns before stamping, but the cache hit only
occurs on the second same-tick call after the first already stamped — value survives. Attr `:8435`. Display only. Holds.

## Test changes in `test_ec_daylight_horizon_poor_night_floor.py`

- `solar_fed_net=True` opt-in (fresh net 0 W → credit = EV, pre-cap arithmetic) added to projection/horizon tests; their
  numeric assertions are unchanged. Not weakened.
- `test_rung1_post_sunrise_ev_draw_documented` → `..._grid_fed_ev_no_entry` (asserts rung_2, latch False, attr 0.0, p1 None)
  + `..._solar_fed_ev_enters` keeps the original rung_1 / p1 = 100 assertions. Strengthened.
- 10-01 replay: production replay assertions kept; the `p1 == p0` check is vacuous on the capped run (p1 None) but the
  same assertions are run on a `legacy_cap=True` replay that keeps the `>= 10` discriminating EV ticks, and the legacy
  flap anchor still requires `>= 10` rung_1 ticks. Not weakened. `_legacy_cap` uses frame-name sniffing (test-only, LOW).

## Builder deviations vs plan

The build report was not available to this reviewer; evaluated from the diff. (1) Plan §D1 predicted 8 tests in the
daylight file would go red; only the `_classify`-entry tests needed the opt-in — tests that set the latch directly stayed
green, as the plan's own last bullet allowed. (2) 10-01 replay needed `legacy_cap` because 10-01 EVs were grid-fed — a
correct reading; the plan did not foresee that the cap alone also kills that flap. (3) Stamp placed after the no-solar
guard: matches plan text "immediately before `:4424`". (4) Sampler comment corrected to "not idempotent" as D5 asked.
None alter semantics.

## Findings

| SEV | Site | Finding |
|---|---|---|
| LOW | `energy_battery.py:4247` | Credit not capped by battery charge-rate headroom when exporting (E credited fully even if battery already at max charge). Pre-existing modelling; overstates only in high-export cases where rung_0 usually already passes. No action. |
| LOW | `test_ec_daylight_horizon_poor_night_floor.py` `_legacy_cap` | `sys._getframe(1).f_code.co_name` sniffing is brittle to renames; fails loud (replay anchor would go red), so acceptable. |

No CRITICAL/HIGH/MEDIUM.

## Verdict: SHIP
