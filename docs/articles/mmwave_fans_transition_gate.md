# Your Ceiling Fan Is Impersonating You: Hunting mmWave Phantom Presence

<!-- slug: mmwave-phantom-presence -->
<!-- date: 2026-08-02 -->

*How we found — in recorder data, to the second — that fan speed changes
create phantom mmWave occupancy, and the three-layer defense that fixed it
without new hardware. From the Universal Room Automation project
(https://universalroom.org, https://github.com/ojiudezue/universal-room-automation).*

## The symptom

A study with nobody in it ran its tower fan for four hours on a summer
afternoon while the house was in `away` mode. The room's mmWave sensor said
someone was there. The PIR said nothing. The occupancy system believed the
mmWave — and the fan it had switched on was, we suspected, the very thing
keeping the mmWave convinced.

If you run mmWave presence sensors (LD2410/LD2412/LD2450 family, Aqara FP2,
Everything Presence, etc.) near a fan, you have probably seen a version of
this. The usual advice — "move the sensor," "mask the zone," "lower the
sensitivity" — trades away real coverage to suppress a fault you haven't
actually characterized.

## Measure before you build

Before designing anything we ran a one-shot, read-only probe over the Home
Assistant recorder database — a week of history that already existed. No new
instrumentation, no live experiments, ~10 minutes of scripting. Three
findings changed the design:

**1. Phantoms begin at the exact second of a fan transition.** Both labeled
phantom events in the week's data — different rooms, different fan types
(a ceiling fan and a DC tower fan) — had their mmWave rising edge aligned
to the second with a fan power/speed change in the same room. Not "while
the fan was running": at the *transition*.

**2. Steady-state fans are innocent.** Multi-hour windows of fans running
at constant speed in vacant rooms produced no phantom onsets. The radar
adapts to a constant moving target; what it cannot ignore is the *change* —
spin-up, spin-down, speed steps — which reads as a new mover entering the
field.

**3. Where energy channels exist, phantom and human textures separate.**
On sensors that expose LD2410 `still_energy`, the phantom signature is a
tight low band (p10–p90 of 33–47, coefficient of variation 0.20) with high
60-second autocorrelation (0.86 — sticky, slow-drifting), while a real
occupant is high and wide (median 79, CV 0.34) and fast-decorrelating
(0.16). Both the center and the *texture* separate. This is a corroborator,
not a primary: it needs per-unit fitting and only exists where the firmware
exposes energy channels.

The literature check was sobering: blade micro-Doppler rejection is a
research topic, and no shipping consumer firmware does fan rejection.
Zone-exclusion polygons (LD2450-class) are the only validated hardware-side
mitigation — and they cost you the coverage under the fan. If you want the
coverage, the fix has to live in fusion.

## The design: three mechanisms at three stages

The temptation is one big rule ("ignore mmWave when the fan is on") — which
also blinds you to a real person reading under that fan. Instead we ship
three narrow mechanisms, each at a different stage of the occupancy
lifecycle, each with its own kill switch:

**1. Creation prevention — the fan-transition coincidence gate.** When a
would-be occupancy *creation* is supported by mmWave alone (no PIR, no BLE,
no camera) and the rising edge lands within 5 seconds of a fan power/speed
transition in that room, the creation is suppressed and a counter
increments. Five seconds is enough because the probe showed exact-second
alignment; a person walking in during that window is almost always caught
by PIR/BLE/camera co-fire, which admits normally — and a suppressed
mmWave-sole tick deliberately preserves any in-progress entry-debounce
clock, so corroboration one tick later doesn't restart from zero.

**2. Sustain correction — fan-corroboration demotion.** If mmWave-sole
occupancy *persists* under a running fan (fan on ≥10 minutes, PIR stale
beyond twice the room timeout, no BLE or camera person), the occupancy is
demoted and released, and a latch prevents mmWave alone from re-creating it
until a clean edge (mmWave-off, PIR, BLE, or fan-off). Hard gates: never
during sleep-family house states, never in rooms with no PIR to consult
(fail closed), never during boot settle.

**3. Actuation guard — the away-veto.** Independent of occupancy state,
comfort-fan actuation while the house is `away` requires *trusted* evidence
(recent PIR, active BLE, camera person) — mmWave alone cannot switch a fan
on in an empty house. This breaks the feedback loop at the actuator even if
the first two layers miss.

The layering matters because each mechanism's failure mode is covered by
another. The gate can miss a genuinely coincident event (event-ordering
race between the fan stamp and the mmWave read in the same tick — measured,
documented, accepted); the demotion catches it ten minutes later. The
demotion can't act in a no-PIR room; the veto still blocks the actuator.

## What we deliberately did not build

- **A "fan mode" sensitivity profile** — punishes real occupants under fans.
- **Runtime signature classification** on still_energy — parked as a
  corroborator behind an evidence trigger (if the gate + demotion leave a
  measurable residual, revisit). The probe fitted one unit in one furniture
  configuration; shipping per-unit learned thresholds for pennies of
  marginal benefit fails the cost/risk decomposition.
- **Hardware changes** — no sensor moves, no zone masks, no coverage loss.

## Results and observability

Every mechanism is observable on the room's occupancy entity: a
suppression counter for the gate, a demotion counter and latch flag for
the sustain leg, a veto counter for the actuator guard. The incident that
started this — a restart recreating the morning's exact conditions (hot
vacant room, house away) — produced zero fan actions post-fix where the
original produced "fans on at 100%."

## Takeaways for your own setup

1. **Suspect transitions, not fans.** If your phantom onsets align with
   fan speed changes (check your recorder history — the alignment is to
   the second), a short transition window is a far cheaper filter than a
   fan-on blanket rule.
2. **Fuse, don't mask.** mmWave is your only stationary-person detector.
   Any fix that discards it while a fan runs trades a phantom for a blind
   spot. Prefer demanding corroboration at *creation* and letting
   corroborated occupancy stand.
3. **Probe your recorder before designing.** A week of history and ten
   minutes of scripting rejected two designs we would otherwise have
   built, and produced the 5-second constant the shipped design rests on.
4. **Make every number a named constant with a kill switch.** Our window
   is one constant; setting it to zero disables the gate. When (not if) a
   sensor firmware update changes the physics, the operator can turn the
   mechanism off without a code change.
