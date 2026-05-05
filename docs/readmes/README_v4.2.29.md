# v4.2.29 — Envoy config validation + fail-safe

**Date:** 2026-05-05
**Type:** Feature cycle (B1 + B3 — startup + config-flow validation, cross-coordinator wiring)

## Summary

Replaces the silent fall-back-to-wrong-default behaviour in Energy Coordinator wiring with an explicit, multi-tier validator (`validate_envoy_config`). When `energy_envoy_entity` is missing, malformed, or its derived entities don't exist in HA, the coordinator now refuses to start and surfaces a repair issue — instead of silently producing wrong cost numbers from a non-existent entity (latent bug discovered while diagnosing the 51% predicted-bill discrepancy).

## Why

The old `DEFAULT_*_ENTITY` constants (line 124–141 of `energy_const.py`) were tied to a hardcoded wrong serial (`202428004328`, an old Envoy that no longer exists in this HA install). Consumers used `entity or DEFAULT_X` / `ec.get(CONF_X, DEFAULT_X)` patterns that fell back to the wrong-serial entity ID when:
- `energy_envoy_entity` was missing in config, OR
- auto-derive failed to seed the derived keys, OR
- HVAC predictor was constructed without `net_power_entity` from EC

Downstream code (`CostTracker._get_net_power`, `BatteryStrategy.net_power`, `HVACPredictor._get_net_power`) handled `state.get → None` defensively, so nothing crashed — but cost accumulation, solar banking decisions, and bill predictions silently produced 0 or stale values, with no warning.

## What changed

### `custom_components/universal_room_automation/domain_coordinators/energy_const.py`

New helper `validate_envoy_config(hass, energy_entity_config) -> dict`. Five-tier validation:

| Tier | Check | Fail mode |
|---|---|---|
| V0 | `energy_envoy_entity` is non-empty | hard error `envoy_required` |
| V1 | `extract_envoy_serial()` returns a serial | hard error `envoy_invalid_format` |
| V2 | `hass.states.get(envoy_entity)` is not None | hard error `envoy_entity_missing` |
| V3 | state is not `unavailable`/`unknown` | warning only (envoy can blip) |
| V4 | All four critical derived entities exist (`NET_POWER`, `SOLAR`, `LIFETIME_NET_IMPORT`, `LIFETIME_CONSUMPTION`) — checked against the resolved config (explicit overrides win over derived) | hard error `derived_entity_missing` |

Returns `{ok, errors, warnings, serial, resolved}`. V4's required-key list (`ENVOY_REQUIRED_DERIVED_KEYS`) is intentionally narrow — battery-only entities aren't validated because non-battery installs legitimately won't have them.

13 `DEFAULT_*_ENTITY` constants now resolve to a `_UNCONFIGURED_ENVOY = "sensor.envoy_unconfigured"` placeholder. The constants are kept for backward-compat at consumer call sites but are unreachable for valid configs (gated by B1). Full structural removal deferred to v4.2.30 alongside None-handling cleanup at the call sites.

### `custom_components/universal_room_automation/__init__.py`

**B1 startup gate** at the auto-derive site: when `envoy_eid` is set, run `validate_envoy_config`. When EC is enabled and validation fails:
- Log ERROR with the field-by-field error map
- Raise an entry-scoped repair issue (`f"energy_envoy_invalid_{entry.entry_id}"`) — Tier 2 review fix; avoids cross-entry collisions and stacking on repeat reloads
- Refuse to register `EnergyCoordinator`
- HVAC's `net_power_entity` is forced to `None` so its predictor degrades gracefully

When EC is enabled and validation passes, any prior repair issue with that id is deleted so a successful reload self-heals.

`async_unload_entry` also clears the repair issue to prevent stale entries in Settings → Repairs after the user removes the integration.

### `custom_components/universal_room_automation/config_flow.py`

**B3 config-flow gate** in `async_step_coordinator_energy`: when the user submits with a non-empty envoy entity, run `validate_envoy_config` against the merged options. Hard-fail tiers (V0/V1/V2/V4) populate `errors` per-field and re-show the form with HA's standard inline error rendering. V3 is logged but doesn't block the save (envoys do go offline transiently). Empty envoy entity is allowed (users can set up EC later).

### `custom_components/universal_room_automation/domain_coordinators/hvac_predict.py`

Removed `or DEFAULT_NET_POWER_ENTITY` fallback. `self._net_power_entity` is now `str | None`. `_get_net_power()` returns `0.0` immediately when `None` — solar-banking conditions (`net_power < -500`) correctly evaluate False, so pre-cool decisions skip rather than read from a wrong-serial entity.

### `custom_components/universal_room_automation/manifest.json`

Added `after_dependencies: ["enphase_envoy"]` per Tier 2 Review 2 HIGH finding — guarantees the Enphase integration loads before URA so V2/V4 don't spuriously fail on first boot after upgrade.

### `custom_components/universal_room_automation/strings.json`

Five new error keys under `options.error` (`envoy_required`, `envoy_invalid_format`, `envoy_entity_missing`, `derived_entity_missing`, `envoy_derived_missing`), and a new top-level `issues.energy_envoy_invalid` translation block for the repair-issue UI.

### `quality/tests/test_envoy_auto_derive.py`

New `TestValidateEnvoyConfig` class with eight tests covering V0–V4, the V3 warning-only path, explicit-override layering through V4, and the full-pass case. Existing HVAC predictor tests updated for `net_power_entity=None` semantics. All 22 envoy tests pass; full energy-suite (envoy + battery + consumption) passes 102/102.

## Reviews — Tier 2 (per CLAUDE.md)

**Review 1 (Core A) — adversarial bug-class audit:**

| Severity | Finding | Status |
|---|---|---|
| (none CRITICAL) | — | — |
| (none HIGH) | — | — |
| MEDIUM | V4 list is narrow (4 of 13 derived entities) | Accepted — non-battery installs legitimately won't have battery entities |
| MEDIUM | DEFAULT_* fallback patterns still present at consumer sites | Accepted — gated by B1, full cleanup deferred to v4.2.30 |
| LOW | All strings.json keys match validator output codes | OK |
| LOW | HVAC predictor None-safe degrade is correct | OK |

Verdict: **READY TO DEPLOY**.

**Review 2 (Core B) — race / restart / cross-coordinator:**

| Severity | Finding | Status |
|---|---|---|
| **CRITICAL** | Repair issue not cleared on `async_unload_entry` → orphaned in Settings → Repairs after integration removal | **Fixed**: added `ir.async_delete_issue` to unload path |
| **HIGH** | No declared dependency on Enphase → V2/V4 spuriously fail on first boot if Enphase loads after URA | **Fixed**: added `after_dependencies: ["enphase_envoy"]` to `manifest.json` |
| MEDIUM | Repair issue was domain-scoped, could collide across entries | **Fixed**: issue id now `f"energy_envoy_invalid_{entry.entry_id}"` |
| MEDIUM | HVAC degrade-to-None was silent; users can't tell solar banking is off | **Fixed**: log a WARNING when HVAC initializes without `net_power_entity` |
| MEDIUM | No retry mechanism if Enphase races back on after URA validation fails | Mitigated by `after_dependencies`; service-call retry deferred |
| LOW | `is_fixable=False` contradicts a "Fix via Coordinator Manager" message | Deferred — implementing a fix flow handler is its own scope |
| LOW | Magic-string error codes scattered across two files | Deferred — refactor opportunity |

Verdict (post-fix): **READY TO DEPLOY**.

Full review at `docs/reviews/code-review/v4.2.29_envoy_validation.md`.

## What we parked

| Item | Reason |
|---|---|
| Full removal of 13 `DEFAULT_*_ENTITY` constants | Requires call-site None-handling refactor — Tier 2 in its own right; not worth widening v4.2.29 scope |
| Repair-issue "fix" flow handler (`is_fixable=True`) | Out of scope; needs `async_create_fix_flow` plumbing |
| Startup retry loop for transient Enphase unavailability | Mitigated by `after_dependencies`; revisit if reports surface |
| Integration test of `__init__.py` validation wiring (mock hass + coordinator manager) | Filed for future cycle — needs more test infra |
| EC `envoy_status: online` while data sensors unavailable (filed in v4.2.28) | Still outstanding; was not v4.2.29 scope |

## Live validation (Review 3 — post-deploy)

After HA restart:

1. Within 1 minute, look for the absence of the repair issue `energy_envoy_invalid_<entry_id>` in Settings → Repairs (current config is valid; validator should pass).
2. Confirm log shows no `Energy Coordinator NOT started` ERROR.
3. Confirm log shows no `HVAC solar banking degraded` WARNING.
4. Sensor `predicted_bill_today` continues to populate (was working pre-deploy after the user fixed the import/export sensors).
5. **Negative test (manual)**: temporarily clear `energy_envoy_entity` via the Coordinator Manager → Configure → Energy form. Expected: form rejects save with field error `envoy_required`. Reload entry without saving.
6. Tomorrow morning: predicted_bill projects from a fresh midnight; no inflated daily cost (was the user's original concern).

## Tests

```bash
PYTHONPATH=quality python3 -m pytest quality/tests/test_envoy_auto_derive.py -v
# 22 passed (8 new validator tests + 14 pre-existing auto-derive tests)

PYTHONPATH=quality python3 -m pytest quality/tests/test_envoy_auto_derive.py quality/tests/test_energy_battery.py quality/tests/test_energy_consumption.py
# 102 passed, no regressions
```

AST-clean for Python 3.9 + 3.14 (forward-compat by construction; no new syntax).

## Deploy notes

- No DB schema changes — no migration.
- HA restart picks up `after_dependencies: ["enphase_envoy"]`; first reload may take a few extra seconds while Enphase initializes first.
- Existing installs with valid envoy_entity: no behaviour change.
- Existing installs with EC enabled but envoy_entity missing/wrong (silent failures pre-v4.2.29): EC will refuse to start + repair issue surfaces. The fix is the same as before — set a valid envoy entity. The visibility is the upgrade.

## Next

- **v4.2.30** — full removal of `DEFAULT_*_ENTITY` constants + None-handling at call sites; address `is_fixable=True` fix flow.
- **v4.5.0** — Routine Awareness (B6 + B7) and/or Energy Architecture Alignment (BACKLOG E).
