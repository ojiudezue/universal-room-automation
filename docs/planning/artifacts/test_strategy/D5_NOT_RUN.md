# D5 — NOT RUN (deliberately skipped)

D5 requires a full-suite invocation and carries an explicit operator-approval gate. It was **not
executed** in this cycle. No full-suite run was performed by any deliverable here; the in-suite
baseline came entirely from the eight full-suite captures already on disk from the prior session.

## What the other deliverables turned up for free

These are observations, not a diagnosis. D5 remains open.

**1. Exactly one file in 425 hangs when run ALONE.**

```
quality/tests/test_memory_compactor.py
  tests complete: "1 failed, 22 passed, 6 warnings in 1.15s"
  process:        NEVER EXITS
  reproduced:     twice — >600 s and >180 s, two independent sweeps, clean __pycache__ both times
```

The tests finish in 1.15 s and then the interpreter refuses to exit. That is the teardown wedge
signature, reproducible in about two seconds of test time, in one file, with no full-suite run
required. Whatever non-daemon thread / unclosed loop / uncancelled task is responsible, it is
reachable from this single module. **If D5 is approved, start here, not with a full-suite run.**

Note the asymmetry, which is itself a clue: the same file does NOT wedge inside the full suite —
the eight captured full-suite runs all completed in 223-283 s, with this file contributing exactly
one ordinary FAILED line. Something a sibling installs makes the wedge go away.

**2. A second, independent hang was produced by a D4 mutation.**

Neutering the write-queue enqueue at `custom_components/universal_room_automation/database.py:421`
makes `quality/tests/test_database_resilience.py` hang instead of fail (>120 s, no exit) — an
awaited future that nothing ever resolves. Whether the two hangs share a mechanism is unknown.

**3. The suite contains 25 tests that spawn nested `pytest` subprocesses and mutate production
source while running.**

`quality/tests/test_chatter_wire_in.py` implements source-mutation drills as ordinary suite tests,
via a `_SourceMutation` context manager plus `subprocess` pytest invocations
(`test_drill_1` … `test_drill_25`). Every full-suite run therefore forks child pytest processes and
edits files under `custom_components/` mid-run. This is a plausible contributor to both the wedge
and to the "source-mutating test without guaranteed restore" hazard the parent card records: a
suite killed mid-drill leaves production source modified. **Not proven to be the wedge cause** — it
is a candidate that a D5 investigation must rule in or out before looking further afield.
