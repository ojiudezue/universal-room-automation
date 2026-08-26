# Midnight drain-target cycle — consolidated Tier-3 review (4 framing-disjoint passes)

**Build:** `feature/midnight-drain-target` @ `a8e573ddb`. **Verdict: FIX-REQUIRED (core SHIP).**
The money-bearing core is sound — A/B/C/D all verified the drain-target arithmetic, `_resolve_target_day`, `_drain_target_for` multi-day max, the HIGH-2 DP value-stamp (C's S6 mutation PROVES the DP floor routes through `_drain_target_for`), the partial_hold clamp ordering, INV-DTDS-1..5, DST safety, and the arbitrage-off-by-one boundary. All fixes below are on narration / telemetry surfaces + guards, NOT the reserve/drain arithmetic.

## Must-fix

- **CF-1 CONVERGENT (A-MED-1 = B-MED-1 = D-HIGH-1) — emitter reason strings narrate calendar-tomorrow while the target is peak-anchored.** `energy_battery.py:5407,5425` interpolate `tomorrow_class`; `drain_class_for_target` is assigned (:5371,:5382) and never read (Bug Class #53 introduced by the diff). Repro: offset 0, today=poor(30)/tomorrow=excellent(10) → `reason "…target 30% (tomorrow excellent)"` (self-contradicting; excellent→10). The narration helpers were re-labelled `target=<class>`, the emitter reason wasn't. FIX: interpolate `drain_class_for_target` in both f-strings (makes the multi-day bump live again) OR delete the dead block and print `target=<d1_class>`. This is the live-validation string.
- **CF-2 (D-MED-1) — D6 telemetry blank in the live DEFAULT config.** DP is OFF by default (`CONF_DP_ENABLE=False`); only `shadow_last_eval_snapshot`/`shadow_last_eval_at` are written, but D6 reads `last_eval_snapshot`/`last_eval_at` → `dp_state` stuck, `dp_last_eval_soc/dp_drain_floor/dp_eval_age_min = None`. D6 acceptance passes vacuously on sentinels. FIX: fall back to `shadow_last_eval_snapshot`/`shadow_last_eval_at` when `last_eval_at is None`; expose which leg (`dp_source: shadow|live`).
- **CF-3 (D-MED-3 = B-MED-4) — D7 labels operator-off/unplugged bay `paused`.** `state="paused"` on `owner is not None OR not is_on`. FIX: `off`/`idle` when `not is_on AND owner is None`; `paused` only when `owner is not None`.
- **CF-4 (D-MED-2) — D7 `throttled` forever for a sub-48A-nameplate bay.** Compares `commanded_amps < SOLAR_FOLLOW_RESTORE_AMPS(48)` with no per-bay nameplate; a legal 40A@32A bay reads throttled at full current. FIX: discriminate throttled by "solar-follow throttle active" (commanded < the bay's CAPTURED original `_original_amps`/`_last_commanded` baseline), not a hardcoded 48.
- **CF-5 (MED-C1) — D6/D7 untested (4 green-on-neuter).** D7 `per_bay_state` carries real derived logic inside a broad `except` that silently yields nothing — a defect is invisible to suite AND operator. FIX: round-trip tests for D7 (paused-by-owner / throttled / charging-at-nameplate) and D6 (shadow leg + enabled leg).
- **CF-6 (MED-B2) — resolver `try/except` silently changes the ARBITRAGE failure mode.** `_resolve_target_day:2450-2453` swallows a TOU raise → arbitrage callers silently evaluate against calendar-tomorrow (wrong day at offset 0) on the money path instead of aborting loudly. FIX: `_LOGGER.warning(..., exc_info=True)` in the except (or scope the guard to drain callers).
- **CF-7 (MED-B3) — post-midnight `solcast_today` unavailability → 40 sentinel EV-hold.** At the 00:05 offset 1→0 flip authority moves to `solcast_today`; if briefly unavailable → `unknown` → drain target 40 (> every class), stamped as the DP floor, extending EV-hold. Conservative direction, but new + unchecked-dependency. FIX: at offset 0 with `classify_solar_day()=="unknown"`, fall back to the previous resolved class or `classify_tomorrow_solar()`; surface which.

## LOW (fold into the pass)
- CF-8 (B5/B7/D-LOW-1) — wall-clock seams: thread `now` into `classify_solar_day`/`classify_solar_day_n` and the two accessor call sites where the caller has a `now`; docstring the boot-only ones.
- CF-9 (B6) — wrap the 3 new drain attrs in `get_status` so a `classify_*` raise doesn't kill the whole strategy sensor render.
- CF-10 (C3) — invert one class in `test_drain_target_for_helper_is_single_source_of_truth` so all four legs discriminate (Bug Class #63 smell: today=excellent/tomorrow=poro both yield 40).

## Re-verify after fix-up
Re-drill CF-1 (reason string now names target-day class); the new D6/D7 tests bite; orchestrator re-run S6 (stamp) + full-suite name-diff = 0 new failures.
