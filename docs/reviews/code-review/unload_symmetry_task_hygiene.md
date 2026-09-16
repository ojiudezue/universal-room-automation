# Code Review — UNLOAD-SYMMETRY-TASK-HYGIENE-1

**Cycle:** setup/unload symmetry + tracked background tasks (reload-safety hardening)
**Branch:** `feature/unload-symmetry-task-hygiene`
**Reviewed:** 2026-09-16 · two framing-disjoint passes + consolidated fix-up
**Version:** unshipped at time of review (stamp at deploy)

## The build

Captured 5 previously-discarded `async_call_later` unsub return values and drained
them on teardown. Sites: `transit_validator.py:1072,1111` (EgressDirectionTracker);
`__init__.py:1618` (desync retry); `coordinator_diagnostics.py:369`
(ComplianceTracker.schedule_check → new async_teardown wired into HVACCoordinator +
CoordinatorManager); `hvac.py:1205` (egress-gate 60s release). Prior audit
(`audit_listener_cleanup.py`) had already reduced a false "294 vs 163" text-grep
panic to this bounded set of 5 real discarded-unsub sites.

## Findings

| ID | Sev | Bug class | Site | Status |
|----|-----|-----------|------|--------|
| A1/B2 | MEDIUM | **Unbounded retention / introduced leak** | `coordinator_diagnostics.py:381`, `transit_validator.py:1075,1119` | **FIXED** |
| B1 | MEDIUM | **Non-working fix + dead defensive branch** | `__init__.py:1618-1633` | **FIXED** |
| A2 | MEDIUM→LOW | **Suppression without discharge** | `coordinator_diagnostics.py:380` | **FIXED (documented as deliberate)** |
| A/B | LOW | **Hollow test anchor (Bug Class #62)** | test sites 5 + egress-gate | **FIXED (behavioral) / relabeled (shape guard)** |
| A/B | LOW | Dead `except` (API cannot raise) | `__init__.py:1626` | **FIXED (removed)** |

### The headline finding — the fix introduced a worse leak than it fixed

Both framings converged here independently. The naive hygiene fix — append each
one-shot unsub to a list, drain at teardown — is correct for *once-per-instance*
schedulers but wrong for *per-event* ones. Three sites are per-event (per governed
command; per camera detection). A fired `TimerHandle` does not null its callback,
so each retained entry pins `hass` + the `HassJob` + the captured closure; and the
CM's shared `ComplianceTracker` is never recreated across room-entry reloads, so
its list grows monotonically for the process lifetime (URA runs weeks between
restarts). **Resolution:** self-removal-on-fire idiom (`list.remove(unsub)` in the
callback, guarded) at the 3 per-event sites; append-then-drain kept only at the 2
genuinely once-per-instance sites (`hvac.py` egress-gate, `__init__` desync retry).

### B1 — the fix didn't close its window

`ConfigEntry.async_on_unload` just appends and cannot raise, so the `except` branch
was dead. Worse, the desync check runs in a parked background task; the on-unload
drain completes and returns *before* the task resumes and re-registers the retry, so
the retry re-registered into an already-drained list. **Resolution:** gate on
`entry.state is ConfigEntryState.LOADED` (register to cancel-on-unload) else cancel
inline, and re-check `entry.state` inside `_retry` before it acts.

### A2 — undischarged compliance drop

Teardown cancels pending `_delayed_check` calls, dropping up to 120s of
compliance-verification DB rows with no re-schedule (relevant against the ~5×/night
CM reload storm). Reviewer B judged the drop *correct* (the tracker resolves state
live; firing against a torn-down coordinator would be strictly worse), so
**Resolution:** documented as a deliberate, bounded drop (≤1 row per active governed
command per reload inside the 120s window) in the teardown docstring + a README note
at ship — per *suppression-needs-a-discharge*, an intentional non-discharge must be
recorded, not silent.

## What passed (cleared with evidence)

Double-teardown idempotency (drain-copy-then-clear; cancel is a no-op), two-owner
routing (HVAC's private tracker vs the CM's shared one are distinct instances, each
torn down by exactly its owner), partial-setup teardown, order-vs-re-setup (teardown
is synchronous, no interleave window), restart-safety (no persisted state touched),
symmetry completeness (grep confirmed both ComplianceTracker owners wired, no new
asymmetry). `__init__.py:1618` and `hvac.py:1210` were correct as originally built.

## Summary statistics

| Severity | Found | Fixed | Deferred |
|----------|-------|-------|----------|
| CRITICAL | 0 | 0 | 0 |
| HIGH | 0 | 0 | 0 |
| MEDIUM | 3 | 3 | 0 |
| LOW | 2 | 2 | 0 |

## Bug-class frequency (recurring)

- **Hollow test anchor (Bug Class #62)** — recurs; two sites this cycle. Self-caught
  by the reviewers, fixed to behavioral where feasible, the one out-of-scope site
  relabeled honestly as a shape guard.
- **Introduced-leak-during-hygiene** — new shape worth naming: a cleanup fix whose
  data structure choice (unbounded list on a hot path) is itself a leak. Candidate
  for QUALITY_CONTEXT if it recurs.

## Post-fix verification

12 tests (up from 6), neuter drills confirm each fix is load-bearing (strip → the
specific test goes red → restore → green). Targeted run 12 passed; audit tool 0
discarded / 286 retained. **Pending before ship:** the orchestrator's full-suite
name-diff (serialised behind the EC-SOC builder), then deploy.
