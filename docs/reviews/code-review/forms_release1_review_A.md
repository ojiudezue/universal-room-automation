# Forms release 1 — Review A (local correctness + save integrity)

Branch `feature/forms-release-1`, base `14147e1a` (verified = merge-base of `14147e1a` and `7bb3a5b4`), head `7bb3a5b4`, three-dot diff. Spec: `PLANNING_config_forms_sections_and_conditional_fields.md` rev 4 (release 1 = D2 + D3), plan review `config_forms_AB_plan_review_rev3.md`, text spec `AUDIT_form_text_plain_pass.md` rev 2. Read-only review; pytest NOT run (suite run in progress elsewhere). Because the branch touches `presence.py`, `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` and `SENSOR_FLEET_CLASSES.md` were read in full; no corrections-ledger claim is re-asserted here.

**Verdict: SHIP-with-ack.** No CRITICAL or HIGH. One MEDIUM needs an operator acknowledgement or a split (scope, not correctness). Two LOWs are cheap fix-ups.

## Per-step save integrity

The flatten line comes first on every step. `_flatten_sections` (`config_flow.py:84-109`) pops the section and merges its fields up, and it does not mutate the caller's dict. `_absent_field_defaults` (`:112-130`) is create-only and reads marker `default=` only.

| Step | Shape | Flatten site | Section sent, no edit | Section omitted | Clear semantics |
|---|---|---|---|---|---|
| integration_config (create) | 3 | `:1564-1565` | flat values win | case (a) backfill fills retention, window, rate and level defaults; the 3 sensors and the service have no default, so nothing is stored (same as the old hidden backfill) | a field cleared inside a sent section is not refilled (the backfill skips a present section, `:125`) |
| global_sensors | 1 | `:4627` | merge | merge keeps stored | unchanged |
| energy_sensors | 1 | `:4718` | merge | keeps | unchanged |
| person_tracking | 1 | `:4809` | merge | keeps | unchanged |
| camera_census | 1 (`cleaned`) | `:4921` | merge after the existing empty-value pops | keeps | pre-existing pops unchanged (a cleared main entry door still cannot be cleared; pre-existing) |
| perimeter_alerting | 1 + strip | `:5210` | merge, then strips 4 retired keys | keeps | unchanged |
| zone_rooms | 4 | `:10981` (before any read; error re-render rebuilds the section, `:11002`) | description from flat | `.get(desc, current_zone_desc)` keeps it | unchanged |
| zone_media | 4 / legacy 1 | `:11260` | mirror helper / merge | keeps | unchanged |
| zone_hvac | 4 / legacy 1 | `:11364` (before `_auto_mirror_to_siblings`) | 3 moved mirror keys reach siblings (`mirror_payload` = keys in BOTH saved data and `MIRROR_KEYS_ZONE_HVAC`) | keys absent, so not mirrored (see L2) | unchanged |
| zone_energy | 4 / legacy 1 | `:11484` | `zone_power_sensors` mirrored | same as zone_hvac | unchanged |
| zone_dynamic_preset | 4 | `:11729`; non-dict filter runs after the flatten | reset-guest + sleep mirrored | not mirrored | unchanged |
| sensors (H2) | 1 + clear-on-absent | `:12672-12686` | JSON from the section | stored caps seeded as `json.dumps(indent=2, sort_keys=True)` before the dropdown pass (`:12676-12686`), so `trust_class` / `failure_mode` survive and dropdowns apply on top | cleared JSON with the section sent → `merged.pop(CONF_SENSOR_CAPABILITIES)` (`:13039-13042`) |
| devices | 1 | `:13540` | merge | keeps | unchanged |
| options_lighting_behaviour (H2) | 1 + clearables | `:13837`, before `_cur` | merge | the 7 evening/scene keys are added to `clearable` only when `ADVANCED_SECTION in _present` (`:13893`) | sent section with a key missing → popped; `CONF_LIGHT_DARK_LUX_SOURCE` keeps top-level behaviour |
| options_covers | 1 | `:14135` | merge | keeps | unchanged |
| climate | 1 + 2 existing sections | `:14271`, before the `humidity_fan_advanced` / `climate_backstop` pops | merge | keeps, but see L1 (validation) | the vacancy-hold clearables are unchanged; climate_backstop clear-on-absent is pre-existing (carded CLIMATE-BACKSTOP-SECTION-CLEAR-ON-ABSENT-1) |

H2 (both clear-on-absent sites): PASS as specified. H3 row 69: `if not show_adv: … energy_setup(user_input={})` is deleted, and the step always returns `async_step_energy_setup()` (`:1579`). H3 row 70: the fallback runs only when `not user_input.get(CONF_NOTIFY_SERVICE)` and the target is a `notify.*` string (`:1572-1575`), after the flatten and the backfill, so an entered service is never overwritten. H4: `presence_sensors`, `door_sensor`, `water_leak_sensor`, `auto_switches` and `humidity_fans` are top-level with `advanced_if_empty` removed (`:2390-2492`); no section on either confirm step. Row 68: the room_class skip is removed (`:2296`).

`show_advanced_options|_show_adv|advanced_hint|_adv(|_filter_advanced|advanced_if_empty|"advanced": True` returns 0 hits in the package.

## Strings

- `strings.json == translations/en.json`: PASS (full dict equality).
- All 16 sectioned steps carry `sections.advanced` with a `data` + `data_description` entry for every field. None of those fields is still in the step's `data` or `data_description` (scripted check over both flows). Field sets match §13 rows (camera_census 13 = rows 19-31, and so on).
- Copy-not-move: the only hits are `coordinator_optimization` sections `optimizer_guards` / `optimizer_llm`. They predate this branch (base has the same duplicate), and the builder kept both copies in sync (C22 labels in both). LOW-3, not this cycle.
- Audit verbatim check: 113 proposed label/description cells were scripted against the shipped values; 95 match exactly. The other 18 are all expected: slash-joined multi-key cells verified per key (R10, C5, C14, C21, C22, C23, Z4 all match), REUSE / delete instructions (Z1-Z3, Z5, Z6 applied: no `options.step.automation_behavior`), Z9 applied ("night clean-up" in both hour descriptions), C24 deferred by plan, and P3 (see M1). R6b / R13 key renames applied: `sensors_confirm` now has `presence_sensors` and `door_sensor`, and no `mmwave_sensors` / `door_sensors`.

## Findings

**M1 — MEDIUM — scope: a presence runtime change and a removed field ride a forms cycle.** `domain_coordinators/presence.py:5187-5256` (new `async_track_state_added_domain` listener, `_track_geofence_persons`, `_handle_person_added`), plus removal of the Presence form's `geofence_entities` field. Plan §14 says the dead `geofence_entities` is "a card, not part of this cycle". The signed audit row P3 specifies a "Phone trackers (not used)" label, not a removal. The runtime effect is real: a `person.*` that appears after setup now produces `handle_geofence_event` / `SIGNAL_PERSON_ARRIVING(source=geofence)` on its next home/not_home edge, and that signal feeds the SC lock regime's garage and away-lock RELEASE (Presence STATE_OF_PLAY §1 table). It was never reviewed under a presence/lock framing.

Local correctness holds:
- the add is deduplicated by `_geofence_tracked`;
- both unsubs go into `_unsub_listeners`;
- the add itself dispatches nothing;
- `_subscribe_geofence` has a single caller (`presence.py:3146`).

The fail direction is release (fail-safe) and it is low-reach here (person entities normally exist at setup). Required: operator acknowledgement of the scope pull-in, or a split into its own card/commit. Bug class: scope creep / unreviewed trust-adjacent path.

**L1 — LOW — climate cross-field validation is skipped when the new section is not sent.** `config_flow.py:14294` calls `_validate_climate_fans_form(user_input)` (`:917-945`), which compares `CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_CAP_S` (top level) with `CONF_HUMIDITY_FAN_MAX_RUNTIME`. The second key now sits in the `advanced` section (`:14541`). With the section omitted, `max_runtime` is None and the check is skipped.

- Repro: stored `humidity_fan_max_runtime` = 900 (legal, min 600). Submit with the section omitted and the cap set to 1800 (legal, max 3600). The save stores cap 1800 > max 900, a pair the form rejects today.
- Runtime is safe: the max-runtime force-off still fires first (`automation.py:3528-3534`).
- Fix: validate against `{**stored, **user_input}` for that pair.
- Bug class: #53-shaped (a moved key that a second reader still expects in the submit).

**L2 — LOW — zone mirror re-sync is lost on an omitted-section save.** `_auto_mirror_to_siblings` mirrors only keys present in the saved payload (`config_flow.py` `mirror_payload`). Before this change, every zone_hvac / zone_energy / zone_dynamic_preset save re-sent all fields, so it forced siblings back into sync on the moved keys. With the section omitted, a sibling that had drifted (e.g. edited before v4.7.5 mirroring) stays drifted until the section is expanded. This is a behaviour delta, not data loss. INV-1b (edit propagation) holds. Accept or note.

**L3 — LOW — pre-existing duplicate strings** for `coordinator_optimization` `optimizer_guards` / `optimizer_llm` fields (in both `data` and `sections.*.data`). This cycle introduced no new duplicate. Card or ignore.

**INFO — the builder's "7 ambiguity resolutions".** I found no list in the branch: commit messages, the plan §11 rows, the test docstrings and the state-of-play notes were all checked. The resolutions I could infer from the code, each judged correct except (3):
1. Options steps flatten by explicit name `(ADVANCED_SECTION,)`, create by schema. Equivalent, because `_flatten_sections` accepts both (`:73-81`).
2. Existing sections (`humidity_fan_advanced`, `climate_backstop`, `reconcile_advanced`, `auto_manual_devices`, optimizer, DPM `advanced` `:8377`) keep their hand flatten. OK.
3. The geofence removal. See M1.
4. zone_rooms error re-render rebuilds the section with `user_input.get(desc, current)`. OK.
5. Zone DPM keeps the non-dict filter after the flatten. OK.
6. HVAC settings `presence_timing` labels were moved into `sections.presence_timing` (they rendered raw). This is a text-only raw-key fix and matches audit intent.
7. The notify fallback also covers the "No notify services configured" `""` value. OK.

The orchestrator should send the builder's own list if one exists.

## Invariant checklist

| Invariant | Result |
|---|---|
| Flatten first on every sectioned step (16 steps) | PASS |
| INV-1a no-edit save, section sent / omitted, Options | PASS (merge keeps stored; no section key stored) |
| INV-1a create integration_config, both variants | PASS |
| INV-1b moved key lands flat; zone mirror keys reach siblings | PASS |
| Cleared-field semantics preserved (incl. v5.37.1 hazard) | PASS |
| H2 clear-on-absent only when the section was sent (sensors, lighting) | PASS |
| H3 row 69 energy step always shown / row 70 fallback never overwrites | PASS |
| H4 five confirm fields top-level | PASS |
| Strings moved not copied; en == strings; zero raw-key section fields | PASS (pre-existing optimizer duplicate, L3) |
| Signed audit text applied verbatim | PASS except P3 (field removed instead of relabelled, M1); C24 deferred by plan |

## Summary

| Severity | Found | Must-fix before ship |
|---|---|---|
| CRITICAL | 0 | — |
| HIGH | 0 | — |
| MEDIUM | 1 (M1 scope) | operator ack or split |
| LOW | 3 | L1 recommended (2-line fix) |

Bug classes: scope pull-in of an unreviewed trust-adjacent path (M1); #53-shaped moved key with a second reader (L1); behaviour delta from a partial-payload mirror (L2).
