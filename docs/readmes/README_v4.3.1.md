# v4.3.1 — Tech Debt Cleanup

**Date:** 2026-05-06
**Type:** Tier 1 hotfix (3 mechanical cleanups, no new features)
**Predecessor:** v4.3.0 (current production)

## Summary

Three mechanical tech-debt cleanups carried over from v4.2.29 + v4.3.0 deferral lists:

1. **A1**: Removed the 13 envoy-derived `DEFAULT_*_ENTITY` placeholder constants. Production now has no envoy entity defaults — entities come exclusively via config (auto-derived in `__init__.py` from `CONF_ENERGY_ENVOY_ENTITY`). Consumer call sites refactored to handle `None` entity_id gracefully.
2. **A2**: Five validator error code string literals (`envoy_required`, `envoy_invalid_format`, `envoy_entity_missing`, `derived_entity_missing`, `envoy_derived_missing`) extracted to `Final` constants in `energy_const.py`. Single source of truth for both validator and config-flow.
3. **A3**: Repair issue `energy_envoy_invalid_<entry_id>` now `is_fixable=True` with a fix-flow handler. New `repairs.py` module implements `EnvoyValidationRepairFlow` — opens a small modal, re-validates on confirm, deletes the issue and reloads the entry on pass.

## What changed

### A1 — `DEFAULT_*_ENTITY` structural removal

**Removed from `domain_coordinators/energy_const.py`** (13 constants + the `_UNCONFIGURED_ENVOY` placeholder):
- `DEFAULT_SOLAR_PRODUCTION_ENTITY`
- `DEFAULT_GRID_CONSUMPTION_ENTITY`
- `DEFAULT_BATTERY_SOC_ENTITY`
- `DEFAULT_BATTERY_POWER_ENTITY`
- `DEFAULT_NET_POWER_ENTITY`
- `DEFAULT_LIFETIME_CONSUMPTION_ENTITY`
- `DEFAULT_LIFETIME_PRODUCTION_ENTITY`
- `DEFAULT_LIFETIME_NET_IMPORT_ENTITY`
- `DEFAULT_LIFETIME_NET_EXPORT_ENTITY`
- `DEFAULT_LIFETIME_BATTERY_CHARGED_ENTITY`
- `DEFAULT_LIFETIME_BATTERY_DISCHARGED_ENTITY`
- `DEFAULT_BATTERY_CAPACITY_ENTITY`
- `DEFAULT_CONSUMPTION_TODAY_ENTITY`

**Non-envoy defaults retained** (legitimate fallbacks for non-Enphase users):
`DEFAULT_STORAGE_MODE_ENTITY`, `DEFAULT_RESERVE_SOC_ENTITY`, `DEFAULT_GRID_ENABLED_ENTITY`, `DEFAULT_CHARGE_FROM_GRID_ENTITY`, `DEFAULT_SOLCAST_*`, `DEFAULT_WEATHER_ENTITY`.

**Consumer changes**:
- `energy_battery.py`: `_get_entity(key, default=None)` — default arg now optional. The 4 envoy properties (`battery_soc`, `solar_production`, `net_power`, `battery_power`) drop the second arg; non-envoy properties keep theirs. `_get_state_*` helpers accept `str | None` and short-circuit to `None`.
- `energy.py`: 7 `ec.get(CONF_X, DEFAULT_X)` patterns simplified to `ec.get(CONF_X)`. Six `_get_lifetime_*` methods refactored to use the existing `_get_state_float` helper (DRY: 6 × 8 lines → 6 × 1 line). `_crosscheck_consumption` adds explicit None guard before reading `_entity_consumption_today`. `_get_battery_capacity_kwh` treats `eid is None` same as unavailable; warning log uses `eid or "(not configured)"`.
- `energy_billing.py`: `_net_power_entity` and `_solar_entity` no longer fall back to defaults; `_get_net_power` adds explicit None guard. (`_solar_entity` is assigned but never read — confirmed safe.)
- `energy_forecast.py`: `_battery_soc_entity` and `_battery_capacity_entity` no longer fall back; `_get_float` accepts `str | None`.
- Tests: `test_energy_battery.py` defines test-local fixture constants at module level (same names as the deleted production constants). `_BatteryHarness` wires them into `BatteryStrategy` via `entity_config`. `test_energy_consumption.py` does the same plus passes `battery_soc_entity` and `battery_capacity_entity` explicitly to `DailyEnergyPredictor`.

**Net effect**: `grep '_UNCONFIGURED_ENVOY'` returns 0 hits. Future devs cannot accidentally trust a default that resolves to a non-existent entity. The validation gate from v4.2.29 is the only path to production envoy entities.

### A2 — Magic-string error codes → `Final` constants

In `energy_const.py`, near `validate_envoy_config`:
```python
ENVOY_ERR_REQUIRED: Final = "envoy_required"
ENVOY_ERR_INVALID_FORMAT: Final = "envoy_invalid_format"
ENVOY_ERR_ENTITY_MISSING: Final = "envoy_entity_missing"
ENVOY_ERR_DERIVED_MISSING: Final = "derived_entity_missing"
ENVOY_ERR_BASE_DERIVED_MISSING: Final = "envoy_derived_missing"
```

`validate_envoy_config` and `config_flow.py:async_step_coordinator_energy` both reference the constants. **String values unchanged** — they still match `strings.json:options.error.<code>` keys, so HA's form rendering and translations continue to work.

### A3 — Repair issue `is_fixable=True` + fix flow

**New module**: `custom_components/universal_room_automation/repairs.py` (~130 lines).

**`EnvoyValidationRepairFlow(RepairsFlow)`**:
- `init` step → `confirm` step
- Confirm step: re-runs `validate_envoy_config` against current entry options (with auto-derive applied to mirror startup wiring at `__init__.py:1381-1386`)
- On pass: `ir.async_delete_issue` + `async_create_background_task(async_reload(entry_id))` named `ura_envoy_repair_reload_<entry_id>` (Bug Class #19 prevention) + `async_create_entry`
- On fail: re-show form with current errors and `envoy_validation_still_failing` error code
- Edge case — entry deleted between issue-raise and fix attempt: deletes orphan issue and exits gracefully

**`async_create_fix_flow(hass, issue_id, data)`**: dispatches by issue id prefix `energy_envoy_invalid_*`. Unknown issue ids return `ConfirmRepairFlow()` with WARNING log.

**`__init__.py`**: `is_fixable=False` → `is_fixable=True`; added `data={"entry_id": entry.entry_id}` to the `ir.async_create_issue` call.

**`strings.json`**: new `issues.energy_envoy_invalid.fix_flow.step.confirm` block + `fix_flow.error.envoy_validation_still_failing`.

## Tier 1 Review

Per project memory `feedback_review_bug_visibility.md` — surfacing ALL bugs found at every severity:

| Severity | Finding | Status |
|---|---|---|
| (none CRITICAL) | — | — |
| (none HIGH) | — | — |
| MEDIUM | `repairs.py:31` — `EnvoyValidationRepairFlow.__init__()` didn't call `super().__init__()` | **Fixed** |
| MEDIUM | `repairs.py:88-91` — untracked `async_create_task(async_reload(...))` (Bug Class #19) | **Fixed** — switched to `async_create_background_task` with named task |
| MEDIUM | `repairs.py:128` — `ConfirmRepairFlow()` no-args constructor | **Accepted** — standard HA pattern, takes no args |
| LOW | Tests use magic strings instead of imported error-code constants | **Deferred** — values unchanged, tests still pass; opportunistic cleanup in future |
| LOW | `_get_entity` docstring doesn't note v4.3.1 signature change | **Deferred** — minor doc nit |
| LOW | f-string `eid or "(not configured)"` flagged but confirmed correct | **No action** — not a bug |

Verdict (post-fix): **READY TO DEPLOY**.

Full review at `docs/reviews/code-review/v4.3.1_tech_debt_cleanup.md`.

## Tests

```bash
PYTHONPATH=quality python3 -m pytest quality/tests/test_envoy_auto_derive.py quality/tests/test_energy_battery.py quality/tests/test_energy_consumption.py
# 112 passed
```

No new tests added (mechanical cleanup; existing tests cover the consumer behavior). AST clean.

## Live validation (Review 3 — post-deploy)

After HA restart with v4.3.0 → v4.3.1 upgrade:

1. Verify HACS installed_version reads `v4.3.1` (per `feedback_verify_hacs_install.md` memory; the v4.3.0 cycle taught us to always check this).
2. Confirm `sensor.ura_energy_coordinator_battery_strategy` keeps producing `mode`, `reason`, threshold attributes — A1 should be transparent for valid configs.
3. Confirm `sensor.ura_arbitrage_savings_*` continue tracking (A1 doesn't touch them).
4. **A3 negative test (manual, optional)**: temporarily clear `energy_envoy_entity` via the Coordinator Manager → Configure → Energy form. The repair issue should appear. Click the new "Fix" button → modal opens → re-set the envoy entity → click Submit in the modal → issue clears, integration reloads automatically.
5. Confirm `grep '_UNCONFIGURED_ENVOY'` on the running custom_components folder returns nothing — the placeholder is gone for good.

## Deploy notes

- No DB schema changes
- No config-entry migration needed (CONF_ keys unchanged; only DEFAULT_X internals removed)
- `_get_entity(key)` two-arg → one-arg refactor is backward-compatible (default=None)
- Manifest stamped to v4.3.1 by deploy.sh
- HACS download required after deploy.sh per `feedback_verify_hacs_install.md` — verify `installed_version` post-restart before declaring live validation passed

## Next

- **v4.3.2** (Tier 2 if needed): Multi-day Solcast forecast lookback for arbitrage smarter when day 2 sunny but day 3 bad
- **v4.4.x** — B5 Appliance Scheduler (TBD scheduling)
- **v4.5.0** — Routine Awareness (B6 + B7) per `docs/planning/PLANNING_v4.5.0_routine_awareness.md`
- Dashboard "estimated savings if enabled" widget — parked until ~June (needs a bill cycle of `arbitrage_cycles` data)
