# Plan review 1: PLANNING_ec_inclement_leftovers_2026_11.md

**Reviewer:** ura-planner (Mode 2, adversarial plan review, Tier 2 rule). **Base:** `develop` @ `a3889b06`.
**Verdict: FIX-PLAN-FIRST.** 0 CRIT / 2 HIGH / 4 MED / 4 LOW. Items 2 and 5 are close to ready. Item 4 (D4) has a migration rule that breaks byte-identity for callers, and a pin spec that doesn't match its own site table.

HVAC STATE_OF_PLAY was read in full, because D4 touches `hvac_predict.py`. `anchor_period` / `anchor_starts_in_minutes` are display-only: they are returned by `get_intent_attrs` (`hvac_predict.py:2124-2128`) and read only by `sensor.py:13065`. No §10 ledger claim is affected.

## Verified correct (re-run, not trusted)

- **D2 consumers.** No decision path reads `inclement_power_threat_events` or `inclement_warn_min_severity`. The only code reader is `_check_legacy_threat_list` (`energy.py:9512-9543`, called at `:1324`).
- **Stored keys are harmless.** Every options-flow save merges `{**self._config_entry.options, **user_input}` (`config_flow.py:4709, 4806, 5303, 6338, 6450`, among others), so fossil keys pass through untouched. `__init__.py` has no migration that reads them.
- **D4 T-change sites.** The 4 sites match parent §14 Q1 (§8 #1/16/23/25) → `energy_battery.py:2296`, `energy.py:9618`, `energy_pool.py:405`, `:1858`. All H sites are byte-identical on the live tariff.
- **D5 literal.** `energy_battery.py:5756` is the only literal `"envoy_available": True`. Every `determine_mode` return (`:6668`, `:6757`…`:7312`) goes through `_result`, `_get_attainability_hold_decision` (→ `_result` `:5613`), `_get_arbitrage_decision` (→ `_result`), `_get_attainability_decision` (→ `_result` `:5559`), the blind literal (`False`, `:6678`), or the HOLD-CURRENT literal. The proposed fix matches `_result` `:7895-7897`.
- **D5 derivation.** `_degraded_telemetry_source` is always a string when Envoy is blind. `_soc_source_last` is assigned only string values (`:1120-1220`), so INV-E1 follows from the `_result` rule.
- **Tier.** Tier 2-DB is sound. No battery decision site migrates.

## HIGH

**H1. The D4 "now" migration rule ignores the `tou_period` argument, so byte-identity fails for callers and tests.**
The plan says to use `is_bottom_rate(now)` for "now" sites (§D4 migration rule, following the parent's `not is_bottom_rate(now)`). But each H site receives `tou_period` as a parameter:
- `_update_energy_situation(tou_period)` (`energy.py:9740`)
- `_update_load_shedding(tou_period)` (`:9751`)
- the EVSE and plug loops in `energy_pool.py` (`:1371`, `:3944`)

`is_bottom_rate(now)` re-derives the period from the wall clock. The hour sweep only proves equality when the passed period equals the clock period. Concrete break:
- `quality/tests/test_v4_6_9_energy_recent_decisions.py:173` sets `coord._tou = MagicMock()`.
- `tou.is_bottom_rate(now)` then returns a truthy MagicMock, which reads as "bottom", so `_update_load_shedding("peak")` stops shedding.
- Other suites call `_update_load_shedding("peak"/"off_peak")` directly (`test_energy_load_shedding_correctness.py`, `test_low_cleanup.py`, …) at whatever the real clock is.

The `_is_bottom_rate` precedent (`energy_battery.py:3405-3414`) has the same blind spot. It is fine there only because its caller passes the clock period.

**Fix in plan:** rank the PASSED period: `rank = tou.period_rank(tou.get_season(now), tou_period)`. Then:
- `rank is None` → literal fallback
- `rank == 0` → bottom
- anything else → above bottom

`isinstance(rank, int)` guards against MagicMock. Use the same form for future-period sites and billing (see L2). It is one rule, and it is byte-identical by construction for any argument.

**H2. The pin spec and the 39-site table disagree; the builder can't satisfy both.**
§D4 says the pin scans "`Compare` nodes (and `in`-tuples / tuple constants)". The table includes, or omits, sites that predicate doesn't match.

Table rows the predicate won't match:
- #4–5 `energy_battery.py:5352-5353`: `periods.get("mid_peak", {})` call args, not a Compare.
- #17 counts only `energy.py:4234`. `:4236` (`"mid_peak" in season_data`, a Compare) is missing, and `:4235` / `:4237` are subscripts.

Literals the table omits:
- `energy_battery.py:5294` (Compare inside the #2–3 walk) and `:5296` (return-tuple constant `(cursor, "peak", …)`).
- `:6991` (kwarg `tou_period="mid_peak"`).
- `energy_tou.py:39-47` (normalizer dict and `_VALID_PERIODS`; the parent excluded `:47` explicitly).
- `energy_const.py:24-59` (default-tariff dict keys).

Raw `git grep -nE '"(peak|mid_peak)"' -- '*.py'` returns about 60 lines in `custom_components`, not 39.

**Fix in plan:**
1. Define the node predicate exactly. Recommendation: every `ast.Constant` whose value is in {"peak","mid_peak"}, keyed by `(file, enclosing func, literal)` with a count.
2. State the exclusions by rule: tariff-definition tables in `energy_const.py`, the `energy_tou.py` normalizer and validation set, and docstrings/comments, which aren't Constants in expression position. Docstrings ARE `ast.Constant`, so the predicate must skip `Expr` docstrings.
3. Regenerate the table from that predicate so the table and the lint are the same set.

## MED

**M1. The D2 enumeration misses the user manual and one test import.**
- `docs/user-manual/ENERGY_COORDINATOR.md:174`, `:306-307` still document "Power-threat events" and "Min severity" as live options. The plan grepped `docs/Coordinator` only (§1d). Add them: edit to retired, or delete the rows.
- `quality/tests/test_inclement_alert_classifier.py:79` imports `DEFAULT_INCLEMENT_POWER_THREAT_EVENTS`, and `:216` builds the threat list from it. Removing the constant breaks collection of the whole module. The plan lists only the shim (`:110-114`) and callers. Name the import and `:216` explicitly. Because the arg is gone, the Red-Flag test becomes a plain classify; keep its assertions.
- `docs/readmes/README_v5.5.0.md:10` is history. Leave it as is, but say so.

**M2. The future-period sites' "dt = transition time" is under-specified.**
`get_next_transition` returns `{next_period, hours_until, transition_hour}` and no datetime (`energy_tou.py:594-622`). Its wrap branch uses the NEXT DAY's season (`:602-610`). Specify `season = tou.get_season(now + timedelta(hours=hours_until))` for `hvac_predict.py:2063` and `sensor.py:9430`; the current-period site `hvac_predict.py:2073` uses `now`. Without this, a builder will use `get_season(now)`, and the 09-30→10-01 discriminator the plan already names will catch it late. Also say what the synthetic `super_off_peak` test expects at `hvac_predict.py:2069`: the `elif next_period == "off_peak"` literal is out of scope, so a `super_off_peak` next period leaves `anchor_period=None`.

**M3. "9 per-site hour sweeps" can't be built as written. Simplify.**
The H predicates sit inline in methods with side effects (shedding, EVSE actions). Sweeping each site for a year means driving 9 different coordinators 8,760 times. Simplest form:
- Add ONE pure predicate, e.g. `_above_bottom_rate(tou, season, period, fallback_literal)`. This is NEW: the engine has `period_rank` but no "rank a given period with literal fallback" helper. Justify it in §1a; the plan currently claims "Anything NEW: None".
- Sweep that helper once, plus once against the synthetic tariff.
- Prove each of the 9 sites routes through it with the Review-C per-site mutation, plus one behavioral test per site.

The marginal value of 9 sweeps over 1 sweep plus 9 routing proofs is zero.

**M4. The D5 whole-surface pin is too narrow.**
The consumer reads `decision.get("envoy_available", True)` (`energy.py:3760`, also `:7949`), so a future literal decision dict that OMITS the key also reports "available", which is the same defect. The planned AST check only forbids `Constant(True)`. Extend it: every dict literal in `energy_battery.py` that has both `"mode"` and `"actions"` keys must have an `"envoy_available"` key whose value is not `Constant(True)`. Changing the consumer default is out of scope; it would page on any keyless dict.

## LOW

- **L1.** The HOLD-CURRENT dict also lacks the `(degraded telemetry: <src>)` reason suffix that the normal path adds (`energy_battery.py:7635`). It is display only, but the same sibling shape as D5. Either mirror it in D5 (1 line) or note it as a non-goal.
- **L2.** The `energy_billing.py:875` "migrate or pin, builder states which" choice is unnecessary. The consumer `_apply_arbitrage_tick(self, tick, period, season, now)` (`energy.py:4595`, use at `:4634`) already has `season` and `period`. Rank with `period_rank(season, period)` per H1, and remove the option.
- **L3.** The D4 Live criterion can't discriminate by design (byte-identical on PEC). Label it "no-regression only" so the README write-back doesn't claim more.
- **L4.** §1d says "Not HVAC work, so the STATE_OF_PLAY docs do not apply", but D4 edits `hvac_predict.py`. Cite the HVAC doc read and the display-only finding above. Nothing in §10 is affected.

## Summary

| Severity | Count | IDs |
|---|---|---|
| CRIT | 0 | |
| HIGH | 2 | H1 migration rule ignores passed period; H2 pin predicate vs table |
| MED | 4 | M1 D2 missed refs; M2 future-season dt; M3 sweep shape (simplify); M4 D5 pin missing-key |
| LOW | 4 | L1–L4 |

**Scope verdict:** FOCUSED. **D2 and D5:** proceed once M1, M4 and L1 are folded in. **D4:** fix H1, H2, M2 and M3 in the plan before build dispatch.
