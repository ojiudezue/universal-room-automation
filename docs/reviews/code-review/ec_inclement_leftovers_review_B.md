# EC inclement leftovers — Review B (integration / precedence / no-op path / lifecycle)

Branch `feature/ec-inclement-leftovers` (HEAD 0fe1948b) vs `pre-review-ec-inclement-leftovers` (three-dot).
Plan: `docs/planning/PLANNING_ec_inclement_leftovers_2026_11.md` rev 2.
Read in full first: `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` (mandatory). No §10 claim re-asserted.
Read-only; no suite run (framing B).

## Findings

| SEV | Site | Finding | Bug class |
|---|---|---|---|
| LOW | `energy_const.py` `TOU_PERIOD_NAME_LITERAL_SITES` key `energy_pool.py::determine_actions::peak` | The pin key is function-name only. `PoolController`, `EVChargerController` and `SmartPlugController` all define `determine_actions`, so the three share one key. A literal moved from the pool method into the EV/plug method (the two sites this cycle routed) keeps the count at 1 and the pin stays green. Suggest qualifying keys with the class (`Class.method`). Not a runtime defect. | #62 (weak anchor) |
| LOW | removed `_check_legacy_threat_list` (`energy.py` ~1322 old) | A repair issue `inclement_legacy_threat_list_retired` raised by the old build stays in the registry for the current run; its translation key is removed. It was created non-persistent (`ir.async_create_issue` default), so HA does not restore it as active after the restart that loads this build. I did not confirm that HA behaviour in HA source this session, so treat it as a residual to check live, not a verified fact. | lifecycle / stale surface |

No CRITICAL / HIGH / MEDIUM.

## Focus checks (cleared)

1. **`tou_engine` into `SmartPlugController.determine_actions`** (`energy_pool.py:3917`). Default `None`. Only production caller `energy.py:7671` passes `tou_engine=self._tou`. Test callers (`test_energy_load_shedding_correctness.py:1077/1097`, `test_ev_fill_priority_repause_band.py:433/437`) take the default, and `above_bottom_rate(None, …)` falls back to the old `("peak","mid_peak")` literal (`energy_tou.py` `above_bottom_rate`). EVSE path: `energy.py:8296` `attach_coord(self)` comes before `determine_actions`, so `_energy_coord._tou` resolves. On the live PEC tariff (`quality/tests/fixtures/tou_rates_live_pec_2026.json`), summer off/mid/peak rank 0/1/2, shoulder and winter off/mid rank 0/1, so rank>0 ⇔ period ∈ {peak, mid_peak}. Plug/EVSE pause, load-shed gate, energy situation and arbitrage displaced-savings are byte-identical live. `period_rank` swallows KeyError/TypeError/ValueError, and the helper also catches everything else, so it never raises into the decision cycle.
2. **HVAC anchor** (`hvac_predict.py:2055-2097`). `anchor_period` / `anchor_starts_in_minutes` come only out of `get_intent_attrs` (`:2145-2146`), and the only reader is `sensor.py:13077` (display). No HVAC decision reads them. This matches the doc's 2026-11-08 header entry. The new module-top import of `energy_tou` adds no cycle (`energy_tou` imports only `energy_const`). The block is still inside the existing `try/except` (`:2097`).
3. **Item 5, `envoy_available` on HOLD-CURRENT** (`energy_battery.py:5760`). It uses the same derivation as `_result` (`:7901`). Both HOLD-CURRENT callers (`:5915`, `:6254`) are in the attain branch, which is reached from `determine_mode` at `:6994`/`:7221`, after the per-tick entry reset `self._degraded_telemetry_source = None` / set-on-blind (`:6706-6708`). So the source can't be stale from an earlier tick, and it isn't inside the inclement save-clear-restore windows (`:6817-6844`, `:6901-6925`). Consumer `energy.py:3752` `_track_envoy_availability`: it is one increment per decision (called once at `energy.py:7912`), and the NM fires on `== 3`, so it pages once per outage and can't double-count or flap. A reboot-mid-attain tick under blind telemetry now counts as unavailable, which is the intended fix. Before, it reset the count. The consumers of `_envoy_unavailable_count` / `_envoy_degraded` are the NM plus display attrs (`sensor.py:14712/14777/14812`). No action reads them, so the change can't suppress a legitimate action. The HOLD-CURRENT action list is unchanged.
4. **Item 2, repair-check removal.** Repo-wide grep finds no remaining reference to `_check_legacy_threat_list`, `CONF_INCLEMENT_POWER_THREAT_EVENTS`, `DEFAULT_INCLEMENT_POWER_THREAT_EVENTS`, `_DISPLACED_PERIODS` or `inclement_legacy_threat` in the integration. Setup hunk `energy.py:1319-1325`: only the call is removed. `_arm_outage_ledger()` before it and the optimizer-intent subscription after it are untouched. Tests that referenced the removed symbols were deleted or updated (`test_ec_stage_b_classification.py`).
5. **Pinned named-period sites.** The diff hunks are limited to `_apply_arbitrage_tick`, `_update_energy_situation`, the head of `_update_load_shedding`, the plug call site, the setup call and the deleted method (`energy.py`); the HOLD-CURRENT dict line (`energy_battery.py`); EV/plug `determine_actions` (`energy_pool.py`); and the new helpers (`energy_tou.py`). No hunk touches the bodies holding the pinned N / T-change / T-fb / DEF literals (`_update_hvac_constraint`, `_get_displaced_rate`, `_decision_cycle_body`, attain / `determine_mode` / `_is_top_rate_edge`, the pool fill-priority / excess-solar code, `peak_ahead_before_offpeak`). `_update_load_shedding::peak` (the import-history literal) is outside the changed hunk.

**Lifecycle:** no new task, timer, listener or RestoreEntity. `season_at` reads `dt_util.now()` per call (pure). On PEC every season boundary falls at midnight inside off_peak, so ranking a tick's period against "now"'s season gives the same answer.

## Summary

| Severity | Found | Fixed | Deferred |
|---|---|---|---|
| CRITICAL | 0 | – | – |
| HIGH | 0 | – | – |
| MEDIUM | 0 | – | – |
| LOW | 2 | 0 | 2 (orchestrator call) |

Bug classes: #62 ×1, lifecycle/stale-surface ×1.

**Verdict: SHIP.**
