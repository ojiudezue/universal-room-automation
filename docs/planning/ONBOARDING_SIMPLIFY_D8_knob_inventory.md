# ONBOARDING-SIMPLIFY-1 — D8 Knob Inventory (Slice 1)

Doc-only enumeration of tuning knobs currently on the room create path
that D3 (Slice 2) will relocate off essentials. Each row cites the
resolved Options-side target step in the CURRENT tree (grep-confirmed;
plan §D8 numbers were approximate — real line numbers below). No new
knobs introduced this cycle.

| Value / CONF | Create-path site | Rung | Options-side home |
|---|---|---|---|
| `CONF_HUMIDITY_FAN_SPIKE_ENABLED` and spike EMA fields (alpha/base/per-min/cap) | `async_step_climate` (create) `:2136` | Config Options (Rung 2) | `async_step_climate` (Options) **`:10959`** |
| `CONF_BLE_HOLD_CAP_ENABLED` | `async_step_climate` (create) `:2136` | Config Options (Rung 2) | `async_step_climate` (Options) `:10959` |
| `CONF_COMFORT_FAN_AWAY_VETO_ENABLED` | `async_step_climate` (create) `:2136` | Config Options (Rung 2) | `async_step_climate` (Options) `:10959` |
| `CONF_WET_ROOM` | `async_step_climate` (create) `:2136` | Config Options (Rung 2) (soft default via `ROOM_TYPE_FEATURE_DEFAULTS`, Slice 1) | `async_step_climate` (Options) `:10959` |
| `CONF_FAN_SPEED_LOW_TEMP` / `_MED_TEMP` / `_HIGH_TEMP` | `async_step_fan_speeds` (create) `:2296` | Config Options (Rung 2) | **Options `async_step_climate` at `:10959`**, fan-speed block **`:11109-11122`** (single step — no dedicated `async_step_options_fan_speeds` exists in the tree; verified by grep of all `async def async_step_*`). |
| Cover open-mode / offsets | `async_step_cover_behavior` (create) `:1618` | Config Options (Rung 2) | `async_step_options_covers` `:10832` |
| `night_light_detail` fields | `async_step_night_light_detail` (create) | Config Options (Rung 2) | `async_step_options_lighting` `:10723` |

## Verification (grep-confirmed on branch)

```
grep -n "async def async_step_" custom_components/universal_room_automation/config_flow.py
# Options-side steps: options_lighting:10723, options_covers:10832,
# climate:10959 (this second definition is the Options-side; the create-side
# lives at :2136).
grep -n "CONF_FAN_SPEED_" config_flow.py
# schema uses: create :2306-2312 (async_step_fan_speeds);
# Options :11109-11122 inside async_step_climate (Options) — single target.
```

## Non-goals (this cycle)

- No new module constants.
- No new Number/Select/Switch entities.
- Fan-speeds do NOT get a separate Options step this cycle — the fields
  already round-trip through Options `async_step_climate:10959` at
  `:11109-11122`. Rejecting a "new dedicated step" per Marginal-Benefit
  Decomposition: zero user benefit, cost = one more menu jump.

## Deferred to Slice 2

- The actual removal of these steps from the essentials path (D3).
- Test `test_no_tuning_constant_on_essentials_path` (requires the D3
  step reshape to exist).

## Slice 1 test coverage of the inventory

- `test_no_two_producers_wet_room` (D2) — confirms the create-side
  cascade at former `:2035-2042` is deleted and `CONF_WET_ROOM` flows
  from `ROOM_TYPE_FEATURE_DEFAULTS`.
- `test_deferred_parity_humidity_fan_spike_enabled` (D9 anchor row) —
  confirms `ROOM_TYPE_FEATURE_DEFAULTS[bathroom][CONF_HUMIDITY_FAN_SPIKE_ENABLED]`
  is `True` (parity with `wet_default` schema default at create-side
  `:2079-2081` given consumer fallback `False` at `automation.py:2550`).
