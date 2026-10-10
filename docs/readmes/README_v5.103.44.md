# URA v5.103.44 — Night lights come on in Sleep even under sleep protection

Operator ruling (a), 2026-10-09: during Sleep, an occupied room's night lights always come on; sleep protection only holds back main lights, fans and covers. Two reviews (SHIP); one review gap fixed in-cycle; full-suite name-diff clean. Card: NIGHT-LIGHT-ACTION-SELECTOR-1.

## Problem
Master Bath Toilet (sleep protection on) got no night light at 04:49 CDT 10-09. Sleep protection ignores the first 2 motions in the room's sleep window (`motion entries needed to override sleep`, default 3), and that stopped all automation for the room — night light included. The background reconciler did not step in because it only reacts to light state changes.

## Fix
- While sleep protection is ignoring motion: an occupied room's night lights turn on with Sleep colour/brightness (manual hold respected). Main lights, fans, covers and the motion counter behave exactly as before.
- When the room empties under the same gate, its night lights turn off (except "leave on when empty" lights) and the motion counter resets, as a normal exit would.

## Live validation (prospective)
- Tonight: a first motion entry into Master Bath Toilet in its sleep window logs a night-light turn_on (sleep) in ura_activity_log with no main-light turn_on; leaving logs a night-light turn_off.
- No URA errors at boot.

## Validated 2026-10-10 (observed window: 2026-10-09 22:00 → 2026-10-10 08:00 CDT, i.e. 2026-10-10T03:00Z→13:00Z; house in `sleep` state 03:00:10Z→11:00:41Z per `house_state_log`)

| Criterion | Result | Evidence |
|---|---|---|
| Master Bath Toilet: first motion entry in sleep window logs a night-light turn_on, with no main-light turn_on, and exit logs a night-light turn_off | **FAIL to confirm — no URA-logged night-light action for any of the sleep-window entries observed** | `ura_activity_log` for room `Master Bath Toilet`, `2026-10-10T03:00:00`→`13:00:00`: 6 `occupancy_entry`/`occupancy_exit` pairs occur while house state is `sleep` (03:35–03:42, 03:56–04:02, 04:08–04:14, 04:58–05:03, 10:23–10:31, all CDT-shifted to Z above), sleep_protection_enabled=True, sleep_bypass_motion_count=3.0. **None of these 5 sleep-window sessions produced a logged `light_turn_on`/`light_turn_off` action.** The only log entry near them is a stale `light_reconcile ... exit_light_off` at 03:45 (cleanup of a prior state, not a new action). |
| (same room) — the physical light DID cycle during the window, unattributed to URA | Needs follow-up, not asserted as a code bug | `ha_get_history` on `light.rgbw_motion_lux_3rdr_wifi_matter_mastertoilet` shows on/off cycles at 05:23–05:31, 06:03–06:08, 07:03–07:20 CDT — none of which line up with any `ura_activity_log` row for this room (nearest logged occupancy session ends 05:03, next starts 10:23). This is either a non-URA actuation path (e.g. the Sonoff/Zigbee device's own local motion automation) or a logging gap in the night-light-under-sleep-protection code path; the evidence here only supports "URA did not log turning this light on during these windows," not a root cause. **Recommend carding for investigation — do not treat as confirmed-fixed from this evidence.** |
| Living Room: night light on/off tracks occupancy during Sleep (same mechanism family) | PASS (comparison case — different room, but exercises the on/off-by-occupancy wiring this cycle also touches) | `ura_activity_log` for Living Room 03:00–13:00: `light_turn_on "Turned on 1 night light(s) (sleep)"` paired 1:1 with `occupancy_entry`, and `light_turn_off` paired 1:1 with `occupancy_exit`, at 03:53/04:00 and 04:04/04:12. |
| No URA errors at boot | PASS | `ha_get_logs(source=system_service, slug=core, search="universal_room_automation", hours_back=4)` → 0 lines (this restart postdates the observed night window, so this is a boot-health check only, not evidence about the night behavior) |

**Net:** the Living Room on/off-by-occupancy night-light wiring (shared mechanism family) is confirmed working. The specific Master Bath Toilet "night light during suppressed sleep-protection motion" criterion from this README could **not be confirmed live** — zero matching log evidence across 5 qualifying sessions in one night, and the light's own on/off history doesn't correlate with any URA-logged session. This is a live-validation gap, not a code read — recommend a follow-up card (sleep-protected night-light path for Master Bath Toilet) rather than closing this criterion as proven.
