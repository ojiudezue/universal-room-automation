# Plan review — ROOM-TYPE-TRIMMED-MENU-1 (Tier 2, one adversarial plan review)

Plan: `docs/planning/PLANNING_room_type_trimmed_menu.md` @ develop a293ad5fb. Read-only review, all claims re-grepped.

**Verdict: REVISE.** Menu-filter idea is sound. But the load-bearing D3 predicate rests on two false premises, and D4 describes a wizard that no longer exists.

## Findings

1. **HIGH: the in-use check reads `options` only, but stored config also lives in `entry.data`.** Plan D2 uses `opts = self._config_entry.options`, and D3 says "present in `options`". The wizard writes everything into `entry.data` (`config_flow.py:1841-1848`). Options steps read `options` first and fall back to `data` (`_get_current`, `config_flow.py:3167-3171`). Chains fall back to `data` too (`:12247`).
   - **Repro 1 (falsifies the invariant):** a utility room is created and `devices_confirm` area-prefills CONF_COVERS (`:1748`). That only touches `devices`, so no harm there. The real break is a room created by the pre-ONBOARDING-SIMPLIFY wizard, which walked climate/energy/notifications/sleep steps and stored into `data`. Take such a closet with `CONF_POWER_SENSORS` or `CONF_NOTIFY_SERVICE` in `data` and the energy/notifications steps never saved in options. The step is hidden while its values are live.
   - **Fix:** evaluate against `{**entry.data, **entry.options}`, same as `_get_current`.
2. **HIGH: `ROOM_TYPE_FEATURE_DEFAULTS` is not a defaults table.** It holds one type (bathroom) and three keys (`const.py:1546-1556`). The real defaults are inline `default=` literals in each step's schema (e.g. `config_flow.py:11951-11983`). Several depend on the room type:
   - `wet_default = room_type == BATHROOM` (`:2672`)
   - `ROOM_TYPE_BLE_HOLD_CAP_DEFAULT` (`:2678`)
   - `ROOM_TYPE_TIMEOUTS` (`:1466`)
   - the fan-mode default depends on HVAC-zone membership (`:11705`, `__init__.py:1786`)

   D3's `MODULE_DEFAULT` names nothing. The builder will invent a second defaults table, which is Bug Class #63 (coincidental-equality) waiting to happen.
   - **Fix:** specify the predicate as "differs from what the step's own schema would render for an empty entry". Or pick the simpler rule in Finding 3.
3. **MEDIUM (simplification, marginal-benefit): per-key equality buys little, because a false-show is harmless.** Every options save stores the whole form (`merged = {**options, **user_input}`, e.g. `:11946`), so default-valued keys end up persisted anyway. The recommended rule is: step is in use iff any of its keys exists in merged data/options with a truthy, non-empty value different from the schema default. At minimum, collections should use "non-empty" only.

   The main false-show source is `_migrate_room_fan_mode` (`__init__.py:1765-1790`). It writes `CONF_ROOM_FAN_MODE` into every room's options, and the select entity writes it too (`select.py:207-209`). When the migration mode is not `off`, climate would un-hide on every closet or utility room, so the trim silently does nothing for climate. **Decide explicitly** whether `room_fan_mode` counts as in use. Recommendation: exclude it from the reveal set, because it is dashboard-owned (Select entity).
4. **HIGH: D4's premise is false.** The add-room wizard is now `room_setup → room_class → sensors_confirm → devices_confirm → room_summary` (`config_flow.py:1526-1533`). The comment at `:1529-1533` states that the old mid-flow steps are unreached on the create path. The wizard walks none of the 12 options steps, so there is nothing to filter.
   - The "closet walks 5 steps / utility 4 / infrastructure 7" acceptance tests are unbuildable.
   - The "skipped steps take defaults" worry doesn't apply: no crash risk from skipping, because consumers already run on today's essentials-only rooms.
   - **Fix:** drop D4, its test, and its Live criterion. Optionally, D4' hides the CONF_COVERS field in `devices_confirm` for utility/infrastructure. That is a field-level change, so it is out of scope per the non-goals.
5. **MEDIUM: nested `section()` keys.** Climate flattens `humidity_fan_advanced` and `climate_backstop` (`:11593-11598`), and lighting flattens `reconcile_advanced` (`:11359-11363`). The D3 "schema→table consistency test" must descend into section schemas. Otherwise it either fails spuriously or misses those keys.
   - **Fix:** name this in D3.
   - Also, the test should build each step's schema by calling the step, not by grepping source. A source grep is Bug Class #62 (hollow anchor).
6. **MEDIUM: cross-step keys.** `CONF_ZONE` and `CONF_ROOM_TYPE` appear in both `basic_setup` and `climate`. `CONF_WET_ROOM` sits in climate. `CONF_COVER_TYPE` is in both devices and `options_covers`. `CONF_COVERS` (the entity list) lives in **devices** (always shown), not `options_covers`. The table must map each key to every step that edits it. It must also avoid letting `CONF_ROOM_TYPE`/`CONF_ZONE` (always set) mark climate as in use. Otherwise climate reveals on every room.
7. **MEDIUM: Covers for garage is a hazard, not a convenience.** Room cover behavior (`options_covers`: sunrise open mode, `CONF_TIMED_CLOSE_ENABLED`, `CONF_EXIT_COVER_ACTION`) has no garage-door exclusion in room automation. Only `hvac_covers.py:795-800` excludes `device_class == garage`.
   - **Recommendation:** hide `options_covers` for **garage** as well as utility/infrastructure. The in-use rule plus "More settings…" still reach it.
   - Closet and hallway: showing Covers is fine (it is a false-show, which is cheap).
   - Separately card a garage-door guard in room cover automation. That is pre-existing and outside this plan.
8. **LOW: the invariant as written is unfalsifiable.** Clause (c) means "More settings…" is always offered whenever anything is trimmed, so nothing is ever unreachable. The real, testable invariant is the "Equivalently…" sentence: a step with in-use values is visible in the default menu. State only that sentence.
9. **LOW: D5 has no work to do.** `CONF_ROOM_TYPE` is edited in `basic_setup` (`:10582`) and in climate. Saving ends the flow via `async_create_entry`, and the next open re-renders init. Keep the test but drop the deliverable wording.
   - Type change bathroom→closet: stored `wet_room=True` and spike=True now differ from the closet defaults, so climate reveals (safe direction).
   - The opposite direction, a value that equals the new type's default and hides, only hides values that are effectively the default, so it is benign. Fine as long as Finding 2's type-aware default is used consistently.
10. **LOW: the one-shot flag is unnecessary.** Each options open is a fresh `OptionsFlow` instance, and HA menus have no back-navigation. `show_all_settings` can just `return self.async_show_menu(step_id="init", menu_options=list(ALL))`. That removes the flag lifecycle.
11. **LOW: coordination with the lighting branch.** `feature/room-lighting-roles` (slices A+B) touches no `config_flow.py` yet. Slices B'/C/D will reshape the Lighting step and likely move `CONF_LIGHTS`/`CONF_NIGHT_LIGHTS` out of devices. Keep the plan's order: Lighting first, then populate `_STEP_CONF_KEYS` from the landed schema. The Finding 5 consistency test is what catches drift. Lighting is visible for every type, so there is no hide risk.
12. **LOW: menu completeness.** Twelve steps is correct (`config_flow.py:3528-3544`). The sub-steps (`chain_*` `:12213-12231`, `ai_rule_add/list/delete` `:12310-12476`) sit under their parents and store `CONF_AUTOMATION_CHAINS` / `CONF_AI_RULES`. Include those in the parents' key sets. `automation_behavior`, `night_light_detail` and `cover_behavior` are ConfigFlow-only and not in the options menu. Zone steps are ZM-entry only. Nothing is missed.

## Knobs / AC / non-goals
- The `ROOM_MENU_STEPS_BY_TYPE` rung-1 module constant is appropriate.
- The ACs discriminate once D4 is removed.
- Add an AC for a legacy room with `data`-only values (Finding 1) and for `room_fan_mode`-only rooms (Finding 3).
- The non-goals are fine.

## Must-fix before build
1, 2, 4, 6 (plus decide 3 and 7).
