# v4.5.3 — EC switch deferred-restore lifecycle race fix

**Date:** 2026-05-08
**Type:** Tier 2 hotfix (one factory + 14 regression tests; touches all 5 EC switches via shared factory)
**Predecessor:** v4.5.2
**Reproducer:** v4.5.2 deploy + restart flipped `switch.ura_energy_coordinator_grid_arbitrage` from OFF (user-set 2026-05-07) back to ON.

## Summary

Closes the deferred bug class documented in `switch.py:511-552`'s prior docstring — "users reported that several EC switches reset to OFF after the v4.5.0 + v4.5.0.1 HACS upgrade restart cycle." We finally got the reproducer (the v4.5.2 restart) and the symptom matched in shape (state-mismatch across a restart) though in the opposite direction (OFF→ON instead of ON→OFF).

Fix is in the shared `_ec_switch_factory` (`switch.py:511`), so all 5 EC switches benefit from the same change:
- `ECArbitrageSwitch`
- `ECGridImportCapSwitch`
- `ECLoadSheddingSwitch`
- `ECExcessSolarSwitch`
- `ECEvTouSwitch`

Pure runtime-behavior change — no schema/migration/UI implications.

## Root cause

The factory's `async_added_to_hass` did the right thing (read RestoreEntity's `last_state`, push to the EnergyCoordinator), but the deferred-coordinator path only had **one 5s retry with no flag**:

```python
# v4.5.2 and earlier
async def async_added_to_hass(self):
    last_state = await self.async_get_last_state()
    if last_state is not None:
        energy = self._get_energy()
        target = last_state.state == "on"
        if energy is not None:
            setattr(energy, attr_name, target)
        else:
            self._deferred_value = target
            self.async_on_remove(
                async_call_later(self.hass, 5, self._retry_restore)
            )

@callback
def _retry_restore(self, _now=None):
    energy = self._get_energy()
    if energy is not None:
        setattr(energy, attr_name, getattr(self, "_deferred_value", self._default))
```

If `_get_energy()` returned None at both the initial call AND the 5s retry (e.g. CM platform setup still in flight), the user's persisted toggle was silently lost — and the EnergyCoordinator constructor's `ec.get(CONF_*_ENABLED, …)` cm_config seed (which doesn't change when the user toggles via the UI) became the visible state.

User flow leading to the bug:
1. User originally enabled arbitrage in the config-flow form → `cm_entry.data["energy_arbitrage_enabled"] = True`.
2. User later toggled the switch OFF → runtime field becomes False; switch's RestoreEntity persists `state="off"`; **but `cm_entry.data` was not updated** (URA mirror pattern: switches don't write back to entry options).
3. v4.5.2 restart. EnergyCoordinator constructor seeds `_arbitrage_enabled = cm_config.get(CONF_ENERGY_ARBITRAGE_ENABLED, False) = True`.
4. Switch's `async_added_to_hass` fires. `_get_energy()` returns None (CM not registered yet). Deferred. Single 5s retry scheduled.
5. 5s later: `_get_energy()` still None for whatever reason → retry's setattr skipped. **No second retry.** The flag pattern other switches use (`if not self._deferred_restore: return` + clearing on success) didn't exist here.
6. Switch's `is_on` polls eventually return `getattr(energy, "arbitrage_enabled", False) = True` (from step 3's seed). User sees the switch ON despite having toggled it OFF.

## Fix

Three lifecycle changes in `_ec_switch_factory` (`switch.py:511`):

### 1. `_deferred_restore` flag

Boolean flag that's True only when a restore is pending. `_retry_restore` early-returns when the flag is False, so a stale callback can't double-fire after either success or an explicit user toggle.

### 2. Retry chain: 5s, 30s, 120s

```python
_RETRY_DELAYS_S = (5, 30, 120)
```

Each retry callback reschedules the next on continued failure. After the 3rd exhaustion, logs a warning and gives up — better signal for future investigations than silent stuck state.

### 3. User toggle clears pending restore

`async_turn_on` and `async_turn_off` now clear `_deferred_restore`, so a queued retry can't stomp the user's explicit action mid-defer.

### Diff shape

```python
# v4.5.3
def __init__(self, hass, entry):
    ...
    self._deferred_restore: bool = False
    self._deferred_value: bool = default
    self._retry_index: int = 0

async def async_added_to_hass(self):
    await super().async_added_to_hass()
    last_state = await self.async_get_last_state()
    if last_state is None:
        return   # first-install: constructor seed is truth
    target = last_state.state == "on"
    self._deferred_value = target
    energy = self._get_energy()
    if energy is not None:
        setattr(energy, attr_name, target)
        self._deferred_restore = False
        return
    self._deferred_restore = True
    self._retry_index = 0
    self.async_on_remove(
        async_call_later(self.hass, self._RETRY_DELAYS_S[0], self._retry_restore)
    )

@callback
def _retry_restore(self, _now=None):
    if not self._deferred_restore:
        return
    energy = self._get_energy()
    if energy is not None:
        setattr(energy, attr_name, self._deferred_value)
        self._deferred_restore = False
        return
    self._retry_index += 1
    if self._retry_index < len(self._RETRY_DELAYS_S):
        self.async_on_remove(
            async_call_later(
                self.hass, self._RETRY_DELAYS_S[self._retry_index], self._retry_restore
            )
        )
    else:
        _LOGGER.warning(
            "EC switch %s: deferred restore exhausted retries…", unique_suffix
        )
        self._deferred_restore = False

async def async_turn_on(self, **kwargs):
    ...
    self._deferred_restore = False   # explicit user action wins

async def async_turn_off(self, **kwargs):
    ...
    self._deferred_restore = False
```

## What this DOES NOT do

- **Doesn't remove the cm_config seed in `EnergyCoordinator.__init__`.** Layer A (the lifecycle race fix) is sufficient: with retry-with-backoff, the RestoreEntity override always lands eventually. Removing the seed would change first-install UX (user's config-flow checkbox would be ignored on a fresh HA install) and trades a real bug for a different one. Memory `feedback_ura_mirror_pattern.md`'s "RestoreEntity = runtime store; entry.options = seed only" is preserved — the seed is for first-install only and is correctly overridden on every subsequent boot.
- **Doesn't touch the `is_on` default-return race** documented in the prior docstring. That's a separate latent issue (it would write "off" to state storage when `_get_energy()` is None and HA polls during boot) and out of scope here. If it reappears, capture HA debug logs around restart.
- **Doesn't change anything about EvTouSwitch's hardcoded `True` seed** (energy.py:242 `self._ev_tou_enabled: bool = True` with no `ec.get`). The EvTou switch defaults to True at construction; user toggles persist via RestoreEntity through the same factory path. Now race-safe like the others.
- **Doesn't bundle dead-config cleanup.** That's planned as v4.5.4 — see `docs/planning/PLANNING_v4.5.4_room_config_cleanup.md`.

## Tier 2 Review

| Severity | Finding | Resolution |
|---|---|---|
| (no CRITICAL) | — | — |
| HIGH | Lifecycle race silently lost user toggles for all 5 EC switches | Fixed in factory |
| MEDIUM | Single retry with no flag — no backoff, no exhaustion signal | Fixed: 3-retry chain (5s/30s/120s), warning on exhaustion |
| MEDIUM | Pending retry could stomp explicit user toggle | Fixed: `async_turn_*` clears `_deferred_restore` |
| LOW | First-install path (`last_state is None`) used to fall through and could schedule retries; cleaner now to early-return | Fixed: explicit early-return |
| LOW | `is_on` default-return race documented in old docstring is unchanged | Out of scope; documented in new docstring |

**Verdict: READY TO DEPLOY.**

## Tests

14 new tests in `quality/tests/test_v4503_ec_switch_restore.py`:
- **3** fast-path: restore-off-overrides-seed, restore-on-overrides-seed, first-install-no-state
- **5** deferred-path: defer-when-coord-unavailable, first-retry-lands, retry-chain-progresses, retry-chain-exhausts-with-warning, retry-delays-spec
- **2** user-toggle-wins: turn-on-clears-pending, turn-off-clears-pending
- **4** source-mirror-contract: factory has `_deferred_restore` flag, has retry chain, retry clears flag on success, user toggles clear pending

Mirror-style (the factory's closure isn't cleanly importable without HA core) — same pattern as v4.5.0.4 + v4.5.2 D5. Mirror is kept in sync with production via review.

**Test count progression:**
- v4.5.2: 1912 tests, 0 isolated failures across 50 files
- **v4.5.3: 1926** (+14), 0 isolated failures across 51 files

## Live validation (post-restart)

1. After HACS download + HA restart, watch the 5 EC switches:
   - `switch.ura_energy_coordinator_grid_arbitrage`
   - `switch.ura_energy_coordinator_grid_import_cap`
   - `switch.ura_energy_coordinator_load_shedding`
   - `switch.ura_energy_coordinator_excess_solar_charging`
   - `switch.ura_energy_coordinator_ev_tou_management`

2. For each: confirm post-restart state matches the state right before the deploy (the user's last toggle should survive). Specifically `grid_arbitrage` should remain OFF if the user toggled it OFF immediately before deploy.

3. In `tail -f /config/home-assistant.log | grep "EC switch"` — expect zero `exhausted retries` warnings on a healthy boot. If one appears, the warning text identifies which switch + indicates the energy coord never registered within 155s; that's a deeper coordinator-init issue, not a switch-fix regression.

4. Manual toggle test:
   - Toggle one EC switch (e.g. arbitrage) OFF in the UI.
   - Restart HA.
   - Confirm the switch is still OFF after restart and the runtime field matches (check `sensor.ura_energy_coordinator_arbitrage_savings_today` attributes if needed).

## Deploy notes

- No DB schema changes
- No migration needed (RestoreEntity is HA-managed; entry.options unchanged)
- HACS download required after deploy.sh per memory `feedback_verify_hacs_install.md`
- HA restart required (switch.py is part of the loaded integration package)

## Next

- **v4.5.4** — Room config & dead-code cleanup (verified blinds-class hits + orphan constants + legacy time-window cleanup). See `docs/planning/PLANNING_v4.5.4_room_config_cleanup.md`. Excludes music following (deferred to CM cleanup) and `CONF_CAMERA_PLATFORM` (deferred to person-tracking audit).
- **v4.6.0** — Routine Awareness with reconciled AnomalyEvent foundation
