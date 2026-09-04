# v5.94.2 — Shell-cleanup parent-entry resolution hotfix

**Card:** `DEVICE-SHELL-CLEANUP-1` (fix-forward tail)
**Tier:** 1 (hotfix — single resolution fix, safety predicate unchanged & already reviewed). PATCH.
**Merge:** develop.

## Problem

v5.94.1 fixed the device-tree **nesting** live (all coordinators now nest under the real CM, CM
under Whole House — validated), but the **empty-shell removal silently no-op'd**: the call site
resolved `parent_entry_id = entry.data.get(CONF_INTEGRATION_ENTRY_ID)` from the CM entry's data, and
that field is stamped only at migration-*create* time (`_ensure_coordinator_manager_entry` ~:968).
The live CM entry (`source=coordinator_manager_migration`) predates the stamping, so its persisted
data lacks the field → `parent_entry_id` was `None` → `async_cleanup_parent_entry_shells` returned 0
without touching the 3 empty shells (`coordinator_manager`, `security_coordinator`,
`music_following_coordinator`, 0 entities each). Confirmed live: no cleanup log line (early return),
sweep unaffected (it doesn't need `parent_entry_id`).

## Solution

At the call site (`__init__.py` CM branch), when `entry.data.get(CONF_INTEGRATION_ENTRY_ID)` is
absent, **resolve the single `ENTRY_TYPE_INTEGRATION` entry directly** (reusing the existing pattern
at `__init__.py:4705`). The removal **predicate and all safety guards are unchanged** — still
iterate `values()`, remove by `device.id`, require 0 entities + sole-parent-ownership + not-CM-owned;
a real populated CM-owned coordinator device remains structurally unselectable.

## Reviews / verification

Predicate + guards already A+B-reviewed (SHIP) and orchestrator-mutation-verified in v5.94.1; this
hotfix changes only the parent-id lookup (a verbatim reuse of the proven `:4705` INTEGRATION-entry
finder). py_compile clean; 66 device-architecture tests pass; full suite at the 62-failing develop
baseline. The resolution fix's proof is the live post-restart check below.

### Acceptance
- **Live:** post-restart the 3 empty shells are gone; exactly ONE `coordinator_manager` device (real
  CM, ~60 entities, nested under Whole House), ONE `security_coordinator`, ONE
  `music_following_coordinator`; Whole House stands alone on the parent entry; real Security (~21) /
  Music (~10) entities intact; no "Error adding entity None".

## References
- [`docs/architecture/DEVICE_TREE.md`](../architecture/DEVICE_TREE.md) · [`docs/reviews/DEVICE_ENTITY_DEFRAG_POSTMORTEM.md`](../reviews/DEVICE_ENTITY_DEFRAG_POSTMORTEM.md)
