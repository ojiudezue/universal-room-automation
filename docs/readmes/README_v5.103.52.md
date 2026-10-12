# URA v5.103.52 — Night lights go red on return at sleep; plain-English room sensors form

Cards: NIGHTLIGHT-RED-RECONCILE-PARITY-1, SENSOR-FORM-PLAIN-TEXT-1. Tier 1 each (one review each, findings fixed and drilled). Full-suite name-diff: 0 new vs pre-cycle baseline (132 = 132 failing names; an 11-test regression from the form change was caught by the name-diff and fixed before ship).

## 1. Night-light red parity (NIGHTLIGHT-RED-RECONCILE-PARITY-1)
**Problem:** when a night light came back online (or was corrected by the reconciler) while the house was asleep, it was re-sent with the normal colour instead of sleep red — the red-at-sleep decision lived only in the canonical turn-on path.
**Fix:** the red-hue decision moved into the shared resolver, so the reconcile-on-return path (including the reconciler's house-sleep branch and rooms mixing canonical/reconciled lights) sends red at sleep exactly like the canonical path.

## 2. Room sensors form in plain English (SENSOR-FORM-PLAIN-TEXT-1)
**Problem:** the sensors step used internal wording and exposed a raw JSON capability field to everyone.
**Fix:** short user-focused labels, one plain question per added sensor ("What can it see?"), and the raw JSON field moved to Advanced only (with the standard Advanced hint on the step).

## Not built / deferred
None from either card.

## Validated 2026-10-11 (restart 19:36 CDT)
| Criterion | Result | Evidence |
|---|---|---|
| Installed + running | PASS | `update.universal_room_automation_update` installed_version v5.103.52 (since 19:36:02); manifest on disk v5.103.52 |
| Boot: 0 URA errors | PASS | `ha core logs` grep universal_room + error/traceback = 0 |
| Sensors form plain text + Advanced-only JSON | PASS (installed code) | live `translations/en.json` carries `{advanced_hint}`; live `config_flow.py:3803` registers `sensor_capabilities_json` as Advanced-only; "What can it see?" label present. Rendering proven in-suite (test_sensor_form_plain_text 9/9, test_room_advanced_fields 56/56) |
| Night light returns red at sleep | PENDING (organic) | needs a sleep-period light return; one-shot check of a night light's `hs_color`/`rgb_color` after the next return during sleep. Proven in-suite (reconciler house-sleep branch + mixed-room batching tests) |
