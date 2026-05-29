# URA v4.7.4.3 — Drop customize_buckets migration; lazy derivation at read time

**Release date:** 2026-05-28
**Tier:** Tier 1 hotfix (single adversarial review)
**Scope:** `__init__.py` migration block deletion, `config_flow.py` lazy derivation, Bug Class #46 update, 6 new tests

---

## Root Cause

v4.7.4 introduced a one-time migration in `async_setup_entry` (Zone Manager path) that set `CONF_ZONE_DYNAMIC_PRESET_CUSTOMIZE_BUCKETS=True` for any zone that had saved per-bucket cells but no explicit flag. The migration called `hass.config_entries.async_update_entry(entry, options=...)` from inside `async_setup_entry`.

HA's update_listener machinery fired the registered `_async_update_listener` callback, which called `hass.async_create_task(hass.config_entries.async_reload(entry_id))`. The reload scheduled a second execution of `async_setup_entry`. On cold install (first HA boot after HACS upgrade), both invocations ran within HA's 120s bootstrap-2 budget window. The second invocation hit slow paths (`anomaly_detector.load_baselines()`, TOU engine initialization) and the budget expired, surfacing as:

```
CancelledError: Global task timeout: Bootstrap stage 2 timeout
```

This is **Bug Class #46**: `async_update_entry` from within `async_setup_entry` triggers re-entrant reload.

---

## v4.7.4.1 — Incomplete Fix (we apologize for the misfire)

v4.7.4.1 attempted to fix the bug by deferring the `async_update_entry` call via `hass.async_create_task(_v474_defer_customize_buckets_persist(...))`. This did NOT fix the root cause.

The deferred task still called `async_update_entry` — just slightly later. The task was scheduled during `async_setup_entry` and executed within the same bootstrap-2 window. The update_listener still fired, the reload still ran, and `async_setup_entry` still executed twice within the budget window. Net result: same cold-boot timeout, same `CancelledError`, on every first boot post-v4.7.4.

v4.7.4.1 was immediately followed by v4.7.4.2 (which fixed an unrelated dead import). Neither addressed the double-setup root cause.

---

## v4.7.4.3 — True Fix: Drop the Migration Entirely

**The canonical fix for Bug Class #46:** Never call `async_update_entry` from anywhere in the setup path — including deferred tasks — because even deferred tasks fire within bootstrap-2 if scheduled during setup.

Instead, derive the `customize_buckets` flag **lazily at read time** in `_build_dynamic_preset_schema` (config_flow.py). The function is only called when the user opens the zone's Dynamic Preset form. No `async_update_entry` call. No reload. No second invocation of `async_setup_entry`. The value persists naturally the next time the user saves the form.

### Changes

**`custom_components/universal_room_automation/__init__.py`**
- Deleted migration block at lines 2322–2359 (the entire `try/except` around `CONF_ZONE_DYNAMIC_PRESET_CUSTOMIZE_BUCKETS` setup + `async_update_entry` call).
- Replaced with a comment explaining v4.7.4.3's approach.
- No helper function was present in this worktree (the v4.7.4.1 `_v474_defer_customize_buckets_persist` helper was only in the develop branch; it is explicitly deleted as part of the v4.7.4.3 merge).

**`custom_components/universal_room_automation/config_flow.py`**
- Added `_customize_buckets_value()` closure inside `_build_dynamic_preset_schema`.
- Replaces `_b(CONF_CUSTOMIZE_BUCKETS, False)` default with `_customize_buckets_value()`.
- Logic: if an explicit value is stored (current_data or source_data), use it. Otherwise, derive from whether any per-bucket home cell is saved — if yes, user was customizing pre-v4.7.4, default to True to preserve their customizations.

**`docs/QUALITY_CONTEXT.md`**
- Added Bug Class #46 with the incomplete-fix narrative as a warning for future hotfixes of this class.

**`quality/tests/test_v4743_no_eager_migration.py`** (new)
- 6 tests: 3 AST/source-grep + 3 runtime invocations of `_build_dynamic_preset_schema`.

**`quality/tests/test_v4741_migration_deferral.py`** (deleted)
- Was guarding the v4.7.4.1 deferred-task invariant, which is now the wrong invariant. Removed to avoid false signal.

---

## Boot Timeline Impact

- **Before v4.7.4.3 (all cold boots post-v4.7.4):** `async_setup_entry` ran twice within bootstrap-2. Second run hit 35s+ DB-ready wait. Total: 120s+ → `CancelledError`.
- **After v4.7.4.3 (all boots):** `async_setup_entry` runs exactly once. Migration block is gone. No `async_update_entry`. No deferred task. No reload from setup.

---

## Deferred Items

None. This is a complete fix with no known deferred items.

---

## Post-Review Fix-Up (2026-05-28)

Tier 1 adversarial review (commit 8f5d5d1) found 4 findings. All 4 addressed:

### CRITICAL-1 — v4.7.4.2 dead-import fix accidentally reverted
**File:** `config_flow.py` (around the `async_step_zone_dynamic_preset` function body)
**Fix:** Deleted `from homeassistant.components.selector import (selector, NumberSelector, ...)` block
that was reintroduced in the initial v4.7.4.3 build. Replaced with a tombstone comment documenting
why the import was removed in v4.7.4.2 and must not return.
**Regression test added:** `quality/tests/test_v4742_dead_import_removed.py` —
`test_v4742_v4743_no_broken_selector_import()` greps config_flow.py for the broken import path
and fails if it reappears.

### HIGH-1 — QUALITY_CONTEXT.md bug class count regressed 46 → 33
**File:** `docs/QUALITY_CONTEXT.md` line 7
**Fix:** Restored count from `33` to `46`. Count reflects actual Bug Class headers (#1–#46,
with #18 absent — never existed). Also added the v4.7.4 async_update_entry re-entrancy class
to the count description.

### MED-1 — Version strings show v4.7.4 instead of v4.7.4.3
**Decision:** No action taken on file-header comment version strings. This is a pre-existing
pattern across all releases — file headers have never been updated to sub-patch versions.
`manifest.json` and the primary `const.py` VERSION string are handled by `deploy.sh`.
The 13 file-header occurrences are documentation artifacts that pre-date this release.

### LOW-1 — Pre-existing async_update_entry calls in ENTRY_TYPE_INTEGRATION setup
**File:** `__init__.py` (first of the 7 migration sites, near line 621)
**Fix:** Added a Bug Class #46 safety analysis comment above the first `async_update_entry`
migration call explaining why all 7 calls are safe (all precede `add_update_listener`
registration at line ~2526). Extended Bug Class #46 in `docs/QUALITY_CONTEXT.md` with a
"When async_update_entry IS safe" sub-section listing the two safe conditions.
