# v4.5.9.2 — Strings for cover_hvac_managed + configurable occupied-cover-close delta

**Date:** 2026-05-10
**Type:** Tier 1 hotfix (~80 LoC + 15 regression tests; closes 2 v4.5.9 half-shipped UI bits)
**Predecessor:** v4.5.9.1
**Reproducer:** v4.5.9 audit follow-up — user opened the per-room cover form to find `cover_hvac_managed` showing as the raw key (no friendly label); separately, asked "where is OCCUPIED_CLOSE_TEMP_DELTA configured?" and the answer was "nowhere" (hardcoded module constant despite the v4.5.9 plan saying "configurable").

## Summary

Two distinct half-shipped pieces from v4.5.9, both fixed in one Tier 1 hotfix because both reduce to the same Bug Class #32 prevention rule (form field needs runtime reader; configurable threshold needs config flow surface):

1. **`CONF_COVER_HVAC_MANAGED` strings.** v4.5.9 added the form field to both setup and reconfig cover flows but forgot to add `strings.json` and `translations/en.json` entries. The toggle worked (runtime read present) but the UI showed the raw key `cover_hvac_managed` with no helper text. Pure UX bug, no behavioral change.

2. **`CONF_HVAC_OCCUPIED_COVER_CLOSE_DELTA`.** v4.5.9 hardcoded `OCCUPIED_CLOSE_TEMP_DELTA = 2.0°F` as a module constant (planning doc said "configurable, default 2.0°F" — implementation drifted). v4.5.9.2 promotes it to a CM-level config field in the `coordinator_hvac` step, threaded through `__init__.py` → `HVACCoordinator` → `CoverController` → `_should_close_for_occupied_room`.

Both changes are additive — no behavior change for users who haven't reconfigured. Defaults preserve v4.5.9 behavior.

## What changed

### Part 1 — Strings for `cover_hvac_managed`

**`strings.json`** + **`translations/en.json`** (kept in sync per CLAUDE.md):

- `config.step.cover_behavior` (setup flow) — added label "HVAC Solar-Gain Management" + helper text
- `options.step.options_covers` (reconfig flow) — same

Helper text:
> "When ON, the HVAC coordinator may close these covers during peak afternoon solar hours to reduce cooling load. Turn OFF to keep this room's covers exempt from HVAC management (e.g. master bedroom for naps, kid's room with light-sensitive sleep)."

### Part 2 — Configurable `CONF_HVAC_OCCUPIED_COVER_CLOSE_DELTA`

**`hvac_const.py`:**
```python
CONF_HVAC_OCCUPIED_COVER_CLOSE_DELTA: Final = "hvac_occupied_cover_close_delta"
DEFAULT_HVAC_OCCUPIED_COVER_CLOSE_DELTA: Final = 2.0  # °F
```

**`config_flow.py`** in the `coordinator_hvac` step (the same step that exposes Sleep Setpoint Offset, Fan Activation Threshold, etc.):
- Number slider, range 0.5–5.0°F, step 0.5, default 2.0°F
- Friendly label: "Occupied-Room Cover Close Threshold"
- Helper text: "When a room is occupied, HVAC only closes its covers for solar-gain reduction if the room temp is at least this many °F above the zone's cooling setpoint. Lower = more aggressive (closes covers sooner when occupied), higher = more conservative (lets occupied rooms get warmer before closing). Default: 2.0°F."

**`__init__.py`** reads from `cm_config` and passes to `HVACCoordinator(occupied_cover_close_delta=…)`.

**`hvac.py`** — `HVACCoordinator.__init__` accepts `occupied_cover_close_delta: float = 2.0`, forwards to `CoverController(occupied_close_delta=…)`.

**`hvac_covers.py`** — `CoverController.__init__` accepts `occupied_close_delta: float = OCCUPIED_CLOSE_TEMP_DELTA` (defaults to module constant for backward-compat), stores as `self._occupied_close_delta`, used in `_should_close_for_occupied_room` instead of the module constant.

The module constant `OCCUPIED_CLOSE_TEMP_DELTA = 2.0` stays as the fallback default — code that constructs `CoverController()` without the kwarg still works.

## Lesson learned (carry-forward from v4.5.9 / v4.5.9.1)

Three half-shipped UI bits from v4.5.9 in one cycle:
1. v4.5.9.1 — mode sensor's manual key picker missed the new diagnostic attrs from `get_cover_status()`
2. v4.5.9.2 — strings missing for `CONF_COVER_HVAC_MANAGED`
3. v4.5.9.2 — `OCCUPIED_CLOSE_TEMP_DELTA` hardcoded vs planning doc's "configurable"

All three slipped past the v4.5.9 Tier 2 review because both reviews focused on the controller's own logic, not the cross-coordinator surfacing path or the planning-doc-vs-implementation alignment. **Adding to the review checklist for future cycles:**

- "Data shape changes → grep every selective consumer for an updated pick list"
- "Planning doc says 'configurable' → must have a CONF + form field + reader"
- "New CONF added to form → must have strings.json + translations/en.json labels in BOTH setup and reconfig flows"

Documented in QUALITY_CONTEXT.md as Bug Class #32 prevention checklist update (forthcoming in v4.5.10).

## Tests

15 new tests in `quality/tests/test_v4592_strings_and_delta.py`:

- **Strings (6):** `cover_hvac_managed` label + helper present in both `cover_behavior` (setup) AND `options_covers` (reconfig) steps; mirrored in `translations/en.json`
- **CONF wiring end-to-end (7):** const defined; form field in coordinator_hvac step; `__init__.py` reads + passes; `HVACCoordinator` accepts kwarg + forwards; `CoverController` stores + uses; strings present
- **Backward-compat (2):** default value still 2.0°F; module constant `OCCUPIED_CLOSE_TEMP_DELTA` still exists as constructor default

**Test count progression:**
- v4.5.9.1: 2055, 0 isolated failures across 57 files
- **v4.5.9.2: 2070** (+15), 0 isolated failures across 58 files

## Live validation (post-restart)

1. Open any room with covers in Settings → Devices & Services → URA → Configure → Cover Automation step. Verify "HVAC Solar-Gain Management" toggle appears with the helper text (not raw `cover_hvac_managed`).
2. Open Coordinator Manager → HVAC config step. Verify "Occupied-Room Cover Close Threshold" slider appears (range 0.5–5.0°F, default 2.0°F).
3. Adjust the slider to 1.0°F, save, reload the integration. The next solar-window close decision should use 1.0°F (more aggressive — closes covers in occupied rooms sooner).

## Deploy notes

- No DB schema changes
- No migration needed (CONF defaults to 2.0°F; missing key reads as the default; behavior matches v4.5.9 exactly)
- HACS download required after deploy.sh
- HA restart required (const + hvac_covers + hvac + __init__ + config_flow + strings all touched)

## Next

- **v4.5.10** — Tier 2 cycle for the runtime-tunable expansion + UI label cleanup. Per the audit conversation:
  - Number entities for HIGH-value HC tunables (COVER_CLOSE_TEMP, COVER_OPEN_TEMP, COVER_MANUAL_OVERRIDE_HOURS, SOLAR_BANK_FLOOR, possibly OCCUPIED_CLOSE_TEMP_DELTA promoted to live slider)
  - Rename `_attr_name` of `HVACZoneIntelligenceSwitch` from "Zone Intelligence" → **"Active Zone Control"** (broader term covering vacancy management, duty cycle, stale sensor failsafe, solar banking, pre-arrival routing — not just "predictive pre-conditioning" which only covers part of the feature set)
  - Rename `_attr_name` of `HVACZoneSweepSwitch` from "Zone Sweep" → **"Vacancy Auto-Off"**
  - **No CONF rename, no entity_id rename** — labels only. Dashboards safe.
- **v4.6.0** — Routine Awareness with reconciled AnomalyEvent foundation
