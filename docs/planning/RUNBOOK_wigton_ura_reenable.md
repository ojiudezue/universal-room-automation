# Wigton — conditions to bring URA back online

Wigton (2nd home, HA 192.168.17.243) had URA fully disabled 2026-10-10 ~14:10 UTC after:
- room lights toggling on motion while room Automation switches read OFF (root cause: built-name switch lookup, ROOM-SWITCH-LOOKUP-BY-NAME-1);
- bulk room-create filling room configs with device-settings switches (anti_interference, detach…; ROOM-CREATE-AREA-PREFILL-DETRITUS-1);
- a flickery Tuya mmWave fleet (17 units);
- unexplained stalls seen locally by operator + Omonele (WIGTON-HA-UNRESPONSIVE-1).

Every gate below is binary and checked once, against live data. All gates in a stage must pass before that stage starts.

## Stage 0 — before re-enabling anything

| # | Gate | How to check | Pass when |
|---|---|---|---|
| G1 | Local stall vector known (Madrone->Wigton dropouts = Wigton IPS, fixed 2026-10-10) | `/tmp/hawatch.log` (local watcher, 5 s) + HA log with Profiler asyncio debug, across ≥1 stall the operator/Omonele report | Either (a) watcher shows HA froze AND the slow-callback log names a non-URA cause, or (b) watcher shows HA answered in ms during the stall (network/client side). Fail = HA froze with URA code in the slow-callback trace, or no stall captured yet. |
| G2 | Switch-lookup fix installed | Wigton `update.universal_room_automation_update` installed_version | ≥ the release carrying ROOM-SWITCH-LOOKUP-BY-NAME-1 (v5.103.48+) |
| G3 | Room configs clean | Re-read every room's options → devices lists (plan: scratchpad `wigton_detritus_plan.json`) | Zero entities with entity_category config/diagnostic or names matching anti_interference / detach / indicator / child_lock / led / relay_mode in any room list |
| G4 | Sensor fleet tuned | Live `number.*` values on all 17 mmWave units | motion ≤ 6, static ≤ 6, fading_time = 120 s, detection_distance ≤ 4 m except Master Bedroom + Living Room; anti_interference ON on all 17 |
| G5 | Flicker actually down | Re-run the fleet audit script (same metrics) over ≥24 h after G4 | Fleet median on/off transitions/day ≤ 50% of the 2026-10-10 baseline AND no unit > 20 sub-5 s flaps/day AND no unit stuck on > 12 h. Units failing → reposition/retune before Stage 2, not a blocker for Stage 1 |

## Stage 1 — enable URA with every room OFF

1. Enable the entries: 🏠 Home → Zone Manager → Coordinator Manager → rooms.
2. **G6 gates resolve OFF:** for every room, the registry-resolved Automation + AI Automation switches read `off` (state check), and the room coordinator's gate reads them (log has no "room switch not found" warning).
3. **G7 no actuation:** one-shot logbook query for the 60 min after enable: zero light/switch/fan/cover service calls with URA context (`context_domain` homeassistant/light/switch from URA, "Room vacated / Turned off" activity lines). Any = disable again, investigate.
4. **G8 no stall regression:** watcher log over that hour shows no HA freeze (> 2 s responses) that wasn't present with URA disabled.

## Stage 2 — turn rooms on, one zone at a time

Order: Back Hallway → Upstairs → Entertainment → Master Suite (bedrooms last; operator may change).
For each zone: turn Automation ON for its rooms (AI Automation stays off), then one-shot check after 2 h:
- **G9** every URA light action in the zone has a matching occupancy edge (no off→on pairs < 10 s apart caused by sensor flicker);
- **G10** no complaints from the household for that zone.
Fail → turn that zone's rooms back off, retune its sensors, retry.

## Stage 3 — presence-dependent features (blocked on enrollment)

- **G11** Omonele enrolled (IRK capture tool / BLE tracker), `person.omonele` home ⇔ house state not `away` in a one-shot comparison over a day.
- Only then: HVAC coordinator (W1-C P3 test plan: observation mode first, Entertainment Zone thermostat), AI Automation, guest/away behaviours.

## Rollback (any stage)
Disable all URA entries (`config_entries/disable`, rooms first, 🏠 Home last). Before-state of every switch touched is saved in the session scratchpad (`wigton_*_before*.json`).

## Instrumentation to remove at the end
- Profiler asyncio debug (`profiler.set_asyncio_debug enabled:false`) once G1 is closed.
- `/tmp/hawatch.sh` in the SSH add-on (dies on add-on restart).
