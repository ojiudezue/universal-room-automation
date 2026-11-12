# v5.108.9: Simpler forms: collapsed Advanced sections and plain-language text

Cards: `FORM-CONDITIONAL-FIELDS-1` (release 1 of 2), `FORM-TEXT-PLAIN-PASS-1`, `PRESENCE-GEOFENCE-FIELD-DEAD-1`, `CLIMATE-BACKSTOP-SECTION-CLEAR-ON-ABSENT-1`. First URA release installed through the HA Marketplace (`HACS-MARKETPLACE-DEPLOY-1`).

## 1. Advanced mode replaced by collapsed sections

**Why:** HA 2026.10 forces `show_advanced_options` on and removes it in 2027.6, so every Advanced field was already showing on every form. Rarely used tuning now sits in a collapsed **Advanced** section per step (62 fields, 16 steps). Fields URA pre-fills by guessing from the room's devices (presence radar, door, water leak, auto switches, humidity fans) stay on the first screen so a lost guess cannot silently drop leak alerts.

**Save integrity:** sections arrive nested; every step flattens them before reading, so stored options keep their flat keys and no runtime reader changed. A save without opening a section keeps every stored value. Steps that clear a value when its field is missing (room sensors capability JSON, lighting evening/scene keys, climate backstop holds) clear only when that section was actually submitted. A save that only moves fields causes no reload. The House form now always shows the energy screen, and fills the notify service from the chosen phone only when the field is blank.

Behaviour change: an Options save with a section never opened no longer writes defaults for keys that were never stored.

## 2. Plain form text (operator-signed table)

41 fields that showed raw keys now have labels; descriptions rewritten to say what the setting does and when to change it, each checked against the code that reads it; 8 wrong descriptions corrected; 24 dead strings removed. Energy coordinator wording is deferred to its own pass (money path). Table: `docs/planning/AUDIT_form_text_plain_pass.md`.

## 3. Presence

- "Geofence device trackers" field removed: it was never read. Arrivals come from each `person.*` entity (trackers set in Settings > People, compared with the Home zone).
- People added to HA after startup are now followed without a restart. Adding a person is never treated as an arrival (`old_state is None` guard), so it cannot release the garage lockout.

## Reviews

Plan: `config_forms_AB_plan_review_rev3.md` (FIX-PLAN, all fixed in rev 4). Build (Tier 2-DB): A save integrity SHIP (`forms_release1_review_A.md`), B lifecycle/reload SHIP (`_B.md`), C mutation (`_C.md`): ~30 sites RED; two hollow merge anchors found and fixed. Fix-up also made the new test file order-proof (donor `test_census_device_switches.py` leaked a dispatcher patch).

## Not done

- Release 2 (`visible=` fields shown only when relevant, `hacs.json` HA floor) waits for a pytest-homeassistant-custom-component release pinned to HA 2026.11 (latest pins 2026.10.4; a hand-built 2026.11.1 venv fails at startup).
- Energy wording pass.

## Validated 2026-11-11 (installed as part of v5.108.10, restart 19:24 CST)

| Criterion | Result | Evidence |
|---|---|---|
| Installed through the Marketplace | PASS (as v5.108.10) | Marketplace never offered v5.108.9; operator installed v5.108.10, which contains it |
| No URA ERROR after restart; house state back | PASS | system_log URA entries WARNING only; `sensor.ura_coordinator_manager_house_state` = home_evening, confidence 0.9 |
| Room options: Advanced collapsed, plain labels | PASS | options flow API on Study A, Sensors step: `advanced` expandable section holding `sensor_capabilities_json`; auto-filled fields (presence, door, water leak) on first screen; installed en.json has 0 blank labels ("Advanced (rarely change)", "Sensor types (advanced)") |
| Presence options: no geofence field | PASS | Coordinator Manager > coordinator_presence schema has no geofence field; fan re-check tuning in its own collapsed section |
| Save without edits leaves options unchanged, no reload | PASS (operator-approved live save) | 2026-11-12 01:32Z: Study A > Sensors submitted with its current values, Advanced section not opened -> `create_entry`; stored options byte-identical before/after; entry stayed `loaded`; `binary_sensor.study_a_occupied` had no state change (no unavailable blip) in the following 20 s |

Inspection flows were aborted (HTTP 200); the one save was the approved no-change test above.
