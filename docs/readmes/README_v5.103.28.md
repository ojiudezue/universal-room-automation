# v5.103.28 — Room lighting roles + role-vs-inventory sweep (Slice A)

**Status:** DRAFT, deploy HELD for operator go.
Branch: `feature/room-lighting-roles`.
Card: ROOM-LIGHTING-SETUP-REDESIGN-1.
Plan: `docs/planning/PLANNING_room_dialog_cleanup_and_lighting_roles.md` (REV 2.3 + 2.3.1 + 2.3.2).

This README is written slice-by-slice. Slice A landed first — additive,
zero behaviour change. Slice B (D1 darkness) and Slice C (D2 hold + D3
switch) follow in the same branch. Do NOT deploy until every planned
slice has either shipped or been explicitly parked.

---

## Slice A — 2026-09-29 (this commit)

D0 (blast-radius audit) + D8 (role picker inventory) + resolver +
resolver-equivalence test + role picker enumeration.

### What shipped

- `custom_components/universal_room_automation/lighting/resolver.py`
  — new module. `effective_entry_set(cfg, is_sleep_hours)` and
  `effective_exit_set(cfg)`. Additive-only. Mirrors today's inline
  derivation at `automation.py:1000-1064,1079-1082` and
  `actuator_reconciler.py:109`. No callers yet — the helper is the
  seam Slices B–D will consume through.
- `custom_components/universal_room_automation/lighting/__init__.py`
  — package init exporting the two resolver helpers.
- `quality/tests/test_lighting_resolver_equivalence.py` — 28 tests.
  Hand-authored oracles rewrite today's inline code so a regression
  in either helper fails without touching the module under test.
  Both is_dark call-site derivations are covered indirectly through
  the exit-union oracle. Sleep-with-no-night-lights fallthrough is a
  named discriminator test (matches the exact seam `automation.py:1023`
  gates on).
- `docs/planning/AUDIT_sun_fallback_blast_radius.md` — D0 audit doc.
  AFFECTED = 3 rooms at probe time (2 no-sensor + 1 currently-unavailable
  lux sensor). Operator sign-off gates D1 (Slice B) build.
- `docs/planning/AUDIT_room_dialog_role_picker_inventory.md` — D8
  enumeration. 7 role-picker sites in `config_flow.py`, tagged
  KEEP/MOVE per plan. Physical MOVE is Slice B.

### Zero-behaviour-change proof

- Slice A adds a new package (`lighting/`), a new test file, and two
  audit docs. Nothing in `automation.py`, `actuator_reconciler.py`,
  `config_flow.py`, `switch.py`, or any coordinator is touched. The
  helper has no callers yet; production code paths are byte-identical
  to develop @ `1bb5f72fa`.
- Resolver-equivalence test (28 tests) proves the helper matches the
  inline derivation on 8 config fixtures × 2 sleep states for entry,
  plus 8 fixtures for exit, plus 4 named discriminators.

### Per-site drills (Slice A load-bearing sites)

Ran on 2026-09-29, this commit, PYTHONDONTWRITEBYTECODE=1 +
`__pycache__` cleared before each run:

| Site | Mutation | Result |
|---|---|---|
| `resolver.py::effective_entry_set` day/union return | replace return with `return []` | 11 tests FAIL, tree restored, 28/28 PASS after restore |
| `resolver.py::effective_exit_set` union return | replace return with `return []` | 8 tests FAIL, tree restored, 28/28 PASS after restore |

Both helpers are load-bearing on the resolver-equivalence suite. Clean
`git status --short` after restoration verified.

### Test selection + name-diff vs develop

Selection: `-k "light or automation or reconciler or config_flow or options or strings"`.

| Run | Passed | Failed | Skipped | Deselected |
|---|---:|---:|---:|---:|
| develop @ `1bb5f72fa` baseline | 1026 | 5 (pre-existing) | 4 | 10958 |
| feature/room-lighting-roles (Slice A) | 1054 | 5 (same) | 4 | 10958 |
| Delta | **+28 (new tests)** | 0 new failures | 0 | 0 |

Pre-existing failures (unchanged on both sides, unrelated to Slice A):

- `test_census_device_switches.py::test_d4_transit_validator_reads_true_on_empty_options`
- `test_census_device_switches.py::test_d4_presence_initial_read_returns_true_on_empty_options`
- `test_d3_area_inherit.py::test_options_overrides_data_for_area`
- `test_energy_write_verification.py::test_c_med_1_h3_options_round_trip_source_anchor`
- `test_v5_7_1_energy_precool.py::TestD5Migration::test_restore_entity_off_overrides_options_true`

### Live acceptance criteria (prospective, for Slice A alone)

Because Slice A has no runtime callers, live acceptance reduces to:

- Verify: `custom_components/universal_room_automation/lighting/`
  package loads with no import error on HA start (integration reload
  clean).
- Verify: no room entry/exit lighting behaviour change post-deploy vs
  pre-deploy for any test room (baseline unchanged — nothing consumes
  the helper yet).
- Live: at least one dark-only room with a working lux sensor lights
  on entry at dusk (control observation — proves today's path is
  unaffected).

Live validation results table will be filled in post-restart per the
CLAUDE.md "Record Live Validation Back Into the README" rule.

### Slice A deferrals (tracked, not dropped)

- Physical picker MOVE (Night Lights → Lighting step, Alert Lights →
  Lighting step, Auto/Manual → behaviour Auto/Manual sub-block).
  Deferred to Slice B because MOVE without dynamic `include_entities`
  from in-flight flow state hits F5 (silent value drop on save).
- `CONF_AUTO_DEVICES` / `CONF_MANUAL_DEVICES` picker rendering not
  found in `config_flow.py`; Slice B must locate before MOVE.
- Strings / translations: no updates in Slice A because no new
  form fields. Slice B / D1 will extend `strings.json`,
  `translations/en.json`, and `quality/tests/test_room_dialog_strings.py`
  when the Lighting step is added.

---

## Slice B — 2026-09-29 (D1 darkness fallback)

Adds a sun-position fallback to `RoomAutomation.is_dark` for rooms
whose primary illuminance sensor returns None (no sensor, or state
`unavailable` / `unknown`). Per-room kill switch defaults TRUE per
operator P0 ruling.

### What shipped

- `const.py` — new keys `CONF_LIGHT_DARK_USE_SUN_FALLBACK`,
  `CONF_LIGHT_DARK_LUX_SOURCE`, and module-const safety bound
  `SUN_DARK_ELEVATION_DEG = -6.0` (civil dusk).
- `lighting/darkness.py` — new module. `is_dark_fallback(cfg, hass)`
  implements the plan §D1 order: borrowed lux → sun → False.
  Availability-only freshness (R2-3): sensor state in
  `unavailable`/`unknown`/empty is skipped, `last_updated` age is
  NEVER consulted. Fail-safe: any exception ⇒ False (never
  auto-light on error).
- `automation.py::is_dark` — extended to route the None-illuminance
  case through `is_dark_fallback`. Because
  `actuator_reconciler.py:794` calls `automation.is_dark(...)`, both
  is_dark call sites the plan enumerated (F2 / R2-2) route through
  ONE definition and receive the fallback.
- `lighting/__init__.py` — exports `is_dark_fallback`.

### What was intentionally deferred (with reasons)

- **No new options-flow field for `CONF_LIGHT_DARK_USE_SUN_FALLBACK`.**
  The code respects the key from stored options; default TRUE per
  operator P0 ruling covers the intended behaviour for the ~3
  AFFECTED rooms. A per-room UI toggle needs `strings.json` +
  `translations/en.json` + `test_room_dialog_strings.py` extension —
  operator's guidance was "borrowed lux only if trivial, else note it
  for a later slice"; the same trivia-vs-slice-bloat calculus applies
  here. **Tracked as a Slice B' follow-up: add
  `CONF_LIGHT_DARK_USE_SUN_FALLBACK` (bool) + `CONF_LIGHT_DARK_LUX_SOURCE`
  (entity) as config-flow fields in the Lighting step once that step
  exists in Slice C or later.** Until then, operators who need a
  per-room disable set the key manually or accept default-TRUE.
- **Borrowed lux (`CONF_LIGHT_DARK_LUX_SOURCE`) code path** IS
  implemented (trivial add — 5 lines) — see step 1 of
  `is_dark_fallback`. It reads from stored options if set. Only the
  UI to set it is deferred with the kill-switch toggle.

### Behaviour change on live rooms (from the D0 audit)

For the 3 AFFECTED rooms (2 no-sensor + 1 currently-unavailable lux
sensor), `entry_light_action = turn_on_if_dark` now engages after
civil dusk instead of never engaging. All other rooms unchanged.

### Per-site drills (Slice B load-bearing sites)

Ran on 2026-09-29, this commit:

| # | Site | Mutation | Result |
|---:|---|---|---|
| 3 | `lighting/darkness.py::is_dark_fallback` sun path (`return elev < SUN_DARK_ELEVATION_DEG`) | replace with `return False` | 8 tests FAIL (7 fallback + 1 wiring); restored; 52/52 PASS |
| 4 | `automation.py::is_dark` call to `is_dark_fallback` | keep import, replace call with `return False` | 1 test FAIL uniquely (`test_none_lux_sun_below_dusk_falls_through_to_true`), proving the wiring at this site is the load-bearing path; restored; 52/52 PASS |

Drill #4 is the wiring drill required by F2 / R2-2 (both is_dark
callers must reach the new fallback). Because
`actuator_reconciler.py:794` delegates to `automation.is_dark`,
neutering the automation.py call site also breaks the reconciler
path — one drill covers both consumer surfaces.

### Test selection + name-diff vs develop (Slice A + Slice B)

Selection: `-k "light or automation or reconciler or config_flow or options or strings"`.

| Run | Passed | Failed | Skipped | Deselected |
|---|---:|---:|---:|---:|
| develop @ `1bb5f72fa` baseline | 1026 | 5 (pre-existing) | 4 | 10958 |
| feature/room-lighting-roles (Slice A) | 1054 | 5 (same) | 4 | 10958 |
| feature/room-lighting-roles (Slice A + B) | 1072 | 5 (same) | 4 | 10964 |
| Delta A→B | +18 (new fallback tests in-selection) | 0 | 0 | +6 (wiring tests, names not matched by `-k`) |
| Cumulative delta A+B | **+46 in-selection, +6 out-of-selection** | 0 new failures | 0 | +6 |

Same 5 pre-existing failures (listed under Slice A above); zero
regressions from Slice B.

### Live acceptance criteria (Slice B, prospective)

- Verify: a room with no `CONF_ILLUMINANCE_SENSOR` and
  `entry_light_action=turn_on_if_dark` lights on entry after civil
  dusk (previously never lit).
- Verify: same room during daylight (sun elevation > 0) does NOT
  light on entry.
- Verify: Garage B (currently-unavailable lux sensor) behaves the
  same as no-sensor rooms — lights at dusk, dark at day. When its
  sensor recovers, primary-lux path resumes automatically.
- Verify: any room with a working lux sensor is UNCHANGED — the
  fallback only fires when the primary read is None.
- Verify: setting `CONF_LIGHT_DARK_USE_SUN_FALLBACK: false` on a
  room's stored options (via YAML / storage edit until Slice B' UI
  lands) preserves today's `is_dark(None) == False` for that room.

Live validation results table filled in post-restart.

---

## Slice C — pending (D2 hold + D3 room-light switch)

Not yet built.

---

## Slices D, E — pending (D4 house-state, D5/D6 slots+scenes)

Not yet built.
