# AUDIT — Zone-tier vs house-tier divergence (ZONE-TIER-DIVERGE-1)

**Status:** Diagnosis of record. READ-ONLY source trace + live/recorder verification — no fixes applied.
**Evidence:** develop @ a7ff3574, live `.storage/core.config_entries` (via `ssh ha`), HA recorder
(`/config/home-assistant_v2.db`, mode=ro, scoped by `states_meta`), live entity reads 2026-08-13.
Incident window: 2026-08-13, all timestamps UTC (Z).
Parent doc: `AUDIT_away_transition_2026_08_13.md` §F2/§Follow-up item 5.

## Verdict in one paragraph

**BUG — confirmed, still live.** The house tier and the zone-entity tier key rooms by **two
different room names for the same config entry**: the presence coordinator's
`ZonePresenceTracker.room_names` are resolved from `entry.data["room_name"]`
(presence.py:2868), while the `OccupancySubstrate` maps and dispatches edges under the **merged**
`{**data, **options}` name (occupancy_substrate.py:197-202). Three room entries have been renamed
via options without updating data — `Jaya Bedroom (Bedroom 4)` → options `Jaya Bedroom`,
`Upstairs Guestroom` → options `Guest Bedroom 2`, `Down Guest Bathroom` → options
`Guest Bedroom 1 Bathroom` — so every substrate edge for those three rooms arrives at
`_on_substrate_kind_changed` with a name no tracker owns and is **silently dropped**
(presence.py:3082-3090 "Substrate edge for unknown room"). The house tier is therefore
**permanently blind to all Tier-1 occupancy in those three rooms**. The two Upstairs rooms
occupied all afternoon on 08-13 were exactly the two renamed Upstairs rooms — hence
zone_upstairs sensors (which key rooms by config-entry object, not name) read occupied while the
house-state attrs showed Upstairs `mode='away'` with zero provenance, and the 20:51:06Z
`home_day → away` fired through a still-occupied Jaya Bedroom. There is no discount/scoping rule
involved; the attrs display was faithful to the (blind) tracker. This is not a display bug.

## Q1 — Which aggregation does the away path consume? Are there two computations?

**Yes — two entirely different computations of "zone occupied", with different room-keying,
different inputs, and different smoothing:**

| | House tier (away path) | Zone entities (`zone_upstairs_*`) |
|---|---|---|
| Code | `presence.py:5209-5212` — `any_zone_occupied = any(t.mode == OCCUPIED for t in self._zone_trackers.values())`; indoor variant 5221-5226; consumed by `infer()` at 1026-1031 (census-0 rule) and 1091-1094/1128 (`indoor_blocked`, path β) | `aggregation.py:3866-3872` (`ZoneOccupiedSensor.native_value`), 3953-3957 (`ZoneAnyoneBinarySensor.is_on` Layer 1) |
| Room membership | ZM entry `zones[z]["zone_rooms"]` (entry IDs) resolved via **`room_entry.data.get(CONF_ROOM_NAME)`** — presence.py:2864-2876 | Per-room `CONF_ZONE` field on each ROOM entry, matched against coordinator objects — aggregation.py:3839-3843. **Never touches a room name.** |
| Occupancy input | Raw substrate per-kind edges (`_on_substrate_kind_changed` → `tracker.update_room_occupancy`, presence.py:3090) + zone cameras + BLE | Room coordinators' smoothed `coord.data[STATE_OCCUPIED]` (room-tier timeouts, fan latches included) + Layer 2/3 zone_persons fallbacks |
| Staleness | None on Tier-1 (event-driven bools); camera timeout only | Room-tier `occupancy_timeout` smoothing |

The **join key between the two halves of the house tier itself is a bare string room name**, and
the two producers of that string disagree:

- Substrate map: `merged = {**entry.data, **entry.options}` → `merged.get(CONF_ROOM_NAME)` —
  occupancy_substrate.py:197-202 → dispatches `room_name` = **options name**.
- Tracker `room_names` + `_room_to_zone`: `room_entry.data.get(CONF_ROOM_NAME, "")` —
  presence.py:2868 → **data name**.
- `tracker.update_room_occupancy` hard-guards `if room_name not in self.room_names: return`
  (presence.py:773-774); `_on_substrate_kind_changed` drops unknown rooms at presence.py:3082-3090.
- `_discover_room_sensors` (register_entity + provenance seed) uses the **merged** name
  (presence.py:3000-3023) and does `self._room_to_zone.get(room_name)` → miss →
  `tracker is None: continue`. So the renamed rooms get **no registration, no seed, and no live
  edges** — a triple miss all caused by the same key divergence.

**Zone registration:** Upstairs is NOT unregistered. The ZM `zones` dict contains Upstairs with
11 zone_rooms, all entry IDs resolving to live entries (verified live). The boot warning
`zone not registered in zone_manager.zones` is a different table entirely — the **HVAC**
`_zone_manager` consulted by the ZoneAnyone Layer-2/3 fallbacks (aggregation.py:4006, 4141) — and
the `Room Study A/Living Room expects HVAC fan management…` warning is the HVAC fan-controller
wiring (automation.py:1930). Related-smelling but distinct tables; neither is this mechanism.

## Q2 — Who writes "mode=away with zero provenance", and how can it coexist with occupied rooms?

Writer: `PresenceHouseStateSensor.extra_state_attributes` — sensor.py:5020-5049. Per zone it
publishes `tracker.mode`, `_zone_provenance_breakdown(tracker)` (reads
`tracker._room_provenance`), `fan_interference_rooms` filtered by `rn in tracker.room_names`, and
`tracker._fan_on_rooms`. All four read the SAME tracker the away path reads — **the attrs and the
away decision cannot disagree with each other; both diverge together from the zone entities.**

Zero provenance + away while member rooms are occupied happens exactly when a zone's only
occupied rooms are name-mismatched: provenance is only ever written by
`update_room_occupancy(kind=...)`, which the mismatch blocks at all three entry points (seed,
register, live edge). The empty fan lists have the same root: `_discover_room_fans`
(presence.py:~3240-3285) resolves the fan's room from the **merged** config, then does
`if room_name in tracker.room_names` (data names) → never matches for the three rooms → their
fans are absent from `_fan_entity_to_room`/`_fan_on_rooms`, and `_handle_fan_change` never stamps
`_fan_last_transition` for them. Yes — this is a `zone_rooms`-adjacent wiring miss, but the broken
link is the data-vs-options name, not the zone_rooms list (which is correct).

**Live reproduction (2026-08-13, today):** `binary_sensor.jaya_3_presence` = `on`, yet
`binary_sensor.jaya_bedroom_bedroom_4_occupied` attrs show `substrate_kinds` all-false,
`tier1_provenance` all-false, `last_edge_entity=""`, `last_kind_to_fire=""` — the room
coordinator queries the substrate with its `entry.data` name (coordinator.py:853, 970) while the
substrate keys the bucket under the options name, so even the ROOM-tier diagnostic surface is
blind. (The room still reads occupied because the room tier keeps its own direct entity
listeners.) `sensor.zone_upstairs_rooms_occupied` currently lists the room as
"Jaya Bedroom (Bedroom 4)" (data name via aggregation.py:3880) — the two names visible
side-by-side in production.

## Q3 — Why did away fire at 20:51:06Z with Jaya occupied?

Inputs the transition consumed (reconstructed; recorder-corroborated):

1. `census_count = 0` since 19:29:17Z (all four persons not_home).
2. `any_zone_occupied` / `indoor_blocked`: Entertainment's tracker released at 20:46:42Z (Screek
   OFF, 37 s after fan-off). Upstairs' tracker had been AWAY the whole time because its only
   occupied rooms (Jaya Bedroom, latched by `jaya_3_presence` ON continuously from 19:00:16Z with
   `fan_temp` running; Upstairs Guestroom, hobeian latched 19:07:59→20:46:35Z) are the two renamed
   rooms — every one of their substrate edges was dropped at presence.py:3082-3090. Upstairs
   zone_cameras (upstairs_hall / playroom / stairs_top) all quiet after 19:16:22Z (recorder), BLE
   none. So from 20:46:42Z **no tracker read OCCUPIED**.
3. The census-0 nobody-home rule (presence.py:1026-1031, force-away emit ~5740-5780:
   `census_count==0 AND not any_zone_occupied`) became satisfiable and fired on the next
   inference ticks → `home_day → away` conf 0.9 at 20:51:06Z.

Jaya Bedroom **is** in a zone the away path checks (Upstairs, ZM zone_rooms entry `01KJXMA4VR` →
resolves fine) — the away path simply never received its occupancy. No trust discount applies:
v4.7.13 sleep-only trust lives in the room-tier D2 demotion gate (`coordinator.py:1816-1843`) and
vetoes only SLEEP/WAKING/HOME_NIGHT demotion; house was `home_day`, and no zone-scoped trust rule
discounts Upstairs. The blindness, not a doctrine, is the whole mechanism.

## Q4 — Why did Entertainment veto 19:29-20:46 but Upstairs not veto at 20:51?

Same code path (`indoor_blocked` / `any_zone_occupied` over `_zone_trackers`), and **the
discriminator is nothing semantic — it is which rooms have consistent names**:

- Living Room: `options.room_name` unset → merged name == data name == "Living Room" → substrate
  edges route into the Entertainment tracker → `mode=OCCUPIED`, provenance `{mmwave:1}`,
  `fan_on_rooms=["Living Room"]` → blocked path β + census-0 for 82 minutes.
- Jaya Bedroom / Upstairs Guestroom: options name ≠ data name → edges dropped → Upstairs tracker
  starved → `mode=AWAY`, zero provenance, empty fan lists.

Not zone flags (`zone_is_outdoor` only on Outside), not zone type, not the nonsleep fallback
(that lives in the aggregation-tier ZoneAnyone sensor, which the away path does not consume).
Negative control from today: Upstairs currently shows `mode=occupied` with `{motion:1, mmwave:1}`
— fed by its name-consistent rooms (Game Room, Media, etc.). The tracker works whenever a
name-consistent room fires; it is blind only to the three renamed rooms.

## Q5 — Verdict, mechanism, blast radius, fix, tier

**BUG.** Divergent room-name keying (entry.data vs merged options-first) across the presence
stack. Latent since the three rooms were renamed via the options flow (the options flow writes
`room_name` to options; nothing writes it back to data). Any future room rename recreates the
class. The v5.46.0-era boot warnings the operator saw are cousins (HVAC-side wiring tables also
join on names), worth re-checking after the fix.

**Blast radius for the three mismatched rooms** (everything reading the tracker or substrate by
the wrong key):
1. House away/veto/census inference — `any_zone_occupied`, `any_indoor_zone_occupied`,
   `indoor_blocked`, census-0 force-away (this incident; also means these rooms can never veto
   away, and conversely can never help hold a zone occupied).
2. WAKING gate `any_zone_raw_occupied` (presence.py:5237-5239) — morning movement in Jaya/Guest
   Bedroom 2 cannot contribute to exiting SLEEP.
3. All tracker-side fan machinery for these rooms: `_fan_on_rooms`, `_fan_on_since`,
   `_fan_last_transition` never populated → v5.46.0 fan-transition creation gate, D3
   fan-interference flagging, and the D2 mmWave-fan demotion's fan legs are ALL dead here —
   stacking on top of the no-PIR fail-closed gate documented in the parent audit. (Guest
   Bedroom 2's unflagged fan latch in §F1 is partly this.)
4. Room-tier substrate-derived diagnostics (`substrate_kinds`, `tier1_provenance`,
   `last_edge_entity`, `last_kind_to_fire`) — all permanently false/empty (verified live).
5. Any consumer of `tracker._room_occupied` / `check_zone_occupancy_confidence`-style zone
   confidence for these rooms (HVAC defer/vacancy consumers see them as never-occupied at the
   zone tier).

**Smallest fix (two rungs):**
- **Config-only mitigation (today, zero code):** re-align the three entries so
  `options.room_name == data.room_name` (pick the display name, write it to both — a one-shot
  `.storage` edit or options-flow save + data patch). Instantly un-blinds all five surfaces.
- **Code fix (the real one):** single canonical accessor for a room's name (merged,
  options-first) used by ALL readers — presence.py:2868 ZM resolution, coordinator.py room_name
  reads (853/970/1020/1372), and any other `entry.data.get(CONF_ROOM_NAME)` site — OR make the
  options-flow rename write-through to `entry.data` via `async_update_entry` plus a one-shot
  migration syncing existing entries. The write-through variant is smaller and kills the class
  (one producer, no N-consumer sweep), but needs the reload-suppression allowlist checked.

**Tier: 2-DB minimum** (shared-primitive key threading through presence ↔ substrate ↔ room
coordinator ↔ HVAC consumers; the failure mode is one missed site — Bug Class #53 shape). If the
fix touches the rename/reload path of config entries, elevate per operator judgment. A regression
test must assert name-consistency: for every ROOM entry, substrate map key ==
tracker-resolved name (a 10-line invariant test that would have caught this on the day of the
rename).

**Why the attrs "contradiction" was not a display bug:** sensor.py's zones block faithfully
mirrors the tracker; the tracker was faithfully starved. The contradiction is between the two
aggregation systems, and the zone entities (config-object-keyed) were the ones telling the truth.

**Irony worth recording:** on 08-13 the bug produced the operator-desired outcome — Jaya's
"occupancy" was itself a fan-latch phantom, so the blind house tier went away correctly for the
wrong reason. Fixing this bug and NOT fixing the fan-latch class (parent audit recs 1-2) would
make the away transition HARDER to reach (three phantom-holdable zones instead of one). Sequence
the fixes together.
