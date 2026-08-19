# URA v5.84.1 — HOTFIX: presence startup UnboundLocalError (v5.84.0 regression)

**Incident + fix-forward.** v5.84.0 (fan-recheck deadlock fix) shipped a regression: the presence
coordinator threw at startup and `_run_inference("startup")` failed.

## The bug

```
UnboundLocalError: cannot access local variable 'CONF_ENTRY_TYPE'
  presence.py:6955 in _run_inference:  if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ROOM:
```

`_run_inference` has a *pre-existing* function-local `from ..const import ... CONF_ENTRY_TYPE`
inside an `if _cm_entry is None:` branch (~:5944). Importing `CONF_ENTRY_TYPE` there makes it a
**function-local for the entire method**, so the module-level import (line 44) is shadowed. v5.84.0's
D3 fan-recheck-loop refactor **moved** the `CONF_ENTRY_TYPE` reference at ~:6955 to a control-flow
position reached *before* that branch on the startup path → the local is accessed unbound.

Latent shadow (always present) + the D3 refactor moving the reference = the regression.

## The fix

Remove `CONF_ENTRY_TYPE` from the function-local import at ~:5944 (it is already imported at module
level, :44). The whole function now resolves `CONF_ENTRY_TYPE` to the module-level name — un-shadowed.
One-line change; `ENTRY_TYPE_COORDINATOR_MANAGER` stays locally imported (used only at its callsite,
not shadow-broken). Verified: no remaining local `CONF_ENTRY_TYPE` assignment in `_run_inference`;
sibling names (`ENTRY_TYPE_ROOM`, `ENTRY_TYPE_COORDINATOR_MANAGER`) not similarly shadowed; py_compile
clean.

## Why it wasn't caught pre-deploy

The v5.84.0 fan-fix behavioral proof was **live-only** (Review C: the real `UniversalRoomCoordinator`
can't be constructed in-suite — v5.8.0 territory), so an in-suite test never exercised the real
`_run_inference` startup path. This is exactly the coordinator-integration test gap the
`TEST-STRATEGY-REARCH-1` investigation is scoped to close (a real-coord harness would have caught it
at author time). Follow-up carded: a lint/audit for function-local const imports that shadow
module-level names (`SHADOW-IMPORT-AUDIT`).

## Acceptance criteria — live

- **L1:** boot clean, **zero URA ERROR** (specifically no `UnboundLocalError` / "Failed to start
  coordinator presence"); `presence_house_state` available and inferring.
- The v5.84.0 fan-recheck validation (L2: `fan_recheck_state` eval_count climbs, a real vacate) then
  proceeds on a fan-ghost episode.

## Live Validation

### Validated 2026-08-19 (~10:31 CT, clean v5.84.1 restart) — residents home

| # | Criterion | Result | Evidence |
|---|---|---|---|
| L1 | Boot clean, zero URA ERROR | **PASS** | system_log ERROR count for universal_room_automation: 0 (the UnboundLocalError / "Failed to start coordinator presence" is GONE) |
| L1 | Presence coordinator STARTED + inferring | **PASS** | `sensor.ura_presence_coordinator_presence_house_state` = `arriving`, FRESH `last_changed 10:31:34` (dwell 33s = genuine fresh boot), `boot_settle_done: true`, `boot_settle_release_reason: real_input`, census 2, tracked 4 |

**Note:** the first v5.84.1 restart did not reboot the process (fix on disk but not loaded); a second clean restart loaded it — hence the two restarts in the log. The v5.84.0 fan-recheck L2 (eval_count climb + a real vacate) remains organic-pending on a fan-ghost episode.

**Incident closed:** presence startup crash fixed; presence inferring cleanly on v5.84.1.
