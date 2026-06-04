# PLANNING v4.7.6.1 — Labels, Helper Text, and `excess_solar_soc` Number Promotion

**Tier:** Tier 1 hotfix-sized cycle (single staff-engineer reviewer).
**Successor to:** v4.7.6 (LIVE 2026-05-29).
**Branch:** `feature/v4.7.6.1-labels-helpers-excess-solar-number` off `develop`.
**Trigger:** Reviewer D live-validation discrepancy + LOW-only deferrals from v4.7.6 §11. README and plan implied `excess_solar_soc` was a live-tunable Number entity; in practice it is still a config-flow-only field read from `entry.options` at `energy.py:236`. Same cycle picks up the user-confirmed Pause/Resume friendly-name framing and helper-text gaps surfaced in live use.

---

## 1. Background

v4.7.6 promoted `fill_priority_soc` to a live Number entity (`number.ura_energy_coordinator_fill_priority_soc`, default 80, min 50, max 95, step 5) but left its sibling `excess_solar_soc` as a config-flow-only seed. The Reviewer D doc records the discrepancy at §"Discrepancies vs Plan / README" and recommends a small UX-only follow-up cycle.

Three orthogonal UX gaps surfaced in the same window:

1. The three EV-SOC Number entities share the device page but have inconsistent friendly-name framing. User-confirmed wording (2026-05-29) standardizes around the **Pause / Resume** verb pair so the asymmetric threshold pair reads as a single concept on the device page.
2. The `coordinator_energy` config step has helper text for `energy_fill_priority_soc` and `energy_excess_solar_soc` already in `strings.json` (`data_description` block at lines 904-913), but the wording predates the v4.7.6 hybrid `self_modulates` semantics and does not cross-reference the EVSE Force-Charge button or the EVSE Solar-Aware Charging master switch the way the post-review docs say it should.
3. The dynamically-injected `<evse_id>_self_modulates` and `<plug_entity_id>_self_modulates` checkboxes render with the raw field key when HA cannot find a translation. The known EVSE keys (`garage_a_self_modulates`, `garage_b_self_modulates`) already have label + helper text. Dynamic per-plug keys do not — and a dead `l1_plug_self_modulates` block (from before v4.7.6 fix-up C-H2 split per-plug) still lives in `strings.json` + `translations/en.json` per v4.7.6 README plan §11.

All four are UX-only fixes. No gating logic changes. No DB schema changes. No `unique_id` changes. No `entity_id` changes on existing entities.

---

## 2. Scope Summary

| Deliverable | Surface | LoC est (prod) | LoC est (test) |
|---|---|---|---|
| D1 | `ExcessSolarSOCNumber` class + EC accessor/setter + `__init__.py` wire-up + tick-snapshot at decision tick | ~80 | ~110 |
| D2 | Friendly-name updates for 3 Numbers | ~6 (3 `_attr_name` strings) | ~12 (entity-name assertions) |
| D3 | `data_description` text updates for 4 config-flow fields + 1 switch | ~40 (strings.json + en.json deltas) | ~30 (translation-key presence tests) |
| D4 | Per-plug `self_modulates` label fallback + dead translation cleanup | ~20 | ~25 |
| **Total** | | **~120** | **~150-180** |

Within the 80-120 / 150-200 envelope in the directive. Confirmed against the actual files read (no surprise sites).

---

## 3. Files Changed

### Production
- `custom_components/universal_room_automation/number.py` — add `ExcessSolarSOCNumber` (mirrors `FillPrioritySOCNumber` exactly, incl. B-M7 `_safe_unsub` guard). Rename three `_attr_name` strings.
- `custom_components/universal_room_automation/__init__.py` — N/A. Actual platform wire-up of the new Number happens in `number.py::async_setup_entry` for the Coordinator Manager entry, alongside `FillPrioritySOCNumber` at `number.py:61`.
- `custom_components/universal_room_automation/domain_coordinators/energy.py` — add `excess_solar_soc` property + `set_excess_solar_soc` setter; snapshot `_excess_solar_soc` once per tick at decision-tick block start (mirrors v4.7.6 fix-up B-M3 for `_fill_priority_soc`); replace direct `self._excess_solar_soc` read at line 2192 with the snapshot.
- `custom_components/universal_room_automation/strings.json` — D2 entity-name block under `entity.number.*`, D3 `data_description` rewrites in `options.step.coordinator_energy.data_description`, D4 generic per-plug helper block + dead `l1_plug_self_modulates` cleanup.
- `custom_components/universal_room_automation/translations/en.json` — mirror of all `strings.json` changes (HA reads `translations/en.json` for the en locale; `strings.json` is the source-of-truth for HA's translation tooling but `en.json` is what ships).

### Tests (new file)
- `quality/tests/test_v4761_labels_helpers_excess_solar_number.py` — verification tests for D1 round-trip, D2 friendly names, D3 translation-key presence, D4 dead-key absence.

### Reference files read (no edits)
- `custom_components/universal_room_automation/domain_coordinators/energy_const.py` — `CONF_ENERGY_EXCESS_SOLAR_SOC` (line 401), `DEFAULT_EXCESS_SOLAR_SOC_THRESHOLD = 95` (line 396) already exist. No new constants needed.
- `custom_components/universal_room_automation/config_flow.py` — schema range for the existing `coordinator_energy` field is `min=80, max=100, step=1` (lines 3486-3494). D1's Number entity adopts the same range for parity.
- `custom_components/universal_room_automation/domain_coordinators/signals.py` — `SIGNAL_ENERGY_ENTITIES_UPDATE` already exists and is the same signal `FillPrioritySOCNumber` uses for its deferred-retry push.

---

## 4. Deliverable Details

### D1 — Promote `excess_solar_soc` to a live Number entity

**What:** Add `ExcessSolarSOCNumber` mirroring `FillPrioritySOCNumber` line-for-line. New entity: `number.ura_energy_coordinator_excess_solar_soc`. Slider, %, range matches the existing config-flow field (min 80, max 100, step 1 — verified against `config_flow.py:3486-3494`).

**Class shape (in `number.py`, place immediately after `FillPrioritySOCNumber`):**

- `_attr_has_entity_name = True`
- `_attr_icon = "mdi:battery-arrow-down"` (distinct from `mdi:battery-arrow-up` on FillPriority)
- `_attr_native_step = 1`
- `_attr_native_min_value = 80`
- `_attr_native_max_value = 100`
- `_attr_native_unit_of_measurement = "%"`
- `_attr_mode = NumberMode.SLIDER`
- `_attr_entity_category = EntityCategory.CONFIG`
- `_attr_unique_id = f"{DOMAIN}_energy_excess_solar_soc"` — stable; first install.
- `_attr_name = "Resume EV at Battery SOC"` (per D2 user-confirmed wording — set directly in this new entity, no rename ceremony needed since it's brand-new).
- `_attr_device_info` — `(DOMAIN, "energy_coordinator")` identifier, same DeviceInfo block as FillPriority.
- Constructor signature `__init__(self, hass, entry, default: int = 95)`.
- Seed from `entry.options.get(CONF_ENERGY_EXCESS_SOLAR_SOC, DEFAULT_EXCESS_SOLAR_SOC_THRESHOLD)` (default 95).
- `async_added_to_hass` exact mirror of FillPriority lines 858-896 including the v4.7.6 fix-up B-M7 `_safe_unsub` one-shot guard.
- `async_set_native_value` pushes to coordinator via `energy.set_excess_solar_soc(self._value)`.

**EC accessor + setter (in `energy.py`, place immediately after `set_fill_priority_soc` at line 3821):**

```python
@property
def excess_solar_soc(self) -> int:
    """Current EV excess-solar turn-ON SOC threshold (v4.7.6.1 D1)."""
    return self._excess_solar_soc

def set_excess_solar_soc(self, value: int) -> None:
    """Update EV excess-solar turn-ON SOC threshold at runtime (v4.7.6.1 D1).

    Slider write goes through here; takes effect on next decision tick via
    the tick-snapshot at _async_evaluate_dynamic_presets.
    """
    self._excess_solar_soc = int(value)
    _LOGGER.info("EV excess-solar SOC threshold set to %d%%", int(value))
```

**Bug Class #14 + #45 mitigation — tick-snapshot.** `_excess_solar_soc` is currently read directly at `energy.py:2192` inside the per-tick actuation block. After D1 lands, that read can race with `set_excess_solar_soc` mid-tick (same shape as the v4.7.6 B-M3 fix for `_fill_priority_soc`). Modify the snapshot block at lines 2144-2152 to capture both values:

```python
# v4.7.6.1 D1: snapshot excess_solar_soc too. Same race as
# fill_priority_soc post-v4.7.6 — now that there is a setter, the
# decision-tick read must be a snapshot.
fill_priority_soc_tick = int(self._fill_priority_soc)
excess_solar_soc_tick = int(self._excess_solar_soc)
```

Then at line 2192, replace `soc_threshold=self._excess_solar_soc` with `soc_threshold=excess_solar_soc_tick`.

**`__init__.py` wire-up:** Add `ExcessSolarSOCNumber(hass, entry, 95)` to the CM-entry entities list in `number.py::async_setup_entry`, immediately after `FillPrioritySOCNumber(hass, entry, 80)` at line 61. (The "CM entry" path is correct — `FillPrioritySOCNumber` already lives there even though its DeviceInfo points to the EC device. The CM entry is where all cross-coordinator Number entities are seeded.)

**RestoreEntity round-trip:** Mirrors FillPriority. RestoreEntity is the canonical runtime store; `entry.options` is the install-time seed only (per `feedback_ura_mirror_pattern`). Restored value flows in via `async_added_to_hass` → `_value` → first deferred or immediate `_push_to_coordinator()` → `set_excess_solar_soc`.

### Acceptance Criteria
- **Verify:** `number.ura_energy_coordinator_excess_solar_soc` exists post-restart with `state=95, min=80, max=100, step=1, unit=%`.
- **Verify:** Setting the slider to 90 logs `"EV excess-solar SOC threshold set to 90%"` and `EnergyCoordinator.excess_solar_soc == 90` within one decision tick.
- **Verify:** Setting the slider, then restarting HA, restores 90 (not the entry.options seed 95) via RestoreEntity.
- **Verify:** Setting the slider mid-tick does not produce a mixed-threshold read between the L2 EVSE `determine_excess_solar_actions` call (line 2190) and any other reader — both read `excess_solar_soc_tick`.
- **Sensor:** `sensor.ura_energy_coordinator_ev_charging_status` attribute `fill_priority_target_soc` continues to report `_fill_priority_soc` (no regression).
- **Test:** `test_excess_solar_soc_number_entity_exists`, `test_excess_solar_soc_round_trip_through_setter`, `test_excess_solar_soc_restore_entity`, `test_excess_solar_soc_tick_snapshot_used_at_line_2192`, `test_excess_solar_soc_safe_unsub_guard` (mirror v4.7.6 B-M7 test for FillPriority).
- **Live:** Post-restart on the user's HA, query `number.ura_energy_coordinator_excess_solar_soc` via MCP; confirm state=95 (or restored), entity registry entry present, unit %. Adjust the slider, observe the EC `_excess_solar_soc` attribute reflect within one tick.

---

### D2 — Friendly-name updates for 3 EV-SOC Numbers (Pause / Resume framing)

**What:** User-confirmed (2026-05-29) friendly-name standardization on the EC device page. The three EV-SOC sliders now read as a coherent Pause / Resume / Floor triple.

| `unique_id` (UNCHANGED) | Current `_attr_name` | New `_attr_name` |
|---|---|---|
| `ura_energy_fill_priority_soc` | `"Fill Priority SOC"` (line 824) | `"Pause EV Until Battery SOC"` |
| `ura_energy_excess_solar_soc` | — (NEW per D1) | `"Resume EV at Battery SOC"` |
| `ura_energy_ev_battery_drain_soc` | `"EV Battery Drain SOC"` (line 697) | `"EV Drain-Protection SOC Floor"` |

**Implementation:** Since these entities use `_attr_has_entity_name = True` + `_attr_name = "..."` directly (no `_attr_translation_key`), the friendly-name change is a one-line edit per class. No translation-key plumbing required, no `strings.json` `entity.number.*` keys needed. (Verified: the existing `entity.number.*` block in `strings.json` does not currently include these unique_ids — only `entity.switch.ev_tou_management` exists at line 1659.)

**`unique_id` stability is mandatory:** `f"{DOMAIN}_energy_ev_battery_drain_soc"` and `f"{DOMAIN}_energy_fill_priority_soc"` MUST remain byte-for-byte the same so HA's entity_registry keeps the existing entity_ids and any user customizations. Only `_attr_name` changes.

**Why not translation keys?** Adding `_attr_translation_key` retroactively would change the device-page sort behavior (HA sorts via `Intl.Collator(numeric: true)` on the rendered name; switching name source from `_attr_name` to translated name is a no-op for sort but introduces a config-flow regression risk for no benefit on this Tier 1 cycle). Stay with `_attr_name`.

### Acceptance Criteria
- **Verify:** EC device page shows three entries:
  - "URA: Energy Coordinator Pause EV Until Battery SOC" (was Fill Priority SOC)
  - "URA: Energy Coordinator Resume EV at Battery SOC" (new)
  - "URA: Energy Coordinator EV Drain-Protection SOC Floor" (was EV Battery Drain SOC)
- **Verify:** `entity_id` for the two pre-existing entities unchanged.
- **Verify:** `unique_id` for all three is stable.
- **Test:** `test_fill_priority_friendly_name_pause_until`, `test_ev_battery_drain_friendly_name_floor`, `test_excess_solar_friendly_name_resume_at`, `test_fill_priority_unique_id_stable`, `test_ev_battery_drain_unique_id_stable`. (Use the same import pattern as v4.7.6 cycle tests in `quality/tests/`.)
- **Live:** Query `state_attr('number.ura_energy_coordinator_fill_priority_soc', 'friendly_name')` via MCP — expect `"URA: Energy Coordinator Pause EV Until Battery SOC"`.

---

### D3 — Helper text (`data_description.*`) in config flow

**What:** Rewrite the four existing `data_description` entries in `strings.json` + `translations/en.json` at lines 907-913 to match the v4.7.6 hybrid semantics + cross-reference the master switch and Force-Charge button. Add helper text to the EVSE Solar-Aware Charging switch entity description.

**Target keys + new copy (insert/replace in `options.step.coordinator_energy.data_description`):**

```jsonc
{
  "energy_fill_priority_soc": "When battery is BELOW this percentage and solar forecast is healthy, URA pauses EV+L1 charging so the battery can fill first. Default 80%. Range 50-95%. Pair with the Excess Solar threshold (the upper bound) for asymmetric battery-first / solar-surplus behavior.",
  "energy_excess_solar_soc": "When battery is ABOVE this percentage AND solar surplus is available, URA turns EV+L1 charging ON even during off-peak pause. Default 95%. Use the EV-Drain-Protection SOC Floor for the lower bound.",
  "energy_ev_battery_drain_soc": "When the home battery falls below this SOC AND is actively discharging AND EV is charging, URA pauses EV+L1 to protect battery reserve. Default 80%. Last-resort safety net — fill-priority normally engages first.",
  "energy_excess_solar_enabled": "Master toggle for both the SOC-based pause-until rule and the SOC-based turn-on rule. Off-peak TOU and battery-drain protection run independently."
}
```

**Default-value note in `energy_ev_battery_drain_soc`:** The directive copy says "Default 80%" for this field. The actual code default is `DEFAULT_EV_BATTERY_DRAIN_SOC_THRESHOLD = 50` (`energy_const.py:405`). **Decision:** use the directive copy verbatim ("Default 80%") since the user authored the helper-text wording knowing the live deploy. The 80 likely reflects the user's *current configured value* rather than the install-default. Builder must NOT change the constant. Reviewer should flag if the discrepancy is unintended — Tier 1 reviewer call.

**EVSE TOU Management switch (`switch.ura_energy_coordinator_ev_tou_management`):** v4.7.6 §D6.2 already added the description block at `strings.json:1659-1662`. D3 verifies this landed correctly post-deploy — no edit needed unless the live HA UI is missing it. Builder reads strings.json lines 1657-1665 and confirms presence; no-op if present.

**EVSE Solar-Aware Charging switch (`switch.ura_energy_coordinator_evse_solar_aware_charging`):** No `entity.switch.evse_solar_aware_charging` block exists in `strings.json` today. The form-side helper at line 904 (`energy_excess_solar_enabled`) covers the field in the config-flow form, but the **switch entity card on the EC device page** has no description. D3 adds an `entity.switch.evse_solar_aware_charging` block:

```jsonc
{
  "entity": {
    "switch": {
      "evse_solar_aware_charging": {
        "name": "EVSE Solar-Aware Charging",
        "description": "Master toggle for both the SOC-based pause-until rule and the SOC-based turn-on rule. Off-peak TOU and battery-drain protection run independently."
      },
      "ev_tou_management": { /* existing block */ }
    }
  }
}
```

(Translation key for switches without `_attr_translation_key` is the entity object_id. Reviewer must verify that the actual `_attr_translation_key` on the renamed switch matches `evse_solar_aware_charging`; if it uses `_attr_name` instead, the `entity.switch.*` block is a no-op and the description belongs on the form-side instead. Builder reads `switch.py` for the renamed entity's name/translation source before committing to the key. Source-of-truth probe: `Grep "evse_solar_aware_charging"` in `switch.py`.)

### Acceptance Criteria
- **Verify:** Opening the Energy Coordinator options flow and hovering each of the four fields shows the new helper text.
- **Verify:** No untranslated keys remain in the form (translation-key presence tests catch this).
- **Test:** `test_d3_fill_priority_helper_text_present`, `test_d3_excess_solar_helper_text_present`, `test_d3_ev_drain_helper_text_present`, `test_d3_master_toggle_helper_text_present`, `test_d3_strings_en_in_sync` (parses both files, asserts identical `data_description` blocks).
- **Live:** Open config flow → coordinator_energy step → screenshot or MCP-probe the form schema. (Cannot programmatically probe HA's rendered form description text via the REST API, so this is a manual visual check post-deploy.)

---

### D4 — Per-plug `self_modulates` label + dead translation cleanup

**What:** Two sub-tasks.

**D4a — Add a generic explainer that surfaces above the dynamically-injected per-plug `self_modulates` checkboxes.**

HA's translation lookup for field labels: if `options.step.<step>.data.<field_key>` is missing, the form renders the raw key (e.g., `switch.smartplug_moes_wifi_garagealeftfront_socket_2_self_modulates`) which is hostile. Per-plug keys are dynamic, so a per-key translation entry per plug is impossible (the plug entity_id isn't known at translation-file authoring time).

**Approach (preferred — generic data_description on a new sentinel field):** the existing checkboxes for `garage_a_self_modulates` and `garage_b_self_modulates` already have label + helper text. For the per-plug checkboxes, accept the raw-key label fallback for the field name (the plug entity_id is recognizable to the user) but add a single shared helper-text key that surfaces the convention. Concretely: add a `description` key at the `step` level in `strings.json` for `coordinator_energy` that explains the per-plug pattern in one sentence.

**Approach (alternate — `data_description` on each known field, leave dynamic labels raw):** keep the existing `garage_a_self_modulates` / `garage_b_self_modulates` data_description blocks but rewrite them with the user-confirmed copy (covers both EVSE and L1-plug paths via a single sentence). Per-plug rows fall back to raw-key labels with the same description because HA renders form-step description above all fields.

**Final call (Tier 1 builder):** go with the alternate. Rewrite both EVSE `self_modulates` helper texts to the user-confirmed wording. Per-plug keys remain visible as raw keys (this is recoverable in a future cycle by adding `data_description` lookup-by-suffix at form-render time, out of scope here).

Replace the existing entries at `strings.json:908-910` and the en.json mirror:

```jsonc
{
  "garage_a_self_modulates": "Check this for smart EVSEs/plugs with native solar or schedule modes (Emporia, Tesla Wall Connector). URA re-pauses every cycle; use the EVSE Force-Charge button to override. Leave unchecked for any other hardware — URA detects real user toggles and backs off for 1 hour.",
  "garage_b_self_modulates": "Check this for smart EVSEs/plugs with native solar or schedule modes (Emporia, Tesla Wall Connector). URA re-pauses every cycle; use the EVSE Force-Charge button to override. Leave unchecked for any other hardware — URA detects real user toggles and backs off for 1 hour."
}
```

**D4b — Remove dead `l1_plug_self_modulates` keys** (per v4.7.6 README §11 and Reviewer C-H2 fix). The field was split into per-plug keys in v4.7.6; the single-flag translation entries still live at `strings.json:854` (label) and `strings.json:910` (data_description), and in `translations/en.json` at the matching lines. Delete both keys from both files.

**Test guard against regression:** add `test_d4_l1_plug_self_modulates_translation_keys_absent` asserting neither file contains the dead key.

### Acceptance Criteria
- **Verify:** `garage_a_self_modulates` and `garage_b_self_modulates` helper text in the config-flow form matches the user-confirmed wording verbatim.
- **Verify:** `l1_plug_self_modulates` does not appear in either `strings.json` or `translations/en.json`.
- **Verify:** Per-plug checkboxes still render in the form (the dynamic injection at `config_flow.py:3628-3642` is untouched).
- **Test:** `test_d4_garage_a_helper_text_matches_spec`, `test_d4_garage_b_helper_text_matches_spec`, `test_d4_l1_plug_self_modulates_translation_keys_absent`.
- **Live:** Open config flow → coordinator_energy step → confirm helper text below the `garage_a self-modulates` checkbox reads the new copy. Confirm per-plug rows still appear.

---

## 5. Bug-Class Checklist

| Class | Verdict | Notes |
|---|---|---|
| #11 (UTC vs local tz) | N/A | No date arithmetic in this cycle. |
| #14 (config snapshot staleness) | **Mitigated in D1.** Tick-snapshot of `_excess_solar_soc` added at the actuation block start (`energy.py:2152` region) so the slider write takes effect on the next decision tick, not "whenever the next coordinator re-init happens." Mirrors v4.7.6 fix-up B-M3 exactly. |
| #45 (lambda closure stale local) | **Mitigated in D1.** B-M7 `_safe_unsub` pattern carried over from `FillPrioritySOCNumber` (`number.py:758-782`). New `ExcessSolarSOCNumber.async_added_to_hass` uses identical one-shot guard wrapping the dispatcher unsub. |
| #46 (`async_update_entry` re-entrancy) | N/A | No `async_update_entry` calls. No entry shape changes. Only entity additions + translation file edits + `_attr_name` edits. |
| #47 (lazy canonical resolution UI surface violation) | N/A | Zone Manager not touched. |

---

## 6. Reviewer Framing (Tier 1 — single review)

**Reviewer focus areas, explicitly:**
1. **RestoreEntity round-trip for `ExcessSolarSOCNumber`** — verify the dispatcher-defer path mirrors FillPriority exactly, including B-M7 `_safe_unsub` guard. No double-unsub.
2. **`data_description` keys appear in the right schema step** — `options.step.coordinator_energy.data_description` is the only block being edited; verify HA's form-render path picks these up for the correct step. Source-of-truth: `config_flow.py::async_step_coordinator_energy` returns `step_id="coordinator_energy"` at line 3647; matches.
3. **Friendly names render verbatim** — `_attr_name` is the source; no translation-key indirection. The three new strings must match the directive copy character-for-character.
4. **No regression in v4.7.6 fill-priority rule behavior** — `_fill_priority_soc` tick-snapshot, `_paused_by_fill_priority` set, NM trip path all untouched. Reviewer spot-checks that the snapshot block at lines 2144-2152 still produces `fill_priority_soc_tick` and that the new `excess_solar_soc_tick` is additive.
5. **Translation-string cleanup doesn't break any HA UI lookup** — verify no `l1_plug_self_modulates` references remain anywhere in `custom_components/universal_room_automation/` (grep both code and translation files). The field was removed from the schema in v4.7.6 fix-up C-H2; only dead translation strings remain.

**Tier-1 single-reviewer rationale:** Hotfix-sized, UX-only, no DAO touches, no gating-logic touches, no entry shape changes, no `unique_id` changes. The largest correctness risk (D1's tick-snapshot for excess_solar_soc) is a direct copy of a v4.7.6-reviewed pattern.

---

## 7. Pre-Deploy Zero-Bugs Gate

Per `feedback_pre_deploy_zero_bugs_gate.md` — MANDATORY before `./scripts/deploy.sh`:

1. **Conflict markers:** `Grep "^<<<<<<< |^======= |^>>>>>>> "` across the changed paths must return zero.
2. **`py_compile`:** `python3 -m py_compile custom_components/universal_room_automation/number.py custom_components/universal_room_automation/domain_coordinators/energy.py` must succeed.
3. **JSON validity:** `python3 -c "import json; json.load(open('custom_components/universal_room_automation/strings.json')); json.load(open('custom_components/universal_room_automation/translations/en.json'))"` must succeed. (New gate-step warranted because this cycle edits JSON files; broken JSON would silently kill HA's translation lookup for the entire integration.)
4. **Cycle tests:** `PYTHONPATH=quality python3 -m pytest quality/tests/test_v4761_labels_helpers_excess_solar_number.py -v` must show all passing.
5. **Full-suite vs baseline:** `pre-review-v4.7.6.1` tag against `HEAD` — zero new failures relative to `pre-review-v4.7.6` baseline (4197 / 55 / 14).

---

## 8. Tagging + Branch Discipline

- Branch: `feature/v4.7.6.1-labels-helpers-excess-solar-number` off `develop`.
- Pre-review tag: `pre-review-v4.7.6.1` at the moment build is declared complete.
- Post-review-fix tag (if any fixes): commit on the same branch, no new tag (Tier 1 single-review).
- Deploy via `./scripts/deploy.sh 4.7.6.1 "Labels + helpers + excess_solar_soc Number" "<release notes>"` — per `feedback_version_prefix.md`, no `v` prefix.
- README required: `docs/readmes/README_v4.7.6.1.md` before deploy.

---

## 9. Live Validation (Post-Deploy)

After HACS install + HA restart:
1. **D1:** `number.ura_energy_coordinator_excess_solar_soc` exists, state=95 (or restored), min=80, max=100, step=1, unit=%.
2. **D1:** Slider write at 90 → `EnergyCoordinator.excess_solar_soc == 90` within one decision tick.
3. **D2:** All three friendly names render verbatim on the EC device page.
4. **D3:** Open config flow → coordinator_energy step → all four helper texts present (manual visual; no programmatic probe).
5. **D4:** Per-plug checkboxes render (raw-key fallback acceptable). Garage A/B helper text reads new copy. No `l1_plug_self_modulates` row appears.
6. **No regressions:** `sensor.ura_energy_coordinator_ev_charging_status` still publishes the 7 D4 attrs from v4.7.6. `paused_by_fill_priority` still engages under the same conditions. `ec_ready_at` still populated. Zero new URA ERROR logs.

---

## 10. Non-Goals (Explicit)

- No coordinator-merge / canonical-resolution changes (v4.7.5 territory).
- No grid-import-cap behavior changes.
- No new gating rules — UX-only + the one missed Number entity.
- No changes to switch `unique_id` or `entity_id`. Only friendly names + helper text.
- No HACS history migrations.
- No `_attr_translation_key` introduction for the three Numbers (`_attr_name` stays the surface — see D2 rationale).
- No new `CONF_*` / `DEFAULT_*` constants — D1 reuses `CONF_ENERGY_EXCESS_SOLAR_SOC` + `DEFAULT_EXCESS_SOLAR_SOC_THRESHOLD`.
- No edits to `__init__.py` — D1 wire-up happens in `number.py::async_setup_entry` alongside `FillPrioritySOCNumber`.
- No backward-compat alias for the new Number's entity_id — first install, no alias warranted.

---

## D5 — Manual Updates (user-added 2026-05-29 post-plan-v1)

User-confirmed scope addition mid-planning: "update the manuals." Helper-text-discipline also locked: **helpers carry mechanics, READMEs carry rationale.**

### D5.1 — Retroactive correction to `README_v4.7.6.md`

The v4.7.6 README's D3 section implied `excess_solar_soc` was already a live Number entity. It was not — it was a config-flow-only field at `entry.options`. Patch the relevant paragraph in `docs/readmes/README_v4.7.6.md` with a footnote pointing at v4.7.6.1: *"Note (corrected 2026-05-29): `excess_solar_soc` was config-flow-only in v4.7.6; promoted to a live Number entity in v4.7.6.1. The functional rule in v4.7.6 worked correctly via `entry.options`; v4.7.6.1 just exposes the value as a live-tunable Number for parity with `fill_priority_soc`."*

### D5.2 — Write `README_v4.7.6.1.md`

Standard Tier 1 README format. Mirror the structure of `README_v4.7.4.4.md` or similar small hotfix. Sections required:
- Headline summary (4 deliverable groups in 1 line each)
- Per-deliverable detail
- **Asymmetric-defaults rationale** (the deep dive): why FP=80 / ES=95 / Drain=50 — explains the 15-point dead band, boundary-oscillation risk at symmetric=95/95, and Drain's role as a "deep floor" safety net behind FP. Pair with concrete walkthrough at FP=80/ES=95/Drain=50 — what happens at SOC=30, 60, 85, 90, 95.
- "Why your live Drain=80 stays" note — RestoreEntity preserves the user's manual setting across deploy; the code-default change to 50 affects only fresh installs.

### D5.3 — Resolution of §11 "Default 80% vs 50%" ambiguity

Confirmed user intent 2026-05-29: keep `DEFAULT_EV_BATTERY_DRAIN_SOC_THRESHOLD = 50` in code. Helper-text reads "Default 50%." User's live value of 80 persists via RestoreEntity. The 50 default is the "deep floor safety net behind fill-priority" rationale per D5.2 README.

### D5.4 — Helper-text length discipline

Each `data_description.*` entry in strings.json/en.json MUST follow this template:

> *"\<one sentence: what triggers the action\>. Default \<N\>%. Range \<min-max\>. \<one sentence: pair/interaction hint OR a 'See README' lookup if the rationale is non-trivial\>."*

Maximum 3 sentences. No prose paragraphs. If the explanation would exceed 3 sentences, push the depth into the README and reference it. The four target entries:

- **`energy_fill_priority_soc`:** *"When battery is BELOW this percentage and solar forecast is healthy, URA pauses EV+L1 charging so the battery fills first. Default 80%. Range 50–95%. Pair with the Resume EV at Battery SOC threshold (default 95) for an asymmetric dead band."*
- **`energy_excess_solar_soc`:** *"When battery is ABOVE this percentage AND solar surplus is available, URA turns EV+L1 charging ON even during off-peak pause. Default 95%. Range 80–100%. Pair with the Pause EV Until Battery SOC threshold (default 80)."*
- **`energy_ev_battery_drain_soc`:** *"When the home battery is actively discharging below this SOC AND EV+L1 is charging, URA pauses to protect battery reserve. Default 50% (deep floor behind Pause EV Until Battery SOC). Range 5–95%. See README_v4.7.6.1 for the asymmetric-defaults rationale."*
- **`energy_excess_solar_enabled` (the switch's description, if applicable):** *"Master toggle for both the SOC-based pause-until rule and the SOC-based turn-on rule. Off-peak TOU pause and battery-drain protection run independently."*

### D5 — Acceptance Criteria
- **Verify:** `docs/readmes/README_v4.7.6.md` contains the corrective footnote at the `excess_solar_soc` mention.
- **Verify:** `docs/readmes/README_v4.7.6.1.md` exists with all 4 sections (headline, deliverables, asymmetric-defaults rationale, "your live Drain=80 stays" note).
- **Verify:** All 4 `data_description.*` blocks match the template (3 sentences max, default values match code constants).
- **Verify:** `DEFAULT_EV_BATTERY_DRAIN_SOC_THRESHOLD` stays at 50 in `energy_const.py`.
- **Live:** After deploy + restart, helper text renders in HA UI's options flow under each Number's edit affordance (where applicable).

---

## 11. Plan-Completion Tracking

Items the planning doc explicitly defers (per `CLAUDE.md` mandate):

| Item | Why deferred | Where tracked |
|---|---|---|
| Per-plug `self_modulates` field-label translation (dynamic key resolution) | Out of scope for Tier 1; requires either a config-flow-level translation hook or migrating to a list-selector UI. v4.7.6.1 accepts raw-key labels with a clear shared helper text as the Tier 1 compromise. | New backlog memo `feedback_per_plug_dynamic_translation.md` (filed during build phase). |
| ~~`data_description` for `energy_ev_battery_drain_soc` literally says "Default 80%"~~ | **Resolved 2026-05-29:** code default stays at 50; helper says "Default 50% (deep floor behind Pause EV Until Battery SOC)". User's live value of 80 persists via RestoreEntity. Rationale documented in D5.2 README. | Closed. |
| Switch-entity-card description for `evse_solar_aware_charging` | Included in D3 BUT contingent on the renamed switch using a translation key matching `evse_solar_aware_charging`. If it doesn't, the description is a no-op. Builder verifies during implementation; if no-op, log and defer to v4.7.6.2. | Build-phase verification. |
| Reviewer B's v4.7.6 LOW B-M5/B-M6 (logging on registry mutation failures, narrower `except` in `ev_status`) | Carried over from v4.7.6 close-out. Stable today. | `project_v476_live.md` backlog list. |
| Dashboard nested-attr rendering of `cooldowns` / `pause_dispatch_state` (`[object Object]` risk) | Carried over from v4.7.6 close-out. Dashboard-layer concern. | v4.7.6 README §11. |
| NM-trip DST consideration on the day-token | Carried over from v4.7.6 close-out. Stable until next DST boundary. | v4.7.6 README §11. |
| `entity.number.*` translation-key migration for the three EV-SOC Numbers | Explicitly deferred in D2 rationale (no benefit on Tier 1; risk of regression for no gain). Future cycle if translation work warrants it. | None — design decision. |

---

## 12. Recall

- "Resume v4.7.6.1 — labels + helpers + excess_solar Number"
- "What's the v4.7.6.1 planning doc?"
