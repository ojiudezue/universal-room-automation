# Review A — local correctness — HVAC-PRECOOL-STANDDOWN-WHEN-COOL-1

Branch `feature/precool-standdown` @ `584fb91a` (tag `pre-review-precool-standdown`). Diff base:
`git merge-base develop 584fb91a` = `9701c938` (develop has moved to `4e3ca3bc`; three-dot diff used).
Plan `docs/planning/PLANNING_hvac_precool_standdown_and_seasons.md` rev 4. Framing A: arithmetic, clamps,
None handling, mode table, row rule, counters, knob ladder, test realism. Lifecycle and completeness belong to B / D.

Read first, completely: `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` (743 lines incl. §9e and §10 C1-C39).
No §10 claim is re-asserted here.

**Verdict: FIX-REQUIRED (one MEDIUM, small fix).**

## Findings

| # | Sev | Site | Finding | Bug class |
|---|---|---|---|---|
| A-M1 | MEDIUM | `hvac_predict.py:1610` (row rule) + `:1723` (heat compare) | A false `pre_arrival_standdown` row when the cool leg is deferred or fails. The heat leg runs whenever no borrow is live after the cool call. That includes cool `deferred` (comfort-delay gate, the CM releases the row) and cool `failed`. The heat compare `T >= effective_low - margin` then reports `standdown` for any T above the band, and the row rule logs it. **Repro (run in suite, scratch test):** SUMMER Home 77/70, live 60/82, floor 74, T 77, `comfort_delay_active` True → cool `deferred`, heat `standdown`, one row `{legs: {cool: deferred, heat: standdown}, T: 77, effective_low: 72, effective_high: 75}`, description "T 77 inside 72-75" (false). The membership flag is then set, so no truthful row follows for that membership, and `prearrival_standdowns_today` counts it. This is display only, but it is exactly the parked D5 revival trigger ("a stand-down row whose recorder T was outside the band"), so the oracle reports a false positive. The same shape occurs with `PRE_ARRIVAL_PRECOOL_STANDDOWN_ENABLED=False` plus a deferred cool write. **Fix:** in the heat leg, report `standdown` only when `effective_low - margin <= T <= effective_high + margin`; return e.g. `above_band` otherwise. Alternatively, have the row rule require `cool_out not in {deferred, failed, interrupted}`. Add a row-rule case (`cool_deferred_no_row`). | #63 coincidental equality (heat "at/above low" conflated with "inside band") |
| A-L1 | LOW | `hvac_predict.py:1387-1398` | The D3 cool mode check is not under `PRE_ARRIVAL_PRECOOL_STANDDOWN_ENABLED`. Plan §6 says "False = today's cool behaviour exactly" and INV-NOOP says "with both new kill consts False … equals today's". With the const False and mode `heat`, today writes; the branch skips `mode_excludes_cool`. There is zero reach on the 3 Carrier zones (B1 holds `heat_cool`). Either gate D3 under the const or reword §6/INV-NOOP. | kill-switch incompleteness |
| A-L2 | LOW | `hvac_predict.py:1698-1701` vs `:1411-1413` | The heat leg's `effective_high` is a hand copy of the cool leg's floor formula. It is equal today (verified, see table), but a later change to one copy leaves the `band_inverted` compare stale. Factor into one helper. | #53 shape (two derivations) |
| A-L3 | LOW | `hvac_predict.py:~764-772` | `_standdown_logged` / `_band_inverted_logged` are discharged only when the pass reaches the pre-arrival block. The master-OFF (`:~602`) and ZI-off (`:~733`) early returns skip it, so a leave-and-re-enter while either is off keeps the old flag (one row fewer). Accept; display only. | observation gating |

Cleared (holds because):
- **Cool compare placement** `:1418-1435`: after `setpoint_skip`, before `begin_excursion`. No orphan row is created (test asserts `db.events == [] and db.state == {}`).
- **None/non-numeric T** `_num_or_none` `:74-84`: covers None, bool, str, NaN. The cool leg fails open (`no_temp`, then it writes). The heat leg fails closed at `:1716-1721` before any begin.
- **Unreadable mode**: `""` is the `ZoneState.hvac_mode` default (`hvac_zones.py:138`). `unavailable` never lands, because the update returns early (`hvac_zones.py:702-703`). Cool fails open and heat fails closed. Both are tested.
- **Heat deadband**: `effective_low <= live_high - 2` by construction. The write sends `(effective_low, live_high)`, and the funnel's own guards still apply.
- **INV-ONE-LEG arithmetic**: when the band is not inverted, cool writes only for T > eff_high (or None), and heat writes only for numeric T < eff_low <= eff_high. These are disjoint. When the band is inverted, heat is skipped. The `is_borrow_active` re-read covers a landed cool begin.
- **Snapshot**: `pre_target_low, pre_target_high = base_heat, base_cool` matches the cool leg's `_baseline_pair` order `(heat, cool)` (test pins `(70, 72)`).
- **Counters**: `DailyCounter.__int__` exists and the object is truthy, so `int(x or 0)` in `sensor.py:14516-14519` is safe. Lazy rollover happens on `increment`/`value`, and the explicit hinge is at `hvac.py:2332-2341`. `precool_writes_today` counts only `reason == "pre_arrival"`.
- **Knob ladder**: all new numbers are rung-1 consts in `hvac_const.py:506-542` with a reason each, and the kill semantics are stated.
- **Tests**: `test_hvac_prearrival_conditioning.py` drives the real predictor, excursion primitive and funnel through `_w1b_harness`, with hand-typed literal oracles. None of them is a source grep (except the §4.3 AST lint, which is the plan's intended lint). Targeted run: 267 passed (this file plus `test_hc_precool_oc_observability`, `w1w2_finish_part_a/b`).

## Truth table — band arithmetic (effective_low = min(H+2, C, live_high−2); effective_high = max(C−2, max(floor, live_low+2)))

| Case | Home H/C | floor | live low/high | eff_low | eff_high | Band | Code result |
|---|---|---|---|---|---|---|---|
| Live summer | 70/76 | 74 | 60/82 | 72 | 74 | 72 ≤ T ≤ 74 | T 75 cool 74, T 73 row, T 71 heat 72 |
| Live shoulder/winter | 70/77 | 74 | 60/78 | 72 | 75 | 72 ≤ T ≤ 75 | as above |
| Defaults winter | 70/72 | 74 | 60/78 | 72 | 74 | 72–74 | tested (`one_standdown_row`) |
| Floor 65 extreme | 70/72 | 65 | 60/78 | 72 | 70 | inverted | heat `band_inverted`; cool writes 70 at T 71 (pre-existing, carded) |
| Floor 65, live 70/77 | 70/77 | 65 | 60/78 | 72 | 75 | 72–75 | not inverted |
| Floor 80 extreme | 70/77 | 80 | 60/78 | 72 | 80 | cool `setpoint_skip` (80 ≥ 78); heat writes for T < 72 | holds |
| Gap 1 F | 72/73 | 74 | 60/78 | 73 | 74 | 73–74 | tested (`narrow_gap`, eff_low 73) |
| Deadband cap | 72/76 | 74 | 60/73 | 71 | 74 | — | tested (71) |
| Zone in Home | 70/76 | 74 | 70/76 | 72 | 74 | heat 72 > live 70 writes | intended mirror |
| Margin 1 | — | — | — | — | — | widens both sides | cool tested; heat symmetric by code |

## Summary

| Sev | Found | Fix required |
|---|---|---|
| CRITICAL | 0 | — |
| HIGH | 0 | — |
| MEDIUM | 1 | A-M1 |
| LOW | 3 | A-L1, A-L2 (fix in-cycle, small); A-L3 accept |

Bug-class frequency: #63 ×1, #53-shape ×1, kill-switch incompleteness ×1, observation gating ×1.
QUALITY_CONTEXT candidate: none new. A-M1 is a #63 instance ("at or above the heat target" was treated as equal to "inside the band").

## Fix-up disposition (2026-11-12)

A-M1 FIXED (heat leg returns `above_band` for T > effective_high + margin; `test_cool_deferred_or_failed_no_standdown_row` x3 + `test_heat_leg_band_edges`; mutation RED). A-L1 FIXED (cool mode check gated on `PRE_ARRIVAL_PRECOOL_STANDDOWN_ENABLED`; `test_cool_mode_check_off_with_backout`). A-L2 FIXED (`_precool_effective_high`, one derivation; `test_heat_band_tracks_cool_floor`). A-L3 ACCEPTED (display only; at most one row fewer when a leave-and-re-enter happens while master/ZI is off).
