# PLANNING v4.7.18 — DPM cleanup + heat-wave drift guard

**Status:** Awaiting operator approval
**Tier:** Tier 2-DB (operator-elevated — see §Tier classification)
**Predecessor:** v4.7.17.2 (current HEAD on `feature/v4.7.17.2-dpm-simplified-frame`, deploy pending)
**Filed:** 2026-06-02

---

## 0. Operator framing (verbatim, the reason for this cycle)

> "On cooler-feeling days relax Home/Sleep ranges (70-75 → 70-76); on super hot days tighten (70-74). That's it."

v4.7.17.2 shipped the operator-frame redesign with rolling 14-day median as baseline. Three gaps remained after that ship's operator audit:

1. Surface 2 (per-zone config flow) still exposes the 16 bucket cells behind a `customize_buckets` toggle even though they are unread at runtime. Misleading UX — looks live, isn't.
2. The rolling-median mechanic **drifts in sustained heat waves**. Operator example: 30 days at 100°F shifts the median to 100°F; a 95°F day then reads as `delta = −5` → relax fires (70-75 → 70-76) **while 95°F is still objectively hot**. Pure rolling-window logic cannot detect this — by construction the window only sees relative motion.
3. The heat-wave ceiling threshold should not be hardcoded — operator wants config exposure with a self-tuning default and named-bucket dropdown options for non-defaults.

Operator's standing directives in force for this cycle:
- "DO NOT throw away stuff that we need."
- "Do reconsider stuff we don't need."
- "DO NOT ever base any conclusion on a partial understanding. Context wide."

---

## 1. Institutional context verified

### Greps run + REUSED / NEW citations

| Proposed surface | Verdict | Citation |
|---|---|---|
| `CONF_DPM_RELAX_CEILING_MODE` | **NEW.** Grep `CONF_DPM*` finds only `CONF_DPM_COOL_DAY_RELAX_F` / `CONF_DPM_HOT_DAY_TIGHTEN_F` in `energy_const.py:220-223`. No existing ceiling/mode CONF. | `energy_const.py:220-223` |
| `_resolve_relax_ceiling()` helper | **NEW.** No `relax_ceiling`/`ceiling_mode` match across repo. | (none — confirmed absent) |
| `_p25_apparent_high()` derived percentile | **NEW.** Grep `percentile`/`p25` returns nothing in `weather_manager.py`. Existing `_rolling_median_apparent_high()` at `weather_manager.py:573` is the pattern to mirror. | `weather_manager.py:573-584` |
| `DPM_ROLLING_WINDOW_MAX_DAYS=90`, `DPM_P25_MIN_DAYS=30` | **NEW.** No 90-day window constant exists. Existing `DPM_ROLLING_WINDOW_DAYS=14` + `DPM_ROLLING_WINDOW_MIN_DAYS=7` at `energy_const.py:233-234` are the symmetric pattern to extend. | `energy_const.py:233-234` |
| Store key `ura_dpm_apparent_high_ring` | **REUSED — same key, widened cap.** Existing Store at `weather_manager.py:131-133` shape `{"ring": [[date_iso, float], ...]}`. List shape stays identical; only cap changes 14 → 90. | `weather_manager.py:131-133, 605-608` |
| Bucket-cell strip from Surface 2 | **REUSED knobs:** the 4 fields we keep (`zone_dynamic_preset_enabled`, `..._offset`, `..._reset_offset_guest`, `..._sleep_enabled`) all exist today and stay in `_PER_ZONE_DPM_KEYS` per `config_flow.py:359-366`. Removing the 16 bucket cells + the `customize_buckets` toggle is a strip-only operation, no new fields. | `config_flow.py:6205-6341` (current Surface 2 schema body); `config_flow.py:6271-6304` (the section to delete); `config_flow.py:6307-6340` (sleep section — strip cells, keep `sleep_enabled` at top level) |
| Strip dead `_validate_dynamic_preset_input` bucket loop | **REUSED method, removing dead code:** lines `config_flow.py:4247-4259` build the bucket-pair list + error keys that D1 makes unreachable. | `config_flow.py:4247-4259` |
| 4 `dynamic_preset_bucket_required_*` error strings | **REMOVED.** Currently at `strings.json:1631-1634` + `translations/en.json:1627-1630`. Made unreachable by D1+D2. | `strings.json:1631-1634` |
| New attrs on `DynamicPresetActiveBucketSensor` | **NEW attrs on REUSED sensor:** `relax_ceiling_f`, `relax_ceiling_source`, `relax_ceiling_blocked_count`, `relax_ceiling_last_blocked_at`. Sensor itself is RestoreEntity already — declared at `sensor.py:6873`. Existing `extra_state_attributes` body at `sensor.py:6982-7045` is what gets extended. | `sensor.py:6873, 6982-7045, 6924-6930` (existing `async_added_to_hass` restore) |
| Dropdown selector pattern for `relax_ceiling_mode` | **REUSED:** `selector.SelectSelector(selector.SelectSelectorConfig(options=..., mode=selector.SelectSelectorMode.DROPDOWN))`. Multiple existing call sites — `config_flow.py:636-643, 868-870, 1017-1018`. | `config_flow.py:636-643` |
| Today-apparent-high plumb into DPM | **REUSED:** `WeatherProviderManager.current_apparent_forecast_high()` already exists and is called at `sensor.py:7000`. DPM `evaluate_with_reason` does not currently take today's value as a separate kwarg — only `delta`. Plumbing it through is a single new kwarg or a fetch inside DPM via the same WPM accessor. | `weather_manager.py:75` (model field); `sensor.py:7000` (existing call) |
| `BLE001` defensive except pattern | **REUSED.** Existing patterns at `dynamic_preset.py:432-436, 623-628` (WPM persist) and `weather_manager.py:623-628`. All new try/except blocks in this cycle adopt this exact style. | `dynamic_preset.py:432-436` |

### Prior planning docs consulted (full read)

- `docs/planning/PLANNING_v4.7.17.2_dpm_simplified_operator_frame.md` — full read. Ground truth for what shipped + what was deferred. §6 row "16 per-zone CONFs" explicitly marks bucket cells as "NOT REMOVED in this cycle (data preserved); not read at runtime" with the deferral note "Cleanup is a future v5.0 architectural-debt sweep." **v4.7.18 D1+D2 pull that sweep forward** for Surface 2 visibility only — entry.options data stays preserved.
- `docs/planning/PLANNING_v4.7.4_dpm_ui_simplification.md` — skim. D3 = the original wrap of bucket cells into the collapsed `customize_buckets_section`. v4.7.18 D1 strips what v4.7.4 D3 wrapped.
- `docs/planning/PLANNING_v4.7.4.3_lazy_derive_customize_buckets_fix.md` (if present, otherwise referenced via `__init__.py:619, 2380-2387, 3328-3333` comments) — skim. v4.7.4.3 deleted eager migration in favor of lazy derivation at form-render time. D1 makes `_customize_buckets_value()` (`config_flow.py:6244-6261`) dead code; we remove it.

### Memory bodies pulled (full read)

- `project_dpm_redesign_operator_framing.md` — operator framing memo. Reaffirms: "Internal mechanics MUST NOT be exposed as control knobs. ≤2 operator-facing knobs." v4.7.18 honors this — `relax_ceiling_mode` is a **named-bucket dropdown**, not a raw threshold Number. The auto default keeps the operator surface at 0 effective new knobs by default; manual buckets are lived-experience names ("Conservative — skip above 85°F").

### Design docs read

- No `docs/Coordinator/Energy.md` exists at this time (grep negative). DPM design is currently captured in planning docs only. This cycle does not introduce one; the v4.7.17.2 README + this plan are the standing references.

### Code locations surveyed end-to-end during scoping

- `domain_coordinators/energy_const.py:200-247` — full DPM block, all CONFs + defaults + internal constants.
- `domain_coordinators/weather_manager.py:117-180` — `__init__` ring + Store setup; `async_setup` hydrate call.
- `domain_coordinators/weather_manager.py:234-261` — `baseline_delta_for_zone` (the rolling-median entry point).
- `domain_coordinators/weather_manager.py:563-668` — full rolling-window helper block (`_rolling_median_apparent_high`, `_record_daily_apparent_high`, `_persist_ring`, `_hydrate_rolling_window_from_store`).
- `domain_coordinators/weather_manager.py:443-485` — `_refresh_all_providers_locked` (where `_record_daily_apparent_high` is invoked).
- `domain_coordinators/dynamic_preset.py:95-123` — `_compute_cool_high_adjustment` (the math the new ceiling will gate).
- `domain_coordinators/dynamic_preset.py:395-465` — `evaluate_with_reason` top half: winter gate, gate 2, fresh config read, adjustment compute.
- `sensor.py:6873-7047` — full `DynamicPresetActiveBucketSensor` class (RestoreEntity + attr derivation + WPM accessor pattern).
- `config_flow.py:4076-4209` — Surface 1 schema + save handler.
- `config_flow.py:4211-4274` — `_validate_dynamic_preset_input` (the dead loop targeted by D2).
- `config_flow.py:6205-6341` — Surface 2 `_build_dynamic_preset_schema` (the strip target for D1).
- `config_flow.py:6097-6151` — Surface 2 save handler (where `customize_buckets` toggle is consumed).
- `strings.json:587-613, 1631-1634` + `translations/en.json:585-611, 1627-1630` — UI strings.

---

## 2. Approved deliverables

| # | Deliverable | Where | Est LoC |
|---|---|---|---|
| D1 | Strip the 16 bucket cells (8 home + 8 sleep) AND the `customize_buckets` toggle from Surface 2 `_build_dynamic_preset_schema`. Collapse to top-level fields only: `zone_dynamic_preset_enabled`, `..._offset`, `..._reset_offset_guest`, `..._sleep_enabled`. Remove `_customize_buckets_value()` derivation. Bucket CONFs remain in `entry.options` untouched. | `config_flow.py` | ~30 |
| D2 | Strip dead `_validate_dynamic_preset_input` bucket-pair loop + 4 `dynamic_preset_bucket_required_*` error keys from `strings.json` + `translations/en.json`. D1 makes these unreachable. | `config_flow.py`, `strings.json`, `translations/en.json` | ~20 |
| D3 | Widen WPM Store ring cap from 14 → 90 entries. Keep emitting 14-day median for relax/tighten math (`_rolling_median_apparent_high()` body uses the most-recent 14 entries of the ring, NOT the full ring). Add `_p25_apparent_high()` derived from the full 90-day window. Track `DPM_ROLLING_WINDOW_MAX_DAYS = 90` + `DPM_P25_MIN_DAYS = 30` cold-start guard. Store key + payload shape unchanged (`{"ring": [[date_iso, float], ...]}`). | `weather_manager.py`, `energy_const.py` | ~40 |
| D4 | New `CONF_DPM_RELAX_CEILING_MODE` (string enum). Dropdown values: `auto` (default), `conservative_85`, `moderate_90`, `aggressive_95`, `off`. Surface 1 only. Add `_resolve_relax_ceiling(today_apparent_high, p25)` returning `float | None`. Plumb today's apparent_high into `_compute_cool_high_adjustment` call site; gate the relax direction when `today_apparent_high >= ceiling`. Track suppression in new counters on the sensor (D5). | `dynamic_preset.py`, `config_flow.py`, `energy_const.py` | ~50 |
| D5 | Add 4 sensor attrs on `sensor.ura_energy_coordinator_dynamic_preset_bucket`: `relax_ceiling_f` (resolved °F or None), `relax_ceiling_source` (one of `auto`/`manual_conservative`/`manual_moderate`/`manual_aggressive`/`off`), `relax_ceiling_blocked_count` (int, persists via RestoreEntity), `relax_ceiling_last_blocked_at` (ISO timestamp, persists). Counters increment whenever the ceiling suppresses a relax that the rolling-median delta would otherwise have produced. | `sensor.py` | ~30 |
| D6 | Strings for the new Surface 1 field + 5 dropdown options. Updated atomically in BOTH `strings.json` AND `translations/en.json`. Operator-approved labels verbatim (see §3). Broader string audit deferred to v4.7.19. | `strings.json`, `translations/en.json` | ~15 |

**Total ~185 LoC production** + tests (see §7).

---

## 3. Operator-approved labels + helper text (verbatim — DO NOT paraphrase)

| Field | Label | Helper text |
|---|---|---|
| `relax_ceiling_mode` (NEW) | "Skip relax on hot days" | "When the forecast is above this temperature, the system won't widen cool ranges even if today is cooler than recent days. Auto picks a sensible value for your climate." |
| `auto` option | "Auto (recommended)" | (description) "Self-tuning based on your local climate history. Adjusts seasonally." |
| `conservative_85` option | "Conservative — skip above 85°F" | (description) "Tighter comfort margin." |
| `moderate_90` option | "Moderate — skip above 90°F" | (description) "Sane fallback for most climates." |
| `aggressive_95` option | "Aggressive — skip above 95°F" | (description) "More relaxation; accepts heat-wave drift." |
| `off` option | "Off — no ceiling" | (description) "Pure rolling-median behavior (v4.7.17.2 default)." |

---

## 4. The new mechanic — ceiling-gated relax

`relative_delta = today_apparent_high − rolling_median_apparent_high_14d`  (unchanged from v4.7.17.2)

New gate, applied AFTER `_compute_cool_high_adjustment` produces a positive (relax) value:

```text
ceiling = _resolve_relax_ceiling(today_apparent_high, p25_90d, mode)
if ceiling is not None and today_apparent_high >= ceiling and adjustment_f > 0:
    # Heat-wave drift detected — suppress the relax
    blocked_count += 1
    last_blocked_at = now_iso
    adjustment_f = 0.0
    skip_reason hint: "relax_ceiling_blocked"  (logged + surfaced on sensor; emission path still proceeds with adjustment=0)
```

### `_resolve_relax_ceiling` resolution table

| Mode | Resolved ceiling | Source label |
|---|---|---|
| `auto` (default) | `p25_apparent_high_90d` if ring has ≥ `DPM_P25_MIN_DAYS=30` entries, else `90.0` (moderate fallback) | `"auto"` |
| `conservative_85` | `85.0` | `"manual_conservative"` |
| `moderate_90` | `90.0` | `"manual_moderate"` |
| `aggressive_95` | `95.0` | `"manual_aggressive"` |
| `off` | `None` (no gate) | `"off"` |
| unrecognized string (defensive) | `90.0` | `"manual_moderate"` (silent fallback) |

**Why p25 for auto:** the 25th percentile of recent forecast highs is the operator's "what's a typical cool day in this climate" anchor. In a sustained heat-wave, p25 drifts UP slowly — much slower than the median — so even a "cool" 95°F day correctly does NOT relax because p25 has stayed near (say) 88°F. After a true seasonal cooldown, p25 catches up over the 90-day window. This is what defends scenario 1 (sustained heat → 95°F dip).

**Tightening direction is NOT gated.** A negative (tighten) adjustment always passes through. The mechanic asymmetry: we suppress relax on hot days; we never suppress tightening.

---

## 5. Heat-wave scenarios (the 5 cases from operator's analysis)

For each scenario, list (rolling_median_14d, today_apparent_high, p25_90d, auto-resolved ceiling, expected adjustment after gate).

| # | Scenario | median_14d | today | p25_90d | ceiling (auto) | v4.7.17.2 adjustment | v4.7.18 adjustment |
|---|---|---|---|---|---|---|---|
| 1 | 30 days at 100°F, then a 95°F day | 100 | 95 | 96 (drifts up with sustained heat) | 96 | +1.0 (relax — WRONG) | **0.0 (gated — RIGHT)** |
| 2 | Normal summer + 78°F cool front | 90 | 78 | 84 | 84 | +1.0 (relax) | +1.0 (relax — under ceiling, allowed) |
| 3 | Embedded heat wave (100°F day inside a 90°F month) | 91 | 100 | 88 | 88 | −1.0 (tighten) | −1.0 (tighten — gate doesn't apply to tighten direction) |
| 4 | Shoulder cooldown (Oct after Sept) | 78 | 70 | 75 | 75 | +1.0 (relax) | +1.0 (relax — under ceiling, allowed) |
| 5 | 100°F stable + 96°F dip | 100 | 96 | 97 (drifts up in heat wave) | 97 | +1.0 (relax — WRONG) | **0.0 (gated — RIGHT)** |

All 5 scenarios behave correctly under the auto ceiling. Manual buckets behave per their fixed threshold.

---

## 6. Risk section (per operator's "very carefully check risks" directive)

### D1 — Surface 2 bucket-cell strip

- **Risk:** Operators with hand-tuned bucket cells lose visibility into their configured values; UI no longer surfaces them.
- **Counter:** Data preserved in `entry.options` (D1 strips schema rendering only — does not touch persisted CONFs). Confirmed by reading `config_flow.py:6097-6151` save handler: `customize_buckets=False` already takes the no-write path. v4.7.4.3 lazy-derivation `_customize_buckets_value()` deletion is safe because the form no longer asks the question.
- **Mitigation:** README explicitly documents the strip. Operator already accepted ("data is dead"). Bucket CONFs stay readable by future operators if they manually inspect `entry.options` via developer tools.
- **Risk accepted.**

### D2 — Strip dead validation + error strings

- **Risk:** A latent caller of `_validate_dynamic_preset_input` outside Surface 2 might still expect the bucket-pair error keys.
- **Verification needed during build:** grep `_validate_dynamic_preset_input` call sites BEFORE removing. The current bucket-pair loop at `config_flow.py:4247-4259` is reachable only when `enabled=True` AND bucket cells are non-None in `user_input`. After D1 there are no bucket cells in `user_input`, so `low is None or high is None` always trips the early `return f"dynamic_preset_bucket_required_{bname}"`. We must strip the loop entirely, not "fix" it — otherwise D1 would crash the save with a phantom error.
- **Mitigation:** Strip the loop; strip the 4 error keys. The `sleep_below_floor` check (`config_flow.py:4261-4272`) reads bucket-derived `sleep_high_keys` — that ALSO becomes dead code under D1. Strip the whole sleep_enabled branch of the validator too. Validator collapses to: `if not enabled: return ""` then check `sleep_below_floor` only against the sleep_offset (no per-bucket sleep_high values exist post-D1) — **simpler: the whole sleep_below_floor branch goes too**. The validator devolves to a no-op past the enabled check. **Consider deleting `_validate_dynamic_preset_input` entirely** and removing call sites; verify call sites via grep first.
- **Risk: HIGH if call-site audit skipped.** Builder must audit before strip.

### D3 — Widen Store ring 14 → 90

- **Risk 1 (back-compat):** Existing 14-entry Store payload must still load cleanly. Verified by reading `_hydrate_rolling_window_from_store` at `weather_manager.py:630-668`: the hydrate loop iterates `data["ring"]` of arbitrary length, validates each entry, then caps to `DPM_ROLLING_WINDOW_DAYS`. After D3, change the cap line at `:664` from `DPM_ROLLING_WINDOW_DAYS` to `DPM_ROLLING_WINDOW_MAX_DAYS` (90). Old 14-entry rings load as-is and slowly grow toward 90 over the next 76 days.
- **Risk 2 (write amplification):** Persist on every record. 90 entries × ~24 bytes = ~2.2 KB. Below HA `Store` "tiny write" threshold; no impact. Already write on every record under v4.7.17.2.
- **Risk 3 (ring eviction order):** The `while len > MAX: pop(0)` pattern at `weather_manager.py:606-607` evicts oldest first. Append order = chronological (forecast lands once per day → append). Median + p25 computations therefore operate on chronologically-sorted-by-append data. **Median is order-invariant; p25 is order-invariant.** Safe.
- **Risk 4 (median frame shift):** v4.7.17.2 computed median over the full ring (which was capped at 14). v4.7.18 must compute median over the **most-recent 14 entries** of the now-90-cap ring, NOT the full 90. Otherwise the 14-day median silently becomes a 90-day median across one deploy — a load-bearing semantic change v4.7.17.2 reviewers explicitly stamped. **`_rolling_median_apparent_high` body becomes `statistics.median([v for _, v in self._apparent_high_ring[-DPM_ROLLING_WINDOW_DAYS:]])`** (the slice is the critical new line).
- **Risk 5 (recorder hydration cost):** v4.7.17.2 hydrates only from Store, not recorder. Same in v4.7.18. No new cold-install hydration queries.
- **Mitigation:** Reviewer A explicitly verifies the median-slice line + the back-compat load path.

### D4 — `_resolve_relax_ceiling` + dropdown selector schema

- **Risk 1 (silent fallback on unrecognized string):** Voluptuous `selector.SelectSelector` with the standard `SelectSelectorMode.DROPDOWN` does NOT enforce server-side that the saved value is in the options list (HA selectors validate on the FE only, not in vol). If `entry.options` ever holds a non-matching string (manual edit, future migration drift), `_resolve_relax_ceiling` must fall through to a defensive default.
- **Mitigation:** `_resolve_relax_ceiling` matches on a known set; on miss returns `(90.0, "manual_moderate")` and logs at `_LOGGER.debug` (NOT warning — this is expected behavior during config-flow rendering before save).
- **Risk 2 (cold-start p25):** Below `DPM_P25_MIN_DAYS=30` entries, `_p25_apparent_high` returns None; auto mode then falls back to `90.0` ceiling. This means a fresh install gets the moderate ceiling for 30 days, then transitions to its own climate's p25. Behavior is conservative-by-default during cold start. **Tested by scenario set in §5.**
- **Risk 3 (timing — today_apparent_high vs ring):** When today's forecast lands, the ring records it AND the median/p25 update before DPM evaluates. **Verify ordering at `weather_manager.py:483` (`_record_daily_apparent_high`) vs `dynamic_preset.py` invocation site.** `_record_daily_apparent_high` runs inside `_refresh_all_providers_locked` BEFORE the forecast is exposed to DPM via `baseline_delta_for_zone`. Safe ordering preserved.
- **Risk 4 (plumb today_apparent_high into DPM):** v4.7.17.2's DPM `evaluate_with_reason` receives only `delta` as input — no separate today_apparent_high. Two options:
  - Option A: add new kwarg `today_apparent_high: float | None = None` to `evaluate_with_reason` and plumb from the caller (energy.py).
  - Option B: have DPM fetch via `self.hass.data[DOMAIN]["weather_manager"].current_apparent_forecast_high()` inside the function.
  - **Recommended: Option B.** Single source of truth (WPM accessor), no caller-site churn, matches the existing pattern at `sensor.py:7000`. Defensive `BLE001` wrapper consistent with `dynamic_preset.py:432-436`.
- **CRITICAL fail mode:** if dropdown saves an unrecognized string, defensive default fires. If `today_apparent_high` is None (WPM down), ceiling check skipped (`adjustment_f` passes through unchanged) — fail-open, matches v4.7.17.2 degraded-state behavior.

### D5 — RestoreEntity counters

- **Risk 1 (Bug Class #46 — lazy derivation):** The two new RestoreEntity-backed values (`relax_ceiling_blocked_count`, `relax_ceiling_last_blocked_at`) must hydrate at `async_added_to_hass` and survive cross-restart. Existing pattern at `sensor.py:6924-6930` reads `last_state.state` only; attribute restoration requires `last_state.attributes`.
- **Mitigation:** In `async_added_to_hass`, after the existing `last_state.state` block, read `last_state.attributes.get("relax_ceiling_blocked_count", 0)` and `last_state.attributes.get("relax_ceiling_last_blocked_at")` into instance vars (`self._restored_blocked_count`, `self._restored_blocked_at`). The `extra_state_attributes` getter then returns the live counter if the override source has fired since boot, else the restored value. Increment logic must be in the override-source side (DPM), surfaced via signal-dispatched state; this sensor merely reads.
- **Risk 2 (counter ownership):** The counters belong to DPM (the gate fires inside `_compute_cool_high_adjustment` call site), not the sensor. DPM tracks via `self._relax_ceiling_blocked_count: dict[str, int]` keyed by zone_id (matches `self._active_bucket` pattern at `dynamic_preset.py`). Sensor reads via `source.get_zone_state(zone_id)` (existing pattern at `sensor.py:6990`). Cross-restart hydration: sensor reads `last_state.attributes`, calls a new `source.restore_blocked_counter(zone_id, count, last_at)` method analogous to the existing `source.restore_zone_state` at `sensor.py:6950`. **Mirror the existing pattern exactly.**
- **Risk 3 (counter monotonicity):** Counter must never decrement. Increment only inside the gate-fired branch. No reset path in v4.7.18 (operator can clear via Developer Tools if needed — defer reset button to v4.7.19).
- **Test cold start + warm start + cross-restart counter survival.**

### D6 — strings.json + en.json drift

- **Risk:** Single-file edits drift apart. URA has been disciplined about this (verified by v4.7.17.2 + v4.7.14.1 patterns).
- **Mitigation:** Edit both files in the same atomic commit. Reviewer C verifies the diff covers both.

---

## 7. Acceptance criteria per deliverable

### D1: Surface 2 bucket-cell strip

- **Verify:** Re-rendering Surface 2 form for an existing DPM-enabled zone shows exactly 4 fields (enabled, offset, reset_guest, sleep_enabled). No collapsed sections.
- **Verify:** Save with all 4 fields filled persists to `entry.options` and does not corrupt pre-existing bucket-cell values.
- **Test:** `test_v4_7_18_surface2_strip_schema_shape` — instantiate the options-flow handler, invoke `_build_dynamic_preset_schema`, assert schema's voluptuous markers contain exactly the 4 expected keys and no bucket keys, no `customize_buckets_section`.
- **Test:** `test_v4_7_18_surface2_strip_preserves_options` — seed `entry.options` with bucket cells + the 4 top-level fields; render schema; save the form with only the 4 fields; assert `entry.options` still contains the original bucket cells unchanged.
- **Live:** Open URA Zone Manager → Configure a DPM-enabled zone. Confirm only 4 visible fields. Cancel without saving. Re-open. Schema renders identically (no re-derivation crash).

### D2: Strip dead validation + error strings

- **Verify:** `_validate_dynamic_preset_input` (or its replacement / deletion) does not reference `bucket_pairs` or `dynamic_preset_bucket_required_*` error keys.
- **Verify:** `strings.json` + `translations/en.json` no longer contain `dynamic_preset_bucket_required_*` keys.
- **Test:** `test_v4_7_18_dead_validator_strip_grep` — grep the source tree for the 4 error key names; assert zero matches outside of historical README docs.
- **Test:** `test_v4_7_18_validator_callers_clean` — grep for `_validate_dynamic_preset_input` call sites; assert each remaining call site provides arguments compatible with the new (stripped) signature OR the function has been removed and the call sites along with it.
- **Live:** Save Surface 2 for a DPM-enabled zone with `enabled=True`. No `dynamic_preset_bucket_required_*` error renders.

### D3: WPM ring widen 14 → 90 + p25

- **Verify:** `DPM_ROLLING_WINDOW_MAX_DAYS = 90` in `energy_const.py`; `DPM_ROLLING_WINDOW_DAYS = 14` and `DPM_ROLLING_WINDOW_MIN_DAYS = 7` UNCHANGED; new `DPM_P25_MIN_DAYS = 30`.
- **Verify:** `_rolling_median_apparent_high` body uses the most-recent 14 entries via `[-DPM_ROLLING_WINDOW_DAYS:]` slice (NOT the full ring).
- **Verify:** `_p25_apparent_high()` returns None when `len(ring) < DPM_P25_MIN_DAYS`, else `statistics.quantiles(values, n=4)[0]` (25th percentile).
- **Sensor:** `sensor.ura_energy_coordinator_dynamic_preset_bucket` attribute `rolling_median_apparent_high_f` value is identical to what v4.7.17.2 would have produced for the same 14-entry sub-window. **No behavior change for median.**
- **Test:** `test_v4_7_18_ring_widen_back_compat` — load a Store payload with 14 entries (the v4.7.17.2 shape); assert hydrate succeeds; assert median equals pre-widen median.
- **Test:** `test_v4_7_18_ring_widen_grows_to_90` — append 91 daily entries; assert ring length caps at 90; oldest entry evicted first.
- **Test:** `test_v4_7_18_p25_min_days_guard` — at 29 entries `_p25_apparent_high()` returns None; at 30 entries returns a valid float.
- **Test:** `test_v4_7_18_median_slice_invariant` — append 30 entries; assert median computed over `ring[-14:]`, not over all 30.
- **Live:** After deploy, `.storage/ura_dpm_apparent_high_ring` loads cleanly; sensor attr `rolling_median_apparent_high_f` value is plausible (within ±2°F of recent days' apparent_high).

### D4: `relax_ceiling_mode` + resolver + gate

- **Verify:** Surface 1 schema includes `relax_ceiling_mode` as a `SelectSelector` with 5 options.
- **Verify:** Default value `auto`; saving the form persists the string value to `entry.options`.
- **Verify:** `_resolve_relax_ceiling(today=None, p25=None, mode="auto")` returns `(90.0, "auto")` (cold-start fallback to moderate).
- **Verify:** `_resolve_relax_ceiling(today=95.0, p25=88.0, mode="auto")` returns `(88.0, "auto")`.
- **Verify:** `_resolve_relax_ceiling(today=95.0, p25=88.0, mode="off")` returns `(None, "off")`.
- **Verify:** `_resolve_relax_ceiling(today=95.0, p25=88.0, mode="unrecognized_string")` returns `(90.0, "manual_moderate")` defensively.
- **Verify:** Gate fires: with mode=auto, today_apparent_high=95, p25=88, rolling_median_14d=100 (relative_delta = −5 → relax direction), `_compute_cool_high_adjustment` returns +1.0 BEFORE gate, post-gate adjustment is 0.0, `relax_ceiling_blocked_count` increments by 1.
- **Test:** `test_v4_7_18_resolve_ceiling_all_modes` — covers all 5 modes + the unrecognized-string defensive path.
- **Test:** `test_v4_7_18_gate_blocks_relax_in_heat_wave` — the §5 scenario 1 path.
- **Test:** `test_v4_7_18_gate_does_not_block_tighten` — relative_delta=+4, tighten_f=1.0, today=100 → adjustment stays −1.0 regardless of ceiling.
- **Test:** `test_v4_7_18_gate_inactive_when_today_below_ceiling` — §5 scenarios 2 and 4.
- **Live:** After ≥1 ≥90°F day post-deploy with auto mode AND the ring already had 14+ entries, `relax_ceiling_blocked_count` attribute on the bucket sensor is > 0.

### D5: Sensor attrs + RestoreEntity counters

- **Sensor:** `relax_ceiling_f` shows the resolved ceiling (float or None).
- **Sensor:** `relax_ceiling_source` shows the source label (string).
- **Sensor:** `relax_ceiling_blocked_count` is int, monotonically non-decreasing, persists across HA restart.
- **Sensor:** `relax_ceiling_last_blocked_at` is ISO timestamp, persists across HA restart.
- **Test:** `test_v4_7_18_sensor_attrs_present` — create the sensor, force an evaluation, assert all 4 attrs present with correct types.
- **Test:** `test_v4_7_18_counter_persists_across_restart` — simulate a restart by re-creating the sensor, providing a `last_state` with the 4 attrs set; assert restored values surface immediately and continue to increment from there.
- **Test:** `test_v4_7_18_counter_monotonicity` — fire the gate N times; assert count goes 0 → 1 → 2 → ... never decrements.
- **Live:** Restart HA. Confirm `relax_ceiling_blocked_count` does not reset to 0 if it had a non-zero value pre-restart.

### D6: Strings

- **Verify:** `strings.json` contains `relax_ceiling_mode` label + helper text + 5 option labels with descriptions, verbatim per §3.
- **Verify:** `translations/en.json` contains the identical strings.
- **Test:** `test_v4_7_18_strings_parity` — diff the new key paths between strings.json and en.json; assert identical structure.
- **Live:** UI renders the operator-approved labels (verbatim).

---

## 8. Tier classification — Tier 2-DB (operator-elevated)

**Operator elevated this cycle to Tier 2-DB per CLAUDE.md operator-elevated clause.** Justification:

- Touches the WPM Store ring (persistence shape: backward-compatible widen, but data integrity matters across restart).
- Adds new sensor attrs that Shipwatch will consume (payload shape contract — counters must round-trip cleanly through RestoreEntity).
- Strips Surface 2 schema (UX surface change that could orphan operator-configured zones if save handler isn't audited).
- Trust-hierarchy ripple: DPM → HVAC → operator-visible output. A ceiling-gate bug silently suppresses every relax — undetectable without the counter telemetry D5 introduces.

The Tier 2-DB trigger criteria in CLAUDE.md are not strictly fired (no `database.py` DAO changes, no SQL schema). Operator elevation invokes the higher bar because the trust-hierarchy ripple risk is real and surgical-fix-with-coordinator-ripple is the precise case CLAUDE.md singles out.

---

## 9. Three review framings (REQUIRED — run in parallel post-build)

### Reviewer A — Data integrity + DB-equivalent persistence

- Existing 14-entry Store data loadable after widen to 90 (back-compat).
- Store schema not corrupted by old/new mixed payloads.
- No data loss path (the `cap = MAX_DAYS` change is additive — the eviction loop slice `cleaned[-DPM_ROLLING_WINDOW_DAYS:]` MUST be updated to `cleaned[-DPM_ROLLING_WINDOW_MAX_DAYS:]` at `weather_manager.py:664` — verify this explicitly).
- p25 derivation correctness — `statistics.quantiles(values, n=4)[0]` returns the 25th percentile; verify against a hand-computed test vector.
- Median frame integrity: `_rolling_median_apparent_high` MUST slice `[-DPM_ROLLING_WINDOW_DAYS:]`; a missing slice silently changes the median to a 90-day median. Reviewer A explicitly stamps this line.
- Existing analytics consumers of `rolling_median_apparent_high_f` (the sensor attr) return the same value shape post-deploy.

### Reviewer B — Migration correctness + signal chain integrity

- D1 strip does not orphan in-flight options-flow state. Existing operator-tuned bucket cells stay in `entry.options` (no destructive write). Verify by reading the save handler at `config_flow.py:6097-6151` end-to-end and confirming the post-D1 save path does not include any `del entry.options[key]` or equivalent.
- D2 dead-code removal does not break any remaining caller of `_validate_dynamic_preset_input`. **Builder must run a call-site grep BEFORE strip and pass results to Reviewer B.**
- Sensor attribute additions (D5) don't break v4.7.17.2 attribute consumers. Existing keys (`relative_delta_f`, `apparent_high_f`, `rolling_median_apparent_high_f`, `cool_high_adjustment_f`, `last_transition_iso`, `dwell_remaining_min`, `active_overrides_count`) remain present and unchanged.
- Counter persistence via RestoreEntity round-trips cleanly across restart. End-to-end trace: increment in DPM → write to `source._relax_ceiling_blocked_count` → expose via `source.get_zone_state` → sensor `extra_state_attributes` → HA RestoreEntity captures → restart → `async_added_to_hass` reads `last_state.attributes` → `source.restore_blocked_counter()` re-seeds.
- No double-emit risk. The gate fires once per evaluation; counter increments once per fired gate; the existing `SIGNAL_DYNAMIC_PRESET_OVERRIDES_UPDATED` dispatch is unchanged (no new payload field; counter is read-pull from source).

### Reviewer C — New surfaces + test fixture authority

- New CONF dropdown options validate via voluptuous `selector.SelectSelector(selector.SelectSelectorConfig(options=[{"label":..., "value":...}, ...], mode=SelectSelectorMode.DROPDOWN))`. Verify the exact selector shape against existing call sites at `config_flow.py:636-643`.
- Cold-start behavior: p25 < min_days → `_resolve_relax_ceiling` mode=auto falls back to `90.0` ceiling. Verified by `test_v4_7_18_resolve_ceiling_all_modes`.
- Heat-wave defense logic fires in the right cases: all 5 §5 scenarios pass the corresponding test.
- Test fixtures NOT hand-rolled — tests drive production `_compute_cool_high_adjustment`, `_resolve_relax_ceiling`, `_rolling_median_apparent_high`, `_p25_apparent_high`, schema-builder paths. No copy of DDL or hand-typed Store payloads beyond minimal seed dicts.
- Tests assert behavior shape, not exact float equality where unstable (use `pytest.approx` for floats).

**Run the three reviews in PARALLEL — different framings can't share blind spots.**

Fix all CRITICAL / HIGH from any review before deploy. Spot-check or run a focused fourth pass if fix-up substantial.

---

## 10. Pre-deploy snapshot (for Tier 2-DB)

Before `./scripts/deploy.sh`, snapshot:

- `wc -l ~/ha-config/.storage/ura_dpm_apparent_high_ring` (file size baseline)
- `ha_get_state("sensor.ura_energy_coordinator_dynamic_preset_bucket_<each_zone>", attribute_keys=["rolling_median_apparent_high_f","relative_delta_f","cool_high_adjustment_f"])` for every DPM-enabled zone (median shape baseline)
- `git tag pre-review-v4.7.18 -m "Pre-review baseline for v4.7.18"`

Post-deploy comparison (Reviewer D / live validation):
- Same median value at restart + ≤1 hour (the median is computed from the most-recent 14 entries; should be identical to the pre-deploy value because the ring is loaded from Store).
- `relax_ceiling_f` attribute populated (not None) for every DPM-enabled zone within an hour of restart.
- `relax_ceiling_source` matches the operator's saved mode (default `auto`).

---

## 11. Live validation (Reviewer D, post-restart)

```python
# Per-zone bucket sensor — verify new attrs present and back-compat preserved:
ha_get_state(
    "sensor.ura_energy_coordinator_dynamic_preset_bucket_<zone>",
    attribute_keys=[
        # v4.7.17.2 attrs (must still be present + populated)
        "relative_delta_f",
        "apparent_high_f",
        "rolling_median_apparent_high_f",
        "cool_high_adjustment_f",
        # v4.7.18 NEW attrs
        "relax_ceiling_f",
        "relax_ceiling_source",
        "relax_ceiling_blocked_count",
        "relax_ceiling_last_blocked_at",
    ],
)

# Store payload — verify widen cap took effect (after enough days):
# cat ~/ha-config/.storage/ura_dpm_apparent_high_ring | jq '.data.ring | length'
# Should grow toward 90 over time; immediately post-deploy still <= 14.

# Surface 2 regression check — verify bucket cells gone:
# Open URA → Zone Manager → Configure DPM-enabled zone.
# Form must show exactly 4 fields: enabled, offset, reset_guest, sleep_enabled.

# Heat-wave defense smoke (only firable on a hot day post-deploy):
# When today's forecast >= 90F and the ring has 14+ days,
# the bucket sensor's `cool_high_adjustment_f` should NOT be positive,
# AND `relax_ceiling_blocked_count` should equal at least 1 if a relax was suppressed.
```

---

## 12. Acceptance YAML (Shipwatch — copied verbatim into README)

```yaml
version: v4.7.18
hypotheses:
  - id: H1
    name: relax_ceiling_mode_dropdown_present_surface_1
    description: |
      The new operator dropdown "Skip relax on hot days" must appear on
      the HVAC Coordinator → Dynamic Preset Surface 1 form with exactly
      5 options (auto, conservative_85, moderate_90, aggressive_95, off).
    query:
      kind: config_flow_schema
      step: hvac_dynamic_preset
      field: dpm_relax_ceiling_mode
    expected:
      condition: "options_set_equals"
      value: ["auto", "conservative_85", "moderate_90", "aggressive_95", "off"]
    window:
      first_check_after: 1h
      confirm_after: 24h
      alert_if_violated_after: 72h

  - id: H2
    name: relax_ceiling_f_sensor_attr_numeric
    description: |
      Bucket sensor exposes relax_ceiling_f attribute, numeric or null
      depending on mode (null only when source=="off").
    query:
      kind: ha_state_attribute
      entity: sensor.ura_energy_coordinator_dynamic_preset_bucket
      attribute: relax_ceiling_f
    expected:
      condition: "is_numeric_or_null"
      value: null
    window:
      first_check_after: 1h
      confirm_after: 24h
      alert_if_violated_after: 72h

  - id: H3
    name: relax_ceiling_source_reflects_operator_choice
    description: |
      Sensor attribute relax_ceiling_source matches the operator's
      configured mode in entry.options after a save.
    query:
      kind: ha_state_attribute
      entity: sensor.ura_energy_coordinator_dynamic_preset_bucket
      attribute: relax_ceiling_source
    expected:
      condition: "in"
      value: ["auto", "manual_conservative", "manual_moderate", "manual_aggressive", "off"]
    window:
      first_check_after: 1h
      confirm_after: 24h
      alert_if_violated_after: 72h

  - id: H4
    name: relax_ceiling_blocked_count_fires_in_production_heat
    description: |
      After at least one >=90F day post-deploy with auto mode AND
      ring has 14+ entries, relax_ceiling_blocked_count > 0. Proves
      the heat-wave drift gate fires in production.
    query:
      kind: ha_state_attribute
      entity: sensor.ura_energy_coordinator_dynamic_preset_bucket
      attribute: relax_ceiling_blocked_count
    expected:
      condition: ">"
      value: 0
    window:
      first_check_after: 168h    # 7 days
      confirm_after: 720h         # 30 days
      alert_if_violated_after: 2160h  # 90 days
      only_during: forecast_apparent_high_seen_geq_90f

  - id: H5
    name: surface_2_no_bucket_cells_rendered
    description: |
      Surface 2 (per-zone DPM config) form schema MUST NOT include any
      of the 16 bucket cell fields nor the customize_buckets toggle.
      Regression check for D1 strip.
    query:
      kind: config_flow_schema
      step: zone_dynamic_preset
      field_names_must_not_include:
        - zone_dynamic_preset_customize_buckets
        - zone_dynamic_preset_cool_home_low
        - zone_dynamic_preset_cool_home_high
        - zone_dynamic_preset_mild_home_low
        - zone_dynamic_preset_mild_home_high
        - zone_dynamic_preset_hot_home_low
        - zone_dynamic_preset_hot_home_high
        - zone_dynamic_preset_extreme_home_low
        - zone_dynamic_preset_extreme_home_high
        - zone_dynamic_preset_cool_sleep_low
        - zone_dynamic_preset_cool_sleep_high
        - zone_dynamic_preset_mild_sleep_low
        - zone_dynamic_preset_mild_sleep_high
        - zone_dynamic_preset_hot_sleep_low
        - zone_dynamic_preset_hot_sleep_high
        - zone_dynamic_preset_extreme_sleep_low
        - zone_dynamic_preset_extreme_sleep_high
    expected:
      condition: "all_absent"
      value: true
    window:
      first_check_after: 1h
      confirm_after: 24h
      alert_if_violated_after: 72h

  - id: H6
    name: existing_zones_load_without_errors_after_strip
    description: |
      Every existing DPM-enabled zone loads without missing-CONF crashes
      after the Surface 2 schema strip. entry.options bucket cells stay
      readable (data preserved); runtime ignores them. URA ERROR log
      must remain clean for one full hour post-restart.
    query:
      kind: log_grep
      source: home_assistant_core
      pattern: "universal_room_automation.*ERROR"
    expected:
      condition: "no_matches_in_window"
      value: null
    window:
      first_check_after: 1h
      confirm_after: 24h
      alert_if_violated_after: 72h
```

---

## 13. Migration shape

- **No DB migration.** Persistence via HA `Store` (unchanged shape, widened cap).
- **No CONF migration.** v4.7.17.2 CONFs untouched; v4.7.18 ADDS `CONF_DPM_RELAX_CEILING_MODE` with default `auto`; bucket cells in `entry.options` stay dormant (already the v4.7.17.2 contract).
- **First restart after deploy:** byte-identical median behavior. Ring loads 14 entries from Store; median computed over the same 14 entries; v4.7.17.2 behavior preserved exactly. The new ceiling gate is active immediately (default `auto` → moderate `90.0°F` ceiling if ring has <30 entries for p25; once ring reaches 30 entries, p25 takes over).
- **First 30 days post-deploy:** auto ceiling pinned at 90.0°F fallback. After day 30, ceiling = climate's p25 (typically 75-90°F depending on region).
- **First ≥90°F day post-deploy:** if relative_delta would have produced relax (rare — would require simultaneous ≥90°F day AND recent days hotter than that), gate fires, counter increments. Operator can observe via the bucket sensor's new attrs.
- **Rollback:** install v4.7.17.2. New CONF stays dormant in `entry.options`; ring Store payload (now potentially >14 entries) loads truncated at v4.7.17.2's 14-entry cap with no data loss (the hydrate-tail slice gracefully handles oversized payloads). No data loss either direction.

---

## 14. Plan completion tracking (items explicitly deferred)

1. **Reset button for `relax_ceiling_blocked_count`** — defer to v4.7.19. Operator can clear via Developer Tools if needed.
2. **Removal of 16 bucket CONF constants from `energy_const.py`** — defer to v5.0 architectural-debt sweep. D1 strips them from UI; constants stay readable for diagnostic `classify_bucket()` callability.
3. **Broader string audit for stale v4.7.4-era labels** — defer to v4.7.19. v4.7.18 D6 covers only the new Surface 1 field and the 4 removed `dynamic_preset_bucket_required_*` keys.
4. **`docs/Coordinator/Energy.md`** — does not currently exist. Not creating in v4.7.18. Future doc-debt cycle.
5. **Asymmetric window option (analyzed and rejected per cycle context)** — confirmed during planning that the absolute-ceiling approach defends all 5 scenarios while asymmetric window fails scenario 1 (sustained heat). Asymmetric window NOT shipped.
6. **Dropdown option descriptions for `relax_ceiling_mode`** — planning §3 specifies per-option helper text (Auto / Conservative 85°F / Moderate 90°F / Aggressive 95°F / Off). Option LABELS landed in `4ac70ed`; per-option DESCRIPTIONS deferred to v4.7.19 alongside the broader Surface 2 string audit (§14 #3). Operator decision: deferring is acceptable since the 5 option labels themselves are self-explanatory. Closes Reviewer C C-M2.

---

## 15. Executive summary

1. Three operator-audit gaps from v4.7.17.2 closed in one cycle: Surface 2 bucket-cell strip (D1+D2), heat-wave drift guard via absolute-ceiling gate (D3+D4+D5), strings (D6).
2. Internal mechanic preserved exactly — v4.7.17.2 rolling 14-day median continues to drive relax/tighten math; the new gate sits AFTER `_compute_cool_high_adjustment` and only suppresses relax when today's apparent_high is ≥ resolved ceiling.
3. `relax_ceiling_mode` is a named-bucket dropdown (`auto`/`conservative_85`/`moderate_90`/`aggressive_95`/`off`) — never a raw threshold Number, per operator framing. Auto default uses p25 of the 90-day forecast ring.
4. WPM Store ring widened 14 → 90 entries (back-compat-safe; payload shape unchanged). Median still uses the most-recent 14 (load-bearing slice); p25 uses the full 90 once `DPM_P25_MIN_DAYS=30` is met.
5. ~185 LoC production across 5 files + ~250 LoC tests. Tier 2-DB review (operator-elevated): 3 framings in parallel (A=data integrity, B=migration correctness, C=new surfaces). Live validation H1–H6 + Reviewer D.
