---
name: ura-optimizer-autonomy-campaign
description: Decision-gated runbook for advancing URA's Optimization Coordinator from L1 Shadow to L2+ actuation without repeating the v5.0.0-v5.2.1 DB write-flood rollback. Triggers — "promote the optimizer", "enable L2 / reversible optimizer", "raise optimizer autonomy", "shadow accuracy ready", "kill switch optimizer", "why isn't the optimizer doing anything", or touching optimization.py's actuation / persist / boot-storm-skip / shadow-accuracy / CONF_OPTIMIZER_* knobs. Enforces Tier 2-DB minimum, write-volume regression test, pre/post row-rate snapshot, in-code rollback tripwires, no soak-watching.
---

# URA Optimizer Autonomy Campaign

Executable, decision-gated runbook for advancing the URA Optimization Coordinator (OC) beyond L1 Shadow **without repeating the v5.0.0-v5.2.1 DB write-flood rollback**. Written for a lone Sonnet-class session with no subagent fleet.

## When NOT to use this skill

- Deploying a version that does not touch `optimization.py`, `optimization_llm.py`, or the OC's DB tables → use `deploy` skill directly.
- Building non-OC HA features (climate, presence, energy strategy) → use `homeassistant_coding`.
- Writing a plan for an OC change without executing it → use the `ura-planner` agent (or write the plan yourself under `docs/planning/`) then return here to execute.
- General code review of an unrelated cycle → use the `ura-reviewer` agent or `code-review` skill.
- Post-feature documentation updates → use `documenter`.

This skill defers to `CLAUDE.md` for tier policy, No-Fabrication, Institutional-Context-First, and the README write-back mandate. If this skill and `CLAUDE.md` conflict, `CLAUDE.md` wins — file an issue against this skill.

---

## Ground truth snapshot (as of 2026-07-02, v5.7.2)

Re-verify with the "Provenance and maintenance" section at the bottom before trusting any of these line numbers.

### Load-bearing files

| Surface | Path | Verified line(s) |
|---|---|---|
| OC coordinator | `custom_components/universal_room_automation/domain_coordinators/optimization.py` | 3973 LoC total |
| Single actuation chokepoint | `optimization.py` `_apply_action` | 2844 |
| Batched persistence (fix-forward) | `optimization.py` `_persist_findings_batch` | 3417 |
| Boot-storm settle gate | `optimization.py` `_should_skip_for_boot_storm` | 3527 |
| One-per-cycle signal dispatch | `optimization.py` `_dispatch_findings_updated_signal` | 3470 |
| Findings cap | `optimization.py` `_cap_findings` | 3492 |
| Shadow-accuracy validator | `optimization.py` `_run_shadow_accuracy_validator` | 1067 |
| Shadow samples buffer (RAM-only, MED-2) | `optimization.py` `self._shadow_accuracy_samples` | 563 |
| Findings DAO | `custom_components/universal_room_automation/database.py` `log_findings_batch` | 5034 |
| Findings pruner | `database.py` `prune_optimization_findings` | 5150 |
| Fresh audit plan | `docs/planning/PLANNING_audit_optimization_coordinator.md` | full read required |

### Load-bearing constants (all `const.py`)

| Constant | Line | Value |
|---|---|---|
| `OPTIMIZER_LEVEL_ADVISORY` | 1561 | `"advisory"` (rank 0) |
| `OPTIMIZER_LEVEL_SHADOW` | 1562 | `"shadow"` (rank 1, DEFAULT) |
| `OPTIMIZER_LEVEL_REVERSIBLE_DEVICE` | 1563 | `"reversible_device"` (rank 2) |
| `OPTIMIZER_LEVEL_PROPOSE_CONFIG` | 1564 | `"propose_config"` (rank 3) |
| `OPTIMIZER_LEVEL_IMMEDIATE_CONFIG` | 1565 | `"immediate_config"` (rank 4) |
| `OPTIMIZER_LEVEL_UNBOUNDED` | 1566 | `"unbounded"` (rank 5) |
| `OPTIMIZER_LEVEL_RANK` | 1578 | ordering map |
| `CONF_OPTIMIZER_KILL_SWITCH` | 1589 | operator kill switch |
| `CONF_OPTIMIZER_DIMENSION_AUTONOMY` | 1590 | per-dimension level map |
| `DEFAULT_OPTIMIZER_AUTONOMY_LEVEL` | 1601 | `= OPTIMIZER_LEVEL_SHADOW` |
| `OPTIMIZER_MAX_FINDINGS_PER_CYCLE` | 1615 | 100 |
| `OPTIMIZER_BOOT_SETTLE_CYCLES` | 1621 | 3 |
| `SCAN_INTERVAL_OPTIMIZATION` | 1747 | 5 min |
| `OPTIMIZER_OUTCOME_SHADOW` | 1755 | `"shadow_dry_run"` |

### Load-bearing tests (`quality/tests/test_optimization_coordinator.py`)

| Test | Line | What it proves |
|---|---|---|
| `test_optimizer_cycle_one_db_write_under_boot_storm` | 3411 | write-flood invariant (batched persistence) |
| `test_optimizer_boot_storm_settle_skips_persistence` | 3618 | boot-storm gate suppresses cold-boot |
| `test_optimizer_boot_storm_uptime_grace_skips_first_cycle` | 3678 | uptime-grace path of the gate |
| `test_optimizer_shadow_emits_intent_no_call` | 649 | L1 fires intent, `hass.services.calls == []` |
| `test_optimizer_activity_log_shadow` | 1143 | activity-log row = `shadow_dry_run` |
| (cap enforcement) `_cap_findings` respected | 3730-3763 | `OPTIMIZER_MAX_FINDINGS_PER_CYCLE` enforced |

Suite command (from CLAUDE.md):

```
PYTHONPATH=quality python3 -m pytest quality/tests/test_optimization_coordinator.py -v
```

Full suite (for baseline-diff):

```
PYTHONPATH=quality python3 -m pytest quality/tests/ -v
```

### Fenced-off failure pattern — DO NOT RECREATE

The v5.0.0-v5.2.1 rollback was caused by **persisting findings one-by-one every cycle** (historical anchor `optimization.py:691` is stale post-fix; grep `optimization.py` for `log_findings_batch`, `_cap_findings`, `_dispatch_findings_updated_signal` for current sites) plus **Sensor-Health emitting one finding per boot-unavailable room**. Result: DB write-queue saturation → core writes starved → HA watchdog restart. The fix-forward is now load-bearing:

1. Batched persistence (1 call per tier per cycle) via `_persist_findings_batch:3417`.
2. Boot-storm gate at `_should_skip_for_boot_storm:3527`.
3. Findings cap at `_cap_findings:3492` with `OPTIMIZER_MAX_FINDINGS_PER_CYCLE=100`.
4. One `SIGNAL_OPTIMIZER_FINDING_EMITTED` per cycle at `_dispatch_findings_updated_signal:3470`.

If a proposed change removes, bypasses, or per-item-loops any of these four → **STOP the campaign.** That is the pattern that rolled back last time.

---

## The campaign — phases and gates

The campaign is a strict sequence. Do not skip forward. Each gate is a decision the operator must confirm before moving on.

```
Phase 0  Preflight: institutional context + baseline
   |
Phase 1  Fix promotion-evidence blockers (audit MEDs)  ---- Tier 2-DB
   |     (persist shadow samples, TTL bug, cap-of-caps, gate cost, hide stub dims)
   |     GATE 1: shadow-accuracy signal is durable across restart
   |
Phase 2  Define per-dimension promotion_readiness (numeric criteria)  ---- Tier 2-DB
   |     GATE 2: promotion_readiness ready=true for at least one dimension for >=7 days
   |
Phase 3  L2 gated actuation for ONE dimension (reversible_device only)  ---- Tier 3
   |     GATE 3: write-volume regression test still passes; DB row-rate snapshot within +/-25%
   |
Phase 4  Rollback tripwires + operator checkpoint before any L3+ move
```

### Phase 0 — Preflight (mandatory, every campaign session)

Do this before proposing or writing any code.

1. **Read the audit plan end to end**: `docs/planning/PLANNING_audit_optimization_coordinator.md`. Do not skim.
2. **Read the OC design doc**: `docs/Coordinator/OPTIMIZATION.md` (if present) and `docs/planning/PLANNING_OPTIMIZATION_COORDINATOR.md`.
3. **Re-verify ground truth**. Run the Provenance section commands. If any line number has drifted, update this file's tables before continuing.
4. **Confirm current live level**. Live check:

   ```
   # via ha-mcp
   ha_get_state entity_id=sensor.ura_optimizer_reasoning
   ha_get_state entity_id=sensor.ura_optimizer_findings
   ```

   Expect `optimizer_autonomy_level: "shadow"` on the reasoning-sensor attributes. If it is not shadow, **STOP** and reconcile with the operator before proceeding.
5. **Snapshot the current baseline**. Both files should be captured to a working note (paste into the cycle's planning doc):
   - Full-suite pass count from `PYTHONPATH=quality python3 -m pytest quality/tests/ -q --tb=no 2>&1 | tail -20`.
   - OC DB row-rate baseline (see Phase 3 snapshot script below) even if you are only planning Phase 1 — you will need it before deploy.
6. **Tag the pre-review baseline** (CLAUDE.md requirement):

   ```
   git tag pre-review-v<next_version> -m "Pre-review baseline for v<next_version>"
   ```

Fallback when the live house is unreachable (Samba down, MCP down): use the last-known snapshot from the most recent OC README under `docs/readmes/` and mark all live acceptance criteria as `unverified pending mount recovery` in the planning doc — do not fabricate live values. See the "Live access fallback" section below.

### Phase 1 — Fix promotion-evidence blockers

Scope: the D1-D8 deliverables in the audit plan, in the plan's suggested build order (D5+D7 → D1+D3+D8 → D4 → D2 → D6). Only D2 (persist shadow-accuracy samples) is a hard prerequisite for Gate 1.

Non-negotiable rules for Phase 1:

- **Tier 2-DB minimum** — three framing-disjoint reviews. This skill's "Do-it-yourself Tier 2-DB" section below tells you how to run all three yourself when no subagent fleet is available.
- **Write-volume regression test is mandatory in every Phase-1 cycle**, even if the change is unrelated to persistence. Any change to the OC's write envelope must be caught by `test_optimizer_cycle_one_db_write_under_boot_storm:3411` or an equivalent added test. If the existing test would not catch the regression your change could introduce, extend it before merging.
- **DB row-rate snapshot mandatory** for any change that alters a persist path (D2 in particular).
- **Do not touch `_apply_action:2844`**. Phase 1 is evidence + observability only. Actuation stays exactly as-is.

Falsifiable invariant that must hold at the end of Phase 1 (verbatim from the audit plan, Part 3):

> For any cycle at `DEFAULT_OPTIMIZER_AUTONOMY_LEVEL = OPTIMIZER_LEVEL_SHADOW`, the number of `hass.services.async_call` invocations attributable to `_apply_action` is zero, AND the number of `database.log_findings_batch` calls is <= 2, AND the number of `SIGNAL_OPTIMIZER_FINDING_EMITTED` dispatches is <= 1, AND the number of `ura_activity_log` INSERTs from the OC path is <= 2, regardless of finding count.

Reviewer D (see Tier 3 later) will attempt to falsify this. Write it into the planning doc verbatim.

#### Gate 1 — shadow-accuracy signal is durable across restart

Cannot pass until D2 has shipped and run in production for at least 7 days (equal to the shadow-accuracy rolling window).

Concrete pass conditions (all four must hold):

- [ ] `sensor.ura_optimizer_reasoning` attribute `shadow_accuracy_status` reads `"ready"` (not `"warming_up"`, not `"no_observable_data"`). Anchor in code: `optimization.py:1195, 1197, 1201`.
- [ ] `sensor.ura_optimizer_reasoning` attribute `shadow_accuracy_pct` is a float in `[0, 100]`.
- [ ] A manual HA restart does not reset `shadow_accuracy_pct` to null (it did before D2).
- [ ] `test_optimizer_shadow_samples_dao_roundtrip` (added under D2) is green in the suite.

If any condition fails, **STOP.** Do not proceed to Phase 2.

### Phase 2 — Define per-dimension promotion readiness

Scope: audit-plan deliverable D6, backed by D5 and D2.

Add a `promotion_readiness` attribute per scorable dimension on `sensor.ura_optimizer_reasoning` with the shape:

```
{
  "comfort": {"ready": bool, "blocked_by": [reason, ...]},
  "sensor_health": {...},
  ...
}
```

Legal `blocked_by` reasons (numeric, not vibes):

| Reason token | Meaning | Numeric criterion |
|---|---|---|
| `samples_below_min` | not enough shadow samples yet | `len(samples[dim]) < OPTIMIZER_PROMOTION_MIN_SAMPLES` (new const, propose 200) |
| `accuracy_below_threshold` | shadow_accuracy_pct too low | `shadow_accuracy_pct[dim] < OPTIMIZER_PROMOTION_MIN_ACCURACY_PCT` (new const, propose 85.0) |
| `window_too_short` | rolling window not yet 7 days full | `oldest_sample_age < timedelta(days=7)` |
| `stub_oracle` | dimension currently returns `[]` (Phase 3.x) | dimension in `_STUB_DIMENSIONS` set |
| `kill_switch_engaged` | `CONF_OPTIMIZER_KILL_SWITCH` true | direct config read |
| `dimension_autonomy_below_L2` | operator hasn't opted this dim into L2 | `CONF_OPTIMIZER_DIMENSION_AUTONOMY[dim] rank < 2` |
| `regression_tripwire_open` | see Phase 4 tripwires | any tripwire sensor `on` |

Rules:

- Numbers above (200 samples, 85% accuracy, 7-day window) are the **proposed defaults**. Operator gets final call; encode them as `const.py` constants with helper text so they are tunable.
- `ready == true` **must not** actuate anything. It only unblocks the operator's manual promotion via `CONF_OPTIMIZER_DIMENSION_AUTONOMY`.
- Persist and expose in the reasoning-sensor attributes; **do not** emit as findings (those go through the write-volume envelope).

#### Gate 2 — sustained readiness

Cannot pass until:

- [ ] At least one dimension shows `promotion_readiness.<dim>.ready == true` continuously for `>=7 days` in live production (check via `ha_get_history entity_id=sensor.ura_optimizer_reasoning`).
- [ ] The same 7-day window shows zero write-flood tripwire fires (Phase 4).
- [ ] Operator has explicitly acknowledged the numeric thresholds by reviewing the sensor attributes and the constants.

### Phase 3 — L2 gated actuation for ONE dimension (Tier 3)

**Do not enter Phase 3 without Gate 2 passing.** This phase moves off shadow for the first time; the rollback risk profile matches Tier 3 in CLAUDE.md (delicate / cost-and-safety-adjacent / regression-prone / operator-flagged).

Design constraints — all mandatory:

1. **`reversible_device` only** — rank 2. No `propose_config`, no `immediate_config`, no `unbounded`. Per-dimension via `CONF_OPTIMIZER_DIMENSION_AUTONOMY[dim] = OPTIMIZER_LEVEL_REVERSIBLE_DEVICE`. Global `optimizer_autonomy_level` stays `shadow` — L2 is opt-in per dimension.
2. **One dimension at a time.** Pick the one that passed Gate 2. Usually `comfort` or `sensor_health`.
3. **`_apply_action:2844` remains the single chokepoint.** Add the L2 branch adjacent to the L1 shadow branch. Do not add a second actuation path elsewhere.
4. **Write-volume regression test is mandatory in the same commit**, extended so that an L2 actuation cycle STILL emits <=2 `log_findings_batch` and <=1 `SIGNAL_OPTIMIZER_FINDING_EMITTED` — the actuation adds a service call, not more DB writes.
5. **DB row-rate snapshot before deploy** — see script below. Post-deploy row rate must stay within +/-25% of the baseline for the affected tables (`optimization_findings`, `ura_activity_log`).
6. **Veto-window plumbing preserved.** L2 must go through `handshake_broker.fire_intent` + veto window logic already in `_apply_action` (`optimization.py:2948` shadow branch and the sibling L2 branch pattern). Do not skip the veto.
7. **Rollback tripwires wired in code** (Phase 4) before deploy, not after.

Tier 3 review requirement (from CLAUDE.md): **four framing-disjoint reviews**, one of which MUST be adversarial-completeness (Reviewer D) with real per-site source mutation. See the "Do-it-yourself Tier 3" section.

#### Gate 3 — safe actuation proven live

Cannot pass until, in production, all of:

- [ ] The chosen dimension has actuated `>= 10` times at L2 with `applied_outcome != "shadow_dry_run"`.
- [ ] Zero rollback tripwires fired.
- [ ] DB row-rate for `optimization_findings` and `ura_activity_log` within +/-25% of pre-deploy baseline.
- [ ] Full suite still green at HEAD (baseline-diff).
- [ ] README write-back complete with a Validated-<date> row per Phase-3 acceptance criterion (CLAUDE.md README write-back mandate).

### Phase 4 — Rollback tripwires (in code, not calendar)

**CLAUDE.md: no soak watching.** Do not tell the operator "watch it for 24h". Instead, put tripwires directly into the OC that flip the effective level back to `shadow` and fire an NM notification. Wire these into `_resolve_effective_level` (near `optimization.py:2612` per the audit) so they short-circuit before any dispatch.

Tripwires to build (name them plainly, expose one binary_sensor per tripwire):

| Tripwire | Trigger condition | Clamp-to-level |
|---|---|---|
| `optimizer_write_flood_tripwire` | `log_findings_batch` call count over last hour > `OPTIMIZER_HOURLY_WRITE_BUDGET` (propose 20) | `shadow` |
| `optimizer_activity_log_flood_tripwire` | OC-attributed rows/hour in `ura_activity_log` > `OPTIMIZER_HOURLY_ACTIVITY_BUDGET` (propose 40) | `shadow` |
| `optimizer_veto_storm_tripwire` | veto-fire rate over 1h > threshold (propose 10) | `shadow` |
| `optimizer_actuation_disagreement_tripwire` | shadow-oracle-vs-actual mismatch rate > `1 - OPTIMIZER_PROMOTION_MIN_ACCURACY_PCT/100` over 24h | dimension-autonomy back to `shadow` |
| `optimizer_kill_switch` | operator flips `CONF_OPTIMIZER_KILL_SWITCH` | `advisory` (rank 0) |

Rules:

- Tripwires must be evaluated **inside the coordinator run loop**, not in a template sensor. Template sensors have historically caused their own boot fragility (Envoy incident 2026-06-12).
- Every tripwire clamp must fire NM notification with tag `optimizer_tripwire_<name>`.
- NM notifications must respect the OC's existing cross-cycle dedup (12 cycles) plus a distinct per-tripwire keying so they don't collide with normal findings.
- Provide a documented recovery: operator flips the tripwire's associated `input_boolean` or waits `OPTIMIZER_TRIPWIRE_HOLD_HOURS` (propose 24) before the tripwire self-clears. Both paths acceptable.

---

## Do-it-yourself Tier 2-DB (three framing-disjoint reviews, one session)

Use these three prompts to yourself, sequentially, with git commits between each so blame is clean. Take a break (or start a new thread) between framings — the entire point is avoiding blind-spot convergence, which does not survive one 8-hour context window.

| Framing | Role | Explicit focus (paste into the review doc header) |
|---|---|---|
| A — data integrity | you-as-DB-reviewer | Does any change alter row shape, column semantics, index coverage, or existing analytic queries? Are existing rows preserved? Is the write queue still bounded? |
| B — migration + signal chain | you-as-integration-reviewer | Every migrated site emits equivalent rows AND fires downstream signals AND does not double-emit. Trace `_apply_action` -> `_persist_findings_batch` -> `log_findings_batch` -> `SIGNAL_OPTIMIZER_FINDING_EMITTED` end-to-end for each dimension. Field-by-field vs pre-change. |
| C — surfaces + test authority | you-as-QA-reviewer | New reasoning-sensor attrs round-trip through options-flow + RestoreEntity. Behavioral tests drive the real production path, not their own SQL. Every load-bearing site has a test that fails when you bypass ONLY that site (source mutation). |

Write each review to `docs/reviews/code-review/v<version>_<name>_review<A|B|C>_<framing>.md`.

Fix all CRITICAL / HIGH from any of the three before deploy. Then re-verify: for each fix, mutate the fixed site's source to a no-op and confirm a specific test now fails.

## Do-it-yourself Tier 3 (four reviews, the fourth is adversarial-completeness)

Only used at Phase 3 (first L2 actuation) and any later move up the level rank.

Framing D — adversarial completeness — is the one that mattered in the v5.5.3 incident (D-HIGH-1). To run it yourself:

1. **State the invariant in falsifiable form** at the top of Review D's doc, verbatim from the planning doc.
2. **Re-enumerate EVERY reachable emission / decision site touching the invariant, including pre-existing code, not just the diff.** Use `rg` and `grep -rn` for the load-bearing symbols (`_apply_action`, `_persist_findings_batch`, `_dispatch_findings_updated_signal`, `hass.services.async_call`, `_log_activity`) across the OC and any coordinator that consumes its signals.
3. **For every candidate leak, produce a concrete legal-config reachable repro** (values + state that trigger it). "It could theoretically" is not acceptable.
4. **Mutate each load-bearing site individually** and confirm a specific test fails. If bypassing the site leaves the suite green, that site is untested — that is the leak.
5. **Do not trust reviewer summaries** — the orchestrator (you) personally re-runs the mutation test on the load-bearing site before deploy (CLAUDE.md standing rule).

If Reviewer D finds anything: fix it, then re-run D's completeness enumeration from scratch. Do not ship until the invariant holds across the whole surface.

---

## DB row-rate snapshot (before/after deploy)

Required for any Phase 1 change that touches a persist path, and mandatory for Phase 3.

Snapshot script (paste into a scratch file; do not commit unless the operator asks):

```sql
-- Run via mcp__ura-sqlite or on the live DB.
-- Rows per hour for the last 24h, grouped by hour, for OC-relevant tables.

SELECT
  strftime('%Y-%m-%d %H:00', observed_at) AS bucket,
  COUNT(*) AS rows
FROM optimization_findings
WHERE observed_at > datetime('now', '-24 hours')
GROUP BY bucket
ORDER BY bucket;

SELECT
  strftime('%Y-%m-%d %H:00', observed_at) AS bucket,
  COUNT(*) AS rows
FROM ura_activity_log
WHERE observed_at > datetime('now', '-24 hours')
  AND source LIKE 'optimizer%'
GROUP BY bucket
ORDER BY bucket;
```

Capture the pre-deploy snapshot into the planning doc. Post-deploy, re-run at the same wall-clock offset (>= 1h in) and compare. Any bucket outside +/-25% of the pre-deploy median = **DO NOT PROCEED**, roll back to the tag from Phase 0.

If MCP `ura-sqlite` is stale (see CLAUDE.md "Data Source Verification"), remount before querying with the exact command from CLAUDE.md — do not attempt to reconstruct it from memory. Copy the mount command verbatim from `CLAUDE.md` under "Data Source Verification".

---

## Live access fallback

When Samba mount is down or MCP tools are unreachable:

1. Do NOT fabricate a live value. Every live acceptance criterion in the planning doc gets marked `unverified pending mount recovery`.
2. Read the last-shipped OC README under `docs/readmes/README_v<latest>.md` for the last validated shadow-accuracy and write-envelope numbers.
3. Attempt SSH to `homeassistant.local` for `.storage/core.restore_state` and the sqlite DB path from CLAUDE.md.
4. If none of the above works, **STOP** and surface the blocker. Do not deploy blind. This is a No-Fabrication boundary.

---

## Pre-deploy zero-bugs gate

Fact-home: `ura-change-control` §Pre-Deploy Zero-Bugs Gate (conflict-marker grep, `py_compile` every changed file, cycle tests, full-suite baseline-diff vs `pre-review-v<version>`). Cycle-specific test target for this campaign:

```
PYTHONPATH=quality python3 -m pytest quality/tests/test_optimization_coordinator.py -v
```

If any gate item fails: fix, re-run, do not deploy with a red suite, do not `--no-verify`, and never amend an older commit — create a new one.

---

## Deploy handoff

Once all gates for the current phase pass and the pre-deploy zero-bugs gate is clean:

1. Ensure `docs/readmes/README_v<version>.md` exists with prospective Live acceptance rows for every acceptance criterion added in this cycle.
2. Hand off to the `deploy` skill for the release pipeline. Do not run `./scripts/deploy.sh` from inside this skill; the deploy skill owns tag safety, HACS, and the release-notes flow.
3. After HA restart, run live validation:
   - `ha_get_state entity_id=sensor.ura_optimizer_reasoning` — confirm autonomy level, shadow_accuracy status, promotion_readiness (Phase 2+).
   - `ha_get_state entity_id=sensor.ura_optimizer_findings` — confirm state is not sentinels-only (write-flood over-correction check).
   - `ha_get_logs` — filter for `optimization` errors; expect zero URA ERRORs attributable to the cycle.
   - Run the DB row-rate snapshot again and diff vs pre-deploy.
4. **Write the observed results back into `README_v<version>.md`** as a Validated-<date> table, PASS/FAIL per criterion, with concrete evidence. CLAUDE.md is explicit: the cycle is not closed until this write-back is in git.

---

## Anti-patterns — reject on sight

| Anti-pattern | Why it is banned | Correct path |
|---|---|---|
| "Let's soak it for 24h and see" | CLAUDE.md: no soak watching. Bugs hide behind vigilance. | Wire a tripwire in code (Phase 4). |
| "Persist findings inside the emit loop for now" | This is the v5.0.0-v5.2.1 rollback pattern. | Only `_persist_findings_batch:3417`. |
| "Add a per-finding NM notification" | Undermines cross-cycle dedup (audit MED-3). | Use existing `_notify_if_severe` with the audit's per-cycle-decrement fix. |
| "Skip Reviewer D — the diff is small" | v5.5.3 D-HIGH-1 was a 7th unclamped site missed by 3 converging reviewers. | Tier 3 always includes D with source mutation. |
| "Move `optimizer_autonomy_level` global to `reversible_device`" | Enables actuation everywhere at once. | L2 is per-dimension via `CONF_OPTIMIZER_DIMENSION_AUTONOMY`. Global stays `shadow`. |
| "Add a new actuation path outside `_apply_action`" | Kills the single-chokepoint invariant. | Extend `_apply_action:2844` in place. |
| "Bypass boot-storm gate to speed up testing" | The gate is fix-forward load-bearing. | Use synthetic-cycle unit tests, not gate bypass. |
| "Deploy without a row-rate baseline" | Post-deploy comparison becomes impossible. | Phase 0 baseline is a hard gate. |

---

## Provenance and maintenance

This skill's ground-truth facts were verified 2026-07-02 against `develop` at commit `e96dc7a0` (v5.7.2 shipped). To re-verify before trusting any file:line:

```
# Line anchors used above.
grep -nE '_persist_findings_batch|_should_skip_for_boot_storm|_apply_action|_dispatch_findings_updated_signal|_cap_findings|_run_shadow_accuracy_validator|_shadow_accuracy_samples' \
  custom_components/universal_room_automation/domain_coordinators/optimization.py

# Constants.
grep -nE 'OPTIMIZER_LEVEL_|DEFAULT_OPTIMIZER_AUTONOMY_LEVEL|OPTIMIZER_MAX_FINDINGS_PER_CYCLE|OPTIMIZER_BOOT_SETTLE_CYCLES|SCAN_INTERVAL_OPTIMIZATION|CONF_OPTIMIZER_KILL_SWITCH|CONF_OPTIMIZER_DIMENSION_AUTONOMY' \
  custom_components/universal_room_automation/const.py

# Tests.
grep -nE 'test_optimizer_(cycle_one_db_write|boot_storm_settle|boot_storm_uptime|shadow_emits_intent|activity_log_shadow)' \
  quality/tests/test_optimization_coordinator.py

# DAO + pruner.
grep -nE 'log_findings_batch|prune_optimization_findings' \
  custom_components/universal_room_automation/database.py
```

If any line number has drifted more than +/-20 lines, update this file's tables in the same session before proceeding — the runbook must not lie.

Sibling skills to cross-reference (do not duplicate their content):

- `deploy` — the actual release pipeline. This skill hands off to it, does not reimplement it.
- `homeassistant_coding` — general HA patterns; use for anything outside the OC's chokepoints.
- `documenter` — post-cycle documentation updates.
- `transition-doc` — when planning ends and implementation starts in a new session.
- `vibememo` / `vibememo-eval` — decision-trail capture; use to record the promotion decisions this campaign gates.
