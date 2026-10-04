# URA v5.103.38 — HOTFIX: Coordinator Manager failed to start in v5.103.37

## What broke
CM-COORDINATORS-ADD-ONE-BY-ONE-1 (v5.103.37) moved the eight coordinator registration gates onto a shared `coordinators_to_register(cm_config, hass)` set, but computed it **before** `cm_config` was assigned in `async_setup_entry`. On the 2026-10-03 15:55 restart this raised `UnboundLocalError: cannot access local variable 'cm_config'` and the Coordinator Manager never started — Energy, HVAC, Presence, Safety, Security, Music Following, Appliance and Notifications were all down; the legacy safety-alert fallback ran instead.

## Fix
`_to_register` is now computed right after `cm_config` is built (`__init__.py`, before `CoordinatorManager(hass)`). No other change.

## Why tests missed it
The gate tests drove `coordinators_to_register` directly and checked call sites by source text; no test runs `async_setup_entry` with the master switch on (noted as a gap in the v5.103.37 build report). New `quality/tests/test_setup_cm_config_assigned_before_use.py` asserts by AST that `cm_config` is stored before any load and that the registration set is computed after the full `cm_config` build; both fail on v5.103.37 and pass on the fix. A scan of every local in `async_setup_entry` found no other use-before-assign.

## Live validation
### Validated 2026-10-03 (~17:05 restart onto v5.103.38; checked ~20:20)

| Check | Result | Evidence |
|---|---|---|
| No `UnboundLocalError: cm_config` | PASS | error_log search 0 matches |
| Coordinator Manager initialises | PASS | CM entry `loaded`; all 46 URA entries `loaded` |
| Coordinators running (not legacy fallback) | PASS | all 8 `switch.ura_*_enabled` on, `added: true`; battery strategy attrs populated |
| Custom Preset Ranges off | PASS (operator-intent restore) | turned off after both restarts; reload/restart re-enables it (code default ON) — fix tracked in Batch C |

5.103.37's 15:55 restart had every coordinator down until this hotfix (~70 min).
