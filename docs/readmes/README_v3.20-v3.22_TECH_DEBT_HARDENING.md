# v3.20.0–v3.22.0 — Tech Debt & Hardening (6 Cycles)

**Period:** 2026-03-31 to 2026-04-01
**Versions:** v3.20.0, v3.20.2, v3.21.0, v3.21.1, v3.21.2, v3.22.0
**New tests:** 307 (from ~1,243 to ~1,550)
**Reviews:** 12 adversarial reviews (2 per feature cycle, 1 per hotfix)
**Findings:** 2 CRITICAL, ~15 HIGH, ~25 MEDIUM fixed; ~12 LOW deferred
**Plan:** `docs/PLANNING_v3.20_TECH_DEBT_HARDENING.md`

---

## What This Was

A comprehensive 6-cycle hardening effort addressing 53 findings from a full
codebase review (7 CRITICAL, 18 HIGH, 25 MEDIUM, 3 LOW). The room automation
core — the foundation of URA — had significant restart resilience gaps,
orphaned toggle switches, flaky cover automation, coordinator signal wiring
gaps, stub entities returning placeholder data, and limited observability.

All CRITICAL and HIGH findings were addressed. 15 stub entities were removed
and documented for reimplementation in v4.0.0 Bayesian Intelligence.

---

## Cycle Summary

### Cycle A: Room Resilience (v3.20.0)
**Risk:** HIGH | **Review:** 2 reviews | **Tests:** +66

The foundation. Room-level automation now survives HA restarts without losing
state, and all 5 per-room toggle switches actually work.

- **RestoreEntity** on OccupiedBinarySensor persists critical coordinator state
  (session time, occupancy state, failsafe, cover dedup dates)
- **room_state DB table** as crash-resilience backup with fallback restore path
- **ManualModeSwitch** wired — ON disables ALL room automation
- **ClimateAutomationSwitch** wired — gates climate/fan actions
- **CoverAutomationSwitch** wired — gates cover open/close
- **OverrideOccupied/Vacant** switches with RestoreEntity, mutual exclusion,
  and correct `_last_occupied_state` tracking for transitions
- Cover entity validation (`_get_available_covers`), retry on failure,
  mode validation, safe sunrise default (don't open when location unknown)
- Listener cleanup on rapid reload prevents accumulation
- Shutdown save on unload for fresh DB state

### Cycle B: Config Flow UX (v3.20.2)
**Risk:** MEDIUM | **Review:** 1 review | **Tests:** +29

User-facing config flow improvements. All changes in config_flow.py.

- Automation chaining available during initial room setup (was options-only)
- AI rules available during initial room setup (was options-only)
- `automation_behavior` options step (15 fields) split into `options_lighting`
  (6 fields) + `options_covers` (10 fields)
- Conditional fields: shared space details hidden unless toggle enabled,
  notification overrides hidden unless toggle enabled (options flow only)
- AI rule person selector changed from TextSelector to EntitySelector(domain="person")

### Cycle C: Stub Cleanup (v3.20.2)
**Risk:** LOW | **Review:** 1 review | **Tests:** +22

Removed 15 dead entities that returned hardcoded placeholder values.
All documented in `docs/DEFERRED_TO_BAYESIAN.md` for v4.0.0 reimplementation.

- 2 non-functional buttons removed (ClearDatabase, OptimizeNow)
- 11 stub sensors removed (OccupancyPercentageToday, EnergyWasteIdle, etc.)
- 2 stub binary sensors removed (OccupancyAnomaly, EnergyAnomaly)
- Dead signal `SIGNAL_COMFORT_REQUEST` + `ComfortRequest` dataclass removed
- Orphaned `STATE_OCCUPANCY_PCT_TODAY` constant removed

### Cycle D: Coordinator Hardening (v3.21.0)
**Risk:** HIGH | **Review:** 2 reviews | **Tests:** +44

All 7 domain coordinators hardened for restart resilience and startup ordering.

- Energy DB restore: 11 sequential methods wrapped in 15s timeout
- Presence→HVAC startup ordering via `asyncio.Event` (10s timeout fallback)
- Safety sensor recovery: unavailable→available re-evaluates hazard with
  current reading (was only clearing rate history)
- NM alert/cooldown/dedup state persisted via RestoreEntity on diagnostics sensor
  (COOLDOWN reset to IDLE on restore; dual-path guard against DB overwrite)
- Security expected arrival expiry verified already working (false positive)
- Energy observation mode switch gets RestoreEntity
- New `AiAutomationSwitch` per room — gates AI rules + chaining (safety/security
  always fire regardless; respects ManualMode)

### Cycle E: Observability (v3.21.1 + v3.21.2)
**Risk:** LOW-MEDIUM | **Review:** 2 reviews | **Tests:** +76

Full transparency into coordinator decision-making.

- **3 observation mode toggles:** Safety, Security, Presence coordinators can
  now run in observation mode (sensors compute, no actions/signals fired)
- **HVAC Arrester Status sensor:** monitoring/detected/grace/acting with
  override counts, planned action, AC reset status, per-zone detail
- **NM Alert State sensor:** idle/alerting/cooldown/repeating with cooldown
  remaining, suppression status
- **Energy Envoy Status sensor:** online/offline/stale/initializing with
  reading age and offline count
- **Safety Active Cooldowns sensor:** per-hazard cooldown timers
- **Security Authorized Guests sensor:** guest list with expiry, expected arrivals
- Hotfix v3.21.2: Security observation mode now gates signal dispatch + side effects;
  Envoy sensor defaults to "initializing" instead of "online" when unchecked

### Cycle F: Signal Wiring (v3.22.0)
**Risk:** MEDIUM-HIGH | **Review:** 2 reviews | **Tests:** +70

Cross-coordinator intelligence via configurable signal responses.

- **8 configurable toggles** (all default OFF) in Coordinator Manager options flow
- `_get_signal_config()` helper on BaseCoordinator for runtime config reads
- **SIGNAL_SAFETY_HAZARD** consumers:
  - HVAC: smoke/CO critical → stop fans; freeze risk → emergency heat
  - Security: smoke/fire critical → unlock egress doors
  - Energy: any critical → emergency max load shed
  - Music: any critical → stop all playback
- **SIGNAL_PERSON_ARRIVING** consumers:
  - Security: add to expected arrivals (5-min window)
  - Music: start music in person's zone (OFF by default)
- **SIGNAL_SECURITY_EVENT** consumer:
  - Music: critical event → stop all playback
- All disabled responses log what they WOULD have done (dry-run visibility)
- All handlers check observation mode and skip when active

---

## After-Cycle Report

### What Went Well

1. **Parallelization worked.** Cycles A, B, C ran in parallel (different file sets).
   D, E, F serialized correctly (dependency chain). Total wall-clock time was
   significantly less than serial execution would have been.

2. **2-review protocol caught real bugs.** Both CRITICALs in Cycle F (hazard type
   string mismatches making safety responses dead code) were caught by Review 2.
   If we'd shipped without review, CO detection fan-stop and freeze emergency
   heat would have been completely non-functional on a safety-critical path.

3. **Live validation caught deployment issues.** v3.21.1 deployed before Review 1
   completed — the review found a HIGH (Security observation mode incomplete gating)
   that was shipped as v3.21.2 hotfix within minutes.

4. **Tests provided regression confidence.** 307 new tests meant we could fix review
   findings aggressively without fear of breaking existing functionality. The 57
   pre-existing test failures were identified and isolated immediately.

5. **Worktree isolation** for B and C prevented merge conflicts with the main branch.
   Both completed in background while A was being reviewed.

### What Went Wrong

1. **Stale worktree base.** Both Cycle B and C worktrees branched from v3.13.2
   (7 months old) instead of current develop. This was caught in review — the
   actual changes were correct but couldn't be merged directly. Had to re-apply
   changes on current codebase. **Lesson:** Verify worktree base branch before
   starting implementation agents.

2. **Cycle B accidentally bundled into C's deploy.** deploy.sh stages ALL `*.py`
   files via glob, so Cycle B's config_flow.py changes (uncommitted) got swept
   into v3.20.2 alongside Cycle C's changes. The code was reviewed and tested,
   but the version naming was wrong (v3.20.1 was skipped). **Lesson:** Either
   commit Cycle B separately before running deploy.sh for C, or stash unrelated
   changes.

3. **Review 1 for Cycle E completed after deploy.** We deployed v3.21.1 with
   only Review 2's findings fixed. Review 1 found a HIGH issue that needed a
   hotfix (v3.21.2). **Lesson:** Wait for both reviews before deploying feature
   cycles, even if LOW-MEDIUM risk.

4. **Enum string mismatches (Cycle F CRITICALs).** The HVAC safety handler used
   informal names ("co", "freeze") instead of the actual HazardType enum values
   ("carbon_monoxide", "freeze_risk"). **Lesson:** Always cross-reference enum
   definitions when writing handlers for typed signals. Add a new bug class for this.

5. **Observation mode gates were incomplete across multiple cycles.** Three
   separate review findings (safety signal before gate, security side effects
   before gate, BLE dispatch bypassing gate) showed that observation mode gating
   is easy to miss when signals are dispatched from multiple locations.
   **Lesson:** Observation mode should be checked at the signal DISPATCH site,
   not just the handler. Add a new bug class for this.

### Deferred Items (Task #10)

| Item | Source | Why Deferred |
|------|--------|-------------|
| UTC vs local timezone in room_state table | Cycle A R1 | Cosmetic, no functional impact |
| Override switch slug DRY violation | Cycle A R1 | Cosmetic |
| Cooldown sensor uses 3600s for all severities | Cycle E R1 | Needs severity stored in dedup cache |
| Switch restore race (pre-existing pattern) | Cycle E R1+R2 | Architectural, affects all obs mode switches |
| Envoy sensor no signal listener | Cycle E R2 | Consistent with existing energy sensors |
| Music Following untracked _stop_all_playback tasks | Cycle F R1+R2 | Needs _pending_tasks infrastructure |
| Emergency load shed no recovery path | Cycle F R2 | Needs hazard-clear signal subscription |
| CO hazard should unlock egress doors | Cycle F R1 | Design decision, not a bug |
| Signal handler unused local imports | Cycle F R1 | Cosmetic |
| No dry-run log when observation_mode suppresses | Cycle F R1 | Polish |
| Disabled coordinators still react to signals | Cycle F R1 | Needs _enabled check in all handlers |
| Config entry iteration on every signal call | Cycle F R2 | Performance, not correctness |

### New Bug Classes Identified

1. **Enum Value Mismatch in Signal Handlers** — Using informal names instead of
   actual enum `.value` strings when handling typed signal payloads. Caught as
   2 CRITICALs in Cycle F. Added to QUALITY_CONTEXT.md as Bug Class #22.

2. **Incomplete Observation Mode Gating** — Checking observation mode at the
   handler level but missing dispatch sites in other files, or checking after
   side effects have already fired. Caught in Cycles E and F across 3 files.
   Added to QUALITY_CONTEXT.md as Bug Class #23.

---

## Entity Inventory Change

| Category | Before (v3.19.1) | After (v3.22.0) | Delta |
|----------|-------------------|-------------------|-------|
| Per-room switches | 8 | 9 (+AiAutomation) | +1/room |
| Coordinator switches | 8 | 11 (+Safety/Security/Presence obs mode) | +3 |
| Coordinator sensors | ~25 | 30 (+Arrester/NM Alert/Envoy/Cooldowns/Guests) | +5 |
| Stub sensors removed | 11 | 0 | -11/room |
| Stub binary sensors removed | 2 | 0 | -2/room |
| Stub buttons removed | 2 | 0 | -2/room |
| **Net per room** | ~90 | **~76** | **-14** |

---

## What's Next

**v4.0.0: Bayesian Predictive Intelligence** — the capstone feature.
See `docs/ROADMAP_v11.md` for the full plan. The stub entities removed in
Cycle C are documented in `docs/DEFERRED_TO_BAYESIAN.md` with their data
source requirements and v4.0.0 milestone assignments (B1-B4).
