# AUDIT: Security periodic lock sweep, and zone-sweep mop-up gap

Measured 2026-11-01 ~12:10 CST (read-only prober). Recorder `/config/home-assistant_v2.db` holds only 7 days (`purge_keep_days: 7`, configuration.yaml:13); lock/battery history beyond that is from long-term `statistics` and the URA DB `compliance_log`. HVAC STATE_OF_PLAY and the zone-sweep audit (`docs/planning/AUDIT_zone_sweep_effectiveness.md`) were read before Part B; the HVAC doc was not re-read in full for this brief (Part B uses only zone status attributes), flag if that matters.

## A. Security sweep

### A1. What and when
- Code: `SecurityCoordinator._evaluate_lock_check` security.py:1678; timer `async_track_time_interval(... _handle_periodic_lock_check, timedelta(minutes=interval))` armed in `async_setup` security.py:701-709, only if interval > 0 and any lock/garage entity is configured; handler queues an `Intent(source="periodic_lock_check")` security.py:1970-1981 dispatched at security.py:819.
- Armed-independent (module docstring security.py:16). Suppressed in observation mode (security.py:823-831).
- Live config (`.storage/core.config_entries`, URA: Coordinator Manager): `security_lock_check_interval` = 60 min, `security_lock_entities` = [`lock.doorlock_kwikset_zwave_frontentry`], `security_garage_entities` = [`cover.ratgdov25i_dbfe2a_door`, `cover.konnected_f0f5bd523b00_garage_door`]. One lock only. The Kwikset 916 at Garage Hallway is not configured (and has no lock entity in the recorder).
- The timer restarts at every URA setup; `sensor.ura_security_coordinator_security_last_lock_sweep` reads `no_sweep_yet` at 11-01 11:24 after several restarts today.

### A2. Does it close doors?
Yes. Unlocked lock -> `lock.lock` (security.py:1692-1701); garage cover in state `open` -> `cover.close_cover` (security.py:1712-1721). Same service pair is used by the lockdown path (security.py:1642-1668, unknown-person / alert).

### A3. State check before acting
Yes, gated per entity: lock only if `state == "unlocked"` (1692), cover only if `== "open"` (1713). `unavailable/unknown` are skipped and NM-notified at most 1/day/entity (1731-1770). So by construction a sweep command never targets an already-locked or already-closed device (race between read and execution aside). Note `opening`/`closing`/`locked`-already states never trigger.
Gap: NO backoff when a command does not take. Each interval re-sends while the state stays `unlocked`.

Counts (producer: sweep action -> `compliance_log` row via `schedule_check`, scope `security`; URA DB):
- Last 7 d: recorder `call_service` events for lock.* = 0. `cover.close_cover` on a security garage cover = 1 (konnected, 10-26 11:06:42 CDT, no parent context; matches compliance row 10-26 16:08Z = 11:08 CDT). Attribution of that one call is by timing match, not proven. Zero since 10-26.
- Oct 2 -> Oct 26 (last 30 d with rows): 21 garage close rows (konnected 18, ratgdov 3) = ~0.7/day; 0 lock rows. Already-closed targets: 0 by code gate.
- Front lock rows by month (compliance_log): Mar 103, Apr 15, May 15, Jun-Oct 0. Last row 2026-05-08.
- Worst case: 2026-03-11, 46 lock commands in one day, every ~30 min (interval was 30 then), every one found `unlocked` again at the next check. Mar 8-12: 74 commands. 116 of 133 lock rows record `actual_state: unlocked` after the command (command not taking effect or state stale).

### A4. Battery
- The configured front lock is dead: all 7 recorder rows since 10-25 are `unavailable`, and `sensor.doorlock_kwikset_zwave_frontentry_battery_level` has NO long-term statistics after 2026-05-08 22:00 (statistics_meta id 716). That is the same date as its last sweep row.
- Battery history (statistics, daily): 20% flat through 03-11, 0% from 03-14 to 04-08, 100% 04-09 to 04-27, 0% from 04-28. The jump pattern (20 -> 0 -> 100 -> 0) looks like a battery swap on ~04-09 then death/wedge ~04-28, then offline ~05-08. Caveat: a 0% reading may be a report artifact; not verified.
- Drain correlation: the heavy retry burst (03-08 -> 03-12, ~15 cmds/day avg, 46 peak, with the lock not changing state) precedes the 0% reading on 03-14, but the battery was already 20% flat before, so causation is NOT established. Only one battery series exists (front lock); no other configured lock to compare.
- Lock command vs human use: UNKNOWN. Recorder keeps 7 d and the lock was unavailable for all of them; no earlier state history to count human lock/unlock events.
- Plausible mechanism for the operator's suspicion (read, not measured): hourly (earlier 30-min) lock.lock re-sends to a lock that stays unlocked. It applies only to non-compliant states; healthy lock = ~0 commands.

### A5. Side finding
`cover.konnected_f0f5bd523b00_garage_door` logs ~230 `opening` and ~230 `closing` transitions/day (10-26, 10-27) vs ~10 `open`/`closed`: flapping, not door travel. Cause unknown. The sweep ignores `opening/closing` so it is not driving this.

## B. Zone-sweep mop-up

Method: vacancy = zone status attr `any_room_occupied` False (sensor.ura_hvac_coordinator_zone_N_status, same flag family that re-arms the sweep, hvac_zones.py:1139-1142); counted after 30 min of continuous vacancy, 7 d to 11-01 ~12:00. Vacant hours (after +30 min): z1 39.5, z2 42.9, z3 38.4 (of 168). Entities mapped to zone by area registry name == `live_rooms` name. Excluded: config/diagnostic entities, LED/DND indicators, camera detection toggles, recheck/auto-recovery URA switches, desk position covers. Unmapped (no area or area not a live room): 357 switch, 254 media_player, 156 light, 37 cover, 15 fan - NOT measured. W from the sibling `sensor` power entity's 5-min mean (statistics_short_term) during overlap only where one exists.

Hours = ON-hours inside vacant>30 min windows (week-total ON hours in brackets).

| Class | Entity (room, zone) | Vacant-ON h | W | Note |
|---|---|---|---|---|
| Light | `light.dimmer_tapo_wifi_matter_kitchenoverhead` (Kitchen z3) | 5.1 [53] | 116 | ~0.6 kWh; configured, but Kitchen is a paused room (swept set skips paused, hvac.py:6743) |
| Light | `light.switch_mmwave_inovelli` (Master Bedroom z1) | 2.1 [7] | 108 | ~0.23 kWh; not in any room `lights` list |
| Light | Study B `rgbw_light_jullison_wifi_7/_9` z1 | 1.8 each | unk | not in room config |
| Light | Garage Hallway hallwaycabinet z3 / Game Room leviton z2 | 1.5 / 0.7 | unk | |
| Fan (not swept) | `fan.fanswitch_treat_wifi_jayabedroom` (z2) | 19.4 [103] | unk | largest transient item; fan mode not checked |
| Fan | `fan.polyfan_508s_wifi_masterbedroom` (z1) | 9.2 [124] | unk | Master Bedroom paused |
| Fan | `jayabathfan` (z2) | 5.3 [41] | 12 | ~0.07 kWh |
| Fan | Game Room ceiling fan x2 (z2) | 3.2 | unk | |
| Fan | Master ceiling fans x2 (z1) | 2.8 [59] | unk | |
| Switch relay | `switch.switch_shelly1pmgen3_wifi_masterbedroom` (z1) | 35.9 [153] | 8.5 | ON nearly all week; unswept relay named in zone-sweep audit |
| Switch | `kitchen_room_lights`, `jaya_bedroom_room_lights`, `garage_hallway_room_lights` | 5.1 / 1.6 / 1.5 | | URA group switches mirroring lights above |
| Media | `media_player.apple_tv1` (AV Closet z1) | 34.8 [113] | unk | state counted: on/playing/paused/buffering; AV Closet is infrastructure |
| Media | `apple_tv2`, `living_room_2` (AV Closet), Master Bedroom TV | 1.4 / 1.4 / 0.4 | unk | the TV only 0.4 h vacant |
| Cover | Living Room blinds x8 (z1) open | 24.4 [78] | n/a | comfort/privacy, not energy |
| Cover | Jaya Bedroom shades (z2) open | 0.9-3.9 | n/a | |
| Smart plugs / outlets | ~40 (Study B desk x5, Study A Geeni x6, Media closet Wattbox x6, Living Room sub/speaker, Master Bath, Kitchen, Stair Closet, Oji Vanity ...) | 37-41 = ON essentially the whole week | mostly no power sensor mapped; Oji Vanity 0.0, Living Room dimmer led 0.0 | always-on load plugs; not "left on", cannot be classified without knowing the load |

Measured energy where W is known: ~0.6 + 0.23 + 0.07 + 0.3 (Master Bedroom relay) = about 1.2 kWh/week. Dominant unknown: fans without power sensors, and plugs.
No humidifier/dehumidifier or vacuum entity appeared mapped to a zone with vacant-ON hours (humidifier class: none mapped; `vacuum` 2 entities unmapped). TVs: only one mapped TV, 0.4 h.

Honest limits: (1) area-based mapping drops 357 switches; (2) `any_room_occupied` is lighting occupancy, not person presence, so vacancy hours may be over-counted (mmWave drops still occupants, per memory/Zone 1 away-while-occupied note); (3) per-device W only for 7 devices; (4) the whole-week-ON plugs include intended infrastructure.

### Scope compare
| | Security sweep | Zone vacancy sweep |
|---|---|---|
| Trigger | fixed interval (60 min), armed-independent | edge on zone vacancy flag (hvac.py:3023-3046, 3099-3121) |
| Scope | 1 lock + 2 garage covers, explicit config list | lights/night_lights + follow_thermostat fans of non-paused rooms |
| State check | yes, per entity | skips entities not ON (per zone audit: 90% no-op) |
| Backoff on non-compliance | none (retries every interval) | one-shot per vacancy edge |
| Accountability | `compliance_log` row per command | none (INFO log only) |

## Recommendations (no code changes made)
1. Front lock first: physical check / replace battery or re-pair the Z-Wave node; it has been unavailable since ~2026-05-08, so the lock the sweep exists for is unprotected. Config-first, no code.
2. Add retry cap/backoff to the sweep for non-compliant devices (e.g. stop after N consecutive failed lock.lock, then NM once). Small, same primitive as the existing 1/day unavailable dedup. Tier 1-2.
3. Do NOT widen the zone sweep into a general mop-up: measured transient waste is small (~1.2 kWh/week where W known; largest hours are Jaya Bedroom fan 19 h and Kitchen light 5 h at 116 W, both already owned by paused/fan-mode rules). Cheaper: config-first - add the Master Bedroom mmWave Inovelli light and Study B RGBW lights to their room `lights` list, and decide the Jaya Bedroom fan mode.
4. Park, with revival trigger: "idle-load audit" if a power meter on plugs shows >50 W idle in a vacant zone; need the plug power-sensor map first (measure-before-build).
5. Garage konnected flapping (A5) deserves its own card; unknown cause.
