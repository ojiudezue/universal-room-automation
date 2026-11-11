# FORMS-RELEASE-1 — Review B (integration, lifecycle, reload, runtime readers)

- Branch `feature/forms-release-1`, head `7bb3a5b4`. Base verified: `git merge-base 14147e1a 7bb3a5b4` = `14147e1a`; diff read three-dot.
- Spec: `docs/planning/PLANNING_config_forms_sections_and_conditional_fields.md` rev 4 (§2 INV-P, §3).
- Read in full before judging presence: `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` and `docs/architecture/SENSOR_FLEET_CLASSES.md`. No §10 ledger claim is re-asserted here. The doc's new geofence note (line 5) matches the code, with one exception (B-L1 below).
- Pytest was not run, as instructed. Every finding is from static reading of the branch and of HA 2026.11.1 source in `.venv-ha-2611`.

## Findings

| # | Sev | Where | Finding |
|---|---|---|---|
| B-L1 | LOW | `domain_coordinators/presence.py` `_handle_person_added` → `_track_geofence_persons`; `_handle_geofence_change` (`old_zone = old_state.state if old_state else None`) | **Whether the add event counts as an arrival depends on listener order.** The per-entity state-change callback is registered *while* the `state_changed` event that added the person is being dispatched. In HA 2026.11 `Bus._async_dispatch` iterates a snapshot of the bus listeners (`core.py` ~1712). The keyed `_KEYED_TRACK_STATE_CHANGE` dispatcher reads its `callbacks` dict live when its own turn comes (`helpers/event.py` 224-232). So if that dispatcher's bus listener sits *after* the `_KEYED_TRACK_STATE_ADDED_DOMAIN` listener, the new callback receives the add event itself, with `old_state=None`. A person added with state `home` then runs `handle_geofence_event` and dispatches `SIGNAL_PERSON_ARRIVING(source=geofence)`, which contradicts the docstring and the state-of-play note ("the add itself is not a transition"). `zone` registers an added-domain tracker during early bootstrap (`components/zone/__init__.py:309`), so in the live house that order is plausible. I did not prove it. The unit test passes either way: in a bare `hass` the state-change bus listener is created during the dispatch, so it is excluded from the snapshot. The test therefore does not pin this. **Reach:** only a person created at runtime whose first state is `home` (a new person with trackers already home). Presence setup defers to HA started (`presence.py` ~2733), so the boot late-load case is effectively unreachable. **Consumer at risk:** the SC lock regime counts geofence arrivals inside its no-real-transition / boot exceptions (state of play §1), so one spurious garage-lockout release is possible. **Fix (1 line):** in `_handle_geofence_change`, `if old_state is None: return`. Any `old_state=None` event is an add or restore, and both are non-transitions by the doc's doctrine. Then add a test that registers a state-change tracker before `_subscribe_geofence`. |

No CRITICAL, HIGH or MEDIUM findings.

## Cleared (holds because …)

- **INV-P (i): a move-only save causes zero reloads.** Every Options step that holds an `advanced` section flattens before anything reads the input. An AST scan found 16 handlers. Ten rebind `user_input` and six use `flat`; in each of the six, the only later `user_input` reference is the flatten call itself. All merge shapes are `{**options, **flat}`, and no Options path calls `_absent_field_defaults`: its only caller is create `integration_config`, `config_flow.py:1565`. HA 2026.11 `_async_update_entry` returns early `if not changed` (`config_entries.py:2858`) before it reaches `update_listeners` (`:2877`), so equal options means the listener never runs. No section-named key can reach options: `_flatten_sections` drops the section keys (`config_flow.py:96`). `zone_dynamic_preset` additionally filters dict values out (`:11730`).
- **INV-P (ii): live-apply keys stay live.** `_ROOM_SUPPRESS_KEYS` (`__init__.py:8518`), `OPTIONS_RELOAD_SUPPRESS_KEYS` (`:7525`) and `INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS` (`:7732`) are untouched; the diff touches `__init__.py` by one import line only. A moved key arrives flat, so the changed-key set is the same as before the move.
- **Clear-on-absent.** `sensors` seeds the stored JSON when the section is absent (`config_flow.py:12675-12686`). `options_lighting_behaviour` extends its clearable list only `if ADVANCED_SECTION in _present` (`:13893`). The existing nested sections (`fan_recheck_advanced`, `humidity_fan_advanced`, `climate_backstop`, `auto_manual_devices`, `reconcile_advanced`, inclement) are not passed to `_flatten_sections`, which is always called with the explicit `(ADVANCED_SECTION,)` tuple, so their handlers are unchanged.
- **Runtime readers of moved keys.** I AST-extracted the 59 keys inside `_advanced_section(...)` and grepped `[KEY]` subscript reads package-wide, excluding `config_flow.py`. There were zero non-assignment hits, so every reader uses `.get`. A never-stored key in an unexpanded section stays unstored and reads its `.get` default, which is the same runtime value.
- **Pre-change stored entries.** Merge shapes keep every stored key. Section inner markers keep the same `default=` / `suggested_value` sources as the old top-level markers, so prefill inside sections is unchanged. Section serialization (`config_validation.py:1164-1176`) is the same path that the live `fan_recheck_advanced` / `climate_backstop` sections already use on 2026.11.1. No `visible=` ships in release 1, so `_strip_hidden_fields` (`data_entry_flow.py:1032`) is inert.
- **2026.11 behaviour.** `show_advanced_options` always returns True until 2027.6 (`data_entry_flow.py:714-720`). The house already rendered every Advanced field, so the frontend submits the same values as before. Whether the frontend sends a never-expanded collapsed section is UNVERIFIED (no frontend source in the venv). Both answers are safe: present means the same as today, and absent means the stored values are kept by the merge plus the two `_present` gates.
- **Geofence field removal.** `async_step_coordinator_presence` merges (`{**options, **user_input}`, `config_flow.py:5448-5451`), so a stored `geofence_entities` is kept, unread, and not counted as a changed key. The only remaining reference is `const.py:3644`. Strings and en.json carry no `geofence_entities` on `coordinator_presence`.
- **Late-person listener lifecycle.** Both the added-domain unsub and each per-batch state-change unsub are appended to `_unsub_listeners`, which `_cancel_listeners` clears at teardown (`base.py:294-299`). `_geofence_tracked` dedups both the setup batch and later adds, so there are no duplicate subscriptions. `async_setup` runs once per coordinator; a reload builds a fresh object, and `_geofence_tracked` is reset in `_subscribe_geofence`. The event-loop cost is one `@callback` filter on `person` domain adds only.
- **Render cost.** Removing `_filter_advanced`, `advanced_hint_for` and the filter-only `add_suggested_values_to_schema` calls cuts per-render work. Sections are static schema, and `_flatten_sections` runs on submit only. No new registry or state scans were added.
- **Strings.** Every step that contains `vol.Optional(ADVANCED_SECTION)` has `sections.advanced` in both `strings.json` and `translations/en.json` (scripted check, including `integration_config` and `zone_dynamic_preset`).

## Note outside lane (for C)

`test_presence_geofence_late_person.py::test_person_added_after_setup_is_tracked` cannot fail on the B-L1 ordering, because no keyed state-change tracker exists before the add.

## Verdict

**SHIP.** B-L1 is LOW and recommended in-cycle (one guard plus one test, per "fix LOWs in-cycle"). INV-P (i)-(iii) hold on static evidence.

| Severity | Found | Fixed |
|---|---|---|
| CRITICAL | 0 | — |
| HIGH | 0 | — |
| MEDIUM | 0 | — |
| LOW | 1 | pending |

Bug class: B-L1 = listener-registration-during-dispatch, a restore/add edge read as a transition (sibling of the boot-restore-edge doctrine, state of play §8). It is a candidate for QUALITY_CONTEXT if it recurs.
