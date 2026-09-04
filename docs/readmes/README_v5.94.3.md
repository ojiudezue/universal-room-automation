# v5.94.3 — Shell-cleanup identifier-unpack hotfix (the removal finally runs)

**Card:** `DEVICE-SHELL-CLEANUP-1` (fix-forward tail)
**Tier:** 1 (hotfix — one-line safe-iteration fix, root cause confirmed by live traceback). PATCH.
**Merge:** develop.

## Problem (root cause, confirmed by live system-log traceback)

v5.94.1/.2's shell-removal **never ran** — not because of parent-entry resolution (my earlier two
diagnoses were wrong; the CM entry's `integration_entry_id` was set to the parent all along). The
helper iterates **every device in the registry** and unpacked identifiers as
`for (dom, ident) in device.identifiers`, assuming 2-tuples. Other integrations register
**3-element identifiers** — `bond` = `('bond', <hub>, <device>)`, `homekit` bridges =
`('homekit', <id>, 'homekit.bridge')` — so the FIRST such non-URA device raised
`ValueError: too many values to unpack (expected 2, got 3)`, aborting the whole cleanup **before it
reached any URA shell**. The call-site `try/except` swallowed it as "guard raised (non-fatal)". The
unit tests passed only because the fake registry used clean 2-tuples. (The D-NEST *sweep* was
unaffected — it already used safe `identifier[0]` indexing — which is why the nesting fix landed but
the shell removal didn't.)

HA permits arbitrary-length identifier tuples, so 2-tuple unpacking over the whole registry is unsafe.

## Solution

`_devices.py:async_cleanup_parent_entry_shells` — iterate without tuple-unpacking, indexing
defensively (`len(identifier) >= 2 and identifier[0] == DOMAIN and identifier[1] in _STATIC_CHILD_IDS`),
mirroring the sweep's existing identifier handling. No change to the predicate/guards — a real
populated CM-owned coordinator device remains structurally unselectable.

## Verification

Regression test added (`test_v5_94_1_shell_cleanup_survives_three_tuple_identifiers`): a fake
registry with a `bond`-style 3-tuple device alongside a real shell — asserts no exception and the
shell is removed. **Mutation-verified**: reverting to the unsafe unpack turns it RED with the exact
`ValueError`. Full-suite name-diff vs clean develop (same `-p no:cacheprovider` invocation) =
**identical failure set, zero regressions** (the 69 vs 62 count is pre-existing order-sensitive
flake surfaced by the no-cache ordering, not this change). py_compile clean.

### Acceptance
- **Live:** post-restart the 3 empty parent-entry shells (`coordinator_manager` df3b,
  `security_coordinator` 29c9, `music_following_coordinator` 3e9b) are **removed**; exactly ONE of
  each coordinator device remains; Whole House stands alone on the parent entry; real
  CM (~60) / Security (~21) / Music (~10) entities intact; no "Error adding entity None".

## References
- [`docs/architecture/DEVICE_TREE.md`](../architecture/DEVICE_TREE.md) · [`docs/reviews/DEVICE_ENTITY_DEFRAG_POSTMORTEM.md`](../reviews/DEVICE_ENTITY_DEFRAG_POSTMORTEM.md) (this arm-length/mis-diagnosis chain is a postmortem entry).
