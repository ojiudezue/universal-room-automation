---
description: Implement a URA cycle via ura-builder agent. Args = the planning doc filename or cycle name.
---

Use the `ura-builder` agent to implement the cycle described in the planning doc.

**Cycle / planning doc:** $ARGUMENTS

**Pre-conditions the agent must check:**
1. Branch exists for this cycle (`feature/v<version>-<topic>`) and is currently checked out
2. Pre-review tag exists (`pre-review-v<version>`) — if not, set it before any code changes
3. Planning doc has been read end-to-end

**Build constraints (per CLAUDE.md):**
- Use `dt_util.now()` / `dt_util.parse_datetime()`, never raw `datetime` (Bug Class #21)
- Module-top imports unless circular risk justifies function-local (Bug Class #34)
- Every `async_dispatcher_connect` wrapped in `async_on_remove`
- Use `entry.async_create_background_task` for new background tasks (Bug Class #19)
- `strings.json` and `translations/en.json` MUST be kept in sync byte-for-byte

**Before declaring done:**
1. Run `PYTHONPATH=quality python3 -m pytest quality/tests/ -v` — confirm new tests pass + bulk failure count matches `pre-review-v<version>` baseline
2. `git log feature/v<version>-<topic> --oneline -5` includes the build commit
3. `git status` shows zero modified/staged

**Report:** files changed (LoC per file), test pass count, baseline-diff number, deviations from spec.

Note: After build, dispatch `ura-validator` for baseline-failure-count comparison BEFORE dispatching `ura-reviewer`. The validator runs the comparison; the reviewer reads the result.
