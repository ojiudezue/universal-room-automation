# PLANNING — Setup/Unload Symmetry (Architectural-Debt Hotfix)

**Status:** Planning. Nothing here has shipped.
**Versioning:** Unversioned until it ships — picks up the next available
patch number at deploy time. This is NOT a minor or major bump: it's a
plumbing hotfix that addresses long-accumulated architectural debt.
**Current production tip (at plan filing):** v4.7.18.1 (sleep→waking
deadlock hotfix, LIVE 2026-06-03).
**Author phase:** ura-planner.
**Cycle classification:** **Tier 2** (two framing-disjoint reviews — see §3).
**Estimated effort:** ~6-10h (single deliverable D1; pure plumbing; no new
constants, sensors, or behavioral changes).
**Relationship to v5.0 subentries:** This plan is the **BLOCKING PREREQ**
for `PLANNING_config_subentries_migration.md`. The subentries migration is
gated on this hotfix shipping AND live-validating cleanly.

---

## 0. Institutional context verified

This section is the proof-of-work mandated by `CLAUDE.md`
§"Institutional Context First". It re-verifies the file:line citations
from the predecessor bundled doc
(`PLANNING_config_subentries_and_arch_debt.md`, now superseded) against
the current `develop` tip, since several originally-cited lines have
drifted.

### 0.1 Greps run (and what they returned)

| Question | Grep | Result | Verdict |
|---|---|---|---|
| Where are services registered? | `_async_register_.*_services\|async_register_(static_paths\|panel)` over `__init__.py` | 4 service registrations at `__init__.py:2267-2276` (`presence`, `safety`, `security`, `notification`); 2 panel/static-path registration blocks at `__init__.py:2292-2321` (panel `:2296, :2321`; static paths `:2292, :2317`). The bundled doc cited `:1589, :1615, :1640` — those lines have drifted. **Build-time-verify required.** | REUSED registration sites; D1 attaches `entry.async_on_unload` paired teardown to each. |
| Untracked `hass.async_create_task` sites | `hass\.async_create_task\(` over `coordinator.py` and `__init__.py` | `coordinator.py`: 10 sites at `:485, :514, :546, :577, :910, :1003, :1015, :1877, :1891, :2253`. `__init__.py`: 1 site at `:3359`. The bundled doc cited `coordinator.py:812, :417` + `__init__.py:2390` — **stale**. Real count is materially larger (~11 sites). | Each site requires audit. Some may be intentional fire-and-forget (e.g. `_fire_*` dispatcher coalescers); others (refresh, reload) must convert to `entry.async_create_background_task` or `async_request_refresh()` per ROADMAP_v11:671-678. |
| Tracked background-task pattern (REUSED) | `entry\.async_create_background_task` over `custom_components/` | Existing usage in cover runners (v4.2.22) — REUSED pattern. | D1 extends this pattern; no new pattern introduced. |
| Existing `entry.async_on_unload` usage | `entry\.async_on_unload` over `__init__.py` | 2+ existing sites incl. `:2399` (Zone Manager update-listener), `:2627` (Coordinator Manager update-listener). | REUSED pattern. D1 attaches teardown lambdas to this hook for every new resource. |
| `async_unload_entry` shape | grep target | One handler at `__init__.py:2807` with five `entry_type` branches. | REUSED. D1 audits each branch for `pop(..., None)` symmetry against the keys written by `async_setup_entry`. |
| `hass.data[DOMAIN]` pop symmetry | `hass\.data\[DOMAIN\]\.pop\b` over `__init__.py` | Build-time-verify — need exhaustive list of keys WRITTEN during setup (≥12: `transition_detector`, `bayesian_predictor`, `weather_manager`, `perimeter_alert_manager`, `transit_validator`, `egress_tracker`, `coordinator_manager`, `census`, `camera_manager`, `activity_logger`, `database`, `_db_init_lock`, `zones`, `zone_manager_entry`, plus `unsub_*` handles) vs keys popped during unload. | The audit IS D1. Defensive `pop(key, None)` matches the v4.6.10 review-fix B2 pattern at `__init__.py:2884` (build-time-verify line). |

### 0.2 Prior planning docs consulted

- `docs/ROADMAP_v11.md:570-698` — full read. Source of the architectural-debt #0-#5 list and the WHY each item exists (external code-review 2026-05-04 against HA quality-scale rules at https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/). Setup/unload symmetry is **tech-debt item #1** in the locally-renumbered list (= **external review item #3**). This plan addresses that item in full.
- `docs/planning/PLANNING_config_subentries_and_arch_debt.md` — predecessor bundled doc, now superseded by this plan plus the v5.0 plan. §2 D1 (lines 107-129) is the immediate ancestor of this doc. §1 (the prereq gate explanation) and §4 (the sequencing diagram) explain WHY D1 must ship standalone before v5.0.
- `docs/planning/PLANNING_v4.7.4.3_*` — skim. Origin of Bug Class #46 (no `async_update_entry` from `async_setup_entry`). D1 does NOT touch this rule (no entry mutation), but D1's reviewers must confirm no fix introduces a v4.7.4.3-shaped regression.
- `docs/planning/PLANNING_v4.6.10_*` — skim for the review-fix B2 pattern (`pop(key, None)` + `setup_telemetry` monotonic counter exposure). D1 generalizes B2's defensive-pop pattern across all `async_unload_entry` branches and reuses `setup_telemetry` for live-validation counters.

### 0.3 Memory bodies pulled

- `project_v4_7_18_1_sleep_wake_deadlock` — confirms current production tip is v4.7.18.1. House state machine does NOT persist across restart. D1 must NOT silently shift any in-memory state to a persisted surface; pure plumbing only.
- `feedback_pre_deploy_zero_bugs_gate` — applies. Before deploying D1: grep conflict markers, py_compile changed files, run cycle tests, run isolated suite-baseline-diff.
- `feedback_fix_lows_in_cycle` — applies. Fix the reasonable LOWs (1-30 LoC) in the same fix-up pass; cap deferral doc at ~6 entries.
- `feedback_no_fabrication_dhcp_incident` + `feedback_no_fabrication` — applies. Several originally-cited file:lines in the bundled doc are stale. This doc replaces them with verified or `build-time-verify` markers.
- `project_v4_6_15_shipped` — sibling thread-safety hotfix (Bug Class #42: lambda+async_create_task in scheduler callbacks). D1's untracked-task sweep must NOT regress Bug Class #42 fixes; reviewers verify any task conversions preserve `add_job` patterns where they were intentionally introduced.

### 0.4 Design docs read

- `docs/Coordinator/*` — no coordinator-specific design doc materially changes. D1 is structural; no `intent → action` contract changes. Verified by sampling Coordinator Manager + Presence Coordinator design docs.

### 0.5 Code surveyed end-to-end during scoping

- `custom_components/universal_room_automation/__init__.py`:
  - Service registration sites (`:2267-2276`)
  - Panel + static-path registration (`:2292-2321`)
  - Zone Manager setup branch (`:2392-2401`) — REUSED `entry.async_on_unload` example at `:2399`
  - Coordinator Manager setup branch (`:2406-2629`) — REUSED `entry.async_on_unload` at `:2627`
  - `async_unload_entry` (`:2807-2970`) — five `entry_type` branches; each must have `pop(key, None)` symmetry against its setup writes
  - Untracked task at `:3359`
- `custom_components/universal_room_automation/coordinator.py`:
  - 10 untracked `hass.async_create_task` sites (`:485, :514, :546, :577, :910, :1003, :1015, :1877, :1891, :2253`). Audit each: some are intentional dispatcher coalescers; others are refresh/reload sites that must convert to `entry.async_create_background_task` or `async_request_refresh()`.

---

## 1. Architectural-debt HISTORY (why this exists)

This section is mandatory per operator request — without the history, future reviewers see a hotfix and ask "why now?". Three threads converged on this debt.

### 1.1 External code review, 2026-05-04

A structured critique against the HA quality-scale rules
(https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/)
surfaced five architectural items, captured at `ROADMAP_v11.md:619-698`.
Setup/unload symmetry was **review item #3** in the external numbering
(= **tech-debt item #1** in the locally-renumbered list). The reviewer's
finding (paraphrased from `ROADMAP_v11:661-668`):

> Services registered in `async_setup` are never unregistered. Panels and
> static paths registered during setup are never torn down. Integration
> unload tears down shared resources (database, coordinators) while
> room/manager entries may still depend on them. Use
> `entry.async_on_unload` for every listener/timer created by that
> entry; reference-count or parent-own shared resources.

### 1.2 The v4.2.24 silent-save class

`ROADMAP_v11:591` and `:665-666` connect setup/unload asymmetry directly
to a shipped production bug. v4.2.24 (silent save during entry reload)
was a symptom of the coordinator-manager listener chain being a
URA-coded surrogate for what should be HA's
`async_unload_subentry` contract. The integration tore down a shared
resource (the listener chain) while sibling entries still depended on
it — the same shape of bug that asymmetric setup/unload will keep
producing until the discipline is enforced everywhere.

### 1.3 Untracked-task orphans (ROADMAP_v11:671-678)

Review item #4 (tech-debt item #2) is a sibling concern: multiple sites
call `hass.async_create_task(...)` without storing the handle. The
v4.2.22 cover-runner work introduced the `entry.async_create_background_task` pattern, but adoption stayed partial. Today's grep shows ~11 untracked sites in `coordinator.py` + `__init__.py`. Each one is a potential leak across reloads — the task is owned by the event loop, not by the entry, so unload returns while the task is still pending. D1 absorbs the audit of these sites because the surface overlaps with the symmetry work.

### 1.4 Why D1 is the v5.0 prereq

The v5.0 subentries migration inverts entry ownership: one parent + N subentries replaces 34 siblings. If shared resources (database, coordinator manager, panels, services, static paths) are owned by the wrong entry — or if their teardown is missing — then unloading the parent tears them down while subentries still depend on them. The v4.2.24 silent-save bug class IS exactly this surface. Shipping subentries on top of an asymmetric setup/unload path multiplies blast radius. Hence: D1 ships standalone, lives on `develop` through at least one live-validation window, THEN v5.0 builds on top of it.

---

## 2. Deliverable

### D1: Setup/Unload Symmetry

**Scope:** address tech-debt item #1. Every listener/timer/registration created by an entry must be released by that entry's unload. Shared resources must be reference-counted or parent-owned. Untracked `hass.async_create_task` sites in `coordinator.py` + `__init__.py` are audited and converted where appropriate.

**Surfaces touched:**

1. **Service registration teardown** — `__init__.py:2267-2276` (build-time-verify line numbers; `_async_register_presence_services`, `_async_register_safety_services`, `_async_register_security_services`, `_async_register_notification_services` calls). Wrap each via `entry.async_on_unload(lambda: hass.services.async_remove(DOMAIN, "<service_name>"))`. REUSED pattern: `entry.async_on_unload` at `__init__.py:2399, :2627`.
2. **Panel + static-path teardown** — `__init__.py:2292-2321` (`hass.http.async_register_static_paths` at `:2292, :2317`; `panel_custom.async_register_panel` at `:2296, :2321`). Wrap each via the same `entry.async_on_unload` hook. Use HA's `frontend.async_remove_panel` for panel teardown and the static-path-handle release API (build-time-verify exact API name against HA's developer docs before code; do NOT fabricate).
3. **`async_unload_entry` pop-symmetry audit** — `__init__.py:2807-2970`. For each of the five `entry_type` branches:
   - Enumerate the `hass.data[DOMAIN]` keys WRITTEN by the corresponding `async_setup_entry` branch.
   - Confirm a paired `pop(key, None)` in the unload branch.
   - Convert any ad-hoc `del hass.data[DOMAIN][key]` to defensive `pop(key, None)` per the v4.6.10 review-fix B2 pattern (build-time-verify line at `:2884`).
   - Known keys requiring symmetry (build-time-verify exhaustive list): `transition_detector`, `bayesian_predictor`, `weather_manager`, `perimeter_alert_manager`, `transit_validator`, `egress_tracker`, `coordinator_manager`, `census`, `camera_manager`, `activity_logger`, `database`, `_db_init_lock`, `zones`, `zone_manager_entry`, plus any `unsub_*` cleanup handles.
4. **Untracked-task conversion** — 10 sites in `coordinator.py` (`:485, :514, :546, :577, :910, :1003, :1015, :1877, :1891, :2253`) + 1 site in `__init__.py` (`:3359`). Audit each:
   - **Refresh sites** (e.g. `:910, :1003, :1015`): convert to `async_request_refresh()` (coalesced; no new task).
   - **Dispatcher coalescers** (e.g. `_fire_*` at `:485, :514, :546, :577`): evaluate whether the existing fire-and-forget pattern is intentional. If intentional, mark with `# noqa: untracked-ok` + justification comment (per the AST regression test's allowed-marker convention).
   - **Reload-as-task** (`__init__.py:3359` and the high-line sites in `coordinator.py`): convert to `entry.async_create_background_task(hass, ..., name="<descriptive>")` per the v4.2.22 cover-runner REUSED pattern.

**Surfaces NOT touched in D1** (descoped to keep D1 hotfix-scale):

- Tech-debt #3 (EntityDescription rollout) — separate ROI track; force-functioned by the next new-coordinator cycle (ROADMAP_v11:680-687).
- Tech-debt #4 (`runtime_data` migration) — absorbed into the v5.0 plan (`PLANNING_config_subentries_migration.md` D3c). NOT in D1.
- Tech-debt #5 (config subentries) — gated on D1; lives in `PLANNING_config_subentries_migration.md`.
- HouseStateMachine restart persistence — operator open question (see `project_v4_7_18_1_sleep_wake_deadlock`). D1 must NOT silently introduce persistence for it.

**Constants / symbols:** **none new**. No new entities. Pure plumbing.

**Acceptance criteria:**

- **Verify:** After integration reload, `hass.services.async_services()[DOMAIN]` returns the same set as before reload (no stale services accumulating one ghost copy per reload).
- **Verify:** `dir(hass.data[DOMAIN])` after `async_unload_entry(integration_entry)` returns no stale keys for the build-time-verified write list (target: 0 stale keys).
- **Verify:** Every `hass.http.async_register_static_paths` and `panel_custom.async_register_panel` call has a paired teardown registered via `entry.async_on_unload`.
- **Test:** `quality/tests/test_setup_unload_symmetry.py`:
  - `test_services_unregistered_on_unload`
  - `test_panels_torn_down_on_unload`
  - `test_static_paths_released_on_unload`
  - `test_hass_data_drained_on_unload`
- **Test (AST regression):** `test_no_untracked_async_create_task_in_coordinator_or_init` — AST-walk `coordinator.py` and `__init__.py` and fail on any `hass.async_create_task(` call that is not part of a tracked pattern (`entry.async_create_background_task`, `asyncio.gather`, or explicitly marked `# noqa: untracked-ok` with a justification comment).
- **Live:** After HA restart on the operator's live instance, the URA reload button (Developer Tools → YAML → Reload Universal Room Automation) can be pressed **5 times in a row** without the integration accumulating ERROR logs and without HA-core logs showing "stale service" or "duplicate static path" warnings.
- **Live:** `setup_telemetry` sensor on the CM device shows monotonically-correct counters for setup/unload cycles (REUSED v4.6.10 review-fix B2 surface).
- **Live:** No new `KeyError` or `AttributeError` in the post-restart log referencing keys removed during the pop-symmetry audit (verify the defensive `pop(key, None)` conversions did not break a reader that depended on `del`-raises-KeyError semantics).

---

## 3. Tier classification: Tier 2 (justified)

This is NOT Tier 2-DB because it does not touch DAO definitions, does not change persisted record payloads, does not migrate ≥3 callers to a new DAO, and does not introduce behavioral test infra against real schemas. It IS Tier 2 (not Tier 1 hotfix) because:

- Multiple files touched (`__init__.py`, `coordinator.py`, tests).
- Cross-cutting surface (every coordinator's setup path is sampled by the pop-symmetry audit).
- Pure plumbing changes that look low-risk are exactly the surface where untested lifecycle paths bite (the v4.2.24 silent-save class).

**Two parallel reviews, framing-disjoint** (per `CLAUDE.md` Tier 2 — different framings can't share blind spots):

- **Review A — Correctness + edge cases.** Every service / panel / static-path registration has a paired teardown. Every `pop(key, None)` matches a setup-time write. AST regression covers the untracked-task surface. No fabricated HA API calls (e.g. confirm `frontend.async_remove_panel` exists and accepts the panel name URA used). Each untracked-task conversion preserves intended fire-and-forget semantics where applicable. Reviewers cite file:line for every finding.
- **Review B — Async / lifecycle / race conditions.** No `async_update_entry` introduced inside `async_setup_entry` (Bug Class #46 invariant holds). Teardown lambdas don't race with setup completion. Shared-resource teardown ordering: the integration entry's unload must NOT tear down a resource a still-loaded sibling entry depends on (the v4.2.24 surface). Bug Class #42 (lambda+async_create_task in scheduler callbacks, v4.6.15) is not regressed by any task conversion. Reload-stress (5x reloads) does not produce orphan tasks or duplicate listeners.

**Pre-deploy zero-bugs gate** per `feedback_pre_deploy_zero_bugs_gate`: grep conflict markers, py_compile changed files, run cycle tests, run isolated suite-baseline-diff.

---

## 4. Sequencing (the gate, explicit)

```
            ┌─────────────────────────────────────────────┐
            │  Today: v4.7.18.1 LIVE                      │
            └──────────────────────┬──────────────────────┘
                                   │
                                   ▼
            ┌─────────────────────────────────────────────┐
            │  THIS PLAN — D1 setup/unload symmetry       │
            │  Tier 2 (two reviews, not Tier 2-DB)        │
            │  Live-validate on operator instance         │
            │  ≥1 reload cycle clean before v5.0 build    │
            └──────────────────────┬──────────────────────┘
                                   │ [GATE — D1 must live-validate]
                                   ▼
            ┌─────────────────────────────────────────────┐
            │  PLANNING_config_subentries_migration.md    │
            │  Tier 2-DB (three reviews, framing-disjoint)│
            └─────────────────────────────────────────────┘
```

D1 ships on its own release. The subentries cycle does NOT begin BUILD until D1 has shipped AND live-validated for at least one reload cycle on the operator's instance.

---

## 5. Plan-completion tracking

Per `CLAUDE.md` §"Plan Completion Tracking — MANDATORY", every item NOT shipped in this hotfix is documented here.

1. **Tech-debt #2 (tracked background tasks) — full sweep.** D1 audits and converts the 10 + 1 sites identified in `coordinator.py` + `__init__.py`. Any sites outside those files (e.g. `domain_coordinators/*.py`, `aggregation.py`, platform files) are NOT in scope for D1. Build-phase verify whether additional sites exist; if so, schedule a follow-up sweep. Reason: scope-bound the hotfix surface.
2. **HouseStateMachine restart persistence.** Open question per `project_v4_7_18_1_sleep_wake_deadlock`. NOT addressed by D1. Reason: D1 is pure plumbing; persistence is a behavioral change.
3. **EntityDescription rollout (tech-debt #3).** Independent ROI track. NOT in D1.
4. **`runtime_data` migration (tech-debt #4).** Absorbed into the v5.0 subentries plan as D3c. NOT in D1.
5. **Config subentries (tech-debt #5).** Lives in `PLANNING_config_subentries_migration.md`. Gated on D1.
6. **Coordinator-internal `async_unload_entry` hooks.** Each domain coordinator may have its own listener-cleanup gaps (build-time-verify). D1 covers `__init__.py`'s 5 branches; coordinator-internal cleanup is opportunistic — fix in-cycle if surfaced by review, defer otherwise.

---

## 6. Risk register

| ID | Risk | Probability | Impact | Mitigation |
|---|---|---|---|---|
| R1 | Defensive `pop(key, None)` conversion breaks a reader that depended on `del`-raises-KeyError semantics | Low | Medium | Reviewer A audits each conversion against caller sites. Live-validation watches for new `KeyError`/`AttributeError` post-restart. |
| R2 | An untracked-task conversion to `entry.async_create_background_task` regresses Bug Class #42 (lambda+async_create_task in scheduler callbacks) | Low | High | Reviewer B specifically chartered to verify Bug Class #42 fixes are preserved. AST regression test allowlists `add_job` patterns. |
| R3 | `frontend.async_remove_panel` API shape (or static-path release API) is fabricated and doesn't exist | Low | High | Build-time-verify against https://developers.home-assistant.io BEFORE writing the call site. If not verified, ASK before SHIP. |
| R4 | Shared-resource teardown ordering: integration-entry unload tears down database while a sibling room entry still depends on it | Medium | High | Reviewer B charters this case explicitly. If the shared-resource ownership model is unclear, defer to the subentries cycle where HA's `async_unload_subentry` contract makes ownership explicit. |
| R5 | Reload-stress live test surfaces a new orphan-task class not caught by AST | Medium | Medium | The 5x-reload live check is the catch. If a regression surfaces post-deploy, hotfix on top of D1; do NOT begin v5.0 build until clean. |

---

## 7. README requirements

`docs/readmes/README_v<patch>.md` for this release must include:

1. **What changed** — setup/unload symmetry hardening; no behavioral or visible changes.
2. **Live-validation procedure** — 5x reload check; `setup_telemetry` sensor counter inspection.
3. **Why this exists** — link to `ROADMAP_v11.md:619-698` arch-debt history.
4. **What this unblocks** — the v5.0 config subentries migration (`PLANNING_config_subentries_migration.md`).

---

## 8. Recall

- "Resume setup/unload symmetry plan"
- "Plan setup unload symmetry"
- "v5.0 prereq plan"
- "Arch-debt #1 hotfix"
