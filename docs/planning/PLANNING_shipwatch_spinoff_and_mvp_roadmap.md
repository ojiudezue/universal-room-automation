# PLANNING — Shipwatch sibling-repo spinoff + MVP roadmap

**Tier classification:** the spinoff itself is operational cleanup (no runtime risk). The MVP cycles inside it follow per-cycle Tier classification as listed in §4.

**Status:** filed 2026-06-02. Operator-approved decisions: spinoff yes, hosting Option 1 → Option 2 smooth migration, MVP sequence reconciled with original PLANNING_ura_shipwatch.md D1-D7.

---

## 1. Why spin Shipwatch off

Shipwatch is generic infrastructure that happens to target URA today. The operator framing is: *"Shipwatch will be bigger than URA."* That implies:

- **Versioning collision** — URA versions like `v4.7.18` should not share a numberspace with Shipwatch versions like `1.2.0`. Today they do (loosely), which makes `./scripts/deploy.sh` calls ambiguous.
- **Cross-project applicability** — Shipwatch should target URA, PWA, and future projects via a `projects:` map. Living inside URA's repo couples it artificially.
- **Independent release cadence** — Shipwatch cycles ship at a different rhythm than URA cycles. Sharing a release pipeline forces unnecessary alignment.
- **CLAUDE.md scope** — URA's CLAUDE.md is HVAC + presence + Tier 2-DB rules that are URA-specific. Shipwatch needs its own protocol surface.

The cost of NOT spinning off compounds with every new Shipwatch cycle that lands inside URA's `docs/planning/`.

---

## 2. Target repo layout

```
~/Code/shipwatch/
├── README.md                          # project overview, install instructions
├── CLAUDE.md                          # shipwatch-specific protocol (Tier rules, etc.)
├── scripts/
│   └── deploy.sh                      # own deploy script (copied from URA, paths swapped)
├── agents/
│   └── watcher.md                     # ← moved from URA's .claude/agents/ura-shipwatch.md
├── docs/
│   ├── planning/
│   │   ├── PLANNING_v1.0.0.md         # retroactive: watcher core + YAML format
│   │   ├── PLANNING_v1.1.0.md         # retroactive: agentic auto-promote
│   │   ├── PLANNING_v1.2.0.md         # deploy.sh integration (next ship)
│   │   └── (future)
│   └── readmes/
│       ├── README_v1.0.0.md           # retroactive
│       ├── README_v1.1.0.md           # retroactive
│       └── (future)
├── dashboard/
│   ├── prototypes/
│   │   ├── P1.html                    # ← moved from URA's docs/dashboard-prototypes/shipwatch/
│   │   ├── P2.html
│   │   ├── P3.html
│   │   └── INDEX.md
│   ├── static/                        # production build (when 2.0.0 ships)
│   └── data/
│       └── status.json                # written by watcher, rsynced to LXC
├── src/
│   └── (future — FastAPI service when 3.0.0 migrates from static to service)
└── config/
    └── projects.yaml                  # the projects: map that tells Shipwatch where READMEs live
```

### projects.yaml example

```yaml
projects:
  ura:
    readme_dir: ~/Code/universal-room-automation/docs/readmes/
    state_oracle: home_assistant
    ha_url: http://homeassistant.local:8123
    ha_token_env: HA_TOKEN
    promote_paths:
      - ~/Code/universal-room-automation/custom_components/universal_room_automation/
  ura_pwa:
    readme_dir: ~/Code/ura-dashboard-pwa/docs/readmes/
    state_oracle: vercel
    vercel_project: ura-dashboard-pwa
```

Sibling repos on the same machine = filesystem path. No git API. Adding a project = one map entry.

---

## 3. Spinoff migration cycle (Shipwatch 1.0.0 retroactive)

**Deliverable:** clean repo at `~/Code/shipwatch/`, dual-pushed to GitHub + Gitea (per operator's standing rule for new repos), with retroactive 1.0.0 and 1.1.0 planning docs + READMEs reflecting what already shipped informally.

### Migration steps

| # | Step | LoC / cost |
|---|---|---|
| M1 | `mkdir -p ~/Code/shipwatch && git init` | 1 cmd |
| M2 | Copy URA's `scripts/deploy.sh` → `~/Code/shipwatch/scripts/deploy.sh`. Strip URA-specific paths (no HACS upload, no HA restart, no `custom_components` path). Replace with: tag release, push to GitHub, push to Gitea, generate README index. | ~80 LoC modified |
| M3 | Move `URA/.claude/agents/ura-shipwatch.md` → `shipwatch/agents/watcher.md`. Keep the URA file as a one-line stub pointing to the new location: `# Moved to ~/Code/shipwatch/agents/watcher.md`. | 1 file moved + 1 stub |
| M4 | Move `URA/docs/dashboard-prototypes/shipwatch/*` → `shipwatch/dashboard/prototypes/`. | 4 files moved |
| M5 | Author `shipwatch/CLAUDE.md` (~30 lines): tier protocol (T1/T2/T2-DB), review framings, deploy discipline, "no soak watching" rule. | ~30 lines |
| M6 | Author `shipwatch/README.md` (~50 lines): what Shipwatch is, install steps, projects.yaml format, where to find planning docs. | ~50 lines |
| M7 | Author `shipwatch/docs/planning/PLANNING_v1.0.0.md` retroactively. Pulls from URA's `PLANNING_ura_shipwatch.md` D1, D3, D4, D5. Includes the original "founding principle" + acceptance YAML contract. | ~150 lines |
| M8 | Author `shipwatch/docs/planning/PLANNING_v1.1.0.md` retroactively. Documents the agentic auto-promote with N≥2 consecutive confirmations + 5-gate judgement layer + action whitelist. | ~100 lines |
| M9 | Author corresponding READMEs (`README_v1.0.0.md`, `README_v1.1.0.md`) with operator-visible acceptance hypotheses retroactively filled in (best-effort — we can leave some as "untracked"). | ~80 lines |
| M10 | Update URA `CLAUDE.md` with a "Sibling project" section: one paragraph noting Shipwatch lives at `~/Code/shipwatch/` and that URA's `deploy.sh` is URA-only. Add to `docs/planning/PLANNING_v4.7.10_deploy_sh_gitea_retrofit.md` if relevant. | ~10 lines |
| M11 | Update URA `MEMORY.md` index entry referencing Shipwatch to point at the new sibling repo. | 1-2 lines |
| M12 | Move URA's `docs/planning/PLANNING_ura_shipwatch.md` content: keep as historical record in URA (it documents pre-spinoff thinking), but add a top banner: `> ⚠️ Pre-spinoff plan. Active planning lives at ~/Code/shipwatch/docs/planning/.` | 2 lines added |
| M13 | First Shipwatch deploy: `cd ~/Code/shipwatch && ./scripts/deploy.sh 1.1.0 "spinoff baseline" "Retroactive spinoff from URA. Captures shipped v1.0 + v1.1 functionality."` | 1 cmd |

### Migration risk

- **URA's existing watcher invocations** continue to work — `.claude/agents/ura-shipwatch.md` stub redirects. No URA cycle breaks.
- **No code execution moves** in M3 — the agent definition is markdown, not code. Filesystem move only.
- **CLAUDE.md collision** — URA and Shipwatch each have their own. Inside their respective repos there's no ambiguity. Cross-repo invocations are explicit by repo cwd.

Total migration cost: ~3 hours of work + 1 deploy. Tier 1.

---

## 4. MVP roadmap (post-spinoff)

Essence-first ranking. Prove the watcher correctly handles production reality (1.x), then add operator daily-glance surfaces (2.x), then grow beyond URA (3.x).

### 1.2.0 — Deploy.sh integration + baseline snapshot

**Why first:** today the watcher has no signal that a new deploy happened. Operator manually triggers a session. Doesn't scale, gets forgotten. Also, original PLANNING_ura_shipwatch.md D2 specified pre-deploy row-rate snapshots for DB-sensitive cycles, which never shipped — without them, the "compared to baseline" hypothesis class (which several v4.6.x/v4.7.x cycles need) is impossible.

**Deliverables:**
- URA `deploy.sh` writes a session marker after a successful deploy: `~/.shipwatch/sessions/<project>_<version>.json` with `{project, version, deployed_at, readme_path, baseline_snapshot}`.
- Watcher on next tick reads `~/.shipwatch/sessions/` for new markers, kicks off a session per marker.
- For Tier 2-DB cycles, deploy.sh queries the relevant DB tables before the deploy and captures row rates by `(coordinator, type, severity)` into the baseline_snapshot field. Hypothesis YAML can reference `expected.compared_to_baseline: ±25%` for percentage-based confirmation.

**Tier:** T1. ~60 LoC across deploy.sh + watcher agent.

### 1.3.0 — Failure-mode taxonomy

**Why second:** today, when a session can't read the YAML (malformed), or the HA state query times out, or the entity returns `unknown`, the hypothesis silently stays `pending`. Operator never learns there's a problem. Trust erodes — "is Shipwatch even running?" Need explicit statuses.

**Deliverables:**
- New statuses: `parse_error`, `query_failed`, `entity_unavailable`, `recorder_timeout`, `auth_failed`.
- Each failure status has a remediation note attached (e.g., "Renew HA token in projects.yaml").
- Status JSON includes failure_count per status, last_failure_at.
- Watcher escalates persistent failures (>3 consecutive) via NM-channel (or memory writeback).

**Tier:** T1. ~50 LoC.

### 1.4.0 — Retroactive backfill

**Why third:** lets us validate past cycles that have YAML blocks but never had a watcher session. Bootstraps evidence for v4.7.x stretch, v4.6.x DB cycles, etc.

**Deliverables:**
- `shipwatch backfill --since=<date>` command that walks all README YAML blocks newer than the date, runs queries against recorder for the historical window, classifies retroactively.
- Output: a report-mode session (not auto-promoting) showing what WOULD have happened.
- Operator can review and either accept retroactive promotions or leave as audit-only.

**Tier:** T1. ~40 LoC.

### 2.0.0 — Dashboard MVP (Option 1: static + JSON feed)

**Why fourth:** first useful operator surface. Watcher works without it but visibility makes it daily-usable. Major version because new surface.

**Deliverables:**
- Pick one of P1/P2/P3 prototype (operator chooses). Productionize.
- Watcher writes `dashboard/data/status.json` on every tick.
- rsync hook in deploy.sh syncs `dashboard/static/` + `dashboard/data/` to the Proxmox LXC.
- LXC nginx serves at `shipwatch.phalanxmadrone.com` (or chosen subdomain).
- Empty state graceful (no active sessions).

**Tier:** T2 — new surface, three review framings (UX, data fidelity, edge cases).

### 2.1.0 — Audit trail + rollback

**Why fifth:** auto-promote has shipped without a safety net. Before we trust it with more cycles, it needs a log + revert path.

**Deliverables:**
- Every promoted action writes to `~/.shipwatch/audit.jsonl` (append-only) with timestamp, hypothesis, action_type, before/after values.
- `shipwatch revert <action_id>` command flips the action back (whitelisted actions only).
- Dashboard surfaces the audit log + revert button.

**Tier:** T2. ~80 LoC + dashboard integration.

### 2.2.0 — Opt-out UX

**Why sixth:** today opt-outs require hand-editing a marker file. Dashboard button is quality-of-life.

**Deliverables:**
- Dashboard "opt-out" button on each hypothesis row.
- POSTs to a simple endpoint (or writes via rsync trigger) that creates the opt-out marker.
- Marker surfaces on dashboard so operator remembers what's opted-out.

**Tier:** T1. ~30 LoC.

### 3.0.0 — Service architecture (Option 1 → Option 2)

**Why seventh:** static + JSON feed has a latency floor (sync interval). Once dashboard actions (rollback, opt-out, manual promote) become routine, the round-trip through file system + rsync becomes painful. Promote to FastAPI service.

**Deliverables:**
- FastAPI service in `~/Code/shipwatch/src/api/`.
- sqlite for state (replaces ad-hoc JSON).
- Frontend points at `/api/*` on the same domain (LXC handles routing).
- Migration: `status.json` becomes a generated artifact (cached snapshot) for backward compatibility.

**Tier:** T2-DB. New persistence layer.

### 3.1.0 — Cross-deploy dedup

**Why eighth:** when v4.7.18 ships, the v4.7.17.2 cool_high_adjustment hypothesis is superseded. Shouldn't double-count promotions across versions watching the same entity.

**Deliverables:**
- Hypothesis-superseded marker in YAML or auto-detected by entity+attribute match.
- Older session marked "superseded by v4.7.18" and frozen.

**Tier:** T2. ~50 LoC.

### 3.2.0 — Multi-query correlation

**Why ninth:** v4.7.18 H4-style hypotheses (counter increments AND weather condition same day) currently can't be expressed in single-entity YAML. Needs a `correlation:` clause.

**Deliverables:**
- YAML `correlation:` clause that joins two queries by timestamp before evaluation.
- Examples: "counter > 0 AND today's forecast >= 90°F."

**Tier:** T2. ~70 LoC. Lower urgency.

---

## 5. Acceptance criteria for the spinoff cycle itself (M1-M13)

- **Verify:** `~/Code/shipwatch/` exists with the file layout in §2.
- **Verify:** `cd ~/Code/shipwatch && ./scripts/deploy.sh 1.1.0 ...` runs without error and tags + pushes.
- **Verify:** GitHub repo `shipwatch` exists with v1.0.0 + v1.1.0 tags.
- **Verify:** Gitea mirror exists.
- **Verify:** URA `.claude/agents/ura-shipwatch.md` stub redirects (`Moved to ~/Code/shipwatch/agents/watcher.md`).
- **Verify:** URA CLAUDE.md mentions Shipwatch as sibling project.
- **Live:** Run watcher manually against URA — it reads URA READMEs successfully via `projects.yaml`.

---

## 6. Out of scope

- v4.7.18 build itself (separate planning doc at `PLANNING_v4.7.18_dpm_drift_guard_and_cleanup.md`).
- URA v4.7.17.2 deploy (separate operator action; not Shipwatch-dependent).
- Shipwatch dashboard pixel-perfect design (handled in Cycle 2.0.0).

---

## 7. Open questions for operator review

1. **Subdomain:** `shipwatch.phalanxmadrone.com`? Or path under existing URA dashboard domain?
2. **Gitea path:** `homelab/shipwatch` or different?
3. **First production project to onboard after URA:** ura-dashboard-pwa (already exists) or wait until shipwatch hits 2.0?
4. **Should `projects.yaml` live in the repo (committed) or in `~/.shipwatch/` (user-local)?** Recommend user-local to avoid leaking HA tokens / project paths.
5. **Does the operator want `shipwatch` Claude Code agent to be a `claude/agents/` entry in EACH project's `.claude/`, or a global agent in `~/.claude/agents/`?** Recommend global — invokable from any project's terminal.

---

## 8. Recall

- "Resume Shipwatch spinoff" — pick up at M1.
- "Resume Shipwatch 1.2.0" — deploy.sh integration build (after spinoff completes).
- "Shipwatch roadmap" — references this doc.
