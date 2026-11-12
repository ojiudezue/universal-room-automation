# Review B: lifecycle, restart, cross-coordinator ripple. fix/zone-sweep-cleanup

Branch `fix/zone-sweep-cleanup`, commits 6e70d194 and 2a6c790a. Diff base is `e3c75a99`, the merge-base with develop (verified).
Card HVAC-ZONE-SWEEP-PURPOSE-AND-FIXES-1. Reviewer read `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` in full first. No §10 claim is re-asserted.
Targeted tests: `test_hvac_zone_sweep_cleanup.py`, `test_restore_guard_52_sweep.py`, `test_zzz_hvac_conditioning_demand.py`, 67 passed.

## Verdict: FIX-REQUIRED (1 HIGH)

## Findings

### B-H1 HIGH: manual-device loop bypasses every fan rule, and live config reaches it (Bug Class #53, one missed site)
`hvac.py` manual-device loop (~6828-6866). It skips `lights` and `_leave_on` but not `fans`. `manual_devices` accepts `fan.*` (`const.py:1041`).
Live `.storage/core.config_entries`: **Master Bedroom** (zone_1) has `fan.master_ceiling_fan_2` in both `manual_devices` and `fans`.
- On every real sweep this fan is turned off whatever the other gates say. The skipped gates are: the pre-arrival exemption (fix #4 of this cycle), Fan Mode (Room temperature / Off), manual-ON holds and the W8 oracle. Fix #4 does not hold for this fan. Repro: zone_1 has an active pre-arrival, house goes `arriving -> home_day`, the zone is past grace with target home, the fan was lit by `_activate_zone_fans` and is turned off by the manual loop.
- `ura_ctx_kwargs("fan")` returns `{}` (`ura_context.py:71-84`: light/switch/scene only). If FanController tracks the fan as on (Follow thermostat), its next `update()` books "turned off externally" and sets the 1 h `manual_off_cooldown` (`hvac_fans.py:688`). That is a false person-OFF.
- **Fix:** skip `entity_id in fans` in the manual loop, so fans go only through the fan block. Add a test where the same fan is in both lists, with pre-arrival active and with Fan Mode Room. (Restricting the loop to non-fan domains also works.)

### B-L1 LOW: one cycle after a parent-entry rebuild can sweep while the switch is OFF (quantified, acceptable)
- `_vacancy_sweep_master_enabled` defaults True (`hvac.py:833`).
- READY is dispatched after the initial cycle (`hvac.py:1696` then `:1704`).
- **Cold boot: safe.** Boot-settle suppresses the initial cycle (`hvac.py:1928`). READY lands, or the switch pushes directly if HVAC is already registered (`register_coordinator` at `__init__.py:4445` runs before `async_start`), before the release kick.
- **Parent/CM rebuild while HA is running:** `_boot_settle_done=True` immediately (`hvac.py:1301`), and the switch entity is not re-added. Exposure is at most the one initial `_async_decision_cycle`, and only for zones that are lighting-empty, past grace, target home/sleep and not yet swept. After that READY re-pushes OFF.
- **Before this branch the same case was unbounded:** rebuilt zones took the config value (True), and the switch never re-pushed until a toggle or restart. Strict improvement. Optional hardening: have the coordinator pull the switch's state in `async_setup` before the initial cycle.

### Cleared
- **Listener lifecycle:** the READY subscription goes through `async_on_remove` (`switch.py:4075`), and `_handle_hvac_ready` is a `@callback`. Same pattern as the 12 sibling HVAC switches. No leak on entity removal. Multiple READY fires are idempotent (a plain assignment).
- **Restart persistence:** the master value is restored through RestoreEntity (`switch.py:4068`, only on/off accepted, so `unavailable` does not flip it). The per-zone flag is ZM config (durable) and is no longer overwritten, so a ZM zone rebuild keeps it correctly. Before, the zone value was clobbered by the switch value only at add/toggle time, and was lost on a zone rebuild. `vacancy_sweep_done` is RAM. A post-boot first sweep of empty zones is pre-existing behaviour and unchanged.
- **Activity-log writer:** `ActivityLogger.log` goes through `database.log_activity` (the shared write queue) and never raises. It is called fire-and-forget via `hass.async_create_task`, the same as other hvac.py callers (`:1984`, `:2661`). It is untracked, but the coroutine is short and swallows its own errors, so this matches the pre-existing pattern rather than adding a new class of issue. Volume is about 10 % of ~173 fires a week, so ~17 rows a week, one per real sweep and never per entity. `details` is well under 2 KB. `importance="notable"`, and the dedup key includes the description (entity list), so distinct sweeps are not deduped away.
- **Manual light hold / reconciler:** manual devices that are also lights are skipped. Other manual devices are not in `_light_entities()`, so `_note_manual_light_change` ignores them (`actuator_reconciler.py:505`). It also requires the room to be occupied, which is false during a sweep. switch/light manual devices carry the URA context. No false person-hold for non-fan manual devices.
- **Operator note (not a defect):** live manual devices that a sweep will now turn off include `switch.game_room_tv`, `switch.q_series_soundbar` and `switch.switch_tapo_wifi_kitchenrange`. The room tier already turns these off on room exit (`automation._control_manual_switches_off`), so behaviour is consistent. They are listed so the operator is not surprised by the activity rows.
- **Pre-arrival exemption lifecycle:** `_pre_arrival_zones` is read live on each sweep. When pre-arrival ends on timeout or max age, `_deactivate_zone_fans` turns the fans off on its own path. When it ends by arrival, the zone is occupied, so there is no sweep and the fan controller owns the fans. If the zone empties later, the next vacancy sweeps the fans normally (`vacancy_sweep_done` is re-armed by lighting occupancy). One subtlety: a sweep during pre-arrival sets `done=True` with the fans kept. If the person never arrives, `_deactivate_zone_fans` discharges them. That is acceptable.
- **Observation mode:** the guard is still the first statement of `_execute_vacancy_sweep` and returns `[]`. `_maybe_run_vacancy_sweep` then sets `done` and does not count, which matches the old shape.
- **Paused rooms:** the whole-room `continue` precedes the manual loop, so paused rooms are skipped (§4.2b holds).

## Bug-class tally
| Class | Count |
|---|---|
| #53 one missed site (fan gate bypass in new loop) | 1 HIGH |
| Boot/reload ordering (bounded, improved) | 1 LOW |

## Must-fix
1. B-H1: exclude `fans` (or the `fan` domain) from the manual-device loop, and add a test where the same fan is in both lists.
