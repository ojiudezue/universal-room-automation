---
description: Run the URA test suite + baseline-failure-count comparison via ura-validator agent. Args = the pre-review tag (e.g., pre-review-v4.6.10).
---

Use the `ura-validator` agent to run the URA test suite and compare against the baseline.

**Pre-review baseline tag:** $ARGUMENTS

**Required output:**

1. Run new cycle-specific tests in isolation:
   ```bash
   PYTHONPATH=quality python3 -m pytest quality/tests/test_v<version>_<topic>.py -v
   ```
   Report pass/fail count.

2. Run full bulk suite on the current (feature) branch:
   ```bash
   PYTHONPATH=quality python3 -m pytest quality/tests/ 2>&1 | tail -3
   ```
   Record: total passed / failed / errors.

3. Stash + checkout baseline, run same suite, restore:
   ```bash
   git stash -u
   git checkout $ARGUMENTS -- custom_components quality
   PYTHONPATH=quality python3 -m pytest quality/tests/ 2>&1 | tail -3
   git checkout - -- custom_components quality
   git stash pop
   ```
   Record baseline: total passed / failed / errors.

4. Compute delta: `(post-build failures) - (baseline failures)`. **Zero new failures = green.** Any positive delta = regression list with first 3 tracebacks per failure.

**Critical: do NOT edit code.** If failures exist, report them and hand back to `ura-builder`.

**Report format:**
- Baseline: X passed / Y failed / Z errors at tag `<args>`
- Post-build: X passed / Y failed / Z errors on `<branch>`
- Delta: +N new failures (or zero)
- New cycle tests: pass count
- Verdict: GREEN / REGRESSION
