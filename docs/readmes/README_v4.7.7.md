# URA v4.7.7 — AC Nudge / AC Reset Decouple + DPM Sensor Cleanup

**Release date:** 2026-05-29
**Tier:** Tier 2 (two parallel staff-engineer reviews, different framings)
**Scope:** A1 new AC Nudge switch (decouples from AC Reset), A2 Gate 0 split, A3 escalation guard, A4 ramp sensor entity-id migration, B1 orphan DPM-active-bucket sweep, B2 per-zone DPM skip-reason taxonomy + new `skipped_zones_with_reason` sensor attribute, B3 DPM sensor device-info unification

**Trigger:**
- Pre-v4.7.7, the single `_ac_reset_enabled` toggle gated BOTH soft-nudge iteration AND hard-reset escalation. Turning AC Reset OFF silently disabled the nudge feature too — surfaced during v4.7.5 live-validation when the user expected nudges to keep running while Reset was held off.
- AC Ramp diagnostic sensors (`ac_ramp_state`, `ac_ramp_last_action`) had zone-name slugs that scrambled across reboots when the canonical-merge ordering changed (e.g., `_back_hallway` displaying "Entertainment + Master Suite"). Confusing for diagnostics; not visible to LTS because neither sensor has `SensorStateClass.MEASUREMENT`.
- DPM diagnostic sensor (`skipped_zones`) reported a list of zone IDs but no reason — operator had to dig through logs to figure out WHY each zone was skipped (gate disabled? unknown bucket? canonical-merge label mismatch? dwell pending?).
- DPM sensors were sprinkled across two different `DeviceInfo` blocks (legacy `dynamic_preset_coordinator` vs canonical HVAC device), so HA's device page split DPM entities awkwardly.

---

## Headline Changes

- **A1** — New `HVACACNudgeSwitch` (RestoreEntity, mirrors `HVACACResetSwitch`). Default ON. Friendly name `26 · AC Nudge`. Deferred-restore via `SIGNAL_HVAC_COORDINATOR_READY`. Sets `override_arrester.ac_nudge_enabled` on the HVAC coord.
- **A2** — Gate 0 split in `hvac_override.check_ac_reset`. Gate 0a: both flags OFF → return. Gate 0b: nudge OFF → return (skip soft-nudge entry). Snapshot semantics: BOTH `_ac_nudge_enabled` and `_ac_reset_enabled` captured into locals at L891-L892 (Bug Class #20 stable-view-per-tick).
- **A3** — `_perform_hard_reset_escalation` early-returns when `_ac_reset_enabled` is False, BEFORE any DB read or `_engage_lockout` call. Fixes the latent `_hard_reset_daily_limit=0` lockout-on-first-eval bug as a side benefit.
- **A4** — Ramp diagnostic sensor entity-id migration (state + last_action). Renames `*_<scrambled_label>_*` slugs to canonical `*_<zone_id>_*` form. Idempotent + slug-collision-guarded. **`kwh_rate` sensor deliberately NOT renamed** because it has `SensorStateClass.MEASUREMENT` and a rename would break LTS history continuity.
- **B1** — Orphan sweep removes stale `dynamic_preset_active_bucket_*` registry entries. Strict-prefix exclusion of live entries. Mutate-during-iterate avoided. Platform-guard for URA only.
- **B2** — Per-zone DPM skip-reason taxonomy. `DynamicPresetOverrideSource.evaluate_with_reason` + `async_evaluate_with_reason` return `(overrides, skip_reason)` tuples. Six in-source reasons plus two caller-side reasons (`canonical_label_mismatch`, `evaluation_failed`). EC captures into `_dynamic_preset_skip_reasons` per-tick. Sensor exposes `skipped_zones_with_reason` attribute alongside back-compat `skipped_zones`.
- **B3** — DPM sensor device-info unified onto the canonical HVAC device via `_hvac_device_info()`. Three sensor classes migrated. Entity-ids preserved → LTS continuity preserved.

---

## Per-Deliverable Detail

### A1 — `HVACACNudgeSwitch`

- `switch.py` class `HVACACNudgeSwitch(SwitchEntity, RestoreEntity)`.
- `unique_id = f"{DOMAIN}_hvac_ac_nudge"`; friendly name `"26 · AC Nudge"`.
- Registered in the CM switch list immediately adjacent to `HVACACResetSwitch`.
- `async_added_to_hass` mirrors `HVACACResetSwitch` line-for-line. Fast path (HVAC coord present at restore): write to `override_arrester.ac_nudge_enabled`. Deferred path (HVAC absent at restore): stash in `self._deferred_value`, wait for `SIGNAL_HVAC_COORDINATOR_READY`, then flush via bound method `_handle_hvac_ready` (Bug Class #42 safe — no lambda).
- `async_on_remove` registers the dispatcher unsub (Bug Class #38 — no untracked unsubs).
- Default state ON for fresh installs (preserves pre-v4.7.7 behavior).
- `strings.json` + `translations/en.json` entries added.

### A2 — Gate 0 split

`hvac_override.check_ac_reset` gating order:

```
0a. _ac_nudge_enabled AND _ac_reset_enabled both False -> return
0b. _ac_nudge_enabled False -> return (soft-nudge entry point has no work)
1. _ramp_master_enabled (v4.5.11 master switch)
... (gates 2-9 unchanged)
```

Snapshot semantics: both flags read into locals at L891-L892 ONE TIME per tick → stable view across the entire method body. Bug Class #20 (concurrent reload race) protected.

### A3 — Escalation guard

`_perform_hard_reset_escalation` early-returns with `zone.ramp_state = AC_RAMP_STATE_IDLE` when `self._ac_reset_enabled` is False. Early return at L1532 PRECEDES the DB-fetch block and the `hard_reset_count >= _hard_reset_daily_limit` check, so:

- NO `_db.save_ac_reset_state` call
- NO `_db.log_ac_ramp_event(lockout_triggered=True)` call
- NO `_engage_lockout` call
- NO DB reads at all

Pre-A3 lockout-on-first-eval bug (`_hard_reset_daily_limit=0` would fire `_engage_lockout` immediately because `0 >= 0` is true) is now harmless. **Live read intentional:** `_ac_reset_enabled` read fresh at L1532 (not snapshotted) so escalation respects the CURRENT toggle, not the toggle at nudge dispatch ~10 min ago. Documented inline (B-L1 fix-up).

### A4 — Ramp diagnostic sensor entity-id migration

`__init__.py` migration block (~L2524-2603):

- Targets `*_ac_ramp_state_*` and `*_ac_ramp_last_action_*`.
- **Excludes `*_ac_ramp_kwh_rate_*`** which has `SensorStateClass.MEASUREMENT` (`sensor.py:9006`) — renaming would break LTS history. Trade-off documented at `__init__.py:2538`.
- Uses `_er.async_update_entity(entity_id, new_entity_id=canonical_slug)`.
- Idempotent (skips if already canonical).
- Slug-collision guard: if canonical slug already held by foreign entity, logs WARNING and skips.
- Bug Class #46 safe: does NOT call `async_update_entry` on the config entry; runs AFTER `async_forward_entry_setups` (L2402) and BEFORE `add_update_listener` (L2605).

### B1 — Orphan DPM-active-bucket sweep

`__init__.py` (~L2481-2521):

- Iterates entity registry for `_dynamic_preset_active_bucket_` substring.
- Strict-prefix exclusion: any entity-id ending with a known canonical `zone_id` is preserved.
- Mutate-during-iterate avoided via materialized `_to_remove` list.
- Platform guard: URA-platform entries only.
- Uses `_er.async_remove(entity_id)`.

### B2 — Per-zone DPM skip-reason taxonomy

**dynamic_preset.py:** new sync `evaluate_with_reason` and async `async_evaluate_with_reason`. Both return `tuple[list[PresetOverride], str | None]`. Async wrapper holds `self._eval_lock` (re-entrancy guard).

In-source skip reasons:

| Reason | Source | Meaning |
|---|---|---|
| `gate_disabled` | `evaluate_with_reason` | Zone not opted in |
| `no_forecast_delta` | `evaluate_with_reason` | WPM delta unavailable |
| `dwell_pending` | `evaluate_with_reason` | Bucket transition gated by dwell timer |
| `unknown_bucket` | `_build_overrides_with_reason` | Bucket boundary lookup returned no match |
| `home_range_not_configured` | `_build_overrides_with_reason` | House preset has no configured target range |

**energy.py:** EC caller captures per-zone reasons into `self._dynamic_preset_skip_reasons: dict[str, str]` (per-tick, replaces wholesale). Two caller-side reasons:

| Reason | Source | Meaning |
|---|---|---|
| `canonical_label_mismatch` | EC caller | Canonical " + " split failed AND zone_id fallback also returned empty data (A-M1 fix-up — gates on `_canonical_resolution_failed and not zone_data`) |
| `evaluation_failed` | EC caller | Exception during eval; zone surfaced rather than silently dropped |

**sensor.py:** `DynamicPresetOverridesAppliedSensor` exposes `skipped_zones_with_reason` as `dict[zone_id, reason]` via `_get_dynamic_preset_skip_reasons` helper. Back-compat `skipped_zones` list preserved. Dict-comprehension keyed by `zone_id` → Bug Class #45 safe.

### B3 — DPM sensor device-info unification

`DynamicPresetActiveBucketSensor`, `DynamicPresetRangeSensor`, `DynamicPresetOverridesAppliedSensor` all use `_hvac_device_info()`. Migration list in `__init__.py` extended with static + per-zone (via `iter_canonical_hvac_zones`) device assignments. Entity-ids preserved → LTS continuity preserved.

---

## Bug Class Regression Check Results

| Class | Surface | Result |
|---|---|---|
| #20 (concurrent reload race) | A2 dual-flag snapshot L891-L892 | CLEAN — locals captured once, zero re-reads |
| #38 (untracked unsub) | A1 deferred-restore `async_on_remove` | CLEAN — dispatcher unsub registered |
| #42 (lambda + async_create_task) | A1 `_handle_hvac_ready` callback | CLEAN — bound method, not lambda |
| #43 (RestoreEntity ordering) | A1 `async_added_to_hass` | CLEAN — `super().async_added_to_hass()` first |
| #44 (cross-coord signal race) | B2 dispatch-only-when-overrides-changed | CLEAN — `_changed` check before dispatcher_send |
| #45 (lambda-closure-over-loop-var) | B2 sensor dict-comp | CLEAN — keyed by `zone_id` |
| #46 (async_update_entry re-entrancy) | A4 + B1 + B3 registry mutations | CLEAN — all three use `_er.*`, none call `async_update_entry` on the entry; placement AFTER L2402 forward-setups, BEFORE L2605 add_update_listener |
| #47 (entity-id slug collision) | A4 rename collision guard | CLEAN — `_er.async_get(canonical_slug)` check before rename |

---

## Live Validation Expectations

Post-restart:

1. **New switch present and ON for fresh installs:** `switch.ura_coordinator_manager_26_ac_nudge` exists, default `on`. Toggle OFF + restart preserves OFF (RestoreEntity).
2. **Gate 0 split visible:** With AC Nudge OFF, DEBUG log `AC Nudge disabled — skipping soft-nudge detection (AC Reset state=...)` on each 5-min tick. With BOTH off, no log (early return).
3. **A3 hard-reset guard:** With AC Reset OFF and a stuck in-flight nudge that times out into `_perform_hard_reset_escalation`, DEBUG log `Hard reset on <zone> skipped — AC Reset feature disabled`. No `_engage_lockout` log, no DB write.
4. **A4 ramp sensor migration:** `sensor.ura_*_ac_ramp_state` and `sensor.ura_*_ac_ramp_last_action` entity-ids end in canonical `<zone_id>`. `sensor.ura_*_ac_ramp_kwh_rate` entity-id UNCHANGED (LTS preserved — intentional residual).
5. **B1 orphan sweep:** Stale `dynamic_preset_active_bucket_*` entries from prior scramble incidents removed; active per-zone DPM bucket sensors unaffected.
6. **B2 new sensor attribute:** `sensor.ura_*_dynamic_preset_overrides_applied` exposes `skipped_zones_with_reason` alongside `skipped_zones`. Within an hour of restart, at least one zone without overrides has a non-empty reason key (e.g., `dwell_pending` after a transition, `gate_disabled` for non-opted zones). **Sentinels-only at `skipped_zones_with_reason` means B2 is not capturing — payload shape broken.**
7. **B3 DPM device unification:** HA device page for canonical HVAC device lists DPM bucket/range/overrides-applied sensors alongside HVAC zone-state sensors. Entity-ids unchanged.

---

## Known Limitations / Deferred Items

- **B-M1 (Reviewer B) — `skipped_zones_with_reason` visible-update lag.** The sensor refreshes only when the overrides dict actually changes (via `SIGNAL_DYNAMIC_PRESET_OVERRIDES_UPDATED` / `SIGNAL_DYNAMIC_PRESET_TRANSITIONED`). If a zone's skip reason changes from one diagnostic label to another (e.g., `gate_disabled` → `home_range_not_configured`) while overrides stay empty both ticks, the sensor attribute stays stale until the next override change. **NOT a bug — diagnostic-sensor staleness is intentional** (one sensor write per tick keeps recorder churn bounded). v4.7.8 may add a dedicated `SIGNAL_DPM_SKIP_REASONS_UPDATED` if user feedback indicates the staleness is confusing.

- **A-L8 (Reviewer A) — AC Ramp kWh-rate sensor entity-ids remain on the legacy zone-name slug.** A4 deliberately did NOT rename `HVACACRampKwhRateSensor` because it has `_attr_state_class = SensorStateClass.MEASUREMENT` and renaming would break LTS history continuity. This is intentional — the trade-off is documented in code at `__init__.py:2538`. Operators with mismatched display labels can accept the residual or drop the LTS history manually via Developer Tools → Statistics.

- **A-M2 (Reviewer A) — Cell (AC Nudge OFF, AC Reset ON) has no triggerable path to `_perform_hard_reset_escalation` in v4.7.7.** Soft-nudge auto-detection is skipped at Gate 0b, and no manual force_reset button exists today. AC Reset is effectively inert in this cell. **Acceptable for v4.7.7** — the user can re-enable AC Nudge to allow escalation. **v4.7.8 candidate:** if user feedback indicates a desire to keep nudges off but trigger a hard reset on demand, add a manual `force_reset` button bridging to `_perform_hard_reset_escalation`. Cell behavior documented inline in `hvac_override.py` docstring + Gate 0b inline comment (A-M2 fix-up).

- **Other LOW deferrals** (Reviewer A): L2 zone.ramp_state preservation on Gate 0b path; L3 `force_nudge` manual path bypasses `_ac_nudge_enabled`; L4 day-rollover skipped when entirely gated off; L5 Gate 0a silent return; L6 docstring precedence clarity; L9 `energy_coordinator` literal in entity_id construction.

- **Other LOW deferrals** (Reviewer B): B-L2 `is_on` returns `True` (default) when HVAC absent but `available=False` (consistent with reference HVACACResetSwitch); B-L3 A4 collision check uses `_er.async_get(entity_id)` (try/except defended); B-L4 A4 silent skip on collision (WARNING logged).

---

## Review Trail (Tier 2 — two parallel reviewers, different framings)

**Reviewer A (correctness + state-machine + B2 root-cause quality):** APPROVE WITH FIXES — 0 CRITICAL / 0 HIGH / 2 MEDIUM / 6 LOW / 3 NIT. State-machine table covered all 4 cells × 7 events. A3 lockout-removal trace clean. Bug Class #20 dual-flag snapshot verified. A4 ramp-sensor migration correctly excludes `kwh_rate`. B1 orphan sweep correct. B2 instrumentation complete modulo A-M1. B3 device migration correct.

**Reviewer B (async + lifecycle + restart resilience + entity-registry safety):** APPROVE WITH FIXES — 0 CRITICAL / 0 HIGH / 1 MEDIUM / 4 LOW / 3 INFO. Bug Class #46 entity-registry mutation placement verified (all three blocks compliant). RestoreEntity lifecycle on the new `HVACACNudgeSwitch` is a faithful mirror of the reference. Async lifecycle sound. Restart resilience preserved. Bug Class #45 dict-comp keyed correctly.

**Combined:** 0 CRITICAL / 0 HIGH across both reviewers. 3 MEDIUMs total (A-M1, A-M2, B-M1) all addressed in fix-up (A-M1 code fix + regression test; A-M2 documentation strike; B-M1 documented as intentional in this README). 4 cheap LOWs landed (A-L7 stale line ref, A-L8 README note, B-L1 TOCTOU comment, plus A-M2 documentation strike).

### Tier 2 Framing Summary

- **Reviewer A — Correctness + state-machine invariants.** Checked: 4-cell × 7-event state matrix, A3 lockout-removal trace, Bug Class #20 dual-flag snapshot, A4 migration correctness (LTS preservation), B1 orphan-sweep targeting (strict-prefix exclusion), B2 taxonomy completeness, B3 device-info uniformity.
- **Reviewer B — Async + lifecycle + restart resilience + entity-registry safety.** Checked: Bug Class #46 placement (entry mutation vs entity mutation), RestoreEntity contract on the new switch, dispatcher unsub tracking (Bug Class #38), bound-method vs lambda (Bug Class #42), TOCTOU on live-read of `_ac_reset_enabled`, full-suite delta vs `pre-review-v4.7.7`.

The two framings were deliberately disjoint so the blind spots didn't overlap. Reviewer A surfaced A-M1 (precedence rule mislabels real reasons); Reviewer B surfaced B-M1 (visible-update lag) — neither would have surfaced the other.

### Pre-Deploy Zero-Bugs Gate (post-fix-up)

1. Conflict markers: clean
2. py_compile: clean across all changed `.py` files
3. JSON validity: strings.json + translations/en.json parse clean
4. v4.7.7 cycle tests: 82 passed / 3 skipped (HA-import gated)
5. Full URA suite: no NEW failures vs `pre-review-v4.7.7` baseline (4315 / 55 / 14)

---

## Carried Forward

- **v4.7.8 candidate:** manual `force_reset` button bridging to `_perform_hard_reset_escalation` for the (AC Nudge OFF, AC Reset ON) cell, if user feedback indicates the cell needs a triggerable path.
- **v4.7.8 candidate:** dedicated `SIGNAL_DPM_SKIP_REASONS_UPDATED` if `skipped_zones_with_reason` visible-update lag is confusing in practice.
- LOW-only deferrals from both reviewers (see Known Limitations) — opportunistic in a future cycle.
