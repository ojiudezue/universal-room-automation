# v5.100.8 — Room "Zone" field now syncs to zone membership (+ D3 test fix)

**Type:** Config-flow correctness. **Tier:** 2 — orchestrator wire-in mutation-verify. Cards:
`ROOM-ZONE-FIELD-NO-SYNC-1`, `D3-CANONICAL-ALLOWLIST-BINARYSENSOR-1`.

## Why
Setting a room's **Zone** in Room Setup wrote `room.CONF_ZONE` but never added the room to that
zone's membership list (`zone.CONF_ZONE_ROOMS`) — bridged only by a one-time migration. New rooms
had to be added by hand in the Zone dialog, and rooms with a zone showed under "Unzoned/Utility"
on dashboards.

## What shipped
- **`_sync_room_zone_to_zm`** (config_flow.py) — on room-setup save, upsert the room into its
  chosen zone's `CONF_ZONE_ROOMS` and remove it from any prior zone; `zone=None` removes it from
  all. Idempotent (zero `async_update_entry` calls when the ZM already agrees), swallow-except so a
  sync hiccup never breaks the room save. Wired at `async_step_basic_setup` (with an old-zone
  snapshot) **and** at `async_setup_entry` for `ENTRY_TYPE_ROOM` (covers create + boot drift).
  `room.CONF_ZONE` is authoritative; `zone.CONF_ZONE_ROOMS` is the derived index. The reverse
  direction (ZM save → room) already existed.
- **D3 test fix** — `binary_sensor.py`'s `iter_canonical_hvac_zones` caller (per-canonical-HVAC-zone
  egress-window sensor) is runtime-legit; added to the D3 allowlist with justification (guard teeth
  verified). Greens the pre-existing red guard.
- **(rides on restart)** v8 Residence dead-entity-ref cleanup — 51 dead auto-entities include refs
  stripped (`.storage`, applied on this restart).

## Live validation
- **L1:** restart clean, config valid.
- **L2:** setting/changing a room's Zone adds/moves it in the Zone dialog's room list (no manual add);
  the dashboard groups it under its real zone (Unzoned/Utility mis-grouping resolved for zoned rooms).
- **L3:** `test_v475_d3_canonical_runtime_only` green.

_Validated <date> — filled in post-restart._
