# v4.7.18.3 — Setup/unload symmetry: paired teardowns + tracked background tasks

**Tier 2 hotfix (two framing-disjoint reviews).** Carved out of the long-standing "v5.0 architectural-debt" backlog item into a standalone, shippable hotfix. ~128 ins `__init__.py`, ~99 ins `coordinator.py`, + a 446-line test module (642 ins / 31 del across 3 code files). Reviews: A = correctness/edge (SHIP, 0C/0H/1M/+LOWs), B = async/lifecycle/race (DON'T-SHIP-as-is, **1C/2H**/4M/3L — all CRITICAL+HIGH fixed). Fix-up `56448d8`. Review docs: `docs/reviews/code-review/setup_unload_symmetry_review_{A_correctness,B_lifecycle}.md` + `setup_unload_symmetry_DEFERRED.md`.

## The problem — asymmetric setup/unload (architectural debt)

URA's `async_setup_entry` registers a lot of process-global state — DOMAIN services, two frontend panels, and ~11 fire-and-forget background tasks — but the matching `async_unload_entry` did not pair every one of those registrations with a teardown. On a config-entry **reload** (which HA implements as unload-then-setup), the un-torn-down registrations leaked:

- **Services** survived the unload and got re-registered on setup → "Service already registered" churn.
- **Frontend panels** were never removed → stale panel entries.
- **Untracked `hass.async_create_task(...)`** tasks were not in `entry._background_tasks`, so `_async_process_on_unload` never cancelled them → they could outlive the entry and touch torn-down state.

This was filed under the old "v5.0 arch debt" umbrella. It's extracted here as its own Tier-2 hotfix with the debt history intact, rather than waiting for a v5.0 that may never be framed as a single cycle (per the versioning convention: major bumps are for major *new functionality*, not debt paydown).

## The fix — pair every registration with a teardown

| Registration (setup) | Teardown (unload) |
|---|---|
| DOMAIN services (full list, grep-verified complete) | `entry.async_on_unload(lambda _n=name: hass.services.async_remove(DOMAIN, _n))` with default-arg closure binding + `has_service` guard (A-LOW-2) |
| 2 frontend panels | `frontend.async_remove_panel(hass, url_path)` on unload (API verified `@callback`/sync at `frontend/__init__.py:394`) |
| ~11 untracked background tasks | `entry.async_create_background_task(...)` so `_async_process_on_unload` cancels them on unload |
| `del hass.data[DOMAIN][...]` | `pop(key, None)` — teardown-order-safe |

**One deliberate exception (B-CRIT-1):** the options-update **self-reload** task MUST stay an *untracked* `hass.async_create_task(hass.config_entries.async_reload(entry.entry_id))`. A tracked background task registered on the same entry gets cancelled by `_async_process_on_unload` during the reload's *own* unload phase (config_entries iterates `entry._background_tasks` and cancels each) — aborting the reload mid-flight and leaving the entry stuck `NOT_LOADED`. This is the standard HA-core self-reload pattern (plex, flux_led, tile, epson). A new AST regression test pins the untracked form present + tracked form absent.

**Static-path gap (documented, not fixed):** registered static paths cannot be cleanly deregistered on older aiohttp versions; the comment now reads "may raise depending on aiohttp version" rather than asserting a clean teardown.

## Tier 2 review resolutions (CRITICAL + HIGH all fixed)

| ID | Sev | Issue | Resolution |
|---|---|---|---|
| B-CRIT-1 | CRIT | Self-reload converted to a *tracked* task self-cancels during its own unload → entry stuck `NOT_LOADED`. | **Fixed** — reverted to untracked `hass.async_create_task` + `# noqa: untracked-ok` justification + AST regression test. |
| B-HIGH-1 | HIGH | Tier-1 refresh swapped `async_refresh()` → `async_request_refresh()`; URA does not override the default debouncer (cooldown=10s), so burst occupant-confirmation latency could rise to ~10s on top of the existing 2s rate limiter. | **Fixed** — reverted to `async_refresh()`, kept the `entry.async_create_background_task` wrapper. |
| B-HIGH-2 | HIGH | Four dispatcher `_on_*` background tasks eager-start (begin synchronously) and the handlers do not early-return when the entry is unloaded. | **Fixed** — `eager_start=False` on all four sites (grep confirmed no `entry.state` guard exists). |
| A-MED-1 | MED | Same `async_request_refresh()` drift as B-HIGH-1, framed from correctness. | **Fixed** (same revert). |
| B-MED-3 | MED | Unbounded `{trigger_key}`/`{room_name}` interpolation in task names. | **Fixed (partial)** — `entry.entry_id[:8]` at 4 sites. |
| A-LOW-1 | LOW | Service-teardown test too loose. | **Fixed** — AST-walks the teardown tuple node. |
| A-LOW-2 | LOW | Teardown lambda could warn on already-absent service. | **Fixed** — `hass.services.has_service` guard. |
| B-LOW-3 | LOW | Static-path comment overstated clean teardown. | **Fixed** — softened. |

Deferred LOW/MED (B-MED-2, B-MED-4, B-LOW-1, B-LOW-2, A-LOW-3/5/6) are listed with reason + tracking in `setup_unload_symmetry_DEFERRED.md`.

## Files changed

| # | File | What |
|---|---|---|
| 1 | `__init__.py` | Paired service + panel teardowns via `async_on_unload`; `del`→`pop(key, None)`; self-reload kept untracked (B-CRIT-1); static-path comment softened. |
| 2 | `coordinator.py` | ~11 untracked tasks → `entry.async_create_background_task`; Tier-1 refresh keeps `async_refresh()` (B-HIGH-1); `eager_start=False` on 4 dispatcher `_on_*` tasks (B-HIGH-2). |
| 3 | `quality/tests/test_setup_unload_symmetry.py` | 11 tests — AST canaries (teardown tuple, untracked self-reload present + tracked absent) + behavioral teardown coverage. |

## Migration

- **No DB migration. No CONF migration. No new config knobs.** Pure config-entry lifecycle hygiene.

## Live validation (post-restart)

1. Trigger an options reload (change any room option, or call `homeassistant.reload_config_entry` on a URA entry).
2. Confirm the entry returns to **LOADED** (not `NOT_LOADED`) — proves the untracked self-reload survived its own unload.
3. Confirm no "Service `<domain>.<name>` already registered" warnings and no duplicate panels after reload.
4. `ha_get_logs source=error_log hours_back=1` — clean of new teardown/lifecycle errors.

## Acceptance

```yaml
version: v4.7.18.3
hypotheses:
  - id: H1
    name: entry_reload_returns_loaded
    description: |
      A config-entry reload (options change) returns the entry to LOADED.
      The self-reload task must not self-cancel during its own unload.
    query:
      kind: ha_log_count
      source: error_log
      search: "Config entry .* for universal_room_automation not ready"
      hours_back: 1
    expected:
      condition: "<="
      value: 0
    window:
      first_check_after: 1h
      confirm_after: 24h
      alert_if_violated_after: 72h
  - id: H2
    name: no_duplicate_service_registration
    description: |
      No "Service already registered" warnings after a reload — services
      are torn down on unload and cleanly re-registered on setup.
    query:
      kind: ha_log_count
      source: error_log
      search: "already registered"
      hours_back: 1
    expected:
      condition: "<="
      value: 0
    window:
      first_check_after: 1h
      confirm_after: 24h
      alert_if_violated_after: 72h
```

## Rollback

HACS install v4.7.18.2 — prior (asymmetric) unload behavior restored. No persisted state shape changed; clean either direction.
