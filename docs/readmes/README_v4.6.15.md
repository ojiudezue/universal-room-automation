# URA v4.6.15 — Thread-Safety Hotfix (Bug Class #42)

**Release date:** 2026-05-26
**Tier:** Tier 2-DB scale (3 parallel reviewers per CLAUDE.md user-coined protocol)
**Trigger:** HA-core crashes correlated with URA frame-helper warnings during 2026-05-26 Envoy maintenance window

---

## TL;DR

URA shipped 5 sites of `lambda _now: self.hass.async_create_task(self._async_refresh())` as scheduler callbacks. HA's `homeassistant.helpers.frame` detected this as "calls async_create_task from a thread other than the event loop, which may cause Home Assistant to crash or data to corrupt" — 18 warnings per boot before this fix. Coroutines were silently never awaited; affected sensors stopped refreshing; multiple HA crashes correlated.

Fix: pass coroutine functions directly to HA schedulers (sensor.py timer-interval callbacks) and use `functools.partial` for closure-binding (NM digest schedulers). Plus two `_handle_db_ready` dispatcher callbacks switched to `hass.add_job` per the v4.6.3.2 precedent.

---

## What's Changed

### Bug fixes — 5 anti-pattern sites + 2 defensive conversions

| Site | Class | Before | After |
|---|---|---|---|
| `sensor.py:11407` | `CoordinatorOverrideFrequencySensor` (v4.6.13) | `lambda _now: async_create_task(...)` in `async_track_time_interval` | `self._async_refresh` passed directly |
| `sensor.py:11525` | `CoordinatorComplianceRateSensor` (v4.6.13) | same | same |
| `sensor.py:11650` | `URADBSizeSensor` (v4.6.13) | same | same |
| `notification_manager.py:1983` | NM morning digest (v3.6.29) | `lambda now, pid=..., pcfg=...: async_create_task(...)` in `async_track_time_change` | `partial(self._fire_digest, person_id, person_cfg)` |
| `notification_manager.py:2001` | NM evening digest (v3.6.29) | same | same |
| **`sensor.py:11426`** | `_handle_db_ready` (defensive) | `self.hass.async_create_task(...)` | `self.hass.add_job(...)` |
| **`sensor.py:11552`** | `_handle_db_ready` (defensive) | same | same |

### Method signatures updated

- `CoordinatorOverrideFrequencySensor._async_refresh(self, _now=None)`
- `CoordinatorComplianceRateSensor._async_refresh(self, _now=None)`
- `URADBSizeSensor._async_refresh(self, _now=None)`
- `NotificationManager._fire_digest(self, person_id, person_cfg, _now=None)`

`_now` accepts the datetime that HA's scheduler passes; default `None` keeps existing direct-call sites working.

### New regression test

`quality/tests/test_v4615_threadsafety.py` (3 tests, all passing):
- `test_no_lambda_wrapping_async_create_task` — AST walk of URA tree, asserts zero `lambda` bodies contain `async_create_task` attribute calls. Would have caught all 5 original sites.
- `test_v4615_fix_sites_use_direct_coroutine_passing` — pins the positive pattern at each known site.
- `test_handle_db_ready_uses_add_job_not_async_create_task` — pins the v4.6.3.2 precedent for the 2 defensive conversions.

### New bug class documentation

`docs/QUALITY_CONTEXT.md` Bug Class #42: "Lambda + async_create_task in HA Scheduler Callback" — full taxonomy entry with shape, v4.6.15 example, sibling pattern (v4.6.3.1), prevention rules, and detection methods.

### Imports added

- `notification_manager.py`: `from functools import partial`

---

## Review Documentation

Three parallel reviewers (Tier 2-DB scale per user-coined rule), each framing a different risk axis:

| Reviewer | Framing | Verdict | Doc |
|---|---|---|---|
| A | Correctness + thread-safety integrity | PASS WITH FIXES (2 CRITICAL, 1 HIGH) | `docs/reviews/code-review/v4.6.15_threadsafety_review_a.md` |
| B | Async + lifecycle + race conditions | SAFE TO COMMIT (0 CRITICAL / HIGH) | `docs/reviews/code-review/v4.6.15_threadsafety_review_b.md` |
| C | Test fixture authority + regression prevention | COMMIT WITH CAUTION (2 CRITICAL, 2 HIGH) | `docs/reviews/code-review/v4.6.15_threadsafety_review_c.md` |

**Convergent CRITICAL findings (both addressed in this release):**
- `_handle_db_ready` conversion to `add_job` (A1 + C2) — applied
- AST regression test (C1 + C3) — added

**Disputed-but-resolved:**
- A2 hypothetical `functools.partial + iscoroutinefunction` Python compat concern — Reviewer B verified HA's `get_hassjob_callable_job_type()` explicitly unwraps partials before introspection. Safe regardless of Python version. Documented with a comment on the import line.

**Deferred (out of scope per all 3 reviewers, tracked as tech debt):**
- 4 other `async_create_task(...)` calls in sensor.py inside `_async_refresh` finally-blocks (lines 10924, 11091, 11363, 11849) — all verified on event loop, pre-existing Bug Class #19 (untracked tasks) cleanup candidates.
- Test harness migration to `pytest-homeassistant-custom-component` to enable HA's frame helper in tests — multi-cycle infrastructure project.

---

## Acceptance Criteria

### Static (verified pre-deploy)

- ✅ AST regression test `test_no_lambda_wrapping_async_create_task` passes (0 matches in URA tree)
- ✅ `_async_refresh` methods on the 3 telemetry sensor classes accept `_now=None`
- ✅ `_fire_digest` accepts `_now=None`
- ✅ `functools.partial` import present in notification_manager.py
- ✅ Both `_handle_db_ready` closures use `hass.add_job` (not `async_create_task`)
- ✅ Bug Class #42 entry present in `docs/QUALITY_CONTEXT.md`
- ✅ 141/141 targeted tests on touched code pass (NotificationManager + v4.6.13 telemetry)

### Live (verify post-deploy)

- **Verify (Review D — Tier 2-DB live validation):** Within 5 min of HA restart, `ha_get_logs(source="system", search="universal_room_automation", level="WARNING")` shows **zero** entries matching `"Detected that custom integration 'universal_room_automation' calls hass.async_create_task from a thread other than the event loop"`. Compare to pre-deploy baseline of 18 warnings per boot.
- **Verify:** `sensor.ura_coordinator_manager_override_frequency`, `sensor.ura_coordinator_manager_compliance_rate`, `sensor.ura_db_size_mb` all populate within 5 min of restart (no longer `unknown` from never-running refresh).
- **Verify:** No HA-core crashes for 1+ hour post-deploy.
- **Verify:** No `RuntimeWarning: coroutine '_async_refresh' was never awaited` in subsequent logs.
- **Live (if anyone has digest delivery enabled):** Verify morning + evening digests fire at their scheduled times. Validates the `functools.partial` path end-to-end.

---

## Risk Register

| Risk | Mitigation |
|---|---|
| Envoy still in maintenance → EC validation fails → repair issue persists | Unrelated to this fix. EC was disabled during maintenance via storage edit; this release re-enables EC's option flag and the validation path is unchanged. |
| `_handle_db_ready` add_job behavior change | `add_job` is HA's documented thread-safe API. Both `add_job` and `async_create_task` end up scheduling the coroutine on the event loop; `add_job` adds the `call_soon_threadsafe` step that's needed if the caller is off-loop. No behavioral change in the on-loop case. |
| Python 3.12+ `functools.partial` inspect compatibility | Verified by Reviewer B: HA's `get_hassjob_callable_job_type()` explicitly unwraps partials BEFORE checking `iscoroutinefunction`. Safe on Python 3.9 through 3.14+. |
| Hidden 6th anti-pattern site I missed | AST regression test (in CI from this release forward) catches any future or past instance. Codebase audit at fix time found zero remaining. |

---

## Sibling Issues Encountered During Investigation

The Envoy maintenance + HA hangs that prompted this investigation also surfaced (out of scope for this release):
- v4.6.3.2 EC startup race still produces "deferred restore exhausted retries" warnings when Envoy is unreachable (per `memory/project_ec_startup_race_evidence.md` — boot timeline now captured)
- HVAC zone state file (`.storage/universal_room_automation.hvac_zone_state`) was the last successful URA write before each hang — timestamp signal worth instrumenting

These are tracked separately; v4.6.15 scope is exclusively the thread-safety bug class.

---

## Files Changed

- `custom_components/universal_room_automation/sensor.py`
- `custom_components/universal_room_automation/domain_coordinators/notification_manager.py`
- `docs/QUALITY_CONTEXT.md`
- `quality/tests/test_v4615_threadsafety.py` (NEW)
- `docs/reviews/code-review/v4.6.15_threadsafety_review_a.md` (NEW)
- `docs/reviews/code-review/v4.6.15_threadsafety_review_b.md` (NEW)
- `docs/reviews/code-review/v4.6.15_threadsafety_review_c.md` (NEW)
- `docs/readmes/README_v4.6.15.md` (NEW — this file)

**Diff stat (pre-review → working tree):** 103 insertions / 17 deletions across 3 modified files + 5 new files.

---

## Tags

- `pre-review-v4.6.15-threadsafety` — baseline before fix-up edits
- `post-review-v4.6.15-threadsafety` — after fix-ups, before commit/deploy
