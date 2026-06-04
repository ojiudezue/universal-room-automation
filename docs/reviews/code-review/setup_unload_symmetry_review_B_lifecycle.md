# Setup/Unload Symmetry Hotfix — Code Review B (Async + Lifecycle + Races)

**Branch:** `feature/setup-unload-symmetry` (tip `7bf8b14`, branched from develop `51a3d72`)
**Files reviewed:** `custom_components/universal_room_automation/__init__.py`, `custom_components/universal_room_automation/coordinator.py`, `quality/tests/test_setup_unload_symmetry.py`
**Spec:** `docs/planning/PLANNING_setup_unload_symmetry.md`
**Reviewer framing:** Async semantics + lifecycle + race conditions + restart resilience
**Parallel review:** A (correctness / edge-cases) — not duplicated here.

---

## Summary of frame-relevant verdicts

| Severity | Count |
|---|---|
| CRITICAL | 1 |
| HIGH | 2 |
| MEDIUM | 4 |
| LOW | 3 |
| Verdict | **DON'T-SHIP as-is** — fix B-CRIT-1 (self-cancelling reload task) + at least B-HIGH-1 (Tier-1 refresh debouncer regression) before merge |

The change is **directionally correct** and the planning-doc analysis is sound. The lambda binding pattern, the LIFO teardown ordering, and the `async_on_unload` callable contract have all been correctly handled. But two conversions changed observable behavior in ways the planning doc did not flag, and one of them (the reload task) is a real foot-gun.

---

## HA core API verifications (cited, not guessed)

Confirmed against `home-assistant/core` master (via `gh api` fetches during review):

| Symbol | Kind | File:line | Implication |
|---|---|---|---|
| `frontend.async_remove_panel` | `@callback` (sync) | `homeassistant/components/frontend/__init__.py:393-405` | Lambda returns `None`, no coroutine leak. **OK.** |
| `hass.services.async_remove` | `@callback` (sync) | `homeassistant/core.py:2663-2671` | Lambda returns `None`, no coroutine leak. **OK.** |
| `ConfigEntry.async_on_unload` signature | `Callable[[], Coroutine[…] \| None]` | `homeassistant/config_entries.py:1214-1220` | Accepts **either** sync or coroutine-returning callables. If the callable returns a coroutine, `_async_process_on_unload` schedules it via `async_create_task(eager_start=True)`. Our lambdas return `None`, so the simple path is taken. **OK.** |
| Unload ordering | `await component.async_unload_entry(...)` THEN `await self._async_process_on_unload(hass)` | `homeassistant/config_entries.py:1042-1046` | The integration's `async_unload_entry` runs **before** any `async_on_unload` callback fires. See B-MED-1 below for the consequence. |
| `_async_process_on_unload` semantics | LIFO callback drain, then `task.cancel(...)` on every `_background_tasks` entry, then `asyncio.wait([...], timeout=10)` | `homeassistant/config_entries.py:1222-1245` | Background tasks are cancelled **after** all on_unload callbacks. See B-CRIT-1 and B-MED-2. |
| Default `request_refresh_debouncer` | `cooldown=10, immediate=True` | `homeassistant/helpers/update_coordinator.py:35-36, 135-141` | Material to B-HIGH-1: switching `async_refresh()` → `async_request_refresh()` adds a 10-second debouncer cooldown on top of URA's existing 2-second hand-rolled rate limiter. |
| `hass.http.async_register_static_paths` | No removal API; aiohttp `app.router.register_resource` exposes no removal | `homeassistant/components/http/__init__.py:512-543` | Static-path gap documentation is accurate. **OK.** |

---

## Findings

### B-CRIT-1 — Reload task self-cancels via the entry's own `_background_tasks` set
**Severity:** CRITICAL — async lifecycle race
**Bug class:** Bug Class #19 (Untracked Background Tasks — inverted: this is "over-tracked")
**File:** `custom_components/universal_room_automation/__init__.py:3433-3442` (`_async_update_listener`)

`_async_update_listener` was converted from `hass.async_create_task(hass.config_entries.async_reload(entry.entry_id), ...)` to `entry.async_create_background_task(hass, hass.config_entries.async_reload(entry.entry_id), "ura_reload_{...}")`.

**Why this is wrong:** the reload task ends up registered in `entry._background_tasks`. The task itself executes `async_reload`, which calls `async_unload(entry)`, which (per `config_entries.py:1042-1046`) eventually invokes `_async_process_on_unload`. That method cancels every task in `_background_tasks` — **including the running reload task itself** — before reload's setup phase runs (`config_entries.py:1233-1234`: `for task in self._background_tasks: task.cancel(cancel_message)`).

The currently-executing task then receives `CancelledError` at the next await point inside `async_reload`'s post-unload setup path. The integration is left in `NOT_LOADED` state because setup never completes. The user's options-change save will *appear* to succeed but the integration will silently stop running until manual reload from the UI.

**HA core convention (verified):** the standard pattern for self-reload from inside a config entry is the **untracked** `hass.async_create_task(hass.config_entries.async_reload(entry.entry_id))` precisely so the task survives its own entry's unload phase. Verified at `homeassistant/components/plex/__init__.py`, `homeassistant/components/flux_led/select.py`, `homeassistant/components/tile/config_flow.py`, `homeassistant/components/epson/media_player.py` (`gh search code`, 4+ exemplars).

The patch comment ("the reload itself replaces this entry's coordinator, so the task is effectively self-terminating") is **incorrect** — by the time the new coordinator is being created, the cancelled task throws `CancelledError` and the new setup is aborted.

**Suggested fix:** revert this site to the untracked `hass.async_create_task(...)` form and add `# noqa: untracked-ok — self-reload must outlive entry unload; standard HA core pattern (plex, flux_led, tile, epson use the same form)`. Update the AST test's allowlist comment to match. Add a regression test that calls `_async_update_listener` and asserts the integration is `LOADED` after the listener returns.

---

### B-HIGH-1 — Tier-1 `async_refresh()` → `async_request_refresh()` introduces ≤10s debouncer cooldown
**Severity:** HIGH — observable behavior change, presence responsiveness regression
**Bug class:** Bug Class #14 (Config Snapshot Staleness) adjacent — "behavior assumed unchanged, was not"
**File:** `coordinator.py:925-936` (Tier-1 event-driven refresh path)

The diff switched the Tier-1 refresh from `self.hass.async_create_task(self.async_refresh())` to `self.entry.async_create_background_task(self.hass, self.async_request_refresh(), "ura_tier1_refresh")`. The patch comment claims "switched … to additionally benefit from the DataUpdateCoordinator debouncer (collapses bursts)."

**The behavior change is non-trivial.** `UniversalRoomCoordinator.__init__` (coordinator.py:276-281) calls `super().__init__(...)` **without** passing `request_refresh_debouncer`, so the default applies (`update_coordinator.py:135-141`): `cooldown=10, immediate=True`. With `immediate=True`, the first call after a quiet period fires immediately, but any subsequent calls within 10 seconds are coalesced into a single trailing-edge execution.

The Tier-1 path already has a **2-second hand-rolled rate limit** (coordinator.py:914-922) with an `async_call_later` trailing-edge follow-up. After the 2-second gate passes (i.e., a real event ≥2s after the last refresh), the old code did a fresh `async_refresh()` directly. The new code routes through a 10-second debouncer, so successive events that pass the 2-second gate but fall within the 10-second debouncer cooldown will be **delayed by up to 10s** — exactly the latency the rate limiter was designed to bound to ~2s for "the last event in a burst."

For a moving occupant (entering a room → quick sequence of motion / presence binary-sensor flips), this could push the "occupied" confirmation that drives lighting / scene actions out to 10s in worst case. Visible regression.

**Mitigation options (pick one):**
1. Revert this single line to `self.async_refresh()` (keep the `entry.async_create_background_task` wrapper for the tracking benefit) — preferred. The rate limiter is already burst-safe; adding the HA debouncer is redundant and slower.
2. Construct a `Debouncer(..., cooldown=0.0, immediate=True)` and pass via `request_refresh_debouncer=` in `super().__init__`. Heavier surface, only worth it if other call sites benefit.

The `_debounce_refresh_callback` (coordinator.py:1027-1033) and `_trailing_refresh_callback` (coordinator.py:1043-1049) correctly keep `async_refresh()` — those are already post-debounce, so no extra-cooldown concern.

---

### B-HIGH-2 — Eager-start coroutine creation can throw inside the registering caller, leaking the unwrapped coroutine
**Severity:** HIGH — restart resilience
**Bug class:** Bug Class #5 (Race Conditions on Startup) adjacent
**Files:** `coordinator.py:486-490, 519-523, 551-557, 585-591, 928-934, 1029-1033, 1045-1049, 1909-1922, 1934-1939, 2293-2306`

`entry.async_create_background_task` defaults to `eager_start=True` (`config_entries.py:1389-1414`). With eager start, the coroutine **begins executing synchronously** inside the `async_create_background_task` call until it hits its first `await`. If the coroutine raises before the first await (e.g., `AttributeError` because `self.entry` was torn down, or a defensive guard fails), the exception propagates out of `async_create_background_task` into the calling `@callback` handler — including the dispatcher-driven `_on_house_state_signal` / `_on_energy_constraint` / `_on_safety_hazard` / `_on_security_event` paths.

These callbacks are invoked from `async_dispatcher_send`. An exception in one signal listener does not currently affect siblings, but a logged-and-ignored stack trace per dispatcher tick during teardown will create noise during reloads.

**Specific risk:** during entry-unload, `self.entry._background_tasks` is being cancelled and `hass.data[DOMAIN].pop(...)` calls are running. A late-arriving signal that enters one of these `_on_*` handlers will eagerly start a coroutine that accesses `self.hass.data[DOMAIN][...]` — pop'd → `KeyError` raised synchronously inside eager-start, propagating to the dispatcher.

**Suggested fix:** wrap each `entry.async_create_background_task(...)` registration call in a defensive try/except OR (cleaner) pass `eager_start=False` for the dispatcher-callback sites so the coroutine starts on the loop, not in the caller. Add a single-line `if not self.entry.state == ConfigEntryState.LOADED: return` guard at the top of each `_on_*` handler if not already present.

---

### B-MED-1 — Service handlers remain registered briefly after their backing state is popped
**Severity:** MEDIUM
**Bug class:** Bug Class #20 (Concurrent Config Entry Reload Race)
**File:** `__init__.py:async_unload_entry` (the entire body) and the service-teardown loop at `__init__.py:2275-2306`

Per `config_entries.py:1042-1046`, `await component.async_unload_entry(hass, self)` runs **before** `_async_process_on_unload`. So:

1. `async_unload_entry` pops `hass.data[DOMAIN][...]` keys (good — the `pop(key, None)` change is the right defensive pattern).
2. Only **then** do the `entry.async_on_unload` lambdas run, which call `hass.services.async_remove(DOMAIN, ...)`.

During the window between step 1 and step 2, the service handlers are still registered. If a HA frontend tab or automation invokes e.g. `universal_room_automation.set_house_state` in that window, the handler's closure references the now-popped `hass.data[DOMAIN]` keys → `KeyError`. The window is microseconds in practice but exists on every reload.

**Suggested fix (low cost, defensive):** move the service-teardown loop to fire **at the top** of `async_unload_entry` (before any `pop`), instead of via `async_on_unload`. The setup/unload symmetry doc explicitly chooses `async_on_unload` for clean pairing, which is the cleaner code pattern — but ordering-wise, services should be torn down first. Alternative: keep `async_on_unload` and ensure each handler defensively `.get()`s its state (which most already do via `hass.data[DOMAIN].get("coordinator_manager")` etc., so the actual blast radius is small — confirm by grepping handler bodies).

I'd accept this as MEDIUM-deferred IF the operator confirms via grep that every service handler uses `.get()` not `[...]` on `hass.data[DOMAIN]`. Otherwise treat as HIGH.

---

### B-MED-2 — Background tasks cancelled mid-flight may attempt `hass.data[DOMAIN]` access on popped keys
**Severity:** MEDIUM
**Bug class:** Bug Class #19 (Untracked Background Tasks)
**Files:** `coordinator.py:486-490, 519-523, 551-557, 585-591, 1909-1922, 1934-1939`

The newly-tracked background tasks (`_fire_house_state`, `_fire_energy`, `_fire_safety`, `_fire_security`, `_delayed_exit_verify`, activity-logger tasks) get cancelled by `_async_process_on_unload` **after** `async_unload_entry` has run and after the on_unload callbacks have fired (LIFO). For most of the cancellation window, the popped keys are gone.

`coordinator.py:2012` uses `self.hass.data[DOMAIN].get("database")` — safe. I spot-checked the dispatcher-fire chains; `_fire_chained_automations` (coordinator.py:354) does not seem to re-enter `hass.data[DOMAIN]` directly, but `_execute_ai_rules` and the activity-logger pathways might. The blast radius depends on those internals.

**Suggested fix:** for the activity-logger tasks (coordinator.py:1909, 2293), the logger handle is already captured by reference (`activity_logger.log(...)`) so the data-pop doesn't matter for the call site itself. The internal log call may write to a DB handle that has been closed; verify that `activity_logger.log()` is safe-on-cancel and safe against the DB pop. Add a `try/except CancelledError` at the top of `_delayed_exit_verify` so its `asyncio.sleep` cancellation doesn't log spurious cancellation tracebacks.

---

### B-MED-3 — Per-trigger task names embed unbounded labels
**Severity:** MEDIUM (memory only, observability)
**Bug class:** None (operational hygiene)
**Files:** `coordinator.py:486-490, 1916-1921, 1934-1939, 2298-2305`

Task names like `f"ura_fire_house_state_{trigger_key}"`, `f"ura_activity_log_{occ_action}_{room_name}"`, `f"ura_delayed_exit_verify_{room_name}"`, `f"ura_activity_log_light_{action_type}"` interpolate values that may include spaces, slashes, or arbitrary user-set room names. HA's task-name handling stores the name string in the task and logs it on slow-task warnings; not unsafe, but creates uniqueness explosion in HA's `_tasks` debug surfaces.

The HA convention is short, fixed task names (see `homeassistant/components/*/coordinator.py` exemplars). Per-instance dynamism is OK for room names; arbitrary trigger keys less so.

**Suggested fix:** drop the trigger_key/action interpolation; use `f"ura_fire_house_state_{self.entry.entry_id[:8]}"` and similar. Low priority.

---

### B-MED-4 — `_panel_path` / `_panel_v3_path` literal-vs-test interaction
**Severity:** MEDIUM (test stability)
**Bug class:** Bug Class #40 (Self-Validating Behavioral Tests) adjacent
**File:** `__init__.py:2338, 2378` + `quality/tests/test_setup_unload_symmetry.py:147-161`

The panel-path string literals (`"ura-dashboard"`, `"ura-dashboard-v3"`) were moved into local variables to support the lambda's default-arg binding. The tests assert the bare string literals appear "anywhere in the file" — currently they do (assigned to `_panel_path`), so the test passes. But a future refactor that uses a constant import would silently break the test without breaking the behavior. This is the "test pins the literal, not the behavior" anti-pattern.

**Suggested fix:** the test should assert the **panel registration kwarg** (`frontend_url_path=_panel_path` resolves to `"ura-dashboard"`) via AST walk, not via raw substring. Or extract the panel path to `const.py` and have both the registration and the teardown reference the constant. Defer unless trivial.

---

### B-LOW-1 — Services are domain-scoped; two INTEGRATION entries would compete
**Severity:** LOW (theoretical; URA is single-entry by design)
**Bug class:** Bug Class #20 (Concurrent Config Entry Reload Race) — far cousin
**File:** `__init__.py:2275-2306`

If — hypothetically — two INTEGRATION-type config entries co-existed, both would register the same `DOMAIN/<service>` handler. The second `async_register` would silently override the first; on unload of either entry, the service is removed and the surviving entry's handler is gone. URA is documented as single-INTEGRATION-entry by `single_user_no_backcompat` memo, so this is unlikely to bite, but worth a one-line comment at the registration site: `# URA assumes a single INTEGRATION entry; if multi-entry support is ever added, scope service registration to the entry that registered it`.

---

### B-LOW-2 — `_async_update_listener` reload uses `entry.title` interpolation but the entry may have been renamed mid-flight
**Severity:** LOW (cosmetic, log clarity)
**File:** `__init__.py:3437`

The task name `f"ura_reload_{entry.entry_id}"` is stable (entry_id is immutable). This is fine — flagging only because the old version used `entry.title` which can change. Drop the comment if not relevant.

---

### B-LOW-3 — Static-path gap documentation: confirm "raises on duplicate" actually raises
**Severity:** LOW (correctness of comment)
**File:** `__init__.py:2326-2334`

The comment claims "on entry reload the duplicate registration is detected by aiohttp and raises (caught by the surrounding except)." I did not verify this against aiohttp — `app.router.register_resource` may or may not raise on duplicate path prefixes. Verify or soften the comment to "may raise depending on aiohttp version." Won't affect runtime since the try/except is already in place.

---

## Concerns NOT raised (verified clean)

These were on my checklist and I found nothing to flag:

- **`async_on_unload` callable contract** — verified at `config_entries.py:1214-1220`. Accepts sync callables returning `None` OR callables returning coroutines (auto-scheduled). Our lambdas return `None`. **No "coroutine never awaited" risk.**
- **Lambda default-arg binding** — every lambda correctly uses `_p=_panel_path` / `_name=_service_name` pattern (Bug Class #45 / #24 avoided).
- **LIFO ordering hazard** — verified `_async_process_on_unload` pops from end. The service-teardown loop registers callbacks in iteration order; on unload they fire in reverse iteration order, which doesn't matter for siblings (they're independent service removals).
- **Concurrent reload race vs `hass.data[DOMAIN]` pops** — `pop(key, None)` is correctly defensive; the previous `del`-based unload could KeyError on partial-setup unload (the v4.6.10 review-fix B2 pattern is being correctly extended).
- **Test coverage** — the AST + source-grep tests are appropriately scoped. They will catch:
  - Service-registration / teardown drift (new service added without teardown).
  - Future `del hass.data[DOMAIN][...]` regressions in `async_unload_entry`.
  - New untracked `hass.async_create_task(...)` calls without `# noqa: untracked-ok`.
  Reasonable + maintainable; not over-fitted.
- **Panel registration failure path** — if `panel_custom.async_register_panel` raises mid-call, the `entry.async_on_unload` registration below it is never reached. No orphan teardown for a registration that failed. (Edge: if the panel partially registers, we'd leak, but that's an HA-core bug, not ours.)
- **DataUpdateCoordinator auto-shutdown** — `DataUpdateCoordinator.__init__` already registers `self.config_entry.async_on_unload(self.async_shutdown)` (update_coordinator.py:148-149). So the coordinator's debouncer + interval refresh + listeners get torn down by HA core. Our new on_unload registrations do not interfere.

---

## Stats

| Surface | Finding count |
|---|---|
| `__init__.py` | 1 CRITICAL, 0 HIGH, 2 MEDIUM, 3 LOW |
| `coordinator.py` | 0 CRITICAL, 2 HIGH, 2 MEDIUM, 0 LOW |
| Tests | 0 CRITICAL, 0 HIGH, 1 MEDIUM (B-MED-4), 0 LOW |
| **Total** | **1 CRITICAL · 2 HIGH · 4 MEDIUM · 3 LOW** |

## Bug-class frequency

| Bug class | Hits in this review |
|---|---|
| #19 Untracked Background Tasks (inc. over-tracked) | 2 |
| #20 Concurrent Config Entry Reload Race | 2 |
| #5 Race Conditions on Startup | 1 |
| #14 Config Snapshot Staleness (analogous) | 1 |
| #40 Self-Validating Behavioral Tests (analogous) | 1 |
| #24 / #45 Lambda Closure Scope | 0 (verified clean — kept the entry for confidence) |

## Verdict

**DON'T-SHIP as-is.**

- **Block on:** B-CRIT-1 (reload task self-cancels) — revert to untracked `hass.async_create_task` per HA core convention with a `# noqa: untracked-ok` and justification comment.
- **Strongly recommend fix before ship:** B-HIGH-1 (Tier-1 refresh debouncer regression) — revert the inner `async_request_refresh()` back to `async_refresh()`, keep the tracked-task wrapper.
- **Defer-allowed:** B-HIGH-2 (eager-start propagation) can be deferred IF the dispatcher callbacks already early-return on torn-down entries; verify by grep.
- **Defer-allowed:** B-MED-1 (service teardown ordering) IF every handler uses `.get()` not `[...]` on `hass.data[DOMAIN]`; verify by grep.
- **Defer-allowed:** B-MED-2, B-MED-3, B-MED-4, all B-LOWs.

After fixing B-CRIT-1 and B-HIGH-1, re-run the test suite (AST tests + the wider behavioral suite) and confirm `_async_update_listener` still produces a successful reload end-to-end.
