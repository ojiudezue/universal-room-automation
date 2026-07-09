# URA v5.8.1 — Hotfix: reconciler construction-order crash (v5.8.0 was rolled back)

**v5.8.0 must not be run.** It shipped the Reconcile-on-Return feature but crashed **every room's setup** on the live house (37/40 config entries → `setup_error`). It was rolled back to v5.7.2 within minutes; the house was never left broken. v5.8.1 is v5.8.0 + the one-line fix that makes setup succeed, plus a new real-construction test tier so this class can't ship green again.

## Root cause (reproduced locally)
`ActuatorReconciler` was constructed in `UniversalRoomCoordinator.__init__` **before** `super().__init__()` ran. `DataUpdateCoordinator.__init__` (super) is what sets `self.hass`; the reconciler's own `__init__` reads `coordinator.hass`, so it accessed an attribute that did not exist yet.
- On **HA 2026.2** this raises `AttributeError: 'UniversalRoomCoordinator' object has no attribute 'hass'`.
- On the house's **HA 2026.7** the identical premature access surfaced as a **RecursionError** (newer HA resolves a missing `hass` via a different path).

Same root cause, fatal to setup either way. It passed 65 unit tests + 4 Tier-3 reviews + mutation verification because **every test used a fake coordinator that already had `.hass`** — the real construction path (`coordinator.py` → `ActuatorReconciler(self)`) was never exercised, and the runtime-smoke tier silently skips wherever `homeassistant` isn't installed.

## The fix
Move `self._actuator_reconciler = ActuatorReconciler(self)` to **after** `super().__init__()` in `coordinator.py`. One-line reorder; no behavior change to the reconciler itself. Reproduced the crash and confirmed the fix under a real HA (2026.2) via pytest-homeassistant-custom-component.

## New: real-coordinator construction test tier
`quality/real_construction/` constructs the **real** `UniversalRoomCoordinator` against a real Home Assistant and arms the reconciler's listener. It fails without the fix, passes with it. It `importorskip`s `homeassistant`, so it skips cleanly on a mock-only dev box and runs where HA is installed (`.venv-ha/bin/python -m pytest quality/real_construction/`). This is the missing tier the incident exposed — construction-order and other integration-time bugs now have a home that isn't a fake coordinator.

## Gate
No conflict markers; `py_compile` clean; **122 reconcile/room tests pass** (mock harness); full suite at the documented 35-failed / 14-error ordering-flake baseline — **zero new failures**. Real-construction tier: **1 passed** under HA 2026.2. Deploy is from `develop` (the v5.8.0 deploy-from-feature-branch mistake is not repeated).

---

## Acceptance

```yaml
version: 5.8.1
hypotheses:
  - id: H1
    name: ura_v581_deployed_and_rooms_loaded
    description: v5.8.1 is installed AND all URA room entries load (no setup_error).
    oracle: home_assistant
    query: { kind: home_assistant.state_attribute, entity: update.universal_room_automation_update, attribute: installed_version }
    expected: { condition: "==", value: "v5.8.1" }
    window: { first_check_after: 10m, confirm_after: 1h, alert_if_violated_after: 6h }
  - id: H2
    name: no_setup_error
    description: No URA config entry is in setup_error after restart (the v5.8.0 failure mode).
    oracle: home_assistant
    query: { kind: home_assistant.log_count, search: "setup_error", period: 1h }
    expected: { condition: "<", value: 1 }
    window: { first_check_after: 10m, confirm_after: 1h, alert_if_violated_after: 6h }
  - id: H3
    name: reconcile_sensors_live
    description: The reconcile health sensor publishes a value (feature actually loaded).
    oracle: home_assistant
    query: { kind: home_assistant.state_attribute, entity: sensor.universal_room_automation_reconcile_health, attribute: total_reconciles_today }
    expected: { condition: "!=", value: "unknown" }
    window: { first_check_after: 10m, confirm_after: 1h, alert_if_violated_after: 24h }
```

## Live Validation — Validated 2026-07-06 (post-restart)
| # | Criterion | Result | Observed evidence |
|---|---|---|---|
| L1 | Rooms load (the exact v5.8.0 regression) | **PASS** | `ha_get_integration universal_room_automation` → `state_summary: {loaded: 40}`. **Zero `setup_error`** (v5.8.0 had 37/40 in setup_error). |
| L2 | Version | **PASS** | `update.universal_room_automation_update` installed_version = `v5.8.1`. |
| L3 | Reconcile feature actually live | **PASS (stronger than planned)** | `sensor.universal_room_automation_reconcile_health` state = `3` (`total_reconciles_today: 3`) — the reconciler not only loaded but already re-asserted 3 actuators post-boot. `rooms_with_auto_recovery_off: []` (all rooms armed). |
| L4 | No error storm | **PASS** | `error_log` search `RecursionError` = 0 lines. |

The construction-order fix is confirmed on the live house: every room set up cleanly and reconcile-on-return is functioning. The deeper v5.8.0 feature-level checks (AV-closet reconcile canary, coalesce, flap quarantine, no write spike from README_v5.8.0.md) now ride on this working base and can be observed on the next real WiFi/actuator event.
