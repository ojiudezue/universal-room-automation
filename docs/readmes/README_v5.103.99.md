# v5.103.99: zone vacancy sweep honours per-zone opt-out, keeps pre-arrival fans, and turns off manual devices

Card: HVAC-ZONE-SWEEP-PURPOSE-AND-FIXES-1. Audit: `docs/planning/AUDIT_zone_sweep_effectiveness.md`. Tier 2, two reviews: A SHIP; B FIX-REQUIRED (1 HIGH), fixed in 553b15d0. Full suite on merged develop: no new failures vs develop (31 pre-existing). Deploy risk: LOW-MEDIUM (turns devices OFF only; never on).

## Problem
- The master switch "Vacancy Auto-Off" overwrote each zone's own sweep setting instead of gating it.
- The sweep turned off fans that pre-arrival had turned on 36-61 s earlier (3 fires, 4 fans in 7 days).
- `vacancy_sweeps_today` counted every flag flip (173 in 7 days, ~90% no-ops); the sweep left no record of what it turned off, so the audit had to attribute by exclusion.
- A room's manual devices (`manual_devices`, legacy `manual_switches`) were never swept.

## Fix
- Master switch AND per-zone `CONF_ZONE_VACANCY_SWEEP_ENABLED`; re-pushed when the HVAC coordinator is ready. Zone status `vacancy_sweep_enabled` shows the effective value.
- One gate (`_maybe_run_vacancy_sweep`) for both callers (row-1 and D6 stale).
- A zone with an active pre-arrival keeps its fans; lights are still swept.
- A real sweep logs one INFO line and one `vacancy_sweep` activity row listing what it turned off; a no-op logs DEBUG only. `vacancy_sweeps_today` counts real sweeps only.
- Manual devices are swept (off only, URA context, through the room's actuatable guard, minus leave-on, paused rooms skipped). Fans are never swept through the manual-device path.
- HVAC state of play §4.2c and §8 updated.

## Tests
`test_hvac_zone_sweep_cleanup.py` (new), `test_restore_guard_52_sweep.py`, `test_zzz_hvac_conditioning_demand.py`.

## Known limits
- B-L1 not built: no call-site anchor test for the ready-signal re-push (needs a full async_setup drive). Noted in state of play §4.2c.
- The 12 fan-on-at-fire cases the audit could not explain are not addressed.

## Live acceptance (prospective)
| Criterion | How to check |
|---|---|
| Real sweeps recorded | A zone sweep that turns something off writes a `vacancy_sweep` activity row naming the entities; no row on a no-op |
| Count is real | `vacancy_sweeps_today` on `sensor.ura_hvac_coordinator_zone_N_status` is small (single digits/day), not ~25 |
| Pre-arrival fans kept | On the next arriving → home transition, pre-arrival fans stay on through the sweep |
| Opt-out honoured | `vacancy_sweep_enabled` attr = master AND zone setting |
| Load clean | No URA ERROR after restart |

## Validated 2026-11-03 ~02:04 CST (overnight pass; deploy 2026-11-02 06:52)

| Criterion | Result | Observed evidence |
|---|---|---|
| Real sweeps recorded | PASS | URA DB `ura_activity_log` `action LIKE '%sweep%'`: exactly 1 row since deploy, at 2026-11-03T01:32:59Z (19:32 CST): zone_1 "Entertainment + Master Suite empty — turned off 1: fan.towerfan_dreopilotmaxs_wifi_livingroom", details `{"turned_off": [...], "house_state": "home_evening", "pre_arrival_fans_kept": false}`. No rows for no-op flips. |
| Count is real | PASS (doc correction) | The counter is house-level, not per-zone. It is `total_vacancy_sweeps_today` on `sensor.ura_hvac_coordinator_hvac_zone_intelligence` (sensor.py:14242) and `sweeps_today` on the sweep switch (switch.py:4094). It is not on `zone_N_status` as the prospective table said. 1 real sweep in ~19 h, against ~25 flag flips/day before. |
| Pre-arrival fans kept | not exercised live | No pre-arrival was active during a sweep in the window (the one sweep had `pre_arrival_fans_kept: false`, a non-arrival case). Covered in-suite by `test_hvac_zone_sweep_cleanup.py`. |
| Opt-out honoured | PASS | `vacancy_sweep_enabled: true` on zone_1/2/3 status (master on, zones on). |
| Load clean | PASS | ha_get_logs source=system, level ERROR, search `universal_room_automation`: 0 entries. |
