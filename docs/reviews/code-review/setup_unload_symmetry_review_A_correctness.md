# Code Review A — Setup/Unload Symmetry Hotfix

**Branch:** `feature/setup-unload-symmetry` (tip `7bf8b14`)
**Base:** `develop` `51a3d72`
**Reviewer framing:** Correctness + edge cases (Tier 2, Reviewer A)
**Plan:** `docs/planning/PLANNING_setup_unload_symmetry.md`
**Files in scope:**

- `custom_components/universal_room_automation/__init__.py`
- `custom_components/universal_room_automation/coordinator.py`
- `quality/tests/test_setup_unload_symmetry.py`

**Stats:** +514 / -31 (per `git diff --stat`).

**Verdict: SHIP, with one MEDIUM and a small set of LOWs to address in fix-up.** No CRITICAL or HIGH findings. The service teardown list is complete vs the current source (verified by exhaustive grep). The panel teardown API call is verified against HA core source. The static-path gap claim is accurate. Defensive `pop(key, None)` conversions are behavior-equivalent vs all observed readers. Lambda closure binding is correct. The one MEDIUM is a semantic drift introduced by swapping `async_refresh()` → `async_request_refresh()` at one site beyond what the diff comment claims, which can extend the post-burst refresh quiet period from 2 s to up to 10 s under the HA-default debouncer cooldown.

---

## Verification work performed

1. **HA-core API verification** (no fabrication):
   - `frontend.async_remove_panel(hass, frontend_url_path, *, warn_if_unknown=True)` confirmed at `homeassistant/components/frontend/__init__.py:394` (fetched via GitHub API). `@callback`, synchronous, returns `None`. Removes the panel from `hass.data[DATA_PANELS]` and fires `EVENT_PANELS_UPDATED`. Matches the diff comment exactly.
   - `panel_custom.async_register_panel` delegates to `frontend.async_register_built_in_panel` at `homeassistant/components/panel_custom/__init__.py:122`, so `frontend.async_remove_panel` IS the correct paired teardown.
   - `async_register_static_paths` in `homeassistant/components/http/__init__.py:512-543` adds aiohttp routes directly via `app.router.register_resource` / `app.router.add_route` with no public removal helper. The "no-API" claim is correct.
   - `hass.services.async_remove` at `homeassistant/core.py:2664` is `@callback`, returns `None`, lowercases domain + service, and emits a `_LOGGER.warning("Unable to remove unknown service ...")` if the service is absent.
   - `ConfigEntry._async_process_on_unload` at `homeassistant/config_entries.py:1222` pops callbacks LIFO; truthy returns are scheduled as tasks, `None` returns execute inline. Both URA teardowns return `None` → safe inline.
   - `DataUpdateCoordinator` debouncer defaults at `homeassistant/helpers/update_coordinator.py:35-36`: `REQUEST_REFRESH_DEFAULT_COOLDOWN = 10`, `REQUEST_REFRESH_DEFAULT_IMMEDIATE = True`. URA does NOT override these (`coordinator.py:276`), so `async_request_refresh()` debounces at 10 s with immediate first-call.

2. **Exhaustive service-registration grep.** All `hass.services.async_register(DOMAIN, "...")` sites in the codebase:

   | Line | Service name | In teardown list? |
   |---|---|---|
   | `__init__.py:3098` | `set_house_state` | yes |
   | `__init__.py:3109` | `clear_house_state_override` | yes |
   | `__init__.py:3142` | `test_safety_hazard` | yes |
   | `__init__.py:3223` | `security_arm` | yes |
   | `__init__.py:3235` | `security_disarm` | yes |
   | `__init__.py:3243` | `authorize_guest` | yes |
   | `__init__.py:3254` | `add_expected_arrival` | yes |
   | `__init__.py:3295` | `acknowledge_notification` | yes |
   | `__init__.py:3303` | `test_notification` | yes |
   | `__init__.py:3326` | `test_inbound` | yes |

   Complete. No service is registered outside the four `_async_register_*_services` helpers.

3. **`del hass.data[DOMAIN][...]` sweep.** Verified zero `del hass.data[DOMAIN][...]` calls remain in the feature branch's `__init__.py`. All converted to `pop(key, None)`.

4. **Untracked-task sweep.** Verified zero `hass.async_create_task(` / `self.hass.async_create_task(` calls remain in either `__init__.py` or `coordinator.py` on the feature branch. AST regression test will pass.

5. **`person_coordinator` / `integration` reader audit.** All 36 readers across `aggregation.py` / `sensor.py` / `binary_sensor.py` use `.get(...)` and None-check. No reader depends on `del`-raises-`KeyError` semantics. The `pop(key, None)` conversions are behavior-equivalent.

---

## Findings

### A-MED-1: `async_request_refresh()` swap at Tier1 path extends quiet period beyond the diff comment's claim

- **File:** `custom_components/universal_room_automation/coordinator.py:934-935` (post-diff lines).
- **Bug class:** New — propose "Debouncer cooldown stacking" (LOW recurrence). Closest existing class: #11 "Refresh storm / coalescing".
- **Severity:** MEDIUM.
- **What changed:** the Tier1 event path swapped from `self.hass.async_create_task(self.async_refresh())` to `self.entry.async_create_background_task(self.hass, self.async_request_refresh(), "ura_tier1_refresh")`. The diff comment justifies it as "additionally benefit from the DataUpdateCoordinator debouncer (collapses bursts)".
- **What the actual debouncer does:** HA's default debouncer is `cooldown=10, immediate=True`. First call fires immediately; subsequent calls within 10 s are batched into a single trailing call at the end of the window. URA does NOT pass a custom debouncer (see `coordinator.py:276`), so the 10 s default applies.
- **Pre-existing room-level rate limit at `coordinator.py:896-908`** is a 2 s coalescer (trailing-edge refresh after a quiet 2 s). This was the intentional event-driven responsiveness target.
- **Net effect:** under sustained event bursts (e.g. motion sensor flickers every 3-5 s on a noisy camera), `async_request_refresh` will fire the first time, then SUPPRESS the next ~10 s of refresh attempts. The room's own 2 s trailing-edge logic re-invokes `async_request_refresh`, but the call is debounced. The 2 s SLA the existing design targets is now effectively 10 s in burst conditions.
- **Counter-evidence (mitigating):** the two trailing/debounce sites at `:1032` and `:1048` kept `async_refresh()` (immediate). So the explicit "force now" paths are unaffected. The MEDIUM only applies to the inline burst path.
- **Suggested fix (pick one):**
  1. **Revert this specific site to `async_refresh()`** — keep the tracking-via-`entry.async_create_background_task` benefit, drop the debouncer-stacking. Adjust the comment accordingly.
  2. **Pass a 2 s cooldown debouncer at coordinator init** so the new behavior matches the pre-change intent.
  3. **Document explicitly** in code + planning doc that the Tier1 refresh SLA is now 10 s under burst, and live-validate.
- **Preferred:** option 1 — least surprise, keeps the diff comment honest.

### A-LOW-1: AST regression test asserts service-name literal presence anywhere in `init_src`, not inside the teardown loop

- **File:** `quality/tests/test_setup_unload_symmetry.py:106-115` (`test_every_registered_service_has_paired_async_remove`).
- **Bug class:** #21 "Test fixture authority drift".
- **Severity:** LOW.
- **What the test does:** `assert f'"{name}"' in init_src` — the literal could match the registration string or any other occurrence (e.g. a constant, a comment, a service handler reference). It does NOT prove the literal is inside the `for _service_name in (...): entry.async_on_unload(...)` block.
- **Why it still mostly works:** the cross-check against `_EXPECTED_SERVICE_NAMES` is the substantive drift guard. If someone adds a new service without adding it to `_EXPECTED_SERVICE_NAMES`, the test fails loudly.
- **Suggested fix:** narrow the literal search to the teardown loop. Either AST-walk for the `for _service_name in (...)` `Tuple` node and assert each registered name appears in `elts`, or constrain the substring search to the slice between the loop's start and its closing `)`. Adds maybe 20 LoC; high signal-to-noise for future-proofing.

### A-LOW-2: `hass.services.async_remove` on partial-setup will log "Unable to remove unknown service" warnings

- **File:** HA core `homeassistant/core.py:2680-2682` (verified) — and our teardown loop at `__init__.py:2294-2308` (post-diff lines).
- **Bug class:** #38 "Teardown noisy on partial setup".
- **Severity:** LOW.
- **What happens:** if `_async_register_*_services(hass)` raises midway (e.g. the third helper fails), some of the 10 services are not registered. On unload, all 10 teardown lambdas still fire; the ones whose service was never registered log a warning each. Up to 10 warnings under worst-case partial-setup failure.
- **Suggested fix (optional):** wrap each `hass.services.async_remove(DOMAIN, _name)` with a `if hass.services.has_service(DOMAIN, _name):` guard, OR register teardown lambdas one-per-service AFTER each `_async_register_*_services` call returns. The latter is more code; the former is a 2-line guard. **Defer if scope-tight; not a regression risk, just log noise.**

### A-LOW-3: `_panel_path` / `_panel_v3_path` are local names but `_ha_frontend` is also a local name — captured by closure across `try`/`except`

- **File:** `__init__.py:2298-2363` (post-diff lines).
- **Bug class:** #46 (Bug Class #46 is unrelated — this is a closure-binding observation, not a real defect; LOW noise).
- **Severity:** LOW.
- **Observation:** the lambda captures `_p` via default-arg (correct) AND `_ha_frontend` and `hass` via closure. `_ha_frontend` is the freshly-imported module reference inside the `try` block. By the time the lambda fires on unload, the module reference is still valid (Python modules are interned in `sys.modules`). No defect. Mentioned for completeness so a future reviewer doesn't re-flag.
- **Suggested fix:** none. Could be made fully explicit via `lambda _p=_panel_path, _f=_ha_frontend: _f.async_remove_panel(hass, _p, warn_if_unknown=False)`, but it's stylistic.

### A-LOW-4: `entry.async_create_background_task` cancellation semantics may interrupt safety/security fire-and-forget mid-execution

- **File:** `coordinator.py:553-559` and `:585-591` (safety + security `_fire_*` handlers, post-diff lines).
- **Bug class:** #36 "Safety-critical task cancellation".
- **Severity:** LOW (design note, not a behavior regression).
- **Pre-change behavior:** `hass.async_create_task(_fire_safety())` — orphan task survives entry unload; runs to completion (with potential `AttributeError` if it touches `self.entry` after unload).
- **Post-change behavior:** `self.entry.async_create_background_task(...)` — task is cancelled on entry unload mid-execution. Partial chained automation execution possible if a smoke-detector signal lands at the exact instant of an admin-triggered reload.
- **Why it's still LOW:** entry unload only happens on admin reload / removal. Concurrent safety-hazard signal is vanishingly rare. The pre-change orphan-task behavior was itself unsafe (use-after-unload). The new behavior is the correct discipline.
- **Suggested fix:** none required. Add a one-line code comment at `_fire_safety` / `_fire_security` documenting the trade-off so future reviewers don't re-litigate.

### A-LOW-5: Panel-teardown registration happens AFTER the `_LOGGER.info` — narrow window where panel exists with no paired teardown if logger fails

- **File:** `__init__.py:2349-2362` and `:2387-2393` (post-diff lines).
- **Bug class:** N/A (defensive coding observation).
- **Severity:** LOW (effectively unreachable in practice).
- **Observation:** the order inside the `try` is: register panel → register teardown → log. If the `_LOGGER.info` somehow raised (it won't under normal circumstances), the panel would be registered AND the teardown would be registered — correct. So actually the order is fine. Initially flagged; on re-read it's a non-issue.
- **Suggested fix:** none.

### A-LOW-6: Test file uses `_REPO_ROOT = ...parents[2]` — couples test location to a fixed depth

- **File:** `quality/tests/test_setup_unload_symmetry.py:42-44`.
- **Bug class:** #21 "Test fixture authority drift".
- **Severity:** LOW.
- **Observation:** if the test is ever moved (e.g. into a sub-directory under `tests/`), `parents[2]` breaks silently. Most other URA tests use the same idiom, so this is a project-wide pattern, not a new defect introduced here. Mentioned for completeness.
- **Suggested fix:** none required in this cycle.

---

## Findings the planning doc anticipated and the build addressed correctly

- **R1 (planning doc):** "Defensive `pop(key, None)` conversion breaks a reader that depended on `del`-raises-KeyError semantics" — exhaustively grep-verified all 36 reader sites use `.get()` and None-check. No reader depends on `del` semantics. Risk fully retired.
- **R3 (planning doc):** "`frontend.async_remove_panel` API shape is fabricated" — verified against HA core source. Exact signature match, including the `warn_if_unknown=False` keyword. Risk fully retired.
- **Lambda closure correctness:** the `_name=_service_name` and `_p=_panel_path` default-arg bindings correctly pin per-iteration values. Python late-binding bug avoided. Correct.
- **Service-list completeness:** verified 10/10 registered services are in the teardown tuple. Drift hazard documented in test + comment. Pending A-LOW-1's narrow-search refinement, the drift guard works.
- **HA static-path gap:** documented in source comments AND test (`TestStaticPathsGapDocumented`). Future reviewers will see the gap with reasoning, not silence.

---

## Summary statistics

| Severity | Found | Suggested fix in this cycle | Defer |
|---|---|---|---|
| CRITICAL | 0 | 0 | 0 |
| HIGH | 0 | 0 | 0 |
| MEDIUM | 1 | 1 (A-MED-1) | 0 |
| LOW | 6 | 1-3 (A-LOW-1, A-LOW-2, A-LOW-4) | 3 (A-LOW-3, A-LOW-5, A-LOW-6 — non-defects) |
| **Total** | **7** | **2-4** | **3** |

### Bug class frequency

| Class | Count | Notes |
|---|---|---|
| Debouncer cooldown stacking (proposed new) | 1 | A-MED-1 — propose adding to `QUALITY_CONTEXT.md` if A-MED-1 is fixed by option 2 (custom debouncer); skip if reverted by option 1. |
| #21 Test fixture authority drift | 2 | A-LOW-1, A-LOW-6 |
| #38 Teardown noisy on partial setup | 1 | A-LOW-2 |
| #36 Safety-critical task cancellation | 1 | A-LOW-4 (design note, not a regression) |
| N/A (non-defects / observations) | 2 | A-LOW-3, A-LOW-5 |

### Recommended `QUALITY_CONTEXT.md` updates

- **Conditional on A-MED-1 fix path:** if option 1 is chosen (revert the swap), no new class. If option 2 is chosen (custom debouncer at coordinator init), add a class "Debouncer cooldown stacking" describing the failure mode: stacking the HA default 10 s `async_request_refresh` debouncer on top of an existing application-level coalescer extends the effective refresh quiet period beyond what the application's coalescer was designed for.

---

## Verdict

**SHIP** after addressing A-MED-1. The LOWs are fix-in-cycle candidates per `feedback_fix_lows_in_cycle` (A-LOW-1, A-LOW-2 are 1-30 LoC); A-LOW-3 / A-LOW-5 / A-LOW-6 are non-defects and can be skipped. Live-validation per planning doc D1 acceptance criteria (5x reload + setup_telemetry counter inspection + `hass.services.async_services()[DOMAIN]` drift check) remains the post-deploy gate.

The work is the right shape for a v5.0 prereq: pure plumbing, narrow blast radius, AST-tested for regression. No CRITICAL or HIGH means Reviewer B's framing (async/lifecycle/race) is the more likely source of any blockers.
