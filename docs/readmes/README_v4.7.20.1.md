# v4.7.20.1 — Hotfix: UnboundLocalError on `async_dispatcher_send` (Bug Class #34 recurrence)

**Tier 1 hotfix.** Fixes a regression introduced by v4.7.20's fan-noise B-H2
fix-up. No feature change. 1 production file + 1 regression test.

## The bug

v4.7.20 hoisted `async_dispatcher_send` to a module-top import in
`presence.py` but left bare **function-local** imports of the same name inside
`_run_inference` and `_handle_face_arrival`. In Python a function-local import
re-scopes that name as a method-local for the **entire** function body. The
`_run_inference` local import lives in the **conditional** house-state-change
branch, so on every tick *without* a state change it never executes — leaving the
textually-later uses unbound:

- `SIGNAL_PRESENCE_ENTITIES_UPDATE` dispatch (pre-existing, ~line 4760)
- the new fan-interference gate dispatch (~line 4613)

Both raised `UnboundLocalError: cannot access local variable
'async_dispatcher_send'` — **~174 times in the first hour** post-deploy (every
tick), confirmed from the HA error-log traceback.

This is a recurrence of **Bug Class #34** (Function-Local Import Shadows
Module-Level Import). It evaded the original v4.5.11 AST guard because that guard
only flags names used *before the import line*; here the uses are textually after
the import, but the import is conditional — line order ≠ execution order.

## Impact

- Presence sensors lost their proactive attribute re-render push (they still
  updated on HA's natural re-query, so this was degraded, not dead).
- The Layer-2 fan-gate signal (`SIGNAL_FAN_INTERFERENCE_GATE_FIRED`) never
  actually dispatched.
- **No safety/HVAC/compliance impact.** The v4.7.20 truth-preserving invariant
  held — zero `_room_occupied=False but provenance=True` violations (H2 clean in
  live validation).

## The fix

Removed both redundant bare function-local imports; the module-top import
(`presence.py:68`) is now the sole binding for `async_dispatcher_send`. The
aliased `... as _dispatcher_send` site is untouched (it binds a different local
name and cannot shadow the global).

Added `quality/tests/test_v4_7_20_1_dispatcher_unbound_regression.py`: an AST
guard that forbids any bare function-local re-import of `async_dispatcher_send`
anywhere in `presence.py`, plus a module-top-presence assertion. Proven
non-hollow — it flags both pre-fix offenders on the v4.7.20 source.

## Files changed

| File | What |
|---|---|
| `domain_coordinators/presence.py` | Removed bare function-local `import async_dispatcher_send` in `_run_inference` (4443) and `_handle_face_arrival` (3223); replaced with comments documenting the trap. |
| `quality/tests/test_v4_7_20_1_dispatcher_unbound_regression.py` | New AST regression guard (2 tests). |
| `docs/QUALITY_CONTEXT.md` | Bug Class #34 updated with the v4.7.20 recurrence + the conditional-import blind-spot in the original detection heuristic. |

## Migration

None. Pure code fix. No config, no DB, no entity changes.

## Live validation (post-restart)

1. **Zero UnboundLocalError:** no `error_log` line matching
   `UnboundLocalError.*async_dispatcher_send` after restart.
2. **Gate dispatch clean:** no `SIGNAL_FAN_INTERFERENCE_GATE_FIRED dispatch
   failed` and no `failed to dispatch SIGNAL_PRESENCE_ENTITIES_UPDATE` warnings.
3. **Gate still silent + truth-preserving** (v4.7.20 H2 unchanged): no
   `_room_occupied=False but` violation.

## Acceptance

```yaml
version: v4.7.20.1
hypotheses:
  - id: H1
    name: no_unbound_local_error
    description: |
      The async_dispatcher_send UnboundLocalError is gone. No error_log line
      matching the regression signature after restart. Covers the
      SIGNAL_PRESENCE_ENTITIES_UPDATE dispatch and the fan-gate dispatch.
    query:
      kind: ha_log_count
      source: error_log
      search: "UnboundLocalError"
      hours_back: 1
    expected:
      condition: "<="
      value: 0
    window:
      first_check_after: 1h
      confirm_after: 24h
      alert_if_violated_after: 72h
  - id: H2
    name: no_dispatch_failed_warnings
    description: |
      Neither the presence-entities-update dispatch nor the fan-gate dispatch
      logs a "dispatch failed" / "failed to dispatch" warning post-fix.
    query:
      kind: ha_log_count
      source: error_log
      search: "failed to dispatch SIGNAL_PRESENCE_ENTITIES_UPDATE"
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

HACS install v4.7.20 — restores the regression (UnboundLocalError every tick).
Prefer rolling forward. The fix is in-memory-neutral; no state migration either
direction.
