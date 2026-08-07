# AUDIT — Writer B Removal Study (ZoneAnyoneBinarySensor direct preset writes)

**Date:** 2026-08-06 (read-only study; no code changed)
**Scope:** Can the direct `climate.set_preset_mode` write path inside
`ZoneAnyoneBinarySensor` (aggregation.py:3892–4110, "Writer B" per
`docs/planning/AUDIT_hvac_preset_flap_fix_implications.md` §Cross-cutting
Finding X) be safely removed?
**Verdict up front: YES — remove outright (Option a).** No zone exists where
Writer B is the only preset automation; the binary-sensor state is fully
separable from the write path; the only user-visible latency change is a
bounded ≤5-min re-`home` after a D1 vacancy-override, which pre-arrival and
signal-driven cycles largely cover — and Writer B's "instant" behavior is
the probable root cause of the preset oscillation the flap audit documents.

---

## 1. Full capability map of Writer B

`ZoneAnyoneBinarySensor(ZoneSensorBase, BinarySensorEntity)` at
aggregation.py:3892 does exactly two jobs:

### 1a. The occupancy sensor (KEEP)
- `is_on` (aggregation.py:4065–4096): three-layer zone-anyone rollup —
  Layer 1 room-coordinator `STATE_OCCUPIED` rollup (:4084–4086), Layer 2
  v4.7.13 sleep-state person-tracker fallback
  (`_sleep_person_fallback_occupied`, :4098+), Layer 3 v4.7.15 D2 non-sleep
  person-tracker fallback (:4092–4094).
- Entity ids live: `binary_sensor.zone_back_hallway_anyone`,
  `binary_sensor.zone_entertainment_entertainment_anyone`,
  `binary_sensor.zone_entertainment_master_suite_anyone`,
  `binary_sensor.zone_master_suite_anyone`, `binary_sensor.zone_outside_anyone`,
  `binary_sensor.zone_upstairs_anyone` (live `core.entity_registry`).
- Consumers: the live Lovelace dashboard `/config/.storage/lovelace.ura_v8`
  references `_anyone` entities (grep confirmed). No in-repo Python consumer
  of the entity id exists (`grep -rn "_anyone"` over
  `custom_components/universal_room_automation` hits only a unique_id
  comment at config_flow.py:8410). The flap audit's P2 proposal would make
  the HVAC Coordinator a future consumer.

### 1b. The preset writer (REMOVE — "Writer B")
- Trigger surface: `async_added_to_hass` → `_schedule_hvac_listener_setup`
  (:3906–3925, includes a 65 s coordinator-ready retry loop) →
  `_setup_hvac_occupancy_listeners` (:3927–3971), which subscribes
  `async_track_state_change_event` (:3963) on every
  `binary_sensor.<room>_occupied` entity of the zone's rooms (entity ids
  reconstructed by name-snaking at :3945–3950 — itself fragile).
- Side effect: `_handle_zone_occupancy_change` (:3973–4028). On any
  zone-level `is_on` edge it writes
  `climate.set_preset_mode` (:4017–4023) on the zone's climate entity:
  occupied → `CONF_ZONE_OCCUPIED_PRESET` (default `home`), vacant →
  `CONF_ZONE_VACANT_PRESET` (default `away`), skipping only if the current
  preset is in `HVAC_PRESET_SKIP = ("manual", "sleep")` (const.py:1106) —
  notably NOT skipping `away`/`home`, and NOT calling
  `_override_arrester.suppress()` (Finding X).
- Climate-entity resolution: `_get_zone_climate_entity` (:4036–4056) —
  `CONF_ZONE_THERMOSTAT` from the zone config, else first room with
  `CONF_CLIMATE_ENTITY`.
- **No other side effects.** No lights, fans, or DB writes — only the
  service call plus `_LOGGER.info/debug/error` lines (:3968, :4003, :4009,
  :4025) and cleanup in `async_will_remove_from_hass` (:4058–4063).
- Private state: `_last_zone_occupied` (:3903) and `_hvac_unsub_listeners`
  (:3904) are used ONLY by the write path.
- Origin: v3.3.5.9 comment at aggregation.py:3930 ("HVAC Zone Preset
  Triggers (v3.3.5.9)").

## 2. Coverage diff vs Writer A — the ONLY-writer question

Live `/config/.storage/core.config_entries` (checked 2026-08-06 via ssh):

| URA zone | `zone_thermostat` | vacant/occupied preset override? |
|---|---|---|
| Back Hallway | `climate.back_hallway_zone_3` | none |
| Entertainment | `climate.thermostat_bryant_wifi_studyb_zone_1` | none |
| Master Suite | `climate.thermostat_bryant_wifi_studyb_zone_1` | none |
| Upstairs | `climate.up_hallway_zone_2` | none |
| Outside | (no thermostat) | none |

- **`zone_vacant_preset` / `zone_occupied_preset` appear NOWHERE in the live
  config** — Writer B has only ever written the defaults `away`/`home`
  (const.py:1104–1105). There is also **no config-flow surface** for these
  keys: repo-wide, `CONF_ZONE_VACANT_PRESET`/`CONF_ZONE_OCCUPIED_PRESET`
  exist only in const.py:1102–1103 and aggregation.py. They are
  set-nowhere, defaults-always constants.
- Writer A (HVAC Coordinator) auto-discovers its zones from
  `CONF_ZONE_THERMOSTAT` (hvac_zones.py:182, :265) — the exact same three
  thermostats (Entertainment + Master Suite merge into the compound
  `studyb_zone_1` HVAC zone by design; see house-zones≠HVAC-zones memory).
- Room-level fallback check: every room carrying `climate_entity` in live
  config points at one of the same three thermostats — no fourth thermostat
  reachable via Writer B's room-fallback path (:4049–4055).
- **Answer: there is NO zone/thermostat where Writer B is the only preset
  automation.** Writer A manages all three climate entities Writer B can
  reach. Removal strands nothing.

## 3. Behavioral differences — user-visible latency

Writer A (`_apply_house_state_presets`, hvac.py:1089; 5-min
`async_track_time_interval` at hvac.py:765–769) computes the target from
`HOUSE_STATE_PRESET_MAP` (hvac_const.py:534–544: every home_* state → `home`)
and uses occupancy only for the D1 vacancy override (away after
`grace_minutes`, hvac.py:1248–1256) and the v4.2.2 entry-dwell skip
(hvac.py:1345–1356). It is also signal-driven, not purely 5-min-clocked:
`SIGNAL_HOUSE_STATE_CHANGED`, `SIGNAL_PERSON_ARRIVING`,
`SIGNAL_ENERGY_CONSTRAINT`, `SIGNAL_ZM_ZONES_UPDATED` subscriptions at
hvac.py:619–662.

What Writer B's event-driven instantness actually buys today:

- **Occupied edge while house_state is home_*:** target is already `home`
  via Writer A's map — Writer B's instant `home` write is redundant except
  in ONE case: re-entering a zone that D1 previously flipped to `away`.
  There, removal introduces an up-to-5-min lag before Writer A restores
  `home`. That is the entire user-visible delta: **≤5 min of `away`-preset
  setpoints (a few °F of drift at most) on re-entry to a vacancy-overridden
  zone.** Arrival-home from outside is separately covered by pre-arrival
  (`SIGNAL_PERSON_ARRIVING` → `_pre_arrival_zones`, hvac.py:2198–2239) and
  by the `arriving` house-state transition — no fast-pre-cool regression.
- **Vacant edge → instant `away`:** removal is strictly an improvement —
  vacancy becomes subject to D1's grace period instead of firing on a
  sub-second binary flap. This instant-away is precisely the flap-audit
  incident mechanism (Finding X step 2).
- Writer B does not respect the arrester, night-trust suppression
  (hvac.py:1380+), dwell, egress pause, or energy constraint — its
  "instant response" is instant *wrongness* whenever those gates disagree.

## 4. Separability of the sensor from the write path

Fully separable. The write path is a bolt-on: methods
`_schedule_hvac_listener_setup`, `_setup_hvac_occupancy_listeners`,
`_handle_zone_occupancy_change`, `_get_zone_climate_entity`, the
`_last_zone_occupied` / `_hvac_unsub_listeners` fields, the
`async_added_to_hass` hook call (:3909), and the unsub loop in
`async_will_remove_from_hass` (:4058–4062). None of these are read by
`is_on` or the Layer 2/3 fallbacks; `_get_zone_config` (:4030) is shared
but read-only. Deleting the write path leaves the sensor byte-identical in
behavior — the dashboard (`lovelace.ura_v8`) and the future P2 predicate
keep their source. **No test references the write path**
(`grep quality/tests` for `_handle_zone_occupancy_change`,
`_setup_hvac_occupancy_listeners`, `ZONE_VACANT_PRESET` → zero hits), so
removal breaks no suite coverage.

Note: `_get_zone_climate_entity` and `_get_zone_config` should be deleted
with the write path unless retained deliberately — nothing else in the
class uses them.

## 5. Removal options

- **(a) Delete the write path outright — RECOMMENDED.** Single-install
  (Single User No Back-Compat memory), no live config uses the preset
  overrides, no config-flow surface promises the behavior, no tests cover
  it, and Writer A + pre-arrival covers every thermostat. Also delete
  `CONF_ZONE_VACANT_PRESET`/`CONF_ZONE_OCCUPIED_PRESET`/
  `DEFAULT_ZONE_*_PRESET` (const.py:1102–1105) — dead after removal —
  and evaluate `HVAC_PRESET_SKIP` (:1106), whose only consumer is Writer B.
- **(b) Legacy flag, default OFF:** rejected — migration scaffolding for a
  one-install integration, and a resurrectable second writer is exactly the
  Finding X hazard.
- **(c) Route through HVAC Coordinator as a proposal:** rejected as part of
  THIS removal — the flap audit's P2-redesign
  (`zone.any_person_present` predicate feeding the D1 vacancy check at
  hvac.py:1249) is the sanctioned future shape, and it consumes the
  sensor's state, not a dispatched write-proposal. Adding a signal now
  would pre-build P2 badly.

Tier per the flap audit's order-of-operations: hotfix-tier surgical change,
**Tier-2 review** (touches a preset-writing surface). This is the audit's
mandated step 1 before P1/P3 land.

## 6. History

- Writer B landed in **7ab922ea3 (2026-02-23) "v3.3.5.9: Service hardening,
  exit retry, and HVAC zone presets"** — the naive-assumptions era the
  operator describes, before any HVAC Coordinator existed.
- The HVAC Coordinator arrived **2f6f70eea (2026-03-07) "v3.8.0: HVAC
  Coordinator H1: Core + Zones + Presets + E6 Signal"** — 12 days later —
  and no commit since has touched, gated, or acknowledged Writer B's write
  path (`git log -S "_handle_zone_occupancy_change"` shows only the
  introducing commit). There is no comment defending its survival; it
  simply was never reconciled. Later work (v4.7.13 Layer 2, v4.7.15 Layer 3)
  extended the *sensor* half of the class and left the writer half
  untouched, which is likely why it escaped notice.

## Answers to the four return questions

1. **ONLY-writer zone:** none. All three live thermostats
   (`back_hallway_zone_3`, `studyb_zone_1`, `up_hallway_zone_2`) carry
   `CONF_ZONE_THERMOSTAT` and are managed by the HVAC Coordinator.
2. **User-visible latency:** only case is re-entry into a D1
   vacancy-overridden zone → up to 5 min before Writer A restores `home`.
   Pre-arrival + house-state signals cover arrival scenarios. Instant-away
   loss is a net improvement (grace period applies).
3. **Separability:** clean. Write path is 6 methods/fields with zero
   coupling to `is_on`/Layers 1–3; sensor and dashboard consumers unaffected.
4. **Recommendation:** Option (a), outright deletion, Tier-2 review, as the
   flap audit's prerequisite step 1.
