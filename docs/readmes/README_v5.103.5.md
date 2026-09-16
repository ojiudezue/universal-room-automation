# v5.103.5 — Reload-safety: capture and release 5 leaked one-shot timers

Tech-debt hardening, **no behavior change on the happy path**. Five
`async_call_later` timers were scheduling callbacks whose cancel-handle was
discarded, so on integration reload/unload those timers fired against
half-torn-down objects. Now each is captured and released.

## What changed

Five discarded one-shot unsubs captured + released on teardown:

| Site | Owner |
|---|---|
| `transit_validator.py` (×2) | `EgressDirectionTracker` egress state/count listeners |
| `__init__.py` | room-name desync-notify retry |
| `coordinator_diagnostics.py` | `ComplianceTracker.schedule_check` (new `async_teardown`, wired into both HVACCoordinator + CoordinatorManager) |
| `hvac.py` | egress-gate 60s release |

For the **per-event** sites (fire per command / per detection) the callback
now **self-removes** its own unsub on fire, so the retention list stays bounded
for process lifetime. For the **once-per-instance** sites, append-then-drain on
teardown.

## Reviewed — two framing-disjoint passes, both caught a real issue

The naive version of this fix **introduced a worse leak than it fixed** — an
unbounded list on hot paths — and one site's fix didn't actually close its
window. Both were found in review and fixed in-cycle (no CRITICAL/HIGH):

- **Self-removal on fire** replaced accumulate-then-drain at the 3 per-event sites.
- `__init__.py` retry now gates on `entry.state is ConfigEntryState.LOADED`
  (cancel inline otherwise) and re-checks entry state inside the retry; the dead
  `except` (the API cannot raise) was removed.

Full record: `docs/reviews/code-review/unload_symmetry_task_hygiene.md`.

### One deliberate, documented behavior note

`ComplianceTracker.async_teardown` **cancels pending compliance-verification
checks** (the `COMPLIANCE_CHECK_DELAY` = 120s window). On a reload within 120s of
a governed command, that command's compliance-verification row is not written —
bounded to ≤1 row per active governed command per reload. This is **intentional**:
the tracker resolves state live, so firing against a torn-down coordinator would
be strictly worse. Recorded here rather than left as a silent side effect.

## Evidence

- 12 tests (up from 6), each fix neuter-drilled (strip → the specific test goes
  red → restore → green). 4 sites that previously survived neutering now have
  real behavioral anchors.
- **Name-diff vs develop: byte-identical** — 305 pre-existing failing names on
  both sides (HA-version drift under pinned phcc), **zero new, zero fixed**,
  +12 passes = the new test file. Run under `.venv-ha`.

## Live validation

- [ ] No new URA ERROR after restart; integration loads clean at v5.103.5.
- [ ] No functional change expected anywhere (hygiene only) — rooms/zones/energy
      behave exactly as v5.103.4.
- [ ] Discriminating negative: a normal config-entry reload produces no
      `async_call_later`-related exceptions in the log (the pre-fix failure mode).
