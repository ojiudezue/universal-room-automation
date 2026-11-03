# Review: HVAC-KWH-AVOIDED-TOTAL-NOT-MONOTONIC-1 (branch `fix/hvac-kwh-avoided-restart-zero` @ 1d87a8c48)

Tier 1, single review, framing A (local correctness + HA statistics semantics + blast radius).
Diff base: `git diff develop...fix/hvac-kwh-avoided-restart-zero`. HVAC STATE_OF_PLAY read first; no §10 claim re-asserted.

**Verdict: SHIP.** No CRITICAL / HIGH / MEDIUM. Two LOWs, neither blocking.

## HA statistics semantics (verified in `.venv-ha` HA source, `homeassistant/components/sensor/`)

| Question | Answer | Evidence |
|---|---|---|
| Is an `unknown` state counted as a reset on TOTAL_INCREASING / TOTAL? | No. Non-float states are dropped before the sum loop; the next numeric state is compared with the last numeric one (`new_state` carries over). | `recorder.py:217-231` (`_entity_history_to_float_and_state`), sum loop `:686-768` |
| TOTAL_INCREASING reset rule | reset when `fstate < 0.9 * previous`; a 0-10 % dip only warns. So the old seeded 0 after restart was a full reset, re-adding the whole value. | `recorder.py:452-470`, `:741-760` |
| TOTAL without `last_reset` | no reset detection; the sum follows the net change, a decrease is a negative delta. | `recorder.py:702-740` (reset only on `last_reset` change or first state) |
| TOTAL_INCREASING -> TOTAL on an entity with existing stats | Handled silently: both map to `{"sum"}` (`recorder.py:75-76`); the only state-class issue is `state_class_removed` (class None, `:860-867`). No crash, no Repair. The existing junk sum (~212,345 kWh) STAYS until the operator fixes it in Developer Tools -> Statistics (card's DO step). | `recorder.py:75-76`, `:848-870` |
| TOTAL valid for ENERGY | yes `{TOTAL, TOTAL_INCREASING}`; MONETARY allows only TOTAL (the $ family already was TOTAL). | `const.py:775-778`, `:788` |

Note vs. the brief: no statistics issue is raised for the class change; the fix is manual.

## Findings

| # | Sev | Site | Finding | Class |
|---|---|---|---|---|
| A-L1 | LOW | `hvac_override.py:5016-5035` (gates 0a/0b/1 return before `_refresh_impact_cache` at `:5217`); also the refresh `except` at `:2170` | With AC Nudge OFF, both nudge+reset OFF, or ramp master OFF at boot, or a refresh that raises every time, the family reads `unknown` forever (was a seeded 0). Unknown is the honest value for nudges/resets/today/cycle (0 was a fabrication, though usually coincidentally right). It is arguably UNDER-informative for the 30-day kWh / $ sensors, whose DB history stays real while the feature is off. Live config has all three ON (§8), so no live change. Recommendation: accept as is; if wanted later, call `_refresh_impact_cache()` at the three early returns (3 lines; still bounded by the 5-min tick) - not required for this card. | #53-adjacent (computed-but-not-refreshed), display only |
| A-L2 | LOW | `/Users/okosisi/ha-config/.storage/lovelace.ura_v8` markdown card | Column header "Lifetime" over `..._78_ac_ramp_savings_lifetime` and `..._ac_kwh_avoided_total` now contradicts the "(30 days)" names. Templates use `|float(0)` so unknown renders 0 - no breakage. Operator-side dashboard text; card it or fix with the next dashboard pass. | doc drift |

## Questions answered

1. **HA semantics:** see table. Unknown is skipped, never a reset; class change handled without crash or Repair; junk sum needs the manual statistics fix.
2. **Feature-off -> unknown forever:** A-L1. Not a regression for any decision consumer; display only.
3. **Other readers of native_value / cache:** none do arithmetic. `_impact_cache` is read only by this sensor family (`sensor.py:13693-13704`); `button.py:1222-1234` (ramp diagnostics dump) reads the DB DAO directly, not the cache; `sensor.py:18919` / `hvac_excursion.py:240` are docstring references to `ac_nudges_today` (reconciliation by a human, no code read). Energy coordinator uses its own `savings_lifetime_baseline` (card adjacency). Dashboard templates `float(0)`-guard.
4. **30-day sensors / today sensors:** `kwh_avoided_total` (ENERGY) and `savings_lifetime` (MONETARY) are TOTAL; restored value then a lower live value = negative delta, correct. No TOTAL_INCREASING remains on a sensor that decreases intra-day: today/nudges/resets are DB-derived since local midnight from non-negative rows (`database.py:9240` `max(0, before-after)`), pruning only removes >30-day rows, so they only fall at midnight; the midnight drop to ~0 is `< 0.9*prev` -> correct meter reset. Residual pre-existing edge: a midnight drop of under 10 % (e.g. 0.50 -> 0.46 because events landed just after midnight before the first refresh) is a dip, not a reset, and costs a tiny negative delta. Negligible; not introduced here.
5. **Mutation (own choice):** `sensor.py` `_get_refreshed_cache` - dropped the `last_refresh_ts is None` check (`if cache is None:` only). Scoped suite baseline 139 passed; mutant **9 failed** (`test_before_first_refresh_reads_unknown_not_zero[...]` x7, `test_total_before_first_refresh_returns_restored_value`, `test_total_before_first_refresh_without_restore_is_unknown`). Restored; `git status` clean; `__pycache__` cleared before each run.

## Local correctness truth table (native_value before/after first refresh)

| Sensor | state_class | pre-refresh | post-refresh |
|---|---|---|---|
| nudges / resets / kWh today | TOTAL_INCREASING | None | cache value |
| kWh cycle, $ today, $ cycle, $ 30 d | TOTAL | None | cache value |
| kWh 30 d (RestoreEntity) | TOTAL | restored float, else None (unknown/unavailable/non-float restore -> None) | cache value |
| false-positive rate | MEASUREMENT | None | cache value (None if n<5) |

All 9 `native_value` sites route through `_get_refreshed_cache` (grep of `_get_cache()` in the family: only the mixin itself). unique_ids unchanged, so entity_ids and history are kept.

## Stats

| Sev | Found | Fixed | Deferred |
|---|---|---|---|
| CRITICAL | 0 | 0 | 0 |
| HIGH | 0 | 0 | 0 |
| MEDIUM | 0 | 0 | 0 |
| LOW | 2 | 0 | 2 (A-L1 accept/optional; A-L2 operator dashboard text) |

Bug classes: #53-adjacent x1 (display), doc drift x1. No new QUALITY_CONTEXT class: "seeded-default published as a real reading on a TOTAL_INCREASING sensor" is an instance of the existing restart/stale-data family (#7).
