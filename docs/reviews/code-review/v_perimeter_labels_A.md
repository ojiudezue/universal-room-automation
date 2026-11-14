# Review A (Tier 1): PERIMETER-SWITCH-LABELS-AND-FLOW-PARITY-1

Branch `feature/perimeter-switch-labels` @ 4aea7bf8. Diff base = `git merge-base develop HEAD` = 065408f0 (verified; three-dot diff, one commit).

Framing: local correctness + edge cases + test-authority spot check. Not an HVAC or presence change (no state-of-play docs required).

## Verdict: SHIP (no CRITICAL/HIGH/MEDIUM)

## Checks

| Check | Result | Evidence |
|---|---|---|
| Entity ids / unique ids unchanged | PASS | switch.py object_id + unique_suffix lines untouched (only fallback_name changed); select.py:1201 unique_id and :1206 entity_id unchanged. No URA code/test references the old names. |
| Names match operator list | PASS | Lower Road Alerts / Lower Single-Sourced Alerts / Unknown Person Door Alert / Add Names to Alerts / AI Person Check; select states Off / Watch only / On (strings.json + en.json identical). Matches card `decided_names`. |
| Name HA actually shows | PASS | HA `Entity._name_internal` (helpers/entity.py:689) returns `_attr_name` when set, so the fallback wins over translation_key. Both now carry the new names, so either path shows them. Select drops the "Perimeter" prefix; with `has_entity_name=True` HA prefixes the device name, so the shown name is "Universal Room Automation AI Person Check" (same pattern as the switches). |
| Select stored values | PASS | Options still `PERIMETER_VLM_GATE_OPTIONS` (off/shadow/enforce); translations only map labels. `current_option` (select.py ChatterModeSelect ~1021) falls back to default (off) for a stored invalid value; flow step does the same (config_flow.py ~5267). |
| Options-flow save | PASS | `{**options, **cleaned}`; single-sourced key popped on a one-NVR install (drill 2 RED). All five keys are in `INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS` (__init__.py:7817-7821), so a save does not reload. |
| Resolver registry-only, fails closed | PASS | camera_resolver.py:1433-1453 uses `enumerate_platform_cameras` + `resolve_detection_legs` integration field, no name guessing, broad except -> False; `dual_nvr_present` (perimeter_fp_gates.py:31) also False on error. |
| Setup timing | PASS (LOW note) | Entity/device registries are loaded during bootstrap before config-entry setup, so the Frigate/Protect entries exist even if those integrations load after URA. Gate reads only the registry. |
| Hidden switch with a stale stored True | PASS | Gate is inert per camera anyway: perimeter_alert.py:4957 `not both -> reason single_nvr`. |
| Step title "Perimeter Alert Filters" | Reasonable | Avoids colliding with the existing "Perimeter Alerting" step; plain phrase per label guide. |
| Orphan note | Correct | Not auto-removing is the right call: a false-negative boot would delete a live entity. |

## Findings

- **LOW-1** (behavior note, no fix): switch.py:216 evaluates the dual-NVR gate once at setup. Adding the second NVR later shows the switch only after a URA reload or restart. The flow step re-evaluates on each open, so the flow can show the field while the switch is still absent. Acceptable; worth one README line.
- **LOW-2** (cosmetic): the switch description for single-sourced says "Only shown when a camera is watched by both systems", which is true of creation, not of display. Fine as is.

## Mutation spot-check (my own, cycle test files only; tree restored, `git status` clean of source changes)

| Site neutered | Result |
|---|---|
| switch.py:265 `if _dual_nvr else None` removed (always create) | RED: `test_one_nvr_install_has_no_single_sourced_switch` |
| config_flow.py:5228 `cleaned.pop(...)` replaced with `pass` | RED: `test_one_nvr_flow_hides_single_sourced_and_never_writes_it` |
| camera_resolver.py:1446 Frigate-leg check replaced with `if legs:` | RED: 3 tests incl. `test_resolver_false_for_protect_only_install` |

Baseline: 201 passed (test_perimeter_switch_labels_flow_parity.py + test_perimeter_fp_gates.py).

## Bug class tally
None found. Classes weighed: #53 one-missed-site (strings.json and en.json both updated; all three gate sites covered), #62 hollow anchor (tests drive real setup/flow/resolver, all three drills RED).
