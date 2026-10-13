# URA v5.103.55 — Energy settings name roles, not brands; no house-specific entity defaults in code

Card: EC-HOUSE-ENTITY-DEFAULTS-1. Plan: docs/planning/PLANNING_ec_house_entity_defaults.md (Rev 5, simplified). Reviews: plan reviews ×3 (Rev 1–4 → Rev 5 simplification), build reviews A (correctness), B (migration/lifecycle), C (test authority, per-site mutation), D (adversarial completeness), all findings fixed and drilled. Full suite: 0 new failures from production code (24 new-file tests made order-independent; 35/35 pass in any order).

## Why
URA's energy code shipped this house's entity IDs as built-in defaults (EV chargers, Enpower battery controls, SPAN mains, smart plugs, Envoy serial, weather, generator, pool). A second home would silently target entities that don't exist (missing reads look like "off"/0 W, so control quietly does nothing), and a rename here (the SPAN Garage A circuit) silently broke a control path.

## What changed
- **No house-specific entity IDs in code.** Defaults are gone. Each former default is now a role-named setting (e.g. "Charger A switch", "Mains power reading 1", "Battery reserve control"). On upgrade, this house's current values are copied into its settings once — only for entities HA's registry knows, whatever their state — so behaviour here is unchanged. A test enforces that no house literal exists outside the one-time copy table.
- **Role-worded labels, any equipment.** Field labels and help text name the role, not the brand; fields accept any entity of the right type (unit checks on save). Two sensors keep their entity IDs (dashboards/PWA depend on them) but are renamed for display: "Battery gateway status", "Battery gateway online".
- **Entity-mapping edits take effect on save.** Changing which entity a role uses now reloads URA once (value comparison: change-and-revert or an unchanged save does nothing). Behaviour settings that already applied live still do, with no reload.
- **Missing entities are visible.** An hourly check (starting after HA has fully started, two failed checks in a row) raises a Repairs issue naming a configured-but-missing energy entity; clears on recovery or when the setting is removed.
- **Homes without the equipment:** no write goes out without a target (battery mode, reserve, grid charging, charger hold, pool).

## Behaviour changes on this house (intended)
- `binary_sensor` "L1 charger active" now reads the 2 configured garage plug sockets; sockets 3–4 are USB ports and no longer count.
- The optimizer's battery-write safety veto now covers the Enpower controls (their settings were previously blank, so it didn't apply).
- Pool entities are not in this house's registry, so nothing is copied; pool control stays inactive (as before).

## Not built / deferred
- Renaming the internal setting keys (users never see them) — parked; Phase 2 brand adapter (Envoy serial anchor etc.) — separate Tier-3 plan.
- Clearing an energy entity field doesn't remove the setting — pre-existing, card EC-OPTIONS-CLEAR-FIELD-NOOP-1.

## Rollback
Setting keys are unchanged and the copied values equal the old defaults, so v5.103.54 reads the same values.

## Live validation (prospective)
- Boot: 0 URA errors.
- Options for the CM entry gain the pinned role keys with the exact old default values; `_ec_defaults_pinned` set; no CM/parent reload at boot.
- Battery reserve/storage-mode/charge-from-grid writes still target the Enpower entities; EVSE A/B pause/resume entities unchanged.
- No new Repairs issue for energy entities after start + 2 scans (unless an entity is genuinely missing).
