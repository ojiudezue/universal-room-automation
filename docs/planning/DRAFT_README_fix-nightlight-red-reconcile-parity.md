# DRAFT README — fix/nightlight-red-reconcile-parity

Card: NIGHTLIGHT-RED-RECONCILE-PARITY-1 (Tier 1 hotfix).

## Problem

At sleep with `CONF_NIGHT_LIGHT_SLEEP_HUE=red`, the canonical writer
`automation._turn_on_night_lights` (~1855-1895) sent `rgb_color` red
(`NIGHT_LIGHT_SLEEP_RED_RGB`) to colour-capable night lights via a
per-entity live `supported_color_modes` check (`rgb/rgbw/rgbww/hs/xy`).

The reconcile-on-return path (`actuator_reconciler._resolve_light`,
sleep-occupied branch ~820-836 and the house-state-sleep fallthrough
at ~883) did NOT consult the shared resolver's red-hue decision:

- The sleep-occupied branch built params by hand with only
  `brightness_pct` — never `rgb_color`.
- The house-state=sleep override called `night_light_turn_on_params(cfg,
  "sleep")` without live modes, so the resolver returned
  `color_temp_kelvin` (warm white).

Result: a colour-capable night light that disappeared and reconnected
while the room was at sleep came back **warm white**, not red. Two
writers were disagreeing on one value (Bug Class #53 flavour).

The red-hue decision was duplicated in `automation.py` behind a
function-local import (Bug Class #34).

## Fix

1. Move the red-hue decision into the shared resolver
   `lighting/resolver.py:night_light_turn_on_params`. New kwarg
   `supported_color_modes: Iterable[str] | None`. When `mode == "sleep"`,
   capability is `FULL`, hue is RED, and the supplied modes intersect
   `{rgb, rgbw, rgbww, hs, xy}` (the SAME "colour-capable" test the
   canonical path used), the resolver emits `rgb_color =
   NIGHT_LIGHT_SLEEP_RED_RGB` INSTEAD OF `color_temp_kelvin`. Default
   `None` preserves pre-cycle `color_temp_kelvin` behaviour for callers
   that cannot read live modes.

2. `automation.py`:
   - Hoist `night_light_turn_on_params` import to module top (Bug Class
     #34). Resolver only depends on `.const` — no import cycle.
   - Delete the duplicated red-hue decision; call the resolver per
     entity with that entity's live `supported_color_modes`; group
     entities by identical params to batch service calls.

3. `actuator_reconciler.py`:
   - Both night-light sleep branches now call the resolver with the
     entity's live `supported_color_modes` (via a new
     `_live_color_modes(entity_id)` helper that reads
     `hass.states.get(e).attributes["supported_color_modes"]`).

## Tests

New file `quality/tests/test_nightlight_red_reconcile_parity.py` (9
tests, all pass):

- Resolver red output requires FULL capability + red hue + rgb-capable
  modes; kelvin-only bulbs still get warm white; non-sleep modes never
  emit red; `supported_color_modes=None` back-compat emits kelvin.
- Reconciler sleep-occupied branch: colour bulb (`hs`) → `rgb_color`
  red; kelvin-only bulb → `color_temp_kelvin`.
- Canonical `_turn_on_night_lights`: mixed colour + kelvin bulb config
  at sleep → each gets the right params in one or two batched service
  calls; day mode never emits red.

Behavioural anchor + call-neuter drills (`PYTHONDONTWRITEBYTECODE=1` +
cache clear, restored after):

- Neuter `actuator_reconciler._resolve_light`'s `supported_color_modes=
  self._live_color_modes(entity_id)` → `None`: reconciler anchor fails
  (returns `color_temp_kelvin` for a colour bulb at sleep). Restore
  leaves `git status` clean.
- Neuter `automation._turn_on_night_lights`'s `supported_color_modes=
  modes` → `None`: canonical anchor fails. Restore clean.

Full lighting-adjacent run (12 files, 202 tests): all pass.

## Prospective Live validation (discriminating)

After deploy + restart, observe the following at the next sleep
window AND engineer a reconnect to prove it:

- **PASS** — Pull a colour-capable night light's power or Zigbee
  briefly during sleep so it goes `unavailable`; when it comes back,
  the entity attributes carry `rgb_color = [255, 30, 10]` and NO
  `color_temp` for the resulting state. The URA activity log row for
  the reconcile pass shows `rgb_color` in the service payload.
- **DIFFERENT FAILURE** (pre-fix behaviour that this ships against) —
  reconnected bulb comes up with a positive `color_temp` and no
  `rgb_color`. Observing this post-ship means the resolver is receiving
  an empty mode set (likely a HA quirk where the attribute is missing
  at reconnect-tick time); open a card for a short grace-read before
  deciding, do NOT revert.
- **UNRELATED FAILURE** — bulb stays unavailable (device-side). Not
  this fix's domain.
