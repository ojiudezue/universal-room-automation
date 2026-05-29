# URA v4.7.5 — Zone Manager UX + Canonical Resolution

**Release date:** 2026-05-29
**Tier:** Tier 2 (two parallel staff-engineer reviews, different framings)
**Scope:** D1 picker LIST mode, D2 house-zone picker, D3 silent canonical resolution, D4 Option C auto-mirror, D5 config-flow runtime smoke tests

**Trigger:**
- Zone Manager Page 1 picker used a dropdown that grew unwieldy as zones increased; LIST mode renders a menu instead.
- The picker showed canonical-merged labels like `"Entertainment + Master Suite"` whenever two house zones shared a thermostat — a leak of internal HVAC-coordinator state into the UI surface.
- Per-house-zone settings on shared-thermostat zones had to be manually mirrored by hand, leading to silent drift between siblings.
- v4.7.4.2 shipped a `selector`-module `ImportError` that source-grep AST tests could not see — closing task #112 by adding runtime instantiation smoke tests.

---

## Headline Changes

### D1 — Dropdown → LIST menu for the ZM picker

`async_step_manage_zones` now renders the zone picker with `SelectSelectorMode.LIST` instead of `DROPDOWN`. Behavior is otherwise identical; the change is purely visual — zone selection is now a menu of radio-style entries rather than a dropdown that hides behind a click.

**Reachable via:**
Settings → Devices & Services → URA Zone Manager → Configure → Manage Zones

### D2 — Picker shows house zones, not canonical-merged labels

The picker now lists raw house zones from `entry.options["zones"]`. Canonical merging (which combines house zones that share a thermostat into a single HVAC zone) no longer leaks into the picker. Zones that share a thermostat get a `(shared thermostat)` suffix in the picker label, making the sharing visible without merging them under one name.

An AST regression test (`test_v475_d2_picker_never_calls_iter_canonical_hvac_zones`) locks the rule: the picker code path must never call `iter_canonical_hvac_zones`. Future contributors who wire it in will see the test fail at CI time.

### D3 — Silent canonical resolution at runtime

`iter_canonical_hvac_zones` continues to merge zones inside the HVAC coordinator. The UI surface never sees the merged view — it derives lazily at read time, mirroring the Bug Class #46 fix pattern from v4.7.4.4.

Documented as **Bug Class #47 — Lazy Canonical Resolution UI Surface Violation** in `docs/QUALITY_CONTEXT.md`. The rule: config-flow / UI code paths read raw `entry.options["zones"]`; only the coordinator runtime invokes `iter_canonical_hvac_zones`. An allowlist test (`test_v475_d3_iter_canonical_hvac_zones_only_called_from_allowlist`) covers the boundary across `custom_components/` and `quality/tests/`.

**Energy consumer hardening:** `energy.py:_async_evaluate_dynamic_presets` previously assumed canonical-merged keys at lookup time. v4.7.5 adds a 3-step explicit resolution (canonical name → split-merged-shape and look up each part → fall back to zone_id with logging) and rejects zone names containing the literal `" + "` separator at config-flow validation time. Prevents name-collision exploits on 3+ constituent merges (`"A + B + C"` no longer mis-splits).

### D4 — Option C auto-mirror on save

When 2+ house zones share a thermostat, saving settings on one auto-mirrors thermostat-tied fields to siblings. A banner on the `zone_config_menu` step renders: *"Shared thermostat: This zone shares thermostat `<entity>` with `<sibling list>`. HVAC, energy, and Dynamic Preset settings saved here also apply to those zones automatically."*

**Mirror sets (per-step `MIRROR_KEYS_*` constants):**

| Step | Mirror keys | Rationale |
|---|---|---|
| `zone_hvac` | `CONF_HVAC_AC_LOAD_SENSOR`, `CONF_HVAC_AC_RAMP_ZONE_ENABLED`, `CONF_ZONE_THERMOSTAT` | Thermostat-tied |
| `zone_energy` | `zone_power_sensors`, `zone_energy_sensors` | Thermostat-tied (audited against schema) |
| `zone_dynamic_preset` | All DPM CONFs on the step | Thermostat-tied (preset semantics follow thermostat) |
| `zone_rooms` | `frozenset()` (none) | Per-house-zone; rooms belong to a zone, not a thermostat |
| `zone_media` | `frozenset()` (none) | Per-house-zone |
| `zone_persons` | `frozenset()` (none) | Per-house-zone |
| `zone_cameras` | `frozenset()` (none) | Per-house-zone |

**One save = one `async_update_entry`:** Every per-zone editor step routes through `_auto_mirror_to_siblings` so the helper folds the mirror write into the primary save. This holds the "one save = one update_entry" invariant the Bug Class #46 fix pattern depends on. An AST regression test (`test_v475_d4_every_save_step_routes_through_mirror_helper`) locks this for all 7 editor steps.

**Unlink path:** When a user reassigns a thermostat away (e.g., zone A had thermostat T1 shared with zone B; user changes A to T2), the mirror writes go to BOTH old siblings (clearing thermostat-tied fields back to defaults on B) AND new siblings (whatever zone C also has T2). `zone_hvac`, `zone_energy`, and `zone_dynamic_preset` all thread `old_thermostat` through the helper.

**Banner rendering as a read-only helper:** `_render_shared_thermostat_banner` is a dedicated side-effect-free method. The explicit read-only contract is documented at the helper — no `async_update_entry`, no dispatcher sends, no task scheduling. Future maintainers who try to extend it with derived-value write-back paths will hit the contract immediately.

### D5 — Config-flow runtime smoke tests (closes task #112)

New test file `quality/tests/test_v475_d5_config_flow_runtime_smoke.py` runtime-instantiates every `async_step_*` handler with `user_input=None` and asserts no `ImportError` / `ModuleNotFoundError` / `AttributeError(homeassistant.*)` escapes. This catches the v4.7.4.2-class of bug (HA upstream module path change) that source-grep AST tests are blind to.

**Mutation-proof test:** `test_v475_d5_mutation_actually_catches_missing_mode_at_runtime` exercises a step after stubbing `SelectSelectorMode.DROPDOWN` away from `homeassistant.helpers.selector` — the test must AttributeError at runtime when the enum member is removed, demonstrating that a future upstream removal would land as a test failure, not a production incident.

**B-M4 trip-wire:** `_StubHass` records every `hass.async_create_task` call. The auto-mirror helper and form-render paths run synchronously inside the options-flow handler and must not schedule background work; tests across D4 and D5 assert `flow.hass.created_tasks == []` on save+mirror round-trips, no-sibling saves, unlink paths, and form renders. A future regression that schedules unintended async work surfaces in tests rather than production (Bug Class #42 prevention).

---

## TL;DR

v4.7.5 cleans up the Zone Manager picker (LIST menu, raw house-zone labels), keeps canonical HVAC zone merging inside the coordinator where it belongs (Bug Class #47), adds auto-mirror on save for shared-thermostat zones with explicit unlink semantics, hardens the energy consumer-side resolver against name collisions on 3+ constituent merges, and adds runtime config-flow smoke tests that would have caught the v4.7.4.2 ImportError class before it shipped.

---

## Review Trail

**Reviewer A (correctness + edge cases):** APPROVE WITH FIXES — 0 CRITICAL / 3 HIGH / 6 MEDIUM / 7 LOW. HIGHs: zone_rooms helper routing, MIRROR_KEYS_ZONE_ENERGY scope, `" + "` split collision. All HIGHs + MEDIUMs fixed in post-review fix-ups 1 & 2.

**Reviewer B (async + lifecycle + race conditions):** APPROVE WITH FIXES — 0 CRITICAL / 3 HIGH / 4 MEDIUM / 4 LOW. HIGHs: legacy zone-entry banner skip, `zone_rooms` helper routing (overlap with Reviewer A), unlink path coverage on `zone_energy` + `zone_dynamic_preset`. All HIGHs + MEDIUMs fixed.

**Combined verdict:** 0 CRITICAL findings across both reviewers. Both reviewers passed Bug Class #43–46 regression checks. New Bug Class #47 formalized in QUALITY_CONTEXT.md as part of the cycle.

**Pre-Deploy Zero-Bugs Gate (all 4 gates pass at `2377ff5`):**
1. Conflict markers: clean
2. py_compile: clean across all changed `.py` files
3. v4.7.5 cycle tests: 36/36 pass
4. Full URA suite: 4118 passed / 55 failed / 14 errors — zero new regressions vs `pre-review-v4.7.5` baseline

---

## Backlog Spun Out During Cycle

- **AC Nudge / AC Reset decouple** (filed in auto-memory `project_ac_nudge_decouple_backlog.md`): split Gate 0 in `hvac_override.py:846` into independent `_ac_nudge_enabled` + `_ac_reset_enabled` toggles with a new `switch.ura_hvac_coordinator_ac_nudge` synced through the config flow. Removes the current side-effect where `daily_limit=0` engages lockout-after-first-failed-eval.
- **`ac_ramp_state` / `ac_ramp_last_action` sensor label scrambling**: entity-id suffixes are misaligned with their friendly-name zone labels. Pre-existing bug surfaced during AC nudge diagnosis.
- LOW-only deferrals from the reviewers are listed in §11 of `docs/planning/PLANNING_v4.7.5_zone_manager_ux.md` with rationale.
