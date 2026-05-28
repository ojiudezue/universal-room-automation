# URA v4.7.0 — WeatherProviderManager + EV TOU Hardening

**Release date:** 2026-05-27
**Tier:** Combined deploy. Two cycles bundled:
- **Cycle A (Tier 2-DB):** WeatherProviderManager + apparent-temp primitive — foundation for Dynamic Preset Management
- **Hotfix (Tier 2):** EV TOU Strict-Policy Hardening + EC startup-race state restore — addresses live cost-bleed incident

**Trigger:**
- 2026-05-27 live EV cost-bleed at $1.45/hr during mid-peak (manual HA-side EVSE re-enable defeated URA's TOU pause)
- Dynamic Preset Management foundation work (multi-provider weather + apparent-temp primitive)

---

## TL;DR

**WeatherProviderManager (Cycle A):** new `domain_coordinators/weather_manager.py` singleton stored at `hass.data[DOMAIN]["weather_manager"]`. Ranked primary + 2 fallback providers, automatic failover on staleness, divergence detection across providers, apparent-temperature probing with raw-temp fallback. Foundation for the upcoming Dynamic Preset Management cycle (per-zone preset ranges keyed off forecast apparent high).

**EV TOU Strict Policy (Hotfix D1):** dropped the `_paused_by_us` bookkeeping short-circuit in `EVChargerController.determine_actions()`. URA now re-issues `switch.turn_off` idempotently on every decision tick during peak/mid-peak TOU. **Manual HA-side EVSE re-enables are defeated within ≤5 min.** New bug class `#43` documented.

**EC Startup-Race Sub-Switch Restore (Hotfix D2):** new `SIGNAL_ENERGY_COORDINATOR_READY` dispatcher signal (mirrors `SIGNAL_DATABASE_READY` pattern). EC sub-switches subscribe and re-apply saved values when EC init lands, fixing the v4.5.3 retry-budget gap that surfaced as `not_initialized` errors on 2 prior HA restarts (2026-05-19 evidence).

**Force-Charge Admin Override (Hotfix D3):** new `button.ura_energy_coordinator_evse_force_charge_30min` — the only supported bypass path for the strict TOU policy. 30-min window, auto-expire, idempotent re-press, NM-notification on activation, ISO expiry persisted across reloads via RestoreEntity.

**Optimization Visibility (Hotfix D4):** new attributes on existing `EnergyBatteryStrategySensor` exposing the current optimization situation (no new entities).

---

## What's Changed — Cycle A: WeatherProviderManager

### New files
- `custom_components/universal_room_automation/domain_coordinators/weather_manager.py` (~530 LoC)

### New entities

| Entity ID | Type | Purpose |
|---|---|---|
| `sensor.ura_weather_active_provider` | Sensor | Active weather entity_id, or `none` / `all_stale` |
| `sensor.ura_weather_apparent_forecast_high` | Sensor | Today's apparent-temperature forecast high (°F) |
| `binary_sensor.ura_weather_divergence` | Binary sensor (`PROBLEM`) | On when ≥2 providers disagree beyond threshold |

All 3 entities have `available` property that returns False when WPM is missing (Bug Class #5 startup-race compliance).

### New CONF keys (CM → Energy step)

| CONF key | Default | Purpose |
|---|---|---|
| `CONF_ENERGY_WEATHER_FALLBACK_1` | (empty) | Failover if primary is stale/unavailable |
| `CONF_ENERGY_WEATHER_FALLBACK_2` | (empty) | Second-level failover |
| `CONF_WEATHER_STALENESS_MAX_HOURS` | 6h | Provider state older than this = stale |
| `CONF_WEATHER_DIVERGENCE_THRESHOLD_F` | 5°F | When ≥2 providers differ by this, divergence sensor turns ON |

Existing `CONF_ENERGY_WEATHER_ENTITY` is preserved as the Primary provider. Single-provider configs continue to work unchanged.

### New dispatcher signals

| Signal | Payload | Fires when |
|---|---|---|
| `SIGNAL_WEATHER_PROVIDER_CHANGED` | `{active, reason}` | Active provider changes (failover) |
| `SIGNAL_WEATHER_DIVERGENCE_DETECTED` | `{divergence_f, provider_highs}` | Divergence transitions from cleared → divergent (transition-guarded; not unbounded spam) |

### Architectural primitives

- **`asyncio.Lock` re-entrancy guard** on `_refresh_all_providers` — serializes concurrent state-change handler invocations across 3 providers.
- **Single-fetch invariant** — each provider's forecast is fetched at most once per refresh; divergence and cached-forecast both derive from the same fetch.
- **Tracked async tasks** — `_pending_refresh_tasks: set[asyncio.Task]` with `add_done_callback` discard + teardown cancellation (Bug Class #19 compliance).
- **Apparent-temperature primitive** — `current_apparent_temp()`, `current_apparent_forecast_high()`, `baseline_delta_for_zone(zone_id, preset)`. Probing order: `apparent_temperature` → `temperature_feels_like` → raw `temperature`. Divergence median uses apparent values when ≥2 are present.

---

## What's Changed — Hotfix: EV TOU Hardening

### D1: Strict EV TOU re-pause

`domain_coordinators/energy_pool.py:EVChargerController.determine_actions()` — removed the `if state["is_on"] and evse_id not in self._paused_by_us` guard. Pause is now re-issued on every decision tick during the active policy period. `_paused_by_us` is used **only** for resume tracking, never for enforcement gating.

**Policy:** *"All grid charging for EV should happen only during off-peak for every season."* Manual HA-side EVSE toggles are intentionally defeated within one decision cycle.

### D2: SIGNAL_ENERGY_COORDINATOR_READY

New dispatcher signal `ura_energy_coordinator_ready` in `domain_coordinators/signals.py`. Fires from `__init__.py` after `hass.data[DOMAIN]["coordinator_manager"]` is set AND `coordinator_manager.async_start()` returns. EC sub-switches subscribe via `_handle_ec_ready` and re-apply saved values from RestoreEntity even when EC init was delayed beyond the v4.5.3 retry budget.

**Sub-switch sync tracking:** new `EnergyCoordinator._pending_sub_switch_restores` counter (starts at 5) + `notify_sub_switch_restore_complete()` + `sub_switches_synced() -> bool` accessor. New `binary_sensor.ura_energy_coordinator_ec_sub_switches_synced` (PROBLEM device class) reports True until all 5 EC sub-switches have completed their deferred restore.

### D3: Force-Charge Admin Override Button

`button.ura_energy_coordinator_evse_force_charge_30min` — single legitimate bypass path for the strict TOU policy.

- **When pressed:** opens 30-min force-charge window; URA's TOU pause is bypassed for all EVSEs; fires NM info notification with UTC expiry; logs activation.
- **Auto-expiry:** the window expires after 30 minutes; URA resumes strict enforcement on the next decision cycle.
- **Idempotent re-press:** pressing during an active window replaces (not extends/stacks) the window — prevents accidental compounding.
- **Visibility:** `switch.ura_energy_coordinator_ev_tou_management` gains `override_active_until_iso` attribute.
- **Reload-safe:** ISO expiry persisted via `ECEvTouSwitch.async_added_to_hass` / RestoreEntity. Mid-window reload resumes the original window for its remaining duration. Expired ISOs silently skipped (safe-default).

### D4: Energy Optimization Visibility Attributes

`EnergyBatteryStrategySensor` (existing entity) gains new attributes describing the current optimization situation. No new entities. Pure visibility add — no behavior change.

---

## New Bug Classes

### Bug Class #43 — Bookkeeping Short-Circuit Defeated by External State Change

A control loop with a "did we do this?" bookkeeping set, gated on `if entity_id not in self._handled_by_us`. External state changes (user, HA automation, other integration) leave the set stale; the loop skips re-issuing the command; policy is silently defeated. Documented in `docs/QUALITY_CONTEXT.md`. v4.7.x EV TOU D1 fix is the canonical example.

### Bug Class #44 — Cross-File `sys.modules` Pollution in Test Harness

Tests using module-level `sys.modules.setdefault(...)` + frozen `_FIXED_NOW` time mocks pollute downstream test modules in the same pytest session. First file to import wins the process-wide mock; downstream tests see frozen time + wrong module proxies. Fix: use force-set (`sys.modules[name] = ...`) and/or extract shared mocks to `conftest.py`. Documented in `docs/QUALITY_CONTEXT.md`. v4.7.x Cycle A fix is the canonical example (cross-contamination between EV TOU + WPM test files).

**`docs/QUALITY_CONTEXT.md` count:** 33 documented bug classes (was 31; +#42 from v4.6.15 + #43 from EV TOU + #44 from Cycle A).

---

## Review Documentation

### EV TOU Hotfix (Tier 2 — 2 parallel reviewers, different framings)

| Reviewer | Framing | Verdict | Doc |
|---|---|---|---|
| A | Correctness + edge cases | 1 HIGH, 4 MEDIUM, 2 LOW | `docs/reviews/code-review/v4.7.x_ev_tou_hardening_reviewerA.md` |
| B | Async + lifecycle + race conditions | **1 CRITICAL**, 2 HIGH, 3 MEDIUM, 3 LOW | `docs/reviews/code-review/v4.7.x_ev_tou_hardening_reviewerB.md` |

CRITICAL B1 (signal ordering) and both HIGHs fixed in commit `49e65a9`. MED/LOW deferred to plan-doc backlog. 7 new tests added (40 total pass).

### Cycle A WPM (Tier 2-DB — 3 parallel reviewers + 4th focused pass)

| Reviewer | Framing | Verdict | Doc |
|---|---|---|---|
| A | Data integrity + DB architecture | **2 CRITICAL**, 2 HIGH, 3 MEDIUM, 2 LOW | `docs/reviews/code-review/v4.7.x_dynamic_preset_cycleA_reviewerA.md` |
| B | Migration correctness + signal chain | **3 CRITICAL**, 3 HIGH, 4 MEDIUM, 2 LOW | `docs/reviews/code-review/v4.7.x_dynamic_preset_cycleA_reviewerB.md` |
| C | New surfaces + test fixture authority | **2 CRITICAL**, 3 HIGH, 4 MEDIUM | `docs/reviews/code-review/v4.7.x_dynamic_preset_cycleA_reviewerC.md` |
| D (4th pass) | Focused verification of fix-up surface | **All 10 fixes verified, no regressions, deploy-ready** | `docs/reviews/code-review/v4.7.x_dynamic_preset_cycleA_4thpass.md` |

After de-dup across A+B+C: 4 distinct CRITICAL + 6 distinct HIGH. All fixed in commits `bc71f5c` + `0fd1980`. 13 new tests added (65 WPM tests total). MED/LOW deferred to plan-doc Post-Review Backlog.

---

## Tests

- **EV TOU cycle suite:** 40 tests pass (33 original + 7 reviewer fix-up)
- **WPM cycle suite:** 65 tests pass (52 original + 13 reviewer fix-up)
- **Both orderings (Bug Class #44 fix verification):** `pytest test_v47x_ev_tou_hardening.py test_v47x_weather_manager.py` AND reverse → 105/105 pass
- **Full URA suite (develop HEAD):** 3728 passed / 56 failed / 14 errors. **2 fewer failures than baseline** (Bug Class #44 fix incidentally repaired pre-existing test-isolation pollution elsewhere). All 56 failures + 14 errors are pre-existing missing-HA-dep issues unrelated to this release.

---

## Acceptance Criteria — Live Validation

After deploy + HACS download + restart, verify on the live HA instance:

1. **Cycle A — entities present and producing real values**
   - `sensor.ura_weather_active_provider.state` is a weather entity_id (not `none`, not `all_stale`)
   - `sensor.ura_weather_apparent_forecast_high.state` is a number in plausible degF range (50–115)
   - `binary_sensor.ura_weather_divergence.state` is `off` (no divergence by default with one provider)

2. **Cycle A — config-flow surfaces 4 new fields**
   - Settings → Devices & Services → URA Coordinator Manager → Configure → Energy step shows Primary + Secondary + Tertiary weather pickers + staleness + divergence threshold sliders.

3. **Hotfix D1 — strict TOU re-enforcement (only verifiable during peak/mid_peak TOU)**
   - During a peak/mid_peak window, manually toggle `switch.evse_a` to ON in HA Developer Tools.
   - Within ≤5 min, URA's decision cycle turns it back off and logs:
     `EVSE garage_a paused (TOU mid_peak: $0.X/kWh)`
   - `_paused_by_us` should NOT prevent re-pause.

4. **Hotfix D2 — sub-switch restore on next HA restart**
   - Before restart: note the on/off state of any 1 of the 5 EC sub-switches (e.g. `switch.ura_energy_coordinator_grid_import_cap`).
   - After restart: same on/off state is preserved.
   - `binary_sensor.ura_energy_coordinator_ec_sub_switches_synced` is `off` (no problem) within ~30s of EC registering.

5. **Hotfix D3 — force-charge admin override**
   - During peak/mid_peak with EVSE plugged in but URA-paused: press `button.ura_energy_coordinator_evse_force_charge_30min`.
   - Within ≤5 min: EVSE turns ON; NM notification fires; `switch.ura_energy_coordinator_ev_tou_management.override_active_until_iso` shows UTC expiry 30 min out.
   - After ~30 min: URA pauses EVSE again; `override_active_until_iso` is `null`.

6. **No HA-core warnings introduced**
   - `ha_get_logs(source="system_service", slug="core")` for `universal_room_automation` — zero new ERROR/WARNING entries beyond pre-deploy baseline.

7. **No frame-helper violations**
   - Zero `"calls async_create_task from a thread other than the event loop"` warnings (the v4.6.15 invariant must hold; nothing new added regresses it).

---

## What's Deferred to Future Cycles

- **Cycle B — Dynamic Preset Override Source:** consumes the WPM apparent-temp primitive shipped here; implements per-zone delta-based preset ranges with 1-hour dwell + ±2°F hysteresis. Plan locked at `docs/planning/PLANNING_v4.7.x_dynamic_preset_management.md` §B. Not in this release.
- **EV TOU MED/LOW backlog:** 9 items in `docs/planning/PLANNING_v4.7.x_ev_tou_hardening.md` "Post-review backlog" — private-attribute cleanup, naive-datetime validation, duplicated expiry checks, fragile type hints.
- **Cycle A WPM MED/LOW backlog:** ~14 items in `docs/planning/PLANNING_v4.7.x_dynamic_preset_management.md` Post-Review Backlog — public accessors for currently-private WPM methods, dead `update_options()` cleanup, AST-test refinement, missing `EntityCategory.DIAGNOSTIC`, etc.

---

## Files Touched (summary)

```
custom_components/universal_room_automation/
  __init__.py                                        — WPM wiring + B1 ordering fix
  binary_sensor.py                                   — WeatherDivergence + ECSubSwitchesSynced sensors
  button.py                                          — force-charge admin override
  config_flow.py                                     — 4 new form fields
  sensor.py                                          — WPM sensors + battery-strategy attrs
  switch.py                                          — ECEvTouSwitch RestoreEntity + sub-switch notify
  domain_coordinators/
    energy.py                                        — restore-counter accessor + signal emit
    energy_const.py                                  — 5 new CONFs + defaults
    energy_pool.py                                   — D1 strict re-pause + force_charge_override
    signals.py                                       — 3 new dispatcher signals
    weather_manager.py                               — NEW: WeatherProviderManager singleton

docs/
  QUALITY_CONTEXT.md                                 — Bug Class #43 + #44
  readmes/README_v4.7.0.md                           — this file
  planning/PLANNING_v4.7.x_dynamic_preset_management.md  — locked plan + Post-Review Backlog
  planning/PLANNING_v4.7.x_ev_tou_hardening.md       — locked plan + Post-review backlog
  planning/PLANNING_v4.7.x_guest_mode_actuation_phase1.md — Phase 2 candidate added earlier in this session
  reviews/code-review/v4.7.x_*.md                    — 7 review docs (3 + 1 4th-pass + 2 + …)
  user-manual/ENERGY_COORDINATOR.md                  — §10 admin override + §11 WPM sections

quality/tests/
  test_v47x_ev_tou_hardening.py                      — 40 tests
  test_v47x_weather_manager.py                       — 65 tests
```

---

## Migration Notes

- **Single-provider configs:** existing `CONF_ENERGY_WEATHER_ENTITY` continues to work as Primary. Secondary/Tertiary are opt-in.
- **No schema migration required.** All new CONF keys are `vol.Optional` with sensible defaults.
- **No DB schema changes.** EnergyConstraint payload extended with `apparent_forecast_high_temp: float | None = None` — additive, all 6 existing consumers audited as safe.
- **EC sub-switch restore is more reliable now.** Previously, sub-switches falling outside the v4.5.3 retry budget would silently keep constructor-seed values across reboots. The new SIGNAL_ENERGY_COORDINATOR_READY path catches all 5.
