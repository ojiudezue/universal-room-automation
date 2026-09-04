# v5.94.0 — Device/entity de-fragmentation + device-tree nesting + menu icons

**Cards:** `DEVICE-ENTITY-REORG-1` (hub), `HA-2026-9-VIA-DEVICE-COMPAT-1`, `MENU-CONSISTENCY-1` (icon fold-in)
**Tier:** 3 (operator-elevated) — 4 framing-disjoint reviews (validator + Review D completeness + Review C test-authority + orchestrator independent mutation-verify), 2 fix-up rounds, live-registry ground truth. MINOR — the nested device tree is a new operator-facing structure.
**Merge:** `feature/device-entity-defrag` → develop.

## Problem

URA's coordinator devices were **split-owned across two config entries**, which the live registry showed as **duplicate device records sharing one identifier** — two `URA: Coordinator Manager` devices (50 + 10 entities), two `URA: Security Coordinator`, and the dead `coordinator_music_following` records lingering. The Coordinator Manager device wasn't even nested under Whole House (`via_device_id=null`). Separately, HA 2026.9 turned the deprecated declarative `DeviceInfo(via_device=…)` into a hard `RuntimeError` — which took the whole coordinator entity set unavailable in the live outage that forced this cycle.

## Solution

- **De-fragment (D1):** all coordinator platforms forward from the CM entry only; the parent/INTEGRATION entry hosts only Whole House. All 211 coordinator entities now single-entry-owned (independent AST re-enumeration: 211/211 under CM, 0 under INTEGRATION). Entity `unique_id`s are byte-identical to pre-cycle (0 new `_2`; the `..._person_oji udezue_...` literal-space id preserved verbatim).
- **Nest the tree (D-NEST):** imperative `dr.async_update_device(via_device_id=…)` — coordinators → CM → Whole House; zones + rooms → Whole House. Reload-independent (per-room / per-zone / per-coordinator reload preserved). Cold-boot sweep via `async_at_started` with a bounded re-arm (survives concurrent/late entry setup) and an INV-4 WARN trip-wire.
- **2026.9 fix:** zero declarative `via_device` anywhere (109 lines stripped in the v5.92.3 hotfix; permanently gated by test on this cycle).
- **Dead-device cleanup (D1 removal):** removes the dead `(DOMAIN, "coordinator_music_following")` records (both of them — iterates the registry, 0-entity guarded). Corrected from the initial build's no-op identifier (`music_following`) after live-registry ground truth.
- **Menu icons (fold-in):** consistent glyphs across config/options-flow menus — iconed `setup_zone`/`add_zone`/`signal_responses` + the config-flow `init_chain_*`/`init_ai_*` menus to match their options-flow twins; unified `✓`→`✅`.

## Scope split / not done

- **Zone instance-picker → menu** is a deliberate Tier-2 fast-follow (`MENU-ZONE-PICKER-1`) — it threads the v4.7.5 raw-vs-canonical-zone contract + a guarding AST test, so it was kept out of this device-tree Tier-3 cycle. Zones still use a `SelectSelector` form to pick an instance (the known odd-one-out).
- **D2 full one-DeviceInfo-per-identity consolidation** (100+ inline sites) parked as `DEVICE-INFO-HELPER-CONSOLIDATION-1` (adjudication #9). This cycle consolidated only the genuine duplicate-authoring (music_following, notification_manager) + the base.py routing.
- **D3 reframed:** `BaseCoordinator` is not an HA `Entity`, so its `device_info` was never read — the "model race" it nominally fixed was never reachable. The base.py routing is kept as harmless future-proofing, NOT presented as a race fix.

## Reviews

Validator CLEAN (merged-tree name-diff, 0 new failures). Review D (completeness): 5 leaks — D-LEAK-1 (HIGH, per-person setup one-shot with no discharge → 8 entities dropped on slow-DB boot), D-LEAK-2/3 (sweep re-arm, runtime-room stamp), D-LEAK-4 (dead-device deletion targeted a nonexistent identifier — CONFIRMED via live registry), D-LEAK-5 (unsubs not on unload). Review C (test authority): the delicate D1b split + wire-ins were grep-anchored, not behavioural; D3 inert. Two fix-up rounds. **Orchestrator independent mutation-verify** caught round-1's "behavioural" anchors were STILL hollow (green on full coroutine neuter) → forced round-2. Final independent verify: CM-hosted sensor coroutine neuter → 4 tests RED; binary coroutine neuter → 1 RED; D-NEST wire-in delete-call-keep-import → RED; INV-NEST zero `via_device`; full suite at the 62-failing develop baseline (0 net-new). Decision log: 24 adjudications (`docs/planning/DECISION_LOG_device_entity_cycle_2026_09_03.md`).

### Falsifiable invariants (Tier-3)
- **INV-DEFRAG:** every entity's `entity_id`+`unique_id` byte-identical; 0 new `_2`; count preserved; no coordinator entity split-owned; no orphans.
- **INV-NEST:** every coordinator device `via_device_id → CM → Whole House`; zones/rooms → Whole House; zero declarative `via_device`.

## Pre-deploy gate

py_compile clean; no conflict markers; full-suite name-diff vs develop = 62 failed (baseline, 0 net-new); INV-NEST grep clean; branch merged current with develop.

## Live Validation — post-restart battery (to be recorded below as `Validated <date>`)

Pre-deploy live baseline (v5.93.1): **2** `coordinator_manager` devices, **2** `security_coordinator`, **2** dead `coordinator_music_following`, CM `via_device_id=null`.

- **A. Device tree** (registry + Devices UI): exactly ONE `coordinator_manager` device, ONE `security_coordinator`, ZERO `coordinator_music_following`; coordinators nested → CM → Whole House; zones+rooms → Whole House.
- **B. Entity integrity:** count preserved (~4626), 0 new `_2`, the 8 per-person sensors present, no coordinator entity unavailable/orphaned.
- **C. Menus exercised** (browser, read-only — navigate + observe, no submit): options-flow `init` menu icons incl. `📶 Signal Responses`; a coordinator submenu opens + backs out; config add-entry `entry_type_select` (`🚪`/`🗂️`/`⚙️`) + `post_integration` (`🗂️`/`✅`) then cancel; no config-flow traceback. (Zone-picker still a form — expected, `MENU-ZONE-PICKER-1`.)
- **D. Per-entry reload:** reload one room + one CM entry individually → scoped, no sibling cascade, tree re-nests.
- **E. Logs:** clean boot, no "Error adding entity None", no via_device RuntimeError, no config-flow tracebacks.
