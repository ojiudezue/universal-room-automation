# Zone Manager Manual (Operator Manual)

**Audience:** the homeowner running URA.
**Scope:** the URA Zone Manager entry — what a "zone" is in URA, how
you wire rooms into it, per-zone knobs, and the sensors it publishes.
**Current through:** URA v5.45.0 (`const.py:34`).

Sibling of `HOUSE_MANUAL.md`, `CM_MANUAL.md`,
`ENERGY_COORDINATOR_MANUAL.md`, `HVAC_COORDINATOR_MANUAL.md`.

This is not a code walkthrough. For per-coordinator design see
`PRESENCE_COORDINATOR.md` and the planning docs.

---

## 1. What the Zone Manager is

A single `ENTRY_TYPE_ZONE_MANAGER` config entry that stores a `zones`
dict — each entry is one **house zone** (a group of your rooms for
aggregation, HVAC handoff, and music-following). One Zone Manager per
install; each zone is a key inside its options.

Zones you configure here are exposed as:
- **Zone devices** (`URA: Zone <zone_name>`), each carrying the
  per-zone entities described in §4.
- **Zone-aware attributes** on the house-level sensors described in
  `HOUSE_MANUAL.md §5`.

**House zone ≠ HVAC zone.** This is a persistent source of confusion:
- **HVAC zones** are Carrier Infinity thermostat zones (3 on this
  deployment).
- **House zones** are the URA groupings you configured per area.
- **One HVAC zone maps to MULTIPLE house zones by design.** Compound
  names like "Entertainment + Master Suite" on an HVAC zone entity
  are the legitimate merge. Full detail in
  `HVAC_COORDINATOR_MANUAL.md §2`.

---

## 2. Getting to the Zone Manager UI

**Settings → Devices & Services → URA: Zone Manager → Configure**

The top-level menu (`config_flow.py:2600-2607`) currently exposes:
- **Manage Zones** — pick a zone, then land in the per-zone config
  menu described in §3.

Zone options are stored inside the ZM entry's options under a `zones`
dict keyed by zone name (§7). Legacy per-zone config entries also
work; they're handled by the same forms but are being migrated.

---

## 3. Per-zone config menu

After selecting a zone, the menu (`config_flow.py:7612-7657`) offers:

| Menu item | What it edits | Field |
|---|---|---|
| **Zone Rooms** | zone name, description, rooms, outdoor flag | `zone_name`, `zone_description`, `zone_rooms`, `zone_is_outdoor` |
| **Zone Media** | media player + follow mode | `zone_player_entity`, `zone_player_mode` |
| **Zone HVAC** | thermostat / zone-side HVAC ties | (see `HVAC_COORDINATOR_MANUAL.md`) |
| **Zone Energy** | zone-scoped power / energy sensors | (v4.1.0) |
| **Zone Persons** | primary sleepers / occupants for HVAC pre-arrival | `zone_persons` |
| **Zone Cameras** | face-confirmed-arrival cameras (HVAC pre-arrival) | `zone_cameras` — occupancy/motion binary_sensors |
| **Zone Dynamic Preset** | per-zone bucket setpoints (see `docs/user-manual/DYNAMIC_PRESET.md`) | Cool / Mild / Hot / Extreme buckets |
| **Zone Delete Confirm** | delete zone (visually separated) | — |

When the selected zone shares its thermostat with sibling zones, the
menu renders a banner (`config_flow.py:7642`) explaining that HVAC /
energy / DPM saves auto-mirror to the shared-thermostat siblings.

---

## 4. Per-zone fields and defaults

Verified against `const.py:64-93` + `config_flow.py:7664-7873`.

| Key | Default | Notes |
|---|---|---|
| `CONF_ZONE_NAME` | — | Free text; **cannot contain " + "** (reserved as the merge separator, `config_flow.py:7715-7730`). |
| `CONF_ZONE_DESCRIPTION` | "" | Free text. |
| `CONF_ZONE_ROOMS` | [] | Multi-select of your configured Room entries. Adding a room here writes `CONF_ZONE=<zone_name>` onto that room's options; removing it clears the room's `CONF_ZONE`. |
| `CONF_ZONE_IS_OUTDOOR` | False (`const.py:72`) | v5.7.0. Outdoor zones still track occupancy but are **excluded from the indoor-occupancy aggregate** that gates the AWAY path — a porch camera can't block the house going AWAY when everybody's out. |
| `CONF_ZONE_PLAYER_ENTITY` | — | Media player used for zone playback. |
| `CONF_ZONE_PLAYER_MODE` | `fallback` | `independent` / `aggregate` / `fallback` (`const.py:87-93`). |
| `CONF_ZONE_PERSONS` | [] | Primary persons for this zone. Consumed by HVAC pre-arrival on geofence arrival (v3.18.5). |
| `CONF_ZONE_CAMERAS` | [] | Face-confirmed-arrival cameras for HVAC pre-arrival (v3.19.0). **These are the ZONE-side "someone is arriving" cameras** — distinct from a room's `CONF_ROOM_CAMERAS` fusion input (§5). |

Zone overrides for presence live on a per-zone Select entity (§4.1),
not in the options flow.

### 4.1 Per-zone Select — `ZonePresenceMode`

Every zone device exposes a Select entity
(`select.py:240-301`, unique_id `<domain>_<zone_slug>_presence_mode`):

- **Options:** `AUTO` (default), plus the members of
  `ZONE_PRESENCE_OVERRIDE_OPTIONS` (typically `AWAY`, `OCCUPIED`,
  `SLEEP`).
- Setting anything other than AUTO **overrides zone-tracker inference**
  until a real detection resumes AUTO. Ephemeral: not persisted with the
  intent to last forever — the house state machine cannot be "paused",
  this is the closest thing.

The Select writes through the presence coordinator's
`tracker.set_override(option)` — same code path a service call would
take. If the zone tracker isn't yet wired (early boot), the Select
degrades to AUTO and logs a WARN.

---

## 5. Zone-aware sensors (what to watch)

- **`sensor.<domain>_zone_<zone>_active_rooms`** (`sensor.py:4444-4470`)
  Attributes: `active_rooms`, `inactive_rooms`. **First stop** for
  *"which room is holding this zone occupied?"*
- **Aggregation sensors** (`const.py:128-141`): `anyone_home`,
  `rooms_occupied`, `occupant_count` — per-zone rollups.
- **Zone identified / guest persons** (`const.py:1176-1177`):
  `SENSOR_ZONE_IDENTIFIED_PERSONS`, `SENSOR_ZONE_GUEST_COUNT`.

Zone occupancy is a **roll-up of its rooms** — the zone doesn't have
its own sensors; it aggregates the rooms you've listed under
`CONF_ZONE_ROOMS`. A room that's occupied but not in any zone still
contributes to the house tier; it just doesn't appear in any
zone-scoped aggregate.

---

## 6. Camera fields — where they live

Cameras are configured in **three distinct places** and it's worth
being clear which is which:

1. **`CONF_ROOM_CAMERAS`** (room options; `const.py:708`) — multi-select
   of any camera-related entities on the room. Feeds the per-room
   fused `binary_sensor.<room_slug>_camera_person_detected` and the
   comfort-fan AWAY-veto rebuttal. See `HOUSE_MANUAL.md §14`.
2. **`CONF_ZONE_CAMERAS`** (zone options; §4) — face-confirmed-arrival
   cameras for HVAC pre-arrival. Zone-side arrival trigger; not part
   of room fusion.
3. **Integration-level census lists** (`const.py:1072-1074`):
   `CONF_CAMERA_PERSON_ENTITIES` (legacy interior),
   `CONF_EGRESS_CAMERAS`, `CONF_PERIMETER_CAMERAS`. Consumed by the
   whole-house census (`camera_census.py`) and the perimeter alerter.
   Different consumer, different problem.

Do NOT try to make one list serve two purposes — the resolvers and
consumers are different. If a physical camera should participate in
both a room's fusion and the whole-house census, add its entities in
both places.

---

## 7. How zones are stored

- **New style (preferred):** the Zone Manager entry's options carry a
  `zones` dict keyed by zone name. Each value is the per-zone options
  described in §4.
- **Legacy style:** per-zone config entries of `ENTRY_TYPE_ZONE`. The
  UI still edits these; the code prefers the ZM-stored path when
  present (`config_flow.py:7669-7671`).

Rename a zone: change `CONF_ZONE_NAME` on the Zone Rooms form. The
old zone device is removed from the device registry and each affected
room's `CONF_ZONE` is updated in-place (`config_flow.py:7756-7763`).

---

## 8. Common gotchas

- **A room shows in `inactive_rooms` and I think it should be
  active.** Read `sensor.<room>_occupied` first (Room tier is the
  source of truth; zone aggregates it). Then check the room's own
  `STATE_OCCUPANCY_SOURCE` per `HOUSE_MANUAL.md §7`.
- **Outdoor zone blocking AWAY.** If a porch/patio zone doesn't have
  `zone_is_outdoor=True`, its camera person sensor will hold the
  indoor-aggregate up and the house will refuse AWAY. Toggle the
  flag (§4).
- **" + " in a zone name.** Rejected on save — the sequence is
  reserved as the shared-thermostat merge separator.
- **Zone Cameras vs Room Cameras.** Room-camera fusion (v5.44+) does
  NOT read `CONF_ZONE_CAMERAS`. If a camera should participate in a
  room's fan-veto rebuttal, add it to `CONF_ROOM_CAMERAS` on the
  room, not to the zone.

---

## 9. Pointer surfaces

- **House-tier behavior** (state machine, AWAY veto, guest, sleep):
  `HOUSE_MANUAL.md §5`.
- **Coordinator Manager** (11 coordinator step menu, notifications,
  house-state override select): `CM_MANUAL.md`.
- **HVAC handoff** (Dynamic Preset, shared thermostat, sibling
  auto-mirror): `HVAC_COORDINATOR_MANUAL.md` and
  `docs/user-manual/DYNAMIC_PRESET.md`.

---

Relevant files:

- `/Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/const.py`
- `/Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/config_flow.py`
- `/Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/select.py`
- `/Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/sensor.py`
