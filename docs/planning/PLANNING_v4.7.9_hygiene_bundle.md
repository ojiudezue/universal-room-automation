# PLANNING v4.7.9 — Hygiene Bundle

**Status:** Plan ready for build
**Tier:** Tier 2-DB (three parallel staff-engineer reviews, different framings)
**Phase:** Phase A (runs in parallel with v4.7.8 Egress and v4.7.10 Gitea; ships SECOND — between Gitea and Egress)
**Predecessor:** v4.7.7 (AC Nudge / AC Reset Decouple + DPM Sensor Cleanup)
**Filed:** 2026-05-29
**Recall:** "Plan v4.7.9 hygiene bundle" / "Resume v4.7.9"

---

## 1. Goal + Why

Three small carry-forwards from the v4.7.7 cycle bundled into one minimal Hygiene release:

- **Group A** — Make the (Nudge=OFF, Reset=ON) cell of the v4.7.7 decouple matrix functionally meaningful by adding a per-zone `force_ac_reset` button that bridges into `_perform_hard_reset_escalation` directly. v4.7.7 §11 documented that cell as "unreachable today" because soft-nudge auto-detection is gated off and no manual entry point bridges to escalation. We add the bridge.
- **Group B** — Add `SIGNAL_DPM_SKIP_REASONS_UPDATED` so `DynamicPresetOverridesAppliedSensor.skipped_zones_with_reason` refreshes when ONLY skip reasons change between ticks while the overrides dict itself is stable empty. Today the sensor only re-renders on `SIGNAL_DYNAMIC_PRESET_OVERRIDES_UPDATED` (fired only when the overrides dict changes). Reviewer B-M1 finding from v4.7.7, carried forward.
- **Group C** — Fix the specific DPM zone-skip ROOT CAUSE surfaced by the v4.7.7 B2 instrumentation. The taxonomy ships in v4.7.7; the actual fix-the-cause was deferred pending live data. v4.7.9 reads the live sensor at build time and patches whichever reason the live attribute surfaces.

**Why bundled (vs three separate cycles):** all three are small, none touch `database.py`, none touch coordinator wiring beyond signals, and Tier 2-DB review ceremony absorbs the bundle-coupling risk. Bundling cuts review-cycle overhead 3x vs three independent Tier 1 cycles.

**Why Tier 2-DB (user-upgraded from Tier 1):** Phase A parallel-merge risk against v4.7.8 (Egress) on `sensor.py` and `signals.py`. Tier 2-DB's third reviewer (Reviewer C) is the parallel-merge-risk reviewer. v4.7.7's Reviewer B-M1 also showed that signal-chain hygiene benefits from the targeted-framing approach over generic correctness review.

---

## 2. Tier Classification

Tier 2-DB. Three parallel reviewers, different framings, locked at planning (see §10).

| Tier 2-DB trigger | Hit? |
|---|---|
| Touches `database.py` DAO definitions | No |
| Migrates ≥3 callers to a new DAO | No |
| Changes dispatched-payload shape | No (new signal, no payload) |
| Adds behavioral test infra against real schemas | No |
| Followed within 1-2 versions by a planned schema migration | No |

| Tier-upgrade rationale (user-set) | Hit? |
|---|---|
| Phase A parallel-merge risk | YES — Egress touches `sensor.py` + `signals.py`; Hygiene also touches both |
| Cross-cycle signal interaction risk | YES — Egress may add `SIGNAL_EGRESS_PAUSE_UPDATED`; Hygiene adds `SIGNAL_DPM_SKIP_REASONS_UPDATED`; both append to `signals.py` |
| Multiple new code surfaces (button + signal + root-cause fix) | YES |

User override to Tier 2-DB stands.

---

## 3. Discovery — Read Before Build

| File | Lines | Why |
|---|---|---|
| `docs/readmes/README_v4.7.7.md` | §A1–B3 + §11 | Establishes the (Nudge=OFF, Reset=ON) unreachable cell and the v4.7.7 B2 skip-reason taxonomy. Group A's existence justification. |
| `custom_components/universal_room_automation/domain_coordinators/hvac_override.py` | 1512–1605 | `_perform_hard_reset_escalation` — TARGET METHOD for Group A. A3 guard at L1549. Signature is `(self, zone: ZoneState, kwh_rate_now: float)` — NO `triggered_by` param; see §6 spec correction. |
| `custom_components/universal_room_automation/domain_coordinators/hvac_override.py` | 1203 | `_read_kwh_rate(zone, now)` — pattern Group A button uses to supply `kwh_rate_now`. |
| `custom_components/universal_room_automation/domain_coordinators/hvac_override.py` | 1649 | `_resolve_zone(zone_id_or_entity)` — bridges climate_entity → ZoneState (button passes climate_entity). |
| `custom_components/universal_room_automation/domain_coordinators/hvac_override.py` | 1733–1756 | `force_nudge` method — semantically closest precedent (manual button → soft-nudge). Group A mirrors this for hard-reset. |
| `custom_components/universal_room_automation/button.py` | 42–77 | Per-zone button registration loop in `async_setup_entry` (iterates `_discover_ac_zones`). Group A extends with a fourth action. |
| `custom_components/universal_room_automation/button.py` | 604–637 | `_AC_RAMP_BUTTON_SPECS` dict — Group A adds a `force_ac_reset` spec entry. |
| `custom_components/universal_room_automation/button.py` | 640–680 | `_ac_ramp_prefix` + `_make_ac_ramp_button` — prefix-computation pattern (`force_ac_reset` needs an action_offset). |
| `custom_components/universal_room_automation/button.py` | 682–803 | `_ACRampButton` class — Group A's button reuses this class verbatim (single-class-multi-action design). The press path at L776–803 calls `getattr(arr, self._method_name)(self._climate_entity)`. The arrester method must accept `climate_entity` as its single positional arg. |
| `custom_components/universal_room_automation/domain_coordinators/signals.py` | 1–97 | Group B adds `SIGNAL_DPM_SKIP_REASONS_UPDATED` at end of file. |
| `custom_components/universal_room_automation/domain_coordinators/energy.py` | 2681–2812 | `_async_evaluate_dynamic_presets` — Group B edge-detection patch site. Existing `_changed` block at 2788-2807 is the model. Add parallel `_reasons_changed` block. |
| `custom_components/universal_room_automation/domain_coordinators/energy.py` | 450 | `self._dynamic_preset_skip_reasons` instance attr — needs `_prev_skip_reasons` companion (or simple prev-snapshot local) for edge detection. |
| `custom_components/universal_room_automation/sensor.py` | 6788–6903 | `DynamicPresetOverridesAppliedSensor` — Group B adds third dispatcher subscription at `async_added_to_hass`. |
| `custom_components/universal_room_automation/domain_coordinators/dynamic_preset.py` | (entire) | Group C may patch one of `_build_overrides_with_reason` / `evaluate_with_reason` / `async_evaluate_with_reason` depending on live skip reason. |
| `docs/QUALITY_CONTEXT.md` | Bug Classes #20, #38, #42, #43, #45, #46 | Active classes for the surfaces this cycle touches. |

---

## 4. Live State Probe — Group C

**Build-time mandatory step:** before writing Group C code, the builder runs:

```
ha-mcp get_state sensor.ura_energy_coordinator_dynamic_preset_overrides_applied
```

Inspect `attributes.skipped_zones_with_reason`. The list-of-dicts shape is `[{"zone_id": "...", "reason": "..."}]`.

**Planner-time probe result (2026-05-29):** Live HA endpoint timed out from the planning environment (`http://homeassistant.local:8123/api/states/...` 60-second timeout). **Live skip-reason state UNKNOWN at planning time.** Builder must re-probe with `ha-mcp` (which uses websocket, not direct HTTP).

Because the live state is unknown at planning time, this plan documents the candidate fixes for ALL 6 taxonomy values and defers the code-decision to build. Tests cover all 6 reason paths regardless of which reason the live attr surfaces.

### Candidate fix per reason

| Reason | Source | Candidate fix |
|---|---|---|
| `gate_disabled` | `dynamic_preset.evaluate_with_reason` | Helper text + config-flow checkbox surfaces per-zone DPM enable toggle. Toggle exists; discoverability is the gap. Add a row to the HVAC DPM step in `config_flow.py` that lists each zone with its current enable state. |
| `no_forecast_delta` | `dynamic_preset.evaluate_with_reason` | WPM delta unavailable for the zone. Either the zone lacks WPM coverage (config gap — surface in form) or WPM hasn't warmed up yet (timing — add a one-shot retry deferred to `SIGNAL_WEATHER_PROVIDER_CHANGED`). Builder picks based on which is the live cause. |
| `dwell_pending` | `dynamic_preset.evaluate_with_reason` | Bucket transition gated by dwell timer. NOT a bug; expected behavior. If consistently surfaced, helper text on the dwell number entity explains "Skips during dwell window are normal." NO code fix; documentation only. |
| `unknown_bucket` | `dynamic_preset._build_overrides_with_reason` | Bucket boundary lookup returned no match. Likely a CONF_DPM_BUCKETS gap (CONF doesn't cover the current delta_f). Builder verifies bucket coverage and either widens defaults in `hvac_const.py` or adds an "out-of-range" fallback in `_build_overrides_with_reason` that returns the nearest bucket. |
| `home_range_not_configured` | `dynamic_preset._build_overrides_with_reason` | PresetManager warming/init race vs DPM tick. Most-substantial fix: add a one-shot retry deferred to a PresetManager-ready signal (or fall back to `SEASONAL_DEFAULTS` if PresetManager.get_seasonal_setpoints returns None during init). Builder traces back to the PresetManager init order at planning-time-deferred read-in. |
| `canonical_label_mismatch` | `energy.py:2693-2708` | The v4.7.5 D3 lazy canonical-resolution chain failing for a specific zone-naming pattern. Builder logs `parts` + `list(zm_zones.keys())` (already logged at L2717-2722) and adds the missing alias or normalizes the zone name. May require widening the canonical-merge `" + "` split. |
| `evaluation_failed` | `energy.py:2774-2777` | Caught exception; surface the traceback. Builder reads the WARNING log line and patches the root cause in `dynamic_preset.py`. |

**If the live attr is empty (no zones skipped):** Group C ships as documentation-only — adds Tier 2-DB Reviewer C check that the 6-reason taxonomy is exercised by tests but no production fix lands. This is acceptable; do NOT invent a fix that's not pointed-to by the live data.

---

## 5. Deliverables

### D1 — Group A: per-zone `force_ac_reset` button

Add a fourth per-zone action to the existing `_AC_RAMP_BUTTON_SPECS` family. One button per canonical HVAC zone, registered alongside `force_nudge` / `cancel_nudge` / `clear_lockout`.

#### Files

- `custom_components/universal_room_automation/button.py`
- `custom_components/universal_room_automation/domain_coordinators/hvac_override.py` (new thin public wrapper)
- `strings.json` + `translations/en.json`

#### Spec

**New entity:** `button.ura_hvac_coordinator_force_ac_reset_<zone_id>`
**Unique ID:** `f"{DOMAIN}_hvac_ac_ramp_force_ac_reset_{zone_id}"`
**Friendly name:** `f"{prefix:02d} · Force AC Reset ({zone_name})"`
**Device:** URA: HVAC Coordinator (mirrors existing `_ACRampButton`)
**Category:** None (primary user-facing action, matches `force_nudge`)
**Icon:** `mdi:hvac-off`

**Button spec dict (added to `_AC_RAMP_BUTTON_SPECS`):**

```python
"force_ac_reset": {
    "label": "Force AC Reset",
    "icon": "mdi:hvac-off",
    "method": "force_ac_reset",
    "category": None,
    "cluster": "controls",
    # Controls cluster, after cancel_nudge (offset 2): force_ac_reset = offset 4
    "action_offset": 4,
},
```

**Prefix scheme:** With `action_offset=4`, prefix = `10 + zone_index*10 + 4` →
- zone 1: prefix 24
- zone 2: prefix 34
- zone 3: prefix 44

(Sits immediately after each zone's `cancel_nudge` button. Linear-grow scheme preserved.)

**New arrester method (`OverrideArrester.force_ac_reset`) in `hvac_override.py`:**

```python
async def force_ac_reset(self, zone_id_or_entity: str) -> None:
    """User-triggered hard AC reset (v4.7.9 D1 button).

    Bridges the (Nudge=OFF, Reset=ON) cell of the v4.7.7 decouple matrix.
    Subject to:
      - Master switch (kill-switch contract — same as force_nudge)
      - A3 guard inside _perform_hard_reset_escalation (no-op if
        _ac_reset_enabled is False; sets zone.ramp_state IDLE)
      - Daily cap + min-interval gates inside the escalation
    """
    if not self._ramp_master_enabled:
        _LOGGER.warning(
            "force_ac_reset blocked: master switch is OFF (zone=%s)",
            zone_id_or_entity,
        )
        return
    zone = self._resolve_zone(zone_id_or_entity)
    if zone is None:
        return
    now = dt_util.now()
    kwh_rate = self._read_kwh_rate(zone, now) or 0.0
    await self._perform_hard_reset_escalation(zone, kwh_rate)
```

**Spec correction vs original task brief:** the task brief mentioned passing `triggered_by="force_reset_button"` to `_perform_hard_reset_escalation`. The actual method signature is `_perform_hard_reset_escalation(self, zone: ZoneState, kwh_rate_now: float)` — there is NO `triggered_by` parameter today. The plan does NOT add one (that would change signature for one caller; out-of-scope for hygiene). The `triggered_by="manual"` signal already propagates downstream via the existing `_perform_soft_nudge`/`_track_zone_action` paths that the escalation invokes; for force-reset the same trail will read `auto` because the existing escalation hard-codes `"auto"` at L1591. **Live-validation step §11 verifies the `ac_ramp_events` row carries `auto` as `triggered_by` — this is a known limitation and is OK; if user wants `manual` traceability, that's a follow-up cycle, not scope here.**

**Registration loop edit (`button.py` line ~61-76):** add a fourth `cm_entities.append` for the new action inside the existing per-zone loop.

**Helper text (strings + translations):** `"Manually trigger a hard AC reset for this zone. Requires AC Reset switch ON. Subject to daily cap and minimum interval gates. Use when soft-nudge auto-detection is disabled and you want to manually clear a stuck AC cycle."`

#### Acceptance Criteria

- **Verify:** `button.ura_hvac_coordinator_force_ac_reset_<zone_id>` entity exists for every canonical HVAC zone after restart.
- **Verify:** Pressing the button with `switch.ura_hvac_coordinator_ac_reset` ON triggers `_perform_hard_reset_escalation` and logs the standard escalation INFO/DEBUG.
- **Verify:** Pressing the button with `switch.ura_hvac_coordinator_ac_reset` OFF logs the A3 DEBUG line ("Hard reset on %s skipped — AC Reset feature disabled") and writes ZERO rows to `ac_reset_state` / `ac_ramp_events`.
- **Verify:** Pressing the button with the ramp master switch OFF logs `"force_ac_reset blocked: master switch is OFF (zone=%s)"` and exits without escalation.
- **Verify:** Pressing the button twice in quick succession respects the existing daily-cap and min-interval gates (second press is a no-op when gates trip).
- **Test:** `test_v479_force_ac_reset_button_creates_one_per_zone` (entity count == canonical zone count).
- **Test:** `test_v479_force_ac_reset_routes_to_escalation` (asserts `_perform_hard_reset_escalation` called once per press).
- **Test:** `test_v479_force_ac_reset_a3_guard_no_op_when_reset_disabled` (asserts NO DB writes when `_ac_reset_enabled` False).
- **Test:** `test_v479_force_ac_reset_master_off_blocked` (asserts blocked-log line; NO arrester method call).
- **Test:** `test_v479_force_ac_reset_button_device_assignment` (asserts DeviceInfo.identifiers carries `("ura", "hvac_coordinator")`).
- **Live:** `button.ura_hvac_coordinator_force_ac_reset_back_hallway` (or whatever canonical zone exists) is present in HA registry within 1 min of restart.
- **Live:** A test press with AC Reset OFF produces the A3 DEBUG line in the journald log and ZERO `ac_ramp_events` rows for the affected zone in the minute post-press.

---

### D2 — Group B: `SIGNAL_DPM_SKIP_REASONS_UPDATED`

#### Files

- `custom_components/universal_room_automation/domain_coordinators/signals.py`
- `custom_components/universal_room_automation/domain_coordinators/energy.py`
- `custom_components/universal_room_automation/sensor.py`

#### Spec

**1. Add constant to `signals.py`:**

```python
# v4.7.9 D2: dispatched from EnergyCoordinator._async_evaluate_dynamic_presets
# when the per-zone DPM skip_reasons dict changes between ticks BUT the
# overrides dict itself is unchanged. Carry-forward from v4.7.7 Reviewer B-M1:
# DynamicPresetOverridesAppliedSensor.skipped_zones_with_reason only refreshes
# when SIGNAL_DYNAMIC_PRESET_OVERRIDES_UPDATED fires (which gates on overrides
# changing), so reason-only deltas were stale for up to 24h on stable-empty days.
# Sensor recomputes from latest state; idempotent re-fire is safe.
SIGNAL_DPM_SKIP_REASONS_UPDATED: Final = "ura_dpm_skip_reasons_updated"
```

**2. Edge-detection + dispatch in `energy.py:_async_evaluate_dynamic_presets`** (after the existing `_changed` block at ~L2788-2807):

```python
# v4.7.9 D2: independent edge detection on the skip_reasons dict.
# Captures the case where the overrides dict stayed empty between ticks
# but skip_reason values transitioned (e.g., dwell_pending -> unknown_bucket
# for the same zone). Sensor subscribes to BOTH signals.
_reasons_prev = getattr(self, "_dynamic_preset_skip_reasons_prev", {})
_reasons_changed = _reasons_prev != updated_skip_reasons
self._dynamic_preset_skip_reasons_prev = dict(updated_skip_reasons)

if _reasons_changed:
    try:
        from homeassistant.helpers.dispatcher import async_dispatcher_send
        from .signals import SIGNAL_DPM_SKIP_REASONS_UPDATED
        async_dispatcher_send(self.hass, SIGNAL_DPM_SKIP_REASONS_UPDATED)
    except Exception:
        pass
```

**Note on idempotency:** if BOTH overrides AND reasons changed in the same tick, BOTH signals fire. Sensor's `_on_signal` callback is identical (`async_write_ha_state`), so double-fire is a no-op write of the same value. Bug Class #45 safe — no lambda closure over loop vars; the dispatcher is a bound module-level call.

**Init-time prev attr:** add `self._dynamic_preset_skip_reasons_prev: dict[str, str] = {}` next to the existing `self._dynamic_preset_skip_reasons = {}` at `energy.py:450` so the first-tick comparison against `{}` doesn't fire spuriously.

**3. Sensor subscription in `sensor.py:DynamicPresetOverridesAppliedSensor.async_added_to_hass`** (extend the existing 2-signal subscription at ~L6816-6830):

```python
from .domain_coordinators.signals import (
    SIGNAL_DYNAMIC_PRESET_OVERRIDES_UPDATED,
    SIGNAL_DYNAMIC_PRESET_TRANSITIONED,
    SIGNAL_DPM_SKIP_REASONS_UPDATED,  # v4.7.9 D2
)
# ... existing two async_on_remove blocks ...
self.async_on_remove(
    async_dispatcher_connect(
        self.hass, SIGNAL_DPM_SKIP_REASONS_UPDATED, self._on_signal,
    )
)
```

**Non-goal (explicit):** do NOT add `SIGNAL_DPM_SKIP_REASONS_UPDATED` subscribers anywhere else. Single subscriber, scoped to `DynamicPresetOverridesAppliedSensor`. Future additions are a separate cycle.

#### Acceptance Criteria

- **Verify:** `SIGNAL_DPM_SKIP_REASONS_UPDATED` is defined as a module-level `Final` in `signals.py`.
- **Verify:** When skip_reasons dict changes between ticks AND overrides dict is unchanged, ONLY `SIGNAL_DPM_SKIP_REASONS_UPDATED` fires (not `SIGNAL_DYNAMIC_PRESET_OVERRIDES_UPDATED`).
- **Verify:** When overrides dict changes, `SIGNAL_DYNAMIC_PRESET_OVERRIDES_UPDATED` fires as today; `SIGNAL_DPM_SKIP_REASONS_UPDATED` ALSO fires if reasons changed (double-fire is harmless).
- **Verify:** When neither dict changes, NEITHER signal fires (no spurious wakeups).
- **Verify:** `DynamicPresetOverridesAppliedSensor` subscription unsub is registered via `async_on_remove` (Bug Class #38 safe).
- **Test:** `test_v479_skip_reasons_signal_constant_defined` (AST check on signals.py).
- **Test:** `test_v479_skip_reasons_signal_fires_on_reason_only_change` (overrides empty both ticks, reasons differ → signal fires).
- **Test:** `test_v479_skip_reasons_signal_silent_on_no_change` (both dicts identical between ticks → signal does NOT fire).
- **Test:** `test_v479_skip_reasons_signal_fires_alongside_overrides_when_both_change` (both signals fire; sensor state-write is idempotent).
- **Test:** `test_v479_skip_reasons_first_tick_no_spurious_fire` (init-from-empty does NOT fire if no zones are skipped).
- **Test:** `test_v479_sensor_subscribes_to_new_signal_with_unsub_tracked` (mock dispatcher; assert `async_on_remove` called with the unsub).
- **Live:** Force a reason transition by toggling a zone's DPM enable switch OFF then ON between two DPM ticks; verify `sensor.ura_energy_coordinator_dynamic_preset_overrides_applied.skipped_zones_with_reason` reflects the new reason within one decision cycle (≤5 min).

---

### D3 — Group C: DPM zone-skip root-cause fix (build-time targeted)

#### Files

Conditional on live skip-reason. Most likely:
- `custom_components/universal_room_automation/domain_coordinators/dynamic_preset.py`
- POSSIBLY `custom_components/universal_room_automation/domain_coordinators/energy.py` (only if reason is `canonical_label_mismatch`)
- POSSIBLY `custom_components/universal_room_automation/config_flow.py` (only if reason is `gate_disabled` and the fix is discoverability)

#### Spec — build-time decision tree

Builder runs the live probe (§4) THEN picks the candidate fix from the table in §4. Builder writes the actual code-fix planning section into a build-time appendix to this doc (`PLANNING_v4.7.9_hygiene_bundle.md` §13 BUILD-TIME APPENDIX) before writing code.

If the live attr is empty, D3 ships as documentation-only. Tests in this plan exercise all 6 reason paths regardless.

**Constraint:** the fix must be small (≤30 LoC production for D3 alone — keep it hygiene-scale). If the live reason demands a fix larger than 30 LoC, builder splits it out into a v4.7.11 follow-up cycle and ships v4.7.9 with the other two groups + the test coverage for all 6 reasons.

#### Acceptance Criteria

- **Verify (always):** all 6 reason values surface correctly through `_get_dynamic_preset_skip_reasons` → `skipped_zones_with_reason` sensor attribute (no regression on the v4.7.7 B2 taxonomy).
- **Verify (conditional):** the live skip-reason that motivated the fix is gone OR has demonstrably reduced count in `sensor.ura_energy_coordinator_dynamic_preset_overrides_applied.skipped_zones_with_reason` post-deploy.
- **Test:** `test_v479_dpm_skip_reason_gate_disabled_path` (force a zone with `dpm_enabled=False`; assert reason).
- **Test:** `test_v479_dpm_skip_reason_no_forecast_delta_path` (mock WPM to return None; assert reason).
- **Test:** `test_v479_dpm_skip_reason_dwell_pending_path` (force a fresh bucket transition; assert reason).
- **Test:** `test_v479_dpm_skip_reason_unknown_bucket_path` (delta_f outside all configured buckets; assert reason).
- **Test:** `test_v479_dpm_skip_reason_home_range_not_configured_path` (PresetManager returns None for home; assert reason).
- **Test:** `test_v479_dpm_skip_reason_canonical_label_mismatch_path` (zone_name with " + " resolving to no zm_zones key + zone_id fallback also empty; assert reason).
- **Live:** Post-deploy, observation of `skipped_zones_with_reason` for 1 full DPM tick (≤5 min) shows the targeted reason cleared (or, if empty-at-build, all 6 reasons surface correctly in test runs).

---

## 6. Constants Inventory

| Constant | Module | Type | Value |
|---|---|---|---|
| `SIGNAL_DPM_SKIP_REASONS_UPDATED` | `domain_coordinators/signals.py` | `Final[str]` | `"ura_dpm_skip_reasons_updated"` |

No new CONF keys (Group A's button has no user-configurable state beyond switch dependencies that already exist).

No new DB tables / columns.

No new device_info identifiers.

---

## 7. Bug Class Coverage

| Class | Surface | Mitigation |
|---|---|---|
| #20 (concurrent reload race) | Group A button → arrester method | `_resolve_zone` + master-switch check are sync-snapshotted at method entry, mirroring `force_nudge` |
| #38 (untracked dispatcher unsub) | Group B sensor third subscription | `async_on_remove(async_dispatcher_connect(...))` pattern (matches existing two subscriptions) |
| #42 (lambda + async_create_task) | Group B dispatcher callbacks | `_on_signal` is a `@callback`-decorated bound method (not a lambda); dispatcher uses module-level `async_dispatcher_send` call (not async_create_task) |
| #43 (RestoreEntity ordering) | N/A (no RestoreEntity additions) | — |
| #45 (lambda closure over loop vars) | Group B edge-detection loop in energy.py | No closure captures; `_reasons_changed` is a plain bool computed from dict equality |
| #46 (config-entry write inside setup) | All groups | NONE of the groups call `async_update_entry`. Button registration is in `async_setup_entry` BEFORE `add_update_listener` (matches existing per-zone button registration). Signal definitions are module-level. |
| Group A specific — kwh_rate read race | Button calls `_read_kwh_rate(zone, now)` then awaits escalation | `_read_kwh_rate` is sync; race-window is the same as `force_nudge` precedent — acceptable. |
| Group B specific — first-tick spurious fire | Edge-detection compares `_prev` (init `{}`) against `updated_skip_reasons` | Init both to `{}` in `__init__`. First-tick with empty skip_reasons → no fire. First-tick with non-empty skip_reasons → fires once (correct, it's a real state change from "no signal yet" to "first reason"). |

---

## 8. Parallel-Merge-Risk Discipline (Phase A)

**Hygiene merges SECOND in Phase A: Gitea → Hygiene → Egress.**

### Files Hygiene touches that Egress may also touch

| File | Hygiene's touch | Egress's expected touch | Conflict-risk |
|---|---|---|---|
| `sensor.py` | Single new dispatcher subscription (~5 lines) in `DynamicPresetOverridesAppliedSensor.async_added_to_hass` near L6816 | New visibility entities (additive new classes) | LOW — Hygiene's edit is line-localized to an existing method; Egress adds new classes. No same-line conflict unless Egress also touches `DynamicPresetOverridesAppliedSensor` (it shouldn't). Reviewer C verifies. |
| `signals.py` | New `SIGNAL_DPM_SKIP_REASONS_UPDATED` constant appended at end of file | Possibly new `SIGNAL_EGRESS_PAUSE_UPDATED` constant appended at end | LOW — both append. Git merge will succeed; risk is ordering / comment-attribution noise. Reviewer C flags ordering preference. |

### Files Hygiene touches that Egress should NOT touch

- `button.py` (Hygiene-only)
- `domain_coordinators/hvac_override.py` (Hygiene-only — new method)
- `domain_coordinators/energy.py` (Hygiene's edge-detection block at L2788-2807 area; Egress should stay out of DPM eval)
- `domain_coordinators/dynamic_preset.py` (Hygiene Group C only)
- `strings.json` + `translations/en.json` (additive; conflict-free)

### Files Hygiene EXPLICITLY does NOT touch

- `database.py` — reserved for Egress and Phase B AnomalyType (non-goal §13)
- `__init__.py` — no new entity-registry migrations, no platform forwarding changes
- `switch.py` / `number.py` / `select.py` — no new entities of those domains

### Merge-order ceremony

1. Gitea merges first (lowest blast-radius, infra-only).
2. Hygiene rebases on post-Gitea develop, runs pre-deploy zero-bugs gate (§9), reviews complete, deploys.
3. Egress rebases on post-Hygiene develop. If Egress added `signals.py` constants in parallel, the rebase has trivial append-conflicts to resolve.

---

## 9. Pre-Deploy Zero-Bugs Gates (5)

Standard 5-gate checklist (user-coined post-v4.7.4.3 incident, MANDATORY per CLAUDE.md). All five MUST pass before `./scripts/deploy.sh` is invoked.

| Gate | Command | Pass criterion |
|---|---|---|
| 1 — Conflict markers | `grep -rn '<<<<<<<\|=======\|>>>>>>>' custom_components/universal_room_automation/` | Zero matches |
| 2 — Syntax (py_compile changed files) | `python3 -m py_compile custom_components/universal_room_automation/button.py custom_components/universal_room_automation/domain_coordinators/hvac_override.py custom_components/universal_room_automation/domain_coordinators/signals.py custom_components/universal_room_automation/domain_coordinators/energy.py custom_components/universal_room_automation/sensor.py custom_components/universal_room_automation/domain_coordinators/dynamic_preset.py` | Zero errors |
| 3 — JSON validity (strings + translations) | `python3 -c "import json; json.load(open('custom_components/universal_room_automation/strings.json')); json.load(open('custom_components/universal_room_automation/translations/en.json'))"` | Zero errors |
| 4 — Cycle test suite | `PYTHONPATH=quality python3 -m pytest quality/tests/test_v479_*.py -v` | All tests pass |
| 5 — Suite baseline diff | `PYTHONPATH=quality python3 -m pytest quality/tests/ -v 2>&1 \| tail -50` against `pre-review-v4.7.9` tag | No regression in pass count |

---

## 10. Tier 2-DB Review Framings (locked at planning)

Three parallel reviewers, different framings. No reviewer sees another's report before submitting their own.

### Reviewer A — Correctness + state-machine invariants

**Focus:** Does the code do the right thing in all the cells of the state space?

**Checklist:**
- Group A: Force-Reset button → `force_ac_reset` arrester method → `_perform_hard_reset_escalation`. Trace each gate (master switch, A3 `_ac_reset_enabled`, daily cap, min-interval) under: button-press-while-mid-nudge, button-press-after-lockout-engaged, button-press-with-A3-disabled, button-press-with-master-off, button-press-with-zone-id-mismatch.
- Group A: Idempotency vs existing AC Nudge button. Pressing Force-Reset while a nudge is in-flight — does the escalation interfere with `_nudge_in_flight` tracking? (Expected: escalation runs independently; `_perform_ac_reset` invokes the off→wait→restore cycle which may interact with an in-flight nudge restore timer. Trace the timer collision.)
- Group A: Test that `triggered_by` in the resulting `ac_ramp_events` row is the existing-hardcoded `"auto"` and document that no `"manual"` traceability exists for force-reset — confirm this is acceptable.
- Group B: Edge-detection conditions. Walk the four combinations of (overrides_changed × reasons_changed). Confirm no double-fire of `SIGNAL_DYNAMIC_PRESET_OVERRIDES_UPDATED`. Confirm `SIGNAL_DPM_SKIP_REASONS_UPDATED` fires exactly when (overrides_unchanged AND reasons_changed) OR (overrides_changed AND reasons_changed).
- Group B: First-tick handling. `_dynamic_preset_skip_reasons_prev` defaults to `{}` — verify the comparison against `updated_skip_reasons={}` does NOT fire spuriously on first tick.
- Group C: Whichever skip-reason fix landed — does it correctly clear the targeted reason without introducing a NEW skip-reason for the same zone?

**Output:** CRITICAL / HIGH / MEDIUM / LOW findings with file:line refs and proposed fixes.

---

### Reviewer B — Async + lifecycle + restart resilience

**Focus:** Does it survive HA restart, reload, and concurrent execution?

**Checklist:**
- Group A: Force-Reset button is a sync entry point (`async def async_press`) into an async escalation. Confirm no `add_executor_job` or sync DB access is introduced. Confirm `_resolve_zone` is sync (it is) and the await chain is clean.
- Group A: Dispatcher subscription lifecycle on the new button. Verify `async_added_to_hass` mirrors `_ACRampButton` (subscription to `SIGNAL_HVAC_ENTITIES_UPDATE` with tracked unsub). Bug Class #38 enforcement.
- Group A: Restart resilience. After HA restart, the button is re-created via the per-zone registration loop in `async_setup_entry`. Verify the loop reads canonical zones from the SAME `_discover_ac_zones` source that the existing 3 buttons use (no divergence in zone enumeration).
- Group B: `SIGNAL_DPM_SKIP_REASONS_UPDATED` dispatcher subscription lifecycle in `DynamicPresetOverridesAppliedSensor`. Verify tracked unsub (Bug Class #38). Verify `_on_signal` is `@callback`-decorated (Bug Class #42 — no lambda + async_create_task).
- Group B: Edge-detection state (`_dynamic_preset_skip_reasons_prev`) survives EnergyCoordinator reload. Confirm it's an instance attribute (it is; init in `__init__`). Confirm no `_async_evaluate_dynamic_presets` re-entrancy because the wrapping method is itself sequential.
- Group B: Bug Class #46 boundary on signal infrastructure. Confirm signal-emit happens INSIDE `_async_evaluate_dynamic_presets` (which runs AFTER setup is complete) and NOT inside any `async_setup` / `async_update_entry` path.
- Group C: If the fix introduces a deferred listener (e.g., for `home_range_not_configured` fix using a PresetManager-ready signal), verify the listener has tracked unsub and follows the deferred-restore pattern from v4.7.x D2.

**Output:** CRITICAL / HIGH / MEDIUM / LOW findings with file:line refs.

---

### Reviewer C — New surfaces + cross-rule precedence + parallel-merge risk

**Focus:** Does it integrate cleanly with the rest of URA, with HA, and with the parallel Phase A cycles?

**Checklist:**
- Group A: Per-zone Force-Reset button DeviceInfo. Verify `identifiers={(DOMAIN, "hvac_coordinator")}` and `via_device=(DOMAIN, "coordinator_manager")`. Verify entity appears under "URA: HVAC Coordinator" device card, not orphaned.
- Group A: Helper text accuracy in `strings.json` + `translations/en.json`. Verify text covers (a) requires AC Reset switch ON, (b) subject to daily cap, (c) subject to min-interval gate, (d) use case (when soft-nudge auto-detection disabled).
- Group A: Button category. `None` (primary action) vs `CONFIG` (admin). Confirm `None` matches the existing `force_nudge` precedent.
- Group A: Numeric-prefix sort order. Verify `24 · Force AC Reset` sits between `22 · Cancel AC Nudge` and `30 · Force AC Nudge (zone 2)` per the cluster ordering scheme.
- Group B: Signal chain end-to-end. Trace from `energy.py:async_dispatcher_send` → dispatcher → `DynamicPresetOverridesAppliedSensor._on_signal` → `async_write_ha_state` → `extra_state_attributes` → `_get_dynamic_preset_skip_reasons(self.hass)` → live attr refresh in dashboard. Confirm no broken link.
- Group B: Cross-cycle signal conflict with Egress. Egress may add `SIGNAL_EGRESS_PAUSE_UPDATED` to `signals.py`. Both cycles append to the same file. Confirm Hygiene's constant addition is at end-of-file with a v4.7.9 comment header, and flag to Egress reviewer that ordering preference is "append after Hygiene's v4.7.9 entry."
- Group C: Same as Group A device-info check but for the actual targeted-fix code (e.g., if `gate_disabled` fix touches `config_flow.py`, verify the form step round-trips through options flow correctly).
- Phase A merge dependency: confirm Hygiene's `sensor.py` edit and `signals.py` edit do NOT touch any line Egress's plan would touch. If Egress's plan is unavailable at review time, flag as "cross-cycle merge review pending."

**Output:** CRITICAL / HIGH / MEDIUM / LOW findings with file:line refs.

---

## 11. Live Validation (Review D — post-deploy)

After `./scripts/deploy.sh 4.7.9 ...` completes AND HACS installs the version AND HA restarts cleanly:

| Check | Tool | Pass criterion |
|---|---|---|
| Force-Reset button exists per zone | `ha-mcp get_state button.ura_hvac_coordinator_force_ac_reset_<zone_id>` | One entity per canonical zone; state is `unknown` (button hasn't been pressed) |
| Force-Reset button DeviceInfo | `ha-mcp get_device <device_id>` | Entity sits under "URA: HVAC Coordinator" |
| A3 guard works on real button press | Press button with `switch.ura_hvac_coordinator_ac_reset` OFF | journald shows the A3 DEBUG line; ZERO new rows in `ac_ramp_events` for the zone in the next 60s |
| Escalation works on real button press | Press button with `switch.ura_hvac_coordinator_ac_reset` ON (and master ON; outside lockout) | At least one new row in `ac_ramp_events` with `event_type=hard_reset_started` for the zone within 60s |
| Signal fires on reason-only change | Toggle a zone's DPM enable OFF, wait one DPM tick, toggle back ON | `sensor.ura_energy_coordinator_dynamic_preset_overrides_applied.skipped_zones_with_reason` updates within ≤5 min (one DPM tick) |
| No regression in DPM overrides applied | `ha-mcp get_state sensor.ura_energy_coordinator_dynamic_preset_overrides_applied` | State is a non-negative int; attrs include `breakdown`, `skipped_zones`, `skipped_zones_with_reason`, `dwell_remaining_per_zone_min` |
| No new frame-helper warnings | `ha-mcp get_logs source=system_service slug=core` | Zero new frame-helper warnings vs pre-v4.7.9 baseline |
| Group C reason fix landed | Live skip-reason attr | Targeted reason from §4 absent (or count reduced) for the affected zone |

---

## 12. Explicit Non-Goals

- Do NOT touch `database.py` (Egress and Phase B AnomalyType own that file in this stretch).
- Do NOT add a new master switch over Force-Reset (the AC Reset switch + master ramp switch are sufficient).
- Do NOT add a new master switch over DPM (the existing DPM master switch + per-zone enable toggles are sufficient).
- Do NOT extend the Force-Reset button to include force_nudge restoration mid-window — that's a separate concern.
- Do NOT add `SIGNAL_DPM_SKIP_REASONS_UPDATED` listeners outside `DynamicPresetOverridesAppliedSensor` — single subscriber, scoped.
- Do NOT add a `triggered_by="force_reset_button"` parameter to `_perform_hard_reset_escalation` (signature change for one caller is out-of-scope for hygiene; the `auto` provenance in `ac_ramp_events` is acceptable for this release).
- Do NOT refactor `_AC_RAMP_BUTTON_SPECS` beyond adding the new entry — keep the existing prefix scheme intact.
- Do NOT add LTS history continuity work for new button entities (buttons have no measurable state).

---

## 13. BUILD-TIME APPENDIX (filled by builder)

**Builder writes this section BEFORE writing Group C code.** Output of §4 live probe lives here.

### Live skip-reason probe result

**Filed 2026-05-29 by build agent.**

Build-time live probe attempts (in order):

1. `curl http://homeassistant.local:8123/api/states/sensor.ura_energy_coordinator_dynamic_preset_overrides_applied` — failed: `Could not resolve host`.
2. `curl http://192.168.13.13:8123/api/` — reachable but returned `401: Unauthorized` (no token in build agent shell context).
3. `mcp__home-assistant__ha_get_state` — the MCP `home-assistant` server is registered as an available resource, but the build agent's shell context cannot invoke MCP tools directly; only the orchestrating parent agent can. No token-bearing alternative was reachable from the sandbox.

**Outcome:** Live `attributes.skipped_zones_with_reason` UNKNOWN at build time. Per planning §4 explicit rule — *"If the live attr is empty (no zones skipped): Group C ships as documentation-only — adds Tier 2-DB Reviewer C check that the 6-reason taxonomy is exercised by tests but no production fix lands. This is acceptable; do NOT invent a fix that's not pointed-to by the live data."* — the same conservative branch is taken when the attr is unobservable, NOT when an arbitrary guess is fabricated. CLAUDE.md "No Fabrication" rule reinforces this: with no live data, the only honest action is tests-only.

### Targeted Group C fix

**None (tests-only).** Production code for Group C is unchanged. All 7 reason literals from the v4.7.7 B2 taxonomy (5 from `dynamic_preset.py` + 2 caller-side reasons from `energy.py`) are exercised by `TestD3SkipReasonTaxonomyCoverage`. Behavioral mirror tests `TestD3BehavioralEasyReasons` exercise `gate_disabled` and `no_forecast_delta` (the 2 reasons reachable without PresetManager + Zone Manager).

Live-validation step (Review D) MUST re-probe the live sensor post-deploy. If a reason surfaces with non-trivial count, file v4.7.11 follow-up cycle scoped to that reason per the §4 candidate-fix table.

### Estimated LoC for chosen fix

0 production LoC for D3 (tests-only). Test file: ~620 LoC across 56 tests covering D1 / D2 / D3 plus the parallel-merge-audit guardrails.

---

## 14. Size Estimate

| Surface | Production LoC | Test LoC |
|---|---|---|
| Group A — `force_ac_reset` button + arrester method | ~35 | ~70 |
| Group A — `strings.json` + `translations/en.json` | ~8 | (no tests) |
| Group B — `SIGNAL_DPM_SKIP_REASONS_UPDATED` + edge detection + sensor subscription | ~25 | ~70 |
| Group C — root-cause fix (build-time, ≤30 LoC budget) | ≤30 | ~60 (covers all 6 reason paths) |
| **Total** | **~80–100 LoC** | **~200 LoC** |

Within the user-specified envelope (~80-120 LoC production + ~150-200 LoC tests). Tier 2-DB test count inflated vs Tier 1 by ~30%, consistent with framing.

---

## 15. Plan Completion Tracking

To be filled out at end of cycle (MANDATORY per CLAUDE.md). Template:

| Planned item | Status | Notes |
|---|---|---|
| D1 — Group A force_ac_reset button | (built / partial / deferred) | |
| D1 — Group A arrester wrapper method | (built / partial / deferred) | |
| D1 — Group A strings + translations | (built / partial / deferred) | |
| D2 — Group B signal constant | (built / partial / deferred) | |
| D2 — Group B edge detection in energy.py | (built / partial / deferred) | |
| D2 — Group B sensor subscription | (built / partial / deferred) | |
| D3 — Group C root-cause fix | (built / partial / deferred) | If deferred to v4.7.11, link the follow-up planning doc |
| D3 — all-6-reasons test coverage | (built / partial / deferred) | Must ship regardless of D3 fix shipping |
| 5 pre-deploy zero-bugs gates | (passed / failed / skipped) | |
| Tier 2-DB review pass A | (clean / fixed N findings) | |
| Tier 2-DB review pass B | (clean / fixed N findings) | |
| Tier 2-DB review pass C | (clean / fixed N findings) | |
| Live validation (Review D) | (clean / failed N checks) | |

---

## 16. References

- v4.7.7 README: `docs/readmes/README_v4.7.7.md` §A1–B3 + §11 (matrix cells)
- v4.7.7 code-review doc: `docs/reviews/code-review/v4.7.7_*.md` Reviewer B-M1 finding
- CLAUDE.md § Review Protocol § Tier 2-DB
- CLAUDE.md § Pre-Deploy Zero-Bugs Gate (5 gates)
- QUALITY_CONTEXT.md Bug Classes #20, #38, #42, #43, #45, #46
- v4.5.11 / v4.5.21 — `_ACRampButton` + prefix scheme precedent (`button.py:582-803`)
- v4.7.7 B2 — skip-reason taxonomy (`energy.py:2680-2810`, `dynamic_preset.py:evaluate_with_reason`)
