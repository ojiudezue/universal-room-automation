# Review: EV-TRIPWIRE-TESTS-ORDER-DEPENDENT-1 (framing C, Tier 1, test-only)

Branch under review: `fix/ev-tripwire-order-dependence` (6ecfda17c, b30aca17e), cherry-picked cleanly onto
develop 295057da7 as scratch branch `review/ev-tripwire-order` (a8cd6f9f0, 01f257f1a). Only
`quality/tests/test_ec_ev_toggle_tripwire.py` changes.

Run mechanics: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=quality .venv-ha/bin/python -m pytest -q -p no:randomly
-p no:cacheprovider`, with all repo `__pycache__` dirs removed before each run. "Prefix" means the 118 sorted
`quality/tests/test_*.py` files up to and including the tripwire file, which matches the card.

## Reproduction

| Run | Result |
|---|---|
| develop test file, isolated | 11 passed |
| develop test file, 118-file prefix | 29 failed / 3513 passed. Tripwire failures: `test_d_next_day_resets_latch`, `test_d2_...fires_nm` |
| fixed test file, isolated | 11 passed |
| fixed test file, 118-file prefix | 27 failed / 3515 passed. No tripwire failures; the other 27 are unrelated failures already present in the prefix |

This prefix order did not make `test_g_kill_switch_disables` fail on develop. I added a synthetic polluter that
re-imports `energy_const` and stubs `dt_util` without `as_local`. With that polluter the old test_g still
passes, but only by accident: production raises AttributeError, the bare `except` at
energy_write_verify.py:1376 swallows it, and no alert fires. The fixed test_g resolves `energy_const` the same
way production does (energy_write_verify.py:1320), so it no longer depends on that accident.

## Mutation drills (production source, one at a time, each restored, `git status` clean afterwards)

| Site | Mutation | Isolated | Prefix |
|---|---|---|---|
| energy_write_verify.py:1340 local-day latch | `as_local(now_utc).date()` changed to `now_utc.date()` (UTC) | test_d2 RED (1 failed) | test_d2 RED |
| energy_write_verify.py:1324 kill switch | `if max_n <= 0` changed to `if False` | test_g RED (1 failed) | test_g RED |
| energy_write_verify.py:1340 day rollover | date key replaced by the constant `'fixed'` | test_d + test_d2 RED (2 failed) | test_d + test_d2 RED |

None of the mutations left its target test green, so the shim does not make the tests hollow.

## Leak / masking check

- `_pin_local_tz` (test file, new helper) only calls `monkeypatch.setattr(_wv, "dt_util", shim)`, so it is
  undone at teardown. Nothing is mutated at module level.
- `_live_ec()` is a read-only lookup. The patch goes through `monkeypatch.setattr`, which is scoped to the test.
- The shim implements only `as_local` and `utcnow`. Under the pinned tests, the method calls `dt_util.utcnow`
  only when `now` is None (line 1328), and the tests always inject `now`. The day computation still runs
  through production's own `dt_util.as_local` call site, which is why mutations a and c are detected.
- Production's call-time `from . import energy_const` is correct behaviour: under HA the package module is a
  single long-lived object, and sibling *test* files are what swap it. The fix does not hide a production
  defect.

## Findings

- LOW (observation, no change required): tests a and c and the wire-in test do not pin `dt_util`. They are
  green in the real prefix order. A harsher polluter than any found in the suite (a `dt_util` stub with no
  `as_local`) turns them red, because of the same swallowed-exception path. If a future sibling stub drops
  `as_local`, apply `_pin_local_tz` to them as well. Bug class: test fixture order-dependence.

## Verdict: SHIP
