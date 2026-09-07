# Code Review — Integration-Reload Comprehensive (Tier 1 + Tier 2)

**Cycle:** INTEGRATION-RELOAD-COMPREHENSIVE (Tier 3 protocol). Plan:
`docs/planning/PLANNING_integration_reload_comprehensive_2026_09.md` (rev-2).
**Branches merged to develop:** Tier 1 (`6c04fc095`, `29acf897a`), Tier 2
(`6c4fa6e25` → reworked `80198a9c3`). Develop tip `80198a9c3`.
**Reviews:** 2 framing-disjoint PLAN reviews (pre-build) + 4 framing-disjoint
BUILD reviews (A local / B lifecycle / C test-authority / D adversarial) +
orchestrator independent mutation-verify.

## What shipped
Extend `INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS` from 3 → **16 keys**, so an
integration-entry options save that changes only fresh-read keys applies
in-place instead of triggering the ~5-min singleton-bootstrap reload → watchdog
outage. All 13 added keys are **path-(a) fresh-read** (re-read
`{**entry.data, **entry.options}` per decision tick): 4 Tier-1 census keys
(cross_validation, ble_cancel_enabled, known_face_guests,
egress_identity_failsafe_strict) + 9 Tier-2 perimeter keys (vehicle_hours ×2,
enrichment ×6, exterior_snapshot_offset_s). Plus D2.5: success-gated snapshot
advance in `_dispatch_integration_key_signals` (a swallowed dispatch retains
the pre-save value so it re-fires, never silently lost).

## Findings

| ID | Sev | Framing | Status | Bug class |
|---|---|---|---|---|
| PLAN CRIT-1 | CRITICAL | plan-completeness/build-pred | FIXED (excluded) | mis-classification |
| PLAN completeness | HIGH | plan-completeness | FIXED (all 45 keys classified) | one-missed-site (#53) |
| B1 | CRITICAL | lifecycle | FIXED (handler deleted) | in-flight state corruption |
| B2 / A1 / D-CRIT-1 | CRITICAL | lifecycle/local/adversarial | FIXED (handler deleted) | untracked bg tasks + supersession-missing |
| A2 | HIGH | local | FIXED (handler deleted) | unreachable-subscribe |
| A3 / D-HIGH-1 | HIGH | local/adversarial | FIXED for new keys (dropped); pre-existing carded | computed-but-not-consumed (#53) / stale data source (#7) |
| C-CRIT-1 | CRITICAL | test-authority | FIXED (handler deleted; new tests drive production) | hollow test anchor (#62) |
| C-HIGH-1 | HIGH | test-authority | FIXED (handler deleted) | hollow test anchor (#62) |
| B3/A6/A7/C-MED-1/D-MED-1 | HIGH-LOW | multiple | FIXED (handler deleted) | untracked tasks / leaks |
| A4 | MEDIUM | local | REFUTED by D (live: keys stripped by migration, pops are no-ops) | — |
| C-LOW-1 | LOW | test-authority | FIXED (drill-convenience `or set()` retained but is correct; comment cleaned) | test-shaped production |

### The pivotal outcome
The Tier-2 build first implemented the perimeter discharge as **preserve →
`await async_setup()` → restore**. All four framings independently condemned it:
- **B/A/D:** re-running `async_setup` + per-key signal dispatch spawned N
  concurrent handler tasks on an ordinary multi-key perimeter save, orphaning
  the sweep timer / Frigate listener / dispatcher subs (uncancellable by
  teardown) and, via a resurrected dedup flag, **permanently muting a camera**
  until restart — both reachable on default config.
- **C:** the entire handler was **behaviorally untested** — all 6 perimeter
  tests were AST *shape* assertions; a `return` at the top of the handler left
  the suite green (Bug Class #62), and 10 of 14 preserve-set members had no
  test.

Root cause: the handler was built for the **camera-list** keys (which genuinely
cache), but those keys are **UNSAFE-structural** (`camera_manager.async_discover`
rebuild consumed on the live occupancy path) and cannot be suppressed at all,
while the 9 non-camera perimeter keys are **fresh-read** and need no handler.
Fix: **delete the entire handler + `SIGNAL_URA_PERIMETER_CONFIG_CHANGED`**
(perimeter_alert.py reverted byte-identical to pre-cycle), keep the 9 fresh-read
keys as allowlist-only, drop the 2 camera keys to the reload path.

## Orchestrator independent verification
- Branch scope: only `__init__.py` + `test_reload_watchdog_hazard.py` changed;
  `perimeter_alert.py`/`const.py` reverted; the unrelated `energy_pool_owners.py`
  working-tree edit NOT committed. Confirmed.
- Allowlist = 16 members, no dupes, no camera/hours keys. Confirmed via AST.
- New tests drive production (`_async_update_listener` via the AST-exec harness),
  not AST shape. Confirmed.
- Independent mutation: deleting the frozenset member
  `CONF_PERIMETER_ENRICHMENT_ENABLED` REDs its parametrised suppress test by
  name; other 8 params pass. Confirmed.
- 33/33 `test_reload_watchdog_hazard.py`; sibling perimeter suites clean
  (`test_perimeter_burst_demotion` 8 pre-existing `/media` env fails, name-diff 0).

## Deferred / carded
- **D-HIGH-1 pre-existing:** `CONF_CAMERA_PERSON_ENTITIES` (allowlisted since the
  v1 2026-08-15 seed) leaves `CameraIntegrationManager` discovery maps stale on a
  live occupancy path when an indoor camera is added. Predates this cycle; not
  introduced here. Carded `INTEGRATION-CAMERA-DISCOVER-STALE-1`. Proper fix is a
  camera-list discharge that re-runs `async_discover`, or the config-subentries
  migration (Tier-3 D3.a).
- **Process miss:** the 4 build-reviewers were pointed at the builder's live
  worktree, then the builder was resumed for the fix-up in that same worktree
  while reviewer C was still running — a worktree-isolation violation. C detected
  the collision, isolated itself, and reported clean; A/B/D had finished before
  the fix-up dispatch. Lesson: reviewers get read-only/own worktrees; never
  resume a builder in a worktree a reviewer is live in.

## QUALITY_CONTEXT recommendation
Reinforces #62 (hollow test anchor — AST shape ≠ behavioral test; a `return` at
the top of the unit must fail a test) and #53 (computed/cached-but-not-consumed —
a cached setup-time consumer of an allowlisted key is a stale-value leak). No new
class.
