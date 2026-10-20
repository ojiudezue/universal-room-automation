# Audit: where the wall panels fit in URA (2026-10-20)

This is a read-only prober audit. It was saved by the orchestrator because the prober cannot write files.

Inputs:
- HomeLab brief: `~/Code/homelab-automation/docs/wallpanel-capability-brief.md`.
- `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`, `SENSOR_FLEET_CLASSES.md` and `URA_ARCHITECTURE_MAP.md`, all read in full.

## 1. "Super sensor" plan: not found

**Searched:** URA `docs/`, `.vibememo`, URA memory, `homelab-automation/docs`, `wall-tablet`, and every Claude project memory and transcript. There is no hit.

**Nearest matches:**
- Card WALLPANEL-TOUCH-WITNESS-1.
- `homelab-automation/docs/plan-wallpanel-fleet.md:46` and `:90`: the noise sensor needs the wake word on, and reads −96 dBFS of silence on Master.

The operator needs to say where the plan lives.

## 2. Sound and noise in URA

**No consumer exists.** Nothing in `custom_components` defines a CONF_* for sound or noise, and `assist_satellite` is not referenced anywhere.

**Live data, 6 h:**
- The floor is −96 dBFS, which is also the mode.
- The average sits between −74 and −88 dBFS, and peaks reach −26 to −43.
- Study B is unavailable.
- Kitchen's `last_interaction` reads 2024-12-26. It can republish stale values, so it needs a freshness guard.

**Decision points that lack evidence:**

| Decision point | Where | What panel input could add |
|---|---|---|
| Fan recheck eligibility | `presence_fan_recheck.py:514`, ladder at `:676-725` | BLE only today. A touch within ~120 s is strong veto evidence. Noise would be weak, and a fan raises noise (inferred). |
| D2 fan-immune witness | `coordinator.py:2176` | Fails closed without a witness. Study A has no witness. A touch fits; noise is confounded by the fan. The state-of-play doc cites `:2159`, which is stale. |
| Nobody-home / AWAY | `presence.py:1126-1131`, α veto `:1169-1180` | A touch can only add "someone is home". |
| Sleep vs awake | `automation.py:1311` | Bedroom noise might separate them (speculative). |
| Guest gate | `presence.py:5953` | Low value: noise carries no identity. |

## 3. Panel rooms: sensor coverage

Every room already has lux, temperature and humidity sensors. Panel temperature reads high, and Media's reads 32 °F.

| Room | Presence class | Motion | Other | Verdict |
|---|---|---|---|---|
| Master Bedroom | Screek, ZG-204ZX, Inovelli mmWave, bed L/R | — | BLE tier 2 | Adequate (noise for sleep/awake?) |
| Study A | ZG-204ZK (athom mmwave entry not in registry) | — | no door, BLE tier 2 | **Sparse.** Single radar, no witness; touch fills the gap |
| Study B | ESPHome LD2410 | — | door, VEML lux, BLE tier 2 | **Sparse.** Single radar; panel offline |
| Upstairs Hallway | — | ZG-204ZV | balcony contact, BLE tier 1; panel has no area | Adequate for a transit room |
| Media | Meross Matter occupancy | MS600 bit | temp/humidity borrowed from closet; no door | Adequate on presence |
| Kitchen | LD2410, ZG-204ZX | UP Sense | BLE tier 1 | Dense |
| Foyer | — | ZG-204ZV | no door, BLE tier 1; area mismatch (sensor `entry_way` vs room `foyer`) | **Sparse** on presence class |

## 4. Generalization: reuse or build

There is no surface or device-role abstraction today. The closest primitive is the sensor capability registry (`sensor_capability.py:28-48`, `CONF_SENSOR_CAPABILITIES` at `const.py:566`). `SENSOR_FLEET_CLASSES.md` rule 4 says to extend that registry rather than build a parallel one.

| Piece | Verdict | Where |
|---|---|---|
| LED as alert light | REUSE: add it to the room's `alert_lights` | `CONF_ALERT_LIGHTS` `const.py:99`; `automation.py:4766` and `:4803`; `aggregation.py:1460` |
| Announce target | REUSE `room_media_player` where the panel exposes a `media_player` | `const.py:83`; `music_following.py:1123` |
| NM speech per room | BUILD, small (NM TTS speaker list is global) | `CONF_NM_TTS_SPEAKERS` `const.py:3387`; `notification_manager.py:2308-2320` |
| `assist_satellite.announce` / ESPHome notification card | BUILD, defer (NM channels are a fixed set) | `const.py:3373-3390` |
| Touch input | REUSE: template binary sensor ("touched ≤120 s", fresh), added to an existing sensor list | — |
| Noise input | BUILD, hold until measured | — |

Unverified risks:
- **Restore from unknown.** The LED reads `unknown` until its first command. `_store_alert_light_states` restore may misbehave from that state.
- **Reconciler exclusion.** `alert_lights` is excluded from the reconciler (`actuator_reconciler.py:105`).

## 5. Are the panels Bermuda scanners?

**Hardware side.**
- All seven panels are `bluetooth_proxy` devices with `bluetooth_scanning_mode: auto`.
- Five have an area: Master, Study A, Study B, Media and Kitchen.
- **Up Hallway and Entry Way have no area.**

**Bermuda side.** There is no evidence any panel is used:
- No panel MAC is in the `rssi_offsets` keys.
- No `distance_to_<panel>` entity exists among 168 distance entities.
- Bermuda's internal scanner list was unreadable.

**URA side.** `CONF_SCANNER_AREAS` (`const.py:571`) maps:
- Study A to study_a_closet;
- Study B to study_b;
- Master to master_bedroom and ezinne_vanity.

The other panel rooms are tier 1 by area. If Bermuda adopts the Study A/B panels, those rooms likely move to tier 1 (unverified).

**First fix:** the operator assigns areas to the Up Hallway and Entry Way panels in the device registry.
