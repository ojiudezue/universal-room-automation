# URA — 2026-06-02 session: v4.7.17.2 + v4.7.18 dual deploy + Shipwatch spinoff

Load-bearing context from a long parallel-threaded session. Future cycles MUST consult this before:
- Authoring acceptance YAML for any URA cycle (the "plug into Shipwatch" section below)
- Interpreting "Number fields" / "Number knobs" in planning docs
- Deferring LOW review findings
- Restarting HA via MCP and immediately validating

Operator: oji@productmind.co. Auto Mode active. Opus 4.7 (1M context).

---

## TL;DR — what shipped

| Cycle | Result |
|---|---|
| **v4.7.17.2** | Tier 1 simplified-frame cycle escalated by operator to Tier 2 in-flight. 0 CRIT / 4 HIGH / multiple MED fixed in one fix-up pass. Released as `v4.7.17.2`, PR #353 merged to master, live on HA. |
| **v4.7.17.2 README fix** | Acceptance YAML had two bugs (singular entity refs, Number-entity-expectation). Patched on develop as commit `d0f1ed8`. Shipwatch can now resolve queries on its normal cadence. |
| **v4.7.18** | Tier 2-DB (operator-elevated) cycle. 6 deliverables, 3 parallel reviewers (data integrity / migration+signal / surfaces+tests), all 3 MEDIUMs resolved, 8 LOWs fixed in-cycle, 6 LOWs justified. Released as `v4.7.18`, PR #354 merged, live on HA. |
| **v4.7.17.3** | Hotfix considered (add platform Number entities for the v4.7.17.2 relax/tighten knobs), built across 3 commits on a feature branch, then **CANCELLED** per operator override. Local-only branch `feature/v4.7.17.3-dpm-number-entities` retains the 3 commits as dead-code artifact; eligible for `git branch -D` whenever. |
| **Shipwatch spinoff** | URA-internal tool `scripts/shipwatch/` extracted to a sibling repo at `~/Code/shipwatch/`. URA `CLAUDE.md` gained a "Sibling project: Shipwatch" section; URA `MEMORY.md` flipped the planned-status memo to SPUN OFF. URA `.claude/agents/ura-shipwatch.md` rewritten as a deprecation stub. See `~/Code/shipwatch/docs/sessions/2026-06-02_spinoff_and_baseline.md` for the Shipwatch-side history. |

Net new URA commits on master via this session: 2 PRs (one per cycle).

---

## v4.7.17.2 timeline + key callouts

**Cycle scope:** rolling-14d-apparent-high-median replaces forecast-vs-cool-target DPM mechanic. ≤2 operator knobs (`CONF_DPM_COOL_DAY_RELAX_F`, `CONF_DPM_HOT_DAY_TIGHTEN_F`). Calendar winter gate (Nov-Feb). PresetManager seasonal as single base via `resolved_pm` plumbed through `evaluate_with_reason`.

**Pre-deploy state (entering session):** built + pre-deploy Tier 1 reviewed (0 CRIT, 2 HIGH, 3 MED, 3 LOW — H1+M2+M3 fixed in place, H2+M1 disposed). Uncommitted on `feature/v4.7.17.2-dpm-simplified-frame`.

**Session actions:**
1. Committed v4.7.17.2 build on feature branch (`da40cdd`)
2. Tagged `pre-review-v4.7.17.2` for diff-able review-fix isolation
3. Dispatched two parallel Tier 2 reviewers per CLAUDE.md (A = correctness/edge cases, B = async lifecycle/race/restart). Both ran ~6 min, returned reports at `docs/reviews/code-review/v4.7.17.2_reviewer_{A,B}_*.md`.
4. Combined: 0 CRIT / 4 HIGH / 2 MED. Reviewer A's `A-H1` (winter gate fails open on `current_season == ""`) and Reviewer B's `B-M3` (winter gate stale cache) converged on the same bug — fix: compute winter directly from `dt_util.now().month`.
5. Single fix-up agent landed 5 fixes + 4 test additions (`6 commits 3707265…bdf364a`):
   - A-H1 + B-M3 — winter gate via calendar (no PM dependency)
   - A-H2 — UTC date key for rolling ring (vs local-time which is what was committed)
   - B-H1 — hydrate-before-listeners race fix in `weather_manager.py`
   - B-H2 — `DPM_SKIP_REASONS: Final[frozenset[str]]` to lock taxonomy
   - B-M2 — explicit `season=` to avoid PM `_current_season` mutation side-effect
6. Pre-deploy zero-bugs gate: py_compile + JSON validation + conflict marker scan (real markers, not pytest decoration). All clean.
7. Merge to develop, `./scripts/deploy.sh 4.7.17.2 ...` — PR #353 merged, release tag created.
8. HACS download via `ha_hacs_download(repository_id="ojiudezue/universal-room-automation", version="v4.7.17.2")`. `ha_restart(confirm=true)`. Polled HA back online.
9. Live validation immediate: `update.universal_room_automation_update.installed_version = v4.7.17.2`, 0 URA ERROR logs, bucket sensor first cycle at T+5min post-boot with new `cool_high_adjustment_f` attribute present.

**README YAML bug (caught during live validation):**
- H1 expected `number.ura_energy_coordinator_dpm_cool_day_relax_f` — entity does not exist by design (config-flow only per plan §83)
- H2-H5 referenced singular `sensor.ura_energy_coordinator_dynamic_preset_bucket` — actual entities are per-zone (`_back_hallway`, `_entertainment_master_suite`, `_upstairs`)
- Fixed on develop as `d0f1ed8`. H1 rewritten to validate sensor availability + per-zone entity IDs throughout.

---

## v4.7.17.3 hotfix — considered, built, cancelled

**Genesis:** during v4.7.17.2 live validation I diagnosed a "Number entity gap" — plan §126 said "2 NEW visible Number fields (relax_f, tighten_f)" which I read as platform Number entities. The build only added them as config_flow NumberSelector form fields. Proposed a v4.7.17.3 hotfix to add `number.py` entries.

**Operator override:** "Actually since the plan doesn't reference number entities, I don't think we should create them. Fix the readme instead. Cancel the code hotfix. This works right?"

**Resolution:**
- TaskStop on the v4.7.17.3 hotfix builder mid-flight
- Feature branch `feature/v4.7.17.3-dpm-number-entities` retains 3 commits as a dead artifact (D1 register Numbers, behavioral tests, planning doc + README). Not pushed to origin. Eligible for `git branch -D` whenever the operator wants.
- README YAML fix landed on develop as `d0f1ed8` (described above)
- Memory entry written: `feedback_plan_phrasing_number_fields.md` → "Number fields in URA plans means config_flow NumberSelector form fields, NOT platform Number entities."

**Lesson encoded (don't repeat):** when a plan says "Number fields" or "Number knobs," default to form-field interpretation. The grep test: `grep -E "NumberEntity|number\.py|platform.*number" <planning-doc>` — if zero hits, it's form fields.

---

## v4.7.18 timeline + key callouts

**Cycle scope:** DPM Drift Guard + Cleanup. Tier 2-DB (operator-elevated). 6 deliverables D1-D6:
- D1: strip 16 dead bucket cells + `customize_buckets` toggle from Surface 2
- D2: delete dead `_validate_dynamic_preset_input` (after call-site audit confirms zero production callers)
- D3: widen WPM ring 14→90 + add `_p25_apparent_high` (median STILL uses 14-day slice — load-bearing `[-DPM_ROLLING_WINDOW_DAYS:]`)
- D4: `_resolve_relax_ceiling` + heat-wave gate (asymmetric: suppresses relax-up only, NEVER tightens) + 5-option dropdown
- D5: 4 new sensor attrs (`relax_ceiling_f`, `relax_ceiling_source`, `relax_ceiling_blocked_count`, `relax_ceiling_last_blocked_at`) + RestoreEntity hydration
- D6: operator-approved labels verbatim + per-option dropdown descriptions

**Tier 2-DB review framings (3 parallel reviewers):**
- A — data integrity + restart resilience (14-day-slice invariant, Store hydrate cap, counter persistence, Bug Class #49)
- B — migration correctness + cross-coordinator + signal chain integrity
- C — new surfaces + UI round-trip + test authority (Bug Class #39)

**Review outcome:** 0 CRIT / 0 HIGH / 3 MED (all C-side) / 14 LOW.

**Operator override mid-cycle:** "Stop the deferment. Fix reasonable lows and don't pile up debt." First fix-up agent had been instructed to "justify 14 LOW deferrals to v4.7.19+" — wrong direction.

**Resolution sequence:**
1. TaskStop on the first fix-up agent
2. `git revert 37123cf` (the C-M2 deferral commit) — destructive op replaced with revert per CLAUDE.md
3. The revert deleted the planning doc (it was the doc's first git-tracking). Recovered via `git show 37123cf:<path> > <path>`, surgically removed the §14 #6 entry, deleted the omnibus LOW deferrals doc, committed as `12a7453 cleanup`.
4. Dispatched corrected fix-up agent with new scope: ship C-M2 dropdown descriptions for real, fix 8 reasonable LOWs (A-L1, A-L2, A-L3, B-L1, B-L2, B-L3+C-L1), justify only 6 genuine non-fix LOWs (B-L4 single-locale, C-L2 intentional data preservation, C-L3 v5.0 sweep, C-L4 live-validation covers, C-L5 matches existing pattern, C-L6 bit-exact today).
5. Two further agent runs (one truncated mid-narrative, one tight tail) completed all the fixes. Final commits: `2dd442b 1fa3b3b 1f32646 2ba5160 47d3c1d 25a38d3 78ca3db`.
6. Final test suite: 62 failed (= baseline) / 14 errors (= baseline) / 4 skipped / 4794+ passed (+13 new behavioral tests). Zero net regressions.
7. Pre-deploy gate clean (py_compile + JSON + no conflict markers). Merge to develop. `./scripts/deploy.sh 4.7.18 ...` — PR #354 merged, release tag created. HACS install + HA restart + live validation: `installed_version = v4.7.18`, bucket sensor at T+5min post-boot with all 4 new D5 attrs present.

**A-L3 cold-start behavior verified live:** `relax_ceiling_f=null` during cold ring (mode=auto but ring not yet at `DPM_P25_MIN_DAYS=30` entries) is the intended A-L3 behavior — sensor renders None when the gate can't meaningfully fire.

**Memory entry written:** `feedback_fix_lows_in_cycle.md` → "Fix reasonable LOWs in the same fix-up pass that handles MEDIUMs. Don't omnibus-defer to a future version. Defer only the few that genuinely need a separate cycle."

---

## How to plug URA cycles into Shipwatch (going forward)

This is the URA → Shipwatch contract. Every URA cycle from v4.7.19 onward MUST follow this:

### 1. Author acceptance YAML in the README

`docs/readmes/README_v<version>.md` MUST include an `## Acceptance` section with a fenced YAML block. Structure:

```yaml
version: v<version>
hypotheses:
  - id: H1
    name: <short_snake_case>
    description: |
      <human-readable, multi-line ok>
    query:
      kind: ha_state | ha_state_attribute | log_grep
      entity: <fully-qualified entity_id>   # PER-ZONE when applicable
      # If kind == ha_state_attribute:
      attribute: <attribute_key>
      # If kind == log_grep:
      source: home_assistant_core
      pattern: <regex>
    expected:
      condition: "==" | "!=" | "in" | "no_matches_in_window" | "all_absent"
      value: <expected value, or list, or null>
    window:
      first_check_after: 1h
      confirm_after: 24h
      alert_if_violated_after: 72h
      # OPTIONAL guard for time/season-gated hypotheses:
      only_during: hvac_season=winter | forecast_apparent_high_seen_geq_90f | ...
```

### 2. Entity-ID rules

- **Use per-zone entity IDs** where the sensor is per-zone. Canonical zone for v4.7.17.2 + v4.7.18 testing: `_upstairs`. Singular entity IDs return ENTITY_NOT_FOUND.
- **Don't expect platform Number entities** for config-flow CONFs. Validate config-flow knobs via their BEHAVIORAL EFFECT (sensor attribute values). See `feedback_plan_phrasing_number_fields.md` memory.
- **CONFs ≠ Numbers.** A CONF in `energy_const.py` is operator-facing if and only if the options-flow form exposes it. Number platform entities are an ADDITIONAL surface, not the default.

### 3. Time-gated hypotheses

For hypotheses that can't confirm immediately (rolling ring fills, season changes, behavioral correctness post-ring-fill), use `window.only_during` and `window.first_check_after >= 168h` (7 days) appropriately. Shipwatch's watcher will park them and check on the configured cadence.

### 4. Post-deploy sequence (codified)

```python
# After ./scripts/deploy.sh completes:
ha_hacs_repository_info("ojiudezue/universal-room-automation")  # verify available vs installed
ha_hacs_download("ojiudezue/universal-room-automation", version="v<version>")
ha_restart(confirm=True)
# Poll until HA back online (curl manifest.json + curl /api/ returning 401 = ready)
# Wait ~5 min for first DPM coordinator cycle
ha_get_state("sensor.ura_energy_coordinator_dynamic_preset_bucket_upstairs")  # canonical zone
# Verify state != "unavailable" and expected v<version> attrs present
ha_get_logs(source="system", level="ERROR", search="universal_room_automation")  # must be empty
```

See `feedback_verify_hacs_install.md` memory for the discipline rule.

### 5. Shipwatch picks up from here

Once acceptance YAML is on `master` (post-deploy.sh merge), Shipwatch's watcher (configured via `~/.shipwatch/projects.yaml`) will:
- Poll HA on its cadence
- Evaluate each hypothesis's query against live state
- Mark CONFIRMED after N≥2 consecutive checks pass
- Alert when `alert_if_violated_after` window elapses without confirmation
- Log every check result to vibememo / `~/.shipwatch/state/`

URA doesn't need to do anything else. The README YAML IS the contract.

### 6. Where Shipwatch lives

| Resource | Location |
|---|---|
| Local repo | `~/Code/shipwatch/` |
| GitHub | https://github.com/ojiudezue/shipwatch (private) |
| Gitea | https://gitea.phalanxmadrone.com/Okosisi/shipwatch (private) |
| Founding session log | `~/Code/shipwatch/docs/sessions/2026-06-02_spinoff_and_baseline.md` |
| Global agent | `~/.claude/agents/shipwatch.md` (invoke via `@shipwatch`) |
| Operator config | `~/.shipwatch/projects.yaml` (USER-LOCAL, not in repo) |
| Recall phrase | `"Resume Shipwatch 1.2.0"` (registered in URA `MEMORY.md` index) |

---

## Branches eligible for cleanup (when operator wants)

All merged or cancelled this session, can be deleted with `git branch -D`:
- `feature/v4.7.17.2-dpm-simplified-frame` (merged via PR #353)
- `feature/v4.7.18-dpm-drift-guard-cleanup` (merged via PR #354)
- `feature/v4.7.17.3-dpm-number-entities` (cancelled — local-only, 3 unpushed commits)

Pre-review tags are preserved for diff-able history (`pre-review-v4.7.17.2`, `pre-review-v4.7.18`).

---

## Memory entries written this session

All under `~/.claude/projects/-Users-okosisi-Code-universal-room-automation/memory/`:

| File | Rule |
|---|---|
| `feedback_fix_lows_in_cycle.md` | Fix reasonable LOWs in the same fix-up pass. Don't omnibus-defer. Cap deferral doc at ~6 entries. |
| `feedback_plan_phrasing_number_fields.md` | "Number fields" in URA plans = config_flow NumberSelector form fields, NOT platform Number entities. |
| `project_pickup_2026_06_02_dpm_shipwatch.md` | Pre-existing pickup memo from prior session; outcomes recorded above. |

Existing memories that govern URA + Shipwatch interaction (don't change):
- `feedback_verify_hacs_install.md` — HACS install + restart discipline post-deploy.sh
- `feedback_pre_deploy_zero_bugs_gate.md` — py_compile + JSON + conflict markers before every deploy
- `feedback_no_fabrication.md` — verify in source / HA docs / ask / admit don't-know
- `feedback_db_sensitive_3x_targeted_reviews.md` — Tier 2-DB three-reviewer protocol
- `feedback_ura_mirror_pattern.md` — RestoreEntity = runtime; entry.options = seed only
- `feedback_no_soak.md` — never propose 24h soak / monitor-and-watch; trip-wires go in code

---

## Pending operator decisions / actions (low urgency)

| Item | Note |
|---|---|
| Restart Claude Code | So global `~/.claude/agents/shipwatch.md` resolves on `@shipwatch` |
| Create `~/.shipwatch/projects.yaml` | From `~/Code/shipwatch/config/projects.yaml.example`, point at URA |
| DNS `shipwatch.phalanxmadrone.com` | Only needed at Shipwatch v2.0.0 Dashboard MVP |
| Delete merged feature branches | `git branch -D feature/v4.7.17.2-dpm-simplified-frame feature/v4.7.18-dpm-drift-guard-cleanup feature/v4.7.17.3-dpm-number-entities` |
| Onboard `ura-dashboard-pwa` to Shipwatch | At Shipwatch v1.2.0 deploy.sh integration time |

---

## What did NOT happen this session (deliberate)

- No v4.7.17.3 Number entity hotfix (cancelled per operator)
- No Shipwatch v1.2.0 build (queued for next cycle)
- No Shipwatch dashboard build (v2.0.0 scope)
- No HA host changes outside the deploy cycles (operator's framing: "HA should only be responding to deploy cycles")
- No new memory entries for ephemeral session state — only durable rules and learnings
