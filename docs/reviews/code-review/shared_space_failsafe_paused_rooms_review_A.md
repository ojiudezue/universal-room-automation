# Review A — SHARED-SPACE-AUTO-OFF-FAILSAFE-1 option A (failsafe in paused rooms)

Branch `fix/shared-space-failsafe-paused-rooms` @ e3e44a5f, base 98e8baa2 (merge-base verified).
Framing A: correctness, edge cases, operator-visible behaviour change. Reviewer did not read HVAC/presence
state-of-play docs: change touches room lighting only (occupancy is consumed, not altered).

## Code correctness — holds

| Check | Result | Evidence |
|---|---|---|
| Old-site gates | skip-first (if-branch), ManualMode (folded into `_is_automation_enabled`, coordinator.py:3234-3244), master switch (`elif` coordinator.py:5320), `_refresh_config()` (:5402), shared try with temperature-fan handler | read |
| New site keeps | skip-first via `_skip_first_this_tick` captured at :5281 before the branch consumes it; ManualMode `is not True`; `_refresh_config()`; own try/except (:5536-5544) | read |
| New site drops | master `automation` switch only (intended). Also no longer skipped when the temperature-fan handler raises (improvement) | read |
| Body gates (unchanged) | shared_space, hour window + night key, once-per-night, occupied, presence boot-settle fail-closed, ON-hold via `light_hold_allowed` (automation.py:4526-4547, 4685) | read |
| Sleep / guest / observation mode | none at old site or in body; nothing dropped | grep |
| Exactly once per tick | if (skip-first): 0; elif (enabled): 1 (old call removed :5421); else (paused, incl. cover sub-branch): 1; ManualMode: 0 | read + tests |
| Tests drive real code | `_async_update_data` real; two tests run the real `check_scheduled_auto_off` body (only `dt_util.now`, boot-settle, `_shared_space_turn_off_all` stubbed) | quality/tests/test_shared_space_failsafe_paused_rooms.py |
| Targeted suites | 110 passed (paused_room_gates, shared_space_auto_off_failsafe, new file, hvac_batch_d_shared_space_fans, v4515/v4516 failsafe) | pytest |

## Findings

**HIGH — operator-intent conflict (behaviour change, not a code bug).** The board records an explicit operator ruling,
kanban.data.yaml:32236 (2026-10-18): *"Paused rooms should stop with lights and fans automation based on occupancy...
I just didn't want it turning off lights when paused."* v5.103.75 built that (`room_automation_paused` gates; INV-P').
This commit makes paused shared-space rooms turn lights AND fans off nightly. The PICK was escalated 11-04
(feed entry `acknowledged: false`, kanban.data.yaml:45) and the build was dispatched on "no veto since 11-04"
(card line "recheck_2026_11_07_overnight"). Silence is not approval of a reversal of a written ruling.
Must-fix: explicit operator go on option A before ship (or ship scoped to Kitchen only).

**MEDIUM — blast radius larger than Kitchen.** From live `.storage/core.config_entries` (shared_space=true) x
`core.restore_state` (snapshot 2026-11-11 02:12, automation switch `off`, manual_mode off), rooms newly swept:
Kitchen, Kitchen Hallway Garage, Staircase, Patio, Receiving Room, Garage A, Garage Hallway, Exercise Room
(auto-off hour 22), Foyer (default hour); Master Hallway and Media have no lights (fans only). Patio (outdoor)
and Garage A/Garage Hallway are the plausible "paused because sensors unreliable / not dialed in"
(operator 10-13: "rooms off on purpose where automation is unwanted or not dialed in") cases.

**MEDIUM — no protection beyond the occupancy reading for paused-because-unreliable rooms.** If a paused
room's sensors false-negative while someone is present, the only guards are: data[STATE_OCCUPIED] (sensors +
BLE + override_occupied), presence boot-settle, a live light ON-hold, once-per-night. Nothing knows WHY a room
is paused. Operator accepted false-occupied (no sweep) trade, not false-vacant sweeps in rooms they paused.
Mitigation is config (Override Occupied, or shared_space off) — say so in the README.

**LOW — README draft should list the swept rooms** and the 10-18 ruling it amends.

## Verdict
**FIX-REQUIRED (process, not code):** obtain explicit operator approval of reversing the 10-18 paused-room ruling
for the night failsafe, with the room list above. Code is correct and well tested; ship as-is once approved.
