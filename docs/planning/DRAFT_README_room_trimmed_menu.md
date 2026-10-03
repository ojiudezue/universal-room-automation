# DRAFT README — ROOM-TYPE-TRIMMED-MENU-1 (room settings menu trimmed by room type)

**Status:** built on `feature/room-trimmed-menu`, deploy HELD for operator.
Version number assigned at deploy (PATCH bump).
Plan: `docs/planning/PLANNING_room_type_trimmed_menu.md` (REV 4, BUILD-READY).

## What changes for you

When you open a room's settings (Settings -> Devices & services -> Universal
Room Automation -> a room -> Configure), the menu now shows only the sections
that room type usually needs.

| Room type | Sections shown |
|---|---|
| Bedroom, Common area, Media room, Generic | all 12 (unchanged) |
| Bathroom | Basic, Sensors, Devices, Lighting, Covers, Climate & Fans, Notifications |
| Garage | Basic, Sensors, Devices, Lighting, Energy, Notifications |
| Infrastructure | Basic, Sensors, Devices, Lighting, Climate & Fans, Energy, Notifications |
| Closet, Hallway | Basic, Sensors, Devices, Lighting, Covers |
| Utility | Basic, Sensors, Devices, Lighting |

- **Nothing you have set is ever hidden.** If a hidden section holds a value
  you changed from the default, that section stays in the menu.
- **More settings…** at the bottom of a trimmed menu shows every section for
  that visit. The next time you open the menu it is trimmed again.
- The hint line at the top of the menu says which room type the list is for.

### A few rarely-used fields are now Advanced-only

| Section | Fields now Advanced-only |
|---|---|
| Cover Automation | Sunrise offset, Sunset offset |
| Climate & Fans | Fan low / medium / high speed temperatures, Humidity fan max runtime |
| Lighting | (unchanged — manual-hold windows, evening brightness/colour, scenes were already Advanced-only) |

If one of these fields holds a value you changed, it is still shown, even when
Advanced mode is off. Hidden fields keep working with their current values,
and saving the form without them does not erase them.

### How to turn on Advanced mode

1. In Home Assistant, click your name at the bottom left of the sidebar (your
   profile page).
2. Turn on **Advanced mode**.
3. Re-open the room's Configure dialog.

With Advanced mode on, the room menu always shows all 12 sections (no "More
settings…"), and the hint says "Advanced settings shown." Advanced mode is a
per-user setting, so other users in the house see their own view.

## Under the hood

- `const.py`: `ROOM_MENU_STEPS_ALL`, `ROOM_MENU_STEPS_BY_TYPE` (rung-1 constants).
- `config_flow.py`, room branch of `async_step_init`: Simple mode = room-type
  steps + any hidden step that holds a non-default value + "More settings…";
  Advanced mode = full menu. New `async_step_show_all_settings`.
- In-use check compares stored values (`{**data, **options}`) with the
  **factory default**, which comes from rendering the step on a separate shim
  flow whose stub entry carries only entry type + room type (plan R1). The
  live flow is never touched; the shim render has no side effects (tested).
  If that render fails, the step is shown (fails open).
- `_adv()` marks Advanced-only fields, but leaves a field unmarked when it holds
  a non-default value. Covers and Climate now go through HA's
  `add_suggested_values_to_schema` (as Lighting already did), so the marker
  takes effect.
- Hint helper renamed: `lighting_advanced_hint` -> `advanced_hint`,
  `LIGHTING_ADVANCED_HINT_*` -> `ADVANCED_HINT_*` (same text). New
  `room_menu_hint`.
- No runtime behaviour change, no migration, no new entities.

## Live checks (post-restart)

- **Closet, Advanced mode off:** menu shows 5 items (Basic, Sensors, Devices,
  Lighting, Covers) + "More settings…"; the hint names "closet rooms" and
  explains Profile -> Advanced mode. "More settings…" -> 12 items; re-open -> 5.
- **Same closet, Advanced mode on:** 12 items, no "More settings…", hint
  "Advanced settings shown."; Climate & Fans shows the fan-speed temperatures;
  Covers shows sunrise/sunset offsets.
- **Garage:** Covers not in the menu; "More settings…" shows it.
- **Legacy room:** a trimmed-type room with energy or notification values only
  in `entry.data` shows those sections without "More settings…".
- **Any room with a changed sunrise offset, Advanced off:** Covers shows the
  sunrise offset field.
- **Integration / Coordinator Manager menus:** description reads normally (no
  literal `{menu_hint}`).

## Validated <date>

(To be filled after deploy + restart, per the README write-back rule.)
