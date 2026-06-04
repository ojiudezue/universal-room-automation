# PLANNING — Config Subentries Migration

**Status:** Planning. **GATE CLEARED 2026-06-04.** The blocking prereq
(`PLANNING_setup_unload_symmetry.md`) shipped as **v4.7.18.3** (paired
teardowns + tracked background tasks, LIVE; Tier 2 two-reviewer cycle;
Reviewer-B CRITICAL self-reload-task carve-out documented in the
v4.7.18.3 README). The presence-provenance follow-on cycle then
shipped as **v4.7.19** (current `develop` tip, `manifest.json:21`). The
symmetry surface has live-validated through ≥1 organic reload cycle on
the operator's instance. This cycle is now **READY TO ENTER BUILD**
once the operator signs off on planning.
**Versioning:** Unversioned until it ships — picks up the next available
patch number at deploy time. **This is NOT a "5.0":** major version bumps
are reserved for major new functionality. A migration + cleanup sweep
remains patch-level work no matter how large the diff (operator
versioning convention, 2026-06-03; see `feedback_versioning_convention`).
**Current production tip (at plan refresh):** v4.7.19 (presence
Tier-1 provenance split + fan-interference Layer-1 diagnostic).
**Author phase:** ura-planner.
**Cycle classification:** **Tier 2-DB** (three parallel framing-disjoint
reviews — see §3). Operator may additionally elevate via the
trust-hierarchy-ripple criterion; that elevation is already implicit in
the §3 Tier 2-DB justification.
**Estimated effort:** 30-50h across three sub-deliverables (D2 subentries
+ D3a/b/c cleanup), plus three parallel reviews + live validation.
**Concurrency note:** A sibling planner is concurrently scoping a
presence/fan-noise cycle in `presence.py` / `aggregation.py` /
`binary_sensor.py`. This plan stays OUT of those files. Its surface is
strictly `config_flow.py`, `__init__.py`, `const.py`, and the four
`energy_const.py` / `dynamic_preset.py` / translations bucket-CONF sites
for D3a.

---

## 0. Institutional context verified

This section is the proof-of-work mandated by `CLAUDE.md`
§"Institutional Context First". All file:line citations in this section
were re-verified against the current `develop` tip (v4.7.19,
`manifest.json:21`) on 2026-06-04. Line numbers from the predecessor
bundled doc (`PLANNING_config_subentries_and_arch_debt.md`, superseded)
and from this doc's prior revision (v4.7.18.1-baselined) have drifted
due to v4.7.18.3 (~128 ins `__init__.py`, ~99 ins `coordinator.py`)
and v4.7.19. Refreshed citations below; any line marked
**build-time-verify** is one that MUST be reconfirmed by `ura-builder`
because the surface is large enough that drift is plausible.

### 0.1 Greps run (and what they returned — 2026-06-04 refresh)

| Question | Grep | Result | Verdict |
|---|---|---|---|
| Does HA `ConfigSubentry` API appear anywhere in URA today? | `config_subentries\|ConfigSubentry\|async_add_subentry` over `custom_components/` | **0 matches.** | NEW surface — URA has never touched the HA 2025.2 subentry API. |
| Does `runtime_data` appear anywhere? | `runtime_data` over `custom_components/` | 2 matches in `switch.py:57-58`, both in a comment. **No production code path initializes or reads `entry.runtime_data`.** | NEW surface. |
| `hass.data[DOMAIN]` footprint | `hass\.data\[DOMAIN\]` over `custom_components/` | **159 occurrences across 17 files** (refreshed 2026-06-04; was 161 in prior plan revision). Heaviest: `__init__.py` (90), `aggregation.py` (27), `sensor.py` (21). | Carrier for D3c migration. Slight drift since prior revision; build-phase will re-count. |
| `ENTRY_TYPE_*` constants | `ENTRY_TYPE_` over `const.py` | 5 constants (`INTEGRATION/ROOM/ZONE/ZONE_MANAGER/COORDINATOR_MANAGER`) at `const.py:50-54`. Used at ~20 sites in `__init__.py` (incl. dispatch branches `:610, :2416, :2480, :2885, :3046, :3060`). | REUSED for D2 mapping. Legacy `ENTRY_TYPE_ZONE` is already migrated away and is skipped silently in D2. |
| 16 DPM bucket CONFs | `CONF_ZONE_DYNAMIC_PRESET_(COOL\|MILD\|HOT\|EXTREME)_(HOME\|SLEEP)_(LOW\|HIGH)` over `custom_components/` | 16 constants at `energy_const.py:309-324` (build-time-verify exact lines). Referenced in 5 files (`config_flow.py`, `dynamic_preset.py`, `energy_const.py`, `translations/en.json`, `strings.json`). | EXISTS — D3a removes them. Deferral source: `PLANNING_v4.7.18_dpm_drift_guard_and_cleanup.md:516`. |
| `CONF_ZONE_DYNAMIC_PRESET_CUSTOMIZE_BUCKETS` | grep target | Defined `energy_const.py:306` (build-time-verify); referenced in `config_flow.py` + `dynamic_preset.py`. | EXISTS — D3a removes constant + ref sites. UI stripped in v4.7.18 D1; constant now dead. |
| `MIRROR_KEYS_ZONE_DPM` | grep target | `config_flow.py:361` (frozenset definition); call site `config_flow.py:6158`. Frozenset of 21 keys (5 control + 16 bucket). | REUSED — D3a prunes to 4 live control keys (`enabled`, `offset`, `reset_offset_guest`, `sleep_enabled`). |
| `_BUCKET_CONF_KEYS` lookup | grep target | `dynamic_preset.py:209` definition; readers `:847, :856`. **`:856` is a "presence-check only" call.** | EXISTS — D3a removes the table; check whether removal is safe given `:847` `if bucket not in _BUCKET_CONF_KEYS` branch — likely replaceable with `BucketClass` StrEnum membership test (build-time-verify). |
| Deprecated `CONF_PHONE_TRACKER` | grep target | `const.py:321-322` (DEPRECATED in v3.2.4 — drifted from prior plan's `:314-315`), `config_flow.py:96` (import only), `config_flow.py:14` (comment only). 4 reference sites total (no live readers). | EXISTS — D3b removes constant + comment + import. |
| `async_step_*` count | grep target | **143 occurrences in `config_flow.py`** (single file, build-time-verify exact count). | Context: 7,685-LoC monolith. No `options_flow.py` exists. **D3d (file split) is DESCOPED** — see §5. |
| `async_setup_entry` shape | grep target | One handler at `__init__.py:596` (drifted from prior `:610`). Dispatches on `entry_type` to 5 branches at `:610 (INTEGRATION), :2416 (ZONE_MANAGER), :2480 (COORDINATOR_MANAGER)`, plus ROOM and (legacy) ZONE. | REUSED — D2 collapses to one parent setup + per-subentry dispatch loop. |
| `async_unload_entry` shape | grep target | One handler at `__init__.py:2881` (drifted from prior `:2807` and bundled-doc `:2807-2970`) with five `entry_type` branches. | REUSED — D2 collapses to one parent + per-subentry teardown via `async_unload_subentry`. v4.7.18.3's paired-teardown discipline must be preserved on the new per-subentry path. |
| `async_migrate_entry` existing? | grep target | **0 matches.** | NEW function — D2 introduces this. |
| Bug Class #46 tombstone | grep target | `__init__.py:2380-2389` (build-time-verify after v4.7.18.3/19 drift; prior plan cited same range). | Explicit rule: no `async_update_entry` from `async_setup_entry`. D2 respects this. |

### 0.2 Prior planning docs consulted

- `docs/ROADMAP_v11.md:570-698` — full read. Source of truth for
  architectural-debt #0-#5 list and order-of-effects relationship
  between #0 / #1 / #5.
- `docs/planning/PLANNING_config_subentries_and_arch_debt.md` —
  predecessor bundled doc, superseded by `PLANNING_setup_unload_symmetry.md`
  (shipped as v4.7.18.3) plus this plan. §2 D2 (lines 131-190) and §2 D3
  (lines 192-251) are this doc's direct ancestors.
- `docs/planning/PLANNING_setup_unload_symmetry.md` — **SHIPPED as
  v4.7.18.3.** Live-validated. The gate is CLEAR. v4.7.18.3 paired
  teardowns for DOMAIN services, two frontend panels, ~11 background
  tasks, plus `pop(key, None)` defensiveness on every `__init__.py`
  unload branch. Reviewer-B carved out one deliberate untracked
  self-reload task (B-CRIT-1) per HA-core convention. D2 preserves
  these guarantees on every NEW per-subentry teardown path.
- `docs/readmes/README_v4.7.18.3.md` — full read. Documents the
  carve-out and the AST canary tests that pin the untracked self-reload
  shape (`quality/tests/test_setup_unload_symmetry.py`, 11 tests).
- `docs/readmes/README_v4.7.19.md` — skim. v4.7.19 is presence-tier
  provenance + fan-noise diagnostic; does NOT touch `__init__.py` setup
  ordering or `config_flow.py` topology. No interaction surface with
  this cycle.
- `docs/planning/PLANNING_v4.7.18_dpm_drift_guard_and_cleanup.md:48, 87,
  197, 513-517` — deferral source for D3a. Doc explicitly assigns the
  cleanup to "v5.0 architectural-debt sweep" — captured here as
  patch-level cleanup riding the migration cycle.
- `docs/planning/PLANNING_v4.7.17.2_dpm_simplified_operator_frame.md` —
  skim of §6 "16 per-zone CONFs" row. Bucket cells were dead at runtime
  by v4.7.17.2; v4.7.18 stripped the UI; this cycle removes the
  constants.
- `docs/planning/PLANNING_v4.7.4.3_*` — Bug Class #46 source. D2 must
  NOT call `async_update_entry` from inside `async_setup_entry`. All
  subentry mutation happens in `async_migrate_entry`.
- `docs/planning/PLANNING_v4.7.5_*` — `MIRROR_KEYS_ZONE_DPM` auto-mirror
  intent. D3a's shrink must NOT regress auto-mirror behavior for the 4
  surviving keys.
- `docs/planning/PLANNING_v4.7.15_*` (sprint runbook) — worktree
  discipline (`.claude/worktrees/...`) the build phase must honor.

### 0.3 Memory bodies pulled

- `feedback_parent_entry_reload_watchdog_hazard` (2026-06-03) — **NEW
  for this plan refresh.** Reloading the URA *parent* config entry
  cascades into full re-setup → event-loop stall → supervisor watchdog
  restarted core (~5 min outage). **Direct implication for this cycle:**
  post-migration the entry topology is "one parent + ~33 subentries,"
  meaning a *reload* of the parent entry will trigger setup/unload of
  EVERY subentry in series. The pre-migration topology already had
  this concentration (parent reload also tore down 33 siblings), but
  D2 doubles down on the parent's blast radius. **Live-validation
  protocol must NOT include a parent-entry reload test.** Use
  deploy-restart (HA restart) for restart resilience instead — same
  technique applied to validate v4.7.18.3. Document this constraint in
  the cycle README's validation runbook.
- `project_v4_7_18_1_sleep_wake_deadlock` — current production tip
  v4.7.19 (one minor cycle past v4.7.18.1). HouseStateMachine does NOT
  persist across restart. Migration runs at HA boot; house-state
  non-persistence does not affect subentry migration.
- `project_single_user_no_backcompat` — **no multi-version back-compat
  shims.** One-shot migration only. State the post-migration data shape
  as authoritative; no dual-read fallback after the migration completes.
- `feedback_pre_deploy_zero_bugs_gate` — applies. Pre-deploy: grep
  conflict markers, py_compile changed files, run cycle tests, run
  isolated suite-baseline-diff.
- `feedback_db_sensitive_3x_targeted_reviews` — applies; this cycle is
  Tier 2-DB (§3).
- `feedback_fix_lows_in_cycle` — applies. Fix the reasonable LOWs (1-30
  LoC) in the same fix-up pass; cap deferral doc at ~6 entries.
- `feedback_versioning_convention` — applies. **No "5.0" prefix.**
  Patch-level cycle.
- `feedback_no_fabrication` + `feedback_no_fabrication_dhcp_incident` —
  applies. §0.6 below explicitly catalogs the HA subentry API surfaces
  the planner could NOT verify from public dev docs. Builder MUST
  cross-check against HA core source before implementing; planner is
  flagging uncertainty rather than guessing.
- `project_v4712_live` (AnomalyType discriminator) — sibling example of
  additive ADD-COLUMN with dual-write; similar shape to D2's subentry
  migration with a `legacy_flat_topology` rollback flag.
- `project_v4_6_15_shipped` (Bug Class #42) — must not regress under
  any new `async_create_task` paths introduced by `async_migrate_entry`.
- `feedback_no_claude_coauthor_trailer` — applies. Build commits must
  NOT include the Claude co-author trailer.

### 0.4 Design docs read

- `docs/Coordinator/*` — no coordinator-specific design doc is
  materially affected. The migration is structural, not behavioral.
  Verified by re-reading CM register sites in `__init__.py` (build-time-
  verify the post-v4.7.19 line numbers): each coordinator is constructed
  from `cm_config` dict reads — those reads are subentry-data-shape-
  agnostic once D2 normalizes the read path.

### 0.5 Code surveyed end-to-end during scoping

- `custom_components/universal_room_automation/__init__.py` (3,000+ LoC;
  structural-debt epicenter):
  - `async_setup_entry` at `:596` (drifted from prior plan's `:610`).
  - `_migrate_sensor_entity_ids` (historical entity-registry migration
    pattern during setup) — build-time-verify line.
  - `_migrate_zones_to_zone_manager` (**closest existing analogue** to
    D2 — flat zone entries collapsed to ZM with device-registry surgery)
    — build-time-verify line.
  - `_ensure_coordinator_manager_entry` (CM bootstrap; will move into
    parent subentry tree) — build-time-verify line.
  - Five `entry_type` dispatch branches in setup: `:610 (INTEGRATION),
    :2416 (ZONE_MANAGER), :2480 (COORDINATOR_MANAGER)`, plus ROOM and
    legacy ZONE.
  - Bug Class #46 tombstone at `__init__.py:2380-2389` (build-time-
    verify) — explicit rule: no `async_update_entry` from setup. D2
    respects this.
  - `async_unload_entry` at `:2881` (drifted from prior plan's `:2807`)
    — five entry_type branches; D2 collapses to one parent + per-
    subentry teardown. **v4.7.18.3 introduced paired-teardown discipline
    via `entry.async_on_unload` hooks across this surface** — D2's
    per-subentry teardown path MUST preserve those guarantees (services,
    panels, tasks all torn down on the right scope).
- `custom_components/universal_room_automation/config_flow.py` (7,685
  LoC, 143 `async_step_*`, no separate options_flow.py):
  - Imports incl. DEPRECATED `CONF_PHONE_TRACKER` at `:96` (comment at
    `:14`) — D3b removes both.
  - `MIRROR_KEYS_ZONE_DPM` at `:361` — D3a shrinks to 4 keys; call site
    `:6158`.
  - `class UniversalRoomAutomationConfigFlow(... VERSION = 1)` at
    `:386-389` (verified 2026-06-04). D2 bumps to `VERSION = 2`, adds
    `minor_version = 1`.
  - `async_step_zone_dynamic_preset` + `_build_dynamic_preset_schema` at
    `:6053-6249` (build-time-verify exact range). Only the first 4
    positional args are consumed. D3a removes the trailing 17 args.
- `custom_components/universal_room_automation/domain_coordinators/dynamic_preset.py:209-234`
  — `_BUCKET_CONF_KEYS` lookup table at `:209`; readers at `:847, :856`.
  D3a removes the table; replace membership check at `:847` with
  `BucketClass` StrEnum lookup if needed.
- `custom_components/universal_room_automation/domain_coordinators/energy_const.py:306-324`
  — 17 constants to delete (build-time-verify exact line range).
- `custom_components/universal_room_automation/const.py:50-54, 321-322`
  — `ENTRY_TYPE_*` table + DEPRECATED `CONF_PHONE_TRACKER` (drifted
  from prior plan's `:314-315`).

### 0.6 HA subentry API — verified vs unverified (no-fabrication discipline)

Per `feedback_no_fabrication`, the planner is explicit about what was
sourceable from public HA developer docs vs. what was NOT and therefore
must be verified against HA core source by `ura-builder` before
implementation. This section exists so the builder doesn't trust the
mechanism block (§2 D2) without crosschecking.

**VERIFIED from `https://developers.home-assistant.io/docs/config_entries_config_flow_handler`:**
- The subentry-flow base class developers subclass is **`ConfigSubentryFlow`** (verbatim from the dev doc).
- The integration declares supported subentry types via a classmethod on the config-flow class:
  ```python
  @classmethod
  @callback
  def async_get_supported_subentry_types(
      cls, config_entry: ConfigEntry
  ) -> dict[str, type[ConfigSubentryFlow]]:
      """Return subentries supported by this integration."""
  ```
  (Signature verbatim from the dev doc.)

**VERIFIED from `https://developers.home-assistant.io/blog/2025/02/16/config-subentries/`:**
- Subentries are "owned by a config entry" and "set up as part of `async_setup_entry`."
- Subentries are created by "config subentry flows" and updated by "config subentry reconfigure flows."
- The blog post is announcement-level — it does NOT name the underlying class for a subentry record, programmatic-add API, or lifecycle hooks.

**NOT VERIFIED from public dev docs (builder MUST cross-check against HA core source at build time, e.g. `homeassistant/config_entries.py` on the matching HA version):**
1. **Exact name of the subentry record class.** Plan body uses `ConfigSubentry` provisionally. Builder verifies the real name (could be `ConfigSubentryData`, a dataclass with a different name, or constructed via a builder method).
2. **Programmatic-add method on `hass.config_entries`.** Plan body uses `hass.config_entries.async_add_subentry(parent_entry, ConfigSubentry(...))` provisionally. The real signature may use a different method name (e.g. `async_add_subentries` plural, or a method on the parent entry itself), and may require a different argument shape.
3. **Subentry-specific lifecycle hooks.** Plan body uses `async_unload_subentry(hass, parent_entry, subentry)` provisionally. The blog post says subentries are "set up as part of `async_setup_entry`" but does not name a separate `async_setup_subentry`/`async_unload_subentry` hook. Builder verifies whether HA-core provides per-subentry hooks or expects the integration to iterate `entry.subentries` inside `async_setup_entry` / `async_unload_entry`.
4. **Subentry data shape — does a subentry carry `data` only, or also `options`?** Plan body merges `{**entry.data, **entry.options}` into the subentry `data` provisionally. If subentries support a separate `options` dict, the migration should preserve the split rather than flatten it.
5. **Whether `async_migrate_entry` is the documented hook for flat→parent+subentries migration.** No public dev-doc mentions this exact pattern. Builder must (a) confirm `async_migrate_entry` is allowed to call `hass.config_entries.async_add_subentry(...)` AND `async_remove(...)` on sibling entries, OR (b) identify the documented alternative (e.g. a one-shot helper invoked from `async_setup`). If neither pattern is endorsed, the design must be reconsidered before build.

**Rule:** if any of items 1-5 turn out different from the plan's
provisional shape, the affected mechanism step in §2 D2 must be edited
BEFORE build proceeds. This is NOT a freedom for the builder to design
silently — it's a forcing function for the builder to *verify and
report back* what the real API is, so the plan can be updated.

---

## 1. Migration safety non-negotiables

These are the rails. Reviewers verify each one explicitly.

1. **Dry-run mode (REQUIRED).** Implement `URA_SUBENTRY_MIGRATION_DRY_RUN`
   env-var gate. When set, `async_migrate_entry` logs the planned
   subentry add + sibling remove for every entry, then returns `False`
   (skips actual migration). Operator runs this before the live
   migration to inspect the plan. Reference: `ROADMAP_v11:608`.
2. **Transactional rollback (REQUIRED).** Migration runs in a try/except
   that, on any mid-batch failure, calls `_rollback_partial_migration`
   to remove any subentries created so far AND restore the sibling
   entries that were already removed (using snapshotted
   `data/options/title/entry_id` captured at function entry). If
   rollback itself fails, raise `ConfigEntryNotReady` so HA leaves the
   integration non-loaded instead of split-brain. Reference:
   `ROADMAP_v11:607`.
3. **No `async_update_entry` from `async_setup_entry` (Bug Class #46).**
   All subentry add/remove operations happen inside `async_migrate_entry`,
   NEVER inside `async_setup_entry`. Reference: `__init__.py:2380-2389`
   (Bug Class #46 tombstone; build-time-verify post-v4.7.19 drift).
4. **Pre-flight JSON snapshot.** Before any mutation, write a JSON
   snapshot of the full pre-migration entry topology to
   `<config>/universal_room_automation/premigration_snapshot.json`.
   Operator (and `@shipwatch`) compare post-migration topology against
   this. Snapshot is the rollback source of truth if the in-memory
   rollback path fails.
5. **No multi-version back-compat.** Per `project_single_user_no_backcompat`:
   after migration runs once and `entry.version == 2`, no path reads
   the old flat-sibling shape. No dual-read fallback. Operator-owned
   rollback procedure is "restore from HA storage backup taken pre-deploy."
6. **Pre-deploy zero-bugs gate.** Per `feedback_pre_deploy_zero_bugs_gate`:
   grep conflict markers, py_compile changed files, run cycle tests,
   run isolated suite-baseline-diff.
7. **Preserve v4.7.18.3 paired-teardown guarantees on the new per-subentry
   path.** Every `entry.async_on_unload` registration that
   v4.7.18.3 added to per-entry-type setup branches must have an
   equivalent on the equivalent per-subentry setup. Otherwise D2 silently
   regresses v4.7.18.3's correctness. Reviewer B charters this check.
8. **Preserve the v4.7.18.3 self-reload carve-out (B-CRIT-1).** The
   options-update self-reload task remains an untracked
   `hass.async_create_task(hass.config_entries.async_reload(...))`. The
   AST canary at `quality/tests/test_setup_unload_symmetry.py` must keep
   passing post-D2. If a subentry-level self-reload is added, the same
   carve-out semantics apply at the subentry scope and must be canary-tested.
9. **No parent-entry reload as a validation step.** Per
   `feedback_parent_entry_reload_watchdog_hazard` (2026-06-03), reloading
   the URA parent config entry can stall the event loop long enough for
   the supervisor watchdog to restart core. Validation runbook uses HA
   restart instead of parent reload to exercise restart resilience.
   Subentry-level reload (a single subentry reload via UI) is fine —
   that's the whole point of the migration.

---

## 2. Deliverables

### D2: Config Subentries Migration

**Scope:** one-shot migration of this install's ~34 flat sibling entries
to one parent integration entry with ~33 HA config subentries (HA 2025.2
API; see §0.6 for the API verification commitments).
Reference: https://developers.home-assistant.io/blog/2025/02/16/config-subentries/.

**Pre-migration topology:**
- 1× `ENTRY_TYPE_INTEGRATION` (parent)
- N× `ENTRY_TYPE_ROOM` (~30 today; build-time-verify exact count on the
  operator's instance via `len([e for e in hass.config_entries.async_entries(DOMAIN) if e.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ROOM])`).
- 1× `ENTRY_TYPE_ZONE_MANAGER`
- 1× `ENTRY_TYPE_COORDINATOR_MANAGER`
- 0× `ENTRY_TYPE_ZONE` (legacy; declared deprecated at `__init__.py`
  build-time-verify lines and migrated to ZM in v3.6.0).

**Post-migration topology:**
- 1× parent integration entry (unchanged `entry_id`)
- ~33 subentries hanging off the parent (one `subentry_type` per source
  ENTRY_TYPE, preserving `room_name` / `zone_name` / etc. on subentry
  `data` dict — see §0.6 item 4 for the data-vs-options split question).

**Mechanism (PROVISIONAL — depends on §0.6 verifications):**

1. Bump `class UniversalRoomAutomationConfigFlow(... VERSION = 2)` at
   `config_flow.py:386-389` (verified `VERSION = 1` 2026-06-04). Add
   `minor_version = 1`.
2. Implement `async_migrate_entry(hass, config_entry)` at module level
   in `__init__.py` (NEW function — verified by grep, none exists).
   Inspect entry version; on `version == 1`, execute one-shot conversion.
3. Migration runs ONLY on the parent integration entry. For each sibling
   room/ZM/CM entry:
   - Read `entry.data` + `entry.options`.
   - Construct the HA subentry record using the verified class name from
     §0.6 item 1 (plan body uses `ConfigSubentry` provisionally).
   - Call the verified programmatic-add API from §0.6 item 2
     (plan body uses `hass.config_entries.async_add_subentry(parent_entry, ConfigSubentry(subentry_type=<mapped type>, data=<merged data+options>, title=<entry.title>))` provisionally).
   - Call `await hass.config_entries.async_remove(sibling_entry.entry_id)`
     for the migrated sibling.
4. Register one `ConfigSubentryFlow` subclass per `subentry_type` for
   adding new rooms/zones via standard HA UI after migration. Wire it
   via `async_get_supported_subentry_types` classmethod on the existing
   `UniversalRoomAutomationConfigFlow` (signature VERIFIED in §0.6).
5. Refactor `async_setup_entry` (`__init__.py:596`) to dispatch by
   subentry. The five `entry_type` branches collapse to one parent
   setup + a per-subentry dispatch loop (iteration source verified per
   §0.6 item 3).
6. Refactor `async_unload_entry` (`__init__.py:2881`) symmetrically.
   Per-subentry teardown follows the verified HA contract (§0.6 item 3).
   This REPLACES the URA-coded coordinator-manager listener chain that
   was the surface of v4.2.24's silent-save bug (`ROADMAP_v11:589-591`).
   **v4.7.18.3 paired-teardown discipline carries forward** — every
   `entry.async_on_unload` registration in the per-entry-type setup
   branches must have an equivalent in the per-subentry setup, scoped
   to that subentry's resources.

**Entry-type → subentry-type mapping (NEW constants in `const.py`):**
- `SUBENTRY_TYPE_ROOM = "room"` (replaces `ENTRY_TYPE_ROOM`)
- `SUBENTRY_TYPE_ZONE_MANAGER = "zone_manager"` (replaces `ENTRY_TYPE_ZONE_MANAGER`)
- `SUBENTRY_TYPE_COORDINATOR_MANAGER = "coordinator_manager"` (replaces `ENTRY_TYPE_COORDINATOR_MANAGER`)

Legacy `ENTRY_TYPE_*` constants are KEPT as aliases for one release
window (only for the migration code path). Deleted in the next patch
once migration is provably complete on the operator's install.

**Acceptance criteria:**

- **Verify:** Pre-migration:
  `len(hass.config_entries.async_entries(DOMAIN))` returns 33-34.
  Post-migration: returns **1** (parent), with
  `len(parent.subentries) == 32-33`.
- **Verify:** Pre-migration JSON snapshot file exists at
  `<config>/universal_room_automation/premigration_snapshot.json` with
  all entries' `data + options + title`.
- **Verify (Dry-run):** `URA_SUBENTRY_MIGRATION_DRY_RUN=1` + HA restart
  logs planned migration without mutating the entry registry. Re-run
  without env var executes the migration.
- **Verify:** Every subentry's `data` dict equals the pre-migration
  sibling's `{**data, **options}` (no key loss). If §0.6 item 4 reveals
  subentries support a separate `options` dict, this acceptance criterion
  splits into two verifications.
- **Verify:** Every subentry's RestoreEntity state survives the
  migration — entity `last_state` / `attributes` are unchanged for at
  least 3 sampled per-room entities (e.g. `sensor.master_bedroom_occupancy_score`,
  `binary_sensor.master_bedroom_anyone_here`, `switch.master_bedroom_dpm_enabled`).
  Verified by snapshotting `entity_registry` + `restore_state.last_states`
  before and after.
- **Verify:** Per-subentry **options round-trip**. The options flow
  surface (currently invoked from `OptionsFlowHandler` chained off
  `UniversalRoomAutomationConfigFlow`) opens the same per-room option
  set against a subentry, saves successfully, and the saved options
  appear on `subentry.data` (or `subentry.options` if §0.6 item 4 yields
  a separate options surface). Cycle this for one ROOM, the
  ZONE_MANAGER, and the COORDINATOR_MANAGER subentry.
- **Verify:** **Unload/reload symmetry at subentry scope.** After a
  single-subentry reload (e.g. via the UI), only that subentry's
  resources are torn down and re-set-up. The parent integration's
  shared resources (DB, coordinator_manager, panels, services,
  static paths) stay alive. `setup_telemetry` counters increment for
  the subentry, not the parent. **Parent reload is NOT exercised
  here** (per §1 rail #9).
- **Sensor:** `sensor.ura_subentry_migration_state` (NEW diagnostic
  sensor on the integration device) shows one of `not_started`,
  `dry_run_complete`, `migrated`, `rolled_back`, `failed`. Attributes:
  `pre_count`, `post_count`, `migration_timestamp`, `snapshot_path`.
  REUSE the existing diagnostic-sensor pattern (e.g. the v4.7.18.x
  drift-guard pattern) — builder verifies the pattern's prior art
  before adding NEW base classes.
- **Test:** `quality/tests/test_subentry_migration.py`:
  - `test_migration_creates_subentry_per_sibling`
  - `test_migration_preserves_data_and_options_per_entry`
  - `test_migration_is_idempotent_on_version_2_entry`
  - `test_dry_run_does_not_mutate_registry`
  - `test_rollback_on_partial_failure_restores_pre_state`
  - `test_snapshot_file_written_before_any_mutation`
  - `test_legacy_entry_type_zone_skipped_silently`
  - `test_async_setup_entry_dispatches_per_subentry_type`
  - `test_async_unload_subentry_releases_only_that_subentrys_resources`
  - `test_subentry_options_flow_roundtrip` (NEW — for the per-subentry
    options round-trip acceptance criterion)
  - `test_subentry_restore_entity_state_preserved` (NEW — for the
    RestoreEntity acceptance criterion)
- **Test (AST regression):** `test_no_async_update_entry_in_async_migrate_entry`
  — assert `async_migrate_entry` body contains zero `async_update_entry`
  calls.
- **Test (AST regression):** `test_v4_7_18_3_self_reload_carve_out_preserved`
  — re-assert the v4.7.18.3 canaries at
  `quality/tests/test_setup_unload_symmetry.py` still pass post-D2.
- **Live:** After HA restart with migration applied, all per-room
  entities present and functional (count via
  `entity_registry.async_get(hass).entities` filtered by `platform == DOMAIN`).
  Zero `ConfigEntryNotReady` exceptions in post-restart log.
- **Live:** Adding a new room via standard HA UI (Settings → Devices →
  URA → Add Subentry → Room) completes without touching `__init__.py`
  registry-surgery code.
- **Live:** Single-subentry reload via UI (Settings → Devices → URA →
  [pick a room] → Reload) succeeds without disturbing other subentries
  and without triggering a parent reload. Setup-telemetry sensor reflects
  the per-subentry cycle.
- **Live (`@shipwatch`):** Acceptance hypothesis **"post-migration
  entity count == pre-migration entity count ± 2"** passes within the
  first census cycle.

### D3: Constant cleanup + runtime_data migration

Three sub-deliverables small enough to ride D2 in the same release.
Independent; each can be reverted without affecting the others.

#### D3a: 16 bucket CONFs + `customize_buckets` removal

**Surfaces touched:**
- `domain_coordinators/energy_const.py:306-324` (build-time-verify) —
  DELETE 17 constants:
  - `CONF_ZONE_DYNAMIC_PRESET_CUSTOMIZE_BUCKETS`
  - 8× `CONF_ZONE_DYNAMIC_PRESET_<BUCKET>_HOME_<LOW|HIGH>`
  - 8× `CONF_ZONE_DYNAMIC_PRESET_<BUCKET>_SLEEP_<LOW|HIGH>`
- `domain_coordinators/dynamic_preset.py:209-234` — DELETE
  `_BUCKET_CONF_KEYS` lookup AND its readers at `:847, :856`. Replace
  the `:847` membership check with a `BucketClass` StrEnum membership
  test if needed.
- `config_flow.py:6053-6249` (build-time-verify exact range) — DELETE
  17 imports from `energy_const` for `async_step_zone_dynamic_preset`
  AND the trailing 17 positional args from the
  `_build_dynamic_preset_schema` call. Update `_build_dynamic_preset_schema`
  signature to 4 explicit positional args (`enabled`, `offset`,
  `reset_guest`, `sleep_enabled`).
- `config_flow.py:361` — Shrink `MIRROR_KEYS_ZONE_DPM` from 21 keys to
  4 (`enabled`, `offset`, `reset_offset_guest`, `sleep_enabled`).
- `translations/en.json` + `strings.json` — DELETE 17 string keys for
  bucket labels.

**Data preservation:** The 16 bucket values may still exist in subentry
`data` post-D2. D3a does NOT delete them from subentry data — they
remain as dead keys until a future explicit subentry data-shape
migration. Matches the v4.7.18 "data-preserved, UI-stripped" precedent.

**Acceptance criteria:**
- **Verify:** `grep -r "CONF_ZONE_DYNAMIC_PRESET_CUSTOMIZE_BUCKETS\|CONF_ZONE_DYNAMIC_PRESET_(COOL\|MILD\|HOT\|EXTREME)_(HOME\|SLEEP)_(LOW\|HIGH)" custom_components/`
  returns 0 matches.
- **Verify:** `MIRROR_KEYS_ZONE_DPM` is a frozenset of exactly 4 keys.
- **Test:** `test_d3a_bucket_constants_removed` — AST regression. Imports
  the 17 constants from `energy_const` and asserts `ImportError` for each.
- **Test:** `test_d3a_subentry_data_with_legacy_bucket_keys_still_loads`
  — subentry whose `data` dict contains the 16 legacy bucket keys still
  loads cleanly.
- **Live:** Surface 2 (zone DPM config) still renders the 4-field form.
  Saving still mirrors to siblings via `_auto_mirror_to_siblings`
  (`config_flow.py:6157-6160` build-time-verify) — and post-D2, "mirror
  to siblings" reads as "mirror to peer subentries."

#### D3b: `CONF_PHONE_TRACKER` removal

**Surfaces touched:**
- `const.py:321-322` — DELETE constant + deprecation comment (drifted
  from prior plan's `:314-315`).
- `config_flow.py:96` — DELETE import line.
- `config_flow.py:14` — DELETE the deprecation-pointer comment.

**Acceptance criteria:**
- **Verify:** `grep -r "CONF_PHONE_TRACKER" custom_components/` returns
  0 matches.
- **Test:** Existing config-flow tests pass unchanged.

#### D3c: `runtime_data` migration

**Scope:** absorb tech-debt item #4. Migrate `hass.data[DOMAIN]`
writes/reads to `entry.runtime_data` typed access. **Biggest LoC delta
in this cycle** — grep showed 159 occurrences across 17 files (refreshed
2026-06-04; vs. ROADMAP_v11's "~50 sites" estimate; field-verify in
build).

**Mechanism:**
1. Define a typed dataclass `URARuntimeData` in `__init__.py` capturing
   all keys currently stored in `hass.data[DOMAIN]`: `database`,
   `coordinator_manager`, `person_coordinator`, `transition_detector`,
   `bayesian_predictor`, `census`, `camera_manager`,
   `perimeter_alert_manager`, `transit_validator`, `egress_tracker`,
   `weather_manager`, `activity_logger`, `setup_telemetry`, plus
   `unsub_*` cleanup handles. Builder verifies the complete key list
   against `__init__.py:90` write sites before pinning the dataclass shape.
2. On parent setup: `entry.runtime_data = URARuntimeData(...)`.
3. Migrate read sites from `hass.data[DOMAIN].get(key)` to
   `entry.runtime_data.<attr>`.
4. **Critically:** cross-platform shared resources (database,
   coordinator_manager) are owned by the **parent integration entry's**
   `runtime_data`. Subentries access via lookup helper
   `_parent_runtime(hass, subentry) -> URARuntimeData`. Preserves the
   single-DB-instance invariant (build-time-verify the post-v4.7.19
   line for this invariant; prior plan cited `__init__.py:2649-2660`).

**Descoped from D3c (defer to next patch):**
- The `hass.data[DOMAIN]` references inside `domain_coordinators/`,
  `aggregation.py`, `coordinator.py`, and other coordinator-internal
  files (per the 2026-06-04 grep: 27 in `aggregation.py`, 2 in
  `coordinator.py`, scattered single-digits across `domain_coordinators/`).
  Migrating these requires touching coordinator-internal APIs. Initial
  D3c migration covers `__init__.py` + the platform files
  (`sensor/binary_sensor/switch/button/select/number`) — the bulk of
  the 159 sites.

**Acceptance criteria:**
- **Verify:** `grep -rn "hass\.data\[DOMAIN\]" custom_components/universal_room_automation/__init__.py | wc -l`
  drops from 90 to ≤ 5 (only DB/CM bootstrap reads that must precede
  `entry.runtime_data = ...` assignment).
- **Verify:** `entry.runtime_data` is set on parent entry after
  `async_setup_entry` returns.
- **Test:** `test_d3c_runtime_data_typed_access` — assert
  `entry.runtime_data` is `URARuntimeData` after setup; assert
  `entry.runtime_data.database is not None`.
- **Test:** `test_d3c_no_hass_data_in_platform_files` — AST regression
  over `sensor.py`, `binary_sensor.py`, `switch.py`, `button.py`,
  `select.py`, `number.py`.
- **Live:** No `KeyError` / `AttributeError` in post-restart log
  referencing `hass.data['universal_room_automation']`.

#### D3d: NOT in scope — `config_flow.py` file split

7,685 LoC monolith, 143 `async_step_*` methods, no separate
`options_flow.py`. Splitting is tempting but is a separate architectural
refactor with its own review surface. **Descoped** to keep this cycle's
review-surface scope-bounded.

---

## 3. Tier classification: Tier 2-DB (justified)

This cycle meets Tier 2-DB triggers from `CLAUDE.md`:

- ☑ **Cycle migrates ≥3 callers to a new shape.** D2 migrates 33-34
  config entries → ~33 subentries; every `entry.data`/`entry.options`
  caller is affected.
- ☑ **Cycle changes payload shape of a persisted record.** Config-entry
  storage shape changes (flat siblings → parent.subentries). HA persists
  this via `core.config_entries` storage.
- ☑ **Cycle is followed within 1-2 versions by a planned schema migration.**
  D3a (bucket-key removal from subentry data) is the natural follow-up.
  D3c's coordinator-internal sweep is the patch after.
- ☑ **Trust-hierarchy ripple change.** D2 ripples through every
  coordinator's setup path (presence ↔ HVAC ↔ compliance ↔ safety ↔
  security ↔ MF ↔ energy). Operator-elevated Tier 2-DB criterion
  applies independently.

**Three parallel reviews, framing-disjoint:**

- **Review A — Data integrity + entry-registry preservation.** Every
  pre-migration entry's `data + options` is preserved byte-for-byte in
  the corresponding subentry. No key loss. Pre-migration snapshot file
  is written before any mutation. Existing readers of legacy
  `ENTRY_TYPE_*` flat shape are removed or gated. Existing entity
  `unique_id`s unchanged. Existing `device_registry` identifiers
  unchanged. RestoreEntity state survives. Per-subentry options
  round-trip preserves keys byte-for-byte.
- **Review B — Migration correctness + lifecycle / restart resilience.**
  `async_migrate_entry` is the only mutator (no `async_update_entry`
  from `async_setup_entry`). Rollback path exercised in tests. Dry-run
  honored. Bug Class #46 invariant holds. Bug Class #42 (lambda+async_create_task)
  not regressed. **v4.7.18.3 paired-teardown guarantees preserved on
  every NEW per-subentry teardown path.** v4.7.18.3 self-reload carve-out
  preserved (AST canaries still pass). Subentry teardown contract
  releases ONLY that subentry's listeners — never the parent's shared
  resources. **Parent-entry reload is NOT exercised** (per §1 rail #9).
- **Review C — New surfaces + test fixture authority.** New
  `sensor.ura_subentry_migration_state` diagnostic round-trips through
  `RestoreEntity`. New `URARuntimeData` dataclass shape is verified by
  tests, not hand-copied between code and test. AST regression tests
  for bucket-CONF removal extract target import list from production
  source (`energy_const.py`), not hand-copied tuple. New
  `ConfigSubentryFlow` subclasses' string keys come from the same
  translation files the legacy flat-flow used (no orphan translation
  keys).

Run the three reviews in PARALLEL — different framings can't share
blind spots.

**Pre-deploy snapshot of affected entity counts** by `(platform,
device_class)` over all URA entities. Operator runs snapshot ~1h before
deploy. Post-deploy comparison: counts within ±2 entities (allowing the
new D2 diagnostic sensor + natural noise) per `(platform, device_class)`
bucket.

**Live Validation (Review D):** Post-restart, after migration has run:
- `len(hass.config_entries.async_entries(DOMAIN)) == 1` (just parent)
- `len(parent.subentries) == pre_migration_count - 1`
- All per-room entities present
- Per-subentry reload works (single subentry via UI; NOT parent)
- Per-subentry options round-trip works
- `@shipwatch` hypothesis "post-migration entity count == pre-migration
  entity count ± 2" passes within first census cycle.

---

## 4. Sequencing (gate cleared)

```
            ┌─────────────────────────────────────────────┐
            │  Today (2026-06-04): v4.7.19 LIVE           │
            │  Prereq v4.7.18.3 setup/unload symmetry     │
            │  shipped + live-validated ≥1 reload cycle.  │
            │  GATE IS CLEAR.                             │
            └──────────────────────┬──────────────────────┘
                                   │
                                   ▼
            ┌─────────────────────────────────────────────┐
            │  THIS PLAN — D2 + D3a/b/c                   │
            │  Tier 2-DB (three reviews, framing-disjoint)│
            │  §0.6 API-verification step BEFORE build    │
            │  Dry-run pass → live migration → snapshot   │
            │  comparison → @shipwatch acceptance         │
            └──────────────────────┬──────────────────────┘
                                   │
                                   ▼
            ┌─────────────────────────────────────────────┐
            │  Next patch — D3c coordinator-internal sweep│
            │  (remaining hass.data[DOMAIN] sites in      │
            │   coordinators / aggregation)               │
            └─────────────────────────────────────────────┘
```

D2 + D3a + D3b + D3c ship together as one deploy. D3c coordinator-
internal sweep is a small follow-up patch.

---

## 5. Plan-completion tracking

Per `CLAUDE.md` §"Plan Completion Tracking — MANDATORY":

1. **D3c coordinator-internal `hass.data[DOMAIN]` sweep** — deferred to
   next patch. Reason: scope-bound this cycle's review surface. The
   coordinator-internal sites require touching coordinator-internal APIs
   and would expand Review C's surface beyond what three parallel
   reviewers can reliably cover.
2. **`config_flow.py` file split / separate `options_flow.py`** (D3d)
   — deferred. Reason: 7,685 LoC monolith refactor has its own review
   surface. Splitting on top of D2 multiplies blind-spot risk.
3. **Bucket-key removal from subentry `data` dicts** — deferred to
   future explicit subentry data-shape migration. Reason: matches
   v4.7.18 "data-preserved, UI-stripped" precedent. D3a removes constants
   but leaves stale data keys.
4. **Tech-debt #2 (tracked background tasks)** — fully addressed in
   v4.7.18.3 setup/unload symmetry hotfix (LIVE). Not this cycle.
5. **Tech-debt #3 (EntityDescription rollout)** — NOT in this cycle.
   Independent ROI track per ROADMAP_v11:680-687. Force-functioned by
   next new-coordinator cycle.
6. **Legacy `ENTRY_TYPE_*` constant deletion** — kept as aliases this
   cycle for one-release-window after migration. Deleted in next patch
   once operator's install is provably migrated.

Cap reached at 6 entries per `feedback_fix_lows_in_cycle`. Any LOW
issues surfaced during reviews that fit the 1-30 LoC bar are fixed in
this cycle's fix-up pass, NOT added to this list.

---

## 6. Risk register

| ID | Risk | Probability | Impact | Mitigation |
|---|---|---|---|---|
| R1 | Subentry API in HA 2025.2 has undocumented edge cases on parent reload | Medium | High | Dry-run mode + snapshot file + rollback path. Reviewer B chartered to walk every lifecycle path. **§1 rail #9 forbids parent-reload as a validation step** per `feedback_parent_entry_reload_watchdog_hazard`. |
| R2 | Migration succeeds but a coordinator's `cm_config` read shape changes silently | Medium | High | Reviewer A chartered to verify byte-for-byte data preservation. D3c does NOT change coordinator-internal reads this cycle; that sweep waits for the next patch. |
| R3 | Provisional HA API names in §2 D2 mechanism differ from real HA core API | Medium | High | §0.6 enumerates the unverified surfaces. Builder MUST verify against HA core source and report back BEFORE writing mechanism code. If real API differs, plan §2 D2 is edited before build proceeds. |
| R4 | Operator runs migration without taking pre-deploy HA storage backup | Low | Critical | README MUST include a top-of-doc "BEFORE DEPLOY: take HA storage backup" callout. `scripts/deploy.sh` should print this reminder for this cycle. |
| R5 | `entry.runtime_data` typed access surfaces None-attribute errors at coordinator startup | Medium | Medium | D3c initializes `URARuntimeData` with all attrs set to None; populated incrementally. Coordinators reading pre-init must handle None (same contract as today's `hass.data[DOMAIN].get(key)`). |
| R6 | Snapshot file collision with existing `data/` directory | Low | Low | Use `<config>/universal_room_automation/premigration_snapshot.json` (managed URA dir; `data/` is gitignored). |
| R7 | v4.7.18.3 paired-teardown guarantees silently regress under the new per-subentry teardown path | Medium | High | §1 rail #7 + Reviewer B charter. AST canary at `quality/tests/test_setup_unload_symmetry.py` must keep passing. New per-subentry teardown re-asserts each `async_on_unload` registration's symmetry against its setup write. |
| R8 | v4.7.18.3 untracked self-reload carve-out silently broken by D2's refactor | Low | Critical | §1 rail #8. AST canary re-asserted. If a subentry-level self-reload is introduced, the same carve-out semantics apply at the subentry scope. |

---

## 7. README requirements

`docs/readmes/README_v<patch>.md` for this cycle must include:

1. **Top-of-doc "BEFORE DEPLOY" callout** — operator MUST take HA
   storage backup before deploy.
2. **Migration runbook** — `URA_SUBENTRY_MIGRATION_DRY_RUN=1` dry-run
   procedure.
3. **Pre-deploy snapshot procedure** — operator runs entity-count query
   before deploy.
4. **Post-deploy validation** — entity-count comparison + D2 acceptance-
   criteria entity IDs. **Validation explicitly uses HA restart, NOT
   parent-entry reload, per `feedback_parent_entry_reload_watchdog_hazard`.**
   Per-subentry reload IS exercised (the whole point of the migration).
5. **Rollback procedure** — if migration sensor shows `failed` or
   `rolled_back`, restore from HA storage backup; do NOT attempt manual
   entry-registry surgery.
6. **Known limitations** — coordinator-internal `hass.data[DOMAIN]`
   sites still on legacy shape (deferred to next patch).
7. **Cross-cycle references** — v4.7.18.3 setup/unload symmetry
   (prereq, LIVE), v4.7.19 (current production tip),
   `PLANNING_v4.7.18_dpm_drift_guard_and_cleanup.md:516` (D3a deferral
   source), `ROADMAP_v11.md:570-698`,
   https://developers.home-assistant.io/blog/2025/02/16/config-subentries/,
   https://developers.home-assistant.io/docs/config_entries_config_flow_handler
   (verified `ConfigSubentryFlow` + `async_get_supported_subentry_types`
   surfaces).

---

## 8. Recall

- "Resume config subentries plan"
- "Subentries migration plan"
- "Plan bucket-CONF removal"
- "Plan runtime_data migration"
- "Subentries gate cleared"
