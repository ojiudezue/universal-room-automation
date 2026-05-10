# v4.5.11.1 — Fix zone_id naming mismatch (per-zone Number sliders + buttons)

**Date:** 2026-05-10
**Type:** Tier 1 hotfix (~25 LoC fix + 9 regression tests)
**Predecessor:** v4.5.11
**Reproducer:** v4.5.11 post-restart inspection of `sensor.ura_hvac_coordinator_mode` attributes showed `vacancy_override_zones: ["zone_3"]`, confirming ZoneManager uses `zone_N` zone_ids. Slice-1 `_discover_ac_zones` in `number.py` + `button.py` derived zone_id differently: `thermostat.replace("climate.", "").replace(".", "_")` → e.g. `back_hallway_zone_3`. The two schemes don't match.

## Summary

Per-zone kWh Rate Threshold sliders, Force AC Nudge buttons, Cancel AC Nudge buttons, and Clear AC Ramp Lockout buttons all referenced ZoneState via a locally-derived `zone_id`. The actual ZoneState dict on `ZoneManager.zones` is keyed by ZoneManager's `_zone_id_from_thermostat` output (extracts `zone_N` from the climate entity), not the sanitized full entity name.

Net effect on v4.5.11 live: all per-zone slider value changes silently no-op'd (push to `ZoneState.kwh_rate_threshold` looked up the wrong key, returned None, exited the push). All three buttons silently no-op'd (arrester methods couldn't find the zone). Detection still worked (uses `ZoneManager.zones.items()` directly — no local zone_id). Hard-reset escalation still worked. Master switch still worked.

User-visible impact: thresholds couldn't be tuned per-zone; manual buttons were inert.

## Fix

Two-part fix preserving public API:

1. **`OverrideArrester._resolve_zone(zone_id_or_entity)`** — accepts either a zone_id or a climate_entity. First tries dict lookup; falls through to a linear scan matching `zone.climate_entity`. Public methods (`force_nudge`, `cancel_nudge`, `clear_zone_lockout`) call it and canonicalize via `zone_id = zone.zone_id` for downstream DB writes.

2. **Per-zone factory + button** — store `climate_entity` alongside the locally-derived `zone_id`. Pass `climate_entity` (stable, unique) to arrester methods. Number factory's `_get_zone()` iterates `zm.zones.values()` matching by `climate_entity`.

Both fixes are surgical — no public API change, no DB schema change, no entity unique_id change (preserves user dashboards).

```python
# OverrideArrester (new helper)
def _resolve_zone(self, zone_id_or_entity: str):
    zone = self._zone_manager.zones.get(zone_id_or_entity)
    if zone is not None:
        return zone
    for z in self._zone_manager.zones.values():
        if z.climate_entity == zone_id_or_entity:
            return z
    return None
```

## Regression test

New test class `TestZoneResolutionAcrossSchemes` (9 tests) in
`quality/tests/test_v4511_ac_energy_aware_ramp_down.py`:

- `test_arrester_has_resolve_zone_helper` — helper exists
- `test_resolve_zone_falls_through_to_climate_entity_match` — fallback path present
- `test_force_nudge_uses_resolve_zone` — and canonicalizes zone_id
- `test_cancel_nudge_uses_resolve_zone` — and canonicalizes
- `test_clear_zone_lockout_uses_resolve_zone` — uses _resolve_zone
- `test_number_factory_stores_climate_entity` — and the runtime lookup uses it
- `test_button_factory_passes_climate_entity` — through `_make_ac_ramp_button`
- `test_button_init_stores_climate_entity` — stored on instance
- `test_button_press_passes_climate_entity_not_zone_id` — runtime call path

These directly assert the resolution chain so a future cycle that re-introduces local-zone_id-only lookups will fail at test time.

**Test count progression:**
- v4.5.11: 139 tests
- **v4.5.11.1: 148** (+9 regression tests), 0 isolated failures

## Lesson

Slice-1 review surfaced two QUALITY_CONTEXT bug classes (#11 TZ mismatch, #33 partial fix). This bug is essentially Bug Class #22 (Enum Value Mismatch / convention drift) but for IDENTIFIERS rather than enums — two parts of the code using different IDs for the same thing.

Source-grep tests confirmed every symbol was correctly imported and every CONF was correctly defined, but didn't check that the IDs used to look up ZoneState at runtime matched the IDs ZoneManager actually assigns. Runtime behavior — even structural runtime behavior — is invisible to grep-based tests.

**Add to review checklist:** when multiple modules derive a shared identifier independently, source-grep the derivation logic in each, OR force one canonical derivation (e.g., import the same helper everywhere).

## Deploy notes

- No DB schema changes
- No migration
- No unique_id changes (dashboards safe)
- HACS download required after deploy.sh
- HA restart required (3 production files touched)
