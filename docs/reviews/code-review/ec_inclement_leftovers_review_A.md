# EC inclement leftovers — Review A (local correctness, edge cases, config extremes)

Branch `feature/ec-inclement-leftovers` (head 0fe1948b) vs `pre-review-ec-inclement-leftovers`.
Reviewer framing A only. Not an HVAC-logic or presence change: `hvac_predict.py` is touched only at the TOU-anchor period test, and the HVAC state-of-play doc gets a 2-line note. I did not re-read the HVAC doc for this pass.

## Verdict: SHIP (0 CRIT / 0 HIGH / 0 MED / 2 LOW)

## Evidence

| Check | Result |
|---|---|
| `above_bottom_rate` vs legacy `period in ("peak","mid_peak")` on the built-in PEC 2026 tariff, all 8,760 hours of 2026 | 0 mismatches (scratch script, `TOURateEngine()` default table) |
| MagicMock engine | `period_rank` returns a MagicMock, which is not an int, so it falls back to the literal: peak=True, off_peak=False |
| bool rank | `isinstance(rank, bool)` is excluded, so it falls back to the literal (True does not count as rank 1) |
| engine None / season None / unknown period / period None | literal fallback: mid_peak=True, peak=True, "bogus"=False, None=False |
| 2-tier tariff, mid_peak rate == off_peak rate | off_peak=F, mid_peak=F, peak=T. A mid_peak priced at the bottom rate no longer sheds or pauses, which is the intended rule |
| Next-day wraparound (`hvac_predict.py` ~2058, `sensor.py` ~9425) | season is computed at `now + hours_until`, not at now, so a transition that crosses a season boundary at midnight ranks in the right season. A `hours_until` that is None or non-numeric gives `_next_when=None`, then the literal fallback |
| Load shedding (`energy.py` `_update_load_shedding`, `_update_energy_situation`) | ranks the PASSED `tou_period` with `season_at(now)`. A mismatch at a season boundary is only possible at a month change at midnight, when the period is off_peak in every season. Harmless |
| Arbitrage displaced (`energy.py:4631`) | uses the caller's `season` argument, so the tick's period and season stay consistent |
| EVSE / plug (`energy_pool.py`) | the decision is computed once per call, before the per-device loop. Plug `tou_engine` defaults to None, which keeps the legacy behavior for other callers. The coordinator call site threads `self._tou` |
| D5 `envoy_available` (`energy_battery.py:5760`) | uses the same expression as `_result` (`:7901`). Both callers of `_get_attainability_hold_current_decision` (`:5915` via `_maybe_run_reboot_recovery`, `:6254`) sit inside `_run_attain_branch`, which is reached only after the per-tick reset of `_degraded_telemetry_source` at `:6706`, so neither reads a stale value |
| D2 removal | no remaining reference to `CONF_INCLEMENT_POWER_THREAT_EVENTS`, `DEFAULT_INCLEMENT_POWER_THREAT_EVENTS`, `_check_legacy_threat_list`, `_DISPLACED_PERIODS` or the translation key in `custom_components/` (the only hits are negative assertions in tests). Stored options that still hold the old key are inert because nothing reads them. The live `.storage/repairs.issue_registry` has 0 `inclement_legacy` entries, so no orphaned issue is left without its translation |

## Findings

- **LOW-1 (tariff extremes, intended-by-rule) `energy_tou.py:380`.** The tariff validator does not enforce rate ordering. On an inverted tariff (off_peak priced above mid_peak), off_peak ranks above the bottom, so EVSE and plugs pause and load shedding arms during "off_peak". This follows the stated rule ("above the bottom rate"), but it contradicts the literal-named off-peak ensure-on paths elsewhere; the pause branch runs first, so pause wins. Not reachable on PEC. Document it, or add a validator warning. Bug class: #63 (coincidental equality: name ≡ rank).
- **LOW-2 (None handling) `energy_tou.py:368`.** `season_at` returns whatever `get_season` returns. A MagicMock season is truthy and is passed straight to `period_rank`. That is safe today because the rank type-guard catches it. Note only.

No CRITICAL, HIGH or MEDIUM findings. Bug classes weighed: #7 stale data (D5 reset ordering: cleared), #22 enum mismatch (period names: pin list plus fallback, cleared), None handling (cleared), #53 one-missed-site (not this framing; that belongs to D).
