# Setup/Unload Symmetry — Deferred Findings

Findings from Reviews A and B that were **deliberately deferred** out of
this fix-up pass. Each entry states WHY and where the issue is tracked.

Per the operator's `feedback_fix_lows_in_cycle` directive, only genuine
non-issues / out-of-scope items are deferred; reasonable LOWs that
landed in 1-30 LoC were fixed in-cycle.

---

## B-HIGH-2 — Eager-start propagation, NON-dispatcher sites

**Status:** Resolved for the four dispatcher `_on_*` handlers
(`_on_house_state_signal`, `_on_energy_constraint`, `_on_safety_hazard`,
`_on_security_event`) by passing `eager_start=False` to their
`entry.async_create_background_task(...)` calls.

**Deferred for the remaining sites** (`coordinator.py:928-934, 1029-1033,
1045-1049, 1909-1922, 1934-1939, 2293-2306`): these are not invoked from
synchronous `@callback` dispatcher entry points. They run either inside
already-async update paths or inside coroutines, so a same-task raise
inside the eager-start prefix cannot leak back into a dispatcher tick.
Tracked under operational hygiene; revisit if Bug Class #19 patterns
recur in these surfaces.

---

## B-MED-1 — Service handlers vs popped `hass.data[DOMAIN]`

**Status:** SAFE — grep verified.

All 10 service handlers (`handle_set_house_state`, `handle_clear_override`,
`handle_test_safety_hazard`, `handle_security_arm`, `handle_security_disarm`,
`handle_authorize_guest`, `handle_add_expected_arrival`,
`handle_acknowledge_notification`, `handle_test_notification`,
`handle_test_inbound`) use the defensive
`hass.data.get(DOMAIN, {}).get("<key>")` pattern (verified at
`__init__.py:3142, 3161, 3205, 3250, 3261, 3274, 3287, 3352, 3362, 3392`).
No handler does `hass.data[DOMAIN][...]`. The microsecond window between
`pop()` and service-teardown is harmless — handlers return cleanly when
the manager is `None`. No fix required.

---

## B-MED-2 — Background task cancellation cleanup tracebacks

`asyncio.sleep` cancellations in `_delayed_exit_verify` and activity-logger
chains may log `CancelledError` tracebacks on entry unload. Cosmetic
log noise only; no behavioral regression. Defer to a future operational
hygiene pass — wrap the cancel-prone awaits in `try/except CancelledError`.
Tracked under operational hygiene.

---

## B-MED-4 — Panel-path literals pinned by raw-substring test

The current `TestPanelsTornDownOnUnload` tests assert the panel-path
literals (`"ura-dashboard"`, `"ura-dashboard-v3"`) appear anywhere in
the source. A future refactor moving them to a `const.py` constant
would break the test without breaking behavior. Defer: ship-of-Theseus
risk on a frontend feature that the v4.7.x stack hasn't touched.
Re-scope when the panel path moves to `const.py` for any reason.

---

## B-LOW-1 — Multi-INTEGRATION-entry hypothetical

URA is documented single-INTEGRATION-entry by `single_user_no_backcompat`
memo. The DOMAIN-scoped service registration would race if a second
INTEGRATION entry ever appeared, but no roadmap item proposes that.
Defer; one-line comment at the registration site can land alongside any
future multi-entry work.

---

## B-LOW-2 — Reload task-name uses `entry.entry_id` (stable)

Reviewer flagged for noting; the post-fix `_async_update_listener` no
longer interpolates anything (untracked task has no name) — moot.

---

## A-LOW-3, A-LOW-5, A-LOW-6

Reviewer A flagged these as observations / non-defects:

- **A-LOW-3** — closure binding of `_ha_frontend`: verified safe
  (Python interns module references in `sys.modules`).
- **A-LOW-5** — panel-registration order vs `_LOGGER.info`: re-read
  confirmed the order is fine.
- **A-LOW-6** — `_REPO_ROOT = parents[2]`: project-wide test pattern,
  not a regression introduced by this cycle.

No action required.
