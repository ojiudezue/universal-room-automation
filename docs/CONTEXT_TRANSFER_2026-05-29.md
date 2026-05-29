# Context Transfer — 2026-05-29 (post-v4.7.4.4)

**Purpose:** Pick up exactly where the prior session left off after a fresh `/clear`. Read this top-to-bottom before issuing any new request.

---

## 1. Where We Are Right Now

**v4.7.4.4 is LIVE.** All post-deploy entities healthy as of ~01:44 UTC 2026-05-29:

| Entity | State | Was (pre-v4.7.4.4) |
|---|---|---|
| `binary_sensor.ura_energy_coordinator_ec_sub_switches_synced` | `ec_ready_at: 2026-05-29T01:42:28`, `pending: 0`, `all_switches_synced: true` | `ec_ready_at: null` |
| `sensor.ura_coordinator_manager_house_state` | `home_evening` (via arriving → home_evening) | Stuck `away` for 18+ min |
| `sensor.ura_energy_coordinator_battery_strategy` | `reason: "Mid-peak (shoulder) — discharging, best rate window"`, soc 61 | `reason: "initializing"` |
| `switch.ura_energy_coordinator_dynamic_preset_overrides` | `on`, on HVAC device | preserved from prior boot |

**Why three symptoms self-resolved with one fix:** v4.7.4.1's incomplete Bug Class #46 fix caused `async_setup_entry` to run TWICE within bootstrap-2 budget. Budget pressure cascaded to presence (couldn't subscribe + ingest person state), EC (signal fired before sensor subscribed), and battery strategy (decision cycle never reached steady state). v4.7.4.4 drops the migration entirely → single setup pass → all three symptoms gone.

---

## 2. The v4.7.x Stretch — Closed

**14 releases:** v4.7.0 → v4.7.4.4. Full retrospective in auto-memory: `project_v4_7_x_stretch_closed.md`.

### Tier 2 / Tier 2-DB feature cycles
- **v4.7.0:** WeatherProviderManager + EV TOU Hardening
- **v4.7.1:** DPM Cycle B + Guest Mode Phase 1 D2/D3/D4 (thermostats actually move)
- **v4.7.2:** DPM HVAC Coordinator Surface + Phase 2 Feature B (sustained-occupancy guest signal)
- **v4.7.4:** DPM UI simplification — drop Surface 1 per-zone iteration, conditional Surface 2

### Tier 1 hotfixes
- v4.7.0.1, v4.7.1.1, v4.7.2.1, v4.7.3, v4.7.3.1
- v4.7.4.1 (FAILED Bug Class #46 fix)
- v4.7.4.2 (dead-import hotfix — HA 2026.5.4 moved `selector` module)
- **v4.7.4.3 (BROKEN RELEASE — shipped with merge conflict markers, would fail SyntaxError on install)**
- v4.7.4.4 (real Bug Class #46 fix — drop migration, derive lazily at read time)

### 4 new Bug Classes documented (in `docs/QUALITY_CONTEXT.md`)
- #43: Bookkeeping Short-Circuit Defeated by External State Change
- #44: Cross-File sys.modules Pollution in Test Harness
- #45: Lambda Closure Captures Stale Local Variable
- #46: `async_update_entry` Re-entrancy from `async_setup_entry` — INCLUDES incomplete-fix incident note + "when async_update_entry IS safe" sub-section listing 7 safe pre-existing call sites

---

## 3. NEXT CYCLE: v4.7.5 — Zone Manager UX + Canonical Resolution

**Tier 2. Locked. Awaiting your kickoff signal.**

**Memory file:** `project_v475_design_intent.md`
**Recall phrase:** "Plan v4.7.5 — Zone Manager UX + canonical resolution"

### Scope (4 deliverables + 1 test scaffold)
1. **Dropdown → menu** for Zone Manager Page 1 picker (UX cleanup)
2. **Picker shows house zones**, NOT canonical-merged HVAC labels (no more "Entertainment + Master Suite" in the picker)
3. **Silent canonical resolution at runtime** — `iter_canonical_hvac_zones` keeps merging inside the coordinator; UI never sees it
4. **Option C auto-mirror on save** — when 2+ house zones share a thermostat, saving one auto-mirrors settings to siblings + banner UI text on shared-thermostat zones (user-confirmed: "Definitely C")
5. **Bundled:** Config-flow runtime smoke tests (closes task #112, the test class that would have caught v4.7.4.2 dead-import bug)

### Estimated size
~565 LoC. Touches `config_flow.py` heavily + `hvac_zones.py`. Heavy reuse of the lazy-derivation pattern from Bug Class #46 fix.

### Dispatch protocol
1. User signals kickoff
2. `ura-planner` writes `PLANNING_v4.7.5_zone_manager_ux.md` with acceptance criteria
3. `ura-builder` (worktree isolation) implements
4. **Two parallel Tier 2 reviewers, different framings:**
   - Reviewer A: correctness + edge cases (auto-mirror round-trip, RestoreEntity, unlink path)
   - Reviewer B: async + lifecycle + race conditions (save → mirror tick ordering, options.on_change reload chain)
5. **Pre-deploy: run the 4-gate Zero-Bugs Gate** (see §6)
6. `/deploy 4.7.5 "<summary>" "<notes>"` via skill
7. Live validation: save one zone → sibling updates within 1 tick; coordinator merge still works

---

## 4. Decisions Locked This Session (from VibeMemo)

- **Entry 013:** Lazy derivation at read time is the **canonical fix pattern** for Bug Class #46. Never defer `async_update_entry` — REMOVE the write entirely. The first user save persists naturally.
- **Entry 014:** Pre-Deploy Zero-Bugs Gate is **mandatory** before every `deploy.sh`. (See §6.)
- **Entry 015:** v4.7.5 Option C auto-mirror with silent canonical resolution + banner UI text.

All three in `.vibememo/users/ojiudezue/entries/013_*.json`, `014_*.json`, `015_*.json`.

---

## 5. Process Lessons (memory files)

- **`feedback_pre_deploy_zero_bugs_gate.md`** — MANDATORY 4-gate before deploy.sh
- **`feedback_no_fabrication.md`** — verify in source/HA docs, ask, or say "I don't know" — never describe a code pattern from a guessed mental model
- **`feedback_db_sensitive_3x_targeted_reviews.md`** — 3 reviewers targeted at DIFFERENT risks (Tier 2-DB)
- **`feedback_deploy_pr_diff_verification.md`** — inspect PR diff after deploy.sh for the cycle's code files
- **`feedback_build_agent_commit_verification.md`** — verify `git log` shows commit on feature branch before declaring build done

---

## 6. The Pre-Deploy Zero-Bugs Gate (MUST run before every `./scripts/deploy.sh`)

```bash
# Gate 1: No unresolved conflict markers anywhere
grep -rln "^<<<<<<<\|^>>>>>>>" custom_components/ docs/ quality/ \
  | grep -v "TEST_SUITE_ACCESS\|test_scenarios" \
  && echo "❌ ABORT: unresolved conflict markers found" && exit 1

# Gate 2: py_compile every changed Python file
git diff --name-only HEAD~1 -- '*.py' | xargs -I{} python3 -m py_compile {} || exit 1

# Gate 3: cycle tests pass
PYTHONPATH=quality python3 -m pytest quality/tests/test_v<VERSION>_*.py -q || exit 1

# Gate 4: full URA suite — no NEW regressions vs pre-deploy baseline
PYTHONPATH=quality python3 -m pytest quality/tests/ -q
# compare failed count vs baseline_v<prev>.txt
```

If ANY gate fails: STOP. Fix. Re-run all gates. Only then `deploy.sh`.

---

## 7. Open Backlog (NOT v4.7.5)

From `project_near_term_roadmap_post_v462.md`:
- **Guest Mode Phase 3** (predictive, sensors only — Phase 1 actuation already shipped in v4.7.1)
- **AnomalyType discriminator** — column rename; on deck after Guest Mode warmth

From other memory files:
- **PWA v6.0.1** is live; v6.1 = D10 OAuth dedicated PWA token (deferred to PWA repo)
- **Dashboard v4 React port** — design complete, port not started (~3-4 weeks, in PWA repo)
- **Advanced Energy Mgt v4.7.x Forecaster** — DEFERRED, not in scope until close-out is fully done

---

## 8. Active Tasks (TaskList)

- **#112 — pending** — Backlog: config_flow runtime smoke tests (bundled into v4.7.5)
- **#113 — completed** — Ship v4.7.4.3 (now superseded by v4.7.4.4)

---

## 9. Recall Phrases (for `/clear` then ask)

| To resume | Say |
|---|---|
| **Start v4.7.5 build** | "Plan v4.7.5 — Zone Manager UX + canonical resolution" |
| Review what shipped recently | "What shipped in the v4.7.x stretch" / "Resume after v4.7.4.4" |
| Pull up the deploy gate | "Apply pre-deploy zero-bugs gate" |
| Pull up other roadmap items | "Resume URA roadmap" |
| Promote Advanced Energy Mgt later | "Resume Advanced Energy Mgt v4.7.x — Forecaster-First" |
| Resume PWA work | "Resume URA Dashboard PWA" |

---

## 10. CRITICAL Reminders for Fresh Session

1. **Read `graphify-out/GRAPH_REPORT.md` FIRST** before touching code (per project CLAUDE.md).
2. **Tier 2 = TWO parallel reviewers, different framings.** Tier 2-DB = THREE.
3. **Worktree isolation for builder agents** — process lapse in v4.7.3 (built directly) did not recur but discipline matters.
4. **DPM master switch lives on HVAC Coordinator device** (`02·` Dynamic Preset Auto-Adjust) — auto-migrated by HA in v4.7.2.
5. **Bootstrap-2 budget is bounded.** Setup-time `async_update_entry` calls AFTER update_listener registration (line ~2526 in `__init__.py`) trigger re-entrant reload. The 7 safe call sites BEFORE 2526 are documented in QUALITY_CONTEXT.md #46.
6. **Live deploy verification:** HA logs go to systemd journald, NOT `~/ha-config/home-assistant.log`. Use `ha_get_logs(source="system_service", slug="core")`.

---

**Generated:** 2026-05-29 ~02:20 UTC
**Generator session:** continuation of `65cf7119-f32d-4c25-bf80-eba5ff40d630`
**Safe to clear context after reading this file.**
