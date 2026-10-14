# Review — EC-OPTIONS-CLEAR-FIELD-NOOP-1 (Framing A: local correctness + operator clarity)

Branch `fix/ec-options-clear-field` @ 1895a876d, base 295057da7 (verified = merge-base). Tier 1.
Targeted tests: `quality/tests/test_ec_options_clear_field_noop.py` 8 passed.

## Findings

| # | Sev | Site | Finding | Class |
|---|---|---|---|---|
| A1 | HIGH | config_flow.py:6327-6330 | Clear is a no-op in the real UI. Every cleared field is rendered with `suggested_value=self._get_current(key)` (e.g. :6661-6663), so the form submits the STORED entity unless the operator also blanks the field. The new-wins rule `if _ck and not user_input.get(_ck)` then treats the prefilled old value as a "fresh pick" and skips the pop. Repro: stored `energy_solar_follow_grid_fallback_entity=sensor.x`; open step, tick "Clear solar-follow grid power fallback", Submit; `user_input` carries `sensor.x`; saved options still hold `sensor.x`; Repairs issue persists. Tests pass only because they omit the key from `user_input` (test_ec_options_clear_field_noop.py:64,87,238), which is not what the frontend sends. The room precedent (config_flow.py:12827-12832) deliberately makes CLEAR win ("explicit clear beats accidental leftover"). Fix: pop unless the submitted value differs from the stored one (`user_input.get(_ck) in (None, "", stored)`), or adopt clear-wins. Add a test that submits the prefilled stored value plus the tick. | #62 hollow anchor / fixture does not model the producer |
| A2 | LOW | config_flow.py:6327 | `.pop()` only clears options. If a role key ever lives in CM `entry.data`, the runtime merge `{**data, **options}` (scanner __init__.py:945) resurfaces it. The room precedent writes `""` for this reason (:12815-12819). I found no path that writes EC role keys into CM data, so this is latent. `_norm_cm_opt` treats "" as unset, so writing "" would be safe here too. | #53 scope |
| A3 | MEDIUM (clarity) | strings.json / translations/en.json | No `clear_grid_fields` label or description for the energy step in either file (grep count 0), so HA shows the raw key `clear_grid_fields` above 36 checkboxes. Add a data label ("Clear fields") and a description ("Tick to remove a saved entity. Leave the field itself alone.") | operator clarity |
| A4 | LOW (clarity) | strings.json:2311 | The repair text names `{key}` as the raw CONF key (`energy_solar_follow_grid_fallback_entity`), but the checkbox says "Clear solar-follow grid power fallback". The operator has to map one to the other. `{problem}` renders as `not_in_registry` for registry-missing entities ("the entity is not_in_registry"), which predates this change. Placeholders are otherwise valid (key/entity_id/problem all supplied at __init__.py:1005-1009) and both JSON files are identical for the key. | operator clarity |

## Cleared (holds because)
- **Q1 coverage/render:** all 36 CONF keys appear in `async_step_coordinator_energy` (config_flow.py:5880-7534). Map is EC_ROLE_KEY_SET plus grid import/export, with no key missing. The cloud_verification flatten (:6120) and baec flatten (:6147-6152) both run before the merge/pop (:6313-6330), so pops hit top-level keys.
- **Q2 absent == unset:** none of the 36 keys are in `derive_envoy_config` (energy_const.py:1262-1285; Enpower keys are explicitly not derived). Every DEFAULT_* for the cleared keys is None or `[]` (energy_const.py:240-263, 305-308, 566, 1023, 1215-1216; energy_circuits.py:56). `_build_entity_map` setdefaults cloud oracles to None (energy.py:1116-1127). The one-shot pin is flag-gated (`EC_DEFAULTS_PINNED_FLAG`, __init__.py:847), so a cleared key is not re-pinned on restart. The scanner clears the issue for an unset key (__init__.py:964-966).
- **Q3 reload:** an unchanged save means `_norm_cm_opt` diff is empty, so there is no reload (__init__.py:8624-8632). All 36 keys are in `EC_CONSTRUCTION_ENTITY_KEYS` and none are in `OPTIONS_RELOAD_SUPPRESS_KEYS` (checked at runtime), so a clear schedules exactly one parent reload (:8637-8648).
- **Q4 new wins:** correct for a genuinely different pick. See A1 for the prefilled-same-value case.
- **Q6:** the two JSON files are identical for `ec_role_entity_broken` (json compare True).

## Q5 — 36 rows in one selector: KEEP, with A3 fixed
The labels are plain short phrases and none are misleading. Splitting into per-section clear widgets would mean four new selectors and flatten paths for a rarely used action. Keep one list in the current grouped order. Fix A3 so the widget has a heading.

## Verdict: FIX-REQUIRED
Must fix: **A1** (the clear does nothing in the real frontend unless the field is also blanked). Should fix in the same pass: A3. Optional: A2, A4.

| Sev | Found | Fixed |
|---|---|---|
| HIGH | 1 | 0 |
| MEDIUM | 1 | 0 |
| LOW | 2 | 0 |
