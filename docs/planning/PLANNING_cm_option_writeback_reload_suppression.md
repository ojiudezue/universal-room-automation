# PLANNING — CM Option-Writeback Reload Suppression + Part-1 Hygiene

**Status:** Build-ready plan. Tier elevated to operator-elevated Tier 2-DB (see Tier classification).
**Version:** unassigned (operator assigns at deploy time, per `feedback_versioning_convention`).
**Cycle scope:** robustness fix on the runtime-tunable HVAC presence-timer Numbers + Dynamic Preset Dwell Number; eliminates the full Coordinator-Manager (CM) entry reload that currently fires on every knob edit. Also resolves the deferred A-MED-1 form-UX bug (two-trip cross-field error surfacing) as D5.

---

## Problem statement (grounded, verified this session)

The v4.7.25 HVAC presence-timer Numbers (`48 Zone Vacancy Delay`, `49 …Energy-Saving`, `50 Max Zone Occupied Time`, `61 Zone Entry Dwell`) and the Dynamic Preset `03 Dwell` Number all follow the "options = sole source of truth + live-attr push" pattern. Each `async_set_native_value` does two things:

1. Pushes the new value to the live coordinator attr (`hvac._max_occupancy_hours`, `hvac._vacancy_grace`, `hvac._vacancy_grace_constrained`, `hvac._zone_entry_dwell`, energy/DPM live attrs).
2. Calls `hass.config_entries.async_update_entry(entry, options={…})` to persist.

Verified setter sites (`custom_components/universal_room_automation/number.py`):
- `ZoneEntryDwellNumber.async_set_native_value` → writeback `:370`
- `VacancyGraceMinutesNumber.async_set_native_value` → writeback `:462` (plus A-HIGH-1 bidirectional clamp at `:448-456` that also writes `CONF_HVAC_VACANCY_GRACE_CONSTRAINED`)
- `VacancyGraceConstrainedNumber.async_set_native_value` → writeback `:551-554` (clamp at `:540-546`)
- `MaxOccupancyHoursNumber.async_set_native_value` → writeback `:625-628`
- `DynamicPresetDwellMinutesNumber.async_set_native_value` → writeback `:2187-2190` (and STILL inherits `RestoreEntity` — Part-1 hygiene target)

Plus the `51 Reset` button (`button.py` ~643-674) which writes all four timer defaults in one `async_update_entry` call.

The update listener `_async_update_listener` (`__init__.py:3521-3542`) schedules an **unconditional, untracked full `async_reload`** of the entry. For the CM entry this rebuilds EVERY coordinator (presence/HVAC/energy/safety/diagnostics/house_state/signals/etc.) and re-creates all CM entities on every single knob edit.

**Observed live 2026-06-06.** Changing one Number re-stamped all four timer Numbers with identical `last_changed` to the millisecond — full re-setup confirmed. Under the house's websocket backpressure (`Client unable to keep up with pending messages. Reached 4096 pending messages` — 51 ERRORs in the day's logs), the reload's burst of `state_changed` events at the save moment pushes the frontend socket over its cap → the iOS app surfaces `Failed to perform the action number/set_value. connection lost` even though the server-side write completed (value persisted).

The reload is redundant for these keys: the live attr was already pushed before the `async_update_entry` call.

This was previously accepted as **B-H1** ("convergent, no debounce") in the v4.7.25 Tier 2 review and as the v4.3.2 mirror-pattern doctrine flip. The new live evidence (connection-lost UX cost under backpressure) is the reason to revisit it.

**Form-UX problem (A-MED-1, addressed in D5).** `async_step_coordinator_hvac_settings` (`config_flow.py:3967-4003`) runs TWO cross-field validations against ONE `errors["base"]` slot:
1. Cover-temp hysteresis check (`:3982-3983` → `errors["base"] = "cover_temp_hysteresis_too_small"`).
2. Vacancy-grace constraint check (`:3987-3997`, guarded by `if not errors:` → `errors["base"] = "vacancy_grace_constrained_exceeds_normal"`).

Because both target the single `base` slot AND the second is gated behind `if not errors`, only ONE error surfaces per submit. An operator with BOTH violations must fix one, resubmit, see the other, and fix it — a two-trip UX. With v4.7.25 having clustered the timer Numbers AND the cover-temp pair on the same form, the probability of co-occurring violations is non-trivial.

---

## Institutional context verified

### Greps run + results (REUSED / NEW)

**Per-entry-type listener registration sites (REUSED — single function, multiple registration points):**
- `__init__.py:2365` — ROOM entry registers `_async_update_listener`
- `__init__.py:2515` — ZONE_MANAGER entry registers `_async_update_listener`
- `__init__.py:2743` — COORDINATOR_MANAGER entry registers `_async_update_listener`
- `__init__.py:2851` — generic fallback (currently in the room-coordinator path)

The listener is **shared across all three entry types**. The suppression allowlist MUST be scoped to keys that live on the CM entry; the listener must be unchanged-from-current for ROOM and ZONE_MANAGER entries unless we explicitly extend coverage there (we do not in this cycle).

**Option-key targets (REUSED, existing constants — no new CONFs):**
- `CONF_HVAC_VACANCY_GRACE_MINUTES` — `domain_coordinators/hvac_const.py:94`
- `CONF_HVAC_VACANCY_GRACE_CONSTRAINED` — `domain_coordinators/hvac_const.py:95`
- `CONF_HVAC_MAX_OCCUPANCY_HOURS` — `domain_coordinators/hvac_const.py:96`
- `CONF_HVAC_ZONE_ENTRY_DWELL` — `domain_coordinators/hvac_const.py:130`
- `CONF_DYNAMIC_PRESET_DWELL_MINUTES` — `domain_coordinators/energy_const.py:201`

**Live coordinator attrs already pushed by Number setters (REUSED):**
- `hvac._vacancy_grace`, `hvac._vacancy_grace_constrained`, `hvac._max_occupancy_hours`, `hvac._zone_entry_dwell` — all set inline by the Number setters under `if hvac is not None:` guards.
- DPM dwell: the existing setter does NOT explicitly poke a live attr — it relies on `_get_cm_options()` reading from `entry.options` on the next evaluate_and_emit (see `number.py:2182-2184` comment). Verify in the build pass whether DPM needs an explicit live-attr push to be reload-skip-safe, or whether the existing read-from-options-on-next-tick is sufficient.

**Single-`errors["base"]` sites surveyed for D5 regression-bar (REUSED):**
- `config_flow.py` carries ~15 sites that set `errors["base"] = "<key>"` and fall through to `async_show_form(..., errors=errors)`. The D5 change MUST preserve this pattern at every other site — the only modification is the SHARED save path of `async_step_coordinator_hvac_settings`. Concrete sites to spot-check during review: `errors["base"] = "duplicate_zone"` and similar zone-management validation sites; the per-step async_show_form returns are unchanged.

**Reseed-from-options surfaces (REUSED — restart-restore is already covered, NOT a new concern):**
- CM coordinator constructor: `__init__.py:1539` `cm_config = {**cm_entry.data, **cm_entry.options}` → consumed at `__init__.py:1994-2031` (HVAC constructor kwargs `vacancy_grace`, `vacancy_grace_constrained`, `max_occupancy_hours`, `zone_entry_dwell`).
- Each Number's `__init__`: `number.py:600-603`, `:414-417`, `:506-509`, `:329`, `:2156-2157`.
- DPM dwell rolling reads via `_get_cm_options()` (operator-noted at `number.py:2182-2184`).

**NEW (only one new constant proposed):**
- `OPTIONS_RELOAD_SUPPRESS_KEYS` (or equivalently named) — a frozenset of option keys that, when they are the ONLY keys changed in a CM-entry options write, suppress the full reload. **NEW** because no equivalent allowlist exists today: `grep -nE 'SUPPRESS_KEYS|RELOAD_KEYS|IN_PLACE_APPLY' custom_components/universal_room_automation/` returns no matches. Located in `__init__.py` near `_async_update_listener` for cohesion with the only function that reads it. The set's membership is verified by a unit test that imports the CONFs above and asserts each is in the set.

**NEW (cached snapshot location for diffing):**
- A `last_applied_options` snapshot per CM entry, cached at `hass.data[DOMAIN]["cm_last_applied_options"]` (or equivalent — see open question O1). **NEW** because today there is no per-entry "last applied" cache; the listener has no way to diff. Seeded at CM setup time (after the CM coordinator and all entities are constructed). Updated by the listener after every in-place apply AND after every reload-path completion.

**NEW (D5) translation keys** — two new error-translation keys in `strings.json` + `translations/en.json` under the existing `error` map for `coordinator_hvac_settings`:
- `cover_and_vacancy_combined` — combined message used when both validations fail in the same submit. **NEW**: no combined-error precedent exists today. Justification: the cover-temp and vacancy-grace error strings, when concatenated naively, exceed HA's typical inline-error length and read awkwardly; a dedicated combined message reads cleanly. Falls back to the individual key when only one fires.
- Existing `cover_temp_hysteresis_too_small` and `vacancy_grace_constrained_exceeds_normal` are REUSED.

### Prior planning docs consulted

- `docs/planning/PLANNING_hvac_presence_timer_knobs_and_options_writeback_retrofit.md` §347-428 — Part-2 deferral inventory + the B-H1 disposition at line 428 ("CM reload fan-out on rapid Number edits — ACCEPTED, not deferred. Convergent by design. A debounce timer was rejected as over-engineering (own untracked-timer hazard). Documented at the live-attr push sites.") This cycle explicitly **revisits** that acceptance with new live evidence, replacing the convergent-by-design rationale with reload suppression. The "no debounce" decision stands — we are NOT adding a timer; we are suppressing the reload by diffing keys.
- Same doc §351-371 — Part-2 retrofit inventory (EC numbers + DPM/HVAC RestoreEntity numbers + `_HVACTunableNumber` factory). This cycle's Part-1 hygiene touches one item from that list (`DynamicPresetDwellMinutesNumber`); the rest stays deferred (now scoped in the sibling `PLANNING_part2_ec_hc_options_writeback_retrofit.md`).
- Same doc §392-394 — original Tier 2 reviewer framings; carried forward to this cycle.
- Same doc §427 — A-MED-1 deferral row (verbatim: "Config-flow `errors[\"base\"]` collision (Tier-2 A-MED-1) — cover-temp and vacancy cross-field errors can't surface together (two-trip fix) … Form-UX backlog; revisit only if it bites."). The "revisit only if it bites" condition has not technically tripped, but the operator has bundled this into the suppression cycle to avoid re-litigating the form-save path twice.

### Memory bodies pulled

- `project_v4_7_25_hvac_presence_timer_knobs_live` — confirms the live setter-writeback pattern, the A-HIGH-1 bidirectional clamp, the 50→46 Switch rename, and that Part 2 (EC/HC writeback) is deferred.
- `feedback_ura_mirror_pattern` — "RestoreEntity = runtime store; entry.options = seed only; don't stomp on reload." This cycle does NOT reintroduce the mirror pattern; it sharpens the v4.7.25 doctrine flip (options = sole source of truth) by removing the only remaining footgun (the unconditional reload) without giving back canonicity to RestoreEntity. The stale `DynamicPresetDwellMinutesNumber` docstring at `number.py:2122-2123` (which still claims the v4.3.2 mirror-pattern) is fixed in D2.
- `feedback_no_fabrication` and `feedback_no_fabrication_dhcp_incident` — relevant because the design rests on a claim about HA-core `async_update_entry` behavior AND on HA's data-entry-flow error semantics. The grounding section below requires the build pass to re-verify both claims against pinned HA-core source before merge.
- `feedback_parsimonious_room_config` — no new runtime entities; no new CONFs; no new form fields. Pattern preserved.
- `feedback_pre_deploy_zero_bugs_gate` — applies to this deploy.

### Design docs read

- `docs/Coordinator/HVAC.md` (if present) — read end-to-end during the build pass to confirm `_vacancy_grace`, `_vacancy_grace_constrained`, `_max_occupancy_hours`, `_zone_entry_dwell` are all idempotent-on-rewrite live attrs (i.e., the next decision cycle reads them straight, no derived state that needs explicit recompute on assignment). If any of these has a derived shadow (e.g., a precomputed `timedelta`), the in-place apply path MUST poke the derivation too OR the live-attr push site must already do it. **Build-pass verification required; not assumed.**

### Code locations surveyed (end-to-end during scoping)

- `custom_components/universal_room_automation/__init__.py:3521-3542` — `_async_update_listener`.
- `custom_components/universal_room_automation/__init__.py:2365`, `:2515`, `:2743`, `:2851` — listener registration sites across entry types.
- `custom_components/universal_room_automation/__init__.py:1538-1539`, `:1994-2031` — CM setup reseeding from options.
- `custom_components/universal_room_automation/number.py:280-470` — `ZoneEntryDwellNumber`, `VacancyGraceMinutesNumber` (incl. A-HIGH-1 clamp).
- `custom_components/universal_room_automation/number.py:467-558` — `VacancyGraceConstrainedNumber` (incl. unidirectional clamp).
- `custom_components/universal_room_automation/number.py:561-630` — `MaxOccupancyHoursNumber`.
- `custom_components/universal_room_automation/number.py:2115-2194` — `DynamicPresetDwellMinutesNumber` (RestoreEntity + writeback, stale docstring).
- `custom_components/universal_room_automation/button.py` ~643-674 — `51 Reset` button (writes all four timer defaults in one `async_update_entry`).
- `custom_components/universal_room_automation/config_flow.py:2054` (`UniversalRoomAutomationOptionsFlow`) — the form path. Key indices verified at `:3924-4301` (timer keys) and `:4359-4591` (DPM dwell key). The form writes options via the OptionsFlow base machinery, which also fires the listener.
- `custom_components/universal_room_automation/config_flow.py:3960-4003` — D5 target: the `async_step_coordinator_hvac_settings` save path with the two single-`base` validations.

---

## Verified HA best-practice facts (grounding — re-verify in build pass before merge)

1. **`async_update_entry` short-circuits on no-change.** HA core sets a `changed` flag and returns early (no `_async_save_and_notify`, no listener dispatch) when nothing actually changed. Source to re-verify: `homeassistant/config_entries.py` on the pinned HA-core version. (`https://github.com/home-assistant/core/blob/dev/homeassistant/config_entries.py`.) **Why it matters here:** repeated identical writebacks from the Number setter are already free — but mixed-key writes still fire the listener. Our diff has to be key-set-aware, not value-equality-only.
2. **Combining a config-entry update listener with `async_update_reload_and_abort` is deprecated in HA Core 2026.6, becomes an error in 2026.12.** Source to re-verify: https://developers.home-assistant.io/blog/2026/05/07/config-entry-listener-together-with-reloading-methods/ . **URA does NOT currently trip this** — grep this session confirmed no `async_update_reload_and_abort` in `config_flow.py` and no `options_flow.py` file. But the deprecation direction (apply options in place, avoid full reload) is the same direction this plan takes. Reference it in the design rationale, not as a forcing function.
3. **`ConfigEntry.data` / `ConfigEntry.options` must never be mutated directly.** Source: https://developers.home-assistant.io/docs/config_entries_index/ . The in-place apply path MUST go through `async_update_entry` for the persist, and only read `entry.options` after the write returns.
4. **(NEW for D5) HA data-entry-flow `errors` dict can carry multiple entries simultaneously.** Verified this session via `https://developers.home-assistant.io/docs/data_entry_flow_index` (fetched 2026-06-06): "Each key in the error dictionary refers to a field name that contains the error. Use the key `base` if you want to show an error unrelated to a specific field." Multiple keys CAN coexist (e.g., `{"username": "invalid_format", "password": "too_short", "base": "auth_failed"}`).
5. **(NEW for D5, UNVERIFIED) Field-attached error rendering inside a `section(...)` is NOT documented.** The developer docs do not state whether errors keyed to a field name INSIDE a `section(...)` block render correctly in the HA frontend. A known-issue search surfaced `home-assistant/frontend#21887` ("Config flow - translation section does not work properly") which suggests sectioned UX has rough edges. The frontend source `step-flow-form.ts` would need to be read to confirm. **Do NOT assert rendering behavior we have not confirmed.** D5's chosen approach (option (a) — combined `errors["base"]`) is the safe path that does NOT depend on this unverified behavior.

If any of facts 1-3 fails to re-verify against the pinned HA-core source at build time, STOP and surface the gap. Fact 5 stays "verified-as-unverified" — the chosen design avoids relying on it.

---

## Restart-restore — already covered, stated for completeness

Values persist across HA restart without any reload (and without any RestoreEntity, except the legacy DPM dwell case being fixed in D2):
- Options live in `.storage/core.config_entries` and survive process restart by definition.
- On CM setup, `cm_config = {**cm_entry.data, **cm_entry.options}` (`__init__.py:1539`) re-seeds the HVAC constructor (`__init__.py:1994-2031`).
- Each Number `__init__` re-seeds `self._value` from `{**entry.data, **entry.options}` (`number.py:600-603`, `:414-417`, `:506-509`, `:329`, `:2156-2157`).

No new RestoreEntity is introduced. No new Store is introduced. The D2 hygiene REMOVES `RestoreEntity` from `DynamicPresetDwellMinutesNumber` — the option write done by the existing setter is sufficient for persistence; the restore branch at `:2171-2178` is currently a tiebreaker on stale state that conflicts with options-as-sole-source-of-truth.

---

## Design approach

Single apply-point in the listener, with key-set diff against a cached snapshot.

**Suppress-keys allowlist (NEW constant `OPTIONS_RELOAD_SUPPRESS_KEYS`, in `__init__.py` near the listener):**

```
frozenset({
    CONF_HVAC_VACANCY_GRACE_MINUTES,
    CONF_HVAC_VACANCY_GRACE_CONSTRAINED,
    CONF_HVAC_MAX_OCCUPANCY_HOURS,
    CONF_HVAC_ZONE_ENTRY_DWELL,
    CONF_DYNAMIC_PRESET_DWELL_MINUTES,
})
```

**Cached snapshot:** `hass.data[DOMAIN]["cm_last_applied_options"][entry.entry_id]` (the entry_id index is defensive — see O1 below). Seeded at the END of CM setup (`__init__.py` ~2743, immediately after listener registration), holding a deep-copy of `dict(entry.options)`. Updated after every in-place apply AND after every reload-path completion.

**Listener decision tree (CM entry only):**

```
on _async_update_listener(hass, entry):
    if entry.entry_id is NOT a CM entry:
        # current behavior unchanged for ROOM / ZONE_MANAGER entries
        schedule_full_reload(); return

    old = cm_last_applied_options.get(entry.entry_id) or {}
    new = dict(entry.options)
    changed_keys = {k for k in (old.keys() | new.keys()) if old.get(k) != new.get(k)}

    if not changed_keys:
        return  # no-op (defensive; HA core should already short-circuit)

    if changed_keys.issubset(OPTIONS_RELOAD_SUPPRESS_KEYS):
        apply_in_place(hass, entry, changed_keys, new)
        cm_last_applied_options[entry.entry_id] = new
        return

    # mixed or non-allowlisted change → full reload (existing behavior)
    schedule_full_reload()
    # snapshot will be reseeded at the END of the next CM setup
```

**`apply_in_place(hass, entry, changed_keys, new)`** is a pure dispatch on key → live-attr-poke against the existing CM coordinators. Each branch is idempotent and tolerant of a missing coordinator (early-return if HVAC / EC not registered):
- `CONF_HVAC_VACANCY_GRACE_MINUTES` → `hvac._vacancy_grace = int(new[...])`
- `CONF_HVAC_VACANCY_GRACE_CONSTRAINED` → `hvac._vacancy_grace_constrained = int(new[...])`
- `CONF_HVAC_MAX_OCCUPANCY_HOURS` → `hvac._max_occupancy_hours = int(new[...])`
- `CONF_HVAC_ZONE_ENTRY_DWELL` → `hvac._zone_entry_dwell = int(new[...])`
- `CONF_DYNAMIC_PRESET_DWELL_MINUTES` → energy/DPM live-attr push (verify exact attr in build pass) OR rely on `_get_cm_options()` next-tick read.

**Critically:** `apply_in_place` is the SOLE apply-point on the suppressed path. The Number setters already do the live-attr push for their own key, which makes the entity path doubly safe (idempotent re-poke from the listener after the setter already poked). The OptionsFlow form path does NOT poke any live attr, so for form edits the listener's `apply_in_place` IS the live-attr push. This unifies the two paths.

**A-HIGH-1 clamp invariant under form edits.** The clamp today lives in two places: `VacancyGraceMinutesNumber.async_set_native_value` (`number.py:444-461`, clamps `_constrained` down when normal drops) and `VacancyGraceConstrainedNumber.async_set_native_value` (`number.py:531-546`, clamps user input up to `<= normal`). The OptionsFlow form has its own validation at `config_flow.py:3989-4275` enforcing the same invariant at submit time. The in-place apply path in this plan does NOT need to re-clamp because:
1. Entity setter path: clamp runs in the setter BEFORE `async_update_entry`, so by the time the listener sees `entry.options` the pair is already consistent.
2. Form path: form validation rejects an inverted pair at submit, so the options write never contains an inverted pair.

The plan must verify both of these claims in the build pass and add an assertion-style unit test that the listener path never observes `vacancy_grace_constrained > vacancy_grace`. If the verification fails for either path, the in-place apply MUST re-clamp.

---

## Deliverables

### D1: Per-CM-entry last-applied-options snapshot

Add a per-CM-entry options snapshot at `hass.data[DOMAIN]["cm_last_applied_options"][entry.entry_id]`. Seeded at end of CM setup (after `entry.async_on_unload(entry.add_update_listener(...))` at `__init__.py:2743`). Cleared in CM teardown (`async_unload_entry`). Updated after every in-place apply (D3) and at end of every CM setup completion (covering the reload path).

#### Acceptance Criteria
- **Verify:** After cold boot, `hass.data[DOMAIN]["cm_last_applied_options"][cm_entry.entry_id]` exists and equals `dict(cm_entry.options)`.
- **Verify:** After CM reload, the snapshot is reseeded to the post-reload `entry.options`.
- **Verify:** After CM unload, the entry_id key is removed from the dict.
- **Test:** `test_cm_last_applied_options_seeded_at_setup`, `test_cm_last_applied_options_cleared_at_unload`, `test_cm_last_applied_options_reseeded_after_reload`.
- **Live:** N/A (internal cache; covered by D3 live criteria).

### D2: Part-1 hygiene — drop RestoreEntity from `DynamicPresetDwellMinutesNumber` + fix stale docstring

Drop `RestoreEntity` from the class signature at `number.py:2115`. Delete the restore branch in `async_added_to_hass` at `:2171-2178`. Rewrite the docstring at `:2122-2123` to match the options-sole-source pattern, e.g. "entry.options is the SOLE source of truth (no RestoreEntity). Writes go through `async_update_entry`; restart re-seeds via the constructor's `{**entry.data, **entry.options}` read."

Audit `number.py` for any OTHER Number that inherits `RestoreEntity` AND also calls `async_update_entry` in its setter. **REUSED grep:** `grep -nE 'class .*RestoreEntity' custom_components/universal_room_automation/number.py` cross-referenced with `grep -nE 'async_update_entry' custom_components/universal_room_automation/number.py`. The Part-2 deferral inventory (`PLANNING_part2_ec_hc_options_writeback_retrofit.md`) lists the candidates. **In-scope decision (recommend):** these stay in Part 2 — they are NOT covered by the suppress-keys allowlist this cycle. The audit's purpose is to confirm no UNLISTED class is doing dual-source.

#### Acceptance Criteria
- **Verify:** `DynamicPresetDwellMinutesNumber` no longer inherits `RestoreEntity` and no longer has an `async_added_to_hass` body that reads `async_get_last_state`.
- **Verify:** Docstring matches the options-sole-source pattern (lockstep with sibling Numbers' docstrings).
- **Verify:** Audit script output (or test) confirms no Number class outside the deferred Part-2 list inherits `RestoreEntity` AND calls `async_update_entry`.
- **Sensor:** `number.ura_hvac_coordinator_dynamic_preset_dwell_minutes` retains its `unique_id` and `entity_id`, displays the persisted value after restart.
- **Test:** `test_dpm_dwell_no_restoreentity`, `test_dpm_dwell_persists_via_options_write`, `test_dpm_dwell_seeds_from_options_after_restart`.
- **Live:** Edit `03 Dynamic Preset Dwell` from 60 → 90; restart HA; entity reads 90 post-restart.

### D3: Reload suppression in `_async_update_listener` for allowlisted CM-option keys

Add `OPTIONS_RELOAD_SUPPRESS_KEYS` constant in `__init__.py` next to the listener. Modify `_async_update_listener` to:
1. Early-return if the entry is NOT a CM entry (preserve current behavior for ROOM / ZONE_MANAGER).
2. Compute `changed_keys` by diffing `entry.options` against `hass.data[DOMAIN]["cm_last_applied_options"][entry.entry_id]`.
3. If `changed_keys ⊆ OPTIONS_RELOAD_SUPPRESS_KEYS` and non-empty → call `apply_in_place(...)`, update the snapshot, return.
4. Otherwise → schedule full reload (existing untracked-task pattern per `__init__.py:3540-3542`, B-CRIT-1 invariant preserved).

`apply_in_place` is a small helper in `__init__.py` that dispatches on key → live-attr poke against `coordinator_manager.coordinators["hvac"]` / `["energy"]`, tolerating `None`.

#### Acceptance Criteria
- **Verify:** Editing a single timer Number triggers ZERO `async_reload` calls on the CM entry (assert via test spy on `hass.config_entries.async_reload`).
- **Verify:** Editing a non-allowlisted CM option (e.g. `CONF_PRESENCE_ENABLED`) STILL triggers `async_reload` (regression guard).
- **Verify:** A single `async_update_entry` write that changes BOTH a suppress-key AND a non-suppress-key triggers `async_reload` (mixed-change guard).
- **Verify:** Editing a Number on a ROOM entry (e.g. `TimeoutOverrideNumber`) STILL triggers `async_reload` (ROOM-entry untouched).
- **Verify:** After `apply_in_place`, the live coordinator attr equals the new value (`hvac._max_occupancy_hours == 8` after writing 8).
- **Verify:** After `apply_in_place`, `cm_last_applied_options[entry_id][key]` equals the new value.
- **Verify:** A second identical write produces `changed_keys == set()` and is a no-op (defensive — HA core already short-circuits at the `async_update_entry` layer).
- **Test:** `test_listener_suppresses_reload_for_allowlisted_keys`, `test_listener_reloads_for_non_allowlisted_keys`, `test_listener_reloads_for_mixed_change`, `test_listener_unchanged_for_room_entries`, `test_apply_in_place_updates_live_attrs`, `test_apply_in_place_updates_snapshot`, `test_clamp_invariant_holds_after_in_place_apply`.
- **Live:** Edit `48 Zone Vacancy Delay` 20 → 25 via the entity. `last_changed` on Numbers 49, 50, 61 does NOT advance (use the HA `recorder` or entity attribute card). `hvac._vacancy_grace` is 25 (visible via the HVAC Coordinator sensor's attribute or a debug log entry). After HA restart, the entity reads 25. iOS app shows NO "connection lost" toast.
- **Live (form path):** Open the CM OptionsFlow, edit `vacancy_grace_minutes` 20 → 30, submit. `48` Number updates to 30 within a few seconds (listener pushed live attr). Numbers 49, 50, 61 do NOT have a fresh `last_changed`.
- **Live (clamp):** Edit `48` 30 → 15. Number `49`'s value clamps to 15 in the same write (existing A-HIGH-1 behavior preserved). `last_changed` on 49 advances because its value actually changed; `last_changed` on 50 and 61 does NOT.
- **Live (reset button):** Press `51 Reset`. All four timer Numbers reset to defaults. NO full reload (changed_keys ⊆ suppress set). `last_changed` advances on each of the four because their values actually changed; other CM entities (e.g. presence-coordinator entities) do NOT have fresh `last_changed`.

### D4: Documentation lockstep + Part-2 backlog memo

- Update `docs/Coordinator/HVAC.md` (if a coordinator design doc exists or is being maintained) with a short "Runtime-tunable option keys" subsection enumerating the five suppress-keys + the in-place apply contract (live-attr push is idempotent; options is sole source of truth; no Store / no RestoreEntity).
- Update the v4.7.25 README's "Validated" table footer with a back-reference to this cycle's planning doc (operator request when this ships: note that B-H1 was revisited and resolved with reload suppression, not debounce).
- Write a backlog memo titled "CM in-place option apply — extend allowlist to remaining runtime-tunable Numbers" capturing the Part-2 candidates from the v4.7.25 planning doc §351-371: each candidate's CONF key, its live-attr target, and the live-attr push that would need to move from the entity setter into the listener's `apply_in_place` to support form-path edits. (Tracked concretely in the sibling `PLANNING_part2_ec_hc_options_writeback_retrofit.md`.)
- Update `docs/QUALITY_CONTEXT.md`: consider a new bug class entry "Unnecessary full-entry reload from listener on runtime-tunable option write." Phrase as a recurrence pattern: "Update listener calls `async_reload` unconditionally → wide blast radius on tiny user edit → frontend backpressure spikes." Decide during the post-review documentation step (per CLAUDE.md), not in this planning doc.

#### Acceptance Criteria
- **Verify:** All four docs updated (or backlog memo filed for the QUALITY_CONTEXT.md decision).
- **Live:** N/A (docs-only).

### D5: Resolve A-MED-1 — surface both cover-temp and vacancy-grace cross-field violations in a single submit

**Files:** `custom_components/universal_room_automation/config_flow.py`, `custom_components/universal_room_automation/strings.json`, `custom_components/universal_room_automation/translations/en.json`.

**Problem (verified):** `async_step_coordinator_hvac_settings` (`config_flow.py:3967-4003`) runs two cross-field validations against ONE `errors["base"]` slot. The second is gated behind `if not errors:` so only one ever surfaces per submit. Operator with both violations must fix one, resubmit, see the other.

**Design — option (a): accumulate both base messages into a combined `errors["base"]`.** Chosen over option (b) field-attached errors because field-attached error rendering inside a `section(...)` block is NOT documented in the HA developer docs (verified this session at `https://developers.home-assistant.io/docs/data_entry_flow_index`; the docs confirm multiple-error support but don't address section interaction). Frontend issue `home-assistant/frontend#21887` ("Config flow - translation section does not work properly") confirms sectioned UX has known rough edges. Per the No-Fabrication rule, we do NOT assert rendering behavior we haven't confirmed. Option (a) uses the documented and battle-tested `errors["base"]` channel.

**What we verified vs. didn't:**
- VERIFIED: `errors` dict supports multiple simultaneous keys (HA dev docs, fetched 2026-06-06).
- VERIFIED: `errors["base"]` renders as a non-field-attached banner above the form (used at ~15 sites in URA's own config_flow.py).
- NOT VERIFIED: whether a field-attached error key INSIDE a `section(...)` (e.g. `errors[CONF_HVAC_VACANCY_GRACE_CONSTRAINED]` where that field lives in the `presence_timing` section) renders correctly. Frontend source `step-flow-form.ts` would need to be read to confirm. The chosen design avoids this dependency.

**Change.**

1. In `config_flow.py:3967-4003`, replace the two single-`base` assignments with an accumulator:
   ```python
   errors: dict[str, str] = {}
   error_keys: list[str] = []  # accumulator
   if user_input is not None:
       advanced = user_input.pop("presence_timing", None)
       if isinstance(advanced, dict):
           user_input = {**user_input, **advanced}

       close_temp = float(user_input.get(
           CONF_HVAC_COVER_CLOSE_TEMP, DEFAULT_HVAC_COVER_CLOSE_TEMP,
       ))
       open_temp = float(user_input.get(
           CONF_HVAC_COVER_OPEN_TEMP, DEFAULT_HVAC_COVER_OPEN_TEMP,
       ))
       if close_temp - open_temp < COVER_HYSTERESIS_MIN_GAP:
           error_keys.append("cover_temp_hysteresis_too_small")

       # No longer gated behind `if not errors:` — both checks always run.
       grace = int(user_input.get(
           CONF_HVAC_VACANCY_GRACE_MINUTES, DEFAULT_VACANCY_GRACE_MINUTES,
       ))
       grace_constrained = int(user_input.get(
           CONF_HVAC_VACANCY_GRACE_CONSTRAINED, DEFAULT_VACANCY_GRACE_CONSTRAINED,
       ))
       if grace_constrained > grace:
           error_keys.append("vacancy_grace_constrained_exceeds_normal")

       if error_keys:
           # Two-failure case: use a dedicated combined message that names
           # BOTH violations clearly. Single-failure case: reuse the
           # existing individual key so the existing translation is reused.
           if len(error_keys) >= 2:
               errors["base"] = "cover_and_vacancy_combined"
           else:
               errors["base"] = error_keys[0]
       else:
           return self.async_create_entry(
               title="",
               data={**self._config_entry.options, **user_input},
           )
   ```

2. Add the new translation key `cover_and_vacancy_combined` under `coordinator_hvac_settings.error` in BOTH `strings.json` and `translations/en.json`. Draft:
   ```
   "cover_and_vacancy_combined": "Two settings need fixing: Cover Open Temp must be at least 3°F below Cover Close Temp, AND Energy-Saving Zone Vacancy Delay must be ≤ the normal Zone Vacancy Delay."
   ```
   The wording names both violations so the operator sees both in one banner.

3. **Regression-bar (no other site touched).** Confirm the ~15 other `errors["base"] = "<key>"` sites in `config_flow.py` are UNCHANGED. The single-base convention is preserved everywhere except this one save path, where both violations are intentionally surface-able together.

#### D5 Acceptance Criteria
- **Verify:** Submitting the HVAC tuning form with BOTH violations (cover-temp gap too small AND `vacancy_grace_constrained > vacancy_grace`) returns the form with `errors["base"] == "cover_and_vacancy_combined"` in ONE submit (no second trip needed).
- **Verify:** Submitting with ONLY the cover-temp violation returns `errors["base"] == "cover_temp_hysteresis_too_small"` (existing behavior preserved).
- **Verify:** Submitting with ONLY the vacancy violation returns `errors["base"] == "vacancy_grace_constrained_exceeds_normal"` (existing behavior preserved).
- **Verify:** Valid input still calls `async_create_entry` and persists.
- **Verify:** No other config_flow.py site that uses `errors["base"]` is modified — single-base convention preserved at the ~15 other sites.
- **Verify:** Both `strings.json` and `translations/en.json` carry the new `cover_and_vacancy_combined` key (lockstep test from D6 of the prior cycle).
- **Sensor:** N/A — config-flow UX.
- **Test:** `test_hvac_settings_form_surfaces_both_errors_in_single_submit` (both violations → combined key), `test_hvac_settings_form_single_cover_error_unchanged`, `test_hvac_settings_form_single_vacancy_error_unchanged`, `test_strings_and_translations_carry_combined_key`.
- **Live:** Open URA → HVAC Coordinator → Configure → HVAC Tuning. Set Cover Close Temp = 80, Cover Open Temp = 78 (gap 2, < 3 minimum) AND Vacancy Grace = 10, Energy-Saving Vacancy Grace = 20. Submit. ONE banner appears citing BOTH violations. Fix both, submit, form saves successfully. Repeat with only one violation at a time → the existing single-violation message renders as before.

---

## Critical edge cases (each MUST be covered by a test in D3 or D5)

1. **OptionsFlow form path.** A form submission that changes only suppress-allowlisted keys must trigger `apply_in_place` (not reload). Today the form path relies on the listener for any apply; with this change the listener IS the apply. Verified via `test_form_edit_to_suppress_key_applies_in_place`.
2. **Mixed-key form submission.** A form submission that changes both `CONF_HVAC_VACANCY_GRACE_MINUTES` AND `CONF_PRESENCE_ENABLED` must trigger full reload. The user might submit a form with several fields edited; the dominant action wins. Verified via `test_mixed_change_falls_back_to_reload`.
3. **A-HIGH-1 bidirectional clamp.** The clamp today happens INSIDE `VacancyGraceMinutesNumber.async_set_native_value` BEFORE `async_update_entry`, so the listener sees an already-consistent pair. The form path has its own validation. Document and assert this. If the verification finds a path that could write an inverted pair (e.g. a future YAML-import path), the in-place apply MUST re-clamp.
4. **Rapid multi-edit / concurrency.** Two rapid `set_value` calls from different sources (entity + form) may race. The setter's clamp is sync within one call; `async_update_entry` is awaited; the listener fires on each completed write. Verified that the cached snapshot is updated under the same single-threaded asyncio loop after each apply, so no torn state.
5. **Reset button.** `51 Reset` writes all four timer defaults in one `async_update_entry`. `changed_keys` is a subset of the allowlist (or empty if already at defaults); `apply_in_place` runs once, no reload. The current button code at `button.py` ~643-674 may push live attrs itself (verify) — if not, the listener's `apply_in_place` handles it.
6. **CM entry teardown mid-flight.** If the CM entry is being unloaded while a knob edit is in flight, the listener may try to apply to a coordinator that is being torn down. `apply_in_place` already early-returns on missing coordinators. Test `test_apply_in_place_safe_when_coordinator_missing`.
7. **Snapshot drift after an external `entry.options` mutation.** No code path outside `async_update_entry` should mutate `entry.options` (per HA core rule), but if one is found in URA, it would skip the listener and leave the snapshot stale. Audit `grep -rn 'entry.options\['` and confirm no in-place mutation. Defensive: the snapshot is also reseeded at the end of every CM setup, so a stale snapshot self-heals on the next non-suppressed reload.
8. **Boot-time race.** The listener is registered at `__init__.py:2743`, AFTER the snapshot must be seeded. Ensure seeding happens BEFORE listener registration to avoid a between-register-and-seed knob edit firing with no snapshot. The listener's `old = ... or {}` fallback degrades to "all keys look new" → falls into the suppress branch if all-new keys are allowlisted, otherwise reload. Either outcome is safe.
9. **(D5) Form path interaction with reload suppression.** D5 changes the form save path to surface both errors; the resulting `async_create_entry` write is unchanged in shape, so the listener (after D3) still classifies the write correctly. If the form submit edits ONLY suppress-allowlisted keys, the listener applies in place; if it edits a mix, it reloads. D5 does NOT change which path the listener takes — only what the operator sees when validation rejects.

---

## Tier classification

**Decision: operator-elevated Tier 2-DB (three parallel reviews, framing-disjoint).**

Per the URA CLAUDE.md "Operator-elevated Tier 2-DB" clause, the operator may elevate any cycle to Tier 2-DB even when the standard structural triggers (DB schema change, ≥3 DAO migration, payload-shape change, behavioral fixture against real schemas, planned migration follow-up) do not fire. The standard justification is **trust-hierarchy ripple** — situations where a small surgical fix risks regressions across multiple coordinators.

**Operator elevation rationale (recorded here for reviewers):**
- The CM reload path's blast radius spans EVERY coordinator on the CM entry: presence, HVAC, energy, safety, diagnostics, house_state, signals. A wrong diff/dispatch decision in `_async_update_listener` either (a) skips a reload that was actually needed, leaving downstream-derived state stale across all of those coordinators, or (b) reloads when an apply-in-place was correct, regressing the very UX cost this cycle exists to fix.
- The operator has set a high robustness bar — verbatim: *"must be robust, no bugs in this very basic high traffic system."* The listener fires on every knob edit, the reset button, every form submit, and indirectly on every restart-path completion. It is high-traffic per the operator's framing.
- The shared-listener registration across THREE entry types (ROOM, ZONE_MANAGER, CM at `__init__.py:2365 / :2515 / :2743`) means a regression on the CM branch can leak to ROOM/ZONE_MANAGER paths if the entry-type guard is wrong.
- D5 changes a form save path that gates persistence behind cross-field validation; a regression here silently weakens the data-integrity invariant the A-HIGH-1 clamp enforces.

**Three-reviewer framing-disjoint protocol applies.** Run reviews in PARALLEL; framings must NOT overlap, per the Tier 2-DB rule that "different framings can't share blind spots."

**Review A — Correctness + the old/new options diff + clamp invariant + A-MED-1 combined-error.**
Focus: allowlist membership is exactly the five intended CONFs (one assertion per CONF, no fewer / no extras); the diff classifies single-key, multi-key-all-allowlisted, mixed-key, and no-change cases correctly; ROOM and ZONE_MANAGER entry behavior is byte-identical pre/post; A-HIGH-1 bidirectional clamp invariant is preserved across BOTH entity setter and form-save paths AND the listener path never observes `vacancy_grace_constrained > vacancy_grace`; D2 `RestoreEntity` removal does not strand a pre-existing `last_state` (first post-deploy boot reads options, not stale recorder); D5 accumulator runs both checks always (no remaining `if not errors:` gate); single-violation paths are byte-identical to pre-D5; combined-key path triggers ONLY when both fail in the same submit.

**Review B — Async + HA-lifecycle + listener-as-apply-point + reload-skip race + Bug Class #46 / B-CRIT-1 untracked-task.**
Focus: snapshot seeding ordering relative to listener registration (seed MUST happen before listener can fire); snapshot lifecycle across CM unload / reload / setup-failed-then-retry; `apply_in_place` defensive against missing or mid-teardown coordinators; the untracked-task pattern at `__init__.py:3540-3542` is preserved on the reload branch — no new untracked timer or task introduced (Bug Class #46 / B-CRIT-1 invariant from v4.7.18 / v4.7.20.1); concurrent entity+form edits do not corrupt the snapshot (single-threaded asyncio assumed but explicitly tested); form-path edits that converge with rapid entity-path edits land in a consistent final state; the reload-skip branch cannot re-enter itself before the prior `apply_in_place` completes; restart path correctly reseeds the snapshot at end of CM setup.

**Review C — New surfaces (allowlist constant, cached-snapshot store) + restart/seed round-trip + test-fixture authority.**
Focus: `OPTIONS_RELOAD_SUPPRESS_KEYS` is colocated with the only function that reads it (cohesion); the snapshot location at `hass.data[DOMAIN]["cm_last_applied_options"][entry.entry_id]` is consistent with the rest of URA's hass.data conventions and is correctly cleared at unload; restart round-trip is end-to-end clean (cold boot → snapshot seeded from options → operator edit → listener applies in place → restart → snapshot reseeded from options that now contain the edit → entity reads the edited value); D2 docstring rewrite and translation keys are present in BOTH `strings.json` AND `translations/en.json` (lockstep); test fixtures DRIVE the real listener and real `apply_in_place` (never hand-copy logic into the test); the new tests in D1+D3+D5 cover the exact branches the planning doc names (one-to-one mapping of acceptance criterion → test name).

Run the three reviews in PARALLEL. Fix every CRITICAL and HIGH finding before deploy. If fix-up substantially mutates the new surfaces, run a focused fourth review on those surfaces.

**Live Validation (Review D)** per the Tier 2-DB protocol: post-restart, verify that at least one suppressed apply-in-place path executed end-to-end (entity edit → live-attr poke verified → no `async_reload` log line → snapshot updated → restart-persistence confirmed). Sentinels-only validation (the "form submitted, value persisted" check alone) is INSUFFICIENT — must also prove the reload was actually suppressed (sibling-Number `last_changed` not advanced is the authoritative live signal).

---

## Plan completion tracking — explicit deferral list

| Item | Why deferred | Where tracked |
|---|---|---|
| Extend `OPTIONS_RELOAD_SUPPRESS_KEYS` to cover the Part-2 EC + DPM/HVAC Numbers (the full EC family + DPM hysteresis + HVAC egress pause/resume + fan-interference hold + the `_HVACTunableNumber` and `_HVACZoneKwhThresholdNumber` factories) | Operator-deferred from v4.7.25 (Part 2). Bundling here doubles the test surface. Each item needs its live-attr target verified and possibly an `apply_in_place` branch added. | `PLANNING_part2_ec_hc_options_writeback_retrofit.md` (sibling doc this session). |
| Per-room Number retrofit (`TimeoutOverrideNumber`, `ComfortTempMinNumber`, `ComfortTempMaxNumber`, `ComfortHumidityMaxNumber`) | These live on ROOM entries; their listener path is intentionally unchanged this cycle. Operator must decide whether ROOM-entry suppress-keys is in scope at all. See O2 below. Notable: ComfortTempMin/Max have NO persistence today (no RestoreEntity, no async_update_entry). | Open question; tracked in `PLANNING_part2_ec_hc_options_writeback_retrofit.md` Open-Questions section. |
| Field-attached error rendering inside `section(...)` blocks (D5 option (b)) | Rendering behavior NOT verified against HA frontend source this session. Combined-base-error (option (a)) chosen as the safe documented path. Revisit only if combined-base UX proves inadequate. | D5 design notes (above). |
| `QUALITY_CONTEXT.md` new bug class entry | Post-review documentation step per CLAUDE.md; happens after Tier 2-DB review. | D4 + post-review step. |
| Version assignment | Per operator convention. | Deploy step. |
| Debouncing rapid edits | Explicitly rejected by v4.7.25 review (own untracked-timer hazard) and not needed once the reload is suppressed. | Closed; not deferred. |

**Items NOT deferred but explicitly considered and rejected this cycle:**
- Bundling Part 2 here (EC + remaining DPM/HVAC RestoreEntity Numbers). Operator framing from v4.7.25: "HVAC is the reference implementation." We have ONE shipped reference (v4.7.25); this cycle hardens it before extending. Bundling Part 2 inflates scope and test surface and risks a second deferral if review finds problems.
- Option (b) field-attached errors for D5. Not verified to render inside a `section(...)`; chose option (a) combined-base per No-Fabrication.

---

## Open questions for operator (must be resolved before build)

- **O1.** Cached-snapshot location: `hass.data[DOMAIN]["cm_last_applied_options"][entry.entry_id]` vs `entry.runtime_data` (HA 2024.4+). `runtime_data` is the modern pattern and naturally cleared on unload; `hass.data` is what URA uses today across the integration. Recommendation: **use `hass.data[DOMAIN]["cm_last_applied_options"]`** for consistency with the rest of URA (see `hass.data[DOMAIN]["coordinator_manager"]`, `["weather_manager"]`, `["zone_manager_entry"]`). Confirm before build.
- **O2.** ROOM-entry scope: should ROOM-entry options writes also be eligible for reload suppression? The four per-room Numbers (`TimeoutOverrideNumber`, `ComfortTempMinNumber`, `ComfortTempMaxNumber`, `ComfortHumidityMaxNumber`) each fire a full ROOM reload on edit today. Same UX cost potentially applies (multiple-room concurrent edits could push the socket). Recommendation: **explicitly OUT of scope this cycle** to keep the change surgical; revisit in Part 2 once the CM-only pattern has soaked. Confirm before build.
- **O3.** DPM dwell live-attr push: does the EC / DPM coordinator need an explicit live-attr poke in `apply_in_place`, or does the existing `_get_cm_options()` read-on-next-tick (see `number.py:2182-2184` comment) suffice for form-path edits to apply within a reasonable latency? **Build pass must verify** by reading the DPM evaluate-and-emit cadence; if the next-tick read is > 5 seconds out, add an explicit poke. Confirm latency expectation with operator.
- **O4.** Tier elevation to 2-DB: **RESOLVED** — operator elevated. See "Tier classification" section above.
- **O5 (D5).** Combined-message wording. Draft above ("Two settings need fixing: …") is functional but verbose. Operator may prefer a terser phrasing. Confirm or revise at build time.

---

## Pre-deploy zero-bugs gate (per `feedback_pre_deploy_zero_bugs_gate`)

Before running `./scripts/deploy.sh <assigned-version> <summary> <release-notes>`:
1. `git grep -nE '<<<<<<< |>>>>>>> '` — no merge conflict markers.
2. `python3 -m py_compile` on every changed `.py` (`__init__.py`, `number.py`, `config_flow.py`, and any test files).
3. `PYTHONPATH=quality python3 -m pytest quality/tests/ -v` — all D1+D2+D3+D5 tests pass + baseline diff CLEAN against `pre-review-v<assigned>`.
4. Re-verify the three HA best-practice claims in the grounding section against the pinned HA-core source. Re-verify the data-entry-flow `errors` dict multi-key support (fact 4) against `homeassistant/data_entry_flow.py`.
5. Verify HACS installed_version matches the assigned version post-deploy; restart HA; run D2 + D3 + D5 live acceptance criteria.

---

## Post-deploy README validation table

Per the URA "Record Live Validation Back Into the README" rule, `README_v<assigned>.md` MUST be updated after live validation with an observed-results table:
- One row per Live acceptance criterion in D2, D3, and D5.
- PASS / FAIL + concrete evidence: entity_id + `last_changed` timestamps (proving sibling Numbers were NOT re-stamped); the live `hvac._vacancy_grace` value read; log scan for any `Options changed for ... scheduling reload` line that should NOT appear during a suppress-eligible edit; iOS app "no connection lost toast" observation; screenshot or recorded text of the combined-error banner from D5.
- Cite the authoritative signal actually used.

A cycle is not closed until its README carries the post-restart validation table.
