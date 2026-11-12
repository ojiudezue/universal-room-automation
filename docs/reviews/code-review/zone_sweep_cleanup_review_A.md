# Review A (local correctness + edge cases): fix/zone-sweep-cleanup

Card HVAC-ZONE-SWEEP-PURPOSE-AND-FIXES-1. Commits 6e70d194, 2a6c790a. Diff base = merge-base with develop `e3c75a99` (verified with `git merge-base`). HVAC_ARCHITECTURE_STATE_OF_PLAY.md was read completely first. No §10 claim is re-asserted.
Targeted tests (worktree): `test_hvac_zone_sweep_cleanup.py`, `test_restore_guard_52_sweep.py`, `test_zzz_hvac_conditioning_demand.py`: **67 passed**.

## Truth table: gate `_maybe_run_vacancy_sweep` (hvac.py:6711)

| lighting-occupied | done | zone opt-in | master | result |
|---|---|---|---|---|
| T | * | * | * | no run, done unchanged |
| F | T | * | * | no run |
| F | F | F | * | no run (per-zone opt-out honoured, previously overwritten) |
| F | F | T | F | no run (master gate) |
| F | F | T | T | run; done=True always; counter +1 only if something was turned off |

Both callers (3051 row-1, 3116 D6) route through this one gate. Their behaviour matches the old inline blocks except that the counter now counts only real sweeps. Holds.

## Findings

| SEV | Site | Finding | Class |
|---|---|---|---|
| MEDIUM (operator-acceptance, not a code defect) | hvac.py manual-device loop (~6830-6866) | **Yes, it can turn off a device a person deliberately left on in an occupied room.** Repro: a radar-less or undetected room (e.g. the person is sitting still with no sensor coverage) where the person switches on a `manual_devices` relay. The room never reads lighting-occupied, so the room-tier exit (`automation._control_manual_switches_off`, automation.py:1434) never fires, and the zone reads `any_room_occupied=False`. Once grace passes, row-1 sweeps and the relay goes off. Lights already carry this exposure. They at least have `light_hold_allowed`, but that hold only exists for a light switched on while the room read occupied, so it does not help in an undetected room either. Manual devices have no hold at all. This is the audit's intended "fill" (person-switched relays the room tier never turned off), so it is by design. It widens the blast radius from lights to arbitrary relays (equipment, TV, etc.). The operator should explicitly accept it. Mitigations: `lights_leave_on_when_empty` is honoured for manual devices, and pausing the room skips it whole. | design scope |
| LOW | hvac.py manual loop `entity_id in lights` | The skip compares against `lights` **after** the `light_hold_allowed` filter. An entity listed in BOTH `lights` and `manual_devices` that is under a person's ON hold is dropped from `lights` and then turned off by the manual loop, which bypasses the hold. Fix: compare against the pre-hold light list (`regular + night`). | #53 one-missed-site (guard bypass) |
| LOW | same loop | A fan listed in both `fans` and `manual_devices` bypasses the fan rules in the manual loop: the pre-arrival exemption (6766), Fan Mode ownership, the manual-ON hold and W8. Because `fan` is not in `URA_LIGHT_WRITE_DOMAINS` (ura_context.py:71), the write carries no URA context, so FanController's external-change sync may book it as a person's OFF. Fix: also skip `entity_id in fans`. | #53 |
| LOW | hvac_zones.py:1242 | The `vacancy_sweep_enabled` attribute on the zone status sensor now shows only the per-zone value. With the master OFF it still reads True. The value is display-only. Consider adding the master or an `effective` attr. The optimizer advisory (optimization.py:3528) likewise no longer goes quiet when the master is OFF. That advisory is about stuck sensors, so this is harmless. | display drift |
| LOW | manual loop `_actuatable_ids` exception path | A failed guard falls back to the unguarded list (fail-open). This matches the room tier's "never block actuation" contract (automation.py:2029 docstring). Accepted. | — |

## Cleared (holds because)

- **Master/per-zone:** the switch (switch.py:4032) only sets `hvac.vacancy_sweep_master_enabled`. No remaining writer of `zone.vacancy_sweep_enabled` exists outside hvac_zones.py:529/573 (grep). The value is pushed on toggle, on restore (switch.py ~4080) and on READY (`_handle_hvac_ready`, :4083). The READY dispatch has no args (hvac.py:1705), which matches the 0-arg handler. A rebuilt coordinator defaults to True and then gets the repush.
- **Once per vacancy:** `done=True` is set after every run, including a no-op or observation mode. A raise inside execute leaves done False and retries next tick, which is the pre-existing behaviour.
- **Counter/row:** the row and the INFO line are emitted only when `turned_off` is non-empty (hvac.py ~6997). The `activity_logger.log` kwargs match the signature (activity_logger.py:63). The row is fire-and-forget through `async_create_task`, as at other HVAC sites.
- **Pre-arrival scope:** `_pre_arrival_zones` holds zone_ids from `self._zone_manager.zones` (hvac.py:7198), compared with `zone.zone_id`. The exemption is per zone and only affects fans (`continue` sits after the lights and manual loops). Test `test_other_zone_pre_arrival_does_not_exempt_fans` pins this.
- **Manual devices:** off-only, only when the device reads `on`, the registry guard is applied, leave-on is honoured, and a paused room is skipped whole (the `continue` at the top of the room loop). Legacy str/list handling mirrors automation.py:2138-2145.
- **Context stamp:** `ura_ctx_kwargs` stamps light/switch/scene (ura_context.py:71). The room-tier manual-light listener therefore ignores sweep offs of `switch.*`/`light.*` manual devices. fan/input_boolean manual devices are unstamped (see the fan LOW). No input_boolean listener exists.

## Verdict: **SHIP** (no CRITICAL/HIGH)

Recommended in-cycle (LOW, about 2 lines): in the manual loop, skip entities in the pre-hold `lights` list and in `fans`. Surface the MEDIUM to the operator as an explicit acceptance: manual devices in undetected rooms get swept.
