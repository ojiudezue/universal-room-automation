# v5.92.1 — Night lights turn off on vacancy (+ stale room-config repoints)

**Cards:** `NIGHT-LIGHT-NO-OFF-PATH-1`, `ROOM-ENTITY-STALE-CONFIG-1`, `ROOM-AUTOMATION-MODE-SELECT-UNAVAILABLE-1` (registry cleanup)
**Tier:** 2-DB (3 framing-disjoint reviews across Rev 2 + a focused framing-B re-review on the Rev-3 inversion + orchestrator neuter re-verify).
**Merge:** `feature/night-light-off-path@5b446fc33` → develop.

## 1. Night lights now behave like any occupancy light

**Problem:** a `night_lights`-only entity (configured as a room's night light but NOT also in `lights`) was turned ON by URA but had **no off-path** — all three light-off paths were `CONF_LIGHTS`-scoped. Result: the Master Bath under-cabinet Sonoff (and 4 other rooms) stayed on 20–29h until a human/device cleared it.

**Solution (operator-corrected premise):** night lights behave like any occupancy light — **ON when occupied + dark, OFF when occupancy clears, always (including sleep).** The vacancy-off set is the **unconditional union** `CONF_LIGHTS ∪ CONF_NIGHT_LIGHTS` at all four off-sites (canonical exit D1, reconciler vacant branch D2a, shared-space D3a, HVAC zone-vacancy sweep D5); the reconciler sleep branch is made **occupancy-aware** (D2b — night light ON only if occupied during sleep, else falls through to OFF); the exit-target consumer is widened (D6). The warning-flash excludes night-only entities in **both** domains (A2 — a dim night light is never blasted to full brightness as a pre-auto-off warning; it is still turned off at auto-off). The sleep-DIM on-entry behavior is untouched.

**5 affected rooms:** Master Bathroom, Study B, Kitchen, Garage Hallway, Master Bedroom. 15 dual-listed rooms and ~20 no-night-light rooms are byte-identical.

**Reviews:** 3 framing-disjoint (A local-correctness, B parity/lifecycle, C test-authority+completeness) on the initial build, which caught the wrong-premise sleep-gate + a missed HVAC off-path + a hollow D3b anchor; then the operator inverted the premise → Rev 3 rebuild → a focused framing-B re-review confirmed **no canonical↔reconciler flap** and safe boot; orchestrator independently re-ran the D1-sleep-vacancy, D2b, and A2 neuters (all RED). Completeness confirmed: 6-site off-path set, no 7th. 11 behavioral neuter→RED anchors; 75 cycle tests; 0 new full-suite failures.

### Acceptance criteria
- **Verify:** a `night_lights`-only entity is turned OFF on vacancy (non-sleep AND during sleep); ON only when occupied+dark.
- **Verify:** dual-listed + no-night-light rooms byte-identical; night-only entities not flashed by the warning cycle.
- **Live:** the Master Bath under-cabinet Sonoff (`switch.sonoff_1002197ef7_1`) turns OFF when the bath goes vacant, including during sleep — no more 20–29h holds.

## 2. Stale room-config repoints (`ROOM-ENTITY-STALE-CONFIG-1`)

Four URA room configs referenced entities HA no longer has (404). Repointed via `.storage/core.config_entries` (backed up, applied at the deploy-restart):
- Kitchen `room_media_player`: `media_player.kitchen_2` → `kitchen_3`
- Upstairs Guestroom `room_media_player`: `up_guest_room_2` → `up_guest_room_3`
- Master Bedroom fan (`data.fans` + `options.manual_switches`): `…rf304_25_masterbedroom` → `…rf_masterbedroom`
- Jaya Bedroom: **remove** `door_sensor` (no distinct door contact); **repoint** the CM `security_entry_sensors` dead contact → `…jayabedroom_contact_2` (live)

## 3. automation_mode select registry cleanup (`ROOM-AUTOMATION-MODE-SELECT-UNAVAILABLE-1`)

The 38 `select.<room>_automation_mode` entities were deliberately deleted from code on 2026-07-26 (inert knob, no consumer; real control is `switch.<room>_automation`) but left in the registry per Bug Class #46. Operator-approved one-time cleanup: the 38 orphaned rows removed from `.storage/core.entity_registry` (backed up, applied at the deploy-restart). No code.

## Pre-deploy gate
0 conflict markers; py_compile clean; 75 cycle tests pass; full-suite name-diff 0 new vs develop.

## Validated 2026-09-01 (post-restart)

| Criterion | Observed evidence | Result |
|---|---|---|
| Clean boot, no new URA errors | `error_log` ERROR-level scan (06:28–12:49 window): **0** `universal_room_automation` ERROR entries / tracebacks (7106 URA lines, all below ERROR). house_state=home_day, ev_charging_status=idle. | **PASS** |
| Stale-config repoints applied | `.storage/core.config_entries` post-restart: Kitchen `room_media_player`=`media_player.kitchen_3`; Master Bedroom `fans`=`[…rf_masterbedroom]` (no `rf304`); Jaya `door_sensor` key **absent** (data+options). (Up-guest media + CM security→contact_2 applied in the same write.) | **PASS** |
| automation_mode selects removed | `.storage` edit was **clobbered** by an HA in-memory registry flush before the restart (config_entries survived, entity_registry did not — the live-`.storage`-edit hazard). Re-done via the proper API `ha_remove_entity` (bulk 38): removed 38 / skipped 0 / errors 0. Confirmed `select.kitchen_automation_mode` + `select.master_bathroom_automation_mode` now return 404. | **PASS** (via API, not `.storage`) |
| Night lights off on vacancy | `switch.sonoff_1002197ef7_1` = off at validation. The off-*on-vacancy* behavior is event-driven — **organic watch** (per `--revisit`): confirm a sub-hour on-episode ending at a Master-Bath vacancy transition, no more 20–29h holds. | **Code+review PASS; live = organic** |

**Process note:** editing `core.entity_registry` directly in `.storage` on a running HA is unsafe — HA flushed its in-memory copy over the edit before the restart read it (the `core.config_entries` edit survived only because it isn't flushed on that cadence). Entity-registry changes must go through `ha_remove_entity` / the registry API, not a `.storage` hand-edit. Recorded so this isn't repeated.

**Organic watch (per `--revisit`):** Master Bath under-cabinet Sonoff turns OFF within a tick of the bath going vacant (incl. during sleep) — query its state history for a short on-episode ending at a vacancy transition.
