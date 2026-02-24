# Post-Mortem: v3.4.0 — Camera Census (Config/Tooling Issues)

**Date:** 2026-02-24
**Versions affected:** v3.4.0 through v3.4.4
**Impact:** UI showed raw config keys; strings fix committed locally but never shipped; wrong entity selector exposed irrelevant sensors to users
**Class:** Config/tooling — not an architectural failure

---

## What Shipped in v3.4.0

- Camera platform discovery for Frigate and UniFi Protect
- Dual-zone person census: house (interior) + property (exterior)
- Three-tier camera config: room-level (`camera_person_entities`), integration-level egress cameras (`egress_cameras`), integration-level perimeter cameras (`perimeter_cameras`)
- 8 census sensors enabled, 4 disabled by default
- Cross-validation between platforms with confidence scoring

---

## What Broke (v3.4.1 – v3.4.4)

| Version | Issue | User Impact |
|---------|-------|-------------|
| v3.4.1 | `strings.json` not updated for any new camera config fields | Users saw raw keys (`camera_person_entities`, `egress_cameras`, `perimeter_cameras`) instead of labels in the config UI |
| v3.4.1 | `translations/en.json` did not exist — directory never created | HA failed to render config flow UI for camera-related fields at runtime |
| v3.4.2 | `deploy.sh` only staged `*.py` and `manifest.json` — missed `strings.json`, `translations/`, and `quality/tests/` | The v3.4.1 strings fix was committed locally but never actually deployed to HA |
| v3.4.3 | strings.json + translations/en.json fix finally staged and shipped, deploy.sh updated | Resolved |
| v3.4.4 | Camera entity selector used `domain="binary_sensor"` — showed every binary_sensor on the camera device (motion, animal, bark, doorbell) instead of just person detection | Users could not identify the correct sensor; selection required guesswork |

---

## Root Causes

1. **No strings.json validation step.** There was no checklist item requiring `strings.json` to be updated when adding config flow fields. The omission was invisible until a user opened the config UI.

2. **No translations folder check.** HA requires `translations/en.json` for runtime UI rendering, but there was no checklist item to verify the directory and file exist. The directory was simply never created.

3. **deploy.sh hardcoded file patterns.** The deploy script staged `*.py` and `manifest.json` only. Adding new file types to the integration (JSON, translations, tests) silently fell outside the staging scope. No warning, no error — just a missing file in production.

4. **Wrong entity selector domain.** The planning doc specified `domain="binary_sensor"` for `camera_person_entities`. That reflects camera-adjacent entities (person detection sensors), but using it in the selector exposes all binary sensors on the device. The correct approach is to select by `domain="camera"` and resolve the person detection entity in code via the device registry.

---

## Fix Sequence

- **v3.4.1:** Added strings.json entries + created translations/en.json — but deploy.sh didn't stage them.
- **v3.4.2:** Attempted re-deploy; discovered deploy.sh staging gap. Updated deploy.sh to include `*.json`, `translations/`, and `quality/tests/`.
- **v3.4.3:** Strings + translations shipped for real. UI labels now correct.
- **v3.4.4:** Switched `camera_person_entities` selector to `domain="camera"`. Added device-registry-based person detection resolution. Added cross-validation toggle.

---

## Prevention

- `CONFIG_FLOW_VALIDATION_CHECKLIST.md` updated with: strings.json + translations/en.json requirements for every new config field, and camera entity selector domain rule.
- `DEVELOPMENT_CHECKLIST.md` Phase 7 updated with: deploy.sh staging check, strings/translations sync step, mandatory quality test run before commit.

---

**Status:** Closed — all issues resolved in v3.4.4
**Follow-up:** None required. Monitor v3.4.4 for stable operation.
