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

## Slice B — pending (D1 darkness resolver)

Not yet built. Blocked on operator sign-off of the D0 audit above.

---

## Slice C — pending (D2 hold + D3 room-light switch)

Not yet built.

---

## Slices D, E — pending (D4 house-state, D5/D6 slots+scenes)

Not yet built.
