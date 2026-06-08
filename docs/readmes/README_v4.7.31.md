# v4.7.31 — Resolve HVAC zones by NAME (Bug Class #53)

**Tier:** 1 hotfix, with a context-wide caller review (operator-requested; zone code
is critical path). Review: `docs/reviews/code-review/v4.7.31_zone_name_resolution.md`.
**Baseline tag:** `pre-review-v4.7.31`.

## What changed
`ZoneManager.zones` (hvac_zones.py) is keyed by `zone_id` ("zone_1/2/3", derived
from the thermostat entity), but zone aggregators address zones by their house-zone
NAME (`self.zone`). The v4.7.13 SLEEP and v4.7.15 non-sleep motionless-occupant
fallbacks did `hvac._zone_manager.zones.get(self.zone)` — a NAME lookup against an
id-keyed dict — so they **silently never matched a real HVAC zone**. The
v4.7.13/v4.7.15 "keep a room occupied when a tracked person is home and sensors are
quiet" protection was dead for every thermostat'd zone (the only symptom was a
one-shot "zone not registered in zone_manager.zones" WARN per boot).

Fix: new module-level `_resolve_hvac_zone(zone_manager, zone_key)` in
`aggregation.py` resolves by **zone_id → exact zone_name → merged-name membership**
("Entertainment + Master Suite" matches "Entertainment" or "Master Suite"). The two
fallback call sites now use it. No other call site was broken — every other
`_zone_manager.zones.get(...)` in the repo (sensor.py, hvac.py, hvac_fans.py,
hvac_override.py) already passes a zone_id.

## Why it's safe (context-wide review)
- **Truth-preserving:** `ZoneAnyoneBinarySensor.is_on` is a disjunction (Layer 1 OR
  sleep-fallback OR non-sleep-fallback). The fallbacks can only return True, never
  force a True down to False → a room can never be wrongly marked empty.
- **Stuck-occupied bounded:** the veto only holds while `house_state` is in the
  allow-list AND a tracked person is literally `home` AND sensors quiet ≥300s. It
  releases when the person leaves home or the house exits the allow-list (v4.7.14
  away-veto guarantees the exit). HVAC preset is state-driven, not latching.
- No other broken-by-name lookups exist in the repo.

## Acceptance criteria
### In-suite (proven pre-deploy)
- **Test:** `test_zone_name_resolution.py` (9) — drives the real extracted resolver;
  `test_proves_old_lookup_was_broken` fails if the fix is reverted.
- **Test:** `test_v4713_sleep_state_zone_presence_trust.py` — harness updated to also
  extract `_resolve_hvac_zone` (the regression the baseline-diff caught: the AST
  extraction didn't include the new helper → NameError → false). Now passes.
- **Suite:** baseline-diff vs `pre-review-v4.7.31` = zero new failures.

### Live Validation (prospective — write back post-restart)
- **Live:** after restart, the "zone not registered in zone_manager.zones" WARN
  stops appearing for the 3 thermostat'd zones (Entertainment/Master Suite→zone_1,
  Upstairs→zone_2, Back Hallway→zone_3).
- **Live:** within ~24h, an INFO indicating the sleep or non-sleep person-fallback
  engaged on Entertainment/Master Suite or Upstairs (the demographic it protects).
- **Live:** the back_hallway `counter.back_hallway_garage_entries` now loads (this
  restart picks up the package counter that had no reload target in v4.7.30's fix).

## Notes / deferred (from review)
- **LOW-1:** resolver iterates all zones per `is_on` read — trivial at 3 zones; add a
  name→id memo in ZoneManager if zone count ever grows.
- **LOW-2 (husk):** the operator-disabled husk zone "Entertainment + Master Suite"
  resolves (correctly) to zone_1, so two aggregators point at zone_1; preset calls
  are idempotent (`HVAC_PRESET_SKIP` + `_last_zone_occupied` cache) → no actuation
  harm. The husk is inert (entities disabled; warning silenced by this fix).
- SPAN baseline prune (`Unmapped Tab%`) intentionally NOT in this cycle — separate.
