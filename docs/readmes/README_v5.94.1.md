# v5.94.1 — Device-shell cleanup (finish the de-frag: remove empty duplicate coordinator devices + fix the nesting sweep)

**Card:** `DEVICE-SHELL-CLEANUP-1`
**Tier:** 2-DB (2 framing-disjoint reviews A+B + orchestrator independent mutation-verify) — fix-forward for v5.94.0. PATCH.
**Merge:** `feature/device-shell-cleanup` → develop.

## Problem

v5.94.0 correctly re-homed all coordinator *entities* onto the Coordinator-Manager (CM) config
entry, but left three residues (confirmed on the live registry post-restart):
1. **Three empty duplicate device records** on the parent/INTEGRATION entry —
   `coordinator_manager`, `security_coordinator`, `music_following_coordinator`, 0 entities each.
   HA never removes a device when its last entity moves to a *different* config entry, so they
   linger forever.
2. **A `via_device` mis-wire:** the D-NEST sweep resolves parents by identifier last-writer-wins, so
   with two same-identifier devices it nested the real coordinators under the *empty shell* and left
   the real CM device unparented.

Nothing was functionally broken (all coordinators live) — the device *tree* was cluttered and
mis-nested.

## Solution

- **Guarded shell removal** (`_devices.py:async_cleanup_parent_entry_shells`, called in the CM
  branch **before** the CM `async_get_or_create` and before the stamp): iterate
  `dev_reg.devices.values()` (never `async_get_device` — the shared index is last-writer-wins),
  remove a device by `device.id` **only** when all three hold — a coordinator identifier, `0`
  entities, and `config_entries == {parent_entry_id}` (sole parent-owner), with a belt-and-suspenders
  "not CM-owned" skip. Removal via `async_update_device(remove_config_entry_id=parent)` (auto-deletes
  when sole entry). **The real, populated, CM-owned coordinator devices are structurally
  unselectable** (they fail the sole-parent guard AND the 0-entity guard).
- **Sweep tie-break** (`async_stamp_via_device_tree`): never index an empty parent-owned shell as a
  parent, so `coordinator_manager` resolves to the real CM device → coordinators nest under the real
  CM, and the CM nests under Whole House.
- **A-MED:** cleanup runs *before* the CM `get_or_create` → "exactly one CM device" is deterministic.
- **B2:** explicit survivor re-index after removal → a same-session CM reload cannot mint a duplicate.
- **B1:** cleanup gated on the `URA_DEVICE_TREE_STAMPING_ENABLED` kill-switch; sweep-schedule hoisted
  out of the stamp's `try`.
- **B3:** sweep unsubs/retry-handles torn down on unload.

## Reviews

Tier 2-DB: **Review A (predicate safety) SHIP** — could not construct any legal repro that deletes a
real device; every real coordinator excluded by ≥2 independent guards, Whole House by the identifier
filter. **Review B (lifecycle) SHIP** — the dict-mutation-during-iteration crash risk was confirmed
NOT present (`list()` snapshot). 4 MEDIUMs (A-MED ordering, B1, B2, B3) all fixed in-cycle.
**Orchestrator independent mutation-verify:** neutering the sole-parent guard → `skips_dual_owned`
RED; the sweep tie-break → `stamp_prefers_populated` RED; the B2 re-index → `b2_reindex` +
`amed_order` RED. Full suite at the 62-failing develop baseline, 0 net-new.

### Acceptance criteria
- **Verify:** the deletion cannot remove a device with entities, a CM-owned device, Whole House, or a
  room/zone device (guarded three ways; behaviourally tested for all three coordinator identifiers).
- **Live:** post-restart the device registry shows exactly ONE `coordinator_manager` device (real CM,
  ~60 entities, nested under Whole House), ONE `security_coordinator`, ZERO
  `coordinator_music_following` / duplicate shells; coordinators nested under the real CM; Whole House
  stands alone on the parent entry as the tree root; real Security (~21) and Music (~10) intact.

## Documentation package (this release)
- **`docs/architecture/DEVICE_TREE.md`** — NEW canonical device/entity architecture: the annotated
  final tree (mermaid + ASCII), the config-entry-ownership vs `via_device`-nesting distinction, and
  the HA mechanics it relies on (2026.9 `via_device` RuntimeError, same-identifier index, entry↔device
  association), with links to recent HA dev docs.
- **`docs/reviews/DEVICE_ENTITY_DEFRAG_POSTMORTEM.md`** — NEW: the 8 mistakes made across
  v5.92.3→v5.94.1 and their fixes/lessons, to inform future device-registry work.
- CLAUDE.md now points at both from the "Before Making Changes" section.

## Pre-deploy gate
py_compile clean; no conflict markers; full-suite name-diff vs develop = 62 (baseline, 0 net-new);
branch merged current with develop; rollback tag `rollback-pre-5.94.1` (v5.94.0 = downgrade target).

## Live Validation — post-restart (to be recorded below as `Validated <date>`)
Pre-fix live baseline (v5.94.0): 2 `coordinator_manager` devices (one empty shell), 2
`security_coordinator`, 2 `music_following_coordinator`, real CM `via_device_id=null`, 6 coordinators
nested under the empty shell.
- **A.** Exactly one of each coordinator device; zero empty shells; parent entry owns only Whole House.
- **B.** Real CM ~60 entities + `via_device_id` = Whole House; coordinators' `via_device_id` = real CM.
- **C.** Real Security (~21) and Music (~10) entities intact; entity count preserved; 0 new `_2`.
- **D.** Clean boot, no "Error adding entity None", no via_device RuntimeError, no config-flow tracebacks.
