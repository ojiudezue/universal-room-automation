# D8 — Role picker inventory (Slice A enumeration)

Cycle: ROOM-LIGHTING-SETUP-REDESIGN-1, Slice A.
Author: builder, 2026-09-29 (branch `feature/room-lighting-roles`).
Read-only sweep of `custom_components/universal_room_automation/config_flow.py`
covering every `async_step_*` that renders a role-picker `EntitySelector`
or `cv.multi_select`. Slice A ENUMERATES; the physical picker MOVE
happens in Slice B once the new Lighting step and dynamic
`include_entities` scaffolding land (avoids the F5 "picker drops saved
values" hazard called out in the plan review).

## Confirmed picker sites

| # | Key | Step / Method | file:line | Slice B action |
|---|---|---|---:|---|
| 1 | `CONF_LIGHTS` | initial room setup — devices | config_flow.py:1755 | **KEEP** (canonical inventory step; this is the enumeration surface) |
| 2 | `CONF_LIGHTS` | edit-path devices step | config_flow.py:2003 | **KEEP** (edit-path parity with #1) |
| 3 | `CONF_NIGHT_LIGHTS` | edit-path devices step | config_flow.py:2010 | **MOVE** → new Lighting step (Slice B) |
| 4 | `CONF_ALERT_LIGHTS` | edit-path notifications step | config_flow.py:3034 | **MOVE** → new Lighting step (Slice B); alert COLOR stays in Notifications per plan |
| 5 | `CONF_AUTO_SWITCHES` | initial room setup — devices | config_flow.py:1760 | **MOVE** → Auto/Manual sub-block in behaviour step (Slice B / later) |
| 6 | `CONF_AUTO_SWITCHES` | edit-path devices step | config_flow.py:2062 | **MOVE** (parity with #5) |
| 7 | `CONF_MANUAL_SWITCHES` | edit-path devices step | config_flow.py:2065 | **MOVE** (parity with #5) |

Confirmed by grep `CONF_LIGHTS\|CONF_NIGHT_LIGHTS\|CONF_ALERT_LIGHTS\|CONF_AUTO_DEVICES\|CONF_MANUAL_DEVICES\|CONF_AUTO_SWITCHES\|CONF_MANUAL_SWITCHES` across the file. No `EntitySelector` for `CONF_AUTO_DEVICES` / `CONF_MANUAL_DEVICES` was found (these keys are declared in `const.py:884-885` but the picker rendering is elsewhere — Slice B must confirm where before wiring the MOVE).

## Read-only sites (NOT pickers — these are validators / defaults / cleanup, no MOVE needed)

- `config_flow.py:1022` — pre-populate loop over `(CONF_LIGHTS, CONF_AUTO_SWITCHES, CONF_FANS, CONF_COVERS)` in the reset-defaults path.
- `config_flow.py:1728` — reads `user_input.get(CONF_LIGHTS)` after user submits the devices step.
- `config_flow.py:1831` — display count (`n_lights = len(...)`) in the review step.
- `config_flow.py:1979` — sub-step gate `if user_input.get(CONF_NIGHT_LIGHTS)`.
- `config_flow.py:2573-2574` — cleanup loop across role keys.

These continue to read the same stored keys after Slice B's picker MOVE
because Slice B does NOT rename keys; only picker locations change.

## What Slice A did NOT do (deferred to Slice B on purpose)

The plan calls for MOVING Night Lights / Alert Lights / Auto-Manual
pickers into a new Lighting step. That MOVE requires:

1. A new `async_step_lighting` / `_edit_lighting` step, dynamically
   sourced `include_entities` from **in-flight** flow state (a pattern
   not present in `config_flow.py` today), and
2. The stored options to round-trip losslessly across the MOVE (F5:
   without dynamic `include_entities`, a Night Light outside
   `CONF_LIGHTS` gets filtered out on save and is silently dropped).

Slice A ships only the enumeration. Physical MOVE is Slice B or a
subsequent D8-focused slice, gated on the new Lighting step existing.

## Deleted / added / renamed keys in Slice A

None. Slice A is additive-only (new `lighting/` helper module + new
resolver-equivalence test + these audit docs). Stored options are
untouched. The resolver-equivalence test in
`quality/tests/test_lighting_resolver_equivalence.py` proves absent new
keys ⇒ today's entry/exit set derivation.
