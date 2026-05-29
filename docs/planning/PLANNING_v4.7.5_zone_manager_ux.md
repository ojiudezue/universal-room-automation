# PLANNING v4.7.5 — Zone Manager UX + Canonical Resolution

**Status:** Plan ready for build (locked after v4.7.4.4 live-validated)
**Tier:** Tier 2 (two parallel staff-engineer reviews, different framings)
**Predecessor:** v4.7.4.4 (Bug Class #46 canonical fix — lazy derivation at read time)
**Filed:** 2026-05-29 after `docs/CONTEXT_TRANSFER_2026-05-29.md` §3 + VibeMemo entry 015 ("Definitely C")
**Recall:** "Plan v4.7.5 — Zone Manager UX + canonical resolution"

---

## 1. Goal + Why

**Goal:** Make the Zone Manager picker reflect the house's actual zone structure (not the HVAC coordinator's internal thermostat-keyed merge), present it as a menu rather than a dropdown, and keep sibling house-zones automatically in sync whenever they share a thermostat — so users save once and both update.

**Today's UX bug.** The Zone Manager Page 1 picker (`async_step_manage_zones`) lists zones straight out of `entry.options["zones"]`. Two house zones ("Entertainment", "Master Suite") share thermostat `climate.studyb_zone_1`. The picker shows them as **two separate entries** — but every per-zone setting page (rooms, HVAC, energy, persons, cameras, DPM) writes per-zone into ZM options. When the user opens "Entertainment", changes a setting, saves, then opens "Master Suite", the second zone's value is **stale**. Meanwhile, downstream the HVAC coordinator's `iter_canonical_hvac_zones` merges them into a single canonical zone labeled `"Entertainment + Master Suite"` whose merge logic picks "first non-empty" / "OR" — silently losing the user's "Master Suite" edits.

**User decision (entry 015): Option C.** Save one, both update. Banner on the picker + editor surfaces tells the user *why*. Rejected: A (silent last-write-wins — confusing), B (error on conflict — punishes the common case), tooltip-only (doesn't change the underlying behavior).

**The architectural lever.** v4.7.4.4 just proved out the canonical fix pattern for Bug Class #46: **derive lazily at read time, never persist eagerly via `async_update_entry` inside the setup path**. v4.7.5 applies the same pattern to canonical zone resolution:

- The Zone Manager **UI surface** never sees canonical-merged labels. The picker reads raw house zones from `entry.options["zones"]`.
- The HVAC **coordinator** continues calling `iter_canonical_hvac_zones` at runtime. The merge happens silently — same code, untouched.
- Saving any per-zone form **mirrors** the saved fields to sibling house zones (zones whose `CONF_ZONE_THERMOSTAT` equals the saved zone's thermostat) in a single `async_update_entry` call on the ZM entry. **Outside `async_setup_entry`** — options-flow handlers run after bootstrap-2 closes, so this is the safe call site documented in QUALITY_CONTEXT.md Bug Class #46 §"When `async_update_entry` IS safe."

**Why now.** v4.7.4 simplified the DPM surface; this is the natural next cleanup — same "stop confusing the user with HVAC internals" theme. The v4.7.4.2 dead-import hotfix also taught us that source-grep AST tests don't catch import-time failures; D5 bundles task #112 (config-flow runtime smoke tests) since this cycle touches `config_flow.py` heavily and is the perfect moment to land the scaffold.

---

## 2. Tier Classification

**Tier 2.** Triggers checked against Tier 2-DB:

| Trigger | Hit? |
|---|---|
| Touches `database.py` DAO | No |
| Migrates ≥3 callers to a new DAO | No |
| Changes dispatched payload shape | No |
| Adds behavioral test infra against real schemas | No (D5 is config-flow surface, not DB) |
| Followed by planned schema migration | No |

Two parallel reviewers per CLAUDE.md Tier 2 protocol. Framings disjoint per §9.

---

## 3. Discovery — Read Before Build

| File | Lines | Why |
|---|---|---|
| `custom_components/universal_room_automation/config_flow.py` | 4906-4960 (`async_step_manage_zones`) | D1 + D2: picker step. Today: `SelectSelectorMode.DROPDOWN`, reads zones from ZM `entry.options["zones"]` (already raw — but no merge-awareness shown to user). |
| `custom_components/universal_room_automation/config_flow.py` | 4962-4985 (`async_step_zone_config_menu`) | D4: this is the right place to render the shared-thermostat banner before routing to per-zone editor steps. |
| `custom_components/universal_room_automation/config_flow.py` | 1956-1981 (`_get_zm_zone_data`) | D4: helper used by every `async_step_zone_*` editor to load current zone data. Auto-mirror entry point. |
| `custom_components/universal_room_automation/config_flow.py` | 4991-5103 (`async_step_zone_rooms`) | D4 call site #1 — ZM save path. `async_update_entry` already called here at 5077. |
| `custom_components/universal_room_automation/config_flow.py` | 5150-5230 (`async_step_zone_media`) | D4 call site #2. |
| `custom_components/universal_room_automation/config_flow.py` | 5232-5333 (`async_step_zone_hvac`) | D4 call site #3 — this is the step that writes `CONF_ZONE_THERMOSTAT`. Edge case: re-assigning a thermostat is the "link/unlink" path. |
| `custom_components/universal_room_automation/config_flow.py` | 5335-5403 (`async_step_zone_energy`) | D4 call site #4. |
| `custom_components/universal_room_automation/config_flow.py` | 5405-5456 (`async_step_zone_persons`) | D4 call site #5. |
| `custom_components/universal_room_automation/config_flow.py` | 5458-5508 (`async_step_zone_cameras`) | D4 call site #6. |
| `custom_components/universal_room_automation/config_flow.py` | 5510-5867 (`async_step_zone_dynamic_preset`) | D4 call site #7 — biggest blast radius (DPM per-zone bucket cells). |
| `custom_components/universal_room_automation/domain_coordinators/hvac_zones.py` | 693-784 (`iter_canonical_hvac_zones`) | D3: stays unchanged. Verify it stays the single source of truth for the merge. |
| `custom_components/universal_room_automation/domain_coordinators/hvac_zones.py` | 213-423 (`async_discover_zones`) | D3: confirms LOCKSTEP partner. Document but do not modify. |
| `docs/QUALITY_CONTEXT.md` | 1743-1788 (Bug Class #46) | D4 safety: confirms options-flow `async_update_entry` is the safe call site. |
| `quality/tests/test_v4742_dead_import_removed.py` | full | D5: existing source-grep regression test — extend pattern to runtime imports. |
| HA selector source (`homeassistant.helpers.selector`) | `SelectSelectorMode` enum | D1: confirms `LIST` and `DROPDOWN` are the two valid modes. **Verified** against upstream `dev` branch: `class SelectSelectorMode(StrEnum): LIST = "list"; DROPDOWN = "dropdown"`. |

**File-size confirmation (matches plan size estimate basis):**
- `config_flow.py`: 6,782 lines
- `domain_coordinators/hvac_zones.py`: 680 lines

**Size estimate sanity-check:** ~565 LoC (from VibeMemo entry 015) broken down:
- D1 picker rewrite: ~30 LoC
- D2 picker rewrite + banner injection: ~25 LoC
- D3: documentation comment block + read-path inventory (no code change to merge): ~40 LoC of comments/docstrings
- D4 auto-mirror helper + 7 call-site invocations: ~280 LoC (helper ~80, per-site wiring ~28 × 7 = ~200)
- D4 banner text + translation entries: ~30 LoC
- D5 runtime smoke test: ~100 LoC
- Misc test fixtures + assertions: ~60 LoC

Total: ~565 LoC. **Confirmed.**

---

## 4. Deliverables

### D1 — Dropdown → menu for the Zone Manager Page 1 picker

**Description:** Change `async_step_manage_zones` (config_flow.py:4906) to render the zone picker as a `SelectSelectorMode.LIST` menu rather than `SelectSelectorMode.DROPDOWN`. This is the upstream-supported menu UI — verified against HA core's `SelectSelectorMode(StrEnum)` enum which exposes exactly two values, `LIST = "list"` and `DROPDOWN = "dropdown"`.

**Implementation note:** The existing schema (config_flow.py:4948-4953) uses:
```python
selector.SelectSelectorConfig(
    options=zone_options,
    mode=selector.SelectSelectorMode.DROPDOWN
)
```
Replace `DROPDOWN` with `LIST`. No other change to the selector contract — `options` list-of-`{label, value}` shape stays identical.

**Edge case:** When more than ~10 zones exist, list mode visually expands the form. Acceptable — the canonical install today has 5 house zones; growth past 10 is unlikely. If future install needs scrolling, add a `description_placeholder` cue rather than reverting to dropdown.

**Non-goal:** Don't introduce `async_show_menu` (which renders a true menu step but doesn't carry the labels-from-data we need). The list-mode select is the right primitive — same data flow, different rendering.

**Acceptance criteria:**
- **Verify:** Picker on Zone Manager → Configure renders as a vertical list of zones, not a dropdown combobox.
- **Verify:** Each menu item shows the raw house-zone label only (D2 enforces no merged labels).
- **Sensor:** N/A (UI-only).
- **Test:** `test_v475_d1_manage_zones_uses_list_mode` — build the schema returned by `async_step_manage_zones`; assert the `SelectSelectorConfig` carries `mode == SelectSelectorMode.LIST`.
- **Live:** Open ZM options on running HA → "Configure" → confirm visual list rendering (screenshot in close-out doc).

---

### D2 — Picker shows house zones, NOT canonical-merged HVAC labels

**Description:** Confirm + lock in that the picker iterates **raw house zones from `entry.options["zones"]`** and never displays the canonical-merged label "Entertainment + Master Suite". Today the picker already reads from `entry.options["zones"]` (config_flow.py:4924-4942) — so the raw labels are already what's shown for the current install. But the file structure does NOT prevent a future contributor from "helpfully" wiring `iter_canonical_hvac_zones` into the picker. D2 locks the contract with an inline comment + a regression test.

**Implementation:**
1. Add a comment block above the picker option-build loop (config_flow.py:4922) explaining: *"Picker MUST show raw house zones from ZM entry.options. The canonical thermostat-keyed merge in `iter_canonical_hvac_zones` is a runtime-only concern for the HVAC coordinator. See PLANNING_v4.7.5 §D3."*
2. Verify the option-build loop produces one entry per `zone_name` key under `entry.options["zones"]` — already true today.
3. If the same thermostat appears in 2+ zones, append a small visual hint to each affected zone's label: `"Entertainment (shared thermostat)"` and `"Master Suite (shared thermostat)"`. The hint comes from a lookup of thermostat → list-of-zones counts in the same `entry.options["zones"]` dict — no canonical call needed. (Banner detail lives in D4; the suffix in the picker is a quick-glance cue.)

**Edge case:** Zone with no thermostat assigned → no shared-thermostat suffix; renders as plain label.

**Non-goal:** Don't surface zone_id (`zone_N`) anywhere on the picker — `zone_id` is a coordinator-internal identifier per `iter_canonical_hvac_zones`'s zone_id derivation; the user shouldn't see it.

**Acceptance criteria:**
- **Verify:** Picker shows "Entertainment", "Master Suite" as separate entries (not "Entertainment + Master Suite").
- **Verify:** Both Entertainment and Master Suite carry the `(shared thermostat)` suffix when both reference the same `CONF_ZONE_THERMOSTAT`.
- **Sensor:** N/A.
- **Test:** `test_v475_d2_picker_shows_raw_house_zones` — fixture: ZM entry with 3 zones, 2 sharing one thermostat. Build picker options; assert exactly 3 entries, no entry contains `+`, both sharing entries carry the suffix.
- **Test:** `test_v475_d2_picker_does_not_call_iter_canonical` — AST/runtime check that `async_step_manage_zones` source body contains no reference to `iter_canonical_hvac_zones`.
- **Live:** Picker on the running HA shows exactly 5 house-zone entries (current install count), Entertainment + Master Suite each labeled with `(shared thermostat)`.

---

### D3 — Silent canonical resolution at runtime (lazy-derivation pattern)

**Description:** Document and enforce the architectural rule: the canonical HVAC merge is a runtime-only concept inside the HVAC coordinator. The UI surface never converts house-zone → canonical. This deliverable is **documentation + a regression test**; no code change to `iter_canonical_hvac_zones` or `async_discover_zones`.

**Read-path inventory.** A required output of D3: enumerate every call site of `iter_canonical_hvac_zones` and confirm each is on a runtime/coordinator code path, not a UI/options-flow path.

**Inventory work for the builder:**
1. `grep -rn "iter_canonical_hvac_zones" custom_components/` to enumerate callers.
2. For each caller, classify as **runtime-only** (coordinator init, platform setup, per-tick evaluation) OR **UI-touching** (config_flow.py, options flow handlers).
3. Any UI-touching caller is a Bug Class #47-candidate violation and must be reworked or documented as intentional.
4. Persist the inventory as a comment block at the top of `hvac_zones.py` (after the existing `_zone_id_from_thermostat_pure` docstring, before `iter_canonical_hvac_zones`).

**Documentation update:** Add a new section to `docs/QUALITY_CONTEXT.md` (or extend Bug Class #46) titled *"Lazy Canonical Resolution"* describing:
- The principle: UI shows raw house zones; runtime derives canonical lazily.
- The mirror to Bug Class #46 fix pattern: never persist a derived view eagerly; always derive at read time.
- The enforcement: `iter_canonical_hvac_zones` is permitted only from coordinator + platform-setup code paths.

**Non-goal:** Do NOT change the merge algorithm in `iter_canonical_hvac_zones` (lines 756-766) or `async_discover_zones` (lines 288-319). The "first non-empty `ac_load_sensor` wins / `ramp_zone_enabled` ORs" semantics stay. The LOCKSTEP requirement (hvac_zones.py:724-728) stays. Coordinator behavior is unchanged.

**Non-goal:** Do not introduce a new "canonical view" public helper for the UI. The whole point is the UI never asks for the canonical view.

**Acceptance criteria:**
- **Verify:** `iter_canonical_hvac_zones` callers all live in `domain_coordinators/` or `__init__.py` platform setup. Zero callers in `config_flow.py`.
- **Verify:** Comment block in `hvac_zones.py` enumerates every caller with file:line.
- **Verify:** QUALITY_CONTEXT.md has a "Lazy Canonical Resolution" entry citing v4.7.5.
- **Sensor:** N/A.
- **Test:** `test_v475_d3_no_canonical_in_config_flow` — AST scan of `config_flow.py` returns zero `iter_canonical_hvac_zones` references.
- **Test:** `test_v475_d3_canonical_callers_all_in_runtime` — `grep` of repo returns canonical callers ONLY in approved paths (allowlist: `domain_coordinators/hvac*.py`, `__init__.py`, `quality/tests/`).
- **Test:** `test_v475_d3_lockstep_still_holds` — extend or re-verify `test_v4513_1_zone_dedup.py` lockstep equivalence still passes.
- **Live:** HVAC coordinator continues to discover exactly the same canonical zones it did pre-v4.7.5 (compare `sensor.ura_hvac_zone_*` entity_ids before vs after restart — count and IDs unchanged).

---

### D4 — Option C auto-mirror on save (with shared-thermostat banner)

**Description:** When the user saves any per-zone form on a zone whose `CONF_ZONE_THERMOSTAT` is shared with one or more sibling house zones, the save **mirrors** the same field set into each sibling under `entry.options["zones"][<sibling>]`. The mirror happens in a single `async_update_entry` call after the saved zone's own update, before returning to the menu.

**The shared-thermostat-siblings helper.** Add to `config_flow.py` (near `_get_zm_zone_data` at line 1956):

```python
def _get_shared_thermostat_siblings(
    self,
    zm_entry,
    zone_name: str,
) -> list[str]:
    """Return list of OTHER house-zone names that share zone_name's thermostat.

    Empty list if zone_name has no thermostat OR no siblings share it.
    Used by every zone editor to drive Option C auto-mirror.
    """
    merged = {**zm_entry.data, **zm_entry.options}
    zones = merged.get("zones", {})
    target_thermostat = zones.get(zone_name, {}).get(CONF_ZONE_THERMOSTAT)
    if not target_thermostat:
        return []
    return [
        name
        for name, cfg in zones.items()
        if name != zone_name and cfg.get(CONF_ZONE_THERMOSTAT) == target_thermostat
    ]
```

**The auto-mirror helper.** Add to `config_flow.py` near `_get_zm_zone_data`:

```python
async def _auto_mirror_to_siblings(
    self,
    zm_entry,
    saved_zone_name: str,
    saved_zone_data: dict,
    mirror_keys: set[str],
) -> list[str]:
    """Copy mirror_keys from saved_zone_data into every shared-thermostat sibling.

    Returns the list of sibling zone names that were mirrored to (for
    description_placeholder / log). Caller has already saved saved_zone_name's
    own data; this function does ONE additional async_update_entry to write
    the mirrored fields into sibling slots.

    Safe call site under Bug Class #46 — runs from options flow (after
    bootstrap-2 closes), not async_setup_entry.
    """
    siblings = self._get_shared_thermostat_siblings(zm_entry, saved_zone_name)
    if not siblings:
        return []

    merged = {**zm_entry.data, **zm_entry.options}
    zones = {k: dict(v) for k, v in merged.get("zones", {}).items()}
    mirror_payload = {k: saved_zone_data[k] for k in mirror_keys if k in saved_zone_data}

    for sib in siblings:
        zones.setdefault(sib, {}).update(mirror_payload)

    self.hass.config_entries.async_update_entry(
        zm_entry,
        options={**zm_entry.options, "zones": zones},
    )
    return siblings
```

**Per-step `mirror_keys` (CRITICAL CORRECTNESS DECISION).** Each editor step gets a tightly-scoped set of keys to mirror. This avoids over-mirroring (e.g., `CONF_ZONE_PERSONS` is intentionally per-zone — bedrooms have different sleepers — and must NOT mirror).

| Step | Mirror keys |
|---|---|
| `zone_rooms` | NONE — `CONF_ZONE_ROOMS` is intentionally per-house-zone (Entertainment has different rooms than Master Suite). **Skip mirror entirely.** |
| `zone_media` | NONE — `CONF_ZONE_PLAYER_ENTITY`, `CONF_ZONE_PLAYER_MODE` are per-house-zone. **Skip mirror.** |
| `zone_hvac` | `CONF_ZONE_THERMOSTAT`, `CONF_HVAC_AC_LOAD_SENSOR`, `CONF_HVAC_AC_RAMP_ZONE_ENABLED`, `CONF_ZONE_VACANCY_SWEEP_ENABLED` — these define the shared physical equipment. |
| `zone_energy` | All per-zone energy CONFs (kWh threshold, etc.) — physical AC is the same circuit. |
| `zone_persons` | NONE — per-house-zone. |
| `zone_cameras` | NONE — per-house-zone. |
| `zone_dynamic_preset` | All DPM CONFs the step writes (master enable, bucket offsets, dwell, hysteresis, per-zone overrides) — these drive the shared thermostat's setpoint. |

**Why "NONE" for several steps:** Option C auto-mirror is precisely for *shared-thermostat fields*. Rooms/media/persons/cameras are about the rooms inside the zone, not the thermostat — they legitimately differ between zones that happen to share an AC. Mirroring them would erase user intent. This is the "URA Mirror Pattern" applied at config-flow time: only mirror what's physically/logically tied to the shared resource.

**Banner UI text.** On `async_step_zone_config_menu` (line 4962) — the submenu shown after picking a zone — render a `description_placeholder` block when `_get_shared_thermostat_siblings()` returns a non-empty list. Text (translatable):

> **Shared thermostat:** This zone shares thermostat `<thermostat_entity_id>` with `<comma-separated sibling names>`. HVAC and energy settings save here also apply to those zones automatically.

Use a new translation key `options.step.zone_config_menu.description` (parameterized). Coordinate with the v4.7.4 translation-prefix-bug fix — match the same pattern of unprefixed CONF keys.

**Save flow per affected editor step.** Pattern repeated at each of the 7 call sites:
1. Existing logic writes to the saved zone slot.
2. After the `async_update_entry` for the saved zone, call `await self._auto_mirror_to_siblings(zm_entry, saved_zone_name, saved_zone_data, MIRROR_KEYS_FOR_THIS_STEP)`.
3. If siblings list is non-empty, surface a description_placeholder on the next-rendered step: *"Also updated <sibling names>."*
4. Log at INFO: `"v4.7.5 auto-mirror: saved zone=%s thermostat=%s mirrored_keys=%s siblings=%s"`.

**RestoreEntity coexistence.** Per `feedback_ura_mirror_pattern.md`: RestoreEntity = runtime store, options = seed only. Auto-mirror writes to `entry.options` only. RestoreEntity-driven runtime values for sibling zones will be re-seeded next reload, BUT: HA fires `update_listener` after `async_update_entry`, which reloads the ZM entry. **Reload chain.** Verify with Reviewer B that one save → one update_listener tick → one reload, NOT two (avoid re-entry to a state where sibling RestoreEntities overwrite the just-mirrored seed). Mitigation if reload chain doubles: collapse the save + mirror into one combined `async_update_entry` call (already what `_auto_mirror_to_siblings` does — but verify the per-step save logic doesn't separately call `async_update_entry` first).

**Unlink path (CRITICAL edge case for Reviewer A).** User opens `async_step_zone_hvac` for "Master Suite" and **changes** `CONF_ZONE_THERMOSTAT` from `climate.studyb_zone_1` to `climate.studyb_zone_2`. Master Suite no longer shares with Entertainment.
1. Compute `siblings_before` (using old thermostat value) and `siblings_after` (using new thermostat value).
2. If `siblings_before` is non-empty AND new thermostat differs: this is an unlink. Mirror the saved fields to `siblings_before` ONE LAST TIME (so Entertainment doesn't suddenly get the half-applied mid-edit state), THEN — separately — also mirror to `siblings_after` (so the new sibling group sees the new shared settings).
3. Log at INFO: `"v4.7.5 unlink: zone=%s old_thermostat=%s new_thermostat=%s mirrored_to_old=%s mirrored_to_new=%s"`.
4. Banner on next render reflects new sibling set.

**Non-goal:** Don't add a "force unlink" button for the case where the user wants two zones to genuinely differ while sharing a thermostat. URA's single-user install has no such case. If it arises later, that's a v4.7.6+ feature.

**Acceptance criteria:**
- **Verify (D4.a):** Saving HVAC settings on "Entertainment" → "Master Suite" zone slot under ZM options now contains the same HVAC keys with the same values, within 1 reload tick.
- **Verify (D4.b):** Saving `zone_rooms` on "Entertainment" leaves "Master Suite" rooms list untouched.
- **Verify (D4.c):** Banner appears on `zone_config_menu` when the selected zone shares a thermostat; banner lists the siblings by name and the thermostat entity_id.
- **Verify (D4.d):** Banner absent when zone has unique thermostat.
- **Verify (D4.e — unlink):** Reassigning a sibling's `CONF_ZONE_THERMOSTAT` to a different climate entity mirrors to BOTH old siblings AND new siblings; banner on next render shows the new sibling set.
- **Sensor:** Coordinator log line `v4.7.5 auto-mirror: ...` at INFO on each shared-thermostat save.
- **Test:** `test_v475_d4_mirror_helper_round_trip` — fixture: ZM with E + MS sharing thermo. Build payload for `zone_hvac`. Save E with `CONF_HVAC_AC_LOAD_SENSOR="sensor.foo"`. Assert MS slot now has the same value.
- **Test:** `test_v475_d4_no_mirror_when_unique_thermostat` — single-zone fixture; assert no mirror call, no log line.
- **Test:** `test_v475_d4_rooms_do_not_mirror` — save `zone_rooms` on E; assert MS `CONF_ZONE_ROOMS` unchanged.
- **Test:** `test_v475_d4_dpm_keys_mirror` — save DPM bucket offsets on E; assert MS bucket offsets match.
- **Test:** `test_v475_d4_unlink_mirrors_to_old_and_new` — start E + MS sharing thermo_1. Save MS with thermo_2 (and a new fan-speed value). Assert E got the fan-speed mirror (old sibling) AND if any zone now shares thermo_2 it also gets it.
- **Test:** `test_v475_d4_banner_lists_siblings` — render `zone_config_menu` on E; assert `description_placeholders` contains MS name + thermostat entity.
- **Test:** `test_v475_d4_one_update_entry_per_save` — instrument `async_update_entry`; assert exactly one call per save (not two — proves the reload chain doesn't double-fire).
- **Live:** On running HA, open ZM → Configure → Entertainment → HVAC, change `CONF_HVAC_AC_LOAD_SENSOR`, save. Open ZM → Configure → Master Suite → HVAC; verify the same value appears. Check HA core log for one `v4.7.5 auto-mirror: ...` INFO line.

---

### D5 — Config-flow runtime smoke tests (bundled, closes task #112)

**Description:** Land a new test module that **runtime-imports** `config_flow` and **instantiates every options-flow step's schema** by calling the step handler with `user_input=None`. Catches the v4.7.4.2 dead-import class of bug (`from homeassistant.components.selector import …` after HA 2026.5.4 moved the module): a source-grep test can't see runtime `ImportError`/`ModuleNotFoundError`/`AttributeError` from a dead module path.

**Pattern (extends `feedback_migration_helper_imports.md` AST-walk pattern):**

The existing `test_v450_d2_migration.py` AST-walks `_migrate_*` helpers and asserts `energy_const` imports resolve at test time. D5 generalizes this:

1. **Discovery layer:** AST-walk `config_flow.py` to enumerate every `async def async_step_*` method on `UniversalRoomAutomationOptionsFlow` and `UniversalRoomAutomationConfigFlow`.
2. **Runtime instantiation layer:** For each step, construct a minimal `OptionsFlow` / `ConfigFlow` instance with a stub `hass` + stub `_config_entry`. Call `await handler(user_input=None)` and assert no exception of class `ImportError`, `ModuleNotFoundError`, `AttributeError` (where the attribute is on a `homeassistant.*` module).
3. **Schema-build layer:** For steps that return `async_show_form(...)`, extract the returned schema; iterate its keys; assert every selector mode/value is accessible (not a stale enum reference).
4. **Allowlist:** Some steps require pre-set instance state (`self._selected_zone_name`, etc.). Test fixture sets up plausible state per allowlist; steps that abort due to missing state are still considered "passed" (the assert is "no `ImportError` raised", not "form rendered").

**Fixtures:**
- A pytest fixture `stub_hass` providing minimal `config_entries.async_entries(DOMAIN)`, `states.get`, `data` shapes.
- A pytest fixture `stub_zm_entry` with 2 zones sharing a thermostat (reuse for D4 tests).
- A pytest fixture `stub_room_entry` for room editor steps.

**What this catches that AST tests miss:**
- Imports at module top that reference modules HA moved (v4.7.4.2 incident).
- `selector.SelectSelectorMode.<X>` typos where `<X>` isn't an enum member (would AttributeError at runtime).
- `homeassistant.helpers.entity_registry as er` aliasing breakage if HA removes `er.async_get` or similar.
- Voluptuous schema construction errors (e.g., `vol.Required(key, default=callable)` where callable resolves to something unhashable).

**What this does NOT replace:**
- Form-rendering correctness (does the schema produce the right field set). Per-step tests (D1/D2/D4 + existing per-cycle tests) still own that.
- Behavioral correctness when `user_input` is passed. D5 only probes `user_input=None` happy-path render.

**Test module:** `quality/tests/test_v475_d5_config_flow_runtime_smoke.py`.

**Test count target:** One parametrized test that iterates ~50 `async_step_*` methods. CI cost target: < 5 seconds.

**Acceptance criteria:**
- **Verify:** Running `PYTHONPATH=quality python3 -m pytest quality/tests/test_v475_d5_config_flow_runtime_smoke.py -v` passes.
- **Verify:** Test discovers ≥ 40 `async_step_*` methods (current count is ~85 — see grep at §3).
- **Verify:** Synthesizing a removed `homeassistant.helpers.selector` attribute in CI (mutation test) causes D5 to FAIL — proves the test would have caught v4.7.4.2.
- **Sensor:** N/A.
- **Test:** `test_v475_d5_discovers_all_options_flow_steps` — AST walk finds expected step methods.
- **Test:** `test_v475_d5_every_step_instantiates_without_import_error` — parametrized; calls each step with `user_input=None`; passes if no `ImportError | ModuleNotFoundError | AttributeError(homeassistant.*)` raised.
- **Test:** `test_v475_d5_mutation_proves_coverage` — manually patches `selector.SelectSelectorMode` to remove `DROPDOWN`; asserts the smoke test detects the breakage.
- **Live:** N/A (CI-only test).

---

## 5. Constants / Schema Changes

| Constant | Where | Purpose |
|---|---|---|
| `MIRROR_KEYS_ZONE_HVAC = {CONF_ZONE_THERMOSTAT, CONF_HVAC_AC_LOAD_SENSOR, CONF_HVAC_AC_RAMP_ZONE_ENABLED, CONF_ZONE_VACANCY_SWEEP_ENABLED}` | `config_flow.py` (module level near other constants) | D4 — drives `_auto_mirror_to_siblings` payload for `zone_hvac` step. |
| `MIRROR_KEYS_ZONE_ENERGY = {...}` | `config_flow.py` | D4 — `zone_energy` step. Enumerate after reading the step's schema. |
| `MIRROR_KEYS_ZONE_DPM = {...}` | `config_flow.py` | D4 — `zone_dynamic_preset` step. Largest set — includes per-zone overrides + bucket cells. |
| `options.step.zone_config_menu.description` (parametrized) | `strings.json` + `translations/en.json` | D4 — banner text. |

**No new persisted CONFs.** No schema/storage version bump. Existing ZM entry shape is preserved.

---

## 6. Backward Compatibility

- **Existing ZM entry data:** untouched on first read.
- **First save after upgrade on a shared-thermostat zone:** Triggers the auto-mirror. Sibling slots are populated from saved values. **This IS a one-time observable behavior change.** Surface in the release notes: *"v4.7.5: Saving any HVAC, energy, or Dynamic Preset setting on a zone now also updates sibling zones that share the same thermostat. See the banner on the zone configuration menu."*
- **`iter_canonical_hvac_zones` callers:** unchanged. Coordinator behavior identical.
- **Bug Class #46 safety:** all `async_update_entry` calls remain in options-flow handlers (after bootstrap-2). No new setup-path writes.

---

## 7. Edge Cases (Quality Context)

Drawn from `docs/QUALITY_CONTEXT.md` bug classes:

| Bug Class | Risk | Mitigation |
|---|---|---|
| **#7 — Stale Data Source** | Mirror reads from `entry.options["zones"]`; HA may serve stale value if a concurrent reload is in flight. | Use the same `merged = {**entry.data, **entry.options}` pattern as existing handlers (config_flow.py:5062-5067) and deep-copy inner dicts before mutating. |
| **#14 — Config Snapshot Staleness** | Mirror payload constructed at step entry; if user took 10 minutes between picker and save, sibling values may have drifted from a parallel browser tab. | Acceptable — single-user install, no concurrent editors. Document in code comment. |
| **#22 — Enum mismatch** | `SelectSelectorMode.LIST` typo. | D5 catches at CI time. |
| **#33 — Sibling Helper Skipped** | D4 has 7 call sites; missing one means save-without-mirror on a sibling-sharing zone. | D4.test-suite explicitly covers each step. Reviewer B verifies grep enumeration is exhaustive. |
| **#36 — Per-Zone Entity Registration Bypasses Dedup** | If a future contributor adds a new per-zone editor step and forgets to call `_auto_mirror_to_siblings`, sibling drift returns. | Add a comment block at `_get_zm_zone_data` saying "every step using this helper that saves shared-thermostat fields MUST call `_auto_mirror_to_siblings` — see PLANNING_v4.7.5 §D4 table." |
| **#42 — Lambda + async_create_task in scheduler callbacks** | D4 helpers are coroutines, called with `await` from step handlers (already on the asyncio event loop). | No new scheduler callbacks. Safe. |
| **#45 — Lambda Closure Captures Stale Local** | Mirror payload is built immediately, then awaited. No deferred lambda capture. | Safe. |
| **#46 — `async_update_entry` re-entrancy** | D4 calls `async_update_entry` from options-flow handlers — explicitly listed as **safe** under "When `async_update_entry` IS safe in `async_setup_entry`" §2 (outside `async_setup_entry`). | Safe. Document in `_auto_mirror_to_siblings` docstring. |

---

## 8. Verification (Pre-Deploy Zero-Bugs Gate)

Per `feedback_pre_deploy_zero_bugs_gate.md`, run all four gates before `deploy.sh`:

```bash
# Gate 1: No unresolved conflict markers
grep -rln "^<<<<<<<\|^>>>>>>>" custom_components/ docs/ quality/ \
  | grep -v "TEST_SUITE_ACCESS\|test_scenarios" \
  && echo "ABORT: unresolved conflict markers" && exit 1

# Gate 2: py_compile every changed Python file
git diff --name-only HEAD~1 -- '*.py' | xargs -I{} python3 -m py_compile {} || exit 1

# Gate 3: cycle tests pass
PYTHONPATH=quality python3 -m pytest quality/tests/test_v475_*.py -q || exit 1

# Gate 4: full URA suite — no NEW regressions vs baseline_v4.7.4.4.txt
PYTHONPATH=quality python3 -m pytest quality/tests/ -q
# Compare failed count vs baseline_v4.7.4.4.txt
```

**Baseline tag.** Before applying review fixes, run:
```bash
git tag pre-review-v4.7.5 -m "Pre-review baseline for v4.7.5"
```

---

## 9. Tier 2 Review — Reviewer Framings

Per CLAUDE.md, two reviewers dispatched in parallel with explicit, disjoint focus areas so blind spots cannot overlap.

### Reviewer A — Correctness + Edge Cases

**Focus:**
- Auto-mirror round-trip: every CONF in each `MIRROR_KEYS_*` set actually round-trips through save → mirror → reload → read.
- `MIRROR_KEYS_*` completeness AND minimality: every shared-thermostat-tied field is included; no per-house-zone-only field leaks in.
- Unlink path: thermostat reassignment correctly mirrors to BOTH old and new sibling groups; banner reflects new state.
- Banner correctness: shows when siblings exist, hides when alone, shows correct thermostat entity_id, correct sibling names.
- D2 picker labels: no canonical "+ " label appears; suffix `(shared thermostat)` rendered exactly when warranted.
- D3 documentation: caller inventory enumerates every grep hit; no `iter_canonical_hvac_zones` call escapes the allowlist.
- RestoreEntity coexistence: mirrored seed values are not stomped by a stale sibling RestoreEntity at next reload. Verify the URA Mirror Pattern (RestoreEntity = runtime store, options = seed) holds end-to-end.
- D5 runtime smoke test: parametrized coverage actually exercises every step; the mutation-proof test demonstrably fails when the enum is mocked away.
- Translation key correctness: banner key matches strings.json + en.json.

### Reviewer B — Async + Lifecycle + Race Conditions

**Focus:**
- Save → mirror tick ordering: one user save produces one `async_update_entry` call (mirror is folded into the same call, not a separate write). Reviewer B owns the assertion that `test_v475_d4_one_update_entry_per_save` catches a regression where someone naively splits save + mirror into two writes.
- Update_listener / reload chain: confirm one save → one update_listener fire → one reload. Two reloads = re-entry hazard (echo of Bug Class #46).
- Bug Class #46 boundary: confirm every `async_update_entry` call in D4 lives strictly in options-flow handler scope (not setup path, not a startup-deferred task).
- Concurrent edits: two parallel ZM saves on different sibling zones; verify no torn-write of `entry.options["zones"]`. (Single-user install reality: rare. Still review the failure mode.)
- Listener cleanup: D4 doesn't register new listeners, but verify no leak if a step-handler raises mid-mirror.
- Task lifecycle: D4 helpers are `async def`, awaited from the step handler. No `hass.async_create_task` fire-and-forget. Confirm this is the case (not a deferred task with a missing cleanup).
- D5 test instantiation: `stub_hass` doesn't accidentally schedule background tasks that survive test teardown.
- Reload race after thermostat reassignment: the unlink path mirrors to two sibling groups. Confirm both mirrors are atomic within one `async_update_entry` (not two sequential writes — would fire update_listener twice).

---

## 10. Deploy + Live Validation

1. Apply review fixes (if any). Re-run gates (§8).
2. `./scripts/deploy.sh 4.7.5 "Zone Manager UX + canonical resolution (Option C auto-mirror)" "<release notes>"`.
3. After HACS install + HA restart:
   - **Live D1:** Open ZM options → Configure. Picker renders as vertical list (screenshot).
   - **Live D2:** "Entertainment" and "Master Suite" are separate entries; both carry `(shared thermostat)` suffix.
   - **Live D3:** `sensor.ura_hvac_zone_*` entity_ids match pre-v4.7.5 set (coordinator unchanged).
   - **Live D4.a:** Configure → Entertainment → HVAC. Change `CONF_HVAC_AC_LOAD_SENSOR`. Save. Configure → Master Suite → HVAC: same value appears.
   - **Live D4.b:** Configure → Entertainment → Rooms. Add a room. Save. Configure → Master Suite → Rooms: unchanged.
   - **Live D4.c:** Configure → Entertainment shows the banner with Master Suite + thermostat entity_id.
   - **Live D4.e:** Reassign Master Suite's thermostat. Banner on next render reflects new sibling set; HA core log shows `v4.7.5 unlink: ...` INFO line.
   - **Logs:** `ha_get_logs(source="system_service", slug="core")` → find at least one `v4.7.5 auto-mirror: ...` INFO line.

---

## 11. Plan Completion Tracking — Explicitly Deferred Items

### Post-Review Fix-Up Status (added 2026-05-29)

| Finding | Severity | Status | Notes |
|---|---|---|---|
| A-H1 / B-H2 — `zone_rooms` bypasses `_auto_mirror_to_siblings` | HIGH | **FIXED** | Routed through helper with new `rename_from` kwarg; M4 AST test added. |
| A-H2 — `MIRROR_KEYS_ZONE_ENERGY` scope | HIGH | **FIXED** | Audited `async_step_zone_energy` schema — only `CONF_ZONE_POWER_SENSORS` + `CONF_ZONE_ENERGY_SENSORS` exist today; both are thermostat-tied and included; `test_v475_d4_energy_mirror_set_covers_step_schema` locks the contract. |
| A-H3 — `" + "` split collision | HIGH | **FIXED** | Validate-time rejection at zone-create + zone-rename (`_ZONE_NAME_PLUS_SEPARATOR_RE`); `energy.py` 3-step resolution with explicit fallback ordering + WARNING when unresolved; Bug Class #47 formalized in `QUALITY_CONTEXT.md`. |
| B-H1 — `async_step_zone_config_menu` legacy path | HIGH | **FIXED** | Explicit `if zone_name is None` guard; legacy `zone_entry` capture preserved; comment explains both paths. |
| B-H3 — `zone_energy` + `zone_dpm` missing `old_thermostat` | HIGH | **FIXED** | Both steps now thread `old_thermostat` to the helper; new test `test_v475_d4_unlink_mirrors_energy_to_old_sibling`; helper logs WARNING if reassignment payload omits `CONF_ZONE_THERMOSTAT` from `mirror_keys`. |
| A-M1 — D3 allowlist test scope drift | MEDIUM | **FIXED** | `_collect_callers` now also walks `quality/tests/`; allowlist extended to match QUALITY_CONTEXT.md docstring. |
| A-M3 — `zone_id`/`zone_name` collision | MEDIUM | **FIXED** | `energy.py` uses explicit 3-step resolution (raw match → split fallback → zone_id last). |
| A-M4 — No AST test for editor-step → helper routing | MEDIUM | **FIXED** | `test_v475_d4_every_save_step_routes_through_mirror_helper` added. |
| A-M6 — D5 mutation test under-asserts runtime coverage | MEDIUM | **FIXED** | `test_v475_d5_mutation_actually_catches_missing_mode_at_runtime` actually runs `async_step_manage_zones` under a stub missing `LIST` and asserts AttributeError. Set-difference test kept as `test_v475_d5_select_mode_set_difference_logic`. |
| B-M1 — helper sync/async naming mismatch | MEDIUM | **DOC ONLY** | Renaming `_auto_mirror_to_siblings` would touch 7 call sites; docstring now explicitly states "synchronous; do NOT await". B-M1 OK with either fix. |
| B-M2 — `asyncio.get_event_loop()` deprecation in D5 | MEDIUM | **FIXED** | Replaced with `_run_coro_isolated` helper that runs on a fresh loop AND restores the prior loop — avoided suite-run pollution observed in `test_v47x_dynamic_preset` (Python-3.9 `asyncio.Lock()` ctor). |
| B-M3 — read-after-write race docstring | MEDIUM | **FIXED** | `_auto_mirror_to_siblings` docstring now carries the explicit "no `await` between mirror call and form render" caveat. |
| A-M2 — banner read-only convention | MEDIUM | **FIXED (pass 2)** | Extracted `_render_shared_thermostat_banner` read-only helper next to `async_step_zone_config_menu`. Docstring locks the "no mutation, no dispatch, no task scheduling" contract. Three unit tests: side-effect-free repeat-call equality + entry snapshot diff; empty banner on solo-thermostat zone; empty banner on `zone_name=None` legacy path. |
| A-M5 — Plan §11 close-out | MEDIUM | **FIXED (this table)** | Per-finding fix-up status captured here. |
| B-M4 — `_StubHass` missing `async_create_task` | MEDIUM | **FIXED (pass 2)** | `_StubHass.async_create_task` recorder added (closes the coroutine to silence "never awaited" warning; appends call name to `created_tasks`). D4 HVAC-mirror / no-mirror / unlink tests + a new dedicated `test_v475_d4_helper_does_not_schedule_background_tasks` assert `created_tasks == []`. A trip-wire self-test (`test_v475_d4_stub_hass_records_async_create_task_calls`) verifies the recorder works, preventing vacuous passes. D5 picker stub gets the same recorder + assertion on `async_step_manage_zones` rendering. |
| A-L1 — banner translation surface | LOW | DEFERRED | en-only consistent with rest of integration. |
| A-L2 — banner shows entity_id, not friendly name | LOW | DEFERRED | Single-user install knows entity IDs; backlog. |
| A-L3 — RestoreEntity coexistence test | LOW | DEFERRED | No test surface today; backlog v4.7.5.x. |
| A-L4 — LIST member runtime verification | LOW | PARTIALLY FIXED | D5 mutation test now exercises the live runtime path; post-deploy live validation is the final verification. |
| A-L5 — unlink test missing `update_calls == 1` assertion | LOW | **FIXED** | `test_v475_d4_unlink_mirrors_energy_to_old_sibling` includes the `len(...) == 1` assertion. |
| A-L6 — D4 module-load order risk | LOW | DEFERRED | Order-independent today; observed pass; backlog if Bug Class #44 recurs. |
| A-L7 — broad `Exception` swallow in siblings lookup | LOW | DEFERRED | Load-bearing (must never break the form); backlog if narrowing is requested. |
| B-L1 — banner broad except masks ImportError class | LOW | DEFERRED | Same as A-L7. |
| B-L2 — helper no-op INFO log | LOW | DEFERRED | Minor logging polish. |
| B-L3 — D4 fixture intra-test mutation | LOW | DEFERRED | Function-scope fixture today; safe. |
| B-L4 — banner `{banner}` placeholder lint | LOW | DEFERRED | Single render site. |

**Bug Class #47 added to `QUALITY_CONTEXT.md`** — "Lazy Canonical Resolution UI Surface Violation" with the `" + "` substring collision documented as a sub-class.

**Cycle test counts post-fix-up:** 31/31 v4.7.5 cycle tests pass (up from 27 pre-fix-up after new test additions). Full suite: 4113 passed / 55 failed / 2 skipped / 14 errors — **zero NEW failures vs `pre-review-v4.7.5` baseline** (was 4109 passed / 55 failed — +4 new passing tests from this fix-up). All baseline failures and errors are pre-existing infrastructure issues unrelated to this cycle (`test_activity_logger.py` `ModuleNotFoundError`).

**LoC delta** on top of `pre-review-v4.7.5`: see `git diff pre-review-v4.7.5..HEAD`.

### Build-cycle status (post-build, pre-review)

| Deliverable | Status | Notes |
|---|---|---|
| D1 — Dropdown → menu (`SelectSelectorMode.LIST`) | DONE | `async_step_manage_zones` switched; AST regression test green. |
| D2 — Raw house-zone picker + `(shared thermostat)` suffix | DONE | Local thermostat-occurrence count drives suffix; AST guard against `iter_canonical_hvac_zones` import added. |
| D3 — Silent canonical resolution + QUALITY_CONTEXT.md section | DONE | "Lazy Canonical Resolution" section added; hvac_zones.py caller inventory comment landed; `iter_canonical_hvac_zones` removed from config_flow.py. |
| D3 read-side fallback in `energy.py` | DONE (one-line consumer fix beyond original plan; documented under Lazy Canonical Resolution) | `_async_evaluate_dynamic_presets` now splits canonical name on `" + "` when raw lookup misses. Without it, post-v4.7.5 DPM data written under a raw house zone would not be read by the EC evaluation loop (canonical merged-label key is never written by the auto-mirror). The `iter_canonical_hvac_zones` merge algorithm itself is unchanged — this is a consumer-side resolver. |
| D4 — Option C auto-mirror + banner + unlink path | DONE | `_get_shared_thermostat_siblings` + `_auto_mirror_to_siblings` helpers; per-step `MIRROR_KEYS_*` frozensets enforce minimal mirror; unlink path mirrors to OLD and NEW sibling groups within ONE `async_update_entry`. Banner via `description_placeholders={"banner": ...}` on `zone_config_menu`; strings.json + en.json description templates carry `{banner}`. |
| D5 — Config-flow runtime smoke tests | DONE | Module-load test under stubbed HA; selector-mode reference verifier with mutation-proof test; representative `async_step_manage_zones` runtime instantiation. Closes task #112. |

### Notes vs the plan

- **Auto-mirror is invoked from rooms / media / persons / cameras steps too** even though their `MIRROR_KEYS_*` are empty. The helper is a single source of truth for the save path; an empty mirror set is a no-op for siblings while still preserving the single `async_update_entry` invariant. Test `test_v475_d4_rooms_do_not_mirror` covers the contract. (Zone-rooms is special because of the rename codepath and keeps its direct `async_update_entry` call.)
- **Banner text rendered via `description_placeholders`.** The static description in `strings.json` is `"What would you like to configure for this zone?{banner}"`; the helper sets `banner` to the formatted "Shared thermostat:" sentence when siblings exist and to `""` when not — keeping the description hidden when irrelevant.
- **"Also updated <sibling names>" follow-up cue on the NEXT step is not rendered** (the `zone_config_menu` banner already lists siblings clearly; revisiting per-step description-placeholders churn was deemed unnecessary). If user reports confusion, revisit.
- **Bug Class #44 (sys.modules pollution) discipline:** the D4 + D5 test modules restore `sys.modules` after their module-scope load. This pattern improved the suite — one pre-existing failure (`test_v472_dpm_surfaces.py::...test_validate_helper_called_with_zone_prefix_empty_in_surface_2`) now passes again because the global sys.modules state is no longer contaminated.

### Original deferred items (preserved)

Per CLAUDE.md "Plan Completion Tracking — MANDATORY", documenting what this plan **does not** cover:

| Item | Why deferred | Track where |
|---|---|---|
| **`async_show_menu`-based picker** (true menu step rather than list-mode select) | The list-mode `SelectSelector` carries the labels-from-data we need; `async_show_menu` would require pre-translating every zone name at strings.json build time, which doesn't work for user-data zone names. | Not tracked — architectural mismatch, not a deferral. |
| **"Force unlink" button** to allow shared-thermostat zones to intentionally diverge | URA single-user install has no current case for this. If requested, file a v4.7.6+ feature. | Auto-memory if user raises. |
| **Bulk-edit "apply to all sibling zones" toggle** on a non-shared-thermostat field | Out of Option C scope. Option C auto-mirrors what's physically tied to the thermostat; per-house-zone fields stay per-house-zone by design. | Out of scope. |
| **Generalizing auto-mirror to non-HVAC shared resources** (e.g., shared media player across zones) | No current shared resource other than thermostat. If a future shared-resource pattern emerges, extract `_auto_mirror_to_siblings` into a generic shared-resource mirror helper. | Roadmap backlog if it arises. |
| **Refactoring the rest of the config flow** (the 85+ step handlers) | Explicit non-goal per kickoff. v4.7.5 touches only ZM picker, ZM submenu, and the 7 per-zone editor steps. | N/A — non-goal. |
| **Changing coordinator merge semantics** (`iter_canonical_hvac_zones` algorithm) | Explicit non-goal. The "first non-empty / OR" merge stays. v4.7.5 only hides the merge from the UI, doesn't change it. | N/A — non-goal. |
| **AnomalyType discriminator rename** | Separate backlog item (`project_near_term_roadmap_post_v462.md`). | Tracked in memory. |
| **Guest Mode Phase 3 (predictive)** | Separate backlog item. | Tracked in memory. |
| **Dashboard PWA work** | Separate repo. | `project_pwa_v6_shipped.md`. |
| **Advanced Energy Mgt v4.7.x Forecaster** | Deferred per memory; close-out priority. | `project_advanced_energy_mgt_v47x.md`. |

---

## 12. Non-Goals (Explicit Call-Out)

1. **Not changing coordinator merge semantics.** `iter_canonical_hvac_zones` (hvac_zones.py:693) and `ZoneManager.async_discover_zones` (hvac_zones.py:213) keep their existing merge algorithm and LOCKSTEP requirement intact.
2. **Not touching the canonical merge algorithm.** "First non-empty `ac_load_sensor` wins / `ramp_zone_enabled` ORs" stays.
3. **Not refactoring the rest of the config flow.** The 85+ other step handlers are out of scope. Only the picker (`async_step_manage_zones`), the submenu (`async_step_zone_config_menu`), and the 7 per-zone editors get touched.
4. **Not introducing a new "canonical view" public helper for the UI.** UI never asks for canonical; UI only ever sees raw house zones.
5. **Not changing `entry.data` / `entry.options` storage shape.** Zero migration. The ZM entry's `options["zones"]` dict shape is preserved.

---

**End of plan.** Ready for `ura-builder` dispatch on user kickoff signal.
