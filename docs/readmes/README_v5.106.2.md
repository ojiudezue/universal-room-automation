# v5.106.2 — Inclement leftovers: TOU rate ranking, Envoy-blind outage counter, retired threat-list removal

**Cards:** EC-STORM-FULLHOLD-DEGRADED-ENVOY-AVAILABLE-1, EC-BLIND-DEESCALATE-TOP-RATE-1 (Stage D residual),
EC-INCLEMENT-HARDENING-1 (retired threat-list tail). **Tier:** 2-DB, three framing-disjoint reviews.
**Plan:** `docs/planning/PLANNING_ec_inclement_leftovers_2026_11.md` rev 2, after plan review 1.
**Reviews:** `docs/reviews/code-review/ec_inclement_leftovers_review_{A,B,C}.md`.
**Threshold probe (item 3, no code):** `docs/planning/AUDIT_winter_forecast_confirm_thresholds_2026_11.md`.
It keeps 50 % / 1.0 mm: all 5 freeze/ice outage windows confirm, and lower values add only false confirms.

## Why
On 2026-11-08 the operator asked for the inclement-weather leftovers to be fixed. The cards were stale: most of
their scope had already shipped. Three real gaps remained:

1. **Envoy outage counter reset.** A battery charge already in progress can go into "hold current" while the
   Envoy is blind, for example after a reboot. That path reported `envoy_available: True`. Each such tick
   reset the Envoy outage counter, which delayed or suppressed the "Envoy Offline" page.
2. **Literal period names.** Several decisions check the literal text "peak" or "mid_peak" where they mean
   "priced above the cheapest rate". The operator ruled on 10-16 that this text matching should go
   ("this text matching is nonsense").
3. **Leftover threat-list code.** The code for the retired free-text threat list stayed in place after the
   storm cycle.

## What changed
- **Envoy availability.** The attain HOLD-CURRENT decision reports Envoy availability by the same rule as every
  other decision. A guard test requires every decision dict to carry `envoy_available`, and never as a literal
  `True`.
- **Rate ranking.** New pure helpers in `energy_tou.py`: `above_bottom_rate(tou, season, period)` and
  `season_at(tou, when)`.
  - The helper ranks the period the site was given, never the clock period.
  - If the rank can't be read, it falls back to the old literal check.
  - 8 sites now route through it: energy situation, load shedding, arbitrage savings, EVSE pause, plug pause,
    the two HVAC intent anchors, and the situation next-boundary text.
  - The plug controller now receives the TOU engine.
  - Every remaining named-period literal is pinned per `file::Class.func`, and a test fails on any new one.
  - A tariff whose rates are not ordered off-peak ≤ mid-peak ≤ peak now logs a warning. Nothing else changes.
  - On the live PEC tariff all 8 sites give identical results for every hour of 2026 (8,760 checked).
- **Threat-list removal.** Removed the setting name and its default list, the repair check, its repair-issue
  text, the leftover test arguments, and the user-manual lines.
  - The severity ordering stays, because it is still live.
  - The two old keys still stored in the options stay untouched. They are inert, and a test proves decisions
    are identical with and without them.

## Knobs
None new. The rate ranking comes from the existing `tou_rates.json`. The forecast confirm thresholds are
unchanged (rung 1).

## Tests
- **New test files:** `test_ec_inclement_leftovers_envoy.py`, `test_ec_inclement_leftovers_legacy_keys.py`,
  `test_ec_inclement_leftovers_period_rank.py`, plus the `fixtures/tou_rates_live_pec_2026.json` fixture.
- **Review C:** about 31 single-site source mutations. The one site that stayed green, the HVAC current-period
  season, now has a test that goes red.
- **Full suite:** name-diff against the baseline shows 0 NEW and 0 GONE failures. The isolated run of the
  affected files is also clean.

## Live validation (after restart)
- `sensor.ura_energy_coordinator_battery_strategy`: mode, reason and the `inclement_*` attributes match the
  pre-deploy snapshot for the same TOU period and alert state. `envoy_available` is true and the Envoy outage
  count is 0 with a healthy Envoy. The degraded Envoy-blind case can't be triggered on demand, so it is proven
  in-suite only.
- No new repairs issue, and no `inclement` / `energy_tou` WARNING or ERROR in the first 10 minutes. On PEC,
  no rate-order warning is expected.
- The CM options still carry the two old keys, untouched.
- Plug and EVSE pause, load shedding and the energy situation behave exactly as before. This is a
  no-regression check only: on PEC the migration is identical by design, and the proof is in the suite.

## Validated 2026-11-08 (post-restart ~13:50 CST, house `away`)
| Criterion | Result | Evidence |
|---|---|---|
| v5.106.2 running | PASS | `update.universal_room_automation_update` installed_version v5.106.2 |
| Battery strategy unchanged vs pre-deploy snapshot (same TOU period: off-peak before the 17:00 mid_peak) | PASS | `sensor.ura_energy_coordinator_battery_strategy` = self_consumption. mode, reason ("Arbitrage WAIT — holding drain floor 30%"), envoy_available, tou_top_rate, inclement_tier/source/hold_depth/reason/reserve_floor/selection, arbitrage_phase and next_high_rate_transition_period are all identical. Only `next_decision_boundary.in_minutes` moved (300 to 240, elapsed time) |
| Envoy availability with a healthy Envoy | PASS | `envoy_available` true. `sensor.ura_energy_coordinator_envoy_status` = online, offline_count_today 0, envoy_degraded false. The degraded Envoy-blind case is proven in-suite only, because it can't be triggered on demand |
| No new repairs issue | PASS | `repairs/list_issues`: no universal_room_automation issues; `inclement_legacy_threat_list_retired` absent |
| No inclement / energy_tou WARNING or ERROR, no rate-order warning | PASS | system_log, current boot: 0 entries matching `inclement`. `energy` matches are pre-existing room energy-sensor warnings plus an enphase_realtime statistics notice |
| CM options still carry the two old keys | PASS (by construction) | No code path writes options; INV-L1 test proves decisions are identical with or without the keys |
| Pause / shed / situation unchanged (no-regression only) | AS EXPECTED | Proof is the 8,760-hour helper sweep in-suite; live only shows no change in behaviour |
