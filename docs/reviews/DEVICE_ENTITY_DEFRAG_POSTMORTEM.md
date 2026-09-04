# Postmortem — device/entity de-fragmentation arc (v5.92.3 → v5.94.1)

**Date:** 2026-09-03/04. **Scope:** the arc that fixed URA's split-owned coordinator devices, the
HA 2026.9 `via_device` outage, and the empty-shell cleanup. Written so future device-registry work
does not re-learn these the hard way. Companion to [`docs/architecture/DEVICE_TREE.md`](../../architecture/DEVICE_TREE.md).

## Timeline

| Version | What shipped |
|---|---|
| v5.92.3 | **Emergency hotfix** — stripped 109 declarative `DeviceInfo(via_device=…)` lines that HA 2026.9 turned into a hard `RuntimeError`, taking all coordinator entities unavailable (live outage). |
| v5.94.0 | De-fragmentation: forward all coordinator platforms from the CM entry only; nest the tree imperatively; delete the dead `coordinator_music_following` records; menu-icon normalization. Tier 3. |
| v5.94.1 | Fix-forward: remove the 3 empty duplicate coordinator device *shells* left on the parent entry; fix the D-NEST sweep's same-identifier resolution; A-MED ordering + B1/B2/B3. Tier 2-DB. |

## Mistakes made (and the fix / lesson for each)

1. **Declarative `via_device` survived into HA 2026.9.** `DeviceInfo(via_device=…)` was deprecated
   long before it became a hard error; URA still used it, so the 2026.9 upgrade caused a house-wide
   outage. **Fix:** imperative `dr.async_update_device(via_device_id=…)` only; a test asserts zero
   declarative `via_device`. **Lesson:** track HA deprecations proactively; a deprecation warning is
   a future outage.

2. **Split ownership was invisible until it manifested as duplicate *devices*.** Coordinator
   entities were historically forwarded from BOTH the INTEGRATION and CM entries → two device
   records per identifier. **Fix:** forward coordinator platforms from the CM entry only. **Lesson:**
   two config entries writing the same `DeviceInfo` identifier silently fork into two device records
   (HA keys by `device.id`, not identifier). Own each device from exactly one entry.

3. **Re-homing entities does NOT remove the old device.** v5.94.0 moved the entities but left 3
   empty shells on the parent entry (HA only clears `config_entries` on full entry removal).
   **Fix (v5.94.1):** an explicit guarded shell-removal pass. **Lesson:** whenever you move entities
   to a different config entry, you MUST explicitly delete the vacated device records — HA won't.

4. **`async_get_device(identifiers=…)` is unsafe when identifiers are duplicated.** The identifier
   index is last-writer-wins and may point at the wrong (empty) record. The D-NEST sweep used it and
   mis-nested 6 coordinators under the empty shell; the initial dead-device deletion targeted the
   wrong identifier and silently no-op'd. **Fix:** iterate `dev_reg.devices.values()` (a `list()`
   snapshot), select by `device.id`, prefer the populated/CM-owned device. **Lesson:** never resolve
   a device by identifier when duplicates are possible.

5. **Ordering bug: cleanup ran after `get_or_create`.** The CM `async_get_or_create` resolved
   through the last-writer-wins index and could re-bind the shell to the CM entry, making "exactly
   one CM device" a coin-flip. **Fix (A-MED):** run the shell cleanup *before* `get_or_create`.
   **Lesson:** device-registry mutations are order-sensitive; do cleanup before any get_or_create
   that reads the shared index.

6. **Removing a shell un-indexes the shared identifier → duplicate-on-reload risk.** HA's
   `__delitem__` deletes the shared `_identifiers` slot unconditionally; the survivor stayed
   un-indexed unless something else happened to re-`__setitem__` it, so a same-session reload could
   mint a duplicate CM device. **Fix (B2):** explicitly re-index survivors after removal. **Lesson:**
   after removing one of two same-identifier records, re-index the survivor deterministically — don't
   rely on a side effect.

7. **Hollow test anchors (repeat offense).** Two build rounds shipped "mutation anchors" that were
   `re.search` over source text — they stayed GREEN when the code body was neutered. Caught only by
   the orchestrator's mandatory independent mutation drill. **Fix:** behavioural tests that *execute*
   the coroutine (reuse the `_FakeDevReg` / `test_v460` / `test_v462` harness). **Lesson:** a source
   grep is not a test; prove RED-on-neuter by mutating the actual line, and the orchestrator must
   re-run the mutation itself, never trust the builder's "goes RED" claim.

8. **Inert deliverable (D3).** The "model first-writer-wins race" fix routed through
   `BaseCoordinator.device_info`, but `BaseCoordinator` is not an HA `Entity`, so that property is
   never read — the race was never reachable. **Fix:** kept the routing as harmless future-proofing;
   stopped presenting it as a race fix; deleted a test docstring citing a nonexistent test.
   **Lesson:** verify a "fix" is on a reachable path before claiming it fixes anything.

## What went RIGHT (keep doing)

- **Tier-3 four-framing review + mandatory orchestrator independent verification** caught, in order:
  the 5 completeness leaks (Review D), the hollow anchors (Review C), the wrong deletion identifier
  (live-registry ground truth), and the *still-hollow* round-1 anchors (orchestrator re-run). Each
  layer caught something the previous missed.
- **Live-registry validation as the acceptance oracle.** The device tree is directly inspectable via
  `ha_get_device`; the #1 post-restart check (exactly one CM/Security/Music device, correct nesting)
  is what proved the fix — not a log string.
- **Rollback readiness before each deploy** (tags + prior release on GitHub for HACS downgrade).

## Open / carded follow-ups
- **LOW (pre-existing):** the zone-slug orphan cleanup at `__init__.py:~4066` calls
  `async_remove_device` with **no 0-entity guard** — a zone renamed while its device still holds
  entities would be deleted outright. Card separately; same guarded-removal pattern as v5.94.1.

## References
- [`docs/architecture/DEVICE_TREE.md`](../../architecture/DEVICE_TREE.md) — the final architecture + HA mechanics.
- [`docs/planning/DECISION_LOG_device_entity_cycle_2026_09_03.md`](../planning/DECISION_LOG_device_entity_cycle_2026_09_03.md) — 24 adjudications.
- HA dev docs: [Device registry](https://developers.home-assistant.io/docs/device_registry_index/) ·
  [Config entries](https://developers.home-assistant.io/docs/config_entries_index/) ·
  [`DeviceInfo` / entity](https://developers.home-assistant.io/docs/core/entity/#deviceinfo).
