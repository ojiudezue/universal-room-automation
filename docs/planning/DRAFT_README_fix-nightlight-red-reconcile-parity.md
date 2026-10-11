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
4. **Review B B1-1 (HIGH, same card):** `automation.py` has THREE
   night-light entry call sites, not one. The night-light-only
   early-return (~1456) was already applying the house-Sleep
   mode-switch. The two downstream sites (`has_on_entry` picker
   ~1553, and the else branch ~1566) were NOT. With
   `CONF_SLEEP_PROTECTION_ENABLED=False` (the default),
   `is_sleep_lighting_active()` is False even when the house is in
   Sleep, so those branches shipped evening/day kelvin to a colour
   night light during house-Sleep. BOTH sites now apply the same
   narrow helper:

   ```python
   _nl_mode = (
       "sleep" if self._house_state_is_sleep()
       else ("evening" if slot == LIGHT_SLOT_EVENING else "day")
   )
   ```

5. **Review B B1-2 (MEDIUM):** the reconciler's
   `entry_night_light` return (now line ~931) previously had no
   `has_params_to_apply`, so the already-on gate (actuator_reconciler
   :645) could skip a bulb that was already "on" — a power-cycled
   colour bulb returning at factory warm white stayed warm white. Now
   `has_params_to_apply=(_mode == "sleep")`: sleep forces re-apply so
   the red-vs-kelvin decision is asserted onto the live state; day /
   evening keep the R3-M3 manual-dim-override skip.

6. **Review B B1-3 (LOW):** `switch.RoomLightsSwitch.async_turn_on`
   also built night-light params by hand (brightness only, own sleep
   test). It now routes through `night_light_turn_on_params` with
   per-entity live `supported_color_modes` and honours
   `_house_state_is_sleep()`, grouping entities by identical params
   for batched service calls — same pattern as
   `automation._turn_on_night_lights`. Unused brightness/colour
   constants pruned from `switch.py`.

   - **On-wire consequence of B1-3 outside sleep:** when
     `RoomLightsSwitch` is manually turned on **outside** sleep (and
     outside house-Sleep), the switch now routes night-light params
     through the resolver in `"day"` mode. The resolver returns
     `{brightness_pct, color_temp_kelvin}` for a FULL-capability
     bulb (verified: `test_nl_params_full_capability_day` at
     `quality/tests/test_night_light_rule_resolver.py:146`;
     `color_temp_kelvin = CONF_NIGHT_LIGHT_DAY_COLOR` or its default
     — resolver.py:195-198). FULL night lights now receive the day
     colour temperature in addition to brightness, where previously
     only brightness was shipped. This matches the entry-path
     writer and the reconciler and is the parity the cycle is
     closing.

   - **Side-effect noted (Review A F2, LOW):** the reconciler's sleep +
     occupied branch previously built params by hand and only
     carried `brightness_pct` for FULL-capability bulbs. It now routes
     through `night_light_turn_on_params`, so a FULL **white-only**
     bulb (e.g. supported modes `{"color_temp"}`) will receive
     `color_temp_kelvin` in addition to `brightness_pct`. This brings
     the reconciler into parity with the canonical writer
     (`_turn_on_night_lights`), which has always emitted
     `color_temp_kelvin` for FULL bulbs. The branch fires only on
     return-from-unavailable, so the on-wire change is bounded to
     reconnect events (not steady-state).

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
