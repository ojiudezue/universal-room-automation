# PLANNING — Config Subentries Migration + Architectural-Debt Sweep

> **SUPERSEDED 2026-06-03** by `PLANNING_setup_unload_symmetry.md` (D1 prereq, Tier 2) + `PLANNING_config_subentries_migration.md` (D2 + D3a/b/c, Tier 2-DB, GATED on the symmetry hotfix). Body retained for historical record.

**Status:** Planning. Nothing here has shipped.
**Versioning:** Unversioned until it ships — picks up the next available patch
number at deploy time. This is NOT a "5.0": major bumps are reserved for major
new functionality, and a migration + arch-debt sweep is patch-level work no
matter how large the diff. (Operator convention, 2026-06-03.)
**Current production tip:** v4.7.18.1 (sleep→waking deadlock hotfix, LIVE 2026-06-03).
**Author phase:** ura-planner.
**Cycle classification:** Tier 2-DB (justified §3).
**Estimated effort:** 30-50h spread across three deliverables (D1 prereq + D2 subentries + D3 cleanup), plus three parallel reviews + live validation.

---

## 0. Institutional context verified

This section is the proof-of-work mandated by `CLAUDE.md` §"Institutional Context First". Every additive surface or removal proposed below is annotated REUSED (with file:line) or NEW (with justification).

### 0.1 Greps run (and what they returned)

| Question | Grep | Result | Verdict |
|---|---|---|---|
| Does HA `ConfigSubentry` API appear anywhere in URA today? | `config_subentries\|ConfigSubentry\|async_add_subentry` over `custom_components/` | **0 matches.** | NEW surface — confirms ROADMAP_v11:570 claim. URA has never touched the HA 2025.2 subentry API. |
| Does `runtime_data` appear anywhere? | `runtime_data` over `custom_components/` | 2 matches in `switch.py:57-58`, both in a comment explaining the prior incorrect guard. **No production code path initializes or reads `entry.runtime_data`.** | NEW surface. Confirms ROADMAP_v11:689-695 ("not broken… URA touches the bag at __init__.py:494, 650, 1575"). |
| `hass.data[DOMAIN]` footprint | `hass\.data\[DOMAIN\]` over `custom_components/` | **161 occurrences across 17 files.** Heaviest: `__init__.py` (93), `aggregation.py` (27), `sensor.py` (21). | This is the carrier for D3 migration. Order-of-magnitude larger than the ROADMAP_v11 "~50 sites" estimate — confirm site count in build phase before scoping LoC. |
| `ENTRY_TYPE_*` constants | `ENTRY_TYPE_` over `const.py` | 5 constants (`INTEGRATION/ROOM/ZONE/ZONE_MANAGER/COORDINATOR_MANAGER`) at `const.py:50-54`. | REUSED for the migration mapping in D2. `ENTRY_TYPE_ZONE` is already declared legacy (`__init__.py:2634-2641`) — migration treats it as already-gone. |
| 16 DPM bucket CONFs | `CONF_ZONE_DYNAMIC_PRESET_(COOL\|MILD\|HOT\|EXTREME)_(HOME\|SLEEP)_(LOW\|HIGH)` over `custom_components/` | 16 constants at `energy_const.py:309-324`. Referenced in 5 files (`config_flow.py`, `dynamic_preset.py`, `energy_const.py`, `translations/en.json`, `strings.json`). | EXISTS — D3a removes them. The deferral comes from `PLANNING_v4.7.18_dpm_drift_guard_and_cleanup.md:516` ("Cleanup is a future v5.0 architectural-debt sweep"). |
| `CONF_ZONE_DYNAMIC_PRESET_CUSTOMIZE_BUCKETS` | grep target | Defined `energy_const.py:306`; referenced `config_flow.py:366, 6097, 6173`; `dynamic_preset.py:59`. | EXISTS — D3a removes the constant + 4 reference sites. UI was stripped in v4.7.18 D1 (`config_flow.py:6234-6249`); constant is now dead. |
| `MIRROR_KEYS_ZONE_DPM` | grep target | `config_flow.py:361-383` — frozenset of 21 keys (5 control + 16 bucket cells). | REUSED — D3a prunes the 16 bucket-cell entries + the `customize_buckets` entry, leaving the 4 currently-live control keys. |
| Deprecated `CONF_PHONE_TRACKER` | grep target | `const.py:315` (DEPRECATED in v3.2.4), `config_flow.py:96` (import only). 2 references total. | EXISTS — D3b removes the import + the constant. No reader remains (replaced by `CONF_SCANNER_AREAS`). |
| `async_step_*` count | grep target | **143 occurrences in `config_flow.py`** (a single file). | Context for scope: config_flow.py is a 7,685-LoC monolith. No `options_flow.py` file exists (verified by glob). D3c does NOT split this file — descoped explicitly (see §5). |
| `async_unload_entry` shape | grep target | One handler at `__init__.py:2807` with five `entry_type` branches. | REUSED — D1 (setup/unload symmetry) hardens this surface; D2 must respect it on subentry teardown. |
| Setup orphan tasks | `entry\.async_create_background_task\|hass\.async_create_task\(` | Confirmed sites at `coordinator.py:812`, `coordinator.py:417`, `__init__.py:2390` (per ROADMAP_v11:671-678) + `entry.async_create_background_task` already used by v4.2.22 cover runners (REUSED pattern). | D1 extends the existing pattern. |

### 0.2 Prior planning docs consulted

- `docs/ROADMAP_v11.md:570-698` — full read. Source of truth for v5.0 scope, the architectural-debt #0-#5 list, and the order-of-effects relationship between #0 / #1 / #5.
- `docs/planning/PLANNING_v4.7.18_dpm_drift_guard_and_cleanup.md:48, 87, 197, 513-517` — full read of §14 "Plan completion tracking (items explicitly deferred)". This is the deferral source for D3a (bucket-CONF removal). The doc explicitly assigns the cleanup to "v5.0 architectural-debt sweep".
- `docs/planning/PLANNING_v4.7.17.2_dpm_simplified_operator_frame.md` — skim of §6 "16 per-zone CONFs" row (referenced in v4.7.18 doc above). The bucket cells were already dead at runtime by v4.7.17.2 — v4.7.18 D1 only stripped the UI surface. v5.0 D3a removes the constants.
- `docs/planning/PLANNING_v4.7.4.3_*` (referenced in `__init__.py:2380-2389` comment) — skim. Source of Bug Class #46 fix that motivates D2's "no `async_update_entry` from `async_setup_entry`" constraint during subentry migration.
- `docs/planning/PLANNING_v4.7.5_*` — skim for `MIRROR_KEYS_ZONE_DPM` author intent (canonical-zone D4 auto-mirror). D3a's mirror-key shrink must not regress auto-mirror behavior for the 4 surviving keys.
- `docs/planning/PLANNING_v4.7.15_*` (sprint runbook) — skim. Source of the worktree-discipline rule (`.claude/worktrees/...`) the build phase must honor.

### 0.3 Memory bodies pulled

- `project_v4_7_18_1_sleep_wake_deadlock` — confirms v4.7.18.1 is the current production tip and that HouseStateMachine does NOT persist across restart. v5.0 D2's migration runs at HA boot; the house-state non-persistence does not affect subentry migration but IS relevant to D1 (any restart-resilience work D1 ships must NOT silently move HouseStateMachine to a persisted surface — out of scope).
- `project_single_user_no_backcompat` — explicit instruction: **no multi-version back-compat shims.** One-shot migration only. State the post-migration data shape as authoritative; no dual-read fallback after the migration completes.
- `feedback_pre_deploy_zero_bugs_gate` — applies. Before deploying v5.0: grep conflict markers, py_compile changed files, run cycle tests, run isolated suite-baseline-diff.
- `feedback_db_sensitive_3x_targeted_reviews` — applies (this cycle is Tier 2-DB; see §3).
- `feedback_fix_lows_in_cycle` — applies. Fix the reasonable LOWs (1-30 LoC) in the same fix-up pass; cap deferral doc at ~6 entries.
- `project_v4712_live` (AnomalyType discriminator) — sibling example of additive ADD-COLUMN with dual-write, similar shape to D2's subentry migration with a `legacy_flat_topology` flag for rollback.

### 0.4 Design docs read

- `docs/Coordinator/*` — no coordinator-specific design doc is materially affected by v5.0 (v5.0 is structural, not behavioral). The change crosses every coordinator's setup path via `__init__.py` rewiring, but no coordinator's `intent → action` contract changes. Verified by re-reading the coordinator manager's register sites at `__init__.py:1570-1700, 1880-1995`: each coordinator is constructed from `cm_config` dict reads — those dict reads are subentry-data-shape-agnostic once D2 normalizes the read path.

### 0.5 Code surveyed end-to-end during scoping

- `custom_components/universal_room_automation/__init__.py` (3,000+ LoC; the structural-debt epicenter). Confirmed:
  - lines 380-466: `_migrate_sensor_entity_ids` (historical pattern for entity-registry migration during setup)
  - lines 469-543: `_migrate_zones_to_zone_manager` (the **closest existing analogue** to D2 — flat zone entries collapsed to a single ZM entry, with device-registry surgery). D2 generalizes this pattern across all three managed entry types.
  - lines 545-593: `_ensure_coordinator_manager_entry` (CM bootstrap; will move into the parent subentry tree).
  - lines 596-700: `async_setup_entry` integration branch — site of D1 ownership-rewiring (services registered here are never unregistered today; ROADMAP_v11:661-668).
  - lines 2380-2400: Bug Class #46 tombstone — the explicit "no `async_update_entry` from setup" rule D2 must respect.
  - lines 2807-2970: `async_unload_entry` — five entry_type branches; D2 collapses to one parent + per-subentry teardown.
- `custom_components/universal_room_automation/config_flow.py` (7,685 LoC, 143 `async_step_*`, no separate options_flow.py). Confirmed:
  - lines 90-130: imports (the DEPRECATED `CONF_PHONE_TRACKER` at line 96 — D3b).
  - lines 350-383: `MIRROR_KEYS_ZONE_*` frozensets — D3a shrinks `MIRROR_KEYS_ZONE_DPM`.
  - lines 386-389: `class UniversalRoomAutomationConfigFlow(... VERSION = 1)` — D2 bumps to VERSION = 2 + minor_version, drives `async_migrate_entry`.
  - lines 6053-6249: `async_step_zone_dynamic_preset` + `_build_dynamic_preset_schema` — verified that the bucket CONFs are passed positionally but only the first 4 (`enabled/offset/reset_guest/sleep_enabled`) are consumed (`config_flow.py:6212-6225`). D3a removes the trailing 17 positional args and the 17 imports.
- `custom_components/universal_room_automation/domain_coordinators/dynamic_preset.py:199-234` — `_BUCKET_CONF_KEYS` lookup table is the **last remaining live reader** of the 16 bucket CONFs. Used only by diagnostic `classify_bucket()` labelling (per v4.7.18 deferral note: "constants stay readable for diagnostic `classify_bucket()` callability"). D3a removes both the lookup table AND verifies no caller reads from entry options via those keys — confirmed by grep: callers consume the lookup table for label strings only, not for option-value resolution.
- `custom_components/universal_room_automation/domain_coordinators/energy_const.py:306-324` — the 17 constants to delete (16 bucket + customize_buckets).
- `custom_components/universal_room_automation/const.py:50-54, 314-315` — `ENTRY_TYPE_*` table (REUSED for D2 mapping) and DEPRECATED `CONF_PHONE_TRACKER` (D3b).

---

## 1. Prereq gate (BLOCKING — explicit)

**Resolving the prereq numbering ambiguity.** The ROADMAP_v11 §"v5.0" header says:

> Depends on: Test baseline cleanup (#0 in tech debt) + setup/unload
> symmetry pass (#3 in tech debt) must complete first

But the tech-debt list immediately below numbers the items differently:

- **#0** Test baseline cleanup — **DONE in v4.5.2** (ROADMAP_v11:629).
- **#1** Setup/unload symmetry (= "review item #3").
- **#2** Tracked background tasks (= "review item #4").
- **#3** EntityDescription rollout (= "review item #5").
- **#4** `runtime_data` migration (= "review item #1").
- **#5** Config subentries (= v5.0 itself; "review item #2").

The header's "#3" refers to the **external code-review item #3** (i.e. setup/unload symmetry), which lands as **tech-debt item #1** in the locally-renumbered list. The current planning doc adopts the local numbering ("#1 setup/unload symmetry") as authoritative.

**Therefore the v5.0 blocking prereq is tech-debt item #1 — setup/unload symmetry — NOT item #3 (EntityDescription rollout).**

Item #0 (test baseline) is already satisfied. Items #2 (tracked background tasks), #3 (EntityDescription), and #4 (`runtime_data`) are NOT pre-blocking for D2 (subentries) but #4 is absorbed into v5.0 as D3c (see §2.4).

**The gate.** D1 (setup/unload symmetry) must ship and live-validate BEFORE D2 (subentry migration) is built. Reason: D2 inverts entry ownership (one parent + 33 subentries replaces 34 siblings) — if shared resources (database, coordinator manager, panels, services, static paths) are owned by the wrong entry, unload of the parent will tear them down while subentries still depend on them. The v4.2.24 silent-save bug class is exactly this surface (`__init__.py:1908` per ROADMAP_v11:666). Shipping D2 on top of an asymmetric setup/unload path multiplies the blast radius.

**Sequencing rule:** D1 ships as a standalone hotfix-scale cycle (likely **v4.7.19**) and lives on `develop` for at least one live-validation window before D2 is built. Do not merge D2 into the same release as D1.

---

## 2. Deliverables

### D1: Setup/Unload Symmetry (PREREQ — ships as v4.7.19)

**Scope:** address tech-debt item #1. Every listener/timer/registration created by an entry must be released by that entry's unload. Shared resources must be reference-counted or parent-owned.

**Surfaces touched:**
- `__init__.py:1589` — `_async_register_*_services` calls in integration `async_setup_entry`. Wrap unregister-on-unload via `entry.async_on_unload(lambda: hass.services.async_remove(DOMAIN, "<name>"))` for each service. REUSED pattern: `entry.async_on_unload` is already used at `__init__.py:2399, 2627`.
- `__init__.py:1615, 1640` — `hass.http.async_register_static_paths` and `panel_custom.async_register_panel`. Wrap teardown via the same `async_on_unload` hook.
- `__init__.py:2807-2970` — `async_unload_entry`. Audit each `hass.data[DOMAIN].pop(...)` for paired cleanup symmetry; convert remaining ad-hoc `del` patterns to `pop(..., None)` (defensive; matches existing v4.6.10 review-fix B2 pattern at `__init__.py:2884`).
- `coordinator.py:812, 417` and `__init__.py:2390` — convert untracked `hass.async_create_task(...)` to `entry.async_create_background_task(hass, ..., name=...)` per ROADMAP_v11:671-678. REUSED pattern from v4.2.22 cover runners.

**Surfaces NOT touched in D1** (descoped to keep D1 hotfix-scale):
- Tech-debt #3 (EntityDescription) — separate ROI track.
- Tech-debt #4 (`runtime_data`) — pulled into v5.0 D3c.

**Constants/symbols:** no new constants. No new entities. Pure plumbing.

**Acceptance criteria:**
- **Verify:** After integration reload, `hass.services.async_services()[DOMAIN]` returns the same set as before reload (no stale services). Today, `_async_register_presence_services` etc. accumulate one ghost copy per reload.
- **Verify:** `dir(hass.data[DOMAIN])` after `async_unload_entry(integration_entry)` returns no stale keys for `transition_detector`, `bayesian_predictor`, `weather_manager`, `perimeter_alert_manager`, `transit_validator`, `egress_tracker`, `coordinator_manager`, `census`, `camera_manager`, `activity_logger`, `database`, `_db_init_lock`.
- **Test:** `quality/tests/test_v4_7_19_setup_unload_symmetry.py::test_services_unregistered_on_unload`, `test_panels_torn_down_on_unload`, `test_static_paths_released_on_unload`, `test_hass_data_drained_on_unload`. Each test reloads the integration entry and asserts no resource leaks across cycles.
- **Test (AST regression):** `test_no_untracked_async_create_task_in_coordinator_or_init` — AST-walk `coordinator.py` and `__init__.py` and fail on any `hass.async_create_task(` call that isn't part of a tracked pattern (`entry.async_create_background_task`, `asyncio.gather`, or explicitly `# noqa: untracked-ok` with justification comment).
- **Live:** After HA restart on the operator's live instance, the URA reload button (Developer Tools → YAML → Reload Universal Room Automation) can be pressed **5 times in a row** without the integration accumulating any ERROR logs and without HA-core logs showing "stale service" or "duplicate static path" warnings.
- **Live:** `setup_telemetry` sensor on the CM device shows monotonically-correct counters for setup/unload cycles (the v4.6.10 review-fix B2 pattern already exposes this).

### D2: Config Subentries Migration

**Scope:** one-shot migration of THIS install's 34 flat sibling entries to one parent integration entry with 33 HA config subentries (HA 2025.2 API). See https://developers.home-assistant.io/blog/2025/02/16/config-subentries/.

**Pre-migration topology (current):**
- 1× `ENTRY_TYPE_INTEGRATION` (the parent)
- N× `ENTRY_TYPE_ROOM` (each room is a sibling entry; ~30 today)
- 1× `ENTRY_TYPE_ZONE_MANAGER` (sibling)
- 1× `ENTRY_TYPE_COORDINATOR_MANAGER` (sibling)
- 0× `ENTRY_TYPE_ZONE` (legacy; declared deprecated at `__init__.py:2634-2641` and migrated to ZM in v3.6.0).

**Post-migration topology:**
- 1× parent integration entry (unchanged `entry_id`)
- 33 subentries hanging off the parent (one `subentry_type` per source ENTRY_TYPE, preserving `room_name` / `zone_name` / etc. on the subentry `data` dict)

**Mechanism:**
1. Bump `class UniversalRoomAutomationConfigFlow(... VERSION = 2)` in `config_flow.py:386-389`. Add `minor_version = 1`.
2. Implement `async_migrate_entry(hass, config_entry)` at the module level in `__init__.py` (NEW function — verified by grep, no existing `async_migrate_entry` defined). The function inspects the entry version and, on version=1, executes the one-shot conversion.
3. The migration runs ONLY on the parent integration entry. For each sibling room/ZM/CM entry, the migration:
   - Reads `entry.data` + `entry.options`
   - Calls `hass.config_entries.async_add_subentry(parent_entry, ConfigSubentry(subentry_type=<mapped type>, data=<copied data>, title=<entry.title>))`
   - Then calls `await hass.config_entries.async_remove(sibling_entry.entry_id)` for the now-migrated sibling
4. Register one `ConfigSubentryFlow` per `subentry_type` for adding new rooms/zones via standard HA UI after migration.
5. Refactor `async_setup_entry` to dispatch by subentry. The five `entry_type` branches (`__init__.py:610-2641`) collapse to one parent setup + a `for subentry in entry.subentries: setup_subentry(...)` loop.
6. Refactor `async_unload_entry` symmetrically. Add `async_unload_subentry(hass, parent_entry, subentry)` per HA's contract — this is the contract that replaces the URA-coded coordinator-manager listener chain (ROADMAP_v11:589-591).

**Migration safety (the non-negotiables):**
- **Dry-run mode (required per ROADMAP_v11:608).** Implement `URA_SUBENTRY_MIGRATION_DRY_RUN` env-var gate. When set, `async_migrate_entry` logs the planned subentry add + sibling remove for every entry, then returns False (skips actual migration). Operator runs this before the live migration to inspect the plan.
- **Transactional rollback (required per ROADMAP_v11:607).** The migration runs in a try/except that, on any failure mid-batch, calls `_rollback_partial_migration` to remove any subentries created so far AND restore the sibling entries that were already removed (using snapshotted `data/options/title/entry_id` captured at function entry). If rollback itself fails, raise `ConfigEntryNotReady` so HA leaves the integration in a non-loaded state instead of split-brain.
- **No `async_update_entry` calls from inside `async_setup_entry` on the parent entry during migration** — Bug Class #46 (`__init__.py:615-619`). All subentry add/remove operations happen inside `async_migrate_entry`, NOT inside `async_setup_entry`.
- **Pre-flight snapshot.** Before any mutation, write a JSON snapshot of the full pre-migration entry topology to `<config>/universal_room_automation/v5_premigration_snapshot.json`. Operator (and `@shipwatch`) can compare post-migration topology against this for spot-check. The snapshot file is the rollback source of truth when the in-memory rollback path fails.
- **No multi-version back-compat.** Per `single_user_no_backcompat`: after migration runs once and `entry.version == 2`, there is no path that reads the old flat-sibling shape. No dual-read fallback. Operator-owned rollback procedure is "restore from HA storage backup taken pre-deploy."

**Entry-type → subentry-type mapping (NEW constants in `const.py`):**
- `SUBENTRY_TYPE_ROOM = "room"` (replaces `ENTRY_TYPE_ROOM`)
- `SUBENTRY_TYPE_ZONE_MANAGER = "zone_manager"` (replaces `ENTRY_TYPE_ZONE_MANAGER`)
- `SUBENTRY_TYPE_COORDINATOR_MANAGER = "coordinator_manager"` (replaces `ENTRY_TYPE_COORDINATOR_MANAGER`)

The legacy `ENTRY_TYPE_*` constants are KEPT as aliases for one release window (only for the migration code path to reference). They are deleted in v5.1 once migration is provably complete on the operator's install.

**Acceptance criteria:**
- **Verify:** Pre-migration: `len(hass.config_entries.async_entries(DOMAIN))` returns 33-34 (varies with current room count). Post-migration: returns **1** (the parent), with `len(parent.subentries) == 32-33` (one fewer than pre, because the integration entry itself no longer counts as a sibling).
- **Verify:** Pre-migration JSON snapshot file exists at `<config>/universal_room_automation/v5_premigration_snapshot.json` with all 34 entries' `data + options + title`.
- **Verify:** Dry-run mode: setting `URA_SUBENTRY_MIGRATION_DRY_RUN=1` and restarting HA logs the planned migration without mutating the entry registry. Re-running without the env var executes the migration.
- **Verify:** Every room/zone/manager subentry's `data` dict equals the pre-migration sibling's `{**data, **options}` dict (no key loss).
- **Sensor:** `sensor.ura_subentry_migration_state` (NEW diagnostic sensor on the integration device) shows one of `not_started`, `dry_run_complete`, `migrated`, `rolled_back`, `failed`. Attributes include `pre_count`, `post_count`, `migration_timestamp`, `snapshot_path`.
- **Test:** `quality/tests/test_v5_0_subentry_migration.py`:
  - `test_migration_creates_subentry_per_sibling`
  - `test_migration_preserves_data_and_options_per_entry`
  - `test_migration_is_idempotent_on_version_2_entry`
  - `test_dry_run_does_not_mutate_registry`
  - `test_rollback_on_partial_failure_restores_pre_state`
  - `test_snapshot_file_written_before_any_mutation`
  - `test_legacy_entry_type_zone_skipped_silently` (already-migrated zone entries — guard against double-handling)
  - `test_async_setup_entry_dispatches_per_subentry_type`
  - `test_async_unload_subentry_releases_only_that_subentrys_resources`
- **Test (AST regression):** `test_no_async_update_entry_in_async_migrate_entry` — assert `async_migrate_entry` body contains zero `async_update_entry` calls.
- **Live:** After HA restart with the migration applied, all 90+ entities per room are present and functional (count via `entity_registry.async_get(hass).entities` filtered by `platform == DOMAIN`). Zero `ConfigEntryNotReady` exceptions in the post-restart log.
- **Live:** Adding a new room via the standard HA UI (Settings → Devices → URA → Add Subentry → Room) completes without touching `__init__.py` registry-surgery code. Today, new rooms route through the legacy flat-sibling flow.
- **Live (`@shipwatch`):** Acceptance hypothesis "post-migration entity count = pre-migration entity count" passes within the first census cycle.

### D3: Constant cleanup + runtime_data migration + config-flow tidy

Three sub-deliverables, sized small enough to ride D2 in the same release. Each is independent and can be reverted without affecting the others.

#### D3a: 16 bucket CONFs + `customize_buckets` removal

**Surfaces touched:**
- `domain_coordinators/energy_const.py:306-324` — DELETE 17 constants:
  - `CONF_ZONE_DYNAMIC_PRESET_CUSTOMIZE_BUCKETS`
  - 8× `CONF_ZONE_DYNAMIC_PRESET_<BUCKET>_HOME_<LOW|HIGH>`
  - 8× `CONF_ZONE_DYNAMIC_PRESET_<BUCKET>_SLEEP_<LOW|HIGH>`
- `domain_coordinators/dynamic_preset.py:55-75, 199-234` — DELETE 17 imports AND `_BUCKET_CONF_KEYS` lookup table. Confirm via grep that `classify_bucket()` no longer references the table (the v4.7.18 deferral comment said "constants stay readable for diagnostic `classify_bucket()` callability"; v5.0 confirms this was either over-cautious or addressable). If `classify_bucket()` still needs bucket labels, replace with a `BucketClass` StrEnum value lookup (already exists at `dynamic_preset.py:199-205`).
- `config_flow.py:6092-6115` — DELETE 17 imports from `energy_const` for the `async_step_zone_dynamic_preset` step.
- `config_flow.py:6164-6184` — DELETE the trailing 17 positional args from the `_build_dynamic_preset_schema` call. Update call signature to accept only the 4 live keys.
- `config_flow.py:6186-6249` — Update `_build_dynamic_preset_schema` signature from `*conf_keys` variadic to 4 explicit positional args (`enabled`, `offset`, `reset_guest`, `sleep_enabled`).
- `config_flow.py:361-383` — Shrink `MIRROR_KEYS_ZONE_DPM` from 21 keys to 4 (`enabled`, `offset`, `reset_offset_guest`, `sleep_enabled`).
- `translations/en.json` + `strings.json` — DELETE 17 string keys for the bucket labels.

**Data preservation:** The 16 bucket values may still exist in subentry `data` post-D2 migration. D3a does NOT delete them from subentry data. They remain as dead keys (no reader) until a future v5.x explicit subentry data-shape migration. This matches the v4.7.18 "data-preserved, UI-stripped" precedent.

**Acceptance criteria:**
- **Verify:** `grep -r "CONF_ZONE_DYNAMIC_PRESET_CUSTOMIZE_BUCKETS\|CONF_ZONE_DYNAMIC_PRESET_(COOL\|MILD\|HOT\|EXTREME)_(HOME\|SLEEP)_(LOW\|HIGH)" custom_components/` returns 0 matches.
- **Verify:** `MIRROR_KEYS_ZONE_DPM` is a frozenset of exactly 4 keys.
- **Test:** `test_v5_0_d3a_bucket_constants_removed` — AST regression. Imports the 17 constants from `energy_const` and asserts `ImportError` for each.
- **Test:** `test_v5_0_d3a_subentry_data_with_legacy_bucket_keys_still_loads` — subentry whose `data` dict contains the 16 legacy bucket keys still loads cleanly (no schema rejection).
- **Live:** Surface 2 (zone DPM config) still renders the 4-field form. Saving the form still mirrors to siblings via `_auto_mirror_to_siblings` (`config_flow.py:6157-6160`).

#### D3b: `CONF_PHONE_TRACKER` removal

**Surfaces touched:**
- `const.py:314-315` — DELETE the constant + deprecation comment.
- `config_flow.py:96` — DELETE the import line.

**Acceptance criteria:**
- **Verify:** `grep -r "CONF_PHONE_TRACKER" custom_components/` returns 0 matches.
- **Test:** Existing config-flow tests pass unchanged.

#### D3c: `runtime_data` migration

**Scope:** absorb tech-debt item #4. Migrate `hass.data[DOMAIN]` writes/reads to `entry.runtime_data` typed access. This is the **biggest LoC delta in v5.0** — grep showed 161 occurrences across 17 files (vs. ROADMAP_v11's "~50 sites" estimate; field-verify in build).

**Mechanism:**
1. Define a typed dataclass `URARuntimeData` in `__init__.py` capturing all the keys currently stored in `hass.data[DOMAIN]`: `database`, `coordinator_manager`, `person_coordinator`, `transition_detector`, `bayesian_predictor`, `census`, `camera_manager`, `perimeter_alert_manager`, `transit_validator`, `egress_tracker`, `weather_manager`, `activity_logger`, `setup_telemetry`, plus the `unsub_*` cleanup handles.
2. On parent setup, `entry.runtime_data = URARuntimeData(...)`.
3. Migrate read sites from `hass.data[DOMAIN].get(key)` to `entry.runtime_data.<attr>`.
4. **Critically:** the cross-platform shared resources (database, coordinator_manager) are owned by the **parent integration entry's** runtime_data. Subentries access them via a lookup helper `_parent_runtime(hass, subentry) -> URARuntimeData`. This preserves the single-DB-instance invariant from `__init__.py:2649-2660`.

**Descoped from D3c (defer to v5.0.x or v5.1):**
- The 27 `hass.data[DOMAIN]` references inside `domain_coordinators/` and `aggregation.py` (per grep). Migrating these requires touching coordinator-internal APIs. Initial D3c migration covers `__init__.py` + the four platform files (`sensor/binary_sensor/switch/button`) — ~130 of the 161 sites. Coordinator-internal sites stay on `hass.data[DOMAIN]` for one release, then sweep in v5.0.1.

**Acceptance criteria:**
- **Verify:** `grep -rn "hass\.data\[DOMAIN\]" custom_components/universal_room_automation/__init__.py | wc -l` drops from 93 to ≤ 5 (only the database/coordinator-manager bootstrap reads that must precede `entry.runtime_data = ...` assignment).
- **Verify:** `entry.runtime_data` is set on the parent entry after `async_setup_entry` returns.
- **Test:** `test_v5_0_d3c_runtime_data_typed_access` — assert `entry.runtime_data` is a `URARuntimeData` instance after setup; assert `entry.runtime_data.database is not None`.
- **Test:** `test_v5_0_d3c_no_hass_data_in_platform_files` — AST regression over `sensor.py`, `binary_sensor.py`, `switch.py`, `button.py`. Allow ≤ N references per file (where N is the verified pre-migration count minus the migrated sites).
- **Live:** No `KeyError` or `AttributeError` in the post-restart log referencing `hass.data['universal_room_automation']`.

#### D3d: NOT in scope — config_flow.py file split

`config_flow.py` is 7,685 LoC with 143 `async_step_*` methods, no separate `options_flow.py`. Splitting the file is tempting but is a separate architectural refactor with its own review surface. **Descoped to v5.1** to keep v5.0's review-surface scope-bounded.

---

## 3. Tier classification: Tier 2-DB (justified)

This cycle meets the Tier 2-DB trigger criteria from `CLAUDE.md`:

- ☑ **Cycle migrates ≥3 callers to a new shape.** D2 migrates 34 config entries → 33 subentries — every caller of `entry.data`/`entry.options` is affected.
- ☑ **Cycle changes payload shape of a persisted record.** Config-entry storage shape changes (flat siblings → parent.subentries). HA persists this via `core.config_entries` storage.
- ☑ **Cycle is followed within 1-2 versions by a planned schema migration.** D3a (bucket-key removal from subentry data) is the natural follow-up. D3c's coordinator-internal sweep is v5.0.1.
- ☑ **Trust-hierarchy ripple change.** The operator-elevated Tier 2-DB criterion applies independently: D2 ripples through every coordinator's setup path (presence ↔ HVAC ↔ compliance ↔ safety ↔ security ↔ MF ↔ energy). A surgical change here can regress any single coordinator's boot sequence.

**Three parallel reviews, framing-disjoint:**

- **Review A — Data integrity + entry-registry preservation.** Every pre-migration entry's `data + options` is preserved byte-for-byte in the corresponding subentry. No key loss. Pre-migration snapshot file is written before any mutation. Existing readers of the legacy `ENTRY_TYPE_*` flat shape are removed or gated. Existing entity unique_ids unchanged. Existing device_registry identifiers unchanged.
- **Review B — Migration correctness + lifecycle / restart resilience.** `async_migrate_entry` is the only mutator (no `async_update_entry` from `async_setup_entry`). Rollback path is exercised in tests. Dry-run mode is honored. Bug Class #46 invariant holds. D1 setup/unload symmetry is verified BEFORE D2 lands. Subentry teardown contract (`async_unload_subentry`) releases only that subentry's listeners.
- **Review C — New surfaces + test fixture authority.** The new `sensor.ura_subentry_migration_state` diagnostic round-trips through RestoreEntity. The new `URARuntimeData` dataclass shape is verified by tests, not hand-copied between code and test. AST regression tests for bucket-CONF removal extract the target import list from the production source (`energy_const.py`), not a hand-copied tuple.

Run the three reviews in PARALLEL — different framings can't share blind spots.

**Pre-deploy snapshot of affected entity counts** by `(platform, device_class)` over all URA entities. Operator runs this snapshot ~1h before deploy. Post-deploy comparison: counts within ±2 entities (allowing for the new D2 diagnostic sensor + any natural noise) for every (platform, device_class) bucket.

**Live Validation (Review D):** Post-restart, after the migration has run:
- `len(hass.config_entries.async_entries(DOMAIN)) == 1` (just the parent)
- `len(parent.subentries) == pre_migration_count - 1`
- All 90+-per-room entities present
- `@shipwatch` post-deploy hypothesis: "post-migration entity count = pre-migration entity count ± 2" passes within first census cycle.

---

## 4. Sequencing (the gate, explicit)

```
            ┌─────────────────────────────────────────────┐
            │  Today (2026-06-03): v4.7.18.1 LIVE         │
            └──────────────────────┬──────────────────────┘
                                   │
                                   ▼
            ┌─────────────────────────────────────────────┐
            │  v4.7.19 — D1 setup/unload symmetry         │
            │  Tier 2 (two reviews, not Tier 2-DB)        │
            │  Live-validate on operator instance         │
            │  ≥1 reload cycle clean before D2 build      │
            └──────────────────────┬──────────────────────┘
                                   │ [GATE — D1 must live-validate]
                                   ▼
            ┌─────────────────────────────────────────────┐
            │  v5.0 — D2 subentries + D3a/b/c cleanup     │
            │  Tier 2-DB (three reviews, framing-disjoint)│
            │  Dry-run pass → live migration → snapshot   │
            │  comparison → @shipwatch acceptance         │
            └──────────────────────┬──────────────────────┘
                                   │
                                   ▼
            ┌─────────────────────────────────────────────┐
            │  v5.0.1 — D3c coordinator-internal sweep    │
            │  (remaining hass.data[DOMAIN] sites)        │
            └─────────────────────────────────────────────┘
```

D1 ships as `v4.7.19` on its own release. D2+D3a+D3b+D3c ship together as `v5.0` (single deploy). D3c coordinator-internal sweep is `v5.0.1` (small follow-up).

---

## 5. Plan-completion tracking (items explicitly deferred)

Per `CLAUDE.md` §"Plan Completion Tracking — MANDATORY", every item that's NOT shipped in v5.0 is documented here.

1. **D3c coordinator-internal `hass.data[DOMAIN]` sweep** — deferred to **v5.0.1**. Reason: scope-bound the v5.0 review surface. The 27 references inside `domain_coordinators/` + `aggregation.py` require touching coordinator-internal APIs and would expand Review C's surface beyond what three parallel reviewers can reliably cover.
2. **`config_flow.py` file split / separate `options_flow.py`** (D3d) — deferred to **v5.1**. Reason: 7,685 LoC monolith refactor has its own review surface. Splitting on top of D2 multiplies blind-spot risk.
3. **Bucket-key removal from subentry `data` dicts** — deferred to **v5.x explicit data-shape migration**. Reason: matches v4.7.18 "data-preserved, UI-stripped" precedent. D3a removes constants but leaves stale data keys until a future subentry data-shape migration cleans them in one pass.
4. **Tech-debt #2 (tracked background tasks)** — partially absorbed into D1; the remaining `coordinator.py` sites swept opportunistically. Full sweep deferred to **v5.0.2** if any sites remain after D1's audit.
5. **Tech-debt #3 (EntityDescription rollout)** — NOT in v5.0 at all. Independent ROI track per ROADMAP_v11:680-687. Force-functioned by the next new-coordinator cycle (Optimization, per v4.0.0 roadmap).
6. **Legacy `ENTRY_TYPE_*` constant deletion** — kept as aliases in v5.0 for the one-release-window after migration. Deleted in **v5.1** once the operator's install is provably migrated.

Cap reached at 6 entries per `feedback_fix_lows_in_cycle`. Any LOW issues surfaced during reviews that fit the 1-30 LoC bar are fixed in the v5.0 fix-up pass, NOT added to this list.

---

## 6. Risk register

| ID | Risk | Probability | Impact | Mitigation |
|---|---|---|---|---|
| R1 | Subentry API in HA 2025.2 has undocumented edge cases on parent reload | Medium | High | Dry-run mode + snapshot file + rollback path. Reviewer B specifically chartered to walk every lifecycle path. |
| R2 | Migration succeeds but a coordinator's `cm_config` read shape changes silently | Medium | High | Reviewer A chartered to verify byte-for-byte data preservation. D3c does NOT change coordinator-internal reads in v5.0; coordinator-internal sweep waits for v5.0.1. |
| R3 | D1 ships but doesn't live-validate cleanly before D2 build begins | Low | High | The sequencing gate (§4) is non-negotiable. If D1 ships and reveals a regression, D2 build does not begin until D1 is hotfixed and clean. |
| R4 | Operator runs migration without taking pre-deploy HA storage backup | Low | Critical | README_v5.0.md MUST include a top-of-doc "BEFORE DEPLOY: take HA storage backup" callout, and `scripts/deploy.sh` should print this reminder for v5.0 specifically. |
| R5 | `entry.runtime_data` typed access surfaces None-attribute errors at coordinator startup | Medium | Medium | D3c initializes `URARuntimeData` with all attrs set to None and populates them incrementally. Coordinators that read pre-init must handle None (same contract as today's `hass.data[DOMAIN].get(key)` pattern). |
| R6 | Snapshot file collision with existing `data/` directory | Low | Low | Use `<config>/universal_room_automation/v5_premigration_snapshot.json` (already a managed URA directory per `git status` showing `data/` is gitignored). |

---

## 7. README requirements

`docs/readmes/README_v5.0.md` must include:

1. **Top-of-doc "BEFORE DEPLOY" callout** — operator MUST take HA storage backup before deploy.
2. **Migration runbook** — `URA_SUBENTRY_MIGRATION_DRY_RUN=1` dry-run procedure (env var set → HA restart → inspect logs → revert env var → HA restart → live migration).
3. **Pre-deploy snapshot procedure** — operator runs entity-count query before deploy; saves output.
4. **Post-deploy validation** — exact entity-count comparison + the 4 D2 acceptance-criteria entity IDs.
5. **Rollback procedure** — if the migration sensor shows `failed` or `rolled_back`, restore from HA storage backup; do NOT attempt manual entry-registry surgery.
6. **Known limitations** — D3c coordinator-internal sites still on legacy `hass.data` (deferred to v5.0.1).
7. **Cross-cycle references** — v4.7.19 (D1 prereq), `PLANNING_v4.7.18_dpm_drift_guard_and_cleanup.md:516` (D3a deferral source), ROADMAP_v11:570-698 (v5.0 + arch-debt queue), https://developers.home-assistant.io/blog/2025/02/16/config-subentries/.

---

## 8. Recall

- "Resume v5.0 subentries plan"
- "v5.0 plan"
- "Plan config subentries migration"
- "Plan bucket-CONF removal"
- "Plan runtime_data migration"
