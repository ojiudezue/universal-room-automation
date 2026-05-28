# URA v4.7.3.1 — HVAC Bespoke Switches Restore Hotfix

**Release date:** 2026-05-28
**Tier:** Tier 1 (hotfix — single adversarial review)
**Scope:** 3 bespoke HVAC `SwitchEntity + RestoreEntity` switches + 1 new signal constant + dispatch site

**Trigger:**
- User-reported AC Ramp Down (`switch.ura_hvac_ac_ramp_master`) flipping to OFF multiple times across restarts.
- Root-cause investigation found the same Bug Class #5 (startup race) pattern on all three bespoke HVAC switches: no deferred-restore mechanism when the HVAC coordinator was not yet registered in `hass.data["coordinator_manager"]` at `async_added_to_hass` time. The switches silently dropped `RestoreEntity` state, reverting to constructor defaults.
- `HVACDynamicPresetSwitch` (v4.7.2 D2) was NOT at risk — it was built via `_ec_switch_factory` reuse and inherited the existing deferred-restore path.

---

## Bug

Three bespoke HVAC switches lacked the SIGNAL-based deferred-restore mechanism present in EC factory-built switches since v4.5.3 / v4.7.x D2:

| Switch | Entity | Backing field | Default |
|---|---|---|---|
| `HVACGuestModeActuationSwitch` | `switch.ura_hvac_coordinator_guest_mode_actuation_enabled` | `hvac._guest_mode_actuation_enabled` | ON |
| `HVACOverrideArresterSwitch` | `switch.ura_hvac_override_arrester` | `hvac.override_arrester.enabled` | ON |
| `HVACACRampMasterSwitch` | `switch.ura_hvac_ac_ramp_master` | `hvac._override_arrester.ramp_master_enabled` | OFF |

If the HVAC coordinator was not registered when `async_added_to_hass` fired, the conditional `if hvac is not None: …` block was skipped entirely. The saved `RestoreEntity` value was never written to the coordinator, and the first HVAC decision cycle saw the constructor default.

---

## Fix

### 1. `SIGNAL_HVAC_COORDINATOR_READY` (signals.py)

New constant parallel to `SIGNAL_ENERGY_COORDINATOR_READY` (v4.7.x D2):

```
SIGNAL_HVAC_COORDINATOR_READY: Final = "ura_hvac_coordinator_ready"
```

### 2. Dispatch site (domain_coordinators/hvac.py)

Dispatched at the end of `HVACCoordinator.async_setup()`, after the initial decision cycle and setup-complete log — same placement pattern as the EC signal in `energy.py`.

### 3. Deferred-restore pattern on each switch (switch.py)

For each of the 3 switches:

- `self._deferred_value: bool | None` instance var added; initialized to `None`.
- `async_added_to_hass` registers a `SIGNAL_HVAC_COORDINATOR_READY` subscription via `async_dispatcher_connect`, tracked with `async_on_remove` (Bug Class #38).
- **Fast path:** if HVAC coord is present at `async_added_to_hass` time, the restored value is applied immediately, `_deferred_value` stays `None`.
- **Deferred path:** if HVAC coord is absent, `_deferred_value` is set; `_handle_hvac_ready` callback applies it when the signal fires.
- `_handle_hvac_ready` is a `@callback` (not `async`, not a lambda — Bug Class #42/#19).

**Structural note for `HVACACRampMasterSwitch`:** This switch uses `_get_arrester()` (not `_get_hvac()`) because its backing field lives on `hvac._override_arrester`. `_handle_hvac_ready` also calls `_get_arrester()` for consistency — the HVAC-coordinator-ready signal fires after the arrester sub-object is fully constructed inside `async_setup()`.

No `_pending_sub_switch_restores` counter added — HVAC has no analogue of `ECSubSwitchesSyncedSensor`. Fire-and-forget restore is acceptable.

---

## Files Changed

- `custom_components/universal_room_automation/domain_coordinators/signals.py` — `SIGNAL_HVAC_COORDINATOR_READY` constant (after `SIGNAL_ENERGY_COORDINATOR_READY`)
- `custom_components/universal_room_automation/domain_coordinators/hvac.py` — dispatch site at end of `async_setup()`
- `custom_components/universal_room_automation/switch.py` — deferred-restore pattern in `HVACGuestModeActuationSwitch`, `HVACOverrideArresterSwitch`, `HVACACRampMasterSwitch`
- `quality/tests/test_v4731_hvac_switches_restore.py` — 27 new tests (fast-path, deferred-path, symmetric ON/OFF, signal infra, source-mirror contract)

---

## Tests

27 tests in `quality/tests/test_v4731_hvac_switches_restore.py`. Both pytest orderings pass.

Bug class compliance verified: #5 (startup race), #38 (dispatcher unsub via async_on_remove), #42 (bound method not lambda), #19 (no async in callback).
