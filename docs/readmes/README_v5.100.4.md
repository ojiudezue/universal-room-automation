# v5.100.4 — Zone picker is now a one-tap menu (MENU-ZONE-PICKER-1)

**Type:** Config-flow UX. **Tier:** 2 (flow-routing change). Self-review + behavioral test proof +
live validation. Card: `MENU-ZONE-PICKER-1`.

## Why
Operator, looking at the live "Manage Zones" screen: *"Why not make this a regular menu vs a
select button and submit?"* The zone picker rendered as a `SelectSelectorMode.LIST` form — pick a
radio, then tap **Submit** (two taps). A menu navigates on the first tap.

## The HA constraint (why it was a form)
HA config-flow menus route a selection to `async_step_<next_step_id>`, and `next_step_id` must be
one of the menu-option keys (verified in `data_entry_flow.py`) — there is **no shared handler**.
That fits a *static* step set (which is why every other URA menu is a static list), but the zone
list is **dynamic**. So a true menu needs a dispatch shim.

## What shipped
- **`async_step_manage_zones`** now returns `async_show_menu` with `menu_options` = a dict of
  `{"zpick_<i>": "<Zone Label>"}` (inline labels; "(shared thermostat)" suffix preserved). Raw
  house zones only — the D2/D3 canonical-merge contract is unchanged.
- **`UniversalRoomAutomationOptionsFlow.__getattr__`** — a strict-prefix dispatch shim: a missing
  `async_step_zpick_<i>` resolves to a handler that sets `_selected_zone_name` (from a
  `_zone_menu_map` built at render) and routes to `async_step_zone_config_menu`. Every other missing
  name raises `AttributeError`, so normal attribute lookup / `hasattr` / the lazily-set
  `_selected_zone_name` are all preserved. A stale/unknown key safely re-renders the picker.
- Menu title/description carry the shared-thermostat guidance (menus don't render `data_description`).

## Tests
- `test_v475_d1_picker_list_mode.py` — repurposed: asserts the method calls `async_show_menu`,
  builds no `SelectSelector`/`async_show_form`, and the `__getattr__` shim + prefix constant exist.
- `test_v475_d5_config_flow_runtime_smoke.py` — **behavioral** (real config_flow module under stubs):
  instantiates the flow, renders the menu (`menu_options={'zpick_0':'Office'}`, inline label),
  dispatches `async_step_zpick_0` → confirms it sets `_selected_zone_name="Office"` and routes to
  `zone_config_menu`; a stale key falls back to the picker. Also asserts `__getattr__` raises
  `AttributeError` for non-zone names and doesn't shadow set attributes.
- D2 (raw zones / no `iter_canonical`) unchanged and passing. (Pre-existing unrelated red:
  D3 `binary_sensor.py` allowlist — carded `D3-CANONICAL-ALLOWLIST-BINARYSENSOR-1`, not this cycle.)

## Live validation — acceptance criteria (discriminating)
- **L1:** restart clean, config valid.
- **L2 (one-tap):** ZM → Configure → Manage Zones shows a **menu** (no radio + Submit); tapping a
  zone opens its categorized submenu directly.
- **L3 (labels — the one thing not verifiable offline):** each menu row shows the **zone name**
  (e.g. "Back Hallway", "Entertainment (shared thermostat)"), NOT the raw key "zpick_0". If keys
  show, HA's frontend treats dict values as translation keys — fall back to per-key translated
  labels. (Backend payload confirmed inline in-suite.)

_Validated <date> — filled in post-restart._
